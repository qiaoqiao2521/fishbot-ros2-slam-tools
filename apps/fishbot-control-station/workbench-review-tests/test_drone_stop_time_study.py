# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Z stopping time re-solves preserve PVA/J and the original hard gates."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("time_study_fixtures", HERE/"test_drone_reference_stops.py")
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
source, geometry, reference = fixture.source, fixture.geometry, fixture.study
study = source.load("drone-stop-time-study")


class TimeStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        window = source.primitives.restrict({"order": 3, "knots": [0.,0.,0.,0.,1.,1.,1.,1.],
            "control_points": [[0.,0.,1.5],[0.,0.,1.5],[0.,0.,1.5],[0.,.05,1.505]],
            "start_sim_s": 10., "received_sim_s": 10., "task_id": "fixture", "trajectory_id": 1},
            .8, source.curve, source.audit, source.LIMITS)
        cls.data = {"archive_task_id": "fixture", "clock": "sim", "limits": source.LIMITS, "windows": [window]}
        cls.previous = reference.run(cls.data, source.ROOT, source.NATIVE, fixture.NATIVE, max_iterations=1)
        cls.result = study.run(cls.data, cls.previous, source.ROOT, fixture.NATIVE,
            trajectory_ids=[1], z_samples=[.4, .6], max_iterations=1)

    def test_default_time_domain_is_unchanged_and_override_is_explicit(self):
        old = self.previous["rows"][0]["search"]["optimizer"]["parameter_bounds"]
        new = self.result["rows"][0]["joint_search"]["optimizer"]["parameter_bounds"]
        self.assertEqual(tuple(old[2]), (.1, .4))
        self.assertEqual(tuple(new[2]), (.1, 1.2))
        self.assertEqual(old[:2]+old[3:], new[:2]+new[3:])
        self.assertEqual(self.result["limits"], source.LIMITS)

    def test_invalid_duration_domain_skips_before_native_generation(self):
        base = self.previous["rows"][0]["candidate"]["request"]
        for bounds in [[0., 1.], [1., .4], [.4,.4], [float('nan'),1.], [1.], "bad"]:
            with patch.object(geometry.tracking, "audit_axis_request") as native:
                result = geometry.search(base, reference.STATIC_BOX, source.LIMITS, fixture.NATIVE,
                    source.audit, z_time_bounds=bounds)
            self.assertEqual(result["reason"], "invalid_z_time_bounds")
            native.assert_not_called()

    def test_fixed_sweep_preserves_five_parameters_and_initial_pvaj(self):
        row = self.result["rows"][0]; original = self.data["windows"][0]
        values = np.asarray(row["source_values"]); keep = [0,1,3,4,5]
        for variant in row["fixed_five_parameter_sweep"]:
            self.assertEqual(variant["status"], "generated")
            np.testing.assert_array_equal(np.asarray(variant["values"])[keep], values[keep])
            c = variant["candidate"]
            self.assertEqual(c["prefix_pieces"], original["pieces"])
            np.testing.assert_array_equal(c["request"]["initial_pva"], np.asarray(original["terminal_pvaj_xyz_columns"])[:,:3])
            np.testing.assert_array_equal(c["request"]["initial_jerk"], np.asarray(original["terminal_pvaj_xyz_columns"])[:,3])
            self.assertTrue(c["cut_c3_passed"])
            self.assertTrue(c["tail_math_gate"]["axis_knot_contract"]["passed"])

    def test_z_endpoint_changes_by_existing_formula_while_full_end_time_does_not(self):
        variants = self.result["rows"][0]["fixed_five_parameter_sweep"]
        candidates = [v["candidate"] for v in variants]
        for v,c in zip(variants,candidates):
            p,vz,_ = c["request"]["initial_pva"][2]
            self.assertAlmostEqual(c["request"]["stop_positions"][2], p+.5*v["z_stop_s"]*vz)
        self.assertNotEqual(candidates[0]["request"]["stop_positions"][2], candidates[1]["request"]["stop_positions"][2])
        self.assertAlmostEqual(candidates[0]["end_sim_s"], candidates[1]["end_sim_s"])

    def test_final_full_curve_gets_both_box_certificates_and_replay(self):
        row = self.result["rows"][0]
        for variant in row["fixed_five_parameter_sweep"]+[row["joint"]]:
            self.assertIn("pieces", variant["full_static_box_gate"])
            self.assertIn("pieces", variant["narrow_box_gate"])
            self.assertEqual(variant["candidate"]["full_continuity_claim"], "C2")
        self.assertEqual(len(row["counterfactual_replay"]["scenarios"]), 16)
        self.assertEqual(self.result["execution_admission"], "not_performed")

    def test_broken_optional_sample_and_missing_source_do_not_block_good_item(self):
        result = study.run(self.data, self.previous, source.ROOT, fixture.NATIVE,
            trajectory_ids=[999,1], z_samples=[-.1, float('nan'), "bad", .6], max_iterations=1)
        self.assertEqual(result["rows"][0]["status"], "unscored")
        good = result["rows"][1]
        self.assertEqual(good["status"], "generated")
        self.assertEqual([r["status"] for r in good["fixed_five_parameter_sweep"]], ["unscored","unscored","unscored","generated"])
        json.dumps(result, allow_nan=False)

    def test_malformed_source_items_skip_and_invalid_domain_report_remains_serializable(self):
        data = copy.deepcopy(self.data); previous = copy.deepcopy(self.previous)
        data["windows"].extend([None, [], {"trajectory_id": []}])
        previous["rows"].extend([None, 4, {"trajectory_id": []}])
        result = study.run(data, previous, source.ROOT, fixture.NATIVE,
            trajectory_ids=[1], z_samples=[.6], z_domain=[.1, float('inf')], max_iterations=1)
        row = result["rows"][0]
        self.assertEqual(row["fixed_five_parameter_sweep"][0]["status"], "generated")
        self.assertEqual(row["joint_search"]["reason"], "invalid_z_time_bounds")
        json.dumps(result, allow_nan=False)

    def test_edited_source_boundary_is_not_replaced_with_zero_a_or_j(self):
        edited = copy.deepcopy(self.previous)
        edited["rows"][0]["candidate"]["request"]["initial_jerk"][2] += .1
        result = study.run(self.data, edited, source.ROOT, fixture.NATIVE,
            trajectory_ids=[1], z_samples=[.6], max_iterations=1)
        variant = result["rows"][0]["fixed_five_parameter_sweep"][0]
        self.assertEqual(variant["reason"], "tail_request_changes_reference_boundary")
        self.assertNotIn("native", variant["candidate"])


if __name__ == "__main__":
    unittest.main()
