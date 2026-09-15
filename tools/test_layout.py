"""Offline relocation regressions; never starts ROS processes or hardware."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
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


if __name__ == '__main__':
    unittest.main()
