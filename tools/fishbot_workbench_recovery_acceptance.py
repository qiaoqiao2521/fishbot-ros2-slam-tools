#!/usr/bin/env python3
"""Two bounded UI missions, observed independently through the existing Probe.

No launch, reset or controller is created. Existing truth freshness, .7 second
dual-clock quiet, .15 metre and .30 radian physical thresholds stay unchanged.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

from fishbot_map_rules_acceptance import request, stationary, truth_metrics, wait_for

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco'


def sources():
    paths = [Path(__file__), Path(__file__).with_suffix('.cjs'),
             ROOT/'tools/fishbot_map_rules_ui_acceptance.cjs',
             ROOT/'tools/fishbot_map_rules_acceptance.py',
             *[PKG/name for name in ('scripts/verify_stack.py', 'scripts/mission_bridge.py',
                                    'scripts/map_rules.py', 'config/nav2.yaml',
                                    'launch/sim.launch.py', 'mjcf/arena.xml')],
             *[ROOT/'apps/fishbot-control-station/frontend/src'/name for name in
               ('App.tsx', 'hooks/use-simulation.ts', 'hooks/use-simulation-workspace.ts',
                'hooks/use-patrol-draft-cache.ts', 'lib/mission-receipt.ts', 'lib/simulation.ts',
                'lib/patrol-mission.ts', 'components/simulation/simulation-page.tsx',
                'components/simulation/simulation-map.tsx', 'components/simulation/simulation.css')]]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def score_case(case, browser, frames, terminal):
    marker = browser['marker']
    identity = marker['owned_mission_id']
    if terminal['id'] != identity or terminal.get('cleanup_state') == 'unresolved':
        raise RuntimeError('Original task identity or cleanup is unresolved')
    boundary = [frame for frame in frames if frame['epoch'] < marker['dispatch_epoch']]
    if not boundary or marker['dispatch_epoch']-boundary[-1]['epoch'] > .25:
        raise RuntimeError('No fresh independent pre-dispatch boundary frame')
    trajectory = [boundary[-1]] + [frame for frame in frames if frame['epoch'] >= marker['dispatch_epoch']]
    timing = truth_metrics(trajectory)
    tail = []
    for frame in reversed(trajectory):
        if not stationary(frame):
            break
        tail.append(frame)
    if len(tail) < 2 or min(tail[0]['stamp']-tail[-1]['stamp'], tail[0]['steady_time']-tail[-1]['steady_time']) < .7:
        raise RuntimeError('No continuous .7 second source/receipt quiet tail')
    result = {'truth_frames': len(trajectory), **timing, 'pre_dispatch_boundary_age_s': marker['dispatch_epoch']-boundary[-1]['epoch'], 'quiet_source_s': tail[0]['stamp']-tail[-1]['stamp'],
              'quiet_receipt_s': tail[0]['steady_time']-tail[-1]['steady_time']}
    if case == 'return_recovery':
        if terminal['status'] != 'succeeded' or terminal.get('native_status') != 4 or terminal.get('native_error_code') != 0 or terminal.get('missed_waypoints') != []:
            raise RuntimeError('Return route lacks same-UUID native 4/0 success with no missed waypoints')
        if not terminal.get('return_home') or not terminal.get('start_pose'):
            raise RuntimeError('Return route has no captured departure pose')
        targets = [marker['requested_body']['waypoints'][0], terminal['start_pose']]
        visits, cursor = [], 0
        for target in targets:
            for index in range(cursor, len(trajectory)):
                frame = trajectory[index]
                if math.hypot(frame['x']-target['x'], frame['y']-target['y']) <= .15:
                    visits.append({'target': target, 'truth': frame}); cursor = index+1; break
            else:
                raise RuntimeError('Truth did not visit the outbound target and captured home in order')
        final, home = trajectory[-1], terminal['start_pose']
        distance = math.hypot(final['x']-home['x'], final['y']-home['y'])
        yaw = abs(math.atan2(math.sin(final['yaw']-home['yaw']), math.cos(final['yaw']-home['yaw'])))
        if distance > .15 or yaw > .30:
            raise RuntimeError('Independent physical return endpoint failed')
        result.update(ordered_visits=visits, endpoint_error_m=distance, endpoint_yaw_error_rad=yaw,
            physical_roundtrip_error_m=math.hypot(final['x']-marker['start_truth']['x'], final['y']-marker['start_truth']['y']))
    else:
        if terminal['status'] != 'canceled' or terminal.get('native_status') != 5:
            raise RuntimeError('The original moving UUID did not reach native canceled status 5')
        moving = [f for f in trajectory if f['epoch'] < marker['cancel_epoch'] and f['linear_speed'] > .03
                  and math.hypot(f['x']-marker['start_truth']['x'], f['y']-marker['start_truth']['y']) >= .05]
        if not moving:
            raise RuntimeError('No independent .03 m/s and .05 metre motion before UI cancel')
        result.update(independent_moving_frame=moving[-1], cancel_epoch=marker['cancel_epoch'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', required=True); parser.add_argument('--web', required=True)
    parser.add_argument('--domain', type=int, required=True); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--chromium', required=True)
    parser.add_argument('--target-x', type=float, default=.6); parser.add_argument('--target-y', type=float, default=0.)
    args = parser.parse_args()
    for address in (args.api, args.web):
        parsed = urlsplit(address)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            parser.error('Select explicit loopback HTTP origins')
    if (not 1 <= args.domain <= 232 or os.environ.get('ROS_DOMAIN_ID') != str(args.domain)
            or os.environ.get('FISHBOT_MUJOCO_DOMAIN_ID') != str(args.domain)
            or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST' or os.environ.get('ROS_STATIC_PEERS', '')):
        parser.error('Require one explicit localhost-only simulation domain')
    output = args.output.expanduser().resolve()
    if output.exists() or output.is_relative_to(ROOT): parser.error('Select a new private directory outside the repository')
    if not all(math.isfinite(v) for v in (args.target_x, args.target_y)) or not Path(args.chromium).is_file() or not shutil.which('node'):
        parser.error('Require finite target coordinates, Node and an explicit Chromium executable')
    output.mkdir(parents=True, mode=0o700)
    report = {'passed': False, 'domain': args.domain, 'api': args.api, 'web': args.web, 'cases': [], 'errors': [],
              'scope': 'Two actual UI missions plus independent ROS/MuJoCo truth; no controller or launch change', 'source_start': sources()}
    def get(resource):
        status, value = request(args.api, resource)
        if status != 200: raise RuntimeError(f'GET {resource}: {status}')
        return value
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.signals import SignalHandlerOptions
    sys.path.insert(0, str(PKG/'scripts'))
    from verify_stack import Probe
    frames, faults, lock = [], [], threading.Lock()
    stream = (output/'truth.jsonl').open('x', buffering=1)
    last_snapshot = 0.
    def atomic(name, value):
        target = output/name; temporary = output/(name+'.tmp')
        temporary.write_text(json.dumps(value)+'\n'); temporary.replace(target)
    class Observer(Probe):
        def on_truth(self, msg):
            nonlocal last_snapshot
            prior = self.truth_updates; super().on_truth(msg)
            if self.truth is None or self.truth_updates == prior: return
            p = self.truth.pose.pose; q = p.orientation; linear, angular = self.planar_speed()
            frame = {'epoch': time.time(), 'steady_time': time.monotonic(), 'stamp': self.truth_time,
                'ros_now': self.get_clock().now().nanoseconds*1e-9, 'x': p.position.x, 'y': p.position.y,
                'yaw': math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z)), 'linear_speed': linear, 'angular_speed': angular}
            with lock:
                try:
                    if not all(math.isfinite(v) for v in frame.values()) or len(frames) >= 50000: raise RuntimeError('Invalid truth or bounded recording budget exhausted')
                    frames.append(frame); stream.write(json.dumps(frame)+'\n')
                    if frame['steady_time']-last_snapshot >= .08:
                        atomic('observer-latest.json', frame); last_snapshot = frame['steady_time']
                except Exception as error: faults.append(str(error))
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    observer = Observer(SimpleNamespace(mode='sensors', odom='/odom', scan='/scan', truth='/ground_truth/free_joint_states', cmd='/cmd_vel'))
    executor = SingleThreadedExecutor(); executor.add_node(observer)
    worker = threading.Thread(target=executor.spin, daemon=True); worker.start()
    def observed():
        with lock:
            if faults: raise RuntimeError(faults[0])
            return [dict(frame) for frame in frames]
    def fresh():
        values = observed()
        if not values or time.monotonic()-values[-1]['steady_time'] > .25 or not -.05 <= observer.get_clock().now().nanoseconds*1e-9-values[-1]['stamp'] <= .25:
            raise RuntimeError('Independent truth is not fresh')
        return values[-1]
    def quiet(after):
        def ready(_):
            fresh(); values = [f for f in observed() if f['steady_time'] >= after]
            if len(values) < 2: return False
            truth_metrics(values); tail = []
            for f in reversed(values):
                if not stationary(f): break
                tail.append(f)
            return len(tail) > 1 and min(tail[0]['stamp']-tail[-1]['stamp'], tail[0]['steady_time']-tail[-1]['steady_time']) >= .7
        wait_for(lambda: None, ready, 15)
    child = None; case_output = None
    try:
        initial = get('state'); runtime = get('runtime'); rules = get('map-rules')
        if initial['domain'] != args.domain or initial['mode'] != 'mujoco' or not initial['ready'] or initial['mission']['status'] in {'running', 'canceling', 'unknown'} or initial['mission'].get('cleanup_state') == 'unresolved':
            raise RuntimeError('Existing instance is not idle and ready; leave its task untouched')
        if rules['apply_state'] != 'applied': raise RuntimeError('Current map rules are not applied')
        report['runtime'] = runtime; report['initial_rules'] = rules
        wait_for(lambda: len(observed()), lambda count: count >= 45, 8); quiet(time.monotonic())
        for case in ('return_recovery', 'moving_cancel'):
            case_output = output/case; case_output.mkdir(mode=0o700)
            quiet(time.monotonic()); before = get('state')
            if before['mission']['status'] in {'running', 'canceling', 'unknown'}: raise RuntimeError('A previous original task is unresolved')
            plan = {'case': case, 'domain': args.domain, 'api': args.api, 'web': args.web,
                    'runtime_instance_id': runtime['instance_id'], 'target': {'x': args.target_x, 'y': args.target_y, 'yaw': 0},
                    'return_home': case == 'return_recovery', 'timeout_s': 360, 'observer_latest': str(output/'observer-latest.json')}
            (case_output/'plan.json').write_text(json.dumps(plan, indent=2)+'\n')
            entry = {'case': case, 'passed': False, 'before': {k: before[k] for k in ('pose', 'truth', 'mission')}, 'started_epoch': time.time()}
            report['cases'].append(entry)
            with (case_output/'browser.log').open('x') as log:
                child = subprocess.Popen([shutil.which('node'), str(Path(__file__).with_suffix('.cjs')), '--plan', str(case_output/'plan.json'), '--output', str(case_output), '--chromium', args.chromium], stdout=log, stderr=subprocess.STDOUT)
                wait_for(lambda: child.poll(), lambda code: code is not None, 400)
            browser = json.loads((case_output/'browser-result.json').read_text()); entry['browser'] = browser
            if child.returncode != 0 or not browser['passed']: raise RuntimeError(f'{case} browser failed: {browser["errors"]}')
            quiet(time.monotonic()); terminal = get('state')['mission']; entry['terminal'] = terminal
            entry['physical'] = score_case(case, browser, observed(), terminal)
            lookup = get('tasks/'+terminal['id']+'?map_id='+terminal['map_id'])
            if lookup['task_id'] != terminal['id'] or lookup['mission']['status'] != terminal['status']: raise RuntimeError('Original task ledger terminal mismatch')
            entry.update(passed=True, finished_epoch=time.time(), original_task_lookup=lookup)
            atomic('result.json', report)
        report['passed'] = True
    except Exception as error:
        report['errors'].append(str(error))
        if child and child.poll() is None:
            child.terminate()
            try: child.wait(timeout=5)
            except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=5)
        try:
            marker_path = case_output/'marker.json' if case_output else None
            marker = json.loads(marker_path.read_text()) if marker_path and marker_path.exists() else {}
            current = get('state')['mission']; identity = marker.get('owned_mission_id')
            if identity and current['id'] == identity and current['status'] in {'running', 'canceling'}:
                report['failure_cancel'] = request(args.api, 'cancel', {'mission_id': identity, 'issued_at': time.time()})
                wait_for(lambda: get('state')['mission'], lambda value: value['id'] == identity and value['status'] not in {'running', 'canceling'}, 15)
            quiet(time.monotonic()); report['failure_stationary_confirmed'] = True
        except Exception as cleanup: report['errors'].append('Original task cleanup unknown: '+str(cleanup))
    finally:
        report['source_end'] = sources()
        if report['source_start'] != report['source_end']: report['passed'] = False; report['errors'].append('Execution sources changed')
        report['finished_epoch'] = time.time()
        try:
            final = get('state'); report['final_state'] = {k: final[k] for k in ('pose', 'truth', 'mission')}
        except Exception as error:
            report['passed'] = False; report['errors'].append('Final state readback unavailable: '+str(error))
        executor.shutdown(timeout_sec=3); worker.join(timeout=3); observer.destroy_node(); rclpy.shutdown(); stream.close()
        atomic('result.json', report)
    print(json.dumps({'passed': report['passed'], 'cases': [{'case': c['case'], 'passed': c['passed']} for c in report['cases']], 'errors': report['errors']}, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
