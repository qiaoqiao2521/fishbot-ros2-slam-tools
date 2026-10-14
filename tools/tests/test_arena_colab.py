"""Offline lifecycle failures and real archive readback; no VM is exercised."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import signal
import stat
import subprocess
import tempfile
import unittest
import warnings
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('arena_colab_run', ROOT/'experiments/arena/colab_run.py')
colab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(colab)


class Clock:
    def __init__(self):
        self.value = 0

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class PendingClient:
    def __init__(self):
        self.stopped = False

    def poll(self):
        return 0 if self.stopped else None

    def terminate(self):
        self.stopped = True

    def wait(self, timeout):
        return 0


def make_bundle(directory, report):
    data = {'report.json': json.dumps(report).encode(), 'logs/install.log': b'native fixture log\n'}
    bundle = directory/'worker.zip'
    with ZipFile(bundle, 'w') as archive:
        for name, content in data.items():
            archive.writestr(name, content)
    index = {'report_final': report['report_final'], 'status': report['status'],
        'bundle': {'name': 'artifacts.zip', 'size_bytes': bundle.stat().st_size, 'sha256': colab.sha(bundle)},
        'files': {name: {'size_bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
                  for name, content in data.items()},
        'report_sha256': hashlib.sha256(data['report.json']).hexdigest()}
    return bundle, index


class Scenario(colab.ColabRun):
    """Explicit local receipt fixture, not an installed Arena or cloud success."""
    def setup(self, remote, bundle, index):
        self.fixture_report, self.fixture_bundle, self.fixture_index = remote, bundle, index
        self.commands = []
        self.download_failures = {}
        self.index_sequence, self.bundle_sequence = [], []
        self.remote_paths = []
        self.readiness_failures = 0
        self.upload_events, self.source_get_events = [], []
        self.upload_hashes = []
        self.before = {'exit_code': 0, 'connection_verified': True, 'active_assignments': 0}
        self.after = dict(self.before)
        self.stop = {'exit_code': 0, 'unassign_completed': True}
        self.poll_running = False

    def call(self, *command, limit=60, until=None):
        self.commands.append(command[0])
        if self.clock() >= (until or self.work_deadline):
            raise TimeoutError('fixture phase deadline')
        if command[0] == 'check-connection':
            return self.after if self.commands.count('check-connection') > 1 else self.before
        if command[0] == 'stop':
            return self.stop
        if command[0] == 'ls' and self.readiness_failures:
            self.readiness_failures -= 1
            self.fail(command[0], method='GET', kind='ReadTimeout')
        if command[0] == 'upload':
            self.upload_hashes.append(colab.sha(Path(command[-2])))
            event = self.upload_events.pop(0) if self.upload_events else 'ack'
            if event == 'timeout':
                self.fail(command[0], method='PUT', kind='ReadTimeout')
        if command[0] == 'download':
            path = str(command[-2])
            self.remote_paths.append(path)
            if path.endswith('-source.zip'):
                event = self.source_get_events.pop(0) if self.source_get_events else 'bytes'
                if event == '404': self.fail(command[0], method='GET', status=404)
                if event == 'timeout': self.fail(command[0], method='GET', kind='ReadTimeout')
                data = (self.output/'public-source.zip').read_bytes()
                if event == 'mismatch': data += b'partial source fixture'
                Path(command[-1]).write_bytes(data)
                return {'exit_code': 0}
            key = 'index' if path.endswith('recovery-index.json') else 'zip' if colab.BUNDLE_NAME.fullmatch(Path(path).name) else 'report'
            if self.download_failures.get(key, 0):
                self.download_failures[key] -= 1
                raise colab.CommandFailed('fixture read timeout')
            target = Path(command[-1])
            if key == 'index':
                target.write_text(json.dumps(self.index_sequence.pop(0) if self.index_sequence else self.fixture_index))
            elif key == 'zip':
                target.write_bytes(self.bundle_sequence.pop(0) if self.bundle_sequence else self.fixture_bundle.read_bytes())
            else:
                report = dict(self.fixture_report)
                if self.poll_running and self.clock() < self.work_deadline:
                    report.update(status='running', report_final=False)
                target.write_text(json.dumps(report))
        return {'exit_code': 0}

    def fail(self, command, *, method, kind=None, status=None):
        self.report['calls'].append({'command': command, 'result': {
            'exit_code': 1, 'error_category': 'timeout' if kind else 'other',
            'request_failure': {'method': method, 'type': kind, 'status_code': status,
                                'elapsed_s': 25.847 if kind == 'ReadTimeout' else 1.859}}})
        raise colab.CommandFailed('observed transport failure fixture')

    def launch(self):
        self.report['source_sha256'] = {name: colab.sha(self.root/name) for name in colab.INPUT_FILES}
        self.owned = True
        self.call('new', '-s', self.session, '--gpu', 'L4')
        self.call('exec', '-s', self.session)
        self.process = PendingClient()
        self.report['remote_execution_attempted'] = True


class ColabLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.root = self.path/'project'; self.root.mkdir()
        for name in colab.INPUT_FILES:
            file = self.root/name; file.parent.mkdir(parents=True, exist_ok=True); file.write_text('source fixture\n')
        self.adapter = self.path/'safe.py'; self.adapter.write_text('# not invoked\n')
        self.python = self.path/'python'; self.python.write_text('# not invoked\n')
        self.clock = Clock()
        self.args = argparse.Namespace(output=self.path/'new-output', budget_seconds=600,
            accept_eula=True, safe_cli=self.adapter, colab_python=self.python)
        self.failed = {'status': 'failed', 'phase': 'smoke', 'report_final': True,
            'arena_smoke_completed': False, 'pipeline_completed': False, 'inputs_unchanged': True,
            'policy_success': None}
        self.completed = dict(self.failed, status='completed', arena_smoke_completed=True,
                              pipeline_completed=True, policy_success=False)

    def job(self, report=None):
        report = dict(report or self.failed)
        hashes = {name: colab.sha(self.root/name) for name in colab.INPUT_FILES}
        report.update(input_sha256_before=hashes, input_sha256_after=hashes)
        bundle, index = make_bundle(self.path, report)
        job = Scenario(self.args, root=self.root, clock=self.clock.now, sleep=self.clock.sleep)
        job.setup(report, bundle, index)
        return job

    def test_missing_explicit_license_and_existing_output_never_create_scope(self):
        for changed in (dict(accept_eula=False), dict(budget_seconds=599), dict(budget_seconds=2701)):
            args = copy.copy(self.args)
            for key, value in changed.items():
                setattr(args, key, value)
            with self.assertRaises(ValueError):
                colab.ColabRun(args, root=self.root)
            self.assertFalse(args.output.exists())
        self.args.output.mkdir(); (self.args.output/'old').write_text('preserve')
        with self.assertRaisesRegex(ValueError, 'new private'):
            colab.ColabRun(self.args, root=self.root)
        self.assertEqual((self.args.output/'old').read_text(), 'preserve')

    def test_scope_permissions_and_unique_identity_without_reading_auth(self):
        first = self.job()
        self.assertEqual(stat.S_IMODE(first.output.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((first.output/'private-session').stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((first.output/'private-session/sessions.json').stat().st_mode), 0o600)
        self.args.output = self.path/'second-output'
        second = Scenario(self.args, root=self.root, clock=self.clock.now, sleep=self.clock.sleep)
        self.assertNotEqual(first.session, second.session)

    def test_failed_remote_does_not_wait_for_pending_local_exec(self):
        job = self.job()
        self.assertEqual(job.run(), 1)
        self.assertLess(self.clock.value, 10)
        self.assertTrue(job.report['artifact_recovery_verified'])
        self.assertTrue(job.report['diagnostic_closure_verified'])
        self.assertFalse(job.report['successful'])
        self.assertTrue(job.report['local_exec_client_stopped'])
        self.assertEqual(job.commands.count('new'), 1)
        self.assertEqual(job.commands.count('exec'), 1)
        self.assertLess(max(i for i, name in enumerate(job.commands) if name == 'download'), job.commands.index('stop'))

    def test_active_or_unknown_account_declines_allocation(self):
        for count in (1, None, False):
            self.args.output = self.path/('output-' + str(count))
            job = self.job(); job.before['active_assignments'] = count
            self.assertEqual(job.run(), 1)
            self.assertNotIn('new', job.commands)
            self.assertNotIn('stop', job.commands)

    def test_transient_exact_reads_retry_without_reallocating_or_reexecuting(self):
        job = self.job(); job.download_failures['index'] = 2
        self.assertEqual(job.run(), 1)
        self.assertTrue(job.report['artifact_recovery_verified'])
        self.assertEqual(job.download_failures['index'], 0)
        self.assertEqual(job.commands.count('new'), 1)
        self.assertEqual(job.commands.count('exec'), 1)

    def test_real_launcher_refuses_insufficient_remote_budget(self):
        job = self.job()
        self.clock.value = job.work_deadline-119
        with patch.object(colab.subprocess, 'Popen') as execute:
            with self.assertRaisesRegex(TimeoutError, 'insufficient work budget'):
                colab.ColabRun.launch(job)
            execute.assert_not_called()
        self.assertIs(job.report['remote_execution_attempted'], False)

    def test_real_launcher_pins_input_bytes_and_passes_only_explicit_license(self):
        job = self.job()
        with patch.object(colab.subprocess, 'Popen', return_value=PendingClient()) as execute:
            colab.ColabRun.launch(job)
        command = execute.call_args.args[0]
        self.assertEqual(command[:len(job.prefix)], job.prefix)
        self.assertEqual(command[len(job.prefix)], 'exec')
        launch = (job.output/'launch.py').read_text()
        compile(launch, 'launch.py', 'exec')
        self.assertIn('"--accept-eula"', launch)
        self.assertIn('hashlib.sha256(data).hexdigest()==digest', launch)
        self.assertNotIn('extractall', launch)
        self.assertEqual(command[-1], str(int(job.work_deadline-self.clock.value)+30))

    def test_uploaded_input_identity_must_match_local_source_freeze(self):
        job = self.job(self.completed)
        job.fixture_report['input_sha256_after'] = {'wrong-input': '0'*64}
        job.fixture_bundle, job.fixture_index = make_bundle(self.path, job.fixture_report)
        self.assertEqual(job.run(), 1)
        self.assertFalse(job.report['uploaded_inputs_verified'])
        self.assertTrue(job.report['artifact_recovery_verified'])

    def real_launch(self, job):
        job.launch = lambda: colab.ColabRun.launch(job)

    def test_observed_put_timeout_readback_confirms_bytes_without_second_put(self):
        job = self.job(); self.real_launch(job)
        job.upload_events = ['timeout']
        job.source_get_events = ['bytes']
        with patch.object(colab.subprocess, 'Popen', return_value=PendingClient()) as execute:
            self.assertEqual(job.run(), 1)  # Native failure fixture; no GPU acceptance.
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(job.commands.count('new'), 1)
        self.assertEqual(job.commands.count('upload'), 1)
        self.assertEqual(job.report['upload_delivery'], 'verified_after_timeout')
        self.assertEqual(colab.sha(job.output/'upload-readback-1.zip'), job.report['upload_identity']['sha256'])

    def test_confirmed_404_allows_identical_second_put_without_new_allocation(self):
        job = self.job(); self.real_launch(job)
        job.upload_events, job.source_get_events = ['timeout', 'ack'], ['404']
        with patch.object(colab.subprocess, 'Popen', return_value=PendingClient()) as execute:
            self.assertEqual(job.run(), 1)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(job.commands.count('new'), 1)
        self.assertEqual(job.commands.count('upload'), 2)
        self.assertEqual(len(set(job.upload_hashes)), 1)
        self.assertEqual(job.report['upload_delivery'], 'acknowledged')

    def test_uncertain_upload_get_does_not_retry_put_or_execute_or_fetch_artifacts(self):
        for event in ('timeout', 'mismatch'):
            self.args.output = self.path/('unknown-upload-' + event)
            job = self.job(); self.real_launch(job)
            job.upload_events, job.source_get_events = ['timeout'], [event]
            with patch.object(colab.subprocess, 'Popen') as execute:
                self.assertEqual(job.run(), 1)
                execute.assert_not_called()
            self.assertEqual(job.commands.count('new'), 1)
            self.assertEqual(job.commands.count('upload'), 1)
            self.assertEqual(job.report['recovery_status'], 'not_applicable')
            self.assertTrue(job.report['diagnostic_closure_verified'])
            self.assertFalse(job.report['successful'])
            self.assertEqual(job.commands.count('download'), 1)
            self.assertTrue(all(path.endswith('-source.zip') for path in job.remote_paths))

    def test_three_confirmed_absent_upload_attempts_are_bounded_and_locally_closed(self):
        job = self.job(); self.real_launch(job)
        job.upload_events, job.source_get_events = ['timeout']*3, ['404']*3
        with patch.object(colab.subprocess, 'Popen') as execute:
            self.assertEqual(job.run(), 1)
            execute.assert_not_called()
        self.assertEqual(job.commands.count('upload'), 3)
        self.assertEqual(job.commands.count('new'), 1)
        self.assertTrue(job.report['diagnostic_closure_verified'])
        self.assertEqual(job.report['recovery_status'], 'not_applicable')

    def test_runtime_contents_probe_is_read_only_and_bounded(self):
        for failures in (2, 3):
            self.args.output = self.path/('readiness-' + str(failures))
            job = self.job(); self.real_launch(job); job.readiness_failures = failures
            with patch.object(colab.subprocess, 'Popen', return_value=PendingClient()) as execute:
                self.assertEqual(job.run(), 1)
            self.assertEqual(job.commands.count('ls'), 3)
            self.assertEqual(job.commands.count('new'), 1)
            if failures == 3:
                execute.assert_not_called()
                self.assertNotIn('upload', job.commands)
                self.assertNotIn('download', job.commands)
                self.assertEqual(job.report['recovery_status'], 'not_applicable')
                self.assertTrue(job.report['diagnostic_closure_verified'])
            else:
                self.assertEqual(execute.call_count, 1)
                self.assertTrue(job.report['runtime_contents_ready'])

    def test_generation_pointer_selects_the_exact_safe_remote_name(self):
        job = self.job(self.completed)
        name = 'artifacts-' + 'a'*32 + '.zip'
        job.fixture_index['bundle']['name'] = name
        self.assertEqual(job.run(), 0)  # Local readback fixture only.
        self.assertEqual(job.report['recovered_generation'], name)
        self.assertIn(job.remote+'/work/'+name, job.remote_paths)
        self.assertNotIn(job.remote+'/work/artifacts.zip', job.remote_paths)

    def test_old_checkpoint_pair_retries_and_retains_bytes_before_final_pair(self):
        job = self.job(self.completed)
        final_bytes, final_index = job.fixture_bundle.read_bytes(), copy.deepcopy(job.fixture_index)
        partial_report = dict(job.fixture_report, status='running', report_final=False, pipeline_completed=False)
        partial_bundle, partial_index = make_bundle(self.path, partial_report)
        partial_bytes = partial_bundle.read_bytes()
        partial_index['bundle']['name'] = 'artifacts-' + 'a'*32 + '.zip'
        final_index['bundle']['name'] = 'artifacts-' + 'b'*32 + '.zip'
        job.index_sequence = [partial_index, final_index]
        job.bundle_sequence = [partial_bytes, final_bytes]
        self.assertEqual(job.run(), 0)  # Local readback fixture only.
        self.assertEqual(job.report['recovery_attempts'], 2)
        self.assertEqual((job.output/'recovery-attempts/attempt-01/artifacts.zip').read_bytes(), partial_bytes)
        self.assertEqual((job.output/'artifacts.zip').read_bytes(), final_bytes)
        self.assertNotIn('recovery_error_type', job.report)
        self.assertEqual(job.commands.count('new'), 1)
        self.assertEqual(job.commands.count('exec'), 1)

    def test_get_success_with_hash_mismatch_retries_pair_then_verifies_final(self):
        job = self.job(self.completed)
        index = copy.deepcopy(job.fixture_index)
        index['bundle']['name'] = 'artifacts-' + 'c'*32 + '.zip'
        job.index_sequence = [index, index]
        correct = job.fixture_bundle.read_bytes()
        wrong = correct + b'old response fixture'
        job.bundle_sequence = [wrong, correct]
        self.assertEqual(job.run(), 0)  # Local readback fixture only.
        self.assertEqual(job.report['recovery_attempts'], 2)
        self.assertEqual((job.output/'recovery-attempts/attempt-01/artifacts.zip').read_bytes(), wrong)
        self.assertEqual((job.output/'artifacts.zip').read_bytes(), correct)
        self.assertTrue(job.report['artifact_recovery_verified'])

    def test_pointer_path_injection_is_not_downloaded_or_used_for_alias_fallback(self):
        job = self.job(self.completed)
        job.fixture_index['bundle']['name'] = '../credentials.zip'
        self.assertEqual(job.run(), 1)
        self.assertTrue(job.report['runtime_released'])
        self.assertFalse(job.report['artifact_recovery_verified'])
        self.assertFalse(any('/../' in path or path.endswith('/artifacts.zip') for path in job.remote_paths))

    def test_three_nonfinal_pairs_preserve_checkpoint_without_final_pass(self):
        job = self.job(self.completed)
        partial = dict(job.fixture_report, status='running', report_final=False, pipeline_completed=False)
        job.fixture_bundle, job.fixture_index = make_bundle(self.path, partial)
        job.fixture_index['bundle']['name'] = 'artifacts-' + 'd'*32 + '.zip'
        self.assertEqual(job.run(), 1)
        self.assertTrue(job.report['checkpoint_recovered'])
        self.assertTrue(job.report['recovery_incomplete'])
        self.assertFalse(job.report['artifact_recovery_verified'])
        self.assertFalse(job.report['diagnostic_closure_verified'])
        self.assertEqual(len(list((job.output/'recovery-attempts').glob('attempt-*/artifacts.zip'))), 3)

    def test_deadline_still_recovers_failure_before_owned_stop(self):
        job = self.job(); job.poll_running = True
        self.assertEqual(job.run(), 1)
        self.assertEqual(job.report['error_type'], 'TimeoutError')
        self.assertTrue(job.report['artifact_recovery_verified'])
        self.assertTrue(job.report['runtime_released'])
        self.assertLessEqual(self.clock.value, 600)

    def test_no_final_index_keeps_checkpoint_but_cannot_close(self):
        job = self.job(); job.download_failures['index'] = 3
        self.assertEqual(job.run(), 1)
        self.assertTrue(job.report['checkpoint_recovered'])
        self.assertFalse(job.report['artifact_recovery_verified'])
        self.assertFalse(job.report['diagnostic_closure_verified'])
        self.assertTrue(job.report['runtime_released'])

    def test_bad_manifest_cannot_be_mistaken_for_verified_recovery(self):
        job = self.job(self.completed)
        job.fixture_index['files']['logs/install.log']['sha256'] = '0'*64
        self.assertEqual(job.run(), 1)
        self.assertFalse(job.report['successful'])
        self.assertEqual(job.report['recovery_error_type'], 'ValueError')
        self.assertTrue(job.report['runtime_released'])

    def test_stop_receipt_without_independent_zero_activity_cannot_pass(self):
        for connection in ({'exit_code': 0}, {'exit_code': 0, 'connection_verified': True, 'active_assignments': 1}):
            self.args.output = self.path/('unknown-' + str(len(connection)))
            job = self.job(self.completed); job.after = connection
            self.assertEqual(job.run(), 1)
            self.assertTrue(job.report['artifact_recovery_verified'])
            self.assertTrue(job.report['runtime_released'])
            self.assertFalse(job.report['connection_zero_verified'])
            self.assertFalse(job.report['successful'])

    def test_worker_completed_does_not_convert_false_policy_success(self):
        job = self.job(self.completed)
        self.assertEqual(job.run(), 0)  # Lifecycle fixture only; no GPU acceptance.
        self.assertIs(job.report['policy_success'], False)
        self.assertTrue(job.report['successful'])

    def test_sigterm_enters_recovery_and_repeat_signal_is_ignored_during_stop(self):
        job = self.job()
        def interrupt():
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        job.poll = interrupt
        original_call = job.call
        def call(*command, **kwargs):
            if command[0] == 'stop':
                self.assertIs(signal.getsignal(signal.SIGTERM), signal.SIG_IGN)
            return original_call(*command, **kwargs)
        job.call = call
        previous = signal.getsignal(signal.SIGTERM)
        self.assertEqual(job.run(), 1)
        self.assertEqual(job.report['error_type'], 'KeyboardInterrupt')
        self.assertTrue(job.report['diagnostic_closure_verified'])
        self.assertIs(signal.getsignal(signal.SIGTERM), previous)

    def test_safe_timeout_discards_partial_output_and_unknown_payload(self):
        job = self.job()
        private = 'not-a-real-secret-fixture'
        with patch.object(colab.subprocess, 'run', side_effect=subprocess.TimeoutExpired('fixture', 1, output=private)):
            with self.assertRaises(colab.CommandFailed):
                colab.ColabRun.call(job, 'check-connection')
        self.assertNotIn(private, json.dumps(job.report))
        self.assertNotIn('token', colab.safe_result({'exit_code': 0, 'token': private}))


class ArchiveReadback(unittest.TestCase):
    def test_report_identity_and_finality_are_required(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = {'status': 'failed', 'report_final': True}
            bundle, original = make_bundle(root, report)
            for change in ('hash', 'report', 'final', 'file_set', 'size'):
                index = copy.deepcopy(original)
                if change == 'hash': index['bundle']['sha256'] = '0'*64
                if change == 'report': index['report_sha256'] = '0'*64
                if change == 'final': index['report_final'] = False
                if change == 'file_set': index['files'].pop('logs/install.log')
                if change == 'size': index['bundle']['size_bytes'] += 1
                with self.subTest(change=change), self.assertRaises(ValueError):
                    colab.recover(bundle, index, root/change)
                self.assertFalse((root/change).exists())

    def test_duplicate_traversal_and_symlink_archives_are_rejected(self):
        from zipfile import ZipInfo
        with tempfile.TemporaryDirectory() as temp:
            for kind in ('duplicate', 'traversal', 'symlink'):
                path = Path(temp)/(kind+'.zip')
                with ZipFile(path, 'w') as archive:
                    archive.writestr('report.json', '{}')
                    if kind == 'duplicate':
                        with warnings.catch_warnings():
                            warnings.simplefilter('ignore', UserWarning)
                            archive.writestr('report.json', '{}')
                    elif kind == 'traversal': archive.writestr('../escape.json', '{}')
                    else:
                        link = ZipInfo('link.json'); link.external_attr = (stat.S_IFLNK | 0o777) << 16
                        archive.writestr(link, 'report.json')
                with ZipFile(path) as archive, self.subTest(kind=kind), self.assertRaises(ValueError):
                    colab.archive_members(archive)


if __name__ == '__main__':
    unittest.main()
