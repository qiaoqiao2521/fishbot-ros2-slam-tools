"""Real pipes/processes with frozen Scene methods; the child never imports Gazebo."""
import asyncio
import concurrent.futures
from contextlib import redirect_stderr
import io
import json
import math
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

import test_drone_command_validity as original
from test_drone_command_revalidation_patch import REPAIR, apply, copy_source
from test_drone_recovery_cache_chain import RecoveryHarness


SCENE_PATCH = REPAIR.parent/'drone-scene-worker-deadline.patch'
WORKER = '''import json, os, pathlib, signal, sys, time
mode, marker = sys.argv[1:]
marker = pathlib.Path(marker)
if mode.startswith('ignore_term'):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
marker.write_text('started')
if mode in ('no_input', 'ignore_term_no_input'):
    time.sleep(20)
for line in sys.stdin:
    request = json.loads(line)
    marker.write_text(json.dumps(request))
    if mode in ('silent', 'ignore_term'):
        time.sleep(20)
    if mode == 'partial':
        sys.stdout.write('{"ok":true')
        sys.stdout.flush()
        time.sleep(20)
    if mode == 'eof':
        os.close(1)
        time.sleep(20)
    if mode == 'bad_json':
        response = '{bad}\\n'
    elif mode == 'bad_hex':
        response = json.dumps({'ok': True, 'response': 'zz'})+'\\n'
    elif mode == 'error':
        response = json.dumps({'error': 'fixture worker error'})+'\\n'
    else:
        response = json.dumps({'ok': True, 'response': request['request']})+'\\n'
    if mode == 'fragmented':
        sys.stdout.write(response[:10])
        sys.stdout.flush()
        time.sleep(.01)
        response = response[10:]
    sys.stdout.write(response)
    sys.stdout.flush()
'''


class Message:
    DESCRIPTOR = types.SimpleNamespace(full_name='fixture.Boolean')

    def __init__(self, payload=b'1', **kwargs):
        self.payload, self.data = payload, None

    def SerializeToString(self):
        return self.payload

    def ParseFromString(self, payload):
        self.payload, self.data = payload, payload == b'1'


class SceneHarness:
    def __init__(self, root, source, enabled=True, mode='normal'):
        self.root, self.mode, self.processes, self.launches = root, mode, [], []
        (root/'worker.py').write_text(WORKER)
        namespace = dict(json=json, math=math, os=os, select=select, sys=sys,
            time=time, Path=Path, threading=threading, obstacle_records=lambda _: [],
            __file__=str(source), subprocess=types.SimpleNamespace(
                Popen=self.spawn, PIPE=subprocess.PIPE, TimeoutExpired=subprocess.TimeoutExpired))
        names = ['__init__', 'request', 'close', 'pause']
        if '_request_with_deadline' in source.read_text():
            names += ['_request_with_deadline', '_close_request_worker']
        methods = original.methods(source, 'Scene', names, namespace)
        cls = type('ExtractedScene', (), methods)
        with patch.dict(os.environ, {'DRONE_REVALIDATE_COMMAND': '1' if enabled else '0'}):
            self.scene = cls('fixture', [], types.SimpleNamespace(), root)

    def spawn(self, argv, **kwargs):
        self.launches.append(kwargs.copy())
        marker = self.root/('worker-'+str(len(self.processes))+'.json')
        child = subprocess.Popen([sys.executable, '-u', str(self.root/'worker.py'),
                                  self.mode, str(marker)], stderr=subprocess.DEVNULL, **kwargs)
        self.processes.append(child)
        return child

    def request(self, payload=b'1', timeout=1):
        return self.scene.request('/fixture', Message(payload), Message, Message, timeout)

    def cleanup(self):
        for child in self.processes:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=2.)
            for stream in (child.stdin, child.stdout):
                if stream and not stream.closed:
                    stream.close()


