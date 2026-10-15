"""Boundary tests; real ROS action/physical acceptance is a separate integration run."""
import copy
import io
import json
import math
import queue
import sys
import threading
import tempfile
import time
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import patch
from rclpy.task import Future as ROSFuture

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from map_rules import MapRulesError, MapRulesStore, build_mask, validate_zones
from mission_bridge import (APIError, GoalStatus, MissionBridge, MissionRecord,
                            Handler, require_free_point, simulation_domain, validate_mission,
                            validate_backup, validate_cancel)


def fixture_grid():
    return {'width': 40, 'height': 40, 'resolution': 0.1,
            'origin': [-2.0, -2.0, 0.0], 'data': [0]*1600}


class IsolationTests(unittest.TestCase):
    def test_default_domain_preserves_baseline(self):
        self.assertEqual(simulation_domain({'ROS_DOMAIN_ID': '93',
            'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST'}), 93)

    def test_isolated_domain_requires_explicit_matching_selection(self):
        env = {'FISHBOT_MUJOCO_DOMAIN_ID': '100', 'ROS_DOMAIN_ID': '100',
               'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST'}
        self.assertEqual(simulation_domain(env), 100)
        for changes in ({'ROS_DOMAIN_ID': '0'}, {'FISHBOT_MUJOCO_DOMAIN_ID': '0', 'ROS_DOMAIN_ID': '0'},
                        {'FISHBOT_MUJOCO_DOMAIN_ID': '233', 'ROS_DOMAIN_ID': '233'},
                        {'FISHBOT_MUJOCO_DOMAIN_ID': '١', 'ROS_DOMAIN_ID': '١'},
                        {'ROS_AUTOMATIC_DISCOVERY_RANGE': 'SUBNET'}, {'ROS_STATIC_PEERS': '192.168.0.1'}):
            with self.subTest(changes=changes), self.assertRaises(SystemExit):
                simulation_domain({**env, **changes})
        with self.assertRaises(SystemExit):
            simulation_domain({'ROS_DOMAIN_ID': '100', 'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST'})

    def test_configured_loopback_origin_retains_host_and_origin_restrictions(self):
        server = SimpleNamespace(port=9076, ui_ports={5173, 5180})
        handler = SimpleNamespace(server=server, headers={'Host': '127.0.0.1:9076',
                                                         'Origin': 'http://127.0.0.1:5180'})
        self.assertTrue(Handler.allowed(handler))
        for origin in ('http://192.168.0.1:5180', 'http://127.0.0.1:5181',
                       'http://127.0.0.1:5180/path', 'http://user@127.0.0.1:5180'):
            handler.headers['Origin'] = origin
            self.assertFalse(Handler.allowed(handler))
        handler.headers = {'Host': '192.168.0.1:9076'}
        self.assertFalse(Handler.allowed(handler))


class IdentifiedVoiceTaskTests(unittest.TestCase):
    def test_optional_id_reaches_original_record_and_cannot_be_reused(self):
        record = MissionRecord()
        original = 'd44b9ba6-ac8e-49dc-83c4-86caf4a14390'
        self.assertEqual(record.begin([], False, mission_id=original), original)
        record.finish(GoalStatus.STATUS_SUCCEEDED, 0, [])
        with self.assertRaises(APIError):
            record.begin([], False, mission_id=original)

    def test_cancel_requires_matching_fresh_original_id(self):
        original = 'd44b9ba6-ac8e-49dc-83c4-86caf4a14390'
        validate_cancel({}, original, now=100.)
        validate_cancel({'mission_id': original, 'issued_at': 100.}, original, now=100.)
        for body, status in [({'mission_id': original, 'issued_at': 96.9}, 408),
                ({'mission_id': original, 'issued_at': 101.1}, 408),
                ({'mission_id': 'db7de024-1f05-4b78-8d6f-088e94f4eae9', 'issued_at': 100.}, 409),
                ({'mission_id': original}, 400), ({'issued_at': 100.}, 400)]:
            with self.subTest(body=body), self.assertRaises(APIError) as caught:
                validate_cancel(body, original, now=100.)
            self.assertEqual(caught.exception.status, status)


class GoalBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.grid = fixture_grid()
        self.body = {'waypoints': [{'x': 1.0, 'y': 1.0, 'yaw': 0.0}],
                     'return_home': True, 'issued_at': 100.0}
        self.return_point = {'x': 0., 'y': 0., 'yaw': 0.}

    def test_home_is_an_actual_last_waypoint(self):
        points, returning = validate_mission(self.body, self.grid, now=100, return_point=self.return_point)
        self.assertTrue(returning)
        self.assertEqual(points[-1], {'x': 0.0, 'y': 0.0, 'yaw': 0.0})
        self.assertEqual(len(points), 2)

    def test_return_requires_explicit_mission_start_not_map_origin(self):
        with self.assertRaises(APIError) as caught:
            validate_mission(self.body, self.grid, now=100.)
        self.assertEqual(caught.exception.status, 503)
        start = {'x': -.8, 'y': .6, 'yaw': .7}
        points, returning = validate_mission(self.body, self.grid, now=100., return_point=start)
        self.assertTrue(returning)
        self.assertEqual(points[-1], start)
        self.assertNotEqual(points[-1], self.return_point)

    def test_selected_start_is_not_appended_or_reclassified_as_automatic_return(self):
        start = {'x': -.8, 'y': .6, 'yaw': .7}
        self.body['waypoints'].append(dict(start))
        points, _returning = validate_mission(self.body, self.grid, now=100., return_point=start)
        self.assertEqual(len(points), 2)
        wall = {'id': 'start_wall', 'kind': 'wall', 'width': .02,
                'points': [{'x': -.7, 'y': .2}, {'x': -.7, 'y': 1.}]}
        with self.assertRaises(MapRulesError) as explicit:
            validate_mission(self.body, self.grid, now=100., zones=[wall], return_point=start)
        self.assertEqual((explicit.exception.issue['target'], explicit.exception.issue['waypoint_index']),
                         ('waypoint', 2))
        self.body['waypoints'].pop()
        with self.assertRaises(MapRulesError) as automatic:
            validate_mission(self.body, self.grid, now=100., zones=[wall], return_point=start)
        self.assertEqual((automatic.exception.issue['target'], automatic.exception.issue['waypoint_index']),
                         ('return_home', None))
        self.assertEqual(automatic.exception.issue['point'], start)

    def test_sender_timestamp_rejects_delayed_and_future_goals(self):
        for timestamp in (96.9, 101.1):
            with self.subTest(timestamp=timestamp):
                body = copy.deepcopy(self.body)
                body['issued_at'] = timestamp
                with self.assertRaises(APIError) as caught:
                    validate_mission(body, self.grid, now=100, return_point=self.return_point)
                self.assertEqual(caught.exception.status, 408)

    def test_nonfinite_and_boolean_coordinates_are_not_goals(self):
        for value in (math.nan, math.inf, -math.inf, True, '1'):
            with self.subTest(value=value):
                body = copy.deepcopy(self.body)
                body['waypoints'][0]['x'] = value
                with self.assertRaises(APIError):
                    validate_mission(body, self.grid, now=100, return_point=self.return_point)

    def test_missing_timestamp_or_coordinates_rejected(self):
        for field in ('issued_at', 'x', 'y'):
            with self.subTest(field=field):
                body = copy.deepcopy(self.body)
                if field == 'issued_at':
                    del body[field]
                else:
                    del body['waypoints'][0][field]
                with self.assertRaises(APIError):
                    validate_mission(body, self.grid, now=100, return_point=self.return_point)

    def test_free_center_does_not_allow_footprint_through_obstacle(self):
        # Center (0.05,0.05) is free, adjacent cell [0.1,0.2] intersects radius .13.
        self.grid['data'][20*40+21] = 100
        with self.assertRaises(APIError):
            require_free_point({'x': 0.05, 'y': 0.05}, self.grid)

    def test_unknown_cell_is_not_traversable(self):
        self.grid['data'][20*40+20] = -1
        with self.assertRaises(APIError):
            require_free_point({'x': 0.05, 'y': 0.05}, self.grid)

    def test_footprint_map_boundary_is_checked(self):
        with self.assertRaises(APIError):
            require_free_point({'x': 1.95, 'y': 0.0}, self.grid)

    def test_rotated_map_uses_map_coordinates(self):
        self.grid['origin'] = [2.0, -2.0, math.pi/2]
        self.grid['data'][20*40+20] = 100
        # Local cell (20,20) maps to approximately (-.05,.05).
        with self.assertRaises(APIError):
            require_free_point({'x': -0.05, 'y': 0.05}, self.grid)
        require_free_point({'x': 1.0, 'y': -1.0}, self.grid)

    def test_rotated_cell_diagnostic_marks_nearest_world_point_and_cell_kind(self):
        self.grid['origin'] = [2., -2., math.pi/2]
        for occupancy, kind in ((100, 'occupied_cell'), (-1, 'unknown_cell')):
            self.grid['data'][20*40+21] = occupancy
            with self.subTest(occupancy=occupancy), self.assertRaises(APIError) as caught:
                require_free_point({'x': -.05, 'y': .05, 'yaw': 0.}, self.grid)
            issue = caught.exception.issue
            self.assertEqual(issue['kind'], kind)
            self.assertEqual(str(caught.exception), 'Waypoint footprint intersects an occupied or unknown cell')
            self.assertAlmostEqual(issue['blocking_point']['x'], -.05)
            self.assertAlmostEqual(issue['blocking_point']['y'], .1)
            self.assertAlmostEqual(issue['clearance_m'], .05)
            self.assertAlmostEqual(issue['shortfall_m'], .08)

    def test_rotated_boundary_diagnostic_marks_actual_limiting_map_edge(self):
        self.grid['origin'] = [2., -2., math.pi/2]
        with self.assertRaises(APIError) as caught:
            require_free_point({'x': 0., 'y': -1.95, 'yaw': 0.}, self.grid)
        issue = caught.exception.issue
        self.assertEqual(issue['kind'], 'map_boundary')
        self.assertAlmostEqual(issue['blocking_point']['x'], 0.)
        self.assertAlmostEqual(issue['blocking_point']['y'], -2.)
        self.assertAlmostEqual(issue['clearance_m'], .05)
        self.assertAlmostEqual(issue['shortfall_m'], .08)

    def test_center_already_outside_map_omits_misleading_distance_to_move(self):
        with self.assertRaises(APIError) as caught:
            require_free_point({'x': 2.1, 'y': 0., 'yaw': 0.}, self.grid)
        self.assertEqual(caught.exception.issue['blocking_point'], {'x': 2., 'y': 0.})
        self.assertNotIn('clearance_m', caught.exception.issue)
        self.assertNotIn('shortfall_m', caught.exception.issue)

    def test_second_user_waypoint_rejection_names_point_and_one_based_index(self):
        self.body['waypoints'].append({'x': .05, 'y': .05, 'yaw': 2*math.pi})
        self.grid['data'][20*40+20] = -1
        with self.assertRaises(APIError) as caught:
            validate_mission(self.body, self.grid, now=100., return_point=self.return_point)
        issue = caught.exception.issue
        self.assertEqual((issue['target'], issue['waypoint_index']), ('waypoint', 2))
        self.assertEqual(issue['kind'], 'unknown_cell')
        self.assertAlmostEqual(issue['point']['yaw'], 0.)
        self.assertEqual((issue['point']['x'], issue['point']['y']), (.05, .05))

    def test_automatic_home_and_explicit_home_are_distinct_rejections(self):
        wall = {'id': 'near_home', 'kind': 'wall', 'width': .02,
                'points': [{'x': .1, 'y': -.4}, {'x': .1, 'y': .4}]}
        with self.assertRaises(MapRulesError) as automatic:
            validate_mission(self.body, self.grid, now=100., zones=[wall], return_point=self.return_point)
        issue = automatic.exception.issue
        self.assertEqual((issue['target'], issue['waypoint_index']), ('return_home', None))
        self.assertEqual(issue['point'], {'x': 0., 'y': 0., 'yaw': 0.})
        self.body['waypoints'].append({'x': 0., 'y': 0.})
        with self.assertRaises(MapRulesError) as explicit:
            validate_mission(self.body, self.grid, now=100., zones=[wall], return_point=self.return_point)
        self.assertEqual((explicit.exception.issue['target'], explicit.exception.issue['waypoint_index']),
                         ('waypoint', 2))

    def test_automatic_home_map_rejection_has_no_user_waypoint_index(self):
        self.grid['data'][20*40+20] = 100
        with self.assertRaises(APIError) as caught:
            validate_mission(self.body, self.grid, now=100., return_point=self.return_point)
        self.assertEqual(caught.exception.issue['kind'], 'occupied_cell')
        self.assertEqual((caught.exception.issue['target'], caught.exception.issue['waypoint_index']),
                         ('return_home', None))

    def test_twelve_user_points_can_append_home_as_thirteenth(self):
        self.body['waypoints'] *= 12
        points, returning = validate_mission(self.body, self.grid, now=100, return_point=self.return_point)
        self.assertTrue(returning)
        self.assertEqual(len(points), 13)
        self.assertEqual(points[-1], {'x': 0.0, 'y': 0.0, 'yaw': 0.0})

    def test_thirteen_user_points_are_rejected(self):
        self.body['waypoints'] *= 13
        with self.assertRaises(APIError):
            validate_mission(self.body, self.grid, now=100, return_point=self.return_point)


class MissionSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.record = MissionRecord()
        self.points = [{'x': 1.0, 'y': 1.0, 'yaw': 0.0}, {'x': 0.0, 'y': 0.0, 'yaw': 0.0}]
        self.record.begin(self.points, True)

    def test_overlap_blocked_while_running_and_canceling(self):
        for cancel in (False, True):
            if cancel:
                self.record.request_cancel()
            with self.assertRaises(APIError) as caught:
                self.record.begin(self.points, True)
            self.assertEqual(caught.exception.status, 409)

    def test_cancel_request_is_not_canceled_result(self):
        self.record.request_cancel()
        self.assertEqual(self.record.value['status'], 'canceling')
        self.record.finish(GoalStatus.STATUS_CANCELED, 0, [])
        self.assertEqual(self.record.value['status'], 'canceled')

    def test_pending_dispatch_does_not_claim_nav2_acceptance(self):
        self.assertEqual(self.record.value['dispatch_state'], 'pending')
        self.assertIsNone(self.record.value['stop_reason'])

    def test_first_cancel_reason_survives_acknowledgement_and_final_result(self):
        self.record.request_cancel('仿真未就绪：仿真时钟未就绪或已暂停')
        self.record.request_cancel('用户请求取消')
        self.record.value['message'] = 'Nav2 已接收取消请求，等待终止结果'
        self.record.finish(GoalStatus.STATUS_CANCELED, 0, [])
        self.assertEqual(self.record.value['status'], 'canceled')
        self.assertEqual(self.record.value['stop_reason'], '仿真未就绪：仿真时钟未就绪或已暂停')
        self.record.begin(self.points, False)
        self.assertIsNone(self.record.value['stop_reason'])

    def test_success_requires_no_error_and_no_missed_waypoints(self):
        self.record.finish(GoalStatus.STATUS_SUCCEEDED, 0, [{'index': 0, 'error_code': 600}])
        self.assertEqual(self.record.value['status'], 'failed')
        self.record.begin(self.points, True)
        self.record.finish(GoalStatus.STATUS_SUCCEEDED, 601, [])
        self.assertEqual(self.record.value['status'], 'failed')

    def test_actual_success_wins_a_cancel_result_race(self):
        self.record.request_cancel()
        self.record.finish(GoalStatus.STATUS_SUCCEEDED, 0, [])
        self.assertEqual(self.record.value['status'], 'succeeded')
        self.assertEqual(self.record.value['current_index'], 1)

    def test_terminal_mission_can_be_replaced_but_not_canceled(self):
        previous_id = self.record.value['id']
        self.record.finish(GoalStatus.STATUS_SUCCEEDED, 0, [])
        with self.assertRaises(APIError):
            self.record.request_cancel()
        next_id = self.record.begin(self.points, False)
        self.assertNotEqual(next_id, previous_id)


class DispatchFeedbackTests(unittest.TestCase):
    def harness(self):
        record = MissionRecord()
        record.begin([{'x': 1.0, 'y': 1.0, 'yaw': 0.0}], False)
        sent_cancels = []
        bridge = SimpleNamespace(lock=threading.RLock(), mission=record,
                                 goal_handle=None, cancel_requested=False, cancel_sent=False,
                                 send_cancel=lambda: sent_cancels.append(True))
        for name in ('reset_cleanup', 'subscribe_result', 'result', 'request_cancel', 'retry_cleanup'):
            setattr(bridge, name, MethodType(getattr(MissionBridge, name), bridge))
        bridge.reset_cleanup()
        return bridge, sent_cancels

    def test_running_receipt_changes_only_after_nav2_accepts(self):
        bridge, _sent = self.harness()
        result = Future()
        response = Future()
        response.set_result(SimpleNamespace(accepted=True, get_result_async=lambda: result))
        MissionBridge.goal_response(bridge, bridge.mission.value['id'], response)
        self.assertEqual(bridge.mission.value['dispatch_state'], 'accepted')
        self.assertEqual(bridge.mission.value['status'], 'running')
        self.assertFalse(result.done())

    def test_nav2_rejection_does_not_become_execution(self):
        bridge, _sent = self.harness()
        response = Future()
        response.set_result(SimpleNamespace(accepted=False))
        MissionBridge.goal_response(bridge, bridge.mission.value['id'], response)
        self.assertEqual(bridge.mission.value['dispatch_state'], 'rejected')
        self.assertEqual(bridge.mission.value['status'], 'failed')
        self.assertIsNone(bridge.goal_handle)

    def test_missing_receipt_retains_unknown_ownership_and_forbids_new_goal(self):
        bridge, _sent = self.harness()
        mission_id = bridge.mission.value['id']
        response = Future()
        response.set_exception(RuntimeError('response lost'))
        MissionBridge.goal_response(bridge, bridge.mission.value['id'], response)
        self.assertEqual(bridge.mission.value['dispatch_state'], 'unavailable')
        self.assertEqual(bridge.mission.value['status'], 'canceling')
        self.assertEqual(bridge.mission.value['cleanup_state'], 'unresolved')
        self.assertEqual(bridge.mission.value['id'], mission_id)
        self.assertIsNone(bridge.goal_handle)
        with self.assertRaises(APIError) as caught:
            bridge.mission.begin(bridge.mission.value['waypoints'], False)
        self.assertEqual(caught.exception.status, 409)

    def test_synchronous_send_error_is_unknown_and_never_retried(self):
        from builtin_interfaces.msg import Time
        bridge, sent_cancels = self.harness()
        bridge.mission = MissionRecord()
        bridge.ready, bridge.grid, bridge.truth = True, fixture_grid(), None
        bridge.get_clock = lambda: SimpleNamespace(now=lambda: SimpleNamespace(to_msg=Time,
                                                                              nanoseconds=100_000_000_000))
        bridge.clock_fresh = lambda *_args: True
        bridge.buffer = SimpleNamespace(lookup_transform=lambda *_args: SimpleNamespace(
            header=SimpleNamespace(stamp=Time(sec=100)), transform=SimpleNamespace(
                translation=SimpleNamespace(x=0., y=0.), rotation=SimpleNamespace(x=0., y=0., z=0., w=1.))))
        sent = []
        def send(*_args, **_kwargs):
            sent.append(True)
            raise RuntimeError('transport send error')
        bridge.client = SimpleNamespace(send_goal_async=send)
        body = {'waypoints': [{'x': 1., 'y': 1.}], 'issued_at': time.time()}
        with self.assertRaisesRegex(RuntimeError, 'transport send error'):
            MissionBridge.start_mission(bridge, body)
        mission_id = bridge.mission.value['id']
        self.assertEqual(bridge.mission.value['status'], 'canceling')
        self.assertEqual(bridge.mission.value['cleanup_state'], 'unresolved')
        self.assertEqual(bridge.mission.value['dispatch_state'], 'unavailable')
        with self.assertRaises(APIError) as caught:
            MissionBridge.start_mission(bridge, body)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(bridge.mission.value['id'], mission_id)
        self.assertEqual(sent, [True])
        self.assertEqual(sent_cancels, [])

    def test_cancel_endpoint_without_ack_handle_stays_unknown(self):
        bridge, sent_cancels = self.harness()
        response = Future()
        response.set_exception(RuntimeError('acceptance response lost'))
        MissionBridge.goal_response(bridge, bridge.mission.value['id'], response)
        mission_id, reason = bridge.mission.value['id'], bridge.mission.value['stop_reason']
        bridge.poll_lifecycle = bridge.poll_collision_monitor = lambda _wall: None
        bridge.evaluate_ready = lambda _wall: (True, 'ready')
        bridge.goal_send_future, bridge.goal_sent_wall = response, 0.
        bridge.pending_services, bridge.operations = [], queue.Queue()
        bridge.state = lambda: copy.deepcopy(bridge.mission.value)
        op = SimpleNamespace(kind='cancel', body={}, deadline=time.monotonic()+2., future=Future())
        bridge.operations.put(op)
        MissionBridge.tick(bridge)
        status, value = op.future.result()
        self.assertEqual(status, 202)
        self.assertEqual(value['status'], 'canceling')
        self.assertEqual(value['cleanup_state'], 'unresolved')
        self.assertEqual(value['id'], mission_id)
        self.assertEqual(value['stop_reason'], reason)
        self.assertEqual(sent_cancels, [])
        self.assertIsNone(bridge.result_future)

    def test_result_subscription_error_does_not_erase_the_actual_acceptance(self):
        bridge, _sent = self.harness()
        response = Future()

        def unavailable_result():
            raise RuntimeError('result subscription failed')

        response.set_result(SimpleNamespace(accepted=True, get_result_async=unavailable_result))
        MissionBridge.goal_response(bridge, bridge.mission.value['id'], response)
        self.assertEqual(bridge.mission.value['dispatch_state'], 'accepted')
        self.assertEqual(bridge.mission.value['status'], 'canceling')
        self.assertIsNotNone(bridge.goal_handle)
        with self.assertRaises(APIError):
            bridge.mission.begin(bridge.mission.value['waypoints'], False)

    def test_late_acceptance_keeps_pending_cancel_and_its_reason(self):
        bridge, sent = self.harness()
        MissionBridge.request_cancel(bridge, '任务接收超时，等待响应后取消')
        response = Future()
        response.set_result(SimpleNamespace(accepted=True, get_result_async=Future))
        MissionBridge.goal_response(bridge, bridge.mission.value['id'], response)
        self.assertEqual(bridge.mission.value['dispatch_state'], 'accepted')
        self.assertEqual(bridge.mission.value['status'], 'canceling')
        self.assertEqual(bridge.mission.value['stop_reason'], '任务接收超时，等待响应后取消')
        self.assertEqual(sent, [True])

    def test_readiness_cancel_captures_the_specific_source_reason(self):
        bridge, _sent = self.harness()
        bridge.poll_lifecycle = lambda _wall: None
        bridge.poll_collision_monitor = lambda _wall: None
        bridge.evaluate_ready = lambda _wall: (False, '仿真时钟未就绪或已暂停')
        bridge.goal_sent_wall = 0.0
        bridge.goal_send_future = None
        bridge.pending_services = []
        bridge.operations = queue.Queue()
        bridge.request_cancel = lambda message: MissionBridge.request_cancel(bridge, message)
        MissionBridge.tick(bridge)
        bridge.mission.finish(GoalStatus.STATUS_CANCELED, 0, [])
        self.assertEqual(bridge.mission.value['stop_reason'], '仿真未就绪：仿真时钟未就绪或已暂停')


