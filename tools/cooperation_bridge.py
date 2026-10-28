#!/usr/bin/env python3
"""Real Nav2 and contact-feedback orchestration; local synthetic worlds only."""
import argparse
import copy
import uuid
import hashlib
import json
import math
import os
import struct
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from urllib.parse import parse_qs

from cooperation_core import (ACTIVE, ContinuousEvidence, Rejected, arm_home_quiet, car_pose,
                              cargo_retained, dispatch_terminal, finite_vector,
                              physical_quiet, quaternion, request_identity,
                              task_scope, task_delivery_pose, task_delivery_approaches, task_business_delivery,
                              reset_request_identity,
                              release_ready_for_retreat, stopped, tip_forces, transport_handoff_ready, validate_physics)
from cooperation_core import station_robot_pose, within_station_capture
from cooperation_perception import (map_covariance, messages_to_observation,
                                    normalize_config, validate_observation)
from cooperation_readiness import NativeReadiness, StaticLocalizationWarmup
from cooperation_sim import LoopTiming
from cooperation_geometry_check import SceneGeometry
from cooperation_loaded_limits import LoadedVelocityLimits, LoadedRppLimits
from cooperation_delivery_route import DELIVERY_ROUTE_WALL_S
from fishbot_runtime import (INSTANCE_HEADER, RUNTIME_CHANGED, RuntimeIdentity, capability,
                            DomainExecutionLock, ExecutionOwnerBusy)


def normalize_egress_motion(value):
    if not isinstance(value, dict) or value.get('type') != 'drive_on_heading':
        raise ValueError('出站运动须为 drive_on_heading')
    distance, speed, allowance = finite_vector(
        [value.get(key) for key in ('distance_m', 'speed_m_s', 'time_allowance_s')], 3, '出站运动')
    if min(distance, speed, allowance) <= 0:
        raise ValueError('出站距离、速度和原生允许时间须为正数')
    speed = struct.unpack('<f', struct.pack('<f', speed))[0]
    if not math.isfinite(speed) or speed <= 0 or round(allowance*1e9) < 1:
        raise ValueError('出站运动超出原生消息数值范围')
    return {'type': 'drive_on_heading', 'distance_m': distance,
            'speed_m_s': speed, 'time_allowance_s': allowance}


class BridgeTiming(LoopTiming):
    """Reuse bounded loop observations for this bridge's processing phases."""
    STAGES = ('physics_callback', 'physics_json', 'physics_validation',
              'physics_readiness', 'physics_lock_wait', 'physics_cache_commit',
              'station_detection', 'station_pair', 'station_lock_wait',
              'station_parse', 'station_admission', 'station_publisher_query',
              'station_pose_publish', 'station_admission_publish',
              'http_lock_wait', 'http_assembly', 'clock_callback', 'clock_update')

    def __init__(self):
        super().__init__()
        self.diagnostic_lock = threading.RLock()
        self.last = {}

    def record(self, stage, start, end, context):
        with self.diagnostic_lock:
            super().observe(stage, start, end, context.get('source_stamp'))
            event = dict(context, stage=stage, start_monotonic=start,
                         end_monotonic=end, duration_s=end-start)
            self.last[stage] = event
            if end-start >= .1:
                self.slow_tail[-1].update(context)

    def snapshot(self):
        with self.diagnostic_lock:
            value = super().snapshot()
            value.update(last={name: event.copy() for name, event in self.last.items()},
                         native_consumption_ack=False,
                         boundary='bridge processing only; not controller consumption',
                         dds_timestamp_clock='RMW timestamp basis unverified; raw nanoseconds only')
            return value


class Canceled(RuntimeError):
    pass


