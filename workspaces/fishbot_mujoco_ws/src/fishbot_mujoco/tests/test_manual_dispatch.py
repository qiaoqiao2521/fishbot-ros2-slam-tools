"""Queue wakeups and native clock routing, without ROS initialization."""
from concurrent.futures import Future
import json
from pathlib import Path
import queue
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from mission_bridge import (APIError, ManualGCTiming, MissionBridge,
                            Node, ClockMessage, TimeSource, run_server)


class ManualDispatchTests(unittest.TestCase):
    def harness(self):
        calls, logger = [], SimpleNamespace(warning=Mock(), error=Mock())
        bridge = SimpleNamespace(lock=threading.RLock(), operations=queue.Queue(maxsize=32),
            stopping=False, dispatch_wakeup=SimpleNamespace(trigger=Mock()), get_logger=lambda: logger)
        bridge.manual_request = lambda method, path, body: (calls.append((path, body)) or
            (200, {'accepted': True, 'outcome': 'accepted', 'sequence': body['sequence']}))
        return bridge, calls, logger

    def enqueue(self, bridge, sequence):
        return MissionBridge.enqueue(bridge, 'manual',
            {'path': '/sim-api/manual/command', 'body': {'sequence': sequence}})

    def test_same_fifo_batch_cap_wakes_remaining_and_never_dispatches_twice(self):
        bridge, calls, _ = self.harness()
        futures = [self.enqueue(bridge, i) for i in range(6)]
        self.assertEqual(bridge.dispatch_wakeup.trigger.call_count, 6)
        MissionBridge.drain_operations(bridge)
        self.assertEqual([body['sequence'] for _, body in calls], list(range(4)))
        self.assertTrue(all(future.done() for future in futures[:4]))
        self.assertTrue(all(not future.done() for future in futures[4:]))
        self.assertEqual(bridge.dispatch_wakeup.trigger.call_count, 7)
        MissionBridge.drain_operations(bridge)
        MissionBridge.drain_operations(bridge)
        self.assertEqual([body['sequence'] for _, body in calls], list(range(6)))
        self.assertEqual([future.result()[1]['sequence'] for future in futures], list(range(6)))

    def test_canceled_and_deadline_expired_requests_are_not_dispatched(self):
        bridge, calls, _ = self.harness()
        with patch('mission_bridge.time.monotonic', return_value=100.):
            canceled, expired = self.enqueue(bridge, 1), self.enqueue(bridge, 2)
        canceled.cancel()
        MissionBridge.drain_operations(bridge, wall=102.001)
        self.assertEqual(calls, [])
        self.assertTrue(canceled.cancelled())
        status, receipt = expired.result()
        self.assertEqual(status, 408)
        self.assertIs(receipt['accepted'], False)
        self.assertEqual(receipt['outcome'], 'rejected')

    def test_wake_failure_retains_original_pending_work_for_periodic_fallback(self):
        bridge, calls, logger = self.harness()
        bridge.dispatch_wakeup.trigger.side_effect = RuntimeError('wake unavailable')
        future = self.enqueue(bridge, 1)
        self.assertFalse(future.done())
        logger.warning.assert_called_once()
        MissionBridge.drain_operations(bridge, wall=0.)
        self.assertEqual(len(calls), 1)
        self.assertEqual(future.result()[0], 200)

    def test_shutdown_fences_new_work_and_does_not_invent_old_future_outcomes(self):
        bridge, calls, _ = self.harness()
        pending = self.enqueue(bridge, 1)
        bridge.stopping = True
        with self.assertRaises(APIError) as caught:
            self.enqueue(bridge, 2)
        self.assertEqual(caught.exception.outcome, 'rejected')
        MissionBridge.drain_operations(bridge)
        self.assertFalse(pending.done())
        self.assertEqual(calls, [])
        self.assertTrue(pending.cancel())

    def test_wakeup_does_not_bypass_original_mission_readiness_evaluation(self):
        bridge, _, _ = self.harness()
        order = []
        bridge.evaluate_ready = lambda wall: (order.append('readiness') or (False, 'not ready'))
        def start(body):
            order.append('start')
            if not bridge.ready: raise APIError(bridge.reason, 503, outcome='rejected')
        bridge.start_mission, bridge.state = start, Mock()
        future = MissionBridge.enqueue(bridge, 'mission', {})
        MissionBridge.drain_operations(bridge)
        self.assertEqual(order, ['readiness', 'start'])
        self.assertEqual(future.result()[0], 503)
        bridge.state.assert_not_called()

    def test_dispatch_boundaries_preserve_the_original_body_and_receipt(self):
        bridge, calls, _ = self.harness()
        body = {'path': '/sim-api/manual/command',
                'body': {'sequence': 6, 'issued_at_ms': 1234}}
        with patch('mission_bridge.time.monotonic', return_value=10.):
            future = MissionBridge.enqueue(bridge, 'manual', body)
        with patch('mission_bridge.time.monotonic', side_effect=[10.025, 10.03, 10.04]):
            MissionBridge.drain_operations(bridge, wall=10.025)
        self.assertIs(calls[0][1], body['body'])
        self.assertEqual(body['body'], {'sequence': 6, 'issued_at_ms': 1234})
        self.assertEqual(future.result(), (200, {'accepted': True, 'outcome': 'accepted', 'sequence': 6}))
        self.assertEqual(future.dispatch_timing, {'enqueued_steady': 10.,
            'put_done_steady': 10., 'trigger_before_steady': 10., 'trigger_after_steady': 10.,
            'drain_entered_steady': 10.025, 'dequeued_steady': 10.03,
            'completed_steady': 10.04})


