#
# Copyright (C) 2025 合肥幻刃科技有限责任公司 (Hefei Huanren Technology Co., Ltd.)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# Project: 鱼香ROS机器人 (Yuxiang ROS Robot)
# Website: fishros.org.cn | fishros.com

from tracemalloc import start
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
import struct
import socket
import math
from functools import reduce
import time
import serial

from enum import Enum

def normalize_scan_grid(scan_msg):
    """Put observed echoes on a fixed half-degree circular grid in place.

    Missing/invalid returns stay infinite. Where input angles share a bin,
    retain the closer measured echo rather than interpolating free space.
    Header and scan timing are left to the existing publishing callback.
    """
    count = 720
    increment = 2 * math.pi / count
    ranges = [float('inf')] * count
    intensities = [0.0] * count
    angle_min = scan_msg.angle_min
    angle_increment = scan_msg.angle_increment
    if (math.isfinite(angle_min) and math.isfinite(angle_increment)
            and angle_increment != 0):
        for index, distance in enumerate(scan_msg.ranges):
            if (not math.isfinite(distance)
                    or not scan_msg.range_min <= distance <= scan_msg.range_max):
                continue
            angle = angle_min + index * angle_increment
            if not math.isfinite(angle):
                continue
            wrapped = (angle + math.pi) % (2 * math.pi)
            grid_index = int(math.floor(wrapped / increment + 0.5)) % count
            if distance < ranges[grid_index]:
                ranges[grid_index] = float(distance)
                intensity = (scan_msg.intensities[index]
                             if index < len(scan_msg.intensities) else 0.0)
                intensities[grid_index] = float(intensity) if math.isfinite(intensity) else 0.0
    scan_msg.angle_min = -math.pi
    scan_msg.angle_increment = increment
    scan_msg.angle_max = -math.pi + (count - 1) * increment
    scan_msg.ranges = ranges
    scan_msg.intensities = intensities
    return scan_msg


class LidarType(Enum):
    LIDAR_TYPE_UNKNOWN = 0
    LIDAR_TYPE_X2 = 1
    LIDAR_TYPE_X2K = 2
    LIDAR_TYPE_X2N = 3
    LIDAR_TYPE_T4B = 4
    LIDAR_TYPE_M1C1 = 5
    LIDAR_TYPE_F2 = 6
    LIDAR_TYPE_MAX = 7


class ScanData:
    def __init__(self, angle, distance, intensity):
        self.angle = angle
        self.distance = distance
        self.intensity = intensity
        self.is_valid = True

