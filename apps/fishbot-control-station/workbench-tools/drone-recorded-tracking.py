#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Read original odometry/FSM evidence for M2; never select or send control."""
import argparse
import bisect
from collections import Counter
import importlib.util
import json
from pathlib import Path
import re
import subprocess

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
    result = {"fsm": [], "reanchor": [], "callbacks": [], "inflation": [], "voxel_events": 0,
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
        kind = ("fsm" if "FSMStart sim=" in line else "reanchor" if "FSMReanchor sim=" in line
                else "callbacks" if "MapCallback kind=" in line else None)
        if kind:
            fields = {}
            for key, value in re.findall(r"(\w+)=(\[[^\]]*\]|[^ ]+)", line):
                try:
                    fields[key] = json.loads(value)
                except ValueError:
                    fields[key] = value
            required = (("sim", "odom_source", "odom_p", "odom_v", "ref_p") if kind == "fsm"
                        else ("sim", "odom_source") if kind == "reanchor" else ("kind", "end"))
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


def predict_pv(anchor, target_s, model, previous=None):
    """Math baseline only. Caller separately qualifies available input frames.

    This function cannot inspect the oracle. A is an explicit model assumption
    or past-velocity estimate, never an observed acceleration/PVA contract.
    """
    dt = target_s - anchor["source_sim_s"]
    if not np.isfinite(dt) or dt < 0:
        return None
    position, velocity = np.asarray(anchor["position"]), np.asarray(anchor["velocity"])
    acceleration = np.zeros(3)
    if model == "hold":
        return {"position": position.tolist(), "velocity": velocity.tolist(), "model_acceleration": None}
    if model == "causal_acceleration":
        if previous is None or not previous["source_sim_s"] < anchor["source_sim_s"]:
            return None
        acceleration = (velocity-np.asarray(previous["velocity"]))/(anchor["source_sim_s"]-previous["source_sim_s"])
    elif model != "constant_velocity":
        return None
    return {"position": (position+velocity*dt+.5*acceleration*dt**2).tolist(),
            "velocity": (velocity+acceleration*dt).tolist(), "model_acceleration": acceleration.tolist()}


def usable_pv(state):
    try:
        p, v = np.asarray(state["position"]), np.asarray(state["velocity"])
        return (state.get("epoch") == 0 and p.shape == v.shape == (3,)
            and all(state.get(k) == "world" for k in ("frame_id", "velocity_frame_id"))
            and np.all(np.isfinite(np.r_[p, v, state["source_sim_s"]]))
            and abs(int(state["source_stamp_ns"])/1e9-state["source_sim_s"]) < 1e-9)
    except (ValueError, KeyError, TypeError):
        return False


def recorded_availability(state):
    value = state.get("available_by_sim_s")
    return value if isinstance(value, (float, int)) and np.isfinite(value) and value >= state["source_sim_s"] else np.inf


def stopping_necessary(position, velocity, box, acceleration):
    """Optimistic per-face necessary bounds, never a joint viability certificate.

    The comparison allows an instantaneous switch to the full acceleration
    budget on each face separately, conditional on the supplied norm bound.
    Initial A/J continuity can restrict this model further; passing does not
    construct a feasible brake or establish the real vehicle's acceleration.
    """
    try:
        p, v, bounds = (np.asarray(value, dtype=float) for value in (position, velocity, box))
        limit = float(acceleration)
        if (p.shape != (3,) or v.shape != (3,) or bounds.shape != (2, 3)
                or not np.all(np.isfinite(np.r_[p, v, bounds.ravel(), limit]))
                or limit <= 0 or np.any(bounds[0] >= bounds[1])):
            raise ValueError("finite PV, ordered box and positive acceleration required")
    except (ValueError, TypeError):
        return {"status": "unscored", "reason": "invalid_pv_box_or_acceleration"}
    faces = []
    for axis, name in enumerate("xyz"):
        for side, sign in (("lower", -1), ("upper", 1)):
            distance = float(p[axis]-bounds[0, axis] if sign < 0 else bounds[1, axis]-p[axis])
            outward = float(max(0., sign*v[axis]))
            minimum_distance = outward**2/(2*limit)
            margin = distance-minimum_distance
            faces.append({"face": name+"_"+side, "distance_m": distance,
                "outward_speed_m_s": outward, "optimistic_minimum_stop_distance_m": minimum_distance,
                "distance_margin_m": margin,
                "required_deceleration_m_s2": outward**2/(2*distance) if distance > 0 else 0. if outward == 0 and distance == 0 else None,
                "status": "outside" if distance < 0 else "necessary_reject" if margin < 0 else "not_ruled_out"})
    rejected = [f["face"] for f in faces if f["status"] != "not_ruled_out"]
    return {"status": "necessary_reject" if rejected else "not_ruled_out", "rejected_faces": rejected,
        "faces": faces, "joint_viability": "not_proven", "initial_acceleration_and_jerk": "unrecorded"}


def axis_stop_fixture(pv, box, limits, executable, audit, handoff):
    """Reuse the native axis brake with explicit zero-A/J assumptions only."""
    head = np.column_stack([pv["position"], pv["velocity"], np.zeros(3)])
    corridor = []
    for axis in range(3):
        normal = np.eye(3)[axis]
        corridor.extend([np.r_[normal, -box[1][axis]].tolist(), np.r_[-normal, box[0][axis]].tolist()])
    request = handoff.axis_stop_request({"id": "pv_stop_fixture", "initial_pva": head.tolist(),
        "original_local_target": head[:, 0].tolist(), "corridor": [corridor], "integral_resolution": 16}, [3.5, 1., .4])
    request["initial_condition_scope"] = "initial A=J=0, neither measured nor a live handoff contract"
    return audit_axis_request(request, box, limits, executable, audit)


def audit_axis_request(request, box, limits, executable, audit, perform_audit=True, exchange=None):
    """Reuse native generation; an optimizer may request generation-only probes."""
    try:
        if exchange is None:
            result = subprocess.run([str(executable)], input=json.dumps(request)+"\n", text=True,
                                    capture_output=True, timeout=10)
            outputs = [json.loads(line.split(" ", 1)[1]) for line in result.stdout.splitlines() if line.startswith("MincoResult ")]
            native = outputs[-1] if outputs else {"native_success": False}
            code = result.returncode
        else:
            native = exchange(request)
            code = 0
        if code or not native.get("native_success"):
            raise ValueError(f"native axis brake unavailable, exit={code}: {native.get('error', 'no successful reply')}")
        return {"status": "audited" if perform_audit else "generated",
            "assumption": request.get("initial_condition_scope", "supplied input A/J, measurement provenance unqualified"),
            "axis_stop_durations_xyz": request["axis_stop_durations_xyz"], "request": request, "native": native,
            **({"audit": audit.audit_trajectory(native, request, [], limits, box)} if perform_audit else {}),
            "occupancy": "not_checked; explicit static box only", "execution_admission": "not_performed"}
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, IndexError) as error:
        return {"status": "unscored", "reason": str(error)}


