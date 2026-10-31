#!/usr/bin/env bash
# Context Engine — Home Assistant Custom Component Installer
# Usage: ./install.sh [--restart] [--config-dir /path/to/ha/config]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPONENT_NAME="context_engine"
REQUIRED_DIRS=("blueprints" "services")

# ── Colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ── Defaults ──
RESTART=false
HA_CONFIG_DIR=""
DETECTED_DIR=""

# ── Helpers ──
log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

detect_ha_config() {
    local candidates=(
        "/config"
        "/home/homeassistant/.homeassistant"
        "/homeassistant/config"
        "${HOME}/.homeassistant"
        "${HOME}/homeassistant/config"
        "/var/lib/homeassistant"
        "/opt/homeassistant/config"
    )

    # Check if we're running inside the HA container
    if [[ -d "/config" && -f "/config/configuration.yaml" ]]; then
        DETECTED_DIR="/config"
        return 0
    fi

    # Look for HA config by finding configuration.yaml
    for dir in "${candidates[@]}"; do
        if [[ -f "${dir}/configuration.yaml" ]]; then
            DETECTED_DIR="${dir}"
            return 0
        fi
    done

    # Try to find via process
    if command -v pgrep &>/dev/null; then
        local ha_proc
        ha_proc=$(pgrep -a -f "homeassistant" 2>/dev/null | head -1 || true)
        if [[ -n "${ha_proc}" ]]; then
            log_warn "Found HA process but couldn't determine config directory."
        fi
    fi

    return 1
}

validate_component() {
    local src="${SCRIPT_DIR}/custom_components/${COMPONENT_NAME}"
    log_info "Validating component files..."

    local required_files=(
        "__init__.py"
        "manifest.json"
        "config_flow.py"
        "const.py"
        "coordinator.py"
        "sensor.py"
        "event.py"
        "services.yaml"
        "strings.json"
    )

    for f in "${required_files[@]}"; do
        if [[ ! -f "${src}/${f}" ]]; then
            log_error "Missing required file: ${f}"
            exit 1
        fi
    done

    for d in "${REQUIRED_DIRS[@]}"; do
        if [[ ! -d "${src}/${d}" ]]; then
            log_error "Missing required directory: ${d}/"
            exit 1
        fi
    done

    # Quick Python syntax check if python3 is available
    if command -v python3 &>/dev/null; then
        log_info "Running Python syntax validation..."
        find "${src}" -name "*.py" -exec python3 -m py_compile {} + || {
            log_error "Python syntax validation failed"
            exit 1
        }
    else
        log_warn "python3 not found — skipping syntax validation"
    fi

    # Validate manifest.json
    if command -v python3 &>/dev/null; then
        python3 -c "
import json, sys
try:
    with open('${src}/manifest.json') as f:
        data = json.load(f)
    assert 'domain' in data and data['domain'] == '${COMPONENT_NAME}', 'domain mismatch'
    assert 'config_flow' in data, 'missing config_flow'
    print('manifest.json: OK')
except Exception as e:
    print(f'manifest.json: INVALID - {e}', file=sys.stderr)
    sys.exit(1)
" || exit 1
    fi

    log_info "Validation passed"
}

install_component() {
    local dest="${HA_CONFIG_DIR}/custom_components/${COMPONENT_NAME}"
    local src="${SCRIPT_DIR}/custom_components/${COMPONENT_NAME}"

    log_info "Installing Context Engine to: ${dest}"

    # Backup existing
    if [[ -d "${dest}" ]]; then
        local backup="${dest}.backup.$(date +%Y%m%d%H%M%S)"
        log_warn "Existing installation found — backing up to ${backup}"
        cp -r "${dest}" "${backup}"
        rm -rf "${dest}"
    fi

    # Create directory structure
    mkdir -p "${dest}"
    cp -r "${src}/"* "${dest}/"

    # Verify
    if [[ -f "${dest}/manifest.json" && -f "${dest}/__init__.py" ]]; then
        log_info "Installation complete"
    else
        log_error "Installation verification failed"
        exit 1
    fi
}

