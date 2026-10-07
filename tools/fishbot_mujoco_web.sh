#!/usr/bin/env bash
set -euo pipefail
_patrol_project="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# ROS setup files intentionally probe optional, unset environment variables.
set +u
source "$_patrol_project/tools/fishbot_mujoco_env.sh"
set -u
_patrol_frontend="$_patrol_project/apps/fishbot-control-station/frontend"
_patrol_runs="$_patrol_project/workspaces/fishbot_mujoco_ws/.runs/web"
mkdir -p "$_patrol_runs"
if [[ ! -x "$_patrol_frontend/node_modules/.bin/vite" ]]; then
    echo 'Frontend dependencies missing: run npm ci in apps/fishbot-control-station/frontend.' >&2
    exit 1
fi
# Refuse occupied task ports instead of stopping an existing user's service.
python3 - <<'PY'
import socket
for port in (5173, 9070):
    with socket.socket() as sock:
        # A stopped task may leave TIME_WAIT sockets, which are not live servers.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('127.0.0.1', port))
        except OSError as error:
            raise SystemExit(f'Port {port} is already in use; close its previous task before starting this one: {error}')
PY
_patrol_frontend_pid=''
cleanup() {
    if [[ -n "$_patrol_frontend_pid" ]] && (( _patrol_frontend_pid > 1 )); then
        _patrol_group="$(ps -o pgid= -p "$_patrol_frontend_pid" | tr -d ' ' || true)"
        if [[ "$_patrol_group" == "$_patrol_frontend_pid" ]]; then
            kill -TERM -- "-$_patrol_frontend_pid" 2>/dev/null || true
        fi
    fi
}
trap cleanup EXIT
setsid npm --prefix "$_patrol_frontend" run dev -- --host 127.0.0.1 --port 5173 --strictPort \
    > "$_patrol_runs/frontend.log" 2>&1 &
_patrol_frontend_pid=$!
python3 - <<'PY'
import time, urllib.request
for _ in range(50):
    try:
        urllib.request.urlopen('http://127.0.0.1:5173/simulation', timeout=.3).close()
        break
    except Exception:
        time.sleep(.1)
else:
    raise SystemExit('Frontend did not start; check .runs/web/frontend.log')
PY
echo 'Open http://127.0.0.1:5173/simulation — isolated MuJoCo patrol, domain 93.'
_patrol_headless=true
if [[ -n "${DISPLAY:-}" ]]; then _patrol_headless=false; fi
ros2 launch fishbot_mujoco sim.launch.py headless:="$_patrol_headless" rviz:=false bridge:=true "$@"
