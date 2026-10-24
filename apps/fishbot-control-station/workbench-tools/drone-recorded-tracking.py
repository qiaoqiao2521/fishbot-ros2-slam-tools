#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Read original odometry/FSM evidence for M2; never select or send control."""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import re

import numpy as np


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def json_rows(file, warnings):
    if not file.exists():
        warnings.append(f"{file.name}: unavailable")
        return []
    result = []
    for line, raw in enumerate(file.read_text().splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise ValueError("expected object")
            result.append({**row, "source_line": line})
        except ValueError as error:
            warnings.append(f"{file.name}:{line}: {error}")
    return result


def read_odometry(run):
    # Existing ROS2 CDR reader only: no rclpy.init(), node or transport.
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from nav_msgs.msg import Odometry
    from rosgraph_msgs.msg import Clock
    sparse = load("sparse_clock", Path(__file__).with_name("drone-sparse-observations.py"))
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(run / "depth-input"), storage_id="mcap"),
                rosbag2_py.ConverterOptions("", ""))
    inventory = [{"name": topic.name, "type": topic.type} for topic in reader.get_all_topics_and_types()]
    reader.set_filter(rosbag2_py.StorageFilter(topics=["/clock", "/drone/ego/odom"]))
    clocks, states = [], []
    while reader.has_next():
        topic, raw, received = reader.read_next()
        if topic == "/clock":
            msg = deserialize_message(raw, Clock)
            stamp = msg.clock.sec * 10**9 + msg.clock.nanosec
            epoch = clocks[-1][2] + int(stamp < clocks[-1][1]) if clocks else 0
            clocks.append((received, stamp, epoch))
        else:
            msg = deserialize_message(raw, Odometry)
            p, v = msg.pose.pose.position, msg.twist.twist.linear
            stamp = msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec
            states.append({"source_stamp_ns": str(stamp), "source_sim_s": stamp / 1e9,
                "record_time_ns": str(received), "frame_id": msg.header.frame_id,
                "velocity_frame_id": msg.child_frame_id, "position": [p.x, p.y, p.z],
                "velocity": [v.x, v.y, v.z], "acceleration": None})
    clocks.sort(key=lambda row: row[0])
    for state in states:
        bracket = sparse.clock_bracket(clocks, int(state["record_time_ns"]))
        state["availability_clock_bracket"] = bracket
        state["epoch"] = bracket.get("epoch")
        bounds = bracket.get("sim_s")
        if bounds and bounds[1] >= state["source_sim_s"]:
            state["available_by_sim_s"] = bounds[1]
            state["age_upper_bound_s"] = bounds[1] - state["source_sim_s"]
    return states, inventory, len({row[2] for row in clocks})


def log_evidence(file):
    result = {"fsm": [], "callbacks": [], "inflation": [], "voxel_events": 0,
              "voxel_cells": set(), "warnings": []}
    if not file.exists():
        result["voxel_cells"] = []
        return result
    for number, line in enumerate(file.read_text().splitlines(), 1):
        line = re.sub(r"\x1b\[[0-9;]*m", "", line)
        if "InflatedVoxelTransition {" in line:
            try:
                result["inflation"].append({"source_line": number, **json.loads(line[line.index("{"):])})
            except ValueError as error:
                result["warnings"].append(f"planner.log:{number}: invalid inflation witness: {error}")
        if "VoxelEvidence " in line:
            result["voxel_events"] += 1
            match = re.search(r"cell=(\[[^\]]+\])", line)
            if match:
                result["voxel_cells"].add(tuple(json.loads(match[1])))
        kind = "fsm" if "FSMStart sim=" in line else "callbacks" if "MapCallback kind=" in line else None
        if kind:
            fields = {}
            for key, value in re.findall(r"(\w+)=(\[[^\]]*\]|[^ ]+)", line):
                try:
                    fields[key] = json.loads(value)
                except ValueError:
                    fields[key] = value
            required = ("sim", "odom_source", "odom_p", "odom_v", "ref_p") if kind == "fsm" else ("kind", "end")
            if any(key not in fields for key in required):
                result["warnings"].append(f"planner.log:{number}: incomplete {kind} witness")
                continue
            wall = re.search(r"\[(\d{10}\.\d+)\]", line)
            result[kind].append({"source_line": number, "wall_stamp_s": wall[1] if wall else None, **fields})
    result["voxel_cells"] = sorted(result["voxel_cells"])
    return result


