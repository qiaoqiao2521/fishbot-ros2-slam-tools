# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Conditional boundary sensitivity and the existing selector's time contract."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


fixture = load("geometry_fixtures", HERE/"test_drone_stop_geometry.py")
module = load("stop_qualification", HERE.parent/"workbench-tools/drone-stop-qualification.py")
tracking_fixture = load("tracking_fixtures", HERE/"test_drone_recorded_tracking.py")


def past_case(source_s=1., previous_s=.8, available_s=1.1):
    anchor, previous = tracking_fixture.state(source_s), tracking_fixture.state(previous_s)
    anchor["velocity"] = [1., .4, 0.]; previous["velocity"] = [1., .5, 0.]
    estimate = module.geometry.tracking.predict_pv(anchor, source_s, "causal_acceleration", previous)
    return {"kind": "fsm", "input_state": anchor, "previous_available_state": previous,
        "forecast_at_sim_s": available_s, "models": {"causal_acceleration": estimate}}


class BoundaryProfileTests(unittest.TestCase):
    def test_past_a_is_held_from_available_past_and_never_called_measured(self):
        evidence = {"archive_task_id": "fixture", "forecast": {"cases": [past_case()]}}
        profile = module.profiles(evidence, "fixture", 1.3, 1.2)[1]
        np.testing.assert_allclose(profile["acceleration"], [0., -.5, 0.])
        self.assertAlmostEqual(profile["held_from_A_source_s"], .3)
        self.assertIn("neither measured", profile["scope"])
        base = fixture.boundary(); before = copy.deepcopy(base)
        request = module.hypothesis_request(base, profile)
        self.assertEqual(base, before)
        np.testing.assert_array_equal(np.asarray(request["initial_pva"])[:, :2], np.asarray(base["initial_pva"])[:, :2])

    def test_malformed_future_or_unavailable_past_only_unqualifies_optional_profile(self):
        bad_case = past_case(); bad_case["previous_available_state"]["available_by_sim_s"] = 2.
        inputs = [None, {"archive_task_id": "other"},
            {"archive_task_id": "fixture", "forecast": None},
            {"archive_task_id": "fixture", "forecast": []},
            {"archive_task_id": "fixture", "forecast": {"cases": None}},
            {"archive_task_id": "fixture", "forecast": {"cases": [{}, bad_case, past_case(1.4, 1.3, 1.5)]}}]
        for evidence in inputs:
            with self.subTest(evidence=evidence):
                result = module.profiles(evidence, "fixture", 1.3, 1.2)
                self.assertEqual(result[1]["status"], "unscored")
                self.assertNotIn("status", result[0])

    def test_parent_specific_boundary_can_precede_event_and_excludes_later_case(self):
        evidence = {"archive_task_id": "fixture", "forecast": {"cases": [past_case(), past_case(1.4, 1.3, 1.5)]}}
        earlier = module.profiles(evidence, "fixture", 1.3, 2.)[1]
        later = module.profiles(evidence, "fixture", 1.7, 1.6)[1]
        self.assertEqual(earlier["A_source_sim_s"], 1.)
        self.assertEqual(later["A_source_sim_s"], 1.4)

        delayed = past_case(); delayed["input_state"]["available_by_sim_s"] = 2.
        data = {"archive_task_id": "fixture", "forecast": {"cases": [delayed]}}
        self.assertEqual(module.profiles(data, "fixture", 1.3, 1.2)[1]["status"], "unscored")
        delayed["input_evidence"] = "FSM logged consumed PV"
        self.assertEqual(module.profiles(data, "fixture", 1.3, 1.2)[1]["A_source_sim_s"], 1.)


