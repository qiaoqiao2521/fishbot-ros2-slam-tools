#!/usr/bin/env python3
"""Final command health gate and bounded trigger recorder.

Dry-run by default; --execute is required to create a motor command publisher.
Inputs are TwistStamped, while the real-board output defaults to Twist.
Collision Monitor owns collision decisions. This node checks message health,
TF and graph ownership, and records CM transitions without redoing its geometry.
This software gate does not establish a firmware watchdog or physical braking.
"""

import argparse
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import queue
import signal
import stat
import threading
import time
import uuid


ZERO = (0.0, 0.0)
ODOM_AGE = 0.25
SCAN_AGE = 0.50
FUTURE_AGE = 0.05
MAX_SCAN_POINTS = 4096


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, deque)):
        return [json_safe(item) for item in value]
    return value


def vector(value, size, label):
    if not isinstance(value, (list, tuple)) or len(value) != size or not all(map(finite, value)):
        raise ValueError(label + ' must contain finite numbers')
    return [float(item) for item in value]


def normalized_quaternion(value):
    q = vector(value, 4, 'quaternion')
    norm2 = sum(item * item for item in q)
    if not 0.8 <= norm2 <= 1.2:
        raise ValueError('invalid quaternion norm')
    return [item / math.sqrt(norm2) for item in q]


@dataclass(frozen=True)
class Settings:
    base_frame: str
    odom_frame: str
    profile: str
    max_linear_speed: float
    max_angular_speed: float
    command_timeout_s: float
    ring_capacity: int
    expected_candidate_publishers: tuple
    expected_final_subscribers: tuple
    geometry: dict
    candidate_topic: str = '/cmd_vel_safe_candidate'
    output_topic: str = '/cmd_vel'
    output_stamped: bool = False
    timing_profile: str = 'strict'
    odom_timeout_s: float = ODOM_AGE
    hold_timeout_s: float | None = 2.0
    recovery_s: float = 0.2
    recovery_policy: str = 'explicit_reset'
    hold_escalates_to_latch: bool = True

    @classmethod
    def from_mapping(cls, document, **overrides):
        guard = document.get('command_guard', {})
        frames, motion = document['frames'], document['motion']
        linear, angular = motion['max_linear_mps'], motion['max_angular_rps']
        for value, ceiling in ((linear, 0.08), (angular, 0.25)):
            if not finite(value) or not 0 < value <= ceiling:
                raise ValueError('motion limits must be positive and <= 0.08 m/s, 0.25 rad/s')
        # The shared motion section is authoritative; reject duplicated limits that drift.
        for key, value in (('max_linear_speed', linear), ('max_angular_speed', angular)):
            if key in guard and guard[key] != value:
                raise ValueError('command_guard.' + key + ' disagrees with motion')
        timing_profile = overrides.pop('timing_profile', 'strict')
        if timing_profile not in ('strict', 'tolerant'):
            raise ValueError('timing_profile must be strict or tolerant')
        timeout = 0.35 if timing_profile == 'tolerant' else guard.get('command_timeout_s', 0.25)
        capacity = guard.get('ring_capacity', 40)
        ceiling = 0.35 if timing_profile == 'tolerant' else 0.25
        if not finite(timeout) or not 0 < timeout <= ceiling:
            raise ValueError('command timeout must be positive and <= ' + str(ceiling) + ' s')
        if not isinstance(capacity, int) or isinstance(capacity, bool) or not 1 <= capacity <= 200:
            raise ValueError('ring_capacity must be in [1, 200]')
        for name in ('base', 'odom'):
            if not isinstance(frames[name], str) or not frames[name]:
                raise ValueError('frames.' + name + ' is required')
        footprint = document['footprint']['points_m']
        if not isinstance(footprint, list) or not 3 <= len(footprint) <= 64:
            raise ValueError('footprint must have 3..64 vertices')
        for point in footprint:
            vector(point, 2, 'footprint vertex')
        candidates = tuple(guard.get('expected_candidate_publishers', ['collision_monitor']))
        subscribers = tuple(overrides.pop('expected_final_subscribers', None)
                            or guard.get('expected_final_subscribers', ['fishbot_motion_control']))
        if len(candidates) != 1 or not subscribers or not all(
                isinstance(name, str) and name for name in candidates + subscribers):
            raise ValueError('one candidate publisher and explicit final subscribers are required')
        options = {key: overrides.get(key) if overrides.get(key) is not None else guard.get(key, default)
                   for key, default in (('candidate_topic', '/cmd_vel_safe_candidate'),
                                        ('output_topic', '/cmd_vel'), ('output_stamped', False))}
        if not isinstance(options['output_stamped'], bool):
            raise ValueError('output_stamped must be boolean')
        if any(not isinstance(options[key], str) or not options[key].startswith('/')
               for key in ('candidate_topic', 'output_topic')):
            raise ValueError('command topics must be absolute')
        if options['candidate_topic'] == options['output_topic']:
            raise ValueError('candidate and final topics must differ')
        geometry = deepcopy(document)
        automatic = timing_profile == 'tolerant'
        geometry.setdefault('command_guard', {}).update(
            timing_profile=timing_profile, command_timeout_s=float(timeout),
            odom_timeout_s=0.35 if timing_profile == 'tolerant' else ODOM_AGE,
            hold_timeout_s=None if automatic else 2.0, recovery_s=0.2,
            recovery_policy='auto_resume' if automatic else 'explicit_reset',
            hold_escalates_to_latch=not automatic)
        return cls(frames['base'], frames['odom'], guard.get('profile', 'official-model'),
                   float(linear), float(angular), float(timeout), capacity,
                   candidates, subscribers, geometry, **options,
                   timing_profile=timing_profile,
                   odom_timeout_s=0.35 if timing_profile == 'tolerant' else ODOM_AGE,
                   hold_timeout_s=None if automatic else 2.0,
                   recovery_policy='auto_resume' if automatic else 'explicit_reset',
                   hold_escalates_to_latch=not automatic)


