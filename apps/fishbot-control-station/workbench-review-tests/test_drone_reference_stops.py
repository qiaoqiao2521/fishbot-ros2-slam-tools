# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Historical-prefix integration, with reference and fixture claims separated."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


source = load("reference_fixtures", HERE/"test_drone_stop_candidates.py")
study = source.load("drone-reference-stops")
geometry = source.load("drone-stop-geometry")
replay = source.load("drone-committed-replay")
NATIVE = Path.home()/".cache/ros2-drone/minco-s4-knots/minco_s4_knots"


class ReferenceStopTests(unittest.TestCase):
    def candidate(self, window=None, request=None):
        window = window or source.window()
        if request is None:
            base = source.handoff.axis_stop_request({"initial_pva": np.asarray(window["terminal_pvaj_xyz_columns"])[:, :3].tolist(),
                "original_local_target": [0., 0., 1.5], "corridor": []}, [3.5, 1., .4],
                np.asarray(window["terminal_pvaj_xyz_columns"])[:, 3].tolist())
            request = geometry.geometry_request(base, [3.5, 1., .4, 0., .5, .8], y_inner=True)
        return source.candidates.compare(window, source.LIMITS, [3.5, 1., .4], NATIVE,
            source.audit, source.handoff, tail_request=request)

    def test_native_override_keeps_exact_prefix_and_cut_jerk(self):
        window = source.window(); before = copy.deepcopy(window)
        row = self.candidate(window)
        self.assertEqual(window, before)
        self.assertEqual(row["prefix_pieces"], window["pieces"])
        self.assertTrue(row["full_math_gate"]["passed"])
        self.assertTrue(row["cut_c3_passed"])
        self.assertTrue(row["tail_math_gate"]["axis_knot_contract"]["passed"])
        self.assertEqual(row["request"]["initial_jerk"], np.asarray(window["terminal_pvaj_xyz_columns"])[:, 3].tolist())
        self.assertEqual(row["full_continuity_claim"], "C2")
        self.assertEqual(row["start_sim_s"], window["window_start_sim_s"])

    def test_reference_boundary_cannot_be_changed_by_tail_request(self):
        request = self.candidate()["request"]
        for field, index in [("initial_jerk", 0), ("initial_pva", (0, 1))]:
            bad = copy.deepcopy(request)
            if isinstance(index, tuple): bad[field][index[0]][index[1]] += .01
            else: bad[field][index] += .01
            row = self.candidate(request=bad)
            self.assertEqual(row["reason"], "tail_request_changes_reference_boundary")
            self.assertNotIn("native", row)

    def test_stale_declared_jerk_is_checked_against_actual_prefix(self):
        window = source.window(); window["terminal_pvaj_xyz_columns"][0][3] += .01
        self.assertEqual(self.candidate(window)["reason"], "reference_cut_pvaj_mismatch")

    def test_actual_inner_point_metadata_is_reaudited_on_generated_curve(self):
        original = self.candidate(); request = copy.deepcopy(original["request"])
        # Correct native identity alone is insufficient: its supplied curve
        # still has Y=0, which contradicts the edited interior Y=.1.
        request["axis_inner_positions_xyz"][1][0] = .1
        reply = SimpleNamespace(stdout="MincoResult "+json.dumps(original["native"]), stderr="", returncode=0)
        with patch.object(source.candidates.subprocess, "run", return_value=reply):
            row = self.candidate(request=request)
        self.assertEqual(row["status"], "generated")
        self.assertFalse(row["full_math_gate"]["passed"])
        self.assertIn("tail_axis_knots", row["full_math_gate"]["failed_checks"])

    def test_final_generation_must_acknowledge_inner_point_interface(self):
        original = self.candidate()
        for field, value in [("generator", "legacy"), ("axis_piece_counts", [1, 1, 1])]:
            native = {**original["native"], field: value}
            reply = SimpleNamespace(stdout="MincoResult "+json.dumps(native), stderr="", returncode=0)
            with patch.object(source.candidates.subprocess, "run", return_value=reply):
                row = self.candidate(request=original["request"])
            self.assertEqual(row["reason"], "native_inner_point_interface_unacknowledged")
            self.assertNotIn("native", row)

    def test_replay_forecast_uses_actual_complete_duration_plus_terminal_window(self):
        row = self.candidate()
        context = {"task_id": "fixture", "scene_revision": "static-test",
            "clock_id": "sim-epoch-1", "frame_id": "scene_enu_m"}
        first = replay.fixture_scenarios(row, row, context, source.handoff)["reject_preserves_phase_then_brakes"][0]
        for short in [0., .01]:
            event = copy.deepcopy(first)
            event["snapshot"]["valid_until_sim_s"] = row["end_sim_s"]+.5-short
            engine = replay.Replay(context, source.LIMITS, source.audit, source.handoff)
            result = engine.step(event)
            self.assertEqual(result["candidate_accepted"], short == 0.)
            if short:
                self.assertIn("map_prediction_horizon_unverified", result["candidate_rejections"])

    def test_finite_box_audits_full_prefix_not_only_tail(self):
        row = self.candidate()
        self.assertTrue(study.static_gate(row, study.STATIC_BOX, source.LIMITS, source.audit)["passed"])
        # Entire tail lies above this X minimum; the historical prefix starts
        # at X=0 and must still fail the complete finite-space certificate.
        box = [[.02, -10., 0.], [15., 10., 2.2]]
        tail = source.audit.audit_trajectory(row["native"], {**row["request"], "integral_resolution": 16,
            "corridor": [study.box_faces(box)]}, [], source.LIMITS, box)
        self.assertTrue(tail["passed"])
        full = study.static_gate(row, box, source.LIMITS, source.audit)
        self.assertFalse(full["passed"])

    def test_replacement_time_is_evidence_not_a_prefix_truncation(self):
        window = source.window(); next_window = {"received_sim_s": 10.2}
        result = study.timing(window, [window, {}, next_window])
        self.assertTrue(result["replaced_before_cut"])
        self.assertAlmostEqual(result["prefix_duration_s"], .8)
        bad = copy.deepcopy(window); bad["window_end_sim_s"] += .1
        with self.assertRaisesRegex(ValueError, "time_mismatch"):
            study.timing(bad, [window])

    def test_identity_and_bad_item_skip_without_blocking_valid_comparison(self):
        good = source.window(); malformed = {**copy.deepcopy(good), "pieces": []}
        unknown = {**copy.deepcopy(good), "task_attribution": "unrecorded"}
        modules = {"drone-stop-candidates": source.candidates, "drone-stop-geometry": geometry,
                   "drone-committed-replay": replay}
        with patch.object(study, "load", side_effect=lambda name: modules[name]):
            # X-only source is outside the existing +Y family. A valid baseline
            # remains recorded; the unsupported search is never fabricated.
            result = study.run({"archive_task_id": "fixture", "clock": "sim", "limits": source.LIMITS,
                "windows": [malformed, unknown, good]}, source.ROOT, source.NATIVE, NATIVE)
        self.assertEqual(result["summary"]["source_windows"], 3)
        self.assertIn("baseline", result["rows"][-1])
        self.assertEqual(result["rows"][-1]["reason"], "outside_recorded_positive_y_profile")
        self.assertEqual(result["actual_qualification"]["dynamic_closed_loop"], "not_passed")

    def test_full_pipeline_supplies_frozen_auditor_inputs_to_search(self):
        window = source.primitives.restrict({"order": 3, "knots": [0.,0.,0.,0.,1.,1.,1.,1.],
            "control_points": [[0.,0.,1.5],[0.,0.,1.5],[0.,0.,1.5],[0.,.05,1.5]],
            "start_sim_s": 10., "received_sim_s": 10., "task_id": "fixture", "trajectory_id": 1},
            .8, source.curve, source.audit, source.LIMITS)
        result = study.run({"archive_task_id": "fixture", "clock": "sim", "limits": source.LIMITS,
            "windows": [window]}, source.ROOT, source.NATIVE, NATIVE, max_iterations=1)
        row = result["rows"][0]
        self.assertEqual(row["status"], "generated")
        self.assertTrue(row["candidate"]["cut_c3_passed"])
        self.assertEqual(len(row["counterfactual_replay"]["scenarios"]), 16)
        self.assertEqual(row["candidate"]["execution_admission"], "not_performed")


if __name__ == "__main__":
    unittest.main()
