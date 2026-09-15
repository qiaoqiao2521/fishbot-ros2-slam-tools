#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")"
# shellcheck source=fishbot_ros_env.sh
source "$SCRIPT_DIR/fishbot_ros_env.sh"
ROS_DISTRO_RESOLVED="$(fishbot_ros_distro)" || exit 127
echo "FishBot stack: using ROS 2 ${ROS_DISTRO_RESOLVED}"

ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
CONTROL_STATION="$ROOT/apps/fishbot-control-station"
LASER_WS="${LASER_WS:-$ROOT/fishbot_laser_ws}"
BRINGUP_WS="${BRINGUP_WS:-$ROOT/fishbot_nav}"
MICRO_ROS_AGENT_WS="${MICRO_ROS_AGENT_WS:-$ROOT/workspaces/micro_ros_agent_ws}"
RVIZ_CONFIG="${RVIZ_CONFIG:-$BRINGUP_WS/src/fishbot_cartographer/config/cartographer.rviz}"
NAV_MAP="${NAV_MAP:-$BRINGUP_WS/src/fishbot_navigation2/maps/current_map.yaml}"
NAV_LIVE_MAP="${NAV_LIVE_MAP:-$BRINGUP_WS/src/fishbot_navigation2/maps/live_map.yaml}"
NAV_FALLBACK_MAP="${NAV_FALLBACK_MAP:-$BRINGUP_WS/src/fishbot_navigation2/maps/room.yaml}"
NAV_RVIZ_CONFIG="${NAV_RVIZ_CONFIG:-/opt/ros/${ROS_DISTRO_RESOLVED}/share/nav2_bringup/rviz/nav2_default_view.rviz}"

SESSION="${FISHBOT_STACK_SESSION:-fishbot}"
SLAM_PARAMS_FILE="${SLAM_PARAMS_FILE:-$ROOT/tools/config/fishbot_slam.yaml}"
BACKEND_PORT="${BACKEND_PORT:-8080}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
CONTROL_ROSBRIDGE_PORT="${CONTROL_ROSBRIDGE_PORT:-9090}"
MICRO_ROS_AGENT_PORT="${MICRO_ROS_AGENT_PORT:-8888}"
LASER_ROSBRIDGE_PORT="${LASER_ROSBRIDGE_PORT:-9091}"
LASER_SOCKET_PORT="${LASER_SOCKET_PORT:-8889}"
LASER_Z="${LASER_Z:-0.02}"
RMW_IMPL="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
ROS_DOMAIN="${ROS_DOMAIN_ID:-0}"

usage() {
  cat <<EOF
FishBot staged stack

Usage:
  $(basename "$0") slam-reset
  $(basename "$0") slam-base
  $(basename "$0") slam-core
  $(basename "$0") slam-rviz
  $(basename "$0") start-control
  $(basename "$0") start-laser
  $(basename "$0") start
  $(basename "$0") start-all
  $(basename "$0") start-slam
  $(basename "$0") start-nav
  $(basename "$0") restart-control
  $(basename "$0") restart-laser
  $(basename "$0") restart
  $(basename "$0") restart-all
  $(basename "$0") restart-slam
  $(basename "$0") restart-nav
  $(basename "$0") preflight-slam
  $(basename "$0") stop
  $(basename "$0") status
  $(basename "$0") attach
  $(basename "$0") logs NAME

tmux session:
  ${SESSION}

Windows:
  agent | control_rosbridge | lidar | rosbridge | backend | frontend | control_bridge | odom2tf | static_tf | slam | nav | rviz

Native SLAM staged flow:
  1. $(basename "$0") slam-reset
  2. $(basename "$0") slam-base
  3. $(basename "$0") preflight-slam
  4. $(basename "$0") slam-core
  5. $(basename "$0") slam-rviz

URLs:
  frontend http://127.0.0.1:${FRONTEND_PORT}
  backend  http://127.0.0.1:${BACKEND_PORT}
  control ws ws://127.0.0.1:${CONTROL_ROSBRIDGE_PORT}/
  laser ws ws://127.0.0.1:${LASER_ROSBRIDGE_PORT}/
EOF
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "error: missing command: $1" >&2
    exit 127
  }
}

