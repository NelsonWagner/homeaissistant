"""Context Engine coordinator, token registry, and profile builder."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from homeassistant.components import mqtt
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_ACTIVE_TOKENS,
    ATTR_FEAT_PREFIX,
    ATTR_POL_PREFIX,
    ATTR_TOPO_PREFIX,
    CONF_AREA_ID,
    CONF_CURRENT_POSTURE,
    CONF_FEATURES,
    CONF_MQTT_ENABLED,
    CONF_POLICY_MAP,
    CONF_POSTURE_SOURCE,
    CONF_ROLE_MAPPINGS,
    DEFAULT_FEATURES,
    DEFAULT_POLICY_MAP,
    DEFAULT_ROLE_MAPPINGS,
    DOMAIN,
    EVENT_INTENT_EVALUATED,
    INTENT_DOMAINS,
    MQTT_ATTR_TOPIC,
    MQTT_AVAIL_TOPIC,
    MQTT_DISCOVERY_TOPIC,
    MQTT_STATE_TOPIC,
    PRIORITY_ORDER,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return dt_util.utcnow()


@dataclass
class IntentToken:
    """Runtime intent token stored in memory."""

    token_id: str
    area_id: str
    domain: str
    intent_type: str
    claimant_id: str
    action_value: str | None
    expires_at: datetime | None
    created_at: datetime
    labels: list[str] | None = None

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        now = now or _utc_now()
        return now >= self.expires_at

    def to_debug_dict(self) -> dict[str, Any]:
        return {
            "claimant": self.claimant_id,
            "expires": (
                self.expires_at.isoformat().replace("+00:00", "Z")
                if self.expires_at
                else None
            ),
            "action_value": self.action_value,
            "labels": self.labels,
        }


class TokenRegistry:
    """Async-safe in-memory intent token store."""

    def __init__(self) -> None:
        self._tokens: dict[str, IntentToken] = {}
        self._lock = asyncio.Lock()

    async def add_token(self, token: IntentToken) -> None:
        async with self._lock:
            self._tokens[token.token_id] = token

    async def remove_token(self, token_id: str) -> IntentToken | None:
        async with self._lock:
            return self._tokens.pop(token_id, None)

    async def remove_matching(
        self,
        area_id: str,
        claimant_id: str,
        domain: str | None = None,
        intent_type: str | None = None,
    ) -> list[IntentToken]:
        removed: list[IntentToken] = []
        async with self._lock:
            to_delete: list[str] = []
            for token_id, token in self._tokens.items():
                if token.area_id != area_id or token.claimant_id != claimant_id:
                    continue
                if domain and token.domain != domain:
                    continue
                if intent_type and token.intent_type != intent_type:
                    continue
                to_delete.append(token_id)
            for token_id in to_delete:
                removed.append(self._tokens.pop(token_id))
        return removed

    async def get_active_for_area(
        self, area_id: str, domain: str | None = None
    ) -> list[IntentToken]:
        now = _utc_now()
        async with self._lock:
            tokens = [
                t
                for t in self._tokens.values()
                if t.area_id == area_id
                and not t.is_expired(now)
                and (domain is None or t.domain == domain)
            ]
        return tokens

    async def prune_expired(self, area_id: str | None = None) -> list[IntentToken]:
        now = _utc_now()
        removed: list[IntentToken] = []
        async with self._lock:
            expired_ids = [
                tid
                for tid, t in self._tokens.items()
                if (area_id is None or t.area_id == area_id) and t.is_expired(now)
            ]
            for tid in expired_ids:
                removed.append(self._tokens.pop(tid))
        return removed

    async def evaluate_priority(
        self, area_id: str, domain: str
    ) -> IntentToken | None:
        await self.prune_expired(area_id)
        tokens = await self.get_active_for_area(area_id, domain)
        if not tokens:
            return None
        tokens.sort(
            key=lambda t: (
                PRIORITY_ORDER.get(t.intent_type, 99),
                t.created_at,
            )
        )
        return tokens[0]

    async def tokens_debug_by_area(self, area_id: str) -> dict[str, Any]:
        """Group active tokens by domain and intent_type for sensor attributes."""
        tokens = await self.get_active_for_area(area_id)
        grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for token in tokens:
            grouped.setdefault(token.domain, {})
            grouped[token.domain].setdefault(token.intent_type, [])
            grouped[token.domain][token.intent_type].append(token.to_debug_dict())
        return grouped


class ProfileBuilder:
    """Build area profile payloads from HA registries."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def build(
        self,
        area_id: str,
        role_mappings: dict[str, str],
        policy_map: dict[str, Any],
        features: dict[str, bool],
        token_debug: dict[str, Any],
        current_posture: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return (state_dict, attributes_dict)."""
        from homeassistant.helpers import entity_registry as er
        from homeassistant.helpers import label_registry as lr

        registry = er.async_get(self.hass)
        label_reg = lr.async_get(self.hass)
        label_ids_by_name = {
            label.name: label.label_id for label in label_reg.async_list_labels()
        }

        topo_lists: dict[str, list[str]] = {
            v: [] for v in role_mappings.values()
        }

        for entry in registry.entities.values():
            if entry.area_id != area_id:
                continue
            entity_label_ids = set(entry.labels or [])
            for label_name, topo_key in role_mappings.items():
                label_id = label_ids_by_name.get(label_name, label_name)
                if label_id in entity_label_ids and topo_key in topo_lists:
                    if entry.entity_id not in topo_lists[topo_key]:
                        topo_lists[topo_key].append(entry.entity_id)

        topo_short = {
            k.replace("_entities", ""): topo_lists[k]
            for k in sorted(topo_lists)
        }

        state_dict: dict[str, Any] = {
            "area_id": area_id,
            "topo": topo_short,
            "pol": policy_map,
            "feat": features,
            "tokens": token_debug,
        }
        if current_posture:
            state_dict["posture"] = current_posture

        attributes: dict[str, Any] = {}
        for topo_key, entities in topo_lists.items():
            attr_name = f"{ATTR_TOPO_PREFIX}{topo_key}"
            attributes[attr_name] = sorted(entities)

        for posture, pol_data in policy_map.items():
            attributes[f"{ATTR_POL_PREFIX}{posture}"] = pol_data

        for feat_key, feat_val in features.items():
            attributes[f"{ATTR_FEAT_PREFIX}{feat_key}"] = feat_val

        attributes[ATTR_ACTIVE_TOKENS] = token_debug

        return state_dict, attributes


class IntentEvaluator:
    """Resolve winning intent and optional actuation."""

    def __init__(
        self,
        hass: HomeAssistant,
        registry: TokenRegistry,
    ) -> None:
        self.hass = hass
        self.registry = registry

    async def evaluate_area_domain(
        self,
        area_id: str,
        domain: str,
        policy_map: dict[str, Any],
        features: dict[str, bool],
        current_posture: str | None,
        topo_presence: list[str],
        topo_doors: list[str],
        apply_actions: bool = True,
    ) -> dict[str, Any]:
        """Evaluate intents and return event payload."""
        cleared: list[str] = []
        new_tokens: list[str] = []

        winner = await self.registry.evaluate_priority(area_id, domain)
        resolution = winner.intent_type if winner else None
        target_state: dict[str, Any] = {}

        if winner and winner.action_value:
            target_state = {"action": winner.action_value}
        elif winner and current_posture and domain == "lighting":
            posture_pol = policy_map.get(current_posture, {})
            target_state = dict(posture_pol.get("lighting", {}))
        elif current_posture and domain == "lighting":
            posture_pol = policy_map.get(current_posture, {})
            target_state = dict(posture_pol.get("lighting", {}))

        if domain == "lock" and features.get("lock_eligible"):
            await self._evaluate_lock_hold(
                area_id, topo_presence, topo_doors, target_state
            )

        if apply_actions and winner and domain == "lighting" and target_state:
            await self._apply_lighting(area_id, target_state, winner.labels)

        event_data = {
            "area_id": area_id,
            "domain": domain,
            "resolution": resolution,
            "target_state": target_state,
            "cleared_tokens": cleared,
            "new_tokens": new_tokens,
        }
        self.hass.bus.async_fire(EVENT_INTENT_EVALUATED, event_data)
        return event_data

    async def _evaluate_lock_hold(
        self,
        area_id: str,
        presence_entities: list[str],
        door_entities: list[str],
        target_state: dict[str, Any],
    ) -> None:
        """Hold lock intent when doors closed and presence active."""
        any_presence = any(
            self.hass.states.get(eid) and self.hass.states.get(eid).state == "on"
            for eid in presence_entities
        )
        all_doors_closed = True
        for eid in door_entities:
            state = self.hass.states.get(eid)
            if state and state.state not in ("off", "closed", "locked"):
                all_doors_closed = False
                break
        target_state["hold"] = any_presence and all_doors_closed
        target_state["area_id"] = area_id

    async def _apply_lighting(
        self,
        area_id: str,
        target_state: dict[str, Any],
        labels: list[str] | None,
    ) -> None:
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(self.hass)
        light_entities: list[str] = []
        for entry in registry.entities.values():
            if entry.area_id != area_id:
                continue
            if not entry.entity_id.startswith("light."):
                continue
            if labels:
                entity_labels = set(entry.labels or [])
                if not entity_labels.intersection(labels):
                    continue
            light_entities.append(entry.entity_id)

        service_data = {k: v for k, v in target_state.items() if k != "hold"}
        for entity_id in light_entities:
            await self.hass.services.async_call(
                "light",
                "turn_on",
                {"entity_id": entity_id, **service_data},
                blocking=False,
            )


class ContextCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Per-area coordinator managing profile refresh and tokens."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_data: dict[str, Any],
        entry_options: dict[str, Any],
        registry: TokenRegistry,
    ) -> None:
        area_id = entry_data[CONF_AREA_ID]
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{area_id}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.area_id = area_id
        self.entry_data = entry_data
        self.entry_options = entry_options
        self.registry = registry
        self.config_entry = None
        self.builder = ProfileBuilder(hass)
        self.evaluator = IntentEvaluator(hass, registry)
        self._state_dict: dict[str, Any] = {}
        self._attributes: dict[str, Any] = {}
        self._unsub_registry: list[Any] = []
        self._expiry_unsub: dict[str, Any] = {}

    @property
    def role_mappings(self) -> dict[str, str]:
        return self.entry_options.get(CONF_ROLE_MAPPINGS, DEFAULT_ROLE_MAPPINGS)

    @property
    def policy_map(self) -> dict[str, Any]:
        return self.entry_options.get(CONF_POLICY_MAP, DEFAULT_POLICY_MAP)

    @property
    def features(self) -> dict[str, bool]:
        return {**DEFAULT_FEATURES, **self.entry_options.get(CONF_FEATURES, {})}

    @property
    def current_posture(self) -> str | None:
        manual = self.entry_options.get(CONF_CURRENT_POSTURE)
        if manual:
            return manual
        return self._posture_from_source()

    def _posture_from_source(self) -> str:
        source = self.entry_options.get(CONF_POSTURE_SOURCE, "sun")
        if source != "sun":
            return "daylight"
        sun = self.hass.states.get("sun.sun")
        if not sun:
            return "daylight"
        elevation = float(sun.attributes.get("elevation", 0))
        if elevation < -6:
            return "night"
        if elevation < 6:
            return "evening"
        if elevation < 30:
            return "morning"
        return "daylight"

    @property
    def mqtt_enabled(self) -> bool:
        return bool(self.entry_data.get(CONF_MQTT_ENABLED, False))

    def update_options(self, options: dict[str, Any]) -> None:
        self.entry_options = options

    async def _async_update_data(self) -> dict[str, Any]:
        await self.registry.prune_expired(self.area_id)
        return await self._rebuild_profile()

    async def _rebuild_profile(self) -> dict[str, Any]:
        token_debug = await self.registry.tokens_debug_by_area(self.area_id)
        state_dict, attributes = await self.builder.build(
            self.area_id,
            self.role_mappings,
            self.policy_map,
            self.features,
            token_debug,
            self.current_posture,
        )
        self._state_dict = state_dict
        self._attributes = attributes
        await self._publish_mqtt(state_dict, attributes)
        return state_dict

    async def async_refresh_profile(self) -> dict[str, Any]:
        data = await self._rebuild_profile()
        await self.async_request_refresh()
        return data

    def get_profile_state(self) -> str:
        if not self._state_dict:
            return STATE_UNAVAILABLE
        return json.dumps(self._state_dict, separators=(",", ":"))

    def get_profile_attributes(self) -> dict[str, Any]:
        return dict(self._attributes)

    async def add_intent(
        self,
        domain: str,
        intent_type: str,
        claimant_id: str,
        seconds: int,
        action_value: str | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        if domain not in INTENT_DOMAINS:
            raise ValueError(f"Invalid domain: {domain}")

        if seconds == 0:
            event = await self._evaluate_domain(domain)
            await self.async_refresh_profile()
            return event

        expires_at: datetime | None
        if seconds == -1:
            expires_at = None
        else:
            expires_at = _utc_now() + timedelta(seconds=seconds)

        token = IntentToken(
            token_id=str(uuid4()),
            area_id=self.area_id,
            domain=domain,
            intent_type=intent_type,
            claimant_id=claimant_id,
            action_value=action_value,
            expires_at=expires_at,
            created_at=_utc_now(),
            labels=labels,
        )

        await self.registry.add_token(token)
        if expires_at and seconds > 0:
            self._schedule_expiry(token.token_id, expires_at)

        event = await self._evaluate_domain(domain)
        await self.async_refresh_profile()
        return event

    async def remove_intents(
        self,
        claimant_id: str,
        domain: str | None = None,
        intent_type: str | None = None,
    ) -> list[IntentToken]:
        removed = await self.registry.remove_matching(
            self.area_id, claimant_id, domain, intent_type
        )
        domains = {t.domain for t in removed} or ({domain} if domain else set())
        for dom in domains:
            if dom:
                await self._evaluate_domain(dom)
        await self.async_refresh_profile()
        return removed

    async def set_posture(self, posture: str | None) -> None:
        if posture is not None and posture not in self.policy_map:
            raise ValueError(f"Invalid posture: {posture}")
        self.entry_options[CONF_CURRENT_POSTURE] = posture
        await self.async_refresh_profile()
        for domain in ("lighting", "climate", "media", "ventilation", "lock"):
            await self._evaluate_domain(domain)

    async def _evaluate_domain(self, domain: str) -> dict[str, Any]:
        attrs = self.get_profile_attributes()
        presence = attrs.get(f"{ATTR_TOPO_PREFIX}presence_entities", [])
        doors = attrs.get(f"{ATTR_TOPO_PREFIX}door_entities", [])
        if not presence and self._attributes:
            presence = self._attributes.get(
                f"{ATTR_TOPO_PREFIX}presence_entities", []
            )
            doors = self._attributes.get(f"{ATTR_TOPO_PREFIX}door_entities", [])
        return await self.evaluator.evaluate_area_domain(
            self.area_id,
            domain,
            self.policy_map,
            self.features,
            self.current_posture,
            presence,
            doors,
        )

    def _schedule_expiry(self, token_id: str, expires_at: datetime) -> None:
        if token_id in self._expiry_unsub:
            self._expiry_unsub[token_id]()
            del self._expiry_unsub[token_id]

        @callback
        def _handle_expiry(_now: datetime) -> None:
            self.hass.async_create_task(self._on_token_expired(token_id))

        self._expiry_unsub[token_id] = async_track_point_in_time(
            self.hass, _handle_expiry, expires_at
        )

    async def _on_token_expired(self, token_id: str) -> None:
        token = await self.registry.remove_token(token_id)
        if token:
            await self._evaluate_domain(token.domain)
            await self.async_refresh_profile()
        self._expiry_unsub.pop(token_id, None)

    async def _publish_mqtt(
        self, state_dict: dict[str, Any], attributes: dict[str, Any]
    ) -> None:
        if not self.mqtt_enabled:
            return
        if not mqtt.async_get(self.hass):
            return

        area_id = self.area_id
        state_topic = MQTT_STATE_TOPIC.format(area_id=area_id)
        attr_topic = MQTT_ATTR_TOPIC.format(area_id=area_id)
        avail_topic = MQTT_AVAIL_TOPIC.format(area_id=area_id)
        discovery_topic = MQTT_DISCOVERY_TOPIC.format(area_id=area_id)

        from homeassistant.helpers import area_registry as ar

        area_reg = ar.async_get(self.hass)
        area_entry = area_reg.async_get_area(area_id)
        area_name = area_entry.name if area_entry else area_id.replace("_", " ").title()

        discovery_payload = {
            "name": f"{area_name} Profile",
            "unique_id": f"context_engine_{area_id}_profile",
            "state_topic": state_topic,
            "json_attributes_topic": attr_topic,
            "availability_topic": avail_topic,
            "device": {
                "identifiers": [f"context_engine_{area_id}"],
                "name": f"{area_name} Context",
                "model": "Context Engine",
                "manufacturer": "Context Engine",
            },
        }

        await mqtt.async_publish(
            self.hass,
            discovery_topic,
            json.dumps(discovery_payload),
            retain=True,
        )
        await mqtt.async_publish(
            self.hass,
            state_topic,
            json.dumps(state_dict, separators=(",", ":")),
            retain=True,
        )
        await mqtt.async_publish(
            self.hass,
            attr_topic,
            json.dumps(attributes),
            retain=True,
        )
        await mqtt.async_publish(self.hass, avail_topic, "online", retain=True)

    def async_setup_listeners(self) -> None:
        from homeassistant.helpers import entity_registry as er

        @callback
        def _registry_updated(event: Any) -> None:
            self.hass.async_create_task(self.async_refresh_profile())

        self._unsub_registry.append(
            self.hass.bus.async_listen("entity_registry_updated", _registry_updated)
        )
        self._unsub_registry.append(
            self.hass.bus.async_listen("area_registry_updated", _registry_updated)
        )

    async def async_shutdown(self) -> None:
        for unsub in self._unsub_registry:
            unsub()
        self._unsub_registry.clear()
        for unsub in self._expiry_unsub.values():
            unsub()
        self._expiry_unsub.clear()
        if self.mqtt_enabled and mqtt.async_get(self.hass):
            avail_topic = MQTT_AVAIL_TOPIC.format(area_id=self.area_id)
            await mqtt.async_publish(self.hass, avail_topic, "offline", retain=True)


def get_coordinator_for_area(
    hass: HomeAssistant, area_id: str
) -> ContextCoordinator | None:
    """Return coordinator for a configured area."""
    coordinators: dict[str, ContextCoordinator] = hass.data.get(DOMAIN, {}).get(
        "coordinators", {}
    )
    return coordinators.get(area_id)


def get_token_registry(hass: HomeAssistant) -> TokenRegistry:
    """Return shared token registry."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    if "registry" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["registry"] = TokenRegistry()
    return hass.data[DOMAIN]["registry"]
