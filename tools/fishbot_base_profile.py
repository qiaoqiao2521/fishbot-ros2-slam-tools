#!/usr/bin/python3
"""Compose a source-attributed four-wheel plant for the existing ROS runtime.

This adapter changes native wheel bodies, actuators, mass/inertia, URDF,
controller arrays and costmap footprint together. It does not start ROS,
teleport a moving base or install an additional simulator.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco'
DEFAULT_PROFILE = ROOT / 'tools/config/base_profiles/jackal_j100.yaml'
ASSETS = PACKAGE / 'mjcf/jackal_j100'
WHEELS = ('front_left', 'rear_left', 'front_right', 'rear_right')


def _numbers(values):
    return ' '.join(f'{float(x):.12g}' for x in values)


def _scene(path):
    spec = importlib.util.spec_from_file_location('base_profile_lidar', ROOT/'tools/fishbot_lidar3d.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._scene_tree(Path(path))


def geometry(profile):
    """Conservative rectangle encloses official chassis AND all four tires."""
    c, d = profile['chassis'], profile['drivetrain']
    padding = profile.get('simulation_assumptions', {}).get('footprint_padding_m', .015)
    hx = max(c['length']/2, d['wheelbase']/2+d['wheel_radius'])
    hy = max(c['width']/2, d['track']/2+d['wheel_width']/2)
    return {'physical_half_extents': [hx, hy], 'padding_m': padding,
            'half_extents': [hx+padding, hy+padding],
            'planning_radius_m': math.hypot(hx+padding, hy+padding),
            'footprint': [[hx+padding, hy+padding], [hx+padding, -hy-padding],
                          [-hx-padding, -hy-padding], [-hx-padding, hy+padding]]}


def _robot(profile):
    c, d, a = profile['chassis'], profile['drivetrain'], profile['simulation_assumptions']
    # The ground projection stays at z=0 when the radius-.0345 wheel centers touch.
    height = d['wheel_radius']-d['wheel_vertical_offset']
    root = ET.Element('body', name='base_footprint', pos='0 0 0.002')
    ET.SubElement(root, 'freejoint', name='base_free_joint')
    base = ET.SubElement(root, 'body', name='base_link', pos=_numbers([0, 0, height]))
    ET.SubElement(base, 'inertial', pos=_numbers(c['com']), mass=str(c['mass']),
                  fullinertia=_numbers(c['inertia']))
    ET.SubElement(base, 'geom', name='base_collision', type='box',
                  pos=_numbers([0, 0, c['height']/2]),
                  size=_numbers([c['length']/2, c['width']/2, c['height']/2]),
                  rgba='.22 .25 .28 1')
    ET.SubElement(base, 'geom', name='jackal_body_visual', type='mesh', mesh='jackal_body_mesh',
                  # URDF fixed-axis rpy(pi/2,0,pi/2), not MJCF intrinsic xyz.
                  pos='0 0 -0.0655', quat='0.5 0.5 0.5 0.5',
                  contype='0', conaffinity='0', group='2', rgba='.32 .35 .38 1')
    old = ET.parse(PACKAGE/'mjcf/fishbot.xml').getroot()
    for name in ('laser_link', 'imu_link'):
        sensor_body = copy.deepcopy(old.find(f'.//body[@name="{name}"]'))
        if name == 'laser_link':
            sensor_body.set('pos', _numbers([0, 0, c['height']+a['laser_above_chassis_m']]))
        base.append(sensor_body)
    for name in WHEELS:
        xyz = [d['wheelbase']/2*(1 if name.startswith('front') else -1),
               d['track']/2*(1 if 'left' in name else -1), d['wheel_vertical_offset']]
        wheel = ET.SubElement(base, 'body', name=name+'_wheel_link', pos=_numbers(xyz))
        ET.SubElement(wheel, 'joint', name=name+'_wheel_joint', type='hinge', axis='0 1 0')
        ET.SubElement(wheel, 'inertial', pos='0 0 0', mass=str(d['wheel_mass']),
                      diaginertia=_numbers(d['wheel_inertia']))
        ET.SubElement(wheel, 'geom', name=name+'_wheel_collision', type='cylinder',
                      size=_numbers([d['wheel_radius'], d['wheel_width']/2]),
                      euler=f'{math.pi/2} 0 0', friction=_numbers(a['wheel_friction']),
                      priority=str(a.get('wheel_contact_priority', 1)),
                      rgba='.08 .08 .08 1')
        ET.SubElement(wheel, 'geom', name=name+'_wheel_visual', type='mesh', mesh='jackal_wheel_mesh',
                      euler=f'{math.pi/2} 0 0', contype='0', conaffinity='0', group='2',
                      rgba='.12 .12 .12 1')
    return root


def _description(robot, profile, output):
    """Generate TF/control description from the same bodies as native physics."""
    xacro = 'http://www.ros.org/wiki/xacro'
    ET.register_namespace('xacro', xacro)
    urdf = ET.Element('robot', name=profile['id'])
    for name, default in [('headless', 'true'), ('scene_path', str(output/'scene.xml')),
                          ('sim_speed_factor', '1.0')]:
        ET.SubElement(urdf, '{'+xacro+'}arg', name=name, default=default)
    for body in robot.iter('body'):
        link = ET.SubElement(urdf, 'link', name=body.get('name'))
        native_inertial = body.find('inertial')
        if native_inertial is not None:
            inertial = ET.SubElement(link, 'inertial')
            ET.SubElement(inertial, 'origin', xyz=native_inertial.get('pos', '0 0 0'))
            ET.SubElement(inertial, 'mass', value=native_inertial.get('mass'))
            inertia = native_inertial.get('fullinertia')
            values = list(map(float, inertia.split())) if inertia else list(map(float, native_inertial.get('diaginertia').split()))+[0, 0, 0]
            ET.SubElement(inertial, 'inertia', **dict(zip(('ixx', 'iyy', 'izz', 'ixy', 'ixz', 'iyz'), map(str, values))))
        for native in body.findall('geom'):
            if native.get('contype') == '0':
                continue
            for tag in ('visual', 'collision'):
                shape = ET.SubElement(link, tag)
                ET.SubElement(shape, 'origin', xyz=native.get('pos', '0 0 0'), rpy=native.get('euler', '0 0 0'))
                geom = ET.SubElement(shape, 'geometry')
                sizes = list(map(float, native.get('size').split()))
                if native.get('type') == 'box':
                    ET.SubElement(geom, 'box', size=_numbers([2*x for x in sizes]))
                elif native.get('type') == 'cylinder':
                    ET.SubElement(geom, 'cylinder', radius=str(sizes[0]), length=str(2*sizes[1]))
                elif native.get('type') == 'sphere':
                    ET.SubElement(geom, 'sphere', radius=str(sizes[0]))
                if tag == 'visual':
                    material = ET.SubElement(shape, 'material', name=body.get('name')+'_material')
                    ET.SubElement(material, 'color', rgba=native.get('rgba', '.3 .3 .3 1'))
        for child in body.findall('body'):
            hinge = child.find('joint')
            joint = ET.SubElement(urdf, 'joint', name=hinge.get('name') if hinge is not None else child.get('name')+'_joint',
                                  type='continuous' if hinge is not None else 'fixed')
            ET.SubElement(joint, 'parent', link=body.get('name'))
            ET.SubElement(joint, 'child', link=child.get('name'))
            ET.SubElement(joint, 'origin', xyz=child.get('pos', '0 0 0'), rpy=child.get('euler', '0 0 0'))
            if hinge is not None:
                ET.SubElement(joint, 'axis', xyz=hinge.get('axis', '0 1 0'))
    original = ET.parse(PACKAGE/'urdf/fishbot_mujoco.urdf.xacro').getroot().find('ros2_control')
    control = copy.deepcopy(original)
    for joint in list(control.findall('joint')):
        control.remove(joint)
    for name in WHEELS:
        joint = ET.SubElement(control, 'joint', name=name+'_wheel_joint')
        ET.SubElement(joint, 'command_interface', name='velocity')
        for interface in ('position', 'velocity', 'effort'):
            ET.SubElement(joint, 'state_interface', name=interface)
    urdf.append(control)
    ET.indent(urdf)
    ET.ElementTree(urdf).write(output/'robot.urdf.xacro', encoding='utf-8', xml_declaration=True)


def prepare(scene_path, output_dir, *, profile_path=None, nav2_path=None, controllers_path=None):
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    profile = yaml.safe_load(Path(profile_path or DEFAULT_PROFILE).read_text())
    if profile.get('id') != 'jackal_j100':
        raise ValueError('Unsupported base profile; original scene was not modified')
    tree = _scene(scene_path)
    old = tree.find('.//body[@name="base_footprint"]')
    if old is None:
        raise ValueError('Scene has no replaceable base_footprint body')
    # A base with attached cargo/arm needs its own explicit fixture, not silent deletion.
    old_joints = {x.get('name') for x in old.iter('joint')}
    robot = _robot(profile)
    for name in ('pos', 'quat', 'euler', 'axisangle', 'xyaxes', 'zaxis'):
        if old.get(name) is not None:
            robot.set(name, old.get(name))
    parent = next(p for p in tree.iter() if old in list(p))
    index = list(parent).index(old)
    parent.remove(old)
    parent.insert(index, robot)
    assets = tree.find('asset')
    if assets is None:
        assets = ET.SubElement(tree, 'asset')
    for name, filename in [('jackal_body_mesh', 'j100_base.stl'), ('jackal_wheel_mesh', 'outdoor.stl')]:
        existing = assets.find(f'mesh[@name="{name}"]')
        if existing is not None:
            assets.remove(existing)
        ET.SubElement(assets, 'mesh', name=name, file=str(ASSETS/filename))
    actuator = tree.find('actuator')
    if actuator is None:
        actuator = ET.SubElement(tree, 'actuator')
    for element in list(actuator):
        if element.get('joint') in old_joints:
            actuator.remove(element)
    a = profile['simulation_assumptions']
    for name in WHEELS:
        ET.SubElement(actuator, 'velocity', name=name+'_wheel_joint', joint=name+'_wheel_joint',
                      kv=str(a['velocity_servo_kv']), ctrllimited='true',
                      ctrlrange=_numbers([-a['wheel_speed_limit_rad_s'], a['wheel_speed_limit_rad_s']]),
                      forcelimited='true', forcerange=_numbers([-a['wheel_torque_limit_nm'], a['wheel_torque_limit_nm']]))
    ET.indent(tree)
    ET.ElementTree(tree).write(output/'scene.xml', encoding='utf-8', xml_declaration=True)
    _description(robot, profile, output)
    controllers = yaml.safe_load(Path(controllers_path or PACKAGE/'config/controllers.yaml').read_text())
    diff = controllers['diff_drive_controller']['ros__parameters']
    diff.update(left_wheel_names=[name+'_wheel_joint' for name in WHEELS if 'left' in name],
                right_wheel_names=[name+'_wheel_joint' for name in WHEELS if 'right' in name],
                wheel_radius=profile['drivetrain']['wheel_radius'],
                wheel_separation=profile['drivetrain']['track'], open_loop=False)
    localization = profile.get('localization', {})
    fusion = bool(localization.get('enabled', False))
    fusion_file = ''
    wheel_odom_topic = '/odom'
    if fusion:
        diff['enable_odom_tf'] = False
        wheel_odom_topic = localization.get('wheel_odom_topic', '/wheel/odom')
        controllers['controller_manager']['ros__parameters']['imu_sensor_broadcaster'] = {
            'type': 'imu_sensor_broadcaster/IMUSensorBroadcaster'}
        def covariance(variance):
            return [float(variance) if index in (0, 4, 8) else 0.0 for index in range(9)]
        controllers['imu_sensor_broadcaster'] = {'ros__parameters': {
            'sensor_name': 'imu', 'frame_id': 'imu_link',
            'static_covariance_orientation': covariance(localization.get('imu_orientation_variance', 1e-6)),
            'static_covariance_angular_velocity': covariance(localization.get('imu_angular_velocity_variance', 1e-6)),
            'static_covariance_linear_acceleration': covariance(.01),
        }}
        filter_config = yaml.safe_load((DEFAULT_PROFILE.parent/'j100_ekf.yaml').read_text())
        filter_params = filter_config['ekf_filter_node']['ros__parameters']
        filter_params.update(odom0=wheel_odom_topic,
                             imu0=localization.get('imu_topic', '/imu_sensor_broadcaster/imu'))
        fusion_file = str(output/'fusion.yaml')
        Path(fusion_file).write_text(yaml.safe_dump(filter_config, sort_keys=False))
    (output/'controllers.yaml').write_text(yaml.safe_dump(controllers, sort_keys=False))
    nav = yaml.safe_load(Path(nav2_path or PACKAGE/'config/nav2.yaml').read_text())
    geom = geometry(profile)
    controller = nav['controller_server']['ros__parameters']
    if 'rpp_rotation_max_angular_accel_rad_s2' in a:
        controller['FollowPath']['max_angular_accel'] = float(a['rpp_rotation_max_angular_accel_rad_s2'])
    for name in controller.get('progress_checker_plugins', []):
        checker = controller[name]
        if checker.get('plugin') in ('nav2_controller::SimpleProgressChecker',
                                     'nav2_controller::PoseProgressChecker'):
            checker['plugin'] = 'nav2_controller::PoseProgressChecker'
            checker['required_movement_angle'] = float(a.get('progress_angle_rad', .2))
    for name in ('local_costmap', 'global_costmap'):
        config = nav[name][name]['ros__parameters']
        # NavFn uses circular inflation. Circumscribe the complete tire/chassis
        # rectangle, rather than pretending half the track encloses the base.
        config.pop('footprint', None)
        config['robot_radius'] = geom['planning_radius_m']
        # Padding already belongs to the derived radius and oracle geometry.
        config['footprint_padding'] = 0.0
        # Preserve the original .30-.13 clearance gradient beyond the larger
        # base. Reusing .30 would truncate inflation inside this robot's body.
        config['inflation_layer']['inflation_radius'] = (
            geom['planning_radius_m']+float(a.get('inflation_margin_m', .17)))
    (output/'nav2.yaml').write_text(yaml.safe_dump(nav, sort_keys=False))
    receipt = {'id': profile['id'], 'label': profile['label'], 'source': profile['source'],
               'assumptions': profile['simulation_assumptions'], 'geometry': geom,
               'scene': str(output/'scene.xml'), 'robot_description_file': str(output/'robot.urdf.xacro'),
               'controllers_file': str(output/'controllers.yaml'), 'nav2': str(output/'nav2.yaml'),
               'fusion_file': fusion_file, 'imu_broadcaster': fusion,
               'localization_fusion': fusion, 'wheel_odom_topic': wheel_odom_topic,
               'localization': localization,
               'wheel_joints': [name+'_wheel_joint' for name in WHEELS],
               'laser_base_xyz': [0., 0., profile['drivetrain']['wheel_radius']-
                    profile['drivetrain']['wheel_vertical_offset']+profile['chassis']['height']+
                    profile['simulation_assumptions']['laser_above_chassis_m']],
               'scope': 'source-derived contact physics; not a calibrated J100 digital twin'}
    (output/'base-profile.json').write_text(json.dumps(receipt, indent=2, ensure_ascii=False)+'\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--profile')
    parser.add_argument('--nav2')
    parser.add_argument('--controllers')
    args = parser.parse_args()
    print(json.dumps(prepare(args.scene, args.output, profile_path=args.profile,
                             nav2_path=args.nav2, controllers_path=args.controllers), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
