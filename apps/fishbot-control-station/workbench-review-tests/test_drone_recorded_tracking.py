# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Source-time association and unavailable-state evidence must remain honest."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np


TOOLS = Path(__file__).parents[1] / "workbench-tools"


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / (name+".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


module = load("drone-recorded-tracking")
curve, _ = load("drone-trajectory-primitives").reuse(Path.home()/"dev/ros2/projects/drone")


def record(identity=1, received=0., offset=0., start=0.):
    return {"trajectory_id": identity, "received_sim_s": received, "start_sim_s": start,
        "source_line": identity, "task_id": "task-fixture", "order": 3,
        "knots": [0., 0., 0., 0., 10., 10., 10., 10.],
        "control_points": [[offset, 0., 1.5], [offset+10/3, 0., 1.5],
                           [offset+20/3, 0., 1.5], [offset+10., 0., 1.5]]}


def state(stamp, available=None):
    return {"source_sim_s": stamp, "source_stamp_ns": str(round(stamp*1e9)),
        "available_by_sim_s": stamp if available is None else available, "record_time_ns": "123456789",
        "epoch": 0, "frame_id": "world", "velocity_frame_id": "world",
        "position": [stamp, 0., 1.5], "velocity": [1., 0., 0.], "acceleration": None}


def log():
    return {"fsm": [], "callbacks": []}


class RecordedTrackingTests(unittest.TestCase):
    def analyze(self, states, curves=None, events=None, single_epoch=True):
        return module.analyze(states, curves or [record()], events or log(),
            "task-fixture", 4., curve, single_epoch)

    def test_source_alignment_uses_available_curve_and_excludes_failure_tail(self):
        result = self.analyze([state(1.), state(2.), state(4.)],
            [record(), record(2, received=1.5, offset=100., start=1.5)])
        self.assertEqual([r["trajectory_id"] for r in result["tracking"]], [1, 2])
        self.assertLess(np.linalg.norm(result["tracking"][0]["position_error_xyz"]), 1e-12)
        self.assertGreater(np.linalg.norm(result["tracking"][1]["position_error_xyz"]), 90.)
        self.assertEqual(result["excluded"]["not_strictly_before_primary_failure"], 1)

    def test_unattributed_replacement_does_not_fall_back_to_old_curve(self):
        second = {**record(2, received=1.5), "task_id": None}
        result = self.analyze([state(1.), state(2.)], [record(), second])
        self.assertEqual(len(result["tracking"]), 1)
        self.assertEqual(result["excluded"]["no_attributed_active_curve"], 1)

    def test_recorder_availability_does_not_import_a_future_state(self):
        result = self.analyze([state(.8, 1.), state(1., 1.2)], [record(received=1.1)])
        receipt = result["curve_receipts"][0]
        self.assertEqual(receipt["latest_recorder_available_pv"]["source_sim_s"], .8)
        self.assertAlmostEqual(receipt["state_source_age_at_curve_receipt_s"], .3)
        self.assertIsNone(receipt["acceleration"])
        self.assertFalse(receipt["full_pva_qualified"])

    def test_fsm_mixed_time_gap_and_same_stamp_gap_are_separate(self):
        events = log()
        events["fsm"] = [{"sim": 2., "trajectory": 1, "odom_source": 1.,
            "odom_p": [1., 0., 1.5], "odom_v": [1., 0., 0.], "ref_p": [2., 0., 1.5]}]
        events["callbacks"] = [{"kind": "front", "source": 1.7, "end": 1.95},
                                 {"kind": "front", "source": 1.8, "end": 2.05}]
        row = self.analyze([state(1.)], events=events)["fsm"][0]
        self.assertEqual(row["mixed_time_position_gap_m"], 1.)
        self.assertLess(row["same_stamp_position_gap_m"], 1e-12)
        self.assertEqual(row["latest_completed_callbacks"]["front"]["end"], 1.95)
        np.testing.assert_allclose(row["bag_pv_match_error"], [0., 0.], atol=1e-12)

    def test_new_curve_is_not_extrapolated_backwards_to_old_odometry(self):
        events = log()
        events["fsm"] = [{"sim": 2., "trajectory": 1, "odom_source": 1.4,
            "odom_p": [1.4, 0., 1.5], "odom_v": [1., 0., 0.], "ref_p": [2., 0., 1.5]}]
        row = self.analyze([state(1.4)], [record(start=1.5, received=1.5)], events)["fsm"][0]
        self.assertIsNone(row["same_stamp_position_gap_m"])
        self.assertIn("no backwards extrapolation", row["alignment"])

    def test_clock_epoch_and_frame_ambiguity_do_not_produce_tracking_stats(self):
        self.assertEqual(self.analyze([state(1.)], single_epoch=False)["tracking_summary"]["samples"], 0)
        invalid = {**state(1.), "velocity_frame_id": "body"}
        self.assertEqual(self.analyze([invalid])["excluded"]["frame_unverified"], 1)

    def test_fsm_cannot_use_curve_received_after_its_start(self):
        events = log()
        events["fsm"] = [{"sim": 2., "trajectory": 1, "odom_source": 1.,
            "odom_p": [1., 0., 1.5], "odom_v": [1., 0., 0.], "ref_p": [2., 0., 1.5]}]
        row = self.analyze([state(1.)], [record(received=3.)], events)["fsm"][0]
        self.assertIsNone(row["same_stamp_position_gap_m"])

    def test_fsm_frame_ambiguity_cannot_be_hidden_by_matching_numbers(self):
        events = log()
        events["fsm"] = [{"sim": 2., "trajectory": 1, "odom_source": 1.,
            "odom_p": [1., 0., 1.5], "odom_v": [1., 0., 0.], "ref_p": [2., 0., 1.5]}]
        row = self.analyze([{**state(1.), "velocity_frame_id": "body"}], events=events)["fsm"][0]
        self.assertIsNone(row["same_stamp_position_gap_m"])
        self.assertNotIn("bag_pv_match_error", row)

    def test_partial_log_keeps_warning_and_does_not_invent_map(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory)/"planner.log"
            file.write_text('InflatedVoxelTransition {bad}\nFSMStart sim=1\n')
            result = module.log_evidence(file)
        self.assertEqual(len(result["warnings"]), 2)
        self.assertEqual(result["fsm"], [])
        self.assertEqual(result["voxel_events"], 0)


if __name__ == "__main__":
    unittest.main()
