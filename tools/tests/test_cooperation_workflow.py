"""CPU-only contract fixtures. No ROS, physical plant, or network listener."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cooperation_core import request_identity, reset_request_identity
from cooperation_workflow import ContractError, LocalBridge, TransportUnknown, Workflow, main, read_json, run_workflow, scene_template_jobs


def uid():
    return str(uuid.uuid4())


class Bridge:
    endpoint = 'http://127.0.0.1:9086'

    def __init__(self):
        self.calls = []
        self.gets = []
        self.lose = set()
        self.reject = set()
        self.records = {}
        self.value = {'mode': 'mujoco', 'source': {'scene_sha': 'a'*64},
                      'episode_id': uid(), 'ready': True,
                      'task': {'id': None, 'status': 'idle'}, 'history': [],
                      'reset': {'available': True, 'pending': False}}

    def state(self):
        self.gets.append(('state',))
        return copy.deepcopy(self.value)

    def reset(self, request_id):
        self.gets.append(('reset', request_id))
        if request_id not in self.records:
            raise TransportUnknown('missing original reset ID')
        return copy.deepcopy(self.records[request_id])

    def post(self, kind, body):
        self.calls.append((kind, copy.deepcopy(body)))
        # Use the actual baseline's strict input contract, not a permissive fake.
        if kind == 'start':
            request_identity(body, episode_id=self.value['episode_id'], now=body['issued_at'])
        elif kind == 'cancel':
            request_identity(body, cancel=True, now=body['issued_at'])
        else:
            reset_request_identity(body, now=body['issued_at'])
        if kind in self.reject:
            return {'error': 'fixture rejection', 'outcome': 'rejected'}
        if kind == 'start':
            self.value['task'] = {'id': body['task_id'], 'status': 'running'}
            if 'delivery_pose' in body:
                self.value['task']['delivery_pose'] = copy.deepcopy(body['delivery_pose'])
            self.value['ready'] = False
            self.value['reset']['available'] = False
            receipt = {'task_id': body['task_id'], 'task': self.value['task']}
        elif kind == 'cancel':
            if body['task_id'] != self.value['task']['id']:
                raise AssertionError('canceled another task')
            self.value['task']['status'] = 'canceling'
            receipt = {'task_id': body['task_id'], 'task': self.value['task']}
        else:
            self.records[body['request_id']] = {'request_id': body['request_id'],
                'episode_id': body['episode_id'], 'new_episode_id': None, 'status': 'pending'}
            self.value['reset']['pending'] = True
            self.value['reset']['available'] = False
            receipt = self.records[body['request_id']]
        if kind in self.lose:
            raise TransportUnknown('lost '+kind+' receipt')
        return copy.deepcopy(receipt)

    def terminal(self, status='succeeded', quiet=True):
        self.value['task']['status'] = status
        self.value['ready'] = False
        self.value['reset'].update(available=quiet, pending=False)

    def acknowledge_reset(self, request_id=None):
        request_id = request_id or next(reversed(self.records))
        record = self.records[request_id]
        self.value['history'].append({'episode_id': self.value['episode_id'],
                                      'task': copy.deepcopy(self.value['task'])})
        self.value.update(episode_id=uid(), ready=True, task={'id': None, 'status': 'idle'})
        self.value['reset'].update(available=True, pending=False)
        record.update(status='succeeded', new_episode_id=self.value['episode_id'])


class SceneTemplateTest(unittest.TestCase):
    def test_selected_three_batch_template_creates_fresh_ids_and_aab_targets(self):
        profile={'schema':1,'vehicle':'jackal_j100','sensors':'lidar3d','task':'three_batch_transport'}
        manifest={'scene_profile':profile,'delivery_pose':{'x':1.,'y':2.,'yaw':.3}}
        batches,goals,selected=scene_template_jobs(manifest)
        self.assertEqual(len(set(batches)),3)
        self.assertEqual(selected,profile)
        self.assertEqual([goals[b]['x'] for b in batches],[1.,1.,1.7])
        goals[batches[0]]['x']=9
        self.assertEqual(goals[batches[1]]['x'],1.)
        self.assertTrue(set(batches).isdisjoint(scene_template_jobs(manifest)[0]))
        self.assertEqual(len(scene_template_jobs({})[0]),1)

    def test_from_scene_cli_checks_actual_profile_without_dispatching(self):
        profile={'schema':1,'vehicle':'jackal_j100','sensors':'planar','task':'three_batch_transport'}
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);manifest=folder/'scene.json'
            manifest.write_text(json.dumps({'scene_profile':profile}))
            bridge=Bridge();bridge.value['scene_profile']=profile
            ledger=folder/'workflow.json'
            with patch('cooperation_workflow.LocalBridge',return_value=bridge),patch('sys.stdout',io.StringIO()):
                result=main(['--ledger',str(ledger),'init','--from-scene',str(manifest)])
            self.assertEqual(result,0)
            self.assertEqual(len(read_json(ledger)['jobs']),3)
            self.assertEqual(bridge.calls,[])
            bridge.value['scene_profile']={**profile,'vehicle':'fishbot'}
            other=folder/'other.json'
            with patch('cooperation_workflow.LocalBridge',return_value=bridge),patch('sys.stdout',io.StringIO()):
                result=main(['--ledger',str(other),'init','--from-scene',str(manifest)])
            self.assertEqual(result,2);self.assertFalse(other.exists())
            self.assertEqual(bridge.calls,[])

    def test_nondefault_scene_template_dispatches_frozen_aab_after_reopen_and_reset(self):
        profile={'schema':1,'vehicle':'jackal_j100','sensors':'lidar3d','task':'three_batch_transport'}
        first={'x':1.25,'y':-1.75,'yaw':.4}
        expected=[first,first,{**first,'x':1.95}]
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);manifest=folder/'scene.json';ledger=folder/'workflow.json'
            manifest.write_text(json.dumps({'scene_profile':profile,'delivery_pose':first}))
            bridge=Bridge();bridge.value['scene_profile']=profile
            with patch('cooperation_workflow.LocalBridge',return_value=bridge),patch('sys.stdout',io.StringIO()):
                self.assertEqual(main(['--ledger',str(ledger),'init','--from-scene',str(manifest)]),0)
            batches=[job['batch_id'] for job in read_json(ledger)['jobs']]
            # Subsequent edits cannot replace destinations frozen into the jobs.
            manifest.write_text(json.dumps({'scene_profile':profile,'delivery_pose':{'x':99,'y':99,'yaw':0}}))
            for index,batch in enumerate(batches):
                with Workflow(ledger,bridge) as workflow:
                    self.assertEqual(workflow.data['index'],index)
                    workflow.event({'event_id':uid(),'machine_id':'laundry-machine-1',
                                    'batch_id':batch,'version':index+1,'ready':True})
                    workflow.dispatch()
                    attempt=workflow.data['jobs'][index]['attempts'][-1]
                    self.assertEqual(attempt['delivery_pose'],expected[index])
                    original=attempt['task_id']
                with Workflow(ledger,bridge) as workflow:
                    before=len(bridge.calls)
                    self.assertEqual(workflow.tick()['status'],'active')
                    self.assertEqual(workflow.data['operation']['task_id'],original)
                    self.assertEqual(len(bridge.calls),before)
                    bridge.terminal()
                    self.assertEqual(workflow.tick()['status'],'succeeded' if index==2 else 'waiting_reset')
                    if index<2:
                        workflow.reset()
                if index<2:
                    # Reopen while the original reset is pending; never resend it.
                    with Workflow(ledger,bridge) as workflow:
                        before=len(bridge.calls)
                        workflow.tick()
                        self.assertEqual(len(bridge.calls),before)
                        bridge.acknowledge_reset()
                        self.assertEqual(workflow.tick()['status'],'waiting_ready')
            starts=[body for kind,body in bridge.calls if kind=='start']
            self.assertEqual([body['delivery_pose'] for body in starts],expected)
            self.assertEqual(len({body['task_id'] for body in starts}),3)
            self.assertEqual(len({body['episode_id'] for body in starts}),3)
            self.assertEqual([kind for kind,_ in bridge.calls],['start','reset','start','reset','start'])
            final=read_json(ledger)
            self.assertEqual(final['status'],'succeeded')
            self.assertEqual([job['delivery_pose'] for job in final['jobs']],expected)
            self.assertEqual([len(job['attempts']) for job in final['jobs']],[1,1,1])


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'workflow.json'
        self.bridge = Bridge()
        self.batches = [uid(), uid()]
        with self.open() as workflow:
            workflow.create(self.batches)

    def tearDown(self):
        self.temp.cleanup()

    def open(self):
        return Workflow(self.path, self.bridge, clock=lambda: 1700000000.)

    def ready(self, workflow, version=1, batch=None, ready=True, event_id=None):
        event = {'event_id': event_id or uid(), 'batch_id': batch or self.batches[workflow.data['index']],
                 'machine_id': 'laundry-machine-1', 'version': version, 'ready': ready}
        workflow.event(event)
        return event

    def start(self, workflow):
        self.ready(workflow)
        workflow.dispatch()
        return workflow.data['jobs'][0]['attempts'][0]['task_id']

    def create_jobs(self, count, targets=None):
        self.path = self.path.parent/('workflow-'+uid()+'.json')
        self.batches = [uid() for _ in range(count)]
        mapping = targets(self.batches) if targets else None
        with self.open() as workflow:
            workflow.create(self.batches, delivery_poses=mapping)
        return mapping

    def test_three_jobs_preserve_optional_destinations_across_resets_and_restart(self):
        target = {'x':1.25, 'y':-1.75, 'yaw':.4}
        self.create_jobs(3, lambda batches: {batches[1]:target})
        task_ids = []
        for index in range(3):
            with self.open() as workflow:
                self.assertEqual(workflow.data['index'],index)
                self.ready(workflow,version=index+1)
                workflow.dispatch()
                attempt = workflow.data['jobs'][index]['attempts'][0]
                task_ids.append(attempt['task_id'])
                if index == 1:
                    self.assertEqual(attempt['delivery_pose'],target)
                    self.assertEqual(attempt['dispatch']['body']['delivery_pose'],target)
                else:
                    self.assertNotIn('delivery_pose',attempt)
                    self.assertEqual(set(attempt['dispatch']['body']),{'task_id','episode_id','issued_at'})
            with self.open() as workflow:
                self.assertEqual(workflow.tick()['status'],'active')
                self.bridge.terminal()
                self.assertEqual(workflow.tick()['status'],'succeeded' if index==2 else 'waiting_reset')
                if index < 2:
                    workflow.reset()
                    self.bridge.acknowledge_reset()
                    self.assertEqual(workflow.tick()['status'],'waiting_ready')
        self.assertEqual(len(set(task_ids)),3)
        self.assertEqual([kind for kind,_ in self.bridge.calls],['start','reset','start','reset','start'])
        self.assertEqual([job['status'] for job in read_json(self.path)['jobs']],['succeeded']*3)

    def test_single_job_finishes_without_an_extra_reset(self):
        self.create_jobs(1)
        with self.open() as workflow:
            self.start(workflow)
            self.bridge.terminal()
            self.assertEqual(workflow.tick()['status'],'succeeded')
            self.assertEqual(workflow.data['index'],0)
        self.assertEqual([kind for kind,_ in self.bridge.calls],['start'])

    def test_delivery_pose_survives_lost_receipt_cancel_restart_and_explicit_recovery(self):
        target = {'x':1.25, 'y':-1.75, 'yaw':7.0}
        provided = self.create_jobs(1, lambda batches: {batches[0]:copy.deepcopy(target)})
        provided[self.batches[0]]['x'] = 99
        self.bridge.lose.update(('start','cancel'))
        with self.open() as workflow:
            original = self.start(workflow)
            self.assertEqual(workflow.data['status'],'unknown')
            self.assertEqual(workflow.data['jobs'][0]['attempts'][0]['delivery_pose'],target)
        with self.open() as workflow:
            self.assertEqual(workflow.tick()['status'],'active')
            workflow.cancel()
        with self.open() as workflow:
            workflow.cancel()
            self.assertEqual([kind for kind,_ in self.bridge.calls],['start','cancel'])
            self.assertEqual(self.bridge.calls[-1][1]['task_id'],original)
            self.bridge.terminal('canceled')
            self.assertEqual(workflow.tick()['status'],'fault')
            workflow.reset(recover=True)
            self.bridge.acknowledge_reset()
            self.assertEqual(workflow.tick()['status'],'waiting_ready')
            self.ready(workflow,version=2)
            self.bridge.lose.clear()
            workflow.dispatch()
            attempts = workflow.data['jobs'][0]['attempts']
            self.assertEqual(len(attempts),2)
            self.assertEqual(attempts[0]['status'],'canceled')
            self.assertNotEqual(attempts[1]['task_id'],original)
            self.assertTrue(all(a['delivery_pose']==target and a['dispatch']['body']['delivery_pose']==target for a in attempts))
        self.assertEqual([kind for kind,_ in self.bridge.calls],['start','cancel','reset','start'])

    def test_same_task_identity_with_changed_or_missing_destination_remains_unknown(self):
        target = {'x':1.,'y':-1.,'yaw':.5}
        self.create_jobs(1,lambda batches:{batches[0]:target})
        with self.open() as workflow:
            original = self.start(workflow)
        original_task = copy.deepcopy(self.bridge.value['task'])
        for changed in ({'x':2.,'y':-1.,'yaw':.5},None):
            self.bridge.value['task'] = copy.deepcopy(original_task)
            if changed is None:
                self.bridge.value['task'].pop('delivery_pose')
            else:
                self.bridge.value['task']['delivery_pose'] = changed
            with self.open() as workflow:
                self.assertEqual(workflow.tick()['status'],'unknown')
                self.assertEqual(workflow.data['operation']['task_id'],original)
                with self.assertRaises(ContractError):
                    workflow.dispatch()
        self.assertEqual([kind for kind,_ in self.bridge.calls],['start'])
        self.bridge.value['task'] = original_task
        with self.open() as workflow:
            self.assertEqual(workflow.tick()['status'],'active')

    def test_destination_content_is_bound_to_job_and_attempt_on_restart(self):
        target = {'x':1.,'y':-1.,'yaw':.5}
        self.create_jobs(1,lambda batches:{batches[0]:target})
        with self.open() as workflow:
            self.start(workflow)
        saved = read_json(self.path)
        for change in ('job','attempt','body'):
            value = copy.deepcopy(saved)
            job = value['jobs'][0]
            record = job if change=='job' else job['attempts'][0] if change=='attempt' else job['attempts'][0]['dispatch']['body']
            record['delivery_pose']['x'] = 2.
            self.path.write_text(json.dumps(value))
            with self.assertRaises(ContractError):
                with self.open():
                    pass
        self.assertEqual([kind for kind,_ in self.bridge.calls],['start'])

    def test_cli_accepts_ordered_batch_list_and_editable_destination_mapping(self):
        path = self.path.parent/'cli-three.json'
        batches = [uid() for _ in range(3)]
        target = {'x':1.,'y':-1.,'yaw':.5}
        mapping = self.path.parent/'destinations.json'
        mapping.write_text(json.dumps({batches[1]:target}))
        with patch('cooperation_workflow.LocalBridge',return_value=self.bridge), patch('builtins.print') as output:
            self.assertEqual(main(['--ledger',str(path),'init','--batches',*batches,'--delivery-poses',str(mapping)]),0)
            result = json.loads(output.call_args.args[0])
        self.assertEqual([job['batch_id'] for job in result['jobs']],batches)
        self.assertEqual(result['jobs'][1]['delivery_pose'],target)
        self.assertNotIn('delivery_pose',result['jobs'][0])
        self.assertEqual(self.bridge.calls,[])

    def test_legacy_repeatable_batch_cli_keeps_its_original_payload(self):
        path = self.path.parent/'cli-legacy.json'
        with patch('cooperation_workflow.LocalBridge',return_value=self.bridge), patch('builtins.print') as output:
            self.assertEqual(main(['--ledger',str(path),'init','--batch',self.batches[0],
                                   '--batch',self.batches[1]]),0)
            result = json.loads(output.call_args.args[0])
        self.assertEqual([job['batch_id'] for job in result['jobs']],self.batches)
        self.assertTrue(all('delivery_pose' not in job for job in result['jobs']))

    def test_invalid_destinations_and_empty_or_duplicate_batches_never_call_bridge(self):
        gets = list(self.bridge.gets)
        invalid = [([],None),([self.batches[0]]*2,None),
                   (self.batches,{uid():{'x':0,'y':0,'yaw':0}}),
                   (self.batches,{self.batches[0]:{'x':True,'y':0,'yaw':0}}),
                   (self.batches,{self.batches[0]:{'x':float('inf'),'y':0,'yaw':0}}),
                   (self.batches,{self.batches[0]:{'x':0,'y':0}})]
        for batches,targets in invalid:
            with Workflow(self.path.parent/(uid()+'.json'),self.bridge) as workflow:
                with self.assertRaises(ContractError):
                    workflow.create(batches,delivery_poses=targets)
        self.assertEqual(self.bridge.gets,gets)
        self.assertEqual(self.bridge.calls,[])

    def test_delayed_ready_and_exactly_two_jobs(self):
        with self.open() as workflow:
            for unused in range(3):
                self.assertEqual(workflow.tick()['status'], 'waiting_ready')
                with self.assertRaises(ContractError):
                    workflow.dispatch()
            self.assertEqual(self.bridge.calls, [])
            first = self.start(workflow)
            self.bridge.terminal(quiet=False)
            self.assertEqual(workflow.tick()['status'], 'waiting_quiet')
            with self.assertRaises(ContractError):
                workflow.reset()
            self.bridge.terminal()
            self.assertEqual(workflow.tick()['status'], 'waiting_reset')
            workflow.reset()
        with self.open() as workflow:
            self.assertEqual(workflow.tick()['status'], 'reset_pending')
            self.bridge.acknowledge_reset()
            value = workflow.tick()
            self.assertEqual(value['status'], 'waiting_ready')
            self.assertEqual(value['index'], 1)
            with self.assertRaises(ContractError):
                workflow.dispatch()
            self.ready(workflow, version=2)
            workflow.dispatch()
            second = workflow.data['jobs'][1]['attempts'][0]['task_id']
            self.assertNotEqual(first, second)
            self.bridge.terminal()
            self.assertEqual(workflow.tick()['status'], 'succeeded')
            with self.assertRaises(ContractError):
                workflow.dispatch()
            self.assertEqual([x[0] for x in self.bridge.calls], ['start', 'reset', 'start'])
            self.assertNotEqual(workflow.data['jobs'][0]['attempts'][0]['episode_id'],
                                workflow.data['jobs'][1]['attempts'][0]['episode_id'])
            self.assertIsNone(workflow.data['machines']['laundry-machine-1']['occupant'])

    def test_duplicate_and_out_of_order_event_preserve_ledger(self):
        with self.open() as workflow:
            event = self.ready(workflow)
            original = self.path.read_bytes()
            workflow.event(event)
            self.assertEqual(original, self.path.read_bytes())
            for invalid in (dict(event, ready=False), dict(event, event_id=uid()),
                            dict(event, event_id=uid(), version=3),
                            dict(event, event_id=uid(), version=True),
                            dict(event, event_id=uid(), batch_id=self.batches[1]),
                            dict(event, event_id=uid(), machine_id='other')):
                with self.assertRaises(ContractError):
                    workflow.event(invalid)
                self.assertEqual(original, self.path.read_bytes())
            workflow.dispatch()
            with self.assertRaises(ContractError):
                self.ready(workflow, version=2, batch=self.batches[1])
            workflow.event(event)  # Idempotent old observation even while occupied.
            self.assertEqual(len(self.bridge.calls), 1)

    def test_false_ready_requires_new_version(self):
        with self.open() as workflow:
            self.ready(workflow, ready=False)
            with self.assertRaises(ContractError):
                workflow.dispatch()
            self.ready(workflow, version=2)
            workflow.dispatch()
            self.assertEqual(len(self.bridge.calls), 1)

    def test_lost_start_receipt_restart_queries_original_id(self):
        self.bridge.lose.add('start')
        with self.open() as workflow:
            original = self.start(workflow)
            self.assertEqual(workflow.data['jobs'][0]['attempts'][0]['dispatch']['outcome'], 'unknown')
            self.assertEqual(workflow.data['status'], 'unknown')
        with self.open() as workflow:
            self.assertEqual(workflow.tick()['status'], 'active')
            self.assertEqual(workflow.data['operation']['task_id'], original)
            with self.assertRaises(ContractError):
                workflow.dispatch()
        self.assertEqual(len(self.bridge.calls), 1)

    def test_crash_after_intent_before_post_never_sends_on_restart(self):
        with self.open() as workflow:
            self.ready(workflow)
            with patch.object(workflow, '_post', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    workflow.dispatch()
        self.assertEqual(self.bridge.calls, [])
        with self.open() as workflow:
            self.assertEqual(workflow.tick()['status'], 'unknown')
            with self.assertRaises(ContractError):
                workflow.dispatch()
            with self.assertRaises(ContractError):
                workflow.reset(recover=True)
        self.assertEqual(self.bridge.calls, [])

    def test_durable_intent_exists_when_post_begins(self):
        post = self.bridge.post
        observations = []
        def checked(kind, body):
            ledger = read_json(self.path)
            self.assertEqual(ledger['operation']['task_id'], body['task_id'])
            self.assertEqual(ledger['jobs'][0]['attempts'][0]['dispatch']['outcome'], 'attempted')
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
            observations.append(kind)
            return post(kind, body)
        with patch.object(self.bridge, 'post', side_effect=checked):
            with self.open() as workflow:
                self.start(workflow)
        self.assertEqual(observations, ['start'])

    def test_fsync_failure_does_not_send(self):
        with self.open() as workflow:
            self.ready(workflow)
            with patch('cooperation_workflow.os.fsync', side_effect=OSError('sync failed')):
                with self.assertRaises(OSError):
                    workflow.dispatch()
        self.assertEqual(self.bridge.calls, [])
        with self.open() as workflow:
            self.assertEqual(workflow.tick()['status'], 'unknown')
            with self.assertRaises(ContractError):
                workflow.dispatch()

    def test_crash_during_post_after_acceptance_reconciles_without_replay(self):
        post = self.bridge.post
        def accepted_then_crash(kind, body):
            post(kind, body)
            raise KeyboardInterrupt
        with self.open() as workflow:
            self.ready(workflow)
            with patch.object(self.bridge, 'post', side_effect=accepted_then_crash):
                with self.assertRaises(KeyboardInterrupt):
                    workflow.dispatch()
        with self.open() as workflow:
            self.assertEqual(workflow.tick()['status'], 'active')
        self.assertEqual(len(self.bridge.calls), 1)

    def test_missing_original_id_never_follows_another_task(self):
        with self.open() as workflow:
            original = self.start(workflow)
            self.bridge.value['task'] = {'id': uid(), 'status': 'succeeded'}
            self.bridge.value['reset']['available'] = True
            self.assertEqual(workflow.tick()['status'], 'unknown')
            self.assertIn('absent', workflow.data['reason'])
            with self.assertRaises(ContractError):
                workflow.reset(recover=True)
            self.assertEqual(workflow.data['operation']['task_id'], original)
            self.assertEqual(len(self.bridge.calls), 1)

    def test_conflicting_history_and_episode_fail_closed(self):
        with self.open() as workflow:
            self.start(workflow)
            original = copy.deepcopy(self.bridge.value)
            self.bridge.value['history'] = [{'episode_id': original['episode_id'],
                'task': dict(original['task'], status='succeeded')}]
            self.assertEqual(workflow.tick()['status'], 'unknown')
            self.bridge.value = copy.deepcopy(original)
            self.bridge.value['episode_id'] = uid()
            self.assertEqual(workflow.tick()['status'], 'unknown')
            self.assertEqual(len(self.bridge.calls), 1)

    def test_unknown_task_blocks_recovery_reset_and_cancel(self):
        with self.open() as workflow:
            self.start(workflow)
            self.bridge.value['task']['status'] = 'unknown'
            self.bridge.value['reset']['available'] = True
            self.assertEqual(workflow.tick()['status'], 'unknown')
            for action in (workflow.dispatch, workflow.cancel, workflow.reset,
                           lambda: workflow.reset(recover=True)):
                with self.assertRaises(ContractError):
                    action()
            self.assertEqual(len(self.bridge.calls), 1)

    def test_lost_cancel_and_restart_retains_uuid_and_failure(self):
        self.bridge.lose.add('cancel')
        with self.open() as workflow:
            original = self.start(workflow)
            workflow.cancel()
            self.assertEqual(workflow.data['jobs'][0]['attempts'][0]['cancel']['outcome'], 'unknown')
        with self.open() as workflow:
            workflow.cancel()
            self.assertEqual([x[0] for x in self.bridge.calls], ['start', 'cancel'])
            self.assertEqual(self.bridge.calls[-1][1]['task_id'], original)
            self.bridge.terminal('canceled', quiet=False)
            self.assertEqual(workflow.tick()['status'], 'waiting_quiet')
            with self.assertRaises(ContractError):
                workflow.reset(recover=True)
            self.bridge.terminal('canceled')
            self.assertEqual(workflow.tick()['status'], 'fault')
            workflow.reset(recover=True)
            self.bridge.acknowledge_reset()
            self.assertEqual(workflow.tick()['status'], 'waiting_ready')
            with self.assertRaises(ContractError):
                workflow.dispatch()  # Old consumed readiness cannot authorize a retry.
            self.ready(workflow, version=2)
            workflow.dispatch()
            attempts = workflow.data['jobs'][0]['attempts']
            self.assertEqual(len(attempts), 2)
            self.assertEqual(attempts[0]['status'], 'canceled')
            self.assertNotEqual(attempts[1]['task_id'], original)
            self.assertEqual(workflow.data['index'], 0)

    def test_failed_task_requires_explicit_recovery(self):
        with self.open() as workflow:
            self.start(workflow)
            self.bridge.terminal('failed')
            self.assertEqual(workflow.tick()['status'], 'fault')
            with self.assertRaises(ContractError):
                workflow.reset()
            with self.assertRaises(ContractError):
                workflow.dispatch()
            workflow.reset(recover=True)
            self.assertEqual(workflow.data['operation']['purpose'], 'retry')

    def test_pending_reset_keeps_scene_identity_while_physics_is_unavailable(self):
        with self.open() as workflow:
            self.start(workflow)
            self.bridge.terminal()
            workflow.reset()
            request_id = workflow.data['operation']['request_id']
            self.bridge.value.update(ready=False, physics=None)
            self.bridge.value['source'] = {'scene_sha':'a'*64,
                'origin':'manifest_world_xml','observed':False}
            self.assertEqual(workflow.tick()['status'], 'reset_pending')
            self.assertEqual(workflow.data['operation']['request_id'], request_id)
            self.assertEqual([call[0] for call in self.bridge.calls], ['start', 'reset'])
            self.bridge.value['source']['scene_sha'] = 'b'*64
            self.assertEqual(workflow.tick()['status'], 'unknown')
            self.assertEqual([call[0] for call in self.bridge.calls], ['start', 'reset'])

    def test_lost_reset_receipt_and_restart_use_same_ack_id(self):
        self.bridge.lose.add('reset')
        with self.open() as workflow:
            self.start(workflow)
            self.bridge.terminal()
            workflow.reset()
            request_id = workflow.data['operation']['request_id']
        with self.open() as workflow:
            for unused in range(3):
                self.assertEqual(workflow.tick()['status'], 'reset_pending')
            with self.assertRaises(ContractError):
                workflow.reset()
            self.bridge.acknowledge_reset(request_id)
            self.assertEqual(workflow.tick()['status'], 'waiting_ready')
            self.assertEqual(workflow.data['resets'][0]['ack']['request_id'], request_id)
        self.assertEqual([kind for kind, body in self.bridge.calls], ['start', 'reset'])
        self.assertTrue(all(x[1] == request_id for x in self.bridge.gets if x[0] == 'reset'))

    def test_wrong_reset_ack_new_episode_and_missing_history_block(self):
        with self.open() as workflow:
            self.start(workflow)
            self.bridge.terminal()
            workflow.reset()
            request_id = workflow.data['operation']['request_id']
            self.bridge.acknowledge_reset()
            original = copy.deepcopy(self.bridge.value)
            ack = copy.deepcopy(self.bridge.records[request_id])
            for field, value in (('request_id', uid()), ('episode_id', uid()),
                                 ('new_episode_id', workflow.data['episode_id'])):
                self.bridge.records[request_id] = dict(ack, **{field: value})
                self.assertEqual(workflow.tick()['status'], 'unknown')
                with self.assertRaises(ContractError):
                    workflow.dispatch()
            self.bridge.records[request_id] = ack
            self.bridge.value['history'] = []
            self.assertEqual(workflow.tick()['status'], 'unknown')
            self.bridge.value = original
            self.assertEqual(workflow.tick()['status'], 'waiting_ready')
            self.assertEqual(len(self.bridge.calls), 2)

    def test_scene_changed_blocks_submission(self):
        with self.open() as workflow:
            self.ready(workflow)
            self.bridge.value['source']['scene_sha'] = 'b'*64
            with self.assertRaises(ContractError):
                workflow.dispatch()
        self.assertEqual(self.bridge.calls, [])

    def test_missing_physics_source_on_restart_persists_unknown(self):
        with self.open() as workflow:
            original = self.start(workflow)
        state = copy.deepcopy(self.bridge.value)
        self.bridge.value.update(source=None, ready=False, reason='waiting for physical feedback')
        with self.open() as workflow:
            self.assertEqual(workflow.tick()['status'], 'unknown')
            self.assertEqual(read_json(self.path)['status'], 'unknown')
            self.assertEqual(workflow.data['operation']['task_id'], original)
            with self.assertRaises(ContractError):
                workflow.dispatch()
        self.bridge.value = state
        with self.open() as workflow:
            self.assertEqual(workflow.tick()['status'], 'active')
        self.assertEqual(len(self.bridge.calls), 1)

    def test_create_without_physics_source_is_an_explicit_contract_error(self):
        self.bridge.value['source'] = None
        other = self.path.parent/'other.json'
        with Workflow(other, self.bridge) as workflow:
            with self.assertRaises(ContractError):
                workflow.create(self.batches)
        self.assertFalse(other.exists())

    def test_bad_history_is_unknown_and_never_replayed(self):
        with self.open() as workflow:
            self.start(workflow)
            self.bridge.value['history'] = [{'episode_id': uid(), 'task': None}]
            self.assertEqual(workflow.tick()['status'], 'unknown')
            self.assertEqual(len(self.bridge.calls), 1)

    def test_lock_and_corrupt_ledger_fail_closed(self):
        with self.open():
            with self.assertRaises(BlockingIOError):
                with self.open():
                    pass
        for value in ('{"schema":1,', '{"schema":NaN}', '{}'):
            self.path.write_text(value)
            with self.assertRaises((ValueError, KeyError)):
                with self.open():
                    pass
        self.assertEqual(self.bridge.calls, [])

    def test_known_start_rejection_is_preserved_until_explicit_recovery(self):
        self.bridge.reject.add('start')
        with self.open() as workflow:
            original = self.start(workflow)
            self.assertEqual(workflow.data['status'], 'fault')
            self.assertEqual(workflow.tick()['reason'], 'start_rejected')
            with self.assertRaises(ContractError):
                workflow.dispatch()
            workflow.reset(recover=True)
            self.bridge.acknowledge_reset()
            self.assertEqual(workflow.tick()['status'], 'waiting_ready')
            self.assertEqual(workflow.data['jobs'][0]['attempts'][0]['task_id'], original)
            self.assertEqual(workflow.data['jobs'][0]['attempts'][0]['status'], 'rejected')

    def test_cli_status_reads_without_api_or_posts(self):
        with patch('cooperation_workflow.LocalBridge', return_value=self.bridge), patch('builtins.print') as output:
            calls_before = list(self.bridge.gets)
            self.assertEqual(main(['--ledger', str(self.path), 'status']), 0)
            result = json.loads(output.call_args.args[0])
            self.assertEqual(result['status'], 'waiting_ready')
            self.assertEqual(calls_before, self.bridge.gets)
            self.assertEqual(self.bridge.calls, [])

    def test_endpoint_refuses_remote_auth_and_ambiguous_ports(self):
        for endpoint in ('https://127.0.0.1:9086', 'http://example.com:9086',
                         'http://user:password@127.0.0.1:9086', 'http://127.0.0.1',
                         'http://127.0.0.1:9086/coop-api', 'http://127.0.0.1:9086/?x=1'):
            with self.assertRaises((ContractError, ValueError)):
                LocalBridge(endpoint)

    def test_http_unknown_does_not_retry_post(self):
        client = LocalBridge(self.bridge.endpoint)
        for error in (OSError('lost connection'), HTTPError(client.endpoint, 500, 'error', {}, io.BytesIO(b'{}')),
                      HTTPError(client.endpoint, 409, 'error', {}, io.BytesIO(b'null'))):
            with patch('cooperation_workflow.urlopen', side_effect=error) as request:
                with self.assertRaises(TransportUnknown):
                    client.post('start', {'task_id': uid()})
                self.assertEqual(request.call_count, 1)
                self.assertEqual(request.call_args.args[0].get_method(), 'POST')

    def test_http_explicit_rejection_and_get_unknown_remain_distinct(self):
        client = LocalBridge(self.bridge.endpoint)
        response = b'{"outcome":"rejected","error":"not admitted"}'
        with patch('cooperation_workflow.urlopen', side_effect=HTTPError(client.endpoint, 409, 'reject', {}, io.BytesIO(response))):
            self.assertEqual(client.post('start', {})['outcome'], 'rejected')
        with patch('cooperation_workflow.urlopen', side_effect=HTTPError(client.endpoint, 404, 'reject', {}, io.BytesIO(response))):
            with self.assertRaises(TransportUnknown):
                client.reset(uid())

    def test_new_episode_without_idle_ready_state_cannot_advance(self):
        with self.open() as workflow:
            self.start(workflow)
            self.bridge.terminal()
            workflow.reset()
            self.bridge.acknowledge_reset()
            state = copy.deepcopy(self.bridge.value)
            for changes in ({'ready': False}, {'task': {'id': uid(), 'status': 'running'}},
                            {'reset': {'available': False, 'pending': True}}):
                self.bridge.value = dict(copy.deepcopy(state), **changes)
                self.assertEqual(workflow.tick()['status'], 'unknown')
                self.assertEqual(workflow.data['index'], 0)
            self.bridge.value = state
            self.assertEqual(workflow.tick()['status'], 'waiting_ready')
            self.assertEqual(len(self.bridge.calls), 2)

    def run_with_clock(self, sleep, timeout=10., poll=1.):
        counter = [0.]
        def advance(seconds):
            counter[0] += seconds
            sleep(counter[0])
        return run_workflow(self.path, self.bridge, timeout=timeout, poll=poll,
                            clock=lambda: counter[0], sleep=advance,
                            wall_clock=lambda: 1700000000.+counter[0])

    def test_run_releases_lock_for_external_events_and_automates_two_jobs(self):
        sleeps = []
        def external(seconds):
            sleeps.append(seconds)
            # This second file owner must succeed while the runner is asleep.
            with self.open() as workflow:
                if seconds == 1:
                    self.ready(workflow)
                elif seconds == 2 or seconds == 6:
                    self.bridge.terminal()
                elif seconds == 4:
                    self.bridge.acknowledge_reset()
                elif seconds == 5:
                    self.ready(workflow, version=2)
        result = self.run_with_clock(external)
        self.assertEqual(result['exit_reason'], 'succeeded')
        self.assertEqual(result['workflow']['status'], 'succeeded')
        self.assertEqual(sleeps, [1., 2., 3., 4., 5., 6.])
        self.assertEqual([kind for kind, body in self.bridge.calls], ['start', 'reset', 'start'])
        self.assertEqual(read_json(self.path)['runner']['exit_reason'], 'succeeded')

    def test_run_automates_three_jobs_and_passes_only_the_selected_new_destination(self):
        target = {'x':1.25,'y':-1.75,'yaw':.4}
        self.create_jobs(3,lambda batches:{batches[1]:target})
        def external(seconds):
            with self.open() as workflow:
                if seconds in (1,5,9):
                    self.ready(workflow,version=int((seconds-1)/4)+1)
                elif seconds in (2,6,10):
                    self.bridge.terminal()
                elif seconds in (4,8):
                    self.bridge.acknowledge_reset()
        result = self.run_with_clock(external,timeout=15)
        self.assertEqual(result['exit_reason'],'succeeded')
        self.assertEqual([job['status'] for job in result['workflow']['jobs']],['succeeded']*3)
        starts = [body for kind,body in self.bridge.calls if kind=='start']
        self.assertEqual(len(starts),3)
        self.assertNotIn('delivery_pose',starts[0])
        self.assertEqual(starts[1]['delivery_pose'],target)
        self.assertNotIn('delivery_pose',starts[2])
        self.assertEqual([kind for kind,_ in self.bridge.calls],['start','reset','start','reset','start'])

    def test_run_timeout_preserves_original_active_task(self):
        with self.open() as workflow:
            original = self.start(workflow)
        result = self.run_with_clock(lambda seconds: None, timeout=3.)
        self.assertEqual(result['exit_reason'], 'timeout')
        self.assertEqual(result['workflow']['status'], 'active')
        self.assertEqual(result['workflow']['operation']['task_id'], original)
        self.assertEqual(self.bridge.value['task']['status'], 'running')
        self.assertEqual([kind for kind, body in self.bridge.calls], ['start'])
        with self.open() as workflow:
            self.assertEqual(workflow.tick()['status'], 'active')

    def test_run_fault_unknown_and_missing_source_stop_without_implicit_recovery(self):
        with self.open() as workflow:
            self.start(workflow)
        self.bridge.terminal('failed')
        result = self.run_with_clock(lambda seconds: self.fail('fault must not sleep'))
        self.assertEqual(result['exit_reason'], 'blocked_fault')
        self.assertEqual([kind for kind, body in self.bridge.calls], ['start'])
        self.bridge.value['source'] = None
        with self.open() as workflow:
            workflow.tick()
        gets = list(self.bridge.gets)
        result = self.run_with_clock(lambda seconds: self.fail('unknown must not sleep'))
        self.assertEqual(result['exit_reason'], 'blocked_unknown')
        self.assertEqual(gets, self.bridge.gets)

    def test_run_lost_post_receipt_returns_unknown_without_resubmission(self):
        with self.open() as workflow:
            self.ready(workflow)
        self.bridge.lose.add('start')
        result = self.run_with_clock(lambda seconds: self.fail('unknown must not sleep'))
        self.assertEqual(result['exit_reason'], 'blocked_unknown')
        self.assertEqual(len(self.bridge.calls), 1)
        self.assertEqual(self.bridge.value['task']['status'], 'running')
        with self.open() as workflow:
            self.assertEqual(workflow.tick()['status'], 'active')

    def test_run_does_not_reset_without_terminal_quiet(self):
        with self.open() as workflow:
            self.start(workflow)
        self.bridge.terminal(quiet=False)
        result = self.run_with_clock(lambda seconds: None, timeout=2.)
        self.assertEqual(result['exit_reason'], 'timeout')
        self.assertEqual(result['workflow']['status'], 'waiting_quiet')
        self.assertEqual([kind for kind, body in self.bridge.calls], ['start'])

    def test_run_bounds_reject_without_api_or_ledger_change(self):
        original = self.path.read_bytes()
        gets = list(self.bridge.gets)
        for options in ({'timeout': 0}, {'timeout': 1801}, {'timeout': float('nan')},
                        {'poll': 0}, {'poll': 11}, {'poll': True}, {'poll': float('inf')}):
            with self.assertRaises(ContractError):
                run_workflow(self.path, self.bridge, **options)
            self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(gets, self.bridge.gets)

    def test_run_slow_start_preflight_expires_without_dispatch_intent_or_post(self):
        with self.open() as workflow:
            self.ready(workflow)
        elapsed = [0.]
        state = self.bridge.state
        def slow_state():
            elapsed[0] += 2.
            return state()
        with patch.object(self.bridge, 'state', side_effect=slow_state):
            result = run_workflow(self.path, self.bridge, timeout=1., poll=.1,
                clock=lambda: elapsed[0], sleep=lambda seconds: self.fail('expired must not sleep'))
        self.assertEqual(result['exit_reason'], 'timeout')
        self.assertEqual(result['workflow']['status'], 'waiting_ready')
        self.assertEqual(result['workflow']['jobs'][0]['attempts'], [])
        self.assertEqual(self.bridge.calls, [])

    def test_run_slow_reset_preflight_expires_without_reset_intent_or_post(self):
        with self.open() as workflow:
            self.start(workflow)
            self.bridge.terminal()
            workflow.tick()
        elapsed = [0.]
        state = self.bridge.state
        def slow_state():
            elapsed[0] += 2.
            return state()
        with patch.object(self.bridge, 'state', side_effect=slow_state):
            result = run_workflow(self.path, self.bridge, timeout=1., poll=.1,
                clock=lambda: elapsed[0], sleep=lambda seconds: self.fail('expired must not sleep'))
        self.assertEqual(result['exit_reason'], 'timeout')
        self.assertEqual(result['workflow']['status'], 'waiting_reset')
        self.assertEqual(result['workflow']['resets'], [])
        self.assertEqual([kind for kind, body in self.bridge.calls], ['start'])

    def test_run_deadline_after_durable_intent_blocks_post_and_preserves_unknown(self):
        with self.open() as workflow:
            self.ready(workflow)
        elapsed = [0.]
        save = Workflow._save
        def slow_save(workflow):
            save(workflow)
            if workflow.data['operation'] is not None:
                elapsed[0] = 2.
        with patch.object(Workflow, '_save', new=slow_save):
            result = run_workflow(self.path, self.bridge, timeout=1., poll=.1,
                clock=lambda: elapsed[0], sleep=lambda seconds: self.fail('expired must not sleep'))
        self.assertEqual(result['exit_reason'], 'timeout')
        self.assertEqual(result['workflow']['status'], 'unknown')
        self.assertEqual(len(result['workflow']['jobs'][0]['attempts']), 1)
        self.assertEqual(self.bridge.calls, [])
        with self.open() as workflow:
            with self.assertRaises(ContractError):
                workflow.dispatch()

    def test_run_preflight_failure_without_intent_is_still_unsent_and_recoverable(self):
        with self.open() as workflow:
            self.ready(workflow)
        source = self.bridge.value['source']
        self.bridge.value['source'] = None
        result = self.run_with_clock(lambda seconds: self.fail('blocked preflight must not sleep'))
        self.assertEqual(result['exit_reason'], 'blocked_preflight')
        self.assertEqual(result['workflow']['status'], 'waiting_ready')
        self.assertIsNone(result['workflow']['operation'])
        self.assertEqual(result['workflow']['jobs'][0]['attempts'], [])
        self.assertEqual(self.bridge.calls, [])
        self.bridge.value['source'] = source
        result = self.run_with_clock(lambda seconds: None, timeout=1.)
        self.assertEqual(result['exit_reason'], 'timeout')
        self.assertEqual(result['workflow']['status'], 'active')
        self.assertEqual(len(self.bridge.calls), 1)


if __name__ == '__main__':
    unittest.main()
