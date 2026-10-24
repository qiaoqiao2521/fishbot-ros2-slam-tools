# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Search diagnostics may change while final hard gates and provenance remain."""
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import numpy as np


HERE = Path(__file__).parent
TOOLS = HERE.parent/"workbench-tools"
BINARY = Path.home()/".cache/ros2-drone/minco-s4-metrics/minco_s4_metrics"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixture = load("extrema_search_fixture", HERE/"test_drone_stop_geometry.py")
qualification = load("extrema_search_qualification", TOOLS/"drone-extrema-qualification.py")
geometry = qualification.geometry
NativeSession = qualification.sessions.NativeSession
GOOD_VALUES = [4.5, 1., .4, .12, .5, .85]


def boundary():
    return fixture.boundary([2.5, 1., 1.5], [.5, .2, .01])


def metrics():
    return {"upper": [4., 1.2, 1.51], "lower": [2.5, 1., 1.5],
        "acceleration_peak_m_s2": .7, "minimum_y_velocity_m_s": 0.,
        "minimum_y_velocity_at_s": 0., "reverse_y_speed_m_s": 0.}


def optimizer(values=GOOD_VALUES, success=True):
    return SimpleNamespace(x=np.asarray(values), success=success,
        message="fixture iteration cap" if not success else "fixture optimizer", nfev=1, nit=1)


def source():
    return {"archive_task_id": "fixture", "rows": [{"variant_id": "fixture",
        "profile": {"name": "zero_A_J"}, "input": {"model": "constant_velocity",
            "position": [2.5, 1., 1.5], "velocity": [.5, .2, .01]},
        "boundary_request": boundary(), "hard_box": copy.deepcopy(fixture.BOX),
        "hard_limits": copy.deepcopy(fixture.LIMITS), "start_sim_s": 11.,
        "resolved": {"candidate": {"request": {"initial_pva": [[-999.]*3]*3}}}}]}


def session_stub():
    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    session.process.poll.return_value = 0
    session.exchange.return_value = {"native_success": True, **metrics()}
    return session


class ExtremaBackendTests(unittest.TestCase):
    def search(self, **options):
        return geometry.search(boundary(), fixture.BOX, fixture.LIMITS, BINARY,
            fixture.audit, y_inner=True, z_time_bounds=(.1, 1.2), max_iterations=1, **options)

    def generated(self, request, *args, **kwargs):
        return {"status": "generated" if kwargs.get("perform_audit") is False else "audited",
            "request": request, "native": {"generator": "official_MINCO_S4NU_axis_inner_points",
                "axis_piece_counts": [1, 2, 1], "pieces": []}, "audit": {"passed": True, "failed_checks": []}}

    def test_explicit_none_uses_original_extrema_and_still_runs_final_audit(self):
        with patch.object(geometry, "minimize", return_value=optimizer()), \
                patch.object(geometry.tracking, "audit_axis_request", side_effect=self.generated) as audit, \
                patch.object(geometry, "extrema", return_value=metrics()) as original, \
                patch.object(geometry, "audit_axis_knots", return_value={"passed": True}):
            result = self.search(metrics_backend=None)
        self.assertEqual(result["status"], "audited")
        original.assert_called_once()
        self.assertEqual(audit.call_count, 2)
        self.assertIs(audit.call_args_list[0].kwargs["perform_audit"], False)
        self.assertNotIn("perform_audit", audit.call_args_list[1].kwargs)
        self.assertTrue(result["candidate"]["audit"]["passed"])

    def test_callback_error_missing_field_and_nonfinite_native_reply_never_fall_back(self):
        missing = metrics()
        del missing["lower"]
        bad_acceleration = {"native_success": True, **metrics(), "acceleration_peak_m_s2": float("nan")}
        bad_range = {"native_success": True, **metrics(), "upper": [4., float("inf"), 1.51]}
        wrong_shape = {"native_success": True, **metrics(), "upper": [[4., 1.2, 1.51]]}
        callbacks = [MagicMock(side_effect=ValueError("backend unavailable")), MagicMock(return_value=missing)]
        for reply in ({"native_success": False, "error": "native failed"},
                {"native_success": True, "upper": [0.]*3}, bad_acceleration, bad_range, wrong_shape):
            exchange = MagicMock(return_value=reply)
            callbacks.append(lambda native, audit, exchange=exchange: qualification.native_search_metrics(native, exchange))
        for callback in callbacks:
            with self.subTest(callback=callback):
                with patch.object(geometry, "minimize", return_value=optimizer()), \
                        patch.object(geometry.tracking, "audit_axis_request", side_effect=self.generated) as audit, \
                        patch.object(geometry, "extrema") as fallback:
                    result = self.search(metrics_backend=callback)
                self.assertEqual(result["status"], "unscored")
                self.assertTrue(result["reason"])
                self.assertEqual(audit.call_count, 1)
                fallback.assert_not_called()


