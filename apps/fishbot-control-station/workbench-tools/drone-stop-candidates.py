#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Offline reference-prefix/MINCO-stop comparison. No control or ROS client."""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import subprocess
import time

import numpy as np
from numpy.polynomial import polynomial as poly


def load_modules(root):
    spec = importlib.util.spec_from_file_location("trajectory_primitives", Path(__file__).with_name("drone-trajectory-primitives.py"))
    primitives = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(primitives)
    _, audit = primitives.reuse(root)
    import replay_minco_handoff
    return audit, replay_minco_handoff


def preview(native, audit):
    points = []
    for piece in native["pieces"]:
        power = audit.normalized_power(piece)
        points.extend(poly.polyval(np.linspace(0., 1., 17), power).T.tolist())
    return points


def compare(window, limits, stopping_times, executable, audit, handoff):
    if window.get("task_attribution") != "recorded":
        return {"trajectory_id": window["trajectory_id"], "status": "unscored",
                "reason": "source_task_identity_unrecorded", "execution_admission": "not_performed"}
    state = np.asarray(window["terminal_pvaj_xyz_columns"])
    request = handoff.axis_stop_request({"initial_pva": state[:, :3].tolist(),
        "original_local_target": state[:, 0].tolist(), "corridor": []}, stopping_times, state[:, 3].tolist())
    request["id"] = f"reference-{window['trajectory_id']}-stop"
    started = time.perf_counter()
    try:
        result = subprocess.run([str(executable)], input=json.dumps(request)+"\n", text=True,
                                capture_output=True, timeout=10)
        outputs = [json.loads(line.split(" ", 1)[1]) for line in result.stdout.splitlines() if line.startswith("MincoResult ")]
        native = outputs[-1] if outputs else {"native_success": False}
        if result.returncode or not native.get("native_success"):
            return {"trajectory_id": window["trajectory_id"], "status": "generation_failed", "request": request,
                    "reason": native.get("error", f"native exit={result.returncode}"),
                    "native_log": result.stdout+result.stderr, "execution_admission": "not_performed"}
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        return {"trajectory_id": window["trajectory_id"], "status": "generation_failed", "reason": str(error),
                "request": request, "execution_admission": "not_performed"}
    process_ms = (time.perf_counter()-started)*1000
    # Original independent V/A/ceiling gates; horizontal space is NOT certified.
    box = [[-np.inf, -np.inf, -np.inf], [np.inf, np.inf, limits["ceiling"]]]
    scored_request = {**request, "corridor": [[[0., 0., 1., -limits["ceiling"]]]], "integral_resolution": 16}
    started = time.perf_counter()
    tail_score = audit.audit_trajectory(native, scored_request, [], limits, box)
    composite = {"native_success": True, "pieces": window["pieces"]+native["pieces"]}
    composite_request = {**scored_request, "mode": "recorded_c2_prefix_and_c3_stop",
        "initial_pva": np.asarray(window["initial_pvaj_xyz_columns"])[:, :3].tolist(),
        "initial_jerk": np.asarray(window["initial_pvaj_xyz_columns"])[:, 3].tolist(),
        "required_continuity_order": 2}
    full_score = audit.audit_trajectory(composite, composite_request, [], limits, box)
    first = audit.normalized_power(native["pieces"][0])
    head = np.column_stack([poly.polyval(0., audit.derivative(first, native["pieces"][0]["duration"], i)) for i in range(4)])
    join = np.linalg.norm(head-state, axis=0)
    joined = bool(np.max(join) <= 1e-8)
    failures = list(full_score["failed_checks"])
    if not joined:
        failures.append("cut_pvaj")
    if not tail_score["passed"]:
        failures.extend("tail_"+key for key in tail_score["failed_checks"])
    return {"trajectory_id": window["trajectory_id"], "recorded_task_id": window["recorded_task_id"],
        "recorded_goal_id": window["recorded_goal_id"], "status": "generated",
        "source_received_sim_s": window["received_sim_s"], "start_sim_s": window["window_start_sim_s"],
        "cut_sim_s": window["window_end_sim_s"], "prefix_duration_s": window["duration_s"],
        "end_sim_s": window["window_end_sim_s"]+sum(p["duration"] for p in native["pieces"]),
        "initial_jerk_source": "incoming reference prefix left limit; not measured vehicle jerk",
        "request": request, "native": native, "prefix_pieces": window["pieces"],
        "full_math_gate": {**full_score, "passed": not failures, "failed_checks": sorted(set(failures))},
        "tail_math_gate": tail_score, "cut_pvaj_error": join.tolist(), "cut_c3_passed": joined,
        "prefix_continuity": "C2; original jerk jumps retained", "full_continuity_claim": "C2",
        "math_gate_scope": "V/A/ceiling and boundary only; horizontal corridor and dynamic occupancy unverified",
        "offline_wall_ms": {"native_compute": native.get("elapsed_ms"), "native_process_roundtrip": process_ms,
                            "audit": (time.perf_counter()-started)*1000},
        "preview_points": preview(composite, audit),
        "occupancy": {"status": "unverified", "reason": "No current per-curve GridMap or future terminal-region certificate"},
        "execution_admission": "not_performed"}


def run(source, root, executable, stopping_times):
    data = json.loads(source.read_text())
    audit, handoff = load_modules(root)
    limits = data.get("limits")
    if not limits:
        return {"schema_version": 1, "archive_task_id": data["archive_task_id"], "rows": [],
                "summary": {"reason": "original_candidate_limits_unavailable"}, "execution_admission": "not_performed"}
    rows = []
    for window in data["windows"]:
        if window.get("recorded_task_id") not in (None, data["archive_task_id"]):
            rows.append({"trajectory_id": window["trajectory_id"], "status": "unscored", "reason": "source_task_identity_mismatch"})
        elif not window.get("conversion", {}).get("passed"):
            rows.append({"trajectory_id": window["trajectory_id"], "status": "unscored", "reason": "source_conversion_not_verified"})
        else:
            rows.append(compare(window, limits, stopping_times, executable, audit, handoff))
    generated = [row for row in rows if row["status"] == "generated"]
    return {"schema_version": 1, "archive_task_id": data["archive_task_id"],
        "kind": "offline_reference_prefix_axis_stop", "clock": data["clock"],
        "source": str(source), "limits": limits, "axis_stop_durations_xyz": stopping_times,
        "scope": "Offline counterfactual only. Reference following and stopping have different objectives; no task success-rate ranking",
        "math_gate_scope": "V/A/ceiling and boundary only; auditor corridor certificate is ceiling-only here",
        "summary": {"source_windows": len(data["windows"]), "generated": len(generated),
            "math_passed": sum(row["full_math_gate"]["passed"] for row in generated),
            "cut_c3_passed": sum(row["cut_c3_passed"] for row in generated),
            "unscored": sum(row["status"] == "unscored" for row in rows),
            "generation_failed": sum(row["status"] == "generation_failed" for row in rows),
            "rejection_reasons": dict(Counter(reason for row in generated for reason in row["full_math_gate"]["failed_checks"])),
            "occupancy_verified": False, "execution_admission": "not_performed"}, "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primitives", type=Path, required=True)
    parser.add_argument("--drone-root", type=Path, default=Path.home()/"dev/ros2/projects/drone")
    parser.add_argument("--native", type=Path, default=Path.home()/".cache/ros2-drone/minco-probe/minco_probe")
    parser.add_argument("--stopping-times", type=float, nargs=3, default=[3.5, 1., .4])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.primitives, args.drone_root, args.native, args.stopping_times)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2)+"\n")
    print(json.dumps(report["summary"]))
