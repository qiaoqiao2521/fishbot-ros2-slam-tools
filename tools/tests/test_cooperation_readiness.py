"""Exercise the reused production GetState method without ROS imports."""
import ast
from concurrent.futures import Future
import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock,patch

TOOLS=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('cooperation_readiness',TOOLS/'cooperation_readiness.py')
readiness=importlib.util.module_from_spec(spec);spec.loader.exec_module(readiness)


def existing_update():
    tree=ast.parse(readiness.SOURCE.read_text())
    method=next(m for c in tree.body if isinstance(c,ast.ClassDef) and c.name=='Readiness'
                for m in c.body if isinstance(m,ast.FunctionDef) and m.name=='update_lifecycle')
    clock=Mock();clock.monotonic.return_value=100.
    state_type=NS(Request=lambda:object())
    namespace={'time':clock,'math':math,'GetState':state_type}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),str(readiness.SOURCE),'exec'),namespace)
    return namespace['update_lifecycle'],state_type,clock


class NativeReadinessTests(unittest.TestCase):
    def test_existing_query_method_waits_for_both_active_receipts(self):
        update,state_type,clock=existing_update();node=Mock();clients={}
        def create_client(kind,path):
            client=Mock();client.service_is_ready.return_value=True
            future=Mock();future.done.return_value=False
            future.result.return_value=NS(current_state=NS(id=1 if 'docking' in path else 3))
            client.call_async.return_value=future;clients[path]=client;return client
        node.create_client.side_effect=create_client
        with patch.object(readiness,'_load_runtime',return_value=(update,state_type)),patch.object(readiness.time,'monotonic',side_effect=lambda:clock.monotonic()):
            gate=readiness.NativeReadiness(node);self.assertFalse(gate.active())
            gate.update()
            for client in clients.values():client.call_async.return_value.done.return_value=True
            gate.update();self.assertFalse(gate.active())
            clock.monotonic.return_value=100.6;gate.update()
            clients['/docking_server/get_state'].call_async.return_value.result.return_value.current_state.id=3
            gate.update();self.assertTrue(gate.active())
        for client in clients.values():self.assertLessEqual(client.call_async.call_count,2)
        self.assertEqual(set(clients),{'/docking_server/get_state','/bt_navigator/get_state'})

    def test_stale_inactive_missing_and_malformed_receipts_never_ready(self):
        snapshot={'ready':True,'observed_monotonic':100.,'lifecycle':{'docking_server':[3,100.],'bt_navigator':[3,100.]}}
        self.assertTrue(readiness.snapshot_active(snapshot,100.1))
        for state in ([1,100.],[3,96.],[True,100.],None):
            changed={**snapshot,'lifecycle':{**snapshot['lifecycle'],'docking_server':state}}
            with self.subTest(state=state):self.assertFalse(readiness.snapshot_active(changed,100.1))


