#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source=fishbot_ros_env.sh
source "$SCRIPT_DIR/fishbot_ros_env.sh"
ROS_SETUP="${FISHBOT_ROS_SETUP:-}"
BRINGUP_WS="${BRINGUP_WS:-$REPO_ROOT/fishbot_nav}"
LASER_WS="${LASER_WS:-$REPO_ROOT/fishbot_laser_ws}"
MICRO_ROS_AGENT_WS="${MICRO_ROS_AGENT_WS:-$REPO_ROOT/workspaces/micro_ros_agent_ws}"
STOP_HOLD_SECONDS="${FISHBOT_STOP_HOLD_SECONDS:-30}"

usage() {
  cat <<'EOF'
FishBot native ROS2 helper

Usage:
  tools/fishbot.sh status        # show native ROS graph and relevant ports
  tools/fishbot.sh topics        # ros2 topic list in WSL native ROS graph
  tools/fishbot.sh validate      # require /cmd_vel /odom /imu and fresh /odom
  tools/fishbot.sh pub [x] [z]   # publish /cmd_vel (linear.x, angular.z) at 10Hz; Ctrl+C to stop
  tools/fishbot.sh drive MODE [seconds]
                                 # MODE: forward/backward/left/right/stop
  tools/fishbot.sh estop         # publish zero /cmd_vel for 30s (override: FISHBOT_STOP_HOLD_SECONDS)
  tools/fishbot.sh stop_cmd      # alias of estop
  tools/fishbot.sh arrows        # arrow-key teleop (up/down/left/right + space stop)

Stack:
  tools/fishbot_stack.sh slam-base starts native micro_ros_agent and rosbridge.

Env (optional):
  FISHBOT_ROS_SETUP       (default: auto-resolve via fishbot_ros_env.sh, or FISHBOT_ROS_DISTRO)
  FISHBOT_ROS_DISTRO      (humble|jazzy; required explicitly when both are installed)
  FISHBOT_STOP_HOLD_SECONDS (default: 30)
  FISHBOT_ALLOW_UNSAFE_TELEOP=1 to bypass /odom safety gate for bench testing only
EOF
}

source_ros() {
  if [[ -n "$ROS_SETUP" ]]; then
    set +u
    # shellcheck disable=SC1090
    source "$ROS_SETUP"
    set -u
  else
    fishbot_source_ros
  fi
  [[ -f "$BRINGUP_WS/install/setup.bash" ]] && source "$BRINGUP_WS/install/setup.bash"
  [[ -f "$LASER_WS/install/setup.bash" ]] && source "$LASER_WS/install/setup.bash"
  [[ -f "$MICRO_ROS_AGENT_WS/install/setup.bash" ]] && source "$MICRO_ROS_AGENT_WS/install/setup.bash"
}

run_ros() {
  source_ros
  "$@"
}

topics() {
  run_ros ros2 topic list
}

validate_topics() {
  local topic_list missing=0
  topic_list="$(topics)"
  echo "$topic_list"
  for topic in /cmd_vel /odom /imu; do
    if ! grep -Fxq "$topic" <<<"$topic_list"; then
      echo "missing topic: $topic" >&2
      missing=1
    fi
  done
  return "$missing"
}

require_motion_ready() {
  if [[ "${FISHBOT_ALLOW_UNSAFE_TELEOP:-0}" == "1" ]]; then
    echo "warning: FISHBOT_ALLOW_UNSAFE_TELEOP=1, skipping /odom safety gate" >&2
    return 0
  fi

  if ! validate_topics >/tmp/fishbot_motion_topics.log 2>&1; then
    echo "motion blocked: required robot topics are not present" >&2
    sed -n '1,80p' /tmp/fishbot_motion_topics.log >&2 || true
    echo "fix: restore native micro-ROS link before publishing /cmd_vel" >&2
    echo "override only for bench testing: FISHBOT_ALLOW_UNSAFE_TELEOP=1 tools/fishbot.sh arrows" >&2
    return 1
  fi

  if ! run_ros timeout 5 ros2 topic echo /odom --once >/tmp/fishbot_motion_odom.log 2>&1; then
    echo "motion blocked: /odom has no fresh data" >&2
    sed -n '1,80p' /tmp/fishbot_motion_odom.log >&2 || true
    echo "fix: backend must report robotOnline=true and /odom must update before moving" >&2
    echo "override only for bench testing: FISHBOT_ALLOW_UNSAFE_TELEOP=1 tools/fishbot.sh arrows" >&2
    return 1
  fi
}

