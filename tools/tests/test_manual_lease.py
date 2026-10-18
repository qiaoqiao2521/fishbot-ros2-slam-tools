"""Exercise source admission and late real Future replies without importing ROS."""
import copy
from concurrent.futures import Future
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fishbot_manual_lease import (ManualError, ManualHTTPAdapter, ManualLeaseController,
                                 QuietEvidence, TimePoint, idle_timing_evidence)


def uid():
    return str(uuid.uuid4())


class Ports:
    def __init__(self):
        self.native = {'task_id': None, 'status': 'idle', 'native_goal_id': None, 'native_status': None}
        self.available = True
        self.fault = None
        self.messages, self.locks, self.stops, self.resets, self.cancels = [], [], [], [], []

    def native_owner(self):
        return copy.deepcopy(self.native)

    def guard_available(self):
        return self.available

    def idle_guard_fault(self):
        return copy.deepcopy(self.fault)

    def publish_manual(self, v, w, stamp):
        self.messages.append((v, w, stamp))

    def nav_lock(self, value):
        self.locks.append(value)

    def guard_stop(self):
        future = Future()
        self.stops.append(future)
        return future

    def guard_reset(self):
        future = Future()
        self.resets.append(future)
        return future

    def cancel_native(self, task_id):
        self.cancels.append(task_id)


class ManualFixture(unittest.TestCase):
    def setUp(self):
        self.ports = Ports()
        self.instance, self.session = uid(), uid()
        self.clock = TimePoint(100_000, 100., 10.)
        self.controller = ManualLeaseController(self.instance, 'map-a', self.ports, enabled=True)
        self.quiet()

    def advance(self, seconds):
        old = self.clock
        self.clock = TimePoint(old.wall_ms+round(seconds*1000), old.steady+seconds, old.ros+seconds)
        return self.clock

    def quiet(self, count=9):
        for _ in range(count):
            self.controller.observe_truth(self.clock.ros, 0., 0., self.clock)
            self.controller.tick(self.clock)
            self.advance(.1)

    def envelope(self, *, sequence=0, ttl_ms=1000, **extra):
        return {'session_id': self.session, 'runtime_instance_id': self.instance, 'map_id': 'map-a',
                'profile_id': 'passage_manual', 'sequence': sequence,
                'issued_at_ms': self.clock.wall_ms, 'ttl_ms': ttl_ms, **extra}

    def acquire(self):
        body = self.envelope(lease_id=uid(), gesture='press')
        result = self.controller.acquire(body, self.clock)
        self.lease_id = body['lease_id']
        return result

    def ready(self):
        self.acquire()
        self.ports.resets[-1].set_result(SimpleNamespace(success=True))
        self.controller.tick(self.clock)

    def command(self, sequence=1, **patch):
        body = self.envelope(sequence=sequence, ttl_ms=250, lease_id=self.lease_id,
                             linear_x=.05, angular_z=0.)
        body.update(patch)
        return self.controller.command(body, self.clock)

    def stop(self, **patch):
        sequence = self.controller.control_sequences.get((self.session, 'stop'), -1)+1
        body = self.envelope(sequence=sequence, request_id=uid(), target_id=None)
        body.update(patch)
        return body, self.controller.stop(body, self.clock)

    def stopped(self):
        body, _ = self.stop()
        self.ports.stops[-1].set_result(SimpleNamespace(success=True))
        self.quiet()
        self.controller.tick(self.clock)
        return body

    def assert_rejected(self, code, function):
        with self.assertRaises(ManualError) as caught:
            function()
        self.assertEqual(caught.exception.code, code)
        self.assertFalse(caught.exception.response()['accepted'])


