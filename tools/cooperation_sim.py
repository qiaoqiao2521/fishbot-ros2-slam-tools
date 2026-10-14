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
import random
import shutil
import threading
import time
import uuid
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from fishbot_sim_power import BEACON_LABEL, PowerModel, Truth
from cooperation_core import ContinuousEvidence
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
    """Bounded monotonic observations, with no control or timing decisions."""
    STAGES = ('spin_once', 'mj_step', 'publish', 'snapshot_refresh',
              'clock_publish', 'joint_publish', 'odom_publish', 'tf_publish',
              'truth_publish', 'cargo_publish', 'imu_publish', 'state_publish',
              'record_write', 'record_flush', 'scan', 'scan_publish',
              'beacon_publish', 'frame_offer')

    def __init__(self, source_time=lambda: None):
        self.source_time = source_time
        self.stats = {name: {'count': 0, 'max_s': 0., 'slow_count': 0} for name in self.STAGES}
        self.slow_tail = deque(maxlen=32)
        self.slow_count = 0

    def observe(self, stage, start, end, source_stamp=None):
        if stage not in self.stats or not all(math.isfinite(t) for t in (start, end)) or end < start:
            raise ValueError('invalid loop timing observation')
        elapsed = end-start
        entry = self.stats[stage]
        entry['count'] += 1
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


class WheelCommands:
    """Steady-time watchdog remains active while arm references are held."""
    def __init__(self):
        self.hold = True
        self.last_received = None
        self.linear = self.angular = 0.
        self.source_floor = None

    def accept(self, linear, angular, now, *, source_stamp=None, sim_now=None):
        linear, angular, now = finite_vector((linear, angular, now), 3, 'car command')
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
        self.last_received = now

    def stop(self):
        self.linear = self.angular = 0.
        self.last_received = None

    def set_hold(self, hold):
        # Release requires a newly received command; queued motion cannot resume.
        self.hold = bool(hold)
        self.stop()

    def begin_episode(self, source_stamp):
        self.source_floor, = finite_vector((source_stamp,), 1, 'episode command floor')
        self.set_hold(True)

    def velocities(self, now):
        if self.hold or self.last_received is None or not 0 <= now-self.last_received <= COMMAND_TIMEOUT:
            return 0., 0.
        return ((self.linear-self.angular*WHEEL_SEPARATION/2)/WHEEL_RADIUS,
                (self.linear+self.angular*WHEEL_SEPARATION/2)/WHEEL_RADIUS)


class EncoderOdometry:
    """Integrate the wheel axle, then transform to the fixed foot origin."""
    def __init__(self, left=0., right=0., *, axle_offset=(0., 0.)):
        self.left, self.right = left, right
        if len(axle_offset) != 2 or not all(math.isfinite(x) for x in axle_offset):
            raise ValueError('axle offset must be a finite planar vector')
        self.axle_offset = tuple(float(x) for x in axle_offset)
        # Odom initially coincides with the foot; its wheel axle is offset.
        self.axle_x, self.axle_y = self.axle_offset
        self.x = self.y = self.yaw = 0.
        self.lateral_velocity = 0.

    def update(self, left, right, dt):
        dl, dr = (left-self.left)*WHEEL_RADIUS, (right-self.right)*WHEEL_RADIUS
        self.left, self.right = left, right
        distance = (dl+dr)/2
        angle = (dr-dl)/WHEEL_SEPARATION
        self.axle_x += distance*math.cos(self.yaw+angle/2)
        self.axle_y += distance*math.sin(self.yaw+angle/2)
        self.yaw = math.atan2(math.sin(self.yaw+angle), math.cos(self.yaw+angle))
        a, b = self.axle_offset
        self.x = self.axle_x-a*math.cos(self.yaw)+b*math.sin(self.yaw)
        self.y = self.axle_y-a*math.sin(self.yaw)-b*math.cos(self.yaw)
        angular = angle/dt if dt > 0 else 0.
        self.lateral_velocity = -angular*a
        return (distance/dt+angular*b, angular) if dt > 0 else (0., 0.)


