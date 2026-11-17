#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Re-solve standalone stopping tails at recorded-PV cuts. No control transport."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path

import numpy as np


def load(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+".py"))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


pv=load("drone-handoff-pv")
qualification=load("drone-stop-qualification")
geometry=qualification.geometry
Z_TIME_BOUNDS=(.1,1.2)


def hypotheses():
    declared={p["name"]:p for p in qualification.profiles(None,None)}
    zero={"name":"zero_A_J","acceleration":[0.]*3,"jerk":[0.]*3,
        "scope":"synthetic A=J=0 at cut; neither measured nor inherited from reference"}
    return [zero]+[declared[name] for name in ("outward_y_A","outward_y_J","inward_y_J")]


def source_index(reports, task_id):
    index={}
    for report in reports:
        if (not isinstance(report,dict) or report.get("archive_task_id")!=task_id
                or not isinstance(report.get("rows"),list)):
            continue
        for item in report["rows"]:
            if isinstance(item,dict) and isinstance(item.get("variant_id"),str):
                index.setdefault(item["variant_id"],[]).append((report,item))
    return index


def seed_request(position, velocity, profile, box, handoff):
    reference=load("drone-reference-stops")
    head=np.column_stack([position,velocity,np.zeros(3)])
    if head.shape!=(3,3) or not np.all(np.isfinite(head)):
        raise ValueError("finite three-axis PV required")
    base=handoff.axis_stop_request({"initial_pva":head.tolist(),
        "original_local_target":list(position),"corridor":[reference.box_faces(box)],
        "integral_resolution":16},[3.5,1.,.4],[0.]*3)
    return qualification.hypothesis_request(base,profile)


