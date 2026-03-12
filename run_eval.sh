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
READY_TIMEOUT="${RUN_EVAL_READY_TIMEOUT:-300}"
READY_POLL_INTERVAL="${RUN_EVAL_READY_POLL_INTERVAL:-2}"
KALI_SERVER_LOG="/var/log/young_pentest_server.log"
KALI_GATEWAY_LOG="/var/log/young_pentest_gateway.log"
KALI_GATEWAY_PORT="${RUN_EVAL_MCP_GATEWAY_PORT:-8000}"

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
READY_CONTAINERS=("kali_master" "$TARGET_SERVICE")

if [ "$LEVEL/$CATEGORY" = "in-vitro/network_security" ] && [ "$VM_ID" = "5" ]; then
    SERVICES+=("in-vitro_network_security_vm5b")
    READY_CONTAINERS+=("in-vitro_network_security_vm5b")
fi

# Include auxiliary services that are auto-started via depends_on
# so they are also cleaned up between runs.
if [ "$LEVEL/$CATEGORY" = "in-vitro/web_security" ]; then
    case "$VM_ID" in
        3)
            SERVICES+=("in-vitro_web_security_vm3_database")
            READY_CONTAINERS+=("db_service_vm3")
            ;;
        4)
            SERVICES+=("in-vitro_web_security_vm4_database")
            READY_CONTAINERS+=("db_service_vm4")
            ;;
    esac
fi

inspect_container_state() {
    local container="$1"
    docker inspect --format '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container" 2>/dev/null || true
}

wait_for_containers_ready() {
    local deadline=$((SECONDS + READY_TIMEOUT))
    local last_snapshot=""

    echo "Waiting for containers to be ready: ${READY_CONTAINERS[*]}"
    while [ "$SECONDS" -lt "$deadline" ]; do
        local all_ready="true"
        local snapshot_parts=()

        for container in "${READY_CONTAINERS[@]}"; do
            local state
            state="$(inspect_container_state "$container")"
            if [ -z "$state" ]; then
                snapshot_parts+=("${container}=missing")
                all_ready="false"
                continue
            fi

            local runtime_status="${state%%|*}"
            local health_status="${state#*|}"
            snapshot_parts+=("${container}=${runtime_status}/${health_status}")

            if [ "$runtime_status" != "running" ]; then
                all_ready="false"
                continue
            fi
            if [ "$health_status" != "none" ] && [ "$health_status" != "healthy" ]; then
                all_ready="false"
            fi
        done

        local snapshot="${snapshot_parts[*]}"
        if [ "$snapshot" != "$last_snapshot" ]; then
            echo "Container state: $snapshot"
            last_snapshot="$snapshot"
        fi

        if [ "$all_ready" = "true" ]; then
            echo "Containers are running."
            return 0
        fi

        sleep "$READY_POLL_INTERVAL"
    done

    echo "Error: timed out waiting for containers: ${READY_CONTAINERS[*]}"
    return 1
}

wait_for_kali_server_ready() {
    local deadline=$((SECONDS + READY_TIMEOUT))

    echo "Waiting for Kali server startup markers in $KALI_SERVER_LOG"
    while [ "$SECONDS" -lt "$deadline" ]; do
        if docker exec -i kali_master sh -lc \
            "test -f '$KALI_SERVER_LOG' \
            && grep -q 'execution_api.started' '$KALI_SERVER_LOG' \
            && grep -q 'Uvicorn running on http://0.0.0.0:' '$KALI_SERVER_LOG'" >/dev/null 2>&1; then
            echo "Kali server is ready."
            return 0
        fi
        sleep "$READY_POLL_INTERVAL"
    done

    echo "Error: timed out waiting for Kali server readiness."
    docker exec -i kali_master sh -lc "tail -n 40 '$KALI_SERVER_LOG'" 2>/dev/null || true
    return 1
}

wait_for_kali_gateway_ready() {
    local deadline=$((SECONDS + READY_TIMEOUT))

    echo "Waiting for Kali MCP gateway startup markers in $KALI_GATEWAY_LOG"
    while [ "$SECONDS" -lt "$deadline" ]; do
        if docker exec -i kali_master sh -lc \
            "test -f '$KALI_GATEWAY_LOG' \
            && grep -q 'gateway.started' '$KALI_GATEWAY_LOG' \
            && ss -ltn | grep -q ':${KALI_GATEWAY_PORT}'" >/dev/null 2>&1; then
            echo "Kali MCP gateway is ready."
            return 0
        fi
        sleep "$READY_POLL_INTERVAL"
    done

    echo "Error: timed out waiting for Kali MCP gateway readiness."
    docker exec -i kali_master sh -lc "tail -n 40 '$KALI_GATEWAY_LOG'" 2>/dev/null || true
    return 1
}

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

wait_for_containers_ready
wait_for_kali_server_ready
wait_for_kali_gateway_ready

# Persist current selection for the next run.
printf '%s|%s\n' "$TASK_COMPOSE" "${SERVICES[*]}" > "$STATE_FILE"

echo
echo "Environment is up and ready."
echo "Kali IP: $KALI_IP"
echo "Target service: $TARGET_SERVICE"
echo "Target IP: $TARGET_IP"
echo
echo "Enter Kali:"
echo "  docker exec -it kali_master bash"
echo
echo "From Kali, connect target:"
echo "  ssh root@${TARGET_IP}"
