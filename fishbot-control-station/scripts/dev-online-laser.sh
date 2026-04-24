#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
LASER_WS="${LASER_WS:-/home/muqiao/dev/ros2/fishbot_laser_ws}"
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

# Clear stale dev servers so this script always owns the expected ports.
fuser -k "${BACKEND_PORT}/tcp" 2>/dev/null || true
fuser -k "${FRONTEND_PORT}/tcp" 2>/dev/null || true
sleep 1

set +u
source /opt/ros/humble/setup.bash
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
if timeout 8 /home/muqiao/dev/ros2/tools/fishbot_laser_scan_probe.sh >/tmp/fishbot-laser-probe.out 2>&1; then
  cat /tmp/fishbot-laser-probe.out
elif grep -q 'RECV count=' /tmp/fishbot-laser-probe.out 2>/dev/null; then
  cat /tmp/fishbot-laser-probe.out
  echo "probe: received /scan data before timeout; continuing with live stack"
else
  cat /tmp/fishbot-laser-probe.out >&2 || true
  echo "warning: /scan probe did not receive data; keep the lidar driver running in ${LASER_WS}" >&2
fi

cd "$BACKEND_DIR"
ROSBRIDGE_HOST=127.0.0.1 ROSBRIDGE_PORT="${ROSBRIDGE_PORT}" ./gradlew --no-daemon bootRun >"$BACKEND_LOG" 2>&1 &
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
npm run dev -- --host 0.0.0.0
