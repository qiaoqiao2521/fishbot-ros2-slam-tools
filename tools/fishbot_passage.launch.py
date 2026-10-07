#!/usr/bin/env python3
"""Persistent Nav2 during SLAM; importing/rendering does not initialize ROS.

No AMCL, map server, static TF or sensor driver is launched here.
Default execute=false validates configuration only. Domain 0 additionally needs
allow_real=true. The owning runner checks the current robot and motion readiness.
"""
import copy
import json
import math
from pathlib import Path
import tempfile

import yaml

ROOT = Path(__file__).resolve().parent


def convex_polygon(points):
    """Validate an ordered strict CCW convex polygon; never repair bad geometry."""
    if not isinstance(points, list) or len(points) < 3:
        raise ValueError('footprint needs at least three ordered vertices')
    result = []
    for point in points:
        if len(point) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                  or not math.isfinite(v) for v in point):
            raise ValueError('footprint coordinates must be finite numbers')
        result.append(tuple(float(v) for v in point))
    for i in range(len(result)):
        a, b, c = result[i-1], result[i], result[(i+1) % len(result)]
        if (b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]) <= 1e-12:
            raise ValueError('footprint must be strictly convex and counterclockwise')
    return result


def expanded_polygon(points, padding, xmin=0.0, xmax=0.0):
    """Outer envelope of polygon + disk padding + the x-translation interval.

    Intersecting original outward support lines keeps the result conservative
    without filling the whole swept shape's bounding rectangle. For rotations,
    the caller adds the maximum point-displacement bound to padding.
    """
    lines = []
    for i, a in enumerate(points):
        b = points[(i+1) % len(points)]
        dx, dy = b[0]-a[0], b[1]-a[1]
        size = math.hypot(dx, dy)
        nx, ny = dy/size, -dx/size
        lines.append((nx, ny, nx*a[0]+ny*a[1]+padding+max(nx*xmin, nx*xmax)))
    out = []
    for i, (ax, ay, ah) in enumerate(lines):
        bx, by, bh = lines[(i+1) % len(lines)]
        det = ax*by-ay*bx
        if abs(det) < 1e-12:
            raise ValueError('parallel adjacent footprint edges')
        out.append([(ah*by-ay*bh)/det, (ax*bh-ah*bx)/det])
    return out


def _number(mapping, key, low, high):
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{key} must be finite')
    if not low <= value <= high:
        raise ValueError(f'{key} outside supported bounds [{low}, {high}]')
    return float(value)


