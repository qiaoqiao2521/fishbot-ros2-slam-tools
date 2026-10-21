"""Controlled parameter futures prove RPC ordering, not physical cargo stability."""
import copy
from types import SimpleNamespace as NS
import unittest

from cooperation_loaded_limits import (LoadedVelocityLimits, LoadedRppLimits,
                                       NAMES, VELOCITY_NAMES, RPP_NAMES, limits, rpp_limits)


ORIGINAL = {'max_accel': [2., 0., 3.], 'max_decel': [-2., 0., -3.]}
LOADED = {'max_accel': [.1, 0., .2], 'max_decel': [-.1, 0., -.2]}
ORIGINAL_VELOCITY = {'max_velocity': [.3, 0., 1.], 'min_velocity': [-.3, 0., -1.]}
LOADED_VELOCITY = {'max_velocity': [.05, 0., .1], 'min_velocity': [-.05, 0., -.1]}
ORIGINAL_RPP = dict(zip(RPP_NAMES, (.12, .05, .03, 1.)))
LOADED_RPP = dict(zip(RPP_NAMES, (.03, .02, .01, .05)))


class Future:
    def __init__(self, value, ready=True):
        self.value, self.ready = value, ready

    def done(self):
        return self.ready

    def result(self):
        return self.value


def wait(future):
    if not future.done():
        raise TimeoutError('controlled unacknowledged RPC')


class Client:
    def __init__(self):
        self.actual = copy.deepcopy(ORIGINAL)
        self.writes, self.reads, self.write_futures = [], [], []
        self.next_write = None
        self.mismatch = False

    def get_parameters(self, names):
        self.reads.append(list(names))
        return Future(NS(values=[NS(type=8, double_array_value=list(self.actual[key]))
            if isinstance(self.actual[key], list) else NS(type=3, double_value=self.actual[key]) for key in names]))

    def set_parameters_atomically(self, parameters):
        values = {parameter.name: copy.deepcopy(parameter.value) for parameter in parameters}
        self.writes.append(copy.deepcopy(values))
        self.actual.update(copy.deepcopy(values))
        if self.mismatch and values == LOADED:
            self.actual['max_accel'][0] = .2
        future = self.next_write or Future(NS(result=NS(successful=True, reason='')))
        self.next_write = None
        self.write_futures.append(future)
        return future


class LoadedLimitsTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.active = True
        self.lifecycle_calls = 0
        def query():
            self.lifecycle_calls += 1
            return Future(NS(current_state=NS(id=3 if self.active else 2)))
        self.adapter = LoadedVelocityLimits(LOADED, self.client, query,
                                           lambda name, value: NS(name=name, value=value))

    def test_apply_and_restore_read_actual_baseline_and_send_each_write_once(self):
        self.adapter.apply(wait)
        self.assertEqual(self.adapter.baseline, ORIGINAL)
        self.assertEqual(self.client.actual, LOADED)
        self.assertEqual(self.adapter.snapshot()['phase'], 'applied')
        first_ack = self.adapter.snapshot()['requests']['apply']['received_monotonic']
        self.adapter.apply(wait)
        self.adapter.restore(wait)
        self.adapter.restore(wait)
        self.assertEqual(self.client.writes, [LOADED, ORIGINAL])
        self.assertEqual(self.client.actual, ORIGINAL)
        self.assertEqual(self.lifecycle_calls, 2)
        self.assertFalse(self.adapter.snapshot()['restoration_required'])
        self.assertEqual(self.adapter.snapshot()['phase'], 'restored')
        self.assertEqual(self.adapter.snapshot()['requests']['apply']['received_monotonic'], first_ack)
        self.assertNotIn('future', str(self.adapter.snapshot()))

    def test_inactive_smoother_never_receives_limits(self):
        self.active = False
        with self.assertRaisesRegex(RuntimeError, 'active'):
            self.adapter.apply(wait)
        self.adapter.restore(wait)
        self.assertEqual(self.client.writes, [])
        self.assertEqual(self.client.reads, [])

    def test_pending_apply_is_reconciled_before_restore_without_replay(self):
        pending = Future(NS(result=NS(successful=True, reason='')), ready=False)
        self.client.next_write = pending
        with self.assertRaises(TimeoutError):
            self.adapter.apply(wait)
        with self.assertRaises(TimeoutError):
            self.adapter.restore(wait)
        self.assertEqual(self.client.writes, [LOADED])
        self.assertTrue(self.adapter.dirty)
        pending.ready = True
        self.adapter.restore(wait)
        self.assertEqual(self.client.writes, [LOADED, ORIGINAL])
        self.assertFalse(self.adapter.dirty)

    def test_pending_restore_is_never_sent_twice(self):
        self.adapter.apply(wait)
        pending = Future(NS(result=NS(successful=True, reason='')), ready=False)
        self.client.next_write = pending
        with self.assertRaises(TimeoutError):
            self.adapter.restore(wait)
        self.assertTrue(self.adapter.dirty)
        pending.ready = True
        self.adapter.restore(wait)
        self.assertEqual(self.client.writes, [LOADED, ORIGINAL])
        self.assertEqual(self.adapter.phase, 'restored')

    def test_rejected_apply_still_restores_possible_native_callback_side_effect(self):
        self.client.next_write = Future(NS(result=NS(successful=False, reason='native rejection')))
        with self.assertRaisesRegex(RuntimeError, 'native rejection'):
            self.adapter.apply(wait)
        self.adapter.restore(wait)
        self.assertEqual(self.client.writes, [LOADED, ORIGINAL])
        self.assertEqual(self.client.actual, ORIGINAL)

    def test_readback_mismatch_fails_apply_and_original_can_be_restored(self):
        self.client.mismatch = True
        with self.assertRaisesRegex(RuntimeError, '回读'):
            self.adapter.apply(wait)
        self.adapter.restore(wait)
        self.assertEqual(self.client.actual, ORIGINAL)

    def test_restore_rejection_is_unconfirmed_and_not_retried(self):
        self.adapter.apply(wait)
        self.client.next_write = Future(NS(result=NS(successful=False, reason='restore rejected')))
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, 'restore rejected'):
                self.adapter.restore(wait)
        self.assertEqual(self.client.writes, [LOADED, ORIGINAL])
        self.assertTrue(self.adapter.dirty)
        self.assertEqual(self.adapter.phase, 'restore_unconfirmed')

    def test_inactive_restore_does_not_claim_internal_limits_restored(self):
        self.adapter.apply(wait)
        self.active = False
        with self.assertRaisesRegex(RuntimeError, 'active'):
            self.adapter.restore(wait)
        self.assertEqual(self.client.writes, [LOADED])
        self.assertTrue(self.adapter.dirty)

    def test_new_task_has_new_baseline_and_no_copied_rpc(self):
        self.adapter.apply(wait)
        self.adapter.restore(wait)
        fresh = self.adapter.new_task()
        self.assertEqual(fresh.requests, {})
        self.assertIsNone(fresh.baseline)
        self.assertFalse(fresh.dirty)
        self.assertEqual(fresh.desired, LOADED)

    def test_invalid_limits_never_create_a_parameter_request(self):
        for key, value in [('max_accel', [-.1, 0., .2]), ('max_decel', [.1, 0., -.2]),
                           ('max_accel', [True, 0., .2]), ('max_accel', [float('nan'), 0., .2]),
                           ('max_decel', [-.1, 0.]), ('max_decel', None)]:
            with self.subTest(key=key, value=value):
                config = copy.deepcopy(LOADED); config[key] = value
                with self.assertRaises(ValueError):
                    limits(config)
        self.assertEqual(self.client.writes, [])

    def test_optional_human_note_warns_and_keeps_actual_control_values(self):
        config={**copy.deepcopy(LOADED),'note':'human-editable simulation assumption'}
        with self.assertWarnsRegex(RuntimeWarning,'note'):
            self.assertEqual(limits(config),LOADED)
        self.assertEqual(config['note'],'human-editable simulation assumption')
        self.assertEqual(self.client.writes,[])

    def velocity_adapter(self):
        self.client.actual.update(copy.deepcopy(ORIGINAL_VELOCITY))
        desired = {**copy.deepcopy(LOADED), **copy.deepcopy(LOADED_VELOCITY)}
        return LoadedVelocityLimits(desired, self.client, self.adapter.lifecycle_query,
                                    lambda name, value: NS(name=name, value=value))

    def test_optional_velocity_bounds_read_apply_and_restore_actual_four_parameter_baseline(self):
        adapter = self.velocity_adapter()
        baseline = {**copy.deepcopy(ORIGINAL), **copy.deepcopy(ORIGINAL_VELOCITY)}
        # The actual service baseline, rather than a static default, owns restore.
        self.client.actual['max_velocity'][0] = .27
        baseline['max_velocity'][0] = .27
        adapter.apply(wait)
        desired = {**LOADED, **LOADED_VELOCITY}
        self.assertEqual(adapter.baseline, baseline)
        self.assertEqual(self.client.actual, desired)
        self.assertEqual(adapter.names, NAMES + VELOCITY_NAMES)
        adapter.restore(wait)
        self.assertEqual(self.client.actual, baseline)
        self.assertEqual(self.client.writes, [desired, baseline])
        self.assertEqual(self.client.reads, [list(NAMES + VELOCITY_NAMES)]*3)
        self.assertEqual(list(adapter.requests), ['active_apply', 'baseline', 'apply',
            'readback_apply', 'active_restore', 'restore', 'readback_restore'])
        fresh = adapter.new_task()
        self.assertEqual(fresh.names, NAMES + VELOCITY_NAMES)
        self.assertEqual(fresh.desired, desired)
        self.assertEqual(fresh.requests, {})

    def test_legacy_two_parameter_path_leaves_undeclared_native_velocity_bounds_untouched(self):
        self.client.actual.update(copy.deepcopy(ORIGINAL_VELOCITY))
        self.adapter.apply(wait)
        self.assertEqual({key: self.client.actual[key] for key in VELOCITY_NAMES}, ORIGINAL_VELOCITY)
        self.adapter.restore(wait)
        self.assertEqual(self.client.reads, [list(NAMES)]*3)
        self.assertEqual(self.client.writes, [LOADED, ORIGINAL])
        self.assertEqual(list(self.adapter.requests), ['active_apply', 'baseline', 'apply',
            'readback_apply', 'active_restore', 'restore', 'readback_restore'])

    def test_optional_velocity_pending_apply_and_restore_reconcile_original_futures_without_replay(self):
        adapter = self.velocity_adapter()
        pending = Future(NS(result=NS(successful=True, reason='')), ready=False)
        self.client.next_write = pending
        with self.assertRaises(TimeoutError): adapter.apply(wait)
        with self.assertRaises(TimeoutError): adapter.restore(wait)
        self.assertEqual(len(self.client.writes), 1)
        pending.ready = True
        restoring = Future(NS(result=NS(successful=True, reason='')), ready=False)
        self.client.next_write = restoring
        with self.assertRaises(TimeoutError): adapter.restore(wait)
        with self.assertRaises(TimeoutError): adapter.restore(wait)
        self.assertEqual(len(self.client.writes), 2)
        self.assertTrue(adapter.snapshot()['restoration_required'])
        restoring.ready = True
        adapter.restore(wait)
        self.assertEqual(len(self.client.writes), 2)
        self.assertEqual(adapter.phase, 'restored')
        self.assertEqual(self.client.actual, {**ORIGINAL, **ORIGINAL_VELOCITY})

    def test_optional_velocity_readback_mismatch_is_unconfirmed_then_restores_baseline(self):
        adapter = self.velocity_adapter()
        original_get = self.client.get_parameters
        def get(names):
            reply = original_get(names)
            if len(self.client.reads) == 2:
                reply.value.values[2].double_array_value[0] += .01
            return reply
        self.client.get_parameters = get
        with self.assertRaisesRegex(RuntimeError, '回读'):
            adapter.apply(wait)
        self.assertEqual(adapter.phase, 'apply_unconfirmed')
        adapter.restore(wait)
        self.assertEqual(self.client.actual, {**ORIGINAL, **ORIGINAL_VELOCITY})
        self.assertFalse(adapter.dirty)

    def test_caller_cancellation_after_optional_write_keeps_original_receipt_for_cleanup(self):
        adapter = self.velocity_adapter()
        def cancel_after_write(future):
            if self.client.write_futures and future is self.client.write_futures[0]:
                raise InterruptedError('caller canceled while waiting for apply ACK')
            wait(future)
        with self.assertRaises(InterruptedError): adapter.apply(cancel_after_write)
        self.assertEqual(adapter.phase, 'apply_unconfirmed')
        self.assertTrue(adapter.dirty)
        self.assertEqual(len(self.client.writes), 1)
        adapter.restore(wait)
        self.assertEqual(len(self.client.writes), 2)
        self.assertEqual(adapter.phase, 'restored')
        self.assertEqual(self.client.actual, {**ORIGINAL, **ORIGINAL_VELOCITY})

    def test_optional_velocity_fields_require_pair_finite_vectors_and_native_signs(self):
        cases = [
            {'max_velocity': [.05, 0., .1]},
            {'min_velocity': [-.05, 0., -.1]},
            {**LOADED_VELOCITY, 'max_velocity': [-.05, 0., .1]},
            {**LOADED_VELOCITY, 'min_velocity': [.05, 0., -.1]},
            {**LOADED_VELOCITY, 'max_velocity': [True, 0., .1]},
            {**LOADED_VELOCITY, 'min_velocity': [-.05, 0., float('inf')]},
            {**LOADED_VELOCITY, 'max_velocity': [.05, 0.]},
        ]
        for extra in cases:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                limits({**LOADED, **extra})
        with self.assertWarnsRegex(RuntimeWarning, 'note'):
            self.assertEqual(limits({**LOADED, **LOADED_VELOCITY, 'note': 'finite panel candidate'}),
                             {**LOADED, **LOADED_VELOCITY})
        self.assertEqual(self.client.writes, [])


class LoadedRppLimitsTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.client.actual = copy.deepcopy(ORIGINAL_RPP)
        self.active = True
        self.adapter = LoadedRppLimits(LOADED_RPP, self.client,
            lambda: Future(NS(current_state=NS(id=3 if self.active else 2))),
            lambda name, value: NS(name=name, value=value))

    def test_scalar_native_double_apply_readback_and_actual_baseline_restore(self):
        self.client.actual[RPP_NAMES[0]] = .115
        baseline = copy.deepcopy(self.client.actual)
        self.adapter.apply(wait)
        self.assertEqual(self.adapter.snapshot()['node'], '/controller_server')
        self.assertEqual(self.adapter.baseline, baseline)
        self.assertEqual(self.client.actual, LOADED_RPP)
        self.assertTrue(all(type(value) is float for value in self.client.writes[0].values()))
        self.adapter.restore(wait)
        self.assertEqual(self.client.actual, baseline)
        self.assertEqual(self.client.writes, [LOADED_RPP, baseline])
        self.assertEqual(self.client.reads, [list(RPP_NAMES)]*3)
        fresh = self.adapter.new_task()
        self.assertIsInstance(fresh, LoadedRppLimits)
        self.assertEqual(fresh.desired, LOADED_RPP)
        self.assertEqual(fresh.requests, {})

    def test_nonempty_declared_subset_does_not_touch_other_controller_parameters(self):
        desired = {RPP_NAMES[0]: .03}
        adapter = LoadedRppLimits(desired, self.client, self.adapter.lifecycle_query,
                                  self.adapter.parameter_factory)
        adapter.apply(wait)
        self.assertEqual(self.client.reads, [[RPP_NAMES[0]]]*2)
        for key in RPP_NAMES[1:]:self.assertEqual(self.client.actual[key], ORIGINAL_RPP[key])
        adapter.restore(wait)
        self.assertEqual(self.client.actual, ORIGINAL_RPP)

    def test_scalar_rejects_array_response_without_claiming_apply(self):
        def wrong(names):return Future(NS(values=[NS(type=8,double_array_value=[.1])for _ in names]))
        self.client.get_parameters = wrong
        with self.assertRaisesRegex(RuntimeError, 'DOUBLE'):
            self.adapter.apply(wait)
        self.assertEqual(self.client.writes, [])
        self.assertFalse(self.adapter.dirty)
        self.assertEqual(self.adapter.phase, 'apply_unconfirmed')

    def test_scalar_readback_mismatch_fails_then_restores_original_values(self):
        original_get = self.client.get_parameters
        def wrong(names):
            reply = original_get(names)
            if len(self.client.reads) == 2:reply.value.values[0].double_value += .01
            return reply
        self.client.get_parameters = wrong
        with self.assertRaisesRegex(RuntimeError, '回读'):
            self.adapter.apply(wait)
        self.adapter.restore(wait)
        self.assertEqual(self.client.actual, ORIGINAL_RPP)

    def test_canceled_scalar_apply_and_unknown_restore_reuse_original_futures(self):
        pending = Future(NS(result=NS(successful=True, reason='')), ready=False)
        self.client.next_write = pending
        def canceled(future):
            if future is pending:raise InterruptedError('task canceled')
            wait(future)
        with self.assertRaises(InterruptedError):self.adapter.apply(canceled)
        with self.assertRaises(TimeoutError):self.adapter.restore(wait)
        self.assertEqual(self.client.writes, [LOADED_RPP])
        pending.ready = True
        restoring = Future(NS(result=NS(successful=True, reason='')), ready=False)
        self.client.next_write = restoring
        with self.assertRaises(TimeoutError):self.adapter.restore(wait)
        self.assertEqual(self.client.writes, [LOADED_RPP, ORIGINAL_RPP])
        self.assertTrue(self.adapter.dirty)
        restoring.ready = True
        self.adapter.restore(wait)
        self.assertEqual(self.client.writes, [LOADED_RPP, ORIGINAL_RPP])
        self.assertEqual(self.adapter.phase, 'restored')

    def test_inactive_controller_or_nonpositive_scalar_never_writes(self):
        self.active = False
        with self.assertRaisesRegex(RuntimeError, 'controller_server.*active'):
            self.adapter.apply(wait)
        for value in (True, 0, -.01, float('nan'), float('inf'), [.1]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                rpp_limits({RPP_NAMES[0]: value})
        for value in ({}, {'note': 'human note'}):
            with self.subTest(value=value), self.assertRaises(ValueError):rpp_limits(value)
        with self.assertWarnsRegex(RuntimeWarning, 'note'):
            self.assertEqual(rpp_limits({**LOADED_RPP, 'note': 'finite panel assumption'}), LOADED_RPP)
        self.assertEqual(self.client.writes, [])


if __name__ == '__main__':
    unittest.main()
