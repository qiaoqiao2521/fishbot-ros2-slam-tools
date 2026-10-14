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


def extra_checks(records, marker_path, expected, *, reset_receipt=None, allow_initial_episode=False):
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
    for start in (e for e in events if e.get('kind') == 'full_started'):
        ends = [e for e in events if e.get('kind') == 'full_finished' and e.get('task_id') == start['task_id'] and e['wall_time'] >= start['wall_time']]
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
        native = bool(action_ids) and any(k[0] == 'dock' for k in action_ids) and any(k[0] == 'nav' for k in action_ids) and all(terminal.get(k) == 4 for k in action_ids)
        http = [r['payload'] for r in records if r['topic'] == 'http_state' and r['payload'].get('task', {}).get('id') == start['task_id']]
        terminal_task = bool(http) and http[-1]['task']['status'] == 'succeeded'
        windows.append({'task_id': start['task_id'], 'wall_start': start['wall_time'], 'wall_end': end,
                        'first_source_stamp': items[0]['source_stamp'] if items else None,
                        'last_source_stamp': items[-1]['source_stamp'] if items else None,
                        'episode_fixed': bool(items) and all(episode_id(x['payload']) == expected for x in items),
                        'native_actions': [{'kind': k[0], 'uuid': k[1], 'terminal_status': terminal.get(k)} for k in sorted(action_ids)],
                        'all_native_success': native, 'terminal_task_success': terminal_task,
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
    all_windows = bool(windows) and all(w['episode_fixed'] and w['all_native_success'] and w['terminal_task_success'] and w['closed'] for w in windows)
    return {'expected_episode_id': expected, 'episode_identity_fixed': identity,
            'source_monotonic': monotonic, 'first_contact_counters': first_contacts,
            'reset_count_fixed': reset_count_fixed,
            'reset_count': reset_counts[0] if reset_counts else None,
            'all_episode_contact_totals_zero': contacts, 'windows': windows,
            'reset_receipt': receipt, 'reset_receipt_precedes_collection_and_tasks': bool(receipt_ok),
            'reset_receipts_inside_task': receipt_inside_task,
            'original_full_score_reused': True,
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


def augment_score(value, records, samples, audit, events):
    extra = extra_checks(records, options.markers, options.expected_episode,
                         reset_receipt=options.reset_receipt,
                         allow_initial_episode=options.allow_initial_episode)
    handoff = transport_checks(samples, audit, value.get('full_attempts', []), events) if audit else {'passed': False, 'windows': []}
    value['original_k_oracle_passed'] = value['passed']
    value['repeated_episode_acceptance'] = extra
    value['continuous_handoff_and_transport'] = handoff
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
    value['passed'] = bool(value['passed'] and extra['passed'] and handoff['passed'] and not callback_errors and current_ok)
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
    parser.add_argument('--duration', type=float)
    parser.add_argument('--markers', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--score-only', type=Path)
    result = parser.parse_args(argv)
    if not result.expected_episode.strip():
        parser.error('--expected-episode must be nonempty')
    if result.duration is not None and (not finite(result.duration) or result.duration <= 0):
        parser.error('--duration must be finite and positive')
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
