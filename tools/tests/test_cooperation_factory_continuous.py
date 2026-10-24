"""CPU contracts for the original factory adapter; no native-motion claims."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cooperation_factory as factory
from tools.tests import test_cooperation_factory as legacy
from tools.tests import test_cooperation_business as entities_fixture
from tools.tests.test_cooperation_continuous import BusinessBridge


def scenario():
    value = legacy.manifest()
    entities, _, _ = entities_fixture.fixture()
    value.update(entities)
    value['business_entities']['world_id'] = 'configured-world'
    station = value['business_entities']['unload_stations']['line_b']
    station['delivery_pose'] = copy.deepcopy(value['factory_delivery']['destinations'][1]['pose'])
    station['cargo_shelf_slots'] = {
        'cargo_1': {'center_xy_m': [.02, -.22], 'half_size_xy_m': [.028, .058]},
        'cargo_2': {'center_xy_m': [.08, -.22], 'half_size_xy_m': [.028, .058]}}
    value['business_entities']['configuration'] = {
        'budgets_wall_s': {'load_and_delivery': 360, 'unload': 180}}
    bindings = {f'order-{letter}': {'cargo_id': f'cargo_{i+1}', 'pickup_arm_id': 'load',
                                   'unload_station_id': 'line_b'} for i,letter in enumerate(('a','b'))}
    return value, bindings


def frame(sequence=1, *, position=(.7, -2., .1), world='world-a', episode='episode-a', reset=0):
    return {'sequence': sequence, 'stamp': sequence*.02, 'world_session_id': world,
            'episode_id': episode, 'episode_reset': {'count': reset}, 'car_hold': True,
            'car': {'position': list(position), 'quaternion_wxyz': [1.,0.,0.,0.],
                    'speed': 0., 'yaw_rate': 0.}}


def records(*frames):
    return [{'topic': 'physics', 'payload': raw, 'received_wall_time': factory.time.time()} for raw in frames]


class ContinuousFactoryTests(unittest.TestCase):
    def test_explicit_b_b_changes_destinations_but_preserves_original_order_ids(self):
        manifest, bindings = scenario();before = copy.deepcopy(manifest)
        value = factory.reference(manifest, candidate='B/B', continuous_deliveries=bindings)
        self.assertEqual([o['id'] for o in value['orders']], ['order-a','order-b'])
        self.assertEqual([o['destination_id'] for o in value['orders']], ['line_b','line_b'])
        self.assertEqual([o['business_delivery']['cargo_id'] for o in value['orders']], ['cargo_1','cargo_2'])
        self.assertEqual(value['orders'][0]['delivery_pose'], value['orders'][1]['delivery_pose'])
        self.assertEqual(len({o['batch_id'] for o in value['orders']}), 2)
        self.assertEqual(manifest, before)
        self.assertEqual(value['task_timeout_wall_s'], 540.)
        self.assertEqual(value['load_and_delivery_timeout_wall_s'], 360.)
        self.assertEqual(value['delivery_route_budget_wall_s'], 120.)
        self.assertEqual(value['startup_and_cleanup_allowance_wall_s'], 280.)
        self.assertEqual(value['total_timeout_wall_s'], 1360.)

    def test_legacy_budgets_and_distinct_episode_contract_unchanged(self):
        manifest, _ = scenario()
        value = factory.reference(manifest, candidate='legacy')
        self.assertEqual((value['task_timeout_wall_s'],value['total_timeout_wall_s']), (360.,1000.))
        self.assertNotIn('execution_mode', value)
        self.assertEqual([o['destination_id'] for o in value['orders']], ['line_a','line_b'])
        self.assertNotIn('business_delivery',value['orders'][0])

    def test_binding_rejects_missing_duplicate_or_unknown_physical_stock(self):
        manifest, bindings = scenario()
        for changed in ({'order-a': bindings['order-a']},
                        dict(bindings, **{'order-b': bindings['order-a']}),
                        dict(bindings, **{'order-b': dict(bindings['order-b'],cargo_id='missing')}),
                        dict(bindings, **{'order-b': dict(bindings['order-b'],unload_station_id='missing')})):
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                factory.reference(manifest,candidate='bad',continuous_deliveries=changed)
        manifest['business_entities']['unload_stations']['line_b']['delivery_pose']['x'] = 9.
        with self.assertRaises(ValueError):
            factory.reference(manifest,candidate='bad',continuous_deliveries=bindings)

    def test_original_load_budget_is_not_silently_extended(self):
        manifest, bindings = scenario()
        for budget in ({'load_and_delivery': 540,'unload':180},
                       {'load_and_delivery':360,'unload':None},
                       {'load_and_delivery':360,'unload':float('nan')}):
            manifest['business_entities']['configuration']['budgets_wall_s'] = budget
            with self.assertRaises(ValueError):
                factory.reference(manifest,candidate='bad',continuous_deliveries=bindings)

    def test_named_score_is_required_even_if_http_and_primary_alias_succeeded(self):
        manifest, bindings = scenario()
        order = factory.reference(manifest,candidate='B/B',continuous_deliveries=bindings)['orders'][0]
        score = legacy.successful_score(order)
        def report(value):
            return factory.order_report(order,task_id='task-a',episode_id='episode-a',
                terminal={'task':{'status':'succeeded'}},score=value,score_file=Path('/private/score'),elapsed_wall_s=500.)
        self.assertEqual(report(score)['task_verdict'],'failed')
        score['business_delivery_acceptance'] = {'required':True,'passed':True,'attempts':[
            {'task_id':'task-a','business_delivery':bindings['order-a'],'passed':True}]}
        score['original_k_oracle_passed'] = False  # Primary alias is not the named score.
        result = report(score)
        self.assertEqual(result['task_verdict'],'passed')
        self.assertTrue(result['execution']['within_task_budget'])
        score['business_delivery_acceptance']['attempts'][0]['business_delivery'] = bindings['order-b']
        self.assertEqual(report(score)['task_verdict'],'failed')

    def test_transition_requires_original_world_no_reset_and_actual_held_pose(self):
        first=frame(1);second=frame(2)
        proof=factory.continuous_transition(factory.measured_world(first),records(first,second),'world-a','episode-a')
        self.assertTrue(proof['passed'])
        for wrong in (frame(2,reset=1),frame(2,world='other'),frame(2,episode='other'),
                      frame(2,position=(.8,-2.,.1))):
            self.assertFalse(factory.continuous_transition(factory.measured_world(first),
                records(first,wrong),'world-a','episode-a')['passed'])
        # A bounded recent window may not silently skip the previous endpoint.
        self.assertFalse(factory.continuous_transition(factory.measured_world(first),
            records(second),'world-a','episode-a')['passed'])

    def test_monitor_aggregates_reset_evidence_after_ring_eviction(self):
        monitor=factory.ReadOnlyMonitor.__new__(factory.ReadOnlyMonitor)
        monitor.lock=threading.Lock()
        monitor.continuity={'sample_count':0,'worlds':set(),'episodes':set(),
                            'reset_count_zero':True,'strict_source_progress':True,'last':None}
        from collections import deque
        monitor.tail=SimpleNamespace(records=deque(maxlen=1))
        for value in (frame(1),frame(2,reset=1),frame(3)):
            monitor.record('physics',SimpleNamespace(data=json.dumps(value)))
        self.assertEqual(len(monitor.tail.records),1)
        proof=monitor.continuity_proof('world-a','episode-a')
        self.assertEqual(proof['sample_count'],3)
        self.assertFalse(proof['reset_count_zero'])
        self.assertFalse(proof['passed'])

    def test_cli_dry_run_accepts_order_mapping_without_ros_or_output(self):
        manifest, bindings=scenario()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'manifest.json';mapping=root/'bindings.json'
            path.write_text(json.dumps(manifest));mapping.write_text(json.dumps(bindings))
            stream=io.StringIO()
            with patch.object(factory,'loaded_code_reference',return_value={}),contextlib.redirect_stdout(stream):
                code=factory.main(['run','--manifest',str(path),'--output',str(root/'new'),
                    '--continuous-deliveries',str(mapping),'--dry-run'])
            self.assertEqual(code,0)
            self.assertFalse((root/'new').exists())
            value=json.loads(stream.getvalue())
            self.assertFalse(value['ROS_initialized'])
            self.assertEqual(value['declaration']['execution_mode'],'continuous')

    def test_summary_requires_same_episode_and_independent_no_reset_evidence(self):
        result={'declaration':{'execution_mode':'continuous','orders':[{'id':'a'},{'id':'b'}]},
            'orders':[{'id':name,'task_id':'task-'+name,'episode_id':'same','batch_id':'batch-'+name,
                       'carrying_nav_uuid':'native-'+name,'task_verdict':'passed',
                       'execution':{'within_task_budget':True}} for name in ('a','b')],
            'errors':[],'execution':{key:True for key in ('cleanup_complete','owned_launch_stopped',
                'owned_port_closed','protected_instances_unchanged','within_total_budget')}}
        result['execution'].update(continuous_physics={'passed':True},mutation_posts={'reset':0},
                                   continuous_transitions=[{'passed':True}])
        self.assertTrue(factory.summarize(result)['passed'])
        for field,replacement in (('continuous_physics',{'passed':False}),('mutation_posts',{'reset':1}),
                                  ('continuous_transitions',[])):
            broken=copy.deepcopy(result);broken['execution'][field]=replacement
            self.assertFalse(factory.summarize(broken)['passed'])
        broken=copy.deepcopy(result);broken['orders'][1]['episode_id']='new'
        self.assertFalse(factory.summarize(broken)['passed'])


class ContinuousRunContractTests(unittest.TestCase):
    def test_original_runner_dispatches_two_bound_orders_without_reset(self):
        """Mock IO, retain original Workflow and adapter control flow; not physics."""
        manifest,bindings=scenario();decl=factory.reference(manifest,candidate='fixture',continuous_deliveries=bindings)
        source=BusinessBridge();source.value.update(domain=166,scene_profile=decl['scene_profile'],native_lifecycle={})
        processes=[];active={};monitors=[]
        class Bridge:
            def __init__(self, endpoint, before_post):self.endpoint=endpoint;self.before_post=before_post
            def state(self):
                if source.value['task']['status']=='running':source.complete()
                return source.state()
            def post(self,kind,body):
                self.before_post(kind,body)
                return source.post(kind,body)
        class Monitor:
            def __init__(self):self.sequence=0;monitors.append(self)
            def records(self):
                self.sequence+=1
                return records(frame(self.sequence,world=source.world,episode=source.value['episode_id']))
            def quiet(self,episode):return {'source_stamp':self.sequence*.02}
            def close(self):pass
            def continuity_proof(self,world,episode):return {'passed':world==source.world and episode==source.value['episode_id']}
        class Tail:
            def __init__(self,path):self.records=[{'topic':'physics'},{'topic':'publisher_inventory'}]
            def refresh(self):pass
            def native(self):return {}
            def quiet_proof(self,**kwargs):return {'source_stamp':1.}
        class Process:
            def __init__(self,command,**kwargs):
                self.command=command;self.returncode=None;self.pid=1234+len(processes);processes.append(self)
                if '--output' in command and 'cooperation_geometry_check.py' in ' '.join(command):
                    Path(command[command.index('--output')+1]).write_text('{"passed":true}');self.returncode=0
            def poll(self):return self.returncode
            def wait(self,timeout=None):self.returncode=0;return 0
        def finish(process,timeout):
            task=source.value['task'];order=next(o for o in decl['orders'] if o['business_delivery']==task['business_delivery'])
            score=legacy.successful_score(order)
            attempt=score['task_delivery_acceptance']['attempts'][0]
            attempt.update(task_id=task['id'],episode_id=source.value['episode_id'],carrying_nav_uuid='native-'+order['id'])
            score['business_delivery_acceptance']={'required':True,'passed':True,'attempts':[
                {'task_id':task['id'],'business_delivery':task['business_delivery'],'passed':True}]}
            folder=Path(process.command[process.command.index('--output')+1]);folder.mkdir()
            (folder/'score-fixture.json').write_text(json.dumps(score));process.returncode=0;return 0
        def wait(predicate,*args,**kwargs):
            # Cleanup dwell needs source progress, so return consecutive endpoint measurements.
            for _ in range(100):
                value=predicate()
                if value:return value
            raise RuntimeError(kwargs.get('description','fixture wait failed'))
        def cleanup(state,native,task_id,episode,quiet,**kwargs):
            active['stamp']=active.get('stamp',0.)+1.1
            return {'state':state,'proof':{'source_stamp':active['stamp']}}
        # The monitor ring below includes the previous endpoint, as the real bounded ring does.
        original_records=Monitor.records
        def accumulated(self):
            next_records=original_records(self)
            self.saved=getattr(self,'saved',[])+next_records
            return self.saved
        Monitor.records=accumulated
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);manifest_path=root/'scene.json';manifest_path.write_text(json.dumps(manifest))
            args=SimpleNamespace(output=root/'run',port=9116,domain=166,planning_python=Path('/python'),
                manifest=manifest_path,scope='transport',isolated_runtime=True,publication_mode='source')
            with contextlib.ExitStack() as stack:
                for name,replacement in {'MarkedBridge':Bridge,'ReadOnlyMonitor':Monitor,'EvidenceTail':Tail,
                    'ensure_port_available':Mock(),'loaded_code_reference':lambda:{'selected_source_text':{}},
                    'protected_snapshot':lambda units:{},'lifecycle_active':lambda _:True,'wait_until':wait,
                    'cleanup_proof':cleanup,'signal_observer_once':Mock(),'finish_observer':finish,
                    'stop_owned_launch':lambda p,r:(setattr(p,'returncode',0) or True),
                    'stop_non_motion_child':lambda *args:[]}.items():
                    stack.enter_context(patch.object(factory,name,replacement))
                stack.enter_context(patch.object(factory.subprocess,'Popen',Process))
                stack.enter_context(patch.dict(sys.modules,{'fishbot_simulation_suite':SimpleNamespace(domain_is_empty=Mock())}))
                result=factory.run(args,manifest,decl)
            self.assertTrue(result['passed'],result['errors'])
            self.assertEqual([kind for kind,_ in source.calls],['start','start'])
            self.assertEqual([body['business_delivery'] for _,body in source.calls],list(bindings.values()))
            self.assertEqual(len(result['execution']['continuous_transitions']),1)
            oracle_commands=[p.command for p in processes if 'oracle' in p.command]
            self.assertEqual(len(oracle_commands),2)
            self.assertTrue(all('--business-manifest' in cmd for cmd in oracle_commands))
            for index,binding in enumerate(bindings.values(),1):
                markers=json.loads((root/'run'/f'order-{index}'/'markers.json').read_text())['events']
                self.assertEqual(next(e for e in markers if e['kind']=='full_started')['business_delivery'],binding)


if __name__=='__main__':unittest.main()
