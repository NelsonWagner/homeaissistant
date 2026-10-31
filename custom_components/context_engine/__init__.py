"""Context Engine integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import ContextCoordinator, get_token_registry
from .services import (
    async_register_add_intent,
    async_register_refresh_profile,
    async_register_remove_intent,
    async_register_set_posture,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Context Engine domain."""
    hass.data.setdefault(DOMAIN, {})
    get_token_registry(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Context Engine from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("coordinators", {})

    registry = get_token_registry(hass)
    coordinator = ContextCoordinator(
        hass,
        dict(entry.data),
        dict(entry.options),
        registry,
    )
    coordinator.config_entry = entry
    coordinator.async_setup_listeners()

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN]["coordinators"][entry.data["area_id"]] = coordinator
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, "add_intent"):
        async_register_add_intent(hass)
        async_register_remove_intent(hass)
        async_register_refresh_profile(hass)
        async_register_set_posture(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    coordinator: ContextCoordinator | None = hass.data.get(DOMAIN, {}).get(
        "coordinators", {}
    ).pop(entry.data["area_id"], None)

    if coordinator:
        await coordinator.async_shutdown()

    if not hass.data.get(DOMAIN, {}).get("coordinators"):
        for service in ("add_intent", "remove_intent", "refresh_profile", "set_posture"):
            hass.services.async_remove(DOMAIN, service)

    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries."""
    return True
