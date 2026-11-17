"""Read a task MCAP against its saved JSON; does not run or rescore physics."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from mcap.reader import make_reader


def quaternion_rotation(values) -> np.ndarray:
    """Restore a rotation independently from the recorded xyzw quaternion."""
    x, y, z, w = np.asarray(values, dtype=float)
    assert np.isfinite([x, y, z, w]).all()
    assert abs(x*x + y*y + z*z + w*w - 1) < 1e-8, "Scene quaternion is not unit length"
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def target_geometry(task_dir: Path):
    root = ET.parse(task_dir / "episode/scene/contact-workcell.xml").getroot()
    geom = root.find(".//body[@name='grasp_target']/geom[@name='target_collision']")
    assert geom is not None and geom.get("type") == "box", "Target box geometry missing"
    assert not any(key in geom.attrib for key in ("euler", "axisangle", "xyaxes", "zaxis", "fromto")), "Unsupported target-local orientation in this audit"
    size = np.fromstring(geom.get("size", ""), sep=" ") * 2
    offset = np.fromstring(geom.get("pos", "0 0 0"), sep=" ")
    w, x, y, z = np.fromstring(geom.get("quat", "1 0 0 0"), sep=" ")
    assert size.shape == offset.shape == (3,)
    return size, offset, quaternion_rotation([x, y, z, w])


def verify(task_dir: Path, require_full_scene: bool = False) -> dict:
    request = json.loads((task_dir / "request.json").read_text())
    status = json.loads((task_dir / "status.json").read_text())
    report = json.loads((task_dir / "episode/report.json").read_text())
    rows = json.loads((task_dir / "episode/trajectory.json").read_text())
    assert rows, "No saved poses to verify"
    receipt = json.loads((task_dir / "episode.recording.json").read_text())
    assert receipt["task_id"] == request["id"], "Recording receipt belongs to another task"
    has_rotation = all("object_rotation" in row for row in rows)
    assert has_rotation or not any("object_rotation" in row for row in rows), "Mixed orientation coverage"
    full_scene = require_full_scene or has_rotation
    if full_scene:
        assert has_rotation, "Full scene requested but source orientation is missing"
        assert receipt.get("geometry") is True, "Full task scene geometry missing"
        assert receipt.get("object_orientation") is True, "Recorded target orientation missing"
        target_size, target_offset, target_local_rotation = target_geometry(task_dir)
    joints = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
    counts = Counter()
    seen = set()
    scene_seen = set()
    position_error = rotation_error = 0.0
    start = end = None
    with (task_dir / "episode.mcap").open("rb") as file:
        reader = make_reader(file, validate_crcs=True)
        summary = reader.get_summary()
        assert summary and summary.chunk_indexes, "Missing indexed MCAP"
        for schema, channel, record in reader.iter_messages():
            message = json.loads(record.data)
            start = record.log_time if start is None else min(start, record.log_time)
            end = record.log_time if end is None else max(end, record.log_time)
            counts[channel.topic] += 1
            if channel.topic == "/so101/task":
                assert message["task_id"] == request["id"]
                assert message["status"] == status["status"]
                assert message["report"] == report, "Original physical report changed"
                assert message["skill_evidence"] == status.get("skill_evidence", report.get("skill_evidence"))
            elif channel.topic == "/so101/episode":
                assert message["run_id"] == request["id"]
                assert message["success"] is report["passed"]
                assert message["metrics"]["physical_lift_passed"] is (report.get("grasp_success") is True)
                assert message["metrics"]["place_verified"] is (report.get("place_success") is True)
                assert message["independent"] == {"available": False}
            elif channel.topic in ("/so101/joints", "/so101/contact"):
                i = record.sequence - 1
                assert 0 <= i < len(rows)
                row = rows[i]
                assert record.log_time == round(row.get("elapsed_s", row.get("time_s")) * 1e9)
                if channel.topic == "/so101/joints":
                    assert [message["position"][key] for key in joints] == row["q6"]
                    assert [message["command"][key] for key in joints] == row["command"]
                    seen.add(i)
                else:
                    assert [message["fixed_finger_n"], message["moving_finger_n"]] == row["tip_forces_n"]
            elif channel.topic == "/so101/scene" and full_scene and record.sequence > 0:
                i = record.sequence - 1
                assert 0 <= i < len(rows) and i not in scene_seen, "Missing or duplicate scene sample"
                row = rows[i]
                assert record.log_time == round(row.get("elapsed_s", row.get("time_s")) * 1e9)
                rotation = np.asarray(row["object_rotation"], dtype=float)
                assert rotation.shape == (3, 3) and np.isfinite(rotation).all()
                expected_position = np.asarray(row["object_xyz_m"]) + rotation @ target_offset
                expected_rotation = rotation @ target_local_rotation
                targets = []
                for entity in message["entities"]:
                    assert entity["timestamp"]["sec"] * 1_000_000_000 + entity["timestamp"]["nsec"] == record.log_time
                    assert {item["key"]: item["value"] for item in entity["metadata"]}.get("task_id") == request["id"]
                    targets.extend(cube for cube in entity.get("cubes", [])
                                   if np.allclose([cube["size"][key] for key in "xyz"], target_size, rtol=0, atol=1e-12))
                assert len(targets) == 1, "Target box not uniquely represented in scene"
                pose = targets[0]["pose"]
                actual_position = np.array([pose["position"][key] for key in "xyz"])
                actual_rotation = quaternion_rotation([pose["orientation"][key] for key in "xyzw"])
                position_error = max(position_error, float(np.max(np.abs(actual_position - expected_position))))
                rotation_error = max(rotation_error, float(np.max(np.abs(actual_rotation - expected_rotation))))
                assert position_error <= 1e-9, f"Target scene position differs at row {i}"
                assert rotation_error <= 1e-8, f"Target scene orientation differs at row {i}"
                scene_seen.add(i)
            if "timestamp" in message:
                assert message["timestamp"]["sec"] * 1_000_000_000 + message["timestamp"]["nsec"] == record.log_time
        assert len(seen) == len(rows), "Some saved poses are missing"
        if full_scene:
            assert len(scene_seen) == len(rows), "Some target scene poses are missing"
        assert counts["/so101/task"] == 2
        middle = round(rows[len(rows) // 2]["elapsed_s"] * 1e9)
        records = list(reader.iter_messages(topics=["/so101/joints"], start_time=middle, end_time=middle + 1))
        assert len(records) == 1, "Indexed seek failed"
    assert start == 0, "Task recording does not include its reset boundary"
    assert end == round(max(rows[-1]["elapsed_s"], report.get("simulation_s", 0)) * 1e9)
    return {"task_id": request["id"], "status": status["status"], "source_rows": len(rows),
            "channels": dict(counts), "start_ns": start, "end_ns": end,
            "original_report_and_grasp_evidence_preserved": True, "indexed_seek": True,
            "full_target_pose_verified": full_scene, "target_scene_rows_verified": len(scene_seen),
            "target_position_max_abs_error_m": position_error if full_scene else None,
            "target_rotation_max_abs_error": rotation_error if full_scene else None,
            "scope": "Saved JSON/MCAP roundtrip, not new physical acceptance"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--require-full-scene", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.task_dir, args.require_full_scene), ensure_ascii=False))
