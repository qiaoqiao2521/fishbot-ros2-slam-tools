#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Offline fixed-pixel observations from an existing ROS2 depth bag. No ROS node or control."""
import argparse
import bisect
from collections import Counter
import json
import math
from pathlib import Path
import struct
import sys
import xml.etree.ElementTree as ET

STREAMS = {
    "front": ("/drone/ego/depth", "/drone/ego/camera_pose"),
    "down": ("/drone/ego/depth_down", "/drone/ego/camera_pose_down"),
}
FRONT_YAWS = (-25, -8, 8, 25)


def clock_bracket(clocks, received_ns):
    """Locate a recorder event between recorded simulation-clock messages."""
    index = bisect.bisect_right([row[0] for row in clocks], received_ns)
    if not index or index == len(clocks):
        return {"reason": "clock_not_bracketed"}
    before, after = clocks[index - 1], clocks[index]
    if before[2] != after[2] or after[1] < before[1]:
        return {"reason": "clock_reset_between_receipts"}
    return {"epoch": before[2], "sim_s": [before[1] / 1e9, after[1] / 1e9]}


def calibration(run, front_sdf):
    import yaml
    file = run / "ego/planner-runtime.yaml"
    params = yaml.safe_load(file.read_text())["/**"]["ros__parameters"]
    front = {key: float(params["grid_map/" + key]) for key in ("fx", "fy", "cx", "cy")}
    front.update(source="saved_planner_yaml_not_recorded_CameraInfo", near_m=None, far_m=None, width=None, height=None)
    # The down camera is generated into this run's model, not assumed identical to the front.
    down = None
    sdf = run / "models/x500_depth/model.sdf"
    if sdf.exists():
        camera = ET.parse(sdf).find(".//sensor[@name='downward_depth']/camera")
        if camera is not None:
            width, height = int(camera.findtext("image/width")), int(camera.findtext("image/height"))
            fov = float(camera.findtext("horizontal_fov"))
            focal = width / (2 * math.tan(fov / 2))
            down = {"fx": focal, "fy": focal, "cx": width / 2, "cy": height / 2,
                    "width": width, "height": height, "near_m": float(camera.findtext("clip/near")),
                    "far_m": float(camera.findtext("clip/far")), "source": "saved_run_SDF_pinhole_not_recorded_CameraInfo"}
    # Preserve the actual front sensor clipping parameters when its pinned SDF is available.
    if front_sdf.exists():
        camera = ET.parse(front_sdf).find(".//sensor[@type='depth_camera']/camera")
        if camera is not None:
            front.update(near_m=float(camera.findtext("clip/near")), far_m=float(camera.findtext("clip/far")),
                         width=int(camera.findtext("image/width")), height=int(camera.findtext("image/height")),
                         clip_source="configured_pinned_OakD_SDF_not_recorded_CameraInfo")
    return {"front": front, "down": down}


def sample_rays(image, intrinsics, stream, sample_pixel, rotate, body_rotation):
    """Fixed pixels only: no obstacle, pose, truth, goal, or policy selects a ray."""
    if intrinsics is None:
        return [{"id": stream, "state": "invalid", "reason": "calibration_unavailable"}]
    if any(not math.isfinite(intrinsics[k]) or intrinsics[k] <= 0 for k in ("fx", "fy")):
        return [{"id": stream, "state": "invalid", "reason": "invalid_intrinsics"}]
    if intrinsics.get("width") is not None and (image["width"], image["height"]) != (intrinsics["width"], intrinsics["height"]):
        return [{"id": stream, "state": "invalid", "reason": "calibration_size_mismatch"}]
    result = []
    for angle in FRONT_YAWS if stream == "front" else (0,):
        fx, fy, cx, cy = (intrinsics[k] for k in ("fx", "fy", "cx", "cy"))
        u, v = math.floor(cx - fx * math.tan(math.radians(angle)) + .5), math.floor(cy + .5)
        optical = [(u - cx) / fx, (v - cy) / fy, 1.]
        scale = math.sqrt(sum(x*x for x in optical))
        direction = [x / scale for x in optical]
        row = {"id": f"{stream}_{angle:+d}", "pixel": [u, v], "requested_yaw_deg": angle,
               "direction_optical": direction, "direction_body_flu": rotate(body_rotation, direction),
               "pixel_fov_rad": [abs(math.atan((u+.5-cx)/fx)-math.atan((u-.5-cx)/fx)),
                                 abs(math.atan((v+.5-cy)/fy)-math.atan((v-.5-cy)/fy))]}
        value = sample_pixel(image, [u, v])
        row.update(raw_float32_hex=value.get("raw_float32_hex"))
        if not value.get("raw_float32_hex"):
            row.update(state="invalid", reason=value.get("reason", "pixel_unavailable"))
        else:
            z = struct.unpack("<f" if image["byte_order"] == "little" else ">f",
                              bytes.fromhex(value["raw_float32_hex"]))[0]
            far, near = intrinsics.get("far_m"), intrinsics.get("near_m")
            if z == math.inf or (far is not None and z >= far):
                row.update(state="no_return", range_m=None, display_range_m=far * scale if far is not None else None)
            elif not math.isfinite(z) or z <= 0 or (near is not None and z < near):
                row.update(state="invalid", reason="invalid_or_near_clipped_depth")
            else:
                row.update(state="hit", depth_z_m=z, range_m=z * scale, display_range_m=z * scale)
        result.append(row)
    return result


