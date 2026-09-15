"""Offline source-layout check. Does not import ROS or contact hardware."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    'tools/fishbot.sh', 'tools/fishbot_stack.sh', 'tools/fishbot_slam_preflight.sh',
    'tools/config/fishbot_slam.yaml', 'apps/fishbot-control-station/backend/build.gradle.kts',
    'apps/fishbot-control-station/frontend/package.json',
    'fishbot_nav/src/fishbot_navigation2/config/nav2_params.yaml',
    'fishbot_laser_ws/src/ydlidar_ros2/ydlidar/ydlidar_node.py',
    'workspaces/micro_ros_agent_ws/src/micro-ROS-Agent/micro_ros_agent/package.xml',
    'workspaces/micro_ros_agent_ws/src/micro_ros_msgs/package.xml',
    'fishbot_motion_control_microros/src/fishbot.cpp', 'FISHBOT_STATUS.md',
)


def check(root=ROOT):
    failures = []
    for name in REQUIRED:
        path = root / name
        if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            failures.append(name)
    for script in (root / 'tools').glob('*.sh'):
        if subprocess.run(['bash', '-n', str(script)], capture_output=True).returncode:
            failures.append(f'shell syntax: {script.name}')
    for failure in failures:
        print(f'FAIL {failure}')
    print(f'Offline layout: {len(REQUIRED)} required paths; {len(failures)} failures')
    print('Not a build, network, sensor freshness, firmware or navigation acceptance.')
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(check())
