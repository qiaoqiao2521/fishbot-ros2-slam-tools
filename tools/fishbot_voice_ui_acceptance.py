#!/usr/bin/env python3
"""Explicitly test one UI voice task and cancel in an existing isolated runtime.

Reuses the manual acceptance's read-only observer and physical quiet scorer.
No runtime is launched, no audio is recorded, and no lease is acquired.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time
import uuid
from urllib.error import HTTPError, URLError

from fishbot_manual_acceptance import (ROOT, LIMITS, Api, Recording, RuntimeObservation,
    require_loopback, quiet_result, source_snapshot)


def manual_preflight(runtime, state, read, *, deadline=None, evidence=None, wait=True):
    """Wait only for known admission work, before generating any action body."""
    capability = next((value for value in runtime.get('capabilities', [])
                       if value.get('id') == 'teleop' and value.get('protocol') == 'manual_lease_v1'), None)
    if capability is None:
        return {'required': False, 'reason': 'manual_capability_absent'}
    map_id = (state.get('map_rules') or {}).get('map_id')
    if (capability.get('profile_id') != 'passage_manual' or capability.get('available') is not True
            or capability.get('limits') != LIMITS or not map_id
            or state['mission'].get('status') not in {'idle', 'completed', 'succeeded', 'failed', 'canceled'}
            or state['mission'].get('cleanup_state') == 'unresolved'):
        raise RuntimeError('Manual capability or original task is unresolved')
    end = min(time.monotonic()+15., float('inf') if deadline is None else deadline)
    original_lease_id = ...
    while time.monotonic() < end:
        status = read('manual/status')
        if evidence is not None:
            evidence.append({'epoch': time.time(), 'steady_time': time.monotonic(), 'status': status})
        owner, recovery = status.get('native_owner') or {}, status.get('idle_recovery') or {}
        if (status.get('runtime_instance_id') != runtime.get('instance_id')
                or status.get('profile_id') != 'passage_manual' or status.get('map_id') != map_id
                or status.get('limits') != LIMITS or status.get('available') is not True
                or status.get('stop_latched') is not False or 'active_lease_id' not in status
                or not {'task_id', 'native_goal_id', 'status', 'terminal'} <= owner.keys()
                or owner['terminal'] is not True or owner['task_id'] != state['mission'].get('id')
                or owner['native_goal_id'] != state['mission'].get('native_goal_id')
                or owner['status'] != ('succeeded' if state['mission']['status'] == 'completed' else state['mission']['status'])
                or recovery.get('state') == 'unknown'):
            raise RuntimeError('Manual owner identity, limits or explicit STOP is unresolved')
        lease_id = status['active_lease_id']
        if original_lease_id is ...:
            original_lease_id = lease_id
        if lease_id != original_lease_id:
            raise RuntimeError('Original manual lease changed during admission')
        lease = None
        if lease_id is not None:
            if str(uuid.UUID(lease_id)) != lease_id:
                raise RuntimeError('Manual lease original identity is invalid')
            lease = read('manual/'+lease_id)['lease']
            if (lease.get('lease_id') != lease_id or lease.get('runtime_instance_id') != runtime['instance_id']
                    or lease.get('map_id') != map_id or lease.get('profile_id') != 'passage_manual'
                    or lease.get('state') not in {'released', 'expired', 'stopped'}
                    or lease.get('guard_stop_acknowledged') is not True
                    or (lease.get('quiet') or {}).get('confirmed') is not True):
                raise RuntimeError('Original manual lease cleanup is unresolved')
        if status.get('can_acquire') is True and status.get('reason') is None:
            quiet = status.get('quiet') or {}
            finite = lambda value: type(value) in (int, float) and math.isfinite(value)
            if (quiet.get('confirmed') is not True or not all(finite(quiet.get(key)) for key in
                    ('duration_s', 'receive_age_s', 'source_age_s', 'source_stamp'))
                    or quiet['duration_s'] < .7 or not 0 <= quiet['receive_age_s'] <= .25
                    or not -.05 <= quiet['source_age_s'] <= .25):
                raise RuntimeError('Manual owner fresh continuous quiet is unconfirmed')
            if time.monotonic() >= end:
                break
            return {'required': True, 'status': status, 'lease': lease}
        if (not wait or status.get('can_acquire') is not False or status.get('reason') not in
                {'continuous_quiet_unconfirmed', 'manual_cleanup_unconfirmed'}):
            raise RuntimeError('Manual owner rejected admission: '+str(status.get('reason')))
        remaining = end-time.monotonic()
        if remaining > 0:
            time.sleep(min(.05, remaining))
    raise RuntimeError('Manual owner admission deadline before total 120 second deadline')


def wait_fresh_observation(observer, deadline):
    """Wait for DDS discovery before fixing the first quiet boundary."""
    while time.monotonic() < deadline:
        try:
            return observer.fresh()
        except RuntimeError as error:
            if str(error) not in {'No independent truth', 'Independent truth is stale'}:
                raise
        remaining = deadline-time.monotonic()
        if remaining > 0:
            time.sleep(min(.05, remaining))
    raise RuntimeError('No fresh independent truth before total 120 second deadline')


def read_with_timeout_recovery(read, resource, deadline, evidence, *, request_budget_s=0.):
    """Repeat only a read whose actual transport exception was a timeout."""
    while time.monotonic() < deadline:
        # Api.get retains its existing two-second transport timeout. Do not
        # start that call inside a shorter remaining original STOP window.
        if deadline-time.monotonic() < request_budget_s:
            break
        entry = {'resource': resource, 'epoch': time.time(), 'steady_time': time.monotonic()}
        evidence.append(entry)
        try:
            value = read(resource)
        except Exception as error:
            causes, current, timeout = [], error, False
            while current is not None and len(causes) < 8:
                causes.append({'type': type(current).__name__, 'error': str(current)})
                if isinstance(current, HTTPError):
                    timeout = False
                    break
                timeout = timeout or isinstance(current, TimeoutError) or (
                    isinstance(current, URLError) and isinstance(current.reason, TimeoutError))
                current = current.__cause__
            entry.update(error=str(error), causes=causes, timeout=timeout)
            if not timeout:
                raise
        else:
            entry['received'] = True
            if time.monotonic() < deadline:
                return value
            break
        remaining = deadline-time.monotonic()
        if remaining > 0:
            time.sleep(min(.08, remaining))
    raise TimeoutError('Original read-only recovery deadline exhausted')


def check_cleanup_identity(current, marker):
    if (current.get('id') != marker['task_id'] or (marker.get('native_goal_id') is not None
            and current.get('native_goal_id') != marker['native_goal_id'])):
        raise RuntimeError('Failure cleanup original task or native UUID identity changed')
    stop_attempted = bool(marker.get('stop_command_id') or marker.get('cancel_epoch'))
    if stop_attempted and (current.get('status') not in {'running', 'canceling', 'canceled'}
            or current.get('native_status') in {4, 6} or current.get('cleanup_state') == 'unresolved'):
        raise RuntimeError('Failure cleanup original STOP task explicitly failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--api'); parser.add_argument('--voice'); parser.add_argument('--web')
    parser.add_argument('--domain', type=int); parser.add_argument('--expected-instance')
    parser.add_argument('--chromium'); parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({'panel': 'voice_preview_confirm_cancel', 'native_missions': 1,
            'voice_commands': 2, 'wall_budget_s': 120, 'audio_recording': False,
            'cleanup': 'At most one original-ID cancel on failure; unknown is not retried'})); return 0
    if not all((args.api, args.voice, args.web, args.domain, args.expected_instance, args.chromium, args.output)):
        parser.error('Explicit runtime, domain, origins, browser and private output are required')
    for address in (args.api, args.voice, args.web): require_loopback(address)
    uuid.UUID(args.expected_instance)
    if (not 1 <= args.domain <= 232 or os.environ.get('ROS_DOMAIN_ID') != str(args.domain)
            or os.environ.get('FISHBOT_MUJOCO_DOMAIN_ID') != str(args.domain)
            or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST'
            or os.environ.get('ROS_STATIC_PEERS', '')):
        parser.error('Require one explicit localhost-only simulation domain')
    output = args.output.expanduser().resolve()
    if output.exists() or output.is_relative_to(ROOT): parser.error('Require new private output outside source')
    output.mkdir(mode=0o700, parents=True)
    def save(name, value): (output/name).write_text(json.dumps(value, indent=2)+'\n')
    def sources():
        values = source_snapshot()
        for name in ['tools/fishbot_voice_ui_acceptance.py', 'tools/fishbot_voice_ui_acceptance.cjs',
                     'tools/fishbot_voice_bridge.py', 'tools/fishbot_edge_voice_node.py',
                     'tools/fishbot_runtime.py', 'tools/fishbot_voice_asr.py',
                     'apps/fishbot-control-station/frontend/src/lib/voice.ts',
                     'apps/fishbot-control-station/frontend/src/components/voice/voice-panel.tsx']:
            values[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        return values
    report = {'passed': False, 'errors': [], 'source_start': sources(), 'scope': 'Text voice UI and actual ROS cancellation; ASR not evaluated'}
    log = Recording(output); observer = child = None
    api = Api(args.api, args.expected_instance, log)
    started = time.monotonic(); deadline = started+120
    def get(resource, *, recover_until=None):
        if time.monotonic() >= deadline: raise TimeoutError('Total 120 second voice panel budget exhausted')
        if recover_until is not None:
            return read_with_timeout_recovery(api.get, resource, min(deadline, recover_until),
                report.setdefault('read_timeout_recovery', []), request_budget_s=2.)
        if deadline-time.monotonic() < 2.:
            raise TimeoutError('Insufficient original deadline for fixed two second GET')
        return api.get(resource)
    try:
        runtime, state = get('runtime'), get('state')
        if runtime['instance_id'] != args.expected_instance or state['domain'] != args.domain or state['mode'] != 'mujoco' or not state['ready']:
            raise RuntimeError('Specified runtime is not ready or identity changed')
        if state['mission']['status'] in {'running', 'canceling', 'unknown'}:
            raise RuntimeError('Existing task is unresolved; leave it untouched')
        report['manual_preflight_observations'] = []
        report['manual_preflight'] = manual_preflight(runtime, state, get, deadline=deadline,
            evidence=report['manual_preflight_observations'])
        observer = RuntimeObservation(output, log)
        def quiet(seconds=15):
            boundary = time.monotonic(); end = min(boundary+seconds, deadline)
            while time.monotonic() < end:
                try:
                    observer.fresh(); frames = observer.frames_after(boundary)
                    result = quiet_result(frames) if len(frames) >= 2 else None
                    if result: return {**result, 'boundary_steady': boundary}
                except RuntimeError as e:
                    if 'No fresh independent pre-dispatch boundary' not in str(e) and 'No independent truth' not in str(e): raise
                time.sleep(.05)
            raise RuntimeError('Independent continuous quiet deadline')
        # Discovery may take longer than a fixed sleep. Only the initial wait
        # precedes the boundary; later quiet failures never move their boundary.
        report['initial_observer_frame'] = wait_fresh_observation(observer, deadline)
        report['initial_quiet'] = quiet(); boundary = time.monotonic()
        plan = {'api': args.api, 'voice': args.voice, 'web': args.web, 'domain': args.domain,
                'runtime_instance_id': args.expected_instance, 'observer_latest': str(output/'observer-latest.json'),
                'deadline_monotonic_s': deadline,
                'remaining_budget_s': max(0., deadline-time.monotonic())}
        save('plan.json', plan)
        with (output/'browser.log').open('x') as stream:
            child = subprocess.Popen(['node', str(Path(__file__).with_suffix('.cjs')), '--plan', str(output/'plan.json'),
                '--output', str(output), '--chromium', args.chromium], stdout=stream, stderr=subprocess.STDOUT)
            child.wait(timeout=max(.1, min(100, deadline-time.monotonic()-20)))
        browser = json.loads((output/'browser-result.json').read_text()); report['browser'] = browser
        if child.returncode or not browser['passed']: raise RuntimeError('Voice UI checks failed; inspect retained browser evidence')
        report['final_quiet'] = quiet()
        marker = browser['marker']; mission = get('tasks/'+marker['task_id'])
        mission = mission.get('mission', mission)
        if (mission.get('id') != marker['task_id'] or mission.get('status') != 'canceled'
                or mission.get('native_goal_id') != marker['native_goal_id'] or mission.get('native_status') != 5
                or observer.statuses().get(marker['native_goal_id']) != 5 or mission.get('cleanup_state') == 'unresolved'):
            raise RuntimeError('Independent original native UUID terminal is unconfirmed')
        frames = observer.frames_after(boundary)
        moving = [f for f in frames if marker['dispatch_epoch'] <= f['epoch'] < marker['cancel_epoch']
                  and f['linear_speed'] > .03 and ((f['x']-marker['start_truth']['x'])**2+(f['y']-marker['start_truth']['y'])**2)**.5 > .05]
        if not moving: raise RuntimeError('No independent movement before cancellation')
        from fishbot_map_rules_acceptance import truth_metrics
        report.update(physical=truth_metrics(frames), native_terminal=mission,
                      independent_moving=moving[-1], guard=observer.guard_evidence(), passed=True)
    except Exception as error:
        report['errors'].append(str(error))
        if child and child.poll() is None: child.terminate(); child.wait(timeout=5)
        marker_path = output/'marker.json'
        if marker_path.exists():
            marker = json.loads(marker_path.read_text()); identity = marker.get('task_id')
            if identity:
                try:
                    stop_attempted = bool(marker.get('stop_command_id') or marker.get('cancel_epoch'))
                    recovery_end = marker.get('stop_terminal_deadline_ms', 0.)/1000. if marker.get('stop_outcome_unknown') is True else None
                    current = get('state', recover_until=recovery_end)['mission']
                    check_cleanup_identity(current, marker)
                    if (current.get('id') == identity and current.get('status') == 'running' and not stop_attempted
                            and marker.get('post_count', 4) < 4):
                        body = {'mission_id': identity, 'issued_at': time.time()}
                        save('failure-cancel-attempt.json', body)
                        report['failure_cleanup_cancel'] = api.call('cancel', body, cleanup=True)
                    elif stop_attempted:
                        report['failure_cleanup_mode'] = 'Existing voice STOP outcome may be unknown; read original ID only'
                    report['failure_quiet'] = quiet()
                    report['failure_original_task'] = get('tasks/'+identity, recover_until=recovery_end)
                except Exception as cleanup: report['errors'].append('Cleanup unresolved: '+str(cleanup))
    finally:
        if observer: observer.close()
        log.close(); report['source_end'] = sources(); report['source_unchanged'] = report['source_start'] == report['source_end']
        report['elapsed_wall_s'] = time.monotonic()-started
        if report['elapsed_wall_s'] > 120: report['errors'].append('Total 120 second voice panel budget exceeded')
        report['passed'] = report['passed'] and report['source_unchanged'] and not log.error and not report['errors']
        if log.error: report['errors'].append(log.error)
        save('result.json', report)
    print(json.dumps({'passed': report['passed'], 'errors': report['errors'], 'output': str(output)}))
    return 0 if report['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
