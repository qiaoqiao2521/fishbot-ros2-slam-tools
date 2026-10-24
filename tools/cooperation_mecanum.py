"""Mecanum contact model and encoder kinematics for the shared MuJoCo world.

Roller pin construction adapted from JunHeonYoon/mujoco_mecanum (MIT, 2023).
See licenses/mujoco_mecanum.MIT. Dimensions come from the merged robot_base;
unmeasured chassis, mass and roller dimensions are explicit simulation assumptions.
"""
import math
from pathlib import Path
import xml.etree.ElementTree as ET

WHEELS = ('front_left', 'rear_left', 'front_right', 'rear_right')
RADIUS = .0485
TRACK = .445
WHEELBASE = .17
K = (TRACK + WHEELBASE) / 2
ROLLERS = 12
ROLLER_RADIUS = .0095


def inverse(vx, vy, wz, radius=RADIUS, k=K):
    return tuple(v / radius for v in (vx-vy-k*wz, vx+vy-k*wz, vx+vy+k*wz, vx-vy+k*wz))


def forward(wheels, radius=RADIUS, k=K):
    a, b, c, d = (float(value)*radius for value in wheels)
    return ((a+b+c+d)/4, (-a+b+c-d)/4, (-a-b+c+d)/(4*k))


class MecanumOdometry:
    """Integrate four hinge encoders only; never reads body truth or roller state."""
    def __init__(self, *wheels, radius=RADIUS, k=K):
        self.previous = tuple(wheels)
        self.radius, self.k = radius, k
        self.x = self.y = self.yaw = self.lateral_velocity = 0.

    def rebase(self, wheels):
        self.previous = tuple(wheels)

    def update(self, *readings):
        *wheels, dt = readings
        vx, vy, wz = forward([(a-b)/dt for a, b in zip(wheels, self.previous)], self.radius, self.k)
        self.previous = tuple(wheels)
        middle = self.yaw + wz*dt/2
        self.x += (vx*math.cos(middle)-vy*math.sin(middle))*dt
        self.y += (vx*math.sin(middle)+vy*math.cos(middle))*dt
        self.yaw += wz*dt
        self.lateral_velocity = vy
        return vx, wz


def passive_joint_names():
    return [f'{name}_roller_{index}_joint' for name in WHEELS for index in range(ROLLERS)]


def vehicle_profile():
    root = Path(__file__).resolve().parents[1]
    base_z, tray_z = .10, .12
    return {
        'id': 'robot_base_mecanum', 'label': 'robot_base Mecanum', 'spawn_free_z_m': .002,
        'wheel_radius_m': RADIUS, 'wheel_separation_m': TRACK,
        'left_wheel_joints': [name+'_wheel_joint' for name in WHEELS[:2]],
        'right_wheel_joints': [name+'_wheel_joint' for name in WHEELS[2:]],
        'passive_joints': passive_joint_names(), 'base_link_z_m': base_z,
        'drive': {'type': 'mecanum_x', 'wheelbase_m': WHEELBASE, 'kinematic_k_m': K,
                  'physical_track_m': TRACK, 'effective_track_multiplier': 1.,
                  'wheel_order': list(WHEELS), 'encoder_truth_feedback': False},
        'tray_offset_m': [-.16, -.22, tray_z], 'dock_offset_m': [.40, .36, 0.],
        'station_height_delta_m': base_z+tray_z-(.092+.067),
        'tray_mount': {'size_m': [.04, .04, .08], 'position_in_tray_m': [0., .055, -.04],
                       'mass_kg': .3456, 'basis': 'assumed_rigid_aluminium_standoff',
                       'support_assumptions': {'chassis_vertical_overlap_m': .01,
                           'density_kg_m3': 2700., 'strength_or_fasteners_validated': False}},
        'installation': {'nominal_handover_xy_station_m': [.24, .14],
                         'handover_unchanged': True, 'base_lateral_clearance_shift_m': .04,
                         'basis': 'wide shell installation; tray remains at original arm handover'},
        'planning_radius_m': math.hypot(.25, .26),
        'footprint_xy': [[.25, .26], [.25, -.26], [-.25, -.26], [-.25, .26]],
        'localization': {'enabled': False},
        'navigation': {'max_angular_accel': 2., 'rotate_to_heading_angular_vel': .4, 'stopped_goal_checker': True},
        'transport_egress': 'staging',
        'transport_egress_motion': {'type': 'drive_on_heading', 'speed_m_s': .03, 'time_allowance_s': 45.},
        'source_files': [str(Path(__file__).resolve()), str(root/'tools/licenses/mujoco_mecanum.MIT'),
                         str(root/'workspaces/mecanum_ws/src/robot_base/robot_base/drive_node.py'),
                         str(root/'workspaces/mecanum_ws/src/robot_base/config/nav2_params.yaml')],
        'simulation_assumptions': {
            'source': 'MIT JunHeonYoon/mujoco_mecanum roller pin construction; capsule adaptation',
            'chassis_size_m': [.50, .52, .10], 'chassis_mass_kg': 6.,
            'body_height_and_mass_measured': False, 'dimensions_basis': 'legacy navigation body .50x.52m, padding excluded',
            'wheel_hub_mass_kg': .25, 'roller_mass_kg': .01, 'rollers_per_wheel': ROLLERS,
            'roller_radius_m': ROLLER_RADIUS, 'roller_geometry': 'capsule approximation',
            'roller_angle_deg': 45., 'roller_bearing_damping': .0001,
            'wheel_velocity_servo_kv': .5, 'wheel_torque_limit_nm': 1.5,
            'internal_wheel_assembly_collision': 'filtered; all external collision retained',
            'real_hardware_calibrated': False, 'online_truth_correction': False,
        },
    }


