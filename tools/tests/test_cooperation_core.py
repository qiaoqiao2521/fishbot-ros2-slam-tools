import ast
import copy
import importlib.util
import json
import math
from pathlib import Path
import threading
import time
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
import uuid
import numpy as np

spec=importlib.util.spec_from_file_location('core',Path(__file__).parents[1]/'cooperation_core.py')
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)


class CooperationEvidenceTests(unittest.TestCase):
    def test_no_duration_from_duplicate_or_missing_source_samples(self):
        gate=core.ContinuousEvidence(.3,.12)
        self.assertFalse(gate.update(1.,True))
        for _ in range(30):self.assertFalse(gate.update(1.,True))
        self.assertFalse(gate.update(1.5,True))
        self.assertFalse(gate.update(1.6,True))
        self.assertFalse(gate.update(1.7,True))
        self.assertTrue(gate.update(1.81,True))

    def test_failed_or_regressed_measurement_breaks_continuity(self):
        gate=core.ContinuousEvidence(.2)
        for stamp,valid in [(1.,True),(1.1,True),(1.2,False),(1.3,True),(1.4,True),(1.2,True)]:
            self.assertFalse(gate.update(stamp,valid))
        self.assertFalse(gate.update(1.3,True))
        self.assertTrue(gate.update(1.41,True))

    def test_expired_future_or_invalid_command_is_not_admitted(self):
        task=str(uuid.uuid4());self.assertEqual(core.request_identity({'task_id':task,'issued_at':10},now=10),task)
        for issued in [True,float('nan'),3,13]:
            with self.assertRaises(core.Rejected):core.request_identity({'task_id':task,'issued_at':issued},now=10)
        with self.assertRaises(core.Rejected):core.request_identity({'task_id':'not-a-task','issued_at':10},now=10)

    def test_settled_cargo_requires_support_released_tips_and_full_extent(self):
        raw={'cargo':{'position_relative_tray':[0,0,.01],'quaternion_wxyz':[1,0,0,0],'velocity_relative_tray':[0,0,0]},
             'tray':{'rotation_world':[[1,0,0],[0,1,0],[0,0,1]]},'cargo_tray_floor_contact':True,
             'finger_normal_forces_n':{'left':0.,'right':0.}}
        self.assertTrue(core.settled_cargo(raw))
        raw['cargo']['position_relative_tray'][0]=.05;self.assertFalse(core.settled_cargo(raw))
        raw['cargo']['position_relative_tray'][0]=0.;raw['cargo_tray_floor_contact']=False;self.assertFalse(core.settled_cargo(raw))
        raw['cargo_tray_floor_contact']=True;raw['finger_normal_forces_n']['left']=.03;self.assertFalse(core.settled_cargo(raw))
        raw['finger_normal_forces_n']['left']=0.;raw['cargo']['velocity_relative_tray'][0]=.003;self.assertFalse(core.settled_cargo(raw))


def measurement():
    car={'position':[0.,0.,0.], 'quaternion_wxyz':[1.,0.,0.,0.], 'velocity_world_angular_linear':[0.]*6,
         'speed':0.,'yaw_rate':0.,'hold':True}
    cargo={'position':[.24,-.13,.03],'quaternion_wxyz':[1.,0.,0.,0.],'velocity_world_angular_linear':[0.]*6,
           'position_relative_tray':[0.,0.,.01],'velocity_relative_tray':[0.]*3}
    tray={'position':[0.]*3,'quaternion_wxyz':[1.,0.,0.,0.],'velocity_world_angular_linear':[0.]*6,
          'rotation_world':[[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]],'floor_top_world':[0.]*3}
    raw={'schema':1,'finite':True,'stamp':10.,'time_s':10.,'ctrl':[0.]*8,'wall_time':time.time(),'sequence':1,'physics_steps':5000,'physics_hz':500,
         'q6':[0.]*6,'qvel6':[0.]*6,'qpos22':[0.]*6+cargo['position']+cargo['quaternion_wxyz']+car['position']+car['quaternion_wxyz']+[0.,0.],
         'qvel20':[0.]*20,'arm_reference_q6':[0.]*6,'car_hold':True,'car':car,'cargo':cargo,'tray':tray,
         'source':{'scene_sha256':'a'*64,'manifest_sha256':'b'*64},
         'finger_normal_forces_n':{'pad_gripper':0.,'pad_moving_jaw':0.},
         'finger_peak_normal_forces_n':{'pad_gripper':0.,'pad_moving_jaw':0.},
         'cargo_tray_floor_contact':True,'cargo_tray_floor_contacts':1,'cargo_tray_floor_normal_force_n':.1}
    for body in ('car','arm'):
        raw.update({f'{body}_forbidden_contacts':[],f'{body}_forbidden_contact_count':0,
                    f'{body}_forbidden_contact_total':0,f'{body}_forbidden_contact_steps':0})
    return raw


