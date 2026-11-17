#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Restrict recorded cubic splines exactly. Offline only; no solver, ROS or control."""
import argparse
from collections import Counter
import json
from math import factorial
from pathlib import Path
import sys

import numpy as np
from numpy.polynomial import polynomial as poly
from scipy.interpolate import PPoly


def reuse(drone_root):
    # Import the existing evaluator/auditor, without modifying the frozen source.
    sys.path.insert(0, str(drone_root / "scripts"))
    import audit_retiming
    import audit_minco
    return audit_retiming.curve, audit_minco


def pvaj(power, duration, fraction, auditor):
    return np.column_stack([poly.polyval(fraction, auditor.derivative(power, duration, i))
                            for i in range(4)])


def restrict(record, horizon, curve, auditor, limits=None):
    if record["order"] != 3 or not np.isfinite(horizon) or horizon <= 0:
        raise ValueError("Expected cubic spline and positive finite horizon")
    spline = curve(record)
    if spline.c.ndim != 2 or spline.c.shape[1] != 3 or not np.all(np.isfinite(spline.c)):
        raise ValueError("Expected finite XYZ control points")
    source_start, source_end = float(spline.t[3]), float(spline.t[-4])
    phase = max(0., record["received_sim_s"] - record["start_sim_s"])
    lower, upper = source_start + phase, min(source_end, source_start + phase + horizon)
    if not np.isfinite(lower) or not upper > lower:
        raise ValueError("No remaining source curve at receipt time")
    polynomials = [PPoly.from_spline((spline.t, spline.c[:, axis], 3), extrapolate=False)
                   for axis in range(3)]
    cuts = np.r_[lower, np.unique(spline.t[(spline.t > lower) & (spline.t < upper)]), upper]
    pieces, diagnostics = [], []
    max_error = np.zeros(4)
    continuity = np.zeros(4)
    previous = None
    for left, right in zip(cuts[:-1], cuts[1:]):
        duration = float(right - left)
        # Taylor translation reanchors PPoly's original knot at this piece's start.
        ascending = np.array([[float(p(left, nu=i)) / factorial(i) for p in polynomials]
                              for i in range(4)])
        padded = np.vstack([ascending, np.zeros((2, 3))])
        piece = {"duration": duration, "coefficients_descending": padded[::-1].T.tolist(),
                 "source_parameter_start_s": float(left), "source_parameter_end_s": float(right)}
        power = auditor.normalized_power(piece)
        head, tail = pvaj(power, duration, 0., auditor), pvaj(power, duration, 1., auditor)
        if previous is not None:
            continuity = np.maximum(continuity, np.linalg.norm(head - previous, axis=0))
        previous = tail
        # Independent B-spline derivative evaluation supplies each span's reference
        # polynomial. A midpoint selects the correct side even at repeated knots.
        middle = float((left + right) / 2)
        reference = np.array([spline(middle, nu=i) / factorial(i) for i in range(4)])
        reference_power = np.zeros((6, 3))
        for axis in range(3):
            translated = poly.polyval(poly.Polynomial([left-middle, duration]), reference[:, axis]).coef
            reference_power[:len(translated), axis] = translated
        errors = [auditor.norm_maximum(auditor.derivative(power-reference_power, duration, i))["value"]
                  for i in range(4)]
        error_certificates = [auditor.interval_certificate(auditor.bernstein(
            auditor.derivative(power-reference_power, duration, i)), "norm", 1e-8) for i in range(4)]
        max_error = np.maximum(max_error, errors)
        velocity, acceleration = auditor.derivative(power, duration), auditor.derivative(power, duration, 2)
        speed, acc = auditor.norm_maximum(velocity), auditor.norm_maximum(acceleration)
        row = {"speed_max_m_s": speed["value"], "acceleration_max_m_s2": acc["value"],
               "acceleration_peak_piece_time_s": duration*acc["u"],
               "height_max_m": auditor.scalar_maximum(power[:, 2]),
               "initial_pvaj_xyz_columns": head.tolist(), "terminal_pvaj_xyz_columns": tail.tolist(),
               "continuous_conversion_error_pvaj": errors, "conversion_error_certificates_pvaj": error_certificates}
        if limits:
            row["certificates"] = {
                "speed": auditor.interval_certificate(auditor.bernstein(velocity), "norm", limits["speed"]),
                "acceleration": auditor.interval_certificate(auditor.bernstein(acceleration), "norm", limits["acceleration"]),
                "ceiling": auditor.interval_certificate(auditor.bernstein(power[:, 2:3]), "box", [[-np.inf], [limits["ceiling"]]]),
            }
        pieces.append(piece)
        diagnostics.append(row)
    logged_start = record.get("start_pva")
    source_head = np.array([spline(source_start, nu=i) for i in range(3)]).T
    numerical_pass = bool(np.max(continuity[:3]) <= 1e-8 and all(
        state == "clear" for row in diagnostics for state in row["conversion_error_certificates_pvaj"]))
    peak = int(np.argmax([r["acceleration_max_m_s2"] for r in diagnostics]))
    failed = sorted({key for row in diagnostics for key, state in row.get("certificates", {}).items() if state != "clear"})
    return {
        "trajectory_id": record.get("trajectory_id"), "recorded_task_id": record.get("task_id"),
        "recorded_goal_id": record.get("goal_id"),
        "task_attribution": "recorded" if record.get("task_id") else "unrecorded",
        "recorded_start_sim_s": record["start_sim_s"], "received_sim_s": record["received_sim_s"],
        "window_start_sim_s": record["start_sim_s"] + phase,
        "window_end_sim_s": record["start_sim_s"] + phase + float(upper-lower),
        "source_domain_start_s": source_start, "source_phase_at_window_start_s": phase,
        "requested_horizon_s": horizon, "duration_s": float(upper-lower),
        "representation": "piecewise_cubic_padded_to_3x6_physical_seconds_descending",
        "pieces": pieces, "piece_diagnostics": diagnostics,
        "initial_pvaj_xyz_columns": diagnostics[0]["initial_pvaj_xyz_columns"],
        "terminal_pvaj_xyz_columns": diagnostics[-1]["terminal_pvaj_xyz_columns"],
        "conversion": {"passed": numerical_pass, "tolerance": 1e-8,
            "continuous_error_max_pvaj": max_error.tolist(), "join_error_max_pva": continuity[:3].tolist(),
            "source_jerk_jump_max_m_s3": float(continuity[3]), "continuity_claim": "PVA only; original jerk jumps retained",
            "logged_domain_start_pva_error": float(np.max(abs(source_head-np.asarray(logged_start).T))) if logged_start is not None else None,
            "receipt_pva_minus_logged_domain_start": (np.asarray(diagnostics[0]["initial_pvaj_xyz_columns"])[:, :3]-source_head).tolist()},
        "vaz_gate": {"status": "checked" if limits else "unverified", "passed": not failed if limits else None,
            "failed_checks": failed, "speed_max_m_s": max(r["speed_max_m_s"] for r in diagnostics),
            "acceleration_max_m_s2": diagnostics[peak]["acceleration_max_m_s2"],
            "height_max_m": max(r["height_max_m"] for r in diagnostics),
            "acceleration_peak_piece": peak,
            "acceleration_peak_sim_s": record["start_sim_s"]+phase+sum(p["duration"] for p in pieces[:peak])+diagnostics[peak]["acceleration_peak_piece_time_s"]},
        "occupancy": {"status": "unverified", "reason": "No timestamped per-curve GridMap snapshot consumed; sparse rays do not certify swept volume"},
        "execution_admission": "not_performed",
    }