class LeaseAdmissionTests(ManualFixture):
    def test_acquire_only_arms_zero_and_requires_later_fresh_command(self):
        result = self.acquire()
        self.assertEqual(result['lease']['state'], 'arming')
        self.assertTrue(all(v == w == 0 for v, w, _ in self.ports.messages))
        self.assert_rejected('manual_lease_not_ready', self.command)
        self.ports.resets[-1].set_result(SimpleNamespace(success=True))
        self.controller.tick(self.clock)
        self.assertEqual(self.controller.lease_record(self.lease_id, self.clock)['state'], 'ready')
        self.command()
        self.assertEqual(self.ports.messages[-1][:2], (.05, 0.))

    def test_tick_does_not_repeat_nonzero_or_extend_deadline(self):
        self.ready()
        result = self.command()
        deadline = result['lease']['expires_at_ms']
        for _ in range(4):
            self.advance(.04)
            self.controller.tick(self.clock)
        self.assertEqual(sum(v != 0 or w != 0 for v, w, _ in self.ports.messages), 1)
        self.assertEqual(self.controller.lease_record(self.lease_id, self.clock)['expires_at_ms'], deadline)

    def test_consumed_source_age_is_subtracted_from_stamp_and_steady_deadline(self):
        self.ready()
        self.advance(.21)
        result = self.command(issued_at_ms=self.clock.wall_ms-200)
        self.assertAlmostEqual(self.ports.messages[-1][2], self.clock.ros-.2)
        self.assertLessEqual(result['lease']['remaining_ms'], 50)
        self.advance(.051)
        self.controller.tick(self.clock)
        self.assertEqual(self.controller.lease_record(self.lease_id, self.clock)['state'], 'expired')
        self.assertEqual(self.ports.messages[-1][:2], (0., 0.))
        self.assertEqual(len(self.ports.stops), 1)

    def test_expiry_uses_steady_time_when_wall_and_ros_clocks_pause(self):
        self.ready()
        self.command()
        self.clock = TimePoint(self.clock.wall_ms, self.clock.steady+.251, self.clock.ros)
        self.controller.tick(self.clock)
        self.assertEqual(self.controller.current_lease['state'], 'expired')
        self.assert_rejected('manual_lease_expired', lambda: self.command(sequence=2))

    def test_expired_lease_is_not_revived_by_new_sequence_or_lookup(self):
        self.ready()
        self.command()
        self.advance(.26)
        self.controller.tick(self.clock)
        for _ in range(3):
            self.controller.lease_record(self.lease_id, self.clock)
        self.assert_rejected('manual_lease_expired', lambda: self.command(sequence=200))
        self.assertEqual(sum(v != 0 for v, _, _ in self.ports.messages), 1)

    def test_old_or_duplicate_sequence_never_republishes(self):
        self.ready()
        self.command(sequence=4)
        before = sum(v != 0 for v, _, _ in self.ports.messages)
        for seq in (0, 1, 4):
            self.assert_rejected('stale_sequence', lambda: self.command(sequence=seq))
        self.assertEqual(sum(v != 0 for v, _, _ in self.ports.messages), before)

    def test_cross_session_instance_map_and_profile_are_rejected(self):
        self.ready()
        for patch, code in [({'session_id': uid()}, 'manual_lease_owner_mismatch'),
            ({'runtime_instance_id': uid()}, 'runtime_changed'), ({'map_id': 'map-b'}, 'task_map_mismatch'),
            ({'profile_id': 'baseline'}, 'manual_profile_mismatch')]:
            self.assert_rejected(code, lambda: self.command(**patch))
        self.assertFalse(any(v != 0 for v, _, _ in self.ports.messages))

    def test_source_expiry_future_and_invalid_types_never_execute(self):
        self.ready()
        for patch, code in [({'issued_at_ms': self.clock.wall_ms-250}, 'manual_request_expired'),
                ({'issued_at_ms': self.clock.wall_ms+51}, 'manual_request_expired'),
                ({'sequence': True}, 'invalid_sequence'), ({'ttl_ms': 251}, 'invalid_ttl_ms'),
                ({'linear_x': float('nan')}, 'manual_speed_out_of_range'),
                ({'angular_z': True}, 'manual_speed_out_of_range'),
                ({'linear_x': -.031}, 'manual_speed_out_of_range'),
                ({'angular_z': .251}, 'manual_speed_out_of_range')]:
            self.assert_rejected(code, lambda: self.command(**patch))

    def test_negative_and_turn_commands_remain_inside_existing_limits(self):
        self.ready()
        for sequence, (v, w) in enumerate(((-.03, 0.), (0., .25), (0., -.25)), 1):
            self.command(sequence=sequence, linear_x=v, angular_z=w)
            self.assertEqual(self.ports.messages[-1][:2], (v, w))

    def test_second_press_cannot_steal_lease_and_uuid_cannot_be_reused(self):
        first = self.acquire()
        self.assert_rejected('manual_lease_busy', self.acquire)
        body = self.envelope(lease_id=first['lease']['lease_id'], gesture='press')
        self.assert_rejected('lease_id_already_used', lambda: self.controller.acquire(body, self.clock))

    def test_native_active_canceling_and_unknown_all_block_acquire(self):
        for status in ('running', 'canceling', 'unknown', 'succeeded'):
            self.ports.native = {'task_id': uid(), 'status': status, 'native_status': None}
            self.assert_rejected('native_owner_unresolved', self.acquire)
        self.assertFalse(self.ports.resets)

    def test_native_terminal_still_needs_new_continuous_quiet(self):
        task = uid()
        self.ports.native = {'task_id': task, 'status': 'canceling', 'native_status': None}
        self.controller.tick(self.clock)
        self.ports.native.update(status='canceled', native_status=5)
        self.assert_rejected('continuous_quiet_unconfirmed', self.acquire)
        self.quiet()
        self.assertEqual(self.acquire()['lease']['state'], 'arming')

    def test_disabled_profile_and_missing_guard_fail_closed(self):
        self.controller.enabled = False
        self.assert_rejected('manual_profile_not_enabled', self.acquire)
        self.controller.enabled = True
        self.ports.available = False
        self.assert_rejected('guard_unavailable', self.acquire)

    def test_new_press_after_release_requires_actual_cleanup_and_fresh_quiet(self):
        self.ready()
        release = self.envelope(lease_id=self.lease_id, sequence=1)
        self.controller.release(release, self.clock)
        self.assert_rejected('manual_cleanup_unconfirmed', self.acquire)
        self.ports.stops[-1].set_result(SimpleNamespace(success=True))
        self.controller.tick(self.clock)
        self.assert_rejected('continuous_quiet_unconfirmed', self.acquire)
        self.quiet()
        self.ports.resets[-1].set_result(SimpleNamespace(success=True))
        self.controller.tick(self.clock)
        self.assertEqual(self.acquire()['lease']['state'], 'arming')

    def test_normal_cleanup_resets_only_zero_gate_then_native_handoff_needs_no_extra_stop(self):
        self.ready()
        self.controller.release(self.envelope(lease_id=self.lease_id, sequence=1), self.clock)
        self.ports.stops[-1].set_result(SimpleNamespace(success=True))
        self.quiet()
        self.assert_rejected('manual_cleanup_unconfirmed', lambda: self.controller.require_native_admission(self.clock))
        self.assertEqual(len(self.ports.resets), 2)
        self.assertTrue(self.ports.locks[-1])
        self.assertTrue(all(v == w == 0 for v, w, _ in self.ports.messages))
        self.ports.resets[-1].set_result(SimpleNamespace(success=True))
        self.controller.tick(self.clock)
        self.controller.require_native_admission(self.clock)
        self.assertEqual(self.controller.current_lease['state'], 'released')
        self.assertFalse(self.controller.stop_latched)

    def test_cleanup_reset_cannot_clear_later_explicit_stop_or_replay_any_motion(self):
        self.ready()
        self.controller.release(self.envelope(lease_id=self.lease_id, sequence=1), self.clock)
        self.ports.stops[-1].set_result(SimpleNamespace(success=True))
        self.quiet()
        cleanup_reset = self.ports.resets[-1]
        body, _ = self.stop()
        count = len(self.ports.stops)
        cleanup_reset.set_result(SimpleNamespace(success=True))
        self.controller.tick(self.clock)
        self.assertTrue(self.controller.stop_latched)
        self.assertEqual(self.controller.current_stop['request_id'], body['request_id'])
        self.assertGreater(len(self.ports.stops), count)
        self.assertTrue(all(v == w == 0 for v, w, _ in self.ports.messages))

    def test_hard_guard_fault_blocks_automatic_cleanup_reset(self):
        self.ready()
        self.controller.release(self.envelope(lease_id=self.lease_id, sequence=1), self.clock)
        self.ports.stops[-1].set_result(SimpleNamespace(success=True))
        self.ports.available = False
        self.quiet()
        self.assertEqual(len(self.ports.resets), 1)
        self.assertTrue(self.controller.guard_reset_needed)

    def test_delayed_command_sent_before_ready_is_never_replayed_after_reset(self):
        self.acquire()
        issued = self.clock.wall_ms
        self.advance(.1)
        self.ports.resets[-1].set_result(SimpleNamespace(success=True))
        self.controller.tick(self.clock)
        self.assert_rejected('command_predates_ready', lambda: self.command(issued_at_ms=issued))
        self.assertFalse(any(v != 0 for v, _, _ in self.ports.messages))

    def test_publication_failure_still_attempts_guard_stop_and_returns_unknown_evidence(self):
        self.ready()
        publish = self.ports.publish_manual
        def failing(v, w, stamp):
            if v or w:
                raise RuntimeError('DDS unavailable')
            publish(v, w, stamp)
        self.ports.publish_manual = failing
        with self.assertRaises(ManualError) as caught:
            self.command()
        self.assertEqual(caught.exception.code, 'manual_publish_unknown')
        self.assertIsNone(caught.exception.response()['accepted'])
        self.assertEqual(self.controller.current_lease['state'], 'unknown')
        self.assertEqual(len(self.ports.stops), 1)

    def test_native_dispatch_cannot_bypass_existing_live_manual_owner(self):
        self.ready()
        self.assert_rejected('manual_owner_not_released', lambda: self.controller.native_started(uid()))

    def test_map_change_revokes_lease_without_losing_original_receipt_or_ids(self):
        self.ready()
        self.command()
        original_id = self.lease_id
        self.controller.bind_map('map-b', self.clock)
        record = self.controller.lease_record(original_id, self.clock)
        self.assertEqual(record['map_id'], 'map-a')
        self.assertEqual(record['state'], 'unknown')
        self.assertEqual(self.controller.map_id, 'map-b')
        self.assert_rejected('task_map_mismatch', self.command)
        self.assertTrue(self.ports.locks[-1])
        self.assertEqual(self.ports.messages[-1][:2], (0., 0.))

    def test_unbound_map_status_is_unavailable_until_actual_owner_binds_it(self):
        controller = ManualLeaseController(self.instance, None, self.ports, enabled=True)
        adapter = ManualHTTPAdapter(controller)
        self.assertEqual(adapter.get('/sim-api/manual/status', self.clock),
                         (503, {'accepted': False, 'outcome': 'rejected', 'error': 'manual_map_unavailable'}))
        controller.bind_map('map-a', self.clock)
        self.assertEqual(adapter.get('/sim-api/manual/status', self.clock)[1]['map_id'], 'map-a')
        self.assertFalse(controller.status(self.clock)['can_acquire'])

    def test_owner_shutdown_revokes_held_motion_and_attempts_guard_before_teardown(self):
        self.ready()
        self.command()
        self.controller.shutdown(self.clock)
        self.assertEqual(self.controller.current_lease['state'], 'released')
        self.assertEqual(self.controller.current_lease['reason'], 'owner_shutdown')
        self.assertEqual(self.ports.messages[-1][:2], (0., 0.))
        self.assertEqual(len(self.ports.stops), 1)