class PairedSearchTests(unittest.TestCase):
    def compare(self, original=None, **options):
        return qualification.run_search(original or source(), fixture.ROOT, BINARY,
            variant_id="fixture", profile_names=("zero_A_J",), max_iterations=1, **options)

    def test_backends_keep_original_seed_provenance_and_alternate_order(self):
        original = source()
        before = copy.deepcopy(original)
        used = []
        seeds = []
        sessions = []

        def make_session(*args, **kwargs):
            session = session_stub()

            def exchange(request):
                self.assertEqual(request["mode"], "rootfinder_extrema")
                used.append("rootfinder")
                return {"native_success": True, **metrics()}

            session.exchange.side_effect = exchange
            sessions.append(session)
            return session

        def python_metrics(native, audit):
            used.append("python")
            return metrics()

        def search(base, box, limits, executable, audit, **options):
            seeds.append(copy.deepcopy(base))
            self.assertEqual(box, before["rows"][0]["hard_box"])
            self.assertEqual(limits, before["rows"][0]["hard_limits"])
            self.assertEqual(options["max_iterations"], 1)
            options["metrics_backend"]({"pieces": []}, audit)
            return {"status": "unscored", "reason": "unit search completed"}

        with patch.object(qualification.sessions, "NativeSession", side_effect=make_session), \
                patch.object(geometry, "search", side_effect=search), \
                patch.object(geometry, "extrema", side_effect=python_metrics):
            result = self.compare(original, repetitions=3)
        self.assertEqual(used, ["python", "rootfinder", "rootfinder", "python", "python", "rootfinder"])
        self.assertEqual([row["backend"] for row in result["rows"]], used)
        self.assertEqual(seeds, [before["rows"][0]["boundary_request"]]*6)
        self.assertEqual(original, before)
        for row in result["rows"]:
            expected_order = ["python", "rootfinder"] if row["repetition"] % 2 == 0 else ["rootfinder", "python"]
            self.assertEqual(row["pair_order"], expected_order)
            self.assertEqual(row["source_input"]["input"], before["rows"][0]["input"])
            self.assertTrue(row["owned_process_exited"])
        for session in sessions:
            session.__exit__.assert_called_once()

    def test_backend_failure_does_not_skip_the_other_backend(self):
        sessions = [session_stub(), session_stub()]
        with patch.object(qualification.sessions, "NativeSession", side_effect=sessions), \
                patch.object(geometry, "search", side_effect=[ValueError("first backend failed"),
                    {"status": "unscored", "reason": "second backend reached"}]) as search:
            result = self.compare(repetitions=1)
        self.assertEqual(search.call_count, 2)
        self.assertEqual(result["rows"][0]["reason"], "first backend failed")
        self.assertEqual(result["rows"][1]["reason"], "second backend reached")
        for session in sessions:
            session.__exit__.assert_called_once()
        self.assertEqual(result["summary"]["python"]["unscored"], 1)
        self.assertEqual(result["summary"]["rootfinder"]["unscored"], 1)

    def test_complete_wall_time_includes_constructor_enter_search_and_close(self):
        clock = SimpleNamespace(now=100.)

        class TimedSession:
            def __init__(self, *args, **kwargs):
                clock.now += 2.
                self.process = SimpleNamespace(poll=lambda: 0)

            def __enter__(self):
                clock.now += 3.
                return self

            def __exit__(self, *args):
                clock.now += 7.

        def search(*args, **kwargs):
            clock.now += 5.
            return {"status": "unscored", "reason": "timing fixture"}

        with patch.object(qualification.time, "perf_counter", side_effect=lambda: clock.now), \
                patch.object(qualification.sessions, "NativeSession", TimedSession), \
                patch.object(geometry, "search", side_effect=search):
            result = self.compare(repetitions=1)
        self.assertEqual([row["wall_s"] for row in result["rows"]], [17., 17.])
        self.assertIn("creation and close", result["timing_scope"])


