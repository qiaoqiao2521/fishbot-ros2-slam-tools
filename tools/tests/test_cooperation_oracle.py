"""Independent scoring regressions; synthetic fixtures are not ROS acceptance."""
import ast
import copy
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cooperation_oracle', TOOLS/'cooperation_oracle.py')
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
base = oracle.oracle


def physical_samples():
    """Declare an independent ideal task timeline, without production helpers."""
    samples = []
    for index in range(626):
        t = index*.02
        lifting = 1. <= t < 2.5
        moving = 5. <= t < 11.
        x = min(.6, max(0., (t-5.)*.1))
        cargo_z = .20 if lifting else .17
        forces = [.04, .04] if lifting else [0., 0.]
        raw = {'finite': True, 'q6': ([.1]*6 if t < 3.5 else [0.]*6),
               'qvel6': [0.]*6, 'car_hold': not moving,
               'cargo': {'velocity_relative_tray': [0., 0., 0.]},
               'cargo_tray_floor_contact': not lifting,
               'arm_forbidden_contact_total': 0, 'car_forbidden_contact_total': 0}
        samples.append({'stamp': t, 'wall_time': 100.+t, 'car': [x, 0., 0.],
                        'cargo': [x, 0., cargo_z], 'relative': [0., 0., .01],
                        'extents': [.009, .009, .008], 'car_yaw': 0.,
                        'car_speed': .1 if moving else 0., 'yaw_rate': 0.,
                        'forces': forces, 'raw': raw, 'independent_crosscheck': True})
    return samples


def audit():
    return {'dock_pose': [0., 0., 0.], 'home_q6': [0.]*6}


def score_transport(samples):
    attempt = {'task_id': 'task', 'started_wall_time': 100., **base.full_score(samples, audit())}
    events = [{'kind': 'full_finished', 'task_id': 'task', 'wall_time': 113.}]
    return attempt, oracle.transport_checks(samples, audit(), [attempt], events)


class PhysicalOracleTests(unittest.TestCase):
    def test_complete_synthetic_task_passes_original_and_continuous_handoff(self):
        old, strict = score_transport(physical_samples())
        self.assertTrue(old['passed'])
        self.assertTrue(strict['passed'])
        self.assertAlmostEqual(old['transport']['max_true_cargo_displacement_m'], .6)
        self.assertLess(strict['windows'][0]['continuous_handoff']['first_pass_stamp'], 5.)

    def test_false_hold_cannot_pass_handoff_despite_original_score_success(self):
        samples = physical_samples()
        for item in samples:
            item['raw']['car_hold'] = False
        old, strict = score_transport(samples)
        self.assertTrue(old['passed'])
        self.assertFalse(strict['passed'])
        self.assertTrue(strict['windows'][0]['motion_before_handoff'])

    def test_arm_leaving_home_after_valid_handoff_fails_transport(self):
        samples = physical_samples()
        samples[400]['raw']['q6'][0] = .02
        old, strict = score_transport(samples)
        self.assertTrue(old['passed'])
        self.assertFalse(strict['passed'])
        self.assertFalse(strict['windows'][0]['violation_samples_preview'][0]['arm_home_quiet'])

    def test_arm_velocity_norm_uses_original_norm_threshold(self):
        samples = physical_samples()
        samples[400]['raw']['qvel6'][:2] = [.03, .04]
        old, strict = score_transport(samples)
        self.assertTrue(old['passed'])
        self.assertFalse(strict['passed'])

    def test_rotated_corner_cannot_hide_behind_center_or_successful_motion(self):
        samples = physical_samples()
        samples[400]['relative'][0] = .047
        samples[400]['extents'][0] = .009*math.sqrt(2)
        old, strict = score_transport(samples)
        self.assertTrue(old['passed'])
        self.assertEqual(old['transport']['full_footprint_violation_samples_after_release'], 1)
        self.assertFalse(strict['passed'])

    def test_original_lift_and_final_stop_are_not_relaxed(self):
        samples = physical_samples()
        for item in samples:
            item['forces'] = [0., 0.]
        old, strict = score_transport(samples)
        self.assertFalse(old['passed'])
        self.assertFalse(strict['passed'])

    def test_duplicate_or_missing_source_samples_do_not_establish_dwell(self):
        gate = base.Gate(1.)
        for _ in range(100):
            self.assertFalse(gate.update(1., True))
        self.assertFalse(gate.update(2., True))
        self.assertFalse(gate.update(2.1, True))
        self.assertIsNone(gate.first_pass)

    def test_true_origin_motion_ignores_reported_inertial_twist(self):
        pose = {'position': {'x': 0., 'y': 0., 'z': 0.},
                'orientation': {'w': 1., 'x': 0., 'y': 0., 'z': 0.}}
        twist = {'linear': {'x': 999., 'y': 0., 'z': 0.},
                 'angular': {'x': 0., 'y': 0., 'z': 0.}}
        truth = [{'source_stamp': t, 'payload': {'pose': {'pose': pose}, 'twist': {'twist': twist}}} for t in (.98, 1.)]
        cargo_pose = copy.deepcopy(pose)
        cargo_pose['position']['x'] = .047
        cargo_pose['orientation'] = {'w': math.cos(math.pi/8), 'x': 0., 'y': 0., 'z': math.sin(math.pi/8)}
        cargo = [{'source_stamp': 1., 'payload': {'pose': cargo_pose}}]
        raw = {'finger_normal_forces_n': {'left': 0., 'right': 0.},
               'car': {'position': [0., 0., 0.]},
               'cargo': {'position': [.047, 0., 0.], 'position_relative_tray': [.047, 0., 0.]}}
        result = base.physical_sample({'payload': raw, 'source_stamp': 1., 'received_wall_time': 1.},
                                      truth, cargo, [{'source_stamp': 1.}], [0.]*3, [.009, .009, .008])
        self.assertEqual(result['car_speed'], 0.)
        self.assertEqual(result['reported_twist_speed_not_scoring_authority'], 999.)
        self.assertTrue(result['independent_crosscheck'])
        self.assertGreater(abs(result['relative'][0])+result['extents'][0], .058)


def episode_records():
    records = []
    for index in range(3):
        t = 1.+index*.02
        payload = {'stamp': t, 'sequence': index+1, 'physics_steps': 100+index,
                   'episode_id': 'episode', 'source': {'episode_id': 'episode'},
                   'episode_reset': {'count': 0}}
        payload.update({name: 0 for name in ('arm_forbidden_contact_total', 'car_forbidden_contact_total',
                                            'arm_forbidden_contact_count', 'car_forbidden_contact_count')})
        records.append({'topic': 'physics', 'source_stamp': t, 'received_wall_time': 10.1+index*.02, 'payload': payload})
        records.append({'topic': 'clock', 'source_stamp': t, 'received_wall_time': 10.1+index*.02, 'payload': {}})
    for kind in ('dock', 'nav'):
        identity = [1]*16 if kind == 'dock' else [2]*16
        for status, wall in ((2, 10.2), (4, 10.3)):
            records.append({'topic': kind+'_status', 'received_wall_time': wall,
                            'payload': {'status_list': [{'goal_info': {'goal_id': {'uuid': identity}}, 'status': status}]}})
    records.append({'topic': 'http_state', 'received_wall_time': 10.4,
                    'payload': {'task': {'id': 'task', 'status': 'succeeded'}}})
    records.append({'topic': 'marker_file', 'received_wall_time': 10.4, 'payload': {'events': [
        {'kind': 'full_started', 'task_id': 'task', 'wall_time': 10.},
        {'kind': 'full_finished', 'task_id': 'task', 'wall_time': 10.5}]}})
    return records