class LidarM1C1Parser:
    def __init__(self):
        self.data_buffer = bytearray()
        self.scan_callback = None
        self.scan_data_buffer = []
        self.frame_id = 'laser_frame'
        self.angle_offset = -math.pi
        self.range_min = 0.01
        self.range_max = 16.0
        self.get_time_stamp = None  # 用于获取时间戳的函数
        self.scan_start_time = None  # 扫描开始时间戳

    def check_frame_checksum(self, frame):
        if(len(frame) < 10):
            return False
        check_data = frame[0:8] + frame[10:]
        if len(check_data) % 2 != 0:
            check_data += b'\x00'
                
        checksum = 0
        for i in range(0, len(check_data), 2):
            word = struct.unpack('<H', check_data[i:i+2])[0]
            checksum ^= word
            
        return checksum == struct.unpack('<H', frame[8:10])[0]

    def check_is_header_frame(self, frame):
        if frame[2:4]==b'\x01\x01':
            return True
        else:
            return False

    def put_raw_frame(self, frame):
        if len(frame) < 10:
            return
        expected_len = 10 + frame[3] * 2
        if len(frame) < expected_len:
            return
        if not self.check_frame_checksum(frame):
            return
        if self.check_is_header_frame(frame):
            self.frame_data_to_scan()
            self.scan_data_buffer.clear()
        self.add_frame_data(frame)
    

    def add_frame_data(self, frame):
        # self.data_buffer.extend(frame)
        lsn = frame[3]
        fsa = struct.unpack('<H', frame[4:6])[0]
        lsa = struct.unpack('<H', frame[6:8])[0]
        start_angle = (fsa >> 1) / 64.0
        end_angle = (lsa >> 1) / 64.0
        # print(f"点云数量:{lsn}, 起始角度:{start_angle}, 结束角度:{end_angle}")
        for i in range(1,lsn+1):
            if lsn==1:
                angle = start_angle
            else:
                angle = (end_angle-start_angle)/(lsn-1)*(i-1) + start_angle
            start_index = 8+i*2
            end_index = start_index + 2
            distance_raw =  struct.unpack('<H', frame[start_index:end_index])[0]
            distance = distance_raw/4/1000.0
            if distance ==0:
                angle_correct = 0
            else:
                angle_correct = math.atan(19.16*(distance_raw-90.0)/(90.15*distance_raw))
            angle = angle - angle_correct
            if i==1:
                start_angle = angle
            if i==lsn:
                end_angle = angle
            # print(f"角度{i}:{angle}, 距离:{distance}, 起始索引:{start_index}, 结束索引:{end_index},数据:{frame[start_index:end_index].hex()}")
            # intensity = angle
            self.scan_data_buffer.append(ScanData(angle, distance, 0))
        # print(f"修正后：点云数量:{lsn}, 起始角度:{start_angle}, 结束角度:{end_angle}")

    def frame_data_to_scan(self):
        # print(f"点云数量:{len(self.scan_data_buffer)}")
        if len(self.scan_data_buffer) == 0:
            return
        
        # 创建 LaserScan 消息
        scan_msg = LaserScan()
        scan_msg.header.frame_id = self.frame_id
        if self.get_time_stamp is not None:
            scan_msg.header.stamp = self.get_time_stamp()
        scan_msg.range_min = float(self.range_min)
        scan_msg.range_max = float(self.range_max)
        
        # 按角度排序数据
        sorted_data = sorted(self.scan_data_buffer, key=lambda x: x.angle)
        
        # 提取角度（转换为弧度）
        angles_rad = [math.radians(point.angle) for point in sorted_data]
        
        if len(angles_rad) == 0:
            return
        
        # 计算角度范围
        angle_min = min(angles_rad)
        angle_max = max(angles_rad)
        angle_span = angle_max - angle_min
        
        # 计算期望的角度增量
        # 如果数据点足够多，使用实际数据点的平均间隔
        # 否则使用一个合理的默认值（例如 0.25 度）
        if len(angles_rad) > 1:
            # 计算相邻角度差的平均值
            angle_diffs = []
            for i in range(len(angles_rad) - 1):
                diff = angles_rad[i + 1] - angles_rad[i]
                # 处理角度跨越 0 度的情况（例如从 359 度到 1 度）
                if diff < 0:
                    diff += 2 * math.pi
                if diff > 0:  # 忽略重复的角度
                    angle_diffs.append(diff)
            
            if len(angle_diffs) > 0:
                # 使用中位数作为角度增量，更抗异常值
                angle_diffs.sort()
                median_diff = angle_diffs[len(angle_diffs) // 2]
                # 如果角度跨度很大（接近 2π），使用更小的增量以获得更好的分辨率
                if angle_span > math.pi:
                    angle_increment = min(median_diff, math.radians(0.5))  # 最多 0.5 度
                else:
                    angle_increment = median_diff
            else:
                # 如果无法计算增量（所有角度相同），使用角度跨度除以点数
                if angle_span > 0:
                    angle_increment = angle_span / max(1, len(angles_rad) - 1)
                else:
                    # 所有角度相同，使用默认值
                    angle_increment = math.radians(0.25)  # 默认 0.25 度
        else:
            angle_increment = math.radians(0.25)  # 默认 0.25 度
        
        # 确保 angle_increment 不为 0，防止除零错误
        if angle_increment <= 0:
            angle_increment = math.radians(0.25)  # 默认 0.25 度
        
        # 创建均匀的角度网格
        # 计算需要的点数
        if angle_span > 0:
            num_points = int(angle_span / angle_increment) + 1
            if num_points > 10000:  # 限制最大点数，防止内存问题
                angle_increment = angle_span / 10000
                num_points = 10001
        else:
            # 所有角度相同，只有一个点
            num_points = 1
        
        # 创建索引到数据的映射（使用索引避免浮点数精度问题）
        index_to_data = {}
        for point in sorted_data:
            angle_rad = math.radians(point.angle)
            # 将角度映射到最近的网格点索引
            grid_index = int(round((angle_rad - angle_min) / angle_increment))
            # 确保索引在有效范围内
            grid_index = max(0, min(grid_index, num_points - 1))
            
            # 如果该网格点还没有数据，或者当前数据更接近，则更新
            if grid_index not in index_to_data:
                index_to_data[grid_index] = {
                    'distance': point.distance,
                    'intensity': point.intensity,
                    'angle': angle_rad
                }
            else:
                # 如果已有数据，选择更接近网格点的数据
                grid_angle = angle_min + grid_index * angle_increment
                existing_angle = index_to_data[grid_index]['angle']
                if abs(angle_rad - grid_angle) < abs(existing_angle - grid_angle):
                    index_to_data[grid_index] = {
                        'distance': point.distance,
                        'intensity': point.intensity,
                        'angle': angle_rad
                    }
        
        # 填充 ranges 和 intensities 数组
        ranges = []
        intensities = []
        for i in range(num_points):
            if i in index_to_data:
                data = index_to_data[i]
                distance = data['distance']
                # 检查距离是否在有效范围内
                if self.range_min <= distance <= self.range_max:
                    ranges.append(float(distance))
                else:
                    ranges.append(float('inf'))  # 无效距离
                intensities.append(float(data['intensity']))
            else:
                # 缺失的角度，使用 inf 表示无效数据
                ranges.append(float('inf'))
                intensities.append(0.0)
        
        # 设置角度参数
        scan_msg.angle_min = angle_min+self.angle_offset
        scan_msg.angle_max = angle_min + (num_points - 1) * angle_increment+self.angle_offset
        scan_msg.angle_increment = angle_increment
        scan_msg.time_increment = 0.0
        scan_msg.scan_time = 0.1
        scan_msg.ranges = ranges
        scan_msg.intensities = intensities
        
        # 如果有回调函数，调用它传递 LaserScan 消息
        if self.scan_callback is not None:
            self.scan_callback(scan_msg)
        return

    def add_scan_callback(self, callback):
        self.scan_callback = callback
    
    def set_scan_params(self, frame_id, range_min, range_max, get_time_stamp):
        """设置 LaserScan 消息的参数"""
        self.frame_id = frame_id
        self.range_min = range_min
        self.range_max = range_max
        self.get_time_stamp = get_time_stamp

class LidarX2Parser:
    def __init__(self):
        self.data_buffer = bytearray()
        self.scan_callback = None
        self.scan_data_buffer = []
        self.frame_id = 'laser_frame'
        self.angle_offset = -math.pi
        self.range_min = 0.01
        self.range_max = 16.0
        self.get_time_stamp = None  # 用于获取时间戳的函数

    def check_frame_checksum(self, frame):
        if(len(frame) < 10):
            return False
        check_data = frame[0:8] + frame[10:]
        if len(check_data) % 2 != 0:
            check_data += b'\x00'
                
        checksum = 0
        for i in range(0, len(check_data), 2):
            word = struct.unpack('<H', check_data[i:i+2])[0]
            checksum ^= word
            
        return checksum == struct.unpack('<H', frame[8:10])[0]

    def check_is_header_frame(self, frame):
        if frame[2]&0x01==0x01 and frame[3]==0x01:
            return True
        else:
            return False

    def put_raw_frame(self, frame):
        # print(frame.hex())
        if not self.check_frame_checksum(frame):
            return
        if self.check_is_header_frame(frame):
            self.frame_data_to_scan()
            self.scan_data_buffer.clear()
        self.add_frame_data(frame)
    

    def add_frame_data(self, frame):
        # self.data_buffer.extend(frame)
        lsn = frame[3]
        fsa = struct.unpack('<H', frame[4:6])[0]
        lsa = struct.unpack('<H', frame[6:8])[0]
        start_angle = (fsa >> 1) / 64.0
        end_angle = (lsa >> 1) / 64.0
        # print(f"点云数量:{lsn}, 起始角度:{start_angle}, 结束角度:{end_angle}")
        for i in range(1,lsn+1):
            if lsn==1:
                angle = start_angle
            else:
                angle = (end_angle-start_angle)/(lsn-1)*(i-1) + start_angle
            start_index = 8+i*2
            end_index = start_index + 2
            distance_raw =  struct.unpack('<H', frame[start_index:end_index])[0]
            distance = distance_raw/4/1000.0
            if distance ==0:
                angle_correct = 0
            else:
                angle_correct = math.atan(21.8*(-distance_raw+155.3)/(155.3*distance_raw))
            angle = angle + angle_correct
            if i==1:
                start_angle = angle
            if i==lsn:
                end_angle = angle
            # print(f"角度{i}:{angle}, 距离:{distance}, 起始索引:{start_index}, 结束索引:{end_index},数据:{frame[start_index:end_index].hex()}")
            intensity = 0
            self.scan_data_buffer.append(ScanData(angle, distance, intensity))
        # print(f"修正后：点云数量:{lsn}, 起始角度:{start_angle}, 结束角度:{end_angle}")

    def frame_data_to_scan(self):
        # print(f"点云数量:{len(self.scan_data_buffer)}")
        if len(self.scan_data_buffer) == 0:
            return
        
        # 创建 LaserScan 消息
        scan_msg = LaserScan()
        scan_msg.header.frame_id = self.frame_id
        if self.get_time_stamp is not None:
            scan_msg.header.stamp = self.get_time_stamp()
        scan_msg.range_min = float(self.range_min)
        scan_msg.range_max = float(self.range_max)
        
        # 按角度排序数据
        sorted_data = sorted(self.scan_data_buffer, key=lambda x: x.angle)
        
        # 提取角度（转换为弧度）
        angles_rad = [math.radians(point.angle) for point in sorted_data]
        
        if len(angles_rad) == 0:
            return
        
        # 计算角度范围
        angle_min = min(angles_rad)
        angle_max = max(angles_rad)
        angle_span = angle_max - angle_min
        
        # 计算期望的角度增量
        # 如果数据点足够多，使用实际数据点的平均间隔
        # 否则使用一个合理的默认值（例如 0.25 度）
        if len(angles_rad) > 1:
            # 计算相邻角度差的平均值
            angle_diffs = []
            for i in range(len(angles_rad) - 1):
                diff = angles_rad[i + 1] - angles_rad[i]
                # 处理角度跨越 0 度的情况（例如从 359 度到 1 度）
                if diff < 0:
                    diff += 2 * math.pi
                if diff > 0:  # 忽略重复的角度
                    angle_diffs.append(diff)
            
            if len(angle_diffs) > 0:
                # 使用中位数作为角度增量，更抗异常值
                angle_diffs.sort()
                median_diff = angle_diffs[len(angle_diffs) // 2]
                # 如果角度跨度很大（接近 2π），使用更小的增量以获得更好的分辨率
                if angle_span > math.pi:
                    angle_increment = min(median_diff, math.radians(0.5))  # 最多 0.5 度
                else:
                    angle_increment = median_diff
            else:
                # 如果无法计算增量（所有角度相同），使用角度跨度除以点数
                if angle_span > 0:
                    angle_increment = angle_span / max(1, len(angles_rad) - 1)
                else:
                    # 所有角度相同，使用默认值
                    angle_increment = math.radians(0.25)  # 默认 0.25 度
        else:
            angle_increment = math.radians(0.25)  # 默认 0.25 度
        
        # 确保 angle_increment 不为 0，防止除零错误
        if angle_increment <= 0:
            angle_increment = math.radians(0.25)  # 默认 0.25 度
        
        # 创建均匀的角度网格
        # 计算需要的点数
        if angle_span > 0:
            num_points = int(angle_span / angle_increment) + 1
            if num_points > 10000:  # 限制最大点数，防止内存问题
                angle_increment = angle_span / 10000
                num_points = 10001
        else:
            # 所有角度相同，只有一个点
            num_points = 1
        
        # 创建索引到数据的映射（使用索引避免浮点数精度问题）
        index_to_data = {}
        for point in sorted_data:
            angle_rad = math.radians(point.angle)
            # 将角度映射到最近的网格点索引
            grid_index = int(round((angle_rad - angle_min) / angle_increment))
            # 确保索引在有效范围内
            grid_index = max(0, min(grid_index, num_points - 1))
            
            # 如果该网格点还没有数据，或者当前数据更接近，则更新
            if grid_index not in index_to_data:
                index_to_data[grid_index] = {
                    'distance': point.distance,
                    'intensity': point.intensity,
                    'angle': angle_rad
                }
            else:
                # 如果已有数据，选择更接近网格点的数据
                grid_angle = angle_min + grid_index * angle_increment
                existing_angle = index_to_data[grid_index]['angle']
                if abs(angle_rad - grid_angle) < abs(existing_angle - grid_angle):
                    index_to_data[grid_index] = {
                        'distance': point.distance,
                        'intensity': point.intensity,
                        'angle': angle_rad
                    }
        
        # 填充 ranges 和 intensities 数组
        ranges = []
        intensities = []
        for i in range(num_points):
            if i in index_to_data:
                data = index_to_data[i]
                distance = data['distance']
                # 检查距离是否在有效范围内
                if self.range_min <= distance <= self.range_max:
                    ranges.append(float(distance))
                else:
                    ranges.append(float('inf'))  # 无效距离
                intensities.append(float(data['intensity']))
            else:
                # 缺失的角度，使用 inf 表示无效数据
                ranges.append(float('inf'))
                intensities.append(0.0)
        
        # 设置角度参数
        scan_msg.angle_min = angle_min+self.angle_offset
        scan_msg.angle_max = angle_min + (num_points - 1) * angle_increment+self.angle_offset
        scan_msg.angle_increment = angle_increment
        scan_msg.time_increment = 0.0
        scan_msg.scan_time = 0.1
        scan_msg.ranges = ranges
        scan_msg.intensities = intensities
        
        # 如果有回调函数，调用它传递 LaserScan 消息
        if self.scan_callback is not None:
            self.scan_callback(scan_msg)
        return

    def add_scan_callback(self, callback):
        self.scan_callback = callback
    
    def set_scan_params(self, frame_id, range_min, range_max, get_time_stamp):
        """设置 LaserScan 消息的参数"""
        self.frame_id = frame_id
        self.range_min = range_min
        self.range_max = range_max
        self.get_time_stamp = get_time_stamp




class LidarX2NParser:
    def __init__(self):
        self.data_buffer = bytearray()
        self.scan_callback = None
        self.scan_data_buffer = []
        self.frame_id = 'laser_frame'
        self.angle_offset = -math.pi
        self.range_min = 0.01
        self.range_max = 16.0
        self.get_time_stamp = None  # 用于获取时间戳的函数

    def check_frame_checksum(self, frame):
        if(len(frame) < 10):
            return False
        check_data = frame[0:8] + frame[10:]
        if len(check_data) % 2 != 0:
            check_data += b'\x00'
                
        checksum = 0
        for i in range(0, len(check_data), 2):
            word = struct.unpack('<H', check_data[i:i+2])[0]
            checksum ^= word
            
        return checksum == struct.unpack('<H', frame[8:10])[0]

    def check_is_header_frame(self, frame):
        if frame[2]&0x01==0x01 and frame[3]==0x01:
            return True
        else:
            return False

    def put_raw_frame(self, frame):
        if not self.check_frame_checksum(frame):
            return
        if self.check_is_header_frame(frame):
            self.frame_data_to_scan()
            self.scan_data_buffer.clear()
        self.add_frame_data(frame)
    

    def add_frame_data(self, frame):
        # self.data_buffer.extend(frame)
        # print(f"frame:{frame.hex()}")
        lsn = frame[3]
        if frame[2]&0x01==0x00:
            # print("这是普通点云包")
            pass
        elif frame[2]&0x01==0x01 and frame[3]==0x01:
            # print("这是头包")
            pass
        else:
            # print(f'这是其他包，扔掉')
            return
           
        # 解析起始角度和结束角度（单位：1/64度，带校验位）
        fsa = struct.unpack('<H', frame[4:6])[0]
        lsa = struct.unpack('<H', frame[6:8])[0]
        
        # 右移1位去除校验位，得到实际角度值（单位：1/64度）
        FirstSampleAngle = fsa >> 1
        LastSampleAngle = lsa >> 1
        
        # 计算角度间隔 IntervalSampleAngle（单位：1/64度）
        # 根据文档：IntervalSampleAngle = (LastSampleAngle - FirstSampleAngle) / (点数 - 1)
        if lsn == 1:
            IntervalSampleAngle = 0.0
        else:
            if LastSampleAngle < FirstSampleAngle:
                # 跨0度情况（如从350度到10度）
                if (FirstSampleAngle > 270 * 64) and (LastSampleAngle < 90 * 64):
                    # 真的跨0度
                    IntervalSampleAngle = float((360 * 64 + LastSampleAngle - FirstSampleAngle) / (lsn - 1))
                else:
                    # 使用上一包的间隔值（这里简化处理，使用当前计算值）
                    IntervalSampleAngle = float((LastSampleAngle - FirstSampleAngle) / (lsn - 1))
            else:
                # 正常情况
                IntervalSampleAngle = float((LastSampleAngle - FirstSampleAngle) / (lsn - 1))
        
        # print(f"点云数量:{lsn}, 起始角度:{FirstSampleAngle}(1/64度), 结束角度:{LastSampleAngle}(1/64度), 角度间隔:{IntervalSampleAngle}")
        
        # 遍历每个采样点（nodeIndex 从 0 开始）
        for nodeIndex in range(lsn):
            # 计算采样角度（单位：1/64度）
            sampleAngle = IntervalSampleAngle * nodeIndex
            
            # 读取距离原始值（2字节，小端序）
            start_index = 10 + nodeIndex * 2
            end_index = start_index + 2
            if end_index > len(frame):
                return
            distance_raw = struct.unpack('<H', frame[start_index:end_index])[0]
            
            # 提取质量信息（低2位）
            # 根据文档：qual = ((0xfc | (distance_raw & 0x0003)) << 2)
            qual = ((0xfc | (distance_raw & 0x0003)) << 2)
            
            # 距离单位转换：原始值除以 4000 转换为米
            # 根据文档：实际距离(米) = 原始距离值 / 4000
            distance = distance_raw / 4000.0
            
            # 计算角度修正（三角测距几何修正）
            # 根据文档公式：correctAngle = atan(((21.8 * (155.3 - dist_mm)) / 155.3) / dist_mm) * 180.0 / π * 64
            # 其中 dist_mm = dist_raw / 4.0
            if distance_raw == 0:
                correctAngle = 0
            else:
                dist_mm = distance_raw / 4.0  # 转换为毫米
                # 计算角度修正（单位：1/64度）
                # 公式：atan((21.8 * (155.3 - dist_mm)) / (155.3 * dist_mm)) * 180.0 / π * 64
                # 等价于：atan(((21.8 * (155.3 - dist_mm)) / 155.3) / dist_mm) * 180.0 / π * 64
                if dist_mm > 0:
                    offset = (21.8 * (155.3 - dist_mm)) / 155.3
                    angle_correction_rad = math.atan(offset / dist_mm)
                    correctAngle = int(angle_correction_rad * (180.0 / math.pi) * 64)
                else:
                    correctAngle = 0
            
            # 计算总角度（单位：1/64度）
            # 根据文档：totalAngle = FirstSampleAngle + sampleAngle + correctAngle
            totalAngle = FirstSampleAngle + sampleAngle + correctAngle
            
            # 处理角度边界（范围：0 ~ 23040，对应 0° ~ 360°）
            if totalAngle < 0:
                totalAngle += 23040  # 23040 = 360 * 64
            elif totalAngle > 23040:
                totalAngle -= 23040
            
            # 转换为度：角度(度) = totalAngle / 64.0
            angle = totalAngle / 64.0
            
            # print(f"点{nodeIndex+1}: 角度={angle:.2f}°, 距离={distance:.3f}m, 原始距离={distance_raw}, 质量={qual}, 总角度={totalAngle}(1/64度)")
            
            intensity = qual
            self.scan_data_buffer.append(ScanData(angle, distance, intensity))
        
        # print(f"修正后：点云数量:{lsn}, 起始角度:{FirstSampleAngle/64.0}°, 结束角度:{LastSampleAngle/64.0}°")

    def frame_data_to_scan(self):
        # print(f"点云数量:{len(self.scan_data_buffer)}")
        # for idx, data in enumerate(self.scan_data_buffer):
        #     print(f"索引{idx}: 角度:{data.angle}, 距离:{data.distance}, 强度:{data.intensity}")
            
        if len(self.scan_data_buffer) == 0:
            return
        
        # 创建 LaserScan 消息
        scan_msg = LaserScan()
        scan_msg.header.frame_id = self.frame_id
        if self.get_time_stamp is not None:
            scan_msg.header.stamp = self.get_time_stamp()
        scan_msg.range_min = float(self.range_min)
        scan_msg.range_max = float(self.range_max)
        
        # 按角度排序数据
        sorted_data = sorted(self.scan_data_buffer, key=lambda x: x.angle)
        
        # 提取角度（转换为弧度）
        angles_rad = [math.radians(point.angle) for point in sorted_data]
        
        if len(angles_rad) == 0:
            return
        
        # 计算角度范围
        angle_min = min(angles_rad)
        angle_max = max(angles_rad)
        angle_span = angle_max - angle_min
        
        # 计算期望的角度增量
        # 如果数据点足够多，使用实际数据点的平均间隔
        # 否则使用一个合理的默认值（例如 0.25 度）
        if len(angles_rad) > 1:
            # 计算相邻角度差的平均值
            angle_diffs = []
            for i in range(len(angles_rad) - 1):
                diff = angles_rad[i + 1] - angles_rad[i]
                # 处理角度跨越 0 度的情况（例如从 359 度到 1 度）
                if diff < 0:
                    diff += 2 * math.pi
                if diff > 0:  # 忽略重复的角度
                    angle_diffs.append(diff)
            
            if len(angle_diffs) > 0:
                # 使用中位数作为角度增量，更抗异常值
                angle_diffs.sort()
                median_diff = angle_diffs[len(angle_diffs) // 2]
                # 如果角度跨度很大（接近 2π），使用更小的增量以获得更好的分辨率
                if angle_span > math.pi:
                    angle_increment = min(median_diff, math.radians(0.5))  # 最多 0.5 度
                else:
                    angle_increment = median_diff
            else:
                # 如果无法计算增量（所有角度相同），使用角度跨度除以点数
                if angle_span > 0:
                    angle_increment = angle_span / max(1, len(angles_rad) - 1)
                else:
                    # 所有角度相同，使用默认值
                    angle_increment = math.radians(0.25)  # 默认 0.25 度
        else:
            angle_increment = math.radians(0.25)  # 默认 0.25 度
        
        # 确保 angle_increment 不为 0，防止除零错误
        if angle_increment <= 0:
            angle_increment = math.radians(0.25)  # 默认 0.25 度
        
        # 创建均匀的角度网格
        # 计算需要的点数
        if angle_span > 0:
            num_points = int(angle_span / angle_increment) + 1
            if num_points > 10000:  # 限制最大点数，防止内存问题
                angle_increment = angle_span / 10000
                num_points = 10001
        else:
            # 所有角度相同，只有一个点
            num_points = 1
        
        # 创建索引到数据的映射（使用索引避免浮点数精度问题）
        index_to_data = {}
        for point in sorted_data:
            # print(f"角度:{point.angle}, 距离:{point.distance}, 强度:{point.intensity}")
            angle_rad = math.radians(point.angle)
            # 将角度映射到最近的网格点索引
            grid_index = int(round((angle_rad - angle_min) / angle_increment))
            # 确保索引在有效范围内
            grid_index = max(0, min(grid_index, num_points - 1))
            
            # 如果该网格点还没有数据，或者当前数据更接近，则更新
            if grid_index not in index_to_data:
                index_to_data[grid_index] = {
                    'distance': point.distance,
                    'intensity': point.intensity,
                    'angle': angle_rad
                }
            else:
                # 如果已有数据，选择更接近网格点的数据
                grid_angle = angle_min + grid_index * angle_increment
                existing_angle = index_to_data[grid_index]['angle']
                if abs(angle_rad - grid_angle) < abs(existing_angle - grid_angle):
                    index_to_data[grid_index] = {
                        'distance': point.distance,
                        'intensity': point.intensity,
                        'angle': angle_rad
                    }
        
        # 填充 ranges 和 intensities 数组
        ranges = []
        intensities = []
        for i in range(num_points):
            if i in index_to_data:
                data = index_to_data[i]
                distance = data['distance']
                # 检查距离是否在有效范围内
                if self.range_min <= distance <= self.range_max:
                    ranges.append(float(distance))
                else:
                    ranges.append(float('inf'))  # 无效距离
                intensities.append(float(data['intensity']))
            else:
                # 缺失的角度，使用 inf 表示无效数据
                ranges.append(float('inf'))
                intensities.append(0.0)
        
        # 设置角度参数
        scan_msg.angle_min = angle_min + self.angle_offset
        scan_msg.angle_max = angle_min + (num_points - 1) * angle_increment + self.angle_offset
        scan_msg.angle_increment = angle_increment
        scan_msg.time_increment = 0.0
        scan_msg.scan_time = 0.1
        scan_msg.ranges = ranges
        scan_msg.intensities = intensities
        
        # 如果有回调函数，调用它传递 LaserScan 消息
        if self.scan_callback is not None:
            self.scan_callback(scan_msg)
        return

    def add_scan_callback(self, callback):
        self.scan_callback = callback
    
    def set_scan_params(self, frame_id, range_min, range_max, get_time_stamp):
        """设置 LaserScan 消息的参数"""
        self.frame_id = frame_id
        self.range_min = range_min
        self.range_max = range_max
        self.get_time_stamp = get_time_stamp




class LidarX2KParser:
    def __init__(self):
        self.data_buffer = bytearray()
        self.scan_callback = None
        self.scan_data_buffer = []
        self.frame_id = 'laser_frame'
        self.angle_offset = -math.pi
        self.range_min = 0.01
        self.range_max = 16.0
        self.get_time_stamp = None  # 用于获取时间戳的函数

    def check_frame_checksum(self, frame):
        if(len(frame) < 10):
            return False
        check_data = frame[0:8] + frame[10:]
        if len(check_data) % 2 != 0:
            check_data += b'\x00'
                
        checksum = 0
        for i in range(0, len(check_data), 2):
            word = struct.unpack('<H', check_data[i:i+2])[0]
            checksum ^= word
            
        return checksum == struct.unpack('<H', frame[8:10])[0]

    def check_is_header_frame(self, frame):
        if frame[2]&0x01==0x01 and frame[3]==0x01:
            return True
        else:
            return False

    def put_raw_frame(self, frame):
        if not self.check_frame_checksum(frame):
            return
        if self.check_is_header_frame(frame):
            self.frame_data_to_scan()
            self.scan_data_buffer.clear()
        self.add_frame_data(frame)
    

    def add_frame_data(self, frame):
        # self.data_buffer.extend(frame)
        # print(f"frame:{frame.hex()}")
        lsn = frame[3]
        if frame[2]&0x01==0x00:
            # print("这是普通点云包")
            pass
        elif frame[2]&0x01==0x01 and frame[3]==0x01:
            # print("这是头包")
            pass
        else:
            # print(f'这是其他包，扔掉')
            return
           
        # 解析起始角度和结束角度（单位：1/64度，带校验位）
        fsa = struct.unpack('<H', frame[4:6])[0]
        lsa = struct.unpack('<H', frame[6:8])[0]
        
        # 右移1位去除校验位，得到实际角度值（单位：1/64度）
        FirstSampleAngle = fsa >> 1
        LastSampleAngle = lsa >> 1
        
        # 计算角度间隔 IntervalSampleAngle（单位：1/64度）
        # 根据文档：IntervalSampleAngle = (LastSampleAngle - FirstSampleAngle) / (点数 - 1)
        if lsn == 1:
            IntervalSampleAngle = 0.0
        else:
            if LastSampleAngle < FirstSampleAngle:
                # 跨0度情况（如从350度到10度）
                if (FirstSampleAngle > 270 * 64) and (LastSampleAngle < 90 * 64):
                    # 真的跨0度
                    IntervalSampleAngle = float((360 * 64 + LastSampleAngle - FirstSampleAngle) / (lsn - 1))
                else:
                    # 使用上一包的间隔值（这里简化处理，使用当前计算值）
                    IntervalSampleAngle = float((LastSampleAngle - FirstSampleAngle) / (lsn - 1))
            else:
                # 正常情况
                IntervalSampleAngle = float((LastSampleAngle - FirstSampleAngle) / (lsn - 1))
        
        # print(f"点云数量:{lsn}, 起始角度:{FirstSampleAngle}(1/64度), 结束角度:{LastSampleAngle}(1/64度), 角度间隔:{IntervalSampleAngle}")
        
        # 遍历每个采样点（nodeIndex 从 0 开始）
        for nodeIndex in range(lsn):
            # 计算采样角度（单位：1/64度）
            sampleAngle = IntervalSampleAngle * nodeIndex
            
            # 读取距离原始值（2字节，小端序）
            start_index = 10 + nodeIndex * 2
            end_index = start_index + 2
            distance_raw = struct.unpack('<H', frame[start_index:end_index])[0]
            
            # 提取质量信息（低2位）
            # 根据文档：qual = ((0xfc | (distance_raw & 0x0003)) << 2)
            qual = 0
            
            # 距离单位转换：原始值除以 4000 转换为米
            # 根据文档：实际距离(米) = 原始距离值 / 4000
            distance = distance_raw / 4000.0
            
            # 计算角度修正（三角测距几何修正）
            # 根据文档公式：correctAngle = atan(((21.8 * (155.3 - dist_mm)) / 155.3) / dist_mm) * 180.0 / π * 64
            # 其中 dist_mm = dist_raw / 4.0
            if distance_raw == 0:
                correctAngle = 0
            else:
                dist_mm = distance_raw / 4.0  # 转换为毫米
                # 计算角度修正（单位：1/64度）
                # 公式：atan((21.8 * (155.3 - dist_mm)) / (155.3 * dist_mm)) * 180.0 / π * 64
                # 等价于：atan(((21.8 * (155.3 - dist_mm)) / 155.3) / dist_mm) * 180.0 / π * 64
                if dist_mm > 0:
                    offset = (21.8 * (155.3 - dist_mm)) / 155.3
                    angle_correction_rad = math.atan(offset / dist_mm)
                    correctAngle = int(angle_correction_rad * (180.0 / math.pi) * 64)
                else:
                    correctAngle = 0
            
            # 计算总角度（单位：1/64度）
            # 根据文档：totalAngle = FirstSampleAngle + sampleAngle + correctAngle
            totalAngle = FirstSampleAngle + sampleAngle + correctAngle
            
            # 处理角度边界（范围：0 ~ 23040，对应 0° ~ 360°）
            if totalAngle < 0:
                totalAngle += 23040  # 23040 = 360 * 64
            elif totalAngle > 23040:
                totalAngle -= 23040
            
            # 转换为度：角度(度) = totalAngle / 64.0
            angle = totalAngle / 64.0
            
            # print(f"点{nodeIndex+1}: 角度={angle:.2f}°, 距离={distance:.3f}m, 原始距离={distance_raw}, 质量={qual}, 总角度={totalAngle}(1/64度)")
            
            intensity = qual
            self.scan_data_buffer.append(ScanData(angle, distance, intensity))
        
        # print(f"修正后：点云数量:{lsn}, 起始角度:{FirstSampleAngle/64.0}°, 结束角度:{LastSampleAngle/64.0}°")

    def frame_data_to_scan(self):
        # print(f"点云数量:{len(self.scan_data_buffer)}")
        # for idx, data in enumerate(self.scan_data_buffer):
        #     print(f"索引{idx}: 角度:{data.angle}, 距离:{data.distance}, 强度:{data.intensity}")
            
        if len(self.scan_data_buffer) == 0:
            return
        
        # 创建 LaserScan 消息
        scan_msg = LaserScan()
        scan_msg.header.frame_id = self.frame_id
        if self.get_time_stamp is not None:
            scan_msg.header.stamp = self.get_time_stamp()
        scan_msg.range_min = float(self.range_min)
        scan_msg.range_max = float(self.range_max)
        
        # 按角度排序数据
        sorted_data = sorted(self.scan_data_buffer, key=lambda x: x.angle)
        
        # 提取角度（转换为弧度）
        angles_rad = [math.radians(point.angle) for point in sorted_data]
        
        if len(angles_rad) == 0:
            return
        
        # 计算角度范围
        angle_min = min(angles_rad)
        angle_max = max(angles_rad)
        angle_span = angle_max - angle_min
        
        # 计算期望的角度增量
        # 如果数据点足够多，使用实际数据点的平均间隔
        # 否则使用一个合理的默认值（例如 0.25 度）
        if len(angles_rad) > 1:
            # 计算相邻角度差的平均值
            angle_diffs = []
            for i in range(len(angles_rad) - 1):
                diff = angles_rad[i + 1] - angles_rad[i]
                # 处理角度跨越 0 度的情况（例如从 359 度到 1 度）
                if diff < 0:
                    diff += 2 * math.pi
                if diff > 0:  # 忽略重复的角度
                    angle_diffs.append(diff)
            
            if len(angle_diffs) > 0:
                # 使用中位数作为角度增量，更抗异常值
                angle_diffs.sort()
                median_diff = angle_diffs[len(angle_diffs) // 2]
                # 如果角度跨度很大（接近 2π），使用更小的增量以获得更好的分辨率
                if angle_span > math.pi:
                    angle_increment = min(median_diff, math.radians(0.5))  # 最多 0.5 度
                else:
                    angle_increment = median_diff
            else:
                # 如果无法计算增量（所有角度相同），使用角度跨度除以点数
                if angle_span > 0:
                    angle_increment = angle_span / max(1, len(angles_rad) - 1)
                else:
                    # 所有角度相同，使用默认值
                    angle_increment = math.radians(0.25)  # 默认 0.25 度
        else:
            angle_increment = math.radians(0.25)  # 默认 0.25 度
        
        # 确保 angle_increment 不为 0，防止除零错误
        if angle_increment <= 0:
            angle_increment = math.radians(0.25)  # 默认 0.25 度
        
        # 创建均匀的角度网格
        # 计算需要的点数
        if angle_span > 0:
            num_points = int(angle_span / angle_increment) + 1
            if num_points > 10000:  # 限制最大点数，防止内存问题
                angle_increment = angle_span / 10000
                num_points = 10001
        else:
            # 所有角度相同，只有一个点
            num_points = 1
        
        # 创建索引到数据的映射（使用索引避免浮点数精度问题）
        index_to_data = {}
        for point in sorted_data:
            # print(f"角度:{point.angle}, 距离:{point.distance}, 强度:{point.intensity}")
            angle_rad = math.radians(point.angle)
            # 将角度映射到最近的网格点索引
            grid_index = int(round((angle_rad - angle_min) / angle_increment))
            # 确保索引在有效范围内
            grid_index = max(0, min(grid_index, num_points - 1))
            
            # 如果该网格点还没有数据，或者当前数据更接近，则更新
            if grid_index not in index_to_data:
                index_to_data[grid_index] = {
                    'distance': point.distance,
                    'intensity': point.intensity,
                    'angle': angle_rad
                }
            else:
                # 如果已有数据，选择更接近网格点的数据
                grid_angle = angle_min + grid_index * angle_increment
                existing_angle = index_to_data[grid_index]['angle']
                if abs(angle_rad - grid_angle) < abs(existing_angle - grid_angle):
                    index_to_data[grid_index] = {
                        'distance': point.distance,
                        'intensity': point.intensity,
                        'angle': angle_rad
                    }
        
        # 填充 ranges 和 intensities 数组
        ranges = []
        intensities = []
        for i in range(num_points):
            if i in index_to_data:
                data = index_to_data[i]
                distance = data['distance']
                # 检查距离是否在有效范围内
                if self.range_min <= distance <= self.range_max:
                    ranges.append(float(distance))
                else:
                    ranges.append(float('inf'))  # 无效距离
                intensities.append(float(data['intensity']))
            else:
                # 缺失的角度，使用 inf 表示无效数据
                ranges.append(float('inf'))
                intensities.append(0.0)
        
        # 设置角度参数
        scan_msg.angle_min = angle_min + self.angle_offset
        scan_msg.angle_max = angle_min + (num_points - 1) * angle_increment + self.angle_offset
        scan_msg.angle_increment = angle_increment
        scan_msg.time_increment = 0.0
        scan_msg.scan_time = 0.1
        scan_msg.ranges = ranges
        scan_msg.intensities = intensities
        
        # 如果有回调函数，调用它传递 LaserScan 消息
        if self.scan_callback is not None:
            self.scan_callback(scan_msg)
        return

    def add_scan_callback(self, callback):
        self.scan_callback = callback
    
    def set_scan_params(self, frame_id, range_min, range_max, get_time_stamp):
        """设置 LaserScan 消息的参数"""
        self.frame_id = frame_id
        self.range_min = range_min
        self.range_max = range_max
        self.get_time_stamp = get_time_stamp

class FishBotLaserDriverNode(Node):
    def __init__(self):
        super().__init__('fishbot_laser_driver_node')
        self.declare_parameter('host', '0.0.0.0')  # Listen on all interfaces
        self.declare_parameter('socket_port', 8889)
        self.declare_parameter('port', '/dev/ttyUSB0')
        self.declare_parameter('protocol', 'net') # serial: 串口模式, net: 网络模式
        self.declare_parameter('baudrate', 115200)
        self.declare_parameter('frame_id', 'laser_frame')
        self.declare_parameter('angle_min', -180.0)
        self.declare_parameter('max_range', 8.0)
        self.declare_parameter('min_range', 0.01)
        # 注意：参数服务器只支持声明数值等基本类型，不能用枚举类型作为默认值
        self.declare_parameter('laser_type', int(LidarType.LIDAR_TYPE_X2.value))  # 默认X2雷达，对应数值1
        self.data_buffer = bytearray()
        self.max_buffer_size = 4096  # 最大缓冲区大小，防止无限增长
        self.protocol_mode = None  # None: 未确定, 'tcp': TCP模式, 'udp': UDP模式
        self.connection_timer = None
        self.driver_type = self.get_parameter('protocol').value
        if self.driver_type == 'serial':
            self._init_serial()
        elif self.driver_type == 'net':
            self._init_udp()
            self._init_tcp()
        self.publisher = self.create_publisher(LaserScan, '/scan', 10)
        self.scan_msg = LaserScan()
        self.scan_msg.header.frame_id = self.get_parameter('frame_id').value
        self.scan_msg.range_min = self.get_parameter('min_range').value
        self.scan_msg.range_max = self.get_parameter('max_range').value
        self.current_angle = 0.0
        self.offset_angle = 0.0
        self.rate = 0.0
        self.scan_count = 0
        self.last_report_time = self.get_clock().now()
        self.last_report_count = 0

        self.lidar_type = 0
        self.full_scan_buffer = []
        self.current_angle = 0.0
        self.is_new_scan = True

        self.count = 0

        self.create_timer(0.001, self.process_data)
        self.laser_type = LidarType.LIDAR_TYPE_UNKNOWN
        self.last_connection_time = time.time()
        self.is_receive_laser_type = False
        self.last_rx_monotonic = time.monotonic()
        self.tcp_rx_timeout = 2.0

        self._reset_parsers()

        # One periodic connection check: creating timers inside its callback
        # starves the data reader after a long wait for the hardware.
        if self.driver_type == 'net':
            self.connection_timer = self.create_timer(0.1, self._accept_connection)

    def _reset_parsers(self):
        self.laser_x2_parser = LidarX2Parser()
        self.laser_m1c1_parser = LidarM1C1Parser()
        self.laser_x2n_parser = LidarX2NParser()
        self.laser_x2k_parser = LidarX2KParser()
        
        # 设置 M1C1 解析器的参数和回调函数
        frame_id = self.get_parameter('frame_id').value
        range_min = self.get_parameter('min_range').value
        range_max = self.get_parameter('max_range').value
        self.laser_m1c1_parser.set_scan_params(
            frame_id, 
            range_min, 
            range_max,
            lambda: self.get_clock().now().to_msg()
        )
        self.laser_m1c1_parser.add_scan_callback(self._handle_m1c1_scan)
        self.laser_x2_parser.add_scan_callback(self._handle_m1c1_scan)
        self.laser_x2n_parser.add_scan_callback(self._handle_m1c1_scan)
        self.laser_x2k_parser.add_scan_callback(self._handle_m1c1_scan)

    def _init_udp(self):
        host = self.get_parameter('host').value
        port = self.get_parameter('socket_port').value
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_sock.bind((host, port))
        self.udp_sock.setblocking(False)
        self.get_logger().info(f"等待激光雷达UDP数据: {host}:{port}")

    def _init_tcp(self):
        host = self.get_parameter('host').value
        port = self.get_parameter('socket_port').value
        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR)  # Allow reuse of the address
        self.tcp_sock.bind((host, port))
        self.tcp_sock.listen(1)
        self.tcp_sock.setblocking(False)
        self.conn = None
        self.get_logger().info(f"等待激光雷达TCP连接: {host}:{port}")


    def _init_serial(self):
        try:
            self.ser = serial.Serial(
                port=self.get_parameter('port').value,
                baudrate=self.get_parameter('baudrate').value,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1
            )
            self.get_logger().info(f"成功打开串口设备: {self.ser.name}")
            self.protocol_mode = 'serial'
            # 发送 t4b_fire_command 到串口
            t4b_fire_command = bytes([0xAA, 0x55, 0xF0, 0x0F])
            self.ser.write(t4b_fire_command)
            self.last_connection_time = time.time()
        except Exception as e:
            self.get_logger().error(f"串口初始化失败: {str(e)}")
            raise

    def _accept_connection(self):
        # 如果已经确定了协议模式，不再检查
        if self.protocol_mode is not None:
            if self.connection_timer is not None:
                self.connection_timer.cancel()
            return
        
        # 检查是否有 TCP 连接
        try:
            if self.conn is None:
                self.conn, addr = self.tcp_sock.accept()
                self.conn.setblocking(False)
                self.protocol_mode = 'tcp'
                self.connection_timer.cancel()
                self.get_logger().info(f"检测到TCP连接，使用TCP协议: {addr}")
                self.last_connection_time = time.time()
                self.last_rx_monotonic = time.monotonic()
                self.is_receive_laser_type = False
                # 关闭 UDP socket，不再使用
                try:
                    self.udp_sock.close()
                except:
                    pass
                return
        except BlockingIOError:
            pass
        
        # 检查是否有 UDP 数据
        try:
            data, addr = self.udp_sock.recvfrom(4096)
            if data:
                self.protocol_mode = 'udp'
                self.connection_timer.cancel()
                self.get_logger().info(f"检测到UDP数据，使用UDP协议: {addr}")
                self.last_connection_time = time.time()
                self.is_receive_laser_type = False
                # 将数据添加到缓冲区
                self.data_buffer += data
                # 关闭 TCP socket，不再使用
                try:
                    self.tcp_sock.close()
                except:
                    pass
                return
        except BlockingIOError:
            pass
        
        # The existing timer will retry; never allocate another timer here.

    def _reset_tcp_connection(self, reason):
        self.get_logger().warning(f"TCP radar disconnected ({reason}); waiting for reconnection")
        if self.conn is not None:
            self.conn.close()
        self.conn = None
        self.protocol_mode = None
        self.data_buffer.clear()
        self.full_scan_buffer.clear()
        self.laser_type = LidarType.LIDAR_TYPE_UNKNOWN
        self.is_receive_laser_type = False
        self.rate = 0.0
        self.scan_count = 0
        self.last_report_count = 0
        self.last_report_time = self.get_clock().now()
        self._reset_parsers()
        # Keep the TCP listener: a replacement connection may already be queued.
        if self.udp_sock.fileno() < 0:
            self._init_udp()
        self.connection_timer.reset()

    def process_data(self):
        # print(f"[INFO] 协议模式: {self.protocol_mode}")
        if self.protocol_mode is None:
            return
        
        # 串口模式
        if self.protocol_mode == 'serial':
            # print(f"[INFO] 串口模式")
            if not self.ser:
                return
            try:
                data = self.ser.read(256)
                # print(f"[INFO] 收到串口数据: {data}")
                if data:
                    self.data_buffer += data
            except BlockingIOError:
                pass
        else: 
            # TCP 模式
            if self.protocol_mode == 'tcp':
                if not self.conn:
                    return
                try:
                    data = self.conn.recv(256)
                    if data:
                        self.last_rx_monotonic = time.monotonic()
                        self.data_buffer += data
                    else:
                        self._reset_tcp_connection('EOF')
                        return
                except BlockingIOError:
                    if time.monotonic() - self.last_rx_monotonic >= self.tcp_rx_timeout:
                        self._reset_tcp_connection('receive timeout')
                        return
                except OSError as exc:
                    self._reset_tcp_connection(str(exc))
                    return
            
            # UDP 模式
            elif self.protocol_mode == 'udp':
                try:
                    # 循环接收 UDP 数据，直到没有数据可接收
                    while True:
                        data, addr = self.udp_sock.recvfrom(4096)
                        if data:
                            self.data_buffer += data
                except BlockingIOError:
                    pass   

        while True:
            header_pos = self.data_buffer.find(b'\xAA\x55')
            if header_pos == -1:
                # 没有包头，可能是数据还没接收完整，保留数据等待更多数据
                # 但如果缓冲区过大，可能是异常情况，丢弃部分数据
                if len(self.data_buffer) > self.max_buffer_size:
                    self.data_buffer = bytearray()
                break
            if header_pos > 0:
                # 丢弃包头前的数据
                self.data_buffer = self.data_buffer[header_pos:]
            # 再查找下一个包头
            next_header_pos = self.data_buffer.find(b'\xAA\x55', 2)
            if next_header_pos == -1:
                # 没有找到下一个包头，等待更多数据
                break
            frame = self.data_buffer[:next_header_pos]
            # 分帧出来的frame处理
            self.parse_frame(frame)
            # 移除已处理的数据
            self.data_buffer = self.data_buffer[next_header_pos:]


    def parse_frame(self,frame):
        if len(frame) < 4:
            return
        # 连接成功后5s内应该收到雷达类型信息
        if time.time() - self.last_connection_time < 5 and not self.is_receive_laser_type:
            print(f"\r[INFO] 正在探测雷达型号，耗时:{time.time() - self.last_connection_time:.2f}s", end="", flush=True)
            if frame[2] == 0x99:
                self.laser_type = LidarType(frame[3])
                print(f"\n[INFO] 雷达型号: {self.laser_type}")
                self.is_receive_laser_type = True
        elif time.time() - self.last_connection_time > 5 and not self.is_receive_laser_type:
            print(f"\r[INFO] 正在探测雷达型号，耗时:{time.time() - self.last_connection_time:.2f}s", end="", flush=True)
            if (frame[2]&0x01 == 0x01) and (frame[3]&0x01 == 0x01): # X2雷达
                if (len(frame)-10) == 3:
                    self.laser_type = LidarType.LIDAR_TYPE_F2
                    print(f"\n[INFO] 雷达型号: {self.laser_type}")
                    self.is_receive_laser_type = True
                elif (len(frame)-10) == 2:
                    self.laser_type = LidarType.LIDAR_TYPE_X2K
                    print(f"\n[INFO] 雷达型号: {self.laser_type}")
                    self.is_receive_laser_type = True
        else:
            try:
                if self.laser_type == LidarType.LIDAR_TYPE_X2:
                    self.laser_x2_parser.put_raw_frame(frame)
                elif self.laser_type == LidarType.LIDAR_TYPE_M1C1:
                    self.laser_m1c1_parser.put_raw_frame(frame)
                elif self.laser_type == LidarType.LIDAR_TYPE_X2N:
                    self.laser_x2n_parser.put_raw_frame(frame)
                elif self.laser_type == LidarType.LIDAR_TYPE_X2K:
                    self.laser_x2k_parser.put_raw_frame(frame)
            except (struct.error, IndexError, ValueError) as exc:
                print(f"\n[WARN] 丢弃异常雷达帧: {exc}, frame_len={len(frame)}, head={frame[:12].hex()}")
                return

    def _handle_m1c1_scan(self, scan_msg):
        """处理 M1C1 雷达的 LaserScan 消息回调"""
        if scan_msg is None or len(scan_msg.ranges) <= 10:
            return
        

        scan_msg.ranges = scan_msg.ranges[::-1]
        scan_msg.intensities = scan_msg.intensities[::-1]
        normalize_scan_grid(scan_msg)

        # 不再重新设置时间戳，保持使用扫描开始时间
        # 这样可以避免TCP传输延迟导致的时间戳不准确问题
        # scan_msg.header.stamp 已经在解析器中设置为扫描开始时间
        
        # 根据Hz频率自动计算 time_increment
        
        if self.rate == 0.0:
            self.rate = 10.0
        else:
            scan_msg.scan_time = 1/self.rate
        
        # 如果时间戳还没有设置，使用当前时间作为后备
        # if scan_msg.header.stamp.sec == 0 and scan_msg.header.stamp.nanosec == 0:
        scan_msg.header.stamp = self.get_clock().now().to_msg()
        
        scan_msg.time_increment = scan_msg.scan_time / len(scan_msg.ranges)
        # 直接发布 LaserScan 消息
        self.publisher.publish(scan_msg)
        
        # 统计发布速率
        self.scan_count += 1
        current_time = self.get_clock().now()
        time_diff = (current_time - self.last_report_time).nanoseconds / 1e9
        
        if time_diff >= 3.0:
            scan_diff = self.scan_count - self.last_report_count
            self.rate = scan_diff / time_diff
            self.get_logger().info(f"/scan话题平均发布速率: {self.rate:.2f} Hz")
            self.last_report_time = current_time
            self.last_report_count = self.scan_count

def main(args=None):
    rclpy.init(args=args)
    node = FishBotLaserDriverNode()
    rclpy.spin(node)
    # try:
    #     rclpy.spin(node)
    # except KeyboardInterrupt:
    #     node.get_logger().info("节点关闭")
    # finally:
    #     node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