def attach_pose(observation, pose, rotate):
    if pose is None:
        observation["pose_state"] = "missing_recorded_source_pose"
        return observation
    if pose["frame"] != "world":
        observation["pose_state"] = "unsupported_pose_frame"
        return observation
    origin, quaternion = pose["position"], pose["orientation"]
    norm = math.sqrt(sum(x*x for x in quaternion))
    if norm <= 0 or not all(math.isfinite(x) for x in [*origin, *quaternion]):
        observation["pose_state"] = "invalid_recorded_pose"
        return observation
    quaternion = [x / norm for x in quaternion]
    observation.update(pose_state="recorded_source_pose", origin_world=origin,
                       pose_record_time_ns=str(pose["record_ns"]), pose_frame=pose["frame"])
    for ray in observation["rays"]:
        if "direction_optical" not in ray:
            continue
        direction = rotate(quaternion, ray["direction_optical"])
        ray["direction_world"] = direction
        if ray.get("display_range_m") is not None:
            ray["endpoint_world"] = [a + ray["display_range_m"]*b for a, b in zip(origin, direction)]
    return observation


def extract(run, root, front_sdf):
    sys.path.insert(0, str(root))
    from inspection_depth import sample_pixel
    from ego.frames import rotate, CAMERA_ROTATION_XYZW, multiply
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message
    request = json.loads((run / "request.json").read_text())
    intrinsics = calibration(run, front_sdf)
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(run / "depth-input"), storage_id="mcap"),
                rosbag2_py.ConverterOptions("", ""))
    selected = {topic for pair in STREAMS.values() for topic in pair} | {"/clock"}
    available = {topic.name: topic.type for topic in reader.get_all_topics_and_types()}
    types = {name: get_message(typ) for name, typ in available.items() if name in selected}
    reader.set_filter(rosbag2_py.StorageFilter(topics=list(types)))
    clocks, poses, observations, counts = [], {key: [] for key in STREAMS}, [], Counter()
    def stamp(header):
        return header.stamp.sec * 10**9 + header.stamp.nanosec
    while reader.has_next():
        topic, raw, received = reader.read_next()
        msg = deserialize_message(raw, types[topic])
        counts[topic] += 1
        if topic == "/clock":
            sim = msg.clock.sec * 10**9 + msg.clock.nanosec
            epoch = (clocks[-1][2] + int(sim < clocks[-1][1])) if clocks else 0
            clocks.append((received, sim, epoch))
            continue
        stream = next(key for key, pair in STREAMS.items() if topic in pair)
        if topic == STREAMS[stream][1]:
            p, q = msg.pose.position, msg.pose.orientation
            poses[stream].append({"source_ns": stamp(msg.header), "record_ns": received,
                                  "position": [p.x, p.y, p.z], "orientation": [q.x, q.y, q.z, q.w], "frame": msg.header.frame_id})
        else:
            image = {"width": msg.width, "height": msg.height, "step": msg.step, "data": bytes(msg.data),
                     "pixel_format": "R_FLOAT32" if msg.encoding == "32FC1" else msg.encoding,
                     "byte_order": "big" if msg.is_bigendian else "little"}
            rotation = CAMERA_ROTATION_XYZW if stream == "front" else multiply((0, math.sqrt(.5), 0, math.sqrt(.5)), CAMERA_ROTATION_XYZW)
            observations.append({"stream": stream, "topic": topic, "source_stamp_ns": str(stamp(msg.header)),
                                 "source_stamp_s": stamp(msg.header) / 1e9, "record_time_ns": str(received),
                                 "frame_id": msg.header.frame_id, "source_encoding": msg.encoding,
                                 "rays": sample_rays(image, intrinsics[stream], stream, sample_pixel, rotate, rotation)})
    clocks.sort(key=lambda row: row[0])
    pose_index = {key: {} for key in STREAMS}
    for stream, values in poses.items():
        for pose in values:
            bracket = clock_bracket(clocks, pose["record_ns"])
            key = (bracket.get("epoch"), pose["source_ns"])
            pose_index[stream].setdefault(key, pose)
    previous, duplicates = {}, 0
    for row in observations:
        bracket = clock_bracket(clocks, int(row["record_time_ns"]))
        row["epoch"] = bracket.get("epoch")
        pose = pose_index[row["stream"]].get((row["epoch"], int(row["source_stamp_ns"]))) if row["epoch"] is not None else None
        attach_pose(row, pose, rotate)
        receipt = max(int(row["record_time_ns"]), pose["record_ns"] if pose else 0)
        row["availability_clock_bracket"] = clock_bracket(clocks, receipt)
        bounds = row["availability_clock_bracket"].get("sim_s")
        if bounds and bounds[1] >= row["source_stamp_s"]:
            row["available_sim_s"] = bounds[1]
            row["age_upper_bound_s"] = bounds[1] - row["source_stamp_s"]
        else:
            row["alignment_reason"] = "source_ahead_of_clock_or_unbracketed"
        key = (row["stream"], row["epoch"])
        old = previous.get(key)
        row["source_gap_s"] = row["source_stamp_s"] - old if old is not None else None
        duplicates += int(old == row["source_stamp_s"])
        previous[key] = row["source_stamp_s"]
    return {"schema_version": 1, "task_id": request["id"], "kind": "virtual_depth_fixed_pixels",
            "clock": "simulation_seconds_not_unix", "record_time_clock": "rosbag_record_time_separate_domain",
            "method": "EGO/PX4 baseline; sparse observer only; MINCO offline candidate",
            "calibration": intrinsics, "topic_counts": dict(counts), "clock_epochs": 1 + max((x[2] for x in clocks), default=-1),
            "source_pose_provenance": "sidecar optical PoseStamped from ideal Gazebo positioning; not independent VIO",
            "limitations": ["四束同一前视深度相机固定像素，非四向ToF；后方、侧方与射线之间未覆盖。",
                            "下视独立一束，不与四束前视假定同步；只有已录转发帧，缺帧不直接判注入丢帧。",
                            "内参来源为保存运行参数/SDF，原包未录CameraInfo；不是实机标定。",
                            "available_sim_s为记录/clock包络上端，非精确传输延迟；无可用包络时不画世界射线。",
                            "位姿由原sidecar理想Gazebo定位生成，不证明仅靠稀疏测距定位或避障。"],
            "summary": {"frames": len(observations), "paired_poses": sum(r.get("pose_state") == "recorded_source_pose" for r in observations),
                        "unaligned_frames": sum("available_sim_s" not in r for r in observations), "duplicate_source_stamps": duplicates,
                        "ray_states": dict(Counter(ray["state"] for r in observations for ray in r["rays"]))},
            "samples": observations}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--drone-root", type=Path, default=Path.home() / "dev/ros2/projects/drone")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--front-model-sdf", type=Path, default=Path.home() / ".cache/ros2-drone/PX4-Autopilot/Tools/simulation/gz/models/OakD-Lite/model.sdf")
    args = parser.parse_args()
    result = extract(args.run_dir, args.drone_root, args.front_model_sdf)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")
    temporary.replace(args.output)
    print(json.dumps({key: result[key] for key in ("task_id", "summary", "clock_epochs", "topic_counts")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
