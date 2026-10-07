import importlib.util
from pathlib import Path
import math
import subprocess
import sys
from types import SimpleNamespace
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'fishbot_passage_goal.py'
spec = importlib.util.spec_from_file_location('passage_goal', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Future:
    def __init__(self):
        self.callbacks = []
        self.ready = False
        self.value = None

    def add_done_callback(self, callback):
        self.callbacks.append(callback)
        if self.ready:
            callback(self)

    def resolve(self, value):
        self.value, self.ready = value, True
        for callback in self.callbacks:
            callback(self)

    def done(self):
        return self.ready

    def result(self):
        return self.value


class PassageGoalTests(unittest.TestCase):
    def test_endpoint_follows_requested_heading(self):
        x, y, yaw = module.requested_endpoint(2, 3, math.pi/2, 1)
        self.assertAlmostEqual(x, 2)
        self.assertAlmostEqual(y, 4)
        self.assertAlmostEqual(yaw, math.pi/2)

    def test_invalid_inputs_fail(self):
        for distance in (0, -1, 4, math.nan, math.inf):
            with self.subTest(distance=distance), self.assertRaises(ValueError):
                module.requested_endpoint(0, 0, 0, distance)

    def test_default_does_not_need_ros(self):
        p = subprocess.run([sys.executable, str(SCRIPT)], text=True, capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('"execute": false', p.stdout)

    def test_real_domain_needs_explicit_real(self):
        p = subprocess.run([sys.executable, str(SCRIPT), '--domain', '0'], text=True, capture_output=True)
        self.assertNotEqual(p.returncode, 0)

    def test_invalid_orientation_cannot_become_a_forward_goal(self):
        for q in ((0,0,0,0), (0,0,0,10), (0,0,math.nan,1)):
            with self.subTest(q=q), self.assertRaises(ValueError):
                module.heading_from_quaternion(q)
        self.assertAlmostEqual(module.heading_from_quaternion((0,0,0,1)), 0)

    def test_old_stack_or_unhealthy_guard_cannot_accept_motion(self):
        values = {'execute':'True','profile':'fishbot_passage'}
        self.assertTrue(module.guard_preflight('priming: awaiting command', values,
                        ['fishbot_command_guard'], ['diff_drive_controller'], 'diff_drive_controller'))
        for status in ('latched: stale', 'priming: scan: missing'):
            self.assertFalse(module.guard_preflight(status, values,
                             ['fishbot_command_guard'], ['diff_drive_controller'], 'diff_drive_controller'))
        self.assertFalse(module.guard_preflight('healthy', values,
                         ['collision_monitor'], ['diff_drive_controller'], 'diff_drive_controller'))

    def test_diagnostic_octet_is_parsed_strictly(self):
        for value in (0, b'\x00', bytearray(b'\x00')):
            self.assertEqual(module.diagnostic_level(value), 0)
        self.assertEqual(module.diagnostic_level(b'\x02'), 2)
        for value in (True, b'', b'00', '0', 4, -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.diagnostic_level(value)

    def test_success_without_final_stationary_feedback_stops_and_cancels(self):
        result = {'completed': True, 'stationary_feedback': False}
        calls = []
        def operation(name):
            return lambda: calls.append(name)
        module.finalize_goal(result, True, operation('stop'), operation('cancel'),
                             operation('observe'), operation('refresh'), operation('destroy'),
                             operation('shutdown'), operation('record'))
        self.assertEqual(calls, ['observe', 'stop', 'cancel', 'refresh', 'destroy', 'shutdown', 'record'])
        self.assertIn('stationary', result['error'])

    def test_one_rpc_or_cleanup_failure_does_not_skip_other_safety_steps(self):
        result = {'completed': False, 'stationary_feedback': False}
        calls = []
        def operation(name, fails=False):
            def execute():
                calls.append(name)
                if name == 'observe':
                    result['stationary_feedback'] = True
                if fails:
                    raise RuntimeError(name + ' unavailable')
            return execute
        module.finalize_goal(result, True, operation('stop', True), operation('cancel', True),
                             operation('observe'), operation('refresh', True), operation('destroy', True),
                             operation('shutdown'), operation('record'))
        self.assertEqual(calls, ['stop', 'cancel', 'observe', 'refresh', 'destroy', 'shutdown', 'record'])
        self.assertEqual(len(result['cleanup_errors']), 4)

    def test_interrupted_observation_cannot_keep_a_previous_stationary_pass(self):
        result = {'completed': True, 'stationary_feedback': True}
        calls = []
        def observe():
            raise RuntimeError('executor failed after an earlier good sample')
        module.finalize_goal(result, True, lambda: calls.append('stop'), lambda: calls.append('cancel'),
                             observe, lambda: None, lambda: None, lambda: None, lambda: None)
        self.assertFalse(result['stationary_feedback'])
        self.assertEqual(calls, ['stop', 'cancel'])

    def test_delayed_goal_ack_still_receives_cancellation(self):
        evidence, calls = {}, []
        pending = module.PendingGoal(evidence)
        ack, cancel, terminal = Future(), Future(), Future()
        def cancel_goal():
            calls.append('cancel')
            return cancel
        handle = SimpleNamespace(accepted=True, cancel_goal_async=cancel_goal,
                                 get_result_async=lambda: terminal)
        pending.track(ack)
        self.assertIsNone(pending.cancel())
        pending.refresh()
        self.assertTrue(evidence['goal_ack_pending'])
        ack.resolve(handle)
        pending.cancel()
        self.assertEqual(calls, ['cancel'])
        cancel.resolve(SimpleNamespace(goals_canceling=['this-goal']))
        terminal.resolve(SimpleNamespace(status=5))
        pending.refresh()
        self.assertFalse(evidence['goal_ack_pending'])
        self.assertTrue(evidence['cancel_acknowledged'])
        self.assertTrue(evidence['canceled'])

    def test_terminal_success_is_not_reported_as_canceled(self):
        evidence = {}
        pending = module.PendingGoal(evidence)
        terminal = Future()
        terminal.resolve(SimpleNamespace(status=4))
        pending.cancel_requested, pending.result_future = True, terminal
        pending.refresh()
        self.assertEqual(evidence['cancel_terminal_status'], 4)
        self.assertFalse(evidence['canceled'])

    def test_evidence_failure_still_cleans_up_and_is_reported(self):
        result = {'completed': True, 'stationary_feedback': True}
        calls = []
        def record():
            calls.append('record')
            raise OSError('disk full')
        module.finalize_goal(result, True, lambda: calls.append('stop'), lambda: calls.append('cancel'),
                             lambda: None, lambda: None, lambda: calls.append('destroy'),
                             lambda: calls.append('shutdown'), record)
        self.assertEqual(calls, ['destroy', 'shutdown', 'record'])
        self.assertIn('disk full', result['cleanup_errors'][0])


if __name__ == '__main__':
    unittest.main()
