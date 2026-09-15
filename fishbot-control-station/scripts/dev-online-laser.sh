#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
WORKBENCH_ROOT="$(cd "$ROOT_DIR/../.." && pwd -P)"
LASER_WS="${LASER_WS:-$WORKBENCH_ROOT/fishbot_laser_ws}"
ROSBRIDGE_PORT="${ROSBRIDGE_PORT:-9091}"
BACKEND_PORT="${BACKEND_PORT:-8080}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_LOG="${TMPDIR:-/tmp}/fishbot-station-backend-laser.log"
ROSBRIDGE_LOG="${TMPDIR:-/tmp}/fishbot-station-rosbridge-laser.log"

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

source "$WORKBENCH_ROOT/.ros2_env" "${FISHBOT_ROS_DISTRO:-jazzy}"
if [[ ! -f "$LASER_WS/install/setup.bash" ]]; then
  echo "Missing laser overlay: $LASER_WS/install/setup.bash" >&2
  exit 1
fi
for station_port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  if ss -H -ltn "sport = :$station_port" | grep -q .; then
    echo "Port $station_port is occupied; stop its owner before starting this station." >&2
    exit 1
  fi
done

set +u
source "$LASER_WS/install/setup.bash"
set -u
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"

if ! ss -ltn | grep -q ":${ROSBRIDGE_PORT} "; then
  ros2 launch rosbridge_server rosbridge_websocket_launch.xml port:="${ROSBRIDGE_PORT}" >"$ROSBRIDGE_LOG" 2>&1 &
  ROSBRIDGE_PID=$!
fi

for _ in $(seq 1 20); do
  if ss -ltn | grep -q ":${ROSBRIDGE_PORT} "; then
    break
  fi
  sleep 1
done

echo "probing /scan ..."
if timeout 8 "$WORKBENCH_ROOT/tools/fishbot_laser_scan_probe.sh" >/tmp/fishbot-laser-probe.out 2>&1; then
  cat /tmp/fishbot-laser-probe.out
elif grep -q 'RECV count=' /tmp/fishbot-laser-probe.out 2>/dev/null; then
  cat /tmp/fishbot-laser-probe.out
  echo "probe: received /scan data before timeout; continuing with live stack"
else
  cat /tmp/fishbot-laser-probe.out >&2 || true
  echo "warning: /scan probe did not receive data; keep the lidar driver running in ${LASER_WS}" >&2
fi

cd "$BACKEND_DIR"
CONTROL_ROSBRIDGE_HOST=127.0.0.1 CONTROL_ROSBRIDGE_PORT="${ROSBRIDGE_PORT}" LASER_ROSBRIDGE_HOST=127.0.0.1 LASER_ROSBRIDGE_PORT="${ROSBRIDGE_PORT}" SERVER_PORT="${BACKEND_PORT}" ./gradlew --no-daemon bootRun >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/api/v1/connection" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "laser rosbridge: ws://127.0.0.1:${ROSBRIDGE_PORT}/"
echo "rosbridge log:  ${ROSBRIDGE_LOG:-already running}"
echo "backend log:    $BACKEND_LOG"
echo "frontend:       http://127.0.0.1:${FRONTEND_PORT}"
echo "backend:        http://127.0.0.1:${BACKEND_PORT}"

cd "$FRONTEND_DIR"
BACKEND_PORT="$BACKEND_PORT" npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort
