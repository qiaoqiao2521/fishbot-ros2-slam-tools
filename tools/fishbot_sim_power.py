#!/usr/bin/python3
"""Domain-98 MuJoCo battery/contact model; never sends robot commands.

The detected dock is a truth-derived simulated positioning beacon, not RGB
perception. SOC uses simulated seconds; optional acceleration is reported in
every status. This models a contact sensor and battery, not hardware charging.

CLI: fishbot_sim_power.py --scene /absolute/path/semantic.json
Integration: configure_docking(nav2_yaml_dict, semantic_dict).
Pure logic and configuration import without ROS. Runtime requires system Jazzy
and the MuJoCo workspace overlay. See fishbot_home_docking.yaml for the schema.
"""
import argparse
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import time


DOMAIN = 98
BATTERY_TOPIC = '/battery_state'
BEACON_TOPIC = '/detected_dock_pose'
STATUS_TOPIC = '/sim_power/status'
TRUTH_TOPIC = '/ground_truth/free_joint_states'
MODEL_LABEL = 'MuJoCo contact sensor and accelerated battery simulation; no hardware charging'
BEACON_LABEL = 'truth-derived relative positioning beacon; not RGB detection'


def validate_environment(env):
    required = {'ROS_DOMAIN_ID': '98', 'FISHBOT_MUJOCO_DOMAIN_ID': '98',
                'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST', 'ROS_LOCALHOST_ONLY': '1'}
    if any(env.get(k) != v for k, v in required.items()) or env.get('ROS_STATIC_PEERS', ''):
        raise ValueError('Requires simulation domain 98, LOCALHOST, ROS_LOCALHOST_ONLY=1, and empty ROS_STATIC_PEERS')


def angle(value):
    return math.atan2(math.sin(value), math.cos(value))


def number(value, name, low=-math.inf, high=math.inf):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} must be a finite number')
    result = float(value)
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(f'{name} outside [{low}, {high}]')
    return result


def pose(value, name):
    return tuple(number(value[k], f'{name}.{k}') for k in ('x', 'y', 'yaw'))