class AcceptedCleanupTests(unittest.TestCase):
    def harness(self, result_method, cancel_method):
        bridge, _sent = DispatchFeedbackTests().harness()
        bridge.send_cancel = MethodType(MissionBridge.send_cancel, bridge)
        bridge.cancel_response = MethodType(MissionBridge.cancel_response, bridge)
        handle = SimpleNamespace(accepted=True, get_result_async=result_method,
                                 cancel_goal_async=cancel_method)
        response = Future()
        response.set_result(handle)
        with patch('mission_bridge.time.monotonic', return_value=10.0):
            MissionBridge.goal_response(bridge, bridge.mission.value['id'], response)
        return bridge, handle

    def terminal(self, status=GoalStatus.STATUS_CANCELED):
        return SimpleNamespace(status=status, result=SimpleNamespace(
            missed_waypoints=[], error_code=0, error_msg=''))

    def test_subscription_and_cancel_send_errors_retry_without_releasing_goal(self):
        result, cancel = Future(), Future()
        result_calls, cancel_calls = [], []
        def subscribe():
            result_calls.append(True)
            if len(result_calls) == 1:
                raise RuntimeError('result unavailable')
            return result
        def request_cancel():
            cancel_calls.append(True)
            if len(cancel_calls) == 1:
                raise RuntimeError('cancel unavailable')
            return cancel
        bridge, handle = self.harness(subscribe, request_cancel)
        self.assertEqual(bridge.mission.value['status'], 'canceling')
        self.assertIs(bridge.goal_handle, handle)
        with patch('mission_bridge.time.monotonic', return_value=11.1):
            bridge.retry_cleanup(11.1)
            cancel.set_result(SimpleNamespace(goals_canceling=[object()]))
            self.assertEqual(bridge.mission.value['status'], 'canceling')
            result.set_result(self.terminal())
        self.assertEqual((len(result_calls), len(cancel_calls)), (2, 2))
        self.assertEqual(bridge.mission.value['status'], 'canceled')
        self.assertIsNone(bridge.goal_handle)
        self.assertIn('result unavailable', bridge.mission.value['stop_reason'])

    def test_result_read_exception_retains_handle_and_accepts_later_terminal(self):
        first, second, cancel = Future(), Future(), Future()
        requests = iter([first, second])
        bridge, handle = self.harness(lambda: next(requests), lambda: cancel)
        with patch('mission_bridge.time.monotonic', return_value=10.0):
            first.set_exception(RuntimeError('response lost'))
        self.assertEqual(bridge.mission.value['status'], 'canceling')
        self.assertIs(bridge.goal_handle, handle)
        with patch('mission_bridge.time.monotonic', return_value=11.1):
            bridge.retry_cleanup(11.1)
            second.set_result(self.terminal(GoalStatus.STATUS_SUCCEEDED))
        self.assertEqual(bridge.mission.value['status'], 'succeeded')
        self.assertIsNone(bridge.goal_handle)

    def test_immediate_terminal_callback_does_not_cancel_a_cleared_handle(self):
        result = Future()
        result.set_result(self.terminal(GoalStatus.STATUS_SUCCEEDED))
        canceled = []
        bridge, _handle = self.harness(lambda: result, lambda: canceled.append(True))
        self.assertEqual(bridge.mission.value['status'], 'succeeded')
        self.assertIsNone(bridge.goal_handle)
        self.assertEqual(canceled, [])

    def test_failed_attempts_are_bounded_and_user_can_retry_the_same_goal(self):
        calls = []
        def unavailable():
            calls.append(True)
            raise RuntimeError('offline')
        bridge, handle = self.harness(unavailable, unavailable)
        for wall in (11.1, 12.2, 13.3, 14.4):
            with patch('mission_bridge.time.monotonic', return_value=wall):
                bridge.retry_cleanup(wall)
        self.assertEqual(len(calls), 6)
        self.assertEqual(bridge.mission.value['cleanup_state'], 'unresolved')
        self.assertEqual(bridge.mission.value['status'], 'canceling')
        self.assertIs(bridge.goal_handle, handle)
        with self.assertRaises(APIError):
            bridge.mission.begin(bridge.mission.value['waypoints'], False)
        with patch('mission_bridge.time.monotonic', return_value=15.0):
            bridge.request_cancel('用户请求取消', retry=True)
            bridge.retry_cleanup(15.0)
        self.assertEqual(len(calls), 8)
        self.assertEqual(bridge.mission.value['cleanup_state'], 'retrying')

    def test_late_old_result_and_cancel_callbacks_do_not_override_new_requests(self):
        first, second, first_cancel, second_cancel = [Future() for _ in range(4)]
        first.set_running_or_notify_cancel()
        first_cancel.set_running_or_notify_cancel()
        results, cancels = iter([first, second]), iter([first_cancel, second_cancel])
        bridge, _handle = self.harness(lambda: next(results), lambda: next(cancels))
        with patch('mission_bridge.time.monotonic', return_value=10.0):
            bridge.request_cancel('test cleanup')
        for wall in (13.1, 14.2):
            with patch('mission_bridge.time.monotonic', return_value=wall):
                bridge.retry_cleanup(wall)
        first.set_result(self.terminal(GoalStatus.STATUS_SUCCEEDED))
        first_cancel.set_result(SimpleNamespace(goals_canceling=[object()]))
        self.assertEqual(bridge.mission.value['status'], 'canceling')
        self.assertIs(bridge.result_future, second)
        self.assertIs(bridge.cancel_future, second_cancel)
        second.set_result(self.terminal())
        self.assertEqual(bridge.mission.value['status'], 'canceled')

    def test_cancel_response_exception_does_not_disable_followup_cancel(self):
        result, first, second = Future(), Future(), Future()
        cancels = iter([first, second])
        bridge, _handle = self.harness(lambda: result, lambda: next(cancels))
        with patch('mission_bridge.time.monotonic', return_value=10.0):
            bridge.request_cancel('test cancel')
            first.set_exception(RuntimeError('reply lost'))
        with patch('mission_bridge.time.monotonic', return_value=11.1):
            bridge.retry_cleanup(11.1)
        self.assertIs(bridge.cancel_future, second)
        self.assertEqual(bridge.mission.value['status'], 'canceling')

    def test_unknown_action_result_cannot_release_the_accepted_goal(self):
        result, cancel = Future(), Future()
        bridge, handle = self.harness(lambda: result, lambda: cancel)
        result.set_result(self.terminal(GoalStatus.STATUS_UNKNOWN))
        self.assertEqual(bridge.mission.value['status'], 'canceling')
        self.assertIs(bridge.goal_handle, handle)
        self.assertIn('未返回终态', bridge.mission.value['stop_reason'])

    def test_unanswered_cleanup_requests_exhaust_without_fake_terminal(self):
        for future_type in (Future, ROSFuture):
            with self.subTest(future_type=future_type):
                results = [future_type() for _ in range(3)]
                cancels = [future_type() for _ in range(3)]
                result_requests, cancel_requests = iter(results), iter(cancels)
                bridge, handle = self.harness(lambda: next(result_requests), lambda: next(cancel_requests))
                with patch('mission_bridge.time.monotonic', return_value=10.0):
                    bridge.request_cancel('test timeout')
                for wall in (13.1, 14.2, 17.3, 18.4, 21.5, 30.0):
                    with patch('mission_bridge.time.monotonic', return_value=wall):
                        bridge.retry_cleanup(wall)
                self.assertTrue(all(future.cancelled() for future in results+cancels))
                self.assertEqual((bridge.result_attempts, bridge.cancel_attempts), (3, 3))
                self.assertEqual(bridge.mission.value['cleanup_state'], 'unresolved')
                self.assertEqual(bridge.mission.value['status'], 'canceling')
                self.assertIs(bridge.goal_handle, handle)


class CollisionMonitorReportTests(unittest.TestCase):
    def harness(self):
        bridge = SimpleNamespace(lock=threading.RLock(), cm_report=None,
            cm_publishers=(b'publisher',), cm_check_wall=0.0,
            lifecycle={'collision_monitor': {'active': True, 'wall': 100.0}})
        return bridge

    def test_continuing_stop_is_not_expired_by_event_age(self):
        bridge = self.harness()
        with patch('mission_bridge.time.monotonic', return_value=1.0):
            MissionBridge.on_collision_monitor(bridge, SimpleNamespace(action_type=1, polygon_name='VelocityStop'))
        state = MissionBridge.collision_monitor_state(bridge, 100.0)
        self.assertEqual(state['action'], 'stop')
        self.assertEqual(state['polygon_name'], 'VelocityStop')
        self.assertEqual(state['observation_age_s'], 99.0)
        with patch('mission_bridge.time.monotonic', return_value=100.0):
            MissionBridge.on_collision_monitor(bridge, SimpleNamespace(action_type=0, polygon_name=''))
        self.assertEqual(MissionBridge.collision_monitor_state(bridge, 100.0)['action'], 'do_nothing')

    def test_missing_source_or_inactive_monitor_is_unknown(self):
        for publishers, active in (((), True), ((b'publisher',), False)):
            bridge = self.harness()
            bridge.cm_publishers = publishers
            bridge.lifecycle['collision_monitor']['active'] = active
            bridge.cm_report = {'action': 'stop', 'action_type': 1, 'polygon_name': 'old', 'wall': 1.0}
            report = MissionBridge.collision_monitor_state(bridge, 100.0)
            self.assertEqual(report['action'], 'unknown')
            self.assertIsNone(report['polygon_name'])

    def test_publisher_replacement_discards_previous_epoch(self):
        bridge = self.harness()
        bridge.cm_report = {'action': 'stop', 'action_type': 1, 'polygon_name': 'old', 'wall': 1.0}
        bridge.get_publishers_info_by_topic = lambda _topic: [SimpleNamespace(endpoint_gid=b'new')]
        MissionBridge.poll_collision_monitor(bridge, 100.0)
        self.assertIsNone(bridge.cm_report)
        self.assertEqual(bridge.cm_publishers, (b'new',))

    def test_first_graph_poll_keeps_an_event_received_before_discovery(self):
        bridge = self.harness()
        bridge.cm_publishers = ()
        bridge.cm_report = {'action': 'stop', 'action_type': 1, 'polygon_name': 'VelocityStop', 'wall': 99.0}
        bridge.get_publishers_info_by_topic = lambda _topic: [SimpleNamespace(endpoint_gid=b'new')]
        MissionBridge.poll_collision_monitor(bridge, 100.0)
        self.assertEqual(MissionBridge.collision_monitor_state(bridge, 100.0)['action'], 'stop')

    def test_clock_rollback_discards_previous_report(self):
        bridge = self.harness()
        bridge.cm_report = {'action': 'stop'}
        bridge.clock_last = 5.0
        bridge.clock_advance_wall = 1.0
        bridge.sample = lambda _name, _stamp: None
        MissionBridge.on_clock(bridge, SimpleNamespace(clock=SimpleNamespace(sec=1, nanosec=0)))
        self.assertIsNone(bridge.cm_report)


