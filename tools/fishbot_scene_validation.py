#!/usr/bin/env python3
"""Editable real-scene case panels on the existing MuJoCo and mission owner.

prepare writes three independent scenes; run connects to a caller-started scene.
No hashes, scheduler, automatic Goal replay, or hardware operations are added.
"""
from __future__ import annotations

import argparse
from collections import deque
import copy
from datetime import datetime, timezone
from html import escape
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
import uuid
import warnings
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'tools'
TERMINAL = {'succeeded', 'failed', 'canceled'}
DEFAULT_CASES = [
    {'id': 'clear', 'label': '畅通往返', 'expected': 'delivered', 'obstacle': None},
    {'id': 'detour', 'label': '绕障往返', 'expected': 'delivered', 'timeout_s': 120.,
     'obstacle': {'center': [1.18, 0., .222], 'half_size': [.18, .18, .22]}},
    {'id': 'blocked', 'label': '堵死后取消', 'expected': 'canceled', 'cancel_after_s': 8.,
     'obstacle': {'center': [.65, 0., .222], 'half_size': [.18, .42, .22]}},
]


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as error:
        if default is None:
            raise
        warnings.warn(f'WARNING: cannot read {path}: {error}; using default')
        return copy.deepcopy(default)


def finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def resolve_path(value, base):
    path = Path(value).expanduser()
    return str((path if path.is_absolute() else base / path).resolve())


def load_config(path):
    path = Path(path).expanduser().resolve()
    raw = read_json(path)
    if not isinstance(raw, dict):
        raise ValueError('Panel config must be a JSON object')
    config = copy.deepcopy(raw)
    for key in ('scene_path', 'map', 'source_map', 'plugins_file', 'params_file'):
        if config.get(key):
            config[key] = resolve_path(config[key], path.parent)
    source = config.get('source')
    if not isinstance(source, dict):
        warnings.warn('WARNING: source metadata missing; scene correspondence is unspecified')
        source = {}
    config['source'] = {**source, 'label': source.get('label', '用户场景'),
                        'basis': source.get('basis', 'unspecified'),
                        'assumption_cells': source.get('assumption_cells')}
    if 'lidar' not in config or not isinstance(config['lidar'], dict):
        warnings.warn('WARNING: lidar metadata missing; retaining existing runtime sensors')
        config['lidar'] = {'profile': 'existing-runtime'}
    config['lidar'].setdefault('profile', 'existing-runtime')
    config.setdefault('api', 'http://127.0.0.1:9100')
    config.setdefault('domain', 130)
    config.setdefault('timeout_s', 90.)
    config.setdefault('startup_timeout_s', 45.)
    config.setdefault('return_home', True)
    config.setdefault('geometry', {'half_length': .105, 'half_width': .125})
    config.setdefault('waypoints', [{'x': 1.75, 'y': 0., 'yaw': 0.}])
    config.setdefault('cases', copy.deepcopy(DEFAULT_CASES))
    if not isinstance(config['cases'], list):
        raise ValueError('cases must be an editable JSON array')
    config['config_file'] = str(path)
    return config


