"""Known-space route contracts; no ROS, GPU or motion owner is started."""
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image
import yaml

TOOLS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('real_scene', TOOLS / 'fishbot_real_scene.py')
scene = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scene)


class RealScene(unittest.TestCase):
    def make_map(self, directory, *, negate=0):
        raw = np.full((61, 81), 254, dtype=np.uint8)
        raw[:2] = raw[-2:] = 0
        raw[:, :2] = raw[:, -2:] = 0
        raw[10:25, 49:65] = 205
        if negate:
            raw = 255-raw
        image = Path(directory) / 'source.pgm'
        Image.fromarray(raw).save(image)
        info = {'image': image.name, 'mode': 'trinary', 'resolution': .05,
                'origin': [-2.025, -1.525, 0.], 'negate': negate,
                'free_thresh': .196, 'occupied_thresh': .65}
        source = Path(directory) / 'source.yaml'
        source.write_text(yaml.safe_dump(info))
        return source, raw

    def test_original_unknown_and_amcl_raster_are_preserved_and_not_physical_walls(self):
        with tempfile.TemporaryDirectory() as directory:
            source, raw = self.make_map(directory)
            output = Path(directory) / 'private-output'
            config, provenance = scene.prepare(source, output, distance_m=.8)
            np.testing.assert_array_equal(np.asarray(Image.open(output / 'map.pgm')), raw)
            mask = np.asarray(Image.open(output / 'assumption_mask.pgm'))
            self.assertTrue((mask[10:25, 49:65] == 127).all())
            self.assertEqual(provenance['unknown_completion'], 'none')
            nav = yaml.safe_load((output / 'nav2.yaml').read_text())
            self.assertFalse(nav['planner_server']['ros__parameters']['GridBased']['allow_unknown'])
            self.assertEqual(nav['amcl']['ros__parameters']['initial_pose']['x'], 0.)
            xml = ET.parse(output / 'scene.xml')
            self.assertIsNone(xml.find("worldbody/geom[@name='dock_marker']"))
            # The physical union is precisely the measured occupied cells. An unknown
            # rectangle remains unmodeled, instead of becoming an AMCL-visible wall.
            union = np.zeros(raw.shape, dtype=bool)
            for wall in provenance['physical_wall_rectangles']:
                r0, r1, c0, c1 = wall['grid_rectangle']
                union[r0:r1, c0:c1] = True
            np.testing.assert_array_equal(union, raw == 0)
            self.assertEqual(config['domain'], 132)
            self.assertEqual(config['api'], 'http://127.0.0.1:9102')
            self.assertTrue(config['return_home'])
            json.dumps(config, allow_nan=False)

    def test_full_disk_sweep_remains_known_free_in_continuous_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            source, _ = self.make_map(directory)
            _, _, free, _, _, _, grid, clearance, radius = scene.measured_space(source)
            route = scene.select_route(grid, clearance, radius, .8, .03)
            bad = np.argwhere(~free)
            for first, second in zip(route['swept_path_xy'], route['swept_path_xy'][1:]):
                for fraction in np.linspace(0., 1., 101):
                    x, y = np.array(first) + fraction*(np.array(second)-first)
                    for row, column in bad:
                        cx, cy = grid.xy(row, column)
                        dx = max(abs(cx-x)-.025, 0.)
                        dy = max(abs(cy-y)-.025, 0.)
                        self.assertGreaterEqual(math.hypot(dx, dy)+1e-9, radius+.03)

    def test_unknown_barrier_cannot_be_used_to_reach_disconnected_free_island(self):
        with tempfile.TemporaryDirectory() as directory:
            source, raw = self.make_map(directory)
            raw[:, 48:53] = 205
            Image.fromarray(raw).save(source.parent / 'source.pgm')
            *_, grid, clearance, radius = scene.measured_space(source)
            route = scene.select_route(grid, clearance, radius, .5, .03)
            self.assertTrue(all(point[0] < .4 for point in route['swept_path_xy']))
            with self.assertRaisesRegex(ValueError, 'connected free space'):
                scene.select_route(grid, clearance, radius, 10., .03)

    def test_negated_raster_has_same_geometry_and_unknown_spawn_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source, raw = self.make_map(directory, negate=1)
            info, _, free, occupied, _, _, grid, clearance, radius = scene.measured_space(source)
            self.assertEqual(info['negate'], 1)
            self.assertTrue(free[30, 40])
            self.assertTrue(occupied[0, 0])
            self.assertEqual(scene.select_route(grid, clearance, radius, .5)['swept_path_xy'][0], [0., 0.])
            raw[29:32, 39:42] = 50
            Image.fromarray(raw).save(source.parent / 'source.pgm')
            output = Path(directory) / 'no-output'
            with self.assertRaisesRegex(ValueError, 'spawn'):
                scene.prepare(source, output, distance_m=.5)
            self.assertFalse(output.exists())

    def test_independent_recording_fails_on_unknown_or_outside_and_missing_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            source, _ = self.make_map(directory)
            case = {'measured_map': str(source)}
            good = scene.audit_recording(case, [{'x': 0., 'y': 0.}, {'x': -.4, 'y': 0.}])
            self.assertTrue(good['passed'])
            self.assertEqual(good['metrics']['measured_truth_samples'], 2)
            self.assertGreater(scene.measured_pose_clearance(source, [0., 0., 0.]), 0.)
            self.assertFalse(scene.audit_recording(case, [{'x': .65, 'y': .5}])['passed'])
            self.assertFalse(scene.audit_recording(case, [{'x': 9., 'y': 9.}])['passed'])
            self.assertIsNone(scene.audit_recording(case, [])['passed'])
            self.assertIsNone(scene.audit_recording({'measured_map': str(source)+'-missing'}, [{'x': 0., 'y': 0.}])['passed'])

    def test_edited_invalid_source_yaml_keeps_scoring_unknown_instead_of_throwing(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'edited.yaml'
            source.write_text('origin: [\n')
            result = scene.audit_recording({'measured_map': str(source)}, [{'x': 0., 'y': 0.}])
            self.assertIsNone(result['passed'])
            self.assertEqual(result['metrics']['measured_truth_samples'], 0)
            self.assertIn('Measured-map evidence unavailable', result['reason'])
            self.assertIsNone(result['metrics']['minimum_measured_free_margin_m'])


if __name__ == '__main__':
    unittest.main()
