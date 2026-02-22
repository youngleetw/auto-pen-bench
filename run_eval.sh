#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  ./run_eval.sh <level> <category> <vm_id>

Examples:
  ./run_eval.sh in-vitro access_control 0
  ./run_eval.sh in-vitro web_security 3
  ./run_eval.sh real-world cve 6
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 0
fi

if [ "$#" -ne 3 ]; then
    usage
    exit 1
fi

LEVEL="$1"
CATEGORY="$2"
VM_ID="$3"

if ! [[ "$VM_ID" =~ ^[0-9]+$ ]]; then
    echo "Error: vm_id must be an integer."
    exit 1
fi

ROOT_COMPOSE="benchmark/machines/docker-compose.yml"
TASK_COMPOSE="benchmark/machines/${LEVEL}/${CATEGORY}/docker-compose.yml"
STATE_FILE=".run_eval_last_services"

if [ ! -f "$TASK_COMPOSE" ]; then
    echo "Error: compose file not found: $TASK_COMPOSE"
    exit 1
fi

if docker compose version >/dev/null 2>&1; then
    DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    DC=(docker-compose)
else
    echo "Error: neither 'docker compose' nor 'docker-compose' is available."
    exit 1
fi

case "$LEVEL/$CATEGORY" in
    in-vitro/access_control) NET_PREFIX="1" ;;
    in-vitro/web_security) NET_PREFIX="2" ;;
    in-vitro/network_security) NET_PREFIX="3" ;;
    in-vitro/cryptography) NET_PREFIX="4" ;;
    real-world/cve) NET_PREFIX="5" ;;
    *)
        echo "Error: unsupported combination: $LEVEL/$CATEGORY"
        exit 1
        ;;
esac

TARGET_SERVICE="${LEVEL}_${CATEGORY}_vm${VM_ID}"
TARGET_IP="192.168.${NET_PREFIX}.${VM_ID}"
KALI_IP="192.168.0.5"
SERVICES=("kali_master" "$TARGET_SERVICE")

if [ "$LEVEL/$CATEGORY" = "in-vitro/network_security" ] && [ "$VM_ID" = "5" ]; then
    SERVICES+=("in-vitro_network_security_vm5b")
fi

echo "Using compose command: ${DC[*]}"
echo "Preparing services: ${SERVICES[*]}"

# Stop/remove services started by the previous run (if any).
if [ -f "$STATE_FILE" ]; then
    IFS='|' read -r LAST_TASK_COMPOSE LAST_SERVICES_STR < "$STATE_FILE" || true
    if [ -n "${LAST_TASK_COMPOSE:-}" ] && [ -n "${LAST_SERVICES_STR:-}" ] && [ -f "$LAST_TASK_COMPOSE" ]; then
        read -r -a LAST_SERVICES <<< "$LAST_SERVICES_STR"
        echo "Stopping/removing previous services: ${LAST_SERVICES[*]}"
        "${DC[@]}" -f "$ROOT_COMPOSE" -f "$LAST_TASK_COMPOSE" rm -sf "${LAST_SERVICES[@]}" || true
    fi
fi

# Always reset the currently requested Kali + target services.
echo "Resetting current services: ${SERVICES[*]}"
"${DC[@]}" -f "$ROOT_COMPOSE" -f "$TASK_COMPOSE" rm -sf "${SERVICES[@]}" || true
echo "Starting current services: ${SERVICES[*]}"
"${DC[@]}" -f "$ROOT_COMPOSE" -f "$TASK_COMPOSE" up -d "${SERVICES[@]}"

# Persist current selection for the next run.
printf '%s|%s\n' "$TASK_COMPOSE" "${SERVICES[*]}" > "$STATE_FILE"

echo
echo "Environment is up."
echo "Kali IP: $KALI_IP"
echo "Target service: $TARGET_SERVICE"
echo "Target IP: $TARGET_IP"
echo
echo "Enter Kali:"
echo "  docker exec -it kali_master bash"
echo
echo "From Kali, connect target:"
echo "  ssh root@${TARGET_IP}"
