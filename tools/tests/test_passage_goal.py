import importlib.util
import json
from pathlib import Path
import math
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET

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
    def test_route_bounds_include_fresh_start(self):
        route = [[1, 0, 0], [1, 1, math.pi/2], [0, .2, -math.pi/2]]
        poses, length = module.requested_map_route(0, 0, 0, route)
        self.assertEqual(poses, [tuple(p) for p in route])
        self.assertAlmostEqual(length, 2 + math.hypot(1, .8))
        with self.assertRaises(ValueError):
            module.requested_map_route(-2.001, 0, 0, route)
        # Inter-point path is 9 m, but the fresh first leg adds 2 m.
        with self.assertRaisesRegex(ValueError, '10 metres'):
            module.requested_map_route(-2, 0, 0,
                                       [[0, 0, 0], [3, 0, 0], [0, 0, 0], [3, 0, 0]])

    def test_closed_loop_near_fresh_start_is_rejected_even_with_different_yaw(self):
        for end_x in (0, .099999, .1):
            for yaw in (0, math.pi, -math.pi/2):
                with self.subTest(end_x=end_x, yaw=yaw), self.assertRaisesRegex(ValueError, 'closed-loop.*goal checker'):
                    module.requested_map_route(0, 0, .3, [[1, 0, 0], [end_x, 0, yaw]])
        module.requested_map_route(0, 0, .3, [[1, 0, 0], [.100001, 0, math.pi]])

    @staticmethod
    def route_feedback(x, y, remaining=1, stamp=100., frame='map'):
        sec = math.floor(stamp)
        return SimpleNamespace(number_of_poses_remaining=remaining, current_pose=SimpleNamespace(
            header=SimpleNamespace(frame_id=frame, stamp=SimpleNamespace(
                sec=sec, nanosec=round((stamp-sec)*1e9))),
            pose=SimpleNamespace(position=SimpleNamespace(x=x, y=y))))

    def test_route_feedback_requires_fresh_intermediates_in_order(self):
        evidence = {}
        coverage = module.RouteCoverage([(1, 0, 0), (2, 0, 0), (3, 0, 0)], evidence)
        coverage.observe(self.route_feedback(2, 0, remaining=1), 100.1)
        self.assertEqual(evidence['route_waypoint_visits'], [])
        for feedback in (self.route_feedback(1, 0, stamp=99),
                         self.route_feedback(1, 0, frame='odom'),
                         self.route_feedback(math.nan, 0)):
            coverage.observe(feedback, 100.1)
        self.assertEqual(evidence['route_invalid_feedback_count'], 3)
        self.assertEqual(evidence['route_waypoint_visits'], [])
        coverage.observe(self.route_feedback(.851, 0, remaining=2), 100.1)
        self.assertEqual(len(evidence['route_waypoint_visits']), 1)
        with self.assertRaisesRegex(RuntimeError, '1/2'):
            coverage.require_complete()
        coverage.observe(self.route_feedback(2, 0, remaining=1), 100.1)
        coverage.require_complete()
        self.assertTrue(evidence['route_intermediate_coverage'])
        self.assertEqual(evidence['route_feedback_remaining'], 1)
        self.assertEqual([v['index'] for v in evidence['route_waypoint_visits']], [0, 1])

    def test_nav2_success_without_route_feedback_enters_stop_and_cancel(self):
        result = {'completed': False, 'stationary_feedback': False, 'action_status': 4}
        coverage = module.RouteCoverage([(1, 0, 0), (2, 0, 0)], result)
        with self.assertRaisesRegex(RuntimeError, '0/1'):
            coverage.require_complete()
        calls = []
        def observe():
            result['stationary_feedback'] = True
        module.finalize_goal(result, True, lambda: calls.append('stop'), lambda: calls.append('cancel'),
                             observe, lambda: None, lambda: None, lambda: None, lambda: None)
        self.assertFalse(result['completed'])
        self.assertEqual(calls, ['stop', 'cancel'])

    def test_invalid_routes_are_rejected_without_ros(self):
        invalid = [[], [[0, 0, 0]], [[0, 0, 0]] * 21,
                   [[0, 0, 0], [0, 0, 1]],
                   [[0, 0, 0], [3.001, 0, 0]],
                   [[0, 0, 0], [1, 0, math.inf]],
                   [[0, 0, 0], [True, 0, 0]],
                   [[0, 0, 0], ['1', 0, 0]],
                   [[0, 0, 0], [1, 0]],
                   {'poses': [[0, 0, 0], [1, 0, 0]]},
                   [[0, 0, 0], [3, 0, 0], [0, 0, 0], [3, 0, 0], [0, 0, 0]]]
        for route in invalid:
            with self.subTest(route=route), self.assertRaises(ValueError):
                module.validate_map_route(route)

    def test_route_preview_and_destination_mutual_exclusion(self):
        route = [[100, -20, 0], [101, -20, .5]]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'route.json'
            path.write_text(json.dumps(route))
            p = subprocess.run([sys.executable, str(SCRIPT), '--route-file', str(path)],
                               text=True, capture_output=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            result = json.loads(p.stdout)
            self.assertEqual(result['route_requested'], route)
            self.assertEqual(result['action'], 'navigate_through_poses')
            self.assertIsNone(result['distance'])
            self.assertFalse(result['execute'])
            for extra in (['--distance', '1'], ['--target', '0', '1', '0']):
                p = subprocess.run([sys.executable, str(SCRIPT), '--route-file', str(path), *extra],
                                   text=True, capture_output=True)
                self.assertNotEqual(p.returncode, 0)
                self.assertIn('not allowed with argument', p.stderr)
            path.write_text('[[0,0,0],[10,0,0]]')
            p = subprocess.run([sys.executable, str(SCRIPT), '--route-file', str(path), '--execute'],
                               text=True, capture_output=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('invalid route file', p.stderr)
            self.assertNotIn('rclpy', p.stderr)

    def test_through_tree_matches_installed_jazzy_pipeline_and_bounded_recovery(self):
        tree = ET.parse(SCRIPT.parent / 'config/fishbot_passage_through_tree.xml')
        official = Path('/opt/ros/jazzy/share/nav2_bt_navigator/behavior_trees/'
                        'navigate_through_poses_w_replanning_and_recovery.xml')
        if official.exists():
            known_tags = {node.tag for node in ET.parse(official).iter()}
            self.assertTrue({node.tag for node in tree.iter()} <= known_tags)
        tags = [node.tag for node in tree.iter()]
        self.assertIn('ComputePathThroughPoses', tags)
        self.assertLess(tags.index('RemovePassedGoals'), tags.index('ComputePathThroughPoses'))
        self.assertNotIn('ComputePathToPose', tags)
        self.assertFalse({'Spin', 'BackUp', 'Wait'} & set(tags))
        self.assertEqual(tree.find('.//RecoveryNode').get('number_of_retries'), '1')
        self.assertEqual(tree.find('.//RemovePassedGoals').get('radius'), '0.1')

    def test_installed_jazzy_action_goal_serializes_route_and_single_pose(self):
        # This uses real generated message classes and CDR serialization. No node
        # or DDS participant is created; unavailable ROS installations skip it.
        code = '''import importlib.util, math
from nav2_msgs.action import NavigateThroughPoses, NavigateToPose
from geometry_msgs.msg import PoseStamped
from builtin_interfaces.msg import Time
from rclpy.serialization import serialize_message, deserialize_message
spec=importlib.util.spec_from_file_location('passage_goal', %r)
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
route=[(1.,2.,0.),(2.,3.,math.pi/2)]
g=m.make_navigation_goal(NavigateThroughPoses,PoseStamped,route,Time(sec=123),True)
g=deserialize_message(serialize_message(g),NavigateThroughPoses.Goal)
assert len(g.poses)==2 and g.poses[0].header.frame_id=='map'
assert g.poses[0].header.stamp.sec==123
assert g.poses[1].pose.position.y==3.
assert abs(g.poses[1].pose.orientation.z-math.sqrt(.5))<1e-12
assert g.behavior_tree.endswith('fishbot_passage_through_tree.xml')
f=NavigateThroughPoses.Feedback(current_pose=g.poses[0],number_of_poses_remaining=1)
f=deserialize_message(serialize_message(f),NavigateThroughPoses.Feedback)
e={}; coverage=m.RouteCoverage(route,e); coverage.observe(f,123.1); coverage.require_complete()
assert e['route_feedback_remaining']==1 and len(e['route_waypoint_visits'])==1
s=m.make_navigation_goal(NavigateToPose,PoseStamped,route[:1],Time(sec=123),False)
s=deserialize_message(serialize_message(s),NavigateToPose.Goal)
assert s.pose.pose.position.x==1.
assert s.behavior_tree.endswith('fishbot_passage_tree.xml')
''' % str(SCRIPT)
        setup = Path('/opt/ros/jazzy/setup.bash')
        if not setup.exists():
            self.skipTest('Jazzy generated messages not installed')
        p = subprocess.run(['bash', '-c', 'source /opt/ros/jazzy/setup.bash; exec /usr/bin/python3 -c "$1"',
                            'goal-message-check', code], text=True, capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_endpoint_follows_requested_heading(self):
        x, y, yaw = module.requested_endpoint(2, 3, math.pi/2, 1)
        self.assertAlmostEqual(x, 2)
        self.assertAlmostEqual(y, 4)
        self.assertAlmostEqual(yaw, math.pi/2)

    def test_invalid_inputs_fail(self):
        for distance in (0, -1, 4, math.nan, math.inf):
            with self.subTest(distance=distance), self.assertRaises(ValueError):
                module.requested_endpoint(0, 0, 0, distance)

    def test_map_target_is_bounded_relative_to_current_pose(self):
        # Absolute map coordinates can exceed three metres; only travel is bounded.
        self.assertEqual(module.requested_map_endpoint(100, -20, 1.2, (103, -20, -.4)),
                         (103, -20, -.4))
        self.assertEqual(module.requested_map_endpoint(2., 3., -.8, (2.5, 3.2, -2.4)),
                         (2.5, 3.2, -2.4))
        for target in ((100, -20, .5), (103.001, -20, 0), (102.2, -17.8, 0),
                       (math.nan, -20, 0), (101, -20, math.inf), (101, -20)):
            with self.subTest(target=target), self.assertRaises(ValueError):
                module.requested_map_endpoint(100, -20, 0, target)
        with self.assertRaises(ValueError):
            module.requested_map_endpoint(math.inf, -20, 0, (101, -20, 0))

    def test_map_target_preview_never_needs_ros(self):
        p = subprocess.run([sys.executable, str(SCRIPT), '--target', '100', '-20', '-.4'],
                           text=True, capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        result = json.loads(p.stdout)
        self.assertEqual(result['target_requested'], [100, -20, -.4])
        self.assertIsNone(result['distance'])
        self.assertFalse(result['execute'])

    def test_target_and_explicit_distance_cannot_be_combined(self):
        p = subprocess.run([sys.executable, str(SCRIPT), '--distance', '1',
                            '--target', '0', '1', '0'], text=True, capture_output=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('not allowed with argument', p.stderr)

    def test_nonfinite_target_fails_before_execute_joins_ros(self):
        for target in (('nan', '1', '0'), ('0', 'inf', '0'), ('0', '1', 'nan')):
            p = subprocess.run([sys.executable, str(SCRIPT), '--target', *target,
                                '--execute'], text=True, capture_output=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('map target coordinates and yaw must be finite', p.stderr)
            self.assertNotIn('rclpy', p.stderr)

    def test_default_does_not_need_ros(self):
        p = subprocess.run([sys.executable, str(SCRIPT)], text=True, capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('"execute": false', p.stdout)
        self.assertEqual(json.loads(p.stdout)['distance'], 1.0)

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

    @staticmethod
    def guard_diagnostic(message='healthy', level=0, received=10., stamp=100., name='fishbot_command_guard'):
        sec = math.floor(stamp)
        status = SimpleNamespace(name=name, level=level, message=message)
        msg = SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(
            sec=sec, nanosec=round((stamp-sec)*1e9))), status=[status])
        return [(received, msg)]

    def test_running_guard_rejects_latch_or_error_with_specific_cause(self):
        for message, level in [('latched: collision monitor stop', 0),
                               ('scan: missing', b'\x02'), ('source stale', 3)]:
            with self.subTest(message=message), self.assertRaisesRegex(RuntimeError, message):
                module.check_running_guard(self.guard_diagnostic(message, level), 10.1, 100.1)

    def test_running_guard_requires_receive_and_source_freshness(self):
        for diagnostics, steady_now, ros_now, cause in [
                ([], 10.1, 100.1, 'diagnostics missing'),
                (self.guard_diagnostic(), 11.001, 100.1, 'receive timeout'),
                (self.guard_diagnostic(), 10.1, 101.001, 'source timestamp'),
                (self.guard_diagnostic(), 10.1, 99.949, 'source timestamp'),
                (self.guard_diagnostic(name='other_guard'), 10.1, 100.1, 'status missing')]:
            with self.subTest(cause=cause), self.assertRaisesRegex(RuntimeError, cause):
                module.check_running_guard(diagnostics, steady_now, ros_now)
        for message, level in [('healthy', 0), ('priming: awaiting command', 1),
                               ('idle: command: expired zero', b'\x01')]:
            module.check_running_guard(self.guard_diagnostic(message, level), 10.1, 100.1)

    def test_action_wait_stops_on_guard_fault_before_progress_timeout(self):
        future, clock, calls = Future(), [10.], []
        diagnostics = self.guard_diagnostic()
        def spin():
            clock[0] += .05
            calls.append('spin')
            diagnostics[:] = self.guard_diagnostic('latched: collision monitor stop', 2,
                                                  received=clock[0], stamp=100.05)
        def check():
            module.check_running_guard(diagnostics, clock[0], 100. + clock[0] - 10.)
        with self.assertRaisesRegex(RuntimeError, 'collision monitor stop'):
            module.wait_action_future(future, 50., spin, check, lambda: clock[0], lambda: False)
        self.assertEqual(calls, ['spin'])
        self.assertLess(clock[0], 10.1)
        self.assertFalse(future.done())

    def test_action_wait_checks_guard_even_when_action_resolves_in_faulting_spin(self):
        future, clock = Future(), [10.]
        diagnostics = self.guard_diagnostic()
        def spin():
            clock[0] += .05
            future.resolve('nominal action result')
            diagnostics[:] = self.guard_diagnostic('latched: scan receive timeout', 2,
                                                  received=clock[0], stamp=100.05)
        with self.assertRaisesRegex(RuntimeError, 'scan receive timeout'):
            module.wait_action_future(future, 50., spin,
                lambda: module.check_running_guard(diagnostics, clock[0], 100.05),
                lambda: clock[0], lambda: False)

    def test_action_wait_healthy_result_and_deadline(self):
        future, clock, checks = Future(), [10.], []
        diagnostics = self.guard_diagnostic()
        def spin():
            clock[0] += .05
            future.resolve('completed')
        def check():
            checks.append(clock[0])
            module.check_running_guard(diagnostics, clock[0], 100. + clock[0] - 10.)
        answer = module.wait_action_future(future, 50., spin, check,
                                          lambda: clock[0], lambda: False)
        self.assertEqual(answer, 'completed')
        self.assertEqual(len(checks), 2)
        pending, clock = Future(), [10.]
        with self.assertRaises(TimeoutError):
            module.wait_action_future(pending, 10.1, lambda: clock.__setitem__(0, clock[0]+.05),
                                      lambda: None, lambda: clock[0], lambda: False)
        self.assertGreaterEqual(clock[0], 10.1)

    def test_action_wait_aborts_when_diagnostics_expire_during_navigation(self):
        future, clock = Future(), [10.]
        diagnostics = self.guard_diagnostic()
        def spin():
            clock[0] += .2
        with self.assertRaisesRegex(RuntimeError, 'diagnostics receive timeout'):
            module.wait_action_future(future, 50., spin,
                lambda: module.check_running_guard(diagnostics, clock[0], 100. + clock[0] - 10.),
                lambda: clock[0], lambda: False)
        self.assertLess(clock[0], 11.21)
        self.assertFalse(future.done())

    def test_guard_fault_enters_existing_stop_cancel_stationary_cleanup(self):
        result, calls = {'completed': False, 'stationary_feedback': False}, []
        def observe():
            calls.append('observe')
            result['stationary_feedback'] = True
        try:
            module.wait_action_future(Future(), 50., lambda: None,
                lambda: module.check_running_guard(self.guard_diagnostic('latched: collision monitor stop', 2),
                                                   10.1, 100.1),
                lambda: 10.1, lambda: False)
        except RuntimeError as exc:
            result['error'] = str(exc)
        finally:
            module.finalize_goal(result, True, lambda: calls.append('stop'), lambda: calls.append('cancel'),
                                 observe, lambda: calls.append('refresh'), lambda: calls.append('destroy'),
                                 lambda: calls.append('shutdown'), lambda: calls.append('record'))
        self.assertEqual(calls, ['stop', 'cancel', 'observe', 'refresh', 'destroy', 'shutdown', 'record'])
        self.assertTrue(result['stationary_feedback'])
        self.assertIn('collision monitor stop', result['error'])

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
