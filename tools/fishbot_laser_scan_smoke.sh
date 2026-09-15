#!/usr/bin/env bash
set -euo pipefail

WORKBENCH_ROOT="$(dirname -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")")"

WS="${WORKBENCH_ROOT}/fishbot_laser_ws"
LOG="/tmp/fishbot_laser_driver.log"
TOOLS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=fishbot_ros_env.sh
source "$TOOLS_DIR/fishbot_ros_env.sh"

cleanup() {
  if [[ -n "${DRIVER_PID:-}" ]]; then
    kill "$DRIVER_PID" 2>/dev/null || true
    wait "$DRIVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

fuser -k 8889/tcp 2>/dev/null || true
fuser -k 8889/udp 2>/dev/null || true

cd "$WS"
set +u
fishbot_source_ros
source "$WS/install/setup.bash"
set -u
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_DOMAIN_ID=0

: > "$LOG"
ros2 run ydlidar ydlidar_node --ros-args -p protocol:=net -p socket_port:=8889 >"$LOG" 2>&1 &
DRIVER_PID=$!

echo "driver pid=$DRIVER_PID"
echo "waiting for TCP connection and lidar type..."

for _ in $(seq 1 40); do
  if grep -q "雷达型号: LidarType.LIDAR_TYPE_X2K" "$LOG"; then
    break
  fi
  sleep 1
done

echo "--- driver tail ---"
tail -n 40 "$LOG" || true
echo "-------------------"

echo "probing /scan for up to 25s..."
timeout 25 python3 - <<'PY'
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy

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
        print(f'RECV count={self.count} ranges={len(msg.ranges)} frame={msg.header.frame_id}')
        if self.count >= 3:
            raise SystemExit(0)

rclpy.init()
node = Probe()
try:
    rclpy.spin(node)
except (KeyboardInterrupt, SystemExit):
    pass
finally:
    node.destroy_node()
    rclpy.shutdown()
PY