@dataclass(frozen=True)
class PowerConfig:
    dock_id: str
    dock_type: str
    frame: str
    dock_pose: tuple
    staging_pose: tuple
    truth_to_dock_frame: tuple
    contact_center: tuple
    half_length: float
    half_width: float
    yaw_tolerance_rad: float
    max_linear_mps: float
    max_angular_rps: float
    dwell_s: float
    max_height_m: float = .04
    initial_soc: float = .36
    low_soc: float = .28
    resume_soc: float = .80
    capacity_ah: float = 2.0
    idle_discharge_a: float = .1
    linear_discharge_a_per_mps: float = 3.0
    angular_discharge_a_per_rps: float = .3
    charging_current_a: float = 2.0
    discharge_time_scale: float = 45.0
    charge_time_scale: float = 288.0
    truth_timeout_s: float = .5
    wall_timeout_s: float = .5
    max_sample_gap_s: float = .25
    future_tolerance_s: float = .05

    @classmethod
    def from_scene(cls, semantic):
        dock = semantic['dock']
        dock_id, frame = dock['id'], dock['frame']
        dock_type = dock.get('type', 'home_charging_dock')
        for key, value in (('id', dock_id), ('type', dock_type)):
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', value):
                raise ValueError(f'dock.{key} must be a ROS parameter identifier')
        if dock_id == dock_type:
            raise ValueError('dock.id and dock.type need separate ROS parameter namespaces')
        if frame != 'map':
            raise ValueError('This fixture requires dock.frame=map and an explicit truth transform')
        target, staging = pose(dock['pose'], 'dock.pose'), pose(dock['staging_pose'], 'dock.staging_pose')
        transform = pose(dock['truth_to_dock_frame'], 'dock.truth_to_dock_frame')
        contact = dock['contact']
        center = contact.get('center', dock['pose'])
        values = dict(dock_id=dock_id, dock_type=dock_type, frame=frame, dock_pose=target, staging_pose=staging,
                      truth_to_dock_frame=transform,
                      max_height_m=number(contact.get('max_height_m', .04), 'contact.max_height_m', .001, .1),
                      contact_center=tuple(number(center[k], f'contact.center.{k}') for k in ('x', 'y')))
        limits = {'half_length': (.001, .5), 'half_width': (.001, .5),
                  'yaw_tolerance_rad': (.001, math.pi/2), 'max_linear_mps': (.001, .1),
                  'max_angular_rps': (.001, .3), 'dwell_s': (.1, 10.)}
        for key, bounds in limits.items():
            values[key] = number(contact[key], f'contact.{key}', *bounds)
        rates = dock.get('charge_model', {})
        limits = {'initial_soc': (0., 1.), 'low_soc': (.001, .999), 'resume_soc': (.001, .999),
                  'capacity_ah': (.01, 100.), 'idle_discharge_a': (0., 100.),
                  'linear_discharge_a_per_mps': (0., 100.), 'angular_discharge_a_per_rps': (0., 100.),
                  'charging_current_a': (.501, 100.), 'discharge_time_scale': (1., 10000.),
                  'charge_time_scale': (1., 10000.), 'truth_timeout_s': (.05, 1.),
                  'wall_timeout_s': (.05, 1.), 'max_sample_gap_s': (.01, .5),
                  'future_tolerance_s': (0., .05)}
        unknown = set(rates)-set(limits)
        if unknown:
            raise ValueError(f'Unknown charge_model fields: {sorted(unknown)}')
        for key, value in rates.items():
            values[key] = number(value, f'charge_model.{key}', *limits[key])
        result = cls(**values)
        if result.low_soc >= result.resume_soc:
            raise ValueError('low_soc must be below resume_soc')
        if result.max_sample_gap_s > result.truth_timeout_s:
            raise ValueError('max_sample_gap_s must not exceed truth_timeout_s')
        # Nav2 SimpleChargingDock supports a local x offset, not an arbitrary staging point.
        dx, dy = staging[0]-target[0], staging[1]-target[1]
        lateral = -math.sin(target[2])*dx+math.cos(target[2])*dy
        forward = math.cos(target[2])*dx+math.sin(target[2])*dy
        if abs(lateral) > 1e-4 or not -2.0 <= forward <= -.2 or abs(angle(staging[2]-target[2])) > 1e-4:
            raise ValueError('staging_pose must lie 0.2..2m behind dock, with the same yaw')
        if math.dist(result.contact_center, target[:2]) > min(result.half_length, result.half_width)/4:
            raise ValueError('dock target must be near the contact region center')
        return result


