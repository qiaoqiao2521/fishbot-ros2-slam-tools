"""Native evidence packaging checks; no Colab allocation or Isaac runtime."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    'arena_bootstrap', ROOT/'experiments/arena/colab_bootstrap.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class ArtifactRecovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        (self.work/'artifacts/logs').mkdir(parents=True)

    def test_failed_phase_keeps_logs_and_matching_recovery_index(self):
        payload = b'20/20 completed, followed by SIGSEGV\n'
        (self.work/'artifacts/logs/smoke.log').write_bytes(payload)
        (self.work/'artifacts/.env').write_text('excluded test fixture')
        outside = self.work/'outside.json'; outside.write_text('excluded symlink fixture')
        (self.work/'artifacts/link.json').symlink_to(outside)
        report = {'status': 'failed', 'phase': 'smoke', 'report_final': True,
                  'pipeline_completed': False}
        bundle = bootstrap.checkpoint_artifacts(self.work, report)
        index = json.loads((self.work/'recovery-index.json').read_text())
        self.assertEqual(index['bundle']['sha256'], hashlib.sha256(bundle.read_bytes()).hexdigest())
        self.assertEqual(index['bundle']['size_bytes'], bundle.stat().st_size)
        self.assertTrue(index['report_final'])
        with ZipFile(bundle) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(set(archive.namelist()), {'report.json', 'logs/smoke.log'})
            self.assertEqual(archive.read('logs/smoke.log'), payload)
            self.assertEqual(json.loads(archive.read('report.json')), report)
            for name, identity in index['files'].items():
                content = archive.read(name)
                self.assertEqual(identity['size_bytes'], len(content))
                self.assertEqual(identity['sha256'], hashlib.sha256(content).hexdigest())

    def test_final_checkpoint_replaces_partial_without_mixing_reports(self):
        bootstrap.checkpoint_artifacts(self.work, {'status': 'running', 'report_final': False})
        first = json.loads((self.work/'recovery-index.json').read_text())
        report = {'status': 'failed', 'report_final': True, 'error_type': 'TimeoutExpired'}
        bootstrap.checkpoint_artifacts(self.work, report)
        last = json.loads((self.work/'recovery-index.json').read_text())
        self.assertNotEqual(first['bundle']['sha256'], last['bundle']['sha256'])
        with ZipFile(self.work/'artifacts.zip') as archive:
            self.assertEqual(json.loads(archive.read('report.json')), report)
        self.assertFalse((self.work/'artifacts.zip.tmp').exists())
        self.assertFalse((self.work/'recovery-index.json.tmp').exists())

    def test_previous_index_keeps_its_immutable_generation_after_new_checkpoint(self):
        first_report = {'status': 'running', 'report_final': False}
        bootstrap.checkpoint_artifacts(self.work, first_report)
        first = json.loads((self.work/'recovery-index.json').read_text())
        bootstrap.checkpoint_artifacts(self.work, {'status': 'failed', 'report_final': True})
        old_bundle = self.work/first['bundle']['name']
        self.assertEqual(hashlib.sha256(old_bundle.read_bytes()).hexdigest(), first['bundle']['sha256'])
        with ZipFile(old_bundle) as archive:
            self.assertEqual(json.loads(archive.read('report.json')), first_report)

    def test_changed_and_missing_uploaded_inputs_remain_observable(self):
        for name in bootstrap.INPUT_FILES:
            path = self.work/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('input fixture')
        before = bootstrap.input_hashes(self.work)
        (self.work/bootstrap.INPUT_FILES[0]).write_text('changed fixture')
        (self.work/bootstrap.INPUT_FILES[1]).unlink()
        after = bootstrap.input_hashes(self.work)
        self.assertNotEqual(before, after)
        self.assertIsNone(after[bootstrap.INPUT_FILES[1]])


class SmokeEvidence(unittest.TestCase):
    def setUp(self):
        self.receipt = {'returncode': 0, 'source_unchanged': True,
                        'source_after': {'verified': True}}
        self.log = 'Steps: 100%|##########| 20/20 [00:02]\n[INFO]: SimulationContext cleared\n'

    def test_completed_native_steps_and_normal_receipt_are_required(self):
        evidence = bootstrap.smoke_readback(self.receipt, self.log)
        self.assertEqual(evidence['steps_completed'], 20)
        self.assertEqual(evidence['returncode'], 0)
        self.assertEqual(evidence['log_sha256'], hashlib.sha256(self.log.encode()).hexdigest())

    def test_twenty_steps_do_not_hide_crash_or_notebook_shutdown_mode(self):
        for marker in ('SIGSEGV: 11', 'fast shutdown not supported with jupyter notebooks'):
            with self.subTest(marker=marker), self.assertRaises(RuntimeError):
                bootstrap.smoke_readback(self.receipt, self.log+marker)

    def test_exit_zero_without_steps_or_source_readback_is_incomplete(self):
        for receipt, log in ((self.receipt, ''), (self.receipt, self.log.replace('20/20', '19/20')),
                             (self.receipt, self.log.replace('SimulationContext cleared', ''))):
            with self.subTest(log=log), self.assertRaises(RuntimeError):
                bootstrap.smoke_readback(receipt, log)
        for key, value in (('returncode', False), ('returncode', -11), ('source_unchanged', False)):
            receipt = copy.deepcopy(self.receipt); receipt[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                bootstrap.smoke_readback(receipt, self.log)


class NativeGroupCleanup(unittest.TestCase):
    def test_leader_exit_does_not_leave_term_ignoring_native_child(self):
        with tempfile.TemporaryDirectory(prefix='arena-native-cleanup-') as name:
            child_pid_file = Path(name)/'native-child.pid'
            child_script = (
                'import os,pathlib,signal,time;'
                'signal.signal(signal.SIGTERM,signal.SIG_IGN);'
                f'pathlib.Path({str(child_pid_file)!r}).write_text(str(os.getpid()));'
                'time.sleep(30)'
            )
            leader_script = (
                'import subprocess,sys,time;'
                f'subprocess.Popen([sys.executable,"-c",{child_script!r}]);'
                'time.sleep(30)'
            )
            process = subprocess.Popen([sys.executable, '-c', leader_script],
                                       start_new_session=True)
            try:
                ready_deadline = time.monotonic()+5
                child_pid = None
                while time.monotonic() < ready_deadline:
                    try:
                        child_pid = int(child_pid_file.read_text())
                    except (FileNotFoundError, ValueError):
                        pass
                    if child_pid is not None:
                        break
                    time.sleep(.02)
                self.assertIsNotNone(child_pid, 'native child did not become ready')
                result = bootstrap.stop_owned_group(process, grace=.2)
                self.assertTrue(result['sigkill_sent'])
                self.assertIsNotNone(result['leader_returncode'])
                stopped_deadline = time.monotonic()+2
                child_stat = Path(f'/proc/{child_pid}/stat')
                state = None
                while time.monotonic() < stopped_deadline:
                    try:
                        state = child_stat.read_text().split()[2]
                    except FileNotFoundError:
                        state = None
                    if state in (None, 'Z', 'X'):
                        break
                    time.sleep(.02)
                self.assertIn(state, (None, 'Z', 'X'), 'native child survived owned group cleanup')
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
