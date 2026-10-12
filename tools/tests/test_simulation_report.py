"""Independent evidence must contradict false action success and missing data."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'fishbot_simulation_report.py'
SPEC = importlib.util.spec_from_file_location('simulation_report', SOURCE)
reporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reporter)


def recording(samples=None):
    if samples is None:
        samples = []
        for step in range(31):
            t = step / 10
            samples.append({'steady_time': 10 + t, 'stamp': 100 + t,
                            'x': min(t / 2, 1), 'y': 0., 'yaw': 0.,
                            'linear_speed': .5 if t < 2 else 0., 'angular_speed': 0.})
    return {'domain': 96, 'truth': samples, 'events': [],
            'final_steady_time': samples[-1]['steady_time'] if samples else 13,
            'final_ros_now': samples[-1]['stamp'] if samples else 103,
            'operator_reset_count': 0}


def goal(**changes):
    result = {'completed': True, 'stationary_feedback': True, 'action_status': 4,
              'error_code': 0, 'goal_sent_steady_time': 10., 'accepted_steady_time': 10.1,
              'terminal_steady_time': 12.2, 'goal_send_count': 1}
    result.update(changes)
    return result


def navigation(**changes):
    result = {'name': 'door-36', 'kind': 'navigation', 'door_width_m': .36,
              'initial_yaw_rad': 0., 'target': [1., 0., 0.], 'command_returncode': 0}
    result.update(changes)
    if result['kind'] == 'cancel' and 'command_returncode' not in changes:
        result['command_returncode'] = 1
    return result


def scan_gap_recording():
    samples, x = [], 0.
    for step in range(40):
        t = step / 10
        speed = .05 if t < 1.3 or 1.8 <= t < 3 else 0.
        x += speed * .1
        samples.append({'steady_time': 10 + t, 'stamp': 100 + t, 'x': x, 'y': 0.,
                        'yaw': 0., 'linear_speed': speed, 'angular_speed': 0.})
    return recording(samples)


class NavigationEvidenceTests(unittest.TestCase):
    def analyze(self, case=None, capture=None, result=None, guards=None, relay=None):
        return reporter.analyze_case(case or navigation(), capture or recording(),
                                     result or goal(), guards or [], relay or [])

    def test_actual_navigation_success_requires_independent_endpoint_and_stopping(self):
        result = self.analyze()
        self.assertTrue(result['passed'], result)
        self.assertAlmostEqual(result['metrics']['final_error_m'], 0)
        self.assertAlmostEqual(result['metrics']['elapsed_s'], 2.2)
        json.dumps(result, allow_nan=False)

    def test_success_at_origin_does_not_count_as_traversing_route(self):
        capture = recording()
        for sample in capture['truth']:
            sample['x'] = sample['linear_speed'] = 0.
        result = self.analyze(capture=capture)
        self.assertFalse(result['passed'])
        self.assertIn('final_pose', result['failed_checks'])
        self.assertIn('movement_observed', result['failed_checks'])

    def test_ordered_route_is_cross_checked_against_truth(self):
        result = self.analyze(case=navigation(kind='route', route=[[.3, 0, 0], [.6, 0, 0], [1., 0, 0]]))
        self.assertTrue(result['passed'], result)
        self.assertEqual([visit['index'] for visit in result['metrics']['ordered_visits']], [0, 1, 2])

    def test_visiting_correct_points_in_wrong_order_fails_even_with_success(self):
        result = self.analyze(case=navigation(kind='route', route=[[.7, 0, 0], [.2, 0, 0], [1., 0, 0]]))
        self.assertFalse(result['passed'])
        self.assertIn('ordered_route_coverage', result['failed_checks'])

    def test_missing_target_and_missing_truth_stay_unknown(self):
        result = self.analyze(case={'name': 'missing', 'kind': 'navigation'})
        self.assertFalse(result['passed'])
        self.assertIn('final_pose', result['unknown_checks'])
        result = self.analyze(capture={'domain': 96, 'truth': []})
        self.assertFalse(result['passed'])
        self.assertIn('truth_present_and_finite', result['unknown_checks'])

    def test_stale_last_sample_and_missing_final_clock_cannot_pass(self):
        capture = recording()
        capture['final_ros_now'] += 1
        result = self.analyze(capture=capture)
        self.assertIn('truth_final_fresh', result['failed_checks'])
        del capture['final_steady_time']
        result = self.analyze(capture=capture)
        self.assertIn('truth_final_fresh', result['unknown_checks'])

    def test_receive_gap_and_frozen_source_clock_invalidate_stationary_claim(self):
        capture = recording()
        del capture['truth'][8:13]
        result = self.analyze(capture=capture)
        self.assertIn('truth_window_continuous', result['failed_checks'])
        capture = recording()
        for sample in capture['truth']:
            sample['stamp'] = 100.
        result = self.analyze(capture=capture)
        self.assertIn('truth_clock_advances', result['failed_checks'])
        self.assertIn('final_stopped', result['failed_checks'])

    def test_idle_startup_gap_is_preserved_but_not_an_active_goal_dropout(self):
        capture = recording()
        idle = [dict(capture['truth'][0], steady_time=9., stamp=99., linear_speed=0.),
                dict(capture['truth'][0], steady_time=9.5, stamp=99.5, linear_speed=0.),
                dict(capture['truth'][0], steady_time=9.9, stamp=99.9, linear_speed=0.)]
        capture['truth'] = idle + capture['truth']
        result = self.analyze(capture=capture)
        self.assertTrue(result['passed'], result)
        evidence = result['checks']['truth_window_continuous']['evidence']
        self.assertAlmostEqual(evidence['whole_recording_max_steady_gap_s'], .5)
        self.assertLessEqual(evidence['max_steady_gap_s'], .3)

    def test_same_gap_crossing_goal_dispatch_still_fails_active_continuity(self):
        capture = recording()
        capture['truth'] = [dict(capture['truth'][0], steady_time=9.9, stamp=99.9,
                                 linear_speed=0.)] + capture['truth'][4:]
        result = self.analyze(capture=capture)
        self.assertIn('truth_window_continuous', result['failed_checks'])

    def test_tail_stopping_must_last_point_seven_seconds_with_rotation_stopped(self):
        capture = recording()
        for sample in capture['truth'][-6:]:
            sample['angular_speed'] = .03
        result = self.analyze(capture=capture)
        self.assertIn('final_stopped', result['failed_checks'])

    def test_stop_confirmation_cannot_replace_canceled_action_terminal(self):
        case = navigation(kind='cancel', cancel_sent_while_moving=True,
                          cancel_trigger={'steady_time': 11.05,
                                          'truth': dict(recording()['truth'][10], ros_now=101.05)})
        result = self.analyze(case=case, result=goal(completed=False, guard_stop_acknowledged=True))
        self.assertIn('canceled_terminal', result['failed_checks'])
        result = self.analyze(case=case, result=goal(completed=False, cancel_terminal_status=5))
        self.assertTrue(result['passed'], result)
        result = self.analyze(case=case, result=goal(completed=True, cancel_terminal_status=5))
        self.assertFalse(result['passed'])

    def test_static_or_stale_cancel_trigger_is_not_moving_cancel(self):
        trigger = {'steady_time': 11.05, 'truth': dict(recording()['truth'][10], ros_now=101.05)}
        case = navigation(kind='cancel', cancel_sent_while_moving=True, cancel_trigger=trigger)
        trigger['truth']['linear_speed'] = 0.
        result = self.analyze(case=case, result=goal(completed=False, cancel_terminal_status=5))
        self.assertIn('cancel_triggered_while_moving', result['failed_checks'])
        trigger['truth']['linear_speed'] = .5
        trigger['truth']['stamp'] = 100.
        result = self.analyze(case=case, result=goal(completed=False, cancel_terminal_status=5))
        self.assertIn('cancel_triggered_while_moving', result['failed_checks'])

    def test_initial_wait_and_final_stop_are_not_internal_pauses(self):
        capture = recording()
        for sample in capture['truth']:
            elapsed = round(sample['steady_time'] - 10, 6)
            if elapsed <= .3 or 1. <= elapsed <= 1.3:
                sample['linear_speed'] = 0.
        result = self.analyze(capture=capture)
        self.assertEqual(result['metrics']['pause_count'], 1)
        self.assertAlmostEqual(result['metrics']['pause_total_duration_s'], .3)

    def test_nan_truth_is_explicit_failure_and_json_remains_serializable(self):
        capture = recording()
        capture['truth'][-1]['x'] = float('nan')
        result = self.analyze(capture=capture)
        self.assertIn('truth_present_and_finite', result['failed_checks'])
        json.dumps(result, allow_nan=False)

    def test_action_success_cannot_override_failed_or_missing_command_exit(self):
        result = self.analyze(case=navigation(command_returncode=1))
        self.assertIn('command_exit', result['failed_checks'])
        result = self.analyze(case=navigation(command_returncode=None))
        self.assertIn('command_exit', result['unknown_checks'])


class FaultEvidenceTests(unittest.TestCase):
    def analyze(self, capture=None, relay=None, guards=None, result=None):
        capture = capture or scan_gap_recording()
        return reporter.analyze_case(
            navigation(name='moving-gap', kind='scan_gap', target=[capture['truth'][-1]['x'], 0, 0]),
            capture, result or goal(terminal_steady_time=13.1),
            guards if guards is not None else [
                {'kind': 'timing_pause', 'reason': 'scan: stale', 'steady_time': 11.31},
                {'kind': 'timing_recovered', 'reason': 'scan: stale', 'steady_time': 11.9}],
            relay if relay is not None else [
                {'event': 'gap_started', 'steady_time': 10.8, 'linear_speed_mps': .05},
                {'event': 'gap_ended', 'steady_time': 11.7},
                {'event': 'scan_restored', 'steady_time': 11.7}])

    def test_moving_scan_gap_brakes_recovers_and_completes_original_goal(self):
        result = self.analyze()
        self.assertTrue(result['passed'], result)
        self.assertGreaterEqual(result['metrics']['gap_stationary_duration_s'], .2)
        self.assertAlmostEqual(result['metrics']['scan_gap_duration_s'], .9)

    def test_static_trigger_does_not_establish_moving_recovery(self):
        result = self.analyze(relay=[{'event': 'gap_started', 'steady_time': 10.8, 'speed': 0.},
                                    {'event': 'gap_ended', 'steady_time': 11.7}])
        self.assertIn('gap_triggered_while_moving', result['failed_checks'])

    def test_gap_timer_end_without_a_new_scan_is_not_recovery(self):
        result = self.analyze(relay=[{'event': 'gap_started', 'steady_time': 10.8, 'linear_speed_mps': .05},
                                    {'event': 'gap_ended', 'steady_time': 11.7}])
        self.assertIn('scan_gap_recorded', result['failed_checks'])

    def test_guard_recovery_alone_does_not_establish_physical_braking(self):
        capture = scan_gap_recording()
        for sample in capture['truth']:
            if sample['steady_time'] < 13:
                sample['linear_speed'] = .05
        result = self.analyze(capture=capture)
        self.assertIn('truth_braked_during_gap', result['failed_checks'])

    def test_no_motion_after_recovery_does_not_establish_resumed_goal(self):
        capture = scan_gap_recording()
        for sample in capture['truth']:
            if sample['steady_time'] > 11.9:
                sample['linear_speed'] = 0.
        result = self.analyze(capture=capture)
        self.assertIn('truth_resumed_after_recovery', result['failed_checks'])

    def test_second_goal_or_operator_reset_invalidates_automatic_resume(self):
        result = self.analyze(result=goal(terminal_steady_time=13.1, goal_send_count=2))
        self.assertIn('same_goal_resumed', result['failed_checks'])
        capture = scan_gap_recording()
        capture['operator_reset_count'] = 1
        result = self.analyze(capture=capture)
        self.assertIn('no_operator_reset', result['failed_checks'])


class MotionAndHtmlTests(unittest.TestCase):
    def test_existing_motion_probe_needs_all_measurements_not_just_pass_flag(self):
        case = {'name': 'expired-command', 'kind': 'motion', 'command_returncode': 0}
        motion = {'passed': True, 'stale_command_drift': .001, 'stopped_after_seconds': .7,
                  'final_planar_speed': 0., 'final_angular_speed': 0., 'post_timeout_drift': .001,
                  'displacement': .25, 'trajectory': [[1, 0, 0], [2, .25, 0]]}
        result = reporter.analyze_case(case, {}, {}, [], [], motion)
        self.assertTrue(result['passed'], result)
        del motion['stale_command_drift']
        result = reporter.analyze_case(case, {}, {}, [], [], motion)
        self.assertFalse(result['passed'])
        self.assertIn('old_command_rejected', result['unknown_checks'])

    def test_html_reuses_recorded_route_escapes_events_and_links_only_existing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / 'door-36' / 'replay').mkdir(parents=True)
            (output / 'door-36' / 'goal.json').write_text('{}')
            (output / 'door-36' / 'replay' / 'index.html').write_text('replay')
            result = reporter.analyze_case(navigation(), recording(), goal(),
                                          [{'kind': 'collision_stop', 'reason': '<script>alert(1)</script>',
                                            'steady_time': 11.1, 'polygon_name': 'VelocityStop'}], [])
            html = reporter.save_suite_report({'cases': [result]}, output).read_text()
            self.assertIn('polyline', html)
            self.assertIn('door-36/goal.json', html)
            self.assertIn('door-36/replay/index.html', html)
            self.assertNotIn('href="door-36/recording.json"', html)
            self.assertIn('&lt;script&gt;', html)
            self.assertNotIn('<script>alert(1)</script>', html)
            self.assertIn('VelocityStop', html)

    def test_interrupted_suite_uses_planned_count_and_never_displays_full_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = reporter.analyze_case(navigation(), recording(), goal(), [], [])
            html = reporter.save_suite_report({'status': 'interrupted', 'case_count': 6, 'cases': [result]}, temporary).read_text()
            self.assertIn('interrupted', html)
            self.assertIn('已执行 1/6', html)
            self.assertIn('通过 1/6', html)
            self.assertIn('16.7%', html)

    def test_startup_retry_links_final_truth_and_preserves_first_failure_and_wall_cost(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            first = output / 'door-36'
            retry = output / 'door-36-startup-retry-1'
            first.mkdir()
            (retry / 'fixture').mkdir(parents=True)
            for filename in ('result.json', 'launch.log', 'recorder.log', 'recording.json'):
                (first / filename).write_text('first failure')
            for filename in ('goal.json', 'recording.json', 'result.json'):
                (retry / filename).write_text('retry evidence')
            (retry / 'fixture' / 'provenance.json').write_text('{}')
            result = reporter.analyze_case(navigation(), recording(), goal(), [], [])
            result.update(artifact_directory=retry.name, first_attempt_passed=False,
                          startup_restart_count=1, total_wall_elapsed_s=88.5,
                          startup_attempts=[
                              {'artifact_directory': first.name, 'status': 'failed',
                               'error': 'readiness timeout <map_server>', 'wall_elapsed_s': 55.},
                              {'artifact_directory': retry.name, 'status': 'passed', 'wall_elapsed_s': 33.5}])
            html = reporter.save_suite_report({'status': 'passed', 'case_count': 1,
                                               'cases': [result], 'wall_elapsed_s': 88.5}, output).read_text()
            self.assertIn('href="door-36-startup-retry-1/recording.json"', html)
            self.assertIn('href="door-36-startup-retry-1/goal.json"', html)
            self.assertIn('href="door-36-startup-retry-1/fixture/provenance.json"', html)
            self.assertIn('href="door-36/result.json"', html)
            self.assertIn('href="door-36/launch.log"', html)
            self.assertNotIn('href="door-36/recording.json"', html)
            self.assertIn('首轮通过 0/1', html)
            self.assertIn('启动重启 1 次', html)
            self.assertIn('88.500', html)
            self.assertIn('55.000', html)
            self.assertIn('readiness timeout &lt;map_server&gt;', html)


if __name__ == '__main__':
    unittest.main()