class ManualSlowTimingTests(unittest.TestCase):
    def harness(self):
        logger = SimpleNamespace(warning=Mock())
        bridge = SimpleNamespace(lock=threading.RLock(), control_profile='passage_manual',
            runtime_instance_id='original-runtime', manual_slow_timing_count=0,
            manual_adapter=SimpleNamespace(controller=SimpleNamespace(
                current_lease={'lease_id': 'original-lease', 'last_sequence': 5})),
            get_logger=lambda: logger)
        return bridge, logger

    def test_only_slow_current_lease_observations_are_retained_with_two_memory_bounds(self):
        bridge, logger = self.harness()
        MissionBridge.record_manual_slow_timing(bridge, 'fast', 10., 10.049)
        bridge.control_profile = 'baseline'
        MissionBridge.record_manual_slow_timing(bridge, 'baseline', 10., 11.)
        logger.warning.assert_not_called()
        bridge.control_profile = 'passage_manual'
        for _ in range(35):
            MissionBridge.record_manual_slow_timing(bridge, 'http.manual', 10., 10.27,
                sequence=6, issued_at_ms=1234, path='/sim-api/manual/command')
        logger.warning.assert_not_called()
        self.assertEqual(bridge.manual_slow_timing_count, 35)
        snapshot = MissionBridge.manual_timing_snapshot(bridge)
        self.assertLessEqual(len(snapshot['events']), 32)
        self.assertLessEqual(snapshot['retained_bytes'], 8192)
        self.assertEqual(snapshot['evicted_events'], 35-len(snapshot['events']))
        self.assertEqual(snapshot['rejected_events'], 0)
        self.assertIs(snapshot['logging_enabled'], False)
        event = snapshot['events'][-1]
        self.assertEqual(event['sequence'], 6)
        self.assertEqual(event['accepted_sequence'], 5)
        self.assertEqual(event['issued_at_ms'], 1234)
        self.assertEqual(event['runtime_instance_id'], 'original-runtime')
        self.assertEqual(event['lease_id'], 'original-lease')
        # A quiet startup cannot exhaust the first real press's trace budget.
        bridge.manual_adapter.controller.current_lease = None
        MissionBridge.record_manual_slow_timing(bridge, 'tick', 10., 11.)
        self.assertEqual(MissionBridge.manual_timing_snapshot(bridge)['events'], [])
        bridge.manual_adapter.controller.current_lease = {
            'lease_id': 'next-original-lease', 'last_sequence': 1}
        MissionBridge.record_manual_slow_timing(bridge, 'tick', 10., 10.27)
        logger.warning.assert_not_called()
        self.assertEqual(bridge.manual_slow_timing_count, 1)

    def test_diagnostic_collection_does_not_call_a_sink_or_replace_the_original_failure(self):
        bridge, logger = self.harness()
        logger.warning.side_effect = RuntimeError('diagnostic sink unavailable')
        with patch('mission_bridge.time.monotonic', side_effect=[10., 10.27]):
            with self.assertRaisesRegex(ValueError, 'original callback failure'):
                with MissionBridge.manual_timing(bridge, 'rules_result.global.costmap'):
                    raise ValueError('original callback failure')
        logger.warning.assert_not_called()
        self.assertEqual(MissionBridge.manual_timing_snapshot(bridge)['observed_events'], 1)

    def test_malformed_or_oversize_context_is_counted_without_escape_or_retention(self):
        bridge, logger = self.harness()
        cyclic = []
        cyclic.append(cyclic)
        for payload in (object(), cyclic, float('nan'), 'x'*9000):
            MissionBridge.record_manual_slow_timing(bridge, 'http.manual', 10., 10.27,
                                                   context=payload)
        snapshot = MissionBridge.manual_timing_snapshot(bridge)
        self.assertEqual(snapshot['events'], [])
        self.assertEqual(snapshot['observed_events'], 4)
        self.assertEqual(snapshot['rejected_events'], 4)
        self.assertEqual(snapshot['retained_bytes'], 0)
        logger.warning.assert_not_called()

    def test_snapshot_and_input_context_do_not_alias_retained_events(self):
        bridge, _ = self.harness()
        context = {'stages': [{'value': 1}]}
        MissionBridge.record_manual_slow_timing(bridge, 'http.manual', 10., 10.27,
                                               context=context)
        context['stages'][0]['value'] = 2
        snapshot = MissionBridge.manual_timing_snapshot(bridge)
        self.assertEqual(snapshot['events'][0]['context']['stages'][0]['value'], 1)
        snapshot['events'][0]['context']['stages'][0]['value'] = 3
        fresh = MissionBridge.manual_timing_snapshot(bridge)
        self.assertEqual(fresh['events'][0]['context']['stages'][0]['value'], 1)

    def test_slow_stage_retains_same_thread_cpu_and_gc_boundaries_in_original_ring(self):
        bridge, _ = self.harness()
        observer = bridge.manual_gc_timing = ManualGCTiming()
        with patch('mission_bridge.time.monotonic', side_effect=[10., 10.27]), \
                patch('mission_bridge.time.thread_time', side_effect=[2., 2.015]), \
                patch('mission_bridge.threading.get_native_id', return_value=99):
            with MissionBridge.manual_timing(bridge, 'tick'):
                observer.state = ((0, 0, 1), (0, 0, 1), None,
                    (1, 10.02, 5., 100, 10.20, 5.17, 100, 3, 0), 0, 0, 0)
        value = MissionBridge.manual_timing_snapshot(bridge)
        event = value['events'][0]
        self.assertEqual(event['thread_id'], 99)
        self.assertEqual(event['end_thread_id'], 99)
        self.assertAlmostEqual(event['thread_cpu_duration_s'], .015)
        self.assertEqual(event['gc_before']['generation_stops'], [0, 0, 0])
        self.assertEqual(event['gc_after']['last_gc2'],
            [1, 10.02, 5., 100, 10.20, 5.17, 100, 3, 0])
        self.assertLessEqual(value['retained_bytes'], 8192)
        self.assertEqual(value['event_limit'], 32)
        event['gc_after']['last_gc2'][1] = -1
        self.assertEqual(MissionBridge.manual_timing_snapshot(bridge)['events'][0]
                         ['gc_after']['last_gc2'][1], 10.02)

    def test_diagnostic_clock_or_recorder_failure_cannot_replace_business_result(self):
        bridge, _ = self.harness()
        with patch('mission_bridge.time.thread_time', side_effect=RuntimeError('diagnostic clock')):
            with self.assertRaisesRegex(ValueError, 'original callback failure'):
                with MissionBridge.manual_timing(bridge, 'tick'):
                    raise ValueError('original callback failure')
        with patch('mission_bridge.time.monotonic', side_effect=[10., 10.27]), \
                patch('mission_bridge.time.thread_time', side_effect=[2., RuntimeError('end clock')]):
            with MissionBridge.manual_timing(bridge, 'tick'):
                result = 'original success'
        self.assertEqual(result, 'original success')
        self.assertEqual(bridge.manual_timing_rejected, 2)
        with patch('mission_bridge.time.monotonic', side_effect=[10., 10.27]), \
                patch.object(MissionBridge, 'record_manual_slow_timing', side_effect=RuntimeError('record')):
            with self.assertRaisesRegex(ValueError, 'original callback failure'):
                with MissionBridge.manual_timing(bridge, 'tick'):
                    raise ValueError('original callback failure')
        self.assertEqual(bridge.manual_timing_rejected, 3)