class SearchSummaryTests(unittest.TestCase):
    def test_fast_rejection_and_unscored_search_cannot_improve_success_timing(self):
        passed = [{"backend": "rootfinder", "profile": "zero_A_J", "status": "audited",
            "math_passed": True, "optimizer": {"success": False}, "wall_s": 6.}]
        baseline = qualification.search_summary(passed)
        rows = passed+[
            {"backend": "rootfinder", "profile": "zero_A_J", "status": "audited",
                "math_passed": False, "optimizer": {"success": True}, "wall_s": .02,
                "final_rejections": ["acceleration"]},
            {"backend": "rootfinder", "profile": "zero_A_J", "status": "unscored",
                "reason": "native unavailable", "wall_s": .001}]
        before = copy.deepcopy(rows)
        result = qualification.search_summary(rows)
        self.assertEqual(rows, before)
        timing = result["wall_summary"]["rootfinder"]
        self.assertEqual(timing["math_passed"], baseline["wall_summary"]["rootfinder"]["math_passed"])
        self.assertEqual(timing["math_rejected"]["samples"], 1)
        self.assertEqual(timing["math_rejected"]["minimum_s"], .02)
        self.assertEqual(timing["unscored"]["samples"], 1)
        self.assertEqual(timing["unscored"]["minimum_s"], .001)
        self.assertEqual(result["summary"]["rootfinder"]["math_passed"], 1)
        self.assertEqual(result["summary"]["rootfinder"]["optimizer_success"], 1)
        self.assertEqual(result["summary"]["rootfinder"]["final_rejection_counts"], {"acceleration": 1})

    def test_new_samples_for_one_profile_do_not_change_other_profile_timings(self):
        rows = [
            {"backend": "rootfinder", "profile": "zero_A_J", "status": "audited",
                "math_passed": True, "wall_s": 12.},
            {"backend": "python", "profile": "zero_A_J", "status": "audited",
                "math_passed": True, "wall_s": 8.},
            {"backend": "rootfinder", "profile": "outward_y_J", "status": "audited",
                "math_passed": True, "wall_s": 30.},
            {"backend": "rootfinder", "profile": "outward_y_J", "status": "audited",
                "math_passed": False, "wall_s": .2},
            {"backend": "rootfinder", "profile": "inward_y_J", "status": "unscored", "wall_s": .001}]
        baseline = qualification.search_summary(rows)
        rows.append({"backend": "rootfinder", "profile": "zero_A_J", "status": "audited",
            "math_passed": True, "wall_s": 2.})
        before = copy.deepcopy(rows)
        result = qualification.search_summary(rows)
        self.assertEqual(rows, before)
        for profile in ("outward_y_J", "inward_y_J"):
            self.assertEqual(result["wall_by_profile"][profile], baseline["wall_by_profile"][profile])
        self.assertEqual(result["wall_by_profile"]["zero_A_J"]["python"],
            baseline["wall_by_profile"]["zero_A_J"]["python"])
        self.assertEqual(result["wall_by_profile"]["zero_A_J"]["rootfinder"]["math_passed"]["samples"], 2)
        self.assertNotIn("math_passed", result["wall_by_profile"]["inward_y_J"]["rootfinder"])


