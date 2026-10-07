#!/usr/bin/env python3
"""Execute one bounded mapping segment with fresh odom/scan and zero-command exit.

This host-side guard does not replace a firmware watchdog or a physical stop.
No movement occurs without an explicit advance/reverse/turn request and --execute.
Reverse is recovery only: at most 0.15 m at 0.03 m/s with rear clearance.
The standard-model profile assumes the official teaching model's dimensions;
it is not a measurement of this physical robot.
"""

import argparse
import json
import math
from pathlib import Path
import signal
import time

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import LaserScan


def clearance(scan, mode, half_width=0.27, rotation_clearance=0.25):
    points = []
    direction_samples = 0
    for i, distance in enumerate(scan.ranges):
        angle = scan.angle_min + i * scan.angle_increment
        if not math.isfinite(distance) or not scan.range_min <= distance <= scan.range_max:
            continue
        x, y = distance * math.cos(angle), distance * math.sin(angle)
        points.append((x, y, distance))
        direction_x = -x if mode == 'reverse' else x
        if abs(math.atan2(y, direction_x)) < math.pi / 6:
            direction_samples += 1
    if len(points) < 100 or direction_samples < 20:
        return 'insufficient scan coverage'
    if mode == 'turn':
        if min(p[2] for p in points) < rotation_clearance:
            return 'obstacle inside rotation clearance'
    elif mode == 'reverse':
        if any(-0.34 < x < 0 and abs(y) < half_width for x, y, _ in points):
            return 'obstacle in rear stopping corridor'
    elif any(0 < x < 0.34 and abs(y) < half_width for x, y, _ in points):
        return 'obstacle in forward stopping corridor'
    return None