class LifecycleRetryTests(unittest.TestCase):
    def harness(self, pending):
        new_request = Future()
        removed = []
        client = SimpleNamespace(service_is_ready=lambda: True,
                                 remove_pending_request=removed.append,
                                 call_async=lambda _request: new_request)
        bridge = SimpleNamespace(lock=threading.RLock(), last_lifecycle_poll=0.0,
            lifecycle={'collision_monitor': {'active': True, 'wall': 1.0,
                                             'future': pending, 'sent': 0.0}},
            lifecycle_clients={'collision_monitor': client})
        bridge.lifecycle_result = lambda name, future: MissionBridge.lifecycle_result(bridge, name, future)
        pending.add_done_callback(lambda future: bridge.lifecycle_result('collision_monitor', future))
        return bridge, new_request, removed

    def test_lost_response_is_removed_and_retried_without_assuming_active(self):
        old = Future()
        bridge, new, removed = self.harness(old)
        MissionBridge.poll_lifecycle(bridge, wall=4.0)
        state = bridge.lifecycle['collision_monitor']
        self.assertEqual(removed, [old])
        self.assertTrue(old.cancelled())
        self.assertFalse(state['active'])
        self.assertIs(state['future'], new)
        new.set_result(SimpleNamespace(current_state=SimpleNamespace(id=3)))
        self.assertTrue(state['active'])
        self.assertIsNone(state['future'])

    def test_late_old_response_cannot_override_new_inactive_result(self):
        old = Future()
        old.set_running_or_notify_cancel()  # Models an uncancelable response already in flight.
        bridge, new, _removed = self.harness(old)
        MissionBridge.poll_lifecycle(bridge, wall=4.0)
        new.set_result(SimpleNamespace(current_state=SimpleNamespace(id=2)))
        self.assertFalse(bridge.lifecycle['collision_monitor']['active'])
        old.set_result(SimpleNamespace(current_state=SimpleNamespace(id=3)))
        self.assertFalse(bridge.lifecycle['collision_monitor']['active'])

    def test_pending_query_within_deadline_is_not_duplicated(self):
        old = Future()
        bridge, _new, removed = self.harness(old)
        MissionBridge.poll_lifecycle(bridge, wall=2.0)
        self.assertIs(bridge.lifecycle['collision_monitor']['future'], old)
        self.assertEqual(removed, [])


class MapRulesIntegrationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = MapRulesStore(self.directory.name)
        self.store.bind(fixture_grid())
        self.rectangle = {'id': 'home_forbidden', 'kind': 'no_go', 'points': [
            {'x': -.2, 'y': -.2}, {'x': .2, 'y': -.2}, {'x': .2, 'y': .2}, {'x': -.2, 'y': .2}]}

    def test_explicit_goal_and_automatic_home_check_the_same_footprint_rules(self):
        zones = validate_zones([self.rectangle], fixture_grid())
        body = {'waypoints': [{'x': 1., 'y': 1., 'yaw': 0.}], 'return_home': False, 'issued_at': 100.}
        points, _returning = validate_mission(body, fixture_grid(), now=100., zones=zones)
        self.assertEqual(len(points), 1)
        for altered in ({**body, 'return_home': True},
                        {**body, 'waypoints': [{'x': .25, 'y': 0., 'yaw': 0.}]}):
            with self.assertRaises(MapRulesError):
                validate_mission(altered, fixture_grid(), now=100., zones=zones,
                                 return_point={'x': 0., 'y': 0., 'yaw': 0.})

    def healthy_bridge(self):
        from builtin_interfaces.msg import Time
        record = MissionRecord()
        record.begin([{'x': 1., 'y': 1., 'yaw': 0.}], False)
        canceled = []
        bridge = SimpleNamespace(lock=threading.RLock(), mission=record,
            rules_store=self.store, rules_apply_state='published', rules_apply_message='读回暂缺',
            rules_hard_failure=False, rules_run=None, rules_mask=build_mask(fixture_grid(), []),
            rules_published_map_id=self.store.map_id, rules_published_revision=0,
            grid=fixture_grid(), lifecycle={'amcl': {'active': True, 'wall': 100.}},
            get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=100_000_000_000)),
            clock_fresh=lambda _ros, _wall: True, fresh=lambda *_args: True,
            client=SimpleNamespace(server_is_ready=lambda: True),
            buffer=SimpleNamespace(lookup_transform=lambda *_args: SimpleNamespace(
                header=SimpleNamespace(stamp=Time(sec=100)),
                transform=SimpleNamespace(translation=SimpleNamespace(x=0., y=0.),
                    rotation=SimpleNamespace(x=0., y=0., z=0., w=1.)))),
            poll_lifecycle=lambda _wall: None, poll_collision_monitor=lambda _wall: None,
            poll_rules=lambda _wall: None, retry_cleanup=lambda _wall: None,
            synchronize_rules=lambda _wall: None,
            goal_sent_wall=98., goal_send_future=None, pending_services=[], operations=queue.Queue(),
            request_cancel=canceled.append, pose=None)
        bridge.evaluate_ready = lambda wall: MissionBridge.evaluate_ready(bridge, wall)
        bridge.record_run = lambda: MissionBridge.record_run(bridge)
        return bridge, canceled

    def dispatch_bridge(self, start=None):
        from builtin_interfaces.msg import Time
        bridge, _canceled = self.healthy_bridge()
        bridge.mission = MissionRecord()
        bridge.ready, bridge.rules_apply_state = True, 'applied'
        source = dict(start or {'x': -.8, 'y': .6, 'yaw': .7})
        reads, goals = [], []
        def transform(*_args):
            reads.append(True)
            return SimpleNamespace(header=SimpleNamespace(stamp=Time(sec=100)),
                transform=SimpleNamespace(translation=SimpleNamespace(x=source['x'], y=source['y']),
                    rotation=SimpleNamespace(x=0., y=0., z=math.sin(source['yaw']/2),
                                             w=math.cos(source['yaw']/2))))
        bridge.buffer = SimpleNamespace(lookup_transform=transform)
        bridge.get_clock = lambda: SimpleNamespace(now=lambda: SimpleNamespace(
            nanoseconds=100_000_000_000, to_msg=lambda: Time(sec=100)))
        def send(goal, **_kwargs):
            goals.append(goal)
            return Future()
        bridge.client.send_goal_async = send
        bridge.reset_cleanup = MethodType(MissionBridge.reset_cleanup, bridge)
        bridge.get_logger = lambda: SimpleNamespace(error=lambda _message: None)
        bridge.pose, bridge.truth = {'x': 0., 'y': 0., 'yaw': 0.}, {'x': 1.8, 'y': 1.8, 'yaw': 2.8}
        bridge.clock_last, bridge.scan_summary, bridge.command = 100., None, None
        bridge.path, bridge.trajectory = [], []
        return bridge, source, reads, goals

    def test_dispatch_captures_nonzero_localized_start_once_and_freezes_every_copy(self):
        bridge, source, reads, goals = self.dispatch_bridge()
        expected = dict(source)
        body = {'waypoints': [{'x': 1., 'y': 1., 'yaw': 0.}], 'return_home': True,
                'issued_at': time.time()}
        MissionBridge.start_mission(bridge, body)
        self.assertEqual(reads, [True])
        self.assertEqual(len(goals), 1)
        last = goals[0].poses[-1].pose
        self.assertEqual((last.position.x, last.position.y), (expected['x'], expected['y']))
        self.assertAlmostEqual(last.orientation.z, math.sin(expected['yaw']/2))
        self.assertAlmostEqual(last.orientation.w, math.cos(expected['yaw']/2))
        self.assertEqual(bridge.mission.value['start_pose'], expected)
        self.assertEqual(bridge.mission.value['waypoints'][-1], expected)
        self.assertEqual(bridge.rules_run['start_pose'], expected)
        self.assertEqual(self.store.runs()['runs'][0]['start_pose'], expected)
        source['x'], source['yaw'], bridge.pose['x'] = .9, -1., 1.4
        self.assertEqual(bridge.mission.value['start_pose'], expected)
        bridge.rules_run['start_pose']['x'] = .8
        self.assertEqual(bridge.mission.value['start_pose'], expected)
        self.assertEqual(bridge.mission.value['waypoints'][-1], expected)

    def test_each_new_mission_captures_its_own_departure_even_without_return(self):
        bridge, source, reads, goals = self.dispatch_bridge()
        body = {'waypoints': [{'x': 1., 'y': 1.}], 'return_home': False, 'issued_at': time.time()}
        MissionBridge.start_mission(bridge, body)
        first = copy.deepcopy(bridge.mission.value['start_pose'])
        bridge.mission.finish(GoalStatus.STATUS_SUCCEEDED, 0, [])
        MissionBridge.record_run(bridge, force=True)
        source.update(x=.4, y=-.8, yaw=-1.1)
        MissionBridge.start_mission(bridge, body)
        self.assertEqual(len(reads), 2)
        self.assertEqual(len(goals), 2)
        self.assertEqual(len(goals[-1].poses), 1)
        self.assertEqual(bridge.mission.value['start_pose'], source)
        self.assertNotEqual(bridge.mission.value['start_pose'], first)

    def test_missing_or_stale_current_tf_rejects_despite_cached_ready_pose(self):
        from builtin_interfaces.msg import Time
        for fault in ('missing', 'old', 'nonfinite', 'clock'):
            with self.subTest(fault=fault):
                bridge, _source, _reads, goals = self.dispatch_bridge()
                if fault == 'clock':
                    bridge.clock_fresh = lambda *_args: False
                elif fault == 'missing':
                    def missing(*_args):
                        raise RuntimeError('No map localization')
                    bridge.buffer.lookup_transform = missing
                else:
                    bridge.buffer.lookup_transform = lambda *_args: SimpleNamespace(
                        header=SimpleNamespace(stamp=Time(sec=98 if fault == 'old' else 100)),
                        transform=SimpleNamespace(translation=SimpleNamespace(x=math.nan if fault == 'nonfinite' else .4,
                            y=.4), rotation=SimpleNamespace(x=0., y=0., z=0., w=1.)))
                with self.assertRaises(APIError) as caught:
                    MissionBridge.start_mission(bridge, {'waypoints': [{'x': 1., 'y': 1.}],
                        'return_home': True, 'issued_at': time.time()})
                self.assertEqual((caught.exception.status, caught.exception.outcome), (503, 'rejected'))
                self.assertEqual(goals, [])
                self.assertEqual(bridge.mission.value['status'], 'idle')
                self.assertIsNone(bridge.mission.value['start_pose'])

    def test_client_cannot_override_captured_start(self):
        bridge, _source, _reads, goals = self.dispatch_bridge()
        with self.assertRaises(APIError) as caught:
            MissionBridge.start_mission(bridge, {'waypoints': [{'x': 1., 'y': 1.}],
                'return_home': True, 'issued_at': time.time(), 'start_pose': {'x': 0., 'y': 0., 'yaw': 0.}})
        self.assertEqual(caught.exception.outcome, 'rejected')
        self.assertEqual(goals, [])

    def test_pre_dispatch_save_failure_restores_previous_task_start_snapshot(self):
        bridge, _source, reads, goals = self.dispatch_bridge()
        bridge.mission.begin([{'x': 1., 'y': 1., 'yaw': 0.}], False,
                             {'x': .4, 'y': -.8, 'yaw': -1.1})
        bridge.mission.finish(GoalStatus.STATUS_SUCCEEDED, 0, [])
        previous = copy.deepcopy(bridge.mission.value)
        with patch.object(self.store, 'save_run', side_effect=MapRulesError('disk failure', 503)):
            with self.assertRaises(MapRulesError) as caught:
                MissionBridge.start_mission(bridge, {'waypoints': [{'x': 1., 'y': 1.}],
                    'return_home': True, 'issued_at': time.time()})
        self.assertEqual(caught.exception.outcome, 'rejected')
        self.assertEqual(reads, [True])
        self.assertEqual(goals, [])
        self.assertEqual(bridge.mission.value, previous)

    def test_unknown_send_receipt_keeps_captured_start_and_never_recaptures_or_replays(self):
        bridge, source, reads, _goals = self.dispatch_bridge()
        expected = dict(source)
        bridge.request_cancel = MethodType(MissionBridge.request_cancel, bridge)
        def fail_send(*_args, **_kwargs):
            raise RuntimeError('unknown receipt')
        bridge.client.send_goal_async = fail_send
        body = {'waypoints': [{'x': 1., 'y': 1.}], 'return_home': True, 'issued_at': time.time()}
        with self.assertRaisesRegex(RuntimeError, 'unknown receipt'):
            MissionBridge.start_mission(bridge, body)
        mission_id = bridge.mission.value['id']
        source.update(x=.4, y=-.8, yaw=-1.1)
        with self.assertRaises(APIError) as caught:
            MissionBridge.start_mission(bridge, body)
        self.assertEqual((caught.exception.status, caught.exception.outcome), (409, 'rejected'))
        self.assertEqual(reads, [True])
        self.assertEqual(bridge.mission.value['start_pose'], expected)
        self.assertEqual(bridge.mission.value['waypoints'][-1], expected)
        self.assertEqual(bridge.mission.value['id'], mission_id)
        self.assertEqual(bridge.mission.value['cleanup_state'], 'unresolved')

    def test_template_save_defers_return_origin_and_retains_boolean_validation(self):
        bridge, _source, _reads, goals = self.dispatch_bridge()
        bridge.clock_fresh = lambda *_args: False
        bridge.buffer.lookup_transform = lambda *_args: self.fail('Saving a template must not resolve a departure pose')
        for returning, status in ((True, 200), ('yes', 400)):
            request = SimpleNamespace(kind='routes', body={'map_id': self.store.map_id, 'name': '将来返航',
                'waypoints': [{'x': 1., 'y': 1.}], 'return_home': returning},
                deadline=102., future=Future())
            bridge.operations.put(request)
            with patch('mission_bridge.time.monotonic', return_value=100.):
                MissionBridge.tick(bridge)
            self.assertEqual(request.future.result()[0], status)
        route = self.store.routes()['routes'][0]
        self.assertTrue(route['return_home'])
        self.assertEqual(len(route['waypoints']), 1)
        self.assertNotIn('start_pose', route)
        self.assertEqual(goals, [])

    def state_harness(self, bridge):
        bridge.domain, bridge.reason = 107, 'ready'
        bridge.obstacle, bridge.obstacle_truth, bridge.obstacle_state_wall = {'state': 'parked'}, {}, None
        bridge.rules_state = lambda: {}
        bridge.collision_monitor_state = lambda _wall: {}
        return bridge

    def test_home_state_freezes_only_active_task_and_idle_preview_uses_live_pose(self):
        bridge, _source, _reads, _goals = self.dispatch_bridge()
        self.state_harness(bridge)
        frozen = {'x': -.8, 'y': .6, 'yaw': .7}
        bridge.mission.begin([{'x': 1., 'y': 1., 'yaw': 0.}], True, frozen)
        bridge.pose = {'x': .9, 'y': -.6, 'yaw': -.8}
        self.assertEqual(MissionBridge.state(bridge)['home'], frozen)
        bridge.mission.request_cancel()
        self.assertEqual(MissionBridge.state(bridge)['home'], frozen)
        bridge.mission.finish(GoalStatus.STATUS_CANCELED, 0, [])
        self.assertEqual(MissionBridge.state(bridge)['home'], bridge.pose)
        self.assertEqual(MissionBridge.state(bridge)['mission']['start_pose'], frozen)
        bridge.ready = False
        self.assertIsNone(MissionBridge.state(bridge)['home'])
        bridge.mission.value.update(status='canceling', start_pose=None)
        self.assertIsNone(MissionBridge.state(bridge)['home'])

    def test_map_change_hides_old_task_home_but_retains_original_snapshot_and_identity(self):
        bridge, _source, _reads, _goals = self.dispatch_bridge()
        self.state_harness(bridge)
        frozen = {'x': -.8, 'y': .6, 'yaw': .7}
        bridge.mission.begin([{'x': 1., 'y': 1., 'yaw': 0.}], True, frozen)
        original_map = self.store.map_id
        bridge.mission.value['map_id'] = original_map
        self.assertEqual(MissionBridge.state(bridge)['home'], frozen)
        changed = fixture_grid()
        changed['data'][0] = 100
        self.store.bind(changed)
        bridge.grid = changed
        state = MissionBridge.state(bridge)
        self.assertIsNone(state['home'])
        self.assertEqual(state['mission']['start_pose'], frozen)
        self.assertEqual(state['mission']['map_id'], original_map)
        self.assertNotEqual(original_map, self.store.map_id)

    def test_reconnection_restores_unknown_task_snapshot_without_current_pose_substitution(self):
        from nav_msgs.msg import OccupancyGrid
        for snapshot in ({'x': -.8, 'y': .6, 'yaw': .7}, None):
            with self.subTest(snapshot=snapshot):
                # Separate map documents exercise new and legacy interrupted records.
                with tempfile.TemporaryDirectory() as directory:
                    store = MapRulesStore(directory)
                    store.bind(fixture_grid())
                    record = {'id': 'interrupted', 'map_id': store.map_id, 'rules_revision': 0,
                        'started_at': 100., 'finished_at': None, 'status': 'running', 'current_index': 0,
                        'waypoints': [{'x': 1., 'y': 1., 'yaw': 0.}], 'return_home': True, 'message': 'running'}
                    if snapshot is not None:
                        record['start_pose'] = snapshot
                    store.save_run(record)
                    bridge = SimpleNamespace(lock=threading.RLock(), mission=MissionRecord(),
                        rules_store=MapRulesStore(directory), pose={'x': 1.4, 'y': -1.4, 'yaw': -2.},
                        publish_rules=lambda: None,
                        request_cancel=lambda _reason: self.fail('A restored unknown task must not be replayed'))
                    msg = OccupancyGrid()
                    msg.header.frame_id = 'map'
                    msg.info.width, msg.info.height, msg.info.resolution = 40, 40, .1
                    msg.info.origin.position.x = msg.info.origin.position.y = -2.
                    msg.info.origin.orientation.w = 1.
                    msg.data = fixture_grid()['data']
                    MissionBridge.on_map(bridge, msg)
                    self.assertEqual(bridge.mission.value['status'], 'canceling')
                    self.assertEqual(bridge.mission.value['cleanup_state'], 'unresolved')
                    self.assertEqual(bridge.mission.value['start_pose'], snapshot)
                    self.assertEqual(bridge.mission.value['id'], 'interrupted')
                    self.assertEqual(bridge.mission.value['map_id'], record['map_id'])

    def test_readback_temporary_gap_does_not_cancel_existing_same_revision_mission(self):
        bridge, canceled = self.healthy_bridge()
        with patch('mission_bridge.time.monotonic', return_value=100.):
            MissionBridge.tick(bridge)
        self.assertTrue(bridge.ready)
        self.assertEqual(canceled, [])
        self.assertEqual(bridge.mission.value['status'], 'running')

    def test_confirmed_filter_loss_uses_existing_cancel_path(self):
        bridge, canceled = self.healthy_bridge()
        bridge.rules_hard_failure = True
        with patch('mission_bridge.time.monotonic', return_value=100.):
            MissionBridge.tick(bridge)
        self.assertFalse(bridge.ready)
        self.assertEqual(canceled, ['仿真未就绪：读回暂缺'])

    def test_new_mission_requires_actual_applied_state(self):
        bridge, _canceled = self.healthy_bridge()
        bridge.mission = MissionRecord()
        bridge.ready = True
        with self.assertRaises(APIError) as caught:
            MissionBridge.start_mission(bridge, {'waypoints': [{'x': 1., 'y': 1.}], 'issued_at': time.time()})
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(caught.exception.outcome, 'rejected')
        self.assertEqual(bridge.mission.value['status'], 'idle')

    def test_map_and_rules_metadata_accept_current_and_reject_stale_before_dispatch(self):
        bridge, _canceled = self.healthy_bridge()
        bridge.mission = MissionRecord()
        bridge.ready, bridge.rules_apply_state = True, 'applied'
        body = {'waypoints': [{'x': 1., 'y': 1.}], 'issued_at': time.time(),
                'map_id': self.store.map_id, 'rules_revision': 0}
        self.assertEqual(len(MissionBridge.prepare_mission(bridge, body)[0]), 1)
        for changes, status in (({'map_id': 'other'}, 409), ({'rules_revision': 1}, 409),
                                ({'rules_revision': True}, 400), ({'rules_revision': math.nan}, 400),
                                ({'rules_revision': .5}, 400), ({'rules_revision': -1}, 400)):
            with self.subTest(changes=changes), self.assertRaises((APIError, MapRulesError)) as caught:
                MissionBridge.prepare_mission(bridge, {**body, **changes})
            self.assertEqual(caught.exception.status, status)
            self.assertEqual(caught.exception.outcome, 'rejected')
        legacy = {key: value for key, value in body.items() if key not in {'map_id', 'rules_revision'}}
        self.assertEqual(len(MissionBridge.prepare_mission(bridge, legacy)[0]), 1)

    def test_rule_rejection_binds_actual_snapshot_without_begin_or_dispatch(self):
        bridge, _canceled = self.healthy_bridge()
        self.store.update_rules({'map_id': self.store.map_id, 'base_revision': 0,
                                 'zones': [self.rectangle]})
        bridge.mission = MissionRecord()
        bridge.ready, bridge.rules_apply_state, bridge.rules_published_revision = True, 'applied', 1
        bridge.client.send_goal_async = lambda *_args, **_kwargs: self.fail('Rejected goal must not dispatch')
        body = {'waypoints': [{'x': 1., 'y': 1.}, {'x': .25, 'y': 0.}],
                'issued_at': time.time(), 'map_id': self.store.map_id, 'rules_revision': 1}
        with self.assertRaises(MapRulesError) as caught:
            MissionBridge.start_mission(bridge, body)
        self.assertEqual(caught.exception.outcome, 'rejected')
        issue = caught.exception.issue
        self.assertEqual(issue['map_id'], self.store.map_id)
        self.assertEqual(issue['rules_revision'], 1)
        self.assertEqual((issue['target'], issue['waypoint_index']), ('waypoint', 2))
        self.assertEqual(issue['rule_id'], self.rectangle['id'])
        self.assertEqual(bridge.mission.value['status'], 'idle')
        self.assertIsNone(bridge.mission.value['id'])

    def test_queue_preserves_authoritative_issue_for_rule_and_occupancy_rejections(self):
        bridge, _canceled = self.healthy_bridge()
        bridge.mission = MissionRecord()
        bridge.ready, bridge.rules_apply_state = True, 'applied'
        bridge.start_mission = MethodType(MissionBridge.start_mission, bridge)
        bridge.client.send_goal_async = lambda *_args, **_kwargs: self.fail('Rejected goal must not dispatch')
        bridge.get_logger = lambda: SimpleNamespace(error=lambda message: self.fail(message))
        # The real operation queue must carry the structured issue, not only its error text.
        for occupancy, kind in ((100, 'occupied_cell'), (-1, 'unknown_cell')):
            bridge.grid['data'][20*40+20] = occupancy
            request = SimpleNamespace(kind='mission', body={'waypoints': [{'x': .05, 'y': .05}],
                'issued_at': time.time()}, deadline=102., future=Future())
            bridge.operations.put(request)
            with patch('mission_bridge.time.monotonic', return_value=100.):
                MissionBridge.tick(bridge)
            status, result = request.future.result()
            self.assertEqual(status, 400)
            self.assertEqual(result['outcome'], 'rejected')
            self.assertEqual(result['issue']['kind'], kind)
            self.assertEqual(result['issue']['map_id'], self.store.map_id)
            self.assertEqual(result['issue']['rules_revision'], 0)
            self.assertEqual(result['issue']['waypoint_index'], 1)
            self.assertEqual(bridge.mission.value['status'], 'idle')
        bridge.grid['data'][20*40+20] = 0
        self.store.update_rules({'map_id': self.store.map_id, 'base_revision': 0,
                                 'zones': [self.rectangle]})
        bridge.rules_published_revision = 1
        request = SimpleNamespace(kind='mission', body={'waypoints': [{'x': .25, 'y': 0.}],
            'issued_at': time.time()}, deadline=102., future=Future())
        bridge.operations.put(request)
        with patch('mission_bridge.time.monotonic', return_value=100.):
            MissionBridge.tick(bridge)
        status, result = request.future.result()
        self.assertEqual(status, 400)
        self.assertEqual(result['outcome'], 'rejected')
        self.assertEqual(result['issue']['kind'], 'map_rule')
        self.assertEqual(result['issue']['rules_revision'], 1)
        self.assertEqual(result['issue']['rule_id'], self.rectangle['id'])
        self.assertEqual(bridge.mission.value['status'], 'idle')

    def test_active_and_unknown_mission_cannot_edit_rules_through_operation_queue(self):
        bridge, _canceled = self.healthy_bridge()
        bridge.publish_rules = lambda: self.fail('Active rules must not be published')
        bridge.rules_state = lambda: self.fail('Active edit must not succeed')
        for status, cleanup in (('running', None), ('canceling', 'unresolved')):
            bridge.mission.value.update(status=status, cleanup_state=cleanup)
            op = SimpleNamespace(kind='map-rules', body={'map_id': self.store.map_id,
                'base_revision': 0, 'zones': [self.rectangle]}, deadline=102., future=Future())
            bridge.operations.put(op)
            with patch('mission_bridge.time.monotonic', return_value=100.):
                MissionBridge.tick(bridge)
            self.assertEqual(op.future.result()[0], 409)
            self.assertEqual(self.store.document['revision'], 0)

    def test_old_revision_query_callback_cannot_confirm_new_mask(self):
        future = Future()
        future.set_result(SimpleNamespace(values=[]))
        check = {'params_future': future, 'params_ok': False, 'config_invalid': False}
        bridge = SimpleNamespace(lock=threading.RLock(), rules_checks={'global': check}, rules_epoch=2)
        MissionBridge.rules_result(bridge, 'global', 'params', 1, future)
        self.assertFalse(check['params_ok'])
        self.assertFalse(check['config_invalid'])
        self.assertIsNone(check['params_future'])

    def test_real_terminal_is_persisted_with_rule_version_and_independent_truth(self):
        bridge, _canceled = self.healthy_bridge()
        bridge.rules_run_store = self.store
        bridge.rules_run = {'id': bridge.mission.value['id'], 'map_id': self.store.map_id,
            'rules_revision': 0, 'started_at': 100., 'finished_at': None,
            'status': 'running', 'current_index': 0, 'waypoints': bridge.mission.value['waypoints'],
            'return_home': False, 'message': '等待', 'events': [], 'observations': []}
        bridge.rules_run_signature = None
        bridge.rules_run_sample_wall = bridge.rules_run_save_wall = 0.
        bridge.truth = {'x': 1.1, 'y': 1., 'yaw': .1}
        bridge.clock_last = 100.
        bridge.path, bridge.command, bridge.scan_summary = [], None, None
        bridge.mission.finish(GoalStatus.STATUS_SUCCEEDED, 0, [])
        MissionBridge.record_run(bridge, force=True)
        persisted = self.store.runs()['runs'][0]
        self.assertEqual(persisted['status'], 'succeeded')
        self.assertIsNotNone(persisted['finished_at'])
        self.assertEqual(persisted['truth']['x'], 1.1)
        self.assertEqual(persisted['rules_revision'], 0)
        self.assertNotIn('physical_score', persisted)
        self.assertEqual(persisted['events'][-1]['status'], 'succeeded')

    def test_other_writer_rules_refreshed_by_route_save_are_never_falsely_applied(self):
        from builtin_interfaces.msg import Time
        bridge, _canceled = self.healthy_bridge()
        bridge.mission = MissionRecord()
        self.store.update_rules({'map_id': self.store.map_id, 'base_revision': 0, 'zones': []})
        bridge.rules_published_revision = 1
        bridge.rules_apply_state, bridge.ready = 'applied', True
        other = MapRulesStore(self.directory.name)
        other.bind(fixture_grid())
        other.update_rules({'map_id': other.map_id, 'base_revision': 1, 'zones': [self.rectangle]})
        self.store.save_route({'map_id': self.store.map_id, 'name': '保存路线',
            'waypoints': [{'x': 1., 'y': 1., 'yaw': 0.}], 'return_home': False})
        self.assertEqual(self.store.document['revision'], 2)
        state = MissionBridge.rules_state(bridge)
        self.assertEqual(state['revision'], 2)
        self.assertEqual(state['apply_state'], 'unavailable')
        self.assertEqual(bridge.rules_published_revision, 1)
        with self.assertRaises(APIError) as caught:
            MissionBridge.prepare_mission(bridge,
                {'waypoints': [{'x': 1., 'y': 1.}], 'issued_at': time.time()})
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.outcome, 'rejected')
        masks, infos = [], []
        bridge.rules_epoch, bridge.rules_checks, bridge.rules_refresh_wall = 1, {}, 0.
        bridge.rules_mask_publisher, bridge.rules_info_publisher = (
            SimpleNamespace(publish=masks.append), SimpleNamespace(publish=infos.append))
        bridge.get_clock = lambda: SimpleNamespace(now=lambda: SimpleNamespace(to_msg=lambda: Time(sec=100)))
        bridge.published_rules_current = MethodType(MissionBridge.published_rules_current, bridge)
        bridge.publish_rules = MethodType(MissionBridge.publish_rules, bridge)
        MissionBridge.synchronize_rules(bridge, 100.)
        self.assertEqual(bridge.rules_published_revision, 2)
        self.assertEqual(bridge.rules_epoch, 2)
        self.assertEqual(len(masks), 1)
        self.assertEqual(len(infos), 1)
        self.assertEqual(MissionBridge.rules_state(bridge)['apply_state'], 'published')

    def test_external_rules_change_is_detected_before_new_goal_without_an_intervening_write(self):
        bridge, _canceled = self.healthy_bridge()
        bridge.mission = MissionRecord()
        bridge.rules_apply_state, bridge.ready = 'applied', True
        other = MapRulesStore(self.directory.name)
        other.bind(fixture_grid())
        other.update_rules({'map_id': other.map_id, 'base_revision': 0, 'zones': [self.rectangle]})
        with self.assertRaises(APIError) as caught:
            MissionBridge.prepare_mission(bridge,
                {'waypoints': [{'x': 1., 'y': 1.}], 'issued_at': time.time()})
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.store.document['revision'], 1)
        self.assertEqual(bridge.rules_published_revision, 0)

    def test_full_queue_http_response_is_authoritatively_rejected(self):
        operations = queue.Queue(maxsize=1)
        operations.put(object())
        bridge = SimpleNamespace(operations=operations)
        bridge.enqueue = lambda kind, body: MissionBridge.enqueue(bridge, kind, body)
        replies = []
        encoded = json.dumps({'waypoints': [{'x': 1., 'y': 1.}], 'issued_at': time.time()}).encode()
        handler = SimpleNamespace(path='/sim-api/mission', allowed=lambda: True,
            server=SimpleNamespace(bridge=bridge), rfile=io.BytesIO(encoded),
            headers={'Content-Type': 'application/json', 'Content-Length': str(len(encoded))},
            reply=lambda status, body: replies.append((status, body)))
        Handler.do_POST(handler)
        self.assertEqual(replies[0][0], 503)
        self.assertEqual(replies[0][1]['outcome'], 'rejected')
        self.assertEqual(operations.qsize(), 1)

    def test_http_direct_api_error_preserves_issue_and_rejection(self):
        issue = {'kind': 'map_boundary', 'target': 'waypoint', 'waypoint_index': 3,
                 'point': {'x': 2.1, 'y': 0., 'yaw': 0.}, 'blocking_point': {'x': 2., 'y': 0.}}
        def reject(_kind, _body):
            raise APIError('Waypoint footprint is outside the map', outcome='rejected', issue=issue)
        replies = []
        encoded = json.dumps({'waypoints': [{'x': 2.1, 'y': 0.}], 'issued_at': time.time()}).encode()
        handler = SimpleNamespace(path='/sim-api/mission', allowed=lambda: True,
            server=SimpleNamespace(bridge=SimpleNamespace(enqueue=reject)), rfile=io.BytesIO(encoded),
            headers={'Content-Type': 'application/json', 'Content-Length': str(len(encoded))},
            reply=lambda status, body: replies.append((status, body)))
        Handler.do_POST(handler)
        self.assertEqual(replies, [(400, {'error': 'Waypoint footprint is outside the map',
                                        'outcome': 'rejected', 'issue': issue})])

    def test_expired_queue_request_is_rejected_without_dispatch(self):
        bridge, _canceled = self.healthy_bridge()
        request = SimpleNamespace(kind='mission', body={}, deadline=99., future=Future())
        bridge.operations.put(request)
        with patch('mission_bridge.time.monotonic', return_value=100.):
            MissionBridge.tick(bridge)
        self.assertEqual(request.future.result()[0], 408)
        self.assertEqual(request.future.result()[1]['outcome'], 'rejected')


