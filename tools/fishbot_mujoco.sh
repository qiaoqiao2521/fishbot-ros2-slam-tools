#!/usr/bin/env bash
set -e
_fishbot_mujoco_project="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$_fishbot_mujoco_project/tools/fishbot_mujoco_env.sh"
cd "$_fishbot_mujoco_project/workspaces/fishbot_mujoco_ws"
_fishbot_mujoco_action="${1:-sim}"
shift || true
case "$_fishbot_mujoco_action" in
    build)
        exec colcon build --symlink-install --packages-select fishbot_mujoco --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3 "$@" ;;
    sim)
        exec ros2 launch fishbot_mujoco sim.launch.py headless:=false rviz:=true "$@" ;;
    headless)
        exec ros2 launch fishbot_mujoco sim.launch.py headless:=true rviz:=false "$@" ;;
    web)
        exec "$_fishbot_mujoco_project/tools/fishbot_mujoco_web.sh" "$@" ;;
    verify)
        _fishbot_mujoco_mode="${1:-nav}"
        shift || true
        mkdir -p .runs
        exec ros2 run fishbot_mujoco verify_stack.py "$_fishbot_mujoco_mode" --output ".runs/${_fishbot_mujoco_mode}-acceptance.json" "$@" ;;
    *)
        echo 'Usage: fishbot_mujoco.sh {build|sim|headless|web|verify [sensors|motion|nav]} [ROS arguments]' >&2
        exit 2 ;;
esac
