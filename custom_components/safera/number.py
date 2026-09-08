"""Number platform for Safera Sense preset settings."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import (
    EntityCategory,
    PERCENTAGE,
    UnitOfLength,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    FAN_PRESET_MAX,
    LIGHT_KELVIN_BASE,
    LIGHT_KELVIN_PER_STEP,
    LIGHT_MAX_KELVIN,
    LIGHT_MIN_KELVIN,
    LIGHT_PRESET_BRIGHTNESS_MAX,
    SETTINGS_LIGHT_BRIGHTNESS,
    SETTINGS_LIGHT_COLOR,
    SETTINGS_MOTOR1_PRESETS,
    SETTINGS_SENSOR_HEIGHT,
    SETTINGS_VENT_SENSITIVITY,
)
from .coordinator import SaferaConfigEntry, SaferaDataUpdateCoordinator
from .entity import SaferaEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class SaferaNumberDescription(NumberEntityDescription):
    """One editable byte of the hood's settings block."""

    offset: int
    to_raw: Callable[[float], int]
    from_raw: Callable[[int], float]
    # Everything on this platform is stored configuration rather than a control,
    # so default the whole table to CONFIG instead of repeating it fourteen
    # times. A description can still override it if a settings byte ever turns
    # out to be something you operate day to day.
    entity_category: EntityCategory | None = EntityCategory.CONFIG


def _pct_to_raw(scale: int) -> Callable[[float], int]:
    return lambda value: max(0, min(scale, round(value * scale / 100)))


def _raw_to_pct(scale: int) -> Callable[[int], float]:
    return lambda raw: round(raw * 100 / scale)


def _kelvin_to_raw(value: float) -> int:
    raw = round((value - LIGHT_KELVIN_BASE) / LIGHT_KELVIN_PER_STEP)
    return max(0, min(255, raw))


def _raw_to_kelvin(raw: int) -> float:
    return LIGHT_KELVIN_BASE + raw * LIGHT_KELVIN_PER_STEP


def _fan_preset(index: int, label: str) -> SaferaNumberDescription:
    """Motor 1 ventilation preset. Index 0 is level 0, 5 is boost."""
    return SaferaNumberDescription(
        key=f"fan_preset_{label.lower()}",
        name=f"Fan preset {label}",
        offset=SETTINGS_MOTOR1_PRESETS + index,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        to_raw=_pct_to_raw(FAN_PRESET_MAX),
        from_raw=_raw_to_pct(FAN_PRESET_MAX),
    )


# Every number here writes a byte into the hood's 200-byte settings block, so
# they are device configuration rather than day-to-day controls. Categorising
# them keeps the device page's Controls group to the five things you actually
# operate — light, fan, the two auto switches and the filter reset — and gives
# the settings a Configuration group of their own.
NUMBERS: tuple[SaferaNumberDescription, ...] = (
    # How eagerly the hood ramps the fan while cooking. Stored as a plain
    # percentage with no scaling; the app calls 50 the default.
    SaferaNumberDescription(
        key="ventilation_sensitivity",
        name="Ventilation sensitivity",
        offset=SETTINGS_VENT_SENSITIVITY,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        to_raw=lambda value: max(0, min(100, round(value))),
        from_raw=lambda raw: raw,
    ),
    # Mounting geometry, both plain centimetres in the settings block. Box mode
    # rather than a slider: these are typed-in dimensions, not things to drag.
    SaferaNumberDescription(
        key="sensor_height",
        name="Sensor height",
        offset=SETTINGS_SENSOR_HEIGHT,
        native_min_value=10,
        native_max_value=200,
        native_step=1,
        native_unit_of_measurement=UnitOfLength.CENTIMETERS,
        device_class=NumberDeviceClass.DISTANCE,
        mode=NumberMode.BOX,
        to_raw=lambda value: max(0, min(255, round(value))),
        from_raw=lambda raw: raw,
    ),
    _fan_preset(1, "1"),
    _fan_preset(2, "2"),
    _fan_preset(3, "3"),
    _fan_preset(4, "4"),
    _fan_preset(5, "Boost"),
    *(
        SaferaNumberDescription(
            key=f"light_preset_{n}_brightness",
            # Named type-first so the three brightnesses and the three colours
            # sort into two blocks in the device page's Configuration group,
            # instead of interleaving as "preset 1 brightness, preset 1 colour,
            # preset 2 brightness, ...". The keys are unchanged, so entity ids
            # and history stay put.
            name=f"Light brightness preset {n}",
            offset=SETTINGS_LIGHT_BRIGHTNESS + n - 1,
            native_min_value=0,
            native_max_value=100,
            native_step=1,
            native_unit_of_measurement=PERCENTAGE,
            mode=NumberMode.SLIDER,
            to_raw=_pct_to_raw(LIGHT_PRESET_BRIGHTNESS_MAX),
            from_raw=_raw_to_pct(LIGHT_PRESET_BRIGHTNESS_MAX),
        )
        for n in (1, 2, 3)
    ),
    *(
        SaferaNumberDescription(
            key=f"light_preset_{n}_color",
            name=f"Light color preset {n}",
            offset=SETTINGS_LIGHT_COLOR + n - 1,
            native_min_value=LIGHT_MIN_KELVIN,
            native_max_value=LIGHT_MAX_KELVIN,
            native_step=LIGHT_KELVIN_PER_STEP,
            native_unit_of_measurement=UnitOfTemperature.KELVIN,
            device_class=NumberDeviceClass.TEMPERATURE,
            mode=NumberMode.SLIDER,
            to_raw=_kelvin_to_raw,
            from_raw=_raw_to_kelvin,
        )
        for n in (1, 2, 3)
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SaferaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the preset number entities."""
    async_add_entities(
        SaferaPresetNumber(entry.runtime_data, description)
        for description in NUMBERS
    )


class SaferaPresetNumber(SaferaEntity, NumberEntity):
    """One byte of the settings block, exposed as an adjustable number.

    These are the same presets the Safera app edits under Cooker Hood Settings.
    They live in the settings block rather than the notify stream, so the value
    comes from a cached read refreshed once per connection and after each write.
    """

    entity_description: SaferaNumberDescription

    def __init__(
        self,
        coordinator: SaferaDataUpdateCoordinator,
        description: SaferaNumberDescription,
    ) -> None:
        """Initialise the number."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Needs the settings block as well as a live connection."""
        return super().available and self.coordinator.settings is not None

    @property
    def native_value(self) -> float | None:
        """Current value, converted from the stored byte."""
        settings = self.coordinator.settings
        if settings is None or self.entity_description.offset >= len(settings):
            return None
        return self.entity_description.from_raw(
            settings[self.entity_description.offset]
        )

    async def async_set_native_value(self, value: float) -> None:
        """Write the byte, which also refreshes the cached block."""
        await self.coordinator.async_write_setting(
            self.entity_description.offset, self.entity_description.to_raw(value)
        )
