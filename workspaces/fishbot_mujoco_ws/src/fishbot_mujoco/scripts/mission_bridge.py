#!/usr/bin/python3
"""Loopback-only HTTP mission API for the isolated domain-93 MuJoCo fixture.

HTTP workers never spin or mutate the ROS node. Their short-lived requests enter
one executor-owned queue; navigation remains a FollowWaypoints action, with no
velocity publisher and no ground-truth TF.
"""
import argparse
import copy
import json
import math
import os
import queue
import signal
import threading
import time
import uuid
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from lifecycle_msgs.srv import GetState
from mujoco_ros2_control_msgs.msg import FreeJointStateArray
from nav2_msgs.action import FollowWaypoints
from nav_msgs.msg import OccupancyGrid, Odometry, Path
from rclpy.action import ActionClient
from rclpy.clock import Clock, ClockType
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import (DurabilityPolicy, QoSProfile, ReliabilityPolicy,
                      qos_profile_sensor_data)
from rclpy.signals import SignalHandlerOptions
from rosgraph_msgs.msg import Clock as ClockMessage
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformListener


HOME = {'x': 0.0, 'y': 0.0, 'yaw': 0.0}
ROBOT_RADIUS = 0.13
MAX_WAYPOINTS = 12  # User-selected points; an optional home point is additional.
ACTIVE_STATUSES = {'running', 'canceling'}


class APIError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def finite_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise APIError(f'{label} must be a finite number')
    return float(value)


def quaternion_yaw(q):
    return math.atan2(2.0 * (q.w*q.z + q.x*q.y), 1.0 - 2.0 * (q.y*q.y + q.z*q.z))


def stamp_seconds(stamp):
    return stamp.sec + stamp.nanosec * 1e-9


def require_free_point(point, grid, radius=ROBOT_RADIUS):
    """Reject unknown/occupied cells intersecting the robot's circular footprint."""
    if grid is None:
        raise APIError('Map is not available', 503)
    ox, oy, yaw = grid['origin']
    dx, dy = point['x']-ox, point['y']-oy
    x = math.cos(yaw)*dx + math.sin(yaw)*dy
    y = -math.sin(yaw)*dx + math.cos(yaw)*dy
    res, width, height = grid['resolution'], grid['width'], grid['height']
    if x < radius or y < radius or x > width*res-radius or y > height*res-radius:
        raise APIError('Waypoint footprint is outside the map')
    for row in range(max(0, math.floor((y-radius)/res)), min(height-1, math.floor((y+radius)/res))+1):
        for col in range(max(0, math.floor((x-radius)/res)), min(width-1, math.floor((x+radius)/res))+1):
            closest_x = max(col*res, min(x, (col+1)*res))
            closest_y = max(row*res, min(y, (row+1)*res))
            if (closest_x-x)**2 + (closest_y-y)**2 <= radius**2:
                occupancy = grid['data'][row*width+col]
                if occupancy < 0 or occupancy >= 50:
                    raise APIError('Waypoint footprint intersects an occupied or unknown cell')


def validate_mission(body, grid, now=None):
    if not isinstance(body, dict) or set(body)-{'waypoints', 'return_home', 'issued_at'}:
        raise APIError('Expected waypoints, return_home and issued_at')
    issued = finite_number(body.get('issued_at'), 'issued_at')
    age = (time.time() if now is None else now)-issued
    if age > 3.0 or age < -1.0:
        raise APIError('Mission request expired or has a future timestamp', 408)
    return_home = body.get('return_home', False)
    if not isinstance(return_home, bool):
        raise APIError('return_home must be a boolean')
    raw = body.get('waypoints')
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_WAYPOINTS:
        raise APIError(f'Provide 1 to {MAX_WAYPOINTS} waypoints')
    points = []
    for index, point in enumerate(raw):
        if not isinstance(point, dict) or set(point)-{'x', 'y', 'yaw'}:
            raise APIError(f'Waypoint {index+1} must contain x, y and optional yaw')
        parsed = {name: finite_number(point.get(name, 0.0) if name == 'yaw' else point.get(name),
                                      f'waypoint {index+1} {name}') for name in ('x', 'y', 'yaw')}
        parsed['yaw'] = math.atan2(math.sin(parsed['yaw']), math.cos(parsed['yaw']))
        require_free_point(parsed, grid)
        points.append(parsed)
    if return_home and any(abs(points[-1][axis]-HOME[axis]) > 1e-6 for axis in HOME):
        require_free_point(HOME, grid)
        points.append(dict(HOME))
    return points, return_home