def configure_docking(params, semantic):
    """Add domain-98 fixture docking parameters to a complete Nav2 YAML dict.

    Root launch must remap docking cmd_vel into the single existing smoother /
    collision-monitor chain and lifecycle-manage docking_server. The helper
    never creates another publisher, alters other servers, or starts ROS.
    """
    cfg = PowerConfig.from_scene(semantic)
    x, y, yaw = cfg.dock_pose
    sx, sy, _ = cfg.staging_pose
    staging_offset = (sx-x)*math.cos(yaw)+(sy-y)*math.sin(yaw)
    params['docking_server'] = {'ros__parameters': {
        'use_sim_time': True, 'enable_stamped_cmd_vel': True,
        'controller_frequency': 20.0, 'initial_perception_timeout': 5.0,
        'wait_charge_timeout': max(5., cfg.dwell_s+3.), 'dock_approach_timeout': 45.0,
        'max_retries': 1, 'base_frame': 'base_footprint', 'fixed_frame': 'odom',
        'dock_backwards': False, 'dock_prestaging_tolerance': .15,
        'undock_linear_tolerance': .05, 'undock_angular_tolerance': .1,
        'dock_plugins': [cfg.dock_type],
        cfg.dock_type: {
            'plugin': 'opennav_docking::SimpleChargingDock', 'use_battery_status': True,
            'charging_threshold': .5, 'use_stall_detection': False,
            'use_external_detection_pose': True, 'external_detection_timeout': cfg.truth_timeout_s,
            'external_detection_translation_x': 0.0, 'external_detection_translation_y': 0.0,
            'external_detection_rotation_roll': 0.0, 'external_detection_rotation_pitch': 0.0,
            'external_detection_rotation_yaw': 0.0, 'filter_coef': 1.0,
            # Its isDocked() checks distance only. Stopping 6 cm early left
            # orientation unconverged, correctly rejected by the contact model.
            'docking_threshold': min(.02, min(cfg.half_length, cfg.half_width)*.5),
            'staging_x_offset': staging_offset, 'staging_yaw_offset': 0.0},
        'docks': [cfg.dock_id],
        cfg.dock_id: {'type': cfg.dock_type, 'frame': cfg.frame, 'pose': [x, y, yaw]},
        # Jazzy projects its control target 0.25 m beyond the contact pose.
        # Keep its default 0.30 m terminal exemption around that projected target.
        # Collision Monitor still checks actual robot motion throughout docking.
        'controller': {'v_linear_min': .02, 'v_linear_max': .08, 'v_angular_max': .25,
                       'use_collision_detection': True, 'dock_collision_threshold': .3,
                       'costmap_topic': 'local_costmap/costmap_raw',
                       'footprint_topic': 'local_costmap/published_footprint'}}}
    return params


@dataclass(frozen=True)
class Truth:
    stamp: float
    received: float
    x: float
    y: float
    yaw: float
    vx: float
    vy: float
    wz: float
    z: float = 0.0
    vz: float = 0.0
    wx: float = 0.0
    wy: float = 0.0


