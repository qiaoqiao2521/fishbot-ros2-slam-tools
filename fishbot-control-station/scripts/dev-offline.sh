#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_LOG="${TMPDIR:-/tmp}/fishbot-station-backend-offline.log"

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

cd "$BACKEND_DIR"
STATION_TELEMETRY_MODE=offline ./gradlew --no-daemon bootRun >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8080/api/v1/connection >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "backend log: $BACKEND_LOG"
echo "frontend: http://127.0.0.1:5173"
echo "backend:  http://127.0.0.1:8080"

cd "$FRONTEND_DIR"
npm run dev -- --host 0.0.0.0
