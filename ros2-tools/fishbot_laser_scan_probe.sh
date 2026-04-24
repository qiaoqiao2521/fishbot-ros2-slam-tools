#!/usr/bin/env bash
set -euo pipefail

WS="/home/muqiao/dev/ros2/fishbot_laser_ws"

cd "$WS"
set +u
source /opt/ros/humble/setup.bash
source "$WS/install/setup.bash"
set -u
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_DOMAIN_ID=0

timeout 25 python3 - <<'PY'
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from rclpy.executors import ExternalShutdownException

class Probe(Node):
    def __init__(self):
        super().__init__('scan_probe')
        qos = QoSProfile(depth=10)
        qos.reliability = ReliabilityPolicy.BEST_EFFORT
        qos.durability = DurabilityPolicy.VOLATILE
        self.count = 0
        self.create_subscription(LaserScan, '/scan', self.cb, qos)
        self.get_logger().info('waiting /scan ...')

    def cb(self, msg):
        self.count += 1
        print(f'RECV count={self.count} ranges={len(msg.ranges)} frame={msg.header.frame_id}', flush=True)
        if self.count >= 3:
            raise SystemExit(0)

rclpy.init()
node = Probe()
try:
    rclpy.spin(node)
except (KeyboardInterrupt, SystemExit, ExternalShutdownException):
    pass
finally:
    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()
PY
