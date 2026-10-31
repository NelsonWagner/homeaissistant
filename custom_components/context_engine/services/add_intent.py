"""add_intent service."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from ..const import (
    DOMAIN,
    INTENT_DOMAINS,
    INTENT_TYPES,
    SERVICE_ADD_INTENT,
)
from ..coordinator import get_coordinator_for_area

SCHEMA = vol.Schema(
    {
        vol.Required("area_id"): cv.string,
        vol.Required("domain"): vol.In(INTENT_DOMAINS),
        vol.Required("intent_type"): vol.In(INTENT_TYPES),
        vol.Required("claimant_id"): cv.entity_id,
        vol.Optional("action_value"): cv.string,
        vol.Required("seconds"): vol.Any(vol.Coerce(int)),
        vol.Optional("labels"): [cv.string],
    }
)


async def async_register_add_intent(hass: HomeAssistant) -> None:
    """Register the add_intent service."""

    async def handle(call: ServiceCall) -> None:
        area_id = call.data["area_id"]
        coordinator = get_coordinator_for_area(hass, area_id)
        if coordinator is None:
            raise ValueError(f"No Context Engine profile configured for area {area_id}")

        await coordinator.add_intent(
            domain=call.data["domain"],
            intent_type=call.data["intent_type"],
            claimant_id=call.data["claimant_id"],
            seconds=int(call.data["seconds"]),
            action_value=call.data.get("action_value"),
            labels=call.data.get("labels"),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_INTENT,
        handle,
        schema=SCHEMA,
    )
