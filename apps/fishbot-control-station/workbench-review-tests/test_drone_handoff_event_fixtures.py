# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Declared event links retain the original selector and physical boundaries."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np


HERE = Path(__file__).parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


timing = load("event_timing_fixture", HERE/"test_drone_handoff_timing.py")
study = load("handoff_event_fixtures", HERE.parent/"workbench-tools/drone-handoff-event-fixtures.py")


def stage(case, name):
    return next(event for event in case["events"] if event["event"] == name)


@unittest.skipUnless(timing.NATIVE.exists(), "existing offline S4 inner-point executable unavailable")
class HandoffEventFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        timing.HandoffTimingTests.setUpClass()
        cls.audit = timing.HandoffTimingTests.audit
        cls.handoff = timing.HandoffTimingTests.handoff
        cls.candidate = timing.HandoffTimingTests.candidate
        cls.frames = load("event_test_frames", timing.ROOT/"frames.py")
        cls.cases = {case["name"]: case for case in study.build_cases(cls.candidate, "fixture", 30.,
            timing.BOX, timing.LIMITS, cls.handoff, cls.frames)}

    def assess(self, case):
        return study.assess(case, self.audit, self.handoff, self.frames)

    def normal(self):
        return copy.deepcopy(self.cases["normal"])

    def source(self):
        return {"archive_task_id": "fixture", "rows": [{"variant_id": "reference-4-h0.1",
            "profile": {"name": "zero_A_J"}, "resolved": {"candidate": copy.deepcopy(self.candidate)},
            "start_sim_s": 30., "hard_box": copy.deepcopy(timing.BOX), "hard_limits": copy.deepcopy(timing.LIMITS)}]}

    def test_named_positive_cases_and_all_declared_expectations_match(self):
        self.assertTrue(self.candidate["audit"]["passed"])
        self.assertTrue(self.candidate["axis_knot_contract"]["passed"])
        self.assertLess(self.candidate["audit"]["boundary_jerk_error"], 1e-8)
        positives = {"normal", "input_before_rpc_return", "sim_paused", "map_changed_and_rechecked",
            "native_resends_unique_consumed_timestamp", "rejected_new_candidate_keeps_original"}
        self.assertTrue(positives.issubset(self.cases))
        for name, case in self.cases.items():
            with self.subTest(name=name):
                result = self.assess(copy.deepcopy(case))
                self.assertEqual(result["fixture_chain_consistent"], case["expected_fixture_consistency"], result["issues"])
                self.assertEqual(result["actual_execution_admission"], "not_performed")
                if name in positives:
                    self.assertTrue(result["fixture_chain_consistent"], result["issues"])

    def test_original_math_map_occupancy_and_terminal_gates_still_reject(self):
        for name in ("candidate_coefficients_tampered", "new_occupied_remaining_curve", "terminal_window_missing", "observed_A_unknown"):
            with self.subTest(name=name):
                result = self.assess(copy.deepcopy(self.cases[name]))
                self.assertFalse(result["fixture_chain_consistent"])
                self.assertIn("original_selector_rejected", result["issues"])
                if name == "candidate_coefficients_tampered":
                    self.assertFalse(result["selector"][0]["candidate_accepted"])
                else:
                    self.assertTrue(result["selector"][0]["candidate_accepted"])
                    self.assertIsNone(result["selector"][1].get("selected_reference_pva"))

    def test_rpc_return_can_follow_ingress_and_resends_select_consumed_timestamp(self):
        late_return = copy.deepcopy(self.cases["input_before_rpc_return"])
        returned = stage(late_return, "sender_rpc_returned")
        ingress = stage(late_return, "px4_input_observed")
        link = next(link for link in late_return["clock_links"] if link["id"] == ingress["clock_link_id"])
        self.assertLess(link["sim_interval_s"][1], returned["clock"]["stamp_s"])
        self.assertTrue(self.assess(late_return)["fixture_chain_consistent"])
        resend = copy.deepcopy(self.cases["native_resends_unique_consumed_timestamp"])
        inputs = [event for event in resend["events"] if event["event"] == "px4_input_observed"]
        consumed = stage(resend, "controller_step_observed")["used_input_timestamp_us"]
        self.assertEqual(sum(event["input_timestamp_us"] == consumed for event in inputs), 1)
        self.assertNotEqual(inputs[0]["input_timestamp_us"], consumed)
        inputs[0]["payload_ned"]["velocity"][0] *= -1.
        self.assertTrue(self.assess(resend)["fixture_chain_consistent"])

    def test_missing_duplicate_ids_versions_sequences_and_cross_goal_are_not_joined(self):
        for name in ("candidate_version_mismatch", "sample_sequence_mismatch", "duplicate_sender_start",
                "native_input_timestamp_ambiguous", "controller_witness_missing", "cross_goal_sender"):
            with self.subTest(name=name):
                self.assertFalse(self.assess(copy.deepcopy(self.cases[name]))["fixture_chain_consistent"])
        for event_name, field in (("candidate_ready", "candidate_id"), ("candidate_ready", "candidate_revision"),
                ("sender_rpc_started", "sample_seq"), ("sender_rpc_returned", "sample_seq")):
            with self.subTest(event=event_name, field=field):
                case = self.normal()
                stage(case, event_name).pop(field)
                self.assertFalse(self.assess(case)["fixture_chain_consistent"])
        case = self.normal()
        case["events"].append(copy.deepcopy(stage(case, "candidate_ready")))
        self.assertFalse(self.assess(case)["fixture_chain_consistent"])

    def test_application_identity_and_phase_are_bound_to_the_selected_candidate(self):
        for field, value in (("candidate_id", "other-candidate"), ("candidate_revision", 2)):
            with self.subTest(field=field):
                case = self.normal()
                for event in case["events"]:
                    if event["event"] in study.APP_STAGES:
                        event[field] = value
                result = self.assess(case)
                self.assertTrue(result["selector"][0]["candidate_accepted"])
                self.assertFalse(result["fixture_chain_consistent"])
                self.assertIn("candidate_body_identity_mismatch", result["issues"])
        for event_name, field, issue in (("sender_rpc_started", "sample_sim_s", "sample_phase_mismatch"),
                ("candidate_audited", "audit_sim_s", "audit_phase_mismatch")):
            with self.subTest(field=field):
                case = self.normal()
                stage(case, event_name)[field] += .01
                result = self.assess(case)
                self.assertFalse(result["fixture_chain_consistent"])
                self.assertIn(issue, result["issues"])

    def test_accepted_replacement_cannot_reuse_old_identity_but_rejected_proposal_can_keep_old_body(self):
        replacement = self.assess(copy.deepcopy(self.cases["sample_selector_replaced_candidate"]))
        self.assertTrue(replacement["selector"][0]["candidate_accepted"])
        self.assertTrue(replacement["selector"][1]["candidate_accepted"])
        self.assertEqual(replacement["payload_binding"], "matched_float32_fixture")
        self.assertFalse(replacement["fixture_chain_consistent"])
        self.assertIn("active_candidate_body_mismatch", replacement["issues"])
        self.assertIn("active_candidate_version_mismatch", replacement["issues"])
        original = self.assess(self.normal())
        rejected = self.assess(copy.deepcopy(self.cases["rejected_new_candidate_keeps_original"]))
        self.assertFalse(rejected["selector"][1]["candidate_accepted"])
        self.assertEqual(rejected["selector"][1]["selected_reference_pva"], original["selector"][1]["selected_reference_pva"])
        self.assertTrue(rejected["fixture_chain_consistent"], rejected["issues"])
        self.assertEqual(rejected["actual_execution_admission"], "not_performed")

    def test_clock_epochs_overlaps_missing_anchors_and_native_rewind_are_rejected(self):
        for name in ("clock_epoch_changed", "native_clock_anchor_missing", "overlapping_clock_intervals",
                "same_epoch_clock_rewind", "native_source_clock_rewind", "native_after_candidate_end"):
            with self.subTest(name=name):
                result = self.assess(copy.deepcopy(self.cases[name]))
                self.assertFalse(result["fixture_chain_consistent"])
                self.assertTrue(result["issues"])
        rewind = copy.deepcopy(self.cases["native_source_clock_rewind"])
        ingress = stage(rewind, "px4_input_observed")
        controller = stage(rewind, "controller_step_observed")
        self.assertEqual(ingress["clock"]["epoch"], controller["clock"]["epoch"])
        self.assertGreater(ingress["clock"]["stamp_s"], controller["clock"]["stamp_s"])
        self.assertIn("native_clock_rewind", self.assess(rewind)["issues"])

    def test_native_clock_role_cannot_be_relabelled_as_sim_to_bypass_anchor(self):
        case = copy.deepcopy(self.cases["native_clock_relabelled_to_sim"])
        self.assertEqual(case["clock_links"], [])
        for event_name in ("px4_input_observed", "controller_step_observed"):
            self.assertEqual(stage(case, event_name)["clock"]["domain"], case["context"]["clock_id"])
        result = self.assess(copy.deepcopy(case))
        self.assertFalse(result["fixture_chain_consistent"])
        self.assertIn("native_clock_role_mismatch", result["issues"])
        case.update(native_clock_domain=case["context"]["clock_id"], native_clock_epoch=case["sim_epoch"])
        self.assertIn("native_clock_role_mismatch", self.assess(case)["issues"])

    def test_native_events_cannot_fabricate_uuid_and_only_normal_success_is_valid(self):
        for event_name in ("px4_input_observed", "controller_step_observed"):
            for field, value in (("candidate_id", "fixture-brake"), ("candidate_revision", 1), ("sample_seq", 17)):
                with self.subTest(event=event_name, field=field):
                    case = self.normal()
                    stage(case, event_name)[field] = value
                    result = self.assess(case)
                    self.assertFalse(result["fixture_chain_consistent"])
                    self.assertIn("native_identity_fabricated", result["issues"])
        for name in ("controller_old_input", "controller_failsafe", "controller_update_failed"):
            with self.subTest(name=name):
                result = self.assess(copy.deepcopy(self.cases[name]))
                self.assertFalse(result["fixture_chain_consistent"])
                self.assertIn("controller_not_normal_success", result["issues"])

    def test_payload_and_frame_mismatch_reject_without_relaxing_physical_state(self):
        sign = self.assess(copy.deepcopy(self.cases["native_payload_sign_error"]))
        self.assertFalse(sign["fixture_chain_consistent"])
        self.assertIn("payload_or_frame_mismatch", sign["issues"])
        case = self.normal()
        for event_name in ("sender_rpc_started", "px4_input_observed", "controller_step_observed"):
            stage(case, event_name)["payload_ned"]["frame"] = "MAV_FRAME_LOCAL_ENU"
        result = self.assess(case)
        self.assertFalse(result["fixture_chain_consistent"])
        self.assertIn("payload_or_frame_mismatch", result["issues"])
        case = self.normal()
        case["origin_enu"] = [1e9, 0., 0.]
        reference = np.asarray(self.handoff.pva(self.candidate["native"], .2))
        exact = study.payload(reference, case["origin_enu"], self.frames)
        drifted = reference.copy(); drifted[0, 0] += .1
        rounded_same = study.payload(drifted, case["origin_enu"], self.frames)
        self.assertEqual(study.wire_values(exact), study.wire_values(rounded_same))
        for event_name in ("sender_rpc_started", "px4_input_observed", "controller_step_observed"):
            stage(case, event_name)["payload_ned"] = copy.deepcopy(rounded_same)
        self.assertTrue(self.assess(copy.deepcopy(case))["fixture_chain_consistent"])
        case["selector_events"][1]["observed_pva"] = drifted.tolist()
        result = self.assess(case)
        self.assertFalse(result["fixture_chain_consistent"])
        self.assertIn("original_selector_rejected", result["issues"])

    def test_build_and_assess_keep_candidate_case_frames_and_limits_immutable(self):
        inputs = (self.candidate, timing.BOX, timing.LIMITS)
        before = copy.deepcopy(inputs)
        cases = study.build_cases(self.candidate, "fixture", 30., timing.BOX, timing.LIMITS, self.handoff, self.frames)
        self.assertEqual(inputs, before)
        normal = next(case for case in cases if case["name"] == "normal")
        snapshot = copy.deepcopy(normal)
        result = self.assess(normal)
        self.assertEqual(normal, snapshot)
        self.assertTrue(result["fixture_chain_consistent"])

    def test_run_skips_bad_source_rows_and_isolates_malformed_case(self):
        source = self.source()
        source["rows"][:0] = [None, {"variant_id": "reference-4-h0.1", "profile": None}]
        before = copy.deepcopy(source)
        normal = self.normal()
        with patch.object(study, "build_cases", return_value=[{"name": "broken"}, normal]):
            result = study.run(source, timing.ROOT)
        self.assertEqual(source, before)
        self.assertEqual(result["rows"][0]["name"], "broken")
        self.assertEqual(result["rows"][0]["status"], "unscored")
        self.assertEqual(result["rows"][1]["name"], "normal")
        self.assertTrue(result["rows"][1]["expectation_matched"])
        self.assertTrue(result["rows"][1]["fixture_chain_consistent"])
        self.assertEqual(result["summary"]["unscored"], 1)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertEqual(result["actual_execution_admission"], "not_performed")
        self.assertEqual(result["dynamic_closed_loop"], "not_passed")

    def test_invalid_json_fixture_is_omitted_without_losing_assessment_or_later_case(self):
        nan_case = self.normal()
        nan_case.update(name="nonfinite-event-clock", expected_fixture_consistency=False)
        stage(nan_case, "sender_rpc_returned")["clock"]["stamp_s"] = float("nan")
        with patch.object(study, "build_cases", return_value=[nan_case, self.normal()]):
            result = study.run(self.source(), timing.ROOT)
        self.assertFalse(result["rows"][0]["fixture_chain_consistent"])
        self.assertTrue(result["rows"][0]["expectation_matched"])
        self.assertEqual(result["rows"][0]["fixture_embedding"], "omitted_nonfinite_or_non_json_values")
        self.assertNotIn("fixture", result["rows"][0])
        self.assertEqual(result["summary"]["unscored"], 0)
        self.assertTrue(result["rows"][1]["fixture_chain_consistent"])
        self.assertTrue(any("invalid JSON fixture omitted" in warning for warning in result["warnings"]))
        self.assertTrue(np.isnan(stage(nan_case, "sender_rpc_returned")["clock"]["stamp_s"]))
        json.dumps(result, allow_nan=False)
        bad_assessment = self.normal()
        bad_assessment["name"] = "nonfinite-assessment"
        original_assess = study.assess

        def assess(case, *args):
            if case["name"] == "nonfinite-assessment":
                return {"name": case["name"], "fixture_chain_consistent": False, "issues": [float("nan")]}
            return original_assess(case, *args)

        with patch.object(study, "build_cases", return_value=[bad_assessment, self.normal()]), \
                patch.object(study, "assess", side_effect=assess):
            result = study.run(self.source(), timing.ROOT)
        self.assertEqual(result["rows"][0]["status"], "unscored")
        self.assertTrue(result["rows"][1]["fixture_chain_consistent"])
        self.assertEqual(result["summary"]["unscored"], 1)
        json.dumps(result, allow_nan=False)

    def test_missing_ambiguous_or_incomplete_source_remains_unscored(self):
        duplicate = self.source(); duplicate["rows"] *= 2
        missing = self.source(); missing["rows"][0].pop("resolved")
        for source in (None, {"rows": None}, duplicate, missing):
            with self.subTest(source=source):
                result = study.run(source, timing.ROOT)
                self.assertEqual(result["status"], "unscored")
                self.assertTrue(result["reason"])


if __name__ == "__main__":
    unittest.main()
