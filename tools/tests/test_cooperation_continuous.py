"""Original Workflow no-reset contracts over the real strict start envelope.

These API fixtures do not claim native motion or independent physics scoring.
"""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.tests.test_cooperation_workflow import Bridge, uid
from cooperation_workflow import ContractError, Workflow, main, read_json


class BusinessBridge(Bridge):
    def __init__(self):
        super().__init__()
        self.world = uid()
        self.value['business_inventory'] = {'world_id': self.world, 'episode_id': self.value['episode_id'],
            'cargo': {name: {'state': 'available', 'task_id': None} for name in ('cargo_1', 'cargo_2')}}

    def post(self, kind, body):
        if kind == 'reset':
            raise AssertionError('continuous workflow must not reset the world')
        result = super().post(kind, body)
        if kind == 'start':
            self.value['task']['business_delivery'] = copy.deepcopy(body['business_delivery'])
            item = self.value['business_inventory']['cargo'][body['business_delivery']['cargo_id']]
            item.update(state='reserved', task_id=body['task_id'])
            result['task'] = copy.deepcopy(self.value['task'])
        return result

    def complete(self, *, inventory=True, quiet=True):
        self.terminal(quiet=quiet)
        task = self.value['task']
        if inventory:
            self.value['business_inventory']['cargo'][task['business_delivery']['cargo_id']].update(
                state='delivered', task_id=task['id'])
        self.value['cleanup'] = {'state': 'verified', 'native_terminal': True,
                                'quiet': quiet, 'hold': True, 'guard_disabled': True}
        self.value['ready'] = any(item['state']=='available'
                                 for item in self.value['business_inventory']['cargo'].values())


class ContinuousWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.bridge = BusinessBridge()
        self.batches = [uid(), uid()]
        self.goals = {batch: {'x': .7, 'y': -2., 'yaw': 0.} for batch in self.batches}
        self.bindings = {batch: {'cargo_id': f'cargo_{i+1}', 'pickup_arm_id': 'load',
                                 'unload_station_id': 'line_b'} for i,batch in enumerate(self.batches)}
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'workflow.json'

    def create(self):
        with Workflow(self.path,self.bridge) as flow:
            return flow.create(self.batches,delivery_poses=self.goals,continuous_deliveries=self.bindings)

    def dispatch(self):
        with Workflow(self.path,self.bridge) as flow:
            job = flow._job();machine = flow.data['machines'][job['machine_id']]
            flow.event({'event_id':uid(),'batch_id':job['batch_id'],'machine_id':job['machine_id'],
                        'version':machine['version']+1,'ready':True})
            return flow.dispatch()

    def test_two_named_orders_keep_world_episode_and_previous_pose_without_reset(self):
        initial = self.create();episode = initial['episode_id']
        first = self.dispatch();first_id = first['jobs'][0]['attempts'][0]['task_id']
        self.bridge.complete()
        # Source metadata is editable; world/episode and owned receipts carry identity.
        self.bridge.value['source']['scene_sha'] = 'human-edited-diagnostic'
        with Workflow(self.path,self.bridge) as flow:
            after = flow.tick()
        self.assertEqual((after['status'],after['index'],after['resets']),('waiting_ready',1,[]))
        self.assertEqual(self.bridge.value['task']['id'],first_id)
        self.bridge.value['nav'] = {'pose': {'x': .7,'y':-2.,'yaw':0.}}
        second = self.dispatch()
        self.assertEqual(second['episode_id'],episode)
        self.assertEqual(self.bridge.value['nav']['pose']['x'],.7)
        self.bridge.complete()
        with Workflow(self.path,self.bridge) as flow:done = flow.tick()
        self.assertEqual(done['status'],'succeeded')
        self.assertEqual(done['resets'],[])
        self.assertEqual(done['world_session_id'],self.bridge.world)
        self.assertEqual([job['status'] for job in done['jobs']],['succeeded','succeeded'])
        self.assertEqual([kind for kind,_ in self.bridge.calls],['start','start'])
        self.assertEqual([body['business_delivery']['cargo_id'] for _,body in self.bridge.calls],['cargo_1','cargo_2'])

    def test_success_status_without_named_inventory_or_cleanup_cannot_advance(self):
        self.create();self.dispatch();self.bridge.complete(inventory=False)
        with Workflow(self.path,self.bridge) as flow:value = flow.tick()
        self.assertEqual((value['status'],value['index']),('waiting_quiet',0))
        self.bridge.complete(quiet=False)
        with Workflow(self.path,self.bridge) as flow:value = flow.tick()
        self.assertEqual(value['status'],'waiting_quiet')
        self.assertEqual(len(self.bridge.calls),1)

    def test_pending_physical_reset_cannot_admit_the_next_order(self):
        self.create();self.dispatch();self.bridge.complete()
        self.bridge.value['reset']['pending']=True
        with Workflow(self.path,self.bridge) as flow:value=flow.tick()
        self.assertEqual((value['status'],value['index']),('waiting_quiet',0))
        self.assertEqual(len(self.bridge.calls),1)

    def test_changed_physical_world_or_wrong_cargo_receipt_stays_unknown_without_replay(self):
        self.create();self.dispatch()
        self.bridge.value['task']['business_delivery']['cargo_id'] = 'cargo_2'
        with Workflow(self.path,self.bridge) as flow:value = flow.tick()
        self.assertEqual(value['status'],'unknown')
        self.assertEqual(len(self.bridge.calls),1)
        self.bridge.value['business_inventory']['world_id'] = uid()
        with Workflow(self.path,self.bridge) as flow:value = flow.tick()
        self.assertEqual(value['status'],'unknown')
        self.assertEqual(len(self.bridge.calls),1)

    def test_continuous_create_does_not_require_a_content_hash(self):
        self.bridge.value['source'] = {}
        value = self.create()
        self.assertEqual(value['execution_mode'],'continuous')
        self.assertIsNone(value['scene_sha256'])
        self.dispatch()
        self.assertEqual(len(self.bridge.calls),1)

    def test_recovery_does_not_create_new_stock_or_a_new_episode(self):
        self.create();self.dispatch()
        episode=self.bridge.value['episode_id'];before=copy.deepcopy(self.bridge.value['business_inventory'])
        self.bridge.terminal(status='failed')
        with Workflow(self.path,self.bridge) as flow:
            with self.assertRaisesRegex(ContractError,'never resets'):
                flow.reset(recover=True)
        self.assertEqual(self.bridge.value['episode_id'],episode)
        self.assertEqual(self.bridge.value['business_inventory'],before)
        self.assertEqual([kind for kind,_ in self.bridge.calls],['start'])

    def test_duplicate_or_unavailable_stock_is_not_reset_or_substituted(self):
        self.bindings[self.batches[1]]['cargo_id'] = 'cargo_1'
        with self.assertRaises(ContractError):self.create()
        self.bindings[self.batches[1]]['cargo_id'] = 'cargo_2'
        self.bridge.value['business_inventory']['cargo']['cargo_1']['state'] = 'delivered'
        with self.assertRaises(ContractError):self.create()
        self.assertEqual(self.bridge.calls,[])
        self.assertFalse(self.path.exists())

    def test_cli_persists_continuous_binding_before_any_start(self):
        goals=self.path.parent/'goals.json';bindings=self.path.parent/'bindings.json'
        goals.write_text(json.dumps(self.goals));bindings.write_text(json.dumps(self.bindings))
        with patch('cooperation_workflow.LocalBridge',return_value=self.bridge),patch('sys.stdout',io.StringIO()):
            result=main(['--ledger',str(self.path),'init','--batches',*self.batches,
                         '--delivery-poses',str(goals),'--continuous-deliveries',str(bindings)])
        self.assertEqual(result,0)
        value=read_json(self.path)
        self.assertEqual(value['execution_mode'],'continuous')
        self.assertEqual(value['jobs'][1]['business_delivery'],self.bindings[self.batches[1]])
        self.assertEqual(self.bridge.calls,[])


if __name__=='__main__':unittest.main()
