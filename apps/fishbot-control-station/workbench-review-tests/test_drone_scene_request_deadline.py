"""Real Scene IPC with controlled owned workers; no Gazebo world or flight."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

from test_drone_command_revalidation_patch import copy_source, apply, REPAIR
from test_drone_command_epoch_patch import EPOCH
from test_drone_source_watch import WATCH
import test_drone_command_validity as original


WORKER = '''
import json, pathlib, sys, time
mode, marker = sys.argv[1:]
if mode == 'no_reader':
    pathlib.Path(marker).write_text('not reading')
    time.sleep(60)
else:
    for line in sys.stdin:
        pathlib.Path(marker).write_text(line)
        if mode == 'reject':
            print(json.dumps({'ok':False,'response':''}),flush=True)
        elif mode == 'accept':
            print(json.dumps({'ok':True,'response':'1001'}),flush=True)
        else:
            if mode == 'partial_reply':
                sys.stdout.write('{"ok":');sys.stdout.flush()
            time.sleep(60)
'''


class SceneWorkerFault:
    """Use actual Scene methods; replace only its owned child request worker."""
    def __init__(self, root, output, mode):
        spec = importlib.util.spec_from_file_location('deadline_scene', root/'scene.py')
        module = importlib.util.module_from_spec(spec)
        with patch.object(sys, 'path', [str(root), *sys.path]):
            spec.loader.exec_module(module)
        self.scene = module.Scene('fixture_no_world', [], types.SimpleNamespace(), output)
        self.marker = Path(output)/'scene-worker-request.json'
        self.process = None
        if mode != 'native_unavailable':
            self.process = subprocess.Popen([sys.executable,'-u','-c',WORKER,mode,str(self.marker)],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
            self.scene.worker = self.process

    def release(self):
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=2.)

    def close(self):
        self.release()
        self.scene.close()


class SceneRequestDeadline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        copy_source(cls.root)
        apply(cls.root,EPOCH);apply(cls.root,REPAIR);apply(cls.root,WATCH)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def fixture(self, mode, original_source=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        f = SceneWorkerFault(original.DRONE if original_source else self.root, Path(directory.name), mode)
        self.addCleanup(f.close)
        return f

    def test_original_partial_line_blocks_request_and_close_until_external_release(self):
        f = self.fixture('partial_reply',original_source=True)
        errors=[]
        def request():
            try:f.scene.pause()
            except Exception as e:errors.append(str(e))
        thread=threading.Thread(target=request,daemon=True);thread.start()
        until=time.monotonic()+1.
        while not f.marker.exists() and time.monotonic()<until:time.sleep(.01)
        self.assertTrue(f.marker.exists())
        closing=threading.Thread(target=f.scene.close,daemon=True);closing.start()
        try:
            thread.join(1.7);closing.join(.15)
            self.assertTrue(thread.is_alive())
            self.assertTrue(closing.is_alive())
        finally:
            f.release();thread.join(2.);closing.join(3.)
        self.assertFalse(thread.is_alive() or closing.is_alive())
        self.assertTrue(errors)

    def test_applied_patch_off_retains_original_partial_line_wait(self):
        f=self.fixture('partial_reply')
        errors=[]
        def request():
            try:f.scene.pause()
            except Exception as e:errors.append(str(e))
        with patch.dict(os.environ, {'DRONE_SOURCE_WATCH':'0'}):
            thread=threading.Thread(target=request,daemon=True);thread.start()
            try:
                thread.join(1.7)
                self.assertTrue(thread.is_alive())
                self.assertIsNone(f.process.poll())
            finally:
                f.release();thread.join(2.)
        self.assertFalse(thread.is_alive())
        self.assertTrue(errors)

    def test_no_reply_and_partial_reply_retire_worker_and_release_lock(self):
        from gz.msgs10.world_control_pb2 import WorldControl
        from gz.msgs10.boolean_pb2 import Boolean
        for mode in ('no_reply','partial_reply'):
            with self.subTest(mode=mode),patch.dict(os.environ, {'DRONE_SOURCE_WATCH':'1'}):
                f=self.fixture(mode)
                started=time.monotonic()
                with self.assertRaisesRegex(TimeoutError,'pipe deadline'):
                    f.scene.request('/fixture',WorldControl(pause=True),WorldControl,Boolean,20)
                self.assertLess(time.monotonic()-started,3.)
                self.assertIsNotNone(f.process.poll())
                self.assertIsNone(f.scene.worker)
                self.assertTrue(f.scene.request_lock.acquire(blocking=False))
                f.scene.request_lock.release()
                sent=json.loads(f.marker.read_text())
                decoded=WorldControl();decoded.ParseFromString(bytes.fromhex(sent['request']))
                self.assertTrue(decoded.pause)
                self.assertEqual(sent['timeout'],20)

    def test_full_pipe_write_is_also_bounded(self):
        from gz.msgs10.stringmsg_pb2 import StringMsg
        from gz.msgs10.boolean_pb2 import Boolean
        f=self.fixture('no_reader')
        with patch.dict(os.environ, {'DRONE_SOURCE_WATCH':'1'}):
            started=time.monotonic()
            with self.assertRaisesRegex(TimeoutError,'pipe deadline'):
                f.scene.request('/fixture',StringMsg(data='x'*300000),StringMsg,Boolean,20)
            self.assertLess(time.monotonic()-started,3.)
            self.assertIsNotNone(f.process.poll())
            self.assertIsNone(f.scene.worker)

    def test_lock_timeout_does_not_kill_another_active_request(self):
        from gz.msgs10.world_control_pb2 import WorldControl
        from gz.msgs10.boolean_pb2 import Boolean
        f=self.fixture('accept');f.scene.request_lock.acquire()
        try:
            with patch.dict(os.environ, {'DRONE_SOURCE_WATCH':'1'}):
                with self.assertRaisesRegex(TimeoutError,'lock deadline'):
                    f.scene.request('/fixture',WorldControl(pause=True),WorldControl,Boolean,20)
            self.assertIsNone(f.process.poll())
        finally:f.scene.request_lock.release()

    def test_rejected_pause_does_not_become_confirmation(self):
        f=self.fixture('reject')
        with patch.dict(os.environ, {'DRONE_SOURCE_WATCH':'1'}):
            with self.assertRaisesRegex(RuntimeError,'暂停未确认'):f.scene.pause()
            self.assertIsNone(f.process.poll())
            f.scene.close()
            self.assertEqual(f.process.poll(),0)

    def test_complete_response_reuses_worker_and_closes_normally(self):
        f=self.fixture('accept')
        with patch.dict(os.environ, {'DRONE_SOURCE_WATCH':'1'}):
            f.scene.pause();f.scene.pause()
            self.assertIs(f.scene.worker,f.process)
            self.assertIsNone(f.process.poll())
            f.scene.close()
            self.assertEqual(f.process.poll(),0)

    def test_native_unavailable_service_returns_failure_and_closes_worker(self):
        f=self.fixture('native_unavailable')
        with patch.dict(os.environ, {'DRONE_SOURCE_WATCH':'1'}):
            with self.assertRaisesRegex(RuntimeError,'暂停未确认'):f.scene.pause()
            process=f.scene.worker
            self.assertIsNotNone(process)
            f.scene.close()
            self.assertEqual(process.poll(),0)


if __name__=='__main__':unittest.main()
