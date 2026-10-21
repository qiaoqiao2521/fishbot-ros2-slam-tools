"""Regression: lidar localization excludes low fixtures without weakening collisions."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[2]
RUNTIME = Path(os.environ.get('FISHBOT_SO101_PYTHON',
                             str(Path.home()/'.cache/so101-colab/planning-venv/bin/python')))


class CooperationPrepareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        code = r'''
import hashlib,json,sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1]+'/tools')
sys.path.append('/usr/lib/python3/dist-packages')
import mujoco
import numpy as np
import yaml
import xml.etree.ElementTree as ET
from PIL import Image
from scipy.spatial import ConvexHull
from cooperation_prepare import prepare,require_native_docking_version
project=Path(sys.argv[1]);out=Path(sys.argv[2])
m=prepare(SimpleNamespace(so101_project=project.parent/'so101',fishbot_project=project,output=out))
j100_profile=out/'j100-profile.json';j100_profile.write_text(json.dumps({'vehicle':'jackal_j100'}))
j100=prepare(SimpleNamespace(so101_project=project.parent/'so101',fishbot_project=project,
    output=out/'j100',scene_profile=j100_profile))
declared={'mode':'perturbed','max_covariance':[.01,.01,.01],
          'noise_std':[.01,.02,.03],'bias':[.02,-.01,.01],
          'dropout_probability':.25,'seed':37,'occlusion_windows':[[2.,3.]]}
declaration=out/'declared-perception.json';declaration.write_text(json.dumps(declared))
condition=prepare(SimpleNamespace(so101_project=project.parent/'so101',fishbot_project=project,
                                output=out/'perturbed',perception_config=declaration))
vision_declaration=out/'vision-perception.json'
vision_declaration.write_text(json.dumps({'mode':'vision','publisher':'station_camera',
    'min_confidence':.75,'max_covariance':[.0013,.0014,.019]}))
vision=prepare(SimpleNamespace(so101_project=project.parent/'so101',fishbot_project=project,
    output=out/'vision',perception_config=vision_declaration))
vision_nav=yaml.safe_load(Path(vision['nav2_yaml']).read_text())
vision_staging={'pose':vision['staging_pose'],'dock_pose':vision['dock_pose'],
    'native_staging_offset':vision_nav['docking_server']['ros__parameters']['station_plugin']['staging_x_offset']}
default_nav=yaml.safe_load(Path(m['nav2_yaml']).read_text())
perturbed_nav=yaml.safe_load(Path(condition['nav2_yaml']).read_text())
for configured in (default_nav,perturbed_nav):
 configured['bt_navigator']['ros__parameters'].pop('default_nav_to_pose_bt_xml')
loaded_condition=json.loads((out/'perturbed/scene-manifest.json').read_text())
condition_result={'config':condition['station_perception'],
                  'persisted_matches':loaded_condition['station_perception']==condition['station_perception'],
                  'no_ideal_claim':'ideal_station_perception' not in condition,
                  'world_xml_unchanged':hashlib.sha256(Path(m['world_xml']).read_bytes()).hexdigest()==hashlib.sha256(Path(condition['world_xml']).read_bytes()).hexdigest(),
                  'map_pixels_unchanged':all(m[key]==condition[key] for key in ('generated_map_sha256','generated_collision_map_sha256')),
                  'nav2_parameters_unchanged':default_nav==perturbed_nav}
invalid=out/'invalid-perception.json';invalid.write_text(json.dumps({'station_id':'other_station'}))
try:
 prepare(SimpleNamespace(so101_project=project.parent/'so101',fishbot_project=project,
                         output=out/'invalid',perception_config=invalid))
 condition_result['wrong_station_rejected_before_generation']=False
except ValueError:
 condition_result['wrong_station_rejected_before_generation']=not (out/'invalid').exists()
maps={name:np.asarray(Image.open(yaml.safe_load(Path(m[key]).read_text())['image']))[::-1]
      for name,key in [('localization','localization_map_yaml'),('collision','collision_map_yaml')]}
def pixel(name,x,y):return int(maps[name][int((y+4.2)/.02),int((x+4.2)/.02)])
source=yaml.safe_load((project/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/config/nav2.yaml').read_text())
params=yaml.safe_load(Path(m['nav2_yaml']).read_text())
try:
 require_native_docking_version('1.3.14')
 rejects_unverified_docking_version=False
except RuntimeError:
 rejects_unverified_docking_version=True
behavior_path=Path(params['bt_navigator']['ros__parameters']['default_nav_to_pose_bt_xml'])
behavior=ET.parse(behavior_path).getroot()
default=ET.parse('/opt/ros/jazzy/share/nav2_bt_navigator/behavior_trees/navigate_to_pose_w_replanning_and_recovery.xml').getroot()
branch=behavior.find('.//RateController/RecoveryNode/Fallback')
native_condition=(branch is not None and branch.find('ReactiveSequence/Inverter/GlobalUpdatedGoal') is not None
                  and branch.find('ReactiveSequence/IsPathValid') is not None
                  and len(branch.findall('ComputePathToPose'))==1)
original_parent=default.find('.//RateController/RecoveryNode');original_action=original_parent.find('ComputePathToPose')
new_action=branch.find('ComputePathToPose') if branch is not None else None
planner_unchanged=new_action is not None and new_action.attrib==original_action.attrib
original_parent.remove(original_action)
if branch is not None:behavior.find('.//RateController/RecoveryNode').remove(branch)
other_nodes_unchanged=ET.tostring(default)==ET.tostring(behavior)
preserved={name:{key:params[name][name]['ros__parameters'].get(key)==source[name][name]['ros__parameters'].get(key)
                 for key in ('robot_radius','footprint_padding')}
           for name in ('global_costmap','local_costmap')}
model=mujoco.MjModel.from_xml_path(m['world_xml']);data=mujoco.MjData(model)
data.qpos[:6]=m['arm_home_qpos6']
# The parked pose from the first failed shared-world navigation episode.
data.qpos[13:20]=[-1.7262360873183609,-1.793048479242986,-.00005856341112695703,
                 -.8504429947307602,.0002027183730955877,.00033301491582677305,.5260670686516161]
mujoco.mj_forward(model,data)
car=model.body('base_footprint').id;descendants={car}
for b in range(model.nbody):
 if int(model.body_parentid[b]) in descendants:descendants.add(b)
for g in range(model.ngeom):
 if int(model.geom_bodyid[g]) in descendants:model.geom_group[g]=5
 elif not (model.geom_contype[g] or model.geom_conaffinity[g]):model.geom_group[g]=4
laser=model.body('laser_link').id;origin=data.xpos[laser];angle=np.deg2rad(303)
direction=data.xmat[laser].reshape(3,3)@np.array([np.cos(angle),np.sin(angle),0.])
actual=mujoco.mj_ray(model,data,origin,direction,np.array([1,1,1,1,0,0],dtype=np.uint8),1,-1,np.empty(1,dtype=np.int32))
car_rotation=data.xmat[car].reshape(3,3)
compiled_tray_corners=[]
for geom in range(model.ngeom):
 if model.geom(geom).name.startswith('place_') and model.geom_type[geom]==mujoco.mjtGeom.mjGEOM_BOX:
  local=np.array([[x,y,z] for x in (-1,1) for y in (-1,1) for z in (-1,1)])*model.geom_size[geom]
  world=local@data.geom_xmat[geom].reshape(3,3).T+data.geom_xpos[geom]
  compiled_tray_corners.extend(((world-data.xpos[car])@car_rotation)[:,:2].tolist())
configured_footprints={name:json.loads(params[name][name]['ros__parameters']['footprint'])
                       for name in ('global_costmap','local_costmap')}
# Test the complete padded shape against actual generated lethal cell squares.
# This is stronger than a perimeter-only check and uses the compiled scene map.
padded=np.array(configured_footprints['local_costmap'])
padded+=params['local_costmap']['local_costmap']['ros__parameters'].get('footprint_padding',.01)*np.sign(padded)
lethal=np.column_stack(np.where(maps['collision']==0)[::-1]);centers=-4.2+(lethal+.5)*.02
edges=np.roll(padded,-1,axis=0)-padded
axes=np.vstack([np.eye(2),np.column_stack([-edges[:,1],edges[:,0]])])
axes/=np.linalg.norm(axes,axis=1)[:,None]
def overlaps_lethal_cell(x,y):
 poly=padded+np.array([x,y]);low=poly.min(axis=0);high=poly.max(axis=0)
 selected=centers[np.all(centers+.01>=low-1e-10,axis=1)&np.all(centers-.01<=high+1e-10,axis=1)]
 if not len(selected):return False
 pp=poly@axes.T
 box=selected[:,None,:]+np.array([[-.01,-.01],[-.01,.01],[.01,-.01],[.01,.01]])[None,:,:]
 bp=box@axes.T
 return bool(np.any(np.all((bp.max(axis=1)>=pp.min(axis=0)-1e-10)&
                           (bp.min(axis=1)<=pp.max(axis=0)+1e-10),axis=1)))
dock=np.array(m['dock_pose']);projection=m['native_docking']['controller_target_projection_m']
virtual=dock[:2]+projection*np.array([np.cos(m['native_dock_pose'][2]),np.sin(m['native_dock_pose'][2])])
collision_threshold=params['docking_server']['ros__parameters']['controller']['dock_collision_threshold']
stop_sweep=[]
for offset in np.arange(.06,-projection-.001,-.005):
 point=dock[:2]+offset*np.array([np.cos(dock[2]),np.sin(dock[2])])
 stop_sweep.append({'offset_m':float(offset),'full_shape_collision':overlaps_lethal_cell(*point),
                    'native_check_applies':bool(np.linalg.norm(point-virtual)>collision_threshold)})
containment={}
for name,polygon in configured_footprints.items():
 equations=ConvexHull(np.asarray(polygon)).equations
 containment[name]=bool(np.all(np.asarray(compiled_tray_corners)@equations[:,:2].T+equations[:,2]<=1e-9))
sample_distances=np.arange(.12,3.5,.001);points=origin[:2]+sample_distances[:,None]*direction[:2]
indices=np.floor((points+4.2)/.02).astype(int)
predicted={name:float(sample_distances[np.flatnonzero(image[indices[:,1],indices[:,0]]==0)[0]])
           for name,image in maps.items()}
result={'egress':{'legacy_absent':'egress_pose' not in m, 'pose':j100.get('egress_pose'),
                  'staging':j100['staging_pose'],'dock':j100['dock_pose'],
                  'motion':j100.get('egress_motion'),
                  'legacy_motion_absent':'egress_motion' not in m},
        'height':m['localization_laser_height_m'],'different_maps':m['localization_map_yaml']!=m['collision_map_yaml'],
        'map_alias':m['map_yaml']==m['localization_map_yaml'],'preserved':preserved,
        'map_topics':[params[name][name]['ros__parameters']['static_layer']['map_topic'] for name in ('global_costmap','local_costmap')],
        'collision_check':params['controller_server']['ros__parameters']['FollowPath']['use_collision_detection'],
        'progress_checker':params['controller_server']['ros__parameters']['progress_checker'],
        'source_progress_checker':source['controller_server']['ros__parameters']['progress_checker'],
        'passage_progress_checker':yaml.safe_load((project/'tools/config/fishbot_passage_nav.yaml').read_text())['controller_server']['ros__parameters']['progress_checker'],
        'registered_progress_plugins':[node.get('type') for node in ET.parse('/opt/ros/jazzy/share/nav2_controller/plugins.xml').getroot().iter('class') if node.get('base_class_type')=='nav2_core::ProgressChecker'],
        'behavior':{'config_matches_manifest':str(behavior_path)==m['navigation_behavior_tree'],
            'exists':behavior_path.is_file(),'private_mode':behavior_path.stat().st_mode & 0o777,
            'native_condition':native_condition,'planner_unchanged':planner_unchanged,
            'other_nodes_unchanged':other_nodes_unchanged,
            'no_timing_wrappers':not behavior.findall('.//RecoveryNode[@name="BoundedTimingFollowPath"]'),
            'generated_hash_matches':hashlib.sha256(behavior_path.read_bytes()).hexdigest()==m['navigation_behavior_tree_sha256'],
            'source_hash_matches':[hashlib.sha256(Path(entry['path']).read_bytes()).hexdigest()==entry['sha256'] for entry in m['navigation_behavior_tree_sources']],
            'source_count':len(m['navigation_behavior_tree_sources'])},
        'bench_pixels':{name:pixel(name,-1.85,-2.07) for name in maps},
        'obstacle_pixels':{name:pixel(name,-1.735,-2.) for name in maps},
        'geometry_names':[section['name'] for section in m['localization_slice_polygons']],
        'actual_ray':float(actual),'predicted':predicted,
        'docking':params['docking_server']['ros__parameters'],
        'native_docking':m['native_docking'],'staging_pose':m['staging_pose'],
        'robot_dock_pose':m['dock_pose'],'native_dock_pose':m['native_dock_pose'],
        'ideal_station_perception':m['ideal_station_perception'],
        'station_perception':m['station_perception'],'condition_result':condition_result,
        'vision_staging':vision_staging,
        'localization_parameters':m['localization_parameters'],
        'configured_footprints':configured_footprints,'manifest_footprint':m['car_footprint_xy'],
        'stop_sweep':stop_sweep,
        'rejects_unverified_docking_version':rejects_unverified_docking_version,
        'footprint_frame':m['car_footprint_frame'],'tray_corners':compiled_tray_corners,
        'compiled_tray_corners_contained':containment,
        'footprint_original_radius':m['car_footprint_original_radius_m'],
        'installed_docking_version':ET.parse('/opt/ros/jazzy/share/opennav_docking/package.xml').getroot().findtext('version'),
        'registered_docking_plugins':[node.get('type') for node in ET.parse('/opt/ros/jazzy/share/opennav_docking/plugins.xml').getroot().iter('class')]}
print('RESULT_JSON:'+json.dumps(result))
'''
        result = subprocess.run([str(RUNTIME), '-B', '-c', code, str(PROJECT), cls.temp.name],
                                text=True, capture_output=True, timeout=90)
        if result.returncode:
            raise RuntimeError(f'Dual-map probe failed:\n{result.stdout}\n{result.stderr}')
        cls.evidence = json.loads(result.stdout.rsplit('RESULT_JSON:', 1)[1])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_j100_declares_straight_staging_egress_without_changing_legacy(self):
        e = self.evidence['egress']
        self.assertTrue(e['legacy_absent'])
        self.assertEqual(e['pose'], dict(zip(('x', 'y', 'yaw'), e['staging'])))
        self.assertAlmostEqual(e['pose']['x']-e['dock'][0], .7)
        self.assertEqual(e['pose']['y'], e['dock'][1])
        self.assertEqual(e['pose']['yaw'], e['dock'][2])
        self.assertTrue(e['legacy_motion_absent'])
        self.assertEqual(e['motion'], {'type':'drive_on_heading', 'distance_m':.7,
                                      'speed_m_s':.03, 'time_allowance_s':45.})

    def test_localization_and_collision_maps_use_separate_native_topics(self):
        self.assertTrue(self.evidence['different_maps'])
        self.assertTrue(self.evidence['map_alias'])
        self.assertEqual(self.evidence['map_topics'], ['/cooperation_collision_map']*2)

    def test_default_and_declared_perception_are_persisted_without_changing_physics(self):
        default = self.evidence['station_perception']
        self.assertEqual(default['mode'], 'ideal')
        self.assertEqual(default['publisher'], 'cooperation_physics')
        self.assertEqual(default['max_covariance'], [.0001]*3)
        self.assertEqual(default['min_confidence'], 1.)
        declared = self.evidence['condition_result']
        for key in ('persisted_matches','no_ideal_claim','world_xml_unchanged',
                    'map_pixels_unchanged','nav2_parameters_unchanged',
                    'wrong_station_rejected_before_generation'):
            self.assertTrue(declared[key], key)
        self.assertEqual(declared['config']['mode'], 'perturbed')
        self.assertEqual(declared['config']['noise_std'], [.01,.02,.03])
        self.assertEqual(declared['config']['bias'], [.02,-.01,.01])
        self.assertEqual(declared['config']['dropout_probability'], .25)
        self.assertEqual(declared['config']['seed'], 37)
        self.assertEqual(declared['config']['occlusion_windows'], [[2.,3.]])

    def test_laser_slice_omits_low_bench_but_collision_map_retains_it(self):
        self.assertAlmostEqual(self.evidence['height'], .167)
        self.assertEqual(self.evidence['bench_pixels'], {'localization': 254, 'collision': 0})
        self.assertEqual(self.evidence['obstacle_pixels'], {'localization': 0, 'collision': 0})
        for name in ('pick_floor', 'worktable', 'pick_bench', 'bench_bridge', 'collision_base_0'):
            self.assertNotIn(name, self.evidence['geometry_names'])

    def test_source_radius_padding_and_rpp_collision_check_remain_enabled(self):
        self.assertTrue(all(all(values.values()) for values in self.evidence['preserved'].values()))
        self.assertTrue(self.evidence['collision_check'])

    def test_both_costmaps_use_the_complete_compiled_body_and_tray_polygon(self):
        self.assertEqual(self.evidence['footprint_frame'], 'base_footprint')
        self.assertEqual(self.evidence['footprint_original_radius'], .13)
        self.assertGreaterEqual(len(self.evidence['manifest_footprint']), 3)
        self.assertEqual(len(self.evidence['tray_corners']), 40)
        for name in ('global_costmap', 'local_costmap'):
            self.assertEqual(self.evidence['configured_footprints'][name], self.evidence['manifest_footprint'])
            self.assertTrue(self.evidence['compiled_tray_corners_contained'][name], name)

    def test_short_transit_counts_native_angular_progress_without_relaxing_stall_limits(self):
        checker = self.evidence['progress_checker']
        self.assertEqual(checker['plugin'], 'nav2_controller::PoseProgressChecker')
        self.assertIn(checker['plugin'], self.evidence['registered_progress_plugins'])
        self.assertEqual(checker['required_movement_angle'], .1)
        self.assertEqual(checker['required_movement_angle'],
                         self.evidence['passage_progress_checker']['required_movement_angle'])
        for name in ('required_movement_radius', 'movement_time_allowance'):
            self.assertEqual(checker[name], self.evidence['source_progress_checker'][name])

    def test_native_path_validity_condition_preserves_default_actions_and_recoveries(self):
        behavior = self.evidence['behavior']
        for name in ('config_matches_manifest', 'exists', 'native_condition',
                     'planner_unchanged', 'other_nodes_unchanged', 'no_timing_wrappers',
                     'generated_hash_matches'):
            self.assertTrue(behavior[name], name)
        self.assertEqual(behavior['private_mode'], 0o600)
        self.assertEqual(behavior['source_count'], 3)
        self.assertTrue(all(behavior['source_hash_matches']))

    def test_failed_episode_ray_matches_slice_instead_of_low_fixture_projection(self):
        self.assertGreater(self.evidence['actual_ray'], 2.4)
        self.assertLess(self.evidence['predicted']['collision'], .4)
        self.assertLess(abs(self.evidence['predicted']['localization']-self.evidence['actual_ray']), .02)

    def test_native_backward_workstation_has_separate_robot_and_station_frames(self):
        import math
        docking = self.evidence['docking']
        self.assertEqual(docking['dock_plugins'], ['station_plugin'])
        self.assertEqual(docking['docks'], ['so101_station'])
        self.assertEqual(docking['station_plugin']['plugin'], 'opennav_docking::SimpleNonChargingDock')
        self.assertIn(docking['station_plugin']['plugin'], self.evidence['registered_docking_plugins'])
        self.assertEqual(self.evidence['native_docking']['version'], self.evidence['installed_docking_version'])
        self.assertEqual(docking['so101_station']['type'], 'station_plugin')
        self.assertEqual(docking['so101_station']['frame'], 'map')
        self.assertEqual(docking['base_frame'], 'base_footprint')
        self.assertEqual(docking['fixed_frame'], 'odom')
        self.assertTrue(docking['dock_backwards'])
        self.assertNotIn('dock_direction', docking)
        self.assertEqual(self.evidence['robot_dock_pose'], [-1.8, -1.8, 0.])
        for actual, expected in zip(self.evidence['staging_pose'], [-1.1, -1.8, 0.]):
            self.assertAlmostEqual(actual, expected)
        self.assertAlmostEqual(self.evidence['native_dock_pose'][2], math.pi)
        self.assertAlmostEqual(docking['station_plugin']['staging_yaw_offset'], math.pi)
        self.assertFalse(self.evidence['native_docking']['navigate_to_staging_pose'])

    def test_rgb_staging_reserves_resolution_margin_without_moving_final_dock(self):
        vision=self.evidence['vision_staging']
        for actual,expected in zip(vision['pose'],[-1.15,-1.8,0.]):
            self.assertAlmostEqual(actual,expected)
        self.assertEqual(vision['dock_pose'],self.evidence['robot_dock_pose'])
        self.assertAlmostEqual(vision['native_staging_offset'],-.65)

    def test_relative_perception_is_explicit_and_docking_preserves_collision_checks(self):
        docking = self.evidence['docking']
        plugin = docking['station_plugin']
        self.assertTrue(plugin['use_external_detection_pose'])
        self.assertFalse(plugin['use_stall_detection'])
        self.assertEqual(plugin['external_detection_timeout'], .5)
        self.assertEqual(plugin['filter_coef'], 1.)
        self.assertEqual(plugin['docking_threshold'], .02)
        for name in ('translation_x', 'translation_y', 'rotation_roll', 'rotation_pitch', 'rotation_yaw'):
            self.assertEqual(plugin['external_detection_'+name], 0.)
        self.assertTrue(docking['controller']['use_collision_detection'])
        self.assertEqual(docking['controller']['dock_collision_threshold'], .25)
        self.assertEqual(docking['controller']['projection_time'], 1.)
        self.assertEqual(docking['max_retries'], 0)
        self.assertEqual(docking['controller']['costmap_topic'], '/local_costmap/costmap_raw')
        self.assertEqual(docking['controller']['footprint_topic'], '/local_costmap/published_footprint')
        self.assertEqual(self.evidence['ideal_station_perception']['max_range_m'], 1.)
        self.assertEqual(self.evidence['ideal_station_perception']['native_station_pose'],
                         self.evidence['native_dock_pose'])
        self.assertEqual(self.evidence['localization_parameters'], {
            'laser_model_type': 'likelihood_field_prob', 'sigma_hit': .05, 'max_beams': 180,
            'z_hit': .95, 'z_rand': .05, 'update_min_d': .01, 'update_min_a': .01,
            'do_beamskip': False})

    def test_native_virtual_target_threshold_keeps_actual_stop_approach_checked(self):
        native = self.evidence['native_docking']
        self.assertEqual(native['controller_target_projection_m'], .25)
        self.assertTrue(self.evidence['rejects_unverified_docking_version'])
        self.assertEqual(native['max_retries'], 0)
        self.assertEqual(native['supported_action_path'], 'DockRobot approach only')
        self.assertEqual(native['unsupported_action_paths'], ['resetApproach', 'UndockRobot'])
        self.assertEqual(len(native['primary_sources']), 3)
        for source in native['primary_sources']:
            self.assertIn('/navigation2/1.3.13/nav2_docking/', source['url'])
            self.assertRegex(source['sha256'], r'^[0-9a-f]{64}$')
        sweep = self.evidence['stop_sweep']
        actual_approach = [point for point in sweep if point['offset_m'] > .02+1e-9]
        self.assertTrue(actual_approach)
        self.assertTrue(all(point['native_check_applies'] for point in actual_approach))
        self.assertTrue(all(not point['full_shape_collision'] for point in sweep
                            if point['offset_m'] >= -1e-9))
        collisions = [point for point in sweep if point['full_shape_collision']]
        self.assertTrue(collisions, 'The generated fixture must exercise the post-stop obstacle')
        self.assertTrue(all(point['offset_m'] < -.02 and not point['native_check_applies']
                            for point in collisions))


if __name__ == '__main__':
    unittest.main()