class IdentityAndCancellationTests(unittest.TestCase):
    def extra(self, records):
        return oracle.extra_checks(records, Path('/nonexistent/no-marker-file'), 'episode', allow_initial_episode=True)

    def test_native_identity_and_episode_success_are_required_together(self):
        self.assertTrue(self.extra(episode_records())['passed'])
        records = episode_records()
        for item in records:
            if item['topic'] == 'dock_status' and item['payload']['status_list'][0]['status'] == 4:
                item['payload']['status_list'][0]['status'] = 6
        result = self.extra(records)
        self.assertFalse(result['passed'])
        self.assertTrue(result['windows'][0]['terminal_task_success'])
        self.assertFalse(result['windows'][0]['all_native_success'])

    def test_conflicting_episode_source_and_duplicate_sequence_fail(self):
        for field in ('episode_id', 'sequence'):
            records = episode_records()
            physics = [item for item in records if item['topic'] == 'physics']
            if field == 'episode_id':
                physics[1]['payload']['source']['episode_id'] = 'other'
            else:
                physics[1]['payload']['sequence'] = physics[0]['payload']['sequence']
            with self.subTest(field=field):
                self.assertFalse(self.extra(records)['passed'])

    def test_reset_inside_same_task_is_not_an_allowed_between_episode_reset(self):
        records = episode_records()
        for item in records:
            if item['topic'] == 'physics':
                item['payload']['episode_reset'] = {'count': 1, 'stamp': 1.02}
        result = self.extra(records)
        self.assertTrue(result['reset_count_fixed'])
        self.assertTrue(result['reset_receipts_inside_task'])
        self.assertFalse(result['passed'])

    def test_missing_clock_or_full_finish_never_passes(self):
        for topic in ('clock', 'marker_file'):
            records = [item for item in episode_records() if item['topic'] != topic]
            with self.subTest(topic=topic):
                self.assertFalse(self.extra(records)['passed'])

    def test_cancellation_matches_active_native_uuid_and_true_motion(self):
        identity = [1]*16
        records = [
            {'topic': 'nav_status', 'received_wall_time': 99., 'payload': {'status_list': [
                {'goal_info': {'goal_id': {'uuid': identity}}, 'status': 2}]}},
            {'topic': 'nav_feedback', 'received_wall_time': 99.5, 'payload': {'goal_id': {'uuid': identity}}},
            {'topic': 'nav_status', 'received_wall_time': 100.2, 'payload': {'status_list': [
                {'goal_info': {'goal_id': {'uuid': identity}}, 'status': 5}]}},
            {'topic': 'http_state', 'received_wall_time': 100.2, 'payload': {'task': {'id': 'task'}}}]
        samples = [{'wall_time': 99.9, 'stamp': 1., 'car_speed': .1, 'yaw_rate': 0.,
                    'independent_crosscheck': True, 'raw': {'qvel6': [0.]*6}}]
        samples += [{'wall_time': 100.+index*.02, 'stamp': 1.+index*.02, 'car_speed': 0., 'yaw_rate': 0.,
                     'independent_crosscheck': True, 'raw': {'qvel6': [0.]*6}} for index in range(1, 51)]
        event = {'wall_time': 100., 'task_id': 'task'}
        self.assertTrue(base.cancellation_score(records, samples, event, None)['passed'])
        wrong = copy.deepcopy(records)
        wrong[2]['payload']['status_list'][0]['goal_info']['goal_id']['uuid'] = [2]*16
        self.assertFalse(base.cancellation_score(wrong, samples, event, None)['passed'])
        stopped = copy.deepcopy(samples)
        stopped[0]['car_speed'] = 0.
        self.assertFalse(base.cancellation_score(records, stopped, event, None)['passed'])


class PortableEntryTests(unittest.TestCase):
    def test_modules_do_not_import_control_helpers_or_ros_for_offline_scoring(self):
        for module_path in (TOOLS/'cooperation_oracle.py', TOOLS/'cooperation_oracle_base.py'):
            tree = ast.parse(module_path.read_text())
            top_imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
            names = [node.module if isinstance(node, ast.ImportFrom) else name.name
                     for node in top_imports for name in (node.names if isinstance(node, ast.Import) else [None])]
            self.assertFalse(any(name and name.startswith(('cooperation_core', 'cooperation_sim', 'cooperation_bridge', 'rclpy')) for name in names))
            self.assertNotIn('/home/muqiao', module_path.read_text())

    def test_replay_cannot_write_inside_original_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = ['--expected-episode', 'episode', '--allow-initial-episode', '--score-only', str(root),
                    '--markers', str(root/'markers.json'), '--output', str(root/'new')]
            with self.assertRaises(SystemExit), patch('sys.stderr'):
                oracle.parse_options(args)
            self.assertFalse((root/'new').exists())

    def test_existing_output_is_never_reused_or_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = ['--expected-episode', 'episode', '--allow-initial-episode', '--domain', '120',
                    '--markers', str(root/'markers.json'), '--output', str(root)]
            with self.assertRaises(SystemExit), patch('sys.stderr'):
                oracle.parse_options(args)

    def test_live_observer_refuses_protected_or_unspecified_domains(self):
        for domain in (None, '0', '107', '114', '-1'):
            args = ['--expected-episode', 'episode', '--allow-initial-episode',
                    '--markers', 'markers.json', '--output', '/nonexistent/new-oracle-output']
            if domain is not None:
                args += ['--domain', domain]
            with self.subTest(domain=domain), self.assertRaises(SystemExit), patch('sys.stderr'):
                oracle.parse_options(args)

    def test_failed_replay_preserves_original_and_writes_private_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            historical = root/'historical'
            historical.mkdir()
            (historical/'observer.jsonl').write_text('{malformed}\n')
            original = (historical/'observer.jsonl').read_bytes()
            output = root/'replay'
            args = ['--expected-episode', 'episode', '--allow-initial-episode', '--score-only', str(historical),
                    '--markers', str(root/'markers.json'), '--output', str(output)]
            with patch('builtins.print'):
                code = oracle.main(args)
            self.assertEqual(code, 1)
            self.assertEqual((historical/'observer.jsonl').read_bytes(), original)
            files = list(output.glob('score-error-*.json'))
            self.assertEqual(len(files), 1)
            result = json.loads(files[0].read_text())
            self.assertFalse(result['passed'])
            self.assertEqual(result['evidence_mode'], 'offline_replay')
            self.assertFalse(result['live_runtime_acceptance_claimed'])
            self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)


if __name__ == '__main__':
    unittest.main()
