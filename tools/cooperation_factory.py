#!/usr/bin/env python3
"""Evaluate prepared factory orders through the existing cooperation stack.

The adapter owns one local launch. It never implements navigation, scheduling,
physical scoring, retries, or recovery of an unknown task. ``--dry-run`` does
not import ROS, launch processes, create a ledger, or send HTTP requests.
"""
from __future__ import annotations

import argparse
from collections import deque
import copy
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import uuid

from cooperation_acceptance import (
    EvidenceTail, ensure_port_available, finish_observer, lifecycle_active,
    native_cleanup_known, private_json, protected_snapshot, rejected_submission_cleanup_known,
    signal_observer_once,
    stop_non_motion_child, stop_owned_launch, wait_until,
)
from cooperation_workflow import LocalBridge, Workflow, read_json
from cooperation_delivery_route import DELIVERY_ROUTE_WALL_S

ROOT = Path(__file__).resolve().parents[1]
TASK_TIMEOUT_S = 360.
TOTAL_TIMEOUT_S = 1000.
PROTECTED_UNITS = (
    'fishbot-cooperation-114-repeat-4fee1ea1.service',
    'fishbot-map-rules-simulation-107-fadd107c.service',
    'fishbot-map-rules-backend-107-fadd107c.service',
    'fishbot-map-rules-frontend-107-fadd107c.service',
    'fishbot-map-rules-mission-107-rviz.service',
    'fishbot-map-rules-rosbridge-107-fadd107c.service',
)


def protected_units(args):
    """A remote container has no local demo services; never invent snapshots."""
    if getattr(args, 'isolated_runtime', False):
        return ()
    return tuple(getattr(args, 'protected_unit', None) or PROTECTED_UNITS)


def save(path, value):
    path = Path(path)
    private_json(path, value, replace=path.exists())


class MarkedBridge(LocalBridge):
    """Observe the original durable intent before its one mutation request."""
    def __init__(self, endpoint, before_post):
        super().__init__(endpoint)
        self.before_post = before_post

    def post(self, kind, body):
        self.before_post(kind, body)
        return super().post(kind, body)


def reference(manifest, *, candidate, order=None):
    """Resolve scene business data; candidate is a display label, not a loader."""
    from cooperation_factory_scene import factory_template_jobs, normalize_factory_config
    batches, targets, profile = factory_template_jobs(manifest)
    factory = normalize_factory_config(manifest['factory_delivery'])
    destinations = {station['id']: station for station in factory['destinations']}
    orders = copy.deepcopy(factory['orders'])
    if len(orders) != 2 or len(batches) != len(orders):
        raise ValueError('F1 requires exactly two declared orders')
    declared = [item['id'] for item in orders]
    selected = declared if order is None else list(order)
    if len(selected) != len(declared) or set(selected) != set(declared):
        raise ValueError('--order must be a permutation of all declared order IDs')
    by_id = {item['id']: (item, batch) for item, batch in zip(orders, batches)}
    resolved = []
    for name in selected:
        item, batch = by_id[name]
        resolved.append({**item, 'batch_id': batch, 'delivery_pose': targets[batch],
                         'delivery_approach_poses': copy.deepcopy(
                             destinations[item['destination_id']].get('approach_poses', []))})
    return {'scene_id': factory['id'], 'candidate_label': candidate,
            'scene_profile': profile, 'orders': resolved,
            'task_timeout_wall_s': TASK_TIMEOUT_S,
            'delivery_route_budget_wall_s': DELIVERY_ROUTE_WALL_S,
            'delivery_route_budget_boundary': 'after_required_egress_through_final_nav_stop_and_hold',
            'total_timeout_wall_s': TOTAL_TIMEOUT_S,
            'budget_semantics': 'Acceptance limits; safe cleanup and scoring may extend execution',
            'candidate_label_loads_code': False}


