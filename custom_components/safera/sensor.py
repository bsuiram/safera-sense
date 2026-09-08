"""Sensor platform for Safera Sense."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    LIGHT_LUX,
    DEGREE,
    EntityCategory,
    PERCENTAGE,
    UnitOfDensity,
    UnitOfPower,
    UnitOfRatio,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import DEVICE_STATES, DOMAIN, LIGHT_KELVIN_BASE, LIGHT_KELVIN_PER_STEP
from .coordinator import (
    SaferaConfigEntry,
    SaferaDataUpdateCoordinator,
    SaferaData,
    format_sw_version,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class SaferaSensorEntityDescription(SensorEntityDescription):
    """Describes Safera sensor entity."""

    value_fn: Callable[[SaferaDataUpdateCoordinator], StateType | datetime]


SENSORS: tuple[SaferaSensorEntityDescription, ...] = (
    SaferaSensorEntityDescription(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda coordinator: coordinator.data.temperature,
    ),
    SaferaSensorEntityDescription(
        key="heat_index",
        name="Heat Index",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda coordinator: coordinator.data.heat_index,
    ),
    SaferaSensorEntityDescription(
        key="humidity",
        name="Humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda coordinator: coordinator.data.humidity,
    ),
    SaferaSensorEntityDescription(
        key="co2",
        name="CO₂",
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda coordinator: coordinator.data.co2,
    ),
    SaferaSensorEntityDescription(
        key="tvoc",
        name="tVOC",
        device_class=SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS,
        native_unit_of_measurement=UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda coordinator: coordinator.data.tvoc,
    ),
    SaferaSensorEntityDescription(
        key="pm25",
        name="PM2.5",
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda coordinator: coordinator.data.pm25,
    ),
    SaferaSensorEntityDescription(
        key="illuminance",
        name="Ambient light",
        device_class=SensorDeviceClass.ILLUMINANCE,
        native_unit_of_measurement=LIGHT_LUX,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda coordinator: coordinator.data.illuminance,
    ),
    SaferaSensorEntityDescription(
        key="aqi",
        name="Air Quality Index",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda coordinator: coordinator.data.aqi,
    ),
    SaferaSensorEntityDescription(
        key="grease_filter",
        name="Grease Filter",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda coordinator: coordinator.data.grease_filter,
    ),
    SaferaSensorEntityDescription(
        key="light",
        name="Light preset level",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda coordinator: coordinator.data.light,
    ),
    SaferaSensorEntityDescription(
        key="fan",
        # Byte 56, the hood's own level index. The fan entity drives the hood
        # with CMD_MOTOR_SPEED_STEP, which writes this same encoding, so it now
        # tracks Home Assistant's commands as well as the hood's own controls.
        # It used to sit at 0 whenever Home Assistant was driving the motor.
        name="Fan preset level",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda coordinator: coordinator.data.fan,
    ),
    SaferaSensorEntityDescription(
        key="activity",
        name="Activity",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda coordinator: coordinator.data.activity,
    ),
    SaferaSensorEntityDescription(
        key="alarm_level",
        name="Alarm Level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda coordinator: coordinator.data.alarm_level,
    ),
    SaferaSensorEntityDescription(
        key="power",
        name="Power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda coordinator: coordinator.data.power,
    ),
    SaferaSensorEntityDescription(
        key="light_brightness",
        name="Light brightness",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda coordinator: (
            None
            if coordinator.data.light_brightness is None
            else round(coordinator.data.light_brightness * 100 / 255)
        ),
    ),
    SaferaSensorEntityDescription(
        key="light_color_temp",
        name="Light color temperature",
        # Deliberately no device class: SensorDeviceClass.TEMPERATURE would let
        # Home Assistant convert this into the user's preferred temperature
        # unit, turning a colour temperature into degrees Celsius.
        native_unit_of_measurement=UnitOfTemperature.KELVIN,
        state_class=SensorStateClass.MEASUREMENT,
        # 0 while the lamp is off, matching the brightness sensor, which reads 0
        # for the same state because byte 54 zeroes out too. None is reserved
        # for "no frame yet" so that genuinely missing data stays distinct from
        # a lamp that is simply off.
        value_fn=lambda coordinator: (
            None
            if coordinator.data.light_raw is None or coordinator.data.light_color is None
            else 0
            if not coordinator.data.light_raw
            else LIGHT_KELVIN_BASE + coordinator.data.light_color * LIGHT_KELVIN_PER_STEP
        ),
    ),
    SaferaSensorEntityDescription(
        key="fan_speed",
        name="Fan speed",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda coordinator: (
            None
            if coordinator.data.fan_speed is None
            else round(coordinator.data.fan_speed * 100 / 255)
        ),
    ),
    SaferaSensorEntityDescription(
        key="pitch",
        name="Pitch",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: coordinator.data.pitch,
    ),
    SaferaSensorEntityDescription(
        key="roll",
        name="Roll",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: coordinator.data.roll,
    ),
    SaferaSensorEntityDescription(
        key="last_ok_press",
        name="Last OK pressed",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda coordinator: coordinator.last_ok_press,
    ),
    SaferaSensorEntityDescription(
        key="device_state",
        name="Device state",
        device_class=SensorDeviceClass.ENUM,
        options=list(DEVICE_STATES.values()),
        value_fn=lambda coordinator: DEVICE_STATES.get(
            coordinator.data.device_state
        ),
    ),
    SaferaSensorEntityDescription(
        key="uptime",
        name="Uptime",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda coordinator: coordinator.data.uptime,
    ),
    # Fields also decoded by crillebaba/safera-sense-ble. All diagnostics: four
    # of them are constant in every frame captured here, and are exposed so a
    # change becomes visible rather than invisible.
    SaferaSensorEntityDescription(
        key="battery",
        name="Battery",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda coordinator: coordinator.data.battery,
    ),
    SaferaSensorEntityDescription(
        key="voc_index",
        name="VOC index",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        # Byte 14 raw, with no scaling. It is a coarse band index derived from
        # tVOC — 16 distinct values from 10 to 25 across 16202 frames, each
        # mapping to a clean tVOC range — but the scale itself is unknown, so
        # inventing a unit would be inventing precision.
        value_fn=lambda coordinator: coordinator.data.voc_index,
    ),
    SaferaSensorEntityDescription(
        key="alarm_status",
        name="Alarm status",
        entity_category=EntityCategory.DIAGNOSTIC,
        # 1 normally; counts down once a second through the pre-alarm buzzer
        # window, then 0 once the cooktop is cut.
        value_fn=lambda coordinator: coordinator.data.alarm_status,
    ),
    SaferaSensorEntityDescription(
        key="sensor_errors",
        name="Sensor errors",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: coordinator.data.sensor_errors,
    ),
    SaferaSensorEntityDescription(
        key="pcu_errors",
        name="PCU errors",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: coordinator.data.pcu_errors,
    ),
    SaferaSensorEntityDescription(
        key="accessories",
        name="Connected accessories",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: coordinator.data.accessories,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SaferaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Safera sensors."""
    _LOGGER.debug("Setting up Safera sensors for entry: %s", entry.entry_id)
    coordinator = entry.runtime_data

    sensors = [SaferaSensor(coordinator, description) for description in SENSORS]
    _LOGGER.debug("Created %d Safera sensor entities", len(sensors))
    async_add_entities(sensors)
    _LOGGER.debug("Added Safera sensor entities to Home Assistant")


class SaferaSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Safera sensor."""

    entity_description: SaferaSensorEntityDescription

    def __init__(
        self,
        coordinator: SaferaDataUpdateCoordinator,
        description: SaferaSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        _LOGGER.debug(
            "Initializing Safera sensor: %s for device %s",
            description.key,
            coordinator.address,
        )
        super().__init__(coordinator)
        self.entity_description = description
        address = coordinator.device_identifier
        self._attr_unique_id = f"{address}_{description.key}"
        # Read from the hood's Device Information Service and cached in the
        # config entry; empty only on the very first run, before the first
        # connection, after which the coordinator updates the registry itself.
        info = coordinator.device_info_values
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(address))},
            name="Safera Sense",
            manufacturer=info.get("manufacturer", "Safera Oy"),
            model=info.get("model", "Sense"),
            serial_number=info.get("serial_number"),
            hw_version=info.get("hw_version"),
            sw_version=format_sw_version(info),
        )

    @property
    def native_value(self) -> StateType | datetime:
        """Return the native value of the sensor."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.device_available
