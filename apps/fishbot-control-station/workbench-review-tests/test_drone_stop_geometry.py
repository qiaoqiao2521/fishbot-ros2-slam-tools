# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Free endpoints must preserve boundary provenance and pass the original gate."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

TOOLS = Path(__file__).parents[1]/"workbench-tools"
spec = importlib.util.spec_from_file_location("stop_geometry", TOOLS/"drone-stop-geometry.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ROOT = Path.home()/"dev/ros2/projects/drone"
NATIVE = Path.home()/".cache/ros2-drone/minco-probe/minco_probe"
audit, handoff = module.tracking.load("stop_tools", TOOLS/"drone-stop-candidates.py").load_modules(ROOT)
BOX = [[1.5, -1., .8], [9.5, 2.03, 2.2]]
LIMITS = {"speed": 1.8, "acceleration": 1., "ceiling": 2.2, "local_target_tolerance": .3}


def boundary(position=None, velocity=None):
    # Original 748f910e source PV at 33.428s, not a measured A/J fixture.
    p = position or [2.6904671845162187, 1.8511652340733886, 2.183529178304161]
    v = velocity or [1.2332207669299111, .4438060272580974, .04771474613355203]
    corridor = []
    for axis in range(3):
        normal = np.eye(3)[axis]
        corridor.extend([np.r_[normal, -BOX[1][axis]].tolist(), np.r_[-normal, BOX[0][axis]].tolist()])
    request = handoff.axis_stop_request({"id": "test-conditional-stop", "initial_pva": np.column_stack([p, v, np.zeros(3)]).tolist(),
        "original_local_target": [8., 0., 1.8], "corridor": [corridor], "integral_resolution": 16}, [3.5, 1., .4])
    request["initial_condition_scope"] = "A/J zero hypotheses, not measured"
    return request


class GeometryRequestTests(unittest.TestCase):
    def test_endpoint_sync_preserves_initial_pva_j_and_original_mission_target(self):
        original = boundary()
        original["initial_pva"][0][2] = .1
        original["initial_jerk"] = [.02, -.03, .01]
        before = copy.deepcopy(original)
        result = module.geometry_request(original, [5., .93, .18, .17])
        self.assertEqual(original, before)
        self.assertEqual(result["initial_pva"], before["initial_pva"])
        self.assertEqual(result["initial_jerk"], before["initial_jerk"])
        self.assertEqual(result["source_local_target_before_stop"], [8., 0., 1.8])
        np.testing.assert_array_equal(np.asarray(result["terminal_pva"])[:, 0], result["stop_positions"])
        self.assertEqual(result["original_local_target"], result["stop_positions"])
        twice = module.geometry_request(result, [4.5, 1., .2, .16])
        self.assertEqual(twice["source_local_target_before_stop"], [8., 0., 1.8])
        self.assertEqual(twice["initial_pva"], before["initial_pva"])

    def test_unknown_jerk_is_not_promoted_to_explicit_measurement(self):
        result = module.geometry_request(boundary(), [5., .93, .18, .17])
        self.assertNotIn("initial_jerk", result)
        self.assertIn("not measured", result["initial_jerk_assumption"])
        self.assertEqual(result["required_continuity_order"], 3)

    def test_invalid_profile_remains_unscored(self):
        for base, inset in (({}, .002), ({"initial_pva": [[1.]]}, .002),
                            (boundary(), -.001), (boundary(), float("nan"))):
            self.assertEqual(module.search(base, BOX, LIMITS, NATIVE, audit, planning_inset=inset)["status"], "unscored")

    def test_batch_retains_provenance_without_promoting_necessary_rejection(self):
        variants = {}
        for name, necessary, baseline in (("constant_velocity", "necessary_reject", None),
                ("retrospective_source_pv", "not_ruled_out", None)):
            variants[name] = {"pv_at_sim_s": 33.428, "provenance": "test input", "necessary": {"status": necessary},
                              "conditional_axis_stop": baseline}
        data = {"archive_task_id": "original-task", "stopping": {"box": BOX, "limits": LIMITS,
            "cases": [{"kind": "reanchor", "forecast_at_sim_s": 33.42, "oracle_source_offset_s": .008, "variants": variants}]}}
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory)/"input.json"; file.write_text(json.dumps(data))
            result = module.run(file, ROOT, NATIVE)
        self.assertEqual(result["rows"][0]["status"], "not_searched")
        self.assertEqual(result["rows"][1]["status"], "unscored")
        self.assertIn("retrospective counterfactual", result["rows"][1]["input_role"])
        self.assertEqual(result["execution_admission"], "not_performed")

    def test_edited_variant_pv_is_not_scored_under_a_stale_boundary(self):
        base = boundary(); pv = np.asarray(base["initial_pva"])
        variant = {"pv_at_sim_s": 33.428, "provenance": "test input", "position": pv[:, 0].tolist(),
            "velocity": pv[:, 1].tolist(), "necessary": {"status": "not_ruled_out"},
            "conditional_axis_stop": {"status": "audited", "request": base, "audit": {"passed": True}}}
        changed = copy.deepcopy(variant); changed["position"][1] += .01
        variants = {"edited_pv": changed, "unchanged_pv": variant, "unknown_bound": {**variant, "necessary": {"status": "unscored"}}}
        data = {"archive_task_id": "original-task", "stopping": {"box": BOX, "limits": LIMITS,
            "cases": [{"kind": "reanchor", "forecast_at_sim_s": 33.42, "oracle_source_offset_s": .008, "variants": variants}]}}
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory)/"input.json"; file.write_text(json.dumps(data))
            with patch('builtins.print') as warning:
                result = module.run(file, ROOT, NATIVE)
        self.assertEqual(result["rows"][0]["reason"], "variant_and_boundary_pv_mismatch")
        self.assertEqual(result["rows"][1]["status"], "unchanged")
        self.assertEqual(result["rows"][2]["reason"], "necessary_bound_unqualified")
        self.assertTrue(warning.called)


