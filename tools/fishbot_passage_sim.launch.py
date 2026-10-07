"""Synthetic passage acceptance, isolated from real domain zero and baseline 93."""
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, IncludeLaunchDescription, OpaqueFunction, SetEnvironmentVariable
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def synthetic_map(scene, directory):
    boxes = []
    for geom in ET.parse(scene).getroot().find('worldbody').findall('geom'):
        if geom.get('type') == 'box':
            p, s = [list(map(float, geom.get(key).split())) for key in ('pos', 'size')]
            if p[2]-s[2] <= .167 <= p[2]+s[2]:
                boxes.append((p, s))
    resolution, width, height, origin = .02, 160, 120, (-.9, -1.2)
    pixels = bytearray()
    for row in range(height):
        y = origin[1]+(height-1-row+.5)*resolution
        for col in range(width):
            x = origin[0]+(col+.5)*resolution
            pixels.append(0 if any(abs(x-p[0]) <= s[0] and abs(y-p[1]) <= s[1] for p, s in boxes) else 254)
    image = directory / 'passage.pgm'
    image.write_bytes(f'P5\n{width} {height}\n255\n'.encode()+pixels)
    config = directory / 'passage.yaml'
    config.write_text(yaml.safe_dump({'image': str(image), 'resolution': resolution,
                                     'origin': [*origin, 0.0], 'negate': 0,
                                     'occupied_thresh': .65, 'free_thresh': .25}))
    return str(config)


def setup(context):
    domain = LaunchConfiguration('ros_domain_id').perform(context)
    if not domain.isdigit() or not 1 <= int(domain) <= 232 or int(domain) == 93:
        raise RuntimeError('Passage acceptance requires an isolated nonzero domain other than baseline 93')
    root = Path(__file__).resolve().parent
    share = Path(get_package_share_directory('fishbot_mujoco'))
    scene = share / 'mjcf/passage.xml'
    output = Path(LaunchConfiguration('output_dir').perform(context)).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    fixture = Path(tempfile.mkdtemp(prefix='fixture-', dir=output))
    map_path = synthetic_map(scene, fixture)
    return [
        SetEnvironmentVariable('ROS_DOMAIN_ID', domain),
        SetEnvironmentVariable('FISHBOT_MUJOCO_DOMAIN_ID', domain),
        SetEnvironmentVariable('ROS_AUTOMATIC_DISCOVERY_RANGE', 'LOCALHOST'),
        SetEnvironmentVariable('ROS_LOCALHOST_ONLY', '1'),
        SetEnvironmentVariable('ROS_STATIC_PEERS', ''),
        # Isolate sim's params_file/use_sim_time declarations from the passage
        # stack; otherwise ROS launch silently reuses the baseline Nav2 YAML.
        GroupAction(actions=[IncludeLaunchDescription(PythonLaunchDescriptionSource(str(share / 'launch/sim.launch.py')),
                                 launch_arguments={'ros_domain_id': domain, 'scene_path':str(scene),
                                                   'nav':'false','headless':'true','rviz':'false','bridge':'false'}.items())]),
        Node(package='nav2_map_server', executable='map_server', name='map_server',
             parameters=[{'use_sim_time':True,'yaml_filename':map_path}], output='screen'),
        Node(package='nav2_lifecycle_manager', executable='lifecycle_manager', name='map_lifecycle',
             parameters=[{'use_sim_time':True,'autostart':True,'node_names':['map_server']}]),
        # Synthetic fixture only: odometry begins at the known world origin.
        # Independent MuJoCo ground truth must still validate actual passage.
        Node(package='tf2_ros', executable='static_transform_publisher', name='fixture_map_to_odom',
             arguments=['--frame-id','map','--child-frame-id','odom'], parameters=[{'use_sim_time':True}]),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(str(root / 'fishbot_passage.launch.py')),
                                 launch_arguments={'execute':'true','ros_domain_id':domain,'allow_real':'false',
                                                   'use_sim_time':'true','output_dir':str(output / 'triggers')}.items()),
    ]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('ros_domain_id', default_value='96'),
        DeclareLaunchArgument('output_dir'),
        OpaqueFunction(function=setup),
    ])
