"""Public MuJoCo/AMCL recovery fixture; only isolated domain 99."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import yaml


def compose_navigation_tree(default_source, validity_source, timing_source=None):
    """Reuse the official planning condition while preserving default recoveries."""
    default = ET.fromstring(default_source)
    validity = ET.fromstring(validity_source)
    planners = default.findall('.//RateController/RecoveryNode/ComputePathToPose')
    fallbacks = validity.findall('.//RateController/RecoveryNode/Fallback')
    if len(planners) != 1 or len(fallbacks) != 1:
        raise ValueError('Official behavior tree planning branch is ambiguous')
    fallback = deepcopy(fallbacks[0])
    official_planners = fallback.findall('ComputePathToPose')
    if len(official_planners) != 1 or fallback.find('ReactiveSequence/Inverter/GlobalUpdatedGoal') is None or fallback.find('ReactiveSequence/IsPathValid') is None:
        raise ValueError('Official behavior tree lacks the expected validity condition')
    index = list(fallback).index(official_planners[0])
    fallback.remove(official_planners[0])
    fallback.insert(index, deepcopy(planners[0]))
    parent = default.find('.//RateController/RecoveryNode')
    index = list(parent).index(planners[0])
    parent.remove(planners[0])
    parent.insert(index, fallback)
    if timing_source is not None:
        # Reuse the existing, native-tested error conditions and one-second
        # Wait. Wrap actions, preserving every official non-leaf recovery.
        timing = ET.fromstring(timing_source)
        waits = timing.findall('.//Sequence[@name="WaitForTransientTiming"]/Wait')
        updated = timing.findall('.//ReactiveFallback[@name="TimingRecoveryOrUpdatedGoal"]/GoalUpdated')
        if len(waits) != 1 or waits[0].get('wait_duration') != '1.0' or len(updated) != 1:
            raise ValueError('Existing timing tree lacks its bounded wait/goal-update branch')
        actions = [('ComputePathToPose','compute_path_error_code','202'),
                   ('FollowPath','follow_path_error_code','102;107')]
        for tag,port,codes in actions:
            nodes = default.findall('.//'+tag)
            conditions = timing.findall('.//Sequence[@name="WaitForTransientTiming"]//AreErrorCodesPresent[@error_code="{'+port+'}"]')
            if (len(nodes) != 1 or len(conditions) != 1 or conditions[0].get('error_codes_to_check') != codes
                    or nodes[0].get('error_code_id') != '{'+port+'}'):
                raise ValueError('Official action/timing error ports are missing or ambiguous')
            action = nodes[0]
            owner = next(node for node in default.iter() if action in list(node))
            slot = list(owner).index(action)
            wrapper = ET.Element('RecoveryNode',number_of_retries='5',name='BoundedTiming'+tag)
            attempt = ET.SubElement(wrapper,'Sequence',name='FreshTiming'+tag)
            ET.SubElement(attempt,'Script',code=port+' := 0')
            attempt.append(deepcopy(action))
            recovery = ET.SubElement(wrapper,'ReactiveFallback',name='TimingOrUpdatedGoal'+tag)
            recovery.append(deepcopy(updated[0]))
            wait = ET.SubElement(recovery,'Sequence',name='SharedTimingWait'+tag)
            ET.SubElement(wait,'ScriptCondition',code='localization_tf_waits < 5')
            wait.append(deepcopy(conditions[0]))
            ET.SubElement(wait,'Script',code='localization_tf_waits := localization_tf_waits + 1')
            wait.append(deepcopy(waits[0]))
            owner.remove(action)
            owner.insert(slot,wrapper)
        trees = default.findall('BehaviorTree')
        if len(trees) != 1 or len(trees[0]) != 1:
            raise ValueError('Official main tree root is ambiguous')
        official_root = trees[0][0]
        scope = ET.Element('Sequence',name='LocalizationGoalTimingScope')
        ET.SubElement(scope,'Script',code='localization_tf_waits := 0; compute_path_error_code := 0; follow_path_error_code := 0')
        scope.append(official_root)
        trees[0].remove(official_root)
        trees[0].append(scope)
    return ET.tostring(default, encoding='unicode')


def build_fixture(share, output):
    share, output = Path(share), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    scene_source = share/'mjcf/arena.xml'
    scene = ET.parse(scene_source)
    model = (scene_source.parent/scene.getroot().find('include').get('file')).resolve()
    scene.getroot().find('include').set('file', str(model))
    world = scene.getroot().find('worldbody')
    for body in list(world.findall('body')):
        if body.get('name') == 'moving_obstacle':
            world.remove(body)
    scene_file = output/'scene.xml'
    scene.write(scene_file, encoding='utf-8', xml_declaration=True)
    root = Path(__file__).resolve().parents[1]
    image = output/'arena.pgm'
    subprocess.run(['/usr/bin/python3', str(root/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/scripts/make_fixture_map.py'),
                    str(scene_file), str(image)], check=True, timeout=10)
    map_file = output/'map.yaml'
    map_file.write_text(yaml.safe_dump(dict(image=str(image), resolution=.05, origin=[-4.2,-4.2,0.],
                                          negate=0, occupied_thresh=.65, free_thresh=.25)))
    plugins = yaml.safe_load((share/'config/plugins.yaml').read_text())
    plugin_params = plugins['/**']['ros__parameters']
    plugin_params['body_names'] = ['base_footprint']
    # The public room is 8 m across. Retain measured ray/stamp generation while
    # extending this benchmark's range to include the distinctive room walls.
    plugin_params['mujoco_plugins']['rangefinder_lidar_plugin']['laser']['range_max'] = 12.
    plugins_file = output/'plugins.yaml'
    plugins_file.write_text(yaml.safe_dump(plugins, sort_keys=False))
    params = yaml.safe_load((share/'config/nav2.yaml').read_text())
    params['amcl']['ros__parameters'].update(
        autostart_node=True, set_initial_pose=True,
        **{'initial_pose.x':1.8, 'initial_pose.y':2.4, 'initial_pose.yaw':1.0},
        # Return to the profile that actually recovered twice in run e. The
        # narrower and probability-model trials did not meet the quality gate.
        sigma_hit=.08, max_beams=180, z_hit=.99, z_rand=.01,
        laser_model_type='likelihood_field', do_beamskip=False,
        min_particles=2500, max_particles=10000, pf_err=.01, pf_z=.99,
        update_min_a=.02, update_min_d=.02, resample_interval=1,
        recovery_alpha_fast=0., recovery_alpha_slow=0., laser_max_range=12.)
    params['map_server'] = dict(ros__parameters=dict(use_sim_time=True, yaml_filename=str(map_file), autostart_node=True))
    geometry = yaml.safe_load((root/'tools/config/fishbot_model_geometry.yaml').read_text())
    for name in ('local_costmap', 'global_costmap'):
        costmap = params[name][name]['ros__parameters']
        costmap.pop('robot_radius', None)
        costmap.update(footprint=json.dumps(geometry['footprint']['points_m']),
                       footprint_padding=geometry['footprint']['padding_m'])
    params['global_costmap']['global_costmap']['ros__parameters']['plugins'] = ['static_layer', 'inflation_layer']
    params['local_costmap']['local_costmap']['ros__parameters']['plugins'] = ['voxel_layer', 'inflation_layer']
    params['velocity_smoother']['ros__parameters']['velocity_timeout'] = .2
    profile_source = root/'tools/config/fishbot_passage_nav.yaml'
    controller_profile = yaml.safe_load(profile_source.read_text())['controller_server']['ros__parameters']
    goal_tolerances = {name:controller_profile['general_goal_checker'][name] for name in
                       ('xy_goal_tolerance','yaw_goal_tolerance')}
    params['controller_server']['ros__parameters']['general_goal_checker'].update(goal_tolerances)
    navigation_rates = {name:controller_profile['FollowPath'][name] for name in
                        ('desired_linear_vel','rotate_to_heading_angular_vel')}
    # Retain the base Nav2 acceleration budget. With 20 Hz control, the
    # previous 0.5 budget added only 0.025 rad/s to measured wheel speed.
    angular_accel_source = share/'config/nav2.yaml'
    navigation_rates['max_angular_accel'] = params['controller_server']['ros__parameters']['FollowPath']['max_angular_accel']
    params['controller_server']['ros__parameters']['FollowPath'].update(navigation_rates)
    # Periodic identical plans reset RPP's reached-XY latch in Nav2 1.3.13.
    # Retain the installed official validity checks and recovery actions while
    # permitting a valid final approach to finish its orientation adjustment.
    from ament_index_python.packages import get_package_share_directory
    trees = Path(get_package_share_directory('nav2_bt_navigator'))/'behavior_trees'
    validity_tree = trees/'navigate_w_recovery_and_replanning_only_if_path_becomes_invalid.xml'
    default_tree = trees/'navigate_to_pose_w_replanning_and_recovery.xml'
    if not validity_tree.is_file() or not default_tree.is_file():
        raise FileNotFoundError('Official Nav2 validity-based replanning tree is unavailable')
    behavior_tree = output/'navigation_behavior.xml'
    timing_tree = root/'tools/config/fishbot_passage_tolerant_tree.xml'
    behavior_tree.write_text('<!-- Derived from official Nav2 1.3.13 behavior trees; Apache-2.0. -->\n'+
        compose_navigation_tree(default_tree.read_text(),validity_tree.read_text(),timing_tree.read_text())+'\n')
    params['bt_navigator']['ros__parameters']['default_nav_to_pose_bt_xml'] = str(behavior_tree)
    params['controller_server']['ros__parameters']['FollowPath']['stateful'] = True
    params['controller_server']['ros__parameters']['progress_checker'].update(
        plugin='nav2_controller::PoseProgressChecker',required_movement_radius=.05,
        required_movement_angle=.1,movement_time_allowance=20.)
    params['planner_server']['ros__parameters']['GridBased']['allow_unknown'] = False
    nav_params = output/'nav2.yaml'
    nav_params.write_text(yaml.safe_dump(params, sort_keys=False))
    provenance = dict(domain=99, truth_role='fault injection and independent scoring only',
        map_to_odom_owner='AMCL', original_spawn=[0.,0.,0.], wrong_initial_pose=[1.8,2.4,1.],
        moved_pose=[1.8,2.4,1.], lidar_range_m=12., source_scene=str(scene_source), source_model=str(model),
        source_scene_sha256=hashlib.sha256(scene_source.read_bytes()).hexdigest(),
        source_model_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
        official_nav2_version='1.3.13',
        amcl_likelihood={'laser_model_type':'likelihood_field', 'do_beamskip':False,
                         'sigma_hit':.08, 'z_hit':.99, 'z_rand':.01, 'max_beams':180},
        amcl_tracking_profile={'laser_model_type':'likelihood_field_prob','do_beamskip':False,
                               'sigma_hit':.05,'z_hit':.95,'z_rand':.05},
        amcl_profile_change_services=['/amcl/set_parameters_atomically','/amcl/get_parameters'],
        navigation_rates=navigation_rates, xy_goal_tolerance_m=goal_tolerances['xy_goal_tolerance'],
        yaw_goal_tolerance_rad=goal_tolerances['yaw_goal_tolerance'],
        navigation_goal_checker_source=str(profile_source),
        navigation_goal_checker_source_sha256=hashlib.sha256(profile_source.read_bytes()).hexdigest(),
        navigation_behavior_tree=str(behavior_tree),
        navigation_behavior_tree_sha256=hashlib.sha256(behavior_tree.read_bytes()).hexdigest(),
        navigation_behavior_tree_license='Apache-2.0 (nav2_bt_navigator package.xml)',
        navigation_behavior_tree_sources=[dict(path=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest())
                                           for source in (default_tree,validity_tree,timing_tree)],
        timing_wait_budget=dict(maximum_per_navigation_goal=5,wait_seconds=1.,
                               controller_error_codes=[102,107],planner_error_codes=[202]),
        navigation_rate_source=str(profile_source),
        navigation_rate_source_sha256=hashlib.sha256(profile_source.read_bytes()).hexdigest(),
        navigation_angular_accel_source=str(angular_accel_source),
        navigation_angular_accel_source_sha256=hashlib.sha256(angular_accel_source.read_bytes()).hexdigest(),
        amcl_random_seed='Nav2 AMCL does not expose a fixed seed in this installed version',
        generated_map=str(map_file), generated_scene=str(scene_file), generated_plugins=str(plugins_file),
        generated_navigation_parameters=str(nav_params),
        generated_navigation_sha256=hashlib.sha256(nav_params.read_bytes()).hexdigest(),
        localization_source_sha256={name:hashlib.sha256((root/'tools'/name).read_bytes()).hexdigest()
            for name in ('fishbot_localization_quality.py','fishbot_localization_recovery.py',
                         'fishbot_localization_sim.launch.py')})
    (output/'provenance.json').write_text(json.dumps(provenance, indent=2)+'\n')
    return scene_file, map_file, plugins_file, nav_params


def setup(context):
    from ament_index_python.packages import get_package_share_directory
    from launch.actions import GroupAction, IncludeLaunchDescription, LogInfo, RegisterEventHandler, SetEnvironmentVariable
    from launch.event_handlers import OnProcessExit
    from launch.launch_description_sources import PythonLaunchDescriptionSource
    from launch.substitutions import LaunchConfiguration
    from launch_ros.actions import Node, SetRemap
    if LaunchConfiguration('ros_domain_id').perform(context) != '99':
        raise RuntimeError('Localization recovery accepts only isolated domain 99')
    output = Path(LaunchConfiguration('output_dir').perform(context)).expanduser().resolve()
    root = Path(__file__).resolve().parents[1]
    if output.is_relative_to(root):
        raise ValueError('Runtime localization evidence must remain outside the repository')
    share = Path(get_package_share_directory('fishbot_mujoco'))
    scene, _map, plugins, params = build_fixture(share, output)
    sensors = Node(package='fishbot_mujoco', executable='wait_ready.py', name='localization_sensor_readiness',
                   arguments=['--nav','false','--timeout','45'], output='screen')
    def after_sensors(event, launch_context):
        if launch_context.is_shutdown:
            return []
        if event.returncode != 0:
            raise RuntimeError('Localization sensors are not ready; navigation was not started')
        return [LogInfo(msg='Localization sensors ready; AMCL exclusively owns map -> odom.'),
            # Official LifecycleNode autostart avoids a second localization
            # lifecycle owner; the runner still verifies both nodes ACTIVE.
            Node(package='nav2_map_server', executable='map_server', name='map_server',
                 parameters=[str(params),{'use_sim_time':True}], output='screen'),
            Node(package='nav2_amcl', executable='amcl', name='amcl',
                 parameters=[str(params),{'use_sim_time':True}], output='screen'),
            GroupAction(actions=[SetRemap(src='docking_server:cmd_vel',dst='/cmd_vel_nav'),
                IncludeLaunchDescription(PythonLaunchDescriptionSource(str(Path(get_package_share_directory('nav2_bringup'))/'launch/navigation_launch.py')),
                    launch_arguments={'params_file':str(params),'use_sim_time':'True','autostart':'True',
                                      'use_composition':'False'}.items())])]
    return [SetEnvironmentVariable('ROS_DOMAIN_ID','99'), SetEnvironmentVariable('FISHBOT_MUJOCO_DOMAIN_ID','99'),
        SetEnvironmentVariable('ROS_AUTOMATIC_DISCOVERY_RANGE','LOCALHOST'), SetEnvironmentVariable('ROS_LOCALHOST_ONLY','1'),
        SetEnvironmentVariable('ROS_STATIC_PEERS',''),
        GroupAction(actions=[IncludeLaunchDescription(PythonLaunchDescriptionSource(str(share/'launch/sim.launch.py')),
            launch_arguments={'ros_domain_id':'99','scene_path':str(scene),'plugins_file':str(plugins),
                              'nav':'false','obstacle':'false','bridge':'false','rviz':'false','headless':'true'}.items())]),
        RegisterEventHandler(OnProcessExit(target_action=sensors,on_exit=after_sensors)), sensors]


def generate_launch_description():
    from launch import LaunchDescription
    from launch.actions import DeclareLaunchArgument, OpaqueFunction
    return LaunchDescription([DeclareLaunchArgument('ros_domain_id', default_value='99'),
                              DeclareLaunchArgument('output_dir'), OpaqueFunction(function=setup)])
