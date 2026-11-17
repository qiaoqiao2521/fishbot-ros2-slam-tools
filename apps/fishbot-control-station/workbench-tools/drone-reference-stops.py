#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Original N2 prefixes with S4NU inner-point tails; offline counterfactual only."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path

import numpy as np


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name+".py"))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


STATIC_BOX = [[-10., -10., 0.], [15., 10., 2.2]]
NARROW_BOX = [[-10., -10., 0.], [15., 2.03, 2.2]]


def timing(window, windows):
    start, cut = window["window_start_sim_s"], window["window_end_sim_s"]
    received = window["received_sim_s"]
    duration = sum(p["duration"] for p in window["pieces"])
    values = [start, cut, received, duration, window["duration_s"]]
    if (not np.all(np.isfinite(values)) or duration <= 0 or abs(cut-start-duration) > 1e-8
            or abs(duration-window["duration_s"]) > 1e-8 or abs(start-received) > 1e-8):
        raise ValueError("reference_prefix_time_mismatch")
    later = []
    for other in windows:
        try:
            stamp = float(other["received_sim_s"])
            if np.isfinite(stamp) and stamp > received:
                later.append(stamp)
        except (ValueError, TypeError, KeyError):
            continue  # A damaged neighbour must not invalidate this window.
    next_received = min(later, default=None)
    return {"start_sim_s": start, "cut_sim_s": cut, "prefix_duration_s": duration,
        "next_curve_received_sim_s": next_received,
        "replaced_before_cut": next_received is not None and next_received < cut,
        "execution_scope": "counterfactual reference prefix; original replacement retained; no execution evidence"}


def box_faces(box):
    faces = []
    for axis in range(3):
        normal = np.eye(3)[axis]
        faces += [np.r_[normal, -box[1][axis]].tolist(), np.r_[-normal, box[0][axis]].tolist()]
    return faces


def static_gate(row, box, limits, audit):
    prefix = np.asarray(row["full_math_gate"]["pieces"][0]["start_pva"])
    request = {**row["request"], "initial_pva": prefix.tolist(), "required_continuity_order": 2,
        "corridor": [box_faces(box)], "integral_resolution": 16}
    return audit.audit_trajectory({"native_success": True, "pieces": row["prefix_pieces"]+row["native"]["pieces"]},
        request, [], limits, box)


def replay_cases(row, context, limits, replay, audit, handoff, *, box=None):
    # Reuse existing scenarios. The negative comparison is deliberately edited,
    # because a formerly rejected baseline can become a math-pass candidate.
    rejected = copy.deepcopy(row)
    rejected["native"]["pieces"][0]["coefficients_descending"][0][-1] += 1.
    scenarios = replay.fixture_scenarios(row, rejected, context, handoff)
    if box is not None:
        for events in scenarios.values():
            for event in events:
                if isinstance(event.get("snapshot"), dict):
                    event["snapshot"]["box"] = copy.deepcopy(box)
    results = []
    for name, events in scenarios.items():
        engine = replay.Replay(context, limits, audit, handoff)
        steps = [{"now_sim_s": e["now_sim_s"] if np.isfinite(e["now_sim_s"]) else None,
                  "result": engine.step(copy.deepcopy(e))} for e in events]
        results.append({"scenario": name, "events": steps, "selection_stats": engine.server.stats()})
    return {"scenarios": results, "state_source": "ideal full reference PVA; not measured vehicle",
        "map_source": "declared static configuration-space fixture; not original/future GridMap",
        "box_fixture": copy.deepcopy(STATIC_BOX if box is None else box),
        "terminal_scope": "finite half-second forecast coverage, not invariant terminal set",
        "execution_admission": "not_performed"}


