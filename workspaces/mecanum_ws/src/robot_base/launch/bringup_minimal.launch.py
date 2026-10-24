"""Reuse the shared driver and existing Slamtec C1 launch."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    def include(package, filename, arguments=None):
        return IncludeLaunchDescription(PythonLaunchDescriptionSource(
            PathJoinSubstitution([FindPackageShare(package), 'launch', filename])),
            launch_arguments=(arguments or {}).items())

    return LaunchDescription([
        DeclareLaunchArgument('laser_port', description='Stable laser serial path'),
        include('robot_base', 'drive.launch.py'),
        include('sllidar_ros2', 'sllidar_c1_launch.py', {'serial_port': LaunchConfiguration('laser_port')}),
    ])