class StaticLocalizationWarmupTests(unittest.TestCase):
    def gate(self, updates=1):
        client=Mock();client.service_is_ready.return_value=True
        client.call_async.side_effect=lambda request:Future()
        return readiness.StaticLocalizationWarmup(client,object,updates)

    def observe(self,gate,stamp=100.1,**changes):
        values={'stamp':stamp,'pose':{'x':-.88,'y':-1.68,'yaw':.02},
                'covariance':[.001 if i in (0,7,35) else 0. for i in range(36)],
                'frame_id':'map','source_now':stamp+.05}
        gate.observe(**(values|changes))

    def tick(self,gate,source=100.,**changes):
        gate.update(source,**({'held':True,'native_active':True}|changes))

    def test_service_ack_is_not_a_pose_and_repeated_old_frame_cannot_complete(self):
        gate=self.gate();self.tick(gate)
        gate.pending['future'].set_result(object());self.tick(gate,100.1)
        self.assertFalse(gate.snapshot()['ready'])
        self.observe(gate,100.);self.tick(gate,100.1)
        self.assertFalse(gate.snapshot()['ready'])
        self.observe(gate);self.tick(gate,100.2)
        state=gate.snapshot();self.assertTrue(state['ready'])
        self.assertEqual(state['records'][0]['pose_source_s'],100.1)
        self.assertEqual(len(state['records'][0]['covariance']),36)
        self.assertFalse(state['service_response_is_pose_consumption_ack'])

    def test_pose_before_service_response_waits_for_original_response(self):
        gate=self.gate();self.tick(gate);self.observe(gate)
        self.tick(gate,100.2);self.assertFalse(gate.snapshot()['ready'])
        gate.pending['future'].set_result(object());self.tick(gate,100.3)
        self.assertTrue(gate.snapshot()['ready'])

    def test_ros_fixed_array_numpy_double_is_accepted_without_changing_values(self):
        import numpy as np
        gate=self.gate();self.tick(gate);gate.pending['future'].set_result(object())
        covariance=np.array([.001 if i in (0,7,35) else 0. for i in range(36)],dtype=np.float64)
        self.observe(gate,covariance=list(covariance));self.tick(gate,100.2)
        self.assertTrue(gate.snapshot()['ready'])
        self.assertEqual(gate.snapshot()['records'][0]['covariance'],covariance.tolist())

    def test_wrong_frame_and_stale_pose_are_skipped_then_new_frame_recovers(self):
        gate=self.gate();self.tick(gate);gate.pending['future'].set_result(object())
        for changes in ({'frame_id':'odom'},{'source_now':102.}):
            self.observe(gate,**changes);self.tick(gate,100.2)
            self.assertFalse(gate.snapshot()['ready'])
        self.observe(gate);self.tick(gate,100.2)
        self.assertTrue(gate.snapshot()['ready'])

    def test_covariance_is_diagnostic_and_does_not_block_the_fresh_pose(self):
        for covariance in ([float('nan')]*36,[0.]*35,[-1e-13]+[0.]*35):
            gate=self.gate();self.tick(gate);gate.pending['future'].set_result(object())
            with self.assertLogs(level='WARNING'):
                self.observe(gate,covariance=covariance)
            self.tick(gate,100.2);state=gate.snapshot()
            self.assertTrue(state['ready'])
            item=state['records'][0];self.assertTrue(item['covariance_warning'])
            self.assertEqual(item['pose'],{'x':-.88,'y':-1.68,'yaw':.02})
            self.assertEqual(item['covariance'],covariance if len(covariance)==36 and covariance[0]<0 else None)

    def test_three_distinct_post_request_frames_required_while_held(self):
        gate=self.gate(updates=3)
        self.tick(gate,held=False);self.tick(gate,native_active=False)
        gate.client.call_async.assert_not_called()
        for i in range(3):
            source=100.+i
            self.tick(gate,source);gate.pending['future'].set_result(object())
            if i:self.observe(gate,source-.9)
            self.observe(gate,source+.1);self.tick(gate,source+.2)
            self.assertEqual(gate.snapshot()['completed_updates'],i+1)
            self.assertEqual(gate.snapshot()['ready'],i==2)
        self.assertEqual(gate.client.call_async.call_count,3)

    def test_service_timeout_or_exception_does_not_prevent_a_later_attempt(self):
        gate=self.gate()
        with patch.object(readiness.time,'monotonic',return_value=10.):self.tick(gate)
        first=gate.pending['future']
        with patch.object(readiness.time,'monotonic',return_value=14.):self.tick(gate,100.2)
        self.assertTrue(first.cancelled());self.assertFalse(gate.snapshot()['ready'])
        self.tick(gate,100.3);gate.pending['future'].set_exception(RuntimeError('temporary'))
        self.tick(gate,100.4);self.assertFalse(gate.snapshot()['ready'])
        self.tick(gate,100.5);gate.pending['future'].set_result(object())
        self.observe(gate,100.6);self.tick(gate,100.7)
        self.assertTrue(gate.snapshot()['ready'])

    def initialized_gate(self):
        client=Mock();client.service_is_ready.return_value=True
        client.call_async.return_value=Future()
        prior={'pose':{'x':-.88,'y':-1.68,'yaw':.02},
               'covariance':[.0004 if i in (0,7) else .001 if i==35 else 0. for i in range(36)]}
        factory=Mock(return_value=(object(),prior))
        gate=self.gate()
        gate.initializer=(client,factory)
        gate.initialization.update(configured=True,state='not_requested')
        return gate,client,factory,prior

    def test_explicit_prior_response_precedes_nomotion_and_new_frames(self):
        gate,client,factory,prior=self.initialized_gate()
        self.tick(gate);self.observe(gate)
        gate.client.call_async.assert_not_called()
        self.assertEqual(gate.snapshot()['initialization']['request'],prior)
        self.assertEqual(gate.snapshot()['completed_updates'],0)
        client.call_async.return_value.set_result(object());self.tick(gate,100.2)
        self.assertEqual(gate.snapshot()['initialization']['state'],'received')
        self.assertFalse(gate.snapshot()['ready'])
        gate.pending['future'].set_result(object());self.observe(gate,100.3);self.tick(gate,100.4)
        self.assertTrue(gate.snapshot()['ready'])
        client.call_async.assert_called_once();factory.assert_called_once()

    def test_unknown_initialization_is_not_resent_and_late_original_ack_reconciles(self):
        gate,client,_,_=self.initialized_gate()
        with patch.object(readiness.time,'monotonic',return_value=10.):self.tick(gate)
        with patch.object(readiness.time,'monotonic',return_value=14.):self.tick(gate,100.2)
        self.assertEqual(gate.snapshot()['initialization']['state'],'unknown')
        self.tick(gate,100.3);client.call_async.assert_called_once()
        gate.client.call_async.assert_not_called()
        client.call_async.return_value.set_result(object());self.tick(gate,100.4)
        self.assertEqual(gate.snapshot()['initialization']['state'],'received')
        client.call_async.assert_called_once()

    def test_ambiguous_initialization_send_error_never_repeats_the_request(self):
        gate,client,_,_=self.initialized_gate()
        client.call_async.side_effect=RuntimeError('response channel lost')
        self.tick(gate);self.tick(gate,100.1);self.tick(gate,100.2)
        self.assertEqual(gate.snapshot()['initialization']['state'],'unknown')
        self.assertFalse(gate.snapshot()['ready'])
        client.call_async.assert_called_once();gate.client.call_async.assert_not_called()


if __name__=='__main__':unittest.main()
