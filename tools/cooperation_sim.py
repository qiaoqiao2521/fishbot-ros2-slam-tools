#!/usr/bin/env python3
"""ROS sensor/control adapter for one contact-based FishBot/SO101 world.

The arm receives bounded position references. Wheel servos receive fresh velocity
commands. Only reset initializes state; runtime never teleports any body.
"""
from __future__ import annotations

import argparse
from collections import deque, OrderedDict
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import random
import shutil
import sys
import threading
import time
import uuid
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from fishbot_sim_power import BEACON_LABEL, PowerModel, Truth
from cooperation_core import ContinuousEvidence
from cooperation_recording import BoundedDiagnosticLog
from cooperation_perception import (
    DETECTION_TOPIC as STATION_DETECTION_TOPIC, DIAGNOSTIC_NAME,
    POSE_TOPIC as STATION_POSE_TOPIC, normalize_config,
)

ARM_JOINTS = ('shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex',
              'wrist_roll', 'gripper')
WHEEL_JOINTS = ('left_wheel_joint', 'right_wheel_joint')
WHEEL_RADIUS = .032
WHEEL_SEPARATION = .20
COMMAND_TIMEOUT = .5
BEACON_RANGE_M = 1.
RESET_REQUEST_TOPIC = '/cooperation/reset_request'
RESET_RESULT_TOPIC = '/cooperation/reset_result'


def reset_request(payload):
    """Admit one recent, explicitly identified new-episode request."""
    if not isinstance(payload, dict) or set(payload) != {'request_id', 'episode_id', 'issued_at'}:
        raise ValueError('reset request requires request_id, episode_id and issued_at')
    for key in ('request_id', 'episode_id'):
        if not isinstance(payload[key], str):
            raise ValueError(f'{key} must be a UUID string')
    try:
        request_id, episode_id = (str(uuid.UUID(payload[key])) for key in ('request_id', 'episode_id'))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError('reset request identifiers must be UUIDs') from error
    issued = payload['issued_at']
    if isinstance(issued, bool) or not isinstance(issued, (float, int)) or not math.isfinite(issued):
        raise ValueError('reset request issued_at must be finite wall time')
    return {'request_id': request_id, 'episode_id': episode_id, 'issued_at': float(issued)}


def reset_result(request, *, episode_id=None, reset_stamp=None, message=''):
    return {'request_id': request['request_id'], 'episode_id': request['episode_id'],
            'status': 'succeeded' if episode_id is not None else 'failed',
            'new_episode_id': episode_id, 'reset_stamp': reset_stamp, 'message': str(message)}


class ResetRequests:
    """Bounded request mailbox and receipts; callbacks never reset MuJoCo."""
    def __init__(self):
        self.pending = deque()
        self.pending_ids = set()
        self.results = OrderedDict()

    def offer(self, payload, now=None):
        request = reset_request(payload)
        identity = request['request_id']
        if identity in self.results:
            return dict(self.results[identity])
        if identity in self.pending_ids:
            return None
        now = time.time() if now is None else now
        if not 0 <= now-request['issued_at'] <= 5:
            return self.finish(request, reset_result(request, message='reset request expired or in the future'))
        if len(self.pending) >= 4:
            return self.finish(request, reset_result(request, message='reset request queue is busy'))
        self.pending.append(request)
        self.pending_ids.add(identity)
        return None

    def take(self):
        if not self.pending:
            return None
        request = self.pending.popleft()
        self.pending_ids.discard(request['request_id'])
        return request

    def finish(self, request, result):
        self.results[request['request_id']] = dict(result)
        while len(self.results) > 64:
            self.results.popitem(last=False)
        return dict(result)


def latest_sensor_qos():
    """Use standard sensor semantics with one replaceable, volatile sample."""
    from rclpy.qos import qos_profile_sensor_data
    profile = copy.copy(qos_profile_sensor_data)
    profile.depth = 1
    return profile


class LoopTiming:
    """Bounded observations without control decisions.

    Stage totals are inclusive wall time. Nested stages overlap; their totals
    cannot be added into elapsed time or interpreted as CPU time.
    """
    STAGES = ('spin_once', 'command_apply', 'mj_step', 'publish', 'snapshot_refresh',
              'clock_publish', 'joint_publish', 'odom_publish', 'tf_publish',
              'truth_publish', 'cargo_publish', 'imu_publish', 'state_publish',
              'record_write', 'record_flush', 'scan', 'scan_publish',
              'beacon_publish', 'frame_offer', 'camera_offer', 'lidar_offer')

    def __init__(self, source_time=lambda: None):
        self.source_time = source_time
        self.stats = {name: {'count': 0, 'total_s': 0., 'max_s': 0., 'slow_count': 0} for name in self.STAGES}
        self.slow_tail = deque(maxlen=32)
        self.slow_count = 0

    def observe(self, stage, start, end, source_stamp=None):
        if stage not in self.stats or not all(math.isfinite(t) for t in (start, end)) or end < start:
            raise ValueError('invalid loop timing observation')
        elapsed = end-start
        entry = self.stats[stage]
        entry['count'] += 1
        entry['total_s'] += elapsed
        entry['max_s'] = max(entry['max_s'], elapsed)
        if elapsed >= .1:
            entry['slow_count'] += 1
            self.slow_count += 1
            self.slow_tail.append({'stage': stage, 'start_monotonic': start,
                                   'end_monotonic': end, 'duration_s': elapsed,
                                   'source_stamp': source_stamp})

    def measure(self, stage, function, *args, **kwargs):
        start = time.monotonic()
        try:
            return function(*args, **kwargs)
        finally:
            self.observe(stage, start, time.monotonic(), self.source_time())

    def snapshot(self):
        return {'clock': 'monotonic', 'slow_threshold_s': .1, 'slow_tail_limit': 32,
                'slow_count': self.slow_count, 'slow_events_evicted': max(0, self.slow_count-32),
                'stages': {name: values.copy() for name, values in self.stats.items()},
                'slow_tail': [event.copy() for event in self.slow_tail],
                'causal_verdict': 'observations only'}


class StationBeacon:
    """Reuse the existing relative-beacon math, without its battery runtime.

    Ideal and declared perturbed modes derive geometry from the shared world.
    Vision mode has no simulated observation or truth fallback.
    """
    mapped_pose = PowerModel.mapped_pose
    relative_beacon = PowerModel.relative_beacon

    def __init__(self, identity, scene):
        manifest = identity.get('manifest', {})
        if Path(manifest.get('world_xml', '')).resolve() != Path(scene).resolve():
            raise ValueError('dock beacon requires the compiled scene manifest binding')
        if hashlib.sha256(Path(scene).read_bytes()).hexdigest() != identity['scene_sha256']:
            raise ValueError('dock beacon scene changed after its source snapshot')
        physical_dock = finite_vector(manifest.get('dock_pose', ()), 3, 'manifest dock_pose')
        field = 'native_dock_pose' if 'native_dock_pose' in manifest else 'dock_pose'
        self.world_dock = finite_vector(manifest.get(field, ()), 3, f'manifest {field}')
        if any(abs(a-b)>1e-9 for a,b in zip(self.world_dock[:2], physical_dock[:2])):
            raise ValueError('native dock frame and physical robot target must share the station point')
        self.config = SimpleNamespace(dock_pose=self.world_dock, truth_to_dock_frame=(0., 0., 0.))
        self.perception_config = normalize_config(manifest.get('station_perception'))
        if self.perception_config['station_id'] != manifest.get('native_docking', {}).get('dock_id', 'so101_station'):
            raise ValueError('station perception identity does not match the compiled native dock')
        self.truth = None
        self.description = {
            'topic': STATION_POSE_TOPIC, 'detection_topic': STATION_DETECTION_TOPIC,
            'frame_id': self.perception_config['frame_id'],
            'method': 'independent vision producer required' if self.perception_config['mode'] == 'vision' else BEACON_LABEL,
            'mode': self.perception_config['mode'],
            'idealized_truth_derived': self.perception_config['mode'] != 'vision',
            'rgb_or_apriltag': False,
            'noise_model': 'declared Gaussian noise and bias' if self.perception_config['mode'] == 'perturbed' else 'none',
            'occlusion_model': 'declared episode-relative windows' if self.perception_config.get('occlusion_windows') else 'none',
            'hardware_validated': False,
            'range_limit_m': self.perception_config['range_limit_m'], 'publish_hz_source_time': 50,
            'world_dock': list(self.world_dock), 'scene_sha256': identity['scene_sha256'],
            'world_dock_source_field': field, 'physical_robot_dock_pose': list(physical_dock),
            'orientation_semantics': 'native dock face, not necessarily the final robot heading',
            'manifest_sha256': identity.get('manifest_sha256'),
            'reused_source': 'fishbot_sim_power.py',
            'reused_source_sha256': hashlib.sha256(
                Path(__file__).with_name('fishbot_sim_power.py').read_bytes()).hexdigest()}
        self.begin_episode(identity.get('episode_id') or str(uuid.uuid4()), 0.)

    def begin_episode(self, episode_id, source_stamp):
        self.episode_id = episode_id
        self.episode_start, = finite_vector((source_stamp,), 1, 'perception episode start')
        self.sequence = 0
        self.rng = random.Random(self.perception_config.get('seed', 0))
        self.last_observation = None
        self.truth = None

    def sample(self, car_pose, source_stamp):
        """Sample once per source stamp; reading state never advances this RNG."""
        if self.perception_config['mode'] == 'vision':
            return None
        source_stamp, = finite_vector((source_stamp,), 1, 'perception source stamp')
        previous = self.last_observation
        if previous is not None:
            if source_stamp < previous['stamp']:
                raise ValueError('perception source time moved backwards within the episode')
            if source_stamp == previous['stamp']:
                return copy.deepcopy(previous)
        self.sequence += 1
        relative = self.measure(car_pose, source_stamp)
        detected = relative is not None
        reason = 'detected' if detected else ('invalid_source_stamp' if source_stamp <= 0 else 'out_of_range')
        in_range = detected
        config = self.perception_config
        elapsed = source_stamp-self.episode_start
        if detected and any(start <= elapsed < end for start, end in config.get('occlusion_windows', [])):
            detected, reason = False, 'occluded'
        if detected and config['mode'] == 'perturbed' and self.rng.random() < config['dropout_probability']:
            detected, reason = False, 'dropout'
        covariance = [0.]*36
        variances = [.0001]*3
        if config['mode'] == 'perturbed':
            variances = [.0001+std**2 for std in config['noise_std']]
            if detected:
                relative = tuple(value+bias+self.rng.gauss(0., std)
                                 for value, bias, std in zip(relative, config['bias'], config['noise_std']))
                relative = (*relative[:2], math.atan2(math.sin(relative[2]), math.cos(relative[2])))
        for index, variance in zip((0, 7, 35), variances):
            covariance[index] = variance
        self.last_observation = {
            'schema': 1, 'publisher': config['publisher'], 'mode': config['mode'],
            'station_id': config['station_id'], 'frame_id': config['frame_id'],
            'scene_sha256': self.description['scene_sha256'],
            'manifest_sha256': self.description['manifest_sha256'],
            'episode_id': self.episode_id, 'sequence': self.sequence,
            'stamp': source_stamp, 'detected': detected,
            'confidence': 1. if detected else 0., 'reason': reason,
            'idealized_truth_derived': True, 'in_range': in_range,
            'relative': list(relative) if detected else None,
            'covariance': covariance if detected else None,
            'episode_elapsed_s': elapsed}
        return copy.deepcopy(self.last_observation)

    def status(self):
        """Return the latest sample without geometry reads or random draws."""
        observed = self.last_observation or {}
        return {**self.description, 'in_range': observed.get('in_range', False),
                'source_stamp': observed.get('stamp'), 'sequence': self.sequence,
                'episode_id': self.episode_id, 'episode_start': self.episode_start,
                'seed_reset_per_episode': self.perception_config['mode'] == 'perturbed',
                'observation': copy.deepcopy(self.last_observation),
                'reason': observed.get('reason', 'awaiting_external_producer' if self.perception_config['mode'] == 'vision' else 'not_sampled')}

    def measure(self, car_pose, source_stamp):
        x, y, yaw = finite_vector(car_pose, 3, 'beacon car pose')
        source_stamp, = finite_vector((source_stamp,), 1, 'beacon source stamp')
        if source_stamp <= 0 or math.hypot(self.world_dock[0]-x, self.world_dock[1]-y) > self.perception_config['range_limit_m']:
            return None
        self.truth = Truth(source_stamp, time.monotonic(), x, y, yaw, 0., 0., 0.)
        return finite_vector(self.relative_beacon(), 3, 'relative dock beacon')


