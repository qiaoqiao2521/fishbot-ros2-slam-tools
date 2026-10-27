"""Real recovery/landing methods with explicitly synthetic control and sensing."""
import asyncio
from pathlib import Path
import tempfile
import types
import unittest

import test_drone_command_validity as original
from test_drone_command_revalidation_patch import REPAIR, apply, copy_source
from test_drone_recovery_cache_chain import RecoveryBlocked, RecoveryHarness


class RecoveryTailRpc(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        copy_source(cls.root)
        apply(cls.root, REPAIR)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def harness(self, recovering=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        h = RecoveryHarness(self.root, Path(directory.name))
        h.owner.recovering = recovering
        h.owner.options['recovery_rpc_timeout_s'] = .01
        if recovering:
            h.owner.report['recovery'] = {'checks': [], 'outcome': 'running'}
        ns = h.owner.goto.__func__.__globals__
        ns['asyncio'].create_task = asyncio.create_task
        ns['asyncio'].wait = asyncio.wait
        ns['asyncio'].FIRST_COMPLETED = asyncio.FIRST_COMPLETED
        methods = original.methods(self.root/'flight.py', 'Flight',
            ('_hold_for_observation', 'retreat_to', 'land', 'with_hover_guard'), ns)
        for name, method in methods.items():
            setattr(h.owner, name, types.MethodType(method, h.owner))
        return h

    def install_controls(self, h, pending=None, position_number=1, descend=False, mode_confirmed=True):
        counts = {'position': 0}
        cancelled = asyncio.Event()
        async def operation(name):
            h.note('control.'+name)
            if name == pending and (name != 'position' or counts['position'] == position_number):
                try:
                    await h.release_replacement.wait()
                finally:
                    cancelled.set()
        async def position(*args):
            counts['position'] += 1
            await operation('position')
        async def stop():
            await operation('stop')
        async def hold():
            await operation('hold')
        async def start():
            await operation('start')
            if mode_confirmed:
                h.owner.telemetry['flight_mode'] = 'OFFBOARD'
        async def land():
            await operation('land')
            h.owner.telemetry['flight_mode'] = 'LAND'
            if not descend:
                h.owner.telemetry.update(landed='ON_GROUND', armed=False)
        h.owner.drone.offboard.set_position_ned = position
        h.owner.drone.offboard.stop, h.owner.drone.offboard.start = stop, start
        h.owner.drone.action.land, h.owner.drone.action.hold = land, hold
        return counts, cancelled

    async def call(self, h, method, *args, **kwargs):
        with h.sdk_modules():
            return await getattr(h.owner, method)(*args, **kwargs)

    def attempts(self, h):
        if h.owner.recovering:
            return h.owner.report['recovery'].get('rpc_attempts', [])
        return h.owner.report.get('landing_rpc_attempts', [])

    async def test_observation_setter_timeout_uses_current_report_scope(self):
        for recovering in (False, True):
            with self.subTest(recovering=recovering):
                h = self.harness(recovering)
                _, cancelled = self.install_controls(h, pending='position')
                with self.assertRaisesRegex(RecoveryBlocked, 'observation_position'):
                    await asyncio.wait_for(self.call(h, '_hold_for_observation', None), .5)
                self.assertTrue(cancelled.is_set())
                self.assertEqual(self.attempts(h)[-1]['status'], 'unconfirmed')
                self.assertEqual(self.attempts(h)[-1]['remote_effect'], 'unknown')
                if not recovering:
                    self.assertNotIn('recovery', h.owner.report)

    async def test_retreat_target_interruption_and_resume_setters_are_bounded(self):
        for number, name in ((1, 'retreat_target'), (2, 'retreat_hold'), (3, 'retreat_resume')):
            with self.subTest(number=number):
                h = self.harness(True)
                self.install_controls(h, pending='position', position_number=number)
                async def obstructed(*args, **kwargs):
                    return {'safe': False, 'reason': 'fixture_occupied'}
                async def observe(*args):
                    return h.clock.sim, 0.
                h.owner.validate_corridor, h.owner.hold_for_observation = obstructed, observe
                with self.assertRaisesRegex(RecoveryBlocked, name):
                    await asyncio.wait_for(self.call(h, 'retreat_to', [1., 0., 1.], 10., 0.), .5)
                self.assertEqual(len(h.rows('control.position')), number)
                self.assertEqual(self.attempts(h)[-1]['operation'], name)

    async def test_landing_hold_stop_and_land_timeout_do_not_advance_to_next_command(self):
        for pending, name, forbidden in (('position', 'landing_position', 'stop'),
                                         ('stop', 'offboard_stop', 'land'),
                                         ('land', 'land', None)):
            for recovering in (False, True):
                with self.subTest(pending=pending, recovering=recovering):
                    h = self.harness(recovering)
                    self.install_controls(h, pending=pending)
                    with self.assertRaisesRegex(RecoveryBlocked, name):
                        await asyncio.wait_for(self.call(h, 'land', verified=True), .5)
                    if forbidden:
                        self.assertEqual(h.rows('control.'+forbidden), [])
                    self.assertEqual(self.attempts(h)[-1]['status'], 'unconfirmed')
                    self.assertFalse(h.owner.report.get('landed', False))
                    if pending == 'stop':
                        self.assertTrue(h.owner.offboard)
                    if not recovering:
                        self.assertNotIn('recovery', h.owner.report)

    async def test_unverified_landing_initial_hold_is_bounded_before_planner_http(self):
        h = self.harness()
        self.install_controls(h, pending='position')
        with self.assertRaisesRegex(RecoveryBlocked, 'landing_validation_position'):
            await asyncio.wait_for(self.call(h, 'land'), .5)
        self.assertFalse(any(row['path'] == '/stop' for row in h.rows('http')))
        self.assertNotIn('recovery', h.owner.report)

    async def test_descent_reacquisition_each_stage_is_bounded(self):
        for pending, number, name in (('hold', 1, 'descent_hold'),
                                       ('position', 2, 'descent_position'),
                                       ('start', 1, 'descent_offboard_start')):
            with self.subTest(pending=pending):
                h = self.harness(True)
                self.install_controls(h, pending=pending, position_number=number, descend=True)
                async def unsafe(*args, **kwargs):
                    return {'safe': False, 'reason': 'fixture_occupied'}
                h.owner.validate_corridor = unsafe
                with self.assertRaisesRegex(RecoveryBlocked, name):
                    await asyncio.wait_for(self.call(h, 'land', verified=True), .5)
                self.assertFalse(h.owner.offboard)
                self.assertEqual(self.attempts(h)[-1]['operation'], name)

    async def test_descent_reacquisition_requires_mode_confirmation(self):
        h = self.harness(True)
        self.install_controls(h, descend=True, mode_confirmed=False)
        async def unsafe(*args, **kwargs):
            return {'safe': False, 'reason': 'fixture_occupied'}
        h.owner.validate_corridor = unsafe
        with self.assertRaisesRegex(TimeoutError, 'mode_unconfirmed'):
            await self.call(h, 'land', verified=True)
        self.assertFalse(h.owner.offboard)

    async def test_descent_reacquisition_returns_to_recovery_after_mode_predicate(self):
        h = self.harness(True)
        self.install_controls(h, descend=True)
        async def unsafe(*args, **kwargs):
            return {'safe': False, 'reason': 'fixture_occupied'}
        h.owner.validate_corridor = unsafe
        with self.assertRaisesRegex(RecoveryBlocked, 'descent_became_unverified'):
            await self.call(h, 'land', verified=True)
        self.assertTrue(h.owner.offboard)
        names = [row['event'] for row in h.events]
        tail = names[names.index('control.hold'):]
        self.assertEqual([name for name in tail if name.startswith('control.') or name == 'mode.confirmed.fixture'],
                         ['control.hold', 'control.position', 'control.start', 'mode.confirmed.fixture'])
        self.assertFalse(h.owner.report.get('landed', False))

    async def test_normal_landing_return_does_not_fabricate_recovery_record(self):
        h = self.harness()
        self.install_controls(h)
        await self.call(h, 'land', verified=True)
        self.assertNotIn('recovery', h.owner.report)
        self.assertTrue(h.owner.report['landed'])  # Synthetic telemetry only.
        self.assertTrue(h.owner.report['disarmed'])
        self.assertEqual([row['operation'] for row in self.attempts(h)],
                         ['landing_position', 'offboard_stop', 'land'])

    async def test_hover_guard_cancellation_reaches_pending_control(self):
        h = self.harness(True)
        _, cancelled = self.install_controls(h, pending='position')
        h.owner.options['recovery_rpc_timeout_s'] = 5.
        async def watcher():
            await asyncio.sleep(.01)
            raise RecoveryBlocked('fixture_keepout')
        h.owner.watch_hover_keepout = watcher
        with h.sdk_modules(), self.assertRaisesRegex(RecoveryBlocked, 'fixture_keepout'):
            await h.owner.with_hover_guard(h.owner._hold_for_observation(None))
        self.assertTrue(cancelled.is_set())
        self.assertEqual(self.attempts(h)[-1]['status'], 'cancelled')
        self.assertEqual(self.attempts(h)[-1]['remote_effect'], 'unknown')

    async def test_real_run_catches_later_observation_retreat_and_landing_failures(self):
        for stage, name in (('observation', 'observation_position'),
                            ('retreat', 'retreat_target'), ('landing', 'landing_position')):
            with self.subTest(stage=stage):
                h = self.harness()
                self.install_controls(h, pending='position', position_number=3)
                async def observation(*args):
                    if stage == 'observation':
                        return await h.owner._hold_for_observation(None)
                    return h.clock.sim, 0.
                async def corridor(*args, landing=False):
                    return {'safe': not (stage == 'retreat' and landing), 'reason': 'fixture_column'}
                h.owner.hold_for_observation, h.owner.wait_for_corridor = observation, corridor
                if stage == 'retreat':
                    h.owner.breadcrumbs.backwards = lambda _: [[0., 0., 1.], [1., 0., 1.]]
                await asyncio.wait_for(h.run(), 1.)
                self.assertEqual(h.owner.status, 'failed')
                self.assertEqual(h.owner.report['recovery']['outcome'], 'blocked')
                self.assertEqual(h.owner.report['recovery']['rpc_attempts'][-1]['operation'], name)
                self.assertEqual(h.owner.report['recovery']['rpc_attempts'][-1]['remote_effect'], 'unknown')
                self.assertEqual(len(h.rows('scene.pause')), 1)
                self.assertEqual(len(h.rows('sdk.close.fixture')), 1)
                self.assertFalse(h.owner.report.get('landed', False))
                self.assertEqual(h.rows('control.land'), [])

    async def test_disabled_landing_keeps_original_pending_wait_and_no_new_journal(self):
        h = self.harness()
        h.owner.command_revalidation_enabled = False
        self.install_controls(h, pending='position')
        task = asyncio.create_task(self.call(h, 'land', verified=True))
        try:
            await asyncio.sleep(.03)
            self.assertFalse(task.done())
            self.assertEqual(h.rows('control.stop'), [])
            self.assertNotIn('landing_rpc_attempts', h.owner.report)
        finally:
            h.release_replacement.set()
            await task

    async def test_disabled_landing_preserves_original_warning_and_continue_policy(self):
        h = self.harness()
        h.owner.command_revalidation_enabled = False
        self.install_controls(h)
        async def failed(*args):
            raise TimeoutError('fixture_timeout')
        h.owner.drone.offboard.set_position_ned = failed
        h.owner.drone.offboard.stop = failed
        await self.call(h, 'land', verified=True)
        self.assertEqual(len(h.rows('control.land')), 1)
        self.assertIn('WARNING: landing hold: fixture_timeout', h.owner.report['errors'])
        self.assertIn('WARNING: offboard stop: fixture_timeout', h.owner.report['errors'])
        self.assertNotIn('landing_rpc_attempts', h.owner.report)


if __name__ == '__main__':
    unittest.main()
