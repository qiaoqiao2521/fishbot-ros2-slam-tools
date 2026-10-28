#!/usr/bin/env python3
"""Prepare separate laser localization and full-height collision maps."""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from cooperation_perception import normalize_config


NATIVE_DOCKING_TARGET_PROJECTION_M=.25
NATIVE_DOCKING_PRIMARY_SOURCES=[
    {'url':'https://raw.githubusercontent.com/ros-navigation/navigation2/1.3.13/nav2_docking/opennav_docking/src/docking_server.cpp',
     'sha256':'9401e8fec77668e4d4ed3fd44707d4a423b350d45422ad59700b807279ef81ac'},
    {'url':'https://raw.githubusercontent.com/ros-navigation/navigation2/1.3.13/nav2_docking/opennav_docking/src/controller.cpp',
     'sha256':'8ff965a3dfd3ead0e576bab4b1d71a26cf494c36fbd8e9aea5fa7e7988d4e8bc'},
    {'url':'https://raw.githubusercontent.com/ros-navigation/navigation2/1.3.13/nav2_docking/opennav_docking/src/simple_non_charging_dock.cpp',
     'sha256':'c7c9bb09dbd421df9a7f879245dad73fc45388d006f0e41855a73436f72d49f6'}]


def require_native_docking_version(version=None):
    """Fail closed when the installed native target/threshold semantics change."""
    if version is None:
        package=Path('/opt/ros/jazzy/share/opennav_docking/package.xml')
        version=ET.parse(package).getroot().findtext('version')
    if version!='1.3.13':
        raise RuntimeError(f'Native docking {version} is unverified; revalidate target projection and collision semantics before use')
    return version


