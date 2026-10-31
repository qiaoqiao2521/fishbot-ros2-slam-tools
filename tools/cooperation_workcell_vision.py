"""Fixed workcell RGB-D cameras and an explicitly declared green-colour prior.

Only ``render_rgbd`` receives simulation state. ``object_points`` receives RGB,
metric optical-Z depth and fixed calibration. Slot centres are inventory/layout
configuration, never queried from MuJoCo's object poses or segmentation buffers.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import numpy as np


def add_workcell_cameras(root_xml, manifest):
    """Add fixed oblique cameras and return configurations indexed by arm ID.

    The optical frame uses +X right, +Y down and +Z forward. All transforms in
    the returned configuration are relative to the fixed arm station frame.
    """
    root = root_xml.getroot() if hasattr(root_xml, 'getroot') else root_xml
    entities = manifest.get('business_entities', {})
    arms = entities.get('arms') or {
        'load': {'root_body': 'base',
                 'station_position_m': manifest.get('station_offset', [0., 0., 0.])}}
    inventory = entities.get('cargo', {})
    mount = np.array([.45, -.50, .60])
    forward = np.array([.24, -.04, .025]) - mount
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, [0., 0., 1.])
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    optical_rotation = np.column_stack((right, -up, forward))
    optical_transform = np.eye(4)
    optical_transform[:3, :3] = optical_rotation
    optical_transform[:3, 3] = mount
    configs = {}
    for arm_id, arm in arms.items():
        name = 'workcell_' + arm_id + '_camera'
        yaw = float(arm.get('station_yaw_rad', 0.))
        c, s = math.cos(yaw), math.sin(yaw)
        station_rotation = np.array([[c, -s, 0.], [s, c, 0.], [0., 0., 1.]])
        station_position = np.asarray(arm['station_position_m'], dtype=float)
        world_mount = station_rotation @ mount + station_position
        world_axes = np.r_[station_rotation @ right, station_rotation @ up]
        body = root.find('worldbody')
        if body.find("camera[@name='%s']" % name) is None:
            ET.SubElement(body, 'camera', name=name, pos=' '.join(map(str, world_mount)),
                          xyaxes=' '.join(map(str, world_axes)), fovy='45', resolution='640 480')
        width, height = 640, 480
        focal = .5 * height / math.tan(math.radians(45.) / 2.)
        if arm_id == 'load':
            slots = {cargo_id: [.24 + value.get('pickup_offset_m', [0., 0., 0.])[0],
                               -.13 + value.get('pickup_offset_m', [0., 0., 0.])[1]]
                     for cargo_id, value in inventory.items()}
            slots = slots or {'cargo_1': [.24, -.13], 'cargo_2': [.24, -.09]}
            # A narrow slot gate separates inventory spaced 4 cm apart, even
            # when image components touch after perspective/lighting effects.
            half_extent = [.035, .019]
        else:
            station = next((v for v in entities.get('configuration', {}).get(
                'unload_stations', []) if v.get('arm_id') == arm_id), {})
            pickup = list(station.get('pickup_xy_m', [.24, .04]))
            slots = {cargo_id: pickup for cargo_id in inventory} or {'cargo_1': pickup}
            half_extent = [.07, .07]
        configs[arm_id] = {
            'name': name, 'frame_id': name + '_optical_frame',
            'width': width, 'height': height, 'fovy': 45.,
            'k': [focal, 0., (width-1)/2., 0., focal, (height-1)/2., 0., 0., 1.],
            'T_station_camera': optical_transform.tolist(),
            'slots_station_xy': slots, 'slot_half_extent_m': half_extent,
            'target_id': next(iter(slots)),
            'minimum_points': 25, 'depth_range_m': [.05, 1.5],
            'colour_prior': {'name': 'declared_green_cargo',
                             'green_to_red_min': 1.22,
                             'green_to_blue_min': 1.12,
                             'green_min_u8': 35},
            'mask_method': 'rgb_connected_component_in_fixed_inventory_slot',
            'point_source': 'visible_rgbd_surface_only',
        }
    return configs


def render_rgbd(model, data, camera):
    """Render RGB and aligned optical-Z metres at one immutable physics state."""
    import mujoco
    options = mujoco.MjvOption()
    options.geomgroup[:] = 1
    options.sitegroup[:] = 0
    with mujoco.Renderer(model, height=int(camera['height']),
                         width=int(camera['width'])) as renderer:
        renderer.update_scene(data, camera=camera['name'], scene_option=options)
        rgb = renderer.render().copy()
        renderer.enable_depth_rendering()
        depth = renderer.render().copy().astype(np.float32)
    return rgb, depth


def object_points(rgb, depth, camera):
    """Select one visible green component near a declared fixed inventory slot.

    This deliberately limited colour prior is not open-vocabulary recognition.
    Missing, occluded or out-of-slot cargo raises a specific observation error;
    it never substitutes complete CAD geometry or a simulated cargo position.
    """
    import cv2
    rgb, depth = np.asarray(rgb), np.asarray(depth)
    expected = (int(camera['height']), int(camera['width']))
    if rgb.shape != expected + (3,) or depth.shape != expected:
        raise ValueError('Workcell RGB and depth dimensions do not match calibration')
    K = np.asarray(camera['k'], dtype=float).reshape(3, 3)
    u, v = np.meshgrid(np.arange(expected[1]), np.arange(expected[0]))
    points = np.stack(((u-K[0, 2])*depth/K[0, 0],
                       (v-K[1, 2])*depth/K[1, 1], depth), axis=-1)
    T = np.asarray(camera['T_station_camera'], dtype=float)
    station = points @ T[:3, :3].T + T[:3, 3]
    target = camera.get('target_id', next(iter(camera['slots_station_xy'])))
    if target not in camera['slots_station_xy']:
        raise ValueError('Unknown declared inventory slot: ' + str(target))
    center = np.asarray(camera['slots_station_xy'][target], dtype=float)
    half_extent = np.asarray(camera['slot_half_extent_m'], dtype=float)
    rgb_float = rgb.astype(float)
    r, g, b = rgb_float[..., 0], rgb_float[..., 1], rgb_float[..., 2]
    prior = camera['colour_prior']
    colour = ((g >= prior['green_min_u8']) &
              (g >= r*prior['green_to_red_min']) &
              (g >= b*prior['green_to_blue_min']))
    near, far = camera.get('depth_range_m', [.05, 1.5])
    valid_depth = np.isfinite(depth) & (depth >= near) & (depth <= far)
    in_slot = np.all(np.abs(station[..., :2] - center) <= half_extent, axis=-1)
    selected = (colour & valid_depth & in_slot).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(selected, 8)
    minimum = int(camera.get('minimum_points', 25))
    candidates = [i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] >= minimum]
    if not candidates:
        raise ValueError('No visible declared-green cargo in inventory slot ' + str(target))
    # Rank image components by observed distance to the declared slot. Depth
    # disambiguates objects behind the slot without using any object truth.
    best = min(candidates, key=lambda i: (
        float(np.linalg.norm(np.median(station[labels == i, :2], axis=0)-center)),
        -int(stats[i, cv2.CC_STAT_AREA])))
    mask = labels == best
    return {'points_camera': np.ascontiguousarray(points[mask], dtype=np.float32),
            'mask': mask, 'target_id': target,
            'mask_kind': 'declared_colour_prior',
            'point_count': int(np.count_nonzero(mask))}
