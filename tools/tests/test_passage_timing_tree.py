"""Execute production timing XML with installed BTCPP/Nav2 control plugins.

Only the navigation/service actions are substitutes. No ROS context, process,
topic, or hardware connection is created. Missing local libraries are reported
as skipped validation, rather than replaced with a Python model of the tree.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class PassageTimingTreeTest(unittest.TestCase):
    def test_installed_behavior_tree_execution(self):
        compiler = shutil.which('g++')
        prefix = Path('/opt/ros/jazzy')
        dependencies = [
            prefix/'include/behaviortree_cpp/bt_factory.h',
            prefix/'lib/libbehaviortree_cpp.so',
            *[prefix/f'lib/libnav2_{name}_bt_node.so' for name in (
                'recovery_node', 'pipeline_sequence', 'rate_controller',
                'are_error_codes_active_condition')],
        ]
        missing = [str(path) for path in dependencies if not path.is_file()]
        if compiler is None or missing:
            self.skipTest('Installed Jazzy BTCPP execution unavailable: '
                          + (', '.join(missing) or 'g++ not found'))
        source = Path(__file__).with_suffix('.cpp')
        xml = source.parents[1]/'config/fishbot_passage_tolerant_tree.xml'
        environment = dict(os.environ)
        environment['LD_LIBRARY_PATH'] = str(prefix/'lib') + os.pathsep + environment.get(
            'LD_LIBRARY_PATH', '')
        with tempfile.TemporaryDirectory(prefix='fishbot-bt-offline-') as temporary:
            executable = Path(temporary)/'timing-tree-test'
            compile_result = subprocess.run([
                compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                '-I'+str(prefix/'include'), str(source), '-o', str(executable),
                '-L'+str(prefix/'lib'), '-lbehaviortree_cpp', '-ldl', '-pthread',
            ], capture_output=True, text=True, env=environment, timeout=60)
            self.assertEqual(compile_result.returncode, 0,
                             compile_result.stdout + compile_result.stderr)
            result = subprocess.run([str(executable), str(xml)],
                                    capture_output=True, text=True,
                                    env=environment, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('11 offline behavior scenarios passed', result.stdout)
            print(result.stdout.rstrip())


if __name__ == '__main__':
    unittest.main()