def station_messages(observation):
    """Build paired standard ROS messages, or diagnostics alone for a miss."""
    from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
    from geometry_msgs.msg import PoseWithCovarianceStamped
    detection = DiagnosticArray()
    detection.header.frame_id = observation['frame_id']
    seconds, nanoseconds = divmod(int(round(observation['stamp']*1_000_000_000)), 1_000_000_000)
    detection.header.stamp.sec, detection.header.stamp.nanosec = seconds, nanoseconds
    status = DiagnosticStatus()
    status.name, status.hardware_id = DIAGNOSTIC_NAME, observation['station_id']
    status.level = DiagnosticStatus.OK if observation['detected'] else DiagnosticStatus.WARN
    status.message = observation['reason']
    keys = ('schema', 'publisher', 'mode', 'station_id', 'scene_sha256', 'manifest_sha256',
            'episode_id', 'sequence', 'detected', 'confidence', 'reason', 'idealized_truth_derived')
    status.values = [KeyValue(key=key, value=(str(observation[key]).lower()
                     if isinstance(observation[key], bool) else str(observation[key]))) for key in keys]
    detection.status = [status]
    pose = None
    if observation['detected']:
        pose = PoseWithCovarianceStamped()
        pose.header = copy.deepcopy(detection.header)
        x, y, yaw = observation['relative']
        pose.pose.pose.position.x, pose.pose.pose.position.y = x, y
        pose.pose.pose.orientation.z, pose.pose.pose.orientation.w = math.sin(yaw/2), math.cos(yaw/2)
        pose.pose.covariance = observation['covariance']
    return pose, detection


def finite_vector(values, length, label):
    result = tuple(float(x) for x in values)
    if len(result) != length or not all(math.isfinite(x) for x in result):
        raise ValueError(f'{label} requires {length} finite values')
    return result


def arm_reference(names, positions, limits):
    """Require exactly the six model joints; reject malformed input atomically."""
    if len(names) != 6 or len(set(names)) != 6 or set(names) != set(ARM_JOINTS):
        raise ValueError('arm reference must name exactly the six SO101 joints')
    values = dict(zip(names, finite_vector(positions, 6, 'arm reference')))
    result = tuple(values[name] for name in ARM_JOINTS)
    for name, value, (low, high) in zip(ARM_JOINTS, result, limits):
        if not low <= value <= high:
            raise ValueError(f'{name} reference outside model joint range')
    return result


def unique_arm_publisher(publishers, expected_name):
    if len(publishers) != 1 or publishers[0].node_name != expected_name:
        raise ValueError(f'arm reference requires the unique {expected_name} publisher')


class CallbackInbox:
    """Receive on an executor thread; apply only at the physics boundary."""
    def __init__(self):
        self.pending = queue.SimpleQueue()

    def callback(self, function, *, with_received_time=False):
        def receive(message):
            received = time.monotonic() if with_received_time else None
            self.pending.put((function, message, received))
        return receive

    def drain(self):
        while True:
            try:
                function, message, received = self.pending.get_nowait()
            except queue.Empty:
                return
            if received is None:
                function(message)
            else:
                function(message, received_at=received)


class WheelCommands:
    """Steady-time watchdog remains active while arm references are held."""
    def __init__(self, *, radius=WHEEL_RADIUS, separation=WHEEL_SEPARATION, mecanum_k=None):
        self.radius, self.separation = radius, separation
        self.mecanum_k = mecanum_k
        self.lateral = 0.
        self.hold = True
        self.last_received = None
        self.linear = self.angular = 0.
        self.source_floor = None

    def accept(self, linear, angular, now, *, source_stamp=None, sim_now=None, lateral=0.):
        linear, angular, now = finite_vector((linear, angular, now), 3, 'car command')
        lateral, = finite_vector((lateral,), 1, 'lateral command')
        if self.source_floor is not None and (source_stamp is None or source_stamp <= self.source_floor):
            self.stop()
            raise ValueError('car command belongs to a previous episode')
        if source_stamp is not None:
            source_stamp, sim_now = finite_vector((source_stamp, sim_now), 2, 'stamp')
            if source_stamp <= 0 or sim_now - source_stamp > COMMAND_TIMEOUT or source_stamp - sim_now > .10:
                self.stop()
                raise ValueError('stamped car command is stale or in the future')
        self.linear = max(-.25, min(.25, linear))
        self.angular = max(-1.5, min(1.5, angular))
        self.lateral = max(-.25, min(.25, lateral))
        self.last_received = now

    def stop(self):
        self.linear = self.angular = self.lateral = 0.
        self.last_received = None

    def set_hold(self, hold):
        # Release requires a newly received command; queued motion cannot resume.
        self.hold = bool(hold)
        self.stop()

    def begin_episode(self, source_stamp):
        self.source_floor, = finite_vector((source_stamp,), 1, 'episode command floor')
        self.set_hold(True)

    def velocities(self, now):
        if self.mecanum_k is not None:
            from cooperation_mecanum import inverse
            if self.hold or self.last_received is None or not 0 <= now-self.last_received <= COMMAND_TIMEOUT:
                return (0.,)*4
            return inverse(self.linear, self.lateral, self.angular, self.radius, self.mecanum_k)
        if self.hold or self.last_received is None or not 0 <= now-self.last_received <= COMMAND_TIMEOUT:
            return 0., 0.
        return ((self.linear-self.angular*self.separation/2)/self.radius,
                (self.linear+self.angular*self.separation/2)/self.radius)


