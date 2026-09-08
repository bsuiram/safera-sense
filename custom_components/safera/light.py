"""Light platform for Safera Sense."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    AUTO_MASK_LIGHT,
    CMD_LIGHT_AUTO_MODE,
    CMD_LIGHT_BRIGHTNESS,
    CMD_LIGHT_COLOR,
    CMD_LIGHT_PRESET,
    LIGHT_MAX_KELVIN,
    LIGHT_MIN_KELVIN,
    LIGHT_PRESET_COUNT,
    LIGHT_PRESET_DEFAULT,
    LIGHT_PRESET_OFF,
    LIGHT_PRESET_PARAM_MAX,
    LIGHT_PRESET_STEP,
)
from .coordinator import SaferaConfigEntry, SaferaDataUpdateCoordinator
from .entity import SaferaEntity

_LOGGER = logging.getLogger(__name__)

EFFECT_AUTO = "Auto"


def preset_effect(preset: int) -> str:
    """Name of the effect that selects a given preset."""
    return f"Preset {preset}"


# Mirrors the app's light column: OFF, then presets 1-3, then Auto. Off is the
# entity being off rather than an effect, so it is not listed here.
PRESET_EFFECTS = [preset_effect(n) for n in range(1, LIGHT_PRESET_COUNT + 1)]
EFFECTS = [*PRESET_EFFECTS, EFFECT_AUTO]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SaferaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the hood light."""
    async_add_entities([SaferaLight(entry.runtime_data)])


