#!/usr/bin/python3
"""Read actual 3-D lidar, Nav2 configuration and a low-obstacle costmap region.

Run in the already selected ROS domain. This observer has no action or velocity
client. Incomplete observations are returned as JSON so a campaign can continue.
"""
from __future__ import annotations

import argparse
from collections import deque
import json
import math
from pathlib import Path
import threading
import time


def cloud_stamp_ns(message) -> int:
    return int(message.header.stamp.sec) * 1_000_000_000 + int(message.header.stamp.nanosec)


class PendingClouds:
    """Bounded original-stamp frames waiting for the matching dynamic TF."""
    def __init__(self, max_frames: int = 32, source_window_sec: float = 3.0):
        self.max_frames = max_frames
        self.source_window_sec = source_window_sec
        self.entries = deque()
        self.dropped = {'capacity': 0, 'source_window': 0, 'superseded': 0, 'duplicate': 0}
        self.processed = 0
        self._last_processed_stamp = None

    def add(self, message, received_wall: float) -> None:
        stamp = cloud_stamp_ns(message)
        if (self._last_processed_stamp is not None and stamp <= self._last_processed_stamp
                or any(cloud_stamp_ns(entry['message']) == stamp for entry in self.entries)):
            self.dropped['duplicate'] += 1
            return
        self.entries.append({'message': message, 'received_wall': received_wall})
        cutoff = stamp - int(self.source_window_sec * 1_000_000_000)
        while self.entries and cloud_stamp_ns(self.entries[0]['message']) < cutoff:
            self.entries.popleft()
            self.dropped['source_window'] += 1
        while len(self.entries) > self.max_frames:
            self.entries.popleft()
            self.dropped['capacity'] += 1

    def consume_through(self, stamp: int) -> None:
        """Retire the processed frame and older frames; never change timestamps."""
        while self.entries and cloud_stamp_ns(self.entries[0]['message']) <= stamp:
            entry = self.entries.popleft()
            if cloud_stamp_ns(entry['message']) < stamp:
                self.dropped['superseded'] += 1
        self._last_processed_stamp = stamp
        self.processed += 1

    def summary(self) -> dict:
        return {'max_frames': self.max_frames, 'source_window_sec': self.source_window_sec,
                'pending_frames': len(self.entries), 'processed_frames': self.processed,
                'dropped': dict(self.dropped)}


def summarize_points(points, *, frame: str, width: int, height: int) -> dict:
    """Summarize decoded XYZ values; decoding remains sensor_msgs_py's job."""
    count = 0
    z_min, z_max = math.inf, -math.inf
    heights = set()
    for point in points:
        x, y, z = (float(point[i]) for i in range(3))
        if not all(math.isfinite(value) for value in (x, y, z)):
            continue
        count += 1
        z_min, z_max = min(z_min, z), max(z_max, z)
        heights.add(round(z / 0.02))
    return {
        'frame': frame, 'width': int(width), 'height': int(height),
        'valid_points': count, 'height_bins_2cm': len(heights),
        'z_min': z_min if count else None, 'z_max': z_max if count else None,
    }


