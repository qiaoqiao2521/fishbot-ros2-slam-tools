#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Recorded PV versus reference handoffs; no state completion or control."""
import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name+".py"))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


tracking = load("drone-recorded-tracking")
NUMERIC_REFERENCE_TOLERANCE = 1e-7


def availability_ns(state):
    value = tracking.recorded_availability(state)
    return round(value*1e9) if np.isfinite(value) else None


def state_view(state):
    return {k: state.get(k) for k in ("source_stamp_ns", "source_sim_s", "record_time_ns", "frame_id",
        "velocity_frame_id", "epoch", "position", "velocity", "availability_clock_bracket")} | {
        "available_by_sim_ns": availability_ns(state), "vehicle_acceleration": None, "vehicle_jerk": None}


def unique_group(states):
    if not states:
        return None, "no_matching_source"
    if any(s[key] != states[0][key] for s in states for key in ("position", "velocity")):
        return None, "conflicting_source_stamp"
    return min(states, key=tracking.recorded_availability), None


def select_inputs(states, cut_ns, single_epoch=True):
    if not single_epoch:
        return {"exact": None, "exact_reason": "ambiguous_clock_epoch", "anchor": None,
            "anchor_reason": "ambiguous_clock_epoch", "eligible_states": 0,
            "excluded_frame_epoch_or_invalid": len(states)}
    eligible = [s for s in states if single_epoch and isinstance(s, dict) and tracking.usable_pv(s)]
    exact, exact_reason = unique_group([s for s in eligible if int(s["source_stamp_ns"]) == cut_ns])
    available = [s for s in eligible if availability_ns(s) is not None
        and int(s["source_stamp_ns"]) <= availability_ns(s) <= cut_ns]
    latest_ns = max((int(s["source_stamp_ns"]) for s in available), default=None)
    anchor, anchor_reason = unique_group([s for s in available if int(s["source_stamp_ns"]) == latest_ns])
    return {"exact": exact, "exact_reason": exact_reason, "anchor": anchor, "anchor_reason": anchor_reason,
        "eligible_states": len(eligible), "excluded_frame_epoch_or_invalid": len(states)-len(eligible)}


def pv_difference(position, velocity, reference_pv):
    dp = np.asarray(position)-reference_pv[:,0]; dv = np.asarray(velocity)-reference_pv[:,1]
    pn, vn = float(np.linalg.norm(dp)), float(np.linalg.norm(dv))
    return {"position_difference_xyz_m": dp.tolist(), "velocity_difference_xyz_m_s": dv.tolist(),
        "position_difference_norm_m": pn, "velocity_difference_norm_m_s": vn,
        "numeric_reference_PV_match": pn <= NUMERIC_REFERENCE_TOLERANCE and vn <= NUMERIC_REFERENCE_TOLERANCE,
        "numeric_scope": "existing offline regression tolerance; not calibrated physical tracking bound"}


def branch(position, velocity, reference_pv, box, limits, margin_lower, margin_upper):
    difference = pv_difference(position, velocity, reference_pv)
    necessary = tracking.stopping_necessary(position, velocity, box, limits["acceleration"])
    necessary["initial_acceleration_and_jerk"] = "vehicle A/J unknown; optimistic PV model ignores continuity"
    faces = []
    for axis, name in enumerate("xyz"):
        for side, sign, margin in (("lower",-1,margin_lower[axis]),("upper",1,margin_upper[axis])):
            outward = max(0., sign*difference["position_difference_xyz_m"][axis])
            faces.append({"face": name+"_"+side, "nominal_whole_path_margin_m": float(margin),
                "outward_cut_P_difference_m": outward, "difference_exceeds_nominal_margin": bool(outward > margin)})
    return {**difference, "necessary_reference_model": necessary, "directional_margin_comparison": faces,
        "margin_scope": "one-time PV difference versus nominal whole-path margins; not a translated trajectory, future bound or collision proof",
        "full_state_handoff": "unqualified", "vehicle_acceleration": None, "vehicle_jerk": None}


