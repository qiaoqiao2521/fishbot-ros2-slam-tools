#!/usr/bin/env bash
set -euo pipefail

ROOT="$(dirname -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")")"
BRINGUP_WS="${BRINGUP_WS:-$ROOT/fishbot_nav}"
MAPS_DIR="${MAPS_DIR:-$BRINGUP_WS/src/fishbot_navigation2/maps}"
MAP_NAME="${1:-current_map}"
# shellcheck source=fishbot_ros_env.sh
source "$ROOT/tools/fishbot_ros_env.sh"

usage() {
  cat <<EOF
Save the current /map topic into the FishBot navigation package.

Usage:
  $(basename "$0") [map_name]

Examples:
  $(basename "$0")
  $(basename "$0") live_map
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

mkdir -p "$MAPS_DIR"

set +u
fishbot_source_ros
[[ -f "$BRINGUP_WS/install/setup.bash" ]] && source "$BRINGUP_WS/install/setup.bash"
set -u

cd "$MAPS_DIR"
echo "Saving /map to $MAPS_DIR/${MAP_NAME}.{pgm,yaml}"
exec ros2 run nav2_map_server map_saver_cli -f "$MAP_NAME"
