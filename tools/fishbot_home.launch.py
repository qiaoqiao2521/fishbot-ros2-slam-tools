"""Private completed-map fixture, AMCL, camera and simulated charger in domain 98."""
import json
import os
from pathlib import Path
import sys

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, ExecuteProcess, IncludeLaunchDescription,
                            OpaqueFunction, SetEnvironmentVariable)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def setup(context):
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / 'tools'))
    from fishbot_sim_power import configure_docking
    share = Path(get_package_share_directory('fishbot_mujoco'))
    fixture = Path(LaunchConfiguration('fixture').perform(context)).expanduser().resolve()
    for name in ('scene.xml', 'map.yaml', 'semantic.json'):
        if not (fixture / name).is_file():
            raise RuntimeError(f'missing prepared fixture: {name}')
    semantic = json.loads((fixture / 'semantic.json').read_text())
    params = yaml.safe_load((share / 'config/nav2.yaml').read_text())
    geometry = yaml.safe_load((root / 'tools/config/fishbot_model_geometry.yaml').read_text())
    for name in ('local_costmap', 'global_costmap'):
        costmap = params[name][name]['ros__parameters']
        costmap.pop('robot_radius', None)
        costmap.update(footprint=json.dumps(geometry['footprint']['points_m']),
                       footprint_padding=geometry['footprint']['padding_m'])
    params['velocity_smoother']['ros__parameters']['velocity_timeout'] = .2
    params['collision_monitor']['ros__parameters']['FootprintApproach']['min_points'] = 1
    params['planner_server']['ros__parameters']['GridBased']['allow_unknown'] = False
    # This fixture is static and fully represented in the generated map.
    # Re-marking walls through AMCL can seal narrow openings with duplicate cells.
    # Live local scan collision checks and the final Collision Monitor remain active.
    params['global_costmap']['global_costmap']['ros__parameters']['plugins'] = [
        'static_layer', 'inflation_layer']
    # The rolling odom map uses nearby measured surfaces. Reprojecting the map
    # into it would combine differently localized copies of those same walls.
    params['local_costmap']['local_costmap']['ros__parameters']['plugins'] = [
        'voxel_layer', 'inflation_layer']
    # Preserve measured clearance when rasterizing walls oblique to odom.
    # The global/source map remains unchanged at its original resolution.
    params['local_costmap']['local_costmap']['ros__parameters']['resolution'] = .01
    # Match the likelihood model to this noiseless simulated lidar and 5 cm map.
    # Broad tutorial defaults admitted heading offsets larger than the dock tolerance.
    params['amcl']['ros__parameters'].update(
        sigma_hit=.05, max_beams=180, z_hit=.95, z_rand=.05,
        update_min_a=.02, update_min_d=.02)
    params['controller_server']['ros__parameters']['general_goal_checker'].update(
        xy_goal_tolerance=.05, yaw_goal_tolerance=.05)
    # Keep the base RPP controller for normal travel. The home tree selects MPPI
    # only after a completed control failure, for the rest of that goal.
    params['controller_server']['ros__parameters']['controller_plugins'] = ['FollowPath', 'NarrowPassage']
    params['controller_server']['ros__parameters']['NarrowPassage'] = yaml.safe_load(
        (root / 'tools/config/fishbot_home_controller.yaml').read_text())
    params['controller_server']['ros__parameters']['progress_checker']['required_movement_radius'] = .05
    configure_docking(params, semantic)
    home_tree = str(root / 'tools/config/fishbot_home_tree.xml')
    params['bt_navigator']['ros__parameters']['default_nav_to_pose_bt_xml'] = home_tree
    params['docking_server']['ros__parameters']['navigator_bt_xml'] = home_tree
    configured = fixture / 'home-nav2.yaml'
    configured.write_text(yaml.safe_dump(params, sort_keys=False))
    power_command = ['/usr/bin/python3', str(root / 'tools/fishbot_sim_power.py'),
                     '--scene', str(fixture / 'semantic.json')]
    disabled = LaunchConfiguration('disable_charging').perform(context)
    if disabled not in ('true', 'false'):
        raise ValueError('disable_charging must be true or false')
    if disabled == 'true':
        power_command.append('--disable-charging')
    return [
        Node(package='tf2_ros', executable='static_transform_publisher', name='home_camera_frame',
             arguments=['--x', '.06', '--y', '0', '--z', '.168', '--roll', '-1.5707963267948966',
                        '--pitch', '0', '--yaw', '-1.5707963267948966', '--frame-id', 'base_link',
                        '--child-frame-id', 'inspection_camera_optical_frame'],
             parameters=[{'use_sim_time': True}]),
        ExecuteProcess(cmd=power_command, output='screen'),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(str(share / 'launch/sim.launch.py')),
            launch_arguments={'ros_domain_id': '98', 'headless': 'true', 'rviz': 'false',
                              'bridge': 'false', 'obstacle': 'false', 'nav': 'true',
                              'scene_path': str(fixture / 'scene.xml'), 'map': str(fixture / 'map.yaml'),
                              'params_file': str(configured),
                              'plugins_file': str(share / 'config/inspection_plugins.yaml')}.items())]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('fixture'),
        DeclareLaunchArgument('disable_charging', default_value=os.environ.get('FISHBOT_HOME_DISABLE_CHARGING', 'false')),
        SetEnvironmentVariable('ROS_DOMAIN_ID', '98'),
        SetEnvironmentVariable('FISHBOT_MUJOCO_DOMAIN_ID', '98'),
        SetEnvironmentVariable('ROS_AUTOMATIC_DISCOVERY_RANGE', 'LOCALHOST'),
        SetEnvironmentVariable('ROS_LOCALHOST_ONLY', '1'),
        SetEnvironmentVariable('ROS_STATIC_PEERS', ''),
        OpaqueFunction(function=setup),
    ])
