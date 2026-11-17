#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Independently read original CDR pixels/poses; never publish or control."""
import argparse
import bisect
import json
import math
from pathlib import Path
import struct


def audit(bag, exported):
    import numpy as np
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message
    value = json.loads(exported.read_text())
    records = {(r['stream'], r['source_stamp_ns']): r for r in value['samples']}
    pairs = {'/drone/ego/depth': 'front', '/drone/ego/depth_down': 'down'}
    pose_topics = {'/drone/ego/camera_pose': 'front', '/drone/ego/camera_pose_down': 'down'}
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(bag), storage_id='mcap'), rosbag2_py.ConverterOptions('', ''))
    types = {t.name: get_message(t.type) for t in reader.get_all_topics_and_types() if t.name in {*pairs, *pose_topics, '/clock'}}
    reader.set_filter(rosbag2_py.StorageFilter(topics=list(types)))
    pixels, poses, clocks, failures = 0, {}, [], []
    slant_error = endpoint_error = 0.
    for_check = []
    while reader.has_next():
        topic, raw, received = reader.read_next()
        msg = deserialize_message(raw, types[topic])
        if topic == '/clock':
            clocks.append((received, msg.clock.sec * 10**9 + msg.clock.nanosec))
            continue
        source_ns = str(msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec)
        if topic in pose_topics:
            p, q = msg.pose.position, msg.pose.orientation
            poses[(pose_topics[topic], source_ns)] = ([p.x, p.y, p.z], [q.x, q.y, q.z, q.w], received)
            continue
        row = records[(pairs[topic], source_ns)]
        cal = value['calibration'][pairs[topic]]
        for ray in row['rays']:
            u, v = ray['pixel']
            actual = bytes(msg.data[v * msg.step + u * 4:v * msg.step + u * 4 + 4])
            if ray['raw_float32_hex'] != actual.hex():
                failures.append('raw_pixel_mismatch')
            z, = struct.unpack('>f' if msg.is_bigendian else '<f', actual)
            if math.isfinite(z) and cal['near_m'] <= z < cal['far_m']:
                point = np.array([z * (u-cal['cx'])/cal['fx'], z * (v-cal['cy'])/cal['fy'], z])
                slant_error = max(slant_error, abs(float(np.linalg.norm(point)) - ray['range_m']))
                for_check.append((row, ray, point))
            elif ray['state'] == 'hit':
                failures.append('invalid_pixel_marked_hit')
            pixels += 1
    clock_receipts = [c[0] for c in clocks]
    paired = 0
    for row in value['samples']:
        p, q, pose_receipt = poses[(row['stream'], row['source_stamp_ns'])]
        if row['origin_world'] != p:
            failures.append('source_pose_origin_mismatch')
        received = max(int(row['record_time_ns']), pose_receipt)
        i = bisect.bisect_right(clock_receipts, received)
        recorded_bounds_ns = [round(t * 1e9) for t in row['availability_clock_bracket']['sim_s']]
        if not 0 < i < len(clocks) or recorded_bounds_ns != [clocks[i-1][1], clocks[i][1]]:
            failures.append('clock_bracket_mismatch')
        paired += 1
    for row, ray, point in for_check:
        p, q, _ = poses[(row['stream'], row['source_stamp_ns'])]
        x, y, z, w = np.asarray(q) / np.linalg.norm(q)
        rotation = np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                             [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                             [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])
        endpoint_error = max(endpoint_error, float(np.max(np.abs(np.asarray(p) + rotation @ point - ray['endpoint_world']))))
    passed = not failures and slant_error < 1e-10 and endpoint_error < 1e-10
    return {'passed': passed, 'task_id': value['task_id'], 'raw_pixels_checked': pixels, 'source_poses_checked': paired,
            'slant_max_error_m': slant_error, 'world_endpoint_max_error_m': endpoint_error,
            'failures': failures[:20], 'scope': 'Original recorded pixels/poses and clock brackets only; not flight or obstacle-detection acceptance'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bag', type=Path, required=True)
    parser.add_argument('--exported', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.bag, args.exported)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result))
    raise SystemExit(0 if result['passed'] else 1)
