"""Probe regression checks use no ROS context or physics integration."""
import collections
import contextlib
import copy
import io
import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml
from PIL import Image

import cooperation_staging_probe as probe
from fishbot_scene_validation import NavigationDiagnostics


def parameters():
    return {
        'controller_server': {'ros__parameters': {}},
        'local_costmap': {'local_costmap': {'ros__parameters': {
            'inflation_layer': {'inflation_radius': .3}}}},
        'global_costmap': {'global_costmap': {'ros__parameters': {
            'inflation_layer': {'inflation_radius': .45}}}},
    }


def map_file(directory, *, negate=0, origin=None):
    image = Image.new('L', (32, 32), 0 if negate else 255)
    image.putpixel((0, 31), 255 if negate else 0)
    image.save(directory / 'map.pgm')
    path = directory / 'map.yaml'
    path.write_text(yaml.safe_dump({'image': 'map.pgm', 'mode': 'trinary',
        'resolution': .05, 'origin': origin or [-.025, -.025, 0.],
        'negate': negate, 'occupied_thresh': .65, 'free_thresh': .25}))
    return path


class GeometryFixture:
    def __init__(self, manifest):
        self.manifest = manifest
        self.base_height = .002

    def check_pose(self, pose):
        return {'passed': True, 'delivery_pose': dict(pose),
            'minimum_sampled_clearance_m': .20,
            'witness': None,
            'scene_bounds': [{'footprint_clearance_m': 2.}]}


