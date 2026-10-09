"""Offline command-guard behavior tests: no ROS nodes, ports or devices.

Run: python3 -B tools/tests/test_command_guard.py
Source /opt/ros/jazzy/setup.bash to include the real-message serialization test.
"""

import ast
from copy import deepcopy
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'fishbot_command_guard.py'
spec = importlib.util.spec_from_file_location('fishbot_command_guard_under_test', SOURCE)
guard_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guard_module
spec.loader.exec_module(guard_module)


def config():
    return {'frames': {'base': 'base_footprint', 'odom': 'odom'},
            'motion': {'max_linear_mps': 0.08, 'max_angular_rps': 0.25},
            'footprint': {'points_m': [[0.1, 0.12], [-0.1, 0.12], [-0.1, -0.12], [0.1, -0.12]]},
            'command_guard': {'profile': 'official-model-unmeasured', 'ring_capacity': 8}}


def odom():
    return {'frame_id': 'odom', 'child_frame_id': 'base_footprint', 'position': [0.0, 0.0, 0.0],
            'orientation': [0.0, 0.0, 0.0, 1.0], 'linear': [0.0, 0.0, 0.0], 'angular': [0.0, 0.0, 0.0]}


def scan():
    return {'frame_id': 'laser_link', 'angle_min': -math.pi, 'angle_increment': 2*math.pi/360,
            'range_min': 0.01, 'range_max': 8.0, 'ranges': [2.0] * 360}


def transform():
    return {'translation': [0.0, 0.0, 0.0], 'rotation': [0.0, 0.0, 0.0, 1.0]}


def sensors(core, ros=100.0, steady=10.0):
    core.accept_odom(odom(), ros, ros, steady)
    core.accept_scan(scan(), transform(), ros, ros, steady)
    core.set_ownership({'candidate_publishers': ['collision_monitor'],
                        'final_publishers': ['fishbot_command_guard'],
                        'final_subscribers': ['fishbot_motion_control']}, None)


def command(core, v=0.0, w=0.0, ros=100.0, steady=10.0, stamp=None):
    core.accept_command([v, 0.0, 0.0, 0.0, 0.0, w], ros if stamp is None else stamp, ros, steady)


def ready_core():
    core = guard_module.CommandGuard(guard_module.Settings.from_mapping(config()))
    sensors(core)
    command(core)
    assert core.tick(100.0, 10.0) == guard_module.ZERO and core.armed
    return core