def validate_scan(raw):
    """Validate native scan metadata and coverage before any TF lookup result."""
    ranges = raw.get('ranges')
    if not isinstance(ranges, (list, tuple)) or not 1 <= len(ranges) <= MAX_SCAN_POINTS:
        raise ValueError('scan count outside bounded range')
    low, high = raw.get('range_min'), raw.get('range_max')
    angle, increment = raw.get('angle_min'), raw.get('angle_increment')
    if not all(map(finite, (low, high, angle, increment))) or not 0 <= low < high or increment == 0:
        raise ValueError('invalid scan metadata')
    if (not isinstance(raw.get('frame_id'), str) or not raw['frame_id']
            or abs(increment) * (len(ranges) - 1) > 2 * math.pi + 0.1):
        raise ValueError('invalid scan frame or angular span')
    if sum(finite(distance) and low <= distance <= high for distance in ranges) < 100:
        raise ValueError('insufficient finite scan returns (need 100)')


def project_scan(raw, transform):
    """Transform scan endpoints using the TF actually returned at scan time."""
    validate_scan(raw)
    if transform is None:
        raise ValueError('scan TF unavailable')
    if 'stamp' in transform and not finite(transform['stamp']):
        raise ValueError('nonfinite scan TF stamp')
    ranges = raw['ranges']
    low, high = raw['range_min'], raw['range_max']
    angle, increment = raw['angle_min'], raw['angle_increment']
    tx, ty, tz = vector(transform.get('translation'), 3, 'TF translation')
    qx, qy, qz, qw = normalized_quaternion(transform.get('rotation'))
    points = []
    for index, distance in enumerate(ranges):
        if not finite(distance) or not low <= distance <= high:
            continue
        theta = angle + index * increment
        x, y = distance * math.cos(theta), distance * math.sin(theta)
        point = {'index': index, 'range': distance,
                 'x': tx + (1-2*(qy*qy+qz*qz))*x + 2*(qx*qy-qz*qw)*y,
                 'y': ty + 2*(qx*qy+qz*qw)*x + (1-2*(qx*qx+qz*qz))*y,
                 'z': tz + 2*(qx*qz-qy*qw)*x + 2*(qy*qz+qx*qw)*y}
        if not all(map(finite, point.values())):
            raise ValueError('nonfinite transformed scan point')
        points.append(point)
    if len(points) < 100:
        raise ValueError('insufficient finite scan returns (need 100)')
    return {**raw, 'points_base': points, 'transform': deepcopy(transform)}


def ownership_reason(graph, settings, own_name, execute):
    if sorted(graph.get('candidate_publishers', [])) != sorted(settings.expected_candidate_publishers):
        return 'candidate publisher ownership mismatch'
    expected = [own_name] if execute else []
    if sorted(graph.get('final_publishers', [])) != expected:
        return 'final publisher ownership mismatch'
    if sorted(graph.get('final_subscribers', [])) != sorted(settings.expected_final_subscribers):
        return 'final subscriber ownership mismatch'
    return None


