"""Offline suite entry boundaries; these tests create no ROS participants."""
import importlib.util
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('suite', TOOLS/'fishbot_simulation_suite.py')
suite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)


class SuiteBoundaries(unittest.TestCase):
    def test_seed_recreates_varied_fixture_without_altering_case_types(self):
        self.assertEqual(suite.case_matrix(12), suite.case_matrix(12))
        self.assertNotEqual(suite.case_matrix(12)[1], suite.case_matrix(13)[1])
        self.assertEqual({case['kind'] for case in suite.case_matrix(12)},
                         {'navigation', 'route', 'scan_gap', 'cancel', 'motion'})

    def test_real_or_baseline_domains_never_reach_runtime(self):
        for domain in ('0', '93', '96'):
            with patch.dict(os.environ, {'ROS_DOMAIN_ID': domain,
                            'FISHBOT_MUJOCO_DOMAIN_ID': '93',
                            'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST'}):
                with self.assertRaises(RuntimeError):
                    suite.selected_environment()
        with patch.dict(os.environ, {'ROS_DOMAIN_ID': '96',
                        'FISHBOT_MUJOCO_DOMAIN_ID': '96',
                        'ROS_AUTOMATIC_DISCOVERY_RANGE': 'SUBNET'}):
            with self.assertRaises(RuntimeError):
                suite.selected_environment()
        with patch.dict(os.environ, {'ROS_DOMAIN_ID': '96',
                        'FISHBOT_MUJOCO_DOMAIN_ID': '96',
                        'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST', 'ROS_STATIC_PEERS': '192.0.2.1'}):
            with self.assertRaises(RuntimeError):
                suite.selected_environment()

    def test_help_works_without_ros_runtime_or_graph(self):
        result = subprocess.run(['bash', str(TOOLS.parent/'fishbot.sh'), 'sim-suite', '--help'],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--seed', result.stdout)
        isolated = subprocess.run([sys.executable, '-I', '-c',
            'import runpy,sys; runpy.run_path(sys.argv[1]); assert "rclpy" not in sys.modules',
            str(TOOLS/'fishbot_simulation_suite.py')], capture_output=True, text=True)
        self.assertEqual(isolated.returncode, 0, isolated.stderr)

    def test_atomic_result_replace_has_no_leftover_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'result.json'
            suite.write_json(path, {'status':'running'})
            suite.write_json(path, {'status':'passed'})
            self.assertEqual(suite.read_json(path), {'status':'passed'})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(Path(temporary).glob('*.tmp')), [])

    def test_interruption_preserves_failed_case_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'case'
            case = {'name':'case', 'kind':'navigation', 'target':[1.,0.,0.]}
            with patch.object(suite, 'domain_is_empty', side_effect=KeyboardInterrupt):
                result = suite.execute_case(case, path, {})
            self.assertTrue(case['interrupted'])
            self.assertFalse(result['passed'])
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(suite.read_json(path/'result.json'), result)

    def test_bad_recording_preserves_case_failure_and_original_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'case'
            def broken_start():
                (path/'recording.json').write_text('{partial')
                raise RuntimeError('recorder failed')
            case = {'name':'case', 'kind':'navigation', 'target':[1.,0.,0.]}
            with patch.object(suite, 'domain_is_empty', side_effect=broken_start):
                result = suite.execute_case(case, path, {})
            self.assertFalse(result['passed'])
            self.assertIn('recorder failed', result['error'])
            self.assertEqual(result['checks']['evidence_analysis']['status'], 'failed')
            self.assertEqual((path/'recording.json').read_text(), '{partial')
            self.assertEqual(suite.read_json(path/'result.json'), result)

    def stationary_startup_failure(self, directory):
        suite.write_json(directory/'recording.json', {'final_steady_time':2., 'truth':[
            dict(steady_time=t, stamp=t, x=0., y=0., yaw=0., linear_speed=0., angular_speed=0.) for t in (1., 2.)]})
        return dict(status='failed', case={'name':'case','kind':'navigation'},
            execution=dict(phase='startup', startup_failure_kind='readiness_timeout',
                           domain_empty=True, cleanup_complete=True, goal_process_started=False))

    def test_startup_retry_requires_complete_stationary_evidence_and_finished_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            result = self.stationary_startup_failure(path)
            self.assertTrue(suite.startup_retry_allowed(result, path))
            result['execution']['cleanup_complete'] = False
            self.assertFalse(suite.startup_retry_allowed(result, path))
            result['execution']['cleanup_complete'] = True
            capture = suite.read_json(path/'recording.json')
            for value in (.02, float('nan')):
                capture['truth'][1]['linear_speed'] = value
                (path/'recording.json').write_text(__import__('json').dumps(capture))
                self.assertFalse(suite.startup_retry_allowed(result, path))
            (path/'recording.json').unlink()
            self.assertFalse(suite.startup_retry_allowed(result, path))

    def test_any_goal_start_artifact_or_interruption_prohibits_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            original = self.stationary_startup_failure(path)
            for key, value in (('goal_process_started', True), ('phase', 'command'), ('domain_empty', False)):
                result = copy.deepcopy(original)
                result['execution'][key] = value
                self.assertFalse(suite.startup_retry_allowed(result, path))
            for key, value in (('interrupted', True), ('command_returncode', 1)):
                result = copy.deepcopy(original)
                result['case'][key] = value
                self.assertFalse(suite.startup_retry_allowed(result, path))
            for name in ('goal.json', 'motion.json', 'ready.json'):
                (path/name).write_text('{}')
                self.assertFalse(suite.startup_retry_allowed(original, path))
                (path/name).unlink()

    def test_only_one_cold_restart_and_first_failure_remains_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'case'
            calls = []
            def failed_attempt(case, directory, env):
                directory.mkdir()
                result = self.stationary_startup_failure(directory)
                result.update(artifact_directory=directory.name, wall_elapsed_s=55.)
                suite.write_json(directory/'result.json', result)
                calls.append(directory)
                return result
            with patch.object(suite, 'execute_case', side_effect=failed_attempt):
                result = suite.execute_case_with_startup_retry({'name':'case','kind':'navigation'}, path, {})
            self.assertEqual(calls, [path, path.with_name('case-startup-retry-1')])
            self.assertEqual(result['startup_restart_count'], 1)
            self.assertFalse(result['first_attempt_passed'])
            self.assertNotIn('startup_attempts', suite.read_json(path/'result.json'))
            self.assertEqual(result, suite.read_json(calls[-1]/'result.json'))

    def test_started_goal_failure_never_calls_execute_again(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'case'
            path.mkdir()
            result = self.stationary_startup_failure(path)
            result.update(artifact_directory='case', wall_elapsed_s=10.)
            result['execution']['goal_process_started'] = True
            with patch.object(suite, 'execute_case', return_value=result) as execute:
                final = suite.execute_case_with_startup_retry({'name':'case','kind':'navigation'}, path, {})
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(final['startup_restart_count'], 0)


if __name__ == '__main__':
    unittest.main()
