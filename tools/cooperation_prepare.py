#!/usr/bin/env python3
"""Prepare separate laser localization and full-height collision maps."""
import argparse
import hashlib
import importlib.util
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path


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


def prepare(args):
    docking_version=require_native_docking_version()
    import mujoco
    import numpy as np
    import yaml
    from cooperation_scene import build_scene
    manifest=build_scene(args.so101_project,args.fishbot_project,args.output)
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
    params['amcl']['ros__parameters']['initial_pose'].update(x=manifest['spawn'][0],y=manifest['spawn'][1],yaw=0.)
    # The shared ideal lidar and 2 cm map need workcell localization precision.
    # Native probability accumulation penalizes jointly inconsistent endpoints;
    # the original navigation model's sum of cubed scores was almost indifferent
    # to a measured 10 cm error. Keep motion noise and collision checks intact.
    localization_parameters={'laser_model_type':'likelihood_field_prob','sigma_hit':.05,
        'max_beams':180,'z_hit':.95,'z_rand':.05,'update_min_d':.01,
        'update_min_a':.01,'do_beamskip':False}
    params['amcl']['ros__parameters'].update(localization_parameters)
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
    staging=[robot_dock[0]+.7*math.cos(robot_dock[2]),
             robot_dock[1]+.7*math.sin(robot_dock[2]),robot_dock[2]]
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
            'filter_coef':1.,'docking_threshold':.02,'staging_x_offset':-.7,
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
    nav_path=args.output/'cooperation-nav2.yaml';nav_path.write_text(yaml.safe_dump(params,sort_keys=False))
    manifest.update(map_yaml=str(localization_path),localization_map_yaml=str(localization_path),
        collision_map_yaml=str(collision_path),nav2_yaml=str(nav_path),static_map_rectangles=rectangles,
        localization_laser_height_m=laser_height,localization_slice_polygons=slices,
        localization_parameters=localization_parameters,
        navigation_behavior_tree=str(behavior_path),
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
        ideal_station_perception={'topic':'/detected_dock_pose','frame':'base_footprint',
            'source':'shared MuJoCo station pose relative to the current physical robot',
            'max_range_m':1.,'noise_std_m':0.,'noise_std_yaw_rad':0.,
            'occlusion_model':'none','native_station_pose':native_dock,
            'assumption':'Ideal simulation-relative perception; not camera or real-hardware evidence'},
        map_resolution_m=resolution,source_nav2_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        generated_map_sha256=localization_hash,generated_collision_map_sha256=collision_hash,
        generated_nav2_sha256=hashlib.sha256(nav_path.read_bytes()).hexdigest())
    (args.output/'scene-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--so101-project',type=Path,required=True)
    parser.add_argument('--fishbot-project',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('输出目录必须是新的，以保留已有回合')
    manifest=prepare(args)
    print(json.dumps({k:manifest[k] for k in ['world_xml','map_yaml','collision_map_yaml','nav2_yaml','dock_pose','nq','nv','nu']}))


if __name__=='__main__':main()
