#!/usr/bin/env python3
"""FishBot 轻量 2D 仿真节点。

用已保存的真实栅格地图做 raycast 合成 /scan，用差速运动学积分发布 /odom 和
odom->base_footprint TF；ground-truth 模式下同时发布 map->odom TF（等价完美定位），
用于在不接实机的情况下迭代 Nav2 导航避障算法。

雷达参数默认对齐实机 ydlidar（360 度、719 点、约 7Hz、0.05-64m）。

用法要点：
- RViz "Publish Point" 点击地图空白处注入虚拟障碍（验证动态避障）；
- RViz "2D Pose Estimate" 发 /initialpose 可瞬间移动机器人；
- 服务 /sim_clear_obstacles 清空虚拟障碍。
"""

import math
import os

import numpy as np
import rclpy
import yaml
from geometry_msgs.msg import PointStamped, PoseWithCovarianceStamped, TransformStamped, Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import LaserScan
from std_srvs.srv import Trigger
from tf2_ros import TransformBroadcaster
from visualization_msgs.msg import Marker, MarkerArray
from fishbot_light_sim.runtime_contract import configure_simulation_environment, readable_map

MAX_VIRTUAL_OBSTACLES = 64


def read_pgm(path):
    """读取 P5/P2 PGM，返回 uint8 灰度图（行 0 为图像顶部）。"""
    with open(path, 'rb') as f:
        magic = f.readline().strip()
        if magic not in (b'P5', b'P2'):
            raise ValueError(f'不支持的 PGM 格式 {magic}: {path}')
        line = f.readline()
        while line.startswith(b'#'):
            line = f.readline()
        width, height = map(int, line.split())
        maxval = int(f.readline())
        if magic == b'P5':
            dtype = np.uint8 if maxval < 256 else np.dtype('>u2')
            data = np.frombuffer(f.read(), dtype=dtype)
        else:
            data = np.array(f.read().split(), dtype=np.int64).astype(
                np.uint8 if maxval < 256 else np.dtype('>u2'))
    return data.reshape(height, width)


def yaw_from_quaternion(x, y, z, w):
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


