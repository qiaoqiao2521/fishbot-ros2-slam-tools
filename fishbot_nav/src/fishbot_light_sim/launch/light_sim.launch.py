"""Legacy raycast simulation; explicit map, isolated domain, one localization owner."""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, IncludeLaunchDescription,
                            OpaqueFunction, SetEnvironmentVariable)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from fishbot_light_sim.runtime_contract import (ground_truth_enabled, readable_map,
                                               simulation_environment)


def setup(context):
    def value(name):
        return LaunchConfiguration(name).perform(context)
    environment = simulation_environment(value('ros_domain_id'))
    map_path = readable_map(value('map'))
    truth_localization = ground_truth_enabled(value('use_amcl'))
    description_share = get_package_share_directory('fishbot_description')
    urdf = os.path.join(description_share, 'urdf', 'fishbot.urdf')
    with open(urdf, encoding='utf-8') as stream:
        robot_description = stream.read()
    return [
        *[SetEnvironmentVariable(key, val) for key, val in environment.items()],
        Node(package='robot_state_publisher', executable='robot_state_publisher',
             name='robot_state_publisher', output='screen',
             parameters=[{'robot_description': robot_description, 'use_sim_time': False}]),
        Node(package='fishbot_light_sim', executable='fishbot_light_sim',
             name='fishbot_light_sim', output='screen',
             parameters=[LaunchConfiguration('sim_config'),
                         {'map_yaml': map_path,
                          'ground_truth_localization': truth_localization}]),
        Node(package='nav2_map_server', executable='map_server', name='map_server',
             output='screen', parameters=[LaunchConfiguration('params_file'),
                                          {'yaml_filename': map_path}]),
        Node(package='nav2_lifecycle_manager', executable='lifecycle_manager',
             name='lifecycle_manager_map', output='screen',
             parameters=[{'use_sim_time': False, 'autostart': True,
                          'node_names': ['map_server']}]),
        Node(package='nav2_amcl', executable='amcl', name='amcl', output='screen',
             parameters=[LaunchConfiguration('params_file')],
             condition=IfCondition(LaunchConfiguration('use_amcl'))),
        Node(package='nav2_lifecycle_manager', executable='lifecycle_manager',
             name='lifecycle_manager_amcl', output='screen',
             parameters=[{'use_sim_time': False, 'autostart': True,
                          'node_names': ['amcl']}],
             condition=IfCondition(LaunchConfiguration('use_amcl'))),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(
                get_package_share_directory('nav2_bringup'), 'launch', 'navigation_launch.py')),
            launch_arguments={'params_file': LaunchConfiguration('params_file'),
                              'use_composition': 'False', 'autostart': 'true',
                              'use_sim_time': 'false'}.items(),
            condition=IfCondition(LaunchConfiguration('nav'))),
        Node(package='rviz2', executable='rviz2', name='rviz2', output='screen',
             arguments=['-d', os.path.join(get_package_share_directory('fishbot_light_sim'),
                                          'config', 'light_sim.rviz')],
             condition=IfCondition(LaunchConfiguration('rviz'))),
    ]


def generate_launch_description():
    nav_share = get_package_share_directory('fishbot_navigation2')
    sim_share = get_package_share_directory('fishbot_light_sim')
    return LaunchDescription([
        DeclareLaunchArgument('map', description='Required readable map-server YAML; no private-map fallback'),
        DeclareLaunchArgument('ros_domain_id', default_value=os.environ.get('FISHBOT_LIGHT_SIM_DOMAIN_ID', '94')),
        DeclareLaunchArgument('params_file', default_value=os.path.join(nav_share, 'config', 'nav2_params.yaml')),
        DeclareLaunchArgument('sim_config', default_value=os.path.join(sim_share, 'config', 'light_sim.yaml')),
        DeclareLaunchArgument('use_amcl', default_value='false'),
        DeclareLaunchArgument('nav', default_value='true'),
        DeclareLaunchArgument('rviz', default_value='true'),
        OpaqueFunction(function=setup),
    ])
