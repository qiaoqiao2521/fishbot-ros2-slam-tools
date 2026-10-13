"""Geometry and persistence acceptance; no ROS or physical effects in this suite."""
import copy
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from map_rules import (MapRulesError, MapRulesStore, build_mask, costmap_matches_mask,
                       grid_value_at, map_identity, require_outside_rules, validate_zones)


def grid():
    return {'width': 80, 'height': 80, 'resolution': .05,
            'origin': [-2., -2., 0.], 'data': [0]*6400}


def wall():
    return {'id': 'wall_1', 'kind': 'wall', 'width': .02,
            'points': [{'x': -.5, 'y': 0.}, {'x': .5, 'y': 0.}]}


def rectangle():
    return {'id': 'room_1', 'kind': 'no_go', 'points': [
        {'x': 0., 'y': 0.}, {'x': .5, 'y': 0.}, {'x': .5, 'y': .5}, {'x': 0., 'y': .5}]}


class GeometryTests(unittest.TestCase):
    def test_map_identity_binds_content_and_geometry(self):
        initial = grid()
        equivalent = copy.deepcopy(initial)
        self.assertEqual(map_identity(initial), map_identity(equivalent))
        for mutate in (lambda g: g['data'].__setitem__(0, -1),
                       lambda g: g['origin'].__setitem__(2, .1),
                       lambda g: g.__setitem__('resolution', .06)):
            altered = copy.deepcopy(initial)
            mutate(altered)
            self.assertNotEqual(map_identity(initial), map_identity(altered))

    def test_rectangle_normalizes_unordered_corners(self):
        shuffled = rectangle()
        shuffled['points'] = shuffled['points'][::2]+shuffled['points'][1::2]
        self.assertEqual(validate_zones([shuffled], grid()), [rectangle()])

    def test_bad_shapes_types_duplicate_ids_and_nonfinite_coordinates_rejected(self):
        cases = []
        for value in (math.nan, math.inf, -math.inf, True, '0'):
            item = wall()
            item['points'][0]['x'] = value
            cases.append([item])
        cases.extend([[wall(), wall()], [{**wall(), 'kind': 'mop_forbid'}],
                      [{**wall(), 'width': 0.}], [{**wall(), 'width': 2.}],
                      [{**wall(), 'id': '../../path'}], [{**wall(), 'extra': True}],
                      [{**rectangle(), 'width': .1}], [{**rectangle(), 'points': rectangle()['points'][:3]}]])
        for points in ([{'x': 0., 'y': 0.}]*4,
                       [{'x': 0., 'y': 0.}, {'x': .5, 'y': .1}, {'x': .5, 'y': .5}, {'x': 0., 'y': .5}]):
            cases.append([{**rectangle(), 'points': points}])
        for case in cases:
            with self.subTest(case=case), self.assertRaises(MapRulesError):
                validate_zones(case, grid())

    def test_out_of_map_points_and_zero_wall_rejected(self):
        for item in ({**wall(), 'points': [{'x': 2.01, 'y': 0.}, {'x': 0., 'y': 0.}]},
                     {**wall(), 'points': [{'x': 0., 'y': 0.}]*2}):
            with self.assertRaises(MapRulesError):
                validate_zones([item], grid())

    def test_rotated_map_validation_and_axis_aligned_mask(self):
        rotated = grid()
        rotated['origin'] = [2., -2., math.pi/2]
        zones = validate_zones([rectangle()], rotated)
        mask = build_mask(rotated, zones)
        self.assertEqual(mask['origin'][2], 0.)
        self.assertEqual(grid_value_at(.25, .25, mask), 100)
        self.assertEqual(grid_value_at(-1., -1., mask), 0)
        rotated['origin'] = [0., 0., math.pi/4]
        with self.assertRaises(MapRulesError):
            validate_zones([wall()], rotated)

    def test_diagonal_origin_mask_covers_world_rectangle(self):
        rotated = grid()
        rotated['origin'] = [0., -2., math.pi/4]
        zones = validate_zones([rectangle()], rotated)
        mask = build_mask(rotated, zones)
        self.assertEqual(grid_value_at(.25, .25, mask), 100)
        self.assertGreater(mask['width'], rotated['width'])
        self.assertEqual(mask['origin'][2], 0.)

    def test_footprint_including_rectangle_corner_rejected(self):
        zones = validate_zones([rectangle()], grid())
        for point in ({'x': -.1, 'y': .2}, {'x': -.08, 'y': -.08}, {'x': .25, 'y': .25}):
            with self.assertRaises(MapRulesError):
                require_outside_rules(point, zones)
        require_outside_rules({'x': -.2, 'y': -.2}, zones)

    def test_wall_caps_and_width_reject_footprint_not_only_center(self):
        zones = validate_zones([wall()], grid())
        for point in ({'x': 0., 'y': .13}, {'x': .62, 'y': 0.}):
            with self.assertRaises(MapRulesError):
                require_outside_rules(point, zones)
        require_outside_rules({'x': 0., 'y': .3}, zones)

    def test_wall_diagnostic_measures_rule_edge_and_snapshot_index(self):
        far = {**wall(), 'id': 'far', 'points': [{'x': -1., 'y': -1.}, {'x': 1., 'y': -1.}]}
        point = {'x': 0., 'y': .1, 'yaw': .4}
        with self.assertRaises(MapRulesError) as caught:
            require_outside_rules(point, [far, wall()])
        issue = caught.exception.issue
        self.assertEqual(str(caught.exception), 'Waypoint footprint intersects map rule wall_1')
        self.assertEqual(issue['kind'], 'map_rule')
        self.assertEqual((issue['rule_id'], issue['rule_kind'], issue['rule_index']),
                         ('wall_1', 'wall', 2))
        self.assertEqual(issue['point'], point)
        self.assertAlmostEqual(issue['clearance_m'], .09)
        self.assertAlmostEqual(issue['required_clearance_m'], .13)
        self.assertAlmostEqual(issue['shortfall_m'], .04)
        self.assertEqual(issue['blocking_point'], {'x': 0., 'y': .01})

    def test_wall_cap_diagnostic_nearest_point_includes_half_width(self):
        with self.assertRaises(MapRulesError) as caught:
            require_outside_rules({'x': .62, 'y': 0.}, [wall()])
        issue = caught.exception.issue
        self.assertAlmostEqual(issue['clearance_m'], .11)
        self.assertEqual(issue['blocking_point'], {'x': .51, 'y': 0.})

    def test_rectangle_corner_diagnostic_uses_exact_existing_distance(self):
        with self.assertRaises(MapRulesError) as caught:
            require_outside_rules({'x': .55, 'y': .55}, [rectangle()])
        issue = caught.exception.issue
        self.assertAlmostEqual(issue['clearance_m'], math.sqrt(2)*.05)
        self.assertEqual(issue['blocking_point'], {'x': .5, 'y': .5})
        self.assertEqual(issue['rule_kind'], 'no_go')

    def test_diagnostic_inside_rule_retains_zero_clearance(self):
        for point, zone in (({'x': .2, 'y': .2}, rectangle()), ({'x': .2, 'y': .005}, wall())):
            with self.subTest(zone=zone['kind']), self.assertRaises(MapRulesError) as caught:
                require_outside_rules(point, [zone])
            self.assertEqual(caught.exception.issue['clearance_m'], 0.)
            self.assertEqual(caught.exception.issue['blocking_point'], point)
            self.assertEqual(caught.exception.issue['shortfall_m'], .13)

    def test_mask_is_software_only_and_conservative(self):
        original = grid()
        snapshot = copy.deepcopy(original)
        mask = build_mask(original, validate_zones([wall()], original))
        self.assertEqual(original, snapshot)
        self.assertEqual(set(mask['data']), {0, 100})
        self.assertEqual(grid_value_at(0., .025, mask), 100)
        # Rasterize wall geometry once. Nav2 retains responsibility for its
        # physical outline; API goal validation independently checks that outline.
        self.assertEqual(grid_value_at(0., .13, mask), 0)
        with self.assertRaises(MapRulesError):
            require_outside_rules({'x': 0., 'y': .13}, [wall()])
        self.assertEqual(grid_value_at(0., .3, mask), 0)

    def test_readback_requires_lethal_not_unknown_or_inscribed(self):
        mask = build_mask(grid(), [rectangle()])
        costmap = copy.deepcopy(mask)
        costmap['data'] = [254 if value else 0 for value in mask['data']]
        self.assertTrue(costmap_matches_mask(costmap, mask)[0])
        marked = mask['data'].index(100)
        for value in (0, 253, 255):
            costmap['data'][marked] = value
            self.assertFalse(costmap_matches_mask(costmap, mask)[0])

    def test_deleted_rule_must_clear_on_free_source_cells(self):
        source = grid()
        previous = build_mask(source, [rectangle()])
        cleared = build_mask(source, [])
        stale = copy.deepcopy(previous)
        stale['data'] = [254 if v else 0 for v in previous['data']]
        self.assertFalse(costmap_matches_mask(stale, cleared, previous, source)[0])
        stale['data'] = [0]*len(stale['data'])
        ok, _marked, removed = costmap_matches_mask(stale, cleared, previous, source)
        self.assertTrue(ok)
        self.assertGreater(removed, 0)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = MapRulesStore(self.temporary.name)
        self.store.bind(grid())

    def request(self, zones=None):
        return {'map_id': self.store.map_id, 'base_revision': self.store.document['revision'],
                'zones': [wall()] if zones is None else zones}

    def test_rules_atomic_roundtrip_and_revision_conflict(self):
        request = self.request()
        response = self.store.update_rules(request)
        self.assertEqual(response['revision'], 1)
        with self.assertRaises(MapRulesError) as caught:
            self.store.update_rules(request)
        self.assertEqual(caught.exception.status, 409)
        other = MapRulesStore(self.temporary.name)
        other.bind(grid())
        self.assertEqual(other.rules(), response)
        self.assertEqual(self.store.filename.stat().st_mode & 0o777, 0o600)

    def test_cas_checks_disk_not_stale_instance_memory(self):
        other = MapRulesStore(self.temporary.name)
        other.bind(grid())
        self.store.update_rules(self.request())
        with self.assertRaises(MapRulesError) as caught:
            other.update_rules({'map_id': other.map_id, 'base_revision': 0, 'zones': []})
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(json.loads(self.store.filename.read_text())['revision'], 1)

    def test_active_or_unknown_mission_rejects_edit(self):
        with self.assertRaises(MapRulesError) as caught:
            self.store.update_rules(self.request(), active=True)
        self.assertEqual(caught.exception.status, 409)
        self.assertFalse(self.store.filename.exists())

    def test_changed_map_and_bad_revision_rejected(self):
        for changes in ({'map_id': 'other'}, {'base_revision': True}, {'base_revision': -1},
                        {'base_revision': 0.5}):
            with self.subTest(changes=changes), self.assertRaises(MapRulesError):
                self.store.update_rules({**self.request(), **changes})

    def test_failed_atomic_replace_preserves_prior_file_and_reports_unavailable(self):
        self.store.update_rules(self.request())
        before = self.store.filename.read_bytes()
        with patch('map_rules.os.replace', side_effect=OSError('disk failure')):
            with self.assertRaises(MapRulesError) as caught:
                self.store.update_rules(self.request([]))
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(self.store.filename.read_bytes(), before)
        self.assertFalse(list(Path(self.temporary.name).glob('.*')))
        with self.assertRaises(MapRulesError):
            self.store.rules()

    def test_corrupt_file_is_not_silently_replaced(self):
        self.store.filename.write_text('{bad json')
        other = MapRulesStore(self.temporary.name)
        other.bind(grid())
        self.assertIn('persistence unavailable', other.error)
        with self.assertRaises(MapRulesError) as caught:
            other.update_rules(self.request())
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(other.filename.read_text(), '{bad json')

    def test_stored_nonfinite_json_and_wrong_map_rejected(self):
        self.store.update_rules(self.request())
        valid = json.loads(self.store.filename.read_text())
        for mutate in (lambda doc: doc.__setitem__('map_id', 'other'),
                       lambda doc: doc['zones'][0]['points'][0].__setitem__('x', math.nan)):
            altered = copy.deepcopy(valid)
            mutate(altered)
            self.store.filename.write_text(json.dumps(altered))
            other = MapRulesStore(self.temporary.name)
            other.bind(grid())
            self.assertIsNotNone(other.error)
            with self.assertRaises(MapRulesError):
                other.routes()

    def test_route_template_saved_without_execution_and_versioned(self):
        body = {'map_id': self.store.map_id, 'name': ' 客厅巡查 ',
                'waypoints': [{'x': 1., 'y': 1., 'yaw': 0.}], 'return_home': True}
        response = self.store.save_route(body)
        route = response['routes'][0]
        self.assertEqual(route['name'], '客厅巡查')
        self.assertEqual(route['revision'], 1)
        self.assertEqual(self.store.runs(), {'runs': []})
        response = self.store.save_route({**body, 'id': route['id'], 'name': '新路线'})
        self.assertEqual(len(response['routes']), 1)
        self.assertEqual(response['routes'][0]['revision'], 2)
        self.assertEqual(response['routes'][0]['id'], route['id'])

    def test_wrong_map_route_and_bad_fields_rejected(self):
        valid = {'map_id': self.store.map_id, 'name': '巡查',
                 'waypoints': [{'x': 1., 'y': 1., 'yaw': 0.}], 'return_home': True}
        for changes in ({'map_id': 'other'}, {'name': ' '}, {'name': 'x'*81},
                        {'return_home': 'yes'}, {'waypoints': []}, {'id': '../x'}):
            with self.subTest(changes=changes), self.assertRaises(MapRulesError):
                self.store.save_route({**valid, **changes})

    def test_route_write_preserves_rules_saved_by_another_instance(self):
        other = MapRulesStore(self.temporary.name)
        other.bind(grid())
        self.store.update_rules(self.request())
        other.save_route({'map_id': other.map_id, 'name': '巡查',
                         'waypoints': [{'x': 1., 'y': 1., 'yaw': 0.}], 'return_home': False})
        saved = json.loads(self.store.filename.read_text())
        self.assertEqual(saved['revision'], 1)
        self.assertEqual(saved['zones'], [wall()])
        self.assertEqual(len(saved['routes']), 1)

    def test_interrupted_run_remains_unknown_and_never_becomes_success(self):
        record = {'id': 'run_1', 'map_id': self.store.map_id, 'rules_revision': 0,
                  'started_at': 100., 'finished_at': None, 'status': 'running', 'current_index': 0,
                  'waypoints': [{'x': 1., 'y': 1., 'yaw': 0.}], 'return_home': False,
                  'message': '已提交', 'events': [], 'observations': []}
        self.store.save_run(record)
        other = MapRulesStore(self.temporary.name)
        other.bind(grid())
        restored = other.runs()['runs'][0]
        self.assertEqual(restored['status'], 'unknown')
        self.assertIsNone(restored['finished_at'])
        self.assertEqual(restored['id'], record['id'])
        self.assertEqual(restored['events'][-1]['type'], 'bridge_restart')
        self.assertEqual(other.routes()['routes'], [])

    def test_new_map_has_separate_routes_rules_and_runs(self):
        self.store.update_rules(self.request())
        old_filename = self.store.filename
        changed = grid()
        changed['data'][0] = 100
        self.store.bind(changed)
        self.assertNotEqual(self.store.filename, old_filename)
        self.assertEqual(self.store.rules()['revision'], 0)
        self.assertEqual(self.store.rules()['zones'], [])
        self.assertEqual(self.store.routes()['routes'], [])
        self.assertTrue(old_filename.exists())


    def run_record(self, status='succeeded', revision=0):
        return {'id': 'saved_run', 'map_id': self.store.map_id, 'rules_revision': revision,
            'started_at': 100., 'finished_at': 101. if status == 'succeeded' else None,
            'status': status, 'current_index': 0,
            'waypoints': [{'x': 1., 'y': 1., 'yaw': 0.}], 'return_home': False,
            'message': '记录', 'events': [], 'observations': []}

    def test_other_writer_revision_is_retained_when_saving_run(self):
        self.store.update_rules(self.request())
        other = MapRulesStore(self.temporary.name)
        other.bind(grid())
        other.update_rules({'map_id': other.map_id, 'base_revision': 1, 'zones': [rectangle()]})
        self.store.save_run(self.run_record(revision=1))
        self.assertEqual(self.store.document['revision'], 2)
        self.assertEqual(self.store.document['zones'], [rectangle()])
        self.assertEqual(self.store.runs()['runs'][0]['rules_revision'], 1)

    def test_start_run_compare_and_swap_rejects_rules_race_without_saving_ownership(self):
        self.store.update_rules(self.request())
        other = MapRulesStore(self.temporary.name)
        other.bind(grid())
        other.update_rules({'map_id': other.map_id, 'base_revision': 1, 'zones': []})
        with self.assertRaises(MapRulesError) as caught:
            self.store.save_run(self.run_record(status='running', revision=1), expected_rules_revision=1)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(json.loads(self.store.filename.read_text())['runs'], [])

    def test_external_writer_cannot_change_rules_while_disk_contains_active_ownership(self):
        self.store.save_run(self.run_record(status='running'))
        other = MapRulesStore(self.temporary.name)
        other.bind(grid())
        with self.assertRaises(MapRulesError) as caught:
            other.update_rules({'map_id': other.map_id, 'base_revision': 0, 'zones': [wall()]})
        self.assertEqual(caught.exception.status, 409)

    def test_refresh_detects_atomic_external_update_and_corruption(self):
        other = MapRulesStore(self.temporary.name)
        other.bind(grid())
        other.update_rules({'map_id': other.map_id, 'base_revision': 0, 'zones': [rectangle()]})
        self.assertTrue(self.store.refresh())
        self.assertEqual(self.store.rules()['revision'], 1)
        self.assertFalse(self.store.refresh())
        self.store.filename.write_text('{corrupt')
        with self.assertRaises(MapRulesError) as caught:
            self.store.refresh()
        self.assertEqual(caught.exception.status, 503)
        self.assertIsNotNone(self.store.error)


if __name__ == '__main__':
    unittest.main()
