# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Reanchored tails retain causal PV without completing a vehicle handoff."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np


HERE = Path(__file__).parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixture = load("reanchor_pv_fixture", HERE/"test_drone_handoff_pv.py")
study = load("handoff_reanchor", HERE.parent/"workbench-tools/drone-handoff-reanchor.py")
ROOT = fixture.ROOT
NATIVE = Path.home()/".cache/ros2-drone/minco-s4-knots/minco_s4_knots"
PROFILES = {
    "zero_A_J": ([0., 0., 0.], [0., 0., 0.]),
    "outward_y_A": ([0., .2, 0.], [0., 0., 0.]),
    "outward_y_J": ([0., 0., 0.], [0., 1., 0.]),
    "inward_y_J": ([0., 0., 0.], [0., -1., 0.]),
}


def source_report():
    result = fixture.report()
    result["limits"].update(speed=1.8, ceiling=2.2, local_target_tolerance=.3)
    # Nonzero reference A_x=.1 and J_x=.06 at the cut are not vehicle evidence.
    candidate = result["rows"][0]["result"]["candidate"]
    candidate["prefix_pieces"][0]["coefficients_descending"][0] = [0., 0., .01, .02, 1., 0.]
    return result


def anchor():
    result = fixture.state(10.8, 10.95)
    result["velocity"] = [1., .2, 0.]
    return result


