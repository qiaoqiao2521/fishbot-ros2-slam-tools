#!/usr/bin/python3
"""Finite startup gate. Exit zero only while real sensors and clock are fresh."""
import argparse
import json
import math
import os
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rosgraph_msgs.msg import Clock
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from lifecycle_msgs.srv import GetState
from tf2_ros import Buffer, TransformListener


class Readiness(Node):
    def __init__(self, nav):
        super().__init__('fishbot_startup_readiness', parameter_overrides=[
            rclpy.parameter.Parameter('use_sim_time', value=True)])
        self.nav = nav
        self.clock_stamp = self.clock_wall = self.clock_advanced_wall = None
        self.samples = {}
        self.create_subscription(Clock,'/clock',self.on_clock,qos_profile_sensor_data)
        self.create_subscription(Odometry,'/odom',lambda msg:self.sensor('odom',msg),qos_profile_sensor_data)
        self.create_subscription(LaserScan,'/scan',lambda msg:self.sensor('scan',msg),qos_profile_sensor_data)
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer,self)
        names = ['amcl','controller_server','bt_navigator','collision_monitor'] if nav else []
        self.lifecycle_clients = {name:self.create_client(GetState,f'/{name}/get_state') for name in names}
        self.pending, self.lifecycle, self.last_query = {}, {}, {}

    def on_clock(self,msg):
        stamp = msg.clock.sec+msg.clock.nanosec*1e-9
        wall = time.monotonic()
        if self.clock_stamp is not None and stamp > self.clock_stamp:
            self.clock_advanced_wall = wall
        self.clock_stamp,self.clock_wall = stamp,wall

    def sensor(self,name,msg):
        self.samples[name] = (msg,time.monotonic(),msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9)

    def update_lifecycle(self):
        now = time.monotonic()
        for name,client in self.lifecycle_clients.items():
            future = self.pending.get(name)
            if future is not None:
                if future.done():
                    try:
                        self.lifecycle[name] = (future.result().current_state.id,now)
                    except Exception:
                        self.lifecycle.pop(name,None)
                    del self.pending[name]
                elif now-self.last_query[name] > 2.0:
                    client.remove_pending_request(future)
                    future.cancel()
                    del self.pending[name]
                    self.lifecycle.pop(name,None)
            elif client.service_is_ready() and now-self.last_query.get(name,-math.inf) >= 0.5:
                self.pending[name] = client.call_async(GetState.Request())
                self.last_query[name] = now

    def reason(self):
        wall = time.monotonic()
        if (self.clock_wall is None or wall-self.clock_wall > 0.6
                or self.clock_advanced_wall is None or wall-self.clock_advanced_wall > 0.6):
            return 'Simulation /clock is missing, stale or not advancing'
        ros = self.get_clock().now().nanoseconds*1e-9
        if abs(ros-self.clock_stamp)>0.6:
            return 'Node simulation time disagrees with /clock'
        for name in ('odom','scan'):
            sample = self.samples.get(name)
            if sample is None or wall-sample[1]>0.6 or abs(ros-sample[2])>0.6:
                return f'/{name} is missing or stale in wall / simulation time'
        odom = self.samples['odom'][0]
        pose,twist = odom.pose.pose,odom.twist.twist
        values = [pose.position.x,pose.position.y,pose.position.z,
                  pose.orientation.x,pose.orientation.y,pose.orientation.z,pose.orientation.w,
                  twist.linear.x,twist.linear.y,twist.angular.z]
        if not all(math.isfinite(value) for value in values):
            return '/odom contains nonfinite pose / velocity'
        scan = self.samples['scan'][0]
        if not scan.ranges or not any(math.isfinite(value) and scan.range_min<=value<=scan.range_max for value in scan.ranges):
            return '/scan contains no finite in-range returns'
        for name in self.lifecycle_clients:
            state = self.lifecycle.get(name)
            if state is None or state[0]!=3 or wall-state[1]>3.0:
                return f'{name} lifecycle is not freshly confirmed ACTIVE'
        if self.nav:
            try:
                transform = self.buffer.lookup_transform('map','base_footprint',rclpy.time.Time())
                stamp = transform.header.stamp.sec+transform.header.stamp.nanosec*1e-9
                if abs(ros-stamp)>0.8:
                    return 'map -> base_footprint transform is stale'
            except Exception:
                return 'map -> base_footprint transform is unavailable'
        return None


def validate_sim_domain(environ=None):
    env = os.environ if environ is None else environ
    selected = env.get('FISHBOT_MUJOCO_DOMAIN_ID', '93')
    if (not selected.isascii() or not selected.isdigit() or not 1 <= int(selected) <= 232
            or env.get('ROS_DOMAIN_ID') != selected
            or env.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST'):
        raise SystemExit('Readiness gate requires matching explicit simulation domain 1..232 (default 93) / loopback discovery')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nav',choices=['true','false'],default='true')
    parser.add_argument('--timeout',type=float,default=45.0)
    args,rosargs = parser.parse_known_args()
    if not 1.0 <= args.timeout <= 60.0:
        parser.error('--timeout must be between 1 and 60 wall-clock seconds')
    validate_sim_domain()
    rclpy.init(args=rosargs)
    node = Readiness(args.nav=='true')
    started,last_log = time.monotonic(),0.0
    reason,ready = 'No messages received',False
    try:
        while time.monotonic()-started < args.timeout and rclpy.ok():
            rclpy.spin_once(node,timeout_sec=0.05)
            node.update_lifecycle()
            reason = node.reason()
            if reason is None:
                ready = True
                break
            if time.monotonic()-last_log > 5.0:
                node.get_logger().info(f'Waiting for startup: {reason}')
                last_log = time.monotonic()
        print(json.dumps({'ready':ready,'nav':node.nav,'elapsed_seconds':round(time.monotonic()-started,3),
                          'reason':'Clock, sensors and requested navigation are fresh / ready' if ready else reason}),flush=True)
    except KeyboardInterrupt:
        print(json.dumps({'ready':False,'reason':'Readiness check interrupted'}),flush=True)
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
    raise SystemExit(0 if ready else 1)


if __name__=='__main__':
    main()