def compiled_axle_offset(model):
    """Read fixed encoder geometry in a separate reset-only kinematic data."""
    import mujoco
    import numpy as np
    geometry = mujoco.MjData(model)
    mujoco.mj_kinematics(model, geometry)
    foot = model.body('base_footprint').id
    local = geometry.xmat[foot].reshape(3, 3).T
    anchors = [local @ (geometry.xanchor[model.joint(name).id]-geometry.xpos[foot])
               for name in WHEEL_JOINTS]
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


def source_identity(scene):
    """Record compiled inputs without publishing machine-specific absolute paths."""
    scene = Path(scene).resolve()
    identity = {'scene_name': scene.name, 'scene_sha256': hashlib.sha256(scene.read_bytes()).hexdigest()}
    manifest = scene.with_name('scene-manifest.json')
    if manifest.is_file():
        payload = manifest.read_bytes()
        identity['manifest_sha256'] = hashlib.sha256(payload).hexdigest()
        identity['manifest'] = json.loads(payload)
    return identity


class Physics:
    def __init__(self, scene):
        import mujoco
        import numpy as np
        self.mj, self.np = mujoco, np
        self.scene = Path(scene).resolve()
        self.model = mujoco.MjModel.from_xml_path(str(self.scene))
        self.data = mujoco.MjData(self.model)
        if abs(self.model.opt.timestep-.002) > 1e-12:
            raise ValueError('cooperation scene must use 500 Hz physics')
        self.arm_joint_ids = [self.model.joint(name).id for name in ARM_JOINTS]
        self.arm_q = [int(self.model.jnt_qposadr[i]) for i in self.arm_joint_ids]
        self.arm_v = [int(self.model.jnt_dofadr[i]) for i in self.arm_joint_ids]
        self.arm_a = [self.model.actuator(name).id for name in ARM_JOINTS]
        self.wheel_joint_ids = [self.model.joint(name).id for name in WHEEL_JOINTS]
        self.wheel_q = [int(self.model.jnt_qposadr[i]) for i in self.wheel_joint_ids]
        self.wheel_v = [int(self.model.jnt_dofadr[i]) for i in self.wheel_joint_ids]
        self.wheel_a = [self.model.actuator(name).id for name in WHEEL_JOINTS]
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
        self.identity = source_identity(self.scene)
        self.episode_id = str(uuid.uuid4())
        self.identity['episode_id'] = self.episode_id
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
        self.wheels = WheelCommands()
        self.encoder_axle_offset = compiled_axle_offset(self.model)
        self.odom = EncoderOdometry(*(float(self.data.qpos[i]) for i in self.wheel_q),
                                    axle_offset=self.encoder_axle_offset[:2])
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
        self.odom.left, self.odom.right = (float(self.data.qpos[i]) for i in self.wheel_q)
        self.odom.lateral_velocity = self.odom_linear = self.odom_angular = 0.
        self.total_forbidden_steps = self.total_forbidden_contacts = 0
        self.total_car_forbidden_steps = self.total_car_forbidden_contacts = 0
        self.max_normal_forces = {name: 0. for name in self.finger_geoms}
        self.episode_id = str(uuid.uuid4())
        self.identity = {**self.identity, 'episode_id': self.episode_id}
        self.station_beacon.begin_episode(self.episode_id, preserved_time)
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
        self.data.ctrl[self.wheel_a] = self.wheels.velocities(time.monotonic())
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
            *(float(self.data.qpos[i]) for i in self.wheel_q), float(self.model.opt.timestep))
        self.contacts = self.contact_state()
        self.observe_reset_quiet()

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
            b1, b2 = (int(self.model.geom_bodyid[g]) for g in (g1, g2))
            geom_names = (self.model.geom(g1).name, self.model.geom(g2).name)
            # The car may touch the arena floor and carry cargo. Any other
            # external collision remains independent evidence, including bench.
            car_external = (b1 in self.car_bodies) != (b2 in self.car_bodies)
            if (car_external and self.cargo_geom not in pair and normal > 1e-8
                    and not any(self.model.geom_type[g] == self.mj.mjtGeom.mjGEOM_PLANE for g in pair)):
                car_forbidden.append({'geom1': geom_names[0], 'geom2': geom_names[1],
                                      'normal_force_n': normal, 'distance_m': float(contact.dist)})
            if not pair & self.arm_geoms:
                continue
            # Only the pads may touch the cargo. Other arm/cargo contact fails.
            if self.cargo_geom in pair and pair & set(self.finger_geoms.values()):
                continue
            body_names = (self.model.body(b1).name, self.model.body(b2).name)
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
                       'axle_offset_in_foot': list(self.encoder_axle_offset),
                       'source': 'compiled reset wheel hinge anchors; runtime wheel encoders only',
                       'wheel_radius_m': WHEEL_RADIUS, 'wheel_separation_m': WHEEL_SEPARATION},
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
    from sensor_msgs.msg import Imu, JointState, LaserScan
    from std_msgs.msg import Bool, String
    from action_msgs.msg import GoalStatusArray
    from tf2_ros import TransformBroadcaster, StaticTransformBroadcaster

    physics = Physics(args.scene)
    timing = LoopTiming(lambda: float(physics.data.time))
    frames = FrameWriter(physics, args.frame_dir, args.frame_fps, args.camera) if args.frame_dir else None
    record = None
    timing_record = None
    if args.state_log:
        destination = Path(args.state_log).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        record = os.fdopen(os.open(destination, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600), 'w')
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
            self.sensor_qos = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT)
            self.latest_qos = latest_sensor_qos()
            self.clock_pub = self.create_publisher(Clock, '/clock', self.latest_qos)
            self.scan_pub = self.create_publisher(LaserScan, '/scan', self.sensor_qos)
            self.imu_pub = self.create_publisher(Imu, '/imu', self.sensor_qos)
            self.joint_pub = self.create_publisher(JointState, '/joint_states', 10)
            self.odom_pub = self.create_publisher(Odometry, '/odom', 10)
            self.truth_pub = self.create_publisher(Odometry, '/ground_truth/odom', 10)
            self.cargo_pub = self.create_publisher(PoseStamped, '/cooperation/cargo_pose', 10)
            if physics.station_beacon.perception_config['mode'] != 'vision':
                self.station_pose_pub = self.create_publisher(PoseWithCovarianceStamped, STATION_POSE_TOPIC, self.latest_qos)
                self.station_detection_pub = self.create_publisher(DiagnosticArray, STATION_DETECTION_TOPIC, self.latest_qos)
            self.state_pub = self.create_publisher(String, '/cooperation/physics_state', self.latest_qos)
            reset_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                  durability=DurabilityPolicy.VOLATILE)
            self.reset_pub = self.create_publisher(String, RESET_RESULT_TOPIC, reset_qos)
            self.reset_requests = ResetRequests()
            self.create_subscription(String, RESET_REQUEST_TOPIC, self.reset_command, reset_qos)
            from rclpy.utilities import get_rmw_implementation_identifier
            self.runtime_observation = {'rmw': get_rmw_implementation_identifier(),
                'ephemeral_qos': {topic: {'depth': pub.qos_profile.depth,
                    'reliability': pub.qos_profile.reliability.name,
                    'history': pub.qos_profile.history.name,
                    'durability': pub.qos_profile.durability.name}
                    for topic, pub in (('/clock', self.clock_pub),
                                       ('/cooperation/physics_state', self.state_pub))}}
            self.tf = TransformBroadcaster(self)
            self.static_tf = StaticTransformBroadcaster(self)
            command_type = TwistStamped if args.stamped_cmd_vel else Twist
            self.create_subscription(command_type, '/cmd_vel', self.car_command, 10)
            self.create_subscription(JointState, '/cooperation/arm_reference', self.arm_command, 10)
            hold_qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
            self.create_subscription(Bool, '/cooperation/car_hold', self.car_hold, hold_qos)
            self.create_subscription(Bool, '/cooperation/docking_guard', self.guard_command, hold_qos)
            self.native_busy = {}
            action_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                   durability=DurabilityPolicy.TRANSIENT_LOCAL)
            for topic in ('/navigate_to_pose/_action/status', '/dock_robot/_action/status'):
                self.create_subscription(GoalStatusArray, topic,
                    lambda message, topic=topic: self.native_status(topic, message), action_qos)
            self.last_rejected = None
            self.publish_static_tf()

        def car_hold(self, message):
            physics.wheels.set_hold(message.data)

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

        def car_command(self, message):
            try:
                if args.stamped_cmd_vel:
                    twist = message.twist
                    source_stamp = message.header.stamp.sec + message.header.stamp.nanosec*1e-9
                    physics.wheels.accept(twist.linear.x, twist.angular.z, time.monotonic(),
                                          source_stamp=source_stamp, sim_now=physics.data.time)
                else:
                    physics.wheels.accept(message.linear.x, message.angular.z, time.monotonic())
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
            joint.name = list(ARM_JOINTS+WHEEL_JOINTS)
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
            timing.measure('imu_publish', self.imu_pub.publish, imu)
            state = physics.state()
            state['last_rejected_reference'] = self.last_rejected
            state['frame_error'] = frames.error if frames else None
            state['loop_diagnostics'] = {**timing.snapshot(), **self.runtime_observation}
            state_json = json.dumps(state, allow_nan=False, separators=(',', ':'))
            timing.measure('state_publish', self.state_pub.publish, String(data=state_json))
            if record:
                timing.measure('record_write', record.write, state_json+'\n')
                timing.measure('record_flush', record.flush)
            if station_observation is not None:
                station_pose, station_detection = station_messages(station_observation)
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
            if frames:
                timing.measure('frame_offer', frames.offer)

    def fill_pose(pose, body):
        pose.position.x, pose.position.y, pose.position.z = map(float, physics.data.xpos[body])
        pose.orientation.w, pose.orientation.x, pose.orientation.y, pose.orientation.z = map(float, physics.data.xquat[body])

    rclpy.init(args=[])
    node = Adapter()
    deadline, started = time.monotonic(), time.monotonic()
    try:
        while rclpy.ok() and (args.duration is None or time.monotonic()-started < args.duration):
            timing.measure('spin_once', rclpy.spin_once, node, timeout_sec=0.)
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
        try:
            if frames:
                frames.close()
            if record:
                record.close()
            if timing_record:
                json.dump({**timing.snapshot(), **node.runtime_observation}, timing_record, allow_nan=False)
        finally:
            if timing_record:
                timing_record.close()
            node.destroy_node()
            rclpy.shutdown()


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--scene', required=True, type=Path)
    result.add_argument('--domain', required=True, type=int)
    result.add_argument('--frame-dir', type=Path)
    result.add_argument('--frame-fps', type=float, default=3.)
    result.add_argument('--camera', default='cooperation_overview')
    result.add_argument('--state-log', type=Path)
    result.add_argument('--timing-log', type=Path, help='optional final bounded timing observations')
    result.add_argument('--duration', type=float)
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
    os.environ['ROS_DOMAIN_ID'] = str(args.domain)
    os.environ['ROS_AUTOMATIC_DISCOVERY_RANGE'] = 'LOCALHOST'
    os.environ['ROS_LOCALHOST_ONLY'] = '1'
    os.environ.setdefault('MUJOCO_GL', 'egl')
    run_ros(args)


if __name__ == '__main__':
    main()