def make_server(bridge, args, *, runtime):
    """HTTP boundary; discovery does not call state() or any ROS operation."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*unused): pass
        def send_json(self,status,value):
            content=json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store')
            self.send_header(INSTANCE_HEADER, runtime.instance_id)
            self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
        def do_GET(self):
            path=urlsplit(self.path).path
            if path=='/coop-api/runtime':
                self.send_json(200, runtime.snapshot(episode_id=bridge.episode_id));return
            if path=='/coop-api/state':self.send_json(200,bridge.state());return
            if path=='/coop-api/report':
                try:
                    report = json.loads((args.output.parent/'acceptance-report.json').read_text())
                    self.send_json(200, report)
                except (OSError, ValueError):
                    self.send_json(404, {'error': '本运行尚无独立验收报告'})
                return
            if path=='/coop-api/vision-frame.jpg':
                try:
                    query = parse_qs(urlsplit(self.path).query)
                    with bridge.lock:
                        info = bridge.vision_frame_request(query)
                        content = bridge.vision_frame_image(info).read_bytes()
                except Rejected as error:
                    self.send_json(error.status, {'error':str(error)});return
                except (OSError, ValueError, KeyError, TypeError, RuntimeError):
                    self.send_json(503, {'error': '后向相机图像已更新或不可用'});return
                self.send_response(200);self.send_header('Content-Type','image/jpeg');self.send_header('Cache-Control','no-store')
                self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content);return
            if path.startswith('/coop-api/reset/'):
                try:self.send_json(200,bridge.reset_record(path.rsplit('/',1)[1]))
                except Rejected as error:self.send_json(error.status,{'error':str(error),'outcome':'rejected'})
                return
            if path.startswith('/coop-api/checkpoint/'):
                try:self.send_json(200,bridge.checkpoint_record(path.rsplit('/',1)[1]))
                except Rejected as error:self.send_json(error.status,{'error':str(error),'outcome':'rejected'})
                return
            if path=='/coop-api/frame.jpg':
                try:
                    with bridge.lock:
                        episode=parse_qs(urlsplit(self.path).query).get('episode_id',[None])[0]
                        if episode is not None and episode != bridge.episode_id:
                            self.send_json(409,{'error':'相机回合已变化'});return
                        if not bridge.frame_state()['available']:
                            self.send_json(503,{'error':'共享相机帧缺失、过期或来源不匹配'});return
                        info=json.loads((args.frame_dir/'latest.json').read_text())
                        content=bridge.frame_image(info).read_bytes()
                except (OSError, ValueError, KeyError, TypeError):
                    self.send_json(503,{'error':'尚无当前回合共享物理世界画面'});return
                self.send_response(200);self.send_header('Content-Type','image/jpeg');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content);return
            self.send_json(404,{'error':'未知接口'})
        def do_POST(self):
            if not runtime.accepts(self.headers):
                self.send_json(409, RUNTIME_CHANGED);return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=4096:raise Rejected('请求长度无效')
                body=json.loads(self.rfile.read(size))
                path=urlsplit(self.path).path
                if path=='/coop-api/start':result=bridge.start(body)
                elif path=='/coop-api/cancel':result=bridge.cancel(body)
                elif path=='/coop-api/reset':result=bridge.reset_episode(body)
                elif path=='/coop-api/checkpoint':result=bridge.request_checkpoint(body)
                else:raise Rejected('未知接口',404)
                self.send_json(200,result)
            except (Rejected,ValueError,TypeError) as error:self.send_json(getattr(error,'status',400),{'error':str(error),'outcome':'rejected'})
            except Exception as error:self.send_json(500,{'error':str(error),'outcome':'unknown'})
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    server.daemon_threads = True
    server.runtime = runtime
    return server


def run(args):
    if (args.output/'task.json').exists():
        raise RuntimeError('已有任务账本，不能复用旧物理回合；保留记录并创建新场景与运行目录')
    import numpy as np
    import rclpy
    from rclpy.action import ActionClient
    from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
    from rclpy.executors import MultiThreadedExecutor, ExternalShutdownException
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, qos_profile_sensor_data
    from rclpy.time import Time
    from rclpy.time_source import TimeSource
    from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped, TwistStamped
    from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
    from message_filters import Subscriber, TimeSynchronizer
    from nav2_msgs.action import NavigateToPose, DockRobot, DriveOnHeading
    from nav2_msgs.srv import ClearEntireCostmap, SetInitialPose
    from sensor_msgs.msg import JointState
    from rosgraph_msgs.msg import Clock
    from std_msgs.msg import Bool, String
    from std_srvs.srv import Empty
    from tf2_ros import Buffer, TransformListener
    from cooperation_arm import ArmPlanner, query_approach, query_placement

    manifest = json.loads(args.manifest.read_text())
    scene_sha = hashlib.sha256(Path(manifest['world_xml']).read_bytes()).hexdigest()
    manifest_sha = hashlib.sha256(args.manifest.read_bytes()).hexdigest()

    class Bridge(Node):
        def __init__(self):
            # TimeSource subscribes during Node construction. Keep its standard
            # clock update independent of native action callbacks in the default group.
            self.clock_callbacks = MutuallyExclusiveCallbackGroup()
            super().__init__('fishbot_so101_cooperation', parameter_overrides=[rclpy.parameter.Parameter('use_sim_time', value=True)])
            self.lock = threading.RLock()
            # Control may hold its lock while querying/publishing perception.
            # Cache commits never acquire that lock; nested users take control first.
            self.physics_cache_lock = threading.RLock()
            self.delivery_geometry_lock = threading.RLock()
            self.delivery_geometry = None
            self.delivery_geometry_error = None
            self.bridge_timing = BridgeTiming()
            self.raw = None
            self.received = 0.
            self.cancel_event = threading.Event()
            self.abort_event = threading.Event()
            self.abort_reason = None
            self.observation_error = None
            self.worker = threading.local()
            self.execution_token = None
            self.task_epoch = self.dispatch_epoch = 0
            self.dispatches = []
            self.cleanup_summary = {'state': 'not_started', 'native_terminal': False,
                                    'quiet': False, 'hold': False, 'guard_disabled': False}
            self.last_ref = list(manifest['arm_home_qpos6'])
            self.task = {'id': None, 'status': 'idle', 'stage': 'idle', 'message': '等待装货运输任务', 'stop_reason': None}
            self.events = []
            self.known_ids = set()
            self.loaded = False
            self.business_inventory = None
            self.loaded_limits = None
            self.loaded_controller = None
            for attribute, field, adapter_type, node_name in (
                    ('loaded_limits', 'loaded_velocity_smoother', LoadedVelocityLimits, '/velocity_smoother'),
                    ('loaded_controller', 'loaded_controller', LoadedRppLimits, '/controller_server')):
                desired = manifest.get('vehicle_profile', {}).get(field)
                if desired is None:
                    continue
                from lifecycle_msgs.srv import GetState
                from rclpy.parameter_client import AsyncParameterClient
                parameter_client = AsyncParameterClient(self, node_name)
                lifecycle_client = self.create_client(GetState, node_name+'/get_state')
                setattr(self, attribute, adapter_type(desired, parameter_client,
                    lambda client=lifecycle_client: client.call_async(GetState.Request()),
                    lambda name, value: rclpy.parameter.Parameter(name, value=value)))
            self.episode_id = None
            self.task_worker = None
            self.reset_worker = None
            self.reset_records = {}
            self.reset_acks = {}
            self.reset_runtime = {}
            self.last_reset_id = None
            self.checkpoint_records = {}
            self.history = []
            self.buffer = Buffer()
            self.listener = TransformListener(self.buffer, self)
            self.nav = ActionClient(self, NavigateToPose, '/navigate_to_pose')
            self.docking = ActionClient(self, DockRobot, '/dock_robot')
            self.egress_client = (ActionClient(self, DriveOnHeading, '/drive_on_heading')
                                  if manifest.get('egress_motion') is not None else None)
            self.native_readiness = NativeReadiness(self)
            self.localization_warmup = None
            if manifest.get('restore_checkpoint') and manifest.get('checkpoint_warmup'):
                warmup_config = manifest['checkpoint_warmup']
                if not isinstance(warmup_config,dict):
                    self.get_logger().warning('R2 warmup config invalid; using 3 fresh AMCL frames')
                    warmup_config = {}
                updates = warmup_config.get('nomotion_updates',3)
                if type(updates) is not int or updates < 1:
                    self.get_logger().warning('R2 warmup count invalid; using 3 fresh AMCL frames')
                    updates = 3
                initializer = ((self.create_client(SetInitialPose,'/set_initial_pose'),
                                self.branch_initial_pose_request)
                               if warmup_config.get('initial_pose') is not None else None)
                self.localization_warmup = StaticLocalizationWarmup(
                    self.create_client(Empty,'/request_nomotion_update'),Empty.Request,updates,
                    initializer=initializer)
                self.create_subscription(PoseWithCovarianceStamped,'/amcl_pose',
                                         self.observe_warmup_pose,qos_profile_sensor_data)
            self.physics_callbacks = MutuallyExclusiveCallbackGroup()
            self.perception_callbacks = MutuallyExclusiveCallbackGroup()
            self.last_freshness_failure = None
            self.beacon = None
            self.perception_config = normalize_config(manifest.get('station_perception'))
            if self.perception_config['station_id'] != manifest['native_docking']['dock_id']:
                raise ValueError('观测工位与原生停靠工位不一致')
            self.station_last_seen = None
            self.station_detection = None
            self.station_rejection = None
            self.station_counts = {'accepted': 0, 'unavailable': 0, 'rejected': 0, 'forwarded': 0}
            self.station_rejection_reason_counts = {}
            self.last_station_pose_stamp = -math.inf
            self.vision_quality = None
            self.pose_pub = self.create_publisher(PoseWithCovarianceStamped, '/initialpose', 1)
            self.dock_pose_pub = self.create_publisher(PoseStamped, '/detected_dock_pose', 1)
            # Exact source stamps, bounded queues, and standard ROS messages.
            perception_qos = copy.copy(qos_profile_sensor_data)
            perception_qos.depth = 1
            self.station_pose_filter = Subscriber(self, PoseWithCovarianceStamped,
                                                  '/cooperation/station_pose', qos_profile=perception_qos,
                                                  callback_group=self.perception_callbacks)
            self.station_detection_filter = Subscriber(self, DiagnosticArray,
                                                       '/cooperation/station_detection', qos_profile=perception_qos,
                                                       callback_group=self.perception_callbacks)
            self.station_detection_filter.registerCallback(self.observe_station_detection)
            self.station_sync = TimeSynchronizer(
                [self.station_pose_filter, self.station_detection_filter], queue_size=5)
            self.station_sync.registerCallback(self.observe_station_pair)
            hold_qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE)
            self.hold_pub = self.create_publisher(Bool, '/cooperation/car_hold', hold_qos)
            if manifest.get('terminal_stop_heartbeat') is True:
                self.terminal_zero_pub = self.create_publisher(TwistStamped, '/cmd_vel_nav', 1)
            self.dock_guard_pub = self.create_publisher(Bool, '/cooperation/docking_guard', hold_qos)
            self.fault_trigger_pub = self.create_publisher(String, '/cooperation/observation_fault_trigger', 1)
            self.admission_pub = self.create_publisher(DiagnosticArray, '/cooperation/station_admission', 10)
            self.dock_guard_active = False
            self.arm_pub = self.create_publisher(JointState, '/cooperation/arm_reference', 1)
            reset_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                   durability=DurabilityPolicy.VOLATILE)
            self.reset_pub = self.create_publisher(String, '/cooperation/reset_request', reset_qos)
            self.create_subscription(String, '/cooperation/reset_result', self.observe_reset, reset_qos)
            self.checkpoint_pub = self.create_publisher(String, '/cooperation/checkpoint_request', reset_qos)
            self.create_subscription(String, '/cooperation/checkpoint_result', self.observe_checkpoint, reset_qos)
            self.reset_clearers = [self.create_client(ClearEntireCostmap, path) for path in (
                '/global_costmap/clear_entirely_global_costmap', '/local_costmap/clear_entirely_local_costmap')]
            latest_state_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                                         durability=DurabilityPolicy.VOLATILE)
            self.create_subscription(String, '/cooperation/physics_state', self.observe_with_info, latest_state_qos,
                                     callback_group=self.physics_callbacks)
            self.create_subscription(DiagnosticArray, '/cooperation/vision_quality', self.observe_vision_quality, perception_qos,
                                     callback_group=self.perception_callbacks)
            args.output.mkdir(parents=True, exist_ok=True)
            self.ledger = args.output/'task.json'
            self.history_dir = args.output/'history'
            self.history_dir.mkdir(exist_ok=True)
            for path in sorted(self.history_dir.glob('*.json')):
                record = json.loads(path.read_text())
                if record['task']['status'] in ACTIVE:
                    raise RuntimeError('历史任务终态未知，不能通过新回合接管')
                self.history.append(record)
                if record['task'].get('id'): self.known_ids.add(record['task']['id'])
            self.hold(True)
            self.dock_guard_pub.publish(Bool(data=False))
            # Compile the independent query model before the HTTP server and
            # telemetry executor start. Optional geometry failure must not
            # remove the legacy no-destination start capability.
            self.prepare_delivery_geometry()

        def create_subscription(self, msg_type, topic, callback, qos_profile, *,
                                callback_group=None, event_callbacks=None,
                                qos_overriding_options=None, raw=False,
                                content_filter_options=None):
            if (msg_type is Clock and topic == '/clock' and callback_group is None
                    and isinstance(getattr(callback, '__self__', None), TimeSource)
                    and getattr(callback, '__func__', None) is TimeSource.clock_callback):
                callback_group = self.clock_callbacks
                original_callback = callback
                # A required second argument selects the real RMW metadata.
                def traced_clock(message, info):
                    return self.observe_clock(message, info, original_callback)
                callback = traced_clock
            return super().create_subscription(
                msg_type, topic, callback, qos_profile, callback_group=callback_group,
                event_callbacks=event_callbacks, qos_overriding_options=qos_overriding_options,
                raw=raw, content_filter_options=content_filter_options)

        def observe_clock(self, message, info, original_callback):
            started = time.monotonic()
            context = self.timing_context(info=info)
            inherited = self.timing_context(getattr(self, 'raw', None))
            for name in ('scene_sha256', 'manifest_sha256', 'episode_id', 'sequence',
                         'source_stamp', 'producer_wall_time'):
                context['inherited_physics_'+name] = inherited[name]
            context['identity_binding'] = 'Clock has no scene/episode; inherited_physics_* is cached bridge context'
            context['source_stamp_ns'] = message.clock.sec*1_000_000_000+message.clock.nanosec
            context['source_stamp'] = context['source_stamp_ns']*1e-9
            context['node_clock_stamp_at_entry'] = self.get_clock().now().nanoseconds*1e-9
            update_at = time.monotonic()
            try:
                return original_callback(message)
            finally:
                context['node_clock_stamp_after_update'] = self.get_clock().now().nanoseconds*1e-9
                self.timing_record('clock_update', update_at, context)
                self.timing_record('clock_callback', started, context)

        def persist(self):
            path = self.ledger.with_suffix('.tmp')
            path.write_text(json.dumps({'task': self.task, 'events': self.events, 'known_ids': sorted(self.known_ids),
                'episode_id': self.episode_id, 'reset_records': self.reset_records,
                'business_inventory': copy.deepcopy(getattr(self, 'business_inventory', None))}, ensure_ascii=False, indent=2)+'\n')
            path.replace(self.ledger)

        def timing_context(self, value=None, info=None):
            value = value if isinstance(value, dict) else {}
            source = value.get('source') if isinstance(value.get('source'), dict) else value
            context = {'entry_wall_time': time.time(), 'entry_monotonic': time.monotonic(),
                       'bridge_episode_id_at_entry': getattr(self, 'episode_id', None),
                       'dds_info_available': info is not None,
                       'dds_source_timestamp_ns': None, 'dds_received_timestamp_ns': None,
                       'producer_wall_time': None}
            for name in ('scene_sha256', 'manifest_sha256'):
                item = source.get(name)
                context[name] = item if isinstance(item, str) and len(item) == 64 else None
            item = value.get('episode_id')
            context['episode_id'] = item if isinstance(item, str) and len(item) <= 64 else None
            item = value.get('stamp_ns')
            context['source_stamp_ns'] = item if type(item) is int and item > 0 else None
            for name, output in (('stamp', 'source_stamp'), ('sequence', 'sequence'), ('wall_time', 'producer_wall_time')):
                item = value.get(name)
                try:
                    context[output] = item if isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(item) else None
                except OverflowError:
                    context[output] = None
            for name in ('source_timestamp', 'received_timestamp'):
                item = info.get(name) if isinstance(info, dict) else getattr(info, name, None)
                context['dds_'+name+'_ns'] = item if type(item) is int and item > 0 else None
            return context

        def station_timing_context(self, diagnostics):
            try:
                status = diagnostics.status[0]
                fields = {item.key: item.value for item in status.values if item.key in
                          ('scene_sha256', 'manifest_sha256', 'episode_id', 'sequence')}
                fields['sequence'] = int(fields['sequence'])
                fields['stamp_ns'] = diagnostics.header.stamp.sec*1_000_000_000+diagnostics.header.stamp.nanosec
                fields['stamp'] = fields['stamp_ns']*1e-9
                return self.timing_context(fields)
            except (AttributeError, IndexError, KeyError, TypeError, ValueError):
                return self.timing_context()

        def timing_record(self, stage, start, context, *, end=None):
            timing = getattr(self, 'bridge_timing', None)
            if timing is not None:
                timing.record(stage, start, time.monotonic() if end is None else end, context)

        def timing_measure(self, stage, function, *values, context=None):
            started = time.monotonic()
            try:
                return function(*values)
            finally:
                self.timing_record(stage, started, context or self.timing_context())

        def observe_with_info(self, message, info):
            # Jazzy selects one argument first when the second is optional.
            # A required two-argument adapter requests its real RMW metadata.
            return self.observe(message, info)

        def observe(self, message, info=None):
            started = time.monotonic()
            context = self.timing_context(info=info)
            try:
                parsed_at = time.monotonic()
                try:
                    value = json.loads(message.data)
                    bound = self.timing_context(value, info)
                    bound.update(entry_wall_time=context['entry_wall_time'], entry_monotonic=context['entry_monotonic'],
                                 bridge_episode_id_at_entry=context['bridge_episode_id_at_entry'])
                    context = bound
                finally:
                    self.timing_record('physics_json', parsed_at, context)
                value = self.timing_measure('physics_validation', validate_physics, value, scene_sha, manifest_sha,
                    (manifest.get('nq',22), manifest.get('nv',20), manifest.get('nu',8)), context=context)
                self.timing_measure('physics_readiness', self.native_readiness.update, context=context)
                episode = value.get('episode_id')
                if episode is not None and value['source'].get('episode_id') != episode:
                    raise ValueError('物理回合来源不一致')
                waiting_at = time.monotonic()
                with self.physics_cache_lock:
                    committed_at = time.monotonic()
                    if episode is not None and self.episode_id not in (None, episode):
                        context['outcome'] = 'foreign_episode_ignored'
                    else:
                        if episode is not None and self.episode_id is None:
                            self.episode_id = episode
                        self.raw, self.received = value, time.monotonic()
                        self.observation_error = None
                        context['outcome'] = 'cache_committed'
                    committed_end = time.monotonic()
                self.timing_record('physics_lock_wait', waiting_at, context, end=committed_at)
                self.timing_record('physics_cache_commit', committed_at, context, end=committed_end)
                if context.get('outcome') == 'cache_committed' and self.localization_warmup is not None:
                    self.localization_warmup.update(value['stamp'],
                        held=value['car_hold'] is True and stopped(value),
                        native_active=self.native_readiness.active())
            except (ValueError, KeyError, TypeError, IndexError) as error:
                reason = f'共享物理反馈无效：{error}'
                with self.lock:
                    with self.physics_cache_lock:
                        self.raw = None
                        self.observation_error = reason
                    if self.task['status'] in ACTIVE:
                        self.abort_event.set()
                        self.abort_reason = reason
                        self.hold(True)
                self.get_logger().warning(reason)
            finally:
                self.timing_record('physics_callback', started, context)

        def branch_initial_pose_request(self):
            prior = manifest['checkpoint_warmup']['initial_pose']
            mean = prior['mean']
            x,y,yaw = finite_vector([mean[k] for k in ('x','y','yaw')],3,'R2定位先验')
            covariance = finite_vector(prior['covariance'],36,'R2分支协方差')
            request = SetInitialPose.Request()
            request.pose.header.frame_id = 'map'
            request.pose.header.stamp = self.get_clock().now().to_msg()
            request.pose.pose.pose.position.x,request.pose.pose.pose.position.y = x,y
            request.pose.pose.pose.orientation.z = math.sin(yaw/2)
            request.pose.pose.pose.orientation.w = math.cos(yaw/2)
            request.pose.pose.covariance = covariance
            stamp = request.pose.header.stamp
            return request, {'frame_id':'map','source_s':stamp.sec+stamp.nanosec*1e-9,
                'pose':{'x':x,'y':y,'yaw':yaw},'covariance':[float(v) for v in request.pose.pose.covariance],
                'mean_source':prior.get('mean_source'),
                'covariance_source':prior.get('covariance_source')}

        def observe_warmup_pose(self, message):
            if self.localization_warmup is None:
                return
            p,q = message.pose.pose.position,message.pose.pose.orientation
            self.localization_warmup.observe(
                stamp=message.header.stamp.sec+message.header.stamp.nanosec*1e-9,
                pose={'x':p.x,'y':p.y,'yaw':math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))},
                covariance=list(message.pose.covariance),frame_id=message.header.frame_id,
                source_now=self.get_clock().now().nanoseconds*1e-9)

        def fresh(self):
            with self.lock:
                with self.physics_cache_lock:
                    raw, received, episode, error = self.raw, self.received, self.episode_id, self.observation_error
                if raw is None or time.monotonic()-received > .5:
                    raise RuntimeError(error or '共享物理反馈中断')
                validate_physics(raw, scene_sha, manifest_sha,
                    (manifest.get('nq',22), manifest.get('nv',20), manifest.get('nu',8)))
                if episode is not None and raw.get('episode_id') != episode:
                    raise RuntimeError('等待新回合的物理反馈')
                now_ns = self.get_clock().now().nanoseconds
                # Match the producer's standard ROS Time rounding. MuJoCo's
                # accumulated float stamp can otherwise cross an exact bound
                # by a fraction of a nanosecond while /clock is still on it.
                whole_seconds = int(raw['stamp'])
                physics_ns = whole_seconds*1_000_000_000 + round(
                    (raw['stamp']-whole_seconds)*1_000_000_000)
                age_ns = now_ns-physics_ns
                if not -100_000_000 <= age_ns <= 250_000_000:
                    self.last_freshness_failure = {'wall_time':time.time(),'task_id':self.task.get('id'),
                        'episode_id':episode,'clock_stamp':now_ns*1e-9,'physics_stamp':raw['stamp'],
                        'clock_stamp_ns':now_ns,'physics_stamp_ns':physics_ns,'source_age_ns':age_ns,
                        'source_age_s':age_ns*1e-9,'received_age_s':time.monotonic()-received}
                    raise RuntimeError('共享物理反馈时间失效')
                return copy.deepcopy(raw)

        def localized(self):
            transform = self.buffer.lookup_transform('map', 'base_footprint', Time())
            stamp = transform.header.stamp.sec+transform.header.stamp.nanosec*1e-9
            if not -1.2 <= self.get_clock().now().nanoseconds*1e-9-stamp <= .8:
                raise RuntimeError('Nav2定位已过期')
            p, q = transform.transform.translation, transform.transform.rotation
            finite_vector([p.x, p.y, p.z], 3, 'Nav2定位')
            quaternion([q.w, q.x, q.y, q.z], 'Nav2定位朝向')
            return {'x': p.x, 'y': p.y, 'yaw': math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))}

        def owner(self, token=None, *, allow_abort=False):
            token = token if token is not None else getattr(self.worker, 'token', None)
            if token is None or token != self.execution_token or token[0] != self.task['id']:
                raise RuntimeError('原任务已失去车臂控制权')
            if not allow_abort:
                if self.cancel_event.is_set():
                    raise Canceled('用户取消任务')
                if self.abort_event.is_set() or self.task['status'] != 'running':
                    raise RuntimeError(self.abort_reason or '原任务已停止执行')
            return token

        def hold(self, enabled, token=None):
            with self.lock:
                if not enabled:
                    self.owner(token)
                elif token is not None:
                    self.owner(token, allow_abort=True)
                self.hold_pub.publish(Bool(data=enabled))

        def set_docking_guard(self, enabled, token, *, allow_abort=False):
            with self.lock:
                self.owner(token,allow_abort=allow_abort)
                self.dock_guard_pub.publish(Bool(data=enabled))
                self.dock_guard_active=enabled

        def guard_acknowledged(self, raw):
            guard=raw.get('docking_guard')
            if (not isinstance(guard,dict) or type(guard.get('enabled')) is not bool
                    or type(guard.get('tripped')) is not bool or guard.get('frame')!='world'
                    or guard.get('body_origin')!='base_footprint' or guard.get('margin_m')!=.01
                    or finite_vector(guard.get('dock_pose'),3,'停靠平面')!=manifest['dock_pose']):
                raise RuntimeError('执行端停靠平面保护与当前场景不一致')
            finite_vector([guard.get('along_m')],1,'停靠沿程')
            return guard['enabled']

        def task_material(self, raw, arm_id=None):
            binding = self.task.get('business_delivery')
            if binding is None:
                return raw
            from cooperation_business import observe
            selected = arm_id or self.task.get('active_arm_id', binding['pickup_arm_id'])
            return observe(raw, manifest, binding['cargo_id'], selected)

        def business_quiet(self, raw):
            if not manifest.get('business_entities'):
                return True
            from cooperation_business import all_quiet
            return all_quiet(raw)

        def inventory(self, raw):
            from cooperation_business import new_inventory
            inventory = getattr(self, 'business_inventory', None)
            world = raw.get('world_session_id', raw['episode_id'])
            if inventory is None:
                inventory = new_inventory(manifest, world, raw['episode_id'])
                self.business_inventory = inventory
            if inventory['world_id'] != world or inventory['episode_id'] != raw['episode_id']:
                raise RuntimeError('库存所属物理世界已变化，不能沿用旧订单库存')
            return inventory

        def task_handoff(self, raw):
            binding = self.task.get('business_delivery')
            home = (manifest['business_entities']['arms'][binding['pickup_arm_id']]['home_qpos6']
                    if binding else manifest['arm_home_qpos6'])
            view = self.task_material(raw, binding['pickup_arm_id'] if binding else None)
            return transport_handoff_ready(view, home) and self.business_quiet(raw)

        def reference(self, value, *, token=None, freeze=False):
            with self.lock:
                self.owner(token, allow_abort=freeze)
                values = finite_vector(list(value), 6, '机械臂参考')
                if freeze:
                    raw = self.task_material(self.fresh())
                    if values[:5] != raw['q6'][:5] or values[5] != self.last_ref[5]:
                        raise RuntimeError('清理阶段只允许保持当前机械臂位置与原夹爪压力')
                message = JointState()
                message.header.stamp = self.get_clock().now().to_msg()
                message.name = manifest['arm_joint_names']
                binding = self.task.get('business_delivery')
                if binding is not None:
                    arm_id = self.task.get('active_arm_id', binding['pickup_arm_id'])
                    message.name = manifest['business_entities']['arms'][arm_id]['joint_names']
                message.position = values
                self.arm_pub.publish(message)
                self.last_ref = list(message.position)

        def freeze_arm(self, token):
            with self.lock:
                self.owner(token, allow_abort=True)
                try:
                    frozen = list(self.task_material(self.fresh())['q6'])
                    frozen[5] = self.last_ref[5]
                    self.reference(frozen, token=token, freeze=True)
                except (RuntimeError, ValueError, KeyError, TypeError):
                    # Missing current physical feedback cannot authorize a stale-position motion.
                    return False
                return True

        def cancel_dispatch(self, dispatch):
            handle = dispatch.get('handle')
            if handle and handle.accepted and not dispatch_terminal(dispatch) and not dispatch.get('cancel_requested'):
                dispatch['cancel_requested'] = True
                dispatch['cancel_requested_wall_time'] = time.time()
                try:
                    dispatch['cancel'] = handle.cancel_goal_async()
                except Exception as error:
                    dispatch['cancel_error'] = str(error)

        def abort(self, token, reason):
            with self.lock:
                self.owner(token, allow_abort=True)
                self.abort_event.set()
                self.abort_reason = self.abort_reason or str(reason)
                self.hold(True, token)
                for dispatch in self.dispatches:
                    if dispatch['token'] == token:
                        dispatch['aborted'] = True
                        self.cancel_dispatch(dispatch)
                self.freeze_arm(token)

        def event(self, role, stage, message, *, terminal=False):
            with self.lock:
                self.owner(allow_abort=terminal)
                stage = {'docking':'car_to_dock','docked':'dock_stopped','approach':'arm_grasp',
                    'descend':'arm_grasp','close':'arm_grasp','lift':'arm_lift','hold':'arm_lift',
                    'holding':'arm_lift','transport':'arm_transport','lower':'arm_transport',
                    'release':'arm_release','retreat':'arm_retreat','settle':'cargo_settle',
                    'loaded':'arm_retreat','delivery':'car_to_delivery','delivered':'delivery_stopped'}.get(stage,stage)
                self.task.update(stage=stage, message=message)
                self.events.append({'sequence': len(self.events)+1, 'time_s': self.get_clock().now().nanoseconds*1e-9,
                                    'role': role, 'message': message})
                self.persist()

        def check(self, *, carrying=False):
            with self.lock:
                self.owner()
                if time.monotonic()>self.wall_deadline:
                    raise RuntimeError('协同任务超过总执行时间')
                raw = self.fresh()
                if self.perception_config['mode'] == 'vision' and raw.get('camera_error'):
                    raise RuntimeError(f'后向相机渲染失败：{raw["camera_error"]}')
                if any(raw[f'{body}_forbidden_contact_{kind}']
                       for body in ('arm','car') for kind in ('count','total')):
                    raise RuntimeError('车体或机械臂发生非预期物理接触')
                material = self.task_material(raw)
                if carrying and not cargo_retained(material):
                    raise RuntimeError('运输途中货物离开托盘支撑范围')
                binding = self.task.get('business_delivery')
                home = (manifest['business_entities']['arms'][binding['pickup_arm_id']]['home_qpos6']
                        if binding else manifest['arm_home_qpos6'])
                if carrying and not arm_home_quiet(material, home):
                    raise RuntimeError('运输期间机械臂未保持回位停稳状态')
                if carrying and binding and any(not arm_home_quiet(
                        {'q6':raw['business_entities']['arms'][name]['qpos6'],
                         'qvel6':raw['business_entities']['arms'][name]['qvel6']},record['home_qpos6'])
                        for name,record in manifest['business_entities']['arms'].items()):
                    raise RuntimeError('运输期间其他工位机械臂未保持回位停稳')
                return raw

        def terminal_stop(self, dispatch, raw):
            """A fresh zero target after native success keeps the original braking tail live."""
            if manifest.get('terminal_stop_heartbeat') is True:
                with self.lock:
                    self.owner(dispatch['token'])
                    result = dispatch.get('result')
                    if (result is None or not result.done() or result.result().status != 4
                            or getattr(getattr(result.result(), 'result', None), 'success', True) is not True):
                        raise RuntimeError('Terminal zero target requires the owned native success')
                    evidence = dispatch.setdefault('terminal_stop_heartbeat', {'count': 0,
                        'native_terminal_status': 4, 'target': 'zero',
                        'scope': 'fresh terminal stop target, not refreshed motion or a consumption ACK'})
                    if evidence.get('last_source_stamp') != raw['stamp']:
                        message = TwistStamped()
                        now = self.get_clock().now()
                        message.header.stamp = now.to_msg()
                        message.header.frame_id = 'base_footprint'
                        self.terminal_zero_pub.publish(message)
                        evidence.update(count=evidence['count']+1, last_source_stamp=raw['stamp'],
                                        last_command_stamp=now.nanoseconds*1e-9)
            return stopped(raw)

        def wait_condition(self, condition, *, duration=.7, timeout=8., carrying=False, cancelable=True):
            gate = ContinuousEvidence(duration)
            started = time.monotonic()
            end = started+timeout
            evidence = {'stage': self.task.get('stage'), 'required_source_duration_s': duration,
                        'timeout_wall_s': timeout, 'max_source_gap_s': gate.max_gap,
                        'unique_samples': 0, 'invalid_samples': 0, 'repeated_samples': 0,
                        'maximum_observed_source_gap_s': 0., 'longest_source_duration_s': 0.,
                        'outcome': 'interrupted'}
            try:
                while time.monotonic()<end:
                    raw = self.check(carrying=carrying) if cancelable else self.fresh()
                    stamp, valid = raw['stamp'], bool(condition(raw))
                    if gate.last == stamp:
                        evidence['repeated_samples'] += 1
                    else:
                        evidence['unique_samples'] += 1
                        evidence['invalid_samples'] += not valid
                        if gate.last is not None:
                            evidence['maximum_observed_source_gap_s'] = max(
                                evidence['maximum_observed_source_gap_s'], stamp-gate.last)
                    passed = gate.update(stamp, valid)
                    evidence['last_source_stamp'] = stamp
                    if gate.started is not None:
                        evidence['longest_source_duration_s'] = max(
                            evidence['longest_source_duration_s'], stamp-gate.started)
                    if passed:
                        evidence['outcome'] = 'passed'
                        return raw
                    time.sleep(.01)
                evidence['outcome'] = 'timed_out'
                raise RuntimeError('未取得连续物理确认')
            finally:
                evidence['elapsed_wall_s'] = time.monotonic()-started
                with self.lock:
                    self.task['physical_wait'] = evidence
                    if evidence['outcome'] != 'passed':
                        self.task.setdefault('physical_wait_failure', evidence)

        def wait_future(self, future, timeout, *, carrying=False, station_localization=False,
                        allow_outside_station=False,docking_guard=False):
            end = time.monotonic()+timeout
            tripped_since=None
            while True:
                raw=self.check(carrying=carrying)
                if future.done():
                    return future.result()
                if docking_guard:
                    if not self.guard_acknowledged(raw):
                        raise RuntimeError('原生停靠期间执行端保护失效')
                    if raw['docking_guard']['tripped']:
                        if tripped_since is None:tripped_since=time.monotonic()
                        elif time.monotonic()-tripped_since>2.:
                            raise RuntimeError('已在停靠平面前停车，但未获原生停靠成功确认')
                if station_localization:
                    self.update_station_localization(optional=allow_outside_station)
                if time.monotonic()>end:
                    raise RuntimeError('原生Nav2动作回执超时')
                time.sleep(.02)

        def station_identity(self):
            raw = self.fresh()
            if self.perception_config['mode'] != 'vision':
                source = raw.get('dock_beacon', {})
                expected = {'mode': self.perception_config['mode'],
                            'idealized_truth_derived': True,
                            'scene_sha256': scene_sha, 'manifest_sha256': manifest_sha,
                            'episode_id': self.episode_id}
                if any(type(source.get(key)) is not type(value) or source.get(key) != value
                       for key, value in expected.items()):
                    raise RuntimeError('物理工位传感器来源与当前观测合同不一致')
            return {'scene_sha256': scene_sha, 'manifest_sha256': manifest_sha,
                    'episode_id': self.episode_id,
                    'reset_stamp': raw.get('episode_reset', {}).get('stamp', 0.)}

        def station_publishers(self, context=None):
            context = context or self.timing_context(getattr(self, 'raw', None))
            for topic in ('/cooperation/station_pose', '/cooperation/station_detection'):
                publishers = self.timing_measure('station_publisher_query', self.get_publishers_info_by_topic,
                    topic, context=dict(context, topic=topic))
                if len(publishers) != 1 or publishers[0].node_name != self.perception_config['publisher']:
                    raise ValueError('工位观测必须来自配置的本域唯一传感器')
            publishers = self.timing_measure('station_publisher_query', self.get_publishers_info_by_topic,
                '/detected_dock_pose', context=dict(context, topic='/detected_dock_pose'))
            if len(publishers) != 1 or publishers[0].node_name != self.get_name():
                raise ValueError('原生停靠位姿必须由本桥唯一转发')

        def publish_station_admission(self, outcome, observation=None):
            if not hasattr(self, 'admission_pub'):
                return
            values = observation or {}
            event = DiagnosticArray()
            event.header.stamp = self.get_clock().now().to_msg()
            event.header.frame_id = 'base_footprint'
            status = DiagnosticStatus()
            status.name, status.hardware_id = 'station_admission', self.perception_config['station_id']
            status.level = DiagnosticStatus.OK if outcome == 'accepted' else DiagnosticStatus.WARN
            status.message = outcome
            metadata = {'schema': 1, 'outcome': outcome, 'reason': self.station_rejection,
                        'scene_sha256': scene_sha, 'manifest_sha256': manifest_sha,
                        'episode_id': self.episode_id, 'input_episode_id': values.get('episode_id'),
                        'input_sequence': values.get('sequence'), 'input_stamp': values.get('stamp'),
                        'input_frame_id': values.get('frame_id'), 'input_detected': values.get('detected'),
                        'received_wall_time': time.time(), 'received_monotonic': time.monotonic(),
                        'task_id': self.task.get('id'), 'native_consumption_ack': False}
            status.values = [KeyValue(key=key, value=json.dumps(value, allow_nan=False)) for key, value in metadata.items()]
            event.status = [status]
            self.timing_measure('station_admission_publish', self.admission_pub.publish,
                event, context=self.timing_context(values))

        def reject_station_observation(self, error, observation=None):
            # A late rejected packet cannot erase a newer accepted observation.
            self.station_counts['rejected'] += 1
            self.station_rejection = str(error)
            reasons = self.station_rejection_reason_counts
            reasons[self.station_rejection] = reasons.get(self.station_rejection, 0)+1
            self.publish_station_admission('rejected', observation)

        def admit_station_observation(self, observation):
            self.station_publishers(self.timing_context(observation))
            admitted = validate_observation(observation, self.perception_config,
                self.station_identity(), self.get_clock().now().nanoseconds*1e-9,
                0., self.station_last_seen)
            self.station_last_seen = admitted
            self.station_detection = (admitted, time.monotonic())
            self.station_rejection = None
            return admitted

        def observe_station_detection(self, diagnostics):
            # A lost detection has no pose to synchronize. Preserve the last
            # valid pose's original time; never republish or restamp that pose.
            if len(diagnostics.status) == 1 and diagnostics.status[0].level in (0, b'\x00'):
                return
            started = time.monotonic()
            context = self.station_timing_context(diagnostics)
            try:
                waiting_at = time.monotonic()
                with self.lock:
                    self.timing_record('station_lock_wait', waiting_at, context)
                    observation = None
                    try:
                        observation = self.timing_measure('station_parse', messages_to_observation,
                            None, diagnostics, context=context)
                        admitted = self.timing_measure('station_admission', self.admit_station_observation,
                            observation, context=context)
                        if admitted['detected']:
                            raise ValueError('失检诊断不能携带有效检测')
                        self.station_counts['unavailable'] += 1
                        self.publish_station_admission('unavailable', admitted)
                    except (RuntimeError, ValueError, KeyError, TypeError, AttributeError) as error:
                        self.reject_station_observation(error, observation)
            finally:
                self.timing_record('station_detection', started, context)

        def observe_station_pair(self, pose, diagnostics):
            started = time.monotonic()
            context = self.station_timing_context(diagnostics)
            try:
                waiting_at = time.monotonic()
                with self.lock:
                    self.timing_record('station_lock_wait', waiting_at, context)
                    observation = None
                    try:
                        observation = self.timing_measure('station_parse', messages_to_observation,
                            pose, diagnostics, context=context)
                        admitted = self.timing_measure('station_admission', self.admit_station_observation,
                            observation, context=context)
                        if not admitted['detected']:
                            raise ValueError('失检不能产生停靠位姿')
                        # Only admitted, fresh, same-episode observations reach Nav2.
                        message = PoseStamped()
                        message.header = copy.deepcopy(pose.header)
                        message.pose = copy.deepcopy(pose.pose.pose)
                        self.timing_measure('station_pose_publish', self.dock_pose_pub.publish,
                            message, context=context)
                        self.beacon = (admitted, time.monotonic(), copy.deepcopy(pose.header.stamp))
                        self.station_counts['accepted'] += 1
                        self.station_counts['forwarded'] += 1
                        self.publish_station_admission('accepted', admitted)
                    except (RuntimeError, ValueError, KeyError, TypeError, AttributeError) as error:
                        self.reject_station_observation(error, observation)
            finally:
                self.timing_record('station_pair', started, context)

        def observe_vision_quality(self, message):
            if self.perception_config['mode'] != 'vision':
                return
            try:
                publishers = self.get_publishers_info_by_topic('/cooperation/vision_quality')
                if len(publishers) != 1 or publishers[0].node_name != self.perception_config['publisher']:
                    raise ValueError('视觉诊断发布者不匹配')
                if len(message.status) != 1:
                    raise ValueError('视觉诊断数量无效')
                pairs = message.status[0].values
                values = {item.key: json.loads(item.value) for item in pairs}
                with self.lock:
                    if len(values) != len(pairs) or any(values.get(key) != value for key, value in
                            (('scene_sha256', scene_sha), ('manifest_sha256', manifest_sha), ('episode_id', self.episode_id))):
                        raise ValueError('视觉诊断来源或回合不匹配')
                    self.vision_quality = values
            except (ValueError, TypeError, AttributeError) as error:
                self.get_logger().warning(f'视觉诊断已拒绝：{error}')

        def update_station_localization(self,*,force=False,optional=False):
            """Use an admitted sensor observation, only under this task's ownership.

            Ideal/perturbed simulation and vision retain distinct provenance.
            This transform never substitutes physics qpos for a detection.
            """
            with self.lock:
                self.owner()
                identity = self.station_identity()
                try:
                    self.station_publishers()
                except ValueError as error:
                    raise RuntimeError(str(error)) from error
                if self.station_detection is not None:
                    latest, detected_at = self.station_detection
                    # An expired loss flag cannot indefinitely suppress a newer
                    # sensor epoch; it retains the same original freshness limit.
                    if (not latest['detected'] and latest['reason'] == 'out_of_range'
                            and time.monotonic()-detected_at <= .5
                            and -.1 <= self.get_clock().now().nanoseconds*1e-9-latest['stamp'] <= .25):
                        if optional:return None
                        raise RuntimeError('工位观测超出1米有效范围')
                if self.beacon is None:
                    if optional:return None
                    raise RuntimeError(self.station_rejection or '尚未收到有效工位相对观测')
                measured, received, source_stamp = self.beacon
                stamp = measured['stamp']
                now=self.get_clock().now().nanoseconds*1e-9
                receive_age = time.monotonic()-received
                if receive_age>.5 or not -.1<=now-stamp<=.25:
                    if optional:return None
                    self.task['station_freshness_failure'] = {
                        'clock_stamp_s': now, 'observation_stamp_s': stamp,
                        'source_age_s': now-stamp, 'received_age_s': receive_age,
                        'sequence': measured.get('sequence'),
                        'source_age_limits_s': [-.1, .25], 'receive_age_limit_s': .5}
                    raise RuntimeError('工位相对观测已过期')
                try:
                    validate_observation(measured, self.perception_config, identity, now,
                                         time.monotonic()-received)
                except ValueError as error:
                    raise RuntimeError(f'工位观测来源或内容无效：{error}') from error
                relative=measured['relative']
                pose=station_robot_pose(relative,manifest['native_dock_pose'])
                if self.perception_config['mode'] == 'vision':
                    # AMCL owns map localization. RGB supplies the native dock
                    # target; uncertain distant PnP must not reset that filter.
                    return pose
                if not force and stamp-self.last_station_pose_stamp<.3:
                    return pose
                message=PoseWithCovarianceStamped()
                message.header.frame_id='map';message.header.stamp=copy.deepcopy(source_stamp)
                message.pose.pose.position.x,message.pose.pose.position.y=pose['x'],pose['y']
                message.pose.pose.orientation.z=math.sin(pose['yaw']/2)
                message.pose.pose.orientation.w=math.cos(pose['yaw']/2)
                if self.perception_config['mode'] == 'ideal':
                    for index in (0,7,35):message.pose.covariance[index]=.0001
                else:
                    message.pose.covariance=list(map_covariance(relative,manifest['native_dock_pose'],
                                                               measured['covariance']))
                self.pose_pub.publish(message)
                self.last_station_pose_stamp=stamp
                return pose

        def align_station_map(self):
            raw=self.check()
            if not stopped(raw):raise RuntimeError('校准工位定位前车辆必须停稳')
            if self.perception_config['mode'] == 'vision':
                def captured(value):
                    self.update_station_localization()
                    return stopped(value)
                self.wait_condition(captured,duration=.4,timeout=5.)
                return
            pose=self.update_station_localization(force=True)
            def aligned(value):
                estimate=self.localized()
                return (stopped(value) and math.hypot(estimate['x']-pose['x'],estimate['y']-pose['y'])<.025
                    and abs(math.atan2(math.sin(estimate['yaw']-pose['yaw']),math.cos(estimate['yaw']-pose['yaw'])))<.025)
            self.wait_condition(aligned,duration=.4,timeout=5.)

        def station_capture_ready(self):
            raw=self.check()
            if not stopped(raw):return False
            measured=self.update_station_localization(optional=True)
            return measured is not None and within_station_capture(measured,manifest['dock_pose'])

        def received_goal(self, dispatch, future):
            with self.lock:
                if dispatch['received']:
                    return
                try:
                    handle = future.result()
                    dispatch['handle'] = handle
                    if handle and handle.accepted:
                        dispatch['result'] = handle.get_result_async()
                    dispatch['received'] = True
                    if (dispatch['aborted'] or dispatch['token'] != self.execution_token
                            or self.cancel_event.is_set() or self.abort_event.is_set()):
                        dispatch['aborted'] = True
                        self.cancel_dispatch(dispatch)
                except Exception as error:
                    dispatch['received'] = True
                    dispatch['error'] = str(error)
                    dispatch['aborted'] = True
                    self.cancel_dispatch(dispatch)

        def cleanup(self, token, timeout=6.):
            try:
                return self.cleanup_evidence(token, timeout)
            except Exception as error:
                self.cleanup_summary.update(state='unknown', error=str(error), finished_wall_time=time.time())
                raise

        def wait_loaded_parameter(self, future, token, deadline, *, cleanup=False):
            while True:
                with self.lock:
                    self.owner(token, allow_abort=cleanup)
                raw = self.fresh() if cleanup else self.check(carrying=True)
                if raw['car_hold'] is not True or not stopped(raw):
                    raise RuntimeError('仅在原任务 hold 且停稳时切换载货参数')
                if future.done():
                    return
                if time.monotonic() >= deadline:
                    raise RuntimeError('载货参数服务回执未知，保留原请求且不自动重发')
                time.sleep(.01)

        def loaded_parameter_evidence(self):
            with self.lock:
                changed = False
                for attribute, field in (('loaded_limits', 'loaded_velocity_smoother'),
                                         ('loaded_controller', 'loaded_controller')):
                    current = getattr(self, attribute, None)
                    if current is not None:
                        self.task[field] = current.snapshot()
                        changed = True
                if changed:
                    self.persist()

        def apply_loaded_parameters(self, token):
            adapters = [current for attribute in ('loaded_limits', 'loaded_controller')
                        if (current := getattr(self, attribute, None)) is not None]
            if not adapters:
                return
            self.hold(True, token)
            deadline = min(self.wall_deadline, time.monotonic()+3.)
            try:
                for current in adapters:
                    current.apply(lambda future: self.wait_loaded_parameter(future, token, deadline))
            finally:
                self.loaded_parameter_evidence()

        def cleanup_evidence(self, token, timeout=6.):
            gate = ContinuousEvidence(.7)
            end = time.monotonic()+timeout
            disabled_at = None
            self.cleanup_summary = {'state': 'running', 'native_terminal': False, 'quiet': False,
                                    'hold': False, 'guard_disabled': False, 'started_wall_time': time.time()}
            while time.monotonic()<end:
                with self.lock:
                    self.owner(token, allow_abort=True)
                    dispatches = [item for item in self.dispatches if item['token'] == token]
                    for dispatch in dispatches:
                        self.cancel_dispatch(dispatch)
                    native_terminal = all(dispatch_terminal(item) for item in dispatches)
                try:
                    raw = self.fresh()
                except (RuntimeError, ValueError) as error:
                    # A transient invalid sample cannot prove quiet, but it
                    # need not abandon the original bounded cleanup attempt.
                    self.cleanup_summary['last_invalid_feedback'] = str(error)
                    gate = ContinuousEvidence(.7)
                    time.sleep(.01)
                    continue
                quiet = gate.update(raw['stamp'], physical_quiet(raw) and self.business_quiet(raw))
                self.cleanup_summary.update(native_terminal=native_terminal, quiet=quiet,
                    hold=raw['car_hold'] is True, source_stamp=raw['stamp'])
                if quiet and native_terminal and raw['car_hold'] is True:
                    enabled=self.guard_acknowledged(raw)
                    tripped=raw['docking_guard']['tripped']
                    if disabled_at is None and (self.dock_guard_active or enabled or tripped):
                        disabled_at = raw['stamp']
                        self.set_docking_guard(False,token,allow_abort=True)
                    if not enabled and not tripped and (disabled_at is None or raw['stamp'] > disabled_at):
                        parameter_errors = []
                        for attribute, field in (('loaded_controller', 'loaded_controller'),
                                                 ('loaded_limits', 'loaded_velocity_smoother')):
                            current = getattr(self, attribute, None)
                            if current is None:
                                continue
                            try:
                                current.restore(lambda future: self.wait_loaded_parameter(
                                    future, token, end, cleanup=True))
                            except Exception as error:
                                parameter_errors.append(f'{field}: {error}')
                            finally:
                                self.loaded_parameter_evidence()
                                self.cleanup_summary[field] = current.snapshot()
                        if parameter_errors:
                            self.cleanup_summary.update(state='unknown', error='; '.join(parameter_errors))
                            return False
                        self.cleanup_summary.update(state='verified', guard_disabled=True, finished_wall_time=time.time())
                        return True
                time.sleep(.01)
            self.cleanup_summary.update(state='unknown', finished_wall_time=time.time())
            return False

        def navigate(self, goal, *, carrying=False, station_localization=False, staging=False,
                     deadline=None, route_leg_index=None):
            request = NavigateToPose.Goal()
            request.pose = PoseStamped()
            request.pose.header.frame_id = 'map'
            request.pose.header.stamp = self.get_clock().now().to_msg()
            request.pose.pose.position.x, request.pose.pose.position.y = goal['x'], goal['y']
            request.pose.pose.orientation.z, request.pose.pose.orientation.w = math.sin(goal['yaw']/2), math.cos(goal['yaw']/2)
            request.behavior_tree = (manifest.get('staging_navigation_behavior_tree') or '') if staging and not carrying else ''
            return self.dispatch_goal(self.nav,request,carrying=carrying,label='Nav2',timeout=120,
                station_localization=station_localization,allow_outside_station=station_localization,
                goal_pose=copy.deepcopy(goal),goal_behavior_tree=request.behavior_tree,
                deadline=deadline,route_leg_index=route_leg_index)

        def delivery_route(self):
            """Keep one navigation deadline after, never instead of, required egress."""
            token = self.owner()
            started = time.monotonic()
            deadline = started+DELIVERY_ROUTE_WALL_S
            goals = copy.deepcopy(self.task.get('delivery_approach_poses', []))
            goals.append(copy.deepcopy(self.task.get('delivery_pose', self.stations()['delivery'])))
            with self.lock:
                self.owner(token)
                self.delivery_route_started_monotonic = started
                route = {'budget_wall_s': DELIVERY_ROUTE_WALL_S, 'clock': 'monotonic_wall',
                         'boundary': 'after_required_egress_through_final_nav_stop_and_hold',
                         'started_wall_time': time.time(), 'finished_wall_time': None,
                         'elapsed_wall_s': 0., 'remaining_wall_s': DELIVERY_ROUTE_WALL_S,
                         'status': 'running', 'goals': goals,
                         'completed_legs': 0, 'active_leg_index': None, 'active_leg_kind': None}
                self.task['delivery_route'] = route
            try:
                for index, goal in enumerate(goals):
                    with self.lock:
                        self.owner(token)
                        route.update(active_leg_index=index,
                                     active_leg_kind='approach' if index < len(goals)-1 else 'delivery')
                    if time.monotonic() >= deadline:
                        raise RuntimeError('配送导航共用120秒预算已耗尽，未派发下一段')
                    self.navigate(goal, carrying=True, deadline=deadline, route_leg_index=index)
                    with self.lock:
                        self.owner(token)
                        route['completed_legs'] = index+1
                    if time.monotonic() > deadline:
                        raise RuntimeError('配送导航共用120秒预算已耗尽')
                route.update(status='succeeded', active_leg_index=None, active_leg_kind=None)
            except Exception as error:
                route.update(status='failed', error=str(error))
                raise
            finally:
                with self.lock:
                    route.update(elapsed_wall_s=time.monotonic()-started, finished_wall_time=time.time())
                    route['within_budget'] = route['elapsed_wall_s'] <= DELIVERY_ROUTE_WALL_S
                    route['remaining_wall_s'] = max(0., DELIVERY_ROUTE_WALL_S-route['elapsed_wall_s'])

        def dock_at_station(self):
            request = DockRobot.Goal()
            request.use_dock_id = True
            request.dock_id = manifest['native_docking']['dock_id']
            # Staging is our separate registered NavigateToPose. There is no
            # hidden navigation child inside the docking action to reconcile.
            request.navigate_to_staging_pose = False
            request.max_staging_time = 30.
            return self.dispatch_goal(self.docking,request,label='Nav2停靠',timeout=60,
                station_localization=True,docking_guard=True)

        def drive_egress(self, motion):
            request = DriveOnHeading.Goal()
            request.target.x = motion['distance_m']
            request.target.y = request.target.z = 0.
            request.speed = motion['speed_m_s']
            total_ns = round(motion['time_allowance_s']*1e9)
            request.time_allowance.sec, request.time_allowance.nanosec = divmod(total_ns, 1000000000)
            body_goal = {'target': {'x': request.target.x, 'y': request.target.y, 'z': request.target.z},
                         'speed': request.speed, 'time_allowance': {
                             'sec': request.time_allowance.sec, 'nanosec': request.time_allowance.nanosec}}
            return self.dispatch_goal(self.egress_client, request, carrying=True,
                label='DriveOnHeading', timeout=120, goal_motion=body_goal)

        def dispatch_goal(self,client,request,*,carrying=False,label,timeout,station_localization=False,
                          allow_outside_station=False,docking_guard=False,goal_pose=None,goal_motion=None,
                          goal_behavior_tree=None,deadline=None,route_leg_index=None):
            token = self.owner()
            def remaining(maximum):
                if deadline is None:
                    return maximum
                value = min(maximum, deadline-time.monotonic())
                if value <= 0:
                    raise RuntimeError('配送导航共用120秒预算已耗尽')
                return value
            remaining(timeout)
            self.hold(True, token)
            try:
                with self.lock:
                    self.owner(token)
                    self.dispatch_epoch += 1
                    dispatch = {'token': token, 'epoch': self.dispatch_epoch, 'label': label, 'request': None, 'handle': None,
                                'result': None, 'cancel': None, 'received': False, 'aborted': False, 'error': None,
                                'carrying': bool(carrying), 'goal_pose': copy.deepcopy(goal_pose),
                                'goal_motion': copy.deepcopy(goal_motion), 'goal_behavior_tree':goal_behavior_tree,
                                'route_leg_index': route_leg_index,
                                'sent_wall_time': time.time()}
                    self.dispatches.append(dispatch)
                    sent = client.send_goal_async(request)
                    dispatch['request'] = sent
                    sent.add_done_callback(lambda future: self.received_goal(dispatch, future))
                handle = self.wait_future(sent, remaining(8), carrying=carrying)
                self.received_goal(dispatch, sent)
                with self.lock:
                    self.owner(token)
                    if not handle or not handle.accepted:
                        raise RuntimeError(f'{label}拒绝目标')
                    if dispatch['error'] or dispatch['result'] is None:
                        raise RuntimeError('原生Nav2结果回执未知')
                if docking_guard:
                    self.set_docking_guard(True,token)
                    self.wait_condition(self.guard_acknowledged,duration=.02,timeout=2.)
                    if hasattr(self, 'fault_trigger_pub'):
                        goal_uuid = getattr(getattr(handle, 'goal_id', None), 'uuid', None)
                        if goal_uuid is None:
                            raise RuntimeError('停靠动作缺少原生UUID，不能绑定实验或继续')
                        trigger = {'scene_sha256': scene_sha, 'manifest_sha256': manifest_sha,
                                   'episode_id': self.episode_id, 'native_goal_uuid': bytes(goal_uuid).hex(),
                                   'source_stamp': self.get_clock().now().nanoseconds*1e-9}
                        self.fault_trigger_pub.publish(String(data=json.dumps(trigger)))
                with self.lock:
                    self.owner(token)
                    if not dispatch['result'].done():
                        self.hold(False, token)
                result = self.wait_future(dispatch['result'], remaining(timeout), carrying=carrying,
                    station_localization=station_localization,allow_outside_station=allow_outside_station,
                    docking_guard=docking_guard)
                native = getattr(result, 'result', None)
                if (carrying and result.status == 4 and getattr(native,'success',True) is True
                        and getattr(getattr(self, 'loaded_limits', None), 'phase', None) == 'applied'):
                    # A brief threshold crossing can precede the smoother's
                    # zero command. Do not hard-hold through its braking tail.
                    raw = self.wait_condition(lambda value: self.terminal_stop(dispatch, value),
                                              duration=.7, timeout=remaining(6.), carrying=True)
                    dispatch['stopped_before_hold'] = {'source_stamp': raw['stamp'],
                        'required_continuous_stop_source_s': .7,
                        'linear_speed': raw['car']['speed'], 'angular_speed': raw['car']['yaw_rate'],
                        'car_hold_before': raw['car_hold']}
                self.hold(True, token)
                if result.status != 4 or getattr(native,'success',True) is not True:
                    code = getattr(native, 'error_code', None)
                    message = getattr(native, 'error_msg', '')
                    detail = message.strip() if isinstance(message, str) and message.strip() else 'Nav2未提供具体失败原因'
                    error_code = f'，错误码{code}' if code is not None else '，错误码未提供'
                    raise RuntimeError(f'{label}目标未成功，状态{result.status}{error_code}：{detail}')
                raw=self.wait_condition(lambda value: stopped(value) and value['car_hold'] is True,
                                        carrying=carrying,timeout=remaining(8.))
                remaining(timeout)
                if docking_guard:
                    disabled_at = raw['stamp']
                    self.set_docking_guard(False,token)
                    raw=self.wait_condition(lambda value: value['stamp'] > disabled_at
                        and value['car_hold'] is True and not self.guard_acknowledged(value)
                        and value['docking_guard']['tripped'] is False,duration=.02,timeout=2.)
                return raw
            except Exception as error:
                self.abort(token, error)
                raise

        def segment(self, segment, planner):
            self.check()
            stage = segment['stage']
            points = np.asarray(segment['path'], dtype=float)
            jaw = float(segment['gripper'])
            if points.ndim != 2 or points.shape[1] != 5 or len(points)<1:
                raise RuntimeError('规划轨迹格式无效')
            distance = np.linalg.norm(np.diff(points, axis=0), axis=1)
            cumulative = np.r_[0., np.cumsum(distance)]
            duration = max(float(segment.get('duration_s', 0)), float(cumulative[-1])*1.875/.3)
            dwell = float(segment.get('dwell_s', .6))
            initial = self.check()['stamp']
            source_limit = duration+dwell+20
            while True:
                raw = self.check()
                age = raw['stamp']-initial
                fraction = min(1., max(0., age/max(duration,1e-9)))
                fraction = fraction**3*(10+fraction*(-15+6*fraction))
                if len(points)==1 or cumulative[-1]<1e-10:
                    q = points[-1]
                else:
                    value = fraction*cumulative[-1]
                    i = max(0, min(int(np.searchsorted(cumulative,value,side='right'))-1,len(points)-2))
                    alpha = (value-cumulative[i])/max(cumulative[i+1]-cumulative[i],1e-12)
                    q = points[i]+alpha*(points[i+1]-points[i])
                self.reference(np.r_[q,jaw])
                view = self.task_material(raw)
                if self.task.get('business_delivery') and (not raw['car_hold'] or not stopped(raw)):
                    raise RuntimeError('实体抓放期间车辆未保持停车')
                if not planner.evaluate(view['q6'])['valid']:
                    raise RuntimeError('实际机械臂位姿失去原碰撞余量')
                if age >= duration+dwell and np.max(np.abs(np.asarray(view['q6'])[:5]-points[-1]))<.012 and np.linalg.norm(view['qvel6'][:5])<.05:
                    return raw
                if age > source_limit:
                    errors=np.abs(np.asarray(view['q6'])[:5]-points[-1])
                    joint=int(np.argmax(errors))
                    raise RuntimeError(f'机械臂 {stage} 段未收敛：关节 {manifest["arm_joint_names"][joint]} '
                        f'误差 {errors[joint]:.4f}rad，仿真时间 {age:.2f}/{source_limit:.2f}s')
                time.sleep(.02)

        def execute_route_branch(self, token):
            raw = self.check()
            branch = raw.get('checkpoint_branch') or {}
            if branch.get('level') != 'R2' or branch.get('restored') is not True:
                raise RuntimeError('载货路线切片需要明确恢复的R2实例')
            self.loaded = True
            raw = self.wait_condition(lambda value: transport_handoff_ready(value, manifest['arm_home_qpos6']),
                                      duration=.7, timeout=8., carrying=True)
            start = raw['cargo']['position'][:2]
            self.apply_loaded_parameters(token)
            self.event('car','delivery','R2检查点分支开始载货路线；本回合不执行装货。')
            self.delivery_route()
            raw = self.wait_condition(lambda value: transport_handoff_ready(value, manifest['arm_home_qpos6']),
                                      duration=1., timeout=8., carrying=True)
            if math.hypot(raw['cargo']['position'][0]-start[0],raw['cargo']['position'][1]-start[1])<.5:
                raise RuntimeError('R2载货路线实际位移不足0.5米')
            self.event('car','delivered','R2载货路线结束，货物留盘且车辆停稳。')
            if not self.cleanup(token):
                raise RuntimeError('R2路线清理证据未知')
            with self.lock:
                self.owner(token)
                self.task.update(status='succeeded',message='R2载货路线完成；未执行本回合装货')
                self.persist()

        def capture_delivery_checkpoint(self):
            if not manifest.get('capture_before_delivery'):
                return
            self.wait_condition(self.task_handoff, duration=.7, timeout=8., carrying=True)
            request = self.request_checkpoint({'request_id':str(uuid.uuid4()),
                'context':{'purpose':'loaded_after_egress_before_delivery'}})
            deadline = time.monotonic()+10.
            while time.monotonic()<deadline:
                self.check(carrying=True)
                receipt = self.checkpoint_record(request['request_id'])
                if receipt['status']=='succeeded':
                    with self.lock:
                        self.task['delivery_checkpoint'] = receipt
                        self.persist()
                    return
                if receipt['status']=='failed':
                    raise RuntimeError('出站检查点保存失败：'+receipt.get('message',''))
                time.sleep(.02)
            raise RuntimeError('出站检查点回执未知；保留原请求，不自动重发')

        def unload_ready(self, raw):
            from cooperation_business import shelf_settled
            binding = self.task['business_delivery']
            station = manifest['business_entities']['unload_stations'][binding['unload_station_id']]
            view = self.task_material(raw, arm_id=station['arm_id'])
            home = manifest['business_entities']['arms'][station['arm_id']]['home_qpos6']
            return (shelf_settled(view, manifest, binding['unload_station_id'])
                    and arm_home_quiet(view, home) and self.business_quiet(raw)
                    and not view['cargo_tray_floor_contact'])

        def unload_evidence(self, raw):
            from cooperation_business import placement_slot
            if not self.unload_ready(raw):
                raise RuntimeError('卸货最终物理条件已失效，库存不记为送达')
            binding = self.task['business_delivery']
            return {'cargo_id':binding['cargo_id'], 'unload_station_id':binding['unload_station_id'],
                    'shelf_slot':placement_slot(manifest,binding['unload_station_id'],binding['cargo_id']),
                    'source_stamp':raw['stamp'],'sequence':raw['sequence'],
                    'world_session_id':raw['world_session_id'],'episode_id':raw['episode_id'],
                    'shelf_settled':True,'arm_home_quiet':True,'tray_empty_for_cargo':True}

        def placement_query(self, planner, raw, centers):
            """Keep the current owner responsive while pure IK/OMPL runs."""
            binding = self.task['business_delivery']
            arm_id = self.task.get('active_arm_id', binding['pickup_arm_id'])
            pose = raw['car']['position']+raw['car']['quaternion_wxyz']
            self.check()
            remaining = self.wall_deadline-time.monotonic()
            plan = query_placement(manifest, raw, centers, check=self.check,
                timeout_s=remaining, arm_id=arm_id, cargo_id=binding['cargo_id'], car_pose=pose)
            self.check()
            # The live segment checker must use the same frozen measured scene
            # as the child, not the earlier pre-grasp query model.
            planner.refresh_placement_context(raw, car_pose=pose)
            self.check()
            with self.lock:
                self.owner()
                self.task['arm_placement_planning'] = {
                    'source_stamp': raw['stamp'], 'arm_id': arm_id, 'cargo_id': binding['cargo_id'],
                    'execution': copy.deepcopy(plan['report']['execution'])}
                self.persist()
            return plan

        def execute_unload(self, token):
            """Continue the same owned task/world after its original loaded route."""
            from cooperation_business import shelf_settled, placement_slot
            binding = self.task['business_delivery']
            station_id = binding['unload_station_id']
            station = manifest['business_entities']['unload_stations'][station_id]
            arm_id = station['arm_id']
            self.hold(True, token)
            raw = self.wait_condition(self.task_handoff, duration=1., timeout=8., carrying=True)
            budgets = self.task['business_budgets_wall_s']
            self.wall_deadline = min(self.task_started_monotonic+sum(budgets.values()),
                                     time.monotonic()+budgets['unload'])
            self.loaded = False
            with self.lock:
                self.owner(token)
                self.task['active_arm_id'] = arm_id
                self.last_ref = list(self.task_material(raw)['q6'])
            pose = raw['car']['position']+raw['car']['quaternion_wxyz']
            options = {'arm_id': arm_id, 'cargo_id': binding['cargo_id'], 'snapshot': raw}
            planner = ArmPlanner(manifest, car_pose=pose, **options)
            baseline = self.task_material(raw)['cargo']['position'][2]
            self.event('arm','unload_grasp','卸货臂按当前货物身份从托盘抓取。')
            plan = query_approach(manifest, self.task_material(raw)['q6'], pose,
                check=self.check, timeout_s=min(30., max(.001,self.wall_deadline-time.monotonic())), **options)
            for segment in plan['segments']:
                self.segment(segment, planner)
            self.wait_condition(lambda value: self.task_material(value)['cargo']['position'][2]-baseline>=.025
                and min(tip_forces(self.task_material(value)))>.02, duration=1., timeout=5.)
            shelf = placement_slot(manifest,station_id,binding['cargo_id'])['center_xy_m']
            centers = station.get('placement_centers_m', [[.18,.14,.06],[.18,0.,.06],
                [.18,-.13,.06],[*shelf,.06],[*shelf,.023]])
            transfer = self.placement_query(planner, self.check(), centers)
            self.check()
            self.event('arm','unload_transport','保持实际双指夹持，搬运到当前货架。')
            for segment in transfer['segments']:
                if segment['stage']=='retreat':
                    self.wait_condition(lambda value: shelf_settled(self.task_material(value),manifest,station_id,before_retreat=True)
                        and self.task_material(value)['q6'][5]>.45, duration=1., timeout=8.)
                self.segment(segment, planner)
            raw = self.wait_condition(self.unload_ready, duration=1., timeout=8.)
            receipt = self.unload_evidence(raw)
            with self.lock:
                self.owner(token)
                self.task['unload_receipt'] = receipt
            self.event('arm','unloaded','同一货物已在货架落稳，卸货臂已回位；等待原任务清理。')
            return receipt

        def execute(self, token):
            self.worker.token = token
            try:
                scope = self.task.get('scope', 'transport')
                self.task_started_monotonic = time.monotonic()
                self.wall_deadline = self.task_started_monotonic+(60 if scope == 'dock' else 360)
                if scope == 'route':
                    self.execute_route_branch(token)
                    return
                self.event('car','docking','前往 SO101 工位，请等待停靠。')
                if self.perception_config['mode'] == 'vision':
                    # The original staging view avoids the arm's oblique
                    # occlusion. Approach uses AMCL; RGB drives the dock leg.
                    self.navigate(self.stations()['staging'],station_localization=False,staging=True)
                elif self.station_capture_ready():
                    self.event('car','docking','已在工位停靠捕获区，继续对准原生停靠。')
                else:
                    self.navigate(self.stations()['staging'],station_localization=True,staging=True)
                self.align_station_map()
                sensor_label = 'AprilTag RGB 观测' if self.perception_config['mode'] == 'vision' else '相对工位观测'
                self.event('car','docking',f'已到工位附近，使用{sensor_label}进行原生近距离精停靠。')
                raw = self.dock_at_station()
                self.hold(True)
                pose = car_pose(raw)
                dock = self.stations()['dock']
                if math.hypot(pose['x']-dock['x'],pose['y']-dock['y'])>.04 or abs(math.atan2(math.sin(pose['yaw']),math.cos(pose['yaw'])))>.05:
                    raise RuntimeError('车体尚未进入真实交接位置与朝向范围')
                docked_message = '已到工位并停稳。' if scope == 'dock' else '已到工位并停稳，请 SO101 装货。'
                self.event('car','docked',docked_message)
                if scope == 'dock':
                    if not self.cleanup(token):
                        raise RuntimeError('停靠完成但清理证据未知')
                    self.event('system','succeeded','停靠与停稳验证完成；本回合未执行装货运输。',terminal=True)
                    with self.lock:
                        self.owner(token)
                        self.task.update(status='succeeded', message='停靠完成')
                        self.persist()
                    return
                binding = self.task.get('business_delivery')
                options = ({'arm_id':binding['pickup_arm_id'],'cargo_id':binding['cargo_id'],'snapshot':raw}
                           if binding else {})
                pose = raw['car']['position']+raw['car']['quaternion_wxyz']
                planner = ArmPlanner(manifest, car_pose=pose, **options)
                plan = query_approach(manifest, self.task_material(raw)['q6'], pose,
                    check=self.check, timeout_s=min(30., max(.001, self.wall_deadline-time.monotonic())), **options)
                self.check()
                # Retain small planning evidence once per task. Full trajectories
                # remain local planning data, not repeated telemetry payloads.
                with self.lock:
                    self.owner(token)
                    self.task['arm_planning'] = {
                        'phase': 'approach', 'source_stamp': raw['stamp'],
                        'planner': plan['planning'].get('planner'),
                        'requested_seed': plan['planning'].get('requested_seed'),
                        'rng_seed_scope': plan['planning'].get('rng_seed_scope'),
                        'path_sha256': hashlib.sha256(json.dumps(plan['planning']['path'],
                            separators=(',', ':'), allow_nan=False).encode()).hexdigest(),
                        'execution': plan['planning']['execution'],
                    }
                baseline = self.task_material(raw)['cargo']['position'][2]
                for segment in plan['segments']:
                    self.event('arm',segment['stage'], {'approach':'正在靠近取货位置。','descend':'正在下降到夹取位置。',
                        'close':'正在闭合夹爪，等待接触反馈。','lift':'正在抬升货物。'}.get(segment['stage'],'正在执行已验证的机械臂轨迹。'))
                    raw = self.segment(segment, planner)
                self.wait_condition(lambda value: self.task_material(value)['cargo']['position'][2]-baseline>=.025 and min(tip_forces(self.task_material(value)))>.02,
                                    duration=1., timeout=5.)
                self.event('arm','holding','双指接触与抬升已确认，正在保持货物。')
                raw = self.check()
                transport = (self.placement_query(planner, raw, [[.18,-.13,.06],[.18,0.,.06],
                    [.18,.14,.06],[.24,.14,.06],[.24,.14,.023]])
                    if binding else planner.prepare_transport(raw))
                self.check()
                released=False
                for segment in transport['segments']:
                    if segment['stage']=='retreat':
                        raw=self.wait_condition(lambda value:release_ready_for_retreat(self.task_material(value)),duration=1.,timeout=6.)
                        released=True
                        self.event('arm','retreat','托盘已接住货物、活动指已张开，正在退出固定指。')
                    else:
                        message={'transport':'正在把货物放入车载托盘。','lower':'正在下降到托盘。',
                            'release':'正在松开夹爪，等待货物落稳。','settle':'正在确认机械臂回位。'}[segment['stage']]
                        self.event('arm',segment['stage'],message)
                    self.segment(segment,planner)
                if not released:raise RuntimeError('规划缺少真实松爪与退出阶段')
                self.wait_condition(self.task_handoff,
                                    duration=1., timeout=8.)
                if binding:
                    from cooperation_business import advance
                    with self.lock:
                        self.owner(token)
                        advance(self.business_inventory,binding['cargo_id'],token[0],'on_tray',
                                {'source_stamp':self.check()['stamp'],'stage':'loaded'})
                self.event('arm','loaded','货物已放稳，机械臂已退出，可以运输。')
                self.loaded = True
                raw = self.check(carrying=True)
                start = self.task_material(raw)['cargo']['position'][:2]
                self.apply_loaded_parameters(token)
                if self.task.get('egress_motion') is not None:
                    self.event('car','delivery','收到交接确认，沿当前车体方向直行出站，再前往交付点。')
                    self.drive_egress(copy.deepcopy(self.task['egress_motion']))
                elif self.task.get('egress_pose') is not None:
                    self.event('car','delivery','收到交接确认，先驶出工位，再前往交付点。')
                    self.navigate(copy.deepcopy(self.task['egress_pose']),carrying=True)
                self.capture_delivery_checkpoint()
                self.event('car','delivery','收到交接确认，驶往交付点。')
                self.delivery_route()
                raw = self.wait_condition(self.task_handoff,
                                          duration=1., timeout=8., carrying=True)
                carried = self.task_material(raw)['cargo']['position']
                if math.hypot(carried[0]-start[0],carried[1]-start[1])<.5:
                    raise RuntimeError('货物实际运输位移不足0.5米')
                self.event('car','delivered','已到交付点，货物仍在托盘，车辆与货物已停稳。')
                receipt = self.execute_unload(token) if binding else None
                if not self.cleanup(token):
                    raise RuntimeError('运输完成但清理证据未知')
                if binding:
                    # Cleanup may have changed the physical shelf/home state.
                    # Only new source frames can confirm the inventory commit.
                    previous_stamp = receipt['source_stamp']
                    raw = self.wait_condition(lambda value: value['stamp']>previous_stamp
                        and self.unload_ready(value), duration=.7, timeout=8.)
                    receipt = self.unload_evidence(raw)
                    receipt['after_cleanup'] = True
                with self.lock:
                    self.owner(token)
                    if binding:
                        self.task['unload_receipt'] = receipt
                        advance(self.business_inventory,binding['cargo_id'],token[0],'delivered',receipt)
                    self.task.update(status='succeeded',message='装货、运输与实体卸货完成' if binding else '装货运输完成')
                    self.persist()
            except Exception as error:
                if token != self.execution_token:
                    return
                self.abort(token, error)
                binding = self.task.get('business_delivery')
                if binding:
                    from cooperation_business import advance
                    with self.lock:
                        try:
                            advance(self.business_inventory,binding['cargo_id'],token[0],'unknown',
                                    {'reason':str(error),'stage':self.task.get('stage')})
                        except (Rejected,ValueError,KeyError) as inventory_error:
                            self.task['inventory_error'] = str(inventory_error)
                terminal = 'canceled' if isinstance(error,Canceled) else 'failed'
                try:
                    if not self.cleanup(token):
                        terminal='unknown'
                except Exception:
                    terminal='unknown'
                self.event('system',terminal,str(error),terminal=True)
                with self.lock:
                    self.owner(token, allow_abort=True)
                    self.task.update(status=terminal,stop_reason=str(error))
                    self.persist()

        def archive_current(self):
            if not self.task.get('id') or self.task['status'] in ACTIVE:
                return
            if any(item['task'].get('id') == self.task['id'] for item in self.history):
                return
            record = {'episode_id': self.episode_id, 'task': copy.deepcopy(self.task),
                      'events': copy.deepcopy(self.events), 'native_actions': self.native_action_state(),
                      'completed_at': time.time()}
            path = self.history_dir/(self.task['id']+'.json')
            with path.open('x') as stream:
                json.dump(record, stream, ensure_ascii=False, allow_nan=False, indent=2)
                stream.write('\n')
            self.history.append(record)

        def reset_in_progress(self):
            return any(item['status'] in ('pending', 'unknown') for item in self.reset_records.values())

        def reset_admission(self, raw):
            if not self.episode_id or raw.get('episode_id') != self.episode_id:
                return '等待带回合编号的物理反馈'
            if self.task['status'] in ACTIVE:
                return '任务仍在执行或终态未知，不能重置'
            if self.task_worker is not None and self.task_worker.is_alive():
                return '任务清理尚未结束'
            if self.reset_in_progress():
                return '正在核对原重置请求，请勿重复操作'
            if not all(dispatch_terminal(item) for item in self.dispatches):
                return '原生导航动作尚未确认结束'
            guard = raw.get('docking_guard', {})
            if raw['car_hold'] is not True or guard.get('enabled') is not False:
                return '等待车辆保持停车及停靠保护退出'
            if not self.reset_quiet(raw):
                return '等待车辆、机械臂和货物停稳'
            if not all(client.service_is_ready() for client in self.reset_clearers):
                return '等待原生代价地图服务'
            return None

        def reset_quiet(self, raw):
            velocity = raw['cargo']['velocity_world_angular_linear']
            return (physical_quiet(raw) and self.business_quiet(raw)
                    and math.sqrt(sum(value*value for value in velocity[3:])) < .03)

        def reset_state(self, raw):
            reason = self.reset_admission(raw) if raw is not None else '等待有效物理反馈'
            record = self.reset_records.get(self.last_reset_id)
            last = None if record is None else {
                'request_id': record['request_id'], 'status': record['status'],
                'from_episode': record['episode_id'], 'to_episode': record['new_episode_id'],
                'message': record['message']}
            return {'available': reason is None, 'reason': reason or '可恢复到新合成回合',
                    'pending': self.reset_in_progress(),
                    'last': last}

        def request_checkpoint(self, body):
            """Capture through the existing physics owner; no second HTTP writer."""
            if not isinstance(body, dict):
                raise Rejected('检查点请求必须是JSON对象')
            identity = str(uuid.UUID(body.get('request_id') or str(uuid.uuid4())))
            with self.lock:
                if identity in self.checkpoint_records:
                    return copy.deepcopy(self.checkpoint_records[identity])
                if not manifest.get('checkpoint_directory'):
                    raise Rejected('此实例未配置检查点目录')
                raw = self.fresh()
                context = {'task_id': self.task['id'], 'stage': self.task['stage'],
                    'native_actions': self.native_action_state(), 'source_stamp':raw['stamp'],
                    'localization_source':'parent map->base_footprint TF',
                    'localization_covariance':None,
                    'caller_context':body.get('context', {})}
                if manifest.get('business_entities'):
                    context['business_inventory'] = copy.deepcopy(self.inventory(raw))
                    context['business_delivery'] = copy.deepcopy(self.task.get('business_delivery'))
                try:
                    context['localized_pose'] = self.localized()
                except Exception as error:
                    context['localized_pose'] = None
                    context['localization_missing_reason'] = str(error)
                try:
                    json.dumps(context, allow_nan=False)
                except (ValueError, TypeError):
                    context['caller_context'] = {}
                    self.get_logger().warning('忽略不能序列化的可选检查点注释')
                request = {'request_id':identity, 'episode_id':self.episode_id,
                           'issued_at':time.time(), 'action':'capture', 'context':context}
                self.checkpoint_records[identity] = {**request, 'status':'pending'}
                self.checkpoint_pub.publish(String(data=json.dumps(request,allow_nan=False)))
                return copy.deepcopy(self.checkpoint_records[identity])

        def observe_checkpoint(self, message):
            try:
                value = json.loads(message.data)
                with self.lock:
                    original = self.checkpoint_records.get(value['request_id'])
                    if (original is None or original['episode_id'] != value['episode_id']
                            or value.get('status') not in ('succeeded','failed')):
                        return
                    self.checkpoint_records[value['request_id']] = {**original, **value}
                    while len(self.checkpoint_records)>128:
                        terminal = next((key for key,item in self.checkpoint_records.items()
                                         if item.get('status') in ('succeeded','failed')), None)
                        if terminal is None:break
                        self.checkpoint_records.pop(terminal)
            except (KeyError, ValueError, TypeError) as error:
                self.get_logger().warning('忽略无效检查点回执：'+str(error))

        def checkpoint_record(self, identity):
            with self.lock:
                if identity not in self.checkpoint_records:
                    raise Rejected('未知检查点请求',404)
                return copy.deepcopy(self.checkpoint_records[identity])

        def observe_reset(self, message):
            try:
                value = json.loads(message.data)
                if not isinstance(value, dict) or set(value) != {
                    'request_id', 'episode_id', 'status', 'new_episode_id', 'reset_stamp', 'message'}:
                    raise ValueError('重置执行回执结构无效')
                import uuid
                if (str(uuid.UUID(value['request_id'])) != value['request_id']
                        or str(uuid.UUID(value['episode_id'])) != value['episode_id']
                        or value['status'] not in ('succeeded', 'failed') or not isinstance(value['message'], str)):
                    raise ValueError('重置执行回执身份无效')
                if value['status'] == 'succeeded':
                    if (str(uuid.UUID(value['new_episode_id'])) != value['new_episode_id']
                            or value['new_episode_id'] == value['episode_id']):
                        raise ValueError('重置回执未提供新回合')
                    finite_vector([value['reset_stamp']], 1, '重置源时刻')
                with self.lock:
                    record = self.reset_records.get(value['request_id'])
                    if record is None or record['episode_id'] != value['episode_id']:
                        return
                    existing = self.reset_acks.get(value['request_id'])
                    if existing is not None and existing != value:
                        raise ValueError('同一重置编号收到冲突回执')
                    self.reset_acks[value['request_id']] = value
            except (ValueError, KeyError, TypeError, AttributeError) as error:
                self.get_logger().warning(f'忽略无效重置回执：{error}')

        def reset_episode(self, body):
            # An old duplicate only reads its receipt. It never repeats a reset.
            known = isinstance(body, dict) and body.get('request_id') in self.reset_records
            request_id, episode = reset_request_identity(body, now=body.get('issued_at') if known else None)
            with self.lock:
                if request_id in self.reset_records:
                    record = self.reset_records[request_id]
                    if record['episode_id'] != episode:
                        raise Rejected('重置编号已用于另一回合', 409)
                    return copy.deepcopy(record)
                if episode != self.episode_id:
                    raise Rejected('场景回合已变化，请读取最新状态', 409)
                raw = self.fresh()
                reason = self.reset_admission(raw)
                if reason:
                    raise Rejected(reason, 409)
                self.archive_current()
                record = {'request_id': request_id, 'episode_id': episode, 'status': 'pending',
                          'new_episode_id': None, 'message': '正在确认停稳并重置合成场景'}
                self.reset_records[request_id] = record
                self.last_reset_id = request_id
                self.reset_runtime[request_id] = {'published': False, 'pose_published': False, 'clear_futures': []}
                self.persist()
                self.launch_reset_worker(request_id)
                return copy.deepcopy(record)

        def launch_reset_worker(self, request_id):
            if self.reset_worker is not None and self.reset_worker.is_alive():
                return
            self.reset_worker = threading.Thread(target=self.execute_reset, args=(request_id,),
                                                 daemon=True, name='cooperation-reset')
            self.reset_worker.start()

        def reset_record(self, request_id):
            with self.lock:
                record = self.reset_records.get(request_id)
                if record is None:
                    raise Rejected('未找到该重置编号；未执行或重发重置', 404)
                if record['status'] == 'unknown' and request_id in self.reset_acks:
                    # Reconcile a late ACK without sending the mutation again.
                    self.launch_reset_worker(request_id)
                return copy.deepcopy(record)

        def wait_reset_condition(self, condition, *, duration=.7, timeout=12.):
            gate = ContinuousEvidence(duration)
            end = time.monotonic()+timeout
            while time.monotonic() < end:
                try:
                    raw = self.fresh()
                    if gate.update(raw['stamp'], bool(condition(raw))):
                        return raw
                except (RuntimeError, ValueError, KeyError, TypeError):
                    gate = ContinuousEvidence(duration)
                time.sleep(.02)
            raise RuntimeError('新回合尚未取得连续物理/定位确认')

        def publish_reset_pose(self, raw):
            pose = car_pose(raw)
            message = PoseWithCovarianceStamped()
            message.header.frame_id = 'map'
            message.header.stamp = self.get_clock().now().to_msg()
            message.pose.pose.position.x, message.pose.pose.position.y = pose['x'], pose['y']
            message.pose.pose.orientation.z, message.pose.pose.orientation.w = math.sin(pose['yaw']/2), math.cos(pose['yaw']/2)
            message.pose.covariance[0] = message.pose.covariance[7] = .0025
            message.pose.covariance[35] = .0025
            self.pose_pub.publish(message)

        def execute_reset(self, request_id):
            with self.lock:
                record = self.reset_records[request_id]
                runtime = self.reset_runtime[request_id]
            try:
                if not runtime['published']:
                    self.hold(True)
                    self.wait_reset_condition(lambda raw: self.reset_quiet(raw) and raw['car_hold']
                        and not raw['docking_guard']['enabled'])
                    with self.lock:
                        if self.task['status'] in ACTIVE or not all(dispatch_terminal(item) for item in self.dispatches):
                            raise RuntimeError('重置前原动作终态变化，保留原回合')
                        runtime['published'] = True
                        self.reset_pub.publish(String(data=json.dumps({'request_id': request_id,
                            'episode_id': record['episode_id'], 'issued_at': time.time()})))
                end = time.monotonic()+12.
                ack = None
                while time.monotonic() < end:
                    with self.lock:
                        ack = self.reset_acks.get(request_id)
                    if ack is not None: break
                    time.sleep(.02)
                if ack is None:
                    raise RuntimeError('重置执行回执未知，仅核对原编号，不重复重置')
                if ack['status'] == 'failed':
                    with self.lock:
                        record.update(status='failed', message=ack['message'])
                        self.persist()
                    return
                with self.lock:
                    with self.physics_cache_lock:
                        self.episode_id = ack['new_episode_id']
                        self.business_inventory = None
                        self.raw, self.received = None, 0.
                        self.observation_error = None
                    self.execution_token = None
                    self.beacon = None
                    self.station_last_seen = None
                    self.station_detection = None
                    self.station_rejection = None
                    self.vision_quality = None
                    self.last_freshness_failure = None
                    self.cleanup_summary = {'state': 'not_started', 'native_terminal': False,
                                            'quiet': False, 'hold': False, 'guard_disabled': False}
                    self.last_station_pose_stamp = -math.inf
                    record['new_episode_id'] = self.episode_id
                raw = self.wait_reset_condition(lambda raw: raw['episode_id'] == self.episode_id
                    and raw['stamp'] > ack['reset_stamp'] and raw['car_hold'] and self.reset_quiet(raw))
                if not runtime['pose_published']:
                    self.publish_reset_pose(raw)
                    runtime['pose_published'] = True
                def localized_reset(value):
                    measured = self.localized()
                    expected = car_pose(value)
                    angle = math.atan2(math.sin(measured['yaw']-expected['yaw']), math.cos(measured['yaw']-expected['yaw']))
                    return (value['car_hold'] and self.reset_quiet(value)
                        and math.hypot(measured['x']-expected['x'], measured['y']-expected['y']) < .1
                        and abs(angle) < .12)
                self.wait_reset_condition(localized_reset, duration=.3)
                if not runtime['clear_futures']:
                    runtime['clear_futures'] = [client.call_async(ClearEntireCostmap.Request()) for client in self.reset_clearers]
                end = time.monotonic()+8.
                for future in runtime['clear_futures']:
                    while not future.done() and time.monotonic() < end:
                        time.sleep(.02)
                    if not future.done() or future.result() is None:
                        raise RuntimeError('新回合代价地图清理回执未知')
                raw = self.wait_reset_condition(localized_reset, duration=.3)
                with self.lock:
                    self.last_ref = list(raw['arm_reference_q6'])
                    self.loaded = False
                    self.task_epoch += 1
                    self.dispatches = []
                    self.task = {'id': None, 'status': 'idle', 'stage': 'idle', 'message': '新回合已就绪，可以开始装货运输', 'stop_reason': None}
                    self.events = []
                    record.update(status='succeeded', message='场景已重置，新回合已就绪')
                    self.persist()
            except Exception as error:
                with self.lock:
                    record.update(status='unknown' if runtime['published'] else 'failed', message=str(error))
                    self.hold(True)
                    self.persist()

        def stations(self):
            dock=manifest['dock_pose']
            delivery = self.task.get('delivery_pose') if self.task.get('id') else None
            delivery = delivery or task_delivery_pose({}, manifest.get('delivery_pose'))
            return {'dock':dict(zip(('x','y','yaw'),dock)),
                    'staging':dict(zip(('x','y','yaw'),manifest['staging_pose'])),
                    'delivery':copy.deepcopy(delivery)}

        def prepare_delivery_geometry(self):
            with self.delivery_geometry_lock:
                if self.delivery_geometry is not None:
                    return True
                if self.delivery_geometry_error is not None:
                    return False
                try:
                    self.delivery_geometry = SceneGeometry(manifest)
                except (ImportError, OSError, ValueError, KeyError, RuntimeError) as error:
                    self.delivery_geometry_error = str(error)
                    self.get_logger().warning(f'可选交付点几何预检不可用；原默认任务保留：{error}')
                    return False
                return True

        def validate_delivery_goal(self, goal):
            if not self.prepare_delivery_geometry():
                raise Rejected(f'无法核对交付点原始碰撞几何：{self.delivery_geometry_error}', 409)
            try:
                with self.delivery_geometry_lock:
                    result = self.delivery_geometry.check_pose(goal)
            except (ImportError, OSError, ValueError, KeyError, RuntimeError) as error:
                raise Rejected(f'无法核对交付点原始碰撞几何：{error}', 409) from error
            if not result['passed']:
                witness = result.get('witness') or {}
                detail = (f'，车体 {witness.get("car_geom")} 与 {witness.get("external_geom")}'
                          if witness else '')
                raise Rejected(f'交付点 ({goal["x"]:.3f}, {goal["y"]:.3f}) 足迹或场景边界预检未通过：{result["reason"]}{detail}', 409)
            return result

        def native_action_state(self):
            result = []
            for item in self.dispatches:
                handle, future = item.get('handle'), item.get('result')
                goal_id = getattr(getattr(handle, 'goal_id', None), 'uuid', None)
                status = None
                known = False
                if future is not None and future.done():
                    try:
                        reply = future.result()
                        status = getattr(reply, 'status', None)
                        known = status in (4, 5, 6)
                    except Exception:
                        known = False
                result.append({'uuid': bytes(goal_id).hex() if goal_id is not None else None,
                    'label': item.get('label'), 'accepted': bool(handle and handle.accepted),
                    'carrying': bool(item.get('carrying', False)), 'goal_pose': copy.deepcopy(item.get('goal_pose')),
                    'goal_motion': copy.deepcopy(item.get('goal_motion')),
                    'goal_behavior_tree': item.get('goal_behavior_tree'),
                    'route_leg_index': item.get('route_leg_index'),
                    'sent_wall_time': item.get('sent_wall_time'),
                    'stopped_before_hold': copy.deepcopy(item.get('stopped_before_hold')),
                    'terminal_stop_heartbeat': copy.deepcopy(item.get('terminal_stop_heartbeat')),
                    'status': status, 'result_known': known, 'terminal': dispatch_terminal(item),
                    'cancel_requested_wall_time': item.get('cancel_requested_wall_time')})
            return result

        def perception_state(self):
            current = self.station_detection[0] if self.station_detection else None
            received = self.station_detection[1] if self.station_detection else None
            quality = getattr(self, 'vision_quality', None) or {}
            if not current or any(quality.get(key) != current.get(key) for key in ('episode_id','sequence','stamp')):
                quality = {}
            source_age = self.get_clock().now().nanoseconds*1e-9-current['stamp'] if current else None
            reason = self.station_rejection or (current.get('reason') if current else 'waiting_for_observation')
            receive_age = max(0., time.monotonic()-received) if received is not None else None
            detected = bool(current and current['detected'])
            if detected and (receive_age > .5 or not -.1 <= source_age <= .25):
                detected, reason = False, 'observation_expired'
            return {'mode': self.perception_config['mode'], 'publisher': self.perception_config['publisher'],
                    'detected': detected, 'reason': reason, 'confidence': current.get('confidence') if current else None,
                    'stamp': current.get('stamp') if current else None,
                    'received_age_s': receive_age, 'source_age_s': source_age,
                    'counts': dict(self.station_counts), 'reprojection_error_px': quality.get('reprojection_error_px')}

        def vision_frame_state(self, raw=None):
            unavailable = {'available': False, 'stamp': None, 'episode_id': self.episode_id or '',
                           'sequence': 0, 'corners': None, 'image_width': 640, 'image_height': 480}
            try:
                raw = self.fresh() if raw is None else raw
                info = json.loads((args.frame_dir/'vision-latest.json').read_text())
                return self.vision_frame_info(info, raw)
            except (OSError, ValueError, KeyError, TypeError, RuntimeError):
                return unavailable

        def vision_frame_info(self, info, raw=None):
            raw = self.fresh() if raw is None else raw
            stamp, wall = finite_vector([info['stamp'], info['wall_time']], 2, '后向相机帧时间')
            sequence = info['sequence']
            if (type(sequence) is not int or sequence < 1
                    or info['scene_sha256'] != scene_sha or info['manifest_sha256'] != manifest_sha
                    or info['episode_id'] != self.episode_id
                    or not 0 <= time.time()-wall <= 3.5 or not -.1 <= raw['stamp']-stamp <= 1.5):
                raise ValueError('后向相机帧来源或时间无效')
            self.vision_frame_image(info)
            corners = info.get('corners')
            if corners is not None:
                if not isinstance(corners, list) or len(corners) != 4:
                    raise ValueError('后向相机角点无效')
                for pair in corners:
                    finite_vector(pair, 2, '标记角点')
            if info['image_width'] != 640 or info['image_height'] != 480:
                raise ValueError('后向相机规格不匹配')
            return {'available': True, 'stamp': stamp, 'episode_id': self.episode_id,
                    'sequence': sequence, 'corners': corners, 'image_width': 640, 'image_height': 480}

        def vision_frame_request(self, query):
            if set(query) != {'stamp','episode_id','sequence'} or any(len(values)!=1 for values in query.values()):
                raise Rejected('后向相机请求必须指定唯一回合、帧编号与源时间',409)
            sequence = int(query['sequence'][0])
            stamp = float(query['stamp'][0])
            if (sequence < 1 or str(sequence) != query['sequence'][0] or not math.isfinite(stamp)
                    or query['episode_id'][0] != self.episode_id):
                raise Rejected('后向相机请求来源或编号不匹配',409)
            path = args.frame_dir/f'vision-{self.episode_id}-{sequence}.json'
            info = json.loads(path.read_text())
            frame = self.vision_frame_info(info)
            if frame['sequence'] != sequence or frame['stamp'] != stamp:
                raise Rejected('后向相机请求源时间与不可变帧不匹配',409)
            return info

        def vision_frame_image(self, info):
            expected = f'vision-{self.episode_id}-{info["sequence"]}.jpg'
            if info.get('episode_id') != self.episode_id or info.get('image_file') != expected:
                raise ValueError('后向相机文件与帧编号不匹配')
            path = args.frame_dir/expected
            if not path.is_file():
                raise ValueError('后向相机帧已更新或缺失')
            return path

        def state(self, *, scope=None):
            scope = scope or ('route' if manifest.get('restore_checkpoint') else 'transport')
            context = self.timing_context(getattr(self, 'raw', None))
            waiting_at = time.monotonic()
            with self.lock:
                self.timing_record('http_lock_wait', waiting_at, context)
                assembled_at = time.monotonic()
                assembly_context = self.timing_context(getattr(self, 'raw', None))
                assembly_context.update(entry_wall_time=context['entry_wall_time'],
                    entry_monotonic=context['entry_monotonic'],
                    bridge_episode_id_at_entry=context['bridge_episode_id_at_entry'])
                ready=False; reason='等待共享物理世界与 Nav2'
                pose=None; raw=None; physics=None; nav_ready=False
                try:
                    raw=self.fresh()
                    if self.perception_config['mode'] == 'vision' and raw.get('camera_error'):
                        raise RuntimeError(f'后向相机渲染失败：{raw["camera_error"]}')
                    cargo=raw['cargo'];velocity=cargo['velocity_world_angular_linear'][3:]
                    physics={'stamp':raw['stamp'],'car':{**car_pose(raw),'linear_speed':raw['car']['speed'],'angular_speed':raw['car']['yaw_rate']},
                        'arm':{'q':raw['q6'],'velocity':raw['qvel6']},'cargo':dict(zip(('x','y','z'),cargo['position']))}
                    physics['cargo'].update(speed=math.sqrt(sum(v*v for v in velocity)),tip_forces=tip_forces(raw),tray_contact=raw['cargo_tray_floor_contact'])
                    pose=self.localized()
                    nav_ready=(self.nav.server_is_ready() and self.docking.server_is_ready()
                               and self.native_readiness.active())
                    ready=nav_ready
                    reason='共享物理世界与 Nav2 已就绪' if ready else '等待原生导航服务'
                    self.station_publishers()
                    station=manifest['station_offset']; target=raw['cargo']['position']
                    if scope == 'route':
                        branch = raw.get('checkpoint_branch') or {}
                        if (not manifest.get('restore_checkpoint') or branch.get('level')!='R2'
                                or branch.get('restored') is not True
                                or branch.get('episode_id')!=raw.get('episode_id')
                                or not transport_handoff_ready(raw, manifest['arm_home_qpos6'])):
                            ready=False;reason='R2分支来源或载货停稳条件尚未就绪'
                        elif self.localization_warmup is not None and not self.localization_warmup.snapshot()['ready']:
                            ready=False;reason='等待R2静止定位预热：'+self.localization_warmup.snapshot()['reason']
                    elif manifest.get('business_entities'):
                        inventory = self.inventory(raw)
                        if not any(item['state']=='available' for item in inventory['cargo'].values()):
                            ready=False;reason='有限货源已耗尽或已被原任务预留，不重置生成库存'
                    elif math.hypot(target[0]-station[0]-.24,target[1]-station[1]+.13)>.035:
                        ready=False; reason='物体已离开取货盘；本回合完成后需重置合成场景'
                    if any(raw[f'{body}_forbidden_contact_{kind}']
                           for body in ('arm','car') for kind in ('count','total')):
                        ready=False;reason='存在非预期物理接触，请查看本回合诊断'
                    if self.task['status'] in ACTIVE: ready=False;reason='当前任务持有车臂控制权'
                    if self.reset_in_progress(): ready=False;reason='正在重置或核对新回合，请等待明确反馈'
                except Exception as error:
                    ready=False;nav_ready=False;reason=str(error)
                frame=self.frame_state(raw)
                result = {'mode':'mujoco','domain':args.domain,'ready':ready,'reason':reason,'task':copy.deepcopy(self.task),
                    'scene_profile':copy.deepcopy(manifest.get('scene_profile')),
                    'vehicle_profile':copy.deepcopy(manifest.get('vehicle_profile')),
                    'events':copy.deepcopy(self.events),'physics':physics,'frame':frame,
                    # Instance identity survives a reset/freshness gap. This is
                    # the XML hashed at startup, not a new physical observation.
                    'source':{'scene_sha':scene_sha,'origin':'manifest_world_xml','observed':raw is not None},
                    'nav':{'ready':nav_ready,'pose':pose},'stations':self.stations(),
                    'native_lifecycle':self.native_readiness.snapshot(),
                    'publication_mode_env':os.environ.get('RMW_FASTRTPS_PUBLICATION_MODE'),
                    'checkpoint_initialization':(self.localization_warmup.snapshot()
                                                 if self.localization_warmup is not None else None),
                    'freshness_failure':copy.deepcopy(getattr(self,'last_freshness_failure',None)),
                    'station_perception':{'mode':self.perception_config['mode'],
                        'publisher':self.perception_config['publisher'],
                        'last_rejection':self.station_rejection,'counts':dict(self.station_counts),
                        'rejection_reason_counts':dict(self.station_rejection_reason_counts),
                        'last_detection':copy.deepcopy(self.station_detection[0]) if self.station_detection else None},
                    'perception': self.perception_state(), 'vision_frame': self.vision_frame_state(raw),
                    'native_actions': self.native_action_state(),
                    'cleanup': copy.deepcopy(getattr(self, 'cleanup_summary', {'state': 'not_started'})),
                    'acceptance_report': {'available': (args.output.parent/'acceptance-report.json').is_file(),
                                          'url': '/coop-api/report' if (args.output.parent/'acceptance-report.json').is_file() else None},
                    **({'episode_id': self.episode_id} if self.episode_id else {}),
                    'reset': self.reset_state(raw), 'history': copy.deepcopy(self.history[-10:])}
                if manifest.get('business_entities'):
                    result['business_inventory'] = copy.deepcopy(getattr(self,'business_inventory',None))
                    result['business_entities'] = copy.deepcopy(raw.get('business_entities')) if raw else None
                route = result['task'].get('delivery_route')
                route_started = getattr(self, 'delivery_route_started_monotonic', None)
                if route and route['status'] == 'running' and route_started is not None:
                    route['elapsed_wall_s'] = time.monotonic()-route_started
                    route['remaining_wall_s'] = max(0., route['budget_wall_s']-route['elapsed_wall_s'])
                self.timing_record('http_assembly', assembled_at, assembly_context)
            timing = getattr(self, 'bridge_timing', None)
            if timing is not None:
                result['bridge_timing'] = timing.snapshot()
            return result

        def frame_state(self, raw=None):
            try:
                raw=self.fresh() if raw is None else raw
                info=json.loads((args.frame_dir/'latest.json').read_text())
                stamp, wall=info['stamp'],info['wall_time']
                finite_vector([stamp,wall],2,'相机帧时间')
                if (info['scene_sha256'] != scene_sha or (self.episode_id is not None and info.get('episode_id') != self.episode_id)
                        or not 0 <= time.time()-wall <= 3.5
                        or not -.1 <= raw['stamp']-stamp <= 1.5 or not self.frame_image(info).is_file()):
                    raise ValueError('相机帧来源或新鲜度无效')
                return {'available':True,'stamp':stamp}
            except (OSError,ValueError,KeyError,TypeError,RuntimeError):
                return {'available':False,'stamp':None}

        def frame_image(self, info):
            if self.episode_id is None:
                return args.frame_dir/'latest.jpg'
            if info.get('episode_id') != self.episode_id or info.get('image_file') != self.episode_id+'.jpg':
                raise ValueError('相机文件与当前回合不匹配')
            return args.frame_dir/info['image_file']

        def existing_start(self, task_id, scope, delivery, approaches, business=None):
            """Called under the telemetry lock at both admission boundaries."""
            if task_id not in self.known_ids:
                return None
            if task_id!=self.task['id']: raise Rejected('该任务编号已使用；请读取原任务记录',409)
            if self.task.get('scope', 'transport') != scope:
                raise Rejected('任务编号已绑定另一范围；请读取原任务',409)
            if self.task.get('delivery_pose', task_delivery_pose({}, manifest.get('delivery_pose'))) != delivery:
                raise Rejected('任务编号已绑定另一交付点；请读取原任务',409)
            if self.task.get('delivery_approach_poses', []) != approaches:
                raise Rejected('任务编号已绑定另一进场路线；请读取原任务',409)
            if self.task.get('business_delivery') != business:
                raise Rejected('任务编号已绑定另一货物或卸货工位；请读取原任务',409)
            return {'task_id':task_id,'task':copy.deepcopy(self.task)}

        def start(self, body):
            body = copy.deepcopy(body)
            with self.lock:
                task_id=request_identity(body, episode_id=self.episode_id)
                scope = task_scope(body)
                delivery = task_delivery_pose(body, manifest.get('delivery_pose'))
                approaches = task_delivery_approaches(body)
                business = task_business_delivery(body)
                if manifest.get('business_entities') and scope=='transport' and business is None:
                    raise Rejected('多实体配送须明确货物、取货臂和卸货工位')
                budgets = None
                if business is not None:
                    from cooperation_business import validate_delivery
                    validate_delivery(manifest,business,delivery)
                    declared = manifest['business_entities']['configuration'].get('budgets_wall_s', {})
                    if declared.get('load_and_delivery') != 360:
                        raise Rejected('连续配送须保留原360秒装运预算，并声明新增卸货预算')
                    unload_budget, = finite_vector([declared.get('unload')],1,'新增卸货预算')
                    if unload_budget <= 0:
                        raise Rejected('新增卸货预算须为正数')
                    budgets = {'load_and_delivery':360.,'unload':unload_budget}
                egress = (task_delivery_pose({}, manifest['egress_pose'])
                          if scope == 'transport' and manifest.get('egress_pose') is not None else None)
                motion = (normalize_egress_motion(manifest['egress_motion'])
                          if scope == 'transport' and manifest.get('egress_motion') is not None else None)
                existing = self.existing_start(task_id, scope, delivery, approaches, business)
                if existing is not None:
                    return existing
                episode = self.episode_id
                current=self.state(scope=scope)
                if not current['ready']: raise Rejected(current['reason'],409)
            # Compilation and native geometry queries never hold the telemetry
            # lock. Physics/observation callbacks continue updating their cache.
            preflight = (self.validate_delivery_goal(delivery)
                         if scope in ('transport','route') and 'delivery_pose' in body else None)
            if preflight is not None:
                preflight.update(cargo_minimum_net_displacement_m=.5, cargo_transport_validated=False)
            approach_preflight = ([self.validate_delivery_goal(goal) for goal in approaches]
                                  if scope in ('transport','route') else [])
            with self.lock:
                if self.episode_id != episode:
                    raise Rejected('场景回合已变化，请读取最新状态后重新开始',409)
                request_identity(body, episode_id=self.episode_id)
                existing = self.existing_start(task_id, scope, delivery, approaches, business)
                if existing is not None:
                    return existing
                current=self.state(scope=scope)
                if not current['ready']: raise Rejected(current['reason'],409)
                if business is not None:
                    from cooperation_business import reserve, observe
                    material = observe(self.fresh(),manifest,business['cargo_id'],business['pickup_arm_id'])
                    if not material['entity_contacts']['supports'].get('pickup',{}).get('contact_count'):
                        raise Rejected('所选货物尚未在真实取货位，未预留库存',409)
                    reserve(self.inventory(self.fresh()),business,task_id)
                self.archive_current()
                self.known_ids.add(task_id)
                self.cancel_event.clear();self.abort_event.clear();self.abort_reason=None;self.loaded=False
                self.task_epoch+=1
                self.execution_token=(task_id,self.task_epoch)
                self.dispatches=[]
                self.last_freshness_failure = None
                self.cleanup_summary = {'state': 'not_started', 'native_terminal': False,
                                        'quiet': False, 'hold': False, 'guard_disabled': False}
                self.task={'id':task_id,'scope':scope,'status':'running','stage':'submitted','message':'任务已提交，等待原生执行','stop_reason':None,
                           'delivery_pose':copy.deepcopy(delivery), 'delivery_goal_preflight':copy.deepcopy(preflight),
                           'delivery_approach_poses':copy.deepcopy(approaches),
                           'delivery_approach_preflight':copy.deepcopy(approach_preflight)}
                if business is not None:
                    self.task.update(business_delivery=copy.deepcopy(business),
                                     active_arm_id=business['pickup_arm_id'],
                                     business_budgets_wall_s=budgets)
                    self.last_ref = list(self.task_material(self.fresh())['q6'])
                for attribute in ('loaded_limits', 'loaded_controller'):
                    current = getattr(self, attribute, None)
                    if current is not None:
                        setattr(self, attribute, current.new_task())
                if egress is not None:
                    self.task['egress_pose'] = copy.deepcopy(egress)
                if motion is not None:
                    self.task['egress_motion'] = copy.deepcopy(motion)
                self.events=[];self.persist()
                self.task_worker = threading.Thread(target=self.execute,args=(self.execution_token,),daemon=True,name='cooperation-task')
                self.task_worker.start()
                return {'task_id':task_id,'task':copy.deepcopy(self.task)}

        def cancel(self, body):
            task_id=request_identity(body,cancel=True)
            with self.lock:
                if task_id!=self.task['id']: raise Rejected('任务编号不匹配；未取消其他任务',409)
                if self.task['status']=='unknown':raise Rejected('任务结果未知，请先核对原生执行状态',409)
                if self.task['status']=='running':
                    self.task.update(status='canceling',stop_reason='用户取消任务')
                    self.cancel_event.set()
                    self.abort(self.execution_token,'用户取消任务')
                    self.persist()
                return {'task_id':task_id,'task':copy.deepcopy(self.task)}

    rclpy.init()
    bridge=Bridge(); executor=MultiThreadedExecutor(num_threads=4);executor.add_node(bridge)
    runtime = RuntimeIdentity('cooperation', 'simulation', args.domain, [
        capability('transport', 'native_action', cancel=True, event_history='bounded'),
    ], scene_id=scene_sha)
    server = make_server(bridge, args, runtime=runtime)
    threading.Thread(target=server.serve_forever,daemon=True,name='cooperation-http').start()
    try:executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass  # The launch signal can close the ROS context before spin returns.
    finally:
        bridge.cancel_event.set()
        if bridge.context.ok():
            bridge.hold(True)
        server.shutdown();executor.shutdown();bridge.destroy_node();rclpy.try_shutdown()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--frame-dir',required=True,type=Path)
    parser.add_argument('--domain',type=int,default=114)
    parser.add_argument('--port',type=int,default=9086)
    args=parser.parse_args()
    if not 1<=args.domain<=232 or args.domain==107:parser.error('必须使用独立非零ROS域，不能占用当前107')
    os.environ['ROS_DOMAIN_ID']=str(args.domain)
    os.environ['ROS_AUTOMATIC_DISCOVERY_RANGE']='LOCALHOST'
    os.environ['ROS_LOCALHOST_ONLY']='1'
    try:
        with DomainExecutionLock(args.domain, 'cooperation'):
            run(args)
    except ExecutionOwnerBusy as error:
        raise SystemExit(str(error)) from None


if __name__=='__main__':main()
