#!/usr/bin/env python3
"""Complete mobile map/template acceptance with independent simulated truth.

Reuse the existing truth probe and timing oracle. The isolated browser saves and
loads a route, then explicitly dispatches it through the actual application.
No startup, reset, network change or physical robot access is performed.
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', default='http://127.0.0.1:9079')
    parser.add_argument('--web', default='http://127.0.0.1:5179')
    parser.add_argument('--domain', type=int, default=107)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--chromium', required=True)
    parser.add_argument('--runtime-manifest', type=Path)
    args = parser.parse_args()
    for address in (args.api, args.web):
        value = urlsplit(address)
        if (value.scheme != 'http' or value.hostname != '127.0.0.1' or not value.port
                or value.username or value.password or value.path or value.query or value.fragment):
            parser.error('Select explicit loopback HTTP ports')
    if (not 1 <= args.domain <= 232
            or os.environ.get('ROS_DOMAIN_ID') != str(args.domain)
            or os.environ.get('FISHBOT_MUJOCO_DOMAIN_ID') != str(args.domain)
            or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST'
            or os.environ.get('ROS_STATIC_PEERS', '')):
        parser.error('Select one isolated, localhost-only simulation domain')
    output = args.output.expanduser().resolve()
    if output.exists() or output.is_relative_to(ROOT):
        parser.error('Output must be a new directory outside the repository')
    node_binary = shutil.which('node')
    if not node_binary or not Path(args.chromium).is_file():
        parser.error('Node and an explicit Chromium executable are required')
    browser_script = Path(__file__).with_suffix('.cjs')
    if not browser_script.is_file():
        parser.error('The companion browser acceptance script is missing')
    output.mkdir(parents=True, mode=0o700)
    report = {'passed': False, 'domain': args.domain, 'checks': [], 'errors': [],
              'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (Path(__file__), browser_script)}}
    if args.runtime_manifest:
        manifest = args.runtime_manifest.expanduser().resolve()
        report['runtime_manifest'] = {'path': str(manifest),
            'sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(),
            'scope': 'Reference only; process/source identity is independently audited'}
    stream = (output/'truth.jsonl').open('w', buffering=1)
    log = (output/'browser.log').open('w')
    samples, errors, lock = [], [], threading.Lock()
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.signals import SignalHandlerOptions
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
    from nav2_msgs.srv import GetCostmap
    from nav_msgs.msg import OccupancyGrid
    sys.path.insert(0, str(ROOT/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/scripts'))
    from verify_stack import Probe

    class Observer(Probe):
        def on_truth(self, msg):
            previous = self.truth_updates
            super().on_truth(msg)
            if self.truth is None or self.truth_updates == previous:
                return
            pose = self.truth.pose.pose
            q = pose.orientation
            linear, angular = self.planar_speed()
            frame = {'epoch': time.time(), 'steady_time': time.monotonic(), 'stamp': self.truth_time,
                'ros_now': self.get_clock().now().nanoseconds*1e-9,
                'x': pose.position.x, 'y': pose.position.y,
                'yaw': math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z)),
                'linear_speed': linear, 'angular_speed': angular}
            with lock:
                try:
                    if not all(math.isfinite(value) for value in frame.values()):
                        raise ValueError('Nonfinite independent truth')
                    samples.append(frame)
                    stream.write(json.dumps(frame)+'\n')
                except Exception as error:
                    errors.append(str(error))

    def get(path):
        status, value = request(args.api, path)
        if status != 200:
            raise RuntimeError(f'GET {path}: {status}')
        return value

    def frames():
        with lock:
            if errors:
                raise RuntimeError(errors[0])
            return [frame.copy() for frame in samples]

    def fresh():
        observed = frames()
        if not observed:
            raise RuntimeError('No independent truth')
        last = observed[-1]
        current_ros = observer.get_clock().now().nanoseconds*1e-9
        if (time.monotonic()-last['steady_time'] > .25
                or not -.05 <= current_ros-last['stamp'] <= .25):
            raise RuntimeError('Independent truth is not currently fresh')
        return last

    def quiet_tail(after):
        def quiet(_):
            fresh()
            observed = [frame for frame in frames() if frame['steady_time'] >= after]
            if len(observed) < 2:
                return False
            truth_metrics(observed)
            index = len(observed)-1
            while index >= 0 and stationary(observed[index]):
                index -= 1
            tail = observed[index+1:]
            return len(tail) > 1 and min(tail[-1]['steady_time']-tail[0]['steady_time'],
                                       tail[-1]['stamp']-tail[0]['stamp']) >= .7
        wait_for(lambda: None, quiet, 15)

    def marker():
        path = output/'marker.json'
        return json.loads(path.read_text()) if path.exists() else {}

    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    observer = Observer(SimpleNamespace(mode='sensors', odom='/odom', scan='/scan',
        truth='/ground_truth/free_joint_states', cmd='/cmd_vel'))
    observer.keepout_mask = None
    observer.create_subscription(OccupancyGrid, '/keepout_filter_mask',
        lambda value: setattr(observer, 'keepout_mask', value),
        QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                   durability=DurabilityPolicy.TRANSIENT_LOCAL))
    executor = SingleThreadedExecutor()
    executor.add_node(observer)
    worker = threading.Thread(target=executor.spin, daemon=True)
    worker.start()
    costmap_clients = {name: observer.create_client(GetCostmap, f'/{name}_costmap/get_costmap')
                       for name in ('global', 'local')}

    def native_cleared_point(label):
        mask = wait_for(lambda: observer.keepout_mask, lambda value: value is not None, 8)
        if mask.header.frame_id != 'map':
            raise RuntimeError('The actual keepout mask is not in the map frame')
        origin, q = mask.info.origin.position, mask.info.origin.orientation
        yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
        dx, dy = .60-origin.x, -origin.y
        col = math.floor((math.cos(yaw)*dx+math.sin(yaw)*dy)/mask.info.resolution)
        row = math.floor((-math.sin(yaw)*dx+math.cos(yaw)*dy)/mask.info.resolution)
        if not 0 <= col < mask.info.width or not 0 <= row < mask.info.height:
            raise RuntimeError('The actual mask does not cover the formerly forbidden point')
        if mask.data[row*mask.info.width+col] != 0:
            raise RuntimeError('The formerly forbidden point remains in the actual keepout mask')
        snapshots = {}
        report.setdefault('native_costmaps', {})[label] = snapshots
        for name, client in costmap_clients.items():
            if not client.wait_for_service(timeout_sec=4):
                raise RuntimeError(f'{name} costmap service unavailable')
            # A new observer must discover map->odom and accumulate its
            # snapshot-time history. Retry only this read, never a mutation.
            deadline = time.monotonic()+8
            while True:
                future = client.call_async(GetCostmap.Request())
                response = wait_for(lambda: future.result() if future.done() else None,
                                    lambda value: value is not None, 4)
                grid = response.map
                if (grid.header.frame_id == 'map' or observer.buffer.can_transform(
                        grid.header.frame_id, 'map', rclpy.time.Time.from_msg(grid.metadata.update_time))):
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('Native snapshot-time map transform is unavailable')
                time.sleep(.12)
            grid = response.map
            meta = grid.metadata
            stamp = meta.update_time.sec+meta.update_time.nanosec*1e-9
            now = observer.get_clock().now().nanoseconds*1e-9
            if not -.05 <= now-stamp <= 1.5:
                raise RuntimeError('Native costmap snapshot is not fresh')
            x, y = .60, 0.
            if grid.header.frame_id != 'map':
                t = observer.buffer.lookup_transform(grid.header.frame_id, 'map',
                    rclpy.time.Time.from_msg(meta.update_time)).transform
                q = t.rotation
                yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
                x, y = (t.translation.x+math.cos(yaw)*x-math.sin(yaw)*y,
                        t.translation.y+math.sin(yaw)*x+math.cos(yaw)*y)
            p, q = meta.origin.position, meta.origin.orientation
            yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
            dx, dy = x-p.x, y-p.y
            col = math.floor((math.cos(yaw)*dx+math.sin(yaw)*dy)/meta.resolution)
            row = math.floor((-math.sin(yaw)*dx+math.cos(yaw)*dy)/meta.resolution)
            if not 0 <= col < meta.size_x or not 0 <= row < meta.size_y:
                raise RuntimeError('Native costmap does not cover the formerly forbidden point')
            value = int(grid.data[row*meta.size_x+col])
            if label == 'before_ui_task' and name == 'global':
                # A UI deletion test needs an initially free patch. Removing
                # software keepouts cannot erase real sensor obstacles.
                count = 0
                for fx in (1.95+index*.05 for index in range(9)):
                    for fy in (1.95+index*.05 for index in range(9)):
                        gx, gy = fx-p.x, fy-p.y
                        cx = math.floor((math.cos(yaw)*gx+math.sin(yaw)*gy)/meta.resolution)
                        cy = math.floor((-math.sin(yaw)*gx+math.cos(yaw)*gy)/meta.resolution)
                        if (not 0 <= cx < meta.size_x or not 0 <= cy < meta.size_y
                                or int(grid.data[cy*meta.size_x+cx]) != 0):
                            raise RuntimeError('The UI temporary rule patch is not initially free')
                        count += 1
                report['temporary_zone_fixture'] = {'corners': [[2., 2.], [2.3, 2.3]],
                    'initial_native_global_cost': 0, 'checked_points_including_raster_margin': count}
            snapshots[name] = {'frame': grid.header.frame_id, 'update_stamp': stamp,
                               'ros_now': now, 'point_in_map': [.60, 0.], 'cost': value,
                               'actual_keepout_mask_cost': 0,
                               'criterion': 'below Nav2 inscribed cost 253; soft inflation remains valid'}
            if value >= 253:
                raise RuntimeError('The formerly forbidden native point is lethal, unknown or inscribed')

    child = None
    try:
        state = get('state')
        if (state['domain'] != args.domain or state['mode'] != 'mujoco' or not state['ready']
                or state['mission']['status'] in {'running', 'canceling'}):
            raise RuntimeError('An idle, ready simulation is required; existing tasks remain untouched')
        # Keep enough independent TF history for the global costmap's 1 Hz
        # update and the corresponding local snapshot-time transform.
        wait_for(lambda: len(frames()), lambda count: count >= 45)
        if not stationary(fresh()):
            raise RuntimeError('The independent observer does not confirm a stationary start')
        original_rules = get('map-rules')
        report['initial_rules'] = original_rules
        native_cleared_point('before_ui_task')
        child = subprocess.Popen([node_binary, str(browser_script), '--base', args.web,
            '--domain', str(args.domain), '--output', str(output), '--chromium', args.chromium],
            stdout=log, stderr=subprocess.STDOUT)
        wait_for(lambda: child.poll(), lambda code: code is not None, 300)
        browser = json.loads((output/'browser-result.json').read_text())
        report['browser'] = browser
        if child.returncode != 0 or not browser['passed']:
            raise RuntimeError(f'Browser acceptance failed: {browser.get("errors")}')
        owned = marker()
        identity = owned.get('owned_mission_id')
        if not identity or identity == owned.get('before_id'):
            raise RuntimeError('No new browser-owned mission was confirmed')
        terminal = get('state')['mission']
        if terminal['id'] != identity or terminal['status'] != 'succeeded':
            raise RuntimeError('The same browser-owned task must actually succeed')
        quiet_tail(time.monotonic())
        observed = frames()
        boundary = [frame for frame in observed if frame['epoch'] < owned['dispatch_epoch']]
        if not boundary or owned['dispatch_epoch']-boundary[-1]['epoch'] > .25:
            raise RuntimeError('The dispatch boundary has no fresh independent frame')
        trajectory = [boundary[-1]] + [frame for frame in observed if frame['epoch'] >= owned['dispatch_epoch']]
        timing = truth_metrics(trajectory)
        fresh()
        expected = owned['requested_body']['waypoints']
        if owned['requested_body']['return_home']:
            expected = [*expected, get('state')['home']]
        visits, cursor = [], 0
        for target in expected:
            for index in range(cursor, len(trajectory)):
                frame = trajectory[index]
                if math.hypot(frame['x']-target['x'], frame['y']-target['y']) <= .15:
                    visits.append({'target': target, 'truth': frame})
                    cursor = index+1
                    break
            else:
                raise RuntimeError('Independent truth did not visit every template waypoint in order')
        former_zone = [frame for frame in trajectory
            if .45 <= frame['x'] <= .75 and -.3 <= frame['y'] <= .3]
        if not former_zone:
            raise RuntimeError('No independent truth entered the deleted keepout')
        target, final = expected[-1], trajectory[-1]
        position_error = math.hypot(final['x']-target['x'], final['y']-target['y'])
        yaw_error = abs(math.atan2(math.sin(final['yaw']-target['yaw']),
                                  math.cos(final['yaw']-target['yaw'])))
        if position_error > .15 or yaw_error > .30:
            raise RuntimeError('Independent template endpoint failed')
        def original_applied(rules):
            if rules['map_id'] != original_rules['map_id'] or rules['zones'] != original_rules['zones']:
                raise RuntimeError('The temporary UI rule was not removed without changing existing rules')
            return rules['apply_state'] == 'applied'
        wait_for(lambda: get('map-rules'), original_applied, 30)
        native_cleared_point('after_ui_task')
        runs = get('runs')['runs']
        if not any(run['id'] == identity and run['status'] == 'succeeded'
                   and run['rules_revision'] == owned['rules_revision'] for run in runs):
            raise RuntimeError('Same-ID, same-rules task terminal is not persisted')
        report.update(passed=True, checks=[*browser['checks'], 'ordered_independent_waypoint_visits',
            'deleted_keepout_route_actually_restored', 'same_task_succeeded_and_fresh_continuous_stop'],
            physical={'truth_frames': len(trajectory), **timing, 'ordered_visits': visits,
                'former_keepout_frames': len(former_zone), 'first_former_keepout_truth': former_zone[0],
                'endpoint_error_m': position_error, 'endpoint_yaw_error_rad': yaw_error,
                'stop_window_s': .7}, mission_id=identity)
    except Exception as error:
        report['errors'].append(str(error))
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        try:
            identity = marker().get('owned_mission_id')
            current = get('state')['mission']
            if identity and current['id'] == identity and current['status'] in {'running', 'canceling'}:
                report['failure_cancel'] = request(args.api, 'cancel', {
                    'mission_id': identity, 'issued_at': time.time()})
                wait_for(lambda: get('state'), lambda s: s['mission']['id'] == identity
                    and s['mission']['status'] not in {'running', 'canceling'}, 15)
                quiet_tail(time.monotonic())
        except Exception as cleanup_error:
            report['errors'].append(f'Owned task cleanup unknown: {cleanup_error}')
    finally:
        executor.shutdown(timeout_sec=3)
        worker.join(timeout=3)
        observer.destroy_node()
        rclpy.shutdown()
        stream.close()
        log.close()
        (output/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({key: report.get(key) for key in ('passed', 'checks', 'errors')}, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
