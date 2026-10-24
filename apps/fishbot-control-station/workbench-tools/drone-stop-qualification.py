#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Offline boundary hypotheses and existing selector's temporal qualifications."""
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


geometry = load("drone-stop-geometry")
committed = load("drone-committed-replay")


def profiles(past, task_id, boundary_s=None, available_at=None):
    """Named finite hypotheses, neither a calibrated uncertainty set nor measurements."""
    held = {"name": "past_velocity_A_held", "status": "unscored", "reason": "past_model_A_unavailable"}
    eligible = []
    if isinstance(past, dict) and past.get("archive_task_id") == task_id:
        forecast = past.get("forecast")
        cases = forecast.get("cases") if isinstance(forecast, dict) else None
        for case in cases if isinstance(cases, list) else []:
            try:
                anchor, previous = case["input_state"], case["previous_available_state"]
                now = case["forecast_at_sim_s"]
                if (case["kind"] != "fsm" or not geometry.tracking.usable_pv(anchor)
                        or not geometry.tracking.usable_pv(previous)
                        or not np.all(np.isfinite([now, boundary_s, available_at]))
                        or not previous["source_sim_s"] < anchor["source_sim_s"] <= now <= min(available_at, boundary_s)
                        or not (geometry.tracking.recorded_availability(anchor) <= now
                                or case.get("input_evidence") == "FSM logged consumed PV")
                        or geometry.tracking.recorded_availability(previous) > now):
                    continue
                estimate = geometry.tracking.predict_pv(anchor, anchor["source_sim_s"], "causal_acceleration", previous)
                stored = np.asarray(case["models"]["causal_acceleration"]["model_acceleration"], dtype=float)
                if stored.shape != (3,) or not np.all(np.isfinite(stored)) or not np.array_equal(stored, estimate["model_acceleration"]):
                    continue
                eligible.append((now, anchor["source_sim_s"], previous["source_sim_s"], stored.tolist()))
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
    if eligible:
        now, source_s, previous_s, a = max(eligible, key=lambda r: (r[0], r[1]))
        held = {"name": held["name"], "acceleration": a, "jerk": [0.]*3,
            "scope": "past-V difference held from source to boundary as A hypothesis; J=0, neither measured",
            "A_source_sim_s": source_s, "previous_V_source_sim_s": previous_s,
            "construction_available_at_sim_s": now, "boundary_sim_s": boundary_s,
            "held_from_A_source_s": boundary_s-source_s}
    return [{"name": "source_boundary", "scope": "retain supplied boundary hypotheses, not measured"}, held,
        {"name": "outward_y_A", "acceleration": [0., .2, 0.], "jerk": [0.]*3, "scope": "synthetic A_y=+.2 m/s^2; J=0"},
        {"name": "outward_y_J", "acceleration": [0.]*3, "jerk": [0., 1., 0.], "scope": "synthetic A=0; J_y=+1 m/s^3"},
        {"name": "inward_y_J", "acceleration": [0.]*3, "jerk": [0., -1., 0.], "scope": "synthetic A=0; J_y=-1 m/s^3"}]


def hypothesis_request(base, profile):
    request = copy.deepcopy(base)
    if "acceleration" in profile:
        for axis in range(3):
            request["initial_pva"][axis][2] = profile["acceleration"][axis]
        request["initial_jerk"] = list(profile["jerk"])
        request["initial_jerk_assumption"] = profile["scope"]+"; not measured"
    request["initial_condition_scope"] = profile["scope"]+"; A/J measurement unqualified"
    return request


