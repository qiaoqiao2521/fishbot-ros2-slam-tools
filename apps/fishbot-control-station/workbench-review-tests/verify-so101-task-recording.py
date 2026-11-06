"""Read a task MCAP against its saved JSON; does not run or rescore physics."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
from mcap.reader import make_reader


def verify(task_dir: Path) -> dict:
    request = json.loads((task_dir / "request.json").read_text())
    status = json.loads((task_dir / "status.json").read_text())
    report = json.loads((task_dir / "episode/report.json").read_text())
    rows = json.loads((task_dir / "episode/trajectory.json").read_text())
    joints = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
    counts = Counter()
    seen = set()
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
            if "timestamp" in message:
                assert message["timestamp"]["sec"] * 1_000_000_000 + message["timestamp"]["nsec"] == record.log_time
        assert len(seen) == len(rows), "Some saved poses are missing"
        assert counts["/so101/task"] == 2
        middle = round(rows[len(rows) // 2]["elapsed_s"] * 1e9)
        records = list(reader.iter_messages(topics=["/so101/joints"], start_time=middle, end_time=middle + 1))
        assert len(records) == 1, "Indexed seek failed"
    assert start == 0, "Task recording does not include its reset boundary"
    assert end == round(max(rows[-1]["elapsed_s"], report.get("simulation_s", 0)) * 1e9)
    return {"task_id": request["id"], "status": status["status"], "source_rows": len(rows),
            "channels": dict(counts), "start_ns": start, "end_ns": end,
            "original_report_and_grasp_evidence_preserved": True, "indexed_seek": True,
            "scope": "Saved JSON/MCAP roundtrip, not new physical acceptance"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    print(json.dumps(verify(parser.parse_args().task_dir), ensure_ascii=False))
