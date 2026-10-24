#!/usr/bin/env python3
"""Durable, explicit batch sequencing over the existing local cooperation API."""
import argparse
import copy
import fcntl
import json
import math
import os
from pathlib import Path
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from cooperation_core import Rejected, task_delivery_pose, task_delivery_approaches
from cooperation_business import normalize_delivery
from fishbot_simulation_suite import write_json


TERMINAL = {'succeeded', 'failed', 'canceled'}


class ContractError(ValueError):
    pass


class TransportUnknown(RuntimeError):
    pass


class RunnerDeadline(TimeoutError):
    pass


def identity(value):
    try:
        if str(uuid.UUID(value)) == value:
            return value
    except (ValueError, TypeError, AttributeError):
        pass
    raise ContractError('identity must be a canonical UUID')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def read_json(path):
    def invalid(value):
        raise ContractError('nonfinite JSON is forbidden: '+value)
    return json.loads(Path(path).read_text(encoding='utf-8'), parse_constant=invalid)


def delivery_pose(value):
    """Canonical request values; preserve yaw so task identity stays explicit."""
    try:
        return task_delivery_pose({'delivery_pose': value})
    except Rejected as error:
        raise ContractError(str(error)) from error


def delivery_approaches(value):
    try:
        return task_delivery_approaches({'delivery_approach_poses': value})
    except Rejected as error:
        raise ContractError(str(error)) from error


class LocalBridge:
    """No POST retries, credentials, bridge restarts, or ROS ownership."""
    def __init__(self, endpoint, timeout=5.):
        parts = urlsplit(endpoint)
        if (parts.scheme != 'http' or parts.hostname not in ('127.0.0.1', 'localhost')
                or parts.username or parts.password or not parts.port
                or parts.path not in ('', '/') or parts.query or parts.fragment):
            raise ContractError('bridge must be an explicit localhost HTTP port')
        self.endpoint = endpoint.rstrip('/')
        self.timeout = timeout

    def request(self, path, body=None):
        request = Request(self.endpoint+path,
                          data=None if body is None else canonical(body).encode(),
                          headers={'Content-Type': 'application/json'},
                          method='GET' if body is None else 'POST')
        try:
            with urlopen(request, timeout=self.timeout) as response:
                value = json.loads(response.read(2*1024*1024).decode())
        except HTTPError as error:
            try:
                value = json.loads(error.read(8192).decode())
            except (ValueError, UnicodeError):
                raise TransportUnknown('HTTP error without a usable receipt') from error
            if (isinstance(value, dict) and body is not None and 400 <= error.code < 500
                    and value.get('outcome') == 'rejected'):
                return value
            raise TransportUnknown('HTTP result unknown: '+str(error.code)) from error
        except (URLError, OSError, ValueError, UnicodeError) as error:
            raise TransportUnknown(str(error)) from error
        if not isinstance(value, dict):
            raise TransportUnknown('bridge response is not an object')
        return value

    def state(self):
        return self.request('/coop-api/state')

    def reset(self, request_id):
        return self.request('/coop-api/reset/'+identity(request_id))

    def post(self, kind, body):
        return self.request('/coop-api/'+kind, body)


