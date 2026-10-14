#!/usr/bin/env bash
set -euo pipefail
_coop_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
_coop_action="${1:-help}"
shift || true
case "$_coop_action" in
  prepare)
    _coop_python="${FISHBOT_COOP_PYTHON:?Set FISHBOT_COOP_PYTHON to the existing SO101 planning Python}"
    _coop_site="$("$_coop_python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
    export PYTHONPATH="$_coop_site:/usr/lib/python3/dist-packages:${PYTHONPATH:-}"
    exec "$_coop_python" "$_coop_root/tools/cooperation_prepare.py" "$@" ;;
  run)
    _coop_python="${FISHBOT_COOP_PYTHON:?Set FISHBOT_COOP_PYTHON to the existing SO101 planning Python}"
    export FISHBOT_MUJOCO_DOMAIN_ID="${FISHBOT_COOP_DOMAIN:-114}"
    set +u
    source "$_coop_root/tools/fishbot_mujoco_env.sh"
    if [[ -n "${FISHBOT_NAV2_QUERY_OVERLAY:-}" ]]; then
      source "$FISHBOT_NAV2_QUERY_OVERLAY/local_setup.bash"
    fi
    set -u
    _coop_site="$("$_coop_python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
    export PYTHONPATH="$_coop_site:/usr/lib/python3/dist-packages:${PYTHONPATH:-}"
    exec ros2 launch "$_coop_root/tools/cooperation.launch.py" "python:=$_coop_python" "domain:=$FISHBOT_MUJOCO_DOMAIN_ID" "$@" ;;
  oracle)
    _coop_python="${FISHBOT_COOP_PYTHON:?Set FISHBOT_COOP_PYTHON to the existing SO101 planning Python}"
    export FISHBOT_MUJOCO_DOMAIN_ID="${FISHBOT_COOP_DOMAIN:-120}"
    set +u
    source "$_coop_root/tools/fishbot_mujoco_env.sh"
    set -u
    _coop_site="$("$_coop_python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
    export PYTHONPATH="$_coop_site:/usr/lib/python3/dist-packages:${PYTHONPATH:-}"
    exec "$_coop_python" -B "$_coop_root/tools/cooperation_oracle.py" "$@" ;;
  *)
    echo 'Set FISHBOT_COOP_PYTHON; use prepare --so101-project PATH --output NEW_PATH [--perception-config JSON], then run manifest:=PATH output:=PATH; oracle --help observes/scores without controlling tasks.' ;;
esac
