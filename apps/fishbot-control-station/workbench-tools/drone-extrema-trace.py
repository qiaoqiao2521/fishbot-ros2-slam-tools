#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Read-only optimizer queries, first stencils and same-coefficient diagnostics."""
import argparse
import copy
import json
from pathlib import Path
import time

import numpy as np

import importlib.util
spec=importlib.util.spec_from_file_location("extrema_qualification",Path(__file__).with_name("drone-extrema-qualification.py"))
qualification=importlib.util.module_from_spec(spec);spec.loader.exec_module(qualification)
geometry=qualification.geometry


def quantities(event,metrics=None):
    metrics=event["metrics"] if metrics is None else metrics
    return np.r_[metrics["acceleration_peak_m_s2"],metrics["upper"],metrics["lower"]]


def stencil(events):
    """Reconstruct the observed forward/adjusted stencil using actual dx."""
    if len(events)<7:return {"status":"unscored","reason":"fewer_than_seven_unique_evaluations"}
    rows=events[:7];head=np.asarray(rows[0]["values"]);columns={};margin_columns={};steps={}
    for row in rows[1:]:
        dx=np.asarray(row["values"])-head;changed=np.flatnonzero(dx)
        if len(changed)!=1 or int(changed[0]) in columns:
            return {"status":"unscored","reason":"not_a_six_axis_stencil"}
        axis=int(changed[0]);columns[axis]=(quantities(row)-quantities(rows[0]))/dx[axis];steps[axis]=float(dx[axis])
        if "planning_margins" in row and "planning_margins" in rows[0]:
            margin_columns[axis]=(np.asarray(row["planning_margins"])-rows[0]["planning_margins"])/dx[axis]
    if set(columns)!=set(range(6)):return {"status":"unscored","reason":"incomplete_axes"}
    return {"status":"observed","head":head.tolist(),"actual_steps":[steps[i] for i in range(6)],
        "quantity_order":["acceleration_peak","upper_x","upper_y","upper_z","lower_x","lower_y","lower_z"],
        "quantity_jacobian":np.column_stack([columns[i] for i in range(6)]).tolist(),
        "actual_margin_jacobian":np.column_stack([margin_columns[i] for i in range(6)]).tolist() if len(margin_columns)==6 else None,
        "scope":"observed value differences; not exact derivatives or a KKT certificate"}


def piece_peaks(native,audit):
    rows=[];elapsed=0.
    for index,piece in enumerate(native["pieces"]):
        peak=audit.norm_maximum(audit.derivative(audit.normalized_power(piece),piece["duration"],2))
        rows.append({"piece_index":index,"value":peak["value"],"unit_time":peak["u"],
            "elapsed_s":elapsed+piece["duration"]*peak["u"]})
        elapsed+=piece["duration"]
    return rows


def compare_queries(left,right):
    common=0
    for a,b in zip(left,right):
        if a["values"]!=b["values"]:break
        common+=1
    return {"identical_input_prefix":common,
        "first_distinct_queries":{name:rows[common]["values"] if common<len(rows) else None
            for name,rows in (("python",left),("rootfinder",right))},
        "common_prefix_maximum_quantity_difference":max((float(np.max(abs(quantities(a)-quantities(b))))
            for a,b in zip(left[:common],right[:common])),default=None),
        "scope":"unique cache misses in query order; not all objective/constraint calls"}