class EncoderOdometry:
    """Integrate the wheel axle, then transform to the fixed foot origin."""
    def __init__(self, left=0., right=0., *, axle_offset=(0., 0.),
                 radius=WHEEL_RADIUS, separation=WHEEL_SEPARATION):
        self.radius, self.separation = radius, separation
        self.left, self.right = left, right
        if len(axle_offset) != 2 or not all(math.isfinite(x) for x in axle_offset):
            raise ValueError('axle offset must be a finite planar vector')
        self.axle_offset = tuple(float(x) for x in axle_offset)
        # Odom initially coincides with the foot; its wheel axle is offset.
        self.axle_x, self.axle_y = self.axle_offset
        self.x = self.y = self.yaw = 0.
        self.lateral_velocity = 0.

    def update(self, left, right, dt):
        dl, dr = (left-self.left)*self.radius, (right-self.right)*self.radius
        self.left, self.right = left, right
        distance = (dl+dr)/2
        angle = (dr-dl)/self.separation
        self.axle_x += distance*math.cos(self.yaw+angle/2)
        self.axle_y += distance*math.sin(self.yaw+angle/2)
        self.yaw = math.atan2(math.sin(self.yaw+angle), math.cos(self.yaw+angle))
        a, b = self.axle_offset
        self.x = self.axle_x-a*math.cos(self.yaw)+b*math.sin(self.yaw)
        self.y = self.axle_y-a*math.sin(self.yaw)-b*math.cos(self.yaw)
        angular = angle/dt if dt > 0 else 0.
        self.lateral_velocity = -angular*a
        return (distance/dt+angular*b, angular) if dt > 0 else (0., 0.)


def compiled_axle_offset(model, left_joints=None, right_joints=None):
    """Read fixed encoder geometry in a separate reset-only kinematic data."""
    import mujoco
    import numpy as np
    geometry = mujoco.MjData(model)
    mujoco.mj_kinematics(model, geometry)
    foot = model.body('base_footprint').id
    local = geometry.xmat[foot].reshape(3, 3).T
    groups = (left_joints or WHEEL_JOINTS[:1], right_joints or WHEEL_JOINTS[1:])
    anchors = [np.mean([local @ (geometry.xanchor[model.joint(name).id]-geometry.xpos[foot])
                        for name in group], axis=0) for group in groups]
    if not np.isfinite(anchors).all() or any(abs(anchors[0][i]-anchors[1][i]) > 1e-9 for i in (0, 2)):
        raise ValueError('wheel anchors must form a finite lateral axle in the foot frame')
    return tuple(float(x) for x in (anchors[0]+anchors[1])/2)


class DockApproachGuard:
    """Ideal plant velocity protection; it does not implement dock success."""
    def __init__(self, dock_pose):
        if len(dock_pose) != 3 or not all(math.isfinite(x) for x in dock_pose):
            raise ValueError('physical dock pose must be finite x/y/yaw')
        self.dock_pose = tuple(float(x) for x in dock_pose)
        self.enabled = self.tripped = False
        self.along_m = 0.
        self.margin_m = .01

    def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('docking guard requires a Bool enable')
        self.enabled = enabled
        if not enabled:
            self.tripped = False

    def update(self, foot_position):
        if len(foot_position) < 2 or not all(math.isfinite(x) for x in foot_position[:2]):
            raise ValueError('foot origin must be finite')
        x, y, heading = self.dock_pose
        self.along_m = ((float(foot_position[0])-x)*math.cos(heading)
                        +(float(foot_position[1])-y)*math.sin(heading))
        if self.enabled and self.along_m <= self.margin_m:
            self.tripped = True
        return self.enabled and self.tripped

    def state(self):
        return {'enabled': self.enabled, 'tripped': self.tripped,
                'along_m': self.along_m, 'margin_m': self.margin_m,
                'dock_pose': list(self.dock_pose), 'frame': 'world',
                'body_origin': 'base_footprint', 'method': 'ideal plant velocity guard',
                'hardware_validated': False}


def descendants(model, root):
    found = {int(root)}
    for body in range(model.nbody):
        parent = int(model.body_parentid[body])
        if body != root and parent in found:
            found.add(body)
    return found


def source_identity(scene, manifest=None):
    """Record compiled inputs without publishing machine-specific absolute paths."""
    scene = Path(scene).resolve()
    identity = {'scene_name': scene.name, 'scene_sha256': hashlib.sha256(scene.read_bytes()).hexdigest()}
    manifest_path = Path(manifest).resolve() if manifest is not None else scene.with_name('scene-manifest.json')
    if manifest is not None or manifest_path.is_file():
        payload = manifest_path.read_bytes()
        identity['manifest_sha256'] = hashlib.sha256(payload).hexdigest()
        identity['manifest'] = json.loads(payload)
    return identity


