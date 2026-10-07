#!/usr/bin/python3
"""Domain-98 semantic inspection with active views and feedback-based charging."""
import argparse
from collections import deque
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import time

from PIL import Image as PillowImage

from fishbot_inspection import (decode_rgb, fresh, pose_error, pose_values,
                               stamp_seconds, validate_capture_pose)
from fishbot_passage_goal import PendingGoal
from fishbot_home_semantics import analyze_observation, next_observation, parse_task
from fishbot_home_report import save_home_report


class LowBattery(RuntimeError):
    """A resumable task interruption, after cancellation and stationary feedback."""


class BatteryDepleted(RuntimeError):
    """A terminal motion failure, independent of the configurable recharge threshold."""


def validate_environment(env):
    if (env.get('ROS_DOMAIN_ID') != '98'
            or env.get('FISHBOT_MUJOCO_DOMAIN_ID') != '98'
            or env.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST'
            or env.get('ROS_STATIC_PEERS', '')):
        raise ValueError('Home mission requires domain 98, localhost and no static peers')


def combined_observation(frames):
    """No single lucky frame can establish an inspection result."""
    signatures = {(f['outcome'], f['state']) for f in frames}
    if len(frames) != 3 or len(signatures) != 1:
        return {'outcome': 'unknown', 'state': 'unknown', 'reason': 'three frames disagree'}
    return {key: frames[-1][key] for key in ('outcome', 'state', 'reason')}


def charge_feedback_ok(battery, status, minimum_soc):
    """Task acceptance independently checks the plugin's cached current result."""
    return (math.isfinite(battery.percentage) and battery.percentage >= minimum_soc
            and math.isfinite(battery.current) and battery.current > .5
            and battery.power_supply_status == battery.POWER_SUPPLY_STATUS_CHARGING
            and status.get('charging') is True and status.get('contact') is True
            and status.get('truth_fresh') is True and status.get('clock_fresh') is True)


def closed_loop_checks(report):
    """Completing a route alone does not pass this three-part acceptance scenario."""
    events = report.get('events', [])
    return {
        'inspection_completed': bool(report.get('steps')) and all(s.get('completed') for s in report['steps']),
        'active_observation': any(
            any(o.get('outcome') == 'unknown' for o in step.get('observations', [])[:-1])
            and step.get('observations', [{}])[-1].get('outcome') in ('found', 'not_found')
            for step in report.get('steps', [])),
        'low_battery_navigation_cancel': any(e.get('event') == 'navigation_canceled_for_charge'
                                             and e.get('result', {}).get('canceled') is True for e in events),
        'charging_and_undocking': any(c.get('charging_verified') is True and c.get('undocked') is True
                                     for c in report.get('recharge_cycles', [])),
        'resumed_task': any(resumed_navigation_ok(report, c) for c in report.get('recharge_cycles', [])),
        'returned_home': report.get('return_home', {}).get('completed') is True,
        'stopped': report.get('final_stationary', {}).get('verified') is True,
    }


def resumed_navigation_ok(report, cycle):
    """Link a completed post-charge navigation to the interrupted place and view."""
    try:
        resume, target = cycle['resumed_navigation'], cycle['resume_target']
        if not (cycle['charging_verified'] is True and cycle['undocked'] is True):
            return False
        if any(resume[key] != target[key] for key in ('step_id', 'place_id', 'view_index')):
            return False
        steps = [s for s in report['steps'] if s['step_id'] == target['step_id']]
        if len(steps) != 1 or steps[0]['place_id'] != target['place_id']:
            return False
        index = resume['attempt_index']
        if type(index) is not int or index < 0:
            return False
        actual = steps[0]['navigation_attempts'][index]
        fields = ('view_index', 'started_stamp', 'completed_stamp', 'action',
                  'goal', 'pose', 'physical_error', 'stationary')
        if any(actual[key] != resume[key] for key in fields):
            return False
        if actual['goal'] != steps[0]['views'][target['view_index']]:
            return False
        action, stopped = actual['action'], actual['stationary']
        undocked = cycle['undocked_stationary']['stamp']
        times = (undocked, actual['started_stamp'], stopped['stamp'], actual['completed_stamp'])
        xy, yaw = pose_error(actual['pose'], actual['goal'])
        return (all(math.isfinite(t) for t in times)
                and undocked < actual['started_stamp'] <= stopped['stamp'] <= actual['completed_stamp']
                and action.get('goal_accepted') is True and action.get('status') == 4
                and action.get('error_code') == 0 and action.get('success', True) is True
                and stopped.get('verified') is True and stopped.get('samples', 0) >= 5
                and stopped.get('duration_s', 0) >= .6 and xy <= .22 and yaw <= .25)
    except (KeyError, IndexError, TypeError, ValueError):
        return False