def temporal_scenarios(candidate, context, box, handoff):
    """Declared static world and ideal full PVA; never actual map/vehicle evidence."""
    start = candidate["start_sim_s"]
    native = candidate["native"]; duration = handoff.duration(native)

    def event(offset=0., **changes):
        now = start+offset
        return {"context": context, "now_sim_s": now, "state_source": "ideal reference PVA fixture",
            "observed_pva": handoff.pva(native, max(0., offset)).tolist(),
            "snapshot": {"context": context, "revision": "five-second-static-fixture",
                "known_space": "declared_static_configuration_space_fixture", "box": box, "voxels": [],
                "observed_sim_s": now, "valid_from_sim_s": start, "valid_until_sim_s": start+duration+2.}, **changes}

    first = event(candidate=candidate)
    current_only = event(candidate=candidate); current_only["snapshot"]["valid_until_sim_s"] = start+.6
    no_terminal = event(candidate=candidate); no_terminal["snapshot"]["valid_until_sim_s"] = start+duration
    finite = event(candidate=candidate); finite["snapshot"]["valid_until_sim_s"] = start+duration+.5
    finite_later = event(duration+.1); finite_later["snapshot"]["valid_until_sim_s"] = start+duration+.5
    unknown = event(candidate=candidate); unknown["snapshot"].pop("known_space")
    stale = event(candidate=candidate); stale["snapshot"]["observed_sim_s"] = start-.7
    missing_a = event(candidate=candidate)
    for axis in range(3): missing_a["observed_pva"][axis][2] = None
    late = event(.2, candidate=candidate); late["observed_pva"] = handoff.pva(native, 0.).tolist()
    drift = event(.2); drift["observed_pva"][1][2] += .2
    occupied = event(candidate=candidate)
    terminal = handoff.pva(native, duration)[:, 0]
    occupied["snapshot"]["voxels"] = [[(terminal-.01).tolist(), (terminal+.01).tolist()]]
    mismatch = event(candidate=candidate)
    mismatch["snapshot"]["context"] = {**context, "clock_id": "different-sim-clock"}
    return {"sufficient_declared_horizon": [first, event(.2), event(duration-.2), event(duration+.1)],
        "fresh_current_snapshot_only": [current_only], "curve_covered_terminal_window_missing": [no_terminal],
        "finite_terminal_window_expires": [finite, finite_later], "known_space_unverified": [unknown],
        "stale_observation": [stale], "measured_A_unknown": [missing_a], "late_submission_old_head": [late],
        "paused_sim_despite_wall_elapsed": [first, event(offline_wall_elapsed_s=10.)],
        "observed_A_changed": [first, drift], "terminal_occupied": [occupied], "clock_context_changed": [mismatch]}


