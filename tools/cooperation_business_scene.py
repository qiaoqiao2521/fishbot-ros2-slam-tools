"""Compose finite delivery entities with MuJoCo's native attachment API.

The existing scene and Physics remain the execution world. These helpers add
named physical entities; they do not implement an order owner or inventory.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path
import xml.etree.ElementTree as ET


def _vector(value, length, label):
    if (not isinstance(value, (list, tuple)) or len(value) != length
            or any(isinstance(x, bool) or not isinstance(x, (int, float))
                   or not math.isfinite(x) for x in value)):
        raise ValueError(f'{label} must contain {length} finite numbers')
    return [float(x) for x in value]


def _identity(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be a nonempty entity ID')
    return value


def _numbers(values):
    return ' '.join(repr(float(value)) for value in values)


def compose_business_world(manifest, configuration, output):
    """Add declared unload stations and free cargo before any world is run."""
    import mujoco

    if not isinstance(configuration, dict):
        raise ValueError('continuous delivery configuration must be an object')
    world_id = _identity(configuration.get('id'), 'world')
    stations = configuration.get('unload_stations', [])
    slots = configuration.get('cargo_slots', [])
    if not isinstance(stations, list) or not stations:
        raise ValueError('continuous delivery requires an unload station')
    if not isinstance(slots, list) or len(slots) < 2:
        raise ValueError('continuous delivery requires two independent cargo slots')

    source_world = manifest['world_xml']
    root = ET.parse(source_world).getroot()
    root.set('model', 'fishbot_continuous_delivery')
    assets, world = root.find('asset'), root.find('worldbody')
    if assets is None:
        assets = ET.SubElement(root, 'asset')
    home = list(manifest['arm_home_qpos6'])
    primary_names = list(manifest['arm_joint_names'])
    arms = {'load': {'root_body': 'base', 'joint_names': primary_names,
                     'home_qpos6': home, 'station_position_m': list(manifest['station_offset']),
                     'station_yaw_rad': 0., 'pad_geoms': ['pad_gripper', 'pad_moving_jaw']}}
    unload = {}
    supports = {'pickup': 'pick_floor', 'tray': 'place_floor'}
    tray = manifest['vehicle_profile']['tray_offset_m']
    for index, station in enumerate(stations):
        station_id = _identity(station.get('id'), 'station')
        arm_id = _identity(station.get('arm_id', 'unload_'+station_id), 'arm')
        if station_id in unload or station_id in supports or arm_id in arms:
            raise ValueError('station and arm IDs must be distinct')
        pose = station.get('delivery_pose', {})
        x, y, yaw = _vector([pose.get(k) for k in ('x', 'y', 'yaw')], 3, 'delivery pose')
        arm_yaw, = _vector([station.get('arm_yaw_rad', yaw)], 1, 'arm yaw')
        shelf = _vector(station.get('shelf_xy_m', [.24, -.13]), 2, 'shelf xy')
        bridge = _vector(station.get('bridge_center_xy_m', [shelf[0]/2, shelf[1]/2]), 2, 'bridge center xy')
        c, s = math.cos(yaw), math.sin(yaw)
        arm_cos, arm_sin = math.cos(arm_yaw), math.sin(arm_yaw)
        position = [x+c*tray[0]-s*tray[1]-arm_cos*.24+arm_sin*.14,
                    y+s*tray[0]+c*tray[1]-arm_sin*.24-arm_cos*.14, float(manifest['station_height_m'])]
        asset_name = f'business_arm_asset_{index}'
        ET.SubElement(assets, 'model', name=asset_name, file=manifest['arm_contact_xml'])
        prefix = arm_id+'__'
        frame = ET.SubElement(world, 'frame', name=f'unload_frame_{index}', pos=_numbers(position),
                              quat=_numbers([math.cos(arm_yaw/2), 0., 0., math.sin(arm_yaw/2)]))
        ET.SubElement(frame, 'attach', model=asset_name, body='base', prefix=prefix)
        child_world = ET.parse(manifest['arm_contact_xml']).getroot().find('worldbody')
        keep = {'robot_mount_plate', 'worktable', 'pick_bench', 'bench_bridge',
                'pick_floor', 'pick_plaque'}
        for original in child_world.findall('geom'):
            name = original.get('name', '')
            if name not in keep and not name.startswith(('mount_bolt_', 'pick_wall_')):
                continue
            geom = copy.deepcopy(original)
            geom.set('name', prefix+name)
            geom.set('group', '0')
            if name.startswith('pick_'):
                pos = [float(value) for value in geom.get('pos', '0 0 0').split()]
                geom.set('pos', _numbers([pos[0]+shelf[0]-.24, pos[1]+shelf[1]+.13, pos[2]]))
            elif name == 'bench_bridge' and (shelf != [.24, -.13] or 'bridge_center_xy_m' in station):
                geom.set('pos', _numbers([*bridge, -.023]))
                angle = math.atan2(shelf[1], shelf[0])
                geom.set('quat', _numbers([math.cos(angle/2), 0., 0., math.sin(angle/2)]))
            frame.append(geom)
        arms[arm_id] = {'root_body': prefix+'base',
                       'joint_names': [prefix+name for name in primary_names],
                       'home_qpos6': home.copy(), 'station_position_m': position,
                       'station_yaw_rad': arm_yaw,
                       'pad_geoms': [prefix+'pad_gripper', prefix+'pad_moving_jaw']}
        floor_name = prefix+'pick_floor'
        supports[station_id] = floor_name
        unload[station_id] = {'arm_id': arm_id, 'delivery_pose': dict(zip(('x', 'y', 'yaw'), (x, y, yaw))),
                              'shelf_floor_geom': floor_name, 'shelf_xy_in_station_m': shelf}
        if 'cargo_shelf_slots' in station:
            unload[station_id]['cargo_shelf_slots'] = copy.deepcopy(station['cargo_shelf_slots'])

    cargo = {}
    ET.SubElement(assets, 'model', name='business_cargo_asset', file=source_world)
    for index, slot in enumerate(slots):
        cargo_id = _identity(slot.get('id'), 'cargo')
        if cargo_id in cargo or cargo_id in arms:
            raise ValueError('cargo IDs must be distinct')
        offset = _vector(slot.get('offset_m', [0., .04*index, 0.]), 3, 'pickup offset')
        if index == 0:
            prefix = ''
            if any(offset):
                body = world.find("body[@name='grasp_target']")
                position = [float(value) for value in body.get('pos', '0 0 0').split()]
                body.set('pos', _numbers([a+b for a, b in zip(position, offset)]))
        else:
            prefix = cargo_id+'__'
            frame = ET.SubElement(world, 'frame', name=f'cargo_slot_frame_{index}', pos=_numbers(offset))
            ET.SubElement(frame, 'attach', model='business_cargo_asset', body='grasp_target', prefix=prefix)
        cargo[cargo_id] = {'body': prefix+'grasp_target', 'geom': prefix+'target_collision',
                           'free_joint': prefix+'target_free', 'pickup_offset_m': offset,
                           'pickup_support': 'pickup'}

    # Validate declared physical shelf cells before creating a live world.
    from cooperation_business import placement_slot
    description = {'business_entities': {'unload_stations': unload}}
    for station_id, station in unload.items():
        cells = station.get('cargo_shelf_slots')
        if cells is None:
            continue
        if not isinstance(cells, dict) or set(cells) != set(cargo):
            raise ValueError('Shelf cells must identify every configured cargo')
        resolved = [placement_slot(description, station_id, key) for key in cells]
        for i, first in enumerate(resolved):
            for second in resolved[i+1:]:
                if all(abs(first['center_xy_m'][axis]-second['center_xy_m'][axis])
                       < first['half_size_xy_m'][axis]+second['half_size_xy_m'][axis]
                       for axis in range(2)):
                    raise ValueError('Shelf cells overlap; assign distinct physical destinations')

    path = Path(output)/'continuous-world.xml'
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)
    model = mujoco.MjModel.from_xml_path(str(path))
    for arm in arms.values():
        joints = [model.joint(name).id for name in arm['joint_names']]
        arm['qpos_indices'] = [int(model.jnt_qposadr[j]) for j in joints]
        arm['qvel_indices'] = [int(model.jnt_dofadr[j]) for j in joints]
        arm['actuator_names'] = [model.actuator(name).name for name in arm['joint_names']]
    for item in cargo.values():
        joint = model.joint(item['free_joint']).id
        if model.jnt_type[joint] != mujoco.mjtJoint.mjJNT_FREE:
            raise ValueError('cargo must remain an independent native free body')
        item['qpos_indices'] = list(range(int(model.jnt_qposadr[joint]), int(model.jnt_qposadr[joint])+7))
        item['qvel_indices'] = list(range(int(model.jnt_dofadr[joint]), int(model.jnt_dofadr[joint])+6))
        item['mass_kg'] = float(model.body_mass[model.body(item['body']).id])

    result = copy.deepcopy(manifest)
    result.update(world_xml=str(path), nq=model.nq, nv=model.nv, nu=model.nu,
                  joints=[model.joint(i).name for i in range(model.njnt)],
                  actuator_names=[model.actuator(i).name for i in range(model.nu)])
    result['business_entities'] = {'schema': 1, 'world_id': world_id, 'arms': arms, 'cargo': cargo,
                                   'support_geoms': supports, 'unload_stations': unload,
                                   'configuration': copy.deepcopy(configuration),
                                   'order_execution_validated': False}
    return result


def bind_entities(model, entities):
    """Resolve actual names; serialized index hints do not control the plant."""
    arms, cargo = {}, {}
    for arm_id, record in entities['arms'].items():
        joints = [model.joint(name).id for name in record['joint_names']]
        if len(joints) != 6:
            raise ValueError('SO101 entity must contain six joints')
        arms[arm_id] = {'body': model.body(record['root_body']).id,
                        'qpos': [int(model.jnt_qposadr[j]) for j in joints],
                        'qvel': [int(model.jnt_dofadr[j]) for j in joints],
                        'limits': [tuple(model.jnt_range[j]) for j in joints],
                        'actuators': [model.actuator(name).id for name in record['actuator_names']],
                        'joint_names': list(record['joint_names']),
                        'reference': _vector(record['home_qpos6'], 6, 'arm home'),
                        'pads': {name: model.geom(name).id for name in record['pad_geoms']}}
    for cargo_id, record in entities['cargo'].items():
        cargo[cargo_id] = {'body': model.body(record['body']).id,
                           'geom': model.geom(record['geom']).id,
                           'joint': model.joint(record['free_joint']).id}
    return arms, cargo


def measured_entities(plant):
    """Read measured entities; never infer inventory or task completion."""
    return {'world_id': plant.business_description['world_id'],
            'arms': {name: {'joint_names': arm['joint_names'],
                             'qpos6': plant.data.qpos[arm['qpos']].tolist(),
                             'qvel6': plant.data.qvel[arm['qvel']].tolist(),
                             'reference_q6': list(plant.reference if name == 'load' else arm['reference'])}
                     for name, arm in plant.business_arms.items()},
            'cargo': {name: {'position': plant.data.xpos[item['body']].tolist(),
                              'quaternion_wxyz': plant.data.xquat[item['body']].tolist(),
                              'velocity_world_angular_linear': plant.body_velocity(item['body']),
                              'contacts': plant.contacts['business_contacts'][name]}
                      for name, item in plant.business_cargo.items()}}