class PowerModel:
    """Integrate only consecutive fresh source samples, never publication ticks."""
    def __init__(self, config, charging_enabled=True):
        self.config = config
        self.charging_enabled = charging_enabled
        self.soc = config.initial_soc
        self.truth = None
        self._previous = None
        self._high_stamp = None
        self._contact_since = None
        self._last_clock = None
        self._clock_progress_wall = None
        self._clock_fault = False
        self.reason = 'waiting_for_clock_and_truth'
        self.contact = False
        self.charging = False
        self.current_a = 0.0
        self.accepted_samples = 0
        self.rejected_samples = 0
        self.distance_m = 0.0
        self.charged_soc_total = 0.0
        self.discharged_soc_total = 0.0

    def _clock_fresh(self, now_sim, now_wall):
        if not all(math.isfinite(v) for v in (now_sim, now_wall)):
            return False
        if self._last_clock is not None:
            if now_sim < self._last_clock-1e-9:
                self._clock_fault = True  # Restart this model after resetting a simulation.
            elif now_sim > self._last_clock:
                self._clock_progress_wall = now_wall
        self._last_clock = now_sim
        return (not self._clock_fault and now_sim > 0 and self._clock_progress_wall is not None
                and 0 <= now_wall-self._clock_progress_wall <= self.config.wall_timeout_s)

    def _fresh(self, sample, now_sim, now_wall):
        c = self.config
        return (sample is not None and sample.stamp > 0
                and -c.future_tolerance_s <= now_sim-sample.stamp <= c.truth_timeout_s
                and 0 <= now_wall-sample.received <= c.wall_timeout_s)

    def invalidate(self, reason):
        self.reason = reason
        self.charging = self.contact = False
        self.current_a = 0.0
        self._previous = None
        self._contact_since = None

    def mapped_pose(self, sample):
        tx, ty, yaw = self.config.truth_to_dock_frame
        return (tx+math.cos(yaw)*sample.x-math.sin(yaw)*sample.y,
                ty+math.sin(yaw)*sample.x+math.cos(yaw)*sample.y, angle(sample.yaw+yaw))

    def relative_beacon(self):
        """Dock target relative to base_footprint; bypasses AMCL only for this beacon."""
        if self.truth is None:
            raise ValueError('No truth for relative beacon')
        x, y, yaw = self.mapped_pose(self.truth)
        dx, dy = self.config.dock_pose[0]-x, self.config.dock_pose[1]-y
        return (math.cos(yaw)*dx+math.sin(yaw)*dy,
                -math.sin(yaw)*dx+math.cos(yaw)*dy, angle(self.config.dock_pose[2]-yaw))

    def contact_metrics(self, sample):
        c = self.config
        x, y, yaw = self.mapped_pose(sample)
        dx, dy = x-c.contact_center[0], y-c.contact_center[1]
        local_x = math.cos(c.dock_pose[2])*dx+math.sin(c.dock_pose[2])*dy
        local_y = -math.sin(c.dock_pose[2])*dx+math.cos(c.dock_pose[2])*dy
        yaw_error = abs(angle(yaw-c.dock_pose[2]))
        linear = math.sqrt(sample.vx**2+sample.vy**2+sample.vz**2)
        angular = math.sqrt(sample.wx**2+sample.wy**2+sample.wz**2)
        contact = (abs(local_x) <= c.half_length and abs(local_y) <= c.half_width
                   and yaw_error <= c.yaw_tolerance_rad and linear <= c.max_linear_mps
                   and angular <= c.max_angular_rps and abs(sample.z) <= c.max_height_m)
        return {'contact': contact, 'dock_local_x': local_x, 'dock_local_y': local_y,
                'yaw_error_rad': yaw_error, 'linear_mps': linear, 'angular_rps': angular,
                'height_m': sample.z}

    def ingest(self, sample, now_sim, now_wall):
        c = self.config
        clock_fresh = self._clock_fresh(now_sim, now_wall)
        if not all(math.isfinite(v) for v in vars(sample).values()):
            reason = 'nonfinite_truth'
        elif self._high_stamp is not None and sample.stamp <= self._high_stamp:
            reason = 'truth_stamp_duplicate_or_regressed'
        elif not clock_fresh:
            reason = 'clock_stale_or_regressed'
        elif not self._fresh(sample, now_sim, now_wall):
            reason = 'truth_stale_or_future'
        else:
            reason = None
        if reason:
            self.rejected_samples += 1
            self.invalidate(reason)
            return False
        previous = self._previous
        dt = sample.stamp-previous.stamp if previous else 0.0
        continuous = (previous is not None and 0 < dt <= c.max_sample_gap_s
                      and 0 <= sample.received-previous.received <= c.wall_timeout_s)
        metrics = self.contact_metrics(sample)
        if not continuous:
            self._contact_since = None
        if not metrics['contact']:
            self._contact_since = None
        elif self._contact_since is None:
            self._contact_since = sample.stamp
        charge_seconds = 0.0
        if continuous and self._contact_since is not None and self.charging_enabled:
            charge_seconds = max(0., sample.stamp-max(previous.stamp, self._contact_since+c.dwell_s))
        drain = c.idle_discharge_a+c.linear_discharge_a_per_mps*metrics['linear_mps']+c.angular_discharge_a_per_rps*metrics['angular_rps']
        if continuous:
            gain = c.charging_current_a*charge_seconds*c.charge_time_scale/(3600*c.capacity_ah)
            loss = drain*(dt-charge_seconds)*c.discharge_time_scale/(3600*c.capacity_ah)
            # Integrate discharge before charge for the threshold-crossing interval.
            actual_loss = min(self.soc, loss)
            self.soc -= actual_loss
            actual_gain = min(1.-self.soc, gain)
            self.soc += actual_gain
            self.charged_soc_total += actual_gain
            self.discharged_soc_total += actual_loss
            self.distance_m += math.hypot(sample.vx, sample.vy)*dt
        self.contact = metrics['contact']
        self.charging = (self.charging_enabled and self._contact_since is not None
                         and sample.stamp-self._contact_since >= c.dwell_s)
        self.current_a = c.charging_current_a if self.charging else -drain
        self.truth = self._previous = sample
        self._high_stamp = sample.stamp
        self.accepted_samples += 1
        self.reason = ('charging_disabled' if self.contact and not self.charging_enabled else
                       'charging' if self.charging else 'contact_dwell' if self.contact else 'discharging')
        return True

    def snapshot(self, now_sim, now_wall):
        clock_fresh = self._clock_fresh(now_sim, now_wall)
        truth_fresh = self._fresh(self.truth, now_sim, now_wall) and self._previous is not None
        if not clock_fresh or not truth_fresh:
            self.invalidate('clock_stale_or_regressed' if not clock_fresh else 'truth_stale_or_invalid')
        c = self.config
        return {'schema_version': 1, 'model': MODEL_LABEL, 'beacon_method': BEACON_LABEL,
                'domain': DOMAIN, 'use_sim_time': True, 'sim_stamp': now_sim,
                'truth_stamp': self.truth.stamp if self.truth else None,
                'truth_age_s': now_sim-self.truth.stamp if self.truth else None,
                'truth_receive_age_s': now_wall-self.truth.received if self.truth else None,
                'truth_fresh': truth_fresh, 'clock_fresh': clock_fresh,
                'contact': self.contact, 'charging': self.charging,
                'charging_enabled': self.charging_enabled,
                'contact_dwell_s': max(0., self.truth.stamp-self._contact_since)
                if self._contact_since is not None else 0.0,
                'reason': self.reason, 'soc': self.soc, 'current_a': self.current_a,
                'low_battery': self.soc <= c.low_soc, 'low_soc': c.low_soc, 'resume_soc': c.resume_soc,
                'discharge_time_scale': c.discharge_time_scale, 'charge_time_scale': c.charge_time_scale,
                'accepted_samples': self.accepted_samples, 'rejected_samples': self.rejected_samples,
                'distance_m': self.distance_m, 'charged_soc_total': self.charged_soc_total,
                'discharged_soc_total': self.discharged_soc_total,
                'contact_metrics': self.contact_metrics(self.truth) if self.truth else None}


