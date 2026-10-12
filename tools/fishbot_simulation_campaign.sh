#!/usr/bin/env bash
set -euo pipefail
_fishbot_campaign_root="$(dirname -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")")"
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    exec /usr/bin/python3 -B "$_fishbot_campaign_root/tools/fishbot_simulation_campaign.py" "$@"
fi
_fishbot_campaign_mode=''
for ((_fishbot_campaign_index=1; _fishbot_campaign_index<=$#; _fishbot_campaign_index++)); do
    if [[ "${!_fishbot_campaign_index}" == --mode ]]; then
        _fishbot_campaign_value=$((_fishbot_campaign_index+1))
        _fishbot_campaign_mode="${!_fishbot_campaign_value:-}"
    fi
done
case "$_fishbot_campaign_mode" in
    soak) export FISHBOT_MUJOCO_DOMAIN_ID=96 ;;
    random) export FISHBOT_MUJOCO_DOMAIN_ID=102 ;;
    *) echo 'Select --mode soak or --mode random' >&2; exit 2 ;;
esac
export ROS_STATIC_PEERS=''
set +u
source "$_fishbot_campaign_root/tools/fishbot_mujoco_env.sh"
_fishbot_campaign_overlay="$("$_fishbot_campaign_root/tools/fishbot_nav2_state_query_overlay.sh" prefix)" || {
    echo 'Build the scoped Nav2 overlay: ./tools/fishbot_nav2_state_query_overlay.sh build' >&2
    exit 1
}
source "$_fishbot_campaign_overlay/local_setup.bash"
export FISHBOT_NAV2_STATE_QUERY_OVERLAY_PREFIX="$_fishbot_campaign_overlay"
set -u
exec /usr/bin/python3 -B "$_fishbot_campaign_root/tools/fishbot_simulation_campaign.py" "$@"
