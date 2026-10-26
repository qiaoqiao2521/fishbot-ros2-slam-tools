"""Exercise actual Bridge methods with controlled physical frames and publishers."""
import copy
from types import SimpleNamespace as NS
import unittest

from tools.tests import test_cooperation_core as core_tests
from tools.tests.test_cooperation_business import fixture


class NamedOwnerTests(unittest.TestCase):
    def setUp(self):
        case=core_tests.BridgeRaceTests(methodName='runTest');case.setUp()
        self.case,self.owner=case,case.bridge
        description,measured,binding=fixture()
        self.manifest=case.namespace['manifest']
        self.manifest['business_entities']=description['business_entities']
        self.manifest['business_entities']['configuration']={'budgets_wall_s':{'load_and_delivery':360,'unload':180}}
        for name,arm in self.manifest['business_entities']['arms'].items():
            arm['home_qpos6']=[0.]*6
            arm['joint_names']=[('' if name=='load' else name+'__')+j
                                for j in ('shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper')]
        for arm in measured['business_entities']['arms'].values():
            arm['qpos6']=[0.]*6;arm['qvel6']=[0.]*6
        for cargo in measured['business_entities']['cargo'].values():
            cargo['velocity_world_angular_linear']=[0.]*6
        self.owner.raw['business_entities']=measured['business_entities']
        self.owner.raw['world_session_id']='controlled-world'
        self.owner.task['business_delivery']=binding
        self.owner.task['active_arm_id']='unload_b'
        self.binding=binding

    def test_reference_and_abort_freeze_address_only_the_selected_unload_arm(self):
        p=self.owner;messages=[]
        p.arm_pub=NS(publish=lambda msg:messages.append((list(msg.name),list(msg.position))))
        p.raw['business_entities']['arms']['unload_b']['qpos6']=[.1,.2,.3,.4,.5,.015]
        p.reference([.11,.21,.31,.41,.51,.02])
        self.assertTrue(all(name.startswith('unload_b__') for name in messages[-1][0]))
        self.assertTrue(p.freeze_arm(p.execution_token))
        self.assertEqual(messages[-1][1],[.1,.2,.3,.4,.5,.02])
        self.assertEqual(p.raw['q6'][:5],[0.]*5)

    def test_cleanup_requires_secondary_arm_and_secondary_cargo_quiet(self):
        p=self.owner
        p.raw['business_entities']['arms']['unload_b']['qvel6']=[.1]*6
        self.assertFalse(p.cleanup(p.execution_token,timeout=.1))
        self.assertFalse(p.cleanup_summary['quiet'])
        p.raw['business_entities']['arms']['unload_b']['qvel6']=[0.]*6
        p.raw['business_entities']['cargo']['cargo_2']['velocity_world_angular_linear'][3]=.1
        self.assertFalse(p.business_quiet(p.raw))
        p.raw['business_entities']['cargo']['cargo_2']['velocity_world_angular_linear'][3]=0.
        self.assertTrue(p.cleanup(p.execution_token,timeout=2.))

    def test_handoff_uses_selected_cargo_without_rewriting_the_common_frame(self):
        p=self.owner;item=p.raw['business_entities']['cargo']['cargo_2']
        item['position']=list(p.raw['tray']['position'])
        item['quaternion_wxyz']=[1.,0.,0.,0.]
        item['contacts']={'supports':{'tray':{'contact_count':4,'normal_force_n':.0981}},
                          'pads':{},'other_cargo':{}}
        p.raw['cargo_tray_floor_contact']=False;p.raw['cargo']['position_relative_tray']=[2.,2.,2.]
        before=copy.deepcopy(p.raw)
        self.assertTrue(p.task_handoff(p.raw))
        self.assertEqual(p.raw,before)
        item['contacts']['supports']={}
        self.assertFalse(p.task_handoff(p.raw))

    def test_named_placement_query_keeps_original_deadline_and_refreshes_execution_geometry(self):
        p=self.owner;calls=[];raw=p.raw
        p.wall_deadline=self.case.namespace['time'].monotonic()+37.
        execution={'mode':'one_owned_query_process','child_exited':True,'child_pid':123,
                   'wall_budget_s':37.,'wall_remaining_s':36.}
        def query(manifest,snapshot,centers,**kwargs):
            calls.append((snapshot,centers,kwargs));kwargs['check']()
            return {'report':{'execution':execution},'segments':[]}
        self.case.namespace['query_placement']=query
        planner=NS(refresh_placement_context=lambda snapshot,**kwargs:calls.append(('refresh',snapshot,kwargs)))
        plan=p.placement_query(planner,raw,[[.18,0.,.06]])
        self.assertEqual(calls[0][2]['arm_id'],'unload_b')
        self.assertEqual(calls[0][2]['cargo_id'],'cargo_2')
        self.assertEqual(calls[0][2]['timeout_s'],37.)
        self.assertEqual(calls[1][0],'refresh')
        self.assertIs(calls[1][1],raw)
        self.assertIsNot(p.task['arm_placement_planning']['execution'],execution)
        self.assertEqual(p.task['arm_placement_planning']['execution'],execution)
        self.assertEqual(plan['report']['execution']['child_pid'],123)

    def test_optional_delivery_checkpoint_checks_the_current_cargo(self):
        p=self.owner;self.manifest['capture_before_delivery']=True
        cargo=p.raw['business_entities']['cargo']['cargo_2']
        cargo.update(position=list(p.raw['tray']['position']),quaternion_wxyz=[1.,0.,0.,0.])
        cargo['contacts']={'supports':{'tray':{'contact_count':1,'normal_force_n':.1}},
                           'pads':{},'other_cargo':{}}
        p.raw.update(cargo_tray_floor_contact=False,cargo_tray_floor_contacts=0,
                     cargo_tray_floor_normal_force_n=0.)
        p.raw['cargo']['position_relative_tray']=[2.,2.,2.]
        checked=[]
        def wait(condition,**kwargs):
            checked.append(condition(p.raw));self.assertTrue(checked[-1]);return p.raw
        p.wait_condition=wait
        p.request_checkpoint=lambda body:{'request_id':body['request_id']}
        p.checkpoint_record=lambda identity:{'status':'succeeded','request_id':identity}
        p.capture_delivery_checkpoint()
        self.assertEqual(checked,[True])
        self.assertEqual(p.task['delivery_checkpoint']['status'],'succeeded')

    def test_final_unload_receipt_reobserves_support_release_and_home(self):
        p=self.owner
        p.raw['episode_id']='controlled-episode'
        item=p.raw['business_entities']['cargo']['cargo_2']
        item.update(position=[10.22,20.05,1.008],quaternion_wxyz=[1.,0.,0.,0.],
                    velocity_world_angular_linear=[0.]*6)
        item['contacts']={'supports':{'line_b':{'contact_count':4,'normal_force_n':.0981}},
                          'pads':{},'other_cargo':{}}
        self.assertTrue(p.unload_ready(p.raw))
        receipt=p.unload_evidence(p.raw)
        self.assertEqual(receipt['sequence'],p.raw['sequence'])
        self.assertEqual(receipt['cargo_id'],'cargo_2')
        item['contacts']['supports']={}
        with self.assertRaisesRegex(RuntimeError,'库存不记为送达'):p.unload_evidence(p.raw)
        item['contacts']['supports']={'line_b':{'contact_count':4,'normal_force_n':.0981}}
        item['contacts']['pads']={'unload_b':{'pad_gripper':{'contact_count':1,'normal_force_n':.02}}}
        self.assertFalse(p.unload_ready(p.raw))
        item['contacts']['pads']={}
        p.raw['business_entities']['arms']['unload_b']['qpos6'][0]=.2
        self.assertFalse(p.unload_ready(p.raw))

    def test_known_task_id_cannot_be_rebound_to_another_physical_cargo(self):
        p=self.owner;p.known_ids.add(p.task['id'])
        delivery=p.task.get('delivery_pose',self.case.namespace['task_delivery_pose']({},self.manifest.get('delivery_pose')))
        original=p.existing_start(p.task['id'],'transport',delivery,[],self.binding)
        self.assertEqual(original['task_id'],p.task['id'])
        other={**self.binding,'cargo_id':'cargo_1'}
        with self.assertRaisesRegex(ValueError,'另一货物'):
            p.existing_start(p.task['id'],'transport',delivery,[],other)


if __name__=='__main__':unittest.main()