def truth_from_message(message, received):
    """Validate the named MuJoCo free joint; no odometry or task-state fallback."""
    bodies = [b for b in message.free_joints if b.name == 'base_footprint']
    if len(bodies) != 1:
        raise ValueError('Expected exactly one base_footprint free joint')
    body = bodies[0]
    p, q, velocity = body.pose.pose.position, body.pose.pose.orientation, body.twist.twist
    norm = sum(v*v for v in (q.x, q.y, q.z, q.w))
    if not math.isfinite(norm) or abs(norm-1.) > .01:
        raise ValueError('Invalid truth quaternion')
    # Reject toppled robots even when their planar projection lies on the dock.
    upright = 1.-2.*(q.x*q.x+q.y*q.y)
    if upright < math.cos(.2):
        raise ValueError('Robot is tilted beyond the dock contact model')
    stamp = message.header.stamp.sec+message.header.stamp.nanosec*1e-9
    yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
    return Truth(stamp, received, p.x, p.y, yaw, velocity.linear.x, velocity.linear.y, velocity.angular.z,
                 p.z, velocity.linear.z, velocity.angular.x, velocity.angular.y)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', type=Path, required=True)
    parser.add_argument('--initial-soc', type=float)
    parser.add_argument('--discharge-time-scale', type=float)
    parser.add_argument('--charge-time-scale', type=float)
    parser.add_argument('--disable-charging', action='store_true',
                        help='Fault injection: contact still sensed; charging current and SOC gain disabled')
    args = parser.parse_args()
    validate_environment(os.environ)
    semantic = json.loads(args.scene.read_text())
    overrides = semantic['dock'].setdefault('charge_model', {})
    for name in ('initial_soc', 'discharge_time_scale', 'charge_time_scale'):
        if getattr(args, name) is not None:
            overrides[name] = getattr(args, name)
    cfg = PowerConfig.from_scene(semantic)
    model = PowerModel(cfg, charging_enabled=not args.disable_charging)

    import rclpy
    from rclpy.clock import Clock, ClockType
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from geometry_msgs.msg import PoseStamped
    from mujoco_ros2_control_msgs.msg import FreeJointStateArray
    from sensor_msgs.msg import BatteryState
    from std_msgs.msg import String

    rclpy.init(args=[], domain_id=DOMAIN)
    node = Node('fishbot_sim_power', use_global_arguments=False,
                parameter_overrides=[Parameter('use_sim_time', value=True)])
    battery_pub = node.create_publisher(BatteryState, BATTERY_TOPIC, 1)
    beacon_pub = node.create_publisher(PoseStamped, BEACON_TOPIC, 1)
    status_pub = node.create_publisher(String, STATUS_TOPIC, 1)

    def now():
        return node.get_clock().now().nanoseconds*1e-9

    def on_truth(message):
        try:
            sample = truth_from_message(message, time.monotonic())
            model.ingest(sample, now(), time.monotonic())
        except (ValueError, OverflowError):
            model.rejected_samples += 1
            model.invalidate('malformed_truth')

    node.create_subscription(FreeJointStateArray, TRUTH_TOPIC, on_truth,
                             QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))

    def publish():
        if node.get_parameter('use_sim_time').value is not True:
            raise RuntimeError('Simulation clock was disabled')
        status = model.snapshot(now(), time.monotonic())
        healthy = status['truth_fresh'] and status['clock_fresh']
        battery = BatteryState()
        # Keep the source stamp, so publication cannot make frozen evidence fresh.
        stamp = model.truth.stamp if model.truth else 0.0
        ns = round(stamp*1e9)
        battery.header.stamp.sec, battery.header.stamp.nanosec = divmod(ns, 1000000000)
        battery.header.frame_id = 'base_footprint'
        battery.voltage = 10.5+2.1*model.soc
        battery.current = model.current_a
        battery.percentage = model.soc
        battery.charge = model.soc*cfg.capacity_ah
        battery.capacity = battery.design_capacity = cfg.capacity_ah
        battery.temperature = float('nan')
        battery.power_supply_status = (BatteryState.POWER_SUPPLY_STATUS_UNKNOWN if not healthy
            else BatteryState.POWER_SUPPLY_STATUS_CHARGING if model.charging
            else BatteryState.POWER_SUPPLY_STATUS_DISCHARGING)
        battery.power_supply_health = BatteryState.POWER_SUPPLY_HEALTH_UNKNOWN
        battery.power_supply_technology = BatteryState.POWER_SUPPLY_TECHNOLOGY_LION
        battery.present = True
        battery.location = 'MuJoCo simulated battery'
        battery.serial_number = 'SIMULATION-DOMAIN-98'
        battery_pub.publish(battery)
        status_pub.publish(String(data=json.dumps(status, allow_nan=False, separators=(',', ':'))))
        if healthy:
            beacon = PoseStamped()
            beacon.header = battery.header
            x, y, yaw = model.relative_beacon()
            beacon.pose.position.x, beacon.pose.position.y = x, y
            beacon.pose.orientation.z, beacon.pose.orientation.w = math.sin(yaw/2), math.cos(yaw/2)
            beacon_pub.publish(beacon)

    # A steady timer revokes charging even while /clock is paused.
    node.create_timer(.05, publish, clock=Clock(clock_type=ClockType.STEADY_TIME))
    node.get_logger().info(f'{MODEL_LABEL}; {BEACON_LABEL}; discharge x{cfg.discharge_time_scale}, charge x{cfg.charge_time_scale}')
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