class LightSimNode(Node):

    def __init__(self):
        super().__init__('fishbot_light_sim')

        # ---- 参数（雷达默认对齐实机 ydlidar 实测）----
        self.declare_parameter('map_yaml', '')
        self.declare_parameter('scan_rate', 7.0)          # 实测 6.9~7.36Hz
        self.declare_parameter('samples', 719)            # 实测点数
        self.declare_parameter('angle_min', -math.pi)     # -180deg
        self.declare_parameter('angle_max', math.pi)      # 180deg
        self.declare_parameter('range_min', 0.05)
        self.declare_parameter('range_max', 64.0)
        self.declare_parameter('invalid_range_is_inf', True)
        self.declare_parameter('map_frame', 'map')
        self.declare_parameter('odom_frame', 'odom')
        self.declare_parameter('base_frame', 'base_footprint')
        self.declare_parameter('laser_frame', 'laser_frame')
        self.declare_parameter('laser_offset_x', 0.0)     # URDF: 激光位于底盘中心正上方
        self.declare_parameter('laser_offset_y', 0.0)
        self.declare_parameter('initial_x', 0.38)
        self.declare_parameter('initial_y', 2.05)
        self.declare_parameter('initial_yaw', 0.0)
        self.declare_parameter('ground_truth_localization', True)
        self.declare_parameter('v_noise_std', 0.0)        # 里程计线速度噪声
        self.declare_parameter('w_noise_std', 0.0)        # 里程计角速度噪声
        self.declare_parameter('max_v', 0.26)             # 对齐 nav2_params 的 max_vel_x
        self.declare_parameter('max_w', 1.0)
        self.declare_parameter('cmd_timeout', 0.5)        # 命令超时刹停（对齐实机安全门思路）
        self.declare_parameter('obstacle_radius', 0.15)   # 虚拟障碍默认半径
        self.declare_parameter('publish_tf_rate', 50.0)
        self.declare_parameter('odom_rate', 30.0)

        p = lambda name: self.get_parameter(name).value
        self.map_yaml = readable_map(p('map_yaml'))

        # ---- 地图加载（对齐 map_server trinary 语义：205=未知，深色=占用）----
        with open(self.map_yaml, 'r', encoding='utf-8') as f:
            meta = yaml.safe_load(f)
        image_path = meta['image']
        if not os.path.isabs(image_path):
            image_path = os.path.join(os.path.dirname(os.path.abspath(self.map_yaml)), image_path)
        img = read_pgm(image_path)
        self.res = float(meta['resolution'])
        self.origin_x = float(meta['origin'][0])
        self.origin_y = float(meta['origin'][1])
        negate = int(meta.get('negate', 0))
        occ_thresh = float(meta.get('occupied_thresh', 0.65))
        free_thresh = float(meta.get('free_thresh', 0.25))

        color = img.astype(np.float64)
        if negate:
            prob = color / 255.0
        else:
            prob = (255.0 - color) / 255.0
        occupied = prob > occ_thresh
        unknown = (img == 205) | ((prob > free_thresh) & ~occupied)
        self.occ_grid = occupied.ravel()          # 射线只在占用格停下
        self.unknown_grid = unknown.ravel()
        self.map_h, self.map_w = img.shape
        self.map_diag = math.hypot(self.map_w, self.map_h) * self.res

        # ---- 雷达 raycast 预计算 ----
        self.scan_rate = float(p('scan_rate'))
        self.n_samples = int(p('samples'))
        self.range_min = float(p('range_min'))
        self.range_max = float(p('range_max'))
        angle_min = float(p('angle_min'))
        angle_max = float(p('angle_max'))
        self.angle_increment = (angle_max - angle_min) / (self.n_samples - 1)
        self.angles = angle_min + self.angle_increment * np.arange(self.n_samples, dtype=np.float32)
        self.ray_unit = np.stack(
            [np.cos(self.angles), np.sin(self.angles)], axis=1).astype(np.float32)  # (N,2)
        self.ray_step = self.res * 0.5            # 半格步长，匹配 0.05m 分辨率
        max_trace = min(self.range_max, self.map_diag)
        self.ray_ts = (np.arange(int(max_trace / self.ray_step)) * self.ray_step
                       + 0.5 * self.ray_step + self.range_min).astype(np.float32)  # (K,)
        self.invalid_inf = bool(p('invalid_range_is_inf'))
        self.ranges_no_hit = np.inf if self.invalid_inf else np.float32(self.range_max)

        # ---- 状态 ----
        self.map_frame = str(p('map_frame'))
        self.odom_frame = str(p('odom_frame'))
        self.base_frame = str(p('base_frame'))
        self.laser_frame = str(p('laser_frame'))
        self.laser_off = (float(p('laser_offset_x')), float(p('laser_offset_y')))
        self.ground_truth = bool(p('ground_truth_localization'))
        self.v_noise = float(p('v_noise_std'))
        self.w_noise = float(p('w_noise_std'))
        self.max_v = float(p('max_v'))
        self.max_w = float(p('max_w'))
        self.cmd_timeout = float(p('cmd_timeout'))
        self.obstacle_radius = float(p('obstacle_radius'))

        # 真实位姿（map 系）与里程计位姿（odom 系）；噪声为 0 时两者一致
        self.true_pose = np.array(
            [p('initial_x'), p('initial_y'), p('initial_yaw')], dtype=np.float64)
        self.odom_pose = self.true_pose.copy()
        self.cmd = (0.0, 0.0)                     # (v, w)
        self.last_cmd_time = None
        self.last_cmd = (0.0, 0.0)
        self.rng = np.random.default_rng()
        self.virtual_obstacles = []               # [(x, y, r)] map 系

        # ---- ROS 接口 ----
        self.tf_broadcaster = TransformBroadcaster(self)
        marker_qos = QoSProfile(depth=10,
                                reliability=ReliabilityPolicy.RELIABLE,
                                durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.marker_pub = self.create_publisher(MarkerArray, 'sim_obstacles', marker_qos)
        self.scan_pub = self.create_publisher(LaserScan, 'scan', 10)
        self.odom_pub = self.create_publisher(Odometry, 'odom', 10)
        self.create_subscription(Twist, 'cmd_vel', self.on_cmd_vel, 10)
        # Jazzy navigation_launch 管线：controller -> cmd_vel_nav -> velocity_smoother
        # -> cmd_vel_smoothed -> collision_monitor -> cmd_vel（与实机底盘接口一致）
        self.create_subscription(PointStamped, 'clicked_point', self.on_clicked_point, 10)
        self.create_subscription(
            PoseWithCovarianceStamped, 'initialpose', self.on_initial_pose, 10)
        self.create_service(Trigger, 'sim_clear_obstacles', self.on_clear_obstacles)

        self.tf_timer = self.create_timer(1.0 / float(p('publish_tf_rate')), self.step)
        odom_period = 1.0 / float(p('odom_rate'))
        self.odom_timer = self.create_timer(odom_period, self.publish_odom)
        self.scan_timer = self.create_timer(1.0 / self.scan_rate, self.publish_scan)

        self.get_logger().info(
            f'地图 {os.path.basename(image_path)} {self.map_w}x{self.map_h}@{self.res} '
            f'origin=({self.origin_x},{self.origin_y}) 占用格={int(self.occ_grid.sum())} '
            f'未知格={int(self.unknown_grid.sum())}')
        self.get_logger().info(
            f'雷达 {self.n_samples} 点 @ {self.scan_rate:.1f}Hz '
            f'FOV [{math.degrees(angle_min):.0f},{math.degrees(angle_max):.0f}]deg '
            f'量程 [{self.range_min},{self.range_max}]m')
        self.get_logger().info(
            f'初始位姿 map 系 ({self.true_pose[0]:.2f},{self.true_pose[1]:.2f},'
            f'{math.degrees(self.true_pose[2]):.0f}deg) '
            f'ground_truth_localization={self.ground_truth}')
        self.publish_markers()

    # ---------------- 订阅 / 服务 ----------------

    def on_cmd_vel(self, msg):
        v = float(np.clip(msg.linear.x, -self.max_v, self.max_v))
        w = float(np.clip(msg.angular.z, -self.max_w, self.max_w))
        self.cmd = (v, w)
        self.last_cmd_time = self.get_clock().now()

    def on_clicked_point(self, msg):
        if msg.header.frame_id not in ('', self.map_frame):
            self.get_logger().warn(f'忽略 {msg.header.frame_id} 系的点，请用 map 系')
            return
        if len(self.virtual_obstacles) >= MAX_VIRTUAL_OBSTACLES:
            self.get_logger().warn(f'虚拟障碍已达上限 {MAX_VIRTUAL_OBSTACLES}')
            return
        self.virtual_obstacles.append((msg.point.x, msg.point.y, self.obstacle_radius))
        self.get_logger().info(
            f'注入虚拟障碍 #{len(self.virtual_obstacles)} '
            f'({msg.point.x:.2f},{msg.point.y:.2f}) r={self.obstacle_radius}')
        self.publish_markers()

    def on_initial_pose(self, msg):
        pos = msg.pose.pose.position
        yaw = yaw_from_quaternion(msg.pose.pose.orientation.x,
                                  msg.pose.pose.orientation.y,
                                  msg.pose.pose.orientation.z,
                                  msg.pose.pose.orientation.w)
        self.true_pose = np.array([pos.x, pos.y, yaw], dtype=np.float64)
        self.odom_pose = self.true_pose.copy()   # 里程计参考点重置
        self.get_logger().info(
            f'瞬移到 ({pos.x:.2f},{pos.y:.2f},{math.degrees(yaw):.0f}deg) 并重置里程计')

    def on_clear_obstacles(self, request, response):
        n = len(self.virtual_obstacles)
        self.virtual_obstacles = []
        self.publish_markers()
        response.success = True
        response.message = f'已清空 {n} 个虚拟障碍'
        return response

    # ---------------- 仿真推进 ----------------

    def step(self):
        now = self.get_clock().now()
        if self.last_cmd_time is None or \
                (now - self.last_cmd_time).nanoseconds * 1e-9 > self.cmd_timeout:
            self.cmd = (0.0, 0.0)   # 命令超时刹停

        v, w = self.cmd
        dt = 0.02
        self.true_pose = self._integrate(self.true_pose, v, w, dt)

        # 里程计位姿：同样的运动学 + 可配置噪声（模拟打滑/编码器误差）。
        # 噪声按速度幅值缩放，静止时无噪声；参数为 0 则里程计完美。
        if self.v_noise > 0.0:
            v_n = v + self.rng.normal(0.0, self.v_noise * max(abs(v), 0.05))
        else:
            v_n = v
        if self.w_noise > 0.0:
            w_n = w + self.rng.normal(0.0, self.w_noise * max(abs(w), 0.2))
        else:
            w_n = w
        self.odom_pose = self._integrate(self.odom_pose, v_n, w_n, dt)
        self.last_cmd = (v_n, w_n)
        self.publish_tf()

    @staticmethod
    def _integrate(pose, v, w, dt):
        x, y, th = pose
        mid = th + 0.5 * w * dt
        return np.array([x + v * dt * math.cos(mid),
                         y + v * dt * math.sin(mid),
                         th + w * dt], dtype=np.float64)

    def _tf_msg(self, parent, child, x, y, yaw, stamp):
        tf = TransformStamped()
        tf.header.stamp = stamp.to_msg()
        tf.header.frame_id = parent
        tf.child_frame_id = child
        tf.transform.translation.x = x
        tf.transform.translation.y = y
        tf.transform.rotation.z = math.sin(yaw / 2.0)
        tf.transform.rotation.w = math.cos(yaw / 2.0)
        return tf

    def publish_tf(self):
        stamp = self.get_clock().now()
        ox, oy, oth = self.odom_pose
        self.tf_broadcaster.sendTransform(
            self._tf_msg(self.odom_frame, self.base_frame, ox, oy, oth, stamp))
        if self.ground_truth:
            # map->odom = T_map_base(真值) * inv(T_odom_base)：
            # 旋转 R(true_yaw - odom_yaw)，平移 t_map - R(dyaw) * t_odom
            dyaw = self._wrap(self.true_pose[2] - oth)
            c, s = math.cos(dyaw), math.sin(dyaw)
            dx = self.true_pose[0] - (c * ox - s * oy)
            dy = self.true_pose[1] - (s * ox + c * oy)
            self.tf_broadcaster.sendTransform(
                self._tf_msg(self.map_frame, self.odom_frame, dx, dy, dyaw, stamp))

    @staticmethod
    def _wrap(a):
        return (a + math.pi) % (2.0 * math.pi) - math.pi

    def publish_odom(self):
        msg = Odometry()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.odom_frame
        msg.child_frame_id = self.base_frame
        x, y, th = self.odom_pose
        msg.pose.pose.position.x = x
        msg.pose.pose.position.y = y
        msg.pose.pose.orientation.z = math.sin(th / 2.0)
        msg.pose.pose.orientation.w = math.cos(th / 2.0)
        v, w = self.last_cmd
        msg.twist.twist.linear.x = v
        msg.twist.twist.angular.z = w
        self.odom_pub.publish(msg)


    # ---------------- 雷达 raycast ----------------

    def publish_scan(self):
        tx, ty, tth = self.true_pose
        # 激光器在 map 系中的位置（URDF 偏移投影）
        lx = tx + self.laser_off[0] * math.cos(tth) - self.laser_off[1] * math.sin(tth)
        ly = ty + self.laser_off[0] * math.sin(tth) + self.laser_off[1] * math.cos(tth)

        ts = self.ray_ts                                   # (K,)
        unit = self.ray_unit                               # (N,2)
        pts_x = np.asarray(lx, dtype=np.float32) + ts[:, None] * unit[None, :, 0]
        pts_y = np.asarray(ly, dtype=np.float32) + ts[:, None] * unit[None, :, 1]

        cols = np.floor((pts_x - self.origin_x) / self.res).astype(np.int32)
        rows = (self.map_h - 1 - np.floor((pts_y - self.origin_y) / self.res)).astype(np.int32)
        inside = (cols >= 0) & (cols < self.map_w) & (rows >= 0) & (rows < self.map_h)
        flat = np.clip(rows, 0, self.map_h - 1) * self.map_w + np.clip(cols, 0, self.map_w - 1)
        hit = inside & self.occ_grid[flat]

        for (ox_, oy_, r_) in self.virtual_obstacles:
            dist2 = (pts_x - ox_) ** 2 + (pts_y - oy_) ** 2
            hit |= dist2 < (r_ * r_)

        has_hit = hit.any(axis=0)
        first = hit.argmax(axis=0)
        ranges = np.where(has_hit, ts[first], self.ranges_no_hit).astype(np.float32)

        msg = LaserScan()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.laser_frame
        msg.angle_min = float(self.angles[0])
        msg.angle_max = float(self.angles[-1])
        msg.angle_increment = float(self.angle_increment)
        msg.time_increment = 0.0
        msg.scan_time = 1.0 / self.scan_rate
        msg.range_min = self.range_min
        msg.range_max = self.range_max
        msg.ranges = ranges.tolist()
        self.scan_pub.publish(msg)

    # ---------------- 障碍可视化 ----------------

    def publish_markers(self):
        msg = MarkerArray()
        for i, (x, y, r) in enumerate(self.virtual_obstacles):
            m = Marker()
            m.header.frame_id = self.map_frame
            m.header.stamp = self.get_clock().now().to_msg()
            m.ns = 'virtual_obstacles'
            m.id = i
            m.type = Marker.CYLINDER
            m.action = Marker.ADD
            m.pose.position.x = x
            m.pose.position.y = y
            m.pose.position.z = 0.1
            m.pose.orientation.w = 1.0
            m.scale.x = 2.0 * r
            m.scale.y = 2.0 * r
            m.scale.z = 0.2
            m.color.r = 0.9
            m.color.g = 0.2
            m.color.b = 0.2
            m.color.a = 0.8
            msg.markers.append(m)
        self.marker_pub.publish(msg)


def main(args=None):
    domain = configure_simulation_environment()
    rclpy.init(args=args, domain_id=domain)
    node = LightSimNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
