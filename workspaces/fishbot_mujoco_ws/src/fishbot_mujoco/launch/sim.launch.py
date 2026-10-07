"""Wheel contact physics; AMCL alone owns map->odom when navigation is enabled."""
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, IncludeLaunchDescription, LogInfo, OpaqueFunction, RegisterEventHandler, SetEnvironmentVariable, Shutdown, TimerAction
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command, LaunchConfiguration
from launch_ros.actions import Node, SetRemap
from launch_ros.parameter_descriptions import ParameterValue


def check_sim_domain(context):
    domain = LaunchConfiguration('ros_domain_id').perform(context)
    if not domain.isdigit() or not 1 <= int(domain) <= 232:
        raise RuntimeError('Simulation requires ROS domain 1..232; domain 0 is reserved for the real car')
    return []


def generate_launch_description():
    share = get_package_share_directory('fishbot_mujoco')
    controllers = os.path.join(share, 'config', 'controllers.yaml')
    description = ParameterValue(Command([
        'xacro ', os.path.join(share, 'urdf', 'fishbot_mujoco.urdf.xacro'),
        ' headless:=', LaunchConfiguration('headless'),
        ' scene_path:=', LaunchConfiguration('scene_path'),
        ' sim_speed_factor:=1.0']), value_type=str)
    ready = Node(package='fishbot_mujoco', executable='wait_ready.py',
                 arguments=['--nav', LaunchConfiguration('nav'), '--timeout', '45'],
                 output='screen')

    def start_readiness(context):
        # OnProcessExit runs after an enclosing GroupAction has popped its launch
        # arguments. Capture the requested view now instead of looking it up later.
        show_rviz = LaunchConfiguration('rviz').perform(context).lower() == 'true'
        def after_ready(event, event_context):
            if event_context.is_shutdown:
                return []
            if event.returncode != 0:
                raise RuntimeError('FishBot sensors/navigation did not become ready within 45 seconds')
            actions = [LogInfo(msg='FishBot sensors/navigation ready; desktop view may now open.')]
            if show_rviz:
                actions.append(Node(package='rviz2', executable='rviz2',
                    arguments=['-d', os.path.join(get_package_share_directory('nav2_bringup'),
                                                 'rviz', 'nav2_default_view.rviz')],
                    parameters=[{'use_sim_time': True}]))
            return actions
        return [RegisterEventHandler(OnProcessExit(target_action=ready, on_exit=after_ready)), ready]

    return LaunchDescription([
        DeclareLaunchArgument('ros_domain_id', default_value=os.environ.get('FISHBOT_MUJOCO_DOMAIN_ID', '93')),
        OpaqueFunction(function=check_sim_domain),
        SetEnvironmentVariable('ROS_DOMAIN_ID', LaunchConfiguration('ros_domain_id')),
        SetEnvironmentVariable('FISHBOT_MUJOCO_DOMAIN_ID', LaunchConfiguration('ros_domain_id')),
        SetEnvironmentVariable('ROS_AUTOMATIC_DISCOVERY_RANGE', 'LOCALHOST'),
        SetEnvironmentVariable('ROS_LOCALHOST_ONLY', '1'),
        DeclareLaunchArgument('headless', default_value='true'),
        DeclareLaunchArgument('nav', default_value='true'),
        DeclareLaunchArgument('rviz', default_value='false'),
        DeclareLaunchArgument('bridge', default_value='false'),
        DeclareLaunchArgument('obstacle', default_value='true'),
        DeclareLaunchArgument('plugins_file', default_value=os.path.join(share, 'config', 'plugins.yaml')),
        DeclareLaunchArgument('scene_path', default_value=os.path.join(share, 'mjcf', 'arena.xml')),
        DeclareLaunchArgument('map', default_value=os.path.join(share, 'config', 'arena.yaml')),
        DeclareLaunchArgument('params_file', default_value=os.path.join(share, 'config', 'nav2.yaml')),
        Node(package='robot_state_publisher', executable='robot_state_publisher',
             parameters=[{'robot_description': description, 'use_sim_time': True}]),
        Node(package='mujoco_ros2_control', executable='ros2_control_node',
             parameters=[controllers, LaunchConfiguration('plugins_file'),
                         {'use_sim_time': True}], output='screen', on_exit=Shutdown()),
        Node(package='controller_manager', executable='spawner',
             arguments=['joint_state_broadcaster', '--param-file', controllers]),
        Node(package='controller_manager', executable='spawner',
             arguments=['diff_drive_controller', '--param-file', controllers,
                        '--controller-ros-args', '--ros-args --remap /diff_drive_controller/cmd_vel:=/cmd_vel --remap /diff_drive_controller/odom:=/odom']),
        Node(package='fishbot_mujoco', executable='obstacle_controller.py', output='screen',
             condition=IfCondition(LaunchConfiguration('obstacle'))),
        Node(package='fishbot_mujoco', executable='mission_bridge.py', output='screen',
             condition=IfCondition(LaunchConfiguration('bridge'))),
        OpaqueFunction(function=start_readiness),
        TimerAction(period=8.0, actions=[GroupAction([SetRemap(src='docking_server:cmd_vel', dst='/cmd_vel_nav'),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('nav2_bringup'), 'launch', 'bringup_launch.py')),
            launch_arguments={'map': LaunchConfiguration('map'),
                              'params_file': LaunchConfiguration('params_file'),
                              'use_sim_time': 'True', 'use_composition': 'False',
                              'autostart': 'True'}.items(), condition=IfCondition(LaunchConfiguration('nav')))])]),
    ])
