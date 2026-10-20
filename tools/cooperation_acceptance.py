#!/usr/bin/env python3
"""Frozen, serial acceptance adapter for existing cooperation entry points.

Panel creation and --dry-run never start ROS. Runtime outputs stay private and
outside Git. The adapter never retries a task or takes over an unknown UUID.
"""
from __future__ import annotations
import argparse
from collections import OrderedDict, deque
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

_readiness_spec=importlib.util.spec_from_file_location('acceptance_cooperation_readiness',Path(__file__).with_name('cooperation_readiness.py'))
_readiness_module=importlib.util.module_from_spec(_readiness_spec)
_readiness_spec.loader.exec_module(_readiness_module)
snapshot_active=_readiness_module.snapshot_active

ROOT = Path(__file__).resolve().parents[1]
POSES = (
    ('dev-0','dev',[.70,0.,0.],11),('dev-1','dev',[.50,.03,.10],29),
    ('dev-2','dev',[.50,-.03,-.10],47),('holdout-0','holdout',[.85,.04,.14],101),
    ('holdout-1','holdout',[.35,-.04,-.14],131),('holdout-2','holdout',[.65,-.02,.07],167))
SOURCE_FILES = ('tools/cooperation_acceptance.py','tools/cooperation_oracle.py',
    'tools/cooperation_oracle_base.py','tools/cooperation_sim.py','tools/cooperation_bridge.py',
    'tools/cooperation_recording.py','tools/cooperation_evidence_recording.py',
    'tools/cooperation_core.py','tools/cooperation_arm.py','tools/cooperation_perception.py',
    'tools/cooperation_prepare.py','tools/cooperation_scene.py','tools/cooperation.launch.py',
    'tools/fishbot_cooperation.sh','tools/fishbot_sim_power.py','tools/fishbot_mujoco_env.sh',
    'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/config/nav2.yaml')


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def private_json(path,value,*,replace=False):
    path=Path(path)
    target=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp') if replace else path
    descriptor=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
    if replace:os.replace(target,path)


def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def world_pose(offset,dock=(-1.8,-1.8,0.)):
    along,lateral,angle=offset;c,s=math.cos(dock[2]),math.sin(dock[2])
    return [dock[0]+c*along-s*lateral,dock[1]+s*along+c*lateral,dock[2]+angle]


def case(name,phase,pose,condition,*,scope='dock',variant='parent',expected='success'):
    return {'name':name,'phase':phase,'pose_id':pose[0],'split':pose[1],
        'offset':pose[2],'spawn':world_pose(pose[2]),'seed':pose[3],
        'condition':condition,'scope':scope,'variant':variant,'expected_outcome':expected,
        'camera_light_scale':1.,
        'budget':{'startup_timeout_s':55.,'native_dock_timeout_s':60.,
                  'task_timeout_s':60. if scope=='dock' else 360.,'caller_timeout_s':75. if scope=='dock' else 375.,
                  'cleanup_timeout_s':15.,
                  'observer_score_timeout_s':120.,'startup_max_retries':0}}


def build_panel():
    cases=[case('baseline-'+p[0],'baseline',p,'ideal') for p in POSES]
    conditions=(('dev-0-clean',0,'zero'),('dev-0-noise-low',0,'noise_low'),
        ('dev-1-noise-high',1,'noise_high'),('dev-1-bias-x',1,'bias_x_positive'),
        ('dev-2-bias-yaw',2,'bias_yaw_positive'),('dev-2-dropout',2,'dropout_10'),
        ('holdout-0-noise-high',3,'noise_high'),('holdout-0-bias-x',3,'bias_x_negative'),
        ('holdout-1-bias-yaw',4,'bias_yaw_negative'),('holdout-1-dropout',4,'dropout_20'),
        ('holdout-2-short-occlusion',5,'short_occlusion'),('holdout-2-combined',5,'combined'))
    for name,index,condition in conditions:
        cases += [case(name+'-'+variant,'perturbed',POSES[index],condition,variant=variant)
                  for variant in ('parent','candidate')]
    for name,index,condition,expected in (
        ('fault-delay',0,'delay_stale','safe_cancel'),
        ('fault-replay-identity',1,'replay_identity','success'),
        ('fault-long-occlusion',3,'long_occlusion','safe_cancel'),
        ('fault-moving-cancel',4,'moving_cancel','safe_cancel')):
        cases += [case(name+'-'+variant,'fault',POSES[index],condition,variant=variant,expected=expected)
                  for variant in ('parent','candidate')]
    for pose in POSES:
        cases.append(case('vision-clear-'+pose[0],'vision',pose,'vision_clear',variant='rgb'))
        condition={'dev-0':'vision_short_occlusion','dev-1':'vision_lighting','dev-2':'vision_lighting',
                   'holdout-0':'vision_long_occlusion','holdout-1':'vision_moving_cancel','holdout-2':'vision_short_occlusion'}[pose[0]]
        variant=case('vision-image-variant-'+pose[0],'vision',pose,condition,variant='rgb',
                     expected='safe_cancel' if condition in ('vision_long_occlusion','vision_moving_cancel') else 'success')
        if condition=='vision_lighting':variant['camera_light_scale']=.5
        cases.append(variant)
    for mode in ('ideal','perturbed','vision'):
        for repeat in (1,2):
            item=case('full-'+mode+'-'+str(repeat),'full',POSES[0],mode,
                      scope='transport',variant='repeat-'+str(repeat))
            item.update(spawn=[0.,-2.,0.],offset=None,pose_id='original-spawn',split='full')
            cases.append(item)
    return {'schema_version':1,'panel_id':'visual-docking-20261014-v1','domain':120,'port':9090,
        'poses':[{'id':p[0],'split':p[1],'offset':p[2],'spawn':world_pose(p[2]),'seed':p[3]} for p in POSES],
        'source_files':list(SOURCE_FILES),'cases':cases,
        'expected_counts':{'baseline':6,'perturbed':24,'fault':8,'vision':12,'full':6},
        'comparison_policy':'Candidate changes are defect-driven; same-source pairs are repetitions, not improvement.',
        'vision_comparison_policy':'Ideal versus RGB is a modality comparison; controlled gains require the same RGB producer and calibration.',
        'threshold_formula':'dev-only: margin=.04-Ep/.05-Eyaw; high=min(margin/3,max(2*residual,margin/6)), xy divided by sqrt(2); low=high/2',
        'physical_thresholds':{'position_m':.04,'yaw_rad':.05,'dock_dwell_source_s':.7}}


