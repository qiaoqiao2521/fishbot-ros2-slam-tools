"""Native-message-shaped first-curve reordering; real temporary Sidecar methods."""
import json
from pathlib import Path
import tempfile
import types
import unittest
import numpy as np
from scipy.interpolate import BSpline

import test_drone_command_validity as original
import test_drone_command_epoch_patch as epochs


class AckHarness:
    def __init__(self, fixture, runtime):
        self.node, self.clock = fixture.node()
        self.node.args.runtime = runtime
        self.node.setpoint, self.node.goal_acknowledged = None, False
        self.node.goal_stamp_ns, self.node.min_trajectory_id = 123, 1
        self.node.trajectory_times.clear()
        namespace = self.node.state.__func__.__globals__
        namespace.update(np=np, BSpline=BSpline, json=json)
        self.node.on_bspline = types.MethodType(original.methods(fixture.root/'ego/sidecar.py', 'Sidecar',
            ('on_bspline',), namespace)['on_bspline'], self.node)

    def curve(self, identity=1, start=10., points=None, knots=None):
        stamp=int(round(start*1e9))
        points=points or [[0.,0.,1.],[.2,0.,1.],[.4,0.,1.],[.6,0.,1.],[.8,0.,1.],[1.,0.,1.]]
        return types.SimpleNamespace(traj_id=identity,order=3,
            start_time=types.SimpleNamespace(sec=stamp//10**9,nanosec=stamp%10**9),
            knots=knots or [-.6,-.4,-.2,0.,.2,.4,.6,.8,1.,1.2],
            pos_pts=[types.SimpleNamespace(x=p[0],y=p[1],z=p[2]) for p in points])

    def ack(self, floor=0, stamp=123):
        self.node.on_goal_ack(types.SimpleNamespace(data=f'{stamp}:{floor}'))

    def command(self, identity=1):
        v=types.SimpleNamespace(x=.2,y=0.,z=1.)
        return types.SimpleNamespace(trajectory_id=identity,position=v,velocity=v,acceleration=v,
            yaw=0.,header=types.SimpleNamespace(stamp=types.SimpleNamespace(sec=10,nanosec=150000000)))


class AckCurveBuffer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        epochs.CommandEpochPatch.setUpClass()
        cls.fixture=epochs.CommandEpochPatch()

    @classmethod
    def tearDownClass(cls):
        epochs.CommandEpochPatch.tearDownClass()

    def harness(self):
        d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup)
        return AckHarness(self.fixture,Path(d.name))

    def test_first_curve_before_ack_is_available_without_second_curve_publication(self):
        h=self.harness();h.node.on_bspline(h.curve())
        self.assertEqual(h.node.trajectory_times,{})
        h.node.on_command(h.command())
        self.assertIsNone(h.node.setpoint)
        h.ack()
        h.node.on_command(h.command())
        self.assertIsNotNone(h.node.setpoint)
        self.assertEqual(h.node.setpoint['trajectory_id'],1)
        self.assertEqual(h.node.setpoint['source_start_sim_s'],10.)

    def test_ack_floor_discards_old_curve_and_replays_only_newer_id(self):
        h=self.harness()
        for identity in (1,2,3):h.node.on_bspline(h.curve(identity))
        h.ack(floor=2)
        self.assertEqual(set(h.node.trajectory_times),{3})
        h.node.on_command(h.command(2));self.assertIsNone(h.node.setpoint)
        h.node.on_command(h.command(3));self.assertEqual(h.node.setpoint['trajectory_id'],3)

    def test_wrong_ack_does_not_release_and_goal_rotation_drops_pending(self):
        h=self.harness();h.node.on_bspline(h.curve())
        h.ack(stamp=122);self.assertEqual(h.node.trajectory_times,{})
        h.node.rotate_command_epoch('goal')
        h.node.goal_stamp_ns=124
        h.ack(stamp=124)
        self.assertEqual(h.node.trajectory_times,{})
        self.assertIsNone(h.node.latest_trajectory)

    def test_rewind_and_clock_stall_drop_waiting_curve(self):
        for kind in ('rewind','stall'):
            with self.subTest(kind=kind):
                h=self.harness();h.node.on_bspline(h.curve())
                if kind=='rewind':h.clock.sim-=.01
                else:h.clock.wall+=3.
                h.node.state();h.ack()
                self.assertEqual(h.node.trajectory_times,{})
                self.assertIsNone(h.node.latest_trajectory)

    def test_replayed_diagnostic_keeps_original_receipt_and_source_time(self):
        h=self.harness();h.node.on_bspline(h.curve(start=9.9))
        h.clock.sim+=.1;h.ack()
        events=[json.loads(x) for x in (h.node.args.runtime/'trajectory-events.jsonl').read_text().splitlines()]
        self.assertEqual(events[0]['received_sim_s'],10.15)
        self.assertAlmostEqual(events[0]['ack_replayed_sim_s'],10.25)
        self.assertEqual(events[0]['start_sim_s'],9.9)
        self.assertEqual(h.node.trajectory_times[1],(9.9,10.5))

    def test_disabled_epoch_preserves_original_unacknowledged_curve_registration(self):
        h=self.harness();h.node.command_epoch.enabled=False
        h.node.on_bspline(h.curve())
        self.assertEqual(set(h.node.trajectory_times),{1})
        events=[json.loads(x) for x in (h.node.args.runtime/'trajectory-events.jsonl').read_text().splitlines()]
        self.assertNotIn('ack_replayed_sim_s',events[0])

    def test_pending_buffer_is_bounded_and_normal_ack_first_still_works(self):
        h=self.harness()
        for identity in range(1,26):h.node.on_bspline(h.curve(identity))
        self.assertLessEqual(len(h.node.pending_ack_curves),20)
        h.ack();self.assertEqual(h.node.latest_trajectory['trajectory_id'],25)
        h.node.on_bspline(h.curve(26));h.node.on_command(h.command(26))
        self.assertEqual(h.node.setpoint['trajectory_id'],26)


if __name__=='__main__':unittest.main()
