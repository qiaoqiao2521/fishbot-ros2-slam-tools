#!/usr/bin/env python3
"""Loopback voice-to-task adapter. ROS and velocity control stay upstream.

A command reserves its UUID before any write. Lost receipts remain unknown until
an exact-ID state read resolves them; this process never retries a task write.
"""
import argparse
import copy
import json
import math
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from fishbot_edge_voice_node import EdgeVoiceIntentParser
from fishbot_runtime import INSTANCE_HEADER, RUNTIME_CHANGED, RuntimeIdentity, capability

ACTIVE = {'submitting', 'running', 'canceling', 'unknown', 'task_unknown'}
TERMINAL = {'succeeded', 'failed', 'canceled', 'rejected'}
MAX_JSON = 8192
MAX_AUDIO = 4 * 1024 * 1024
MAX_COMMANDS = 4096
AUDIO_TYPES = {'audio/wav', 'audio/x-wav', 'audio/webm', 'audio/ogg'}


class VoiceError(Exception):
    def __init__(self, reason, status=400):
        super().__init__(reason)
        self.reason, self.status = reason, status


class UpstreamUnknown(Exception):
    pass


def finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise VoiceError(label + '_invalid')
    return float(value)


def identity(value, label):
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise VoiceError(label + '_invalid') from None
    return value


def local_url(value, *, origin=False):
    try:
        url = urlsplit(value)
        valid = (url.scheme == 'http' and url.hostname in {'127.0.0.1', 'localhost', '::1'}
                 and url.port is not None and 1 <= url.port <= 65535
                 and not url.username and not url.password and not url.query and not url.fragment
                 and url.path in {'', '/'})
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise VoiceError('origin_invalid' if origin else 'upstream_url_must_be_fixed_loopback')
    return value.rstrip('/')


def read_json(data):
    def invalid(unused):
        raise ValueError('nonfinite JSON')
    return json.loads(data, parse_constant=invalid)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class LocalHTTP:
    """No proxy, redirects, endpoint selection, or implicit retry."""
    def __init__(self, base, timeout=1.5):
        self.base, self.timeout = local_url(base), timeout
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method, path, body=None):
        data = None if body is None else json.dumps(body, allow_nan=False).encode()
        request = Request(self.base + path, data=data, method=method,
                          headers={'Content-Type': 'application/json'})
        try:
            try:
                response = self.opener.open(request, timeout=self.timeout)
            except HTTPError as error:
                response = error
            with response:
                data = response.read(1024 * 1024 + 1)
                if len(data) > 1024 * 1024:
                    raise ValueError('upstream response too large')
                result = read_json(data)
                if not isinstance(result, dict):
                    raise ValueError('upstream response is not an object')
                return response.code, result
        except (OSError, URLError, ValueError, UnicodeError) as error:
            raise UpstreamUnknown(type(error).__name__) from error


