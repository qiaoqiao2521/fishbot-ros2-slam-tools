#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Offline fixed-five-parameter Z-time sweep and explicit joint-domain study."""
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


Z_SAMPLES = [.4, .5, .6, .8, 1., 1.2]
Z_DOMAIN = [.1, 1.2]


def finite_number(value):
    try:
        number = float(value)
        return number if np.isfinite(number) else None
    except (ValueError, TypeError, OverflowError):
        return None


def index_rows(rows, label):
    result = {}
    for row in rows:
        try:
            key = row["trajectory_id"]
            if key is None:
                raise ValueError("missing trajectory ID")
            result[key] = row
        except (ValueError, TypeError, KeyError):
            print(f"WARNING: {label}: malformed source item skipped")
    return result


def describe_peak(candidate, audit):
    score = candidate["full_math_gate"]
    pieces = candidate["prefix_pieces"]+candidate["native"]["pieces"]
    index = score["acceleration_peak_segment"]; piece = pieces[index]
    u = score["acceleration_peak_local_t"]/piece["duration"]
    power = audit.derivative(audit.normalized_power(piece), piece["duration"], 2)
    return {"piece_index": index, "in_prefix": index < len(candidate["prefix_pieces"]),
        "time_after_cut_s": score["acceleration_peak_global_t"]-candidate["prefix_duration_s"],
        "acceleration_xyz": np.polynomial.polynomial.polyval(u, power).tolist()}


def compose(window, request, native, limits, audit, handoff, reference, candidates):
    candidate = candidates.compare(window, limits, request["axis_stop_durations_xyz"], native,
        audit, handoff, tail_request=request)
    if candidate["status"] != "generated":
        return {"status": candidate["status"], "reason": candidate.get("reason"), "candidate": candidate}
    return {"status": "generated", "candidate": candidate,
        "full_static_box_gate": reference.static_gate(candidate, reference.STATIC_BOX, limits, audit),
        "narrow_box_gate": reference.static_gate(candidate, reference.NARROW_BOX, limits, audit),
        "peak": describe_peak(candidate, audit), "execution_admission": "not_performed"}


def run(primitives, previous, root, native, *, trajectory_ids=(4, 7), z_samples=Z_SAMPLES,
        z_domain=Z_DOMAIN, max_iterations=60):
    reference, geometry, candidates, replay = [load(n) for n in
        ("drone-reference-stops", "drone-stop-geometry", "drone-stop-candidates", "drone-committed-replay")]
    audit, handoff = candidates.load_modules(root)
    windows = index_rows(primitives["windows"], "primitives")
    seeds = index_rows(previous["rows"], "reference report")
    limits = primitives["limits"]; rows = []
    for trajectory_id in trajectory_ids:
        row = {"trajectory_id": trajectory_id, "execution_admission": "not_performed"}; rows.append(row)
        try:
            if (primitives["archive_task_id"] != previous["archive_task_id"] or limits != previous["limits"]):
                raise ValueError("source_task_or_limits_mismatch")
            window, seed = windows[trajectory_id], seeds[trajectory_id]
            if (window.get("recorded_task_id") != primitives["archive_task_id"]
                    or window.get("task_attribution") != "recorded" or not window.get("conversion", {}).get("passed")):
                raise ValueError("source_identity_or_conversion_unverified")
            values = np.asarray(seed["search"]["optimizer"]["values"], dtype=float)
            if values.shape != (6,) or not np.all(np.isfinite(values)):
                raise ValueError("source_six_parameters_unavailable")
            row["timing"] = reference.timing(window, primitives["windows"])
            row["source_values"] = values.tolist()
            base = copy.deepcopy(seed["candidate"]["request"])
            row["fixed_five_parameter_sweep"] = []
            for tz in z_samples:
                # End position follows the existing stopping formula. This is
                # a re-solve with fixed head PVA/J, not coefficient retiming.
                try:
                    varied = values.copy(); varied[2] = tz
                    request = geometry.geometry_request(base, varied, y_inner=True)
                    variant = {"z_stop_s": tz, "values": varied.tolist(),
                        **compose(window, request, native, limits, audit, handoff, reference, candidates)}
                except (ValueError, TypeError, KeyError, IndexError) as error:
                    variant = {"z_stop_s": finite_number(tz),
                        "status": "unscored", "reason": str(error)}
                    print(f"WARNING: time study {trajectory_id}, Tz={tz}: {error}")
                row["fixed_five_parameter_sweep"].append(variant)
            base.update(integral_resolution=16, corridor=[reference.box_faces(reference.STATIC_BOX)])
            searched = geometry.search(base, reference.STATIC_BOX, limits, native, audit, y_inner=True,
                z_time_bounds=z_domain, max_iterations=max_iterations)
            row["joint_search"] = searched
            if searched["status"] != "audited":
                row.update(status="unscored", reason=searched.get("reason", "joint_search_unavailable")); continue
            final = compose(window, searched["candidate"]["request"], native, limits, audit, handoff, reference, candidates)
            row.update(status=final["status"], joint=final)
            if final["status"] == "generated":
                row["counterfactual_replay"] = reference.replay_cases(final["candidate"], previous["context"],
                    limits, replay, audit, handoff)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
            row.update(status="unscored", reason=str(error))
            print(f"WARNING: time study {trajectory_id}: {error}")
    generated = [r for r in rows if r["status"] == "generated"]
    return {"schema_version": 1, "archive_task_id": primitives["archive_task_id"], "limits": limits,
        "kind": "offline_reference_Z_time_domain_comparison", "declared_trajectory_ids": list(trajectory_ids),
        "fixed_sweep_z_samples_s": [finite_number(t) for t in z_samples],
        "joint_z_time_bounds_s": [finite_number(t) for t in z_domain],
        "original_z_time_bounds_s": [.1, .4], "static_box_fixture": reference.STATIC_BOX,
        "narrow_box_comparison": reference.NARROW_BOX,
        "summary": {"selected_windows": len(rows), "generated": len(generated),
            "joint_math_passed": sum(r["joint"]["candidate"]["full_math_gate"]["passed"] for r in generated),
            "joint_static_box_passed": sum(r["joint"]["full_static_box_gate"]["passed"] for r in generated),
            "joint_narrow_box_passed": sum(r["joint"]["narrow_box_gate"]["passed"] for r in generated)},
        "scope": "reference PVA/J only; fixed-five sweep and joint bounded experiment, not a global feasibility proof",
        "qualification": "actual state/map/terminal/deadline/tracking/adoption unverified; dynamic closed loop not passed",
        "execution_admission": "not_performed", "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primitives", type=Path, required=True)
    parser.add_argument("--reference-report", type=Path, required=True)
    parser.add_argument("--drone-root", type=Path, default=Path.home()/"dev/ros2/projects/drone")
    parser.add_argument("--native", type=Path, default=Path.home()/".cache/ros2-drone/minco-s4-knots/minco_s4_knots")
    parser.add_argument("--trajectory-ids", type=int, nargs="+", default=[4, 7])
    parser.add_argument("--z-samples", type=float, nargs="+", default=Z_SAMPLES)
    parser.add_argument("--z-domain", type=float, nargs=2, default=Z_DOMAIN)
    parser.add_argument("--max-iterations", type=int, default=60)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(json.loads(args.primitives.read_text()), json.loads(args.reference_report.read_text()),
        args.drone_root, args.native, trajectory_ids=args.trajectory_ids, z_samples=args.z_samples,
        z_domain=args.z_domain, max_iterations=args.max_iterations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps(result["summary"]))


if __name__ == "__main__":
    main()
