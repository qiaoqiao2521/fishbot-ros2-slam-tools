"""Optional native transport selection preserves shared physical contracts."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    'f1_candidate', ROOT/'experiments/kaggle/f1_candidate.py')
CANDIDATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CANDIDATE)
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

    def test_native_selection_without_progress_does_not_leave_empty_adapter(self):
        self.manifest['vehicle_profile']['loaded_controller'] = {'FollowPath.desired_linear_vel': .03}
        self.path.write_text(json.dumps(self.manifest))
        CANDIDATE.configure(self.path, PRESET)
        manifest, _ = self.read()
        self.assertNotIn('loaded_controller', manifest['vehicle_profile'])


if __name__ == '__main__':
    unittest.main()
