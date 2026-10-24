"""Optional native transport selection preserves shared physical contracts."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    'f1_candidate', ROOT/'experiments/kaggle/f1_candidate.py')
CANDIDATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CANDIDATE)
RUN_SPEC = importlib.util.spec_from_file_location('f1_run', ROOT/'experiments/kaggle/f1_run.py')
RUNNER = importlib.util.module_from_spec(RUN_SPEC)
RUN_SPEC.loader.exec_module(RUNNER)
PRESET = ROOT/'experiments/kaggle/graceful-j100.yaml'


class NativeTransportSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.nav_path = self.folder/'nav2.yaml'
        self.path = self.folder/'scene-manifest.json'
        self.controllers = {
            'FollowPath': {'plugin': 'nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController',
                           'use_collision_detection': True},
            'StagingPath': {'plugin': 'nav2_rotation_shim_controller::RotationShimController',
                            'allow_reversing': True, 'desired_linear_vel': .12},
            'general_goal_checker': {'xy_goal_tolerance': .015, 'yaw_goal_tolerance': .035},
            'progress_checker': {'required_movement_radius': .15}}
        self.nav = {
            'controller_server': {'ros__parameters': copy.deepcopy(self.controllers)},
            'planner_server': {'ros__parameters': {'HeadingAware': {'plugin': 'nav2_smac_planner/SmacPlannerLattice'}}},
            'global_costmap': {'global_costmap': {'ros__parameters': {'footprint_padding': .04}}},
            'local_costmap': {'local_costmap': {'ros__parameters': {'footprint_padding': .01}}},
            'velocity_smoother': {'ros__parameters': {'stamp_smoothed_velocity_with_smoothing_time': False}}}
        self.limits = {'max_accel': [.025, 0., .05], 'max_decel': [-.025, 0., -.05],
                       'max_velocity': [.03, 0., .05], 'min_velocity': [-.03, 0., -.05]}
        self.progress = {'progress_checker.required_movement_radius': .005,
                         'progress_checker.required_movement_angle': .05}
        self.manifest = {
            'nav2_yaml': str(self.nav_path), 'world_xml': '/fixture/original-world.xml',
            'spawn': [0., -2., 0.], 'spawn_yaw': 0., 'delivery_pose': {'x': .7, 'y': -2., 'yaw': 0.},
            'vehicle_profile': {'loaded_velocity_smoother': copy.deepcopy(self.limits),
                                'loaded_controller': {
                                    'FollowPath.desired_linear_vel': .03,
                                    'FollowPath.min_approach_linear_velocity': .005,
                                    **self.progress}}}
        self.nav_path.write_text(yaml.safe_dump(self.nav))
        self.path.write_text(json.dumps(self.manifest))

    def read(self):
        return json.loads(self.path.read_text()), yaml.safe_load(self.nav_path.read_text())

    def assert_shared_contracts(self, manifest, nav):
        controllers = nav['controller_server']['ros__parameters']
        for name in ('StagingPath', 'general_goal_checker', 'progress_checker'):
            self.assertEqual(controllers[name], self.controllers[name])
        self.assertEqual(nav['local_costmap'], self.nav['local_costmap'])
        self.assertFalse(nav['velocity_smoother']['ros__parameters']['stamp_smoothed_velocity_with_smoothing_time'])
        for key in ('world_xml', 'spawn', 'spawn_yaw', 'delivery_pose'):
            self.assertEqual(manifest[key], self.manifest[key])
        limits = manifest['vehicle_profile']['loaded_velocity_smoother']
        self.assertEqual(limits['max_accel'], self.limits['max_accel'])
        self.assertEqual(limits['max_decel'], self.limits['max_decel'])
        self.assertEqual(limits['max_velocity'], [.06, 0., .10])
        self.assertEqual(limits['min_velocity'], [-.06, 0., -.10])
        self.assertFalse(manifest['kaggle_candidate']['qualified'])

    def test_default_keeps_rpp_and_shared_contracts(self):
        CANDIDATE.configure(self.path)
        manifest, nav = self.read()
        self.assert_shared_contracts(manifest, nav)
        controller = nav['controller_server']['ros__parameters']['FollowPath']
        self.assertTrue(controller['use_collision_detection'])
        self.assertEqual(controller['desired_linear_vel'], .06)
        self.assertEqual(controller['curvature_lookahead_dist'], .3)
        self.assertEqual(manifest['vehicle_profile']['loaded_controller']['FollowPath.desired_linear_vel'], .06)
        self.assertNotIn('transport_controller', manifest)

    def test_graceful_is_native_transport_only_and_copies_input(self):
        CANDIDATE.configure(self.path, PRESET)
        manifest, nav = self.read()
        self.assert_shared_contracts(manifest, nav)
        expected = yaml.safe_load(PRESET.read_text())['controller_server']['ros__parameters']['FollowPath']
        self.assertEqual(nav['controller_server']['ros__parameters']['FollowPath'], expected)
        self.assertEqual(manifest['vehicle_profile']['loaded_controller'], self.progress)
        self.assertEqual(Path(manifest['transport_controller']['prepared_copy']).read_bytes(), PRESET.read_bytes())
        self.assertEqual(manifest['transport_controller']['plugin'], 'nav2_graceful_controller::GracefulController')

    def test_reconfigure_preserves_native_selection_and_human_edit(self):
        CANDIDATE.configure(self.path, PRESET)
        _, nav = self.read()
        nav['controller_server']['ros__parameters']['FollowPath']['min_lookahead'] = .25
        self.nav_path.write_text(yaml.safe_dump(nav))
        CANDIDATE.configure(self.path)
        manifest, nav = self.read()
        self.assertEqual(nav['controller_server']['ros__parameters']['FollowPath']['min_lookahead'], .25)
        self.assertEqual(manifest['vehicle_profile']['loaded_controller'], self.progress)
        # Reusing the prepared copy itself must not fail with SameFileError.
        CANDIDATE.configure(self.path, self.folder/'transport-controller.yaml')

    def test_native_smoothing_is_explicit_and_preserves_physical_contracts(self):
        CANDIDATE.configure(self.path, PRESET, lattice_smooth_path=True)
        manifest, nav = self.read()
        self.assert_shared_contracts(manifest, nav)
        self.assertTrue(nav['planner_server']['ros__parameters']['HeadingAware']['smooth_path'])
        # An absent selection must preserve a later human edit.
        CANDIDATE.configure(self.path)
        _, nav = self.read()
        self.assertTrue(nav['planner_server']['ros__parameters']['HeadingAware']['smooth_path'])
        CANDIDATE.configure(self.path, lattice_smooth_path=False)
        _, nav = self.read()
        self.assertFalse(nav['planner_server']['ros__parameters']['HeadingAware']['smooth_path'])

    def test_native_selection_without_progress_does_not_leave_empty_adapter(self):
        self.manifest['vehicle_profile']['loaded_controller'] = {'FollowPath.desired_linear_vel': .03}
        self.path.write_text(json.dumps(self.manifest))
        CANDIDATE.configure(self.path, PRESET)
        manifest, _ = self.read()
        self.assertNotIn('loaded_controller', manifest['vehicle_profile'])


class FactoryInputSelectionTests(unittest.TestCase):
    def prepare(self, explicit=None, smoothing=None):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            calls = []
            env = {'FISHBOT_F1_FACTORY_CONFIG': explicit} if explicit else {}
            if smoothing is not None:
                env['FISHBOT_LATTICE_SMOOTH_PATH'] = smoothing
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(RUNNER, 'ARTIFACTS', folder), \
                    mock.patch.object(RUNNER, 'run', side_effect=lambda label, args, **kw:
                                      calls.append((label, args))):
                RUNNER.prepare_scene(ROOT, Path('/fixture/so101'), sys.executable,
                                     Path('/fixture/data'), {})
            actual = json.loads((folder/'factory.json').read_text())
            self.candidate_args = dict(calls)['candidate-configuration']
            args = dict(calls)['scene-prepare']
            self.assertEqual(args[args.index('--factory-config')+1], str(folder/'factory.json'))
            return actual

    def test_smoothing_selection_reaches_candidate_entry(self):
        self.prepare(smoothing='1')
        self.assertIn('--lattice-smooth-path', self.candidate_args)
        self.assertIn(str(ROOT/'experiments/kaggle/f1_candidate.py'), self.candidate_args)
        self.prepare()
        self.assertNotIn('--lattice-smooth-path', self.candidate_args)

    def test_native_entry_only_changes_b_approach(self):
        candidate = self.prepare('tools/config/factory_delivery/line-side-j100-native-entry.json')
        point = next(x for x in candidate['destinations'] if x['id'] == 'line_b')
        self.assertEqual(point.pop('approach_poses'),
                         [{'x': 1.25, 'y': -2., 'yaw': 0.4636476090008061}])
        original = json.loads((ROOT/'tools/config/factory_delivery/line-side-occupied.json').read_text())
        self.assertEqual(candidate, original)

    def test_default_preserves_original_approach(self):
        factory = self.prepare()
        point = next(x for x in factory['destinations'] if x['id'] == 'line_b')
        self.assertEqual(point['approach_poses'], [{'x': 1.35, 'y': -2., 'yaw': 0.}])

    def test_explicit_factory_keeps_pose_and_all_business_inputs(self):
        relative = 'tools/config/factory_delivery/line-side-j100-tangent-040.json'
        source = ROOT/relative
        original = source.read_bytes()
        self.assertEqual(self.prepare(relative), json.loads(original))
        self.assertEqual(source.read_bytes(), original)


class NativeBuildArgumentsTests(unittest.TestCase):
    def check_packages(self, packages):
        with tempfile.TemporaryDirectory(prefix='f1 native path ') as temp:
            folder = Path(temp)
            capture = folder/'args.json'
            fake = folder/'fake colcon.py'
            fake.write_text('import json,os,sys\nfrom pathlib import Path\n'
                           'Path(os.environ["FISHBOT_TEST_ARG_OUTPUT"]).write_text(json.dumps(sys.argv[1:]))\n')
            native = folder/'native runtime'
            subprocess.run(['bash', '-ec', RUNNER.NATIVE_BUILD_SHELL, 'test-native-build',
                            str(native), sys.executable, str(fake), *packages], check=True,
                           env=dict(os.environ, FISHBOT_TEST_ARG_OUTPUT=str(capture)),
                           capture_output=True, text=True)
            args = json.loads(capture.read_text())
            start = args.index('--base-paths')+1
            end = args.index('--build-base')
            self.assertEqual(args[start:end], [str(native/'src/navigation2'/p) for p in packages])
            start = args.index('--packages-select')+1
            end = args.index('--allow-overriding')
            self.assertEqual(args[start:end], packages)
            self.assertEqual(args[args.index('--install-base')+1], str(native/'install'))
            self.assertIn('-DPython3_EXECUTABLE='+sys.executable, args)

    def test_original_packages_with_spaces_in_runtime_path(self):
        self.check_packages(['nav2_smac_planner', 'nav2_velocity_smoother'])

    def test_cached_overlay_builds_selected_transport_packages(self):
        self.check_packages(['nav2_rotation_shim_controller', 'nav2_graceful_controller'])


if __name__ == '__main__':
    unittest.main()
