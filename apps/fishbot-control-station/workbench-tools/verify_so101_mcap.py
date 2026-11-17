"""Independently read MCAP and compare every saved numeric sample to its source."""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path

from jsonschema import Draft7Validator
from mcap.reader import make_reader
from mcap.records import DataEnd, Footer
from mcap.stream_reader import StreamReader
import numpy as np


def sha(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def rotation_from_xyzw(q):
    x, y, z, w = [q[key] for key in ("x", "y", "z", "w")]
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def check_data_section_crc(path: Path) -> None:
    """SeekingReader only checks chunk CRCs; also validate the original byte stream."""
    data_ends = footers = 0
    with path.open("rb") as file:
        for record in StreamReader(file, validate_crcs=True).records:
            if isinstance(record, DataEnd):
                data_ends += 1
                if record.data_section_crc == 0:
                    raise ValueError("Data-section CRC is missing; whole-data validation unavailable")
            elif isinstance(record, Footer):
                footers += 1
    if data_ends != 1 or footers != 1:
        raise ValueError("Expected one complete MCAP data section and footer")


def verify(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    for key, expected in manifest["input_sha256"].items():
        if sha(manifest["input_paths"][key]) != expected:
            raise ValueError(f"Source hash mismatch: {key}")
    if sha(directory / "so101.mcap") != manifest["mcap_sha256"]:
        raise ValueError("MCAP hash mismatch")
    original = json.loads(Path(manifest["input_paths"]["report"]).read_text())
    independent = json.loads(Path(manifest["input_paths"]["independent"]).read_text())
    bindings = {
        "report_to_trace": sha(manifest["input_paths"]["trace"]) == original.get("trace_sha256"),
        "report_to_recorder": sha(manifest["input_paths"]["recorder"]) == original.get("source_adapter_sha256"),
        "report_to_cycle_source": sha(manifest["input_paths"]["cycle_source"]) == original.get("full_cycle_adapter_sha256"),
        "independent_to_report": independent.get("report_sha256") == sha(manifest["input_paths"]["report"]),
    }
    source_bound = all(bindings.values())
    if not source_bound:
        failed = ", ".join(key for key, passed in bindings.items() if not passed)
        raise ValueError(f"Original source binding mismatch: {failed}")
    expected_metrics = {key: original[key] for key in
                        ("wall_s", "physical_lift_passed", "place_verified", "controller_done")}
    expected_metrics.update({
        "settled_duration_s": original["monitor"]["settled_duration_s"],
        "max_xy_drift_m": original["release_audit"]["max_xy_drift_m"],
        "post_detach_peak_force_n": original["release_audit"]["post_detach_peak_force_n"],
    })
    check_data_section_crc(directory / "so101.mcap")
    with np.load(manifest["input_paths"]["trace"], allow_pickle=False) as archive:
        trace = {key: archive[key] for key in archive.files}
    times = np.rint(trace["time_s"] * 1e9).astype(np.int64)
    counts, validators = Counter(), {}
    quaternion_error = 0.0
    image_digests = []
    all_messages = 0
    expected_keys = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
    with (directory / "so101.mcap").open("rb") as file:
        reader = make_reader(file, validate_crcs=True)
        summary = reader.get_summary()
        if summary is None or not summary.chunk_indexes:
            raise ValueError("Seekable MCAP indexes are missing")
        for schema, channel, record in reader.iter_messages():
            if schema.encoding != "jsonschema" or channel.message_encoding != "json":
                raise ValueError("Unexpected schema/message encoding")
            if schema.id not in validators:
                definition = json.loads(schema.data)
                Draft7Validator.check_schema(definition)
                validators[schema.id] = Draft7Validator(definition)
            message = json.loads(record.data)
            validators[schema.id].validate(message)
            i = record.sequence
            if not 0 <= i < len(times):
                raise ValueError("Trace index out of range")
            if record.log_time != int(times[i]) or record.publish_time != int(times[i]):
                raise ValueError("Physical timestamp was changed")
            # Every ordinary channel has one message per original control step.
            expected_index = counts[channel.topic] if channel.topic != "/so101/camera/overview" else 2 * counts[channel.topic] + 1
            if i != expected_index:
                raise ValueError("Missing, duplicate or reordered source row")
            if channel.topic == "/so101/joints":
                for key, array in (("position", "state"), ("command", "action")):
                    if [message[key][joint] for joint in expected_keys] != trace[array][i].tolist():
                        raise ValueError("Joint target or measured state changed")
            elif channel.topic == "/so101/contact":
                if [message["fixed_finger_n"], message["moving_finger_n"]] != trace["tip_forces_n"][i].tolist():
                    raise ValueError("Contact forces changed")
                for key in ("floor_contact", "arm_valid", "obstacle_contact"):
                    if message[key] != bool(trace[key][i]):
                        raise ValueError("Safety/contact flag changed")
            elif channel.topic == "/so101/scene":
                entity = message["entities"][0]
                if entity["frame_id"] != "world" or entity["id"] != "grasp_target":
                    raise ValueError("Object frame identity changed")
                cube = entity["cubes"][0]
                if [cube["pose"]["position"][axis] for axis in ("x", "y", "z")] != trace["object_xyz_m"][i].tolist():
                    raise ValueError("Object trajectory changed")
                if [cube["size"][axis] for axis in ("x", "y", "z")] != manifest["object_size_m"]:
                    raise ValueError("Recorded object geometry changed")
                error = float(np.max(np.abs(rotation_from_xyzw(cube["pose"]["orientation"]) - trace["object_rotation"][i])))
                quaternion_error = max(quaternion_error, error)
                if error > 1e-12:
                    raise ValueError("Object orientation conversion changed the pose")
            elif channel.topic == "/so101/episode":
                if message["stage"] != trace["stage"][i]:
                    raise ValueError("Original phase changed")
                if message["success"] != original["full_grasp_place_passed"]:
                    raise ValueError("Original success was reinterpreted")
                if message["independent"]["passed"] != independent["passed"]:
                    raise ValueError("Independent result changed")
                if message["independent"]["return_max_error_rad"] != independent["return_max_error_rad"]:
                    raise ValueError("Independent metric changed")
                if message["metrics"] != expected_metrics:
                    raise ValueError("Original report metrics changed")
                if message["provenance"]["source_bound"] is not source_bound:
                    raise ValueError("Message source_bound differs from recomputed source bindings")
                events = [{"stage": str(trace["stage"][j]), "sim_time_s": float(trace["time_s"][j])}
                          for j in range(len(times)) if j == 0 or trace["stage"][j] != trace["stage"][j-1]]
                if message["stage_events"] != events:
                    raise ValueError("Phase event timestamps changed")
                for key, expected in manifest["input_sha256"].items():
                    if key in ("trace", "report") and message["provenance"][key + "_sha256"] != expected:
                        raise ValueError("Source fingerprint changed")
            elif channel.topic == "/so101/camera/overview":
                data = base64.b64decode(message["data"], validate=True)
                if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
                    raise ValueError("RGB payload is not a complete JPEG")
                image_digests.append(hashlib.sha256(data).hexdigest())
            else:
                raise ValueError(f"Unexpected topic: {channel.topic}")
            ts = message.get("timestamp", message.get("entities", [{}])[0].get("timestamp"))
            if ts["sec"] * 1_000_000_000 + ts["nsec"] != record.log_time:
                raise ValueError("Payload and MCAP timestamps differ")
            counts[channel.topic] += 1
            all_messages += 1
        # Request one interior step through the actual chunk index.
        middle = int(times[len(times) // 2])
        found = list(reader.iter_messages(topics=["/so101/episode"], start_time=middle, end_time=middle + 1))
        if len(found) != 1:
            raise ValueError("Indexed seek did not find exactly one interior episode state")
    for topic in ("/so101/joints", "/so101/contact", "/so101/scene", "/so101/episode"):
        if counts[topic] != len(times):
            raise ValueError(f"Incomplete channel: {topic}")
    if manifest["video_mapping"].get("verified"):
        if len(image_digests) != len(times[1::2]):
            raise ValueError("RGB coverage differs from the proven recording cadence")
        if image_digests[0] != sha(directory / "first-frame.jpg") or image_digests[-1] != sha(directory / "last-frame.jpg"):
            raise ValueError("RGB endpoint previews differ")
    return {"passed": True, "scope": "MCAP chunk/data-section CRC, schema/index/source roundtrip; not browser or new physics acceptance",
            "mcap_sha256": manifest["mcap_sha256"], "input_sha256": manifest["input_sha256"],
            "messages": all_messages, "channel_counts": dict(counts),
            "source_rows_compared": len(times), "max_orientation_roundtrip_error": quaternion_error,
            "indexed_seek_passed": True, "data_section_crc_passed": True,
            "original_source_bindings": bindings, "report_metrics_compared": list(expected_metrics),
            "video_mapping": manifest["video_mapping"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    result = verify(args.directory)
    (args.directory / "readback.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))
