"""remove_intent service."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from ..const import DOMAIN, INTENT_DOMAINS, INTENT_TYPES, SERVICE_REMOVE_INTENT
from ..coordinator import get_coordinator_for_area

SCHEMA = vol.Schema(
    {
        vol.Required("area_id"): cv.string,
        vol.Required("claimant_id"): cv.entity_id,
        vol.Optional("domain"): vol.In(INTENT_DOMAINS),
        vol.Optional("intent_type"): vol.In(INTENT_TYPES),
    }
)


async def async_register_remove_intent(hass: HomeAssistant) -> None:
    """Register the remove_intent service."""

    async def handle(call: ServiceCall) -> None:
        area_id = call.data["area_id"]
        coordinator = get_coordinator_for_area(hass, area_id)
        if coordinator is None:
            raise ValueError(f"No Context Engine profile configured for area {area_id}")

        await coordinator.remove_intents(
            claimant_id=call.data["claimant_id"],
            domain=call.data.get("domain"),
            intent_type=call.data.get("intent_type"),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_INTENT,
        handle,
        schema=SCHEMA,
    )
