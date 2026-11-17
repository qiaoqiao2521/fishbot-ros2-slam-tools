"""Replay actual run/recover methods with an explicit fake SDK cache, never ROS.

Recovery observation normally stops at a deliberate fixture boundary. The one
synthetic landing result tests status routing only. No physical hold, landing,
SDK acknowledgement, or real cache replacement is established here.
"""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import test_drone_command_validity as original
from test_drone_command_revalidation_patch import REPAIR, apply, copy_source


class RecoveryBlocked(Exception):
    pass


class ReturnHome(Exception):
    pass


class RecoveryHarness(original.FlightHarness):
    def __init__(self, root, output, trigger='cancel', fault=None):
        with patch.object(original, 'DRONE', root):
            super().__init__(response={'ready': True, 'setpoint': original.command(source_end_sim_s=10.2)})
        self.events = []
        self.cache = {'mode': 'prior_pva'}
        self.trigger, self.fault, self.reads = trigger, fault, 0
        self.replacement_entered, self.release_replacement = asyncio.Event(), asyncio.Event()
        self.pva_entered = asyncio.Event()
        owner = self.owner
        owner.command_revalidation_enabled = True
        owner.station = {'program': [{'action': 'waypoint', 'target': 'goal'}], 'nodes': {}}
        owner.options, owner.offboard, owner.arm_requested = {'planner': 'ego'}, True, True
        owner.telemetry.update(armed=True, landed='IN_AIR', flight_mode='OFFBOARD')
        owner.report.update(errors=[], speed={'requested_max_m_s': 1.8, 'mavsdk_peak_m_s': 0.})
        owner.tasks, owner.output = [], output
        owner.home, owner.orientation = [0., 0., 0.], {'w': 1., 'x': 0., 'y': 0., 'z': 0.}
        owner.tracking_samples = owner.tracking_sum_squares = owner.tracking_peak = 0
        owner.clearance_required = .25
        owner.observer.__dict__.update(contacts={}, minimum_clearance=None, clearance_frames=0,
            invalid_clearance_frames=0, speed_peak=0., speed_peak_by_phase={}, speed_samples=0,
            cruise_fast_s=0., cruise_fast_longest_s=0., cruise_gap_count=0, max_cruise_gap_s=0.,
            cruise_speed_samples=[], cruise_acceleration_peak=0., cruise_jerk_peak=0.,
            max_height=None, minimum_cruise_speed=None)
        owner.scene.__dict__.update(commands=[], motion_epoch_s=None, records=[])

        def phase(name, message):
            owner.phase, owner.message = name, message
            self.note('phase', name=name)

        def pause():
            self.note('scene.pause')
            if self.fault == 'pause_failure':
                raise RuntimeError('fixture_pause_failed')

        def close_scene():
            self.note('scene.close')

        async def connect():
            self.note('connect.fixture')

        async def observation(*args):
            self.note('observation.fixture_boundary')
            if self.fault == 'fixture_landing_success':
                return self.clock.sim, 0.
            raise RecoveryBlocked('fixture_stop_before_observation')

        async def corridor(*args, **kwargs):
            self.note('corridor.safe.fixture')
            return {'safe': True, 'scope': 'fixture'}

        async def land(*, verified):
            self.note('landed.fixture', verified=verified)
            owner.telemetry.update(armed=False, landed='ON_GROUND')
            owner.report.update(landed=True, disarmed=True)

        async def close_sdk():
            self.note('sdk.close.fixture')
            if self.fault == 'cleanup_failure':
                raise RuntimeError('fixture_cleanup_failed')
            self.cache = None
            self.note('sdk.closed.fixture')

        async def sleep(_):
            self.note('sleep.fixture')
            if len(self.events) > 100:
                raise RuntimeError('Fixture loop did not reach its boundary')

        def atomic_json(path, data):
            path.write_text(json.dumps(data))
            self.note('write', name=path.name)

        namespace = owner.goto.__func__.__globals__
        namespace.update(json=json, RecoveryBlocked=RecoveryBlocked, ReturnHome=ReturnHome,
            resolve_position=lambda *args: [5., 0., 1.], MAX_CRUISE_POSE_GAP_S=.25,
            atomic_json=atomic_json, classify=lambda *args, **kwargs: {'scope': 'fixture'})
        namespace['asyncio'] = types.SimpleNamespace(to_thread=namespace['asyncio'].to_thread,
            sleep=sleep, gather=asyncio.gather, wait_for=asyncio.wait_for,
            CancelledError=asyncio.CancelledError)
        selected = original.methods(root/'flight.py', 'Flight',
            ('run', 'recover', 'stop_planner', 'localization_current', 'current_yaw',
             'record_failure', 'block_recovery', 'recovery_command'), namespace)
        for name, method in selected.items():
            setattr(owner, name, types.MethodType(method, owner))
        owner.connect, owner.hold_for_observation, owner.close_mavsdk = connect, observation, close_sdk
        owner.set_phase, owner.scene.pause, owner.scene.close = phase, pause, close_scene
        owner.obstacle_snapshot = lambda: []
        owner.write_status = lambda: atomic_json(output/'status.json', {'status': owner.status})
        owner.ego_request = self.ego_request
        owner.breadcrumbs = types.SimpleNamespace(backwards=lambda point: [list(point)])
        owner.wait_for_corridor, owner.land = corridor, land

        async def position(*payload):
            recovery = owner.phase == 'recovery_hover'
            self.note('position.begin', recovery=recovery, payload=[list(v.values) for v in payload])
            if recovery:
                self.replacement_entered.set()
                if self.fault == 'pending_replacement':
                    await self.release_replacement.wait()
                if self.fault == 'setter_before_accept':
                    raise TimeoutError('fixture_position_rpc_timeout')
            self.cache = {'mode': 'position', 'payload': [list(v.values) for v in payload]}
            self.note('position.accept.fixture', recovery=recovery)
            if recovery and self.fault == 'setter_after_accept':
                raise TimeoutError('fixture_position_response_lost')
            self.note('position.return', recovery=recovery)

        async def pva(*payload):
            self.cache = {'mode': 'pva', 'payload': [list(v.values) for v in payload]}
            self.pva_entered.set()
            if self.fault == 'task_cancel':
                self.note('pva.pending.fixture')
                await asyncio.Event().wait()
            self.note('pva.return')

        async def hold():
            self.note('hold.begin')
            if self.fault == 'hold_failure':
                raise RuntimeError('fixture_hold_failed')
            self.note('hold.return')

        async def start():
            self.note('offboard.start.begin')
            if self.fault == 'start_failure':
                raise RuntimeError('fixture_start_failed')
            if self.fault != 'mode_unconfirmed':
                owner.telemetry['flight_mode'] = 'OFFBOARD'
            self.note('offboard.start.return')

        async def wait_until(predicate, *args, **kwargs):
            if not predicate():
                raise TimeoutError('fixture_mode_unconfirmed')
            self.note('mode.confirmed.fixture')

        owner.wait_until = wait_until
        owner.drone = types.SimpleNamespace(action=types.SimpleNamespace(hold=hold),
            offboard=types.SimpleNamespace(set_position_ned=position,
                set_position_velocity_acceleration_ned=pva, start=start))

    def note(self, event, **details):
        self.events.append(dict(event=event, cache=copy.deepcopy(self.cache),
            reference=copy.deepcopy(self.owner.reference), **details))

    def ego_request(self, path, body=None):
        self.note('http', path=path)
        if path == '/state':
            self.reads += 1
            if self.reads == 2:
                self.note('trigger', kind=self.trigger)
                if self.trigger == 'cancel':
                    self.cancelled = True
                else:
                    self.advance(10.4)
                if self.fault == 'localization':
                    self.owner.position_valid = False
                if self.fault in ('takeover', 'hold_failure', 'start_failure', 'mode_unconfirmed'):
                    self.owner.telemetry['flight_mode'] = 'LAND'
                if self.fault == 'unknown_arm':
                    self.owner.telemetry.update(armed=None, flight_mode='LAND')
                if self.fault == 'already_grounded':
                    self.owner.telemetry.update(armed=False, landed='ON_GROUND')
            return copy.deepcopy(self.response)
        if path == '/stop' and self.fault == 'stop_failure':
            raise OSError('fixture_planner_unreachable')
        return {'accepted': True}

    async def run(self):
        with self.sdk_modules():
            return await self.owner.run()

    def rows(self, name):
        return [row for row in self.events if row['event'] == name]


