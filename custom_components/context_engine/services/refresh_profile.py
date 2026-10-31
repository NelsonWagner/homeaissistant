"""refresh_profile service."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from ..const import DOMAIN, SERVICE_REFRESH_PROFILE
from ..coordinator import get_coordinator_for_area

SCHEMA = vol.Schema(
    {
        vol.Required("area_id"): cv.string,
    }
)


async def async_register_refresh_profile(hass: HomeAssistant) -> None:
    """Register the refresh_profile service."""

    async def handle(call: ServiceCall) -> None:
        area_id = call.data["area_id"]
        coordinator = get_coordinator_for_area(hass, area_id)
        if coordinator is None:
            raise ValueError(f"No Context Engine profile configured for area {area_id}")

        await coordinator.async_refresh_profile()

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_PROFILE,
        handle,
        schema=SCHEMA,
    )
