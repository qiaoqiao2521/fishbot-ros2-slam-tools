#!/usr/bin/env bash
set -euo pipefail
_scene_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
_scene_python="${FISHBOT_SPATIALLM_PYTHON:-$HOME/.cache/fishbot-spatiallm/runtime/bin/python}"
export MUJOCO_GL="${MUJOCO_GL:-egl}"
exec "$_scene_python" "$_scene_root/editor.py" "$@"