@unittest.skipUnless(fixture.NATIVE.exists(), "existing offline MINCO executable unavailable")
class StopTemporalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit, cls.handoff = module.committed.reuse(fixture.ROOT)
        cls.good = module.geometry.search(fixture.boundary(), fixture.BOX, fixture.LIMITS, fixture.NATIVE, cls.audit)["candidate"]
        cls.task = "fixture-qualification"; cls.start = 33.428
        cls.report = module.temporal_replay(cls.good, cls.task, cls.start, fixture.BOX, fixture.LIMITS, cls.audit, cls.handoff)
        cls.scenarios = {r["name"]: r["events"] for r in cls.report["scenarios"]}

    def engine_and_candidate(self, candidate=None):
        row = {"kind": "axis_stop_geometry_candidate", "recorded_task_id": self.task,
            "trajectory_id": "test-brake", "request": copy.deepcopy((candidate or self.good)["request"]),
            "native": copy.deepcopy((candidate or self.good)["native"]), "hard_box": fixture.BOX, "start_sim_s": self.start}
        engine = module.committed.Replay(self.report["context"], fixture.LIMITS, self.audit, self.handoff)
        return engine, row

    def test_actual_duration_requires_full_curve_and_finite_terminal_window(self):
        self.assertAlmostEqual(self.report["curve_duration_sim_s"], 5.)
        self.assertAlmostEqual(self.report["required_until_at_admission_sim_s"], self.start+5.5)
        events = self.scenarios["sufficient_declared_horizon"]
        self.assertTrue(events[0]["result"]["candidate_accepted"])
        self.assertEqual([e["result"]["mode"] for e in events], ["track", "track", "braking_tail", "terminal_hold"])
        self.assertEqual(self.report["execution_admission"], "not_performed")

    def test_unknown_state_map_expiry_and_late_head_do_not_select_a_reference(self):
        expected = {"fresh_current_snapshot_only": "map_prediction_horizon_unverified",
            "curve_covered_terminal_window_missing": "map_prediction_horizon_unverified",
            "finite_terminal_window_expires": "map_prediction_horizon_unverified",
            "known_space_unverified": "known_space_unverified", "stale_observation": "map_stale_or_future",
            "measured_A_unknown": "invalid_clock_or_state", "late_submission_old_head": "handoff_state_mismatch",
            "observed_A_changed": "tracking_state_mismatch", "clock_context_changed": "map_context_mismatch"}
        for name, reason in expected.items():
            with self.subTest(name=name):
                result = self.scenarios[name][-1]["result"]
                self.assertIsNone(result["selected_reference_pva"])
                self.assertIn(reason, result.get("candidate_rejections", [])+[result.get("reason")])
        result = self.scenarios["terminal_occupied"][-1]["result"]
        self.assertIsNone(result["selected_reference_pva"])
        self.assertTrue(any(r.startswith("remaining_voxel_") for r in result["candidate_rejections"]))

    def test_wall_elapsed_never_advances_paused_sim_phase(self):
        events = self.scenarios["paused_sim_despite_wall_elapsed"]
        self.assertEqual(events[0]["input"]["now_sim_s"], events[1]["input"]["now_sim_s"])
        np.testing.assert_array_equal(events[0]["result"]["selected_reference_pva"], events[1]["result"]["selected_reference_pva"])

    def test_new_entry_reaudits_mutation_and_keeps_old_absolute_phase(self):
        engine, row = self.engine_and_candidate()
        cases = module.temporal_scenarios(row, self.report["context"], fixture.BOX, self.handoff)
        initial = copy.deepcopy(cases["sufficient_declared_horizon"][0])
        self.assertTrue(engine.step(initial)["candidate_accepted"])
        later = copy.deepcopy(cases["sufficient_declared_horizon"][1]); later["candidate"] = copy.deepcopy(row)
        later["candidate"]["native"]["pieces"][0]["coefficients_descending"][0][-1] += 1.
        later["candidate"]["cached_passed"] = True
        result = engine.step(later)
        self.assertFalse(result["candidate_accepted"])
        self.assertTrue(result["continue_previous"])
        self.assertEqual(result["start_sim_s"], self.start)
        np.testing.assert_allclose(result["selected_reference_pva"], self.handoff.pva(self.good["native"], .2), atol=1e-12)

    def test_duration_comes_from_pieces_not_axis_time_metadata(self):
        candidate = copy.deepcopy(self.good)
        endpoint = candidate["request"]["stop_positions"]
        constant = np.zeros((3, 8)); constant[:, -1] = endpoint
        candidate["native"]["pieces"].append({"duration": 1., "coefficients_descending": constant.tolist()})
        engine, row = self.engine_and_candidate(candidate)
        event = module.temporal_scenarios(row, self.report["context"], fixture.BOX, self.handoff)["curve_covered_terminal_window_missing"][0]
        event["snapshot"]["valid_until_sim_s"] = self.start+5.5
        result = engine.step(event)
        self.assertFalse(result["candidate_accepted"])
        self.assertIn("map_prediction_horizon_unverified", result["candidate_rejections"])
        self.assertAlmostEqual(self.handoff.duration(row["native"]), 6.)
        self.assertAlmostEqual(max(row["request"]["axis_stop_durations_xyz"]), 5.)

    def test_new_entry_requires_stop_mode_and_zero_terminal_jerk(self):
        engine, row = self.engine_and_candidate(); row["request"]["mode"] = "different-mode"
        _, gate = engine.score(row)
        self.assertIn("axis_stop_contract", gate["failed_checks"])
        request = copy.deepcopy(row["request"]); request["mode"] = "axis_stop"
        coefficients = np.zeros((3, 8)); coefficients[:, -1] = [4.999, 0., 1.5]
        coefficients[0, -4:-1] = [.001, -.003, .003]
        request.update(initial_pva=[[4.999, .003, -.006], [0., 0., 0.], [1.5, 0., 0.]],
            initial_jerk=[.006, 0., 0.], terminal_pva=[[5., 0., 0.], [0., 0., 0.], [1.5, 0., 0.]],
            terminal_jerk=[.006, 0., 0.], original_local_target=[5., 0., 1.5])
        native = {"native_success": True, "pieces": [{"duration": 1., "coefficients_descending": coefficients.tolist()}]}
        self.assertTrue(self.audit.audit_trajectory(native, request, [], fixture.LIMITS, fixture.BOX)["passed"])
        _, gate = engine.score({**row, "request": request, "native": native})
        self.assertIn("axis_stop_contract", gate["failed_checks"])

    def test_nonpositive_piece_time_is_rejected_by_existing_auditor(self):
        engine, row = self.engine_and_candidate(); row["native"]["pieces"][0]["duration"] = -1.
        event = module.temporal_scenarios(self.engine_and_candidate()[1], self.report["context"], fixture.BOX, self.handoff)["sufficient_declared_horizon"][0]
        event["candidate"] = row
        result = engine.step(event)
        self.assertFalse(result["candidate_accepted"])
        self.assertIn("malformed_candidate", result["candidate_rejections"])

    def test_nonzero_hypothesis_is_reconstructed_and_can_fail_original_gate(self):
        profile = {"scope": "synthetic A_y=.2", "acceleration": [0., .2, 0.], "jerk": [0.]*3}
        request = module.hypothesis_request(self.good["request"], profile)
        result = module.geometry.tracking.audit_axis_request(request, fixture.BOX, fixture.LIMITS, fixture.NATIVE, self.audit)
        self.assertLess(result["audit"]["boundary_pva_error"], 1e-8)
        self.assertIn("acceleration", result["audit"]["failed_checks"])
        self.assertGreater(result["audit"]["acceleration_max"], 1.)

    def test_bad_hypothesis_row_does_not_stop_other_rows(self):
        good = {"variant": "actual-counterfactual", "pv_at_sim_s": self.start, "event_sim_s": self.start-.008,
            "input_role": "retrospective counterfactual", "candidate": self.good}
        malformed = {"variant": "incomplete", "candidate": {}}
        data = {"archive_task_id": self.task, "hard_box": fixture.BOX, "hard_limits": fixture.LIMITS, "rows": [malformed, good]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"geometry.json"; path.write_text(json.dumps(data))
            with patch('builtins.print'):
                result = module.run(path, fixture.ROOT, fixture.NATIVE)
        self.assertEqual(result["rows"][0]["status"], "unscored")
        self.assertEqual(len(result["rows"]), 6)
        self.assertTrue(next(r for r in result["rows"] if r.get("profile", {}).get("name") == "source_boundary")["fixed"]["audit"]["passed"])
        self.assertEqual(result["actual_qualification"]["measured_A_J"], "unrecorded")


if __name__ == "__main__":
    unittest.main()
