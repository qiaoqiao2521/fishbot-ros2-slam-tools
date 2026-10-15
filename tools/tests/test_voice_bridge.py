"""Real loopback HTTP fixtures; no ROS import, simulation, or robot process."""
import copy
import json
import math
from pathlib import Path
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fishbot_voice_bridge import LocalHTTP, VoiceBridge, VoiceError, make_server
from fishbot_voice_asr import VoiceAudioError
from fishbot_edge_voice_node import VoiceGatewayClient


def uid():
    return str(uuid.uuid4())


def parse(text):
    intent, _, argument = text.partition(':')
    params = {}
    if argument:
        params = {'place': argument} if intent == 'GOTO' else {
            'angle_rad' if intent.startswith('TURN') else 'distance_m': float(argument)}
    return {'raw': text, 'cleaned': text, 'dropped_fillers': [], 'intent': intent,
            'accepted': intent != 'UNKNOWN', 'reason': 'unknown_intent' if intent == 'UNKNOWN' else 'accepted',
            'parameters': params}


class Upstream:
    def __init__(self, kind):
        self.kind, self.lock = kind, threading.RLock()
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *unused):
                pass

            def reply(self, code, value):
                data = json.dumps(value).encode()
                self.send_response(code)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self):
                with fixture.lock:
                    fixture.gets.append(self.path)
                    result = copy.deepcopy(fixture.value)
                    elapsed = fixture.read_advance
                    fixture.read_advance = 0
                    if elapsed:
                        fixture.clock[0] += elapsed
                self.reply(200, result)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                with fixture.lock:
                    fixture.calls.append((self.path, copy.deepcopy(body)))
                    if fixture.reject:
                        self.reply(409, {'error': 'geometry_footprint_rejected', 'outcome': 'rejected'})
                        return
                    key = 'mission' if fixture.kind == 'mission' else 'task'
                    if self.path.endswith('/cancel'):
                        expected = fixture.value[key]['id']
                        received = body.get('mission_id' if fixture.kind == 'mission' else 'task_id')
                        if received != expected:
                            self.reply(409, {'error': 'wrong_owner', 'outcome': 'rejected'})
                            return
                        fixture.value[key]['status'] = 'canceled' if fixture.finish_cancel else 'canceling'
                    else:
                        original = body['mission_id' if fixture.kind == 'mission' else 'task_id']
                        fixture.value[key] = {'id': original, 'status': 'running', 'dispatch_state': 'pending'}
                        if fixture.kind == 'mission':
                            fixture.value[key]['start_pose'] = copy.deepcopy(fixture.value['pose'])
                        fixture.value['ready'] = False
                    result = copy.deepcopy(fixture.value)
                    if fixture.wrong_receipt_id:
                        result[key]['id'] = uid()
                    if fixture.receipt_status:
                        result[key]['status'] = fixture.receipt_status
                    delay = fixture.delay
                    lost = fixture.lose
                if delay:
                    time.sleep(delay)
                self.reply(504 if lost else 202, {'error': 'lost_receipt'} if lost else result)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.reset()

    def reset(self):
        with self.lock:
            self.value = {'mode': 'mujoco', 'domain': 121, 'ready': True, 'reason': 'ready',
                          'pose': {'x': 2., 'y': -1., 'yaw': math.pi/2},
                          'nav': {'pose': {'x': 2., 'y': -1., 'yaw': math.pi/2}},
                          'map_rules': {'map_id': 'map-a', 'revision': 7},
                          'episode_id': uid(),
                          'mission' if self.kind == 'mission' else 'task': {'id': None, 'status': 'idle'}}
            self.calls, self.gets = [], []
            self.lose, self.reject, self.finish_cancel = False, False, False
            self.delay, self.read_advance, self.clock = 0, 0, None
            self.wrong_receipt_id, self.receipt_status = False, None

    def terminal(self, status='succeeded'):
        with self.lock:
            self.value['mission' if self.kind == 'mission' else 'task']['status'] = status
            self.value['ready'] = True

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class ASR:
    def __init__(self):
        self.entered, self.release = threading.Event(), threading.Event()
        self.block = False
        self.calls = []
        self.error = None
        self.result = {'text': 'FORWARD', 'model': 'fixture-local', 'language': 'zh',
                       'inference_ms': 12.5, 'word_confidence_mean': .87,
                       'confidence_is_success_probability': False, 'recording_stored': False}

    def availability(self):
        return {'available': True, 'model': 'fixture-local'}

    def transcribe(self, data, mime_type='audio/wav'):
        self.calls.append((data, mime_type))
        self.entered.set()
        if self.block:
            self.release.wait(2.)
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.result)


class VoiceBridgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mission, cls.coop = Upstream('mission'), Upstream('cooperation')

    @classmethod
    def tearDownClass(cls):
        cls.mission.close()
        cls.coop.close()

    def setUp(self):
        self.mission.reset()
        self.coop.reset()
        self.clock = [1700000000.]
        self.asr = ASR()
        self.bridge = VoiceBridge(self.mission.url, self.coop.url, parser=parse,
                                  clock=lambda: self.clock[0], timeout=.08, stop_wait=.04,
                                  transcriber=self.asr, places={'desk': {'x': 3, 'y': 4, 'yaw': 0}})
        self.sequence = 0

    def command(self, text='FORWARD', **changes):
        self.sequence += 1
        return {'command_id': uid(), 'session_id': self.bridge.session_id,
                'sequence': self.sequence, 'issued_at_ms': self.clock[0]*1000,
                'ttl_ms': 5000, 'text': text, **changes}

    def test_preview_never_contacts_upstream(self):
        result = self.bridge.preview({'text': 'FORWARD'})
        self.assertTrue(result['accepted'])
        self.assertEqual(self.mission.calls + self.coop.calls + self.mission.gets + self.coop.gets, [])

    def test_nonzero_heading_relative_goal_preserves_map_and_original_id(self):
        command = self.command()
        result = self.bridge.execute(command)
        path, body = self.mission.calls[0]
        self.assertEqual(path, '/sim-api/mission')
        self.assertEqual(body['mission_id'], command['command_id'])
        self.assertEqual(body['map_id'], 'map-a')
        self.assertEqual(body['rules_revision'], 7)
        self.assertAlmostEqual(body['waypoints'][0]['x'], 2.)
        self.assertAlmostEqual(body['waypoints'][0]['y'], -.6)
        self.assertFalse(body['return_home'])
        self.assertEqual(body['timeout_s'], 30)
        self.assertEqual(result['status'], 'running')
        self.assertIs(result['accepted'], True)
        self.assertEqual(result['task']['id'], command['command_id'])
        self.assertEqual(result['owner'], 'voice:' + self.bridge.session_id)

    def test_backward_uses_native_backup_contract_without_waypoints(self):
        command = self.command('BACKWARD')
        result = self.bridge.execute(command)
        self.assertEqual(self.mission.calls, [('/sim-api/mission', {
            'mission_id': command['command_id'], 'operation': 'backup',
            'distance_m': .3, 'issued_at': self.clock[0], 'timeout_s': 30,
            'map_id': 'map-a', 'rules_revision': 7})])
        self.assertIs(result['accepted'], True)
        self.assertEqual(result['task']['id'], command['command_id'])
        self.assertEqual(self.bridge.home, {
            'pose': {'x': 2., 'y': -1., 'yaw': math.pi/2}, 'map_id': 'map-a'})

    def test_backup_distance_bounds_and_optional_map_fence(self):
        self.mission.value.pop('map_rules')
        for distance in (.05, 1.):
            with self.subTest(distance=distance):
                self.bridge.execute(self.command('BACKWARD:' + str(distance)))
                body = self.mission.calls[-1][1]
                self.assertEqual(body['distance_m'], distance)
                self.assertEqual(body['operation'], 'backup')
                self.assertNotIn('waypoints', body)
                self.assertNotIn('return_home', body)
                self.assertNotIn('map_id', body)
                self.assertNotIn('rules_revision', body)
                self.mission.terminal()

    def test_backup_unknown_receipt_and_cancel_keep_original_uuid(self):
        self.mission.lose = True
        command = self.command('BACKWARD:.2')
        first = self.bridge.execute(command)
        self.assertIsNone(first['accepted'])
        self.assertEqual(first['status'], 'task_unknown')
        self.assertEqual(self.bridge.execute(command), first)
        self.assertEqual(len(self.mission.calls), 1)
        self.assertEqual(self.bridge.state()['task']['status'], 'running')
        stop = self.bridge.execute(self.command('STOP'))
        self.assertIsNone(stop['accepted'])
        self.assertEqual(stop['status'], 'task_unknown')
        self.assertEqual(self.mission.calls[-1], ('/sim-api/cancel', {
            'mission_id': command['command_id'], 'issued_at': self.clock[0]}))
        self.bridge.execute(self.command('STOP'))
        self.assertEqual(len(self.mission.calls), 2)
        self.mission.terminal('canceled')
        self.assertEqual(self.bridge.state()['task']['status'], 'canceled')

    def test_backup_geometry_rejection_remains_definite_without_home_capture(self):
        self.mission.reject = True
        result = self.bridge.execute(self.command('BACKWARD'))
        self.assertIs(result['accepted'], False)
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(result['reason'], 'geometry_footprint_rejected')
        self.assertIsNone(self.bridge.home)

    def test_turn_goal_uses_same_position_and_signed_heading(self):
        self.bridge.execute(self.command('TURN_RIGHT'))
        goal = self.mission.calls[0][1]['waypoints'][0]
        self.assertEqual((goal['x'], goal['y']), (2., -1.))
        self.assertAlmostEqual(goal['yaw'], 0.)

    def test_relative_parameters_cannot_bypass_bounds(self):
        for text in ('FORWARD:1.01', 'BACKWARD:0.01', 'TURN_LEFT:-1', 'TURN_RIGHT:4'):
            with self.subTest(text=text):
                self.assertEqual(self.bridge.execute(self.command(text))['status'], 'rejected')
        self.assertEqual(self.mission.calls, [])

    def test_duplicate_original_envelope_returns_original_receipt_after_expiry(self):
        command = self.command()
        first = self.bridge.execute(command)
        self.clock[0] += 20
        self.mission.terminal()
        self.assertEqual(self.bridge.execute(command), first)
        self.assertEqual(len(self.mission.calls), 1)

    def test_same_uuid_changed_payload_conflicts(self):
        command = self.command()
        self.bridge.execute(command)
        with self.assertRaisesRegex(VoiceError, 'command_id_conflict'):
            self.bridge.execute({**command, 'text': 'STOP'})
        self.assertEqual(len(self.mission.calls), 1)

    def test_sequence_replay_has_no_write(self):
        self.bridge.execute(self.command('UNKNOWN'))
        with self.assertRaisesRegex(VoiceError, 'sequence_replayed'):
            self.bridge.execute(self.command(sequence=1))
        self.assertEqual(self.mission.calls, [])

    def test_stale_future_session_and_ttl_rejected_before_upstream(self):
        changes = ({'issued_at_ms': self.clock[0]*1000-5001},
                   {'issued_at_ms': self.clock[0]*1000+501},
                   {'ttl_ms': 0}, {'ttl_ms': 5001}, {'session_id': uid()})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(VoiceError):
                self.bridge.execute(self.command(**change))
        self.assertEqual(self.mission.gets + self.coop.gets + self.mission.calls, [])

    def test_expiry_is_rechecked_after_state_reads_before_dispatch(self):
        self.mission.clock, self.mission.read_advance = self.clock, .101
        result = self.bridge.execute(self.command(ttl_ms=100))
        self.assertEqual(result['reason'], 'command_expired_or_future')
        self.assertEqual(self.mission.calls, [])

    def test_unknown_intent_and_charging_dock_do_not_dispatch(self):
        self.assertEqual(self.bridge.execute(self.command('UNKNOWN'))['reason'], 'unknown_intent')
        self.assertEqual(self.bridge.execute(self.command('DOCK'))['reason'], 'charging_dock_adapter_not_configured')
        self.assertFalse(self.bridge.state()['capabilities']['DOCK'])
        self.assertEqual(self.mission.calls + self.coop.calls, [])

    def test_wrong_domain_or_unknown_mode_or_task_status_never_dispatches(self):
        for change in ({'domain': 107}, {'mode': 'hardware'}, {'task': {'id': None, 'status': 'mystery'}}):
            with self.subTest(change=change):
                self.coop.reset()
                self.coop.value.update(change)
                result = self.bridge.execute(self.command())
                self.assertEqual(result['status'], 'rejected')
        self.assertEqual(self.mission.calls + self.coop.calls, [])

    def test_unavailable_state_is_rejection_without_unknown_write(self):
        self.bridge.coop.timeout = .000001
        # Deterministically use a closed loopback port, not an external address.
        closed = ThreadingHTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler)
        self.bridge.coop.base = 'http://127.0.0.1:' + str(closed.server_port)
        closed.server_close()
        self.assertEqual(self.bridge.execute(self.command())['reason'], 'upstream_state_unavailable')
        self.assertIsNone(self.bridge.task)
        self.assertEqual(self.mission.calls, [])

    def test_other_owner_active_task_blocks_new_voice_motion(self):
        self.coop.value['task'] = {'id': uid(), 'status': 'running'}
        self.assertEqual(self.bridge.execute(self.command())['reason'], 'upstream_task_busy')
        self.assertEqual(self.mission.calls + self.coop.calls, [])

    def test_authoritative_footprint_rejection_remains_rejected(self):
        self.mission.reject = True
        result = self.bridge.execute(self.command())
        self.assertEqual(result['status'], 'rejected')
        self.assertIs(result['accepted'], False)
        self.assertEqual(result['reason'], 'geometry_footprint_rejected')
        self.assertIsNone(self.bridge.home)

    def test_lost_receipt_recovers_same_uuid_without_resend(self):
        self.mission.lose = True
        command = self.command()
        first = self.bridge.execute(command)
        self.assertEqual(first['status'], 'task_unknown')
        self.assertIsNone(first['accepted'])
        self.assertEqual(first['task']['id'], command['command_id'])
        self.assertEqual(self.bridge.execute(command), first)
        state = self.bridge.state()
        self.assertEqual(state['task']['id'], command['command_id'])
        self.assertEqual(state['task']['status'], 'running')
        self.assertEqual(len(self.mission.calls), 1)

    def test_actual_http_timeout_does_not_resubmit(self):
        self.mission.delay = .2
        command = self.command()
        result = self.bridge.execute(command)
        self.assertEqual(result['status'], 'task_unknown')
        self.bridge.execute(command)
        self.assertEqual(len(self.mission.calls), 1)
        self.assertEqual(self.bridge.state()['task']['status'], 'running')

    def test_unknown_slot_cannot_adopt_idle_or_another_task(self):
        self.mission.lose = True
        self.bridge.execute(self.command())
        self.mission.value['mission'] = {'id': uid(), 'status': 'idle'}
        self.assertEqual(self.bridge.state()['task']['status'], 'task_unknown')
        result = self.bridge.execute(self.command())
        self.assertEqual(result['reason'], 'owned_task_busy_or_unknown')
        self.assertEqual(len(self.mission.calls), 1)

    def test_home_captured_once_at_actual_first_voice_mission(self):
        self.bridge.execute(self.command())
        self.mission.terminal()
        self.mission.value['pose'] = {'x': 9., 'y': 8., 'yaw': 0.}
        self.bridge.execute(self.command('RETURN_HOME'))
        goal = self.mission.calls[-1][1]['waypoints'][0]
        self.assertEqual(goal, {'x': 2., 'y': -1., 'yaw': math.pi/2})
        self.assertEqual(self.bridge.home['pose'], goal)
        self.assertEqual(self.mission.calls[-1][1]['timeout_s'], 120)

    def test_home_missing_or_map_changed_rejects(self):
        self.assertEqual(self.bridge.execute(self.command('RETURN_HOME'))['reason'], 'voice_home_not_captured')
        self.bridge.execute(self.command())
        self.mission.terminal()
        self.mission.value['map_rules']['map_id'] = 'map-b'
        self.assertEqual(self.bridge.execute(self.command('RETURN_HOME'))['reason'], 'voice_home_map_changed')
        self.assertEqual(len(self.mission.calls), 1)

    def test_goto_uses_explicit_named_place_only(self):
        self.assertEqual(self.bridge.execute(self.command('GOTO:door'))['reason'], 'place_not_configured')
        self.bridge.execute(self.command('GOTO:desk'))
        self.assertEqual(self.mission.calls[0][1]['waypoints'][0], {'x': 3., 'y': 4., 'yaw': 0.})

    def test_transport_uses_original_cooperation_identity_and_episode(self):
        command = self.command('TRANSPORT')
        result = self.bridge.execute(command)
        self.assertEqual(result['status'], 'running')
        path, body = self.coop.calls[0]
        self.assertEqual(path, '/coop-api/start')
        self.assertEqual(body['task_id'], command['command_id'])
        self.assertEqual(body['scope'], 'transport')
        self.assertEqual(body['episode_id'], self.coop.value['episode_id'])
        self.assertEqual(self.mission.calls, [])

    def test_stop_waits_for_exact_upstream_terminal_not_cancel_ack(self):
        command = self.command()
        self.bridge.execute(command)
        result = self.bridge.execute(self.command('STOP'))
        self.assertEqual(result['status'], 'canceling')
        self.assertIs(result['accepted'], True)
        self.assertEqual(result['reason'], 'cancel_requested_waiting_terminal')
        self.assertEqual(self.mission.calls[-1][1]['mission_id'], command['command_id'])
        self.mission.terminal('canceled')
        self.assertEqual(self.bridge.state()['task']['status'], 'canceled')

    def test_stop_reports_confirmed_terminal_and_repeated_stop_does_not_resend(self):
        self.coop.finish_cancel = True
        command = self.command('TRANSPORT')
        self.bridge.execute(command)
        result = self.bridge.execute(self.command('STOP'))
        self.assertEqual(result['status'], 'canceled')
        self.assertEqual(self.coop.calls[-1][1]['task_id'], command['command_id'])
        self.bridge.execute(self.command('STOP'))
        self.assertEqual(len(self.coop.calls), 2)

    def test_stop_never_cancels_another_owner(self):
        self.assertEqual(self.bridge.execute(self.command('STOP'))['reason'], 'no_owned_task')
        self.bridge.execute(self.command())
        self.mission.value['mission'] = {'id': uid(), 'status': 'running'}
        self.assertEqual(self.bridge.execute(self.command('STOP'))['reason'], 'owned_task_id_not_current')
        self.assertEqual(len(self.mission.calls), 1)

    def test_lost_cancel_receipt_never_resends_cancel_under_new_stop_uuid(self):
        self.bridge.execute(self.command())
        self.mission.lose = True
        self.assertEqual(self.bridge.execute(self.command('STOP'))['status'], 'task_unknown')
        self.bridge.execute(self.command('STOP'))
        self.assertEqual(len(self.mission.calls), 2)

    def test_asr_received_time_is_not_refreshed_after_transcription(self):
        result = self.bridge.transcribe(b'fixture', 'audio/webm;codecs=opus',
                                        received_at_ms=self.clock[0]*1000-5001)
        self.assertEqual(result['expires_at_ms'], self.clock[0]*1000-1)
        with self.assertRaisesRegex(VoiceError, 'asr_source_expired'):
            self.bridge.execute(self.command(result['text'], asr_id=result['asr_id']))
        self.assertEqual(self.mission.calls, [])

    def test_asr_source_is_bound_to_exact_text_session_and_one_command(self):
        result = self.bridge.transcribe(b'fixture')
        with self.assertRaisesRegex(VoiceError, 'asr_source_mismatch'):
            self.bridge.execute(self.command('BACKWARD', asr_id=result['asr_id']))
        command = self.command(result['text'], asr_id=result['asr_id'])
        self.bridge.execute(command)
        self.mission.terminal()
        with self.assertRaisesRegex(VoiceError, 'asr_source_already_used'):
            self.bridge.execute(self.command(result['text'], asr_id=result['asr_id']))
        self.assertEqual(len(self.mission.calls), 1)

    def test_blocked_asr_does_not_hold_task_lock_or_block_stop(self):
        self.bridge.execute(self.command())
        self.asr.block = True
        with ThreadPoolExecutor(max_workers=2) as executor:
            transcription = executor.submit(self.bridge.transcribe, b'fixture')
            self.assertTrue(self.asr.entered.wait(.2))
            stop = executor.submit(self.bridge.execute, self.command('STOP'))
            result = stop.result(timeout=.4)
            self.assertEqual(result['status'], 'canceling')
            self.assertFalse(transcription.done())
            self.asr.release.set()
            transcription.result(timeout=.3)

    def test_upstream_urls_reject_remote_or_redirect_target_configuration(self):
        for url in ('https://127.0.0.1:9071', 'http://example.com:9071',
                    'http://127.0.0.1:9071/a', 'http://u:p@127.0.0.1:9071'):
            with self.subTest(url=url), self.assertRaises(VoiceError):
                VoiceBridge(mission_url=url)


    def test_successful_http_with_unconfirmed_id_or_invalid_status_stays_unknown(self):
        for option in ('wrong_receipt_id', 'receipt_status'):
            with self.subTest(option=option):
                self.mission.reset()
                setattr(self.mission, option, True if option == 'wrong_receipt_id' else 'mystery')
                command = self.command()
                result = self.bridge.execute(command)
                self.assertEqual(result['status'], 'task_unknown')
                self.assertEqual(self.bridge.execute(command), result)
                self.mission.terminal()
                self.assertEqual(self.bridge.state()['task']['status'], 'succeeded')
                self.assertEqual(len(self.mission.calls), 1)

    def test_state_latest_receipt_tracks_task_but_duplicate_keeps_original(self):
        command = self.command()
        first = self.bridge.execute(command)
        self.mission.terminal()
        latest = self.bridge.state()['latest_command']
        self.assertEqual(latest['status'], 'succeeded')
        self.assertEqual(latest['receipt_status'], 'running')
        self.assertIs(latest['accepted'], True)
        self.assertEqual(self.bridge.execute(command), first)

    def test_explicit_dock_requires_charging_purpose_then_preserves_original_task(self):
        self.bridge.dock = LocalHTTP(self.coop.url, timeout=.08)
        rejected = self.bridge.execute(self.command('DOCK'))
        self.assertEqual(rejected['reason'], 'charging_adapter_purpose_unconfirmed')
        self.assertEqual(self.coop.calls, [])
        self.coop.value['purpose'] = 'charging'
        command = self.command('DOCK')
        result = self.bridge.execute(command)
        self.assertEqual(result['task_id'], command['command_id'])
        self.assertEqual(result['task']['upstream'], 'dock')
        self.assertEqual(self.coop.calls[-1][0], '/dock-api/start')
        self.coop.finish_cancel = True
        stopped = self.bridge.execute(self.command('STOP'))
        self.assertEqual(stopped['status'], 'canceled')
        self.assertEqual(self.coop.calls[-1][0], '/dock-api/cancel')
        self.assertEqual(self.coop.calls[-1][1]['task_id'], command['command_id'])

    def test_invalid_asr_id_is_rejected_without_unhashable_lookup(self):
        with self.assertRaisesRegex(VoiceError, 'asr_id_invalid'):
            self.bridge.execute(self.command(asr_id=[]))
        self.assertEqual(self.mission.calls + self.coop.calls, [])

    def test_stop_unknown_ack_has_null_acceptance_and_never_retries(self):
        self.bridge.execute(self.command())
        self.mission.wrong_receipt_id = True
        result = self.bridge.execute(self.command('STOP'))
        self.assertIsNone(result['accepted'])
        self.assertEqual(result['status'], 'task_unknown')
        self.bridge.execute(self.command('STOP'))
        self.assertEqual(len(self.mission.calls), 2)

    def test_stop_explicit_rejection_has_false_acceptance(self):
        self.bridge.execute(self.command())
        self.mission.reject = True
        result = self.bridge.execute(self.command('STOP'))
        self.assertIs(result['accepted'], False)
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(len(self.mission.calls), 2)

    def test_navigation_profile_leaves_optional_transport_unconfigured(self):
        self.bridge = VoiceBridge(self.mission.url, parser=parse, clock=lambda: self.clock[0])
        self.assertIsNone(self.bridge.coop)
        state = self.bridge.state()
        self.assertTrue(state['ready'])
        self.assertFalse(state['capabilities']['TRANSPORT'])
        self.assertEqual(state['capabilities']['transport_reason'], 'transport_adapter_not_configured')
        result = self.bridge.execute(self.command('TRANSPORT'))
        self.assertIs(result['accepted'], False)
        self.assertEqual(result['reason'], 'transport_adapter_not_configured')
        motion = self.bridge.execute(self.command())
        self.assertIs(motion['accepted'], True)
        self.assertEqual(self.coop.gets + self.coop.calls, [])

    def test_transport_only_profile_does_not_require_mission_api(self):
        self.bridge = VoiceBridge(None, self.coop.url, parser=parse, clock=lambda: self.clock[0])
        self.assertTrue(self.bridge.state()['ready'])
        self.assertFalse(self.bridge.state()['capabilities']['FORWARD'])
        rejected = self.bridge.execute(self.command())
        self.assertIs(rejected['accepted'], False)
        self.assertEqual(rejected['reason'], 'mission_adapter_not_configured')
        result = self.bridge.execute(self.command('TRANSPORT'))
        self.assertIs(result['accepted'], True)
        self.assertEqual(self.mission.gets + self.mission.calls, [])

    def test_no_task_adapters_reports_unavailable_and_rejects_motion(self):
        self.bridge = VoiceBridge(None, None, parser=parse, clock=lambda: self.clock[0])
        self.assertEqual(self.bridge.state()['reason'], 'no_task_adapters_configured')
        self.assertFalse(self.bridge.state()['ready'])
        self.assertIs(self.bridge.execute(self.command())['accepted'], False)
        self.assertEqual(self.mission.gets + self.coop.gets, [])

    def test_asr_audio_errors_preserve_stable_reason_status_without_message(self):
        for reason, status in (('silence', 422), ('asr_busy', 409), ('audio_duration', 413)):
            self.asr.error = VoiceAudioError(reason, '/private/model-path must stay internal', status)
            with self.subTest(reason=reason), self.assertRaises(VoiceError) as caught:
                self.bridge.transcribe(b'fixture')
            self.assertEqual(caught.exception.reason, reason)
            self.assertEqual(caught.exception.status, status)
            self.assertNotIn('/private', str(caught.exception))

    def test_asr_measurements_pass_but_path_metadata_and_probability_claim_do_not(self):
        self.asr.result.update(model='/private/model', language='../../secret',
                               confidence_is_success_probability=True, unused_path='/private/recording')
        result = self.bridge.transcribe(b'fixture')
        self.assertEqual(result['inference_ms'], 12.5)
        self.assertEqual(result['word_confidence_mean'], .87)
        self.assertIs(result['confidence_is_success_probability'], False)
        self.assertIs(result['recording_stored'], False)
        self.assertNotIn('model', result)
        self.assertNotIn('language', result)
        self.assertNotIn('/private', json.dumps(result))
        self.asr.availability = lambda: {'available': True, 'model': '/private/model',
                                        'path': '/private/model', 'reason': '/private/failure'}
        state = self.bridge.asr_state()
        self.assertTrue(state['available'])
        self.assertEqual(state['reason'], 'ready')
        self.assertNotIn('/private', json.dumps(state))

    def test_unknown_receipt_recovery_does_not_rewrite_acceptance_evidence(self):
        self.mission.lose = True
        result = self.bridge.execute(self.command())
        self.assertIsNone(result['accepted'])
        self.mission.terminal()
        latest = self.bridge.state()['latest_command']
        self.assertEqual(latest['status'], 'succeeded')
        self.assertIsNone(latest['accepted'])

    def test_http_origin_host_body_and_preview_guards(self):
        server = make_server(self.bridge, 0, ['http://127.0.0.1:5180'])
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        url = 'http://127.0.0.1:' + str(server.server_port)

        def request(path, body=None, headers=None):
            data = None if body is None else json.dumps(body).encode()
            request = Request(url + path, data=data, headers={'Content-Type': 'application/json', **(headers or {})})
            try:
                response = urlopen(request, timeout=1.)
            except HTTPError as error:
                response = error
            with response:
                return response.code, json.loads(response.read())

        try:
            self.assertEqual(request('/voice-api/state')[1]['mode'], 'simulation')
            self.assertEqual(request('/voice-api/preview', {'text': 'FORWARD'})[1]['intent'], 'FORWARD')
            audio_request = Request(url + '/voice-api/transcribe', data=b'fixture-audio',
                                    headers={'Content-Type': 'audio/webm;codecs=opus'})
            with urlopen(audio_request, timeout=1.) as audio_response:
                audio = json.loads(audio_response.read())
            self.assertEqual(audio['session_id'], self.bridge.session_id)
            self.assertEqual(audio['expires_at_ms'], audio['received_at_ms'] + 5000)
            self.assertEqual(self.mission.calls + self.coop.calls, [])
            for headers in ({'Origin': 'https://evil.example'}, {'Origin': 'null'},
                            {'Origin': 'http://127.0.0.1:1111'}, {'Host': 'evil.example'},
                            {'Sec-Fetch-Site': 'cross-site'}):
                with self.subTest(headers=headers):
                    self.assertEqual(request('/voice-api/execute', self.command(), headers)[0], 403)
            self.assertEqual(request('/voice-api/execute', self.command(),
                                     {'Origin': 'http://127.0.0.1:5180'})[1]['status'], 'running')
            self.assertEqual(request('/voice-api/preview', {'text': 'x'*9000})[0], 413)
            self.assertEqual(request('/voice-api/preview', {'text': 'FORWARD'},
                                     {'Content-Type': 'text/plain'})[0], 415)
            malformed_code, malformed = request('/voice-api/execute', self.command(command_id=[]))
            self.assertEqual(malformed_code, 400)
            self.assertIs(malformed['accepted'], False)
            self.assertEqual(malformed['status'], 'rejected')
            self.assertEqual(len(self.mission.calls), 1)
            client = VoiceGatewayClient(url + '/voice-api/execute')
            stopped = client.forward(self.command('STOP', issued_at_ms=int(self.clock[0]*1000)))
            self.assertIs(stopped['accepted'], True)
            self.assertEqual(stopped['status'], 'canceling')
            rejected = client.forward(self.command('FORWARD', issued_at_ms=int(self.clock[0]*1000)))
            self.assertIs(rejected['accepted'], False)
            self.assertNotEqual(rejected['reason'], 'invalid_gateway_receipt')
            self.asr.error = VoiceAudioError('asr_busy', '/private/internal-error', 409)
            try:
                urlopen(audio_request, timeout=1.)
                self.fail('ASR busy must return HTTP 409')
            except HTTPError as error:
                self.assertEqual(error.code, 409)
                body = json.loads(error.read())
                self.assertEqual(body['reason'], 'asr_busy')
                self.assertIs(body['accepted'], False)
                self.assertNotIn('/private', json.dumps(body))
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == '__main__':
    unittest.main()
