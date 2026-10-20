#!/usr/bin/env bash
suction_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
suction_python="${FISHBOT_SUCTION_PYTHON:-$HOME/.cache/fishbot/suction-python/bin/python}"
if [[ ! -x "$suction_python" ]]; then
  echo 'Negative-pressure experiments need an isolated Python with mujoco==3.3.7. Set FISHBOT_SUCTION_PYTHON; see docs/HARDWARE_LAB.md.' >&2
  exit 1
fi
export MUJOCO_GL="${MUJOCO_GL:-egl}"
exec env -u PYTHONPATH -u LD_LIBRARY_PATH "$suction_python" "$suction_root/tools/fishbot_suction.py" "$@"
