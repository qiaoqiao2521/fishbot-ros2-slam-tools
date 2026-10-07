"""Offline tests for private map preservation and physical scene consistency."""
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

MODULE = Path(__file__).resolve().parents[1] / 'fishbot_home_scene.py'
spec = importlib.util.spec_from_file_location('fishbot_home_scene', MODULE)
scene = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scene)


class HomeSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name)
        # Synthetic input only; no captured map or coordinates enter test fixtures.
        source = np.full((60, 60), 205, dtype=np.uint8)
        source[19:40, 19:41] = 254
        source[40, 19:41] = 0
        source[19:40, 18] = 0
        cls.raw = source
        Image.fromarray(source).save(cls.base / 'source.pgm')
        cls.info = {'image': 'source.pgm', 'resolution': .05, 'origin': [-1.5, -1.5, 0.],
                    'mode': 'trinary', 'negate': 0, 'occupied_thresh': .65, 'free_thresh': .196}
        cls.source = cls.base / 'source.yaml'
        cls.source.write_text(yaml.safe_dump(cls.info))
        cls.source_hashes = (scene.digest(cls.source), scene.digest(cls.base/'source.pgm'))
        cls.output = cls.base / 'generated'
        cls.semantic = scene.generate(cls.source, cls.output)
        cls.provenance = json.loads((cls.output/'provenance.json').read_text())
        cls.map = yaml.safe_load((cls.output/'map.yaml').read_text())
        cls.pixels = np.asarray(Image.open(cls.output/'map.pgm'))
        cls.assumptions = np.asarray(Image.open(cls.output/'assumption_mask.pgm'))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_source_bytes_and_known_pixels_are_preserved(self):
        self.assertEqual(self.source_hashes, (scene.digest(self.source), scene.digest(self.base/'source.pgm')))
        pad_y, pad_x = self.provenance['source_offset_rows_cols']
        inside = self.pixels[pad_y:pad_y+60, pad_x:pad_x+60]
        known = self.raw != 205
        np.testing.assert_array_equal(inside[known], self.raw[known])
        inside_mask = self.assumptions[pad_y:pad_y+60, pad_x:pad_x+60]
        np.testing.assert_array_equal(inside_mask == 0, known)
        self.assertEqual(self.source_hashes[0], self.provenance['source_yaml_sha256'])
        self.assertEqual(self.source_hashes[1], self.provenance['source_image_sha256'])

    def test_assumption_mask_explains_every_cell(self):
        self.assertEqual(set(np.unique(self.assumptions)), {0, 127, 255})
        self.assertTrue(np.all(self.pixels[self.assumptions == 127] == 255))
        self.assertTrue(np.all(self.pixels[self.assumptions == 255] == 0))
        self.assertEqual(int((self.assumptions == 0).sum()), int((self.raw != 205).sum()))

    def test_mujoco_boxes_exactly_match_map_including_rotated_textures(self):
        counts = np.zeros(self.pixels.shape, dtype=np.uint8)
        resolution = self.map['resolution']; ox, oy, _ = self.map['origin']
        root = ET.parse(self.output/'scene.xml').getroot()
        for geom in root.findall('./worldbody/geom'):
            if geom.get('type') != 'box': continue
            pos = np.fromstring(geom.get('pos'), sep=' ')
            half = np.fromstring(geom.get('size'), sep=' ')
            roll = float(geom.get('euler', '0 0 0').split()[0])
            transformed = np.array([half[0], abs(math.cos(roll))*half[1]+abs(math.sin(roll))*half[2],
                                    abs(math.sin(roll))*half[1]+abs(math.cos(roll))*half[2]])
            low, high = pos-transformed, pos+transformed
            self.assertLessEqual(low[2], 1e-8)
            self.assertGreaterEqual(high[2], .55-1e-8)
            c0, c1 = [round((v-ox)/resolution) for v in (low[0], high[0])]
            r0, r1 = [self.pixels.shape[0]-round((v-oy)/resolution) for v in (high[1], low[1])]
            self.assertTrue(0 <= r0 < r1 <= counts.shape[0] and 0 <= c0 < c1 <= counts.shape[1])
            counts[r0:r1, c0:c1] += 1
        np.testing.assert_array_equal(counts, (self.pixels == 0).astype(np.uint8))

    def test_rectangle_packing_keeps_thin_walls_and_single_cells(self):
        rng = np.random.default_rng(713)
        for _ in range(20):
            mask = rng.random((17, 23)) < .30
            counts = np.zeros(mask.shape, dtype=np.uint8)
            for r0, r1, c0, c1 in scene.rectangles(mask):
                counts[r0:r1, c0:c1] += 1
            np.testing.assert_array_equal(counts, mask.astype(np.uint8))

    def test_robot_model_is_included_unchanged(self):
        root = ET.parse(self.output/'scene.xml').getroot()
        self.assertEqual(Path(root.find('include').get('file')), scene.DEFAULT_ROBOT.resolve())
        self.assertFalse(root.findall('.//actuator'))
        self.assertFalse(root.findall('.//body[@name="base_footprint"]'))
        self.assertEqual(self.provenance['robot_model_sha256'], scene.digest(scene.DEFAULT_ROBOT))

    def test_spawn_goals_and_observation_poses_have_physical_clearance(self):
        grid = scene.Grid(self.pixels == 0, self.assumptions == 0, self.map['origin'], self.map['resolution'])
        reach = grid.reachable()
        poses = [self.semantic['spawn'], *[s['goal'] for s in self.semantic['stations']]]
        poses += [v for p in self.semantic['places'].values() for v in p['views']]
        poses += [[self.semantic['dock'][field][k] for k in ('x','y','yaw')]
                  for field in ('pose','staging_pose')]
        for pose in poses:
            cell = grid.cell(*pose[:2])
            self.assertGreaterEqual(reach[cell], 0)
            self.assertTrue(grid.safe_centers(pose[2])[cell])
            self.assertTrue(grid.pose_is_free(pose))

    def test_off_grid_pose_uses_continuous_center(self):
        occupied = np.zeros((30, 30), dtype=bool); occupied[:, 10] = True
        grid = scene.Grid(occupied, occupied, [0., 0., 0.], .05)
        self.assertTrue(grid.safe_centers()[grid.cell(.651, .5)])
        self.assertFalse(grid.pose_is_free([.651, .5, 0.]))
        self.assertTrue(grid.pose_is_free([.661, .5, 0.]))

    def test_dock_contact_frame_and_approach_direction_are_explicit(self):
        dock = self.semantic['dock']; final, stage = dock['pose'], dock['staging_pose']
        self.assertEqual(dock['truth_to_dock_frame'], {'x':0., 'y':0., 'yaw':0.})
        self.assertAlmostEqual(final['yaw'], stage['yaw'])
        dx, dy = stage['x']-final['x'], stage['y']-final['y']
        forward = dx*math.cos(final['yaw'])+dy*math.sin(final['yaw'])
        sideways = -dx*math.sin(final['yaw'])+dy*math.cos(final['yaw'])
        self.assertLess(forward, -.2)
        self.assertAlmostEqual(sideways, 0.)
        self.assertEqual(dock['contact']['center'], {k:final[k] for k in ('x','y')})

    def test_artifact_hashes_bind_local_outputs(self):
        for filename, expected in self.provenance['artifacts_sha256'].items():
            self.assertEqual(scene.digest(self.output/filename), expected)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)

    def test_existing_output_is_not_overwritten(self):
        before = scene.digest(self.output/'scene.xml')
        with self.assertRaisesRegex(ValueError, 'new or empty'):
            scene.generate(self.source, self.output)
        self.assertEqual(scene.digest(self.output/'scene.xml'), before)

    def test_rotated_or_nonfinite_source_metadata_is_rejected(self):
        for origin in ([-1., -1., .2], [-1., float('nan'), 0.]):
            path = self.base/'invalid.yaml'
            path.write_text(yaml.safe_dump({**self.info, 'origin': origin}))
            with self.assertRaisesRegex(ValueError, 'axis-aligned'):
                scene.load_map(path)

    def test_task_targets_are_not_observation_results(self):
        self.assertEqual(self.semantic['home'], [0.,0.,0.])
        self.assertEqual(set(self.semantic['places']), {'toolshelf','observation_point','entrance_indicator'})
        self.assertEqual(len(self.semantic['places']['toolshelf']['views']), 2)
        for place in self.semantic['places'].values():
            self.assertIn(place['target'], ('red_box','indicator'))
            self.assertNotIn('observed_state', place)
            self.assertNotIn('found', place)


