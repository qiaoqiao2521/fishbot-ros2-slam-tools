#!/usr/bin/env python3
"""Observe or replay shared-world evidence with unchanged K physical scoring.

Never dispatch, cancel, reset, restart, or clean up ROS actions. Historical
replays write new private output; live observation requires an isolated domain.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import os
import re
import struct
import time

BASE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('original_cooperation_oracle', BASE / 'cooperation_oracle_base.py')
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
original_audit = oracle.driver_audit
original_score = oracle.score
original_topic_stamp = oracle.topic_stamp
options = None
STATUS_KINDS = {'nav_status': 'nav', 'dock_status': 'dock',
                'drive_on_heading_status': 'drive_on_heading'}
FEEDBACK_KINDS = {'nav_feedback': 'nav', 'dock_feedback': 'dock',
                  'drive_on_heading_feedback': 'drive_on_heading'}
LABEL_KINDS = {'Nav2': 'nav', 'Nav2停靠': 'dock', 'DriveOnHeading': 'drive_on_heading'}


def cargo_topic(cargo_id):
    if not isinstance(cargo_id, str) or re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', cargo_id) is None:
        raise ValueError('Named cargo IDs must be valid ROS topic components')
    return f'/cooperation/cargo/{cargo_id}/pose'


def topic_stamp(topic, payload):
    if topic.startswith('cargo:'):
        return oracle.stamp(payload['header']['stamp'])
    return original_topic_stamp(topic, payload)


def named_observer_node(base, cargo_ids):
    """Extend the existing read-only observer node and its recording callback."""
    class NamedObserver(base):
        def create_subscription(self, msg_type, topic, callback, qos, **kwargs):
            result = super().create_subscription(msg_type, topic, callback, qos, **kwargs)
            if topic == '/cooperation/cargo_pose':
                self.named_cargo_subscriptions = []
                for cargo_id in cargo_ids:
                    def named_callback(message, cargo_id=cargo_id):
                        return callback(message, name='cargo:'+cargo_id)
                    self.named_cargo_subscriptions.append(super().create_subscription(
                        msg_type, cargo_topic(cargo_id), named_callback, qos, **kwargs))
            return result
    return NamedObserver


def observe(args):
    """Reuse the original recorder, adding only configured independent poses."""
    path = getattr(args, 'business_manifest', None)
    if path is None:
        return oracle.observe(args)
    manifest = json.loads(Path(path).read_text())
    cargo_ids = list(manifest['business_entities']['cargo'])
    for cargo_id in cargo_ids:
        cargo_topic(cargo_id)
    args.publisher_inventory_topics = tuple(cargo_topic(cargo_id) for cargo_id in cargo_ids)
    import rclpy.node as node_module
    original_node = node_module.Node
    node_module.Node = named_observer_node(original_node, cargo_ids)
    try:
        return oracle.observe(args)
    finally:
        node_module.Node = original_node


def driver_audit():
    result = original_audit()
    tree = ast.parse(oracle.DRIVER.read_text())
    reset_method = next((item for cls in tree.body if isinstance(cls, ast.ClassDef) and cls.name == 'Physics'
                         for item in cls.body if isinstance(item, ast.FunctionDef) and item.name == 'reset_episode'), None)
    allowed = {'Physics.__init__', 'FrameWriter.run', 'Physics.reset_episode'}
    unexpected = [w for w in result['state_writes'] if w['scope'] not in allowed]
    result.update(no_runtime_physics_teleport=not unexpected,
                  no_task_runtime_teleport_source_scope=not unexpected,
                  allowed_init_and_isolated_render_only=sorted(allowed),
                  explicit_between_episode_reset={'method': 'Physics.reset_episode',
                    'present': reset_method is not None,
                    'line': reset_method.lineno if reset_method else None,
                    'method_sha256': hashlib.sha256(ast.unparse(reset_method).encode()).hexdigest() if reset_method else None,
                    'state_writes': [w for w in result['state_writes'] if w['scope'] == 'Physics.reset_episode'],
                    'scope_limit': 'Allowed only outside every task active window; runtime receipt and episode fence checked separately'},
                  unexpected_state_writes=unexpected)
    return result


def episode_id(raw):
    source = raw.get('source', {})
    values = [v for v in (raw.get('episode_id'), source.get('episode_id')) if v is not None]
    return values[0] if values and all(v == values[0] for v in values) else None


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def uuid_hex(value):
    return bytes(value).hex()


def extra_checks(records, marker_path, expected, *, reset_receipt=None, allow_initial_episode=False,
                 scope='transport', expected_outcome='success'):
    physics = [r for r in records if r['topic'] == 'physics']
    events = oracle.marker_events(records, marker_path)
    identifiers = [episode_id(r['payload']) for r in physics]
    identity = bool(identifiers) and bool(expected) and all(x == expected for x in identifiers)
    monotonic = {}
    for key in ('stamp', 'sequence', 'physics_steps'):
        values = [r['payload'].get(key) for r in physics]
        monotonic[key] = bool(values) and all(finite(x) for x in values) and all(b > a for a, b in zip(values, values[1:]))
    clocks = [r['source_stamp'] for r in records if r['topic'] == 'clock']
    monotonic['clock'] = bool(clocks) and all(finite(x) for x in clocks) and all(b > a for a, b in zip(clocks, clocks[1:]))
    contact_keys = ('arm_forbidden_contact_total', 'car_forbidden_contact_total',
                    'arm_forbidden_contact_count', 'car_forbidden_contact_count')
    contacts = bool(physics) and all(r['payload'].get(k) == 0 for r in physics for k in contact_keys)
    first_contacts = {k: physics[0]['payload'].get(k) if physics else None for k in contact_keys}
    reset_counts = [r['payload'].get('episode_reset', {}).get('count') for r in physics]
    reset_count_fixed = bool(reset_counts) and all(isinstance(x, int) and not isinstance(x, bool) for x in reset_counts) and len(set(reset_counts)) == 1
    windows = []
    prefix = 'dock' if scope == 'dock' else 'route' if scope == 'route' else 'full'
    for start in (e for e in events if e.get('kind') == prefix+'_started'):
        ends = [e for e in events if e.get('kind') == prefix+'_finished' and e.get('task_id') == start['task_id'] and e['wall_time'] >= start['wall_time']]
        end = min((e['wall_time'] for e in ends), default=None)
        items = [r for r in physics if start['wall_time'] <= r['received_wall_time'] <= (end or math.inf)]
        action_ids = set()
        terminal = {}
        for r in records:
            in_window = start['wall_time'] <= r['received_wall_time'] <= (end or math.inf) + 1
            if not in_window:
                continue
            if r['topic'] in FEEDBACK_KINDS:
                action_ids.add((FEEDBACK_KINDS[r['topic']], uuid_hex(r['payload']['goal_id']['uuid'])))
            if r['topic'] in STATUS_KINDS:
                kind = STATUS_KINDS[r['topic']]
                for s in r['payload']['status_list']:
                    key = (kind, uuid_hex(s['goal_info']['goal_id']['uuid']))
                    if s['status'] in (1, 2, 3):
                        action_ids.add(key)
                    if key in action_ids:
                        terminal[key] = s['status']
        dock_ids = [k for k in action_ids if k[0] == 'dock']
        native_success = bool(action_ids) and all(terminal.get(k) == 4 for k in action_ids)
        if scope == 'dock':
            native_success = native_success and len(dock_ids) == 1
        elif scope == 'route':
            native_success = native_success and not dock_ids and any(k[0] == 'nav' for k in action_ids)
        else:
            native_success = native_success and bool(dock_ids) and any(k[0] == 'nav' for k in action_ids)
        native_known = bool(action_ids) and all(terminal.get(k) in (4,5,6) for k in action_ids)
        native = native_success if expected_outcome == 'success' else native_known
        http = [r['payload'] for r in records if r['topic'] == 'http_state'
                and r['received_wall_time'] >= start['wall_time']
                and r['payload'].get('task', {}).get('id') == start['task_id']]
        strict_handles = scope == 'dock' or start.get('scope') in ('dock','transport','route')
        handle_ids=set();handle_terminal={};handle_cancel_times={};handle_bad=False
        for state in http:
            for action in state.get('native_actions',[]):
                if action.get('accepted') is not True:continue
                kind=LABEL_KINDS.get(action.get('label'))
                identifier=action.get('uuid')
                if kind is None or not isinstance(identifier,str) or len(identifier)!=32:
                    handle_bad=True;continue
                key=(kind,identifier);handle_ids.add(key)
                if action.get('result_known') is True:handle_terminal[key]=action.get('status')
                if finite(action.get('cancel_requested_wall_time')):handle_cancel_times[key]=action['cancel_requested_wall_time']
        handles_bound=(not handle_bad and bool(handle_ids) and handle_ids==action_ids
                       and all(handle_terminal.get(key)==terminal.get(key) for key in action_ids))
        cancel_events=[e for e in events if e.get('kind')=='cancel_requested' and e.get('task_id')==start['task_id']]
        cancel_bound=all(sum(key[1]==e.get('native_uuid')
                             and handle_cancel_times.get(key)==e.get('wall_time') for key in action_ids)==1
                         for e in cancel_events)
        if strict_handles:
            native = native and handles_bound and cancel_bound
        terminal_status = http[-1]['task'].get('status') if http else None
        terminal_task = terminal_status == 'succeeded' if expected_outcome == 'success' else terminal_status in ('canceled','failed')
        windows.append({'task_id': start['task_id'], 'wall_start': start['wall_time'], 'wall_end': end,
                        'first_source_stamp': items[0]['source_stamp'] if items else None,
                        'last_source_stamp': items[-1]['source_stamp'] if items else None,
                        'episode_fixed': bool(items) and all(episode_id(x['payload']) == expected for x in items),
                        'native_actions': [{'kind': k[0], 'uuid': k[1], 'terminal_status': terminal.get(k)} for k in sorted(action_ids)],
                        'all_native_success': native_success, 'native_terminal_known':native_known,
                        'native_expected_outcome':native,'terminal_task_success':terminal_status == 'succeeded',
                        'accepted_handle_uuid_bound':handles_bound if strict_handles else None,
                        'cancel_marker_uuid_and_actual_time_bound':cancel_bound if strict_handles else None,
                        'terminal_task_expected_outcome':terminal_task,'terminal_task_status':terminal_status,
                        'closed': end is not None})
    receipt = None
    receipt_ok = allow_initial_episode
    if reset_receipt:
        receipt = json.loads(Path(reset_receipt).read_text())
        if 'reset_receipt' in receipt:
            receipt = receipt['reset_receipt']
        stamp = receipt.get('reset_stamp')
        receipt_ok = (receipt.get('status') == 'succeeded' and receipt.get('new_episode_id') == expected
                      and finite(stamp) and bool(physics) and stamp < physics[0]['source_stamp']
                      and all(w['first_source_stamp'] is not None and stamp < w['first_source_stamp'] for w in windows))
    observed_receipts = []
    for r in records:
        if r['topic'] == 'reset_receipt':
            observed_receipts.append({'received_wall_time': r['received_wall_time'], **r['payload']})
        if r['topic'] == 'physics' and isinstance(r['payload'].get('reset_receipt'), dict):
            observed_receipts.append({'received_wall_time': r['received_wall_time'], **r['payload']['reset_receipt']})
        reset_info = r['payload'].get('episode_reset', {}) if r['topic'] == 'physics' else {}
        if finite(reset_info.get('stamp')) and reset_info.get('count', 0) > 0:
            observed_receipts.append({'received_wall_time': r['received_wall_time'],
                                      'new_episode_id': episode_id(r['payload']),
                                      'reset_stamp': reset_info['stamp']})
    receipt_inside_task = []
    for item in observed_receipts:
        stamp = item.get('reset_stamp')
        for w in windows:
            if finite(stamp) and w['first_source_stamp'] is not None and w['last_source_stamp'] is not None and w['first_source_stamp'] <= stamp <= w['last_source_stamp']:
                receipt_inside_task.append(item)
    all_windows = bool(windows) and all(w['episode_fixed'] and w['native_expected_outcome'] and w['terminal_task_expected_outcome'] and w['closed'] for w in windows)
    return {'expected_episode_id': expected, 'episode_identity_fixed': identity,
            'source_monotonic': monotonic, 'first_contact_counters': first_contacts,
            'reset_count_fixed': reset_count_fixed,
            'reset_count': reset_counts[0] if reset_counts else None,
            'all_episode_contact_totals_zero': contacts, 'windows': windows,
            'reset_receipt': receipt, 'reset_receipt_precedes_collection_and_tasks': bool(receipt_ok),
            'reset_receipts_inside_task': receipt_inside_task,
            'original_full_score_reused':scope == 'transport','scope':scope,'expected_outcome':expected_outcome,
            'passed': identity and all(monotonic.values()) and contacts and reset_count_fixed and bool(receipt_ok) and not receipt_inside_task and all_windows}



def transport_checks(samples, audit, attempts, events):
    """Independently apply the already-shipped continuous handoff contract."""
    windows = []
    for attempt in attempts:
        start = attempt['started_wall_time']
        ends = [event['wall_time'] for event in events
                if event.get('kind') == 'full_finished'
                and event.get('task_id') == attempt['task_id']
                and event['wall_time'] >= start]
        end = min(ends, default=math.inf)
        placed = attempt['released_full_footprint_supported_and_relative_rest']['first_pass_stamp']
        handoff = oracle.Gate(1.)
        first_move = None
        premature = False
        violations = []
        violation_count = 0
        count = 0
        for item in samples:
            if not start <= item['wall_time'] <= end or placed is None or item['stamp'] < placed:
                continue
            raw = item['raw']
            valid = item['independent_crosscheck'] and raw.get('finite') is True
            quiet = item['car_speed'] < .01 and abs(item['yaw_rate']) < .01
            footprint = all(abs(item['relative'][axis])+item['extents'][axis] <= .058 for axis in range(2))
            retained = (abs(item['relative'][0]) <= .047 and abs(item['relative'][1]) <= .047
                        and -.002 <= item['relative'][2] <= .04
                        and raw.get('cargo_tray_floor_contact') is True and footprint)
            released = retained and max(item['forces']) < .02 and oracle.norm(raw['cargo']['velocity_relative_tray']) < .002
            arm_home = (len(raw['q6']) == 6 and len(raw['qvel6']) == 6
                        and all(finite(value) for value in raw['q6']+raw['qvel6'])
                        and max(abs(value-target) for value,target in zip(raw['q6'],audit['home_q6'])) < .02
                        and oracle.norm(raw['qvel6']) < .05)
            if first_move is None:
                handoff.update(item['stamp'], valid and raw.get('car_hold') is True and quiet and arm_home and released)
                if not quiet:
                    first_move = item['stamp']
                    premature = handoff.first_pass is None or handoff.first_pass > item['stamp']
            if handoff.first_pass is not None:
                count += 1
                if not (valid and arm_home and retained):
                    violation_count += 1
                    if len(violations) < 40:
                        violations.append({'stamp': item['stamp'], 'arm_home_quiet': arm_home,
                                           'cargo_retained_full_footprint': retained, 'independent_crosscheck': valid})
        windows.append({'task_id': attempt['task_id'], 'continuous_handoff': handoff.result(),
                        'first_true_motion_stamp': first_move, 'motion_before_handoff': premature,
                        'transport_samples': count, 'violation_samples_total': violation_count,
                        'violation_samples_preview': violations,
                        'passed': handoff.first_pass is not None and first_move is not None
                                  and not premature and count > 0 and violation_count == 0})
    return {'windows': windows, 'controller_helpers_imported': False,
            'passed': bool(windows) and all(window['passed'] for window in windows)}


def delivery_checks(records, samples, audit, attempts, events, *, marker_prefix='full'):
    """Bind each declared task destination to its native UUID and true stop.

    The bridge freezes the sent goal before send_goal_async. HTTP is evidence
    for that request and handle binding, never authority for physical success.
    The observer independently receives the same UUID's ROS status/feedback
    and standard truth/cargo poses. Historical captures without any task-level
    destination declaration retain the original K score.
    """
    def pose(value):
        if not isinstance(value, dict) or not all(finite(value.get(k)) for k in ('x', 'y', 'yaw')):
            return None
        return {k: float(value[k]) for k in ('x', 'y', 'yaw')}

    def motion(value):
        keys = ('distance_m', 'speed_m_s', 'time_allowance_s')
        if (not isinstance(value, dict) or value.get('type') != 'drive_on_heading'
                or any(not finite(value.get(key)) or value[key] <= 0 for key in keys)):
            return None
        try:
            speed = struct.unpack('<f', struct.pack('<f', value['speed_m_s']))[0]
        except (OverflowError, struct.error):
            return None
        if not math.isfinite(speed) or speed <= 0 or round(value['time_allowance_s']*1e9) < 1:
            return None
        return {'type': 'drive_on_heading', 'distance_m': float(value['distance_m']),
                'speed_m_s': speed, 'time_allowance_s': float(value['time_allowance_s'])}

    def body_goal(value):
        if value is None:
            return None
        sec, nanosec = divmod(round(value['time_allowance_s']*1e9), 1000000000)
        return {'target': {'x': value['distance_m'], 'y': 0., 'z': 0.},
                'speed': value['speed_m_s'], 'time_allowance': {'sec': sec, 'nanosec': nanosec}}

    def observed_body_goal(value):
        if not isinstance(value, dict) or set(value) != {'target', 'speed', 'time_allowance'}:
            return None
        point, duration = value['target'], value['time_allowance']
        if (not isinstance(point, dict) or set(point) != {'x', 'y', 'z'}
                or any(not finite(point[key]) for key in point) or not finite(value['speed'])
                or not isinstance(duration, dict) or set(duration) != {'sec', 'nanosec'}
                or any(type(duration[key]) is not int for key in duration)
                or not 0 <= duration['nanosec'] < 1000000000 or duration['sec'] < 0):
            return None
        return value

    target_keys = ('expected_delivery_pose', 'delivery_pose', 'requested_delivery_pose')
    declared = any(e.get('kind') == marker_prefix+'_started' and any(k in e for k in target_keys) for e in events)
    declared |= any(r['topic'] == 'http_state' and 'delivery_pose' in r['payload'].get('task', {}) for r in records)
    results = []
    for attempt in attempts:
        task_id, start = attempt['task_id'], attempt['started_wall_time']
        starts = [e for e in events if e.get('kind') == marker_prefix+'_started'
                  and e.get('task_id') == task_id and e['wall_time'] == start]
        event = starts[0] if len(starts) == 1 else {}
        ends = [e['wall_time'] for e in events if e.get('kind') == marker_prefix+'_finished'
                and e.get('task_id') == task_id and e['wall_time'] >= start]
        end = min(ends, default=math.inf)
        states = [r['payload'] for r in records if r['topic'] == 'http_state'
                  and start <= r['received_wall_time'] <= end + 1.
                  and r['payload'].get('task', {}).get('id') == task_id]
        required = any(k in event for k in target_keys) or any('delivery_pose' in state.get('task', {}) for state in states)
        if not required:
            results.append({'task_id': task_id, 'required': False, 'passed': True,
                            'reason': 'Historical capture has no task destination declaration; original K score retained.'})
            continue
        target = pose(event.get('expected_delivery_pose', event.get('delivery_pose')))
        episode = event.get('episode_id')
        binding = (len(starts) == 1 and len(ends) == 1 and target is not None
                   and isinstance(episode, str) and bool(episode) and bool(states))
        for key in ('expected_delivery_pose', 'delivery_pose'):
            if key in event:
                binding &= pose(event[key]) == target and target is not None
        if event.get('requested_delivery_pose') is not None:
            binding &= pose(event['requested_delivery_pose']) == target and target is not None
        for state in states:
            binding &= (state.get('episode_id') == episode
                        and pose(state.get('task', {}).get('delivery_pose')) == target and target is not None)
        approach_values = event.get('expected_delivery_approach_poses',
            states[0].get('task', {}).get('delivery_approach_poses', []) if states else [])
        approaches = [pose(value) for value in approach_values] if isinstance(approach_values, list) else None
        binding &= approaches is not None and all(value is not None for value in approaches)
        if 'requested_delivery_approach_poses' in event:
            binding &= event['requested_delivery_approach_poses'] == approaches
        for state in states:
            binding &= state.get('task', {}).get('delivery_approach_poses', []) == approaches
        manifests = [r['payload'].get('source', {}).get('manifest', {}) for r in records
                     if r['topic'] == 'physics' and episode_id(r['payload']) == episode]
        declarations = [m['egress_pose'] for m in manifests
                        if marker_prefix!='route' and m.get('egress_pose') is not None]
        egress_declared = bool(declarations)
        def egress_pose(value):
            return pose(dict(zip(('x', 'y', 'yaw'), value))
                        if isinstance(value, (list, tuple)) and len(value) == 3 else value)
        egress = egress_pose(declarations[0]) if declarations else None
        binding &= all(egress_pose(value) == egress and egress is not None for value in declarations)
        motion_declarations = [m['egress_motion'] for m in manifests
                               if marker_prefix!='route' and m.get('egress_motion') is not None]
        motion_declared = bool(motion_declarations)
        egress_motion = motion(motion_declarations[0]) if motion_declarations else None
        binding &= all(motion(value) == egress_motion and egress_motion is not None
                       for value in motion_declarations)
        for state in states:
            task_egress = state.get('task', {}).get('egress_pose')
            binding &= (pose(task_egress) == egress if egress_declared else task_egress is None)
            task_motion = state.get('task', {}).get('egress_motion')
            binding &= (motion(task_motion) == egress_motion if motion_declared else task_motion is None)
        expected_goals = [{'label': 'Nav2', 'goal_pose': goal, 'goal_motion': None}
                          for goal in (approaches or [])+[target]]
        if motion_declared:
            expected_goals.insert(0, {'label': 'DriveOnHeading', 'goal_pose': None,
                                      'goal_motion': body_goal(egress_motion)})
        elif egress_declared:
            expected_goals.insert(0, {'label': 'Nav2', 'goal_pose': egress, 'goal_motion': None})
        carried = {}
        last_nav = None
        goal_frozen = True
        for state in states:
            accepted = [a for a in state.get('native_actions', [])
                        if a.get('accepted') is True]
            if accepted:
                last_nav = accepted[-1]
            snapshot_ids = []
            for action in accepted:
                if action.get('carrying') is not True:
                    continue
                identifier = action.get('uuid')
                identifier_ok = (isinstance(identifier, str) and len(identifier) == 32
                                 and all(ch in '0123456789abcdef' for ch in identifier))
                goal = {'label': action.get('label'), 'goal_pose': pose(action.get('goal_pose')),
                        'goal_motion': observed_body_goal(action.get('goal_motion'))}
                goal_frozen &= identifier_ok
                if goal['label'] == 'DriveOnHeading':
                    goal_frozen &= action.get('goal_pose') is None and isinstance(goal['goal_motion'], dict)
                else:
                    goal_frozen &= goal['label'] == 'Nav2' and goal['goal_pose'] is not None
                if identifier_ok:
                    snapshot_ids.append(identifier)
                    if identifier in carried:
                        goal_frozen &= carried[identifier] == goal
                    carried[identifier] = goal
            goal_frozen &= (len(snapshot_ids) == len(set(snapshot_ids))
                            and snapshot_ids == list(carried)[:len(snapshot_ids)])
        route_ids = list(carried)
        goal_frozen &= (len(route_ids) == len(expected_goals)
                        and list(carried.values()) == expected_goals
                        and target is not None and (not motion_declared or egress_motion is not None))
        native_id = route_ids[-1] if len(route_ids) == len(expected_goals) else None
        last_nav_is_delivery = bool(native_id and last_nav and last_nav.get('carrying') is True
                                    and last_nav.get('uuid') == native_id and last_nav.get('label') == 'Nav2')
        observed = {identifier: {'active_wall_time': None, 'terminal_status': None,
                                'success_wall_time': None} for identifier in route_ids}
        for record in sorted(records, key=lambda r: r.get('received_wall_time', 0.)):
            if not start <= record.get('received_wall_time', 0.) <= end + 1.:
                continue
            wall = record['received_wall_time']
            if record['topic'] in FEEDBACK_KINDS:
                identifier = uuid_hex(record['payload']['goal_id']['uuid'])
                seen = observed.get(identifier)
                if (seen is not None and FEEDBACK_KINDS[record['topic']] == LABEL_KINDS.get(carried[identifier]['label'])
                        and seen['active_wall_time'] is None):
                    seen['active_wall_time'] = wall
            if record['topic'] in STATUS_KINDS:
                for status in record['payload'].get('status_list', []):
                    identifier = uuid_hex(status['goal_info']['goal_id']['uuid'])
                    seen = observed.get(identifier)
                    if (seen is not None and STATUS_KINDS[record['topic']] == LABEL_KINDS.get(carried[identifier]['label'])):
                        if status['status'] in (1, 2, 3) and seen['active_wall_time'] is None:
                            seen['active_wall_time'] = wall
                        seen['terminal_status'] = status['status']
                        if status['status'] == 4 and seen['success_wall_time'] is None:
                            seen['success_wall_time'] = wall
        route_success = all(seen['active_wall_time'] is not None and seen['terminal_status'] == 4
                            for seen in observed.values())
        route_order = all(observed[earlier]['success_wall_time'] is not None
                          and observed[later]['active_wall_time'] is not None
                          and observed[earlier]['success_wall_time'] <= observed[later]['active_wall_time']
                          for earlier, later in zip(route_ids, route_ids[1:]))
        active = bool(native_id and observed[native_id]['active_wall_time'] is not None)
        terminal = observed[native_id]['terminal_status'] if native_id else None
        native = bool(native_id and goal_frozen and last_nav_is_delivery and route_success and route_order)
        # Old captures retain the old score. New factory requests declare the
        # route and require a complete shared-budget receipt, not N x 120 s.
        budget_required = ('expected_delivery_approach_poses' in event or
                           any(state.get('task', {}).get('delivery_route') is not None for state in states))
        budgets = [state['task']['delivery_route'] for state in states
                   if isinstance(state.get('task', {}).get('delivery_route'), dict)]
        receipt = budgets[-1] if budgets else {}
        elapsed = receipt.get('elapsed_wall_s')
        route_native = route_ids[1:] if egress_declared or motion_declared else route_ids
        active_times = [observed[identifier]['active_wall_time'] for identifier in route_native]
        final_success = observed[native_id]['success_wall_time'] if native_id else None
        independent_span = (final_success-min(active_times) if final_success is not None
                            and active_times and all(value is not None for value in active_times) else None)
        budget_passed = (not budget_required or bool(
            receipt.get('budget_wall_s') == 120. and receipt.get('clock') == 'monotonic_wall'
            and receipt.get('boundary') == 'after_required_egress_through_final_nav_stop_and_hold'
            and receipt.get('status') == 'succeeded' and finite(elapsed) and 0 <= elapsed <= 120.
            and receipt.get('goals') == (approaches or [])+[target]
            and receipt.get('completed_legs') == len((approaches or [])+[target])
            and finite(receipt.get('started_wall_time')) and finite(receipt.get('finished_wall_time'))
            and start <= receipt['started_wall_time'] <= receipt['finished_wall_time'] <= end
            and independent_span is not None and 0 <= independent_span <= 120.))
        gate = oracle.Gate(1.)
        placed = (attempt.get('route_started_source_stamp') if marker_prefix=='route' else
                  attempt.get('released_full_footprint_supported_and_relative_rest', {}).get('first_pass_stamp'))
        previous = last = None
        last_valid = False
        errors = None
        for item in samples:
            if not start <= item['wall_time'] <= end or placed is None or item['stamp'] < placed:
                continue
            raw = item['raw']
            errors = ({'position_m': math.hypot(item['car'][0] - target['x'], item['car'][1] - target['y']),
                       'yaw_rad': oracle.yaw_error(item['car_yaw'], target['yaw'])} if target else None)
            retained = (all(abs(item['relative'][i]) + item['extents'][i] <= .058 for i in range(2))
                        and abs(item['relative'][0]) <= .047 and abs(item['relative'][1]) <= .047
                        and -.002 <= item['relative'][2] <= .04 and raw.get('cargo_tray_floor_contact') is True)
            arm_home = (len(raw.get('q6', [])) == 6 and len(raw.get('qvel6', [])) == 6
                        and max(abs(a-b) for a, b in zip(raw['q6'], audit['home_q6'])) < .02
                        and oracle.norm(raw['qvel6']) < .05)
            cargo_speed = math.inf
            if previous and 0 < item['stamp'] - previous['stamp'] <= .1:
                cargo_speed = oracle.norm([item['cargo'][i] - previous['cargo'][i] for i in range(3)]) / (item['stamp'] - previous['stamp'])
            last_valid = bool(errors and errors['position_m'] <= .04 and errors['yaw_rad'] <= .05
                and item['independent_crosscheck'] and raw.get('finite') is True
                and episode_id(raw) == episode and raw.get('car_hold') is True
                and item['car_speed'] < .01 and abs(item['yaw_rate']) < .01 and arm_home and retained
                and len(item['forces']) >= 2 and max(item['forces']) < .02
                and oracle.norm(raw.get('cargo', {}).get('velocity_relative_tray', [math.inf])) < .002
                and cargo_speed < .005)
            gate.update(item['stamp'], last_valid)
            previous = last = item
        settled = bool(last and last_valid and gate.started is not None and last['stamp'] - gate.started >= 1.)
        results.append({'task_id': task_id, 'episode_id': episode, 'required': True,
            'expected_delivery_pose': target, 'task_request_and_acceptance_match': bool(binding),
            'expected_delivery_approach_poses': approaches,
            'delivery_route_budget': {'required': budget_required, 'passed': budget_passed,
                                      'receipt': receipt, 'independent_native_span_wall_s': independent_span,
                                      'bridge_forwarding_is_not_consumption_ack': True},
            'carrying_nav_uuid': native_id, 'carrying_nav_sent_goal_matches': bool(goal_frozen and native_id),
            'expected_egress_pose': egress, 'egress_required': egress_declared or motion_declared,
            'expected_egress_motion': egress_motion,
            'egress_map_pose_role': 'nominal_staging_reference_not_native_body_goal' if motion_declared else 'native_map_goal',
            'carrying_nav_route': [{'uuid': identifier, **carried[identifier], **observed[identifier]}
                                   for identifier in route_ids],
            'carrying_nav_route_order_confirmed': route_order,
            'last_nav_is_delivery': last_nav_is_delivery, 'native_uuid_active_observed': active,
            'native_uuid_terminal_status': terminal, 'native_uuid_success_independently_observed': native,
            'goal_request_evidence': 'bridge_pre_send_frozen_goal_and_accepted_handle_HTTP_snapshot',
            'native_status_evidence': 'independently_subscribed_ROS_action_status_and_feedback',
            'goal_request_independently_observed': False, 'native_goal_consumption_ack_claimed': False,
            'final_true_pose_error': errors, 'final_true_pose_and_cargo_stop': gate.result(),
            'position_tolerance_m': .04, 'yaw_tolerance_rad': .05, 'continuous_final_dwell_s': 1.,
            'threshold_basis': 'original_physical_dock_pose_tolerances_and_original_final_rest_dwell',
            'passed': bool(binding and native and settled and budget_passed)})
    return {'required': bool(declared), 'attempts': results,
            'passed': (bool(results) and all(r['passed'] for r in results)) if declared else True,
            'original_K_checks_remain_required': True, 'controller_helpers_imported': False}


def percentile(values, fraction=.95):
    values = sorted(value for value in values if finite(value))
    return values[min(len(values)-1, math.ceil(fraction*len(values))-1)] if values else None


def cleanup_checks(records, samples, events, task_id):
    """Require independently observed quiet, hold, guard ACK and native terminal."""
    proofs = [e for e in events if e.get('kind') == 'cleanup_checked' and e.get('task_id') == task_id]
    if not proofs:
        return {'passed':False,'reason':'No explicit cleanup proof marker'}
    end = proofs[-1]['wall_time']
    eligible = [s for s in samples if s['wall_time'] <= end]
    quiet = oracle.Gate(.7)
    for item in eligible:
        raw = item['raw']; guard = raw.get('docking_guard', {})
        valid = (item['independent_crosscheck'] and raw.get('finite') is True
                 and raw.get('car_hold') is True and item['car_speed'] < .01
                 and abs(item['yaw_rate']) < .01 and oracle.norm(raw.get('qvel6',[math.inf])) < .05
                 and guard.get('enabled') is False and guard.get('tripped') is False)
        quiet.update(item['stamp'], valid)
    last = eligible[-1] if eligible else None
    clocks = [r for r in records if r['topic'] == 'clock' and r['received_wall_time'] <= end]
    source_age = clocks[-1]['source_stamp']-last['stamp'] if last and clocks else None
    received_age = end-last['wall_time'] if last else None
    native = {}
    for record in records:
        if record['topic'] in STATUS_KINDS and record['received_wall_time'] <= end:
            for item in record['payload']['status_list']:
                native[(record['topic'],uuid_hex(item['goal_info']['goal_id']['uuid']))] = item['status']
    terminal = bool(native) and all(status in (4,5,6) for status in native.values())
    fresh = finite(source_age) and -.1 <= source_age <= .25 and finite(received_age) and 0 <= received_age <= .5
    # An earlier quiet dwell does not certify a later moving/faulted plant.
    last_valid = bool(last and last['raw'].get('car_hold') is True
                      and last['car_speed'] < .01 and abs(last['yaw_rate']) < .01
                      and last['raw'].get('docking_guard',{}).get('enabled') is False
                      and last['raw'].get('docking_guard',{}).get('tripped') is False)
    enabled=[s['stamp'] for s in eligible if s['raw'].get('docking_guard',{}).get('enabled') is True]
    disabled_after_enabled=bool(enabled and last and last['stamp']>max(enabled))
    return {'passed':quiet.first_pass is not None and quiet.started is not None
            and last is not None and last['stamp']-quiet.started >= .7 and fresh and terminal and last_valid and disabled_after_enabled,
            'continuous_quiet':quiet.result(),'received_age_s':received_age,'source_age_s':source_age,
            'native_terminal_known':terminal,'guard_disabled_after_enabled':disabled_after_enabled,
            'native_actions':[{'topic':key[0],'uuid':key[1],'status':status}
                for key,status in sorted(native.items())],'proof_wall_time':end}


def dock_checks(records, samples, audit, events, *, expected_outcome='success'):
    attempts = []
    for event in events:
        if event.get('kind') != 'dock_started':
            continue
        ends = [e['wall_time'] for e in events if e.get('kind') == 'dock_finished'
                and e.get('task_id') == event['task_id'] and e['wall_time'] >= event['wall_time']]
        end = min(ends, default=None)
        episode = [s for s in samples if event['wall_time'] <= s['wall_time'] <= (end or math.inf)]
        # Read the existing K predicate; full transport remains unclaimed.
        original = oracle.full_score(episode, audit)
        clean = cleanup_checks(records,samples,events,event['task_id'])
        first=original['dock_true_pose_and_stop']['first_pass_stamp']
        dwell=[s for s in episode if first is not None and first-.7 <= s['stamp'] <= first]
        errors = [math.hypot(s['car'][0]-audit['dock_pose'][0],s['car'][1]-audit['dock_pose'][1])
                  for s in dwell if s['car_speed'] < .01 and abs(s['yaw_rate']) < .01]
        yaw_errors = [oracle.yaw_error(s['car_yaw'],audit['dock_pose'][2])
                      for s in dwell if s['car_speed'] < .01 and abs(s['yaw_rate']) < .01]
        cancellations = [e for e in events if e.get('kind') == 'cancel_requested'
                         and e.get('task_id') == event['task_id']]
        cancellation = oracle.cancellation_score(records,samples,cancellations[-1],None) if cancellations else None
        physical_ok = original['forbidden_contacts']['passed'] and original['independent_pose_crosschecks']['passed']
        completion = expected_outcome == 'success' and original['dock_true_pose_and_stop']['passed']
        safety = expected_outcome == 'safe_cancel' and cancellation is not None and cancellation['passed']
        attempts.append({'task_id':event['task_id'],'started_wall_time':event['wall_time'],'finished_wall_time':end,
            'dock_true_pose_and_stop':original['dock_true_pose_and_stop'],
            'forbidden_contacts':original['forbidden_contacts'],'independent_pose_crosschecks':original['independent_pose_crosschecks'],
            'cleanup':clean,'cancellation':cancellation,'expected_outcome':expected_outcome,
            'task_completion_passed':bool(completion and physical_ok and clean['passed'] and end is not None),
            'expected_safety_passed':bool(safety and physical_ok and clean['passed'] and end is not None),
            'stationary_position_error_p95_m':percentile(errors),'stationary_yaw_error_p95_rad':percentile(yaw_errors),
            'full_transport_claimed':False,'passed':bool((completion or safety) and physical_ok and clean['passed'] and end is not None)})
    return {'attempts':attempts,'passed':bool(attempts) and all(item['passed'] for item in attempts)}


def observation_metrics(records, samples, audit):
    """Compare raw standard observations with independently received truth."""
    poses = {r['source_stamp']:r for r in records if r['topic'] == 'station_pose'}
    diagnostics = [r for r in records if r['topic'] == 'station_detection']
    position_errors=[]; angle_errors=[]; paired=detected=misses=0
    sample_by_stamp = sorted(samples,key=lambda s:s['stamp'])
    import bisect
    for record in diagnostics:
        statuses=record['payload'].get('status',[])
        if len(statuses) != 1:
            continue
        metadata={item['key']:item['value'] for item in statuses[0].get('values',[])}
        if metadata.get('detected') != 'true':
            misses += 1; continue
        detected += 1
        pose=poses.get(record['source_stamp'])
        if pose is None or pose['payload']['header'] != record['payload']['header']:
            continue
        paired += 1
        index=bisect.bisect_left(sample_by_stamp,record['source_stamp'],key=lambda s:s['stamp'])
        choices=sample_by_stamp[max(0,index-1):index+1]
        if not choices:
            continue
        truth=min(choices,key=lambda s:abs(s['stamp']-record['source_stamp']))
        if abs(truth['stamp']-record['source_stamp']) > .04:
            continue
        relative=pose['payload']['pose']['pose']; p=oracle.point(relative)
        heading=audit['native_dock_pose'][2]-oracle.yaw(oracle.quaternion(relative))
        c,s=math.cos(heading),math.sin(heading)
        estimate=[audit['native_dock_pose'][0]-c*p[0]+s*p[1],audit['native_dock_pose'][1]-s*p[0]-c*p[1]]
        position_errors.append(math.hypot(estimate[0]-truth['car'][0],estimate[1]-truth['car'][1]))
        angle_errors.append(oracle.yaw_error(heading,truth['car_yaw']))
    return {'raw_pose_count':len(poses),'raw_diagnostic_count':len(diagnostics),'detected_count':detected,
        'miss_count':misses,'exact_pair_count':paired,'independent_error_sample_count':len(position_errors),
        'observation_position_error_p95_m':percentile(position_errors),'observation_yaw_error_p95_rad':percentile(angle_errors),
        'camera_metadata_count':sum(r['topic']=='camera_metadata' for r in records),
        'vision_quality_count':sum(r['topic']=='vision_quality' for r in records),
        'admission_decisions_are_native_consumption_ack':False}


def camera_checks(records, expected_episode):
    physics=next((r['payload'] for r in records if r['topic']=='physics'),{})
    source=physics.get('source',{});config=source.get('manifest',{}).get('station_camera',{})
    expected={'scene_sha256':source.get('scene_sha256'),'manifest_sha256':source.get('manifest_sha256'),
              'episode_id':expected_episode}
    images={r['source_stamp']:r for r in records if r['topic']=='camera_image'}
    infos={r['source_stamp']:r for r in records if r['topic']=='camera_info'}
    metadata=[r for r in records if r['topic']=='camera_metadata'];quality=[r for r in records if r['topic']=='vision_quality']
    pairs=bad=unmatched=0;sequences=[];capture_ages=[];source_ages=[];inference=[];reasons={}
    for record in metadata:
        payload=record['payload'];statuses=payload.get('status',[])
        if len(statuses)!=1:bad+=1;continue
        fields={item['key']:item['value'] for item in statuses[0].get('values',[])}
        identity_ok=all(isinstance(value,str) and fields.get(key)==value for key,value in expected.items())
        identity_ok &= payload.get('header',{}).get('frame_id')=='cooperation_camera_optical_frame'
        identity_ok &= statuses[0].get('hardware_id')=='cooperation_camera'
        identity_ok &= not any(key in fields for key in ('car_pose','cargo_pose','qpos','truth_pose'))
        try:
            sequence=int(fields.get('sequence',''));capture=int(fields.get('capture_steady_ns',''))
            identity_ok &= sequence>0 and capture>0
        except (TypeError,ValueError):identity_ok=False
        if not identity_ok:bad+=1;continue
        sequences.append(sequence)
        image=images.get(record['source_stamp']);info=infos.get(record['source_stamp'])
        if image and info and image['payload']['header']==info['payload']['header']==payload['header']:
            image_payload=image['payload'];info_payload=info['payload']
            calibrated=(image_payload.get('encoding')=='rgb8'
                and image_payload.get('width')==info_payload.get('width')==config.get('width')
                and image_payload.get('height')==info_payload.get('height')==config.get('height')
                and info_payload.get('k')==config.get('k') and info_payload.get('d')==config.get('d'))
            if calibrated:pairs+=1
            else:bad+=1
        else:unmatched+=1
    for record in quality:
        for status in record['payload'].get('status',[]):
            fields={}
            for item in status.get('values',[]):
                try:fields[item['key']]=json.loads(item['value'])
                except (TypeError,ValueError):fields[item['key']]=item['value']
            if any(fields.get(key)!=value for key,value in expected.items()):bad+=1
            reason=str(fields.get('reason',status.get('message','unknown')));reasons[reason]=reasons.get(reason,0)+1
            for key,target in (('capture_age_s',capture_ages),('source_age_s',source_ages),('inference_duration_s',inference)):
                if finite(fields.get(key)):target.append(fields[key])
    monotonic=bool(sequences) and all(b>a for a,b in zip(sequences,sequences[1:]))
    return {'passed':bool(config) and pairs>0 and bool(quality) and bad==0 and monotonic,
        'exact_calibrated_image_metadata_pairs':pairs,'bad_identity_or_calibration_count':bad,
        'metadata_sequence_monotonic':monotonic,'quality_count':len(quality),'quality_reasons':reasons,
        'capture_age_p95_s':percentile(capture_ages),'source_age_p95_s':percentile(source_ages),
        'inference_duration_p95_s':percentile(inference),'quality_is_probability':False,
        'metadata_count':len(metadata),'unmatched_image_info_metadata_count':unmatched,
        'complete_rgb_pairing_claimed':False,'expected_camera_sample_coverage':'unknown',
        'native_consumption_ack_claimed':False,'pixel_bytes_recorded_in_oracle':False}


def camera_artifacts(directory):
    """Read the existing runner layout; missing or partial logs stay explicit."""
    root=Path(directory).resolve().parent/'runtime'/'vision'
    result={'directory':str(root),'renderer':[],'detector':[], 'read_errors':{}, 'missing':[], 'sha256':{}}
    for key,name in (('renderer','camera.jsonl'),('detector','vision.jsonl')):
        path=root/name
        if not path.is_file():
            result['missing'].append(name);continue
        try:
            digest=hashlib.sha256()
            with path.open('rb') as stream:
                for line in stream:
                    digest.update(line)
                    try:
                        value=json.loads(line)
                        if not isinstance(value,dict):raise ValueError('camera artifact must be an object')
                        result[key].append(value)
                    except (ValueError,TypeError):
                        result['read_errors'][name]=result['read_errors'].get(name,0)+1
            result['sha256'][name]=digest.hexdigest()
        except OSError as error:
            result['read_errors'][name]=str(error)
    result['readback']='missing' if result['missing'] else 'partial' if result['read_errors'] else 'complete'
    return result


def camera_frame_key(fields, source_stamp):
    """Join original source stamps at nanosecond precision, without restamping."""
    sequence=fields.get('sequence')
    if isinstance(sequence,str) and sequence.isdigit():sequence=int(sequence)
    if type(sequence) is not int or sequence<=0 or not finite(source_stamp) or source_stamp<=0:
        return None
    identity=tuple(fields.get(key) for key in ('scene_sha256','manifest_sha256','episode_id'))
    if not all(isinstance(value,str) and value for value in identity):return None
    return (*identity,sequence,int(round(source_stamp*1e9)))


def diagnostic_fields(record, *, camera=False):
    payload=record.get('payload',{});statuses=payload.get('status',[])
    if len(statuses)!=1:return None
    pairs=statuses[0].get('values',[])
    try:
        fields={item['key']:item['value'] if camera else json.loads(item['value']) for item in pairs}
        if len(fields)!=len(pairs):return None
        header=payload['header'];stamp=header['stamp']
        if type(stamp['sec']) is not int or type(stamp['nanosec']) is not int or not 0<=stamp['nanosec']<1_000_000_000:return None
        source=stamp['sec']+stamp['nanosec']*1e-9
        if header['frame_id']!=('cooperation_camera_optical_frame' if camera else 'base_footprint'):return None
        key=camera_frame_key(fields,source)
        if key is None or not finite(record.get('source_stamp')) or key[-1]!=int(round(record['source_stamp']*1e9)):return None
        if not camera and camera_frame_key(fields,fields.get('stamp'))!=key:return None
        return key,fields,header
    except (KeyError,TypeError,ValueError):return None


def rgb_occlusion_checks(records, source, status, artifacts):
    """Prove an opaque rendered frame caused a same-frame RGB detection miss."""
    artifacts=artifacts or {'renderer':[],'detector':[],'missing':['camera.jsonl','vision.jsonl'],
                            'read_errors':{},'readback':'missing','directory':None}
    expected=tuple(source.get(key) for key in ('scene_sha256','manifest_sha256','episode_id'))
    metadata={};quality={};images={};detector={}
    for record in records:
        if record['topic'] in ('camera_metadata','vision_quality'):
            parsed=diagnostic_fields(record,camera=record['topic']=='camera_metadata')
            if parsed is not None:(metadata if record['topic']=='camera_metadata' else quality)[parsed[0]]=parsed
        elif record['topic']=='camera_image' and finite(record.get('source_stamp')):
            images[int(round(record['source_stamp']*1e9))]=record['payload']
    for row in artifacts['detector']:
        key=camera_frame_key(row,row.get('stamp'))
        if key is not None:detector[key]=row
    matched=[];occluded=hash_verified=hash_unknown=hash_mismatch=0;hash_cache={}
    config=source.get('manifest',{}).get('station_camera',{})
    start=status.get('started_monotonic');duration=status.get('config',{}).get('duration_wall_s')
    for frame in artifacts['renderer']:
        if frame.get('occluded') is not True:continue
        occluded+=1;key=camera_frame_key(frame,frame.get('stamp'))
        capture=frame.get('capture_steady_ns')
        if (key is None or key[:3]!=expected or status.get('episode_id')!=expected[2] or type(capture) is not int or
                not finite(start) or not finite(duration) or not start<=capture*1e-9<=start+duration):continue
        joined=metadata.get(key);metric=quality.get(key);row=detector.get(key)
        if joined is None or metric is None or row is None:continue
        if joined[1].get('capture_steady_ns')!=str(capture):continue
        if (metric[1].get('detected') is not False or metric[1].get('reason')!='not_detected' or
                row.get('detected') is not False or row.get('reason')!='not_detected' or
                row.get('relative') is not None or row.get('covariance') is not None):continue
        if artifacts['directory'] is None:continue
        expected_path=Path(artifacts['directory'])/'rgb'/f'vision-{key[2]}-{key[3]}.png'
        if row.get('rgb_file')!=str(expected_path):continue
        try:
            # Reuse Pillow, already used by the camera. No OpenCV/NumPy ABI is
            # imported into the planning-venv oracle process.
            if expected_path not in hash_cache:
                from PIL import Image
                with Image.open(expected_path) as pixels:
                    if pixels.size!=(config.get('width'),config.get('height')):raise ValueError('RGB dimensions changed')
                    hash_cache[expected_path]=hashlib.sha256(pixels.convert('RGB').tobytes()).hexdigest()
            independent=images.get(key[-1])
            if independent is not None:
                if (independent.get('header')!=joined[2] or independent.get('encoding')!='rgb8' or
                        independent.get('step')!=config.get('width',0)*3):
                    hash_mismatch+=1;continue
                if independent.get('data_sha256') is None:
                    hash_unknown+=1;hash_status='unknown_independent_hash_not_recorded'
                elif independent['data_sha256']!=hash_cache[expected_path]:
                    hash_mismatch+=1;continue
                else:hash_verified+=1;hash_status='verified'
            else:hash_unknown+=1;hash_status='unknown_independent_image_not_sampled'
        except (OSError,ValueError,ImportError):
            hash_unknown+=1;continue
        matched.append({'episode_id':key[2],'sequence':key[3],'stamp':key[-1]*1e-9,
                        'rgb_sha256':hash_cache[expected_path],'independent_image_hash':hash_status})
    return {'passed':bool(matched),'renderer_occluded_frame_count':occluded,
            'same_frame_not_detected_count':len(matched),'matched_frames':matched,
            'independent_rgb_hash_verified_count':hash_verified,'independent_rgb_hash_unknown_count':hash_unknown,
            'independent_rgb_hash_mismatch_count':hash_mismatch,'artifact_readback':artifacts['readback'],
            'artifact_missing':artifacts['missing'],'artifact_read_errors':artifacts['read_errors'],
            'artifact_directory':artifacts['directory'],'artifact_log_sha256':artifacts.get('sha256',{}),
            'complete_rgb_pairing_claimed':False}


def fault_checks(records, events, accepted_windows, *, artifacts=None):
    """Prove the declared injection actually ran and reached the admission gate."""
    physics=[r for r in records if r['topic']=='physics']
    manifest=physics[0]['payload'].get('source',{}).get('manifest',{}) if physics else {}
    declaration=manifest.get('observation_faults',{'kind':'none'});kind=declaration.get('kind','none')
    if kind=='none':return {'passed':True,'kind':'none','injection_required':False}
    statuses=[r['payload']['observation_faults'] for r in physics if isinstance(r['payload'].get('observation_faults'),dict)]
    if not statuses:return {'passed':False,'kind':kind,'reason':'No independently sampled fault status'}
    status=statuses[-1];counts=status.get('counts',{});goal=status.get('native_goal_uuid')
    if not isinstance(counts,dict) or any(type(counts.get(key)) is not int or counts[key]<0 for key in ('triggers','input','output','dropped','mutated')):
        return {'passed':False,'kind':kind,'reason':'Malformed injection counters'}
    windows=[window for window in accepted_windows if any(action['kind']=='dock' and action['uuid']==goal
             for action in window['native_actions']) and window.get('accepted_handle_uuid_bound') is True]
    started=status.get('started_wall_time');triggered=status.get('trigger_wall_time')
    bound=(len(windows)==1 and finite(started) and finite(triggered)
           and windows[0]['wall_start'] <= triggered <= started <= (windows[0]['wall_end'] or math.inf)
           and status.get('config')==declaration and counts.get('triggers')==1)
    reasons={}
    for record in records:
        if record['topic']=='http_state':data=record['payload'].get('station_perception',{})
        elif record['topic']=='station_admission':data=record['payload']
        else:continue
        for reason,count in data.get('rejection_reason_counts',{}).items():
            if type(count) is int and count>0:reasons[reason]=max(reasons.get(reason,0),count)
    # Direct standard diagnostics preserve intermediate rejection reasons too.
    direct={}
    for record in records:
        if record['topic']!='station_admission_event':continue
        for item in record['payload'].get('status',[]):
            values={}
            for pair in item.get('values',[]):
                try:values[pair['key']]=json.loads(pair['value'])
                except (TypeError,ValueError):values[pair['key']]=pair['value']
            if values.get('outcome')=='rejected' and isinstance(values.get('reason'),str):
                reason=values['reason'];direct[reason]=direct.get(reason,0)+1
    for reason,count in direct.items():reasons[reason]=max(reasons.get(reason,0),count)
    coverage={};actual=False
    if kind=='replay_identity':
        coverage={key:any(key in reason and count>0 for reason,count in reasons.items())
                  for key in ('sequence','episode','frame','station_id','manifest_sha256')}
        actual=(status.get('replay_packets')==6 and counts.get('mutated',0)>=6
                and sum(reasons.values())>=6 and all(coverage.values()))
    elif kind=='delay':
        coverage={'stale_source_rejected':any(('source time' in reason or 'source stamp' in reason)
                                             and count>0 for reason,count in reasons.items())}
        actual=counts.get('dropped',0)>0 and status.get('delay_released') is True and coverage['stale_source_rejected']
    elif kind in ('short_occlusion','long_occlusion'):
        mode=manifest.get('station_perception',{}).get('mode','ideal')
        if mode=='vision':
            rgb=rgb_occlusion_checks(records,physics[0]['payload'].get('source',{}),status,artifacts)
            coverage={'actual_rgb_miss_during_window':rgb['passed'],'same_frame_rgb_evidence':rgb};actual=rgb['passed']
        else:actual=counts.get('mutated',0)>0
    return {'passed':bool(bound and actual),'kind':kind,'injection_required':True,
        'declared_config':declaration,'actual_status':status,'native_uuid_bound':bound,
        'rejection_reason_counts':reasons,'rejection_coverage':coverage,'actual_injection_proved':bool(actual),
        'admission_is_native_consumption_ack':False}


def plant_guard_telemetry(records, events):
    """Describe observed ideal plant assistance without changing any verdict."""
    physics=[r for r in records if r['topic']=='physics'];windows=[]
    for start in events:
        if start.get('kind') not in ('dock_started','full_started','route_started'):continue
        prefix=start['kind'].split('_')[0]
        finishes=[e['wall_time'] for e in events if e.get('kind')==prefix+'_finished'
                  and e.get('task_id')==start['task_id'] and e['wall_time']>=start['wall_time']]
        end=min(finishes,default=None)
        samples=[r for r in physics if start['wall_time']<=r['received_wall_time']<=(end or math.inf)]
        enabled=tripped=enable_edges=disable_edges=trip_edges=invalid=gap_count=0
        enabled_duration=tripped_duration=0.;previous=None;methods=set();hardware=set();margins=set()
        for record in samples:
            guard=record['payload'].get('docking_guard',{});stamp=record.get('source_stamp')
            if (not finite(stamp) or type(guard.get('enabled')) is not bool or type(guard.get('tripped')) is not bool):
                invalid+=1;previous=None;continue
            enabled+=int(guard['enabled']);tripped+=int(guard['tripped'])
            if isinstance(guard.get('method'),str):methods.add(guard['method'])
            if type(guard.get('hardware_validated')) is bool:hardware.add(guard['hardware_validated'])
            if finite(guard.get('margin_m')):margins.add(guard['margin_m'])
            if previous is not None:
                old_t,old=previous;delta=stamp-old_t
                enable_edges+=int(old['enabled'] is False and guard['enabled'] is True)
                disable_edges+=int(old['enabled'] is True and guard['enabled'] is False)
                trip_edges+=int(old['tripped'] is False and guard['tripped'] is True)
                if 0<delta<=.1:
                    if old['enabled'] and guard['enabled']:enabled_duration+=delta
                    if old['tripped'] and guard['tripped']:tripped_duration+=delta
                else:gap_count+=1
            previous=(stamp,guard)
        first=samples[0]['payload'].get('docking_guard',{}) if samples else {}
        windows.append({'task_id':start['task_id'],'scope':'dock' if prefix=='dock' else 'transport',
            'wall_start':start['wall_time'],'wall_end':end,'closed':end is not None,
            'physics_sample_count':len(samples),'enabled_sample_count':enabled,'tripped_sample_count':tripped,
            'observed_enable_transitions':enable_edges,'observed_disable_transitions':disable_edges,
            'observed_trip_transitions':trip_edges,'initial_sample_tripped':first.get('tripped'),
            'enabled_observed_contiguous_source_duration_s':enabled_duration,
            'tripped_observed_contiguous_source_duration_s':tripped_duration,
            'invalid_guard_sample_count':invalid,'source_gap_or_nonadvance_count':gap_count,
            'maximum_accumulated_source_gap_s':.1,'methods':sorted(methods),
            'hardware_validated_values':sorted(hardware),'margin_m_values':sorted(margins),
            'plant_assistance_observed':tripped>0,'pure_vision_precision_claimed':False})
    return {'windows':windows,'changes_acceptance_verdict':False,
        'source':'independently received physics raw.docking_guard within task marker windows',
        'boundary':'Ideal plant velocity guard remains available; observed intervention is separate from sensor/native/physical success.',
        'sampling_limit':'Durations sum adjacent same-state source intervals <=0.1s; gaps are omitted, not interpolated. An initially tripped sample is not a within-window rising edge.'}


def route_checks(records, samples, audit, events):
    """R2 loaded slices reuse destination scoring, without inventing a grasp."""
    attempts = []
    windows = []
    for start in (e for e in events if e.get('kind') == 'route_started'):
        ends = [e['wall_time'] for e in events if e.get('kind') == 'route_finished'
                and e.get('task_id') == start['task_id'] and e['wall_time'] >= start['wall_time']]
        end = min(ends, default=math.inf)
        items = [s for s in samples if start['wall_time'] <= s['wall_time'] <= end]
        first = items[0] if items else None
        branch = first['raw'].get('checkpoint_branch', {}) if first else {}
        origin = bool(first and branch.get('restored') is True and branch.get('level')=='R2'
            and branch.get('snapshot_id')==start.get('snapshot_id')
            and branch.get('episode_id')==first['raw'].get('episode_id')
            and branch.get('parent_episode_id')!=branch.get('episode_id')
            and isinstance(branch.get('world_session_id'),str)
            and branch['world_session_id']==first['raw'].get('world_session_id')
            and branch.get('parent_world_session_id')!=branch['world_session_id']
            and branch.get('old_motion_commands_restored') is False
            and branch.get('external_components_restored') is False
            and branch.get('integration_readback_max_abs_error')==0.)
        violations = []
        for item in items:
            raw = item['raw']
            retained = (abs(item['relative'][0])<=.047 and abs(item['relative'][1])<=.047
                and -.002<=item['relative'][2]<=.04 and raw.get('cargo_tray_floor_contact') is True
                and all(abs(item['relative'][axis])+item['extents'][axis]<=.058 for axis in range(2)))
            home = (max(abs(q-target) for q,target in zip(raw['q6'],audit['home_q6']))<.02
                    and oracle.norm(raw['qvel6'])<.05)
            if not (item['independent_crosscheck'] and raw.get('finite') is True and retained and home
                    and len(item['forces'])>=2 and max(item['forces'])<.02):
                violations.append(item['stamp'])
        moved = oracle.norm([items[-1]['cargo'][i]-first['cargo'][i] for i in (0,1)]) if first else 0.
        attempts.append({'task_id':start['task_id'],'started_wall_time':start['wall_time'],
                         'route_started_source_stamp':first['stamp'] if first else None})
        windows.append({'task_id':start['task_id'],'snapshot_origin_bound':origin,
            'physical_sample_count':len(items),'cargo_displacement_m':moved,
            'retention_or_home_violation_count':len(violations),'violation_preview':violations[:40],
            'passed':origin and bool(ends) and bool(items) and not violations and moved>=.5})
    delivery = delivery_checks(records,samples,audit,attempts,events,marker_prefix='route')
    return {'passed':bool(windows) and all(w['passed'] for w in windows) and delivery['passed'],
            'windows':windows,'task_delivery_acceptance':delivery,
            'full_transport_acceptance_claimed':False,'grasp_or_release_in_this_episode_claimed':False}


def _business_vector(values, length):
    if (not isinstance(values, (list, tuple)) or len(values) != length
            or not all(finite(value) for value in values)):
        raise ValueError('Incomplete finite named-entity measurement')
    return list(values)


def _business_quaternion(value):
    value = _business_vector(value, 4)
    if abs(sum(v*v for v in value)-1.) > .002:
        raise ValueError('Named cargo quaternion is not a unit quaternion')
    return value


def _business_binding(value):
    keys = {'cargo_id', 'pickup_arm_id', 'unload_station_id'}
    if (not isinstance(value, dict) or set(value) != keys
            or not all(isinstance(value[key], str) and value[key].strip() for key in keys)):
        raise ValueError('Missing explicit business_delivery selection')
    return dict(value)


def _business_project(raw, manifest, binding, arm_id):
    """Independent scoring projection; never import owner predicates or rewrite qpos."""
    description = manifest['business_entities']
    arm = raw['business_entities']['arms'][arm_id]
    cargo = raw['business_entities']['cargo'][binding['cargo_id']]
    point = _business_vector(cargo['position'], 3)
    quat = _business_quaternion(cargo['quaternion_wxyz'])
    velocity = _business_vector(cargo['velocity_world_angular_linear'], 6)
    tray = raw['tray']
    rotation = oracle.quat_matrix(_business_quaternion(tray['quaternion_wxyz']))
    inverse = oracle.transpose(rotation)
    offset = [a-b for a, b in zip(point, _business_vector(tray['position'], 3))]
    tray_velocity = _business_vector(tray['velocity_world_angular_linear'], 6)
    a, b, c = tray_velocity[:3];x, y, z = offset
    rotating = [b*z-c*y, c*x-a*z, a*y-b*x]
    relative_velocity = oracle.matvec(inverse, [velocity[i+3]-tray_velocity[i+3]-rotating[i] for i in range(3)])
    contacts = cargo['contacts']
    forces = {'pad_gripper': 0., 'pad_moving_jaw': 0.}
    for name in description['arms'][arm_id]['pad_geoms']:
        force = contacts['pads'].get(arm_id, {}).get(name, {}).get('normal_force_n', 0.)
        if not finite(force) or force < 0:
            raise ValueError('Invalid named pad force')
        canonical = name.rsplit('__', 1)[-1]
        if canonical in forces:
            forces[canonical] += force
    support = contacts['supports'].get('tray', {})
    count = support.get('contact_count', 0)
    if type(count) is not int or count < 0:
        raise ValueError('Invalid named tray support count')
    view = dict(raw)
    view.update(q6=_business_vector(arm['qpos6'], 6), qvel6=_business_vector(arm['qvel6'], 6),
                cargo={'position': point, 'quaternion_wxyz': quat, 'velocity_world_angular_linear': velocity,
                       'position_relative_tray': oracle.matvec(inverse, offset),
                       'velocity_relative_tray': relative_velocity},
                finger_normal_forces_n=forces, cargo_tray_floor_contact=count > 0)
    return view


def business_samples(records, manifest, binding, arm_id):
    """Use the corresponding independently subscribed pose; legacy cargo_1 may fall back."""
    cargo_id = binding['cargo_id']
    poses = oracle.records_by_topic(records, 'cargo:'+cargo_id)
    description = manifest['business_entities']['cargo'][cargo_id]
    if not poses and description.get('body') == 'grasp_target':
        poses = oracle.records_by_topic(records, 'cargo')
    truth = oracle.records_by_topic(records, 'truth')
    clocks = oracle.records_by_topic(records, 'clock')
    samples, errors = [], []
    audit = oracle.scene_audit(next(r['payload'] for r in records if r['topic'] == 'physics'))
    for record in records:
        if record['topic'] != 'physics':
            continue
        try:
            raw = _business_project(record['payload'], manifest, binding, arm_id)
            item = oracle.physical_sample({**record, 'payload': raw}, truth, poses, clocks,
                audit['tray_offset_from_base_footprint'], audit['half_extents'])
            if item is None:
                errors.append({'stamp': record['source_stamp'], 'wall_time':record['received_wall_time'],
                               'reason': 'Missing independent cargo, car or clock pose'})
                continue
            pose = oracle.nearest(poses, item['stamp'])
            item['cargo_quaternion_wxyz'] = _business_quaternion(oracle.quaternion(pose['payload']['pose']))
            item['full_raw'] = record['payload']
            samples.append(item)
        except (KeyError, TypeError, ValueError, IndexError) as error:
            errors.append({'stamp': record.get('source_stamp'), 'wall_time':record['received_wall_time'], 'reason': str(error)})
    return samples, errors


def _business_shelf(item, previous, manifest, binding, unload_arm):
    """Recompute footprint and rest from independent poses and measured contacts."""
    raw = item['raw'];cargo = item['full_raw']['business_entities']['cargo'][binding['cargo_id']]
    entities = manifest['business_entities']
    station = entities['unload_stations'][binding['unload_station_id']]
    arm = entities['arms'][unload_arm]
    yaw = arm['station_yaw_rad'];c, s = math.cos(yaw), math.sin(yaw)
    inverse = [[c, s, 0.], [-s, c, 0.], [0., 0., 1.]]
    position = oracle.matvec(inverse, [a-b for a, b in zip(item['cargo'], arm['station_position_m'])])
    rotation = oracle.quat_matrix(item['cargo_quaternion_wxyz'])
    half = (.009, .009, .008)
    extent = [sum(abs(sum(inverse[i][k]*rotation[k][j] for k in range(3)))*half[j]
                  for j in range(3)) for i in range(2)]
    shelf = _business_vector(station['shelf_xy_in_station_m'], 2)
    footprint = all(abs(position[i]-shelf[i])+extent[i] <= .058 for i in range(2))
    slots = station.get('cargo_shelf_slots')
    if slots is not None:
        slot = slots[binding['cargo_id']]
        center, size = _business_vector(slot['center_xy_m'], 2), _business_vector(slot['half_size_xy_m'], 2)
        footprint &= all(size[i] > 0 and abs(position[i]-center[i])+extent[i] <= size[i] for i in range(2))
    contacts = cargo['contacts']
    support = contacts['supports'].get(binding['unload_station_id'], {})
    supported = (type(support.get('contact_count')) is int and support['contact_count'] > 0
                 and finite(support.get('normal_force_n')) and support['normal_force_n'] > 0)
    pad_forces = [record['normal_force_n'] for pads in contacts['pads'].values() for record in pads.values()]
    released = all(finite(force) and 0 <= force < .02 for force in pad_forces)
    velocity = _business_vector(cargo['velocity_world_angular_linear'], 6)
    speed = math.inf
    if previous and 0 < item['stamp']-previous['stamp'] <= .1:
        speed = oracle.norm([a-b for a, b in zip(item['cargo'], previous['cargo'])])/(item['stamp']-previous['stamp'])
    home = _business_vector(arm['home_qpos6'], 6)
    home_quiet = max(abs(a-b) for a, b in zip(raw['q6'], home)) < .02 and oracle.norm(raw['qvel6']) < .05
    entities_quiet = (all(oracle.norm(_business_vector(a['qvel6'], 6)) < .05
                          for a in item['full_raw']['business_entities']['arms'].values())
                      and all(oracle.norm(_business_vector(cargo['velocity_world_angular_linear'], 6)[3:]) < .03
                              for cargo in item['full_raw']['business_entities']['cargo'].values()))
    valid = (item['independent_crosscheck'] and raw.get('finite') is True and raw.get('car_hold') is True
             and item['car_speed'] < .01 and abs(item['yaw_rate']) < .01 and footprint and supported
             and released and home_quiet and entities_quiet and speed < .002 and oracle.norm(velocity[3:]) < .002
             and raw['cargo_tray_floor_contact'] is False)
    return bool(valid), {'full_shelf_and_slot_footprint': bool(footprint), 'shelf_supported': bool(supported),
                         'all_pads_released': bool(released), 'unload_arm_home_quiet': bool(home_quiet),
                         'all_entities_quiet': bool(entities_quiet), 'independent_world_speed_m_s': speed}


def named_publisher_identity(records, cargo_id, start, end):
    """Audit recorded endpoints; historical missing inventories remain explicit."""
    topic = cargo_topic(cargo_id)
    inventories = [r['payload'] for r in records if r['topic'] == 'publisher_inventory'
                   and start <= r['received_wall_time'] <= end]
    required = any(topic in value for value in inventories)
    endpoints = {}
    for name in (topic, '/cooperation/physics_state'):
        entries = [entry for value in inventories for entry in value.get(name, [])]
        endpoints[name] = {'gids': sorted({tuple(entry.get('gid', [])) for entry in entries}),
                           'nodes': sorted({(entry.get('namespace'), entry.get('node')) for entry in entries})}
    complete = all(len(value['gids']) == 1 and bool(value['gids'][0])
                   and len(value['nodes']) == 1
                   and all(isinstance(part, str) and part for part in value['nodes'][0])
                   for value in endpoints.values())
    same_owner = complete and endpoints[topic]['nodes'] == endpoints['/cooperation/physics_state']['nodes']
    return {'required': required, 'checked': required and complete,
            'passed': bool(same_owner) if required else True,
            'status': ('verified' if same_owner else 'invalid_or_missing_endpoints') if required else 'historical_inventory_unavailable',
            'topics': endpoints, 'scope': 'recorded_endpoint_identity_not_per_message_consumption_ack'}


def business_delivery_checks(records, events, audit):
    """Score named load/transport, then physical unload through final cleanup."""
    states = [r for r in records if r['topic'] == 'http_state']
    declared = any('business_delivery' in e for e in events if e.get('kind') == 'full_started')
    declared |= any('business_delivery' in r['payload'].get('task', {}) for r in states)
    if not declared:
        return {'required': False, 'passed': True, 'attempts': []}
    manifests = [r['payload'].get('source', {}).get('manifest') for r in records if r['topic'] == 'physics']
    manifest = next((m for m in manifests if isinstance(m, dict) and 'business_entities' in m), None)
    results = []
    for event in (e for e in events if e.get('kind') == 'full_started'):
        task_id, start = event['task_id'], event['wall_time']
        ends = [e['wall_time'] for e in events if e.get('kind') == 'full_finished'
                and e.get('task_id') == task_id and e['wall_time'] >= start]
        end = min(ends, default=math.inf)
        task_states = [r for r in states if start <= r['received_wall_time'] <= end+1.
                       and r['payload'].get('task', {}).get('id') == task_id]
        declarations = ([event['business_delivery']] if 'business_delivery' in event else [])
        declarations += [r['payload']['task']['business_delivery'] for r in task_states
                         if 'business_delivery' in r['payload']['task']]
        if not declarations:
            continue
        result = {'task_id': task_id, 'passed': False, 'physical_proof_source': 'independent_named_ROS_poses_and_measured_contacts',
                  'inventory_receipt_is_physical_proof': False, 'controller_helpers_imported': False}
        try:
            binding = _business_binding(declarations[0]);result['business_delivery'] = binding
            publishers = named_publisher_identity(records, binding['cargo_id'], start, end)
            result['named_pose_publisher_identity'] = publishers
            if manifest is None or any(_business_binding(value) != binding for value in declarations):
                raise ValueError('Missing manifest or changing named cargo binding')
            entities = manifest['business_entities'];station = entities['unload_stations'][binding['unload_station_id']]
            unload_arm = station['arm_id'];entities['cargo'][binding['cargo_id']]
            selected_audit = dict(audit, home_q6=entities['arms'][binding['pickup_arm_id']]['home_qpos6'])
            selected, missing = business_samples(records, manifest, binding, binding['pickup_arm_id'])
            selected = [s for s in selected if start <= s['wall_time'] <= end]
            window_missing = [e for e in missing if start <= e['wall_time'] <= end]
            preliminary = oracle.full_score(selected, selected_audit)
            arrival_gate = oracle.Gate(1.)
            placed = preliminary['released_full_footprint_supported_and_relative_rest']['first_pass_stamp']
            destination = station['delivery_pose']
            previous = None
            for item in selected:
                raw = item['raw'];speed = math.inf
                if previous and 0 < item['stamp']-previous['stamp'] <= .1:
                    speed = oracle.norm([a-b for a,b in zip(item['cargo'],previous['cargo'])])/(item['stamp']-previous['stamp'])
                valid = (placed is not None and item['stamp'] >= placed and item['independent_crosscheck']
                    and raw.get('finite') is True and raw.get('car_hold') is True
                    and math.hypot(item['car'][0]-destination['x'],item['car'][1]-destination['y']) <= .04
                    and oracle.yaw_error(item['car_yaw'],destination['yaw']) <= .05
                    and item['car_speed'] < .01 and abs(item['yaw_rate']) < .01
                    and raw['cargo_tray_floor_contact'] and max(item['forces']) < .02
                    and all(abs(item['relative'][i])+item['extents'][i] <= .058 for i in range(2))
                    and oracle.norm(raw['cargo']['velocity_relative_tray']) < .002 and speed < .005
                    and max(abs(a-b) for a,b in zip(raw['q6'],selected_audit['home_q6'])) < .02
                    and oracle.norm(raw['qvel6']) < .05)
                arrival_gate.update(item['stamp'],bool(valid));previous = item
            arrival = arrival_gate.first_pass
            prefix = [s for s in selected if arrival is not None and s['stamp'] <= arrival]
            load = {'task_id': task_id, 'started_wall_time': start, **oracle.full_score(prefix, selected_audit)}
            prefix_end = prefix[-1]['wall_time'] if prefix else end
            prefix_events = [e for e in events if not (e.get('kind') == 'full_finished' and e.get('task_id') == task_id)]
            prefix_events.append({'kind': 'full_finished', 'task_id': task_id, 'wall_time': prefix_end})
            handoff = transport_checks(prefix, selected_audit, [load], prefix_events)
            delivery = delivery_checks(records, prefix, selected_audit, [load], events)
            unload, missing_unload = business_samples(records, manifest, binding, unload_arm)
            unload = [s for s in unload if start <= s['wall_time'] <= end]
            lift, settled = oracle.Gate(1.), oracle.Gate(1.)
            baseline = prefix[-1]['cargo'][2] if prefix else math.inf
            previous = last = None;last_valid = False;details = {}
            for item in unload:
                if arrival is None or item['stamp'] <= arrival:
                    previous = item;continue
                raw = item['raw']
                lift.update(item['stamp'], bool(item['independent_crosscheck'] and raw.get('finite') is True
                    and item['cargo'][2]-baseline >= .025 and min(item['forces']) > .02
                    and raw.get('cargo_tray_floor_contact') is False and raw.get('car_hold') is True
                    and item['car_speed'] < .01 and abs(item['yaw_rate']) < .01))
                last_valid, details = _business_shelf(item, previous, manifest, binding, unload_arm)
                settled.update(item['stamp'], lift.first_pass is not None and last_valid)
                previous = last = item
            cleanup = cleanup_checks(records, unload, events, task_id)
            final_state = task_states[-1]['payload'] if task_states else {}
            stock = final_state.get('business_inventory') or {}
            entry = stock.get('cargo', {}).get(binding['cargo_id'], {})
            receipt = final_state.get('task', {}).get('unload_receipt') or {}
            receipt_ok = (entry.get('state') == 'delivered' and entry.get('task_id') == task_id
                          and final_state.get('task', {}).get('status') == 'succeeded'
                          and stock.get('episode_id') == event.get('episode_id')
                          and receipt.get('cargo_id') == binding['cargo_id']
                          and receipt.get('unload_station_id') == binding['unload_station_id']
                          and receipt.get('episode_id') == event.get('episode_id')
                          and receipt.get('world_session_id') == stock.get('world_id')
                          and last is not None and last['full_raw'].get('world_session_id') == stock.get('world_id')
                          and finite(receipt.get('source_stamp')) and settled.first_pass is not None
                          and settled.first_pass <= receipt['source_stamp'] <= last['stamp']+.1)
            fresh = bool(last and finite(end) and 0 <= end-last['wall_time'] <= .5)
            continuously_settled = bool(last_valid and last and settled.started is not None
                                       and last['stamp']-settled.started >= 1.)
            all_contacts_clear = all(s['raw'].get('arm_forbidden_contact_total') == 0
                                     and s['raw'].get('car_forbidden_contact_total') == 0
                                     and s['independent_crosscheck']
                                     and episode_id(s['full_raw']) == event.get('episode_id')
                                     and s['full_raw'].get('world_session_id') == stock.get('world_id')
                                     for s in selected)
            declared_budget = entities.get('configuration', {}).get('budgets_wall_s')
            budget_ok = prefix_end-start <= 360
            if declared_budget is not None:
                unload_budget = declared_budget.get('unload')
                budget_ok = bool(declared_budget.get('load_and_delivery') == 360
                    and finite(unload_budget) and unload_budget > 0 and finite(end)
                    and prefix_end-start <= 360
                    and end-start <= 360+unload_budget)
            result.update(original_k_load_and_transport=load, continuous_handoff_and_transport=handoff,
                          task_delivery_acceptance=delivery, physical_unload_lift=lift.result(),
                          shelf_home_rest_through_cleanup=settled.result(), last_shelf_predicates=details,
                          cleanup=cleanup, final_physical_evidence_fresh=fresh,
                          inventory_and_receipt_bound=bool(receipt_ok),
                          wall_budget={'required': declared_budget is not None, 'passed': budget_ok,
                                       'load_and_delivery_limit_wall_s': 360.,
                                       'declared': declared_budget, 'load_and_delivery_wall_s':prefix_end-start,
                                       'load_and_delivery_complete': arrival is not None,
                                       'load_and_delivery_time_basis': ('physical_arrival_prefix' if arrival is not None
                                                                       else 'elapsed_until_terminal_or_observation_end'),
                                       'full_task_wall_s':end-start},
                          phase_evidence={'independent_selected_samples': len(selected),
                              'load_and_transport_prefix_samples': len(prefix),
                              'arrival_source_stamp': arrival,
                              'pickup_and_transport_observed': preliminary,
                              'unload_samples_after_arrival': sum(arrival is not None and s['stamp'] > arrival for s in unload),
                              'rejection_reasons': ([ 'missing_independent_samples' ] if window_missing or not selected else [])
                                  + ([ 'named_publisher_identity_not_verified' ] if not publishers['passed'] else [])
                                  + ([ 'arrival_not_verified' ] if arrival is None else [])
                                  + ([ 'load_and_delivery_budget_exceeded' ] if prefix_end-start > 360 else [])
                                  + ([ 'unload_lift_not_verified' ] if lift.first_pass is None else [])
                                  + ([ 'shelf_home_rest_not_verified' ] if not continuously_settled else [])},
                          missing_independent_samples=len(window_missing),
                          missing_independent_samples_preview=(missing+missing_unload)[:8])
            result['passed'] = bool(publishers['passed'] and len(ends) == 1 and selected and load['passed']
                and handoff['passed'] and delivery['passed'] and lift.first_pass is not None
                and continuously_settled and fresh and cleanup['passed'] and receipt_ok and all_contacts_clear and budget_ok)
        except (KeyError, TypeError, ValueError, IndexError, StopIteration) as error:
            result['reason'] = f'{type(error).__name__}: {error}'
        results.append(result)
    return {'required': True, 'attempts': results, 'passed': bool(results) and all(r['passed'] for r in results),
            'independent_pose_topic_template': '/cooperation/cargo/<cargo_id>/pose',
            'legacy_primary_pose_fallback': True,
            'named_pose_publisher_identity_checked': bool(results) and all(
                r.get('named_pose_publisher_identity', {}).get('checked') is True for r in results),
            'original_thresholds_preserved': True}


def augment_score(value, records, samples, audit, events):
    scope=getattr(options,'scope','transport'); outcome=getattr(options,'expected_outcome','success')
    extra = extra_checks(records, options.markers, options.expected_episode,
                         reset_receipt=options.reset_receipt,
                         allow_initial_episode=options.allow_initial_episode,scope=scope,expected_outcome=outcome)
    handoff = transport_checks(samples, audit, value.get('full_attempts', []), events) if audit else {'passed': False, 'windows': []}
    delivery = (delivery_checks(records, samples, audit, value.get('full_attempts', []), events)
                if audit and scope == 'transport' else {'required': False, 'passed': True, 'attempts': []})
    business = (business_delivery_checks(records, events, audit) if audit and scope == 'transport'
                else {'required': False, 'passed': True, 'attempts': []})
    value['original_k_oracle_passed'] = value['passed']
    value['repeated_episode_acceptance'] = extra
    value['continuous_handoff_and_transport'] = handoff
    value['task_delivery_acceptance'] = delivery
    if business['required']:
        value['business_delivery_acceptance'] = business
    value['evidence_mode'] = 'offline_replay' if options.score_only else 'live_observation'
    value['collection_directory'] = str(options.score_only or options.output)
    value['oracle_reuse'] = {
        'k_observer_sha256': 'cf315731f102c26774e3a9eee77be11a0f8f87357b775739e37e637a8c13abe9',
        'repeat_base_sha256': '9bb7be2cc2f8d9dad099533fea91b8d457a55fe5ab4f06969a0c07f21c227088',
        'repeat_observer_sha256': '788383af86568da7d5ddfec6d37e7b6285a08b2ec01b1f3ec095e4c8914c9058',
        'preserved_physical_functions': ['Gate', 'physical_sample', 'full_score', 'cancellation_score'],
        'no_controller_scoring_dependency': True}
    callback_errors = [item['payload'] for item in records if item['topic'] == 'callback_error']
    value['callback_errors'] = callback_errors
    integrity = value.get('source_integrity', {})
    current_ok = bool(options.score_only) or integrity.get('current_driver_matches_collection_end') is True
    value['observation_metrics']=observation_metrics(records,samples,audit) if audit else {}
    value['scope']=scope;value['expected_outcome']=outcome
    if scope == 'dock':
        docking=dock_checks(records,samples,audit,events,expected_outcome=outcome) if audit else {'passed':False,'attempts':[]}
        value['docking_acceptance']=docking
        value['full_transport_acceptance_claimed']=False
        value['passed']=bool(docking['passed'] and extra['passed'] and integrity.get('passed') is True and not callback_errors and current_ok)
        value['task_completion_passed']=bool(outcome == 'success' and value['passed'])
        value['expected_safety_passed']=bool(outcome == 'safe_cancel' and value['passed'])
    elif scope == 'route':
        routing = route_checks(records,samples,audit,events) if audit else {'passed':False}
        value['route_acceptance'] = routing
        value['full_transport_acceptance_claimed'] = False
        value['task_delivery_acceptance'] = routing.get('task_delivery_acceptance',{})
        value['passed'] = bool(routing['passed'] and extra['passed'] and integrity.get('passed') is True
                               and value.get('recording_integrity',{}).get('passed') is True
                               and not callback_errors and current_ok)
    else:
        if business['required']:
            named = {attempt['task_id']: attempt for attempt in business['attempts']}
            legacy = [attempt for attempt in value.get('full_attempts', []) if attempt['task_id'] not in named]
            legacy_handoff = transport_checks(samples,audit,legacy,events) if legacy else {'passed':True,'windows':[]}
            legacy_delivery = delivery_checks(records,samples,audit,legacy,events) if legacy else {'passed':True,'attempts':[]}
            value['legacy_primary_full_attempts'] = value.get('full_attempts', [])
            value['full_attempts'] = [dict(attempt.get('original_k_load_and_transport', {}),
                task_id=attempt['task_id'],business_delivery=attempt.get('business_delivery'),passed=attempt['passed'])
                for attempt in business['attempts']]+legacy
            value['continuous_handoff_and_transport'] = {'passed':business['passed'] and legacy_handoff['passed'],
                'windows':legacy_handoff['windows']+[window for attempt in business['attempts']
                    for window in attempt.get('continuous_handoff_and_transport',{}).get('windows',[])]}
            value['task_delivery_acceptance'] = {'required':True,'passed':business['passed'] and legacy_delivery['passed'],
                'attempts':legacy_delivery['attempts']+[item for attempt in business['attempts']
                    for item in attempt.get('task_delivery_acceptance',{}).get('attempts',[])]}
            value['passed'] = bool(business['passed'] and all(attempt['passed'] for attempt in legacy)
                and all(attempt['passed'] for attempt in value.get('cancellations', []))
                and legacy_handoff['passed'] and legacy_delivery['passed'] and integrity.get('passed') is True
                and extra['passed'] and not callback_errors and current_ok)
        else:
            value['passed'] = bool(value['passed'] and extra['passed'] and handoff['passed'] and delivery['passed'] and not callback_errors and current_ok)
    first_physics=next((r['payload'] for r in records if r['topic']=='physics'),{})
    mode=first_physics.get('source',{}).get('manifest',{}).get('station_perception',{}).get('mode','ideal')
    if mode=='vision':
        value['camera_acceptance']=camera_checks(records,options.expected_episode)
        value['passed']=bool(value['passed'] and value['camera_acceptance']['passed'])
        if scope=='dock':
            value['task_completion_passed']=bool(outcome=='success' and value['passed'])
            value['expected_safety_passed']=bool(outcome=='safe_cancel' and value['passed'])
    fault_kind=first_physics.get('source',{}).get('manifest',{}).get('observation_faults',{}).get('kind')
    artifacts=(camera_artifacts(options.score_only or options.output)
               if mode=='vision' and fault_kind in ('short_occlusion','long_occlusion') else None)
    value['fault_acceptance']=fault_checks(records,events,extra['windows'],artifacts=artifacts)
    value['passed']=bool(value['passed'] and value['fault_acceptance']['passed'])
    if scope=='dock':
        value['task_completion_passed']=bool(outcome=='success' and value['passed'])
        value['expected_safety_passed']=bool(outcome=='safe_cancel' and value['passed'])
    value['plant_guard_telemetry']=plant_guard_telemetry(records,events)
    value['live_runtime_acceptance_claimed'] = not bool(options.score_only) and value['passed']
    return value


def score(directory, marker_path):
    return original_score(directory, marker_path, output_directory=options.output, augment=augment_score)


def parse_options(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-episode', required=True)
    origin = parser.add_mutually_exclusive_group(required=True)
    origin.add_argument('--reset-receipt', type=Path)
    origin.add_argument('--allow-initial-episode', action='store_true')
    parser.add_argument('--driver', type=Path, default=BASE/'cooperation_sim.py')
    parser.add_argument('--domain', type=int)
    parser.add_argument('--api', default='http://127.0.0.1:9088/coop-api')
    parser.add_argument('--duration', type=float, default=900., help='finite wall-clock collection limit, at most 900 seconds')
    parser.add_argument('--max-record-bytes', type=int, default=1024**3, help='observer byte budget; exhaustion fails collection')
    parser.add_argument('--markers', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--score-only', type=Path)
    parser.add_argument('--scope',choices=('dock','transport','route'),default='transport')
    parser.add_argument('--business-manifest',type=Path,
                        help='Subscribe independent PoseStamped topics for every configured physical cargo')
    parser.add_argument('--expected-outcome',choices=('success','safe_cancel'),default='success')
    result = parser.parse_args(argv)
    if not result.expected_episode.strip():
        parser.error('--expected-episode must be nonempty')
    if not finite(result.duration) or not 0 < result.duration <= 900:
        parser.error('--duration must be finite and in (0, 900]')
    if not 1024 <= result.max_record_bytes <= 4*1024**3:
        parser.error('--max-record-bytes must be 1024..4294967296')
    if result.score_only is None and (result.domain is None or result.domain in (0, 107, 114) or result.domain < 0):
        parser.error('live observation requires an explicit isolated domain; 0/107/114 are protected')
    if result.score_only is not None:
        result.score_only = result.score_only.resolve()
        if result.output.resolve() == result.score_only or result.score_only in result.output.resolve().parents:
            parser.error('--output must be outside the historical evidence directory')
    if result.output.exists():
        parser.error('--output must be a new directory')
    return result


def main(argv=None):
    global options
    options = parse_options(argv)
    oracle.DRIVER = options.driver.resolve()
    oracle.driver_audit = driver_audit
    oracle.score = score
    oracle.topic_stamp = topic_stamp
    if options.score_only:
        options.output.mkdir(parents=True, exist_ok=False, mode=0o700)
        try:
            result = score(options.score_only, options.markers)
        except (OSError, ValueError, TypeError, KeyError, IndexError) as error:
            result = {'passed': False, 'evidence_mode': 'offline_replay',
                      'reason': f'{type(error).__name__}: {error}', 'live_runtime_acceptance_claimed': False}
            target = options.output/f'score-error-{time.time_ns()}.json'
            oracle.private_json(target, result)
            print(json.dumps({'score_file': str(target), 'passed': False, 'reason': result['reason']}))
        return 0 if result['passed'] else 1
    os.environ['ROS_DOMAIN_ID'] = str(options.domain)
    os.environ['ROS_AUTOMATIC_DISCOVERY_RANGE'] = 'LOCALHOST'
    os.environ['ROS_LOCALHOST_ONLY'] = '1'
    observe(options)
    files = list(options.output.glob('score-*.json'))
    return 0 if len(files) == 1 and json.loads(files[0].read_text()).get('passed') is True else 1


if __name__ == '__main__':
    sys.exit(main())