class ExecutionLifecycleTests(unittest.TestCase):
    def test_both_profiles_keep_one_native_owner_and_original_server_cleanup(self):
        for profile in ('baseline', 'passage_manual'):
            with self.subTest(profile=profile):
                executor, server = Mock(), Mock()
                executor.spin.side_effect = KeyboardInterrupt()
                bridge = SimpleNamespace(manual_adapter=None, destroy_node=Mock(),
                    get_logger=lambda: SimpleNamespace(info=Mock()))
                factory = Mock(return_value=bridge)
                factory.close_manual_timing = MissionBridge.close_manual_timing
                args = SimpleNamespace(control_profile=profile, manual_profile_receipt='/tmp/private-profile',
                    port=9097, ui_port=5182)
                with patch('mission_bridge.rclpy.init'), patch('mission_bridge.rclpy.ok', return_value=False), \
                        patch('mission_bridge.signal.signal'), patch('mission_bridge.threading.Thread'), \
                        patch('mission_bridge.MissionBridge', factory), \
                        patch('mission_bridge.SingleThreadedExecutor', return_value=executor) as native, \
                        patch('mission_bridge.LocalHTTPServer', return_value=server):
                    run_server(args, [], 129)
                native.assert_called_once_with()
                executor.add_node.assert_called_once_with(bridge)
                executor.spin.assert_called_once_with()
                executor.shutdown.assert_called_once_with()
                bridge.destroy_node.assert_called_once_with()
                server.shutdown.assert_called_once_with()
                server.server_close.assert_called_once_with()


