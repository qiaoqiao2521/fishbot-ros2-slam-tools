#!/usr/bin/env python3
"""Real Nav2 and contact-feedback orchestration; local synthetic worlds only."""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from urllib.parse import parse_qs

from cooperation_core import (ACTIVE, ContinuousEvidence, Rejected, arm_home_quiet, car_pose,
                              cargo_retained, dispatch_terminal, finite_vector,
                              physical_quiet, quaternion, request_identity,
                              reset_request_identity,
                              settled_cargo, stopped, tip_forces, transport_handoff_ready, validate_physics)
from cooperation_core import station_robot_pose, within_station_capture
from cooperation_perception import (map_covariance, messages_to_observation,
                                    normalize_config, validate_observation)


class Canceled(RuntimeError):
    pass


def run(args):
    if (args.output/'task.json').exists():
        raise RuntimeError('已有任务账本，不能复用旧物理回合；保留记录并创建新场景与运行目录')
    import numpy as np
    import rclpy
    from rclpy.action import ActionClient
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, qos_profile_sensor_data
    from rclpy.time import Time
    from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
    from diagnostic_msgs.msg import DiagnosticArray
    from message_filters import Subscriber, TimeSynchronizer
    from nav2_msgs.action import NavigateToPose, DockRobot
    from nav2_msgs.srv import ClearEntireCostmap
    from sensor_msgs.msg import JointState
    from std_msgs.msg import Bool, String
    from tf2_ros import Buffer, TransformListener
    from cooperation_arm import ArmPlanner

    manifest = json.loads(args.manifest.read_text())
    scene_sha = hashlib.sha256(Path(manifest['world_xml']).read_bytes()).hexdigest()
    manifest_sha = hashlib.sha256(args.manifest.read_bytes()).hexdigest()

    class Bridge(Node):
        def __init__(self):
            super().__init__('fishbot_so101_cooperation', parameter_overrides=[rclpy.parameter.Parameter('use_sim_time', value=True)])
            self.lock = threading.RLock()
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
            self.last_ref = list(manifest['arm_home_qpos6'])
            self.task = {'id': None, 'status': 'idle', 'stage': 'idle', 'message': '等待装货运输任务', 'stop_reason': None}
            self.events = []
            self.known_ids = set()
            self.loaded = False
            self.episode_id = None
            self.task_worker = None
            self.reset_worker = None
            self.reset_records = {}
            self.reset_acks = {}
            self.reset_runtime = {}
            self.last_reset_id = None
            self.history = []
            self.buffer = Buffer()
            self.listener = TransformListener(self.buffer, self)
            self.nav = ActionClient(self, NavigateToPose, '/navigate_to_pose')
            self.docking = ActionClient(self, DockRobot, '/dock_robot')
            self.beacon = None
            self.perception_config = normalize_config(manifest.get('station_perception'))
            if self.perception_config['station_id'] != manifest['native_docking']['dock_id']:
                raise ValueError('观测工位与原生停靠工位不一致')
            self.station_last_seen = None
            self.station_detection = None
            self.station_rejection = None
            self.station_counts = {'accepted': 0, 'unavailable': 0, 'rejected': 0, 'forwarded': 0}
            self.last_station_pose_stamp = -math.inf
            self.pose_pub = self.create_publisher(PoseWithCovarianceStamped, '/initialpose', 1)
            self.dock_pose_pub = self.create_publisher(PoseStamped, '/detected_dock_pose', 1)
            # Exact source stamps, bounded queues, and standard ROS messages.
            perception_qos = copy.copy(qos_profile_sensor_data)
            perception_qos.depth = 1
            self.station_pose_filter = Subscriber(self, PoseWithCovarianceStamped,
                                                  '/cooperation/station_pose', qos_profile=perception_qos)
            self.station_detection_filter = Subscriber(self, DiagnosticArray,
                                                       '/cooperation/station_detection', qos_profile=perception_qos)
            self.station_detection_filter.registerCallback(self.observe_station_detection)
            self.station_sync = TimeSynchronizer(
                [self.station_pose_filter, self.station_detection_filter], queue_size=5)
            self.station_sync.registerCallback(self.observe_station_pair)
            hold_qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE)
            self.hold_pub = self.create_publisher(Bool, '/cooperation/car_hold', hold_qos)
            self.dock_guard_pub = self.create_publisher(Bool, '/cooperation/docking_guard', hold_qos)
            self.dock_guard_active = False
            self.arm_pub = self.create_publisher(JointState, '/cooperation/arm_reference', 1)
            reset_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                   durability=DurabilityPolicy.VOLATILE)
            self.reset_pub = self.create_publisher(String, '/cooperation/reset_request', reset_qos)
            self.create_subscription(String, '/cooperation/reset_result', self.observe_reset, reset_qos)
            self.reset_clearers = [self.create_client(ClearEntireCostmap, path) for path in (
                '/global_costmap/clear_entirely_global_costmap', '/local_costmap/clear_entirely_local_costmap')]
            latest_state_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                                         durability=DurabilityPolicy.VOLATILE)
            self.create_subscription(String, '/cooperation/physics_state', self.observe, latest_state_qos)
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

        def persist(self):
            path = self.ledger.with_suffix('.tmp')
            path.write_text(json.dumps({'task': self.task, 'events': self.events, 'known_ids': sorted(self.known_ids),
                'episode_id': self.episode_id, 'reset_records': self.reset_records}, ensure_ascii=False, indent=2)+'\n')
            path.replace(self.ledger)

        def observe(self, message):
            try:
                value = validate_physics(json.loads(message.data), scene_sha, manifest_sha)
                with self.lock:
                    episode = value.get('episode_id')
                    if episode is not None:
                        if value['source'].get('episode_id') != episode:
                            raise ValueError('物理回合来源不一致')
                        if self.episode_id is None:
                            self.episode_id = episode
                        if episode != self.episode_id:
                            return
                    self.raw, self.received = value, time.monotonic()
                    self.observation_error = None
            except (ValueError, KeyError, TypeError, IndexError) as error:
                with self.lock:
                    self.raw = None
                    self.observation_error = f'共享物理反馈无效：{error}'
                    if self.task['status'] in ACTIVE:
                        self.abort_event.set()
                        self.abort_reason = self.observation_error
                        self.hold(True)
                self.get_logger().warning(self.observation_error)

        def fresh(self):
            with self.lock:
                if self.raw is None or time.monotonic()-self.received > .5:
                    raise RuntimeError(self.observation_error or '共享物理反馈中断')
                validate_physics(self.raw, scene_sha, manifest_sha)
                if self.episode_id is not None and self.raw.get('episode_id') != self.episode_id:
                    raise RuntimeError('等待新回合的物理反馈')
                now = self.get_clock().now().nanoseconds*1e-9
                if not -.1 <= now-self.raw['stamp'] <= .25:
                    raise RuntimeError('共享物理反馈时间失效')
                return copy.deepcopy(self.raw)

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

        def reference(self, value, *, token=None, freeze=False):
            with self.lock:
                self.owner(token, allow_abort=freeze)
                values = finite_vector(list(value), 6, '机械臂参考')
                if freeze:
                    raw = self.fresh()
                    if values[:5] != raw['q6'][:5] or values[5] != self.last_ref[5]:
                        raise RuntimeError('清理阶段只允许保持当前机械臂位置与原夹爪压力')
                message = JointState()
                message.header.stamp = self.get_clock().now().to_msg()
                message.name = manifest['arm_joint_names']
                message.position = values
                self.arm_pub.publish(message)
                self.last_ref = list(message.position)

        def freeze_arm(self, token):
            with self.lock:
                self.owner(token, allow_abort=True)
                try:
                    frozen = list(self.fresh()['q6'])
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
                if any(raw[f'{body}_forbidden_contact_{kind}']
                       for body in ('arm','car') for kind in ('count','total')):
                    raise RuntimeError('车体或机械臂发生非预期物理接触')
                if carrying and not cargo_retained(raw):
                    raise RuntimeError('运输途中货物离开托盘支撑范围')
                if carrying and not arm_home_quiet(raw, manifest['arm_home_qpos6']):
                    raise RuntimeError('运输期间机械臂未保持回位停稳状态')
                return raw

        def wait_condition(self, condition, *, duration=.7, timeout=8., carrying=False, cancelable=True):
            gate = ContinuousEvidence(duration)
            end = time.monotonic()+timeout
            while time.monotonic()<end:
                raw = self.check(carrying=carrying) if cancelable else self.fresh()
                if gate.update(raw['stamp'], bool(condition(raw))):
                    return raw
                time.sleep(.01)
            raise RuntimeError('未取得连续物理确认')

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

        def station_publishers(self):
            for topic in ('/cooperation/station_pose', '/cooperation/station_detection'):
                publishers = self.get_publishers_info_by_topic(topic)
                if len(publishers) != 1 or publishers[0].node_name != self.perception_config['publisher']:
                    raise ValueError('工位观测必须来自配置的本域唯一传感器')
            publishers = self.get_publishers_info_by_topic('/detected_dock_pose')
            if len(publishers) != 1 or publishers[0].node_name != self.get_name():
                raise ValueError('原生停靠位姿必须由本桥唯一转发')

        def reject_station_observation(self, error):
            # A late rejected packet cannot erase a newer accepted observation.
            self.station_counts['rejected'] += 1
            self.station_rejection = str(error)

        def admit_station_observation(self, observation):
            self.station_publishers()
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
            with self.lock:
                try:
                    admitted = self.admit_station_observation(messages_to_observation(None, diagnostics))
                    if admitted['detected']:
                        raise ValueError('失检诊断不能携带有效检测')
                    self.station_counts['unavailable'] += 1
                except (RuntimeError, ValueError, KeyError, TypeError, AttributeError) as error:
                    self.reject_station_observation(error)

        def observe_station_pair(self, pose, diagnostics):
            with self.lock:
                try:
                    admitted = self.admit_station_observation(messages_to_observation(pose, diagnostics))
                    if not admitted['detected']:
                        raise ValueError('失检不能产生停靠位姿')
                    # Only admitted, fresh, same-episode observations reach Nav2.
                    message = PoseStamped()
                    message.header = copy.deepcopy(pose.header)
                    message.pose = copy.deepcopy(pose.pose.pose)
                    self.dock_pose_pub.publish(message)
                    self.beacon = (admitted, time.monotonic(), copy.deepcopy(pose.header.stamp))
                    self.station_counts['accepted'] += 1
                    self.station_counts['forwarded'] += 1
                except (RuntimeError, ValueError, KeyError, TypeError, AttributeError) as error:
                    self.reject_station_observation(error)

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
                if time.monotonic()-received>.5 or not -.1<=now-stamp<=.25:
                    if optional:return None
                    raise RuntimeError('工位相对观测已过期')
                try:
                    validate_observation(measured, self.perception_config, identity, now,
                                         time.monotonic()-received)
                except ValueError as error:
                    raise RuntimeError(f'工位观测来源或内容无效：{error}') from error
                relative=measured['relative']
                pose=station_robot_pose(relative,manifest['native_dock_pose'])
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
            gate = ContinuousEvidence(.7)
            end = time.monotonic()+timeout
            disabled_at = None
            while time.monotonic()<end:
                with self.lock:
                    self.owner(token, allow_abort=True)
                    dispatches = [item for item in self.dispatches if item['token'] == token]
                    for dispatch in dispatches:
                        self.cancel_dispatch(dispatch)
                    native_terminal = all(dispatch_terminal(item) for item in dispatches)
                raw = self.fresh()
                quiet = gate.update(raw['stamp'], physical_quiet(raw))
                if quiet and native_terminal and raw['car_hold'] is True:
                    enabled=self.guard_acknowledged(raw)
                    tripped=raw['docking_guard']['tripped']
                    if disabled_at is None and (self.dock_guard_active or enabled or tripped):
                        disabled_at = raw['stamp']
                        self.set_docking_guard(False,token,allow_abort=True)
                    if not enabled and not tripped and (disabled_at is None or raw['stamp'] > disabled_at):
                        return True
                time.sleep(.01)
            return False

        def navigate(self, goal, *, carrying=False, station_localization=False):
            request = NavigateToPose.Goal()
            request.pose = PoseStamped()
            request.pose.header.frame_id = 'map'
            request.pose.header.stamp = self.get_clock().now().to_msg()
            request.pose.pose.position.x, request.pose.pose.position.y = goal['x'], goal['y']
            request.pose.pose.orientation.z, request.pose.pose.orientation.w = math.sin(goal['yaw']/2), math.cos(goal['yaw']/2)
            return self.dispatch_goal(self.nav,request,carrying=carrying,label='Nav2',timeout=120,
                station_localization=station_localization,allow_outside_station=station_localization)

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

        def dispatch_goal(self,client,request,*,carrying=False,label,timeout,station_localization=False,
                          allow_outside_station=False,docking_guard=False):
            token = self.owner()
            self.hold(True, token)
            try:
                with self.lock:
                    self.owner(token)
                    self.dispatch_epoch += 1
                    dispatch = {'token': token, 'epoch': self.dispatch_epoch, 'request': None, 'handle': None,
                                'result': None, 'cancel': None, 'received': False, 'aborted': False, 'error': None}
                    self.dispatches.append(dispatch)
                    sent = client.send_goal_async(request)
                    dispatch['request'] = sent
                    sent.add_done_callback(lambda future: self.received_goal(dispatch, future))
                handle = self.wait_future(sent, 8, carrying=carrying)
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
                with self.lock:
                    self.owner(token)
                    if not dispatch['result'].done():
                        self.hold(False, token)
                result = self.wait_future(dispatch['result'], timeout, carrying=carrying,
                    station_localization=station_localization,allow_outside_station=allow_outside_station,
                    docking_guard=docking_guard)
                self.hold(True, token)
                native = getattr(result, 'result', None)
                if result.status != 4 or getattr(native,'success',True) is not True:
                    code = getattr(native, 'error_code', None)
                    message = getattr(native, 'error_msg', '')
                    detail = message.strip() if isinstance(message, str) and message.strip() else 'Nav2未提供具体失败原因'
                    error_code = f'，错误码{code}' if code is not None else '，错误码未提供'
                    raise RuntimeError(f'{label}目标未成功，状态{result.status}{error_code}：{detail}')
                raw=self.wait_condition(lambda value: stopped(value) and value['car_hold'] is True,
                                        carrying=carrying)
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
                if not planner.evaluate(raw['q6'])['valid']:
                    raise RuntimeError('实际机械臂位姿失去原碰撞余量')
                if age >= duration+dwell and np.max(np.abs(np.asarray(raw['q6'])[:5]-points[-1]))<.012 and np.linalg.norm(raw['qvel6'][:5])<.05:
                    return raw
                if age > source_limit:
                    errors=np.abs(np.asarray(raw['q6'])[:5]-points[-1])
                    joint=int(np.argmax(errors))
                    raise RuntimeError(f'机械臂 {stage} 段未收敛：关节 {manifest["arm_joint_names"][joint]} '
                        f'误差 {errors[joint]:.4f}rad，仿真时间 {age:.2f}/{source_limit:.2f}s')
                time.sleep(.02)

        def execute(self, token):
            self.worker.token = token
            try:
                self.wall_deadline = time.monotonic()+360
                self.event('car','docking','前往 SO101 工位，请等待停靠。')
                if self.station_capture_ready():
                    self.event('car','docking','已在工位停靠捕获区，继续对准原生停靠。')
                else:
                    self.navigate(self.stations()['staging'],station_localization=True)
                self.align_station_map()
                self.event('car','docking','已到工位附近，使用仿真信标进行原生近距离精停靠。')
                raw = self.dock_at_station()
                self.hold(True)
                pose = car_pose(raw)
                dock = self.stations()['dock']
                if math.hypot(pose['x']-dock['x'],pose['y']-dock['y'])>.04 or abs(math.atan2(math.sin(pose['yaw']),math.cos(pose['yaw'])))>.05:
                    raise RuntimeError('车体尚未进入真实交接位置与朝向范围')
                self.event('car','docked','已到工位并停稳，请 SO101 装货。')
                planner = ArmPlanner(manifest, car_pose=raw['qpos22'][13:20])
                plan = planner.prepare_approach(raw['q6'])
                self.check()
                baseline = raw['cargo']['position'][2]
                for segment in plan['segments']:
                    self.event('arm',segment['stage'], {'approach':'正在靠近取货位置。','descend':'正在下降到夹取位置。',
                        'close':'正在闭合夹爪，等待接触反馈。','lift':'正在抬升货物。'}.get(segment['stage'],'正在执行已验证的机械臂轨迹。'))
                    raw = self.segment(segment, planner)
                self.wait_condition(lambda value: value['cargo']['position'][2]-baseline>=.025 and min(tip_forces(value))>.02,
                                    duration=1., timeout=5.)
                self.event('arm','holding','双指接触与抬升已确认，正在保持货物。')
                raw = self.check()
                transport = planner.prepare_transport(raw)
                self.check()
                released=False
                for segment in transport['segments']:
                    if segment['stage']=='retreat':
                        raw=self.wait_condition(settled_cargo,duration=1.,timeout=6.)
                        released=True
                        self.event('arm','retreat','托盘支撑与松爪落稳已确认，正在退出。')
                    else:
                        message={'transport':'正在把货物放入车载托盘。','lower':'正在下降到托盘。',
                            'release':'正在松开夹爪，等待货物落稳。','settle':'正在确认机械臂回位。'}[segment['stage']]
                        self.event('arm',segment['stage'],message)
                    self.segment(segment,planner)
                if not released:raise RuntimeError('规划缺少真实松爪与退出阶段')
                self.wait_condition(lambda v: transport_handoff_ready(v, manifest['arm_home_qpos6']),
                                    duration=1., timeout=8.)
                self.event('arm','loaded','货物已放稳，机械臂已退出，可以运输。')
                self.loaded = True
                raw = self.check(carrying=True)
                start = raw['cargo']['position'][:2]
                self.event('car','delivery','收到交接确认，驶往交付点。')
                self.navigate(self.stations()['delivery'],carrying=True)
                raw = self.wait_condition(lambda v: transport_handoff_ready(v, manifest['arm_home_qpos6']),
                                          duration=1., timeout=8., carrying=True)
                if math.hypot(raw['cargo']['position'][0]-start[0],raw['cargo']['position'][1]-start[1])<.5:
                    raise RuntimeError('货物实际运输位移不足0.5米')
                self.event('car','delivered','已到交付点，货物仍在托盘，车辆与货物已停稳。')
                with self.lock:
                    self.owner(token)
                    self.task.update(status='succeeded',message='装货运输完成')
                    self.persist()
            except Exception as error:
                if token != self.execution_token:
                    return
                self.abort(token, error)
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
                      'events': copy.deepcopy(self.events), 'completed_at': time.time()}
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
            return physical_quiet(raw) and math.sqrt(sum(value*value for value in velocity[3:])) < .03

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
                    self.episode_id = ack['new_episode_id']
                    self.execution_token = None
                    self.beacon = None
                    self.station_last_seen = None
                    self.station_detection = None
                    self.station_rejection = None
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
            return {'dock':dict(zip(('x','y','yaw'),dock)),
                    'staging':dict(zip(('x','y','yaw'),manifest['staging_pose'])),
                    'delivery':{'x':0.,'y':-2.,'yaw':0.}}

        def state(self):
            with self.lock:
                ready=False; reason='等待共享物理世界与 Nav2'
                pose=None; raw=None; physics=None; nav_ready=False
                try:
                    raw=self.fresh()
                    cargo=raw['cargo'];velocity=cargo['velocity_world_angular_linear'][3:]
                    physics={'stamp':raw['stamp'],'car':{**car_pose(raw),'linear_speed':raw['car']['speed'],'angular_speed':raw['car']['yaw_rate']},
                        'arm':{'q':raw['q6'],'velocity':raw['qvel6']},'cargo':dict(zip(('x','y','z'),cargo['position']))}
                    physics['cargo'].update(speed=math.sqrt(sum(v*v for v in velocity)),tip_forces=tip_forces(raw),tray_contact=raw['cargo_tray_floor_contact'])
                    pose=self.localized()
                    nav_ready=self.nav.server_is_ready() and self.docking.server_is_ready()
                    ready=nav_ready
                    reason='共享物理世界与 Nav2 已就绪' if ready else '等待原生导航服务'
                    self.station_publishers()
                    station=manifest['station_offset']; target=raw['cargo']['position']
                    if math.hypot(target[0]-station[0]-.24,target[1]-station[1]+.13)>.035:
                        ready=False; reason='物体已离开取货盘；本回合完成后需重置合成场景'
                    if any(raw[f'{body}_forbidden_contact_{kind}']
                           for body in ('arm','car') for kind in ('count','total')):
                        ready=False;reason='存在非预期物理接触，请查看本回合诊断'
                    if self.task['status'] in ACTIVE: ready=False;reason='当前任务持有车臂控制权'
                    if self.reset_in_progress(): ready=False;reason='正在重置或核对新回合，请等待明确反馈'
                except Exception as error:
                    ready=False;nav_ready=False;reason=str(error)
                frame=self.frame_state(raw)
                return {'mode':'mujoco','domain':args.domain,'ready':ready,'reason':reason,'task':copy.deepcopy(self.task),
                    'events':copy.deepcopy(self.events),'physics':physics,'frame':frame,'source':{'scene_sha':raw['source']['scene_sha256']} if raw else None,
                    'nav':{'ready':nav_ready,'pose':pose},'stations':self.stations(),
                    'station_perception':{'mode':self.perception_config['mode'],
                        'publisher':self.perception_config['publisher'],
                        'last_rejection':self.station_rejection,'counts':dict(self.station_counts),
                        'last_detection':copy.deepcopy(self.station_detection[0]) if self.station_detection else None},
                    **({'episode_id': self.episode_id} if self.episode_id else {}),
                    'reset': self.reset_state(raw), 'history': copy.deepcopy(self.history[-10:])}

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

        def start(self, body):
            with self.lock:
                task_id=request_identity(body, episode_id=self.episode_id)
                if task_id in self.known_ids:
                    if task_id!=self.task['id']: raise Rejected('该任务编号已使用；请读取原任务记录',409)
                    return {'task_id':task_id,'task':copy.deepcopy(self.task)}
                current=self.state()
                if not current['ready']: raise Rejected(current['reason'],409)
                self.archive_current()
                self.known_ids.add(task_id)
                self.cancel_event.clear();self.abort_event.clear();self.abort_reason=None;self.loaded=False
                self.task_epoch+=1
                self.execution_token=(task_id,self.task_epoch)
                self.dispatches=[]
                self.task={'id':task_id,'status':'running','stage':'submitted','message':'任务已提交，等待原生执行','stop_reason':None}
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
    bridge=Bridge(); executor=MultiThreadedExecutor(num_threads=3);executor.add_node(bridge)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*unused): pass
        def send_json(self,status,value):
            content=json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
        def do_GET(self):
            path=urlsplit(self.path).path
            if path=='/coop-api/state':self.send_json(200,bridge.state());return
            if path.startswith('/coop-api/reset/'):
                try:self.send_json(200,bridge.reset_record(path.rsplit('/',1)[1]))
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
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=4096:raise Rejected('请求长度无效')
                body=json.loads(self.rfile.read(size))
                path=urlsplit(self.path).path
                if path=='/coop-api/start':result=bridge.start(body)
                elif path=='/coop-api/cancel':result=bridge.cancel(body)
                elif path=='/coop-api/reset':result=bridge.reset_episode(body)
                else:raise Rejected('未知接口',404)
                self.send_json(200,result)
            except (Rejected,ValueError,TypeError) as error:self.send_json(getattr(error,'status',400),{'error':str(error),'outcome':'rejected'})
            except Exception as error:self.send_json(500,{'error':str(error),'outcome':'unknown'})
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    threading.Thread(target=server.serve_forever,daemon=True,name='cooperation-http').start()
    try:executor.spin()
    finally:
        bridge.cancel_event.set();bridge.hold(True);server.shutdown();executor.shutdown();bridge.destroy_node();rclpy.shutdown()


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
    run(args)


if __name__=='__main__':main()
