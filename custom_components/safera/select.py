"""Select platform: the hood's two mode pickers, and fixed-choice settings."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    AUTO_MASK_FAN,
    AUTO_MASK_LIGHT,
    CMD_LIGHT_AUTO_MODE,
    CMD_LIGHT_PRESET,
    CMD_MOTOR_AUTO_MODE,
    CMD_MOTOR_SPEED_STEP,
    COOKER_WIDTHS,
    FAN_LEVEL_COUNT,
    FAN_LEVEL_STEP,
    LIGHT_PRESET_COUNT,
    LIGHT_PRESET_STEP,
    SETTINGS_COOKER_WIDTH,
)
from .coordinator import SaferaConfigEntry, SaferaData, SaferaDataUpdateCoordinator
from .entity import SaferaEntity

_LOGGER = logging.getLogger(__name__)

MODE_OFF = "Off"
MODE_AUTO = "Auto"


def mode_preset(preset: int) -> str:
    """Name of the option that selects a given preset."""
    return f"Preset {preset}"


def mode_options(count: int) -> list[str]:
    """The app's column for a control with ``count`` presets: Off, 1..n, Auto."""
    return [MODE_OFF, *(mode_preset(n) for n in range(1, count + 1)), MODE_AUTO]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SaferaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the mode pickers and the settings selects."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            SaferaFanModeSelect(coordinator),
            SaferaLightModeSelect(coordinator),
            SaferaCookerWidthSelect(coordinator),
        ]
    )


class SaferaModeSelect(SaferaEntity, SelectEntity):
    """One of the hood's two columns: Off, numbered presets, Auto.

    The Safera app drives both ventilation and light from a single vertical
    selector, and the two work identically underneath: a command that takes
    ``preset * 30``, a status byte that reports the same encoding back, and a
    bit in byte 60 saying the hood is deciding for itself. Only the constants
    differ, so both are this one class.

    These exist alongside the ``fan`` and ``light`` entities rather than
    replacing them. For the light that is not optional: **Home Assistant hides a
    light's ``effect`` attribute while the light is off**, and this lamp is off
    most of the time, so Auto would be invisible and unselectable in exactly the
    state you want to check it. The fan does not have that problem — its
    ``preset_mode`` shows while it is off — but a matching picker is what the
    app looks like, and an asymmetric pair would be its own kind of confusing.

    Deliberately not an ``EntityCategory``: these are controls.
    """

    _preset_count: int
    _step: int
    _auto_mask: int
    _preset_command: int
    _auto_command: int

    def __init__(self, coordinator: SaferaDataUpdateCoordinator, key: str) -> None:
        """Initialise the mode select."""
        super().__init__(coordinator, key)
        self._attr_options = mode_options(self._preset_count)

    def _current_preset(self, data: SaferaData) -> int | None:
        """The preset the hood reports, from its own status byte."""
        raise NotImplementedError

    @property
    def current_option(self) -> str | None:
        """Auto when armed, otherwise the reported preset, otherwise Off."""
        data = self.coordinator.data
        preset = self._current_preset(data)
        if data.auto_flags is None or preset is None:
            return None
        # Auto wins when both apply: the hood can be armed and running at the
        # same time, and "the hood is deciding" is the more useful thing to say.
        if data.auto_flags & self._auto_mask:
            return MODE_AUTO
        if 1 <= preset <= self._preset_count:
            return mode_preset(preset)
        return MODE_OFF

    async def async_select_option(self, option: str) -> None:
        """Apply a preset, stop, or hand control back to the hood."""
        if option == MODE_AUTO:
            await self.coordinator.async_send_command(self._auto_command, 1)
            return
        # Off sits at index 0, so an option's index is its preset number.
        preset = 0 if option == MODE_OFF else self._attr_options.index(option)
        await self.coordinator.async_send_command(
            self._preset_command, preset * self._step
        )


class SaferaFanModeSelect(SaferaModeSelect):
    """The app's ventilation column: Off, levels 1-4, Auto.

    Boost is not here because the hood will not select it over BLE — params
    above the top level are silently ignored, and the app's own picker does not
    offer it either. It is a nine-minute temporary mode started by long-pressing
    the plus button on the hood.
    """

    _attr_name = "Fan mode"
    _preset_count = FAN_LEVEL_COUNT
    _step = FAN_LEVEL_STEP
    _auto_mask = AUTO_MASK_FAN
    _preset_command = CMD_MOTOR_SPEED_STEP
    _auto_command = CMD_MOTOR_AUTO_MODE

    def __init__(self, coordinator: SaferaDataUpdateCoordinator) -> None:
        """Initialise the fan mode select."""
        super().__init__(coordinator, "fan_mode")

    def _current_preset(self, data: SaferaData) -> int | None:
        """Byte 56, the hood's own level index."""
        return data.fan


class SaferaLightModeSelect(SaferaModeSelect):
    """The app's light column: Off, presets 1-3, Auto."""

    _attr_name = "Light mode"
    _preset_count = LIGHT_PRESET_COUNT
    _step = LIGHT_PRESET_STEP
    _auto_mask = AUTO_MASK_LIGHT
    _preset_command = CMD_LIGHT_PRESET
    _auto_command = CMD_LIGHT_AUTO_MODE

    def __init__(self, coordinator: SaferaDataUpdateCoordinator) -> None:
        """Initialise the light mode select."""
        super().__init__(coordinator, "light_mode")

    def _current_preset(self, data: SaferaData) -> int | None:
        """Byte 53, the light preset."""
        return data.light


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