def build_parameters(config, geometry):
    """Return Nav2 parameters generated from the single authoritative geometry."""
    if geometry.get('schema_version') != 1:
        raise ValueError('unsupported geometry schema')
    points = convex_polygon(geometry['footprint']['points_m'])
    padding = _number(geometry['footprint'], 'padding_m', 0.0, 0.03)
    motion, collision, frames = geometry['motion'], geometry['collision'], geometry['frames']
    vmax = _number(motion, 'max_linear_mps', 0.01, 0.08)
    wmax = _number(motion, 'max_angular_rps', 0.02, 0.25)
    vslow = _number(motion, 'slow_linear_mps', 0.01, vmax)
    hard_time = _number(collision, 'hard_reaction_time_s', 0.05, 1.0)
    soft_pad = _number(collision, 'soft_padding_m', 0.0, 0.20)
    approach_time = _number(collision, 'approach_time_s', hard_time, 3.0)
    step = _number(collision, 'simulation_step_s', 0.01, 0.10)
    source_timeout = _number(collision, 'source_timeout_s', 0.1, 0.5)
    if collision.get('min_points') != 1:
        raise ValueError('hard collision policy requires min_points=1 for thin obstacles')
    if any(not isinstance(frames.get(k), str) or not frames[k] for k in ('base', 'odom', 'map', 'scan')):
        raise ValueError('all coordinate frame names are required')
    p = copy.deepcopy(config)
    p['bt_navigator']['ros__parameters']['default_nav_to_pose_bt_xml'] = str(
        ROOT/'config/fishbot_passage_tree.xml')
    p['bt_navigator']['ros__parameters'].update(
        global_frame=frames['map'], robot_base_frame=frames['base'])
    p['behavior_server']['ros__parameters'].update(
        global_frame=frames['map'], local_frame=frames['odom'], robot_base_frame=frames['base'])
    p['docking_server']['ros__parameters'].update(
        base_frame=frames['base'], fixed_frame=frames['odom'])
    footprint = expanded_polygon(points, padding)
    encoded = lambda shape: json.dumps(shape, separators=(',', ':'))
    for name in ('local_costmap', 'global_costmap'):
        c = p[name][name]['ros__parameters']
        c.pop('robot_radius', None)
        c.update(footprint=encoded(footprint), footprint_padding=0.0,
                 robot_base_frame=frames['base'])
    p['local_costmap']['local_costmap']['ros__parameters']['global_frame'] = frames['odom']
    p['global_costmap']['global_costmap']['ros__parameters']['global_frame'] = frames['map']
    cm = p['collision_monitor']['ros__parameters']
    cm.update(base_frame_id=frames['base'], odom_frame_id=frames['odom'],
              source_timeout=source_timeout)
    cm['FootprintApproach'] = dict(type='polygon', action_type='approach',
        footprint_topic='/local_costmap/published_footprint',
        time_before_collision=approach_time, simulation_time_step=step,
        min_points=1, visualize=False, enabled=True)
    cm['Slowdown'] = dict(type='polygon', action_type='limit',
        points=encoded(expanded_polygon(points, padding+soft_pad)),
        linear_limit=vslow, angular_limit=min(.15, wmax),
        min_points=1, visualize=True, polygon_pub_topic='/passage_slow_polygon', enabled=True)
    stop = dict(type='velocity_polygon', action_type='stop', holonomic=False,
                min_points=1, visualize=True, polygon_pub_topic='/passage_stop_polygon',
                enabled=True, velocity_polygons=[])
    # First matching closed interval wins. Small/idle bands go first. Each
    # zone covers EVERY velocity in its band, including both signs at zero.
    linear_bands = [('idle', -.001, .001), ('forward_slow', 0., vslow),
                    ('reverse_slow', -vslow, 0.), ('forward', vslow, vmax),
                    ('reverse', -vmax, -vslow)]
    angular_bands = [('straight', -.01, .01), ('left', 0., wmax), ('right', -wmax, 0.)]
    radius = max(math.hypot(x, y) for x, y in points)
    for linear_name, vlo, vhi in linear_bands:
        for angular_name, wlo, whi in angular_bands:
            name = linear_name+'_'+angular_name
            turn = max(abs(wlo), abs(whi))*hard_time
            # Rigid-body rotation displacement <= radius * |angle|. During
            # turning, translation can depart from x by <= v*t*|angle|;
            # adding that bound makes this envelope conservative for arcs too.
            turn_padding = radius*turn + max(abs(vlo), abs(vhi))*hard_time*turn
            shape = expanded_polygon(points, padding+turn_padding,
                                     min(0., vlo*hard_time), max(0., vhi*hard_time))
            stop['velocity_polygons'].append(name)
            stop[name] = dict(points=encoded(shape), linear_min=vlo, linear_max=vhi,
                              theta_min=wlo, theta_max=whi)
    cm['VelocityStop'] = stop
    c = p['controller_server']['ros__parameters']['FollowPath']
    c.update(desired_linear_vel=vmax, rotate_to_heading_angular_vel=wmax,
             regulated_linear_scaling_min_speed=vslow)
    smooth = p['velocity_smoother']['ros__parameters']
    smooth.update(max_velocity=[vmax, 0., wmax], min_velocity=[-vslow, 0., -wmax])
    return p


def load_parameters(config_path=None, geometry_path=None):
    config = yaml.safe_load(Path(config_path or ROOT/'config/fishbot_passage_nav.yaml').read_text())
    geometry = yaml.safe_load(Path(geometry_path or ROOT/'config/fishbot_model_geometry.yaml').read_text())
    return build_parameters(config, geometry), geometry


def validate_execution_request(domain, execute, allow_real, sim_time, output_dir=''):
    """Check opt-ins and private evidence location without filesystem mutation."""
    if not 0 <= domain <= 232:
        raise ValueError('ros_domain_id must be 0..232')
    if domain == 0 and (not allow_real or sim_time):
        raise ValueError('domain 0 requires allow_real:=true and use_sim_time:=false')
    if not execute:
        return None
    if not output_dir or not Path(output_dir).is_absolute():
        raise ValueError('execute=true requires an absolute external output_dir')
    output = Path(output_dir).resolve()
    # Use the nearest owning repository. An unrelated parent/home dotfiles
    # repository must not redefine the independent source checkout boundary.
    for parent in (ROOT, *ROOT.parents):
        if (parent/'.git').exists():
            if output.is_relative_to(parent):
                raise ValueError('output_dir must be outside the source repository')
            break
    if output.exists() and not output.is_dir():
        raise ValueError('output_dir must be a directory')
    return output


