"""Thin vehicle/sensor/task composition around the existing contact models."""
from __future__ import annotations

import copy
import math
from pathlib import Path
import warnings
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENE_PROFILE = {'schema': 1, 'vehicle': 'fishbot', 'sensors': 'planar', 'task': 'transport'}


def normalize_scene_profile(value=None):
    if value is None:
        return dict(DEFAULT_SCENE_PROFILE)
    if not isinstance(value, dict):
        raise ValueError('scene_profile must be an object')
    extra = set(value)-set(DEFAULT_SCENE_PROFILE)
    if extra:
        warnings.warn(f'Ignoring unknown scene_profile metadata fields: {sorted(map(str, extra))}',
                      RuntimeWarning, stacklevel=2)
    result = {**DEFAULT_SCENE_PROFILE,
              **{key: value[key] for key in DEFAULT_SCENE_PROFILE if key in value}}
    if type(result['schema']) is not int or result['schema'] != 1:
        raise ValueError('scene_profile schema must be 1')
    for field, choices in (('vehicle', ('fishbot', 'jackal_j100')),
                           ('sensors', ('planar', 'lidar3d')),
                           ('task', ('transport', 'three_batch_transport'))):
        if result[field] not in choices:
            raise ValueError(f'Unsupported {field}: {result[field]}')
    return result