class Segment(Node):
    def __init__(self):
        super().__init__('fishbot_guarded_mapping')
        qos = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=1,
                         reliability=ReliabilityPolicy.BEST_EFFORT)
        self.publisher = self.create_publisher(Twist, '/cmd_vel', qos)
        self.odom = self.scan = None
        self.odom_at = self.scan_at = 0.0
        self.yaw = self.unwrapped_yaw = None
        self.odom_count = self.scan_count = 0
        self.create_subscription(Odometry, '/odom', self.on_odom, qos)
        self.create_subscription(LaserScan, '/scan', self.on_scan, qos)

    def on_odom(self, msg):
        q = msg.pose.pose.orientation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y*q.y + q.z*q.z))
        if self.yaw is None:
            self.unwrapped_yaw = yaw
        else:
            delta = yaw - self.yaw
            self.unwrapped_yaw += math.atan2(math.sin(delta), math.cos(delta))
        self.yaw = yaw
        self.odom, self.odom_at = msg, time.monotonic()
        self.odom_count += 1

    def on_scan(self, msg):
        self.scan, self.scan_at = msg, time.monotonic()
        self.scan_count += 1

    def fresh(self):
        now = time.monotonic()
        for name, msg, received, limit in (
            ('odom', self.odom, self.odom_at, 0.25),
            ('scan', self.scan, self.scan_at, 0.50),
        ):
            if msg is None or now - received > limit:
                return name + ' receive timeout'
            age = time.time() - msg.header.stamp.sec - msg.header.stamp.nanosec / 1e9
            if not math.isfinite(age) or not -0.05 <= age <= limit:
                return name + ' timestamp outside freshness limit'
        p, q, v = self.odom.pose.pose.position, self.odom.pose.pose.orientation, self.odom.twist.twist
        values = (p.x, p.y, self.unwrapped_yaw, q.x, q.y, q.z, q.w, v.linear.x, v.angular.z)
        if not all(value is not None and math.isfinite(value) for value in values):
            return 'nonfinite odometry'
        if not 0.8 <= q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w <= 1.2:
            return 'invalid odometry orientation'
        return None

    def command(self, v=0.0, w=0.0):
        msg = Twist()
        msg.linear.x, msg.angular.z = v, w
        self.publisher.publish(msg)

    def pose(self):
        p = self.odom.pose.pose.position
        return [p.x, p.y, self.unwrapped_yaw]

    def stationary(self):
        return (self.odom is not None and abs(self.odom.twist.twist.linear.x) < 0.008
                and abs(self.odom.twist.twist.angular.z) < 0.025)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('advance', 'reverse', 'turn'))
    parser.add_argument('--amount', type=float, required=True,
                        help='advance/reverse: positive metres (reverse recovery max 0.15); '
                             'turn: signed radians (+left, -right)')
    parser.add_argument('--profile', choices=('conservative', 'standard-model'),
                        default='conservative',
                        help='standard-model uses official teaching-model dimensions, not robot measurements')
    parser.add_argument('--hold-heading', action='store_true',
                        help='advance only: correct yaw drift toward the initial heading')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    limit = 0.15 if args.mode == 'reverse' else (0.30 if args.mode == 'advance' else math.pi * 2)
    amount = abs(args.amount)
    if (not args.execute or not math.isfinite(args.amount) or not 0 < amount <= limit
            or (args.mode != 'turn' and args.amount < 0)
            or (args.hold_heading and args.mode != 'advance')):
        parser.error('--execute required; advance: 0 < metres <= 0.30; '
                     'reverse recovery: 0 < metres <= 0.15; turn: 0 < |radians| <= 2*pi; '
                     '--hold-heading is allowed only with advance')
    turn_sign = 1.0 if args.amount > 0 else -1.0
    linear_sign = -1.0 if args.mode == 'reverse' else 1.0
    half_width = 0.18 if args.profile == 'standard-model' else 0.27
    # Teaching model: hypot(0.052, 0.12) + 0.06 margin, rounded up to 0.20 m.
    rotation_clearance = 0.20 if args.profile == 'standard-model' else 0.25
    if args.output.exists():
        parser.error('evidence output already exists')
    from rclpy.signals import SignalHandlerOptions
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = Segment()
    interrupted = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda signum, frame: interrupted.append(signum))
    speed = (0.25 if args.mode == 'turn' else
             (0.03 if args.mode == 'reverse' or args.profile == 'standard-model' else 0.06))
    result = {'mode': args.mode, 'requested': args.amount, 'completed': False,
              'stopped': False, 'samples': [], 'profile': args.profile,
              'half_width': half_width,
              'rotation_clearance': rotation_clearance,
              'speed': speed * turn_sign if args.mode == 'turn' else speed * linear_sign,
              'speed_semantics': 'signed nominal maximum; per-sample command_v/command_w are published velocities',
              'hold_heading': args.hold_heading,
              'heading_hold_gain': 4.0, 'heading_hold_rate_cap': 0.10,
              'model_assumption': (
                  'official teaching model: width 0.24 m plus 0.06 m per side; '
                  'not measured on this robot'
                  if args.profile == 'standard-model' else None)}
    try:
        ready_until = time.monotonic() + 8
        while time.monotonic() < ready_until and not interrupted:
            rclpy.spin_once(node, timeout_sec=0.02)
            if (node.odom_count >= 30 and node.scan_count >= 15
                    and node.fresh() is None):
                break
        if node.fresh() or node.odom_count < 30 or node.scan_count < 15:
            raise RuntimeError(node.fresh() or 'insufficient live samples')
        others = [p.node_name for p in node.get_publishers_info_by_topic('/cmd_vel')
                  if p.node_name != node.get_name()]
        receivers = [p.node_name for p in node.get_subscriptions_info_by_topic('/cmd_vel')]
        if others or receivers != ['fishbot_motion_control']:
            raise RuntimeError('unexpected command publisher/subscriber ownership')
        if not node.stationary():
            raise RuntimeError('robot was already moving')
        start = node.pose()
        result['start'] = start
        began = time.monotonic()
        deadline = began + amount / speed + 5
        next_publish = 0.0
        while not interrupted:
            rclpy.spin_once(node, timeout_sec=0.01)
            now = time.monotonic()
            if now < next_publish:
                continue
            next_publish = now + 0.05
            reason = node.fresh() or clearance(node.scan, args.mode, half_width=half_width,
                                               rotation_clearance=rotation_clearance)
            if reason:
                raise RuntimeError(reason)
            current = node.pose()
            distance = math.hypot(current[0]-start[0], current[1]-start[1])
            angle = current[2]-start[2]
            forward = ((current[0]-start[0])*math.cos(start[2])
                       + (current[1]-start[1])*math.sin(start[2]))
            lateral = (-(current[0]-start[0])*math.sin(start[2])
                       + (current[1]-start[1])*math.cos(start[2]))
            turn_progress = angle * turn_sign
            linear_progress = forward * linear_sign
            if args.mode in ('advance', 'reverse'):
                if linear_progress < -0.01 or abs(angle) > 0.20 or abs(lateral) > 0.04:
                    raise RuntimeError('unexpected motion direction')
            elif turn_progress < -0.03 or distance > 0.05:
                raise RuntimeError('unexpected rotation response')
            progress = turn_progress if args.mode == 'turn' else linear_progress
            if progress > 0.003 and 'first_motion_response_s' not in result:
                result['first_motion_response_s'] = now-began
            result['samples'].append({'elapsed': now-began, 'pose': current,
                                      'v': node.odom.twist.twist.linear.x,
                                      'w': node.odom.twist.twist.angular.z})
            if progress >= amount:
                result['completed'] = True
                break
            if now > deadline:
                raise RuntimeError('segment deadline exceeded')
            if now-began > 1.5 and progress < 0.003:
                raise RuntimeError('no timely measured motion response')
            command_v = speed * linear_sign if args.mode != 'turn' else 0.0
            command_w = (turn_sign * max(0.06, min(speed, 2 * (amount-progress)))
                         if args.mode == 'turn' else 0.0)
            if args.hold_heading:
                command_w = max(-0.10, min(0.10, -4.0 * angle))
                if command_w != 0.0:
                    correction_reason = clearance(node.scan, 'turn', half_width=half_width,
                                                  rotation_clearance=rotation_clearance)
                    if correction_reason:
                        raise RuntimeError('heading correction unsafe: ' + correction_reason)
            node.command(command_v, command_w)
            result['samples'][-1].update({'command_v': command_v, 'command_w': command_w})
        if interrupted:
            result['error'] = 'interrupted'
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        # Continue sending fresh zero commands while measuring actual stopping.
        stop_started = time.monotonic()
        stopped_since = None
        stop_errors = set()
        while time.monotonic() - stop_started < 8:
            try:
                node.command()
            except Exception as exc:
                stop_errors.add('zero publish: ' + str(exc))
            until = time.monotonic() + 0.05
            while time.monotonic() < until:
                try:
                    rclpy.spin_once(node, timeout_sec=0.01)
                except Exception as exc:
                    stop_errors.add('stop observation: ' + str(exc))
                    time.sleep(0.01)
            now = time.monotonic()
            if not stop_errors and node.fresh() is None and node.stationary():
                stopped_since = stopped_since or now
                if 'first_stationary_after_zero_s' not in result:
                    result['first_stationary_after_zero_s'] = now-stop_started
                if now-stopped_since > 1.0 and now-stop_started >= 5.0:
                    result['stopped'] = True
                    break
            else:
                stopped_since = None
        result['stop_observation_s'] = time.monotonic()-stop_started
        result['end'] = node.pose() if node.odom is not None else None
        if stop_errors:
            result['stop_errors'] = sorted(stop_errors)
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2))
            args.output.chmod(0o600)
            print(json.dumps({k:v for k,v in result.items() if k != 'samples'}), flush=True)
        finally:
            node.destroy_node()
            rclpy.shutdown()
    return 0 if result['completed'] and result['stopped'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
