#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

NAME="${FISHBOT_AGENT_NAME:-fishbot_agent}"
PORT="${FISHBOT_UDP_PORT:-8888}"
ROSBRIDGE_PORT="${FISHBOT_ROSBRIDGE_PORT:-9090}"
AGENT_IMAGE="${FISHBOT_AGENT_IMAGE:-fishbot_agent_plus:humble}"
TOOLS_IMAGE="${FISHBOT_TOOLS_IMAGE:-fishbot_tools:humble}"
ROS_SETUP="${FISHBOT_ROS_SETUP:-/opt/ros/humble/setup.bash}"

usage() {
  cat <<'EOF'
FishBot (micro-ROS UDP) helper for Docker Desktop + WSL2

Usage:
  tools/fishbot.sh start         # create+start persistent agent container
  tools/fishbot.sh status        # show WSL IP, container state, and port mapping
  tools/fishbot.sh stop          # stop agent container (keeps it)
  tools/fishbot.sh rm            # remove agent container
  tools/fishbot.sh logs          # follow agent logs
  tools/fishbot.sh topics        # ros2 topic list (inside agent container)
  tools/fishbot.sh validate      # require /cmd_vel /odom /imu to exist
  tools/fishbot.sh pub [x] [z]   # publish /cmd_vel (linear.x, angular.z) at 10Hz; Ctrl+C to stop
  tools/fishbot.sh drive MODE [seconds]
                                 # MODE: forward/backward/left/right/stop
  tools/fishbot.sh estop         # publish repeated zero /cmd_vel for emergency stop
  tools/fishbot.sh stop_cmd      # publish a single 0 /cmd_vel
  tools/fishbot.sh build-tools   # build fishbot_tools image (teleop inside)
  tools/fishbot.sh teleop        # keyboard teleop (tools container shares agent network)
  tools/fishbot.sh arrows        # arrow-key teleop (up/down/left/right + space stop)
  tools/fishbot.sh shell         # bash inside agent container

Env (optional):
  FISHBOT_AGENT_NAME   (default: fishbot_agent)
  FISHBOT_UDP_PORT     (default: 8888)
  FISHBOT_ROSBRIDGE_PORT (default: 9090)
  FISHBOT_AGENT_IMAGE  (default: fishbot_agent_plus:humble)
  FISHBOT_TOOLS_IMAGE  (default: fishbot_tools:humble)
  FISHBOT_ROS_SETUP    (default: /opt/ros/humble/setup.bash)
  FISHBOT_DOCKER_BIN   (default: auto-detect docker/docker.exe)

Notes:
  - Windows UDP 8888 can only be bound by ONE thing at a time (relay / container / other listener).
  - teleop/arrows run in the tools image, not in the agent container.
EOF
}

case "${1:-}" in
  -h|--help|help|"")
    usage
    exit 0
    ;;
esac

DOCKER_CMD=()

try_docker_cmd() {
  local -a candidate=("$@")
  if ! "${candidate[@]}" version >/dev/null 2>&1; then
    return 1
  fi
  DOCKER_CMD=("${candidate[@]}")
  return 0
}

if [[ -n "${FISHBOT_DOCKER_BIN:-}" ]]; then
  # User override (should be a single token like docker/docker.exe or an absolute path without spaces).
  if ! try_docker_cmd "${FISHBOT_DOCKER_BIN}"; then
    echo "error: FISHBOT_DOCKER_BIN='${FISHBOT_DOCKER_BIN}' not runnable" >&2
    exit 127
  fi
