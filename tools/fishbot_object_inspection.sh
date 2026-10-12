#!/usr/bin/env bash
# Reuse the established isolated camera/Nav2 runtime; ML stays in a local environment.
set -euo pipefail
object_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
object_cache="${FISHBOT_OBJECT_CACHE:-$HOME/.cache/fishbot/object-inspection}"
object_python="${FISHBOT_OBJECT_PYTHON:-$object_root/../../vision/uw-yolo-code-assets/.venv-monitor/bin/python}"
object_assets="${FISHBOT_OBJECT_ASSETS:-$object_cache/assets-v3}"
object_device="${FISHBOT_OBJECT_DEVICE:-cuda:0}"
if [[ "${1:-}" == --help ]]; then
    echo 'Usage: fishbot_object_inspection.sh NEW_EXTERNAL_OUTPUT_DIRECTORY'
    echo 'Requires prepared cache assets/yolo11n.pt and a local Ultralytics interpreter.'
    exit 0
fi
object_output="${1:?Provide a new external output directory}"
if [[ -e "$object_output" || ! -x "$object_python" || ! -f "$object_cache/yolo11n.pt" || ! -f "$object_assets/manifest.json" ]]; then
    echo 'Output must be new; prepare the cached official model/assets and local interpreter first.' >&2
    exit 2
fi
object_output="$(realpath -m "$object_output")"
case "$object_output/" in "$object_root/"*) echo 'Use an external output directory.' >&2; exit 2;; esac
mkdir -m 700 -p -- "$object_output"
/usr/bin/python3 - "$object_root" "$object_output" <<'PY'
import hashlib,json,sys,time
from pathlib import Path
root,output=map(Path,sys.argv[1:])
paths=['tools/fishbot_object_infer.py','tools/fishbot_object_inspection.py',
       'tools/fishbot_object_scene.py','tools/fishbot_object_inspection.launch.py',
       'tools/fishbot_object_inspection.sh','tools/fishbot_inspection.py',
       'tools/fishbot_inspection_vision.py','tools/fishbot_passage_goal.py',
       'tools/config/fishbot_passage_tree.xml',
       'tools/config/fishbot_passage_nav.yaml',
       'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/launch/sim.launch.py',
       'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/config/nav2.yaml',
       'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/config/inspection_plugins.yaml']
with (output/'runtime-provenance.json').open('x') as file:
    json.dump({'domain':101,'steady_time':time.monotonic(),
               'source_sha256':{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths}},file,indent=2)
PY
export FISHBOT_MUJOCO_DOMAIN_ID=101 ROS_STATIC_PEERS=
export FISHBOT_MUJOCO_LOG_DIR="$object_output/ros-log"
set +u
source "$object_root/tools/fishbot_mujoco_env.sh"
set -u
object_pid=
cleanup() {
    if [[ -n "$object_pid" ]]; then
        kill -INT -- "-$object_pid" 2>/dev/null || true
        for object_retry in {1..60}; do kill -0 -- "-$object_pid" 2>/dev/null || break; sleep .1; done
        kill -TERM -- "-$object_pid" 2>/dev/null || true
        for object_retry in {1..30}; do kill -0 -- "-$object_pid" 2>/dev/null || break; sleep .1; done
        kill -KILL -- "-$object_pid" 2>/dev/null || true
        wait "$object_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
# Direct graph check, bypassing the shared ROS CLI daemon.
/usr/bin/python3 - <<'PY'
import rclpy,time
rclpy.init();node=rclpy.create_node('object_domain_check');until=time.monotonic()+5
try:
    while time.monotonic()<until:
        rclpy.spin_once(node,timeout_sec=.1)
        others=[n for n in node.get_node_names() if n!=node.get_name()]
        if others:raise RuntimeError('Domain 101 is occupied: '+str(others))
finally:node.destroy_node();rclpy.shutdown()
PY
setsid ros2 launch "$object_root/tools/fishbot_object_inspection.launch.py" \
    output_dir:="$object_output/fixture" assets:="$object_assets" >"$object_output/stack.log" 2>&1 &
object_pid=$!
for object_retry in {1..100}; do
    [[ -f "$object_output/fixture/route.json" ]] && break
    kill -0 "$object_pid" 2>/dev/null || { echo 'Object launch exited before fixture creation.' >&2; exit 1; }
    sleep .1
done
/usr/bin/python3 "$object_root/tools/fishbot_object_inspection.py" --python "$object_python" \
    --model "$object_cache/yolo11n.pt" --device "$object_device" --route "$object_output/fixture/route.json" \
    --output "$object_output" | tee "$object_output/mission.log"
