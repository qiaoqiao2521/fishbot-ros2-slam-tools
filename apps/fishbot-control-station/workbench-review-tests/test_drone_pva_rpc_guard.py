"""Actual frozen run/goto/setpoint/recover; SDK/cache/state are explicit fakes."""
import asyncio
from pathlib import Path
import tempfile
import types
import unittest

from test_drone_command_revalidation_patch import REPAIR, apply, copy_source
from test_drone_recovery_cache_chain import RecoveryHarness, ReturnHome
import test_drone_command_validity as original


class PendingPva(RecoveryHarness):
    def __init__(self, root, output, accepted=False):
        super().__init__(root, output)
        self.owner.options['command_rpc_timeout_s'] = .06
        self.send_entered, self.send_cancelled, self.send_release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.sent = 0
        async def pending(*payload):
            self.sent += 1
            self.note('pva.pending', accepted=accepted)
            if accepted:
                self.cache = {'mode': 'unconfirmed_pva'}
            self.send_entered.set()
            try:
                await self.send_release.wait()
            except asyncio.CancelledError:
                self.send_cancelled.set()
                raise
            self.note('pva.return')
        self.owner.drone.offboard.set_position_velocity_acceleration_ned = pending


class PvaRpcGuard(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        copy_source(cls.root)
        apply(cls.root, REPAIR)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def harness(self, **kw):
        out = tempfile.TemporaryDirectory()
        self.addCleanup(out.cleanup)
        return PendingPva(self.root, Path(out.name), **kw)

    async def finish(self, h, action=None):
        task = asyncio.create_task(h.run())
        try:
            await asyncio.wait_for(h.send_entered.wait(), .3)
            if action: action(h)
            await asyncio.wait_for(asyncio.shield(task), .35)
        finally:
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return task

    async def test_wall_deadline_routes_to_recovery_before_or_after_remote_acceptance(self):
        for accepted in (False, True):
            with self.subTest(accepted=accepted):
                h = self.harness(accepted=accepted)
                await self.finish(h)
                self.assertTrue(h.send_cancelled.is_set())
                self.assertEqual(h.sent, 1)
                self.assertEqual(h.owner.status, 'failed')
                self.assertFalse(h.owner.report.get('landed', False))
                attempt = h.owner.report['command_rpc_attempts'][0]
                self.assertEqual(attempt['reason'], 'command_rpc_timeout')
                self.assertEqual(attempt['remote_effect'], 'unknown')
                self.assertFalse(attempt['rpc_returned'])
                replacement = next(x for x in h.rows('position.begin') if x['recovery'])
                self.assertEqual(replacement['cache']['mode'], 'unconfirmed_pva' if accepted else 'position')
                self.assertEqual(replacement['reference']['mode'], 'position')
                self.assertEqual(h.rows('scene.pause')[0]['cache']['mode'], 'position')

    async def test_inflight_source_expiry_is_observed_with_fresh_sample(self):
        h = self.harness(accepted=True)
        h.owner.options['command_rpc_timeout_s'] = 1.
        await self.finish(h, lambda h: h.advance(10.4))
        self.assertEqual(h.owner.report['command_rpc_attempts'][0]['reason'], 'inflight_command_source_expired')
        self.assertEqual(h.sent, 1)
        self.assertTrue(h.send_cancelled.is_set())

    async def test_pending_send_checks_cancel_clock_position_and_scene(self):
        cases = [('cancel', lambda h: setattr(h, 'cancelled', True), 'CancelFlight'),
                 ('position', lambda h: setattr(h.owner, 'position_valid', False), 'PX4 本地定位无效'),
                 ('scene', lambda h: setattr(h.owner.scene, 'failure', 'fixture'), '动态障碍驱动失效: fixture'),
                 ('clock', lambda h: setattr(h.owner.observer, 'clock_received', 97.), 'simulation_clock_stopped')]
        for label, action, reason in cases:
            with self.subTest(label=label):
                h = self.harness()
                await self.finish(h, action)
                attempt = h.owner.report['command_rpc_attempts'][0]
                self.assertEqual(attempt['reason'], reason)
                self.assertEqual(h.sent, 1)
                self.assertTrue(h.send_cancelled.is_set())

    async def test_successful_response_cannot_bypass_simultaneous_cancel(self):
        h = self.harness(accepted=True)
        def action(h):
            h.cancelled = True
            h.send_release.set()
        await self.finish(h, action)
        self.assertEqual(h.owner.report['command_rpc_attempts'][0]['reason'], 'CancelFlight')
        self.assertEqual(h.sent, 1)
        self.assertEqual(h.owner.status, 'failed')

    async def test_disabled_guard_preserves_unbounded_original_wait(self):
        h = self.harness()
        h.owner.command_revalidation_enabled = False
        task = asyncio.create_task(h.run())
        try:
            await asyncio.wait_for(h.send_entered.wait(), .3)
            await asyncio.sleep(.09)
            self.assertFalse(task.done())
            self.assertNotIn('command_rpc_attempts', h.owner.report)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


    async def test_previous_cached_pva_can_expire_before_fresh_inflight_candidate(self):
        h = self.harness()
        h.owner.reference = dict(original.command(stamp_sim_s=10.0),
            mode='position_velocity_acceleration', command_stamp_sim_s=10.0)
        # goto begins with a position hold, so exercise the actual waiting helper directly.
        with h.sdk_modules():
            task = asyncio.create_task(h.owner.await_pva_command(original.command(), [5.,0.,1.], 200., True))
            try:
                await asyncio.wait_for(h.send_entered.wait(), .3)
                h.advance(10.4)
                with self.assertRaisesRegex(RuntimeError, 'cached_command_sample_expired'):
                    await task
            finally:
                if not task.done(): task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(h.send_cancelled.is_set())

    async def test_goal_hold_source_exception_still_requires_fresh_sample_while_pending(self):
        h = self.harness()
        h.response['setpoint'] = original.command(position=[5.,0.,1.], velocity=[0.]*3,
            acceleration=[0.]*3, source_end_sim_s=9.)
        await self.finish(h, lambda h: h.advance(10.5))
        self.assertEqual(h.owner.report['command_rpc_attempts'][0]['reason'], 'inflight_command_sample_expired')

    async def test_external_cancel_propagates_without_inventing_business_recovery(self):
        h = self.harness(accepted=True)
        task = asyncio.create_task(h.run())
        await asyncio.wait_for(h.send_entered.wait(), .3)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(h.send_cancelled.is_set())
        self.assertEqual(h.owner.report['command_rpc_attempts'][0]['status'], 'cancelled')
        self.assertFalse(any(x['recovery'] for x in h.rows('position.begin')))
        self.assertEqual(len(h.rows('sdk.close.fixture')), 1)

    async def test_external_cancel_cannot_reuse_prior_landing_evidence_as_success(self):
        h = self.harness(accepted=True)
        h.owner.report.update(landed=True, disarmed=True,
            visits=[{'truth_error_m': 0., 'truth_hold_s': 1.}])
        h.owner.observer.max_height, h.owner.observer.speed_samples = 1., 1
        task = asyncio.create_task(h.run())
        await asyncio.wait_for(h.send_entered.wait(), .3)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(h.owner.telemetry['landed'], 'IN_AIR')
        self.assertTrue(h.owner.telemetry['armed'])
        self.assertEqual(h.owner.status, 'failed')
        self.assertFalse(h.owner.report['passed'])
        self.assertFalse(h.owner.report['landed'])
        self.assertFalse(h.owner.report['disarmed'])
        self.assertFalse(any(x['recovery'] for x in h.rows('position.begin')))
        self.assertEqual(len(h.rows('sdk.close.fixture')), 1)

    async def test_external_cancel_in_return_home_handler_also_rejects_old_landing(self):
        h = self.harness(accepted=True)
        h.owner.report.update(landed=True, disarmed=True,
            visits=[{'truth_error_m': 0., 'truth_hold_s': 1.}])
        h.owner.observer.max_height, h.owner.observer.speed_samples = 1., 1
        h.owner.cruise_height, h.owner.home = 1., [5.,0.,0.]
        method = original.methods(self.root/'flight.py', 'Flight', ('return_home',),
            h.owner.goto.__func__.__globals__)['return_home']
        h.owner.return_home = types.MethodType(method, h.owner)
        def request_return():
            raise ReturnHome()
        h.owner.check_operator = request_return
        task = asyncio.create_task(h.run())
        try:
            await asyncio.wait_for(h.send_entered.wait(), .3)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(h.owner.status, 'failed')
            self.assertFalse(h.owner.report['passed'])
            self.assertFalse(h.owner.report['landed'])
            self.assertFalse(h.owner.report['disarmed'])
            self.assertEqual(len(h.rows('sdk.close.fixture')), 1)
        finally:
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_local_clock_epoch_change_aborts_inflight_rpc(self):
        from types import SimpleNamespace
        h = self.harness()
        h.owner.observer.command_epoch = SimpleNamespace(enabled=True, token='before')
        await self.finish(h, lambda h: setattr(h.owner.observer.command_epoch, 'token', 'after'))
        self.assertEqual(h.owner.report['command_rpc_attempts'][0]['reason'], 'command_clock_epoch_changed')

    async def test_success_and_numeric_string_end_keep_metadata_and_invalid_budget_warns(self):
        for budget in (None, 'nan', -1, 0, 'bad'):
            with self.subTest(budget=budget):
                h = self.harness()
                h.owner.options['command_rpc_timeout_s'] = budget
                h.response['setpoint']['source_end_sim_s'] = '10.2'
                await self.finish(h, lambda h: h.send_release.set())
                attempt = h.owner.report['command_rpc_attempts'][0]
                self.assertEqual(attempt['status'], 'returned')
                self.assertTrue(attempt['rpc_returned'])
                self.assertEqual(attempt['wait_timeout_s'], 1.)
                self.assertTrue(any('WARNING: invalid command_rpc_timeout_s' in x for x in h.owner.report['errors']))
                # Triggered cancellation on the next state read, not a fabricated cache failure.
                self.assertEqual(h.owner.report['recovery']['trigger'], 'operator_cancel')


if __name__ == '__main__':
    unittest.main()