def vehicle_element():
    root = ET.Element('mujoco', model='robot_base_mecanum')
    ET.SubElement(root, 'compiler', angle='radian', autolimits='true')
    defaults = ET.SubElement(root, 'default')
    ET.SubElement(defaults, 'geom', friction='.8 .005 .0001', condim='3', solref='.01 1')
    car = ET.SubElement(ET.SubElement(root, 'worldbody'), 'body', name='base_footprint')
    ET.SubElement(car, 'freejoint', name='base_free_joint')
    base = ET.SubElement(car, 'body', name='base_link', pos='0 0 .10')
    imu = ET.SubElement(base, 'body', name='imu_link', pos='0 0 0')
    ET.SubElement(imu, 'site', name='imu_site', pos='0 0 0', size='.005', rgba='0 0 1 0')
    ET.SubElement(base, 'geom', name='mecanum_chassis', type='box', size='.25 .26 .05', mass='6',
                  contype='4', conaffinity='3', rgba='.13 .28 .48 1')
    ET.SubElement(base, 'body', name='laser_link', pos='0 0 .10')
    actuators = ET.SubElement(root, 'actuator')
    sensors = ET.SubElement(root, 'sensor')
    ET.SubElement(sensors, 'framequat', name='imu_quat', objtype='site', objname='imu_site')
    ET.SubElement(sensors, 'gyro', name='imu_gyro', site='imu_site')
    ET.SubElement(sensors, 'accelerometer', name='imu_accel', site='imu_site')
    center_radius = RADIUS-ROLLER_RADIUS
    # Equal tangent chord and axial span produce a 45-degree roller axle.
    width = 2*center_radius*math.sin(math.pi/ROLLERS)
    for name, x, y, hand in zip(WHEELS, [.085, -.085, .085, -.085], [.2225, .2225, -.2225, -.2225], [-1, 1, 1, -1]):
        wheel = ET.SubElement(base, 'body', name=name+'_wheel', pos=f'{x} {y} {RADIUS-.10}')
        joint = name+'_wheel_joint'
        ET.SubElement(wheel, 'joint', name=joint, type='hinge', axis='0 1 0', damping='.005', frictionloss='.002')
        ET.SubElement(wheel, 'geom', name=name+'_hub', type='cylinder', size=f'{center_radius*.65} {width/2}',
                      quat='.7071067811865476 .7071067811865476 0 0', mass='.25', contype='4', conaffinity='3', rgba='.12 .12 .14 1')
        for index in range(ROLLERS):
            a = 2*math.pi*index/ROLLERS
            b = a + hand*2*math.pi/ROLLERS
            pin1 = (center_radius*math.cos(a), -width/2, center_radius*math.sin(a))
            pin2 = (center_radius*math.cos(b), width/2, center_radius*math.sin(b))
            axis = tuple(v-u for u, v in zip(pin1, pin2))
            midpoint = tuple((u+v)/2 for u, v in zip(pin1, pin2))
            roller = ET.SubElement(wheel, 'body', name=f'{name}_roller_{index}', pos=' '.join(map(str, midpoint)))
            ET.SubElement(roller, 'joint', name=f'{name}_roller_{index}_joint', type='hinge',
                          axis=' '.join(map(str, axis)), damping='.0001', frictionloss='.00001')
            endpoints = [v/2 for v in axis]
            ET.SubElement(roller, 'geom', name=f'{name}_roller_{index}_collision', type='capsule',
                          fromto=' '.join(map(str, [-v for v in endpoints]+endpoints)), size=str(ROLLER_RADIUS),
                          mass='.01', contype='4', conaffinity='3', rgba='.20 .22 .24 1')
        ET.SubElement(actuators, 'velocity', name=joint, joint=joint, kv='.5',
                      ctrllimited='true', ctrlrange='-10 10', forcelimited='true', forcerange='-1.5 1.5')
    return root, car
