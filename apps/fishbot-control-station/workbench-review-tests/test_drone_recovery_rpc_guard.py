"""Recovery RPC deadlines with real Flight methods and explicit SDK substitutes."""
import asyncio
from pathlib import Path
import tempfile
import unittest

from test_drone_command_revalidation_patch import REPAIR, apply, copy_source
from test_drone_recovery_cache_chain import RecoveryHarness


class RecoveryRpcGuard(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        copy_source(cls.root)
        apply(cls.root, REPAIR)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def harness(self, **kwargs):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        h = RecoveryHarness(self.root, Path(directory.name), **kwargs)
        h.owner.options['recovery_rpc_timeout_s'] = .01
        return h

    async def test_pending_replacement_now_reaches_pause_and_cleanup_with_unknown_effect(self):
        for trigger in ('cancel', 'expired'):
            with self.subTest(trigger=trigger):
                h = self.harness(trigger=trigger, fault='pending_replacement')
                await asyncio.wait_for(h.run(), 1.)
                attempt = h.owner.report['recovery']['rpc_attempts'][-1]
                self.assertEqual(attempt['operation'], 'position')
                self.assertEqual(attempt['status'], 'unconfirmed')
                self.assertEqual(attempt['remote_effect'], 'unknown')
                self.assertEqual(attempt['error_type'], 'TimeoutError')
                self.assertEqual(h.rows('scene.pause')[0]['cache']['mode'], 'pva')
                self.assertEqual(h.rows('scene.pause')[0]['reference']['mode'], 'position_velocity_acceleration')
                self.assertFalse(any(row['path'] == '/stop' for row in h.rows('http')))
                self.assertTrue(h.owner.report['recovery']['simulation_pause_confirmed'])
                self.assertEqual(h.owner.status, 'failed')
                self.assertFalse(h.owner.report.get('landed', False))
                self.assertEqual(len(h.rows('sdk.close.fixture')), 1)

    async def test_pending_hold_and_start_are_bounded_without_retrying_control(self):
        for operation in ('hold', 'offboard_start'):
            with self.subTest(operation=operation):
                h = self.harness(fault='takeover')
                cancelled = asyncio.Event()
                calls = []
                async def pending():
                    calls.append(operation)
                    try:
                        await asyncio.Event().wait()
                    finally:
                        cancelled.set()
                if operation == 'hold':
                    h.owner.drone.action.hold = pending
                else:
                    h.owner.drone.offboard.start = pending
                await asyncio.wait_for(h.run(), 1.)
                self.assertTrue(cancelled.is_set())
                self.assertEqual(calls, [operation])
                attempts = h.owner.report['recovery']['rpc_attempts']
                self.assertEqual(attempts[-1]['operation'], operation)
                self.assertEqual(attempts[-1]['status'], 'unconfirmed')
                self.assertEqual(h.rows('scene.pause')[0]['cache']['mode'],
                                 'pva' if operation == 'hold' else 'position')
                self.assertNotIn('control_takeover', h.owner.report['recovery'])
                self.assertEqual(h.owner.status, 'failed')

    async def test_disabled_guard_preserves_pending_wait_without_new_journal(self):
        h = self.harness(fault='pending_replacement')
        h.owner.command_revalidation_enabled = False
        task = asyncio.create_task(h.run())
        try:
            await asyncio.wait_for(h.replacement_entered.wait(), 1.)
            await asyncio.sleep(.03)
            self.assertFalse(task.done())
            self.assertNotIn('rpc_attempts', h.owner.report['recovery'])
            self.assertEqual(h.rows('scene.pause'), [])
        finally:
            h.release_replacement.set()
            await task

    async def test_invalid_optional_budget_warns_and_uses_default(self):
        for value in ('bad', None, 0., -1., float('nan'), float('inf')):
            with self.subTest(value=value):
                h = self.harness()
                h.owner.options['recovery_rpc_timeout_s'] = value
                await h.run()
                attempt = h.owner.report['recovery']['rpc_attempts'][0]
                self.assertEqual(attempt['wait_timeout_s'], 1.)
                self.assertEqual(attempt['status'], 'returned')
                self.assertEqual(attempt['remote_effect'], 'not_independently_observed')
                self.assertIn('WARNING: invalid recovery_rpc_timeout_s; using 1.0s',
                              h.owner.report['errors'])

    async def test_timeout_and_pause_failure_still_enter_original_cleanup(self):
        h = self.harness(fault='pending_replacement')
        def failed_pause():
            h.note('pause.failed.fixture')
            raise RuntimeError('fixture_pause_failed')
        h.owner.scene.pause = failed_pause
        await asyncio.wait_for(h.run(), 1.)
        self.assertNotIn('simulation_pause_confirmed', h.owner.report['recovery'])
        self.assertEqual(h.owner.report['recovery']['rpc_attempts'][0]['status'], 'unconfirmed')
        self.assertEqual(h.owner.status, 'failed')
        self.assertTrue(any('fixture_pause_failed' in e for e in h.owner.report['errors']))
        self.assertEqual(len(h.rows('sdk.close.fixture')), 1)

    async def test_task_cancel_during_business_cancel_never_claims_landing(self):
        h = self.harness(fault='pending_replacement')
        h.owner.options['recovery_rpc_timeout_s'] = 5.
        task = asyncio.create_task(h.run())
        try:
            await asyncio.wait_for(h.replacement_entered.wait(), 1.)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        attempt = h.owner.report['recovery']['rpc_attempts'][0]
        self.assertEqual(attempt['status'], 'cancelled')
        self.assertEqual(attempt['remote_effect'], 'unknown')
        self.assertEqual(h.owner.status, 'failed')
        self.assertNotEqual(h.owner.message, '任务已取消，已落地')
        self.assertFalse(h.owner.report.get('landed', False))

    async def test_old_landing_flags_cannot_confirm_cancel_after_new_flight(self):
        h = self.harness(fault='pending_replacement')
        h.owner.options['recovery_rpc_timeout_s'] = 5.
        h.owner.report.update(landed=True, disarmed=True)
        h.owner.telemetry.update(landed='IN_AIR', armed=True)
        task = asyncio.create_task(h.run())
        try:
            await asyncio.wait_for(h.replacement_entered.wait(), 1.)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(h.owner.status, 'failed')
        self.assertFalse(h.owner.report['landed'])
        self.assertFalse(h.owner.report['disarmed'])
        self.assertNotEqual(h.owner.message, '任务已取消，已落地')
        self.assertEqual(h.owner.report['recovery']['rpc_attempts'][0]['remote_effect'], 'unknown')

    async def test_blocked_recovery_also_discards_previous_landing_flags(self):
        h = self.harness(fault='pending_replacement')
        h.owner.report.update(landed=True, disarmed=True)
        await asyncio.wait_for(h.run(), 1.)
        self.assertEqual(h.owner.status, 'failed')
        self.assertFalse(h.owner.report['landed'])
        self.assertFalse(h.owner.report['disarmed'])
        self.assertEqual(h.owner.report['recovery']['outcome'], 'blocked')


if __name__ == '__main__':
    unittest.main()
