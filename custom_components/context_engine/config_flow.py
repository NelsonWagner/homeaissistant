"""Config flow for Context Engine."""

from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigFlowResult as FlowResult
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.selector import (
    AreaSelector,
    AreaSelectorConfig,
    BooleanSelector,
    NumberSelector,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
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
)

_LOGGER = logging.getLogger(__name__)


def _policy_from_brightness_inputs(user_input: dict[str, Any]) -> dict[str, dict]:
    """Build policy map from slider fields."""
    mapping = {
        "morning": ("morning_brightness", "morning_color_temp"),
        "daylight": ("daylight_brightness", "daylight_color_temp"),
        "evening": ("evening_brightness", "evening_color_temp"),
        "night": ("night_brightness", "night_color_temp"),
    }
    policy: dict[str, dict] = {}
    for posture, (b_key, c_key) in mapping.items():
        policy[posture] = {
            "lighting": {
                "brightness_pct": user_input.get(b_key, 50),
                "color_temp_kelvin": user_input.get(c_key, 4000),
            }
        }
    return policy


def _get_area_options(hass: HomeAssistant) -> list[dict[str, str]]:
    area_reg = ar.async_get(hass)
    return [
        {"value": area.id, "label": area.name}
        for area in area_reg.async_list_areas()
    ]


class ContextEngineConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Context Engine."""

    VERSION = 1

    def __init__(self) -> None:
        self._flow_area_ids: list[str] = []
        self._shared: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ContextEngineOptionsFlow:
        return ContextEngineOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Discover areas and MQTT availability."""
        queued = self.hass.data.get(DOMAIN, {}).pop("setup_queue", None)
        if queued:
            self._flow_area_ids = queued["areas"]
            self._shared = queued["shared"]
            return await self._async_create_area_entries()

        areas = _get_area_options(self.hass)
        if not areas:
            return self.async_abort(reason="invalid_area")

        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required("areas"): SelectSelector(
                            SelectSelectorConfig(
                                options=areas,
                                mode=SelectSelectorMode.DROPDOWN,
                                multiple=True,
                            )
                        ),
                    }
                ),
            )

        self._flow_area_ids = user_input["areas"]
        return await self.async_step_role_mappings()

    async def async_step_role_mappings(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Review label → topology role mappings."""
        if user_input is None:
            return self.async_show_form(
                step_id="role_mappings",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_ROLE_MAPPINGS,
                            default=json.dumps(DEFAULT_ROLE_MAPPINGS, indent=2),
                        ): TextSelector(),
                    }
                ),
            )

        try:
            role_mappings = json.loads(user_input[CONF_ROLE_MAPPINGS])
            if not isinstance(role_mappings, dict):
                raise ValueError("Role mappings must be a JSON object")
        except (json.JSONDecodeError, ValueError) as err:
            return self.async_show_form(
                step_id="role_mappings",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_ROLE_MAPPINGS): TextSelector(),
                    }
                ),
                errors={"role_mappings": str(err)},
            )

        self._shared[CONF_ROLE_MAPPINGS] = role_mappings
        return await self.async_step_policy()

    async def async_step_policy(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure default posture lighting policy."""
        if user_input is None:
            return self.async_show_form(
                step_id="policy",
                data_schema=vol.Schema(
                    {
                        vol.Required("morning_brightness", default=100): NumberSelector(
                            NumberSelectorConfig(min=0, max=100, mode=NumberSelectorMode.SLIDER)
                        ),
                        vol.Required("morning_color_temp", default=4500): NumberSelector(
                            NumberSelectorConfig(min=2000, max=6500, mode=NumberSelectorMode.BOX)
                        ),
                        vol.Required("daylight_brightness", default=100): NumberSelector(
                            NumberSelectorConfig(min=0, max=100, mode=NumberSelectorMode.SLIDER)
                        ),
                        vol.Required("daylight_color_temp", default=5500): NumberSelector(
                            NumberSelectorConfig(min=2000, max=6500, mode=NumberSelectorMode.BOX)
                        ),
                        vol.Required("evening_brightness", default=50): NumberSelector(
                            NumberSelectorConfig(min=0, max=100, mode=NumberSelectorMode.SLIDER)
                        ),
                        vol.Required("evening_color_temp", default=3000): NumberSelector(
                            NumberSelectorConfig(min=2000, max=6500, mode=NumberSelectorMode.BOX)
                        ),
                        vol.Required("night_brightness", default=5): NumberSelector(
                            NumberSelectorConfig(min=0, max=100, mode=NumberSelectorMode.SLIDER)
                        ),
                        vol.Required("night_color_temp", default=2200): NumberSelector(
                            NumberSelectorConfig(min=2000, max=6500, mode=NumberSelectorMode.BOX)
                        ),
                    }
                ),
            )

        self._shared[CONF_POLICY_MAP] = _policy_from_brightness_inputs(user_input)
        return await self.async_step_features()

    async def async_step_features(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Feature flags and MQTT."""
        if user_input is None:
            return self.async_show_form(
                step_id="features",
                data_schema=vol.Schema(
                    {
                        vol.Required("lock_eligible", default=False): BooleanSelector(),
                        vol.Required("night_light", default=True): BooleanSelector(),
                        vol.Required("media_eligible", default=True): BooleanSelector(),
                        vol.Required("ventilation_eligible", default=False): BooleanSelector(),
                        vol.Required("auto_actuate", default=False): BooleanSelector(),
                        vol.Required(
                            "mqtt_enabled",
                            default=bool(mqtt.async_get(self.hass)),
                        ): BooleanSelector(),
                        vol.Required(
                            CONF_POSTURE_SOURCE,
                            default="sun",
                        ): SelectSelector(
                            SelectSelectorConfig(
                                options=[
                                    {"value": "sun", "label": "Sun elevation"},
                                    {"value": "schedule", "label": "Schedule"},
                                    {"value": "input_select", "label": "Input select"},
                                ],
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                    }
                ),
            )

        self._shared[CONF_FEATURES] = {
            "lock_eligible": user_input["lock_eligible"],
            "night_light": user_input["night_light"],
            "media_eligible": user_input["media_eligible"],
            "ventilation_eligible": user_input["ventilation_eligible"],
            "auto_actuate": user_input.get("auto_actuate", False),
        }
        self._shared[CONF_MQTT_ENABLED] = user_input["mqtt_enabled"]
        self._shared[CONF_POSTURE_SOURCE] = user_input[CONF_POSTURE_SOURCE]

        return await self._async_create_area_entries()

    async def _async_create_area_entries(self) -> FlowResult:
        """Create one config entry per selected area."""
        area_reg = ar.async_get(self.hass)
        pending = list(self._flow_area_ids)

        while pending:
            area_id = pending.pop(0)
            await self.async_set_unique_id(f"{DOMAIN}_{area_id}")
            self._abort_if_unique_id_configured()

            area = area_reg.async_get_area(area_id)
            title = f"{area.name if area else area_id} Profile"

            options = {
                CONF_ROLE_MAPPINGS: self._shared.get(
                    CONF_ROLE_MAPPINGS, DEFAULT_ROLE_MAPPINGS
                ),
                CONF_POLICY_MAP: self._shared.get(
                    CONF_POLICY_MAP, DEFAULT_POLICY_MAP
                ),
                CONF_FEATURES: self._shared.get(CONF_FEATURES, DEFAULT_FEATURES),
                CONF_POSTURE_SOURCE: self._shared.get(CONF_POSTURE_SOURCE, "sun"),
                CONF_CURRENT_POSTURE: None,
            }

            if pending:
                self.hass.data.setdefault(DOMAIN, {})["setup_queue"] = {
                    "areas": pending,
                    "shared": self._shared,
                }
                self.hass.async_create_task(
                    self.hass.config_entries.flow.async_init(
                        DOMAIN,
                        context={"source": config_entries.SOURCE_USER},
                    )
                )

            return self.async_create_entry(
                title=title,
                data={
                    CONF_AREA_ID: area_id,
                    CONF_MQTT_ENABLED: self._shared.get(CONF_MQTT_ENABLED, True),
                },
                options=options,
            )

        return self.async_abort(reason="invalid_area")

class ContextEngineOptionsFlow(config_entries.OptionsFlow):
    """Options flow for Context Engine."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage options."""
        if user_input is not None:
            try:
                role_mappings = json.loads(user_input[CONF_ROLE_MAPPINGS])
            except json.JSONDecodeError:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._options_schema(),
                    errors={"role_mappings": "invalid_json"},
                )

            options = dict(self.config_entry.options)
            options[CONF_ROLE_MAPPINGS] = role_mappings
            options[CONF_FEATURES] = {
                "lock_eligible": user_input["lock_eligible"],
                "night_light": user_input["night_light"],
                "media_eligible": user_input["media_eligible"],
                "ventilation_eligible": user_input["ventilation_eligible"],
                "auto_actuate": user_input.get("auto_actuate", False),
            }
            options[CONF_POSTURE_SOURCE] = user_input[CONF_POSTURE_SOURCE]

            data = dict(self.config_entry.data)
            data[CONF_MQTT_ENABLED] = user_input["mqtt_enabled"]

            self.hass.config_entries.async_update_entry(
                self.config_entry, data=data, options=options
            )

            coordinator = self.hass.data.get(DOMAIN, {}).get("coordinators", {}).get(
                self.config_entry.data[CONF_AREA_ID]
            )
            if coordinator:
                coordinator.entry_data = data
                coordinator.update_options(options)
                await coordinator.async_refresh_profile()

            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=self._options_schema(),
        )

    def _options_schema(self) -> vol.Schema:
        opts = self.config_entry.options
        features = {**DEFAULT_FEATURES, **opts.get(CONF_FEATURES, {})}
        return vol.Schema(
            {
                vol.Required(
                    CONF_ROLE_MAPPINGS,
                    default=json.dumps(
                        opts.get(CONF_ROLE_MAPPINGS, DEFAULT_ROLE_MAPPINGS),
                        indent=2,
                    ),
                ): TextSelector(),
                vol.Required("lock_eligible", default=features["lock_eligible"]): BooleanSelector(),
                vol.Required("night_light", default=features["night_light"]): BooleanSelector(),
                vol.Required("media_eligible", default=features["media_eligible"]): BooleanSelector(),
                vol.Required(
                    "ventilation_eligible", default=features["ventilation_eligible"]
                ): BooleanSelector(),
                vol.Required(
                    "auto_actuate", default=features.get("auto_actuate", False)
                ): BooleanSelector(),
                vol.Required(
                    "mqtt_enabled",
                    default=self.config_entry.data.get(CONF_MQTT_ENABLED, True),
                ): BooleanSelector(),
                vol.Required(
                    CONF_POSTURE_SOURCE,
                    default=opts.get(CONF_POSTURE_SOURCE, "sun"),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=["sun", "schedule", "input_select"],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