class StopAndLateReplyTests(ManualFixture):
    def test_native_stop_uses_original_id_and_cancel_ack_is_not_terminal_or_quiet(self):
        task = uid()
        self.ports.native = {'task_id': task, 'status': 'running', 'native_goal_id': uid(),
                             'native_status': None, 'cancel_acknowledged': False}
        body, result = self.stop(target_id=task)
        self.assertEqual(self.ports.cancels, [task])
        self.assertEqual(result['stop']['target_kind'], 'mission')
        self.ports.stops[-1].set_result(SimpleNamespace(success=True))
        self.ports.native.update(status='canceling', cancel_acknowledged=True)
        self.quiet()
        self.assertNotEqual(self.controller.stop_record(body['request_id'], self.clock)['state'], 'stopped')
        self.ports.native.update(status='canceled', native_status=5)
        self.quiet()
        self.controller.tick(self.clock)
        record = self.controller.stop_record(body['request_id'], self.clock)
        self.assertEqual(record['state'], 'stopped')
        self.assertEqual(record['native_status'], 5)

    def test_mismatched_original_stop_does_not_cancel_or_latch_new_action(self):
        self.ports.native = {'task_id': uid(), 'status': 'running', 'native_status': None}
        self.assert_rejected('stop_target_changed', lambda: self.stop(target_id=uid()))
        self.assertFalse(self.ports.cancels)
        self.assertFalse(self.ports.stops)
        self.assertFalse(self.controller.stop_latched)

    def test_repeated_stop_id_reads_original_without_canceling_new_task(self):
        body = self.stopped()
        self.ports.native = {'task_id': uid(), 'status': 'running', 'native_status': None}
        count = len(self.ports.stops)
        again = self.controller.stop(body, self.clock)
        self.assertIsNone(again['stop']['target_id'])
        self.assertEqual(len(self.ports.stops), count)
        self.assertFalse(self.ports.cancels)

    def test_late_acquire_reset_after_release_reasserts_stop_and_never_readies_lease(self):
        self.acquire()
        original_reset = self.ports.resets[-1]
        release = self.envelope(lease_id=self.lease_id, sequence=1)
        self.controller.release(release, self.clock)
        self.ports.stops[-1].set_result(SimpleNamespace(success=True))
        self.controller.tick(self.clock)
        original_reset.set_result(SimpleNamespace(success=True))
        self.controller.tick(self.clock)
        self.assertEqual(self.controller.current_lease['state'], 'released')
        self.assertEqual(len(self.ports.stops), 2)
        self.assertFalse(self.controller.status(self.clock)['can_acquire'])

    def test_explicit_reset_only_clears_bound_stop_and_creates_no_lease(self):
        body = self.stopped()
        reset = self.envelope(request_id=uid(), stop_request_id=body['request_id'], gesture='reset')
        result = self.controller.reset(reset, self.clock)
        self.assertEqual(result['reset']['state'], 'resetting')
        self.ports.resets[-1].set_result(SimpleNamespace(success=True))
        self.controller.tick(self.clock)
        self.assertFalse(self.controller.stop_latched)
        self.assertFalse(self.controller.leases)
        self.assertTrue(all(v == w == 0 for v, w, _ in self.ports.messages))

    def test_old_reset_reply_cannot_clear_later_stop(self):
        first = self.stopped()
        reset = self.envelope(request_id=uid(), stop_request_id=first['request_id'], gesture='reset')
        self.controller.reset(reset, self.clock)
        old_future = self.ports.resets[-1]
        second, _ = self.stop()
        old_future.set_result(SimpleNamespace(success=True))
        self.controller.tick(self.clock)
        self.assertTrue(self.controller.stop_latched)
        self.assertEqual(self.controller.current_stop['request_id'], second['request_id'])
        self.assertEqual(self.controller.reset_record(reset['request_id'])['state'], 'unknown')
        self.assertGreaterEqual(len(self.ports.stops), 3)

    def test_guard_timeout_remains_unknown_and_never_retries_reset(self):
        self.acquire()
        self.advance(1.01)
        self.controller.tick(self.clock)
        self.assertEqual(self.controller.current_lease['state'], 'unknown')
        self.quiet()
        self.assertEqual(len(self.ports.resets), 1)
        self.assertFalse(self.controller.status(self.clock)['can_acquire'])

    def test_timed_out_old_reset_reasserts_current_stop_when_real_reply_arrives(self):
        self.acquire()
        late = self.ports.resets[-1]
        self.advance(1.01)
        self.controller.tick(self.clock)
        body, _ = self.stop()
        count = len(self.ports.stops)
        late.set_result(SimpleNamespace(success=True))
        self.controller.tick(self.clock)
        self.assertTrue(self.controller.stop_latched)
        self.assertEqual(self.controller.current_stop['request_id'], body['request_id'])
        self.assertGreater(len(self.ports.stops), count)

    def test_historical_stop_retains_its_own_quiet_evidence(self):
        body = self.stopped()
        before = self.controller.stop_record(body['request_id'], self.clock)
        self.controller.observe_truth(self.clock.ros, .05, 0., self.clock)
        self.assertEqual(self.controller.stop_record(body['request_id'], self.clock)['quiet'], before['quiet'])
        self.assertFalse(any(key.startswith('_') for key in before))

    def test_idle_stop_terminal_means_no_hanging_native_action(self):
        body = self.stopped()
        record = self.controller.stop_record(body['request_id'], self.clock)
        self.assertIs(record['native_terminal'], True)
        self.assertIs(record['guard_stop_acknowledged'], True)
        self.assertIs(record['quiet']['confirmed'], True)

    def test_reset_cannot_clear_stop_without_actual_new_quiet_and_guard_reply(self):
        body, _ = self.stop()
        reset = self.envelope(request_id=uid(), stop_request_id=body['request_id'], gesture='reset')
        self.assert_rejected('stop_cleanup_unconfirmed', lambda: self.controller.reset(reset, self.clock))
        self.assertFalse(self.ports.resets)

    def test_http_contract_has_original_lookup_and_cannot_mutate_through_get(self):
        api = ManualHTTPAdapter(self.controller)
        body = self.envelope(lease_id=uid(), gesture='press')
        status, result = api.post('/sim-api/manual/acquire', body, self.clock)
        self.assertEqual(status, 202)
        self.assertIs(result['accepted'], True)
        deadline = self.controller.current_lease['_deadline']
        self.advance(.1)
        status, read = api.get('/sim-api/manual/'+body['lease_id'], self.clock)
        self.assertEqual(status, 200)
        self.assertEqual(read['lease']['lease_id'], body['lease_id'])
        self.assertEqual(self.controller.current_lease['_deadline'], deadline)
        self.assertEqual(api.get('/sim-api/manual/'+uid(), self.clock)[0], 404)
        self.assertEqual(api.get('/sim-api/manual/not-a-uuid', self.clock)[0], 400)
        status, status_body = api.get('/sim-api/manual/status', self.clock)
        self.assertEqual(status_body['map_id'], 'map-a')
        self.assertTrue(status_body['can_stop'])

    def test_reordered_stop_cannot_bind_new_owner_even_with_new_request_uuid(self):
        self.stop(sequence=4)
        count = len(self.ports.stops)
        self.assert_rejected('stale_sequence', lambda: self.stop(sequence=3))
        self.assertEqual(len(self.ports.stops), count)

    def test_completed_stop_is_immutable_when_later_native_task_starts(self):
        body = self.stopped()
        reset = self.envelope(request_id=uid(), stop_request_id=body['request_id'], gesture='reset')
        self.controller.reset(reset, self.clock)
        self.ports.resets[-1].set_result(SimpleNamespace(success=True))
        self.controller.tick(self.clock)
        original = self.controller.stop_record(body['request_id'], self.clock)
        self.ports.native = {'task_id': uid(), 'status': 'running', 'native_status': None}
        self.controller.tick(self.clock)
        self.assertEqual(self.controller.stop_record(body['request_id'], self.clock), original)

    def test_only_explicit_native_dispatch_unlocks_nav_and_idle_never_falls_back(self):
        task = uid()
        self.ports.native = {'task_id': task, 'status': 'running', 'native_status': None}
        self.controller.tick(self.clock)
        self.assertTrue(self.ports.locks[-1])
        self.controller.native_started(task)
        self.controller.tick(self.clock)
        self.assertFalse(self.ports.locks[-1])
        self.ports.native.update(status='canceled', native_status=5)
        self.controller.tick(self.clock)
        self.assertTrue(self.ports.locks[-1])

    def test_legacy_native_compact_uuid_remains_the_original_owner_identity(self):
        task = uuid.uuid4().hex
        self.ports.native = {'task_id': task, 'status': 'running', 'native_status': None}
        self.controller.native_started(task)
        self.controller.tick(self.clock)
        self.assertFalse(self.ports.locks[-1])
        body, result = self.stop(target_id=task)
        self.assertEqual(result['stop']['target_id'], task)
        self.assertEqual(self.ports.cancels, [task])


