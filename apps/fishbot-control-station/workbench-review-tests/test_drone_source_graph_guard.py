"""Observed graph continuity on real temporary Sidecar methods, not DDS attestation."""
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import test_drone_command_validity as original
import test_drone_command_epoch_patch as epochs
from test_drone_ack_curve_buffer import AckHarness


class SourceGraphGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        epochs.CommandEpochPatch.setUpClass()
        cls.fixture=epochs.CommandEpochPatch()

    @classmethod
    def tearDownClass(cls):
        epochs.CommandEpochPatch.tearDownClass()

    def harness(self):
        d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup)
        h=AckHarness(self.fixture,Path(d.name))
        h.node.command_epoch.source_graph_enabled=True
        h.node.source_expected_nodes={'ack':'planner_owned','bspline':'planner_owned','position':'trajectory_owned'}
        h.graph={k:[types.SimpleNamespace(node_name=name,node_namespace='/',endpoint_gid=bytes([i+1])*16)]
                 for i,(k,name) in enumerate(h.node.source_expected_nodes.items())}
        topics={'/drone/ego/goal_ack':'ack','/drone/ego/bspline':'bspline','/drone/ego/position_cmd':'position'}
        h.node.get_publishers_info_by_topic=lambda topic: h.graph[topics[topic]]
        ns=h.node.state.__func__.__globals__
        for name,method in original.methods(self.fixture.root/'ego/sidecar.py',
            'Sidecar',('observe_source_graph','invalidate_command_source'),ns).items():
            setattr(h.node,name,types.MethodType(method,h.node))
        h.ack();h.node.on_bspline(h.curve());h.node.on_command(h.command())
        return h

    def test_source_flag_enables_epoch_and_defaults_off(self):
        for setting in (None,'0','1'):
            with self.subTest(setting=setting),patch.dict(os.environ,{},clear=True):
                if setting is not None:os.environ['DRONE_SOURCE_GRAPH']=setting
                e=self.fixture.module.CommandEpoch()
                self.assertEqual(e.source_graph_enabled,setting=='1')
                self.assertEqual(e.enabled,setting=='1')

    def test_healthy_binding_preserves_current_goal_and_setpoint(self):
        h=self.harness();token=h.node.command_epoch.token
        self.assertIsNotNone(h.node.setpoint)
        self.assertTrue(h.node.state()['ready'])
        self.assertEqual(h.node.command_epoch.token,token)

    def test_each_multiple_publisher_topic_invalidates_once_and_clears_pending_work(self):
        for kind in ('ack','bspline','position'):
            with self.subTest(kind=kind):
                h=self.harness();old=h.node.command_epoch.token
                h.node.requests.put({'type':'goal','goal_id':'old'})
                h.node.pending_ack_curves={8:{'message':'old'}}
                h.graph[kind].append(types.SimpleNamespace(node_name='other',node_namespace='/',endpoint_gid=b'x'*16))
                state=h.node.state();changed=h.node.command_epoch.token
                self.assertFalse(state['ready'])
                self.assertNotEqual(changed,old)
                self.assertIsNone(h.node.active_goal);self.assertIsNone(h.node.setpoint)
                self.assertFalse(h.node.goal_acknowledged)
                self.assertEqual(h.node.trajectory_times,{})
                self.assertEqual(h.node.pending_ack_curves,{})
                self.assertTrue(h.node.requests.empty())
                h.node.state();self.assertEqual(h.node.command_epoch.token,changed)
                self.assertEqual(h.node.stops,['123'])

    def test_same_name_new_gid_needs_a_new_goal_and_matching_ack(self):
        h=self.harness();old=h.node.command_epoch.token
        h.graph['bspline'][0].endpoint_gid=b'n'*16
        h.node.on_command(h.command())
        self.assertNotEqual(h.node.command_epoch.token,old)
        self.assertIsNone(h.node.setpoint)
        h.ack();h.node.on_bspline(h.curve());h.node.on_command(h.command())
        self.assertIsNone(h.node.setpoint)
        # Restored healthy inputs allow a new independent goal; no runtime restart lock.
        reply=self.fixture.post(h.node,'/goal',dict(x=5.,y=0.,z=1.,task_id='task-A',goal_id='goal-B'))
        self.assertEqual(reply[0][0],202)
        h.ack(stamp=123);self.assertFalse(h.node.goal_acknowledged)
        h.node.on_bspline(h.curve())
        h.ack(stamp=h.node.goal_stamp_ns);h.node.on_command(h.command())
        self.assertEqual(h.node.setpoint['goal_id'],'goal-B')

    def test_unavailable_graph_wrong_node_namespace_and_zero_gid_preserve_reason(self):
        for fault in ('missing','node','namespace','gid','unavailable'):
            with self.subTest(fault=fault):
                h=self.harness()
                if fault=='missing':h.graph['bspline']=[]
                elif fault=='node':h.graph['bspline'][0].node_name='unknown'
                elif fault=='namespace':h.graph['bspline'][0].node_namespace='/other'
                elif fault=='gid':h.graph['bspline'][0].endpoint_gid=bytes(16)
                else:
                    def fail(_):raise RuntimeError('fixture_graph_error')
                    h.node.get_publishers_info_by_topic=fail
                state=h.node.state()
                self.assertFalse(state['ready']);self.assertIsNone(state['setpoint'])
                if fault=='unavailable':self.assertIn('fixture_graph_error',state['source_graph']['observed']['error'])

    def test_disabled_guard_retains_existing_behavior_and_schema(self):
        h=self.harness();h.node.command_epoch.source_graph_enabled=False
        h.graph['bspline']=[]
        h.node.on_bspline(h.curve());h.node.on_command(h.command())
        self.assertTrue(h.node.state()['ready'])
        self.assertNotIn('source_graph',h.node.state())

    def test_known_gap_queued_message_origin_is_not_visible_in_current_graph(self):
        h=self.harness()
        # A gone foreign writer can leave a queued message. The callback has no GID.
        curve=h.curve(points=[[10.+.2*i,0.,1.] for i in range(6)])
        h.node.on_bspline(curve)
        self.assertGreater(h.node.latest_trajectory['control_points'][0][0],5.)
        self.assertIsNotNone(h.node.active_goal)


if __name__=='__main__':unittest.main()
