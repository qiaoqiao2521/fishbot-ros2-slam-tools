#!/usr/bin/env bash
set -euo pipefail
ROOT="$(dirname -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")")"
PACKAGE="$ROOT/workspaces/mecanum_ws/src/robot_base"
OUTPUT="${FISHBOT_MECANUM_BUILD_ROOT:-${XDG_CACHE_HOME:-$HOME/.cache}/fishbot/mecanum-build}"
COMMAND="${1:-help}"
if (($#)); then shift; fi
case "$COMMAND" in
  help|-h|--help)
    echo 'Mecanum: info | build | args <drive|minimal|mapping|navigation|rviz>'
    echo 'Explicit hardware launches: drive | minimal | mapping | navigation | rviz [ROS launch arguments]'
    echo 'Build output: FISHBOT_MECANUM_BUILD_ROOT or ~/.cache/fishbot/mecanum-build'
    exit 0 ;;
  info)
    /usr/bin/python3 - "$PACKAGE" "$OUTPUT" <<'INFO'
import json, sys
from pathlib import Path
package, output = map(Path, sys.argv[1:])
print(json.dumps({'vehicle': 'robot_base_mecanum', 'ros_package': 'robot_base',
    'source': str(package), 'install': str(output/'install'), 'drive': 'mecanum_x',
    'interfaces': ['Twist vx/vy/wz', 'Odometry', 'odom->base_link TF', 'scan/map', 'Nav2 actions'],
    'serial': {'protocol': '$pwm:m1,m2,m3,m4# / $MSPD:mm_s1,mm_s2,mm_s3,mm_s4#'},
    'status': 'source integrated; hardware not accepted; simulation evidence tracked separately',
    'simulation': {'cli': './fishbot.sh cooperation',
        'scene_profile': {'schema': 1, 'vehicle': 'robot_base_mecanum', 'sensors': 'planar', 'task': 'transport'},
        'report': '/results#workbench-delivery-timing'},
    'legacy_nav_lateral_velocity_limit_m_s': 0.0}, ensure_ascii=False, indent=2))
INFO
    exit 0 ;;
esac
set +u
source /opt/ros/jazzy/setup.bash
set -u
if [[ "$COMMAND" == build ]]; then
  mkdir -p "$OUTPUT"
  exec colcon --log-base "$OUTPUT/log" build --base-paths "$PACKAGE" \
    --packages-select robot_base --build-base "$OUTPUT/build" --install-base "$OUTPUT/install" "$@"
fi
SHOW_ARGS=()
if [[ "$COMMAND" == args ]]; then
  COMMAND="${1:-drive}"
  if (($#)); then shift; fi
  SHOW_ARGS=(--show-args)
fi
case "$COMMAND" in
  drive) LAUNCH=drive.launch.py ;;
  minimal) LAUNCH=bringup_minimal.launch.py ;;
  mapping) LAUNCH=bringup.launch.py ;;
  navigation) LAUNCH=nav_all.launch.py ;;
  rviz) LAUNCH=rviz_nav.launch.py ;;
  *) echo "Unknown mecanum command: $COMMAND" >&2; exit 2 ;;
esac
if [[ ! -f "$OUTPUT/install/setup.bash" ]]; then
  echo 'Mecanum overlay is not built. Run ./fishbot.sh mecanum build.' >&2
  exit 2
fi
set +u
source "$OUTPUT/install/setup.bash"
set -u
exec ros2 launch robot_base "$LAUNCH" "${SHOW_ARGS[@]}" "$@"