class VoiceBridge:
    def __init__(self, mission_url='http://127.0.0.1:9071',
                 coop_url=None, domain=121, *,
                 places=None, transcriber=None, parser=None, dock_adapter=None, clock=time.time,
                 timeout=1.5, stop_wait=.6):
        if type(domain) is not int or not 1 <= domain <= 232 or domain == 107:
            raise VoiceError('isolated_domain_required')
        self.domain, self.clock = domain, clock
        self.mission = LocalHTTP(mission_url, timeout) if mission_url is not None else None
        self.coop = LocalHTTP(coop_url, timeout) if coop_url is not None else None
        self.transcriber, self.parser = transcriber, parser or EdgeVoiceIntentParser.parse
        # Optional charging adapter uses LocalHTTP.request semantics and must
        # declare purpose='charging' in its exact-domain simulation state.
        self.dock = dock_adapter
        self.session_id = str(uuid.uuid4())
        self.owner = 'voice:' + self.session_id
        self.lock = threading.RLock()
        self.last_sequence, self.commands = 0, {}
        self.latest_command, self.task, self.home = None, None, None
        self.asr_records, self.stop_wait = {}, stop_wait
        self.places = {}
        for name, value in (places or {}).items():
            if not isinstance(name, str) or not name.strip() or len(name) > 80:
                raise VoiceError('place_name_invalid')
            self.places[name] = self.pose(value)

    @staticmethod
    def pose(value):
        if not isinstance(value, dict):
            raise VoiceError('estimated_pose_unavailable', 409)
        return {key: finite(value.get(key), 'pose_' + key) for key in ('x', 'y', 'yaw')}

    def preview(self, body):
        if not isinstance(body, dict) or set(body) != {'text'}:
            raise VoiceError('preview_requires_text')
        text = body['text']
        if not isinstance(text, str) or not 1 <= len(text) <= 1000:
            raise VoiceError('text_invalid')
        result = self.parser(text)
        if not isinstance(result, dict):
            raise VoiceError('parser_contract_invalid', 503)
        return result

    @staticmethod
    def safe_metadata(value):
        """Expose model labels and bounded measurements, never adapter paths."""
        result = {}
        for key in ('model', 'language', 'backend', 'mode', 'hardware_acceleration'):
            item = value.get(key)
            if isinstance(item, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,119}', item):
                result[key] = item
        for key, maximum in (('inference_ms', 3600000), ('duration_s', 15),
                             ('rms', 1), ('word_confidence_mean', 1), ('confidence', 1),
                             ('max_audio_bytes', MAX_AUDIO), ('max_duration_s', 15)):
            item = value.get(key)
            if (not isinstance(item, bool) and isinstance(item, (int, float))
                    and math.isfinite(item) and 0 <= item <= maximum):
                result[key] = item
            elif key == 'word_confidence_mean' and item is None:
                result[key] = None
        if isinstance(value.get('audio_formats'), list):
            result['audio_formats'] = [item for item in value['audio_formats']
                                       if isinstance(item, str) and item in AUDIO_TYPES]
        return result

    def asr_state(self):
        if self.transcriber is None:
            return {'available': False, 'reason': 'local_asr_not_configured', 'recording_stored': False}
        try:
            value = self.transcriber.availability()
            if not isinstance(value, dict):
                return {'available': False, 'reason': 'asr_contract_invalid', 'recording_stored': False}
            available = value.get('available') is True
            reason = value.get('reason') or ('ready' if available else 'asr_unavailable')
            if not isinstance(reason, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,99}', reason):
                reason = 'ready' if available else 'asr_unavailable'
            return {**self.safe_metadata(value), 'available': available, 'reason': reason,
                    'recording_stored': False, 'confidence_is_success_probability': False}
        except Exception:
            return {'available': False, 'reason': 'asr_unavailable', 'recording_stored': False}

    def transcribe(self, data, mime_type='audio/wav', *, received_at_ms=None):
        received = int(self.clock() * 1000) if received_at_ms is None else received_at_ms
        media = mime_type.split(';', 1)[0].strip().lower()
        if media not in AUDIO_TYPES:
            raise VoiceError('audio_type_unsupported', 415)
        if not isinstance(data, bytes) or not 0 < len(data) <= MAX_AUDIO:
            raise VoiceError('audio_size_invalid', 413)
        if self.asr_state().get('available') is not True:
            raise VoiceError('local_asr_unavailable', 503)
        try:
            result = self.transcriber.transcribe(data, mime_type=mime_type)
        except Exception as error:
            from fishbot_voice_asr import VoiceAudioError
            if isinstance(error, VoiceAudioError):
                reason = error.reason
                if not isinstance(reason, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,99}', reason):
                    reason = 'asr_failed'
                status = error.status if type(error.status) is int and 400 <= error.status <= 599 else 422
                raise VoiceError(reason, status) from error
            raise VoiceError('asr_failed', 422) from error
        if not isinstance(result, dict) or not isinstance(result.get('text'), str):
            raise VoiceError('asr_contract_invalid', 502)
        parsed = self.preview({'text': result['text']})
        with self.lock:
            now = self.clock() * 1000
            self.asr_records = {key: item for key, item in self.asr_records.items()
                                if now - item['received_at_ms'] <= 5000}
            if len(self.asr_records) >= 128:
                raise VoiceError('asr_capacity_reached', 429)
            asr_id = str(uuid.uuid4())
            self.asr_records[asr_id] = {'session_id': self.session_id, 'text': result['text'],
                                      'received_at_ms': received, 'command_id': None}
        return {'asr_id': asr_id, 'text': result['text'], 'parse': parsed,
                'received_at_ms': received, 'expires_at_ms': received + 5000,
                'session_id': self.session_id, **self.safe_metadata(result),
                'confidence_is_success_probability': False, 'recording_stored': False}

    def endpoint(self, kind):
        if kind == 'mission' and self.mission is not None:
            return self.mission, '/sim-api/state', '/sim-api/mission', '/sim-api/cancel'
        if kind == 'cooperation' and self.coop is not None:
            return self.coop, '/coop-api/state', '/coop-api/start', '/coop-api/cancel'
        if kind == 'dock' and self.dock is not None:
            return self.dock, '/dock-api/state', '/dock-api/start', '/dock-api/cancel'
        reason = {'mission': 'mission_adapter_not_configured',
                  'cooperation': 'transport_adapter_not_configured',
                  'dock': 'charging_dock_adapter_not_configured'}
        raise VoiceError(reason.get(kind, 'task_adapter_not_configured'), 409)

    def sources(self):
        return [(kind, client, self.endpoint(kind)[1]) for kind, client in
                (('mission', self.mission), ('cooperation', self.coop), ('dock', self.dock))
                if client is not None]

    def upstream(self, client, path):
        try:
            code, value = client.request('GET', path)
        except UpstreamUnknown as error:
            raise VoiceError('upstream_state_unavailable', 503) from error
        if code != 200:
            raise VoiceError('upstream_state_unavailable', 503)
        if value.get('mode') not in {'mujoco', 'simulation'}:
            raise VoiceError('upstream_simulation_mode_required', 409)
        if type(value.get('domain')) is not int or value['domain'] != self.domain:
            raise VoiceError('upstream_domain_mismatch', 409)
        if client is self.dock and value.get('purpose') != 'charging':
            raise VoiceError('charging_adapter_purpose_unconfirmed', 409)
        return value

    @staticmethod
    def upstream_task(value, kind):
        record = value.get('mission' if kind == 'mission' else 'task')
        if not isinstance(record, dict) or record.get('status') not in ACTIVE | TERMINAL | {'idle'}:
            raise VoiceError('upstream_task_state_unknown', 409)
        return record

    def refresh_task(self, value, kind):
        if self.task is None or self.task['upstream'] != kind:
            return
        record = self.upstream_task(value, kind)
        if record.get('id') != self.task['id']:
            # Never adopt another owner's task or infer a terminal result from idle.
            if self.task['status'] in ACTIVE:
                self.task.update(status='task_unknown', phase='ownership_unconfirmed')
            return
        status = record['status']
        if status == 'idle':
            self.task.update(status='task_unknown', phase='ownership_unconfirmed')
            return
        self.task.update(status=status, phase=record.get('stage') or record.get('dispatch_state') or status,
                         upstream_record=copy.deepcopy(record))
        for key in ('native_status', 'native_goal_id', 'native_error_code'):
            if key in record:
                self.task[key] = copy.deepcopy(record[key])

    def state(self):
        with self.lock:
            reason, ready = 'ready', True
            snapshots = {}
            for kind, client, path in self.sources():
                try:
                    value = self.upstream(client, path)
                    self.refresh_task(value, kind)
                    record = self.upstream_task(value, kind)
                    snapshots[kind] = {'ready': value.get('ready') is True,
                                       'reason': value.get('reason'), 'task_id': record.get('id'),
                                       'status': record['status']}
                    if record['status'] in ACTIVE:
                        ready, reason = False, 'upstream_task_busy'
                    elif kind == 'mission' and value.get('ready') is not True:
                        ready, reason = False, 'mission_not_ready'
                except (VoiceError, UpstreamUnknown) as error:
                    ready, reason = False, getattr(error, 'reason', 'upstream_unavailable')
                    snapshots[kind] = {'ready': False, 'reason': reason}
            if not snapshots:
                ready, reason = False, 'no_task_adapters_configured'
            elif ready and not any(item.get('ready') is True for item in snapshots.values()):
                ready, reason = False, 'no_adapter_ready'
            if self.task and self.task['status'] in ACTIVE:
                ready, reason = False, 'owned_task_' + self.task['status']
            latest = copy.deepcopy(self.latest_command)
            if (latest and self.task and latest.get('task_id') == self.task['id']
                    and latest['status'] != 'rejected'):
                latest.update(receipt_status=latest['status'], status=self.task['status'],
                              phase=self.task['phase'], task=copy.deepcopy(self.task))
            return copy.deepcopy({'mode': 'simulation', 'domain': self.domain,
                'session_id': self.session_id, 'last_sequence': self.last_sequence,
                'ready': ready, 'reason': reason,
                'asr': self.asr_state(), 'capabilities': {
                    'FORWARD': self.mission is not None, 'BACKWARD': self.mission is not None,
                    'TURN_LEFT': self.mission is not None, 'TURN_RIGHT': self.mission is not None,
                    'STOP': bool(snapshots), 'RETURN_HOME': self.mission is not None and self.home is not None,
                    'TRANSPORT': snapshots.get('cooperation', {}).get('ready', False),
                    'transport_reason': snapshots.get('cooperation', {}).get('reason') or 'transport_adapter_not_configured',
                    'GOTO': self.mission is not None and bool(self.places), 'DOCK': snapshots.get('dock', {}).get('ready', False),
                    'dock_reason': snapshots.get('dock', {}).get('reason') or 'charging_dock_adapter_not_configured',
                    'places': sorted(self.places)},
                'latest_command': latest, 'task': self.task,
                'home': self.home, 'upstreams': snapshots})

    def ensure_current(self, body):
        age = self.clock() * 1000 - finite(body['issued_at_ms'], 'issued_at_ms')
        if age < -500 or age > min(body['ttl_ms'], 5000):
            raise VoiceError('command_expired_or_future', 408)
        if 'asr_id' in body:
            source = self.asr_records.get(body['asr_id'])
            if source is None or not 0 <= self.clock()*1000-source['received_at_ms'] <= 5000:
                raise VoiceError('asr_source_expired', 408)

    def envelope(self, body):
        fields = {'command_id', 'session_id', 'sequence', 'issued_at_ms', 'ttl_ms', 'text'}
        if not isinstance(body, dict) or not fields <= set(body) or set(body) - fields - {'asr_id'}:
            raise VoiceError('command_envelope_invalid')
        identity(body['command_id'], 'command_id')
        if body['session_id'] != self.session_id:
            raise VoiceError('session_mismatch', 409)
        if type(body['sequence']) is not int or body['sequence'] <= 0:
            raise VoiceError('sequence_invalid')
        if type(body['ttl_ms']) is not int or not 1 <= body['ttl_ms'] <= 5000:
            raise VoiceError('ttl_invalid')
        if 'asr_id' in body:
            identity(body['asr_id'], 'asr_id')
        self.ensure_current(body)
        if body['sequence'] <= self.last_sequence:
            raise VoiceError('sequence_replayed', 409)
        if 'asr_id' in body:
            identity(body['asr_id'], 'asr_id')
            source = self.asr_records.get(body['asr_id'])
            if source is None:
                raise VoiceError('asr_source_missing_or_expired', 409)
            if source['session_id'] != self.session_id or source['text'] != body['text']:
                raise VoiceError('asr_source_mismatch', 409)
            if not 0 <= self.clock()*1000 - source['received_at_ms'] <= 5000:
                raise VoiceError('asr_source_expired', 408)
            if source['command_id'] is not None and source['command_id'] != body['command_id']:
                raise VoiceError('asr_source_already_used', 409)

    def execute(self, body):
        with self.lock:
            if not isinstance(body, dict):
                raise VoiceError('command_envelope_invalid')
            try:
                signature = json.dumps(body, sort_keys=True, separators=(',', ':'), allow_nan=False)
            except (ValueError, TypeError):
                raise VoiceError('command_envelope_invalid') from None
            identity(body.get('command_id'), 'command_id')
            previous = self.commands.get(body['command_id'])
            if previous:
                if previous['signature'] != signature:
                    raise VoiceError('command_id_conflict', 409)
                return copy.deepcopy(previous['receipt'])
            self.envelope(body)
            if len(self.commands) >= MAX_COMMANDS:
                raise VoiceError('session_command_capacity_reached', 429)
            parsed = self.preview({'text': body['text']})
            receipt = {'command_id': body['command_id'], 'session_id': self.session_id,
                       'sequence': body['sequence'], 'parse': parsed,
                       'accepted': None, 'status': 'reserved', 'reason': 'reserved',
                       'retry_allowed': False, 'task': None}
            # Reserve before GET/POST. Every outcome, including unknown, is final
            # for this command UUID; a duplicate only reads this exact receipt.
            self.commands[body['command_id']] = {'signature': signature, 'receipt': receipt}
            self.last_sequence = body['sequence']
            if 'asr_id' in body:
                self.asr_records[body['asr_id']]['command_id'] = body['command_id']
            try:
                if parsed.get('accepted') is not True:
                    raise VoiceError(parsed.get('reason') or 'intent_rejected', 422)
                if parsed['intent'] == 'STOP':
                    self.stop(receipt, body)
                else:
                    self.dispatch(receipt, body)
            except VoiceError as error:
                receipt.update(accepted=False, status='rejected', reason=error.reason, http_status=error.status)
            except UpstreamUnknown:
                receipt.update(accepted=None, status='task_unknown', reason='upstream_receipt_unknown')
                if self.task and self.task['status'] in ACTIVE:
                    self.task.update(status='task_unknown', phase='receipt_unknown')
            receipt['task'] = copy.deepcopy(self.task)
            if self.task:
                receipt.update(task_id=self.task['id'], owner=self.task['owner'], phase=self.task['phase'])
            self.latest_command = copy.deepcopy(receipt)
            return copy.deepcopy(receipt)

    def dispatch(self, receipt, envelope):
        parsed, command_id = receipt['parse'], receipt['command_id']
        intent = parsed['intent']
        if intent == 'DOCK' and self.dock is None:
            raise VoiceError('charging_dock_adapter_not_configured', 409)
        if intent == 'TRANSPORT' and self.coop is None:
            raise VoiceError('transport_adapter_not_configured', 409)
        if intent not in {'DOCK', 'TRANSPORT'} and self.mission is None:
            raise VoiceError('mission_adapter_not_configured', 409)
        if self.task and self.task['status'] in ACTIVE:
            # First recover the original task; do not dispatch on an unknown slot.
            kind = self.task['upstream']
            client, path, _, _ = self.endpoint(kind)
            current = self.upstream(client, path)
            self.refresh_task(current, kind)
            if self.task['status'] in ACTIVE:
                raise VoiceError('owned_task_busy_or_unknown', 409)
        configured = {kind: self.upstream(client, path) for kind, client, path in self.sources()}
        mission, coop, dock = (configured.get(kind) for kind in ('mission', 'cooperation', 'dock'))
        for kind, value in configured.items():
            if self.upstream_task(value, kind)['status'] in ACTIVE:
                raise VoiceError('upstream_task_busy', 409)
        if intent == 'DOCK':
            if dock.get('ready') is not True:
                raise VoiceError('charging_dock_not_ready', 409)
            body = {'task_id': command_id, 'issued_at': self.clock()}
            kind, client, path = 'dock', self.dock, '/dock-api/start'
            start_pose = None
        elif intent == 'TRANSPORT':
            if coop.get('ready') is not True:
                raise VoiceError('cooperation_not_ready', 409)
            body = {'task_id': command_id, 'issued_at': self.clock(), 'scope': 'transport'}
            if coop.get('episode_id') is not None:
                body['episode_id'] = coop['episode_id']
            kind, client, path = 'cooperation', self.coop, '/coop-api/start'
            start_pose = None
        else:
            if mission.get('ready') is not True:
                raise VoiceError('mission_not_ready', 409)
            start_pose = self.pose(mission.get('pose'))
            goal = dict(start_pose)
            params = parsed.get('parameters', {})
            if intent in {'FORWARD', 'BACKWARD'}:
                distance = finite(params.get('distance_m', .4 if intent == 'FORWARD' else .3), 'distance')
                if not .05 <= distance <= 1.:
                    raise VoiceError('distance_out_of_range')
                if intent == 'FORWARD':
                    goal['x'] += distance * math.cos(start_pose['yaw'])
                    goal['y'] += distance * math.sin(start_pose['yaw'])
            elif intent in {'TURN_LEFT', 'TURN_RIGHT'}:
                angle = finite(params.get('angle_rad', math.pi/2 if intent == 'TURN_LEFT' else -math.pi/2), 'angle')
                if not 0 < abs(angle) <= math.pi or (angle > 0) != (intent == 'TURN_LEFT'):
                    raise VoiceError('angle_out_of_range')
                goal['yaw'] = math.atan2(math.sin(goal['yaw'] + angle), math.cos(goal['yaw'] + angle))
            elif intent == 'RETURN_HOME':
                if self.home is None:
                    raise VoiceError('voice_home_not_captured', 409)
                current_map = (mission.get('map_rules') or {}).get('map_id')
                if current_map != self.home['map_id']:
                    raise VoiceError('voice_home_map_changed', 409)
                goal = dict(self.home['pose'])
            elif intent == 'GOTO':
                if params.get('place') not in self.places:
                    raise VoiceError('place_not_configured', 409)
                goal = dict(self.places[params['place']])
            else:
                raise VoiceError('intent_not_supported', 422)
            body = {'mission_id': command_id, 'issued_at': self.clock(),
                    'timeout_s': 120 if intent in {'GOTO', 'RETURN_HOME'} else 30}
            if intent == 'BACKWARD':
                # The owner derives the reverse sweep from its fresh pose and
                # dispatches Nav2 BackUp; a rearward waypoint could turn first.
                body.update(operation='backup', distance_m=distance)
            else:
                body.update(waypoints=[goal], return_home=False)
            rules = mission.get('map_rules')
            if isinstance(rules, dict) and rules.get('map_id') is not None:
                body.update(map_id=rules['map_id'], rules_revision=rules.get('revision'))
            kind, client, path = 'mission', self.mission, '/sim-api/mission'
        self.ensure_current(envelope)
        self.task = {'id': command_id, 'task_id': command_id, 'owner': self.owner,
                     'upstream': kind, 'status': 'submitting', 'phase': 'submitted', 'intent': intent}
        try:
            code, value = client.request('POST', path, body)
        except UpstreamUnknown:
            if start_pose is not None and self.home is None:
                self.home = {'pose': start_pose, 'map_id': (mission.get('map_rules') or {}).get('map_id')}
            raise
        if code >= 400 and value.get('outcome') == 'rejected':
            self.task.update(status='rejected', phase='rejected', upstream_record=value)
            raise VoiceError(value.get('error') or 'upstream_rejected', code)
        if code >= 400:
            raise UpstreamUnknown('upstream write outcome unavailable')
        if start_pose is not None and self.home is None:
            self.home = {'pose': start_pose, 'map_id': (mission.get('map_rules') or {}).get('map_id')}
        record = value.get('mission' if kind == 'mission' else 'task')
        if not isinstance(record, dict) or record.get('id') != command_id:
            raise UpstreamUnknown('upstream original task ID unconfirmed')
        try:
            self.refresh_task(value, kind)
        except VoiceError as error:
            raise UpstreamUnknown('upstream task receipt invalid') from error
        receipt.update(accepted=None if self.task['status'] in {'unknown', 'task_unknown'}
                       else self.task['status'] != 'rejected',
                       status=self.task['status'], reason='upstream_task_receipt')

    def stop(self, receipt, envelope):
        if self.task is None or self.task['owner'] != self.owner:
            raise VoiceError('no_owned_task', 409)
        kind, task_id = self.task['upstream'], self.task['id']
        client, state_path, _, cancel_path = self.endpoint(kind)
        value = self.upstream(client, state_path)
        if self.upstream_task(value, kind).get('id') != task_id:
            raise VoiceError('owned_task_id_not_current', 409)
        self.refresh_task(value, kind)
        if self.task['status'] in TERMINAL:
            receipt.update(accepted=self.task['status'] != 'rejected', status=self.task['status'],
                           reason='owned_task_already_terminal')
            return
        body = {'mission_id' if kind == 'mission' else 'task_id': task_id, 'issued_at': self.clock()}
        # An uncertain cancellation is never resent, even under another STOP UUID.
        if self.task.get('cancel_sent'):
            confirmed = self.task.get('cancel_accepted') is True or self.task['status'] == 'canceling'
            receipt.update(accepted=True if confirmed else None,
                           status=self.task['status'] if confirmed else 'task_unknown',
                           reason='cancel_already_requested')
            return
        self.ensure_current(envelope)
        self.task['cancel_sent'] = True
        code, result = client.request('POST', cancel_path, body)
        if code >= 400 and result.get('outcome') == 'rejected':
            self.task['cancel_sent'] = False
            raise VoiceError(result.get('error') or 'cancel_rejected', code)
        if code >= 400:
            raise UpstreamUnknown('cancel outcome unknown')
        record = result.get('mission' if kind == 'mission' else 'task')
        if isinstance(record, dict) and record.get('id') == task_id and record.get('status') == 'rejected':
            self.task['cancel_sent'] = False
            raise VoiceError('cancel_rejected', 409)
        if (not isinstance(record, dict) or record.get('id') != task_id
                or record.get('status') not in ACTIVE | TERMINAL or record['status'] in {'unknown', 'task_unknown'}):
            raise UpstreamUnknown('cancel original task receipt unconfirmed')
        self.task.update(cancel_accepted=True, status='canceling', phase='awaiting_upstream_terminal')
        deadline = time.monotonic() + self.stop_wait
        while True:
            try:
                value = self.upstream(client, state_path)
                self.refresh_task(value, kind)
            except VoiceError as error:
                raise UpstreamUnknown('cancel terminal state unconfirmed') from error
            if self.task['status'] in TERMINAL or time.monotonic() >= deadline:
                break
            time.sleep(.04)
        receipt.update(accepted=None if self.task['status'] in {'unknown', 'task_unknown'} else True,
                       status=self.task['status'], reason='upstream_terminal' if self.task['status'] in TERMINAL
                       else 'cancel_requested_waiting_terminal')


