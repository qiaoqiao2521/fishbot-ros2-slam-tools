"""Exercise frozen AST methods with fakes, without Flight/ROS imports or threads.

Tests named observed_diagnostic document current gaps. Their passing result is
evidence of that behavior, not evidence that a control fix has been applied.
"""
import ast
import asyncio
import copy
import io
import json
import math
import os
from pathlib import Path
import queue
import sys
import threading
import types
import unittest
from unittest.mock import patch


DRONE = Path('/home/muqiao/dev/ros2/projects/drone')


class CancelFlight(Exception):
    pass


class ProbeComplete(Exception):
    """Stop a fake loop after its first complete evaluation; no real wait."""


def methods(path, class_name, names, namespace):
    tree = ast.parse(path.read_text())
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == class_name)
    selected = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    if {n.name for n in selected} != set(names):
        raise RuntimeError('Requested frozen methods missing from '+str(path))
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), namespace)
    return {name: namespace[name] for name in names}


class Clock:
    def __init__(self, sim=10.15):
        self.sim, self.wall = sim, 100.

    def monotonic(self):
        return self.wall


def command(**changes):
    result = dict(position=[1., 0., 1.], velocity=[.2, .1, 0.], acceleration=[.01, 0., 0.],
        yaw_rad=.25, stamp_sim_s=10.15, trajectory_id=7, source_start_sim_s=10.,
        source_end_sim_s=11., task_id='task-A', goal_id='goal-A')
    result.update(changes)
    return result


class FlightHarness:
    def __init__(self, response=None, response_hook=None, sdk_hook=None, sdk_error=None):
        self.clock = Clock()
        self.cancelled = False
        self.calls, self.http = [], []
        self.response = response or {'ready': True, 'reason': 'ready', 'setpoint': command(), 'simulation_s': 10.15}
        self.response_hook, self.sdk_hook, self.sdk_error = response_hook, sdk_hook, sdk_error

        async def to_thread(function, *args, **kwargs):
            # Intentionally execute a fake HTTP function directly, without a thread.
            return function(*args, **kwargs)

        async def sleep(_):
            if self.cancelled:
                return
            raise ProbeComplete()

        namespace = dict(math=math, time=self.clock,
            asyncio=types.SimpleNamespace(to_thread=to_thread, sleep=sleep),
            uuid=types.SimpleNamespace(uuid4=lambda: 'goal-A'), CancelFlight=CancelFlight)
        frame_tree = ast.parse((DRONE/'frames.py').read_text())
        frame_methods = [n for n in frame_tree.body if isinstance(n, ast.FunctionDef)
                         and n.name in ('enu_to_ned', 'enu_yaw_to_ned_degrees')]
        exec(compile(ast.Module(body=frame_methods, type_ignores=[]), str(DRONE/'frames.py'), 'exec'), namespace)
        selected = ['goto', 'setpoint', 'wait_for_future_odometry']
        flight_tree = ast.parse((DRONE/'flight.py').read_text())
        if any(isinstance(n, ast.AsyncFunctionDef) and n.name == 'await_planner_state' for n in ast.walk(flight_tree)):
            selected.append('await_planner_state')
        extracted = methods(DRONE/'flight.py', 'Flight', selected, namespace)
        self.owner = types.SimpleNamespace(acceptance={'max_altitude_m': 2.2}, ground_z=0.,
            pose={'position': [0., 0., 1.]}, position_tolerance=.15,
            request={'id': 'task-A'}, phase='waypoint', scene=types.SimpleNamespace(failure=None),
            position_received=100., position_valid=True, origin=[0., 0., 0.],
            observer=types.SimpleNamespace(simulation_s=self.clock.sim, clock_received=100.,
                pose=None, pose_stamp=None, received=100.), telemetry={'speed_m_s': 1.},
            report={'visits': []}, command_position='previous', reference={'previous': True},
            cancel_file=types.SimpleNamespace(exists=lambda: self.cancelled),
            current_yaw=lambda: 0., require_recovery_inputs=lambda: None)

        def check_operator():
            if self.cancelled:
                raise CancelFlight()

        def ego_request(path, body=None):
            self.http.append((path, copy.deepcopy(body)))
            if path == '/goal':
                return {'accepted': True}
            if path != '/state':
                raise RuntimeError('Unexpected fake HTTP path '+path)
            if self.response_hook:
                self.response_hook(self)
            return copy.deepcopy(self.response)

        self.owner.check_operator = check_operator
        self.owner.ego_request = ego_request
        for name, method in extracted.items():
            setattr(self.owner, name, types.MethodType(method, self.owner))

        async def sdk(mode, *payload):
            self.calls.append({'mode': mode, 'cancelled_at_call': self.cancelled,
                'sim_at_call': self.owner.observer.simulation_s,
                'payload': [list(v.values) for v in payload]})
            if self.sdk_hook:
                self.sdk_hook(self)
            if self.sdk_error:
                raise self.sdk_error

        async def position(*payload):
            return await sdk('position', *payload)

        async def pva(*payload):
            return await sdk('pva', *payload)

        self.owner.drone = types.SimpleNamespace(offboard=types.SimpleNamespace(
            set_position_ned=position, set_position_velocity_acceleration_ned=pva))

    def advance(self, sim, wall=None):
        self.clock.sim = self.owner.observer.simulation_s = sim
        if wall is not None:
            self.clock.wall = wall
        self.owner.position_received = self.owner.observer.clock_received = self.clock.wall

    def sdk_modules(self):
        class Value:
            def __init__(self, *values):
                self.values = values
        package = types.ModuleType('mavsdk_grpc')
        offboard = types.ModuleType('mavsdk_grpc.offboard')
        offboard.PositionNedYaw = offboard.VelocityNedYaw = offboard.AccelerationNed = Value
        return patch.dict(sys.modules, {'mavsdk_grpc': package, 'mavsdk_grpc.offboard': offboard})

    async def goto(self):
        with self.sdk_modules():
            return await self.owner.goto([5., 0., 1.], use_ego=True)

    @property
    def pva_calls(self):
        return [row for row in self.calls if row['mode'] == 'pva']


