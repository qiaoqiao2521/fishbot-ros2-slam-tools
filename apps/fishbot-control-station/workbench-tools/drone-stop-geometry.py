#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Offline stop-position/time comparison using existing MINCO and hard auditors."""
import argparse
import copy
from functools import lru_cache
import json
from pathlib import Path
import time

import numpy as np
from scipy.optimize import minimize

import importlib.util
spec = importlib.util.spec_from_file_location("recorded_tracking", Path(__file__).with_name("drone-recorded-tracking.py"))
tracking = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tracking)


def geometry_request(base, values, *, y_inner=False):
    """Resolve a new curve with unchanged initial PVA/J; never stretch a curve."""
    values = np.asarray(values, dtype=float)
    tx, ty, tz, dy = values[:4] if y_inner else values
    if not np.all(np.isfinite([tx, ty, tz, dy])) or min(tx, ty, tz) <= 0 or dy < 0:
        raise ValueError("positive finite times and nonnegative Y displacement required")
    request = copy.deepcopy(base)
    head = np.asarray(base["initial_pva"], dtype=float)
    target = head[:, 0]+.5*np.asarray([tx, ty, tz])*head[:, 1]
    target[1] = head[1, 0]+dy
    request.update(mode="axis_stop", axis_stop_durations_xyz=[float(tx), float(ty), float(tz)],
        stop_positions=target.tolist(), terminal_pva=np.column_stack([target, np.zeros((3, 2))]).tolist(),
        terminal_jerk=[0., 0., 0.], original_local_target=target.tolist(), required_continuity_order=3,
        contract_scope="backup endpoint; not mission waypoint completion")
    request.setdefault("source_local_target_before_stop", copy.deepcopy(base["original_local_target"]))
    request.pop("axis_inner_positions_xyz", None)
    request.pop("axis_segment_durations_xyz", None)
    if y_inner:
        ratio, fraction = values[4:]
        if not np.all(np.isfinite([ratio, fraction])) or not 0 < ratio < 1 or not 0 <= fraction <= 1:
            raise ValueError("finite internal time ratio in (0,1) and displacement fraction in [0,1] required")
        request["axis_inner_positions_xyz"] = [[], [float(head[1, 0]+dy*fraction)], []]
        request["axis_segment_durations_xyz"] = [[float(tx)], [float(ty*ratio), float(ty*(1-ratio))], [float(tz)]]
    return request


def audit_axis_knots(native, request, audit):
    """Local stop semantics absent from the frozen global boundary audit."""
    stops = np.asarray(request["axis_stop_durations_xyz"], dtype=float)
    target = np.asarray(request["stop_positions"], dtype=float)
    total = sum(piece["duration"] for piece in native["pieces"])
    if (stops.shape != (3,) or target.shape != (3,) or not np.all(np.isfinite(np.r_[stops, target, total]))
            or np.any(stops <= 0)):
        return {"passed": False, "reason": "invalid_declared_axis_stops"}
    residual = np.zeros((3, 4)); elapsed = 0.
    for piece in native["pieces"]:
        duration = piece["duration"]; power = audit.normalized_power(piece)
        for axis in range(3):
            if elapsed+duration > stops[axis]:
                begin = max(0., min(1., (stops[axis]-elapsed)/duration))
                for order in range(4):
                    scalar = audit.derivative(power, duration, order)[:, axis].copy()
                    if order == 0: scalar[0] -= target[axis]
                    scalar = np.polynomial.Polynomial(scalar)(np.polynomial.Polynomial([begin, 1.-begin])).coef
                    residual[axis, order] = max(residual[axis, order], audit.scalar_maximum(scalar), audit.scalar_maximum(-scalar))
        elapsed += duration
    last = native["pieces"][-1]; power = audit.normalized_power(last)
    for order in range(4):
        value = np.polynomial.polynomial.polyval(1., audit.derivative(power, last["duration"], order))
        if order == 0: value -= target
        residual[:, order] = np.maximum(residual[:, order], abs(value))
    inner_error = 0.
    inner = request.get("axis_inner_positions_xyz", [[], [], []])
    times = request.get("axis_segment_durations_xyz", [[s] for s in stops])
    for axis in range(3):
        durations = np.asarray(times[axis], dtype=float); points = np.asarray(inner[axis], dtype=float)
        if (durations.ndim != 1 or points.ndim != 1 or len(durations) != len(points)+1
                or not np.all(np.isfinite(np.r_[durations, points])) or np.any(durations <= 0)
                or abs(sum(durations)-stops[axis]) > 1e-9):
            return {"passed": False, "reason": "invalid_declared_inner_knots"}
        for at, position in zip(np.cumsum(durations)[:-1], points):
            elapsed = 0.
            for piece in native["pieces"]:
                if at <= elapsed+piece["duration"]:
                    u = (at-elapsed)/piece["duration"]
                    actual = np.polynomial.polynomial.polyval(u, audit.normalized_power(piece)[:, axis])
                    inner_error = max(inner_error, abs(float(actual)-position)); break
                elapsed += piece["duration"]
            else:
                return {"passed": False, "reason": "inner_knot_outside_curve"}
    passed = (np.all(np.isfinite(residual)) and abs(total-max(stops)) < 1e-8
        and np.max(residual) <= 1e-8 and inner_error <= 1e-8)
    return {"passed": bool(passed), "maximum_residual_PVAJ_by_axis": residual.tolist(),
        "maximum_inner_position_error_m": inner_error,
        "scope": "declared inner positions and constant axes after each stop; numeric residual threshold 1e-8"}