def make_server(bridge, port=9094, allowed_origins=()):
    origins = {local_url(origin, origin=True) for origin in allowed_origins}
    runtime = RuntimeIdentity('voice', 'simulation', bridge.domain, [
        capability('voice', 'delegated', cancel=True, event_history='snapshot'),
    ])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass

        def reply(self, status, value):
            data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header(INSTANCE_HEADER, runtime.instance_id)
            self.send_header('Access-Control-Expose-Headers', INSTANCE_HEADER)
            self.send_header('X-Content-Type-Options', 'nosniff')
            if self.headers.get('Origin') in self.server.origins:
                self.send_header('Access-Control-Allow-Origin', self.headers['Origin'])
                self.send_header('Vary', 'Origin')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def guard(self):
            hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            if self.headers.get('Host') not in hosts:
                raise VoiceError('loopback_host_required', 403)
            origin = self.headers.get('Origin')
            if origin is not None and origin not in self.server.origins:
                raise VoiceError('trusted_loopback_origin_required', 403)
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                raise VoiceError('cross_site_request_rejected', 403)
            if self.headers.get('Transfer-Encoding'):
                raise VoiceError('transfer_encoding_unsupported', 400)

        def do_OPTIONS(self):
            try:
                self.guard()
                self.send_response(204)
                self.send_header('Access-Control-Allow-Origin', self.headers.get('Origin', ''))
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', f'Content-Type, {INSTANCE_HEADER}')
                self.send_header('Content-Length', '0')
                self.end_headers()
            except VoiceError as error:
                self.reply(error.status, {'accepted': False, 'status': 'rejected', 'reason': error.reason,
                                                'error': error.reason, 'outcome': 'rejected', 'retry_allowed': False})

        def do_GET(self):
            try:
                self.guard()
                if self.path == '/voice-api/runtime':
                    self.reply(200, runtime.snapshot())
                    return
                if self.path != '/voice-api/state':
                    raise VoiceError('unknown_endpoint', 404)
                self.reply(200, bridge.state())
            except VoiceError as error:
                self.reply(error.status, {'accepted': False, 'status': 'rejected', 'reason': error.reason,
                                                'error': error.reason, 'outcome': 'rejected', 'retry_allowed': False})

        def do_POST(self):
            received = int(bridge.clock() * 1000)
            try:
                self.guard()
                if not runtime.accepts(self.headers):
                    self.reply(409, RUNTIME_CHANGED)
                    return
                if self.path not in {'/voice-api/preview', '/voice-api/execute', '/voice-api/transcribe'}:
                    raise VoiceError('unknown_endpoint', 404)
                audio = self.path.endswith('/transcribe')
                maximum = MAX_AUDIO if audio else MAX_JSON
                length = self.headers.get('Content-Length', '')
                if not length.isdecimal() or not 0 < int(length) <= maximum:
                    raise VoiceError('body_size_invalid', 413)
                media = self.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
                if not audio and media != 'application/json':
                    raise VoiceError('json_content_type_required', 415)
                self.connection.settimeout(2.)
                data = self.rfile.read(int(length))
                if len(data) != int(length):
                    raise VoiceError('body_incomplete')
                if audio:
                    value = bridge.transcribe(data, self.headers.get('Content-Type', ''), received_at_ms=received)
                else:
                    body = read_json(data)
                    value = bridge.preview(body) if self.path.endswith('/preview') else bridge.execute(body)
                self.reply(200, value)
            except VoiceError as error:
                self.reply(error.status, {'accepted': False, 'status': 'rejected', 'reason': error.reason,
                                                'error': error.reason, 'outcome': 'rejected', 'retry_allowed': False})
            except (ValueError, UnicodeError, OSError):
                self.reply(400, {'accepted': False, 'status': 'rejected', 'reason': 'invalid_or_incomplete_body',
                                 'error': 'invalid_or_incomplete_body', 'outcome': 'rejected', 'retry_allowed': False})

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.runtime = runtime
    server.origins = origins | {f'http://127.0.0.1:{server.server_port}', f'http://localhost:{server.server_port}'}
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=9094)
    parser.add_argument('--domain', type=int, default=121)
    parser.add_argument('--mission-url', default='http://127.0.0.1:9071')
    parser.add_argument('--coop-url', default=None, help='Optional fixed loopback transport API')
    parser.add_argument('--no-mission', action='store_true', help='Disable navigation for a transport-only profile')
    parser.add_argument('--dock-url', help='Explicit charging adapter with purpose=charging; never a SO101 workcell')
    parser.add_argument('--places', type=Path, help='Explicit JSON object mapping place names to map poses')
    parser.add_argument('--asr-model', type=Path, help='Existing local ASR model; never downloaded here')
    parser.add_argument('--allow-origin', action='append', default=[], help='Fixed trusted loopback UI origin')
    args = parser.parse_args(argv)
    try:
        from fishbot_voice_asr import create_transcriber
        transcriber = create_transcriber(model_path=args.asr_model)
        places = read_json(args.places.read_bytes()) if args.places else {}
        if not isinstance(places, dict):
            raise VoiceError('places_must_be_object')
        bridge = VoiceBridge(None if args.no_mission else args.mission_url, args.coop_url, args.domain,
                             places=places, transcriber=transcriber,
                             dock_adapter=LocalHTTP(args.dock_url) if args.dock_url else None)
        server = make_server(bridge, args.port, args.allow_origin)
    except (VoiceError, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({'mode': 'simulation', 'domain': args.domain, 'session_id': bridge.session_id,
                      'url': f'http://127.0.0.1:{server.server_port}/voice-api/state'}, ensure_ascii=False), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
