#!/usr/bin/python3
"""Image-only AprilTag station pose for the existing native docking contract."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import time
import threading
import uuid

import cv2
import numpy as np
cv2.setNumThreads(1)

from cooperation_camera import CAMERA_FRAME, IMAGE_TOPIC, INFO_TOPIC, METADATA_TOPIC, FAULT_TOPIC, LatestCameraSnapshot, camera_sync_qos, CAMERA_SYNC_DEPTH
from cooperation_perception import normalize_config
from fishbot_inspection import decode_rgb

QUALITY_TOPIC = '/cooperation/vision_quality'
PREVIEW_FRAME_LIMIT = 32


class CameraReceiver:
    """Let the standard executor receive while image inference is occupied."""
    def __init__(self, executor):
        self.executor = executor
        self.error = None
        self.thread = threading.Thread(target=self.receive, name='station-camera-receiver', daemon=True)

    def receive(self):
        try:
            self.executor.spin()
        except Exception as error:
            self.error = error

    def start(self):
        self.thread.start()

    def check(self):
        if self.error is not None:
            raise RuntimeError(f'Camera reception failed: {type(self.error).__name__}: {self.error}') from self.error
        if not self.thread.is_alive():
            raise RuntimeError('Camera reception stopped before inference shutdown')

    def close(self):
        stopped = self.executor.shutdown(timeout_sec=2.)
        self.thread.join(timeout=2.)
        if stopped is False or self.thread.is_alive():
            raise RuntimeError('Camera reception did not stop within the shutdown bound')


def transform(rotation, translation):
    result = np.eye(4)
    result[:3, :3], result[:3, 3] = rotation, translation
    return result


def planar_pose(rvec, tvec, config):
    camera_tag = transform(cv2.Rodrigues(rvec)[0], np.asarray(tvec).reshape(3))
    base_camera = transform(config['base_camera_rotation'], config['base_camera_translation'])
    tag_dock = transform(config['tag_dock_rotation'], config['tag_dock_translation'])
    base_dock = base_camera @ camera_tag @ tag_dock
    return np.array([base_dock[0, 3], base_dock[1, 3],
                     math.atan2(base_dock[1, 0], base_dock[0, 0])])


def refine_planar_corners(points, image_points, initial, k, d, config):
    """Fit the calibrated flat-floor model to pixels, without a pose oracle.

    IPPE remains the image-derived seed. Full six-dimensional uncertainty is
    retained separately; this declared fixture constraint does not cap it.
    """
    import scipy
    from scipy.optimize import least_squares
    if scipy.__version__ != config['detector']['scipy_version']:
        raise ValueError('SciPy version does not match the frozen refinement')
    camera_base = np.linalg.inv(transform(config['base_camera_rotation'], config['base_camera_translation']))
    dock_tag = np.linalg.inv(transform(config['tag_dock_rotation'], config['tag_dock_translation']))

    def camera_tag(pose):
        x, y, yaw = pose
        c, s = math.cos(yaw), math.sin(yaw)
        return camera_base @ transform([[c, -s, 0.], [s, c, 0.], [0., 0., 1.]], [x, y, 0.]) @ dock_tag

    def residual(pose):
        matrix = camera_tag(pose)
        rvec = cv2.Rodrigues(matrix[:3, :3])[0]
        projected, _ = cv2.projectPoints(points, rvec, matrix[:3, 3], k, d)
        return (projected.reshape(4, 2)-image_points).reshape(-1)

    result = least_squares(residual, initial, max_nfev=40, ftol=1e-10, xtol=1e-10, gtol=1e-10)
    if not result.success or not np.isfinite(result.x).all():
        raise ValueError('planar image refinement did not converge')
    matrix = camera_tag(result.x)
    depths = (points @ matrix[:3, :3].T+matrix[:3, 3])[:, 2]
    if not np.all(depths > 0.) or matrix[2, 2] >= 0.:
        raise ValueError('planar image refinement is behind the camera')
    result.x[2] = math.atan2(math.sin(result.x[2]), math.cos(result.x[2]))
    return result.x, float(np.sqrt(np.mean(residual(result.x).reshape(4, 2)**2)*2.))


def pose_covariance(points, rvec, tvec, k, d, config):
    """Propagate pixel uncertainty through PnP and the rigid mount transforms."""
    _, jacobian = cv2.projectPoints(points, rvec, tvec, k, d)
    jacobian = jacobian[:, :6]
    information = jacobian.T @ jacobian
    if np.linalg.matrix_rank(information) < 6:
        raise ValueError('singular tag pose information')
    pose_cov = np.linalg.inv(information)*config['detector']['pixel_sigma_px']**2
    vector = np.r_[np.asarray(rvec).reshape(3), np.asarray(tvec).reshape(3)]
    derivative = np.zeros((3, 6))
    for axis in range(6):
        plus, minus = vector.copy(), vector.copy()
        plus[axis] += 1e-5
        minus[axis] -= 1e-5
        difference = planar_pose(plus[:3], plus[3:], config)-planar_pose(minus[:3], minus[3:], config)
        difference[2] = math.atan2(math.sin(difference[2]), math.cos(difference[2]))
        derivative[:, axis] = difference/(2e-5)
    planar = derivative @ pose_cov @ derivative.T + np.diag(config['detector']['covariance_floor'])
    result = np.zeros((6, 6))
    result[np.ix_([0, 1, 5], [0, 1, 5])] = (planar+planar.T)/2.
    return result.reshape(36).tolist(), pose_cov.reshape(36).tolist()


def estimate_station(rgb, config, k=None, d=None):
    """Estimate from pixels and fixed calibration; no simulator state argument."""
    evidence = {'detected': False, 'reason': 'not_detected', 'confidence': 0.,
                'corners': None, 'candidates': [], 'reprojection_error_px': None,
                'relative': None, 'covariance': None,
                'confidence_semantics': 'deterministic_image_quality_score_v1'}
    if rgb.dtype != np.uint8 or rgb.shape != (config['height'], config['width'], 3):
        raise ValueError('RGB dimensions or dtype do not match calibration')
    if cv2.__version__ != config['detector']['opencv_version']:
        raise ValueError('OpenCV version does not match the frozen detector')
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    parameters = cv2.aruco.DetectorParameters_create()
    parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_APRILTAG
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    corners, ids, _ = cv2.aruco.detectMarkers(gray, dictionary,
                                            parameters=parameters)
    if ids is None:
        return evidence
    matching = [index for index, identity in enumerate(ids.reshape(-1)) if identity == config['tag_id']]
    if len(matching) != 1:
        evidence['reason'] = 'wrong_or_duplicate_tag_id'
        return evidence
    refined = corners[matching[0]].reshape(4, 2).astype(np.float32)
    window = config['detector'].get('subpixel_window', 5)
    cv2.cornerSubPix(gray, refined, (window, window), (-1, -1),
                    (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
                     config['detector'].get('subpixel_iterations', 30),
                     config['detector'].get('subpixel_epsilon', .01)))
    image_points = refined.astype(np.float64)
    evidence['corners'] = image_points.tolist()
    minimum_edge = min(float(np.linalg.norm(image_points[i]-image_points[(i+1)%4])) for i in range(4))
    evidence['minimum_edge_px'] = minimum_edge
    if minimum_edge < config['detector']['minimum_edge_px']:
        evidence['reason'] = 'insufficient_resolution'
        return evidence
    if (np.any(image_points < 3.) or
            np.any(image_points[:, 0] > config['width']-4) or
            np.any(image_points[:, 1] > config['height']-4)):
        evidence['reason'] = 'clipped_tag'
        return evidence
    half = config['tag_size_m']/2.
    points = np.array([[-half, half, 0.], [half, half, 0.], [half, -half, 0.], [-half, -half, 0.]])
    k = np.asarray(config['k'] if k is None else k, dtype=float).reshape(3, 3)
    d = np.asarray(config['d'] if d is None else d, dtype=float)
    solved = cv2.solvePnPGeneric(points, image_points, k, d, flags=cv2.SOLVEPNP_IPPE_SQUARE)
    candidates = []
    for rvec, tvec in zip(solved[1], solved[2]):
        rvec, tvec = cv2.solvePnPRefineLM(points, image_points, k, d, rvec.copy(), tvec.copy())
        rotation = cv2.Rodrigues(rvec)[0]
        camera_points = points @ rotation.T + tvec.reshape(3)
        if not np.all(camera_points[:, 2] > 0.) or rotation[2, 2] >= 0.:
            continue
        projected, _ = cv2.projectPoints(points, rvec, tvec, k, d)
        raw_error = float(np.sqrt(np.mean(np.sum((projected.reshape(4, 2)-image_points)**2, axis=1))))
        relative = planar_pose(rvec, tvec, config)
        if np.isfinite(np.r_[relative, raw_error]).all():
            raw_relative = relative.copy()
            if config.get('pose_model') == 'upright_tag_and_flat_floor_planar_base':
                try:
                    relative, error = refine_planar_corners(points, image_points, relative, k, d, config)
                except ValueError:
                    continue
            else:
                error = raw_error
            candidates.append((error, relative, rvec, tvec, raw_error, raw_relative))
    candidates.sort(key=lambda item: item[0])
    evidence['candidates'] = [{'reprojection_error_px': candidate[0], 'relative': candidate[1].tolist(),
                               'unconstrained_reprojection_error_px': candidate[4],
                               'unconstrained_relative': candidate[5].tolist()}
                              for candidate in candidates]
    if not candidates or candidates[0][0] > config['detector']['max_reprojection_px']:
        evidence['reason'] = 'invalid_pose_or_reprojection'
        return evidence
    error, relative, rvec, tvec, _, _ = candidates[0]
    if len(candidates) > 1 and candidates[1][0]-error <= config['detector']['ambiguous_error_delta_px']:
        difference = candidates[1][1]-relative
        yaw_difference = abs(math.atan2(math.sin(difference[2]), math.cos(difference[2])))
        if np.linalg.norm(difference[:2]) > config['detector']['ambiguity_xy_m'] or yaw_difference > config['detector']['ambiguity_yaw_rad']:
            evidence['reason'] = 'ambiguous_planar_pose'
            return evidence
    try:
        covariance, unconstrained_covariance = pose_covariance(points, rvec, tvec, k, d, config)
    except (ValueError, np.linalg.LinAlgError) as error_detail:
        evidence['reason'] = str(error_detail)
        return evidence
    quality = min(1., minimum_edge/40.)*math.exp(-error/config['detector']['max_reprojection_px'])
    evidence.update(detected=True, reason='tag_detected', confidence=quality,
                    relative=relative.tolist(), covariance=covariance, reprojection_error_px=error,
                    pose_model=config.get('pose_model', 'unconstrained_ippe'),
                    covariance_model='full_6d_pixel_jacobian_with_calibration_floor',
                    unconstrained_pose_covariance6x6=unconstrained_covariance)
    return evidence


def frame_identity(image, info, metadata, config, identity):
    headers = [(item.header.stamp.sec, item.header.stamp.nanosec, item.header.frame_id)
               for item in (image, info, metadata)]
    if len(set(headers)) != 1 or headers[0][2] != CAMERA_FRAME:
        raise ValueError('camera input must share its exact capture stamp and optical frame')
    if (len(metadata.status) != 1 or metadata.status[0].name != 'cooperation_camera_frame' or
            metadata.status[0].hardware_id != config['name']):
        raise ValueError('camera frame metadata is malformed')
    values = metadata.status[0].values
    fields = {item.key: item.value for item in values}
    if len(fields) != len(values) or set(fields) != {'scene_sha256', 'manifest_sha256', 'episode_id',
                                                  'sequence', 'capture_steady_ns', 'render_duration_s', 'fault_started'}:
        raise ValueError('camera identity fields are malformed')
    for key in ('scene_sha256', 'manifest_sha256'):
        if fields[key] != identity[key]:
            raise ValueError('camera identity differs from the declared scene')
    if str(uuid.UUID(fields['episode_id'])) != fields['episode_id']:
        raise ValueError('camera episode is malformed')
    fields['sequence'], fields['capture_steady_ns'] = int(fields['sequence']), int(fields['capture_steady_ns'])
    fields['render_duration_s'] = float(fields['render_duration_s'])
    if fields['fault_started'] not in ('true', 'false'):
        raise ValueError('camera fault activation must be boolean')
    fields['fault_started'] = fields['fault_started'] == 'true'
    if fields['sequence'] < 0 or fields['capture_steady_ns'] <= 0 or not math.isfinite(fields['render_duration_s']):
        raise ValueError('camera sequence or timing is malformed')
    if (info.width, info.height) != (config['width'], config['height']) or not np.allclose(info.k, config['k'], atol=1e-9, rtol=0):
        raise ValueError('CameraInfo differs from frozen intrinsics')
    if list(info.d) != config['d']:
        raise ValueError('CameraInfo distortion differs from frozen calibration')
    return dict(fields, stamp=headers[0][0]+headers[0][1]*1e-9)


def station_message_pair(observation):
    # Reuse the P0 codec; importing this module does not construct physics.
    from cooperation_sim import station_messages
    return station_messages(observation)


def commit_vision_preview(frame_dir, preview, metadata, preview_paths):
    """Commit the captured frame pair before publishing its latest pointer."""
    from PIL import Image as PillowImage

    frame_dir = Path(frame_dir)
    basename = f"vision-{metadata['episode_id']}-{metadata['sequence']}"
    if metadata.get('image_file') != basename+'.jpg':
        raise ValueError('vision preview metadata must identify its immutable image')
    image_path = frame_dir/(basename+'.jpg')
    metadata_path = frame_dir/(basename+'.json')
    if metadata_path.exists():
        raise FileExistsError(f'vision preview metadata already exists: {metadata_path.name}')
    # An existing identity cannot be overwritten, including a partial pair.
    with image_path.open('xb') as stream:
        PillowImage.fromarray(preview).save(stream, format='JPEG', quality=85)
    payload = json.dumps(metadata, allow_nan=False)
    temporary = frame_dir/(basename+'.'+uuid.uuid4().hex+'.json.tmp')
    try:
        temporary.write_text(payload)
        # Creating the hard link atomically admits the completed JSON without
        # replacing an immutable identity. Both paths share this directory.
        os.link(temporary, metadata_path)
    finally:
        temporary.unlink(missing_ok=True)
    temporary = frame_dir/('vision-next-'+uuid.uuid4().hex+'.json')
    try:
        temporary.write_text(payload)
        temporary.replace(frame_dir/'vision-latest.json')
    finally:
        temporary.unlink(missing_ok=True)
    preview_paths.append(image_path)
    while len(preview_paths) > PREVIEW_FRAME_LIMIT:
        expired = preview_paths.pop(0)
        expired.unlink(missing_ok=True)
        expired.with_suffix('.json').unlink(missing_ok=True)


def run(args):
    import rclpy
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.executors import SingleThreadedExecutor
    from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
    from geometry_msgs.msg import PoseWithCovarianceStamped
    from sensor_msgs.msg import Image, CameraInfo
    from std_msgs.msg import String
    from message_filters import Subscriber, TimeSynchronizer
    from cooperation_sim import latest_sensor_qos, unique_arm_publisher
    from cooperation_faults import FaultInjector, normalize_fault_config

    payload = args.manifest.read_bytes()
    manifest = json.loads(payload)
    config = manifest['station_camera']
    perception = normalize_config(manifest['station_perception'])
    if perception['mode'] != 'vision' or perception['publisher'] != 'station_camera':
        raise ValueError('vision runtime requires the station_camera publisher contract')
    identity = {'manifest_sha256': hashlib.sha256(payload).hexdigest(),
                'scene_sha256': hashlib.sha256(Path(manifest['world_xml']).read_bytes()).hexdigest()}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'rgb').mkdir(exist_ok=True)
    args.frame_dir.mkdir(parents=True, exist_ok=True)
    slot = LatestCameraSnapshot()
    faults = FaultInjector(normalize_fault_config(manifest.get('observation_faults')), identity=identity)
    fault_lock = threading.Lock()
    rclpy.init(args=[])
    node = Node('station_camera', parameter_overrides=[Parameter('use_sim_time', value=True)])
    qos = latest_sensor_qos()
    pose_pub = node.create_publisher(PoseWithCovarianceStamped, '/cooperation/station_pose', qos)
    detection_pub = node.create_publisher(DiagnosticArray, '/cooperation/station_detection', qos)
    quality_pub = node.create_publisher(DiagnosticArray, QUALITY_TOPIC, qos)
    ingress_counts = {IMAGE_TOPIC: 0, INFO_TOPIC: 0, METADATA_TOPIC: 0}
    synchronized_frames = 0

    def ingress(message, topic):
        with fault_lock:
            ingress_counts[topic] += 1

    filters = [Subscriber(node, kind, topic, qos_profile=camera_sync_qos())
               for kind, topic in [(Image, IMAGE_TOPIC), (CameraInfo, INFO_TOPIC), (DiagnosticArray, METADATA_TOPIC)]]
    for source, topic in zip(filters, (IMAGE_TOPIC, INFO_TOPIC, METADATA_TOPIC)):
        source.registerCallback(ingress, topic)
    sync = TimeSynchronizer(filters, queue_size=CAMERA_SYNC_DEPTH)
    last = None
    discarded = 0

    def capture(image, info, metadata):
        nonlocal discarded, synchronized_frames
        synchronized_frames += 1
        try:
            for topic in (IMAGE_TOPIC, INFO_TOPIC, METADATA_TOPIC):
                unique_arm_publisher(node.get_publishers_info_by_topic(topic), 'cooperation_physics')
            sample = frame_identity(image, info, metadata, config, identity)
            sample.update(rgb=decode_rgb(image), k=list(info.k), d=list(info.d))
            with fault_lock:
                if not slot.offer(sample):
                    discarded += 1
                    return
                if faults.episode_id != sample['episode_id']:
                    faults.begin_episode(sample['episode_id'])
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            with fault_lock:
                discarded += 1
            node.get_logger().warning(f'Rejected camera frame: {error}')

    def trigger(message):
        try:
            unique_arm_publisher(node.get_publishers_info_by_topic(FAULT_TOPIC), 'fishbot_so101_cooperation')
            with fault_lock:
                faults.trigger(json.loads(message.data))
        except (ValueError, TypeError, KeyError) as error:
            node.get_logger().warning(f'Rejected observation fault: {error}')

    sync.registerCallback(capture)
    trigger_sub = node.create_subscription(String, FAULT_TOPIC, trigger, 10)
    report = (args.output/'vision.jsonl').open('a')
    preview_paths = []
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    receiver = CameraReceiver(executor)
    receiver.start()
    try:
        while rclpy.ok():
            receiver.check()
            sample = slot.take()
            if sample is None:
                time.sleep(.01)
                continue
            started = time.monotonic()
            metrics = estimate_station(sample['rgb'], config, sample['k'], sample['d'])
            metrics['inference_duration_s'] = time.monotonic()-started
            capture_age = (time.monotonic_ns()-sample['capture_steady_ns'])*1e-9
            source_age = node.get_clock().now().nanoseconds*1e-9-sample['stamp']
            if not 0 <= capture_age <= .5 or not -.1 <= source_age <= .25:
                metrics.update(detected=False, reason='camera_capture_stale', relative=None, covariance=None, confidence=0.)
            if (metrics['detected'] and (metrics['confidence'] < perception['min_confidence'] or
                    any(metrics['covariance'][i] > limit for i, limit in zip((0, 7, 35), perception['max_covariance'])))):
                metrics.update(detected=False, reason='image_quality_or_covariance_rejected', relative=None, covariance=None)
            observation = {key: sample[key] for key in ('scene_sha256', 'manifest_sha256', 'episode_id', 'sequence', 'stamp')}
            observation.update(schema=1, publisher='station_camera', mode='vision', station_id=perception['station_id'],
                               frame_id='base_footprint', idealized_truth_derived=False,
                               **{key: metrics[key] for key in ('detected', 'confidence', 'reason', 'relative', 'covariance')})
            # The detector does not consume velocity or robot state. Accepted
            # Dock triggers bind fault activation; physical camera occlusion is
            # applied separately by the renderer at its captured source time.
            with fault_lock:
                # Reception may have fenced a new episode during inference.
                if not slot.current(sample['episode_id']):
                    discarded += 1
                    continue
                for outgoing in faults.apply(observation, wall_time=time.monotonic(), source_stamp=sample['stamp'],
                                             episode_id=sample['episode_id'], moving=sample['fault_started'], synthetic_occlusion=False):
                    pose, diagnostic = station_message_pair(outgoing)
                    if pose is not None:
                        pose_pub.publish(pose)
                    detection_pub.publish(diagnostic)
                fault_status = faults.status()
                discarded_frames = discarded
                received_counts = dict(ingress_counts)
                paired_frames = synchronized_frames
            quality = DiagnosticArray()
            _, diagnostic = station_message_pair(observation)
            quality.header = copy.deepcopy(diagnostic.header)
            status = DiagnosticStatus()
            status.name, status.hardware_id = 'station_vision_quality', 'so101_station'
            status.level = DiagnosticStatus.OK if metrics['detected'] else DiagnosticStatus.WARN
            status.message = metrics['reason']
            quality_values = {**observation, **metrics, 'render_duration_s': sample['render_duration_s'],
                              'capture_age_s': capture_age, 'source_age_s': source_age,
                              'overwritten_frames': slot.overwritten, 'discarded_frames': discarded_frames,
                              'camera_ingress_counts': received_counts,
                              'camera_synchronized_frames': paired_frames}
            status.values = [KeyValue(key=key, value=json.dumps(value)) for key, value in quality_values.items()]
            quality.status = [status]
            quality_pub.publish(quality)
            # A PNG preserves the pixels used by detection. Preview commits use
            # immutable identity filenames and then atomically publish metadata.
            from PIL import Image as PillowImage
            basename = f"vision-{sample['episode_id']}-{sample['sequence']}"
            rgb_path = args.output/'rgb'/(basename+'.png')
            PillowImage.fromarray(sample['rgb']).save(rgb_path)
            preview = sample['rgb'].copy()
            if metrics['corners'] is not None:
                cv2.polylines(preview, [np.asarray(metrics['corners'], dtype=np.int32)], True, (30, 180, 90), 2)
            preview_name = basename+'.jpg'
            metadata = {key: sample[key] for key in ('stamp', 'scene_sha256', 'manifest_sha256', 'episode_id', 'sequence')}
            metadata.update(wall_time=time.time(), corners=metrics['corners'], image_width=config['width'],
                            image_height=config['height'], image_file=preview_name)
            commit_vision_preview(args.frame_dir, preview, metadata, preview_paths)
            report.write(json.dumps({**metadata, **quality_values, 'rgb_file': str(rgb_path),
                                     'faults': fault_status}, allow_nan=False)+'\n')
            report.flush()
            last = sample
    finally:
        report.close()
        try:
            receiver.close()
        finally:
            node.destroy_node()
            rclpy.try_shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--frame-dir', type=Path, required=True)
    parser.add_argument('--domain', type=int, required=True)
    args = parser.parse_args()
    if not 1 <= args.domain <= 232 or args.domain in (107, 114):
        parser.error('vision requires a new isolated domain, preserving 107/114')
    os.environ.update(ROS_DOMAIN_ID=str(args.domain), ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST', ROS_LOCALHOST_ONLY='1')
    run(args)


if __name__ == '__main__':
    main()
