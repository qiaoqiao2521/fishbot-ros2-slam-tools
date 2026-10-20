"""Offline business-case contracts; no ROS, HTTP owner, or robot is started."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import xml.etree.ElementTree as ET

TOOLS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('scene_validation', TOOLS/'fishbot_scene_validation.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class SceneValidation(unittest.TestCase):
    def setUp(self):
        self.native = 'e1'*16
        self.case = {'id':'clear', 'label':'clear', 'expected':'delivered',
            'waypoints':[{'x':1.,'y':0.,'yaw':0.}], 'return_home':False,
            'static_boxes':[{'id':'wall','center':[0.,2.],'half_size':[3.,.05]}],
            'geometry':{'half_length':.105,'half_width':.125}}
        self.evidence = {'task_id':'mission-1','sent_steady':1.,'mission':{
            'id':'mission-1','status':'succeeded','native_goal_id':self.native,'native_status':4,
            'cleanup_state':None,'start_pose':{'x':0.,'y':0.,'yaw':0.}}}
        self.recording = {'truth':[], 'native_status':[{'uuid':self.native,'status':4}],
            'final_steady_time':3.401,'final_ros_now':3.401,
            'contact_audit':[{'steady_time':.99,'stamp':.99,'available':True,'physics_steps_total':99,'collision_steps_total':0,'peak_normal_force_n':0.},
                             {'steady_time':3.4,'stamp':3.4,'available':True,'physics_steps_total':340,'collision_steps_total':0,'peak_normal_force_n':0.}]}
        for step in range(25):
            stamp = 1.+step*.1
            self.recording['truth'].append({'steady_time':stamp,'stamp':stamp,'ros_now':stamp,
                'x':min(1.,step/12),'y':0.,'yaw':0.,'linear_speed':.08 if step<12 else 0.,'angular_speed':0.})

    def test_delivered_requires_actual_original_uuid_and_independent_parking(self):
        result = runner.assess(self.case,self.evidence,self.recording)
        self.assertEqual((result['acceptance_result'],result['business_result']),('passed','route_completed'))
        self.assertTrue(result['metrics']['contact_force_observed'])
        self.assertEqual(result['metrics']['actual_contact_steps_delta'],0)
        self.assertGreater(result['metrics']['minimum_declared_clearance_m'],1.)
        other = copy.deepcopy(self.recording)
        other['native_status'][0]['uuid'] = 'e2'*16
        rejected = runner.assess(self.case,self.evidence,other)
        self.assertEqual(rejected['acceptance_result'],'failed')
        self.assertEqual(rejected['checks']['independent_native_terminal']['status'],'failed')

    def test_blocked_cancel_is_accepted_without_delivery(self):
        case = {**self.case,'id':'blocked','expected':'canceled'}
        evidence = copy.deepcopy(self.evidence)
        evidence['cancel_task_id'] = evidence['task_id']
        evidence['mission'].update(status='canceled',native_status=5)
        recording = copy.deepcopy(self.recording)
        recording['native_status'][0]['status'] = 5
        for sample in recording['truth']:
            sample.update(x=0.,linear_speed=0.)
        result = runner.assess(case,evidence,recording)
        self.assertEqual((result['acceptance_result'],result['business_result']),('passed','route_incomplete'))
        evidence['cancel_task_id'] = 'someone-elses-task'
        self.assertEqual(runner.assess(case,evidence,recording)['acceptance_result'],'failed')

    def test_foreign_task_repeated_old_frame_gap_and_overlap_cannot_pass(self):
        evidence = copy.deepcopy(self.evidence)
        evidence['mission']['id'] = 'other'
        self.assertEqual(runner.assess(self.case,evidence,self.recording)['checks']['original_task']['status'],'failed')
        old = copy.deepcopy(self.recording)
        old['truth'][10]['stamp'] = old['truth'][9]['stamp']
        self.assertEqual(runner.assess(self.case,self.evidence,old)['checks']['truth_advances']['status'],'failed')
        gap = copy.deepcopy(self.recording)
        del gap['truth'][3:10]
        self.assertEqual(runner.assess(self.case,self.evidence,gap)['checks']['truth_continuity']['status'],'failed')
        collision = {**self.case,'static_boxes':[{'center':[1.,0.],'half_size':[.05,.05]}]}
        result = runner.assess(collision,self.evidence,self.recording)
        self.assertEqual(result['acceptance_result'],'failed')
        self.assertLess(result['metrics']['minimum_declared_clearance_m'],0.)

    def test_return_home_requires_observed_outbound_visit(self):
        case = {**self.case,'return_home':True}
        recording = copy.deepcopy(self.recording)
        for sample in recording['truth']:
            sample.update(x=0.,linear_speed=0.)
        result = runner.assess(case,self.evidence,recording)
        self.assertEqual(result['checks']['ordered_waypoint_coverage']['status'],'failed')
        self.assertEqual(result['business_result'],'route_incomplete')

    def test_missing_contact_audit_is_incomplete_and_actual_collision_fails(self):
        missing = copy.deepcopy(self.recording)
        missing.pop('contact_audit')
        result = runner.assess(self.case,self.evidence,missing)
        self.assertEqual(result['acceptance_result'],'incomplete')
        self.assertIsNone(result['metrics']['actual_contact_steps_delta'])
        collision = copy.deepcopy(self.recording)
        collision['contact_audit'][-1]['collision_steps_total'] = 2
        result = runner.assess(self.case,self.evidence,collision)
        self.assertEqual(result['acceptance_result'],'failed')
        self.assertEqual(result['metrics']['actual_contact_steps_delta'],2)
        frozen = copy.deepcopy(self.recording)
        frozen['contact_audit'][-1]['physics_steps_total'] = 99
        self.assertEqual(runner.assess(self.case,self.evidence,frozen)['acceptance_result'],'incomplete')

    def test_rectangle_distance_handles_rotation_touching_and_diagonal(self):
        square = {'half_length':1.,'half_width':1.}
        self.assertAlmostEqual(runner.polygon_clearance([0,0,0],{'center':[4,4],'half_size':[1,1]},square),8**.5)
        self.assertEqual(runner.polygon_clearance([0,0,0],{'center':[2,0],'half_size':[1,1]},square),0.)
        self.assertLess(runner.polygon_clearance([0,0,.7],{'center':[.2,0],'half_size':[.1,.1]},square),0.)

    def test_reference_three_worlds_keep_one_base_map_and_physical_actor_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = runner.load_config(TOOLS/'config/scene_validation.example.json')
            panel = runner.prepare_panel(config,Path(temporary)/'panel')
            self.assertEqual(panel['source']['basis'],'synthetic_reference')
            self.assertEqual({case['id'] for case in panel['cases']},{'clear','detour','blocked'})
            self.assertEqual(len({case['map'] for case in panel['cases']}),1)
            worlds = []
            for case in panel['cases']:
                scene = ET.parse(case['scene_path']).getroot()
                actor = scene.find("worldbody/body[@name='moving_obstacle']")
                self.assertIsNotNone(actor.find("freejoint[@name='moving_obstacle_free_joint']"))
                self.assertEqual(case['launch_arguments']['obstacle'],'false')
                self.assertNotIn('base_footprint',ET.tostring(actor).decode())
                scene.find('worldbody').remove(actor)
                worlds.append(ET.tostring(scene))
            self.assertEqual(worlds[0],worlds[1])
            self.assertEqual(worlds[1],worlds[2])
            prepared = runner.load_config(Path(temporary)/'panel/panel.json')
            self.assertTrue(Path(prepared['map']).exists())
            self.assertEqual(prepared['layout']['door_width_m'],.8)
            self.assertIn('low_height_probe',{box['id'] for box in prepared['cases'][0]['static_boxes']})
            pgm = Path(prepared['map']).with_suffix('.pgm').read_bytes().split(b'\n',3)[3]
            row = 136-1-int((.55+1.7)/.025)
            column = int((-.25+.85)/.025)
            self.assertEqual(pgm[row*126+column],254)

    def test_optional_metadata_warns_and_uses_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'editable.json'
            path.write_text('{"cases": []}')
            with warnings.catch_warnings(record=True) as messages:
                config = runner.load_config(path)
            self.assertEqual(len(messages),2)
            self.assertEqual(config['source']['basis'],'unspecified')
            self.assertEqual(config['lidar']['profile'],'existing-runtime')
            path.write_text('{"source":{"label":"人工二改"},"lidar":{"profile":"3d"},"cases":[]}')
            self.assertEqual(runner.load_config(path)['source']['label'],'人工二改')

    def test_failed_case_does_not_block_later_case_and_selected_runs_accumulate(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = runner.load_config(TOOLS/'config/scene_validation.example.json')
            calls = []
            def execute(case, *_):
                calls.append(case['id'])
                if case['id']=='clear':
                    raise TimeoutError('one unavailable scene')
                return {'id':case['id'],'label':case['label'],'expected':case['expected'],
                    'business_result':'undelivered','acceptance_result':'passed','reason':'fixture',
                    'metrics':{},'task_id':'task','native_goal_id':self.native,'native_status':5}
            with patch.object(runner,'run_case',side_effect=execute),warnings.catch_warnings():
                warnings.simplefilter('ignore')
                result = runner.run_panel(config,temporary,execute=True)
            self.assertEqual(calls,['clear','detour','blocked'])
            self.assertEqual([case['acceptance_result'] for case in result['cases']],['incomplete','passed','passed'])
            with patch.object(runner,'run_case',side_effect=execute):
                result = runner.run_panel(config,temporary,selected=['blocked'],execute=True)
            self.assertEqual({case['id'] for case in result['cases']},{'clear','detour','blocked'})
            self.assertTrue((Path(temporary)/'index.html').exists())

    def test_dry_run_and_help_never_import_ros(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = runner.load_config(TOOLS/'config/scene_validation.example.json')
            with patch.object(runner,'run_case',side_effect=AssertionError('must not run')):
                result = runner.run_panel(config,temporary,execute=False)
            self.assertFalse(result['execute'])
            self.assertFalse((Path(temporary)/'report.json').exists())
        result = subprocess.run([sys.executable,'-I','-c',
            'import runpy,sys;runpy.run_path(sys.argv[1]);assert "rclpy" not in sys.modules',
            str(TOOLS/'fishbot_scene_validation.py')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_api_never_accepts_remote_target(self):
        with self.assertRaises(ValueError):
            runner.MissionAPI('http://192.0.2.1:9100')
        self.assertEqual(runner.MissionAPI('http://127.0.0.1:9100').base,'http://127.0.0.1:9100')

    def test_navigation_diagnostics_rate_and_retention_are_bounded(self):
        diagnostic = runner.NavigationDiagnostics()
        for index in range(100):
            wall = index*.1
            for topic in diagnostic.LIMITS:
                if diagnostic.accept(topic,wall):
                    diagnostic.append(topic,index*.01,'map',wall,index*.01,{'sample':index})
        data = diagnostic.snapshot()
        for topic,frames in data['topics'].items():
            self.assertLessEqual(len(frames),diagnostic.LIMITS[topic])
            self.assertGreater(data['statistics'][topic]['rate_skipped'],0)
            self.assertTrue(all(b['steady_time']-a['steady_time']>=.5 for a,b in zip(frames,frames[1:])))
        self.assertEqual(len(data['topics']['/local_costmap/costmap']),10)
        self.assertAlmostEqual(data['topics']['/plan'][-1]['stamp'],.95)

    def test_uncertain_submission_queries_original_id_and_cancels_once_with_timestamp(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = runner.load_config(TOOLS/'config/scene_validation.example.json')
            case = runner.normalized_case({'id':'blocked','expected':'canceled','cancel_after_s':0.},0,config)
            directory = Path(temporary)/'case'
            requests = []
            owner = {'task':None,'canceled':False,'task_queries':0}
            class FakeAPI:
                instance = None
                def request(api, method, path, body=None):
                    requests.append((method,path,body))
                    if path == '/sim-api/runtime':
                        return 200,{'domain':130,'mode':'simulation','instance_id':'runtime-1'},{}
                    mission = {'id':owner['task'],'status':'canceled' if owner['canceled'] else 'running' if owner['task'] else 'idle',
                        'native_goal_id':'e1'*16,'native_status':5 if owner['canceled'] else 2,'cleanup_state':None}
                    if path == '/sim-api/state':
                        return 200,{'ready':True,'domain':130,'mission':mission},{}
                    if path == '/sim-api/mission':
                        owner['task'] = body['mission_id']
                        raise runner.URLError('lost reply after server accepted')
                    if path.startswith('/sim-api/tasks/'):
                        self.assertEqual(path.split('/')[-1],owner['task'])
                        owner['task_queries'] += 1
                        return 200,{'mission':mission},{}
                    if path == '/sim-api/cancel':
                        self.assertEqual(body['mission_id'],owner['task'])
                        self.assertTrue(runner.finite(body['issued_at']))
                        owner['canceled'] = True
                        return 202,{},{}
                    raise AssertionError(path)
            class FakeObserver:
                returncode = None
                def poll(child):
                    return child.returncode
                def send_signal(child, signal):
                    pass
                def wait(child, timeout):
                    child.returncode = 0
            def spawn(*_args,**_kwargs):
                runner.write_json(directory/'observer-ready.json',{'observed':True})
                runner.write_json(directory/'recording.json',self.recording)
                return FakeObserver()
            with patch.object(runner,'MissionAPI',return_value=FakeAPI()), \
                    patch.object(runner.subprocess,'Popen',side_effect=spawn), patch.object(runner.time,'sleep'):
                runner.run_case(case,config,directory)
            self.assertEqual(sum(method=='POST' and path=='/sim-api/mission' for method,path,_ in requests),1)
            self.assertEqual(sum(method=='POST' and path=='/sim-api/cancel' for method,path,_ in requests),1)
            self.assertGreaterEqual(owner['task_queries'],2)


if __name__ == '__main__':
    unittest.main()
