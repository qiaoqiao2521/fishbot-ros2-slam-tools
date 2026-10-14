"""Bounded acceptance-only station faults, anchored to an accepted Dock UUID.

This adapter keeps captured stamps and sequences. It neither commands motion
nor owns a scheduler. RGB occlusion uses the same window in the render model;
the detector must still decide visibility from pixels.
"""
import copy
import math
import re
import time
import uuid


KINDS = {'none', 'short_occlusion', 'long_occlusion', 'delay', 'replay_identity'}


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f'{label} must be finite')
    return float(value)


def normalize_fault_config(config=None):
    config = {} if config is None else config
    if not isinstance(config, dict) or set(config) - {
            'schema', 'kind', 'duration_wall_s', 'delay_wall_s', 'delay_source_s'}:
        raise ValueError('unknown observation fault configuration')
    if type(config.get('schema', 1)) is not int or config.get('schema', 1) != 1:
        raise ValueError('observation fault schema must be 1')
    kind = config.get('kind', 'none')
    if kind not in KINDS:
        raise ValueError('unknown observation fault kind')
    default_duration = .1 if kind == 'short_occlusion' else .8 if kind == 'long_occlusion' else 0.
    result = {'schema': 1, 'kind': kind,
              'duration_wall_s': _finite(config.get('duration_wall_s', default_duration), 'duration'),
              'delay_wall_s': _finite(config.get('delay_wall_s', 0.), 'wall delay'),
              'delay_source_s': _finite(config.get('delay_source_s', 0.), 'source delay')}
    if any(not 0 <= result[key] <= 5. for key in ('duration_wall_s', 'delay_wall_s', 'delay_source_s')):
        raise ValueError('fault intervals must remain within 0..5 seconds')
    if kind in ('short_occlusion', 'long_occlusion') and result['duration_wall_s'] <= 0:
        raise ValueError('occlusion requires a positive duration')
    if kind == 'long_occlusion' and result['duration_wall_s'] < .8:
        raise ValueError('long occlusion must last at least .8 wall seconds')
    if kind == 'delay' and result['delay_wall_s'] == result['delay_source_s'] == 0:
        raise ValueError('delay requires a positive interval')
    if kind not in ('short_occlusion', 'long_occlusion') and result['duration_wall_s'] != 0:
        raise ValueError('duration applies only to occlusion')
    if kind != 'delay' and (result['delay_wall_s'] != 0 or result['delay_source_s'] != 0):
        raise ValueError('delays apply only to delay faults')
    return result


