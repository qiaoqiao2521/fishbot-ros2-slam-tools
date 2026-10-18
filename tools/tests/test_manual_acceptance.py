"""B07 declarations and evidence boundaries only; never initialize ROS or move."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import subprocess
import threading
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fishbot_manual_acceptance as acceptance


def frames(direction='forward'):
    values = []
    for index in range(14):
        progress = min(index, 4)/4
        x = .06*progress if direction == 'forward' else -.03*progress if direction == 'backward' else 0.
        yaw = .3*progress if direction == 'left' else -.3*progress if direction == 'right' else 0.
        values.append({'epoch': 100+index*.1, 'steady_time': 100+index*.1, 'stamp': 10+index*.1,
            'ros_now': 10+index*.1+.01, 'x': x, 'y': 0., 'yaw': yaw,
            'linear_speed': .04 if index < 4 and direction in ('forward', 'backward') else 0.,
            'angular_speed': .2 if index < 4 and direction in ('left', 'right') else 0.})
    return values


class ManualAcceptanceTests(unittest.TestCase):
    def admission_fixture(self):
        clock = [0.]
        run = acceptance.Acceptance(SimpleNamespace(api='http://127.0.0.1:9097', expected_instance='instance'),
            Path('/unused'), Mock(), Mock(), started=0.)
        run.map_id = 'map'; run.api = Mock()
        status = {'runtime_instance_id': 'instance', 'map_id': 'map', 'profile_id': acceptance.PROFILE,
            'limits': acceptance.LIMITS, 'available': True, 'can_acquire': False,
            'reason': 'continuous_quiet_unconfirmed', 'stop_latched': False,
            'active_lease_id': None, 'native_owner': {'terminal': True, 'task_id': None, 'native_goal_id': None}}
        return run, clock, status

    def test_delayed_admission_reads_only_then_sends_one_fresh_acquire(self):
        run, clock, status = self.admission_fixture()
        status_reads, accepted = [], []
        def get(path):
            if path == 'manual/status':
                status_reads.append(clock[0])
                return {**status, 'can_acquire': clock[0] >= .1,
                    'reason': None if clock[0] >= .1 else 'continuous_quiet_unconfirmed'}
            self.assertEqual(path, 'manual/'+accepted[0]['lease_id'])
            return {'lease': {**accepted[0], 'last_sequence': 0, 'state': 'ready',
                              'guard_reset_acknowledged': True}}
        def submit(path, body):
            self.assertEqual(path, 'manual/acquire'); self.assertGreaterEqual(clock[0], .1)
            accepted.append(body)
            return {'lease': {**body, 'last_sequence': 0, 'state': 'arming'}}
        run.api.get.side_effect = get; run.api.accepted.side_effect = submit
        def sleep(seconds): clock[0] += seconds
        with patch.object(acceptance.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(acceptance.time, 'time_ns', side_effect=lambda: int((100+clock[0])*1e9)), \
                patch.object(acceptance.time, 'sleep', side_effect=sleep):
            self.assertEqual(run.acquire()['state'], 'ready')
        self.assertEqual(status_reads, [0., .05, .1])
        run.api.accepted.assert_called_once(); run.api.call.assert_not_called()
        self.assertEqual(accepted[0]['issued_at_ms'], 100100)
        self.assertEqual(accepted[0]['sequence'], 0)
        self.assertEqual(accepted[0]['ttl_ms'], acceptance.LIMITS['acquire_ttl_ms'])
        self.assertEqual(run.deadline, 440.)

    def test_admission_timeout_uses_existing_deadline_without_any_mutation(self):
        for active_deadline in (.12, 440.):
            with self.subTest(active_deadline=active_deadline):
                run, clock, status = self.admission_fixture(); run.deadline = active_deadline
                reads = []
                def get(path):
                    self.assertEqual(path, 'manual/status'); reads.append(clock[0]); return status
                run.api.get.side_effect = get
                def sleep(seconds): clock[0] += seconds
                with patch.object(acceptance.time, 'monotonic', side_effect=lambda: clock[0]), \
                        patch.object(acceptance.time, 'sleep', side_effect=sleep):
                    with self.assertRaisesRegex(TimeoutError, 'Declared acceptance deadline'):
                        run.acquire()
                self.assertTrue(all(at < min(active_deadline, 15.) for at in reads))
                self.assertLessEqual(clock[0], min(active_deadline, 15.)+.05)
                self.assertEqual(run.deadline, active_deadline); self.assertIsNone(run.lease)
                run.api.accepted.assert_not_called(); run.api.call.assert_not_called()

    def test_fatal_admission_identity_owner_and_stop_changes_fail_without_waiting(self):
        changes = [{'runtime_instance_id': 'different'}, {'map_id': 'different'},
            {'profile_id': 'different'}, {'limits': {}}, {'stop_latched': True},
            {'active_lease_id': 'different'}, {'available': False},
            {'native_owner': {'terminal': False, 'task_id': None, 'native_goal_id': None}},
            {'native_owner': {'terminal': True, 'task_id': 'different', 'native_goal_id': None}},
            {'native_owner': {'terminal': True, 'task_id': None, 'native_goal_id': 'different'}},
            {'idle_recovery': {'state': 'unknown'}}, {'reason': 'guard_unavailable'}]
        for change in changes:
            with self.subTest(change=change):
                run, _, status = self.admission_fixture(); run.api.get.return_value = {**status, **change}
                with patch.object(acceptance.time, 'monotonic', return_value=0.), \
                        patch.object(acceptance.time, 'sleep') as sleep:
                    with self.assertRaises(RuntimeError): run.acquire()
                run.api.get.assert_called_once_with('manual/status')
                run.api.accepted.assert_not_called(); run.api.call.assert_not_called(); sleep.assert_not_called()

    def test_default_is_plan_only_and_includes_bounded_ui_and_explicit_unrun_faults(self):
        with patch.object(acceptance, 'RuntimeObservation') as observer, patch.object(acceptance, 'Acceptance') as runtime, patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(acceptance.main([]), 0)
            plan = json.loads(output.getvalue())
        observer.assert_not_called(); runtime.assert_not_called()
        self.assertFalse(plan['execute_by_default']); self.assertEqual(len(plan['cases']), 8)
        self.assertIn('actual_ui_forward_release', plan['cases'])
        self.assertEqual(plan['budget']['native_missions'], 1)
        self.assertEqual(plan['budget']['wall_s'], 480)
        self.assertEqual({item['case'] for item in plan['not_run']}, {'scan_loss', 'rogue_final_publisher'})

    def test_four_directions_need_independent_signed_motion_and_dual_clock_quiet(self):
        for direction in acceptance.VECTORS:
            with self.subTest(direction=direction):
                result = acceptance.score_direction(direction, frames(direction))
                self.assertGreaterEqual(result['quiet_source_s'], .7)
                self.assertGreaterEqual(result['quiet_wall_s'], .7)
                with self.assertRaises(RuntimeError): acceptance.score_direction(direction, frames('right' if direction == 'left' else 'left' if direction == 'right' else 'backward' if direction == 'forward' else 'forward'))

    def test_wrong_heading_lateral_motion_and_missing_stop_never_pass(self):
        for kind in ('yaw', 'sideways', 'moving_tail'):
            sample = frames()
            if kind == 'yaw': sample[-1]['yaw'] = .09
            elif kind == 'sideways': sample[-1]['y'] = .03
            else: sample[-2]['linear_speed'] = .1
            with self.subTest(kind=kind), self.assertRaises(RuntimeError): acceptance.score_direction('forward', sample)

    def test_source_and_receive_gaps_and_ages_are_not_relaxed(self):
        for kind in ('source_gap', 'wall_gap', 'old', 'duplicate'):
            sample = frames()
            if kind == 'source_gap': sample[6]['stamp'] += .31
            if kind == 'wall_gap': sample[6]['steady_time'] += .31
            if kind == 'old': sample[6]['ros_now'] += .3
            if kind == 'duplicate': sample[6]['stamp'] = sample[5]['stamp']
            with self.subTest(kind=kind), self.assertRaises(RuntimeError): acceptance.quiet_result(sample)

    def test_fresh_boundary_is_required_before_each_phase(self):
        sample = frames()
        self.assertEqual(acceptance.boundary_frames(sample, 100.05)[0], sample[0])
        with self.assertRaises(RuntimeError): acceptance.boundary_frames(sample, 99.9)
        with self.assertRaises(RuntimeError): acceptance.boundary_frames(sample[:1], 100.3)

    def test_drive_includes_slow_ack_in_monotonic_heartbeat_without_catchup(self):
        for ack in (.08, .10, .20):
            with self.subTest(ack=ack), tempfile.TemporaryDirectory() as temp:
                clock, sent = [0.], []
                observer = Mock(); observer.fresh.side_effect = lambda: {'stamp': clock[0]}
                run = acceptance.Acceptance(SimpleNamespace(api='http://127.0.0.1:9097', expected_instance='instance'), Path(temp), Mock(), observer, started=0.)
                def command(vector):
                    sent.append(clock[0]); clock[0] += ack
                    return {'sequence': len(sent), 'issued_at_ms': int(clock[0]*1000)}
                run.command = command
                def sleep(seconds): clock[0] += seconds
                with patch.object(acceptance.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(acceptance.time, 'sleep', side_effect=sleep):
                    run.drive((.08, 0.), .59)
                self.assertGreaterEqual(len(sent), 3)
                for before, after in zip(sent, sent[1:]): self.assertAlmostEqual(after-before, max(.14, ack))

    def test_drive_stops_after_expired_ack_without_renewal(self):
        clock = [0.]; observer = Mock(); observer.fresh.side_effect = lambda: {'stamp': clock[0]}
        run = acceptance.Acceptance(SimpleNamespace(api='http://127.0.0.1:9097', expected_instance='instance'), Path('/unused'), Mock(), observer, started=0.)
        def command(vector): clock[0] += .3; return {'sequence': 1}
        run.command = Mock(side_effect=command)
        with patch.object(acceptance.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(acceptance.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'TTL budget'): run.drive((.08, 0.))
        self.assertEqual(run.command.call_count, 1); sleep.assert_not_called()

    def test_get_accepts_earlier_server_sequence_but_post_ack_must_match_sent_sequence(self):
        identity = {'lease_id': 'lease', 'session_id': 'session', 'runtime_instance_id': 'runtime', 'map_id': 'map', 'profile_id': acceptance.PROFILE}
        original = {**identity, 'last_sequence': 0, 'state': 'expired'}
        self.assertEqual(acceptance.original_lease(original, identity)['last_sequence'], 0)
        with self.assertRaises(RuntimeError): acceptance.original_lease(original, identity, accepted_sequence=1)
        with self.assertRaises(RuntimeError): acceptance.original_lease({**original, 'lease_id': 'other'}, identity)
        with self.assertRaises(RuntimeError): acceptance.original_lease({**original, 'last_sequence': -1}, identity)

    def test_native_cancel_requires_exact_uuid_and_original_task_and_guard_quiet(self):
        mission = {'id': 'task', 'native_goal_id': 'native', 'status': 'canceled', 'native_status': 5, 'cleanup_state': None}
        stop = {'target_id': 'task', 'state': 'stopped', 'native_terminal': True, 'guard_stop_acknowledged': True, 'quiet': {'confirmed': True}}
        self.assertTrue(acceptance.native_stop_complete(mission, stop, {'native': 5}, 'task', 'native'))
        for change in ({'id': 'other'}, {'native_goal_id': 'other'}, {'native_status': 4}, {'status': 'unknown'}, {'cleanup_state': 'unresolved'}):
            self.assertFalse(acceptance.native_stop_complete({**mission, **change}, stop, {'native': 5}, 'task', 'native'))
        for change in ({'target_id': 'other'}, {'native_terminal': False}, {'guard_stop_acknowledged': None}, {'quiet': {'confirmed': False}}):
            self.assertFalse(acceptance.native_stop_complete(mission, {**stop, **change}, {'native': 5}, 'task', 'native'))
        self.assertFalse(acceptance.native_stop_complete(mission, stop, {'other': 5}, 'task', 'native'))

    def test_loopback_boundary_excludes_remote_credentials_and_paths(self):
        self.assertEqual(acceptance.require_loopback('http://127.0.0.1:9097'), 'http://127.0.0.1:9097')
        for address in ('http://localhost:9097', 'http://127.0.0.1:9097/', 'http://u:p@127.0.0.1:9097', 'http://127.0.0.1:9097?x=1', 'https://example.com'):
            with self.subTest(address=address), self.assertRaises(ValueError): acceptance.require_loopback(address)

    def test_recording_handles_ros_bytes_without_silent_failure_and_is_private(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp); log = acceptance.Recording(output)
            log.emit('guard', {'level': bytes([2]), 'sequence': 7}); log.close()
            self.assertIsNone(log.error)
            record = json.loads((output/'observations.jsonl').read_text())
            self.assertEqual(record['payload'], {'level': [2], 'sequence': 7})
            self.assertEqual((output/'observations.jsonl').stat().st_mode & 0o777, 0o600)

    def test_post_transport_error_is_logged_once_without_automatic_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            log = acceptance.Recording(Path(temp)); api = acceptance.Api('http://127.0.0.1:9097', 'instance', log)
            with patch.object(acceptance, 'urlopen', side_effect=TimeoutError('network')) as transport:
                with self.assertRaisesRegex(RuntimeError, 'outcome unknown'): api.accepted('manual/command', {'sequence': 1})
                self.assertEqual(transport.call_count, 1)
            log.close(); records = [json.loads(v) for v in (Path(temp)/'observations.jsonl').read_text().splitlines()]
            self.assertEqual([v['topic'] for v in records], ['http_intent', 'http_unknown'])

    def test_network_boundaries_separate_log_delay_and_preserve_original_command_age(self):
        clock, records = [100.], []
        body = {'session_id': 'original-session', 'sequence': 6,
                'issued_at_ms': 12345, 'ttl_ms': 250, 'linear_x': .08}
        original = copy.deepcopy(body)
        def emit(topic, payload):
            records.append((topic, copy.deepcopy(payload)))
            clock[0] += .300 if topic == 'http_intent' else .075
        api = acceptance.Api('http://127.0.0.1:9097', 'instance', SimpleNamespace(emit=emit))
        class Response(io.BytesIO):
            status = 200
            headers = {'X-Fishbot-Instance': 'instance'}
            def read(self, *args):
                clock[0] += .020
                return super().read(*args)
        def transport(request, timeout):
            self.assertEqual(clock[0], 100.300)
            self.assertEqual(json.loads(request.data), original)
            self.assertEqual(timeout, 2)
            clock[0] += .015
            return Response(b'{"accepted":true}')
        with patch.object(acceptance.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(acceptance.time, 'time', side_effect=lambda: 1000+clock[0]), \
                patch.object(acceptance, 'urlopen', side_effect=transport) as network:
            self.assertEqual(api.call('manual/command', body), (200, {'accepted': True}))
        self.assertEqual(body, original); network.assert_called_once()
        timing = api.posts[0]['network_timing']
        self.assertIs(timing, api.request_timings[0])
        self.assertEqual(timing['session_id'], body['session_id'])
        self.assertEqual(timing['issued_at_ms'], original['issued_at_ms'])
        for name, expected in [('before_intent_log', 100.), ('after_intent_log', 100.300),
                ('before_urlopen', 100.300), ('after_headers', 100.315),
                ('after_body', 100.335), ('after_log', 100.410)]:
            self.assertAlmostEqual(timing[name]['steady_time'], expected)
            self.assertAlmostEqual(timing[name]['epoch'], expected+1000)
        self.assertEqual([topic for topic, _ in records], ['http_intent', 'http_receipt'])
        receipt = records[-1][1]['network_timing']
        self.assertIsNone(receipt['after_log'])  # Future completion belongs in the final report.
        self.assertAlmostEqual(receipt['before_urlopen']['steady_time'], 100.300)

    def test_failed_network_and_body_read_keep_reached_boundaries_without_retry(self):
        for failure in ('network', 'body'):
            with self.subTest(failure=failure):
                clock, records = [10.], []
                def emit(topic, payload):
                    records.append((topic, copy.deepcopy(payload)))
                    clock[0] += .010
                api = acceptance.Api('http://127.0.0.1:9097', 'instance', SimpleNamespace(emit=emit))
                def transport(request, timeout):
                    clock[0] += .020
                    if failure == 'network': raise TimeoutError('network timeout')
                    response = io.BytesIO(b'not-json')
                    response.status = 200
                    response.headers = {'X-Fishbot-Instance': 'instance'}
                    return response
                with patch.object(acceptance.time, 'monotonic', side_effect=lambda: clock[0]), \
                        patch.object(acceptance.time, 'time', side_effect=lambda: 1000+clock[0]), \
                        patch.object(acceptance, 'urlopen', side_effect=transport) as network:
                    with self.assertRaisesRegex(RuntimeError, 'outcome unknown'):
                        api.call('manual/command', {'sequence': 1, 'issued_at_ms': 42, 'ttl_ms': 250})
                network.assert_called_once()
                timing = api.posts[0]['network_timing']
                self.assertAlmostEqual(timing['before_urlopen']['steady_time'], 10.010)
                self.assertIsNone(timing['after_body'])
                if failure == 'network': self.assertIsNone(timing['after_headers'])
                else: self.assertAlmostEqual(timing['after_headers']['steady_time'], 10.030)
                self.assertAlmostEqual(timing['after_log']['steady_time'], 10.040)
                self.assertEqual(timing['log_event'], 'http_unknown')
                self.assertEqual([topic for topic, _ in records], ['http_intent', 'http_unknown'])
                self.assertIsNone(records[-1][1]['network_timing']['after_log'])

    def test_request_timing_ring_is_bounded_and_discloses_dropped_entries(self):
        api = acceptance.Api('http://127.0.0.1:9097', 'instance', Mock())
        self.assertEqual(api.request_timings.maxlen, 2048)
        api.request_timings = acceptance.deque(maxlen=2)
        def response(*args, **kwargs):
            value = io.BytesIO(b'{}'); value.status = 200
            value.headers = {'X-Fishbot-Instance': 'instance'}
            return value
        with patch.object(acceptance, 'urlopen', side_effect=response) as network:
            for index in range(3): api.get('read-'+str(index))
        self.assertEqual(network.call_count, 3)
        self.assertEqual([item['path'] for item in api.request_timings], ['read-1', 'read-2'])
        self.assertEqual(api.request_timing_dropped, 1)
        self.assertEqual(api.posts, [])

    def test_http_rejection_is_not_misclassified_as_an_unknown_transport(self):
        with tempfile.TemporaryDirectory()as temp:
            log = acceptance.Recording(Path(temp)); api = acceptance.Api('http://127.0.0.1:9097', 'instance', log)
            reply = HTTPError('http://127.0.0.1:9097', 409, 'conflict', {'X-Fishbot-Instance': 'instance'},
                io.BytesIO(json.dumps({'accepted': False, 'outcome': 'rejected', 'error': 'stale_sequence'}).encode()))
            with patch.object(acceptance, 'urlopen', side_effect=reply):
                self.assertEqual(api.rejected('manual/command', {'sequence': 1}, 'stale_sequence')['http_status'], 409)
            log.close()

    def test_unknown_mission_is_not_resolved_by_an_idle_snapshot_or_reissued(self):
        with tempfile.TemporaryDirectory()as temp:
            output = Path(temp); log = acceptance.Recording(output)
            run = acceptance.Acceptance(SimpleNamespace(api='http://127.0.0.1:9097', expected_instance='instance'), output, log, Mock())
            run.native_task = 'original'; run.native_submission = 'unknown'; run.api = Mock()
            run.api.get.return_value = {'mission': {'id': None, 'status': 'idle'}}
            run.status = lambda: {'active_lease_id': None, 'native_owner': {'terminal': True}}
            result = run.cleanup(); log.close()
            self.assertFalse(result['passed']); self.assertIn('submission remains unknown', result['error'])
            run.api.accepted.assert_not_called()

    def test_cleanup_does_not_take_over_a_different_lease(self):
        with tempfile.TemporaryDirectory()as temp:
            output = Path(temp); log = acceptance.Recording(output)
            run = acceptance.Acceptance(SimpleNamespace(api='http://127.0.0.1:9097', expected_instance='instance'), output, log, Mock())
            run.lease = {'lease_id': 'original'}; run.api = Mock(); run.api.get.return_value = {'mission': {'id': None, 'status': 'idle'}}
            run.status = lambda: {'active_lease_id': 'different', 'native_owner': {'terminal': True}}
            result = run.cleanup(); log.close()
            self.assertFalse(result['passed']); self.assertIn('different active manual owner', result['error'])
            run.api.accepted.assert_not_called()

    def test_runtime_input_snapshot_binds_domain_profile_and_all_selected_files(self):
        with tempfile.TemporaryDirectory()as temp:
            root = Path(temp); params = root/'params.yaml'; params.write_text('selected: true\n')
            manifest = root/'manual-profile.json'; manifest.write_text(json.dumps({'domain': 129, 'profile_id': acceptance.PROFILE, 'paths': {'parameters': str(params)}}))
            first = acceptance.input_snapshot(manifest); params.write_text('selected: false\n')
            self.assertNotEqual(first, acceptance.input_snapshot(manifest))
            manifest.write_text(json.dumps({'domain': 128, 'profile_id': acceptance.PROFILE}))
            with self.assertRaises(ValueError): acceptance.input_snapshot(manifest)

    def test_actual_ui_route_guard_aborts_unauthorized_mutations_before_network(self):
        # Execute the actual embedded guard against a fake context, not a browser.
        harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs');
const source=JSON.parse(fs.readFileSync(0,'utf8'));let handler;
const context={route:async(_,fn)=>{handler=fn;},newPage:async()=>{throw Error('pure guard test, no page');}};
const browser={newContext:async()=>context,close:async()=>{}};
const plan={web:'http://127.0.0.1:5182',instance:'instance',map_id:'map',domain:129};
new Function('require','process',source)(name=>name==='playwright'?{chromium:{launch:async()=>browser}}:{writeFileSync:()=>{}},{argv:['node',JSON.stringify(plan)]});
setImmediate(async()=>{try{assert.equal(typeof handler,'function');const good={runtime_instance_id:'instance',map_id:'map',profile_id:'passage_manual'};
for(const [url,method,body,expected]of[
 [plan.web+'/sim-api/manual/command','POST',good,'continue'],
 [plan.web+'/sim-api/manual/stop','POST',good,'abort'],
 [plan.web+'/sim-api/manual/command','PUT',good,'abort'],
 ['http://127.0.0.1:9097/sim-api/manual/command','POST',good,'abort'],
 [plan.web+'/sim-api/mission','DELETE',good,'abort'],
 [plan.web+'/sim-api/manual/command','POST',{...good,runtime_instance_id:'other'},'abort'],
 [plan.web+'/sim-api/state','GET',null,'continue']]){let observed;await handler({request:()=>({url:()=>url,method:()=>method,postDataJSON:()=>body}),abort:()=>{observed='abort';},continue:()=>{observed='continue';}});assert.equal(observed,expected);}
}catch(error){console.error(error);process.exitCode=1;}});
"""
        result = subprocess.run(['node', '-e', harness], input=json.dumps(acceptance.UI_PROGRAM), text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_declared_execution_sources_exist(self):
        sources = acceptance.source_snapshot()
        self.assertGreaterEqual(len(sources), 20)
        self.assertIn('tools/fishbot_manual_lease.py', sources)  # idle evidence helper lives here
        self.assertIn('tools/fishbot_manual_ros.py', sources)
        self.assertIn('workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/scripts/mission_bridge.py', sources)

    def initial_fixture(self, output, log):
        observation = Mock(); observation.frames = [None] * 20
        observation.guard_evidence.return_value = {'status': 'latched: odom: receive timeout'}
        run = acceptance.Acceptance(SimpleNamespace(api='http://127.0.0.1:9097', expected_instance='instance', domain=129), output, log, observation)
        runtime = {'instance_id': 'instance', 'domain': 129, 'mode': 'simulation', 'service': 'mission'}
        state = {'mode': 'mujoco', 'domain': 129, 'mission': {'id': None, 'status': 'idle'}}
        status = {'runtime_instance_id': 'instance', 'map_id': 'map', 'profile_id': acceptance.PROFILE, 'limits': acceptance.LIMITS,
            'can_acquire': False, 'reason': 'guard_unavailable', 'native_owner': {'terminal': True}, 'stop_latched': False, 'active_lease_id': None}
        run.api = Mock(); run.api.get.side_effect = lambda path: {'runtime': runtime, 'state': state, 'manual/status': status}[path]
        run.quiet = Mock()
        return run, observation, status, state

    def guard_observer(self, observation, clock, value=None):
        holder = SimpleNamespace(lock=threading.RLock(), guard=value,
            node=SimpleNamespace(get_clock=lambda: SimpleNamespace(now=lambda:
                SimpleNamespace(nanoseconds=round((10.+clock[0])*1e9)))))
        observation.guard_evidence.side_effect = lambda: acceptance.RuntimeObservation.guard_evidence(holder)
        return holder

    def guard_frame(self, clock, *, profile='fishbot_passage', execute='True'):
        return {'steady_time': clock[0], 'source_stamp': 10.+clock[0], 'value': {'status': [
            {'name': 'fishbot_command_guard', 'values': [{'key': 'execute', 'value': execute},
                                                       {'key': 'profile', 'value': profile}]}]}}

    def test_initial_waits_for_actual_delayed_guard_delivery_before_quiet(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp); log = acceptance.Recording(output)
            run, observation, status, _ = self.initial_fixture(output, log)
            status.update(can_acquire=True, reason=None)
            clock = [0.]; holder = self.guard_observer(observation, clock)
            def sleep(seconds):
                clock[0] += seconds
                if clock[0] >= .2:
                    holder.guard = self.guard_frame(clock)
                elif clock[0] >= .1:
                    holder.guard = self.guard_frame([-2.])  # An actual stale frame is not freshness.
            with patch.object(acceptance.time, 'monotonic', side_effect=lambda: clock[0]), \
                    patch.object(acceptance.time, 'sleep', side_effect=sleep):
                value = run.initial()
            self.assertTrue(value['manual']['can_acquire'])
            self.assertAlmostEqual(clock[0], .2)
            self.assertGreaterEqual(observation.guard_evidence.call_count, 5)
            run.quiet.assert_called_once_with(.2)
            run.api.accepted.assert_not_called(); run.api.call.assert_not_called(); log.close()

    def test_initial_guard_delivery_timeout_has_no_mutation_or_quiet_rebase(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp); log = acceptance.Recording(output)
            run, observation, _, _ = self.initial_fixture(output, log)
            run.deadline = .12; clock = [0.]; self.guard_observer(observation, clock)
            def sleep(seconds): clock[0] += seconds
            with patch.object(acceptance.time, 'monotonic', side_effect=lambda: clock[0]), \
                    patch.object(acceptance.time, 'sleep', side_effect=sleep):
                with self.assertRaisesRegex(TimeoutError, 'Declared acceptance deadline'):
                    run.initial()
            self.assertEqual(run.deadline, .12); run.quiet.assert_not_called()
            self.assertEqual(run.api.get.call_count, 3)
            run.api.accepted.assert_not_called(); run.api.call.assert_not_called(); log.close()

    def test_initial_wrong_guard_identity_execute_and_other_errors_fail_immediately(self):
        for change in ({'profile': 'different'}, {'execute': 'False'}, {'missing_status': True},
                       {'exception': RuntimeError('Recorder unavailable')}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                output = Path(temp); log = acceptance.Recording(output)
                run, observation, _, _ = self.initial_fixture(output, log); clock = [0.]
                frame = self.guard_frame(clock, **{k:v for k,v in change.items() if k in {'profile','execute'}})
                if change.get('missing_status'): frame['value']['status'] = []
                self.guard_observer(observation, clock, frame)
                if 'exception' in change: observation.guard_evidence.side_effect = change['exception']
                with patch.object(acceptance.time, 'monotonic', return_value=0.), \
                        patch.object(acceptance.time, 'sleep') as sleep:
                    with self.assertRaises(RuntimeError): run.initial()
                sleep.assert_not_called(); run.quiet.assert_not_called()
                run.api.accepted.assert_not_called(); run.api.call.assert_not_called(); log.close()

    def test_startup_timeout_preserves_last_admission_guard_and_recovery_evidence_without_mutating(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp); log = acceptance.Recording(output)
            run, observation, status, _ = self.initial_fixture(output, log)
            status['idle_recovery'] = {'state': 'unknown', 'reason': 'guard_reset_timeout'}
            def wait(read, predicate, seconds=15):
                value = read()
                if predicate(value): return value
                raise TimeoutError('Declared acceptance deadline exceeded')
            run.wait = wait
            with self.assertRaisesRegex(TimeoutError, 'guard_unavailable.*guard_reset_timeout.*odom: receive timeout'):
                run.initial()
            run.api.accepted.assert_not_called(); log.close()
            records = [json.loads(line) for line in (output/'observations.jsonl').read_text().splitlines()]
            self.assertEqual(records[-1]['topic'], 'initial_readiness_failure')
            self.assertEqual(records[-1]['payload']['last_manual_status']['reason'], 'guard_unavailable')
            self.assertEqual(observation.guard_evidence.call_count, 2)  # Initial gate and retained failure evidence.

    def test_initial_rechecks_original_idle_owner_after_waits_and_never_uses_old_state(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp); log = acceptance.Recording(output)
            run, _, status, state = self.initial_fixture(output, log)
            status['can_acquire'] = True
            def wait(read, predicate, seconds=15):
                value = read()
                self.assertTrue(predicate(value))
                if seconds == 20: state['mission'] = {'id': 'new-owner', 'status': 'running'}
                return value
            run.wait = wait
            with self.assertRaisesRegex(RuntimeError, 'owner or admission changed'): run.initial()
            run.api.accepted.assert_not_called(); log.close()


if __name__ == '__main__': unittest.main()
