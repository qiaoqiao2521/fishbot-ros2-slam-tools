#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Paired offline transport timings and explicit simulation-time late submissions."""
import argparse
import copy
import json
from pathlib import Path
import time

import importlib.util
import numpy as np


def load(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+".py"))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


reanchor=load("drone-handoff-reanchor")
session_module=load("drone-native-session")


def late_submissions(candidate, task_id, start, box, limits, audit, handoff):
    """Clock and state fixtures only; never convert measured wall cost to sim."""
    native=candidate["native"];end=start+handoff.duration(native)
    context={"task_id":task_id,"scene_revision":"late-submit-static-fixture",
        "clock_id":"explicit-sim-fixture","frame_id":"scene_enu_m"}
    row={"kind":"axis_stop_geometry_candidate","recorded_task_id":task_id,
        "trajectory_id":"late-submit-probe","request":candidate["request"],"native":native,
        "hard_box":box,"start_sim_s":start}
    specifications=[("at_cut",start,"phase"),("late_old_head",start+.2,"head"),
        ("late_current_phase",start+.2,"phase"),("late_CV_model",start+.2,"CV_model"),
        ("before_original_end",float(np.nextafter(end,start)),"phase"),
        ("at_original_end",end,"phase"),("after_original_end",float(np.nextafter(end,np.inf)),"phase"),
        ("wall_elapsed_sim_paused",start,"phase"),("late_A_unknown",start+.2,"unknown_A"),
        ("late_stale_map",start+.7,"phase"),("late_terminal_window_missing",start+.2,"phase")]
    results=[]
    for name,now,state_mode in specifications:
        state=handoff.pva(native,0. if state_mode=="head" else now-start).tolist()
        if state_mode=="CV_model":
            head=np.asarray(candidate["request"]["initial_pva"])
            state=np.column_stack([head[:,0]+head[:,1]*(now-start),head[:,1],np.zeros(3)]).tolist()
        if state_mode=="unknown_A":
            for axis in state:axis[2]=None
        snapshot={"context":context,"revision":"declared-static-fixture",
            "known_space":"declared_static_configuration_space_fixture","box":box,"voxels":[],
            "observed_sim_s":start if name=="late_stale_map" else now,
            "valid_from_sim_s":start,"valid_until_sim_s":end if name=="late_terminal_window_missing" else end+2.}
        event={"context":context,"now_sim_s":now,"observed_pva":state,"snapshot":snapshot,"candidate":row}
        if name=="wall_elapsed_sim_paused":event["offline_wall_elapsed_s"]=100.
        replay=reanchor.qualification.committed.Replay(context,limits,audit,handoff)
        result=replay.step(event)
        if result.get("candidate_math_gate"):
            result["candidate_math_gate"]={k:result["candidate_math_gate"].get(k) for k in ("passed","failed_checks")}
        results.append({"name":name,"original_start_sim_s":start,"now_sim_s":now,
            "state_scope":"old head fixture" if state_mode=="head" else "A unknown" if state_mode=="unknown_A"
                else "CV propagation with model A=0, not measured" if state_mode=="CV_model" else "ideal phase-matched PVA fixture",
            "observed_pva_fixture":state,"snapshot_fixture":snapshot,
            "offline_wall_elapsed_s":event.get("offline_wall_elapsed_s"),
            "selected_original_start_sim_s":replay.server.active[2] if replay.server.active else None,"result":result})
    return {"scope":"explicit sim times and declared static space; no measured-state or computation-deadline qualification",
        "original_start_sim_s":start,"original_end_sim_s":end,"cases":results,"execution_admission":"not_performed"}


