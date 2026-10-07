"""Behavioral tests for RGB-only inspection and report output."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw


SOURCE = Path(__file__).resolve().parents[1] / 'fishbot_inspection_vision.py'
SPEC = importlib.util.spec_from_file_location('inspection_vision', SOURCE)
vision = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vision)


def panel(state='empty', box=(60, 35, 260, 205), size=(320, 240)):
    image = Image.new('RGB', size, (150, 145, 135))
    draw = ImageDraw.Draw(image)
    draw.rectangle(box, fill=(15, 40, 220))
    x0, y0, x1, y1 = box
    border = max(3, min(x1 - x0, y1 - y0) // 12)
    draw.rectangle((x0 + border, y0 + border, x1 - border, y1 - border), fill=(15, 15, 15))
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    if state in ('red', 'green', 'yellow'):
        color = {'red': (230, 20, 15), 'green': (20, 220, 25), 'yellow': (220, 220, 20)}[state]
        draw.ellipse((cx - 19, cy - 19, cx + 19, cy + 19), fill=color)
    if state == 'both':
        draw.ellipse((cx - 38, cy - 16, cx - 6, cy + 16), fill=(230, 20, 15))
        draw.ellipse((cx + 6, cy - 16, cx + 38, cy + 16), fill=(20, 220, 25))
    return np.array(image)


class InspectionVisionTests(unittest.TestCase):
    def test_states_depend_only_on_pixels(self):
        for state in ('red', 'green', 'empty'):
            with self.subTest(state=state):
                result = vision.analyze_rgb(panel(state))
                self.assertEqual(result['state'], state)
                self.assertTrue(result['evidence']['visible_blue_frame'])
                json.dumps(result, allow_nan=False)

    def test_no_panel_and_outside_lamp_are_not_empty_or_green(self):
        rgb = np.full((240, 320, 3), 15, dtype=np.uint8)
        rgb[80:120, 100:140] = (20, 220, 25)
        self.assertEqual(vision.analyze_rgb(rgb)['state'], 'unknown')
        empty = panel()
        empty[0:25, 0:25] = (20, 220, 25)
        self.assertEqual(vision.analyze_rgb(empty)['state'], 'empty')

    def test_tiny_and_clipped_panels_are_unknown(self):
        for rgb in (panel(box=(20, 20, 38, 38)), panel(box=(-15, 35, 185, 205))):
            self.assertEqual(vision.analyze_rgb(rgb)['state'], 'unknown')

    def test_missing_frame_side_and_solid_blue_are_unknown(self):
        rgb = panel()
        rgb[35:206, 60:74] = (150, 145, 135)
        self.assertEqual(vision.analyze_rgb(rgb)['state'], 'unknown')
        self.assertEqual(vision.analyze_rgb(np.full((80, 100, 3), (10, 30, 220), dtype=np.uint8))['state'], 'unknown')

    def test_conflicting_or_unknown_indicator_color_is_unknown(self):
        self.assertEqual(vision.analyze_rgb(panel('both'))['state'], 'unknown')
        self.assertEqual(vision.analyze_rgb(panel('yellow'))['state'], 'unknown')

    def test_tiny_indicator_does_not_claim_empty(self):
        rgb = panel()
        rgb[116:118, 156:158] = (230, 20, 15)
        self.assertEqual(vision.analyze_rgb(rgb)['state'], 'unknown')

    def test_indicator_near_inner_edge_is_not_cropped_to_empty(self):
        rgb = panel()
        rgb[80:100, 77:94] = (20, 220, 25)
        self.assertEqual(vision.analyze_rgb(rgb)['state'], 'green')

    def test_small_unrecognized_bright_object_is_not_empty(self):
        for color in ((220, 220, 20), (220, 220, 220)):
            rgb = panel()
            rgb[116:120, 156:160] = color
            self.assertEqual(vision.analyze_rgb(rgb)['state'], 'unknown')

    def test_multiple_panels_are_ambiguous(self):
        rgb = np.concatenate([panel('red'), panel('green')], axis=1)
        self.assertEqual(vision.analyze_rgb(rgb)['state'], 'unknown')

    def test_dim_frame_and_indicator_remain_readable(self):
        rgb = (panel('green').astype(float) * 0.6).astype(np.uint8)
        self.assertEqual(vision.analyze_rgb(rgb)['state'], 'green')

    def test_large_image_bounding_box_uses_original_coordinates(self):
        rgb = np.asarray(Image.fromarray(panel('red')).resize((1280, 960), Image.Resampling.NEAREST))
        result = vision.analyze_rgb(rgb)
        self.assertEqual(result['state'], 'red')
        self.assertEqual(result['evidence']['image_size'], [1280, 960])
        self.assertEqual(result['evidence']['bbox'], [240, 140, 1044, 824])

    def test_invalid_inputs_fail_explicitly(self):
        for value, exception in [(None, TypeError), (np.zeros((10, 10, 3)), TypeError),
                                 (np.zeros((10, 10), dtype=np.uint8), ValueError),
                                 (np.zeros((10, 10, 4), dtype=np.uint8), ValueError),
                                 (np.zeros((0, 10, 3), dtype=np.uint8), ValueError)]:
            with self.subTest(shape=getattr(value, 'shape', None)):
                with self.assertRaises(exception):
                    vision.analyze_rgb(value)


class ReportTests(unittest.TestCase):
    def test_report_contains_escaped_evidence_and_relative_photo(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            report = {'overall_status': 'completed', 'elapsed_s': 12.3, 'stations': [{
                'name': '<script>alert(1)</script>', 'question': '灯是绿色吗？',
                'state': 'green', 'photo': 'photos/station 1.png', 'capture_stamp': 123.4,
                'pose': {'x': 1.2}, 'action': {'result': 'succeeded'},
                'evidence': {'text': '<img src=x onerror=alert(1)>'}}]}
            path = vision.save_report(report, directory)
            html = path.read_text()
            self.assertEqual(path, directory / 'index.html')
            self.assertIn('photos/station%201.png', html)
            self.assertIn('&lt;script&gt;', html)
            self.assertNotIn('<script>', html)
            self.assertIn('&lt;img src=x onerror=alert(1)&gt;', html)
            for value in ('12.3', '123.4', 'succeeded', '1.2', '绿灯'):
                self.assertIn(value, html)

    def test_remote_and_parent_photos_cannot_load(self):
        with tempfile.TemporaryDirectory() as temporary:
            for photo in ('https://host/image.png', '../outside.png', '//host/image.png',
                          'javascript:alert(1)', '/tmp/elsewhere.png', 'a\\b.png'):
                with self.subTest(photo=photo):
                    path = vision.save_report({'stations': [{'photo': photo}]}, Path(temporary))
                    self.assertNotIn('<img ', path.read_text())

    def test_absolute_contained_photo_becomes_relative(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = vision.save_report({'stations': [{'photo': root / 'capture.png'}]}, root)
            self.assertIn('src="capture.png"', path.read_text())

    def test_report_exposes_failed_return_and_unverified_stop(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = {'stations': [{'state': 'green'}], 'overall_status': 'failed',
                      'return_home': {'completed': False, 'action': {'status': 6},
                                      'physical_error': {'xy_m': .7}},
                      'final_stationary': {'verified': False},
                      'error': '<script>failure</script>', 'cleanup_errors': ['stop feedback: stale']}
            html = vision.save_report(report, Path(temporary)).read_text()
            for value in ('未完成或未验证', '停稳未验证', 'stop feedback: stale', 'xy_m', '0.7'):
                self.assertIn(value, html)
            self.assertIn('&lt;script&gt;failure&lt;/script&gt;', html)
            self.assertNotIn('<script>', html)
            self.assertIn('拍摄时间（仿真秒）', html)

    def test_report_route_requires_recorded_finite_samples(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            absent = vision.save_report({'stations': []}, root).read_text()
            self.assertNotIn('<svg ', absent)
            report = {'stations': [{'goal': [1, 0, 0]}],
                      'trajectory': [[1, 0, 0, 0], [2, 1, .5, 0], [3, float('nan'), 2, 0]],
                      'return_home': {'completed': True, 'goal': [0, 0, 0]},
                      'final_stationary': {'verified': True}}
            html = vision.save_report(report, root).read_text()
            self.assertIn('<svg ', html)
            self.assertIn('<polyline ', html)
            self.assertNotIn('nan', html)
            self.assertIn('已验证停稳', html)


if __name__ == '__main__':
    unittest.main()