else
  # Auto-detect, prefer native linux docker if present; fallback to docker.exe (works without /mnt/wsl mounts).
  if command -v docker >/dev/null 2>&1 && try_docker_cmd docker; then
    :
  elif [[ -x /usr/bin/docker ]] && try_docker_cmd /usr/bin/docker; then
    :
  elif command -v docker.exe >/dev/null 2>&1 && try_docker_cmd docker.exe; then
    :
  elif [[ -x "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" ]] && \
    try_docker_cmd "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"; then
    :
  else
    echo "error: docker CLI not runnable from this WSL distro." >&2
    echo "fix:" >&2
    echo "  - make sure Docker Desktop is running on Windows" >&2
    echo "  - enable Docker Desktop -> Settings -> Resources -> WSL Integration -> this distro (e.g. Ubuntu-22.04)" >&2
    echo "  - then run: wsl.exe --shutdown (Windows) and reopen WSL" >&2
    echo "note: running docker from WSL requires Docker Desktop WSL integration; otherwise run docker commands in Windows PowerShell instead." >&2
    exit 127
  fi
fi

docker_has_container() {
  "${DOCKER_CMD[@]}" ps -a --format '{{.Names}}' | grep -Fxq "$NAME"
}

docker_container_running() {
  docker_has_container && "${DOCKER_CMD[@]}" inspect -f '{{.State.Running}}' "$NAME" | grep -Fxq "true"
}

container_image() {
  "${DOCKER_CMD[@]}" inspect -f '{{.Config.Image}}' "$NAME"
}

container_ports() {
  "${DOCKER_CMD[@]}" port "$NAME" 2>/dev/null || true
}

container_needs_recreate() {
  if ! docker_has_container; then
    return 1
  fi

  local image ports
  image="$(container_image)"
  ports="$(container_ports)"

  if [[ "$image" != "$AGENT_IMAGE" ]]; then
    return 0
  fi

  grep -Fq "${PORT}/udp -> 0.0.0.0:${PORT}" <<<"$ports" || return 0
  grep -Fq "${ROSBRIDGE_PORT}/tcp -> 0.0.0.0:${ROSBRIDGE_PORT}" <<<"$ports" || return 0

  return 1
}

ensure_rosbridge_running() {
  if ! docker_container_running; then
    return 1
  fi

  if "${DOCKER_CMD[@]}" exec -i "$NAME" bash -lc "ps -ef | grep -q '[r]osbridge_websocket'"; then
    return 0
  fi

  "${DOCKER_CMD[@]}" exec -d "$NAME" bash -lc \
    "source \"$ROS_SETUP\"; ros2 launch rosbridge_server rosbridge_websocket_launch.xml port:=${ROSBRIDGE_PORT}"

  local attempt
  for attempt in $(seq 1 20); do
    if "${DOCKER_CMD[@]}" exec -i "$NAME" bash -lc "ps -ef | grep -q '[r]osbridge_websocket'"; then
      return 0
    fi
    sleep 0.5
  done

  echo "warning: rosbridge did not appear inside ${NAME}" >&2
  return 1
}

ensure_agent_running() {
  if container_needs_recreate; then
    echo "recreating ${NAME} to match image/port requirements..."
    "${DOCKER_CMD[@]}" rm -f "$NAME" >/dev/null || true
  fi

  if docker_has_container; then
    "${DOCKER_CMD[@]}" start "$NAME" >/dev/null
    ensure_rosbridge_running >/dev/null || true
    return 0
  fi

  "${DOCKER_CMD[@]}" run -d \
    --name "$NAME" \
    --restart unless-stopped \
    -p "0.0.0.0:${PORT}:${PORT}/udp" \
    -p "0.0.0.0:${ROSBRIDGE_PORT}:${ROSBRIDGE_PORT}" \
    "$AGENT_IMAGE" udp4 --port "$PORT" -v6 >/dev/null

  ensure_rosbridge_running >/dev/null || true
}

tools_image_has() {
  local command="$1"
  "${DOCKER_CMD[@]}" image inspect "$TOOLS_IMAGE" >/dev/null 2>&1 || return 1
  "${DOCKER_CMD[@]}" run --rm "$TOOLS_IMAGE" bash -lc "$command" >/dev/null 2>&1
}