def navigation_behavior(project, output):
    """Reuse the project's native validity condition and default recoveries."""
    helper=project/'tools/fishbot_localization_sim.launch.py'
    trees=Path('/opt/ros/jazzy/share/nav2_bt_navigator/behavior_trees')
    default=trees/'navigate_to_pose_w_replanning_and_recovery.xml'
    validity=trees/'navigate_w_recovery_and_replanning_only_if_path_becomes_invalid.xml'
    for source in (helper,default,validity):
        if not source.is_file():
            raise FileNotFoundError(f'Native navigation behavior source is unavailable: {source}')
    spec=importlib.util.spec_from_file_location('cooperation_native_behavior_reuse',helper)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    xml=module.compose_navigation_tree(default.read_text(),validity.read_text())
    path=output/'cooperation-navigation.xml'
    path.write_text('<!-- Derived from official Nav2 1.3.13 behavior trees; Apache-2.0. -->\n'+xml+'\n')
    path.chmod(0o600)
    return path,[{'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
                 for source in (helper,default,validity)]


def staging_navigation(params, behavior_path, output, *, transport_planner=None,
                       transport_reversing=False, transport_in_place_rotation=False,
                       transport_rotation_shim=False, staging_reversing=False):
    """Isolate transit XY latches using existing native plugins and trees."""
    controller = params['controller_server']['ros__parameters']
    controller['StagingPath'] = copy.deepcopy(controller['FollowPath'])
    controller['StagingPath']['stateful'] = True
    controller['staging_goal_checker'] = copy.deepcopy(controller['general_goal_checker'])
    controller['staging_goal_checker']['stateful'] = True
    if transport_reversing:
        # Native RPP rejects reversing together with rotate-to-heading.
        # Preserve forward/rotate staging; only the loaded path follows cusps.
        controller['StagingPath'].update(allow_reversing=False, use_rotate_to_heading=True)
        controller['FollowPath'].update(allow_reversing=True, use_rotate_to_heading=False)
    elif transport_in_place_rotation:
        # Forward differential primitives include zero-translation turns.
        # Preserve those poses and let the existing native RPP rotate first.
        for name in ('StagingPath', 'FollowPath'):
            controller[name].update(allow_reversing=False, use_rotate_to_heading=True)
    if staging_reversing:
        controller['StagingPath'].update(allow_reversing=True, use_rotate_to_heading=False)
    shim_controllers = (['FollowPath'] if transport_rotation_shim else [])
    if staging_reversing:
        shim_controllers.append('StagingPath')
    for name in shim_controllers:
        follow = controller[name]
        angle = follow.get('rotate_to_heading_min_angle', .785)
        follow.update(primary_controller=follow.get('primary_controller', follow['plugin']),
            plugin='nav2_rotation_shim_controller::RotationShimController',
            angular_dist_threshold=angle, angular_disengage_threshold=angle/2.,
            forward_sampling_distance=params['global_costmap']['global_costmap']['ros__parameters']['resolution'],
            use_path_orientations=True, rotate_to_goal_heading=True,
            rotate_to_heading_once=False, closed_loop=True)
    for field, name in (('controller_plugins','StagingPath'),
                        ('goal_checker_plugins','staging_goal_checker')):
        if name not in controller[field]:
            controller[field].append(name)
    main = ET.fromstring(Path(behavior_path).read_text())
    for follow in main.iter('FollowPath'):
        follow.set('goal_checker_id','general_goal_checker')
    staging = copy.deepcopy(main)
    if transport_planner is not None:
        for compute in main.iter('ComputePathToPose'):
            compute.set('planner_id',transport_planner)
        for compute in staging.iter('ComputePathToPose'):
            compute.set('planner_id','GridBased')
    for selector in staging.iter('ControllerSelector'):
        selector.set('default_controller','StagingPath')
    for follow in staging.iter('FollowPath'):
        follow.set('controller_id','StagingPath')
        follow.set('goal_checker_id','staging_goal_checker')
    stage_path = Path(output)/'cooperation-staging-navigation.xml'
    for path, tree in ((Path(behavior_path),main),(stage_path,staging)):
        path.write_text('<!-- Derived from official Nav2 1.3.13 behavior trees; Apache-2.0. -->\n'+
                        ET.tostring(tree,encoding='unicode')+'\n')
        path.chmod(0o600)
    return stage_path


def navigation_planner(params, profile='navfn', *, minimum_turning_radius=.20,
                       lattice_filepath=None, lattice_allow_reversing=False,
                       lattice_rotation_shim=False):
    """Select installed native planning; leave control and scoring unchanged."""
    planner = params['planner_server']['ros__parameters']
    lattice_info = {}
    if profile in ('smac-hybrid', 'smac-reeds-shepp'):
        if not math.isfinite(minimum_turning_radius) or minimum_turning_radius <= 0:
            raise ValueError('planner minimum turning radius must be finite and positive')
        # Nav2 1.3.13 SmacPlannerHybrid, Apache-2.0. Match the native RPP
        # direction contract; neither profile accepts an approximate goal.
        previous = planner['GridBased']
        planner['HeadingAware'] = {
            'plugin': 'nav2_smac_planner::SmacPlannerHybrid',
            'tolerance': 0., 'allow_unknown': previous.get('allow_unknown', True),
            'motion_model_for_search': ('REEDS_SHEPP' if profile == 'smac-reeds-shepp' else 'DUBIN'),
            'minimum_turning_radius': minimum_turning_radius,
            'angle_quantization_bins': 72, 'lookup_table_size': 5.,
            'smooth_path': True,
        }
        if 'HeadingAware' not in planner['planner_plugins']:
            planner['planner_plugins'].append('HeadingAware')
    elif profile == 'smac-lattice':
        from cooperation_lattice import lattice_parameters
        settings, lattice_info = lattice_parameters(params, lattice_filepath,
            allow_reversing=lattice_allow_reversing)
        planner['HeadingAware'] = settings
        if 'HeadingAware' not in planner['planner_plugins']:
            planner['planner_plugins'].append('HeadingAware')
    elif profile != 'navfn':
        raise ValueError('unknown native planner profile: '+str(profile))
    chosen='HeadingAware' if profile in ('smac-hybrid','smac-reeds-shepp','smac-lattice') else 'GridBased'
    return {'profile': profile, 'plugin': planner[chosen]['plugin'],
            'minimum_turning_radius_m': planner[chosen].get('minimum_turning_radius'),
            'transport_planner': chosen if chosen=='HeadingAware' else None,
            'transport_reversing': profile=='smac-reeds-shepp' or (profile=='smac-lattice' and lattice_allow_reversing),
            'transport_in_place_rotation': profile=='smac-lattice' and not lattice_allow_reversing,
            'transport_rotation_shim': profile=='smac-lattice' and lattice_rotation_shim,
            'staging_planner': 'GridBased',
            'role': 'global path generation; not controller or physical acceptance',
            **lattice_info}


def amcl_motion_model(params, profile='source'):
    """Use native lateral odometry at a foot origin displaced from the axle."""
    amcl=params['amcl']['ros__parameters']
    if profile=='omni':
        amcl['robot_model_type']='nav2_amcl::OmniMotionModel'
    elif profile!='source':
        raise ValueError('unknown AMCL motion profile: '+str(profile))
    return {'profile':profile,'plugin':amcl['robot_model_type'],
            'base_reference':amcl['base_frame_id'],
            'physical_kinematics_changed':False,'truth_input':False}


def laser_slice(vertices, height):
    """Intersect a box or MuJoCo convex collision mesh with the scan plane."""
    import numpy as np
    from scipy.spatial import ConvexHull
    if not vertices[:, 2].min() <= height <= vertices[:, 2].max():
        return None
    hull = ConvexHull(vertices)
    edges = {tuple(sorted((int(a), int(b)))) for face in hull.simplices
             for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0]))}
    points = []
    for a, b in edges:
        start, end = vertices[a], vertices[b]
        if min(start[2], end[2]) <= height <= max(start[2], end[2]):
            if abs(end[2] - start[2]) > 1e-12:
                points.append((start + (height-start[2])/(end[2]-start[2])*(end-start))[:2])
            else:
                points.extend((start[:2], end[:2]))
    points = np.unique(np.asarray(points), axis=0)
    if len(points) < 3:
        return None
    return points[ConvexHull(points).vertices]