def loaded_code_reference():
    """Observe actual local code, without a content-hash execution lock."""
    import cooperation_acceptance
    import cooperation_factory_scene
    import cooperation_workflow
    modules = (sys.modules[__name__], cooperation_acceptance,
               cooperation_factory_scene, cooperation_workflow)
    module_files = {module.__name__: str(Path(module.__file__).resolve()) for module in modules}
    runtime_files = [ROOT/'tools'/name for name in
                     ('cooperation_bridge.py', 'cooperation_sim.py', 'cooperation_lidar.py', 'cooperation_oracle.py',
                      'cooperation_oracle_base.py', 'cooperation_core.py', 'cooperation_arm.py',
                      'cooperation_factory_policy.py', 'cooperation_delivery_route.py')]
    paths = [Path(path) for path in module_files.values()]+runtime_files
    result = {'module_files': module_files,
              'module_files_scope': 'Actually imported in the evaluation process',
              'runtime_entrypoint_source_files': [str(path) for path in runtime_files],
              'runtime_module_import_receipt_claimed': False,
              'selected_source_text': {}, 'observation_errors': []}
    for path in paths:
        try:
            result['selected_source_text'][str(path)] = path.read_text()
        except (OSError, UnicodeError) as error:
            result['observation_errors'].append(str(error))
    for key, arguments in (
            ('git_head', ['rev-parse', 'HEAD']),
            ('git_status', ['status', '--short']),
            ('tracked_dirty_diff', ['diff', '--no-ext-diff', '--', 'tools'])):
        try:
            result[key] = subprocess.check_output(['git', *arguments], cwd=ROOT, text=True)
        except (OSError, subprocess.SubprocessError) as error:
            result['observation_errors'].append(str(error))
    return result


def order_report(order, *, task_id, episode_id, terminal, score, score_file,
                 elapsed_wall_s):
    """Summarize original scores; do not reproduce physical verdict logic."""
    delivery = score.get('task_delivery_acceptance', {}) if score else {}
    attempts = [item for item in delivery.get('attempts', [])
                if item.get('task_id') == task_id and item.get('episode_id') == episode_id]
    attempt = attempts[0] if len(attempts) == 1 else {}
    bound = (len(attempts) == 1 and
             attempt.get('expected_delivery_pose') == order['delivery_pose'] and
             attempt.get('expected_delivery_approach_poses', []) == order.get('delivery_approach_poses', []))
    verdict = 'unknown' if score is None else 'passed' if (
        score.get('passed') is True and score.get('original_k_oracle_passed') is True
        and delivery.get('required') is True and delivery.get('passed') is True
        and bound and attempt.get('passed') is True) else 'failed'
    pose_error = attempt.get('final_true_pose_error') or {}
    rest = attempt.get('final_true_pose_and_cargo_stop') or {}
    status = terminal.get('task', {}).get('status') if terminal else None
    valid_elapsed = (type(elapsed_wall_s) in (int, float)
                     and math.isfinite(elapsed_wall_s) and elapsed_wall_s >= 0.)
    return {**copy.deepcopy(order), 'task_id': task_id, 'episode_id': episode_id,
            'execution': {'task_status': status,
                          'terminal_observed': status in ('succeeded', 'failed', 'canceled'),
                          'within_task_budget': elapsed_wall_s <= TASK_TIMEOUT_S if valid_elapsed else None},
            'task_verdict': verdict, 'original_score_passed': None if score is None else score.get('passed'),
            'original_k_passed': None if score is None else score.get('original_k_oracle_passed'),
            'destination_bound': bound, 'carrying_nav_uuid': attempt.get('carrying_nav_uuid'),
            'expected_egress_pose': attempt.get('expected_egress_pose'),
            'egress_required': attempt.get('egress_required', False),
            'native_route': attempt.get('carrying_nav_route', []),
            'delivery_route_budget': attempt.get('delivery_route_budget'),
            'metrics': {'elapsed_wall_s': elapsed_wall_s,
                        'final_position_error_m': pose_error.get('position_m'),
                        'final_yaw_error_rad': pose_error.get('yaw_rad'),
                        'continuous_final_stop_source_s': rest.get('longest_source_duration_s')},
            'score_file': None if score_file is None else str(score_file),
            'failure_reason': None if verdict == 'passed' else
                ('Original independent score unavailable' if score is None else
                 'Original independent score or task-bound delivery failed; inspect score_file'),
            'guard_telemetry': None if score is None else score.get('plant_guard_telemetry')}


