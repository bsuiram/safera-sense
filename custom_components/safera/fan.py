"""Fan platform for Safera Sense."""

from __future__ import annotations

import logging
import math
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from .const import (
    CMD_MOTOR_SPEED_STEP,
    FAN_LEVEL_COUNT,
    FAN_LEVEL_PARAM_MAX,
    FAN_LEVEL_STEP,
)
from .coordinator import SaferaConfigEntry, SaferaDataUpdateCoordinator
from .entity import SaferaEntity

_LOGGER = logging.getLogger(__name__)

# Levels 1..FAN_LEVEL_COUNT, in the order Home Assistant should step through
# them. Level 0 is "off" and is not a member.
_LEVELS = list(range(1, FAN_LEVEL_COUNT + 1))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SaferaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the hood fan."""
    async_add_entities([SaferaFan(entry.runtime_data)])


class SaferaFan(SaferaEntity, FanEntity):
    """The hood's extraction fan, driven by the hood's own speed levels.

    This deliberately uses ``CMD_MOTOR_SPEED_STEP`` rather than the raw
    0-255 ``CMD_MOTOR_RAW_SPEED``. Both move the motor, but only the step
    command keeps the hood's own controller in the loop: it takes the level
    scaled by 30, which is the exact encoding byte 56 reports back.

    Driving the raw command instead moves the motor while byte 56 stays at 0,
    because the hood never learns the speed changed — so the ``fan_level``
    sensor, the hood's panel and its automatic mode all disagree with reality
    for as long as Home Assistant is in control. That was the old behaviour
    here, and the sensor reading 0 mid-run was written off as "not a bug".

    Byte 57, the true motor speed in raw units, is still read and still exposed
    as its own sensor. It remains the honest answer to "how fast is it actually
    turning", and it is used here as a fallback for on/off.

    Four levels, not five. Measured 2026-09-08: params 30/60/90/120 work and
    produce this hood's stored preset speeds, while 150, 180 and 210 are all
    silently ignored — the fan simply stays where it was. Boost is not reachable
    through this command despite having a preset slot of its own.
    """

    _attr_name = "Fan"
    _attr_speed_count = FAN_LEVEL_COUNT
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: SaferaDataUpdateCoordinator) -> None:
        """Initialise the fan."""
        super().__init__(coordinator, "fan")

    @property
    def _level(self) -> int | None:
        """Current speed level from byte 56, clamped to the levels we know."""
        level = self.coordinator.data.fan
        if level is None:
            return None
        return min(level, FAN_LEVEL_COUNT)

    @property
    def is_on(self) -> bool | None:
        """Whether the motor is turning.

        Byte 56 is the level the hood believes it is at; byte 57 is the motor
        actually moving. Either being nonzero means on — during a ramp, and
        while the hood's automatic mode is driving things, they briefly
        disagree, and reporting off while the motor spins is the worse error.
        """
        level = self._level
        speed = self.coordinator.data.fan_speed
        if level is None and speed is None:
            return None
        return bool(level) or bool(speed)

    @property
    def percentage(self) -> int | None:
        """Current level as a percentage of the five available levels."""
        level = self._level
        if level is None:
            return None
        if level <= 0:
            # The hood's own controller can be running the motor at a speed it
            # has no level for. Report the lowest level rather than 0%, which
            # Home Assistant reads as off and would contradict is_on.
            speed = self.coordinator.data.fan_speed
            if speed:
                return ordered_list_item_to_percentage(_LEVELS, _LEVELS[0])
            return 0
        return ordered_list_item_to_percentage(_LEVELS, level)

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed level. 0 stops the motor."""
        if percentage == 0:
            level = 0
        else:
            level = percentage_to_ordered_list_item(_LEVELS, percentage)
        param = level * FAN_LEVEL_STEP
        # The hood drops an out-of-range parameter on the floor without saying
        # so, which would leave the fan at its previous speed and the user with
        # no indication anything failed. Refuse loudly instead.
        if param > FAN_LEVEL_PARAM_MAX:
            raise HomeAssistantError(
                f"Fan level {level} is out of range; the hood accepts 0-"
                f"{FAN_LEVEL_COUNT}"
            )
        await self.coordinator.async_send_command(CMD_MOTOR_SPEED_STEP, param)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Start the fan, defaulting to the middle level.

        Full speed is a poor default for a cooker hood — it is loud, and the
        hood's own controls start low.
        """
        if percentage is None:
            percentage = ordered_list_item_to_percentage(
                _LEVELS, _LEVELS[math.floor((FAN_LEVEL_COUNT - 1) / 2)]
            )
        await self.async_set_percentage(percentage)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the fan."""
        await self.async_set_percentage(0)
