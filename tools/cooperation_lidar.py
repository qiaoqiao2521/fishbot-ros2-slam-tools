"""Native 3-D ray sensor for the existing Python MuJoCo common world.

The installed 3.12 C++ extension cannot load into this 3.3.7 world. This thin
adapter uses its documented spherical beam layout and the same native
mj_multiRay API, without a second executing world or a hand-written ROS codec.
This generic ideal sensor is not a calibrated commercial lidar.
"""
from __future__ import annotations

import math
import threading
import time
from typing import Any

from cooperation_camera import LatestCameraSnapshot

POINTS_TOPIC = '/sensors/lidar3d/points'
RAW_POINTS_TOPIC = '/sensors/lidar3d/points_raw'
METADATA_TOPIC = '/sensors/lidar3d/frame_metadata'
FRAME_ID = 'lidar3d_link'


def configuration(manifest: dict[str, Any]) -> dict[str, Any] | None:
    scene = manifest.get('scene_profile', {})
    mode = scene.get('sensors', 'planar')
    if mode == 'planar':
        return None
    if mode != 'lidar3d':
        raise ValueError('scene_profile.sensors must be planar or lidar3d')
    c = {'frame_id': FRAME_ID, 'parent_body': 'laser_link', 'mount_xyz': [0., 0., .035],
         'horizontal_samples': 360, 'lines': 16, 'vertical_degrees': [-15., 15.],
         'min_range_m': .12, 'max_range_m': 8., 'rate_hz': 10.,
         'topic': POINTS_TOPIC, 'metadata_topic': METADATA_TOPIC,
         'basis': 'native_mj_multiRay_generic_instantaneous_16_line_sensor',
         'layout_source': 'ros-controls/mujoco_ros2_control/0.1.1/mujoco_extensions/mujoco_3d_lidar',
         'plugin_3_12_loaded': False}
    c.update(manifest.get('lidar3d', {}))
    envelope = manifest.get('transport_height_envelope', {})
    footprint = manifest.get('car_footprint_xy')
    declared = bool(footprint and envelope.get('compiled_collision_components'))
    nominal_z = envelope.get('nominal_base_footprint_world_z_m', 0.)
    self_filter = {'enabled': declared, 'type': 'compiled_body_convex_containment',
                   'frame_id': 'base_footprint', 'footprint_xy': footprint,
                   'padding_xy_m': 0.,
                   'z_min_m': min((part['bottom_world_m'] for part in
                       envelope.get('compiled_collision_components', [])), default=nominal_z)-nominal_z,
                   'z_max_m': envelope.get('unpadded_top_world_m',
                       envelope.get('max_obstacle_height_m', nominal_z)-
                       envelope.get('existing_footprint_padding_m', 0.))-nominal_z,
                   'basis': 'compiled full vehicle footprint and declared rigid loaded height envelope',
                   'decision_inputs': 'source-stamped point coordinates only; no task, cargo identity or contact state',
                   'removed_value': 'NaN', 'reraycast_removed_rays': False}
    self_filter.update(c.get('self_filter', {}))
    c['self_filter'] = self_filter
    c['raw_topic'] = RAW_POINTS_TOPIC
    return c


def beam_directions(c: dict[str, Any]):
    import numpy as np
    azimuth = np.arange(c['horizontal_samples']) * (2 * math.pi / c['horizontal_samples']) - math.pi
    elevation = np.linspace(*np.radians(c['vertical_degrees']), c['lines'])
    a, e = np.meshgrid(azimuth, elevation)
    return np.column_stack((np.cos(a).ravel() * np.cos(e).ravel(),
                            np.sin(a).ravel() * np.cos(e).ravel(), np.sin(e).ravel()))


def body_contains(points_base, halfspaces, config):
    import numpy as np
    inside = np.all(points_base[:, :2] @ halfspaces[:, :2].T + halfspaces[:, 2]
                    <= config['padding_xy_m'] + 1e-7, axis=1)
    return (inside & (points_base[:, 2] >= config['z_min_m']-1e-7)
            & (points_base[:, 2] <= config['z_max_m']+1e-7))