def run(source,root,executable,*,variant_id="reference-7-h0.05",profile_name="outward_y_A",max_iterations=60):
    result={"kind":"offline_extrema_optimizer_trace","variant_id":variant_id,"profile":profile_name,
        "rows":[],"warnings":[],"execution_admission":"not_performed","dynamic_closed_loop":"not_passed",
        "scope":"instrumented search and post-search diagnostics; wall is not a performance benchmark"}
    try:
        matches=[r for r in source["rows"] if isinstance(r,dict) and r.get("variant_id")==variant_id
            and isinstance(r.get("profile"),dict) and r["profile"].get("name")==profile_name]
    except (KeyError,TypeError):return {**result,"status":"unscored","reason":"archive_rows_unavailable"}
    if len(matches)!=1:return {**result,"status":"unscored","reason":"one_variant_profile_required"}
    original=matches[0]
    try:
        result["source_input"]={key:copy.deepcopy(original[key]) for key in ("boundary_request","hard_box","hard_limits","input","profile","start_sim_s")}
    except (KeyError,TypeError):return {**result,"status":"unscored","reason":"archive_boundary_or_provenance_unavailable"}
    audit,_=geometry.tracking.load("stop_candidates",Path(__file__).with_name("drone-stop-candidates.py")).load_modules(root)
    for backend in ("python","rootfinder"):
        row={"backend":backend,"events":[]};result["rows"].append(row);session=None;began=time.perf_counter()
        try:
            with qualification.sessions.NativeSession(executable,timeout=1.) as session:
                callback=None if backend=="python" else lambda native,current_audit: qualification.native_search_metrics(native,session.exchange)
                row["resolved"]=geometry.search(original["boundary_request"],original["hard_box"],original["hard_limits"],
                    executable,audit,y_inner=True,z_time_bounds=(.1,1.2),max_iterations=max_iterations,
                    exchange=session.exchange,metrics_backend=callback,observer=row["events"].append)
            row["status"]=row["resolved"]["status"]
        except (ValueError,KeyError,TypeError,OSError) as error:
            row.update(status="unscored",reason=str(error));result["warnings"].append(f"{backend}: {error}")
        row.update(instrumented_wall_s=time.perf_counter()-began,
            owned_process_exited=session.process.poll() is not None if session is not None else None)
        evaluations=[event for event in row["events"] if event["kind"]=="evaluation"]
        row["first_stencil"]=stencil(evaluations)
        # Shadow diagnostics happen after the optimizer and owned generation
        # process have finished; they cannot influence the search path.
        shadow=None
        try:
            for index,event in enumerate(evaluations):
                try:
                    if shadow is None or shadow.closed:shadow=qualification.sessions.NativeSession(executable,timeout=1.)
                    py=geometry.extrema(event["native"],audit);native_metrics=qualification.native_search_metrics(event["native"],shadow.exchange)
                    event["same_coefficients_maximum_quantity_difference"]=float(np.max(abs(quantities(event,py)-quantities(event,native_metrics))))
                    if index<7:event["acceleration_piece_peaks"]=piece_peaks(event["native"],audit)
                except (ValueError,KeyError,TypeError,OSError) as error:
                    event["shadow_error"]=str(error);result["warnings"].append(f"{backend}/query{index}: {error}")
        finally:
            if shadow is not None:
                try:shadow.close()
                except ValueError as error:result["warnings"].append(f"{backend}/shadow_close: {error}")
                row["shadow_process_exited"]=shadow.process.poll() is not None
        if row.get("status")=="audited":row["final_acceleration_piece_peaks"]=piece_peaks(row["resolved"]["candidate"]["native"],audit)
        row["evaluation_count"]=len(evaluations)
        row["maximum_same_coefficient_quantity_difference"]=max((event["same_coefficients_maximum_quantity_difference"]
            for event in evaluations if "same_coefficients_maximum_quantity_difference" in event),default=None)
    left,right=([event for event in row["events"] if event["kind"]=="evaluation"] for row in result["rows"])
    result["query_comparison"]=compare_queries(left,right)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reanchor-report",type=Path,required=True)
    parser.add_argument("--drone-root",type=Path,default=Path.home()/"dev/ros2/projects/drone")
    parser.add_argument("--native",type=Path,default=Path.home()/".cache/ros2-drone/minco-s4-metrics/minco_s4_metrics")
    parser.add_argument("--variant-id",default="reference-7-h0.05")
    parser.add_argument("--profile",default="outward_y_A")
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();result=run(json.loads(args.reanchor_report.read_text()),args.drone_root,args.native,
        variant_id=args.variant_id,profile_name=args.profile)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"comparison":result.get("query_comparison"),"warnings":result["warnings"]},ensure_ascii=False))


if __name__=="__main__":main()
