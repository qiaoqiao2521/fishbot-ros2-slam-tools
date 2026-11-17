#!/usr/bin/env python3
"""Captured native-message reordering through temporary Sidecar methods; no control."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types

sys.dont_write_bytecode=True
TOOLS=Path(__file__).resolve().parent
sys.path.insert(0,str(TOOLS.parent/'workbench-review-tests'))
import test_drone_command_epoch_patch as epochs
from test_drone_command_revalidation_patch import apply,copy_source
from test_drone_ack_curve_buffer import AckHarness


def run(recording, output, baseline_ref):
    output.mkdir(parents=True,exist_ok=True)
    captured=[json.loads(line) for line in (recording/'ros-events.jsonl').read_text().splitlines()]
    goals=[e for e in captured if e['kind']=='goal_sent']
    baseline=subprocess.check_output(['git','-C',str(TOOLS),'show',
        baseline_ref+':apps/fishbot-control-station/workbench-tools/patches/drone-command-epoch.patch'],text=True)
    rows=[]
    for label in ('baseline','buffered'):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_source(root)
            patch=epochs.EPOCH
            if label=='baseline':
                patch=root/'baseline.patch';patch.write_text(baseline)
            apply(root,patch)
            spec=importlib.util.spec_from_file_location('ack_replay_'+label,root/'command_epoch.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            fixture=epochs.CommandEpochPatch();fixture.root,fixture.module=root,module
            for index,goal in enumerate(goals):
                ack=next(e for e in captured if e['kind']=='ack' and
                    e['message']['data'].split(':')[0]==str(goal['stamp_ns']))
                floor=int(ack['message']['data'].split(':')[1])
                curve=next(e for e in captured if e['kind']=='bspline' and
                    e['host_monotonic_ns']>=ack['host_monotonic_ns'] and e['message']['traj_id']>floor)
                command=next(e for e in captured if e['kind']=='position' and
                    e['message']['trajectory_id']==curve['message']['traj_id'])
                for order in ('ack_first','curve_first'):
                    h=AckHarness(fixture,root/f'{index}-{order}')
                    h.node.goal_stamp_ns=goal['stamp_ns']
                    h.node.active_goal=dict(zip(('x','y','z'),goal['target']),task_id='native-probe-replay',goal_id=str(index))
                    c=curve['message']
                    message=h.curve(c['traj_id'],c['start_sim_s'],c['control_points'],c['knots'])
                    message.order=c['order']
                    h.clock.sim=curve['harness_sim_s']
                    if order=='ack_first':
                        h.ack(floor,goal['stamp_ns']);h.node.on_bspline(message)
                    else:
                        h.node.on_bspline(message)
                        h.clock.sim+=.001 # Explicit injected processing delay, not a native wire timestamp.
                        h.ack(floor,goal['stamp_ns'])
                    value=command['message'];msg=h.command(value['trajectory_id'])
                    for field in ('position','velocity','acceleration'):
                        setattr(msg,field,types.SimpleNamespace(**dict(zip(('x','y','z'),value[field]))))
                    stamp=int(round(value['stamp_sim_s']*1e9))
                    msg.header.stamp.sec,msg.header.stamp.nanosec=stamp//10**9,stamp%10**9
                    msg.yaw=value['yaw'];h.node.on_command(msg)
                    log=h.node.args.runtime/'trajectory-events.jsonl'
                    rows.append(dict(source=label,goal_index=index,processing_order=order,
                        candidate_registered=bool(h.node.setpoint),sample=h.node.setpoint,
                        source_curve_id=c['traj_id'],source_ack=ack['message']['data'],
                        native_curve_host_ns=curve['host_monotonic_ns'],native_ack_host_ns=ack['host_monotonic_ns'],
                        curves_delivered=1,commands_delivered=1,
                        trajectory_events=[] if not log.exists() else [json.loads(x) for x in log.read_text().splitlines()]))
    checks={}
    for index in range(len(goals)):
        for order in ('ack_first','curve_first'):
            old=next(r for r in rows if r['source']=='baseline' and r['goal_index']==index and r['processing_order']==order)
            new=next(r for r in rows if r['source']=='buffered' and r['goal_index']==index and r['processing_order']==order)
            checks[f'goal{index}_{order}']=(old['candidate_registered']==(order=='ack_first') and new['candidate_registered'])
    checks['two_native_goals']=len(goals)==2
    result={'scope':'captured native C++ ROS messages; controlled callback processing order and synthetic Sidecar context',
        'recording':str(recording),'baseline_ref':baseline_ref,'diagnostic_checks':checks,'rows':rows,
        'native_wire_reordering_observed':False,'source_provenance_verified':False,
        'flight_accepted':False,'control_commands_sent':0}
    (output/'ack-order-replay.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'output':str(output),'checks':checks,'source_provenance_verified':False},indent=2))
    return int(not all(checks.values()))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recording',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline-ref',default='f3de761')
    args=parser.parse_args()
    return run(args.recording.resolve(),args.output.resolve(),args.baseline_ref)

if __name__=='__main__':raise SystemExit(main())