class MissionRecord:
    """Only terminal action results can produce a successful/canceled mission."""
    def __init__(self):
        self.value = {'id': None, 'status': 'idle', 'current_index': 0, 'waypoints': [],
                      'return_home': False, 'message': '等待巡逻任务', 'missed_waypoints': []}

    def begin(self, points, return_home):
        if self.value['status'] in ACTIVE_STATUSES:
            raise APIError('A mission is already running or canceling', 409)
        self.value = {'id': uuid.uuid4().hex, 'status': 'running', 'current_index': 0,
                      'waypoints': points, 'return_home': return_home,
                      'message': '正在提交 Nav2 巡逻任务', 'missed_waypoints': []}
        return self.value['id']

    def request_cancel(self):
        if self.value['status'] not in ACTIVE_STATUSES:
            raise APIError('There is no active mission to cancel', 409)
        self.value['status'] = 'canceling'
        self.value['message'] = '正在请求取消，等待 Nav2 实际结果'

    def finish(self, status, error_code, missed, error_msg=''):
        self.value['missed_waypoints'] = missed
        if status == GoalStatus.STATUS_CANCELED:
            self.value.update(status='canceled', message='Nav2 已取消巡逻')
        elif status == GoalStatus.STATUS_SUCCEEDED and error_code == 0 and not missed:
            self.value.update(status='succeeded', current_index=len(self.value['waypoints'])-1,
                              message='全部巡逻点已由 Nav2 确认完成')
        else:
            self.value.update(status='failed', message=error_msg or
                              f'巡逻失败：action={status}, error={error_code}, missed={len(missed)}')


@dataclass
class Operation:
    kind: str
    body: dict
    deadline: float
    future: Future