def _launch(context):
    # Keep ROS imports out of offline geometry/replay use.
    from ament_index_python.packages import get_package_share_directory
    from launch.actions import (ExecuteProcess, GroupAction, IncludeLaunchDescription,
                                LogInfo, SetEnvironmentVariable)
    from launch.launch_description_sources import PythonLaunchDescriptionSource
    from launch.substitutions import LaunchConfiguration
    def arg(name):
        return LaunchConfiguration(name).perform(context)
    def boolean(name):
        text = arg(name).lower()
        if text not in ('true', 'false'):
            raise ValueError(name+' must be true or false')
        return text == 'true'
    execute, allow_real, sim_time = boolean('execute'), boolean('allow_real'), boolean('use_sim_time')
    domain = int(arg('ros_domain_id'))
    output_dir = validate_execution_request(domain, execute, allow_real, sim_time, arg('output_dir'))
    params, _ = load_parameters(arg('params_file'), arg('geometry_file'))
    for name, section in params.items():
        nested = section.get(name, section)
        if 'ros__parameters' in nested:
            nested['ros__parameters']['use_sim_time'] = sim_time
    if not execute:
        return [LogInfo(msg='Passage configuration valid; execute=false, no ROS nodes started.')]
    guard_path = ROOT/'fishbot_command_guard.py'
    tree_path = ROOT/'config/fishbot_passage_tree.xml'
    if not guard_path.is_file() or not tree_path.is_file():
        raise ValueError('passage command guard and bounded behavior tree are required')
    guard_cmd = ['/usr/bin/python3', str(guard_path), '--config', arg('geometry_file'),
                 '--output-dir', str(output_dir/'command_guard'), '--execute']
    if sim_time:
        guard_cmd += ['--output-stamped', '--expected-subscriber', 'diff_drive_controller']
    guard_cmd += ['--ros-args', '-p', 'use_sim_time:='+str(sim_time).lower()]
    guard = ExecuteProcess(cmd=guard_cmd, name='fishbot_command_guard', output='screen')
    # launch owns this temporary parameter file through process shutdown.
    from launch.actions import RegisterEventHandler
    from launch.event_handlers import OnProcessExit, OnShutdown
    from launch_ros.actions import SetRemap
    with tempfile.NamedTemporaryFile(mode='w', prefix='fishbot-passage-', suffix='.yaml', delete=False) as tmp:
        yaml.safe_dump(params, tmp, sort_keys=False)
        temporary = Path(tmp.name)
    def cleanup(_event, _context):
        temporary.unlink(missing_ok=True)
        return []
    def guard_exited(event, launch_context):
        if not launch_context.is_shutdown:
            raise RuntimeError('Final command guard exited unexpectedly with code '+str(event.returncode))
        return []
    launch_file = Path(get_package_share_directory('nav2_bringup'))/'launch/navigation_launch.py'
    return [SetEnvironmentVariable('ROS_DOMAIN_ID', str(domain)),
        SetEnvironmentVariable('ROS_AUTOMATIC_DISCOVERY_RANGE', 'SUBNET' if domain == 0 else 'LOCALHOST'),
        SetEnvironmentVariable('ROS_LOCALHOST_ONLY', '0' if domain == 0 else '1'),
        SetEnvironmentVariable('ROS_STATIC_PEERS', ''),
        RegisterEventHandler(OnShutdown(on_shutdown=cleanup)),
        RegisterEventHandler(OnProcessExit(target_action=guard, on_exit=guard_exited)),
        guard,
        GroupAction(actions=[
            # The installed navigation launch also activates docking_server,
            # which otherwise publishes directly to cmd_vel. Scope this remap
            # to ALL Nav2 nodes, outside the sole final guard process.
            SetRemap(src='/cmd_vel', dst='/cmd_vel_nav'),
            IncludeLaunchDescription(PythonLaunchDescriptionSource(str(launch_file)),
                launch_arguments={'params_file': str(temporary), 'use_sim_time': str(sim_time).lower(),
                                  'autostart': 'true', 'use_composition': 'False',
                                  'use_respawn': 'False'}.items()),
        ])]


def generate_launch_description():
    from launch import LaunchDescription
    from launch.actions import DeclareLaunchArgument, OpaqueFunction
    return LaunchDescription([
        DeclareLaunchArgument('execute', default_value='false'),
        DeclareLaunchArgument('allow_real', default_value='false'),
        DeclareLaunchArgument('ros_domain_id', default_value='96'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('output_dir', default_value='',
                              description='Absolute private evidence directory, required to execute'),
        DeclareLaunchArgument('params_file', default_value=str(ROOT/'config/fishbot_passage_nav.yaml')),
        DeclareLaunchArgument('geometry_file', default_value=str(ROOT/'config/fishbot_model_geometry.yaml')),
        OpaqueFunction(function=_launch),
    ])


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Render checked Nav2 parameters without starting ROS')
    parser.add_argument('--params-file')
    parser.add_argument('--geometry-file')
    args = parser.parse_args()
    parameters, _geometry = load_parameters(args.params_file, args.geometry_file)
    print(yaml.safe_dump(parameters, sort_keys=False), end='')
