#!/usr/bin/env bash
set -euo pipefail
_fishbot_suite_root="$(dirname -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")")"
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    exec /usr/bin/python3 -B "$_fishbot_suite_root/tools/fishbot_simulation_suite.py" "$@"
fi
export FISHBOT_MUJOCO_DOMAIN_ID=96
export ROS_STATIC_PEERS=''
# ROS setup scripts read optional environment variables without defaults.
set +u
source "$_fishbot_suite_root/tools/fishbot_mujoco_env.sh"
set -u
exec /usr/bin/python3 -B "$_fishbot_suite_root/tools/fishbot_simulation_suite.py" "$@"