class MapRulesFilterRecoveryTests(unittest.TestCase):
    def harness(self):
        bridge = SimpleNamespace(lock=threading.RLock(), rules_store=SimpleNamespace(error=None),
            rules_mask=build_mask(fixture_grid(), []), rules_check_wall=0., rules_epoch=1,
            previous_rules_mask=None,
            rules_hard_failure=False, rules_graph_missing_since=None, rules_graph_missing_last=None,
            rules_checks={}, lifecycle={}, rules_subscribers_present=lambda: True,
            get_logger=lambda: SimpleNamespace(debug=lambda _message: None))
        for name in ('global', 'local'):
            bridge.rules_checks[name] = {'params_ok': True, 'config_invalid': False,
                'config_reason': '', 'costmap_ok': True, 'wall': 0.,
                'mismatch_since': None, 'mismatch_last': None,
                'params_future': Future(), 'costmap_future': Future(),
                'params_sent': 0., 'costmap_sent': 0.}
            bridge.lifecycle[f'{name}_costmap/{name}_costmap'] = {'active': True, 'wall': 0.}
        return bridge

    def poll(self, bridge, wall, present):
        if isinstance(present, Exception):
            def query():
                raise present
            bridge.rules_subscribers_present = query
        else:
            bridge.rules_subscribers_present = lambda: present
        # Keep independent parameter/costmap replies current while exercising
        # only the graph evidence. Pending slots avoid unrelated RPC creation.
        for name, check in bridge.rules_checks.items():
            check.update(wall=wall, params_sent=wall, costmap_sent=wall)
            for kind in ('params', 'costmap'):
                if check[kind+'_future'] is None:
                    check[kind+'_future'] = Future()
            bridge.lifecycle[f'{name}_costmap/{name}_costmap']['wall'] = wall
        MissionBridge.poll_rules(bridge, wall)

    def values(self, enabled=True):
        from rcl_interfaces.msg import ParameterType, ParameterValue
        return [ParameterValue(type=ParameterType.PARAMETER_STRING_ARRAY,
                               string_array_value=['keepout_filter', 'keepout_inflation']),
            ParameterValue(type=ParameterType.PARAMETER_STRING, string_value='nav2_costmap_2d::KeepoutFilter'),
            ParameterValue(type=ParameterType.PARAMETER_BOOL, bool_value=enabled),
            ParameterValue(type=ParameterType.PARAMETER_STRING, string_value='/keepout_costmap_filter_info'),
            ParameterValue(type=ParameterType.PARAMETER_DOUBLE, double_value=.13)]

    def params_result(self, bridge, values=None, error=None):
        future = Future()
        if error:
            future.set_exception(error)
        else:
            future.set_result(SimpleNamespace(values=values))
        bridge.rules_checks['global']['params_future'] = future
        MissionBridge.rules_result(bridge, 'global', 'params', 1, future)
        bridge.rules_checks['global']['params_future'] = Future()

    def test_clear_recovery_short_subscription_gap_does_not_become_hard_failure(self):
        bridge = self.harness()
        for wall in (100., 100.75, 101.5, 102.25):
            self.poll(bridge, wall, False)
            self.assertFalse(bridge.rules_hard_failure)
            self.assertEqual(bridge.rules_apply_state, 'published')
        self.poll(bridge, 103., True)
        self.assertFalse(bridge.rules_hard_failure)
        self.assertEqual(bridge.rules_apply_state, 'applied')
        self.assertIsNone(bridge.rules_graph_missing_since)

    def test_successive_missing_observations_for_three_seconds_are_hard_failure(self):
        bridge = self.harness()
        for wall in (100., 100.75, 101.5, 102.25):
            self.poll(bridge, wall, False)
            self.assertFalse(bridge.rules_hard_failure)
        self.poll(bridge, 103., False)
        self.assertTrue(bridge.rules_hard_failure)
        self.assertIn('连续缺失至少3秒', bridge.rules_apply_message)
        self.poll(bridge, 103.75, True)
        self.assertFalse(bridge.rules_hard_failure)
        self.assertEqual(bridge.rules_apply_state, 'applied')

    def test_query_exception_breaks_missing_evidence_instead_of_extending_it(self):
        bridge = self.harness()
        self.poll(bridge, 100., False)
        self.poll(bridge, 100.75, False)
        self.poll(bridge, 101.5, RuntimeError('DDS graph temporarily unavailable'))
        self.assertIsNone(bridge.rules_graph_missing_since)
        self.poll(bridge, 102.25, False)
        self.poll(bridge, 103., False)
        self.assertFalse(bridge.rules_hard_failure)
        self.assertEqual(bridge.rules_graph_missing_since, 102.25)

    def test_unobserved_long_gap_cannot_prove_continuous_disappearance(self):
        bridge = self.harness()
        self.poll(bridge, 100., False)
        self.poll(bridge, 104., False)
        self.assertFalse(bridge.rules_hard_failure)
        self.assertEqual(bridge.rules_graph_missing_since, 104.)

    def test_complete_explicit_disable_is_hard_and_has_priority_over_graph(self):
        bridge = self.harness()
        self.params_result(bridge, self.values(enabled=False))
        self.poll(bridge, 100., False)
        self.assertTrue(bridge.rules_hard_failure)
        self.assertIn('配置失配', bridge.rules_apply_message)
        self.assertIn('enabled', bridge.rules_apply_message)
        self.params_result(bridge, self.values())
        self.poll(bridge, 100.75, True)
        self.assertFalse(bridge.rules_hard_failure)
        self.assertEqual(bridge.rules_apply_state, 'applied')

    def test_undeclared_parameters_and_service_loss_are_unknown_not_disabled(self):
        from rcl_interfaces.msg import ParameterValue
        bridge = self.harness()
        for values in ([], [ParameterValue() for _ in range(5)]):
            self.params_result(bridge, values)
            self.poll(bridge, 100.+bridge.rules_check_wall, True)
            self.assertFalse(bridge.rules_checks['global']['params_ok'])
            self.assertFalse(bridge.rules_checks['global']['config_invalid'])
            self.assertFalse(bridge.rules_hard_failure)
            self.assertEqual(bridge.rules_apply_state, 'published')
        self.params_result(bridge, error=RuntimeError('response lost'))
        self.poll(bridge, bridge.rules_check_wall+.75, True)
        self.assertFalse(bridge.rules_hard_failure)
        self.assertEqual(bridge.rules_apply_state, 'published')

    def deletion_bridge(self):
        bridge = self.harness()
        bridge.grid = fixture_grid()
        retained = {'id': 'retained', 'kind': 'wall', 'width': .02, 'points': [
            {'x': -.4, 'y': .4}, {'x': -.4, 'y': .8}]}
        removed = {'id': 'removed', 'kind': 'no_go', 'points': [
            {'x': -1.5, 'y': 1.}, {'x': -1.2, 'y': 1.},
            {'x': -1.2, 'y': 1.3}, {'x': -1.5, 'y': 1.3}]}
        bridge.rules_mask = build_mask(bridge.grid, [retained])
        bridge.previous_rules_mask = build_mask(bridge.grid, [retained, removed])
        bridge.rules_publish_stamp = 99.
        bridge.rules_checks['global']['costmap_ok'] = False
        bridge.rules_checks['local']['costmap_ok'] = False
        return bridge

    def deletion_result(self, bridge, name, wall, observed):
        from builtin_interfaces.msg import Time
        from nav2_msgs.msg import Costmap
        bridge.get_clock = lambda: SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=int(wall*1e9)))
        msg = Costmap()
        msg.header.frame_id = 'map'
        msg.metadata.size_x, msg.metadata.size_y, msg.metadata.resolution = 40, 40, .1
        msg.metadata.origin.position.x, msg.metadata.origin.position.y = -2., -2.
        msg.metadata.origin.orientation.w = 1.
        msg.metadata.update_time = Time(sec=int(wall), nanosec=int((wall-int(wall))*1e9))
        msg.data = observed
        future = Future()
        future.set_result(SimpleNamespace(map=msg))
        bridge.rules_checks[name]['costmap_future'] = future
        with patch('mission_bridge.time.monotonic', return_value=wall):
            MissionBridge.rules_result(bridge, name, 'costmap', 1, future)

    def test_completed_deletion_does_not_revoke_rules_when_a_live_obstacle_arrives_later(self):
        bridge = self.deletion_bridge()
        previous = copy.deepcopy(bridge.previous_rules_mask)
        cleared = [254 if cell == 100 else 0 for cell in bridge.rules_mask['data']]
        self.deletion_result(bridge, 'global', 100., cleared)
        self.poll(bridge, 100., True)
        self.assertEqual(bridge.rules_apply_state, 'published')
        self.assertIsNotNone(bridge.previous_rules_mask)
        self.deletion_result(bridge, 'local', 100.75, cleared)
        self.poll(bridge, 100.75, True)
        self.assertEqual(bridge.rules_apply_state, 'applied')
        self.assertIsNone(bridge.previous_rules_mask)

        observed = list(cleared)
        removed_cell = next(i for i, cell in enumerate(previous['data'])
                            if cell == 100 and bridge.rules_mask['data'][i] == 0)
        observed[removed_cell] = 254  # Newly observed physical obstacle, after deletion was confirmed.
        for name in ('global', 'local'):
            self.deletion_result(bridge, name, 101.5, observed)
        self.poll(bridge, 101.5, True)
        self.assertEqual(bridge.rules_apply_state, 'applied')

        retained_cell = bridge.rules_mask['data'].index(100)
        observed[retained_cell] = 0  # Current virtual wall still requires continuous confirmation.
        self.deletion_result(bridge, 'global', 102.25, observed)
        self.poll(bridge, 102.25, True)
        self.assertEqual(bridge.rules_apply_state, 'published')

    def test_unconfirmed_deleted_lethal_or_unknown_cells_are_never_retired(self):
        for value in (254, 255):
            with self.subTest(value=value):
                bridge = self.deletion_bridge()
                observed = [254 if cell == 100 else 0 for cell in bridge.rules_mask['data']]
                removed_cell = next(i for i, cell in enumerate(bridge.previous_rules_mask['data'])
                                    if cell == 100 and bridge.rules_mask['data'][i] == 0)
                observed[removed_cell] = value
                for name in ('global', 'local'):
                    self.deletion_result(bridge, name, 100., observed)
                self.poll(bridge, 100., True)
                self.assertEqual(bridge.rules_apply_state, 'published')
                self.assertIsNotNone(bridge.previous_rules_mask)
                self.assertFalse(bridge.rules_hard_failure)

    def test_new_publication_reinstates_deletion_verification_after_an_applied_revision(self):
        from builtin_interfaces.msg import Time
        bridge = self.deletion_bridge()
        current = copy.deepcopy(bridge.rules_mask)
        cleared = [254 if cell == 100 else 0 for cell in current['data']]
        for name in ('global', 'local'):
            self.deletion_result(bridge, name, 100., cleared)
        self.poll(bridge, 100., True)
        self.assertIsNone(bridge.previous_rules_mask)
        bridge.rules_store = SimpleNamespace(error=None, map_id='same_map', document={'revision': 3, 'zones': []})
        bridge.rules_mask_publisher = SimpleNamespace(publish=lambda _message: None)
        bridge.rules_info_publisher = SimpleNamespace(publish=lambda _message: None)
        bridge.get_clock = lambda: SimpleNamespace(now=lambda: SimpleNamespace(to_msg=lambda: Time(sec=101)))
        MissionBridge.publish_rules(bridge)
        self.assertEqual(bridge.previous_rules_mask, current)
        self.assertEqual(bridge.rules_apply_state, 'published')
        self.assertTrue(all(not check['costmap_ok'] for check in bridge.rules_checks.values()))


    def costmap_result(self, bridge, wall, value, frame='map', stamp=None, error=None):
        from builtin_interfaces.msg import Time
        from nav2_msgs.msg import Costmap
        stamp = wall if stamp is None else stamp
        bridge.grid = fixture_grid()
        bridge.rules_mask = build_mask(bridge.grid, [{'id': 'test_zone', 'kind': 'no_go', 'points': [
            {'x': 0., 'y': 0.}, {'x': .5, 'y': 0.}, {'x': .5, 'y': .5}, {'x': 0., 'y': .5}]}])
        bridge.previous_rules_mask = None
        bridge.rules_publish_stamp = 99.
        bridge.get_clock = lambda: SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=int(wall*1e9)))
        msg = Costmap()
        msg.header.frame_id = frame
        msg.metadata.size_x, msg.metadata.size_y, msg.metadata.resolution = 40, 40, .1
        msg.metadata.origin.position.x, msg.metadata.origin.position.y = -2., -2.
        msg.metadata.origin.orientation.w = 1.
        msg.metadata.update_time = Time(sec=int(stamp), nanosec=int((stamp-int(stamp))*1e9))
        msg.data = [value if cell == 100 else 0 for cell in bridge.rules_mask['data']]
        future = Future()
        if error:
            future.set_exception(error)
        else:
            future.set_result(SimpleNamespace(map=msg))
        bridge.rules_checks['global']['costmap_future'] = future
        with patch('mission_bridge.time.monotonic', return_value=wall):
            MissionBridge.rules_result(bridge, 'global', 'costmap', 1, future)
        return msg

    def test_short_valid_costmap_counterevidence_then_match_does_not_cancel_recovery(self):
        bridge = self.harness()
        for wall in (100., 100.75, 101.5, 102.25):
            self.costmap_result(bridge, wall, 0)
            self.poll(bridge, wall, True)
            self.assertFalse(bridge.rules_hard_failure)
            self.assertEqual(bridge.rules_apply_state, 'published')
        self.costmap_result(bridge, 103., 254)
        self.poll(bridge, 103., True)
        self.assertFalse(bridge.rules_hard_failure)
        self.assertEqual(bridge.rules_apply_state, 'applied')
        self.assertIsNone(bridge.rules_checks['global']['mismatch_since'])

    def test_successive_valid_native_missing_cells_for_three_seconds_are_hard_failure(self):
        bridge = self.harness()
        for wall in (100., 100.75, 101.5, 102.25):
            self.costmap_result(bridge, wall, 0)
            self.poll(bridge, wall, True)
            self.assertFalse(bridge.rules_hard_failure)
        self.costmap_result(bridge, 103., 0)
        self.poll(bridge, 103., True)
        self.assertTrue(bridge.rules_hard_failure)
        self.assertIn('禁区格连续读回未生效', bridge.rules_apply_message)
        self.costmap_result(bridge, 103.75, 254)
        self.poll(bridge, 103.75, True)
        self.assertFalse(bridge.rules_hard_failure)

    def test_unknown_invalid_stale_and_error_replies_break_counterevidence(self):
        for value, stamp, error in ((255, None, None), (0, 99., None),
                                    (0, 90., None), (0, None, RuntimeError('reply lost'))):
            with self.subTest(value=value, stamp=stamp, error=error):
                bridge = self.harness()
                self.costmap_result(bridge, 100., 0)
                self.costmap_result(bridge, 100.75, 0)
                self.costmap_result(bridge, 101.5, value, stamp=stamp, error=error)
                self.assertIsNone(bridge.rules_checks['global']['mismatch_since'])
                self.costmap_result(bridge, 102.25, 0)
                self.poll(bridge, 102.25, True)
                self.assertFalse(bridge.rules_hard_failure)
                self.assertEqual(bridge.rules_checks['global']['mismatch_since'], 102.25)

    def test_long_unobserved_costmap_gap_does_not_prove_continuous_failure(self):
        bridge = self.harness()
        self.costmap_result(bridge, 100., 0)
        self.costmap_result(bridge, 104., 0)
        self.poll(bridge, 104., True)
        self.assertFalse(bridge.rules_hard_failure)
        self.assertEqual(bridge.rules_checks['global']['mismatch_since'], 104.)

    def test_non_map_frame_uses_snapshot_time_tf_and_does_not_accumulate_hard_counterevidence(self):
        bridge = self.harness()
        requested = []
        def transform(_target, _source, stamp):
            requested.append(stamp.nanoseconds)
            return SimpleNamespace(transform=SimpleNamespace(
                translation=SimpleNamespace(x=0., y=0.), rotation=SimpleNamespace(x=0., y=0., z=0., w=1.)))
        bridge.buffer = SimpleNamespace(lookup_transform=transform)
        self.costmap_result(bridge, 100.75, 0, frame='odom')
        self.assertEqual(requested, [100_750_000_000])
        self.assertIsNone(bridge.rules_checks['global']['mismatch_since'])


