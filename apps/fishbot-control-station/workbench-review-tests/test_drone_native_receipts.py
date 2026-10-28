"""C++ envelope admission on temporary real Sidecar methods; sensing is synthetic."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import types
import unittest
from unittest.mock import patch

from scipy.interpolate import BSpline
import test_drone_source_graph_guard as graph_fixture


class NativeReceiptIngress(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        graph_fixture.SourceGraphGuard.setUpClass()
        cls.fixture=graph_fixture.SourceGraphGuard.fixture
        spec=importlib.util.spec_from_file_location('native_receipt_fixture',cls.fixture.root/'native_receipts.py')
        cls.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        graph_fixture.SourceGraphGuard.tearDownClass()

    def harness(self):
        return graph_fixture.SourceGraphGuard.harness(self)

    def native(self):
        h=self.harness()
        h.node.command_epoch.native_receipts_enabled=True
        h.node.setpoint=None;h.node.trajectory_times.clear();h.node.goal_acknowledged=False
        h.wall_ns=100_000_000_000
        h.reader=self.module.NativeReceipts(h.node.args.runtime/'receipts.jsonl',clock_ns=lambda:h.wall_ns)
        h.reader.process=types.SimpleNamespace(poll=lambda:None)
        h.node.native_receipts=h.reader
        h.curve_body={'traj_id':1,'order':3,'knots':list(h.curve().knots),
                      'control_points':[[p.x,p.y,p.z] for p in h.curve().pos_pts]}
        self.heartbeat(h)
        return h

    def heartbeat(self,h):
        h.reader.feed(h.node,dict(kind='heartbeat',host_monotonic_ns=h.wall_ns,
            publisher_counts=dict(ack=1,bspline=1,position=1)))

    def envelope(self,h,kind,body,sequence=1,stamp=10_000_000_000):
        return dict(kind=kind,message=body,publisher_gid=bytes(h.graph[kind][0].endpoint_gid).hex(),
            host_monotonic_ns=h.wall_ns,source_timestamp=1000+sequence,
            publication_sequence_number=sequence,source_stamp_ns=stamp)

    def acknowledge(self,h,sequence=1):
        h.reader.feed(h.node,self.envelope(h,'ack',dict(data=str(h.node.goal_stamp_ns)+':0'),sequence))

    def curve(self,h,sequence=1):
        h.reader.feed(h.node,self.envelope(h,'bspline',copy.deepcopy(h.curve_body),sequence))

    def position(self,h,sequence=1,stamp=10_150_000_000):
        c=BSpline(h.curve_body['knots'],h.curve_body['control_points'],3)
        u=h.curve_body['knots'][3]+(stamp-10_000_000_000)*1e-9
        body={k:c.derivative(i)(u).tolist() for i,k in enumerate(('position','velocity','acceleration'))}
        body.update(trajectory_id=1,yaw=.25)
        return self.envelope(h,'position',body,sequence,stamp)

    def ready(self,h):
        self.acknowledge(h);self.curve(h)
        h.reader.feed(h.node,self.position(h))

    def test_native_flag_enables_both_existing_layers_only_when_one(self):
        for setting in (None,'0','false','1'):
            with self.subTest(setting=setting),patch.dict(os.environ,{},clear=True):
                if setting is not None:os.environ['DRONE_NATIVE_RECEIPTS']=setting
                e=self.fixture.module.CommandEpoch()
                self.assertEqual((e.enabled,e.source_graph_enabled,e.native_receipts_enabled),(setting=='1',)*3)

    def test_init_planner_rejects_goal_without_queueing_then_wait_target_allows_it(self):
        h=self.native()
        h.node.active_goal=None;h.node.planner_state='INIT'
        body=dict(x=5.,y=0.,z=1.,task_id='task-A',goal_id='goal-new')
        state=h.node.state()
        self.assertFalse(state['ready'])
        self.assertEqual(state['reason'],'planner_waiting_for_odometry')
        response=self.fixture.post(h.node,'/goal',body)
        self.assertNotEqual(response[0][0],202)
        self.assertTrue(h.node.requests.empty());self.assertIsNone(h.node.active_goal)
        h.node.planner_state='WAIT_TARGET'
        response=self.fixture.post(h.node,'/goal',body)
        self.assertEqual(response[0][0],202)
        self.assertEqual(h.node.active_goal['goal_id'],'goal-new')
        h.node.planner_state='INIT';h.node.command_epoch.native_receipts_enabled=False
        self.assertTrue(h.node.state()['ready'])

    def test_exact_ns_pva_and_source_receipts_reach_current_point(self):
        h=self.native();self.acknowledge(h);self.curve(h)
        event=self.position(h,stamp=10_123_456_789);h.reader.feed(h.node,event)
        point=h.node.state()['setpoint']
        self.assertEqual(point['stamp_sim_s'],10.123456789)
        self.assertEqual(point['native_source']['position']['host_monotonic_ns'],h.wall_ns)
        self.assertEqual(point['native_source']['curve']['publisher_gid'],h.graph['bspline'][0].endpoint_gid.hex())
        self.assertFalse(h.node._native_receipt_dispatch)

    def test_curve_before_ack_keeps_first_curve_liveness(self):
        h=self.native();self.curve(h);self.assertEqual(h.node.trajectory_times,{})
        self.acknowledge(h);h.reader.feed(h.node,self.position(h))
        self.assertEqual(h.node.setpoint['trajectory_id'],1)

    def test_queued_foreign_curve_rejected_even_when_current_graph_is_healthy(self):
        h=self.native();self.ready(h);old=h.node.command_epoch.token
        event=self.envelope(h,'bspline',copy.deepcopy(h.curve_body),2)
        event['publisher_gid']='ab'*16
        event['message']['control_points'][0][0]=42.
        h.reader.feed(h.node,event)
        self.assertIsNone(h.node.setpoint);self.assertIsNone(h.node.active_goal)
        self.assertNotEqual(h.node.command_epoch.token,old)
        self.assertEqual(h.reader.last_error,'native_receipt_source_mismatch_bspline')

    def test_untrusted_ack_or_position_cannot_use_current_goal_label(self):
        for kind in ('ack','position'):
            with self.subTest(kind=kind):
                h=self.native();self.ready(h)
                event=self.position(h,2) if kind=='position' else self.envelope(h,'ack',dict(data='123:0'),2)
                event['publisher_gid']='ff'*16
                h.reader.feed(h.node,event)
                self.assertIsNone(h.node.setpoint);self.assertIsNone(h.node.active_goal)

    def test_trusted_output_with_wrong_pva_does_not_sanitize_unknown_curve_input(self):
        for key in ('position','velocity','acceleration'):
            with self.subTest(key=key):
                h=self.native();self.ready(h)
                event=self.position(h,2);event['message'][key][0]+=.01
                h.reader.feed(h.node,event)
                self.assertIsNone(h.node.setpoint)
                self.assertEqual(h.reader.last_error,'native_pva_curve_mismatch')

    def test_same_receipt_sequence_is_not_a_fresh_sample(self):
        h=self.native();self.ready(h);point=copy.deepcopy(h.node.setpoint)
        event=self.position(h);event['message']['position'][0]=999.
        h.reader.feed(h.node,event)
        self.assertEqual(h.node.setpoint,point)
        self.assertEqual(h.reader.counts['ignored'],1)

    def test_legacy_typed_callback_cannot_bypass_native_mode(self):
        for kind in ('ack','bspline','position'):
            with self.subTest(kind=kind):
                h=self.native();self.ready(h)
                {'ack':lambda:h.ack(),'bspline':lambda:h.node.on_bspline(h.curve()),
                 'position':lambda:h.node.on_command(h.command())}[kind]()
                self.assertIsNone(h.node.setpoint);self.assertIsNone(h.node.active_goal)

    def test_pending_new_goal_ignores_old_stream_until_ack_and_curve(self):
        h=self.native();self.ready(h)
        h.node.rotate_command_epoch('goal');h.node.goal_acknowledged=False;h.node.setpoint=None
        h.reader.feed(h.node,self.position(h,2));self.assertIsNone(h.node.setpoint)
        self.acknowledge(h,2);self.curve(h,2);h.reader.feed(h.node,self.position(h,3))
        self.assertIsNotNone(h.node.setpoint)

    def test_stream_fragment_and_unrelated_logs_do_not_drop_a_complete_message(self):
        h=self.native();self.acknowledge(h);self.curve(h)
        event=json.dumps(self.position(h)).encode();p=h.reader.path
        p.write_bytes(b'[INFO] native startup\n'+event[:20]);h.reader.poll(h.node)
        self.assertIsNone(h.node.setpoint)
        with p.open('ab') as f:f.write(event[20:]+b'\n')
        h.reader.poll(h.node)
        self.assertIsNotNone(h.node.setpoint)

    def test_dead_or_stale_channel_does_not_keep_current_point_ready(self):
        for fault in ('dead','stale','bad_json'):
            with self.subTest(fault=fault):
                h=self.native();self.ready(h);h.reader.path.write_bytes(b'')
                if fault=='dead':h.reader.process=types.SimpleNamespace(poll=lambda:1)
                elif fault=='stale':h.wall_ns+=2_000_000_001
                else:h.reader.path.write_bytes(b'{broken\n')
                h.reader.poll(h.node)
                self.assertIsNone(h.node.setpoint);self.assertFalse(h.node.state()['ready'])

    def test_previous_runtime_log_is_not_a_current_heartbeat(self):
        h=self.native()
        fresh=self.module.NativeReceipts(h.reader.path,clock_ns=lambda:h.wall_ns)
        fresh.process=h.reader.process
        fresh.feed(h.node,dict(kind='heartbeat',host_monotonic_ns=h.wall_ns-1,
            publisher_counts=dict(ack=1,bspline=1,position=1)))
        self.assertEqual(fresh.reason(),'native_receipt_waiting')
        self.assertEqual(fresh.counts['ignored'],1)

    def test_connections_must_be_ready_and_stream_reset_invalidates_current_goal(self):
        h=self.native();self.ready(h)
        h.reader.path.write_bytes(json.dumps(dict(kind='heartbeat',host_monotonic_ns=h.wall_ns,
            publisher_counts=dict(ack=0,bspline=0,position=1))).encode()+b'\n')
        h.reader.poll(h.node)
        self.assertIsNone(h.node.setpoint)
        self.assertEqual(h.reader.reason(),'native_receipt_connections_unready')
        h=self.native();self.ready(h)
        h.reader.path.write_bytes(b'[INFO] healthy\n');h.reader.poll(h.node)
        h.reader.path.write_bytes(b'');h.reader.poll(h.node)
        self.assertIsNone(h.node.active_goal)
        self.assertEqual(h.reader.last_error,'native_receipt_stream_restarted')


if __name__=='__main__':unittest.main()