class RecoveryCacheChain(unittest.IsolatedAsyncioTestCase):
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
        return RecoveryHarness(self.root, Path(directory.name), **kwargs)

    def assert_finished_failed(self, h):
        self.assertTrue(h.owner.finished)
        self.assertEqual(h.owner.status, 'failed')
        report = json.loads((h.owner.output/'report.json').read_text())
        self.assertFalse(report['passed'])
        self.assertFalse(report.get('landed', False))
        self.assertEqual(report['recovery']['outcome'], 'blocked')
        self.assertEqual(len(h.rows('sdk.close.fixture')), 1)
        return report

    async def test_cancel_and_expiry_route_through_real_run_and_replace_before_stop(self):
        for trigger in ('cancel', 'expired'):
            with self.subTest(trigger=trigger):
                h = self.harness(trigger=trigger)
                self.assertFalse(await h.run())
                report = self.assert_finished_failed(h)
                self.assertEqual(len(h.rows('pva.return')), 1)
                self.assertEqual(h.rows('trigger')[0]['cache']['mode'], 'pva')
                stop = next(row for row in h.rows('http') if row['path'] == '/stop')
                self.assertEqual(stop['cache']['mode'], 'position')
                self.assertEqual(stop['reference']['mode'], 'position')
                self.assertEqual(stop['cache']['payload'], [[0., 0., -1., 90.]])
                names = [row['event'] for row in h.events]
                self.assertLess(names.index('pva.return'), names.index('trigger'))
                self.assertLess(names.index('trigger'), names.index('observation.fixture_boundary'))
                self.assertEqual(report['recovery']['trigger'], 'operator_cancel' if trigger == 'cancel'
                                 else 'cached_command_source_expired')
                self.assertTrue(report['recovery']['simulation_pause_confirmed'])
                self.assertIsNone(h.cache)

    async def test_pending_replacement_blocks_planner_stop_and_cleanup_until_return(self):
        h = self.harness(fault='pending_replacement')
        task = asyncio.create_task(h.run())
        try:
            await asyncio.wait_for(h.replacement_entered.wait(), 1.)
            self.assertEqual(h.cache['mode'], 'pva')
            self.assertEqual(h.owner.reference['mode'], 'position_velocity_acceleration')
            self.assertFalse(any(row['path'] == '/stop' for row in h.rows('http')))
            self.assertEqual(h.rows('scene.pause'), [])
            self.assertEqual(h.rows('sdk.close.fixture'), [])
        finally:
            h.release_replacement.set()
            await task
        self.assert_finished_failed(h)

    async def test_return_home_nested_faults_use_same_replacement_before_stop(self):
        for cancel, trigger in ((True, 'cancel_during_return_home'), (False, 'return_home_fault')):
            with self.subTest(cancel=cancel):
                h = self.harness()

                def request_return():
                    raise ReturnHome()

                async def return_home(*, operator):
                    h.note('return_home.fixture', operator=operator)
                    if cancel:
                        raise original.CancelFlight()
                    raise RuntimeError('fixture_return_home_fault')

                h.owner.check_operator = request_return
                h.owner.return_home = return_home
                with h.sdk_modules():
                    # Prime the actual setter/reference path before the operator event.
                    await h.owner.setpoint([1., 0., 1.], .25, [.2, .1, 0.], [.01, 0., 0.])
                    await h.owner.run()
                report = self.assert_finished_failed(h)
                self.assertEqual(report['recovery']['trigger'], trigger)
                self.assertFalse(h.rows('return_home.fixture')[0]['operator'])
                self.assertEqual(len(h.rows('pva.return')), 1)
                stop = next(row for row in h.rows('http') if row['path'] == '/stop')
                self.assertEqual(stop['cache']['mode'], 'position')
                self.assertEqual(stop['reference']['mode'], 'position')
                self.assertEqual(stop['cache']['payload'], [[0., 0., -1., 90.]])
                self.assertEqual(len([row for row in h.rows('position.return') if row['recovery']]), 1)

    async def test_failed_setter_does_not_prove_cache_was_or_was_not_replaced(self):
        for fault, cache_mode in (('setter_before_accept', 'pva'), ('setter_after_accept', 'position')):
            with self.subTest(fault=fault):
                h = self.harness(fault=fault)
                await h.run()
                report = self.assert_finished_failed(h)
                pause = h.rows('scene.pause')[0]
                self.assertEqual(pause['cache']['mode'], cache_mode)
                self.assertEqual(pause['reference']['mode'], 'position_velocity_acceleration')
                self.assertFalse(any(row['path'] == '/stop' for row in h.rows('http')))
                self.assertIn('TimeoutError', report['recovery']['reason'])

    async def test_localization_loss_blocks_before_cache_replacement(self):
        h = self.harness(trigger='expired', fault='localization')
        await h.run()
        report = self.assert_finished_failed(h)
        self.assertEqual(report['recovery']['reason'], 'localization_unavailable')
        self.assertEqual(h.rows('scene.pause')[0]['cache']['mode'], 'pva')
        self.assertEqual(len(h.rows('position.begin')), 1)  # New-goal hold only.

    async def test_control_takeover_orders_hold_position_start_mode_before_stop(self):
        h = self.harness(fault='takeover')
        await h.run()
        report = self.assert_finished_failed(h)
        events = [row['event'] for row in h.events]
        sequence = ['hold.begin', 'hold.return', 'offboard.start.begin',
                    'offboard.start.return', 'mode.confirmed.fixture']
        self.assertEqual([name for name in events if name in sequence], sequence)
        position_index = next(index for index, row in enumerate(h.events)
                              if row['event'] == 'position.return' and row['recovery'])
        stop_index = next(index for index, row in enumerate(h.events)
                          if row['event'] == 'http' and row['path'] == '/stop')
        self.assertLess(events.index('hold.return'), position_index)
        self.assertLess(position_index, events.index('offboard.start.begin'))
        self.assertLess(events.index('mode.confirmed.fixture'), stop_index)
        start = h.rows('offboard.start.begin')[0]
        self.assertEqual(start['cache']['mode'], 'position')
        self.assertEqual(report['recovery']['control_takeover']['confirmed_mode'], 'OFFBOARD')

    async def test_takeover_failure_boundaries_preserve_distinct_cache_states(self):
        for fault, cache_mode in (('hold_failure', 'pva'), ('unknown_arm', 'pva'),
                                 ('start_failure', 'position'), ('mode_unconfirmed', 'position')):
            with self.subTest(fault=fault):
                h = self.harness(fault=fault)
                await h.run()
                self.assert_finished_failed(h)
                self.assertEqual(h.rows('scene.pause')[0]['cache']['mode'], cache_mode)
                self.assertFalse(any(row['path'] == '/stop' for row in h.rows('http')))
                self.assertNotIn('control_takeover', h.owner.report['recovery'])

    async def test_planner_stop_failure_warns_after_cache_replacement(self):
        h = self.harness(fault='stop_failure')
        await h.run()
        report = self.assert_finished_failed(h)
        self.assertIn('WARNING: planner stop: fixture_planner_unreachable', report['errors'])
        self.assertEqual(h.rows('observation.fixture_boundary')[0]['cache']['mode'], 'position')

    async def test_pause_failure_does_not_claim_pause_confirmation(self):
        h = self.harness(fault='pause_failure')
        await h.run()
        report = self.assert_finished_failed(h)
        self.assertNotIn('simulation_pause_confirmed', report['recovery'])
        self.assertTrue(any('fixture_pause_failed' in error for error in report['errors']))

    async def test_cleanup_failure_retains_failure_without_claiming_cache_cleared(self):
        h = self.harness(fault='cleanup_failure')
        await h.run()
        report = self.assert_finished_failed(h)
        self.assertEqual(h.cache['mode'], 'position')
        self.assertEqual(report['cleanup_errors'], ['MAVSDK cleanup: fixture_cleanup_failed'])

    async def test_grounded_early_return_skips_replacement_and_uses_reported_ground_state(self):
        h = self.harness(fault='already_grounded')
        await h.run()
        self.assertEqual(h.owner.status, 'cancelled')
        self.assertEqual(h.owner.report['recovery']['outcome'], 'landed')
        self.assertTrue(h.owner.report['landed'])
        self.assertEqual(len(h.rows('position.begin')), 1)
        self.assertEqual(h.rows('sdk.close.fixture')[0]['cache']['mode'], 'pva')
        self.assertFalse(h.owner.report['passed'])

    async def test_recovery_return_cannot_upgrade_failed_task_to_success(self):
        for trigger, status in (('cancel', 'cancelled'), ('expired', 'failed')):
            with self.subTest(trigger=trigger):
                h = self.harness(trigger=trigger, fault='fixture_landing_success')
                await h.run()
                self.assertEqual(h.owner.status, status)
                self.assertEqual(h.owner.report['recovery']['outcome'], 'landed')
                self.assertEqual(h.rows('landed.fixture')[0]['cache']['mode'], 'position')
                self.assertTrue(h.rows('landed.fixture')[0]['verified'])
                self.assertFalse(h.owner.report['passed'])

    async def test_never_armed_cancel_skips_recovery_and_motion(self):
        h = self.harness()
        h.cancelled = True
        h.owner.arm_requested = False
        h.owner.telemetry.update(armed=False, landed='ON_GROUND')
        await h.run()
        self.assertEqual(h.owner.status, 'cancelled')
        self.assertTrue(h.owner.report['cancelled_before_takeoff'])
        self.assertNotIn('recovery', h.owner.report)
        self.assertEqual(h.rows('position.begin') + h.rows('pva.return'), [])

    async def test_observed_boundary_task_cancel_skips_business_recovery(self):
        h = self.harness(fault='task_cancel')
        task = asyncio.create_task(h.run())
        try:
            await asyncio.wait_for(h.pva_entered.wait(), 1.)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(h.owner.finished)
        self.assertNotIn('recovery', h.owner.report)
        self.assertEqual(h.rows('scene.pause'), [])
        self.assertFalse(any(row['path'] == '/stop' for row in h.rows('http')))
        self.assertEqual(h.rows('sdk.close.fixture')[0]['cache']['mode'], 'pva')
        self.assertFalse(h.owner.report['passed'])
        self.assertTrue((h.owner.output/'report.json').exists())


if __name__ == '__main__':
    unittest.main()
