"""Render the actual launch actions; never run a LaunchService or ROS graph probe."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from launch import LaunchContext
from launch.actions import GroupAction, SetLaunchConfiguration
from launch_ros.actions import SetRemap

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
PACKAGE = ROOT/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco'
spec = importlib.util.spec_from_file_location('manual_actual_sim_launch', PACKAGE/'launch/sim.launch.py')
sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim)


class ManualLaunchTests(unittest.TestCase):
    def setUp(self):
        # Only render actions here. Package installation is checked by the real
        # isolated launch, not assumed by this source-only regression fixture.
        prefix = patch.object(sim, 'get_package_prefix', return_value='/fixture/fishbot_mujoco')
        prefix.start(); self.addCleanup(prefix.stop)

    def context(self, output, profile='passage_manual'):
        context = LaunchContext()
        context.launch_configurations.update(control_profile=profile, map_rules='false',
            params_file=str(PACKAGE/'config/nav2.yaml'), plugins_file=str(PACKAGE/'config/plugins.yaml'),
            ros_domain_id='129', nav='true', bridge='true', manual_output_dir=str(output),
            manual_observers='fishbot_mission_bridge', map=str(PACKAGE/'config/arena.yaml'),
            resolved_params_file=str(PACKAGE/'config/nav2.yaml'))
        return context

    def test_baseline_does_not_probe_domain_or_generate_manual_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            context = self.context(Path(directory)/'unused', profile='baseline')
            with patch.object(sim.subprocess, 'run') as probe:
                actions = sim.prepare_navigation_parameters(context)
            probe.assert_not_called()
            self.assertFalse((Path(directory)/'unused').exists())
            for action in actions:
                if isinstance(action, SetLaunchConfiguration):
                    action.execute(context)
            self.assertEqual(context.launch_configurations['resolved_params_file'], str(PACKAGE/'config/nav2.yaml'))
            self.assertEqual(sim.start_manual_chain(context), [])

    def test_nonempty_domain_is_rejected_before_parameters_or_nodes_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'run'
            context = self.context(output)
            with patch.object(sim.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=0, stdout='/old_navigator\n', stderr='')):
                with self.assertRaisesRegex(RuntimeError, 'empty isolated domain'):
                    sim.prepare_navigation_parameters(context)
            self.assertFalse(output.exists())

    def test_explicit_profile_generates_single_chain_and_qualified_smoother_remap(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'run'
            context = self.context(output)
            with patch.object(sim.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=0, stdout='', stderr='')):
                actions = sim.prepare_navigation_parameters(context)
            for action in actions:
                if isinstance(action, SetLaunchConfiguration):
                    action.execute(context)
            receipt = json.loads((output/'manual-profile.json').read_text())
            self.assertIsInstance(receipt['empty_domain_checked_at_ms'], int)
            self.assertEqual(context.launch_configurations['manual_profile_receipt'], str(output/'manual-profile.json'))
            chain = sim.start_manual_chain(context)
            self.assertEqual(len(chain), 3)  # guard exit handler, original guard, stock mux
            timers = sim.start_navigation(context)
            group = next(action for action in timers[0].actions if isinstance(action, GroupAction))
            remaps = [action for action in group.get_sub_entities() if isinstance(action, SetRemap)]
            for action in remaps:
                action.execute(context)
            self.assertEqual(context.launch_configurations['ros_remaps'],
                [('velocity_smoother:cmd_vel', '/cmd_vel_selected'), ('/cmd_vel', '/cmd_vel_nav')])


if __name__ == '__main__':
    unittest.main()
