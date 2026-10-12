"""Boundary tests; real ROS action/physical acceptance is a separate integration run."""
import copy
import math
import queue
import sys
import threading
import time
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import patch
from rclpy.task import Future as ROSFuture

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from mission_bridge import (APIError, GoalStatus, MissionBridge, MissionRecord,
                            Handler, require_free_point, simulation_domain, validate_mission)


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


class GoalBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.grid = fixture_grid()
        self.body = {'waypoints': [{'x': 1.0, 'y': 1.0, 'yaw': 0.0}],
                     'return_home': True, 'issued_at': 100.0}

    def test_home_is_an_actual_last_waypoint(self):
        points, returning = validate_mission(self.body, self.grid, now=100)
        self.assertTrue(returning)
        self.assertEqual(points[-1], {'x': 0.0, 'y': 0.0, 'yaw': 0.0})
        self.assertEqual(len(points), 2)

    def test_sender_timestamp_rejects_delayed_and_future_goals(self):
        for timestamp in (96.9, 101.1):
            with self.subTest(timestamp=timestamp):
                body = copy.deepcopy(self.body)
                body['issued_at'] = timestamp
                with self.assertRaises(APIError) as caught:
                    validate_mission(body, self.grid, now=100)
                self.assertEqual(caught.exception.status, 408)

    def test_nonfinite_and_boolean_coordinates_are_not_goals(self):
        for value in (math.nan, math.inf, -math.inf, True, '1'):
            with self.subTest(value=value):
                body = copy.deepcopy(self.body)
                body['waypoints'][0]['x'] = value
                with self.assertRaises(APIError):
                    validate_mission(body, self.grid, now=100)

    def test_missing_timestamp_or_coordinates_rejected(self):
        for field in ('issued_at', 'x', 'y'):
            with self.subTest(field=field):
                body = copy.deepcopy(self.body)
                if field == 'issued_at':
                    del body[field]
                else:
                    del body['waypoints'][0][field]
                with self.assertRaises(APIError):
                    validate_mission(body, self.grid, now=100)

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

    def test_twelve_user_points_can_append_home_as_thirteenth(self):
        self.body['waypoints'] *= 12
        points, returning = validate_mission(self.body, self.grid, now=100)
        self.assertTrue(returning)
        self.assertEqual(len(points), 13)
        self.assertEqual(points[-1], {'x': 0.0, 'y': 0.0, 'yaw': 0.0})

    def test_thirteen_user_points_are_rejected(self):
        self.body['waypoints'] *= 13
        with self.assertRaises(APIError):
            validate_mission(self.body, self.grid, now=100)


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
        bridge.get_clock = lambda: SimpleNamespace(now=lambda: SimpleNamespace(to_msg=Time))
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


if __name__ == '__main__':
    unittest.main()
