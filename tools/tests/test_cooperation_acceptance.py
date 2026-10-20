"""Panel/threshold/dispatch boundaries; no ROS runtime is started."""
import copy
import importlib.util
import json
import math
import socket
import io
import urllib.error
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock

TOOLS=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('cooperation_acceptance',TOOLS/'cooperation_acceptance.py')
acceptance=importlib.util.module_from_spec(spec);spec.loader.exec_module(acceptance)


def baseline_reports():
    reports=[]
    for item in acceptance.build_panel()['cases'][:3]:
        reports.append({'case':item,'passed':True,'source_unchanged':True,
            'geometry':{'passed':True,'certified_margin_m':.04},
            'source_start_sha256':'a'*64,'source_end_sha256':'b'*64,
            'oracle':{'observation_metrics':{'observation_position_error_p95_m':0.,'observation_yaw_error_p95_rad':0.},
                'docking_acceptance':{'attempts':[{'stationary_position_error_p95_m':.01,'stationary_yaw_error_p95_rad':.01}]}}})
    return reports


class PanelTests(unittest.TestCase):
    def test_fixed_counts_capture_tube_seeds_and_original_full_spawn(self):
        panel=acceptance.validate_panel(acceptance.build_panel())
        counts={phase:sum(c['phase']==phase for c in panel['cases']) for phase in panel['expected_counts']}
        self.assertEqual(counts,{'baseline':6,'perturbed':24,'fault':8,'vision':12,'full':6})
        self.assertEqual(len(set(c['name'] for c in panel['cases'])),56)
        self.assertEqual([p['seed'] for p in panel['poses']],[11,29,47,101,131,167])
        for item in panel['cases']:
            if item['scope']=='dock':
                along,lateral,yaw=item['offset']
                self.assertTrue(.2<=along<=.9 and abs(lateral)<=.06 and abs(yaw)<=.15)
                self.assertEqual(item['budget']['task_timeout_s'],60.)
            else:
                self.assertEqual(item['spawn'],[0.,-2.,0.])
                self.assertEqual(item['budget']['task_timeout_s'],360.)

    def test_world_transform_rotates_offsets(self):
        result=acceptance.world_pose([.7,.03,.1],[2.,3.,math.pi/2])
        self.assertAlmostEqual(result[0],1.97);self.assertAlmostEqual(result[1],3.7)
        self.assertAlmostEqual(result[2],math.pi/2+.1)

    def test_posthoc_threshold_budget_or_case_tampering_is_rejected(self):
        for key in ('threshold','budget','case'):
            panel=acceptance.build_panel()
            if key=='threshold':panel['physical_thresholds']['position_m']=.05
            if key=='budget':panel['cases'][0]['budget']['task_timeout_s']=75.
            if key=='case':panel['cases'].pop()
            with self.subTest(key=key),self.assertRaises(ValueError):acceptance.validate_panel(panel)

    def test_vision_lighting_and_physical_occlusion_are_literal(self):
        variants=[c for c in acceptance.build_panel()['cases'] if c['phase']=='vision' and c['name'].startswith('vision-image')]
        self.assertEqual([c['camera_light_scale'] for c in variants],[1.,.5,.5,1.,1.,1.])
        self.assertEqual([c['expected_outcome'] for c in variants],['success','success','success','safe_cancel','safe_cancel','success'])
        config={'mode':'vision','publisher':'station_camera','min_confidence':.5,'max_covariance':[.0025,.0025,.01]}
        _,fault=acceptance.perception_config(variants[3],None,config)
        self.assertEqual(fault,{'schema':1,'kind':'long_occlusion','duration_wall_s':.8})

    def test_dry_run_never_spawns_or_mutates(self):
        with (patch.object(acceptance.subprocess,'Popen',side_effect=AssertionError('spawn')),
             patch.object(acceptance,'execute_case',side_effect=AssertionError('execute')),
             patch('builtins.print') as output):
            self.assertEqual(acceptance.main(['--phase','all','--dry-run']),0)
        value=json.loads(output.call_args.args[0]);self.assertFalse(value['execution_started'])
        self.assertEqual(len(value['cases']),56)


