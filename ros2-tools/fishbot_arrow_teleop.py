#!/usr/bin/env python3
import os
import select
import sys
import termios
import threading
import time
import tty
import math

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node


LINEAR_STEP = float(os.environ.get("FISHBOT_ARROW_LINEAR", "0.05"))
ANGULAR_STEP = float(os.environ.get("FISHBOT_ARROW_ANGULAR", "0.35"))
PUBLISH_HZ = float(os.environ.get("FISHBOT_ARROW_HZ", "8.0"))
IDLE_TIMEOUT = float(os.environ.get("FISHBOT_ARROW_IDLE_TIMEOUT", "0.25"))
if not all(math.isfinite(v) for v in (LINEAR_STEP, ANGULAR_STEP, PUBLISH_HZ, IDLE_TIMEOUT)) or not (0 <= LINEAR_STEP <= 0.3 and 0 <= ANGULAR_STEP <= 1.0 and 5 <= PUBLISH_HZ <= 50 and 0 < IDLE_TIMEOUT <= 0.5):
    raise ValueError('Invalid teleop limits: linear 0..0.3, angular 0..1, hz 5..50, idle (0,0.5]')


HELP = f"""FishBot arrow teleop

Controls:
  Up       forward   ({LINEAR_STEP:.2f} m/s)
  Down     backward  ({-LINEAR_STEP:.2f} m/s)
  Left     turn left ({ANGULAR_STEP:.2f} rad/s)
  Right    turn right({-ANGULAR_STEP:.2f} rad/s)
  Space    stop
  q        quit

Behavior:
  - Hold a key to keep publishing motion.
  - Release keys and the robot auto-stops after {IDLE_TIMEOUT:.2f}s.
  - Space sends an immediate zero command.
"""


class ArrowTeleop(Node):
    def __init__(self) -> None:
        super().__init__("fishbot_arrow_teleop")
        self.pub = self.create_publisher(Twist, "/cmd_vel", 10)
        self.linear_x = 0.0
        self.angular_z = 0.0
        self.last_input_time = time.monotonic()
        self.last_sent = None
        self.quit_requested = False
        period = 1.0 / PUBLISH_HZ
        self.create_timer(period, self.publish_loop)

    def set_motion(self, linear_x: float, angular_z: float) -> None:
        self.linear_x = linear_x
        self.angular_z = angular_z
        self.last_input_time = time.monotonic()

    def stop_now(self) -> None:
        self.linear_x = 0.0
        self.angular_z = 0.0
        self.last_input_time = time.monotonic()
        self.publish(force=True)

    def publish_loop(self) -> None:
        if time.monotonic() - self.last_input_time > IDLE_TIMEOUT:
            if self.linear_x != 0.0 or self.angular_z != 0.0:
                self.linear_x = 0.0
                self.angular_z = 0.0
        self.publish()

    def publish(self, force: bool = False) -> None:
        current = (self.linear_x, self.angular_z)
        # Repeat commands: packet loss and the motor watchdog require a heartbeat.
        msg = Twist()
        msg.linear.x = self.linear_x
        msg.angular.z = self.angular_z
        self.pub.publish(msg)
        self.last_sent = current


def read_key(fd: int) -> str | None:
    ready, _, _ = select.select([fd], [], [], 0.1)
    if not ready:
        return None
    first = os.read(fd, 1)
    if not first:
        return None
    if first == b"\x1b":
        rest = os.read(fd, 2)
        return (first + rest).decode("utf-8", errors="ignore")
    return first.decode("utf-8", errors="ignore")


def input_loop(node: ArrowTeleop, fd: int) -> None:
    while not node.quit_requested:
        key = read_key(fd)
        if key is None:
            continue
        if key == "\x1b[A":
            node.set_motion(LINEAR_STEP, 0.0)
        elif key == "\x1b[B":
            node.set_motion(-LINEAR_STEP, 0.0)
        elif key == "\x1b[D":
            node.set_motion(0.0, ANGULAR_STEP)
        elif key == "\x1b[C":
            node.set_motion(0.0, -ANGULAR_STEP)
        elif key == " ":
            node.stop_now()
        elif key.lower() == "q":
            node.quit_requested = True
            node.stop_now()
            break


def main() -> int:
    print(HELP, flush=True)
    if not sys.stdin.isatty():
        print("error: arrow teleop requires a TTY", file=sys.stderr)
        return 2

    rclpy.init()
    node = ArrowTeleop()

    old_settings = termios.tcgetattr(sys.stdin.fileno())
    input_thread = None
    try:
        tty.setraw(sys.stdin.fileno())
        input_thread = threading.Thread(
            target=input_loop, args=(node, sys.stdin.fileno()), daemon=True
        )
        input_thread.start()
        while rclpy.ok() and not node.quit_requested:
            rclpy.spin_once(node, timeout_sec=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        node.quit_requested = True
        node.stop_now()
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)
        if input_thread is not None:
            input_thread.join(timeout=1.0)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
