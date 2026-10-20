#!/usr/bin/env bash
# Select the existing runtime for this command only.
set -o pipefail
scene_project="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export FISHBOT_MUJOCO_DOMAIN_ID="${FISHBOT_MUJOCO_DOMAIN_ID:-130}"
source "$scene_project/tools/fishbot_mujoco_env.sh" || echo 'WARNING: runtime setup incomplete; individual cases will report missing dependencies.' >&2
scene_lidar_prefix="${FISHBOT_LIDAR3D_PREFIX:-$HOME/.cache/fishbot/lidar3d/prefix}"
if [[ -d "$scene_lidar_prefix" ]]; then
  export AMENT_PREFIX_PATH="$scene_lidar_prefix:${AMENT_PREFIX_PATH:-}"
fi
scene_dds_root="$HOME/.cache/fishbot/workbench-rebuild-20261018/cyclonedds-runtime-a/prefix"
if [[ -d "$scene_dds_root/opt/ros/jazzy/share/rmw_cyclonedds_cpp" ]]; then
  export AMENT_PREFIX_PATH="$scene_dds_root/opt/ros/jazzy:${AMENT_PREFIX_PATH:-}"
  export LD_LIBRARY_PATH="$scene_dds_root/opt/ros/jazzy/lib:$scene_dds_root/opt/ros/jazzy/lib/x86_64-linux-gnu:$scene_dds_root/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
  export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
fi
exec /usr/bin/python3 "$scene_project/tools/fishbot_scene_campaign.py" "$@"