def extrema(native, audit):
    """Continuous polynomial-root diagnostics; the final gate is separate."""
    upper, lower = [], []
    acceleration = 0.
    min_y_velocity, min_y_time, elapsed = np.inf, None, 0.
    for piece in native["pieces"]:
        power = audit.normalized_power(piece)
        velocity = audit.derivative(power, piece["duration"])
        upper.append([audit.scalar_maximum(power[:, i]) for i in range(3)])
        lower.append([-audit.scalar_maximum(-power[:, i]) for i in range(3)])
        acceleration = max(acceleration, audit.norm_maximum(audit.derivative(power, piece["duration"], 2))["value"])
        candidates = np.r_[0., 1., audit.roots_in_unit(np.polynomial.polynomial.polyder(velocity[:, 1]))]
        values = np.polynomial.polynomial.polyval(candidates, velocity[:, 1])
        index = int(np.argmin(values))
        if values[index] < min_y_velocity:
            min_y_velocity = float(values[index]); min_y_time = elapsed+piece["duration"]*float(candidates[index])
        elapsed += piece["duration"]
    return {"upper": np.max(upper, axis=0).tolist(), "lower": np.min(lower, axis=0).tolist(),
        "acceleration_peak_m_s2": acceleration, "minimum_y_velocity_m_s": min_y_velocity,
        "minimum_y_velocity_at_s": min_y_time, "reverse_y_speed_m_s": max(0., -min_y_velocity)}