def rasterize_slices(slices, resolution, size, origin):
    import numpy as np
    from scipy.spatial import ConvexHull
    occupied = np.zeros((size, size), dtype=bool)
    coordinates = origin + (np.arange(size)+.5)*resolution
    for section in slices:
        polygon = np.asarray(section['polygon'])
        x_indices = np.flatnonzero((coordinates >= polygon[:, 0].min()) &
                                  (coordinates <= polygon[:, 0].max()))
        y_indices = np.flatnonzero((coordinates >= polygon[:, 1].min()) &
                                  (coordinates <= polygon[:, 1].max()))
        xx, yy = np.meshgrid(coordinates[x_indices], coordinates[y_indices])
        points = np.column_stack((xx.ravel(), yy.ravel()))
        equations = ConvexHull(polygon).equations
        mask = np.all(points @ equations[:, :2].T + equations[:, 2] <= 1e-12, axis=1)
        occupied[np.ix_(y_indices, x_indices)] |= mask.reshape(len(y_indices), len(x_indices))
    return np.where(occupied[::-1], 0, 254).astype(np.uint8).tobytes()


def write_map(output, stem, pixels, resolution, size, origin):
    import yaml
    pgm = output / (stem+'.pgm')
    pgm.write_bytes(f'P5\n{size} {size}\n255\n'.encode()+pixels)
    path = output / (stem+'-map.yaml')
    path.write_text(yaml.safe_dump({'image': str(pgm), 'mode': 'trinary',
        'resolution': resolution, 'origin': [origin, origin, 0.],
        'negate': 0, 'occupied_thresh': .65, 'free_thresh': .25}))
    return path, hashlib.sha256(pgm.read_bytes()).hexdigest()