class CommandGuardTests(unittest.TestCase):
    def test_dry_run_default_and_ros_sim_arguments_are_explicit(self):
        argv = ['--config', 'geometry.yaml', '--output-dir', 'private-run']
        args, ros_args = guard_module.parse_arguments(argv)
        self.assertFalse(args.execute)
        self.assertIsNone(args.output_stamped)
        args, ros_args = guard_module.parse_arguments(argv + [
            '--execute', '--output-stamped', '--expected-subscriber', 'diff_drive_controller',
            '--ros-args', '-p', 'use_sim_time:=true'])
        self.assertTrue(args.execute)
        self.assertTrue(args.output_stamped)
        self.assertEqual(ros_args, ['--ros-args', '-p', 'use_sim_time:=true'])

    def test_diagnostic_levels_serialize_with_real_installed_ros_messages(self):
        try:
            from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus
            from rclpy.serialization import serialize_message
        except ModuleNotFoundError:
            self.skipTest('source /opt/ros/jazzy/setup.bash for installed ROS message serialization')
        tree = ast.parse(SOURCE.read_text())
        assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Attribute) and ast.unparse(target) == 'status.level'
                               for target in node.targets)]
        self.assertEqual(len(assignments), 1)
        for level in (0, 1, 2):
            with self.subTest(level=level):
                status = DiagnosticStatus()
                exec(compile(ast.Module(body=assignments, type_ignores=[]), str(SOURCE), 'exec'),
                     {'status': status, 'level': level})
                message = DiagnosticArray(status=[status])
                self.assertTrue(serialize_message(message))
                self.assertEqual(status.level, bytes([level]))

    def test_shared_motion_limits_and_output_overrides_are_validated(self):
        settings = guard_module.Settings.from_mapping(config(), output_stamped=True,
                                                       expected_final_subscribers=['diff_drive_controller'])
        self.assertTrue(settings.output_stamped)
        self.assertEqual(settings.expected_final_subscribers, ('diff_drive_controller',))
        for key, value in (('max_linear_speed', 0.09), ('command_timeout_s', 0.26),
                           ('ring_capacity', 10000)):
            document = config()
            document['command_guard'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                guard_module.Settings.from_mapping(document)
        with self.assertRaises(ValueError):
            guard_module.Settings.from_mapping(config(), output_topic='/cmd_vel_safe_candidate')

    def test_priming_zeros_do_not_latch_or_replay_a_rejected_moving_command(self):
        core = guard_module.CommandGuard(guard_module.Settings.from_mapping(config()))
        command(core, v=0.04)
        self.assertEqual(core.tick(100.0, 10.0), guard_module.ZERO)
        self.assertIsNone(core.latched_reason)
        self.assertNotIn('command', core.latest)
        sensors(core, 100.05, 10.05)
        self.assertEqual(core.tick(100.05, 10.05), guard_module.ZERO)
        self.assertFalse(core.armed)
        command(core, ros=100.05, steady=10.05)
        core.tick(100.05, 10.05)
        self.assertTrue(core.armed)

    def test_healthy_latest_candidate_passes_forward_reverse_and_rotation(self):
        core = ready_core()
        for v, w in ((0.08, 0.0), (-0.03, 0.0), (0.03, -0.25), (0.0, 0.25), (0.0, 0.0)):
            with self.subTest(v=v, w=w):
                command(core, v, w)
                self.assertEqual(core.tick(100.0, 10.0), (v, w))
        self.assertEqual(len([key for key in core.latest if key == 'command']), 1)

    def test_nonzero_command_expiry_latches_and_new_commands_cannot_resume_it(self):
        core = ready_core()
        command(core, 0.04)
        self.assertEqual(core.tick(100.0, 10.0), (0.04, 0.0))
        sensors(core, 100.251, 10.251)
        self.assertEqual(core.tick(100.251, 10.251), guard_module.ZERO)
        self.assertIn('command: receive timeout', core.latched_reason)
        command(core, 0.04, ros=100.251, steady=10.251)
        self.assertEqual(core.tick(100.251, 10.251), guard_module.ZERO)
        self.assertEqual(len(core.events), 1)

    def test_zero_command_expiry_is_idle_not_a_permanent_collision_stop(self):
        core = ready_core()
        sensors(core, 100.3, 10.3)
        self.assertEqual(core.tick(100.3, 10.3), guard_module.ZERO)
        self.assertIsNone(core.latched_reason)
        command(core, 0.03, ros=100.3, steady=10.3)
        self.assertEqual(core.tick(100.3, 10.3), (0.03, 0.0))

    def test_steady_age_expires_even_when_ros_simulation_clock_is_paused(self):
        core = ready_core()
        command(core, 0.03)
        sensors(core, 100.0, 10.251)
        self.assertEqual(core.tick(100.0, 10.251), guard_module.ZERO)
        self.assertIn('command: receive timeout', core.latched_reason)

    def test_future_and_invalid_zero_command_stamps_are_rejected_on_arrival(self):
        for stamp in (100.051, math.nan, math.inf, None):
            with self.subTest(stamp=stamp):
                core = ready_core()
                core.accept_command([0.0] * 6, stamp, 100.0, 10.0)
                self.assertEqual(core.tick(100.0, 10.0), guard_module.ZERO)
                self.assertIn('source timestamp', core.latched_reason)
                json.dumps(core.events[-1], allow_nan=False)

    def test_old_smoother_zero_after_reset_expires_to_idle_without_refresh_or_relatch(self):
        core = ready_core()
        core.latch('operator/task stop', 100.0, 10.0)
        command(core)
        self.assertTrue(core.reset(100.0, 10.0)[0])
        sensors(core, 100.258, 10.258)
        command(core, ros=100.258, steady=10.258, stamp=100.0)
        self.assertEqual(core.latest['command']['source_stamp'], 100.0)
        self.assertIsNone(core.latest['command']['error'])
        self.assertEqual(core.tick(100.258, 10.258), guard_module.ZERO)
        self.assertIsNone(core.latched_reason)
        self.assertNotIn('command', core.latest)
        self.assertEqual(len(core.events), 1)
        command(core, 0.03, ros=100.258, steady=10.258)
        self.assertEqual(core.tick(100.258, 10.258), (0.03, 0.0))

    def test_expired_nonzero_translation_or_rotation_still_latches(self):
        for v, w in ((0.03, 0.0), (0.0, -0.06)):
            with self.subTest(v=v, w=w):
                core = ready_core()
                command(core, v, w, stamp=99.749)
                self.assertEqual(core.latest['command']['source_stamp'], 99.749)
                self.assertEqual(core.tick(100.0, 10.0), guard_module.ZERO)
                self.assertIn('source timestamp', core.latched_reason)

    def test_command_age_and_future_tolerance_boundaries(self):
        for stamp in (99.75, 100.05):
            core = ready_core()
            command(core, 0.03, stamp=stamp)
            self.assertEqual(core.tick(100.0, 10.0), (0.03, 0.0))

    def test_nonfinite_unsupported_axes_and_excessive_commands_fail_closed(self):
        for values in ([math.nan, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, math.inf],
                       [0.03, 0.01, 0, 0, 0, 0], [0.081, 0, 0, 0, 0, 0],
                       [0, 0, 0, 0, 0, -0.251], []):
            with self.subTest(values=values):
                core = ready_core()
                core.accept_command(values, 100.0, 100.0, 10.0)
                self.assertEqual(core.tick(100.0, 10.0), guard_module.ZERO)
                self.assertIn('command: malformed', core.latched_reason)

    def test_native_odom_and_scan_age_limits_and_future_stamps_latch(self):
        for kind, payload, limit in (('odom', odom(), 0.25), ('scan', scan(), 0.5)):
            for stamp in (100.0-limit-0.001, 100.051):
                with self.subTest(kind=kind, stamp=stamp):
                    core = ready_core()
                    if kind == 'odom':
                        core.accept_odom(payload, stamp, 100.0, 10.0)
                    else:
                        core.accept_scan(payload, transform(), stamp, 100.0, 10.0)
                    self.assertEqual(core.tick(100.0, 10.0), guard_module.ZERO)
                    self.assertTrue(core.latched_reason.startswith(kind + ': source stamp'))

    def test_sensor_receive_timeout_latches_even_while_command_is_zero(self):
        core = ready_core()
        self.assertEqual(core.tick(100.0, 10.251), guard_module.ZERO)
        self.assertEqual(core.latched_reason, 'odom: receive timeout')

    def test_bad_odom_frame_quaternion_or_velocity_cannot_arm_or_pass(self):
        for key, value in (('frame_id', 'station_odom'), ('child_frame_id', 'unknown'),
                           ('orientation', [0, 0, 0, 0]), ('linear', [math.nan, 0, 0])):
            with self.subTest(key=key):
                core = ready_core()
                raw = odom()
                raw[key] = value
                core.accept_odom(raw, 100.0, 100.0, 10.0)
                self.assertEqual(core.tick(100.0, 10.0), guard_module.ZERO)
                self.assertIn('odom: malformed', core.latched_reason)

    def test_scan_uses_supplied_tf_rotation_and_translation_without_model_fallback(self):
        tf = {'translation': [1.0, 2.0, 0.0],
              'rotation': [0, 0, math.sin(math.pi/4), math.cos(math.pi/4)]}
        data = guard_module.project_scan(scan(), tf)
        front = data['points_base'][180]
        self.assertAlmostEqual(front['x'], 1.0)
        self.assertAlmostEqual(front['y'], 4.0)
        with self.assertRaisesRegex(ValueError, 'TF unavailable'):
            guard_module.project_scan(scan(), None)

    def test_invalid_scan_metadata_coverage_or_tf_latches(self):
        for scenario in ('no tf', 'zero increment', 'empty', 'infinite', 'oversized'):
            with self.subTest(scenario=scenario):
                core, raw, tf = ready_core(), scan(), transform()
                if scenario == 'no tf':
                    tf = None
                elif scenario == 'zero increment':
                    raw['angle_increment'] = 0
                elif scenario == 'empty':
                    raw['ranges'] = []
                elif scenario == 'infinite':
                    raw['ranges'] = [math.inf] * 360
                else:
                    raw['ranges'] = [2.0] * 5000
                core.accept_scan(raw, tf, 100.0, 100.0, 10.0)
                self.assertEqual(core.tick(100.0, 10.0), guard_module.ZERO)
                self.assertIn('scan: malformed', core.latched_reason)
                self.assertLessEqual(len(core.latest['scan']['data']['ranges']), guard_module.MAX_SCAN_POINTS)

    def test_graph_rejects_duplicate_final_publisher_and_wrong_candidate_or_receiver(self):
        settings = guard_module.Settings.from_mapping(config())
        graph = {'candidate_publishers': ['collision_monitor'], 'final_publishers': ['fishbot_command_guard'],
                 'final_subscribers': ['fishbot_motion_control']}
        self.assertIsNone(guard_module.ownership_reason(graph, settings, 'fishbot_command_guard', True))
        for key, value in (('candidate_publishers', ['teleop']),
                           ('final_publishers', ['fishbot_command_guard', 'teleop']),
                           ('final_subscribers', [])):
            broken = {**graph, key: value}
            issue = guard_module.ownership_reason(broken, settings, 'fishbot_command_guard', True)
            core = ready_core()
            core.set_ownership(broken, issue)
            self.assertEqual(core.tick(100.0, 10.0), guard_module.ZERO)
            self.assertEqual(core.latched_reason, issue)
        graph['final_publishers'] = []
        self.assertIsNone(guard_module.ownership_reason(graph, settings, 'fishbot_command_guard', False))

    def test_collision_stop_records_once_and_clear_requires_a_new_candidate(self):
        core = ready_core()
        command(core, 0.04)
        core.accept_collision_state(1, 'passage_stop', 100.0, 10.0)
        self.assertEqual(core.tick(100.0, 10.0), guard_module.ZERO)
        self.assertIsNone(core.latched_reason)
        self.assertEqual(core.events[-1]['kind'], 'collision_stop')
        self.assertEqual(core.events[-1]['latest']['command']['data']['twist'][0], 0.04)
        self.assertIn('collision monitor stop', core.status)
        core.accept_collision_state(1, 'passage_stop', 100.0, 10.0)
        self.assertEqual(len(core.events), 1)
        command(core)
        sensors(core, 100.3, 10.3)
        self.assertEqual(core.tick(100.3, 10.3), guard_module.ZERO)
        self.assertIsNone(core.latched_reason)
        core.accept_collision_state(0, '', 100.3, 10.3)
        self.assertEqual(core.tick(100.3, 10.3), guard_module.ZERO)
        command(core, 0.03, ros=100.3, steady=10.3)
        self.assertEqual(core.tick(100.3, 10.3), (0.03, 0.0))

    def test_invalid_collision_source_is_a_health_latch(self):
        core = ready_core()
        core.accept_collision_state(1, 'invalid source', 100.0, 10.0)
        self.assertEqual(core.tick(100.0, 10.0), guard_module.ZERO)
        self.assertEqual(core.latched_reason, 'collision monitor invalid source')

    def test_operator_stop_requires_explicit_reset_and_fresh_zero_then_new_command(self):
        core = ready_core()
        core.latch('operator/task stop', 100.0, 10.0)
        command(core, 0.04)
        self.assertEqual(core.tick(100.0, 10.0), guard_module.ZERO)
        self.assertFalse(core.reset(100.0, 10.0)[0])
        command(core)
        self.assertTrue(core.reset(100.0, 10.0)[0])
        self.assertNotIn('command', core.latest)
        self.assertEqual(core.tick(100.0, 10.0), guard_module.ZERO)
        command(core, 0.03)
        self.assertEqual(core.tick(100.0, 10.0), (0.03, 0.0))

    def test_reset_rejects_stale_zero_or_unhealthy_sensors(self):
        core = ready_core()
        core.latch('operator/task stop', 100.0, 10.0)
        sensors(core, 100.3, 10.3)
        self.assertFalse(core.reset(100.3, 10.3)[0])
        command(core, ros=100.3, steady=10.3)
        core.set_ownership({}, 'final publisher ownership mismatch')
        self.assertFalse(core.reset(100.3, 10.3)[0])

    def test_snapshot_is_bounded_immutable_has_native_ages_geometry_and_nonfinite_safe_json(self):
        core = ready_core()
        raw = scan()
        raw['ranges'][0] = math.inf
        for index in range(20):
            core.accept_scan(raw, transform(), 100.0, 100.0, 10.0)
        core.zones['stop_polygon'] = {'frame_id': 'base_footprint', 'points': [[0.1, 0.1, 0.0]]}
        command(core, 0.03)
        core.latch('test failure', 100.1, 10.1)
        event = core.events[-1]
        self.assertEqual(len(event['ring']), 8)
        self.assertAlmostEqual(event['latest']['scan']['source_age_s'], 0.1)
        self.assertAlmostEqual(event['latest']['scan']['receive_age_s'], 0.1)
        self.assertIn('footprint', event['geometry'])
        self.assertIn('stop_polygon', event['zones'])
        self.assertIsNone(event['latest']['scan']['data']['ranges'][0])
        self.assertEqual(event['latest']['command']['data']['twist'][0], 0.03)
        raw['ranges'][1] = 7.0
        core.accept_scan(raw, transform(), 100.1, 100.1, 10.1)
        self.assertEqual(event['latest']['scan']['data']['ranges'][1], 2.0)
        self.assertEqual(core.latest['scan']['data']['ranges'][1], 7.0)
        json.dumps(event, allow_nan=False)

    def test_first_zero_precedes_scan_materialization_for_fault_stop_and_collision_callbacks(self):
        tree = ast.parse(SOURCE.read_text())
        node_class = next(item for item in ast.walk(tree)
                          if isinstance(item, ast.ClassDef) and item.name == 'GuardNode')
        functions = [item for item in node_class.body if isinstance(item, ast.FunctionDef)
                     and item.name in ('evaluate', 'on_stop', 'on_collision')]
        namespace = {'ZERO': guard_module.ZERO}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), 'exec'), namespace)
        original_copy, original_safe = guard_module.deepcopy, guard_module.json_safe
        for path in ('health fault', 'operator stop', 'collision stop'):
            with self.subTest(path=path):
                core, actions = ready_core(), []
                command(core, 0.03)
                event_time = (100.251, 10.251) if path == 'health fault' else (100.0, 10.0)

                def guarded_copy(value, *args, **kwargs):
                    if isinstance(value, dict) and value.get('kind') == 'scan':
                        self.assertTrue(actions, 'scan deepcopy happened before first zero')
                    return original_copy(value, *args, **kwargs)

                def guarded_safe(value):
                    if isinstance(value, dict) and 'ring' in value:
                        self.assertTrue(actions, 'snapshot materialized before first zero')
                        self.assertEqual(actions[0], ('publish', guard_module.ZERO))
                    return original_safe(value)

                recorded = []

                def submit(event):
                    # Simulate the disk worker materializing the captured snapshot.
                    recorded.append(guard_module.json_safe(event))
                    actions.append(('record', event['kind']))

                node = NS(guard=core, times=lambda: event_time, update_ownership=lambda: None,
                          recorder=NS(error=None, submit=submit), last_diagnostic=event_time[1],
                          publish_velocity=lambda value: actions.append(('publish', value)),
                          publish_trigger=lambda event: actions.append(('markers', event['kind'])))
                node.evaluate = lambda: namespace['evaluate'](node)
                with patch.object(guard_module, 'deepcopy', side_effect=guarded_copy), \
                        patch.object(guard_module, 'json_safe', side_effect=guarded_safe):
                    if path == 'health fault':
                        node.evaluate()
                    elif path == 'operator stop':
                        namespace['on_stop'](node, None, NS())
                    else:
                        namespace['on_collision'](node, NS(action_type=1, polygon_name='passage_stop'))
                self.assertEqual(actions[0], ('publish', guard_module.ZERO))
                self.assertTrue(recorded)
                self.assertEqual(recorded[0]['latest']['command']['data']['twist'][0], 0.03)
                self.assertEqual(recorded[0]['ros_time'], event_time[0])

    def test_trigger_file_is_private_and_cannot_overwrite_an_existing_event(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(guard_module.uuid, 'uuid4', return_value=NS(hex='fixed')):
                path = guard_module.write_snapshot(directory, {'distance': math.inf, 'value': 1})
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(json.loads(path.read_text()), {'distance': None, 'value': 1})
                with self.assertRaises(FileExistsError):
                    guard_module.write_snapshot(directory, {'value': 2})
                self.assertEqual(json.loads(path.read_text())['value'], 1)

    def test_stopped_markers_clear_on_successful_reset_and_before_first_resumed_velocity(self):
        tree = ast.parse(SOURCE.read_text())
        node_class = next(item for item in ast.walk(tree)
                          if isinstance(item, ast.ClassDef) and item.name == 'GuardNode')
        methods = [item for item in node_class.body if isinstance(item, ast.FunctionDef)
                   and item.name in ('clear_trigger_markers', 'publish_velocity', 'on_reset')]

        class Marker:
            DELETEALL = 3

        namespace = {'ZERO': guard_module.ZERO, 'Marker': Marker,
                     'MarkerArray': lambda: NS(markers=[]),
                     'Twist': lambda: NS(linear=NS(x=0.0), angular=NS(z=0.0)),
                     'settings': NS(output_stamped=False)}
        exec(compile(ast.Module(body=methods, type_ignores=[]), str(SOURCE), 'exec'), namespace)
        actions = []
        core = ready_core()
        core.latch('operator/task stop', 100.0, 10.0)
        node = NS(guard=core, recorder=NS(error=None), times=lambda: (100.0, 10.0),
                  update_ownership=lambda: None, trigger_markers_visible=True,
                  markers=NS(publish=lambda msg: actions.append(('markers', msg.markers[0].action))),
                  publisher=NS(publish=lambda msg: actions.append(('velocity', msg.linear.x, msg.angular.z))))
        node.publish_velocity = lambda velocity: namespace['publish_velocity'](node, velocity)
        node.clear_trigger_markers = lambda: namespace['clear_trigger_markers'](node)
        event_count = len(core.events)
        response = namespace['on_reset'](node, None, NS())
        self.assertTrue(response.success)
        self.assertEqual(actions, [('velocity', 0.0, 0.0), ('markers', Marker.DELETEALL)])
        self.assertFalse(node.trigger_markers_visible)
        self.assertEqual(len(core.events), event_count)  # JSON history remains available.
        actions.clear()
        node.trigger_markers_visible = True  # A normal CM stop can later resume without reset.
        node.publish_velocity(guard_module.ZERO)
        self.assertTrue(node.trigger_markers_visible)
        node.publish_velocity((0.03, 0.0))
        node.publish_velocity((0.03, 0.0))
        self.assertEqual(actions, [('velocity', 0.0, 0.0), ('markers', Marker.DELETEALL),
                                   ('velocity', 0.03, 0.0), ('velocity', 0.03, 0.0)])
        node.trigger_markers_visible = True
        command(core, 0.03)
        actions.clear()
        response = namespace['on_reset'](node, None, NS())
        self.assertFalse(response.success)
        self.assertTrue(node.trigger_markers_visible)
        self.assertEqual(actions, [('velocity', 0.0, 0.0)])

    def test_recorder_rejects_public_directory_and_reports_write_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, 0o755)
            with self.assertRaisesRegex(ValueError, 'private'):
                guard_module.TriggerRecorder(directory)
            os.chmod(directory, 0o700)
            with patch.object(guard_module, 'write_snapshot', side_effect=OSError('disk full')):
                recorder = guard_module.TriggerRecorder(directory)
                recorder.submit({'test': True})
                recorder.pending.join()
                self.assertIn('disk full', recorder.error)
                recorder.close()