def run(reports, states, epochs, root, task_id):
    candidates, geometry = load("drone-stop-candidates"), load("drone-stop-geometry")
    audit, handoff = candidates.load_modules(root)
    rows = []; warnings = []
    for report in reports:
        if not isinstance(report, dict) or not isinstance(report.get("rows"), list):
            warnings.append("optional candidate report must be an object with rows array; report skipped"); continue
        if report.get("archive_task_id") != task_id:
            warnings.append("candidate report task identity mismatch; report skipped"); continue
        for item in report.get("rows", []):
            row = {"variant_id": item.get("variant_id") if isinstance(item,dict) else None,
                "execution_admission": "not_performed"}
            try:
                if (not isinstance(item,dict) or item.get("status") != "generated"
                        or not item["result"]["candidate"]["full_math_gate"]["passed"]
                        or not item["result"]["narrow_box_gate"]["passed"]):
                    continue
                rows.append(row)
                c = item["result"]["candidate"]; start = c["start_sim_s"]; cut = c["cut_sim_s"]
                prefix = {"native_success": True, "pieces": c["prefix_pieces"]}
                duration = sum(p["duration"] for p in prefix["pieces"])
                if (c.get("recorded_task_id") != task_id or not np.all(np.isfinite([start,cut,duration]))
                        or abs(cut-start-duration) > 1e-8):
                    raise ValueError("candidate_identity_or_prefix_time_mismatch")
                cut_ns = round(cut*1e9); cut_s = cut_ns/1e9
                reference_pv = handoff.pva(prefix,duration)[:,:2]
                box = np.asarray(report["narrow_box_fixture"]); limits = report["limits"]
                bounds = geometry.extrema({"pieces": c["prefix_pieces"]+c["native"]["pieces"]}, audit)
                margin_lower = np.asarray(bounds["lower"])-box[0]; margin_upper = box[1]-bounds["upper"]
                row.update(status="unscored", source_reference_PV=reference_pv.tolist(), cut_sim_s=cut,
                    comparison_cut_ns=str(cut_ns), comparison_cut_s=cut_s,
                    cut_rounding_scope="nearest integer ns; no nearest-frame matching or interpolation",
                    historical_timing=item["timing"], nominal_face_margins_m={"lower":margin_lower.tolist(),"upper":margin_upper.tolist()})
                selected = select_inputs(states,cut_ns,epochs==1)
                exact = selected["exact"]
                row["exact_cut_retrospective"] = ({"status":"compared","source_state":state_view(exact),
                    "available_by_cut": availability_ns(exact) is not None and availability_ns(exact)<=cut_ns,
                    **branch(exact["position"],exact["velocity"],reference_pv,box,limits,margin_lower,margin_upper)}
                    if exact else {"status":"unscored","reason":selected["exact_reason"]})
                if exact is not None:
                    row["status"] = "compared"
                anchor = selected["anchor"]
                if anchor is None:
                    row["recorder_available_CV"] = {"status":"unscored","reason":selected["anchor_reason"]}; continue
                prediction = tracking.predict_pv(anchor,cut_s,"constant_velocity")
                if prediction is None:
                    row["recorder_available_CV"] = {"status":"unscored","reason":"source_float_time_after_cut"}; continue
                causal = {"status":"compared_to_reference_not_oracle_accuracy", "source_state":state_view(anchor),
                    "source_age_s": cut_s-anchor["source_sim_s"], "availability_age_s":(cut_ns-availability_ns(anchor))/1e9,
                    "input_scope":"recorder clock upper bound; not planner consumption ACK",
                    "model":"constant_velocity", "model_acceleration":prediction["model_acceleration"],
                    "predicted_position":prediction["position"], "predicted_velocity":prediction["velocity"],
                    **branch(prediction["position"],prediction["velocity"],reference_pv,box,limits,margin_lower,margin_upper)}
                source_t = anchor["source_sim_s"]
                if start <= source_t <= cut:
                    at_source = handoff.pva(prefix,source_t-start)[:,:2]
                    causal["observed_same_source_stamp"] = {"status":"compared", "reference_PV":at_source.tolist(),
                        **pv_difference(anchor["position"],anchor["velocity"],at_source),
                        "scope":"recorded older-source PV; not a measurement at the cut"}
                else:
                    causal["observed_same_source_stamp"] = {"status":"unscored","reason":"source_outside_selected_reference_prefix; no extrapolation"}
                row["recorder_available_CV"] = causal
                row["status"] = "compared"
            except (ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
                if row not in rows: rows.append(row)
                row.update(status="unscored",reason=str(error)); warnings.append(f"{row['variant_id']}: {error}")
    compared = [r for r in rows if r.get("status")=="compared"]
    cv = [r["recorder_available_CV"] for r in compared if r.get("recorder_available_CV",{}).get("model")=="constant_velocity"]
    return {"schema_version":1,"archive_task_id":task_id,"kind":"offline_recorded_PV_reference_handoff_comparison",
        "source":"Gazebo ideal odometry /drone/ego/odom; causal pose-difference V, not PX4 full PVA",
        "clock_epochs":epochs,"state_count":len(states),"warnings":warnings,
        "numeric_reference_tolerance":NUMERIC_REFERENCE_TOLERANCE,
        "summary":{"selected_variants":len(rows),"compared":len(compared),
            "exact_cut_compared":sum(r["exact_cut_retrospective"]["status"]=="compared" for r in compared),
            "recorder_available_CV_compared":len(cv),"CV_numeric_PV_matches":sum(r["numeric_reference_PV_match"] for r in cv),
            "full_state_handoffs_qualified":0},
        "qualification":{"vehicle_A_J":"unknown","tracking_tube":"uncalibrated","live_map":"unqualified",
            "terminal_region":"unqualified","clock_deadline":"unqualified","PX4_adoption":"not_performed"},
        "dynamic_closed_loop":"not_passed","execution_admission":"not_performed","rows":rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates",type=Path,nargs="+",required=True)
    parser.add_argument("--run-dir",type=Path,required=True)
    parser.add_argument("--drone-root",type=Path,default=Path.home()/"dev/ros2/projects/drone")
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();reports=[]
    for path in args.candidates:
        try:reports.append(json.loads(path.read_text()))
        except (OSError,ValueError) as error:print(f"WARNING: optional candidate report skipped: {path.name}: {error}")
    task_id=json.loads((args.run_dir/"request.json").read_text())["id"]
    states,_,epochs=tracking.read_odometry(args.run_dir)
    result=run(reports,states,epochs,args.drone_root,task_id)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps(result["summary"]))


if __name__=="__main__":main()
