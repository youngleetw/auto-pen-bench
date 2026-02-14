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
SERVICES=("kali_master" "$TARGET_SERVICE")

if [ "$LEVEL/$CATEGORY" = "in-vitro/network_security" ] && [ "$VM_ID" = "5" ]; then
    SERVICES+=("in-vitro_network_security_vm5b")
fi

echo "Using compose command: ${DC[*]}"
echo "Starting services: ${SERVICES[*]}"

"${DC[@]}" -f "$ROOT_COMPOSE" -f "$TASK_COMPOSE" up -d "${SERVICES[@]}"

echo
echo "Environment is up."
echo "Target service: $TARGET_SERVICE"
echo "Target IP: $TARGET_IP"
echo
echo "Enter Kali:"
echo "  docker exec -it kali_master bash"
echo
echo "From Kali, connect target:"
echo "  ssh root@${TARGET_IP}"
