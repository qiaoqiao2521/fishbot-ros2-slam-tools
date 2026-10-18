"""Offline checks of the reused physical oracle boundary; no ROS initialization."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fishbot_workbench_recovery_acceptance import score_case, sources


class RecoveryOracle(unittest.TestCase):
    def setUp(self):
        self.identity = '3493539a-c09d-400b-972d-81ef6045c9c0'
        self.marker = {'owned_mission_id': self.identity, 'dispatch_epoch': 100.,
                       'requested_body': {'waypoints': [{'x': .6, 'y': 0, 'yaw': 0}]},
                       'start_truth': {'x': 0, 'y': 0}, 'cancel_epoch': 100.3}
        self.terminal = {'id': self.identity, 'status': 'succeeded', 'native_status': 4,
                         'native_error_code': 0, 'missed_waypoints': [], 'return_home': True,
                         'start_pose': {'x': 0, 'y': 0, 'yaw': 0}, 'cleanup_state': None}
        xs = [0, .1, .2, .3, .4, .5, .6, .5, .4, .3, .2, .1, 0] + [0]*10
        self.frames = [{'epoch': 100+i*.1, 'steady_time': 100+i*.1, 'stamp': 10+i*.1,
                        'ros_now': 10+i*.1+.01, 'x': x, 'y': 0, 'yaw': 0,
                        'linear_speed': .1 if i < 12 else 0, 'angular_speed': 0} for i, x in enumerate(xs)]
        self.frames.insert(0, {**self.frames[0], 'epoch': 99.9, 'steady_time': 99.9, 'stamp': 9.9, 'ros_now': 9.91, 'linear_speed': 0})

    def test_native_success_and_truth_return_both_required(self):
        result = score_case('return_recovery', {'marker': self.marker}, self.frames, self.terminal)
        self.assertEqual(len(result['ordered_visits']), 2)
        self.assertEqual(result['endpoint_error_m'], 0)
        for change in ({'native_status': 6}, {'native_error_code': 1}, {'missed_waypoints': [0]},
                       {'return_home': False}, {'id': 'another'}, {'cleanup_state': 'unresolved'}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                score_case('return_recovery', {'marker': self.marker}, self.frames, {**self.terminal, **change})

    def test_stale_gap_and_insufficient_quiet_are_not_a_pass(self):
        for kind in ('age', 'gap', 'quiet'):
            frames = copy.deepcopy(self.frames)
            if kind == 'age': frames[3]['ros_now'] += .3
            if kind == 'gap': frames[3]['steady_time'] += .31
            if kind == 'quiet': frames[-2]['linear_speed'] = .1
            with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                score_case('return_recovery', {'marker': self.marker}, frames, self.terminal)

    def test_a_missing_or_old_pre_dispatch_boundary_never_passes(self):
        with self.assertRaises(RuntimeError): score_case('return_recovery', {'marker': self.marker}, self.frames[1:], self.terminal)
        frames = copy.deepcopy(self.frames); frames[0]['epoch'] = 99.7
        with self.assertRaises(RuntimeError): score_case('return_recovery', {'marker': self.marker}, frames, self.terminal)

    def test_a_native_terminal_cannot_replace_actual_outbound_visits_or_home_accuracy(self):
        frames = [{**f, 'x': 0} for f in self.frames]
        with self.assertRaises(RuntimeError): score_case('return_recovery', {'marker': self.marker}, frames, self.terminal)
        frames = copy.deepcopy(self.frames)
        for f in frames[-10:]: f['x'] = .3
        with self.assertRaises(RuntimeError): score_case('return_recovery', {'marker': self.marker}, frames, self.terminal)

    def test_cancel_requires_independent_translation_before_the_same_native_canceled_goal(self):
        terminal = {**self.terminal, 'status': 'canceled', 'native_status': 5}
        self.assertIn('independent_moving_frame', score_case('moving_cancel', {'marker': self.marker}, self.frames, terminal))
        for change in ({'native_status': 4}, {'status': 'succeeded'}, {'id': 'other'}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                score_case('moving_cancel', {'marker': self.marker}, self.frames, {**terminal, **change})
        with self.assertRaises(RuntimeError): score_case('moving_cancel', {'marker': self.marker}, [{**f, 'linear_speed': 0} for f in self.frames], terminal)

    def test_all_declared_execution_sources_exist(self):
        manifest = sources()
        self.assertGreaterEqual(len(manifest), 20)
        self.assertTrue(all(len(value) == 64 for value in manifest.values()))


if __name__ == '__main__': unittest.main()
