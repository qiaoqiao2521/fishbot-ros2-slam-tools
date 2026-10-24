# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Official S4NU inner points must preserve C3 and per-axis stopping contracts."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest

import numpy as np

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("s4_fixtures", HERE/"test_drone_stop_geometry.py")
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
module = fixture.module
NATIVE = Path.home()/".cache/ros2-drone/minco-s4-knots/minco_s4_knots"


def pvaj(native, elapsed):
    for piece in native["pieces"]:
        if elapsed <= piece["duration"]+1e-12:
            return np.array([[np.polyval(np.polyder(c, k), min(elapsed, piece["duration"])) for k in range(4)]
                for c in piece["coefficients_descending"]])
        elapsed -= piece["duration"]
    raise ValueError("outside curve")


def run_native(requests, executable=NATIVE):
    lines = [r if isinstance(r, str) else json.dumps(r) for r in requests]
    result = subprocess.run([str(executable)], input="\n".join(lines)+"\n", text=True,
        capture_output=True, timeout=10)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return [json.loads(line.split(" ", 1)[1]) for line in result.stdout.splitlines() if line.startswith("MincoResult ")]


class InnerRequestTests(unittest.TestCase):
    def test_inner_point_does_not_pin_internal_vaj_or_change_initial_boundary(self):
        base = fixture.boundary(); base["initial_pva"][1][2] = .2; base["initial_jerk"] = [.1, -.2, .03]
        before = copy.deepcopy(base)
        request = module.geometry_request(base, [5., 1., .4, .15, .4, .8], y_inner=True)
        self.assertEqual(base, before)
        self.assertEqual(request["initial_pva"], base["initial_pva"])
        self.assertEqual(request["initial_jerk"], base["initial_jerk"])
        self.assertEqual(request["axis_segment_durations_xyz"], [[5.], [.4, .6], [.4]])
        self.assertAlmostEqual(request["axis_inner_positions_xyz"][1][0], base["initial_pva"][1][0]+.12)
        self.assertNotIn("junction_pva", request)
        self.assertEqual(request["source_local_target_before_stop"], base["source_local_target_before_stop"])
        single = module.geometry_request(request, [5., 1., .4, .15])
        self.assertNotIn("axis_inner_positions_xyz", single)
        self.assertNotIn("axis_segment_durations_xyz", single)

    def test_tiny_hold_interval_is_checked_separately_from_stop_time_tolerance(self):
        duration = 1e-10; amplitude = 1e-32
        unit = (np.polynomial.Polynomial([1., -1.])**4).coef
        physical = unit*amplitude/np.power(duration, np.arange(len(unit)))
        coefficients = np.zeros((3, 8)); coefficients[0, -len(physical):] = physical[::-1]
        native = {"pieces": [{"duration": duration, "coefficients_descending": coefficients.tolist()}]}
        request = {"axis_stop_durations_xyz": [.5*duration, duration, duration], "stop_positions": [0., 0., 0.]}
        self.assertLess(np.max(abs(pvaj(native, duration))), 1e-8)
        result = module.audit_axis_knots(native, request, fixture.audit)
        self.assertFalse(result["passed"])
        self.assertGreater(result["maximum_residual_PVAJ_by_axis"][0][3], .1)