tmux_has_session() {
  tmux has-session -t "$SESSION" 2>/dev/null
}

tmux_has_window() {
  local name="$1"
  tmux list-windows -t "$SESSION" -F '#W' 2>/dev/null | grep -Fxq "$name"
}

ros_prefix() {
  cat <<EOF
set +u
source /opt/ros/${ROS_DISTRO_RESOLVED}/setup.bash
[[ -f '$BRINGUP_WS/install/setup.bash' ]] && source '$BRINGUP_WS/install/setup.bash'
[[ -f '$LASER_WS/install/setup.bash' ]] && source '$LASER_WS/install/setup.bash'
[[ -f '$MICRO_ROS_AGENT_WS/install/setup.bash' ]] && source '$MICRO_ROS_AGENT_WS/install/setup.bash'
set -u
export RMW_IMPLEMENTATION='$RMW_IMPL'
export ROS_DOMAIN_ID='$ROS_DOMAIN'
EOF
}

source_ros_here() {
  fishbot_source_ros
  [[ -f "$BRINGUP_WS/install/setup.bash" ]] && source "$BRINGUP_WS/install/setup.bash"
  [[ -f "$LASER_WS/install/setup.bash" ]] && source "$LASER_WS/install/setup.bash"
  [[ -f "$MICRO_ROS_AGENT_WS/install/setup.bash" ]] && source "$MICRO_ROS_AGENT_WS/install/setup.bash"
  export RMW_IMPLEMENTATION="$RMW_IMPL"
  export ROS_DOMAIN_ID="$ROS_DOMAIN"
}

tmux_new_session() {
  tmux new-session -d -s "$SESSION" -n bootstrap "bash --noprofile --norc -lc 'sleep infinity'"
  tmux set-option -t "$SESSION" remain-on-exit on >/dev/null
}

cleanup_bootstrap() {
  if tmux_has_window "bootstrap"; then
    tmux kill-window -t "$SESSION:bootstrap"
  fi
}

reset_session() {
  if tmux_has_session; then
    tmux kill-session -t "$SESSION"
  fi
  tmux_new_session
}

tmux_replace_window() {
  local name="$1"
  local cmd="$2"
  if tmux_has_window "$name"; then
    tmux kill-window -t "$SESSION:$name"
  fi
  tmux new-window -d -t "$SESSION" -n "$name" "bash --noprofile --norc -lc \"$cmd\""
}

kill_stale_ports() {
  fuser -k "${BACKEND_PORT}/tcp" 2>/dev/null || true
  fuser -k "${FRONTEND_PORT}/tcp" 2>/dev/null || true
  fuser -k "${CONTROL_ROSBRIDGE_PORT}/tcp" 2>/dev/null || true
  fuser -k "${LASER_ROSBRIDGE_PORT}/tcp" 2>/dev/null || true
  fuser -k "${MICRO_ROS_AGENT_PORT}/udp" 2>/dev/null || true
}

start_agent() {
  tmux_replace_window "agent" "$(ros_prefix)
if ss -lun 2>/dev/null | grep -q ':${MICRO_ROS_AGENT_PORT} '; then
  echo 'error: UDP ${MICRO_ROS_AGENT_PORT} is already in use before starting native micro_ros_agent.'
  echo 'Check stale Docker Desktop port mappings or old native agents, then free the port.'
  echo 'Diagnostics: ss -lunp | grep :${MICRO_ROS_AGENT_PORT}'
  exit 98
fi
if ! ros2 pkg prefix micro_ros_agent >/dev/null 2>&1; then
  echo 'error: ROS2 package micro_ros_agent not found.'
  echo 'Build/source $MICRO_ROS_AGENT_WS first (see workspaces/micro_ros_agent_ws).'
  exit 127
fi
ros2 run micro_ros_agent micro_ros_agent udp4 --port ${MICRO_ROS_AGENT_PORT} -v6
echo 'micro_ros_agent exited; this is not expected during live operation.'
exit 1"

  tmux_replace_window "control_rosbridge" "$(ros_prefix)
exec ros2 launch rosbridge_server rosbridge_websocket_launch.xml port:=${CONTROL_ROSBRIDGE_PORT}"

  echo "agent: native micro-ROS on udp/${MICRO_ROS_AGENT_PORT}"
  echo "control_rosbridge: ws://127.0.0.1:${CONTROL_ROSBRIDGE_PORT}/"
}

