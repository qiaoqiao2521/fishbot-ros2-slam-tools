"""Behavioral geometry tests; no ROS initialization, topics, or robot commands."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1]/'fishbot_passage.launch.py'
SPEC = importlib.util.spec_from_file_location('fishbot_passage_launch', SCRIPT)
passage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(passage)


def inside(point, polygon, tolerance=1e-10):
    return all((b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0]) >= -tolerance
               for a, b in zip(polygon, polygon[1:]+polygon[:1]))


def zone_for(config, linear, angular):
    zones = config['collision_monitor']['ros__parameters']['VelocityStop']
    for name in zones['velocity_polygons']:
        zone = zones[name]
        if zone['linear_min'] <= linear <= zone['linear_max'] and zone['theta_min'] <= angular <= zone['theta_max']:
            return json.loads(zone['points'])
    raise AssertionError(f'Uncovered velocity {linear}, {angular}')


class PassageGeometryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.params, cls.geometry = passage.load_parameters()

    def test_model_encloses_round_body_and_outside_wheel_corners(self):
        footprint = self.geometry['footprint']['points_m']
        # An inscribed octagon would fail at angles between its vertices.
        for i in range(3600):
            angle = i*math.tau/3600
            self.assertTrue(inside((.10*math.cos(angle), .10*math.sin(angle)), footprint))
        for x in (-.052, .012):
            for y in (-.12, .12):
                self.assertTrue(inside((x, y), footprint))
        self.assertAlmostEqual(max(y for _, y in footprint)-min(y for _, y in footprint), .24)

    def test_every_allowed_command_has_zone_covering_its_whole_arc(self):
        points = self.geometry['footprint']['points_m']
        duration = self.geometry['collision']['hard_reaction_time_s']
        for v in (-.08, -.07, -.03, -.001, 0., .001, .02, .03, .07, .08):
            for w in (-.25, -.1, -.01, 0., .01, .1, .25):
                polygon = zone_for(self.params, v, w)
                for i in range(31):
                    t = duration*i/30
                    a = w*t
                    tx = v*math.sin(a)/w if w else v*t
                    ty = v*(1-math.cos(a))/w if w else 0.
                    for x, y in points:
                        transformed = (tx+x*math.cos(a)-y*math.sin(a),
                                       ty+x*math.sin(a)+y*math.cos(a))
                        self.assertTrue(inside(transformed, polygon), (v, w, t, transformed))

    def test_every_generated_band_encloses_interior_velocities(self):
        points = json.loads(self.params['local_costmap']['local_costmap']['ros__parameters']['footprint'])
        duration = self.geometry['collision']['hard_reaction_time_s']
        zones = self.params['collision_monitor']['ros__parameters']['VelocityStop']
        for name in zones['velocity_polygons']:
            zone = zones[name]
            polygon = json.loads(zone['points'])
            self.assertLessEqual(zone['theta_max']-zone['theta_min'], .05+1e-12)
            for vf in (0., .4, 1.):
                v = zone['linear_min'] + vf*(zone['linear_max']-zone['linear_min'])
                for wf in (0., .2, .5, .8, 1.):
                    w = zone['theta_min'] + wf*(zone['theta_max']-zone['theta_min'])
                    for i in range(17):
                        t = duration*i/16
                        a = w*t
                        tx = v*math.sin(a)/w if w else v*t
                        ty = v*(1-math.cos(a))/w if w else 0.
                        for x, y in points:
                            moved = (tx+x*math.cos(a)-y*math.sin(a),
                                     ty+x*math.sin(a)+y*math.cos(a))
                            self.assertTrue(inside(moved, polygon), (name, v, w, t, moved))

    def test_angular_bands_are_truncated_and_cover_both_signs(self):
        config = passage.yaml.safe_load((SCRIPT.parent/'config/fishbot_passage_nav.yaml').read_text())
        for maximum in (.02, .073, .23, .25):
            geometry = copy.deepcopy(self.geometry)
            geometry['motion']['max_angular_rps'] = maximum
            params = passage.build_parameters(config, geometry)
            zones = params['collision_monitor']['ros__parameters']['VelocityStop']
            self.assertEqual(zones['velocity_polygons'][0], 'idle_straight')
            for name in zones['velocity_polygons']:
                zone = zones[name]
                self.assertGreaterEqual(zone['theta_min'], -maximum)
                self.assertLessEqual(zone['theta_max'], maximum)
                self.assertLessEqual(zone['theta_max']-zone['theta_min'], .05+1e-12)
            for i in range(201):
                w = -maximum+2*maximum*i/200
                for v in (-.08, 0., .08):
                    zone_for(params, v, w)
            if maximum == .25:
                self.assertLess(max(y for _, y in zone_for(params, 0., .025)),
                                max(y for _, y in zone_for(params, 0., .25)))

    def test_nearby_side_wall_is_soft_at_idle_not_fixed_hard_rectangle(self):
        cm = self.params['collision_monitor']['ros__parameters']
        # A wall at y=.16 leaves 4 cm from the wheels. It should invoke the
        # soft speed limit, not the old .36 m-wide fixed hard rectangle.
        wall = (-.02, .16)
        self.assertTrue(inside(wall, json.loads(cm['Slowdown']['points'])))
        self.assertFalse(inside(wall, zone_for(self.params, 0., 0.)))

    def test_model_change_propagates_to_both_costmaps_and_collision_zone(self):
        geometry = copy.deepcopy(self.geometry)
        geometry['footprint']['points_m'] = [[x*1.1, y*1.1] for x, y in geometry['footprint']['points_m']]
        config = passage.yaml.safe_load((SCRIPT.parent/'config/fishbot_passage_nav.yaml').read_text())
        changed = passage.build_parameters(config, geometry)
        a = changed['local_costmap']['local_costmap']['ros__parameters']['footprint']
        b = changed['global_costmap']['global_costmap']['ros__parameters']['footprint']
        self.assertEqual(a, b)
        self.assertTrue(inside((-.02, .13), json.loads(a)))
        self.assertTrue(inside((-.02, .13), zone_for(changed, 0., 0.)))
        self.assertFalse(inside((-.02, .13), zone_for(self.params, 0., 0.)))

    def test_invalid_geometry_and_weakened_thin_obstacle_policy_rejected(self):
        config = passage.yaml.safe_load((SCRIPT.parent/'config/fishbot_passage_nav.yaml').read_text())
        for mutation in ('clockwise', 'nan', 'min_points'):
            geometry = copy.deepcopy(self.geometry)
            if mutation == 'clockwise':
                geometry['footprint']['points_m'].reverse()
            elif mutation == 'nan':
                geometry['footprint']['points_m'][0][0] = float('nan')
            else:
                geometry['collision']['min_points'] = 2
            with self.assertRaises(ValueError):
                passage.build_parameters(config, geometry)

    def test_frame_override_propagates_to_all_navigation_consumers(self):
        geometry = copy.deepcopy(self.geometry)
        geometry['frames'] = dict(base='custom_base', odom='custom_odom',
                                  map='custom_map', scan='custom_laser')
        config = passage.yaml.safe_load((SCRIPT.parent/'config/fishbot_passage_nav.yaml').read_text())
        changed = passage.build_parameters(config, geometry)
        expected = {
            'bt_navigator': dict(global_frame='custom_map', robot_base_frame='custom_base'),
            'behavior_server': dict(global_frame='custom_map', local_frame='custom_odom',
                                    robot_base_frame='custom_base'),
            'docking_server': dict(base_frame='custom_base', fixed_frame='custom_odom'),
            'collision_monitor': dict(base_frame_id='custom_base', odom_frame_id='custom_odom'),
        }
        for node, frames in expected.items():
            for key, value in frames.items():
                self.assertEqual(changed[node]['ros__parameters'][key], value, (node, key))
        for name, global_frame in [('local_costmap', 'custom_odom'), ('global_costmap', 'custom_map')]:
            parameters = changed[name][name]['ros__parameters']
            self.assertEqual(parameters['robot_base_frame'], 'custom_base')
            self.assertEqual(parameters['global_frame'], global_frame)

    def test_execution_opt_in_and_runtime_privacy_boundaries(self):
        self.assertIsNone(passage.validate_execution_request(96, False, False, False))
        with self.assertRaises(ValueError):
            passage.validate_execution_request(0, True, False, False, '/tmp/fishbot-test')
        with self.assertRaises(ValueError):
            passage.validate_execution_request(0, True, True, True, '/tmp/fishbot-test')
        with self.assertRaises(ValueError):
            passage.validate_execution_request(96, True, False, True)
        with self.assertRaises(ValueError):
            passage.validate_execution_request(96, True, False, True, str(SCRIPT.parent/'captures'))
        self.assertEqual(passage.validate_execution_request(96, True, False, True, '/tmp/fishbot-test'),
                         Path('/tmp/fishbot-test'))


if __name__ == '__main__':
    unittest.main()
