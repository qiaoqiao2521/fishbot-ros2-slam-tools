#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Same-coefficient offline qualification of existing GCOPTER root interfaces."""
import argparse
from collections import Counter
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


def native_search_metrics(native,exchange):
    """Existing diagnostic mode, not a replacement for the final hard gate."""
    response=exchange({"mode":"rootfinder_extrema","pieces":native["pieces"]})
    if not response.get("native_success"):
        raise ValueError(response.get("error","native extrema unavailable"))
    keys=("upper","lower","acceleration_peak_m_s2","minimum_y_velocity_m_s",
        "minimum_y_velocity_at_s","reverse_y_speed_m_s")
    metrics={key:response[key] for key in keys}
    for key in ("upper","lower"):
        if np.asarray(metrics[key]).shape!=(3,):raise ValueError("native extrema needs three-axis ranges")
    if not np.all(np.isfinite(np.r_[metrics["upper"],metrics["lower"],[metrics[key] for key in keys[2:]]])):
        raise ValueError("native extrema returned nonfinite metrics")
    return metrics


def search_summary(rows):
    """A fast rejected search is not a successful-search timing sample."""
    def outcomes(selected):
        timing={}
        for outcome in ("math_passed","math_rejected","unscored"):
            group=[r for r in selected if (r["status"]=="unscored" if outcome=="unscored" else
                r["status"]=="audited" and bool(r.get("math_passed"))==(outcome=="math_passed")) and "wall_s" in r]
            if group:
                values=[r["wall_s"] for r in group]
                timing[outcome]={"samples":len(values),"minimum_s":min(values),"median_s":float(np.median(values)),"maximum_s":max(values)}
        return timing
    backends={backend:[r for r in rows if r.get("backend")==backend] for backend in ("python","rootfinder")}
    return {"summary":{backend:{"searches":len(selected),"audited":sum(r["status"]=="audited" for r in selected),
            "unscored":sum(r["status"]=="unscored" for r in selected),
            "math_passed":sum(r.get("math_passed",False) for r in selected),
            "optimizer_success":sum(r.get("optimizer",{}).get("success",False) for r in selected),
            "final_rejection_counts":dict(Counter(reason for r in selected for reason in r.get("final_rejections",[])))}
            for backend,selected in backends.items() if selected},
        "wall_summary":{backend:outcomes(selected) for backend,selected in backends.items() if selected},
        "wall_by_profile":{profile:{backend:outcomes([r for r in selected if r.get("profile")==profile])
            for backend,selected in backends.items() if any(r.get("profile")==profile for r in selected)}
            for profile in sorted({r["profile"] for r in rows if "backend" in r})}}