class NativeCloudQuery:
    """A read-only query clone; qpos copies never write the executing plant."""
    def __init__(self, scene, c):
        import mujoco
        import numpy as np
        self.mj, self.np, self.config = mujoco, np, c
        self.model = mujoco.MjModel.from_xml_path(str(scene))
        self.data = mujoco.MjData(self.model)
        self.laser = self.model.body(c['parent_body']).id
        car = self.model.body('base_footprint').id
        self.car = car
        self.body_halfspaces = None
        self_filter = c.get('self_filter', {})
        if self_filter.get('enabled'):
            from scipy.spatial import ConvexHull
            if self_filter['frame_id'] != 'base_footprint':
                raise ValueError('The compiled self filter requires base_footprint coordinates')
            footprint = np.asarray(self_filter['footprint_xy'], dtype=float)
            if (footprint.ndim != 2 or footprint.shape[1] != 2 or len(footprint) < 3
                    or not np.isfinite(footprint).all()):
                raise ValueError('The self filter requires a finite full vehicle footprint')
            bounds = [self_filter[name] for name in ('padding_xy_m', 'z_min_m', 'z_max_m')]
            if (not all(math.isfinite(value) for value in bounds) or bounds[0] < 0
                    or bounds[1] >= bounds[2]):
                raise ValueError('The compiled self filter requires finite nonempty bounds')
            self.body_halfspaces = ConvexHull(footprint).equations
        descendants = {car}
        for body in range(self.model.nbody):
            if int(self.model.body_parentid[body]) in descendants:
                descendants.add(body)
        for geom in range(self.model.ngeom):
            if int(self.model.geom_bodyid[geom]) in descendants:
                self.model.geom_group[geom] = 5
            elif not (self.model.geom_contype[geom] or self.model.geom_conaffinity[geom]):
                self.model.geom_group[geom] = 4
        self.groups = np.array([1, 1, 1, 1, 0, 0], dtype=np.uint8)
        self.directions = beam_directions(c)
        self.ranges = np.empty(len(self.directions), dtype=float)
        self.hit = np.empty(len(self.directions), dtype=np.int32)

    def compute(self, snapshot):
        c, np, started = self.config, self.np, time.monotonic()
        # Same convention as the existing camera query clone: copy immutable
        # source state, refresh kinematics/sensors, and never mj_step this data.
        self.data.qpos[:] = snapshot['qpos']
        self.data.qvel[:] = snapshot['qvel']
        self.data.time = snapshot['stamp']
        self.mj.mj_forward(self.model, self.data)
        rotation = self.data.xmat[self.laser].reshape(3, 3)
        origin = self.data.xpos[self.laser] + rotation @ np.asarray(c['mount_xyz'])
        rays = (self.directions @ rotation.T).reshape(-1)
        self.mj.mj_multiRay(self.model, self.data, origin, rays, self.groups,
                            1, -1, self.hit, self.ranges, len(self.directions), c['max_range_m'])
        valid = np.isfinite(self.ranges) & (self.ranges >= c['min_range_m']) & (self.ranges < c['max_range_m'])
        raw_points = (self.directions * self.ranges[:, None]).astype(np.float32)
        raw_points[~valid] = np.nan
        points = raw_points.copy()
        removed = np.zeros(len(points), dtype=bool)
        if self.body_halfspaces is not None:
            self_filter = c['self_filter']
            # Filter the actual first return, never re-cast through a load.
            # The containment volume is declared before the episode; it does
            # not inspect hit IDs, attachment status, contacts or task stages.
            world = points @ rotation.T + origin
            base = ((world-self.data.xpos[self.car]) @
                    self.data.xmat[self.car].reshape(3, 3))
            removed = valid & body_contains(base, self.body_halfspaces, self_filter)
            points[removed] = np.nan
        filtered_valid = valid & ~removed
        return {'points': points, 'snapshot': snapshot, 'compute_duration_s': time.monotonic()-started,
                'raw_points': raw_points, 'raw_valid_points': int(valid.sum()),
                'self_filter_removed_points': int(removed.sum()),
                'valid_points': int(filtered_valid.sum()),
                'native_version': self.mj.__version__,
                'rows_with_returns': int(filtered_valid.reshape(c['lines'], c['horizontal_samples']).any(axis=1).sum()),
                'z_min': float(points[filtered_valid, 2].min()) if filtered_valid.any() else None,
                'z_max': float(points[filtered_valid, 2].max()) if filtered_valid.any() else None}


def pointcloud_message(points, snapshot, c):
    from std_msgs.msg import Header
    from sensor_msgs_py import point_cloud2
    header = Header(frame_id=c['frame_id'])
    header.stamp.sec, header.stamp.nanosec = divmod(round(snapshot['stamp']*1e9), 1_000_000_000)
    cloud = point_cloud2.create_cloud_xyz32(header, points)
    cloud.width, cloud.height = c['horizontal_samples'], c['lines']
    cloud.row_step = cloud.point_step * cloud.width
    return cloud


def raw_frame_message(frame, c):
    return pointcloud_message(frame['raw_points'], frame['snapshot'], c)


