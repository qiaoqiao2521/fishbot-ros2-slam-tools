"""Named Oracle fixtures use independent pose streams, never ROS or MuJoCo."""
import copy
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.tests.test_cooperation_oracle import oracle, base, audit, delivery_fixture


def fixture():
    records, initial, _, events = delivery_fixture()
    binding = {'cargo_id':'cargo_2','pickup_arm_id':'load','unload_station_id':'line_b'}
    manifest = {'business_entities': {
        'arms': {'load': {'pad_geoms':['pad_gripper','pad_moving_jaw'],'home_qpos6':[0.]*6},
                 'unload_b': {'pad_geoms':['unload_b__pad_gripper','unload_b__pad_moving_jaw'],
                    'home_qpos6':[0.,0.,0.,0.,0.,.5], 'station_position_m':[.6,0.,.16],
                    'station_yaw_rad':math.pi/2}},
        'cargo': {'cargo_1':{'body':'grasp_target'}, 'cargo_2':{'body':'cargo_2__grasp_target'}},
        'configuration':{'budgets_wall_s':{'load_and_delivery':360,'unload':180}},
        'unload_stations': {'line_b': {'arm_id':'unload_b','delivery_pose':{'x':.6,'y':0.,'yaw':0.},
            'shelf_xy_in_station_m':[.04,-.02],
            'cargo_shelf_slots': {'cargo_2':{'center_xy_m':[.04,-.02],'half_size_xy_m':[.018,.018]}}}}}}
    events[0]['business_delivery']=copy.deepcopy(binding)
    events[1]['wall_time']=118.5
    events.append({'kind':'cleanup_checked','task_id':'task','wall_time':118.5})
    for row in records:
        if row['topic']=='http_state':row['payload']['task']['business_delivery']=copy.deepcopy(binding)
    def contact(force):return {'contact_count':1,'normal_force_n':force}
    def pose(point, quat):
        return {'position':dict(zip(('x','y','z'),point)), 'orientation':dict(zip(('w','x','y','z'),quat))}
    for index in range(926):
        t=round(index*.02, 8);x=min(.6,max(0.,(t-5.)*.1));moving=5.<=t<11.
        load_lift=1.<=t<2.5;unload_lift=13.<=t<14.3
        xyz=[x,0.,.20 if load_lift else .17]
        quat=[1.,0.,0.,0.]
        if 13.<=t<15.:xyz=[.62,.04,.21]
        elif t>=15.:xyz=[.62,.04,.168];quat=[math.sqrt(.5),0.,0.,math.sqrt(.5)]
        supports=({'pickup':contact(.0981)} if t<2.5 else
                  {'tray':contact(.0981)} if t<13. else {'line_b':contact(.0981)} if t>=15. else {})
        pads=({'load':{'pad_gripper':contact(.04),'pad_moving_jaw':contact(.04)}} if load_lift else
              {'unload_b':{'unload_b__pad_gripper':contact(.04),
                            'unload_b__pad_moving_jaw':contact(.04)}} if unload_lift else {})
        cargo={'position':xyz,'quaternion_wxyz':quat,'velocity_world_angular_linear':[0.]*6,
               'contacts':{'supports':supports,'pads':pads,'other_cargo':{}}}
        primary={'position':[0.,0.,.17],'quaternion_wxyz':[1.,0.,0.,0.],
                 'velocity_world_angular_linear':[0.]*6,
                 'contacts':{'supports':{'pickup':contact(.0981)},'pads':{},'other_cargo':{}}}
        raw={'stamp':t,'finite':True,'episode_id':'episode','world_session_id':'world',
             'source':{'episode_id':'episode', **({'manifest':manifest} if index==0 else {})},
             'q6':[9.]*6,'qvel6':[0.]*6,'car_hold':not moving,
             'car':{'position':[x,0.,0.]},
             'cargo':primary,'tray':{'position':[x,0.,.16], 'quaternion_wxyz':[1.,0.,0.,0.],
                'velocity_world_angular_linear':[0.]*6},
             'arm_forbidden_contact_total':0,'car_forbidden_contact_total':0,
             'docking_guard':{'enabled':t<.8,'tripped':False},
             'business_entities':{'arms':{
                'load':{'qpos6':[.1]*6 if t<3.5 else [0.]*6,'qvel6':[0.]*6},
                'unload_b':{'qpos6':[.1]*5+[.015] if 13.<=t<15.2 else [0.,0.,0.,0.,0.,.5],
                             'qvel6':[0.]*6}},'cargo':{'cargo_1':primary,'cargo_2':cargo}}}
        records.append({'topic':'physics','source_stamp':t,'received_wall_time':100.+t,'payload':raw})
        records.append({'topic':'clock','source_stamp':t,'received_wall_time':100.+t,'payload':{'clock':{}}})
        records.append({'topic':'truth','source_stamp':t,'received_wall_time':100.+t,
                        'payload':{'pose':{'pose':pose([x,0.,0.],[1.,0.,0.,0.])},
                                   'twist':{'twist':{'linear':dict(x=0.,y=0.,z=0.),'angular':dict(x=0.,y=0.,z=0.)}}}})
        for name,p,q in [('cargo:cargo_2',xyz,quat),('cargo',[0.,0.,.17],[1.,0.,0.,0.])]:
            records.append({'topic':name,'source_stamp':t,'received_wall_time':100.+t,'payload':{'pose':pose(p,q)}})
    last=copy.deepcopy(next(r for r in records if r['topic']=='http_state' and r['received_wall_time']==112.8))
    last['received_wall_time']=118.5
    last['payload'].update(business_inventory={'world_id':'world','episode_id':'episode',
        'cargo':{'cargo_2':{'state':'delivered','task_id':'task'}}})
    last['payload']['task'].update(status='succeeded',unload_receipt={'cargo_id':'cargo_2','unload_station_id':'line_b',
        'episode_id':'episode','world_session_id':'world','source_stamp':18.5})
    records.append(last)
    return records,events,manifest,binding


