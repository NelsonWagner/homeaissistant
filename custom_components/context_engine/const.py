"""Constants for the Context Engine integration."""

DOMAIN = "context_engine"

CONF_AREA_ID = "area_id"
CONF_MQTT_ENABLED = "mqtt_enabled"
CONF_ROLE_MAPPINGS = "role_mappings"
CONF_POLICY_MAP = "policy_map"
CONF_FEATURES = "features"
CONF_POSTURE_SOURCE = "posture_source"
CONF_CURRENT_POSTURE = "current_posture"

DEFAULT_ROLE_MAPPINGS: dict[str, str] = {
    "presence": "presence_entities",
    "door": "door_entities",
    "light": "light_entities",
    "fan": "fan_entities",
    "media": "media_entities",
    "climate": "climate_entities",
}

DEFAULT_POLICY_MAP: dict[str, dict] = {
    "morning": {
        "lighting": {"brightness_pct": 100, "color_temp_kelvin": 4500},
    },
    "daylight": {
        "lighting": {"brightness_pct": 100, "color_temp_kelvin": 5500},
    },
    "evening": {
        "lighting": {"brightness_pct": 50, "color_temp_kelvin": 3000},
    },
    "night": {
        "lighting": {"brightness_pct": 5, "color_temp_kelvin": 2200},
    },
}

DEFAULT_FEATURES: dict[str, bool] = {
    "lock_eligible": False,
    "night_light": True,
    "media_eligible": True,
    "ventilation_eligible": False,
}

POSTURE_CHOICES = ("morning", "daylight", "evening", "night")
INTENT_TYPES = ("active", "override", "schedule")
INTENT_DOMAINS = ("lighting", "climate", "media", "ventilation", "lock")

SERVICE_ADD_INTENT = "add_intent"
SERVICE_REMOVE_INTENT = "remove_intent"
SERVICE_REFRESH_PROFILE = "refresh_profile"
SERVICE_SET_POSTURE = "set_posture"

ATTR_TOPO_PREFIX = "topo__"
ATTR_POL_PREFIX = "pol__"
ATTR_FEAT_PREFIX = "feat__"
ATTR_ACTIVE_TOKENS = "active_tokens"

EVENT_INTENT_EVALUATED = "context_engine_intent_evaluated"

MQTT_STATE_TOPIC = "context_engine/{area_id}/profile/state"
MQTT_ATTR_TOPIC = "context_engine/{area_id}/profile/attributes"
MQTT_AVAIL_TOPIC = "context_engine/{area_id}/availability"
MQTT_DISCOVERY_TOPIC = "homeassistant/sensor/{area_id}_profile/config"

PRIORITY_ORDER = {"override": 0, "schedule": 1, "active": 2}

PLATFORMS = ["sensor", "event"]

UPDATE_INTERVAL = 60