def reference(record, stamp, evaluator):
    spline = evaluator(record)
    local = stamp - record["start_sim_s"] + spline.t[3]
    if not spline.t[3] <= local <= spline.t[-4]:
        return None
    return np.column_stack([spline(local, nu=i) for i in range(3)])


def summarize(rows):
    if not rows:
        return {"samples": 0}
    p = np.array([row["position_error_xyz"] for row in rows])
    v = np.array([row["velocity_error_xyz"] for row in rows])
    norm = np.linalg.norm(p, axis=1)
    return {"samples": len(rows), "position_max_m": float(norm.max()),
        "position_p95_m": float(np.quantile(norm, .95)), "position_rms_m": float(np.sqrt(np.mean(norm**2))),
        "position_abs_axis_max_m": abs(p).max(axis=0).tolist(),
        "positive_z_error_max_m": float(max(0., p[:, 2].max())),
        "velocity_max_m_s": float(np.linalg.norm(v, axis=1).max()),
        "peak_position_source_sim_s": rows[int(norm.argmax())]["source_sim_s"]}


def analyze(states, records, log, task_id, failure_s, evaluator, single_epoch=True):
    records = sorted(records, key=lambda row: row["received_sim_s"])
    rows, excluded = [], Counter()
    for state in states:
        time = state["source_sim_s"]
        if not single_epoch or state.get("epoch") != 0:
            excluded["clock_epoch_unattributed"] += 1
            continue
        if state.get("frame_id") != "world" or state.get("velocity_frame_id") != "world":
            excluded["frame_unverified"] += 1
            continue
        if failure_s is None or time >= failure_s:
            excluded["not_strictly_before_primary_failure"] += 1
            continue
        current = next((r for r in reversed(records) if r["received_sim_s"] <= time), None)
        if current is None or current.get("task_id") != task_id:
            excluded["no_attributed_active_curve"] += 1
            continue
        target = reference(current, time, evaluator)
        if target is None:
            excluded["outside_curve_domain"] += 1
            continue
        p, v = np.asarray(state["position"]), np.asarray(state["velocity"])
        if p.shape != (3,) or v.shape != (3,) or not np.all(np.isfinite(np.r_[p, v])):
            excluded["invalid_recorded_pv"] += 1
            continue
        rows.append({"source_sim_s": time, "source_stamp_ns": state["source_stamp_ns"],
            "record_time_ns": state["record_time_ns"], "trajectory_id": current["trajectory_id"],
            "curve_source_line": current["source_line"], "observed_position": p.tolist(),
            "observed_velocity": v.tolist(), "reference_pva": target.tolist(),
            "position_error_xyz": (p-target[:, 0]).tolist(), "velocity_error_xyz": (v-target[:, 1]).tolist()})
    fsm = []
    for item in log["fsm"]:
        current = next((r for r in records if r["trajectory_id"] == item.get("trajectory")), None)
        row = {**item, "same_stamp_position_gap_m": None, "same_stamp_velocity_gap_m_s": None,
               "odometry_age_sim_s": item["sim"] - item["odom_source"]}
        observed = next((s for s in states if abs(s["source_sim_s"]-item["odom_source"]) < 1e-9), None)
        source_verified = observed and single_epoch and observed.get("epoch") == 0 and all(
            observed.get(key) == "world" for key in ("frame_id", "velocity_frame_id"))
        if source_verified:
            row["bag_pv_match_error"] = [float(np.linalg.norm(np.asarray(observed[key])-item[log_key]))
                for key, log_key in (("position", "odom_p"), ("velocity", "odom_v"))]
        row["mixed_time_position_gap_m"] = float(np.linalg.norm(np.asarray(item["ref_p"])-item["odom_p"]))
        current_available = current and current.get("task_id") == task_id and current["received_sim_s"] <= item["sim"]
        aligned = reference(current, item["odom_source"], evaluator) if current_available and source_verified else None
        if aligned is not None:
            row["alignment"] = "retrospective_current_curve_at_odometry_source_stamp"
            row["same_stamp_position_gap_m"] = float(np.linalg.norm(aligned[:, 0]-item["odom_p"]))
            row["same_stamp_velocity_gap_m_s"] = float(np.linalg.norm(aligned[:, 1]-item["odom_v"]))
        else:
            row["alignment"] = "unverified_curve_domain_availability_frame_or_epoch; no backwards extrapolation"
        # Associate only callbacks finished before FSM start, in the same sim domain.
        row["latest_completed_callbacks"] = {kind: next((c for c in reversed(log["callbacks"])
            if single_epoch and c.get("kind") == kind and c.get("end", np.inf) <= item["sim"]), None)
            for kind in ("front", "down")}
        fsm.append(row)
    receipts = []
    for current in records:
        now = current["received_sim_s"]
        available = [s for s in states if single_epoch and s.get("epoch") == 0
                     and s.get("available_by_sim_s", np.inf) <= now]
        observed = max(available, key=lambda s: s["source_sim_s"]) if available else None
        receipts.append({"trajectory_id": current["trajectory_id"], "curve_source_line": current["source_line"],
            "received_sim_s": now, "recorded_task_id": current.get("task_id"),
            "latest_recorder_available_pv": observed,
            "state_source_age_at_curve_receipt_s": now-observed["source_sim_s"] if observed else None,
            "state_scope": "conservative recorder availability; not planner callback consumption ACK",
            "full_pva_qualified": False, "acceleration": None,
            "unqualified_reasons": ["acceleration_unrecorded", "tracking_bound_uncalibrated",
                "complete_time_valid_map_unqualified", "terminal_region_unqualified"] +
                ([] if current.get("task_id") == task_id else ["curve_task_identity_unverified"])})
    return {"tracking": rows, "tracking_summary": summarize(rows), "excluded": dict(excluded),
        "per_curve": {str(c["trajectory_id"]): summarize([r for r in rows if r["trajectory_id"] == c["trajectory_id"]]) for c in records},
        "fsm": fsm, "curve_receipts": receipts}


