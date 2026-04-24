#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_LOG="${TMPDIR:-/tmp}/fishbot-station-backend-online.log"
ROSBRIDGE_LOG="${TMPDIR:-/tmp}/fishbot-station-rosbridge.log"

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "${ROSBRIDGE_PID:-}" ]] && kill -0 "$ROSBRIDGE_PID" 2>/dev/null; then
    kill "$ROSBRIDGE_PID" 2>/dev/null || true
    wait "$ROSBRIDGE_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

source /home/muqiao/dev/ros2/.ros2_env >/dev/null 2>&1

if ! ss -ltn | grep -q ':9090'; then
  ros2 launch rosbridge_server rosbridge_websocket_launch.xml port:=9090 >"$ROSBRIDGE_LOG" 2>&1 &
  ROSBRIDGE_PID=$!
fi

for _ in $(seq 1 20); do
  if ss -ltn | grep -q ':9090'; then
    break
  fi
  sleep 1
done

cd "$BACKEND_DIR"
./gradlew --no-daemon bootRun >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8080/api/v1/connection >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "rosbridge log: ${ROSBRIDGE_LOG:-already running}"
echo "backend log:   $BACKEND_LOG"
echo "frontend:      http://127.0.0.1:5173"
echo "backend:       http://127.0.0.1:8080"

cd "$FRONTEND_DIR"
npm run dev -- --host 0.0.0.0