def summarize(result):
    orders = result.get('orders', [])
    expected = len(result['declaration']['orders'])
    complete = (len(orders) == expected and {item['id'] for item in orders} ==
                {item['id'] for item in result['declaration']['orders']})
    identity = complete and all(len({item.get(key) for item in orders}) == expected
                                and all(item.get(key) for item in orders)
                                for key in ('task_id', 'episode_id', 'batch_id', 'carrying_nav_uuid'))
    verdicts = [item['task_verdict'] for item in orders]
    result['task_verdict'] = ('failed' if 'failed' in verdicts else 'passed'
                              if identity and all(v == 'passed' for v in verdicts) else 'unknown')
    result['independent_order_identities_distinct'] = identity
    execution = result['execution']
    execution['within_task_budgets'] = complete and all(
        item.get('execution', {}).get('within_task_budget') is True for item in orders)
    execution['status'] = ('unknown' if execution.get('retained_launch_pid')
                           or execution.get('retained_observer_pid')
                           or execution.get('retained_non_motion_pids') else
                           'failed' if result['errors'] else 'completed' if complete else 'incomplete')
    result['passed'] = (result['task_verdict'] == 'passed'
                        and execution['status'] == 'completed'
                        and all(execution.get(key) is True for key in
                                ('cleanup_complete', 'owned_launch_stopped', 'owned_port_closed',
                                 'protected_instances_unchanged', 'within_total_budget',
                                 'within_task_budgets')))
    result['unexecuted_order_ids'] = [item['id'] for item in result['declaration']['orders']
                                     if item['id'] not in {order['id'] for order in orders}]
    return result


def cleanup_proof(state, native, task_id, episode, quiet, *, submission_rejected=False):
    """Only an exact terminal task can authorize reclaiming its owned launch."""
    if submission_rejected:
        known = rejected_submission_cleanup_known(state, native, episode)
    else:
        task = state.get('task', {})
        known = (state.get('episode_id') == episode and task.get('id') == task_id
                 and task.get('status') in ('succeeded', 'failed', 'canceled')
                 and native_cleanup_known(state, native, task_id, episode))
    if not known:
        return None
    proof = quiet(episode)
    return {'state': state, 'proof': proof} if proof else None


def protection_observation(before, after):
    """Compare only configured unit snapshots; absence never proves a live robot."""
    def inventory(snapshot):
        active, running = [], []
        for unit, raw in snapshot.items():
            fields = dict(line.split('=', 1) for line in str(raw).splitlines() if '=' in line)
            if fields.get('ActiveState') == 'active':
                active.append(unit)
                pid = fields.get('MainPID', '')
                if pid.isdecimal() and int(pid) > 0:
                    running.append(unit)
        return active, running
    active_before, running_before = inventory(before)
    active_after, running_after = inventory(after)
    return {'protected_comparison_scope': 'Explicitly configured systemd unit snapshots only; '
                'no global process or ROS instance discovery',
            'configured_systemd_units': list(before),
            'configured_systemd_units_unchanged': before == after,
            'protected_instances_unchanged': before == after,  # Legacy comparison field.
            'active_before': active_before, 'active_after': active_after,
            'running_configured_units_before': running_before,
            'running_configured_units_after': running_after,
            'historical_instances_were_running': bool(running_before),
            'historical_running_semantics': 'At least one configured unit was active with '
                'a nonzero MainPID; does not claim all historical ROS instances were running'}