class HandoffReanchorTests(unittest.TestCase):
    def analyze(self, states, report=None, epochs=1, max_iterations=3):
        return study.run([report or source_report()], states, epochs, ROOT, NATIVE,
            "fixture", max_iterations=max_iterations)

    def test_four_hypotheses_keep_forecast_pv_without_reference_aj_or_late_exact(self):
        report = source_report()
        late = fixture.state(11., 11.01)
        late.update(position=[9., 1.9, 2.1], velocity=[9., 0., 0.])
        before = copy.deepcopy(report)
        with patch.object(study.geometry, "search", return_value={"status": "unscored", "reason": "unit probe"}) as search:
            result = self.analyze([late, anchor()], report)
        self.assertEqual(report, before)
        self.assertEqual(result["summary"]["hypotheses"], 4)
        self.assertEqual(search.call_count, 4)
        self.assertEqual({row["profile"]["name"] for row in result["rows"]}, set(PROFILES))
        for row, call in zip(result["rows"], search.call_args_list):
            with self.subTest(profile=row["profile"]["name"]):
                request = call.args[0]
                acceleration, jerk = PROFILES[row["profile"]["name"]]
                np.testing.assert_allclose(np.asarray(request["initial_pva"])[:, 0], [1., .04, 1.5], atol=1e-12)
                np.testing.assert_array_equal(np.asarray(request["initial_pva"])[:, 1], [1., .2, 0.])
                np.testing.assert_array_equal(np.asarray(request["initial_pva"])[:, 2], acceleration)
                self.assertEqual(request["initial_jerk"], jerk)
                self.assertEqual(row["input"]["source_state"]["source_stamp_ns"], anchor()["source_stamp_ns"])
                self.assertAlmostEqual(row["input"]["source_age_s"], .2)
                self.assertAlmostEqual(row["input"]["availability_age_s"], .05)
                self.assertIn("not measured", request["initial_jerk_assumption"])

    def test_missing_causal_pv_does_not_fall_back_to_retrospective_exact(self):
        late_exact = fixture.state(11., 11.01)
        for states in ([late_exact], []):
            with self.subTest(states=states):
                with patch.object(study.geometry, "search") as search:
                    result = self.analyze(states)
                search.assert_not_called()
                self.assertEqual(result["summary"]["unscored"], 4)
                self.assertEqual(result["summary"]["full_vehicle_handoffs_qualified"], 0)
                self.assertTrue(all("boundary_request" not in row for row in result["rows"]))
                if states:
                    self.assertTrue(all("no retrospective fallback" in row["reason"] for row in result["rows"]))

    def test_future_frame_and_epoch_outliers_do_not_poison_available_anchor(self):
        invalid = [fixture.state(11.+1e-9), {**anchor(), "frame_id": "body"},
            {**anchor(), "velocity_frame_id": "body"}, {**anchor(), "epoch": 1}]
        invalid[0].update(position=[1e8]*3, velocity=[1e8]*3)
        with patch.object(study.geometry, "search", return_value={"status": "unscored"}) as search:
            expected = self.analyze([anchor()])
            requests = [copy.deepcopy(call.args[0]) for call in search.call_args_list]
            search.reset_mock()
            actual = self.analyze(invalid+[anchor()])
            self.assertEqual([call.args[0] for call in search.call_args_list], requests)
        self.assertEqual(actual["rows"], expected["rows"])
        for states, epochs in ((invalid, 1), ([anchor()], 2)):
            with self.subTest(epochs=epochs, states=states):
                with patch.object(study.geometry, "search") as search:
                    result = self.analyze(states, epochs=epochs)
                search.assert_not_called()
                self.assertEqual(result["summary"]["unscored"], 4)

    def test_one_unqualified_variant_does_not_suppress_other_tail_searches(self):
        report = source_report()
        broken = copy.deepcopy(report["rows"][0])
        broken["variant_id"] = "invalid-prefix-time"
        broken["result"]["candidate"]["cut_sim_s"] = 11.01
        report["rows"].insert(0, broken)
        with patch.object(study.geometry, "search", return_value={"status": "unscored", "reason": "unit probe"}) as search:
            result = self.analyze([anchor()], report)
        self.assertEqual(search.call_count, 4)
        self.assertEqual(result["summary"]["variants"], 2)
        self.assertEqual(result["summary"]["unscored"], 8)
        self.assertTrue(all("boundary_request" not in row for row in result["rows"][:4]))
        self.assertTrue(all("boundary_request" in row for row in result["rows"][4:]))

    def test_duplicate_variant_only_unqualifies_that_source(self):
        report = source_report()
        duplicate = copy.deepcopy(report["rows"][0])
        independent = copy.deepcopy(report["rows"][0])
        independent["variant_id"] = "independent"
        report["rows"].extend([duplicate, independent])
        with patch.object(study.geometry, "search", return_value={"status": "not_searched"}) as search:
            result = self.analyze([anchor()], report)
        self.assertEqual(search.call_count, 4)
        affected = [row for row in result["rows"] if row["variant_id"] == "analytic"]
        surviving = [row for row in result["rows"] if row["variant_id"] == "independent"]
        self.assertEqual(len(affected), 8)
        self.assertTrue(all(row["status"] == "unscored" for row in affected))
        self.assertTrue(all(row["reason"] == "source_variant_missing_or_ambiguous" for row in affected))
        self.assertEqual(len(surviving), 4)
        self.assertTrue(all("boundary_request" in row for row in surviving))

    def test_all_hypotheses_share_box_limits_and_explicit_search_domain(self):
        report = source_report()
        with patch.object(study.geometry, "search", return_value={"status": "unscored"}) as search:
            result = self.analyze([anchor()], report, max_iterations=2)
        self.assertEqual(search.call_count, 4)
        for row, call in zip(result["rows"], search.call_args_list):
            self.assertEqual(call.args[1], report["narrow_box_fixture"])
            self.assertEqual(call.args[2], report["limits"])
            self.assertEqual(call.args[3], NATIVE)
            self.assertEqual(call.kwargs, {"y_inner": True, "z_time_bounds": (.1, 1.2), "max_iterations": 2})
            self.assertEqual(row["hard_box"], report["narrow_box_fixture"])
            self.assertEqual(row["hard_limits"], report["limits"])
        self.assertEqual(result["search_configuration"]["z_time_bounds_s"], [.1, 1.2])
        self.assertEqual(result["search_configuration"]["planning_inset_m"], .002)
        self.assertEqual(result["search_configuration"]["max_iterations"], 2)

    def test_standalone_tail_and_temporal_fixture_start_at_cut_without_prefix(self):
        tail = {"duration": .5, "coefficients_descending": [[0., 0., 0., 0., 0., value] for value in (1., .04, 1.5)]}

        def resolved(request, *args, **kwargs):
            return {"status": "audited", "candidate": {"request": request,
                "native": {"native_success": True, "pieces": [copy.deepcopy(tail)]}, "audit": {"passed": True}}}

        report = source_report()
        with patch.object(study.geometry, "search", side_effect=resolved), \
                patch.object(study.qualification, "acceleration_peak", return_value={"value": 0.}), \
                patch.object(study.qualification, "temporal_replay", return_value={"execution_admission": "not_performed"}) as temporal:
            result = self.analyze([anchor()], report)
        self.assertEqual(temporal.call_count, 4)
        for row, call in zip(result["rows"], temporal.call_args_list):
            candidate, task_id, start = call.args[:3]
            self.assertEqual(task_id, "fixture")
            self.assertEqual(start, 11.)
            self.assertEqual(row["start_sim_s"], 11.)
            self.assertEqual(row["tail_end_sim_s"], 11.5)
            self.assertEqual(row["tail_duration_sim_s"], .5)
            self.assertEqual(candidate["native"]["pieces"], [tail])
            self.assertNotIn("prefix_pieces", candidate)
            self.assertIn("no historical reference prefix", row["prefix_scope"])
        self.assertEqual(report["rows"][0]["result"]["candidate"]["start_sim_s"], 10.)

    def test_new_tail_audit_failure_cannot_inherit_source_reference_pass(self):
        report = source_report()

        def rejected(request, *args, **kwargs):
            return {"status": "audited", "candidate": {"request": request,
                "native": {"pieces": [{"duration": .5}]},
                "audit": {"passed": False, "failed_checks": ["boundary_jerk"]}}}

        with patch.object(study.geometry, "search", side_effect=rejected), \
                patch.object(study.qualification, "acceleration_peak", return_value={"value": 0.}), \
                patch.object(study.qualification, "temporal_replay") as temporal:
            result = self.analyze([anchor()], report)
        temporal.assert_not_called()
        self.assertTrue(report["rows"][0]["result"]["candidate"]["full_math_gate"]["passed"])
        self.assertEqual(result["summary"]["audited"], 4)
        self.assertEqual(result["summary"]["conditional_math_passed"], 0)
        self.assertTrue(all(row["conditional_math_passed"] is False for row in result["rows"]))
        self.assertEqual(result["summary"]["full_vehicle_handoffs_qualified"], 0)

    def test_optional_temporal_fixture_failure_preserves_completed_math_audit(self):
        def resolved(request, *args, **kwargs):
            return {"status": "audited", "candidate": {"request": request,
                "native": {"pieces": [{"duration": .5}]}, "audit": {"passed": True}}}

        with patch.object(study.geometry, "search", side_effect=resolved), \
                patch.object(study.qualification, "acceleration_peak", return_value={"value": 0.}), \
                patch.object(study.qualification, "temporal_replay", side_effect=ValueError("fixture unavailable")):
            result = self.analyze([anchor()])
        self.assertEqual(result["summary"]["audited"], 4)
        self.assertEqual(result["summary"]["conditional_math_passed"], 4)
        self.assertEqual(result["summary"]["unscored"], 0)
        self.assertEqual(len(result["warnings"]), 4)
        for row in result["rows"]:
            self.assertEqual(row["status"], "audited")
            self.assertTrue(row["conditional_math_passed"])
            self.assertEqual(row["temporal_fixture"], {"status": "unscored", "reason": "fixture unavailable",
                "execution_admission": "not_performed"})

    def test_main_reads_original_run_odometry_instead_of_cached_forecasts(self):
        states = [anchor()]
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            candidate_path = run_dir/"candidate.json"
            candidate_path.write_text(json.dumps(source_report()))
            (run_dir/"request.json").write_text(json.dumps({"id": "fixture"}))
            output = run_dir/"out.json"
            argv = ["drone-handoff-reanchor", "--candidates", str(candidate_path), "--run-dir", str(run_dir),
                "--drone-root", str(ROOT), "--native", str(NATIVE), "--max-iterations", "1", "--output", str(output)]
            with patch.object(sys, "argv", argv), \
                    patch.object(study.pv.tracking, "read_odometry", return_value=(states, {}, 1)) as read, \
                    patch.object(study, "run", return_value={"summary": {"hypotheses": 4}}) as run, \
                    patch("builtins.print"):
                study.main()
            read.assert_called_once_with(run_dir)
            self.assertEqual(run.call_args.args[1:3], (states, 1))
            self.assertEqual(run.call_args.args[5], "fixture")
            self.assertEqual(run.call_args.kwargs, {"max_iterations": 1})
            self.assertEqual(json.loads(output.read_text()), {"summary": {"hypotheses": 4}})


