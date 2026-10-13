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

from cooperation_core import (ACTIVE, ContinuousEvidence, Rejected, car_pose,
                              cargo_retained, dispatch_terminal, finite_vector,
                              physical_quiet, quaternion, request_identity,
                              settled_cargo, stopped, tip_forces, validate_physics)
from cooperation_core import station_robot_pose, within_station_capture


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
    from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
    from rclpy.time import Time
    from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
    from nav2_msgs.action import NavigateToPose, DockRobot
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
            self.buffer = Buffer()
            self.listener = TransformListener(self.buffer, self)
            self.nav = ActionClient(self, NavigateToPose, '/navigate_to_pose')
            self.docking = ActionClient(self, DockRobot, '/dock_robot')
            self.beacon = None
            self.last_station_pose_stamp = -math.inf
            self.pose_pub = self.create_publisher(PoseWithCovarianceStamped, '/initialpose', 1)
            self.create_subscription(PoseStamped, '/detected_dock_pose', self.observe_beacon, 1)
            hold_qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE)
            self.hold_pub = self.create_publisher(Bool, '/cooperation/car_hold', hold_qos)
            self.dock_guard_pub = self.create_publisher(Bool, '/cooperation/docking_guard', hold_qos)
            self.dock_guard_active = False
            self.arm_pub = self.create_publisher(JointState, '/cooperation/arm_reference', 1)
            latest_state_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                                         durability=DurabilityPolicy.VOLATILE)
            self.create_subscription(String, '/cooperation/physics_state', self.observe, latest_state_qos)
            args.output.mkdir(parents=True, exist_ok=True)
            self.ledger = args.output/'task.json'
            self.hold(True)
            self.dock_guard_pub.publish(Bool(data=False))

        def persist(self):
            path = self.ledger.with_suffix('.tmp')
            path.write_text(json.dumps({'task': self.task, 'events': self.events, 'known_ids': sorted(self.known_ids)}, ensure_ascii=False, indent=2)+'\n')
            path.replace(self.ledger)

        def observe(self, message):
            try:
                value = validate_physics(json.loads(message.data), scene_sha, manifest_sha)
                with self.lock:
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

        def observe_beacon(self,message):
            with self.lock:
                self.beacon=(message,time.monotonic())

        def update_station_localization(self,*,force=False,optional=False):
            """Feed the explicitly idealized station observation to native AMCL.

            Only near the fixed station, while this task owns the robot. Neither
            world qpos nor ground_truth topics are used to derive this pose.
            The sensor itself is truth-derived simulation, disclosed in the UI.
            """
            with self.lock:
                self.owner()
                raw=self.fresh()
                source=raw.get('dock_beacon',{})
                if (source.get('idealized_truth_derived') is not True
                        or source.get('scene_sha256') != scene_sha
                        or source.get('manifest_sha256') != manifest_sha):
                    raise RuntimeError('工位信标来源与当前仿真场景不一致')
                if source.get('in_range') is False:
                    if optional:return None
                    raise RuntimeError('工位观测超出1米有效范围')
                if source.get('in_range') is not True:
                    raise RuntimeError('工位信标缺少有效范围状态')
                publishers=self.get_publishers_info_by_topic('/detected_dock_pose')
                if len(publishers)!=1 or publishers[0].node_name!='cooperation_physics':
                    raise RuntimeError('工位信标必须来自本域唯一物理传感器')
                if self.beacon is None:
                    if optional:return None
                    raise RuntimeError('尚未收到工位相对观测')
                measured,received=self.beacon
                stamp=measured.header.stamp.sec+measured.header.stamp.nanosec*1e-9
                now=self.get_clock().now().nanoseconds*1e-9
                if measured.header.frame_id!='base_footprint':
                    raise RuntimeError('工位相对观测坐标系错误')
                if time.monotonic()-received>.5 or not -.1<=now-stamp<=.25:
                    if optional:return None
                    raise RuntimeError('工位相对观测已过期或坐标系错误')
                position=measured.pose.position;rotation=measured.pose.orientation
                q=quaternion([rotation.w,rotation.x,rotation.y,rotation.z],'工位观测朝向')
                relative=finite_vector([position.x,position.y,
                    math.atan2(2*(q[0]*q[3]+q[1]*q[2]),1-2*(q[2]*q[2]+q[3]*q[3]))],3,'工位观测')
                if math.hypot(*relative[:2])>1.:
                    raise RuntimeError('工位观测超出1米有效范围')
                pose=station_robot_pose(relative,manifest['native_dock_pose'])
                if not force and stamp-self.last_station_pose_stamp<.3:
                    return pose
                message=PoseWithCovarianceStamped()
                message.header.frame_id='map';message.header.stamp=copy.deepcopy(measured.header.stamp)
                message.pose.pose.position.x,message.pose.pose.position.y=pose['x'],pose['y']
                message.pose.pose.orientation.z=math.sin(pose['yaw']/2)
                message.pose.pose.orientation.w=math.cos(pose['yaw']/2)
                for index in (0,7,35):message.pose.covariance[index]=.0001
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
                self.wait_condition(lambda v: settled_cargo(v) and np.max(np.abs(np.asarray(v['q6'])-manifest['arm_home_qpos6']))<.02
                    and np.linalg.norm(v['qvel6'])<.05,duration=1.,timeout=8.)
                self.event('arm','loaded','货物已放稳，机械臂已退出，可以运输。')
                self.loaded = True
                raw = self.check(carrying=True)
                start = raw['cargo']['position'][:2]
                self.event('car','delivery','收到交接确认，驶往交付点。')
                self.navigate(self.stations()['delivery'],carrying=True)
                raw = self.wait_condition(lambda v: stopped(v) and settled_cargo(v),duration=1.,timeout=8.,carrying=True)
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
                    station=manifest['station_offset']; target=raw['cargo']['position']
                    if math.hypot(target[0]-station[0]-.24,target[1]-station[1]+.13)>.035:
                        ready=False; reason='物体已离开取货盘；本回合完成后需重置合成场景'
                    if any(raw[f'{body}_forbidden_contact_{kind}']
                           for body in ('arm','car') for kind in ('count','total')):
                        ready=False;reason='存在非预期物理接触，请查看本回合诊断'
                    if self.task['status'] in ACTIVE: ready=False;reason='当前任务持有车臂控制权'
                except Exception as error:
                    ready=False;nav_ready=False;reason=str(error)
                frame=self.frame_state(raw)
                return {'mode':'mujoco','domain':args.domain,'ready':ready,'reason':reason,'task':copy.deepcopy(self.task),
                    'events':copy.deepcopy(self.events),'physics':physics,'frame':frame,'source':{'scene_sha':raw['source']['scene_sha256']} if raw else None,
                    'nav':{'ready':nav_ready,'pose':pose},'stations':self.stations()}

        def frame_state(self, raw=None):
            try:
                raw=self.fresh() if raw is None else raw
                info=json.loads((args.frame_dir/'latest.json').read_text())
                stamp, wall=info['stamp'],info['wall_time']
                finite_vector([stamp,wall],2,'相机帧时间')
                if (info['scene_sha256'] != scene_sha or not 0 <= time.time()-wall <= 3.5
                        or not -.1 <= raw['stamp']-stamp <= 1.5 or not (args.frame_dir/'latest.jpg').is_file()):
                    raise ValueError('相机帧来源或新鲜度无效')
                return {'available':True,'stamp':stamp}
            except (OSError,ValueError,KeyError,TypeError,RuntimeError):
                return {'available':False,'stamp':None}

        def start(self, body):
            task_id=request_identity(body)
            with self.lock:
                if task_id in self.known_ids:
                    if task_id!=self.task['id']: raise Rejected('该任务编号已使用；请读取原任务记录',409)
                    return {'task_id':task_id,'task':copy.deepcopy(self.task)}
                current=self.state()
                if not current['ready']: raise Rejected(current['reason'],409)
                self.known_ids.add(task_id)
                self.cancel_event.clear();self.abort_event.clear();self.abort_reason=None;self.loaded=False
                self.task_epoch+=1
                self.execution_token=(task_id,self.task_epoch)
                self.dispatches=[]
                self.task={'id':task_id,'status':'running','stage':'submitted','message':'任务已提交，等待原生执行','stop_reason':None}
                self.events=[];self.persist()
                threading.Thread(target=self.execute,args=(self.execution_token,),daemon=True,name='cooperation-task').start()
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
            if path=='/coop-api/frame.jpg':
                if not bridge.frame_state()['available']:
                    self.send_json(503,{'error':'共享相机帧缺失、过期或来源不匹配'});return
                try:content=(args.frame_dir/'latest.jpg').read_bytes()
                except OSError:self.send_json(503,{'error':'尚无共享物理世界画面'});return
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