class IdleRecoveryTests(ManualFixture):
    def fault(self, *, token='trigger-a', eligible=True):
        self.ports.available = False
        self.ports.fault = {'trigger_id': token, 'reason': 'odom: receive timeout',
                            'steady_time': self.clock.steady, 'eligible': eligible}
        self.controller.tick(self.clock)

    def test_idle_reset_is_once_per_incident_zero_only_and_ack_fenced(self):
        self.fault()
        self.assertEqual(len(self.ports.resets), 1)
        self.assertEqual(self.controller.status(self.clock)['idle_recovery']['state'], 'resetting')
        self.assertFalse(self.controller.status(self.clock)['can_acquire'])
        self.assert_rejected('manual_cleanup_unconfirmed', lambda: self.controller.require_native_admission(self.clock))
        self.ports.resets[0].set_result(SimpleNamespace(success=True))
        self.ports.available, self.ports.fault = True, None
        self.controller.tick(self.clock)
        self.assertEqual(self.controller.idle_recovery['state'], 'ready')
        self.assertTrue(self.controller.status(self.clock)['can_acquire'])
        self.controller.require_native_admission(self.clock)
        self.assertIsNone(self.controller.current_lease)
        self.assertEqual(self.ports.cancels, [])
        self.assertTrue(all(v == w == 0 for v, w, _ in self.ports.messages))
        self.assertTrue(all(self.ports.locks))
        self.fault()
        self.assertEqual(len(self.ports.resets), 1)

    def test_old_trigger_path_cannot_impersonate_new_latch_after_reset_ack(self):
        self.fault()
        old = copy.deepcopy(self.ports.fault)
        self.ports.resets[0].set_result(SimpleNamespace(success=True))
        self.advance(.01)
        self.controller.tick(self.clock)
        self.ports.fault = {**old, 'trigger_id': 'writer-still-reporting-older-path'}
        self.controller.tick(self.clock)
        self.assertEqual(len(self.ports.resets), 1)

    def test_new_stop_wins_over_late_idle_reset_and_is_reasserted(self):
        self.fault()
        body, _ = self.stop()
        reset = self.ports.resets[0]
        self.quiet()
        reset.set_result(SimpleNamespace(success=True))
        self.controller.tick(self.clock)
        self.assertTrue(self.controller.stop_latched)
        self.assertEqual(self.controller.current_stop['request_id'], body['request_id'])
        self.assertEqual(self.controller.idle_recovery['state'], 'unknown')
        self.assertEqual(len(self.ports.stops), 2)
        self.assertTrue(self.ports.locks[-1])

    def test_new_native_owner_or_map_cannot_be_cleared_by_old_reset(self):
        for change in ('native', 'map'):
            with self.subTest(change=change):
                self.setUp()
                self.fault()
                if change == 'native':
                    self.ports.native = {'task_id': uid(), 'status': 'running', 'native_status': None}
                    self.controller.native_authority = self.ports.native['task_id']
                else:
                    self.controller.bind_map('map-b', self.advance(.01))
                self.ports.resets[0].set_result(SimpleNamespace(success=True))
                self.controller.tick(self.clock)
                self.assertEqual(self.controller.idle_recovery['state'], 'unknown')
                self.assertEqual(len(self.ports.stops), 1)
                self.assertTrue(self.ports.locks[-1])

    def test_late_success_after_timeout_does_not_unlock_or_retry(self):
        self.fault()
        self.advance(1.1)
        self.controller.tick(self.clock)
        self.assertEqual(self.controller.idle_recovery['state'], 'unknown')
        self.quiet()
        self.ports.resets[0].set_result(SimpleNamespace(success=True))
        self.controller.tick(self.clock)
        self.assertEqual(self.controller.idle_recovery['state'], 'unknown')
        self.assertFalse(self.controller.status(self.clock)['can_acquire'])
        self.assertEqual(len(self.ports.resets), 1)
        self.assertEqual(len(self.ports.stops), 1)

    def test_hard_or_later_fault_is_not_eligible(self):
        self.fault(eligible=False)
        self.assertEqual(self.ports.resets, [])
        self.fault()
        self.ports.fault = {'trigger_id': 'ownership-incident', 'eligible': False}
        self.ports.resets[0].set_result(SimpleNamespace(success=True))
        self.controller.tick(self.clock)
        self.assertEqual(self.controller.idle_recovery['state'], 'unknown')
        self.assertEqual(len(self.ports.stops), 1)

    def test_active_unknown_unresolved_or_stale_quiet_never_resets(self):
        for state in ('running', 'unknown', 'unresolved', 'quiet_stale', 'lease_unknown'):
            with self.subTest(state=state):
                self.setUp()
                if state == 'quiet_stale': self.advance(.4)
                elif state == 'lease_unknown':
                    self.controller.current_lease = {'state': 'unknown', 'lease_id': uid()}
                else:
                    self.ports.native = {'task_id': uid(), 'status': 'succeeded' if state == 'unresolved' else state,
                        'native_status': 4, 'cleanup_state': 'unresolved' if state == 'unresolved' else None}
                self.fault()
                self.assertEqual(self.ports.resets, [])

    def test_same_native_uuid_retires_only_after_terminal_and_fresh_quiet(self):
        task = uid()
        self.ports.native = {'task_id': task, 'status': 'running', 'native_status': None}
        self.controller.native_started(task)
        self.ports.native.update(status='succeeded', native_status=4)
        self.controller.tick(self.clock)
        self.assertEqual(self.controller.native_authority, task)
        self.quiet()
        self.assertIsNone(self.controller.native_authority)
        self.fault()
        self.assertEqual(len(self.ports.resets), 1)
        self.assertEqual(self.controller.idle_recovery['native_task_id'], task)

    def test_trigger_evidence_requires_stationary_zero_commands_and_exact_graph(self):
        zero = {'error': None, 'data': {'twist': [0.] * 6}}
        evidence = {'schema_version': 1, 'profile': 'fishbot_passage', 'reason': 'odom: receive timeout',
            'kind': 'health_stop', 'motion_active': False, 'hold_motion': False, 'steady_time': 100.,
            'geometry': {'command_guard': {'timing_profile': 'strict',
                'expected_final_subscribers': ['diff_drive_controller', 'fishbot_mission_bridge']}},
            'graph': {'candidate_publishers': ['collision_monitor'], 'final_publishers': ['fishbot_command_guard'],
                'final_subscribers': ['diff_drive_controller', 'fishbot_mission_bridge']},
            'latest': {'command': zero, 'desired_command': copy.deepcopy(zero),
                'scan': {'error': None, 'tf_issue': None},
                'odom': {'error': None, 'data': {'linear': [0., 0., 0.], 'angular': [0., 0., 0.]}}}}
        self.assertTrue(idle_timing_evidence(evidence, evidence['reason']))
        for change in ('nonzero', 'moving', 'graph', 'malformed', 'tf', 'hidden_tf', 'hidden_cm'):
            altered = copy.deepcopy(evidence)
            if change == 'nonzero': altered['latest']['desired_command']['data']['twist'][0] = .01
            elif change == 'moving': altered['latest']['odom']['data']['linear'][0] = .005
            elif change == 'graph': altered['graph']['final_publishers'].append('rogue')
            elif change == 'malformed': altered['latest']['command']['error'] = 'bad stamp'
            elif change == 'hidden_tf': altered['latest']['scan']['tf_issue'] = 'scan TF unavailable'
            elif change == 'hidden_cm': altered['latest']['collision_state'] = {
                'error': None, 'data': {'action_type': 1, 'polygon_name': 'invalid source'}}
            else: altered['reason'] = 'scan: TF unavailable'
            self.assertFalse(idle_timing_evidence(altered, altered['reason']))


    def test_real_strict_guard_zero_expiry_retains_required_ring_evidence(self):
        from tools.tests.test_command_guard import guard_module, config, sensors, command
        document = config()
        document['command_guard'].update(profile='fishbot_passage', ring_capacity=40,
            expected_final_subscribers=['diff_drive_controller', 'fishbot_mission_bridge'])
        core = guard_module.CommandGuard(guard_module.Settings.from_mapping(document))
        def fresh(ros, steady):
            sensors(core, ros, steady)
            core.set_ownership({'candidate_publishers': ['collision_monitor'],
                'final_publishers': ['fishbot_command_guard'],
                'final_subscribers': ['diff_drive_controller', 'fishbot_mission_bridge']}, None)
        fresh(100., 10.)
        command(core)
        core.accept_command([0.] * 6, 100., 100., 10., desired=True)
        core.tick(100., 10.)
        fresh(100.26, 10.26)
        core.tick(100.26, 10.26)
        self.assertNotIn('command', core.latest)
        core.accept_command([0.] * 6, 100.52, 100.52, 10.52, desired=True)
        core.tick(100.52, 10.52)
        incident = core.events[-1]
        self.assertEqual(incident['reason'], 'odom: receive timeout')
        self.assertNotIn('command', incident['latest'])
        self.assertTrue(idle_timing_evidence(incident, incident['reason']))
        for change in ('nonzero', 'error', 'no_candidate', 'malformed', 'nonfinite', 'too_large'):
            with self.subTest(change=change):
                altered = copy.deepcopy(incident)
                candidate = next(r for r in altered['ring'] if r['kind'] == 'command')
                if change == 'nonzero': candidate['data']['twist'][0] = .01
                elif change == 'error': candidate['error'] = 'source timestamp rejected'
                elif change == 'no_candidate': altered['ring'] = [r for r in altered['ring'] if r['kind'] != 'command']
                elif change == 'malformed': candidate['data']['twist'] = [0.] * 5
                elif change == 'nonfinite': candidate['data']['twist'][5] = float('nan')
                else: altered['ring'] = [candidate] * 41
                self.assertFalse(idle_timing_evidence(altered, altered['reason']))
        altered = copy.deepcopy(incident)
        next(r for r in altered['ring'] if r['kind'] == 'desired_command')['data']['twist'][5] = .01
        self.assertFalse(idle_timing_evidence(altered, altered['reason']))
        altered = copy.deepcopy(incident)
        altered.pop('ring')
        self.assertFalse(idle_timing_evidence(altered, altered['reason']))