def validate_panel(panel):
    reference=build_panel()
    if panel.get('schema_version')!=1 or panel.get('domain')!=120 or panel.get('port')!=9090:
        raise ValueError('Panel requires schema 1 and owned isolated domain120/port9090')
    # The fixed core is literal; runtime source receipts are stored separately.
    for key in ('poses','cases','expected_counts','physical_thresholds','source_files','threshold_formula'):
        if canonical(panel.get(key))!=canonical(reference[key]):
            raise ValueError('Frozen core panel differs: '+key)
    return panel


def derive_thresholds(reports,*,geometry_margin_m=None):
    expected={p[0] for p in POSES if p[1]=='dev'}
    seen=set();rp=[];ry=[];ep=[];ey=[];receipts=[];margins=[]
    for report in reports:
        declaration=report['case']
        if declaration['split']!='dev' or declaration['phase']!='baseline':
            raise ValueError('Calibration accepts dev baseline only; holdout cannot set thresholds')
        if declaration['pose_id'] not in expected or declaration['pose_id'] in seen:
            raise ValueError('Calibration requires exactly the three unique dev poses')
        if report.get('passed') is not True or report.get('source_unchanged') is not True:
            raise ValueError('Calibration baseline or source fence failed')
        geometry=report.get('geometry',{})
        if geometry.get('passed') is not True or not finite(geometry.get('certified_margin_m')) or geometry['certified_margin_m']<=0:
            raise ValueError('Calibration requires each dev scene certified positive geometry margin')
        margins.append(geometry['certified_margin_m'])
        seen.add(declaration['pose_id']);score=report['oracle']
        observation=score['observation_metrics'];attempt=score['docking_acceptance']['attempts'][0]
        values=(observation.get('observation_position_error_p95_m'),observation.get('observation_yaw_error_p95_rad'),
                attempt.get('stationary_position_error_p95_m'),attempt.get('stationary_yaw_error_p95_rad'))
        if not all(finite(x) and x>=0 for x in values):
            raise ValueError('Calibration needs finite independently measured residuals and dock errors')
        for target,value in zip((rp,ry,ep,ey),values):target.append(value)
        receipts.append({'case_name':declaration['name'],'source_start_sha256':report['source_start_sha256'],
                         'source_end_sha256':report['source_end_sha256']})
    if seen!=expected:raise ValueError('All three dev baseline results are required')
    certified_margin=min(margins)
    hp=min(.04-max(ep),certified_margin);hy=.05-max(ey)
    if geometry_margin_m is not None:
        if not finite(geometry_margin_m) or geometry_margin_m<=0:raise ValueError('Geometry margin must be finite and positive')
        hp=min(hp,geometry_margin_m)
    if hp<=0 or hy<=0:raise ValueError('No remaining physical margin; baseline must be resolved without relaxing gates')
    high_p=min(hp/(3*math.sqrt(2)),max(2*max(rp),hp/(6*math.sqrt(2))))
    high_y=min(hy/3,max(2*max(ry),hy/6))
    return {'schema_version':1,'derived_from_split':'dev','case_names':sorted('baseline-'+x for x in seen),
        'residual_position_p95_max_m':max(rp),'residual_yaw_p95_max_rad':max(ry),
        'dock_position_p95_max_m':max(ep),'dock_yaw_p95_max_rad':max(ey),
        'position_margin_m':hp,'yaw_margin_rad':hy,'geometry_margin_m':geometry_margin_m,
        'certified_geometry_margin_m':certified_margin,
        'noise_high':[high_p,high_p,high_y],'noise_low':[high_p/2,high_p/2,high_y/2],
        'bias_position_m':hp/2,'bias_yaw_rad':hy/2,'baseline_receipts':receipts,
        'gaussian_support_is_bounded':False,'physical_thresholds_unchanged':True}