def run(data, root, old_native, new_native, *, max_iterations=60):
    candidates, geometry, replay = [load(n) for n in
        ("drone-stop-candidates", "drone-stop-geometry", "drone-committed-replay")]
    audit, handoff = candidates.load_modules(root)
    limits = data["limits"]
    context = {"task_id": data["archive_task_id"], "scene_revision": "reference-static-box-v1",
        "clock_id": "historical-reference-counterfactual-epoch-1", "frame_id": "scene_enu_m"}
    rows = []
    for window in data["windows"]:
        row = {"trajectory_id": window.get("trajectory_id"), "execution_admission": "not_performed"}
        rows.append(row)
        try:
            if window.get("recorded_task_id") != data["archive_task_id"] or window.get("task_attribution") != "recorded":
                row.update(status="unscored", reason="source_task_identity_unrecorded_or_mismatch"); continue
            if not window.get("conversion", {}).get("passed"):
                row.update(status="unscored", reason="source_conversion_not_verified"); continue
            row["timing"] = timing(window, data["windows"])
            baseline = candidates.compare(window, limits, [3.5, 1., .4], old_native, audit, handoff)
            row["baseline"] = baseline
            if baseline["status"] != "generated":
                row.update(status="unscored", reason=baseline.get("reason", "baseline_unavailable")); continue
            row["baseline_static_box_gate"] = static_gate(baseline, STATIC_BOX, limits, audit)
            head = np.asarray(baseline["request"]["initial_pva"])
            row["narrow_box_cut_inside"] = bool(np.all(head[:, 0] >= NARROW_BOX[0]) and np.all(head[:, 0] <= NARROW_BOX[1]))
            base = {**baseline["request"], "integral_resolution": 16, "corridor": [box_faces(STATIC_BOX)]}
            row["search"] = geometry.search(base, STATIC_BOX, limits, new_native, audit,
                y_inner=True, max_iterations=max_iterations)
            if row["search"]["status"] != "audited":
                row.update(status="unscored", reason=row["search"].get("reason", "search_unavailable")); continue
            proposed = row["search"]["candidate"]
            candidate = candidates.compare(window, limits, proposed["request"]["axis_stop_durations_xyz"],
                new_native, audit, handoff, tail_request=proposed["request"])
            row.update(status=candidate["status"], candidate=candidate)
            if candidate["status"] != "generated":
                row["reason"] = candidate.get("reason", "candidate_generation_failed"); continue
            row["full_static_box_gate"] = static_gate(candidate, STATIC_BOX, limits, audit)
            row["narrow_box_gate"] = static_gate(candidate, NARROW_BOX, limits, audit)
            row["counterfactual_replay"] = replay_cases(candidate, context, limits, replay, audit, handoff)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
            row.update(status="unscored", reason=str(error))
            print(f"WARNING: reference {row['trajectory_id']}: {error}")
    generated = [r for r in rows if r["status"] == "generated"]
    return {"schema_version": 1, "archive_task_id": data["archive_task_id"],
        "kind": "offline_original_reference_prefix_S4NU_inner_point_comparison", "clock": data["clock"],
        "limits": limits, "context": context, "static_box_fixture": STATIC_BOX, "narrow_box_comparison": NARROW_BOX,
        "summary": {"source_windows": len(rows), "generated": len(generated),
            "baseline_math_passed": sum(r.get("baseline", {}).get("full_math_gate", {}).get("passed", False) for r in rows),
            "full_math_passed": sum(r["candidate"]["full_math_gate"]["passed"] for r in generated),
            "full_static_box_passed": sum(r["full_static_box_gate"]["passed"] for r in generated),
            "unscored": sum(r["status"] == "unscored" for r in rows)},
        "scope": "all original windows, same recorded reference cut PVA/J; +Y search domain retained; no trajectory/flight success-rate ranking",
        "actual_qualification": {"state": "reference PVA/J only; actual full state unknown", "map": "unverified",
            "terminal_region": "unverified", "deadline": "unverified; offline search wall time retained",
            "tracking_and_adoption": "not_performed", "dynamic_closed_loop": "not_passed"},
        "execution_admission": "not_performed", "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primitives", type=Path, required=True)
    parser.add_argument("--drone-root", type=Path, default=Path.home()/"dev/ros2/projects/drone")
    parser.add_argument("--old-native", type=Path, default=Path.home()/".cache/ros2-drone/minco-probe/minco_probe")
    parser.add_argument("--native", type=Path, default=Path.home()/".cache/ros2-drone/minco-s4-knots/minco_s4_knots")
    parser.add_argument("--max-iterations", type=int, default=60)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(json.loads(args.primitives.read_text()), args.drone_root, args.old_native, args.native,
                 max_iterations=args.max_iterations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps(result["summary"]))


if __name__ == "__main__":
    main()