class MapThresholdTests(unittest.TestCase):
    def write_source(self, base, raw, negate, free, occupied):
        Image.fromarray(raw).save(base/'source.pgm')
        info = {'image': 'source.pgm', 'mode': 'trinary', 'resolution': .05,
                'origin': [-1.5, -1.5, 0.], 'negate': negate,
                'free_thresh': free, 'occupied_thresh': occupied}
        path = base/'source.yaml'
        path.write_text(yaml.safe_dump(info))
        return path

    def test_exact_endpoints_are_known_for_both_negations(self):
        raw = np.tile(np.array([0, 128, 255], dtype=np.uint8), (3, 1))
        for negate in (0, 1):
            with self.subTest(negate=negate), tempfile.TemporaryDirectory() as directory:
                path = self.write_source(Path(directory), raw, negate, 0., 1.)
                _, _, free, occupied, _, _ = scene.load_map(path)
                expected_free = np.tile([False, False, True] if negate == 0 else [True, False, False], (3, 1))
                expected_occupied = np.tile([True, False, False] if negate == 0 else [False, False, True], (3, 1))
                np.testing.assert_array_equal(free, expected_free)
                np.testing.assert_array_equal(occupied, expected_occupied)

    def test_equal_float32_thresholds_remain_known(self):
        raw = np.tile(np.array([0, 127, 128, 255], dtype=np.uint8), (3, 1))
        for negate in (0, 1):
            values = raw.astype(np.float32)/np.float32(255)
            if not negate:
                values = 1-values
            free_threshold, occupied_threshold = sorted([float(values[0, 1]), float(values[0, 2])])
            with self.subTest(negate=negate), tempfile.TemporaryDirectory() as directory:
                path = self.write_source(Path(directory), raw, negate, free_threshold, occupied_threshold)
                _, _, free, occupied, _, _ = scene.load_map(path)
                expected_free = np.tile([False, False, True, True] if negate == 0 else [True, True, False, False], (3, 1))
                np.testing.assert_array_equal(free, expected_free)
                np.testing.assert_array_equal(occupied, ~expected_free)

    def test_completed_pixels_match_physical_occupancy_at_extreme_thresholds(self):
        for negate in (0, 1):
            for free, occupied in ((.001, .999), (0., 1.)):
                with self.subTest(negate=negate, free=free, occupied=occupied), tempfile.TemporaryDirectory() as directory:
                    base = Path(directory)
                    raw = np.full((60, 60), 128, dtype=np.uint8)
                    free_pixel, occupied_pixel = (255, 0) if not negate else (0, 255)
                    raw[19:40, 19:41] = free_pixel
                    raw[40, 19:41] = occupied_pixel
                    raw[19:40, 18] = occupied_pixel
                    path = self.write_source(base, raw, negate, free, occupied)
                    before = path.read_bytes(), (base/'source.pgm').read_bytes()
                    scene.generate(path, base/'fixture')
                    pixels = np.asarray(Image.open(base/'fixture/map.pgm'))
                    mask = np.asarray(Image.open(base/'fixture/assumption_mask.pgm'))
                    # Classify output independently of load_map using Nav2 1.3.13 semantics.
                    probability = pixels.astype(np.float32)/np.float32(255)
                    if not negate:
                        probability = 1-probability
                    self.assertTrue(np.all(probability[mask == 127] <= free))
                    self.assertTrue(np.all(probability[mask == 255] >= occupied))
                    self.assertEqual(before, (path.read_bytes(), (base/'source.pgm').read_bytes()))
                    known = np.isin(raw, [0, 255]); pad = round(3/.05)
                    np.testing.assert_array_equal(pixels[pad:pad+60, pad:pad+60][known], raw[known])


if __name__ == '__main__':
    unittest.main()
