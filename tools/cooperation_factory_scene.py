#!/usr/bin/env python3
"""Add editable line-side delivery data to the existing contact cooperation scene.

This module supplies task inputs and optional static geometry. The existing
prepare, Workflow, Nav2, arm planner and physical oracle retain execution and
scoring ownership. No ROS publisher or alternative scheduler is created here.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET

from cooperation_core import Rejected, task_delivery_pose
from cooperation_profiles import normalize_scene_profile


OCCUPANCY_GEOM = 'factory_channel_occupancy'


def _vector(value, count, field):
    if (not isinstance(value, (list, tuple)) or len(value) != count
            or any(type(item) not in (int, float) or not math.isfinite(item) for item in value)):
        raise ValueError(f'{field} must contain {count} finite numbers')
    return [float(item) for item in value]


def normalize_factory_config(value):
    """Validate essential geometry and order references; retain editable metadata."""
    if not isinstance(value, dict) or value.get('schema') != 1:
        raise ValueError('factory delivery config requires schema 1')
    result = copy.deepcopy(value)
    if result.get('frame', 'map') != 'map':
        raise ValueError('factory delivery poses use the existing map/world frame')
    result['frame'] = 'map'
    result.setdefault('id', 'line-side-delivery')
    result.setdefault('units', {'position': 'm', 'angle': 'rad', 'size': 'full edge lengths'})
    destinations = result.get('destinations')
    if not isinstance(destinations, list) or not destinations:
        raise ValueError('factory delivery requires at least one destination')
    ids = set()
    for station in destinations:
        if (not isinstance(station, dict) or not isinstance(station.get('id'), str)
                or not station['id'] or station['id'] in ids):
            raise ValueError('factory destination IDs must be nonempty and unique')
        ids.add(station['id'])
        try:
            station['pose'] = task_delivery_pose({'delivery_pose': station.get('pose')})
        except Rejected as error:
            raise ValueError(f"destination {station['id']}: {error}") from error
    orders = result.get('orders')
    if not isinstance(orders, list) or not orders:
        raise ValueError('factory delivery requires at least one order')
    order_ids = set()
    for order in orders:
        if (not isinstance(order, dict) or not isinstance(order.get('id'), str)
                or not order['id'] or order['id'] in order_ids
                or order.get('destination_id') not in ids):
            raise ValueError('factory orders require unique IDs and known destination IDs')
        order_ids.add(order['id'])
    channel = result.setdefault('channel', {'id': 'south_delivery_lane', 'occupied': False})
    if not isinstance(channel, dict) or type(channel.get('occupied')) is not bool:
        raise ValueError('channel.occupied must be a boolean')
    if 'centerline_m' in channel:
        line = channel['centerline_m']
        if not isinstance(line, list) or len(line) < 2:
            raise ValueError('channel.centerline_m requires two or more map points')
        channel['centerline_m'] = [_vector(point, 2, 'channel.centerline_m') for point in line]
    if 'obstacle' in channel or channel['occupied']:
        obstacle = channel.get('obstacle', {})
        obstacle['center_m'] = _vector(obstacle.get('center_m'), 3, 'obstacle.center_m')
        obstacle['size_m'] = _vector(obstacle.get('size_m'), 3, 'obstacle.size_m')
        if any(edge <= 0 for edge in obstacle['size_m']):
            raise ValueError('obstacle.size_m requires positive full edge lengths')
        yaw = obstacle.get('yaw_rad', 0.)
        obstacle['yaw_rad'] = _vector([yaw], 1, 'obstacle.yaw_rad')[0]
        channel['obstacle'] = obstacle
    return result


def _numbers(values):
    return ' '.join(format(float(value), '.12g') for value in values)


def apply_factory_scene(manifest, config):
    """Apply before prepare compiles the world and rasterizes its static geometry.

    World, arm-contact and arm-rig receive the same static occupied box, with
    the arm models translated into their existing station-local frame.
    Consequently the existing map generator, ray sensors and contact queries
    consume one obstacle. Open-channel scenes keep the source XML unchanged.
    """
    factory = normalize_factory_config(config)
    factory['pickup_station'] = {'id': 'so101_station',
        'dock_pose': dict(zip(('x', 'y', 'yaw'), manifest['dock_pose'])),
        'station_offset_m': list(manifest['station_offset'])}
    factory['execution'] = {
        'implementation': 'existing cooperation_workflow.Workflow and cooperation_bridge',
        'per_task_wall_timeout_s': 360,
        'order_count': len(factory['orders']),
        'delivery_semantics': 'original handover, retained cargo, target arrival and quiet cleanup',
        'not_implemented': ['destination unloading', 'factory equipment automation', 'ARIAC scoring']}
    channel = factory['channel']
    if channel['occupied']:
        obstacle = channel['obstacle']
        for key in ('world_xml', 'arm_contact_xml', 'rig_xml'):
            path = Path(manifest[key])
            tree = ET.parse(path)
            world = tree.getroot().find('worldbody')
            if world.find(f"geom[@name='{OCCUPANCY_GEOM}']") is not None:
                raise ValueError('factory geometry was already applied; prepare a new scene')
            offset = [0., 0., 0.] if key == 'world_xml' else manifest['station_offset']
            position = [a-b for a, b in zip(obstacle['center_m'], offset)]
            ET.SubElement(world, 'geom', name=OCCUPANCY_GEOM, type='box',
                pos=_numbers(position), size=_numbers(edge/2 for edge in obstacle['size_m']),
                euler=_numbers([0., 0., obstacle['yaw_rad']]),
                contype='1', conaffinity='3', group='0' if key == 'world_xml' else '3',
                rgba='.85 .45 .12 1')
            tree.write(path, encoding='utf-8', xml_declaration=True)
        channel['geometry_name'] = OCCUPANCY_GEOM
        channel['map_source'] = 'same compiled static world geom as physical contact and sensor rays'
    manifest['factory_delivery'] = factory
    return manifest


def factory_template_jobs(manifest):
    """Translate factory orders to the existing Workflow.create inputs.

    The profile's task remains the original transport action. Explicit factory
    orders determine the number and destinations of workflow jobs, independent
    of the older one/three-job demo template. Every initialization gets new
    batch IDs; names in the editable scenario are business labels, not commands.
    """
    factory = normalize_factory_config(manifest['factory_delivery'])
    destinations = {station['id']: station['pose'] for station in factory['destinations']}
    batches = [str(uuid.uuid4()) for _ in factory['orders']]
    goals = {batch: copy.deepcopy(destinations[order['destination_id']])
             for batch, order in zip(batches, factory['orders'])}
    return batches, goals, normalize_scene_profile(manifest.get('scene_profile'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--so101-project', type=Path, required=True)
    parser.add_argument('--fishbot-project', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scene-profile', type=Path)
    parser.add_argument('--factory-config', type=Path,
        default=Path(__file__).with_name('config')/'factory_delivery/line-side-open.json')
    parser.add_argument('--spawn', type=float, nargs=2, default=(0., -2.))
    parser.add_argument('--spawn-yaw', type=float, default=0.)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('output must be new to preserve existing episodes')
    from cooperation_prepare import prepare
    manifest = prepare(args)
    if 'factory_delivery' not in manifest:
        parser.error('cooperation_prepare requires the optional factory_config hook')
    print(json.dumps({'manifest': str(args.output/'scene-manifest.json'),
        'factory_delivery': manifest['factory_delivery'], 'scene_profile': manifest['scene_profile'],
        'world_xml': manifest['world_xml'], 'collision_map_yaml': manifest['collision_map_yaml']},
        ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