class ThresholdTests(unittest.TestCase):
    def test_zero_ideal_residual_still_has_predeclared_positive_noise_and_margin_cap(self):
        result=acceptance.derive_thresholds(baseline_reports())
        self.assertGreater(result['noise_high'][0],0.)
        self.assertLessEqual(result['noise_high'][0]*3*math.sqrt(2),.03+1e-12)
        self.assertEqual(result['noise_low'][0],result['noise_high'][0]/2)
        self.assertEqual(result['derived_from_split'],'dev')
        self.assertFalse(result['gaussian_support_is_bounded'])

    def test_holdout_duplicate_missing_failure_and_exhausted_margin_do_not_calibrate(self):
        variants=[]
        hold=baseline_reports();hold[0]['case']['split']='holdout';variants.append(hold)
        duplicate=baseline_reports();duplicate[1]['case']=copy.deepcopy(duplicate[0]['case']);variants.append(duplicate)
        variants.append(baseline_reports()[:2])
        failed=baseline_reports();failed[0]['passed']=False;variants.append(failed)
        exhausted=baseline_reports();exhausted[0]['oracle']['docking_acceptance']['attempts'][0]['stationary_position_error_p95_m']=.04;variants.append(exhausted)
        for reports in variants:
            with self.subTest(reports=reports),self.assertRaises(ValueError):acceptance.derive_thresholds(reports)

    def test_geometry_margin_and_noise_covariance_are_respected(self):
        thresholds=acceptance.derive_thresholds(baseline_reports(),geometry_margin_m=.006)
        self.assertEqual(thresholds['position_margin_m'],.006)
        item=next(c for c in acceptance.build_panel()['cases'] if c['condition']=='noise_high')
        config,_=acceptance.perception_config(item,thresholds)
        for variance,std in zip(config['max_covariance'],config['noise_std']):self.assertEqual(variance,.0001+std*std)

    def test_perturbed_without_frozen_dev_measurements_and_vision_without_producer_fail(self):
        item=next(c for c in acceptance.build_panel()['cases'] if c['condition']=='noise_high')
        with self.assertRaises(ValueError):acceptance.perception_config(item)

    def test_missing_or_failed_geometry_cannot_supply_nominal_margin(self):
        for key in ('missing','failed','zero'):
            reports=baseline_reports()
            if key=='missing':reports[0].pop('geometry')
            if key=='failed':reports[0]['geometry']['passed']=False
            if key=='zero':reports[0]['geometry']['certified_margin_m']=0.
            with self.subTest(key=key),self.assertRaises(ValueError):acceptance.derive_thresholds(reports)
        item=next(c for c in acceptance.build_panel()['cases'] if c['phase']=='vision')
        with self.assertRaises(ValueError):acceptance.perception_config(item)


