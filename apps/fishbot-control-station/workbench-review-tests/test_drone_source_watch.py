"""Opt-in epoch propagation at the sole SDK owner; synthetic control, real HTTP."""
import asyncio
import importlib.util
import itertools
import os
import shutil
import subprocess
from pathlib import Path
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

import test_drone_command_validity as original
from test_drone_command_revalidation_patch import REPAIR, SENDER, apply, copy_source
from test_drone_command_epoch_patch import EPOCH
import test_drone_state_epoch_window as windows
from test_drone_state_epoch_window import http_source

WATCH = Path(__file__).resolve().parents[1]/'workbench-tools/patches/drone-source-watch.patch'


def apply_source_watch(fixture):
    apply(fixture.root, WATCH)
    spec = importlib.util.spec_from_file_location('watched_epoch_fixture', fixture.root/'command_epoch.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture.module = module
    spec = importlib.util.spec_from_file_location('source_watch_fixture', fixture.root/'source_epoch_watch.py')
    watch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(watch)
    return watch


def wire_source_watch(h, module):
    node = h.source.node
    node.command_epoch_condition = threading.Condition(node.lock)
    node.notify_command_epoch = types.MethodType(original.methods(h.root/'ego/sidecar.py', 'Sidecar',
        ('notify_command_epoch',), {})['notify_command_epoch'], node)
    node.command_epoch.on_rotate = node.notify_command_epoch
    namespace = h.owner.goto.__func__.__globals__
    namespace['SourceEpochWatch'] = module.SourceEpochWatch
    for name, method in original.methods(h.root/'flight.py', 'Flight',
            ('start_source_watch', 'check_source_watch'), namespace).items():
        setattr(h.owner, name, types.MethodType(method, h.owner))


class SourceWatchPropagation(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        windows.StateEpochWindow.setUpClass()
        cls.fixture = windows.StateEpochWindow.fixture
        cls.watch_module = apply_source_watch(cls.fixture)

    @classmethod
    def tearDownClass(cls):
        windows.StateEpochWindow.tearDownClass()

    def bridge(self, ordering='manual', enabled=True):
        with patch.dict(os.environ, {'DRONE_SOURCE_WATCH': '1' if enabled else '0'}):
            h = windows.StateEpochWindow.bridge(self, ordering)
        wire_source_watch(h, self.watch_module)
        return h

    async def finish_watches(self, h):
        for task in h.owner.tasks:
            task.cancel()
        await asyncio.gather(*h.owner.tasks, return_exceptions=True)

    def test_watch_flag_defaults_off_and_enables_existing_epoch(self):
        for setting in (None, '0', '1'):
            with self.subTest(setting=setting), patch.dict(os.environ, {}, clear=True):
                if setting is not None:
                    os.environ['DRONE_SOURCE_WATCH'] = setting
                epoch = self.fixture.module.CommandEpoch()
                self.assertEqual((epoch.source_watch_enabled, epoch.enabled), (setting=='1',)*2)

    def test_actual_shell_launcher_imports_candidate_root_modules(self):
        for name in ('frames.py', 'perception.py', 'motion_budget.py'):
            shutil.copyfile(original.DRONE/'ego'/name, self.fixture.root/'ego'/name)
        result = subprocess.run(['bash', str(self.fixture.root/'ego/run_sidecar.sh'), '--help'],
            env=dict(os.environ, PYTHONPATH='', PYTHONDONTWRITEBYTECODE='1'),
            text=True, capture_output=True, timeout=20.)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--runtime', result.stdout)

    def test_source_watch_composes_after_six_existing_patch_orders(self):
        for order in itertools.permutations((EPOCH, REPAIR, SENDER)):
            with self.subTest(order=[p.name for p in order]), tempfile.TemporaryDirectory() as d:
                root = Path(d); copy_source(root)
                for p in (*order, WATCH):
                    apply(root, p)
                for name in ('flight.py', 'ego/sidecar.py', 'command_epoch.py', 'source_epoch_watch.py', 'scene.py'):
                    compile((root/name).read_text(), str(root/name), 'exec')

    async def test_applied_patch_disabled_preserves_old_snapshot_gap(self):
        h = self.bridge('after_snapshot', enabled=False)
        with http_source(h):
            await h.run()
            windows.StateEpochWindow.assert_old_snapshot_dispatch_then_recovery(self, h)
            self.assertNotIn('source_epoch_watches', h.owner.report)
            self.assertEqual(h.owner.tasks, [])

    async def test_notification_latches_without_sending_control(self):
        h = self.bridge()
        with http_source(h):
            try:
                await h.owner.start_source_watch(h.source.node.command_epoch.token)
                watch = h.owner.source_epoch_watch
                h.source.node.invalidate_command_source('fixture_source_changed')
                await asyncio.wait_for(watch.task, 1.)
                with self.assertRaisesRegex(RuntimeError, 'command_source_epoch_changed'):
                    h.owner.check_source_watch()
                self.assertEqual(h.rows('position.begin')+h.rows('pva.return'), [])
                self.assertFalse(any(r['path']=='/stop' for r in h.rows('source.request')))
            finally:
                await self.finish_watches(h)

    async def test_invalidated_snapshot_is_rejected_while_its_http_response_is_held(self):
        h = self.bridge('after_snapshot')
        entered, release = threading.Event(), threading.Event()
        def before_send(path, body):
            if path == '/state' and len(h.snapshots)==1:
                entered.set(); release.wait(2.)
        with http_source(h, before_send):
            task = asyncio.create_task(h.run())
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1.))
                await asyncio.wait_for(asyncio.shield(task), 1.)
                self.assertFalse(release.is_set())
                self.assertEqual(h.rows('pva.return'), [])
                self.assertEqual(h.owner.report['recovery']['trigger'], 'command_source_epoch_changed')
                self.assertEqual(h.owner.status, 'failed')
            finally:
                release.set()
                if not task.done(): task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_notification_interrupts_pending_pva_without_claiming_remote_rollback(self):
        for accepted in (False, True):
            with self.subTest(accepted=accepted):
                h = self.bridge()
                entered, cancelled = asyncio.Event(), asyncio.Event()
                async def pending(*payload):
                    if accepted: h.cache = {'mode': 'unconfirmed_pva'}
                    entered.set()
                    try: await asyncio.Event().wait()
                    finally: cancelled.set()
                h.owner.drone.offboard.set_position_velocity_acceleration_ned = pending
                with http_source(h):
                    task = asyncio.create_task(h.run())
                    try:
                        await asyncio.wait_for(entered.wait(), 1.)
                        h.source.node.invalidate_command_source('fixture_source_changed')
                        await asyncio.wait_for(asyncio.shield(task), 1.)
                        self.assertTrue(cancelled.is_set())
                        attempt = h.owner.report['command_rpc_attempts'][0]
                        self.assertEqual(attempt['reason'], 'command_source_epoch_changed')
                        self.assertEqual(attempt['remote_effect'], 'unknown')
                        self.assertTrue(attempt['rpc_started'])
                        self.assertFalse(attempt['rpc_returned'])
                        self.assertEqual(h.owner.report['recovery']['trigger'], 'command_source_epoch_changed')
                        self.assertEqual(h.owner.report['recovery']['reason'],
                            'unconfirmed_pva_without_native_epoch_fence')
                        self.assertEqual(h.owner.report['recovery']['unfenced_pva'], attempt)
                        self.assertFalse(any(r['recovery'] for r in h.rows('position.begin')))
                        self.assertEqual(h.rows('observation.fixture_boundary'), [])
                        self.assertEqual(h.rows('scene.pause')[0]['cache']['mode'],
                            'unconfirmed_pva' if accepted else 'position')
                        self.assertEqual(h.owner.status, 'failed')
                        self.assertFalse(h.owner.report.get('landed', False))
                    finally:
                        if not task.done(): task.cancel()
                        await asyncio.gather(task, return_exceptions=True)

    async def test_pre_dispatch_veto_still_uses_original_recovery(self):
        h = self.bridge()
        check = h.owner.check_command_wait
        def veto(*args, **kwargs):
            command = args[4] if len(args)>4 else kwargs.get('command')
            if command is not None:
                raise RuntimeError('fixture_pre_dispatch_veto')
            return check(*args, **kwargs)
        h.owner.check_command_wait = veto
        with http_source(h):
            await h.run()
        attempt = h.owner.report['command_rpc_attempts'][0]
        self.assertFalse(attempt['rpc_started'])
        self.assertFalse(attempt['rpc_returned'])
        self.assertEqual(h.rows('pva.return'), [])
        self.assertTrue(any(r['recovery'] for r in h.rows('position.return')))
        self.assertNotIn('unfenced_pva', h.owner.report['recovery'])
        self.assertEqual(len(h.rows('observation.fixture_boundary')), 1)

    async def test_returned_pva_then_source_failure_keeps_original_recovery(self):
        h = self.bridge()
        request = h.source_request
        def invalidate_on_next_state(path, body=None):
            if path=='/state' and h.rows('pva.return'):
                h.source.node.invalidate_command_source('fixture_source_changed')
            return request(path, body)
        h.source_request = invalidate_on_next_state
        with http_source(h):
            await h.run()
        attempt = h.owner.report['command_rpc_attempts'][0]
        self.assertTrue(attempt['rpc_started'])
        self.assertTrue(attempt['rpc_returned'])
        self.assertEqual(attempt['status'], 'returned')
        self.assertNotIn('unfenced_pva', h.owner.report['recovery'])
        self.assertTrue(any(r['recovery'] for r in h.rows('position.return')))
        self.assertEqual(h.rows('scene.pause')[0]['cache']['mode'], 'position')

    async def test_missing_invalid_or_old_notification_blocks_before_pva(self):
        for body in ({}, {'command_epoch':'epoch', 'observed_monotonic_ns':0},
                     {'command_epoch':'epoch', 'observed_monotonic_ns':True}):
            with self.subTest(body=body):
                h = self.bridge(); request = h.source_request
                h.owner.ego_request = lambda path, data=None: body if path.startswith('/command-epoch') else request(path,data)
                await h.run()
                self.assertEqual(h.rows('pva.return'), [])
                self.assertIn('command_source_watch_unavailable', h.owner.report['recovery']['trigger'])

    async def test_unchanged_epoch_with_failed_health_is_not_kept_alive(self):
        h = self.bridge()
        with http_source(h):
            try:
                epoch = h.source.node.command_epoch.token
                await h.owner.start_source_watch(epoch)
                h.source.node.planner_error = 'fixture_depth_lost'
                await asyncio.wait_for(h.owner.source_epoch_watch.task, 1.5)
                self.assertEqual(h.owner.source_epoch_watch.last_epoch, epoch)
                with self.assertRaisesRegex(RuntimeError, 'command_source_unready: fixture_depth_lost'):
                    h.owner.check_source_watch()
            finally:
                await self.finish_watches(h)

    async def test_new_goal_cancels_old_watch_without_late_rebinding(self):
        h = self.bridge()
        with http_source(h):
            try:
                await h.owner.start_source_watch(h.source.node.command_epoch.token)
                old = h.owner.source_epoch_watch
                reply = self.fixture.post(h.source.node, '/goal',
                    dict(x=5., y=0., z=1., task_id='task-A', goal_id='new-fixture-goal'))
                expected = reply[0][1]['command_epoch']
                await h.owner.start_source_watch(expected)
                current = h.owner.source_epoch_watch
                self.assertIsNot(current, old)
                self.assertTrue(old.task.done())
                self.assertEqual(current.last_epoch, expected)
                self.assertIsNone(current.failure)
            finally:
                await self.finish_watches(h)

    async def test_source_clock_epoch_notifies_even_when_flight_clock_is_unchanged(self):
        h = self.bridge()
        with http_source(h):
            try:
                await h.owner.start_source_watch(h.source.node.command_epoch.token)
                local = h.owner.observer.command_epoch.token
                with h.source.node.lock:
                    h.source.clock.sim -= .01
                    h.source.node.observe_command_epoch()
                await asyncio.wait_for(h.owner.source_epoch_watch.task, 1.)
                self.assertEqual(h.owner.observer.command_epoch.token, local)
                self.assertEqual(h.owner.source_epoch_watch.failure, 'command_source_epoch_changed')
            finally:
                await self.finish_watches(h)

    async def test_watch_transport_loss_interrupts_pending_control_wait(self):
        h = self.bridge()
        request, first = h.source_request, True
        release, entered = threading.Event(), asyncio.Event()
        def source(path, body=None):
            nonlocal first
            if not path.startswith('/command-epoch'):
                return request(path, body)
            if first:
                first = False
                return dict(command_epoch=h.source.node.command_epoch.token,
                    ready=True, reason='ready', observed_monotonic_ns=time.monotonic_ns())
            release.wait(2.)
            raise OSError('fixture_watch_channel_closed')
        async def pending(*payload):
            entered.set()
            await asyncio.Event().wait()
        h.owner.ego_request = source
        h.owner.drone.offboard.set_position_velocity_acceleration_ned = pending
        task = asyncio.create_task(h.run())
        try:
            await asyncio.wait_for(entered.wait(), 1.)
            release.set()
            await asyncio.wait_for(asyncio.shield(task), 1.)
            self.assertIn('command_source_watch_unavailable: OSError', h.owner.report['recovery']['trigger'])
            self.assertEqual(h.owner.report['command_rpc_attempts'][0]['remote_effect'], 'unknown')
            self.assertEqual(h.owner.report['recovery']['reason'],
                'unconfirmed_pva_without_native_epoch_fence')
            self.assertFalse(any(r['recovery'] for r in h.rows('position.begin')))
        finally:
            release.set()
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)


if __name__ == '__main__':
    unittest.main()
