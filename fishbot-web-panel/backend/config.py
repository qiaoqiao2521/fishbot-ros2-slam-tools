from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel, Field


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None else int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value is None else float(value)


def _env_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if value is None:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseModel):
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8010
    serial_enabled: bool = True
    serial_stream: str = "serial0"
    serial_port: str = "/dev/ttyUSB0"
    serial_baud: int = 115200
    serial_read_timeout_s: float = 0.25
    serial_reconnect_interval_s: float = 1.0
    serial_mock_interval_ms: int = 100
    serial_window_seconds: int = 30
    serial_window_max_points: int = 600
    serial_batch_interval_ms: int = 250
    serial_stats_interval_ms: int = 1000
    serial_stale_after_ms: int = 3000
    system_state_interval_ms: int = 1000
    robot_pose_interval_ms: int = 250
    map_snapshot_interval_ms: int = 1200
    scan_frame_interval_ms: int = 200
    ros_enabled: bool = True
    ros_node_name: str = "ros2_mobile_panel_bridge"
    ros_odom_topic: str = "/odom"
    ros_map_topic: str = "/map"
    ros_scan_topic: str = "/scan"
    ros_status_topic: str = "/robot/status"
    ros_status_message_type: str = "std_msgs/msg/String"
    ros_topic_stale_after_ms: int = 3000
    ros_map_stale_after_ms: int = 30000
    ros_scan_stale_after_ms: int = 2000
    ros_scan_max_points: int = 360
    ros_spin_timeout_ms: int = 100
    ros_cmd_vel_topic: str = "/cmd_vel"
    control_node_name: str = "ros2_mobile_panel_command_gateway"
    control_default_ttl_ms: int = 300
    control_min_ttl_ms: int = 120
    control_max_ttl_ms: int = 1000
    control_watchdog_interval_ms: int = 50
    control_command_max_age_ms: int = 3000
    control_max_linear_mps: float = 0.2
    control_max_angular_rps: float = 0.8
    control_debug_override_enabled: bool = False
    control_debug_override_allow_hosts: list[str] = Field(
        default_factory=lambda: ["127.0.0.1", "::1", "localhost"],
    )
    control_debug_mock_cmd_vel_enabled: bool = False
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    @property
    def control_debug_override_active(self) -> bool:
        return self.control_debug_override_enabled and self.app_env.strip().lower() not in {
            "prod",
            "production",
        }

    @property
    def serial_batch_interval_s(self) -> float:
        return max(self.serial_batch_interval_ms, 20) / 1000.0

    @property
    def serial_stats_interval_s(self) -> float:
        return max(self.serial_stats_interval_ms, 100) / 1000.0

    @property
    def serial_mock_interval_s(self) -> float:
        return max(self.serial_mock_interval_ms, 20) / 1000.0

    @property
    def system_state_interval_s(self) -> float:
        return max(self.system_state_interval_ms, 200) / 1000.0

    @property
    def robot_pose_interval_s(self) -> float:
        return max(self.robot_pose_interval_ms, 100) / 1000.0

    @property
    def map_snapshot_interval_s(self) -> float:
        return max(self.map_snapshot_interval_ms, 500) / 1000.0

    @property
    def scan_frame_interval_s(self) -> float:
        return max(self.scan_frame_interval_ms, 80) / 1000.0

    @property
    def ros_spin_timeout_s(self) -> float:
        return max(self.ros_spin_timeout_ms, 20) / 1000.0

    @property
    def control_watchdog_interval_s(self) -> float:
        return max(self.control_watchdog_interval_ms, 20) / 1000.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    origins = os.getenv("CORS_ORIGINS", "*")
    cors_origins = ["*"] if origins.strip() == "*" else [item.strip() for item in origins.split(",") if item.strip()]

    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        app_host=os.getenv("APP_HOST", "0.0.0.0"),
        app_port=_env_int("APP_PORT", 8010),
        serial_enabled=_env_bool("SERIAL_ENABLED", True),
        serial_stream=os.getenv("SERIAL_STREAM", "serial0"),
        serial_port=os.getenv("SERIAL_PORT", "/dev/ttyUSB0"),
        serial_baud=_env_int("SERIAL_BAUD", 115200),
        serial_read_timeout_s=_env_float("SERIAL_READ_TIMEOUT_S", 0.25),
        serial_reconnect_interval_s=_env_float("SERIAL_RECONNECT_INTERVAL_S", 1.0),
        serial_mock_interval_ms=_env_int("SERIAL_MOCK_INTERVAL_MS", 100),
        serial_window_seconds=_env_int("SERIAL_WINDOW_SECONDS", 30),
        serial_window_max_points=_env_int("SERIAL_WINDOW_MAX_POINTS", 600),
        serial_batch_interval_ms=_env_int("SERIAL_BATCH_INTERVAL_MS", 250),
        serial_stats_interval_ms=_env_int("SERIAL_STATS_INTERVAL_MS", 1000),
        serial_stale_after_ms=_env_int("SERIAL_STALE_AFTER_MS", 3000),
        system_state_interval_ms=_env_int("SYSTEM_STATE_INTERVAL_MS", 1000),
        robot_pose_interval_ms=_env_int("ROBOT_POSE_INTERVAL_MS", 250),
        map_snapshot_interval_ms=_env_int("MAP_SNAPSHOT_INTERVAL_MS", 1200),
        scan_frame_interval_ms=_env_int("SCAN_FRAME_INTERVAL_MS", 200),
        ros_enabled=_env_bool("ROS_ENABLED", True),
        ros_node_name=os.getenv("ROS_NODE_NAME", "ros2_mobile_panel_bridge"),
        ros_odom_topic=os.getenv("ROS_ODOM_TOPIC", "/odom"),
        ros_map_topic=os.getenv("ROS_MAP_TOPIC", "/map"),
        ros_scan_topic=os.getenv("ROS_SCAN_TOPIC", "/scan"),
        ros_status_topic=os.getenv("ROS_STATUS_TOPIC", "/robot/status"),
        ros_status_message_type=os.getenv("ROS_STATUS_MESSAGE_TYPE", "std_msgs/msg/String"),
        ros_topic_stale_after_ms=_env_int("ROS_TOPIC_STALE_AFTER_MS", 3000),
        ros_map_stale_after_ms=_env_int("ROS_MAP_STALE_AFTER_MS", 30000),
        ros_scan_stale_after_ms=_env_int("ROS_SCAN_STALE_AFTER_MS", 2000),
        ros_scan_max_points=_env_int("ROS_SCAN_MAX_POINTS", 360),
        ros_spin_timeout_ms=_env_int("ROS_SPIN_TIMEOUT_MS", 100),
        ros_cmd_vel_topic=os.getenv("ROS_CMD_VEL_TOPIC", "/cmd_vel"),
        control_node_name=os.getenv("CONTROL_NODE_NAME", "ros2_mobile_panel_command_gateway"),
        control_default_ttl_ms=_env_int("CONTROL_DEFAULT_TTL_MS", 300),
        control_min_ttl_ms=_env_int("CONTROL_MIN_TTL_MS", 120),
        control_max_ttl_ms=_env_int("CONTROL_MAX_TTL_MS", 1000),
        control_watchdog_interval_ms=_env_int("CONTROL_WATCHDOG_INTERVAL_MS", 50),
        control_command_max_age_ms=_env_int("CONTROL_COMMAND_MAX_AGE_MS", 3000),
        control_max_linear_mps=_env_float("CONTROL_MAX_LINEAR_MPS", 0.2),
        control_max_angular_rps=_env_float("CONTROL_MAX_ANGULAR_RPS", 0.8),
        control_debug_override_enabled=_env_bool("CONTROL_DEBUG_OVERRIDE_ENABLED", False),
        control_debug_override_allow_hosts=_env_list(
            "CONTROL_DEBUG_OVERRIDE_ALLOW_HOSTS",
            ["127.0.0.1", "::1", "localhost"],
        ),
        control_debug_mock_cmd_vel_enabled=_env_bool("CONTROL_DEBUG_MOCK_CMD_VEL_ENABLED", False),
        cors_origins=cors_origins,
    )
