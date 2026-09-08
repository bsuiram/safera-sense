"""Select platform for Safera Sense settings with fixed choices."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import COOKER_WIDTHS, SETTINGS_COOKER_WIDTH
from .coordinator import SaferaConfigEntry, SaferaDataUpdateCoordinator
from .entity import SaferaEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SaferaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the settings selects."""
    async_add_entities([SaferaCookerWidthSelect(entry.runtime_data)])


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