def run(source, root, native, *, variant_id="reference-7-h0.05", profile_name="zero_A_J", repetitions=3):
    result={"kind":"offline_transport_and_late_submission_comparison","rows":[],"warnings":[],
        "execution_admission":"not_performed","dynamic_closed_loop":"not_passed"}
    try:
        matches=[r for r in source["rows"] if isinstance(r,dict) and r.get("variant_id")==variant_id
            and isinstance(r.get("profile"),dict) and r["profile"].get("name")==profile_name]
        if len(matches)!=1 or repetitions<1:
            raise ValueError("one source variant/profile and positive repetitions required")
        original=matches[0];request=original["boundary_request"];box=original["hard_box"];limits=original["hard_limits"]
        if not original.get("conditional_math_passed"):
            raise ValueError("source tail has no conditional mathematical pass")
    except (KeyError,ValueError,TypeError,AttributeError) as error:
        return {**result,"status":"unscored","reason":str(error)}
    audit,handoff=reanchor.qualification.committed.reuse(root)
    result.update(archive_task_id=source["archive_task_id"],variant_id=variant_id,profile_name=profile_name,
        source_input=copy.deepcopy(original["input"]),original_start_sim_s=original["start_sim_s"],
        scope="same archived boundary and search settings; wall includes complete native process lifecycle; no wall-to-sim conversion")
    representatives={}
    for repetition in range(repetitions):
        paired={}
        for reuse in (False,True):
            mode="per_search" if reuse else "per_evaluation"
            row={"repetition":repetition,"transport":mode};result["rows"].append(row)
            try:
                began=time.perf_counter()
                options={"y_inner":True,"z_time_bounds":reanchor.Z_TIME_BOUNDS,"max_iterations":60}
                if reuse:
                    with session_module.NativeSession(native) as session:
                        resolved=reanchor.geometry.search(request,box,limits,native,audit,exchange=session.exchange,**options)
                    row["owned_process_exited"]=session.process.poll() is not None
                else:
                    resolved=reanchor.geometry.search(request,box,limits,native,audit,**options)
                row.update(wall_s=time.perf_counter()-began,status=resolved["status"])
                if resolved["status"]=="audited":
                    row.update(math_passed=resolved["candidate"]["audit"]["passed"],optimizer=resolved["optimizer"])
                    paired[mode]=resolved["candidate"]
                    representatives[mode]=resolved["candidate"]
                else:row["reason"]=resolved.get("reason")
            except (OSError,ValueError,TypeError,KeyError,AttributeError) as error:
                row.update(status="unscored",reason=str(error));result["warnings"].append(f"{repetition}/{mode}: {error}")
        if len(paired)==2:
            left,right=paired["per_evaluation"],paired["per_search"]
            result["rows"][-1]["paired_equivalence"]={"request":left["request"]==right["request"],
                "pieces":left["native"]["pieces"]==right["native"]["pieces"],"hard_audit":left["audit"]==right["audit"],
                "axis_knots":left["axis_knot_contract"]==right["axis_knot_contract"]}
    result["representative_candidates"]=representatives
    result["wall_summary"]={mode:{"samples":len(times),"minimum_s":min(times),"median_s":float(np.median(times)),"maximum_s":max(times)}
        for mode in ("per_evaluation","per_search") if (times:=[r["wall_s"] for r in result["rows"] if r["transport"]==mode and r.get("status")=="audited"])}
    if "per_search" in representatives:
        result["late_submissions"]=late_submissions(representatives["per_search"],source["archive_task_id"],
            original["start_sim_s"],box,limits,audit,handoff)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reanchor-report",type=Path,required=True)
    parser.add_argument("--drone-root",type=Path,default=Path.home()/"dev/ros2/projects/drone")
    parser.add_argument("--native",type=Path,default=Path.home()/".cache/ros2-drone/minco-s4-knots/minco_s4_knots")
    parser.add_argument("--variant-id",default="reference-7-h0.05")
    parser.add_argument("--profile",default="zero_A_J")
    parser.add_argument("--repetitions",type=int,default=3)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=run(json.loads(args.reanchor_report.read_text()),args.drone_root,args.native,
        variant_id=args.variant_id,profile_name=args.profile,repetitions=args.repetitions)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps(result.get("wall_summary",{"status":result.get("status"),"reason":result.get("reason")})))


if __name__=="__main__":main()
