#!/usr/bin/env python3
"""Bounded B07 acceptance of an existing isolated manual-lease runtime.

Default invocation prints the panel only. Explicit execution never launches,
resets, teleports or restarts a simulation. Nonzero motion uses the existing
HTTP/UI owner exclusively. Independent sampling reuses Probe and truth_metrics.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict, deque
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import uuid

from fishbot_map_rules_acceptance import stationary, truth_metrics
from cooperation_oracle_base import clean

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco'
PROFILE = 'passage_manual'
LIMITS = {'forward_mps': .08, 'reverse_mps': .03, 'angular_rps': .25,
          'command_ttl_ms': 250, 'acquire_ttl_ms': 1000, 'heartbeat_ms': 140}
VECTORS = {'forward': (.08, 0.), 'backward': (-.03, 0.),
           'left': (0., .25), 'right': (0., -.25)}


def panel():
    return {'schema': 1, 'kind': 'B07_real_manual_lease_acceptance', 'domain': 129,
        'api': 'http://127.0.0.1:9097', 'web': 'http://127.0.0.1:5182',
        'execute_by_default': False, 'launch_or_stop_runtime': False,
        'budget': {'wall_s': 480, 'native_missions': 1, 'manual_acquires': 8,
                   'posts': 1500, 'record_bytes': 64*1024*1024, 'truth_frames': 40000},
        'wall_budget_parts': {'active_s': 440, 'cleanup_until_s': 475,
                              'last_http_tail_s': 2, 'observer_close_s': 2, 'report_margin_s': 1},
        'limits': dict(LIMITS), 'hold_source_s': 1.5, 'hold_wall_limit_s': 12.,
        'cases': ['forward_release', 'link_loss_expiry', 'native_exclusion_stop_reset',
                  'backward_release', 'left_release', 'right_release',
                  'sequence_and_ttl_rejection', 'actual_ui_forward_release'],
        'quiet': {'source_s': .7, 'wall_s': .7, 'linear_mps': .005,
                  'angular_rps': .02, 'receive_age_s': .25, 'source_age_s': [-.05, .25],
                  'max_source_and_receive_gap_s': .30},
        'not_run': [{'case': name, 'reason': 'No authorized bounded injection in this panel'}
                    for name in ('scan_loss', 'rogue_final_publisher')],
        'cleanup': 'Read original IDs; at most one explicit STOP, never replay an unknown mutation; '
                   'require native terminal, guard acknowledgement and independent dual-clock quiet. '
                   'Keep runtime alive for its owner. Any unresolved cleanup fails the panel.'}


def source_snapshot():
    names = ['tools/fishbot_manual_acceptance.py', 'tools/fishbot_manual_lease.py',
        'tools/fishbot_manual_ros.py', 'tools/fishbot_manual_profile.py',
        'tools/fishbot_command_guard.py', 'tools/fishbot_map_rules_acceptance.py',
        'tools/cooperation_oracle_base.py',
        'tools/config/fishbot_manual_mux.yaml', 'tools/config/fishbot_model_geometry.yaml',
        'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/scripts/verify_stack.py',
        'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/scripts/mission_bridge.py',
        'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/scripts/map_rules.py',
        'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/launch/sim.launch.py',
        'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/config/nav2.yaml',
        'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/mjcf/arena.xml',
        *['apps/fishbot-control-station/frontend/src/'+name for name in
          ('App.tsx', 'lib/manual-control.ts', 'hooks/use-manual-owner.ts',
           'components/control/leased-motion-panel.tsx', 'lib/runtime-context.ts', 'lib/simulation.ts')]]
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}


def input_snapshot(manifest_path):
    path = manifest_path.resolve(); manifest = json.loads(path.read_text())
    if manifest.get('profile_id') != PROFILE or manifest.get('domain') != 129:
        raise ValueError('Require the domain129 manual-profile.json from the owned launch')
    paths = [path, *[Path(value) for value in manifest.get('paths', {}).values()],
             *[Path(manifest[key]) for key in ('source_params', 'source_plugins') if key in manifest]]
    if any(not item.is_absolute() or not item.is_file() for item in paths):
        raise ValueError('Every declared runtime input must be an existing absolute file')
    return {str(item.resolve()): hashlib.sha256(item.read_bytes()).hexdigest() for item in paths}


def require_loopback(address):
    value = urlsplit(address)
    if (value.scheme != 'http' or value.hostname != '127.0.0.1' or not value.port
            or value.username or value.password or value.path or value.query or value.fragment):
        raise ValueError('Require an explicit loopback HTTP origin without a path')
    return address


def original_lease(value, identity, *, accepted_sequence=None):
    if not isinstance(value, dict) or any(value.get(k) != identity[k] for k in
            ('lease_id', 'session_id', 'runtime_instance_id', 'map_id', 'profile_id')):
        raise RuntimeError('Original lease identity mismatch')
    sequence = value.get('last_sequence')
    if type(sequence) is not int or sequence < 0:
        raise RuntimeError('Invalid original accepted sequence')
    if accepted_sequence is not None and sequence != accepted_sequence:
        raise RuntimeError('POST receipt does not acknowledge its sent sequence')
    # GET may be behind the last sent sequence when a request never arrived.
    return value


def boundary_frames(frames, boundary):
    before = [f for f in frames if f['steady_time'] <= boundary]
    if not before or boundary-before[-1]['steady_time'] > .25:
        raise RuntimeError('No fresh independent pre-dispatch boundary')
    return [before[-1]]+[f for f in frames if f['steady_time'] > boundary]


def quiet_result(frames):
    timing = truth_metrics(frames)
    tail = []
    for frame in reversed(frames):
        if not stationary(frame): break
        tail.append(frame)
    if len(tail) < 2: return None
    source = tail[0]['stamp']-tail[-1]['stamp']
    wall = tail[0]['steady_time']-tail[-1]['steady_time']
    if min(source, wall) < .7-1e-9: return None
    return {**timing, 'quiet_source_s': source, 'quiet_wall_s': wall,
            'last_truth': tail[0], 'quiet_frames': len(tail)}


def score_direction(direction, frames):
    timing = truth_metrics(frames)
    initial, final = frames[0], frames[-1]
    dx, dy = final['x']-initial['x'], final['y']-initial['y']
    along = dx*math.cos(initial['yaw'])+dy*math.sin(initial['yaw'])
    cross = -dx*math.sin(initial['yaw'])+dy*math.cos(initial['yaw'])
    yaw = math.atan2(math.sin(final['yaw']-initial['yaw']), math.cos(final['yaw']-initial['yaw']))
    if direction in ('forward', 'backward'):
        signed = along if direction == 'forward' else -along
        if not (.025 if direction == 'forward' else .012) <= signed <= .22:
            raise RuntimeError('Independent signed translation is outside the declared panel')
        if abs(cross) > .025 or abs(yaw) > .08:
            raise RuntimeError('Independent straight motion deviated from its original heading')
    elif direction in ('left', 'right'):
        signed = yaw if direction == 'left' else -yaw
        if not .10 <= signed <= .65 or math.hypot(dx, dy) > .025:
            raise RuntimeError('Independent turn direction or translation failed')
    else: raise ValueError('Unknown direction')
    quiet = quiet_result(frames)
    if quiet is None: raise RuntimeError('No independent .7 second source/wall quiet')
    return {**timing, **quiet, 'along_m': along, 'cross_m': cross,
            'yaw_change_rad': yaw, 'distance_m': math.hypot(dx, dy)}


def native_stop_complete(mission, stop, statuses, task_id, native_id):
    return (mission.get('id') == task_id and mission.get('native_goal_id') == native_id
        and mission.get('status') == 'canceled' and mission.get('native_status') == 5
        and mission.get('cleanup_state') != 'unresolved' and statuses.get(native_id) == 5
        and stop.get('target_id') == task_id and stop.get('state') == 'stopped'
        and stop.get('native_terminal') is True and stop.get('guard_stop_acknowledged') is True
        and stop.get('quiet', {}).get('confirmed') is True)


class Recording:
    def __init__(self, output):
        self.lock = threading.RLock(); self.error = None; self.bytes = 0
        descriptor = os.open(output/'observations.jsonl', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self.stream = os.fdopen(descriptor, 'w', buffering=1)
    def emit(self, topic, payload, **extra):
        with self.lock:
            if self.error: return
            try:
                line = json.dumps(clean({'topic': topic, 'epoch': time.time(), 'steady_time': time.monotonic(),
                                   'payload': payload, **extra}), allow_nan=False)+'\n'
                size = len(line.encode())
                if self.bytes+size > panel()['budget']['record_bytes']: raise RuntimeError('Complete recording budget exhausted')
                self.stream.write(line); self.bytes += size
            except Exception as error: self.error = str(error)
    def close(self):
        with self.lock:
            try: self.stream.flush(); os.fsync(self.stream.fileno()); self.stream.close()
            except Exception as error: self.error = self.error or str(error)


class Api:
    def __init__(self, base, instance, log):
        self.base, self.instance, self.log = base, instance, log
        self.posts = []; self.acquires = self.missions = 0
        self.request_timings = deque(maxlen=2048)
        self.request_timing_dropped = 0
    def call(self, path, body=None, *, cleanup=False):
        def point():
            return {'steady_time': time.monotonic(), 'epoch': time.time()}
        timing = {'path': path, 'runtime_instance_id': self.instance,
            **{key: body.get(key) if body is not None else None
               for key in ('session_id', 'sequence', 'issued_at_ms')},
            'call_started': point(), 'before_intent_log': None, 'after_intent_log': None,
            'before_urlopen': None, 'after_headers': None, 'after_body': None,
            'after_log': None, 'log_event': None}
        if len(self.request_timings) == self.request_timings.maxlen:
            self.request_timing_dropped += 1
        self.request_timings.append(timing)
        if body is not None:
            if not cleanup and len(self.posts) >= panel()['budget']['posts']: raise RuntimeError('POST budget exhausted')
            if path == 'manual/acquire':
                self.acquires += 1
                if self.acquires > 8: raise RuntimeError('Acquire budget exhausted')
            if path == 'mission':
                self.missions += 1
                if self.missions > 1: raise RuntimeError('Native mission budget exhausted')
            self.posts.append({'path': path, 'body': body, 'steady_time': time.monotonic(),
                               'network_timing': timing})
            timing['before_intent_log'] = point()
            self.log.emit('http_intent', {'path': path, 'body': body, 'cleanup': cleanup})
            timing['after_intent_log'] = point()
        encoded = None if body is None else json.dumps(body, allow_nan=False).encode()
        request = Request(self.base+'/sim-api/'+path, data=encoded,
            headers={'Content-Type': 'application/json', 'X-Fishbot-Instance': self.instance})
        try:
            # No recorder lock or logging lies between this local sample and
            # the actual network call. The original issued_at/stamp is retained.
            timing['before_urlopen'] = point()
            try: response = urlopen(request, timeout=2)
            except HTTPError as error: response = error
            timing['after_headers'] = point()
            with response:
                code, result = response.status, json.load(response)
                timing['after_body'] = point()
                header = response.headers.get('X-Fishbot-Instance')
            timing['log_event'] = 'http_receipt'
            self.log.emit('http_receipt', {'path': path, 'body': body, 'status': code,
                'value': result, 'instance_header': header, 'network_timing': timing})
            # This future boundary cannot appear in the JSONL entry just
            # written. Keep it in the bounded report trace and original POST.
            timing['after_log'] = point()
            if header != self.instance: raise RuntimeError('HTTP runtime identity changed or missing')
            return code, result
        except Exception as error:
            timing.update(after_log=None, log_event='http_unknown')
            self.log.emit('http_unknown', {'path': path, 'mutation': body is not None,
                                         'error': str(error), 'network_timing': timing})
            timing['after_log'] = point()
            raise RuntimeError(f'{path}: outcome unknown; original IDs retained, no retry') from error
    def get(self, path):
        code, result = self.call(path)
        if code != 200: raise RuntimeError(f'GET {path}: {code}: {result}')
        return result
    def accepted(self, path, body, **kwargs):
        code, result = self.call(path, body, **kwargs)
        if code not in (200, 202) or result.get('accepted') is not True or result.get('outcome') != 'accepted':
            raise RuntimeError(f'{path} not explicitly accepted: {code}: {result}')
        return result
    def rejected(self, path, body, expected):
        code, result = self.call(path, body)
        if not (400 <= code < 500 and result.get('accepted') is False and result.get('outcome') == 'rejected' and result.get('error') == expected):
            raise RuntimeError(f'Expected explicit {expected} rejection: {code}: {result}')
        return {'http_status': code, **result}


class RuntimeObservation:
    """The only ROS participant is the existing Probe in sensors mode."""
    def __init__(self, output, recording):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.signals import SignalHandlerOptions
        from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
        from diagnostic_msgs.msg import DiagnosticArray
        from geometry_msgs.msg import TwistStamped
        from action_msgs.msg import GoalStatusArray
        from rosidl_runtime_py.convert import message_to_ordereddict
        sys.path.insert(0, str(PKG/'scripts'))
        from verify_stack import Probe
        self.lock = threading.RLock(); self.frames = []; self.native = OrderedDict(); self.guard = None
        self.commands = []; self.log = recording; self.output = output
        owner = self
        class Observer(Probe):
            def on_truth(self, msg):
                previous = self.truth_updates; super().on_truth(msg)
                if self.truth is None or self.truth_updates == previous: return
                pose = self.truth.pose.pose; q = pose.orientation; linear, angular = self.planar_speed()
                frame = {'epoch': time.time(), 'steady_time': time.monotonic(), 'stamp': self.truth_time,
                    'ros_now': self.get_clock().now().nanoseconds/1e9, 'x': pose.position.x, 'y': pose.position.y,
                    'yaw': math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z)), 'linear_speed': linear, 'angular_speed': angular}
                with owner.lock:
                    if not all(math.isfinite(v) for v in frame.values()) or len(owner.frames) >= 40000:
                        owner.log.error = 'Invalid independent truth or bounded frame budget exhausted'; return
                    owner.frames.append(frame)
                    temporary = output/'observer-latest.tmp'
                    try:
                        temporary.write_text(json.dumps(frame)+'\n'); temporary.chmod(0o600); temporary.replace(output/'observer-latest.json')
                    except Exception as error: owner.log.error = 'Independent latest snapshot write failed: '+str(error)
                owner.log.emit('truth', frame)
        rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
        self.node = Observer(SimpleNamespace(mode='sensors', odom='/odom', scan='/scan', truth='/ground_truth/free_joint_states', cmd='/cmd_vel'))
        def command(topic, msg):
            value = message_to_ordereddict(msg)
            with self.lock:
                if len(self.commands) >= 100000:
                    recording.error = 'Bounded command observation budget exhausted'; return
                self.commands.append({'topic': topic, 'epoch': time.time(), 'steady_time': time.monotonic(), 'value': value})
            recording.emit(topic, value)
        self.subscriptions = [self.node.create_subscription(TwistStamped, topic, lambda msg, t=topic: command(t, msg), 1)
            for topic in ('/cmd_vel_manual', '/cmd_vel_selected', '/cmd_vel_safe_candidate')]
        def native(msg):
            raw = message_to_ordereddict(msg); recording.emit('native_status', raw)
            with self.lock:
                for item in msg.status_list:
                    key = bytes(item.goal_info.goal_id.uuid).hex(); self.native.pop(key, None); self.native[key] = item.status
                while len(self.native) > 256: self.native.popitem(last=False)
        qos = QoSProfile(depth=20, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.subscriptions.append(self.node.create_subscription(GoalStatusArray, '/follow_waypoints/_action/status', native, qos))
        def guard(msg):
            raw = clean(message_to_ordereddict(msg))
            with self.lock: self.guard = {'steady_time': time.monotonic(), 'source_stamp': msg.header.stamp.sec+msg.header.stamp.nanosec/1e9, 'value': raw}
            recording.emit('guard_diagnostics', raw)
        self.subscriptions.append(self.node.create_subscription(DiagnosticArray, '/fishbot_command_guard/diagnostics', guard, 1))
        self.executor = SingleThreadedExecutor(); self.executor.add_node(self.node)
        self.worker = threading.Thread(target=self.executor.spin, daemon=True); self.worker.start()
    def fresh(self):
        with self.lock:
            if self.log.error: raise RuntimeError(self.log.error)
            if not self.frames: raise RuntimeError('No independent truth')
            frame = dict(self.frames[-1])
        if time.monotonic()-frame['steady_time'] > .25 or not -.05 <= self.node.get_clock().now().nanoseconds/1e9-frame['stamp'] <= .25:
            raise RuntimeError('Independent truth is stale')
        return frame
    def frames_after(self, boundary):
        with self.lock: return boundary_frames(list(self.frames), boundary)
    def statuses(self):
        with self.lock: return dict(self.native)
    def guard_evidence(self):
        with self.lock: value = self.guard
        if value is None or time.monotonic()-value['steady_time'] > 1 or not -.05 <= self.node.get_clock().now().nanoseconds/1e9-value['source_stamp'] <= 1:
            raise RuntimeError('Independent guard diagnostics are stale')
        statuses = [v for v in value['value']['status'] if v['name'] == 'fishbot_command_guard']
        if len(statuses) != 1: raise RuntimeError('Independent guard diagnostics missing')
        fields = {v['key']: v['value'] for v in statuses[0]['values']}
        if fields.get('execute', '').lower() != 'true' or fields.get('profile') != 'fishbot_passage':
            raise RuntimeError('Wrong or nonexecuting command guard')
        return value
    def close(self):
        import rclpy
        started = time.monotonic()
        self.executor.shutdown(timeout_sec=1); self.worker.join(timeout=1)
        stopped = not self.worker.is_alive()
        if not stopped: self.log.error = self.log.error or 'Independent ROS observer did not stop within its 2 second budget'
        self.node.destroy_node(); rclpy.try_shutdown()
        return {'stopped': stopped, 'elapsed_s': time.monotonic()-started, 'budget_s': 2}


class Acceptance:
    def __init__(self, args, output, log, observation, *, started=None):
        self.args, self.output, self.log, self.observation = args, output, log, observation
        self.api = Api(args.api, args.expected_instance, log); self.started = time.monotonic() if started is None else started; self.deadline = self.started+440
        self.lease = None; self.sequence = 0; self.native_task = self.native_id = None
        self.native_submission = 'not_sent'
        self.stop_id = self.reset_id = None; self.control_session = str(uuid.uuid4()); self.control_sequence = 0
        self.cases = []; self.map_id = None
    def wait(self, read, predicate, seconds=15):
        end = min(self.deadline, time.monotonic()+seconds); value = None
        while time.monotonic() < end:
            value = read()
            if predicate(value): return value
            time.sleep(.05)
        raise TimeoutError('Declared acceptance deadline exceeded')
    def status(self):
        value = self.api.get('manual/status')
        if value.get('runtime_instance_id') != self.args.expected_instance or value.get('profile_id') != PROFILE or value.get('map_id') != self.map_id or value.get('limits') != LIMITS:
            raise RuntimeError('Manual status identity, map, profile or limits changed')
        return value
    def quiet(self, boundary):
        def read():
            self.observation.fresh()
            frames = self.observation.frames_after(boundary)
            return quiet_result(frames) if len(frames) >= 2 else None
        value = self.wait(read, bool, 18); value['guard_diagnostics'] = self.observation.guard_evidence(); return value
    def raw_chain(self, boundary, vector):
        with self.observation.lock:
            commands = [dict(v) for v in self.observation.commands if v['steady_time'] >= boundary]
        result = {}
        for topic in ('/cmd_vel_manual', '/cmd_vel_selected', '/cmd_vel_safe_candidate'):
            matching = []
            for record in commands:
                if record['topic'] != topic: continue
                twist = record['value']['twist']; v, w = twist['linear']['x'], twist['angular']['z']
                nonzero = v*vector[0] > 0 if vector[0] else w*vector[1] > 0
                if nonzero: matching.append(record)
            if not matching: raise RuntimeError('No independently observed command forwarding at '+topic)
            result[topic] = {'matching_nonzero_records': len(matching), 'first': matching[0], 'last': matching[-1]}
        return {'kind': 'DDS publication/forwarding observations; not a controller consumption receipt', 'topics': result}
    def envelope(self, sequence, ttl=1000):
        return {'session_id': self.control_session, 'runtime_instance_id': self.args.expected_instance,
            'map_id': self.map_id, 'profile_id': PROFILE, 'sequence': sequence,
            'issued_at_ms': time.time_ns()//1_000_000, 'ttl_ms': ttl}
    def acquire(self):
        def admission():
            self.observation.fresh()
            value = self.status()
            owner = value.get('native_owner') or {}
            recovery = value.get('idle_recovery') or {}
            if (value.get('available') is not True or value.get('stop_latched') is not False
                    or value.get('active_lease_id') is not None or owner.get('terminal') is not True
                    or owner.get('task_id') != self.native_task
                    or owner.get('native_goal_id') != self.native_id
                    or (value.get('can_acquire') is not True and recovery.get('state') == 'unknown')):
                raise RuntimeError('Original owner, STOP or recovery changed before fresh press')
            if value.get('can_acquire') is True and value.get('reason') is None:
                return value
            if (value.get('can_acquire') is not False or value.get('reason') not in {
                    'continuous_quiet_unconfirmed', 'manual_cleanup_unconfirmed'}):
                raise RuntimeError('Original owner rejected fresh press: '+str(value.get('reason')))
            return value
        # Reuse native/UI's bounded read-only readiness wait. Create the press
        # and its timestamp only after admission; never retry a sent mutation.
        self.wait(admission, lambda value: value['can_acquire'] is True, 15)
        self.lease = {**self.envelope(0), 'lease_id': str(uuid.uuid4()), 'gesture': 'press'}; self.sequence = 0
        result = self.api.accepted('manual/acquire', self.lease)
        original_lease(result['lease'], self.lease, accepted_sequence=0)
        value = self.wait(lambda: original_lease(self.api.get('manual/'+self.lease['lease_id'])['lease'], self.lease),
            lambda v: v['state'] != 'arming', 2)
        if value['state'] != 'ready' or value.get('guard_reset_acknowledged') is not True:
            raise RuntimeError('Original lease never became ready; no nonzero command sent')
        return value
    def command(self, vector):
        self.sequence += 1
        body = {**self.envelope(self.sequence, 250), 'session_id': self.lease['session_id'],
            'lease_id': self.lease['lease_id'], 'linear_x': vector[0], 'angular_z': vector[1]}
        value = self.api.accepted('manual/command', body)
        original_lease(value['lease'], self.lease, accepted_sequence=self.sequence)
        return body
    def drive(self, vector, duration=1.5):
        start = self.observation.fresh(); boundary = time.monotonic(); last = None
        while self.observation.fresh()['stamp']-start['stamp'] < duration:
            if time.monotonic()-boundary > 12 or time.monotonic() > self.deadline:
                raise TimeoutError('Held command exceeded its source/wall budget')
            sent_at = time.monotonic()
            last = self.command(vector)
            elapsed = time.monotonic()-sent_at
            if not math.isfinite(elapsed) or elapsed < 0 or elapsed >= LIMITS['command_ttl_ms']/1000:
                raise RuntimeError('Command receipt exceeded its original monotonic TTL budget; no renewal')
            # ACK time is part of the 140ms interval. Still serialize requests;
            # a late ACK permits at most one fresh command, never a catch-up loop.
            delay = LIMITS['heartbeat_ms']/1000-elapsed
            if delay > 0: time.sleep(delay)
        return boundary, last
    def lease_finished(self, expected):
        def read(): return original_lease(self.api.get('manual/'+self.lease['lease_id'])['lease'], self.lease)
        value = self.wait(read, lambda v: v['state'] in ('released', 'expired', 'stopped', 'unknown')
            and v.get('guard_stop_acknowledged') is True and v.get('quiet', {}).get('confirmed') is True, 18)
        if value['state'] != expected: raise RuntimeError('Original lease outcome was not '+expected)
        return value
    def release(self):
        self.sequence += 1
        body = {**self.envelope(self.sequence), 'session_id': self.lease['session_id'], 'lease_id': self.lease['lease_id']}
        original_lease(self.api.accepted('manual/release', body)['lease'], self.lease, accepted_sequence=self.sequence)
        return self.lease_finished('released')
    def record_case(self, name, value):
        self.cases.append({'name': name, 'passed': True, **value}); self.log.emit('case', self.cases[-1])
    def initial(self):
        runtime = self.api.get('runtime'); state = self.api.get('state'); status = self.api.get('manual/status')
        if runtime.get('instance_id') != self.args.expected_instance or runtime.get('domain') != self.args.domain or runtime.get('mode') != 'simulation' or runtime.get('service') != 'mission':
            raise RuntimeError('Explicit runtime identity is not the selected simulation')
        if state.get('mode') != 'mujoco' or state.get('domain') != self.args.domain or state['mission'].get('id') is not None or state['mission']['status'] != 'idle':
            raise RuntimeError('Require the new idle arena; existing tasks remain untouched')
        self.map_id = status.get('map_id')
        if not isinstance(self.map_id, str) or not self.map_id: raise RuntimeError('Runtime map unavailable')
        def observation_ready():
            if len(self.observation.frames) < 20:
                return False
            try:
                self.observation.guard_evidence()
            except RuntimeError as error:
                if str(error) == 'Independent guard diagnostics are stale':
                    return False  # No sample yet, or its original ages are stale.
                raise
            return True
        self.wait(observation_ready, bool, 15)
        self.quiet(time.monotonic())
        latest = status
        def readiness():
            nonlocal latest
            latest = self.status()
            return latest
        try:
            self.wait(readiness, lambda v: v['can_acquire'], 20)
        except TimeoutError as error:
            details = {'last_manual_status': latest}
            try: details['guard_diagnostics'] = self.observation.guard_evidence()
            except RuntimeError as unavailable: details['guard_evidence_error'] = str(unavailable)
            self.log.emit('initial_readiness_failure', details)
            raise TimeoutError('Initial manual readiness deadline exceeded: '+json.dumps(details)) from error
        # The initial HTTP read is not readiness at dispatch time. Recheck the
        # same idle owner after all waits; never recover or unlock it here.
        final_status, final_state = self.status(), self.api.get('state')
        self.observation.fresh()
        if (final_state.get('mode') != 'mujoco' or final_state.get('domain') != self.args.domain
                or final_state['mission'].get('id') is not None or final_state['mission']['status'] != 'idle'
                or final_status.get('can_acquire') is not True or final_status.get('active_lease_id') is not None
                or final_status.get('stop_latched') is not False
                or final_status.get('native_owner', {}).get('terminal') is not True):
            self.log.emit('initial_owner_changed', {'state': final_state, 'manual': final_status})
            raise RuntimeError('Initial idle owner or admission changed before dispatch; no mutation sent')
        return {'runtime': runtime, 'state': final_state, 'manual': final_status}
    def native_case(self):
        self.wait(self.status, lambda value: value['can_acquire'], 15)
        self.observation.fresh(); state = self.api.get('state'); grid = self.api.get('map'); rules = self.api.get('map-rules')
        if rules['map_id'] != self.map_id or rules['apply_state'] != 'applied': raise RuntimeError('Unapplied or different map rules')
        sys.path.insert(0, str(PKG/'scripts'))
        from mission_bridge import require_free_point
        from map_rules import require_outside_rules
        pose = state['pose']; goal = {'x': pose['x']+.45*math.cos(pose['yaw']), 'y': pose['y']+.45*math.sin(pose['yaw']), 'yaw': pose['yaw']}
        for index in range(91):
            point = {key: pose[key]+(goal[key]-pose[key])*index/90 for key in ('x', 'y')}
            require_free_point(point, grid); require_outside_rules(point, rules['zones'])
        self.native_task = str(uuid.uuid4()); boundary = time.monotonic(); start = self.observation.fresh()
        body = {'mission_id': self.native_task, 'waypoints': [goal], 'return_home': False,
            'issued_at': time.time(), 'timeout_s': 120, 'map_id': self.map_id, 'rules_revision': rules['revision']}
        self.native_submission = 'unknown'
        code, receipt = self.api.call('mission', body)
        if code >= 400 and receipt.get('outcome') == 'rejected': self.native_submission = 'rejected'
        if code != 202 or receipt.get('mission', {}).get('id') != self.native_task:
            raise RuntimeError('Original mission submission did not return its recorded identity')
        self.native_submission = 'submitted'
        # This legacy 202 records submission only. Native evidence comes from
        # the original DDS UUID plus independent motion below.
        def moving():
            mission = self.api.get('state')['mission']; current = self.observation.fresh()
            if mission.get('id') != self.native_task: raise RuntimeError('Original mission identity changed')
            native_id = mission.get('native_goal_id')
            if mission.get('status') in ('failed', 'unknown', 'canceled'): raise RuntimeError('Original native action failed before STOP test')
            return (mission, current) if native_id and self.observation.statuses().get(native_id) == 2 and current['linear_speed'] > .02 and math.hypot(current['x']-start['x'], current['y']-start['y']) >= .03 else None
        mission, moving_frame = self.wait(moving, bool, 90); self.native_id = mission['native_goal_id']
        rejected = {**self.envelope(0), 'lease_id': str(uuid.uuid4()), 'gesture': 'press'}
        denied = self.api.rejected('manual/acquire', rejected, 'native_owner_unresolved')
        self.stop_id = str(uuid.uuid4()); self.control_sequence += 1
        stop = self.api.accepted('manual/stop', {**self.envelope(self.control_sequence), 'request_id': self.stop_id, 'target_id': self.native_task})['stop']
        if stop.get('request_id') != self.stop_id or stop.get('target_id') != self.native_task: raise RuntimeError('Original STOP binding changed')
        def stopped():
            current = self.api.get('state')['mission']; stop = self.api.get('manual/stops/'+self.stop_id)['stop']
            if stop.get('request_id') != self.stop_id: raise RuntimeError('Original STOP ID changed')
            return {'mission': current, 'stop': stop} if native_stop_complete(current, stop, self.observation.statuses(), self.native_task, self.native_id) else None
        terminal = self.wait(stopped, bool, 25); physical = self.quiet(boundary)
        self.reset_id = str(uuid.uuid4()); self.control_sequence += 1
        reset = self.api.accepted('manual/reset', {**self.envelope(self.control_sequence), 'request_id': self.reset_id, 'stop_request_id': self.stop_id, 'gesture': 'reset'})['reset']
        def ready_reset():
            v = self.api.get('manual/resets/'+self.reset_id)['reset']
            if v.get('request_id') != self.reset_id or v.get('stop_request_id') != self.stop_id: raise RuntimeError('Original reset binding changed')
            return v if v.get('state') == 'ready' and v.get('guard_reset_acknowledged') is True else None
        reset = self.wait(ready_reset, bool, 10)
        count = len(self.api.posts); no_restart = self.quiet(time.monotonic())
        if len(self.api.posts) != count or self.api.get('state')['mission'].get('native_goal_id') != self.native_id: raise RuntimeError('Reset restarted an action')
        self.record_case('native_exclusion_stop_reset', {'submission': receipt, 'manual_rejection': denied,
            'native_uuid': self.native_id, 'moving_truth': moving_frame, 'terminal': terminal,
            'physical': physical, 'reset': reset, 'quiet_after_reset': no_restart})
        self.stop_id = self.reset_id = None
    def directions(self, selected=('forward', 'backward', 'left', 'right')):
        for direction in selected:
            vector = VECTORS[direction]
            self.quiet(time.monotonic()); lease = self.acquire(); boundary, _ = self.drive(vector)
            released = self.release(); self.quiet(boundary)
            physical = score_direction(direction, self.observation.frames_after(boundary))
            self.record_case(direction+'_release', {'lease_id': self.lease['lease_id'], 'submission': lease,
                'raw_forwarding': self.raw_chain(boundary, vector), 'terminal': released, 'physical': physical})
            self.lease = None
    def expiry(self, replay=False):
        self.quiet(time.monotonic()); lease = self.acquire(); boundary, last = self.drive((.04, 0.), .6)
        rejected_sequence = None
        if replay:
            stale = {**last, 'issued_at_ms': time.time_ns()//1_000_000}
            rejected_sequence = self.api.rejected('manual/command', stale, 'stale_sequence')
        count = len(self.api.posts); expired = self.lease_finished('expired'); quiet = self.quiet(boundary)
        if len(self.api.posts) != count: raise RuntimeError('Expired lease emitted a mutation')
        ttl_rejection = None
        if replay:
            if time.time_ns()//1_000_000-last['issued_at_ms'] < 800: raise RuntimeError('TTL replay is not clearly outside its window')
            before = time.monotonic(); ttl_rejection = self.api.rejected('manual/command', last, 'manual_request_expired'); self.quiet(before)
        self.record_case('sequence_and_ttl_rejection' if replay else 'link_loss_expiry', {'lease_id': self.lease['lease_id'], 'submission': lease,
            'terminal': expired, 'last_original_command': last, 'physical': quiet, 'sequence_rejection': rejected_sequence,
            'raw_forwarding': self.raw_chain(boundary, (.04, 0.)),
            'unchanged_ttl_replay_rejection': ttl_rejection, 'no_mutation_during_expiry': True})
        self.lease = None
    def cleanup(self):
        result = {'attempted_stop': False, 'runtime_left_alive': True, 'passed': False}
        self.deadline = self.started+475
        try:
            # Read first. A previous unknown STOP/reset is never submitted again.
            state = self.api.get('state'); status = self.status()
            if self.native_submission == 'unknown' and state['mission'].get('id') != self.native_task:
                raise RuntimeError('Original mission submission remains unknown; idle snapshot cannot resolve it')
            active_lease = status.get('active_lease_id')
            if active_lease and (self.lease is None or active_lease != self.lease['lease_id']):
                raise RuntimeError('A different active manual owner appeared; do not stop it')
            if not status['native_owner']['terminal'] and state['mission'].get('id') != self.native_task:
                raise RuntimeError('A different native owner appeared; do not stop it')
            if self.stop_id:
                result['original_stop'] = self.api.get('manual/stops/'+self.stop_id)
            elif (self.lease is not None or state['mission'].get('id') == self.native_task and state['mission'].get('status') in ('running', 'canceling', 'unknown')):
                target = status.get('active_lease_id') or (self.native_task if not status['native_owner']['terminal'] else None)
                self.stop_id = str(uuid.uuid4()); self.control_sequence += 1; result['attempted_stop'] = True
                result['receipt'] = self.api.accepted('manual/stop', {**self.envelope(self.control_sequence), 'request_id': self.stop_id, 'target_id': target}, cleanup=True)
            if self.reset_id:
                def reset_known():
                    value = self.api.get('manual/resets/'+self.reset_id)['reset']
                    if value.get('request_id') != self.reset_id or value.get('stop_request_id') != self.stop_id:
                        raise RuntimeError('Original cleanup reset identity mismatch')
                    return value if value.get('state') == 'ready' and value.get('guard_reset_acknowledged') is True else None
                result['original_reset'] = self.wait(reset_known, bool, 15)
            def clean():
                current = self.status()
                if not current['native_owner']['terminal'] or not current['quiet']['confirmed']: return None
                if self.native_submission == 'submitted':
                    mission = self.api.get('state')['mission']; native_id = mission.get('native_goal_id')
                    if mission.get('id') != self.native_task or not native_id or (self.native_id and native_id != self.native_id): return None
                    if self.observation.statuses().get(native_id) not in (4, 5, 6): return None
                if self.stop_id:
                    stop = self.api.get('manual/stops/'+self.stop_id)['stop']
                    if stop.get('request_id') != self.stop_id or stop.get('state') != 'stopped' or stop.get('guard_stop_acknowledged') is not True or stop.get('native_terminal') is not True: return None
                    return {'status': current, 'stop': stop}
                return {'status': current}
            result['owner'] = self.wait(clean, bool, 20); result['physical'] = self.quiet(time.monotonic()); result['passed'] = True
        except Exception as error: result['error'] = str(error)
        return result


UI_PROGRAM = r"""
const fs=require('node:fs'),{chromium}=require('playwright');
const p=JSON.parse(process.argv[1]);let browser,page,held=false;const result={passed:false,posts:[],receipts:[],blocked_requests:[],errors:[]};
async function wait(read,predicate,label,ms=15000){const end=Date.now()+ms;while(Date.now()<end){const v=await read();if(predicate(v))return v;await new Promise(r=>setTimeout(r,50));}throw Error(label);}
(async()=>{try{browser=await chromium.launch({headless:true,executablePath:p.chromium});const context=await browser.newContext({viewport:{width:1440,height:900},serviceWorkers:'block'});
await context.route('**/*',async route=>{const request=route.request(),url=new URL(request.url()),method=request.method();let allowed=url.origin===p.web;
if(!['GET','HEAD','OPTIONS'].includes(method)){allowed=allowed&&method==='POST'&&['/sim-api/manual/acquire','/sim-api/manual/command','/sim-api/manual/release'].includes(url.pathname);
if(allowed){try{const body=request.postDataJSON();allowed=body.runtime_instance_id===p.instance&&body.map_id===p.map_id&&body.profile_id==='passage_manual';}catch{allowed=false;}}}
if(!allowed){const blocked={url:request.url(),method};result.blocked_requests.push(blocked);result.errors.push('Blocked before network: '+method+' '+url.pathname);return route.abort();}return route.continue();});
page=await context.newPage();page.setDefaultTimeout(15000);
page.on('pageerror',e=>result.errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'){const u=new URL(r.url());if(u.pathname.startsWith('/sim-api/manual/'))result.posts.push({path:u.pathname,body:r.postDataJSON(),epoch:Date.now()/1000});else result.errors.push('Unexpected UI mutation '+u.pathname);}});
page.on('response',async r=>{if(r.request().method()==='POST'&&new URL(r.url()).pathname.startsWith('/sim-api/manual/')){try{result.receipts.push({path:new URL(r.url()).pathname,status:r.status(),value:await r.json()});}catch(e){result.errors.push(String(e));}}});
await page.goto(p.web+'/',{waitUntil:'domcontentloaded'});const runtime=await page.evaluate(async()=>await(await fetch('/sim-api/runtime')).json());if(runtime.instance_id!==p.instance||runtime.domain!==p.domain)throw Error('UI runtime identity mismatch');
const button=page.getByRole('button',{name:'按住前进',exact:true});await wait(()=>button.isEnabled(),Boolean,'UI manual readiness');await button.scrollIntoViewIfNeeded();const box=await button.boundingBox();
const start=JSON.parse(fs.readFileSync(p.latest));if(Date.now()/1000-start.epoch>.25)throw Error('UI boundary truth stale');result.boundary=start;result.dispatch_epoch=Date.now()/1000;
await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();held=true;await wait(()=>JSON.parse(fs.readFileSync(p.latest)),v=>{if(Date.now()/1000-v.epoch>.25)throw Error('Held UI truth stale');return v.stamp-start.stamp>=1.5;},'UI hold source/wall budget',12000);
await page.mouse.up();held=false;await wait(()=>result.posts.filter(v=>v.path.endsWith('/release')).length,n=>n===1,'UI original release');await wait(()=>button.isEnabled(),Boolean,'UI quiet original lease cleanup');
const acquire=result.posts.filter(v=>v.path.endsWith('/acquire'));if(acquire.length!==1||!result.posts.some(v=>v.path.endsWith('/command')))throw Error('UI did not use one original lease');result.lease_id=acquire[0].body.lease_id;
for(const post of result.posts)if(post.body.runtime_instance_id!==p.instance||post.body.map_id!==p.map_id)throw Error('UI mutation identity changed');
await page.screenshot({path:p.screenshot,fullPage:true});result.passed=result.errors.length===0;
}catch(e){result.errors.push(String(e));}finally{if(held&&page)await page.mouse.up().catch(e=>result.errors.push(String(e)));if(browser)await browser.close();fs.writeFileSync(p.result,JSON.stringify(result,null,2)+'\n',{mode:0o600});}process.exitCode=result.passed?0:1;})();
"""


def actual_ui(run):
    run.quiet(time.monotonic()); boundary = time.monotonic()
    if run.api.acquires >= 8: raise RuntimeError('No remaining budget for the mandatory UI lease')
    remaining = min(40., run.deadline-time.monotonic())
    if remaining < 15: raise RuntimeError('Insufficient remaining active budget for the mandatory UI lease')
    plan = {'web': run.args.web, 'domain': run.args.domain, 'instance': run.args.expected_instance,
        'map_id': run.map_id, 'chromium': run.args.chromium, 'latest': str(run.output/'observer-latest.json'),
        'result': str(run.output/'ui-result.json'), 'screenshot': str(run.output/'ui-forward.png')}
    with (run.output/'ui.log').open('x') as log:
        os.chmod(log.name, 0o600)
        child = subprocess.Popen(['node', '-e', UI_PROGRAM, json.dumps(plan)], stdout=log,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        try: code = child.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            # Only this owned browser group is stopped. A surviving renderer
            # must not keep renewing a gesture after its acceptance runner dies.
            os.killpg(child.pid, signal.SIGTERM)
            try: child.wait(timeout=3)
            except subprocess.TimeoutExpired: os.killpg(child.pid, signal.SIGKILL); child.wait(timeout=3)
            raise RuntimeError('UI observer budget exhausted; no replay')
    path = run.output/'ui-result.json'
    if not path.exists(): raise RuntimeError('UI result unavailable; retain original HTTP audit')
    result = json.loads(path.read_text()); acquired = [v for v in result['posts'] if v['path'].endswith('/acquire')]
    if acquired:
        run.api.acquires += len(acquired)
        run.lease = acquired[0]['body']; run.sequence = max(v['body']['sequence'] for v in result['posts'])
    if code or not result['passed']: raise RuntimeError('Actual UI hold/release failed: '+str(result['errors']))
    if not run.lease or len(acquired) != 1: raise RuntimeError('UI original lease unavailable')
    terminal = run.lease_finished('released'); run.quiet(boundary)
    physical = score_direction('forward', run.observation.frames_after(boundary))
    run.record_case('actual_ui_forward_release', {'browser': result, 'terminal': terminal,
        'raw_forwarding': run.raw_chain(boundary, (.04, 0.)), 'physical': physical})
    run.lease = None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true'); parser.add_argument('--plan', action='store_true')
    parser.add_argument('--domain', type=int, default=129); parser.add_argument('--api', default='http://127.0.0.1:9097')
    parser.add_argument('--web', default='http://127.0.0.1:5182'); parser.add_argument('--expected-instance')
    parser.add_argument('--runtime-manifest', type=Path); parser.add_argument('--output', type=Path)
    parser.add_argument('--chromium', default='/opt/google/chrome/chrome')
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps(panel(), ensure_ascii=False, indent=2)); return 0
    if args.plan: parser.error('--plan cannot execute motion')
    try:
        require_loopback(args.api); require_loopback(args.web)
        if (args.domain != 129 or os.environ.get('ROS_DOMAIN_ID') != str(args.domain)
                or os.environ.get('FISHBOT_MUJOCO_DOMAIN_ID') != str(args.domain)
                or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST'
                or os.environ.get('ROS_STATIC_PEERS', '')): raise ValueError('Require the confirmed isolated domain129 environment')
        if not args.expected_instance or str(uuid.UUID(args.expected_instance)) != args.expected_instance: raise ValueError('Require the confirmed exact runtime UUID')
        if not args.runtime_manifest or not args.runtime_manifest.is_file(): raise ValueError('Require the owned launch manifest reference')
        inputs = input_snapshot(args.runtime_manifest)
        if not args.output or args.output.exists() or args.output.resolve().is_relative_to(ROOT): raise ValueError('Select a new external private output directory')
        if not Path(args.chromium).is_file(): raise ValueError('Select an installed Chromium executable')
    except ValueError as error: parser.error(str(error))
    output = args.output.resolve(); output.mkdir(parents=True, mode=0o700)
    report = {'passed': False, 'panel': panel(), 'source_start': source_snapshot(), 'cases': [], 'errors': [],
        'input_start': inputs,
        'runtime_manifest_reference': {'path': str(args.runtime_manifest.resolve()), 'sha256': hashlib.sha256(args.runtime_manifest.read_bytes()).hexdigest(),
                                     'scope': 'Owner-provided reference; not independent process/source attestation'}}
    frozen = output/'frozen-sources'; frozen.mkdir(mode=0o700)
    for name, digest in report['source_start'].items():
        content = (ROOT/name).read_bytes()
        if hashlib.sha256(content).hexdigest() != digest: raise RuntimeError('Source changed during freezing; nothing dispatched')
        path = frozen/name; path.parent.mkdir(parents=True, exist_ok=True, mode=0o700); path.write_bytes(content); path.chmod(0o600)
    frozen_inputs = output/'frozen-inputs'; frozen_inputs.mkdir(mode=0o700)
    for index, (name, digest) in enumerate(inputs.items()):
        content = Path(name).read_bytes()
        if hashlib.sha256(content).hexdigest() != digest: raise RuntimeError('Runtime input changed during freezing; nothing dispatched')
        path = frozen_inputs/(str(index)+'-'+Path(name).name); path.write_bytes(content); path.chmod(0o600)
    recording = Recording(output); observation = run = None
    started = time.monotonic()
    try:
        observation = RuntimeObservation(output, recording); run = Acceptance(args, output, recording, observation, started=started)
        report['initial'] = run.initial(); run.directions(('forward',)); run.expiry(); run.native_case()
        run.directions(('backward', 'left', 'right')); run.expiry(replay=True); actual_ui(run)
        report['cleanup'] = run.cleanup(); report['passed'] = report['cleanup']['passed']
    except Exception as error:
        report['errors'].append(str(error))
        if run: report['cleanup'] = run.cleanup()
    finally:
        if run:
            report['cases'] = run.cases; report['http_posts'] = run.api.posts
            report['http_call_timings'] = {'capacity': run.api.request_timings.maxlen,
                'dropped_oldest': run.api.request_timing_dropped,
                'entries': list(run.api.request_timings),
                'after_log_scope': 'Sampled after emit returns; retained here and on original POSTs, not inside the earlier JSONL entry'}
        if observation:
            try: report['observer_close'] = observation.close()
            except Exception as error: report['errors'].append('Independent observer cleanup failed: '+str(error))
        recording.close(); report['recording_error'] = recording.error; report['recording_bytes'] = recording.bytes
        try: report['source_end'] = source_snapshot()
        except Exception as error: report['source_end'] = {}; report['errors'].append('Source readback failed: '+str(error))
        report['source_unchanged'] = report['source_start'] == report['source_end']
        try: report['input_end'] = input_snapshot(args.runtime_manifest)
        except Exception as error: report['input_end'] = {}; report['errors'].append('Runtime input readback failed: '+str(error))
        report['inputs_unchanged'] = report['input_start'] == report['input_end']
        report['elapsed_s'] = time.monotonic()-started
        if not report['source_unchanged']: report['errors'].append('Execution sources changed')
        if not report['inputs_unchanged']: report['errors'].append('Runtime inputs changed')
        if recording.error: report['errors'].append('Complete evidence recording failed: '+recording.error)
        if len(report['cases']) != 8: report['errors'].append('Predeclared cases missing: '+str([name for name in panel()['cases'] if name not in {case['name'] for case in report['cases']}]))
        if not report.get('cleanup', {}).get('passed'): report['errors'].append('Original-ID cleanup incomplete')
        if report['elapsed_s'] > 480: report['errors'].append('Overall wall-clock budget exceeded')
        report['passed'] = bool(report['passed'] and not report['errors'])
        descriptor = os.open(output/'result.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream: json.dump(report, stream, indent=2, allow_nan=False)
    print(json.dumps({'passed': report['passed'], 'errors': report['errors'], 'output': str(output)}))
    return 0 if report['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
