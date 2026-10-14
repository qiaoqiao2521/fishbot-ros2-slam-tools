"""Admission boundaries over synthetic reports; no ROS or physics is executed."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('stack_gate', TOOLS/'fishbot_stack_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class PairedGate(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.source = self.directory/'source'
        self.source.mkdir()
        for name in gate.CORE_SOURCES:
            path = self.source/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('Synthetic source fixture: '+name+'\n')
        subprocess.run(['git', 'init', '-q', str(self.source)], check=True)
        self.commit()
        self.budget = dict(startup_timeout_s=55, command_timeout_s=90,
                           command_watchdog_s=110, startup_max_retries=1)
        self.panel = dict(schema_version=1, panel_id='paired-fixture', mode='suite', seed=12,
            cases=[dict(name=name, inputs=dict(name=name, domain=96, kind='navigation',
                   target=[1.25, 0., 0.], door_width_m=.4, initial_yaw_rad=0.), budget=self.budget)
                   for name in ('existing-win', 'former-failure', 'second-failure')],
            source_files=list(gate.CORE_SOURCES), thresholds=dict(min_new_successes=1, max_lost_successes=0))
        self.panel_path = self.directory/'panel.json'
        self.write(self.panel_path, self.panel)
        self.receipts = {}

    def commit(self):
        subprocess.run(['git', '-c', 'user.name=Gate Fixture', '-c', 'user.email=gate@example.invalid',
                        'commit', '--allow-empty', '-qm', 'fixture'], cwd=self.source, check=True)

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value))

    def report(self, outcomes, source_receipt):
        cases = []
        for item, success in zip(self.panel['cases'], outcomes):
            checks = {'command_exit': {'status': 'passed', 'evidence': {'actual': 0}},
                      'task_completion': {'status': 'passed' if success else 'failed', 'evidence': success}}
            cases.append(dict(name=item['name'], kind='navigation', case=copy.deepcopy(item['inputs']),
                execution_budget=copy.deepcopy(item['budget']), passed=success,
                status='passed' if success else 'failed', checks=checks,
                execution={'cleanup_complete': True}))
        return dict(schema_version=1, domain=96, mode='suite', seed=12, case_count=len(cases), cases=cases,
                    status='passed' if all(outcomes) else 'failed', passed_count=sum(outcomes),
                    source_revision=source_receipt['source_revision'], source_sha256=source_receipt['source_sha256'])

    def run_receipts(self, label, outcomes):
        path = self.directory/(label+'.json')
        before_path, after_path = self.directory/(label+'-before.json'), self.directory/(label+'-after.json')
        before = gate.snapshot(self.panel_path, self.source, path, 'before')
        self.write(before_path, before)
        self.write(path, self.report(outcomes, before))
        after = gate.snapshot(self.panel_path, self.source, path, 'after', before_path)
        self.write(after_path, after)
        self.receipts[label+'_before'], self.receipts[label+'_after'] = before_path, after_path
        return path

    def pair(self, parent=(True, False, False), candidate=(True, True, False)):
        parent_path = self.run_receipts('parent', parent)
        (self.source/'tools/fishbot_passage_goal.py').write_text('Synthetic candidate behavior fixture\n')
        self.commit()
        candidate_path = self.run_receipts('candidate', candidate)
        return parent_path, candidate_path

    def comparison(self, paths, receipts=True):
        return gate.compare(self.panel_path, *paths, self.receipts if receipts else None)

    def edit_bound_report(self, path, label, change):
        report = gate.load(path)
        change(report)
        self.write(path, report)
        # Re-observe after receipt; mutation is not hidden by an old file hash.
        self.write(self.receipts[label+'_after'], gate.snapshot(self.panel_path, self.source, path,
                    'after', self.receipts[label+'_before']))

    def test_new_measured_success_with_no_loss_accepts_without_apply(self):
        result = self.comparison(self.pair())
        self.assertTrue(result['gate_accepted'], result['rejection_reasons'])
        self.assertEqual(result['original_verdict']['gained_tasks'], ['former-failure'])
        self.assertFalse(result['applied'])

    def test_net_aggregate_improvement_still_rejects_one_original_loss(self):
        result = self.comparison(self.pair(candidate=(False, True, True)))
        self.assertEqual(result['candidate_success_count'], 2)
        self.assertFalse(result['gate_accepted'])
        self.assertEqual(result['original_verdict']['regressed_tasks'], ['existing-win'])

    def test_failure_stage_advance_is_not_a_new_task_success(self):
        paths = self.pair(candidate=(True, False, False))
        report = gate.load(paths[1])
        report['cases'][1].update(failure_class='later-stage', progress=.9)
        self.write(paths[1], report)
        result = self.comparison(paths)
        self.assertFalse(result['gate_accepted'])
        self.assertEqual(result['original_verdict']['reason'], 'no_measured_improvement')

    def test_legacy_report_with_gain_remains_diagnostic(self):
        result = self.comparison(self.pair(), receipts=False)
        self.assertFalse(result['gate_accepted'])
        self.assertEqual(result['original_verdict']['gained_tasks'], ['former-failure'])
        self.assertIn('legacy diagnostic only', ' '.join(result['rejection_reasons']))

    def test_source_boundary_change_rejects_even_with_new_success(self):
        paths = self.pair()
        after_path = self.receipts['candidate_after']
        after = gate.load(after_path)
        after['source_sha256']['tools/fishbot_passage_goal.py'] = 'f'*64
        self.write(after_path, after)
        self.assertFalse(self.comparison(paths)['gate_accepted'])

    def test_report_mutation_after_receipt_is_rejected(self):
        paths = self.pair()
        report = gate.load(paths[1])
        report['extra'] = 'changed after capture'
        self.write(paths[1], report)
        result = self.comparison(paths)
        self.assertFalse(result['gate_accepted'])
        self.assertIn('actual report hash', ' '.join(result['rejection_reasons']))

    def test_backdated_report_is_rejected_even_with_matching_after_hash(self):
        import os
        paths = self.pair()
        before = gate.load(self.receipts['candidate_before'])
        past = before['observed_wall_ns']-10_000_000_000
        os.utime(paths[1], ns=(past, past))
        self.write(self.receipts['candidate_after'], gate.snapshot(self.panel_path, self.source, paths[1],
                    'after', self.receipts['candidate_before']))
        result = self.comparison(paths)
        self.assertFalse(result['gate_accepted'])
        self.assertIn('chronology', ' '.join(result['rejection_reasons']))

    def test_real_mtime_chronology_accepts_repeated_fresh_fixtures(self):
        for attempt in range(10):
            with self.subTest(attempt=attempt):
                paths = self.pair()
                result = self.comparison(paths)
                self.assertTrue(result['gate_accepted'], result['rejection_reasons'])
                for path in (*paths, *self.receipts.values()):
                    path.unlink()

    def test_immutable_geometry_change_is_rejected(self):
        parent = self.run_receipts('parent', (True, False, False))
        (self.source/gate.ORACLES[1]).write_text('Smaller fixture footprint\n')
        candidate = self.run_receipts('candidate', (True, True, False))
        result = self.comparison((parent, candidate))
        self.assertFalse(result['gate_accepted'])
        self.assertIn('immutable', ' '.join(result['rejection_reasons']))

    def test_fixture_generator_scene_model_and_plugin_changes_reject_gain(self):
        for relative in gate.ORACLES[2:]:
            with self.subTest(source=relative):
                parent = self.run_receipts('parent', (True, False, False))
                source = self.source/relative
                original = source.read_text()
                source.write_text('Changed synthetic physical fixture\n')
                candidate = self.run_receipts('candidate', (True, True, False))
                result = self.comparison((parent, candidate))
                self.assertFalse(result['gate_accepted'])
                self.assertEqual(result['original_verdict']['gained_tasks'], ['former-failure'])
                self.assertTrue(any(relative in reason and 'immutable' in reason
                                    for reason in result['rejection_reasons']))
                source.write_text(original)
                for path in (parent, candidate, *self.receipts.values()):
                    path.unlink()

    def test_json_bool_alias_cannot_match_frozen_input_or_budget_number(self):
        self.panel['cases'][1]['inputs']['initial_yaw_rad'] = 1
        self.write(self.panel_path, self.panel)
        paths = self.pair()
        self.edit_bound_report(paths[1], 'candidate', lambda report:
            report['cases'][1]['case'].update(initial_yaw_rad=True))
        result = self.comparison(paths)
        self.assertFalse(result['gate_accepted'])
        self.assertIn('realized inputs differ', ' '.join(result['rejection_reasons']))
        self.edit_bound_report(paths[1], 'candidate', lambda report:
            report['cases'][1]['case'].update(initial_yaw_rad=1))
        self.edit_bound_report(paths[1], 'candidate', lambda report:
            report['cases'][1]['execution_budget'].update(startup_max_retries=True))
        result = self.comparison(paths)
        self.assertFalse(result['gate_accepted'])
        self.assertIn('execution budget unverified', ' '.join(result['rejection_reasons']))

    def test_incomplete_candidate_cannot_cherry_pick(self):
        paths = self.pair()
        self.edit_bound_report(paths[1], 'candidate', lambda report: report['cases'].pop())
        self.assertFalse(self.comparison(paths)['gate_accepted'])

    def test_unknown_check_is_not_a_parent_failure_or_candidate_win(self):
        paths = self.pair()
        self.edit_bound_report(paths[1], 'candidate', lambda report:
            report['cases'][1]['checks']['task_completion'].update(status='unknown'))
        result = self.comparison(paths)
        self.assertFalse(result['gate_accepted'])
        self.assertNotIn('former-failure', result['original_verdict']['gained_tasks'])

    def test_input_seed_and_budget_mismatch_are_rejected(self):
        for field, value in (('door_width_m', .5), ('target', [2., 0., 0.])):
            with self.subTest(field=field):
                paths = self.pair()
                self.edit_bound_report(paths[1], 'candidate', lambda report:
                    report['cases'][1]['case'].update({field: value}))
                self.assertFalse(self.comparison(paths)['gate_accepted'])
                for path in self.directory.glob('*candidate*'):
                    path.unlink()
                for path in self.directory.glob('*parent*'):
                    path.unlink()
        paths = self.pair()
        self.edit_bound_report(paths[1], 'candidate', lambda report:
            report['cases'][1]['execution_budget'].update(command_timeout_s=180))
        self.assertFalse(self.comparison(paths)['gate_accepted'])

    def test_removed_original_check_cannot_create_success(self):
        paths = self.pair()
        self.edit_bound_report(paths[1], 'candidate', lambda report:
            report['cases'][1]['checks'].pop('task_completion'))
        result = self.comparison(paths)
        self.assertFalse(result['gate_accepted'])
        self.assertIn('check set differs', ' '.join(result['rejection_reasons']))

    def test_claimed_success_with_failed_check_rejects(self):
        paths = self.pair()
        self.edit_bound_report(paths[1], 'candidate', lambda report:
            report['cases'][1]['checks']['task_completion'].update(status='failed'))
        self.assertFalse(self.comparison(paths)['gate_accepted'])

    def test_minimum_gain_threshold_is_applied_after_original_verdict(self):
        self.panel['thresholds']['min_new_successes'] = 2
        self.write(self.panel_path, self.panel)
        self.assertFalse(self.comparison(self.pair())['gate_accepted'])

    def test_before_snapshot_refuses_existing_report(self):
        path = self.directory/'already.json'
        self.write(path, {})
        with self.assertRaisesRegex(ValueError, 'absent report'):
            gate.snapshot(self.panel_path, self.source, path, 'before')

    def test_selection_change_after_before_snapshot_is_rejected(self):
        paths = self.pair()
        self.panel['cases'][0]['inputs']['target'][0] = 1.3
        self.write(self.panel_path, self.panel)
        self.assertFalse(self.comparison(paths)['gate_accepted'])

    def test_cli_rejection_exit_and_private_new_output(self):
        paths = self.pair()
        output = self.directory/'diagnostic.json'
        command = [sys.executable, '-B', str(TOOLS/'fishbot_stack_gate.py'), 'compare',
                   '--panel', str(self.panel_path), '--parent', str(paths[0]), '--candidate', str(paths[1]),
                   '--output', str(output)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(gate.load(output)['gate_accepted'])
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        old = output.read_bytes()
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(output.read_bytes(), old)

    def test_partial_receipts_and_duplicate_json_are_input_errors(self):
        paths = self.pair()
        result = subprocess.run([sys.executable, '-B', str(TOOLS/'fishbot_stack_gate.py'), 'compare',
            '--panel', str(self.panel_path), '--parent', str(paths[0]), '--candidate', str(paths[1]),
            '--parent-before', str(self.receipts['parent_before']), '--output', str(self.directory/'bad.json')],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.directory/'bad.json').exists())
        self.panel_path.write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON'):
            gate.load(self.panel_path)

    def test_malformed_boundary_receipt_is_input_error(self):
        paths = self.pair()
        self.write(self.receipts['candidate_after'], [])
        with self.assertRaisesRegex(ValueError, 'JSON objects'):
            self.comparison(paths)

    def test_check_evidence_key_missing_cannot_be_promoted(self):
        paths = self.pair()
        self.edit_bound_report(paths[1], 'candidate', lambda report:
            report['cases'][1]['checks']['task_completion'].pop('evidence'))
        self.assertFalse(self.comparison(paths)['gate_accepted'])

    def test_cli_accepts_only_complete_admissible_fixture(self):
        paths = self.pair()
        command = [sys.executable, '-B', str(TOOLS/'fishbot_stack_gate.py'), 'compare',
                   '--panel', str(self.panel_path), '--parent', str(paths[0]), '--candidate', str(paths[1]),
                   '--output', str(self.directory/'accepted.json')]
        for name, path in self.receipts.items():
            command.extend(['--'+name.replace('_', '-'), str(path)])
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(gate.load(self.directory/'accepted.json')['gate_accepted'])

    def test_licensed_verdict_is_exact_upstream_excerpt_except_indentation(self):
        import ast
        import hashlib
        source = (TOOLS/'recursia_verdict.py').read_text()
        function = next(node for node in ast.walk(ast.parse(source))
                        if isinstance(node, ast.FunctionDef) and node.name == 'verdict')
        lines = ast.get_source_segment(source, function).splitlines()
        original = lines[0]+'\n'+'\n'.join('    '+line for line in lines[1:])
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),
                         'b50de7ad8fb9a7fb8d1b5e941c19f1133a76f4f0985e48140305a39164f380d9')

    def test_help_and_import_do_not_load_ros(self):
        result = subprocess.run([sys.executable, '-I', '-c',
            'import runpy,sys;sys.path.insert(0,sys.argv[1]);runpy.run_path(sys.argv[2]);'
            'assert "rclpy" not in sys.modules', str(TOOLS), str(TOOLS/'fishbot_stack_gate.py')],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([sys.executable, str(TOOLS/'fishbot_stack_gate.py'), '--help'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