class Physics:
    def __init__(self, scene, *, manifest=None):
        import mujoco
        import numpy as np
        self.mj, self.np = mujoco, np
        self.scene = Path(scene).resolve()
        self.model = mujoco.MjModel.from_xml_path(str(self.scene))
        self.data = mujoco.MjData(self.model)
        self.identity = source_identity(self.scene, manifest)
        profile = self.identity.get('manifest', {}).get('vehicle_profile', {})
        self.left_wheel_names = tuple(profile.get('left_wheel_joints', WHEEL_JOINTS[:1]))
        self.right_wheel_names = tuple(profile.get('right_wheel_joints', WHEEL_JOINTS[1:]))
        self.wheel_joint_names = self.left_wheel_names + self.right_wheel_names
        self.wheel_radius = float(profile.get('wheel_radius_m', WHEEL_RADIUS))
        self.wheel_separation = float(profile.get('wheel_separation_m', WHEEL_SEPARATION))
        self.track_multiplier = float(profile.get('drive', {}).get('effective_track_multiplier', 1.))
        self.mecanum_k = (float(profile['drive']['kinematic_k_m'])
                          if profile.get('drive', {}).get('type') == 'mecanum_x' else None)
        self.effective_wheel_separation = self.wheel_separation*self.track_multiplier
        self.localization_enabled = profile.get('localization', {}).get('enabled', False) is True
        if abs(self.model.opt.timestep-.002) > 1e-12:
            raise ValueError('cooperation scene must use 500 Hz physics')
        self.arm_joint_ids = [self.model.joint(name).id for name in ARM_JOINTS]
        self.arm_q = [int(self.model.jnt_qposadr[i]) for i in self.arm_joint_ids]
        self.arm_v = [int(self.model.jnt_dofadr[i]) for i in self.arm_joint_ids]
        self.arm_a = [self.model.actuator(name).id for name in ARM_JOINTS]
        self.wheel_joint_ids = [self.model.joint(name).id for name in self.wheel_joint_names]
        self.wheel_q = [int(self.model.jnt_qposadr[i]) for i in self.wheel_joint_ids]
        self.wheel_v = [int(self.model.jnt_dofadr[i]) for i in self.wheel_joint_ids]
        self.wheel_a = [self.model.actuator(name).id for name in self.wheel_joint_names]
        split = len(self.left_wheel_names)
        self.left_wheel_q, self.right_wheel_q = self.wheel_q[:split], self.wheel_q[split:]
        self.arm_limits = [tuple(self.model.jnt_range[i]) for i in self.arm_joint_ids]
        self.car_body = self.model.body('base_footprint').id
        car_free = self.model.joint('base_free_joint').id
        if (self.model.jnt_bodyid[car_free] != self.car_body or self.model.body_parentid[self.car_body] != 0
                or self.model.jnt_type[car_free] != mujoco.mjtJoint.mjJNT_FREE):
            raise ValueError('car freejoint must describe the world foot origin')
        self.car_free_q = int(self.model.jnt_qposadr[car_free])
        self.laser_body = self.model.body('laser_link').id
        self.cargo_body = self.model.body('grasp_target').id
        self.cargo_geom = self.model.geom('target_collision').id
        self.finger_geoms = {name: self.model.geom(name).id for name in ('pad_gripper', 'pad_moving_jaw')}
        self.tray_floor = self.model.geom('place_floor').id
        self.tray_body = self.model.body('cargo_tray').id
        self.arm_bodies = descendants(self.model, self.model.body('base').id)
        self.car_bodies = descendants(self.model, self.car_body)
        self.arm_geoms = {i for i in range(self.model.ngeom) if int(self.model.geom_bodyid[i]) in self.arm_bodies}
        self.excluded = set()
        for node in ET.parse(self.scene).getroot().findall('./contact/exclude'):
            self.excluded.add(frozenset((node.get('body1'), node.get('body2'))))
        # Descriptive compiled geometry is immutable within this scene. Forces
        # and distances below still come from every current native contact.
        self.contact_geom_names = tuple(self.model.geom(i).name for i in range(self.model.ngeom))
        self.contact_body_names = tuple(self.model.body(i).name for i in range(self.model.nbody))
        self.contact_geom_bodyids = tuple(map(int, self.model.geom_bodyid))
        self.contact_planes = tuple(value == self.mj.mjtGeom.mjGEOM_PLANE for value in self.model.geom_type)
        # Ray groups do not modify contact geometry or forces. Exclude all car
        # descendants and decorative geoms, preserving arm/worktable obstacles.
        for geom in range(self.model.ngeom):
            if int(self.model.geom_bodyid[geom]) in self.car_bodies:
                self.model.geom_group[geom] = 5
            elif not (self.model.geom_contype[geom] or self.model.geom_conaffinity[geom]):
                self.model.geom_group[geom] = 4
        self.ray_groups = np.array([1, 1, 1, 1, 0, 0], dtype=np.uint8)
        angles = np.arange(360)*math.pi/180
        self.ray_directions = np.column_stack((np.cos(angles), np.sin(angles), np.zeros(360)))
        self.episode_id = str(uuid.uuid4())
        self.identity['episode_id'] = self.episode_id
        from cooperation_faults import FaultInjector, normalize_fault_config
        self.observation_faults = FaultInjector(
            normalize_fault_config(self.identity.get('manifest', {}).get('observation_faults')),
            identity={key: self.identity[key] for key in ('scene_sha256', 'manifest_sha256')})
        self.observation_faults.begin_episode(self.episode_id)
        self.station_beacon = StationBeacon(self.identity, self.scene)
        self.docking_guard = DockApproachGuard(self.identity['manifest']['dock_pose'])
        mujoco.mj_resetData(self.model, self.data)
        if self.model.nkey:
            mujoco.mj_resetDataKeyframe(self.model, self.data, 0)
        initial = self.identity.get('manifest', {}).get('initial_arm_q6')
        if initial is not None:
            self.data.qpos[self.arm_q] = arm_reference(ARM_JOINTS, initial, self.arm_limits)
        self.reference = tuple(float(self.data.qpos[i]) for i in self.arm_q)
        self.data.ctrl[self.arm_a] = self.reference
        mujoco.mj_forward(self.model, self.data)
        self.initial_qpos = self.data.qpos.copy()
        self.initial_reference = self.reference
        self.wheels = WheelCommands(radius=self.wheel_radius, separation=self.effective_wheel_separation, mecanum_k=self.mecanum_k)
        self.encoder_axle_offset = compiled_axle_offset(self.model, self.left_wheel_names, self.right_wheel_names)
        if self.mecanum_k is not None:
            from cooperation_mecanum import MecanumOdometry
            self.odom = MecanumOdometry(*self.wheel_encoder_positions(), radius=self.wheel_radius, k=self.mecanum_k)
        else:
            self.odom = EncoderOdometry(*self.wheel_encoder_positions(), axle_offset=self.encoder_axle_offset[:2],
                                        radius=self.wheel_radius, separation=self.effective_wheel_separation)
        self.odom_linear = self.odom_angular = 0.
        self.total_forbidden_steps = self.total_forbidden_contacts = 0
        self.total_car_forbidden_steps = self.total_car_forbidden_contacts = 0
        self.max_normal_forces = {name: 0. for name in self.finger_geoms}
        self.contacts = self.contact_state()
        self.docking_guard.update(self.data.qpos[self.car_free_q:self.car_free_q+2])
        self.last_wall = time.time()
        self.steps = 0
        self.scan_sequence = self.state_sequence = 0
        self.reset_count = 0
        self.reset_stamp = None
        self.native_actions_busy = False
        self.reset_quiet = ContinuousEvidence(.7)
        self.reset_ready = False

    def set_arm_reference(self, names, positions, *, source_stamp=None):
        if self.reset_stamp is not None:
            if (source_stamp is None or not math.isfinite(source_stamp)
                    or source_stamp <= self.reset_stamp
                    or not -.1 <= float(self.data.time)-source_stamp <= COMMAND_TIMEOUT):
                raise ValueError('arm reference belongs to a previous episode or has an invalid stamp')
        validated = arm_reference(names, positions, self.arm_limits)
        self.reference = validated

    def reset_physical_quiet(self):
        car, cargo = self.body_velocity(self.car_body), self.body_velocity(self.cargo_body)
        quiet = (self.wheels.hold and not self.docking_guard.enabled and not self.docking_guard.tripped
                 and not self.native_actions_busy
                 and math.hypot(*car[3:5]) < .01 and abs(car[2]) < .01
                 and self.np.linalg.norm(self.data.qvel[self.arm_v]) < .05
                 and self.np.linalg.norm(cargo[3:]) < .005 and self.np.linalg.norm(cargo[:3]) < .05
                 and self.np.max(self.np.abs(self.data.ctrl[self.wheel_a])) < 1e-9)
        return bool(quiet)

    def observe_reset_quiet(self):
        self.reset_ready = self.reset_quiet.update(float(self.data.time), self.reset_physical_quiet())

    def reset_episode(self, expected_episode_id):
        """Initialize an explicit, authorized episode boundary, never a task step.

        The unique coordinator supplies terminal-task admission. Independent
        native status plus physical hold/quiet remain plant-side requirements.
        Source time, encoder pose, sequence and global step count do not rewind.
        """
        if expected_episode_id != self.episode_id:
            raise ValueError('reset expected episode does not match the current world')
        if (not self.reset_ready or self.native_actions_busy or not self.wheels.hold
                or self.docking_guard.enabled or self.docking_guard.tripped):
            self.reset_ready = False
            self.reset_quiet = ContinuousEvidence(.7)
            raise ValueError('reset requires held, native-terminal, continuously quiet physics')
        # Recheck the current plant, even if readiness was earned earlier.
        self.refresh_snapshot()
        if not self.reset_physical_quiet():
            self.reset_ready = False
            self.reset_quiet = ContinuousEvidence(.7)
            raise ValueError('physical reset readiness changed')
        preserved_time = float(self.data.time)
        self.mj.mj_resetData(self.model, self.data)
        self.data.qpos[:] = self.initial_qpos
        self.data.time = preserved_time
        self.reference = self.initial_reference
        self.data.ctrl[self.arm_a] = self.reference
        self.data.ctrl[self.wheel_a] = 0.
        self.wheels.begin_episode(preserved_time)
        self.docking_guard.set_enabled(False)
        # Wheel positions restart with the model. Rebase only the encoder's
        # wheel-reading baseline; preserve its independent integrated pose.
        if self.mecanum_k is not None:
            self.odom.rebase(self.wheel_encoder_positions())
        else:
            self.odom.left, self.odom.right = self.wheel_encoder_positions()
        self.odom.lateral_velocity = self.odom_linear = self.odom_angular = 0.
        self.total_forbidden_steps = self.total_forbidden_contacts = 0
        self.total_car_forbidden_steps = self.total_car_forbidden_contacts = 0
        self.max_normal_forces = {name: 0. for name in self.finger_geoms}
        self.episode_id = str(uuid.uuid4())
        self.identity = {**self.identity, 'episode_id': self.episode_id}
        self.station_beacon.begin_episode(self.episode_id, preserved_time)
        self.observation_faults.begin_episode(self.episode_id)
        self.reset_count += 1
        self.reset_stamp = preserved_time
        self.reset_quiet = ContinuousEvidence(.7)
        self.reset_ready = False
        self.last_wall = time.time()
        self.refresh_snapshot()
        self.docking_guard.update(self.data.qpos[self.car_free_q:self.car_free_q+2])
        return self.episode_id, preserved_time

    def step(self):
        self.data.ctrl[self.arm_a] = self.reference
        velocities = self.wheels.velocities(time.monotonic())
        self.data.ctrl[self.wheel_a] = (velocities if self.mecanum_k is not None else
                                      [velocities[0]]*len(self.left_wheel_q) + [velocities[1]]*len(self.right_wheel_q))
        for actuator in self.wheel_a:
            low, high = self.model.actuator_ctrlrange[actuator]
            self.data.ctrl[actuator] = max(low, min(high, self.data.ctrl[actuator]))
        if self.docking_guard.update(self.data.qpos[self.car_free_q:self.car_free_q+2]):
            self.data.ctrl[self.wheel_a] = 0.
        self.mj.mj_step(self.model, self.data)
        self.steps += 1
        self.last_wall = time.time()
        if not (all(self.np.isfinite(value).all() for value in
                    (self.data.qpos, self.data.qvel, self.data.ctrl, self.data.sensordata,
                     self.data.xpos, self.data.xquat)) and math.isfinite(self.data.time)):
            self.wheels.set_hold(True)
            self.data.ctrl[self.wheel_a] = 0.
            raise RuntimeError('nonfinite MuJoCo state; car hold latched')
        if self.docking_guard.update(self.data.qpos[self.car_free_q:self.car_free_q+2]):
            self.data.ctrl[self.wheel_a] = 0.
        self.odom_linear, self.odom_angular = self.odom.update(
            *self.wheel_encoder_positions(), float(self.model.opt.timestep))
        self.contacts = self.contact_state()
        self.observe_reset_quiet()

    def wheel_encoder_positions(self):
        """Mecanum keeps four readings; differential/skid averages each side."""
        if getattr(self, 'mecanum_k', None) is not None:
            return tuple(float(self.data.qpos[i]) for i in self.wheel_q)
        return tuple(sum(float(self.data.qpos[i]) for i in group)/len(group)
                     for group in (self.left_wheel_q, self.right_wheel_q))

    def body_velocity(self, body):
        velocity = self.np.zeros(6)
        # State positions use xpos (the body frame origin), not xipos (COM).
        # This also works for massless parent bodies such as base_footprint.
        self.mj.mj_objectVelocity(self.model, self.data, self.mj.mjtObj.mjOBJ_XBODY, body, velocity, 0)
        return velocity.tolist()

    def refresh_snapshot(self):
        """Align derived sensors/poses with the integrated state, without stepping.

        mj_step has advanced qpos while some derived fields still describe its
        input state. This forward pass refreshes one published 50 Hz snapshot.
        The 500 Hz contact counters continue to count physics steps only.
        """
        self.mj.mj_forward(self.model, self.data)
        self.contacts = self.contact_state(accumulate=False)

    def contact_state(self, *, accumulate=True):
        normals = {name: 0. for name in self.finger_geoms}
        forbidden, car_forbidden, floor_count, floor_normal = [], [], 0, 0.
        force = self.np.zeros(6)
        for index in range(self.data.ncon):
            contact = self.data.contact[index]
            g1, g2 = int(contact.geom1), int(contact.geom2)
            pair = {g1, g2}
            self.mj.mj_contactForce(self.model, self.data, index, force)
            if not self.np.isfinite(force).all() or not math.isfinite(contact.dist):
                self.wheels.set_hold(True)
                raise RuntimeError('nonfinite contact evidence; car hold latched')
            normal = max(0., float(force[0]))
            if self.cargo_geom in pair:
                for name, geom in self.finger_geoms.items():
                    if geom in pair:
                        normals[name] += normal
                if self.tray_floor in pair:
                    floor_count += 1
                    floor_normal += normal
            b1, b2 = self.contact_geom_bodyids[g1], self.contact_geom_bodyids[g2]
            geom_names = self.contact_geom_names[g1], self.contact_geom_names[g2]
            # The car may touch the arena floor and carry cargo. Any other
            # external collision remains independent evidence, including bench.
            car_external = (b1 in self.car_bodies) != (b2 in self.car_bodies)
            if (car_external and self.cargo_geom not in pair and normal > 1e-8
                    and not any(self.contact_planes[g] for g in pair)):
                car_forbidden.append({'geom1': geom_names[0], 'geom2': geom_names[1],
                                      'normal_force_n': normal, 'distance_m': float(contact.dist)})
            if not pair & self.arm_geoms:
                continue
            # Only the pads may touch the cargo. Other arm/cargo contact fails.
            if self.cargo_geom in pair and pair & set(self.finger_geoms.values()):
                continue
            body_names = self.contact_body_names[b1], self.contact_body_names[b2]
            if frozenset(body_names) in self.excluded:
                continue
            # The fixed base is mounted on its table/plate by construction.
            if 'base' in body_names and any(name in ('worktable', 'robot_mount_plate') for name in geom_names):
                continue
            if normal > 1e-8:
                forbidden.append({'geom1': geom_names[0], 'geom2': geom_names[1],
                                  'normal_force_n': normal, 'distance_m': float(contact.dist)})
        if accumulate:
            self.total_forbidden_contacts += len(forbidden)
            self.total_forbidden_steps += bool(forbidden)
            self.total_car_forbidden_contacts += len(car_forbidden)
            self.total_car_forbidden_steps += bool(car_forbidden)
            for name, normal in normals.items():
                self.max_normal_forces[name] = max(self.max_normal_forces[name], normal)
        return {'finger_normal_forces_n': normals, 'finger_peak_normal_forces_n': dict(self.max_normal_forces),
                'cargo_tray_floor_contact': floor_count > 0, 'cargo_tray_floor_contacts': floor_count,
                'cargo_tray_floor_normal_force_n': floor_normal, 'arm_forbidden_contacts': forbidden,
                'arm_forbidden_contact_count': len(forbidden),
                'arm_forbidden_contact_total': self.total_forbidden_contacts,
                'arm_forbidden_contact_steps': self.total_forbidden_steps,
                'car_forbidden_contacts': car_forbidden,
                'car_forbidden_contact_count': len(car_forbidden),
                'car_forbidden_contact_total': self.total_car_forbidden_contacts,
                'car_forbidden_contact_steps': self.total_car_forbidden_steps}

    def state(self):
        car_velocity, cargo_velocity = self.body_velocity(self.car_body), self.body_velocity(self.cargo_body)
        tray_position = self.data.xpos[self.tray_body]
        tray_rotation = self.data.xmat[self.tray_body].reshape(3, 3)
        tray_velocity = self.body_velocity(self.tray_body)
        cargo_offset = self.data.xpos[self.cargo_body] - tray_position
        # Relative velocity includes tray angular motion at the cargo location.
        cargo_relative_velocity = tray_rotation.T @ (
            self.np.array(cargo_velocity[3:])-self.np.array(tray_velocity[3:])
            -self.np.cross(self.np.array(tray_velocity[:3]), cargo_offset))
        payload = {'schema': 1, 'stamp': float(self.data.time), 'wall_time': self.last_wall,
                   'episode_id': self.episode_id,
                   'episode_reset': {'count': self.reset_count, 'stamp': self.reset_stamp,
                       'ready': self.reset_ready, 'native_actions_busy': self.native_actions_busy,
                       'source_clock_continuous': True, 'encoder_odometry_continuous': True},
                   'sequence': self.state_sequence, 'physics_steps': self.steps, 'physics_hz': 500,
                   'q6': self.data.qpos[self.arm_q].tolist(), 'qvel6': self.data.qvel[self.arm_v].tolist(),
                   'qpos22': self.data.qpos.tolist(), 'qvel20': self.data.qvel.tolist(),
                   'qpos': self.data.qpos.tolist(), 'qvel': self.data.qvel.tolist(),
                   'ctrl': self.data.ctrl.tolist(), 'time_s': float(self.data.time),
                   'car_hold': self.wheels.hold,
                   'docking_guard': self.docking_guard.state(),
                   'encoder_odometry_geometry': {'child_frame_id': 'base_footprint',
                       'drive_type': 'mecanum_x' if self.mecanum_k is not None else 'differential_or_skid',
                       'mecanum_k_m': self.mecanum_k,
                       'axle_offset_in_foot': list(self.encoder_axle_offset),
                       'source': 'compiled reset wheel hinge anchors; runtime wheel encoders only',
                       'wheel_radius_m': self.wheel_radius, 'wheel_separation_m': self.wheel_separation,
                       'effective_track_multiplier': self.track_multiplier,
                       'effective_wheel_separation_m': self.effective_wheel_separation,
                       'left_wheel_joints': list(self.left_wheel_names),
                       'right_wheel_joints': list(self.right_wheel_names),
                       'odom_topic': '/wheel/odom' if self.localization_enabled else '/odom',
                       'odom_tf_published_by_physics': not self.localization_enabled},
                   'arm_reference_q6': list(self.reference), 'arm_joint_names': list(ARM_JOINTS),
                   'car': {'position': self.data.xpos[self.car_body].tolist(),
                           'quaternion_wxyz': self.data.xquat[self.car_body].tolist(),
                           'velocity_world_angular_linear': car_velocity,
                           'speed': math.hypot(car_velocity[3], car_velocity[4]),
                           'yaw_rate': car_velocity[2], 'hold': self.wheels.hold,
                           'command_age_s': (None if self.wheels.last_received is None else
                                             max(0., time.monotonic()-self.wheels.last_received))},
                   'cargo': {'position': self.data.xpos[self.cargo_body].tolist(),
                             'quaternion_wxyz': self.data.xquat[self.cargo_body].tolist(),
                             'velocity_world_angular_linear': cargo_velocity,
                             'position_relative_tray': (tray_rotation.T @ cargo_offset).tolist(),
                             'velocity_relative_tray': cargo_relative_velocity.tolist()},
                   'tray': {'position': tray_position.tolist(),
                            'rotation_world': tray_rotation.tolist(),
                            'quaternion_wxyz': self.data.xquat[self.tray_body].tolist(),
                            'floor_top_world': (self.data.geom_xpos[self.tray_floor]+
                                self.data.geom_xmat[self.tray_floor].reshape(3, 3) @
                                self.np.array([0., 0., self.model.geom_size[self.tray_floor, 2]])).tolist(),
                            'velocity_world_angular_linear': tray_velocity},
                   'finite': True, 'source': self.identity,
                   'dock_beacon': self.station_beacon.status()}
        payload.update(self.contacts)
        self.state_sequence += 1
        return payload

    def beacon(self):
        observation = self.observe_station()
        return None if observation is None else observation['relative']

    def observe_station(self):
        w, x, y, z = map(float, self.data.xquat[self.car_body])
        yaw = math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z))
        return self.station_beacon.sample(
            (*map(float, self.data.xpos[self.car_body][:2]), yaw), float(self.data.time))

    def scan(self, count=360, range_min=.12, range_max=3.5):
        if count != 360:
            raise ValueError('scan contract requires 360 beams')
        origin = self.data.xpos[self.laser_body].copy()
        orientation = self.data.xmat[self.laser_body].reshape(3, 3)
        directions = (self.ray_directions @ orientation.T).reshape(-1)
        hit = self.np.empty(count, dtype=self.np.int32)
        distances = self.np.empty(count, dtype=float)
        self.mj.mj_multiRay(self.model, self.data, origin, directions,
                            self.ray_groups, 1, -1, hit, distances, count, range_max)
        distances[(distances < range_min) | (distances > range_max)] = math.inf
        self.scan_sequence += 1
        return distances.tolist()