class Workflow:
    """One file owner and one explicit step per invocation; no background scheduler."""
    def __init__(self, path, bridge, clock=time.time):
        self.path, self.bridge, self.clock = Path(path), bridge, clock
        self.data = None
        self.lock = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(str(self.path)+'.lock', os.O_RDWR | os.O_CREAT, 0o600)
        self.lock = os.fdopen(descriptor, 'a+')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.path.exists():
                self.data = read_json(self.path)
                self._validate_ledger()
        except BaseException:
            self.lock.close()
            self.lock = None
            raise
        return self

    def __exit__(self, *unused):
        self.lock.close()

    def _validate_ledger(self):
        value = self.data
        scope=value.get('scope','transport') if isinstance(value,dict) else None
        continuous = value.get('execution_mode') == 'continuous' if isinstance(value,dict) else False
        if (not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1
                or value.get('endpoint') != self.bridge.endpoint
                or type(value.get('revision')) is not int or value['revision'] < 1
                or value.get('status') not in {'waiting_ready', 'active', 'canceling', 'unknown',
                                              'waiting_quiet', 'waiting_reset', 'reset_pending',
                                              'fault', 'succeeded'} or scope not in ('transport','route')):
            raise ContractError('invalid ledger or different bridge endpoint')
        identity(value['workflow_id'])
        identity(value['episode_id'])
        if continuous and (not isinstance(value.get('world_session_id'),str) or not value['world_session_id']):
            raise ContractError('continuous ledger requires its original physical world identity')
        if (not isinstance(value.get('jobs'), list) or not value['jobs']
                or type(value.get('index')) is not int or not 0 <= value['index'] < len(value['jobs'])):
            raise ContractError('ledger must contain a nonempty sequential job list')
        if not isinstance(value.get('events'), dict) or not isinstance(value.get('resets'), list):
            raise ContractError('ledger event/reset inventory is invalid')
        ids, tasks, jobs = set(), set(), set()
        for job in value['jobs']:
            identity(job['job_id'])
            identity(job['batch_id'])
            if (job['batch_id'] in ids or job['job_id'] in jobs or job['machine_id'] not in value['machines']
                    or job['status'] not in ('waiting', 'active', 'fault', 'succeeded')):
                raise ContractError('duplicate batch or unknown machine')
            ids.add(job['batch_id'])
            jobs.add(job['job_id'])
            target = delivery_pose(job['delivery_pose']) if 'delivery_pose' in job else None
            approaches = (delivery_approaches(job['delivery_approach_poses'])
                          if 'delivery_approach_poses' in job else None)
            for attempt in job['attempts']:
                identity(attempt['task_id'])
                identity(attempt['episode_id'])
                if (attempt['task_id'] in tasks or attempt['dispatch']['body']['task_id'] != attempt['task_id']
                        or attempt['dispatch']['body']['episode_id'] != attempt['episode_id']
                        or set(attempt['dispatch']['body']) != ({'task_id', 'episode_id', 'issued_at'}
                            | ({'scope'} if 'scope' in value else set())
                            | ({'business_delivery'} if continuous else set())
                            | ({'delivery_pose'} if target is not None else set())
                            | ({'delivery_approach_poses'} if approaches is not None else set()))
                        or ('scope' in value and attempt['dispatch']['body'].get('scope')!=scope)
                        or (continuous and normalize_delivery(attempt['dispatch']['body']['business_delivery'])
                            != normalize_delivery(job['business_delivery']))
                        or ('delivery_pose' in attempt) != (target is not None)
                        or (target is not None and (delivery_pose(attempt['delivery_pose']) != target
                            or delivery_pose(attempt['dispatch']['body']['delivery_pose']) != target))
                        or ('delivery_approach_poses' in attempt) != (approaches is not None)
                        or (approaches is not None and (
                            delivery_approaches(attempt['delivery_approach_poses']) != approaches
                            or delivery_approaches(attempt['dispatch']['body']['delivery_approach_poses']) != approaches))
                        or attempt['status'] not in TERMINAL | {'unknown', 'running', 'canceling', 'rejected'}):
                    raise ContractError('conflicting task identity in ledger')
                tasks.add(attempt['task_id'])
        for machine in value['machines'].values():
            if (type(machine['capacity']) is not int or machine['capacity'] != 1
                    or type(machine['version']) is not int or machine['version'] < 0
                    or machine['occupant'] not in jobs | {None}):
                raise ContractError('machine inventory/capacity is invalid')
        operation = value['operation']
        if operation is not None:
            attempt = self._job()['attempts'][-1]
            if operation['kind'] not in ('task', 'reset') or operation['task_id'] != attempt['task_id']:
                raise ContractError('operation does not bind the original current task')
            if operation['kind'] == 'reset':
                identity(operation['request_id'])
                if (operation['body']['request_id'] != operation['request_id']
                        or operation['body']['episode_id'] != attempt['episode_id']
                        or operation['from_episode'] != attempt['episode_id']
                        or operation['purpose'] not in ('advance', 'retry')
                        or len([r for r in value['resets'] if r == operation]) != 1):
                    raise ContractError('reset operation inventory is inconsistent')
        canonical(value)

    def _save(self):
        self.data['revision'] += 1
        write_json(self.path, self.data)
        # Reuse the project's atomic replace. Do not send until durability is confirmed.
        with self.path.open('rb') as stream:
            os.fsync(stream.fileno())
        descriptor = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def create(self, batches, machine='laundry-machine-1', delivery_poses=None, scene_profile=None,
               delivery_approach_poses=None, scope='transport', continuous_deliveries=None):
        if self.data is not None:
            raise ContractError('ledger already exists; it cannot be reinitialized')
        if scope not in ('transport','route'):
            raise ContractError('workflow scope must be transport or an explicit R2 route')
        if (not isinstance(batches, (list, tuple)) or not batches
                or not machine or not isinstance(machine, str)):
            raise ContractError('a nonempty batch list and a machine are required')
        for batch in batches:
            identity(batch)
        if len(set(batches)) != len(batches):
            raise ContractError('batch identities must be distinct')
        targets = {} if delivery_poses is None else delivery_poses
        if not isinstance(targets, dict) or set(targets) - set(batches):
            raise ContractError('delivery-poses must map selected batch UUIDs to delivery_pose values')
        targets = {batch: delivery_pose(target) for batch, target in targets.items()}
        approaches = {} if delivery_approach_poses is None else delivery_approach_poses
        if not isinstance(approaches, dict) or set(approaches)-set(batches):
            raise ContractError('delivery-approach-poses must map selected batch UUIDs to ordered poses')
        approaches = {batch: delivery_approaches(poses) for batch, poses in approaches.items()}
        selected = None
        if continuous_deliveries is not None:
            if (scope != 'transport' or not isinstance(continuous_deliveries,dict)
                    or set(continuous_deliveries) != set(batches) or set(targets) != set(batches)):
                raise ContractError('continuous deliveries require explicit cargo binding and goal for every batch')
            selected = {batch:normalize_delivery(binding) for batch,binding in continuous_deliveries.items()}
            if len({binding['cargo_id'] for binding in selected.values()}) != len(selected):
                raise ContractError('finite continuous orders must use distinct physical cargo')
        state = self.bridge.state()
        if scene_profile is not None and state.get('scene_profile') != scene_profile:
            raise ContractError('selected scene profile does not match the actual bridge instance')
        episode = identity(state.get('episode_id'))
        source, task = state.get('source'), state.get('task')
        scene = source.get('scene_sha') if isinstance(source, dict) else None
        if (state.get('mode') != 'mujoco' or state.get('ready') is not True
                or not isinstance(task, dict)
                or (selected is None and (task.get('id') is not None or task.get('status') != 'idle'))
                or (selected is not None and task.get('status') not in ('idle','succeeded'))
                or (selected is None and (not isinstance(scene, str) or len(scene) != 64
                    or any(c not in '0123456789abcdef' for c in scene)))):
            raise ContractError('create requires a fresh idle ready synthetic episode')
        self.data = {'schema': 1, 'workflow_id': str(uuid.uuid4()), 'revision': 0,
                     'endpoint': self.bridge.endpoint, 'scene_sha256': scene,
                     'episode_id': episode, 'status': 'waiting_ready', 'reason': None,
                     'index': 0, 'operation': None, 'events': {}, 'resets': [],
                     'machines': {machine: {'capacity': 1, 'occupant': None, 'version': 0, 'event': None}},
                     'jobs': [{'job_id': str(uuid.uuid4()), 'batch_id': batch, 'machine_id': machine,
                               'status': 'waiting', 'attempts': [],
                               **({'delivery_pose': copy.deepcopy(targets[batch])} if batch in targets else {}),
                               **({'delivery_approach_poses': copy.deepcopy(approaches[batch])}
                                  if batch in approaches else {}),
                               **({'business_delivery':copy.deepcopy(selected[batch])} if selected else {})}
                              for batch in batches]}
        if scope!='transport':
            self.data['scope']=scope
        if selected is not None:
            inventory = state.get('business_inventory') or {}
            world = inventory.get('world_id')
            if not isinstance(world,str) or not world:
                self.data=None
                raise ContractError('continuous delivery requires measured world inventory')
            if any(inventory.get('cargo',{}).get(binding['cargo_id'],{}).get('state')!='available'
                   for binding in selected.values()):
                self.data=None
                raise ContractError('selected physical stock is unavailable; no reset requested')
            self.data.update(execution_mode='continuous',world_session_id=world)
        self._save()
        return self.snapshot()

    def snapshot(self):
        if self.data is None:
            raise ContractError('initialize the workflow first')
        return copy.deepcopy(self.data)

    def _job(self):
        return self.data['jobs'][self.data['index']]

    def _state(self):
        state = self.bridge.state()
        source, reset = state.get('source'), state.get('reset')
        if (state.get('mode') != 'mujoco'
                or (self.data.get('execution_mode') != 'continuous'
                    and (not isinstance(source,dict) or source.get('scene_sha') != self.data['scene_sha256']))
                or not isinstance(state.get('task'), dict) or not isinstance(state.get('history'), list)
                or not isinstance(reset, dict) or type(reset.get('available')) is not bool
                or type(reset.get('pending')) is not bool):
            raise ContractError('bridge scene or state contract changed')
        identity(state.get('episode_id'))
        if (self.data.get('execution_mode')=='continuous'
                and (state.get('business_inventory') or {}).get('world_id')!=self.data['world_session_id']):
            raise ContractError('continuous physical world changed; original order was not replayed')
        return state

    def _find_task(self, state, attempt):
        candidates = []
        if state['task'].get('id') == attempt['task_id']:
            candidates.append({'task': state['task'], 'episode_id': state['episode_id']})
        if any(not isinstance(item, dict) or not isinstance(item.get('task'), dict) for item in state['history']):
            raise ContractError('malformed task history cannot prove an original task')
        candidates.extend(item for item in state['history'] if item['task'].get('id') == attempt['task_id'])
        if not candidates:
            raise ContractError('original task ID is absent; execution remains unknown')
        if (any(item.get('episode_id') != attempt['episode_id'] for item in candidates)
                or len({canonical(item['task']) for item in candidates}) != 1):
            raise ContractError('conflicting task history or episode')
        task = candidates[0]['task']
        if 'scope' in self.data and task.get('scope')!=self.data['scope']:
            raise ContractError('original task ID has a different scope')
        if ('delivery_pose' in attempt
                and delivery_pose(task.get('delivery_pose')) != attempt['delivery_pose']):
            raise ContractError('original task ID has a different delivery_pose')
        if ('delivery_approach_poses' in attempt
                and delivery_approaches(task.get('delivery_approach_poses')) != attempt['delivery_approach_poses']):
            raise ContractError('original task ID has different delivery_approach_poses')
        if self.data.get('execution_mode')=='continuous':
            try:
                matched = normalize_delivery(task.get('business_delivery'))==attempt['dispatch']['body']['business_delivery']
            except Rejected as error:
                raise ContractError('original task has no usable named delivery binding') from error
            if not matched:
                raise ContractError('original task ID has a different physical cargo binding')
        if task.get('status') not in TERMINAL | {'running', 'canceling', 'unknown'}:
            raise ContractError('original task has no usable state')
        return copy.deepcopy(task)

    def _quiet(self, state, attempt):
        if self.data.get('execution_mode')=='continuous':
            cleanup=state.get('cleanup',{})
            binding=attempt['dispatch']['body']['business_delivery']
            cargo=(state.get('business_inventory') or {}).get('cargo',{}).get(binding['cargo_id'],{})
            delivered=(cargo.get('state')=='delivered' and cargo.get('task_id')==attempt['task_id'])
            return (state['episode_id']==attempt['episode_id']
                    and state['task'].get('id')==attempt['task_id']
                    and state.get('reset',{}).get('pending') is False
                    and cleanup.get('state')=='verified'
                    and all(cleanup.get(key) is True for key in ('native_terminal','quiet','hold','guard_disabled'))
                    and (state['task'].get('status')!='succeeded' or delivered))
        return (state['episode_id'] == attempt['episode_id']
                and state['task'].get('id') in (None, attempt['task_id'])
                and state.get('reset', {}).get('available') is True
                and state['reset'].get('pending') is False)

    def event(self, event):
        self.snapshot()
        if (not isinstance(event, dict) or set(event) != {'event_id', 'batch_id', 'machine_id', 'version', 'ready'}
                or type(event['version']) is not int or event['version'] < 1 or type(event['ready']) is not bool):
            raise ContractError('event needs identity, batch, machine, version, and boolean ready')
        identity(event['event_id'])
        identity(event['batch_id'])
        existing = self.data['events'].get(event['event_id'])
        if existing is not None:
            if existing != event:
                raise ContractError('event ID already binds a different payload')
            return self.snapshot()
        job = self._job()
        if (self.data['status'] != 'waiting_ready' or event['batch_id'] != job['batch_id']
                or event['machine_id'] != job['machine_id']):
            raise ContractError('readiness must match the currently waiting batch and machine')
        machine = self.data['machines'][job['machine_id']]
        if machine['occupant'] is not None or event['version'] != machine['version']+1:
            raise ContractError('machine occupied or event version is stale/out of order')
        machine.update(version=event['version'], event=copy.deepcopy(event))
        self.data['events'][event['event_id']] = copy.deepcopy(event)
        self._save()
        return self.snapshot()

    def _post(self, kind, record, before_dispatch=None):
        # This record has already been durably saved. Even exceptions cannot authorize replay.
        if before_dispatch is not None:
            before_dispatch()
        try:
            receipt = self.bridge.post(kind, record['body'])
            record['receipt'] = copy.deepcopy(receipt)
            record['outcome'] = 'rejected' if receipt.get('outcome') == 'rejected' else 'receipt_received'
        except TransportUnknown as error:
            record.update(outcome='unknown', error=str(error))
            self.data.update(status='unknown', reason=kind+' receipt unknown; query original ID only')
        self._save()

    def dispatch(self, before_dispatch=None):
        self.snapshot()
        if self.data['status'] != 'waiting_ready' or self.data['operation'] is not None:
            raise ContractError('dispatch requires an unsent waiting job')
        job = self._job()
        machine = self.data['machines'][job['machine_id']]
        event = machine['event']
        if (machine['occupant'] is not None or event is None or event['ready'] is not True
                or event['batch_id'] != job['batch_id']):
            raise ContractError('matching machine-ready event is required')
        state = self._state()
        legacy = self.data.get('execution_mode') != 'continuous'
        if (state['episode_id'] != self.data['episode_id'] or state.get('ready') is not True
                or (legacy and (state['task'].get('id') is not None or state['task'].get('status') != 'idle'))
                or (not legacy and state['task'].get('status') not in ('idle','succeeded'))):
            raise ContractError('current episode is not idle and ready')
        if before_dispatch is not None:
            before_dispatch()
        task_id = str(uuid.uuid4())
        record = {'body': {'task_id': task_id, 'episode_id': self.data['episode_id'],
                           'issued_at': self.clock()},
                  'outcome': 'attempted', 'receipt': None}
        if 'scope' in self.data:
            record['body']['scope']=self.data['scope']
        if 'business_delivery' in job:
            record['body']['business_delivery']=copy.deepcopy(job['business_delivery'])
        attempt = {'task_id': task_id, 'episode_id': self.data['episode_id'], 'status': 'unknown',
                   'ready_event_id': event['event_id'], 'dispatch': record, 'cancel': None, 'task': None}
        if 'delivery_pose' in job:
            target = delivery_pose(job['delivery_pose'])
            record['body']['delivery_pose'] = copy.deepcopy(target)
            attempt['delivery_pose'] = copy.deepcopy(target)
        if 'delivery_approach_poses' in job:
            approaches = delivery_approaches(job['delivery_approach_poses'])
            record['body']['delivery_approach_poses'] = copy.deepcopy(approaches)
            attempt['delivery_approach_poses'] = copy.deepcopy(approaches)
        job['attempts'].append(attempt)
        job['status'] = 'active'
        machine['occupant'] = job['job_id']
        self.data.update(status='active', reason=None, operation={'kind': 'task', 'task_id': task_id})
        self._save()
        self._post('start', record, before_dispatch)
        if record['outcome'] == 'rejected':
            attempt['status'] = 'rejected'
            self.data.update(status='fault', reason='start_rejected')
            self._save()
        return self.snapshot()

    def tick(self):
        self.snapshot()
        operation = self.data['operation']
        if operation is None or self.data['status'] == 'succeeded':
            return self.snapshot()
        try:
            state = self._state()
            if operation['kind'] == 'reset':
                self._reconcile_reset(state, operation)
            else:
                attempt = self._job()['attempts'][-1]
                if attempt['dispatch']['outcome'] == 'rejected':
                    self.data.update(status='fault', reason='start_rejected')
                else:
                    task = self._find_task(state, attempt)
                    attempt.update(status=task['status'], task=task)
                    if state['episode_id'] != attempt['episode_id']:
                        raise ContractError('episode changed without this workflow reset ACK')
                    if task['status'] in TERMINAL:
                        if not self._quiet(state, attempt):
                            self.data.update(status='waiting_quiet', reason='terminal task still lacks quiet/reset admission')
                        elif task['status'] == 'succeeded':
                            self._job()['status'] = 'succeeded'
                            last = self.data['index'] == len(self.data['jobs'])-1
                            continuous = self.data.get('execution_mode')=='continuous'
                            self.data.update(status='succeeded' if last else ('waiting_ready' if continuous else 'waiting_reset'), reason=None)
                            if last:
                                self.data['machines'][self._job()['machine_id']]['occupant'] = None
                            elif continuous:
                                machine=self.data['machines'][self._job()['machine_id']]
                                machine.update(occupant=None,event=None)
                                self.data['index']+=1
                                self.data['operation']=None
                        else:
                            self._job()['status'] = 'fault'
                            self.data.update(status='fault', reason=task['status'])
                    else:
                        self.data.update(status=task['status'] if task['status'] != 'running' else 'active', reason=None)
        except (TransportUnknown, ContractError) as error:
            self.data.update(status='unknown', reason=str(error))
        self._save()
        return self.snapshot()

    def cancel(self):
        self.tick()
        if self.data['operation'] is None or self.data['operation']['kind'] != 'task':
            raise ContractError('no original task to cancel')
        attempt = self._job()['attempts'][-1]
        if attempt['cancel'] is not None:
            return self.snapshot()  # The same cancel intent also never replays.
        if attempt['status'] not in ('running', 'canceling') or self.data['status'] not in ('active', 'canceling'):
            raise ContractError('cancel requires a known active original task')
        record = {'body': {'task_id': attempt['task_id'], 'issued_at': self.clock()},
                  'outcome': 'attempted', 'receipt': None}
        attempt['cancel'] = record
        self.data['status'] = 'canceling'
        self._save()
        self._post('cancel', record)
        return self.snapshot()

    def reset(self, recover=False, before_dispatch=None):
        self.snapshot()
        if self.data.get('execution_mode')=='continuous':
            raise ContractError('continuous workflow never resets or manufactures stock; inspect the original world')
        self.tick()
        if before_dispatch is not None:
            before_dispatch()
        operation = self.data['operation']
        if operation is None or operation['kind'] == 'reset':
            raise ContractError('reset already attempted or no completed task')
        attempt = self._job()['attempts'][-1]
        expected = {'failed', 'canceled', 'rejected'} if recover else {'succeeded'}
        if self.data['status'] not in ('fault', 'waiting_reset') or attempt['status'] not in expected:
            raise ContractError('explicit recovery requires known failure; advance requires success')
        state = self._state()
        if attempt['status'] != 'rejected' and self._find_task(state, attempt)['status'] != attempt['status']:
            raise ContractError('original terminal status changed')
        if not self._quiet(state, attempt):
            raise ContractError('original episode lacks terminal/quiet reset admission')
        if before_dispatch is not None:
            before_dispatch()
        request_id = str(uuid.uuid4())
        record = {'kind': 'reset', 'request_id': request_id, 'from_episode': attempt['episode_id'],
                  'task_id': attempt['task_id'], 'purpose': 'retry' if recover else 'advance',
                  'body': {'request_id': request_id, 'episode_id': attempt['episode_id'], 'issued_at': self.clock()},
                  'outcome': 'attempted', 'receipt': None, 'ack': None}
        self.data['resets'].append(record)
        self.data.update(operation=record, status='reset_pending', reason=None)
        self._save()
        self._post('reset', record, before_dispatch)
        return self.snapshot()

    def _reconcile_reset(self, state, operation):
        # JSON loading does not preserve the operation/resets alias; update both explicitly.
        record = next(item for item in self.data['resets'] if item['request_id'] == operation['request_id'])
        if record['outcome'] == 'rejected':
            self.data.update(status='fault', reason='reset_rejected; retain receipt for owner review')
            return
        ack = self.bridge.reset(operation['request_id'])
        if (ack.get('request_id') != operation['request_id'] or ack.get('episode_id') != operation['from_episode']
                or ack.get('status') not in ('pending', 'unknown', 'failed', 'succeeded')):
            raise ContractError('reset ACK identity/status mismatch')
        record['ack'] = copy.deepcopy(ack)
        self.data['operation'] = record
        if ack['status'] != 'succeeded':
            self.data.update(status='fault' if ack['status'] == 'failed' else 'reset_pending',
                             reason='reset_'+ack['status'])
            return
        # The ACK may complete after tick's state GET. Re-read only after the
        # original reset succeeds, so its new episode and history agree.
        state = self._state()
        new_episode = identity(ack.get('new_episode_id'))
        attempt = self._job()['attempts'][-1]
        if attempt['status'] != 'rejected':
            if self._find_task(state, attempt)['status'] != attempt['status']:
                raise ContractError('reset lost original terminal history')
        if (new_episode == operation['from_episode'] or state['episode_id'] != new_episode
                or state.get('ready') is not True or state['task'].get('id') is not None
                or state['task'].get('status') != 'idle' or state.get('reset', {}).get('pending') is not False):
            raise ContractError('same-ID reset ACK lacks a ready new episode')
        self.data['machines'][self._job()['machine_id']].update(occupant=None, event=None)
        if operation['purpose'] == 'advance':
            self.data['index'] += 1
        else:
            self._job()['status'] = 'waiting'
        self.data.update(episode_id=new_episode, operation=None, status='waiting_ready', reason=None)


