"""Boundary tests; real ROS action/physical acceptance is a separate integration run."""
import copy
import math
import sys
import threading
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from mission_bridge import (APIError, GoalStatus, MissionBridge, MissionRecord,
                            require_free_point, validate_mission)


def fixture_grid():
    return {'width': 40, 'height': 40, 'resolution': 0.1,
            'origin': [-2.0, -2.0, 0.0], 'data': [0]*1600}


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