class SaferaLight(SaferaEntity, LightEntity):
    """The hood's lamp, modelled on the Safera app's light column.

    The app offers OFF, three presets and Auto in one selector, so the presets
    and Auto are exposed as effects. Brightness and colour stay available as
    well: the app has its own colour control, byte 54 and byte 55 report both
    back exactly, and a Home Assistant light that cannot be dimmed would be a
    poor citizen.

    ``CMD_LIGHT_PRESET`` takes **preset * 30**, not the preset index. Measured
    2026-09-08: 30, 60 and 90 produced this hood's three stored presets exactly,
    while 1, 2 and 3 all lit the lamp at the same fallback. Sending the index
    was the old behaviour here, and ``light.py`` overwriting brightness and
    colour immediately afterwards is why nobody noticed.

    Selecting a preset applies the hood's stored brightness and colour for it,
    so a preset deliberately does **not** re-apply remembered values. Setting
    brightness or colour explicitly still overrides, exactly as the app allows.
    """

    _attr_name = "Light"
    _attr_color_mode = ColorMode.COLOR_TEMP
    _attr_supported_color_modes = {ColorMode.COLOR_TEMP}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = EFFECTS
    _attr_min_color_temp_kelvin = LIGHT_MIN_KELVIN
    _attr_max_color_temp_kelvin = LIGHT_MAX_KELVIN

    def __init__(self, coordinator: SaferaDataUpdateCoordinator) -> None:
        """Initialise the light."""
        super().__init__(coordinator, "light")
        # Brightness and colour both read 0 while the lamp is off, so the last
        # non-zero values are kept to restore them when switching back on.
        self._last_brightness: int | None = None
        self._last_color: int | None = None
        # Which preset a bare turn-on should use, remembered across an off/on
        # cycle so the lamp comes back the way it went out.
        self._last_preset: int = LIGHT_PRESET_DEFAULT

    @property
    def _preset(self) -> int | None:
        """Current preset from byte 53, 0 when the lamp is off."""
        return self.coordinator.data.light

    @property
    def _auto(self) -> bool | None:
        flags = self.coordinator.data.auto_flags
        if flags is None:
            return None
        return bool(flags & AUTO_MASK_LIGHT)

    @property
    def is_on(self) -> bool | None:
        """Whether the lamp is lit, from byte 53."""
        preset = self._preset
        if preset is None:
            return None
        return preset > 0

    @property
    def effect(self) -> str | None:
        """The active preset, or Auto.

        Auto wins when both apply: the hood can be armed and lit at the same
        time, and "the hood is deciding" is the more useful thing to show.
        """
        if self._auto:
            return EFFECT_AUTO
        preset = self._preset
        if not preset or preset > LIGHT_PRESET_COUNT:
            return None
        return preset_effect(preset)

    @property
    def brightness(self) -> int | None:
        """Brightness reported by the hood, byte 54."""
        if not self.is_on:
            return None
        return self.coordinator.data.light_brightness

    @property
    def color_temp_kelvin(self) -> int | None:
        """Colour reported by the hood, byte 55, mapped onto Kelvin.

        The hood has no notion of Kelvin — byte 55 is a 0-255 warm-to-cool
        slider — but the mapping is measured rather than assumed: the app showed
        2790 K, 2970 K and 2943 K for stored bytes 10, 30 and 27, an exact fit
        for ``2700 + byte * 9``.
        """
        if not self.is_on:
            return None
        raw = self.coordinator.data.light_color
        if raw is None:
            return None
        span = LIGHT_MAX_KELVIN - LIGHT_MIN_KELVIN
        return round(LIGHT_MIN_KELVIN + (raw / 255) * span)

    def _kelvin_to_raw(self, kelvin: int) -> int:
        """Map a Kelvin value back onto the hood's 0-255 colour slider."""
        span = LIGHT_MAX_KELVIN - LIGHT_MIN_KELVIN
        raw = round((kelvin - LIGHT_MIN_KELVIN) / span * 255)
        return max(0, min(255, raw))

    async def _async_select_preset(self, preset: int) -> None:
        """Apply one of the hood's stored light presets."""
        param = preset * LIGHT_PRESET_STEP
        # An out-of-range parameter is dropped without complaint, which would
        # leave the lamp as it was and give no clue why. Refuse instead.
        if not 0 <= param <= LIGHT_PRESET_PARAM_MAX:
            raise HomeAssistantError(
                f"Light preset {preset} is out of range; the hood has "
                f"{LIGHT_PRESET_COUNT}"
            )
        await self.coordinator.async_send_command(CMD_LIGHT_PRESET, param)
        if preset:
            self._last_preset = preset

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Switch the lamp on.

        With an effect, that is the hood's own preset or its automatic mode.
        Otherwise the last preset used is re-selected, and any brightness or
        colour given explicitly is applied on top.
        """
        effect = kwargs.get(ATTR_EFFECT)

        if effect == EFFECT_AUTO:
            await self.coordinator.async_send_command(CMD_LIGHT_AUTO_MODE, 1)
            return

        if effect in PRESET_EFFECTS:
            await self._async_select_preset(PRESET_EFFECTS.index(effect) + 1)
        else:
            await self._async_select_preset(self._last_preset)

        # A preset carries its own brightness and colour, so only override when
        # the caller actually asked for something.
        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            await self.coordinator.async_send_command(
                CMD_LIGHT_BRIGHTNESS, int(brightness)
            )
            self._last_brightness = int(brightness)

        if (kelvin := kwargs.get(ATTR_COLOR_TEMP_KELVIN)) is not None:
            color = self._kelvin_to_raw(int(kelvin))
            await self.coordinator.async_send_command(CMD_LIGHT_COLOR, color)
            self._last_color = color

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch the lamp off, remembering how it was lit.

        Brightness 0 is a dim floor rather than off, so this has to go through
        the preset command. Turning the lamp off by hand also disarms the hood's
        light automation, which is the hood's behaviour and not something this
        works around — the alternative would be a lamp that switches itself back
        on a moment later.
        """
        if self.is_on:
            data = self.coordinator.data
            if data.light_brightness:
                self._last_brightness = data.light_brightness
            if data.light_color is not None:
                self._last_color = data.light_color
            if data.light:
                self._last_preset = data.light

        await self._async_select_preset(LIGHT_PRESET_OFF)
