#!/usr/bin/env bash
# Complete simulation-only mission; clean up exactly the process group we start.
set -euo pipefail
inspection_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${1:-}" == --help ]]; then
    echo 'Usage: fishbot_inspection.sh [NEW_OUTPUT_DIRECTORY] [runner arguments]'
    echo 'Build first with tools/fishbot_mujoco.sh build. Runs isolated simulation domain 97.'
    exit 0
fi
inspection_output="${1:-$inspection_root/workspaces/fishbot_mujoco_ws/.runs/inspection-$(date +%Y%m%d-%H%M%S)}"
if (( $# )); then shift; fi
if [[ -e "$inspection_output" ]]; then
    echo 'Use a new output directory to preserve earlier reports.' >&2
    exit 2
fi
mkdir -p "$inspection_output"
inspection_output="$(realpath "$inspection_output")"
export FISHBOT_MUJOCO_DOMAIN_ID=97 ROS_STATIC_PEERS=
export FISHBOT_MUJOCO_LOG_DIR="$inspection_output/ros-log"
# ROS setup files are not nounset-safe.
set +u
source "$inspection_root/tools/fishbot_mujoco_env.sh"
set -u
inspection_pid=
cleanup() {
    if [[ -n "$inspection_pid" ]] && kill -0 -- "-$inspection_pid" 2>/dev/null; then
        kill -INT -- "-$inspection_pid" 2>/dev/null || true
        for inspection_retry in {1..50}; do
            kill -0 -- "-$inspection_pid" 2>/dev/null || break
            sleep .1
        done
        if kill -0 -- "-$inspection_pid" 2>/dev/null; then
            kill -TERM -- "-$inspection_pid" 2>/dev/null || true
            for inspection_retry in {1..30}; do
                kill -0 -- "-$inspection_pid" 2>/dev/null || break
                sleep .1
            done
        fi
        if kill -0 -- "-$inspection_pid" 2>/dev/null; then
            kill -KILL -- "-$inspection_pid" 2>/dev/null || true
        fi
        wait "$inspection_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
setsid ros2 launch "$inspection_root/tools/fishbot_inspection.launch.py" \
    output_dir:="$inspection_output/fixture" >"$inspection_output/stack.log" 2>&1 &
inspection_pid=$!
/usr/bin/python3 "$inspection_root/tools/fishbot_inspection.py" \
    --route "$inspection_root/tools/config/fishbot_inspection_route.json" \
    --output "$inspection_output" "$@" | tee "$inspection_output/mission.log"