def run(reports, states, epochs, root, native, task_id, *, max_iterations=60, reuse_native=False):
    # Re-select from original state/clock evidence; cached predicted PV, exact
    # oracle branches and the nominal reference's A/J are never generator inputs.
    comparison=pv.run(reports,states,epochs,root,task_id)
    audit,handoff=qualification.committed.reuse(root)
    index=source_index(reports,task_id)
    rows=[];warnings=list(comparison["warnings"])
    for compared in comparison["rows"]:
        variant=compared.get("variant_id")
        for profile in hypotheses():
            row={"variant_id":variant,"profile":profile,"execution_admission":"not_performed",
                "prefix_scope":"standalone tail; no historical reference prefix",
                "real_handoff":"unqualified; vehicle A/J and consumption ACK unknown"}
            rows.append(row)
            try:
                if len(index.get(variant,[]))!=1:
                    raise ValueError("source_variant_missing_or_ambiguous")
                source,parent=index[variant][0]
                if (compared.get("status")!="compared" or parent.get("status")!="generated"
                        or not parent["result"]["candidate"]["full_math_gate"]["passed"]
                        or not parent["result"]["narrow_box_gate"]["passed"]):
                    raise ValueError("source_reference_or_PV_comparison_unqualified")
                causal=compared.get("recorder_available_CV",{})
                if causal.get("model")!="constant_velocity":
                    raise ValueError("recorder_available_CV_unqualified; no retrospective fallback")
                position,velocity=causal["predicted_position"],causal["predicted_velocity"]
                box,limits=source["narrow_box_fixture"],source["limits"]
                start=compared["comparison_cut_s"]
                row.update(start_sim_s=start,hard_box=box,hard_limits=limits,
                    historical_timing=copy.deepcopy(parent["timing"]),
                    input={"source_state":copy.deepcopy(causal["source_state"]),
                        "source_age_s":causal["source_age_s"],"availability_age_s":causal["availability_age_s"],
                        "position":position,"velocity":velocity,"model":"constant_velocity",
                        "PV_scope":"recorder-available causal forecast; no exact-cut measurement or planner ACK",
                        "A_J_scope":"separate finite hypotheses; not prediction output or measured state"})
                request=seed_request(position,velocity,profile,box,handoff)
                row["boundary_request"]=request
                necessary=pv.tracking.stopping_necessary(position,velocity,box,limits["acceleration"])
                row["necessary"]=necessary
                if necessary["status"]!="not_ruled_out":
                    row.update(status="not_searched",reason="optimistic_PV_necessary_bound_not_passed");continue
                options={"y_inner":True,"z_time_bounds":Z_TIME_BOUNDS,"max_iterations":max_iterations}
                if reuse_native:
                    with load("drone-native-session").NativeSession(native) as session:
                        resolved=geometry.search(request,box,limits,native,audit,exchange=session.exchange,**options)
                else:
                    resolved=geometry.search(request,box,limits,native,audit,**options)
                row.update(status=resolved["status"],resolved=resolved)
                if resolved["status"]!="audited":
                    continue
                candidate=resolved["candidate"]
                row["acceleration_peak"]=qualification.acceleration_peak(candidate["native"],audit)
                row["tail_duration_sim_s"]=handoff.duration(candidate["native"])
                row["tail_end_sim_s"]=start+row["tail_duration_sim_s"]
                row["conditional_math_passed"]=candidate["audit"]["passed"]
                if candidate["audit"]["passed"]:
                    try:
                        row["temporal_fixture"]=qualification.temporal_replay(candidate,task_id,start,box,limits,audit,handoff)
                    except (ValueError,TypeError,KeyError,IndexError,AttributeError) as error:
                        row["temporal_fixture"]={"status":"unscored","reason":str(error),
                            "execution_admission":"not_performed"}
                        warnings.append(f"{variant}/{profile['name']}: optional temporal fixture: {error}")
            except (ValueError,TypeError,KeyError,IndexError,AttributeError) as error:
                row.update(status="unscored",reason=str(error))
                warnings.append(f"{variant}/{profile['name']}: {error}")
    audited=[r for r in rows if r.get("status")=="audited"]
    return {"schema_version":1,"archive_task_id":task_id,
        "kind":"offline_recorder_PV_reanchored_stopping_tails",
        "source_PV_comparison_summary":comparison["summary"],
        "search_configuration":{"y_inner":True,"z_time_bounds_s":list(Z_TIME_BOUNDS),
            "native_transport":"one_process_per_search" if reuse_native else "one_process_per_evaluation",
            "max_iterations":max_iterations,"planning_inset_m":.002,
            "scope":"same explicit domain as narrow reference cuts; not default geometry.search domain"},
        "summary":{"variants":len(comparison["rows"]),"hypotheses":len(rows),"audited":len(audited),
            "conditional_math_passed":sum(r.get("conditional_math_passed",False) for r in audited),
            "full_vehicle_handoffs_qualified":0,"unscored":sum(r.get("status")=="unscored" for r in rows)},
        "actual_qualification":{"vehicle_A_J":"unknown","current_known_map":"unqualified",
            "future_free_volume":"unqualified","terminal_region":"unqualified","deadline":"unqualified",
            "tracking":"unqualified","PX4_adoption":"not_performed"},
        "scope":"finite A/J hypotheses and explicit static box, not a robust backup or real C3 handoff certificate",
        "dynamic_closed_loop":"not_passed","execution_admission":"not_performed","warnings":warnings,"rows":rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates",type=Path,nargs="+",required=True)
    parser.add_argument("--run-dir",type=Path,required=True)
    parser.add_argument("--drone-root",type=Path,default=Path.home()/"dev/ros2/projects/drone")
    parser.add_argument("--native",type=Path,default=Path.home()/".cache/ros2-drone/minco-s4-knots/minco_s4_knots")
    parser.add_argument("--max-iterations",type=int,default=60)
    parser.add_argument("--reuse-native",action="store_true",help="Reuse existing JSON-line CLI for each offline search")
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();reports=[]
    for path in args.candidates:
        try:reports.append(json.loads(path.read_text()))
        except (OSError,ValueError) as error:print(f"WARNING: optional candidate report skipped: {path.name}: {error}")
    task_id=json.loads((args.run_dir/"request.json").read_text())["id"]
    states,_,epochs=pv.tracking.read_odometry(args.run_dir)
    result=run(reports,states,epochs,args.drone_root,args.native,task_id,max_iterations=args.max_iterations,
        **({"reuse_native":True} if args.reuse_native else {}))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps(result["summary"]))


if __name__=="__main__":main()