class FrameWriter:
    """A separate render model consumes snapshots; physics never waits for GL."""
    def __init__(self, physics, directory, fps, camera):
        self.physics, self.directory = physics, Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.fps, self.camera = fps, camera
        self.pending = None
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self.run, name='cooperation-render', daemon=True)
        self.thread.start()

    def offer(self):
        snapshot = (self.physics.data.qpos.copy(), float(self.physics.data.time), time.time(),
                    self.physics.episode_id)
        with self.lock:
            self.pending = snapshot

    def reset_episode(self, expected_episode_id):
        # The explicit episode boundary and render commits share this lock.
        # Rendering itself remains outside the lock and uses isolated data.
        with self.lock:
            result = self.physics.reset_episode(expected_episode_id)
            self.pending = None
            return result

    def commit(self, pixels, snapshot):
        from PIL import Image
        _, stamp, wall_time, episode_id = snapshot
        with self.lock:
            if episode_id != self.physics.episode_id:
                return False
            image_file = f'{episode_id}.jpg'
            Image.fromarray(pixels).save(self.directory/'frame-next.jpg', quality=85)
            (self.directory/'frame-next.jpg').replace(self.directory/image_file)
            # Keep the compatibility name, but metadata-aware consumers use
            # the immutable episode basename and cannot cross a reset fence.
            shutil.copyfile(self.directory/image_file, self.directory/'frame-next.jpg')
            (self.directory/'frame-next.jpg').replace(self.directory/'latest.jpg')
            metadata = {'stamp': stamp, 'sim_stamp': stamp, 'wall_time': wall_time,
                        'scene_sha256': self.physics.identity['scene_sha256'], 'episode_id': episode_id,
                        'image_file': image_file}
            (self.directory/'frame-next.json').write_text(json.dumps(metadata))
            (self.directory/'frame-next.json').replace(self.directory/'latest.json')
            return True

    def run(self):
        try:
            import mujoco
            model = mujoco.MjModel.from_xml_path(str(self.physics.scene))
            data = mujoco.MjData(model)
            renderer = mujoco.Renderer(model, height=540, width=960)
            options = mujoco.MjvOption()
            options.geomgroup[:] = 1
            options.flags[mujoco.mjtVisFlag.mjVIS_RANGEFINDER] = False
            try:
                while not self.stop_event.wait(1/self.fps):
                    with self.lock:
                        snapshot, self.pending = self.pending, None
                    if snapshot is None:
                        continue
                    qpos, _, _, _ = snapshot
                    # This is an isolated render-only model, never the physics data.
                    data.qpos[:] = qpos
                    mujoco.mj_forward(model, data)
                    renderer.update_scene(data, camera=self.camera, scene_option=options)
                    self.commit(renderer.render(), snapshot)
            finally:
                renderer.close()
        except Exception as error:
            self.error = f'{type(error).__name__}: {error}'

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=2.)


