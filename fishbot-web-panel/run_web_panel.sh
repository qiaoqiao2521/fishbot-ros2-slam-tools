#!/usr/bin/env bash
# FishBot web panel launcher: one uvicorn process serving the PWA + API/WS.
# rclpy comes from the ROS 2 install via --system-site-packages; web deps
# (fastapi/uvicorn/httpx/pydantic) live in the local .venv.
set -euo pipefail

DIR="$(cd "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")" && pwd -P)"

DISTRO="${ROS_DISTRO:-}"
if [[ -z "$DISTRO" ]]; then
  for d in /opt/ros/*; do
    [[ -f "$d/setup.bash" ]] && DISTRO="$(basename "$d")" && break
  done
fi
if [[ -n "$DISTRO" && -f "/opt/ros/$DISTRO/setup.bash" ]]; then
  set +u
  # shellcheck disable=SC1091
  source "/opt/ros/$DISTRO/setup.bash"
  set -u
fi

# FishBot defaults: control link is micro-ROS UDP, not a USB serial stream;
# flip SERIAL_ENABLED=true on hosts that actually have the bottom serial.
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
export APP_HOST="${APP_HOST:-0.0.0.0}"
export APP_PORT="${APP_PORT:-8010}"
export SERIAL_ENABLED="${SERIAL_ENABLED:-false}"
export ROS_ENABLED="${ROS_ENABLED:-true}"

if [[ ! -x "$DIR/.venv/bin/python" ]]; then
  echo "fishbot-web-panel: first run - creating .venv (system-site-packages)"
  python3 -m venv --system-site-packages "$DIR/.venv"
  "$DIR/.venv/bin/pip" install --quiet -r "$DIR/backend/requirements.txt"
fi

cd "$DIR"
exec "$DIR/.venv/bin/python" -m uvicorn fishbot_app:app \
  --host "$APP_HOST" --port "$APP_PORT" --workers 1