def run_workflow(path, bridge, *, timeout=900., poll=1., clock=time.monotonic,
                 sleep=time.sleep, wall_clock=time.time):
    """Bounded polling for this workflow only; release ownership between each step."""
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout)
            or not 1 <= timeout <= 1800 or isinstance(poll, bool)
            or not isinstance(poll, (int, float)) or not math.isfinite(poll) or not .1 <= poll <= 10):
        raise ContractError('run requires timeout 1..1800 seconds and poll 0.1..10 seconds')
    started = clock()
    def before_dispatch():
        if clock()-started >= timeout:
            raise RunnerDeadline('runner deadline reached; no new POST')
    first = True
    while True:
        # Never hold this lock while sleeping; a different CLI delivers readiness.
        with Workflow(path, bridge, clock=wall_clock) as workflow:
            value = workflow.snapshot()
            if first:
                workflow.data['runner'] = {'timeout_s': timeout, 'poll_s': poll,
                                           'started_at': wall_clock(), 'exit_reason': None}
                workflow._save()
                first = False
            reason = None
            if value['status'] == 'succeeded':
                reason = 'succeeded'
            elif value['status'] in ('fault', 'unknown'):
                reason = 'blocked_'+value['status']
            elif clock()-started >= timeout:
                reason = 'timeout'
            else:
                try:
                    if value['status'] == 'waiting_ready':
                        job = workflow._job()
                        event = value['machines'][job['machine_id']]['event']
                        if event is not None and event['ready'] is True and event['batch_id'] == job['batch_id']:
                            workflow.dispatch(before_dispatch=before_dispatch)
                    elif value['status'] == 'waiting_reset':
                        workflow.reset(before_dispatch=before_dispatch)
                    else:
                        workflow.tick()
                except RunnerDeadline:
                    reason = 'timeout'
                    if workflow.data['operation'] != value['operation']:
                        workflow.data.update(status='unknown', reason='deadline after durable intent; retain original ID without replay')
                except (ContractError, TransportUnknown) as error:
                    if value['operation'] is None and workflow.data['operation'] is None:
                        # No mutation intent exists: this job is still provably unsent.
                        workflow.data.update(status='waiting_ready', reason=str(error))
                        reason = 'blocked_preflight'
                    else:
                        workflow.data.update(status='unknown', reason=str(error))
            status = workflow.data['status']
            if reason is None and status in ('succeeded', 'fault', 'unknown'):
                reason = 'succeeded' if status == 'succeeded' else 'blocked_'+status
            if reason is not None:
                workflow.data['runner'].update(exit_reason=reason, ended_at=wall_clock(),
                                                elapsed_s=max(0., clock()-started))
                workflow._save()
                return {'exit_reason': reason, 'workflow': workflow.snapshot()}
        sleep(min(poll, max(0., timeout-(clock()-started))))


