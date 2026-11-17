#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Offline earlier reference cuts in the original declared narrow-box fixture."""
import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name+".py"))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


HORIZONS = [.1, .2, .4, .6, .8]


def relative_to(cut, event):
    if event is None:
        return "unknown"
    return "before" if cut < event else "after" if cut > event else "at"


def failure_evidence(report, task_id):
    if not isinstance(report, dict) or report.get("task_id") != task_id or report.get("mode") != "simulation":
        return {"status": "unverified", "reason": "failure_report_identity_or_clock_unknown", "simulation_s": None}
    events = report.get("failure_events")
    if not isinstance(events, list):
        return {"status": "unverified", "reason": "failure_events_unavailable", "simulation_s": None}
    times = []; invalid = 0
    for event in events:
        try:
            stamp = float(event["simulation_s"])
            if not np.isfinite(stamp): raise ValueError("nonfinite failure time")
            times.append(stamp)
        except (ValueError, TypeError, KeyError):
            invalid += 1
    return {"status": "recorded" if times and not invalid else "unverified",
        "simulation_s": min(times) if times and not invalid else None, "invalid_events": invalid,
        "scope": "first recorded failure event, not exact fault onset or online readiness"}


def run(data, failure_report, root, native, *, trajectory_ids=(4,7), horizons=HORIZONS,
        z_domain=(.1,1.2), max_iterations=60):
    primitives, reference, geometry, candidates, time_study, replay = [load(n) for n in
        ("drone-trajectory-primitives", "drone-reference-stops", "drone-stop-geometry",
         "drone-stop-candidates", "drone-stop-time-study", "drone-committed-replay")]
    curve, audit = primitives.reuse(root)
    _, handoff = candidates.load_modules(root)
    windows = time_study.index_rows(data["windows"], "primitives")
    failure = failure_evidence(failure_report, data["archive_task_id"])
    limits = data["limits"]; rows = []
    context = {"task_id": data["archive_task_id"], "scene_revision": "reference-narrow-static-box-v1",
        "clock_id": "historical-reference-counterfactual-epoch-1", "frame_id": "scene_enu_m"}
    for parent in trajectory_ids:
        for requested in horizons:
            row = {"trajectory_id": parent, "requested_horizon_s": time_study.finite_number(requested),
                "variant_id": f"reference-{parent}-h{requested!r}", "execution_admission": "not_performed"}
            rows.append(row)
            try:
                source = windows[parent]["source_curve"]
                if source.get("task_id") != data["archive_task_id"] or source.get("trajectory_id") != parent:
                    raise ValueError("raw_source_identity_mismatch")
                window = primitives.restrict(source, float(requested), curve, audit, limits)
                if not window["conversion"]["passed"]:
                    raise ValueError("new_prefix_conversion_unverified")
                row["window"] = window
                timing = reference.timing(window, data["windows"])
                cut = window["window_end_sim_s"]
                timing.update(relative_to_next_received=relative_to(cut, timing["next_curve_received_sim_s"]),
                    relative_to_recorded_failure=relative_to(cut, failure["simulation_s"]),
                    first_recorded_failure_sim_s=failure["simulation_s"],
                    online_admission="unverified: reference cut timing does not qualify compute/state/map")
                row["timing"] = timing
                head = np.asarray(window["terminal_pvaj_xyz_columns"])
                necessary = geometry.tracking.stopping_necessary(head[:,0], head[:,1], reference.NARROW_BOX, limits["acceleration"])
                necessary["initial_acceleration_and_jerk"] = "reference left limit known but ignored by this bound; vehicle A/J unrecorded"
                row["necessary"] = necessary
                if necessary["status"] == "necessary_reject":
                    row.update(status="necessary_reject", reason="optimistic_per_face_reference_model_reject"); continue
                if necessary["status"] != "not_ruled_out":
                    row.update(status="unscored", reason="necessary_bound_unqualified"); continue
                base = handoff.axis_stop_request({"initial_pva": head[:,:3].tolist(),
                    "original_local_target": head[:,0].tolist(), "corridor": [reference.box_faces(reference.NARROW_BOX)],
                    "integral_resolution": 16}, [3.5,1.,.4], head[:,3].tolist())
                searched = geometry.search(base, reference.NARROW_BOX, limits, native, audit, y_inner=True,
                    z_time_bounds=z_domain, max_iterations=max_iterations)
                row["search"] = searched
                if searched["status"] != "audited":
                    row.update(status="unscored", reason=searched.get("reason", "search_unavailable")); continue
                result = time_study.compose(window, searched["candidate"]["request"], native, limits,
                    audit, handoff, reference, candidates)
                row.update(status=result["status"], result=result)
                if result["status"] == "generated":
                    result["candidate"]["candidate_id"] = row["variant_id"]
                    row["counterfactual_replay"] = reference.replay_cases(result["candidate"], context,
                        limits, replay, audit, handoff, box=reference.NARROW_BOX)
            except (ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
                row.update(status="unscored", reason=str(error))
                print(f"WARNING: narrow handoff {row['variant_id']}: {error}")
    generated = [r for r in rows if r["status"] == "generated"]
    passed = [r for r in generated if r["result"]["candidate"]["full_math_gate"]["passed"]
              and r["result"]["narrow_box_gate"]["passed"]]
    return {"schema_version": 1, "archive_task_id": data["archive_task_id"], "limits": limits,
        "kind": "offline_earlier_reference_cut_narrow_box_comparison", "context": context,
        "horizons_s": [time_study.finite_number(h) for h in horizons],
        "z_time_bounds_s": [time_study.finite_number(t) for t in z_domain],
        "narrow_box_fixture": reference.NARROW_BOX, "failure_evidence": failure,
        "summary": {"source_windows": len(data["windows"]), "variants": len(rows), "generated": len(generated),
            "necessary_rejected": sum(r["status"] == "necessary_reject" for r in rows),
            "narrow_math_passed": len(passed), "unscored": sum(r["status"] == "unscored" for r in rows),
            "narrow_passed_before_both_recorded_events": sum(r["timing"]["relative_to_next_received"] == "before"
                and r["timing"]["relative_to_recorded_failure"] == "before" for r in passed)},
        "scope": "each cut preserves its own reference PVA/J; no measured-state, map, deadline or flight qualification",
        "terminal_scope": "finite static-fixture forecast only; no invariant landing or hover region",
        "dynamic_closed_loop": "not_passed", "execution_admission": "not_performed", "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primitives", type=Path, required=True)
    parser.add_argument("--failure-report", type=Path, required=True)
    parser.add_argument("--drone-root", type=Path, default=Path.home()/"dev/ros2/projects/drone")
    parser.add_argument("--native", type=Path, default=Path.home()/".cache/ros2-drone/minco-s4-knots/minco_s4_knots")
    parser.add_argument("--trajectory-ids", type=int, nargs="+", default=[4,7])
    parser.add_argument("--horizons", type=float, nargs="+", default=HORIZONS)
    parser.add_argument("--max-iterations", type=int, default=60)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        failure = json.loads(args.failure_report.read_text())
    except (OSError, ValueError) as error:
        print(f"WARNING: failure report unavailable; temporal qualification unknown: {error}"); failure = {}
    report = run(json.loads(args.primitives.read_text()), failure, args.drone_root, args.native,
        trajectory_ids=args.trajectory_ids, horizons=args.horizons, max_iterations=args.max_iterations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print(json.dumps(report["summary"]))


if __name__ == "__main__":
    main()
