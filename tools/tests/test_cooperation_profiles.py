import math
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cooperation_profiles import normalize_scene_profile, vehicle_profile, vehicle_element


class SceneProfileTests(unittest.TestCase):
    def test_legacy_defaults_and_all_composable_choices(self):
        self.assertEqual(normalize_scene_profile(), {'schema':1,'vehicle':'fishbot','sensors':'planar','task':'transport'})
        for vehicle in ('fishbot','jackal_j100'):
            for sensors in ('planar','lidar3d'):
                for task in ('transport','three_batch_transport'):
                    value=normalize_scene_profile(dict(vehicle=vehicle,sensors=sensors,task=task))
                    self.assertEqual(value,dict(schema=1,vehicle=vehicle,sensors=sensors,task=task))

    def test_unsupported_profile_does_not_silently_select_another_vehicle(self):
        for value in ([],{'schema':True},{'schema':2},{'vehicle':'go2'}, {'sensors':'pretend'},
                      {'task':'anything'}):
            with self.subTest(value=value),self.assertRaises(ValueError):normalize_scene_profile(value)

    def test_optional_metadata_warns_and_preserves_selected_configuration(self):
        with self.assertWarnsRegex(RuntimeWarning, 'Ignoring unknown scene_profile metadata.*note'):
            result = normalize_scene_profile({'vehicle':'jackal_j100', 'note':'editable install note'})
        self.assertEqual(result,dict(schema=1,vehicle='jackal_j100',sensors='planar',task='transport'))

    def test_j100_drive_full_geometry_and_gripper_relative_target_are_preserved(self):
        profile=vehicle_profile({'vehicle':'jackal_j100'})
        self.assertEqual(profile['wheel_radius_m'],.098)
        self.assertEqual(profile['wheel_separation_m'],.37559)
        self.assertEqual(profile['left_wheel_joints'],['front_left_wheel_joint','rear_left_wheel_joint'])
        self.assertTrue(profile['localization']['enabled'])
        self.assertEqual(profile['localization']['imu_topic'],'/imu')
        self.assertAlmostEqual(profile['planning_radius_m'],math.hypot(.244,.222795))
        self.assertEqual(profile['tray_offset_m'][:2],[-.16,-.18])
        self.assertEqual(profile['dock_offset_m'],[.40,.32,0.])
        self.assertEqual(profile['tray_mount']['position_in_tray_m'][:2],[0.,.075])
        self.assertAlmostEqual(profile['tray_mount']['mass_kg'],.486)
        self.assertEqual(profile['tray_mount']['support_assumptions']['floor_overlap_xy_m'],[.10,.035])
        self.assertFalse(profile['tray_mount']['support_assumptions']['strength_or_fasteners_validated'])
        self.assertFalse(profile['installation']['total_3d_sweep_margin_improved'])
        for actual,expected in zip([profile['dock_offset_m'][i]+profile['tray_offset_m'][i] for i in (0,1)],[.24,.14]):
            self.assertAlmostEqual(actual,expected)
        top=profile['spawn_free_z_m']+profile['base_link_z_m']+profile['tray_offset_m'][2]+.002
        self.assertAlmostEqual(top-(.16+profile['station_height_delta_m']),.003)

    def test_effective_skid_track_preserves_geometry_and_declares_calibration_limits(self):
        legacy=vehicle_profile()['drive']
        self.assertEqual(legacy['effective_track_multiplier'],1.)
        self.assertEqual(legacy['effective_track_m'],legacy['physical_track_m'])
        profile=vehicle_profile({'vehicle':'jackal_j100'})
        control=profile['drive'];calibration=control['calibration']
        self.assertEqual(profile['wheel_separation_m'],.37559)
        self.assertEqual(control['physical_track_m'],profile['wheel_separation_m'])
        self.assertEqual(control['effective_track_multiplier'],4.5)
        self.assertAlmostEqual(control['effective_track_m'],1.690155)
        self.assertFalse(calibration['online_truth_feedback'])
        self.assertFalse(calibration['real_hardware_calibrated'])
        self.assertTrue(calibration['same_effective_track_required_for_commands_and_encoder_odometry'])
        self.assertEqual(calibration['wheel_sliding_friction'],profile['simulation_assumptions']['wheel_friction'][0])
        self.assertEqual(calibration['wheel_velocity_servo_kv'],profile['simulation_assumptions']['velocity_servo_kv'])
        self.assertEqual(calibration['wheel_torque_limit_nm'],profile['simulation_assumptions']['wheel_torque_limit_nm'])

    def test_j100_reuses_source_mass_inertia_and_four_real_bounded_wheels(self):
        source=Path(__file__).resolve().parents[2]/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/mjcf/fishbot.xml'
        root,car,profile=vehicle_element(source,(0,-2),0,{'vehicle':'jackal_j100'})
        inertial=car.find("body[@name='base_link']/inertial")
        self.assertEqual(float(inertial.get('mass')),16.523)
        self.assertEqual([float(x) for x in inertial.get('fullinertia').split()],[.3136,.3922,.4485,-.0008,.0164,-.0009])
        self.assertEqual(len(car.findall('.//joint')),4)
        self.assertEqual(len(root.findall('actuator/velocity')),4)
        self.assertTrue(all(a.get('forcerange')=='-12.0 12.0' for a in root.findall('actuator/velocity')))
        self.assertEqual([float(x) for x in car.find("body[@name='base_link']/geom[@name='base_collision']").get('size').split()],[.21,.155,.092])
        self.assertEqual(profile['source']['license'],'BSD-3-Clause')