def vehicle_profile(selected=None):
    """Expose geometry/drive contracts without importing a native ROS runtime."""
    scene = normalize_scene_profile(selected)
    common = {'spawn_free_z_m': .002,
              'localization': {'enabled': False}, 'tray_mount': None}
    if scene['vehicle'] == 'fishbot':
        return {**common, 'id': 'fishbot', 'label': 'FishBot', 'wheel_radius_m': .032,
                'wheel_separation_m': .20, 'left_wheel_joints': ['left_wheel_joint'],
                'right_wheel_joints': ['right_wheel_joint'], 'base_link_z_m': .092,
                'drive': {'type': 'differential', 'effective_track_multiplier': 1.,
                          'physical_track_m': .20, 'effective_track_m': .20},
                'tray_offset_m': [.04, -.06, .067], 'dock_offset_m': [.20, .20, 0.],
                'station_height_delta_m': 0., 'planning_radius_m': .13,
                'source_files': [str(ROOT/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/mjcf/fishbot.xml')]}
    import yaml
    from fishbot_base_profile import DEFAULT_PROFILE, geometry
    source = yaml.safe_load(DEFAULT_PROFILE.read_text())
    actuation = copy.deepcopy(source['simulation_assumptions'])
    # Small differential targets were not tracked at kv=8. Tune the existing
    # native velocity servo; retain contact materials and the force limit.
    actuation['velocity_servo_kv'] = 32.
    drive, chassis = source['drivetrain'], source['chassis']
    base_z = drive['wheel_radius']-drive['wheel_vertical_offset']
    mount_height = .018
    tray_z = chassis['height']+mount_height
    # Shift the tray back as the car moves east: arm-frame XY remains [.24,.14].
    # Raising the complete station keeps the original tray/arm height relation.
    height_delta = base_z+tray_z-(.092+.067)
    # Reuse the native diff_drive_controller effective-track convention. This
    # is an offline calibration of this contact plant, not a physical resize or
    # online ground-truth correction. The official older Jackal value (1.5)
    # supplies the convention only; this MuJoCo plant needs its own value.
    drive_calibration = {
        'type': 'four_wheel_skid_steer', 'effective_track_multiplier': 4.5,
        'physical_track_m': drive['track'], 'effective_track_m': drive['track']*4.5,
        'calibration': {'method': 'offline_native_fixed_track_with_wheel_servo_gain',
            'simulator': 'MuJoCo 3.3.7', 'scope': 'shared_flat_floor_contact_plant_only',
            'online_truth_feedback': False, 'real_hardware_calibrated': False,
            'same_effective_track_required_for_commands_and_encoder_odometry': True,
            'command_yaw_abs_rad_s': [.01, .03, .05, .3],
            'command_linear_m_s': [0., .02], 'cargo_mass_kg': .01,
            'command_step_duration_s': 8., 'statistics_after_command_s': [4., 8.],
            'wheel_sliding_friction': .5, 'wheel_velocity_servo_kv': actuation['velocity_servo_kv'],
            'wheel_torque_limit_nm': 12.,
            'effective_track_baseline': {
                'wheel_velocity_servo_kv': 8.,
                'command_yaw_abs_rad_s': [.08, .3, .573, .67],
                'command_linear_m_s': [-.15, 0., .15],
                'command_step_duration_s': 5., 'statistics_after_command_s': [2., 5.],
                'empty_pure_spin_max_abs_error_rad_s': .04702330142901712,
                'empty_or_loaded_arc_max_abs_yaw_error_rad_s': .06594376177819167,
                'empty_or_loaded_arc_max_abs_linear_error_m_s': .03135374140823912},
            'current_servo_development_panel': {
                'method': 'native_fixed_track_wheel_servo_gain_comparison',
                'gains_compared': [8., 16., 32.],
                'loaded_linear_m_s': .02, 'loaded_yaw_abs_rad_s': [.01, .03, .05],
                'empty_yaw_abs_rad_s': [.3], 'motion_source_s': 8.,
                'stable_window_source_s': [4., 8.],
                'true_yaw_at_signed_001_rad_s': [.010608, -.008285],
                'true_empty_yaw_at_signed_03_rad_s': [.278861, -.279808],
                'loaded_50hz_retention_failures': 0,
                'loaded_500hz_floor_contact_gaps': 1,
                'full_transport_qualification': False},
            'boundary': 'Residual skid is speed/load/direction dependent; this is not exact inverse dynamics.'},
        'sources': [
            {'url': 'https://raw.githubusercontent.com/jackal/jackal/foxy-devel/jackal_control/config/control.yaml',
             'scope': 'official earlier Jackal effective-track convention; its 1.5 value is not adopted'},
            {'url': 'https://raw.githubusercontent.com/ros-controls/ros2_controllers/jazzy/diff_drive_controller/src/diff_drive_controller.cpp',
             'scope': 'native Jazzy applies effective track to wheel commands and encoder odometry'}]}
    return {**common, 'id': source['id'], 'label': source['label'],
            'wheel_radius_m': drive['wheel_radius'], 'wheel_separation_m': drive['track'],
            'drive': drive_calibration,
            'left_wheel_joints': ['front_left_wheel_joint', 'rear_left_wheel_joint'],
            'right_wheel_joints': ['front_right_wheel_joint', 'rear_right_wheel_joint'],
            'base_link_z_m': base_z, 'tray_offset_m': [-.16, -.18, tray_z],
            'dock_offset_m': [.40, .32, 0.], 'station_height_delta_m': height_delta,
            'tray_mount': {'size_m': [.10, .10, mount_height], 'density_kg_m3': 2700.,
                           'position_in_tray_m': [0., .075, -mount_height/2],
                           'mass_kg': .10*.10*mount_height*2700.,
                           'basis': 'assumed_rigid_aluminium_mount_with_real_collision',
                           'support_assumptions': {'rigid_fixed_cantilever': True,
                               'floor_overlap_xy_m': [.10, .035],
                               'outboard_unsupported_span_m': .085,
                               'strength_or_fasteners_validated': False}},
            'navigation': {'max_angular_accel': 2., 'rotate_to_heading_angular_vel': .4,
                           'stopped_goal_checker': True},
            'transport_egress': 'staging',
            'transport_egress_motion': {'type':'drive_on_heading',
                'speed_m_s':.03, 'time_allowance_s':45.},
            'loaded_velocity_smoother': {'max_accel': [.025, 0., .05],
                'max_decel': [-.1, 0., -.2], 'max_velocity': [.03, 0., .05],
                'min_velocity': [-.03, 0., -.05]},
            'loaded_controller': {'FollowPath.desired_linear_vel': .03,
                'FollowPath.regulated_linear_scaling_min_speed': .03,
                'FollowPath.min_approach_linear_velocity': .005,
                'FollowPath.rotate_to_heading_angular_vel': .05},
            'installation': {'nominal_handover_xy_station_m': [.24, .14],
                             'handover_unchanged': True,
                             'layout_purpose': 'increase_low_side_planar_clearance_with_full_tray_footprint',
                             'total_3d_sweep_margin_improved': False},
            'planning_radius_m': geometry(source)['planning_radius_m'],
            'footprint_xy': geometry(source)['footprint'],
            'localization': {**copy.deepcopy(source.get('localization', {})), 'imu_topic': '/imu'},
            'source': copy.deepcopy(source['source']),
            'source_files': [str(DEFAULT_PROFILE), str(ROOT/'tools/fishbot_base_profile.py'),
                *[str(ROOT/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/mjcf/jackal_j100'/name)
                  for name in ('j100_base.stl', 'outdoor.stl')]],
            'simulation_assumptions': actuation}


def vehicle_element(path, spawn, spawn_yaw, selected=None):
    """Reuse the source-derived J100 element; never call ros2_control prepare."""
    profile = vehicle_profile(selected)
    original = ET.parse(path).getroot()
    if profile['id'] == 'fishbot':
        root = original
        car = root.find('worldbody/body')
    else:
        import yaml
        from fishbot_base_profile import DEFAULT_PROFILE, ASSETS, WHEELS, _robot
        source = yaml.safe_load(DEFAULT_PROFILE.read_text())
        root = ET.Element('mujoco')
        root.append(copy.deepcopy(original.find('compiler')))
        root.append(copy.deepcopy(original.find('default')))
        assets = ET.SubElement(root, 'asset')
        for name, filename in (('jackal_body_mesh', 'j100_base.stl'), ('jackal_wheel_mesh', 'outdoor.stl')):
            ET.SubElement(assets, 'mesh', name=name, file=str(ASSETS/filename))
        car = _robot(source)
        world = ET.SubElement(root, 'worldbody');world.append(car)
        actuators = ET.SubElement(root, 'actuator')
        a = profile['simulation_assumptions']
        for name in WHEELS:
            joint = name+'_wheel_joint'
            ET.SubElement(actuators, 'velocity', name=joint, joint=joint,
                kv=str(a['velocity_servo_kv']), ctrllimited='true',
                ctrlrange=f'-{a["wheel_speed_limit_rad_s"]} {a["wheel_speed_limit_rad_s"]}',
                forcelimited='true', forcerange=f'-{a["wheel_torque_limit_nm"]} {a["wheel_torque_limit_nm"]}')
        root.append(copy.deepcopy(original.find('sensor')))
    car.set('pos', ' '.join(map(str, [*spawn, profile['spawn_free_z_m']])))
    if spawn_yaw:
        car.set('quat', ' '.join(map(str, [math.cos(spawn_yaw/2), 0., 0., math.sin(spawn_yaw/2)])))
    return root, car, profile


def _geom_vertical_bounds(model, data, geom):
    import mujoco
    import numpy as np

    kind = int(model.geom_type[geom])
    size = np.asarray(model.geom_size[geom], dtype=float)
    rotation = data.geom_xmat[geom].reshape(3, 3)
    center = data.geom_xpos[geom]
    row = rotation[2]
    if kind == mujoco.mjtGeom.mjGEOM_BOX:
        extent = float(np.abs(row) @ size)
        basis = 'oriented_box_support_function'
    elif kind == mujoco.mjtGeom.mjGEOM_SPHERE:
        extent = float(size[0])
        basis = 'sphere_radius'
    elif kind == mujoco.mjtGeom.mjGEOM_CYLINDER:
        extent = float(size[0]*math.hypot(row[0], row[1])+size[1]*abs(row[2]))
        basis = 'oriented_finite_cylinder_support_function'
    elif kind == mujoco.mjtGeom.mjGEOM_CAPSULE:
        extent = float(size[0]+size[1]*abs(row[2]))
        basis = 'oriented_capsule_support_function'
    elif kind == mujoco.mjtGeom.mjGEOM_ELLIPSOID:
        extent = float(np.linalg.norm(row*size))
        basis = 'oriented_ellipsoid_support_function'
    elif kind == mujoco.mjtGeom.mjGEOM_MESH:
        mesh = int(model.geom_dataid[geom])
        start, count = int(model.mesh_vertadr[mesh]), int(model.mesh_vertnum[mesh])
        vertices = model.mesh_vert[start:start+count] @ rotation.T + center
        return {'name': model.geom(geom).name, 'body': model.body(int(model.geom_bodyid[geom])).name,
                'type': 'mesh', 'compiled_size': size.tolist(),
                'nominal_center_world_m': center.tolist(), 'bound_basis': 'compiled_mesh_vertices',
                'bottom_world_m': float(vertices[:, 2].min()), 'top_world_m': float(vertices[:, 2].max())}
    else:
        # No plane/hfield is part of either current vehicle. An infinite or
        # unsupported collision body cannot be represented by a finite height.
        raise ValueError(f'Unsupported transport collision geometry {model.geom(geom).name}: {kind}')
    return {'name': model.geom(geom).name, 'body': model.body(int(model.geom_bodyid[geom])).name,
            'type': mujoco.mjtGeom(kind).name.removeprefix('mjGEOM_').lower(),
            'compiled_size': size.tolist(), 'nominal_center_world_m': center.tolist(),
            'bound_basis': basis, 'bottom_world_m': float(center[2]-extent),
            'top_world_m': float(center[2]+extent)}


def height_envelope(model, data, manifest, padding_m=.01):
    """Return vehicle/cargo upper Z plus the unchanged footprint padding.

    `data` preserves the proposed prepare-call signature. Its mutable/settled
    state is intentionally not consulted. A fresh MjData uses compiled qpos0,
    so a later call cannot lower the cap by passing a settled suspension pose.
    The result is for a horizontal world floor z=0, rigid cargo supported by
    place_floor, and the current fixed transport mount. Roll, ramps, external
    attachments, and multi-object stacks require a newly derived envelope.
    """
    import mujoco
    import numpy as np

    padding = padding_m
    if not isinstance(padding, (int, float)) or isinstance(padding, bool) or not math.isfinite(padding) or padding < 0:
        raise ValueError('Existing footprint padding must be a finite nonnegative distance')
    nominal = mujoco.MjData(model)
    mujoco.mj_forward(model, nominal)
    base = model.body('base_footprint').id
    descendants = {base}
    for body in range(base+1, model.nbody):
        if int(model.body_parentid[body]) in descendants:
            descendants.add(body)
    components = [_geom_vertical_bounds(model, nominal, geom)
                  for geom in range(model.ngeom)
                  if int(model.geom_bodyid[geom]) in descendants
                  and (model.geom_contype[geom] or model.geom_conaffinity[geom])]
    if not components:
        raise ValueError('Compiled vehicle has no collision geometry for transport height')
    floor = model.geom('place_floor').id
    floor_bound = _geom_vertical_bounds(model, nominal, floor)
    target = model.geom('target_collision').id
    if model.geom_type[target] != mujoco.mjtGeom.mjGEOM_BOX:
        raise ValueError('Current rigid cargo envelope requires target_collision box')
    radius = float(np.linalg.norm(model.geom_size[target]))
    cargo_top = floor_bound['top_world_m'] + 2*radius
    vehicle = max(components, key=lambda item: item['top_world_m'])
    unpadded = max(vehicle['top_world_m'], cargo_top)
    return {'schema': 1, 'scope': 'flat_floor_rigid_single_box_cargo_transport_observation_height',
            'height_reference': 'world_floor_z_zero_nominal_spawn_lift_retained',
            'nominal_base_footprint_world_z_m': float(nominal.xpos[base, 2]),
            'nominal_source': 'fresh_MjData_compiled_qpos0_not_settled_runtime_state',
            'vehicle_id': manifest.get('vehicle_profile', {}).get('id', 'fishbot'),
            'vehicle_top_world_m': vehicle['top_world_m'], 'vehicle_top_component': vehicle['name'],
            'tray_floor_top_world_m': floor_bound['top_world_m'],
            'cargo': {'geom': model.geom(target).name, 'type': 'box',
                      'compiled_half_extents_m': model.geom_size[target].tolist(),
                      'arbitrary_orientation_radius_m': radius,
                      'bound_basis': 'place_floor_top_plus_twice_box_circumsphere_radius',
                      'top_world_m': cargo_top},
            'unpadded_top_world_m': unpadded, 'existing_footprint_padding_m': float(padding),
            'max_obstacle_height_m': unpadded+float(padding),
            'compiled_collision_components': components,
            'physical_geometry_changed': False, 'physical_scoring_changed': False,
            'unsupported_scope': ['ramps', 'body_roll_envelope', 'deformable_cargo', 'cargo_stacks',
                                  'unconfigured_attachments'],
            'native_runtime_costmap_acceptance_claimed': False}