ensure_tools_image() {
  if tools_image_has "command -v ros2 >/dev/null && command -v fishbot-arrow-teleop >/dev/null"; then
    return 0
  fi

  echo "building ${TOOLS_IMAGE}..."
  "${DOCKER_CMD[@]}" build -f "${SCRIPT_DIR}/Dockerfile.fishbot_tools" -t "$TOOLS_IMAGE" "$REPO_ROOT"
}

run_ros() {
  local cmd="$1"
  "${DOCKER_CMD[@]}" exec -i "$NAME" bash -lc "source \"$ROS_SETUP\"; ${cmd}"
}

exec_ros() {
  local cmd="$1"
  "${DOCKER_CMD[@]}" exec -it "$NAME" bash -lc "source \"$ROS_SETUP\"; ${cmd}"
}

install_arrow_teleop_in_agent() {
  "${DOCKER_CMD[@]}" exec -i "$NAME" bash -lc "cat > /usr/local/bin/fishbot-arrow-teleop && chmod +x /usr/local/bin/fishbot-arrow-teleop" \
    < "${SCRIPT_DIR}/fishbot_arrow_teleop.py"
}

get_wsl_ip() {
  ip -4 -o addr show up primary scope global | awk '$2 != "lo" {split($4, a, "/"); print a[1]; exit}'
}

print_status() {
  local wsl_ip
  wsl_ip="$(get_wsl_ip || true)"
  echo "wsl_ip: ${wsl_ip:-unknown}"
  echo "docker: ${DOCKER_CMD[*]}"

  if ! docker_has_container; then
    echo "agent: missing"
    return 0
  fi

  if docker_container_running; then
    echo "agent: running"
  else
    echo "agent: stopped"
  fi

  "${DOCKER_CMD[@]}" ps -a --filter "name=^${NAME}$" \
    --format 'container: {{.Names}}  status: {{.Status}}  ports: {{.Ports}}  image: {{.Image}}'
}

validate_topics() {
  local topics
  ensure_agent_running
  topics="$(run_ros "ros2 topic list")"
  echo "${topics}"

  local missing=0
  for topic in /cmd_vel /odom /imu; do
    if ! grep -Fxq "${topic}" <<<"${topics}"; then
      echo "missing topic: ${topic}" >&2
      missing=1
    fi
  done

  return "${missing}"
}

require_motion_ready() {
  ensure_agent_running

  if [[ "${FISHBOT_ALLOW_UNSAFE_TELEOP:-0}" == "1" ]]; then
    echo "warning: FISHBOT_ALLOW_UNSAFE_TELEOP=1, skipping /odom safety gate" >&2
    return 0
  fi

  if ! validate_topics >/tmp/fishbot_motion_topics.log 2>&1; then
    echo "motion blocked: required robot topics are not present" >&2
    sed -n '1,80p' /tmp/fishbot_motion_topics.log >&2 || true
    echo "fix: restore micro-ROS link before publishing /cmd_vel" >&2
    echo "override only for bench testing: FISHBOT_ALLOW_UNSAFE_TELEOP=1 tools/fishbot.sh arrows" >&2
    return 1
  fi

  if ! run_ros "timeout 5 ros2 topic echo /odom --once" >/tmp/fishbot_motion_odom.log 2>&1; then
    echo "motion blocked: /odom has no fresh data" >&2
    sed -n '1,80p' /tmp/fishbot_motion_odom.log >&2 || true
    echo "fix: backend must report robotOnline=true and /odom must update before moving" >&2
    echo "override only for bench testing: FISHBOT_ALLOW_UNSAFE_TELEOP=1 tools/fishbot.sh arrows" >&2
    return 1
  fi
}

