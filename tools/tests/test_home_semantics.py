"""Offline semantics, RGB recognition, active observation, and report tests."""

import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from fishbot_home_semantics import TaskParseError, parse_task, analyze_observation, next_observation
from fishbot_home_report import save_home_report


def semantic():
    return {'schema_version': 1, 'places': {
        'toolshelf': {'id': 'toolshelf', 'name': '工具架', 'aliases': ['工具区'],
                      'views': [[0, 0, 0], [.5, .2, .1], [.6, .3, .1]], 'target': 'red_box'},
        'entrance': {'id': 'entrance', 'name': '门口', 'aliases': ['入口'],
                     'views': [[1, 0, 1]], 'target': 'indicator'},
        'observation_point': {'name': '观察点', 'aliases': [],
                              'views': [[.5, .2, .1]], 'target': 'red_box'}}}


def panel(kind='red_box'):
    image = Image.new('RGB', (320, 240), (140, 140, 140))
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 35, 260, 205), fill=(15, 40, 220))
    draw.rectangle((74, 49, 246, 191), fill=(15, 15, 15))
    if kind == 'red_box':
        draw.rectangle((135, 95, 188, 147), fill=(220, 20, 20))
    elif kind in ('red', 'green'):
        draw.ellipse((136, 96, 184, 144), fill=(220, 20, 20) if kind == 'red' else (20, 220, 20))
    elif kind == 'occluded':
        draw.rectangle((50, 20, 180, 220), fill=(140, 140, 140))
    return np.array(image)


def observation(rgb, target, index):
    frames = [analyze_observation(rgb, target) for _ in range(3)]
    return {'view_index': index, 'frames': frames, **frames[0]}


class TaskGrammarTests(unittest.TestCase):
    def test_user_example_preserves_order_and_return(self):
        plan = parse_task('去工具架找红色盒子，看看门口指示灯，然后回来', semantic())
        self.assertEqual([s['place_id'] for s in plan['steps']], ['toolshelf', 'entrance'])
        self.assertEqual([s['target'] for s in plan['steps']], ['red_box', 'indicator'])
        self.assertTrue(plan['return_home'])
        json.dumps(plan, allow_nan=False)

    def test_aliases_and_three_station_grammar(self):
        plan = parse_task('请去工具区找红盒，再去入口查看指示灯状态，接着去观察点找红盒子，最后回家。', semantic())
        self.assertEqual([s['step_id'] for s in plan['steps']], ['step-1', 'step-2', 'step-3'])
        self.assertTrue(plan['return_home'])

    def test_unknown_place_target_and_extra_instructions_are_rejected(self):
        for task in ('去厨房找红盒', '去工具架找蓝盒子', '去工具架找红盒并关灯',
                     '如果有人就去门口看看指示灯', '回来，然后去工具架找红盒'):
            with self.subTest(task=task), self.assertRaises(TaskParseError):
                parse_task(task, semantic())

    def test_alias_collision_and_invalid_views_are_rejected(self):
        schema = semantic()
        schema['places']['entrance']['aliases'].append('工具架')
        with self.assertRaises(TaskParseError):
            parse_task('去工具架找红盒', schema)
        schema = semantic()
        schema['places']['toolshelf']['views'][0][0] = float('nan')
        with self.assertRaises(TaskParseError):
            parse_task('去工具架找红盒', schema)

    def test_place_fixture_target_does_not_override_user_target(self):
        plan = parse_task('去门口找红盒', semantic())
        self.assertEqual(plan['steps'][0]['target'], 'red_box')
        self.assertFalse(plan['return_home'])


