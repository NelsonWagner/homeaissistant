# Context Engine

**Context-driven automation for Home Assistant that eliminates maintenance.**

Instead of hardcoding entity IDs into automations, Context Engine treats each room as a software object. Label your devices (`presence`, `light`, `door`, etc.), and the engine abstracts intent so hardware swaps require zero script changes.

## Install

- **HACS:** Add this repo as a custom repository and install.
- **Manual:** Run `./install.sh` from the repo root.

## Quick Start

1. Install and restart Home Assistant
2. Go to **Settings → Devices & services → Add integration → Context Engine**
3. Select areas to enable
4. Label entities in each area (presence, light, door, fan, media, climate)
5. Import the bundled blueprints

## Docs

Full spec: `context_engine_spec.md` in the repo root.