def composition_navigation(params, manifest, output):
    """Bind existing native navigation components to the selected assets."""
    import yaml
    profile = manifest.get('scene_profile', {})
    vehicle = manifest.get('vehicle_profile', {})
    if profile or vehicle:
        # A heading correction may move a skid-steer chassis after XY first
        # entered tolerance. Require both coordinates at the final heading.
        params['controller_server']['ros__parameters']['general_goal_checker']['stateful'] = False
        params['controller_server']['ros__parameters']['FollowPath']['stateful'] = False
    if vehicle.get('id') == 'jackal_j100':
        source = Path(__file__).with_name('config')/'base_profiles/j100_ekf.yaml'
        ekf = yaml.safe_load(source.read_text())
        ekf['ekf_filter_node']['ros__parameters']['imu0'] = '/imu'
        ekf_path = Path(output)/'cooperation-ekf.yaml'
        ekf_path.write_text(yaml.safe_dump(ekf, sort_keys=False))
        manifest['localization'] = {'enabled': True, 'ekf_yaml': str(ekf_path),
            'wheel_odom_topic': '/wheel/odom', 'imu_topic': '/imu',
            'implementation': 'robot_localization/ekf_node',
            'absolute_yaw_or_truth_input': False}
    if vehicle.get('id') in ('jackal_j100', 'robot_base_mecanum'):
        radius = max(math.hypot(*point) for point in manifest['car_footprint_xy'])
        for name in ('global_costmap','local_costmap'):
            config = params[name][name]['ros__parameters']
            config['robot_radius'] = radius
            config['inflation_layer']['inflation_radius'] = radius + .17
        follow = params['controller_server']['ros__parameters']['FollowPath']
        navigation = vehicle.get('navigation', {})
        follow['max_angular_accel'] = navigation.get('max_angular_accel', 10.)
        if 'rotate_to_heading_angular_vel' in navigation:
            follow['rotate_to_heading_angular_vel'] = navigation['rotate_to_heading_angular_vel']
        if navigation.get('stopped_goal_checker'):
            params['controller_server']['ros__parameters']['general_goal_checker'].update(
                plugin='nav2_controller::StoppedGoalChecker',
                trans_stopped_velocity=.01, rot_stopped_velocity=.01)
        params['controller_server']['ros__parameters']['progress_checker']['required_movement_angle'] = .2
    if profile.get('sensors') == 'lidar3d':
        from cooperation_lidar import configuration as lidar_configuration
        from fishbot_lidar3d import configure_costmaps
        sensor = lidar_configuration(manifest)
        ceiling = manifest['transport_height_envelope']['max_obstacle_height_m']
        configure_costmaps(params, sensor['topic'], sensor['max_range_m'])
        for name in ('global_costmap','local_costmap'):
            config = params[name][name]['ros__parameters']
            key = 'voxel_layer' if 'voxel_layer' in config['plugins'] else 'lidar3d_voxel_layer'
            config[key]['lidar3d'].update(max_obstacle_height=ceiling,
                obstacle_min_range=sensor['min_range_m'], raytrace_min_range=sensor['min_range_m'])
        monitor = params['collision_monitor']['ros__parameters']
        if 'lidar3d' not in monitor['observation_sources']:
            monitor['observation_sources'].append('lidar3d')
        monitor['lidar3d'] = {'type':'pointcloud','topic':sensor['topic'],
            'min_height':.025,'max_height':ceiling,'min_range':sensor['min_range_m'],'enabled':True}
        manifest['lidar3d_navigation'] = {'topic':sensor['topic'],
            'min_range_m':sensor['min_range_m'], 'max_range_m':sensor['max_range_m'],
            'costmaps':['global_costmap','local_costmap'], 'collision_monitor':True,
            'localization_source':'/scan', 'implementation':'shared native mj_multiRay adapter',
            'height_envelope':manifest['transport_height_envelope']}