start_laser_windows() {
  tmux_replace_window "lidar" "$(ros_prefix)
cd '$LASER_WS'
exec ros2 run ydlidar ydlidar_node --ros-args -p protocol:=net -p socket_port:=${LASER_SOCKET_PORT}"

  tmux_replace_window "rosbridge" "$(ros_prefix)
exec ros2 launch rosbridge_server rosbridge_websocket_launch.xml port:=${LASER_ROSBRIDGE_PORT}"

}

start_lidar_window() {
  tmux_replace_window "lidar" "$(ros_prefix)
cd '$LASER_WS'
exec ros2 run ydlidar ydlidar_node --ros-args -p protocol:=net -p socket_port:=${LASER_SOCKET_PORT}"
}

start_backend_window() {
  tmux_replace_window "backend" "cd '$CONTROL_STATION/backend'
export CONTROL_ROSBRIDGE_HOST=127.0.0.1
export CONTROL_ROSBRIDGE_PORT=${CONTROL_ROSBRIDGE_PORT}
export LASER_ROSBRIDGE_HOST=127.0.0.1
export LASER_ROSBRIDGE_PORT=${LASER_ROSBRIDGE_PORT}
export SERVER_PORT=${BACKEND_PORT}
exec ./gradlew --no-daemon bootRun"
}

start_ui_windows() {
  start_backend_window

  tmux_replace_window "frontend" "cd '$CONTROL_STATION/frontend'
exec npm run dev -- --host 0.0.0.0 --port ${FRONTEND_PORT}"

  cleanup_bootstrap
  tmux select-window -t "$SESSION:frontend"
}

start_base_windows() {
  start_laser_windows
  start_ui_windows
}

start_control_windows() {
  start_ui_windows
}

start_laser_only_windows() {
  start_laser_windows
  start_ui_windows
}

start_slam_windows() {
  tmux_replace_window "control_bridge" "cd '$ROOT'
exec python3 '$ROOT/tools/fishbot_control_state_bridge.py' 'http://127.0.0.1:${BACKEND_PORT}' 15"

  tmux_replace_window "odom2tf" "$(ros_prefix)
exec ros2 run fishbot_bringup odom2tf"

  tmux_replace_window "static_tf" "$(ros_prefix)
exec ros2 run tf2_ros static_transform_publisher 0 0 ${LASER_Z} 0 0 0 1 base_footprint laser_frame"

  tmux_replace_window "slam" "$(ros_prefix)
exec ros2 launch slam_toolbox online_async_launch.py use_sim_time:=False slam_params_file:='$SLAM_PARAMS_FILE'"

  tmux_replace_window "rviz" "$(ros_prefix)
if [[ -f '$RVIZ_CONFIG' ]]; then
  exec rviz2 -d '$RVIZ_CONFIG'
else
  exec rviz2
fi"

  tmux select-window -t "$SESSION:rviz"
}

start_slam_core_windows() {
  tmux_replace_window "control_bridge" "cd '$ROOT'
exec python3 '$ROOT/tools/fishbot_control_state_bridge.py' 'http://127.0.0.1:${BACKEND_PORT}' 15"

  tmux_replace_window "odom2tf" "$(ros_prefix)
exec ros2 run fishbot_bringup odom2tf"

  tmux_replace_window "static_tf" "$(ros_prefix)
exec ros2 run tf2_ros static_transform_publisher 0 0 ${LASER_Z} 0 0 0 1 base_footprint laser_frame"

  tmux_replace_window "slam" "$(ros_prefix)
exec ros2 launch slam_toolbox online_async_launch.py use_sim_time:=False slam_params_file:='$SLAM_PARAMS_FILE'"

  tmux select-window -t "$SESSION:slam"
}

