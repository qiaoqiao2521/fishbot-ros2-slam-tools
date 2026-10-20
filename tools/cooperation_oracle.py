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
import time

BASE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('original_cooperation_oracle', BASE / 'cooperation_oracle_base.py')
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
original_audit = oracle.driver_audit
original_score = oracle.score
options = None


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
    prefix = 'dock' if scope == 'dock' else 'full'
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
            if r['topic'] in ('nav_feedback', 'dock_feedback'):
                action_ids.add((r['topic'].split('_')[0], uuid_hex(r['payload']['goal_id']['uuid'])))
            if r['topic'] in ('nav_status', 'dock_status'):
                kind = r['topic'].split('_')[0]
                for s in r['payload']['status_list']:
                    key = (kind, uuid_hex(s['goal_info']['goal_id']['uuid']))
                    if s['status'] in (1, 2, 3):
                        action_ids.add(key)
                    if key in action_ids:
                        terminal[key] = s['status']
        dock_ids = [k for k in action_ids if k[0] == 'dock']
        native_success = bool(action_ids) and bool(dock_ids) and all(terminal.get(k) == 4 for k in action_ids)
        if scope == 'dock':
            native_success = native_success and len(dock_ids) == 1
        else:
            native_success = native_success and any(k[0] == 'nav' for k in action_ids)
        native_known = bool(action_ids) and all(terminal.get(k) in (4,5,6) for k in action_ids)
        native = native_success if expected_outcome == 'success' else native_known
        http = [r['payload'] for r in records if r['topic'] == 'http_state'
                and r['received_wall_time'] >= start['wall_time']
                and r['payload'].get('task', {}).get('id') == start['task_id']]
        strict_handles = scope == 'dock' or start.get('scope') in ('dock','transport')
        handle_ids=set();handle_terminal={};handle_cancel_times={};handle_bad=False
        for state in http:
            for action in state.get('native_actions',[]):
                if action.get('accepted') is not True:continue
                kind={'Nav2停靠':'dock','Nav2':'nav'}.get(action.get('label'))
                identifier=action.get('uuid')
                if kind is None or not isinstance(identifier,str) or len(identifier)!=32:
                    handle_bad=True;continue
                key=(kind,identifier);handle_ids.add(key)
                if action.get('result_known') is True:handle_terminal[key]=action.get('status')
                if finite(action.get('cancel_requested_wall_time')):handle_cancel_times[key]=action['cancel_requested_wall_time']
        handles_bound=(not handle_bad and bool(handle_ids) and handle_ids==action_ids
                       and all(handle_terminal.get(key)==terminal.get(key) for key in action_ids))
        cancel_events=[e for e in events if e.get('kind')=='cancel_requested' and e.get('task_id')==start['task_id']]
        cancel_bound=all(('dock',e.get('native_uuid')) in action_ids
                         and handle_cancel_times.get(('dock',e.get('native_uuid')))==e.get('wall_time') for e in cancel_events)
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


