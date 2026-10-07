#!/usr/bin/python3
"""Drive one external MuJoCo box, with measured state and bounded clearance.

The car is never included in SetFreeJointState requests. Box motion is externally
prescribed; its collision and rangefinder geometry remain ordinary MuJoCo geoms.
"""
import heapq
import json
import math
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import rclpy
from rclpy.clock import Clock, ClockType
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import String
from std_srvs.srv import Trigger
from mujoco_ros2_control_msgs.msg import FreeJointState, FreeJointStateArray
from mujoco_ros2_control_msgs.srv import SetFreeJointState
from ament_index_python.packages import get_package_share_directory

PARK = (-0.70, -0.70)
ACTOR_RADIUS = math.hypot(0.18, 0.18)
ROBOT_CLEARANCE = 0.13 + ACTOR_RADIUS + 0.055
MAX_SPEED = 0.75
FORWARD_DISTANCES = (0.80, 0.65, 0.60)


def valid_point(point, boxes, robot=None):
    """Conservative circular box envelope, walls and current robot clearance."""
    x, y = point
    if not all(math.isfinite(v) for v in point) or max(abs(x), abs(y)) > 3.5:
        return False
    margin = ACTOR_RADIUS + 0.045
    if any(abs(x-bx) <= sx+margin and abs(y-by) <= sy+margin for bx, by, sx, sy in boxes):
        return False
    return robot is None or math.dist(point, robot) >= ROBOT_CLEARANCE


def segment_clear(start, end, boxes, robot=None):
    count = max(2, math.ceil(math.dist(start, end)/0.025))
    return all(valid_point((start[0]+(end[0]-start[0])*i/count,
                            start[1]+(end[1]-start[1])*i/count), boxes, robot)
               for i in range(count+1))


def safe_path(start, end, boxes, robot):
    """Small fixture A*; no straight-line shortcut through a fixed box or car."""
    if not valid_point(start, boxes, robot) or not valid_point(end, boxes, robot):
        return None
    if segment_clear(start, end, boxes, robot):
        return [end]
    step = 0.10
    origin = tuple(round(value/step) for value in start)
    goal = tuple(round(value/step) for value in end)
    def point(cell):
        return cell[0]*step, cell[1]*step
    if not segment_clear(start, point(origin), boxes, robot):
        return None
    queue = [(math.dist(point(origin), end), 0.0, origin)]
    cost, parent = {origin: 0.0}, {}
    while queue:
        _, current_cost, current = heapq.heappop(queue)
        if current_cost > cost[current]+1e-9:
            continue
        if current == goal and segment_clear(point(current), end, boxes, robot):
            cells = [current]
            while cells[-1] != origin:
                cells.append(parent[cells[-1]])
            # Keep corners, not every grid cell. All shortcuts use the same full
            # swept clearance checks; async service latency must not accumulate
            # an extra timer wait at each 10 cm cell.
            raw = [start]+[point(cell) for cell in reversed(cells)]+[end]
            result, index = [], 0
            while index < len(raw)-1:
                following = len(raw)-1
                while following > index+1 and not segment_clear(raw[index],raw[following],boxes,robot):
                    following -= 1
                result.append(raw[following])
                index = following
            return result
        for dx, dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
            following = current[0]+dx, current[1]+dy
            if not segment_clear(point(current), point(following), boxes, robot):
                continue
            new_cost = current_cost+step*math.hypot(dx,dy)
            if new_cost < cost.get(following, math.inf):
                cost[following], parent[following] = new_cost, current
                heapq.heappush(queue, (new_cost+math.dist(point(following), end),new_cost,following))
    return None


