# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Complete native prefix/stop selection: temporal and occupancy regressions."""
import copy
import importlib.util
from pathlib import Path
import unittest

import numpy as np

HERE = Path(__file__).parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


source = load("stop_test_fixtures", HERE / "test_drone_stop_candidates.py")
module = load("committed_replay", HERE.parent / "workbench-tools/drone-committed-replay.py")


class CommittedReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.good = source.candidates.compare(source.window(), source.LIMITS, [3.5, 1., .4],
            source.NATIVE, source.audit, source.handoff)
        cls.bad = source.candidates.compare(source.window(1.), source.LIMITS, [3.5, 1., .4],
            source.NATIVE, source.audit, source.handoff)
        cls.good["trajectory_id"], cls.bad["trajectory_id"] = 6, 7
        cls.context = {"task_id": "fixture", "scene_revision": "static-test",
                       "clock_id": "sim-epoch-1", "frame_id": "scene_enu_m"}
        cls.cases = module.fixture_scenarios(cls.good, cls.bad, cls.context, source.handoff)

    def replay(self, name):
        engine = module.Replay(self.context, source.LIMITS, source.audit, source.handoff)
        return [engine.step(copy.deepcopy(e)) for e in self.cases[name]]

    def test_rejected_candidate_preserves_absolute_phase_and_stopping_tail(self):
        results = self.replay("reject_preserves_phase_then_brakes")
        self.assertTrue(results[0]["candidate_accepted"])
        self.assertFalse(results[1]["candidate_accepted"])
        self.assertIn("acceleration", results[1]["candidate_rejections"])
        self.assertTrue(results[1]["continue_previous"])
        native = module.complete(self.good)
        np.testing.assert_allclose(results[1]["selected_reference_pva"], source.handoff.pva(native, .2), atol=1e-12)
        self.assertEqual(results[1]["start_sim_s"], self.good["start_sim_s"])
        self.assertEqual(results[-2]["mode"], "braking_tail")
        self.assertEqual(results[-1]["mode"], "terminal_hold")
        self.assertLess(np.max(abs(np.asarray(results[-1]["selected_reference_pva"])[:, 1:])), 1e-8)

    def test_first_tick_and_nan_cannot_erase_admission_clock_anchor(self):
        for name in ("first_tick_rewind", "invalid_clock_does_not_erase_anchor"):
            with self.subTest(name=name):
                results = self.replay(name)
                self.assertTrue(results[0]["candidate_accepted"])
                self.assertEqual(results[-1]["reason"], "clock_rewind")
                self.assertIsNone(results[-1]["selected_reference_pva"])

    def test_pause_retains_phase_but_state_drift_protects(self):
        results = self.replay("paused_clock_then_state_drift")
        np.testing.assert_array_equal(results[1]["selected_reference_pva"], results[2]["selected_reference_pva"])
        self.assertEqual(results[-1]["reason"], "tracking_state_mismatch")

    def test_changed_occupancy_revokes_remaining_curve_and_terminal_hold(self):
        for name in ("new_occupied_remaining_curve", "terminal_region_intrusion"):
            with self.subTest(name=name):
                result = self.replay(name)[-1]
                self.assertEqual(result["mode"], "protect")
                self.assertTrue(result["reason"].startswith("remaining_voxel_"))
                self.assertIsNone(result["selected_reference_pva"])
                self.assertEqual(result["checked_map_revision"], "fixture-intrusion")

    def test_unknown_stale_future_and_short_horizon_are_distinct(self):
        cases = {"unknown_map": "map_unknown", "unknown_free_space": "known_space_unverified",
            "current_snapshot_without_future_coverage": "map_prediction_horizon_unverified",
            "stale_map": "map_stale_or_future", "future_dated_observation": "map_stale_or_future",
            "map_context_changed": "map_context_mismatch"}
        for name, reason in cases.items():
            with self.subTest(name=name):
                result = self.replay(name)[-1]
                self.assertEqual(result["mode"], "protect")
                self.assertIn(reason, result["candidate_rejections"] + [result.get("reason")])
                self.assertIsNone(result["selected_reference_pva"])

    def test_wrong_task_rejection_keeps_valid_old_curve(self):
        result = self.replay("candidate_task_mismatch")[-1]
        self.assertEqual(result["candidate_rejections"], ["candidate_task_mismatch"])
        self.assertEqual(result["plan_id"], "6")
        self.assertTrue(result["continue_previous"])

    def test_future_start_and_absent_backup_do_not_select_reference(self):
        result = self.replay("future_start_rejected")[-1]
        self.assertIn("trajectory_not_current", result["candidate_rejections"])
        self.assertIsNone(result["selected_reference_pva"])
        self.assertEqual(self.replay("no_backup")[-1]["reason"], "no_committed_trajectory")

    def test_mutable_candidate_is_reaudited_and_bad_item_does_not_erase_old_curve(self):
        engine = module.Replay(self.context, source.LIMITS, source.audit, source.handoff)
        first, later = copy.deepcopy(self.cases["reject_preserves_phase_then_brakes"][:2])
        self.assertTrue(engine.step(first)["candidate_accepted"])
        later["candidate"] = copy.deepcopy(self.good)
        # Cached math boolean stays true. An edited coefficient must still fail.
        later["candidate"]["native"]["pieces"][0]["coefficients_descending"][0][-1] += 1.
        result = engine.step(later)
        self.assertFalse(result["candidate_accepted"])
        self.assertFalse(result["candidate_math_gate"]["passed"])
        later["candidate"] = None
        result = engine.step(later)
        self.assertEqual(result["candidate_rejections"], ["malformed_candidate"])
        self.assertEqual(result["mode"], "track")


if __name__ == "__main__":
    unittest.main()
