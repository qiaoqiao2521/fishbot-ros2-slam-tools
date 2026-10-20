#!/usr/bin/env python3
"""Independent trace oracle for one continuous four-wheel ground/wall episode.

Wheel order is front-left, front-right, rear-left, rear-right.  This module reads
truth for scoring only.  A trace cannot establish collision flags, the absence
of pose writes, or the origin of forces: retain plant metadata and code review
as separate evidence.
"""
from __future__ import annotations

import math
from typing import Any


DEFAULT_CRITERIA = {
    'initial_window_s': .1,
    'initial_pitch_rad': .05,
    'handoff_min_pitch_rad': .1,
    'upright_tolerance_rad': .1,
    'minimum_rise_m': .2,
    'hold_s': .7,
    'stationary_linear_m_s': .01,
    'stationary_angular_rad_s': .02,
    'maximum_sample_gap_s': .05,
    'maximum_linear_speed_m_s': 2.0,
    'maximum_angular_speed_rad_s': 8.0,
    'position_allowance_m': .005,
    'orientation_allowance_rad': .02,
    'zero_pressure_pa': 1e-6,
}
STOP_PHASES = ('hold', 'stop')


def _finite(value: Any) -> bool:
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def _vector(row: dict[str, Any], key: str, size: int) -> bool:
    values = row.get(key)
    return isinstance(values, (list, tuple)) and len(values) == size and all(map(_finite, values))


def _valid(row: Any) -> bool:
    if not isinstance(row, dict) or not _finite(row.get('source_s')):
        return False
    for key, size in (('position_m', 3), ('quaternion_wxyz', 4),
                      ('velocity_m_s', 3), ('angular_velocity_rad_s', 3), ('pressure_pa', 4)):
        if not _vector(row, key, size):
            return False
    if not _finite(row.get('pitch_up_rad')) or not isinstance(row.get('phase'), str):
        return False
    contacts = row.get('wheel_contacts')
    if not isinstance(contacts, (list, tuple)) or len(contacts) != 4:
        return False
    for wheel in contacts:
        if not isinstance(wheel, dict) or any(
            not isinstance(wheel.get(key), int) or wheel[key] < 0 for key in ('floor', 'wall')
        ):
            return False
    q = row['quaternion_wxyz']
    if abs(sum(x * x for x in q) - 1.0) > .02 or min(row['pressure_pa']) < 0:
        return False
    # The local +X forward axis must agree with the independently recorded angle.
    w, x, y, z = q
    return abs(2 * (x * z - w * y) - math.sin(row['pitch_up_rad'])) <= .03


def _norm(vector: list[float]) -> float:
    return math.sqrt(sum(x * x for x in vector))


def _all_contact(row: dict[str, Any], surface: str) -> bool:
    other = 'floor' if surface == 'wall' else 'wall'
    return all(wheel[surface] > 0 and wheel[other] == 0 for wheel in row['wheel_contacts'])


def _upright(row: dict[str, Any], tolerance: float) -> bool:
    w, x, y, z = row['quaternion_wxyz']
    forward_z = min(1.0, max(-1.0, 2 * (x * z - w * y)))
    return _all_contact(row, 'wall') and math.acos(forward_z) <= tolerance