@unittest.skipUnless(BINARY.exists(), "compiled offline MINCO extrema executable unavailable")
class NativeExtremaSearchTests(unittest.TestCase):
    def test_false_low_acceleration_diagnostic_cannot_bypass_final_hard_gate(self):
        base = boundary()
        base["initial_pva"][0][2] = .01
        base["initial_pva"][1][2] = .02
        base["initial_jerk"] = [.02, -.04, .01]
        false_metrics = {**metrics(), "acceleration_peak_m_s2": 0.}
        with NativeSession(BINARY, timeout=2.) as session, \
                patch.object(geometry, "minimize", return_value=optimizer([4.8, 1.2, .6, .15, .6, .4])), \
                patch.object(geometry.tracking, "audit_axis_request", wraps=geometry.tracking.audit_axis_request) as audit:
            result = geometry.search(base, fixture.BOX, fixture.LIMITS, BINARY, fixture.audit,
                y_inner=True, z_time_bounds=(.1, 1.2), max_iterations=1, exchange=session.exchange,
                metrics_backend=lambda native, audit: copy.deepcopy(false_metrics))
        self.assertEqual(audit.call_count, 2)
        self.assertEqual(result["diagnostics"]["acceleration_peak_m_s2"], 0.)
        self.assertTrue(result["optimizer"]["success"])
        self.assertFalse(result["candidate"]["audit"]["passed"])
        self.assertIn("acceleration", result["candidate"]["audit"]["failed_checks"])
        self.assertGreater(result["candidate"]["audit"]["acceleration_max"], fixture.LIMITS["acceleration"])

    def test_axis_knot_failure_still_rejects_candidate_with_native_metrics(self):
        with NativeSession(BINARY, timeout=2.) as session, \
                patch.object(geometry, "minimize", return_value=optimizer()), \
                patch.object(geometry, "audit_axis_knots", return_value={"passed": False, "reason": "fixture knot mismatch"}):
            result = geometry.search(boundary(), fixture.BOX, fixture.LIMITS, BINARY, fixture.audit,
                y_inner=True, z_time_bounds=(.1, 1.2), max_iterations=1, exchange=session.exchange,
                metrics_backend=lambda native, audit: qualification.native_search_metrics(native, session.exchange))
        self.assertEqual(result["status"], "audited")
        self.assertFalse(result["candidate"]["audit"]["passed"])
        self.assertEqual(result["candidate"]["audit"]["failed_checks"], ["axis_knots"])
        self.assertFalse(result["candidate"]["axis_knot_contract"]["passed"])

    def test_one_iteration_pair_keeps_optimizer_failure_and_original_source(self):
        original = source()
        before = copy.deepcopy(original)
        result = qualification.run_search(original, fixture.ROOT, BINARY, variant_id="fixture",
            profile_names=("zero_A_J",), repetitions=1, max_iterations=1)
        self.assertEqual(original, before)
        self.assertEqual(len(result["rows"]), 2)
        for row in result["rows"]:
            self.assertEqual(row["status"], "audited")
            self.assertFalse(row["optimizer"]["success"])
            self.assertEqual(row["optimizer"], row["resolved"]["optimizer"])
            self.assertLessEqual(row["optimizer"]["iterations"], 1)
            self.assertTrue(row["math_passed"])
            self.assertTrue(row["resolved"]["candidate"]["axis_knot_contract"]["passed"])
            self.assertEqual(row["source_input"]["boundary_request"], before["rows"][0]["boundary_request"])
            self.assertGreater(row["counters"]["generation_calls"], 1)
            self.assertGreater(row["counters"]["metrics_calls"], 0)
            self.assertTrue(row["owned_process_exited"])
            self.assertGreaterEqual(row["wall_s"], row["resolved"]["offline_wall_s"])
        self.assertEqual(result["rows"][0]["counters"]["extrema_requests"], 0)
        self.assertGreater(result["rows"][1]["counters"]["extrema_requests"], 0)
        for backend in ("python", "rootfinder"):
            self.assertEqual(result["summary"][backend]["optimizer_success"], 0)
            self.assertEqual(result["summary"][backend]["math_passed"], 1)
        self.assertEqual(result["execution_admission"], "not_performed")


if __name__ == "__main__":
    unittest.main()
