"""Profile sensor platform for Context Engine."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ContextCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up profile sensor from config entry."""
    coordinator: ContextCoordinator = entry.runtime_data
    async_add_entities([ContextProfileSensor(coordinator, entry)])


class ContextProfileSensor(CoordinatorEntity[ContextCoordinator], SensorEntity):
    """Area profile sensor with topology, policy, and token attributes."""

    _attr_has_entity_name = True
    _attr_translation_key = "area_profile"

    def __init__(self, coordinator: ContextCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        area_id = coordinator.area_id
        self._attr_unique_id = f"context_engine_{area_id}_profile"
        self._attr_name = "profile"
        self.entity_id = f"sensor.{area_id}_profile"

    @property
    def native_value(self) -> str:
        return self.coordinator.get_profile_state()

    @property
    def extra_state_attributes(self) -> dict:
        return self.coordinator.get_profile_attributes()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
