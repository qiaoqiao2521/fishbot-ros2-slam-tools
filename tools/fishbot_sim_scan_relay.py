"""One-shot scan gap for the isolated synthetic passage; source stamps survive."""
import argparse
import json
import math
import os
from pathlib import Path
import time


ROOT = Path(__file__).resolve().parents[1]


class ScanGap:
    def __init__(self, seconds, trigger_distance, record, started_steady):
        if not math.isfinite(seconds) or not .2 <= seconds <= 1.:
            raise ValueError('gap seconds must be 0.2..1')
        if not math.isfinite(trigger_distance) or not .05 <= trigger_distance <= .35:
            raise ValueError('trigger distance must be 0.05..0.35')
        self.seconds, self.trigger_distance, self.record = seconds, trigger_distance, record
        self.started_steady = started_steady
        self.origin = self.truth = self.gap_start = self.gap_end = None
        self.restored = False
        self.dropped = 0
        self.last_forwarded_stamp = None

    def emit(self, event, now, sim_stamp, **values):
        truth = self.truth or {}
        self.record(dict(event=event, steady_time=now, steady_elapsed_s=now-self.started_steady,
            sim_stamp=sim_stamp, truth_stamp=truth.get('stamp'), pose=truth.get('pose'),
            dropped_count=self.dropped, **values))

    def observe_truth(self, x, y, linear_speed, stamp, ros_now, now):
        if not all(math.isfinite(v) for v in (x, y, linear_speed, stamp, ros_now, now)):
            return
        if linear_speed < 0 or stamp <= 0 or not -.05 <= ros_now-stamp <= .25:
            return
        if self.truth is not None and stamp <= self.truth['stamp']:
            return
        self.truth = dict(pose={'x':x, 'y':y}, speed=linear_speed, stamp=stamp, received=now)
        if self.origin is None:
            self.origin = (x, y)
        distance = math.dist(self.origin, (x, y))
        if self.gap_start is None and distance >= self.trigger_distance and linear_speed > .005:
            self.gap_start = now
            self.emit('gap_started', now, ros_now, linear_speed_mps=linear_speed,
                      moved_distance_m=distance, requested_gap_s=self.seconds)

    def tick(self, now, ros_now):
        if self.gap_start is not None and self.gap_end is None and now-self.gap_start >= self.seconds:
            self.gap_end = now
            self.emit('gap_ended', now, ros_now, actual_gap_s=now-self.gap_start)

    def forward(self, message, stamp, now, ros_now, publish):
        self.tick(now, ros_now)
        if self.gap_start is not None and self.gap_end is None:
            self.dropped += 1
            return False
        publish(message)  # Forward this exact newly arrived message; do not rewrite its header.
        if self.gap_end is not None and not self.restored:
            self.restored = True
            self.emit('scan_restored', now, stamp, first_restored_stamp=stamp,
                      last_forwarded_stamp=self.last_forwarded_stamp,
                      scan_gap_elapsed_s=now-self.gap_start)
        self.last_forwarded_stamp = stamp
        return True


class EventRecorder:
    def __init__(self, path):
        path = Path(path)
        if not path.is_absolute():
            raise ValueError('output must be an absolute new JSONL path')
        path = path.resolve()
        if path.is_relative_to(ROOT) and not any(path.is_relative_to(ROOT / name) for name in ('.runs', '.local')):
            raise ValueError('output inside source must be ignored .runs or .local evidence')
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open('x', encoding='utf-8')
        os.fchmod(self.stream.fileno(), 0o600)

    def __call__(self, event):
        self.stream.write(json.dumps(event, allow_nan=False)+'\n')
        self.stream.flush()

    def close(self):
        self.stream.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gap-seconds', type=float, default=.6)
    parser.add_argument('--trigger-distance', type=float, default=.15)
    parser.add_argument('--output', required=True)
    parser.add_argument('--execute', action='store_true')
    args, ros_args = parser.parse_known_args()
    if not args.execute:
        ScanGap(args.gap_seconds, args.trigger_distance, lambda event: None, 0.)
        print('Relay parameters valid; execute absent, no ROS nodes started.')
        return 0
    if (os.environ.get('ROS_DOMAIN_ID') not in ('96', '102')
            or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST'
            or os.environ.get('ROS_STATIC_PEERS', '')):
        raise ValueError('Scan relay requires domain 96 or 102, localhost discovery and no static peers')
    import rclpy
    from mujoco_ros2_control_msgs.msg import FreeJointStateArray
    from rclpy.clock import Clock, ClockType
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import LaserScan
    recorder = EventRecorder(args.output)
    rclpy.init(args=ros_args)
    node = Node('fishbot_sim_scan_relay')
    gap = ScanGap(args.gap_seconds, args.trigger_distance, recorder, time.monotonic())
    qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                     durability=DurabilityPolicy.VOLATILE)
    publisher = node.create_publisher(LaserScan, '/scan', qos)
    def ros_now():
        return node.get_clock().now().nanoseconds * 1e-9
    def stamp(message):
        return message.sec + message.nanosec * 1e-9
    def on_scan(message):
        gap.forward(message, stamp(message.header.stamp), time.monotonic(), ros_now(), publisher.publish)
    def on_truth(message):
        for state in message.free_joints:
            if state.name == 'base_footprint':
                position, velocity = state.pose.pose.position, state.twist.twist.linear
                gap.observe_truth(position.x, position.y, math.hypot(velocity.x, velocity.y),
                                  stamp(message.header.stamp), ros_now(), time.monotonic())
    node.create_subscription(LaserScan, '/scan_raw', on_scan, qos)
    node.create_subscription(FreeJointStateArray, '/ground_truth/free_joint_states', on_truth, qos)
    node.create_timer(.01, lambda: gap.tick(time.monotonic(), ros_now()),
                      clock=Clock(clock_type=ClockType.STEADY_TIME))
    gap.emit('relay_ready', time.monotonic(), ros_now())
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        recorder.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
