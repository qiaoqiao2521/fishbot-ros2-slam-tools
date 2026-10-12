#!/usr/bin/env bash
set -euo pipefail
_fishbot_localization_root="$(dirname -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")")"
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    exec /usr/bin/python3 -B "$_fishbot_localization_root/tools/fishbot_localization_recovery.py" "$@"
fi
export FISHBOT_MUJOCO_DOMAIN_ID=99
export ROS_STATIC_PEERS=''
set +u
source "$_fishbot_localization_root/tools/fishbot_mujoco_env.sh"
set -u
exec /usr/bin/python3 -B "$_fishbot_localization_root/tools/fishbot_localization_recovery.py" "$@"