def search(base, box, limits, executable, audit, *, planning_inset=.002, max_iterations=60, y_inner=False,
           z_time_bounds=None, exchange=None, metrics_backend=None):
    """Bounded recorded +Y profile, not a generic planner or feasibility proof."""
    try:
        head = np.asarray(base["initial_pva"], dtype=float)
        bounds = np.asarray(box, dtype=float)
    except (KeyError, ValueError, TypeError):
        return {"status": "unscored", "reason": "invalid_boundary_or_box"}
    if (head.shape != (3, 3) or bounds.shape != (2, 3) or not np.all(np.isfinite(np.r_[head.ravel(), bounds.ravel(), planning_inset]))
            or planning_inset < 0 or head[1, 1] <= 0 or np.any(bounds[0] >= bounds[1])):
        return {"status": "unscored", "reason": "outside_recorded_positive_y_profile"}
    planning_box = np.array([bounds[0]+planning_inset, bounds[1]-planning_inset])
    if np.any(head[:, 0] < planning_box[0]) or np.any(head[:, 0] >= planning_box[1]):
        return {"status": "unscored", "reason": "input_outside_planning_box", "planning_box": planning_box.tolist()}
    try:
        z_bounds = np.asarray((.1, .4) if z_time_bounds is None else z_time_bounds, dtype=float)
    except (ValueError, TypeError):
        return {"status": "unscored", "reason": "invalid_z_time_bounds"}
    if z_bounds.shape != (2,) or not np.all(np.isfinite(z_bounds)) or not 0 < z_bounds[0] < z_bounds[1]:
        return {"status": "unscored", "reason": "invalid_z_time_bounds"}
    # Explicit bounded experiment, not a full search of all possible brakes.
    displacement = planning_box[1, 1]-head[1, 0]
    parameter_bounds = [(3.5, 5.), (.6, 2.), tuple(z_bounds), (0., displacement)]
    initial = [4.5, 1., float(np.clip(.4, *z_bounds)), min(.5*head[1, 1], .95*displacement)]
    if y_inner:
        parameter_bounds += [(.15, .85), (0., 1.)]
        initial += [.5, .85]
    started = time.perf_counter()

    @lru_cache(maxsize=512)
    def evaluate(values):
        request = geometry_request(base, values, y_inner=y_inner)
        result = tracking.audit_axis_request(request, box, limits, executable, audit, perform_audit=False,
            **({"exchange":exchange} if exchange is not None else {}))
        if result["status"] != "generated":
            raise ValueError(result.get("reason", "native generation unavailable"))
        if y_inner and (result["native"].get("generator") != "official_MINCO_S4NU_axis_inner_points"
                or result["native"].get("axis_piece_counts") != [1, 2, 1]):
            raise ValueError("native interface did not acknowledge the requested Y inner point")
        metrics = extrema(result["native"], audit) if metrics_backend is None else metrics_backend(result["native"], audit)
        margins = np.r_[planning_box[1]-metrics["upper"], np.asarray(metrics["lower"])-planning_box[0]]
        return result, metrics, margins

    try:
        optimizer = minimize(lambda x: evaluate(tuple(x))[1]["acceleration_peak_m_s2"], initial,
            method="SLSQP", bounds=parameter_bounds,
            constraints=[{"type": "ineq", "fun": lambda x: evaluate(tuple(x))[2]}],
            options={"maxiter": max_iterations, "ftol": 1e-9})
        result, metrics, margins = evaluate(tuple(optimizer.x))
        # An optimizer status and polynomial-root diagnostics cannot replace
        # the original conservative Bernstein and boundary audit.
        final = tracking.audit_axis_request(result["request"], box, limits, executable, audit,
            **({"exchange":exchange} if exchange is not None else {}))
        if final["status"] != "audited":
            return final
        if y_inner:
            final["axis_knot_contract"] = audit_axis_knots(final["native"], final["request"], audit)
            if not final["axis_knot_contract"]["passed"]:
                final["audit"]["passed"] = False
                final["audit"]["failed_checks"].append("axis_knots")
        target = np.asarray(final["request"]["stop_positions"])
        return {"status": "audited", "optimizer": {"method": "SLSQP bounded external search, not native GCOPTER weights",
            "success": bool(optimizer.success), "message": str(optimizer.message), "evaluations": int(optimizer.nfev),
            "iterations": int(optimizer.nit), "parameter_order": ["tx", "ty", "tz", "dy"]+(["y_time_ratio", "y_displacement_fraction"] if y_inner else []), "values": optimizer.x.tolist(),
            "parameter_bounds": parameter_bounds, "planning_inset_m": planning_inset,
            "planning_box": planning_box.tolist(), "planning_margins_m": margins.tolist()},
            "diagnostics": {**metrics, "endpoint_face_margins_m": np.r_[bounds[1]-target, target-bounds[0]].tolist(),
                "whole_curve_face_margins_m": np.r_[bounds[1]-metrics["upper"], np.asarray(metrics["lower"])-bounds[0]].tolist()},
            "candidate": final, "offline_wall_s": time.perf_counter()-started,
            "scope": "conditional recorded-state +Y static-box experiment; no global feasibility or optimality proof",
            "execution_admission": "not_performed"}
    except (ValueError, KeyError, TypeError, np.linalg.LinAlgError) as error:
        return {"status": "unscored", "reason": str(error), "execution_admission": "not_performed"}


