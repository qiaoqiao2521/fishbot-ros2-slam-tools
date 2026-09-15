from __future__ import annotations

import importlib
import base64
import json
import math
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from backend.config import Settings
from backend.schemas import MapSnapshotEvent, RobotPose, RobotRuntimeState, ScanFrameEvent, now_ms


def _read_path(obj: Any, path: str, default: Any = None) -> Any:
    current = obj
    for part in path.split("."):
        if current is None:
            return default
        current = getattr(current, part, default)
    return current


def _clamp_battery(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, round(numeric, 2)))


def _normalize_text(value: Any, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _pick_field(payload: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in payload:
            return payload[name]
    return None


def _parse_text_payload(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return {}

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, dict):
        return parsed

    result: dict[str, Any] = {}
    for item in stripped.split(","):
        if "=" not in item:
            continue
        key, raw_value = item.split("=", maxsplit=1)
        result[key.strip()] = raw_value.strip()
    return result


def _message_to_mapping(message: Any) -> dict[str, Any]:
    if isinstance(message, Mapping):
        return dict(message)

    if hasattr(message, "data"):
        data = getattr(message, "data")
        if isinstance(data, (bytes, bytearray)):
            return _parse_text_payload(data.decode("utf-8", errors="ignore"))
        if isinstance(data, str):
            return _parse_text_payload(data)

    mapping: dict[str, Any] = {}
    for key in (
        "mode",
        "robot_mode",
        "battery_pct",
        "battery_percent",
        "battery",
        "nav_status",
        "nav_state",
        "navigation_status",
        "state",
        "read_only",
        "readonly",
    ):
        if hasattr(message, key):
            mapping[key] = getattr(message, key)
    return mapping


def adapt_status_payload(message: Any) -> RobotRuntimeState:
    payload = _message_to_mapping(message)

    return RobotRuntimeState(
        mode=_normalize_text(_pick_field(payload, "mode", "robot_mode"), "unknown"),
        battery_pct=_clamp_battery(
            _pick_field(payload, "battery_pct", "battery_percent", "battery")
        ),
        nav_status=_normalize_text(
            _pick_field(payload, "nav_status", "nav_state", "navigation_status", "state"),
            "unknown",
        ),
        read_only=_pick_field(payload, "read_only", "readonly"),
    )


def quaternion_to_yaw(x: float, y: float, z: float, w: float) -> float:
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def _map_cell_to_gray(value: Any) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return 205
    if numeric < 0:
        return 205
    if numeric >= 65:
        return 0
    return 255


def _encode_rle8(values: list[int]) -> str:
    if not values:
        return ""

    encoded = bytearray()
    current = values[0]
    run = 1

    for value in values[1:]:
        if value == current and run < 255:
            run += 1
            continue
        encoded.extend((run, current))
        current = value
        run = 1

    encoded.extend((run, current))
    return base64.b64encode(bytes(encoded)).decode("ascii")


def occupancy_grid_to_map_snapshot(message: Any) -> MapSnapshotEvent:
    width = int(_read_path(message, "info.width", 0) or 0)
    height = int(_read_path(message, "info.height", 0) or 0)
    if width <= 0 or height <= 0:
        raise ValueError("OccupancyGrid width/height must be positive")

    raw_data = list(getattr(message, "data", []) or [])
    if len(raw_data) < width * height:
        raise ValueError("OccupancyGrid data is shorter than width*height")

    grayscale_rows: list[int] = []
    for row_index in range(height - 1, -1, -1):
        row_start = row_index * width
        row = raw_data[row_start : row_start + width]
        grayscale_rows.extend(_map_cell_to_gray(value) for value in row)

    orientation = _read_path(
        message,
        "info.origin.orientation",
        SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
    )

    return MapSnapshotEvent(
        ts=now_ms(),
        frame=str(_read_path(message, "header.frame_id", "map") or "map"),
        width=width,
        height=height,
        resolution=round(float(_read_path(message, "info.resolution", 0.05) or 0.05), 6),
        origin={
            "x": round(float(_read_path(message, "info.origin.position.x", 0.0) or 0.0), 4),
            "y": round(float(_read_path(message, "info.origin.position.y", 0.0) or 0.0), 4),
            "yaw": round(
                quaternion_to_yaw(
                    float(getattr(orientation, "x", 0.0)),
                    float(getattr(orientation, "y", 0.0)),
                    float(getattr(orientation, "z", 0.0)),
                    float(getattr(orientation, "w", 1.0)),
                ),
                6,
            ),
        },
        encoding="rle8",
        data=_encode_rle8(grayscale_rows),
    )


def laser_scan_to_scan_frame(
    message: Any,
    *,
    pose: RobotPose | None,
    max_points: int,
) -> ScanFrameEvent:
    ranges = list(getattr(message, "ranges", []) or [])
    if not ranges:
        return ScanFrameEvent(
            ts=now_ms(),
            frame=pose.frame if pose is not None else str(_read_path(message, "header.frame_id", "scan") or "scan"),
            points=[],
        )

    stride = max(1, math.ceil(len(ranges) / max(1, max_points)))
    angle_min = float(getattr(message, "angle_min", 0.0) or 0.0)
    angle_increment = float(getattr(message, "angle_increment", 0.0) or 0.0)
    range_min = float(getattr(message, "range_min", 0.0) or 0.0)
    range_max = float(getattr(message, "range_max", float("inf")) or float("inf"))
    cos_yaw = math.cos(pose.yaw) if pose is not None else 1.0
    sin_yaw = math.sin(pose.yaw) if pose is not None else 0.0

    points: list[dict[str, float]] = []
    for index in range(0, len(ranges), stride):
        distance = float(ranges[index])
        if not math.isfinite(distance) or distance < range_min or distance > range_max:
            continue

        angle = angle_min + index * angle_increment
        local_x = distance * math.cos(angle)
        local_y = distance * math.sin(angle)

        if pose is not None:
            world_x = pose.x + local_x * cos_yaw - local_y * sin_yaw
            world_y = pose.y + local_x * sin_yaw + local_y * cos_yaw
        else:
            world_x = local_x
            world_y = local_y

        points.append({"x": round(world_x, 4), "y": round(world_y, 4)})

    return ScanFrameEvent(
        ts=now_ms(),
        frame=pose.frame if pose is not None else str(_read_path(message, "header.frame_id", "scan") or "scan"),
        points=points,
    )


@dataclass(slots=True)
class OdomState:
    pose: RobotPose
    linear_speed: float | None
    angular_speed: float | None


def extract_odom_state(message: Any, *, topic: str = "/odom") -> OdomState:
    position = _read_path(message, "pose.pose.position", SimpleNamespace(x=0.0, y=0.0))
    orientation = _read_path(
        message,
        "pose.pose.orientation",
        SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
    )
    frame = _read_path(message, "header.frame_id", "odom") or "odom"
    linear_speed = _read_path(message, "twist.twist.linear.x", None)
    angular_speed = _read_path(message, "twist.twist.angular.z", None)

    return OdomState(
        pose=RobotPose(
            x=round(float(getattr(position, "x", 0.0)), 4),
            y=round(float(getattr(position, "y", 0.0)), 4),
            yaw=quaternion_to_yaw(
                float(getattr(orientation, "x", 0.0)),
                float(getattr(orientation, "y", 0.0)),
                float(getattr(orientation, "z", 0.0)),
                float(getattr(orientation, "w", 1.0)),
            ),
            frame=str(frame),
            source=topic,
        ),
        linear_speed=None if linear_speed is None else round(float(linear_speed), 4),
        angular_speed=None if angular_speed is None else round(float(angular_speed), 4),
    )


class RosTopicBridge:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._node: Any = None
        self._executor: Any = None
        self._rclpy: Any = None
        self._startup_error: str | None = None
        self._status = RobotRuntimeState()
        self._pose: RobotPose | None = None
        self._last_pose_ms: int | None = None
        self._last_status_ms: int | None = None
        self._pose_revision = 0
        self._map_snapshot: MapSnapshotEvent | None = None
        self._last_map_ms: int | None = None
        self._map_revision = 0
        self._scan_frame: ScanFrameEvent | None = None
        self._last_scan_ms: int | None = None
        self._scan_revision = 0

    def start(self) -> None:
        if not self.settings.ros_enabled:
            return
        if self._thread is not None and self._thread.is_alive():
            return

        try:
            self._setup_ros()
        except Exception as exc:  # pragma: no cover - exercised on real ROS env
            self._startup_error = str(exc)
            self._teardown_ros()
            return

        self._stop.clear()
        self._thread = threading.Thread(target=self._spin_forever, name="ros-topic-bridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._teardown_ros()

    def snapshot_state(self) -> RobotRuntimeState:
        current_ms = now_ms()
        with self._lock:
            status = self._status.model_copy(deep=True)
            pose = self._pose.model_copy(deep=True) if self._pose is not None else None
            last_pose_ms = self._last_pose_ms
            last_status_ms = self._last_status_ms

        fresh_pose = last_pose_ms is not None and current_ms - last_pose_ms <= self.settings.ros_topic_stale_after_ms
        fresh_status = (
            last_status_ms is not None and current_ms - last_status_ms <= self.settings.ros_topic_stale_after_ms
        )

        status.ok = fresh_pose or fresh_status
        status.pose = pose if fresh_pose else None
        if not fresh_pose:
            status.linear_speed = None
            status.angular_speed = None
        return status

    def snapshot_pose(self) -> tuple[int, RobotPose | None]:
        current_ms = now_ms()
        with self._lock:
            revision = self._pose_revision
            pose = self._pose.model_copy(deep=True) if self._pose is not None else None
            last_pose_ms = self._last_pose_ms

        if pose is None or last_pose_ms is None:
            return revision, None
        if current_ms - last_pose_ms > self.settings.ros_topic_stale_after_ms:
            return revision, None
        return revision, pose

    def snapshot_map(self) -> tuple[int, MapSnapshotEvent | None]:
        current_ms = now_ms()
        with self._lock:
            revision = self._map_revision
            snapshot = self._map_snapshot.model_copy(deep=True) if self._map_snapshot is not None else None
            last_map_ms = self._last_map_ms

        if snapshot is None or last_map_ms is None:
            return revision, None
        if current_ms - last_map_ms > self.settings.ros_map_stale_after_ms:
            return revision, None
        return revision, snapshot

    def snapshot_scan(self) -> tuple[int, ScanFrameEvent | None]:
        current_ms = now_ms()
        with self._lock:
            revision = self._scan_revision
            frame = self._scan_frame.model_copy(deep=True) if self._scan_frame is not None else None
            last_scan_ms = self._last_scan_ms

        if frame is None or last_scan_ms is None:
            return revision, None
        if current_ms - last_scan_ms > self.settings.ros_scan_stale_after_ms:
            return revision, None
        return revision, frame

    def _setup_ros(self) -> None:
        rclpy = importlib.import_module("rclpy")
        executors = importlib.import_module("rclpy.executors")
        odom_module = importlib.import_module("nav_msgs.msg")
        sensor_module = importlib.import_module("sensor_msgs.msg")
        status_type = _resolve_message_type(self.settings.ros_status_message_type)

        if not rclpy.ok():
            rclpy.init(args=None)

        node = rclpy.create_node(self.settings.ros_node_name)
        executor = executors.SingleThreadedExecutor()
        executor.add_node(node)
        node.create_subscription(odom_module.Odometry, self.settings.ros_odom_topic, self._handle_odom, 10)
        node.create_subscription(odom_module.OccupancyGrid, self.settings.ros_map_topic, self._handle_map, 1)
        node.create_subscription(sensor_module.LaserScan, self.settings.ros_scan_topic, self._handle_scan, 10)
        node.create_subscription(status_type, self.settings.ros_status_topic, self._handle_status, 10)

        self._rclpy = rclpy
        self._node = node
        self._executor = executor
        self._startup_error = None

    def _teardown_ros(self) -> None:
        if self._executor is not None:
            try:
                self._executor.shutdown()
            except Exception:
                pass
            self._executor = None

        if self._node is not None:
            try:
                self._node.destroy_node()
            except Exception:
                pass
            self._node = None

        if self._rclpy is not None:
            try:
                if self._rclpy.ok():
                    self._rclpy.shutdown()
            except Exception:
                pass
            self._rclpy = None

    def _spin_forever(self) -> None:  # pragma: no cover - exercised on real ROS env
        while not self._stop.is_set() and self._executor is not None:
            self._executor.spin_once(timeout_sec=self.settings.ros_spin_timeout_s)

    def _handle_odom(self, message: Any) -> None:
        odom_state = extract_odom_state(message, topic=self.settings.ros_odom_topic)
        current_ms = now_ms()
        with self._lock:
            self._pose = odom_state.pose
            self._last_pose_ms = current_ms
            self._pose_revision += 1
            self._status.linear_speed = odom_state.linear_speed
            self._status.angular_speed = odom_state.angular_speed

    def _handle_status(self, message: Any) -> None:
        adapted = adapt_status_payload(message)
        current_ms = now_ms()
        with self._lock:
            if adapted.mode:
                self._status.mode = adapted.mode
            self._status.battery_pct = adapted.battery_pct
            if adapted.nav_status:
                self._status.nav_status = adapted.nav_status
            self._status.read_only = adapted.read_only
            self._last_status_ms = current_ms

    def _handle_map(self, message: Any) -> None:
        snapshot = occupancy_grid_to_map_snapshot(message)
        current_ms = now_ms()
        with self._lock:
            self._map_snapshot = snapshot
            self._last_map_ms = current_ms
            self._map_revision += 1

    def _handle_scan(self, message: Any) -> None:
        with self._lock:
            pose = self._pose.model_copy(deep=True) if self._pose is not None else None
        frame = laser_scan_to_scan_frame(
            message,
            pose=pose,
            max_points=self.settings.ros_scan_max_points,
        )
        current_ms = now_ms()
        with self._lock:
            self._scan_frame = frame
            self._last_scan_ms = current_ms
            self._scan_revision += 1


def _resolve_message_type(type_name: str) -> Any:
    normalized = type_name.strip()
    if not normalized:
        raise ValueError("ROS status message type is empty")

    if "/" in normalized:
        package, _, message_name = normalized.rpartition("/")
        module = importlib.import_module(package.replace("/", "."))
        return getattr(module, message_name)

    raise ValueError(f"Unsupported ROS message type: {type_name}")
