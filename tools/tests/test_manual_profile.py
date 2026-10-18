"""Check generated topology/geometry and the real installed dependency, without ROS."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from fishbot_manual_profile import (build_manual_profile, installed_twist_mux, manual_capability,
                                   prepare_manual_files, claim_manual_boot)


class ManualProfileTests(unittest.TestCase):
    def setUp(self):
        self.base = yaml.safe_load((ROOT/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/config/nav2.yaml').read_text())
        self.base['map_server'] = {'ros__parameters': {'yaml_filename': '/selected/map.yaml', 'use_sim_time': True}}
        self.geometry = yaml.safe_load((ROOT/'tools/config/fishbot_model_geometry.yaml').read_text())

    def test_profile_keeps_selected_localization_map_and_keepout_configuration(self):
        self.base['global_costmap']['global_costmap']['ros__parameters']['filters'] = ['keepout_filter']
        before = copy.deepcopy(self.base)
        result = build_manual_profile(self.base, self.geometry, scan_frame='laser_link')
        self.assertEqual(self.base, before)
        self.assertEqual(result['parameters']['amcl'], {**before['amcl'],
            'ros__parameters': {**before['amcl']['ros__parameters'], 'use_sim_time': True}})
        self.assertEqual(result['parameters']['map_server'], {**before['map_server'],
            'ros__parameters': {**before['map_server']['ros__parameters'], 'use_sim_time': True}})
        costmap = result['parameters']['global_costmap']['global_costmap']['ros__parameters']
        self.assertEqual(costmap['filters'], ['keepout_filter'])
        self.assertEqual(costmap['robot_radius'], before['global_costmap']['global_costmap']['ros__parameters']['robot_radius'])
        self.assertGreaterEqual(len(json.loads(costmap['footprint'])), 8)

    def test_low_speed_stamped_chain_has_one_guard_candidate_and_no_final_bypass(self):
        result = build_manual_profile(self.base, self.geometry, scan_frame='laser_link')
        p = result['parameters']
        self.assertEqual(p['velocity_smoother']['ros__parameters']['max_velocity'], [.08, 0., .25])
        self.assertEqual(p['velocity_smoother']['ros__parameters']['min_velocity'], [-.03, 0., -.25])
        self.assertFalse(p['velocity_smoother']['ros__parameters']['stamp_smoothed_velocity_with_smoothing_time'])
        cm = p['collision_monitor']['ros__parameters']
        self.assertEqual(cm['cmd_vel_out_topic'], '/cmd_vel_safe_candidate')
        self.assertEqual(cm['polygons'], ['VelocityStop', 'Slowdown', 'FootprintApproach'])
        self.assertEqual(cm['VelocityStop']['min_points'], 1)
        self.assertEqual(result['geometry']['frames']['scan'], 'laser_link')
        self.assertEqual(self.geometry['frames']['scan'], 'laser_frame')
        self.assertEqual(result['guard_options']['expected_final_subscribers'],
                         ['diff_drive_controller', 'fishbot_mission_bridge'])
        self.assertEqual(result['nav_remappings'][0], ('velocity_smoother:cmd_vel', '/cmd_vel_selected'))
        mux = result['mux']['twist_mux']['ros__parameters']
        self.assertTrue(mux['use_stamped'])
        self.assertLess(mux['topics']['navigation']['priority'], mux['locks']['navigation_owner']['priority'])
        self.assertLess(mux['locks']['navigation_owner']['priority'], mux['topics']['manual']['priority'])
        self.assertGreater(mux['locks']['navigation_owner']['timeout'], 0)

    def test_guard_accepts_rendered_settings_without_relaxing_original_limits(self):
        spec = importlib.util.spec_from_file_location('manual_profile_guard', ROOT/'tools/fishbot_command_guard.py')
        guard = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = guard
        spec.loader.exec_module(guard)
        result = build_manual_profile(self.base, self.geometry, scan_frame='laser_link')
        settings = guard.Settings.from_mapping(result['geometry'], **result['guard_options'])
        self.assertEqual((settings.max_linear_speed, settings.max_angular_speed), (.08, .25))
        self.assertTrue(settings.output_stamped)
        self.assertEqual(settings.command_timeout_s, .25)

    def test_installed_official_binary_descriptor_and_capability_are_truthful(self):
        installed = installed_twist_mux()
        self.assertEqual(installed['version'], '4.5.0')
        self.assertEqual(installed['declared_license'], 'Apache License 2.0')
        capability = manual_capability()
        self.assertFalse(capability['available'])
        self.assertEqual(capability['submission'], 'topic_publish')
        self.assertEqual(capability['protocol'], 'manual_lease_v1')

    def test_prepared_profile_uses_actual_sensor_frame_and_refuses_evidence_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'run'
            receipt = prepare_manual_files(
                ROOT/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/config/nav2.yaml',
                ROOT/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/config/plugins.yaml',
                output, domain=129)
            self.assertEqual(receipt['scan_frame'], 'laser_link')
            geometry = yaml.safe_load(Path(receipt['paths']['geometry']).read_text())
            self.assertEqual(geometry['frames']['scan'], 'laser_link')
            before = (output/'manual-profile.json').read_bytes()
            with self.assertRaises(FileExistsError):
                prepare_manual_files(
                    ROOT/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/config/nav2.yaml',
                    ROOT/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/config/plugins.yaml',
                    output, domain=129)
            self.assertEqual((output/'manual-profile.json').read_bytes(), before)

    def test_boot_receipt_cannot_restart_bridge_or_claim_stale_or_other_domain(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'manual-profile.json'
            receipt = {'profile_id': 'passage_manual', 'domain': 129,
                       'boot_id': 'e7a55ce7-acbb-4c46-b645-d6dfb33b9943', 'empty_domain_checked_at_ms': 100_000}
            path.write_text(json.dumps(receipt))
            for domain, now in ((128, 100_000), (129, 160_001), (129, 99_999)):
                with self.assertRaisesRegex(ValueError, 'missing, stale or mismatched'):
                    claim_manual_boot(path, domain, now_ms=now)
            claim_manual_boot(path, 129, now_ms=101_000)
            claim = path.with_name('manual-owner.claim')
            before = claim.read_bytes()
            with self.assertRaisesRegex(ValueError, 'already consumed'):
                claim_manual_boot(path, 129, now_ms=101_001)
            self.assertEqual(claim.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
