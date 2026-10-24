"""Shared mecanum driver and laser transform."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    defaults = {
        'serial_port': ('/dev/ttyUSB0', 'Motor-controller serial path; prefer /dev/serial/by-id'),
        'baudrate': ('115200', 'Motor-controller baud rate'),
        'cmd_timeout': ('0.5', 'Host command watchdog in seconds'),
        'kinematic_k': ('0.3075', 'Mecanum rotation coefficient in meters'),
        'feedback_sign': ('-1.0', 'Measured wheel-feedback polarity'),
        'allow_cmd_odom_fallback': ('true', 'Open-loop fallback is not measured wheel feedback'),
        'min_command_pwm': ('1150', 'Legacy motor deadband compensation'),
        'cmd_topic': ('cmd_vel', 'Final command from the existing command owner'),
        'odom_topic': ('odom', 'Wheel odometry output'),
    }
    arguments = [DeclareLaunchArgument(name, default_value=value, description=description)
                 for name, (value, description) in defaults.items()]
    arguments.append(DeclareLaunchArgument('laser_yaw', description='Required calibrated laser yaw in radians'))
    driver = Node(
        package='robot_base', executable='drive_node', name='drive_node', output='screen',
        parameters=[{
            'serial_port': LaunchConfiguration('serial_port'),
            **{name: ParameterValue(LaunchConfiguration(name), value_type=kind) for name, kind in (
                ('baudrate', int), ('cmd_timeout', float), ('kinematic_k', float),
                ('feedback_sign', float), ('allow_cmd_odom_fallback', bool), ('min_command_pwm', int))},
        }],
        remappings=[('cmd_vel', LaunchConfiguration('cmd_topic')), ('odom', LaunchConfiguration('odom_topic'))],
    )
    transform = Node(
        package='tf2_ros', executable='static_transform_publisher', name='static_tf_laser',
        arguments=['--x', '0.05', '--y', '0.0', '--z', '1.35', '--roll', '0.0',
                   '--pitch', '-0.244346', '--yaw', LaunchConfiguration('laser_yaw'),
                   '--frame-id', 'base_link', '--child-frame-id', 'laser'],
    )
    return LaunchDescription([*arguments, driver, transform])