start_slam_rviz_window() {
  tmux_replace_window "rviz" "$(ros_prefix)
if [[ -f '$RVIZ_CONFIG' ]]; then
  exec rviz2 -d '$RVIZ_CONFIG'
else
  exec rviz2
fi"

  tmux select-window -t "$SESSION:rviz"
}

resolve_nav_map() {
  if [[ -f "$NAV_MAP" ]]; then
    echo "$NAV_MAP"
    return 0
  fi
  if [[ -f "$NAV_LIVE_MAP" ]]; then
    echo "$NAV_LIVE_MAP"
    return 0
  fi
  echo "$NAV_FALLBACK_MAP"
}

start_nav_windows() {
  local nav_map
  nav_map="$(resolve_nav_map)"

  tmux_replace_window "control_bridge" "cd '$ROOT'
exec python3 '$ROOT/tools/fishbot_control_state_bridge.py' 'http://127.0.0.1:${BACKEND_PORT}' 15"

  tmux_replace_window "odom2tf" "$(ros_prefix)
exec ros2 run fishbot_bringup odom2tf"

  tmux_replace_window "static_tf" "$(ros_prefix)
exec ros2 run tf2_ros static_transform_publisher 0 0 ${LASER_Z} 0 0 0 1 base_footprint laser_frame"

  tmux_replace_window "nav" "$(ros_prefix)
exec ros2 launch nav2_bringup bringup_launch.py map:='${nav_map}' use_sim_time:=False params_file:='$BRINGUP_WS/src/fishbot_navigation2/config/nav2_params.yaml'"

  tmux_replace_window "rviz" "$(ros_prefix)
if [[ -f '$NAV_RVIZ_CONFIG' ]]; then
  exec rviz2 -d '$NAV_RVIZ_CONFIG'
else
  exec rviz2
fi"

  tmux select-window -t "$SESSION:rviz"
}

ensure_mode_windows() {
  local mode="$1"
  case "$mode" in
    control)
      tmux_has_window "backend" || start_ui_windows
      ;;
    laser)
      tmux_has_window "lidar" || start_laser_windows
      tmux_has_window "rosbridge" || start_laser_windows
      tmux_has_window "backend" || start_ui_windows
      tmux_has_window "frontend" || start_ui_windows
      ;;
    slam)
      tmux_has_window "lidar" || start_laser_windows
      tmux_has_window "rosbridge" || start_laser_windows
      tmux_has_window "backend" || start_ui_windows
      tmux_has_window "frontend" || start_ui_windows
      tmux_has_window "control_bridge" || start_slam_windows
      tmux_has_window "odom2tf" || start_slam_windows
      tmux_has_window "static_tf" || start_slam_windows
      tmux_has_window "slam" || start_slam_windows
      tmux_has_window "rviz" || start_slam_windows
      ;;
    nav)
      tmux_has_window "lidar" || start_laser_windows
      tmux_has_window "rosbridge" || start_laser_windows
      tmux_has_window "backend" || start_ui_windows
      tmux_has_window "frontend" || start_ui_windows
      tmux_has_window "control_bridge" || start_nav_windows
      tmux_has_window "odom2tf" || start_nav_windows
      tmux_has_window "static_tf" || start_nav_windows
      tmux_has_window "nav" || start_nav_windows
      tmux_has_window "rviz" || start_nav_windows
      ;;
  esac
}