def reference_scene(output):
    """Public dimensioned fixture; explicitly not a measured home reconstruction."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    model = ET.Element('mujoco', model='fishbot_room_door_corridor_reference')
    ET.SubElement(model, 'include', file=str(ROOT / 'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/mjcf/fishbot.xml'))
    world = ET.SubElement(model, 'worldbody')
    ET.SubElement(world, 'light', name='reference_light', pos='0 0 4')
    ET.SubElement(world, 'geom', name='floor', type='plane', size='5 5 .1', rgba='.8 .83 .86 1')
    boxes = [
        ('west_wall', [-.8,0,.3], [.05,1.65,.3]),
        ('east_wall', [2.25,0,.3], [.05,1.65,.3]),
        ('north_wall', [.725,1.65,.3], [1.575,.05,.3]),
        ('south_wall', [.725,-1.65,.3], [1.575,.05,.3]),
        ('door_north', [.65,1.025,.3], [.06,.625,.3]),
        ('door_south', [.65,-1.025,.3], [.06,.625,.3]),
        ('low_height_probe', [-.25,.55,.04], [.08,.08,.04]),
    ]
    for name, center, half in boxes:
        ET.SubElement(world, 'geom', name=name, type='box', pos=' '.join(map(str,center)),
                      size=' '.join(map(str,half)), rgba='.28 .4 .55 1')
    ET.indent(model)
    ET.ElementTree(model).write(output / 'scene.xml', encoding='utf-8', xml_declaration=True)
    resolution, origin, width, height = .025, [-.85,-1.7,0.], 126, 136
    pixels = bytearray()
    for row in range(height):
        y = origin[1]+(height-row-.5)*resolution
        for column in range(width):
            x = origin[0]+(column+.5)*resolution
            pixels.append(0 if any(abs(x-center[0]) <= half[0] and abs(y-center[1]) <= half[1]
                                   for name,center,half in boxes if name != 'low_height_probe') else 254)
    (output/'map.pgm').write_bytes(f'P5\n{width} {height}\n255\n'.encode()+pixels)
    (output/'map.yaml').write_text('image: map.pgm\nresolution: 0.025\norigin: [-0.85, -1.7, 0.0]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.25\nmode: trinary\n')
    return {'scene_path': str(output/'scene.xml'), 'map': str(output/'map.yaml'),
        'layout': {'type': 'room-door-corridor', 'door_width_m': .8,
            'interior_bounds_m': [-.75,-1.6,2.2,1.6], 'partition_x_m': .65,
            'spawn': [0.,0.,0.], 'goal': [1.75,0.,0.],
            'low_height_probe': {'center':[-.25,.55,.04], 'half_size':[.08,.08,.04],
                'in_static_map':False, 'source':'synthetic sensor probe, outside mission route'}}}


def normalized_case(raw, index, config):
    if not isinstance(raw, dict):
        raise ValueError('Case must be a JSON object')
    case = copy.deepcopy(raw)
    case.setdefault('id', f'case-{index + 1}')
    if not isinstance(case['id'], str) or not case['id'] or Path(case['id']).name != case['id'] or case['id'] in {'.', '..'}:
        raise ValueError('Case id must be one directory name')
    case.setdefault('label', case['id'])
    case.setdefault('expected', 'canceled' if case['id'] == 'blocked' else 'delivered')
    if case['expected'] not in {'delivered', 'canceled'}:
        raise ValueError('expected must be delivered or canceled')
    case.setdefault('waypoints', copy.deepcopy(config['waypoints']))
    case.setdefault('timeout_s', config['timeout_s'])
    case.setdefault('api', config['api'])
    case.setdefault('domain', config['domain'])
    case.setdefault('return_home', config['return_home'])
    case.setdefault('geometry', copy.deepcopy(config['geometry']))
    if case['expected'] == 'canceled':
        case.setdefault('cancel_after_s', 8.)
    return case


def scene_boxes(scene_path):
    """Read only axis-aligned world boxes; unsupported geometry stays explicit."""
    root = ET.parse(scene_path).getroot()
    boxes = []
    unsupported = []
    world = root.find('worldbody')
    if world is None:
        return boxes, ['worldbody missing']
    for geom in world.findall('geom'):
        if geom.get('type') != 'box':
            continue
        if any(key in geom.attrib for key in ('quat', 'axisangle', 'xyaxes', 'zaxis')):
            unsupported.append(geom.get('name', 'unnamed rotated geom'))
            continue
        if geom.get('euler'):
            # home_scene rotates textured Y/Z boxes onto the same planar union.
            euler = list(map(float, geom.get('euler').split()))
            if len(euler) == 3 and abs(abs(euler[0]) - math.pi / 2) < 1e-8 and max(abs(euler[1]), abs(euler[2])) < 1e-8:
                size = list(map(float, geom.get('size').split()))
                size[1], size[2] = size[2], size[1]
            else:
                unsupported.append(geom.get('name', 'unnamed rotated geom'))
                continue
        else:
            size = list(map(float, geom.get('size').split()))
        center = list(map(float, geom.get('pos', '0 0 0').split()))
        if len(size) == len(center) == 3 and center[2] + size[2] > .02 and center[2] - size[2] < .24:
            boxes.append({'id': geom.get('name', 'world-box'), 'center': center[:2], 'half_size': size[:2]})
    return boxes, unsupported


def prepare_panel(config, output):
    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    panel = copy.deepcopy(config)
    if not panel.get('scene_path'):
        if panel.get('source_map'):
            spec = importlib.util.spec_from_file_location('fishbot_scene_home_reuse', TOOLS / 'fishbot_home_scene.py')
            helper = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(helper)
            semantic = helper.generate(panel['source_map'], output / 'base', padding=float(panel.get('padding', 3.)))
            panel.update(scene_path=str(output / 'base/scene.xml'), map=str(output / 'base/map.yaml'))
            provenance = semantic.get('provenance', {})
            panel['source']['assumption_cells'] = {
                key: provenance.get(key) for key in ('assumed_free_cells', 'assumed_occupied_cells')}
            panel['source']['assumption_mask'] = str(output/'base/assumption_mask.pgm')
            panel['source']['basis'] = 'measured occupancy with explicit synthetic unknown completion'
        else:
            panel.update(reference_scene(output/'base'))
            panel['source'].update(label=panel['source'].get('label', '房间-门口-走廊参考场景'),
                                   basis='synthetic_reference', assumption_cells='all scene cells are synthetic')
    if not panel.get('map'):
        raise ValueError('map YAML is required with scene_path')
    source_scene = Path(panel['scene_path'])
    static_boxes, unsupported = scene_boxes(source_scene)
    prepared = []
    errors = []
    for index, raw in enumerate(panel['cases']):
        try:
            case = normalized_case(raw, index, panel)
            directory = output / case['id']
            directory.mkdir(parents=True, exist_ok=True)
            tree = ET.parse(source_scene)
            for element in tree.getroot().iter():
                value = element.get('file')
                if value:
                    element.set('file', resolve_path(value, source_scene.parent))
            world = tree.getroot().find('worldbody')
            if world is None:
                raise ValueError('Scene has no worldbody')
            actor = world.find("body[@name='moving_obstacle']")
            if actor is None:
                actor = ET.SubElement(world, 'body', name='moving_obstacle')
                ET.SubElement(actor, 'freejoint', name='moving_obstacle_free_joint')
            for geom in list(actor.findall('geom')):
                actor.remove(geom)
            obstacle = case.get('obstacle')
            if obstacle is None:
                center, half = [-20., -20., .222], [.18, .18, .22]
            else:
                if not isinstance(obstacle,dict):
                    raise ValueError('Obstacle must be an object or null')
                center = obstacle.get('center', [.65, 0., .222])
                half = obstacle.get('half_size', [.18, .18, .22])
                if len(center) != 3 or len(half) != 3 or not all(finite(v) for v in center + half) or min(half) <= 0:
                    raise ValueError('Obstacle center and positive half_size require three finite numbers')
            actor.set('pos', ' '.join(map(str, center)))
            actor.attrib.pop('quat', None)
            actor.attrib.pop('euler', None)
            ET.SubElement(actor, 'geom', name='moving_obstacle_collision', type='box',
                          size=' '.join(map(str, half)), mass='2', rgba='.85 .35 .12 1')
            scene_path = directory / 'scene.xml'
            ET.indent(tree)
            tree.write(scene_path, encoding='utf-8', xml_declaration=True)
            case.update(scene_path=str(scene_path), map=panel['map'], static_boxes=static_boxes,
                        unscored_static_geometry=unsupported,
                        obstacle_initial={'center': center, 'half_size': half},
                        scene_selection_basis='caller must launch this case scene; mission API alone cannot attest XML identity')
            for key in ('plugins_file', 'params_file'):
                if panel.get(key):
                    case[key] = panel[key]
            case['launch_arguments'] = {'scene_path': str(scene_path), 'map': panel['map'],
                'ros_domain_id': str(case['domain']), 'bridge': 'true', 'obstacle': 'false'}
            for key in ('plugins_file', 'params_file'):
                if case.get(key):
                    case['launch_arguments'][key] = case[key]
            write_json(directory / 'case.json', case)
            prepared.append(case)
        except (OSError, ValueError, TypeError, ET.ParseError) as error:
            warnings.warn(f'WARNING: case {index + 1} not prepared: {error}; continuing other cases')
            candidate = raw.get('id') if isinstance(raw,dict) else None
            case_id = candidate if isinstance(candidate,str) and candidate not in {'','.', '..'} \
                and Path(candidate).name == candidate else f'case-{index+1}'
            errors.append({'index':index,'case_id':case_id,
                'label':str(raw.get('label',case_id)) if isinstance(raw,dict) else case_id,
                'expected':raw.get('expected','unknown') if isinstance(raw,dict) else 'unknown',
                'error':str(error)})
    panel.update(schema_version=1, scope='simulation', cases=prepared, preparation_errors=errors,
                 prepared_at=datetime.now(timezone.utc).isoformat())
    panel.pop('config_file', None)
    write_json(output / 'panel.json', panel)
    return panel


class MissionAPI:
    def __init__(self, base, timeout=2.):
        parts = urlsplit(base)
        if parts.scheme != 'http' or parts.hostname not in {'127.0.0.1', 'localhost', '::1'}:
            raise ValueError('Use the existing loopback mission API')
        self.base = base.rstrip('/')
        self.timeout = timeout
        self.instance = None

    def request(self, method, path, body=None):
        headers = {'Accept': 'application/json'}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        if self.instance:
            headers['X-Fishbot-Instance'] = self.instance
        request = Request(self.base + path, data=payload, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                return response.status, json.loads(raw), dict(response.headers)
        except HTTPError as error:
            raw = error.read().decode(errors='replace')
            try:
                value = json.loads(raw)
            except ValueError:
                value = {'error': raw}
            return error.code, value, dict(error.headers)


def cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])


def point_segment_distance(point, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    t = max(0., min(1., ((point[0]-a[0])*dx + (point[1]-a[1])*dy) / (dx*dx+dy*dy or 1.)))
    return math.hypot(point[0]-a[0]-t*dx, point[1]-a[1]-t*dy)


def polygon_clearance(pose, box, geometry):
    """Signed SAT separation, with Euclidean edge distance for disjoint rectangles."""
    x, y, yaw = pose
    half_x, half_y = geometry.get('half_length', .105), geometry.get('half_width', .125)
    c, s = math.cos(yaw), math.sin(yaw)
    car = [(x+c*a-s*b, y+s*a+c*b) for a, b in
           ((-half_x, -half_y), (half_x, -half_y), (half_x, half_y), (-half_x, half_y))]
    bx, by = box['center'][:2]
    hx, hy = box['half_size'][:2]
    obstacle = [(bx-hx, by-hy), (bx+hx, by-hy), (bx+hx, by+hy), (bx-hx, by+hy)]
    gaps = []
    for axis in ((1., 0.), (0., 1.), (c, s), (-s, c)):
        car_projection = [px*axis[0]+py*axis[1] for px, py in car]
        box_projection = [px*axis[0]+py*axis[1] for px, py in obstacle]
        gaps.append(max(min(box_projection)-max(car_projection), min(car_projection)-max(box_projection)))
    if max(gaps) <= 0:
        return max(gaps)
    return min(point_segment_distance(p, a, b) for shape, other in ((car, obstacle), (obstacle, car))
               for p in shape for a, b in zip(other, other[1:]+other[:1]))


def assess(case, evidence, recording):
    """Score navigation roundtrips, without inventing cargo or receipt evidence."""
    spec = importlib.util.spec_from_file_location('fishbot_scene_score_reuse', TOOLS / 'fishbot_simulation_report.py')
    score = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(score)
    mission = evidence.get('mission') or {}
    expected = case.get('expected', 'delivered')
    native = mission.get('native_goal_id')
    samples = recording.get('truth') or []
    sent = evidence.get('sent_steady')
    start = next((index for index, sample in enumerate(samples) if finite(sent) and sample.get('steady_time', -1) >= sent), 0)
    samples = samples[max(0, start-1):]
    checks = {}
    def check(key, condition, detail=None):
        checks[key] = {'status': 'unknown' if condition is None else 'passed' if condition else 'failed', 'detail': detail}
    check('original_task', mission.get('id') == evidence.get('task_id') if mission else None)
    check('native_uuid', isinstance(native, str) and len(native) == 32 if mission else None)
    check('native_terminal', mission.get('native_status') == (5 if expected == 'canceled' else 4) if native else None)
    observed = [event for event in recording.get('native_status', []) if event.get('uuid') == native]
    check('independent_native_terminal', any(event.get('status') == (5 if expected == 'canceled' else 4) for event in observed) if native else None)
    check('owner_terminal', mission.get('status') == ('canceled' if expected == 'canceled' else 'succeeded') if mission else None)
    check('owner_cleanup', mission.get('cleanup_state') is None if mission else None, mission.get('cleanup_state'))
    if expected == 'canceled':
        check('original_cancel_submitted', evidence.get('cancel_task_id') == evidence.get('task_id'))
    fields = ('steady_time', 'stamp', 'x', 'y', 'yaw', 'linear_speed', 'angular_speed', 'ros_now')
    valid = bool(samples) and all(all(finite(sample.get(key)) for key in fields) for sample in samples)
    check('truth_present', valid if samples else None)
    physical_delivery = False
    metrics = {'truth_samples': len(samples), 'contact_force_observed': False,
               'clearance_basis': 'padded rectangular footprint versus declared axis-aligned boxes; not contact force',
               'unscored_static_geometry': case.get('unscored_static_geometry', [])}
    contacts = recording.get('contact_audit') or []
    baseline = next((item for item in reversed(contacts) if finite(sent) and item.get('steady_time', math.inf) <= sent), None)
    after = [item for item in contacts if finite(sent) and item.get('steady_time', -math.inf) >= sent]
    terminal_at = evidence.get('terminal_observed_steady')
    end = after[-1] if after else None
    available = (baseline is not None and end is not None
        and all(item.get('available') is True and isinstance(item.get('physics_steps_total'), int)
                and isinstance(item.get('collision_steps_total'), int) for item in [baseline]+after))
    check('actual_contact_audit_available', True if available else None)
    metrics.update(audit_source='/scene_validation/contact_audit: MuJoCo ContactAudit robot/non-floor normal-force pre_step',
                   actual_contact_steps_delta=None)
    if available:
        totals = [item['physics_steps_total'] for item in [baseline]+after]
        collisions = [item['collision_steps_total'] for item in [baseline]+after]
        contact_delta = end['collision_steps_total']-baseline['collision_steps_total']
        advancing = end['physics_steps_total'] > baseline['physics_steps_total'] and all(b >= a for a,b in zip(totals, totals[1:]))
        counter_valid = all(b >= a for a,b in zip(collisions,collisions[1:]))
        fresh = (finite(recording.get('final_steady_time')) and finite(recording.get('final_ros_now'))
            and finite(end.get('stamp')) and 0 <= recording['final_steady_time']-end['steady_time'] <= score.TRUTH_AGE
            and -.05 <= recording['final_ros_now']-end['stamp'] <= score.TRUTH_AGE
            and (not finite(terminal_at) or end['steady_time'] >= terminal_at))
        check('actual_contact_audit_live', True if advancing and counter_valid and fresh else None)
        check('no_actual_collision_steps', contact_delta == 0 if advancing and counter_valid and fresh else None, contact_delta)
        metrics.update(actual_contact_steps_delta=contact_delta, contact_force_observed=True,
            contact_physics_steps_delta=end['physics_steps_total']-baseline['physics_steps_total'],
            peak_normal_force_n=max((item.get('peak_normal_force_n',0.) for item in after if finite(item.get('peak_normal_force_n'))),default=None))
    else:
        check('actual_contact_audit_live', None)
        check('no_actual_collision_steps', None)
    if valid:
        source_gaps = [b['stamp']-a['stamp'] for a, b in zip(samples, samples[1:])]
        receive_gaps = [b['steady_time']-a['steady_time'] for a, b in zip(samples, samples[1:])]
        check('truth_advances', bool(source_gaps) and min(source_gaps + receive_gaps) > 0)
        maximum = max(source_gaps + receive_gaps, default=math.inf)
        check('truth_continuity', maximum <= score.TRUTH_GAP, maximum)
        final = samples[-1]
        receive_age = recording.get('final_steady_time', final['steady_time']) - final['steady_time']
        source_age = recording.get('final_ros_now', final['ros_now']) - final['stamp']
        check('truth_fresh', 0 <= receive_age <= score.TRUTH_AGE and -.05 <= source_age <= score.TRUTH_AGE,
              {'source_age_s': source_age, 'receive_age_s': receive_age})
        stopped = []
        for sample in reversed(samples):
            if not score._stopped(sample):
                break
            stopped.insert(0, sample)
        duration = score._duration(stopped)
        check('continuous_stationary', duration >= .7-1e-9, duration)
        metrics.update(final_pose={key: final[key] for key in ('x', 'y', 'yaw')},
            maximum_source_gap_s=max(source_gaps, default=None), maximum_receive_gap_s=max(receive_gaps, default=None),
            stationary_duration_s=duration, source_age_s=source_age, receive_age_s=receive_age,
            distance_m=sum(math.hypot(b['x']-a['x'], b['y']-a['y']) for a,b in zip(samples,samples[1:])))
        waypoints = case.get('waypoints') or []
        route = [point for point in waypoints if isinstance(point, dict) and all(finite(point.get(key)) for key in ('x','y','yaw'))]
        if case.get('return_home') and isinstance(mission.get('start_pose'), dict):
            route.append(mission['start_pose'])
        route_valid = bool(waypoints) and len(route) == len(waypoints)+int(bool(case.get('return_home')))
        if route_valid and all(all(finite(point.get(key)) for key in ('x','y','yaw')) for point in route):
            goal = route[-1]
            distance = math.hypot(final['x']-goal['x'], final['y']-goal['y'])
            yaw = abs(math.atan2(math.sin(final['yaw']-goal['yaw']), math.cos(final['yaw']-goal['yaw'])))
            visits = score._ordered_visits(samples, [[point[key] for key in ('x','y','yaw')] for point in route])
            ordered = len(visits) == len(route)
            pose_ok = distance <= score.POSITION_TOLERANCE and yaw <= score.YAW_TOLERANCE
            physical_delivery = pose_ok and ordered and duration >= .7-1e-9
            metrics.update(final_position_error_m=distance, final_yaw_error_rad=yaw, ordered_waypoint_visits=visits)
            if expected == 'delivered':
                check('final_pose', distance <= score.POSITION_TOLERANCE and yaw <= score.YAW_TOLERANCE)
                check('ordered_waypoint_coverage', ordered)
        elif expected == 'delivered':
            check('final_pose', None)
            check('ordered_waypoint_coverage', None)
        boxes = case.get('static_boxes', [])
        clearance = math.inf
        for sample in samples:
            dynamic = sample.get('actor')
            active_boxes = list(boxes)
            if dynamic:
                active_boxes.append({'center': [dynamic['x'], dynamic['y']],
                    'half_size': case.get('obstacle_initial', {}).get('half_size', [.18,.18,.22])})
            elif case.get('obstacle'):
                active_boxes.append(case['obstacle'])
            for box in active_boxes:
                clearance = min(clearance, polygon_clearance([sample['x'],sample['y'],sample['yaw']], box, case.get('geometry', {})))
        check('declared_geometry_clearance', clearance >= 0 if finite(clearance) else None, clearance if finite(clearance) else None)
        metrics['minimum_declared_clearance_m'] = clearance if finite(clearance) else None
    else:
        for key in ('truth_advances', 'truth_continuity', 'truth_fresh', 'continuous_stationary', 'declared_geometry_clearance'):
            check(key, None)
        if expected == 'delivered':
            check('final_pose', None)
    passed = checks and all(item['status'] == 'passed' for item in checks.values())
    has_failed = any(item['status'] == 'failed' for item in checks.values())
    acceptance = 'passed' if passed else 'failed' if has_failed else 'incomplete'
    delivered = physical_delivery and mission.get('status') == 'succeeded' and mission.get('native_status') == 4
    business = 'route_completed' if delivered else 'route_incomplete' if mission.get('status') in TERMINAL else 'unknown'
    reason = '往返路线完成并通过独立几何/停车验收' if delivered and passed else '原任务正确取消，往返路线未完成' if passed else '; '.join(key for key,item in checks.items() if item['status'] != 'passed')
    return {'id': case['id'], 'label': case.get('label', case['id']), 'expected': expected,
            'business_scope': 'navigation_roundtrip', 'business_result': business, 'acceptance_result': acceptance, 'reason': reason,
            'metrics': metrics, 'checks': checks, 'task_id': evidence.get('task_id'),
            'native_goal_id': native, 'native_status': mission.get('native_status')}


class NavigationDiagnostics:
    """Bounded read-only snapshots, with separate source and receive clocks."""
    LIMITS = {'/plan':20, '/received_global_plan':20, '/lookahead_point':20, '/local_costmap/costmap':10}

    def __init__(self):
        self.frames = {topic:deque(maxlen=limit) for topic,limit in self.LIMITS.items()}
        self.last = {}
        self.stats = {topic:{'received':0,'sampled':0,'rate_skipped':0} for topic in self.LIMITS}
        self.errors = deque(maxlen=20)

    def accept(self, topic, wall):
        self.stats[topic]['received'] += 1
        if topic in self.last and wall-self.last[topic] < .5:
            self.stats[topic]['rate_skipped'] += 1
            return False
        self.last[topic] = wall
        return True

    def append(self, topic, stamp, frame, wall, ros_now, payload):
        self.frames[topic].append({'stamp':stamp,'frame_id':frame,'steady_time':wall,
                                  'ros_now':ros_now,**payload})
        self.stats[topic]['sampled'] += 1

    def snapshot(self):
        return {'schema_version':1,'scope':'read_only_navigation_diagnostics',
            'maximum_wall_sample_hz_per_topic':2.,'limits':self.LIMITS,
            'maximum_path_points':512,'maximum_full_grid_cells':100000,
            'topics':{topic:list(frames) for topic,frames in self.frames.items()},
            'statistics':self.stats,'errors':list(self.errors),
            'association':'Source stamps and local receipt times are preserved; no direct RPP collision-consumption receipt is claimed.'}


def observe(domain, output, ready):
    """Independent ROS subscriber, intentionally separate from the HTTP owner."""
    os.environ.update(ROS_DOMAIN_ID=str(domain), FISHBOT_MUJOCO_DOMAIN_ID=str(domain),
                      ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST', ROS_LOCALHOST_ONLY='1', ROS_STATIC_PEERS='')
    import rclpy
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, qos_profile_sensor_data
    from rclpy.signals import SignalHandlerOptions
    from action_msgs.msg import GoalStatusArray
    from diagnostic_msgs.msg import DiagnosticArray
    from geometry_msgs.msg import PointStamped
    from nav_msgs.msg import Path as NavigationPath, OccupancyGrid
    from mujoco_ros2_control_msgs.msg import FreeJointStateArray
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = Node('fishbot_scene_validation_observer', parameter_overrides=[Parameter('use_sim_time', value=True)])
    recording = {'truth': [], 'native_status': [], 'contact_audit': [], 'domain': domain}
    navigation = NavigationDiagnostics()
    stopped = []
    signal.signal(signal.SIGINT, lambda *_: stopped.append(True))
    signal.signal(signal.SIGTERM, lambda *_: stopped.append(True))
    def truth(message):
        base = next((item for item in message.free_joints if item.name == 'base_footprint'), None)
        actor = next((item for item in message.free_joints if item.name == 'moving_obstacle'), None)
        if base is None:
            return
        pose, twist = base.pose.pose, base.twist.twist
        q = pose.orientation
        sample = {'steady_time': time.monotonic(), 'stamp': message.header.stamp.sec+message.header.stamp.nanosec*1e-9,
            'x': pose.position.x, 'y': pose.position.y,
            'yaw': math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z)),
            'linear_speed': math.hypot(twist.linear.x, twist.linear.y), 'angular_speed': abs(twist.angular.z),
            'ros_now': node.get_clock().now().nanoseconds*1e-9}
        if actor:
            sample['actor'] = {'x': actor.pose.pose.position.x, 'y': actor.pose.pose.position.y}
        recording['truth'].append(sample)
        write_json(Path(output).with_name('latest-truth.json'), sample)
        publish_ready()
    def publish_ready():
        audits = recording['contact_audit']
        live = len(audits) >= 2 and all(item.get('available') for item in audits[-2:]) \
            and audits[-1].get('physics_steps_total',0) > audits[-2].get('physics_steps_total',0)
        if recording['truth'] and live and not Path(ready).exists():
            write_json(ready, {'observed': True, 'stamp': recording['truth'][-1]['stamp'],
                               'contact_audit_available': True, 'physics_steps_advanced': True})
    def audit(message):
        item = next((value for value in message.status if value.name == 'scene_validation/contact_audit'), None)
        if item is None:
            return
        values = {value.key:value.value for value in item.values}
        level = item.level[0] if isinstance(item.level,(bytes,bytearray)) else int(item.level)
        event = {'steady_time':time.monotonic(), 'stamp':message.header.stamp.sec+message.header.stamp.nanosec*1e-9,
                 'available':str(values.get('available','false')).lower() == 'true', 'level':level}
        for key in ('physics_steps_total','collision_steps_total'):
            try:
                event[key] = int(values[key])
            except (KeyError,ValueError,TypeError):
                event['available'] = False
        for key in ('peak_normal_force_n','last_collision_source_s'):
            try:
                event[key] = float(values[key])
            except (KeyError,ValueError,TypeError):
                event[key] = None
        recording['contact_audit'].append(event)
        publish_ready()
    def status(message):
        for item in message.status_list:
            event = {'uuid': bytes(item.goal_info.goal_id.uuid).hex(), 'status': item.status,
                     'steady_time': time.monotonic()}
            if not any(old['uuid'] == event['uuid'] and old['status'] == event['status'] for old in recording['native_status']):
                recording['native_status'].append(event)
    def nav_capture(topic, message):
        wall = time.monotonic()
        if not navigation.accept(topic,wall):
            return
        try:
            stamp = message.header.stamp.sec+message.header.stamp.nanosec*1e-9
            now = node.get_clock().now().nanoseconds*1e-9
            if topic in {'/plan','/received_global_plan'}:
                original = len(message.poses)
                stride = max(1,math.ceil(max(0,original-1)/511))
                selected = list(message.poses[::stride])
                if original and selected[-1] is not message.poses[-1]:
                    selected.append(message.poses[-1])
                payload = {'original_pose_count':original,'downsampled':len(selected)<original,
                    'poses':[{'position':[pose.pose.position.x,pose.pose.position.y,pose.pose.position.z],
                        'orientation':[pose.pose.orientation.x,pose.pose.orientation.y,pose.pose.orientation.z,pose.pose.orientation.w]}
                        for pose in selected]}
            elif topic == '/lookahead_point':
                payload = {'point':[message.point.x,message.point.y,message.point.z]}
            else:
                info = message.info
                count = len(message.data)
                payload = {'width':info.width,'height':info.height,'resolution':info.resolution,
                    'origin':{'position':[info.origin.position.x,info.origin.position.y,info.origin.position.z],
                        'orientation':[info.origin.orientation.x,info.origin.orientation.y,info.origin.orientation.z,info.origin.orientation.w]},
                    'original_cell_count':count,'grid_omitted':count>100000,
                    'data':list(message.data) if count<=100000 else None}
            navigation.append(topic,stamp,message.header.frame_id,wall,now,payload)
        except (ValueError,TypeError,AttributeError) as error:
            navigation.errors.append({'topic':topic,'steady_time':wall,'error':str(error)})
    node.create_subscription(FreeJointStateArray, '/ground_truth/free_joint_states', truth, qos_profile_sensor_data)
    node.create_subscription(DiagnosticArray, '/scene_validation/contact_audit', audit, qos_profile_sensor_data)
    node.create_subscription(GoalStatusArray, '/follow_waypoints/_action/status', status,
        QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL))
    for topic in ('/plan','/received_global_plan'):
        node.create_subscription(NavigationPath,topic,lambda message,name=topic:nav_capture(name,message),qos_profile_sensor_data)
    node.create_subscription(PointStamped,'/lookahead_point',lambda message:nav_capture('/lookahead_point',message),qos_profile_sensor_data)
    node.create_subscription(OccupancyGrid,'/local_costmap/costmap',lambda message:nav_capture('/local_costmap/costmap',message),qos_profile_sensor_data)
    try:
        while not stopped:
            rclpy.spin_once(node, timeout_sec=.05)
    finally:
        recording.update(final_steady_time=time.monotonic(), final_ros_now=node.get_clock().now().nanoseconds*1e-9)
        try:
            write_json(Path(output).with_name('nav-diagnostics.json'),navigation.snapshot())
        except OSError as error:
            recording['navigation_diagnostics_error'] = str(error)
        write_json(output, recording)
        node.destroy_node()
        rclpy.shutdown()


def stop_observer(process):
    if process is None:
        return
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=3)


def run_case(case, config, directory, api_override=None, domain_override=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    task_id = str(uuid.uuid4())
    evidence = {'task_id': task_id, 'mission': {}, 'http': [], 'scope': 'simulation',
        'scene_path': case.get('scene_path'), 'scene_identity': 'caller_selected_not_attested_by_mission_api',
        'contact_force_observed': False}
    api = MissionAPI(api_override or case.get('api', config['api']))
    domain = domain_override if domain_override is not None else int(case.get('domain', config['domain']))
    if not 1 <= domain <= 232:
        raise ValueError('Select a nonzero simulation ROS domain')
    observer = stream = None
    posted = cancel_attempted = False
    latest = {}
    def request(method, path, body=None):
        stamp = time.monotonic()
        status, data, headers = api.request(method, path, body)
        evidence['http'].append({'method': method, 'path': path, 'status': status, 'at': stamp, 'body': data})
        return status, data
    def cancel_original():
        nonlocal cancel_attempted
        if cancel_attempted:
            return
        status, state = request('GET', '/sim-api/state')
        if status == 200 and state.get('mission', {}).get('id') == task_id and state['mission'].get('status') not in TERMINAL:
            cancel_attempted = True
            evidence['cancel_task_id'] = task_id
            try:
                request('POST', '/sim-api/cancel', {'mission_id': task_id, 'issued_at': time.time()})
            except (OSError, ValueError, URLError) as error:
                evidence['cancel_receipt_unknown'] = str(error)
    try:
        status, runtime = request('GET', '/sim-api/runtime')
        if status != 200 or runtime.get('domain') != domain or runtime.get('mode') not in {'simulation', 'mujoco'}:
            raise ValueError('Selected API is not the requested simulation domain')
        evidence['runtime'] = runtime
        api.instance = runtime.get('instance_id')
        deadline = time.monotonic()+float(config.get('startup_timeout_s', 45.))
        while time.monotonic() < deadline:
            status, latest = request('GET', '/sim-api/state')
            if status == 200 and latest.get('domain') == domain and latest.get('ready'):
                break
            time.sleep(.1)
        else:
            raise TimeoutError('Selected scene runtime did not become ready')
        active = latest.get('mission', {})
        if active.get('status') not in TERMINAL | {'idle'}:
            raise ValueError('Existing task still active or unknown; this case did not replace it')
        stream = (directory / 'observer.log').open('w')
        observer = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_observe',
            '--domain', str(domain), '--output', str(directory / 'recording.json'),
            '--ready', str(directory / 'observer-ready.json')], stdout=stream, stderr=subprocess.STDOUT)
        deadline = time.monotonic()+10.
        while not (directory / 'observer-ready.json').is_file():
            if observer.poll() is not None:
                raise RuntimeError('Independent observer exited; inspect observer.log')
            if time.monotonic() > deadline:
                raise TimeoutError('Independent ground truth/contact-audit steps unavailable before dispatch')
            time.sleep(.05)
        body = {'mission_id': task_id, 'waypoints': case['waypoints'], 'return_home': case.get('return_home', False),
                'timeout_s': float(case.get('timeout_s', 90.)), 'issued_at': time.time()}
        rules = latest.get('map_rules') or {}
        map_id = rules.get('map_id')
        if map_id:
            body['map_id'] = map_id
        if isinstance(rules.get('revision'), int):
            body['rules_revision'] = rules['revision']
        evidence.update(sent_steady=time.monotonic(), request=body)
        posted = True
        try:
            status, response = request('POST', '/sim-api/mission', body)
            evidence['submission_status'] = status
            if status >= 400 and response.get('outcome') == 'rejected':
                raise ValueError(f'Original mission rejected: {response.get("error", status)}')
        except (URLError, OSError) as error:
            evidence['submission_unknown'] = str(error)
        # Query only the original ID after an uncertain write. Never resend.
        deadline = time.monotonic()+float(case.get('timeout_s', 90.))+10.
        lookup = '/sim-api/tasks/' + task_id + ('?map_id='+quote(map_id) if map_id else '')
        while time.monotonic() < deadline:
            try:
                status, payload = request('GET', lookup)
                mission = payload.get('mission', {})
                if status == 200 and mission.get('id') == task_id:
                    evidence['mission'] = mission
                    if mission.get('status') in TERMINAL and mission.get('cleanup_state') is None:
                        evidence['terminal_observed_steady'] = time.monotonic()
                        break
                elif status not in {404, 503, 504}:
                    raise ValueError(f'Original task lookup failed: HTTP {status}')
            except (URLError, OSError) as error:
                evidence.setdefault('warnings', []).append(str(error))
            if case.get('expected') == 'canceled' and time.monotonic()-evidence['sent_steady'] >= float(case.get('cancel_after_s', 8.)):
                cancel_original()
            if observer.poll() is not None:
                raise RuntimeError('Independent observer exited during task')
            time.sleep(.1)
        else:
            raise TimeoutError('Original task terminal/cleanup not confirmed')
    except (OSError, ValueError, TimeoutError, RuntimeError, URLError) as error:
        evidence['error'] = str(error)
    finally:
        if posted and evidence.get('mission', {}).get('status') not in TERMINAL:
            try:
                cancel_original()
                until = time.monotonic()+8.
                while time.monotonic() < until:
                    status, payload = request('GET', '/sim-api/tasks/'+task_id)
                    if status == 200 and payload.get('mission', {}).get('id') == task_id:
                        evidence['mission'] = payload['mission']
                        if payload['mission'].get('status') in TERMINAL and payload['mission'].get('cleanup_state') is None:
                            evidence['terminal_observed_steady'] = time.monotonic()
                            break
                    time.sleep(.1)
            except (OSError, ValueError, URLError) as error:
                evidence['cleanup_error'] = str(error)
        if observer is not None and observer.poll() is None:
            time.sleep(1.)
        stop_observer(observer)
        if stream:
            stream.close()
        write_json(directory / 'evidence.json', evidence)
    result = assess(case, evidence, read_json(directory / 'recording.json', {}))
    if evidence.get('error') or evidence.get('cleanup_error'):
        result.update(acceptance_result='failed' if posted else 'incomplete', reason=evidence.get('error') or evidence['cleanup_error'])
    result['artifact_directory'] = directory.name
    write_json(directory / 'result.json', result)
    return result


def save_report(config, results, output):
    output = Path(output)
    report = {'schema_version': 1, 'scope': 'simulation', 'business_scope': 'navigation_roundtrip', 'source': config.get('source', {}),
              'lidar': config.get('lidar', {'profile': 'existing-runtime'}), 'cases': results,
              'layout': config.get('layout'),
              'preparation_errors': config.get('preparation_errors', []),
              'limitations': ['Scene XML selection is declared by the launcher, not attested by mission API.',
                              'Geometry clearance is separate from actual ContactAudit normal-force counters; missing contact evidence is incomplete.',
                              'No hardware or sim-to-real claim.']}
    write_json(output / 'report.json', report)
    rows = ''.join('<tr>'+''.join('<td>'+escape(str(result.get(key, '')) )+'</td>' for key in
        ('label', 'expected', 'business_result', 'acceptance_result', 'reason', 'task_id', 'native_goal_id'))+'</tr>' for result in results)
    page = '<!doctype html><meta charset="utf-8"><title>FishBot 场景业务验收</title>' \
        '<style>body{font:15px system-ui;margin:32px;color:#17243a}table{border-collapse:collapse;width:100%}td,th{padding:12px;border:1px solid #d6deea;text-align:left}td{overflow-wrap:anywhere}p{max-width:900px}</style>' \
        '<h1>FishBot 场景路线验收</h1><p>本轮只验证导航往返，不包含货物或收货签收。路线结果与验收结果分别记录，场景为明确声明来源的仿真输入。</p>' \
        '<p><a href="report.json">结构化报告</a></p><table><tr><th>工况</th><th>预期</th><th>业务结果</th><th>验收</th><th>原因</th><th>任务</th><th>原生 UUID</th></tr>'+rows+'</table>'
    (output / 'index.html').write_text(page)
    return report


def run_panel(config, output, selected=None, execute=False, api=None, domain=None):
    output = Path(output).expanduser().resolve()
    cases, errors = [], []
    for index, raw in enumerate(config['cases']):
        try:
            case = normalized_case(raw, index, config)
            if not selected or case['id'] in selected:
                cases.append(case)
        except (ValueError, TypeError) as error:
            errors.append({'id': f'case-{index+1}', 'label': str(raw.get('label', '无效案例')) if isinstance(raw, dict) else '无效案例',
                'expected': 'unknown', 'business_result': 'unknown', 'acceptance_result': 'incomplete',
                'reason': str(error), 'metrics': {}, 'task_id': None, 'native_goal_id': None, 'native_status': None})
    if not execute:
        return {'execute': False, 'cases': cases, 'invalid_cases': errors,
                'message': 'Launch each selected scene first; --execute connects to the existing simulation owner.'}
    output.mkdir(parents=True, exist_ok=True)
    previous = read_json(output/'report.json', {}).get('cases', []) if (output/'report.json').is_file() else []
    replacing = {case['id'] for case in cases} | {case['id'] for case in errors}
    results = [result for result in previous if result.get('id') not in replacing] + list(errors)
    for case in cases:
        directory = output / (case['id']+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
        try:
            result = run_case(case, config, directory, api, domain)
        except Exception as error:
            warnings.warn(f'WARNING: case {case["id"]} failed: {error}; continuing independent cases')
            result = {'id': case['id'], 'label': case['label'], 'expected': case['expected'],
                'business_result': 'unknown', 'acceptance_result': 'incomplete', 'reason': str(error),
                'metrics': {}, 'task_id': None, 'native_goal_id': None, 'native_status': None}
        results.append(result)
        save_report(config, results, output)
    return save_report(config, results, output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare', help='Generate independently editable case scene files')
    prepare.add_argument('--config', type=Path, required=True)
    prepare.add_argument('--output', type=Path, required=True)
    prepare.add_argument('--source-map', type=Path, help='Import measured occupancy with home_scene instead of synthetic reference')
    run = commands.add_parser('run', help='Connect to the selected already-started simulation')
    run.add_argument('--config', type=Path, required=True)
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--case', '--cases', dest='cases', nargs='+')
    run.add_argument('--api')
    run.add_argument('--domain', type=int)
    run.add_argument('--execute', action='store_true')
    report = commands.add_parser('report', help='Rebuild HTML from saved results without ROS')
    report.add_argument('directory', type=Path)
    observer = commands.add_parser('_observe', help=argparse.SUPPRESS)
    observer.add_argument('--domain', type=int, required=True)
    observer.add_argument('--output', type=Path, required=True)
    observer.add_argument('--ready', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == 'prepare':
        config = load_config(args.config)
        if args.source_map:
            config['source_map'] = str(args.source_map.expanduser().resolve())
            config.pop('scene_path', None)
            config.pop('map', None)
        result = prepare_panel(config, args.output)
        print(json.dumps({'panel': str(args.output / 'panel.json'), 'cases': [case['id'] for case in result['cases']],
                          'preparation_errors': result['preparation_errors']}, ensure_ascii=False))
        return 0 if result['cases'] else 1
    if args.command == 'run':
        result = run_panel(load_config(args.config), args.output, args.cases, args.execute, args.api, args.domain)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if not args.execute or result['cases'] and all(case['acceptance_result'] == 'passed' for case in result['cases']) else 1
    if args.command == '_observe':
        observe(args.domain, args.output, args.ready)
        return 0
    data = read_json(args.directory / 'report.json', {})
    results = data.get('cases', [])
    if not results:
        results = [read_json(path) for path in sorted(args.directory.glob('*/result.json'))]
    save_report(data, results, args.directory)
    print(str((args.directory / 'index.html').resolve()))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