def run(run_dir, root, candidates=None):
    warnings = []
    request = json.loads((run_dir / "request.json").read_text())
    report = json.loads((run_dir / "report.json").read_text())
    states, inventory, epochs = read_odometry(run_dir)
    primitives = load("primitives", Path(__file__).with_name("drone-trajectory-primitives.py"))
    evaluator, _ = primitives.reuse(root)
    records = []
    for row in json_rows(run_dir / "ego/trajectory-events.jsonl", warnings):
        try:
            if row.get("order") != 3:
                raise ValueError("existing source evaluator expects cubic B-spline")
            if not np.all(np.isfinite([row["start_sim_s"], row["received_sim_s"]])):
                raise ValueError("nonfinite source time")
            evaluator(row)
            records.append(row)
        except (ValueError, KeyError, TypeError) as error:
            warnings.append(f"trajectory-events.jsonl:{row['source_line']}: skipped: {error}")
    log = log_evidence(run_dir / "ego/planner.log")
    if report.get("task_id") != request["id"]:
        warnings.append("report task identity mismatch; failure time not used")
        report = {}
    failure = next((r.get("simulation_s") for r in report.get("failure_events", []) if r.get("simulation_s") is not None), None)
    result = analyze(states, records, log, request["id"], failure, evaluator, epochs == 1)
    headroom = []
    if candidates and candidates.get("archive_task_id") != request["id"]:
        warnings.append("candidate task identity mismatch; headroom comparison skipped")
        candidates = None
    if candidates:
        for row in candidates.get("rows", []):
            if row.get("full_math_gate", {}).get("passed"):
                margin = candidates["limits"]["ceiling"] - row["full_math_gate"]["height_max"]
                gap = result["tracking_summary"].get("positive_z_error_max_m")
                headroom.append({"trajectory_id": row["trajectory_id"], "nominal_ceiling_margin_m": margin,
                    "historical_positive_z_gap_max_m": gap,
                    "observed_gap_exceeds_margin": gap > margin if gap is not None else None,
                    "scope": "diagnostic only; historical maximum is not a certified counterfactual tracking bound"})
    truths = json_rows(run_dir / "truth.jsonl", warnings)
    matches = [(s, t) for t in truths for s in states if abs(s["source_sim_s"]-t["simulation_s"]) < 1e-9]
    truth_check = {"matched_source_stamps": len(matches), "max_position_difference_m": max(
        (float(np.linalg.norm(np.asarray(s["position"])-t["pose"]["position"])) for s, t in matches), default=None),
        "scope": "same ideal Gazebo source, independent stored representation; not independent localization"}
    ages = [s["age_upper_bound_s"] for s in states if "age_upper_bound_s" in s]
    return {"schema_version": 1, "archive_task_id": request["id"], "source": str(run_dir),
        "kind": "recorded_source_state_and_map_qualification", "clock_epochs": epochs,
        "odometry_count": len(states), "bag_topic_inventory": inventory, "primary_failure_sim_s": failure,
        "state_source": "sidecar ideal Gazebo pose and causal difference velocity; not PX4 measured PVA",
        "recorded_state_availability": {"clock_bracketed": len(ages), "unbracketed": len(states)-len(ages),
            "recorder_age_upper_bound_max_s": max(ages, default=None),
            "duplicate_source_stamps": len(states)-len({(s["epoch"], s["source_stamp_ns"]) for s in states}),
            "source_range_sim_s": [min((s["source_sim_s"] for s in states), default=None),
                                   max((s["source_sim_s"] for s in states), default=None)]},
        "acceleration_state": "unrecorded; never filled from reference or finite-differenced here",
        "tracking_scope": "sampled source-time nominal PV difference before primary failure; not command ACK or continuous bound",
        "truth_representation_crosscheck": truth_check, "qualification": {"full_pva": "unverified",
            "tracking_bound": "uncalibrated", "complete_known_map": "not_qualified_by_this_extractor",
            "future_safe_set": "not_qualified", "terminal_region": "not_qualified",
            "execution_admission": "not_performed"},
        "map_witness": {"voxel_transition_events": log["voxel_events"], "unique_threshold_cells": len(log["voxel_cells"]),
            "inflated_transitions": log["inflation"],
            "scope": "whole log including recovery; local thresholds only; absent cell is not known free"},
        "nominal_ceiling_margin_comparison": headroom, "warnings": warnings+log["warnings"], **result}


