#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Inventory legacy sender evidence without admitting or sending trajectories."""
import argparse
from collections import Counter, defaultdict
import copy
import importlib.util
import json
import math
from pathlib import Path


spec = importlib.util.spec_from_file_location("handoff_recorded_tracking",
    Path(__file__).with_name("drone-recorded-tracking.py"))
tracking = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tracking)


def finite(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def identity(row):
    """No task/goal backfill from a folder, nearest time, or another message."""
    task, goal, trajectory = (row.get(k) for k in ("task_id", "goal_id", "trajectory_id"))
    if (not isinstance(task, str) or not task or not isinstance(goal, str) or not goal
            or not isinstance(trajectory, int) or not finite(trajectory) or trajectory < 0):
        return None
    return task, goal, trajectory


def analyze(request, report, curves, telemetry):
    """Metadata joins are sender witnesses, never payload/consumer ACKs."""
    task_id = request.get("id") if isinstance(request.get("id"), str) else None
    keys = Counter(identity(row) for row in curves if identity(row) is not None)
    associated = defaultdict(list)
    rejected = Counter()
    references = 0
    for row in telemetry:
        reference = row.get("reference")
        if not isinstance(reference, dict):
            continue
        references += 1
        key = identity(reference)
        if key is None:
            rejected["reference_identity_missing"] += 1
            continue
        if task_id is None or key[0] != task_id:
            rejected["reference_task_unattributed"] += 1
            continue
        if keys[key] != 1:
            rejected["reference_curve_missing_or_ambiguous"] += 1
            continue
        curve = next(c for c in curves if identity(c) == key)
        recorded, sampled, command = (row.get("simulation_s"), reference.get("simulation_s"),
            reference.get("command_stamp_sim_s"))
        start, received, duration = (curve.get(k) for k in ("start_sim_s", "received_sim_s", "duration_s"))
        if (not all(finite(v) for v in (recorded, sampled, command, start, received, duration))
                or duration <= 0 or not start <= command <= sampled <= recorded
                or not received <= sampled < start + duration):
            rejected["reference_time_unqualified"] += 1
            continue
        arrays = [reference.get(k) for k in ("position", "velocity", "acceleration")]
        if reference.get("mode") != "position_velocity_acceleration" or any(
                not isinstance(a, list) or len(a) != 3 or not all(finite(v) for v in a) for a in arrays):
            rejected["reference_PVA_unqualified"] += 1
            continue
        associated[key].append({"telemetry_source_line": row.get("source_line"),
            "recorded_sim_s": recorded, "reference_sampled_sim_s": sampled,
            "command_stamp_sim_s": command,
            "scope": "local reference stored after SDK await; sampled sim time taken before await, not return time"})
    rows = []
    for curve in curves:
        key = identity(curve)
        reasons = []
        if key is None or task_id is None or key[0] != task_id:
            reasons.append("curve_task_goal_identity_unattributed")
        elif keys[key] != 1:
            reasons.append("curve_identity_ambiguous")
        refs = associated.get(key, []) if not reasons else []
        rows.append({"curve_source_line": curve.get("source_line"),
            "task_id": curve.get("task_id") if isinstance(curve.get("task_id"), str) else None,
            "goal_id": curve.get("goal_id") if isinstance(curve.get("goal_id"), str) else None,
            "trajectory_id": curve.get("trajectory_id") if finite(curve.get("trajectory_id")) else None,
            "local_identity_issues": reasons,
            "curve_record": "observed_sidecar_receipt",
            "curve_identity_scope": "task/goal copied from sidecar active_goal; not carried by native Bspline",
            "post_rpc_reference_snapshots": refs,
            "full_curve_audit_transaction": "unrecorded_by_legacy_streams",
            "px4_ingress_witness": "unrecorded_by_legacy_streams",
            "controller_consumption_witness": "unrecorded_by_legacy_streams",
            "candidate_adoption": "unproven"})
    matching_report = task_id is not None and report.get("task_id") == task_id
    return {"schema_version": 1, "kind": "legacy_handoff_sender_evidence_inventory", "archive_task_id": task_id,
        "scope": "legacy metadata/time joins only; no full PVA state, map, payload equality or execution certification",
        "clock_binding": "legacy_sim_values_only_epoch_unverified_by_this_reader",
        "historical_task_report": {k: copy.deepcopy(report[k]) for k in ("status", "landed", "disarmed")
            if matching_report and isinstance(report.get(k), str if k == "status" else bool)},
        "historical_report_identity_matched": matching_report,
        "rows": rows, "summary": {"curve_records": len(rows),
            "unique_task_attributed_curves": sum(not r["local_identity_issues"] for r in rows),
            "curves_with_post_rpc_reference_snapshots": sum(bool(r["post_rpc_reference_snapshots"]) for r in rows),
            "reference_snapshots": references,
            "associated_PVA_reference_snapshots": sum(len(r["post_rpc_reference_snapshots"]) for r in rows),
            "unassociated_reference_reasons": dict(rejected), "candidate_adoptions_proven": 0},
        "execution_admission_in_this_audit": "not_performed", "dynamic_closed_loop": "not_passed"}


def object_file(path, warnings):
    try:
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise ValueError("expected object")
        return value
    except (OSError, ValueError) as error:
        warnings.append(f"{path.name}: {error}")
        return {}


def run(run_dir):
    warnings = []
    request, report = (object_file(run_dir / name, warnings) for name in ("request.json", "report.json"))
    streams = []
    for name in ("ego/trajectory-events.jsonl", "telemetry.jsonl"):
        try:
            streams.append(tracking.json_rows(run_dir / name, warnings))
        except (OSError, UnicodeError) as error:
            warnings.append(f"{name}: {error}")
            streams.append([])
    return {**analyze(request, report, *streams), "source_run": str(run_dir), "warnings": warnings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.run_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result["summary"], ensure_ascii=False))
    for warning in result["warnings"]:
        print("WARNING: " + warning)


if __name__ == "__main__":
    main()
