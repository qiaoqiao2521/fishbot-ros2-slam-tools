"""Decision boundaries of the feedback-driven mission; no ROS graph is needed."""
from pathlib import Path
import copy
import sys
import time
import types
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))


class MissionBoundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import fishbot_home_mission
        cls.m = fishbot_home_mission

    def test_real_or_remote_discovery_is_refused(self):
        healthy = dict(ROS_DOMAIN_ID='98', FISHBOT_MUJOCO_DOMAIN_ID='98',
                       ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST', ROS_STATIC_PEERS='')
        self.m.validate_environment(healthy)
        for key, value in [('ROS_DOMAIN_ID', '0'), ('FISHBOT_MUJOCO_DOMAIN_ID', '0'),
                           ('ROS_AUTOMATIC_DISCOVERY_RANGE', 'SUBNET'), ('ROS_STATIC_PEERS', 'host')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.m.validate_environment({**healthy, key: value})

    def test_one_positive_frame_cannot_override_unknown(self):
        green = dict(outcome='found', state='green', reason='pixels')
        unknown = dict(outcome='unknown', state='unknown', reason='occluded')
        self.assertEqual(self.m.combined_observation([green, unknown, unknown])['outcome'], 'unknown')
        self.assertEqual(self.m.combined_observation([green] * 3)['state'], 'green')

    def test_dock_result_or_soc_alone_does_not_prove_charging(self):
        battery = types.SimpleNamespace(percentage=.85, current=2., power_supply_status=1,
                                        POWER_SUPPLY_STATUS_CHARGING=1)
        healthy = dict(contact=True, charging=True, truth_fresh=True, clock_fresh=True)
        self.assertTrue(self.m.charge_feedback_ok(battery, healthy, .8))
        for status in ({}, dict(contact=False, charging=True), dict(contact=True, charging=False)):
            self.assertFalse(self.m.charge_feedback_ok(battery, status, .8))
        battery.current = -.2
        self.assertFalse(self.m.charge_feedback_ok(battery, healthy, .8))

    def test_completed_route_without_charge_is_not_complete_scenario(self):
        report = {'steps': [{'completed': True, 'observations': [{'outcome': 'found'}]}],
                  'return_home': {'completed': True}, 'final_stationary': {'verified': True}}
        checks = self.m.closed_loop_checks(report)
        self.assertTrue(checks['inspection_completed'])
        self.assertFalse(checks['charging_and_undocking'])
        self.assertFalse(checks['active_observation'])

    def test_empty_observations_are_a_failed_boundary_not_an_index_error(self):
        self.assertFalse(self.m.closed_loop_checks({'steps': [{'observations': []}]})['active_observation'])

    def test_invalid_battery_cannot_poison_failure_report(self):
        import json
        mission = self.m.HomeMission.__new__(self.m.HomeMission)
        mission.samples = {}
        mission.report = {'battery_history': []}
        message = types.SimpleNamespace(header=types.SimpleNamespace(stamp=types.SimpleNamespace(sec=1, nanosec=0)),
                                        percentage=float('nan'), current=2., power_supply_status=1)
        mission.remember('battery', message)
        self.assertEqual(mission.report['battery_history'], [])
        json.dumps(mission.report, allow_nan=False)

    def test_failure_stops_before_diagnostic_io(self):
        mission = self.m.HomeMission.__new__(self.m.HomeMission)
        order = []
        mission.report, mission.interrupts, mission.pending = {}, [], object()
        mission.ready = lambda: (_ for _ in ()).throw(RuntimeError('lost feedback'))
        mission.event = lambda *a, **kw: None
        mission.cancel = lambda **kw: order.append('cancel')
        mission.stationary = lambda *a, **kw: order.append('stop') or {'verified': True}
        mission.save_diagnostics = lambda: order.append('diagnostics')
        mission.persist = lambda: order.append('persist')
        mission.node = types.SimpleNamespace(destroy_node=lambda: order.append('destroy'))
        self.assertFalse(mission.run())
        self.assertEqual(order, ['cancel', 'stop', 'diagnostics', 'persist', 'destroy'])

    def empty_mission(self):
        mission = self.m.HomeMission.__new__(self.m.HomeMission)
        mission.sample = lambda name: (types.SimpleNamespace(percentage=0.), 0., 0.)
        mission.pending = None
        mission.interrupts = []
        mission.node = object()
        mission.rclpy = types.SimpleNamespace(spin_once=lambda *a, **kw: None)
        return mission

    def test_empty_battery_blocks_return_home_dock_and_undock_before_send(self):
        for kind in ('navigate', 'dock', 'undock'):
            mission = self.empty_mission()
            # No clients are installed: the guard must run before any send attempt.
            with self.subTest(kind=kind), self.assertRaises(self.m.BatteryDepleted):
                mission.action(kind, object(), {}, 1, monitor_battery=False)
            self.assertIsNone(mission.pending)

    def test_empty_battery_precedes_completed_predicate_even_without_low_monitor(self):
        mission = self.empty_mission()
        called = []
        with self.assertRaises(self.m.BatteryDepleted):
            mission.spin(time.monotonic()+1, lambda: called.append(True) or True,
                         health=True, monitor_battery=False)
        self.assertEqual(called, [])

    def test_empty_battery_does_not_interrupt_cleanup(self):
        mission = self.empty_mission()
        mission.spin(time.monotonic()+1, lambda: True, health=True, cleanup=True)

    def resumed_fixture(self):
        target = {'step_id': 'step1', 'place_id': 'shelf', 'view_index': 0}
        attempt = {'view_index': 0, 'started_stamp': 11., 'completed_stamp': 12.,
                   'action': {'goal_accepted': True, 'status': 4, 'error_code': 0},
                   'goal': [1., 2., 0.], 'pose': [1., 2., 0.],
                   'physical_error': {'xy_m': 0., 'yaw_rad': 0.},
                   'stationary': {'stamp': 11.9, 'verified': True, 'samples': 6,
                                  'duration_s': .6, 'pose': [1., 2., 0.]}}
        step = {'step_id': 'step1', 'place_id': 'shelf', 'views': [[1., 2., 0.]],
                'navigation_attempts': [attempt]}
        cycle = {'cycle_index': 0, 'resume_target': target, 'charging_verified': True,
                 'undocked': True, 'undocked_stationary': {'stamp': 10.}}
        mission = self.m.HomeMission.__new__(self.m.HomeMission)
        mission.resume_pending = 0
        mission.report = {'steps': [step], 'recharge_cycles': [cycle],
                          'events': [{'event': 'task_resume_ready'}]}
        mission.event = lambda name, **kw: mission.report['events'].append({'event': name, **kw})
        return mission, step, cycle, attempt

    def test_resume_requires_successful_linked_postcharge_navigation(self):
        mission, step, cycle, attempt = self.resumed_fixture()
        mission.report['events'].append({'event': 'task_resumed'})
        self.assertFalse(self.m.closed_loop_checks(mission.report)['resumed_task'])
        mission.record_resumed_navigation(step, 0, attempt, 0)
        self.assertTrue(self.m.closed_loop_checks(mission.report)['resumed_task'])
        self.assertIsNone(mission.resume_pending)
        self.assertEqual(mission.report['events'][-1]['pose'], attempt['pose'])
        for field, value in [('started_stamp', 9.), ('completed_stamp', 11.),
                             ('action', {'goal_accepted': True, 'status': 6, 'error_code': 106}),
                             ('pose', [3., 2., 0.])]:
            damaged = copy.deepcopy(mission.report)
            actual = damaged['steps'][0]['navigation_attempts'][0]
            actual[field] = value
            damaged['recharge_cycles'][0]['resumed_navigation'][field] = value
            with self.subTest(field=field):
                self.assertFalse(self.m.closed_loop_checks(damaged)['resumed_task'])
        cycle['resumed_navigation']['attempt_index'] = 9
        self.assertFalse(self.m.closed_loop_checks(mission.report)['resumed_task'])


if __name__ == '__main__':
    unittest.main()
