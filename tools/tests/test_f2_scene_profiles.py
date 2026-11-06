"""Contracts and conservative added-layout clearance; no native runtime or steps."""
import json
import math
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from cooperation_factory_scene import normalize_factory_config
from cooperation_profiles import normalize_scene_profile, vehicle_profile

RECIPES = ROOT/'tools/config/factory_delivery/f2-scenes.json'


def load(path):
    return json.loads((ROOT/path).read_text())


def conservative_radius(vehicle):
    # Include the original chassis/tire footprint and the complete tray rim.
    # A disc bounds every yaw, including turns between declared route samples.
    points = list(vehicle['footprint_xy'])
    tx, ty, _ = vehicle['tray_offset_m']
    points += [[tx+x, ty+y] for x in (-.06, .06) for y in (-.06, .06)]
    return max(math.hypot(x, y) for x, y in points) + .02


def sampled_clearance(route, tree, radius, spacing=.01):
    obstacles = []
    for geom in tree.findall('worldbody/geom'):
        if geom.get('type') != 'box':
            continue
        center = [float(x) for x in geom.get('pos', '0 0 0').split()]
        half = [float(x) for x in geom.get('size').split()]
        obstacles.append((geom.get('name'), center, half))
    minimum = float('inf')
    for a, b in zip(route, route[1:]):
        count = max(1, math.ceil(math.dist(a, b)/spacing))
        bound = math.dist(a, b)/count/2
        for n in range(count+1):
            point = [a[j]+(b[j]-a[j])*n/count for j in range(2)]
            for _, center, half in obstacles:
                distance = math.hypot(*[max(abs(point[j]-center[j])-half[j], 0.) for j in range(2)])
                minimum = min(minimum, distance-radius-bound)
    return minimum


class F2SceneProfiles(unittest.TestCase):
    def scenes(self):
        return load(RECIPES)['scenes']

    def test_profiles_resolve_original_owners_and_preserve_original_budgets(self):
        self.assertEqual(len(self.scenes()), 2)
        for scene in self.scenes():
            profile = normalize_scene_profile(load(scene['scene_profile']))
            self.assertEqual(profile['sensors'], 'lidar3d')
            self.assertEqual(profile['task'], 'transport')
            factory = normalize_factory_config(load(scene['factory_config']))
            self.assertEqual(factory['id'], scene['id'])
            self.assertEqual(scene['orders'], ['order-b', 'order-a'])
            entities = load(scene['continuous_delivery'])
            self.assertEqual(entities['budgets_wall_s'], {'load_and_delivery': 360, 'unload': 180})
            self.assertEqual(load(scene['continuous_deliveries']), load('tools/config/factory_delivery/continuous-ba-orders.json'))
            stations = {s['id']: s for s in entities['unload_stations']}
            for destination in factory['destinations']:
                self.assertEqual(stations[destination['id']]['delivery_pose'], destination['pose'])
            self.assertEqual({c['id'] for c in entities['cargo_slots']}, {'cargo_1', 'cargo_2'})

    def test_warehouse_recipe_does_not_override_known_clear_j100_spawn(self):
        warehouse, workshop = self.scenes()
        self.assertEqual(warehouse['spawn'], [-.9, -1.68])
        self.assertEqual(warehouse['spawn_yaw'], 0.)
        self.assertEqual(workshop['spawn'], [-.9, -1.64])
        # [0,-2] overlaps unload_line_a__collision_base_1 in the actual v2
        # warehouse world. Changing the native check or body is not a fix.

    def test_workshop_coaxial_candidate_preserves_relative_handover_and_budgets(self):
        workshop = self.scenes()[1]
        entities = load(workshop['continuous_delivery'])
        original = load('tools/config/factory_delivery/continuous-ba-entities.json')
        self.assertIn('--staging-reversing', workshop['prepare_flags'])
        vehicle = vehicle_profile(load(workshop['scene_profile']))
        lane_y = -2. + vehicle['dock_offset_m'][1]
        for candidate, source in zip(entities['unload_stations'], original['unload_stations']):
            self.assertAlmostEqual(candidate['delivery_pose']['y'], lane_y)
            # Reuse the original station transform input: at yaw +pi/2 this
            # moves the complete unload fixture world X -0.10m toward cargo.
            self.assertEqual(candidate['pickup_xy_m'], [.24, .04])
            normalized = dict(candidate, delivery_pose=dict(candidate['delivery_pose'], y=source['delivery_pose']['y']))
            normalized.pop('pickup_xy_m')
            self.assertEqual(normalized, source)
        self.assertEqual(entities['budgets_wall_s'], original['budgets_wall_s'])
        self.assertEqual(entities['cargo_slots'], original['cargo_slots'])
        factory = load(workshop['factory_config'])
        self.assertTrue(all(abs(s['pose']['y']-lane_y)<1e-12 for s in factory['destinations']))

    def test_vision_and_ideal_are_explicit_and_never_inferred_from_camera_toggle(self):
        warehouse, workshop = self.scenes()
        self.assertEqual(warehouse['observation'], 'vision')
        self.assertEqual(load(warehouse['perception_config'])['mode'], 'vision')
        self.assertTrue((ROOT/warehouse['pretrained_grasp_config']).is_file())
        self.assertIn('--camera-rgbd', warehouse['prepare_flags'])
        self.assertEqual(workshop['observation'], 'ideal')
        self.assertNotIn('perception_config', workshop)
        self.assertNotIn('pretrained_grasp_config', workshop)

    def test_new_layouts_are_compact_native_primitives_and_not_renamed_old_geometry(self):
        old = ET.parse(ROOT/'tools/config/factory_delivery/j100-wide-arena.xml')
        old_boxes = {(g.get('pos'), g.get('size')) for g in old.findall('worldbody/geom') if g.get('type') == 'box'}
        layouts = []
        for scene in self.scenes():
            path = ROOT/scene['arena_xml']
            self.assertLess(path.stat().st_size, 10000)
            tree = ET.parse(path)
            names = [g.get('name') for g in tree.findall('worldbody/geom')]
            self.assertEqual(len(names), len(set(names)))
            self.assertTrue({'wall_north', 'wall_south', 'wall_east', 'wall_west', 'floor'} <= set(names))
            self.assertIsNotNone(tree.find('worldbody/camera[@name="arena_overview"]'))
            self.assertEqual(tree.findall('.//mesh'), [])
            boxes = {(g.get('pos'), g.get('size')) for g in tree.findall('worldbody/geom') if g.get('type') == 'box'}
            self.assertGreaterEqual(len(boxes-old_boxes), 7)
            layouts.append(boxes)
        self.assertNotEqual(*layouts)

    def test_added_layout_obstacles_leave_a_complete_vehicle_disc_sweep_clear(self):
        for scene in self.scenes():
            vehicle = vehicle_profile(load(scene['scene_profile']))
            radius = conservative_radius(vehicle)
            margin = sampled_clearance(scene['static_route_reference'], ET.parse(ROOT/scene['arena_xml']), radius)
            self.assertGreater(margin, .25, (scene['id'], margin))
            # This checks the new arena only. Original station-arm interactions
            # still need the existing compiled geometry and native task oracle.


if __name__ == '__main__':
    unittest.main()