class ActiveObservationTests(unittest.TestCase):
    def setUp(self):
        self.step = parse_task('去工具架找红盒', semantic())['steps'][0]

    def test_occluded_first_view_then_visible_box_succeeds(self):
        first = observation(panel('occluded'), 'red_box', 0)
        self.assertEqual(first['outcome'], 'unknown')
        decision = next_observation(self.step, [first])
        self.assertEqual((decision['status'], decision['view_index']), ('observe', 1))
        second = observation(panel('red_box'), 'red_box', 1)
        self.assertEqual(second['outcome'], 'found')
        self.assertEqual(next_observation(self.step, [first, second])['status'], 'complete')

    def test_visible_empty_region_is_explicit_not_found(self):
        absent = observation(panel('empty'), 'red_box', 0)
        self.assertEqual(absent['outcome'], 'not_found')
        self.assertEqual(next_observation(self.step, [absent])['status'], 'not_found')
        self.assertEqual(analyze_observation(panel('empty'), 'indicator')['outcome'], 'found')

    def test_red_circular_lamp_is_not_called_a_box(self):
        self.assertEqual(analyze_observation(panel('red'), 'indicator')['outcome'], 'found')
        self.assertEqual(analyze_observation(panel('red'), 'red_box')['outcome'], 'unknown')

    def test_all_unknown_exhausts_bound_without_claiming_absence(self):
        observations = [observation(panel('occluded'), 'red_box', i) for i in range(3)]
        self.assertEqual(next_observation(self.step, observations)['status'], 'failed')
        self.assertEqual(next_observation(self.step, observations[:2], max_views=2)['status'], 'failed')

    def test_battery_interruption_without_capture_resumes_same_view(self):
        self.assertEqual(next_observation(self.step, [])['view_index'], 0)
        observations = [observation(panel('occluded'), 'red_box', 0)]
        before = next_observation(self.step, observations)
        after = next_observation(self.step, copy.deepcopy(observations))
        self.assertEqual(before, after)
        self.assertEqual(after['view_index'], 1)

    def test_terminal_results_require_three_frame_agreement(self):
        item = observation(panel('red_box'), 'red_box', 0)
        item['frames'][1] = analyze_observation(panel('empty'), 'red_box')
        self.assertEqual(next_observation(self.step, [item])['status'], 'failed')

    def test_invalid_target_and_reused_view_fail_explicitly(self):
        with self.assertRaises(ValueError):
            analyze_observation(panel(), 'blue_box')
        first = observation(panel('occluded'), 'red_box', 0)
        with self.assertRaises(ValueError):
            next_observation(self.step, [first, first])


class HomeReportTests(unittest.TestCase):
    def test_all_views_frames_and_battery_events_remain_visible(self):
        step = parse_task('去工具架找红盒', semantic())['steps'][0]
        records = [observation(panel('occluded'), 'red_box', 0),
                   observation(panel('red_box'), 'red_box', 1)]
        for view in records:
            for i, frame in enumerate(view['frames']):
                frame.update(photo=f'view-{view["view_index"]}-{i}.png', capture_stamp=10 + i,
                             pose=[1, .2, .3])
        step.update(observations=records, outcome='found', completed=True)
        report = {'overall_status': 'completed', 'task': '去工具架找红盒，然后回来',
                  'steps': [step], 'final_stationary': {'verified': True},
                  'events': [{'event': 'battery_low', 'stamp': 5, 'soc': .2},
                             {'event': 'charging_confirmed', 'stamp': 15, 'current': 2}],
                  'battery_history': [[5, .2, -1, 2], [15, .4, 2, 1]],
                  'recharge_cycles': [{'completed': True}], 'elapsed_s': 30}
        with tempfile.TemporaryDirectory() as directory:
            html = save_home_report(report, Path(directory)).read_text()
        self.assertEqual(html.count('<img '), 6)
        for value in ('视角 0', '视角 1', 'battery_low', 'charging_confirmed',
                      'capture_stamp', '仿真秒', '已验证停稳', '场景假设'):
            self.assertIn(value, html)

    def test_errors_are_escaped_and_missing_stop_never_claims_success(self):
        report = {'task': '<script>bad()</script>', 'overall_status': 'failed', 'steps': [],
                  'error': '<img onerror=bad()>', 'events': [{'event': '<script>event</script>'}]}
        with tempfile.TemporaryDirectory() as directory:
            html = save_home_report(report, Path(directory)).read_text()
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img ', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('停稳未验证', html)
        self.assertNotIn('已验证停稳', html)

    def test_external_image_and_overview_cannot_load(self):
        report = {'steps': [{'observations': [{'frames': [{'photo': 'https://host/image.png'}]}]}],
                  'overview': '../secret.png'}
        with tempfile.TemporaryDirectory() as directory:
            html = save_home_report(report, Path(directory)).read_text()
        self.assertNotIn('<img ', html)
        self.assertIn('无有效本地照片', html)


if __name__ == '__main__':
    unittest.main()