def prepare(args):
    perception_path = getattr(args, 'perception_config', None)
    perception_input = json.loads(Path(perception_path).read_text()) if perception_path else None
    station_perception = normalize_config(perception_input)
    fault_path = getattr(args, 'observation_faults', None)
    observation_faults = None
    if fault_path:
        from cooperation_faults import normalize_fault_config
        observation_faults = normalize_fault_config(json.loads(Path(fault_path).read_text()))
    if station_perception['station_id'] != 'so101_station':
        raise ValueError('station perception identity must match the native so101_station dock')
    docking_version=require_native_docking_version()
    import mujoco
    import numpy as np
    import yaml
    from cooperation_scene import build_scene
    profile_path = getattr(args, 'scene_profile', None)
    scene_profile = json.loads(Path(profile_path).read_text()) if profile_path else None
    business_path = getattr(args, 'continuous_delivery', None)
    business = json.loads(Path(business_path).read_text()) if business_path else None
    spawn=getattr(args,'spawn',(0.,-2.))
    spawn_yaw=getattr(args,'spawn_yaw',0.)
    manifest=build_scene(args.so101_project,args.fishbot_project,args.output,
                         spawn=spawn,spawn_yaw=spawn_yaw,camera=station_perception['mode']=='vision',
                         camera_light_scale=getattr(args,'camera_light_scale',1.),
                         tag_lateral_offset=getattr(args,'tag_lateral_offset',.03),
                         scene_profile=scene_profile,
                         omit_unused_native_rangefinders=getattr(args,'omit_unused_native_rangefinders',False),
                         continuous_delivery=business,
                         arena_xml=getattr(args, 'arena_xml', None))
    if getattr(args,'queued_ros_dispatch',False):
        manifest['queued_ros_dispatch']=True
    if getattr(args,'terminal_stop_heartbeat',False):
        manifest['terminal_stop_heartbeat']=True
    factory_path = getattr(args, 'factory_config', None)
    if factory_path:
        from cooperation_factory_scene import apply_factory_scene
        apply_factory_scene(manifest, json.loads(Path(factory_path).read_text()))
    model=mujoco.MjModel.from_xml_path(manifest['world_xml'])
    data=mujoco.MjData(model);mujoco.mj_forward(model,data)
    rectangles=[];slices=[]
    # base_footprint is the ground frame. Ignore the temporary 2 mm spawn lift.
    laser_height=float((data.xpos[model.body('laser_link').id] -
                        data.xpos[model.body('base_footprint').id])[2])
    # Static world geometry and the fixed arm base are map obstacles. The arm's
    # moving links, the car and the free cargo remain real sensor obstacles.
    for geom in range(model.ngeom):
        if not model.geom_contype[geom]:continue
        body=int(model.geom_bodyid[geom]);ancestor=body;moving=False
        while ancestor:
            moving=moving or model.body_dofnum[ancestor]>0
            ancestor=int(model.body_parentid[ancestor])
        if moving or model.geom_type[geom]==mujoco.mjtGeom.mjGEOM_PLANE:continue
        center=data.geom_xpos[geom];rotation=data.geom_xmat[geom].reshape(3,3)
        if model.geom_type[geom]==mujoco.mjtGeom.mjGEOM_BOX:
            extent=np.abs(rotation) @ model.geom_size[geom]
            corners=np.array([[x,y,z] for x in (-1,1) for y in (-1,1) for z in (-1,1)])
            vertices=(corners*model.geom_size[geom]) @ rotation.T + center
        elif model.geom_type[geom]==mujoco.mjtGeom.mjGEOM_MESH:
            mesh=int(model.geom_dataid[geom]);start=int(model.mesh_vertadr[mesh]);count=int(model.mesh_vertnum[mesh])
            vertices=model.mesh_vert[start:start+count] @ rotation.T + center
            lo,hi=vertices.min(axis=0),vertices.max(axis=0);center=(lo+hi)/2;extent=(hi-lo)/2
        else:
            raise RuntimeError(f"Unsupported static map geometry: {model.geom(geom).name}")
        if center[2]+extent[2]<0:continue
        rectangles.append({'name':model.geom(geom).name,'center':center.tolist(),'extent':extent.tolist()})
        polygon=laser_slice(vertices,laser_height)
        if polygon is not None:
            slices.append({'name':model.geom(geom).name,'polygon':polygon.tolist()})
    resolution=.02;size=420;origin=-4.2
    pixels=bytearray()
    for row in range(size):
        y=origin+(size-1-row+.5)*resolution
        for col in range(size):
            x=origin+(col+.5)*resolution
            pixels.append(0 if any(abs(x-r['center'][0])<=r['extent'][0] and abs(y-r['center'][1])<=r['extent'][1] for r in rectangles) else 254)
    collision_path,collision_hash=write_map(args.output,'cooperation',pixels,resolution,size,origin)
    localization_path,localization_hash=write_map(args.output,'cooperation-localization',
        rasterize_slices(slices,resolution,size,origin),resolution,size,origin)
    source=args.fishbot_project/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/config/nav2.yaml'
    params=yaml.safe_load(source.read_text())
    params['amcl']['ros__parameters']['initial_pose'].update(x=manifest['spawn'][0],y=manifest['spawn'][1],yaw=spawn_yaw)
    # The shared ideal lidar and 2 cm map need workcell localization precision.
    # Native probability accumulation penalizes jointly inconsistent endpoints;
    # the original navigation model's sum of cubed scores was almost indifferent
    # to a measured 10 cm error. Keep motion noise and collision checks intact.
    localization_parameters={'laser_model_type':'likelihood_field_prob','sigma_hit':.05,
        'max_beams':180,'z_hit':.95,'z_rand':.05,'update_min_d':.01,
        'update_min_a':.01,'do_beamskip':False}
    params['amcl']['ros__parameters'].update(localization_parameters)
    motion_choice = getattr(args,'amcl_motion_model','source')
    if manifest.get('vehicle_profile', {}).get('id') == 'robot_base_mecanum' and motion_choice == 'source':
        motion_choice = 'omni'
    motion_profile=amcl_motion_model(params,motion_choice)
    controller=params['controller_server']['ros__parameters']
    # Reuse the installed Nav2 checker also used by the passage profile. A
    # short transit after cancellation can require turning before translating;
    # keep the source distance and timeout while counting angular progress.
    controller['progress_checker'].update(plugin='nav2_controller::PoseProgressChecker',
                                          required_movement_angle=.1)
    controller['general_goal_checker']['xy_goal_tolerance']=.015
    controller['general_goal_checker']['yaw_goal_tolerance']=.035
    controller['FollowPath']['desired_linear_vel']=.12
    # Keep a valid final approach while RPP completes its orientation. Periodic
    # setPlan calls clear RPP's reached-XY state in the installed Nav2 version.
    behavior_path,behavior_sources=navigation_behavior(args.fishbot_project,args.output)
    params['bt_navigator']['ros__parameters']['default_nav_to_pose_bt_xml']=str(behavior_path)
    footprint=manifest['car_footprint_xy']
    if (manifest['car_footprint_frame']!='base_footprint' or len(footprint)<3 or
        any(len(point)!=2 or not all(math.isfinite(value) for value in point) for point in footprint)):
        raise RuntimeError('共同场景必须提供 base_footprint 帧完整非空车体与托盘足迹')
    footprint_json=json.dumps(footprint,separators=(',',':'),allow_nan=False)
    for name in ['global_costmap','local_costmap']:
        params[name][name]['ros__parameters']['resolution']=resolution
        params[name][name]['ros__parameters']['footprint']=footprint_json
        params[name][name]['ros__parameters']['static_layer']['map_topic']='/cooperation_collision_map'
    # Nav2 handles transit. Native DockRobot handles the final relative approach.
    # Jazzy 1.3.13 projects past the dock along its dock-frame yaw, then flips the
    # target orientation when dock_backwards is true. The dock frame therefore
    # faces opposite the desired final ROBOT heading for this east-side approach.
    robot_dock=[float(value) for value in manifest['dock_pose']]
    native_dock=[robot_dock[0],robot_dock[1],
                 math.atan2(math.sin(robot_dock[2]+math.pi),math.cos(robot_dock[2]+math.pi))]
    # Reserve 5 cm for Nav2's arrival tolerance before the frozen 60 px
    # camera-resolution boundary. Final robot dock and legacy staging stay fixed.
    staging_distance=.65 if station_perception['mode']=='vision' else .7
    staging=[robot_dock[0]+staging_distance*math.cos(robot_dock[2]),
             robot_dock[1]+staging_distance*math.sin(robot_dock[2]),robot_dock[2]]
    docking=params['docking_server']['ros__parameters']
    docking.pop('simple_charging_dock',None)
    docking.update(base_frame='base_footprint',fixed_frame='odom',dock_backwards=True,max_retries=0,
        dock_plugins=['station_plugin'],docks=['so101_station'],
        so101_station={'type':'station_plugin','frame':'map','pose':native_dock},
        station_plugin={'plugin':'opennav_docking::SimpleNonChargingDock',
            'use_external_detection_pose':True,'use_stall_detection':False,
            'external_detection_timeout':.5,'external_detection_translation_x':0.,
            'external_detection_translation_y':0.,'external_detection_rotation_roll':0.,
            'external_detection_rotation_pitch':0.,'external_detection_rotation_yaw':0.,
            'filter_coef':1.,'docking_threshold':.02,'staging_x_offset':-staging_distance,
            'staging_yaw_offset':math.pi})
    # Native 1.3.13 checks distance to its target 25 cm beyond the real dock.
    # Match that offset so the complete approach remains checked, without
    # rejecting motion for a future segment beyond the plugin's stopping point.
    # The same threshold skips an initial segment of reset/undock control;
    # disable native retries, and this workflow never invokes UndockRobot.
    docking['controller'].update(use_collision_detection=True,
        dock_collision_threshold=NATIVE_DOCKING_TARGET_PROJECTION_M,
        costmap_topic='/local_costmap/costmap_raw',
        footprint_topic='/local_costmap/published_footprint',projection_time=1.)
    from cooperation_profiles import height_envelope
    manifest['transport_height_envelope'] = height_envelope(model, data, manifest,
        padding_m=float(params['local_costmap']['local_costmap']['ros__parameters'].get('footprint_padding', .01)))
    composition_navigation(params, manifest, args.output)
    planner_profile = navigation_planner(params,getattr(args,'navigation_planner','navfn'),
        minimum_turning_radius=getattr(args,'planner_minimum_turning_radius',.20),
        lattice_filepath=getattr(args,'lattice_filepath',None),
        lattice_allow_reversing=getattr(args,'lattice_allow_reversing',False),
        lattice_rotation_shim=getattr(args,'lattice_rotation_shim',False))
    if planner_profile['profile'] == 'smac-lattice':
        source_lattice = Path(planner_profile['lattice_filepath'])
        prepared_lattice = args.output/'cooperation-diff-lattice.json'
        shutil.copyfile(source_lattice, prepared_lattice)
        planner_profile.update(source_lattice_filepath=str(source_lattice),
                               lattice_filepath=str(prepared_lattice))
        params['planner_server']['ros__parameters']['HeadingAware']['lattice_filepath'] = str(prepared_lattice)
    staging_behavior = staging_navigation(params,behavior_path,args.output,
        transport_planner=planner_profile.get('transport_planner'),
        transport_reversing=planner_profile.get('transport_reversing',False),
        transport_in_place_rotation=planner_profile.get('transport_in_place_rotation',False),
        transport_rotation_shim=planner_profile.get('transport_rotation_shim',False),
        staging_reversing=getattr(args,'staging_reversing',False))
    nav_path=args.output/'cooperation-nav2.yaml';nav_path.write_text(yaml.safe_dump(params,sort_keys=False))
    manifest.update(map_yaml=str(localization_path),localization_map_yaml=str(localization_path),
        collision_map_yaml=str(collision_path),nav2_yaml=str(nav_path),static_map_rectangles=rectangles,
        localization_laser_height_m=laser_height,localization_slice_polygons=slices,
        localization_parameters=localization_parameters,
        navigation_behavior_tree=str(behavior_path),
        staging_navigation_behavior_tree=str(staging_behavior),
        staging_motion={'allow_reversing':bool(getattr(args,'staging_reversing',False)),
                        'rotation_shim':bool(getattr(args,'staging_reversing',False))},
        navigation_planner=planner_profile,
        amcl_motion_model=motion_profile,
        navigation_behavior_tree_sha256=hashlib.sha256(behavior_path.read_bytes()).hexdigest(),
        navigation_behavior_tree_sources=behavior_sources,
        navigation_behavior_tree_license='Apache-2.0 (Nav2 1.3.13)',
        staging_pose=staging,native_dock_pose=native_dock,
        native_docking={'dock_id':'so101_station','dock_type':'station_plugin',
            'package':'opennav_docking','version':docking_version,
            'navigate_to_staging_pose':False,'dock_backwards':True,
            'max_retries':0,'supported_action_path':'DockRobot approach only',
            'unsupported_action_paths':['resetApproach','UndockRobot'],
            'controller_target_projection_m':NATIVE_DOCKING_TARGET_PROJECTION_M,
            'collision_threshold_reference':'projected virtual target, not actual dock',
            'primary_sources':NATIVE_DOCKING_PRIMARY_SOURCES,
            'physical_robot_dock_pose':robot_dock,'native_station_pose':native_dock},
        station_perception=station_perception,
        map_resolution_m=resolution,source_nav2_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        generated_map_sha256=localization_hash,generated_collision_map_sha256=collision_hash,
        generated_nav2_sha256=hashlib.sha256(nav_path.read_bytes()).hexdigest())
    if manifest.get('vehicle_profile', {}).get('transport_egress') == 'staging':
        manifest['egress_pose'] = dict(zip(('x', 'y', 'yaw'), staging))
        motion = manifest['vehicle_profile'].get('transport_egress_motion')
        if motion is not None:
            manifest['egress_motion'] = {**motion, 'distance_m': staging_distance}
    if station_perception['mode'] == 'ideal':
        manifest['ideal_station_perception'] = {
            'topic':'/cooperation/station_pose','detection_topic':'/cooperation/station_detection',
            'native_pose_topic':'/detected_dock_pose','native_pose_publisher':'fishbot_so101_cooperation',
            'frame':'base_footprint',
            'source':'shared MuJoCo station pose relative to the current physical robot',
            'max_range_m':station_perception['range_limit_m'],'noise_std_m':0.,'noise_std_yaw_rad':0.,
            'occlusion_model':'none','native_station_pose':native_dock,
            'assumption':'Ideal simulation-relative perception; not camera or real-hardware evidence'}
    if observation_faults is not None:
        manifest['observation_faults'] = observation_faults
    (args.output/'scene-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--so101-project',type=Path,required=True)
    parser.add_argument('--fishbot-project',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--scene-profile',type=Path,
                        help='Editable vehicle/sensors/task JSON; creates a new independent scene')
    parser.add_argument('--continuous-delivery',type=Path,
                        help='Finite cargo slots and physical unload stations JSON')
    parser.add_argument('--arena-xml',type=Path,
                        help='Static arena XML shared by physics, arm collision queries and generated maps')
    parser.add_argument('--factory-config',type=Path,
                        help='Editable delivery stations, orders and physical channel occupancy')
    parser.add_argument('--omit-unused-native-rangefinders',action='store_true',
                        help='Omit legacy 500 Hz native rays; preserve actual scan, point cloud and IMU producers')
    parser.add_argument('--queued-ros-dispatch',action='store_true',
                        help='Receive ROS callbacks separately; apply them on the physics owner thread')
    parser.add_argument('--terminal-stop-heartbeat',action='store_true',
                        help='Reuse fresh zero targets while the existing loaded terminal stop completes')
    parser.add_argument('--navigation-planner',choices=('navfn','smac-hybrid','smac-reeds-shepp','smac-lattice'),default='navfn',
                        help='Optional native planner candidate; preserves controller and physical limits')
    parser.add_argument('--planner-minimum-turning-radius',type=float,default=.20,
                        help='Hybrid radius in metres; lattice radius comes from its selected primitives')
    parser.add_argument('--lattice-filepath',type=Path,
                        help='Native differential primitive JSON matching the costmap grid; optional for smac-lattice')
    parser.add_argument('--lattice-allow-reversing',action='store_true',
                        help='Enable native lattice reverse expansion and the existing reversing RPP phase contract')
    parser.add_argument('--lattice-rotation-shim',action='store_true',
                        help='Wrap transport RPP in the native RotationShim; does not imply task qualification')
    parser.add_argument('--staging-reversing',action='store_true',
                        help='Use native reversing RPP and RotationShim for staging; preserve transport and physical limits')
    parser.add_argument('--amcl-motion-model',choices=('source','omni'),default='source',
                        help='Native motion proposal for the odometry reference point; no truth input')
    parser.add_argument('--perception-config',type=Path,
                        help='JSON station observation contract; ideal by default, no vision truth fallback')
    parser.add_argument('--spawn',type=float,nargs=2,default=(0.,-2.),metavar=('X','Y'))
    parser.add_argument('--spawn-yaw',type=float,default=0.,help='initial robot yaw in radians')
    parser.add_argument('--observation-faults',type=Path,help='accepted-Dock fault declaration JSON')
    parser.add_argument('--camera-light-scale',type=float,default=1.,help='actual renderer light attenuation (.1..1)')
    parser.add_argument('--tag-lateral-offset',type=float,default=.03,help='calibrated marker offset along world +Y (m)')
    args=parser.parse_args()
    if args.output.exists():parser.error('输出目录必须是新的，以保留已有回合')
    manifest=prepare(args)
    if args.navigation_planner == 'smac-lattice':
        import sys
        print('WARNING: Nav2 1.3.13 lattice needs the transition-cache patch overlay; '
              'see tools/config/navigation_lattices/README.md. '
              'The manifest alone does not verify the loaded native library.', file=sys.stderr)
    print(json.dumps({k:manifest[k] for k in ['world_xml','map_yaml','collision_map_yaml','nav2_yaml','dock_pose','nq','nv','nu']}))


if __name__=='__main__':main()
