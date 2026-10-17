"""Convert a saved SO101 episode to indexed MCAP; never run the simulation."""
from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from mcap.writer import Writer
import numpy as np

HERE = Path(__file__).resolve().parent
JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
TOPICS = {"joints": "/so101/joints", "contact": "/so101/contact", "scene": "/so101/scene",
          "episode": "/so101/episode", "image": "/so101/camera/overview"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def packed(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def timestamp(ns: int) -> dict:
    return {"sec": ns // 1_000_000_000, "nsec": ns % 1_000_000_000}


def object_quaternion(rotation: np.ndarray) -> dict:
    """Extract xyzw from a proper rotation using its symmetric eigenproblem."""
    r = rotation
    k = np.array([
        [r[0, 0]-r[1, 1]-r[2, 2], r[0, 1]+r[1, 0], r[0, 2]+r[2, 0], r[2, 1]-r[1, 2]],
        [r[0, 1]+r[1, 0], r[1, 1]-r[0, 0]-r[2, 2], r[1, 2]+r[2, 1], r[0, 2]-r[2, 0]],
        [r[0, 2]+r[2, 0], r[1, 2]+r[2, 1], r[2, 2]-r[0, 0]-r[1, 1], r[1, 0]-r[0, 1]],
        [r[2, 1]-r[1, 2], r[0, 2]-r[2, 0], r[1, 0]-r[0, 1], np.trace(r)],
    ]) / 3
    _, vectors = np.linalg.eigh(k)
    q = vectors[:, -1]
    if q[3] < 0:
        q = -q
    return dict(zip(("x", "y", "z", "w"), map(float, q)))


def validate_trace(trace) -> np.ndarray:
    times = np.asarray(trace["time_s"])
    n = len(times)
    shapes = {"stage": (n,), "state": (n, 6), "action": (n, 6), "object_xyz_m": (n, 3),
              "object_rotation": (n, 3, 3), "tip_forces_n": (n, 2), "floor_contact": (n,),
              "arm_valid": (n,), "obstacle_contact": (n,)}
    if n == 0 or times.ndim != 1 or not np.isfinite(times).all() or np.any(times < 0):
        raise ValueError("Expected nonempty finite nonnegative simulation time")
    if np.any(np.diff(times) <= 0):
        raise ValueError("Simulation time must strictly increase")
    for key, shape in shapes.items():
        array = np.asarray(trace[key])
        if array.shape != shape:
            raise ValueError(f"Unexpected {key} shape: {array.shape}")
        if key != "stage" and not np.isfinite(array).all():
            raise ValueError(f"Nonfinite {key}")
    rotations = trace["object_rotation"]
    if not np.allclose(rotations @ rotations.transpose(0, 2, 1), np.eye(3), atol=1e-10):
        raise ValueError("Object orientations must be orthogonal")
    if not np.allclose(np.linalg.det(rotations), 1, atol=1e-10):
        raise ValueError("Object orientations must be proper rotations")
    ns = np.rint(times * 1_000_000_000).astype(np.int64)
    if np.any(np.diff(ns) <= 0):
        raise ValueError("Simulation times collide after nanosecond conversion")
    return ns


def verify_video_source(source: Path, expected_hash: str) -> None:
    """Accept only the reviewed recorder rule, without importing its module."""
    if digest(source) != expected_hash:
        raise ValueError("Recorder source no longer matches the original report")
    tree = ast.parse(source.read_text())
    modulo_rule = False
    writer_25fps = False
    append_rendered = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            text = ast.unparse(node.test)
            modulo_rule |= text == "renderer is not None and len(rows) % 2 == 0"
            append_rendered |= modulo_rule and any(
                isinstance(call, ast.Call) and ast.unparse(call.func) == "writer.append_data"
                and [ast.unparse(arg) for arg in call.args] == ["renderer.render()"]
                for item in node.body for call in ast.walk(item)
            )
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "imageio.get_writer":
            writer_25fps |= any(k.arg == "fps" and isinstance(k.value, ast.Constant)
                               and k.value.value == 25 for k in node.keywords)
    if not (modulo_rule and writer_25fps and append_rendered):
        raise ValueError("Recorder rule requires a fresh source review")


def video_mapping(video: Path, times: np.ndarray, source: Path, expected_hash: str) -> dict:
    verify_video_source(source, expected_hash)
    raw = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
        "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(video)], text=True)
    pts = np.array([float(row["best_effort_timestamp_time"]) for row in json.loads(raw)["frames"]])
    expected = times[1::2]
    if len(pts) != len(expected) or not len(pts):
        raise ValueError("Video frame count does not match recorder cadence")
    if not np.allclose(pts, np.arange(len(pts)) / 25, atol=1e-8, rtol=0):
        raise ValueError("Video PTS is not the reviewed constant 25fps stream")
    if not np.allclose(expected - expected[0], pts, atol=1e-8, rtol=0):
        raise ValueError("Video timestamps cannot be mapped to physical samples")
    return {"verified": True, "frames": len(pts), "trace_first_index": 1, "trace_stride": 2,
            "fps": 25, "first_video_pts_s": float(pts[0]),
            "first_sim_time_s": float(expected[0]), "mapping": "video_frame_j -> trace[2*j+1]",
            "recorder_source_sha256": expected_hash, "jpeg_transcode": True}


def jpeg_frames(video: Path, log: Path):
    """Stream ffmpeg's intra-frame JPEG output without buffering the video."""
    with log.open("wb") as errors:
        process = subprocess.Popen([
            "ffmpeg", "-nostdin", "-v", "error", "-i", str(video), "-map", "0:v:0",
            "-fps_mode", "passthrough", "-f", "image2pipe", "-c:v", "mjpeg", "-q:v", "3", "-"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors)
        try:
            pending = b""
            while block := process.stdout.read(65536):
                pending += block
                while (end := pending.find(b"\xff\xd9")) != -1:
                    image, pending = pending[:end + 2], pending[end + 2:]
                    if not image.startswith(b"\xff\xd8"):
                        raise ValueError("Invalid JPEG frame from ffmpeg")
                    yield image
                if len(pending) > 16 * 1024 * 1024:
                    raise ValueError("Unbounded JPEG frame")
            if pending or process.wait() != 0:
                raise ValueError("ffmpeg did not finish a complete image stream")
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.terminate()
                process.wait()


def numeric_schema(name: str, fields: dict) -> dict:
    return {"title": name, "type": "object", "properties": fields, "required": list(fields)}


def convert(episode: Path, source_root: Path, output: Path, include_rgb: bool = False) -> dict:
    episode, source_root, output = episode.resolve(), source_root.resolve(), output.resolve()
    if not output.is_relative_to(HERE / "output") or output == HERE / "output":
        raise ValueError("Output must be a new directory below workbench-tools/output/")
    files = {"trace": episode / "trace.npz", "report": episode / "report.json",
             "independent": episode / "independent-acceptance.json",
             "scene": episode / "scene/contact-workcell.xml",
             "recorder": source_root / "experiments/graspgenx-demo/contact_probe.py",
             "cycle_source": source_root / "experiments/graspgenx-demo/full_cycle.py",
             "adapter": Path(__file__)}
    if include_rgb:
        files["video"] = episode / "grasp-lift.mp4"
    frozen = {name: digest(path) for name, path in files.items()}
    report = json.loads(files["report"].read_text())
    independent = json.loads(files["independent"].read_text())
    bound = (frozen["trace"] == report.get("trace_sha256")
             and frozen["recorder"] == report.get("source_adapter_sha256")
             and frozen["cycle_source"] == report.get("full_cycle_adapter_sha256"))
    if not bound or independent.get("report_sha256") != frozen["report"]:
        raise ValueError("Original trace/source/report/independent bindings do not match")
    if report.get("hardware_access") is not False:
        raise ValueError("This adapter only accepts recorded simulation evidence")
    if not isinstance(report.get("full_grasp_place_passed"), bool) or not isinstance(independent.get("passed"), bool):
        raise ValueError("Original acceptance fields must be booleans")
    with np.load(files["trace"], allow_pickle=False) as archive:
        trace = {key: archive[key] for key in archive.files}
        ns = validate_trace(trace)
        times, stages = trace["time_s"], trace["stage"]
        mapping = video_mapping(files["video"], times, files["recorder"], frozen["recorder"]) if include_rgb else {"verified": False, "included": False}
        scene_xml = ET.parse(files["scene"]).getroot()
        geom = scene_xml.find('.//geom[@name="target_collision"]')
        if geom is None or geom.get("type") != "box":
            raise ValueError("Expected recorded box target geometry")
        size = 2 * np.fromstring(geom.attrib["size"], sep=" ")
        if size.shape != (3,) or not np.isfinite(size).all() or np.any(size <= 0):
            raise ValueError("Invalid recorded target dimensions")
        events = [{"stage": str(stages[i]), "sim_time_s": float(times[i])}
                  for i in range(len(times)) if i == 0 or stages[i] != stages[i - 1]]
        metrics = {key: report[key] for key in ("wall_s", "physical_lift_passed", "place_verified", "controller_done")}
        metrics.update({"settled_duration_s": report["monitor"]["settled_duration_s"],
                        "max_xy_drift_m": report["release_audit"]["max_xy_drift_m"],
                        "post_detach_peak_force_n": report["release_audit"]["post_detach_peak_force_n"]})
        review = {"schema_version": 1, "run_id": episode.name,
                  "task": "固定方块抓取、搬运、释放与回位", "source_kind": "simulation_recording",
                  "clock": "simulation_seconds_not_unix", "sim_duration_s": float(times[-1]),
                  "success": report["full_grasp_place_passed"], "stage_events": events,
                  "independent": {"available": True, "passed": independent["passed"],
                                  "return_max_error_rad": independent["return_max_error_rad"]},
                  "metrics": metrics, "provenance": {"trace_sha256": frozen["trace"],
                  "report_sha256": frozen["report"], "source_bound": bound},
                  "limitations": ["固定场景单回合，不是批次成功率", "历史仿真记录，不是实时或实体操作", "没有重新训练或运行仿真"]}
        output.mkdir(parents=True, exist_ok=False)
        (output / "episode.sample.json").write_bytes(packed({**review, "timestamp": timestamp(int(ns[0])), "stage": str(stages[0])}) + b"\n")
        manifest = {"schema_version": 1, "status": "converting", "input_sha256": frozen,
                    "input_paths": {k: str(v) for k, v in files.items()}, "source_bound": bound,
                    "samples": len(times), "start_ns": int(ns[0]), "end_ns": int(ns[-1]),
                    "clock": "simulation_seconds_not_unix", "video_mapping": mapping,
                    "topics": TOPICS, "object_size_m": size.tolist(), "mcap_library": "mcap==1.3.0"}
        (output / "manifest.json").write_bytes(packed(manifest) + b"\n")
        time_schema = {"type": "object", "properties": {"sec": {"type": "integer"}, "nsec": {"type": "integer"}}}
        joints_schema = numeric_schema("so101.JointSample", {"timestamp": time_schema,
            "position": numeric_schema("position", {j: {"type": "number"} for j in JOINTS}),
            "command": numeric_schema("command", {j: {"type": "number"} for j in JOINTS})})
        contact_schema = numeric_schema("so101.ContactSample", {"timestamp": time_schema,
            "fixed_finger_n": {"type": "number"}, "moving_finger_n": {"type": "number"},
            "floor_contact": {"type": "boolean"}, "arm_valid": {"type": "boolean"}, "obstacle_contact": {"type": "boolean"}})
        schemas = {"joints": joints_schema, "contact": contact_schema,
                   "scene": json.loads((HERE / "schemas/SceneUpdate.json").read_text()),
                   "episode": json.loads((HERE / "schemas/EpisodeReview.json").read_text())}
        if include_rgb:
            schemas["image"] = json.loads((HERE / "schemas/CompressedImage.json").read_text())
        stream = jpeg_frames(files["video"], output / "ffmpeg.log") if include_rgb else None
        image_count = 0
        with (output / "so101.mcap.partial").open("wb") as file:
            writer = Writer(file, enable_data_crcs=True)
            writer.start(library="SO101 saved-episode adapter; mcap 1.3.0")
            channels = {}
            for kind, schema in schemas.items():
                schema_id = writer.register_schema(schema["title"], "jsonschema", packed(schema))
                channels[kind] = writer.register_channel(TOPICS[kind], "json", schema_id,
                    {"clock": manifest["clock"], "source_kind": "simulation_recording"})
            writer.add_metadata("so101.provenance", {k: str(v) for k, v in frozen.items()})
            writer.add_metadata("so101.clock", {"kind": manifest["clock"], "video_mapping": json.dumps(mapping)})
            try:
                for i, tick in enumerate(ns):
                    ts = timestamp(int(tick))
                    messages = {
                        "joints": {"timestamp": ts, "position": dict(zip(JOINTS, map(float, trace["state"][i]))),
                                   "command": dict(zip(JOINTS, map(float, trace["action"][i])))},
                        "contact": {"timestamp": ts, "fixed_finger_n": float(trace["tip_forces_n"][i, 0]),
                                    "moving_finger_n": float(trace["tip_forces_n"][i, 1]),
                                    **{key: bool(trace[key][i]) for key in ("floor_contact", "arm_valid", "obstacle_contact")}},
                        "episode": {**review, "timestamp": ts, "stage": str(stages[i])},
                        "scene": {"deletions": [], "entities": [{"timestamp": ts, "frame_id": "world", "id": "grasp_target",
                            "lifetime": {"sec": 0, "nsec": 0}, "frame_locked": False, "metadata": [], "arrows": [],
                            "cubes": [{"pose": {"position": dict(zip(("x", "y", "z"), map(float, trace["object_xyz_m"][i]))),
                                                 "orientation": object_quaternion(trace["object_rotation"][i])},
                                       "size": dict(zip(("x", "y", "z"), map(float, size))),
                                       "color": {"r": 0.1, "g": 0.8, "b": 0.25, "a": 1}}],
                            "spheres": [], "cylinders": [], "lines": [], "triangles": [], "texts": [], "models": []}]},
                    }
                    if stream is not None and i % 2 == 1:
                        image = next(stream)
                        messages["image"] = {"timestamp": ts, "frame_id": "overview", "format": "jpeg",
                                             "data": base64.b64encode(image).decode()}
                        image_count += 1
                        if image_count in (1, mapping["frames"]):
                            (output / ("first-frame.jpg" if image_count == 1 else "last-frame.jpg")).write_bytes(image)
                    for kind, message in messages.items():
                        writer.add_message(channels[kind], int(tick), packed(message), int(tick), sequence=i)
                if stream is not None and next(stream, None) is not None:
                    raise ValueError("Video has additional frames")
                writer.finish()
            finally:
                if stream is not None:
                    stream.close()
        if frozen != {k: digest(v) for k, v in files.items()}:
            raise ValueError("Inputs changed during conversion")
        (output / "so101.mcap.partial").rename(output / "so101.mcap")
        manifest.update(status="converted_not_browser_accepted", image_samples=image_count,
                        adapter_sha256=digest(Path(__file__)),
                        mcap_sha256=digest(output / "so101.mcap"))
        (output / "manifest.json").write_bytes(packed(manifest) + b"\n")
        return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode-dir", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-rgb", action="store_true")
    args = parser.parse_args()
    result = convert(args.episode_dir, args.source_root, args.output, args.include_rgb)
    print(json.dumps({"status": result["status"], "samples": result["samples"],
                      "image_samples": result["image_samples"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
