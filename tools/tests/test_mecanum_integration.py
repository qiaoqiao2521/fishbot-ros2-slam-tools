import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / 'workspaces/mecanum_ws/src/robot_base'


class MecanumIntegrationTests(unittest.TestCase):
    def test_root_entry_works_outside_checkout_without_opening_ros_or_serial(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([str(ROOT/'fishbot.sh'), 'mecanum', 'info'], cwd=folder, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        info = json.loads(result.stdout)
        self.assertEqual(info['vehicle'], 'robot_base_mecanum')
        self.assertEqual(Path(info['source']), PACKAGE)
        self.assertIn('Twist vx/vy/wz', info['interfaces'])
        self.assertEqual(info['legacy_nav_lateral_velocity_limit_m_s'], 0.)
        self.assertIn('not accepted', info['status'])
        self.assertEqual(info['simulation']['scene_profile']['vehicle'], info['vehicle'])
        self.assertEqual(info['simulation']['cli'], './fishbot.sh cooperation')

    def test_packaging_has_provenance_and_no_nested_checkout_or_historical_map(self):
        self.assertEqual(ET.parse(PACKAGE/'package.xml').getroot().findtext('name'), 'robot_base')
        self.assertIn('Apache License', (PACKAGE/'LICENSE').read_text())
        self.assertTrue((PACKAGE/'UPSTREAM.md').is_file())
        self.assertFalse((PACKAGE/'.git').exists())
        self.assertFalse((PACKAGE/'map').exists())
        self.assertFalse((PACKAGE/'robot_base/test_wheels.py').exists())

    def test_build_and_launch_scripts_have_valid_shell_syntax(self):
        result = subprocess.run(['bash', '-n', str(ROOT/'tools/fishbot_mecanum.sh')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
