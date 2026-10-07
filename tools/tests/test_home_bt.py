"""Run the shipped fallback with native BT controls and fake action leaves."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

TOOLS = Path(__file__).resolve().parents[1]
ROS = Path('/opt/ros/jazzy')


class NativeHomeTree(unittest.TestCase):
    def test_controller_handoff_and_halt(self):
        if not shutil.which('g++') or not (ROS / 'include/behaviortree_cpp').is_dir():
            self.skipTest('native boundary check requires installed Jazzy and g++')
        document = ET.parse(TOOLS / 'config/fishbot_home_tree.xml')
        fallback = document.find(".//Fallback[@name='BoundedControllerFallback']")
        self.assertIsNotNone(fallback)
        self.assertEqual(document.find('.//RecoveryNode').get('number_of_retries'), '1')
        root = ET.Element('root', BTCPP_format='4', main_tree_to_execute='Test')
        ET.SubElement(root, 'BehaviorTree', ID='Test').append(fallback)
        with tempfile.TemporaryDirectory(prefix='fishbot-home-bt-') as directory:
            directory = Path(directory)
            xml = directory / 'fallback.xml'
            ET.ElementTree(root).write(xml, encoding='unicode')
            executable = directory / 'home_bt_boundary'
            includes = [f'-I{ROS / "include"}']
            includes += [f'-I{path}' for path in (ROS / 'include').iterdir() if path.is_dir()]
            compiled = subprocess.run(['g++', '-std=c++17', '-O0', *includes,
                            str(TOOLS / 'tests/home_bt_boundary.cpp'),
                            f'-L{ROS / "lib"}', f'-Wl,-rpath,{ROS / "lib"}',
                            '-lbehaviortree_cpp', '-o', str(executable)],
                           capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            env = dict(os.environ, LD_LIBRARY_PATH=str(ROS / 'lib'))
            result = subprocess.run([str(executable), str(xml)], env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('11 native BT lifecycle scenarios passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
