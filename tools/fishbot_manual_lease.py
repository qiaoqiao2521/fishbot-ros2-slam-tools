"""Manual admission inside the existing mission owner; no ROS executor or HTTP server.

Every nonzero publication originates in one fresh command request. ``tick`` can
only publish zero, maintain the upstream Nav2 lock, and collect existing replies.
The caller serializes these methods on its existing ROS owner thread.
"""
from dataclasses import dataclass
import copy
import math
import uuid

from cooperation_core import ContinuousEvidence


PROFILE_ID = 'passage_manual'
LIMITS = {'forward_mps': .08, 'reverse_mps': .03, 'angular_rps': .25,
          'command_ttl_ms': 250, 'acquire_ttl_ms': 1000, 'heartbeat_ms': 140}
TERMINAL = {'succeeded', 'failed', 'canceled'}
LIVE_LEASE = {'arming', 'ready', 'active'}
IDLE_TIMING_REASONS = {'odom: receive timeout', 'odom: source stamp too old',
                       'scan: receive timeout', 'scan: source stamp too old'}


def idle_timing_evidence(document, reason):
    """Admit only a recorded strict zero-output, stationary timing incident."""
    try:
        if (reason not in IDLE_TIMING_REASONS or document['reason'] != reason
                or document['kind'] != 'health_stop' or document['schema_version'] != 1
                or document['profile'] != 'fishbot_passage'
                or document['motion_active'] is not False or document['hold_motion'] is not False
                or not finite(document['steady_time'])):
            return False
        settings = document['geometry']['command_guard']
        graph = document['graph']
        if (settings['timing_profile'] != 'strict'
                or sorted(graph['candidate_publishers']) != ['collision_monitor']
                or sorted(graph['final_publishers']) != ['fishbot_command_guard']
                or sorted(graph['final_subscribers']) != sorted(settings['expected_final_subscribers'])):
            return False
        def explicit_zero(record):
            values = record['data']['twist']
            return record['error'] is None and len(values) == 6 and all(finite(v) and v == 0 for v in values)
        latest = document['latest']
        if not explicit_zero(latest['desired_command']):
            return False
        if 'command' in latest:
            if not explicit_zero(latest['command']):
                return False
        else:
            # Strict idle expiry deliberately removes latest.command. Its
            # original bounded ring must still prove explicit zero candidates;
            # absence alone never supplies a zero velocity.
            ring = document['ring']
            capacity = settings.get('ring_capacity', 40)
            if (type(capacity) is not int or not 1 <= capacity <= 512
                    or not isinstance(ring, list) or not 1 <= len(ring) <= capacity):
                return False
            commands = [record for record in ring if record['kind'] in ('command', 'desired_command')]
            if (not any(record['kind'] == 'command' for record in commands)
                    or not all(explicit_zero(record) for record in commands)):
                return False
        scan = document['latest']['scan']
        if scan['error'] is not None or scan['tf_issue'] is not None:
            return False
        collision = document['latest'].get('collision_state')
        if collision and (collision['error'] is not None or collision['data'] == {
                'action_type': 1, 'polygon_name': 'invalid source'}):
            return False
        odom = document['latest']['odom']
        linear, angular = odom['data']['linear'], odom['data']['angular']
        return (odom['error'] is None and len(linear) == len(angular) == 3
                and all(finite(v) for v in [*linear, *angular])
                and math.hypot(*linear[:2]) < .005 and abs(angular[2]) < .02)
    except (KeyError, TypeError, ValueError):
        return False


class ManualError(ValueError):
    def __init__(self, code, status=409, *, unknown=False):
        super().__init__(code)
        self.code, self.status = code, status
        self.unknown = unknown

    def response(self):
        return {'accepted': None if self.unknown else False,
                'outcome': 'unknown' if self.unknown else 'rejected', 'error': self.code}


def canonical_id(value):
    try:
        valid = isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        valid = False
    if not valid:
        raise ManualError('invalid_uuid', 400)
    return value


def native_owner_id(value):
    """Keep the original legacy compact UUID literal; never alias task records."""
    try:
        parsed = uuid.UUID(value) if isinstance(value, str) else None
        valid = parsed is not None and value in (str(parsed), parsed.hex)
    except (ValueError, AttributeError):
        valid = False
    if not valid:
        raise ManualError('invalid_uuid', 400)
    return value


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


