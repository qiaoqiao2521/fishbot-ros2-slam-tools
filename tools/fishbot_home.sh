#!/usr/bin/env bash
# One owned simulation process group; input map and generated evidence remain local.
set -euo pipefail
home_sim_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -lt 1 || "${1:-}" == --help ]]; then
    echo 'Usage: fishbot_home.sh MAP_YAML [NEW_OUTPUT_DIRECTORY] [mission arguments]'
    echo 'Runs semantic inspection and simulated charging in isolated domain 98.'
    exit 0
fi
home_sim_map="$(realpath "$1")"
shift
home_sim_output="$home_sim_root/workspaces/fishbot_mujoco_ws/.runs/home-$(date +%Y%m%d-%H%M%S)"
if (( $# )) && [[ "$1" != --* ]]; then home_sim_output="$1"; shift; fi
if [[ -e "$home_sim_output" ]]; then
    echo 'Use a new output directory to preserve earlier evidence.' >&2
    exit 2
fi
mkdir -m 700 -p "$home_sim_output"
home_sim_output="$(realpath "$home_sim_output")"
export FISHBOT_MUJOCO_DOMAIN_ID=98 ROS_STATIC_PEERS=
export FISHBOT_MUJOCO_LOG_DIR="$home_sim_output/ros-log"
set +u
source "$home_sim_root/tools/fishbot_mujoco_env.sh"
set -u
/usr/bin/python3 "$home_sim_root/tools/fishbot_home_scene.py" \
    --map "$home_sim_map" --output "$home_sim_output/fixture"
# Keep the executed source identity beside private evidence, including dirty work.
/usr/bin/python3 - "$home_sim_root" "$home_sim_output" <<'PY'
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

root, output = map(Path, sys.argv[1:])
sources = [
    'tools/fishbot_home.sh', 'tools/fishbot_home.launch.py',
    'tools/fishbot_home_mission.py', 'tools/fishbot_home_scene.py',
    'tools/fishbot_home_semantics.py', 'tools/fishbot_home_report.py',
    'tools/fishbot_sim_power.py', 'tools/fishbot_mujoco_env.sh',
    'tools/fishbot_inspection.py', 'tools/fishbot_inspection_vision.py',
    'tools/fishbot_passage_goal.py', 'tools/config/fishbot_model_geometry.yaml',
    'tools/config/fishbot_home_controller.yaml', 'tools/config/fishbot_home_tree.xml',
    'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/config/nav2.yaml',
]
manifest = {
    'recorded_utc': datetime.now(timezone.utc).isoformat(), 'domain': 98,
    'git_head': subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip(),
    'source_sha256': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sources},
    'scope': 'Source snapshot at launch; scene provenance separately binds map and robot assets.',
}
(output / 'runtime-source.json').write_text(json.dumps(manifest, indent=2) + '\n')
PY
home_sim_pid=
cleanup() {
    if [[ -n "$home_sim_pid" ]] && kill -0 -- "-$home_sim_pid" 2>/dev/null; then
        kill -INT -- "-$home_sim_pid" 2>/dev/null || true
        for home_sim_retry in {1..50}; do
            kill -0 -- "-$home_sim_pid" 2>/dev/null || break
            sleep .1
        done
        if kill -0 -- "-$home_sim_pid" 2>/dev/null; then
            kill -TERM -- "-$home_sim_pid" 2>/dev/null || true
            for home_sim_retry in {1..30}; do
                kill -0 -- "-$home_sim_pid" 2>/dev/null || break
                sleep .1
            done
        fi
        if kill -0 -- "-$home_sim_pid" 2>/dev/null; then
            kill -KILL -- "-$home_sim_pid" 2>/dev/null || true
        fi
        wait "$home_sim_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
setsid ros2 launch "$home_sim_root/tools/fishbot_home.launch.py" \
    fixture:="$home_sim_output/fixture" >"$home_sim_output/stack.log" 2>&1 &
home_sim_pid=$!
/usr/bin/python3 "$home_sim_root/tools/fishbot_home_mission.py" \
    --scene "$home_sim_output/fixture/semantic.json" --output "$home_sim_output" "$@" \
    | tee "$home_sim_output/mission.log"
