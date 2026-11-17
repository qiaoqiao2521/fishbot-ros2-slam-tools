# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Source-time association and unavailable-state evidence must remain honest."""
import importlib.util
import copy
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


class ForecastTests(unittest.TestCase):
    def test_constant_velocity_uses_source_age_and_retains_initial_pv(self):
        anchor = state(1.)
        prediction = module.predict_pv(anchor, 1.2, "constant_velocity")
        np.testing.assert_allclose(prediction["position"], [1.2, 0., 1.5])
        np.testing.assert_allclose(prediction["velocity"], anchor["velocity"])
        same_time = module.predict_pv(anchor, 1., "constant_velocity")
        np.testing.assert_allclose(same_time["position"], anchor["position"])
        self.assertIsNone(anchor["acceleration"])

    def test_causal_acceleration_is_estimated_not_recorded_or_reference(self):
        anchor, previous = state(1.), {**state(.8), "velocity": [.8, 0., 0.]}
        prediction = module.predict_pv(anchor, 1.2, "causal_acceleration", previous)
        np.testing.assert_allclose(prediction["model_acceleration"], [1., 0., 0.])
        np.testing.assert_allclose(prediction["position"], [1.22, 0., 1.5])
        self.assertIsNone(anchor["acceleration"])
        self.assertIsNone(module.predict_pv(anchor, 1.2, "causal_acceleration", state(1.1)))

    def test_late_history_frame_cannot_enter_acceleration_estimate(self):
        states = [state(.8, 2.), state(1., 1.), state(1.2, 1.2)]
        result = module.forecast_evidence(states, [{"source_stamp_ns": "1000000000"}], [], 1.3)
        case = next(r for r in result["cases"] if r["requested_horizon_from_available_s"] == .08)
        self.assertIsNone(case["previous_available_state"])
        self.assertEqual(case["models"]["causal_acceleration"]["status"], "unscored")
        self.assertEqual(case["oracle_source_sim_s"], 1.2)
        self.assertAlmostEqual(case["oracle_source_offset_s"], .12)

    def test_future_oracle_position_changes_only_score_not_prediction(self):
        states = [state(.8), state(1.), state(1.2)]
        focus = [{"source_stamp_ns": "1000000000"}]
        first = module.forecast_evidence(states, focus, [], 1.3)
        changed = copy.deepcopy(states)
        changed[-1]["position"] = [20., 0., 1.5]
        second = module.forecast_evidence(changed, focus, [], 1.3)
        a = next(r for r in first["cases"] if r["requested_horizon_from_available_s"] == .08)
        b = next(r for r in second["cases"] if r["requested_horizon_from_available_s"] == .08)
        for model in first["models"]:
            np.testing.assert_array_equal(a["models"][model]["position"], b["models"][model]["position"])
        self.assertNotEqual(a["models"]["constant_velocity"]["position_error_m"], b["models"]["constant_velocity"]["position_error_m"])

    def test_fsm_consumption_and_recorder_availability_are_distinct(self):
        anchor = state(1., 1.5)
        fsm = [{"sim": 1.1, "odom_source": 1., "bag_pv_match_error": [0., 0.]}]
        result = module.forecast_evidence([state(.8), anchor, state(1.2)],
            [{"source_stamp_ns": "1000000000"}], fsm, 1.3)
        self.assertEqual([r["kind"] for r in result["cases"]], ["fsm"])
        self.assertEqual(result["cases"][0]["input_evidence"], "FSM logged consumed PV")

    def test_conflicting_duplicate_stamp_and_post_failure_oracle_are_unscored(self):
        anchor = state(1.)
        result = module.forecast_evidence([anchor, {**anchor, "position": [2., 0., 1.5]}, state(1.2)],
            [{"source_stamp_ns": "1000000000"}], [], 1.3)
        self.assertEqual(result["ambiguous_source_stamps"], 1)
        self.assertEqual(result["cases"], [])
        result = module.forecast_evidence([anchor, state(1.2)],
            [{"source_stamp_ns": "1000000000"}], [], 1.1)
        self.assertTrue(all(r["oracle_source_sim_s"] < 1.1 for r in result["cases"]))

    def test_bad_frame_epoch_or_nonfinite_state_does_not_produce_forecast(self):
        focus = [{"source_stamp_ns": "1000000000"}]
        for bad in ({**state(1.), "velocity_frame_id": "body"},
                    {**state(1.), "position": [float("nan"), 0., 1.5]}):
            self.assertEqual(module.forecast_evidence([bad], focus, [], 2.)["cases"], [])
        self.assertEqual(module.forecast_evidence([state(1.)], focus, [], 2., False)["cases"], [])

    def test_invalid_availability_and_consumption_match_do_not_become_inputs(self):
        focus = [{"source_stamp_ns": "1000000000"}]
        for value in (None, float("nan"), .9):
            bad = {**state(1.), "available_by_sim_s": value}
            self.assertEqual(module.forecast_evidence([bad, state(1.2)], focus, [], 1.3)["cases"], [])
        fsm = [{"sim": 1.1, "odom_source": 1., "bag_pv_match_error": [float("nan"), 0.]}]
        self.assertEqual(module.forecast_evidence([state(1.), state(1.2)], [], fsm, 1.3)["cases"], [])

    def test_identical_duplicate_uses_earliest_valid_availability(self):
        a = {**state(1.), "available_by_sim_s": None}
        result = module.forecast_evidence([a, state(1., 1.04), state(1.2)],
            [{"source_stamp_ns": "1000000000"}], [], 1.3)
        self.assertEqual(result["ambiguous_source_stamps"], 0)
        self.assertEqual(result["cases"][0]["forecast_at_sim_s"], 1.04)

    def test_numeric_and_string_stamp_cannot_bypass_conflict_detection(self):
        a = state(1.)
        b = {**a, "source_stamp_ns": 1000000000, "position": [2., 0., 1.5]}
        result = module.forecast_evidence([a, b, state(1.2)],
            [{"source_stamp_ns": "1000000000"}], [], 1.3)
        self.assertEqual(result["ambiguous_source_stamps"], 1)
        self.assertEqual(result["cases"], [])

    def test_nonfinite_primary_failure_does_not_open_scoring_horizon(self):
        fsm = [{"sim": 1.1, "odom_source": 1., "bag_pv_match_error": [0., 0.]}]
        for failure in (None, float("nan"), float("inf")):
            result = module.forecast_evidence([state(1.), state(1.2)],
                [{"source_stamp_ns": "1000000000"}], fsm, failure)
            self.assertEqual(result["cases"], [])