class ManualGCTimingTests(unittest.TestCase):
    def test_direct_destroy_removes_own_real_gc_callback_even_if_node_destroy_raises(self):
        from mission_bridge import gc
        before = tuple(gc.callbacks)
        unrelated = lambda phase, info: None
        bridge = MissionBridge.__new__(MissionBridge)
        bridge.control_profile = 'passage_manual'
        gc.callbacks.append(unrelated)
        try:
            MissionBridge.start_manual_timing(bridge)
            observer = bridge.manual_gc_timing
            self.assertIn(observer.callback, gc.callbacks)
            with patch.object(Node, 'destroy_node', side_effect=RuntimeError('original destroy failure')):
                with self.assertRaisesRegex(RuntimeError, 'original destroy failure'):
                    bridge.destroy_node()
            self.assertFalse(observer.registered)
            self.assertNotIn(observer.callback, gc.callbacks)
            self.assertIn(unrelated, gc.callbacks)
            with patch.object(Node, 'destroy_node', return_value=True):
                self.assertTrue(bridge.destroy_node())
        finally:
            MissionBridge.close_manual_timing(bridge)
            gc.callbacks.remove(unrelated)
        self.assertEqual(tuple(gc.callbacks), before)

    def test_executor_creation_and_add_node_failures_uninstall_before_server_finally(self):
        for failure in ('creation', 'add_node'):
            with self.subTest(failure=failure), patch('mission_bridge.gc.callbacks', []) as callbacks:
                bridge = SimpleNamespace(control_profile='passage_manual')
                MissionBridge.start_manual_timing(bridge)
                factory = Mock(return_value=bridge)
                factory.close_manual_timing = MissionBridge.close_manual_timing
                executor = Mock()
                construction = RuntimeError('original executor failure') if failure == 'creation' else executor
                if failure == 'add_node':
                    executor.add_node.side_effect = RuntimeError('original executor failure')
                args = SimpleNamespace(control_profile='passage_manual', manual_profile_receipt='/tmp/private-profile')
                with patch('mission_bridge.rclpy.init'), patch('mission_bridge.signal.signal'), \
                        patch('mission_bridge.MissionBridge', factory), \
                        patch('mission_bridge.SingleThreadedExecutor', side_effect=construction if failure == 'creation' else None,
                              return_value=executor):
                    with self.assertRaisesRegex(RuntimeError, 'original executor failure'):
                        run_server(args, [], 129)
                self.assertFalse(bridge.manual_gc_timing.registered)
                self.assertEqual(callbacks, [])

    def test_profile_registration_and_shutdown_preserve_other_callbacks(self):
        unrelated = lambda phase, info: None
        callbacks = [unrelated]
        with patch('mission_bridge.gc.callbacks', callbacks):
            baseline = SimpleNamespace(control_profile='baseline')
            MissionBridge.start_manual_timing(baseline)
            self.assertIsNone(baseline.manual_gc_timing)
            self.assertEqual(callbacks, [unrelated])
            manual = SimpleNamespace(control_profile='passage_manual')
            MissionBridge.start_manual_timing(manual)
            observer = manual.manual_gc_timing
            observer.start()
            self.assertEqual(callbacks, [unrelated, observer.callback])
            MissionBridge.close_manual_timing(manual)
            MissionBridge.close_manual_timing(manual)
            self.assertEqual(callbacks, [unrelated])
            observer.observe('start', {'generation': 2})
            self.assertEqual(observer.state[0], (0, 0, 0))

    def test_gc2_pairs_record_cpu_and_tid_while_all_generation_counts_remain_explicit(self):
        observer = ManualGCTiming()
        with patch('mission_bridge.gc.callbacks', []):
            observer.start()
            for generation in (0, 1):
                observer.observe('start', {'generation': generation})
                observer.observe('stop', {'generation': generation})
            with patch('mission_bridge.time.monotonic', side_effect=[10., 10.2]), \
                    patch('mission_bridge.time.thread_time', side_effect=[1., 1.15]), \
                    patch('mission_bridge.threading.get_native_id', return_value=7):
                observer.observe('start', {'generation': 2})
                observer.observe('stop', {'generation': 2, 'collected': 4, 'uncollectable': 1})
            value = ManualGCTiming.snapshot(observer.state)
            self.assertEqual(value['generation_starts'], (1, 1, 1))
            self.assertEqual(value['generation_stops'], (1, 1, 1))
            self.assertEqual(value['last_gc2'], (1, 10., 1., 7, 10.2, 1.15, 7, 4, 1))
            self.assertIsNone(value['pending_gc2'])
            self.assertIs(value['last_only'], True)
            self.assertIs(value['generation_0_1_duration_observed'], False)
            observer.close()

    def test_fixed_storage_reports_completed_and_incomplete_overwrites(self):
        observer = ManualGCTiming()
        with patch('mission_bridge.gc.callbacks', []):
            observer.start()
            for _ in range(500):
                observer.observe('start', {'generation': 2})
                observer.observe('stop', {'generation': 2, 'collected': 0, 'uncollectable': 0})
            observer.observe('start', {'generation': 2})
            observer.observe('start', {'generation': 2})
            value = ManualGCTiming.snapshot(observer.state)
            self.assertEqual(value['completed_gc2_overwritten'], 499)
            self.assertEqual(value['pending_gc2_overwritten'], 1)
            self.assertEqual(value['last_gc2'][0], 500)
            self.assertEqual(value['pending_gc2'][0], 502)
            self.assertEqual(len(observer.state), 7)
            self.assertLess(len(json.dumps(value)), 1024)
            observer.close()

    def test_malformed_or_failed_hook_observations_do_not_escape_or_call_owner(self):
        observer = ManualGCTiming()
        with patch('mission_bridge.gc.callbacks', []):
            observer.start()
            for phase, info in [('start', {}), ('start', {'generation': True}),
                                ('bad', {'generation': 2}),
                                ('stop', {'generation': 2, 'collected': 0, 'uncollectable': 0})]:
                observer.observe(phase, info)
            with patch('mission_bridge.time.monotonic', side_effect=RuntimeError('diagnostic clock')):
                observer.observe('start', {'generation': 2})
            self.assertEqual(observer.state[6], 5)
            self.assertEqual(observer.state[0], (0, 0, 0))
            observer.close()

    def test_failed_registration_or_external_removal_preserves_callback_lifecycle(self):
        observer = ManualGCTiming()
        callbacks = Mock()
        callbacks.append.side_effect = RuntimeError('diagnostic registration')
        with patch('mission_bridge.gc.callbacks', callbacks):
            observer.start()
        self.assertFalse(observer.registered)
        self.assertEqual(observer.state[6], 1)
        with patch('mission_bridge.gc.callbacks', []):
            observer.start()
            # Removing only this callback does not grant ownership of the list.
            from mission_bridge import gc
            gc.callbacks.remove(observer.callback)
            observer.close()
        self.assertFalse(observer.registered)


