"""Source-step external-force pulses for the existing Physics owner.

Call before_step(context), the owner's normal mj_step, then after_step(). This
adapter writes only its additive xfrc_applied force contribution. It neither
steps a model nor dispatches motion, schedules cases, or changes the timestep.
"""
from __future__ import annotations

import copy
import math
import re


_CONTEXT = ('world_session_id', 'episode_id', 'task_id', 'native_goal_uuid', 'stage')
_EVENT = set(_CONTEXT) | {'event_id', 'body_name', 'force_world_n', 'duration_source_s'}
_TERMINAL = {'completed', 'dearmed', 'overrun'}


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{label} must be finite')
    return float(value)


def _vector(value, label):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f'{label} must contain three finite world-axis values')
    return [_number(item, label) for item in value]


def _context(value):
    if not isinstance(value, dict):
        raise ValueError('Force event requires an explicit current owner context')
    result = {}
    for key in _CONTEXT:
        item = value.get(key)
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f'{key} must be a nonempty string')
        result[key] = item
    if re.fullmatch(r'[0-9a-f]{32}', result['native_goal_uuid']) is None:
        raise ValueError('native_goal_uuid must identify the accepted native Goal')
    return result


class ForceImpulse:
    """Maintain independent event IDs and additive forces in one native model.

    A final fractional pulse uses its average force over the full native step.
    effective_duration_source_s measures force-equivalent duration; the actual
    source_window_s includes that complete last step. Actual Ns are recorded
    only when data.time advances. Capture the adapter beside the native state.
    """
    def __init__(self, model, data):
        self.model, self.data = model, data
        self.events = {}
        self._pending = None

    def _body(self, name):
        if not isinstance(name, str) or not name.strip():
            raise ValueError('body_name must be a nonempty native body name')
        try:
            body = int(self.model.body(name).id)
        except (KeyError, ValueError, TypeError) as error:
            raise ValueError(f'Unknown native force body: {name}') from error
        if body <= 0:
            raise ValueError('World body cannot receive a ForceImpulse')
        return body

    def _event(self, value):
        if not isinstance(value, dict) or set(value) != _EVENT:
            raise ValueError('Force event fields do not match the explicit event contract')
        event = {**_context(value)}
        for key in ('event_id', 'body_name'):
            if not isinstance(value[key], str) or not value[key].strip():
                raise ValueError(f'{key} must be a nonempty string')
            event[key] = value[key]
        self._body(event['body_name'])
        event['force_world_n'] = _vector(value['force_world_n'], 'force_world_n')
        event['duration_source_s'] = _number(value['duration_source_s'], 'duration_source_s')
        if event['duration_source_s'] <= 0:
            raise ValueError('duration_source_s must be positive')
        return event

    def _time(self):
        return _number(float(self.data.time), 'native source time')

    def _delta(self, name, force, sign=1.):
        body = self._body(name)
        for axis in range(3):
            self.data.xfrc_applied[body][axis] += sign*force[axis]

    def offer(self, event, *, context):
        """Bind one event now; an invalid/conflicting event changes nothing else."""
        event = self._event(event)
        if _context(context) != {key:event[key] for key in _CONTEXT}:
            raise ValueError('Force event does not match the current accepted Goal and stage')
        identity = event['event_id']
        if identity in self.events:
            if self.events[identity]['event'] != event:
                raise ValueError('Force event ID is already bound to different parameters')
            return self.status(identity)
        self.events[identity] = {'event':event, 'state':'armed', 'effective_duration_source_s':0.,
            'source_window_s':0., 'impulse_world_ns':[0.,0.,0.], 'source_steps':0,
            'started_source_s':None, 'last_source_s':None, 'last_step':None, 'reason':None}
        return self.status(identity)

    def before_step(self, context):
        """Add this step's owned average force before the owner's normal mj_step.

        Repeated calls before source progression do not add the force twice.
        If the previous after_step was omitted, reconcile it here first.
        """
        current = _context(context)
        now = self._time()
        if self._pending is not None:
            if now < self._pending['source_start_s']:
                raise ValueError('Native source time regressed while a force step was pending')
            if now > self._pending['source_start_s']:
                self.after_step()
            elif all({key:self.events[identity]['event'][key] for key in _CONTEXT} == current
                     for identity in self._pending['contributions']):
                return self.status()
        for identity, record in self.events.items():
            if record['state'] not in _TERMINAL and {key:record['event'][key] for key in _CONTEXT} != current:
                self.dearm(identity, reason='owner_context_changed')
        if self._pending is not None:
            return self.status()
        dt = _number(float(self.model.opt.timestep), 'native timestep')
        if dt <= 0:
            raise ValueError('native timestep must be positive')
        contributions = {}
        for identity, record in self.events.items():
            if record['state'] in _TERMINAL:
                continue
            event = record['event']
            remaining = event['duration_source_s']-record['effective_duration_source_s']
            if remaining <= 0:
                record.update(state='completed' if remaining == 0 else 'dearmed',
                              reason=None if remaining == 0 else 'invalid_remaining_source_duration')
                continue
            effective = min(dt, remaining)
            fraction = effective/dt
            force = [value*fraction for value in event['force_world_n']]
            contributions[identity] = {'body_name':event['body_name'], 'force_world_n':force,
                                       'fraction':fraction, 'effective_step_source_s':effective}
        # Validate all native targets before adding any contribution.
        for value in contributions.values():
            self._body(value['body_name'])
        for identity, value in contributions.items():
            self._delta(value['body_name'], value['force_world_n'])
            record = self.events[identity]
            record['state'] = 'active'
            if record['started_source_s'] is None:
                record['started_source_s'] = now
        if contributions:
            self._pending = {'source_start_s':now, 'native_step_source_s':dt,
                             'contributions':contributions}
        return self.status()

    def after_step(self):
        """Integrate observed source progression and remove only owned forces."""
        if self._pending is None:
            return self.status()
        pending = self._pending
        now = self._time();elapsed = now-pending['source_start_s']
        if elapsed <= 0:
            raise ValueError('Force step has no positive native source progression')
        dt = pending['native_step_source_s']
        overrun = elapsed > dt+max(1e-12, dt*1e-9)
        for identity, contribution in pending['contributions'].items():
            record = self.events[identity];force = contribution['force_world_n']
            self._delta(contribution['body_name'], force, -1.)
            record['impulse_world_ns'] = [a+f*elapsed for a,f in zip(record['impulse_world_ns'],force)]
            record['effective_duration_source_s'] += contribution['fraction']*elapsed
            record['source_window_s'] += elapsed
            record['source_steps'] += 1;record['last_source_s'] = now
            record['last_step'] = {'source_start_s':pending['source_start_s'], 'source_end_s':now,
                'native_step_source_s':dt, 'actual_source_s':elapsed,
                'average_force_world_n':list(force), 'last_step_fraction':contribution['fraction'],
                'effective_source_s':contribution['fraction']*elapsed,
                'partial_step_averaging':contribution['fraction'] < 1.}
            if overrun:
                record.update(state='overrun', reason='More than one declared native step elapsed before reconciliation')
            elif record['effective_duration_source_s'] >= record['event']['duration_source_s']-max(1e-12,dt*1e-9):
                record['state'] = 'completed'
        self._pending = None
        return self.status()

    def dearm(self, event_id=None, *, reason='dearmed'):
        """Account for any completed step, then withdraw only selected contributions."""
        if self._pending is not None and self._time() > self._pending['source_start_s']:
            self.after_step()
        if event_id is not None and event_id not in self.events:
            raise ValueError('Unknown force event ID')
        identities = list(self.events) if event_id is None else [event_id]
        for identity in identities:
            if self._pending is not None:
                contribution = self._pending['contributions'].pop(identity, None)
                if contribution is not None:
                    self._delta(contribution['body_name'], contribution['force_world_n'], -1.)
            record = self.events[identity]
            if record['state'] not in _TERMINAL:
                record.update(state='dearmed',reason=str(reason))
        if self._pending is not None and not self._pending['contributions']:
            self._pending = None
        return self.status(event_id)

    def capture_state(self):
        """JSON-ready application state; native xfrc_applied stays in the native snapshot."""
        return {'schema':1, 'source_s':self._time(), 'events':copy.deepcopy(self.events),
                'pending':copy.deepcopy(self._pending)}

    def restore_state(self, value, *, context, wrench_included=True):
        """Restore beside native state on a fresh/dearmed adapter.

        wrench_included=True means the native snapshot already contains the
        saved contributions: do not add them again. False is for application-
        only restoration onto baseline forces. A changed owner deactivates the
        restored event and removes its saved contribution when included.
        """
        if self._pending is not None:
            raise ValueError('Dearm current adapter contributions before replacing application state')
        if not isinstance(value,dict) or value.get('schema') != 1 or not isinstance(value.get('events'),dict):
            raise ValueError('Invalid force application state')
        if type(wrench_included) is not bool:
            raise ValueError('wrench_included must explicitly describe the native snapshot')
        current = _context(context);saved = copy.deepcopy(value)
        if not math.isclose(_number(saved['source_s'],'saved source time'),self._time(),abs_tol=1e-9,rel_tol=1e-12):
            raise ValueError('Force application state and native state source times differ')
        for identity,record in saved['events'].items():
            event = self._event(record['event'])
            if identity != event['event_id'] or record.get('state') not in _TERMINAL | {'armed','active'}:
                raise ValueError('Invalid restored event identity or state')
            record['event'] = event
            for key in ('effective_duration_source_s','source_window_s'):
                if _number(record[key],key) < 0:
                    raise ValueError('Restored force durations must be nonnegative')
            effective = record['effective_duration_source_s']
            if record['state'] not in _TERMINAL and effective >= event['duration_source_s']:
                raise ValueError('Restored active force duration has no positive remaining interval')
            if effective > record['source_window_s']+max(1e-12,effective*1e-9):
                raise ValueError('Restored effective force duration exceeds its source window')
            record['impulse_world_ns'] = _vector(record['impulse_world_ns'],'restored impulse')
        pending = saved.get('pending')
        if pending is not None:
            start = _number(pending['source_start_s'],'pending source time')
            dt = _number(pending['native_step_source_s'],'pending native timestep')
            if dt <= 0 or start > self._time() or self._time()-start > dt+max(1e-12,dt*1e-9):
                raise ValueError('Restored pending step does not match native source time')
            if not isinstance(pending['contributions'],dict) or not pending['contributions']:
                raise ValueError('Restored pending contributions are missing')
            for identity,contribution in pending['contributions'].items():
                record = saved['events'][identity]
                if record['state'] != 'active' or contribution['body_name'] != record['event']['body_name']:
                    raise ValueError('Restored contribution belongs to another event or body')
                force = _vector(contribution['force_world_n'],'pending force')
                fraction = _number(contribution['fraction'],'pending fraction')
                if not 0 < fraction <= 1 or any(not math.isclose(f,e*fraction,rel_tol=1e-12,abs_tol=1e-12)
                        for f,e in zip(force,record['event']['force_world_n'])):
                    raise ValueError('Restored force contribution is inconsistent')
                remaining = record['event']['duration_source_s']-record['effective_duration_source_s']
                if not math.isclose(fraction,min(dt,remaining)/dt,rel_tol=1e-9,abs_tol=1e-12):
                    raise ValueError('Restored pending force exceeds or differs from its remaining interval')
                contribution['force_world_n'] = force
        self.events,self._pending = saved['events'],pending
        if pending is not None and not wrench_included:
            for contribution in pending['contributions'].values():
                self._delta(contribution['body_name'],contribution['force_world_n'])
        for identity,record in self.events.items():
            if record['state'] not in _TERMINAL and {key:record['event'][key] for key in _CONTEXT} != current:
                self.dearm(identity,reason='restored_owner_context_changed')
        return self.status()

    def status(self, event_id=None):
        if event_id is not None:
            if event_id not in self.events:
                raise ValueError('Unknown force event ID')
            return copy.deepcopy(self.events[event_id])
        return {'events':copy.deepcopy(self.events),'step_pending':self._pending is not None,
                'clock':'native_source_time','last_partial_step':'average_force_over_unchanged_native_timestep'}
