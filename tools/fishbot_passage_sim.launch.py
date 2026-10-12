"""Synthetic passage acceptance, isolated from real domain zero and baseline 93."""
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import yaml


def fixture_options(domain, door_width_m=.36, initial_yaw_rad=0., scan_gap_s=0.,
                    scan_trigger_distance_m=.15, timing_profile='strict'):
    if not str(domain).isdigit() or not 1 <= int(domain) <= 232 or int(domain) == 93:
        raise ValueError('Passage acceptance requires an isolated nonzero domain other than baseline 93')
    values = {}
    for name, value, low, high in (
            ('door_width_m', door_width_m, .30, .52),
            ('initial_yaw_rad', initial_yaw_rad, -.35, .35),
            ('scan_gap_s', scan_gap_s, 0., 1.),
            ('scan_trigger_distance_m', scan_trigger_distance_m, .05, .35)):
        number = float(value)
        if isinstance(value, bool) or not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f'{name} outside supported bounds [{low}, {high}]')
        values[name] = number
    if 0 < values['scan_gap_s'] < .2:
        raise ValueError('scan_gap_s must be zero or 0.2..1 seconds')
    if values['scan_gap_s'] and int(domain) not in (96, 102):
        raise ValueError('Scan fault injection requires isolated domain 96 or 102')
    if timing_profile not in ('strict', 'tolerant'):
        raise ValueError('timing_profile must be strict or tolerant')
    return dict(domain=int(domain), timing_profile=timing_profile, **values)


