# Context Engine — Home Assistant Integration Spec
## Version: 0.1.0-draft | Domain: `context_engine`

---

## 1. Overview

A native Home Assistant integration that implements profile-driven room context management. Replaces brittle entity-ID-based automations with an abstracted intent-token system where rooms are software objects, hardware is role-mapped via labels, and MQTT discovery handles zero-touch provisioning.

**Core Principle:** The engine evaluates *meaning* ("this room needs ventilation now") rather than *events* ("motion sensor X fired").

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         HOME ASSISTANT CORE                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐     │
│  │  MQTT        │  │  Entity      │  │  Automation / Script     │     │
│  │  Integration │  │  Registry    │  │  (User/Blueprint)        │     │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────────┘     │
│         │                 │                      │                    │
│  ┌──────▼─────────────────▼──────────────────────▼───────────────┐ │
│  │              CONTEXT ENGINE INTEGRATION                         │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐     │ │
│  │  │ Coordinator  │  │ Profile      │  │ Token            │     │ │
│  │  │ (DataUpdate) │  │ Sensor       │  │ Registry         │     │ │
│  │  └──────────────┘  │ Platform     │  │ (In-memory)      │     │ │
│  │         │          └──────────────┘  └──────────────────┘     │ │
│  │         │                 ▲                      ▲            │ │
│  │         └─────────────────┴──────────────────────┘            │ │
│  │                    Config Entry (per area)                    │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Platforms

### 3.1 `sensor` — Area Profile Sensor

For every area enabled in the config entry, the integration creates:

```
sensor.<area_id>_profile
```

**State:** JSON string (compacted) containing the room's live profile.

**Attributes (expanded in HA UI):**
| Attribute | Type | Description |
|-----------|------|-------------|
| `topo__presence_entities` | list[str] | Entity IDs with `presence` label in this area |
| `topo__door_entities` | list[str] | Entity IDs with `door` label in this area |
| `topo__light_entities` | list[str] | Entity IDs with `light` label in this area |
| `topo__fan_entities` | list[str] | Entity IDs with `fan` label in this area |
| `topo__media_entities` | list[str] | Entity IDs with `media` label in this area |
| `topo__climate_entities` | list[str] | Entity IDs with `climate` label in this area |
| `pol__morning` | dict | Target state for morning posture |
| `pol__daylight` | dict | Target state for daylight posture |
| `pol__evening` | dict | Target state for evening posture |
| `pol__night` | dict | Target state for night posture |
| `feat__lock_eligible` | bool | Whether room supports auto-lock |
| `feat__night_light` | bool | Whether room supports night lighting |
| `feat__media_eligible` | bool | Whether room supports media control |
| `feat__ventilation_eligible` | bool | Whether room supports auto-ventilation |
| `active_tokens` | dict | Currently-held intent tokens (debug) |

**Example State Value:**
```json
{
  "area_id": "living_room",
  "topo": {
    "presence_entities": ["binary_sensor.lr_motion"],
    "light_entities": ["light.lr_ceiling", "light.lr_lamp"],
    "media_entities": ["media_player.lr_tv"]
  },
  "pol": {
    "morning": {"lighting": {"brightness_pct": 80, "color_temp_kelvin": 4000}},
    "evening": {"lighting": {"brightness_pct": 40, "color_temp_kelvin": 2700}}
  },
  "feat": {
    "lock_eligible": false,
    "night_light": true,
    "media_eligible": true
  },
  "tokens": {
    "lighting": {"active": [{"claimant": "binary_sensor.lr_motion", "expires": "2026-10-31T20:15:00Z"}]},
    "media": {"override": [{"claimant": "media_player.lr_tv", "expires": null}]}
  }
}
```

### 3.2 `event` — Context Event

Optional platform firing structured events for other automations:

```
event.context_engine_intent_evaluated
```

**Event Data:**
```yaml
area_id: living_room
domain: lighting
resolution: active  # Which intent_type won
target_state:
  brightness_pct: 40
cleared_tokens: []
new_tokens: []
```

---

## 4. Data Models

### 4.1 Config Entry