def stopping_evidence(states, forecast, reanchors, failure_s, fixture, brake=None):
    """Compare stale, causal-predicted and retrospective PV in an explicit box."""
    cases = [r for r in forecast["cases"] if r["kind"] == "fsm"]
    cases = [{**r, "event_source_line": None} for r in cases]
    excluded = Counter()
    for event in reanchors:
        now = event["sim"]
        parent = next((r for r in reversed(cases) if r["kind"] == "fsm"
            and r["forecast_at_sim_s"] <= now
            and abs(r["input_state"]["source_sim_s"]-event["odom_source"]) < 1e-9), None)
        if (parent is None or failure_s is None or not np.isfinite(failure_s) or not np.isfinite(now) or now >= failure_s):
            excluded["reanchor_without_verified_prefailure_fsm_source"] += 1
            continue
        # A reanchor has only the consumed source stamp. Link its PV to a
        # numerically verified earlier FSM, not an arbitrary same-stamp value.
        future = [s for s in states if usable_pv(s) and round(now*1e9) <= int(s["source_stamp_ns"]) < round(failure_s*1e9)]
        next_stamp = min((int(s["source_stamp_ns"]) for s in future), default=None)
        matches = [s for s in future if int(s["source_stamp_ns"]) == next_stamp]
        if not matches or any(s[key] != matches[0][key] for s in matches for key in ("position", "velocity")):
            excluded["reanchor_without_unambiguous_prefailure_source_oracle"] += 1
            continue
        oracle = matches[0]
        anchor, previous = parent["input_state"], parent["previous_available_state"]
        cases.append({"kind": "reanchor", "forecast_at_sim_s": now, "input_state": anchor,
            "previous_available_state": previous, "oracle_source_sim_s": oracle["source_sim_s"],
            "oracle_source_offset_s": oracle["source_sim_s"]-now,
            "oracle_position": oracle["position"], "oracle_velocity": oracle["velocity"],
            "event_source_line": event["source_line"], "input_evidence": "reanchor stamp linked to earlier verified FSM PV; same past-V pair retained",
            "models": {model: {"status": "scored", **prediction} if prediction else {"status": "unscored"}
                for model in forecast["models"] if (prediction := predict_pv(anchor, oracle["source_sim_s"], model, previous)) is not None}})
    rows = []
    last_fsm_time = max((r["forecast_at_sim_s"] for r in cases if r["kind"] == "fsm"), default=None)
    for case in cases:
        variants = {"cached_source_pv": case["input_state"],
            **{k: v for k, v in case["models"].items() if k != "hold" and v["status"] == "scored"},
            "retrospective_source_pv": {"position": case["oracle_position"], "velocity": case["oracle_velocity"]}}
        row = {key: case[key] for key in ("kind", "forecast_at_sim_s", "oracle_source_sim_s", "oracle_source_offset_s", "input_evidence")}
        row.update(source_sim_s=case["input_state"]["source_sim_s"],
            prediction_evaluated_sim_s=case["oracle_source_sim_s"], event_source_line=case["event_source_line"], variants={})
        for name, pv in variants.items():
            row["variants"][name] = {"position": pv["position"], "velocity": pv["velocity"],
                "pv_at_sim_s": case["input_state"]["source_sim_s"] if name == "cached_source_pv" else case["oracle_source_sim_s"],
                "provenance": "recorded old source" if name == "cached_source_pv" else "retrospective source, scoring only" if name == "retrospective_source_pv" else "causal model, not a measurement",
                "necessary": stopping_necessary(pv["position"], pv["velocity"], fixture["box"], fixture["limits"]["acceleration"])}
            if brake and (case["kind"] == "reanchor" or case["forecast_at_sim_s"] == last_fsm_time):
                row["variants"][name]["conditional_axis_stop"] = brake(pv)
        rows.append(row)
    return {"kind": "offline_per_face_necessary_stopping_bound", "box": fixture["box"], "limits": fixture["limits"],
        "box_scope": "hand-defined historical test fixture, not reconstructed current known free space",
        "bound_scope": "conditional on supplied norm-acceleration bound; optimistic instantaneous full budget on each face separately; passing is not joint viability",
        "oracle_scope": "retrospective only; next source timestamp and offset disclosed, all formulas evaluated there; future PV never used by predictions or control",
        "dynamic_occupancy": "unqualified", "execution_admission": "not_performed", "excluded": dict(excluded), "cases": rows}


