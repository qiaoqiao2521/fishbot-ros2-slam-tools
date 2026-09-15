#!/usr/bin/env python3
import json
import math
import sys
import time
import urllib.error
import urllib.request

import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from sensor_msgs.msg import Imu


def quaternion_from_rpy(roll: float, pitch: float, yaw: float) -> tuple[float, float, float, float]:
    cy = math.cos(yaw * 0.5)
    sy = math.sin(yaw * 0.5)
    cp = math.cos(pitch * 0.5)
    sp = math.sin(pitch * 0.5)
    cr = math.cos(roll * 0.5)
    sr = math.sin(roll * 0.5)
    return (
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    )


class ControlStateBridge(Node):
    def __init__(self, backend_base: str, publish_hz: float) -> None:
        super().__init__("fishbot_control_state_bridge")
        self.backend_base = backend_base.rstrip("/")
        self.state_url = f"{self.backend_base}/api/v1/state"
        self.connection_url = f"{self.backend_base}/api/v1/connection"
        # UI-derived diagnostics are not an authoritative SLAM/EKF sensor source.
        self.odom_pub = self.create_publisher(Odometry, "/station/odom", 10)
        self.imu_pub = self.create_publisher(Imu, "/station/imu", 10)
        self.last_state_received = 0.0
        self.latest_state: dict | None = None
        self.control_connected = False
        self.state_tick = self.create_timer(0.1, self.refresh_state)
        self.connection_tick = self.create_timer(1.0, self.refresh_connection)
        self.publish_tick = self.create_timer(1.0 / publish_hz, self.publish_latest)
        self.last_log = ""

    def refresh_connection(self) -> None:
        payload = self.fetch_json(self.connection_url)
        if not payload:
            self.control_connected = False
            return
        control = payload.get("controlBridge", {})
        self.control_connected = bool(control.get("connected", False))

    def refresh_state(self) -> None:
        payload = self.fetch_json(self.state_url)
        if payload:
            self.latest_state = payload
            self.last_state_received = time.monotonic()
        else:
            self.latest_state = None

    def publish_latest(self) -> None:
        if not self.control_connected or not self.latest_state or time.monotonic() - self.last_state_received > 0.5:
            return

        now = self.get_clock().now().to_msg()
        odom = Odometry()
        odom.header.stamp = now
        odom.header.frame_id = "odom"
        odom.child_frame_id = "base_footprint"
        odom.pose.pose.position.x = float(self.latest_state.get("x", 0.0))
        odom.pose.pose.position.y = float(self.latest_state.get("y", 0.0))
        odom.pose.pose.position.z = 0.0
        roll = float(self.latest_state.get("roll", 0.0))
        pitch = float(self.latest_state.get("pitch", 0.0))
        yaw = float(self.latest_state.get("yaw", 0.0))
        qx, qy, qz, qw = quaternion_from_rpy(roll, pitch, yaw)
        odom.pose.pose.orientation.x = qx
        odom.pose.pose.orientation.y = qy
        odom.pose.pose.orientation.z = qz
        odom.pose.pose.orientation.w = qw
        odom.twist.twist.linear.x = float(self.latest_state.get("linearVelocity", 0.0))
        odom.twist.twist.angular.z = float(self.latest_state.get("angularVelocity", 0.0))
        self.odom_pub.publish(odom)

        imu = Imu()
        imu.header.stamp = now
        imu.header.frame_id = "imu_link"
        imu.orientation.x = qx
        imu.orientation.y = qy
        imu.orientation.z = qz
        imu.orientation.w = qw
        imu.angular_velocity.x = float(self.latest_state.get("angularVelX", 0.0))
        imu.angular_velocity.y = float(self.latest_state.get("angularVelY", 0.0))
        imu.angular_velocity.z = float(self.latest_state.get("angularVelZ", 0.0))
        imu.linear_acceleration.x = float(self.latest_state.get("accelX", 0.0))
        imu.linear_acceleration.y = float(self.latest_state.get("accelY", 0.0))
        imu.linear_acceleration.z = float(self.latest_state.get("accelZ", 0.0))
        self.imu_pub.publish(imu)

        summary = (
            f"connected={self.control_connected} "
            f"x={odom.pose.pose.position.x:.3f} "
            f"y={odom.pose.pose.position.y:.3f} "
            f"yaw={yaw:.3f} "
            f"vx={odom.twist.twist.linear.x:.3f} "
            f"wz={odom.twist.twist.angular.z:.3f}"
        )
        if summary != self.last_log:
            self.get_logger().info(summary)
            self.last_log = summary

    def fetch_json(self, url: str) -> dict | None:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return None


def main() -> int:
    backend = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
    publish_hz = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
    rclpy.init()
    node = ControlStateBridge(backend, publish_hz)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
