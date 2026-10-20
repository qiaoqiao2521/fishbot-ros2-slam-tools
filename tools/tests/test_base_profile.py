"""Source-derived base/control contracts; native physics is a separate probe."""
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('base_profile', ROOT/'tools/fishbot_base_profile.py')
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)


class BaseProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)

    def prepare(self, **kwargs):
        return base.prepare(base.PACKAGE/'mjcf/arena.xml', self.path/'output', **kwargs)

    def test_replaces_two_wheel_plant_with_four_real_joints_and_full_inertia(self):
        result = self.prepare()
        tree = ET.parse(result['scene'])
        joints = {x.get('name') for x in tree.findall('.//joint')}
        self.assertTrue(set(result['wheel_joints']).issubset(joints))
        self.assertNotIn('left_wheel_joint', joints)
        self.assertNotIn('right_wheel_joint', joints)
        self.assertEqual(len(tree.findall('.//actuator/velocity')), 4)
        chassis = tree.find('.//body[@name="base_link"]/inertial')
        self.assertEqual(float(chassis.get('mass')), 16.523)
        self.assertEqual(list(map(float, chassis.get('fullinertia').split())),
                         [.3136, .3922, .4485, -.0008, .0164, -.0009])
        self.assertIsNotNone(tree.find('.//geom[@name="floor"]'))

    def test_official_mesh_preserves_urdf_fixed_axis_rotation(self):
        result = self.prepare()
        visual = ET.parse(result['scene']).find('.//geom[@name="jackal_body_visual"]')
        self.assertEqual(list(map(float, visual.get('quat').split())), [.5, .5, .5, .5])
        self.assertIsNone(visual.get('euler'))
        self.assertEqual(visual.get('contype'), '0')
        self.assertEqual(visual.get('conaffinity'), '0')

    def test_control_feedback_and_description_match_all_native_joints(self):
        result = self.prepare()
        controllers = yaml.safe_load(Path(result['controllers_file']).read_text())
        params = controllers['diff_drive_controller']['ros__parameters']
        self.assertFalse(params['open_loop'])
        self.assertEqual(params['wheel_radius'], .098)
        self.assertEqual(params['wheel_separation'], .37559)
        self.assertEqual(set(params['left_wheel_names']+params['right_wheel_names']), set(result['wheel_joints']))
        tree = ET.parse(result['robot_description_file'])
        self.assertEqual({x.get('name') for x in tree.findall('.//ros2_control/joint')}, set(result['wheel_joints']))
        self.assertEqual(tree.find('.//hardware/param[@name="mujoco_model"]').text, '$(arg scene_path)')
        self.assertIsNotNone(tree.find('.//link[@name="laser_link"]'))

    def test_planner_radius_encloses_tire_extremities_and_oracle_padding(self):
        result = self.prepare()
        hx, hy = result['geometry']['half_extents']
        self.assertAlmostEqual(hx, .244)
        self.assertAlmostEqual(hy, .222795)
        nav = yaml.safe_load(Path(result['nav2']).read_text())
        for name in ('local_costmap', 'global_costmap'):
            costmap = nav[name][name]['ros__parameters']
            self.assertNotIn('footprint', costmap)
            self.assertAlmostEqual(costmap['robot_radius'], math.hypot(hx, hy))
            self.assertEqual(costmap['footprint_padding'], 0.)
        self.assertEqual(nav['controller_server']['ros__parameters']['FollowPath']['desired_linear_vel'], .2)

    def test_source_scene_is_not_modified_and_new_output_retains_start_pose(self):
        original = base.PACKAGE/'mjcf/arena.xml'
        source = self.path/'source.xml'
        tree = base._scene(original)
        tree.find('.//body[@name="base_footprint"]').set('pos', '.4 -.2 .003')
        tree.find('.//body[@name="base_footprint"]').set('euler', '0 0 .6')
        ET.ElementTree(tree).write(source)
        before = source.read_bytes()
        result = base.prepare(source, self.path/'out')
        body = ET.parse(result['scene']).find('.//body[@name="base_footprint"]')
        self.assertEqual(body.get('pos'), '.4 -.2 .003')
        self.assertEqual(body.get('euler'), '0 0 .6')
        self.assertEqual(source.read_bytes(), before)

    def test_inflation_preserves_old_clearance_gradient_without_mutating_input(self):
        source = self.path/'original-nav2.yaml'
        source.write_bytes((base.PACKAGE/'config/nav2.yaml').read_bytes())
        before = source.read_bytes()
        result = self.prepare(nav2_path=source)
        generated = yaml.safe_load(Path(result['nav2']).read_text())
        for name in ('local_costmap', 'global_costmap'):
            config = generated[name][name]['ros__parameters']
            inflation = config['inflation_layer']
            self.assertGreater(inflation['inflation_radius'], config['robot_radius'])
            self.assertAlmostEqual(inflation['inflation_radius']-config['robot_radius'], .17)
            self.assertEqual(inflation['cost_scaling_factor'], 4.)
        self.assertEqual(source.read_bytes(), before)

    def test_upstream_ekf_uses_native_imu_and_wheel_translation_with_single_tf_owner(self):
        result = self.prepare()
        controllers = yaml.safe_load(Path(result['controllers_file']).read_text())
        self.assertFalse(controllers['diff_drive_controller']['ros__parameters']['enable_odom_tf'])
        broadcaster = controllers['imu_sensor_broadcaster']['ros__parameters']
        self.assertEqual(broadcaster['sensor_name'], 'imu')
        self.assertEqual(broadcaster['frame_id'], 'imu_link')
        self.assertEqual(len(broadcaster['static_covariance_angular_velocity']), 9)
        params = yaml.safe_load(Path(result['fusion_file']).read_text())['ekf_filter_node']['ros__parameters']
        self.assertEqual([i for i, enabled in enumerate(params['odom0_config']) if enabled], [6, 7])
        self.assertEqual([i for i, enabled in enumerate(params['imu0_config']) if enabled], [3, 4, 11])
        self.assertEqual(params['odom0'], result['wheel_odom_topic'])
        self.assertEqual(params['base_link_frame'], 'base_footprint')
        self.assertEqual(params['world_frame'], 'odom')
        self.assertFalse(params['two_d_mode'])
        self.assertTrue(params['publish_tf'])
        self.assertTrue(result['imu_broadcaster'])
        self.assertTrue(result['localization_fusion'])

    def test_fusion_can_be_disabled_in_editable_profile_without_changing_legacy_inputs(self):
        profile = yaml.safe_load(base.DEFAULT_PROFILE.read_text())
        profile['localization']['enabled'] = False
        source = self.path/'no-fusion.yaml'
        source.write_text(yaml.safe_dump(profile))
        result = self.prepare(profile_path=source)
        self.assertFalse(result['localization_fusion'])
        self.assertFalse(result['imu_broadcaster'])
        self.assertEqual(result['fusion_file'], '')
        self.assertEqual(result['wheel_odom_topic'], '/odom')
        controllers = yaml.safe_load(Path(result['controllers_file']).read_text())
        self.assertTrue(controllers['diff_drive_controller']['ros__parameters']['enable_odom_tf'])
        self.assertNotIn('imu_sensor_broadcaster', controllers['controller_manager']['ros__parameters'])

    def test_pose_progress_counts_turns_without_extending_movement_deadline(self):
        result = self.prepare()
        params = yaml.safe_load(Path(result['nav2']).read_text())['controller_server']['ros__parameters']
        checker = params['progress_checker']
        self.assertEqual(checker['plugin'], 'nav2_controller::PoseProgressChecker')
        self.assertEqual(checker['required_movement_angle'], .2)
        self.assertEqual(checker['required_movement_radius'], .15)
        self.assertEqual(checker['movement_time_allowance'], 10.)

    def test_j100_rpp_rotation_adaptation_retains_wheel_limits_and_original_nav(self):
        original_path = base.PACKAGE/'config/nav2.yaml'
        before = original_path.read_bytes()
        result = self.prepare()
        nav = yaml.safe_load(Path(result['nav2']).read_text())
        rpp = nav['controller_server']['ros__parameters']['FollowPath']
        self.assertEqual(rpp['max_angular_accel'], 10.)
        self.assertEqual(rpp['rotate_to_heading_angular_vel'], .8)
        self.assertTrue(rpp['use_collision_detection'])
        wheel = yaml.safe_load(Path(result['controllers_file']).read_text())['diff_drive_controller']['ros__parameters']
        self.assertEqual(wheel['angular.z.max_acceleration'], 2.)
        self.assertEqual(wheel['angular.z.max_velocity'], 1.5)
        self.assertEqual(wheel['cmd_vel_timeout'], .5)
        self.assertEqual(original_path.read_bytes(), before)
        original = yaml.safe_load(before)
        self.assertEqual(original['controller_server']['ros__parameters']['FollowPath']['max_angular_accel'], 2.)

    def test_generated_files_are_editable_and_provenance_is_not_an_execution_lock(self):
        result = self.prepare()
        receipt = Path(result['scene']).parent/'base-profile.json'
        metadata = json.loads(receipt.read_text())
        metadata['human_note'] = '更换工位'
        receipt.write_text(json.dumps(metadata))
        self.assertEqual(json.loads(receipt.read_text())['human_note'], '更换工位')
        self.assertEqual(result['source']['license'], 'BSD-3-Clause')
        self.assertIn('not a calibrated', result['scope'])
        for mesh in ET.parse(result['scene']).findall('.//asset/mesh'):
            self.assertTrue(Path(mesh.get('file')).is_file())


if __name__ == '__main__':
    unittest.main()