def delivery_checks(records, samples, audit, attempts, events):
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

    target_keys = ('expected_delivery_pose', 'delivery_pose', 'requested_delivery_pose')
    declared = any(e.get('kind') == 'full_started' and any(k in e for k in target_keys) for e in events)
    declared |= any(r['topic'] == 'http_state' and 'delivery_pose' in r['payload'].get('task', {}) for r in records)
    results = []
    for attempt in attempts:
        task_id, start = attempt['task_id'], attempt['started_wall_time']
        starts = [e for e in events if e.get('kind') == 'full_started'
                  and e.get('task_id') == task_id and e['wall_time'] == start]
        event = starts[0] if len(starts) == 1 else {}
        ends = [e['wall_time'] for e in events if e.get('kind') == 'full_finished'
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
        carried = {}
        last_nav_is_delivery = False
        goal_frozen = True
        for state in states:
            accepted = [a for a in state.get('native_actions', [])
                        if a.get('label') == 'Nav2' and a.get('accepted') is True]
            if accepted:
                last_nav_is_delivery = accepted[-1].get('carrying') is True
            for action in accepted:
                if action.get('carrying') is not True:
                    continue
                identifier = action.get('uuid')
                identifier_ok = (isinstance(identifier, str) and len(identifier) == 32
                                 and all(ch in '0123456789abcdef' for ch in identifier))
                goal = pose(action.get('goal_pose'))
                goal_frozen &= identifier_ok and goal == target and target is not None
                if identifier_ok:
                    if identifier in carried:
                        goal_frozen &= carried[identifier] == goal
                    carried[identifier] = goal
        native_id = next(iter(carried)) if len(carried) == 1 else None
        active = False
        terminal = None
        for record in sorted(records, key=lambda r: r.get('received_wall_time', 0.)):
            if not start <= record.get('received_wall_time', 0.) <= end + 1.:
                continue
            if record['topic'] == 'nav_feedback' and uuid_hex(record['payload']['goal_id']['uuid']) == native_id:
                active = True
            if record['topic'] == 'nav_status':
                for status in record['payload'].get('status_list', []):
                    if uuid_hex(status['goal_info']['goal_id']['uuid']) == native_id:
                        active |= status['status'] in (1, 2, 3)
                        terminal = status['status']
        native = bool(native_id and goal_frozen and last_nav_is_delivery and active and terminal == 4)
        gate = oracle.Gate(1.)
        placed = attempt.get('released_full_footprint_supported_and_relative_rest', {}).get('first_pass_stamp')
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
            'carrying_nav_uuid': native_id, 'carrying_nav_sent_goal_matches': bool(goal_frozen and native_id),
            'last_nav_is_delivery': last_nav_is_delivery, 'native_uuid_active_observed': active,
            'native_uuid_terminal_status': terminal, 'native_uuid_success_independently_observed': native,
            'goal_request_evidence': 'bridge_pre_send_frozen_goal_and_accepted_handle_HTTP_snapshot',
            'native_status_evidence': 'independently_subscribed_ROS_action_status_and_feedback',
            'goal_request_independently_observed': False, 'native_goal_consumption_ack_claimed': False,
            'final_true_pose_error': errors, 'final_true_pose_and_cargo_stop': gate.result(),
            'position_tolerance_m': .04, 'yaw_tolerance_rad': .05, 'continuous_final_dwell_s': 1.,
            'threshold_basis': 'original_physical_dock_pose_tolerances_and_original_final_rest_dwell',
            'passed': bool(binding and native and settled)})
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
        if record['topic'] in ('dock_status','nav_status') and record['received_wall_time'] <= end:
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
        if start.get('kind') not in ('dock_started','full_started'):continue
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


def augment_score(value, records, samples, audit, events):
    scope=getattr(options,'scope','transport'); outcome=getattr(options,'expected_outcome','success')
    extra = extra_checks(records, options.markers, options.expected_episode,
                         reset_receipt=options.reset_receipt,
                         allow_initial_episode=options.allow_initial_episode,scope=scope,expected_outcome=outcome)
    handoff = transport_checks(samples, audit, value.get('full_attempts', []), events) if audit else {'passed': False, 'windows': []}
    delivery = (delivery_checks(records, samples, audit, value.get('full_attempts', []), events)
                if audit and scope == 'transport' else {'required': False, 'passed': True, 'attempts': []})
    value['original_k_oracle_passed'] = value['passed']
    value['repeated_episode_acceptance'] = extra
    value['continuous_handoff_and_transport'] = handoff
    value['task_delivery_acceptance'] = delivery
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
    parser.add_argument('--scope',choices=('dock','transport'),default='transport')
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
    oracle.observe(options)
    files = list(options.output.glob('score-*.json'))
    return 0 if len(files) == 1 and json.loads(files[0].read_text()).get('passed') is True else 1


if __name__ == '__main__':
    sys.exit(main())