class ReadOnlyMonitor:
    """Existing private-runner monitor reduced to reset/quiet evidence only."""
    def __init__(self):
        import rclpy
        from geometry_msgs.msg import PoseStamped
        from nav_msgs.msg import Odometry
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
        from rosgraph_msgs.msg import Clock
        from rosidl_runtime_py.convert import message_to_ordereddict
        from std_msgs.msg import String
        self.rclpy, self.convert = rclpy, message_to_ordereddict
        self.lock = threading.Lock()
        self.tail = EvidenceTail(Path('/unused-factory-live-monitor'))
        rclpy.init()
        self.node = rclpy.create_node('factory_independent_reset_quiet')
        self.executor = SingleThreadedExecutor()
        self.executor.add_node(self.node)
        self.subscriptions = []
        for topic, kind, path in (
                ('physics', String, '/cooperation/physics_state'),
                ('truth', Odometry, '/ground_truth/odom'),
                ('cargo', PoseStamped, '/cooperation/cargo_pose'),
                ('clock', Clock, '/clock'),
                ('reset_receipt', String, '/cooperation/reset_result')):
            qos = (QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE)
                   if topic == 'reset_receipt' else qos_profile_sensor_data)
            self.subscriptions.append(self.node.create_subscription(
                kind, path, lambda message, name=topic: self.record(name, message), qos))
        self.worker = threading.Thread(target=self.executor.spin, daemon=True)
        self.worker.start()

    def record(self, topic, message):
        value = json.loads(message.data) if topic in ('physics', 'reset_receipt') else self.convert(message)
        stamp = (value.get('reset_stamp') if topic == 'reset_receipt' else value['stamp']
                 if topic == 'physics' else message.clock.sec+message.clock.nanosec*1e-9
                 if topic == 'clock' else message.header.stamp.sec+message.header.stamp.nanosec*1e-9)
        with self.lock:
            self.tail.records.append({'topic': topic, 'source_stamp': stamp,
                                      'received_wall_time': time.time(), 'payload': value})

    def records(self):
        with self.lock:
            return list(self.tail.records)

    def quiet(self, episode):
        records = self.records()
        physics = [item for item in records if item['topic'] == 'physics']
        if not physics or physics[-1]['payload'].get('episode_id') != episode:
            return None
        trial = EvidenceTail(Path('/unused-factory-live-monitor'))
        trial.records = deque(records, maxlen=20000)
        trial.oracle, trial.audit = self.tail.oracle, self.tail.audit
        proof = trial.quiet_proof()
        self.tail.oracle, self.tail.audit = trial.oracle, trial.audit
        return proof

    def reset_proof(self, request_id, episode):
        records = self.records()
        receipts = [item for item in records if item['topic'] == 'reset_receipt'
                    and item['payload'].get('request_id') == request_id
                    and item['payload'].get('new_episode_id') == episode
                    and item['payload'].get('status') == 'succeeded']
        physics = [item for item in records if item['topic'] == 'physics'
                   and item['payload'].get('episode_id') == episode]
        if not receipts or not physics:
            return None
        receipt, raw = receipts[-1], physics[-1]['payload']
        stamp = receipt['payload'].get('reset_stamp')
        if (not isinstance(stamp, (int, float))
                or raw.get('episode_reset', {}).get('stamp') != stamp or not stamp < raw['stamp']):
            return None
        return {'reset_receipt': receipt['payload'],
                'origin': 'independent /cooperation/reset_result',
                'physics_crosscheck': {'stamp': raw['stamp'], 'sequence': raw['sequence'],
                                      'episode_id': raw['episode_id']}}

    def close(self):
        self.executor.shutdown(timeout_sec=2)
        self.worker.join(timeout=2)
        self.node.destroy_node()
        self.rclpy.try_shutdown()


