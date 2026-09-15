#!/usr/bin/env bash
set -euo pipefail

WORKBENCH_ROOT="$(dirname -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")")"

TOOLS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=fishbot_ros_env.sh
source "$TOOLS_DIR/fishbot_ros_env.sh"

set +u
fishbot_source_ros
source "${WORKBENCH_ROOT}/fishbot_laser_ws/install/setup.bash"
source "${WORKBENCH_ROOT}/fishbot_nav/install/setup.bash"
set -u

export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"

timeout 20 python3 - <<'PY'
import rclpy
from rclpy.node import Node
from nav_msgs.msg import OccupancyGrid
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from rclpy.executors import ExternalShutdownException

class Probe(Node):
    def __init__(self):
        super().__init__('map_probe')
        qos = QoSProfile(depth=1)
        qos.reliability = ReliabilityPolicy.RELIABLE
        qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self.create_subscription(OccupancyGrid, '/map', self.cb, qos)
        self.get_logger().info('waiting /map ...')

    def cb(self, msg):
        print(
            f"RECV map width={msg.info.width} height={msg.info.height} "
            f"res={msg.info.resolution} frame={msg.header.frame_id}",
            flush=True,
        )
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