class StaticProbeTests(unittest.TestCase):
    def test_aligned_fixture_changes_only_heading_and_preserves_default_fixture(self):
        spawn = {'x': 0., 'y': -2., 'yaw': 0., 'z': .002}
        fixed = probe.probe_goals(spawn, .25, 'fixed')
        aligned = probe.probe_goals(spawn, .25, 'aligned')
        self.assertEqual([goal['yaw'] for goal in fixed], [0., math.pi/2])
        self.assertEqual([goal['yaw'] for goal in aligned], [math.pi, math.pi])
        for a, b in zip(fixed, aligned):
            self.assertEqual({key: a[key] for key in ('x', 'y', 'z')},
                             {key: b[key] for key in ('x', 'y', 'z')})
        self.assertEqual(spawn, {'x': 0., 'y': -2., 'yaw': 0., 'z': .002})

    def test_nested_costmaps_and_relative_image_use_stricter_fixture_margin(self):
        config = parameters()
        before = copy.deepcopy(config)
        with tempfile.TemporaryDirectory() as temp:
            checks = probe.isolation_clearance(config, map_file(Path(temp)),
                {'far': {'x': .8, 'y': 0.}, 'soft': {'x': .29, 'y': 0.}})
        self.assertTrue(checks['far']['fixture_clearance_passed'])
        self.assertFalse(checks['soft']['fixture_clearance_passed'])
        self.assertIsNone(checks['soft']['native_collision_verdict'])
        self.assertAlmostEqual(checks['far']['fixture_clearance_required_m'], .47)
        self.assertEqual(config, before)

    def test_rotated_map_origin_and_negate_preserve_world_coordinates(self):
        with tempfile.TemporaryDirectory() as temp:
            path = map_file(Path(temp), negate=1, origin=[2., 3., math.pi/2])
            # Occupied cell (0, 0) transforms from local (.025,.025).
            checks = probe.isolation_clearance(parameters(), path,
                {'goal': {'x': 1.975, 'y': 3.825}})
        self.assertAlmostEqual(checks['goal']['nearest_occupied_cell_center_m'], .8)
        self.assertTrue(checks['goal']['fixture_clearance_passed'])

    def test_endpoint_clearance_cannot_hide_an_intermediate_collision(self):
        query = GeometryFixture({'car_footprint_xy': [[.13, 0.], [0., .13]]})
        original = query.check_pose

        def collision(pose):
            result = original(pose)
            if -.14 < pose['x'] < -.11:
                result['minimum_sampled_clearance_m'] = -.01
            return result

        query.check_pose = collision
        result = probe.declared_sweep(query,
            [{'x': 0., 'y': 0., 'yaw': 0.}, {'x': -.25, 'y': 0., 'yaw': 0.}])
        self.assertFalse(result['passed'])
        self.assertLess(result['certified_margin_m'], 0.)
        self.assertEqual(result['physics_steps'], 0)

    def test_default_entry_cannot_launch_ros(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            map_path = map_file(root)
            config = root / 'nav2.yaml'
            config.write_text(yaml.safe_dump(parameters()))
            manifest = root / 'scene-manifest.json'
            manifest.write_text(json.dumps({'nav2_yaml': str(config),
                'collision_map_yaml': str(map_path), 'spawn': [-1., 0.],
                'car_footprint_xy': [[.13, 0.], [0., .13]]}))
            with patch.object(probe, 'SceneGeometry', GeometryFixture), \
                 patch.object(probe.subprocess, 'check_output', return_value='test-source'), \
                 patch.object(probe.subprocess, 'Popen') as launch, \
                 patch.object(probe, 'domain_is_empty') as domain, \
                 contextlib.redirect_stdout(io.StringIO()):
                result = probe.main(['--manifest', str(manifest), '--output', str(root/'out')])
            launch.assert_not_called()
            domain.assert_not_called()
            report = json.loads((root/'out/preflight.json').read_text())
        self.assertEqual(result, 0)
        self.assertTrue(report['preflight_passed'])
        self.assertFalse(report['ros_initialized'])
        self.assertFalse(report['passed'])
        self.assertEqual(report['goals'], [])
        self.assertAlmostEqual(report['planned_goals']['staging']['x'], -1.25)
        self.assertAlmostEqual(report['planned_goals']['default']['x'], -1.5)


def physical_frame():
    return {'stamp': 12., 'car_hold': True,
        'car': {'position': [.25, 0., 0.], 'quaternion_wxyz': [1., 0., 0., 0.],
            'speed': 0., 'yaw_rate': 0.}, 'qvel6': [0.] * 6,
        'source': {'episode_id': 'episode-a', 'manifest': {'payload': 'x' * 100000}}}


class EvidenceProbeTests(unittest.TestCase):
    def witness_report(self):
        return {'plan_publishers': [{'node': 'controller_server', 'gid': 'aa'},
                                   {'node': 'controller_server', 'gid': 'bb'}],
            'goals': [{'phase': phase, 'accepted_monotonic': start,
                'evidence_end_monotonic': start+1., 'control_loop_observed': True,
                'requested_behavior_tree': phase+'.xml'}
                for phase, start in (('staging', 10.), ('default', 20.))]}

    def attach(self, report, events):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'native.jsonl'
            path.write_text(''.join(json.dumps(event)+'\n' for event in events))
            probe.attach_native_witness(report, path)

    def test_native_receipts_bind_only_inside_accepted_goal_windows(self):
        report = self.witness_report()
        self.attach(report, [
            {'kind': 'plan', 'receive_monotonic': 9., 'publisher_gid': 'foreign'},
            {'kind': 'plan', 'receive_monotonic': 10.5, 'publisher_gid': 'aa'},
            {'kind': 'plan', 'receive_monotonic': 20.5, 'publisher_gid': 'bb'},
            {'kind': 'plan', 'receive_monotonic': 21.5, 'publisher_gid': 'foreign'}])
        self.assertTrue(report['phase_rpp_activity_switch_observed'])
        self.assertEqual([g['native_plan_witness']['plan_count'] for g in report['goals']], [1, 1])
        self.assertEqual([g['controller_instance_binding']['publisher_gid']
                          for g in report['goals']], ['aa', 'bb'])

    def test_shared_foreign_or_overflow_receipts_cannot_prove_switch(self):
        for second_gid, overflow in (('aa', False), ('foreign', False), ('bb', True)):
            report = self.witness_report()
            events = [{'kind': 'plan', 'receive_monotonic': 10.5, 'publisher_gid': 'aa'},
                      {'kind': 'plan', 'receive_monotonic': 20.5, 'publisher_gid': second_gid}]
            if overflow:
                events.append({'kind': 'overflow'})
            self.attach(report, events)
            self.assertFalse(report['phase_rpp_activity_switch_observed'])
            self.assertFalse(report['goals'][1].get('controller_instance_binding')
                             if second_gid == 'foreign' or overflow else False)

    def node(self):
        node = SimpleNamespace(phase='default', raw=physical_frame())
        node.gids = collections.defaultdict(set)
        node.plan_messages = collections.defaultdict(lambda: collections.deque(maxlen=2))
        node.commands = collections.defaultdict(lambda: collections.deque(maxlen=2))
        node.counts = collections.defaultdict(collections.Counter)
        node.navigation = collections.defaultdict(NavigationDiagnostics)
        node.phase_samples = collections.defaultdict(list)
        node.amcl_samples = collections.defaultdict(list)
        node.transforms = collections.defaultdict(list)
        return node

    def test_timeout_preserves_observed_phase_without_fabricating_terminal(self):
        node = self.node()
        node.gids['default'].add('unavailable:NoneType')
        for index in range(5):
            node.plan_messages['default'].append({'stamp': index})
            node.commands['default'].append({'linear_x': .03})
        node.counts['default'].update(plans=5, commands=5, nonzero_commands=5)
        entry = {'phase': 'default', 'uuid': 'accepted-goal',
            'start_truth_pose': {'x': 0., 'y': 0., 'yaw': 0.}}
        saved = []

        def never_completes():
            raise TimeoutError('wall budget exceeded')

        with self.assertRaises(TimeoutError):
            probe.record_phase_wait(node, entry, {'x': .25, 'y': 0., 'yaw': 0.},
                never_completes, lambda: saved.append(copy.deepcopy(entry)))
        self.assertEqual(saved, [entry])
        self.assertEqual(entry['observed_message_counts']['plans'], 5)
        self.assertEqual(len(entry['received_global_plans']), 2)
        self.assertEqual(len(entry['controller_commands']), 2)
        self.assertTrue(entry['control_loop_observed'])
        self.assertIsNone(entry['controller_instance_binding'])
        self.assertNotIn('status', entry)
        self.assertNotIn('terminal', entry)

    def test_zero_commands_cannot_claim_control_loop(self):
        node = self.node()
        node.counts['default'].update(plans=1, commands=1, nonzero_commands=0)
        entry = {'phase': 'default', 'start_truth_pose': {'x': 0., 'y': 0., 'yaw': 0.}}
        probe.phase_snapshot(node, entry, {'x': .25, 'y': 0., 'yaw': 0.})
        self.assertFalse(entry['control_loop_observed'])

    def test_snapshot_does_not_overwrite_a_previous_phase_with_current_truth(self):
        node = self.node()
        entry = {'phase': 'staging', 'start_truth_pose': {'x': 0., 'y': 0., 'yaw': 0.},
            'truth_goal_error': {'xy_m': .094, 'yaw_rad': .033}}
        probe.phase_snapshot(node, entry, {'x': .25, 'y': 0., 'yaw': 0.})
        self.assertEqual(entry['truth_goal_error'], {'xy_m': .094, 'yaw_rad': .033})

    def test_per_frame_identity_omits_repeated_manifest(self):
        raw = physical_frame()
        sample = probe.compact_physics_sample(raw, 50.)
        self.assertEqual(sample['episode_id'], 'episode-a')
        self.assertNotIn('source', sample)
        self.assertNotIn('manifest', sample)
        self.assertLess(len(json.dumps(sample)), 600)
        self.assertIn('manifest', raw['source'])

    def test_bounded_tail_cannot_hide_an_earlier_contact_or_missing_contact_data(self):
        node = self.node()
        node.counts['default'].update(physics=4001, unsafe_or_missing_contact_samples=1)
        entry = {'phase': 'default', 'start_truth_pose': {'x': 0., 'y': 0., 'yaw': 0.}}
        probe.phase_snapshot(node, entry, {'x': .25, 'y': 0., 'yaw': 0.})
        self.assertFalse(entry['no_forbidden_contacts_observed'])
        node.counts['default']['unsafe_or_missing_contact_samples'] = 0
        probe.phase_snapshot(node, entry, {'x': .25, 'y': 0., 'yaw': 0.})
        self.assertTrue(entry['no_forbidden_contacts_observed'])

    def test_source_and_wall_budgets_use_their_own_clocks(self):
        self.assertIsNone(probe.phase_budget_reason(10., 70., 100., 170., 60., 70.))
        self.assertEqual(probe.phase_budget_reason(10., 70.01, 100., 110., 60., 70.),
            'source budget exceeded')
        self.assertEqual(probe.phase_budget_reason(10., 10., 100., 170.01, 60., 70.),
            'wall budget exceeded')
        self.assertEqual(probe.phase_budget_reason(10., 9., 100., 101., 60., 70.),
            'source clock moved backwards')


if __name__ == '__main__':
    unittest.main()
