#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Same-coefficient offline qualification of existing GCOPTER root interfaces."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import time

import numpy as np


def load(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+".py"))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


geometry=load("drone-stop-geometry")
sessions=load("drone-native-session")


def official_negatives(executable):
    """Known analytical counterexamples, each isolated by an owned deadline."""
    rows=[]
    for name,duration,power,coefficient,expected in (
            ("short_acceleration",1e-6,3,1/(6e-6),1.),
            ("monomial_acceleration",1.,7,1e-5,.00042)):
        coeff=np.zeros((3,8));coeff[0,7-power]=coefficient
        request={"mode":"official_piece_rates","rate":"acceleration",
            "pieces":[{"duration":duration,"coefficients_descending":coeff.tolist()}]}
        row={"name":name,"request":request,"analytical_acceleration_peak_m_s2":expected}
        for label,mode,timeout in (("official","official_piece_rates",.25),("rootfinder","rootfinder_extrema",1.)):
            began=time.perf_counter();session=None
            try:
                session=sessions.NativeSession(executable,timeout=timeout)
                with session:response=session.exchange({**request,"mode":mode})
                row[label+"_result"]=response
                row[label+"_status"]="compared" if response.get("native_success") else "unscored"
            except (ValueError,OSError,TypeError,AttributeError) as error:
                row[label+"_error"]=str(error);row[label+"_status"]="unscored"
            row[label+"_wall_s"]=time.perf_counter()-began
            row[label+"_owned_process_exited"]=session.process.poll() is not None if session is not None else None
        rows.append(row)
    return rows


def python_extrema(native,audit):
    metrics=geometry.extrema(native,audit)
    metrics["velocity_peak_m_s"]=max(audit.norm_maximum(audit.derivative(audit.normalized_power(p),p["duration"]))["value"]
        for p in native["pieces"])
    return metrics


def differences(left,right):
    keys=("upper","lower","acceleration_peak_m_s2","velocity_peak_m_s",
        "minimum_y_velocity_m_s","reverse_y_speed_m_s")
    return {key:float(np.max(abs(np.asarray(left[key])-right[key]))) for key in keys}


def run(source,root,executable,*,repetitions=3):
    """Compare fixed curves; do not replace search metrics or the hard gate."""
    audit,handoff=geometry.tracking.load("stop_candidates",Path(__file__).with_name("drone-stop-candidates.py")).load_modules(root)
    result={"kind":"offline_same_coefficient_extrema_qualification","rows":[],"warnings":[],
        "scope":"fixed archived tails and finite analytical fixtures; no optimizer-path equivalence or real-time qualification",
        "comparison_tolerance":1e-8,"execution_admission":"not_performed","dynamic_closed_loop":"not_passed"}
    if repetitions<1:raise ValueError("positive repetitions required")
    result["official_negative_probes"]=official_negatives(executable)
    for index,original in enumerate(source.get("rows",[])):
        row={"source_index":index}
        result["rows"].append(row)
        try:
            row.update(variant_id=original.get("variant_id"),profile=original.get("profile",{}).get("name"))
            candidate=original["resolved"]["candidate"];native=candidate["native"]
            before=copy.deepcopy(candidate)
            wall={"python":[],"rootfinder_exchange":[],"rootfinder_internal":[]}
            with sessions.NativeSession(executable,timeout=1.) as session:
                for _ in range(repetitions):
                    began=time.perf_counter();reference=python_extrema(native,audit)
                    wall["python"].append(time.perf_counter()-began)
                    began=time.perf_counter();metrics=session.exchange({"mode":"rootfinder_extrema","pieces":native["pieces"]})
                    wall["rootfinder_exchange"].append(time.perf_counter()-began)
                    if not metrics.get("native_success"):raise ValueError(metrics.get("error","native extrema unavailable"))
                    wall["rootfinder_internal"].append(metrics["elapsed_ms"]/1000.)
            delta=differences(reference,metrics)
            # Equal minima need not have a unique argmin. Check the value at
            # the returned time instead of demanding identical timestamps.
            actual_vy=float(handoff.pva(native,metrics["minimum_y_velocity_at_s"])[1,1])
            score=audit.audit_trajectory(native,candidate["request"],[],original["hard_limits"],original["hard_box"])
            knots=geometry.audit_axis_knots(native,candidate["request"],audit)
            row.update(status="compared",python_metrics=reference,rootfinder_metrics=metrics,
                maximum_absolute_differences=delta,reported_minimum_time_value_error=abs(actual_vy-metrics["minimum_y_velocity_m_s"]),
                same_coefficients_and_request=candidate==before,independent_hard_audit=score,
                hard_audit_unchanged=score==candidate["audit"],axis_knots_unchanged=knots==candidate["axis_knot_contract"],
                wall_s=wall,owned_process_exited=session.process.poll() is not None)
            row["comparison_passed"]=(max(delta.values())<=1e-8 and row["reported_minimum_time_value_error"]<=1e-8
                and row["same_coefficients_and_request"] and row["hard_audit_unchanged"] and row["axis_knots_unchanged"])
        except (KeyError,ValueError,TypeError,OSError,IndexError,AttributeError) as error:
            row.update(status="unscored",reason=str(error));result["warnings"].append(f"row {index}: {error}")
    result["summary"]={"rows":len(result["rows"]),"compared":sum(r["status"]=="compared" for r in result["rows"]),
        "comparison_passed":sum(r.get("comparison_passed",False) for r in result["rows"])}
    result["timing_scope"]="per-call fixed-curve diagnostics; native exchange uses an already open owned process; lifecycle excluded"
    result["timing_summary"]={mode:{"samples":len(values),"minimum_s":min(values),"median_s":float(np.median(values)),"maximum_s":max(values)}
        for mode in ("python","rootfinder_exchange","rootfinder_internal")
        if (values:=[t for r in result["rows"] if r["status"]=="compared" for t in r["wall_s"][mode]])}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reanchor-report",type=Path,required=True)
    parser.add_argument("--drone-root",type=Path,default=Path.home()/"dev/ros2/projects/drone")
    parser.add_argument("--native",type=Path,default=Path.home()/".cache/ros2-drone/minco-s4-metrics/minco_s4_metrics")
    parser.add_argument("--repetitions",type=int,default=3)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=run(json.loads(args.reanchor_report.read_text()),args.drone_root,args.native,repetitions=args.repetitions)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    print(json.dumps(result["summary"],ensure_ascii=False))


if __name__=="__main__":main()
