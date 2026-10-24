"""Native multi-entity fixtures; no ROS, navigation or order-success claim."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cooperation_business_scene import bind_entities, compose_business_world
from cooperation_checkpoint import capture, restore
from cooperation_scene import build_scene
from cooperation_sim import Physics
from cooperation_arm import ArmPlanner
from cooperation_arm_entities import ArmEntityView


class BusinessSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temp.name)
        project = Path(__file__).resolve().parents[2]
        cls.base = build_scene(project.parent/'so101', project, cls.directory/'base',
            scene_profile={'schema': 1, 'vehicle': 'jackal_j100', 'sensors': 'lidar3d', 'task': 'transport'})
        cls.configuration = {'id': 'f1-continuous-b', 'unload_stations': [
            {'id': 'line_b', 'delivery_pose': {'x': .7, 'y': -2., 'yaw': 0.},
             'arm_yaw_rad': math.pi/2, 'shelf_xy_m': [.05, -.22], 'bridge_center_xy_m': [.033, -.145]}],
            'cargo_slots': [{'id': 'cargo_1', 'offset_m': [0., 0., 0.]},
                            {'id': 'cargo_2', 'offset_m': [0., .04, 0.]}]}
        cls.output = cls.directory/'continuous';cls.output.mkdir()
        cls.manifest = compose_business_world(cls.base, cls.configuration, cls.output)
        cls.path = cls.output/'scene-manifest.json'
        cls.path.write_text(json.dumps(cls.manifest))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def plant(self):
        return Physics(self.manifest['world_xml'], manifest=self.path)

    def test_default_scene_and_legacy_entities_are_preserved(self):
        import mujoco
        self.assertNotIn('business_entities', self.base)
        original = mujoco.MjModel.from_xml_path(self.base['world_xml'])
        compound = mujoco.MjModel.from_xml_path(self.manifest['world_xml'])
        self.assertEqual((compound.nq-original.nq, compound.nv-original.nv, compound.nu-original.nu), (13, 12, 6))
        for i in range(original.nbody):
            name = original.body(i).name
            if name:
                j = compound.body(name).id
                self.assertEqual(original.body_mass[i], compound.body_mass[j])
                self.assertTrue((original.body_inertia[i] == compound.body_inertia[j]).all())
        self.assertEqual(compound.opt.timestep, original.opt.timestep)
        for i in range(original.ngeom):
            name = original.geom(i).name
            if name:
                j = compound.geom(name).id
                for field in ('geom_size', 'geom_friction', 'geom_solref', 'geom_solimp'):
                    self.assertTrue((getattr(original, field)[i] == getattr(compound, field)[j]).all(), (name, field))
        for i in range(original.nu):
            j = compound.actuator(original.actuator(i).name).id
            for field in ('actuator_gainprm', 'actuator_biasprm', 'actuator_ctrlrange', 'actuator_forcerange'):
                self.assertTrue((getattr(original, field)[i] == getattr(compound, field)[j]).all(), field)

    def test_declared_shelf_cells_are_distinct_and_inside_the_original_shelf(self):
        configuration=copy.deepcopy(self.configuration)
        cells={'cargo_1':{'center_xy_m':[.02,-.22],'half_size_xy_m':[.028,.058]},
               'cargo_2':{'center_xy_m':[.08,-.22],'half_size_xy_m':[.028,.058]}}
        configuration['unload_stations'][0]['cargo_shelf_slots']=cells
        with tempfile.TemporaryDirectory() as output:
            result=compose_business_world(self.base,configuration,output)
            self.assertEqual(result['business_entities']['unload_stations']['line_b']['cargo_shelf_slots'],cells)
        for bad in ('overlap','outside','unknown'):
            item=copy.deepcopy(configuration)
            slots=item['unload_stations'][0]['cargo_shelf_slots']
            if bad=='overlap':slots['cargo_2']['center_xy_m']=[.02,-.22]
            elif bad=='outside':slots['cargo_2']['center_xy_m']=[.12,-.22]
            else:slots['unknown']=slots.pop('cargo_2')
            with self.subTest(bad=bad),tempfile.TemporaryDirectory() as output,self.assertRaises(ValueError):
                compose_business_world(self.base,item,output)

    def test_delivery_pose_is_physically_clear_in_a_fresh_initial_world(self):
        import xml.etree.ElementTree as ET
        manifest = copy.deepcopy(self.manifest)
        root = ET.parse(manifest['world_xml']).getroot()
        car = root.find("worldbody/body[@name='base_footprint']")
        car.set('pos', '.7 -2 0')
        path = self.directory/'delivery-initial.xml'
        ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)
        manifest['world_xml'] = str(path)
        m = self.directory/'delivery-initial.json';m.write_text(json.dumps(manifest))
        plant = Physics(path, manifest=m)
        for _ in range(1000):plant.step()
        plant.refresh_snapshot();state = plant.state()
        self.assertEqual(state['arm_forbidden_contact_total'], 0)
        self.assertEqual(state['car_forbidden_contact_total'], 0)
        self.assertEqual(state['episode_reset']['count'], 0)

    def test_serialized_index_hints_do_not_rebind_an_entity(self):
        plant = self.plant()
        entities = copy.deepcopy(self.manifest['business_entities'])
        entities['arms']['unload_line_b']['qpos_indices'] = [0]*6
        arms, cargo = bind_entities(plant.model, entities)
        self.assertTrue(set(arms['load']['qpos']).isdisjoint(arms['unload_line_b']['qpos']))
        self.assertNotEqual(cargo['cargo_1']['joint'], cargo['cargo_2']['joint'])

    def test_both_free_cargo_and_arms_live_in_one_physics_world(self):
        plant = self.plant()
        episode = plant.episode_id
        for _ in range(1000):plant.step()
        plant.refresh_snapshot();state = plant.state();entities = state['business_entities']
        self.assertEqual(plant.episode_id, episode)
        self.assertAlmostEqual(state['stamp'], 2.)
        self.assertEqual(state['episode_reset']['count'], 0)
        self.assertEqual(state['arm_forbidden_contact_total'], 0)
        self.assertEqual(state['car_forbidden_contact_total'], 0)
        self.assertEqual(set(entities['arms']), {'load', 'unload_line_b'})
        self.assertEqual(set(entities['cargo']), {'cargo_1', 'cargo_2'})
        first, second = (entities['cargo'][name] for name in ('cargo_1', 'cargo_2'))
        self.assertAlmostEqual(second['position'][1]-first['position'][1], .04, places=6)
        for item in (first, second):
            self.assertGreater(item['contacts']['supports']['pickup']['contact_count'], 0)
            self.assertAlmostEqual(item['contacts']['supports']['pickup']['normal_force_n'], .0981, places=5)
            self.assertEqual(item['contacts']['pads'], {})
            self.assertEqual(item['contacts']['other_cargo'], {})

    def test_snapshot_restores_added_arm_target_and_both_cargo_dynamics(self):
        import numpy as np
        a = self.plant()
        for _ in range(50):a.step()
        arm = a.business_arms['unload_line_b']
        target = list(arm['reference']);target[0] += .02
        arm['reference'] = tuple(target)
        a.refresh_snapshot();snapshot = capture(a)
        b = self.plant();result = restore(b, snapshot)
        self.assertTrue(result['restored'], result)
        self.assertEqual(b.business_arms['unload_line_b']['reference'], tuple(target))
        for _ in range(100):a.step();b.step()
        np.testing.assert_array_equal(a.data.qpos, b.data.qpos)
        np.testing.assert_array_equal(a.data.qvel, b.data.qvel)

    def test_existing_named_reference_moves_only_the_selected_arm(self):
        plant = self.plant();primary = tuple(plant.reference)
        arm = plant.business_arms['unload_line_b']
        target = list(arm['reference']);target[0] += .02
        plant.set_arm_reference(list(reversed(arm['joint_names'])), list(reversed(target)))
        self.assertEqual(tuple(arm['reference']), tuple(target))
        self.assertEqual(tuple(plant.reference), primary)
        for _ in range(100):plant.step()
        self.assertEqual(plant.data.ctrl[arm['actuators']].tolist(), target)
        with self.assertRaises(ValueError):
            plant.set_arm_reference(arm['joint_names'], [999.]*6)
        self.assertEqual(tuple(arm['reference']), tuple(target))

    def test_secondary_cargo_motion_prevents_a_false_quiet_reset(self):
        plant = self.plant()
        for _ in range(1000):plant.step()
        plant.refresh_snapshot()
        self.assertTrue(plant.reset_physical_quiet())
        joint = plant.business_cargo['cargo_2']['joint']
        dof = int(plant.model.jnt_dofadr[joint])
        plant.data.qvel[dof] = .01
        plant.refresh_snapshot()
        self.assertFalse(plant.reset_physical_quiet())

    def test_missing_added_arm_target_skips_only_the_restore_case(self):
        a = self.plant();snapshot = capture(a)
        snapshot['application'].pop('additional_arm_references')
        b = self.plant();before = b.data.qpos.copy();result = restore(b, snapshot)
        self.assertFalse(result['restored'])
        self.assertFalse(result['active_world_changed'])
        self.assertTrue((before == b.data.qpos).all())

    def test_entity_snapshot_uses_names_and_rotates_linear_velocity_only(self):
        import numpy as np
        plant = self.plant()
        joint = plant.business_cargo['cargo_2']['joint']
        dof = int(plant.model.jnt_dofadr[joint])
        plant.data.qvel[dof:dof+6] = [1., 2., 3., .1, .2, .3]
        snapshot = {'qpos': plant.data.qpos.tolist(), 'qvel': plant.data.qvel.tolist(),
                    'ctrl': plant.data.ctrl.tolist()}
        before = plant.data.qpos.copy()
        view = ArmEntityView(self.manifest, plant.model, 'unload_line_b', 'cargo_2', snapshot)
        local = view.canonical_snapshot(snapshot)
        np.testing.assert_allclose(local['qvel'][6:9], [2., -1., 3.], atol=1e-14)
        np.testing.assert_allclose(local['qvel'][9:12], [.1, .2, .3], atol=1e-14)
        np.testing.assert_allclose(view.rotation @ local['qpos'][6:9]+view.origin,
                                   plant.data.qpos[plant.model.jnt_qposadr[joint]:][:3], atol=1e-14)
        np.testing.assert_array_equal(plant.data.qpos, before)

    def test_named_query_keeps_other_entities_and_full_mesh_hulls(self):
        import mujoco
        import numpy as np
        plant = self.plant()
        snapshot = {'qpos': plant.data.qpos.tolist(), 'qvel': plant.data.qvel.tolist()}
        before = plant.data.qpos.copy()
        planner = ArmPlanner(self.manifest, arm_id='unload_line_b', cargo_id='cargo_2', snapshot=snapshot)
        self.assertEqual((planner.rig.nq, planner.contact.nq), (6, 13))
        self.assertEqual(planner.entity_contract()['joint_names'],
                         self.manifest['business_entities']['arms']['unload_line_b']['joint_names'])
        view = planner.entity_view
        frozen = {item['source']: item['query'] for item in view.frozen_geoms}
        self.assertIn('target_collision', frozen)
        self.assertNotIn('cargo_2__target_collision', frozen)
        self.assertIn('car_tray_floor' if 'car_tray_floor' in frozen else 'place_floor', frozen)
        data = mujoco.MjData(planner.rig);mujoco.mj_forward(planner.rig, data)
        seen_meshes = 0
        for source, query in frozen.items():
            a, b = plant.model.geom(source).id, planner.rig.geom(query).id
            self.assertEqual(plant.model.geom_type[a], planner.rig.geom_type[b])
            self.assertEqual(plant.model.geom_contype[a], planner.rig.geom_contype[b])
            self.assertEqual(plant.model.geom_conaffinity[a], planner.rig.geom_conaffinity[b])
            if plant.model.geom_type[a] != mujoco.mjtGeom.mjGEOM_MESH:
                np.testing.assert_allclose(planner.rig.geom_size[b], plant.model.geom_size[a], atol=1e-14)
                np.testing.assert_allclose(data.geom_xpos[b], view.point(view.data.geom_xpos[a]), atol=1e-12)
                continue
            seen_meshes += 1
            def vertices(model, state, geom):
                mesh = int(model.geom_dataid[geom]);start = model.mesh_vertadr[mesh]
                v = model.mesh_vert[start:start+model.mesh_vertnum[mesh]]
                return v @ state.geom_xmat[geom].reshape(3, 3).T+state.geom_xpos[geom]
            original = (vertices(plant.model, view.data, a)-view.origin) @ view.rotation
            copied = vertices(planner.rig, data, b)
            directions = np.vstack([np.eye(3), -np.eye(3), [[1, 1, 1], [1, -2, 3]]])
            np.testing.assert_allclose(np.max(original @ directions.T, axis=0),
                                       np.max(copied @ directions.T, axis=0), atol=2e-7)
        self.assertGreater(seen_meshes, 10)
        np.testing.assert_array_equal(plant.data.qpos, before)
        with self.assertRaisesRegex(ValueError, 'explicit station route'):
            planner.prepare_transport(snapshot)

    def test_named_query_cannot_use_an_implicit_entity_or_truncated_snapshot(self):
        plant = self.plant()
        with self.assertRaisesRegex(ValueError, 'explicit arm_id and cargo_id'):
            ArmPlanner(self.manifest)
        with self.assertRaisesRegex(ValueError, 'measured snapshot'):
            ArmPlanner(self.manifest, arm_id='load', cargo_id='cargo_1')
        with self.assertRaisesRegex(ValueError, 'full common-world snapshot'):
            ArmEntityView(self.manifest, plant.model, 'load', 'cargo_2', {'qpos': [0.]*13, 'qvel': [0.]*12})

    def test_named_grasp_preserves_the_original_pinch_above_the_settled_center(self):
        import numpy as np
        plant = self.plant()
        for _ in range(1000):plant.step()
        snapshot = {'qpos': plant.data.qpos.tolist(), 'qvel': plant.data.qvel.tolist()}
        planner = ArmPlanner(self.manifest, arm_id='load', cargo_id='cargo_2', snapshot=snapshot)
        target = planner.grasp_target()
        np.testing.assert_allclose(target[:2], [.24, -.09], atol=1e-12)
        self.assertAlmostEqual(target[2], .019, delta=.0001)
        down = planner.modules['grasp_episode'].solve_pinch_ik(planner.rig, target, planner.home[:5])
        self.assertTrue(planner.open_checker.evaluate(down)['valid'])
        self.assertTrue(planner.closed_checker.evaluate(down)['valid'])

    def test_placement_contact_query_retains_selected_actuator_effort_and_source_time(self):
        import numpy as np
        plant = self.plant();arm = plant.business_arms['unload_line_b']
        snapshot = {'qpos': plant.data.qpos.tolist(), 'qvel': plant.data.qvel.tolist(),
                    'ctrl': plant.data.ctrl.tolist(), 'stamp': 12.34}
        for i, actuator in enumerate(arm['actuators']):snapshot['ctrl'][actuator] = .01*(i+1)
        planner = ArmPlanner(self.manifest, arm_id='unload_line_b', cargo_id='cargo_1', snapshot=snapshot)
        observed = {}
        def forces(model, data):
            observed.update(ctrl=data.ctrl.copy(), source_time=float(data.time))
            return {'fixed': 0., 'moving': 0.}
        with patch.object(planner.modules['grasp_episode'], 'grasp_contacts', side_effect=forces):
            with self.assertRaisesRegex(RuntimeError, 'no measured dual-finger contact'):
                planner.prepare_placement(snapshot, [[.05, -.22, .019]])
        np.testing.assert_array_equal(observed['ctrl'], np.array(snapshot['ctrl'])[arm['actuators']])
        self.assertEqual(observed['source_time'], 12.34)
        snapshot.pop('ctrl')
        with self.assertRaisesRegex(ValueError, 'current actuator references'):
            planner.prepare_placement(snapshot, [[.05, -.22, .019]])

    def test_nonselected_cargo_overlapping_a_pad_is_rejected_without_moving_the_plant(self):
        import numpy as np
        plant = self.plant();before = plant.data.qpos.copy()
        joint = plant.business_cargo['cargo_2']['joint'];adr = int(plant.model.jnt_qposadr[joint])
        for pad in ('pad_gripper', 'pad_moving_jaw'):
            snapshot = {'qpos': plant.data.qpos.tolist(), 'qvel': plant.data.qvel.tolist()}
            snapshot['qpos'][adr:adr+3] = plant.data.geom_xpos[plant.model.geom(pad).id].tolist()
            planner = ArmPlanner(self.manifest, arm_id='load', cargo_id='cargo_1', snapshot=snapshot)
            result = planner.closed_checker.evaluate(plant.data.qpos[plant.business_arms['load']['qpos']],
                                                       require_fixed_gripper=False)
            self.assertFalse(result['valid'], result)
            self.assertIn('frozen__cargo_2__target_collision', result['pair'])
            self.assertLess(result['min_distance_m'], 0.)
        np.testing.assert_array_equal(plant.data.qpos, before)


if __name__ == '__main__':
    unittest.main()