class PhysicsAdmissionTests(unittest.TestCase):
    def test_retention_rejects_rotated_corner_outside_despite_center_inside(self):
        raw=measurement()
        raw['cargo']['position_relative_tray'][0]=.047
        raw['cargo']['quaternion_wxyz']=[math.cos(math.pi/8),0.,0.,math.sin(math.pi/8)]
        # Original center/height/support gates pass, but the diagonal corner is
        # .047 + .009*sqrt(2) = .059728m, beyond the unchanged .058m boundary.
        self.assertLessEqual(abs(raw['cargo']['position_relative_tray'][0]),.047)
        self.assertTrue(raw['cargo_tray_floor_contact'])
        self.assertGreater(.047+.009*math.sqrt(2),.058)
        self.assertFalse(core.cargo_retained(raw))
        self.assertFalse(core.settled_cargo(raw))
        raw['cargo']['position_relative_tray'][0]=.04
        self.assertTrue(core.cargo_retained(raw))
        self.assertTrue(core.settled_cargo(raw))

    def test_shared_cargo_rotation_tracks_tray_frame_and_keeps_original_center_limit(self):
        raw=measurement();raw['cargo']['position_relative_tray'][0]=.047
        q=[math.cos(math.pi/8),0.,0.,math.sin(math.pi/8)]
        raw['cargo']['quaternion_wxyz']=q
        c,s=math.cos(math.pi/4),math.sin(math.pi/4)
        raw['tray']['rotation_world']=[[c,-s,0.],[s,c,0.],[0.,0.,1.]]
        self.assertTrue(core.cargo_retained(raw))  # Same world yaw, relative box is aligned.
        raw['cargo']['position_relative_tray'][0]=.0471
        self.assertTrue(core.cargo_footprint_inside(raw))
        self.assertFalse(core.cargo_retained(raw))  # Preserve the original .047 center gate.

    def test_transport_handoff_requires_hold_stop_home_and_arm_quiet_together(self):
        raw=measurement();home=[0.]*6
        self.assertTrue(core.transport_handoff_ready(raw,home))
        changes=[lambda r:r.update(car_hold=False),lambda r:r['car'].update(speed=.01),
                 lambda r:r['car'].update(yaw_rate=.01),lambda r:r['q6'].__setitem__(5,.02),
                 lambda r:r['qvel6'].__setitem__(2,.05),lambda r:r.update(cargo_tray_floor_contact=False)]
        for change in changes:
            value=copy.deepcopy(raw);change(value)
            with self.subTest(change=change):self.assertFalse(core.transport_handoff_ready(value,home))
        raw['qvel6'][:2]=[.03,.04]
        self.assertFalse(core.arm_home_quiet(raw,home))  # Norm, not per-joint maximum.

    def test_capture_requires_correct_side_alignment_and_heading_in_dock_frame(self):
        dock=[-1.8,-1.8,0.]
        self.assertTrue(core.within_station_capture({'x':-1.1,'y':-1.8,'yaw':0.},dock))
        for pose in ({'x':-2.5,'y':-1.8,'yaw':0.}, {'x':-1.1,'y':-1.6,'yaw':0.},
                     {'x':-1.1,'y':-1.8,'yaw':math.pi}, {'x':-.8,'y':-1.8,'yaw':0.}):
            self.assertFalse(core.within_station_capture(pose,dock))
        self.assertTrue(core.within_station_capture({'x':0.,'y':.7,'yaw':math.pi/2},[0.,0.,math.pi/2]))
    def test_station_observation_recovers_robot_pose_in_both_frames(self):
        self.assertEqual(core.station_robot_pose([-.7,0.,math.pi],[0.,0.,math.pi]),
                         {'x':.7,'y':0.,'yaw':0.})
        pose=core.station_robot_pose([.7,0.,math.pi/2],[0.,0.,math.pi])
        self.assertAlmostEqual(pose['x'],0.)
        self.assertAlmostEqual(pose['y'],-.7)
        self.assertAlmostEqual(pose['yaw'],math.pi/2)
        with self.assertRaises(ValueError):core.station_robot_pose([float('nan'),0.,0.],[0.,0.,0.])
    def test_forward_first_contact_is_not_hidden_by_independent_step_totals(self):
        raw=measurement()
        raw['car_forbidden_contacts']=[{'geom1':'car','geom2':'bench','normal_force_n':.01,'distance_m':-.0001}]
        raw['car_forbidden_contact_count']=1
        self.assertIs(core.validate_physics(raw,'a'*64,'b'*64),raw)
        self.assertEqual(raw['car_forbidden_contact_count'],1)
        self.assertEqual(raw['car_forbidden_contact_total'],0)
        raw['ctrl'][0]=float('nan')
        with self.assertRaises(ValueError):core.validate_physics(raw,'a'*64,'b'*64)
        raw['ctrl'][0]=0.;raw['time_s']=11.
        with self.assertRaises(ValueError):core.validate_physics(raw,'a'*64,'b'*64)

    def test_actual_adapter_schema_is_bound_to_compiled_scene_and_complete_finite_arrays(self):
        raw=measurement();self.assertIs(core.validate_physics(raw,'a'*64,'b'*64),raw)
        corruptions=[lambda r:r['source'].update(scene_sha256='c'*64),
                     lambda r:r['source'].update(manifest_sha256='c'*64),
                     lambda r:r.pop('arm_forbidden_contact_total'),
                     lambda r:r['qpos22'].pop(),lambda r:r['qvel20'].__setitem__(1,float('nan')),
                     lambda r:r['car']['position'].__setitem__(0,float('inf')),
                     lambda r:r['cargo'].update(quaternion_wxyz=[0.,0.,0.,0.]),
                     lambda r:r['finger_normal_forces_n'].pop('pad_gripper'),
                     lambda r:r['tray']['rotation_world'][1].__setitem__(1,2.),
                     lambda r:r['car'].update(speed=-1.),lambda r:r.update(finite=1)]
        for change in corruptions:
            value=copy.deepcopy(raw);change(value)
            with self.subTest(change=change),self.assertRaises((ValueError,KeyError,TypeError)):
                core.validate_physics(value,'a'*64,'b'*64)


class ControlledFuture:
    def __init__(self,value=None,done=False):self.value=value;self.ready=done;self.callbacks=[]
    def done(self):return self.ready
    def result(self):return self.value
    def add_done_callback(self,callback):
        self.callbacks.append(callback)
        if self.ready:callback(self)
    def resolve(self,value):
        self.value=value;self.ready=True
        for callback in list(self.callbacks):callback(self)


