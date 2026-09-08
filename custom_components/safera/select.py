"""Select platform: the light's mode picker, and settings with fixed choices."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    AUTO_MASK_LIGHT,
    CMD_LIGHT_AUTO_MODE,
    CMD_LIGHT_PRESET,
    COOKER_WIDTHS,
    LIGHT_PRESET_COUNT,
    LIGHT_PRESET_OFF,
    LIGHT_PRESET_STEP,
    SETTINGS_COOKER_WIDTH,
)
from .coordinator import SaferaConfigEntry, SaferaDataUpdateCoordinator
from .entity import SaferaEntity

_LOGGER = logging.getLogger(__name__)

LIGHT_MODE_OFF = "Off"
LIGHT_MODE_AUTO = "Auto"


def light_mode_preset(preset: int) -> str:
    """Name of the option that selects a given preset."""
    return f"Preset {preset}"


# The app's light column, in the same order: OFF, presets 1-3, Auto.
LIGHT_MODES = [
    LIGHT_MODE_OFF,
    *(light_mode_preset(n) for n in range(1, LIGHT_PRESET_COUNT + 1)),
    LIGHT_MODE_AUTO,
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SaferaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the light mode picker and the settings selects."""
    coordinator = entry.runtime_data
    async_add_entities(
        [SaferaLightModeSelect(coordinator), SaferaCookerWidthSelect(coordinator)]
    )


class SaferaLightModeSelect(SaferaEntity, SelectEntity):
    """The light column from the Safera app: Off, three presets, Auto.

    This exists because Home Assistant **hides a light's ``effect`` attribute
    while the light is off**. Auto is exposed on the light entity too, but the
    lamp is off most of the time, and in that state the effect is invisible and
    unselectable — you could not see whether the hood's light automation was
    armed, let alone arm it. A select has no such rule, so this is always
    readable and always selectable.

    Deliberately not an ``EntityCategory``: this is a control, unlike the
    cooker width below it.
    """

    _attr_name = "Light mode"
    _attr_options = LIGHT_MODES

    def __init__(self, coordinator: SaferaDataUpdateCoordinator) -> None:
        """Initialise the light mode select."""
        super().__init__(coordinator, "light_mode")

    @property
    def current_option(self) -> str | None:
        """Auto when armed, otherwise the preset in byte 53, otherwise Off."""
        data = self.coordinator.data
        if data.auto_flags is None or data.light is None:
            return None
        # Auto wins when both apply: the hood can be armed and lit at once, and
        # "the hood is deciding" is the more useful thing to show.
        if data.auto_flags & AUTO_MASK_LIGHT:
            return LIGHT_MODE_AUTO
        if 1 <= data.light <= LIGHT_PRESET_COUNT:
            return light_mode_preset(data.light)
        return LIGHT_MODE_OFF

    async def async_select_option(self, option: str) -> None:
        """Apply a preset, switch the lamp off, or hand back to the hood."""
        if option == LIGHT_MODE_AUTO:
            await self.coordinator.async_send_command(CMD_LIGHT_AUTO_MODE, 1)
            return
        if option == LIGHT_MODE_OFF:
            param = LIGHT_PRESET_OFF
        else:
            # Off sits at index 0, so an option's index is its preset number.
            preset = LIGHT_MODES.index(option)
            param = preset * LIGHT_PRESET_STEP
        await self.coordinator.async_send_command(CMD_LIGHT_PRESET, param)


class SaferaCookerWidthSelect(SaferaEntity, SelectEntity):
    """The cooker's width, from the fixed list the Safera app offers.

    A select rather than a number because the app offers 50 to 100 cm in 10 cm
    steps rather than free entry, and there is no reason to let Home Assistant
    write a width the hood was never designed to be told.
    """

    _attr_name = "Cooker width"
    # A stored setting in the hood's settings block, not something to operate.
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = [f"{width}" for width in COOKER_WIDTHS]
    _attr_unit_of_measurement = None

    def __init__(self, coordinator: SaferaDataUpdateCoordinator) -> None:
        """Initialise the select."""
        super().__init__(coordinator, "cooker_width")

    @property
    def available(self) -> bool:
        """Needs the settings block as well as a live connection."""
        return super().available and self.coordinator.settings is not None

    @property
    def current_option(self) -> str | None:
        """Stored width, or None if it is not one of the offered values."""
        settings = self.coordinator.settings
        if settings is None or SETTINGS_COOKER_WIDTH >= len(settings):
            return None
        stored = str(settings[SETTINGS_COOKER_WIDTH])
        return stored if stored in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        """Store the chosen width."""
        await self.coordinator.async_write_setting(
            SETTINGS_COOKER_WIDTH, int(option)
        )