class ObstacleController(Node):
    def __init__(self):
        super().__init__('fishbot_dynamic_obstacle', parameter_overrides=[
            rclpy.parameter.Parameter('use_sim_time', value=True)])
        arena = Path(get_package_share_directory('fishbot_mujoco'))/'mjcf'/'arena.xml'
        self.boxes = []
        for geom in ET.parse(arena).getroot().find('worldbody').findall('geom'):
            if geom.get('type') == 'box':
                pos, size = geom.get('pos','0 0 0').split(), geom.get('size').split()
                self.boxes.append((float(pos[0]),float(pos[1]),float(size[0]),float(size[1])))
        self.robot = self.actor = None
        self.robot_sample = self.actor_sample = None
        self.truth_stamp = self.truth_wall = self.clock_advanced_wall = None
        self.state, self.message = 'parked', 'Waiting for measured actor state'
        self.path, self.phase = [], None
        self.cycle_start = self.hold_start = None
        self.pending = None
        self.pending_wall = None
        self.client = None
        self.last_tick = time.monotonic()
        self.last_move_wall = self.last_tick
        self.create_subscription(FreeJointStateArray, '/ground_truth/free_joint_states', self.truth_callback, qos_profile_sensor_data)
        self.publisher = self.create_publisher(String, '/sim/obstacle/state', 10)
        self.create_service(Trigger, '/sim/obstacle/block_path', self.block)
        self.create_service(Trigger, '/sim/obstacle/clear', self.clear)
        self.timer = self.create_timer(0.05, self.tick, clock=Clock(clock_type=ClockType.STEADY_TIME))

    def truth_callback(self, msg):
        stamp = msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9
        wall = time.monotonic()
        if self.truth_stamp is None or stamp > self.truth_stamp:
            self.clock_advanced_wall = wall
        self.truth_stamp, self.truth_wall = stamp, wall
        for item in msg.free_joints:
            if item.name == 'base_footprint':
                self.robot = item
                self.robot_sample = (stamp, wall)
            elif item.name == 'moving_obstacle':
                self.actor = item
                self.actor_sample = (stamp, wall)

    def fresh(self):
        wall, ros = time.monotonic(), self.get_clock().now().nanoseconds*1e-9
        if self.robot is None or self.actor is None or self.truth_wall is None:
            return False
        values = (self.robot.pose.pose.position.x,self.robot.pose.pose.position.y,
                  self.actor.pose.pose.position.x,self.actor.pose.pose.position.y)
        return (all(math.isfinite(v) for v in values) and wall-self.truth_wall < 0.5
                and self.clock_advanced_wall is not None and wall-self.clock_advanced_wall < 0.5
                and abs(ros-self.truth_stamp) < 0.5
                and self.robot_sample is not None and self.actor_sample is not None
                and wall-self.robot_sample[1] < 0.5 and abs(ros-self.robot_sample[0]) < 0.5
                and wall-self.actor_sample[1] < 0.5 and abs(ros-self.actor_sample[0]) < 0.5)

    @staticmethod
    def xy(item):
        return item.pose.pose.position.x, item.pose.pose.position.y

    def fail(self, message):
        self.state, self.message, self.path = 'error', message, []
        self.get_logger().error(message)

    def locate_service(self):
        if self.client is not None:
            return self.client.service_is_ready()
        for name, types in self.get_service_names_and_types():
            if 'mujoco_ros2_control_msgs/srv/SetFreeJointState' in types:
                self.client = self.create_client(SetFreeJointState, name)
                self.get_logger().info(f'External actor service: {name}')
                return self.client.service_is_ready()
        return False

    def staging_path(self):
        position = self.xy(self.robot)
        q = self.robot.pose.pose.orientation
        yaw = math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
        forward, left = (math.cos(yaw),math.sin(yaw)), (-math.sin(yaw),math.cos(yaw))
        for distance in FORWARD_DISTANCES:
            target = (position[0]+distance*forward[0],position[1]+distance*forward[1])
            if not valid_point(target,self.boxes,position):
                continue
            choices = []
            for side in (-1,1):
                staging = (target[0]+side*0.65*left[0],target[1]+side*0.65*left[1])
                path = safe_path(self.xy(self.actor), staging, self.boxes, position)
                if path:
                    choices.append((sum(math.dist(a,b) for a,b in zip([self.xy(self.actor)]+path,path)),path))
            if choices:
                return min(choices,key=lambda choice:choice[0])[1]
        return None

    def block(self, request, response):
        if self.state != 'parked' or not self.fresh() or not self.locate_service():
            response.success, response.message = False, 'Actor busy, simulation stale or MuJoCo service unavailable'
            return response
        path = self.staging_path()
        if path is None:
            response.success, response.message = False, 'No collision-free side approach in this fixture'
            return response
        self.path = path
        self.state, self.phase, self.message = 'moving', 'staging', 'Approaching from the side'
        self.cycle_start = time.monotonic()
        self.last_move_wall = self.cycle_start
        response.success, response.message = True, 'Physical obstacle cycle accepted'
        return response

    def start_return(self):
        path = safe_path(self.xy(self.actor), PARK, self.boxes, self.xy(self.robot))
        if path is None:
            self.fail('Cannot safely return actor around current robot and fixture')
            return False
        self.path, self.state, self.phase = path, 'returning', 'return'
        self.last_move_wall = time.monotonic()
        self.message = 'Returning outside the route'
        return True

    def clear(self, request, response):
        if not self.fresh() or not self.locate_service():
            response.success, response.message = False, 'Cannot move actor with stale simulation or unavailable service'
        elif self.state == 'parked':
            response.success, response.message = True, 'Actor already parked'
        else:
            response.success = self.start_return()
            if response.success:
                self.cycle_start = time.monotonic()
            response.message = 'Safe return accepted' if response.success else self.message
        return response

    def write_actor(self, position):
        # A single hard-coded name makes robot teleportation impossible through this node.
        state = FreeJointState()
        state.name = 'moving_obstacle'
        state.pose.pose.position.x, state.pose.pose.position.y = position
        state.pose.pose.position.z = 0.222
        state.pose.pose.orientation.w = 1.0
        request = SetFreeJointState.Request()
        request.free_joints = [state]
        self.pending = self.client.call_async(request)
        self.pending_wall = time.monotonic()
        self.last_move_wall = self.pending_wall

    def tick(self):
        now = time.monotonic()
        self.last_tick = now
        if self.pending is not None:
            if self.pending.done():
                try:
                    response = self.pending.result()
                    if not response.success:
                        self.fail(f'MuJoCo rejected actor: {response.message}')
                except Exception as error:
                    self.fail(f'Actor service failed: {error}')
                self.pending = None
            elif now-self.pending_wall > 1.0:
                self.fail('MuJoCo actor service timed out')
                self.pending.cancel()
                self.pending = None
        if self.state in ('moving','blocking','returning'):
            if not self.fresh():
                self.fail('Ground truth or simulation clock stopped advancing; actor frozen')
            elif self.cycle_start is not None and now-self.cycle_start > 25.0:
                self.fail('External actor cycle exceeded its 25 second limit')
            elif self.pending is None:
                if self.state == 'moving' and now-self.cycle_start > 15.0:
                    self.message = 'Insertion time budget exhausted; yielding safely'
                    self.start_return()
                if self.state == 'blocking':
                    if now-self.hold_start >= 3.5 or math.dist(self.xy(self.actor),self.xy(self.robot)) < ROBOT_CLEARANCE+0.035:
                        self.start_return()
                elif self.path:
                    actual, target = self.xy(self.actor), self.path[0]
                    # Native pose writes can reach millimetre accuracy. A loose
                    # tolerance at an A* corner cuts into inflated geometry,
                    # causing repeated safe-return replans at the same corner.
                    distance = math.dist(actual,target)
                    if distance < 0.004 and (len(self.path)==1 or
                            segment_clear(actual,self.path[1],self.boxes,self.xy(self.robot))):
                        self.path.pop(0)
                    elif distance < 1e-6:
                        # The robot may have moved onto the next segment while
                        # the actor reached this corner; replan rather than
                        # divide by zero or bypass the swept clearance guard.
                        self.start_return()
                    else:
                        # Account for actual async service completion intervals,
                        # while bounding each externally prescribed pose step.
                        elapsed = min(now-self.last_move_wall,0.15)
                        step = min(MAX_SPEED*elapsed,0.10,distance)
                        following = tuple(a+(b-a)*step/distance for a,b in zip(actual,target))
                        if segment_clear(actual,following,self.boxes,self.xy(self.robot)):
                            self.write_actor(following)
                        else:
                            self.start_return()
                else:
                    if self.phase == 'staging':
                        position = self.xy(self.robot)
                        q = self.robot.pose.pose.orientation
                        yaw = math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
                        targets = [(position[0]+distance*math.cos(yaw),position[1]+distance*math.sin(yaw))
                                   for distance in FORWARD_DISTANCES]
                        target = next((point for point in targets if valid_point(point,self.boxes,position)),None)
                        if target is not None and segment_clear(self.xy(self.actor),target,self.boxes,position):
                            self.path, self.phase, self.message = [target], 'insert', 'Entering the forward route'
                        else:
                            # A moving car can outdate the original staging pose.
                            # Catch up on its side rather than crossing its body.
                            path = self.staging_path()
                            if path is not None:
                                self.path, self.message = path, 'Repositioning beside the moving car'
                            else:
                                self.start_return()
                    elif self.phase == 'insert':
                        self.state, self.hold_start, self.message = 'blocking', now, 'Holding briefly, then yielding'
                    elif self.phase == 'return':
                        self.state, self.phase, self.message = 'parked', None, 'Measured actor back at parking point'
                        self.cycle_start = None
        position = self.xy(self.actor) if self.actor is not None else (None,None)
        if self.state == 'parked' and self.fresh():
            self.message = 'Measured actor at parking point'
        self.publisher.publish(String(data=json.dumps({'state':self.state,'x':position[0],
            'y':position[1],'size':0.36,'fresh':self.fresh(),'message':self.message})))


def validate_sim_domain(environ=None):
    env = os.environ if environ is None else environ
    selected = env.get('FISHBOT_MUJOCO_DOMAIN_ID', '93')
    if (not selected.isascii() or not selected.isdigit() or not 1 <= int(selected) <= 232
            or env.get('ROS_DOMAIN_ID') != selected
            or env.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST'):
        raise SystemExit('External actor requires matching explicit simulation domain 1..232 (default 93) / loopback discovery')


def main():
    validate_sim_domain()
    rclpy.init()
    node = ObstacleController()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
