"""Pure named-delivery measurements and stock transitions; no simulator imports."""
import copy
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cooperation_core import Rejected
from cooperation_business import (advance, all_quiet, new_inventory, normalize_delivery,
                                  observe, reserve, shelf_settled, validate_delivery, placement_slot)


def fixture():
    manifest = {'business_entities': {
        'arms': {'load': {'pad_geoms': ['pad_gripper', 'pad_moving_jaw'],
                          'station_position_m': [0., 0., 0.], 'station_yaw_rad': 0.},
                 'unload_b': {'pad_geoms': ['unload_b__pad_gripper', 'unload_b__pad_moving_jaw'],
                              'station_position_m': [10., 20., 1.], 'station_yaw_rad': math.pi/2}},
        'cargo': {f'cargo_{i}': {'body': f'body_{i}', 'free_joint': f'free_{i}', 'geom': f'geom_{i}'}
                  for i in (1, 2)},
        'unload_stations': {'line_b': {'arm_id': 'unload_b',
                                     'delivery_pose': {'x': .7, 'y': -2., 'yaw': math.pi/2},
                                     'shelf_xy_in_station_m': [.05, -.22],
                                     'shelf_floor_geom': 'unload_b__pick_floor'}}}}
    yaw90 = [math.sqrt(.5), 0., 0., math.sqrt(.5)]
    raw = {'stamp': 3., 'car_hold': True, 'qpos': ['opaque, unrelated common-world snapshot'],
           'car': {'speed': 0., 'yaw_rate': 0., 'position': [1., 2., 3.]},
           'tray': {'position': [1., 2., 3.], 'quaternion_wxyz': yaw90,
                    'rotation_world': [[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]],
                    'velocity_world_angular_linear': [0., 0., 2., 1., 2., 3.]},
           'business_entities': {'arms': {
               'load': {'qpos6': [0.]*6, 'qvel6': [0.]*6},
               'unload_b': {'qpos6': [.1, .2, .3, .4, .5, .6], 'qvel6': [.001]*6}},
               'cargo': {
                   'cargo_1': {'position': [0., 0., 0.], 'quaternion_wxyz': [1., 0., 0., 0.],
                               'velocity_world_angular_linear': [0.]*6,
                               'contacts': {'supports': {}, 'pads': {}, 'other_cargo': {}}},
                   'cargo_2': {'position': [2., 4., 3.], 'quaternion_wxyz': yaw90,
                               'velocity_world_angular_linear': [.7, .8, .9, 4., 8., 9.],
                               'contacts': {'supports': {'tray': {'contact_count': 4, 'normal_force_n': .0981}},
                                            'pads': {'unload_b': {
                                                'unload_b__pad_gripper': {'contact_count': 1, 'normal_force_n': 1.2},
                                                'unload_b__pad_moving_jaw': {'contact_count': 2, 'normal_force_n': 1.3}},
                                                'load': {'pad_gripper': {'contact_count': 1, 'normal_force_n': .4}}},
                                            'other_cargo': {}}}}}}
    binding = {'cargo_id': 'cargo_2', 'pickup_arm_id': 'load', 'unload_station_id': 'line_b'}
    return manifest, raw, binding


