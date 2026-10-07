#!/usr/bin/env python3
"""One continuous Nav2 goal; explicit execution, bounded time and cancellation.

Default inspection never joins a ROS domain or sends a goal. Domain zero also
requires --real. Navigation may choose a safe route to the requested endpoint.
"""
import argparse
import json
import math
import os
from pathlib import Path
import signal
import time


def requested_endpoint(x, y, yaw, distance):
    if not all(math.isfinite(v) for v in (x, y, yaw, distance)) or not 0 < distance <= 3:
        raise ValueError('finite pose and distance in (0, 3] metres required')
    return x + distance * math.cos(yaw), y + distance * math.sin(yaw), yaw


def heading_from_quaternion(values):
    if len(values) != 4 or not all(math.isfinite(v) for v in values):
        raise ValueError('invalid map orientation')
    norm = sum(v*v for v in values)
    if not .8 <= norm <= 1.2:
        raise ValueError('invalid map orientation norm')
    x, y, z, w = [v/math.sqrt(norm) for v in values]
    return math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z))


def guard_preflight(status, values, publishers, subscribers, expected_subscriber):
    allowed = status in ('healthy', 'priming: awaiting command', 'ready; awaiting new command')
    allowed = allowed or status.startswith('idle: command:')
    return (allowed and values.get('execute', '').lower() == 'true'
            and values.get('profile') == 'fishbot_passage'
            and publishers == ['fishbot_command_guard']
            and subscribers == [expected_subscriber])


def diagnostic_level(value):
    """ROS octet fields can be returned as one byte instead of an integer."""
    if isinstance(value, (bytes, bytearray)) and len(value) == 1:
        value = value[0]
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 3:
        raise ValueError('invalid DiagnosticStatus.level')
    return value


class PendingGoal:
    """Keep cancellation intent across a delayed action acknowledgement."""

    def __init__(self, evidence):
        self.evidence = evidence
        self.send_future = self.handle = self.cancel_future = self.result_future = None
        self.cancel_requested = False

    def track(self, future):
        self.send_future = future
        future.add_done_callback(self._accepted)
        return future

    def _accepted(self, future):
        try:
            self.handle = future.result()
            self.evidence['goal_accepted'] = bool(self.handle and self.handle.accepted)
            if self.cancel_requested:
                self.cancel()
                self.get_result()
        except Exception as exc:
            self.evidence.setdefault('cleanup_errors', []).append('goal acknowledgement: ' + str(exc))

    def get_result(self):
        if self.result_future is None and self.handle is not None and self.handle.accepted:
            self.result_future = self.handle.get_result_async()
        return self.result_future

    def cancel(self):
        self.cancel_requested = True
        if self.handle is not None and self.handle.accepted and self.cancel_future is None:
            self.cancel_future = self.handle.cancel_goal_async()
        return self.cancel_future

    def refresh(self):
        self.evidence['goal_ack_pending'] = bool(self.send_future is not None and not self.send_future.done())
        if self.cancel_future is not None and self.cancel_future.done():
            response = self.cancel_future.result()
            self.evidence['cancel_acknowledged'] = bool(response and response.goals_canceling)
        if self.cancel_requested and self.result_future is not None and self.result_future.done():
            response = self.result_future.result()
            self.evidence['cancel_terminal_status'] = response.status if response else None
            self.evidence['canceled'] = bool(response and response.status == 5)