def run_search(source,root,executable,*,variant_id="reference-7-h0.05",profile_names=("zero_A_J",),
               repetitions=3,max_iterations=60,derivative_method=None,constrain_acceleration=False):
    """Complete paired offline searches; keep failures and lifecycle costs."""
    audit,_=geometry.tracking.load("stop_candidates",Path(__file__).with_name("drone-stop-candidates.py")).load_modules(root)
    result={"kind":"offline_extrema_backend_search_comparison","archive_task_id":source.get("archive_task_id"),
        "variant_id":variant_id,"rows":[],"warnings":[],"configuration":{"y_inner":True,"z_time_bounds":[.1,1.2],
            "max_iterations":max_iterations,"planning_inset":.002},
        "scope":"archived boundary and finite A/J hypotheses in a declared static box; not online admission or dynamic accept rate",
        "timing_scope":"complete search including owned process creation and close; serial pairs alternate backend order",
        "execution_admission":"not_performed","dynamic_closed_loop":"not_passed"}
    if repetitions<1:raise ValueError("positive repetitions required")
    if derivative_method is not None:
        result["configuration"]["derivative_method"]=derivative_method
    if constrain_acceleration:
        result["configuration"]["constrain_acceleration"]=True
    for profile in profile_names:
        try:
            matches=[r for r in source["rows"] if isinstance(r,dict) and r.get("variant_id")==variant_id
                and isinstance(r.get("profile"),dict) and r["profile"].get("name")==profile]
            if len(matches)!=1:raise ValueError("one archived variant/profile required")
            original=matches[0];base=original["boundary_request"];box=original["hard_box"];limits=original["hard_limits"]
            # These are the original seed and causal PV provenance, not the
            # previously optimized endpoint used as a more favorable seed.
            source_input={k:copy.deepcopy(original[k]) for k in ("input","boundary_request","hard_box","hard_limits","start_sim_s","profile")}
        except (KeyError,ValueError,TypeError) as error:
            result["warnings"].append(f"{profile}: {error}")
            result["rows"].append({"profile":profile,"status":"unscored","reason":str(error)})
            continue
        for repetition in range(repetitions):
            order=("python","rootfinder") if repetition%2==0 else ("rootfinder","python")
            for backend in order:
                row={"profile":profile,"repetition":repetition,"backend":backend,"pair_order":list(order),
                    "source_input":source_input,"execution_admission":"not_performed"}
                result["rows"].append(row)
                counters={"generation_calls":0,"extrema_requests":0,"metrics_calls":0,
                    "native_exchange_wall_s":0.,"metrics_wall_s":0.}
                session=None;began=time.perf_counter()
                try:
                    with sessions.NativeSession(executable,timeout=1.) as session:
                        def exchange(request):
                            counters["extrema_requests" if request.get("mode")=="rootfinder_extrema" else "generation_calls"]+=1
                            start=time.perf_counter()
                            try:return session.exchange(request)
                            finally:counters["native_exchange_wall_s"]+=time.perf_counter()-start
                        def metrics(native,current_audit):
                            counters["metrics_calls"]+=1;start=time.perf_counter()
                            try:
                                return geometry.extrema(native,current_audit) if backend=="python" else native_search_metrics(native,exchange)
                            finally:counters["metrics_wall_s"]+=time.perf_counter()-start
                        resolved=geometry.search(base,box,limits,executable,audit,exchange=exchange,
                            metrics_backend=metrics,**result["configuration"])
                    row.update(status=resolved["status"],resolved=resolved)
                    if resolved["status"]=="audited":
                        candidate=resolved["candidate"]
                        row.update(math_passed=bool(candidate["audit"]["passed"]),
                            final_rejections=list(candidate["audit"]["failed_checks"]),optimizer=resolved["optimizer"])
                    else:row["reason"]=resolved.get("reason")
                except (ValueError,KeyError,TypeError,OSError,AttributeError) as error:
                    row.update(status="unscored",reason=str(error));result["warnings"].append(f"{profile}/{repetition}/{backend}: {error}")
                row.update(wall_s=time.perf_counter()-began,counters=counters,
                    owned_process_exited=session.process.poll() is not None if session is not None else None)
                if row["status"]=="audited":
                    try:
                        row["python_final_metrics"]=geometry.extrema(row["resolved"]["candidate"]["native"],audit)
                        row["final_metric_absolute_differences"]={key:float(np.max(abs(np.asarray(row["python_final_metrics"][key])-row["resolved"]["diagnostics"][key])))
                            for key in ("upper","lower","acceleration_peak_m_s2","minimum_y_velocity_m_s","reverse_y_speed_m_s")}
                    except (ValueError,KeyError,TypeError) as error:
                        row["final_metric_readback_error"]=str(error)
    result.update(search_summary(result["rows"]))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reanchor-report",type=Path,required=True)
    parser.add_argument("--drone-root",type=Path,default=Path.home()/"dev/ros2/projects/drone")
    parser.add_argument("--native",type=Path,default=Path.home()/".cache/ros2-drone/minco-s4-metrics/minco_s4_metrics")
    parser.add_argument("--repetitions",type=int,default=3)
    parser.add_argument("--compare-search",action="store_true")
    parser.add_argument("--variant-id",default="reference-7-h0.05")
    parser.add_argument("--profiles",nargs="+",default=["zero_A_J"])
    parser.add_argument("--derivative-method",choices=["3-point"],default=None,
        help="Explicit SciPy central-difference experiment; default retains the original absolute-step path")
    parser.add_argument("--constrain-acceleration",action="store_true",
        help="Explicitly pass the existing acceleration limit as an optimizer inequality; final gate remains independent")
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    source=json.loads(args.reanchor_report.read_text())
    result=(run_search(source,args.drone_root,args.native,variant_id=args.variant_id,profile_names=args.profiles,
        repetitions=args.repetitions,derivative_method=args.derivative_method,constrain_acceleration=args.constrain_acceleration)
        if args.compare_search else run(source,args.drone_root,args.native,repetitions=args.repetitions))
    if not args.compare_search and (args.derivative_method is not None or args.constrain_acceleration):
        message="optimization options were not applied: fixed-coefficient comparison has no optimizer; use --compare-search"
        result["warnings"].append(message)
        print("WARNING: "+message)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    print(json.dumps(result["summary"],ensure_ascii=False))


if __name__=="__main__":main()
