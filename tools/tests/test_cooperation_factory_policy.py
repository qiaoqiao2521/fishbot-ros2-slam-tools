"""Policy software contracts; no ROS, physical stepping or MuJoCo compilation."""
import argparse
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cooperation_factory as factory
import cooperation_factory_policy as policy


def scene():
    return {'scene_profile': {'schema': 1, 'vehicle': 'fishbot', 'sensors': 'planar',
                              'task': 'transport'}, 'world_xml': '/prepared/world.xml',
            'factory_delivery': {'schema': 1, 'id': 'occupied-contract',
                'destinations': [{'id': 'a', 'pose': {'x': 0., 'y': -2., 'yaw': 0.}},
                                 {'id': 'b', 'pose': {'x': .7, 'y': -2., 'yaw': 0.}}],
                'orders': [{'id': 'order-a', 'destination_id': 'a'},
                           {'id': 'order-b', 'destination_id': 'b'}],
                'channel': {'occupied': True, 'obstacle': {'center_m': [.35, -2.1, .25],
                    'size_m': [.12, .3, .5], 'yaw_rad': 0.}}}}


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.manifest = self.folder/'prepared.json'
        self.manifest.write_text(json.dumps(scene()))
        self.config = self.folder/'policy.json'
        self.module = self.folder/'custom.py'
        self.imported = self.folder/'imported'
        self.called = self.folder/'called'
        self.output = self.folder/'derived.json'
        self.receipt = self.folder/'receipt.json'
        self.geometry = Mock()
        self.geometry.return_value.check_pose.return_value = {
            'passed': True, 'scope': 'static_delivery_goal_original_geometry_and_scene_bounds',
            'path_validated': False, 'arrival_validated': False}

    def custom(self, body="return context['parameters']['egress_pose']"):
        self.module.write_text(
            'from pathlib import Path\n'
            f'Path({str(self.imported)!r}).write_text("imported")\n'
            'def select_egress(context):\n'
            f'    target = Path({str(self.called)!r})\n'
            '    target.write_text(target.read_text()+"1" if target.exists() else "1")\n'
            f'    {body}\n')
        self.config.write_text(json.dumps({'schema': 1,
            'entrypoint': {'module_path': 'custom.py', 'function': 'select_egress'},
            'parameters': {'egress_pose': {'x': 0., 'y': -2.7, 'yaw': 0.}}}))

    def materialize(self):
        return policy.materialize(self.manifest, self.config, self.output, self.receipt,
                                  geometry_factory=self.geometry)

    def test_actual_custom_function_called_once_and_derived_manifest_preserves_prepared(self):
        self.custom()
        before = self.manifest.read_text()
        derived, receipt = self.materialize()
        self.assertEqual(self.called.read_text(), '1')
        self.assertEqual(receipt['actual_entrypoint']['module_file'], str(self.module.resolve()))
        self.assertEqual(receipt['actual_entrypoint']['function'], 'select_egress')
        self.assertTrue(receipt['function_invoked'])
        self.assertTrue(receipt['call_completed'])
        self.assertEqual(receipt['input_context']['factory_delivery']['channel']['occupied'], True)
        self.assertEqual(receipt['returned_value'], {'x': 0., 'y': -2.7, 'yaw': 0.})
        self.assertEqual(derived['egress_pose'], receipt['selected_egress_pose'])
        self.geometry.return_value.check_pose.assert_called_once_with(derived['egress_pose'])
        self.assertFalse(receipt['point_geometry']['path_validated'])
        self.assertEqual(json.loads(self.output.read_text())['egress_pose'], derived['egress_pose'])
        self.assertEqual(self.manifest.read_text(), before)

    def test_builtin_direct_removes_optional_map_via_without_compiling_geometry(self):
        value = scene()
        value['egress_pose'] = {'x': -.9, 'y': -1.8, 'yaw': 0.}
        self.manifest.write_text(json.dumps(value))
        self.config.write_text(json.dumps({'schema': 1, 'entrypoint': {'builtin': 'direct'}}))
        derived, receipt = self.materialize()
        self.assertNotIn('egress_pose', derived)
        self.assertIsNone(receipt['returned_value'])
        self.assertEqual(receipt['actual_entrypoint']['function'], 'direct')
        self.geometry.assert_not_called()

    def test_builtin_declared_via_uses_original_pose_and_point_geometry_contract(self):
        self.config.write_text(json.dumps({'schema': 1,
            'entrypoint': {'builtin': 'declared_via'},
            'parameters': {'egress_pose': {'x': 0, 'y': -3, 'yaw': 0}}}))
        derived, receipt = self.materialize()
        self.assertEqual(derived['egress_pose'], {'x': 0., 'y': -3., 'yaw': 0.})
        self.assertEqual(receipt['actual_entrypoint']['function'], 'declared_via')
        self.assertFalse(receipt['arrival_validated'])

    def test_invalid_pose_or_function_exception_preserves_failure_without_baseline(self):
        for body, stage in (("return {'x': 0, 'y': float('nan'), 'yaw': 0}", 'pose_validation'),
                            ('return [0, -2.7, 0]', 'pose_validation'),
                            ("raise RuntimeError('selected policy broke')", 'call')):
            with self.subTest(body=body):
                self.custom(body)
                with self.assertRaises(policy.PolicyError):
                    self.materialize()
                receipt = json.loads(self.receipt.read_text())
                self.assertEqual(receipt['execution_status'], 'failed')
                self.assertEqual(receipt['stage'], stage)
                self.assertTrue(receipt['function_invoked'])
                self.assertTrue(receipt['failure_reason'])
                self.assertFalse(self.output.exists())

    def test_point_collision_is_not_replaced_with_direct_success(self):
        self.custom()
        self.geometry.return_value.check_pose.return_value = {
            'passed': False, 'reason': 'original_geometry_collision', 'path_validated': False}
        with self.assertRaises(policy.PolicyError):
            self.materialize()
        receipt = json.loads(self.receipt.read_text())
        self.assertEqual(receipt['stage'], 'geometry')
        self.assertIn('original_geometry_collision', receipt['failure_reason'])
        self.assertFalse(self.output.exists())

    def test_j100_or_body_motion_rejected_before_importing_arbitrary_module(self):
        self.custom()
        for variant in ('jackal_j100', 'body-motion'):
            value = scene()
            if variant == 'jackal_j100':
                value['scene_profile']['vehicle'] = variant
            else:
                value['egress_motion'] = {'type': 'drive_on_heading'}
            self.manifest.write_text(json.dumps(value))
            with self.subTest(variant=variant), self.assertRaises(policy.PolicyError):
                self.materialize()
            self.assertFalse(self.imported.exists())
            self.assertFalse(self.called.exists())
            self.assertFalse(self.output.exists())

    def test_public_j100_policy_rejected_before_runtime_and_without_outputs(self):
        self.custom()
        value = scene()
        value['scene_profile']['vehicle'] = 'jackal_j100'
        self.manifest.write_text(json.dumps(value))
        output = self.folder/'not-created'
        with (patch.object(factory, 'run', side_effect=AssertionError('runtime invoked')),
              contextlib.redirect_stdout(io.StringIO()) as stream):
            code = factory.main(['run', '--manifest', str(self.manifest), '--output', str(output),
                                 '--policy-config', str(self.config)])
        self.assertEqual(code, 2)
        self.assertIn('J100', json.loads(stream.getvalue())['error'])
        self.assertFalse(output.exists())
        self.assertFalse(self.imported.exists())

    def test_actual_software_worker_calls_custom_direct_function_without_ros_or_geometry(self):
        self.custom('return None')
        process = subprocess.run([sys.executable, '-B', str(Path(policy.__file__)),
            '--manifest', str(self.manifest), '--config', str(self.config),
            '--output-manifest', str(self.output), '--receipt', str(self.receipt)],
            text=True, capture_output=True, timeout=5)
        self.assertEqual(process.returncode, 0, process.stderr)
        receipt = json.loads(self.receipt.read_text())
        self.assertEqual(self.called.read_text(), '1')
        self.assertEqual(receipt['actual_entrypoint']['module_file'], str(self.module.resolve()))
        self.assertFalse(receipt['adapter_initializes_ROS'])
        self.assertFalse(receipt['point_geometry']['required'])
        self.assertNotIn('egress_pose', json.loads(self.output.read_text()))

    def test_dry_run_and_report_do_not_import_or_invoke_selected_function(self):
        self.custom("raise RuntimeError('must not execute')")
        output = self.folder/'run'
        stream = io.StringIO()
        with (patch.object(factory, 'run', side_effect=AssertionError('runtime invoked')),
              patch.object(factory, 'loaded_code_reference', return_value={}),
              contextlib.redirect_stdout(stream)):
            code = factory.main(['run', '--manifest', str(self.manifest), '--output', str(output),
                                 '--policy-config', str(self.config), '--dry-run'])
        self.assertEqual(code, 0)
        request = json.loads(stream.getvalue())['declaration']['policy_request']
        self.assertEqual(request['execution_status'], 'not_executed')
        self.assertFalse(request['selected_module_imported'])
        self.assertFalse(request['function_invoked'])
        self.assertFalse(output.exists())
        output.mkdir()
        (output/'result.json').write_text(json.dumps({
            'declaration': factory.reference(scene(), candidate='display-label'),
            'orders': [], 'errors': [], 'execution': {}, 'policy': request}))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(factory.main(['report', '--run', str(output)]), 1)
        self.assertFalse(self.imported.exists())
        self.assertFalse(self.called.exists())

    def test_derived_egress_is_consumed_by_original_launch_manifest_argument(self):
        self.custom()
        output = self.folder/'run'
        arguments = argparse.Namespace(output=output, manifest=self.manifest, domain=141, port=19111,
            planning_python=Path(sys.executable), protected_unit=None, policy_config=self.config)
        commands = []
        class Process:
            pid = 999999999
            def __init__(self, code): self.returncode = code
            def wait(self, timeout=None): return self.returncode
            def poll(self): return self.returncode
        def popen(command, **unused):
            commands.append(command)
            if 'cooperation_factory_policy.py' in command[2]:
                get = lambda key: Path(command[command.index(key)+1])
                policy.materialize(get('--manifest'), get('--config'), get('--output-manifest'),
                                   get('--receipt'), geometry_factory=self.geometry)
                return Process(0)
            if 'cooperation_geometry_check.py' in command[2]:
                Path(command[command.index('--output')+1]).write_text('{"passed": true}')
                return Process(0)
            return Process(None)
        with (patch.dict(os.environ), patch('fishbot_simulation_suite.domain_is_empty'),
              patch.object(factory, 'ensure_port_available'),
              patch.object(factory, 'protected_snapshot', return_value={}),
              patch.object(factory, 'loaded_code_reference', return_value={'selected_source_text': {}}),
              patch.object(factory.subprocess, 'Popen', side_effect=popen),
              patch.object(factory, 'ReadOnlyMonitor', side_effect=RuntimeError('stop before ROS boundary')),
              patch.object(factory, 'stop_non_motion_child', return_value=[]),
              patch.object(factory.socket, 'socket') as socket):
            socket.return_value.__enter__.return_value.connect_ex.return_value = 111
            result = factory.run(arguments, scene(), factory.reference(scene(), candidate='label-only'))
        self.assertEqual(self.called.read_text(), '1')
        runtime = output/'derived-manifest.json'
        self.assertEqual(json.loads(runtime.read_text())['egress_pose'], {'x': 0., 'y': -2.7, 'yaw': 0.})
        launch = next(command for command in commands if len(command) > 1 and command[1] == 'run')
        self.assertIn('manifest:='+str(runtime.resolve()), launch)
        geometry = next(command for command in commands if 'cooperation_geometry_check.py' in command[2])
        self.assertEqual(geometry[geometry.index('--manifest')+1], str(runtime.resolve()))
        self.assertEqual(result['manifest'], str(runtime.resolve()))
        self.assertFalse(result['passed'])  # This contract test never ran the physical task.


if __name__ == '__main__':
    unittest.main()