def score(rows: Any, *, expected: str = 'transition',
          criteria: dict[str, float] | None = None) -> dict[str, Any]:
    """Score a trace without mutating it or hiding incomplete evidence.

    ``passed`` for a no-pump negative control means the control behaved as
    expected.  ``task_motion_success`` remains false for that control.
    Malformed rows and source-clock gaps yield ``unknown``; usable rows still
    produce metrics for diagnosis.  Separate calls have no shared state.
    """
    c = dict(DEFAULT_CRITERIA)
    warnings: list[str] = []
    for key, value in (criteria or {}).items():
        if key in c and _finite(value) and value >= 0:
            c[key] = value
        elif key in c:
            warnings.append(f'Invalid criterion {key}; retained default')
    if expected not in ('transition', 'no_pump'):
        return {'status': 'unknown', 'expected': expected, 'task_motion_success': False,
                'checks': {'supported_expectation': None}, 'metrics': {},
                'warnings': ['Expected transition or no_pump']}
    if not isinstance(rows, (list, tuple)):
        rows = []
        warnings.append('Trace must contain a sequence of source samples')
    valid = [row for row in rows if _valid(row)]
    invalid = len(rows) - len(valid)
    if invalid:
        warnings.append(f'{invalid} malformed sample(s); retained usable samples')
    monotonic = all(b['source_s'] > a['source_s'] for a, b in zip(valid, valid[1:]))
    gaps = [b['source_s'] - a['source_s'] for a, b in zip(valid, valid[1:])]
    max_gap = max(gaps, default=0.0)
    starts_in_window = bool(valid) and 0 <= valid[0]['source_s'] <= c['initial_window_s']
    complete = starts_in_window and not invalid and monotonic and max_gap <= c['maximum_sample_gap_s'] + 1e-9
    if valid and not starts_in_window:
        warnings.append('Missing initial source-time window')
    if not monotonic:
        warnings.append('Source timestamps are nonmonotonic; samples were not reordered')
    if max_gap > c['maximum_sample_gap_s'] + 1e-9:
        warnings.append('Source sampling gap exceeds the declared limit')

    continuous = True
    max_step = max_angle_step = 0.0
    for a, b in zip(valid, valid[1:]):
        dt = b['source_s'] - a['source_s']
        step = math.dist(a['position_m'], b['position_m'])
        dot = abs(sum(x * y for x, y in zip(a['quaternion_wxyz'], b['quaternion_wxyz'])))
        angle = 2 * math.acos(min(1.0, dot))
        max_step, max_angle_step = max(max_step, step), max(max_angle_step, angle)
        if dt <= 0:
            continue
        linear = min(c['maximum_linear_speed_m_s'], max(_norm(a['velocity_m_s']), _norm(b['velocity_m_s'])))
        angular = min(c['maximum_angular_speed_rad_s'],
                      max(_norm(a['angular_velocity_rad_s']), _norm(b['angular_velocity_rad_s'])))
        if (step > linear * dt + c['position_allowance_m'] + 1e-9
                or angle > angular * dt + c['orientation_allowance_rad'] + 1e-9):
            continuous = False

    first = valid[0] if valid else None
    # A free vehicle may need a few gravity steps to load its wheels. Preserve
    # those source samples; do not reset the clock to a synthetic settled pose.
    initial_index = next((i for i, row in enumerate(valid)
                          if 0 <= row['source_s'] <= c['initial_window_s']
                          and _all_contact(row, 'floor')
                          and abs(row['pitch_up_rad']) <= c['initial_pitch_rad']
                          and max(row['pressure_pa']) <= c['zero_pressure_pa']), None)
    initial = initial_index is not None and all(
        abs(row['pitch_up_rad']) <= c['initial_pitch_rad']
        and max(row['pressure_pa']) <= c['zero_pressure_pa']
        and all(wheel['wall'] == 0 for wheel in row['wheel_contacts'])
        for row in valid[:initial_index + 1])
    upright = next((i for i, row in enumerate(valid)
                    if _upright(row, c['upright_tolerance_rad'])), None)
    handoff = next((i for i, row in enumerate(valid)
                    if (upright is None or i < upright)
                    and row['pitch_up_rad'] > c['handoff_min_pitch_rad']
                    and row['pitch_up_rad'] < math.pi / 2 - c['upright_tolerance_rad']
                    and all(w['wall'] > 0 for w in row['wheel_contacts'][:2])
                    and all(w['floor'] > 0 for w in row['wheel_contacts'][2:])), None)
    rise = 0.0
    hold_start = None
    longest_hold = final_hold = 0.0
    completion_s = None
    if upright is not None:
        reference_z = valid[upright]['position_m'][2]
        for row in valid[upright:]:
            all_wall = _upright(row, c['upright_tolerance_rad'])
            current_rise = row['position_m'][2] - reference_z
            if all_wall:
                rise = max(rise, current_rise)
            qualified = (row['phase'] in STOP_PHASES
                         and all_wall and current_rise + 1e-9 >= c['minimum_rise_m']
                         and _norm(row['velocity_m_s']) <= c['stationary_linear_m_s']
                         and _norm(row['angular_velocity_rad_s']) <= c['stationary_angular_rad_s'])
            if not qualified:
                hold_start, final_hold = None, 0.0
                continue
            if hold_start is None:
                hold_start = row['source_s']
            final_hold = row['source_s'] - hold_start
            longest_hold = max(longest_hold, final_hold)
            if completion_s is None and final_hold + 1e-9 >= c['hold_s']:
                completion_s = row['source_s']

    zero_pressure = bool(valid) and all(max(row['pressure_pa']) <= c['zero_pressure_pa'] for row in valid)
    common = {'valid_source_samples': complete, 'starts_on_floor_without_pressure': initial,
              'bounded_pose_increments': continuous if monotonic else None}
    if expected == 'no_pump':
        checks = {**common, 'pressure_remains_zero': zero_pressure,
                  'does_not_complete_transition': completion_s is None}
        motion_success = False
    else:
        checks = {**common, 'front_wall_rear_floor_handoff': handoff is not None,
                  'all_wheels_wall_and_upright': upright is not None,
                  'rises_after_upright': rise + 1e-9 >= c['minimum_rise_m'],
                  'final_stationary_wall_hold': final_hold + 1e-9 >= c['hold_s']}
        motion_success = complete and all(value is True for value in checks.values())
    status = 'unknown' if not complete else ('passed' if all(value is True for value in checks.values()) else 'failed')
    return {'status': status, 'expected': expected, 'task_motion_success': motion_success,
            'checks': checks,
            'metrics': {'samples': len(valid), 'invalid_samples': invalid,
                        'source_start_s': first['source_s'] if first else None,
                        'initial_floor_source_s': valid[initial_index]['source_s'] if initial_index is not None else None,
                        'source_end_s': valid[-1]['source_s'] if valid else None,
                        'maximum_sample_gap_s': max_gap, 'maximum_position_step_m': max_step,
                        'maximum_orientation_step_rad': max_angle_step,
                        'handoff_source_s': valid[handoff]['source_s'] if handoff is not None else None,
                        'upright_source_s': valid[upright]['source_s'] if upright is not None else None,
                        'rise_after_upright_m': rise, 'longest_stationary_wall_hold_s': longest_hold,
                        'final_stationary_wall_hold_s': final_hold, 'first_completion_source_s': completion_s},
            'criteria': c, 'warnings': warnings,
            'evidence_scope': 'Trace-only motion score; plant construction, force origins, and the matched no-pump drive profile require separate review'}