class MissionBridge(Node):
    def __init__(self):
        super().__init__('fishbot_mission_bridge', parameter_overrides=[
            rclpy.parameter.Parameter('use_sim_time', value=True)])
        self.lock = threading.RLock()
        self.operations = queue.Queue(maxsize=32)
        self.mission = MissionRecord()
        self.grid = None
        self.samples = {}
        self.clock_last = None
        self.clock_advance_wall = None
        self.pose = None
        self.truth = None
        self.path = []
        self.trajectory = []
        self.last_trace = 0.0
        self.obstacle = {'state': 'unknown', 'x': None, 'y': None, 'size': 0.36}
        self.obstacle_truth = None
        self.obstacle_truth_wall = None
        self.obstacle_state_wall = None
        self.goal_handle = None
        self.goal_send_future = None
        self.goal_sent_wall = None
        self.cancel_sent = False
        self.cancel_requested = False
        self.last_lifecycle_poll = 0.0
        self.lifecycle = {name: {'active': False, 'wall': 0.0, 'future': None}
                          for name in ('amcl', 'controller_server', 'bt_navigator',
                                       'collision_monitor', 'waypoint_follower')}
        self.lifecycle_clients = {name: self.create_client(GetState, f'/{name}/get_state')
                                  for name in self.lifecycle}
        self.obstacle_clients = {
            'block': self.create_client(Trigger, '/sim/obstacle/block_path'),
            'clear': self.create_client(Trigger, '/sim/obstacle/clear')}
        self.pending_services = []
        self.client = ActionClient(self, FollowWaypoints, '/follow_waypoints')
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self)
        self.create_subscription(ClockMessage, '/clock', self.on_clock, qos_profile_sensor_data)
        self.create_subscription(LaserScan, '/scan', self.on_scan, qos_profile_sensor_data)
        self.create_subscription(Odometry, '/odom', self.on_odom, qos_profile_sensor_data)
        self.create_subscription(FreeJointStateArray, '/ground_truth/free_joint_states',
                                 self.on_truth, qos_profile_sensor_data)
        self.create_subscription(Path, '/plan', self.on_path, 10)
        self.create_subscription(String, '/sim/obstacle/state', self.on_obstacle, 10)
        self.create_subscription(OccupancyGrid, '/map', self.on_map,
                                 QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                            durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.ready = False
        self.reason = '等待仿真时钟、传感器与 Nav2 启动'
        # A steady timer keeps HTTP/readiness alive even when simulation time pauses.
        self.create_timer(0.1, self.tick, clock=Clock(clock_type=ClockType.STEADY_TIME))

    def sample(self, name, stamp):
        self.samples[name] = (stamp_seconds(stamp), time.monotonic())

    def on_clock(self, msg):
        with self.lock:
            current = stamp_seconds(msg.clock)
            if self.clock_last is not None and current > self.clock_last:
                self.clock_advance_wall = time.monotonic()
            elif self.clock_last is not None and current < self.clock_last:
                self.clock_advance_wall = None
            self.clock_last = current
            self.sample('clock', msg.clock)

    def on_scan(self, msg):
        if not any(math.isfinite(v) and msg.range_min <= v <= msg.range_max for v in msg.ranges):
            return
        with self.lock:
            self.sample('scan', msg.header.stamp)

    def on_odom(self, msg):
        p, q, t = msg.pose.pose.position, msg.pose.pose.orientation, msg.twist.twist
        if not all(math.isfinite(v) for v in (p.x, p.y, q.x, q.y, q.z, q.w,
                                             t.linear.x, t.linear.y, t.angular.z)):
            return
        with self.lock:
            self.sample('odom', msg.header.stamp)

    def on_truth(self, msg):
        with self.lock:
            for state in msg.free_joints:
                p, q, t = state.pose.pose.position, state.pose.pose.orientation, state.twist.twist
                if not all(math.isfinite(v) for v in (p.x, p.y, q.x, q.y, q.z, q.w,
                                                     t.linear.x, t.linear.y, t.angular.z)):
                    continue
                if state.name == 'base_footprint':
                    self.truth = {'x': p.x, 'y': p.y, 'yaw': quaternion_yaw(q),
                                  'linear_speed': math.hypot(t.linear.x, t.linear.y),
                                  'angular_speed': abs(t.angular.z)}
                    self.sample('truth', msg.header.stamp)
                    wall = time.monotonic()
                    if wall-self.last_trace >= 0.2:
                        self.trajectory.append({'x': p.x, 'y': p.y})
                        self.trajectory = self.trajectory[-3000:]
                        self.last_trace = wall
                elif state.name == 'moving_obstacle':
                    self.obstacle_truth = {'x': p.x, 'y': p.y}
                    self.obstacle_truth_wall = time.monotonic()
                    self.sample('obstacle_truth', msg.header.stamp)

    def on_path(self, msg):
        if msg.header.frame_id != 'map':
            return
        with self.lock:
            self.path = [{'x': p.pose.position.x, 'y': p.pose.position.y}
                         for p in msg.poses[:2000]
                         if math.isfinite(p.pose.position.x) and math.isfinite(p.pose.position.y)]

    def on_obstacle(self, msg):
        try:
            body = json.loads(msg.data)
            if (not isinstance(body, dict) or body.get('state') not in
                    {'parked', 'moving', 'blocking', 'returning', 'error'}):
                return
            size = finite_number(body.get('size', 0.36), 'obstacle size')
            if not 0 < size <= 1:
                return
            with self.lock:
                self.obstacle.update(state=body['state'], size=size)
                self.obstacle_state_wall = time.monotonic()
        except (ValueError, TypeError, APIError):
            return

    def on_map(self, msg):
        info = msg.info
        p, q = info.origin.position, info.origin.orientation
        if (msg.header.frame_id != 'map' or not 0 < info.resolution <= 1
                or not 0 < info.width*info.height <= 4_000_000
                or len(msg.data) != info.width*info.height
                or not all(math.isfinite(v) for v in (info.resolution, p.x, p.y, q.x, q.y, q.z, q.w))):
            return
        with self.lock:
            self.grid = {'width': info.width, 'height': info.height,
                         'resolution': info.resolution,
                         'origin': [p.x, p.y, quaternion_yaw(q)], 'data': list(msg.data)}

    def fresh(self, name, ros_now, wall_now, age=0.8):
        sample = self.samples.get(name)
        return (sample is not None and 0 <= wall_now-sample[1] <= age
                and -0.15 <= ros_now-sample[0] <= age)

    def clock_fresh(self, ros_now, wall):
        return (self.fresh('clock', ros_now, wall) and self.clock_advance_wall is not None
                and wall-self.clock_advance_wall <= 0.8)

    def poll_lifecycle(self, wall):
        if wall-self.last_lifecycle_poll < 0.75:
            return
        self.last_lifecycle_poll = wall
        for name, state in self.lifecycle.items():
            client = self.lifecycle_clients[name]
            pending = state['future']
            if pending is not None:
                if pending.done():
                    self.lifecycle_result(name, pending)
                elif wall-state['sent'] <= 3:
                    continue
                else:
                    # A lost service response must not occupy this poll slot forever.
                    # Clear ownership before canceling; late callbacks are ignored.
                    state.update(active=False, wall=0.0, future=None)
                    client.remove_pending_request(pending)
                    pending.cancel()
            if not client.service_is_ready():
                state['active'] = False
                continue
            state['sent'] = wall
            state['future'] = client.call_async(GetState.Request())
            state['future'].add_done_callback(lambda f, n=name: self.lifecycle_result(n, f))

    def lifecycle_result(self, name, future):
        with self.lock:
            if self.lifecycle[name]['future'] is not future:
                return
            try:
                self.lifecycle[name]['active'] = future.result().current_state.id == 3
                self.lifecycle[name]['wall'] = time.monotonic()
            except Exception:
                self.lifecycle[name]['active'] = False
                self.lifecycle[name]['wall'] = 0.0
            self.lifecycle[name]['future'] = None

    def evaluate_ready(self, wall):
        ros_now = self.get_clock().now().nanoseconds*1e-9
        if not self.clock_fresh(ros_now, wall):
            return False, '仿真时钟未就绪或已暂停'
        for name in ('scan', 'odom', 'truth'):
            if not self.fresh(name, ros_now, wall):
                return False, f'{name} 缺失或过期'
        if self.grid is None:
            return False, '等待地图'
        for name, state in self.lifecycle.items():
            if not state['active'] or wall-state['wall'] > 3:
                return False, f'{name} 未处于 ACTIVE 状态'
        if not self.client.server_is_ready():
            return False, 'FollowWaypoints 服务未就绪'
        try:
            transform = self.buffer.lookup_transform('map', 'base_footprint', rclpy.time.Time())
            # AMCL transform_tolerance may intentionally stamp map->odom in the future.
            if not -1.2 <= ros_now-stamp_seconds(transform.header.stamp) <= 0.8:
                return False, '定位 TF 已过期'
            p, q = transform.transform.translation, transform.transform.rotation
            if not all(math.isfinite(v) for v in (p.x, p.y, q.x, q.y, q.z, q.w)):
                return False, '定位 TF 包含无效值'
            self.pose = {'x': p.x, 'y': p.y, 'yaw': quaternion_yaw(q)}
        except Exception:
            return False, '等待 map → base_footprint 定位'
        return True, '仿真传感器、定位和 Nav2 已就绪'

    def state(self):
        with self.lock:
            wall = time.monotonic()
            ros_now = self.clock_last or 0.0
            clock_fresh = self.clock_fresh(ros_now, wall)
            obstacle = dict(self.obstacle)
            if self.obstacle_state_wall is None or wall-self.obstacle_state_wall > 1:
                obstacle['state'] = 'unknown'
            if clock_fresh and self.fresh('obstacle_truth', ros_now, wall):
                obstacle.update(self.obstacle_truth)
            else:
                obstacle.update(x=None, y=None)
            return copy.deepcopy({'mode': 'mujoco', 'domain': 93,
                'ready': self.ready, 'reason': self.reason,
                'pose': self.pose if self.ready else None,
                'truth': self.truth if clock_fresh and self.fresh('truth', ros_now, wall) else None,
                'path': self.path, 'trajectory': self.trajectory,
                'mission': self.mission.value, 'obstacle': obstacle, 'home': HOME})

    def enqueue(self, kind, body):
        op = Operation(kind, body, time.monotonic()+2.0, Future())
        try:
            self.operations.put_nowait(op)
        except queue.Full:
            raise APIError('Bridge request queue is full', 503)
        return op.future

    def tick(self):
        with self.lock:
            wall = time.monotonic()
            self.poll_lifecycle(wall)
            self.ready, self.reason = self.evaluate_ready(wall)
            if (self.mission.value['status'] == 'running' and not self.ready
                    and self.goal_sent_wall is not None and wall-self.goal_sent_wall > 1):
                self.request_cancel('仿真状态过期，正在取消任务')
            if (self.goal_send_future is not None and not self.goal_send_future.done()
                    and wall-self.goal_sent_wall > 5 and not self.cancel_requested):
                self.request_cancel('任务接收超时，等待响应后取消')
            if self.cancel_requested and self.goal_handle is not None and not self.cancel_sent:
                self.send_cancel()
            for pending in list(self.pending_services):
                op, future, deadline = pending
                if not future.done() and wall > deadline:
                    if not op.future.done():
                        op.future.set_result((504, {'error': 'Obstacle service response timed out; poll actual state'}))
                    self.pending_services.remove(pending)
            for _ in range(4):
                try:
                    op = self.operations.get_nowait()
                except queue.Empty:
                    break
                if not op.future.set_running_or_notify_cancel():
                    continue
                if wall > op.deadline:
                    op.future.set_result((408, {'error': 'Request expired before ROS dispatch'}))
                    continue
                try:
                    if op.kind == 'mission':
                        self.start_mission(op.body)
                        op.future.set_result((202, self.state()))
                    elif op.kind == 'cancel':
                        if op.body:
                            raise APIError('Cancel request must be an empty object')
                        self.mission.request_cancel()
                        self.cancel_requested = True
                        if self.goal_handle is not None and not self.cancel_sent:
                            self.send_cancel()
                        op.future.set_result((202, self.state()))
                    elif op.kind == 'obstacle':
                        self.request_obstacle(op)
                    else:
                        raise APIError('Unknown operation', 404)
                except APIError as error:
                    op.future.set_result((error.status, {'error': str(error)}))
                except Exception as error:
                    self.get_logger().error(f'HTTP operation failed: {error}')
                    op.future.set_result((500, {'error': 'ROS operation failed'}))

    def start_mission(self, body):
        if self.mission.value['status'] in ACTIVE_STATUSES:
            raise APIError('A mission is already running or canceling', 409)
        if not self.ready:
            raise APIError(self.reason, 503)
        points, return_home = validate_mission(body, self.grid)
        goal = FollowWaypoints.Goal()
        goal.number_of_loops = 0
        goal.goal_index = 0
        for point in points:
            pose = PoseStamped()
            pose.header.frame_id = 'map'
            pose.header.stamp = self.get_clock().now().to_msg()
            pose.pose.position.x, pose.pose.position.y = point['x'], point['y']
            pose.pose.orientation.z = math.sin(point['yaw']/2)
            pose.pose.orientation.w = math.cos(point['yaw']/2)
            goal.poses.append(pose)
        mission_id = self.mission.begin(points, return_home)
        self.goal_handle = None
        self.cancel_requested = self.cancel_sent = False
        self.goal_sent_wall = time.monotonic()
        self.trajectory = [dict(self.truth and {'x': self.truth['x'], 'y': self.truth['y']} or HOME)]
        self.path = []
        try:
            self.goal_send_future = self.client.send_goal_async(
                goal, feedback_callback=lambda msg: self.feedback(mission_id, msg))
        except Exception:
            self.mission.value.update(status='failed', message='无法提交 Nav2 巡逻任务')
            raise
        self.goal_send_future.add_done_callback(lambda f: self.goal_response(mission_id, f))

    def feedback(self, mission_id, msg):
        with self.lock:
            if self.mission.value['id'] == mission_id:
                index = int(msg.feedback.current_waypoint)
                if 0 <= index < len(self.mission.value['waypoints']):
                    self.mission.value['current_index'] = index

    def goal_response(self, mission_id, future):
        with self.lock:
            if self.mission.value['id'] != mission_id:
                return
            try:
                handle = future.result()
                if not handle.accepted:
                    self.mission.value.update(status='failed', message='Nav2 拒绝了巡逻任务')
                    return
                self.goal_handle = handle
                if not self.cancel_requested:
                    self.mission.value['message'] = 'Nav2 巡逻进行中'
                handle.get_result_async().add_done_callback(lambda f: self.result(mission_id, f))
                if self.cancel_requested:
                    self.send_cancel()
            except Exception as error:
                self.mission.value.update(status='failed', message=f'任务接收失败：{error}')

    def result(self, mission_id, future):
        with self.lock:
            if self.mission.value['id'] != mission_id:
                return
            try:
                response = future.result()
                missed = [{'index': int(m.index), 'error_code': int(m.error_code)}
                          for m in response.result.missed_waypoints]
                self.mission.finish(response.status, response.result.error_code, missed,
                                    response.result.error_msg)
            except Exception as error:
                self.mission.value.update(status='failed', message=f'无法读取任务结果：{error}')
            self.goal_handle = None
            self.goal_send_future = None
            self.cancel_requested = self.cancel_sent = False

    def request_cancel(self, message):
        if self.mission.value['status'] not in ACTIVE_STATUSES:
            return
        self.mission.request_cancel()
        self.mission.value['message'] = message
        self.cancel_requested = True
        if self.goal_handle is not None and not self.cancel_sent:
            self.send_cancel()

    def send_cancel(self):
        self.cancel_sent = True
        mission_id = self.mission.value['id']
        self.goal_handle.cancel_goal_async().add_done_callback(lambda f: self.cancel_response(mission_id, f))

    def cancel_response(self, mission_id, future):
        with self.lock:
            if self.mission.value['id'] != mission_id or self.mission.value['status'] not in ACTIVE_STATUSES:
                return
            try:
                if not future.result().goals_canceling:
                    # Even a rejection can race a terminal success; the result decides.
                    self.mission.value['message'] = '取消未获确认，等待 Nav2 最终结果'
                else:
                    self.mission.value['message'] = 'Nav2 已接收取消请求，等待终止结果'
            except Exception as error:
                self.mission.value['message'] = f'取消响应异常，等待最终结果：{error}'

    def request_obstacle(self, op):
        if (set(op.body) != {'action'} or not isinstance(op.body['action'], str)
                or op.body['action'] not in self.obstacle_clients):
            raise APIError('Obstacle action must be block or clear')
        action = op.body['action']
        if action == 'block' and not self.ready:
            raise APIError(self.reason, 503)
        client = self.obstacle_clients[action]
        if not client.service_is_ready():
            raise APIError('Obstacle service is not available', 503)
        future = client.call_async(Trigger.Request())
        pending = (op, future, time.monotonic()+2.0)
        self.pending_services.append(pending)
        def complete(f):
            with self.lock:
                if pending in self.pending_services:
                    self.pending_services.remove(pending)
                if op.future.done():
                    return
                try:
                    response = f.result()
                    if response.success:
                        op.future.set_result((202, self.state()))
                    else:
                        op.future.set_result((409, {'error': response.message or 'Obstacle operation rejected'}))
                except Exception:
                    op.future.set_result((500, {'error': 'Obstacle service failed'}))
        future.add_done_callback(complete)


class LocalHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, port, bridge):
        self.bridge = bridge
        super().__init__(('127.0.0.1', port), Handler)
        self.port = self.server_address[1]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(4.0)

    def allowed(self):
        host = self.headers.get('Host', '')
        if host not in {f'127.0.0.1:{self.server.port}', f'localhost:{self.server.port}'}:
            return False
        origin = self.headers.get('Origin')
        if origin is None:
            return True
        try:
            parsed = urlsplit(origin)
            return (parsed.scheme == 'http' and parsed.hostname in {'localhost', '127.0.0.1'}
                    and parsed.port in {5173, 5174, 5175, 5176, 5177}
                    and not parsed.path and not parsed.query and not parsed.fragment
                    and parsed.username is None)
        except ValueError:
            return False

    def reply(self, status, body):
        encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(encoded)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if self.headers.get('Origin') and self.allowed():
            self.send_header('Access-Control-Allow-Origin', self.headers['Origin'])
            self.send_header('Vary', 'Origin')
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self):
        if not self.allowed():
            self.reply(403, {'error': 'Local browser origin required'})
            return
        self.send_response(204)
        if self.headers.get('Origin'):
            self.send_header('Access-Control-Allow-Origin', self.headers['Origin'])
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        if not self.allowed():
            self.reply(403, {'error': 'Local browser origin required'})
            return
        path = urlsplit(self.path).path
        if path == '/sim-api/state':
            self.reply(200, self.server.bridge.state())
        elif path == '/sim-api/map':
            with self.server.bridge.lock:
                grid = copy.deepcopy(self.server.bridge.grid)
            self.reply(200, grid) if grid else self.reply(503, {'error': 'Map is not available'})
        else:
            self.reply(404, {'error': 'Unknown endpoint'})

    def do_POST(self):
        if not self.allowed():
            self.reply(403, {'error': 'Local browser origin required'})
            return
        paths = {'/sim-api/mission': 'mission', '/sim-api/cancel': 'cancel',
                 '/sim-api/obstacle': 'obstacle'}
        kind = paths.get(urlsplit(self.path).path)
        if kind is None:
            self.reply(404, {'error': 'Unknown endpoint'})
            return
        future = None
        try:
            if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
                raise APIError('Content-Type must be application/json', 415)
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 8192:
                raise APIError('JSON body must be between 1 and 8192 bytes', 413)
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise APIError('JSON body must be an object')
            future = self.server.bridge.enqueue(kind, body)
            status, result = future.result(timeout=3.0)
            self.reply(status, result)
        except FutureTimeout:
            if future is not None:
                future.cancel()  # Prevent a queued request executing after the HTTP timeout.
            self.reply(504, {'error': 'ROS bridge response timed out; poll actual state'})
        except APIError as error:
            self.reply(error.status, {'error': str(error)})
        except (ValueError, UnicodeError, TimeoutError):
            self.reply(400, {'error': 'Invalid or incomplete JSON body'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=9070)
    args, ros_args = parser.parse_known_args()
    if args.port < 1024 or args.port > 65535:
        raise SystemExit('HTTP port must be between 1024 and 65535')
    if os.environ.get('ROS_DOMAIN_ID') != '93' or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST':
        raise SystemExit('Requires simulation domain 93 and LOCALHOST discovery')
    # Keep ROS alive briefly on SIGINT/SIGTERM so an active action can be canceled.
    rclpy.init(args=ros_args, signal_handler_options=SignalHandlerOptions.NO)
    def stop(_signal, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    bridge = MissionBridge()
    executor = SingleThreadedExecutor()
    executor.add_node(bridge)
    server = None
    try:
        server = LocalHTTPServer(args.port, bridge)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        bridge.get_logger().info(f'MuJoCo mission API http://127.0.0.1:{args.port}/sim-api/state')
        executor.spin()
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if rclpy.ok():
            with bridge.lock:
                bridge.request_cancel('桥接正在关闭，取消任务')
            deadline = time.monotonic()+3
            while bridge.mission.value['status'] in ACTIVE_STATUSES and time.monotonic() < deadline:
                executor.spin_once(timeout_sec=0.1)
        executor.shutdown()
        bridge.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
