"""Offline relocation regressions; never starts ROS processes or hardware."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from check_layout import ROOT, REQUIRED, check


class LayoutTests(unittest.TestCase):
    def test_current_layout(self):
        self.assertFalse(check())

    def test_missing_dependency_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(check(Path(tmp)))

    def test_preflight_dispatch_in_detached_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools = root / 'tools'
            tools.mkdir()
            shutil.copy2(ROOT / 'tools/fishbot_stack.sh', tools)
            (tools / 'fishbot_ros_env.sh').write_text('fishbot_ros_distro() { echo jazzy; }\n')
            probe = tools / 'fishbot_slam_preflight.sh'
            probe.write_text('#!/bin/sh\necho DETACHED_PREFLIGHT\nexit 23\n')
            probe.chmod(0o755)
            # Also exercise a legacy symlink whose parent is not the project.
            alias = root / 'legacy-stack.sh'
            alias.symlink_to(tools / 'fishbot_stack.sh')
            for entry in (tools / 'fishbot_stack.sh', alias):
                result = subprocess.run(['bash', str(entry), 'preflight-slam'], capture_output=True, text=True)
                self.assertEqual(result.returncode, 23, result.stderr)
                self.assertIn('DETACHED_PREFLIGHT', result.stdout)

    def test_help_and_unknown_command(self):
        help_run = subprocess.run(['bash', str(ROOT / 'fishbot.sh'), 'help'], capture_output=True, text=True)
        self.assertEqual(help_run.returncode, 0)
        bad_run = subprocess.run(['bash', str(ROOT / 'fishbot.sh'), 'invalid'], capture_output=True, text=True)
        self.assertEqual(bad_run.returncode, 2)

    def test_feedback_dispatch_in_detached_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copy2(ROOT / 'fishbot.sh', root)
            (root / 'tools').mkdir()
            (root / 'tools/fishbot_feedback_check.py').write_text(
                'import sys\nprint("DETACHED_FEEDBACK", sys.argv[1:])\nraise SystemExit(2)\n')
            result = subprocess.run(['bash', str(root / 'fishbot.sh'),
                                     'check-feedback', '--help'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("DETACHED_FEEDBACK ['--help']", result.stdout)

    def test_feedback_partial_cannot_report_complete_pass(self):
        from fishbot_feedback_check import exit_status, python_group
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / 'test_optional.py'
            path.write_text('import unittest\nclass Optional(unittest.TestCase):\n'
                            '    @unittest.skip("fixture dependency unavailable")\n'
                            '    def test_optional(self): pass\n'
                            '    def test_available(self): self.assertTrue(True)\n')
            with patch('fishbot_feedback_check.PYTHON_GROUPS', {'control': (path,)}):
                report = python_group('control')
            self.assertEqual(report['tests_run'], 2)
            self.assertEqual(report['status'], 'partial')
            self.assertEqual(len(report['skipped']), 1)
            self.assertEqual(exit_status([report]), 2)
            path.write_text('import fishbot_fixture_missing_dependency\n')
            with patch('fishbot_feedback_check.PYTHON_GROUPS', {'control': (path,)}):
                missing = python_group('control')
            self.assertEqual(missing['status'], 'partial')
            self.assertEqual(missing['missing_dependencies'][0]['dependency'],
                             'fishbot_fixture_missing_dependency')
            self.assertEqual(exit_status([missing]), 2)

    def test_feedback_real_failure_wins_over_partial_groups(self):
        from fishbot_feedback_check import exit_status, python_group
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / 'test_failure.py'
            path.write_text('import unittest\nclass Failure(unittest.TestCase):\n'
                            '    def test_failure(self): self.fail("fixture failure")\n')
            with patch('fishbot_feedback_check.PYTHON_GROUPS', {'control': (path,)}):
                report = python_group('control')
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(len(report['failures']), 1)
            self.assertEqual(exit_status([{'status': 'partial'}, report]), 1)


if __name__ == '__main__':
    unittest.main()