verify_mode_windows() {
  local mode="$1"
  local -a required=()
  case "$mode" in
    control)
      required=(backend frontend)
      ;;
    laser)
      required=(lidar rosbridge backend frontend)
      ;;
    slam)
      required=(lidar rosbridge backend frontend control_bridge odom2tf static_tf slam rviz)
      ;;
    nav)
      required=(lidar rosbridge backend frontend control_bridge odom2tf static_tf nav rviz)
      ;;
    *)
      return 0
      ;;
  esac

  local missing=()
  local name
  for name in "${required[@]}"; do
    tmux_has_window "$name" || missing+=("$name")
  done

  if ((${#missing[@]} == 0)); then
    return 0
  fi

  echo "warning: missing tmux windows for mode '${mode}': ${missing[*]}" >&2
  return 1
}

wait_for_mode_windows() {
  local mode="$1"
  local attempt
  for attempt in $(seq 1 5); do
    ensure_mode_windows "$mode"
    if verify_mode_windows "$mode" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  verify_mode_windows "$mode"
}

probe_scan() {
  if [[ -x "$ROOT/tools/fishbot_laser_scan_probe.sh" ]]; then
    source_ros_here
    timeout 8 "$ROOT/tools/fishbot_laser_scan_probe.sh" || true
  fi
}

probe_map() {
  if [[ -x "$ROOT/tools/fishbot_map_probe.sh" ]]; then
    source_ros_here
    timeout 8 "$ROOT/tools/fishbot_map_probe.sh" || true
  fi
}

wait_backend_api() {
  local i
  for i in $(seq 1 30); do
    if curl -m 2 -fsS "http://127.0.0.1:${BACKEND_PORT}/api/v1/connection" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "warning: backend API did not become ready on :${BACKEND_PORT}" >&2
  return 1
}

wait_scan_api() {
  local i body
  for i in $(seq 1 20); do
    body="$(curl -m 2 -fsS "http://127.0.0.1:${BACKEND_PORT}/api/v1/perception" 2>/dev/null || true)"
    if grep -q '"scan":{"ready":true' <<<"$body"; then
      return 0
    fi
    sleep 1
  done
  echo "warning: backend is up but /scan has not appeared in perception API yet" >&2
  return 1
}

print_urls() {
  local frontend_url
  frontend_url="$(detect_frontend_url)"
  echo
  echo "frontend: ${frontend_url}"
  echo "backend:  http://127.0.0.1:${BACKEND_PORT}"
  echo "control:  ws://127.0.0.1:${CONTROL_ROSBRIDGE_PORT}/"
  echo "laser ws: ws://127.0.0.1:${LASER_ROSBRIDGE_PORT}/"
  echo "tmux:     tmux attach -t ${SESSION}"
}

detect_frontend_url() {
  if tmux_has_window "frontend"; then
    local url
    url="$(tmux capture-pane -p -t "$SESSION:frontend" -S -80 2>/dev/null | sed -n 's/.*http:\/\/localhost:\([0-9]\+\)\/.*/http:\/\/127.0.0.1:\1/p' | tail -n 1)"
    if [[ -n "$url" ]]; then
      echo "$url"
      return 0
    fi
  fi
  echo "http://127.0.0.1:${FRONTEND_PORT}"
}

ensure_session() {
  need_cmd tmux
  if ! tmux_has_session; then
    tmux_new_session
  fi
}

start_stack() {
  kill_stale_ports
  reset_session
  start_agent
  start_base_windows
  sleep 3
  wait_for_mode_windows laser || true
  probe_scan
  wait_backend_api || true
  wait_scan_api || true
  print_urls
}

start_control_stack() {
  kill_stale_ports
  reset_session
  start_agent
  start_control_windows
  sleep 2
  wait_for_mode_windows control || true
  wait_backend_api || true
  print_urls
}

start_laser_stack() {
  kill_stale_ports
  reset_session
  start_laser_only_windows
  sleep 3
  wait_for_mode_windows laser || true
  probe_scan
  wait_backend_api || true
  wait_scan_api || true
  print_urls
}

start_stack_with_slam() {
  kill_stale_ports
  reset_session
  start_agent
  start_base_windows
  start_slam_windows
  sleep 3
  wait_for_mode_windows slam || true
  probe_scan
  wait_backend_api || true
  wait_scan_api || true
  probe_map
  print_urls
}

start_stack_with_nav() {
  kill_stale_ports
  reset_session
  start_agent
  start_base_windows
  start_nav_windows
  sleep 3
  wait_for_mode_windows nav || true
  probe_scan
  wait_backend_api || true
  wait_scan_api || true
  probe_map
  print_urls
}

slam_reset_stack() {
  stop_stack
  reset_session
  echo "SLAM session reset. Next: ./tools/fishbot_stack.sh slam-base"
}

slam_base_stack() {
  kill_stale_ports
  ensure_session
  start_agent
  start_backend_window
  start_lidar_window
  sleep 3
  probe_scan
  wait_backend_api || true
  print_urls
  echo
  echo "Next: ./tools/fishbot_stack.sh preflight-slam"
}

slam_core_stack() {
  ensure_session
  if ! preflight_slam; then
    echo
    echo "slam-core blocked: preflight-slam failed. Do not start SLAM or move the robot." >&2
    return 1
  fi
  start_slam_core_windows
  sleep 3
  probe_map
  print_urls
  echo
  echo "Next: ./tools/fishbot_stack.sh slam-rviz"
}

slam_rviz_stack() {
  ensure_session
  start_slam_rviz_window
  print_urls
}

stop_stack() {
  if tmux_has_session; then
    tmux kill-session -t "$SESSION"
    echo "tmux: session ${SESSION} stopped"
  else
    echo "tmux: session ${SESSION} not running"
  fi

  echo "agent: stopped"
}

show_status() {
  echo "Ports:"
  ss -ltnp | egrep ":${BACKEND_PORT}|:${FRONTEND_PORT}|:${LASER_ROSBRIDGE_PORT}|:${CONTROL_ROSBRIDGE_PORT}" || true
  ss -lunp | egrep ":${MICRO_ROS_AGENT_PORT}|:${LASER_SOCKET_PORT}" || true
  echo

  if tmux_has_session; then
    echo "tmux session: ${SESSION}"
    tmux list-windows -t "$SESSION"
  else
    echo "tmux session: stopped"
  fi

  echo
  source_ros_here
  echo "ROS nodes:"
  timeout 5 ros2 node list 2>/dev/null | sort || true

  echo
  curl -m 2 -s "http://127.0.0.1:${BACKEND_PORT}/api/v1/connection" || true
  echo
  curl -m 2 -s "http://127.0.0.1:${BACKEND_PORT}/api/v1/perception" || true
  echo
}

preflight_slam() {
  "$ROOT/tools/fishbot_slam_preflight.sh"
}

attach_stack() {
  ensure_session
  exec tmux attach -t "$SESSION"
}

show_logs() {
  local name="${1:-}"
  [[ -n "$name" ]] || { echo "usage: $(basename "$0") logs NAME" >&2; exit 2; }
  if ! tmux_has_window "$name"; then
    echo "window not found: $name" >&2
    exit 1
  fi
  tmux capture-pane -p -t "$SESSION:$name" -S -200
}

case "${1:-}" in
  slam-reset)
    slam_reset_stack
    ;;
  slam-base)
    slam_base_stack
    ;;
  slam-core)
    slam_core_stack
    ;;
  slam-rviz)
    slam_rviz_stack
    ;;
  start-control)
    start_control_stack
    ;;
  start-laser)
    start_laser_stack
    ;;
  start)
    start_stack
    ;;
  start-all)
    start_stack
    ;;
  start-slam)
    start_stack_with_slam
    ;;
  start-nav)
    start_stack_with_nav
    ;;
  restart-control)
    stop_stack
    start_control_stack
    ;;
  restart-laser)
    stop_stack
    start_laser_stack
    ;;
  restart)
    stop_stack
    start_stack
    ;;
  restart-all)
    stop_stack
    start_stack
    ;;
  restart-slam)
    stop_stack
    start_stack_with_slam
    ;;
  restart-nav)
    stop_stack
    start_stack_with_nav
    ;;
  preflight-slam)
    preflight_slam
    ;;
  stop)
    stop_stack
    ;;
  status)
    show_status
    ;;
  attach)
    attach_stack
    ;;
  logs)
    show_logs "${2:-}"
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    usage
    exit 2
    ;;
esac