class CommandGuard:
    """ROS-independent state machine. All times are supplied by its adapter."""

    def __init__(self, settings):
        self.settings = settings
        self.ring = deque(maxlen=settings.ring_capacity)
        self.events = deque(maxlen=8)
        self.latest = {}
        self.zones = {}
        self.graph = {}
        self.owner_issue = 'ownership not checked'
        self.armed = False
        self.motion_active = False
        self.motion_ros = None
        self.motion_sequence = 0
        self.latched_reason = None
        self.status = 'priming'
        self.sequence = 0
        self.event_sequence = 0
        self.cm_action = 0
        self.cm_polygon = ''
        self.hold_started = None
        self.hold_reason = None
        self.hold_healthy_since = None
        self.hold_needs_command = False
        self.hold_motion = False
        self.resume_ros = None
        self.resume_sequence = 0
        self.last_tick_ros = None

    def _store(self, kind, data, stamp, ros_now, steady_now, error=None):
        self.sequence += 1
        record = {'sequence': self.sequence, 'kind': kind, 'data': json_safe(deepcopy(data)),
                  'source_stamp': json_safe(stamp), 'received_ros': json_safe(ros_now),
                  'received_steady': json_safe(steady_now),
                  'error': error}
        self.latest[kind] = record
        self.ring.append(record)
        return record

    def accept_command(self, values, stamp, ros_now, steady_now, desired=False):
        error = None
        try:
            values = vector(values, 6, 'Twist')
            if any(values[index] != 0 for index in (1, 2, 3, 4)):
                raise ValueError('unsupported Twist axis')
            if (abs(values[0]) > self.settings.max_linear_speed + 1e-9
                    or abs(values[5]) > self.settings.max_angular_speed + 1e-9):
                raise ValueError('command exceeds configured speed limits')
            if (not all(map(finite, (stamp, ros_now)))
                    or (self.settings.timing_profile == 'strict' and (
                        ros_now-stamp < -FUTURE_AGE-1e-9
                        or (any(values) and ros_now-stamp > self.settings.command_timeout_s+1e-9)))):
                raise ValueError('command source timestamp outside freshness limit')
            # A valid old zero cannot move the robot. Preserve its old stamp so
            # tick handles it as idle expiry, without arming or replaying it.
        except ValueError as exc:
            error = str(exc)
        self._store('desired_command' if desired else 'command', {'twist': values}, stamp,
                    ros_now, steady_now, error)

    def accept_odom(self, raw, stamp, ros_now, steady_now):
        error = None
        try:
            for name in ('position', 'linear', 'angular'):
                vector(raw.get(name), 3, 'odom ' + name)
            normalized_quaternion(raw.get('orientation'))
            if raw.get('frame_id') != self.settings.odom_frame or raw.get('child_frame_id') != self.settings.base_frame:
                raise ValueError('odom frames disagree with configuration')
        except ValueError as exc:
            error = str(exc)
        self._store('odom', raw, stamp, ros_now, steady_now, error)

    def accept_scan(self, raw, transform, stamp, ros_now, steady_now, tf_error=None, tf_unavailable=False):
        error, tf_issue = None, None
        # Never retain an unbounded array, even when a message is malformed.
        bounded = dict(raw)
        ranges = raw.get('ranges')
        bounded['ranges'] = list(ranges)[:MAX_SCAN_POINTS] if isinstance(ranges, (list, tuple)) else []
        try:
            expected_frame = self.settings.geometry['frames'].get('scan')
            if expected_frame is not None and raw.get('frame_id') != expected_frame:
                raise ValueError('scan frame disagrees with configuration')
            validate_scan(raw)
            if tf_error:
                if not tf_unavailable:
                    raise ValueError(tf_error)
                tf_issue = tf_error
            else:
                if transform is not None and (
                        transform.get('target_frame', self.settings.base_frame) != self.settings.base_frame
                        or transform.get('source_frame', raw['frame_id']) != raw['frame_id']):
                    raise ValueError('scan TF frames disagree with requested transform')
                bounded = project_scan(raw, transform)
        except ValueError as exc:
            error = str(exc)
        record = self._store('scan', bounded, stamp, ros_now, steady_now, error)
        record['tf_issue'] = tf_issue

    def set_ownership(self, graph, issue):
        self.graph, self.owner_issue = deepcopy(graph), issue

    def _age_issue(self, kind, limit, ros_now, steady_now):
        record = self.latest.get(kind)
        if record is None:
            return kind + ': missing'
        if record['error']:
            return kind + ': malformed: ' + record['error']
        stamp = record['source_stamp']
        if not all(map(finite, (ros_now, steady_now, stamp, record['received_steady']))):
            return kind + ': invalid clock or source stamp'
        if record.get('tf_issue'):
            return kind + ': ' + record['tf_issue']
        received_age = steady_now - record['received_steady']
        source_age = ros_now - stamp
        if received_age < -1e-9 or received_age > limit + 1e-9:
            return kind + ': receive timeout'
        if source_age < -FUTURE_AGE - 1e-9:
            return kind + ': source stamp in future'
        if source_age > limit + 1e-9:
            return kind + ': source stamp too old'
        return None

    def health_issue(self, ros_now, steady_now):
        return (self._age_issue('odom', self.settings.odom_timeout_s, ros_now, steady_now)
                or self._age_issue('scan', SCAN_AGE, ros_now, steady_now)
                or self.owner_issue
                or ('collision monitor invalid source' if self.cm_action == 1
                    and self.cm_polygon == 'invalid source' else None))

    def snapshot(self, reason, kind, ros_now, steady_now):
        # _store owns its copied payloads and never mutates them. Freeze the record
        # selection and scalar ages now, without walking scan arrays on the stop
        # path. The recorder materializes JSON only after the adapter publishes.
        def ages(record):
            item = dict(record)
            item['receive_age_s'] = (steady_now - record['received_steady']
                                     if finite(steady_now) and finite(record['received_steady']) else None)
            item['source_age_s'] = (ros_now - record['source_stamp']
                                    if finite(ros_now) and finite(record['source_stamp']) else None)
            return item
        self.event_sequence += 1
        return {'schema_version': 1, 'event_sequence': self.event_sequence,
                          'kind': kind, 'reason': reason, 'ros_time': json_safe(ros_now),
                          'steady_time': json_safe(steady_now), 'profile': self.settings.profile,
                          'motion_active': self.motion_active, 'hold_motion': self.hold_motion,
                          'geometry': self.settings.geometry, 'zones': dict(self.zones),
                          'graph': self.graph, 'latest': {key: ages(value) for key, value in self.latest.items()},
                          'ring': [ages(record) for record in self.ring],
                          'collision_association': 'latest received data at state callback; '
                          'CM state has no source timestamp or scan sequence'}

    def _event(self, reason, kind, ros_now, steady_now, **details):
        if len(self.events) == self.events.maxlen:
            self.latched_reason = 'trigger event queue full'
        event = self.snapshot(reason, kind, ros_now, steady_now)
        event.update(details)
        self.events.append(event)

    def latch(self, reason, ros_now, steady_now):
        if self.latched_reason is None:
            self.latched_reason = reason
            self._event(reason, 'health_stop', ros_now, steady_now)
        self.status = 'latched: ' + self.latched_reason

    def accept_collision_state(self, action, polygon, ros_now, steady_now):
        if not isinstance(action, int) or isinstance(action, bool) or action not in range(5) or not isinstance(polygon, str):
            self.latch('malformed CollisionMonitorState', ros_now, steady_now)
            return
        polygon = polygon[:256]
        changed = (action, polygon) != (self.cm_action, self.cm_polygon)
        self._store('collision_state', {'action_type': action, 'polygon_name': polygon},
                    None, ros_now, steady_now)
        self.cm_action, self.cm_polygon = action, polygon
        if changed:
            if action == 1:
                self._event('collision monitor stop: ' + polygon, 'collision_stop', ros_now, steady_now)
            # Record the triggering candidate first, then prevent its later replay.
            self.latest.pop('command', None)
        if action == 1 and polygon == 'invalid source' and self.armed:
            if self.settings.timing_profile == 'tolerant':
                self._timing_hold('collision monitor invalid source', ros_now, steady_now)
            else:
                self.latch('collision monitor invalid source', ros_now, steady_now)

    def tick(self, ros_now, steady_now):
        if self.settings.timing_profile == 'tolerant':
            return self._tolerant_tick(ros_now, steady_now)
        if self.latched_reason is not None:
            self.status = 'latched: ' + self.latched_reason
            return ZERO
        issue = self.health_issue(ros_now, steady_now)
        command = self.latest.get('command')
        if issue:
            if self.armed:
                self.latch(issue, ros_now, steady_now)
            else:
                self.status = 'priming: ' + issue
                # A command rejected before readiness cannot later start the robot.
                self.latest.pop('command', None)
            return ZERO
        if command is None:
            self.status = ('collision monitor stop: ' + self.cm_polygon if self.cm_action == 1
                           else ('ready; awaiting new command' if self.armed else 'priming: awaiting command'))
            return ZERO
        issue = self._age_issue('command', self.settings.command_timeout_s, ros_now, steady_now)
        values = command['data']['twist']
        moving = bool(command['error']) or values[0] != 0 or values[5] != 0
        if issue:
            idle_expiry = not moving and issue in ('command: receive timeout', 'command: source stamp too old')
            if self.armed and not idle_expiry:
                self.latch(issue, ros_now, steady_now)
            else:
                self.status = 'idle: ' + issue
                self.latest.pop('command', None)
            return ZERO
        self.armed = True
        if self.cm_action == 1:
            self.status = 'collision monitor stop: ' + self.cm_polygon
            return ZERO
        self.status = 'healthy'
        return values[0], values[5]

    def _hard_issue(self, ros_now, steady_now):
        """Inspect every hard fault before a recoverable age issue can hide it."""
        if not all(map(finite, (ros_now, steady_now))):
            return 'invalid guard clock'
        if self.owner_issue:
            return self.owner_issue
        for kind in ('odom', 'scan', 'command'):
            record = self.latest.get(kind)
            if record is None:
                continue
            if record['error']:
                return kind + ': malformed: ' + record['error']
            stamp, received = record['source_stamp'], record['received_steady']
            if not all(map(finite, (stamp, received))) or steady_now < received - 1e-9:
                return kind + ': invalid clock or source stamp'
        return None

    def _clear_hold(self):
        self.hold_started = self.hold_reason = self.hold_healthy_since = None
        self.hold_needs_command = False
        self.hold_motion = False

    def _observe_motion(self, ros_now, steady_now):
        """Only healthy feedback and a fresh zero can retire passed motion."""
        if self._age_issue('odom', self.settings.odom_timeout_s, ros_now, steady_now):
            return
        record = self.latest['odom']
        odom = record['data']
        if any(odom['linear']) or any(odom['angular']):
            self.motion_active = True
            if record['sequence'] > self.motion_sequence:
                self.motion_sequence = record['sequence']
                self.motion_ros = max(record['source_stamp'], self.motion_ros or record['source_stamp'])
            return
        if self.motion_ros is not None and (record['sequence'] <= self.motion_sequence
                or record['source_stamp'] < self.motion_ros - 1e-9):
            return
        if self.hold_started is None and not self._age_issue(
                'command', self.settings.command_timeout_s, ros_now, steady_now):
            if not any(self.latest['command']['data']['twist']):
                self.motion_active = False

    def _timing_hold(self, issue, ros_now, steady_now):
        if self.hold_started is None:
            self.hold_started, self.hold_reason = steady_now, issue
            self.hold_motion = self.motion_active
            self._event(issue, 'timing_pause', ros_now, steady_now)
        self.hold_motion = self.hold_motion or self.motion_active
        if issue.startswith('command:'):
            self.hold_needs_command = True
            self.hold_motion = True
        self.hold_healthy_since = None
        self.latest.pop('command', None)
        if self.latched_reason is None:
            self.status = 'timing hold: ' + issue
        else:
            self.status = 'latched: ' + self.latched_reason
        return ZERO

    def _tolerant_tick(self, ros_now, steady_now):
        if self.latched_reason is not None:
            self.status = 'latched: ' + self.latched_reason
            return ZERO
        hard = self._hard_issue(ros_now, steady_now)
        if hard:
            if self.armed:
                self.latch(hard, ros_now, steady_now)
            else:
                self.status = 'priming: ' + hard
                self.latest.pop('command', None)
            return ZERO
        previous_ros, self.last_tick_ros = self.last_tick_ros, ros_now
        if previous_ros is not None and previous_ros - ros_now > FUTURE_AGE + 1e-9:
            # The old epoch cannot remain the lower bound for new commands.
            self.resume_ros = None
            self.motion_ros, self.motion_sequence = None, self.sequence
            return self._timing_hold('guard clock moved backwards', ros_now, steady_now)
        self._observe_motion(ros_now, steady_now)
        issue = self.health_issue(ros_now, steady_now)
        if issue:
            if self.armed:
                return self._timing_hold(issue, ros_now, steady_now)
            self.status = 'priming: ' + issue
            self.latest.pop('command', None)
            return ZERO
        command = self.latest.get('command')
        if command and self.resume_ros is not None and (
                command['sequence'] <= self.resume_sequence
                or command['source_stamp'] < self.resume_ros - 1e-9):
            # Receive freshness alone cannot authorize a queued pre-recovery command.
            self.latest.pop('command', None)
            command = None
        if command:
            issue = self._age_issue('command', self.settings.command_timeout_s, ros_now, steady_now)
            if issue:
                if not any(command['data']['twist']) and issue in (
                        'command: receive timeout', 'command: source stamp too old'):
                    self.latest.pop('command', None)
                    command = None
                    self.status = 'idle: ' + issue
                elif self.armed:
                    return self._timing_hold(issue, ros_now, steady_now)
                else:
                    self.latest.pop('command', None)
                    self.status = 'priming: ' + issue
                    return ZERO
        if self.hold_started is not None:
            if self.hold_needs_command:
                if command is None:
                    return self._timing_hold('command: awaiting fresh candidate', ros_now, steady_now)
                self.hold_needs_command = False
            self.hold_motion = self.hold_motion or self.motion_active
            self.latest.pop('command', None)
            if self.hold_healthy_since is None:
                self.hold_healthy_since = steady_now
            if steady_now - self.hold_healthy_since < self.settings.recovery_s - 1e-9:
                self.status = 'timing recovery: waiting for stable health'
                return ZERO
            self._event(self.hold_reason, 'timing_recovered', ros_now, steady_now,
                        duration_s=steady_now - self.hold_started)
            self._clear_hold()
            self.resume_ros, self.resume_sequence = ros_now, self.sequence
            self.status = 'ready; awaiting new command after timing recovery'
            return ZERO
        if command is None:
            self.status = ('collision monitor stop: ' + self.cm_polygon if self.cm_action == 1
                           else ('ready; awaiting new command' if self.armed else 'priming: awaiting command'))
            return ZERO
        self.armed = True
        if self.cm_action == 1:
            self.status = 'collision monitor stop: ' + self.cm_polygon
            return ZERO
        self.status = 'healthy'
        values = command['data']['twist']
        if values[0] != 0 or values[5] != 0:
            self.motion_active = True
            self.motion_ros, self.motion_sequence = ros_now, self.sequence
        return values[0], values[5]

    def reset(self, ros_now, steady_now):
        hard = self._hard_issue(ros_now, steady_now) if self.settings.timing_profile == 'tolerant' else None
        issue = hard or self.health_issue(ros_now, steady_now) or self._age_issue(
            'command', self.settings.command_timeout_s, ros_now, steady_now)
        command = self.latest.get('command')
        if issue:
            return False, issue
        if any(command['data']['twist']):
            return False, 'reset requires a fresh zero candidate'
        if self.cm_action == 1 and self.cm_polygon == 'invalid source':
            return False, 'collision monitor still reports invalid source'
        self.latched_reason = None
        self._clear_hold()
        self.resume_ros, self.resume_sequence = ros_now, self.sequence
        self.latest.pop('command', None)
        self.armed = True
        odom = self.latest['odom']['data']
        self.motion_active = bool(any(odom['linear']) or any(odom['angular']))
        self.motion_ros, self.motion_sequence = None, 0
        self.last_tick_ros = ros_now
        self.status = 'reset; awaiting new command'
        return True, self.status


