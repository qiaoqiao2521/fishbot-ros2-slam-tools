#!/usr/bin/env python3
"""One continuous Nav2 goal or map route, with bounded time and cancellation.

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


def requested_map_endpoint(x, y, yaw, target):
    """Bound a map target against the fresh current pose, before goal submission."""
    if (len(target) != 3 or not all(math.isfinite(v) for v in (x, y, yaw, *target))
            or not 0 < math.hypot(target[0]-x, target[1]-y) <= 3):
        raise ValueError('finite map pose and target distance in (0, 3] metres required')
    return tuple(target)


def validate_map_route(route):
    """Require JSON [[map_x, map_y, yaw], ...], without loading ROS."""
    if not isinstance(route, list) or not 2 <= len(route) <= 20:
        raise ValueError('route requires 2..20 map poses')
    for pose in route:
        if (not isinstance(pose, (list, tuple)) or len(pose) != 3
                or any(isinstance(v, bool) or not isinstance(v, (int, float))
                       or not math.isfinite(v) for v in pose)):
            raise ValueError('route poses require finite numeric [x, y, yaw]')
    length = 0.
    for start, pose in zip(route, route[1:]):
        requested_map_endpoint(*start, pose)
        length += math.hypot(pose[0]-start[0], pose[1]-start[1])
    if length > 10:
        raise ValueError('requested route length must not exceed 10 metres')
    return [tuple(pose) for pose in route]


def requested_map_route(x, y, yaw, route):
    """Bound every requested segment, including the fresh pose to point one."""
    route = validate_map_route(route)
    start, length = (x, y, yaw), 0.
    for pose in route:
        requested_map_endpoint(*start, pose)
        length += math.hypot(pose[0]-start[0], pose[1]-start[1])
        start = pose
    if length > 10:
        raise ValueError('requested route length must not exceed 10 metres')
    if math.hypot(route[-1][0]-x, route[-1][1]-y) <= .1:
        raise ValueError('closed-loop route ends within 0.1 m of the fresh start; '
                         'Nav2 goal checker may finish before traversing the route')
    return route, length


class RouteCoverage:
    """Accept route completion only after fresh ordered intermediate feedback."""

    def __init__(self, route, evidence):
        self.intermediates = route[:-1]
        self.evidence = evidence
        evidence.update(route_waypoint_visits=[], route_feedback_count=0,
                        route_feedback_remaining=None,
                        route_intermediate_coverage=False)

    def observe(self, feedback, ros_now):
        evidence = self.evidence
        evidence['route_feedback_count'] += 1
        evidence['route_feedback_remaining'] = int(feedback.number_of_poses_remaining)
        pose = feedback.current_pose
        x, y = pose.pose.position.x, pose.pose.position.y
        age = ros_now - pose.header.stamp.sec - pose.header.stamp.nanosec * 1e-9
        if (pose.header.frame_id != 'map' or not all(math.isfinite(v) for v in (x, y, age))
                or not -.05 <= age <= .5):
            evidence['route_invalid_feedback_count'] = evidence.get('route_invalid_feedback_count', 0) + 1
            return
        visits = evidence['route_waypoint_visits']
        while len(visits) < len(self.intermediates):
            index = len(visits)
            target = self.intermediates[index]
            distance = math.hypot(x-target[0], y-target[1])
            if distance > .15:
                break
            visits.append({'index': index, 'position': [x, y],
                           'distance': distance, 'source_age': age})
        evidence['route_intermediate_coverage'] = len(visits) == len(self.intermediates)

    def require_complete(self):
        if not self.evidence['route_intermediate_coverage']:
            raise RuntimeError('Nav2 reported success without observed ordered intermediate '
                               f'waypoints ({len(self.evidence["route_waypoint_visits"])}/'
                               f'{len(self.intermediates)})')


def make_navigation_goal(action_type, pose_type, poses, stamp, through_poses):
    """Build the installed Jazzy action shape; one goal owns the entire route."""
    goal = action_type.Goal()
    messages = []
    for x, y, yaw in poses:
        pose = pose_type()
        pose.header.frame_id, pose.header.stamp = 'map', stamp
        pose.pose.position.x, pose.pose.position.y = float(x), float(y)
        pose.pose.orientation.z = math.sin(yaw/2)
        pose.pose.orientation.w = math.cos(yaw/2)
        messages.append(pose)
    if through_poses:
        goal.poses = messages
        tree = 'fishbot_passage_through_tree.xml'
    else:
        goal.pose = messages[0]
        tree = 'fishbot_passage_tree.xml'
    goal.behavior_tree = str(Path(__file__).parent / 'config' / tree)
    return goal


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


def check_running_guard(diagnostics, steady_now, ros_now):
    """Abort active goals on a blocked guard or untrustworthy diagnostics."""
    if not diagnostics:
        raise RuntimeError('guard diagnostics missing during goal')
    received, message = diagnostics[0]
    receive_age = steady_now - received
    if not math.isfinite(receive_age) or not 0 <= receive_age <= 1:
        raise RuntimeError('guard diagnostics receive timeout during goal')
    source_age = ros_now - (message.header.stamp.sec + message.header.stamp.nanosec * 1e-9)
    if not math.isfinite(source_age) or not -.05 <= source_age <= 1:
        raise RuntimeError('guard diagnostics source timestamp outside freshness limit during goal')
    status = next((s for s in message.status if s.name == 'fishbot_command_guard'), None)
    if status is None:
        raise RuntimeError('guard status missing from diagnostics during goal')
    level = diagnostic_level(status.level)
    if status.message.startswith('latched:') or level >= 2:
        raise RuntimeError(f'guard blocked goal: {status.message} (level={level})')


def wait_action_future(future, until, spin_once, check_health, steady_now, interrupted):
    """Monitor the independent final guard while awaiting action acknowledgement/result."""
    check_health()
    while not future.done() and steady_now() < until and not interrupted():
        spin_once()
        check_health()
    if not future.done():
        raise TimeoutError('goal operation interrupted or deadline reached')
    return future.result()


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
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument('--distance', type=float)
    destination.add_argument('--target', nargs=3, type=float, metavar=('X', 'Y', 'YAW'),
                             help='map target in metres and radians; at most 3 metres from the fresh pose')
    destination.add_argument('--route-file', type=Path,
                             help='JSON [[map_x, map_y, yaw], ...], 2..20 poses; segments <=3 m, requested total <=10 m')
    parser.add_argument('--domain', type=int, default=96)
    parser.add_argument('--real', action='store_true')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--use-sim-time', action='store_true')
    parser.add_argument('--timeout', type=float, default=90)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    route = None
    if args.route_file is not None:
        try:
            route = validate_map_route(json.loads(args.route_file.read_text()))
        except (OSError, ValueError, TypeError) as exc:
            parser.error('invalid route file: ' + str(exc))
    elif args.target is None:
        args.distance = 1.0 if args.distance is None else args.distance
        requested_endpoint(0, 0, 0, args.distance)
    elif not all(math.isfinite(v) for v in args.target):
        parser.error('map target coordinates and yaw must be finite')
    if not 0 <= args.domain <= 232 or (args.domain == 0 and not args.real):
        parser.error('domain 0 requires --real; domain must be 0..232')
    if args.real and (args.domain != 0 or args.use_sim_time):
        parser.error('--real requires domain 0 and system time')
    if not math.isfinite(args.timeout) or not 5 <= args.timeout <= 180:
        parser.error('timeout must be 5..180 seconds')
    if not args.execute:
        print(json.dumps({'execute': False, 'distance': args.distance,
                          'target_requested': args.target,
                          'route_requested': route,
                          'domain': args.domain,
                          'action': 'navigate_through_poses' if route else 'navigate_to_pose'}))
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
    from nav2_msgs.action import NavigateToPose, NavigateThroughPoses
    from geometry_msgs.msg import PoseStamped
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
    action_type = NavigateThroughPoses if route else NavigateToPose
    action_name = 'navigate_through_poses' if route else 'navigate_to_pose'
    action = ActionClient(node, action_type, '/' + action_name)
    stop_client = node.create_client(Trigger, '/fishbot_command_guard/stop')
    odom = []
    guard_diagnostic = []
    node.create_subscription(Odometry, '/odom', lambda m: odom.__setitem__(slice(None), [(time.monotonic(), m)]), qos_profile_sensor_data)
    node.create_subscription(DiagnosticArray, '/fishbot_command_guard/diagnostics',
                             lambda m: guard_diagnostic.__setitem__(slice(None), [(time.monotonic(), m)]), 1)
    result = {'completed': False, 'stationary_feedback': False,
              'distance_requested': args.distance, 'target_requested': args.target,
              'route_requested': route, 'action': action_name,
              'domain': args.domain}
    pending = PendingGoal(result)
    goal_requested = False
    began = time.monotonic()
    deadline = began + args.timeout

    def wait(future, until):
        def check_health():
            check_running_guard(guard_diagnostic, time.monotonic(),
                                node.get_clock().now().nanoseconds * 1e-9)
        return wait_action_future(future, until,
                                  lambda: rclpy.spin_once(node, timeout_sec=.05),
                                  check_health, time.monotonic, lambda: bool(stopped))

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
        result['start'] = [t.x, t.y, yaw]
        if route is not None:
            poses, length = requested_map_route(t.x, t.y, yaw, route)
            result.update(route=[list(pose) for pose in poses], route_length=length)
            x, y, target_yaw = poses[-1]
        else:
            x, y, target_yaw = (requested_map_endpoint(t.x, t.y, yaw, args.target)
                                if args.target is not None else requested_endpoint(t.x, t.y, yaw, args.distance))
            poses = [(x, y, target_yaw)]
        result['target'] = [x, y, target_yaw]
        result['relative_target_distance'] = math.hypot(x-t.x, y-t.y)
        goal = make_navigation_goal(action_type, PoseStamped, poses,
                                    node.get_clock().now().to_msg(), route is not None)
        coverage = RouteCoverage(poses, result) if route is not None else None
        def feedback_callback(message):
            if coverage is not None:
                coverage.observe(message.feedback, node.get_clock().now().nanoseconds * 1e-9)
        goal_requested = True
        send_future = (action.send_goal_async(goal, feedback_callback=feedback_callback)
                       if coverage is not None else action.send_goal_async(goal))
        handle = wait(pending.track(send_future), min(deadline, time.monotonic()+10))
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
        if coverage is not None:
            coverage.require_complete()
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