def finalize_goal(result, goal_requested, request_stop, request_cancel, observe,
                  refresh, destroy_node, shutdown, record_result):
    """Finish all independent safety/cleanup steps even when an RPC raises."""
    def attempt(label, operation):
        try:
            operation()
            return True
        except Exception as exc:
            result.setdefault('cleanup_errors', []).append(label + ': ' + str(exc))
            return False

    def stop_and_cancel():
        attempt('guard stop', request_stop)
        attempt('goal cancellation', request_cancel)

    if goal_requested and not result['completed']:
        stop_and_cancel()
    if not attempt('stationary observation', observe):
        result['stationary_feedback'] = False
    if goal_requested and not result['stationary_feedback']:
        result.setdefault('error', 'final stationary feedback did not pass')
        # Includes Nav2 SUCCEEDED with moving, stale or missing final odometry.
        stop_and_cancel()
    attempt('final action evidence', refresh)
    attempt('destroy node', destroy_node)
    attempt('ROS shutdown', shutdown)
    # Record last, including failures during ROS cleanup.
    attempt('write evidence', record_result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--distance', type=float, default=1.0)
    parser.add_argument('--domain', type=int, default=96)
    parser.add_argument('--real', action='store_true')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--use-sim-time', action='store_true')
    parser.add_argument('--timeout', type=float, default=90)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    requested_endpoint(0, 0, 0, args.distance)
    if not 0 <= args.domain <= 232 or (args.domain == 0 and not args.real):
        parser.error('domain 0 requires --real; domain must be 0..232')
    if args.real and (args.domain != 0 or args.use_sim_time):
        parser.error('--real requires domain 0 and system time')
    if not math.isfinite(args.timeout) or not 5 <= args.timeout <= 180:
        parser.error('timeout must be 5..180 seconds')
    if not args.execute:
        print(json.dumps({'execute': False, 'distance': args.distance,
                          'domain': args.domain, 'action': 'navigate_to_pose'}))
        return 0
    if args.output is None or args.output.exists():
        parser.error('execution requires a new --output evidence file')
    os.environ['ROS_DOMAIN_ID'] = str(args.domain)
    if not args.real:
        os.environ['ROS_AUTOMATIC_DISCOVERY_RANGE'] = 'LOCALHOST'
        os.environ['ROS_LOCALHOST_ONLY'] = '1'
        os.environ.pop('ROS_STATIC_PEERS', None)
    import rclpy
    from rclpy.action import ActionClient
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.signals import SignalHandlerOptions
    from nav2_msgs.action import NavigateToPose
    from nav_msgs.msg import Odometry
    from diagnostic_msgs.msg import DiagnosticArray
    from std_srvs.srv import Trigger
    from rclpy.qos import qos_profile_sensor_data
    from tf2_ros import Buffer, TransformListener
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = Node('fishbot_passage_goal', parameter_overrides=[
        Parameter('use_sim_time', value=args.use_sim_time)])
    stopped = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda signum, frame: stopped.append(signum))
    buffer = Buffer()
    listener = TransformListener(buffer, node)
    action = ActionClient(node, NavigateToPose, '/navigate_to_pose')
    stop_client = node.create_client(Trigger, '/fishbot_command_guard/stop')
    odom = []
    guard_diagnostic = []
    node.create_subscription(Odometry, '/odom', lambda m: odom.__setitem__(slice(None), [(time.monotonic(), m)]), qos_profile_sensor_data)
    node.create_subscription(DiagnosticArray, '/fishbot_command_guard/diagnostics',
                             lambda m: guard_diagnostic.__setitem__(slice(None), [(time.monotonic(), m)]), 1)
    result = {'completed': False, 'stationary_feedback': False,
              'distance_requested': args.distance, 'domain': args.domain}
    pending = PendingGoal(result)
    goal_requested = False
    began = time.monotonic()
    deadline = began + args.timeout

    def wait(future, until):
        while not future.done() and time.monotonic() < until and not stopped:
            rclpy.spin_once(node, timeout_sec=.05)
        if not future.done():
            raise TimeoutError('goal operation interrupted or deadline reached')
        return future.result()

    try:
        def guard_ready():
            if not stop_client.service_is_ready() or not guard_diagnostic or time.monotonic()-guard_diagnostic[0][0] > 1:
                return False
            message = guard_diagnostic[0][1]
            age = node.get_clock().now().nanoseconds*1e-9-message.header.stamp.sec-message.header.stamp.nanosec*1e-9
            if not -.05 <= age <= 1:
                return False
            status = next((s for s in message.status if s.name == 'fishbot_command_guard'), None)
            if status is None or diagnostic_level(status.level) > 1:
                return False
            publishers = [p.node_name for p in node.get_publishers_info_by_topic('/cmd_vel')]
            subscribers = [p.node_name for p in node.get_subscriptions_info_by_topic('/cmd_vel')]
            expected = 'fishbot_motion_control' if args.real else 'diff_drive_controller'
            return guard_preflight(status.message, {v.key:v.value for v in status.values}, publishers, subscribers, expected)

        while time.monotonic() < min(deadline, began + 15) and not stopped:
            rclpy.spin_once(node, timeout_sec=.05)
            if guard_ready() and action.server_is_ready() and buffer.can_transform('map', 'base_footprint', rclpy.time.Time()):
                break
        if stopped or not action.server_is_ready() or not guard_ready():
            raise RuntimeError('new passage guard/navigation is not ready; no goal sent')
        tf = buffer.lookup_transform('map', 'base_footprint', rclpy.time.Time())
        now = node.get_clock().now().nanoseconds * 1e-9
        age = now - (tf.header.stamp.sec + tf.header.stamp.nanosec * 1e-9)
        if not -.05 <= age <= .5:
            raise RuntimeError('map pose timestamp is stale')
        t, q = tf.transform.translation, tf.transform.rotation
        yaw = heading_from_quaternion((q.x, q.y, q.z, q.w))
        x, y, yaw = requested_endpoint(t.x, t.y, yaw, args.distance)
        result['start'] = [t.x, t.y, yaw]
        result['target'] = [x, y, yaw]
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = node.get_clock().now().to_msg()
        goal.pose.pose.position.x, goal.pose.pose.position.y = x, y
        goal.pose.pose.orientation.z = math.sin(yaw/2)
        goal.pose.pose.orientation.w = math.cos(yaw/2)
        goal.behavior_tree = str(Path(__file__).parent / 'config/fishbot_passage_tree.xml')
        goal_requested = True
        handle = wait(pending.track(action.send_goal_async(goal)), min(deadline, time.monotonic()+10))
        # Some future adapters dispatch done callbacks on the next executor turn.
        if pending.handle is None:
            pending._accepted(pending.send_future)
        if not handle.accepted:
            raise RuntimeError('Nav2 rejected the goal')
        action_result = pending.get_result()
        response = wait(action_result, deadline)
        result.update(action_status=response.status, error_code=response.result.error_code)
        if response.status != 4 or response.result.error_code != 0:
            raise RuntimeError('Nav2 did not complete the requested goal')
        result['completed'] = True
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        def request_stop():
            # Late acknowledgement remains cancellable while the final gate is
            # latched. Set intent before spinning for the stop service reply.
            pending.cancel_requested = True
            result['guard_stop_acknowledged'] = False
            if stop_client.wait_for_service(timeout_sec=1.0):
                stop_future = stop_client.call_async(Trigger.Request())
                stop_deadline = time.monotonic()+2
                while not stop_future.done() and time.monotonic() < stop_deadline:
                    rclpy.spin_once(node, timeout_sec=.05)
                response = stop_future.result() if stop_future.done() else None
                result['guard_stop_acknowledged'] = bool(response and response.success)

        def request_cancel():
            cancel = pending.cancel()
            result['cancel_acknowledged'] = False
            end = time.monotonic()+3
            while cancel is not None and not cancel.done() and time.monotonic() < end:
                rclpy.spin_once(node, timeout_sec=.05)
            terminal = pending.get_result()
            end = time.monotonic()+3
            while terminal is not None and not terminal.done() and time.monotonic() < end:
                rclpy.spin_once(node, timeout_sec=.05)
            pending.refresh()

        def observe():
            since = None
            stop_end = time.monotonic()+5
            while time.monotonic() < stop_end:
                rclpy.spin_once(node, timeout_sec=.05)
                now = time.monotonic()
                good = False
                if odom:
                    received, msg = odom[0]
                    source_age = node.get_clock().now().nanoseconds*1e-9-msg.header.stamp.sec-msg.header.stamp.nanosec*1e-9
                    v, w = msg.twist.twist.linear.x, msg.twist.twist.angular.z
                    good = 0 <= now-received <= .25 and -.05 <= source_age <= .25 and abs(v)<.008 and abs(w)<.025
                    values = {'x':msg.pose.pose.position.x,'y':msg.pose.pose.position.y,'v':v,'w':w,'source_age':source_age}
                    result['last_odom'] = {k:(v if math.isfinite(v) else None) for k,v in values.items()}
                since = (since if since is not None else now) if good else None
                result['stationary_feedback'] = bool(since is not None and now-since >= 1)

        def record_result():
            result['elapsed_s'] = time.monotonic()-began
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('x') as f:
                os.chmod(args.output, 0o600)
                json.dump(result, f, indent=2, allow_nan=False)

        finalize_goal(result, goal_requested, request_stop, request_cancel, observe,
                      pending.refresh, node.destroy_node, rclpy.shutdown, record_result)
        print(json.dumps(result, allow_nan=False))
    return 0 if result['completed'] and result['stationary_feedback'] and not result.get('cleanup_errors') else 1


if __name__ == '__main__':
    raise SystemExit(main())
