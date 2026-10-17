#!/usr/bin/env python3
"""Independent K physical scoring and ROS sampling, retained for audit.

Migrated from the accepted K observer and its reset-receipt extension.
The public entry point is cooperation_oracle.py. Pure physical scoring stays
independent of cooperation_core, bridge, simulation, and controller helpers.
"""
from __future__ import annotations
import argparse
import ast
import bisect
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import statistics
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parent
DRIVER = BASE / 'cooperation_sim.py'


def clean(value):
    if isinstance(value, (bytes, bytearray)):
        return list(value)
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def private_json(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        json.dump(clean(value), output, indent=2, ensure_ascii=False, allow_nan=False)
        output.write('\n')


def driver_audit():
    source = DRIVER.read_bytes()
    tree = ast.parse(source.decode())
    writes = []
    class Walk(ast.NodeVisitor):
        def __init__(self): self.scope = []
        def visit_ClassDef(self, node):
            self.scope.append(node.name); self.generic_visit(node); self.scope.pop()
        def visit_FunctionDef(self, node):
            self.scope.append(node.name); self.generic_visit(node); self.scope.pop()
        def visit_Assign(self, node):
            for target in node.targets:
                text = ast.unparse(target)
                if isinstance(target, ast.Subscript) and ('.qpos' in text or '.qvel' in text):
                    writes.append({'scope': '.'.join(self.scope), 'line': node.lineno, 'target': text})
            self.generic_visit(node)
        def visit_AugAssign(self, node):
            text = ast.unparse(node.target)
            if '.qpos' in text or '.qvel' in text:
                writes.append({'scope': '.'.join(self.scope), 'line': node.lineno, 'target': text})
            self.generic_visit(node)
    Walk().visit(tree)
    allowed = {'Physics.__init__', 'FrameWriter.run'}
    return {'path': str(DRIVER), 'sha256': hashlib.sha256(source).hexdigest(),
            'state_writes': writes, 'no_runtime_physics_teleport': all(w['scope'] in allowed for w in writes),
            'allowed_init_and_isolated_render_only': sorted(allowed)}


def stamp(message):
    return message['sec'] + message['nanosec']*1e-9


def topic_stamp(topic, payload):
    if topic == 'physics': return float(payload['stamp'])
    if topic == 'clock': return stamp(payload['clock'])
    if topic in ('truth', 'cargo', 'beacon', 'station_pose', 'station_detection', 'vision_quality', 'camera_metadata', 'camera_image', 'camera_info', 'plan', 'received_global_plan', 'lookahead_collision_arc', 'docking_trajectory', 'initialpose', 'encoder_odom', 'cmd_vel', 'amcl_pose'): return stamp(payload['header']['stamp'])
    if topic == 'tf' and payload.get('transforms'):return stamp(payload['transforms'][0]['header']['stamp'])
    if topic == 'nav_feedback': return stamp(payload['feedback']['current_pose']['header']['stamp'])
    if topic == 'nav_status': return None
    return None


def quat_matrix(q):
    w,x,y,z = q
    return [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
            [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
            [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]


def quaternion(pose):
    q=pose['orientation']; return [q['w'],q['x'],q['y'],q['z']]


def point(pose):
    p=pose['position']; return [p['x'],p['y'],p['z']]


def matvec(matrix, vector):
    return [sum(row[j]*vector[j] for j in range(3)) for row in matrix]


def transpose(matrix): return list(map(list,zip(*matrix)))

def norm(values): return math.sqrt(sum(x*x for x in values))


def yaw(q):
    w,x,y,z=q
    return math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))


def yaw_error(a,b): return abs(math.atan2(math.sin(a-b),math.cos(a-b)))


class Gate:
    def __init__(self,duration,max_gap=.1):
        self.duration,self.max_gap=duration,max_gap
        self.started=self.last=None
        self.first_pass=None
        self.longest=0.
    def update(self,t,valid):
        if not math.isfinite(t):
            self.started=self.last=None;return False
        if self.last is not None and (t <= self.last or t-self.last>self.max_gap):
            self.started=None
        self.last=t
        if not valid:
            self.started=None;return False
        if self.started is None:self.started=t
        self.longest=max(self.longest,t-self.started)
        passed=t-self.started>=self.duration
        if passed and self.first_pass is None:self.first_pass=t
        return passed
    def result(self):
        return {'passed':self.first_pass is not None,'first_pass_stamp':self.first_pass,
                'longest_source_duration_s':self.longest,'required_duration_s':self.duration,
                'max_source_gap_s':self.max_gap}


def nearest(items, t, max_gap=.06):
    if not items:return None
    i=bisect.bisect_left(items,t,key=lambda item:item['source_stamp'])
    choices=[items[k] for k in (i-1,i) if 0 <= k < len(items)]
    found=min(choices,key=lambda item:abs(item['source_stamp']-t))
    return found if abs(found['source_stamp']-t)<=max_gap else None


def physical_sample(record, truth, cargo, clocks, offset, half):
    raw,t=record['payload'],record['source_stamp']
    car=nearest(truth,t);object_pose=nearest(cargo,t);clock=nearest(clocks,t,.04)
    if car is None or object_pose is None or clock is None:return None
    # These positions come from separately subscribed standard ROS messages.
    car_pose=car['payload']['pose']['pose'];cargo_pose=object_pose['payload']['pose']
    cp,qp=point(car_pose),point(cargo_pose)
    cq,qq=quaternion(car_pose),quaternion(cargo_pose)
    # BODY twist may refer to an inertial COM. Derive origin motion from the
    # independently subscribed origin positions, including in old-source runs.
    car_index=bisect.bisect_left(truth,car['source_stamp'],key=lambda item:item['source_stamp'])
    if car_index == 0:return None
    previous_car=truth[car_index-1]
    origin_dt=car['source_stamp']-previous_car['source_stamp']
    if not 0 < origin_dt <= .1:return None
    previous_pose=previous_car['payload']['pose']['pose']
    previous_position=point(previous_pose)
    origin_linear=[(cp[i]-previous_position[i])/origin_dt for i in range(3)]
    origin_yaw_rate=math.atan2(math.sin(yaw(cq)-yaw(quaternion(previous_pose))),
                               math.cos(yaw(cq)-yaw(quaternion(previous_pose))))/origin_dt
    rotation=quat_matrix(cq);inverse=transpose(rotation)
    tray=[cp[i]+matvec(rotation,offset)[i] for i in range(3)]
    relative=matvec(inverse,[qp[i]-tray[i] for i in range(3)])
    obj_rotation=quat_matrix(qq)
    relative_rotation=[[sum(inverse[i][k]*obj_rotation[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    extents=[sum(abs(relative_rotation[i][j])*half[j] for j in range(3)) for i in range(3)]
    twist=car['payload']['twist']['twist'];linear=twist['linear'];angular=twist['angular']
    forces=list(raw['finger_normal_forces_n'].values())
    crosscheck=max(abs(cp[i]-raw['car']['position'][i]) for i in range(3))<.012
    crosscheck &= max(abs(qp[i]-raw['cargo']['position'][i]) for i in range(3))<.012
    crosscheck &= max(abs(relative[i]-raw['cargo']['position_relative_tray'][i]) for i in range(3))<.012
    return {'stamp':t,'wall_time':record['received_wall_time'],'car':cp,'cargo':qp,'relative':relative,
            'extents':extents,'car_yaw':yaw(cq),'car_speed':norm(origin_linear),
            'car_velocity_origin_finite_difference':origin_linear,'car_velocity_origin_dt_s':origin_dt,
            'reported_twist_speed_not_scoring_authority':norm([linear['x'],linear['y'],linear['z']]),
            'yaw_rate':origin_yaw_rate,'forces':forces,'raw':raw,'independent_crosscheck':bool(crosscheck),
            'clock_delta':clock['source_stamp']-t}


def scene_audit(raw):
    source=raw['source'];manifest=source['manifest'];path=Path(manifest['world_xml'])
    xml=path.read_bytes();root=ET.fromstring(xml)
    target=root.find("./worldbody/body[@name='grasp_target']")
    geom=target.find("geom[@name='target_collision']") if target is not None else None
    joint=target.find("freejoint[@name='target_free']") if target is not None else None
    half=[float(x) for x in geom.get('size').split()] if geom is not None else [.009,.009,.008]
    car=root.find("./worldbody/body[@name='base_footprint']")
    base=car.find("body[@name='base_link']")
    tray=base.find("body[@name='cargo_tray']")
    offset=[sum(parts) for parts in zip(map(float,base.get('pos','0 0 0').split()),map(float,tray.get('pos','0 0 0').split()))]
    return {'world_path':str(path),'reported_scene_sha256':source['scene_sha256'],
            'actual_scene_sha256':hashlib.sha256(xml).hexdigest(),
            'sha_matches':hashlib.sha256(xml).hexdigest()==source['scene_sha256'],
            'target_body':'grasp_target','target_freejoint':'target_free','target_geom':'target_collision',
            'target_is_world_child_with_freejoint':target is not None and joint is not None,
            'target_mocap':target.get('mocap','false') if target is not None else None,
            'equality_weld_count':len(root.findall('./equality/weld')),
            'half_extents':half,'tray_offset_from_base_footprint':offset,
            'home_q6':manifest['arm_home_qpos6'],'dock_pose':manifest['dock_pose'],
            'native_dock_pose':manifest.get('native_dock_pose',manifest['dock_pose']),
            'source_sha256':manifest['source_sha256']}


def records_by_topic(records,topic):
    return sorted((r for r in records if r['topic']==topic and r.get('source_stamp') is not None),key=lambda r:r['source_stamp'])


def marker_events(records, marker_path):
    events=[]
    for r in records:
        if r['topic']=='marker_file':events.extend(r['payload'].get('events',[]))
    if marker_path.exists():events.extend(json.loads(marker_path.read_text()).get('events',[]))
    seen=set();unique=[]
    for event in events:
        key=json.dumps(event,sort_keys=True)
        if key not in seen:seen.add(key);unique.append(event)
    return sorted(unique,key=lambda e:e.get('wall_time',0))


def topic_statistics(records):
    answer={}
    for topic in sorted(set(r['topic'] for r in records)):
        items=[r for r in records if r['topic']==topic]
        gaps=[b['received_monotonic']-a['received_monotonic'] for a,b in zip(items,items[1:])]
        source=[r['source_stamp'] for r in items if r.get('source_stamp') is not None]
        source_gaps=[b-a for a,b in zip(source,source[1:])]
        answer[topic]={'count':len(items),'max_received_gap_s':max(gaps,default=None),
                       'max_source_gap_s':max(source_gaps,default=None),
                       'repeated_or_backward_source':sum(g<=0 for g in source_gaps),
                       'received_gap_over_0_1_s':sum(g>.1 for g in gaps)}
        if len(gaps)>1:
            sorted_gaps=sorted(gaps)
            answer[topic]['p99_received_gap_s']=sorted_gaps[min(len(gaps)-1,math.ceil(.99*len(gaps))-1)]
    physics=[r['payload'] for r in records if r['topic']=='physics']
    seq=[r['sequence'] for r in physics]
    if 'physics' in answer:
        answer['physics']['missing_sequence_count']=sum(max(0,b-a-1) for a,b in zip(seq,seq[1:]))
    return answer


def full_score(samples, audit):
    dock=Gate(.7);lift=Gate(1.);placed=Gate(1.);home=Gate(1.);final=Gate(1.)
    baseline_samples=[];baseline=None;load_car=load_cargo=None
    first_move=None;premature_move=False;max_cargo_distance=max_car_distance=0.
    forbidden=[];bad_crosschecks=0;full_footprint_violations=0
    previous=None
    for item in samples:
        raw,t=item['raw'],item['stamp']
        if not item['independent_crosscheck']:bad_crosschecks+=1
        valid=item['independent_crosscheck'] and raw.get('finite') is True
        quiet=item['car_speed']<.01 and abs(item['yaw_rate'])<.01
        docking_error=math.hypot(item['car'][0]-audit['dock_pose'][0],item['car'][1]-audit['dock_pose'][1])
        dock_valid=valid and docking_error<=.04 and yaw_error(item['car_yaw'],audit['dock_pose'][2])<=.05 and quiet
        if dock.first_pass is None:
            if dock_valid:baseline_samples.append(item['cargo'][2])
            else:baseline_samples=[]
            if dock.update(t,dock_valid):baseline=statistics.median(baseline_samples)
        if dock.first_pass is not None:
            lifted=valid and item['cargo'][2]-baseline>=.025 and min(item['forces'])>.02
            lift.update(t,lifted)
        footprint=all(abs(item['relative'][i])+item['extents'][i]<=.058 for i in range(2))
        released=(valid and footprint and raw['cargo_tray_floor_contact'] and max(item['forces'])<.02
                  and norm(raw['cargo']['velocity_relative_tray'])<.002)
        if lift.first_pass is not None and placed.first_pass is None and placed.update(t,released):
            load_car,load_cargo=list(item['car']),list(item['cargo'])
        if placed.first_pass is not None:
            home_valid=valid and max(abs(a-b) for a,b in zip(raw['q6'],audit['home_q6']))<.02 and norm(raw['qvel6'])<.05 and quiet
            home.update(t,home_valid)
            if not quiet and first_move is None:
                first_move=t;premature_move=home.first_pass is None or home.first_pass>t
            cargo_distance=norm([item['cargo'][i]-load_cargo[i] for i in range(2)])
            car_distance=norm([item['car'][i]-load_car[i] for i in range(2)])
            max_cargo_distance=max(max_cargo_distance,cargo_distance);max_car_distance=max(max_car_distance,car_distance)
            if not footprint:full_footprint_violations+=1
            world_cargo_speed=math.inf
            if previous and 0 < t-previous['stamp']<=.1:
                world_cargo_speed=norm([item['cargo'][i]-previous['cargo'][i] for i in range(3)])/(t-previous['stamp'])
            final.update(t,max_cargo_distance>=.5 and max_car_distance>=.5 and quiet and released and world_cargo_speed<.005)
        if raw.get('arm_forbidden_contact_total',0) or raw.get('car_forbidden_contact_total',0):
            if not forbidden:forbidden.append({'stamp':t,'arm_total':raw.get('arm_forbidden_contact_total'),'car_total':raw.get('car_forbidden_contact_total'),
                                                'arm_pairs':raw.get('arm_forbidden_contacts'),'car_pairs':raw.get('car_forbidden_contacts')})
        previous=item
    checks={'dock_true_pose_and_stop':dock.result(),'actual_lift_and_two_tip_forces':lift.result(),
            'released_full_footprint_supported_and_relative_rest':placed.result(),'arm_home_before_motion':home.result(),
            'final_car_and_cargo_rest':final.result(),
            'transport':{'passed':max_cargo_distance>=.5 and max_car_distance>=.5,
                         'max_true_cargo_displacement_m':max_cargo_distance,'max_true_car_displacement_m':max_car_distance,
                         'first_car_motion_after_release_stamp':first_move,'car_moved_before_home_dwell':premature_move,
                         'full_footprint_violation_samples_after_release':full_footprint_violations},
            'forbidden_contacts':{'passed':not forbidden,'first_violation':forbidden},
            'independent_pose_crosschecks':{'passed':bad_crosschecks==0,'bad_samples':bad_crosschecks},
            'cargo_baseline_z_m':baseline,'scored_samples':len(samples)}
    checks['passed']=bool(samples) and all(checks[k]['passed'] for k in ('dock_true_pose_and_stop','actual_lift_and_two_tip_forces',
              'released_full_footprint_supported_and_relative_rest','arm_home_before_motion','final_car_and_cargo_rest','transport',
              'forbidden_contacts','independent_pose_crosschecks')) and not premature_move
    return checks


def goal_id(value):return bytes(value).hex()


def cancellation_score(records,samples,event,next_start):
    start=event['wall_time'];end=next_start or math.inf
    actions={}
    for name,status_topic,feedback_topic in (
            ('NavigateToPose','nav_status','nav_feedback'),('DockRobot','dock_status','dock_feedback')):
        before=[r for r in records if r['topic']==status_topic and r['received_wall_time']<=start]
        active_ids=set()
        if before:
            active_ids={goal_id(s['goal_info']['goal_id']['uuid']) for s in before[-1]['payload']['status_list'] if s['status'] in (1,2,3)}
        canceled_ids=set()
        for r in records:
            if r['topic']==status_topic and start<=r['received_wall_time']<end:
                canceled_ids.update(goal_id(s['goal_info']['goal_id']['uuid']) for s in r['payload']['status_list'] if s['status']==5)
        feedback_ids={goal_id(r['payload']['goal_id']['uuid']) for r in records
                      if r['topic']==feedback_topic and start-8<=r['received_wall_time']<=start}
        actions[name]={'active':active_ids,'canceled':canceled_ids,'matching':active_ids&canceled_ids&feedback_ids}
    active={(name,identity) for name,value in actions.items() for identity in value['active']}
    canceled={(name,identity) for name,value in actions.items() for identity in value['canceled']}
    matching={(name,identity) for name,value in actions.items() for identity in value['matching']}
    native_start_wall=None
    if len(matching)==1:
        name,identity=next(iter(matching))
        status_topic='dock_status' if name=='DockRobot' else 'nav_status'
        starts=[r['received_wall_time'] for r in records
                if r['topic']==status_topic and r['received_wall_time']<=start
                and any(goal_id(s['goal_info']['goal_id']['uuid'])==identity and s['status'] in (1,2)
                        for s in r['payload']['status_list'])]
        if starts:native_start_wall=min(starts)
    motion_window_start=max(start-8,native_start_wall) if native_start_wall is not None else start
    moving_samples=[s for s in samples if motion_window_start<=s['wall_time']<=start]
    moving_before=any(s['car_speed']>.02 for s in moving_samples)
    quiet=Gate(.7)
    for s in samples:
        if start<=s['wall_time']<end:
            quiet.update(s['stamp'],s['independent_crosscheck'] and s['car_speed']<.01 and abs(s['yaw_rate'])<.01 and norm(s['raw']['qvel6'])<.05)
    same_id=any(r['topic']=='http_state' and start<=r['received_wall_time']<end and
                r['payload'].get('task',{}).get('id')==event['task_id'] for r in records)
    native=bool(matching) and len(active)==1
    return {'task_id':event['task_id'],'cancel_requested_wall_time':start,'moving_before_cancel':moving_before,
            'active_goal_ids_at_cancel':[identity for name,identity in sorted(active)],
            'native_canceled_goal_ids':[identity for name,identity in sorted(canceled)],
            'matching_native_canceled_goal_ids':[identity for name,identity in sorted(matching)],
            'matching_native_actions':[name for name,identity in sorted(matching)],
            'native_action_receipts':{name:{key:sorted(value) for key,value in action.items()} for name,action in actions.items()},
            'native_active_start_wall_time':native_start_wall,'motion_window_start_wall_time':motion_window_start,
            'max_true_origin_speed_during_native_action_before_cancel_m_s':max((s['car_speed'] for s in moving_samples),default=None),
            'original_task_id_readback':same_id,'continuous_true_stop':quiet.result(),'stop_includes_arm_qvel6_norm_below_0_05':True,
            'passed':moving_before and native and same_id and quiet.first_pass is not None}


def score(directory,marker_path,*,output_directory=None,augment=None):
    collection = collection_integrity(directory)
    if collection['required'] and not collection['passed']:
        result = {'passed': False, 'recording_integrity': collection,
            'reason': 'Collection incomplete or unconfirmed; physical acceptance was not evaluated',
            'physical_evaluation_performed': False, 'live_runtime_acceptance_claimed': False,
            'task_completion_passed': False, 'expected_safety_passed': False,
            'full_transport_acceptance_claimed': False}
        target = (output_directory or directory)/f'score-{time.time_ns()}.json'
        private_json(target, result)
        print(json.dumps({'score_file':str(target),'passed':False,'reason':result['reason']}))
        return result
    records=[]; first_physics=True
    with (directory/'observer.jsonl').open() as source_file:
        for line in source_file:
            record=json.loads(line)
            if record['topic']=='physics':
                if not first_physics:
                    identity=record['payload']['source']
                    record['payload']['source']={key:value for key,value in identity.items() if key!='manifest'}
                first_physics=False
            records.append(record)
    physics=records_by_topic(records,'physics')
    if not physics:
        result={'passed':False,'reason':'No independent physics samples','topics':topic_statistics(records)}
    else:
        audit=scene_audit(physics[0]['payload'])
        truth=records_by_topic(records,'truth');cargo=records_by_topic(records,'cargo');clocks=records_by_topic(records,'clock')
        samples=[];unmatched=[]
        for record in physics:
            item=physical_sample(record,truth,cargo,clocks,audit['tray_offset_from_base_footprint'],audit['half_extents'])
            if item is not None:samples.append(item)
            else:unmatched.append(record['source_stamp'])
        events=marker_events(records,marker_path)
        cancellations=[];full=[]
        for event in events:
            if event.get('kind')=='cancel_requested':
                later=[e['wall_time'] for e in events if e.get('kind')=='full_started' and e['wall_time']>event['wall_time']]
                cancellations.append(cancellation_score(records,samples,event,min(later) if later else None))
            if event.get('kind')=='full_started':
                later=[e['wall_time'] for e in events if e.get('kind')=='full_started' and e['wall_time']>event['wall_time']]
                end=min(later) if later else math.inf
                episode=[s for s in samples if event['wall_time']<=s['wall_time']<end]
                full.append({'task_id':event['task_id'],'started_wall_time':event['wall_time'],**full_score(episode,audit)})
        source_ids={r['payload']['source']['scene_sha256'] for r in physics}
        initial=json.loads((directory/'source-start.json').read_text())
        current=driver_audit()
        ended=json.loads((directory/'source-end.json').read_text())
        topic_stats=topic_statistics(records)
        physics_in_arrival_order=[r['payload'] for r in records if r['topic']=='physics']
        physics_resets=sum(b['physics_steps']<=a['physics_steps'] for a,b in zip(physics_in_arrival_order,physics_in_arrival_order[1:]))
        inventories=[r['payload'] for r in records if r['topic']=='publisher_inventory']
        publisher_ids={topic:{tuple(info['gid']) for inventory in inventories for info in inventory.get(topic,[])}
                       for topic in ('/cooperation/physics_state','/ground_truth/odom','/cooperation/cargo_pose','/clock')}
        integrity={'driver_source_unchanged':initial['sha256']==ended['sha256'],
                   'driver_no_runtime_physics_teleport':ended['no_runtime_physics_teleport'],
                   'driver_source_at_collection_start_sha256':initial['sha256'],
                   'driver_source_at_collection_end_sha256':ended['sha256'],
                   'current_driver_matches_collection_end':current['sha256']==ended['sha256'],
                   'scene_source_identity_count':len(source_ids),'scene_identities':sorted(source_ids),
                   'target_body_freejoint_identity':audit['target_is_world_child_with_freejoint'] and audit['target_mocap']=='false' and audit['equality_weld_count']==0,
                   'world_sha_matches':audit['sha_matches'],
                   'physics_step_resets_or_repeats':physics_resets,
                   'clock_repeated_or_backward_count':topic_stats.get('clock',{}).get('repeated_or_backward_source'),
                   'independent_source_publisher_identity_counts':{topic:len(ids) for topic,ids in publisher_ids.items()}}
        integrity['passed']=integrity['driver_source_unchanged'] and integrity['driver_no_runtime_physics_teleport'] and len(source_ids)==1 and integrity['target_body_freejoint_identity'] and audit['sha_matches'] and physics_resets==0 and integrity['clock_repeated_or_backward_count']==0 and all(len(ids)==1 for ids in publisher_ids.values())
        result={'passed':bool(full) and all(r['passed'] for r in cancellations+full) and integrity['passed'],
                'declared_marker_scope':{'cancel_attempt_count':len(cancellations),'full_attempt_count':len(full)},
                'cancellations':cancellations,'full_attempts':full,'source_integrity':integrity,'scene_audit':audit,
                'topics':topic_stats,'unmatched_physics_samples':len(unmatched),'unmatched_source_stamps':unmatched[:40],
                'marker_events':events,'http_state_is_scoring_authority':False,
                'car_motion_scoring_source':'independently received truth body origin position and yaw finite differences'}
    if augment is not None:
        result=augment(result,records,samples if physics else [],audit if physics else None,events if physics else [])
    collection = collection_integrity(directory)
    result['recording_integrity'] = collection
    if collection['required'] and not collection['passed']:
        result['passed'] = False
        for key in ('live_runtime_acceptance_claimed', 'task_completion_passed',
                    'expected_safety_passed', 'full_transport_acceptance_claimed'):
            if key in result:result[key] = False
    target=(output_directory or directory)/f'score-{time.time_ns()}.json';private_json(target,result)
    print(json.dumps({'score_file':str(target),'passed':result['passed'], 'full_attempts':[{'task_id':x['task_id'],'passed':x['passed']} for x in result.get('full_attempts',[])]},ensure_ascii=False))
    return result


def collection_integrity(directory):
    """New bounded collections cannot pass after truncation, IO failure or missing closeout."""
    try:
        start_path = directory/'source-start.json'
        started = json.loads(start_path.read_text()) if start_path.exists() else {}
        required = 'collection_policy' in started
        end_path = directory/'collection-end.json'
        ended = json.loads(end_path.read_text()) if end_path.exists() else {}
        recording = ended.get('recording')
        if not required:
            return {'required': False, 'passed': False, 'mode': 'legacy_budget_not_declared'}
        policy = started['collection_policy']
        if not isinstance(policy, dict) or policy.get('kind') != 'complete_bounded':
            return {'required': True, 'passed': False, 'reason': 'collection policy invalid'}
        budget = policy.get('max_record_bytes')
        bounded = isinstance(budget, int) and not isinstance(budget, bool) and 1024 <= budget <= 4*1024**3
        counts = [recording.get(key) for key in ('offered', 'written', 'bytes')] if isinstance(recording, dict) else []
        counts_valid = len(counts) == 3 and all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in counts)
        valid = (isinstance(recording, dict) and recording.get('capture_complete') is True
            and recording.get('closed') is True and recording.get('failed') is False
            and recording.get('truncated') is False and not ended.get('errors')
            and bounded and counts_valid and counts[0] == counts[1] and counts[2] <= budget
            and recording.get('bytes_uncertain') is False and recording.get('incomplete') == 0
            and recording.get('error') is None and recording.get('error_code') is None)
        return {'required': True, 'passed': bool(valid), 'recording': recording,
                'callback_errors': ended.get('errors'), 'mode': 'complete_bounded'}
    except (OSError, ValueError, TypeError, AttributeError):
        return {'required': True, 'passed': False, 'reason': 'collection metadata invalid or unavailable'}


def observe(args):
    from cooperation_evidence_recording import EvidenceRecorder
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile,ReliabilityPolicy,DurabilityPolicy
    from rosidl_runtime_py.convert import message_to_ordereddict
    from rosgraph_msgs.msg import Clock
    from nav_msgs.msg import Odometry,Path
    from geometry_msgs.msg import PoseStamped,PoseWithCovarianceStamped,TwistStamped
    from tf2_msgs.msg import TFMessage
    from std_msgs.msg import String,Bool
    from action_msgs.msg import GoalStatusArray
    from nav2_msgs.action import NavigateToPose,DockRobot
    from diagnostic_msgs.msg import DiagnosticArray
    from sensor_msgs.msg import Image,CameraInfo
    directory=args.output or BASE/f'run-{time.time_ns()}'
    directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    private_json(directory/'source-start.json',{**driver_audit(), 'collection_policy': {
        'kind': 'complete_bounded', 'duration_limit_s': args.duration, 'max_record_bytes': args.max_record_bytes,
        'manifest_storage': 'first full identity per content digest, subsequent references', 'sampling_reduced': False}})
    descriptor=os.open(directory/'observer.jsonl',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    output=EvidenceRecorder(os.fdopen(descriptor,'w',buffering=1,encoding='utf-8'), max_bytes=args.max_record_bytes)
    lock=threading.Lock();done=threading.Event();errors=[]
    def record(topic,payload):
        received=time.monotonic();wall=time.time()
        try:source=topic_stamp(topic,payload)
        except (KeyError,TypeError,ValueError):source=None
        value={'topic':topic,'received_monotonic':received,'received_wall_time':wall,
               'source_stamp':source,'payload':clean(payload)}
        with lock:
            if not output.record(value):
                done.set()
    rclpy.init(args=[]);node=Node('independent_cooperation_oracle')
    reliable=QoSProfile(depth=500,reliability=ReliabilityPolicy.RELIABLE)
    from rclpy.qos import qos_profile_sensor_data
    import copy
    clockq=copy.copy(qos_profile_sensor_data);clockq.depth=1
    observationq=copy.copy(qos_profile_sensor_data);observationq.depth=100
    statusq=QoSProfile(depth=100,durability=DurabilityPolicy.TRANSIENT_LOCAL,reliability=ReliabilityPolicy.RELIABLE)
    resetq=QoSProfile(depth=100,durability=DurabilityPolicy.VOLATILE,reliability=ReliabilityPolicy.RELIABLE)
    subscriptions=[]
    for topic,msg_type,name,qos in [('/cooperation/physics_state',String,'physics',clockq),('/ground_truth/odom',Odometry,'truth',reliable),
            ('/cooperation/cargo_pose',PoseStamped,'cargo',reliable),('/clock',Clock,'clock',clockq),
            ('/navigate_to_pose/_action/status',GoalStatusArray,'nav_status',statusq),
            ('/navigate_to_pose/_action/feedback',NavigateToPose.Impl.FeedbackMessage,'nav_feedback',reliable),
            ('/plan',Path,'plan',reliable),('/received_global_plan',Path,'received_global_plan',reliable),
            ('/lookahead_collision_arc',Path,'lookahead_collision_arc',reliable),
            ('/docking_trajectory',Path,'docking_trajectory',reliable),
            ('/dock_robot/_action/status',GoalStatusArray,'dock_status',statusq),
            ('/dock_robot/_action/feedback',DockRobot.Impl.FeedbackMessage,'dock_feedback',reliable),
            ('/detected_dock_pose',PoseStamped,'beacon',reliable),
            ('/cooperation/station_pose',PoseWithCovarianceStamped,'station_pose',observationq),
            ('/cooperation/station_detection',DiagnosticArray,'station_detection',observationq),
            ('/cooperation/station_admission',DiagnosticArray,'station_admission_event',reliable),
            ('/cooperation/perception_status',String,'perception_status',reliable),
            ('/cooperation/camera/camera_info',CameraInfo,'camera_info',observationq),
            ('/cooperation/camera/frame_metadata',DiagnosticArray,'camera_metadata',observationq),
            ('/cooperation/vision_quality',DiagnosticArray,'vision_quality',observationq),
            ('/initialpose',PoseWithCovarianceStamped,'initialpose',reliable),
            ('/cooperation/docking_guard',Bool,'guard_enable',statusq),
            ('/cooperation/reset_result',String,'reset_receipt',resetq),
            ('/cmd_vel',TwistStamped,'cmd_vel',reliable),
            ('/odom',Odometry,'encoder_odom',reliable),
            ('/amcl_pose',PoseWithCovarianceStamped,'amcl_pose',reliable),
            ('/tf',TFMessage,'tf',reliable)]:
        def callback(message,name=name):
            try:record(name,json.loads(message.data) if name in ('physics','reset_receipt','perception_status') else message_to_ordereddict(message))
            except Exception as error:
                errors.append(f'{name}: {type(error).__name__}: {error}');record('callback_error',{'topic':name,'error':errors[-1]})
        subscriptions.append(node.create_subscription(msg_type,topic,callback,qos))
    def image_callback(message):
        try:
            # Pixels remain in the camera producer's private image sequence.
            record('camera_image',{'header':message_to_ordereddict(message.header),
                'width':message.width,'height':message.height,'encoding':message.encoding,
                'step':message.step,'data_size':len(message.data),
                'data_sha256':hashlib.sha256(bytes(message.data)).hexdigest()})
        except Exception as error:
            errors.append(f'camera_image: {type(error).__name__}: {error}')
            record('callback_error',{'topic':'camera_image','error':errors[-1]})
    subscriptions.append(node.create_subscription(Image,'/cooperation/camera/image_raw',image_callback,clockq))
    def http_worker():
        while not done.is_set():
            try:
                with urllib.request.urlopen(args.api+'/state',timeout=.8) as response:
                    state=json.load(response)
                    record('http_state',state)
                    if isinstance(state.get('station_perception'),dict):
                        record('station_admission',{'native_consumption_ack_claimed':False,
                            'episode_id':state.get('episode_id'),**state['station_perception']})
                    if isinstance(state.get('frame'),dict):
                        record('camera_identity',state['frame'])
            except Exception as error:record('http_error',{'error':f'{type(error).__name__}: {error}'})
            done.wait(.5)
    worker=threading.Thread(target=http_worker,daemon=True);worker.start()
    def shutdown(signum,frame):done.set()
    signal.signal(signal.SIGINT,shutdown);signal.signal(signal.SIGTERM,shutdown)
    start=time.monotonic();last_markers=None;last_inventory=0.
    print(json.dumps({'ready_to_observe':True,'domain':args.domain,'output':str(directory),'marker_file':str(args.markers)},ensure_ascii=False),flush=True)
    try:
        while rclpy.ok() and not done.is_set() and time.monotonic()-start<args.duration:
            rclpy.spin_once(node,timeout_sec=.01)
            if args.markers.exists():
                content=args.markers.read_text()
                if content!=last_markers:
                    try:record('marker_file',json.loads(content));last_markers=content
                    except ValueError:pass
            if time.monotonic()-last_inventory>2.:
                inventory={topic:[{'node':info.node_name,'namespace':info.node_namespace,'gid':list(info.endpoint_gid)}
                                   for info in node.get_publishers_info_by_topic(topic)]
                           for topic in ('/cooperation/physics_state','/ground_truth/odom','/cooperation/cargo_pose','/clock',
                                         '/cmd_vel','/detected_dock_pose','/initialpose','/cooperation/docking_guard',
                                         '/cooperation/station_pose','/cooperation/station_detection','/cooperation/perception_status',
                                         '/cooperation/station_admission',
                                         '/cooperation/camera/image_raw','/cooperation/camera/camera_info',
                                         '/cooperation/camera/frame_metadata','/cooperation/vision_quality')}
                record('publisher_inventory',inventory);last_inventory=time.monotonic()
    finally:
        done.set();worker.join(timeout=2.)
        if worker.is_alive():errors.append('HTTP observer worker did not stop before closeout')
        node.destroy_node();rclpy.shutdown()
        with lock:output.close()
        private_json(directory/'source-end.json',driver_audit())
        private_json(directory/'collection-end.json',{'errors':errors,'wall_duration_s':time.monotonic()-start,
            'finished_wall_time':time.time(),'recording':output.snapshot()})
        score(directory,args.markers)


# Live observation is started only through cooperation_oracle.py.
