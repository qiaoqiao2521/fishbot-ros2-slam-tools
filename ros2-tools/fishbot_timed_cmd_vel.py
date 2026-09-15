#!/usr/bin/env python3
import argparse
import time
import math
import signal

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node


class TimedCmdVel(Node):
    def __init__(self, linear_x: float, angular_z: float, seconds: float, hz: float) -> None:
        super().__init__("fishbot_timed_cmd_vel")
        self.publisher = self.create_publisher(Twist, "/cmd_vel", 10)
        self.linear_x = linear_x
        self.angular_z = angular_z
        self.deadline = time.monotonic() + max(0.0, seconds)
        self.done = False
        self.create_timer(1.0 / hz, self.publish_once)

    def publish_once(self) -> None:
        msg = Twist()
        if time.monotonic() < self.deadline:
            msg.linear.x = self.linear_x
            msg.angular.z = self.angular_z
        else:
            self.done = True
        self.publisher.publish(msg)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--linear-x", type=float, default=0.0)
    parser.add_argument("--angular-z", type=float, default=0.0)
    parser.add_argument("--seconds", type=float, default=1.0)
    parser.add_argument("--hz", type=float, default=10.0)
    args = parser.parse_args()
    if not all(math.isfinite(v) for v in (args.linear_x, args.angular_z, args.seconds, args.hz)) or not (0 < args.hz <= 100 and 0 <= args.seconds <= 300 and abs(args.linear_x) <= 0.3 and abs(args.angular_z) <= 1.0):
        parser.error('finite values required: |linear|<=0.3, |angular|<=1, seconds 0..300, hz (0,100]')

    from rclpy.signals import SignalHandlerOptions
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = TimedCmdVel(args.linear_x, args.angular_z, args.seconds, args.hz)
    def request_stop(signum, frame):
        node.deadline = 0.0
        node.done = True
    previous = {s: signal.signal(s, request_stop) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        while rclpy.ok() and not node.done:
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        node.deadline = 0.0
        try:
            if rclpy.ok():
                for _ in range(3):
                    node.publish_once()
                    time.sleep(0.05)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