def plot_report(result, file):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rows = result["tracking"]
    if not rows:
        print("WARNING: no qualified source-time samples; plot skipped")
        return
    times = [row["source_sim_s"] for row in rows]
    errors = np.asarray([row["position_error_xyz"] for row in rows])
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True, constrained_layout=True)
    fig.suptitle("Original recording: ideal Gazebo odometry vs nominal reference\nSampled evidence only; no flight or admission")
    axes[0].plot(times, np.linalg.norm(errors, axis=1), color="#226fbe", label="Same-source-time position difference")
    axes[0].set_ylabel("Position (m)")
    axes[1].plot(times, errors[:, 2], color="#188462", label="Actual Z - nominal Z")
    margin = next((r for r in result["nominal_ceiling_margin_comparison"] if r["trajectory_id"] == 6), None)
    if margin:
        axes[1].axhline(margin["nominal_ceiling_margin_m"], color="#ba6f18", linestyle="--",
            label="Candidate #6 nominal headroom (comparison only)")
    axes[1].set_ylabel("Z difference (m)")
    fsm = result["fsm"]
    axes[2].scatter([f["sim"] for f in fsm], [f["mixed_time_position_gap_m"] for f in fsm],
        color="#b64d52", marker="x", label="FSM mixed-time position gap")
    aligned = [f for f in fsm if f["same_stamp_position_gap_m"] is not None]
    axes[2].scatter([f["sim"] for f in aligned], [f["same_stamp_position_gap_m"] for f in aligned],
        color="#226fbe", label=f"Same-stamp comparison ({len(fsm)-len(aligned)} unscored omitted)")
    axes[2].set_ylabel("FSM gap (m)")
    axes[2].set_xlabel("Simulation time (s); FSM points use FSM start time")
    for ax in axes:
        if result["primary_failure_sim_s"] is not None:
            ax.axvline(result["primary_failure_sim_s"], color="#687480", linestyle=":", label="Primary failure")
        ax.grid(alpha=.2)
        ax.legend(loc="upper left", fontsize=8)
    file.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(file, dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--drone-root", type=Path, default=Path.home()/"dev/ros2/projects/drone")
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plot", type=Path, help="Optional scientific diagnostic figure")
    args = parser.parse_args()
    data = json.loads(args.candidates.read_text()) if args.candidates else None
    result = run(args.run_dir, args.drone_root, data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    if args.plot:
        try:
            plot_report(result, args.plot)
        except (ImportError, OSError) as error:
            print(f"WARNING: optional plot unavailable: {error}; JSON retained")
    print(json.dumps({"odometry": result["odometry_count"], "tracking": result["tracking_summary"],
        "qualification": result["qualification"]}))


if __name__ == "__main__":
    main()