def score(records, events):
    scene={**audit(),'tray_offset_from_base_footprint':[0.,0.,.16],'half_extents':[.009,.009,.008]}
    with patch.object(base,'scene_audit',return_value=scene):
        return oracle.business_delivery_checks(records,events,scene)


class BusinessOracleTests(unittest.TestCase):
    def test_second_cargo_uses_its_independent_pose_and_physical_unload(self):
        records,events,manifest,binding=fixture();before=copy.deepcopy(records)
        result=score(records,events)
        self.assertTrue(result['passed'],result)
        attempt=result['attempts'][0]
        self.assertTrue(attempt['original_k_load_and_transport']['passed'])
        self.assertTrue(attempt['physical_unload_lift']['passed'])
        self.assertTrue(attempt['shelf_home_rest_through_cleanup']['passed'])
        self.assertTrue(attempt['inventory_and_receipt_bound'])
        self.assertFalse(attempt['inventory_receipt_is_physical_proof'])
        self.assertEqual(records,before)

    def test_missing_secondary_pose_does_not_reuse_primary_success(self):
        records,events,_,_=fixture()
        records=[r for r in records if r['topic']!='cargo:cargo_2']
        result=score(records,events)
        self.assertFalse(result['passed'])
        self.assertTrue(result['attempts'][0]['missing_independent_samples_preview'])

    def test_failed_arrival_retains_observed_samples_and_elapsed_load_budget(self):
        records,events,_,_=fixture()
        records=[r for r in records if r['received_wall_time'] <= 106.]
        for event in events:
            if event['kind'] in ('full_finished','cleanup_checked'):
                event['wall_time']=461.
        result=score(records,events)
        attempt=result['attempts'][0]
        self.assertFalse(result['passed'])
        evidence=attempt['phase_evidence']
        self.assertGreater(evidence['independent_selected_samples'],0)
        self.assertEqual(evidence['load_and_transport_prefix_samples'],0)
        self.assertGreater(evidence['pickup_and_transport_observed']['scored_samples'],0)
        self.assertIn('arrival_not_verified',evidence['rejection_reasons'])
        self.assertLess(attempt['missing_independent_samples'],evidence['independent_selected_samples'])
        self.assertIn('load_and_delivery_budget_exceeded',evidence['rejection_reasons'])
        self.assertFalse(attempt['wall_budget']['passed'])
        self.assertFalse(attempt['wall_budget']['load_and_delivery_complete'])
        self.assertEqual(attempt['wall_budget']['load_and_delivery_wall_s'],361.)

    def test_raw_cargo_pose_cannot_override_independently_received_pose(self):
        records,events,_,_=fixture()
        for row in records:
            if row['topic']=='cargo:cargo_2' and row['source_stamp']>15.:
                row['payload']['pose']['position']['x']+=.02
        self.assertFalse(score(records,events)['passed'])

    def test_named_endpoint_identity_rejects_second_source_and_wrong_owner(self):
        for kind in ('valid','second_source','wrong_owner','empty'):
            records,events,_,_=fixture()
            primary={'node':'physics','namespace':'/','gid':[1,2,3]}
            named={'node':'physics','namespace':'/','gid':[4,5,6]}
            entries=[named]
            if kind=='second_source':entries.append({**named,'gid':[7,8,9]})
            elif kind=='wrong_owner':named['node']='another_process'
            elif kind=='empty':entries=[]
            records.append({'topic':'publisher_inventory','received_wall_time':102.,
                'payload':{'/cooperation/physics_state':[primary],
                           '/cooperation/cargo/cargo_2/pose':entries}})
            with self.subTest(kind=kind):
                result=score(records,events);identity=result['attempts'][0]['named_pose_publisher_identity']
                self.assertTrue(identity['required'])
                self.assertEqual(result['passed'],kind=='valid')
                self.assertEqual(identity['passed'],kind=='valid')

    def test_historical_missing_endpoint_inventory_is_not_claimed_verified(self):
        records,events,_,_=fixture()
        result=score(records,events)
        self.assertTrue(result['passed'])
        self.assertFalse(result['named_pose_publisher_identity_checked'])
        identity=result['attempts'][0]['named_pose_publisher_identity']
        self.assertFalse(identity['required'])
        self.assertEqual(identity['status'],'historical_inventory_unavailable')

    def test_web_inventory_and_success_do_not_substitute_for_unload_lift(self):
        records,events,_,_=fixture()
        for row in records:
            if row['topic']=='physics' and row['source_stamp']>=13.:
                row['payload']['business_entities']['cargo']['cargo_2']['contacts']['pads']={}
        self.assertFalse(score(records,events)['passed'])

    def test_lost_final_support_rest_or_arm_home_cannot_use_an_earlier_dwell(self):
        for kind in ('support','arm','other_cargo_motion','held_pad','world_motion'):
            records,events,_,_=fixture()
            for row in records:
                if row['topic']!='physics' or row['source_stamp']<18.3:continue
                raw=row['payload'];cargo=raw['business_entities']['cargo']['cargo_2']
                if kind=='support':cargo['contacts']['supports']={}
                elif kind=='arm':raw['business_entities']['arms']['unload_b']['qpos6'][0]=.02
                elif kind=='other_cargo_motion':raw['business_entities']['cargo']['cargo_1']['velocity_world_angular_linear'][3]=.03
                elif kind=='held_pad':cargo['contacts']['pads']={'load':{'pad_gripper':{'contact_count':1,'normal_force_n':.02}}}
                else:cargo['velocity_world_angular_linear'][3]=.002
            with self.subTest(kind=kind):self.assertFalse(score(records,events)['passed'])

    def test_slot_checks_use_full_rotated_corners_and_station_yaw(self):
        records,events,_,_=fixture()
        # Rotate 45 degrees relative to the 90-degree station and shift 6mm
        # along station local x; center fits in its slot but corners do not.
        q=[math.cos(3*math.pi/8),0.,0.,math.sin(3*math.pi/8)]
        for row in records:
            if row.get('source_stamp',0)<15.:continue
            if row['topic']=='physics':
                cargo=row['payload']['business_entities']['cargo']['cargo_2']
                cargo['position'][1]+=.006;cargo['quaternion_wxyz']=q[:]
            elif row['topic']=='cargo:cargo_2':
                row['payload']['pose']['position']['y']+=.006
                row['payload']['pose']['orientation']=dict(zip(('w','x','y','z'),q))
        result=score(records,events)
        self.assertFalse(result['passed'])
        self.assertFalse(result['attempts'][0]['last_shelf_predicates']['full_shelf_and_slot_footprint'])

    def test_inventory_wrong_task_and_stale_receipt_are_only_corroborating_failures(self):
        for kind in ('wrong_task','stale_receipt','wrong_world','wrong_cargo'):
            records,events,_,_=fixture();state=records[-1]['payload']
            if kind=='wrong_task':state['business_inventory']['cargo']['cargo_2']['task_id']='other'
            elif kind=='stale_receipt':state['task']['unload_receipt']['source_stamp']=12.
            elif kind=='wrong_world':state['business_inventory']['world_id']='another'
            else:state['task']['unload_receipt']['cargo_id']='cargo_1'
            with self.subTest(kind=kind):
                result=score(records,events)
                self.assertFalse(result['passed'])
                self.assertTrue(result['attempts'][0]['shelf_home_rest_through_cleanup']['passed'])

    def test_missing_cleanup_proof_and_named_binding_changes_fail(self):
        records,events,_,_=fixture()
        self.assertFalse(score(records,[e for e in events if e['kind']!='cleanup_checked'])['passed'])
        records[-1]['payload']['task']['business_delivery']['cargo_id']='cargo_1'
        self.assertFalse(score(records,events)['passed'])

    def test_declared_load_budget_cannot_replace_original_360_seconds(self):
        records,events,manifest,_=fixture()
        manifest['business_entities']['configuration']['budgets_wall_s']['load_and_delivery']=540
        result=score(records,events)
        self.assertFalse(result['passed'])
        self.assertFalse(result['attempts'][0]['wall_budget']['passed'])

    def test_named_scoring_wires_into_overall_acceptance_without_primary_aliasing(self):
        records,events,_,_=fixture()
        _,primary,primary_attempt,_=delivery_fixture()
        scene={**audit(),'tray_offset_from_base_footprint':[0.,0.,.16],'half_extents':[.009,.009,.008]}
        settings=SimpleNamespace(scope='transport',expected_outcome='success',markers=Path('/unused'),
            expected_episode='episode',reset_receipt=None,allow_initial_episode=True,
            score_only=Path('/unused'),output=Path('/unused'))
        value={'passed':False,'full_attempts':[{**primary_attempt,'passed':False}],
               'source_integrity':{'passed':True},'cancellations':[]}
        with patch.object(base,'scene_audit',return_value=scene),patch.object(oracle,'options',settings), \
                patch.object(oracle,'extra_checks',return_value={'passed':True,'windows':[]}), \
                patch.object(oracle,'transport_checks',wraps=oracle.transport_checks), \
                patch.object(oracle,'observation_metrics',return_value={}), \
                patch.object(oracle,'fault_checks',return_value={'passed':True}), \
                patch.object(oracle,'plant_guard_telemetry',return_value={}):
            result=oracle.augment_score(value,records,primary,scene,events)
        self.assertTrue(result['passed'])
        self.assertFalse(result['original_k_oracle_passed'])
        self.assertTrue(result['full_attempts'][0]['passed'])
        self.assertEqual(result['full_attempts'][0]['business_delivery']['cargo_id'],'cargo_2')

    def test_legacy_tasks_do_not_activate_named_scoring(self):
        records,_,_,events=delivery_fixture()
        self.assertEqual(oracle.business_delivery_checks(records,events,audit()),
                         {'required':False,'passed':True,'attempts':[]})

    def test_observer_adds_only_read_subscriptions_and_keeps_existing_callback(self):
        calls=[];recorded=[]
        class Node:
            def create_subscription(self,*args,**kwargs):calls.append(args);return len(calls)
        observer=oracle.named_observer_node(Node,['cargo_1','cargo_2'])()
        def callback(message,name='cargo'):recorded.append((name,message))
        observer.create_subscription(object,'/cooperation/cargo_pose',callback,10)
        self.assertEqual([call[1] for call in calls],['/cooperation/cargo_pose',
            '/cooperation/cargo/cargo_1/pose','/cooperation/cargo/cargo_2/pose'])
        calls[-1][2]('measured-pose')
        self.assertEqual(recorded,[('cargo:cargo_2','measured-pose')])
        self.assertEqual(oracle.topic_stamp('cargo:cargo_2',{'header':{'stamp':{'sec':1,'nanosec':500000000}}}),1.5)
        with self.assertRaises(ValueError):oracle.cargo_topic('../cargo')


if __name__=='__main__':unittest.main()
