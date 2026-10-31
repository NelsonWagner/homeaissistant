"""Context event platform for intent evaluation."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, EVENT_INTENT_EVALUATED
from .coordinator import ContextCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up context event entity."""
    coordinator: ContextCoordinator = entry.runtime_data
    async_add_entities([ContextIntentEvaluatedEvent(hass, coordinator, entry)])


class ContextIntentEvaluatedEvent(EventEntity):
    """Records context_engine_intent_evaluated events for an area."""

    _attr_has_entity_name = True
    _attr_translation_key = "intent_evaluated"
    _attr_event_types = ["intent_evaluated"]

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ContextCoordinator,
        entry: ConfigEntry,
    ) -> None:
        self.hass = hass
        self._coordinator = coordinator
        self._entry = entry
        area_id = coordinator.area_id
        self._attr_unique_id = f"context_engine_{area_id}_intent_event"
        self._attr_name = "intent evaluated"
        self.entity_id = f"event.{area_id}_context_engine_intent_evaluated"
        super().__init__()
        self._unsub = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to bus events."""
        await super().async_added_to_hass()

        @callback
        def _handle_event(event: Any) -> None:
            if event.data.get("area_id") != self._coordinator.area_id:
                return
            self._trigger_event(
                "intent_evaluated",
                event.data,
            )

        self._unsub = self.hass.bus.async_listen(
            EVENT_INTENT_EVALUATED, _handle_event
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe."""
        if self._unsub:
            self._unsub()
            self._unsub = None
        await super().async_will_remove_from_hass()