@unittest.skipUnless(NATIVE.exists(), "existing offline MINCO executable unavailable")
class NativeGeometryTests(unittest.TestCase):
    def test_free_endpoint_resolves_recorded_counterfactual_without_relaxing_gate(self):
        base = boundary()
        result = module.search(base, BOX, LIMITS, NATIVE, audit)
        self.assertEqual(result["status"], "audited")
        self.assertTrue(result["candidate"]["audit"]["passed"])
        self.assertLessEqual(result["candidate"]["audit"]["acceleration_max"], 1.)
        self.assertEqual(result["candidate"]["request"]["initial_pva"], base["initial_pva"])
        self.assertGreaterEqual(min(result["diagnostics"]["whole_curve_face_margins_m"]), .00199)
        self.assertEqual(LIMITS["acceleration"], 1.)

    def test_causal_model_pv_uses_same_explicit_boundary_assumptions(self):
        base = boundary([2.694011499914361, 1.8509274362066406, 2.1873977142025036],
                        [1.2451533547353655, .4228485388521911, .07753463600274953])
        result = module.search(base, BOX, LIMITS, NATIVE, audit)
        self.assertTrue(result["candidate"]["audit"]["passed"])
        np.testing.assert_array_equal(np.asarray(result["candidate"]["request"]["initial_pva"])[:, 2], [0.]*3)
        self.assertIn("not measured", result["candidate"]["assumption"])
        self.assertLess(result["diagnostics"]["reverse_y_speed_m_s"], 1e-8)

    def test_legal_endpoint_can_still_overshoot_continuous_box(self):
        request = module.geometry_request(boundary(), [3.5, 1.4, .4, .15])
        result = module.tracking.audit_axis_request(request, BOX, LIMITS, NATIVE, audit)
        self.assertLess(request["stop_positions"][1], BOX[1][1])
        self.assertFalse(result["audit"]["passed"])
        self.assertIn("corridor", result["audit"]["failed_checks"])
        self.assertGreater(module.extrema(result["native"], audit)["upper"][1], 2.03)
        self.assertGreater(module.extrema(result["native"], audit)["reverse_y_speed_m_s"], 0.)

    def test_optimizer_success_is_not_an_audit_pass(self):
        returned = SimpleNamespace(x=np.array([3.5, 1.4, .4, .15]), success=True, message="test optimizer", nfev=1, nit=1)
        with patch.object(module, "minimize", return_value=returned):
            result = module.search(boundary(), BOX, LIMITS, NATIVE, audit)
        self.assertTrue(result["optimizer"]["success"])
        self.assertFalse(result["candidate"]["audit"]["passed"])
        self.assertEqual(result["execution_admission"], "not_performed")

    def test_native_reconstruction_retains_nonzero_initial_a_and_j(self):
        base = boundary(); base["initial_pva"][0][2] = .03; base["initial_jerk"] = [.02, -.01, .005]
        request = module.geometry_request(base, [5., 1., .2, .17])
        result = module.tracking.audit_axis_request(request, BOX, LIMITS, NATIVE, audit)
        self.assertLess(result["audit"]["boundary_pva_error"], 1e-8)
        self.assertLess(result["audit"]["boundary_jerk_error"], 1e-8)
        self.assertEqual(request["initial_jerk"], base["initial_jerk"])

    def test_missing_native_is_not_replaced_by_a_cached_pass(self):
        result = module.search(boundary(), BOX, LIMITS, Path('/nonexistent/minco'), audit)
        self.assertEqual(result["status"], "unscored")
        self.assertNotIn("candidate", result)


if __name__ == "__main__":
    unittest.main()