class FaultInjector:
    """One trigger, one bounded saved frame, no implicit repeat across episodes."""
    def __init__(self, config=None, identity=None):
        self.config = normalize_fault_config(config)
        self.identity = {key: (identity or {}).get(key) for key in ('scene_sha256', 'manifest_sha256')}
        self.begin_episode(None)

    def begin_episode(self, episode_id):
        if episode_id is not None:
            uuid.UUID(episode_id)
        self.episode_id = episode_id
        self.accepted_goal = None
        self.trigger_stamp = None
        self.trigger_wall_time = self.trigger_monotonic = None
        self.start_wall = self.start_source = self.started_wall_time = None
        self.saved = self.previous = None
        self.delay_released = False
        self.replay_index = 0
        self.normal_between_faults = False
        self.counts = {'input': 0, 'output': 0, 'dropped': 0, 'mutated': 0, 'triggers': 0}

    def trigger(self, payload):
        required = {'scene_sha256', 'manifest_sha256', 'episode_id', 'native_goal_uuid', 'source_stamp'}
        if not isinstance(payload, dict) or set(payload) != required:
            raise ValueError('fault trigger fields do not match the contract')
        if any(payload[key] != value for key, value in self.identity.items()):
            raise ValueError('fault trigger source does not match the frozen scene')
        if self.episode_id is None or payload['episode_id'] != self.episode_id:
            raise ValueError('fault trigger belongs to another episode')
        goal = payload['native_goal_uuid']
        if not isinstance(goal, str) or not re.fullmatch('[0-9a-f]{32}', goal):
            raise ValueError('fault trigger needs the accepted native goal UUID')
        stamp = _finite(payload['source_stamp'], 'trigger source stamp')
        if stamp <= 0:
            raise ValueError('fault trigger source stamp must be positive')
        if self.accepted_goal is not None:
            if goal == self.accepted_goal:
                return False
            raise ValueError('another native goal already owns this episode fault')
        self.accepted_goal, self.trigger_stamp = goal, stamp
        self.trigger_wall_time, self.trigger_monotonic = time.time(), time.monotonic()
        self.counts['triggers'] += 1
        return True

    def _window(self, *, wall_time, source_stamp, episode_id, moving):
        wall_time = _finite(wall_time, 'fault wall time')
        source_stamp = _finite(source_stamp, 'fault source stamp')
        if episode_id != self.episode_id or self.accepted_goal is None:
            return None
        if self.start_wall is None:
            if not moving or source_stamp < self.trigger_stamp:
                return None
            self.start_wall, self.start_source = wall_time, source_stamp
            self.started_wall_time = time.time()
        return max(0., wall_time-self.start_wall), max(0., source_stamp-self.start_source)

    def occlusion_active(self, **context):
        window = self._window(**context)
        return (window is not None and self.config['kind'] in ('short_occlusion', 'long_occlusion')
                and window[0] < self.config['duration_wall_s'])

    def apply(self, sample, *, synthetic_occlusion=True, **context):
        if sample is None:
            return []
        value = copy.deepcopy(sample)
        self.counts['input'] += 1
        window = self._window(**context)
        if window is None or self.config['kind'] == 'none':
            result = [value]
        elif self.config['kind'] in ('short_occlusion', 'long_occlusion'):
            if synthetic_occlusion and window[0] < self.config['duration_wall_s']:
                value.update(detected=False, confidence=0., reason='synthetic_occlusion', relative=None, covariance=None)
                self.counts['mutated'] += 1
            result = [value]
        elif self.config['kind'] == 'delay' and not self.delay_released:
            if self.saved is None:
                self.saved = copy.deepcopy(value)
            if window[0] < self.config['delay_wall_s'] or window[1] < self.config['delay_source_s']:
                self.counts['dropped'] += 1
                result = []
            else:
                result, self.saved = [self.saved], None
                self.delay_released = True
        elif self.config['kind'] == 'replay_identity' and self.replay_index < 6:
            if self.normal_between_faults:
                result = [value]
                self.normal_between_faults = False
            else:
                index = self.replay_index
                if index in (0, 1):
                    # Both packets retain an actual previous source epoch. The
                    # second is older again, not a fabricated current stamp.
                    altered = copy.deepcopy(self.saved or self.previous or value)
                else:
                    altered = copy.deepcopy(value)
                    fields = {2: ('episode_id', str(uuid.UUID(int=0))),
                              3: ('frame_id', 'wrong_camera_frame'),
                              4: ('station_id', 'wrong_station'),
                              5: ('manifest_sha256', '0'*64)}
                    key, replacement = fields[index]
                    altered[key] = replacement
                result = [altered]
                if self.saved is None:
                    self.saved = copy.deepcopy(self.previous or value)
                self.replay_index += 1
                self.normal_between_faults = True
                self.counts['mutated'] += 1
        else:
            result = [value]
        self.previous = copy.deepcopy(value)
        self.counts['output'] += len(result)
        return result

    def status(self):
        return {'config': dict(self.config), 'episode_id': self.episode_id,
                'native_goal_uuid': self.accepted_goal, 'trigger_source_stamp': self.trigger_stamp,
                'trigger_wall_time': self.trigger_wall_time, 'trigger_monotonic': self.trigger_monotonic,
                'started_wall_time': self.started_wall_time, 'started_monotonic': self.start_wall,
                'started_source_stamp': self.start_source,
                'delay_released': self.delay_released, 'replay_packets': self.replay_index,
                'counts': dict(self.counts), 'acceptance_only': True}
