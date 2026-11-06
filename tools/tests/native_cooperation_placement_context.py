#!/usr/bin/env python3
"""Compare legacy full-forward and current geometry-only query contexts.

Load one saved snapshot into independent old/new query models; never step the
world, start ROS, run a model, or alter the saved input. No delivery score here.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time
import tempfile
import xml.etree.ElementTree as ET
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cooperation_arm import ArmPlanner


def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('manifest','request','legacy-dir','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--pre-reuse-entities',type=Path)
    args=parser.parse_args();report={'passed':False,'is_delivery_acceptance':False}
    try:
        import numpy as np
        import mujoco
        manifest=json.loads(args.manifest.read_text());request=json.loads(args.request.read_text())
        raw=request['snapshot'];pose=request['car_pose']
        old_entities=load_module('_legacy_arm_entities',args.legacy_dir/'cooperation_arm_entities.py')
        old_arm=load_module('_legacy_arm',args.legacy_dir/'cooperation_arm.py')
        class Stages:
            def __init__(self):self.events=[]
            def emit(self,stage,**fields):self.events.append((stage,time.monotonic()))
        old_trace,current_trace=Stages(),Stages()
        began=time.monotonic()
        with patch.dict(sys.modules,{'cooperation_arm_entities':old_entities}):
            old=old_arm.ArmPlanner(manifest,car_pose=pose,arm_id=request['arm_id'],cargo_id=request['cargo_id'],snapshot=raw,trace=old_trace)
        old_s=time.monotonic()-began;began=time.monotonic()
        current=ArmPlanner(manifest,car_pose=pose,arm_id=request['arm_id'],cargo_id=request['cargo_id'],snapshot=raw,trace=current_trace)
        current_s=time.monotonic()-began
        # These are the fields consumed by point/quaternion, frozen geom export,
        # grasp_target and canonical_snapshot. Contact state is not a pose input.
        pose_fields=('qpos','qvel','xpos','xquat','xmat','geom_xpos','geom_xmat','xanchor','xaxis')
        for key in pose_fields:
            if not np.array_equal(getattr(old.entity_view.data,key),getattr(current.entity_view.data,key)):
                raise AssertionError('Consumed common-world field differs: '+key)
        if old.entity_view.canonical_snapshot(raw)!=current.entity_view.canonical_snapshot(raw):
            raise AssertionError('Canonical arm/cargo/control snapshot changed')
        if old.entity_contract()!=current.entity_contract():
            raise AssertionError('Entity IDs or frozen geom mapping changed')
        arrays=('qpos0','body_mass','body_inertia','body_pos','body_quat','geom_type',
            'geom_bodyid','geom_contype','geom_conaffinity','geom_group','geom_size',
            'geom_pos','geom_quat','geom_dataid','mesh_vert','mesh_face','jnt_type',
            'jnt_axis','jnt_pos','jnt_range','jnt_qposadr','jnt_dofadr',
            'actuator_trnid','actuator_gainprm','actuator_biasprm','actuator_ctrlrange')
        models={}
        local_snapshot=current.entity_view.canonical_snapshot(raw)
        with tempfile.TemporaryDirectory(prefix='query-mesh-asset-proof-') as binary_folder:
            for name in ('common','contact','rig'):
                a,b=getattr(old,name),getattr(current,name)
                for count,accessor in (('ngeom','geom'),('nbody','body'),('njnt','joint'),('nu','actuator')):
                    if getattr(a,count)!=getattr(b,count):raise AssertionError(name+' object count differs: '+count)
                    if any(getattr(a,accessor)(i).name!=getattr(b,accessor)(i).name for i in range(getattr(a,count))):
                        raise AssertionError(name+' object names differ: '+accessor)
                # Mesh IDs and concatenated asset arrays may intentionally differ.
                # Compare actual per-geom topology/vertices instead of asset slots.
                strict=arrays if name=='common' else tuple(k for k in arrays if k not in ('geom_dataid','mesh_vert','mesh_face'))
                bad=[key for key in strict if not np.array_equal(getattr(a,key),getattr(b,key))]
                if bad:raise AssertionError(name+' collision/model arrays differ: '+str(bad))
                if a.opt.disableflags!=b.opt.disableflags:raise AssertionError(name+' flags differ')
                ad,bd=mujoco.MjData(a),mujoco.MjData(b)
                qpos=raw['qpos'] if name=='common' else local_snapshot['qpos'] if name=='contact' else np.asarray(raw['qpos'])[current.entity_view.arm['qpos']]
                ad.qpos[:]=qpos;bd.qpos[:]=qpos
                mujoco.mj_kinematics(a,ad);mujoco.mj_kinematics(b,bd)
                checked_meshes=[];collision_geom_count=0
                for geom in range(a.ngeom):
                    if a.geom_contype[geom] or a.geom_conaffinity[geom]:collision_geom_count+=1
                    if int(a.geom_type[geom])!=int(mujoco.mjtGeom.mjGEOM_MESH):continue
                    local_vertices=[];world_vertices=[];faces=[]
                    for model,data in ((a,ad),(b,bd)):
                        mesh=int(model.geom_dataid[geom])
                        va,vn=int(model.mesh_vertadr[mesh]),int(model.mesh_vertnum[mesh])
                        fa,fn=int(model.mesh_faceadr[mesh]),int(model.mesh_facenum[mesh])
                        vertices=model.mesh_vert[va:va+vn]
                        rotation=np.empty(9);mujoco.mju_quat2Mat(rotation,model.geom_quat[geom])
                        local_vertices.append(vertices @ rotation.reshape(3,3).T+model.geom_pos[geom])
                        world_vertices.append(vertices @ data.geom_xmat[geom].reshape(3,3).T+data.geom_xpos[geom])
                        faces.append(model.mesh_face[fa:fa+fn])
                    if not np.array_equal(local_vertices[0],local_vertices[1]):raise AssertionError(name+' local vertices changed: '+str(a.geom(geom).name))
                    if not np.array_equal(world_vertices[0],world_vertices[1]):raise AssertionError(name+' world vertices changed: '+str(a.geom(geom).name))
                    if not np.array_equal(faces[0],faces[1]):raise AssertionError(name+' mesh faces changed: '+str(a.geom(geom).name))
                    checked_meshes.append(a.geom(geom).name)
                sizes=[]
                for index,model in enumerate((a,b)):
                    path=Path(binary_folder)/(name+'-'+str(index)+'.mjb')
                    mujoco.mj_saveModel(model,str(path));sizes.append(path.stat().st_size);path.unlink()
                models[name]={'arrays_equal':list(strict),'mesh_asset_indices_intentionally_compared_by_geometry':name!='common',
                    'nmesh':[int(a.nmesh),int(b.nmesh)],'actual_mjb_bytes':sizes,
                    'all_mesh_geom_local_world_vertices_and_faces_equal':checked_meshes,
                    'collision_geom_count_unchanged':collision_geom_count,
                    'full_visual_geoms':[int(np.sum((m.geom_contype==0)&(m.geom_conaffinity==0))) for m in (a,b)]}
        def phase_times(trace):
            result={}
            for stage,at in trace.events:
                if stage.endswith('_started'):
                    completed=stage[:-8]+'_completed'
                    end=next((t for s,t in trace.events if s==completed and t>=at),None)
                    if end is not None:result[stage[:-8]]=end-at
            return result
        xml_projection=[]
        views=[('legacy3304',old.entity_view),('current_reused',current.entity_view)]
        if args.pre_reuse_entities:
            baseline_module=load_module('_pre_reuse_entities',args.pre_reuse_entities)
            views.insert(1,('kinematics_without_mesh_reuse',baseline_module.ArmEntityView(manifest,old.common,request['arm_id'],request['cargo_id'],raw)))
        for label,view in views:
            began=time.monotonic();tree=view.query_root(old._base_root,pose)
            generated=time.monotonic()-began;began=time.monotonic();encoded=ET.tostring(tree,encoding='unicode')
            xml_projection.append({'label':label,'xml_generation_wall_s':generated,'xml_serialization_wall_s':time.monotonic()-began,
                'xml_bytes':len(encoded.encode()),'mesh_asset_reuse':getattr(view,'mesh_asset_reuse',None)})
        q=np.asarray(raw['qpos'])[current.entity_view.arm['qpos']]
        low,high=current.rig.jnt_range[:5].T
        samples=[q,current.home,np.r_[low*.75+high*.25,.5],np.r_[low*.25+high*.75,.5],np.r_[(low+high)/2.,.015]]
        verdicts=[]
        for checker in ('open_checker','closed_checker'):
            for sample in samples:
                a=getattr(old,checker).evaluate(sample,require_fixed_gripper=False)
                b=getattr(current,checker).evaluate(sample,require_fixed_gripper=False)
                if a!=b:raise AssertionError('Original collision verdict/distance/pair changed')
                verdicts.append({'checker':checker,'q6':sample.tolist(),'old':a,'current':b})
        # Actual placement admission still evaluates contact in its independent
        # contact model; compare that original force boundary too.
        forces=[];carried=[]
        for planner in (old,current):
            local=planner.entity_view.canonical_snapshot(raw)
            data=mujoco.MjData(planner.contact)
            data.qpos[:]=local['qpos'];data.qvel[:]=local['qvel']
            if 'ctrl' in local:data.ctrl[:]=local['ctrl']
            if 'time_s' in local:data.time=local['time_s']
            mujoco.mj_forward(planner.contact,data)
            forces.append(planner.modules['grasp_episode'].grasp_contacts(planner.contact,data))
            valid,audit=planner.payload_placement.carried_configuration_checker(planner.contact,data,planner.closed_checker)
            carried.append([bool(valid(sample[:5])) for sample in samples])
        if forces[0]!=forces[1]:raise AssertionError('Measured dual-pad contact force changed')
        if carried[0]!=carried[1]:raise AssertionError('Original carried-cargo collision verdict changed')
        report={'passed':True,'scope':'same saved snapshot independent query geometry; no mj_step/ROS/inference',
            'is_delivery_acceptance':False,'legacy_directory':str(args.legacy_dir),
            'original_init_wall_s':old_s,'current_init_wall_s':current_s,
            'consumed_fields_equal':list(pose_fields),'canonical_snapshot_equal':True,
            'frozen_binding_equal':True,'models':models,'collision_verdicts':verdicts,
            'initialization_phases_wall_s':{'legacy3304':phase_times(old_trace),'current':phase_times(current_trace)},
            'xml_projection':xml_projection,
            'same_snapshot_pad_forces':forces,'carried_collision_verdicts':carried,
            'snapshot_sequence':raw.get('sequence'),'arm_id':request['arm_id'],'cargo_id':request['cargo_id'],
            'contact_evaluation_policy':'original checker mj_forward and measured force admission unchanged; kinematics only replaces pose-only full-world queries'}
    except Exception as error:
        report.update(error_type=type(error).__name__,error=str(error));raise
    finally:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
        print(json.dumps(report,allow_nan=False))


if __name__=='__main__':main()