def run(source, root, executable, planning_inset=.002, max_iterations=60):
    original = json.loads(source.read_text())
    data = original["stopping"]
    audit, _ = tracking.load("stop_candidates", Path(__file__).with_name("drone-stop-candidates.py")).load_modules(root)
    events = [r for r in data["cases"] if r["kind"] == "reanchor"]
    rows = []
    for event in events:
        for name, variant in event["variants"].items():
            row = {"variant": name, "pv_at_sim_s": variant["pv_at_sim_s"], "provenance": variant["provenance"],
                "input_role": "retrospective counterfactual input, not causal online evidence" if name == "retrospective_source_pv" else "offline cached/model input",
                "necessary": variant["necessary"], "baseline": variant.get("conditional_axis_stop"),
                "event_sim_s": event["forecast_at_sim_s"], "oracle_source_offset_s": event["oracle_source_offset_s"]}
            baseline = row["baseline"]
            if variant["necessary"].get("status") == "necessary_reject":
                row.update(status="not_searched", reason="necessary_bound_reject_in_supplied_model")
            elif variant["necessary"].get("status") != "not_ruled_out":
                row.update(status="unscored", reason="necessary_bound_unqualified")
            elif not baseline or baseline.get("status") != "audited" or not baseline.get("request"):
                row.update(status="unscored", reason="baseline_boundary_request_unavailable")
            else:
                base = copy.deepcopy(baseline["request"])
                try:
                    supplied = np.asarray(base["initial_pva"], dtype=float)
                    expected = np.column_stack([variant["position"], variant["velocity"]])
                    matched = supplied.shape == (3, 3) and np.array_equal(supplied[:, :2], expected) and np.all(np.isfinite(expected))
                except (KeyError, ValueError, TypeError):
                    matched = False
                if not matched:
                    row.update(status="unscored", reason="variant_and_boundary_pv_mismatch")
                    print(f"WARNING: {name}: variant PV and baseline request disagree; this row skipped")
                    rows.append(row)
                    continue
                if baseline["audit"]["passed"]:
                    row.update(status="unchanged", reason="baseline_already_passed_conditionally")
                    rows.append(row)
                    continue
                base["initial_condition_scope"] = baseline.get("assumption", "provided boundary, A/J measurement unqualified")
                row["acceleration_scope"] = "original boundary A retained; predictor model acceleration not substituted as measured A"
                row.update(search(base, data["box"], data["limits"], executable, audit,
                    planning_inset=planning_inset, max_iterations=max_iterations))
            rows.append(row)
    return {"schema_version": 1, "archive_task_id": original["archive_task_id"], "source": str(source),
        "kind": "offline_stop_position_time_comparison", "hard_box": data["box"], "hard_limits": data["limits"],
        "scope": "manual static fixture; A/J hypotheses retained, not measured; no current map or terminal region",
        "oracle_scope": "retrospective PV explicitly used only as counterfactual generator input; not an online candidate",
        "rows": rows, "execution_admission": "not_performed"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stopping-report", type=Path, required=True)
    parser.add_argument("--drone-root", type=Path, default=Path.home()/"dev/ros2/projects/drone")
    parser.add_argument("--native", type=Path, default=Path.home()/".cache/ros2-drone/minco-probe/minco_probe")
    parser.add_argument("--planning-inset", type=float, default=.002)
    parser.add_argument("--max-iterations", type=int, default=60)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.stopping_report, args.drone_root, args.native, args.planning_inset, args.max_iterations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"rows": [{"variant": r["variant"], "status": r["status"],
        "passed": r.get("candidate", {}).get("audit", {}).get("passed")} for r in result["rows"]],
        "execution_admission": "not_performed"}))
