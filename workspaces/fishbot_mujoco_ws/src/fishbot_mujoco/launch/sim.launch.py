"""Wheel contact physics; AMCL alone owns map->odom when navigation is enabled."""
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from ament_index_python.packages import get_package_prefix, get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, GroupAction, IncludeLaunchDescription, LogInfo, OpaqueFunction, RegisterEventHandler, SetEnvironmentVariable, SetLaunchConfiguration, Shutdown, TimerAction
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


def prepare_navigation_parameters(context):
    value = LaunchConfiguration('map_rules').perform(context).lower()
    if value not in ('true', 'false'):
        raise RuntimeError('map_rules must be true or false')
    helper_path = Path(__file__).with_name('keepout_parameters.py')
    spec = importlib.util.spec_from_file_location('fishbot_keepout_parameters', helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    params_file = LaunchConfiguration('params_file').perform(context)
    profile = LaunchConfiguration('control_profile').perform(context)
    actions = []
    if profile == 'passage_manual':
        if any(LaunchConfiguration(name).perform(context).lower() != 'true' for name in ('nav', 'bridge')):
            raise RuntimeError('passage_manual requires nav:=true and bridge:=true')
        domain = int(LaunchConfiguration('ros_domain_id').perform(context))
        # Reuse the ROS CLI's read-only graph probe before this launch starts any
        # node. A bridge restart cannot silently claim a surviving old Nav2 goal.
        env = {**os.environ, 'ROS_DOMAIN_ID': str(domain), 'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST',
               'ROS_LOCALHOST_ONLY': '1', 'ROS_STATIC_PEERS': ''}
        probe = subprocess.run(['/opt/ros/jazzy/bin/ros2', 'node', 'list', '--no-daemon'],
                               env=env, capture_output=True, text=True, timeout=10)
        nodes = [line for line in probe.stdout.splitlines() if line.startswith('/')
                 and not line.startswith('/_ros2cli_')]
        if probe.returncode or nodes:
            raise RuntimeError('passage_manual requires an empty isolated domain; existing nodes: '+repr(nodes))
        module_dir = Path(get_package_prefix('fishbot_mujoco'))/'lib/fishbot_mujoco'
        sys.path.insert(0, str(module_dir))
        from fishbot_manual_profile import prepare_manual_files
        output_dir = LaunchConfiguration('manual_output_dir').perform(context)
        observers = LaunchConfiguration('manual_observers').perform(context).split(',')
        receipt = prepare_manual_files(params_file, LaunchConfiguration('plugins_file').perform(context),
            output_dir, domain=domain, observers=observers,
            empty_domain_checked_at_ms=time.time_ns()//1_000_000)
        params_file = receipt['paths']['parameters']
        actions += [SetLaunchConfiguration('manual_geometry', receipt['paths']['geometry']),
                    SetLaunchConfiguration('manual_mux', receipt['paths']['mux']),
                    SetLaunchConfiguration('manual_profile_receipt', str(Path(output_dir)/'manual-profile.json')),
                    LogInfo(msg='FishBot explicit manual profile: '+json.dumps(receipt, sort_keys=True))]
    elif profile != 'baseline':
        raise RuntimeError('control_profile must be baseline or passage_manual')
    provenance = helper.prepare_keepout_parameters(params_file, value == 'true')
    return actions + [
        SetLaunchConfiguration('resolved_params_file', provenance['params_path']),
        LogInfo(msg='FishBot navigation parameters: ' + json.dumps(provenance, sort_keys=True)),
    ]


def start_manual_chain(context):
    if LaunchConfiguration('control_profile').perform(context) != 'passage_manual':
        return []
    module_dir = Path(get_package_prefix('fishbot_mujoco'))/'lib/fishbot_mujoco'
    guard = ExecuteProcess(cmd=['/usr/bin/python3', str(module_dir/'fishbot_command_guard.py'),
        '--config', LaunchConfiguration('manual_geometry').perform(context), '--output-dir',
        str(Path(LaunchConfiguration('manual_output_dir').perform(context))/'command_guard'),
        '--execute', '--output-stamped', '--timing-profile', 'strict',
        '--ros-args', '-p', 'use_sim_time:=true'], output='screen')
    def guard_exited(event, launch_context):
        if not launch_context.is_shutdown:
            raise RuntimeError('Final command guard exited; manual runtime cannot continue')
        return []
    return [RegisterEventHandler(OnProcessExit(target_action=guard, on_exit=guard_exited)), guard,
        Node(package='twist_mux', executable='twist_mux', name='twist_mux', output='screen',
             parameters=[LaunchConfiguration('manual_mux')],
             remappings=[('cmd_vel_out', '/cmd_vel_selected')])]


def start_navigation(context):
    if LaunchConfiguration('nav').perform(context).lower() != 'true':
        return []
    manual = LaunchConfiguration('control_profile').perform(context) == 'passage_manual'
    remaps = ([SetRemap(src='velocity_smoother:cmd_vel', dst='/cmd_vel_selected'),
               SetRemap(src='/cmd_vel', dst='/cmd_vel_nav')] if manual else
              [SetRemap(src='docking_server:cmd_vel', dst='/cmd_vel_nav')])
    include = IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(
        get_package_share_directory('nav2_bringup'), 'launch', 'bringup_launch.py')),
        launch_arguments={'map': LaunchConfiguration('map'),
                          'params_file': LaunchConfiguration('resolved_params_file'),
                          'use_sim_time': 'True', 'use_composition': 'False', 'autostart': 'True'}.items())
    return [TimerAction(period=8., actions=[GroupAction([*remaps, include])])]


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
                    arguments=['-d', os.path.join(share, 'config', 'simulation.rviz')],
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
        DeclareLaunchArgument('control_profile', default_value='baseline',
                              description='baseline or explicit low-speed passage_manual'),
        DeclareLaunchArgument('manual_output_dir', default_value='',
                              description='Fresh absolute external run directory required by passage_manual'),
        DeclareLaunchArgument('manual_profile_receipt', default_value=''),
        DeclareLaunchArgument('manual_observers', default_value='fishbot_mission_bridge',
                              description='Exact comma-separated final command observer node names'),
        DeclareLaunchArgument('map_rules', default_value=LaunchConfiguration('bridge'),
                              description='Enable costmap keepout filters; defaults to bridge'),
        DeclareLaunchArgument('bridge_port', default_value='9070'),
        DeclareLaunchArgument('web_port', default_value='5173'),
        DeclareLaunchArgument('obstacle', default_value='true'),
        DeclareLaunchArgument('plugins_file', default_value=os.path.join(share, 'config', 'plugins.yaml')),
        DeclareLaunchArgument('lidar3d_tf', default_value='false'),
        DeclareLaunchArgument('lidar3d_parent', default_value='laser_link'),
        DeclareLaunchArgument('lidar3d_frame', default_value='lidar3d_link'),
        DeclareLaunchArgument('lidar3d_x', default_value='0'),
        DeclareLaunchArgument('lidar3d_y', default_value='0'),
        DeclareLaunchArgument('lidar3d_z', default_value='0.035'),
        DeclareLaunchArgument('scene_path', default_value=os.path.join(share, 'mjcf', 'arena.xml')),
        DeclareLaunchArgument('map', default_value=os.path.join(share, 'config', 'arena.yaml')),
        DeclareLaunchArgument('params_file', default_value=os.path.join(share, 'config', 'nav2.yaml')),
        OpaqueFunction(function=prepare_navigation_parameters),
        OpaqueFunction(function=start_manual_chain),
        Node(package='robot_state_publisher', executable='robot_state_publisher',
             parameters=[{'robot_description': description, 'use_sim_time': True}]),
        Node(package='tf2_ros', executable='static_transform_publisher',
             arguments=['--x', LaunchConfiguration('lidar3d_x'),
                        '--y', LaunchConfiguration('lidar3d_y'),
                        '--z', LaunchConfiguration('lidar3d_z'),
                        '--roll', '0', '--pitch', '0', '--yaw', '0',
                        '--frame-id', LaunchConfiguration('lidar3d_parent'),
                        '--child-frame-id', LaunchConfiguration('lidar3d_frame')],
             parameters=[{'use_sim_time': True}],
             condition=IfCondition(LaunchConfiguration('lidar3d_tf'))),
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
             arguments=['--port', LaunchConfiguration('bridge_port'),
                        '--ui-port', LaunchConfiguration('web_port'),
                        '--control-profile', LaunchConfiguration('control_profile'),
                        '--manual-profile-receipt', LaunchConfiguration('manual_profile_receipt')],
             condition=IfCondition(LaunchConfiguration('bridge'))),
        OpaqueFunction(function=start_readiness),
        OpaqueFunction(function=start_navigation),
    ])