class StoppingNecessaryTests(unittest.TestCase):
    box = [[1.5, -1., .8], [9.5, 2.03, 2.2]]

    def test_original_recorded_head_is_not_ruled_out_per_face(self):
        result = module.stopping_necessary([2.443276083629172, 1.7565359918948806, 2.1646591444870626],
            [1.262200808117, .521065904265, .149851061152], self.box, 1.)
        self.assertEqual(result["status"], "not_ruled_out")
        self.assertEqual(result["joint_viability"], "not_proven")
        upper = [f["required_deceleration_m_s2"] for f in result["faces"] if f["face"].endswith("upper")]
        np.testing.assert_allclose(upper, [.1128817634706717, .49642671163353647, .31769661773128305])

    def test_reject_uses_distance_not_only_current_position(self):
        result = module.stopping_necessary([2., 0., 2.17], [0., 0., .3], self.box, 1.)
        self.assertEqual(result["rejected_faces"], ["z_upper"])
        self.assertAlmostEqual(result["faces"][-1]["distance_margin_m"], -.015)
        reverse = module.stopping_necessary([2., 0., 2.17], [0., 0., -.3], self.box, 1.)
        self.assertEqual(reverse["status"], "not_ruled_out")

    def test_boundary_rest_and_outside_are_not_conflated(self):
        at_rest = module.stopping_necessary([2., 0., 2.2], [0.]*3, self.box, 1.)
        self.assertEqual(at_rest["status"], "not_ruled_out")
        outward = module.stopping_necessary([2., 0., 2.2], [0., 0., .01], self.box, 1.)
        self.assertEqual(outward["status"], "necessary_reject")
        self.assertIsNone(outward["faces"][-1]["required_deceleration_m_s2"])
        outside = module.stopping_necessary([2., 0., 2.21], [0., 0., -.1], self.box, 1.)
        self.assertEqual(outside["faces"][-1]["status"], "outside")

    def test_exact_optimistic_stop_boundary_is_not_a_relaxed_gate(self):
        box = [[0.]*3, [1.]*3]
        exact = module.stopping_necessary([.5]*3, [1., 0., 0.], box, 1.)
        self.assertEqual(exact["status"], "not_ruled_out")
        nearer = module.stopping_necessary([np.nextafter(.5, 1.), .5, .5], [1., 0., 0.], box, 1.)
        self.assertEqual(nearer["rejected_faces"], ["x_upper"])

    def test_lower_face_and_shared_budget_never_claim_sufficiency(self):
        result = module.stopping_necessary([.5, .5, .5], [1., 1., 0.], [[0.]*3, [1.]*3], 1.)
        self.assertEqual(result["status"], "not_ruled_out")
        self.assertEqual(result["joint_viability"], "not_proven")
        lower = module.stopping_necessary([.1, .5, .5], [-1., 0., 0.], [[0.]*3, [1.]*3], 1.)
        self.assertEqual(lower["rejected_faces"], ["x_lower"])

    def test_invalid_inputs_remain_unscored(self):
        for p, v, box, acceleration in (([float("nan"), 0., 1.], [0.]*3, self.box, 1.),
                ([2., 0., 1.], [0.]*3, self.box, 0.), ([2., 0.], [0.]*3, self.box, 1.),
                ([2., 0., 1.], [0.]*3, [self.box[1], self.box[0]], 1.)):
            self.assertEqual(module.stopping_necessary(p, v, box, acceleration)["status"], "unscored")

    def evidence(self, oracle=None, brake=None):
        states = [state(.8), state(1.), state(1.1), oracle or state(1.2)]
        fsm = [{"sim": 1.1, "odom_source": 1., "bag_pv_match_error": [0., 0.]}]
        forecast = module.forecast_evidence(states, [], fsm, 1.3)
        events = [{"sim": 1.2, "odom_source": 1., "source_line": 123}]
        result = module.stopping_evidence(states, forecast, events, 1.3,
            {"box": [[0., -1., 0.], [10., 1., 2.]], "limits": {"acceleration": 1.}}, brake)
        return states, forecast, events, result

    def test_future_pv_only_changes_retrospective_bound_not_prediction(self):
        *_, baseline = self.evidence()
        *_, changed = self.evidence({**state(1.2), "position": [99., 0., 1.5]})
        a, b = baseline["cases"][-1], changed["cases"][-1]
        self.assertEqual(a["kind"], "reanchor")
        self.assertEqual(a["variants"]["constant_velocity"], b["variants"]["constant_velocity"])
        self.assertEqual(b["variants"]["retrospective_source_pv"]["necessary"]["status"], "necessary_reject")
        self.assertEqual(a["source_sim_s"], 1.)
        self.assertEqual(a["oracle_source_sim_s"], 1.2)

    def test_conflicting_reanchor_oracle_and_missing_consumption_are_excluded(self):
        states, forecast, events, _ = self.evidence()
        fixture = {"box": self.box, "limits": {"acceleration": 1.}}
        conflict = states+[{**state(1.2), "position": [99., 0., 1.5]}]
        result = module.stopping_evidence(conflict, forecast, events, 1.3, fixture)
        self.assertEqual(len(result["cases"]), 1)
        self.assertIn("reanchor_without_unambiguous_prefailure_source_oracle", result["excluded"])
        result = module.stopping_evidence(states, {**forecast, "cases": []}, events, 1.3, fixture)
        self.assertEqual(result["cases"], [])

    def test_reanchor_next_source_offset_and_prediction_time_are_disclosed(self):
        *_, result = self.evidence(state(1.216))
        row = result["cases"][-1]
        self.assertEqual(row["forecast_at_sim_s"], 1.2)
        self.assertEqual(row["prediction_evaluated_sim_s"], 1.216)
        self.assertAlmostEqual(row["oracle_source_offset_s"], .016)
        self.assertAlmostEqual(row["variants"]["constant_velocity"]["position"][0], 1.216)

    def test_native_brake_is_separate_from_necessary_diagnostic(self):
        calls = []
        def rejected_brake(pv):
            calls.append(pv)
            return {"status": "audited", "audit": {"passed": False, "failed_checks": ["corridor"]}}
        *_, result = self.evidence(brake=rejected_brake)
        self.assertEqual(len(calls), 8)
        for case in result["cases"]:
            row = case["variants"]["constant_velocity"]
            self.assertEqual(row["necessary"]["status"], "not_ruled_out")
            self.assertFalse(row["conditional_axis_stop"]["audit"]["passed"])
        self.assertEqual(result["execution_admission"], "not_performed")

    def test_reanchor_log_does_not_treat_result_as_a_new_consumed_state(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory)/"planner.log"
            file.write_text("FSMReanchor sim=1.2 odom_source=1.0 age=0.2\nFSMReanchor result=0 sim=1.3\n")
            result = module.log_evidence(file)
        self.assertEqual(len(result["reanchor"]), 1)
        self.assertEqual(result["reanchor"][0]["odom_source"], 1.)


if __name__ == "__main__":
    unittest.main()
