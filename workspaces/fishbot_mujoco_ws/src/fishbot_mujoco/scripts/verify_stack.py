#!/usr/bin/python3
"""Bounded simulation acceptance: action success AND measured MuJoCo position.

Run only in domain 93 with loopback discovery; never drive the real robot.
"""
import argparse
import json
import math
import os
import time
from pathlib import Path

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from geometry_msgs.msg import TwistStamped
from nav_msgs.msg import Odometry
from nav2_msgs.action import NavigateToPose
from sensor_msgs.msg import LaserScan
from lifecycle_msgs.srv import GetState
from mujoco_ros2_control_msgs.msg import FreeJointStateArray
from tf2_ros import Buffer, TransformListener


class Probe(Node):
    def __init__(self, args):
        super().__init__('fishbot_mujoco_acceptance', parameter_overrides=[
            rclpy.parameter.Parameter('use_sim_time', value=True)])
        self.args = args
        self.odom = None
        self.truth = None
        self.truth_time = None
        self.truth_wall_time = None
        self.truth_updates = 0
        self.trajectory = []
        self.scan = None
        self.scan_times = []
        self.odom_times = []
        self.motion_started = False
        self.create_subscription(Odometry, args.odom, self.on_odom, qos_profile_sensor_data)
        self.create_subscription(LaserScan, args.scan, self.on_scan, qos_profile_sensor_data)
        self.create_subscription(FreeJointStateArray, args.truth, self.on_truth, qos_profile_sensor_data)
        self.cmd = self.create_publisher(TwistStamped, args.cmd, 1) if args.mode == 'motion' else None
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self)
        self.client = ActionClient(self, NavigateToPose, 'navigate_to_pose')

    def on_scan(self, msg):
        self.scan = msg
        self.scan_times.append(msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9)

    def on_odom(self, msg):
        self.odom = msg
        self.odom_times.append(msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9)

    def on_truth(self, msg):
        for state in msg.free_joints:
            if state.name == 'base_footprint':
                self.truth = state
                self.truth_time = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
                self.truth_wall_time = time.monotonic()
                self.truth_updates += 1
                p = state.pose.pose.position
                if not self.trajectory or self.truth_time-self.trajectory[-1][0] >= 0.2:
                    self.trajectory.append([self.truth_time, p.x, p.y])

    def spin_for(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)

    def wait_future(self, future, seconds):
        deadline = time.monotonic() + seconds
        while not future.done() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
        if not future.done():
            raise TimeoutError('ROS future timed out')
        return future.result()

    def velocity(self, speed, age=0.0):
        msg = TwistStamped()
        msg.header.stamp = (self.get_clock().now()-rclpy.duration.Duration(seconds=age)).to_msg()
        msg.header.frame_id = 'base_footprint'
        msg.twist.linear.x = speed
        self.cmd.publish(msg)

    @staticmethod
    def position(pose):
        return [pose.position.x, pose.position.y, pose.position.z]

    @staticmethod
    def rate(times):
        return (len(times)-1) / (times[-1]-times[0]) if len(times)>1 and times[-1]>times[0] else 0.0

    def snapshot(self):
        now = self.get_clock().now().nanoseconds * 1e-9
        if (self.truth_time is None or abs(now-self.truth_time) > 0.5
                or self.truth_wall_time is None or time.monotonic()-self.truth_wall_time > 0.5):
            raise RuntimeError('Stale MuJoCo ground truth')
        p = self.truth.pose.pose
        t = self.truth.twist.twist
        values = [p.position.x, p.position.y, p.position.z, p.orientation.x,
                  p.orientation.y, p.orientation.z, p.orientation.w,
                  t.linear.x, t.linear.y, t.linear.z, t.angular.x, t.angular.y, t.angular.z]
        if not all(math.isfinite(value) for value in values):
            raise RuntimeError('Nonfinite MuJoCo pose or twist')
        return self.position(p)

    def planar_speed(self):
        t = self.truth.twist.twist
        return math.hypot(t.linear.x, t.linear.y), abs(t.angular.z)

    def require_updates(self, previous_updates, previous_stamp):
        if self.truth_updates-previous_updates < 3 or self.truth_time <= previous_stamp:
            raise RuntimeError('Ground truth or simulation clock did not advance during the phase')

    def wait_transform(self, target, source):
        deadline = time.monotonic()+20
        while time.monotonic() < deadline:
            self.spin_for(0.1)
            if self.buffer.can_transform(target, source, rclpy.time.Time()):
                return self.buffer.lookup_transform(target, source, rclpy.time.Time())
        raise RuntimeError(f'Transform unavailable: {target} <- {source}')

    def wait_active(self, name):
        client = self.create_client(GetState, f'/{name}/get_state')
        deadline = time.monotonic()+40
        try:
            while time.monotonic() < deadline:
                if client.wait_for_service(timeout_sec=0.5):
                    response = self.wait_future(client.call_async(GetState.Request()), 3)
                    if response.current_state.id == 3:
                        return
                self.spin_for(0.2)
            raise RuntimeError(f'Lifecycle node not active: {name}')
        finally:
            self.destroy_client(client)

    def run(self):
        self.spin_for(8)
        if self.scan is None or self.odom is None or self.truth is None:
            raise RuntimeError('Missing scan, odom or MuJoCo ground truth')
        now = self.get_clock().now().nanoseconds * 1e-9
        if now-self.scan_times[-1] > 0.5 or now-self.odom_times[-1] > 0.5:
            raise RuntimeError('Stale sensors')
        report = {'mode': self.args.mode, 'domain': 93,
                  'scan_points': len(self.scan.ranges), 'scan_hz': self.rate(self.scan_times),
                  'odom_hz': self.rate(self.odom_times), 'scan_frame': self.scan.header.frame_id,
                  'valid_scan_points': sum(math.isfinite(r) and self.scan.range_min <= r <= self.scan.range_max for r in self.scan.ranges)}
        if report['valid_scan_points'] == 0:
            raise RuntimeError('LaserScan contains no obstacle returns')
        self.wait_transform('odom', self.scan.header.frame_id)
        start = self.snapshot()
        initial_updates, initial_stamp = self.truth_updates, self.truth_time
        if self.args.mode == 'motion':
            if any(p.node_name != self.get_name() for p in self.get_publishers_info_by_topic(self.args.cmd)):
                raise RuntimeError('Motion probe requires exclusive command ownership; launch nav:=false')
            self.motion_started = True
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                self.velocity(0.1)
                self.spin_for(0.05)
            # The command source disappears here; the controller's 500 ms TTL must brake.
            last_command = time.monotonic()
            timeout_updates, timeout_stamp = self.truth_updates, self.truth_time
            stop_elapsed = None
            while time.monotonic()-last_command < 2:
                self.spin_for(0.05)
                self.snapshot()
                linear, angular = self.planar_speed()
                if linear < 0.005 and angular < 0.02 and stop_elapsed is None:
                    stop_elapsed = time.monotonic()-last_command
            stopped = self.snapshot()
            self.require_updates(timeout_updates, timeout_stamp)
            self.spin_for(1)
            final = self.snapshot()
            linear, angular = self.planar_speed()
            report.update(start_truth=start, final_truth=final,
                          displacement=math.dist(start[:2], final[:2]),
                          post_timeout_drift=math.dist(stopped[:2], final[:2]),
                          stopped_after_seconds=stop_elapsed,
                          final_planar_speed=linear, final_angular_speed=angular)
            if (report['displacement'] < 0.15 or report['post_timeout_drift'] > 0.015
                    or stop_elapsed is None or stop_elapsed > 1.0 or linear > 0.005 or angular > 0.02):
                raise RuntimeError(f'Motion/timeout acceptance failed: {report}')
            # A stamped command delayed ten seconds must not restart a stopped robot.
            stale_updates, stale_stamp = self.truth_updates, self.truth_time
            for _ in range(10):
                self.velocity(0.1, age=10.0)
                self.spin_for(0.05)
            self.spin_for(1)
            self.require_updates(stale_updates, stale_stamp)
            report['stale_command_drift'] = math.dist(final[:2], self.snapshot()[:2])
            if report['stale_command_drift'] > 0.015:
                raise RuntimeError('Controller accepted an expired stamped command')
        elif self.args.mode == 'nav':
            for name in ['amcl', 'controller_server', 'bt_navigator', 'collision_monitor']:
                self.wait_active(name)
            if not self.client.wait_for_server(timeout_sec=30):
                raise RuntimeError('NavigateToPose server unavailable')
            self.wait_transform('map', 'base_footprint')
            goal = NavigateToPose.Goal()
            goal.pose.header.frame_id = 'map'
            goal.pose.header.stamp = self.get_clock().now().to_msg()
            goal.pose.pose.position.x = self.args.x
            goal.pose.pose.position.y = self.args.y
            goal.pose.pose.orientation.w = 1.0
            started = time.monotonic()
            handle = self.wait_future(self.client.send_goal_async(goal), 15)
            if not handle.accepted:
                raise RuntimeError('Navigation goal rejected')
            future = handle.get_result_async()
            try:
                result = self.wait_future(future, self.args.timeout)
            except TimeoutError:
                self.wait_future(handle.cancel_goal_async(), 5)
                raise
            self.spin_for(1)
            final = self.snapshot()
            self.require_updates(initial_updates, initial_stamp)
            error = math.hypot(final[0]-self.args.x, final[1]-self.args.y)
            q = self.truth.pose.pose.orientation
            yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
            yaw_error = abs(math.atan2(math.sin(yaw), math.cos(yaw)))
            linear_speed, angular_speed = self.planar_speed()
            report.update(goal=[self.args.x, self.args.y], action_status=result.status,
                          nav_error_code=result.result.error_code, elapsed_seconds=time.monotonic()-started,
                          start_truth=start, final_truth=final, physical_goal_error=error,
                          physical_yaw_error=yaw_error, final_planar_speed=linear_speed,
                          final_angular_speed=angular_speed,
                          final_odom=self.position(self.odom.pose.pose))
            if (result.status != 4 or result.result.error_code != 0 or error > self.args.tolerance
                    or yaw_error > self.args.yaw_tolerance or linear_speed > 0.005 or angular_speed > 0.02):
                raise RuntimeError(f'Navigation acceptance failed: {report}')
            report['trajectory'] = self.trajectory
        report['passed'] = True
        return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['sensors', 'motion', 'nav'])
    parser.add_argument('--scan', default='/scan')
    parser.add_argument('--odom', default='/odom')
    parser.add_argument('--cmd', default='/cmd_vel')
    parser.add_argument('--truth', default='/ground_truth/free_joint_states')
    parser.add_argument('--x', type=float, default=1.5)
    parser.add_argument('--y', type=float, default=-0.5)
    parser.add_argument('--timeout', type=float, default=100)
    parser.add_argument('--tolerance', type=float, default=0.25)
    parser.add_argument('--yaw-tolerance', type=float, default=0.30)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if os.environ.get('ROS_DOMAIN_ID') != '93' or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST':
        raise SystemExit('Requires simulation domain 93 and LOCALHOST discovery')
    rclpy.init()
    probe = Probe(args)
    report = None
    try:
        report = probe.run()
    except Exception as exc:
        report = {'passed': False, 'mode': args.mode, 'error': str(exc)}
        raise
    finally:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps(report, ensure_ascii=False))
        # Simulation-only cleanup after bounded motion probes; Nav2 owns commands during navigation.
        if args.mode == 'motion' and probe.motion_started:
            for _ in range(10):
                probe.velocity(0.0)
                probe.spin_for(0.05)
        probe.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