def costmap_region(message, target: tuple[float, float], half_size: float) -> dict:
    """Read grid cells whose centres fall in the requested world-frame region."""
    info = message.info
    q = info.origin.orientation
    yaw = math.atan2(2 * (q.w * q.z + q.x * q.y),
                     1 - 2 * (q.y * q.y + q.z * q.z))
    cosine, sine = math.cos(yaw), math.sin(yaw)
    origin = info.origin.position
    cells = []
    if info.resolution <= 0:
        return {'frame': message.header.frame_id, 'cells': 0, 'lethal_cells': 0,
                'occupied_cells': 0, 'unknown_cells': 0, 'max_occupancy': None}
    corners = []
    for dx in (-half_size, half_size):
        for dy in (-half_size, half_size):
            x, y = target[0] + dx - origin.x, target[1] + dy - origin.y
            corners.append(((cosine * x + sine * y) / info.resolution,
                            (-sine * x + cosine * y) / info.resolution))
    x0 = max(0, math.floor(min(x for x, _ in corners)))
    x1 = min(info.width - 1, math.floor(max(x for x, _ in corners)))
    y0 = max(0, math.floor(min(y for _, y in corners)))
    y1 = min(info.height - 1, math.floor(max(y for _, y in corners)))
    for row in range(y0, y1 + 1):
        for column in range(x0, x1 + 1):
            local_x, local_y = (column + 0.5) * info.resolution, (row + 0.5) * info.resolution
            x = origin.x + cosine * local_x - sine * local_y
            y = origin.y + sine * local_x + cosine * local_y
            index = row * info.width + column
            if (abs(x - target[0]) <= half_size and abs(y - target[1]) <= half_size
                    and index < len(message.data)):
                cells.append(int(message.data[index]))
    known = [value for value in cells if value >= 0]
    return {
        'frame': message.header.frame_id, 'resolution': float(info.resolution),
        'cells': len(cells), 'lethal_cells': sum(value >= 100 for value in cells),
        'occupied_cells': sum(value >= 65 for value in cells),
        'unknown_cells': sum(value < 0 for value in cells),
        'max_occupancy': max(known) if known else None,
    }


def _transform_xyz(point, transform):
    q, t = transform.rotation, transform.translation
    x, y, z = (float(point[i]) for i in range(3))
    # Quaternion-vector rotation, followed by the actual TF translation.
    tx, ty, tz = 2 * (q.y * z - q.z * y), 2 * (q.z * x - q.x * z), 2 * (q.x * y - q.y * x)
    return (x + q.w * tx + q.y * tz - q.z * ty + t.x,
            y + q.w * ty + q.z * tx - q.x * tz + t.y,
            z + q.w * tz + q.x * ty - q.y * tx + t.z)


def record_transform_failure(state: dict, error: Exception, *, source: str,
                             target: str, seconds: int, nanoseconds: int) -> None:
    """Retain concrete TF failures without retaining an unbounded error log."""
    name = type(error).__name__
    state['failed_lookups'] += 1
    state['exception_types'][name] = state['exception_types'].get(name, 0) + 1
    detail = {
        'type': name, 'message': str(error), 'source_frame': source,
        'target_frame': target, 'requested_stamp_sec': seconds,
        'requested_stamp_nanosec': nanoseconds,
    }
    if state['first_exception'] is None:
        state['first_exception'] = detail
    state['last_exception'] = detail