def sidecar(clock, point=None):
    node = types.SimpleNamespace(lock=threading.RLock(), native_depth_lock=threading.RLock(),
        sim_now=lambda: clock.sim, args=types.SimpleNamespace(downward_depth=False,
            recovery_lidar=False, recovery_lidar_bottom=False, world='fixture', model='fixture', runtime='.'),
        odom_stamp=clock.sim, odom_wall=clock.wall, depth_stamp=clock.sim, depth_wall=clock.wall,
        planner_error=None, last_clock_wall=clock.wall, planner_started=True,
        goal_pub=types.SimpleNamespace(get_subscription_count=lambda: 1),
        setpoint=command() if point is None else point,
        active_goal=dict(x=5., y=0., z=1., task_id='task-A', goal_id='goal-A', position_tolerance_m=.15),
        owner_task_id='task-A', goal_acknowledged=True, min_trajectory_id=7,
        last_trajectory_id=7, trajectory_times={7: (10., 11.)},
        planning_since=None, planner_state='EXEC_TRAJ', goal_stamp=10., intrinsics={},
        raw_depth_stamp=clock.sim, last_depth_pose_delta=None, depth_pose_rejections=0,
        max_depth_gap=0., pose_publish_stamp=None, pose_publish_count=0,
        depth_publish_stamp=None, depth_publish_count=0, history=[],
        requests=queue.Queue(), goal_stamp_ns=123, goal_sequence=0)
    node.get_clock = lambda: types.SimpleNamespace(now=lambda: types.SimpleNamespace(nanoseconds=int(clock.sim*1e9)))
    node.stops = []
    node.stop_pub = types.SimpleNamespace(publish=lambda value: node.stops.append(value.data))
    namespace = dict(math=math, time=clock, os=os, Path=Path, start_ticks=lambda _: 0,
        seconds=lambda stamp: stamp.sec+stamp.nanosec*1e-9)
    extracted = methods(DRONE/'ego/sidecar.py', 'Sidecar', ('state', 'on_command'), namespace)
    for name, method in extracted.items():
        setattr(node, name, types.MethodType(method, node))
    return node


def post(node, path, body):
    namespace = dict(node=node, math=math, json=json, String=lambda **kw: types.SimpleNamespace(**kw))
    method = methods(DRONE/'ego/sidecar.py', 'Handler', ('do_POST',), namespace)['do_POST']
    data = json.dumps(body).encode()
    replies = []
    handler = types.SimpleNamespace(path=path, headers={'Content-Length': str(len(data))},
        rfile=io.BytesIO(data), send=lambda code, value: replies.append((code, value)))
    method(handler)
    return replies


