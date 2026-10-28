"""Local epoch contract on temporary real methods, no ROS/SDK/flight."""
import importlib.util
import itertools
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import test_drone_command_validity as original
from test_drone_command_revalidation_patch import TOOLS, REPAIR, SENDER, apply, copy_source

EPOCH = TOOLS/'patches/drone-command-epoch.patch'


class CommandEpochPatch(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        copy_source(cls.root)
        apply(cls.root, EPOCH)
        spec = importlib.util.spec_from_file_location('epoch_fixture', cls.root/'command_epoch.py')
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def guard(self, enabled=True):
        with patch.dict(os.environ, {'DRONE_COMMAND_EPOCH': '1' if enabled else '0'}):
            return self.module.CommandEpoch()

    def node(self, enabled=True):
        with patch.object(original, 'DRONE', self.root):
            node = original.sidecar(original.Clock())
        clock = node.state.__func__.__globals__['time']
        node.command_epoch = self.guard(enabled)
        node.latest_trajectory = None
        ns = node.state.__func__.__globals__
        ns['String'] = lambda **kw: types.SimpleNamespace(**kw)
        for name, method in original.methods(self.root/'ego/sidecar.py', 'Sidecar',
                ('rotate_command_epoch', 'observe_command_epoch', 'on_goal_ack'), ns).items():
            setattr(node, name, types.MethodType(method, node))
        node.setpoint['command_epoch'] = node.command_epoch.token
        node.state()  # Establish the first clock observation.
        return node, clock

    def post(self, node, path, body):
        with patch.object(original, 'DRONE', self.root):
            return original.post(node, path, body)

    def message(self, trajectory=7):
        v = types.SimpleNamespace(x=1., y=0., z=1.)
        return types.SimpleNamespace(trajectory_id=trajectory, position=v, velocity=v,
            acceleration=v, yaw=0., header=types.SimpleNamespace(
                stamp=types.SimpleNamespace(sec=10, nanosec=150000000)))

    def test_default_off_requires_explicit_one(self):
        for setting in (None, '0', 'false', '1'):
            with self.subTest(setting=setting), patch.dict(os.environ, {}, clear=True):
                if setting is not None:
                    os.environ['DRONE_COMMAND_EPOCH'] = setting
                self.assertEqual(self.module.CommandEpoch().enabled, setting == '1')

    def test_epoch_patch_and_existing_sender_revalidation_compose_in_all_orders(self):
        for patches in itertools.permutations([EPOCH, REPAIR, SENDER]):
            with self.subTest(order=[p.name for p in patches]), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                copy_source(root)
                for p in patches:
                    apply(root, p)
                for name in ('flight.py', 'ego/sidecar.py', 'command_epoch.py'):
                    compile((root/name).read_text(), str(root/name), 'exec')

    def test_rewind_invalidates_once_even_when_clock_recovers_same_value(self):
        guard = self.guard()
        token = guard.token
        guard.observe(10., 100.)
        self.assertEqual(guard.observe(9.99, 100.01), 'clock_rewind')
        changed = guard.token
        self.assertNotEqual(changed, token)
        guard.observe(10., 100.02)
        self.assertEqual(guard.token, changed)

    def test_stall_and_resume_do_not_silently_reuse_pre_pause_epoch(self):
        for observe_during_pause in (True, False):
            with self.subTest(observe_during_pause=observe_during_pause):
                guard = self.guard()
                guard.observe(10., 100.)
                token = guard.token
                if observe_during_pause:
                    self.assertEqual(guard.observe(10., 102.01), 'clock_stalled')
                    paused = guard.token
                    guard.observe(10., 102.02)
                    self.assertEqual(guard.token, paused)
                guard.observe(10.1, 102.1)
                self.assertNotEqual(guard.token, token)

    def test_state_rewind_clears_goal_ack_samples_curves_and_queue_before_reacceptance(self):
        node, clock = self.node()
        old = node.command_epoch.token
        node.requests.put({'type': 'goal', 'goal_id': 'goal-A'})
        clock.sim -= .01
        state = node.state()
        self.assertNotEqual(state['command_epoch'], old)
        self.assertIsNone(state['setpoint'])
        self.assertIsNone(node.active_goal)
        self.assertFalse(node.goal_acknowledged)
        self.assertEqual(node.trajectory_times, {})
        self.assertTrue(node.requests.empty())
        self.assertEqual(node.stops, ['123'])
        # Even a numerically matching old ACK cannot reactivate the cleared goal.
        node.on_goal_ack(types.SimpleNamespace(data='123:6'))
        node.on_command(self.message())
        self.assertFalse(node.goal_acknowledged)
        self.assertIsNone(node.setpoint)

    def test_stop_rotates_epoch_while_clock_is_paused(self):
        node, clock = self.node()
        old = node.command_epoch.token
        clock.wall += 3.
        reply = self.post(node, '/stop', {'task_id': 'task-A'})
        self.assertEqual(reply[0][0], 202)
        self.assertNotEqual(reply[0][1]['command_epoch'], old)
        self.assertIsNone(node.setpoint)
        self.assertEqual(node.trajectory_times, {})

    def test_new_goal_rotates_epoch_and_command_uses_only_current_known_curve(self):
        node, _ = self.node()
        old = node.command_epoch.token
        reply = self.post(node, '/goal', dict(x=5., y=0., z=1., task_id='task-A', goal_id='goal-B'))
        self.assertEqual(reply[0][0], 202)
        current = reply[0][1]['command_epoch']
        self.assertNotEqual(current, old)
        self.assertFalse(node.goal_acknowledged)
        self.assertEqual(node.trajectory_times, {})
        node.on_goal_ack(types.SimpleNamespace(data=f'{node.goal_stamp_ns}:7'))
        node.on_command(self.message(8))
        self.assertIsNone(node.setpoint)
        node.trajectory_times[8] = (10., 11.)  # Explicit synthetic new curve receipt.
        node.on_command(self.message(8))
        self.assertEqual(node.setpoint['command_epoch'], current)
        self.assertEqual(node.setpoint['goal_id'], 'goal-B')

    def test_native_ack_stamp_does_not_collide_after_clock_rewind(self):
        node, clock = self.node()
        goal = dict(x=5., y=0., z=1., task_id='task-A', goal_id='same-id')
        self.post(node, '/goal', goal)
        first = node.goal_stamp_ns
        clock.sim -= 1e-9  # Original sim_ns+sequence can equal the old stamp.
        self.post(node, '/goal', goal)
        self.assertEqual(node.get_clock().now().nanoseconds + node.goal_sequence, first)
        self.assertGreater(node.goal_stamp_ns, first)
        node.on_goal_ack(types.SimpleNamespace(data=f'{first}:7'))
        self.assertFalse(node.goal_acknowledged)
        node.on_goal_ack(types.SimpleNamespace(data=f'{node.goal_stamp_ns}:7'))
        self.assertTrue(node.goal_acknowledged)

    def test_unacknowledged_or_below_floor_bspline_cannot_be_registered(self):
        node, _ = self.node()
        ns = node.state.__func__.__globals__
        method = original.methods(self.root/'ego/sidecar.py', 'Sidecar', ('on_bspline',), ns)['on_bspline']
        node.trajectory_times.clear()
        for acknowledged, trajectory in [(False, 8), (True, 6)]:
            with self.subTest(acknowledged=acknowledged, trajectory=trajectory):
                node.goal_acknowledged = acknowledged
                msg = types.SimpleNamespace(order=3, knots=[0., 0., 0., 0., 1., 1., 1., 1.],
                    start_time=types.SimpleNamespace(sec=10, nanosec=0), traj_id=trajectory)
                method(node, msg)
                self.assertEqual(node.trajectory_times, {})
                self.assertIsNone(node.latest_trajectory)

    def test_tick_drops_old_epoch_queue_even_when_goal_id_is_reused(self):
        node, clock = self.node()
        goal = dict(x=5., y=0., z=1., task_id='task-A', goal_id='same-id')
        first = self.post(node, '/goal', goal)[0][1]['command_epoch']
        second = self.post(node, '/goal', goal)[0][1]['command_epoch']
        self.assertNotEqual(first, second)
        self.assertEqual(node.requests.qsize(), 2)
        emitted = []
        node.goal_pub.publish = emitted.append
        node.flush_depth = node.flush_lidar = lambda: None
        node.processes, node.history = [], []
        node.last_clock, node.last_logged_reason = clock.sim, None
        node.get_logger = lambda: types.SimpleNamespace(info=lambda _: None)
        ns = node.state.__func__.__globals__
        ns['json'] = json
        ns['PoseStamped'] = lambda: types.SimpleNamespace(
            header=types.SimpleNamespace(stamp=types.SimpleNamespace()),
            pose=types.SimpleNamespace(position=types.SimpleNamespace(), orientation=types.SimpleNamespace()))
        tick = original.methods(self.root/'ego/sidecar.py', 'Sidecar', ('tick',), ns)['tick']
        tick(node)
        self.assertEqual(len(emitted), 1)
        self.assertTrue(node.requests.empty())
        self.assertEqual(emitted[0].header.stamp.sec*10**9 + emitted[0].header.stamp.nanosec,
                         node.goal_stamp_ns)

    def test_reply_epoch_is_captured_inside_acceptance_lock(self):
        node, _ = self.node()
        lock = node.lock
        class ConcurrentGoalAfterUnlock:
            depth, injected = 0, False
            def __enter__(self):
                lock.acquire()
                self.depth += 1
                return self
            def __exit__(self, *args):
                self.depth -= 1
                lock.release()
                if not self.depth and not self.injected and node.active_goal['goal_id'] == 'new-A':
                    self.injected = True
                    node.test_epoch_A = node.command_epoch.token
                    node.test_post(node, '/goal', dict(x=6., y=0., z=1., task_id='task-A', goal_id='new-B'))
        node.test_post = self.post
        node.lock = ConcurrentGoalAfterUnlock()
        reply = self.post(node, '/goal', dict(x=5., y=0., z=1., task_id='task-A', goal_id='new-A'))
        self.assertEqual(reply[0][1]['command_epoch'], node.test_epoch_A)
        self.assertNotEqual(reply[0][1]['command_epoch'], node.command_epoch.token)
        self.assertEqual(node.active_goal['goal_id'], 'new-B')

    def test_wrong_owner_stop_does_not_rotate_valid_epoch(self):
        node, _ = self.node()
        epoch = node.command_epoch.token
        reply = self.post(node, '/stop', {'task_id': 'other-task'})
        self.assertEqual(reply[0][0], 409)
        self.assertEqual(node.command_epoch.token, epoch)
        self.assertIsNotNone(node.setpoint)

    def test_real_observer_callback_detects_rewind_and_catch_up(self):
        guard = self.guard()
        clock = original.Clock()
        owner = types.SimpleNamespace(command_epoch=guard, simulation_s=None)
        method = original.methods(self.root/'flight.py', 'GazeboObserver', ('on_clock',), {'time': clock})['on_clock']
        for stamp in [10, 9, 10]:
            method(owner, types.SimpleNamespace(sim=types.SimpleNamespace(sec=stamp, nsec=0)))
            if stamp == 10 and not hasattr(owner, 'original_epoch'):
                owner.original_epoch = guard.token
        self.assertNotEqual(guard.token, owner.original_epoch)
        self.assertEqual(owner.simulation_s, 10.)

    def test_disabled_sidecar_keeps_preexisting_small_rewind_behavior_and_schema(self):
        node, clock = self.node(enabled=False)
        del node.setpoint['command_epoch']
        clock.sim -= .01
        result = node.state()
        self.assertTrue(result['ready'])
        self.assertNotIn('command_epoch', result)
        self.assertIsNotNone(node.active_goal)
        self.assertEqual(node.stops, [])

    def flight(self, scenario=None, enabled=True):
        response = {'ready': True, 'command_epoch': 'goal-epoch-A',
                    'setpoint': original.command(command_epoch='goal-epoch-A')}
        with patch.object(original, 'DRONE', self.root):
            h = original.FlightHarness(response=response)
        h.owner.command_revalidation_enabled = True
        h.owner.handoff_observation = None
        h.owner.observer.command_epoch = guard = self.guard(enabled)
        guard.observe(h.clock.sim, h.clock.wall)
        real = h.owner.ego_request
        def request(path, body=None):
            result = real(path, body)
            if path == '/goal':
                if scenario == 'goal_rewind':
                    guard.observe(h.clock.sim-.01, h.clock.wall+.01)
                    guard.observe(h.clock.sim, h.clock.wall+.02)
                return {'accepted': True} if scenario == 'missing_goal_epoch' else {
                    'accepted': True, 'command_epoch': 'goal-epoch-A'}
            if path == '/state':
                if scenario == 'rewind_and_catch_up':
                    guard.observe(h.clock.sim-.01, h.clock.wall+.01)
                    guard.observe(h.clock.sim, h.clock.wall+.02)
                if scenario == 'stalled_resume':
                    guard.observe(h.clock.sim+.01, h.clock.wall+3.)
                if scenario == 'state_epoch': result['command_epoch'] = 'goal-epoch-B'
                if scenario == 'sample_epoch': result['setpoint']['command_epoch'] = 'goal-epoch-B'
            return result
        h.owner.ego_request = request
        return h

    async def test_composed_methods_keep_epoch_cancel_and_source_expiry_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_source(root)
            for repair in (REPAIR, SENDER, EPOCH):
                apply(root, repair)
            with patch.object(self, 'root', root):
                h = self.flight()
                with self.assertRaises(original.ProbeComplete):
                    await h.goto()
                self.assertEqual(len(h.pva_calls), 1)
                for scenario in ('state_epoch', 'sample_epoch', 'rewind_and_catch_up'):
                    with self.subTest(scenario=scenario):
                        h = self.flight(scenario)
                        with self.assertRaisesRegex(RuntimeError, 'command_.*epoch'):
                            await h.goto()
                        self.assertEqual(h.pva_calls, [])
                h = self.flight()
                h.response_hook = lambda h: setattr(h, 'cancelled', True)
                with self.assertRaises(original.CancelFlight):
                    await h.goto()
                self.assertEqual(h.pva_calls, [])
                h = self.flight()
                h.response['setpoint']['source_end_sim_s'] = 10.2
                h.response_hook = lambda h: h.advance(10.4)
                with self.assertRaisesRegex(RuntimeError, '轨迹已结束'):
                    await h.goto()
                self.assertEqual(h.pva_calls, [])

    async def test_changed_state_epoch_after_first_pva_bypasses_planning_grace(self):
        for ready, replacement in ((True, None), (True, original.command(goal_id='other-goal')), (False, None)):
            with self.subTest(sample=replacement):
                h = self.flight()
                reads = 0
                def next_response(_):
                    nonlocal reads
                    reads += 1
                    if reads == 2:
                        h.response.update(ready=ready, command_epoch='goal-epoch-B', setpoint=replacement)
                h.response_hook = next_response
                async def wait_next(_):
                    if reads >= 2:
                        raise original.ProbeComplete('stale epoch entered planning grace')
                h.owner.goto.__func__.__globals__['asyncio'].sleep = wait_next
                with self.assertRaisesRegex(RuntimeError, 'command_epoch_mismatch'):
                    await h.goto()
                self.assertEqual(reads, 2)
                self.assertEqual(len(h.pva_calls), 1)

    async def test_fresh_matching_epoch_keeps_existing_pva_dispatch(self):
        h = self.flight()
        with self.assertRaises(original.ProbeComplete):
            await h.goto()
        self.assertEqual(len(h.pva_calls), 1)
        self.assertEqual(h.owner.reference['command_epoch'], 'goal-epoch-A')
        self.assertEqual(h.owner.reference['clock_epoch'], h.owner.observer.command_epoch.token)

    async def test_mismatched_http_or_sample_epoch_never_reaches_pva(self):
        for scenario in ('state_epoch', 'sample_epoch', 'missing_goal_epoch'):
            with self.subTest(scenario=scenario):
                h = self.flight(scenario)
                with self.assertRaisesRegex(RuntimeError, 'command_epoch_'):
                    await h.goto()
                self.assertEqual(h.pva_calls, [])
                self.assertEqual([p['mode'] for p in h.calls], ['position'])

    async def test_local_clock_rewind_then_catch_up_during_http_cannot_pass_by_age(self):
        for scenario in ('rewind_and_catch_up', 'stalled_resume', 'goal_rewind'):
            with self.subTest(scenario=scenario):
                h = self.flight(scenario)
                with self.assertRaisesRegex(RuntimeError, 'command_clock_epoch_changed'):
                    await h.goto()
                self.assertEqual(h.pva_calls, [])

    async def test_disabled_flight_keeps_original_dispatch_despite_epoch_changes(self):
        h = self.flight('sample_epoch', enabled=False)
        with self.assertRaises(original.ProbeComplete):
            await h.goto()
        self.assertEqual(len(h.pva_calls), 1)


if __name__ == '__main__':
    unittest.main()