def run(args, manifest, declaration):
    from fishbot_simulation_suite import domain_is_empty
    output = args.output.resolve()
    if output.exists() or output.is_relative_to(ROOT):
        raise ValueError('Use a new private output directory outside the source repository')
    ensure_port_available(args.port)
    env = dict(os.environ, FISHBOT_COOP_PYTHON=str(args.planning_python),
               FISHBOT_COOP_DOMAIN=str(args.domain), FISHBOT_MUJOCO_DOMAIN_ID=str(args.domain),
               ROS_DOMAIN_ID=str(args.domain), ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST',
               ROS_LOCALHOST_ONLY='1', ROS_STATIC_PEERS='')
    os.environ.update({key: env[key] for key in
                       ('ROS_DOMAIN_ID', 'FISHBOT_COOP_DOMAIN', 'FISHBOT_MUJOCO_DOMAIN_ID',
                        'ROS_AUTOMATIC_DISCOVERY_RANGE', 'ROS_LOCALHOST_ONLY', 'ROS_STATIC_PEERS')})
    domain_is_empty(timeout=5)
    output.mkdir(mode=0o700, parents=True)
    started = time.monotonic()
    result = {'schema': 1, 'run_id': str(uuid.uuid4()), 'declaration': declaration,
              'manifest': str(args.manifest.resolve()), 'domain': args.domain, 'port': args.port,
              'execution': {}, 'orders': [], 'errors': [], 'task_verdict': 'unknown', 'passed': False}
    result['execution']['started_wall_time'] = time.time()
    source_start = loaded_code_reference()
    save(output/'loaded-code-start.json', source_start)
    save(output/'manifest-used.json', manifest)
    save(output/'declaration.json', declaration)
    units = protected_units(args)
    result['execution']['host_protection_scope'] = {
        'isolated_runtime': bool(getattr(args, 'isolated_runtime', False)),
        'configured_units': list(units), 'owned_launch_cleanup_required': True}
    protected = protected_snapshot(units)
    save(output/'protected-before.json', protected)
    launcher = ROOT/'tools/fishbot_cooperation.sh'
    ledger = output/'workflow.json'
    launch = observer = monitor = geometry = policy_process = None
    runtime_manifest = args.manifest.resolve()
    streams = []
    episode = task_id = current_folder = tail = current_order = None
    task_rejected = False
    order_started = task_elapsed = None
    mutation_posts = []

    def spawn(command, name):
        stream = (output/(name+'.log')).open('x')
        os.chmod(stream.name, 0o600)
        streams.append(stream)
        return subprocess.Popen(command, cwd=ROOT, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, start_new_session=True)

    def checkpoint():
        if time.monotonic()-started > TOTAL_TIMEOUT_S:
            raise TimeoutError('Original declared 1000s F1 run budget exceeded')

    def ready():
        checkpoint()
        if launch.poll() is not None:
            raise RuntimeError('Owned launch exited')
        try:
            state = bridge.state()
        except RuntimeError:
            return None
        return state if (state.get('ready') is True and state.get('domain') == args.domain
                         and state.get('scene_profile') == declaration['scene_profile']
                         and lifecycle_active(state.get('native_lifecycle', {}))) else None

    def workflow(method, *values, **kwargs):
        checkpoint()
        with Workflow(ledger, bridge) as value:
            return getattr(value, method)(*values, **kwargs)

    def marker(kind, **fields):
        path = current_folder/'markers.json'
        value = read_json(path)
        value['events'].append({'kind': kind, 'wall_time': time.time(),
                                'task_id': task_id, 'episode_id': episode, **fields})
        save(path, value)

    def before_post(kind, body):
        nonlocal task_id
        mutation_posts.append({'kind': kind, 'body': copy.deepcopy(body),
                               'wall_time': time.time()})
        save(output/'mutation-intents.json', mutation_posts)
        if kind == 'start':
            task_id = body['task_id']
            marker('full_started', scope='transport',
                   expected_delivery_pose=current_order['delivery_pose'],
                   requested_delivery_pose=body.get('delivery_pose'),
                   expected_delivery_approach_poses=current_order.get('delivery_approach_poses', []),
                   requested_delivery_approach_poses=body.get('delivery_approach_poses', []))

    bridge = MarkedBridge('http://127.0.0.1:'+str(args.port), before_post)

    def clean():
        if task_id is None or monitor is None:
            return None
        tail.refresh()
        state = bridge.state()
        return cleanup_proof(state, tail.native(), task_id, episode, monitor.quiet,
                             submission_rejected=task_rejected)

    def independent_cleanup():
        proof = wait_until(clean, 20, description='Native terminal/held/guard-off quiet unavailable')
        begin = proof['proof']['source_stamp']
        def dwell():
            current = clean()
            return current if current and current['proof']['source_stamp']-begin >= 1. else None
        return wait_until(dwell, 20, description='Independent cleanup source dwell incomplete')

    try:
        if getattr(args, 'policy_config', None) is not None:
            policy_receipt = output/'policy-receipt.json'
            derived = output/'derived-manifest.json'
            result['policy'] = {'execution_status': 'not_completed',
                                'receipt_file': str(policy_receipt),
                                'worker_timeout_wall_s': 30., 'candidate_label_loads_code': False}
            policy_process = spawn([
                str(args.planning_python), '-B', str(ROOT/'tools/cooperation_factory_policy.py'),
                '--manifest', str(args.manifest.resolve()), '--config', str(args.policy_config.resolve()),
                '--output-manifest', str(derived), '--receipt', str(policy_receipt),
                '--declaration', str(output/'declaration.json')], 'policy')
            policy_process.wait(timeout=30)
            if policy_receipt.exists():
                result['policy'].update(read_json(policy_receipt))
            if policy_process.returncode != 0 or result['policy'].get('execution_status') != 'succeeded':
                raise RuntimeError('Factory policy failed; no baseline fallback: '+
                                   str(result['policy'].get('failure_reason', 'worker receipt unavailable')))
            manifest = read_json(derived)
            runtime_manifest = derived.resolve()
            result.update(input_manifest=str(args.manifest.resolve()), manifest=str(runtime_manifest))
            save(output/'manifest-used.json', manifest)
        geometry = spawn([str(args.planning_python), '-B',
                          str(ROOT/'tools/cooperation_geometry_check.py'),
                          '--manifest', str(runtime_manifest),
                          '--output', str(output/'geometry.json')], 'geometry')
        geometry.wait(timeout=60)
        geometry_report = read_json(output/'geometry.json') if (output/'geometry.json').exists() else {}
        result['execution']['geometry_preflight'] = {
            'report': str(output/'geometry.json'), 'returncode': geometry.returncode,
            'passed': geometry_report.get('passed') is True,
            'is_delivery_score': False}
        if geometry.returncode != 0 or geometry_report.get('passed') is not True:
            raise RuntimeError('Original scene geometry preflight failed; no world launched')
        command = [str(launcher), 'run', 'manifest:='+str(runtime_manifest),
                   'output:='+str(output/'runtime'), 'domain:='+str(args.domain),
                   'port:='+str(args.port), 'record_state:=false']
        command.append('publication_mode:='+getattr(args, 'publication_mode', 'source'))
        result['execution']['launch_command'] = command
        launch = spawn(command, 'launch')
        monitor = ReadOnlyMonitor()
        initial = wait_until(ready, 65, description='Original native readiness unavailable')
        result['execution']['actual_initial_source'] = initial.get('source')
        declared = declaration['orders']
        workflow('create', [item['batch_id'] for item in declared], 'factory-pickup',
                 {item['batch_id']: item['delivery_pose'] for item in declared},
                 scene_profile=declaration['scene_profile'],
                 delivery_approach_poses={item['batch_id']: item['delivery_approach_poses'] for item in declared})
        reset_receipt = None
        for index, order in enumerate(declared):
            current_order = order
            task_elapsed = None
            task_rejected = False
            state = wait_until(ready, 20, description='New episode not ready')
            episode, task_id = state['episode_id'], None
            current_folder = output/('order-'+str(index+1))
            current_folder.mkdir(mode=0o700)
            save(current_folder/'markers.json', {'events': []})
            arguments = [str(launcher), 'oracle', '--domain', str(args.domain),
                         '--api', bridge.endpoint+'/coop-api', '--expected-episode', episode,
                         '--scope', 'transport', '--expected-outcome', 'success',
                         '--markers', str(current_folder/'markers.json'),
                         '--output', str(current_folder/'observer')]
            arguments += (['--reset-receipt', str(reset_receipt)] if reset_receipt
                          else ['--allow-initial-episode'])
            observer = spawn(arguments, 'order-'+str(index+1)+'-oracle')
            tail = EvidenceTail(current_folder/'observer/observer.jsonl')
            def observing():
                if observer.poll() is not None:
                    raise RuntimeError('Original oracle exited before dispatch')
                tail.refresh()
                return (any(item['topic'] == 'physics' for item in tail.records)
                        and any(item['topic'] == 'publisher_inventory' for item in tail.records))
            wait_until(observing, 15, description='Independent observer discovery unavailable')
            wait_until(ready, 10, description='Dispatch readiness unavailable')
            workflow('event', {'event_id': str(uuid.uuid4()), 'batch_id': order['batch_id'],
                               'machine_id': 'factory-pickup', 'version': index+1, 'ready': True})
            # Workflow persists the UUID, then MarkedBridge records its marker
            # before the original one POST. Sampling never starts retrospectively.
            order_started = time.monotonic()
            value = workflow('dispatch')
            task_id = value['jobs'][index]['attempts'][-1]['task_id']
            task_rejected = value['jobs'][index]['attempts'][-1]['dispatch']['outcome'] == 'rejected'
            terminal = None
            while time.monotonic()-order_started < TASK_TIMEOUT_S:
                checkpoint()
                tail.refresh()
                state = bridge.state()
                if task_rejected:
                    terminal = state
                    task_elapsed = time.monotonic()-order_started
                    break
                if state.get('task', {}).get('id') != task_id:
                    raise RuntimeError('Original task identity disappeared; no resend')
                workflow('tick')
                if state['task']['status'] in ('succeeded', 'failed', 'canceled', 'unknown'):
                    terminal = state
                    task_elapsed = time.monotonic()-order_started
                    break
                if launch.poll() is not None or observer.poll() is not None:
                    raise RuntimeError('Owned launch or oracle exited during task')
                time.sleep(.1)
            if terminal is None:
                raise TimeoutError('Original 360s task limit exceeded; no automatic resend')
            marker('full_finished', scope='transport')
            save(current_folder/'terminal-state.json', terminal)
            proof = independent_cleanup()
            save(current_folder/'cleanup-quiet.json', proof)
            marker('cleanup_checked')
            signal_observer_once(observer)
            code = finish_observer(observer, 120)
            if code is None:
                raise RuntimeError('Original observer still scoring; retain process')
            scores = list((current_folder/'observer').glob('score-*.json'))
            score_file = scores[0] if len(scores) == 1 else None
            score = read_json(score_file) if score_file else None
            item = order_report(order, task_id=task_id, episode_id=episode, terminal=terminal,
                                score=score, score_file=score_file,
                                elapsed_wall_s=task_elapsed)
            item['observer_returncode'] = code
            result['orders'].append(item)
            save(output/'progress.json', result)
            observer = None
            if item['task_verdict'] != 'passed':
                break  # Retain this failure; never reset/retry an unknown outcome.
            if index < len(declared)-1:
                old_episode = episode
                reset = workflow('reset')
                request_id = reset['resets'][-1]['request_id']
                def reset_done():
                    value = workflow('tick')
                    if value['status'] == 'unknown':
                        raise RuntimeError('Original reset outcome unknown; no retry')
                    state = bridge.state()
                    return state if (value['status'] == 'waiting_ready'
                                     and state['episode_id'] != old_episode
                                     and state['episode_id'] == value['episode_id']
                                     and state.get('ready') is True) else None
                new = wait_until(reset_done, 25, description='Original reset ACK unavailable')
                proof = wait_until(lambda: monitor.reset_proof(request_id, new['episode_id']), 10,
                                   description='Independent reset/physics crosscheck unavailable')
                reset_receipt = output/('reset-'+request_id+'.json')
                save(reset_receipt, proof)
        final = independent_cleanup()
        save(output/'final-cleanup-quiet.json', final)
        result['execution']['cleanup_complete'] = True
        result['execution']['owned_launch_stopped'] = stop_owned_launch(launch, result)
    except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.SubprocessError,
            KeyboardInterrupt) as error:
        result['errors'].append(type(error).__name__+': '+str(error))
        if launch is not None and launch.poll() is None and task_id is not None and tail is not None:
            try:
                proof = independent_cleanup()
                save(output/'failure-cleanup-quiet.json', proof)
                result['execution']['cleanup_complete'] = True
                if observer is not None:
                    signal_observer_once(observer)
                result['execution']['owned_launch_stopped'] = stop_owned_launch(launch, result)
                if observer is not None:
                    finish_observer(observer, 120)
            except (OSError, RuntimeError, TimeoutError) as cleanup_error:
                result['errors'].append('cleanup: '+str(cleanup_error))
    finally:
        result['execution']['retained_non_motion_pids'] = []
        for name, process in (('policy', policy_process), ('geometry', geometry)):
            if process is not None:
                result['execution']['retained_non_motion_pids'].extend(
                    stop_non_motion_child(process, name, result))
        result['execution']['retained_launch_pid'] = (launch.pid if launch is not None
                                                     and launch.poll() is None else None)
        result['execution']['retained_observer_pid'] = (observer.pid if observer is not None
                                                       and observer.poll() is None else None)
        with socket.socket() as probe:
            result['execution']['owned_port_closed'] = probe.connect_ex(('127.0.0.1', args.port)) != 0
        protected_after = protected_snapshot(units)
        save(output/'protected-after.json', protected_after)
        result['execution'].update(protection_observation(protected, protected_after))
        result['execution']['protected_snapshots'] = {
            'before': str(output/'protected-before.json'), 'after': str(output/'protected-after.json')}
        result['execution']['elapsed_wall_s'] = time.monotonic()-started
        result['execution']['within_total_budget'] = result['execution']['elapsed_wall_s'] <= TOTAL_TIMEOUT_S
        result['execution']['ended_wall_time'] = time.time()
        result['execution']['mutation_posts'] = {
            kind: sum(item['kind'] == kind for item in mutation_posts)
            for kind in ('start', 'cancel', 'reset')}
        if (current_order is not None and task_id is not None
                and not any(item['task_id'] == task_id for item in result['orders'])):
            scores = list((current_folder/'observer').glob('score-*.json'))
            score_file = scores[0] if len(scores) == 1 else None
            terminal_path = current_folder/'terminal-state.json'
            terminal = read_json(terminal_path) if terminal_path.exists() else None
            result['orders'].append(order_report(
                current_order, task_id=task_id, episode_id=episode, terminal=terminal,
                score=read_json(score_file) if score_file else None, score_file=score_file,
                elapsed_wall_s=task_elapsed))
        source_end = loaded_code_reference()
        save(output/'loaded-code-end.json', source_end)
        result['code_observation'] = {'start': str(output/'loaded-code-start.json'),
                                      'end': str(output/'loaded-code-end.json'),
                                      'selected_text_unchanged': source_start['selected_source_text'] ==
                                      source_end['selected_source_text'],
                                      'source_change_blocks_execution': False}
        if monitor is not None:
            monitor.close()
        for stream in streams:
            stream.close()
        summarize(result)
        save(output/'result.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    execute = sub.add_parser('run')
    execute.add_argument('--manifest', type=Path, required=True)
    execute.add_argument('--output', type=Path, required=True)
    execute.add_argument('--domain', type=int, default=141)
    execute.add_argument('--port', type=int, default=9111)
    execute.add_argument('--candidate', default='baseline', help='Display label; does not load code')
    execute.add_argument('--publication-mode', choices=('source', 'asynchronous'), default='source',
                         help='Fast DDS publication candidate for simulator and task bridge only')
    execute.add_argument('--policy-config', type=Path,
                         help='Explicit trusted local policy JSON; loads only during run')
    execute.add_argument('--order', action='append', help='Explicit permutation of all order IDs')
    execute.add_argument('--planning-python', type=Path,
                         default=Path.home()/'.cache/so101-colab/planning-venv/bin/python')
    protection = execute.add_mutually_exclusive_group()
    protection.add_argument('--protected-unit', action='append')
    protection.add_argument('--isolated-runtime', action='store_true',
                            help='Cloud/container has no host demo services; owned cleanup remains required')
    execute.add_argument('--dry-run', action='store_true')
    report = sub.add_parser('report')
    report.add_argument('--run', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'report':
            result = summarize(read_json(args.run/'result.json'))
        else:
            if not 1 <= args.domain <= 232 or args.domain in (107, 114):
                raise ValueError('Choose an isolated domain; preserve 107/114')
            if not 1024 <= args.port <= 65535:
                raise ValueError('Choose an unprivileged TCP port')
            manifest = read_json(args.manifest)
            declaration = reference(manifest, candidate=args.candidate, order=args.order)
            declaration['publication_mode'] = {
                'requested': args.publication_mode,
                'process_scope': ['cooperation_sim', 'cooperation_bridge'],
                'changes_qos_or_freshness_thresholds': False,
            }
            if args.policy_config is not None:
                from cooperation_factory_policy import describe_config, require_supported
                require_supported(manifest)
                declaration['policy_request'] = describe_config(args.policy_config)
            if args.dry_run:
                code = loaded_code_reference()
                result = {'dry_run': True, 'ROS_initialized': False, 'actions_started': False,
                          'declaration': declaration, 'manifest': str(args.manifest.resolve()),
                          'output': str(args.output.resolve()), 'loaded_code': {
                              key: code[key] for key in ('module_files', 'git_head', 'git_status',
                                                        'observation_errors') if key in code}}
            else:
                result = run(args, manifest, declaration)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
        return 0 if result.get('dry_run') or result.get('passed') is True else 1
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({'execution': {'status': 'failed'}, 'task_verdict': 'unknown',
                          'error': type(error).__name__+': '+str(error)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