class NativeClockRoutingTests(unittest.TestCase):
    def test_only_stock_timesource_is_routed_and_all_subscription_options_survive(self):
        bridge = MissionBridge.__new__(MissionBridge)
        bridge.clock_callbacks = object()
        source = TimeSource()
        kwargs = {'event_callbacks': object(), 'qos_overriding_options': object(),
                  'raw': True, 'content_filter_options': object()}
        qos = object()
        with patch.object(Node, 'create_subscription', return_value='subscription') as native:
            result = bridge.create_subscription(ClockMessage, '/clock', source.clock_callback, qos, **kwargs)
            self.assertEqual(result, 'subscription')
            self.assertEqual(native.call_args.args, (ClockMessage, '/clock', source.clock_callback, qos))
            self.assertEqual(native.call_args.kwargs, {**kwargs, 'callback_group': bridge.clock_callbacks})
            bridge.create_subscription(ClockMessage, '/clock', bridge.on_clock, qos)
            self.assertIsNone(native.call_args.kwargs['callback_group'])
            explicit_group = object()
            bridge.create_subscription(ClockMessage, '/clock', source.clock_callback, qos,
                                       callback_group=explicit_group)
            self.assertIs(native.call_args.kwargs['callback_group'], explicit_group)
            bridge.clock_callbacks = None
            bridge.create_subscription(ClockMessage, '/clock', source.clock_callback, qos)
            self.assertIsNone(native.call_args.kwargs['callback_group'])


if __name__ == '__main__': unittest.main()