def write_snapshot(directory, snapshot):
    """Exclusive 0600 creation; the caller supplies a private owned directory."""
    path = Path(directory) / ('trigger-' + uuid.uuid4().hex + '.json')
    content = json.dumps(json_safe(snapshot), ensure_ascii=False, allow_nan=False, indent=2)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    return path


class TriggerRecorder:
    """Disk writes run outside the command timer; its backlog is bounded."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('output directory must be owned by this user and private (0700)')
        self.pending = queue.Queue(maxsize=4)
        self.error = None
        self.last_path = None
        self.worker = threading.Thread(target=self._run, name='fishbot-trigger-writer', daemon=True)
        self.worker.start()

    def submit(self, event):
        try:
            self.pending.put_nowait(event)
        except queue.Full:
            self.error = 'trigger disk queue full'

    def _run(self):
        while True:
            event = self.pending.get()
            try:
                if event is None:
                    return
                self.last_path = str(write_snapshot(self.directory, event))
            except Exception as exc:
                self.error = 'trigger write failed: ' + str(exc)
            finally:
                self.pending.task_done()

    def close(self):
        try:
            self.pending.put(None, timeout=0.2)
        except queue.Full:
            self.error = 'trigger writer still busy at shutdown'
            return
        self.worker.join(timeout=1.0)
        if self.worker.is_alive():
            self.error = 'trigger writer did not finish at shutdown'


def create_ros_node(settings, recorder, execute):
    # ROS is imported only by the runtime adapter; unit tests need none of it.
    import rclpy
    from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
    from geometry_msgs.msg import Point, PolygonStamped, Twist, TwistStamped
    from nav_msgs.msg import Odometry
    from nav2_msgs.msg import CollisionMonitorState
    from rclpy.clock import Clock, ClockType
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from rclpy.time import Time
    from sensor_msgs.msg import LaserScan
    from std_srvs.srv import Trigger
    from tf2_ros import (Buffer, ConnectivityException, ExtrapolationException,
                         LookupException, TimeoutException, TransformListener)
    from visualization_msgs.msg import Marker, MarkerArray

    def stamp_seconds(stamp):
        return stamp.sec + stamp.nanosec / 1e9

    def xyz(value):
        return [value.x, value.y, value.z]

    def twist_values(value):
        return xyz(value.linear) + xyz(value.angular)

    class GuardNode(Node):
        def __init__(self):
            super().__init__('fishbot_command_guard')
            self.guard = CommandGuard(settings)
            self.recorder = recorder
            self.execute = execute
            self.publisher = None
            if execute:
                self.publisher = self.create_publisher(
                    TwistStamped if settings.output_stamped else Twist, settings.output_topic, 1)
            qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
            latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                                 reliability=ReliabilityPolicy.RELIABLE)
            self.diagnostics = self.create_publisher(DiagnosticArray, '~/diagnostics', 1)
            self.markers = self.create_publisher(MarkerArray, '~/markers', latched)
            self.trigger_markers_visible = False
            self.tf_buffer = Buffer(node=self)
            self.tf_listener = TransformListener(self.tf_buffer, self)
            self.create_subscription(TwistStamped, settings.candidate_topic, self.on_command, qos)
            self.create_subscription(TwistStamped, '/cmd_vel_smoothed', self.on_desired, qos)
            self.create_subscription(Odometry, '/odom', self.on_odom, qos)
            self.create_subscription(LaserScan, '/scan', self.on_scan, qos)
            self.create_subscription(CollisionMonitorState, '/collision_monitor_state', self.on_collision, 1)
            options = settings.geometry.get('command_guard', {})
            for name, default in (('stop_polygon', '/passage_stop_polygon'),
                                  ('slow_polygon', '/passage_slow_polygon'),
                                  ('footprint', '/local_costmap/published_footprint')):
                self.create_subscription(PolygonStamped, options.get(name + '_topic', default),
                                         lambda msg, key=name: self.on_polygon(key, msg), qos)
            self.create_service(Trigger, '~/reset', self.on_reset)
            self.create_service(Trigger, '~/stop', self.on_stop)
            self.last_diagnostic = 0.0
            # Steady time still expires commands when simulation /clock is paused.
            self.timer = self.create_timer(0.05, self.evaluate, clock=Clock(clock_type=ClockType.STEADY_TIME))

        def times(self):
            return self.get_clock().now().nanoseconds / 1e9, time.monotonic()

        def on_command(self, msg):
            self.guard.accept_command(twist_values(msg.twist), stamp_seconds(msg.header.stamp), *self.times())
            self.evaluate()

        def on_desired(self, msg):
            self.guard.accept_command(twist_values(msg.twist), stamp_seconds(msg.header.stamp),
                                      *self.times(), desired=True)

        def on_odom(self, msg):
            q = msg.pose.pose.orientation
            self.guard.accept_odom({'frame_id': msg.header.frame_id, 'child_frame_id': msg.child_frame_id,
                                    'position': xyz(msg.pose.pose.position),
                                    'orientation': [q.x, q.y, q.z, q.w],
                                    'linear': xyz(msg.twist.twist.linear), 'angular': xyz(msg.twist.twist.angular)},
                                   stamp_seconds(msg.header.stamp), *self.times())

        def on_scan(self, msg):
            raw = {'frame_id': msg.header.frame_id, 'angle_min': msg.angle_min,
                   'angle_increment': msg.angle_increment, 'range_min': msg.range_min,
                   'range_max': msg.range_max, 'ranges': list(msg.ranges)[:MAX_SCAN_POINTS + 1]}
            transform, error, unavailable = None, None, False
            try:
                tf = self.tf_buffer.lookup_transform(settings.base_frame, msg.header.frame_id,
                                                     Time.from_msg(msg.header.stamp))
                q = tf.transform.rotation
                transform = {'translation': xyz(tf.transform.translation),
                             'rotation': [q.x, q.y, q.z, q.w], 'target_frame': tf.header.frame_id,
                             'source_frame': tf.child_frame_id,
                             'stamp': stamp_seconds(tf.header.stamp)}
            except (LookupException, ConnectivityException, ExtrapolationException, TimeoutException) as exc:
                unavailable = True
                error = 'scan TF unavailable (' + type(exc).__name__ + '): ' + str(exc)[:300]
            except Exception as exc:
                error = 'scan TF failure (' + type(exc).__name__ + '): ' + str(exc)[:300]
            self.guard.accept_scan(raw, transform, stamp_seconds(msg.header.stamp), *self.times(),
                                   tf_error=error, tf_unavailable=unavailable)

        def on_collision(self, msg):
            self.guard.accept_collision_state(msg.action_type, msg.polygon_name, *self.times())
            self.evaluate()

        def on_polygon(self, name, msg):
            points = [[point.x, point.y, point.z] for point in msg.polygon.points[:128]]
            self.guard.zones[name] = json_safe({'frame_id': msg.header.frame_id,
                                               'source_stamp': stamp_seconds(msg.header.stamp),
                                               'received_ros': self.times()[0], 'points': points})

        def update_ownership(self):
            # Duplicate names remain duplicate entries and therefore fail ownership checks.
            graph = {'candidate_publishers': [info.node_name for info in self.get_publishers_info_by_topic(settings.candidate_topic)],
                     'final_publishers': [info.node_name for info in self.get_publishers_info_by_topic(settings.output_topic)],
                     'final_subscribers': [info.node_name for info in self.get_subscriptions_info_by_topic(settings.output_topic)]}
            self.guard.set_ownership(graph, ownership_reason(graph, settings, self.get_name(), execute))

        def publish_velocity(self, velocity):
            if self.publisher is None:
                return
            if velocity != ZERO:
                # Markers describe a stopped incident, not a live obstacle map.
                self.clear_trigger_markers()
            msg = TwistStamped() if settings.output_stamped else Twist()
            twist = msg.twist if settings.output_stamped else msg
            if settings.output_stamped:
                msg.header.stamp = self.get_clock().now().to_msg()
            twist.linear.x, twist.angular.z = velocity
            self.publisher.publish(msg)

        def on_reset(self, request, response):
            try:
                self.update_ownership()
                if self.recorder.error:
                    response.success, response.message = False, self.recorder.error
                else:
                    response.success, response.message = self.guard.reset(*self.times())
                self.publish_velocity(ZERO)
                if response.success:
                    self.clear_trigger_markers()
            except Exception as exc:
                response.success, response.message = False, str(exc)
            return response

        def on_stop(self, request, response):
            self.guard.latch('operator/task stop', *self.times())
            self.publish_velocity(ZERO)
            self.evaluate()
            response.success, response.message = True, self.guard.status
            return response

        def evaluate(self):
            ros_now, steady_now = self.times()
            try:
                self.update_ownership()
                if self.recorder.error:
                    self.guard.latch(self.recorder.error, ros_now, steady_now)
                velocity = self.guard.tick(ros_now, steady_now)
            except Exception as exc:
                self.guard.latch('guard exception: ' + str(exc), ros_now, steady_now)
                velocity = ZERO
            # Publish the stop before enqueuing evidence or doing visualization work.
            self.publish_velocity(velocity)
            while self.guard.events:
                event = self.guard.events.popleft()
                self.recorder.submit(event)
                self.publish_trigger(event)
            if steady_now - self.last_diagnostic >= 0.5:
                self.last_diagnostic = steady_now
                msg = DiagnosticArray()
                msg.header.stamp = self.get_clock().now().to_msg()
                status = DiagnosticStatus()
                status.name, status.hardware_id = 'fishbot_command_guard', 'official-model-unmeasured'
                level = 2 if self.guard.latched_reason else (0 if self.guard.status == 'healthy' else 1)
                status.level = bytes([level])
                status.message = self.guard.status
                status.values = [KeyValue(key='execute', value=str(execute)),
                                 KeyValue(key='profile', value=settings.profile),
                                 KeyValue(key='timing_profile', value=settings.timing_profile),
                                 KeyValue(key='command_timeout_s', value=str(settings.command_timeout_s)),
                                 KeyValue(key='odom_timeout_s', value=str(settings.odom_timeout_s)),
                                 KeyValue(key='hold_timeout_s', value='none' if settings.hold_timeout_s is None
                                          else str(settings.hold_timeout_s)),
                                 KeyValue(key='recovery_s', value=str(settings.recovery_s)),
                                 KeyValue(key='recovery_policy', value=settings.recovery_policy),
                                 KeyValue(key='hold_escalates_to_latch',
                                          value=str(settings.hold_escalates_to_latch)),
                                 KeyValue(key='motion_active', value=str(self.guard.motion_active)),
                                 KeyValue(key='hold_motion', value=str(self.guard.hold_motion)),
                                 KeyValue(key='last_trigger', value=self.recorder.last_path or '')]
                msg.status = [status]
                self.diagnostics.publish(msg)

        def publish_trigger(self, event):
            msg = MarkerArray()
            clear = Marker()
            clear.action = Marker.DELETEALL
            msg.markers.append(clear)
            scan = event['latest'].get('scan', {}).get('data', {})
            marker = Marker()
            marker.header.frame_id = settings.base_frame
            marker.header.stamp = self.get_clock().now().to_msg()
            marker.ns, marker.id, marker.type = 'trigger_scan', 0, Marker.POINTS
            marker.pose.orientation.w = 1.0
            marker.scale.x = marker.scale.y = 0.02
            marker.color.r = marker.color.a = 1.0
            marker.points = [Point(x=point['x'], y=point['y'], z=point['z'])
                             for point in scan.get('points_base', [])]
            msg.markers.append(marker)
            for index, (name, zone) in enumerate(event['zones'].items(), start=1):
                if not zone['points'] or not all(all(map(finite, point)) for point in zone['points']):
                    continue
                outline = Marker()
                outline.header.frame_id = zone['frame_id']
                outline.header.stamp = marker.header.stamp
                outline.ns, outline.id, outline.type = name, index, Marker.LINE_STRIP
                outline.pose.orientation.w = 1.0
                outline.scale.x = 0.01
                outline.color.g = outline.color.a = 1.0
                outline.points = [Point(x=float(p[0]), y=float(p[1]), z=float(p[2]))
                                  for p in zone['points'] + zone['points'][:1]]
                msg.markers.append(outline)
            self.markers.publish(msg)
            self.trigger_markers_visible = True

        def clear_trigger_markers(self):
            if not self.trigger_markers_visible:
                return
            msg = MarkerArray()
            clear = Marker()
            clear.action = Marker.DELETEALL
            msg.markers.append(clear)
            self.markers.publish(msg)
            self.trigger_markers_visible = False

    return GuardNode()


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--dry-run', action='store_true', help='default: no final command publisher')
    parser.add_argument('--output-topic')
    parser.add_argument('--candidate-topic')
    parser.add_argument('--output-stamped', action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument('--expected-subscriber', action='append')
    parser.add_argument('--timing-profile', choices=('strict', 'tolerant'), default='strict')
    args, ros_args = parser.parse_known_args(argv)
    if ros_args and ros_args[0] != '--ros-args':
        parser.error('unknown arguments; ROS options must follow --ros-args')
    return args, ros_args


def main(argv=None):
    args, ros_args = parse_arguments(argv)
    import yaml
    settings = Settings.from_mapping(yaml.safe_load(args.config.read_text()),
                                     output_topic=args.output_topic, candidate_topic=args.candidate_topic,
                                     output_stamped=args.output_stamped,
                                     expected_final_subscribers=args.expected_subscriber,
                                     timing_profile=args.timing_profile)
    recorder = TriggerRecorder(args.output_dir)
    import rclpy
    from rclpy.signals import SignalHandlerOptions
    rclpy.init(args=ros_args, signal_handler_options=SignalHandlerOptions.NO)
    interrupted = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda signum, frame: interrupted.set())
    node = None
    try:
        node = create_ros_node(settings, recorder, args.execute)
        while rclpy.ok() and not interrupted.is_set():
            rclpy.spin_once(node, timeout_sec=0.05)
    finally:
        if node is not None:
            for _ in range(5):
                try:
                    node.publish_velocity(ZERO)
                except Exception as exc:
                    node.get_logger().error('shutdown zero publish failed: ' + str(exc))
                time.sleep(0.05)
            node.destroy_node()
        recorder.close()
        if rclpy.ok():
            rclpy.shutdown()
    if recorder.error:
        raise RuntimeError(recorder.error)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