class QuietEvidenceTests(unittest.TestCase):
    def test_duplicate_source_does_not_refresh_age_or_prove_stopped(self):
        gate = QuietEvidence()
        for i in range(10):
            gate.observe(10., 0., 0., TimePoint(1000+i*100, i*.1, 10.))
        self.assertFalse(gate.snapshot(TimePoint(2000, 1., 10.))['confirmed'])
        self.assertAlmostEqual(gate.snapshot(TimePoint(2000, 1., 10.))['receive_age_s'], 1.)

    def test_fast_sim_time_cannot_replace_wall_duration_and_gaps_restart_window(self):
        gate = QuietEvidence()
        for i in range(9):
            gate.observe(10+i*.1, 0., 0., TimePoint(1000+i*10, i*.01, 10+i*.1))
        self.assertFalse(gate.snapshot(TimePoint(1090, .09, 10.8))['confirmed'])
        gate.observe(11., 0., 0., TimePoint(2000, 1., 11.))
        self.assertEqual(gate.snapshot(TimePoint(2000, 1., 11.))['duration_s'], 0.)

    def test_nonzero_or_stale_source_invalidates_previously_quiet_window(self):
        gate = QuietEvidence()
        for i in range(9):
            gate.observe(10+i*.1, 0., 0., TimePoint(1000+i*100, i*.1, 10+i*.1))
        self.assertTrue(gate.snapshot(TimePoint(1800, .8, 10.8))['confirmed'])
        gate.observe(10.9, .005, 0., TimePoint(1900, .9, 10.9))
        self.assertFalse(gate.snapshot(TimePoint(1900, .9, 10.9))['confirmed'])
        gate.observe(11., 0., 0., TimePoint(2500, 1.5, 11.5))
        self.assertIsNone(gate.snapshot(TimePoint(2500, 1.5, 11.5))['source_stamp'])


if __name__ == '__main__':
    unittest.main()