class TolerantTimingTests(unittest.TestCase):
    def ready(self):
        core = guard_module.CommandGuard(guard_module.Settings.from_mapping(config(), timing_profile='tolerant'))
        sensors(core)
        command(core)
        self.assertEqual(core.tick(100.0, 10.0), guard_module.ZERO)
        self.assertTrue(core.armed)
        return core

    def stale_odom(self, core, ros=100.0, steady=10.0):
        core.accept_odom(odom(), ros - 0.351, ros, steady)
        self.assertEqual(core.tick(ros, steady), guard_module.ZERO)

    def recover(self, core):
        sensors(core, 100.1, 10.1)
        command(core, 0.04, ros=100.1, steady=10.1)
        self.assertEqual(core.tick(100.1, 10.1), guard_module.ZERO)
        sensors(core, 100.3, 10.3)
        command(core, 0.04, ros=100.3, steady=10.3)
        self.assertEqual(core.tick(100.3, 10.3), guard_module.ZERO)
        self.assertIsNone(core.hold_started)
        self.assertNotIn('command', core.latest)

    def test_cli_is_explicit_and_effective_geometry_preserves_footprint(self):
        argv = ['--config', 'geometry.yaml', '--output-dir', 'private-run']
        self.assertEqual(guard_module.parse_arguments(argv)[0].timing_profile, 'strict')
        self.assertEqual(guard_module.parse_arguments(argv + ['--timing-profile', 'tolerant'])[0].timing_profile,
                         'tolerant')
        document = config()
        settings = guard_module.Settings.from_mapping(document, timing_profile='tolerant')
        self.assertEqual((settings.command_timeout_s, settings.odom_timeout_s), (0.35, 0.35))
        self.assertEqual(settings.geometry['footprint'], document['footprint'])
        self.assertEqual(settings.geometry['command_guard']['timing_profile'], 'tolerant')
        self.assertNotIn('timing_profile', document['command_guard'])
        with self.assertRaises(ValueError):
            guard_module.Settings.from_mapping(document, timing_profile='disabled')

    def test_short_stale_odom_recovers_only_on_new_post_recovery_candidate(self):
        core = self.ready()
        command(core, 0.04)
        self.stale_odom(core)
        self.assertIsNone(core.latched_reason)
        self.assertTrue(core.status.startswith('timing hold:'))
        self.assertNotIn('command', core.latest)
        self.recover(core)
        # A queued command can arrive after recovery and still be too old to authorize motion.
        command(core, 0.04, ros=100.31, steady=10.31, stamp=100.29)
        self.assertEqual(core.tick(100.31, 10.31), guard_module.ZERO)
        command(core, 0.04, ros=100.31, steady=10.31)
        self.assertEqual(core.tick(100.31, 10.31), (0.04, 0.0))

    def test_old_nonzero_command_is_a_soft_hold_but_never_executed(self):
        core = self.ready()
        command(core, 0.04, stamp=99.649)
        self.assertIsNone(core.latest['command']['error'])
        self.assertEqual(core.tick(100.0, 10.0), guard_module.ZERO)
        self.assertIsNone(core.latched_reason)
        self.assertTrue(core.hold_needs_command)
        self.recover(core)
        command(core, 0.04, ros=100.31, steady=10.31)
        self.assertEqual(core.tick(100.31, 10.31), (0.04, 0.0))

    def test_source_age_tolerance_is_bounded_at_350ms(self):
        core = self.ready()
        core.accept_odom(odom(), 99.65, 100.0, 10.0)
        command(core, 0.04, stamp=99.65)
        self.assertEqual(core.tick(100.0, 10.0), (0.04, 0.0))
        self.stale_odom(core)
        self.assertIsNone(core.latched_reason)

    def test_future_command_and_ownership_fault_cannot_hide_behind_old_odom(self):
        for fault in ('future', 'ownership'):
            with self.subTest(fault=fault):
                core = self.ready()
                core.accept_odom(odom(), 99.0, 100.0, 10.0)
                if fault == 'future':
                    command(core, 0.04, stamp=100.051)
                else:
                    core.set_ownership({}, 'final publisher ownership mismatch')
                self.assertEqual(core.tick(100.0, 10.0), guard_module.ZERO)
                self.assertIsNotNone(core.latched_reason)
                self.assertIn('source timestamp' if fault == 'future' else 'ownership', core.latched_reason)

    def test_future_sensor_stamp_cannot_hide_behind_receive_timeout(self):
        core = self.ready()
        core.accept_scan(scan(), transform(), 101.0, 100.0, 10.0)
        self.assertEqual(core.tick(100.0, 10.7), guard_module.ZERO)
        self.assertEqual(core.latched_reason, 'scan: source stamp in future')

    def test_continuous_odom_failure_latches_after_two_seconds(self):
        core = self.ready()
        command(core, 0.04)
        self.assertEqual(core.tick(100.0, 10.0), (0.04, 0.0))
        self.stale_odom(core)
        sensors(core, 102.0, 12.0)
        core.accept_odom(odom(), 99.0, 102.0, 12.0)
        self.assertEqual(core.tick(102.0, 12.0), guard_module.ZERO)
        self.assertIn('persistent timing fault: odom:', core.latched_reason)

    def test_deleted_command_does_not_delete_outage_timer(self):
        core = self.ready()
        command(core, 0.04)
        self.assertEqual(core.tick(100.0, 10.0), (0.04, 0.0))
        sensors(core, 100.351, 10.351)
        self.assertEqual(core.tick(100.351, 10.351), guard_module.ZERO)
        self.assertNotIn('command', core.latest)
        self.assertTrue(core.hold_needs_command)
        sensors(core, 102.351, 12.351)
        self.assertEqual(core.tick(102.351, 12.351), guard_module.ZERO)
        self.assertIn('persistent timing fault: command:', core.latched_reason)

    def test_idle_long_sensor_gap_recovers_without_latch_or_queued_motion(self):
        for source in ('scan', 'odom'):
            with self.subTest(source=source):
                core = self.ready()

                def fault(ros, steady):
                    sensors(core, ros, steady)
                    if source == 'scan':
                        core.accept_scan(scan(), transform(), ros - 1.0, ros, steady)
                    else:
                        core.accept_odom(odom(), ros - 1.0, ros, steady)

                fault(100.0, 10.0)
                self.assertEqual(core.tick(100.0, 10.0), guard_module.ZERO)
                fault(104.0, 14.0)
                command(core, 0.04, ros=104.0, steady=14.0)
                self.assertEqual(core.tick(104.0, 14.0), guard_module.ZERO)
                self.assertIsNone(core.latched_reason)
                self.assertFalse(core.motion_active)
                self.assertFalse(core.hold_motion)
                self.assertNotIn('command', core.latest)
                for ros, steady in ((105.0, 15.0), (105.2, 15.2)):
                    sensors(core, ros, steady)
                    command(core, 0.04, ros=ros, steady=steady)
                    self.assertEqual(core.tick(ros, steady), guard_module.ZERO)
                self.assertIsNone(core.hold_started)
                self.assertEqual(core.tick(105.21, 15.21), guard_module.ZERO)
                command(core, 0.04, ros=105.21, steady=15.21, stamp=105.19)
                self.assertEqual(core.tick(105.21, 15.21), guard_module.ZERO)
                command(core, 0.04, ros=105.21, steady=15.21)
                self.assertEqual(core.tick(105.21, 15.21), (0.04, 0.0))

    def test_active_scan_gap_latches_despite_fresh_zero_during_hold(self):
        core = self.ready()
        command(core, 0.04)
        self.assertEqual(core.tick(100.0, 10.0), (0.04, 0.0))
        core.accept_scan(scan(), transform(), 99.0, 100.0, 10.0)
        self.assertEqual(core.tick(100.0, 10.0), guard_module.ZERO)
        for ros, steady in ((100.1, 10.1), (102.0, 12.0)):
            core.accept_odom(odom(), ros, ros, steady)
            command(core, ros=ros, steady=steady)
            self.assertEqual(core.tick(ros, steady), guard_module.ZERO)
        self.assertTrue(core.motion_active)
        self.assertTrue(core.hold_motion)
        self.assertIn('persistent timing fault: scan:', core.latched_reason)

    def test_fresh_residual_odom_motion_keeps_zero_output_active(self):
        core = self.ready()
        moving = odom()
        moving['linear'][0] = 0.01
        core.accept_odom(moving, 100.0, 100.0, 10.0)
        self.assertEqual(core.tick(100.0, 10.0), guard_module.ZERO)
        self.assertTrue(core.motion_active)
        core.latch('operator/task stop', 100.0, 10.0)
        command(core)
        self.assertTrue(core.reset(100.0, 10.0)[0])
        self.assertTrue(core.motion_active)
        self.stale_odom(core)
        sensors(core, 102.0, 12.0)
        core.accept_odom(odom(), 99.0, 102.0, 12.0)
        self.assertEqual(core.tick(102.0, 12.0), guard_module.ZERO)
        self.assertIn('persistent timing fault: odom:', core.latched_reason)

    def test_fresh_zero_and_stationary_odom_retire_motion_before_an_idle_gap(self):
        core = self.ready()
        command(core, 0.04)
        self.assertEqual(core.tick(100.0, 10.0), (0.04, 0.0))
        sensors(core, 100.1, 10.1)
        command(core, ros=100.1, steady=10.1)
        self.assertEqual(core.tick(100.1, 10.1), guard_module.ZERO)
        self.assertFalse(core.motion_active)
        self.stale_odom(core, 100.2, 10.2)
        core.accept_scan(scan(), transform(), 104.0, 104.0, 14.0)
        self.assertEqual(core.tick(104.0, 14.0), guard_module.ZERO)
        self.assertIsNone(core.latched_reason)

    def test_zero_requires_stationary_odom_received_and_stamped_after_passed_motion(self):
        core = self.ready()
        command(core, 0.04)
        self.assertEqual(core.tick(100.0, 10.0), (0.04, 0.0))
        command(core, ros=100.1, steady=10.1)
        self.assertEqual(core.tick(100.1, 10.1), guard_module.ZERO)
        self.assertTrue(core.motion_active)  # Last odom preceded the moving output.
        core.accept_odom(odom(), 99.99, 100.1, 10.1)
        self.assertEqual(core.tick(100.1, 10.1), guard_module.ZERO)
        self.assertTrue(core.motion_active)  # A later delivery of older source feedback is insufficient.
        core.accept_odom(odom(), 100.1, 100.1, 10.1)
        self.assertEqual(core.tick(100.1, 10.1), guard_module.ZERO)
        self.assertFalse(core.motion_active)

    def test_preoutput_stationary_odom_and_later_zero_cannot_downgrade_scan_hold(self):
        core = self.ready()
        command(core, 0.04)
        self.assertEqual(core.tick(100.0, 10.0), (0.04, 0.0))
        command(core, ros=100.1, steady=10.1)
        core.accept_scan(scan(), transform(), 99.0, 100.1, 10.1)
        self.assertEqual(core.tick(100.1, 10.1), guard_module.ZERO)
        self.assertTrue(core.hold_motion)
        core.accept_odom(odom(), 102.1, 102.1, 12.1)
        command(core, ros=102.1, steady=12.1)
        self.assertEqual(core.tick(102.1, 12.1), guard_module.ZERO)
        self.assertIn('persistent timing fault: scan:', core.latched_reason)

    def test_desired_zero_cannot_retire_a_passed_moving_command(self):
        core = self.ready()
        command(core, 0.04)
        self.assertEqual(core.tick(100.0, 10.0), (0.04, 0.0))
        core.accept_command([0.0] * 6, 100.0, 100.0, 10.0, desired=True)
        self.stale_odom(core)
        sensors(core, 102.0, 12.0)
        core.accept_odom(odom(), 99.0, 102.0, 12.0)
        self.assertEqual(core.tick(102.0, 12.0), guard_module.ZERO)
        self.assertIsNotNone(core.latched_reason)

    def test_long_idle_sensor_wait_still_latches_hard_faults(self):
        for fault in ('future', 'malformed', 'ownership', 'operator'):
            with self.subTest(fault=fault):
                core = self.ready()
                self.stale_odom(core)
                self.assertEqual(core.tick(104.0, 14.0), guard_module.ZERO)
                self.assertIsNone(core.latched_reason)
                if fault == 'future':
                    command(core, ros=104.0, steady=14.0, stamp=104.051)
                elif fault == 'malformed':
                    core.accept_command([math.nan, 0, 0, 0, 0, 0], 104.0, 104.0, 14.0)
                elif fault == 'ownership':
                    core.set_ownership({}, 'final publisher ownership mismatch')
                else:
                    core.latch('operator/task stop', 104.0, 14.0)
                self.assertEqual(core.tick(104.0, 14.0), guard_module.ZERO)
                self.assertIsNotNone(core.latched_reason)

    def test_reset_discards_old_motion_but_residual_feedback_rearms_it(self):
        core = self.ready()
        command(core, 0.04)
        self.assertEqual(core.tick(100.0, 10.0), (0.04, 0.0))
        core.latch('operator/task stop', 100.0, 10.0)
        command(core)
        self.assertTrue(core.reset(100.0, 10.0)[0])
        self.assertFalse(core.motion_active)
        self.assertNotIn('command', core.latest)
        self.assertEqual(core.tick(100.0, 10.0), guard_module.ZERO)
        moving = odom()
        moving['angular'][2] = 0.01
        core.accept_odom(moving, 100.0, 100.0, 10.0)
        self.assertEqual(core.tick(100.0, 10.0), guard_module.ZERO)
        self.assertTrue(core.motion_active)

    def test_zero_idle_does_not_start_command_outage_timer(self):
        core = self.ready()
        sensors(core, 104.0, 14.0)
        self.assertEqual(core.tick(104.0, 14.0), guard_module.ZERO)
        self.assertIsNone(core.latched_reason)
        self.assertIsNone(core.hold_started)

    def test_recovery_stability_uses_steady_clock_when_ros_time_pauses(self):
        core = self.ready()
        self.stale_odom(core)
        sensors(core, 100.0, 10.1)
        self.assertEqual(core.tick(100.0, 10.1), guard_module.ZERO)
        sensors(core, 100.0, 10.3)
        self.assertEqual(core.tick(100.0, 10.3), guard_module.ZERO)
        self.assertIsNone(core.hold_started)
        command(core, 0.04, ros=100.0, steady=10.31)
        self.assertEqual(core.tick(100.0, 10.31), (0.04, 0.0))

    def test_operator_stop_and_invalid_data_remain_explicit_reset_faults(self):
        core = self.ready()
        self.stale_odom(core)
        core.latch('operator/task stop', 100.0, 10.0)
        sensors(core, 100.1, 10.1)
        command(core, 0.04, ros=100.1, steady=10.1)
        self.assertEqual(core.tick(100.1, 10.1), guard_module.ZERO)
        self.assertFalse(core.reset(100.1, 10.1)[0])
        command(core, ros=100.1, steady=10.1)
        self.assertTrue(core.reset(100.1, 10.1)[0])
        self.assertIsNone(core.hold_started)
        command(core, 0.04, ros=100.11, steady=10.11)
        self.assertEqual(core.tick(100.11, 10.11), (0.04, 0.0))
        core.accept_command([math.nan, 0, 0, 0, 0, 0], 100.11, 100.11, 10.11)
        self.assertEqual(core.tick(100.11, 10.11), guard_module.ZERO)
        self.assertIn('malformed', core.latched_reason)


if __name__ == '__main__':
    unittest.main(verbosity=2)
