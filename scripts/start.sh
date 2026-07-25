#!/usr/bin/env bash
# Start the Python API and Vite frontend for local/LAN development.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

API_PORT="${AGENT_WEB_PORT:-18080}"
WEB_PORT="${VITE_PORT:-5173}"

stop_port() {
  local port="$1"
  local pids

  pids="$(fuser -n tcp "$port" 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    return
  fi

  echo "Port $port is occupied by PID(s): $pids. Stopping them..."
  kill $pids 2>/dev/null || true

  for _ in {1..20}; do
    if ! fuser -n tcp "$port" >/dev/null 2>&1; then
      return
    fi
    sleep 0.25
  done

  echo "Port $port did not stop cleanly; forcing shutdown."
  kill -9 $pids 2>/dev/null || true
}

command -v uv >/dev/null || { echo "uv is required."; exit 1; }
command -v npm >/dev/null || { echo "npm is required."; exit 1; }

stop_port "$API_PORT"
stop_port "$WEB_PORT"

if [[ ! -d "$ROOT_DIR/web/node_modules" ]]; then
  echo "Installing frontend dependencies..."
  npm --prefix "$ROOT_DIR/web" install
fi

cleanup() {
  trap - EXIT INT TERM
  [[ -n "${API_PID:-}" ]] && kill "$API_PID" 2>/dev/null || true
  [[ -n "${WEB_PID:-}" ]] && kill "$WEB_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

cd "$ROOT_DIR"
echo "Starting API at http://127.0.0.1:$API_PORT"
# The API reads its model settings from .env. Clear stale shell overrides so a
# previous provider/model selection does not silently win over that file.
env -u AGENTSCOPE_MODEL_PROVIDER -u AGENTSCOPE_MODEL_NAME \
  AGENT_WEB_PORT="$API_PORT" uv run agent-web &
API_PID=$!

echo "Starting frontend at http://127.0.0.1:$WEB_PORT"
env VITE_API_PORT="$API_PORT" npm --prefix "$ROOT_DIR/web" run dev -- --host 0.0.0.0 --port "$WEB_PORT" &
WEB_PID=$!

echo "Open http://localhost:$WEB_PORT"
wait -n "$API_PID" "$WEB_PID"