class BusinessObservationTests(unittest.TestCase):
    def test_binding_has_exact_named_fields_and_goal_is_the_configured_station(self):
        manifest, _, binding = fixture()
        manifest['business_entities']['unload_stations']['line_b']['cargo_shelf_slots'] = {
            'cargo_1': {'center_xy_m':[.02,-.22], 'half_size_xy_m':[.028,.058]},
            'cargo_2': {'center_xy_m':[.08,-.22], 'half_size_xy_m':[.028,.058]}}
        normalized = normalize_delivery(binding)
        self.assertEqual(normalized, binding)
        self.assertIsNot(normalized, binding)
        pose = {'x': .7, 'y': -2., 'yaw': math.pi/2+2*math.pi}
        self.assertEqual(validate_delivery(manifest, binding, pose), dict(binding, unload_arm_id='unload_b'))
        for bad in (None, {}, dict(binding, extra=True), dict(binding, cargo_id='  '),
                    dict(binding, pickup_arm_id=True)):
            with self.subTest(bad=bad), self.assertRaises(Rejected):
                normalize_delivery(bad)
        for key in binding:
            with self.subTest(key=key), self.assertRaises(Rejected):
                validate_delivery(manifest, dict(binding, **{key: 'missing'}), pose)
        for wrong in ({'x': .701, 'y': -2., 'yaw': math.pi/2},
                      {'x': .7, 'y': -2., 'yaw': 0.}, {'x': .7, 'y': -2., 'yaw': float('nan')}):
            with self.subTest(wrong=wrong), self.assertRaises(Rejected):
                validate_delivery(manifest, binding, wrong)

    def test_continuous_order_without_a_distinct_physical_cell_is_rejected(self):
        manifest, _, binding = fixture()
        with self.assertRaisesRegex(Rejected,'distinct configured shelf cells'):
            validate_delivery(manifest,binding,{'x':.7,'y':-2.,'yaw':math.pi/2})

    def test_named_projection_rotates_position_and_subtracts_angular_tray_velocity(self):
        manifest, raw, _ = fixture()
        before = copy.deepcopy(raw)
        view = observe(raw, manifest, 'cargo_2', 'unload_b')
        self.assertEqual(view['q6'], [.1, .2, .3, .4, .5, .6])
        self.assertEqual(view['qvel6'], [.001]*6)
        for actual, expected in zip(view['cargo']['position_relative_tray'], [2., -1., 0.]):
            self.assertAlmostEqual(actual, expected)
        # omega x offset=(-4,2,0); v_c-v_tray-omega x offset=(7,4,6).
        for actual, expected in zip(view['cargo']['velocity_relative_tray'], [4., -7., 6.]):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(view['finger_normal_forces_n'], {'pad_gripper': 1.2, 'pad_moving_jaw': 1.3})
        self.assertTrue(view['cargo_tray_floor_contact'])
        self.assertEqual(view['cargo_tray_floor_contacts'], 4)
        self.assertEqual(view['cargo_tray_floor_normal_force_n'], .0981)
        self.assertNotIn('qpos', view)
        self.assertEqual(raw, before)
        view['cargo']['position'][0] = 99
        view['entity_contacts']['pads'].clear()
        view['tray']['position'][0] = 99
        self.assertEqual(raw, before)

    def test_missing_contacts_mean_no_contact_but_missing_measurement_is_rejected(self):
        manifest, raw, _ = fixture()
        raw['business_entities']['cargo']['cargo_2']['contacts'] = {'supports': {}, 'pads': {}, 'other_cargo': {}}
        view = observe(raw, manifest, 'cargo_2', 'unload_b')
        self.assertEqual(view['finger_normal_forces_n'], {'pad_gripper': 0., 'pad_moving_jaw': 0.})
        self.assertFalse(view['cargo_tray_floor_contact'])
        cases = []
        malformed = copy.deepcopy(raw);malformed['business_entities']['arms'].pop('unload_b');cases.append(malformed)
        malformed = copy.deepcopy(raw);malformed['business_entities']['cargo']['cargo_2']['position'] = [0., 0.];cases.append(malformed)
        malformed = copy.deepcopy(raw);malformed['business_entities']['cargo']['cargo_2']['quaternion_wxyz'] = [2., 0., 0., 0.];cases.append(malformed)
        malformed = copy.deepcopy(raw);malformed['business_entities']['cargo']['cargo_2']['contacts']['supports'] = [];cases.append(malformed)
        malformed = copy.deepcopy(raw);malformed['tray']['velocity_world_angular_linear'][0] = float('nan');cases.append(malformed)
        for item in cases:
            with self.subTest(item=item), self.assertRaises(ValueError):
                observe(item, manifest, 'cargo_2', 'unload_b')
        with self.assertRaises(ValueError):
            observe(raw, manifest, 'missing', 'unload_b')

    def shelf_view(self):
        manifest, raw, _ = fixture()
        cargo = raw['business_entities']['cargo']['cargo_2']
        cargo.update(position=[10.22, 20.05, 1.008], velocity_world_angular_linear=[0.]*6)
        cargo['contacts'] = {'supports': {'line_b': {'contact_count': 4, 'normal_force_n': .0981}},
                             'pads': {}, 'other_cargo': {}}
        return manifest, observe(raw, manifest, 'cargo_2', 'unload_b')

    def test_shelf_uses_station_yaw_and_full_rotated_box_footprint(self):
        manifest, view = self.shelf_view()
        self.assertTrue(shelf_settled(view, manifest, 'line_b'))

        # Along station local x (world +y), an aligned box fits at 48mm.
        view['cargo']['position'][1] += .048
        self.assertTrue(shelf_settled(view, manifest, 'line_b'))
        # Rotate the box 45 degrees relative to the shelf: its center fits,
        # but the full .009/.009 rotated footprint crosses the 58mm boundary.
        view['cargo']['quaternion_wxyz'] = [math.cos(3*math.pi/8), 0., 0., math.sin(3*math.pi/8)]
        self.assertFalse(shelf_settled(view, manifest, 'line_b'))
        view['cargo']['position'][1] -= .004
        self.assertTrue(shelf_settled(view, manifest, 'line_b'))
        # A tilted box also projects its original 8mm height into the footprint.
        view['cargo']['position'][1] = 20.05+.047
        view['cargo']['quaternion_wxyz'] = [.8535533905932737, .3535533905932738,
                                            .3535533905932738, .1464466094067262]
        self.assertFalse(shelf_settled(view, manifest, 'line_b'))

    def test_release_before_retreat_exempts_only_the_selected_fixed_pad(self):
        manifest, view = self.shelf_view()
        view['entity_contacts']['pads'] = {'unload_b': {
            'unload_b__pad_gripper': {'contact_count': 1, 'normal_force_n': .3}}}
        self.assertFalse(shelf_settled(view, manifest, 'line_b'))
        self.assertTrue(shelf_settled(view, manifest, 'line_b', before_retreat=True))
        view['entity_contacts']['pads']['load'] = {'pad_gripper': {'contact_count': 1,'normal_force_n': .3}}
        self.assertFalse(shelf_settled(view, manifest, 'line_b', before_retreat=True))

    def test_shelf_requires_correct_support_all_arms_released_and_world_rest(self):
        manifest, baseline = self.shelf_view()
        for mutation in ('wrong_support', 'zero_force', 'other_arm_pad', 'moving_world', 'nan_velocity'):
            view = copy.deepcopy(baseline)
            if mutation == 'wrong_support':
                view['entity_contacts']['supports'] = {'tray': {'contact_count': 4, 'normal_force_n': .1}}
            elif mutation == 'zero_force':view['entity_contacts']['supports']['line_b']['normal_force_n'] = 0.
            elif mutation == 'other_arm_pad':
                view['entity_contacts']['pads']['load'] = {'pad_gripper': {'contact_count': 1, 'normal_force_n': .02}}
            elif mutation == 'moving_world':view['cargo']['velocity_world_angular_linear'][3] = .002
            else:view['cargo']['velocity_world_angular_linear'][3] = float('nan')
            with self.subTest(mutation=mutation):self.assertFalse(shelf_settled(view, manifest, 'line_b'))

    def test_assigned_slot_rejects_the_other_cargos_shelf_cell(self):
        manifest, view = self.shelf_view()
        station = manifest['business_entities']['unload_stations']['line_b']
        station['cargo_shelf_slots'] = {
            'cargo_1': {'center_xy_m': [.02,-.22], 'half_size_xy_m': [.028,.058]},
            'cargo_2': {'center_xy_m': [.08,-.22], 'half_size_xy_m': [.028,.058]}}
        # Same shelf support is insufficient: this cargo must fit its own cell.
        self.assertFalse(shelf_settled(view,manifest,'line_b'))
        view['cargo']['position'][1] = 20.08
        self.assertTrue(shelf_settled(view,manifest,'line_b'))
        view['cargo']['position'][1] = 20.02
        self.assertFalse(shelf_settled(view,manifest,'line_b'))
        station['cargo_shelf_slots']['cargo_2']['center_xy_m'] = [.10,-.22]
        with self.assertRaises(ValueError):placement_slot(manifest,'line_b','cargo_2')

    def test_all_quiet_checks_secondary_arms_cargo_and_vector_norm(self):
        _, raw, _ = fixture()
        for cargo in raw['business_entities']['cargo'].values():cargo['velocity_world_angular_linear'] = [0.]*6
        self.assertTrue(all_quiet(raw))
        self.assertTrue(all_quiet({}))
        raw['business_entities']['arms']['unload_b']['qvel6'] = [.03]*6
        self.assertFalse(all_quiet(raw))
        raw['business_entities']['arms']['unload_b']['qvel6'] = [0.]*6
        raw['business_entities']['cargo']['cargo_2']['velocity_world_angular_linear'] = [100., 0., 0., 0., .03, 0.]
        self.assertFalse(all_quiet(raw))
        raw['business_entities']['cargo']['cargo_2']['velocity_world_angular_linear'] = [100., 0., 0., 0., 0., 0.]
        self.assertTrue(all_quiet(raw))
        raw['business_entities']['cargo']['cargo_2']['velocity_world_angular_linear'][3] = float('nan')
        self.assertFalse(all_quiet(raw))
        self.assertFalse(all_quiet({'business_entities': None}))