class ControlledHandle:
    accepted=True
    def __init__(self):self.cancels=0;self.result_future=ControlledFuture();self.before_result=None
    def get_result_async(self):
        if self.before_result:self.before_result()
        return self.result_future
    def cancel_goal_async(self):self.cancels+=1;return ControlledFuture(NS(return_code=0),True)


class BridgeRaceTests(unittest.TestCase):
    """Execute current Bridge methods, with native futures and source samples controlled."""
    def setUp(self):
        parsed=ast.parse((Path(__file__).parents[1]/'cooperation_bridge.py').read_text())
        original=next(node for node in ast.walk(parsed) if isinstance(node,ast.ClassDef) and node.name=='Bridge')
        methods=[copy.deepcopy(node) for node in original.body if isinstance(node,ast.FunctionDef) and node.name!='__init__']
        extracted=ast.Module(body=[ast.ClassDef(name='BridgeProbe',bases=[],keywords=[],body=methods,decorator_list=[])],type_ignores=[])
        self.clock=100.;self.epoch=time.time();self.on_sleep=None;self.threads=[]
        test=self
        class Thread:
            def __init__(self,**kwargs):self.kwargs=kwargs
            def start(self):test.threads.append(self.kwargs)
            def is_alive(self):return False
        self.namespace={**vars(core),'copy':copy,'json':json,'math':math,
            'np':np,
            'time':NS(monotonic=lambda:self.clock,time=lambda:self.epoch+self.clock-100.,sleep=self.sleep),
            'threading':NS(Thread=Thread), 'String':lambda **kw:NS(**kw), 'ClearEntireCostmap':NS(Request=lambda:NS()),'manifest':{'station_offset':[0.,0.,0.],'dock_pose':[0.,0.,0.],
                'staging_pose':[.7,0.,0.],'native_dock_pose':[0.,0.,math.pi],
                'native_docking':{'dock_id':'so101_station'},
                'arm_home_qpos6':[0.]*6,'arm_joint_names':['joint']*6},
            'scene_sha':'a'*64,'manifest_sha':'b'*64,
            'args':NS(frame_dir=Path('/nonexistent/cooperation-race-test'),domain=114),
            'Bool':lambda **kwargs:NS(**kwargs),'JointState':lambda:NS(header=NS()),
            'Canceled':type('Canceled',(RuntimeError,),{}),'NavigateToPose':NS(Goal=lambda:NS()),
            'DockRobot':NS(Goal=lambda:NS()),
            'PoseWithCovarianceStamped':lambda:NS(header=NS(),pose=NS(
                pose=NS(position=NS(),orientation=NS()),covariance=[0.]*36)),
            'PoseStamped':lambda:NS(header=NS(),pose=NS(position=NS(),orientation=NS()))}
        exec(compile(ast.fix_missing_locations(extracted),'<current-cooperation-bridge>','exec'),self.namespace)
        self.bridge=self.namespace['BridgeProbe']();p=self.bridge
        p.episode_id=None;p.history=[];p.task_worker=None;p.reset_worker=None;p.reset_clearers=[];p.reset_records={};p.reset_acks={};p.reset_runtime={};p.last_reset_id=None
        p.lock=threading.RLock();p.worker=threading.local();p.execution_token=('task-a',1);p.worker.token=p.execution_token
        p.task_epoch=1;p.dispatch_epoch=0;p.dispatches=[];p.cancel_event=threading.Event();p.abort_event=threading.Event()
        p.abort_reason=None;p.observation_error=None;p.last_ref=[0.]*6;p.raw=measurement();p.received=self.clock;p.wall_deadline=1000.
        p.task={'id':'task-a','status':'running','stage':'submitted'};p.events=[];p.known_ids=set();p.holds=[];p.refs=[]
        p.dock_guard_active=False;p.guard_requests=[]
        p.raw['docking_guard']={'enabled':False,'tripped':False,'along_m':.7,'margin_m':.01,
            'dock_pose':[0.,0.,0.],'frame':'world','body_origin':'base_footprint'}
        def guard_publish(message):
            p.guard_requests.append(message.data);p.raw['docking_guard']['enabled']=message.data
        p.dock_guard_pub=NS(publish=guard_publish)
        p.hold_pub=NS(publish=lambda msg:p.holds.append(msg.data));p.arm_pub=NS(publish=lambda msg:p.refs.append(msg.position))
        p.persist=lambda:None;p.get_logger=lambda:NS(warning=lambda message:None)
        p.get_clock=lambda:NS(now=lambda:NS(nanoseconds=int(p.raw['stamp']*1e9) if p.raw else 0,to_msg=lambda:NS()))
        p.localized=lambda:{'x':0.,'y':0.,'yaw':0.}
        p.nav=NS(server_is_ready=lambda:True)
        p.docking=NS(server_is_ready=lambda:True)
        p.beacon=None;p.last_station_pose_stamp=-math.inf;p.poses=[]
        p.pose_pub=NS(publish=lambda message:p.poses.append(message))
        p.get_publishers_info_by_topic=lambda name:[NS(node_name='cooperation_physics')]

    def sleep(self,seconds):
        self.clock+=seconds
        if self.bridge.raw is not None:
            self.bridge.raw['stamp']+=seconds*getattr(self,'source_rate',1.)
            self.bridge.raw['sequence']+=1;self.bridge.received=self.clock
            self.bridge.raw['time_s']=self.bridge.raw['stamp']
        if self.on_sleep:self.on_sleep()

    def goal(self):return {'x':0.,'y':0.,'yaw':0.}

    def reset_probe(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        p=self.bridge;p.history_dir=Path(folder.name)
        p.episode_id=str(uuid.uuid4());p.raw['episode_id']=p.episode_id;p.raw['source']['episode_id']=p.episode_id
        p.task.update(status='succeeded');p.raw['car_hold']=True;p.raw['car']['hold']=True
        p.raw['cargo']['velocity_world_angular_linear']=[0.]*6
        p.localized=lambda:core.car_pose(p.raw)
        p.reset_requests=[];p.clear_requests=[]
        p.reset_pub=NS(publish=lambda value:p.reset_requests.append(json.loads(value.data)))
        def clear(value):
            p.clear_requests.append(value)
            return ControlledFuture(NS(),True)
        p.reset_clearers=[NS(service_is_ready=lambda:True,call_async=clear)]
        return p,{'request_id':str(uuid.uuid4()),'episode_id':p.episode_id,'issued_at':self.epoch}

    def reset_ack(self,p,request,status='succeeded'):
        episode=str(uuid.uuid4()) if status=='succeeded' else None
        result={'request_id':request['request_id'],'episode_id':request['episode_id'],'status':status,
                'new_episode_id':episode,'reset_stamp':p.raw['stamp'] if episode else None,'message':'new round' if episode else 'busy'}
        p.observe_reset(NS(data=json.dumps(result)))
        if episode:
            p.raw['episode_id']=episode;p.raw['source']['episode_id']=episode
        return result

    def test_reset_rejects_running_unknown_and_live_native_action_without_mutation(self):
        p,body=self.reset_probe()
        for status in ('running','canceling','unknown'):
            p.task['status']=status
            with self.assertRaises(core.Rejected):p.reset_episode(body)
        p.task['status']='succeeded';handle=ControlledHandle()
        p.dispatches=[{'received':True,'handle':handle,'result':handle.result_future,'error':None}]
        with self.assertRaises(core.Rejected):p.reset_episode(body)
        self.assertEqual(p.reset_requests,[]);self.assertEqual(p.history,[])

    def test_reset_preserves_history_then_confirms_new_episode_and_never_repeats_same_request(self):
        p,body=self.reset_probe();old=p.episode_id;old_task=copy.deepcopy(p.task)
        p.reset_episode(body)
        self.assertEqual(p.history[0]['task'],old_task)
        self.assertTrue((p.history_dir/'task-a.json').is_file())
        p.reset_pub=NS(publish=lambda value:(p.reset_requests.append(json.loads(value.data)),self.reset_ack(p,body)))
        p.execute_reset(body['request_id'])
        receipt=p.reset_record(body['request_id'])
        self.assertEqual(receipt['status'],'succeeded');self.assertNotEqual(p.episode_id,old)
        self.assertEqual(p.task['status'],'idle');self.assertEqual(p.reset_state(p.raw)['last']['to_episode'],p.episode_id)
        self.assertEqual(p.reset_state(p.raw)['last']['from_episode'],old)
        self.assertEqual(len(p.reset_requests),1);self.assertEqual(len(p.clear_requests),1)
        body['issued_at']-=100
        self.assertEqual(p.reset_episode(body)['status'],'succeeded')
        self.assertEqual(len(p.reset_requests),1)
        with self.assertRaises(core.Rejected):p.start({'task_id':str(uuid.uuid4()),'issued_at':self.epoch,'episode_id':old})
        p.start({'task_id':str(uuid.uuid4()),'issued_at':self.epoch,'episode_id':p.episode_id})
        self.assertEqual(p.task['status'],'running');self.assertEqual(len(p.history),1)

    def test_reset_unknown_late_ack_is_reconciled_without_second_physics_request(self):
        p,body=self.reset_probe();p.reset_episode(body)
        p.execute_reset(body['request_id'])
        self.assertEqual(p.reset_record(body['request_id'])['status'],'unknown')
        self.assertFalse(p.reset_state(p.raw)['available'])
        self.reset_ack(p,body)
        p.reset_record(body['request_id']);p.execute_reset(body['request_id'])
        self.assertEqual(p.reset_record(body['request_id'])['status'],'succeeded')
        self.assertEqual(len(p.reset_requests),1);self.assertEqual(len(p.clear_requests),1)

    def test_reset_failed_plant_receipt_keeps_old_task_and_episode(self):
        p,body=self.reset_probe();old=p.episode_id;p.reset_episode(body)
        p.reset_pub=NS(publish=lambda value:self.reset_ack(p,body,'failed'))
        p.execute_reset(body['request_id'])
        self.assertEqual(p.reset_record(body['request_id'])['status'],'failed')
        self.assertEqual(p.episode_id,old);self.assertEqual(p.task['status'],'succeeded')
        self.assertEqual(p.clear_requests,[]);self.assertEqual(p.poses,[])

    def test_reset_stale_episode_and_wrong_ack_cannot_admit_or_finish(self):
        p,body=self.reset_probe();wrong={**body,'episode_id':str(uuid.uuid4())}
        with self.assertRaises(core.Rejected):p.reset_episode(wrong)
        p.reset_episode(body)
        self.reset_ack(p,{**body,'request_id':str(uuid.uuid4())})
        self.assertEqual(p.reset_acks,{})
        p.raw['episode_id']=p.episode_id;p.raw['source']['episode_id']=p.episode_id
        p.execute_reset(body['request_id'])
        self.assertEqual(p.reset_record(body['request_id'])['status'],'unknown')
        self.assertEqual(p.task['status'],'succeeded')

    def test_frame_path_is_bound_to_current_episode(self):
        p,body=self.reset_probe()
        self.assertEqual(p.frame_image({'episode_id':p.episode_id,'image_file':p.episode_id+'.jpg'}).name,p.episode_id+'.jpg')
        for info in ({'episode_id':str(uuid.uuid4()),'image_file':'latest.jpg'},
                     {'episode_id':p.episode_id,'image_file':'../other.jpg'}):
            with self.assertRaises(ValueError):p.frame_image(info)

    def test_cancel_between_acceptance_and_release_never_releases_car_hold(self):
        p=self.bridge;handle=ControlledHandle();handle.result_future.resolve(NS(status=4))
        def cancel():
            with p.lock:
                p.cancel_event.set();p.task['status']='canceling';p.abort(p.execution_token,'用户取消任务')
        handle.before_result=cancel;p.nav.send_goal_async=lambda request:ControlledFuture(handle,True)
        with self.assertRaises(self.namespace['Canceled']):p.navigate(self.goal())
        self.assertTrue(p.holds);self.assertNotIn(False,p.holds)
        self.assertTrue(p.abort_event.is_set())

    def test_late_accepted_goal_uses_its_result_and_retains_unknown_owner(self):
        p=self.bridge;sent=ControlledFuture();handle=ControlledHandle();p.nav.send_goal_async=lambda request:sent
        p.station_capture_ready=lambda:False
        # These stale attributes reproduce the prior bug. Current paths must ignore them.
        p.result_future=ControlledFuture(NS(status=4),True);p.goal_pending=ControlledFuture(None,True)
        def timeout(*args,**kwargs):raise RuntimeError('原生Nav2动作回执超时')
        p.wait_future=timeout
        def late_accept():
            if not sent.done():sent.resolve(handle)
        self.on_sleep=late_accept
        p.execute(p.execution_token)
        self.assertEqual(p.task['status'],'unknown');self.assertEqual(handle.cancels,1)
        self.assertIs(p.dispatches[0]['result'],handle.result_future)
        self.assertTrue(p.abort_event.is_set());self.assertNotIn(False,p.holds)
        self.assertEqual(p.execution_token,('task-a',1))

    def test_completed_result_does_not_override_user_cancel_or_authorize_new_reference(self):
        p=self.bridge;p.cancel_event.set();p.abort_event.set();p.task['status']='canceling'
        with self.assertRaises(self.namespace['Canceled']):p.wait_future(ControlledFuture(NS(status=4),True),8)
        with self.assertRaises(self.namespace['Canceled']):p.reference([.1]*6)
        with self.assertRaises(self.namespace['Canceled']):p.hold(False)
        self.assertEqual(p.refs,[]);self.assertTrue(p.freeze_arm(p.execution_token))
        self.assertEqual(p.refs,[[0.]*6])

    def test_already_terminal_native_result_never_releases_motion_hold(self):
        p=self.bridge;handle=ControlledHandle()
        handle.result_future.resolve(NS(status=4))
        p.nav.send_goal_async=lambda request:ControlledFuture(handle,True)
        p.navigate(self.goal())
        self.assertNotIn(False,p.holds)

    def test_stale_callback_cancels_only_its_handle_without_overwriting_new_task(self):
        p=self.bridge;old={'token':p.execution_token,'epoch':1,'received':False,'handle':None,'result':None,'cancel':None,'aborted':True,'error':None}
        p.execution_token=('task-b',2);p.task['id']='task-b';new_handle=ControlledHandle()
        p.dispatches=[{'token':p.execution_token,'epoch':2,'handle':new_handle}]
        old_handle=ControlledHandle();p.received_goal(old,ControlledFuture(old_handle,True))
        self.assertEqual(old_handle.cancels,1);self.assertEqual(new_handle.cancels,0)
        self.assertIs(p.dispatches[0]['handle'],new_handle);self.assertEqual(p.task['id'],'task-b')

    def test_malformed_or_foreign_source_never_yields_ready_and_clears_old_observation(self):
        p=self.bridge;p.task['status']='idle';p.raw.pop('arm_forbidden_contact_total')
        result=p.state();self.assertFalse(result['ready']);self.assertIsNone(result['physics'])
        foreign=measurement();foreign['source']['scene_sha256']='c'*64
        p.observe(NS(data=json.dumps(foreign)))
        self.assertIsNone(p.raw);self.assertIn('SHA',p.observation_error)
        self.assertFalse(p.state()['ready'])

    def test_foreign_cancel_does_not_touch_current_nav_or_dock_handles(self):
        p = self.bridge
        task_id, foreign_id = str(uuid.uuid4()), str(uuid.uuid4())
        p.task.update(id=task_id, status='running')
        p.execution_token = (task_id, p.task_epoch)
        handles = [ControlledHandle(), ControlledHandle()]
        p.dispatches = [{'token': p.execution_token, 'handle': handle} for handle in handles]
        with self.assertRaises(core.Rejected):
            p.cancel({'task_id': foreign_id, 'issued_at': time.time()})
        self.assertEqual([handle.cancels for handle in handles], [0, 0])
        self.assertFalse(p.cancel_event.is_set())
        self.assertFalse(p.abort_event.is_set())
        self.assertEqual(p.holds, [])
        self.assertEqual(p.task['status'], 'running')

    def test_duplicate_uuid_is_readback_and_unknown_task_cannot_start_a_new_epoch(self):
        p=self.bridge;p.task.update(id=None,status='idle');p.execution_token=None
        task=str(uuid.uuid4());body={'task_id':task,'issued_at':time.time()}
        first=p.start(body);second=p.start(body)
        self.assertEqual(first['task_id'],second['task_id']);self.assertEqual(len(self.threads),1)
        self.assertEqual(p.task_epoch,2)
        p.task['status']='unknown'
        with self.assertRaises(core.Rejected):p.start({'task_id':str(uuid.uuid4()),'issued_at':time.time()})
        self.assertEqual(len(self.threads),1)

    def test_native_terminal_and_continuous_car_arm_quiet_are_both_required(self):
        p=self.bridge;handle=ControlledHandle();dispatch={'token':p.execution_token,'received':True,'handle':handle,
            'result':handle.result_future,'cancel':None,'error':None,'aborted':True}
        p.dispatches=[dispatch];p.abort_event.set()
        self.assertFalse(p.cleanup(p.execution_token,timeout=.8))
        handle.result_future.resolve(NS(status=5));p.raw['qvel6'][0]=.2;p.raw['qvel20'][0]=.2
        self.assertFalse(p.cleanup(p.execution_token,timeout=.8))
        p.raw['qvel6'][0]=p.raw['qvel20'][0]=0.
        self.assertTrue(p.cleanup(p.execution_token,timeout=.8))

    def test_first_forward_contact_stops_before_the_next_step_total(self):
        p=self.bridge
        p.raw['car_forbidden_contacts']=[{'geom1':'car','geom2':'bench','normal_force_n':.01,'distance_m':-.0001}]
        p.raw['car_forbidden_contact_count']=1
        self.assertEqual(p.raw['car_forbidden_contact_total'],0)
        with self.assertRaisesRegex(RuntimeError,'非预期物理接触'):p.check()
        p.task['status']='idle'
        self.assertFalse(p.state()['ready'])

    def test_transport_wait_rechecks_arm_home_after_transfer(self):
        p=self.bridge;future=ControlledFuture()
        p.check(carrying=True)
        def leaves_home():
            p.raw['q6'][0]=p.raw['qpos22'][0]=.021
        self.on_sleep=leaves_home
        with self.assertRaisesRegex(RuntimeError,'机械臂未保持回位停稳'):
            p.wait_future(future,timeout=1.,carrying=True)
        self.assertFalse(future.done())

    def test_transport_check_rejects_supported_corner_overhang_and_arm_motion(self):
        p=self.bridge;p.raw['cargo']['position_relative_tray'][0]=.047
        q=[math.cos(math.pi/8),0.,0.,math.sin(math.pi/8)]
        p.raw['cargo']['quaternion_wxyz']=q;p.raw['qpos22'][9:13]=q
        with self.assertRaisesRegex(RuntimeError,'托盘支撑范围'):p.check(carrying=True)
        p.raw['cargo']['position_relative_tray'][0]=0.
        p.raw['qvel6'][1]=p.raw['qvel20'][1]=.05
        with self.assertRaisesRegex(RuntimeError,'机械臂未保持回位停稳'):p.check(carrying=True)

    def execution_handoff_probe(self, *, before_transfer=None, after_delivery=None, delivery_distance=1.):
        """Exercise current execute ordering; controlled samples are not physical acceptance."""
        p=self.bridge;p.station_capture_ready=lambda:True;p.align_station_map=lambda:None
        p.dock_at_station=lambda:p.check()
        class Planner:
            def __init__(self,*args,**kwargs):pass
            def prepare_approach(self,q):return {'segments':[{'stage':'lift'}]}
            def prepare_transport(self,raw):return {'segments':[{'stage':name} for name in ('release','retreat','settle')]}
        self.namespace['ArmPlanner']=Planner
        def segment(item,planner):
            if item['stage']=='lift':
                p.raw['cargo']['position'][2]=p.raw['qpos22'][8]=.07
                p.raw['finger_normal_forces_n']={key:.1 for key in p.raw['finger_normal_forces_n']}
            if item['stage']=='release':
                p.raw['cargo']['position'][2]=p.raw['qpos22'][8]=.03
                p.raw['finger_normal_forces_n']={key:0. for key in p.raw['finger_normal_forces_n']}
            if item['stage']=='settle' and before_transfer:before_transfer(p.raw)
            return p.check()
        p.segment=segment;deliveries=[]
        def navigate(goal,**kwargs):
            deliveries.append(goal)
            p.raw['cargo']['position'][0]=p.raw['qpos22'][6]=.24+delivery_distance
            if after_delivery:after_delivery(p.raw)
            return p.raw
        p.navigate=navigate
        def hold(message):
            p.holds.append(message.data);p.raw['car_hold']=p.raw['car']['hold']=message.data
        p.hold_pub=NS(publish=hold)
        p.execute(p.execution_token)
        return p,deliveries

    def test_execute_never_dispatches_transport_without_held_stationary_handoff(self):
        for fault in ('unheld','moving'):
            with self.subTest(fault=fault):
                self.setUp()
                def change(raw):
                    if fault=='unheld':raw['car_hold']=raw['car']['hold']=False
                    else:raw['car']['speed']=.01
                p,deliveries=self.execution_handoff_probe(before_transfer=change)
                self.assertEqual(deliveries,[])
                self.assertNotEqual(p.task['status'],'succeeded')
                self.assertNotIn('货物已放稳，机械臂已退出，可以运输。',[event['message'] for event in p.events])

    def test_execute_does_not_succeed_if_arm_leaves_home_at_delivery(self):
        def change(raw):raw['q6'][0]=raw['qpos22'][0]=.021
        p,deliveries=self.execution_handoff_probe(after_delivery=change)
        self.assertEqual(len(deliveries),1)
        self.assertEqual(p.task['status'],'failed')
        self.assertIn('机械臂未保持回位停稳',p.task['stop_reason'])

    def test_execute_controlled_handoff_keeps_half_meter_completion_gate(self):
        for distance in (.49,.5,1.):
            with self.subTest(distance=distance):
                self.setUp()
                p,deliveries=self.execution_handoff_probe(delivery_distance=distance)
                self.assertEqual(len(deliveries),1)
                self.assertEqual(p.task['status'],'failed' if distance<.5 else 'succeeded')
                if distance<.5:self.assertIn('运输位移不足0.5米',p.task['stop_reason'])

    def test_dock_action_has_no_hidden_staging_and_requires_payload_success(self):
        p=self.bridge;handle=ControlledHandle();requests=[]
        handle.result_future.resolve(NS(status=4,result=NS(success=False,error_code=905,error_msg='Dock control failed')))
        def send(request):requests.append(request);return ControlledFuture(handle,True)
        p.docking.send_goal_async=send
        with self.assertRaisesRegex(RuntimeError,'Nav2停靠目标未成功.*905.*Dock control failed'):p.dock_at_station()
        self.assertEqual(requests[0].dock_id,'so101_station')
        self.assertTrue(requests[0].use_dock_id)
        self.assertFalse(requests[0].navigate_to_staging_pose)
        self.assertEqual(len(p.dispatches),1)
        self.assertIs(p.dispatches[0]['handle'],handle)

    def test_unavailable_native_docking_service_never_reports_ready(self):
        p=self.bridge;p.task['status']='idle';p.docking.server_is_ready=lambda:False
        self.assertFalse(p.state()['ready'])

    def station_measurement(self):
        p=self.bridge
        p.raw['dock_beacon']={'idealized_truth_derived':True,'scene_sha256':'a'*64,
                             'manifest_sha256':'b'*64,'in_range':True}
        measured=NS(header=NS(frame_id='base_footprint',stamp=NS(sec=10,nanosec=0)),
            pose=NS(position=NS(x=-.7,y=0.,z=0.),orientation=NS(w=0.,x=0.,y=0.,z=1.)))
        p.beacon=(measured,self.clock)
        return measured

    def test_station_hint_preserves_sensor_stamp_and_requires_this_task_owner(self):
        p=self.bridge;measured=self.station_measurement()
        self.assertEqual(p.update_station_localization(force=True),{'x':.7,'y':0.,'yaw':0.})
        self.assertEqual(len(p.poses),1)
        self.assertEqual(p.poses[0].header.frame_id,'map')
        self.assertEqual(p.poses[0].header.stamp.sec,measured.header.stamp.sec)
        self.assertEqual(p.poses[0].pose.pose.position.x,.7)
        p.update_station_localization();self.assertEqual(len(p.poses),1)
        p.cancel_event.set()
        with self.assertRaises(self.namespace['Canceled']):p.update_station_localization(force=True)
        self.assertEqual(len(p.poses),1)

    def test_transit_station_hint_only_uses_fresh_in_range_observations(self):
        p=self.bridge;measured=self.station_measurement()
        p.raw['dock_beacon']['in_range']=False
        self.assertIsNone(p.update_station_localization(optional=True))
        with self.assertRaisesRegex(RuntimeError,'有效范围'):p.update_station_localization()
        p.raw['dock_beacon']['in_range']=True;measured.header.stamp.sec=9
        self.assertIsNone(p.update_station_localization(optional=True))
        self.assertEqual(p.poses,[])
        measured.header.stamp.sec=10
        self.assertEqual(p.update_station_localization(optional=True),{'x':.7,'y':0.,'yaw':0.})
        self.assertEqual(p.poses[0].header.stamp.sec,10)
        p.raw['dock_beacon']['manifest_sha256']='c'*64
        with self.assertRaisesRegex(RuntimeError,'来源'):p.update_station_localization(optional=True)

    def test_capture_never_uses_moving_stale_or_outside_station_observations(self):
        p=self.bridge;self.station_measurement()
        p.raw['car']['speed']=.1
        self.assertFalse(p.station_capture_ready());self.assertEqual(p.poses,[])
        p.raw['car']['speed']=0.;p.raw['dock_beacon']['in_range']=False
        self.assertFalse(p.station_capture_ready());self.assertEqual(p.poses,[])
        p.raw['dock_beacon']['in_range']=True
        self.assertTrue(p.station_capture_ready())
        p.cancel_event.set()
        with self.assertRaises(self.namespace['Canceled']):p.station_capture_ready()

    def test_docking_guard_wrong_scene_ack_never_releases_the_car(self):
        p=self.bridge;handle=ControlledHandle()
        p.docking.send_goal_async=lambda request:ControlledFuture(handle,True)
        p.raw['docking_guard']['dock_pose']=[1.,0.,0.]
        with self.assertRaisesRegex(RuntimeError,'当前场景'):p.dock_at_station()
        self.assertNotIn(False,p.holds)
        self.assertEqual(handle.cancels,1)

    def test_guard_stop_without_native_success_is_failure_not_completion(self):
        p=self.bridge;p.raw['docking_guard'].update(enabled=True,tripped=True)
        with self.assertRaisesRegex(RuntimeError,'未获原生停靠成功'):
            p.wait_future(ControlledFuture(),10,docking_guard=True)
        self.assertLess(self.clock,103.)

    def test_cleanup_keeps_guard_until_hold_and_owned_terminal_are_confirmed(self):
        p=self.bridge;p.dock_guard_active=True;p.raw['docking_guard']['enabled']=True
        p.raw['car_hold']=False;p.raw['car']['hold']=False
        self.assertFalse(p.cleanup(p.execution_token,timeout=1.))
        self.assertEqual(p.guard_requests,[])
        p.raw['car_hold']=True;p.raw['car']['hold']=True
        self.assertTrue(p.cleanup(p.execution_token,timeout=1.))
        self.assertEqual(p.guard_requests,[False])

    def test_cleanup_missing_disable_ack_keeps_unknown_instead_of_assuming_delivery(self):
        p=self.bridge;p.dock_guard_active=True;p.raw['docking_guard']['enabled']=True
        p.dock_guard_pub=NS(publish=lambda message:p.guard_requests.append(message.data))
        self.assertFalse(p.cleanup(p.execution_token,timeout=1.))
        self.assertEqual(p.guard_requests,[False]);self.assertTrue(p.raw['docking_guard']['enabled'])

    def test_native_success_disable_timeout_cannot_escape_cleanup_actual_ack(self):
        p=self.bridge;handle=ControlledHandle()
        handle.result_future.resolve(NS(status=4,result=NS(success=True)))
        p.docking.send_goal_async=lambda request:ControlledFuture(handle,True)
        def drop_disable_ack(message):
            p.guard_requests.append(message.data)
            if message.data:p.raw['docking_guard']['enabled']=True
        p.dock_guard_pub=NS(publish=drop_disable_ack)
        with self.assertRaisesRegex(RuntimeError,'未取得连续物理确认'):p.dock_at_station()
        self.assertFalse(p.dock_guard_active);self.assertTrue(p.raw['docking_guard']['enabled'])
        self.assertFalse(p.cleanup(p.execution_token,timeout=1.))
        self.assertEqual(p.guard_requests,[True,False,False])
        self.assertNotIn(False,p.holds)

    def test_cleanup_local_disabled_flag_still_waits_for_actual_false_ack(self):
        p=self.bridge;p.dock_guard_active=False;p.raw['docking_guard']['enabled']=True
        sent_at=[]
        def publish(message):
            p.guard_requests.append(message.data);sent_at.append(self.clock)
        p.dock_guard_pub=NS(publish=publish)
        def late_ack():
            if sent_at and self.clock > sent_at[-1]+.1:p.raw['docking_guard']['enabled']=False
        self.on_sleep=late_ack
        self.assertTrue(p.cleanup(p.execution_token,timeout=1.))
        self.assertEqual(p.guard_requests,[False]);self.assertFalse(p.raw['docking_guard']['enabled'])
        self.assertGreater(self.clock,sent_at[-1]+.1)

    def test_segment_slow_physics_uses_source_budget_and_keeps_joint_accuracy(self):
        p=self.bridge;self.source_rate=.4
        def track_reference():
            p.raw['q6']=list(p.last_ref)
            p.raw['qpos22'][:6]=p.last_ref
        self.on_sleep=track_reference
        planner=NS(evaluate=lambda q:{'valid':True})
        p.segment({'stage':'approach','path':[[0.]*5,[.1]*5], 'gripper':.5,
                   'duration_s':25.,'dwell_s':.6},planner)
        self.assertGreater(self.clock-100.,45.6)
        self.assertGreaterEqual(p.raw['stamp']-10.,25.6)
        self.assertLess(np.max(np.abs(np.asarray(p.raw['q6'])[:5]-.1)),.012)

    def test_segment_paused_source_still_hits_independent_total_wall_deadline(self):
        p=self.bridge;self.source_rate=0.;p.wall_deadline=100.5
        with self.assertRaisesRegex(RuntimeError,'超过总执行时间'):
            p.segment({'stage':'approach','path':[[0.]*5], 'gripper':.5,
                       'duration_s':25.,'dwell_s':.6},NS(evaluate=lambda q:{'valid':True}))

    def test_segment_bad_servo_identifies_joint_without_relaxing_settling_budget(self):
        p=self.bridge
        with self.assertRaisesRegex(RuntimeError,'关节 joint 误差 0.1000rad，仿真时间'):
            p.segment({'stage':'approach','path':[[.1]*5], 'gripper':.5,
                       'duration_s':0.,'dwell_s':0.},NS(evaluate=lambda q:{'valid':True}))
        self.assertLess(self.clock-100.,20.1)

    def test_foreign_stale_or_out_of_range_station_never_changes_localization(self):
        p=self.bridge;measured=self.station_measurement();measured.header.stamp.sec=9
        with self.assertRaisesRegex(RuntimeError,'过期'):p.update_station_localization(force=True)
        measured.header.stamp.sec=10;measured.pose.position.x=-1.1
        with self.assertRaisesRegex(RuntimeError,'有效范围'):p.update_station_localization(force=True)
        measured.pose.position.x=-.7;p.raw['dock_beacon']['manifest_sha256']='c'*64
        with self.assertRaisesRegex(RuntimeError,'来源'):p.update_station_localization(force=True)
        p.raw['dock_beacon']['manifest_sha256']='b'*64
        p.get_publishers_info_by_topic=lambda name:[NS(node_name='other')]
        with self.assertRaisesRegex(RuntimeError,'唯一'):p.update_station_localization(force=True)
        self.assertEqual(p.poses,[])

    def test_native_failure_preserves_official_error_code_and_message(self):
        p=self.bridge;handle=ControlledHandle()
        handle.result_future.resolve(NS(status=6,result=NS(error_code=104,error_msg='Trajectory collision detected')))
        p.nav.send_goal_async=lambda request:ControlledFuture(handle,True)
        with self.assertRaisesRegex(RuntimeError,'状态6，错误码104：Trajectory collision detected'):
            p.navigate(self.goal())
        self.assertEqual(p.abort_reason,'Nav2目标未成功，状态6，错误码104：Trajectory collision detected')

    def test_missing_native_failure_message_is_reported_as_unprovided(self):
        p=self.bridge;handle=ControlledHandle()
        handle.result_future.resolve(NS(status=6,result=NS(error_code=0,error_msg='')))
        p.nav.send_goal_async=lambda request:ControlledFuture(handle,True)
        with self.assertRaisesRegex(RuntimeError,'状态6，错误码0：Nav2未提供具体失败原因'):
            p.navigate(self.goal())


class RuntimePreflightTests(unittest.TestCase):
    def test_old_or_corrupt_ledger_is_rejected_before_ros_import_and_unchanged(self):
        source=Path(__file__).parents[1]/'cooperation_bridge.py'
        spec=importlib.util.spec_from_file_location('bridge_preflight',source)
        bridge=importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules',{'cooperation_core':core}):spec.loader.exec_module(bridge)
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory);ledger=output/'task.json'
            for contents in ('invalid JSON',*[json.dumps({'task':{'id':'old','status':state}})
                    for state in ['running','canceling','unknown','canceled','failed','succeeded']]):
                ledger.write_text(contents)
                with self.assertRaisesRegex(RuntimeError,'不能复用旧物理回合'):
                    bridge.run(NS(output=output))
                self.assertEqual(ledger.read_text(),contents)


if __name__=='__main__':unittest.main()