Stored per-area (not per-integration). Each area gets its own config entry so users can disable rooms individually.

```python
ConfigEntry(
    domain="context_engine",
    title="Living Room Profile",
    data={
        "area_id": "living_room",
        "mqtt_enabled": True,
    },
    options={
        "role_mappings": {  # Label → topo key
            "presence": "presence_entities",
            "door": "door_entities",
            "light": "light_entities",
            "fan": "fan_entities",
            "media": "media_entities",
            "climate": "climate_entities",
        },
        "policy_map": {
            "morning": {"lighting": {"brightness_pct": 100, "color_temp_kelvin": 4500}},
            "daylight": {"lighting": {"brightness_pct": 100, "color_temp_kelvin": 5500}},
            "evening": {"lighting": {"brightness_pct": 50, "color_temp_kelvin": 3000}},
            "night": {"lighting": {"brightness_pct": 5, "color_temp_kelvin": 2200}},
        },
        "features": {
            "lock_eligible": False,
            "night_light": True,
            "media_eligible": True,
            "ventilation_eligible": False,
        },
        "posture_source": "sun",  # or "schedule", "input_select"
    }
)
```

### 4.2 Intent Token (Runtime)

Stored in-memory in the TokenRegistry (not persisted — tokens are ephemeral):

```python
@dataclass
class IntentToken:
    token_id: str          # UUID4
    area_id: str
    domain: str            # lighting, climate, media, ventilation, lock
    intent_type: str       # active, override, schedule
    claimant_id: str       # Entity ID that created the token
    action_value: str | None  # Optional: e.g., "tv_off", "fan_low"
    expires_at: datetime | None  # None = -1 (indefinite)
    created_at: datetime
    labels: list[str] | None  # Optional targeted labels within area
```

**Priority Hierarchy (highest wins):**
1. `override` (manual switches, guest mode)
2. `schedule` (time-based baselines)
3. `active` (sensor events)

---

## 5. Services

### 5.1 `context_engine.add_intent`

Push an intent token into the registry for evaluation.

**Service Schema:**
```yaml
service: context_engine.add_intent
data:
  area_id: living_room          # Required
  domain: lighting              # Required: lighting | climate | media | ventilation | lock
  intent_type: active             # Required: active | override | schedule
  claimant_id: binary_sensor.lr_motion  # Required: entity_id
  action_value: null            # Optional: domain-specific string
  seconds: 300                  # Required: 0 | positive int | -1 (indefinite)
  labels: []                      # Optional: subset of area entities to target
```

**Behavior:**
- Adds token to TokenRegistry.
- Triggers immediate evaluation for that area+domain.
- If `seconds: 0`, evaluates once and discards.
- If `seconds: -1`, persists until `remove_intent` called.
- If `seconds > 0`, schedules automatic expiry.
- Emits `context_engine_intent_evaluated` event.

### 5.2 `context_engine.remove_intent`

Remove a specific token or all tokens from a claimant.

**Service Schema:**
```yaml
service: context_engine.remove_intent
data:
  area_id: living_room          # Required
  claimant_id: binary_sensor.lr_motion  # Required
  domain: lighting              # Optional: if omitted, removes all domains
  intent_type: active           # Optional: if omitted, removes all types
```

### 5.3 `context_engine.refresh_profile`

Force rebuild of an area's profile sensor from current entity registry + labels.

**Service Schema:**
```yaml
service: context_engine.refresh_profile
data:
  area_id: living_room  # Required
```

### 5.4 `context_engine.set_posture`

Manually set or override the room's current posture.

**Service Schema:**
```yaml
service: context_engine.set_posture
data:
  area_id: living_room
  posture: evening      # morning | daylight | evening | night | null (auto)
```

---

## 6. MQTT Discovery (Auto-Provisioning)

When `mqtt_enabled: true` for an area, the integration publishes discovery payloads allowing the profile sensor to be consumed by external systems or other HA instances.

### 6.1 Discovery Topic Pattern

```
homeassistant/sensor/<area_id>_profile/config
```

### 6.2 Discovery Payload