def forecast_evidence(states, tracking, fsm, failure_s, single_epoch=True):
    """Fixed baselines; future source samples are scoring-only, not inputs."""
    models = ("hold", "constant_velocity", "causal_acceleration")
    horizons = (0., .04, .08, .16, .24)
    failure_valid = isinstance(failure_s, (int, float)) and np.isfinite(failure_s)
    eligible = [s for s in states if single_epoch and usable_pv(s)]
    # A repeated source stamp with conflicting PV has no unique oracle/input.
    groups = {}
    for state in eligible:
        groups.setdefault(int(state["source_stamp_ns"]), []).append(state)
    ambiguous = {stamp for stamp, values in groups.items() if any(
        v[key] != values[0][key] for v in values for key in ("position", "velocity"))}
    unique = sorted((min(values, key=recorded_availability)
                     for stamp, values in groups.items() if stamp not in ambiguous), key=lambda s: s["source_sim_s"])
    times_ns = [int(s["source_stamp_ns"]) for s in unique]
    cases, rejected = [], Counter()
    rejected["input_frame_state_or_epoch_unverified"] = len(states)-len(eligible)

    def score(anchor, now, target, kind, horizon=None):
        index = bisect.bisect_left(times_ns, round(target*1e9))
        if index == len(unique) or not failure_valid or unique[index]["source_sim_s"] >= failure_s:
            rejected[kind+"_oracle_missing_or_after_failure"] += 1
            return
        oracle = unique[index]
        previous = next((s for s in reversed(unique) if s["source_sim_s"] < anchor["source_sim_s"]
            and recorded_availability(s) <= now), None)
        row = {"kind": kind, "requested_horizon_from_available_s": horizon,
            "forecast_at_sim_s": now, "requested_target_sim_s": target,
            "input_state": anchor, "previous_available_state": previous,
            "input_evidence": "FSM logged consumed PV" if kind == "fsm" else "recorder clock upper bound",
            "oracle_source_sim_s": oracle["source_sim_s"],
            "oracle_source_offset_s": oracle["source_sim_s"]-target,
            "realized_dt_from_source_s": oracle["source_sim_s"]-anchor["source_sim_s"],
            "oracle_position": oracle["position"], "oracle_velocity": oracle["velocity"], "models": {}}
        # Each formula defines a continuous forecast from the initial PV. Score
        # it at the first actual source timestamp at/after the requested time;
        # do not interpolate oracle values into the forecast or hide the offset.
        for model in models:
            prediction = predict_pv(anchor, oracle["source_sim_s"], model, previous)
            if prediction is None:
                row["models"][model] = {"status": "unscored", "reason": "past_velocity_pair_unavailable"}
                continue
            error = np.asarray(prediction["position"])-oracle["position"]
            row["models"][model] = {"status": "scored", **prediction,
                "position_error_xyz": error.tolist(), "position_error_m": float(np.linalg.norm(error)),
                "velocity_error_m_s": float(np.linalg.norm(np.asarray(prediction["velocity"])-oracle["velocity"]))}
        cases.append(row)

    focus = {int(r["source_stamp_ns"]) for r in tracking}
    for anchor in unique:
        now = recorded_availability(anchor)
        if int(anchor["source_stamp_ns"]) not in focus or not np.isfinite(now):
            continue
        for horizon in horizons:
            score(anchor, now, now+horizon, "recorder", horizon)
    for event in fsm:
        now = event["sim"]
        if not np.isfinite(now) or not failure_valid or now >= failure_s:
            rejected["fsm_at_or_after_failure"] += 1
            continue
        anchor = next((s for s in unique if abs(s["source_sim_s"]-event["odom_source"]) < 1e-9), None)
        match = np.asarray(event.get("bag_pv_match_error", [np.inf]))
        if anchor is None or anchor["source_sim_s"] > now or not np.all(np.isfinite(match)) or np.max(match) > 1e-10:
            rejected["fsm_consumed_pv_unverified"] += 1
            continue
        score(anchor, now, now, "fsm")

    summaries = []
    for kind, horizon in [("fsm", None)]+[("recorder", h) for h in horizons]:
        subset = [r for r in cases if r["kind"] == kind and r["requested_horizon_from_available_s"] == horizon]
        summary = {"kind": kind, "requested_horizon_from_available_s": horizon, "cases": len(subset), "models": {},
            "all_models_scored_cases": sum(all(r["models"][m]["status"] == "scored" for m in models) for r in subset),
            "realized_dt_from_source_range_s": [min((r["realized_dt_from_source_s"] for r in subset), default=None),
                                                max((r["realized_dt_from_source_s"] for r in subset), default=None)],
            "oracle_offset_max_s": max((r["oracle_source_offset_s"] for r in subset), default=None)}
        for model in models:
            values = [r["models"][model] for r in subset if r["models"][model]["status"] == "scored"]
            errors = np.array([v["position_error_m"] for v in values])
            summary["models"][model] = {"scored": len(values), "unscored": len(subset)-len(values),
                "position_rms_m": float(np.sqrt(np.mean(errors**2))) if len(errors) else None,
                "position_p95_m": float(np.quantile(errors, .95)) if len(errors) else None,
                "position_max_m": float(errors.max()) if len(errors) else None}
        summaries.append(summary)
    return {"kind": "offline_pv_prediction_fixed_baselines", "models": list(models), "horizons_sim_s": list(horizons),
        "scope": "same original flight, ideal Gazebo PV; no control, measured A, calibration or invariant bound",
        "model_acceleration_scope": "CV zero / CA past-V secant; neither is measured acceleration",
        "hold_scope": "cached PV baseline, not a kinematically consistent executable trajectory",
        "oracle_scope": "next actual PV source timestamp, offset disclosed; future PV used only to score",
        "input_scope": "recorder availability and explicit FSM consumption are distinct evidence paths",
        "ambiguous_source_stamps": len(ambiguous), "excluded": dict(rejected), "summary": summaries, "cases": cases}


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
        if failure_s is None or not np.isfinite(failure_s) or time >= failure_s:
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


