"""Apply the repair only to temporary files and replay real frozen methods."""
import ast
import asyncio
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

import test_drone_command_validity as original


TOOLS = Path(__file__).resolve().parents[1]/'workbench-tools'
REPAIR = TOOLS/'patches/drone-command-revalidation.patch'
SENDER = TOOLS/'patches/drone-handoff-sender.patch'


def apply(root, patchfile):
    subprocess.run(['git', 'apply', '--check', '--whitespace=error-all', str(patchfile)],
                   cwd=root, check=True, capture_output=True)
    subprocess.run(['git', 'apply', str(patchfile)], cwd=root, check=True, capture_output=True)


def copy_source(root):
    for name in ('flight.py', 'frames.py', 'scene.py', 'ego/sidecar.py', 'ego/run_sidecar.sh'):
        path = root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original.DRONE/name, path)


class RevalidationPatch(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        copy_source(cls.root)
        apply(cls.root, REPAIR)
        compile((cls.root/'flight.py').read_text(), str(cls.root/'flight.py'), 'exec')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def harness(self, enabled=True, **kwargs):
        with patch.object(original, 'DRONE', self.root):
            instance = original.FlightHarness(**kwargs)
        instance.owner.command_revalidation_enabled = enabled
        return instance

    def test_real_constructor_option_defaults_off_and_only_one_enables(self):
        tree = ast.parse((self.root/'flight.py').read_text())
        assignment = next(node for node in ast.walk(tree) if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Attribute) and target.attr == 'command_revalidation_enabled'
                    for target in node.targets))
        for setting in (None, '0', 'false', '1'):
            with self.subTest(setting=setting), patch.dict(os.environ, {}, clear=True):
                if setting is not None:
                    os.environ['DRONE_REVALIDATE_COMMAND'] = setting
                owner = types.SimpleNamespace()
                exec(compile(ast.Module(body=[assignment], type_ignores=[]), 'option', 'exec'), {'self': owner, 'os': os})
                self.assertEqual(owner.command_revalidation_enabled, setting == '1')

    async def test_disabled_repair_preserves_old_cancel_and_source_expiry_behavior(self):
        for scenario in ('cancel', 'source_expired'):
            with self.subTest(scenario=scenario):
                response = {'ready': True, 'setpoint': original.command(source_end_sim_s=10.2)}
                hook = ((lambda h: setattr(h, 'cancelled', True)) if scenario == 'cancel'
                        else (lambda h: h.advance(10.4)))
                old = original.FlightHarness(response=response, response_hook=hook)
                off = self.harness(enabled=False, response=response, response_hook=hook)
                for h in (old, off):
                    with self.assertRaises((original.CancelFlight, original.ProbeComplete)):
                        await h.goto()
                self.assertEqual(old.calls, off.calls)
                self.assertEqual(len(off.pva_calls), 1)

    async def test_cancel_during_http_never_sends_pva_even_without_operator_handling(self):
        for operator in (True, False):
            with self.subTest(operator=operator):
                h = self.harness(response_hook=lambda h: setattr(h, 'cancelled', True))
                with h.sdk_modules(), self.assertRaises(original.CancelFlight):
                    await h.owner.goto([5., 0., 1.], use_ego=True, operator=operator)
                self.assertEqual(h.pva_calls, [])

    async def test_return_home_during_http_is_rechecked_when_operator_enabled(self):
        class ReturnHome(Exception):
            pass
        h = self.harness(response_hook=lambda h: setattr(h, 'returning', True))
        def check():
            if getattr(h, 'returning', False):
                raise ReturnHome()
        h.owner.check_operator = check
        with self.assertRaises(ReturnHome):
            await h.goto()
        self.assertEqual(h.pva_calls, [])

    async def test_source_expiring_during_http_is_rejected_with_sample_still_fresh(self):
        h = self.harness(response={'ready': True, 'setpoint': original.command(source_end_sim_s=10.2)},
                         response_hook=lambda h: h.advance(10.4))
        with self.assertRaisesRegex(RuntimeError, '轨迹已结束'):
            await h.goto()
        self.assertEqual(h.pva_calls, [])

    async def test_sidecar_sample_readiness_is_rechecked_without_relaxing_flight_window(self):
        h = self.harness(response_hook=lambda h: h.advance(10.5))
        with self.assertRaisesRegex(RuntimeError, '轨迹样本已过期'):
            await h.goto()
        self.assertEqual(h.pva_calls, [])

    async def test_source_grace_and_normal_fresh_command_still_send(self):
        for end in (11., 10.3):
            with self.subTest(end=end):
                h = self.harness(response={'ready': True, 'setpoint': original.command(source_end_sim_s=end)},
                                 response_hook=lambda h: h.advance(10.4))
                with self.assertRaises(original.ProbeComplete):
                    await h.goto()
                self.assertEqual(len(h.pva_calls), 1)

    async def test_deadline_decisions_agree_with_real_sidecar_at_dispatch_time(self):
        cases = [original.command(source_end_sim_s=11.),
                 original.command(source_end_sim_s=10.3),
                 original.command(source_end_sim_s=10.2),
                 original.command(stamp_sim_s=10.05),
                 original.command(position=[5., 0., 1.], velocity=[0.]*3,
                                  acceleration=[0.]*3, source_end_sim_s=9.),
                 original.command(position=[5., 0., 1.], velocity=[.01, 0., 0.],
                                  acceleration=[0.]*3, source_end_sim_s=9.)]
        for point in cases:
            with self.subTest(point=point):
                state = original.sidecar(original.Clock(10.4), point).state()
                h = self.harness(response={'ready': True, 'setpoint': point},
                                 response_hook=lambda h: h.advance(10.4))
                with self.assertRaises(original.ProbeComplete if state['ready'] else RuntimeError):
                    await h.goto()
                self.assertEqual(bool(h.pva_calls), state['ready'])

    async def test_real_goal_hold_exception_survives_expiry_even_from_old_trajectory_mode(self):
        point = original.command(position=[5., 0., 1.], velocity=[0.]*3,
                                 acceleration=[0.]*3, source_end_sim_s=9., mode='trajectory')
        h = self.harness(response={'ready': True, 'setpoint': point})
        with self.assertRaises(original.ProbeComplete):
            await h.goto()
        self.assertEqual(len(h.pva_calls), 1)

    async def test_goal_hold_label_cannot_exempt_nonzero_feedforward_or_wrong_target(self):
        for changes in ({'velocity': [.01, 0., 0.]}, {'position': [1., 0., 1.]}, {'acceleration': [0., .01, 0.]}):
            with self.subTest(changes=changes):
                point = original.command(position=[5., 0., 1.], velocity=[0.]*3,
                    acceleration=[0.]*3, source_end_sim_s=9., mode='goal_hold')
                point.update(changes)
                h = self.harness(response={'ready': True, 'setpoint': point})
                with self.assertRaisesRegex(RuntimeError, '轨迹已结束'):
                    await h.goto()
                self.assertEqual(h.pva_calls, [])

    async def test_missing_or_nonfinite_source_deadline_never_dispatches(self):
        for end in (None, float('nan'), float('inf'), 'missing'):
            with self.subTest(end=end):
                point = original.command(source_end_sim_s=end)
                if end == 'missing':
                    point.pop('source_end_sim_s')
                h = self.harness(response={'ready': True, 'setpoint': point})
                with self.assertRaisesRegex(RuntimeError, '轨迹源期限不可用'):
                    await h.goto()
                self.assertEqual(h.pva_calls, [])

    async def test_existing_sample_age_and_identity_rejections_survive(self):
        for point in (original.command(stamp_sim_s=9.), original.command(goal_id='other')):
            h = self.harness(response={'ready': True, 'setpoint': point},
                             response_hook=lambda h: h.advance(10.15, wall=111.))
            with self.assertRaises(RuntimeError):
                await h.goto()
            self.assertEqual(h.pva_calls, [])

    async def test_same_future_tolerance_is_preserved_not_relabelled_as_epoch_detection(self):
        h = self.harness(response_hook=lambda h: h.advance(10.1))
        with self.assertRaises(original.ProbeComplete):
            await h.goto()
        self.assertEqual(len(h.pva_calls), 1)

    async def test_inputs_expiring_during_http_are_rechecked_at_existing_limits(self):
        scenarios = [lambda h: setattr(h.owner.scene, 'failure', 'stopped'),
                     lambda h: setattr(h.owner, 'position_valid', False),
                     lambda h: setattr(h.owner, 'position_received', 90.),
                     lambda h: setattr(h.owner.observer, 'clock_received', 90.),
                     lambda h: h.advance(10.15, wall=201.)]
        for hook in scenarios:
            h = self.harness(response_hook=hook)
            with self.assertRaises((RuntimeError, TimeoutError)):
                await h.goto()
            self.assertEqual(h.pva_calls, [])

    async def test_observed_boundary_inflight_rpc_is_not_made_atomic_by_dispatch_guard(self):
        h = self.harness(sdk_hook=lambda h: setattr(h, 'cancelled', h.calls[-1]['mode'] == 'pva'))
        with self.assertRaises(original.CancelFlight):
            await h.goto()
        self.assertEqual(len(h.pva_calls), 1)
        self.assertFalse(h.pva_calls[0]['cancelled_at_call'])

    async def land_observation(self, enabled, rewound, during_query=True):
        clock = original.Clock(10.)
        validations, actions = [], []
        owner = types.SimpleNamespace(command_revalidation_enabled=enabled,
            options={}, recovering=False,
            telemetry={'landed': 'IN_AIR', 'armed': True},
            observer=types.SimpleNamespace(simulation_s=10., pose=None), offboard=False,
            pose={'position': [0., 0., 1.]}, home=[0., 0., 0.], report={'errors': []},
            localization_current=lambda: True, set_phase=lambda *_: None)
        async def stop():
            pass
        async def land():
            actions.append('land')
        async def validate(*_, **__):
            validations.append(owner.observer.simulation_s)
            if rewound and during_query and len(validations) == 1:
                owner.observer.simulation_s = clock.sim = 5.
            return {'safe': True}
        ticks = [5.1, 5.21] if rewound and during_query else ([5., 5.21] if rewound else [10.1, 10.21])
        async def sleep(_):
            if not ticks:
                raise original.ProbeComplete()
            owner.observer.simulation_s = clock.sim = ticks.pop(0)
        owner.stop_planner, owner.validate_corridor = stop, validate
        owner.drone = types.SimpleNamespace(action=types.SimpleNamespace(land=land))
        namespace = dict(asyncio=types.SimpleNamespace(sleep=sleep, wait_for=asyncio.wait_for,
            CancelledError=asyncio.CancelledError), time=clock, math=original.math, RecoveryBlocked=RuntimeError)
        methods = original.methods(self.root/'flight.py', 'Flight', ('land', 'recovery_command'), namespace)
        owner.recovery_command = types.MethodType(methods['recovery_command'], owner)
        method = methods['land']
        with self.assertRaises(original.ProbeComplete):
            await method(owner, verified=True)
        return validations, actions

    async def test_land_revalidates_after_rewind_inside_or_between_queries(self):
        for during_query in (True, False):
            off, actions_off = await self.land_observation(False, True, during_query)
            on, actions_on = await self.land_observation(True, True, during_query)
            self.assertEqual(off, [10.])
            self.assertEqual(on[:2], [10., 5.1 if during_query else 5.])
            self.assertEqual(actions_off, actions_on)

    async def test_land_normal_point_two_second_cadence_is_unchanged(self):
        self.assertEqual(await self.land_observation(False, False), await self.land_observation(True, False))
        self.assertEqual((await self.land_observation(True, False))[0], [10., 10.21])

    async def test_sender_observer_patch_composes_in_either_order(self):
        for order in ((REPAIR, SENDER), (SENDER, REPAIR)):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                copy_source(root)
                for patchfile in order:
                    apply(root, patchfile)
                with patch.object(original, 'DRONE', root):
                    h = original.FlightHarness()
                h.owner.command_revalidation_enabled = True
                h.owner.handoff_observation = None
                with self.assertRaises(original.ProbeComplete):
                    await h.goto()
                self.assertEqual(len(h.pva_calls), 1)


if __name__ == '__main__':
    unittest.main()