class SceneWorkerDeadline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        shutil.copyfile(original.DRONE/'scene.py', cls.root/'scene.py')
        apply(cls.root, SCENE_PATCH)
        compile((cls.root/'scene.py').read_text(), str(cls.root/'scene.py'), 'exec')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def harness(self, original_source=False, **kwargs):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        source = original.DRONE/'scene.py' if original_source else self.root/'scene.py'
        h = SceneHarness(Path(directory.name), source, **kwargs)
        self.addCleanup(h.cleanup)
        return h

    def assert_reaped(self, h):
        self.assertTrue(h.processes)
        self.assertTrue(all(child.poll() is not None for child in h.processes))
        self.assertTrue(all(child.stdin.closed and child.stdout.closed for child in h.processes))
        self.assertIsNone(h.scene.worker)

    def test_original_silent_and_half_line_worker_stall_until_explicit_cleanup(self):
        for mode in ('silent', 'partial'):
            with self.subTest(mode=mode):
                h = self.harness(original_source=True, mode=mode)
                pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                pending = pool.submit(h.request)
                try:
                    deadline = time.monotonic()+2.
                    marker = h.root/'worker-0.json'
                    while time.monotonic() < deadline:
                        if marker.exists() and marker.read_text().startswith('{'):
                            break
                        time.sleep(.01)
                    self.assertTrue(marker.read_text().startswith('{'))
                    with self.assertRaises(concurrent.futures.TimeoutError):
                        pending.result(timeout=.1)
                    self.assertIsNone(h.processes[0].poll())
                finally:
                    for child in h.processes:
                        if child.poll() is None:
                            child.kill()
                    with self.assertRaises((RuntimeError, json.JSONDecodeError)):
                        pending.result(timeout=2.)
                    pool.shutdown(wait=True)
                    h.scene.close()

    def test_normal_and_fragmented_responses_reuse_worker_and_preserve_packet(self):
        for mode in ('normal', 'fragmented'):
            with self.subTest(mode=mode):
                h = self.harness(mode=mode)
                self.assertTrue(h.request()[1].data)
                self.assertFalse(h.request(b'0')[1].data)
                self.assertEqual(len(h.processes), 1)
                packet = json.loads((h.root/'worker-0.json').read_text())
                self.assertEqual(packet, dict(service='/fixture', request='30',
                    request_type='fixture.Boolean', response_type='fixture.Boolean', timeout=1))
                h.scene.close()
                self.assert_reaped(h)

    def test_silent_and_half_line_responses_expire_and_discard_old_worker(self):
        for mode in ('silent', 'partial'):
            with self.subTest(mode=mode):
                h = self.harness(mode=mode)
                started = time.monotonic()
                with self.assertRaisesRegex(TimeoutError, '响应超时'):
                    h.request()
                self.assertLess(time.monotonic()-started, 3.)
                self.assert_reaped(h)
                h.mode = 'normal'
                self.assertTrue(h.request()[1].data)
                self.assertEqual(len(h.processes), 2)
                self.assertNotEqual(h.processes[0].pid, h.processes[1].pid)
                h.scene.close()
                self.assert_reaped(h)

    def test_nonreading_child_does_not_block_large_pipe_write(self):
        h = self.harness(mode='no_input')
        with self.assertRaisesRegex(TimeoutError, '写入超时'):
            h.request(b'x'*262144)
        self.assert_reaped(h)

    def test_protocol_errors_and_eof_reap_only_the_request_worker(self):
        for mode, error in (('eof', RuntimeError), ('bad_json', json.JSONDecodeError),
                            ('bad_hex', ValueError), ('error', RuntimeError)):
            with self.subTest(mode=mode):
                h = self.harness(mode=mode)
                with self.assertRaises(error):
                    h.request()
                self.assert_reaped(h)

    def test_uncooperative_worker_escalates_from_terminate_to_kill(self):
        h = self.harness(mode='ignore_term')
        with self.assertRaisesRegex(TimeoutError, '响应超时'):
            h.request()
        self.assertEqual(h.processes[0].returncode, -9)
        self.assert_reaped(h)

    def test_default_off_preserves_original_text_pipe_and_normal_result(self):
        h = self.harness(enabled=False)
        self.assertTrue(h.request()[1].data)
        self.assertTrue(h.launches[0]['text'])
        self.assertNotIn('bufsize', h.launches[0])
        h.scene.close()
        self.assert_reaped(h)

    def test_invalid_parent_timeout_warns_without_rewriting_protocol_field(self):
        for value in (float('nan'), float('inf'), 'bad', None):
            with self.subTest(value=value):
                h = self.harness()
                warning = io.StringIO()
                with redirect_stderr(warning):
                    self.assertTrue(h.request(timeout=value)[1].data)
                self.assertIn('parent wait uses 1.5s', warning.getvalue())
                received = json.loads((h.root/'worker-0.json').read_text())['timeout']
                if isinstance(value, float) and math.isnan(value):
                    self.assertTrue(math.isnan(received))
                else:
                    self.assertEqual(received, value)
                h.scene.close()
                self.assert_reaped(h)

    def test_close_escalates_eof_then_term_then_kill_for_unresponsive_worker(self):
        h = self.harness(mode='ignore_term_no_input')
        h.scene.worker = h.spawn([], stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        deadline = time.monotonic()+2.
        while not (h.root/'worker-0.json').exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue((h.root/'worker-0.json').exists())
        h.scene.close()
        self.assertEqual(h.processes[0].returncode, -9)
        self.assert_reaped(h)

    def test_close_lock_failure_reports_unconfirmed_cleanup_and_keeps_handle(self):
        h = self.harness()
        child = h.scene.worker = h.spawn([], stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        h.scene.request_lock = types.SimpleNamespace(acquire=lambda **kw: False,
            release=lambda: self.fail('A lock that was not acquired must not be released'))
        with self.assertRaisesRegex(TimeoutError, '回收锁等待超时'):
            h.scene.close()
        self.assertIs(h.scene.worker, child)
        self.assertIsNone(child.poll())

    def test_lock_timeout_does_not_kill_another_inflight_request_worker(self):
        h = self.harness()
        h.scene.worker = h.spawn([], stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        h.scene.request_lock.acquire()
        try:
            with self.assertRaisesRegex(TimeoutError, '队列等待超时'):
                h.request()
            self.assertIsNone(h.processes[0].poll())
        finally:
            h.scene.request_lock.release()
            h.scene.close()
        self.assert_reaped(h)


class SceneRecoveryIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_pause_worker_timeout_reaches_real_run_cleanup_without_landing_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_source(root)
            shutil.copyfile(original.DRONE/'scene.py', root/'scene.py')
            for patchfile in (REPAIR, SCENE_PATCH):
                apply(root, patchfile)
            output = root/'output'
            output.mkdir()
            scene = SceneHarness(root, root/'scene.py', mode='partial')
            self.addCleanup(scene.cleanup)
            h = RecoveryHarness(root, output, fault='pending_replacement')
            h.owner.options['recovery_rpc_timeout_s'] = .01
            h.owner.scene = scene.scene
            h.owner.goto.__func__.__globals__['asyncio'].to_thread = asyncio.to_thread
            modules = {name: types.ModuleType(name) for name in (
                'gz', 'gz.msgs10', 'gz.msgs10.world_control_pb2', 'gz.msgs10.boolean_pb2')}
            modules['gz.msgs10.world_control_pb2'].WorldControl = Message
            modules['gz.msgs10.boolean_pb2'].Boolean = Message
            with patch.dict(sys.modules, modules):
                await asyncio.wait_for(h.run(), 3.)
            self.assertEqual(h.owner.status, 'failed')
            self.assertFalse(h.owner.report.get('landed', False))
            self.assertNotIn('simulation_pause_confirmed', h.owner.report['recovery'])
            self.assertTrue(any('worker响应超时' in e for e in h.owner.report['errors']))
            self.assertEqual(len(h.rows('sdk.close.fixture')), 1)
            self.assertIsNone(scene.scene.worker)
            self.assertTrue(all(child.poll() is not None for child in scene.processes))


if __name__ == '__main__':
    unittest.main()