```json
{
  "name": "Living Room Profile",
  "unique_id": "context_engine_living_room_profile",
  "state_topic": "context_engine/living_room/profile/state",
  "json_attributes_topic": "context_engine/living_room/profile/attributes",
  "availability_topic": "context_engine/living_room/availability",
  "device": {
    "identifiers": ["context_engine_living_room"],
    "name": "Living Room Context",
    "model": "Context Engine",
    "manufacturer": "Context Engine"
  }
}
```

### 6.3 State Topics

| Topic | Payload |
|-------|---------|
| `context_engine/<area_id>/profile/state` | Compact JSON profile |
| `context_engine/<area_id>/profile/attributes` | Flattened attributes for MQTT consumers |
| `context_engine/<area_id>/availability` | `online` / `offline` |
| `context_engine/<area_id>/tokens/+` | Individual token events |

---

## 7. Internal Components

### 7.1 `ContextCoordinator` (DataUpdateCoordinator)

- Manages per-area refresh cycles.
- Listens to HA `area_registry_updated` and `entity_registry_updated` events.
- Rebuilds profile sensors when labels or area assignments change.
- Evaluates token expiration via `async_track_point_in_time`.

### 7.2 `TokenRegistry`

- Thread-safe (async) in-memory store.
- Methods: `add_token()`, `remove_token()`, `get_active_for_area()`, `evaluate_priority()`.
- Automatically prunes expired tokens on evaluation.

### 7.3 `ProfileBuilder`

- Queries `entity_registry` and `area_registry` from HA core.
- Maps labels → `topo__` keys via configurable role_mappings.
- Assembles final JSON payload for sensor state.

### 7.4 `IntentEvaluator`

- Core logic: given an area_id + domain, resolve which intent_type wins.
- Considers `lock_eligible` + door state for hold logic.
- Returns target state from policy map or action_value override.
- Calls `homeassistant.turn_on` / `turn_off` / `climate.set_...` etc. via `hass.services.async_call`.

---

## 8. Blueprints (Bundled Automations)

The integration ships with four blueprints installed automatically:

### 8.1 Blueprint: `commission_entity.yaml`
**Trigger:** `entity_registry_updated` (label or area change)
**Action:** Calls `context_engine.refresh_profile` for affected areas.

### 8.2 Blueprint: `universal_controller.yaml`
**Trigger:** `context_engine_intent_evaluated` event
**Action:** Calls service based on `resolution.target_state`.

### 8.3 Blueprint: `sensor_to_intent.yaml`
**Trigger:** Any `state_changed` on labeled entities
**Action:** Translates sensor state → `context_engine.add_intent` call.
- Motion detected → `active` token, `seconds: 300`
- Door closed + presence active → `active` token + check `lock_eligible`
- Media playing → `active` token, `seconds: -1`
- Physical switch pressed → `override` token, `seconds: -1`

### 8.4 Blueprint: `janitor_cleanup.yaml`
**Trigger:** Every 60 seconds or on token expiry
**Action:** Scans TokenRegistry, issues `remove_intent` for expired tokens, evaluates affected areas.

---

## 9. Config Flow

### Step 1: Discovery
- Check if MQTT integration is loaded.
- Discover all HA areas.
- Pre-fill role mappings with sensible defaults.

### Step 2: Area Selection
- Multi-select which areas to enable.
- Each area becomes its own config entry (allows granular disable).

### Step 3: Role Mapping Review
- Show table: Label → Topo Key.
- User can add/remove custom labels.
- Defaults: `presence`, `door`, `light`, `fan`, `media`, `climate`.

### Step 4: Policy Configuration
- Per-area time-of-day sliders for brightness, color temp, etc.
- Or skip and configure via UI later (OptionsFlow).

### Step 5: Feature Flags
- Toggle `lock_eligible`, `night_light`, `media_eligible`, etc.

---

## 10. Options Flow

After setup, users can reconfigure any area:
- Change role mappings
- Edit policy maps per posture
- Toggle features
- Enable/disable MQTT discovery
- Adjust token expiry defaults

---

## 11. File Structure