def perception_config(declaration,thresholds=None,vision_config=None):
    condition=declaration['condition']
    if condition=='ideal':return {'mode':'ideal'},{'schema':1,'kind':'none'}
    if condition.startswith('vision') or condition=='vision':
        if not isinstance(vision_config,dict) or vision_config.get('mode')!='vision':
            raise ValueError('Vision requires a frozen actual RGB producer configuration')
        faults={'vision_short_occlusion':{'kind':'short_occlusion','duration_wall_s':.10},
                'vision_short_delay':{'kind':'delay','delay_wall_s':.10,'delay_source_s':0.},
                'vision_replay_identity':{'kind':'replay_identity'},
                'vision_long_occlusion':{'kind':'long_occlusion','duration_wall_s':.8}}
        return dict(vision_config),{'schema':1,**faults.get(condition,{'kind':'none'})}
    if thresholds is None or thresholds.get('derived_from_split')!='dev':
        raise ValueError('Perturbed conditions require frozen dev-only thresholds')
    noise=[0.,0.,0.];bias=[0.,0.,0.];dropout=0.;fault={'schema':1,'kind':'none'}
    if condition in ('noise_low','combined','perturbed'):noise=thresholds['noise_low']
    if condition=='noise_high':noise=thresholds['noise_high']
    if condition=='bias_x_positive':bias[0]=thresholds['bias_position_m']
    if condition=='bias_x_negative':bias[0]=-thresholds['bias_position_m']
    if condition=='bias_yaw_positive':bias[2]=thresholds['bias_yaw_rad']
    if condition=='bias_yaw_negative':bias[2]=-thresholds['bias_yaw_rad']
    if condition in ('combined','perturbed'):
        bias=[0.,thresholds['bias_position_m']/2,-thresholds['bias_yaw_rad']/2]
    if condition=='dropout_10':dropout=.10
    if condition=='dropout_20':dropout=.20
    if condition=='short_occlusion':fault={'schema':1,'kind':'short_occlusion','duration_wall_s':.10}
    if condition=='long_occlusion':fault={'schema':1,'kind':'long_occlusion','duration_wall_s':.8}
    if condition=='delay_stale':fault={'schema':1,'kind':'delay','delay_wall_s':.55,'delay_source_s':.30}
    if condition=='replay_identity':fault={'schema':1,'kind':'replay_identity'}
    return {'schema':1,'mode':'perturbed','seed':declaration['seed'],'noise_std':noise,'bias':bias,
            'dropout_probability':dropout,'occlusion_windows':[],
            'max_covariance':[.0001+std*std for std in noise]},fault