def run(run_dir, root, candidates=None, forecast=False, stopping_fixture=None, native=None):
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
    if not isinstance(failure, (float, int)) or not np.isfinite(failure):
        warnings.append("primary failure time unavailable/nonfinite; pre-failure scoring unqualified")
        failure = None
    result = analyze(states, records, log, request["id"], failure, evaluator, epochs == 1)
    if forecast or stopping_fixture:
        result["forecast"] = forecast_evidence(states, result["tracking"], result["fsm"], failure, epochs == 1)
    if stopping_fixture:
        try:
            fixture = json.loads(stopping_fixture.read_text())
            if stopping_necessary([0.]*3, [0.]*3, fixture["box"], fixture["limits"]["acceleration"])["status"] == "unscored":
                raise ValueError("invalid stopping fixture")
            brake = None
            if native:
                audit, handoff = load("stop_candidates", Path(__file__).with_name("drone-stop-candidates.py")).load_modules(root)
                brake = lambda pv: axis_stop_fixture(pv, fixture["box"], fixture["limits"], native, audit, handoff)
            result["stopping"] = {"fixture_source": str(stopping_fixture), **stopping_evidence(
                states, result["forecast"], log["reanchor"], failure, fixture, brake)}
        except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
            warnings.append(f"optional stopping analysis unavailable: {error}")
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