class BusinessInventoryTests(unittest.TestCase):
    def test_reserve_advance_are_idempotent_and_do_not_restore_delivered_stock(self):
        manifest, _, binding = fixture()
        inventory = new_inventory(manifest, 'world-1', 'episode-1')
        self.assertEqual(inventory['world_id'], 'world-1')
        record = reserve(inventory, binding, 'task-1')
        self.assertEqual(record['state'], 'reserved')
        self.assertEqual(reserve(inventory, binding, 'task-1'), record)
        record['state'] = 'delivered'
        self.assertEqual(inventory['cargo']['cargo_2']['state'], 'reserved')
        evidence = {'stamp': 3.}
        self.assertEqual(advance(inventory, 'cargo_2', 'task-1', 'on_tray', evidence)['state'], 'on_tray')
        evidence['stamp'] = 99
        self.assertEqual(inventory['cargo']['cargo_2']['evidence'], {'stamp': 3.})
        delivered = advance(inventory, 'cargo_2', 'task-1', 'delivered', {'stamp': 4.})
        self.assertEqual(advance(inventory, 'cargo_2', 'task-1', 'delivered', {'stamp': 5.}), delivered)
        before = copy.deepcopy(inventory)
        for task in ('task-1', 'task-2'):
            with self.subTest(task=task), self.assertRaises(Rejected):reserve(inventory, binding, task)
        for state in ('reserved', 'on_tray', 'available', 'unknown', 'failure'):
            with self.subTest(state=state), self.assertRaises(Rejected):
                advance(inventory, 'cargo_2', 'task-1', state)
        self.assertEqual(inventory, before)
        self.assertEqual(reserve(inventory, dict(binding, cargo_id='cargo_1'), 'task-2')['state'], 'reserved')

    def test_wrong_owner_unknown_cargo_and_skipped_transition_leave_stock_unchanged(self):
        manifest, _, binding = fixture()
        inventory = new_inventory(manifest, 'world-1', 'episode-1')
        reserve(inventory, binding, 'task-1')
        before = copy.deepcopy(inventory)
        actions = [lambda: reserve(inventory, binding, 'task-2'),
                   lambda: reserve(inventory, dict(binding, cargo_id='cargo_1'), 'task-1'),
                   lambda: reserve(inventory, dict(binding, cargo_id='missing'), 'task-2'),
                   lambda: advance(inventory, 'missing', 'task-1', 'on_tray'),
                   lambda: advance(inventory, 'cargo_2', 'task-2', 'on_tray'),
                   lambda: advance(inventory, 'cargo_2', 'task-1', 'delivered'),
                   lambda: advance(inventory, 'cargo_1', 'task-1', 'on_tray'),
                   lambda: advance(inventory, 'cargo_2', 'task-1', 'failure')]
        for action in actions:
            with self.assertRaises(Rejected):action()
            self.assertEqual(inventory, before)

    def test_resolved_binding_is_supported_and_physical_aliases_are_rejected(self):
        manifest, _, binding = fixture()
        manifest['business_entities']['unload_stations']['line_b']['cargo_shelf_slots'] = {
            'cargo_1': {'center_xy_m':[.02,-.22], 'half_size_xy_m':[.028,.058]},
            'cargo_2': {'center_xy_m':[.08,-.22], 'half_size_xy_m':[.028,.058]}}
        inventory = new_inventory(manifest, 'world-1', 'episode-1')
        resolved = validate_delivery(manifest, binding, {'x': .7, 'y': -2., 'yaw': math.pi/2})
        self.assertEqual(reserve(inventory, resolved, 'task-1')['binding'], resolved)
        manifest['business_entities']['cargo']['cargo_2']['free_joint'] = 'free_1'
        with self.assertRaises(Rejected):new_inventory(manifest, 'world-2', 'episode-2')

    def test_failed_owned_cargo_becomes_unknown_and_never_reenters_stock(self):
        manifest, _, binding = fixture()
        for origin in ('reserved', 'on_tray'):
            with self.subTest(origin=origin):
                inventory = new_inventory(manifest, 'world-1', 'episode-1')
                reserve(inventory, binding, 'task-1')
                if origin == 'on_tray':advance(inventory, 'cargo_2', 'task-1', 'on_tray')
                before = copy.deepcopy(inventory)
                with self.assertRaises(Rejected):advance(inventory, 'cargo_2', 'task-2', 'unknown')
                self.assertEqual(inventory, before)
                record = advance(inventory, 'cargo_2', 'task-1', 'unknown', {'reason': 'partial task'})
                self.assertEqual(record['state'], 'unknown')
                self.assertEqual(advance(inventory, 'cargo_2', 'task-1', 'unknown'), record)
                before = copy.deepcopy(inventory)
                for state in ('available', 'reserved', 'on_tray', 'delivered'):
                    with self.subTest(state=state), self.assertRaises(Rejected):
                        advance(inventory, 'cargo_2', 'task-1', state)
                for task in ('task-1', 'task-2'):
                    with self.subTest(task=task), self.assertRaises(Rejected):reserve(inventory, binding, task)
                self.assertEqual(inventory, before)


if __name__ == '__main__':
    unittest.main()