print_next_steps() {
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo -e "${GREEN}  Context Engine installed successfully!${NC}"
    echo "═══════════════════════════════════════════════════════════"
    echo ""
    echo "  Next steps:"
    echo ""
    echo "  1. Restart Home Assistant"
    if [[ "${RESTART}" == true ]]; then
        echo "     → The installer will handle this (see below)"
    else
        echo "     → Settings → System → Restart"
    fi
    echo ""
    echo "  2. Add the integration"
    echo "     → Settings → Devices & services → Add integration"
    echo "     → Search for 'Context Engine'"
    echo ""
    echo "  3. Label your entities in each area"
    echo "     → Settings → Devices & services → Entities"
    echo "     → Select entity → Settings (gear icon) → Labels"
    echo "     → Add labels: presence, light, door, fan, media, climate"
    echo ""
    echo "  4. Import blueprints (optional)"
    echo "     → Settings → Automations & Scenes → Blueprints"
    echo "     → Import blueprint → Paste one of these:"
    echo ""
    for bp in "${HA_CONFIG_DIR}/custom_components/${COMPONENT_NAME}/blueprints/"*.yaml; do
        local bp_name
        bp_name=$(basename "${bp}")
        echo "       ${bp_name}"
    done
    echo ""
    echo "═══════════════════════════════════════════════════════════"
}

restart_ha() {
    echo ""
    read -r -p "Restart Home Assistant now? [y/N] " answer
    if [[ "${answer,,}" =~ ^y(es)?$ ]]; then
        log_info "Attempting to restart Home Assistant..."

        # Try Home Assistant CLI (Supervised / OS)
        if command -v ha &>/dev/null; then
            ha core restart || {
                log_warn "HA CLI restart failed — restart manually via UI"
            }
            return
        fi

        # Try Docker
        local container_name
        container_name=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -i homeassistant | head -1 || true)
        if [[ -n "${container_name}" ]]; then
            log_info "Found Docker container: ${container_name}"
            read -r -p "Restart this container? [y/N] " docker_answer
            if [[ "${docker_answer,,}" =~ ^y(es)?$ ]]; then
                docker restart "${container_name}" || log_warn "Docker restart failed"
            fi
            return
        fi

        # Try systemd
        if systemctl is-active homeassistant &>/dev/null || systemctl is-active home-assistant@* &>/dev/null; then
            sudo systemctl restart homeassistant || sudo systemctl restart home-assistant@homeassistant || {
                log_warn "systemd restart failed"
            }
            return
        fi

        log_warn "Could not auto-detect restart method. Please restart manually."
    else
        log_info "Skipping restart. Remember to restart before using the integration."
    fi
}

# ── Parse args ──
while [[ $# -gt 0 ]]; do
    case "$1" in
        --restart)
            RESTART=true
            shift
            ;;
        --config-dir)
            HA_CONFIG_DIR="$2"
            shift 2
            ;;
        --help | -h)
            cat <<EOF
Context Engine Installer

Usage: ./install.sh [OPTIONS]

Options:
  --config-dir PATH    Path to Home Assistant config directory
  --restart            Prompt to restart Home Assistant after install
  -h, --help           Show this help

Examples:
  ./install.sh
  ./install.sh --config-dir /config --restart
  ./install.sh --config-dir /home/homeassistant/.homeassistant
EOF
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# ── Main ──
echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║       Context Engine — Home Assistant Installer          ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Detect HA config dir
if [[ -z "${HA_CONFIG_DIR}" ]]; then
    if detect_ha_config; then
        HA_CONFIG_DIR="${DETECTED_DIR}"
        log_info "Detected HA config directory: ${HA_CONFIG_DIR}"
    else
        log_error "Could not auto-detect Home Assistant config directory"
        echo ""
        echo "Please specify it manually:"
        echo "  ./install.sh --config-dir /path/to/homeassistant/config"
        echo ""
        echo "Common locations:"
        echo "  - /config                     (HA Container / HA OS)"
        echo "  - /home/homeassistant/.homeassistant  (venv install)"
        echo "  - /opt/homeassistant/config   (custom install)"
        exit 1
    fi
else
    if [[ ! -f "${HA_CONFIG_DIR}/configuration.yaml" ]]; then
        log_warn "Config dir doesn't contain configuration.yaml — proceeding anyway"
    fi
fi

validate_component
install_component
print_next_steps

if [[ "${RESTART}" == true ]]; then
    restart_ha
fi

log_info "Done."