class J100NativeSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        project=Path(__file__).resolve().parents[2]
        runtime=Path(os.environ.get('FISHBOT_SO101_PYTHON',str(Path.home()/'.cache/so101-colab/planning-venv/bin/python')))
        code=r'''
import json,math,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]+'/tools')
sys.path.append('/usr/lib/python3/dist-packages')
import mujoco,numpy as np
from cooperation_scene import build_scene
from cooperation_arm import ArmPlanner
from cooperation_geometry_check import SceneGeometry,check
p,out=Path(sys.argv[1]),Path(sys.argv[2])
m=build_scene(p.parent/'so101',p,out,scene_profile={'vehicle':'jackal_j100'})
m['staging_pose']=[m['dock_pose'][0]+.7,m['dock_pose'][1],m['dock_pose'][2]]
(out/'scene-manifest.json').write_text(json.dumps(m))
goal=SceneGeometry(m).check_pose(dict(zip(('x','y','yaw'),m['dock_pose'])))
sweep=check(out/'scene-manifest.json')
a=ArmPlanner(m);model=a.common;d=mujoco.MjData(model)
d.qpos[:6]=a.home;d.ctrl[:6]=a.home
x,y,yaw=m['dock_pose'];d.qpos[13:20]=[x,y,.002,math.cos(yaw/2),0,0,math.sin(yaw/2)]
mujoco.mj_forward(model,d)
fixed_center=(d.xpos[model.body('cargo_tray').id]-np.array(m['station_offset'])).tolist()
obstacle=model.geom('approach_obstacle').id
points=np.array(m['car_footprint_xy'])+m['dock_pose'][:2]
planar_gap=float(points[:,1].min()-(d.geom_xpos[obstacle,1]+model.geom_size[obstacle,1]))
for _ in range(1000):mujoco.mj_step(model,d)
before=[d.qpos.copy(),d.qvel.copy(),d.ctrl.copy()]
approach=a.prepare_approach(d.qpos[:6],car_pose=d.qpos[13:20])
result={'version':mujoco.__version__,'layout':[model.nq,model.nv,model.nu],
 'manifest':m,'goal':goal,'sweep':sweep,'fixed_tray_center_arm':fixed_center,
 'planar_footprint_obstacle_gap_m':planar_gap,'home':a.evaluate(d.qpos[:6]),
 'max_static_speed':float(np.max(np.abs(d.qvel))),
 'original_body_mass':float(model.body('base_link').mass[0]),
 'wheel_masses':[float(model.body(name+'_wheel_link').mass[0]) for name in ('front_left','rear_left','front_right','rear_right')],
 'mount_mass':float(model.geom('tray_mount').size[0]*model.geom('tray_mount').size[1]*model.geom('tray_mount').size[2]*8*2700),
 'planning_exact':approach['planning']['exact_solution'],'descent_valid':approach['descent']['valid'],
 'ascent_valid':approach['ascent']['valid'],
 'query_preserved_live':all(np.array_equal(x,y) for x,y in zip(before,[d.qpos,d.qvel,d.ctrl]))}
print('RESULT_JSON:'+json.dumps(result))
'''
        run=subprocess.run([str(runtime),'-B','-c',code,str(project),cls.temp.name],capture_output=True,text=True,timeout=60)
        if run.returncode:raise RuntimeError('J100 scene probe failed:\n'+run.stdout+'\n'+run.stderr)
        cls.evidence=json.loads(run.stdout.rsplit('RESULT_JSON:',1)[1])

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_real_j100_four_wheel_model_compiles_in_existing_python_runtime(self):
        e=self.evidence
        self.assertEqual(e['version'],'3.3.7')
        self.assertEqual(e['layout'],[24,22,10])
        self.assertEqual(e['original_body_mass'],16.523)
        self.assertEqual(e['wheel_masses'],[.477]*4)
        self.assertAlmostEqual(e['mount_mass'],.486)
        self.assertLess(e['max_static_speed'],1e-5)

    def test_full_vehicle_approach_and_padded_planar_footprint_are_clear(self):
        e=self.evidence
        self.assertTrue(e['goal']['passed'],e['goal'])
        self.assertTrue(e['sweep']['passed'],e['sweep'])
        self.assertGreater(e['sweep']['geometry_margin_m'],.01)
        self.assertGreater(e['planar_footprint_obstacle_gap_m'],.01)
        self.assertFalse(e['goal']['robot_geometry_shrunk'])

    def test_lateral_fixture_keeps_original_padding_and_two_map_cells_of_clearance(self):
        e=self.evidence
        map_resolution=.02
        original_nav_footprint_padding=.01
        self.assertGreaterEqual(e['planar_footprint_obstacle_gap_m']-original_nav_footprint_padding,
                                2*map_resolution)
        self.assertAlmostEqual(e['planar_footprint_obstacle_gap_m'],.052)
        footprint=e['manifest']['car_footprint_xy']
        self.assertEqual(len(footprint),6)
        self.assertAlmostEqual(min(point[1] for point in footprint),-.24)
        self.assertEqual(e['manifest']['car_footprint_method'],
                         'convex_hull_of_source_vehicle_envelope_and_compiled_tray_corners')
        # Side clearance and the full 3-D sweep remain separate observations.
        self.assertAlmostEqual(e['sweep']['geometry_margin_m'],.01984143051575514,places=6)

    def test_existing_arm_target_and_exact_planner_still_work(self):
        e=self.evidence
        for actual,expected in zip(e['fixed_tray_center_arm'],[.24,.14,.001]):
            self.assertAlmostEqual(actual,expected)
        for key in ('planning_exact','descent_valid','ascent_valid','query_preserved_live'):
            self.assertTrue(e[key],key)
        self.assertTrue(e['home']['valid'],e['home'])


if __name__=='__main__':unittest.main()
