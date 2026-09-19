#!/usr/bin/env bash
# Start the whole engine_server stack in one terminal.
#
#   ./scripts/dev.sh           # redis x2 + api + backtest worker
#   ./scripts/dev.sh --live    # ... and the live (paper) supervisor
#
# Ctrl+C stops everything, including the Redis instances this script started.
set -euo pipefail

cd "$(dirname "$0")/.."

WITH_LIVE=0
[[ "${1:-}" == "--live" ]] && WITH_LIVE=1

command -v redis-server >/dev/null || {
  echo "redis-server not found. Install it with:  sudo apt install -y redis-server" >&2
  exit 1
}

mkdir -p catalog artifacts raw run/kill logs

PIDS=()
STARTED_REDIS=()

cleanup() {
  echo
  echo "shutting down..."
  # SIGTERM first: the live supervisor releases its account leases on it.
  for pid in "${PIDS[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  wait "${PIDS[@]:-}" 2>/dev/null || true
  for port in "${STARTED_REDIS[@]:-}"; do redis-cli -p "$port" shutdown nosave 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM

start_redis() {
  local port=$1 name=$2
  if redis-cli -p "$port" ping >/dev/null 2>&1; then
    echo "redis :$port already running ($name) -- reusing"
  else
    echo "starting redis :$port ($name)"
    redis-server --port "$port" --daemonize yes --appendonly no
    STARTED_REDIS+=("$port")
    until redis-cli -p "$port" ping >/dev/null 2>&1; do sleep 0.2; done
  fi
}

# Queue + live desired-state. Separate INSTANCE from the cache below, not a
# separate db index -- Nautilus's DatabaseConfig ignores the trailing /0.
start_redis 6379 "queue"
[[ $WITH_LIVE == 1 ]] && start_redis 6380 "nautilus cache"

echo "starting api        -> http://localhost:8000/docs"
uv run fastapi dev src/engine/api/app.py --port 8000 & PIDS+=($!)

echo "starting worker     -> arq"
uv run arq engine.worker.main.WorkerSettings & PIDS+=($!)

if [[ $WITH_LIVE == 1 ]]; then
  echo "starting live       -> engine.live.main (paper)"
  uv run python -m engine.live.main & PIDS+=($!)
fi

echo
echo "all up. Ctrl+C to stop."
wait -n