def scene_template_jobs(manifest):
    """Translate a prepared task choice into the existing batch/goal inputs."""
    if manifest.get('factory_delivery') is not None:
        from cooperation_factory_scene import factory_template_jobs
        return factory_template_jobs(manifest)
    from cooperation_profiles import normalize_scene_profile
    profile = normalize_scene_profile(manifest.get('scene_profile'))
    count = 3 if profile['task'] == 'three_batch_transport' else 1
    batches = [str(uuid.uuid4()) for _ in range(count)]
    target = task_delivery_pose({}, manifest.get('delivery_pose'))
    goals = [target, target, {**target, 'x': target['x']+.7}] if count == 3 else [target]
    return batches, {batch: copy.deepcopy(goal) for batch, goal in zip(batches, goals)}, profile


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--bridge', default='http://127.0.0.1:9086')
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init')
    batches = init.add_mutually_exclusive_group(required=True)
    batches.add_argument('--batch', action='append', help='Legacy repeatable batch UUID')
    batches.add_argument('--batches', nargs='+', help='Nonempty ordered batch UUID list')
    batches.add_argument('--from-scene', type=Path, help='Generate fresh batches for the prepared scene task template')
    init.add_argument('--delivery-poses', type=Path, help='JSON object mapping batch UUIDs to {x,y,yaw}')
    init.add_argument('--delivery-approach-poses', type=Path,
                      help='JSON object mapping batch UUIDs to ordered approach pose lists')
    init.add_argument('--continuous-deliveries', type=Path,
                      help='JSON batch UUID to cargo/pickup arm/unload station binding; no world reset')
    init.add_argument('--machine', default='laundry-machine-1')
    event = sub.add_parser('event')
    event.add_argument('--file', type=Path, required=True)
    run = sub.add_parser('run')
    run.add_argument('--timeout', type=float, default=900.)
    run.add_argument('--poll', type=float, default=1.)
    for command in ('status', 'tick', 'dispatch', 'cancel', 'reset', 'recover'):
        sub.add_parser(command)
    args = parser.parse_args(argv)
    try:
        if args.command == 'run':
            result = run_workflow(args.ledger, LocalBridge(args.bridge), timeout=args.timeout, poll=args.poll)
            print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
            return 0 if result['exit_reason'] == 'succeeded' else 3 if result['exit_reason'] == 'timeout' else 2
        with Workflow(args.ledger, LocalBridge(args.bridge)) as workflow:
            if args.command == 'init':
                if args.from_scene:
                    if args.delivery_poses or args.delivery_approach_poses or args.continuous_deliveries:
                        raise ContractError('--from-scene uses its task template; use explicit batches for custom goals')
                    from cooperation_factory_scene import factory_template_approaches
                    scene = read_json(args.from_scene)
                    ids, goals, profile = scene_template_jobs(scene)
                    result = workflow.create(ids, args.machine, goals, scene_profile=profile,
                        delivery_approach_poses=factory_template_approaches(scene, ids))
                else:
                    result = workflow.create(args.batches if args.batches is not None else args.batch,
                                             args.machine, read_json(args.delivery_poses) if args.delivery_poses else None,
                        delivery_approach_poses=read_json(args.delivery_approach_poses) if args.delivery_approach_poses else None,
                        continuous_deliveries=read_json(args.continuous_deliveries) if args.continuous_deliveries else None)
            elif args.command == 'event':
                result = workflow.event(read_json(args.file))
            elif args.command in ('reset', 'recover'):
                result = workflow.reset(recover=args.command == 'recover')
            else:
                result = getattr(workflow, 'snapshot' if args.command == 'status' else args.command)()
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
        return 0
    except (ContractError, TransportUnknown, OSError, KeyError, TypeError, ValueError) as error:
        print(json.dumps({'error': str(error), 'outcome': 'blocked'}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
