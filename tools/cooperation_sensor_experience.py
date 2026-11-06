#!/usr/bin/env python3
"""Read-only same-source lidar/truth capture for the results workbench.

Only this observer sees physics truth. It creates no publisher, action client or
service that writes control. Native geometry is queried in an independent data
clone with mj_kinematics; no mj_step or controller feedback uses it.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
import json
import math
from pathlib import Path
import time


def stamp_ns(message):
    return int(message.header.stamp.sec)*1_000_000_000+int(message.header.stamp.nanosec)


def metadata_values(message):
    status = next((item for item in message.status if item.name == 'cooperation_lidar3d_frame'), None)
    return {item.key: item.value for item in status.values} if status else {}


def matching_state(metadata, state, source_stamp_ns):
    """Do not borrow a nearby or new-episode pose to fill a missing source."""
    try:
        identities = state.get('source', {})
        checks = (
            str(metadata.get('sequence')) == str(state.get('sequence')),
            str(metadata.get('episode_id')) == str(state.get('episode_id')),
            str(metadata.get('scene_sha256')) == str(identities.get('scene_sha256')),
            str(metadata.get('manifest_sha256')) == str(identities.get('manifest_sha256')),
            round(float(state['stamp'])*1e9) == source_stamp_ns,
        )
        return all(checks) and all(metadata.get(name) for name in
            ('sequence', 'episode_id', 'scene_sha256', 'manifest_sha256'))
    except (ValueError, TypeError, KeyError):
        return False


class TruthProjection:
    """Box wireframes in the actual lidar frame, never a controller input."""
    def __init__(self, manifest):
        import mujoco
        import numpy as np
        from cooperation_lidar import configuration
        self.mj, self.np = mujoco, np
        self.config = configuration(manifest)
        self.model = mujoco.MjModel.from_xml_path(manifest['world_xml'])
        self.data = mujoco.MjData(self.model)
        self.laser = self.model.body(self.config['parent_body']).id
        car = self.model.body('base_footprint').id
        self.self_bodies = {car}
        for body in range(self.model.nbody):
            if int(self.model.body_parentid[body]) in self.self_bodies:
                self.self_bodies.add(body)

    def project(self, state):
        np, model, data = self.np, self.model, self.data
        data.qpos[:] = state['qpos']
        data.qvel[:] = state['qvel']
        data.time = float(state['stamp'])
        self.mj.mj_kinematics(model, data)
        rotation = data.xmat[self.laser].reshape(3, 3)
        origin = data.xpos[self.laser]+rotation@np.asarray(self.config['mount_xyz'])
        boxes = []; omitted = 0
        for i in range(model.ngeom):
            if not (model.geom_contype[i] or model.geom_conaffinity[i]):
                continue
            if int(model.geom_bodyid[i]) in self.self_bodies:
                continue
            if int(model.geom_type[i]) != self.mj.mjtGeom.mjGEOM_BOX:
                omitted += 1
                continue
            corners = np.array([[x, y, z] for x in (-1., 1.) for y in (-1., 1.) for z in (-1., 1.)])
            world = (corners*model.geom_size[i])@data.geom_xmat[i].reshape(3, 3).T+data.geom_xpos[i]
            vertices = (world-origin)@rotation
            boxes.append({'id': model.geom(i).name, 'vertices': vertices.tolist()})
        return {'boxes': boxes, 'omitted_nonbox_collision_geometries': omitted,
                'source': 'compiled_collision_box_corners_at_exact_matched_physics_source',
                'frame_id': self.config['frame_id'], 'reference_only': True,
                'scope': 'box wireframes only; occluded geometry included; not a complete mesh render'}


def observe(manifest_path, output, *, timeout=30., frames=3, separation_source_s=.5):
    import rclpy
    import numpy as np
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from rclpy.parameter import Parameter
    from rclpy.time import Time
    from tf2_ros import Buffer, TransformListener, TransformException
    from sensor_msgs.msg import PointCloud2
    from sensor_msgs_py import point_cloud2
    from diagnostic_msgs.msg import DiagnosticArray
    from std_msgs.msg import String
    from cooperation_lidar import POINTS_TOPIC, METADATA_TOPIC, configuration

    manifest = json.loads(Path(manifest_path).read_text()); config = configuration(manifest)
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    truth = TruthProjection(manifest)
    report = {'schema': 'fishbot.sensor-experience.v1', 'status': 'incomplete',
              'new_execution': False, 'read_only': True, 'rescored': False,
              'frame_id': config['frame_id'], 'sensor': config,
              'frames': [], 'warnings': [], 'actual_subscribers': [],
              'message_counts': {'pointcloud': 0, 'metadata': 0, 'physics': 0},
              'tf': {'requested': 0, 'matched_source': 0, 'failed': 0},
              'consumer_evidence_scope': 'DDS endpoint discovery only; not a per-message consumer ACK',
              'truth_to_control': False, 'coordinate_frame': 'sensor_xyz_m',
              'projection': {'horizontal': 'atan2(y,x)', 'vertical': 'atan2(z,hypot(x,y))',
                             'same_view_for_truth_and_observation': True}}
    states, metas, clouds = OrderedDict(), OrderedDict(), OrderedDict()
    def retain(cache, key, value):
        cache[key] = value
        while len(cache) > 512: cache.popitem(last=False)
    def on_state(message):
        report['message_counts']['physics'] += 1
        try:
            value = json.loads(message.data)
            retain(states, (value['episode_id'], int(value['sequence'])), value)
        except (ValueError, KeyError, TypeError) as error:
            note = 'physics sample skipped: '+str(error)
            if note not in report['warnings']: report['warnings'].append(note)
    def on_meta(message):
        report['message_counts']['metadata'] += 1
        value = metadata_values(message)
        if value: retain(metas, stamp_ns(message), value)
    def on_cloud(message):
        report['message_counts']['pointcloud'] += 1
        retain(clouds, stamp_ns(message), message)
    rclpy.init(); node = Node('cooperation_sensor_experience_capture',
        parameter_overrides=[Parameter('use_sim_time', value=True)])
    buffer = Buffer(node=node)
    listener = TransformListener(buffer, node, spin_thread=False)
    subscriptions = [node.create_subscription(PointCloud2, config.get('topic', POINTS_TOPIC), on_cloud, qos_profile_sensor_data),
        node.create_subscription(DiagnosticArray, config.get('metadata_topic', METADATA_TOPIC), on_meta, qos_profile_sensor_data),
        node.create_subscription(String, '/cooperation/physics_state', on_state, qos_profile_sensor_data)]
    started = time.monotonic(); last = None
    try:
        while time.monotonic()-started < timeout and len(report['frames']) < frames:
            rclpy.spin_once(node, timeout_sec=.05)
            for stamp, metadata in list(metas.items()):
                if stamp not in clouds: continue
                try: state = states.get((metadata['episode_id'], int(metadata['sequence'])))
                except (KeyError, TypeError, ValueError): continue
                if state is None or not matching_state(metadata, state, stamp): continue
                if last and last[0] == state['episode_id'] and float(state['stamp'])-last[1] < separation_source_s: continue
                cloud = clouds.pop(stamp); metas.pop(stamp, None)
                try:
                    points = point_cloud2.read_points_numpy(cloud, field_names=('x', 'y', 'z'), skip_nans=True).reshape(-1, 3)
                    reference = truth.project(state)
                except (RuntimeError, ValueError, KeyError) as error:
                    report['warnings'].append('matched frame export failed: '+str(error));continue
                points = points[np.isfinite(points).all(axis=1)]
                if not len(points):
                    if 'A matched frame has no finite returns' not in report['warnings']:
                        report['warnings'].append('A matched frame has no finite returns')
                    continue
                actual_tf = None
                report['tf']['requested'] += 1
                try:
                    transform = buffer.lookup_transform('map', cloud.header.frame_id,
                        Time.from_msg(cloud.header.stamp)).transform
                    actual_tf = {'source_frame': cloud.header.frame_id, 'target_frame': 'map',
                        'source_stamp_ns': stamp,
                        'translation_m': [transform.translation.x, transform.translation.y, transform.translation.z],
                        'quaternion_xyzw': [transform.rotation.x, transform.rotation.y, transform.rotation.z, transform.rotation.w],
                        'source': 'actual_tf2_lookup_at_received_cloud_stamp'}
                    report['tf']['matched_source'] += 1
                except TransformException as error:
                    report['tf']['failed'] += 1
                    note = 'Same-source map TF unavailable: '+str(error)
                    if note not in report['warnings']: report['warnings'].append(note)
                index = len(report['frames']); filename = f'frame-{index}.json'
                record = {'identity': {name: metadata[name] for name in ('scene_sha256','manifest_sha256','episode_id','sequence')},
                    'source_s': state['stamp'], 'source_stamp_ns': stamp, 'frame_id': cloud.header.frame_id,
                    'receive_wall_s': time.time(), 'metadata': metadata, 'actual_tf': actual_tf,
                    'observed': {'topic': config.get('topic', POINTS_TOPIC), 'source': 'actual_received_PointCloud2',
                        'points': points.tolist(), 'width': cloud.width, 'height': cloud.height,
                        'valid_points': len(points)}, 'truth': reference,
                    'no_nearest_pose_substitution': True, 'truth_to_control': False}
                (output/filename).write_text(json.dumps(record, allow_nan=False, separators=(',', ':'))+'\n')
                report['frames'].append({'url': filename, 'identity': record['identity'],
                    'source_s': state['stamp'], 'valid_points': len(points)})
                last = (state['episode_id'], float(state['stamp']))
                if len(report['frames']) >= frames: break
        report['actual_subscribers'] = [{'node': info.node_namespace.rstrip('/')+'/'+info.node_name,
            'type': info.topic_type} for info in node.get_subscriptions_info_by_topic(config.get('topic', POINTS_TOPIC))
            if info.node_name != node.get_name()]
        report['elapsed_wall_s'] = time.monotonic()-started
        if len(report['frames']) >= frames: report['status'] = 'complete'
        else: report['warnings'].append('Not enough exact metadata/physics/cloud matches before timeout; no nearest-frame fallback')
    finally:
        del listener
        for subscription in subscriptions: node.destroy_subscription(subscription)
        node.destroy_node(); rclpy.shutdown()
    (output/'sensor-experience.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=30.)
    parser.add_argument('--frames', type=int, default=3)
    parser.add_argument('--separation-source-s', type=float, default=.5)
    args = parser.parse_args()
    try:
        report = observe(args.manifest, args.output, timeout=args.timeout,
            frames=args.frames, separation_source_s=args.separation_source_s)
    except Exception as error:
        report = {'schema': 'fishbot.sensor-experience.v1', 'status': 'incomplete',
            'read_only': True, 'warnings': [type(error).__name__+': '+str(error)]}
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output/'sensor-experience.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'sensor'}, ensure_ascii=False))


if __name__ == '__main__': main()