class FlightCommandValidity(unittest.IsolatedAsyncioTestCase):
    async def test_expired_sample_is_rejected_after_state_response(self):
        h = FlightHarness(response={'ready': True, 'setpoint': command(stamp_sim_s=9.4)})
        with self.assertRaisesRegex(RuntimeError, '轨迹源时间已过期'):
            await h.goto()
        self.assertEqual(h.pva_calls, [])
        self.assertEqual([row['mode'] for row in h.calls], ['position'])

    async def test_task_and_goal_mismatches_are_rejected_after_existing_grace(self):
        for field in ('task_id', 'goal_id'):
            with self.subTest(field=field):
                h = FlightHarness(response={'ready': True, 'setpoint': command(**{field: 'another'})},
                    response_hook=lambda h: h.advance(10.15, wall=111.))
                with self.assertRaisesRegex(RuntimeError, '规划未就绪'):
                    await h.goto()
                self.assertEqual(h.pva_calls, [])

    async def test_state_response_clock_advance_inside_sample_window_is_accepted(self):
        h = FlightHarness(response_hook=lambda h: h.advance(10.4))
        with self.assertRaises(ProbeComplete):
            await h.goto()
        self.assertEqual(len(h.pva_calls), 1)
        self.assertAlmostEqual(h.owner.reference['simulation_s']-h.owner.reference['command_stamp_sim_s'], .25)
        self.assertEqual(h.owner.reference['trajectory_id'], 7)

    async def test_observed_diagnostic_source_expired_during_response_still_sends_pva(self):
        clock = Clock()
        node = sidecar(clock, command(source_end_sim_s=10.2))
        snapshot = node.state()
        self.assertTrue(snapshot['ready'])
        clock.sim = 10.4
        node.odom_stamp = node.depth_stamp = clock.sim
        current = node.state()
        self.assertEqual(current['reason'], 'trajectory_expired')
        h = FlightHarness(response=snapshot, response_hook=lambda h: h.advance(10.4))
        with self.assertRaises(ProbeComplete):
            await h.goto()
        self.assertEqual(len(h.pva_calls), 1)  # observed gap, not a fixed invariant
        self.assertGreater(h.owner.observer.simulation_s-snapshot['setpoint']['source_end_sim_s'], .15)

    async def test_observed_diagnostic_cancel_arriving_during_state_response_allows_one_pva(self):
        h = FlightHarness(response_hook=lambda h: setattr(h, 'cancelled', True))
        with self.assertRaises(CancelFlight):
            await h.goto()
        self.assertEqual(len(h.pva_calls), 1)  # cancellation is caught on the next loop
        self.assertTrue(h.pva_calls[0]['cancelled_at_call'])

    async def test_clock_rewind_beyond_future_tolerance_is_rejected(self):
        h = FlightHarness(response_hook=lambda h: h.advance(9.9))
        with self.assertRaisesRegex(RuntimeError, '轨迹源时间已过期'):
            await h.goto()
        self.assertEqual(h.pva_calls, [])

    async def test_observed_diagnostic_small_clock_rewind_inside_tolerance_is_not_an_epoch_check(self):
        h = FlightHarness(response_hook=lambda h: h.advance(10.1))
        with self.assertRaises(ProbeComplete):
            await h.goto()
        self.assertEqual(len(h.pva_calls), 1)
        self.assertLess(h.owner.observer.simulation_s, h.owner.reference['command_stamp_sim_s'])

    async def test_future_odometry_wait_already_rechecks_cancel_after_http(self):
        h = FlightHarness(response_hook=lambda h: setattr(h, 'cancelled', True))
        future = {'reason': 'odometry_unavailable', 'odom_age_s': -.2,
                  'sensor_diagnostics': {'odom_wall_age_s': 0., 'clock_wall_age_s': 0.}}
        with h.sdk_modules(), self.assertRaises(CancelFlight):
            await h.owner.wait_for_future_odometry(future, 200.)
        self.assertEqual(h.pva_calls, [])
        self.assertEqual([row['mode'] for row in h.calls], ['position'])

    async def test_setpoint_keeps_presend_stamp_and_commits_only_after_sdk_return(self):
        h = FlightHarness(sdk_hook=lambda h: h.advance(10.8))
        with h.sdk_modules():
            await h.owner.setpoint([1., 0., 1.], velocity=[.2, 0., 0.])
        self.assertEqual(h.owner.reference['simulation_s'], 10.15)
        self.assertEqual(h.owner.observer.simulation_s, 10.8)
        self.assertEqual(h.owner.command_position, [1., 0., 1.])
        failure = RuntimeError('fake SDK failure')
        h = FlightHarness(sdk_error=failure)
        with h.sdk_modules(), self.assertRaisesRegex(RuntimeError, 'fake SDK failure'):
            await h.owner.setpoint([1., 0., 1.], velocity=[.2, 0., 0.])
        self.assertEqual(h.owner.reference, {'previous': True})
        self.assertEqual(h.owner.command_position, 'previous')

    async def test_observed_diagnostic_land_clock_rewind_delays_periodic_revalidation(self):
        clock = Clock(10.)
        validations, actions = [], []
        owner = types.SimpleNamespace(telemetry={'landed': 'IN_AIR', 'armed': True},
            observer=types.SimpleNamespace(simulation_s=10., pose=None), offboard=False,
            pose={'position': [0., 0., 1.]}, home=[0., 0., 0.], report={'errors': []},
            localization_current=lambda: True, set_phase=lambda *_: None)

        async def stop_planner():
            return

        async def land_action():
            actions.append('land')

        async def validate(*_, **__):
            validations.append(owner.observer.simulation_s)
            # /validate-path returns safe, but the sim clock rewound in flight.
            owner.observer.simulation_s = clock.sim = 5.
            return {'safe': True}

        waits = 0

        async def sleep(_):
            nonlocal waits
            waits += 1
            if waits >= 3:
                raise ProbeComplete()
            owner.observer.simulation_s = clock.sim = 5.+waits*.1

        owner.stop_planner = stop_planner
        owner.validate_corridor = validate
        owner.drone = types.SimpleNamespace(action=types.SimpleNamespace(land=land_action))
        namespace = dict(asyncio=types.SimpleNamespace(sleep=sleep), time=clock, RecoveryBlocked=RuntimeError)
        method = methods(DRONE/'flight.py', 'Flight', ('land',), namespace)['land']
        with self.assertRaises(ProbeComplete):
            await method(owner, verified=True)
        self.assertEqual(actions, ['land'])  # a fake endpoint, not a vehicle API
        self.assertEqual(validations, [10.])  # no new validation at 5.1 or 5.2
        self.assertEqual(waits, 3)


