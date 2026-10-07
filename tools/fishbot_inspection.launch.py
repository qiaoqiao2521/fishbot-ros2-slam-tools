"""Synthetic camera inspection with AMCL; fixed isolated simulation domain 97."""
from pathlib import Path
import subprocess

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction, SetEnvironmentVariable
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def setup(context):
    share = Path(get_package_share_directory('fishbot_mujoco'))
    root = Path(__file__).resolve().parent.parent
    output = Path(LaunchConfiguration('output_dir').perform(context)).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    scene = share/'mjcf/inspection.xml'
    image = output/'inspection-map.pgm'
    subprocess.run(['/usr/bin/python3', str(root/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/scripts/make_fixture_map.py'),
                    str(scene), str(image)], check=True, timeout=10)
    map_file = output/'inspection-map.yaml'
    map_file.write_text(yaml.safe_dump({'image': str(image), 'resolution': .05,
                                      'origin': [-4.2, -4.2, 0.], 'negate': 0,
                                      'occupied_thresh': .65, 'free_thresh': .25}))
    return [Node(package='tf2_ros', executable='static_transform_publisher',
                 name='inspection_camera_frame',
                 arguments=['--x', '.06', '--y', '0', '--z', '.168',
                            '--roll', '-1.5707963267948966', '--pitch', '0',
                            '--yaw', '-1.5707963267948966',
                            '--frame-id', 'base_link', '--child-frame-id', 'inspection_camera_optical_frame'],
                 parameters=[{'use_sim_time': True}]),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(str(share/'launch/sim.launch.py')),
        launch_arguments={'ros_domain_id': '97', 'headless': 'true', 'rviz': 'false',
                          'bridge': 'false', 'obstacle': 'false', 'nav': 'true',
                          'scene_path': str(scene), 'map': str(map_file),
                          'plugins_file': str(share/'config/inspection_plugins.yaml')}.items())]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('output_dir'),
        SetEnvironmentVariable('ROS_DOMAIN_ID', '97'),
        SetEnvironmentVariable('FISHBOT_MUJOCO_DOMAIN_ID', '97'),
        SetEnvironmentVariable('ROS_AUTOMATIC_DISCOVERY_RANGE', 'LOCALHOST'),
        SetEnvironmentVariable('ROS_LOCALHOST_ONLY', '1'),
        SetEnvironmentVariable('ROS_STATIC_PEERS', ''),
        OpaqueFunction(function=setup),
    ])