def frame_messages(frame, c):
    from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
    snapshot = frame['snapshot']
    # Standard serializer accepts a flat float32 XYZ array. Our storage is
    # elevation-major, hence its bytes are valid 16 rows of 360 column points.
    cloud = pointcloud_message(frame['points'], snapshot, c)
    status = DiagnosticStatus(name='cooperation_lidar3d_frame', hardware_id='native_generic_16_line',
                              level=DiagnosticStatus.OK, message='captured_native_rays')
    evidence = {k: snapshot[k] for k in ('scene_sha256', 'manifest_sha256', 'episode_id', 'sequence')}
    evidence.update({k: frame[k] for k in ('compute_duration_s', 'valid_points', 'rows_with_returns', 'native_version')})
    evidence.update(instantaneous_scan=True, plugin_3_12_loaded=False,
                    self_filter_enabled=c.get('self_filter', {}).get('enabled', False),
                    self_filter_removed_points=frame.get('self_filter_removed_points', 0),
                    raw_valid_points=frame.get('raw_valid_points', frame['valid_points']),
                    raw_topic=c.get('raw_topic', RAW_POINTS_TOPIC))
    status.values = [KeyValue(key=k, value=str(v).lower() if isinstance(v, bool) else str(v)) for k, v in evidence.items()]
    metadata = DiagnosticArray(header=cloud.header, status=[status])
    return cloud, metadata


class CloudWorker:
    """One replaceable source snapshot and one native query worker."""
    def __init__(self, physics, c, publish, *, publish_raw=None):
        self.physics, self.config, self.publish = physics, c, publish
        self.publish_raw = publish_raw
        self.slot = LatestCameraSnapshot()
        self.wake, self.stop = threading.Event(), threading.Event()
        self.error = None
        self.ready = False
        self.frames = 0
        self.raw_frames = self.removed_points = 0
        self.last = None
        self.max_compute_s = 0.
        self.thread = threading.Thread(target=self.run, name='cooperation-lidar3d-query', daemon=True)
        self.thread.start()

    def offer(self, source_sequence=None):
        snapshot = {'qpos': self.physics.data.qpos.copy(), 'qvel': self.physics.data.qvel.copy(),
                    'stamp': float(self.physics.data.time),
                    'sequence': self.physics.state_sequence if source_sequence is None else source_sequence,
                    'episode_id': self.physics.episode_id,
                    'scene_sha256': self.physics.identity['scene_sha256'],
                    'manifest_sha256': self.physics.identity['manifest_sha256']}
        self.slot.offer(snapshot)
        self.wake.set()

    def run(self):
        try:
            query = NativeCloudQuery(self.physics.scene, self.config)
            self.ready = True
            while not self.stop.is_set():
                self.wake.wait(.1)
                self.wake.clear()
                snapshot = self.slot.take()
                if snapshot is None:
                    continue
                frame = query.compute(snapshot)
                # Reset fences publication as well as pending queries. The
                # physical owner never waits for ray computation or codec work.
                messages = frame_messages(frame, self.config)
                raw = raw_frame_message(frame, self.config) if self.publish_raw is not None else None
                with self.slot.lock:
                    if snapshot['episode_id'] != self.slot.episode_id:
                        continue
                    self.publish(*messages)
                    if raw is not None:
                        self.publish_raw(raw)
                self.frames += 1
                self.raw_frames += raw is not None
                self.removed_points += frame.get('self_filter_removed_points', 0)
                self.max_compute_s = max(self.max_compute_s, frame['compute_duration_s'])
                self.last = {k: frame[k] for k in ('compute_duration_s', 'valid_points', 'rows_with_returns', 'z_min', 'z_max', 'native_version')}
                self.last.update(stamp=snapshot['stamp'], episode_id=snapshot['episode_id'], sequence=snapshot['sequence'])
                self.last.update(self_filter_removed_points=frame.get('self_filter_removed_points', 0),
                                 raw_valid_points=frame.get('raw_valid_points', frame['valid_points']))
        except Exception as error:
            self.error = f'{type(error).__name__}: {error}'

    def summary(self):
        return {'enabled': True, 'ready': self.ready, 'error': self.error,
                'published_frames': self.frames, 'overwritten_pending_snapshots': self.slot.overwritten,
                'raw_published_frames': self.raw_frames,
                'self_filter_removed_points_total': self.removed_points,
                'max_compute_s': self.max_compute_s, 'last_frame': dict(self.last) if self.last else None,
                'profile': dict(self.config), 'plant_stepped_by_sensor_worker': False}

    def close(self):
        self.stop.set(); self.wake.set()
        self.thread.join(timeout=2.)