def source_snapshot(source_root,manifest_path,panel,extra_inputs=()):
    files={str((source_root/name).resolve()) for name in panel['source_files']}
    files.update(str(path.resolve()) for path in (source_root/'tools').glob('cooperation*.py'))
    files.add(str((source_root/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/scripts/wait_ready.py').resolve()))
    files.update(str(Path(path).resolve()) for path in extra_inputs if path is not None)
    manifest=json.loads(manifest_path.read_text())
    files.update(str(Path(name).resolve()) for name in manifest.get('source_sha256',{}))
    def paths(value):
        if isinstance(value,dict):
            for child in value.values():paths(child)
        elif isinstance(value,list):
            for child in value:paths(child)
        elif isinstance(value,str) and Path(value).is_absolute() and Path(value).is_file():files.add(str(Path(value).resolve()))
    paths(manifest);files.add(str(manifest_path.resolve()))
    missing=[name for name in files if not Path(name).is_file()]
    if missing:raise ValueError('Missing executed/input source files: '+', '.join(missing))
    return {'schema_version':1,'wall_time':time.time(),'panel_sha256':hashlib.sha256(canonical(panel)).hexdigest(),
        'revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=source_root,text=True).strip(),
        'files':{name:digest(name) for name in sorted(files)}}


class ApiRejected(RuntimeError):
    def __init__(self,status,details):
        self.status,self.details=status,details
        super().__init__('HTTP rejected '+str(status)+': '+json.dumps(details,ensure_ascii=False))


def api_request(api,path,body=None,timeout=2.):
    request=urllib.request.Request(api+path,data=canonical(body) if body is not None else None,
        headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response:return json.load(response)
    except urllib.error.HTTPError as error:
        # A known rejection is retained, distinct from an unknown request outcome.
        try:details=json.load(error)
        except (ValueError,UnicodeError):details={}
        if isinstance(details,dict) and details.get('outcome')=='rejected':
            raise ApiRejected(error.code,details) from error
        raise RuntimeError('HTTP error with unconfirmed outcome '+str(error.code)+': '+json.dumps(details,ensure_ascii=False)) from error


def ensure_port_available(port):
    # Match HTTPServer's address reuse for closed TIME_WAIT connections.
    # SO_REUSEPORT is intentionally absent; a live listener still conflicts.
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        probe.bind(('127.0.0.1',port))


class EvidenceTail:
    # Action status is sparse; a long arm stage can outlive the physics tail.
    # Bound goal identities separately, retaining their last observed status.
    NATIVE_STATUS_LIMIT = 256

    def __init__(self,path):
        self.path=path;self.offset=0;self.partial=b'';self.records=deque(maxlen=20000);self.oracle=None;self.audit=None
        self.native_statuses=OrderedDict()

    def remember_native(self,record):
        if record.get('topic') not in ('dock_status','nav_status'):return
        for item in record['payload']['status_list']:
            identity=(record['topic'],bytes(item['goal_info']['goal_id']['uuid']).hex())
            self.native_statuses.pop(identity,None)
            self.native_statuses[identity]=item['status']
            while len(self.native_statuses)>self.NATIVE_STATUS_LIMIT:
                self.native_statuses.popitem(last=False)

    def refresh(self):
        if not self.path.exists():return
        with self.path.open('rb') as stream:
            stream.seek(self.offset);data=stream.read();self.offset=stream.tell()
        lines=(self.partial+data).split(b'\n');self.partial=lines.pop()
        for line in lines:
            if line:
                record=json.loads(line);self.records.append(record);self.remember_native(record)
    def native(self):
        for record in self.records:
            self.remember_native(record)
        return dict(self.native_statuses)
    def moving_dock(self):
        truth=[r for r in self.records if r['topic']=='truth']
        active=[key[1] for key,status in self.native().items() if key[0]=='dock_status' and status==2]
        if len(truth)<2 or len(active)!=1:return None
        a,b=truth[-2:];dt=b['source_stamp']-a['source_stamp']
        if not 0<dt<=.1 or time.time()-b['received_wall_time']>.5:return None
        pa=a['payload']['pose']['pose']['position'];pb=b['payload']['pose']['pose']['position']
        speed=math.sqrt(sum((pb[k]-pa[k])**2 for k in ('x','y','z')))/dt
        return active[0] if speed>.02 else None
    def quiet_proof(self):
        if self.oracle is None:
            spec=importlib.util.spec_from_file_location('acceptance_independent_physics',Path(__file__).with_name('cooperation_oracle_base.py'))
            self.oracle=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.oracle)
        records=list(self.records);physics=self.oracle.records_by_topic(records,'physics')
        if not physics:return None
        if self.audit is None:self.audit=self.oracle.scene_audit(physics[0]['payload'])
        truth=self.oracle.records_by_topic(records,'truth');cargo=self.oracle.records_by_topic(records,'cargo')
        clocks=self.oracle.records_by_topic(records,'clock');gate=self.oracle.Gate(.7);last=None
        for record in physics[-150:]:
            sample=self.oracle.physical_sample(record,truth,cargo,clocks,
                self.audit['tray_offset_from_base_footprint'],self.audit['half_extents'])
            if sample is None:continue
            raw=sample['raw'];guard=raw.get('docking_guard',{})
            valid=(sample['independent_crosscheck'] and raw.get('finite') is True and raw.get('car_hold') is True
                and sample['car_speed']<.01 and abs(sample['yaw_rate'])<.01
                and self.oracle.norm(raw.get('qvel6',[math.inf]))<.05
                and guard.get('enabled') is False and guard.get('tripped') is False)
            gate.update(sample['stamp'],valid);last=sample
        fresh=bool(last and clocks and 0<=time.time()-last['wall_time']<=.5
                   and -.1<=clocks[-1]['source_stamp']-last['stamp']<=.25)
        if fresh and gate.started is not None and last['stamp']-gate.started>=.7:
            return {'continuous_quiet':gate.result(),'source_stamp':last['stamp'],'received_wall_time':last['wall_time']}
        return None


def protected_snapshot(units):
    result={unit:subprocess.check_output(['systemctl','--user','show',unit,'--property=Id,LoadState,MainPID,InvocationID,ActiveState'],text=True).strip()
            for unit in units}
    for unit,value in result.items():
        fields=dict(line.split('=',1) for line in value.splitlines() if '=' in line)
        if fields.get('Id')!=unit or not fields.get('MainPID','').isdigit():
            raise RuntimeError('Protected unit identity could not be read: '+unit)
    return result


def wait_until(function,timeout,*,description):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        result=function()
        if result:return result
        time.sleep(.05)
    raise TimeoutError(description)


def lifecycle_active(snapshot,now=None):
    """Read real GetState receipts; action-server discovery is insufficient."""
    return snapshot_active(snapshot,now)


def native_cleanup_known(state,native,task_id,episode_id):
    """An explicit rejected handle permits cleanup, never task success."""
    if state.get('episode_id')!=episode_id or state.get('task',{}).get('id')!=task_id:
        return False
    if state.get('task',{}).get('status')=='unknown':return False
    handles=state.get('native_actions',[])
    if native:
        if not all(status in (4,5,6) for status in native.values()):return False
        if not isinstance(handles,list) or not handles:return False
        # A terminal from another goal cannot stand in for an evicted or
        # unobserved accepted UUID, even when the bridge task has failed.
        return all(isinstance(item,dict) and item.get('accepted') is True
            and any(key[1]==item.get('uuid') for key in native) for item in handles)
    cleanup = state.get('cleanup', {})
    if (state.get('task',{}).get('status') == 'failed' and state.get('native_actions') == []
            and cleanup.get('state') == 'verified'
            and all(cleanup.get(key) is True for key in ('native_terminal','quiet','hold','guard_disabled'))):
        # Failure before the first dispatch has no native UUID to wait for.
        # The caller still requires independently observed continuous quiet.
        return True
    return (state.get('task',{}).get('status')=='failed' and isinstance(handles,list) and bool(handles)
        and all(item.get('accepted') is False and item.get('terminal') is True
                and item.get('result_known') is False and item.get('status') is None
                and isinstance(item.get('uuid'),str) and len(item['uuid'])==32 for item in handles))


def rejected_submission_cleanup_known(state,native,episode_id):
    return (state.get('episode_id')==episode_id and state.get('task',{}).get('id') is None
        and state.get('task',{}).get('status')=='idle' and state.get('native_actions')==[]
        and all(status in (4,5,6) for status in native.values()))


def finish_observer(process,timeout):
    try:return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Scoring may still be writing an artifact. Do not destroy its evidence.
        return None


def signal_observer_once(process):
    if process.poll() is None and not getattr(process,'_acceptance_sigint_sent',False):
        process._acceptance_sigint_sent=True
        process.send_signal(signal.SIGINT)
        return True
    return False


def stop_non_motion_child(process,label,result):
    identities=owned_processes(process.pid)
    if process.poll() is None:
        os.killpg(process.pid,signal.SIGTERM)
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL)
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:pass
    remaining=surviving_processes(identities)
    result.setdefault('non_motion_children',[]).append({'label':label,'pid':process.pid,
        'returncode':process.poll(),'survivors':remaining,'identity_start_times':identities})
    return remaining


def owned_processes(parent_pid):
    """Capture PID start times for the owned tree, never match by program name."""
    rows=subprocess.check_output(['ps','-e','-o','pid=,ppid=,sid='],text=True).splitlines()
    topology=[tuple(map(int,line.split())) for line in rows]
    owned={parent_pid};changed=True
    while changed:
        changed=False
        for pid,parent,session in topology:
            if (parent in owned or session==parent_pid) and pid not in owned:owned.add(pid);changed=True
    result={}
    for pid in owned:
        try:
            stat=(Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split()
            result[pid]=stat[19]  # Field22, after pid/comm, uniquely binds PID lifetime.
        except (OSError,IndexError):pass
    return result


def surviving_processes(identities):
    survivors=[]
    for pid,started in identities.items():
        try:
            stat=(Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split()
            if stat[19]==started and stat[0]!='Z':survivors.append(pid)
        except (OSError,IndexError):pass
    return survivors


def stop_owned_launch(process,result):
    identities=owned_processes(process.pid)
    result['owned_process_identities']={str(pid):started for pid,started in identities.items()}
    if process.poll() is None:os.killpg(process.pid,signal.SIGINT)
    try:process.wait(timeout=20)
    except subprocess.TimeoutExpired:result['errors'].append('Owned launch still active after safe SIGINT')
    remaining=surviving_processes(identities)
    result['owned_process_survivors']=remaining
    if remaining:result['errors'].append('Owned descendants still active; root owns reconciliation')
    return not remaining


def delivery_start_marker(body, manifest):
    """Record the requested/default goal before POST, never infer it at arrival."""
    from cooperation_core import task_delivery_pose
    return {'expected_delivery_pose': task_delivery_pose(body, manifest.get('delivery_pose')),
            'requested_delivery_pose': dict(body['delivery_pose']) if 'delivery_pose' in body else None}


def execute_case(declaration,directory,args,panel,thresholds,vision_config):
    directory.mkdir(mode=0o700)
    api='http://127.0.0.1:9090/coop-api';source_root=args.source_root.resolve()
    launcher=source_root/'tools/fishbot_cooperation.sh';budget=declaration['budget']
    result={'case':declaration,'passed':False,'task_completion_passed':False,'expected_safety_passed':False,
            'start_posts':0,'cleanup_complete':False,'domain':120,'port':9090,'errors':[]}
    env=dict(os.environ,FISHBOT_COOP_PYTHON=str(args.python),FISHBOT_COOP_DOMAIN='120',
             FISHBOT_MUJOCO_DOMAIN_ID='120',ROS_DOMAIN_ID='120',
             ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST',ROS_LOCALHOST_ONLY='1')
    streams=[];children=[];launch=observer=None;task_id=None;episode=None;start_snapshot=None
    markers={'events':[]};marker_path=directory/'markers.json'
    def marker(kind,**fields):
        event={'kind':kind,'wall_time':time.time(),'task_id':task_id,'episode_id':episode,**fields}
        markers['events'].append(event);private_json(marker_path,markers,replace=marker_path.exists())
    def spawn(command,label):
        stream=(directory/(label+'.log')).open('x');os.chmod(stream.name,0o600);streams.append(stream)
        process=subprocess.Popen(command,cwd=source_root,env=env,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        children.append((label,process));return process
    try:
        planning_site=subprocess.check_output([str(args.python),'-c','import sysconfig; print(sysconfig.get_path("purelib"))'],text=True).strip()
        env['PYTHONPATH']=planning_site+':/usr/lib/python3/dist-packages:'+env.get('PYTHONPATH','')
        protected=protected_snapshot(args.protected_unit)
        result['protected_units_before']=protected
        result['historical_instances_were_running']=any('ActiveState=active' in value and 'MainPID=0' not in value.splitlines() for value in protected.values())
        # Check both identities before creating the owned launch.
        ensure_port_available(9090)
        check=['bash','-c','set -e; source "$1"; exec "$2" -B "$3" --domain-check','cooperation-domain-check',
               str(source_root/'tools/fishbot_mujoco_env.sh'),str(args.python),str(Path(__file__).resolve())]
        subprocess.run(check,env=env,check=True,timeout=12)
        config,fault=perception_config(declaration,thresholds,vision_config)
        config_path=directory/'perception.json';fault_path=directory/'faults.json'
        private_json(config_path,config);private_json(fault_path,fault)
        scene=directory/'scene'
        command=[str(launcher),'prepare','--so101-project',str(args.so101_project),'--output',str(scene),
                 '--perception-config',str(config_path),'--spawn',*map(str,declaration['spawn'][:2]),
                 '--spawn-yaw',str(declaration['spawn'][2]),'--observation-faults',str(fault_path),
                 '--camera-light-scale',str(declaration['camera_light_scale'])]
        prepared=spawn(command,'prepare');prepared.wait(timeout=60)
        if prepared.returncode:raise RuntimeError('Existing prepare failed; inspect preserved prepare.log')
        manifest=scene/'scene-manifest.json'
        geometry_path=directory/'geometry.json'
        geometry=spawn([str(args.python),'-B',str(source_root/'tools/cooperation_geometry_check.py'),
            '--manifest',str(manifest),'--output',str(geometry_path)],'geometry')
        geometry.wait(timeout=60)
        if geometry.returncode:raise RuntimeError('Independent geometry check failed before launch')
        certified=json.loads(geometry_path.read_text())
        if (certified.get('passed') is not True or not finite(certified.get('certified_margin_m'))
            or certified['certified_margin_m']<=0 or certified.get('manifest_sha256')!=digest(manifest)
            or certified.get('scene_sha256')!=digest(json.loads(manifest.read_text())['world_xml'])):
            raise ValueError('Geometry result does not certify positive clearance for this exact scene/manifest')
        result['geometry']=certified
        input_files=(config_path,fault_path,args.thresholds,args.vision_config)
        start_snapshot=source_snapshot(source_root,manifest,panel,input_files)
        private_json(directory/'source-start.json',start_snapshot)
        launch=spawn([str(launcher),'run','manifest:='+str(manifest),'output:='+str(directory/'runtime'),
                      'domain:=120','port:=9090'],'launch')
        startup_deadline=time.monotonic()+budget['startup_timeout_s']
        def ready():
            if launch.poll() is not None:raise RuntimeError('Owned launch exited before readiness')
            try:
                state=api_request(api,'/state')
                native=state.get('native_lifecycle',{})
                if (state.get('ready') is True and state.get('domain')==120 and state.get('episode_id')
                    and lifecycle_active(native)):
                    result['startup_lifecycle']=native
                    return state
                return None
            except (OSError,RuntimeError):return None
        state=wait_until(ready,max(0.,startup_deadline-time.monotonic()),description='Readiness exceeded frozen budget')
        episode=state['episode_id'];task_id=str(uuid.uuid4())
        private_json(marker_path,markers)
        observed=directory/'observer'
        observer=spawn([str(launcher),'oracle','--domain','120','--api',api,'--expected-episode',episode,
            '--allow-initial-episode','--scope',declaration['scope'],'--expected-outcome',declaration['expected_outcome'],
            '--markers',str(marker_path),'--output',str(observed)],'oracle')
        tail=EvidenceTail(observed/'observer.jsonl')
        def observing():
            if observer.poll() is not None:raise RuntimeError('Oracle exited before task dispatch')
            tail.refresh()
            return any(r['topic']=='physics' for r in tail.records) and any(r['topic']=='publisher_inventory' for r in tail.records)
        wait_until(observing,min(15.,max(0.,startup_deadline-time.monotonic())),description='Oracle did not independently observe physics and publishers')
        # Observer discovery consumed time. Recheck rather than reuse the old
        # pre-observer readiness receipt; stay inside the original 55s budget.
        state=wait_until(ready,max(0.,startup_deadline-time.monotonic()),description='Dispatch readiness exceeded frozen budget')
        if state.get('episode_id')!=episode:raise RuntimeError('Episode changed before submission')
        private_json(directory/'runtime'/'acceptance-report.json',{
            'schema_version':1,'status':'running','passed':False,'case':declaration,
            'budget':budget,'scope':declaration['scope'],'task_id':task_id,'episode_id':episode,
            'task_completion_passed':False,'expected_safety_passed':False,
            'evidence_mode':'live_observation','independent_score_available':False})
        prefix='dock' if declaration['scope']=='dock' else 'full'
        body={'task_id':task_id,'issued_at':time.time(),'episode_id':episode,'scope':declaration['scope']}
        declaration_fields=(delivery_start_marker(body,json.loads(manifest.read_text()))
                            if declaration['scope']=='transport' else {})
        marker(prefix+'_started',scope=declaration['scope'],**declaration_fields)
        result['start_posts']=1  # Set before POST; an uncertain send never authorizes retry.
        rejected=False
        try:
            receipt=api_request(api,'/start',body)
            result['start_receipt']=receipt
        except ApiRejected as error:
            rejected=True
            result['start_rejection']={'http_status':error.status,**error.details}
            result['errors'].append(str(error))
            marker(prefix+'_finished',scope=declaration['scope'],submission_rejected=True)
        except (OSError,RuntimeError) as error:
            result['start_request_unknown']=str(error)  # Reconcile the original task ID below.
        cancel_post_sent=False;cancel_marker_recorded=False;cancel_uuid=None
        deadline=time.monotonic()+budget['caller_timeout_s']
        while not rejected and time.monotonic()<deadline:
            tail.refresh();state=api_request(api,'/state');task=state.get('task',{})
            if task.get('id')!=task_id:
                time.sleep(.05);continue
            if declaration['expected_outcome']=='safe_cancel' and not cancel_marker_recorded:
                for action in state.get('native_actions',[]):
                    canceled_at=action.get('cancel_requested_wall_time')
                    if (finite(canceled_at) and action.get('accepted') is True
                        and action.get('label')=='Nav2停靠'
                        and (cancel_uuid is None or action.get('uuid')==cancel_uuid)):
                        marker('cancel_requested',wall_time=canceled_at,native_uuid=action.get('uuid'))
                        cancel_marker_recorded=True;break
            if declaration['condition'] in ('moving_cancel','vision_moving_cancel') and not cancel_post_sent and tail.moving_dock():
                cancel_uuid=tail.moving_dock();cancel_post_sent=True
                try:result['cancel_receipt']=api_request(api,'/cancel',{'task_id':task_id,'issued_at':time.time()})
                except (OSError,RuntimeError) as error:result['cancel_request_unknown']=str(error)
            if task.get('status') in ('succeeded','failed','canceled','unknown'):
                result['task']=task;marker(prefix+'_finished',scope=declaration['scope']);break
            if launch.poll() is not None or observer.poll() is not None:raise RuntimeError('Owned launch or observer exited while task active')
            time.sleep(.05)
        else:
            if not rejected:raise TimeoutError('Task exceeded frozen caller watchdog; no task resend')
        # root bridge's persisted cleanup includes its own acknowledgements;
        # oracle independently checks raw physics/native messages at this marker.
        def cleaned():
            tail.refresh();latest=api_request(api,'/state')
            native=tail.native()
            physics=[r for r in tail.records if r['topic']=='physics']
            known=(rejected_submission_cleanup_known(latest,native,episode) if rejected
                   else native_cleanup_known(latest,native,task_id,episode))
            if not physics or not known:return None
            raw=physics[-1]['payload'];guard=raw.get('docking_guard',{})
            if (latest.get('episode_id')!=episode or (not rejected and latest.get('task',{}).get('id')!=task_id)
                or latest.get('task',{}).get('status')=='unknown' or raw.get('car_hold') is not True
                or guard.get('enabled') is not False or guard.get('tripped') is not False
                or time.time()-physics[-1]['received_wall_time']>.5):return None
            proof=tail.quiet_proof()
            if not proof:return None
            result['pre_stop_independent_quiet']=proof
            return latest
        clean=wait_until(cleaned,budget['cleanup_timeout_s'],description='Fresh held/native-terminal/guard-disabled cleanup unavailable')
        # Keep sampling through a complete independent source dwell.
        source_start=[r for r in tail.records if r['topic']=='physics'][-1]['source_stamp']
        def dwell():
            clean_state=cleaned()
            physics=[r for r in tail.records if r['topic']=='physics']
            return clean_state if clean_state and physics[-1]['source_stamp']-source_start>=1. else None
        result['cleanup_state']=wait_until(dwell,budget['cleanup_timeout_s'],description='Independent cleanup dwell unavailable')
        marker('cleanup_checked');result['cleanup_complete']=True
        time.sleep(.1)
        # Sampling has proved fresh stop. Reclaim physics/rendering before the
        # oracle's offline parse; its independently captured evidence remains.
        signal_observer_once(observer)
        result['owned_launch_stopped']=stop_owned_launch(launch,result)
        with socket.socket() as probe:
            probe.settimeout(.3)
            result['owned_port_closed']=probe.connect_ex(('127.0.0.1',9090))!=0
        score_exit=finish_observer(observer,budget['observer_score_timeout_s']);result['observer_returncode']=score_exit
        if score_exit is None:raise RuntimeError('Oracle scoring still active; preserved for root reconciliation')
        scores=list(observed.glob('score-*.json'))
        if len(scores)!=1:raise RuntimeError('Oracle did not produce exactly one original score artifact')
        result['oracle']=json.loads(scores[0].read_text());result['score_file']=str(scores[0])
        ended=source_snapshot(source_root,manifest,panel,input_files);private_json(directory/'source-end.json',ended)
        result['source_unchanged']=start_snapshot['files']==ended['files'] and start_snapshot['revision']==ended['revision']
        result['source_start_sha256']=digest(directory/'source-start.json');result['source_end_sha256']=digest(directory/'source-end.json')
        result['protected_units_after']=protected_snapshot(args.protected_unit)
        result['protected_instances_unchanged']=result['protected_units_after']==protected
        result['passed']=bool(result['oracle'].get('passed') is True and result['source_unchanged']
            and result['protected_instances_unchanged'] and result.get('owned_launch_stopped') is True
            and result.get('owned_port_closed') is True and not result['errors'])
        result['task_completion_passed']=bool(result['passed'] and declaration['expected_outcome']=='success')
        result['expected_safety_passed']=bool(result['passed'] and declaration['expected_outcome']=='safe_cancel')
    except (OSError,ValueError,RuntimeError,TimeoutError,subprocess.SubprocessError,KeyboardInterrupt) as error:
        result['errors'].append(type(error).__name__+': '+str(error))
    finally:
        # A failed/unknown cleanup retains the live owned world for root.
        if observer and observer.poll() is None and result['cleanup_complete']:
            signal_observer_once(observer)
            finish_observer(observer,5.)
        if launch and launch.poll() is None and result['cleanup_complete'] and (observer is None or observer.poll() is not None):
            stop_owned_launch(launch,result)
        result['retained_launch_pid']=launch.pid if launch and launch.poll() is None else None
        result['retained_observer_pid']=observer.pid if observer and observer.poll() is None else None
        result['retained_non_motion_pids']=[]
        for label,process in children:
            if label in ('prepare','geometry'):
                result['retained_non_motion_pids'].extend(stop_non_motion_child(process,label,result))
        if result['retained_launch_pid'] or result['retained_observer_pid'] or result.get('owned_process_survivors') or result['retained_non_motion_pids']:result['passed']=False
        for stream in streams:stream.close()
        result['status']='passed' if result['passed'] else 'unknown' if result.get('retained_launch_pid') or result.get('retained_observer_pid') else 'failed'
        result['scope']=declaration['scope'];result['independent_score_available']='oracle' in result
        private_json(directory/'result.json',result)
        report_path=directory/'runtime'/'acceptance-report.json'
        if report_path.parent.is_dir():private_json(report_path,result,replace=report_path.exists())
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=('baseline','perturbed','fault','vision','full','all'),default='baseline')
    parser.add_argument('--panel',type=Path);parser.add_argument('--write-panel',type=Path)
    parser.add_argument('--thresholds',type=Path);parser.add_argument('--vision-config',type=Path)
    parser.add_argument('--output',type=Path);parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--python',type=Path);parser.add_argument('--so101-project',type=Path)
    parser.add_argument('--protected-unit',action='append',default=[])
    parser.add_argument('--variant');parser.add_argument('--case');parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--split',choices=('dev','holdout','all'),default='all')
    parser.add_argument('--domain-check',action='store_true');parser.add_argument('--geometry-margin-m',type=float)
    args=parser.parse_args(argv)
    if args.domain_check:
        os.environ['ROS_DOMAIN_ID']='120'
        from fishbot_simulation_suite import domain_is_empty
        domain_is_empty()
        return 0
    panel=validate_panel(json.loads(args.panel.read_text())) if args.panel else build_panel()
    if args.write_panel:
        private_json(args.write_panel,panel);print(json.dumps({'panel':str(args.write_panel),'cases':len(panel['cases'])}));return 0
    cases=[item for item in panel['cases'] if (args.phase=='all' or item['phase']==args.phase)
           and (args.variant is None or item['variant']==args.variant) and (args.case is None or item['name']==args.case)
           and (args.split=='all' or item['split']==args.split)]
    if not cases:parser.error('No declared cases selected')
    if args.dry_run:
        print(json.dumps({'execution_started':False,'cases':cases,'counts':panel['expected_counts']},ensure_ascii=False,indent=2));return 0
    if not args.panel or not args.output or not args.python or not args.so101_project:
        parser.error('Execution requires an existing frozen panel, new private output, planning Python and SO101 project')
    if len(args.protected_unit)<2:parser.error('Explicit existing107/114 protected unit identities are required')
    output=args.output.resolve()
    if output.exists() or output.is_relative_to(args.source_root.resolve()):parser.error('Output must be new and outside source repository')
    output.mkdir(parents=True,mode=0o700)
    thresholds=json.loads(args.thresholds.read_text()) if args.thresholds else None
    vision=json.loads(args.vision_config.read_text()) if args.vision_config else None
    private_json(output/'panel.json',panel)
    reports=[]
    for declaration in cases:
        result=execute_case(declaration,output/declaration['name'],args,panel,thresholds,vision);reports.append(result)
        private_json(output/'report.json',{'schema_version':1,'phase':args.phase,'cases':reports,'case_count':len(cases),
            'completed_count':len(reports),'passed':len(reports)==len(cases) and all(r['passed'] for r in reports)},replace=(output/'report.json').exists())
        if result.get('retained_launch_pid') or result.get('retained_observer_pid') or result.get('owned_process_survivors') or result.get('retained_non_motion_pids'):return 1
        if declaration['phase']=='baseline' and not result['passed']:
            return 1  # Resolve the baseline before further dispatch/calibration.
        dev=[r for r in reports if r['case']['phase']=='baseline' and r['case']['split']=='dev']
        if thresholds is None and len(dev)==3:
            thresholds=derive_thresholds(dev,geometry_margin_m=args.geometry_margin_m)
            private_json(output/'thresholds.json',thresholds)
    return 0 if all(r['passed'] for r in reports) else 1


if __name__=='__main__':sys.exit(main())
