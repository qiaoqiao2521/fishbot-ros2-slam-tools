"""Native component configuration contracts; physical acceptance is separate."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cooperation_prepare import composition_navigation

ROOT = Path(__file__).resolve().parents[2]


class CompositionNavigationTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.params = yaml.safe_load((ROOT/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/config/nav2.yaml').read_text())

    def test_legacy_composition_preserves_all_navigation_parameters(self):
        before = copy.deepcopy(self.params)
        manifest = {}
        composition_navigation(self.params, manifest, self.folder.name)
        self.assertEqual(self.params, before)
        self.assertEqual(manifest, {})

    def test_jackal_uses_existing_ekf_without_truth_or_absolute_yaw(self):
        manifest = {'vehicle_profile': {'id':'jackal_j100'},
                    'car_footprint_xy': [[.244,.223],[-.244,.223],[-.244,-.223],[.244,-.223]]}
        composition_navigation(self.params, manifest, self.folder.name)
        ekf = yaml.safe_load(Path(manifest['localization']['ekf_yaml']).read_text())['ekf_filter_node']['ros__parameters']
        self.assertEqual(ekf['odom0'], '/wheel/odom')
        self.assertEqual(ekf['imu0'], '/imu')
        self.assertEqual([i for i,v in enumerate(ekf['odom0_config']) if v], [6,7])
        self.assertEqual([i for i,v in enumerate(ekf['imu0_config']) if v], [3,4,11])
        self.assertNotIn('pose0', ekf)
        self.assertTrue(ekf['publish_tf'])
        for name in ('global_costmap','local_costmap'):
            config = self.params[name][name]['ros__parameters']
            self.assertGreater(config['robot_radius'], .33)
            self.assertAlmostEqual(config['inflation_layer']['inflation_radius'], config['robot_radius']+.17)

    def test_j100_declares_loaded_limits_without_changing_transit_docking_or_emergency_path(self):
        from cooperation_profiles import vehicle_profile
        manifest = {'vehicle_profile': vehicle_profile({'vehicle':'jackal_j100'}),
                    'car_footprint_xy': [[.244,.223],[-.244,.223],[-.244,-.223],[.244,-.223]]}
        before = copy.deepcopy(self.params)
        composition_navigation(self.params, manifest, self.folder.name)
        smoothing = self.params['velocity_smoother']['ros__parameters']
        loaded = manifest['vehicle_profile']['loaded_velocity_smoother']
        self.assertEqual(loaded['max_accel'], [.025,0.,.05])
        self.assertEqual(loaded['max_velocity'], [.03,0.,.05])
        self.assertEqual(loaded['min_velocity'], [-.03,0.,-.05])
        self.assertEqual(manifest['vehicle_profile']['loaded_controller'], {
            'FollowPath.desired_linear_vel': .03,
            'FollowPath.regulated_linear_scaling_min_speed': .03,
            'FollowPath.min_approach_linear_velocity': .005,
            'FollowPath.rotate_to_heading_angular_vel': .05})
        self.assertEqual(loaded['max_decel'], [-.1,0.,-.2])
        self.assertEqual(smoothing, before['velocity_smoother']['ros__parameters'])
        for key in ('max_velocity', 'min_velocity', 'smoothing_frequency', 'velocity_timeout'):
            self.assertEqual(smoothing[key], before['velocity_smoother']['ros__parameters'][key])
        self.assertEqual(self.params['collision_monitor'], before['collision_monitor'])
        controller = self.params['controller_server']['ros__parameters']
        self.assertFalse(controller['FollowPath']['stateful'])
        goal = controller['general_goal_checker']
        self.assertEqual(goal['plugin'], 'nav2_controller::StoppedGoalChecker')
        self.assertEqual(goal['trans_stopped_velocity'], .01)
        self.assertEqual(goal['rot_stopped_velocity'], .01)
        self.assertFalse(goal['stateful'])
        for key in ('xy_goal_tolerance', 'yaw_goal_tolerance'):
            self.assertEqual(goal[key], before['controller_server']['ros__parameters']['general_goal_checker'][key])
        self.assertEqual(controller['FollowPath']['max_angular_accel'], 2.)
        self.assertEqual(controller['FollowPath']['rotate_to_heading_angular_vel'], .4)
        for key in ('desired_linear_vel','regulated_linear_scaling_min_speed','min_approach_linear_velocity'):
            self.assertEqual(controller['FollowPath'][key], before['controller_server']['ros__parameters']['FollowPath'][key])

    def test_profile_requires_position_at_final_heading_without_relaxing_tolerances(self):
        before = copy.deepcopy(self.params)
        composition_navigation(self.params, {'scene_profile': {'vehicle': 'fishbot'}}, self.folder.name)
        goal = self.params['controller_server']['ros__parameters']['general_goal_checker']
        self.assertFalse(goal['stateful'])
        self.assertFalse(self.params['controller_server']['ros__parameters']['FollowPath']['stateful'])
        for name in ('plugin', 'xy_goal_tolerance', 'yaw_goal_tolerance'):
            self.assertEqual(goal[name], before['controller_server']['ros__parameters']['general_goal_checker'][name])

    def test_three_dimensional_input_reaches_both_costmaps_and_collision_monitor(self):
        manifest = {'scene_profile': {'sensors':'lidar3d'},
                    'transport_height_envelope': {'max_obstacle_height_m':.3095665927567458}}
        composition_navigation(self.params, manifest, self.folder.name)
        composition_navigation(self.params, manifest, self.folder.name)
        for name in ('global_costmap','local_costmap'):
            config = self.params[name][name]['ros__parameters']
            layer = config['voxel_layer'] if 'voxel_layer' in config['plugins'] else config['lidar3d_voxel_layer']
            self.assertEqual(layer['lidar3d']['data_type'], 'PointCloud2')
            self.assertEqual(layer['lidar3d']['topic'], '/sensors/lidar3d/points')
            self.assertEqual(layer['lidar3d']['max_obstacle_height'], .3095665927567458)
            self.assertEqual(layer['observation_sources'].split().count('lidar3d'), 1)
        monitor = self.params['collision_monitor']['ros__parameters']
        self.assertEqual(monitor['observation_sources'], ['scan','lidar3d'])
        self.assertEqual(monitor['lidar3d']['type'], 'pointcloud')
        self.assertEqual(monitor['lidar3d']['min_height'], .025)
        self.assertEqual(monitor['lidar3d']['max_height'], .3095665927567458)
        self.assertEqual(monitor['source_timeout'], 1.)
        self.assertEqual(self.params['amcl']['ros__parameters']['scan_topic'], '/scan')

    def test_custom_lidar_topic_and_ranges_follow_sensor_configuration(self):
        from cooperation_lidar import configuration
        manifest = {'scene_profile': {'sensors':'lidar3d'},
                    'lidar3d': {'topic':'/sensors/custom_lidar/points',
                                'min_range_m':.2, 'max_range_m':4.},
                    'transport_height_envelope': {'max_obstacle_height_m':.3}}
        sensor = configuration(manifest)
        composition_navigation(self.params, manifest, self.folder.name)
        for name in ('global_costmap','local_costmap'):
            config = self.params[name][name]['ros__parameters']
            key = 'voxel_layer' if 'voxel_layer' in config['plugins'] else 'lidar3d_voxel_layer'
            source = config[key]['lidar3d']
            self.assertEqual(source['topic'], sensor['topic'])
            self.assertEqual(source['obstacle_min_range'], sensor['min_range_m'])
            self.assertEqual(source['raytrace_min_range'], sensor['min_range_m'])
            self.assertAlmostEqual(source['obstacle_max_range'], sensor['max_range_m']-.1)
            self.assertEqual(source['raytrace_max_range'], sensor['max_range_m'])
        monitor = self.params['collision_monitor']['ros__parameters']['lidar3d']
        self.assertEqual(monitor['topic'], sensor['topic'])
        self.assertEqual(monitor['min_range'], sensor['min_range_m'])
        evidence = manifest['lidar3d_navigation']
        self.assertEqual(evidence['topic'], sensor['topic'])
        self.assertEqual(evidence['min_range_m'], sensor['min_range_m'])
        self.assertEqual(evidence['max_range_m'], sensor['max_range_m'])


if __name__ == '__main__':
    unittest.main()