@dataclass(frozen=True)
class TimePoint:
    wall_ms: int
    steady: float
    ros: float

    def __post_init__(self):
        if (type(self.wall_ms) is not int or self.wall_ms < 0
                or not finite(self.steady) or not finite(self.ros)):
            raise ManualError('invalid_clock', 503)


class QuietEvidence:
    """Reuse the consecutive-source gate and retain the navigation truth limits."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.gate = ContinuousEvidence(.7, max_gap=.30)
        self.started_steady = self.last_steady = self.last_stamp = None
        self.duration = 0.
        self.confirmed = False

    def observe(self, stamp, linear_speed, angular_speed, now):
        if (not all(finite(value) for value in (stamp, linear_speed, angular_speed))
                or not -.05 <= now.ros-stamp <= .25):
            self.reset()
            return
        # A repeated source frame must not refresh receive age or grow evidence.
        if stamp == self.last_stamp:
            return
        if self.last_stamp is not None and (stamp < self.last_stamp
                or now.steady < self.last_steady or now.steady-self.last_steady > .30):
            self.reset()
        valid = 0 <= linear_speed < .005 and 0 <= angular_speed < .02
        consecutive = self.gate.update(stamp, valid)
        if not valid:
            self.started_steady = None
        elif self.started_steady is None or self.gate.started == stamp:
            self.started_steady = now.steady
        self.last_stamp, self.last_steady = stamp, now.steady
        self.duration = (min(stamp-self.gate.started, now.steady-self.started_steady)
                         if valid else 0.)
        self.confirmed = consecutive and self.duration >= .7-1e-9

    def snapshot(self, now):
        receive_age = None if self.last_steady is None else now.steady-self.last_steady
        source_age = None if self.last_stamp is None else now.ros-self.last_stamp
        fresh = (receive_age is not None and 0 <= receive_age <= .25
                 and -.05 <= source_age <= .25)
        return {'confirmed': bool(self.confirmed and fresh),
                'duration_s': self.duration if fresh else 0.,
                'source': '/ground_truth/free_joint_states', 'source_stamp': self.last_stamp,
                'receive_age_s': receive_age, 'source_age_s': source_age}


class ManualLeaseController:
    """Small admission adapter around injected existing owner/guard operations.

    ports: native_owner()->record, guard_available()->bool,
    publish_manual(v,w,source_ros_stamp), nav_lock(bool),
    guard_stop()/guard_reset()->Future, cancel_native(original_task_id).
    Native records retain task_id/status/native_goal_id/native_status and optional
    cancel_acknowledged. Unknown native terminal evidence always blocks takeover.
    """
    def __init__(self, runtime_instance_id, map_id, ports, *, enabled=False,
                 profile_id=PROFILE_ID, history_limit=4096):
        self.runtime_instance_id = canonical_id(runtime_instance_id)
        if map_id is not None and (not isinstance(map_id, str) or not 1 <= len(map_id) <= 128):
            raise ManualError('invalid_map_id', 400)
        if profile_id != PROFILE_ID:
            raise ManualError('unsupported_manual_profile', 400)
        self.map_id, self.profile_id, self.ports = map_id, profile_id, ports
        self.enabled, self.history_limit = enabled, history_limit
        self.leases, self.stops, self.resets = {}, {}, {}
        self.control_sequences = {}
        self.current_lease = self.current_stop = None
        self.stop_latched = False
        self.pending = []
        self.quiet = QuietEvidence()
        self.native_authority = None
        self.last_native = None
        self.last_steady = None
        self.cleanup_ack = True
        self.output_error = None
        self.guard_reset_needed = False
        self.idle_recoveries, self.idle_recovery = {}, None
        self.idle_epoch_steady = None

    def _envelope(self, body, now, *, operation, extra=()):
        common = {'session_id', 'runtime_instance_id', 'map_id', 'profile_id',
                  'sequence', 'issued_at_ms', 'ttl_ms'}
        if not isinstance(body, dict) or set(body) != common | set(extra):
            raise ManualError('invalid_manual_envelope', 400)
        canonical_id(body['session_id'])
        if self.map_id is None:
            raise ManualError('manual_map_unavailable', 503)
        if body['runtime_instance_id'] != self.runtime_instance_id:
            raise ManualError('runtime_changed')
        if body['map_id'] != self.map_id:
            raise ManualError('task_map_mismatch')
        if body['profile_id'] != self.profile_id:
            raise ManualError('manual_profile_mismatch')
        for key in ('sequence', 'issued_at_ms', 'ttl_ms'):
            if type(body[key]) is not int or not 0 <= body[key] <= 2**53-1:
                raise ManualError('invalid_'+key, 400)
        maximum = LIMITS['command_ttl_ms'] if operation == 'command' else 1000
        if not 50 <= body['ttl_ms'] <= maximum:
            raise ManualError('invalid_ttl_ms', 400)
        age = now.wall_ms-body['issued_at_ms']
        if age < -50 or age >= body['ttl_ms']:
            raise ManualError('manual_request_expired', 408)
        remaining = body['ttl_ms']-max(0, age)
        return now.steady+remaining/1000, now.wall_ms+remaining, now.ros-max(0, age)/1000

    def _native(self):
        value = self.ports.native_owner()
        value = {**value, 'task_id': value.get('task_id', value.get('id'))}
        clear = value.get('status') == 'idle' or (value.get('status') in TERMINAL
                    and value.get('native_status') in (4, 5, 6))
        clear = clear and value.get('cleanup_state') != 'unresolved'
        identity = (value.get('task_id'), clear)
        if self.last_native is not None and identity != self.last_native:
            self.quiet.reset()
        self.last_native = identity
        return {**value, 'terminal': clear}

    def _cleanup_pending(self):
        return any(not item['done'] for item in self.pending)

    def _admission_reason(self, now):
        native = self._native()
        if not self.enabled:
            return 'manual_profile_not_enabled'
        if self.map_id is None:
            return 'manual_map_unavailable'
        if self.stop_latched:
            return 'explicit_stop_latched'
        if self.output_error:
            return self.output_error
        if not native['terminal']:
            return 'native_owner_unresolved'
        if self.current_lease and self.current_lease['state'] in LIVE_LEASE | {'unknown'}:
            return 'manual_lease_busy'
        if self._cleanup_pending() or not self.cleanup_ack:
            return 'manual_cleanup_unconfirmed'
        if not self.quiet.snapshot(now)['confirmed']:
            return 'continuous_quiet_unconfirmed'
        if not self.ports.guard_available():
            return 'guard_unavailable'
        return None

    def status(self, now):
        reason = self._admission_reason(now)
        native = self._native()
        return {'runtime_instance_id': self.runtime_instance_id, 'map_id': self.map_id,
                'profile_id': self.profile_id, 'available': self.enabled,
                'can_acquire': reason is None, 'can_stop': self.enabled,
                'can_reset': bool(self.stop_latched and native['terminal']
                    and self.quiet.snapshot(now)['confirmed'] and not self._cleanup_pending()
                    and self.current_stop and self.current_stop['state'] == 'stopped'),
                'reason': reason, 'stop_latched': self.stop_latched,
                'active_lease_id': (self.current_lease['lease_id'] if self.current_lease
                    and self.current_lease['state'] in LIVE_LEASE | {'unknown'} else None),
                'active_stop_request_id': self.current_stop['request_id'] if self.current_stop else None,
                'native_owner': {key: native.get(key) for key in
                    ('task_id', 'status', 'native_goal_id', 'terminal')},
                'quiet': self.quiet.snapshot(now), 'limits': copy.deepcopy(LIMITS),
                'idle_recovery': (None if self.idle_recovery is None else {
                    key: copy.deepcopy(value) for key, value in self.idle_recovery.items()
                    if not key.startswith('_')}), 'idle_recovery_attempts': len(self.idle_recoveries)}

    def _record(self, book, key):
        canonical_id(key)
        if key not in book:
            raise ManualError('manual_record_not_found', 404)
        return book[key]

    def lease_record(self, lease_id, now):
        record = copy.deepcopy(self._record(self.leases, lease_id))
        record.pop('_deadline', None)
        record['remaining_ms'] = max(0, int((self.leases[lease_id]['_deadline']-now.steady)*1000))
        record['quiet'] = record.get('quiet', self.quiet.snapshot(now))
        return {key: value for key, value in record.items() if not key.startswith('_')}

    def stop_record(self, request_id, now):
        record = copy.deepcopy(self._record(self.stops, request_id))
        record['quiet'] = record.get('quiet', self.quiet.snapshot(now))
        return {key: value for key, value in record.items() if not key.startswith('_')}

    def reset_record(self, request_id):
        return {key: copy.deepcopy(value) for key, value in self._record(self.resets, request_id).items()
                if not key.startswith('_')}

    def _capacity(self, book):
        if len(book) >= self.history_limit:
            raise ManualError('manual_history_capacity', 503)

    def _check_control_sequence(self, operation, body):
        if body['sequence'] <= self.control_sequences.get((body['session_id'], operation), -1):
            raise ManualError('stale_sequence')

    def _call_guard(self, kind, record, now, *, purpose=None):
        if kind == 'stop':
            self.guard_reset_needed = True
        try:
            future = getattr(self.ports, 'guard_'+kind)()
            if not callable(getattr(future, 'done', None)) or not callable(getattr(future, 'result', None)):
                raise TypeError('guard operation did not return a future')
            self.pending.append({'kind': kind, 'record': record, 'future': future,
                                 'deadline': now.steady+1., 'done': False, 'timed_out': False,
                                 'purpose': purpose})
        except Exception as error:
            record.update(state='unknown', reason='guard_'+kind+'_dispatch_failed')
            record['guard_'+kind+'_acknowledged'] = None
            self.cleanup_ack = False

    def _zero(self, now):
        errors = []
        for effect in (lambda: self.ports.nav_lock(True),
                       lambda: self.ports.publish_manual(0., 0., now.ros)):
            try:
                effect()
            except Exception:
                errors.append('manual_zero_dispatch_unknown')
        self.output_error = errors[0] if errors else None
        if errors:
            self.cleanup_ack = False
            if self.current_lease:
                self.current_lease.update(state='unknown', reason=self.output_error)
        return not errors

    def acquire(self, body, now):
        self.tick(now)
        deadline, expiry, _ = self._envelope(body, now, operation='acquire', extra=('lease_id', 'gesture'))
        lease_id = canonical_id(body['lease_id'])
        if body['sequence'] != 0 or body['gesture'] != 'press':
            raise ManualError('new_press_required', 400)
        if lease_id in self.leases:
            raise ManualError('lease_id_already_used')
        reason = self._admission_reason(now)
        if reason:
            raise ManualError(reason, 503 if reason in ('guard_unavailable', 'manual_profile_not_enabled') else 409)
        self._capacity(self.leases)
        self.native_authority = None
        record = {key: body[key] for key in
                  ('lease_id', 'session_id', 'runtime_instance_id', 'map_id', 'profile_id')}
        record.update(last_sequence=0, state='arming', reason=None, expires_at_ms=expiry,
                      _deadline=deadline, guard_reset_acknowledged=None, guard_stop_acknowledged=None)
        self.current_lease = self.leases[lease_id] = record
        self.idle_epoch_steady = now.steady
        if self._zero(now):
            self._call_guard('reset', record, now)
        else:
            self._call_guard('stop', record, now)
        return {'accepted': True, 'outcome': 'accepted', 'lease': self.lease_record(lease_id, now)}

    def _lease_request(self, body, now, operation, extra=()):
        deadline, expiry, stamp = self._envelope(body, now, operation=operation,
                                                extra=('lease_id', *extra))
        record = self._record(self.leases, body['lease_id'])
        if record is not self.current_lease or record['session_id'] != body['session_id']:
            raise ManualError('manual_lease_owner_mismatch')
        if body['sequence'] <= record['last_sequence']:
            raise ManualError('stale_sequence')
        if record['state'] not in LIVE_LEASE:
            raise ManualError('manual_lease_'+record['state'])
        return record, deadline, expiry, stamp

    def command(self, body, now):
        self.tick(now)
        record, deadline, expiry, stamp = self._lease_request(body, now, 'command', ('linear_x', 'angular_z'))
        if record['state'] not in ('ready', 'active'):
            raise ManualError('manual_lease_not_ready')
        if body['issued_at_ms'] < record['_ready_after_ms']:
            raise ManualError('command_predates_ready')
        v, w = body['linear_x'], body['angular_z']
        if (not finite(v) or not finite(w) or not -LIMITS['reverse_mps'] <= v <= LIMITS['forward_mps']
                or abs(w) > LIMITS['angular_rps']):
            raise ManualError('manual_speed_out_of_range', 400)
        if not self._native()['terminal'] or self.stop_latched or not self.ports.guard_available():
            self._revoke('unknown', 'manual_readiness_lost', now)
            raise ManualError('manual_readiness_lost', 503)
        record.update(last_sequence=body['sequence'], state='active', _deadline=deadline, expires_at_ms=expiry)
        try:
            self.ports.nav_lock(True)
            self.ports.publish_manual(v, w, stamp)
        except Exception:
            self._revoke('unknown', 'manual_publish_unknown', now)
            raise ManualError('manual_publish_unknown', 503, unknown=True) from None
        return {'accepted': True, 'outcome': 'accepted', 'lease': self.lease_record(record['lease_id'], now)}

    def _revoke(self, state, reason, now):
        record = self.current_lease
        if record:
            record.update(state=state, reason=reason)
            self.cleanup_ack = False
            self.quiet.reset()
            self._zero(now)
            self._call_guard('stop', record, now)

    def release(self, body, now):
        self.tick(now)
        record, _, _, _ = self._lease_request(body, now, 'release')
        record['last_sequence'] = body['sequence']
        self._revoke('released', 'user_release', now)
        return {'accepted': True, 'outcome': 'accepted', 'lease': self.lease_record(record['lease_id'], now)}

    def stop(self, body, now):
        self.tick(now)
        self._envelope(body, now, operation='stop', extra=('request_id', 'target_id'))
        request_id = canonical_id(body['request_id'])
        if request_id in self.stops:
            original = self.stops[request_id]
            if (original['_session_id'] != body['session_id']
                    or original['_requested_target_id'] != body['target_id']):
                raise ManualError('manual_stop_owner_mismatch')
            return {'accepted': True, 'outcome': 'accepted', 'stop': self.stop_record(request_id, now)}
        if not self.enabled:
            raise ManualError('manual_profile_not_enabled', 503)
        self._capacity(self.stops)
        self._check_control_sequence('stop', body)
        native = self._native()
        active_lease = self.current_lease and self.current_lease['state'] in LIVE_LEASE | {'unknown'}
        target = self.current_lease['lease_id'] if active_lease else native['task_id'] if not native['terminal'] else None
        if body['target_id'] is not None:
            native_owner_id(body['target_id'])
            if body['target_id'] != target:
                raise ManualError('stop_target_changed')
        kind = 'manual' if active_lease else 'mission' if not native['terminal'] else 'idle'
        record = {'request_id': request_id, 'target_id': target, 'target_kind': kind,
                  'state': 'stopping', 'reason': None, 'runtime_instance_id': self.runtime_instance_id,
                  'guard_stop_acknowledged': None, 'native_cancel_acknowledged': None,
                  'native_terminal': native['terminal'],
                  'native_status': None, '_session_id': body['session_id'],
                  '_requested_target_id': body['target_id'],
                  '_native_task_id': None if native['terminal'] else native['task_id']}
        self.current_stop = self.stops[request_id] = record
        self.control_sequences[(body['session_id'], 'stop')] = body['sequence']
        self.stop_latched, self.native_authority, self.cleanup_ack = True, None, False
        self.idle_epoch_steady = now.steady
        if active_lease:
            self.current_lease.update(state='stopped', reason='explicit_stop')
        self.quiet.reset()
        self._zero(now)
        self._call_guard('stop', record, now)
        if record['_native_task_id'] is not None:
            try:
                self.ports.cancel_native(record['_native_task_id'])
            except Exception:
                record.update(state='unknown', reason='native_cancel_dispatch_unknown')
        return {'accepted': True, 'outcome': 'accepted', 'stop': self.stop_record(request_id, now)}

    def reset(self, body, now):
        self.tick(now)
        self._envelope(body, now, operation='reset', extra=('request_id', 'stop_request_id', 'gesture'))
        request_id, stop_id = canonical_id(body['request_id']), canonical_id(body['stop_request_id'])
        if body['gesture'] != 'reset':
            raise ManualError('explicit_reset_required', 400)
        if request_id in self.resets:
            record = self.resets[request_id]
            if record['stop_request_id'] != stop_id or record['_session_id'] != body['session_id']:
                raise ManualError('reset_request_reused')
            return {'accepted': True, 'outcome': 'accepted', 'reset': self.reset_record(request_id)}
        if not self.current_stop or self.current_stop['request_id'] != stop_id:
            raise ManualError('stop_generation_changed')
        if not self.status(now)['can_reset']:
            raise ManualError('stop_cleanup_unconfirmed')
        self._capacity(self.resets)
        self._check_control_sequence('reset', body)
        record = {'request_id': request_id, 'stop_request_id': stop_id, 'state': 'resetting',
                  'runtime_instance_id': self.runtime_instance_id, 'guard_reset_acknowledged': None,
                  'reason': None, '_session_id': body['session_id']}
        self.resets[request_id] = record
        self.control_sequences[(body['session_id'], 'reset')] = body['sequence']
        if self._zero(now):
            self._call_guard('reset', record, now)
        else:
            record.update(state='unknown', reason='manual_zero_dispatch_unknown')
            self._call_guard('stop', self.current_stop, now)
        return {'accepted': True, 'outcome': 'accepted', 'reset': self.reset_record(request_id)}

    def require_native_admission(self, now):
        self.tick(now)
        reason = self._admission_reason(now)
        if reason:
            raise ManualError(reason)
        if self.guard_reset_needed:
            raise ManualError('guard_reset_required')

    def bind_map(self, map_id, now):
        """Fence a real map change without discarding original-ID receipts.

        The existing owner retains responsibility for canceling its native task
        on map/readiness changes. This adapter immediately masks its raw output.
        """
        if not isinstance(map_id, str) or not 1 <= len(map_id) <= 128:
            raise ManualError('invalid_map_id', 400)
        if map_id == self.map_id:
            return
        if self.current_lease and self.current_lease['state'] in LIVE_LEASE | {'unknown'}:
            self._revoke('unknown', 'manual_map_changed', now)
        self.map_id, self.native_authority = map_id, None
        self.idle_epoch_steady = now.steady
        self.quiet.reset()
        self._zero(now)

    def shutdown(self, now):
        """Revoke upstream motion before the existing owner tears down its node."""
        self.native_authority = None
        self.quiet.reset()
        if self.current_lease and self.current_lease['state'] in LIVE_LEASE | {'unknown'}:
            self._revoke('released', 'owner_shutdown', now)
        else:
            self.cleanup_ack = False
            self._zero(now)
            self._call_guard('stop', self.current_stop or {
                'state': 'stopping', 'reason': 'owner_shutdown'}, now)

    def native_started(self, task_id):
        """Called by the existing owner only after its own identified dispatch."""
        if (self.stop_latched or self._cleanup_pending() or not self.cleanup_ack
                or self.current_lease and self.current_lease['state'] in LIVE_LEASE | {'unknown'}):
            raise ManualError('manual_owner_not_released')
        self.native_authority = native_owner_id(task_id)
        self.idle_epoch_steady = self.last_steady
        self.quiet.reset()

    def _idle_context(self):
        read = getattr(self.ports, 'idle_guard_fault', None)
        return read() if read else None

    def _idle_owner_clear(self, now, native):
        return (self.enabled and self.map_id is not None and not self.stop_latched
                and self.native_authority is None and native['terminal']
                and not self.output_error and self.quiet.snapshot(now)['confirmed']
                and not (self.current_lease and self.current_lease['state'] in LIVE_LEASE | {'unknown'}))

    def _idle_identity(self, native):
        return tuple(native.get(key) for key in
                     ('task_id', 'status', 'native_goal_id', 'native_status', 'cleanup_state'))

    def _maybe_recover_idle(self, now, native):
        if (not self._idle_owner_clear(now, native) or self._cleanup_pending() or not self.cleanup_ack):
            return
        fault = self._idle_context()
        if (not fault or fault.get('eligible') is not True
                or not finite(fault.get('steady_time'))
                or fault['steady_time'] < self.idle_epoch_steady
                or fault['steady_time'] > now.steady+.05
                or fault['trigger_id'] in self.idle_recoveries
                or len(self.idle_recoveries) >= self.history_limit):
            return
        record = {'trigger_id': fault['trigger_id'], 'reason': fault['reason'], 'state': 'resetting',
                  'guard_reset_acknowledged': None, 'runtime_instance_id': self.runtime_instance_id,
                  'native_task_id': native['task_id'], '_native_identity': self._idle_identity(native),
                  '_stop_id': self.current_stop['request_id'] if self.current_stop else None,
                  '_map_id': self.map_id, '_epoch': self.idle_epoch_steady}
        self.idle_recovery = self.idle_recoveries[fault['trigger_id']] = record
        self.cleanup_ack, self.guard_reset_needed = False, True
        if self._zero(now):
            self._call_guard('reset', record, now, purpose='idle_health_reset')
        else:
            record.update(state='unknown', reason='manual_zero_dispatch_unknown')
            self._call_guard('stop', record, now)

    def observe_truth(self, stamp, linear_speed, angular_speed, now):
        self._native()
        self.quiet.observe(stamp, linear_speed, angular_speed, now)

    def _guard_reply(self, item, now):
        record, kind = item['record'], item['kind']
        try:
            response = item['future'].result()
            success = getattr(response, 'success', None)
            if type(success) is not bool:
                raise ValueError('malformed guard reply')
        except Exception:
            success = None
        record['guard_'+kind+'_acknowledged'] = success
        if success is not True:
            record.update(state='unknown', reason='guard_'+kind+'_unconfirmed')
            self.cleanup_ack = False
        elif kind == 'stop':
            self.cleanup_ack = True
        elif item.get('purpose') == 'idle_health_reset':
            native, fault = self._native(), self._idle_context()
            same_fault = (fault is not None and fault.get('eligible') is True
                          and fault.get('trigger_id') == record['trigger_id'])
            healthy = fault is None and self.ports.guard_available()
            if (record is self.idle_recovery and not item['timed_out']
                    and self._idle_owner_clear(now, native)
                    and self._idle_identity(native) == record['_native_identity']
                    and self.map_id == record['_map_id'] and self.idle_epoch_steady == record['_epoch']
                    and (self.current_stop['request_id'] if self.current_stop else None) == record['_stop_id']
                    and (same_fault or healthy)):
                record.update(state='ready', reason=None)
                self.cleanup_ack, self.guard_reset_needed = True, False
                self.idle_epoch_steady = now.steady
            else:
                record.update(state='unknown', reason='idle_recovery_owner_or_fault_changed')
                self._zero(now)
                self.cleanup_ack = False
                self._call_guard('stop', self.current_stop or record, now)
        elif item.get('purpose') == 'cleanup_reset':
            if (record is self.current_lease and record['state'] in {'released', 'expired'}
                    and not self.stop_latched and self._native()['terminal']
                    and self.quiet.snapshot(now)['confirmed'] and not item['timed_out']):
                # Ordinary cleanup restores only the healthy zero gate. It does
                # not grant a lease, unlock navigation, or publish stored intent.
                self.guard_reset_needed = False
                self.cleanup_ack = True
                self.idle_epoch_steady = now.steady
            else:
                target = self.current_stop or self.current_lease
                self._zero(now)
                if target:
                    self.cleanup_ack = False
                    self._call_guard('stop', target, now)
        elif 'lease_id' in record:
            if (record is self.current_lease and record['state'] == 'arming'
                    and not self.stop_latched and not item['timed_out']):
                record.update(state='ready', reason=None, _ready_after_ms=now.wall_ms)
                self.guard_reset_needed = False
                self.idle_epoch_steady = now.steady
            else:
                # An old Trigger reset cannot be allowed to undo a later stop.
                target = self.current_stop or self.current_lease
                self._zero(now)
                if target:
                    self.cleanup_ack = False
                    self._call_guard('stop', target, now)
        elif (self.current_stop and record['stop_request_id'] == self.current_stop['request_id']
                and self.current_stop['state'] == 'stopped' and self._native()['terminal']
                and self.quiet.snapshot(now)['confirmed'] and not item['timed_out']):
            self.stop_latched = False
            self.guard_reset_needed = False
            record.update(state='ready', reason=None)
            self.idle_epoch_steady = now.steady
        else:
            record.update(state='unknown', reason='stop_generation_changed')
            target = self.current_stop or self.current_lease
            self._zero(now)
            if target:
                self.cleanup_ack = False
                self._call_guard('stop', target, now)

    def tick(self, now):
        if self.idle_epoch_steady is None:
            self.idle_epoch_steady = now.steady
        if self.last_steady is not None and now.steady < self.last_steady:
            if self.current_lease and self.current_lease['state'] in LIVE_LEASE:
                self._revoke('unknown', 'steady_clock_rollback', now)
            self.quiet.reset()
        self.last_steady = now.steady
        if self.current_lease and self.current_lease['state'] in LIVE_LEASE:
            if now.steady >= self.current_lease['_deadline']:
                self._revoke('expired', 'lease_deadline_elapsed', now)
        for item in list(self.pending):
            if item['done']:
                continue
            if item['future'].done():
                item['done'] = True
                self._guard_reply(item, now)
            elif now.steady >= item['deadline'] and not item['timed_out']:
                item['timed_out'] = True
                item['record'].update(state='unknown', reason='guard_'+item['kind']+'_timeout')
                self.cleanup_ack = False
        # Completed operations need no further polling; unresolved timed-out
        # resets remain fenced until their actual result, never retried.
        self.pending[:] = [item for item in self.pending if not item['done']]
        native = self._native()
        if (self.native_authority is not None and self.native_authority == native['task_id']
                and native['terminal'] and self.quiet.snapshot(now)['confirmed']
                and not self.stop_latched):
            # Retire only this completed UUID's token after independent quiet.
            # Older incidents cannot then masquerade as faults from idle time.
            self.native_authority, self.idle_epoch_steady = None, now.steady
        if (self.current_lease and self.current_lease['state'] in LIVE_LEASE
                and (not native['terminal'] or not self.ports.guard_available())):
            self._revoke('unknown', 'manual_readiness_lost', now)
        allow_nav = (not self.stop_latched and self.native_authority == native['task_id']
                     and not native['terminal'] and native.get('status') in ('running', 'canceling')
                     and not self._cleanup_pending())
        if not allow_nav and not (self.current_lease and self.current_lease['state'] == 'active'):
            was_live = self.current_lease and self.current_lease['state'] in LIVE_LEASE
            if not self._zero(now) and was_live:
                self._call_guard('stop', self.current_lease, now)
        else:
            try:
                self.ports.nav_lock(not allow_nav)
            except Exception:
                self.output_error = 'manual_nav_lock_unknown'
                if self.current_lease and self.current_lease['state'] in LIVE_LEASE:
                    self._revoke('unknown', self.output_error, now)
        if (self.current_lease and self.current_lease['state'] in ('released', 'expired', 'stopped')
                and self.cleanup_ack and not self._cleanup_pending() and self.quiet.snapshot(now)['confirmed']):
            self.current_lease.setdefault('quiet', self.quiet.snapshot(now))
        lease = self.current_lease
        if (lease and lease['state'] in {'released', 'expired'} and self.guard_reset_needed
                and not lease.get('_cleanup_reset_started') and not self.stop_latched
                and self.cleanup_ack and not self._cleanup_pending() and native['terminal']
                and self.quiet.snapshot(now)['confirmed'] and self.ports.guard_available()):
            lease['_cleanup_reset_started'] = True
            lease['guard_reset_acknowledged'] = None
            self._zero(now)
            self._call_guard('reset', lease, now, purpose='cleanup_reset')
        self._maybe_recover_idle(now, native)
        if self.current_stop and self.stop_latched:
            stop = self.current_stop
            if stop['_native_task_id'] is not None:
                if native['task_id'] != stop['_native_task_id']:
                    stop.update(state='unknown', reason='native_owner_changed')
                else:
                    stop.update(native_terminal=native['terminal'], native_status=native.get('native_status'),
                                native_cancel_acknowledged=native.get('cancel_acknowledged'))
            elif not native['terminal']:
                stop.update(state='unknown', reason='native_owner_changed', native_terminal=False)
            if (self.stop_latched and stop['guard_stop_acknowledged'] is True
                    and stop['native_terminal'] is True
                    and self.quiet.snapshot(now)['confirmed'] and not self._cleanup_pending()):
                stop.update(state='stopped', reason=None, quiet=self.quiet.snapshot(now))


class ManualHTTPAdapter:
    """Route already-admitted HTTP work on the existing owner's execution thread."""
    def __init__(self, controller):
        self.controller = controller

    def post(self, path, body, now):
        operations = {'/sim-api/manual/acquire': ('acquire', 202),
                      '/sim-api/manual/command': ('command', 200),
                      '/sim-api/manual/release': ('release', 200),
                      '/sim-api/manual/stop': ('stop', 202),
                      '/sim-api/manual/reset': ('reset', 202)}
        try:
            if path not in operations:
                raise ManualError('manual_endpoint_not_found', 404)
            method, status = operations[path]
            return status, getattr(self.controller, method)(body, now)
        except ManualError as error:
            return error.status, error.response()

    def get(self, path, now):
        try:
            if path == '/sim-api/manual/status':
                if self.controller.map_id is None:
                    raise ManualError('manual_map_unavailable', 503)
                return 200, self.controller.status(now)
            for prefix, field, getter in (
                    ('/sim-api/manual/stops/', 'stop', lambda key: self.controller.stop_record(key, now)),
                    ('/sim-api/manual/resets/', 'reset', self.controller.reset_record),
                    ('/sim-api/manual/', 'lease', lambda key: self.controller.lease_record(key, now))):
                if path.startswith(prefix):
                    return 200, {field: getter(path[len(prefix):])}
            raise ManualError('manual_endpoint_not_found', 404)
        except ManualError as error:
            return error.status, error.response()
