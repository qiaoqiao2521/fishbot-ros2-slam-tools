#!/usr/bin/python3
"""Loopback-only HTTP mission API for an explicitly isolated MuJoCo domain.

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
from geometry_msgs.msg import PoseStamped, TwistStamped
from lifecycle_msgs.srv import GetState
from mujoco_ros2_control_msgs.msg import FreeJointStateArray
from nav2_msgs.action import FollowWaypoints
from nav2_msgs.msg import CollisionMonitorState, CostmapFilterInfo
from nav2_msgs.srv import GetCostmap
from nav_msgs.msg import OccupancyGrid, Odometry, Path
from rclpy.action import ActionClient
from rclpy.clock import Clock, ClockType
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import (DurabilityPolicy, QoSProfile, ReliabilityPolicy,
                      qos_profile_sensor_data)
from rclpy.signals import SignalHandlerOptions
from rcl_interfaces.srv import GetParameters
from rcl_interfaces.msg import ParameterType
from rosgraph_msgs.msg import Clock as ClockMessage
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformListener
from wait_ready import validate_sim_domain
from map_rules import (MapRulesError, MapRulesStore, build_mask, costmap_matches_mask,
                       grid_to_world, grid_value_at, integer, map_identity, require_outside_rules)
from rviz_desktop import RvizDesktop, RvizDesktopError


HOME = {'x': 0.0, 'y': 0.0, 'yaw': 0.0}
ROBOT_RADIUS = 0.13
MAX_WAYPOINTS = 12  # User-selected points; an optional home point is additional.
ACTIVE_STATUSES = {'running', 'canceling'}
CLEANUP_ATTEMPTS = 3
CLEANUP_RETRY_SECONDS = 1.0
CLEANUP_RESPONSE_SECONDS = 3.0
CM_ACTIONS = {0: 'do_nothing', 1: 'stop', 2: 'slowdown', 3: 'approach', 4: 'limit'}
RULES_GRAPH_FAILURE_SECONDS = 3.0
RULES_GRAPH_MAX_SAMPLE_GAP = 1.5


def simulation_domain(environ=None):
    env = os.environ if environ is None else environ
    validate_sim_domain(env)
    if env.get('ROS_STATIC_PEERS', '').strip():
        raise SystemExit('Mission API requires empty ROS_STATIC_PEERS for loopback isolation')
    return int(env.get('FISHBOT_MUJOCO_DOMAIN_ID', '93'))


class APIError(Exception):
    def __init__(self, message, status=400, outcome=None):
        super().__init__(message)
        self.status = status
        self.outcome = outcome


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


def validate_mission(body, grid, now=None, zones=None):
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
        require_outside_rules(parsed, zones or [], ROBOT_RADIUS)
        points.append(parsed)
    if return_home and any(abs(points[-1][axis]-HOME[axis]) > 1e-6 for axis in HOME):
        require_free_point(HOME, grid)
        require_outside_rules(HOME, zones or [], ROBOT_RADIUS)
        points.append(dict(HOME))
    return points, return_home


class MissionRecord:
    """Only terminal action results can produce a successful/canceled mission."""
    def __init__(self):
        self.value = {'id': None, 'status': 'idle', 'current_index': 0, 'waypoints': [],
                      'return_home': False, 'message': '等待巡逻任务', 'missed_waypoints': [],
                      'dispatch_state': None, 'stop_reason': None, 'cleanup_state': None}

    def begin(self, points, return_home):
        if self.value['status'] in ACTIVE_STATUSES:
            raise APIError('A mission is already running or canceling', 409)
        # Keep the legacy active-status contract; dispatch_state carries the Nav2 receipt.
        self.value = {'id': uuid.uuid4().hex, 'status': 'running', 'current_index': 0,
                      'waypoints': points, 'return_home': return_home,
                      'message': '任务已提交，等待 Nav2 接收回执', 'missed_waypoints': [],
                      'dispatch_state': 'pending', 'stop_reason': None, 'cleanup_state': None}
        return self.value['id']

    def request_cancel(self, reason='用户请求取消'):
        if self.value['status'] not in ACTIVE_STATUSES:
            raise APIError('There is no active mission to cancel', 409)
        if self.value['stop_reason'] is None:
            self.value['stop_reason'] = reason
        self.value['status'] = 'canceling'
        self.value['message'] = '正在请求取消，等待 Nav2 实际结果'

    def finish(self, status, error_code, missed, error_msg=''):
        self.value['cleanup_state'] = None
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
    def __init__(self, domain=93):
        super().__init__('fishbot_mission_bridge', parameter_overrides=[
            rclpy.parameter.Parameter('use_sim_time', value=True)])
        self.lock = threading.RLock()
        self.domain = domain
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
        self.command = None
        self.scan_summary = None
        cache = os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache'))
        self.rules_store = MapRulesStore(os.environ.get('FISHBOT_MAP_RULES_DIR',
            os.path.join(cache, 'fishbot', 'map-rules', f'domain-{domain}')))
        self.rules_mask = self.previous_rules_mask = None
        self.rules_epoch = 0
        self.rules_publish_stamp = 0.0
        self.rules_published_map_id = ''
        self.rules_published_revision = None
        self.rules_refresh_wall = 0.0
        self.rules_apply_state = 'unavailable'
        self.rules_apply_message = '等待地图与禁区过滤器'
        self.rules_hard_failure = False
        self.rules_graph_missing_since = self.rules_graph_missing_last = None
        self.rules_check_wall = 0.0
        self.rules_run = None
        self.rules_run_store = None
        self.rules_run_signature = None
        self.rules_run_sample_wall = self.rules_run_save_wall = 0.0
        self.obstacle = {'state': 'unknown', 'x': None, 'y': None, 'size': 0.36}
        self.obstacle_truth = None
        self.obstacle_truth_wall = None
        self.obstacle_state_wall = None
        self.goal_handle = None
        self.goal_send_future = None
        self.goal_sent_wall = None
        self.cancel_sent = False
        self.cancel_requested = False
        self.reset_cleanup()
        self.cm_report = None
        self.cm_publishers = ()
        self.cm_check_wall = 0.0
        self.last_lifecycle_poll = 0.0
        self.lifecycle = {name: {'active': False, 'wall': 0.0, 'future': None}
                          for name in ('amcl', 'controller_server', 'bt_navigator',
                                       'collision_monitor', 'waypoint_follower',
                                       'global_costmap/global_costmap', 'local_costmap/local_costmap')}
        self.lifecycle_clients = {name: self.create_client(GetState, f'/{name}/get_state')
                                  for name in self.lifecycle}
        self.obstacle_clients = {
            'block': self.create_client(Trigger, '/sim/obstacle/block_path'),
            'clear': self.create_client(Trigger, '/sim/obstacle/clear')}
        self.pending_services = []
        self.client = ActionClient(self, FollowWaypoints, '/follow_waypoints')
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self)
        rules_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                               durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.rules_mask_publisher = self.create_publisher(OccupancyGrid, '/keepout_filter_mask', rules_qos)
        self.rules_info_publisher = self.create_publisher(CostmapFilterInfo,
                                                        '/keepout_costmap_filter_info', rules_qos)
        self.rules_checks = {}
        for name in ('global', 'local'):
            self.rules_checks[name] = {'params_ok': False, 'config_invalid': False, 'config_reason': '',
                'costmap_ok': False,
                'mismatch_since': None, 'mismatch_last': None,
                'wall': 0.0, 'params_future': None, 'costmap_future': None,
                'params_client': self.create_client(GetParameters,
                    f'/{name}_costmap/{name}_costmap/get_parameters'),
                'costmap_client': self.create_client(GetCostmap, f'/{name}_costmap/get_costmap')}
        self.create_subscription(ClockMessage, '/clock', self.on_clock, qos_profile_sensor_data)
        self.create_subscription(LaserScan, '/scan', self.on_scan, qos_profile_sensor_data)
        self.create_subscription(Odometry, '/odom', self.on_odom, qos_profile_sensor_data)
        self.create_subscription(FreeJointStateArray, '/ground_truth/free_joint_states',
                                 self.on_truth, qos_profile_sensor_data)
        self.create_subscription(Path, '/plan', self.on_path, 10)
        self.create_subscription(TwistStamped, '/cmd_vel', self.on_command, 10)
        self.create_subscription(String, '/sim/obstacle/state', self.on_obstacle, 10)
        # Jazzy CM publishes a volatile change event, not a timestamped heartbeat.
        self.create_subscription(CollisionMonitorState, '/collision_monitor_state',
                                 self.on_collision_monitor, 10)
        self.create_subscription(OccupancyGrid, '/map', self.on_map,
                                 QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                            durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.ready = False
        self.reason = '等待仿真时钟、传感器与 Nav2 启动'
        # A steady timer keeps HTTP/readiness alive even when simulation time pauses.
        self.create_timer(0.1, self.tick, clock=Clock(clock_type=ClockType.STEADY_TIME))

    def sample(self, name, stamp):
        self.samples[name] = (stamp_seconds(stamp), time.monotonic())

    def on_collision_monitor(self, msg):
        with self.lock:
            action = CM_ACTIONS.get(msg.action_type)
            self.cm_report = (None if action is None else {
                'action': action, 'action_type': int(msg.action_type),
                'polygon_name': msg.polygon_name, 'wall': time.monotonic()})

    def poll_collision_monitor(self, wall):
        if wall-self.cm_check_wall < 0.75:
            return
        self.cm_check_wall = wall
        try:
            publishers = tuple(sorted(bytes(info.endpoint_gid) for info in
                self.get_publishers_info_by_topic('/collision_monitor_state')))
        except Exception:
            publishers = ()
        if publishers != self.cm_publishers and (self.cm_publishers or not publishers):
            # A replacement publisher starts a new observation epoch.
            self.cm_report = None
        self.cm_publishers = publishers
        lifecycle = self.lifecycle['collision_monitor']
        if not lifecycle['active'] or wall-lifecycle['wall'] > 3:
            self.cm_report = None

    def collision_monitor_state(self, wall):
        lifecycle = self.lifecycle['collision_monitor']
        available = bool(self.cm_publishers) and lifecycle['active'] and wall-lifecycle['wall'] <= 3
        report = self.cm_report if available else None
        return {'source': '/collision_monitor_state', 'available': available,
                'action': report['action'] if report else 'unknown',
                'action_type': report['action_type'] if report else None,
                'polygon_name': report['polygon_name'] if report else None,
                'observation_age_s': max(0.0, wall-report['wall']) if report else None}

    def on_clock(self, msg):
        with self.lock:
            current = stamp_seconds(msg.clock)
            rolled_back = self.clock_last is not None and current < self.clock_last
            if self.clock_last is not None and current > self.clock_last:
                self.clock_advance_wall = time.monotonic()
            elif self.clock_last is not None and current < self.clock_last:
                self.clock_advance_wall = None
                self.cm_report = None
            self.clock_last = current
            self.sample('clock', msg.clock)
            if rolled_back and hasattr(self, 'rules_store') and self.rules_mask is not None:
                # A simulator reset starts a new verification epoch. This is not
                # periodic republication and does not replay the old mission.
                self.publish_rules()

    def on_scan(self, msg):
        if not any(math.isfinite(v) and msg.range_min <= v <= msg.range_max for v in msg.ranges):
            return
        with self.lock:
            self.sample('scan', msg.header.stamp)
            values = [v for v in msg.ranges if math.isfinite(v) and msg.range_min <= v <= msg.range_max]
            self.scan_summary = {'stamp_sim': stamp_seconds(msg.header.stamp),
                'count': len(msg.ranges), 'valid_count': len(values), 'nearest_m': min(values)}

    def on_command(self, msg):
        if math.isfinite(msg.twist.linear.x) and math.isfinite(msg.twist.angular.z):
            with self.lock:
                self.command = {'linear_x': msg.twist.linear.x, 'angular_z': msg.twist.angular.z,
                                'received_at': time.time(), 'stamp_sim': stamp_seconds(msg.header.stamp)}

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
            if self.rules_store.map_id and self.rules_store.map_id != map_identity(self.grid):
                # Keep an active old-map run's original store until its real
                # terminal result; never write it into the new map document.
                self.rules_store = MapRulesStore(self.rules_store.directory)
            if self.rules_store.bind(self.grid):
                if self.mission.value['status'] in ACTIVE_STATUSES:
                    self.request_cancel('地图版本变更，取消旧地图任务')
                self.publish_rules()
                # A previous bridge may have disappeared while Nav2 still owned a
                # goal. Keep unknown ownership visible; never replay that mission.
                if not self.rules_store.error:
                    unknown = next((r for r in self.rules_store.document['runs']
                                    if r['status'] == 'unknown'), None)
                    if unknown and self.mission.value['status'] == 'idle':
                        self.mission.value.update(id=unknown['id'], status='canceling',
                            waypoints=unknown['waypoints'], return_home=unknown['return_home'],
                            current_index=unknown['current_index'], dispatch_state='unavailable',
                            cleanup_state='unresolved', stop_reason=unknown.get('stop_reason'),
                            message=unknown['message'])

    def rules_state(self):
        with self.lock:
            if self.rules_store.error or not self.rules_store.map_id:
                return {'map_id': self.rules_store.map_id, 'revision': 0, 'zones': [],
                        'apply_state': 'unavailable',
                        'message': self.rules_store.error or '等待地图'}
            rules = self.rules_store.rules()
            if not MissionBridge.published_rules_current(self):
                return {**rules, 'apply_state': 'unavailable',
                        'message': '已保存规则版本尚未发布，等待执行线程同步'}
            return {**rules, 'apply_state': self.rules_apply_state, 'message': self.rules_apply_message}

    def published_rules_current(self):
        doc = self.rules_store.document
        return (doc is not None and self.rules_published_map_id == doc['map_id']
                and self.rules_published_revision == doc['revision'])

    def synchronize_rules(self, wall):
        if not self.rules_store.map_id or self.rules_store.error:
            return
        try:
            if wall-self.rules_refresh_wall >= .75:
                self.rules_refresh_wall = wall
                self.rules_store.refresh()
            if not self.published_rules_current():
                if self.mission.value['status'] in ACTIVE_STATUSES:
                    self.request_cancel('地图规则版本变更，取消旧规则任务')
                self.publish_rules()
        except MapRulesError as error:
            self.rules_apply_state, self.rules_apply_message = 'unavailable', str(error)
            self.get_logger().error(f'Rules refresh unavailable: {error}')

    def publish_rules(self):
        self.rules_epoch += 1
        for check in self.rules_checks.values():
            check.update(params_ok=False, config_invalid=False, config_reason='', costmap_ok=False, wall=0.,
                         mismatch_since=None, mismatch_last=None)
        self.rules_hard_failure = False
        self.rules_graph_missing_since = self.rules_graph_missing_last = None
        if self.rules_store.error or not self.rules_store.map_id:
            self.rules_apply_state = 'unavailable'
            self.rules_apply_message = self.rules_store.error or '等待地图'
            return
        self.previous_rules_mask = self.rules_mask
        try:
            self.rules_mask = build_mask(self.grid, self.rules_store.document['zones'])
            mask = OccupancyGrid()
            mask.header.frame_id = 'map'
            mask.header.stamp = self.get_clock().now().to_msg()
            self.rules_publish_stamp = stamp_seconds(mask.header.stamp)
            mask.info.map_load_time = mask.header.stamp
            mask.info.width, mask.info.height = self.rules_mask['width'], self.rules_mask['height']
            mask.info.resolution = self.rules_mask['resolution']
            mask.info.origin.position.x, mask.info.origin.position.y = self.rules_mask['origin'][:2]
            mask.info.origin.orientation.w = 1.
            mask.data = self.rules_mask['data']
            info = CostmapFilterInfo()
            info.header = mask.header
            info.type = 0  # KEEP_OUT; base + multiplier * occupancy yields the mask cost.
            info.filter_mask_topic = '/keepout_filter_mask'
            info.base, info.multiplier = 0., 1.
            self.rules_mask_publisher.publish(mask)
            self.rules_info_publisher.publish(info)
            self.rules_published_map_id = self.rules_store.map_id
            self.rules_published_revision = self.rules_store.document['revision']
            self.rules_apply_state = 'published'
            self.rules_apply_message = '规则已保存并发布，等待全局与局部代价地图读回确认'
        except Exception as error:
            self.rules_mask = None
            self.rules_apply_state = 'unavailable'
            self.rules_apply_message = f'禁区发布失败：{error}'

    def rules_subscribers_present(self):
        required = {'/global_costmap/global_costmap', '/local_costmap/local_costmap'}
        for topic in ('/keepout_filter_mask', '/keepout_costmap_filter_info'):
            names = {f'{item.node_namespace.rstrip("/")}/{item.node_name}'
                     for item in self.get_subscriptions_info_by_topic(topic)}
            if not required <= names:
                return False
        return True

    def poll_rules(self, wall):
        if wall-self.rules_check_wall < .75 or self.rules_mask is None or self.rules_store.error:
            return
        self.rules_check_wall = wall
        epoch = self.rules_epoch
        for name, check in self.rules_checks.items():
            for kind in ('params', 'costmap'):
                future = check[f'{kind}_future']
                if future is not None:
                    if wall-check[f'{kind}_sent'] > 3.:
                        check[f'{kind}_client'].remove_pending_request(future)
                        check[f'{kind}_future'] = None
                        check[f'{kind}_ok'] = False
                        if kind == 'costmap':
                            check.update(mismatch_since=None, mismatch_last=None)
                        future.cancel()
                    else:
                        continue
                client = check[f'{kind}_client']
                if not client.service_is_ready():
                    check[f'{kind}_ok'] = False
                    if kind == 'costmap':
                        check.update(mismatch_since=None, mismatch_last=None)
                    continue
                request = GetParameters.Request() if kind == 'params' else GetCostmap.Request()
                if kind == 'params':
                    request.names = ['filters', 'keepout_filter.plugin', 'keepout_filter.enabled',
                                     'keepout_filter.filter_info_topic', 'robot_radius']
                check[f'{kind}_sent'] = wall
                future = client.call_async(request)
                check[f'{kind}_future'] = future
                future.add_done_callback(lambda f, n=name, k=kind, e=epoch: self.rules_result(n, k, e, f))
        try:
            healthy = self.rules_subscribers_present()
            graph_missing = not healthy
        except Exception:
            healthy = False
            graph_missing = False  # A graph query exception is not proof of missing consumers.
            self.rules_graph_missing_since = self.rules_graph_missing_last = None
        if graph_missing:
            # Nav2 clearing recovery resets and recreates filter subscriptions.
            # Only successive observations of a persistent disappearance can
            # invalidate an already-running mission's same rules revision.
            if (self.rules_graph_missing_since is None or self.rules_graph_missing_last is None
                    or wall-self.rules_graph_missing_last > RULES_GRAPH_MAX_SAMPLE_GAP):
                self.rules_graph_missing_since = wall
            self.rules_graph_missing_last = wall
        else:
            self.rules_graph_missing_since = self.rules_graph_missing_last = None
        graph_failed = (graph_missing and self.rules_graph_missing_since is not None
                        and wall-self.rules_graph_missing_since >= RULES_GRAPH_FAILURE_SECONDS)
        for name, check in self.rules_checks.items():
            lifecycle = self.lifecycle[f'{name}_costmap/{name}_costmap']
            healthy = (healthy and lifecycle['active'] and wall-lifecycle['wall'] <= 3.
                       and check['params_ok'] and check['costmap_ok'] and wall-check['wall'] <= 3.)
        self.rules_apply_state = 'applied' if healthy else 'published'
        if healthy:
            # Both costmaps have confirmed this revision's deletion transaction.
            # Later sensor observations may legitimately occupy a removed zone;
            # they must not turn an already-confirmed deletion into a new failure.
            # Current mask cells remain under continuous readback verification.
            self.previous_rules_mask = None
        invalid = [(name, check.get('config_reason', '')) for name, check in self.rules_checks.items()
                   if check['config_invalid']]
        mismatched = [name for name, check in self.rules_checks.items()
            if check.get('mismatch_since') is not None and check.get('mismatch_last') is not None
            and check['mismatch_last']-check['mismatch_since'] >= RULES_GRAPH_FAILURE_SECONDS
            and wall-check['mismatch_last'] <= RULES_GRAPH_MAX_SAMPLE_GAP]
        self.rules_hard_failure = bool(invalid) or graph_failed or bool(mismatched)
        if invalid:
            self.rules_apply_message = '禁区过滤器配置失配：'+', '.join(
                f'{name}: {reason}' for name, reason in invalid)
        elif graph_failed:
            self.rules_apply_message = '禁区过滤器订阅连续缺失至少3秒，无法维持规则执行确认'
        elif mismatched:
            self.rules_apply_message = '禁区格连续读回未生效至少3秒：'+', '.join(mismatched)
        elif healthy:
            self.rules_apply_message = '全局与局部禁区过滤器及代价地图已读回确认'
        else:
            self.rules_apply_message = '禁区确认暂缺，现有任务继续等待恢复；新任务需等待读回确认'

    def observe_rules_mismatch(self, name, wall, missing):
        check = self.rules_checks[name]
        if not missing:
            check.update(mismatch_since=None, mismatch_last=None)
            return
        if (check.get('mismatch_since') is None or check.get('mismatch_last') is None
                or wall-check['mismatch_last'] > RULES_GRAPH_MAX_SAMPLE_GAP):
            check['mismatch_since'] = wall
        check['mismatch_last'] = wall

    def rules_result(self, name, kind, epoch, future):
        with self.lock:
            check = self.rules_checks[name]
            if check[f'{kind}_future'] is not future:
                return
            check[f'{kind}_future'] = None
            if epoch != self.rules_epoch:
                return
            try:
                response = future.result()
                if kind == 'params':
                    values = response.values
                    types = (ParameterType.PARAMETER_STRING_ARRAY, ParameterType.PARAMETER_STRING,
                             ParameterType.PARAMETER_BOOL, ParameterType.PARAMETER_STRING,
                             ParameterType.PARAMETER_DOUBLE)
                    if len(values) != 5 or tuple(value.type for value in values) != types:
                        # Not-yet-declared parameters during lifecycle recovery
                        # are unavailable evidence, not an explicit disable.
                        check.update(params_ok=False, config_invalid=False, config_reason='')
                        return
                    matches = ('keepout_filter' in values[0].string_array_value,
                        values[1].string_value == 'nav2_costmap_2d::KeepoutFilter', values[2].bool_value,
                        values[3].string_value == '/keepout_costmap_filter_info',
                        abs(values[4].double_value-ROBOT_RADIUS) < 1e-6)
                    labels = ('filters', 'plugin', 'enabled', 'filter_info_topic', 'robot_radius')
                    check.update(params_ok=all(matches), config_invalid=not all(matches),
                                 config_reason=', '.join(label for label, match in zip(labels, matches) if not match))
                    return
                msg = response.map
                metadata = msg.metadata
                ros_now = self.get_clock().now().nanoseconds*1e-9
                if (stamp_seconds(metadata.update_time) <= self.rules_publish_stamp
                        or not -.15 <= ros_now-stamp_seconds(metadata.update_time) <= 1.5
                        or not 0 < metadata.size_x*metadata.size_y <= 4_000_000
                        or len(msg.data) != metadata.size_x*metadata.size_y
                        or not 0 < metadata.resolution <= 1.):
                    check['costmap_ok'] = False
                    MissionBridge.observe_rules_mismatch(self, name, time.monotonic(), False)
                    return
                origin = metadata.origin
                ox, oy, yaw = origin.position.x, origin.position.y, quaternion_yaw(origin.orientation)
                if msg.header.frame_id != 'map':
                    transform = self.buffer.lookup_transform('map', msg.header.frame_id,
                        rclpy.time.Time.from_msg(metadata.update_time))
                    p, q = transform.transform.translation, transform.transform.rotation
                    theta = quaternion_yaw(q)
                    ox, oy = p.x+math.cos(theta)*ox-math.sin(theta)*oy, p.y+math.sin(theta)*ox+math.cos(theta)*oy
                    yaw += theta
                if not all(math.isfinite(v) for v in (ox, oy, yaw)):
                    raise ValueError('Invalid costmap origin')
                grid = {'width': metadata.size_x, 'height': metadata.size_y,
                        'resolution': metadata.resolution, 'origin': [ox, oy, yaw], 'data': list(msg.data)}
                matches, _marked, _cleared = costmap_matches_mask(grid, self.rules_mask,
                                                               self.previous_rules_mask, self.grid)
                # Global costmap must cover all forbidden cells; local rolling
                # costmap checks only cells currently inside its window.
                known_missing = False
                if name == 'global':
                    for index, value in enumerate(self.rules_mask['data']):
                        if value == 100:
                            x, y = grid_to_world((index % self.rules_mask['width']+.5)*self.rules_mask['resolution'],
                                (index // self.rules_mask['width']+.5)*self.rules_mask['resolution'], self.rules_mask)
                            observed = grid_value_at(x, y, grid)
                            if observed != 254:
                                matches = False
                                if observed is not None and 0 <= observed < 254:
                                    known_missing = True
                # Global map-frame cells provide comparable negative evidence.
                # Local TF failures or edge differences remain pending rather
                # than using a latest transform as proof that a rule disappeared.
                MissionBridge.observe_rules_mismatch(self, name, time.monotonic(),
                    known_missing and msg.header.frame_id == 'map')
                check.update(costmap_ok=matches, wall=time.monotonic())
            except Exception as error:
                check[f'{kind}_ok'] = False
                if kind == 'costmap':
                    MissionBridge.observe_rules_mismatch(self, name, time.monotonic(), False)
                self.get_logger().debug(f'Keepout {name} {kind} readback pending: {error}')

    def record_run(self, force=False):
        if self.rules_run is None:
            return
        wall = time.monotonic()
        mission = self.mission.value
        if mission['id'] != self.rules_run['id']:
            return
        signature = tuple(mission.get(key) for key in ('status', 'current_index', 'dispatch_state',
                                                       'cleanup_state', 'stop_reason', 'message'))
        changed = signature != self.rules_run_signature
        self.rules_run.update({key: copy.deepcopy(mission.get(key)) for key in
                               ('status', 'current_index', 'dispatch_state', 'cleanup_state',
                                'stop_reason', 'message', 'missed_waypoints')})
        self.rules_run['truth'] = copy.deepcopy(self.truth)
        if changed:
            self.rules_run['events'].append({'time_unix': time.time(), 'sim_time': self.clock_last,
                'type': 'mission_state', 'status': mission['status'], 'current_index': mission['current_index'],
                'dispatch_state': mission.get('dispatch_state'), 'cleanup_state': mission.get('cleanup_state'),
                'stop_reason': mission.get('stop_reason'), 'message': mission['message']})
            self.rules_run['events'] = self.rules_run['events'][-300:]
            self.rules_run_signature = signature
        if mission['status'] not in ACTIVE_STATUSES:
            if self.rules_run['finished_at'] is None:
                self.rules_run['finished_at'] = time.time()
                self.rules_run['observations'] = self.rules_run['observations'][-60:]
                force = True
        elif wall-self.rules_run_sample_wall >= 1.:
            self.rules_run['observations'].append({'time_unix': time.time(), 'sim_time': self.clock_last,
                'pose': copy.deepcopy(self.pose), 'truth': copy.deepcopy(self.truth),
                'scan_summary': copy.deepcopy(self.scan_summary), 'command': copy.deepcopy(self.command),
                'path': copy.deepcopy(self.path[:32]), 'current_index': mission['current_index']})
            self.rules_run['observations'] = self.rules_run['observations'][-300:]
            self.rules_run_sample_wall = wall
        if changed or force or (mission['status'] in ACTIVE_STATUSES and wall-self.rules_run_save_wall >= 5.):
            try:
                self.rules_run_store.save_run(self.rules_run)
                self.rules_run_save_wall = wall
            except MapRulesError as error:
                self.rules_apply_state = 'unavailable'
                self.rules_apply_message = str(error)
                self.get_logger().error(f'Run persistence failed: {error}')

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
        if hasattr(self, 'rules_store') and self.rules_hard_failure:
            return False, self.rules_apply_message
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
            return copy.deepcopy({'mode': 'mujoco', 'domain': self.domain,
                'ready': self.ready, 'reason': self.reason,
                'pose': self.pose if self.ready else None,
                'truth': self.truth if clock_fresh and self.fresh('truth', ros_now, wall) else None,
                'path': self.path, 'trajectory': self.trajectory,
                'mission': self.mission.value, 'obstacle': obstacle, 'home': HOME,
                'map_rules': self.rules_state() if hasattr(self, 'rules_store') else None,
                'collision_monitor': self.collision_monitor_state(wall)})

    def enqueue(self, kind, body):
        op = Operation(kind, body, time.monotonic()+2.0, Future())
        try:
            self.operations.put_nowait(op)
        except queue.Full:
            raise APIError('Bridge request queue is full', 503, outcome='rejected')
        return op.future

    def tick(self):
        with self.lock:
            wall = time.monotonic()
            self.poll_lifecycle(wall)
            self.poll_collision_monitor(wall)
            if hasattr(self, 'rules_store'):
                self.synchronize_rules(wall)
                self.poll_rules(wall)
            self.ready, self.reason = self.evaluate_ready(wall)
            if (self.mission.value['status'] == 'running' and not self.ready
                    and self.goal_sent_wall is not None and wall-self.goal_sent_wall > 1):
                self.request_cancel(f'仿真未就绪：{self.reason}')
            if (self.goal_send_future is not None and not self.goal_send_future.done()
                    and wall-self.goal_sent_wall > 5 and not self.cancel_requested):
                self.request_cancel('任务接收超时，等待响应后取消')
            self.retry_cleanup(wall)
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
                    op.future.set_result((408, {'error': 'Request expired before ROS dispatch',
                                               'outcome': 'rejected'}))
                    continue
                try:
                    if op.kind == 'mission':
                        self.start_mission(op.body)
                        op.future.set_result((202, self.state()))
                    elif op.kind == 'cancel':
                        if op.body:
                            raise APIError('Cancel request must be an empty object')
                        if self.mission.value['status'] not in ACTIVE_STATUSES:
                            raise APIError('There is no active mission to cancel', 409)
                        self.request_cancel('用户请求取消',
                            retry=self.mission.value.get('cleanup_state') == 'unresolved')
                        op.future.set_result((202, self.state()))
                    elif op.kind == 'obstacle':
                        self.request_obstacle(op)
                    elif op.kind == 'map-rules':
                        self.rules_store.update_rules(op.body,
                            active=self.mission.value['status'] in ACTIVE_STATUSES)
                        self.publish_rules()
                        op.future.set_result((200, self.rules_state()))
                    elif op.kind == 'routes':
                        body = op.body
                        if not isinstance(body, dict):
                            raise APIError('Route must be an object')
                        points, returning = validate_mission({'waypoints': body.get('waypoints'),
                            'return_home': body.get('return_home', False), 'issued_at': time.time()}, self.grid)
                        body = {**body, 'waypoints': points[:len(body['waypoints'])], 'return_home': returning}
                        op.future.set_result((200, self.rules_store.save_route(body)))
                    else:
                        raise APIError('Unknown operation', 404)
                except (APIError, MapRulesError) as error:
                    payload = {'error': str(error)}
                    if getattr(error, 'outcome', None) is not None:
                        payload['outcome'] = error.outcome
                    op.future.set_result((error.status, payload))
                except Exception as error:
                    self.get_logger().error(f'HTTP operation failed: {error}')
                    op.future.set_result((500, {'error': 'ROS operation failed'}))
            if hasattr(self, 'rules_store'):
                self.record_run()

    def prepare_mission(self, body):
        """All errors here precede dispatch and are authoritative rejections."""
        try:
            if self.mission.value['status'] in ACTIVE_STATUSES:
                raise APIError('A mission is already running or canceling', 409)
            if not self.ready:
                raise APIError(self.reason, 503)
            zones = []
            if hasattr(self, 'rules_store'):
                self.rules_store.refresh()
                if not MissionBridge.published_rules_current(self):
                    raise APIError('Saved rules version is not yet published; wait for synchronization', 409)
                if self.rules_apply_state != 'applied':
                    raise APIError(self.rules_apply_message, 503)
                rules = self.rules_store.rules()
                if not isinstance(body, dict):
                    raise APIError('Mission must be an object')
                if 'map_id' in body and body['map_id'] != rules['map_id']:
                    raise APIError('Mission map identity changed; reload before sending', 409)
                if ('rules_revision' in body
                        and integer(body['rules_revision'], 'rules_revision') != rules['revision']):
                    raise APIError('Mission rules revision changed; reload before sending', 409)
                body = {key: value for key, value in body.items() if key not in {'map_id', 'rules_revision'}}
                zones = rules['zones']
            return validate_mission(body, self.grid, zones=zones)
        except (APIError, MapRulesError) as error:
            error.outcome = 'rejected'
            raise

    def start_mission(self, body):
        points, return_home = MissionBridge.prepare_mission(self, body)
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
        previous_mission = copy.deepcopy(self.mission.value)
        mission_id = self.mission.begin(points, return_home)
        if hasattr(self, 'rules_store'):
            self.rules_run_store = self.rules_store
            self.rules_run = {'id': mission_id, 'map_id': self.rules_store.map_id,
                'rules_revision': self.rules_store.document['revision'], 'started_at': time.time(),
                'finished_at': None, 'status': 'running', 'current_index': 0,
                'waypoints': copy.deepcopy(points), 'return_home': return_home,
                'stop_reason': None, 'message': self.mission.value['message'],
                'dispatch_state': 'pending', 'cleanup_state': None,
                'events': [], 'observations': [], 'truth': copy.deepcopy(self.truth)}
            self.mission.value.update(map_id=self.rules_store.map_id,
                                      rules_revision=self.rules_store.document['revision'])
            self.rules_run_signature = None
            try:
                # Record ownership before dispatch; a write failure sends no goal.
                self.rules_store.save_run(self.rules_run,
                    expected_rules_revision=self.mission.value['rules_revision'])
            except MapRulesError as error:
                self.mission.value = previous_mission
                self.rules_run = None
                # Persistence may be ambiguous, but this goal has not been sent.
                error.outcome = 'rejected'
                raise
        self.goal_handle = None
        self.cancel_requested = self.cancel_sent = False
        self.reset_cleanup()
        self.goal_sent_wall = time.monotonic()
        self.trajectory = [dict(self.truth and {'x': self.truth['x'], 'y': self.truth['y']} or HOME)]
        self.path = []
        try:
            self.goal_send_future = self.client.send_goal_async(
                goal, feedback_callback=lambda msg: self.feedback(mission_id, msg))
        except Exception as error:
            # A local send error does not establish whether Nav2 received the goal.
            self.mission.value['dispatch_state'] = 'unavailable'
            self.request_cancel(f'提交异常，Nav2 接收状态未知：{error}')
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
                    self.mission.value.update(status='failed', dispatch_state='rejected',
                                              message='Nav2 拒绝了巡逻任务')
                    if hasattr(self, 'rules_store'):
                        self.record_run(force=True)
                    return
                self.goal_handle = handle
                self.mission.value['dispatch_state'] = 'accepted'
                if not self.cancel_requested:
                    self.mission.value['message'] = 'Nav2 已接受，巡逻进行中'
                self.subscribe_result()
                if self.cancel_requested and self.goal_handle is not None:
                    self.send_cancel()
            except Exception as error:
                if self.mission.value['dispatch_state'] != 'accepted':
                    self.mission.value['dispatch_state'] = 'unavailable'
                    self.request_cancel(f'接收回执异常，Nav2 接收状态未知：{error}')
                else:
                    self.request_cancel(f'已接受任务的回执异常：{error}')

    def reset_cleanup(self):
        self.result_future = self.cancel_future = None
        self.result_attempts = self.cancel_attempts = 0
        self.result_retry_wall = self.cancel_retry_wall = 0.0
        self.result_sent_wall = self.cancel_sent_wall = 0.0
        self.cancel_requested_wall = None

    def subscribe_result(self):
        if self.goal_handle is None or self.result_future is not None:
            return
        mission_id = self.mission.value['id']
        self.result_attempts += 1
        self.result_sent_wall = time.monotonic()
        try:
            future = self.goal_handle.get_result_async()
            self.result_future = future
            future.add_done_callback(lambda f: self.result(mission_id, f))
        except Exception as error:
            self.result_future = None
            self.result_retry_wall = time.monotonic()+CLEANUP_RETRY_SECONDS
            self.request_cancel(f'结果回执异常，正在收束任务：{error}')

    def result(self, mission_id, future):
        with self.lock:
            if self.mission.value['id'] != mission_id or self.result_future is not future:
                return
            try:
                response = future.result()
                if response.status not in (GoalStatus.STATUS_SUCCEEDED,
                                            GoalStatus.STATUS_CANCELED, GoalStatus.STATUS_ABORTED):
                    raise RuntimeError(f'Nav2 未返回终态：{response.status}')
                missed = [{'index': int(m.index), 'error_code': int(m.error_code)}
                          for m in response.result.missed_waypoints]
                self.mission.finish(response.status, response.result.error_code, missed,
                                    response.result.error_msg)
                if hasattr(self, 'rules_store'):
                    self.record_run(force=True)
            except Exception as error:
                self.result_future = None
                self.result_retry_wall = time.monotonic()+CLEANUP_RETRY_SECONDS
                self.request_cancel(f'无法确认任务结果，正在收束：{error}')
                return
            self.goal_handle = None
            self.goal_send_future = None
            self.cancel_requested = self.cancel_sent = False
            self.reset_cleanup()

    def request_cancel(self, message, retry=False):
        if self.mission.value['status'] not in ACTIVE_STATUSES:
            return
        self.mission.request_cancel(message)
        self.mission.value['message'] = message
        self.cancel_requested = True
        if self.cancel_requested_wall is None:
            self.cancel_requested_wall = time.monotonic()
        if retry:
            self.result_attempts = self.cancel_attempts = 0
            self.result_retry_wall = self.cancel_retry_wall = 0.0
            self.cancel_sent = False
        self.mission.value['cleanup_state'] = 'retrying'
        if self.goal_handle is None and self.mission.value.get('dispatch_state') == 'unavailable':
            self.mission.value.update(cleanup_state='unresolved',
                message='Nav2 接收状态未知，当前无法确认取消；原任务保留，禁止派发新目标')
            return
        if self.goal_handle is not None and not self.cancel_sent:
            self.send_cancel()

    def send_cancel(self):
        if (self.goal_handle is None or self.cancel_future is not None or self.cancel_sent
                or self.cancel_attempts >= CLEANUP_ATTEMPTS
                or time.monotonic() < self.cancel_retry_wall):
            return
        mission_id = self.mission.value['id']
        self.cancel_attempts += 1
        self.cancel_sent_wall = time.monotonic()
        try:
            future = self.goal_handle.cancel_goal_async()
            self.cancel_future = future
            future.add_done_callback(lambda f: self.cancel_response(mission_id, f))
        except Exception as error:
            self.cancel_future = None
            self.cancel_retry_wall = time.monotonic()+CLEANUP_RETRY_SECONDS
            self.mission.value['message'] = f'取消发送异常，保留目标等待重试：{error}'

    def cancel_response(self, mission_id, future):
        with self.lock:
            if (self.mission.value['id'] != mission_id or self.cancel_future is not future
                    or self.mission.value['status'] not in ACTIVE_STATUSES):
                return
            self.cancel_future = None
            try:
                if not future.result().goals_canceling:
                    # Even a rejection can race a terminal success; the result decides.
                    self.mission.value['message'] = '取消未获确认，等待 Nav2 最终结果'
                else:
                    self.cancel_sent = True
                    self.mission.value['message'] = 'Nav2 已接收取消请求，等待终止结果'
            except Exception as error:
                self.mission.value['message'] = f'取消响应异常，等待最终结果：{error}'
            self.cancel_retry_wall = time.monotonic()+CLEANUP_RETRY_SECONDS

    def retry_cleanup(self, wall):
        if not self.cancel_requested or self.goal_handle is None:
            return
        for name in ('result', 'cancel'):
            future = getattr(self, name+'_future')
            sent = getattr(self, name+'_sent_wall')
            since = max(sent, self.cancel_requested_wall or sent)
            if future is not None and not future.done() and wall-since > CLEANUP_RESPONSE_SECONDS:
                # Canceling a local future removes the rclpy pending request, not the Nav2 goal.
                setattr(self, name+'_future', None)
                future.cancel()
                setattr(self, name+'_retry_wall', wall+CLEANUP_RETRY_SECONDS)
        if (self.result_future is None and self.result_attempts < CLEANUP_ATTEMPTS
                and wall >= self.result_retry_wall):
            self.subscribe_result()
        if not self.cancel_sent and wall >= self.cancel_retry_wall:
            self.send_cancel()
        result_exhausted = self.result_future is None and self.result_attempts >= CLEANUP_ATTEMPTS
        cancel_exhausted = (not self.cancel_sent and self.cancel_future is None
                            and self.cancel_attempts >= CLEANUP_ATTEMPTS)
        if result_exhausted or cancel_exhausted:
            self.mission.value['cleanup_state'] = 'unresolved'
            self.mission.value['message'] = '有限收束未确认终态；目标仍保留，可重试取消，不能派发新目标'

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

    def __init__(self, port, bridge, ui_port=5173):
        self.bridge = bridge
        self.rviz = RvizDesktop(bridge.domain)
        self.ui_ports = {5173, 5174, 5175, 5176, 5177, ui_port}
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
                    and parsed.port in self.server.ui_ports
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
        elif path == '/sim-api/rviz':
            self.reply(200, self.server.rviz.status())
        elif path == '/sim-api/map':
            with self.server.bridge.lock:
                grid = copy.deepcopy(self.server.bridge.grid)
                if grid and hasattr(self.server.bridge, 'rules_store'):
                    grid['map_id'] = self.server.bridge.rules_store.map_id
            self.reply(200, grid) if grid else self.reply(503, {'error': 'Map is not available'})
        elif path in {'/sim-api/map-rules', '/sim-api/routes', '/sim-api/runs'}:
            try:
                with self.server.bridge.lock:
                    if path == '/sim-api/map-rules':
                        result = self.server.bridge.rules_state()
                    elif path == '/sim-api/routes':
                        result = self.server.bridge.rules_store.routes()
                    else:
                        result = self.server.bridge.rules_store.runs()
                self.reply(200, result)
            except MapRulesError as error:
                self.reply(error.status, {'error': str(error)})
        else:
            self.reply(404, {'error': 'Unknown endpoint'})

    def do_POST(self):
        if not self.allowed():
            self.reply(403, {'error': 'Local browser origin required'})
            return
        paths = {'/sim-api/mission': 'mission', '/sim-api/cancel': 'cancel',
                 '/sim-api/obstacle': 'obstacle', '/sim-api/map-rules': 'map-rules',
                 '/sim-api/routes': 'routes', '/sim-api/rviz': 'rviz'}
        kind = paths.get(urlsplit(self.path).path)
        if kind is None:
            self.reply(404, {'error': 'Unknown endpoint'})
            return
        future = None
        try:
            if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
                raise APIError('Content-Type must be application/json', 415)
            length = int(self.headers.get('Content-Length', '0'))
            maximum = 65536 if kind in {'map-rules', 'routes'} else 8192
            if not 0 < length <= maximum:
                raise APIError(f'JSON body must be between 1 and {maximum} bytes', 413)
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise APIError('JSON body must be an object')
            if kind == 'rviz':
                if body:
                    raise APIError('RViz endpoint accepts only an empty object')
                try:
                    status, result = self.server.rviz.open()
                except RvizDesktopError as error:
                    raise APIError(str(error), error.status) from error
                self.reply(status, result)
                return
            future = self.server.bridge.enqueue(kind, body)
            status, result = future.result(timeout=3.0)
            self.reply(status, result)
        except FutureTimeout:
            if future is not None:
                future.cancel()  # Prevent a queued request executing after the HTTP timeout.
            self.reply(504, {'error': 'ROS bridge response timed out; poll actual state'})
        except APIError as error:
            payload = {'error': str(error)}
            if error.outcome is not None:
                payload['outcome'] = error.outcome
            self.reply(error.status, payload)
        except (ValueError, UnicodeError, TimeoutError):
            self.reply(400, {'error': 'Invalid or incomplete JSON body'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=9070)
    parser.add_argument('--ui-port', type=int, default=5173)
    args, ros_args = parser.parse_known_args()
    if args.port < 1024 or args.port > 65535:
        raise SystemExit('HTTP port must be between 1024 and 65535')
    if args.ui_port < 1024 or args.ui_port > 65535:
        raise SystemExit('UI port must be between 1024 and 65535')
    domain = simulation_domain()
    # Keep ROS alive briefly on SIGINT/SIGTERM so an active action can be canceled.
    rclpy.init(args=ros_args, signal_handler_options=SignalHandlerOptions.NO)
    def stop(_signal, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    bridge = MissionBridge(domain=domain)
    executor = SingleThreadedExecutor()
    executor.add_node(bridge)
    server = None
    try:
        server = LocalHTTPServer(args.port, bridge, ui_port=args.ui_port)
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