def run_ros(args):
    # Import after the command sets an isolated domain, before initializing DDS.
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
    from builtin_interfaces.msg import Time
    from geometry_msgs.msg import Twist, TwistStamped, TransformStamped, PoseStamped, PoseWithCovarianceStamped
    from diagnostic_msgs.msg import DiagnosticArray
    from nav_msgs.msg import Odometry
    from rosgraph_msgs.msg import Clock
    from sensor_msgs.msg import Imu, JointState, LaserScan, Image, CameraInfo, PointCloud2
    from std_msgs.msg import Bool, String
    from action_msgs.msg import GoalStatusArray
    from tf2_ros import TransformBroadcaster, StaticTransformBroadcaster
    from cooperation_camera import CameraRenderer, frame_messages, IMAGE_TOPIC, INFO_TOPIC, METADATA_TOPIC, FAULT_TOPIC
    from cooperation_lidar import CloudWorker, configuration as lidar_configuration

    manifest = getattr(args, 'manifest', None)
    physics = Physics(args.scene, manifest=manifest) if manifest is not None else Physics(args.scene)
    timing = LoopTiming(lambda: float(physics.data.time))
    frames = (FrameWriter(physics, args.frame_dir, args.frame_fps, args.camera)
              if args.frame_dir and not getattr(args, 'no_overview_render', False) else None)
    record = None
    timing_record = None
    if args.state_log:
        record = BoundedDiagnosticLog(args.state_log, hz=args.state_log_hz,
            max_bytes=args.state_log_max_bytes, backups=args.state_log_backups)
    if args.timing_log:
        destination = Path(args.timing_log).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        timing_record = os.fdopen(os.open(destination, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600), 'w')

    def stamp(seconds):
        result = Time()
        result.sec = int(seconds)
        result.nanosec = int(round((seconds-result.sec)*1_000_000_000))
        if result.nanosec == 1_000_000_000:
            result.sec += 1
            result.nanosec = 0
        return result

    class Adapter(Node):
        def __init__(self):
            super().__init__('cooperation_physics')
            self.callback_inbox = CallbackInbox() if getattr(args, 'queued_ros_dispatch', False) else None
            self.recording_error_reported = None
            self.sensor_qos = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT)
            self.latest_qos = latest_sensor_qos()
            self.clock_pub = self.create_publisher(Clock, '/clock', self.latest_qos)
            self.scan_pub = self.create_publisher(LaserScan, '/scan', self.sensor_qos)
            self.imu_pub = self.create_publisher(Imu, '/imu', self.sensor_qos)
            self.joint_pub = self.create_publisher(JointState, '/joint_states', 10)
            self.odom_pub = self.create_publisher(Odometry, '/wheel/odom' if physics.localization_enabled else '/odom', 10)
            self.truth_pub = self.create_publisher(Odometry, '/ground_truth/odom', 10)
            self.cargo_pub = self.create_publisher(PoseStamped, '/cooperation/cargo_pose', 10)
            self.lidar = None
            lidar_config = lidar_configuration(physics.identity['manifest'])
            if lidar_config is not None:
                self.points_pub = self.create_publisher(PointCloud2, lidar_config['topic'], self.latest_qos)
                self.raw_points_pub = self.create_publisher(PointCloud2, lidar_config['raw_topic'], self.latest_qos)
                self.points_metadata_pub = self.create_publisher(DiagnosticArray, lidar_config['metadata_topic'], self.latest_qos)
                self.lidar = CloudWorker(physics, lidar_config,
                    lambda points, metadata: (self.points_pub.publish(points), self.points_metadata_pub.publish(metadata)),
                    publish_raw=self.raw_points_pub.publish)
            if physics.station_beacon.perception_config['mode'] != 'vision':
                self.station_pose_pub = self.create_publisher(PoseWithCovarianceStamped, STATION_POSE_TOPIC, self.latest_qos)
                self.station_detection_pub = self.create_publisher(DiagnosticArray, STATION_DETECTION_TOPIC, self.latest_qos)
            self.camera = None
            if physics.station_beacon.perception_config['mode'] == 'vision':
                self.image_pub = self.create_publisher(Image, IMAGE_TOPIC, self.latest_qos)
                self.camera_info_pub = self.create_publisher(CameraInfo, INFO_TOPIC, self.latest_qos)
                self.camera_metadata_pub = self.create_publisher(DiagnosticArray, METADATA_TOPIC, self.latest_qos)
                def camera_publish(pixels, snapshot):
                    for publisher, message in zip((self.image_pub, self.camera_info_pub, self.camera_metadata_pub),
                                                  frame_messages(pixels, snapshot, physics.identity['manifest']['station_camera'])):
                        publisher.publish(message)
                directory = Path(args.frame_dir).parent/'vision' if args.frame_dir else args.scene.parent/'vision'
                self.camera = CameraRenderer(physics, directory, camera_publish)
            self.state_pub = self.create_publisher(String, '/cooperation/physics_state', self.latest_qos)
            reset_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                  durability=DurabilityPolicy.VOLATILE)
            self.reset_pub = self.create_publisher(String, RESET_RESULT_TOPIC, reset_qos)
            self.reset_requests = ResetRequests()
            self.create_subscription(String, RESET_REQUEST_TOPIC, self.handler(self.reset_command), reset_qos)
            self.create_subscription(String, FAULT_TOPIC, self.handler(self.fault_trigger), 10)
            from rclpy.utilities import get_rmw_implementation_identifier
            self.runtime_observation = {'rmw': get_rmw_implementation_identifier(),
                'ros_dispatch': 'queued_receive_main_owner_apply' if self.callback_inbox else 'inline',
                'record_write_includes_handler_flush': True,
                'ephemeral_qos': {topic: {'depth': pub.qos_profile.depth,
                    'reliability': pub.qos_profile.reliability.name,
                    'history': pub.qos_profile.history.name,
                    'durability': pub.qos_profile.durability.name}
                    for topic, pub in (('/clock', self.clock_pub),
                                       ('/cooperation/physics_state', self.state_pub))}}
            self.tf = TransformBroadcaster(self)
            self.static_tf = StaticTransformBroadcaster(self)
            command_type = TwistStamped if args.stamped_cmd_vel else Twist
            self.create_subscription(command_type, '/cmd_vel', self.handler(self.car_command, with_received_time=True), 10)
            self.create_subscription(JointState, '/cooperation/arm_reference', self.handler(self.arm_command), 10)
            hold_qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
            self.create_subscription(Bool, '/cooperation/car_hold', self.handler(self.car_hold), hold_qos)
            self.create_subscription(Bool, '/cooperation/docking_guard', self.handler(self.guard_command), hold_qos)
            self.native_busy = {}
            action_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                   durability=DurabilityPolicy.TRANSIENT_LOCAL)
            for topic in ('/navigate_to_pose/_action/status', '/dock_robot/_action/status'):
                self.create_subscription(GoalStatusArray, topic,
                    self.handler(lambda message, topic=topic: self.native_status(topic, message)), action_qos)
            self.last_rejected = None
            self.publish_static_tf()

        def handler(self, function, *, with_received_time=False):
            if self.callback_inbox is None:
                return function
            return self.callback_inbox.callback(function, with_received_time=with_received_time)

        def car_hold(self, message):
            physics.wheels.set_hold(message.data)

        def fault_trigger(self, message):
            try:
                unique_arm_publisher(self.get_publishers_info_by_topic(FAULT_TOPIC), args.arm_publisher_node)
                physics.observation_faults.trigger(json.loads(message.data))
            except (ValueError, TypeError, KeyError) as error:
                self.reject('observation_fault_trigger', error)

        def native_status(self, topic, message):
            self.native_busy[topic] = any(item.status not in (4, 5, 6) for item in message.status_list)
            physics.native_actions_busy = any(self.native_busy.values())

        def reset_command(self, message):
            try:
                unique_arm_publisher(self.get_publishers_info_by_topic(RESET_REQUEST_TOPIC),
                                     args.arm_publisher_node)
                reply = self.reset_requests.offer(json.loads(message.data))
                if reply is not None:
                    self.reset_pub.publish(String(data=json.dumps(reply, allow_nan=False)))
            except (ValueError, TypeError, OverflowError) as error:
                self.reject('episode_reset', error)

        def process_reset(self):
            request = self.reset_requests.take()
            if request is None:
                return
            try:
                unique_arm_publisher(self.get_publishers_info_by_topic(RESET_REQUEST_TOPIC),
                                     args.arm_publisher_node)
                if not args.stamped_cmd_vel:
                    raise ValueError('new episodes require stamped cmd_vel to reject old commands')
                if not 0 <= time.time()-request['issued_at'] <= 5:
                    raise ValueError('reset request expired before the physics boundary')
                begin = frames.reset_episode if frames else physics.reset_episode
                episode_id, reset_stamp = begin(request['episode_id'])
                if self.camera:
                    self.camera.slot.fence(episode_id)
                if self.lidar:
                    self.lidar.slot.fence(episode_id)
                reply = reset_result(request, episode_id=episode_id, reset_stamp=reset_stamp,
                                     message='new synthetic episode initialized; previous records retained')
                self.last_rejected = None
            except (ValueError, TypeError, OverflowError) as error:
                reply = reset_result(request, message=error)
                self.reject('episode_reset', error)
            reply = self.reset_requests.finish(request, reply)
            self.reset_pub.publish(String(data=json.dumps(reply, allow_nan=False)))

        def guard_command(self, message):
            try:
                unique_arm_publisher(self.get_publishers_info_by_topic('/cooperation/docking_guard'),
                                     args.arm_publisher_node)
                physics.docking_guard.set_enabled(message.data)
            except (ValueError, TypeError, OverflowError) as error:
                physics.wheels.stop()
                self.reject('docking_guard', error)

        def car_command(self, message, *, received_at=None):
            try:
                received = time.monotonic() if received_at is None else received_at
                if args.stamped_cmd_vel:
                    twist = message.twist
                    source_stamp = message.header.stamp.sec + message.header.stamp.nanosec*1e-9
                    physics.wheels.accept(twist.linear.x, twist.angular.z, received,
                                          source_stamp=source_stamp, sim_now=physics.data.time,
                                          **({'lateral': twist.linear.y} if getattr(physics, 'mecanum_k', None) is not None else {}))
                else:
                    physics.wheels.accept(message.linear.x, message.angular.z, received,
                                          **({'lateral': message.linear.y} if getattr(physics, 'mecanum_k', None) is not None else {}))
            except (ValueError, TypeError, OverflowError) as error:
                physics.wheels.stop()
                self.reject('car', error)

        def arm_command(self, message):
            try:
                unique_arm_publisher(self.get_publishers_info_by_topic('/cooperation/arm_reference'),
                                     args.arm_publisher_node)
                if message.velocity or message.effort:
                    raise ValueError('arm interface accepts positions only')
                source_stamp = message.header.stamp.sec + message.header.stamp.nanosec*1e-9
                physics.set_arm_reference(message.name, message.position, source_stamp=source_stamp)
            except (ValueError, TypeError, OverflowError) as error:
                physics.wheels.set_hold(True)
                self.reject('arm', error)

        def reject(self, source, error):
            self.last_rejected = {'source': source, 'reason': str(error), 'stamp': float(physics.data.time)}
            self.get_logger().warning(f'Rejected {source} reference: {error}')

        def publish_static_tf(self):
            transforms = []
            root_position = physics.model.body('base_link').pos + physics.model.body('laser_link').pos
            for child, xyz in [('laser_link', root_position), ('imu_link', physics.model.body('base_link').pos + physics.model.body('imu_link').pos)]:
                transform = TransformStamped()
                transform.header.frame_id = 'base_footprint'
                transform.child_frame_id = child
                transform.transform.translation.x, transform.transform.translation.y, transform.transform.translation.z = map(float, xyz)
                transform.transform.rotation.w = 1.
                transforms.append(transform)
            self.static_tf.sendTransform(transforms)
            if self.lidar:
                c = self.lidar.config
                transform = TransformStamped()
                transform.header.frame_id, transform.child_frame_id = c['parent_body'], c['frame_id']
                transform.transform.translation.x, transform.transform.translation.y, transform.transform.translation.z = c['mount_xyz']
                transform.transform.rotation.w = 1.
                self.static_tf.sendTransform([transform])
            camera_config = physics.identity['manifest'].get('station_camera')
            if camera_config:
                transform = TransformStamped()
                transform.header.frame_id, transform.child_frame_id = 'base_footprint', camera_config['frame_id']
                transform.transform.translation.x, transform.transform.translation.y, transform.transform.translation.z = camera_config['base_camera_translation']
                # Rear optical axes (+Y,-Z,-X), quaternion xyzw=(-.5,-.5,.5,.5).
                transform.transform.rotation.x, transform.transform.rotation.y = -.5, -.5
                transform.transform.rotation.z, transform.transform.rotation.w = .5, .5
                self.static_tf.sendTransform([transform])

        def publish(self, include_scan):
            timing.measure('snapshot_refresh', physics.refresh_snapshot)
            current_stamp = stamp(float(physics.data.time))
            # Reuse the 50 Hz state cycle; slow scan cadence is not freshness.
            # Cache the current measurement once, then expose that same sample.
            station_observation = physics.observe_station()
            clock = Clock()
            clock.clock = current_stamp
            timing.measure('clock_publish', self.clock_pub.publish, clock)
            joint = JointState()
            joint.header.stamp = current_stamp
            joint.name = list(ARM_JOINTS+physics.wheel_joint_names)
            joint.position = physics.data.qpos[physics.arm_q+physics.wheel_q].tolist()
            joint.velocity = physics.data.qvel[physics.arm_v+physics.wheel_v].tolist()
            timing.measure('joint_publish', self.joint_pub.publish, joint)
            odom = Odometry()
            odom.header.stamp = current_stamp
            odom.header.frame_id, odom.child_frame_id = 'odom', 'base_footprint'
            odom.pose.pose.position.x, odom.pose.pose.position.y = physics.odom.x, physics.odom.y
            odom.pose.pose.orientation.z, odom.pose.pose.orientation.w = math.sin(physics.odom.yaw/2), math.cos(physics.odom.yaw/2)
            odom.twist.twist.linear.x, odom.twist.twist.angular.z = physics.odom_linear, physics.odom_angular
            odom.twist.twist.linear.y = physics.odom.lateral_velocity
            for index in (0, 7, 35):
                odom.pose.covariance[index] = .0025
                odom.twist.covariance[index] = .0025
            timing.measure('odom_publish', self.odom_pub.publish, odom)
            transform = TransformStamped()
            transform.header = odom.header
            transform.child_frame_id = 'base_footprint'
            transform.transform.translation.x, transform.transform.translation.y = physics.odom.x, physics.odom.y
            transform.transform.rotation = odom.pose.pose.orientation
            if not physics.localization_enabled:
                timing.measure('tf_publish', self.tf.sendTransform, transform)
            truth = Odometry()
            truth.header.stamp = current_stamp
            truth.header.frame_id, truth.child_frame_id = 'world', 'base_footprint'
            fill_pose(truth.pose.pose, physics.car_body)
            car_velocity = physics.body_velocity(physics.car_body)
            rotation = physics.data.xmat[physics.car_body].reshape(3,3)
            linear = rotation.T @ physics.np.array(car_velocity[3:])
            angular = rotation.T @ physics.np.array(car_velocity[:3])
            truth.twist.twist.linear.x, truth.twist.twist.linear.y, truth.twist.twist.linear.z = map(float, linear)
            truth.twist.twist.angular.x, truth.twist.twist.angular.y, truth.twist.twist.angular.z = map(float, angular)
            timing.measure('truth_publish', self.truth_pub.publish, truth)
            cargo = PoseStamped()
            cargo.header.stamp, cargo.header.frame_id = current_stamp, 'world'
            fill_pose(cargo.pose, physics.cargo_body)
            timing.measure('cargo_publish', self.cargo_pub.publish, cargo)
            imu = Imu()
            imu.header.stamp, imu.header.frame_id = current_stamp, 'imu_link'
            for sensor_name, field in [('imu_quat', 'orientation'), ('imu_gyro', 'angular_velocity'), ('imu_accel', 'linear_acceleration')]:
                sensor = physics.model.sensor(sensor_name)
                values = physics.data.sensordata[sensor.adr[0]:sensor.adr[0]+sensor.dim[0]]
                target = getattr(imu, field)
                if field == 'orientation':
                    target.w, target.x, target.y, target.z = map(float, values)
                else:
                    target.x, target.y, target.z = map(float, values)
            if physics.localization_enabled:
                # Ideal native IMU with explicit assumed covariance, matching
                # the existing J100 EKF experiment rather than truth odometry.
                for index in (0, 4, 8):
                    imu.orientation_covariance[index] = 1e-6
                    imu.angular_velocity_covariance[index] = 1e-6
                    imu.linear_acceleration_covariance[index] = .01
            timing.measure('imu_publish', self.imu_pub.publish, imu)
            state = physics.state()
            state['last_rejected_reference'] = self.last_rejected
            state['frame_error'] = frames.error if frames else None
            if getattr(self, 'camera', None):
                state['camera_error'] = self.camera.error
                state['camera_rendered_frames'] = self.camera.rendered
            if getattr(self, 'lidar', None):
                state['lidar3d'] = self.lidar.summary()
            if hasattr(physics, 'observation_faults'):
                state['observation_faults'] = physics.observation_faults.status()
            state['loop_diagnostics'] = {**timing.snapshot(), **self.runtime_observation}
            state['diagnostic_recording'] = record.snapshot() if record else {
                'kind': 'disabled', 'enabled': False, 'complete_evidence': False}
            state_json = json.dumps(state, allow_nan=False, separators=(',', ':'))
            timing.measure('state_publish', self.state_pub.publish, String(data=state_json))
            if record:
                timing.measure('record_write', record.offer, state_json)
                recording_error = record.snapshot()['error']
                if recording_error and recording_error != self.recording_error_reported:
                    self.get_logger().error('Diagnostic recording disabled: '+recording_error)
                    self.recording_error_reported = recording_error
            if station_observation is not None:
                outgoing = [station_observation]
                if hasattr(physics, 'observation_faults'):
                    velocity = physics.body_velocity(physics.car_body)
                    moving = math.hypot(*velocity[3:5]) > .005 or abs(velocity[2]) > .005
                    outgoing = physics.observation_faults.apply(station_observation,
                        wall_time=time.monotonic(), source_stamp=float(physics.data.time),
                        episode_id=physics.episode_id, moving=moving)
                for observed in outgoing:
                    station_pose, station_detection = station_messages(observed)
                    if station_pose is not None:
                        timing.measure('beacon_publish', self.station_pose_pub.publish, station_pose)
                    timing.measure('beacon_publish', self.station_detection_pub.publish, station_detection)
            if include_scan:
                scan = LaserScan()
                scan.header.stamp, scan.header.frame_id = current_stamp, 'laser_link'
                scan.angle_min, scan.angle_max = 0., 359*math.pi/180
                scan.angle_increment, scan.time_increment = math.pi/180, 0.
                scan.scan_time, scan.range_min, scan.range_max = .1, .12, 3.5
                scan.ranges = timing.measure('scan', physics.scan)
                timing.measure('scan_publish', self.scan_pub.publish, scan)
                if getattr(self, 'lidar', None):
                    timing.measure('lidar_offer', self.lidar.offer, state['sequence'])
            if frames:
                timing.measure('frame_offer', frames.offer)
            if getattr(self, 'camera', None):
                timing.measure('camera_offer', self.camera.offer)

    def fill_pose(pose, body):
        pose.position.x, pose.position.y, pose.position.z = map(float, physics.data.xpos[body])
        pose.orientation.w, pose.orientation.x, pose.orientation.y, pose.orientation.z = map(float, physics.data.xquat[body])

    rclpy.init(args=[])
    node = Adapter()
    receiver_executor = receiver_thread = None
    receiver_errors = []
    deadline, started = time.monotonic(), time.monotonic()
    try:
        if node.callback_inbox is not None:
            from rclpy.executors import SingleThreadedExecutor, ExternalShutdownException
            receiver_executor = SingleThreadedExecutor()
            receiver_executor.add_node(node)

            def receive_ros():
                try:
                    receiver_executor.spin()
                except ExternalShutdownException:
                    pass
                except Exception as error:
                    receiver_errors.append(error)

            receiver_thread = threading.Thread(target=receive_ros, name='cooperation-ros-receive', daemon=True)
            receiver_thread.start()
        while rclpy.ok() and (args.duration is None or time.monotonic()-started < args.duration):
            if receiver_errors:
                raise RuntimeError('ROS receive executor failed') from receiver_errors[0]
            if node.callback_inbox is None:
                timing.measure('spin_once', rclpy.spin_once, node, timeout_sec=0.)
            else:
                timing.measure('command_apply', node.callback_inbox.drain)
            node.process_reset()
            timing.measure('mj_step', physics.step)
            # 50 Hz state/odom and 10 Hz synchronous rays; physics stays single-owner.
            if physics.steps % 10 == 0:
                timing.measure('publish', node.publish, physics.steps % 50 == 0)
            deadline += .002
            remaining = deadline-time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            elif remaining < -.25:
                # Never synthesize clock jumps to catch up with wall time.
                deadline = time.monotonic()
    except KeyboardInterrupt:
        pass
    finally:
        physics.wheels.set_hold(True)
        physics.data.ctrl[physics.wheel_a] = 0.
        original_error = sys.exc_info()[1]
        finalization_errors = []

        def finalize_stage(stage, function):
            try:
                function()
            except (Exception, KeyboardInterrupt) as error:
                # A second SIGINT may interrupt a thread join. Finish the other
                # resources and diagnostics before preserving the first error.
                finalization_errors.append((stage, error))

        try:
            if receiver_executor is not None:
                def stop_receiver():
                    try:
                        receiver_executor.shutdown(timeout_sec=2.)
                    finally:
                        if receiver_thread is not None:
                            receiver_thread.join(timeout=2.)
                            if receiver_thread.is_alive():
                                raise RuntimeError('ROS receive thread did not stop')
                    if receiver_errors:
                        raise RuntimeError('ROS receive executor failed') from receiver_errors[0]
                finalize_stage('ros_receive.stop', stop_receiver)
            for name, resource in (('frames', frames), ('camera', node.camera),
                                   ('lidar', node.lidar), ('record', record)):
                if resource is not None:
                    finalize_stage(name+'.close', resource.close)
        finally:
            try:
                finalize_stage('node.destroy_node', node.destroy_node)
                finalize_stage('rclpy.try_shutdown', rclpy.try_shutdown)
            finally:
                if timing_record is not None:
                    def write_timing():
                        json.dump({**timing.snapshot(), **node.runtime_observation,
                            'diagnostic_recording': record.snapshot() if record else {'kind': 'disabled', 'enabled': False},
                            'finalization_errors': [{'stage': stage, 'type': type(error).__name__,
                                                     'message': str(error)}
                                                    for stage, error in finalization_errors]},
                            timing_record, allow_nan=False)
                        timing_record.flush()
                    try:
                        finalize_stage('timing_record.write_flush', write_timing)
                    finally:
                        finalize_stage('timing_record.close', timing_record.close)
        for stage, error in finalization_errors:
            print(f'cooperation finalization {stage}: {type(error).__name__}: {error}', file=sys.stderr)
        if finalization_errors and original_error is None:
            raise finalization_errors[0][1]


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--scene', required=True, type=Path)
    result.add_argument('--manifest', type=Path, help='explicit runtime manifest; defaults to the scene sibling')
    result.add_argument('--domain', required=True, type=int)
    result.add_argument('--frame-dir', type=Path)
    result.add_argument('--frame-fps', type=float, default=3.)
    result.add_argument('--camera', default='cooperation_overview')
    result.add_argument('--no-overview-render', action='store_true',
                        help='Disable the display-only overview; retain sensor cameras and physics')
    result.add_argument('--state-log', type=Path, help='opt-in rolling diagnostic JSONL, never complete scoring evidence')
    result.add_argument('--state-log-hz', type=float, default=2.)
    result.add_argument('--state-log-max-bytes', type=int, default=8*1024*1024)
    result.add_argument('--state-log-backups', type=int, default=3)
    result.add_argument('--timing-log', type=Path, help='optional final bounded timing observations')
    result.add_argument('--duration', type=float)
    result.add_argument('--queued-ros-dispatch', action='store_true',
                        help='receive ROS off-thread and apply commands at the physics boundary')
    result.add_argument('--stamped-cmd-vel', action='store_true')
    result.add_argument('--arm-publisher-node', default='fishbot_so101_cooperation')
    return result