```
custom_components/context_engine/
├── __init__.py              # Setup, coordinator, registry init
├── config_flow.py           # ConfigFlow + OptionsFlow
├── const.py                 # Domain, defaults, service names
├── coordinator.py           # ContextCoordinator
├── manifest.json            # Integration manifest
├── sensor.py                # Profile Sensor platform
├── event.py                 # Context Event platform (optional)
├── services.yaml            # Service descriptions for UI
├── strings.json             # Translations
├── blueprints/
│   ├── commission_entity.yaml
│   ├── universal_controller.yaml
│   ├── sensor_to_intent.yaml
│   └── janitor_cleanup.yaml
└── services/
    ├── __init__.py
    ├── add_intent.py
    ├── remove_intent.py
    ├── refresh_profile.py
    └── set_posture.py
```

---

## 12. Manifest

```json
{
  "domain": "context_engine",
  "name": "Context Engine",
  "codeowners": [],
  "config_flow": true,
  "dependencies": ["mqtt"],
  "documentation": "https://github.com/...",
  "iot_class": "local_push",
  "requirements": [],
  "version": "0.1.0"
}
```

**Note:** MQTT is an optional dependency at runtime (graceful degradation if MQTT not configured), but required for auto-discovery features.

---

## 13. Implementation Phases

### Phase 1: Foundation (MVP)
- [ ] `sensor` platform with static profile (no live token evaluation)
- [ ] `config_flow` for area selection + role mapping
- [ ] `context_engine.refresh_profile` service
- [ ] `ProfileBuilder` querying entity/area registries
- [ ] Blueprint: `commission_entity.yaml`

### Phase 2: Intent System
- [ ] `TokenRegistry` in-memory store
- [ ] `context_engine.add_intent` + `remove_intent` services
- [ ] `IntentEvaluator` with priority hierarchy
- [ ] Blueprint: `sensor_to_intent.yaml`
- [ ] Blueprint: `janitor_cleanup.yaml`
- [ ] `context_engine.set_posture` service

### Phase 3: Actuation
- [ ] `event` platform for `context_engine_intent_evaluated`
- [ ] Blueprint: `universal_controller.yaml`
- [ ] Service dispatch to `light.turn_on`, `climate.set_...`, etc.
- [ ] `lock_eligible` logic (door + presence = hold)

### Phase 4: MQTT + Polish
- [ ] MQTT discovery publishing
- [ ] OptionsFlow for post-setup edits
- [ ] `strings.json` translations
- [ ] HACS compatibility
- [ ] Documentation + tests

---

## 14. Open Questions

1. Should posture (morning/daylight/evening/night) be derived from sun elevation, fixed times, or an input_select?
   → Proposed: Default to sun + offset, overrideable per-area.

2. How should the integration handle entities in multiple areas?
   → Proposed: Token includes `area_id`; entity can contribute to multiple profiles.

3. Should token evaluation run synchronously on `add_intent` or queue for async batch?
   → Proposed: Immediate async evaluation to avoid latency on physical switches.

4. How to handle `action_value` schema validation per domain?
   → Proposed: Domain-specific validators in `IntentEvaluator`.

5. Should there be a centralized "all areas" profile sensor (e.g., `sensor.home_profile`)?
   → Future: Aggregate via template or separate `context_engine.aggregate` service.

---

## 15. Example User Journey

**Day 0:** Install via HACS. Config flow discovers 8 areas. User enables 5. Reviews role mappings — defaults look fine.

**Day 1:** User buys a new mmWave presence sensor. In HA GUI, assigns it to `Master Bedroom` area, adds `presence` label. Commissioning automation fires. `sensor.master_bedroom_profile` now lists the new sensor in `topo__presence_entities`. No YAML edited.

**Day 2:** User adds a blueprint automation: when `media_player.mb_tv` starts playing, call `add_intent` → `area_id: master_bedroom`, `domain: media`, `intent_type: active`, `seconds: -1`. TV turns on, lights dim. When user presses Pico switch to raise lights, `override` token takes priority. TV turns off, override remains until Pico switch pressed again.

**Day 3:** User checks `sensor.master_bedroom_profile` state. Sees active tokens, features, policy. Understands why lights are at 40% without reading YAML.

---

*End of spec.*
