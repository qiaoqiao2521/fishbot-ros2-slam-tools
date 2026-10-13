#!/usr/bin/python3
"""Verify software keepouts against native costmaps and independent MuJoCo truth.

Connect only an explicitly selected, idle, isolated synthetic arena. This test
changes its rules and runs bounded missions; it never launches or resets a robot.
"""
import argparse
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/scripts'


def request(base, path, body=None):
    data = None if body is None else json.dumps(body, allow_nan=False).encode()
    req = Request(base + '/sim-api/' + path, data=data,
                  headers={'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=5) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def wait_for(get, predicate, seconds=30):
    deadline = time.monotonic() + seconds
    value = None
    while time.monotonic() < deadline:
        value = get()
        if predicate(value):
            return value
        time.sleep(.12)
    raise TimeoutError(f'Acceptance deadline: {value}')


def rectangle_clearance(sample, radius=.13):
    # Independent geometric oracle, not the production mask implementation.
    dx = max(.45-sample['x'], 0., sample['x']-.75)
    dy = max(-.30-sample['y'], 0., sample['y']-.30)
    return math.hypot(dx, dy) - radius


def truth_metrics(frames):
    """Reject stale, duplicated or discontinuous source and receive timelines."""
    if len(frames) < 2:
        raise RuntimeError('Insufficient independent truth frames')
    ages = [frame['ros_now']-frame['stamp'] for frame in frames]
    receipt_gaps = [b['steady_time']-a['steady_time'] for a, b in zip(frames, frames[1:])]
    source_gaps = [b['stamp']-a['stamp'] for a, b in zip(frames, frames[1:])]
    if (any(not -.05 <= age <= .25 for age in ages)
            or any(not 0 < gap <= .30 for gap in receipt_gaps + source_gaps)):
        raise RuntimeError('Independent truth is stale, nonmonotonic or discontinuous')
    return {'max_receipt_gap_s': max(receipt_gaps), 'max_source_gap_s': max(source_gaps),
            'min_source_age_s': min(ages), 'max_source_age_s': max(ages)}


def stationary(frame):
    return frame['linear_speed'] < .005 and frame['angular_speed'] < .02


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', default='http://127.0.0.1:9079')
    parser.add_argument('--domain', type=int, default=107)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runtime-manifest', type=Path,
                        help='Reference an independently verified owned-runtime/source manifest')
    args = parser.parse_args()
    address = urlsplit(args.api)
    if (address.scheme != 'http' or address.hostname != '127.0.0.1'
            or address.username or address.password or address.path or address.query
            or not address.port or not 1 <= args.domain <= 232
            or os.environ.get('ROS_DOMAIN_ID') != str(args.domain)
            or os.environ.get('FISHBOT_MUJOCO_DOMAIN_ID') != str(args.domain)
            or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST'
            or os.environ.get('ROS_STATIC_PEERS', '')):
        parser.error('Select one loopback simulation domain and HTTP API explicitly')
    output = args.output.expanduser().resolve()
    if output.is_relative_to(ROOT) or output.exists():
        parser.error('Output must be a new directory outside the repository')
    output.mkdir(parents=True, mode=0o700)
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.signals import SignalHandlerOptions
    from nav2_msgs.srv import GetCostmap
    from rcl_interfaces.srv import GetParameters
    sys.path.insert(0, str(SCRIPTS))
    from verify_stack import Probe

    report = {'passed': False, 'domain': args.domain, 'api': args.api, 'checks': [],
              'events': [], 'errors': [], 'source_sha256': {str(Path(__file__).relative_to(ROOT)):
                  hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    if args.runtime_manifest:
        manifest = args.runtime_manifest.expanduser().resolve()
        report['runtime_manifest'] = {'path': str(manifest),
            'sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(),
            'scope': 'Reference only; this script does not establish process/source identity'}
    def event(kind, value):
        report['events'].append({'kind': kind, 'steady_time': time.monotonic(),
                                 'epoch': time.time(), 'value': value})
    def get(path):
        status, value = request(args.api, path)
        if status != 200:
            raise RuntimeError(f'GET {path}: {status} {value}')
        return value
    stream = (output / 'truth.jsonl').open('w', buffering=1)
    samples, sample_lock, observer_errors = [], threading.Lock(), []

    class Observer(Probe):
        def on_truth(self, msg):
            previous = self.truth_updates
            super().on_truth(msg)
            if self.truth is None or self.truth_updates == previous:
                return
            p = self.truth.pose.pose
            linear, angular = self.planar_speed()
            q = p.orientation
            value = {'steady_time': time.monotonic(), 'stamp': self.truth_time,
                     'ros_now': self.get_clock().now().nanoseconds*1e-9,
                     'x': p.position.x, 'y': p.position.y,
                     'yaw': math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z)),
                     'linear_speed': linear, 'angular_speed': angular}
            if not all(math.isfinite(v) for v in value.values()):
                with sample_lock:
                    observer_errors.append('Nonfinite independent truth')
                return
            with sample_lock:
                samples.append(value)
                stream.write(json.dumps(value) + '\n')

    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = Observer(SimpleNamespace(mode='sensors', odom='/odom', scan='/scan',
        truth='/ground_truth/free_joint_states', cmd='/cmd_vel'))
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    worker = threading.Thread(target=executor.spin, daemon=True)
    worker.start()
    clients = {name: node.create_client(GetCostmap, f'/{name}_costmap/get_costmap')
               for name in ('global', 'local')}
    def latest_fresh():
        with sample_lock:
            if observer_errors:
                raise RuntimeError(observer_errors[0])
            latest = samples[-1].copy()
        if (time.monotonic()-latest['steady_time'] > .25
                or not -.05 <= latest['ros_now']-latest['stamp'] <= .25):
            raise RuntimeError('Dispatch/motion requires fresh independent truth')
        return latest

    def wait_stopped(after, label):
        def quiet_tail(_value):
            latest_fresh()
            with sample_lock:
                frames = [s.copy() for s in samples if s['steady_time'] >= after]
            if len(frames) < 2:
                return False
            truth_metrics(frames)
            start = len(frames)-1
            while start >= 0 and stationary(frames[start]):
                start -= 1
            tail = frames[start+1:]
            if len(tail) < 2:
                return False
            return (tail[-1]['steady_time']-tail[0]['steady_time'] >= .7
                    and tail[-1]['stamp']-tail[0]['stamp'] >= .7)
        wait_for(lambda: None, quiet_tail, 15)
        event(label, {'after': after, 'last_truth': latest_fresh(),
                      'stop_window_s': .7, 'all_window_frames_checked': True})

    def phase_frames(boundary, end):
        with sample_lock:
            if observer_errors:
                raise RuntimeError(observer_errors[0])
            frames = [boundary.copy()] + [s.copy() for s in samples
                if boundary['steady_time'] < s['steady_time'] <= end]
        metrics = truth_metrics(frames)
        if time.monotonic()-frames[-1]['steady_time'] > .25:
            raise RuntimeError('Independent truth stopped before the phase ended')
        return frames, metrics

    def footprint_radius():
        # Nav2 pads each polygon coordinate. sqrt(2)*padding conservatively
        # bounds the resulting circumscribed circle without reducing the body.
        radii, values = [], {}
        for name in clients:
            client = node.create_client(GetParameters, f'/{name}_costmap/{name}_costmap/get_parameters')
            try:
                if not client.wait_for_service(timeout_sec=4):
                    raise RuntimeError(f'{name} footprint parameter service is not available')
                future = client.call_async(GetParameters.Request(
                    names=['robot_radius', 'footprint', 'footprint_padding']))
                response = wait_for(lambda: future.result() if future.done() else None,
                                    lambda value: value is not None, 4)
                radius, polygon, padding = response.values
                if radius.type != 3 or polygon.type != 4 or padding.type != 3:
                    raise RuntimeError(f'{name} footprint parameters are unavailable')
                points = ast.literal_eval(polygon.string_value) if polygon.string_value.strip() else []
                if points:
                    if (not isinstance(points, (list, tuple)) or len(points) < 3
                            or any(not isinstance(p, (list, tuple)) or len(p) != 2 for p in points)):
                        raise RuntimeError(f'{name} footprint is not a planar polygon')
                    body_radius = max(math.hypot(*point) for point in points)
                else:
                    body_radius = radius.double_value
                padded_radius = body_radius+math.sqrt(2)*padding.double_value
                if (not math.isfinite(padded_radius) or body_radius <= 0
                        or padding.double_value < 0):
                    raise RuntimeError(f'{name} footprint parameters are invalid')
                radii.append(padded_radius)
                values[name] = {'robot_radius': radius.double_value,
                    'footprint': polygon.string_value, 'footprint_padding': padding.double_value,
                    'oracle_circumscribed_radius': padded_radius}
            finally:
                node.destroy_client(client)
        event('native_footprint_parameters', values)
        report['oracle_radius_m'] = max(radii)
        return max(radii)
    def cost_at(name, x, y):
        if not clients[name].wait_for_service(timeout_sec=4):
            raise RuntimeError(f'{name} native costmap service is not available')
        future = clients[name].call_async(GetCostmap.Request())
        response = wait_for(lambda: future.result() if future.done() else None,
                            lambda value: value is not None, 4)
        grid = response.map
        meta, origin = grid.metadata, grid.metadata.origin
        # Transform a map-frame test point into the native costmap frame.
        if grid.header.frame_id != 'map':
            t = node.buffer.lookup_transform(grid.header.frame_id, 'map',
                rclpy.time.Time.from_msg(meta.update_time))
            q, p = t.transform.rotation, t.transform.translation
            angle = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
            x, y = p.x+math.cos(angle)*x-math.sin(angle)*y, p.y+math.sin(angle)*x+math.cos(angle)*y
        col = math.floor((x-origin.position.x)/meta.resolution)
        row = math.floor((y-origin.position.y)/meta.resolution)
        if not 0 <= col < meta.size_x or not 0 <= row < meta.size_y:
            raise RuntimeError(f'{name} does not cover test point')
        value = int(grid.data[row*meta.size_x+col])
        event('native_costmap', {'name': name, 'frame': grid.header.frame_id,
            'stamp': grid.header.stamp.sec+grid.header.stamp.nanosec*1e-9,
            'x': x, 'y': y, 'cost': value})
        return value
    owned_id = None
    try:
        state = wait_for(lambda: get('state'), lambda s: s['ready'], 50)
        if state['domain'] != args.domain or state['mode'] != 'mujoco':
            raise RuntimeError('API identifies a different environment')
        if state['mission']['status'] in {'running', 'canceling'}:
            raise RuntimeError('Existing mission must remain untouched')
        wait_for(lambda: len(samples), lambda count: count >= 10)
        radius = footprint_radius()
        initial_truth = latest_fresh()
        if not stationary(initial_truth):
            raise RuntimeError('Acceptance requires an independently stationary robot')
        if math.hypot(state['truth']['x'], state['truth']['y']) > .15:
            raise RuntimeError('Acceptance requires the synthetic arena start near zero')
        rules = get('map-rules')
        if rules['zones']:
            raise RuntimeError('Acceptance requires an empty rule set; existing edits are preserved')
        baseline = {name: cost_at(name, .60, 0.) for name in clients}
        if any(value >= 254 for value in baseline.values()):
            raise RuntimeError('Test zone was not free before editing')
        zone = {'id': 'acceptance-rectangle', 'kind': 'no_go', 'points': [
            {'x': .45, 'y': -.30}, {'x': .75, 'y': -.30},
            {'x': .75, 'y': .30}, {'x': .45, 'y': .30}]}
        status, saved = request(args.api, 'map-rules', {
            'map_id': rules['map_id'], 'base_revision': rules['revision'], 'zones': [zone]})
        if status != 200:
            raise RuntimeError(f'Rule save failed: {status} {saved}')
        event('saved_rules', saved)
        wait_for(lambda: get('map-rules'), lambda r: r['apply_state'] == 'applied')
        if any(cost_at(name, .60, 0.) != 254 for name in clients):
            raise RuntimeError('Both native costmaps must mark the rule lethal')
        report['checks'].append('both_costmaps_mark_keepout')
        body = {'waypoints': [{'x': .60, 'y': 0., 'yaw': 0.}],
                'return_home': False, 'issued_at': time.time(),
                'map_id': saved['map_id'], 'rules_revision': saved['revision']}
        before_denied = get('state')['mission']
        status, denied = request(args.api, 'mission', body)
        event('keepout_goal_denied', {'status': status, 'body': denied})
        after_denied = get('state')['mission']
        if (status != 400 or denied.get('outcome') != 'rejected'
                or zone['id'] not in denied.get('error', '')
                or 'footprint' not in denied.get('error', '').lower()
                or any(before_denied.get(key) != after_denied.get(key)
                       for key in ('id', 'status', 'dispatch_state'))):
            raise RuntimeError('Keepout rejection lacked its cause or mutated the current mission')
        event('rejected_mission_unchanged', {'before': before_denied, 'after': after_denied})
        report['checks'].append('keepout_goal_rejected_before_dispatch')
        target = {'x': 1.20, 'y': -.35, 'yaw': 0.}
        status, route = request(args.api, 'routes', {'id': 'acceptance-route',
            'map_id': saved['map_id'], 'name': '禁区绕行验收',
            'waypoints': [target], 'return_home': False})
        if status != 200:
            raise RuntimeError(f'Route save failed: {status} {route}')
        event('route_saved_without_dispatch', route)
        before = get('state')['mission']['id']
        boundary = latest_fresh()
        start = time.monotonic()
        event('dispatch_truth_boundary', {'dispatch_start': start, 'prior_truth': boundary})
        body.update(waypoints=[target], issued_at=time.time())
        status, submitted = request(args.api, 'mission', body)
        if status != 202:
            raise RuntimeError(f'Mission dispatch failed: {status} {submitted}')
        identity = submitted['mission']['id']
        owned_id = identity
        if identity == before:
            raise RuntimeError('Mission identity did not change')
        event('mission_submitted', submitted)
        status, rejected_edit = request(args.api, 'map-rules', {
            'map_id': saved['map_id'], 'base_revision': saved['revision'], 'zones': []})
        if status != 409:
            raise RuntimeError('Rules changed while a mission was active')
        report['checks'].append('active_mission_preserves_rules')
        terminal = wait_for(lambda: get('state'), lambda s: s['mission']['id'] == identity
            and s['mission']['status'] in {'succeeded', 'failed', 'canceled'}, 150)
        event('mission_terminal', terminal)
        if terminal['mission']['status'] != 'succeeded':
            raise RuntimeError('Keepout route did not succeed')
        wait_stopped(time.monotonic(), 'route_continuous_stop')
        end = time.monotonic()
        trajectory, timing = phase_frames(boundary, end)
        if len(trajectory) < 20:
            raise RuntimeError('Missing independent trajectory')
        clearances = [rectangle_clearance(s, radius) for s in trajectory]
        clearance = min(clearances)
        # The distance-to-zone function is 1-Lipschitz. Subtracting a whole
        # observed step bounds its piecewise-linear sweep, not unknown motion.
        sweep_bound = min(min(a, b)-math.hypot(q['x']-p['x'], q['y']-p['y'])
            for a, b, p, q in zip(clearances, clearances[1:], trajectory, trajectory[1:]))
        error = math.hypot(trajectory[-1]['x']-target['x'], trajectory[-1]['y']-target['y'])
        yaw_error = abs(math.atan2(math.sin(trajectory[-1]['yaw']-target['yaw']),
                                  math.cos(trajectory[-1]['yaw']-target['yaw'])))
        report['physical'] = {'min_rule_clearance_m': clearance, 'endpoint_error_m': error,
            'min_piecewise_linear_sweep_bound_m': sweep_bound, 'endpoint_yaw_error_rad': yaw_error,
            'truth_frames': len(trajectory), **timing,
            'clearance_scope': 'Sampled truth plus conservative piecewise-linear sweep; unobserved motion is not established'}
        if clearance < 0 or sweep_bound < 0 or error > .15 or yaw_error > .30:
            raise RuntimeError('Independent trajectory/clearance/freshness failed')
        report['checks'].append('physical_route_avoids_software_zone')
        status, cleared = request(args.api, 'map-rules', {
            'map_id': saved['map_id'], 'base_revision': saved['revision'], 'zones': []})
        if status != 200:
            raise RuntimeError(f'Rule removal failed: {status} {cleared}')
        wait_for(lambda: get('map-rules'), lambda r: r['apply_state'] == 'applied')
        if any(cost_at(name, .60, 0.) >= 254 for name in clients):
            raise RuntimeError('Deleted keepout remained in a native costmap')
        report['checks'].append('deleted_keepout_clears_both_native_costmaps')

        # Cancel a separate moving task. A cancel receipt alone cannot prove
        # either action ownership or physical stopping.
        cancel_origin = latest_fresh()
        cancel_start = time.monotonic()
        event('cancel_dispatch_truth_boundary', {'dispatch_start': cancel_start,
                                                 'prior_truth': cancel_origin})
        body.update(waypoints=[{'x': 0., 'y': 0., 'yaw': 0.}],
                    rules_revision=cleared['revision'], issued_at=time.time())
        status, dispatched = request(args.api, 'mission', body)
        if status != 202:
            raise RuntimeError(f'Cancellation task dispatch failed: {status} {dispatched}')
        cancel_identity = dispatched['mission']['id']
        owned_id = cancel_identity
        def moving(_value):
            latest = latest_fresh()
            return (latest['steady_time'] >= cancel_start
                    and time.monotonic()-latest['steady_time'] <= .25
                    and latest['linear_speed'] > .03
                    and math.hypot(latest['x']-cancel_origin['x'],
                                   latest['y']-cancel_origin['y']) >= .05)
        wait_for(lambda: None, moving, 35)
        event('independent_motion_before_cancel', latest_fresh())
        status, cancel_receipt = request(args.api, 'cancel', {})
        event('moving_cancel', {'status': status, 'body': cancel_receipt})
        if status != 202:
            raise RuntimeError('Moving cancellation was not accepted')
        canceled = wait_for(lambda: get('state'), lambda s:
            s['mission']['id'] == cancel_identity
            and s['mission']['status'] in {'succeeded', 'failed', 'canceled'}, 15)
        if canceled['mission']['status'] != 'canceled':
            raise RuntimeError('Moving task did not reach the canceled terminal')
        wait_stopped(time.monotonic(), 'cancel_continuous_stop')
        cancel_frames, cancel_timing = phase_frames(cancel_origin, time.monotonic())
        report['cancel_physical'] = {'truth_frames': len(cancel_frames), **cancel_timing}
        event('moving_cancel_terminal', canceled)
        report['checks'].append('moving_cancel_reaches_terminal_and_fresh_stop')
        runs = get('runs')
        event('run_history', runs)
        if not any(run['id'] == identity and run['status'] == 'succeeded' for run in runs['runs']):
            raise RuntimeError('Actual mission terminal missing from saved runs')
        if not any(run['id'] == cancel_identity and run['status'] == 'canceled' for run in runs['runs']):
            raise RuntimeError('Canceled mission terminal missing from saved runs')
        report['checks'].append('route_template_and_actual_run_saved')
        report['passed'] = True
    except Exception as error:
        report['errors'].append(str(error))
        try:
            mission = get('state')['mission']
            if owned_id and mission['id'] == owned_id and mission['status'] in {'running', 'canceling'}:
                event('failure_cancel', request(args.api, 'cancel', {}))
                event('failure_terminal', wait_for(lambda: get('state'),
                    lambda s: s['mission']['id'] == owned_id
                        and s['mission']['status'] not in {'running', 'canceling'}, 15))
        except Exception as cleanup_error:
            report['errors'].append(f'Cleanup result unknown: {cleanup_error}')
    finally:
        executor.shutdown(timeout_sec=3)
        worker.join(timeout=3)
        node.destroy_node()
        rclpy.shutdown()
        stream.close()
        (output/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: report.get(key) for key in ('passed', 'checks', 'physical', 'errors')},
                     ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