@unittest.skipUnless(NATIVE.exists() and fixture.NATIVE.exists(), "existing offline native interfaces unavailable")
class NativeS4Tests(unittest.TestCase):
    def request(self, values=None):
        return module.geometry_request(fixture.boundary(), values or [5., 1., .4, .15, .4, .8], y_inner=True)

    def test_no_inner_points_reproduce_the_existing_single_axis_curves(self):
        request = module.geometry_request(fixture.boundary(), [5., .93, .18, .16])
        actual = run_native([request])[0]; old = run_native([request], fixture.NATIVE)[0]
        self.assertTrue(actual["native_success"])
        self.assertEqual(actual["axis_piece_counts"], [1, 1, 1])
        for t in np.linspace(0., 5., 31):
            np.testing.assert_allclose(pvaj(actual, t), pvaj(old, t), rtol=0, atol=1e-9)

    def test_declared_inner_position_changes_the_curve_and_is_really_hit(self):
        first = self.request(); second = self.request([5., 1., .4, .15, .4, .6])
        curves = run_native([first, second])
        for request, native in zip([first, second], curves):
            self.assertTrue(native["native_success"])
            self.assertEqual(native["axis_piece_counts"], [1, 2, 1])
            self.assertAlmostEqual(pvaj(native, .4)[1, 0], request["axis_inner_positions_xyz"][1][0], places=9)
            self.assertTrue(module.audit_axis_knots(native, request, fixture.audit)["passed"])
        self.assertGreater(abs(pvaj(curves[0], .4)[1, 0]-pvaj(curves[1], .4)[1, 0]), .02)
        bad = copy.deepcopy(first); bad["axis_inner_positions_xyz"][1][0] += .03
        self.assertFalse(module.audit_axis_knots(curves[0], bad, fixture.audit)["passed"])

    def test_nonzero_initial_pvaj_and_c3_survive_the_unified_breakpoints(self):
        request = self.request([5., 1.1, .25, .16, .45, .8])
        for axis, value in enumerate([.03, .2, -.05]): request["initial_pva"][axis][2] = value
        request["initial_jerk"] = [.1, -.1, .03]
        native = run_native([request])[0]
        self.assertTrue(native["native_success"])
        expected = np.column_stack([request["initial_pva"], request["initial_jerk"]])
        np.testing.assert_allclose(pvaj(native, 0.), expected, rtol=0, atol=1e-8)
        for previous, current in zip(native["pieces"], native["pieces"][1:]):
            a = pvaj({"pieces": [previous]}, previous["duration"])
            b = pvaj({"pieces": [current]}, 0.)
            np.testing.assert_allclose(a, b, rtol=0, atol=1e-8)
        self.assertTrue(module.audit_axis_knots(native, request, fixture.audit)["passed"])

    def test_common_stop_times_and_overlapping_internal_nodes_are_supported(self):
        for values, pieces in [([1., 1., 1., .15, .5, .8], 2), ([5., 1., .4, .15, .4, .8], 3)]:
            request = self.request(values); native = run_native([request])[0]
            self.assertTrue(native["native_success"])
            self.assertEqual(len(native["pieces"]), pieces)
            self.assertTrue(module.audit_axis_knots(native, request, fixture.audit)["passed"])

    def test_axis_stop_metadata_cannot_hide_motion_after_that_time(self):
        request = self.request(); native = run_native([request])[0]
        bad = copy.deepcopy(request); bad["axis_stop_durations_xyz"][2] = .05
        bad["axis_segment_durations_xyz"][2] = [.05]
        result = module.audit_axis_knots(native, bad, fixture.audit)
        self.assertFalse(result["passed"])
        self.assertGreater(max(result["maximum_residual_PVAJ_by_axis"][2]), 1e-4)

    def test_nearby_axis_knots_do_not_refit_or_change_unaffected_xy_polynomials(self):
        first = self.request([3.5, .9994447264216297, .4, .18728824258131896,
                              .4988675808857195, .8507967875308301])
        first["initial_pva"] = [[3.3588164448570073,1.489432157919301,.28178840537663435],
            [2.132179257196546,.36902106071049245,-.3831968238939351],
            [2.121164784137278,-.1425450258909372,-.5908327335097329]]
        first["initial_jerk"] = [-.12931996715376998,-.1438908562505944,.08490949631904857]
        first = module.geometry_request(first, [3.5,.9994447264216297,.4,.18728824258131896,
            .4988675808857195,.8507967875308301], y_inner=True)
        curves = []
        for tz in [.4,.5,1.]:
            request = copy.deepcopy(first); request["axis_stop_durations_xyz"][2] = tz
            request["axis_segment_durations_xyz"][2] = [tz]
            request["stop_positions"][2] = first["initial_pva"][2][0]+.5*tz*first["initial_pva"][2][1]
            curves.append(run_native([request])[0])
        for native in curves:
            self.assertTrue(native["native_success"])
            self.assertEqual(native["unified_piece_method"], "source_polynomial_time_translation_no_refit")
            # The tiny union intervals around .5 and 1 are checked inside,
            # not just at their already constrained endpoint PVA/J.
            elapsed = 0.
            for piece in native["pieces"]:
                for u in [.1,.25,.5,.75,.9]:
                    t = elapsed+u*piece["duration"]
                    np.testing.assert_allclose(pvaj(native,t)[:2],pvaj(curves[0],t)[:2],rtol=0,atol=1e-8)
                elapsed += piece["duration"]

    def test_invalid_rows_and_nonadvancing_time_do_not_stop_the_following_input(self):
        good = self.request(); wrong_size = copy.deepcopy(good)
        wrong_size["axis_inner_positions_xyz"][1] = []
        nonpositive = copy.deepcopy(good); nonpositive["axis_segment_durations_xyz"][1][0] = 0.
        mismatch = copy.deepcopy(good); mismatch["axis_segment_durations_xyz"][1][0] += .1
        stalled = copy.deepcopy(good); stalled["axis_stop_durations_xyz"][0] = 1.
        stalled["axis_inner_positions_xyz"][0] = [2.8]
        stalled["axis_segment_durations_xyz"][0] = [1., 1e-300]
        nonfinite = copy.deepcopy(good); nonfinite["initial_pva"][0][0] = float('nan')
        results = run_native(['{"broken":', wrong_size, nonpositive, mismatch, stalled, nonfinite, good])
        self.assertEqual(len(results), 7)
        self.assertTrue(all(not r["native_success"] for r in results[:-1]))
        self.assertIn("strictly advance", results[4]["error"])
        self.assertTrue(results[-1]["native_success"])

    def test_frozen_native_does_not_acknowledge_the_new_freedom(self):
        result = module.search(fixture.boundary(), fixture.BOX, fixture.LIMITS, fixture.NATIVE,
            fixture.audit, y_inner=True)
        self.assertEqual(result["status"], "unscored")
        self.assertIn("did not acknowledge", result["reason"])

    def test_committed_replay_reaudits_edited_inner_point_metadata(self):
        request = self.request([5., .85, .2, .176, .2, .4])
        native = run_native([request])[0]
        replay = module.tracking.load("s4_replay", HERE.parent/"workbench-tools/drone-committed-replay.py")
        _, handoff = replay.reuse(fixture.ROOT)
        engine = replay.Replay({}, fixture.LIMITS, fixture.audit, handoff)
        row = {"kind": "axis_stop_geometry_candidate", "request": copy.deepcopy(request), "native": native,
            "hard_box": fixture.BOX, "audit": {"passed": True}}
        head = np.asarray(request["initial_pva"]); prefix = np.zeros((3, 8))
        prefix[:, -2] = head[:, 1]; prefix[:, -1] = head[:, 0]-.1*head[:, 1]
        full = {"request": copy.deepcopy(request), "native": native,
            "prefix_pieces": [{"duration": .1, "coefficients_descending": prefix.tolist()}],
            "full_math_gate": {"pieces": [{"start_pva": np.column_stack([prefix[:, -1], head[:, 1], np.zeros(3)]).tolist()}]},
            "scope": "synthetic constant-velocity prefix only; not executed history"}
        for candidate, failure in [(row, "axis_knots"), (full, "tail_axis_knots")]:
            with self.subTest(failure=failure):
                self.assertTrue(engine.score(candidate)[1]["passed"])
                candidate["request"]["axis_inner_positions_xyz"][1][0] += .03
                self.assertTrue(fixture.audit.audit_trajectory(native, candidate["request"], [], fixture.LIMITS, fixture.BOX)["passed"])
                result = engine.score(candidate)[1]
                self.assertFalse(result["passed"])
                self.assertIn(failure, result["failed_checks"])


if __name__ == "__main__":
    unittest.main()