def temporal_replay(candidate, task_id, start, box, limits, audit, handoff):
    row = {"kind": "axis_stop_geometry_candidate", "recorded_task_id": task_id,
        "trajectory_id": "conditional-axis-brake", "request": candidate["request"],
        "native": candidate["native"], "hard_box": box, "start_sim_s": start}
    context = {"task_id": task_id, "scene_revision": "declared-stop-box-fixture",
               "clock_id": "counterfactual-sim-epoch", "frame_id": "scene_enu_m"}
    scenarios = []
    for name, events in temporal_scenarios(row, context, box, handoff).items():
        replay = committed.Replay(context, limits, audit, handoff)
        log = []
        for event in events:
            try:
                result = replay.step(event)
            except (ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
                print(f"WARNING: {name}: malformed fixture item skipped: {error}")
                result = {**replay.protect("malformed_fixture_item"), "error": str(error)}
            gate = result.get("candidate_math_gate")
            if gate:
                result["candidate_math_gate"] = {k: gate.get(k) for k in ("passed", "failed_checks", "boundary_pva_error", "boundary_jerk_error")}
            log.append({"input": {k: v for k, v in event.items() if k != "candidate"}, "result": result})
        scenarios.append({"name": name, "events": log})
    return {"context": context, "candidate_start_sim_s": start, "curve_duration_sim_s": handoff.duration(candidate["native"]),
        "terminal_window_sim_s": .5, "required_until_at_admission_sim_s": start+handoff.duration(candidate["native"])+.5,
        "scope": "existing selector, ideal full-PVA and declared static space; not actual state/map or a terminal invariant set",
        "wall_clock_scope": "wall elapsed is never converted to simulation time", "scenarios": scenarios,
        "execution_admission": "not_performed"}


def run(source, root, executable, past=None):
    original = json.loads(source.read_text())
    audit, handoff = committed.reuse(root)
    rows = []
    for parent in original["rows"]:
        if "candidate" not in parent:
            continue
        try:
            if not np.all(np.isfinite([parent["pv_at_sim_s"], parent["event_sim_s"]])):
                raise ValueError("nonfinite source/event time")
            parent["variant"], parent["input_role"], parent["candidate"]["request"]
        except (KeyError, ValueError, TypeError) as error:
            print(f"WARNING: geometry row with incomplete boundary metadata skipped: {error}")
            rows.append({"variant": parent.get("variant"), "status": "unscored", "reason": "incomplete_boundary_metadata"})
            continue
        hypotheses = profiles(past, original["archive_task_id"], parent.get("pv_at_sim_s"), parent.get("event_sim_s"))
        for profile in hypotheses:
            row = {"variant": parent["variant"], "profile": profile,
                "pv_at_sim_s": parent["pv_at_sim_s"], "input_role": parent["input_role"]}
            if profile.get("status") == "unscored":
                print(f"WARNING: {parent['variant']}: optional {profile['name']} unqualified")
                rows.append({**row, "status": "unscored", "reason": profile["reason"]}); continue
            try:
                request = hypothesis_request(parent["candidate"]["request"], profile)
                fixed = geometry.tracking.audit_axis_request(request, original["hard_box"], original["hard_limits"], executable, audit)
                row.update(status=fixed["status"], fixed=fixed)
                if fixed.get("audit", {}).get("passed"):
                    if profile["name"] == "source_boundary":
                        row["temporal"] = temporal_replay(fixed, original["archive_task_id"], parent["pv_at_sim_s"],
                            original["hard_box"], original["hard_limits"], audit, handoff)
                elif fixed["status"] == "audited":
                    row["resolved"] = geometry.search(request, original["hard_box"], original["hard_limits"], executable, audit)
            except (KeyError, ValueError, TypeError, IndexError, AttributeError) as error:
                print(f"WARNING: {parent['variant']}/{profile['name']}: this hypothesis skipped: {error}")
                row.update(status="unscored", reason=str(error))
            rows.append(row)
    return {"schema_version": 1, "archive_task_id": original["archive_task_id"], "source": str(source),
        "kind": "offline_stop_boundary_and_temporal_qualification", "hard_box": original["hard_box"],
        "hard_limits": original["hard_limits"], "scope": "finite named A/J hypotheses, not a robust uncertainty certificate",
        "actual_qualification": {"measured_A_J": "unrecorded", "current_known_map": "unqualified",
            "future_free_volume": "unqualified", "terminal_region": "unqualified", "dynamic_closed_loop": "not_passed"},
        "rows": rows, "execution_admission": "not_performed"}


def handoff_inputs(past, task_id, anchor_s, boundary_s):
    """Recorder-available prediction and exact-source retrospective PV stay separate."""
    names = ("causal_acceleration", "retrospective_source_pv")
    results = {name: {"status": "unscored", "reason": "past_report_unqualified"} for name in names}
    if not isinstance(past, dict) or past.get("archive_task_id") != task_id:
        return results
    forecast = past.get("forecast")
    cases = forecast.get("cases") if isinstance(forecast, dict) else None
    if not isinstance(cases, list) or not np.all(np.isfinite([anchor_s, boundary_s])):
        return results
    pairs, oracles = [], []
    for case in cases:
        if not isinstance(case, dict):
            continue
        anchor, previous = case.get("input_state"), case.get("previous_available_state")
        if (case.get("kind") == "fsm" and geometry.tracking.usable_pv(anchor)
                and geometry.tracking.usable_pv(previous)
                and anchor["source_sim_s"] == anchor_s
                and previous["source_sim_s"] < anchor_s):
            pairs.append((anchor, previous, case.get("forecast_at_sim_s")))
        try:
            pv = np.asarray([case["oracle_position"], case["oracle_velocity"]], dtype=float)
            if (abs(case["oracle_source_sim_s"]-boundary_s) < 1e-9
                    and pv.shape == (2, 3) and np.all(np.isfinite(pv))):
                oracles.append(pv)
        except (KeyError, TypeError, ValueError):
            continue
    if pairs:
        anchor, previous, located_at = pairs[0]
        same = all(a == anchor and p == previous for a, p, _ in pairs)
        available = max(geometry.tracking.recorded_availability(anchor), geometry.tracking.recorded_availability(previous))
        if not same:
            results[names[0]]["reason"] = "ambiguous_past_pair"
        elif available > boundary_s or anchor_s > boundary_s:
            results[names[0]]["reason"] = "past_pair_unavailable_at_boundary"
        else:
            estimate = geometry.tracking.predict_pv(anchor, boundary_s, names[0], previous)
            results[names[0]] = {"status": "qualified_counterfactual", **estimate,
                "anchor_state": copy.deepcopy(anchor), "previous_state": copy.deepcopy(previous),
                "available_by_sim_s": available, "pair_locator_fsm_sim_s": located_at,
                "scope": "recorder-available counterfactual prediction; not earlier planner consumption or measured A"}
    if oracles and all(np.array_equal(pv, oracles[0]) for pv in oracles):
        results[names[1]] = {"status": "qualified_counterfactual", "source_sim_s": boundary_s,
            "position": oracles[0][0].tolist(), "velocity": oracles[0][1].tolist(),
            "scope": "exact-source retrospective PV only; not causal input or measured A/J"}
    else:
        results[names[1]]["reason"] = "exact_source_oracle_missing_or_conflicting"
    return results


def acceleration_peak(native, audit):
    """Locate the existing continuous norm maximum; do not replace its gate."""
    best = {"value": -1.}; elapsed = 0.
    for index, piece in enumerate(native["pieces"]):
        power = audit.derivative(audit.normalized_power(piece), piece["duration"], 2)
        peak = audit.norm_maximum(power)
        if peak["value"] > best["value"]:
            best = {**peak, "piece_index": index, "local_sim_s": peak["u"]*piece["duration"],
                "elapsed_sim_s": elapsed+peak["u"]*piece["duration"],
                "vector_m_s2": np.polynomial.polynomial.polyval(peak["u"], power).tolist()}
        elapsed += piece["duration"]
    return best


def compare_handoffs(source, root, executable, past=None, times=(33.248, 33.388, 33.428)):
    """Predeclared finite timing comparison, with the existing search unchanged."""
    original = json.loads(source.read_text())
    result = {"schema_version": 1, "archive_task_id": original["archive_task_id"], "source": str(source),
        "kind": "offline_earlier_stop_handoff_comparison", "boundary_times_sim_s": [],
        "hard_box": original["hard_box"], "hard_limits": original["hard_limits"],
        "scope": "same recorded pair, finite A/J profiles and search bounds; not an online handoff or ICS proof",
        "actual_qualification": {"measured_A_J": "unrecorded", "current_known_map": "unqualified", "future_free_volume": "unqualified",
            "terminal_region": "unqualified", "dynamic_closed_loop": "not_passed"},
        "rows": [], "excluded": [], "execution_admission": "not_performed"}
    try:
        cached = next(r for r in original["rows"] if isinstance(r, dict) and r.get("variant") == "cached_source_pv")
        baseline = cached["baseline"]["request"]
        anchor_s = cached["pv_at_sim_s"]
        head = np.asarray(baseline["initial_pva"], dtype=float)
        if head.shape != (3, 3) or not np.all(np.isfinite(np.r_[head.ravel(), anchor_s])):
            raise ValueError("finite source PVA and time required")
    except (KeyError, TypeError, ValueError, StopIteration, IndexError) as error:
        print(f"WARNING: earlier handoff template unavailable: {error}")
        return {**result, "status": "unscored", "reason": "source_boundary_template_unavailable"}
    audit, _ = committed.reuse(root)
    declared = {p["name"]: p for p in profiles(None, original["archive_task_id"])}
    selected = (("causal_acceleration", "source_boundary"), ("causal_acceleration", "outward_y_A"),
        ("retrospective_source_pv", "source_boundary"), ("retrospective_source_pv", "outward_y_A"),
        ("retrospective_source_pv", "outward_y_J"))
    result.update(anchor_source_sim_s=anchor_s, selected_profiles=[list(p) for p in selected])
    for at in times:
        if not isinstance(at, (int, float)) or not np.isfinite(at):
            print(f"WARNING: nonfinite or invalid handoff time skipped: {at}")
            result["excluded"].append({"requested_time": str(at), "reason": "invalid_boundary_time"})
            continue
        result["boundary_times_sim_s"].append(at)
        inputs = handoff_inputs(past, original["archive_task_id"], anchor_s, at)
        for variant, name in selected:
            evidence = inputs[variant]
            row = {"boundary_sim_s": at, "variant": variant, "profile": declared[name], "input": evidence}
            if evidence["status"] != "qualified_counterfactual":
                print(f"WARNING: {at}/{variant}/{name}: {evidence['reason']}")
                result["rows"].append({**row, "status": "unscored", "reason": evidence["reason"]})
                continue
            request = hypothesis_request(baseline, declared[name])
            for axis in range(3):
                request["initial_pva"][axis][:2] = [evidence["position"][axis], evidence["velocity"][axis]]
            try:
                resolved = geometry.search(request, original["hard_box"], original["hard_limits"], executable, audit)
                row.update(status=resolved["status"], resolved=resolved)
                if "candidate" in resolved:
                    row["acceleration_peak"] = acceleration_peak(resolved["candidate"]["native"], audit)
            except (KeyError, ValueError, TypeError, IndexError, AttributeError) as error:
                print(f"WARNING: {at}/{variant}/{name}: this comparison skipped: {error}")
                row.update(status="unscored", reason=str(error))
            result["rows"].append(row)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry-report", type=Path, required=True)
    parser.add_argument("--stopping-report", type=Path, help="Optional original forecast evidence for past-A hypothesis")
    parser.add_argument("--earlier-handoff", action="store_true", help="Compare fixed earlier boundaries using recorder-available inputs")
    parser.add_argument("--handoff-times", type=float, nargs="+", default=[33.248, 33.388, 33.428])
    parser.add_argument("--drone-root", type=Path, default=Path.home()/"dev/ros2/projects/drone")
    parser.add_argument("--native", type=Path, default=Path.home()/".cache/ros2-drone/minco-probe/minco_probe")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    past = None
    if args.stopping_report:
        try: past = json.loads(args.stopping_report.read_text())
        except (OSError, ValueError) as error: print(f"WARNING: optional past-A evidence unavailable: {error}")
    operation = compare_handoffs if args.earlier_handoff else run
    result = operation(args.geometry_report, args.drone_root, args.native, past,
        **({"times": args.handoff_times} if args.earlier_handoff else {}))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"profiles": len(result["rows"]), ("comparison_passes" if args.earlier_handoff else "fixed_passes"): sum(r.get("resolved", {}).get("candidate", {}).get("audit", {}).get("passed", False)
        if args.earlier_handoff else r.get("fixed", {}).get("audit", {}).get("passed", False) for r in result["rows"]),
        "temporal_fixture_sets": sum("temporal" in r for r in result["rows"]), "execution_admission": "not_performed"}))
