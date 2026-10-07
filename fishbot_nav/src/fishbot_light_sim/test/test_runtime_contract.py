"""Pure boundary tests; no ROS imports, nodes, actions, or hardware commands."""
import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fishbot_light_sim.runtime_contract import (configure_simulation_environment,
                                               ground_truth_enabled, readable_map,
                                               simulation_environment)


class RuntimeContractTests(unittest.TestCase):
    def test_default_domain_overrides_ambient_hardware_or_other_sim_domain(self):
        for ambient in ('0', '93', '96', '97'):
            env = {'ROS_DOMAIN_ID': ambient, 'ROS_AUTOMATIC_DISCOVERY_RANGE': 'SUBNET',
                   'ROS_STATIC_PEERS': '192.0.2.1', 'ROS_LOCALHOST_ONLY': '0'}
            self.assertEqual(configure_simulation_environment(env), 94)
            self.assertEqual(env, simulation_environment('94'))

    def test_invalid_explicit_domain_is_rejected_without_environment_mutation(self):
        for domain in ('0', '00', '-1', '233', '94.0', '+94', '', '９４'):
            env = {'FISHBOT_LIGHT_SIM_DOMAIN_ID': domain, 'ROS_DOMAIN_ID': '0'}
            original = dict(env)
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                configure_simulation_environment(env)
            self.assertEqual(env, original)

    def test_explicit_nonzero_domain_remains_loopback_only(self):
        env = {'FISHBOT_LIGHT_SIM_DOMAIN_ID': '95'}
        self.assertEqual(configure_simulation_environment(env), 95)
        self.assertEqual(env['ROS_AUTOMATIC_DISCOVERY_RANGE'], 'LOCALHOST')
        self.assertEqual(env['ROS_STATIC_PEERS'], '')

    def test_amcl_excludes_ground_truth_localization(self):
        for enabled in (True, 'true', 'TRUE'):
            self.assertFalse(ground_truth_enabled(enabled))
        for disabled in (False, 'false', 'FALSE'):
            self.assertTrue(ground_truth_enabled(disabled))
        for invalid in (None, 0, 1, '', 'yes'):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                ground_truth_enabled(invalid)

    def test_no_map_or_missing_map_never_falls_back(self):
        for source in ('', ' ', None, '/nonexistent/fishbot-test-map.yaml'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                readable_map(source)

    def test_explicit_map_requires_a_readable_nonempty_image(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            source = directory/'map.yaml'
            source.write_text('image: map.pgm\nresolution: 0.05\norigin: [0, 0, 0]\n')
            with self.assertRaises(ValueError):
                readable_map(source)
            image = directory/'map.pgm'
            image.touch()
            with self.assertRaises(ValueError):
                readable_map(source)
            image.write_bytes(b'P5\n1 1\n255\n\xfe')
            self.assertEqual(readable_map(source), str(source.resolve()))
            with patch.object(Path, 'open', side_effect=PermissionError('unreadable')):
                with self.assertRaises(ValueError):
                    readable_map(source)

    def test_map_yaml_must_contain_image_not_a_scalar_or_empty_key(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'map.yaml'
            for text in ('[]', 'null', 'image: null', 'image: ""', 'image: [broken'):
                source.write_text(text)
                with self.subTest(text=text), self.assertRaises(ValueError):
                    readable_map(source)

    def test_launch_applies_amcl_owner_and_domain_before_node_actions(self):
        """Exercise the actual launch setup with inert action constructors."""
        path = Path(__file__).resolve().parents[1]/'launch/light_sim.launch.py'
        tree = ast.parse(path.read_text())
        setup = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'setup')
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory/'urdf').mkdir()
            (directory/'urdf/fishbot.urdf').write_text('<robot name="fixture"/>')
            (directory/'map.pgm').write_bytes(b'P5\n1 1\n255\n\xfe')
            source = directory/'map.yaml'
            source.write_text('image: map.pgm\n')
            values = {'ros_domain_id': '94', 'map': str(source), 'use_amcl': 'true',
                      'sim_config': 'fixture-config.yaml', 'params_file': 'nav.yaml',
                      'nav': 'true', 'rviz': 'false'}
            class Configuration:
                def __init__(self, name):
                    self.name = name
                def perform(self, _context):
                    return values[self.name]
            made_nodes = []
            def node(**kwargs):
                made_nodes.append(kwargs)
                return kwargs
            namespace = dict(
                os=__import__('os'), LaunchConfiguration=Configuration,
                get_package_share_directory=lambda _name: str(directory),
                simulation_environment=simulation_environment, readable_map=readable_map,
                ground_truth_enabled=ground_truth_enabled, Node=node,
                SetEnvironmentVariable=lambda key, value: (key, value),
                IfCondition=lambda config: config.perform(None),
                PythonLaunchDescriptionSource=lambda path: path,
                IncludeLaunchDescription=lambda *args, **kwargs: ('navigation', kwargs))
            exec(compile(ast.Module(body=[setup], type_ignores=[]), str(path), 'exec'), namespace)
            for amcl, truth in [('true', False), ('false', True)]:
                made_nodes.clear()
                values['use_amcl'] = amcl
                actions = namespace['setup'](None)
                self.assertEqual(actions[:5], list(simulation_environment('94').items()))
                sim = next(n for n in made_nodes if n['package'] == 'fishbot_light_sim')
                self.assertIs(sim['parameters'][-1]['ground_truth_localization'], truth)
                amcl_node = next(n for n in made_nodes if n['package'] == 'nav2_amcl')
                self.assertEqual(amcl_node['condition'], amcl)
            for changes in ({'ros_domain_id': '0'}, {'map': ''}, {'use_amcl': 'invalid'}):
                made_nodes.clear()
                previous = dict(values)
                values.update(changes)
                with self.assertRaises(ValueError):
                    namespace['setup'](None)
                self.assertEqual(made_nodes, [])
                values.clear()
                values.update(previous)


if __name__ == '__main__':
    unittest.main()
