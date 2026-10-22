"""Factory task data and real static-geometry/map integration; no ROS actions."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT/'tools'))
from cooperation_factory_scene import (factory_template_jobs, normalize_factory_config,
                                       apply_factory_scene, OCCUPANCY_GEOM, factory_template_approaches)

CONFIG = PROJECT/'tools/config/factory_delivery'
RUNTIME = Path(os.environ.get('FISHBOT_SO101_PYTHON',
    str(Path.home()/'.cache/so101-colab/planning-venv/bin/python')))


class FactoryDeliveryContractTests(unittest.TestCase):
    def config(self):
        return json.loads((CONFIG/'line-side-open.json').read_text())

    def test_two_orders_use_original_transport_with_fresh_batch_ids(self):
        manifest = {'factory_delivery': self.config()}
        batches, goals, profile = factory_template_jobs(manifest)
        self.assertEqual(profile['task'], 'transport')
        self.assertEqual(len(batches), 2)
        self.assertTrue(all(str(uuid.UUID(value)) == value for value in batches))
        self.assertEqual([goals[batch] for batch in batches],
            [{'x': 0., 'y': -2., 'yaw': 0.}, {'x': .7, 'y': -2., 'yaw': 0.}])
        self.assertFalse(set(batches) & set(factory_template_jobs(manifest)[0]))

    def test_orders_override_demo_count_without_changing_vehicle_or_sensor(self):
        profile = {'schema': 1, 'vehicle': 'jackal_j100', 'sensors': 'lidar3d',
                   'task': 'three_batch_transport'}
        config = self.config()
        config['orders'] = list(reversed(config['orders']))
        batches, goals, actual = factory_template_jobs(
            {'factory_delivery': config, 'scene_profile': profile})
        self.assertEqual(actual, profile)
        self.assertEqual(len(batches), 2)
        self.assertEqual(goals[batches[0]], {'x': .7, 'y': -2., 'yaw': 0.})

    def test_optional_metadata_is_editable_and_input_not_modified(self):
        config = self.config()
        config['operator_notes'] = 'Move only this scene fixture during a later experiment.'
        before = copy.deepcopy(config)
        normalized = normalize_factory_config(config)
        self.assertEqual(config, before)
        self.assertEqual(normalized['operator_notes'], config['operator_notes'])

    def test_station_approach_keeps_final_pose_and_validates_yaw(self):
        config=self.config();original=copy.deepcopy(config['destinations'][1]['pose'])
        config['destinations'][1]['approach_poses']=[{'x':.5,'y':-1.68,'yaw':.1}]
        actual=normalize_factory_config(config)
        self.assertEqual(actual['destinations'][1]['pose'],original)
        self.assertEqual(actual['destinations'][1]['approach_poses'],[{'x':.5,'y':-1.68,'yaw':.1}])
        scene={'factory_delivery':config};batches,_,_=factory_template_jobs(scene)
        self.assertEqual(factory_template_approaches(scene,batches),
                         {batches[1]:[{'x':.5,'y':-1.68,'yaw':.1}]})
        config['destinations'][1]['approach_poses'][0]['yaw']=float('nan')
        with self.assertRaisesRegex(ValueError,'line_b'):normalize_factory_config(config)

    def test_invalid_destination_and_order_are_local_config_errors(self):
        for mutate in (
            lambda c: c['destinations'][0]['pose'].update(x=float('nan')),
            lambda c: c['orders'][0].update(destination_id='unknown'),
            lambda c: c['destinations'].append(copy.deepcopy(c['destinations'][0])),
            lambda c: c['orders'].append(copy.deepcopy(c['orders'][0])),
        ):
            config = self.config()
            mutate(config)
            with self.assertRaises(ValueError):
                normalize_factory_config(config)

    def test_invalid_occupied_geometry_is_rejected(self):
        for mutate in (
            lambda c: c['channel']['obstacle'].update(size_m=[-.1, .3, .5]),
            lambda c: c['channel']['obstacle'].update(center_m=[0., 0., float('inf')]),
            lambda c: c['channel'].update(occupied='true'),
        ):
            config = self.config()
            mutate(config)
            with self.assertRaises(ValueError):
                normalize_factory_config(config)

    def test_open_scene_only_adds_metadata_without_touching_xml(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = {key: str(Path(folder)/(key+'.xml'))
                     for key in ('world_xml', 'arm_contact_xml', 'rig_xml')}
            for path in paths.values():
                Path(path).write_text('<mujoco><worldbody/></mujoco>')
            before = {key: Path(path).read_bytes() for key, path in paths.items()}
            manifest = {**paths, 'dock_pose': [-1.8, -1.8, 0.],
                        'station_offset': [-2., -2., .16]}
            self.assertIs(apply_factory_scene(manifest, self.config()), manifest)
            self.assertEqual({key: Path(path).read_bytes() for key, path in paths.items()}, before)
            self.assertEqual(manifest['factory_delivery']['pickup_station']['id'], 'so101_station')


class FactoryDeliveryGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        code = r'''
import json, math, sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1]+'/tools')
sys.path.append('/usr/lib/python3/dist-packages')
import mujoco
import numpy as np
import yaml
from PIL import Image
from scipy.spatial import ConvexHull
from cooperation_prepare import prepare
from cooperation_factory_scene import OCCUPANCY_GEOM
from cooperation_geometry_check import check as original_incoming_geometry_check
project=Path(sys.argv[1]); output=Path(sys.argv[2]); result={}
def overlaps(a,b):
    # Independent separating-axis check of complete convex shapes.
    a,b=np.asarray(a),np.asarray(b)
    edges=np.vstack((np.roll(a,-1,axis=0)-a,np.roll(b,-1,axis=0)-b))
    axes=np.column_stack((-edges[:,1],edges[:,0]))
    pa,pb=a@axes.T,b@axes.T
    return bool(np.all((pa.max(axis=0)>=pb.min(axis=0)-1e-10)&
                       (pb.max(axis=0)>=pa.min(axis=0)-1e-10)))
def box_polygon(center,extent):
    return np.array(center)+np.array([[-1,-1],[1,-1],[1,1],[-1,1]])*np.array(extent)
for vehicle in ('fishbot','jackal_j100'):
    pair={}
    for variant in ('open','occupied'):
        folder=output/(vehicle+'-'+variant)
        profile=output/(vehicle+'-profile.json')
        profile.write_text(json.dumps({'schema':1,'vehicle':vehicle,'sensors':'planar','task':'transport'}))
        manifest=prepare(SimpleNamespace(so101_project=project.parent/'so101',
            fishbot_project=project,output=folder,scene_profile=profile,
            factory_config=project/'tools/config/factory_delivery'/('line-side-'+variant+'.json')))
        model=mujoco.MjModel.from_xml_path(manifest['world_xml']); data=mujoco.MjData(model)
        mujoco.mj_forward(model,data)
        config=manifest['factory_delivery']; obstacle=config['channel']['obstacle']
        center=obstacle['center_m']; size=obstacle['size_m']
        maps={}
        for key in ('collision_map_yaml','localization_map_yaml'):
            details=yaml.safe_load(Path(manifest[key]).read_text())
            image=np.asarray(Image.open(details['image']))[::-1]
            xy=np.floor((np.asarray(center[:2])-details['origin'][:2])/details['resolution']).astype(int)
            maps[key]=int(image[xy[1],xy[0]])
        geoms={mujoco.MjModel.from_xml_path(manifest[key]).geom(OCCUPANCY_GEOM).name
               for key in ('world_xml','arm_contact_xml','rig_xml')} if variant=='occupied' else set()
        nav=yaml.safe_load(Path(manifest['nav2_yaml']).read_text())
        padded=np.asarray(manifest['car_footprint_xy'])
        padded+=nav['local_costmap']['local_costmap']['ros__parameters'].get('footprint_padding',.01)*np.sign(padded)
        blocked=box_polygon(center[:2],np.asarray(size[:2])/2)
        staging=np.asarray(manifest['staging_pose'][:2]); target=np.array([.7,-2.])
        straight=np.vstack((padded+staging,padded+target))
        straight=straight[ConvexHull(straight).vertices]
        # A connected XY corridor at constant yaw is geometric evidence only;
        # native Nav2 still owns the nonholonomic trajectory and its outcome.
        corridor=[staging,[0.,-2.],[0.,-2.65],[.7,-2.65],[.7,-2.]]
        static=[box_polygon(r['center'][:2],r['extent'][:2]) for r in manifest['static_map_rectangles']]
        route_clear=True
        for start,end in zip(corridor,corridor[1:]):
            sweep=np.vstack((padded+start,padded+end))
            sweep=sweep[ConvexHull(sweep).vertices]
            route_clear=route_clear and not any(overlaps(sweep,box) for box in static)
        endpoints_clear=not any(overlaps(padded+point,blocked)
            for point in (manifest['dock_pose'][:2],manifest['staging_pose'][:2],manifest['spawn'],[0.,-2.],[.7,-2.]))
        incoming=original_incoming_geometry_check(folder/'scene-manifest.json')
        local_center={}
        if variant=='occupied':
            for key in ('world_xml','arm_contact_xml','rig_xml'):
                query=mujoco.MjModel.from_xml_path(manifest[key]); q=mujoco.MjData(query);mujoco.mj_forward(query,q)
                pos=q.geom_xpos[query.geom(OCCUPANCY_GEOM).id]
                local_center[key]=pos.tolist()
        pair[variant]={'maps':maps,'geoms':sorted(geoms),'center':local_center,
            'same_footprint':manifest['car_footprint_xy'],'pickup':config['pickup_station'],
            'dimensions':[model.nq,model.nv,model.nu],
            'physics':[model.opt.timestep,int(model.opt.noslip_iterations),model.opt.gravity.tolist()],
            'orders':config['orders'],'native_nav':nav,
            'direct_sweep_intersects_obstacle':overlaps(straight,blocked),
            'endpoints_clear_of_occupancy':endpoints_clear,'geometric_corridor_clear':route_clear,
            'original_incoming_geometry':incoming,
            'source_assumption':'full padded XY footprint, constant yaw; not a native motion-plan or completion proof'}
    result[vehicle]=pair
print('RESULT_JSON:'+json.dumps(result))
'''
        process = subprocess.run([str(RUNTIME), '-B', '-c', code, str(PROJECT), cls.temp.name],
                                 capture_output=True, text=True, timeout=180)
        if process.returncode:
            raise RuntimeError(process.stderr+process.stdout)
        cls.results = json.loads(next(line[len('RESULT_JSON:'):] for line in process.stdout.splitlines()
                                     if line.startswith('RESULT_JSON:')))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_occupied_box_exists_in_all_physical_and_arm_query_models(self):
        for vehicle, pair in self.results.items():
            with self.subTest(vehicle=vehicle):
                self.assertEqual(pair['occupied']['geoms'], [OCCUPANCY_GEOM])
                center = pair['occupied']['center']
                offset = pair['occupied']['pickup']['station_offset_m']
                self.assertEqual(center['world_xml'], [.35, -2.1, .25])
                for key in ('arm_contact_xml', 'rig_xml'):
                    for actual, expected, shift in zip(center[key], center['world_xml'], offset):
                        self.assertAlmostEqual(actual+shift, expected)

    def test_one_static_geometry_drives_both_maps(self):
        for vehicle, pair in self.results.items():
            with self.subTest(vehicle=vehicle):
                self.assertEqual(set(pair['open']['maps'].values()), {254})
                self.assertEqual(set(pair['occupied']['maps'].values()), {0})

    def test_obstacle_blocks_direct_full_footprint_but_has_geometric_corridor(self):
        for vehicle, pair in self.results.items():
            with self.subTest(vehicle=vehicle):
                self.assertTrue(pair['occupied']['direct_sweep_intersects_obstacle'])
                self.assertTrue(pair['occupied']['endpoints_clear_of_occupancy'])
                self.assertTrue(pair['occupied']['geometric_corridor_clear'])

    def test_original_incoming_geometry_preflight_passes_all_variants(self):
        for vehicle, pair in self.results.items():
            for variant, scene in pair.items():
                with self.subTest(vehicle=vehicle, variant=variant):
                    result = scene['original_incoming_geometry']
                    self.assertTrue(result['passed'], result)
                    self.assertFalse(result['robot_geometry_shrunk'])
                    self.assertGreater(result['certified_margin_m'], 0.)

    def test_same_orders_geometry_and_original_physics_across_variants(self):
        for vehicle, pair in self.results.items():
            with self.subTest(vehicle=vehicle):
                for key in ('orders', 'same_footprint', 'pickup', 'dimensions', 'physics', 'native_nav'):
                    # Generated behavior-tree and EKF paths differ by output directory.
                    if key != 'native_nav':
                        self.assertEqual(pair['open'][key], pair['occupied'][key])
                self.assertEqual(pair['occupied']['physics'], [.002, 10, [0., 0., -9.81]])
                for params in (pair['open']['native_nav'], pair['occupied']['native_nav']):
                    self.assertTrue(params['controller_server']['ros__parameters']['FollowPath']['use_collision_detection'])
                    self.assertEqual(params['controller_server']['ros__parameters']['general_goal_checker']['xy_goal_tolerance'], .015)


if __name__ == '__main__':
    unittest.main()
