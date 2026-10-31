# Context Engine for Home Assistant

A context-driven automation framework that eliminates maintenance by treating rooms as software objects. Replaces brittle entity-ID-based automations with an abstract intent-token system.

## What It Does

Instead of writing automations that reference `binary_sensor.powder_room_motion` directly, Context Engine gives each room a **Profile Sensor** that maps **roles** (`presence`, `light`, `door`, `media`, etc.) to whatever physical devices you have in that area. Swap a Zigbee motion sensor for mmWave radar? Just change the label in the HA UI — zero script edits.

## Core Concepts

- **Profile Sensors** (`sensor.<area>_profile`) — Live JSON registry of each room's topology, policy map, and features
- **Role Mapping** — Tag entities with labels (`presence`, `light`, `fan`) and the profile auto-populates
- **Intent Tokens** — Events push abstract tokens (`active`, `override`, `schedule`) with expiry instead of commanding devices directly
- **Priority Resolution** — `override` > `schedule` > `active`; the engine resolves what a room means, not which sensor fired

## Quick Install

### Option 1: HACS (Recommended)

1. Open HACS → Custom repositories
2. Add `https://github.com/NelsonWagner/homeaissistant`
3. Install **Context Engine**
4. Restart Home Assistant

### Option 2: Manual

```bash
git clone https://github.com/NelsonWagner/homeaissistant.git
cd homeaissistant
chmod +x install.sh
./install.sh --restart
```

Or copy `custom_components/context_engine/` into your HA `config/custom_components/` and restart.

## Setup

1. **Add the integration** — Settings → Devices & services → Add integration → Context Engine
2. **Select areas** to enable (one config entry per area)
3. **Review role mappings** — default labels: `presence`, `door`, `light`, `fan`, `media`, `climate`
4. **Set policy defaults** per posture (morning / daylight / evening / night)
5. **Toggle features** like `lock_eligible`, `night_light`, `media_eligible`

## Label Your Entities

Go to **Settings → Devices & services → Entities**, select an entity, open settings (gear icon), and add labels:

| Label | Meaning |
|-------|---------|
| `presence` | Motion / occupancy sensors |
| `door` | Door / window contact sensors |
| `light` | Light entities in this area |
| `fan` | Fan / ventilation entities |
| `media` | Media players |
| `climate` | Thermostats / climate entities |

Once labeled, `sensor.<area>_profile` will automatically list them under `topo__*` attributes.

## Services

| Service | Purpose |
|---------|---------|
| `context_engine.add_intent` | Push an intent token into the registry |
| `context_engine.remove_intent` | Remove tokens by claimant |
| `context_engine.refresh_profile` | Force rebuild of a room's profile |
| `context_engine.set_posture` | Manually set posture (morning/daylight/evening/night) |

### Example: Add Intent

```yaml
service: context_engine.add_intent
data:
  area_id: living_room
  domain: lighting
  intent_type: active
  claimant_id: binary_sensor.lr_motion
  seconds: 300
```

## Blueprints (Included)

The integration ships with four blueprints under `custom_components/context_engine/blueprints/`:

- **commission_entity** — Rebuilds profiles when labels or area assignments change
- **sensor_to_intent** — Translates motion/media/door events into intent tokens
- **universal_controller** — Resolves winning intent and calls HA services
- **janitor_cleanup** — Prunes expired tokens every 60 seconds

Import them via **Settings → Automations & Scenes → Blueprints → Import blueprint**.

## Architecture

```
Sensor fires → sensor_to_intent blueprint → context_engine.add_intent
                                              ↓
         TokenRegistry (in-memory priority stack)
                                              ↓
         IntentEvaluator → context_engine_intent_evaluated event
                                              ↓
         universal_controller blueprint → light.turn_on / climate.set_...
```

## File Structure

```
custom_components/context_engine/
├── __init__.py              # Setup, entry config
├── config_flow.py           # Config + Options flow
├── const.py                 # Constants
├── coordinator.py           # ContextCoordinator + TokenRegistry
├── manifest.json            # Integration manifest
├── sensor.py                # Profile sensor platform
├── event.py                 # Intent evaluated events
├── services.yaml            # Service UI definitions
├── strings.json             # Translations
├── blueprints/
│   ├── commission_entity.yaml
│   ├── sensor_to_intent.yaml
│   ├── universal_controller.yaml
│   └── janitor_cleanup.yaml
└── services/
    ├── add_intent.py
    ├── remove_intent.py
    ├── refresh_profile.py
    └── set_posture.py
```

## License

MIT
