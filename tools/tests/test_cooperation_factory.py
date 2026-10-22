"""Factory adapter contracts only; no ROS, listener, process or robot motion."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cooperation_factory as factory
from cooperation_workflow import LocalBridge, TransportUnknown


def manifest():
    return {'scene_profile': {'schema': 1, 'vehicle': 'fishbot', 'sensors': 'planar',
                              'task': 'transport'},
            'factory_delivery': {'schema': 1, 'id': 'f1',
                'destinations': [{'id': 'line_a', 'pose': {'x': 0., 'y': -2., 'yaw': 0.}},
                                 {'id': 'line_b', 'pose': {'x': .7, 'y': -2., 'yaw': 0.}}],
                'orders': [{'id': 'order-a', 'destination_id': 'line_a'},
                           {'id': 'order-b', 'destination_id': 'line_b'}],
                'channel': {'occupied': False}}}


def successful_score(order):
    return {'passed': True, 'original_k_oracle_passed': True,
            'plant_guard_telemetry': {'assisted': True},
            'task_delivery_acceptance': {'required': True, 'passed': True, 'attempts': [
                {'task_id': 'task-a', 'episode_id': 'episode-a', 'passed': True,
                 'expected_delivery_pose': order['delivery_pose'],
                 'carrying_nav_uuid': 'native-a', 'carrying_nav_route': [],
                 'final_true_pose_error': {'position_m': .02, 'yaw_rad': .03},
                 'final_true_pose_and_cargo_stop': {'longest_source_duration_s': 1.1}}]}}


class ReferenceTests(unittest.TestCase):
    def test_original_factory_jobs_get_fresh_batches_and_distinct_targets(self):
        first = factory.reference(manifest(), candidate='baseline')
        second = factory.reference(manifest(), candidate='baseline')
        self.assertEqual([item['delivery_pose']['x'] for item in first['orders']], [0., .7])
        self.assertEqual(len({item['batch_id'] for item in first['orders']}), 2)
        self.assertTrue({item['batch_id'] for item in first['orders']}.isdisjoint(
            item['batch_id'] for item in second['orders']))
        self.assertEqual(first['scene_profile']['task'], 'transport')
        self.assertEqual(first['task_timeout_wall_s'], 360.)
        self.assertEqual(first['total_timeout_wall_s'], 1000.)
        self.assertFalse(first['candidate_label_loads_code'])

    def test_order_policy_changes_sequence_without_rebinding_destinations(self):
        value = factory.reference(manifest(), candidate='reverse', order=['order-b', 'order-a'])
        self.assertEqual([(item['id'], item['delivery_pose']['x']) for item in value['orders']],
                         [('order-b', .7), ('order-a', 0.)])

    def test_partial_duplicate_or_unknown_policy_is_rejected(self):
        for order in ([], ['order-a'], ['order-a', 'order-a'], ['order-a', 'unknown']):
            with self.subTest(order=order), self.assertRaises(ValueError):
                factory.reference(manifest(), candidate='label', order=order)

    def test_this_first_slice_cannot_silently_drop_extra_orders(self):
        value = manifest()
        value['factory_delivery']['orders'].append({'id': 'extra', 'destination_id': 'line_a'})
        with self.assertRaises(ValueError):
            factory.reference(value, candidate='baseline')


class ScoreTests(unittest.TestCase):
    def setUp(self):
        self.order = factory.reference(manifest(), candidate='baseline')['orders'][0]
        self.score = successful_score(self.order)

    def report(self, score=None, **changes):
        arguments = {'task_id': 'task-a', 'episode_id': 'episode-a',
                     'terminal': {'task': {'status': 'succeeded'}},
                     'score': self.score if score is None else score,
                     'score_file': Path('/private/original-score.json'), 'elapsed_wall_s': 123.}
        arguments.update(changes)
        return factory.order_report(self.order, **arguments)

    def test_original_physical_and_task_bound_delivery_required(self):
        value = self.report()
        self.assertEqual(value['task_verdict'], 'passed')
        self.assertEqual(value['carrying_nav_uuid'], 'native-a')
        self.assertEqual(value['metrics']['final_position_error_m'], .02)
        self.assertEqual(value['metrics']['final_yaw_error_rad'], .03)
        self.assertEqual(value['metrics']['continuous_final_stop_source_s'], 1.1)

    def test_http_or_terminal_success_does_not_replace_physical_score(self):
        for field in ('passed', 'original_k_oracle_passed'):
            score = copy.deepcopy(self.score)
            score[field] = False
            value = self.report(score)
            self.assertTrue(value['execution']['terminal_observed'])
            self.assertEqual(value['execution']['task_status'], 'succeeded')
            self.assertEqual(value['task_verdict'], 'failed')

    def test_old_episode_wrong_task_or_other_goal_cannot_be_accepted(self):
        for field, replacement in (('task_id', 'old-task'), ('episode_id', 'old-episode'),
                                   ('expected_delivery_pose', {'x': 9., 'y': -2., 'yaw': 0.})):
            score = copy.deepcopy(self.score)
            score['task_delivery_acceptance']['attempts'][0][field] = replacement
            value = self.report(score)
            self.assertFalse(value['destination_bound'])
            self.assertEqual(value['task_verdict'], 'failed')

    def test_missing_score_is_unknown_even_when_terminal_succeeded(self):
        value = factory.order_report(self.order, task_id='task-a', episode_id='episode-a',
            terminal={'task': {'status': 'succeeded'}}, score=None, score_file=None,
            elapsed_wall_s=12.)
        self.assertEqual(value['task_verdict'], 'unknown')
        self.assertIsNone(value['metrics']['final_position_error_m'])

    def test_failed_before_delivery_preserves_null_pose_and_rest_without_losing_report(self):
        score = copy.deepcopy(self.score)
        score.update(passed=False,original_k_oracle_passed=False)
        score['task_delivery_acceptance']['passed'] = False
        attempt = score['task_delivery_acceptance']['attempts'][0]
        attempt.update(passed=False,final_true_pose_error=None,final_true_pose_and_cargo_stop=None,
                       carrying_nav_uuid=None)
        value = self.report(score,terminal={'task':{'status':'failed'}})
        self.assertEqual(value['task_verdict'],'failed')
        self.assertTrue(value['execution']['terminal_observed'])
        self.assertIsNone(value['metrics']['final_position_error_m'])
        self.assertIsNone(value['metrics']['final_yaw_error_rad'])
        self.assertIsNone(value['metrics']['continuous_final_stop_source_s'])
        self.assertIsNone(value['carrying_nav_uuid'])

    def test_guard_intervention_remains_separate_telemetry(self):
        value = self.report()
        self.assertEqual(value['task_verdict'], 'passed')
        self.assertEqual(value['guard_telemetry'], {'assisted': True})

    def test_completed_execution_and_failed_task_are_independent(self):
        first = self.report()
        second = self.report()
        second['task_verdict'] = 'failed'
        second['id'] = 'order-b'
        result = {'declaration': {'orders': [{'id': 'order-a'}, {'id': 'order-b'}]},
                  'orders': [first, second], 'errors': [],
                  'execution': {key: True for key in ('cleanup_complete', 'owned_launch_stopped',
                    'owned_port_closed', 'protected_instances_unchanged', 'within_total_budget')}}
        value = factory.summarize(result)
        self.assertEqual(value['execution']['status'], 'completed')
        self.assertEqual(value['task_verdict'], 'failed')
        self.assertFalse(value['passed'])

    def test_missing_second_order_or_retained_process_never_passes(self):
        result = {'declaration': {'orders': [{'id': 'order-a'}, {'id': 'order-b'}]},
                  'orders': [self.report()], 'errors': [],
                  'execution': {'retained_launch_pid': 123}}
        value = factory.summarize(result)
        self.assertEqual(value['execution']['status'], 'unknown')
        self.assertEqual(value['task_verdict'], 'unknown')
        self.assertFalse(value['passed'])

    def test_two_distinct_physical_scores_need_complete_cleanup(self):
        first = self.report()
        second = self.report()
        second.update(id='order-b', task_id='task-b', episode_id='episode-b',
                      batch_id='batch-b', carrying_nav_uuid='native-b')
        result = {'declaration': {'orders': [{'id': 'order-a'}, {'id': 'order-b'}]},
                  'orders': [first, second], 'errors': [],
                  'execution': {key: True for key in ('cleanup_complete', 'owned_launch_stopped',
                    'owned_port_closed', 'protected_instances_unchanged', 'within_total_budget')}}
        self.assertTrue(factory.summarize(result)['passed'])
        result['execution']['cleanup_complete'] = False
        value = factory.summarize(result)
        self.assertEqual(value['task_verdict'], 'passed')
        self.assertFalse(value['passed'])

    def test_reusing_a_previous_native_uuid_does_not_prove_two_deliveries(self):
        first = self.report()
        second = self.report()
        second.update(id='order-b', task_id='task-b', episode_id='episode-b', batch_id='batch-b')
        result = {'declaration': {'orders': [{'id': 'order-a'}, {'id': 'order-b'}]},
                  'orders': [first, second], 'errors': [], 'execution': {}}
        value = factory.summarize(result)
        self.assertFalse(value['independent_order_identities_distinct'])
        self.assertEqual(value['task_verdict'], 'unknown')
        self.assertFalse(value['passed'])

    def test_task_budget_boundary_does_not_rewrite_original_physical_verdict(self):
        for elapsed, within in ((360., True), (361., False), (None, None),
                                (float('inf'), None), (float('nan'), None), (-1., None)):
            with self.subTest(elapsed=elapsed):
                first = self.report(elapsed_wall_s=elapsed)
                second = self.report()
                second.update(id='order-b', task_id='task-b', episode_id='episode-b',
                              batch_id='batch-b', carrying_nav_uuid='native-b')
                result = {'declaration': {'orders': [{'id': 'order-a'}, {'id': 'order-b'}]},
                          'orders': [first, second], 'errors': [],
                          'execution': {key: True for key in (
                              'cleanup_complete', 'owned_launch_stopped', 'owned_port_closed',
                              'protected_instances_unchanged', 'within_total_budget')}}
                value = factory.summarize(result)
                self.assertIs(first['execution']['within_task_budget'], within)
                self.assertEqual(value['task_verdict'], 'passed')
                self.assertEqual(value['passed'], within is True)


class BoundaryTests(unittest.TestCase):
    def test_missing_units_are_unchanged_but_do_not_claim_running_original_instances(self):
        missing = {'old-107.service': 'MainPID=0\nLoadState=not-found\nActiveState=inactive',
                   'old-114.service': 'MainPID=0\nLoadState=not-found\nActiveState=inactive'}
        value = factory.protection_observation(missing, copy.deepcopy(missing))
        self.assertTrue(value['configured_systemd_units_unchanged'])
        self.assertTrue(value['protected_instances_unchanged'])
        self.assertEqual(value['active_before'], [])
        self.assertEqual(value['running_configured_units_before'], [])
        self.assertFalse(value['historical_instances_were_running'])
        self.assertIn('configured systemd', value['protected_comparison_scope'])

    def test_active_unit_requires_a_nonzero_main_pid_for_running_claim(self):
        before = {'running.service': 'ActiveState=active\nMainPID=123',
                  'oneshot.service': 'ActiveState=active\nMainPID=0'}
        after = {**before, 'running.service': 'ActiveState=inactive\nMainPID=0'}
        value = factory.protection_observation(before, after)
        self.assertEqual(value['active_before'], ['running.service', 'oneshot.service'])
        self.assertEqual(value['running_configured_units_before'], ['running.service'])
        self.assertTrue(value['historical_instances_were_running'])
        self.assertFalse(value['configured_systemd_units_unchanged'])
        self.assertEqual(value['running_configured_units_after'], [])

    def test_running_or_unknown_task_cannot_be_reclaimed_after_native_actions_end(self):
        native = {('nav_status', 'a'*32): 4}
        state = {'episode_id': 'episode-a', 'task': {'id': 'task-a', 'status': 'running'},
                 'native_actions': [{'accepted': True, 'uuid': 'a'*32, 'label': 'Nav2'}]}
        # This reproduces why the lower-level helper alone is insufficient.
        self.assertTrue(factory.native_cleanup_known(state, native, 'task-a', 'episode-a'))
        for status in ('running', 'canceling', 'unknown'):
            with self.subTest(status=status):
                state['task']['status'] = status
                quiet = Mock(return_value={'source_stamp': 1., 'continuous_quiet': True})
                self.assertIsNone(factory.cleanup_proof(state, native, 'task-a', 'episode-a', quiet))
                quiet.assert_not_called()

    def test_only_exact_terminal_task_can_use_independent_quiet_to_reclaim_launch(self):
        native = {('nav_status', 'a'*32): 4}
        state = {'episode_id': 'episode-a', 'task': {'id': 'task-a', 'status': 'succeeded'},
                 'native_actions': [{'accepted': True, 'uuid': 'a'*32, 'label': 'Nav2'}]}
        for status in ('succeeded', 'failed', 'canceled'):
            state['task']['status'] = status
            quiet = Mock(return_value={'source_stamp': 1.})
            self.assertIsNotNone(factory.cleanup_proof(state, native, 'task-a', 'episode-a', quiet))
            quiet.assert_called_once_with('episode-a')
        for task_id, episode in (('another-task', 'episode-a'), ('task-a', 'old-episode')):
            quiet = Mock(return_value={'source_stamp': 1.})
            self.assertIsNone(factory.cleanup_proof(state, native, task_id, episode, quiet))
            quiet.assert_not_called()

    def test_explicit_submission_rejection_retains_separate_idle_cleanup_path(self):
        state = {'episode_id': 'episode-a', 'task': {'id': None, 'status': 'idle'},
                 'native_actions': []}
        quiet = Mock(return_value={'source_stamp': 1.})
        self.assertIsNone(factory.cleanup_proof(state, {}, 'task-a', 'episode-a', quiet))
        self.assertIsNotNone(factory.cleanup_proof(state, {}, 'task-a', 'episode-a', quiet,
                                                  submission_rejected=True))

    def test_marker_precedes_original_single_post_and_unknown_is_not_retried(self):
        calls = []
        bridge = factory.MarkedBridge('http://127.0.0.1:9111',
                                      lambda kind, body: calls.append(('marker', kind)))
        def request(self, kind, body):
            calls.append(('post', kind))
            raise TransportUnknown('receipt lost')
        with patch.object(LocalBridge, 'post', request), self.assertRaises(TransportUnknown):
            bridge.post('start', {'task_id': 'original'})
        self.assertEqual(calls, [('marker', 'start'), ('post', 'start')])

    def test_dry_run_is_read_only_and_candidate_is_only_a_label(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'manifest.json'
            path.write_text(json.dumps(manifest()))
            output = Path(folder)/'not-created'
            code = {'module_files': ['/actual/cooperation_workflow.py'], 'git_head': 'actual-head',
                    'git_status': ' M actual.py', 'observation_errors': []}
            stream = io.StringIO()
            with (patch.object(factory, 'run', side_effect=AssertionError('runtime invoked')),
                  patch.object(factory, 'loaded_code_reference', return_value=code),
                  patch.object(LocalBridge, 'request', side_effect=AssertionError('HTTP invoked')),
                  contextlib.redirect_stdout(stream)):
                rc = factory.main(['run', '--manifest', str(path), '--output', str(output),
                                   '--candidate', 'new-algorithm-label',
                                   '--publication-mode', 'asynchronous', '--dry-run'])
            self.assertEqual(rc, 0)
            self.assertFalse(output.exists())
            value = json.loads(stream.getvalue())
            self.assertFalse(value['ROS_initialized'])
            self.assertFalse(value['actions_started'])
            self.assertEqual(value['loaded_code']['git_head'], 'actual-head')
            self.assertFalse(value['declaration']['candidate_label_loads_code'])
            self.assertEqual(value['declaration']['publication_mode']['requested'], 'asynchronous')
            self.assertEqual(value['declaration']['publication_mode']['process_scope'],
                             ['cooperation_sim', 'cooperation_bridge'])


if __name__ == '__main__':
    unittest.main()
