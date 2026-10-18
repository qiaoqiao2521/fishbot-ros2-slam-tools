"""Real loopback manual routes and original mission records; no ROS initialization."""
from concurrent.futures import Future
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT/'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from fishbot_manual_lease import ManualLeaseController, TimePoint
from mission_bridge import GoalStatus, LocalHTTPServer, MissionBridge, MissionRecord


def uid():
    return str(uuid.uuid4())


class ManualHTTPTests(unittest.TestCase):
    def setUp(self):
        self.clock = TimePoint(100_000, 100., 10.)
        self.reset_future, self.stop_future = Future(), Future()
        self.publish = Mock()
        self.bridge = SimpleNamespace(domain=129, lock=threading.RLock(), mission=MissionRecord(),
            cancel_sent=False, state=Mock(), enqueue=Mock(), manual_guard_available=lambda: True)
        for name in ('manual_request', 'manual_native_owner', 'manual_idle_guard_fault'):
            setattr(self.bridge, name, MethodType(getattr(MissionBridge, name), self.bridge))
        with patch('mission_bridge.RvizDesktop'):
            self.server = LocalHTTPServer(0, self.bridge, ui_port=5182)
        ports = SimpleNamespace(native_owner=self.bridge.manual_native_owner, guard_available=lambda: True,
            publish_manual=self.publish, nav_lock=Mock(), guard_reset=lambda: self.reset_future,
            guard_stop=lambda: self.stop_future, cancel_native=Mock())
        self.controller = ManualLeaseController(self.server.runtime.instance_id, 'map-a', ports, enabled=True)
        self.bridge.manual_adapter = SimpleNamespace(controller=self.controller, now=lambda: self.clock)
        def enqueue(kind, body):
            future = Future()
            with self.bridge.lock:
                result = self.bridge.manual_request('POST', body['path'], body['body'])
            future.set_result(result)
            return future
        self.bridge.enqueue.side_effect = enqueue
        self.session = uid()
        self.quiet()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def quiet(self):
        for _ in range(9):
            self.controller.observe_truth(self.clock.ros, 0., 0., self.clock)
            self.controller.tick(self.clock)
            self.clock = TimePoint(self.clock.wall_ms+100, self.clock.steady+.1, self.clock.ros+.1)

    def envelope(self, **extra):
        return {'session_id': self.session, 'runtime_instance_id': self.server.runtime.instance_id,
                'map_id': 'map-a', 'profile_id': 'passage_manual', 'sequence': 0,
                'issued_at_ms': self.clock.wall_ms, 'ttl_ms': 1000, **extra}

    def request(self, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.port, timeout=2)
        connection.request('GET' if body is None else 'POST', path,
            body=None if body is None else json.dumps(body),
            headers={'Content-Type': 'application/json', **(headers or {})})
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def test_discovery_and_status_expose_real_owner_limits_and_map(self):
        status, runtime = self.request('/sim-api/runtime')
        self.assertEqual(status, 200)
        cap = next(cap for cap in runtime['capabilities'] if cap['id'] == 'teleop')
        self.assertTrue(cap['available'])
        self.assertEqual(cap['submission'], 'topic_publish')
        self.assertEqual(cap['protocol'], 'manual_lease_v1')
        status, value = self.request('/sim-api/manual/status')
        self.assertTrue(value['can_acquire'])
        self.assertEqual(value['map_id'], 'map-a')
        self.assertEqual(value['limits']['reverse_mps'], .03)
        self.bridge.enqueue.assert_not_called()

    def test_existing_status_get_projects_detached_current_lease_timing_without_dispatch(self):
        self.bridge.control_profile = 'passage_manual'
        lease_id = uid()
        self.assertEqual(self.request('/sim-api/manual/acquire',
            self.envelope(lease_id=lease_id, gesture='press'))[0], 202)
        MissionBridge.record_manual_slow_timing(self.bridge, 'http.manual', 10., 10.27,
                                               context={'stages': [1]})
        self.bridge.enqueue.reset_mock()
        code, value = self.request('/sim-api/manual/status')
        self.assertEqual(code, 200)
        diagnostic = value['timing_diagnostics']
        self.assertEqual(diagnostic['scope_lease_id'], lease_id)
        self.assertEqual(diagnostic['observed_events'], 1)
        self.assertFalse(diagnostic['logging_enabled'])
        diagnostic['events'][0]['context']['stages'][0] = 99
        _, fresh = self.request('/sim-api/manual/status')
        self.assertEqual(fresh['timing_diagnostics']['events'][0]['context']['stages'], [1])
        self.assertEqual(fresh['active_lease_id'], lease_id)
        self.bridge.enqueue.assert_not_called()

    def test_real_owner_initializes_before_map_and_binds_actual_map_later(self):
        self.bridge.control_profile = 'passage_manual'
        self.bridge.rules_store = SimpleNamespace(map_id='')
        self.bridge.manual_cancel_native = Mock()
        def attach(node, instance, map_id, **kwargs):
            controller = ManualLeaseController(instance, map_id, self.controller.ports, enabled=True)
            return SimpleNamespace(controller=controller, now=lambda: self.clock)
        with patch('mission_bridge.attach_manual', side_effect=attach):
            MissionBridge.initialize_manual(self.bridge)
        self.assertIsNone(self.bridge.manual_adapter.controller.map_id)
        code, value = self.request('/sim-api/manual/status')
        self.assertEqual((code, value['error']), (503, 'manual_map_unavailable'))
        self.bridge.manual_adapter.controller.bind_map('actual-map', self.clock)
        code, value = self.request('/sim-api/manual/status')
        self.assertEqual((code, value['map_id']), (200, 'actual-map'))
        self.assertFalse(value['can_acquire'])

    def test_idle_incident_reader_requires_current_latch_local_file_and_fresh_sensors(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = directory/'trigger-zero.json'
            path.write_text(json.dumps({'steady_time': time.monotonic()}))
            self.bridge.manual_guard_directory = directory
            self.bridge.get_clock = lambda: SimpleNamespace(now=lambda:
                SimpleNamespace(nanoseconds=round(self.clock.ros*1e9)))
            seconds = int(self.clock.ros)
            status = SimpleNamespace(name='fishbot_command_guard', message='latched: odom: receive timeout',
                values=[SimpleNamespace(key=key, value=value) for key, value in {
                    'last_trigger': str(path), 'execute': 'True', 'profile': 'fishbot_passage',
                    'timing_profile': 'strict'}.items()])
            message = SimpleNamespace(status=[status], header=SimpleNamespace(stamp=SimpleNamespace(
                sec=seconds, nanosec=round((self.clock.ros-seconds)*1e9))))
            self.bridge.manual_guard = (time.monotonic(), message)
            self.bridge.samples = {name: (self.clock.ros, time.monotonic())
                                   for name in ('clock', 'scan', 'odom', 'truth')}
            with patch('mission_bridge.idle_timing_evidence', return_value=True) as validate:
                value = self.bridge.manual_idle_guard_fault()
                self.assertTrue(value['eligible'])
                validate.assert_called_once()
                self.assertEqual(value['trigger_id'], str(path))
                self.bridge.samples['odom'] = (self.clock.ros, time.monotonic()-.251)
                self.assertFalse(self.bridge.manual_idle_guard_fault()['eligible'])
                status.message = 'healthy'
                self.assertIsNone(self.bridge.manual_idle_guard_fault())
                status.message = 'latched: odom: receive timeout'
                status.values[0].value = str(directory/'outside'/'trigger-zero.json')
                self.assertFalse(self.bridge.manual_idle_guard_fault()['eligible'])
                status.values[0].value = str(path)
                path.write_text('[]')
                self.bridge.manual_guard_trigger_cache = None
                self.assertFalse(self.bridge.manual_idle_guard_fault()['eligible'])

    def test_actual_http_acquire_original_lookup_arming_rejection_and_fresh_command(self):
        lease_id = uid()
        body = self.envelope(lease_id=lease_id, gesture='press')
        code, value = self.request('/sim-api/manual/acquire', body)
        self.assertEqual((code, value['accepted'], value['lease']['state']), (202, True, 'arming'))
        self.bridge.enqueue.assert_called_with('manual', {'path': '/sim-api/manual/acquire', 'body': body})
        command = self.envelope(lease_id=lease_id, sequence=1, ttl_ms=250, linear_x=.05, angular_z=0.)
        self.assertEqual(self.request('/sim-api/manual/command', command)[1]['error'], 'manual_lease_not_ready')
        self.reset_future.set_result(SimpleNamespace(success=True))
        self.controller.tick(self.clock)
        code, value = self.request('/sim-api/manual/command', command)
        self.assertEqual((code, value['accepted'], value['lease']['state']), (200, True, 'active'))
        self.assertEqual(self.publish.call_args.args[:2], (.05, 0.))
        self.assertEqual(self.request('/sim-api/manual/command', command)[1]['error'], 'stale_sequence')
        self.assertEqual(self.request('/sim-api/manual/'+lease_id)[1]['lease']['lease_id'], lease_id)
        self.assertEqual(self.request('/sim-api/manual/'+uid())[0], 404)

    def test_runtime_header_fence_precedes_queue_and_cannot_be_retimestamped(self):
        body = self.envelope(lease_id=uid(), gesture='press')
        code, value = self.request('/sim-api/manual/acquire', body, {'X-Fishbot-Instance': uid()})
        self.assertEqual(code, 409)
        self.assertIs(value['accepted'], False)
        self.bridge.enqueue.assert_not_called()
        body['issued_at_ms'] -= 1000
        code, value = self.request('/sim-api/manual/acquire', body)
        self.assertEqual((code, value['error']), (408, 'manual_request_expired'))
        self.assertFalse(self.controller.leases)

    def test_real_mission_finish_can_be_followed_by_manual_after_new_quiet(self):
        task = uid()
        self.bridge.mission.begin([{'x': .2, 'y': .1, 'yaw': 0.}], False, mission_id=task)
        self.controller.tick(self.clock)
        self.bridge.mission.finish(GoalStatus.STATUS_SUCCEEDED, 0, [])
        self.assertEqual(self.bridge.mission.value['status'], 'succeeded')
        self.assertFalse(self.controller.status(self.clock)['can_acquire'])
        self.quiet()
        self.assertTrue(self.controller.status(self.clock)['can_acquire'])
        self.assertEqual(self.request('/sim-api/manual/acquire', self.envelope(lease_id=uid(), gesture='press'))[0], 202)
        self.bridge.mission.value['status'] = 'completed'
        self.assertEqual(self.bridge.manual_native_owner()['status'], 'succeeded')

    def test_normal_lease_expiry_can_rearm_but_ownership_and_scan_hard_latches_require_reset(self):
        values = [SimpleNamespace(key='execute', value='true'),
                  SimpleNamespace(key='profile', value='fishbot_passage')]
        status = SimpleNamespace(name='fishbot_command_guard', values=values, message='healthy')
        self.bridge.manual_guard = (time.monotonic(), SimpleNamespace(
            header=SimpleNamespace(stamp=SimpleNamespace(sec=10, nanosec=0)), status=[status]))
        self.bridge.get_clock = lambda: SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=10_000_000_000))
        self.controller.current_lease = {'state': 'expired', 'guard_stop_acknowledged': True}
        for message, expected in [
                ('latched: command: source stamp too old', True),
                ('latched: candidate publisher ownership mismatch', False),
                ('latched: scan: receive timeout', False), ('latched: recorder failure', False)]:
            status.message = message
            self.assertEqual(MissionBridge.manual_guard_available(self.bridge), expected)


if __name__ == '__main__':
    unittest.main()