def build_fixture(source_scene, source_plugins, directory, options):
    """Copy the public fixture; change only doorway geometry and initial yaw."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    source_scene = Path(source_scene).resolve()
    scene = ET.parse(source_scene)
    include = scene.getroot().find('include')
    source_model = (source_scene.parent / include.get('file')).resolve()
    model = ET.parse(source_model)
    base = model.getroot().find("worldbody/body[@name='base_footprint']")
    yaw = options['initial_yaw_rad']
    base.set('quat', f'{math.cos(yaw/2):.17g} 0 0 {math.sin(yaw/2):.17g}')
    model_path = directory / 'fishbot.xml'
    model.write(model_path, encoding='utf-8', xml_declaration=True)
    include.set('file', str(model_path.resolve()))
    half_gap = options['door_width_m']/2
    for name, sign in (('door_left', 1), ('door_right', -1)):
        door = scene.getroot().find(f"worldbody/geom[@name='{name}']")
        door.set('pos', f'.65 {sign*(1+half_gap)/2:.17g} .3')
        door.set('size', f'.10 {(1-half_gap)/2:.17g} .3')
    scene_path = directory / 'passage.xml'
    scene.write(scene_path, encoding='utf-8', xml_declaration=True)
    plugins = yaml.safe_load(Path(source_plugins).read_text())
    scan_input = '/scan_raw' if options['scan_gap_s'] else '/scan'
    laser = plugins['/**']['ros__parameters']['mujoco_plugins']['rangefinder_lidar_plugin']['laser']
    laser['laserscan_topic'] = scan_input
    plugins_path = directory / 'plugins.yaml'
    plugins_path.write_text(yaml.safe_dump(plugins, sort_keys=False))
    geometry = copy.deepcopy(yaml.safe_load((Path(__file__).parent / 'config/fishbot_model_geometry.yaml').read_text()))
    geometry['frames']['scan'] = laser['frame_name']
    geometry_path = directory / 'geometry.yaml'
    geometry_path.write_text(yaml.safe_dump(geometry, sort_keys=False))
    map_path = synthetic_map(scene_path, directory)
    provenance = dict(schema_version=1, **options, map_to_odom=[0., 0., yaw],
        scan_input=scan_input, scan_output='/scan',
        source_scene={'path': str(source_scene), 'sha256': hashlib.sha256(source_scene.read_bytes()).hexdigest()},
        source_model={'path': str(source_model), 'sha256': hashlib.sha256(source_model.read_bytes()).hexdigest()},
        generated_scene=str(scene_path), generated_model=str(model_path), generated_map=map_path,
        generated_geometry=str(geometry_path), generated_plugins=str(plugins_path))
    (directory / 'provenance.json').write_text(json.dumps(provenance, indent=2)+'\n')
    return provenance


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
    from ament_index_python.packages import get_package_share_directory
    from launch.actions import ExecuteProcess, GroupAction, IncludeLaunchDescription, LogInfo, RegisterEventHandler, SetEnvironmentVariable
    from launch.event_handlers import OnProcessExit
    from launch.launch_description_sources import PythonLaunchDescriptionSource
    from launch.substitutions import LaunchConfiguration
    from launch_ros.actions import Node

    def arg(name):
        return LaunchConfiguration(name).perform(context)
    domain = LaunchConfiguration('ros_domain_id').perform(context)
    options = fixture_options(domain, *(arg(name) for name in (
        'door_width_m', 'initial_yaw_rad', 'scan_gap_s', 'scan_trigger_distance_m', 'timing_profile')))
    localization = arg('localization')
    if localization not in ('static', 'amcl'):
        raise ValueError('localization must be static or amcl')
    root = Path(__file__).resolve().parent
    share = Path(get_package_share_directory('fishbot_mujoco'))
    # Reuse the owning passage stack's output/privacy boundary before writing fixtures.
    specification = importlib.util.spec_from_file_location('passage_output_validation', root / 'fishbot_passage.launch.py')
    passage = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(passage)
    output = passage.validate_execution_request(int(domain), True, False, True, arg('output_dir'))
    output.mkdir(parents=True, exist_ok=True)
    fixture = build_fixture(share / 'mjcf/passage.xml', share / 'config/plugins.yaml',
                            output / 'fixture', options)
    navigation_params = str(root/'config/fishbot_passage_nav.yaml')
    if localization == 'amcl':
        params = yaml.safe_load(Path(navigation_params).read_text())
        amcl = yaml.safe_load((share/'config/nav2.yaml').read_text())['amcl']['ros__parameters']
        amcl.update(use_sim_time=True, autostart_node=True, sigma_hit=.05, max_beams=180,
                    z_hit=.95, z_rand=.05, update_min_a=.02, update_min_d=.02,
                    initial_pose={'x':0., 'y':0., 'z':0., 'yaw':options['initial_yaw_rad']})
        params['amcl'] = {'ros__parameters':amcl}
        params['global_costmap']['global_costmap']['ros__parameters']['plugins'] = ['static_layer','inflation_layer']
        navigation_params = str(output/'fixture/amcl-navigation.yaml')
        Path(navigation_params).write_text(yaml.safe_dump(params, sort_keys=False))
        fixture.update(map_to_odom_owner='AMCL', navigation_parameters=navigation_params)
    else:
        fixture['map_to_odom_owner'] = 'static fixture transform'
    (output/'fixture/provenance.json').write_text(json.dumps(fixture, indent=2)+'\n')
    localization_node = (Node(package='nav2_amcl', executable='amcl', name='amcl',
                             parameters=[navigation_params], output='screen') if localization == 'amcl' else
        Node(package='tf2_ros', executable='static_transform_publisher', name='fixture_map_to_odom',
             arguments=['--frame-id','map','--child-frame-id','odom', '--yaw', str(options['initial_yaw_rad'])],
             parameters=[{'use_sim_time':True}]))
    navigation = [
        Node(package='nav2_map_server', executable='map_server', name='map_server',
             parameters=[{'use_sim_time':True,'yaml_filename':fixture['generated_map'],
                          'autostart_node':True}], output='screen'),
        localization_node,
        IncludeLaunchDescription(PythonLaunchDescriptionSource(str(root / 'fishbot_passage.launch.py')),
                                 launch_arguments={'execute':'true','ros_domain_id':domain,'allow_real':'false',
                                                   'use_sim_time':'true','output_dir':str(output / 'triggers'),
                                                   'geometry_file':fixture['generated_geometry'],
                                                   'params_file':navigation_params,
                                                   'timing_profile':options['timing_profile']}.items()),
    ]
    sensors_ready = Node(package='fishbot_mujoco', executable='wait_ready.py',
        name='passage_sensor_readiness', arguments=['--nav','false','--timeout','45'], output='screen')
    def after_sensors(event, launch_context):
        if launch_context.is_shutdown:
            return []
        if event.returncode != 0:
            raise RuntimeError('Passage sensors did not become ready; navigation was not started')
        return [LogInfo(msg='Passage sensors ready; starting map and navigation.'), *navigation]
    actions = [
        SetEnvironmentVariable('ROS_DOMAIN_ID', domain),
        SetEnvironmentVariable('FISHBOT_MUJOCO_DOMAIN_ID', domain),
        SetEnvironmentVariable('ROS_AUTOMATIC_DISCOVERY_RANGE', 'LOCALHOST'),
        SetEnvironmentVariable('ROS_LOCALHOST_ONLY', '1'),
        SetEnvironmentVariable('ROS_STATIC_PEERS', ''),
        # Isolate sim's params_file/use_sim_time declarations from the passage
        # stack; otherwise ROS launch silently reuses the baseline Nav2 YAML.
        GroupAction(actions=[IncludeLaunchDescription(PythonLaunchDescriptionSource(str(share / 'launch/sim.launch.py')),
                                 launch_arguments={'ros_domain_id': domain, 'scene_path':fixture['generated_scene'],
                                                   'plugins_file':fixture['generated_plugins'],
                                                   'nav':'false','headless':'true','rviz':'false','bridge':'false'}.items())]),
        RegisterEventHandler(OnProcessExit(target_action=sensors_ready, on_exit=after_sensors)),
        sensors_ready,
    ]
    if options['scan_gap_s']:
        relay = ExecuteProcess(cmd=['/usr/bin/python3', str(root / 'fishbot_sim_scan_relay.py'),
            '--gap-seconds', str(options['scan_gap_s']),
            '--trigger-distance', str(options['scan_trigger_distance_m']),
            '--output', str(output / 'scan-relay.jsonl'), '--execute',
            '--ros-args', '-p', 'use_sim_time:=true'], name='fishbot_sim_scan_relay', output='screen')
        def relay_exited(event, launch_context):
            if not launch_context.is_shutdown:
                raise RuntimeError('Scan relay exited unexpectedly with code '+str(event.returncode))
            return []
        actions.extend([RegisterEventHandler(OnProcessExit(target_action=relay, on_exit=relay_exited)), relay])
    return actions


def generate_launch_description():
    from launch import LaunchDescription
    from launch.actions import DeclareLaunchArgument, OpaqueFunction
    return LaunchDescription([
        DeclareLaunchArgument('ros_domain_id', default_value='96'),
        DeclareLaunchArgument('output_dir'),
        DeclareLaunchArgument('door_width_m', default_value='.36'),
        DeclareLaunchArgument('initial_yaw_rad', default_value='0'),
        DeclareLaunchArgument('localization', default_value='static'),
        DeclareLaunchArgument('timing_profile', default_value='strict'),
        DeclareLaunchArgument('scan_gap_s', default_value='0'),
        DeclareLaunchArgument('scan_trigger_distance_m', default_value='.15'),
        OpaqueFunction(function=setup),
    ])
