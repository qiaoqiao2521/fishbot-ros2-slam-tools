"""Execute production-derived XML with installed BTCPP and Nav2 conditions."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('localization_fixture_native',TOOLS/'fishbot_localization_sim.launch.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class LocalizationTimingTreeTests(unittest.TestCase):
    def test_actual_complete_derived_tree_with_installed_control_plugins(self):
        compiler = shutil.which('g++')
        prefix = Path('/opt/ros/jazzy')
        if compiler is None or not (prefix/'include/behaviortree_cpp/bt_factory.h').is_file():
            self.skipTest('Installed native BTCPP compiler/dependencies unavailable')
        trees = prefix/'share/nav2_bt_navigator/behavior_trees'
        default = (trees/'navigate_to_pose_w_replanning_and_recovery.xml').read_text()
        validity = (trees/'navigate_w_recovery_and_replanning_only_if_path_becomes_invalid.xml').read_text()
        timing = (TOOLS/'config/fishbot_passage_tolerant_tree.xml').read_text()
        environment = dict(os.environ)
        environment['LD_LIBRARY_PATH'] = str(prefix/'lib')+os.pathsep+environment.get('LD_LIBRARY_PATH','')
        with tempfile.TemporaryDirectory(prefix='fishbot-localization-bt-') as directory:
            directory = Path(directory)
            derived,baseline = directory/'derived.xml',directory/'baseline.xml'
            derived.write_text(fixture.compose_navigation_tree(default,validity,timing))
            baseline.write_text(fixture.compose_navigation_tree(default,validity))
            executable = directory/'timing-test'
            compiled = subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror',
                '-I'+str(prefix/'include'),str(Path(__file__).with_suffix('.cpp')),'-o',str(executable),
                '-L'+str(prefix/'lib'),'-lbehaviortree_cpp','-ldl','-pthread'],
                capture_output=True,text=True,env=environment,timeout=60)
            self.assertEqual(compiled.returncode,0,compiled.stdout+compiled.stderr)
            result = subprocess.run([str(executable),str(derived),str(baseline)],
                capture_output=True,text=True,env=environment,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('13 complete localization timing scenarios passed',result.stdout)
            print(result.stdout.rstrip())
