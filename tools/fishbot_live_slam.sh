#!/usr/bin/env bash
set -euo pipefail

WORKBENCH_ROOT="$(dirname -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")")"

LASER_WS="${LASER_WS:-${WORKBENCH_ROOT}/fishbot_laser_ws}"
BRINGUP_WS="${BRINGUP_WS:-${WORKBENCH_ROOT}/fishbot_nav}"
LASER_Z="${LASER_Z:-0.02}"
SLAM_LOG="${TMPDIR:-/tmp}/fishbot-live-slam.log"
TOOLS_DIR="${WORKBENCH_ROOT}/tools"
# shellcheck source=fishbot_ros_env.sh
source "$TOOLS_DIR/fishbot_ros_env.sh"

cleanup() {
  for pid_var in ODOM2TF_PID STATIC_TF_PID; do
    pid="${!pid_var:-}"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
}

trap cleanup EXIT INT TERM

set +u
fishbot_source_ros
source "$LASER_WS/install/setup.bash"
source "$BRINGUP_WS/install/setup.bash"
set -u

export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"

echo "checking /scan ..."
if ! timeout 8 "${WORKBENCH_ROOT}/tools/fishbot_laser_scan_probe.sh" >/tmp/fishbot-live-scan-probe.out 2>&1; then
  cat /tmp/fishbot-live-scan-probe.out >&2 || true
  echo "error: /scan not available; keep ydlidar_node running in ${LASER_WS}" >&2
  exit 1
fi
cat /tmp/fishbot-live-scan-probe.out

echo "starting odom -> tf bridge ..."
ros2 run fishbot_bringup odom2tf > /tmp/fishbot-odom2tf.log 2>&1 &
ODOM2TF_PID=$!

echo "starting static tf base_footprint -> laser_frame ..."
ros2 run tf2_ros static_transform_publisher \
  0 0 "${LASER_Z}" 0 0 0 1 base_footprint laser_frame \
  > /tmp/fishbot-static-laser-tf.log 2>&1 &
STATIC_TF_PID=$!

echo "waiting for /tf ..."
for _ in $(seq 1 20); do
  if timeout 2 ros2 topic echo /tf --once >/tmp/fishbot-live-tf.out 2>&1; then
    break
  fi
  sleep 0.5
done

echo "starting slam_toolbox ..."
echo "logs: ${SLAM_LOG}"
ros2 launch slam_toolbox online_async_launch.py use_sim_time:=False | tee "${SLAM_LOG}"
