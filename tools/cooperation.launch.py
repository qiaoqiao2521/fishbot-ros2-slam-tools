"""Separate common-world driver, native Nav2, and fixed-workcell task bridge."""
import json
import os
from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, GroupAction, IncludeLaunchDescription, OpaqueFunction, SetEnvironmentVariable, Shutdown, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, SetRemap


def start(context):
    domain=LaunchConfiguration('domain').perform(context)
    if not domain.isdigit() or not 1<=int(domain)<=232 or int(domain)==107:
        raise RuntimeError('协同必须使用独立非零域，当前107保留')
    manifest_path=Path(LaunchConfiguration('manifest').perform(context)).resolve()
    manifest=json.loads(manifest_path.read_text());root=Path(__file__).resolve().parent
    if not manifest.get('localization_map_yaml') or not manifest.get('collision_map_yaml'):
        raise RuntimeError('旧协同场景只有投影地图；请 prepare 到新目录以生成定位图与碰撞图')
    python=LaunchConfiguration('python').perform(context)
    output=Path(LaunchConfiguration('output').perform(context)).resolve()
    if (output/'tasks'/'task.json').exists():
        raise RuntimeError('已有任务账本，不能复用旧物理回合；保留记录并创建新场景与运行目录')
    frames=output/'frames'
    port=LaunchConfiguration('port').perform(context)
    return [SetEnvironmentVariable('ROS_DOMAIN_ID',domain),
        SetEnvironmentVariable('ROS_AUTOMATIC_DISCOVERY_RANGE','LOCALHOST'),SetEnvironmentVariable('ROS_LOCALHOST_ONLY','1'),
        ExecuteProcess(cmd=[python,str(root/'cooperation_sim.py'),'--scene',manifest['world_xml'],'--domain',domain,
            '--stamped-cmd-vel','--frame-dir',str(frames),'--frame-fps','2',
            '--state-log',str(output/'physics.jsonl'),'--timing-log',str(output/'loop-timing.json')],
            output='screen',on_exit=Shutdown()),
        ExecuteProcess(cmd=[python,str(root/'cooperation_bridge.py'),'--manifest',str(manifest_path),'--domain',domain,
            '--port',port,'--frame-dir',str(frames),'--output',str(output/'tasks')],output='screen',on_exit=Shutdown()),
        Node(package='nav2_map_server',executable='map_server',name='cooperation_collision_map_server',
            parameters=[{'use_sim_time':True,'yaml_filename':manifest['collision_map_yaml'],
                         'topic_name':'cooperation_collision_map','frame_id':'map'}],
            output='screen',on_exit=Shutdown()),
        Node(package='nav2_lifecycle_manager',executable='lifecycle_manager',
            name='lifecycle_manager_cooperation_collision_map',
            parameters=[{'use_sim_time':True,'autostart':True,
                         'node_names':['cooperation_collision_map_server']}],output='screen',on_exit=Shutdown()),
        TimerAction(period=5.,actions=[GroupAction([
            SetRemap(src='docking_server:cmd_vel',dst='/cmd_vel_nav'),
            IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('nav2_bringup'),'launch','bringup_launch.py')),
            launch_arguments={'map':manifest['localization_map_yaml'],'params_file':manifest['nav2_yaml'],'use_sim_time':'True',
                              'use_composition':'False','autostart':'True'}.items())])])]


def generate_launch_description():
    return LaunchDescription([DeclareLaunchArgument('manifest'),DeclareLaunchArgument('python'),
        DeclareLaunchArgument('output'),DeclareLaunchArgument('domain',default_value='114'),
        DeclareLaunchArgument('port',default_value='9086'),OpaqueFunction(function=start)])