class SidecarCommandValidity(unittest.TestCase):
    def test_command_requires_active_acknowledged_goal_known_curve_and_id_floor(self):
        for variant in ('inactive', 'unacknowledged', 'below_floor', 'unknown_curve', 'nonfinite'):
            with self.subTest(variant=variant):
                node = sidecar(Clock())
                node.setpoint = None
                trajectory_id = 7
                if variant == 'inactive': node.active_goal = None
                if variant == 'unacknowledged': node.goal_acknowledged = False
                if variant == 'below_floor': node.min_trajectory_id = 8
                if variant == 'unknown_curve': node.trajectory_times = {}
                vector = types.SimpleNamespace(x=float('nan') if variant == 'nonfinite' else 1., y=0., z=1.)
                msg = types.SimpleNamespace(trajectory_id=trajectory_id, position=vector, velocity=vector,
                    acceleration=vector, yaw=0., header=types.SimpleNamespace(stamp=types.SimpleNamespace(sec=10, nanosec=150000000)))
                node.on_command(msg)
                self.assertIsNone(node.setpoint)

    def test_state_sample_stale_and_source_expired_protections_exist(self):
        clock = Clock(10.4)
        node = sidecar(clock, command(source_end_sim_s=10.2))
        self.assertEqual(node.state()['reason'], 'trajectory_expired')
        node.setpoint = command(stamp_sim_s=10., source_end_sim_s=11.)
        self.assertEqual(node.state()['reason'], 'trajectory_stale')

    def test_expired_curve_allows_only_existing_zero_pva_goal_hold_exception(self):
        clock = Clock(10.4)
        node = sidecar(clock, command(position=[5., 0., 1.], velocity=[0., 0., 0.],
            acceleration=[0., 0., 0.], stamp_sim_s=10.3, source_end_sim_s=10.2))
        state = node.state()
        self.assertTrue(state['ready'])
        self.assertEqual(state['setpoint']['mode'], 'goal_hold')
        node.setpoint['velocity'][0] = .01
        self.assertEqual(node.state()['reason'], 'trajectory_expired')

    def test_paused_clock_stop_clears_command_without_waiting_for_tick(self):
        clock = Clock()
        node = sidecar(clock)
        clock.wall += 3.
        self.assertEqual(node.state()['reason'], 'simulation_clock_stopped')
        node.requests.put({'type': 'goal', 'goal_id': 'queued-old'})
        replies = post(node, '/stop', {'task_id': 'task-A'})
        self.assertEqual(replies[0][0], 202)
        self.assertIsNone(node.active_goal)
        self.assertIsNone(node.setpoint)
        self.assertFalse(node.goal_acknowledged)
        self.assertTrue(node.requests.empty())
        self.assertEqual(node.stops, ['123'])

    def test_new_goal_resets_ack_setpoint_and_floor_and_checks_paused_state(self):
        clock = Clock()
        node = sidecar(clock)
        body = dict(x=6., y=0., z=1., task_id='task-A', goal_id='goal-B')
        clock.wall += 3.
        self.assertEqual(post(node, '/goal', body)[0][0], 503)
        self.assertEqual(node.active_goal['goal_id'], 'goal-A')
        node.last_clock_wall = node.odom_wall = node.depth_wall = clock.wall
        self.assertEqual(post(node, '/goal', body)[0][0], 202)
        self.assertEqual(node.active_goal['goal_id'], 'goal-B')
        self.assertIsNone(node.setpoint)
        self.assertFalse(node.goal_acknowledged)
        self.assertEqual(node.min_trajectory_id, 8)


if __name__ == '__main__':
    unittest.main()
