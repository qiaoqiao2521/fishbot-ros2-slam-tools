"""Real ephemeral HTTP fixtures; discovery and fences never dispatch ROS."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import threading
import unittest
from email.message import Message
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fishbot_runtime import (INSTANCE_HEADER, RUNTIME_CHANGED, RuntimeIdentity, capability,
                            DomainExecutionLock, ExecutionOwnerBusy)
from fishbot_voice_bridge import make_server as voice_server
from cooperation_bridge import make_server as cooperation_server


class HTTPFixture:
    def __init__(self, server):
        self.server = server
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)
        self.thread.start()

    def request(self, path, body=None, headers=None, method=None):
        data = None if body is None else json.dumps(body).encode()
        request = Request(f'http://127.0.0.1:{self.server.server_port}{path}', data=data,
                          headers={'Content-Type': 'application/json', **(headers or {})}, method=method)
        try:
            response = urlopen(request, timeout=2)
        except HTTPError as error:
            response = error
        with response:
            data = response.read()
            return response.status, response.headers, json.loads(data) if data else None

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class RuntimeIdentityTests(unittest.TestCase):
    def test_identity_is_stable_per_server_and_copies_do_not_mutate_contract(self):
        caps = [capability('navigation', 'native_action', cancel=True)]
        runtime = RuntimeIdentity('mission', 'simulation', 122, caps)
        one = runtime.snapshot()
        two = runtime.snapshot()
        self.assertEqual(one, two)
        self.assertIsNone(one['scene_id'])
        self.assertIsNone(one['episode_id'])
        caps[0]['cancel'] = False
        one['capabilities'][0]['task_lookup'] = True
        self.assertTrue(runtime.snapshot()['capabilities'][0]['cancel'])
        self.assertFalse(runtime.snapshot()['capabilities'][0]['task_lookup'])
        other = RuntimeIdentity('mission', 'simulation', 122, [])
        self.assertNotEqual(runtime.instance_id, other.instance_id)

    def test_optional_fence_rejects_empty_stale_and_duplicate_headers(self):
        runtime = RuntimeIdentity('station', 'unknown', None, [])
        self.assertTrue(runtime.accepts(Message()))
        for values, expected in (([runtime.instance_id], True), (['old'], False), ([''], False),
                                 ([runtime.instance_id, runtime.instance_id], False)):
            headers = Message()
            for value in values:
                headers[INSTANCE_HEADER] = value
            self.assertEqual(runtime.accepts(headers), expected)
        for domain in (True, -1, 233, '121'):
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                RuntimeIdentity('voice', 'simulation', domain, [])


class ExecutionOwnershipTests(unittest.TestCase):
    def test_same_domain_conflicts_without_changing_original_owner_or_lock_inode(self):
        with tempfile.TemporaryDirectory() as directory:
            with DomainExecutionLock(122, 'mission', directory=directory):
                filename = Path(directory) / 'domain-122.lock'
                before, inode = filename.read_bytes(), filename.stat().st_ino
                with self.assertRaisesRegex(ExecutionOwnerBusy, 'existing owner unchanged'):
                    with DomainExecutionLock(122, 'cooperation', directory=directory):
                        self.fail('A second execution owner acquired the same domain')
                self.assertEqual(filename.read_bytes(), before)
                with DomainExecutionLock(123, 'cooperation', directory=directory):
                    self.assertTrue((Path(directory) / 'domain-123.lock').is_file())
            with DomainExecutionLock(122, 'cooperation', directory=directory):
                self.assertEqual(filename.stat().st_ino, inode)
                self.assertEqual(json.loads(filename.read_bytes())['owner'], 'cooperation')

    def test_separate_process_conflicts_and_kernel_releases_lock_after_exit(self):
        code = ('import sys;sys.path.insert(0,sys.argv[1]);'
                'from fishbot_runtime import DomainExecutionLock;'
                'lock=DomainExecutionLock(122,"mission",directory=sys.argv[2]);'
                'lock.__enter__();print("READY",flush=True);sys.stdin.buffer.read(1)')
        with tempfile.TemporaryDirectory() as directory:
            child = subprocess.Popen([sys.executable, '-B', '-c', code, str(Path(__file__).resolve().parents[1]), directory],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertTrue(select.select([child.stdout], [], [], 3)[0], 'Child did not acquire its lock')
                self.assertEqual(child.stdout.readline().strip(), 'READY')
                with self.assertRaises(ExecutionOwnerBusy):
                    with DomainExecutionLock(122, 'cooperation', directory=directory):
                        self.fail('A second process acquired a held domain')
                child.terminate()
                child.wait(timeout=3)
                with DomainExecutionLock(122, 'cooperation', directory=directory):
                    pass
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=3)

    def test_default_namespace_is_independent_of_output_cwd_and_environment(self):
        one = DomainExecutionLock(122, 'mission')
        with patch.dict(os.environ, {'XDG_CACHE_HOME': '/not-used', 'XDG_RUNTIME_DIR': '/also-not-used'}):
            two = DomainExecutionLock(122, 'cooperation')
        self.assertEqual(one.directory, two.directory)
        self.assertEqual(one.directory, Path('/tmp') / f'fishbot-execution-{os.getuid()}')
        with self.assertRaises(ValueError):
            DomainExecutionLock(122, 'voice')

    def test_cooperation_conflict_refuses_before_native_run_or_ros_import(self):
        import cooperation_bridge
        with patch.object(sys, 'argv', ['cooperation_bridge.py', '--domain', '122',
                '--manifest', '/not-read', '--output', '/not-written', '--frame-dir', '/not-read']), \
                patch.dict(os.environ), patch.object(cooperation_bridge, 'DomainExecutionLock',
                side_effect=ExecutionOwnerBusy('domain occupied')), patch.object(cooperation_bridge, 'run') as run:
            with self.assertRaisesRegex(SystemExit, 'domain occupied'):
                cooperation_bridge.main()
        run.assert_not_called()


class VoiceDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.bridge = SimpleNamespace(domain=121, clock=lambda: 100.,
            state=Mock(side_effect=AssertionError('runtime must not poll upstream')),
            execute=Mock(return_value={'status': 'rejected', 'accepted': False}),
            preview=Mock(return_value={'status': 'preview'}), transcribe=Mock())
        self.fixture = HTTPFixture(voice_server(self.bridge, 0, ['http://127.0.0.1:5180']))

    def tearDown(self):
        self.fixture.close()

    def test_runtime_is_local_only_and_get_never_checks_an_upstream(self):
        code, headers, body = self.fixture.request('/voice-api/runtime')
        self.assertEqual(code, 200)
        self.assertEqual(body['service'], 'voice')
        self.assertEqual(body['domain'], 121)
        self.assertEqual(body['mode'], 'simulation')
        self.assertIsNone(body['scene_id'])
        self.assertIsNone(body['episode_id'])
        self.assertEqual(headers[INSTANCE_HEADER], body['instance_id'])
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertFalse(body['capabilities'][0]['task_lookup'])
        self.bridge.state.assert_not_called()
        self.bridge.execute.assert_not_called()
        code, headers, _ = self.fixture.request('/voice-api/runtime', headers={'Host': 'evil.example'})
        self.assertEqual(code, 403)
        self.assertEqual(headers[INSTANCE_HEADER], body['instance_id'])

    def test_stale_post_never_reaches_adapter_and_legacy_or_matching_still_work(self):
        instance = self.fixture.server.runtime.instance_id
        code, headers, body = self.fixture.request('/voice-api/execute', {}, {INSTANCE_HEADER: 'old'})
        self.assertEqual((code, body), (409, RUNTIME_CHANGED))
        self.assertEqual(headers[INSTANCE_HEADER], instance)
        self.bridge.execute.assert_not_called()
        for supplied in ({}, {INSTANCE_HEADER: instance}):
            self.assertEqual(self.fixture.request('/voice-api/execute', {}, supplied)[0], 200)
        self.assertEqual(self.bridge.execute.call_count, 2)
        code, headers, _ = self.fixture.request('/voice-api/missing')
        self.assertEqual(code, 404)
        self.assertEqual(headers[INSTANCE_HEADER], instance)
        self.assertEqual(headers['Cache-Control'], 'no-store')

    def test_preflight_allows_fence_and_cors_exposes_response_identity(self):
        code, headers, _ = self.fixture.request('/voice-api/execute', method='OPTIONS',
            headers={'Origin': 'http://127.0.0.1:5180', 'Access-Control-Request-Headers': INSTANCE_HEADER})
        self.assertEqual(code, 204)
        self.assertIn(INSTANCE_HEADER.lower(), headers['Access-Control-Allow-Headers'].lower())
        _, headers, _ = self.fixture.request('/voice-api/runtime', headers={'Origin': 'http://127.0.0.1:5180'})
        self.assertIn(INSTANCE_HEADER.lower(), headers['Access-Control-Expose-Headers'].lower())


class CooperationDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.bridge = SimpleNamespace(episode_id='episode-one',
            state=Mock(side_effect=AssertionError('runtime must not assemble physics')),
            start=Mock(return_value={'task_id': 'one'}), cancel=Mock(return_value={'task_id': 'one'}),
            reset_episode=Mock(return_value={'status': 'pending'}))
        self.runtime = RuntimeIdentity('cooperation', 'simulation', 122,
            [capability('transport', 'native_action', cancel=True, event_history='bounded')], scene_id='a' * 64)
        args = SimpleNamespace(port=0, output=Path(self.temporary.name) / 'tasks')
        self.fixture = HTTPFixture(cooperation_server(self.bridge, args, runtime=self.runtime))

    def tearDown(self):
        self.fixture.close()
        self.temporary.cleanup()

    def test_runtime_reports_actual_scene_and_current_episode_without_physics_work(self):
        code, headers, value = self.fixture.request('/coop-api/runtime')
        self.assertEqual(code, 200)
        self.assertEqual((value['domain'], value['scene_id'], value['episode_id']),
                         (122, 'a' * 64, 'episode-one'))
        self.assertEqual(headers[INSTANCE_HEADER], value['instance_id'])
        self.bridge.state.assert_not_called()
        self.bridge.episode_id = 'episode-two'
        _, _, after = self.fixture.request('/coop-api/runtime')
        self.assertEqual(after['instance_id'], value['instance_id'])
        self.assertEqual(after['episode_id'], 'episode-two')

    def test_stale_start_cancel_reset_all_reject_before_owner_and_errors_have_identity(self):
        for path, method in (('start', self.bridge.start), ('cancel', self.bridge.cancel),
                             ('reset', self.bridge.reset_episode)):
            code, headers, body = self.fixture.request('/coop-api/' + path, {}, {INSTANCE_HEADER: 'old'})
            self.assertEqual((code, body), (409, RUNTIME_CHANGED))
            self.assertEqual(headers[INSTANCE_HEADER], self.runtime.instance_id)
            method.assert_not_called()
            for supplied in ({}, {INSTANCE_HEADER: self.runtime.instance_id}):
                self.assertEqual(self.fixture.request('/coop-api/' + path, {}, supplied)[0], 200)
            self.assertEqual(method.call_count, 2)
        self.bridge.start.side_effect = RuntimeError('fixture failed')
        code, headers, body = self.fixture.request('/coop-api/start', {})
        self.assertEqual(code, 500)
        self.assertEqual(body['outcome'], 'unknown')
        self.assertEqual(headers[INSTANCE_HEADER], self.runtime.instance_id)
        self.assertEqual(headers['Cache-Control'], 'no-store')


if __name__ == '__main__':
    unittest.main()