def plot_forecast(result, file):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    forecast = result.get("forecast")
    if not forecast or not forecast["cases"]:
        print("WARNING: no forecast cases; optional forecast plot skipped")
        return
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), constrained_layout=True)
    fig.suptitle("Original-run PV prediction: fixed causal baselines\nIdeal Gazebo pose / differentiated V; no measured A or control")
    profiles = [s for s in forecast["summary"] if s["kind"] == "recorder"]
    fsm = [r for r in forecast["cases"] if r["kind"] == "fsm"]
    for model, color, label in (("hold", "#7c8795", "Cached PV"),
            ("constant_velocity", "#226fbe", "Constant velocity"),
            ("causal_acceleration", "#188462", "Past-V acceleration estimate")):
        axes[0].plot([s["requested_horizon_from_available_s"] for s in profiles],
            [s["models"][model]["position_rms_m"] for s in profiles], "o-", color=color, label=label)
        valid = [r for r in fsm if r["models"][model]["status"] == "scored"]
        axes[1].plot([r["forecast_at_sim_s"] for r in valid],
            [r["models"][model]["position_error_m"] for r in valid], "o-", color=color, label=label)
    axes[0].set_xlabel("Horizon requested after recorder availability (s)")
    axes[0].set_ylabel("Position RMS (m)")
    axes[1].set_xlabel("FSM start time (s); scores use next actual source timestamp")
    axes[1].set_ylabel("Position error (m)")
    for ax in axes:
        ax.set_yscale("log")
        ax.grid(alpha=.2, which="both")
        ax.legend(fontsize=8)
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
    parser.add_argument("--forecast", action="store_true", help="Evaluate fixed PV prediction baselines offline")
    parser.add_argument("--forecast-plot", type=Path, help="Optional forecast comparison figure; requires --forecast")
    parser.add_argument("--stopping-fixture", type=Path, help="Explicit historical JSON containing box and limits; offline only")
    parser.add_argument("--native", type=Path, help="Optional existing MINCO executable for zero-A/J axis-stop fixture audit")
    args = parser.parse_args()
    data = json.loads(args.candidates.read_text()) if args.candidates else None
    result = run(args.run_dir, args.drone_root, data, args.forecast, args.stopping_fixture, args.native)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    if args.plot:
        try:
            plot_report(result, args.plot)
        except (ImportError, OSError) as error:
            print(f"WARNING: optional plot unavailable: {error}; JSON retained")
    if args.forecast_plot:
        try:
            plot_forecast(result, args.forecast_plot)
        except (ImportError, OSError) as error:
            print(f"WARNING: optional forecast plot unavailable: {error}; JSON retained")
    print(json.dumps({"odometry": result["odometry_count"], "tracking": result["tracking_summary"],
        "qualification": result["qualification"]}))


if __name__ == "__main__":
    main()