class HomeMission:
    def __init__(self, args, scene, plan):
        import rclpy
        from rclpy.node import Node
        from rclpy.action import ActionClient
        from rclpy.parameter import Parameter
        from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
        from sensor_msgs.msg import Image, LaserScan, BatteryState
        from nav_msgs.msg import Odometry, OccupancyGrid, Path as RosPath
        from nav2_msgs.action import NavigateToPose, DockRobot, UndockRobot
        from mujoco_ros2_control_msgs.msg import FreeJointStateArray
        from std_msgs.msg import String
        from tf2_ros import Buffer, TransformListener

        self.rclpy, self.args, self.scene, self.plan = rclpy, args, scene, plan
        self.node = Node('fishbot_home_mission', parameter_overrides=[Parameter('use_sim_time', value=True)])
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self.node)
        self.types = {'navigate': NavigateToPose, 'dock': DockRobot, 'undock': UndockRobot}
        self.clients = {kind: ActionClient(self.node, typ, name) for kind, typ, name in (
            ('navigate', NavigateToPose, '/navigate_to_pose'),
            ('dock', DockRobot, '/dock_robot'), ('undock', UndockRobot, '/undock_robot'))}
        self.samples, self.truth_history = {}, deque(maxlen=150)
        self.pending = None
        self.resume_pending = None
        self.interrupts = []
        self.started = time.monotonic()
        sensor_qos = QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST,
                                reliability=ReliabilityPolicy.BEST_EFFORT)
        self.report = {'schema_version': 1, 'environment': 'MuJoCo simulation', 'domain': 98,
                       'overall_status': 'running', 'task': args.task, 'plan': plan,
                       'steps': [], 'events': [], 'trajectory': [], 'battery_history': [],
                       'recharge_cycles': [], 'scene_provenance': scene.get('provenance', {}),
                       'overview': 'fixture/overview.png',
                       'limits': ['Completed unknown map areas are simulation assumptions.',
                                  'Language uses a bounded place/target grammar.',
                                  'Vision recognizes marked synthetic targets from RGB.',
                                  'Charging uses a simulated contact and battery model.']}
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda signum, frame: self.interrupts.append(signum))
        for typ, topic, key in ((Image, '/inspection/camera/image_raw', 'image'),
                                (LaserScan, '/scan', 'scan'), (Odometry, '/odom', 'odom'),
                                (BatteryState, '/battery_state', 'battery')):
            self.node.create_subscription(typ, topic, lambda m, k=key: self.remember(k, m), sensor_qos)
        self.node.create_subscription(FreeJointStateArray, '/ground_truth/free_joint_states', self.truth, sensor_qos)
        self.node.create_subscription(String, '/sim_power/status', self.power_status, 1)
        for topic, key in (('/global_costmap/costmap', 'global_costmap'), ('/local_costmap/costmap', 'local_costmap')):
            self.node.create_subscription(OccupancyGrid, topic, lambda m, k=key: self.remember(k, m), 1)
        for topic in ('/plan', '/docking_trajectory'):
            self.node.create_subscription(RosPath, topic, lambda m, k=topic: self.remember(k, m), 1)

    def now(self):
        return self.node.get_clock().now().nanoseconds * 1e-9

    def remember(self, key, message):
        stamp = stamp_seconds(message.header.stamp)
        self.samples[key] = (message, time.monotonic(), stamp)
        if key == 'battery':
            if (not math.isfinite(message.percentage) or not 0 <= message.percentage <= 1
                    or not math.isfinite(message.current)):
                return  # sample() rejects it; invalid telemetry must not poison JSON evidence.
            history = self.report['battery_history']
            if not history or stamp - history[-1][0] >= .4:
                history.append([stamp, message.percentage, message.current, message.power_supply_status])

    def truth(self, message):
        for body in message.free_joints:
            if body.name == 'base_footprint':
                stamp = stamp_seconds(message.header.stamp)
                self.samples['truth'] = (body, time.monotonic(), stamp)
                self.truth_history.append((stamp, body))
                history = self.report['trajectory']
                if not history or stamp - history[-1][0] >= .2:
                    history.append([stamp, *pose_values(body.pose.pose)])

    def power_status(self, message):
        try:
            status = json.loads(message.data)
            stamp = float(status['sim_stamp'])
            self.samples['power_status'] = (status, time.monotonic(), stamp)
        except (KeyError, ValueError, TypeError):
            self.samples.pop('power_status', None)

    def sample(self, name):
        value = self.samples.get(name)
        if value is None or not fresh(value[2], value[1], self.now(), time.monotonic(), .8):
            ages = '' if value is None else f' (source age {self.now()-value[2]:.3f}s, receive age {time.monotonic()-value[1]:.3f}s)'
            raise RuntimeError(f'{name} missing or stale in source/receive time{ages}')
        if name == 'battery' and (not math.isfinite(value[0].percentage)
                                  or not 0 <= value[0].percentage <= 1
                                  or not math.isfinite(value[0].current)):
            raise RuntimeError('invalid battery state')
        return value

    def event(self, event, **values):
        record = {'event': event, 'stamp': self.now(),
                  'wall_elapsed': round(time.monotonic() - self.started, 3), **values}
        self.report['events'].append(record)
        print(json.dumps(record, ensure_ascii=False, allow_nan=False), flush=True)

    def require_motion_power(self):
        if self.sample('battery')[0].percentage <= 0:
            raise BatteryDepleted('fresh battery feedback is empty; motion must stop')

    def spin(self, deadline, predicate, health=False, monitor_battery=False, cleanup=False):
        while time.monotonic() < deadline:
            self.rclpy.spin_once(self.node, timeout_sec=.025)
            if self.interrupts and not cleanup:
                raise InterruptedError('home mission interrupted')
            if health:
                for name in ('odom', 'scan', 'truth', 'battery', 'power_status'):
                    self.sample(name)
                if not cleanup:
                    self.require_motion_power()
            if predicate():
                return
            if monitor_battery and self.sample('battery')[0].percentage <= self.args.low_soc:
                raise LowBattery('fresh battery feedback below task threshold')
        raise TimeoutError('bounded mission operation timed out')

    def future(self, future, timeout, **kwargs):
        self.spin(time.monotonic() + timeout, future.done, **kwargs)
        return future.result()

    def stationary(self, duration=.6, cleanup=False):
        stable_since, last_stamp, count = None, None, 0
        def settled():
            nonlocal stable_since, last_stamp, count
            body, _, stamp = self.sample('truth')
            odom = self.sample('odom')[0]
            values = [v for twist in (body.twist.twist, odom.twist.twist)
                      for v in (twist.linear.x, twist.linear.y, twist.angular.z)]
            if not all(math.isfinite(v) for v in values):
                raise RuntimeError('nonfinite velocity feedback')
            if max(abs(v) for v in values) > .015:
                stable_since, count = None, 0
                return False
            if stamp != last_stamp:
                last_stamp, count = stamp, count + 1
                if stable_since is None:
                    stable_since = time.monotonic()
            return count >= 5 and time.monotonic() - stable_since >= duration
        self.spin(time.monotonic() + 5, settled, cleanup=cleanup)
        return {'verified': True, 'stamp': self.sample('truth')[2], 'samples': count,
                'pose': pose_values(self.sample('truth')[0].pose.pose), 'duration_s': duration}

    def cancel(self, cleanup=False):
        if self.pending is None:
            return
        pending = self.pending
        pending.cancel()
        self.spin(time.monotonic() + 8,
                  lambda: pending.get_result() is not None and pending.get_result().done(), cleanup=cleanup)
        pending.refresh()
        response = pending.get_result().result()
        if response.status not in (4, 5, 6):
            raise RuntimeError('action cancellation has no terminal result')
        if pending.cancel_future is not None:
            self.future(pending.cancel_future, 3, cleanup=cleanup)
            pending.refresh()
        self.pending = None
        pending.evidence['stop'] = self.stationary(cleanup=cleanup)
        return pending.evidence

    def action(self, kind, goal, record, timeout, monitor_battery=False):
        self.require_motion_power()
        record['kind'] = kind
        evidence = record.setdefault('action', {})
        self.pending = PendingGoal(evidence)
        began = time.monotonic()
        try:
            handle = self.future(self.pending.track(self.clients[kind].send_goal_async(goal)), 8, health=True)
            if self.pending.handle is None:
                self.pending._accepted(self.pending.send_future)
            if not handle.accepted:
                raise RuntimeError(f'{kind} goal rejected')
            response = self.future(self.pending.get_result(), timeout, health=True, monitor_battery=monitor_battery)
            evidence.update(status=response.status, error_code=response.result.error_code,
                            elapsed_s=round(time.monotonic() - began, 3))
            if hasattr(response.result, 'success'):
                evidence['success'] = response.result.success
            if response.status != 4 or response.result.error_code != 0 or evidence.get('success') is False:
                if hasattr(response.result, 'error_msg'):
                    evidence['error_msg'] = response.result.error_msg
                raise RuntimeError(f'{kind} failed: {evidence}')
            self.pending = None
        except LowBattery:
            self.event('low_battery_interrupt', percentage=self.sample('battery')[0].percentage, action=kind)
            self.cancel()
            self.event('navigation_canceled_for_charge', result=evidence)
            raise

    def navigate(self, target, record, monitor_battery=True):
        record['goal'] = target
        record['started_stamp'] = self.now()
        goal = self.types['navigate'].Goal()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = self.node.get_clock().now().to_msg()
        goal.pose.pose.position.x, goal.pose.pose.position.y = target[:2]
        goal.pose.pose.orientation.z, goal.pose.pose.orientation.w = math.sin(target[2] / 2), math.cos(target[2] / 2)
        goal.behavior_tree = str(Path(__file__).parent / 'config/fishbot_home_tree.xml')
        self.action('navigate', goal, record, self.args.goal_timeout, monitor_battery)
        record['stationary'] = self.stationary()
        record['pose'] = pose_values(self.sample('truth')[0].pose.pose)
        xy, yaw = pose_error(record['pose'], target)
        record['physical_error'] = {'xy_m': xy, 'yaw_rad': yaw}
        if xy > .22 or yaw > .25:
            raise RuntimeError('Nav2 success outside independent physical pose tolerance')
        transform = self.buffer.lookup_transform('map', 'base_footprint', self.rclpy.time.Time())
        if abs(self.now() - stamp_seconds(transform.header.stamp)) > .8:
            raise RuntimeError('localization transform stale')
        record['completed_stamp'] = self.now()

    def record_resumed_navigation(self, step, view_index, attempt, attempt_index):
        if self.resume_pending is None:
            return
        cycle = self.report['recharge_cycles'][self.resume_pending]
        fields = ('started_stamp', 'completed_stamp', 'action', 'goal', 'pose',
                  'physical_error', 'stationary')
        cycle['resumed_navigation'] = {
            'step_id': step['step_id'], 'place_id': step['place_id'],
            'view_index': view_index, 'attempt_index': attempt_index,
            **{key: attempt[key] for key in fields}}
        if not resumed_navigation_ok(self.report, cycle):
            raise RuntimeError('post-charge navigation does not prove the interrupted task resumed')
        self.event('task_resumed', cycle_index=self.resume_pending, **cycle['resumed_navigation'])
        self.resume_pending = None

    def capture(self, step, record):
        last, deadline = self.now(), time.monotonic() + 8
        frames = []
        while len(frames) < 3:
            self.spin(deadline, lambda: self.samples.get('image') is not None
                      and self.samples['image'][2] > last, health=True)
            message, _, stamp = self.sample('image')
            truth_stamp, body = min(self.truth_history, key=lambda item: abs(item[0] - stamp))
            twist = body.twist.twist
            binding = validate_capture_pose(message.header.frame_id, stamp, truth_stamp,
                pose_values(body.pose.pose), [twist.linear.x, twist.linear.y, twist.angular.z], record['goal'])
            rgb = decode_rgb(message)
            result = analyze_observation(rgb, step['target'])
            photo = f"step-{len(self.report['steps'])}-view-{record['view_index']}-frame-{len(frames)+1}.png"
            path = self.args.output / photo
            PillowImage.fromarray(rgb).save(path)
            frames.append({'photo': photo, 'capture_stamp': stamp, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                           **binding, **result})
            last = stamp
        record.update(frames=frames, photo=frames[-1]['photo'], **combined_observation(frames))
        record['post_capture_stationary'] = self.stationary(.3)
        self.event('observation', place_id=step['place_id'], view_index=record['view_index'],
                   outcome=record['outcome'], state=record['state'], photo=record['photo'])

    def recharge(self, step, view_index):
        if len(self.report['recharge_cycles']) >= 2:
            raise RuntimeError('bounded recharge budget exhausted')
        cycle = {'battery_before': self.sample('battery')[0].percentage,
                 'cycle_index': len(self.report['recharge_cycles']),
                 'resume_target': {'step_id': step['step_id'], 'place_id': step['place_id'],
                                   'view_index': view_index}}
        self.report['recharge_cycles'].append(cycle)
        self.event('docking_started', battery=cycle['battery_before'])
        goal = self.types['dock'].Goal()
        goal.use_dock_id = True
        goal.dock_id = self.scene['dock'].get('id', 'home_dock')
        goal.max_staging_time = 120.
        goal.navigate_to_staging_pose = True
        self.action('dock', goal, cycle.setdefault('docking', {}), 180)
        cycle['docked_stationary'] = self.stationary()
        # The stock dock server can succeed on geometric arrival before the
        # independent contact sensor's dwell and charging response have arrived.
        self.spin(time.monotonic() + 8,
                  lambda: charge_feedback_ok(self.sample('battery')[0], self.sample('power_status')[0], 0.),
                  health=True)
        start_soc = self.sample('battery')[0].percentage
        started, last_stamp, samples = None, None, 0
        def charged():
            nonlocal started, last_stamp, samples
            battery, _, stamp = self.sample('battery')
            status = self.sample('power_status')[0]
            if not charge_feedback_ok(battery, status, 0.):
                raise RuntimeError('DockRobot success without fresh contact and charging feedback')
            if started is None:
                started = stamp
            if stamp != last_stamp:
                last_stamp, samples = stamp, samples + 1
            return (stamp - started >= 1. and samples >= 5 and battery.percentage >= self.args.resume_soc
                    and battery.percentage - start_soc >= .03)
        self.spin(time.monotonic() + 40, charged, health=True)
        cycle.update(charging_verified=True, battery_after=self.sample('battery')[0].percentage,
                     charge_samples=samples, status=self.sample('power_status')[0])
        self.event('charging_verified', battery_before=cycle['battery_before'], battery_after=cycle['battery_after'])
        undock = self.types['undock'].Goal()
        undock.dock_type = self.scene['dock'].get('type', 'home_charging_dock')
        undock.max_undocking_time = 40.
        self.action('undock', undock, cycle.setdefault('undocking', {}), 45)
        cycle['undocked_stationary'] = self.stationary()
        self.spin(time.monotonic() + 4, lambda: self.sample('battery')[0].current <= 0
                  and self.sample('power_status')[0].get('contact') is False
                  and self.sample('power_status')[0].get('charging') is False, health=True)
        cycle['undocked'] = True
        cycle['undocked_power_status'] = self.sample('power_status')[0]
        self.resume_pending = cycle['cycle_index']
        self.event('task_resume_ready', cycle_index=self.resume_pending,
                   **cycle['resume_target'], battery=self.sample('battery')[0].percentage)
        self.persist()

    def ready(self):
        from lifecycle_msgs.srv import GetState
        def streams():
            try:
                for name in ('image', 'odom', 'scan', 'truth', 'battery', 'power_status'):
                    self.sample(name)
                return all(c.server_is_ready() for c in self.clients.values()) and self.buffer.can_transform(
                    'map', 'base_footprint', self.rclpy.time.Time())
            except RuntimeError:
                return False
        self.spin(time.monotonic() + 60, streams)
        for name in ('amcl', 'controller_server', 'bt_navigator', 'collision_monitor', 'docking_server'):
            client = self.node.create_client(GetState, f'/{name}/get_state')
            try:
                until = time.monotonic() + 20
                while time.monotonic() < until:
                    if client.wait_for_service(timeout_sec=.2):
                        state = self.future(client.call_async(GetState.Request()), 3)
                        if state.current_state.id == 3:
                            break
                else:
                    raise RuntimeError(f'{name} not ACTIVE')
            finally:
                self.node.destroy_client(client)
        pubs = sorted(p.node_name for p in self.node.get_publishers_info_by_topic('/cmd_vel'))
        subs = sorted(p.node_name for p in self.node.get_subscriptions_info_by_topic('/cmd_vel'))
        if pubs != ['collision_monitor'] or subs != ['diff_drive_controller']:
            raise RuntimeError(f'unexpected final command topology: {pubs} -> {subs}')
        self.report['command_chain'] = {'publishers': pubs, 'subscribers': subs}
        self.report['initial_stationary'] = self.stationary()
        self.event('mission_ready', battery=self.sample('battery')[0].percentage)

    def persist(self):
        self.report['elapsed_s'] = round(time.monotonic() - self.started, 3)
        temporary = self.args.output / 'report.json.tmp'
        temporary.write_text(json.dumps(self.report, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
        temporary.replace(self.args.output / 'report.json')
        save_home_report(self.report, self.args.output)

    def save_diagnostics(self):
        """Retain the actual planner inputs when an integrated trial stops."""
        data = {'stamp': self.now()}
        for key in ('global_costmap', 'local_costmap'):
            if key in self.samples:
                grid, received, stamp = self.samples[key]
                data[key] = {'stamp': stamp, 'frame': grid.header.frame_id,
                             'resolution': grid.info.resolution, 'width': grid.info.width,
                             'height': grid.info.height, 'origin': pose_values(grid.info.origin),
                             'data': list(grid.data)}
        if 'scan' in self.samples:
            scan, _, stamp = self.samples['scan']
            data['scan'] = {'stamp': stamp, 'frame': scan.header.frame_id,
                            'angle_min': scan.angle_min, 'angle_increment': scan.angle_increment,
                            'ranges': [v if math.isfinite(v) else None for v in scan.ranges]}
        for key in ('odom', 'truth'):
            if key in self.samples:
                body, _, stamp = self.samples[key]
                data[key] = {'stamp': stamp, 'pose': pose_values(body.pose.pose)}
        if 'power_status' in self.samples:
            data['power_status'] = self.samples['power_status'][0]
        for key in ('/plan', '/docking_trajectory'):
            if key in self.samples:
                path, _, stamp = self.samples[key]
                data[key] = {'stamp': stamp, 'frame': path.header.frame_id,
                             'poses': [pose_values(p.pose) for p in path.poses]}
        for frame in ('base_footprint', 'laser_link', 'odom'):
            try:
                tf = self.buffer.lookup_transform('map', frame, self.rclpy.time.Time())
                q, p = tf.transform.rotation, tf.transform.translation
                data['map_to_' + frame] = {'stamp': stamp_seconds(tf.header.stamp),
                    'xyz': [p.x, p.y, p.z], 'xyzw': [q.x, q.y, q.z, q.w]}
            except Exception as exc:
                data['map_to_' + frame] = {'error': str(exc)}
        (self.args.output / 'diagnostics.json').write_text(json.dumps(data, allow_nan=False) + '\n')

    def run(self):
        try:
            self.ready()
            for step in self.plan['steps']:
                record = {**step, 'observations': [], 'navigation_attempts': [], 'completed': False}
                self.report['steps'].append(record)
                while True:
                    decision = next_observation(step, record['observations'])
                    if decision['status'] != 'observe':
                        record.update(completed=decision['status'] in ('complete', 'not_found'),
                                      outcome='found' if decision['status'] == 'complete' else decision['status'],
                                      decision_status=decision['status'], reason=decision['reason'])
                        if not record['completed']:
                            raise RuntimeError('active observation exhausted without a reliable answer')
                        break
                    view_index = decision['view_index']
                    view = step['views'][view_index]
                    attempt = {'view_index': view_index}
                    record['navigation_attempts'].append(attempt)
                    self.event('navigate_to_view', place_id=step['place_id'], view_index=view_index)
                    try:
                        self.navigate(view, attempt)
                    except LowBattery:
                        self.recharge(step, view_index)
                        continue
                    self.record_resumed_navigation(step, view_index, attempt,
                                                   len(record['navigation_attempts'])-1)
                    if self.sample('battery')[0].percentage <= self.args.low_soc:
                        self.event('low_battery_at_view', place_id=step['place_id'])
                        self.recharge(step, view_index)
                        continue
                    self.capture(step, attempt)
                    record['observations'].append(attempt)
                    self.persist()
                    if attempt['outcome'] == 'unknown':
                        self.event('active_reobservation', place_id=step['place_id'], previous_view=view_index)
            if self.plan.get('return_home', True):
                home = self.scene.get('home', [0., 0., 0.])
                self.navigate(home, self.report.setdefault('return_home', {}), monitor_battery=False)
                self.report['return_home']['completed'] = True
            self.report['overall_status'] = 'completed'
        except Exception as exc:
            self.report.update(overall_status='interrupted' if self.interrupts else 'failed',
                               error=f'{type(exc).__name__}: {exc}')
            self.event('mission_failed', error=self.report['error'])
        finally:
            if self.pending is not None:
                try:
                    self.cancel(cleanup=True)
                except Exception as exc:
                    self.report.setdefault('cleanup_errors', []).append('cancel: ' + str(exc))
            try:
                self.report['final_stationary'] = self.stationary(1., cleanup=True)
            except Exception as exc:
                self.report['overall_status'] = 'failed'
                self.report.setdefault('cleanup_errors', []).append('stop: ' + str(exc))
            # Synchronous diagnostic I/O must never postpone motion cancellation.
            try:
                self.save_diagnostics()
            except Exception as exc:
                self.report.setdefault('diagnostic_errors', []).append(str(exc))
            self.report['closed_loop_checks'] = closed_loop_checks(self.report)
            if self.report['overall_status'] == 'completed' and not all(self.report['closed_loop_checks'].values()):
                self.report['overall_status'] = 'incomplete_scenario'
                self.report['error'] = 'route completed, but required active-observation or charging scenario was not exercised'
            try:
                self.persist()
            finally:
                self.node.destroy_node()
        return self.report['overall_status'] == 'completed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--task', default='去工具架找红色盒子，看看门口指示灯，再去观察点找红色盒子，然后回来')
    parser.add_argument('--goal-timeout', type=float, default=120.)
    parser.add_argument('--low-soc', type=float, default=.28)
    parser.add_argument('--resume-soc', type=float, default=.8)
    args = parser.parse_args()
    validate_environment(os.environ)
    if not (1 <= args.goal_timeout <= 180 and 0 < args.low_soc < args.resume_soc <= .95):
        parser.error('invalid action deadline or battery thresholds')
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / 'report.json').exists():
        parser.error('use a fresh report output directory')
    scene = json.loads(args.scene.read_text())
    plan = parse_task(args.task, scene)
    import rclpy
    from rclpy.signals import SignalHandlerOptions
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    try:
        success = HomeMission(args, scene, plan).run()
    finally:
        rclpy.try_shutdown()
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
