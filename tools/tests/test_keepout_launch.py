"""Configuration contract for optional map rules; no ROS processes are started."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
HELPER = (ROOT / 'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco'
          / 'launch/keepout_parameters.py')
spec = importlib.util.spec_from_file_location('keepout_parameters', HELPER)
keepout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(keepout)


def configuration():
    return {
        name: {name: {'ros__parameters': {
            'plugins': ['static_layer', 'obstacle_layer', 'inflation_layer'],
            'filters': ['speed_filter'],
            'speed_filter': {'plugin': 'nav2_costmap_2d::SpeedFilter'},
            'resolution': 0.05,
        }}}
        for name in ('global_costmap', 'local_costmap')
    } | {'controller_server': {'ros__parameters': {
        'goal_checker': {'xy_goal_tolerance': 0.03},
        'FollowPath': {'desired_linear_vel': 0.12},
    }}, 'custom_node': {'ros__parameters': {'custom': [2, 4, 6]}}}


class KeepoutLaunchTest(unittest.TestCase):
    def test_disabled_preserves_exact_source_and_avoids_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'custom.yaml'
            raw = b'# Preserve comments and bytes\ncontroller_server: {}\n'
            source.write_bytes(raw)
            output = Path(directory) / 'output'
            result = keepout.prepare_keepout_parameters(str(source), False, output)
            self.assertEqual(result['params_path'], str(source))
            self.assertEqual(source.read_bytes(), raw)
            self.assertEqual(result['params_sha256'], hashlib.sha256(raw).hexdigest())
            self.assertFalse(output.exists())

    def test_enabled_adds_both_filters_without_changing_plugins(self):
        original = configuration()
        saved = copy.deepcopy(original)
        merged = keepout.merge_keepout_parameters(original)
        self.assertEqual(original, saved)
        for name in ('global_costmap', 'local_costmap'):
            values = merged[name][name]['ros__parameters']
            self.assertEqual(values['plugins'], saved[name][name]['ros__parameters']['plugins'])
            self.assertEqual(values['filters'], ['speed_filter', 'keepout_filter',
                                                 'keepout_inflation'])
            self.assertEqual(values['keepout_filter'], {
                'plugin': 'nav2_costmap_2d::KeepoutFilter', 'enabled': True,
                'filter_info_topic': '/keepout_costmap_filter_info',
                'override_lethal_cost': False,
            })
            self.assertEqual(values['keepout_inflation'], {
                'plugin': 'nav2_costmap_2d::InflationLayer', 'enabled': True,
                'inflation_radius': 0.3, 'cost_scaling_factor': 4.0,
            })

    def test_existing_filters_are_preserved_and_merge_is_idempotent(self):
        original = configuration()
        original['global_costmap']['global_costmap']['ros__parameters']['filters'] = [
            'keepout_inflation', 'speed_filter', 'keepout_filter', 'other_filter',
            'speed_filter', 'keepout_filter', 'keepout_inflation']
        first = keepout.merge_keepout_parameters(original)
        self.assertEqual(first, keepout.merge_keepout_parameters(first))
        self.assertEqual(first['global_costmap']['global_costmap']['ros__parameters']['filters'],
                         ['speed_filter', 'other_filter', 'keepout_filter', 'keepout_inflation'])

    def test_native_inflation_parameters_and_footprint_remain_unchanged(self):
        original = configuration()
        baseline = {
            'plugin': 'nav2_costmap_2d::InflationLayer', 'enabled': True,
            'inflation_radius': 0.42, 'cost_scaling_factor': 3.7,
            'inflate_unknown': True, 'inflate_around_unknown': False,
        }
        for name in ('global_costmap', 'local_costmap'):
            values = original[name][name]['ros__parameters']
            values['inflation_layer'] = copy.deepcopy(baseline)
            values['robot_radius'] = 0.13
            values['footprint_padding'] = 0.01
        merged = keepout.merge_keepout_parameters(original)
        for name in ('global_costmap', 'local_costmap'):
            values = merged[name][name]['ros__parameters']
            self.assertEqual(values['inflation_layer'], baseline)
            self.assertEqual(values['keepout_inflation'], baseline)
            self.assertEqual(values['robot_radius'], 0.13)
            self.assertEqual(values['footprint_padding'], 0.01)
            self.assertIsNot(values['inflation_layer'], values['keepout_inflation'])
            self.assertEqual(values['plugins'], original[name][name]['ros__parameters']['plugins'])

    def test_custom_navigation_settings_and_node_parameters_survive(self):
        original = configuration()
        original['local_costmap']['local_costmap']['ros__parameters']['keepout_filter'] = {
            'plugin': 'nav2_costmap_2d::KeepoutFilter', 'transform_tolerance': 0.2,
            'enabled': False, 'override_lethal_cost': True}
        merged = keepout.merge_keepout_parameters(original)
        self.assertEqual(merged['controller_server'], original['controller_server'])
        self.assertEqual(merged['custom_node'], original['custom_node'])
        self.assertEqual(merged['local_costmap']['local_costmap']['ros__parameters']
                         ['keepout_filter']['transform_tolerance'], 0.2)

    def test_generated_file_has_verifiable_source_and_unique_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'custom.yaml'
            source.write_text(yaml.safe_dump(configuration()), encoding='utf-8')
            output = Path(directory) / 'run'
            first = keepout.prepare_keepout_parameters(str(source), True, output)
            second = keepout.prepare_keepout_parameters(str(source), True, output)
            self.assertNotEqual(first['params_path'], second['params_path'])
            self.assertEqual(first['source_sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
            generated = Path(first['params_path'])
            self.assertEqual(first['params_sha256'], hashlib.sha256(generated.read_bytes()).hexdigest())
            self.assertEqual(json.loads(Path(str(generated) + '.source.json').read_text()), first)
            self.assertEqual(yaml.safe_load(generated.read_text()),
                             keepout.merge_keepout_parameters(configuration()))

    def test_invalid_parameter_files_fail_before_generating_output(self):
        invalid = [b'broken: [', b'[]', b'global_costmap: {}',
                   yaml.safe_dump(configuration() | {
                       'local_costmap': {'local_costmap': {'ros__parameters': {'filters': 'wrong'}}}
                   }).encode()]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'run'
            for index, raw in enumerate(invalid):
                source = Path(directory) / f'invalid-{index}.yaml'
                source.write_bytes(raw)
                with self.subTest(index=index), self.assertRaises(ValueError):
                    keepout.prepare_keepout_parameters(source, True, output)
            with self.assertRaises(ValueError):
                keepout.prepare_keepout_parameters(Path(directory) / 'missing.yaml', True, output)
            self.assertFalse(output.exists())

    def test_conflicting_filter_plugin_is_not_overwritten(self):
        for name in ('keepout_filter', 'keepout_inflation'):
            original = configuration()
            original['local_costmap']['local_costmap']['ros__parameters'][name] = {
                'plugin': 'other::Plugin'}
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'different plugin'):
                keepout.merge_keepout_parameters(original)


if __name__ == '__main__':
    unittest.main()