@unittest.skipUnless(NATIVE.exists(), "existing offline MINCO S4 inner-point executable unavailable")
class NativeHandoffReanchorTests(unittest.TestCase):
    def test_one_iteration_native_fixture_retains_endpoint_pvaj_and_axis_knots_without_real_qualification(self):
        result = study.run([source_report()], [anchor()], 1, ROOT, NATIVE, "fixture", max_iterations=1)
        audit, handoff = study.qualification.committed.reuse(ROOT)
        self.assertEqual(result["summary"]["audited"], 4)
        self.assertEqual(result["summary"]["full_vehicle_handoffs_qualified"], 0)
        self.assertEqual(result["dynamic_closed_loop"], "not_passed")
        self.assertEqual(result["execution_admission"], "not_performed")
        self.assertEqual(result["actual_qualification"]["vehicle_A_J"], "unknown")
        self.assertEqual(result["actual_qualification"]["PX4_adoption"], "not_performed")
        for row in result["rows"]:
            with self.subTest(profile=row["profile"]["name"]):
                candidate = row["resolved"]["candidate"]
                native, request = candidate["native"], candidate["request"]
                self.assertEqual(native["generator"], "official_MINCO_S4NU_axis_inner_points")
                self.assertEqual(native["axis_piece_counts"], [1, 2, 1])
                self.assertTrue(candidate["axis_knot_contract"]["passed"])
                self.assertLessEqual(row["resolved"]["optimizer"]["iterations"], 1)
                for piece, u, pva, jerk in ((native["pieces"][0], 0., request["initial_pva"], request["initial_jerk"]),
                        (native["pieces"][-1], 1., request["terminal_pva"], request["terminal_jerk"])):
                    power = audit.normalized_power(piece)
                    actual = np.column_stack([np.polynomial.polynomial.polyval(u,
                        audit.derivative(power, piece["duration"], order)) for order in range(4)])
                    np.testing.assert_allclose(actual, np.column_stack([pva, jerk]), atol=1e-8, rtol=0.)
                self.assertEqual(row["start_sim_s"], 11.)
                self.assertAlmostEqual(row["tail_end_sim_s"], 11.+handoff.duration(native))
                self.assertNotIn("prefix_pieces", candidate)
                self.assertEqual(row["execution_admission"], "not_performed")
                self.assertIn("unqualified", row["real_handoff"])
        json.dumps(result, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
