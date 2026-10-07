#!/usr/bin/env bash
# Source this file in a fresh shell; no host-wide installation is required.
_fishbot_mujoco_project="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
_fishbot_mujoco_ws="$_fishbot_mujoco_project/workspaces/fishbot_mujoco_ws"
_fishbot_mujoco_root="${FISHBOT_MUJOCO_RUNTIME:-$_fishbot_mujoco_ws/.runtime}"
if [[ ! -d "$_fishbot_mujoco_root/opt/ros/jazzy" ]]; then
    echo "Missing extracted runtime; set FISHBOT_MUJOCO_RUNTIME to its root." >&2
    return 1
fi
export PATH="/usr/bin:/bin:$PATH"
source /opt/ros/jazzy/setup.bash
_fishbot_mujoco_prefix="$_fishbot_mujoco_root/opt/ros/jazzy"
export AMENT_PREFIX_PATH="$_fishbot_mujoco_prefix:$AMENT_PREFIX_PATH"
export CMAKE_PREFIX_PATH="$_fishbot_mujoco_prefix:${CMAKE_PREFIX_PATH:-}"
export LD_LIBRARY_PATH="$_fishbot_mujoco_prefix/lib:$_fishbot_mujoco_prefix/opt/mujoco_vendor/lib:$_fishbot_mujoco_root/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="$_fishbot_mujoco_prefix/lib/python3.12/site-packages:$_fishbot_mujoco_root/usr/lib/python3/dist-packages:${PYTHONPATH:-}"
# Default domain 93 is preserved; isolated acceptance may choose another nonzero domain.
_fishbot_mujoco_domain="${FISHBOT_MUJOCO_DOMAIN_ID:-93}"
if [[ ! "$_fishbot_mujoco_domain" =~ ^[0-9]+$ ]] || (( 10#$_fishbot_mujoco_domain < 1 || 10#$_fishbot_mujoco_domain > 232 )); then
    echo 'FISHBOT_MUJOCO_DOMAIN_ID must be 1..232; simulation must never use real domain 0.' >&2
    return 1
fi
export ROS_DOMAIN_ID="$_fishbot_mujoco_domain"
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export ROS_LOCALHOST_ONLY=1
export ROS_LOG_DIR="${FISHBOT_MUJOCO_LOG_DIR:-$_fishbot_mujoco_ws/.runs/ros-log}"
if [[ -f "$_fishbot_mujoco_ws/install/local_setup.bash" ]]; then
    source "$_fishbot_mujoco_ws/install/local_setup.bash"
fi