def observe(*, timeout: float = 15.0, topic: str = '/sensors/lidar3d/points',
            costmap_topic: str = '/global_costmap/costmap',
            target: tuple[float, float] = (-0.25, 0.55),
            half_size: float = 0.12) -> dict:
    import rclpy
    from rclpy.node import Node
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.parameter import Parameter, parameter_value_to_python
    from rclpy.qos import qos_profile_sensor_data
    from rclpy.time import Time
    from rcl_interfaces.srv import GetParameters
    from sensor_msgs.msg import PointCloud2
    from sensor_msgs_py import point_cloud2
    from nav_msgs.msg import OccupancyGrid
    from tf2_ros import Buffer, TransformListener, TransformException

    result = {
        'status': 'incomplete', 'reasons': [], 'warnings': [],
        'topic': topic, 'costmap_topic': costmap_topic,
        'target': list(target), 'region_half_size': half_size,
        'pointcloud': None, 'subscription_endpoints': [],
        'global_parameters': {}, 'costmap': None, 'target_cloud': None,
        'evidence': {},
        'tf': {'lookup_attempts': 0, 'successful_lookups': 0, 'failed_lookups': 0,
               'exception_types': {}, 'first_exception': None, 'last_exception': None,
               'frames_yaml': None, 'observer_clock_nanoseconds': None},
    }
    rclpy.init(args=[])
    node = Node('fishbot_lidar3d_probe',
                parameter_overrides=[Parameter('use_sim_time', value=True)])
    buffer = Buffer(node=node)
    listener = TransformListener(buffer, node, spin_thread=False)
    pending = PendingClouds()
    callback_lock = threading.Lock()
    latest_cloud = None
    last_summary_stamp = None
    grid = None
    messages = 0
    parameter_future = None
    prefix = 'lidar3d_voxel_layer'
    parameter_names = [
        'plugins', f'{prefix}.plugin', f'{prefix}.enabled',
        f'{prefix}.observation_sources', f'{prefix}.lidar3d.topic',
        f'{prefix}.lidar3d.data_type', f'{prefix}.lidar3d.marking',
        f'{prefix}.lidar3d.clearing', f'{prefix}.lidar3d.min_obstacle_height',
        f'{prefix}.lidar3d.max_obstacle_height',
    ]

    def on_cloud(message):
        nonlocal messages, latest_cloud
        with callback_lock:
            pending.add(message, time.monotonic())
            latest_cloud = message
            messages += 1

    def on_grid(message):
        nonlocal grid
        with callback_lock:
            grid = message

    cloud_subscription = node.create_subscription(PointCloud2, topic, on_cloud, qos_profile_sensor_data)
    grid_subscription = node.create_subscription(OccupancyGrid, costmap_topic, on_grid, qos_profile_sensor_data)
    parameters = node.create_client(GetParameters, '/global_costmap/global_costmap/get_parameters')
    # Exactly one executor owns this node, its TimeSource and TF subscriptions.
    # Parsing and graph queries stay outside that thread so TF can catch up.
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, name='lidar3d_probe_callbacks', daemon=True)
    spin_thread.start()
    start = time.monotonic()
    try:
        while time.monotonic() - start < timeout:
            time.sleep(0.02)
            with callback_lock:
                current_cloud = latest_cloud
                current_grid = grid
                candidates = list(reversed(pending.entries))
                current_messages = messages
            if parameter_future is None and parameters.service_is_ready():
                parameter_future = parameters.call_async(GetParameters.Request(names=parameter_names))
            if parameter_future is not None and parameter_future.done() and not result['global_parameters']:
                try:
                    response = parameter_future.result()
                    result['global_parameters'] = {
                        name: parameter_value_to_python(value)
                        for name, value in zip(parameter_names, response.values)
                    }
                except Exception as error:
                    warning = f'Parameter read incomplete: {error}'
                    if warning not in result['warnings']:
                        result['warnings'].append(warning)
            result['subscription_endpoints'] = [
                {'node': f"{info.node_namespace.rstrip('/')}/{info.node_name}",
                 'type': info.topic_type,
                 'reliability': str(info.qos_profile.reliability)}
                for info in node.get_subscriptions_info_by_topic(topic)
                if info.node_name != node.get_name()
            ]
            if current_cloud is not None and cloud_stamp_ns(current_cloud) != last_summary_stamp:
                current = current_cloud
                points = list(point_cloud2.read_points(current, field_names=('x', 'y', 'z'), skip_nans=True))
                result['pointcloud'] = summarize_points(
                    points, frame=current.header.frame_id, width=current.width, height=current.height)
                result['pointcloud'].update(
                    messages=current_messages, source_stamp_sec=current.header.stamp.sec,
                    source_stamp_nanosec=current.header.stamp.nanosec)
                last_summary_stamp = cloud_stamp_ns(current)
            if current_grid is not None:
                result['costmap'] = costmap_region(current_grid, target, half_size)
                for entry in candidates:
                    current = entry['message']
                    result['tf']['lookup_attempts'] += 1
                    try:
                        transform = buffer.lookup_transform(
                            current_grid.header.frame_id, current.header.frame_id,
                            Time.from_msg(current.header.stamp)).transform
                    except TransformException as error:
                        record_transform_failure(
                            result['tf'], error, source=current.header.frame_id,
                            target=current_grid.header.frame_id, seconds=current.header.stamp.sec,
                            nanoseconds=current.header.stamp.nanosec)
                        continue
                    result['tf']['successful_lookups'] += 1
                    count = 0
                    heights = []
                    for point in point_cloud2.read_points(current, field_names=('x', 'y', 'z'), skip_nans=True):
                        x, y, z = _transform_xyz(point, transform)
                        if (all(math.isfinite(v) for v in (x, y, z))
                                and abs(x - target[0]) <= half_size
                                and abs(y - target[1]) <= half_size and 0.015 <= z <= 0.12):
                            count += 1
                            heights.append(z)
                    result['target_cloud'] = {
                        'frame': current_grid.header.frame_id, 'points': count,
                        'z_min': min(heights) if heights else None,
                        'z_max': max(heights) if heights else None,
                        'source_stamp_sec': current.header.stamp.sec,
                        'source_stamp_nanosec': current.header.stamp.nanosec,
                        'source_age_sec': (node.get_clock().now().nanoseconds - cloud_stamp_ns(current)) / 1e9,
                        'transform_wait_wall_sec': time.monotonic() - entry['received_wall'],
                    }
                    with callback_lock:
                        pending.consume_through(cloud_stamp_ns(current))
                    break
            params = result['global_parameters']
            evidence = {
                'actual_multiline_pointcloud': bool(result['pointcloud']
                    and result['pointcloud']['height'] > 1
                    and result['pointcloud']['valid_points'] > 0
                    and result['pointcloud']['height_bins_2cm'] > 1),
                'global_costmap_subscription_found': any(
                    endpoint['node'] == '/global_costmap/global_costmap'
                    and endpoint['type'] == 'sensor_msgs/msg/PointCloud2'
                    for endpoint in result['subscription_endpoints']),
                'global_3d_source_configured': (
                    params.get(f'{prefix}.lidar3d.topic') == topic
                    and params.get(f'{prefix}.lidar3d.data_type') == 'PointCloud2'
                    and params.get(f'{prefix}.enabled') is True
                    and params.get(f'{prefix}.lidar3d.marking') is True),
                'low_obstacle_has_3d_returns': bool(result['target_cloud'] and result['target_cloud']['points'] > 0),
                'low_obstacle_costmap_has_lethal_cells': bool(result['costmap'] and result['costmap']['lethal_cells'] > 0),
            }
            result['evidence'] = evidence
            if all(evidence.values()):
                result['status'] = 'complete'
                break
        result['elapsed_wall_sec'] = time.monotonic() - start
        result['tf']['frames_yaml'] = buffer.all_frames_as_yaml()
        result['tf']['observer_clock_nanoseconds'] = node.get_clock().now().nanoseconds
        with callback_lock:
            result['pending_clouds'] = pending.summary()
        if result['status'] != 'complete':
            result['reasons'] = [key for key, value in result['evidence'].items() if not value]
            if not result['reasons']:
                result['reasons'] = ['No complete ROS observation before the wall-clock timeout']
            if result['target_cloud'] is None and result['tf']['last_exception']:
                last = result['tf']['last_exception']
                result['warnings'].append(f"TF {last['type']}: {last['message']}")
        return result
    finally:
        executor.shutdown(timeout_sec=1.0)
        spin_thread.join(timeout=1.0)
        del listener, cloud_subscription, grid_subscription
        node.destroy_node()
        rclpy.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=float, default=15.0)
    parser.add_argument('--topic', default='/sensors/lidar3d/points')
    parser.add_argument('--costmap-topic', default='/global_costmap/costmap')
    parser.add_argument('--target-x', type=float, default=-0.25)
    parser.add_argument('--target-y', type=float, default=0.55)
    parser.add_argument('--half-size', type=float, default=0.12)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        result = observe(timeout=args.timeout, topic=args.topic,
                         costmap_topic=args.costmap_topic,
                         target=(args.target_x, args.target_y), half_size=args.half_size)
    except Exception as error:
        result = {'status': 'incomplete', 'reasons': [f'{type(error).__name__}: {error}']}
    text = json.dumps(result, indent=2, allow_nan=False) + '\n'
    if args.output:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text)
        except OSError as error:
            print(f'WARNING: Could not write optional probe report: {error}')
    print(text, end='')


if __name__ == '__main__':
    main()