run_timed_pub() {
  local seconds="$1"
  local linear_x="$2"
  local angular_z="$3"
  local rc=0

  timeout --signal=INT "${seconds}s" \
    "${DOCKER_CMD[@]}" exec -i "$NAME" bash -lc \
    "source \"$ROS_SETUP\"; ros2 topic pub -r 10 /cmd_vel geometry_msgs/msg/Twist \"{linear: {x: ${linear_x}}, angular: {z: ${angular_z}}}\"" \
    >/dev/null 2>&1 || rc=$?

  if [[ "${rc}" -ne 0 && "${rc}" -ne 124 && "${rc}" -ne 130 ]]; then
    return "${rc}"
  fi
}

emergency_stop() {
  local i
  ensure_agent_running
  for ((i = 0; i < 5; i++)); do
    run_ros "ros2 topic pub -1 /cmd_vel geometry_msgs/msg/Twist \"{linear: {x: 0.0}, angular: {z: 0.0}}\"" >/dev/null
    sleep 0.1
  done
}

case "${1:-}" in
  start|up)
    ensure_agent_running
    echo "agent: $NAME (udp/${PORT})"
    echo "logs: ${DOCKER_CMD[*]} logs -f $NAME"
    ;;
  status)
    print_status
    ;;
  stop|down)
    "${DOCKER_CMD[@]}" stop "$NAME" >/dev/null || true
    ;;
  rm)
    "${DOCKER_CMD[@]}" rm -f "$NAME" >/dev/null
    ;;
  logs)
    "${DOCKER_CMD[@]}" logs -f "$NAME"
    ;;
  topics)
    ensure_agent_running
    run_ros "ros2 topic list"
    ;;
  validate)
    if validate_topics; then
      echo "validation: required topics present"
    else
      exit 1
    fi
    ;;
  shell)
    ensure_agent_running
    "${DOCKER_CMD[@]}" exec -it "$NAME" bash
    ;;
  pub)
    require_motion_ready
    linear_x="${2:-0.1}"
    angular_z="${3:-0.0}"
    exec_ros "ros2 topic pub -r 10 /cmd_vel geometry_msgs/msg/Twist \"{linear: {x: ${linear_x}}, angular: {z: ${angular_z}}}\""
    ;;
  stop_cmd)
    ensure_agent_running
    run_ros "ros2 topic pub -1 /cmd_vel geometry_msgs/msg/Twist \"{linear: {x: 0.0}, angular: {z: 0.0}}\""
    ;;
  estop)
    emergency_stop
    echo "estop: zero /cmd_vel burst sent"
    ;;
  drive)
    require_motion_ready
    mode="${2:-}"
    seconds="${3:-1.0}"
    case "${mode}" in
      forward)  linear_x="0.12";  angular_z="0.0" ;;
      backward) linear_x="-0.12"; angular_z="0.0" ;;
      left)     linear_x="0.0";   angular_z="0.8" ;;
      right)    linear_x="0.0";   angular_z="-0.8" ;;
      stop)     linear_x="0.0";   angular_z="0.0" ;;
      *)
        echo "usage: tools/fishbot.sh drive {forward|backward|left|right|stop} [seconds]" >&2
        exit 2
        ;;
    esac
    run_timed_pub "${seconds}" "${linear_x}" "${angular_z}"
    emergency_stop
    echo "drive: mode=${mode} duration=${seconds}s"
    ;;
  build-tools)
    ensure_tools_image
    ;;
  teleop)
    require_motion_ready
    ensure_tools_image
    "${DOCKER_CMD[@]}" run --rm -it --network="container:${NAME}" "$TOOLS_IMAGE" \
      bash -lc "source \"$ROS_SETUP\"; ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -r cmd_vel:=/cmd_vel"
    ;;
  arrows)
    require_motion_ready
    install_arrow_teleop_in_agent
    "${DOCKER_CMD[@]}" exec -it "$NAME" bash -lc "source \"$ROS_SETUP\"; fishbot-arrow-teleop"
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    echo "unknown command: $1" >&2
    usage >&2
    exit 2
    ;;
esac
