#!/usr/bin/env python3
"""Real ROS 2 + Linux PTY check. Never opens a physical serial device."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import time
import tty


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--domain', type=int, default=181)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    os.environ['ROS_DOMAIN_ID'] = str(args.domain)
    os.environ['ROS_LOCALHOST_ONLY'] = '1'
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
    from tf2_msgs.msg import TFMessage
    import robot_base.drive_node as module

    master, slave = os.openpty()
    tty.setraw(master); tty.setraw(slave); os.set_blocking(master, False)
    serial_path = os.ttyname(slave)
    report = {'scope': 'ROS 2 driver with synthetic PTY feedback; no physical chassis or MuJoCo acceptance',
              'passed': False, 'checks': [], 'domain': args.domain, 'serial': serial_path,
              'module': module.__file__, 'physical_serial_opened': False}
    driver = observer = executor = None
    packets = []
    buffer = b''
    odometry, transforms = [], []

    def read_packets():
        nonlocal buffer
        try:
            buffer += os.read(master, 65536)
        except BlockingIOError:
            pass
        packets[:] = [tuple(map(int, match)) for match in re.findall(rb'\$pwm:(-?\d+),(-?\d+),(-?\d+),(-?\d+)#', buffer)]

    def until(predicate, timeout=3., feedback=None):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if feedback is not None:
                os.write(master, feedback)
            executor.spin_once(timeout_sec=.01)
            read_packets()
            if predicate():
                return
        raise AssertionError('PTY/ROS observation timed out')

    try:
        rclpy.init(args=['--ros-args', '-r', '__ns:=/mecanum_probe',
                        '-p', f'serial_port:={serial_path}', '-p', 'cmd_timeout:=0.15',
                        '-p', 'min_command_pwm:=0', '-p', 'feedback_sign:=1.0',
                        '-p', 'allow_cmd_odom_fallback:=false'])
        driver = module.RobotDriveNode()
        if driver.serial_port != serial_path or not serial_path.startswith('/dev/pts/'):
            raise AssertionError('Probe must use its own PTY')
        observer = rclpy.create_node('serial_probe_observer')
        publisher = observer.create_publisher(Twist, '/mecanum_probe/cmd_vel', 10)
        observer.create_subscription(Odometry, '/mecanum_probe/odom', odometry.append, 10)
        observer.create_subscription(TFMessage, '/tf', lambda msg: transforms.extend(msg.transforms), 10)
        executor = SingleThreadedExecutor()
        executor.add_node(driver); executor.add_node(observer)
        until(lambda: publisher.get_subscription_count() > 0 and bool(odometry))
        if not packets or packets[0] != (0, 0, 0, 0) or b'$upload:0,0,1#' not in buffer:
            raise AssertionError('Connection must start at zero and enable feedback')
        report['checks'].append('startup zero and MSPD enable over actual PTY')
        for label, components, signs in [
            ('forward', (.05, 0., 0.), (1, 1, 1, 1)),
            ('lateral', (0., .05, 0.), (-1, 1, 1, -1)),
            ('rotation', (0., 0., .05), (-1, -1, 1, 1)),
        ]:
            message = Twist()
            message.linear.x, message.linear.y, message.angular.z = components
            count = len(packets)
            publisher.publish(message)
            until(lambda: any(tuple(1 if v > 0 else -1 if v < 0 else 0 for v in p) == signs for p in packets[count:]))
            report['checks'].append(f'{label}: ROS Twist produces expected signed wheel protocol')
        count = len(packets)
        until(lambda: (0, 0, 0, 0) in packets[count:] and driver.last_cmd_time is not None
              and time.monotonic() - driver.last_cmd_time >= .15)
        report['checks'].append('host watchdog emits zero after command expiry')
        count = len(odometry)
        until(lambda: len(odometry) > count and abs(odometry[-1].twist.twist.linear.y - .05) < 1e-6
              and abs(odometry[-1].twist.twist.linear.x) < 1e-6 and abs(odometry[-1].twist.twist.angular.z) < 1e-6
              and any(t.child_frame_id == 'base_link' and t.transform.translation.y > .0001 for t in transforms),
              feedback=b'$MSPD:-50,50,50,-50#')
        report['checks'].append('synthetic wheel feedback produces lateral Odometry and odom/base_link TF')
        report['lateral_odometry_m_s'] = {
            'vx': odometry[-1].twist.twist.linear.x,
            'vy': odometry[-1].twist.twist.linear.y,
            'wz': odometry[-1].twist.twist.angular.z,
        }
        message = Twist(); message.linear.x = math.nan
        publisher.publish(message)
        until(lambda: driver.last_cmd_time is None and packets[-1] == (0, 0, 0, 0))
        report['checks'].append('nonfinite ROS command is rejected with a zero frame')
        # Exercise the watchdog's send/reconnect path, not only the 2s reconnect timer.
        upload_count = buffer.count(b'$upload:0,0,1#')
        with driver.serial_lock:
            driver.ser.close()
        until(lambda: driver.ser is not None and driver.ser.is_open and buffer.count(b'$upload:0,0,1#') > upload_count)
        report['checks'].append('reconnect through command watchdog restores feedback enable')
        report['passed'] = True
    finally:
        if executor:
            executor.shutdown()
        if driver:
            driver.destroy_node()
        if observer:
            observer.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        os.close(master); os.close(slave)
        report['cleanup_closed'] = not (driver and driver.serial_thread.is_alive())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(report))


if __name__ == '__main__':
    main()
