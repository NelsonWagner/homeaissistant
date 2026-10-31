"""set_posture service."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from ..const import CONF_CURRENT_POSTURE, DOMAIN, POSTURE_CHOICES, SERVICE_SET_POSTURE
from ..coordinator import get_coordinator_for_area

SCHEMA = vol.Schema(
    {
        vol.Required("area_id"): cv.string,
        vol.Optional("posture"): vol.Any(vol.In(POSTURE_CHOICES), vol.Equal(""), None),
    }
)


async def async_register_set_posture(hass: HomeAssistant) -> None:
    """Register the set_posture service."""

    async def handle(call: ServiceCall) -> None:
        area_id = call.data["area_id"]
        coordinator = get_coordinator_for_area(hass, area_id)
        if coordinator is None:
            raise ValueError(f"No Context Engine profile configured for area {area_id}")

        posture = call.data.get("posture")
        if posture == "":
            posture = None

        entry = coordinator.config_entry
        if entry is not None:
            new_options = dict(entry.options)
            new_options[CONF_CURRENT_POSTURE] = posture
            hass.config_entries.async_update_entry(entry, options=new_options)
            coordinator.update_options(new_options)

        await coordinator.set_posture(posture)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_POSTURE,
        handle,
        schema=SCHEMA,
    )