def main():
    args = parser().parse_args()
    if not 1 <= args.domain <= 232 or args.domain == 107:
        raise SystemExit('cooperation requires isolated domain 1..232, excluding runtime 107')
    if not math.isfinite(args.frame_fps) or not .1 <= args.frame_fps <= 10:
        raise SystemExit('--frame-fps must be 0.1..10')
    if args.duration is not None and (not math.isfinite(args.duration) or args.duration <= 0):
        raise SystemExit('--duration must be finite and positive')
    if not math.isfinite(args.state_log_hz) or not .1 <= args.state_log_hz <= 50:
        raise SystemExit('--state-log-hz must be 0.1..50')
    if not 1024 <= args.state_log_max_bytes <= 64*1024*1024:
        raise SystemExit('--state-log-max-bytes must be 1024..67108864')
    if not 1 <= args.state_log_backups <= 7:
        raise SystemExit('--state-log-backups must be 1..7; zero would disable rotation')
    os.environ['ROS_DOMAIN_ID'] = str(args.domain)
    os.environ['ROS_AUTOMATIC_DISCOVERY_RANGE'] = 'LOCALHOST'
    os.environ['ROS_LOCALHOST_ONLY'] = '1'
    os.environ.setdefault('MUJOCO_GL', 'egl')
    run_ros(args)


if __name__ == '__main__':
    main()
