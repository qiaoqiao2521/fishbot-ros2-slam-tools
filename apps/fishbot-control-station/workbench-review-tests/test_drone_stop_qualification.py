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


class EarlierHandoffTests(unittest.TestCase):
    def evidence(self):
        case = past_case(1., .8, 1.3)
        case["input_state"]["available_by_sim_s"] = 1.02
        case["previous_available_state"]["available_by_sim_s"] = .82
        oracles = [{"oracle_source_sim_s": t, "oracle_position": [2.+t, 1., 1.8],
            "oracle_velocity": [1., .4, 0.]} for t in [1.1, 1.2]]
        return {"archive_task_id": "fixture", "forecast": {"cases": [case, *oracles]}}

    def source(self, directory):
        original = {"archive_task_id": "fixture", "hard_box": fixture.BOX, "hard_limits": fixture.LIMITS,
            "rows": [None, {"variant": "cached_source_pv", "pv_at_sim_s": 1.,
                "baseline": {"request": fixture.boundary()}}]}
        path = Path(directory)/"geometry.json"; path.write_text(json.dumps(original))
        return path

    def test_recorder_available_prediction_is_not_earlier_fsm_consumption(self):
        data = self.evidence(); before = copy.deepcopy(data)
        inputs = module.handoff_inputs(data, "fixture", 1., 1.1)
        predicted = inputs["causal_acceleration"]
        self.assertEqual(predicted["status"], "qualified_counterfactual")
        self.assertEqual(predicted["available_by_sim_s"], 1.02)
        self.assertEqual(predicted["pair_locator_fsm_sim_s"], 1.3)
        self.assertIn("not earlier planner consumption", predicted["scope"])
        self.assertEqual(data, before)

    def test_future_wrong_frame_or_conflicting_pair_does_not_qualify_prediction(self):
        original = self.evidence()
        for change in ["future", "previous_future", "previous_missing", "frame", "epoch", "conflict"]:
            data = copy.deepcopy(original); case = data["forecast"]["cases"][0]
            if change == "future": case["input_state"]["available_by_sim_s"] = 1.2
            elif change == "previous_future": case["previous_available_state"]["available_by_sim_s"] = 1.2
            elif change == "previous_missing": case["previous_available_state"].pop("available_by_sim_s")
            elif change == "frame": case["input_state"]["velocity_frame_id"] = "body"
            elif change == "epoch": case["previous_available_state"]["epoch"] = 1
            else:
                other = copy.deepcopy(case); other["input_state"]["velocity"][1] += .1
                data["forecast"]["cases"].append(other)
            with self.subTest(change=change):
                inputs = module.handoff_inputs(data, "fixture", 1., 1.1)
                self.assertEqual(inputs["causal_acceleration"]["status"], "unscored")
                self.assertEqual(inputs["retrospective_source_pv"]["status"], "qualified_counterfactual")

    def test_oracle_edits_or_conflicts_never_change_prediction(self):
        data = self.evidence(); first = module.handoff_inputs(data, "fixture", 1., 1.1)
        data["forecast"]["cases"][1]["oracle_position"][0] += 10.
        changed = module.handoff_inputs(data, "fixture", 1., 1.1)
        self.assertEqual(first["causal_acceleration"], changed["causal_acceleration"])
        self.assertNotEqual(first["retrospective_source_pv"]["position"], changed["retrospective_source_pv"]["position"])
        duplicate = copy.deepcopy(data["forecast"]["cases"][1]); duplicate["oracle_velocity"][0] += .1
        data["forecast"]["cases"].append(duplicate)
        conflicted = module.handoff_inputs(data, "fixture", 1., 1.1)
        self.assertEqual(conflicted["causal_acceleration"], first["causal_acceleration"])
        self.assertEqual(conflicted["retrospective_source_pv"]["status"], "unscored")

    def test_nearby_source_and_other_task_are_not_exact_counterfactual_inputs(self):
        data = self.evidence(); data["forecast"]["cases"][1]["oracle_source_sim_s"] += .001
        inputs = module.handoff_inputs(data, "fixture", 1., 1.1)
        self.assertEqual(inputs["retrospective_source_pv"]["status"], "unscored")
        self.assertEqual(inputs["causal_acceleration"]["status"], "qualified_counterfactual")
        wrong = module.handoff_inputs(data, "other-task", 1., 1.1)
        self.assertTrue(all(r["status"] == "unscored" for r in wrong.values()))

    def test_each_boundary_is_resolved_from_its_pv_with_the_same_profile(self):
        calls = []
        def search(request, box, limits, executable, audit):
            calls.append(copy.deepcopy(request))
            self.assertEqual(box, fixture.BOX); self.assertEqual(limits, fixture.LIMITS)
            return {"status": "unscored", "reason": "generation stub; not an audited curve"}
        evidence = self.evidence()
        with tempfile.TemporaryDirectory() as directory:
            path = self.source(directory); before = path.read_text()
            with patch.object(module.geometry, "search", side_effect=search):
                result = module.compare_handoffs(path, fixture.ROOT, fixture.NATIVE, evidence, [1.1, 1.2])
            self.assertEqual(path.read_text(), before)
        self.assertEqual(len(calls), 10)
        for i, at in enumerate([1.1, 1.2]):
            inputs = module.handoff_inputs(evidence, "fixture", 1., at)
            for j, (variant, profile) in enumerate(result["selected_profiles"]):
                request = calls[i*5+j]; pv = np.asarray(request["initial_pva"])
                np.testing.assert_array_equal(pv[:, :2], np.column_stack([inputs[variant]["position"], inputs[variant]["velocity"]]))
                if profile == "outward_y_A": np.testing.assert_array_equal(pv[:, 2], [0., .2, 0.])
                if profile == "outward_y_J": self.assertEqual(request["initial_jerk"], [0., 1., 0.])
        self.assertNotEqual(calls[0]["initial_pva"], calls[5]["initial_pva"])
        self.assertEqual(result["execution_admission"], "not_performed")

    def test_missing_oracle_and_invalid_time_only_skip_affected_items(self):
        evidence = self.evidence(); evidence["forecast"]["cases"] = evidence["forecast"]["cases"][:1]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(module.geometry, "search", return_value={"status": "unscored"}) as search, patch('builtins.print'):
                result = module.compare_handoffs(self.source(directory), fixture.ROOT, fixture.NATIVE,
                    evidence, [float("nan"), 1.1])
        self.assertEqual(search.call_count, 2)
        self.assertEqual(len(result["rows"]), 5)
        self.assertEqual(result["boundary_times_sim_s"], [1.1])
        self.assertEqual(len(result["excluded"]), 1)
        self.assertTrue(all(r["status"] == "unscored" for r in result["rows"] if r["variant"] == "retrospective_source_pv"))
        json.dumps(result, allow_nan=False)

    def test_missing_past_evidence_has_no_fabricated_comparisons(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(module.geometry, "search") as search, patch('builtins.print'):
                result = module.compare_handoffs(self.source(directory), fixture.ROOT, fixture.NATIVE, None, [1.1])
        search.assert_not_called()
        self.assertEqual(len(result["rows"]), 5)
        self.assertTrue(all(r["status"] == "unscored" for r in result["rows"]))

    @unittest.skipUnless(fixture.NATIVE.exists(), "existing offline MINCO executable unavailable")
    def test_late_curve_relabel_does_not_preserve_an_earlier_boundary(self):
        audit, _ = module.committed.reuse(fixture.ROOT)
        candidate = module.geometry.search(fixture.boundary(), fixture.BOX, fixture.LIMITS, fixture.NATIVE, audit)["candidate"]
        peak = module.acceleration_peak(candidate["native"], audit)
        self.assertAlmostEqual(np.linalg.norm(peak["vector_m_s2"]), peak["value"], places=10)
        self.assertAlmostEqual(peak["value"], candidate["audit"]["acceleration_max"], places=10)
        earlier = copy.deepcopy(candidate["request"]); earlier["initial_pva"][0][0] -= .1
        gate = audit.audit_trajectory(candidate["native"], earlier, [], fixture.LIMITS, fixture.BOX)
        self.assertFalse(gate["passed"])
        self.assertGreater(gate["boundary_pva_error"], .09)


if __name__ == "__main__":
    unittest.main()
