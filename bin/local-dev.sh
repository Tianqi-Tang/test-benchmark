#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-test-benchmark}"
COMPOSE=(docker compose -p "$PROJECT_NAME" -f "$ROOT_DIR/docker-compose.dev.yml")
READY_TIMEOUT_SECONDS="${DEV_READY_TIMEOUT:-120}"
TEST_BENCHMARK_WEB_HOST_PORT="${TEST_BENCHMARK_WEB_HOST_PORT:-18110}"
TEST_BENCHMARK_BACKEND_HOST_PORT="${TEST_BENCHMARK_BACKEND_HOST_PORT:-18111}"
TEST_BENCHMARK_DB_HOST_PORT="${TEST_BENCHMARK_DB_HOST_PORT:-18112}"
export TEST_BENCHMARK_WEB_HOST_PORT TEST_BENCHMARK_BACKEND_HOST_PORT TEST_BENCHMARK_DB_HOST_PORT

usage() {
  cat <<EOF
Usage:
  bin/local-dev.sh             Toggle local dev services: stop only when all core services are running, otherwise start
  bin/local-dev.sh start       Start local dev services
  bin/local-dev.sh pull        Pull base images used by local dev services
  bin/local-dev.sh stop        Stop local dev services, keeping containers and volumes
  bin/local-dev.sh restart     Stop, then start local dev services
  bin/local-dev.sh status      Show service status
  bin/local-dev.sh logs [svc]  Follow logs for all services or one service
  bin/local-dev.sh down        Remove containers and network, keeping volumes
  bin/local-dev.sh clean       Remove containers, network, and dev volumes

Local URLs:
  Web:     http://localhost:${TEST_BENCHMARK_WEB_HOST_PORT}
  Backend: http://localhost:${TEST_BENCHMARK_BACKEND_HOST_PORT}/health
  DB:      localhost:${TEST_BENCHMARK_DB_HOST_PORT}

Override local host ports with TEST_BENCHMARK_WEB_HOST_PORT
TEST_BENCHMARK_BACKEND_HOST_PORT, and TEST_BENCHMARK_DB_HOST_PORT.
EOF
}

all_core_services_running() {
  local running
  running="$("${COMPOSE[@]}" ps --services --filter status=running 2>/dev/null || true)"
  for service in postgres backend frontend; do
    if ! grep -qx "$service" <<<"$running"; then
      return 1
    fi
  done
  return 0
}

start_services() {
  "${COMPOSE[@]}" up -d --remove-orphans
  wait_for_service
  cat <<EOF

Local dev stack is ready:
  Web:     http://localhost:${TEST_BENCHMARK_WEB_HOST_PORT}
  Backend: http://localhost:${TEST_BENCHMARK_BACKEND_HOST_PORT}/health
  DB:      localhost:${TEST_BENCHMARK_DB_HOST_PORT}

Use "bin/local-dev.sh logs" to watch logs.
EOF
}

stop_services() {
  "${COMPOSE[@]}" stop
}

pull_services() {
  "${COMPOSE[@]}" pull
}

wait_for_service() {
  local backend_url="http://localhost:${TEST_BENCHMARK_BACKEND_HOST_PORT}/health"
  local frontend_url="http://localhost:${TEST_BENCHMARK_WEB_HOST_PORT}/"
  local deadline=$((SECONDS + READY_TIMEOUT_SECONDS))
  until curl -fsS "$backend_url" >/dev/null 2>&1 && curl -fsS "$frontend_url" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      echo "Timed out waiting for local dev services" >&2
      return 1
    fi
    sleep 2
  done
}

case "${1:-toggle}" in
  toggle)
    if all_core_services_running; then
      stop_services
    else
      start_services
    fi
    ;;
  start|up)
    start_services
    ;;
  pull)
    pull_services
    ;;
  stop)
    stop_services
    ;;
  restart)
    stop_services
    start_services
    ;;
  status|ps)
    "${COMPOSE[@]}" ps
    ;;
  logs)
    shift || true
    "${COMPOSE[@]}" logs -f "$@"
    ;;
  down)
    "${COMPOSE[@]}" down
    ;;
  clean)
    "${COMPOSE[@]}" down -v --remove-orphans
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    usage
    exit 1
    ;;
esac
