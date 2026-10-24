"""Four-wheel control, independent encoder integration and plant layout."""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from cooperation_mecanum import K, RADIUS, MecanumOdometry, forward, inverse, vehicle_profile
from cooperation_sim import Physics, WheelCommands


class MecanumControlTests(unittest.TestCase):
    def test_wide_chassis_reuses_native_straight_egress_before_route_turning(self):
        profile = vehicle_profile()
        self.assertEqual(profile['transport_egress'], 'staging')
        self.assertEqual(profile['transport_egress_motion'],
            {'type': 'drive_on_heading', 'speed_m_s': .03, 'time_allowance_s': 45.})
        self.assertFalse(profile['drive']['encoder_truth_feedback'])

    def test_installation_keeps_handover_and_connects_mount_to_the_chassis(self):
        profile = vehicle_profile()
        for index, expected in enumerate((.24, .14)):
            self.assertAlmostEqual(profile['dock_offset_m'][index]+profile['tray_offset_m'][index], expected)
        mount = profile['tray_mount']
        bottom = profile['tray_offset_m'][2]+mount['position_in_tray_m'][2]-mount['size_m'][2]/2
        self.assertLess(bottom, .05)  # Chassis top relative to base_link.
        self.assertAlmostEqual(math.prod(mount['size_m'])*2700., mount['mass_kg'])

    def test_legacy_wheel_order_and_body_command_round_trip(self):
        self.assertEqual(tuple(math.copysign(1, v) for v in inverse(0., 1., 0.)), (-1., 1., 1., -1.))
        self.assertEqual(tuple(math.copysign(1, v) for v in inverse(0., 0., 1.)), (-1., -1., 1., 1.))
        for command in ((.06, 0., 0.), (0., -.06, 0.), (.04, -.04, .08)):
            with self.subTest(command=command):
                for actual, expected in zip(forward(inverse(*command)), command):
                    self.assertAlmostEqual(actual, expected)

    def test_all_four_wheels_obey_existing_hold_expiry_and_episode_boundary(self):
        wheels = WheelCommands(radius=RADIUS, mecanum_k=K)
        wheels.accept(.04, .08, 1., lateral=-.04)
        self.assertEqual(wheels.velocities(1.1), (0.,)*4)
        wheels.set_hold(False)
        self.assertEqual(wheels.velocities(1.1), (0.,)*4)
        wheels.accept(.04, .08, 1.1, lateral=-.04, source_stamp=2., sim_now=2.)
        self.assertEqual(wheels.velocities(1.2), inverse(.04, -.04, .08))
        self.assertEqual(wheels.velocities(1.7), (0.,)*4)
        wheels.begin_episode(3.)
        wheels.set_hold(False)
        with self.assertRaisesRegex(ValueError, 'previous episode'):
            wheels.accept(0., 0., 2., lateral=.04, source_stamp=2.9, sim_now=3.1)
        self.assertEqual(wheels.velocities(2.), (0.,)*4)

    def test_four_encoders_are_not_collapsed_to_side_averages(self):
        physics = Physics.__new__(Physics)
        physics.mecanum_k = K
        physics.wheel_q = [0, 3, 6, 9]
        physics.data = SimpleNamespace(qpos=[1., 99., 99., 2., 99., 99., 3., 99., 99., 4.])
        self.assertEqual(physics.wheel_encoder_positions(), (1., 2., 3., 4.))

    def test_lateral_odometry_and_rebase_preserve_integrated_pose(self):
        odom = MecanumOdometry(0., 0., 0., 0.)
        turn = inverse(0., 0., math.pi/2)
        odom.update(*turn, 1.)
        lateral = inverse(0., .2, 0.)
        odom.update(*(a+b for a, b in zip(turn, lateral)), 1.)
        self.assertAlmostEqual(odom.x, -.2)
        self.assertAlmostEqual(odom.y, 0.)
        self.assertAlmostEqual(odom.lateral_velocity, .2)
        pose = (odom.x, odom.y, odom.yaw)
        odom.rebase((0.,)*4)
        self.assertEqual(odom.update(0., 0., 0., 0., .02), (0., 0.))
        self.assertEqual((odom.x, odom.y, odom.yaw), pose)


class MecanumPlantTests(unittest.TestCase):
    def test_shared_plant_keeps_arm_cargo_and_passive_rollers_independent(self):
        runtime = Path(os.environ.get('FISHBOT_SO101_PYTHON',
            str(Path.home()/'.cache/so101-colab/planning-venv/bin/python')))
        code = r'''
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]+'/tools')
sys.path.append('/usr/lib/python3/dist-packages')
from cooperation_scene import build_scene
from cooperation_sim import Physics
from cooperation_lidar import configuration,NativeCloudQuery
p=Path(sys.argv[1]);out=Path(sys.argv[2])
m=build_scene(p.parent/'so101',p,out,spawn=(0.,0.),scene_profile={'vehicle':'robot_base_mecanum','sensors':'lidar3d'})
path=out/'scene-manifest.json';path.write_text(json.dumps(m))
plant=Physics(m['world_xml'],manifest=path)
for _ in range(1000):plant.step()
plant.reset_episode(plant.episode_id)
before=plant.data.qpos.copy()
cloud=NativeCloudQuery(m['world_xml'],configuration(m)).compute(
 {'qpos':plant.data.qpos.copy(),'qvel':plant.data.qvel.copy(),'stamp':float(plant.data.time)})
print('RESULT_JSON:'+json.dumps({'layout':[plant.model.nq,plant.model.nv,plant.model.nu],
 'wheel_q':list(plant.wheel_q),'passive':len(m['passive_joint_names']),
 'wheel_readings':plant.wheel_encoder_positions(),'hold':plant.wheels.hold,
 'reset_count':plant.reset_count,'actuated_wheels':m['actuated_wheel_qpos_indices'],
 'external_contacts':plant.total_car_forbidden_contacts,'arm_count':len(plant.arm_q),
 'imu_frame':plant.model.body('imu_link').id>=0,
 'cloud_rays':len(cloud['points']),'cloud_valid':cloud['valid_points'],
 'query_preserves_plant':bool((before==plant.data.qpos).all())}))
'''
        with tempfile.TemporaryDirectory() as out:
            run = subprocess.run([str(runtime), '-B', '-c', code, str(ROOT), out],
                                 capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout+'\n'+run.stderr)
        data = json.loads(run.stdout.rsplit('RESULT_JSON:', 1)[1])
        self.assertEqual(data['layout'], [72, 70, 10])
        self.assertEqual(data['passive'], 48)
        self.assertEqual(data['actuated_wheels'], data['wheel_q'])
        self.assertEqual(len(set(data['wheel_q'])), 4)
        self.assertEqual(data['arm_count'], 6)
        self.assertTrue(data['imu_frame'])
        self.assertEqual(data['cloud_rays'], 16*360)
        self.assertGreater(data['cloud_valid'], 0)
        self.assertTrue(data['query_preserves_plant'])
        self.assertTrue(data['hold'])
        self.assertEqual(data['reset_count'], 1)
        self.assertEqual(data['external_contacts'], 0)


if __name__ == '__main__':
    unittest.main()
