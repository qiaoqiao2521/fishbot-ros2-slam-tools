"""Mission HTTP contract, without a ROS node, executor or native dispatch."""
from concurrent.futures import Future
import http.client
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(SCRIPTS))
from mission_bridge import LocalHTTPServer, MissionBridge, MissionRecord
from fishbot_runtime import INSTANCE_HEADER, RUNTIME_CHANGED, ExecutionOwnerBusy


class MissionRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.bridge = SimpleNamespace(domain=122,
            lock=threading.RLock(), mission=MissionRecord(),
            state=Mock(side_effect=AssertionError('discovery must not assemble state')), enqueue=Mock())
        self.bridge.task_record = MethodType(MissionBridge.task_record, self.bridge)
        future = Future()
        future.set_result((202, {'mission': {'id': 'same-original', 'dispatch_state': 'pending'}}))
        self.bridge.enqueue.return_value = future
        with patch('mission_bridge.RvizDesktop'):
            self.server = LocalHTTPServer(0, self.bridge, ui_port=5180)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path, body=None, headers=None, method=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=2)
        data = None if body is None else json.dumps(body).encode()
        connection.request(method or ('GET' if body is None else 'POST'), path, data,
                           {'Content-Type': 'application/json', **(headers or {})})
        response = connection.getresponse()
        data = response.read()
        result = response.status, dict(response.getheaders()), json.loads(data) if data else None
        connection.close()
        return result

    def test_discovery_has_no_guessed_scene_and_never_calls_ros_state(self):
        code, headers, value = self.request('/sim-api/runtime')
        self.assertEqual(code, 200)
        self.assertEqual((value['service'], value['domain'], value['mode']), ('mission', 122, 'simulation'))
        self.assertIsNone(value['scene_id'])
        self.assertIsNone(value['episode_id'])
        self.assertTrue(value['capabilities'][0]['task_lookup'])
        self.assertFalse(value['capabilities'][1]['task_lookup'])
        self.assertEqual(headers[INSTANCE_HEADER], value['instance_id'])
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.bridge.state.assert_not_called()
        self.bridge.enqueue.assert_not_called()

    def test_original_task_lookup_is_read_only_and_retains_response_identity(self):
        task_id = 'd44b9ba6-ac8e-49dc-83c4-86caf4a14390'
        self.bridge.mission.begin([{'x': 1., 'y': 1., 'yaw': 0.}], False, mission_id=task_id)
        self.bridge.mission.value.update(runtime_instance_id=self.server.runtime.instance_id,
                                        map_id='original-map', native_goal_id='a' * 32)
        code, headers, value = self.request('/sim-api/tasks/' + task_id + '?map_id=original-map',
                                            headers={INSTANCE_HEADER: 'old-instance'})
        self.assertEqual(code, 200)
        self.assertEqual(headers[INSTANCE_HEADER], self.server.runtime.instance_id)
        self.assertEqual(value['source'], 'current')
        self.assertEqual(value['task_id'], task_id)
        self.assertEqual(value['runtime_instance_id'], self.server.runtime.instance_id)
        self.assertEqual(value['mission']['native_goal_id'], 'a' * 32)
        self.bridge.state.assert_not_called()
        self.bridge.enqueue.assert_not_called()

    def test_task_lookup_errors_do_not_return_another_latest_task(self):
        task_id = 'd44b9ba6-ac8e-49dc-83c4-86caf4a14390'
        self.bridge.mission.begin([{'x': 1., 'y': 1., 'yaw': 0.}], False, mission_id=task_id)
        self.bridge.mission.value.update(runtime_instance_id=self.server.runtime.instance_id,
                                        map_id='original-map')
        for suffix, status in ((task_id + '?map_id=wrong-map', 409),
                ('db7de024-1f05-4b78-8d6f-088e94f4eae9', 404), ('not-uuid', 400),
                (task_id.upper(), 400), (task_id + '/', 400),
                (task_id + '?map_id=original-map&map_id=wrong-map', 400),
                (task_id + '?map_id=', 400), (task_id + '?task_id=another', 400)):
            with self.subTest(suffix=suffix):
                code, headers, value = self.request('/sim-api/tasks/' + suffix)
                self.assertEqual(code, status)
                self.assertNotIn('mission', value)
                self.assertEqual(headers[INSTANCE_HEADER], self.server.runtime.instance_id)
                self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(self.bridge.mission.value['id'], task_id)
        self.bridge.enqueue.assert_not_called()

    def test_execution_lock_conflict_refuses_before_ros_initialization(self):
        import mission_bridge
        with patch.object(sys, 'argv', ['mission_bridge.py']), \
                patch.object(mission_bridge, 'simulation_domain', return_value=122), \
                patch.object(mission_bridge, 'DomainExecutionLock', side_effect=ExecutionOwnerBusy('domain occupied')), \
                patch.object(mission_bridge.rclpy, 'init') as initialize, patch.object(mission_bridge, 'run_server') as run:
            with self.assertRaisesRegex(SystemExit, 'domain occupied'):
                mission_bridge.main()
        initialize.assert_not_called()
        run.assert_not_called()

    def test_stale_mutations_reject_before_queue_or_rviz_but_legacy_remains(self):
        for endpoint in ('mission', 'cancel', 'obstacle', 'map-rules', 'routes', 'rviz'):
            code, headers, body = self.request('/sim-api/' + endpoint, {}, {INSTANCE_HEADER: 'old'})
            self.assertEqual((code, body), (409, RUNTIME_CHANGED))
            self.assertEqual(headers[INSTANCE_HEADER], self.server.runtime.instance_id)
        self.bridge.enqueue.assert_not_called()
        self.server.rviz.open.assert_not_called()
        for supplied in ({}, {INSTANCE_HEADER: self.server.runtime.instance_id}):
            code, headers, body = self.request('/sim-api/mission', {}, supplied)
            self.assertEqual(code, 202)
            self.assertEqual(body['mission']['dispatch_state'], 'pending')
        self.assertEqual(self.bridge.enqueue.call_count, 2)

    def test_errors_and_preflight_preserve_discovery_header_contract(self):
        for path, headers, expected in (('/sim-api/missing', {}, 404),
                                         ('/sim-api/runtime', {'Host': 'evil.example'}, 403)):
            code, response_headers, _ = self.request(path, headers=headers)
            self.assertEqual(code, expected)
            self.assertEqual(response_headers[INSTANCE_HEADER], self.server.runtime.instance_id)
            self.assertEqual(response_headers['Cache-Control'], 'no-store')
        code, headers, _ = self.request('/sim-api/mission', method='OPTIONS',
            headers={'Origin': 'http://127.0.0.1:5180', 'Access-Control-Request-Headers': INSTANCE_HEADER})
        self.assertEqual(code, 204)
        self.assertIn(INSTANCE_HEADER.lower(), headers['Access-Control-Allow-Headers'].lower())

    def test_colcon_sibling_helper_import_does_not_depend_on_checkout_or_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory) / 'lib' / 'fishbot_mujoco'
            installed.mkdir(parents=True)
            for name in ('mission_bridge.py', 'map_rules.py', 'wait_ready.py', 'rviz_desktop.py'):
                shutil.copyfile(SCRIPTS / name, installed / name)
            for name in ('fishbot_runtime.py', 'fishbot_manual_lease.py', 'fishbot_manual_profile.py',
                         'fishbot_manual_ros.py', 'cooperation_core.py'):
                shutil.copyfile(ROOT / 'tools' / name, installed / name)
            code = ('import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); '
                    'import mission_bridge, fishbot_runtime; '
                    'assert Path(fishbot_runtime.__file__).parent == Path(sys.argv[1])')
            completed = subprocess.run([sys.executable, '-B', '-c', code, str(installed)],
                cwd=directory, capture_output=True, text=True, timeout=10)
            self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == '__main__':
    unittest.main()