class NativeBackupTests(unittest.TestCase):
    identity = 'd44b9ba6-ac8e-49dc-83c4-86caf4a14390'

    def body(self, **changes):
        return {'mission_id': self.identity, 'operation': 'backup', 'distance_m': .3,
                'issued_at': 100., **changes}

    def test_derives_rear_endpoint_from_localization_and_preserves_heading(self):
        start = {'x': .4, 'y': .6, 'yaw': math.pi/2}
        points, returning = validate_backup(self.body(), fixture_grid(), start, now=100.)
        self.assertFalse(returning)
        self.assertAlmostEqual(points[0]['x'], .4)
        self.assertAlmostEqual(points[0]['y'], .3)
        self.assertAlmostEqual(points[0]['yaw'], math.pi/2)
        self.assertEqual(start, {'x': .4, 'y': .6, 'yaw': math.pi/2})

    def test_rejects_mixed_goals_unbounded_motion_and_stale_requests(self):
        start = {'x': 0., 'y': 0., 'yaw': 0.}
        for changed in ({'distance_m': 0.}, {'distance_m': -.3}, {'distance_m': 1.01},
                {'distance_m': True}, {'distance_m': math.nan}, {'mission_id': None},
                {'operation': 'forward'}, {'waypoints': []}, {'return_home': False},
                {'issued_at': 96.9}, {'issued_at': 101.1}, {'timeout_s': .49},
                {'timeout_s': 360.1}, {'timeout_s': True}):
            with self.subTest(changed=changed), self.assertRaises(APIError):
                validate_backup(self.body(**changed), fixture_grid(), start, now=100.)
        for distance in (.05, 1.):
            points, _returning = validate_backup(self.body(distance_m=distance),
                fixture_grid(), start, now=100.)
            self.assertAlmostEqual(points[0]['x'], -distance)

    def test_sweep_rejects_occupied_middle_even_when_endpoint_is_free(self):
        grid = fixture_grid()
        grid['data'][20*40+20] = 100
        end = {'x': -.5, 'y': 0., 'yaw': 0.}
        require_free_point(end, grid)
        with self.assertRaises(APIError) as caught:
            validate_backup(self.body(distance_m=1.), grid,
                            {'x': .5, 'y': 0., 'yaw': 0.}, now=100.)
        self.assertEqual(caught.exception.issue['target'], 'backup_sweep')
        self.assertEqual(caught.exception.issue['kind'], 'occupied_cell')
        self.assertEqual(caught.exception.issue['destination'], end)
        self.assertGreater(caught.exception.issue['sweep_fraction'], 0.)
        self.assertLess(caught.exception.issue['sweep_fraction'], 1.)

    def test_sweep_rejects_thin_virtual_wall_and_map_start_boundary(self):
        wall = {'id': 'rear_wall', 'kind': 'wall', 'width': .01,
                'points': [{'x': 0., 'y': -.5}, {'x': 0., 'y': .5}]}
        with self.assertRaises(MapRulesError) as caught:
            validate_backup(self.body(distance_m=1.), fixture_grid(),
                {'x': .5, 'y': 0., 'yaw': 0.}, now=100., zones=[wall])
        self.assertEqual(caught.exception.issue['target'], 'backup_sweep')
        self.assertEqual(caught.exception.issue['rule_id'], 'rear_wall')
        with self.assertRaises(APIError) as boundary:
            validate_backup(self.body(), fixture_grid(),
                {'x': 1.9, 'y': 0., 'yaw': 0.}, now=100.)
        self.assertEqual(boundary.exception.issue['kind'], 'map_boundary')
        self.assertEqual(boundary.exception.issue['sweep_fraction'], 0.)

    def bridge(self):
        existing = MapRulesIntegrationBoundaryTests()
        existing.setUp()
        self.addCleanup(existing.directory.cleanup)
        bridge, source, reads, waypoint_goals = existing.dispatch_bridge()
        backup_goals = []
        bridge.lifecycle['behavior_server'] = {'active': True, 'wall': time.monotonic()}
        bridge.backup_client = SimpleNamespace(server_is_ready=lambda: True,
            send_goal_async=lambda goal, **_kwargs: backup_goals.append(goal) or Future())
        return bridge, source, reads, waypoint_goals, backup_goals

    def test_dispatch_uses_native_negative_target_and_one_original_owner(self):
        from nav2_msgs.action import BackUp
        bridge, source, reads, waypoint_goals, backup_goals = self.bridge()
        body = self.body(issued_at=time.time(), timeout_s=30.75,
                         map_id=bridge.rules_store.map_id, rules_revision=0)
        MissionBridge.start_mission(bridge, body)
        self.assertEqual(len(backup_goals), 1)
        self.assertEqual(waypoint_goals, [])
        self.assertIsInstance(backup_goals[0], BackUp.Goal)
        self.assertAlmostEqual(backup_goals[0].target.x, -.3)
        self.assertEqual((backup_goals[0].target.y, backup_goals[0].target.z), (0., 0.))
        self.assertAlmostEqual(backup_goals[0].speed, .08)
        self.assertEqual((backup_goals[0].time_allowance.sec,
                          backup_goals[0].time_allowance.nanosec), (30, 750_000_000))
        self.assertEqual(reads, [True])
        self.assertEqual(bridge.mission.value['id'], self.identity)
        self.assertEqual(bridge.mission.value['native_action'], '/backup')
        self.assertEqual(bridge.mission.value['operation'], 'backup')
        self.assertEqual(bridge.mission.value['start_pose'], source)
        self.assertAlmostEqual(bridge.mission.value['waypoints'][0]['x'],
                               source['x']-.3*math.cos(source['yaw']))
        self.assertEqual(bridge.rules_store.runs()['runs'][0]['native_action'], '/backup')
        with self.assertRaises(APIError):
            MissionBridge.start_mission(bridge, body)
        self.assertEqual(len(backup_goals), 1)

    def test_default_backup_timeout_is_bounded_and_duration_rounding_is_normalized(self):
        for requested, expected in ((None, (30, 0)), (1.9999999999, (2, 0))):
            with self.subTest(requested=requested):
                bridge, _source, _reads, _waypoint, goals = self.bridge()
                body = self.body(issued_at=time.time())
                if requested is not None:
                    body['timeout_s'] = requested
                MissionBridge.start_mission(bridge, body)
                self.assertEqual((goals[0].time_allowance.sec, goals[0].time_allowance.nanosec), expected)
                self.assertEqual(bridge.mission.value['timeout_s'], requested or 30.)

    def test_backup_readiness_is_specific_and_rejection_never_dispatches(self):
        for failure in ('inactive', 'stale', 'unavailable', 'changed_map', 'changed_rules'):
            with self.subTest(failure=failure):
                bridge, _source, _reads, _waypoint, goals = self.bridge()
                body = self.body(issued_at=time.time())
                if failure == 'inactive':
                    bridge.lifecycle['behavior_server']['active'] = False
                elif failure == 'stale':
                    bridge.lifecycle['behavior_server']['wall'] -= 3.1
                elif failure == 'unavailable':
                    bridge.backup_client.server_is_ready = lambda: False
                elif failure == 'changed_map':
                    body['map_id'] = 'different'
                else:
                    body['rules_revision'] = 1
                with self.assertRaises(APIError) as caught:
                    MissionBridge.start_mission(bridge, body)
                self.assertEqual(caught.exception.outcome, 'rejected')
                self.assertEqual(goals, [])
                self.assertEqual(bridge.mission.value['status'], 'idle')

    def test_waypoint_readiness_does_not_require_backup_server(self):
        bridge, _source, _reads, _waypoint, _goals = self.bridge()
        bridge.lifecycle = {'amcl': {'active': True, 'wall': 100.},
                            'behavior_server': {'active': False, 'wall': 0.}}
        bridge.backup_client.server_is_ready = lambda: False
        bridge.mission = MissionRecord()
        with patch('mission_bridge.time.monotonic', return_value=100.):
            self.assertTrue(MissionBridge.evaluate_ready(bridge, 100.)[0])
        bridge.mission.begin([{'x': -.3, 'y': 0., 'yaw': 0.}], False)
        bridge.mission.value['operation'] = 'backup'
        self.assertFalse(MissionBridge.evaluate_ready(bridge, 100.)[0])

    def test_backup_feedback_and_native_terminal_need_no_waypoint_result_fields(self):
        result, cancel = Future(), Future()
        bridge, handle = AcceptedCleanupTests().harness(lambda: result, lambda: cancel)
        original = bridge.mission.value['id']
        bridge.mission.value.update(operation='backup', native_action='/backup')
        MissionBridge.feedback(bridge, original,
            SimpleNamespace(feedback=SimpleNamespace(distance_traveled=.12)))
        self.assertAlmostEqual(bridge.mission.value['distance_traveled_m'], .12)
        with patch('mission_bridge.time.monotonic', return_value=11.):
            bridge.request_cancel('用户请求取消')
        self.assertIs(bridge.goal_handle, handle)
        cancel.set_result(SimpleNamespace(goals_canceling=[object()]))
        result.set_result(SimpleNamespace(status=GoalStatus.STATUS_CANCELED,
            result=SimpleNamespace(error_code=0, error_msg='')))
        self.assertEqual(bridge.mission.value['id'], original)
        self.assertEqual(bridge.mission.value['native_status'], GoalStatus.STATUS_CANCELED)
        self.assertEqual(bridge.mission.value['status'], 'canceled')
        self.assertEqual(bridge.mission.value['message'], 'Nav2 已取消倒车')
        self.assertIsNone(bridge.goal_handle)

    def test_backup_native_error_cannot_be_reported_as_success(self):
        result, cancel = Future(), Future()
        bridge, _handle = AcceptedCleanupTests().harness(lambda: result, lambda: cancel)
        bridge.mission.value['operation'] = 'backup'
        result.set_result(SimpleNamespace(status=GoalStatus.STATUS_SUCCEEDED,
            result=SimpleNamespace(error_code=714, error_msg='collision ahead')))
        self.assertEqual(bridge.mission.value['status'], 'failed')
        self.assertEqual(bridge.mission.value['native_error_code'], 714)
        self.assertEqual(bridge.mission.value['message'], 'collision ahead')


if __name__ == '__main__':
    unittest.main()
