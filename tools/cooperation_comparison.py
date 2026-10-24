#!/usr/bin/env python3
"""Project two recorded delivery branches; never initialize ROS or run physics.

The existing timing importer owns stage/gap extraction. This task-specific
export adds measured cargo and arm projections for the workbench comparison.
General log playback remains with the existing Lichtblick workbench.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path

from cooperation_timing import import_run, number, obj, vector

SCHEMA='fishbot.delivery-comparison.v1'


def arm_projection(manifest):
    """FK on independent query data. No step, controller or live world writes."""
    import mujoco
    import numpy as np
    model=mujoco.MjModel.from_xml_path(manifest['rig_xml'])
    data=mujoco.MjData(model)
    names=manifest['arm_joint_names']
    joints=[model.joint(name).id for name in names]
    positions=[int(model.jnt_qposadr[j]) for j in joints]
    station=np.asarray(manifest['station_offset'],dtype=float)
    def project(q):
        data.qpos[positions]=q
        mujoco.mj_forward(model,data)
        return (data.xanchor[joints]+station).tolist()
    return project


def scene_projection(manifest):
    import mujoco
    import numpy as np
    model=mujoco.MjModel.from_xml_path(manifest['world_xml'])
    data=mujoco.MjData(model);mujoco.mj_forward(model,data)
    boxes=[]
    for i in range(model.ngeom):
        if (model.geom_bodyid[i]!=0 or model.geom_type[i]!=mujoco.mjtGeom.mjGEOM_BOX
                or not (model.geom_contype[i] or model.geom_conaffinity[i])):continue
        rotation=data.geom_xmat[i].reshape(3,3)
        boxes.append({'id':model.geom(i).name,'position':data.geom_xpos[i].tolist(),
            'half_size':model.geom_size[i].tolist(),
            'yaw':math.atan2(float(rotation[1,0]),float(rotation[0,0]))})
    geom=model.geom('target_collision').id
    return {'frame':'world','static_boxes':boxes,
        'car_footprint_xy':manifest.get('car_footprint_xy'),
        'cargo_half_size':np.asarray(model.geom_size[geom]).tolist()}


def project_case(case,points,*,label,manifest,project_arm=None,group='unassigned'):
    """Keep absolute coordinates and source gaps; no interpolation or rescore."""
    frames=[];warnings=list(case.get('warnings',[]));previous=None
    route_start=case['route'].get('start_wall_s')
    anchors={}
    for p in points:
        source=number(p.get('source_s'))
        if source is None or (previous is not None and source<=previous):
            warnings.append('Nonadvancing or missing source sample skipped; display remains incomplete')
            continue
        previous=source
        q=vector(p.get('arm_q6_rad'),6)
        arm=None
        if q is not None and project_arm is not None:
            try:arm=project_arm(q)
            except (ValueError,RuntimeError):warnings.append('Arm FK unavailable for one sample')
        frame={k:p.get(k) for k in ('sequence','stage','hold','gap_before')}
        frame.update(source_s=source,receive_wall_s=number(p.get('receive_wall_s')),
            car=vector(p.get('car_position_m'),3),quaternion=vector(p.get('car_quaternion_wxyz'),4),
            cargo=vector(p.get('cargo_position_m'),3),arm_q6=q,arm_joints_world=arm)
        frames.append(frame)
        if isinstance(p.get('stage'),str):anchors.setdefault('stage:'+p['stage'],source)
        if (route_start is not None and frame['receive_wall_s'] is not None
                and frame['receive_wall_s']>=route_start):anchors.setdefault('route',source)
    if frames:anchors['recording']=frames[0]['source_s']
    return {'id':case['id'],'label':label,'group':group,'task_id':case['task_id'],'episode_id':case['episode_id'],
        'scope':case.get('scope','transport'),'scene_id':case['scene_id'],
        'vehicle':case['vehicle'],'sensor':case['sensor'],'snapshot_id':
            obj(manifest.get('checkpoint_parent')).get('snapshot_id'),
        'physical':case['physical'],'route':case['route'],'original_verdict':case['original_verdict'],
        'guard':case.get('guard',[]),'sampling':case['sampling'],'spans':case['spans'],
        'anchors':anchors,'frames':frames,'warnings':list(dict.fromkeys(warnings))}


def build_comparison(run_paths,output,*,labels=None,groups=None,geometry=True):
    output=Path(output).resolve()
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    runs=[];scene=None;compatible=True
    for i,path in enumerate(run_paths):
        path=Path(path).resolve()
        imported=output/('import-'+str(i+1))
        report=import_run(path,imported)
        manifest=json.loads((path/'manifest-used.json').read_text())
        projection=arm_projection(manifest) if geometry else None
        shape=scene_projection(manifest) if geometry else {'frame':'world','static_boxes':[],
                'car_footprint_xy':manifest.get('car_footprint_xy'),'cargo_half_size':None}
        if scene is not None and shape!=scene:compatible=False
        if scene is None:scene=shape
        for case in report['cases']:
            source=imported/case['trajectory']['stream_ref']
            with source.open() as stream:
                points=(json.loads(line) for line in stream)
                runs.append(project_case(case,points,label=labels[i] if labels and i<len(labels) else path.name,
                    manifest=manifest,project_arm=projection,
                    group=groups[i] if groups and i<len(groups) else 'unassigned'))
    snapshots={run['snapshot_id'] for run in runs}
    same_snapshot=len(snapshots)==1 and None not in snapshots
    positions=[p for run in runs for frame in run['frames'] for p in
               ([frame['car'],frame['cargo']]+(frame['arm_joints_world'] or [])) if p is not None]
    bounds=([min(p[0] for p in positions)-.45,min(p[1] for p in positions)-.45,
             max(p[0] for p in positions)+.45,max(p[1] for p in positions)+.45] if positions else [-1.,-1.,1.,1.])
    value={'schema':SCHEMA,'read_only':True,'new_execution':False,'rescored':False,
        'frame':'world','scene':scene,'view_bounds_xy':bounds,'runs':runs,
        'same_scene_geometry':compatible,'same_checkpoint_id':same_snapshot,
        'spatial_alignment_applied':False,'display_sampling_hz':10,
        'limits':['Native scores are copied, never inferred from playback.',
                  'Time anchors align source elapsed time, never world coordinates.',
                  'Arm links are FK projections from recorded q6, not contact or collision geometry.',
                  'Missing samples remain gaps. This export cannot send motion.']}
    (output/'comparison.json').write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')))
    return value


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,action='append',required=True)
    parser.add_argument('--label',action='append')
    parser.add_argument('--group',choices=('baseline','candidate','replication','holdout'),action='append')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=build_comparison(args.run,args.output,labels=args.label,groups=args.group)
    print(json.dumps({'runs':len(result['runs']),'same_checkpoint_id':result['same_checkpoint_id'],
                      'output':str(args.output/'comparison.json')}))
