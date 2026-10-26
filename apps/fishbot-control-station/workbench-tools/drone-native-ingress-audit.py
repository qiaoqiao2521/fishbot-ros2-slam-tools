#!/usr/bin/env python3
"""Read recorded native reception/control evidence; never sends a command."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path


def counts(values):
    return {str(key): value for key, value in Counter(map(int, values)).items()}


def span(values):
    values = list(values)
    return {'count': len(values), 'min': min(values), 'max': max(values)} if values else None


def same_pva(left, left_prefix, right, right_prefix):
    for field in ('position', 'velocity', 'acceleration'):
        for axis in range(3):
            a, b = float(left[f'{left_prefix}{field}[{axis}]']), float(right[f'{right_prefix}{field}[{axis}]'])
            if not (a == b or (math.isnan(a) and math.isnan(b))):
                return False
    return True


def associate(control, receptions):
    """All stamp+PVA matches in the recorded file, without selecting an ambiguous row."""
    stamps = [r for r in receptions if r['decision'] == 5
              and r['setpoint_timestamp'] == control['raw_input_timestamp']]
    return [r for r in stamps if same_pva(control, 'raw_', r, 'decoded_')], len(stamps)


def sequence_regressions(receptions):
    previous, regressions = {}, 0
    for row in receptions:
        channel, sequence = row['receiver_channel'], row['receiver_sequence']
        if channel in previous and sequence <= previous[channel]:
            regressions += 1
        previous[channel] = sequence
    return regressions


def rows(data):
    return [{key: value[index].item() for key, value in data.items()}
            for index in range(len(data['timestamp']))]


def audit_file(path, run):
    from pyulog import ULog
    log = ULog(str(path))
    datasets = {d.name: d.data for d in log.data_list if d.multi_id == 0}
    result = {'file': str(path.relative_to(run)), 'dropout_records': len(log.dropouts),
              'topic_counts': {name: len(data['timestamp']) for name, data in datasets.items()
                               if name in ('mavlink_setpoint_ingress', 'position_control_handoff',
                                           'trajectory_setpoint', 'vehicle_status', 'vehicle_command')}}
    status = datasets.get('vehicle_status')
    command = datasets.get('vehicle_command')
    result['arming_states'] = counts(status['arming_state']) if status is not None else None
    result['arm_disarm_command_count'] = int(sum(command['command'] == 400)) if command is not None else None
    if 'mavlink_setpoint_ingress' not in datasets or 'position_control_handoff' not in datasets:
        result['native_chain'] = 'missing_topic'
        return result
    ingress = rows(datasets['mavlink_setpoint_ingress'])
    control = rows(datasets['position_control_handoff'])
    result['decisions'] = counts(r['decision'] for r in ingress)
    result['sender_systems'] = counts(r['sender_system'] for r in ingress)
    result['sender_components'] = counts(r['sender_component'] for r in ingress)
    result['receiver_channels'] = counts(r['receiver_channel'] for r in ingress)
    result['wire_frames'] = counts(r['coordinate_frame'] for r in ingress)
    result['wire_masks'] = counts(r['type_mask'] for r in ingress)
    result['wire_time_boot_ms'] = span(r['wire_time_boot_ms'] for r in ingress)
    result['handler_elapsed_native_us'] = span(r['timestamp']-r['receive_timestamp'] for r in ingress)
    result['native_receive_us'] = span(r['receive_timestamp'] for r in ingress)
    published = [r for r in ingress if r['decision'] == 5]
    result['repeated_published_stamps'] = {str(k): n for k, n in
        Counter(r['setpoint_timestamp'] for r in published).items() if n > 1}
    result['nonincreasing_receiver_sequences'] = sequence_regressions(ingress)
    matches, delay, no_match, ambiguous, stamp_payload_mismatch, future = [], [], 0, 0, 0, 0
    for c in control:
        if not c['raw_input_available'] or not c['input_updated']:
            continue
        candidates, stamp_count = associate(c, ingress)
        payload_matched = bool(candidates)
        future += sum(r['receive_timestamp'] > c['timestamp'] for r in candidates)
        candidates = [r for r in candidates if r['receive_timestamp'] <= c['timestamp']]
        if not candidates:
            no_match += 1
            stamp_payload_mismatch += bool(stamp_count) and not payload_matched
        elif len(candidates) > 1:
            ambiguous += 1
        else:
            r = candidates[0]
            matches.append({'control_timestamp': c['timestamp'], 'raw_timestamp': c['raw_input_timestamp'],
                            'receiver_channel': r['receiver_channel'], 'receiver_sequence': r['receiver_sequence'],
                            'message_sequence': r['message_sequence']})
            delay.append(c['timestamp']-r['receive_timestamp'])
    result['new_raw_updates'] = sum(bool(c['input_updated']) for c in control)
    result['recorded_stamp_and_pva_matches'] = len(matches)
    result['unmatched_new_raw'] = no_match
    result['stamp_present_but_pva_mismatch'] = stamp_payload_mismatch
    result['future_compatible_receptions_excluded'] = future
    result['ambiguous_new_raw'] = ambiguous
    result['receive_to_control_native_us'] = span(delay)
    result['recorded_matches'] = matches
    result['ground_diagnostics'] = {name: counts(c[name] for c in control) if control and name in control[0] else None
        for name in ('ground_state_evaluated', 'not_taken_off', 'flying_ground_contact',
                     'ground_override', 'rampup_acceleration_cleared')}
    result['ground_override_pva_rows'] = sum(
        all(math.isnan(c[f'used_{field}[{axis}]']) for field in ('position', 'velocity') for axis in range(3))
        and [c[f'used_acceleration[{axis}]'] for axis in range(3)] == [0., 0., 100.] for c in control)
    result['native_chain'] = 'recorded_matches_only'
    return result


def audit(run):
    result = {'run': str(run), 'native_files': [], 'warnings': [],
              'clock_scope': 'native HRT differences only; sender host/wire clocks not calibrated',
              'unique_rpc_adoption': 'not_proven', 'flight_accepted': False,
              'logging_completeness': 'not_proven'}
    for path in sorted((run/'sitl/log').glob('**/*.ulg')):
        try:
            native = audit_file(path, run)
            result['native_files'].append(native)
            if native['native_chain'] == 'missing_topic':
                result['warnings'].append({'file': str(path), 'error': 'Required native topic missing; no chain conclusion'})
        except Exception as error:
            result['warnings'].append({'file': str(path), 'error': type(error).__name__+': '+str(error)})
    if not result['native_files']:
        result['warnings'].append({'error': 'No readable native ULog; no native chain conclusion'})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = audit(args.run.resolve())
    text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    if args.output:
        args.output.write_text(text)
    print(text, end='')


if __name__ == '__main__':
    main()