class EvidenceTests(unittest.TestCase):
    def test_port_probe_reuses_closed_connections_but_refuses_live_listener(self):
        with socket.socket() as server:
            server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            server.bind(('127.0.0.1',0));server.listen(1)
            port=server.getsockname()[1]
            with self.assertRaises(OSError):acceptance.ensure_port_available(port)
            with socket.create_connection(('127.0.0.1',port)) as client:
                accepted,_=server.accept();accepted.close()
                self.assertEqual(client.recv(1),b'')
        acceptance.ensure_port_available(port)
    def test_failed_baseline_stops_before_any_later_dispatch_or_calibration(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);panel=path/'panel.json';acceptance.private_json(panel,acceptance.build_panel())
            with patch.object(acceptance,'execute_case',side_effect=lambda declaration,*args:
                              {'case':declaration,'passed':False}) as run:
                code=acceptance.main(['--phase','baseline','--split','dev','--panel',str(panel),
                    '--output',str(path/'results'),'--python','/usr/bin/python3',
                    '--so101-project',str(path),'--protected-unit','old107','--protected-unit','old114'])
            self.assertEqual(code,1);self.assertEqual(run.call_count,1)
            self.assertFalse((path/'results/thresholds.json').exists())

    def test_action_server_discovery_without_fresh_active_lifecycle_never_dispatches(self):
        inactive={'ready':True,'observed_monotonic':100.,
                  'lifecycle':{'docking_server':[1,100.],'bt_navigator':[3,100.]}}
        self.assertFalse(acceptance.lifecycle_active(inactive,100.1))
        active=copy.deepcopy(inactive);active['lifecycle']['docking_server'][0]=3
        self.assertTrue(acceptance.lifecycle_active(active,100.1))
        self.assertFalse(acceptance.lifecycle_active(active,100.6))
        missing=copy.deepcopy(active);missing['lifecycle'].pop('bt_navigator')
        self.assertFalse(acceptance.lifecycle_active(missing,100.1))

    def test_explicit_rejected_original_handle_allows_cleanup_but_unknown_acceptance_does_not(self):
        state={'episode_id':'episode','task':{'id':'task','status':'failed'},'native_actions':[
            {'uuid':'01'*16,'accepted':False,'terminal':True,'result_known':False,'status':None}]}
        self.assertTrue(acceptance.native_cleanup_known(state,{},'task','episode'))
        self.assertFalse(acceptance.native_cleanup_known(state,{('dock_status','01'*16):2},'task','episode'))
        for changed in ('accepted','terminal','unknown','missing','wrong_task'):
            altered=copy.deepcopy(state)
            if changed=='accepted':altered['native_actions'][0]['accepted']=True
            if changed=='terminal':altered['native_actions'][0]['terminal']=False
            if changed=='unknown':altered['task']['status']='unknown'
            if changed=='missing':altered['native_actions']=[]
            if changed=='wrong_task':altered['task']['id']='other'
            with self.subTest(changed=changed):self.assertFalse(acceptance.native_cleanup_known(altered,{},'task','episode'))

    def test_observer_is_signaled_once_and_scoring_waits_do_not_signal(self):
        process=Mock();process.poll.return_value=None;process._acceptance_sigint_sent=False
        self.assertTrue(acceptance.signal_observer_once(process))
        self.assertFalse(acceptance.signal_observer_once(process))
        acceptance.finish_observer(process,1.);acceptance.finish_observer(process,1.)
        self.assertEqual(process.send_signal.call_count,1)

    def test_non_motion_timeout_children_are_stopped_and_survivors_retained(self):
        process=Mock();process.pid=123;process.poll.side_effect=[None,0]
        result={}
        with (patch.object(acceptance,'owned_processes',return_value={123:'start'}),
             patch.object(acceptance.os,'killpg') as stop,
             patch.object(acceptance,'surviving_processes',return_value=[456])):
            self.assertEqual(acceptance.stop_non_motion_child(process,'prepare',result),[456])
        stop.assert_called_once_with(123,acceptance.signal.SIGTERM)
        self.assertEqual(result['non_motion_children'][0]['survivors'],[456])

    def test_unknown_http_submission_is_not_retried(self):
        with patch.object(acceptance.urllib.request,'urlopen',side_effect=TimeoutError('unknown')) as send:
            with self.assertRaises(TimeoutError):acceptance.api_request('http://127.0.0.1:9090/coop-api','/start',{'task_id':'uuid'})
        self.assertEqual(send.call_count,1)

    def test_explicit_http_rejection_is_distinct_from_unconfirmed_http_error(self):
        for body,kind in (({'outcome':'rejected','error':'stale'},acceptance.ApiRejected),
                          ({'error':'proxy failure'},RuntimeError)):
            error=urllib.error.HTTPError('http://127.0.0.1/start',409,'conflict',{},io.BytesIO(json.dumps(body).encode()))
            with patch.object(acceptance.urllib.request,'urlopen',side_effect=error) as send:
                with self.assertRaises(kind) as caught:acceptance.api_request('http://127.0.0.1','/start',{})
            self.assertEqual(send.call_count,1)
            if body.get('outcome')=='rejected':self.assertEqual(caught.exception.details,body)
            else:self.assertNotIsInstance(caught.exception,acceptance.ApiRejected)

    def test_rejected_submission_cleanup_cannot_take_over_another_task_or_active_uuid(self):
        idle={'episode_id':'e','task':{'id':None,'status':'idle'},'native_actions':[]}
        self.assertTrue(acceptance.rejected_submission_cleanup_known(idle,{},'e'))
        self.assertFalse(acceptance.rejected_submission_cleanup_known(idle,{('dock','01'*16):2},'e'))
        for key,value in (('episode_id','other'),('task',{'id':'other','status':'succeeded'}),
                          ('native_actions',[{'accepted':True}])):
            changed={**idle,key:value}
            with self.subTest(key=key):self.assertFalse(acceptance.rejected_submission_cleanup_known(changed,{},'e'))

    def test_private_panel_does_not_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'panel.json';acceptance.private_json(path,acceptance.build_panel())
            original=path.read_bytes()
            with self.assertRaises(FileExistsError):acceptance.private_json(path,{})
            self.assertEqual(path.read_bytes(),original);self.assertEqual(path.stat().st_mode&0o777,0o600)

    def test_tail_preserves_partial_lines_and_requires_independent_motion(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'observer.jsonl';tail=acceptance.EvidenceTail(path)
            items=[{'topic':'dock_status','payload':{'status_list':[{'goal_info':{'goal_id':{'uuid':[1]*16}},'status':2}]}},
                *[{'topic':'truth','source_stamp':t,'received_wall_time':100.,'payload':{'pose':{'pose':{'position':{'x':x,'y':0.,'z':0.}}}}}
                  for t,x in ((1.,0.),(1.02,.002))]]
            data='\n'.join(json.dumps(i) for i in items)+'\n';path.write_text(data[:-4]);tail.refresh()
            self.assertIsNone(tail.moving_dock())
            with path.open('a') as stream:stream.write(data[-4:])
            with patch.object(acceptance.time,'time',return_value=100.1):tail.refresh();self.assertEqual(tail.moving_dock(),'01'*16)

    def test_native_terminal_survives_long_physics_tail_without_rewriting_failure(self):
        def native(status):
            return {'topic':'dock_status','payload':{'status_list':[
                {'goal_info':{'goal_id':{'uuid':[1]*16}},'status':status}]}}
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'observer.jsonl';tail=acceptance.EvidenceTail(path)
            with path.open('w')as stream:
                stream.write(json.dumps(native(4))+'\n')
                for i in range(20001):stream.write(json.dumps({'topic':'clock','source_stamp':i})+'\n')
            tail.refresh()
            self.assertEqual(len(tail.records),20000)
            self.assertFalse(any(r['topic']=='dock_status'for r in tail.records))
            self.assertEqual(tail.native(),{('dock_status','01'*16):4})
            failed={'episode_id':'e','task':{'id':'t','status':'failed'},'native_actions':[
                {'uuid':'01'*16,'accepted':True,'terminal':True,'result_known':True,'status':4}]}
            self.assertTrue(acceptance.native_cleanup_known(failed,tail.native(),'t','e'))
            self.assertEqual(failed['task']['status'],'failed')
            unknown=copy.deepcopy(failed);unknown['task']['status']='unknown'
            self.assertFalse(acceptance.native_cleanup_known(unknown,tail.native(),'t','e'))
            self.assertFalse(acceptance.native_cleanup_known(failed,tail.native(),'other','e'))
            self.assertFalse(acceptance.native_cleanup_known(failed,tail.native(),'t','other'))
            missing=copy.deepcopy(failed);missing['native_actions'][0]['uuid']='02'*16
            self.assertFalse(acceptance.native_cleanup_known(missing,tail.native(),'t','e'))
            rejected=copy.deepcopy(failed);rejected['native_actions'][0]['accepted']=False
            self.assertFalse(acceptance.native_cleanup_known(rejected,tail.native(),'t','e'))
            with path.open('a')as stream:stream.write(json.dumps(native(2))+'\n')
            tail.refresh()
            self.assertEqual(tail.native(),{('dock_status','01'*16):2})
            self.assertFalse(acceptance.native_cleanup_known(failed,tail.native(),'t','e'))

    def test_native_status_index_is_bounded_and_empty_status_list_is_not_terminal(self):
        with tempfile.TemporaryDirectory()as temp:
            path=Path(temp)/'observer.jsonl';tail=acceptance.EvidenceTail(path)
            with path.open('w')as stream:
                for n in range(tail.NATIVE_STATUS_LIMIT+1):
                    stream.write(json.dumps({'topic':'nav_status','payload':{'status_list':[
                        {'goal_info':{'goal_id':{'uuid':list(n.to_bytes(16,'big'))}},'status':4}]}})+'\n')
            tail.refresh()
            self.assertEqual(len(tail.native_statuses),tail.NATIVE_STATUS_LIMIT)
            self.assertEqual(len(tail.native()),tail.NATIVE_STATUS_LIMIT)
            self.assertNotIn(('nav_status','00'*16),tail.native_statuses)
            # Empty DDS arrays do not fabricate terminal evidence for a new UUID.
            with path.open('a')as stream:stream.write(json.dumps({'topic':'dock_status','payload':{'status_list':[]}})+'\n')
            tail.refresh()
            self.assertEqual(len(tail.native_statuses),tail.NATIVE_STATUS_LIMIT)


class TaskDestinationCompatibilityTests(unittest.TestCase):
    def test_default_and_explicit_targets_are_declared_before_submission(self):
        self.assertEqual(acceptance.delivery_start_marker({}, {}), {
            'expected_delivery_pose': {'x': 0., 'y': -2., 'yaw': 0.},
            'requested_delivery_pose': None})
        body={'delivery_pose': {'x': .7, 'y': -2, 'yaw': 0}}
        marker=acceptance.delivery_start_marker(body, {})
        body['delivery_pose']['x']=9
        self.assertEqual(marker['expected_delivery_pose']['x'], .7)
        self.assertEqual(marker['requested_delivery_pose']['x'], .7)

    def test_failure_before_dispatch_needs_explicit_cleanup_and_no_native_actions(self):
        state={'episode_id':'e','task':{'id':'t','status':'failed'},'native_actions':[],
               'cleanup':{'state':'verified','native_terminal':True,'quiet':True,'hold':True,'guard_disabled':True}}
        self.assertTrue(acceptance.native_cleanup_known(state,{},'t','e'))
        missing=copy.deepcopy(state);missing.pop('native_actions')
        self.assertFalse(acceptance.native_cleanup_known(missing,{},'t','e'))
        for key in state['cleanup']:
            changed=copy.deepcopy(state);changed['cleanup'].pop(key)
            self.assertFalse(acceptance.native_cleanup_known(changed,{},'t','e'))
        for status in ('running','unknown','succeeded'):
            changed=copy.deepcopy(state);changed['task']['status']=status
            self.assertFalse(acceptance.native_cleanup_known(changed,{},'t','e'))
        self.assertFalse(acceptance.native_cleanup_known(state,{('nav','01'*16):2},'t','e'))


if __name__=='__main__':unittest.main()
