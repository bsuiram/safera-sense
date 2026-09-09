"""Fan platform for Safera Sense."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    AUTO_MASK_FAN,
    CMD_MOTOR_AUTO_MODE,
    CMD_MOTOR_RAW_SPEED,
    CMD_MOTOR_SPEED_STEP,
    FAN_LEVEL_COUNT,
    FAN_LEVEL_STEP,
    FAN_RAW_SPEED_MAX,
)
from .coordinator import SaferaConfigEntry, SaferaDataUpdateCoordinator
from .entity import SaferaEntity

_LOGGER = logging.getLogger(__name__)

PRESET_AUTO = "Auto"
PRESET_MANUAL = "Manual"


def preset_name(level: int) -> str:
    """Name of the preset mode that selects a given hood level."""
    return f"Preset {level}"


# Off is deliberately absent: Home Assistant's convention is that off is the
# power button, not a preset. The Fan mode select carries an Off position for
# anyone who wants the app's column verbatim.
PRESET_LEVELS = [preset_name(n) for n in range(1, FAN_LEVEL_COUNT + 1)]
PRESET_MODES = [PRESET_AUTO, *PRESET_LEVELS, PRESET_MANUAL]


def raw_to_percentage(raw: int) -> int:
    """Motor duty as a percentage of full scale."""
    return round(raw * 100 / FAN_RAW_SPEED_MAX)


def percentage_to_raw(percentage: int) -> int:
    """Percentage back to the 0-255 the raw speed command takes."""
    return max(0, min(FAN_RAW_SPEED_MAX, round(percentage * FAN_RAW_SPEED_MAX / 100)))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SaferaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the hood fan."""
    async_add_entities([SaferaFan(entry.runtime_data)])


class SaferaFan(SaferaEntity, FanEntity):
    """The hood's extraction fan.

    Two commands drive this motor and they are mutually exclusive, so the entity
    uses both and is explicit about the trade:

    * ``CMD_MOTOR_SPEED_STEP`` selects one of the hood's four levels. Byte 56,
      the hood's own level index, tracks it, so the panel and the automatic mode
      stay in step — but only four speeds exist.
    * ``CMD_MOTOR_RAW_SPEED`` sets any duty from 0-255. Byte 57 reports it back
      exactly, but **byte 56 is left untouched**: the hood's level index keeps
      whatever it last said, so it goes stale rather than blank.

    Preset modes go through the step command, the percentage slider through the
    raw one. That makes any speed reachable — including everything between level
    4 (55% duty on this hood) and boost (100%), which the hood's own controls
    cannot select — at the cost of the hood losing track while the slider is in
    use. Selecting a preset again puts it back.

    ``percentage`` is byte 57, the real motor duty, not a position in a list of
    levels. The hood's four levels are 9%, 18%, 39% and 55% here, so reporting
    level 1 as "25%" was wrong by nearly a factor of three.
    """

    _attr_name = "Fan"
    _attr_preset_modes = PRESET_MODES
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: SaferaDataUpdateCoordinator) -> None:
        """Initialise the fan."""
        super().__init__(coordinator, "fan")

    @property
    def _level(self) -> int | None:
        """The hood's own level index, byte 56. 0 while a raw speed is set."""
        level = self.coordinator.data.fan
        if level is None:
            return None
        return min(level, FAN_LEVEL_COUNT)

    @property
    def is_on(self) -> bool | None:
        """Whether the motor is turning, from byte 57."""
        speed = self.coordinator.data.fan_speed
        if speed is None:
            return None
        return speed > 0

    @property
    def percentage(self) -> int | None:
        """Actual motor duty as a percentage, from byte 57."""
        speed = self.coordinator.data.fan_speed
        if speed is None:
            return None
        return raw_to_percentage(speed)

    @property
    def preset_mode(self) -> str | None:
        """Auto, one of the hood's levels, or Manual for a raw speed.

        Auto wins over a level: the hood can be armed and running at once, and
        "the hood is deciding" is the more useful thing to say.

        Manual cannot be read off byte 56, because a raw speed command leaves
        that byte stale rather than clearing it — a hood at 70% still reports
        "level 4". ``coordinator.fan_is_manual`` compares the actual duty with
        the duty stored for that level instead, which is the only way to tell
        the two apart.
        """
        data = self.coordinator.data
        if data.auto_flags is None or data.fan_speed is None:
            return None
        if data.auto_flags & AUTO_MASK_FAN:
            return PRESET_AUTO
        if not data.fan_speed:
            return None
        if self.coordinator.fan_is_manual:
            return PRESET_MANUAL
        level = self._level
        if level:
            return preset_name(level)
        # Running, not at a known level, and the settings block has not been
        # read yet, so Manual is the only honest answer.
        return PRESET_MANUAL

    async def _async_select_level(self, level: int) -> None:
        """Apply one of the hood's own speed levels."""
        if not 0 <= level <= FAN_LEVEL_COUNT:
            raise HomeAssistantError(
                f"Fan level {level} is out of range; the hood has {FAN_LEVEL_COUNT}"
            )
        await self.coordinator.async_send_command(
            CMD_MOTOR_SPEED_STEP, level * FAN_LEVEL_STEP
        )

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the motor duty directly. 0 stops it.

        Byte 56 is not updated by this command, so the hood's level index goes
        stale until a preset is selected again. That is why Manual is detected
        by comparing the actual duty against the level's stored duty rather than
        by reading byte 56.
        """
        if percentage == 0:
            await self._async_select_level(0)
            return
        await self.coordinator.async_send_command(
            CMD_MOTOR_RAW_SPEED, percentage_to_raw(percentage)
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Arm the hood's automatic mode, pick a level, or resume manual speed."""
        if preset_mode == PRESET_AUTO:
            await self.coordinator.async_send_command(CMD_MOTOR_AUTO_MODE, 1)
            return
        if preset_mode == PRESET_MANUAL:
            speed = self.coordinator.last_manual_fan_speed
            if not speed:
                raise HomeAssistantError(
                    "No manual speed to resume; set one with the speed slider first"
                )
            await self.coordinator.async_send_command(CMD_MOTOR_RAW_SPEED, speed)
            return
        if preset_mode in PRESET_LEVELS:
            await self._async_select_level(PRESET_LEVELS.index(preset_mode) + 1)
            return
        raise HomeAssistantError(f"Unknown preset mode: {preset_mode}")

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Start the fan.

        A bare turn-on picks level 2 rather than full speed: a cooker hood at
        100% is loud, and the hood's own controls start low.
        """
        if preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)
            return
        if percentage is not None:
            await self.async_set_percentage(percentage)
            return
        await self._async_select_level(min(2, FAN_LEVEL_COUNT))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the fan.

        Through the step command, so the hood's level index lands on 0 as well
        rather than being left stale at whatever a raw speed left behind.
        """
        await self._async_select_level(0)