def run(run_dir, drone_root, horizon):
    curve, auditor = reuse(drone_root)
    request = json.loads((run_dir / "request.json").read_text())
    source = run_dir / "ego/trajectory-events.jsonl"
    limits_file = run_dir / "minco-margin-audit.json"
    warnings, results = [], []
    limits = json.loads(limits_file.read_text())["limits"] if limits_file.exists() else None
    if limits is None:
        warnings.append("Saved candidate limits unavailable; conversion continues without gate acceptance")
    for number, line in enumerate(source.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            row = restrict(record, horizon, curve, auditor, limits)
            row.update(source_line=number, source_curve=record)
            results.append(row)
        except (ValueError, KeyError, TypeError) as error:
            warnings.append(f"{source.name}:{number}: skipped: {error}")
    return {"schema_version": 1, "archive_task_id": request["id"],
        "kind": "exact_recorded_spline_windows", "clock": "simulation_seconds_not_unix",
        "source": str(source), "horizon_s": horizon, "warnings": warnings,
        "limits_source": str(limits_file) if limits else None, "limits": limits,
        "limits_scope": "Saved offline candidate hard gates; not measured flight acceptance",
        "scope": "Recorded nominal reference only; receipt is not PX4 adoption. Future windows may be superseded or invalidated by unseen occupancy",
        "summary": {"windows": len(results), "conversion_passed": sum(r["conversion"]["passed"] for r in results),
            "vaz_passed": sum(r["vaz_gate"]["passed"] is True for r in results),
            "attribution": dict(Counter(r["task_attribution"] for r in results)),
            "occupancy_verified": False, "execution_admission": "not_performed"}, "windows": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--drone-root", type=Path, default=Path.home() / "dev/ros2/projects/drone")
    parser.add_argument("--horizon", type=float, default=.8)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.run_dir, args.drone_root, args.horizon)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2)+"\n")
    print(json.dumps({"archive_task_id": report["archive_task_id"], **report["summary"], "warnings": report["warnings"]}))