install_arrow_teleop() {
  install -m 0755 "$SCRIPT_DIR/fishbot_arrow_teleop.py" /tmp/fishbot-arrow-teleop
}

install_timed_cmd_vel() {
  install -m 0755 "$SCRIPT_DIR/fishbot_timed_cmd_vel.py" /tmp/fishbot-timed-cmd-vel
}

run_timed_pub() {
  local seconds="$1"
  local linear_x="$2"
  local angular_z="$3"
  install_timed_cmd_vel
  # ROS binary extensions target the distro Python, not Conda's PATH interpreter.
  run_ros /usr/bin/python3 /tmp/fishbot-timed-cmd-vel --linear-x "$linear_x" --angular-z "$angular_z" --seconds "$seconds"
}

publish_zero_for() {
  local seconds="$1"
  run_timed_pub "$seconds" 0.0 0.0
}

emergency_stop() {
  publish_zero_for "$STOP_HOLD_SECONDS"
}

status() {
  echo "Ports:"
  ss -ltnp | egrep ':8080|:5173|:9090|:9091' || true
  ss -lunp | egrep ':8888|:8889' || true
  echo
  echo "ROS nodes:"
  source_ros
  timeout 5 ros2 node list 2>/dev/null | sort || true
  echo
  echo "Topics:"
  timeout 5 ros2 topic list 2>/dev/null | sort || true
}

case "${1:-}" in
  -h|--help|help|"")
    usage
    ;;
  start|up)
    echo "native mode: use ./tools/fishbot_stack.sh slam-base to start micro_ros_agent"
    ;;
  stop|down|rm|logs|shell|build-tools|teleop)
    echo "native mode: '$1' is no longer a Docker command. Use ./tools/fishbot_stack.sh {stop,logs NAME,attach}." >&2
    exit 2
    ;;
  status)
    status
    ;;
  topics)
    topics
    ;;
  validate)
    require_motion_ready
    echo "validation: required topics present and /odom is fresh"
    ;;
  pub)
    require_motion_ready
    linear_x="${2:-0.1}"
    angular_z="${3:-0.0}"
    python3 -c 'import math,sys; x,z=map(float,sys.argv[1:]); sys.exit(0 if math.isfinite(x) and math.isfinite(z) and abs(x)<=0.3 and abs(z)<=1 else "velocity out of bounds")' "$linear_x" "$angular_z"
    run_ros ros2 topic pub -r 10 /cmd_vel geometry_msgs/msg/Twist "{linear: {x: ${linear_x}}, angular: {z: ${angular_z}}}"
    ;;
  stop_cmd)
    emergency_stop
    echo "stop_cmd: zero /cmd_vel held for ${STOP_HOLD_SECONDS}s"
    ;;
  estop)
    emergency_stop
    echo "estop: zero /cmd_vel held for ${STOP_HOLD_SECONDS}s"
    ;;
  drive)
    require_motion_ready
    mode="${2:-}"
    seconds="${3:-1.0}"
    case "$mode" in
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
    run_timed_pub "$seconds" "$linear_x" "$angular_z"
    emergency_stop
    echo "drive: mode=${mode} duration=${seconds}s"
    ;;
  arrows)
    require_motion_ready
    install_arrow_teleop
    run_ros /usr/bin/python3 /tmp/fishbot-arrow-teleop
    ;;
  *)
    echo "unknown command: $1" >&2
    usage >&2
    exit 2
    ;;
esac
