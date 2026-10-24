# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Offline observations must preserve solver inputs, results and hard gates."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np


HERE = Path(__file__).parent
TOOLS = HERE.parent/"workbench-tools"
BINARY = Path.home()/".cache/ros2-drone/minco-s4-metrics/minco_s4_metrics"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shared = load("trace_search_fixtures", HERE/"test_drone_extrema_search.py")
trace = load("extrema_trace", TOOLS/"drone-extrema-trace.py")
geometry = trace.geometry
NativeSession = trace.qualification.sessions.NativeSession
VALUES = [4.5, 1., .4, .12, .5, .85]


def native_fixture():
    return {"generator": "official_MINCO_S4NU_axis_inner_points", "axis_piece_counts": [1, 2, 1],
        "pieces": [{"duration": 1., "coefficients_descending": [[0.]*7+[p] for p in (2.5, 1., 1.5)]}]}


def event(values):
    x = values
    return {"kind": "evaluation", "values": list(x), "native": native_fixture(),
        "metrics": {"acceleration_peak_m_s2": 2*x[0]-3*x[1],
            "upper": [x[2], 4*x[3], -5*x[4]], "lower": [6*x[5], x[0]+x[5], -x[1]+2*x[2]]},
        "planning_margins": [1.]*6}


class SearchObserverTests(unittest.TestCase):
    def setUp(self):
        self.generated = []

    def audit_request(self, request, *args, **kwargs):
        result = {"status": "generated" if kwargs.get("perform_audit") is False else "audited",
            "request": request, "native": native_fixture(), "audit": {"passed": True, "failed_checks": []}}
        self.generated.append(result)
        return result

    def drive(self, objective, initial, **options):
        self.assertEqual(objective(np.asarray(VALUES)), .7)
        options["constraints"][0]["fun"](np.asarray(VALUES))
        if "callback" in options:
            options["callback"](np.asarray(VALUES))
        return SimpleNamespace(x=np.asarray(VALUES), jac=np.arange(6.)+10., success=False,
            status=9, message="fixture iteration cap", nfev=1, nit=1)

    def search(self, **options):
        return geometry.search(shared.boundary(), shared.fixture.BOX, shared.fixture.LIMITS,
            BINARY, shared.fixture.audit, y_inner=True, z_time_bounds=(.1, 1.2), max_iterations=1, **options)

    def test_none_observer_does_not_pass_callback_to_optimizer(self):
        with patch.object(geometry, "minimize", side_effect=self.drive) as minimize, \
                patch.object(geometry.tracking, "audit_axis_request", side_effect=self.audit_request), \
                patch.object(geometry, "extrema", return_value=shared.metrics()), \
                patch.object(geometry, "audit_axis_knots", return_value={"passed": True}):
            result = self.search(observer=None)
        self.assertNotIn("callback", minimize.call_args.kwargs)
        self.assertNotIn("jac", minimize.call_args.kwargs)
        self.assertEqual(len(minimize.call_args.kwargs["constraints"]), 1)
        self.assertEqual(result["status"], "audited")
        self.assertNotIn("observation_warnings", result)

    def test_explicit_three_point_is_forwarded_and_recorded(self):
        with patch.object(geometry, "minimize", side_effect=self.drive) as minimize, \
                patch.object(geometry.tracking, "audit_axis_request", side_effect=self.audit_request), \
                patch.object(geometry, "extrema", return_value=shared.metrics()), \
                patch.object(geometry, "audit_axis_knots", return_value={"passed": True}):
            result = self.search(derivative_method="3-point")
        self.assertEqual(minimize.call_args.kwargs["jac"], "3-point")
        self.assertEqual(len(minimize.call_args.kwargs["constraints"]), 1)
        self.assertEqual(result["optimizer"]["derivative_method"], "3-point")
        self.assertNotIn("acceleration_constraint_m_s2", result["optimizer"])

    def test_acceleration_constraint_uses_limit_and_joint_norm_without_extra_generation(self):
        limits = {**shared.fixture.LIMITS, "acceleration": 1.25}
        joint_metrics = {**shared.metrics(), "acceleration_peak_m_s2": 1.}

        def minimize(objective, initial, **options):
            point = np.asarray(VALUES)
            self.assertEqual(objective(point), 1.)
            self.assertEqual(len(options["constraints"]), 2)
            self.assertEqual(np.asarray(options["constraints"][0]["fun"](point)).shape, (6,))
            for _ in range(3):
                self.assertEqual(options["constraints"][1]["fun"](point), .25)
            self.assertEqual(len(self.generated), 1)
            return shared.optimizer()

        with patch.object(geometry, "minimize", side_effect=minimize), \
                patch.object(geometry.tracking, "audit_axis_request", side_effect=self.audit_request) as audited, \
                patch.object(geometry, "extrema", return_value=joint_metrics) as extrema, \
                patch.object(geometry, "audit_axis_knots", return_value={"passed": True}):
            result = geometry.search(shared.boundary(), shared.fixture.BOX, limits, BINARY, shared.fixture.audit,
                y_inner=True, z_time_bounds=(.1, 1.2), max_iterations=1, constrain_acceleration=True)
        self.assertEqual(audited.call_count, 2)
        extrema.assert_called_once()
        self.assertEqual(result["optimizer"]["acceleration_constraint_m_s2"], 1.25)
        self.assertNotIn("derivative_method", result["optimizer"])

    def test_invalid_acceleration_limit_is_unscored_before_optimizer_or_native_generation(self):
        for limit in (None, 0., -1., float("nan"), float("inf"), "invalid", "missing"):
            with self.subTest(limit=limit):
                limits = {**shared.fixture.LIMITS, "acceleration": limit}
                if limit == "missing":
                    limits.pop("acceleration")
                with patch.object(geometry, "minimize") as minimize, \
                        patch.object(geometry.tracking, "audit_axis_request") as generated:
                    result = geometry.search(shared.boundary(), shared.fixture.BOX, limits, BINARY,
                        shared.fixture.audit, y_inner=True, max_iterations=1, constrain_acceleration=True)
                self.assertEqual(result["status"], "unscored")
                self.assertTrue(result["reason"])
                minimize.assert_not_called()
                generated.assert_not_called()

    def test_observer_mutations_only_change_event_copies(self):
        events = []
        actual_metrics = shared.metrics()

        def mutate(observed):
            events.append(copy.deepcopy(observed))
            observed["values"][0] = 999.
            if observed["kind"] == "evaluation":
                observed["native"]["pieces"][0]["coefficients_descending"][0][-1] = 999.
                observed["metrics"]["acceleration_peak_m_s2"] = 999.
                observed["metrics"]["upper"][0] = 999.
                observed["planning_margins"][0] = 999.
            if observed["kind"] == "solver_exit":
                observed["reported_jac"][0] = 999.

        with patch.object(geometry, "minimize", side_effect=self.drive), \
                patch.object(geometry.tracking, "audit_axis_request", side_effect=self.audit_request), \
                patch.object(geometry, "extrema", return_value=actual_metrics), \
                patch.object(geometry, "audit_axis_knots", return_value={"passed": True}):
            result = self.search(observer=mutate)
        self.assertEqual(actual_metrics, shared.metrics())
        self.assertTrue(all(row["native"] == native_fixture() for row in self.generated))
        self.assertEqual(result["optimizer"]["values"], VALUES)
        self.assertEqual(result["diagnostics"]["acceleration_peak_m_s2"], .7)
        self.assertEqual(result["diagnostics"]["upper"], shared.metrics()["upper"])
        evaluations = [row for row in events if row["kind"] == "evaluation"]
        self.assertEqual(len(evaluations), 1)
        self.assertEqual(evaluations[0]["values"], VALUES)
        self.assertEqual(evaluations[0]["planning_margins"], result["optimizer"]["planning_margins_m"])
        iteration = next(row for row in events if row["kind"] == "iteration")
        self.assertEqual(set(iteration), {"kind", "values"})
        exit_event = next(row for row in events if row["kind"] == "solver_exit")
        self.assertEqual(exit_event["reported_jac"], [10., 11., 12., 13., 14., 15.])
        self.assertIn("not implied", exit_event["jac_scope"])

    def test_observer_exception_warns_and_original_final_gate_still_rejects(self):
        def audit(request, *args, **kwargs):
            result = self.audit_request(request, *args, **kwargs)
            if kwargs.get("perform_audit") is not False:
                result["audit"] = {"passed": False, "failed_checks": ["acceleration"]}
            return result

        def broken_observer(observed):
            raise RuntimeError("optional observer unavailable")

        with patch.object(geometry, "minimize", side_effect=self.drive), \
                patch.object(geometry.tracking, "audit_axis_request", side_effect=audit) as audited, \
                patch.object(geometry, "extrema", return_value=shared.metrics()), \
                patch.object(geometry, "audit_axis_knots", return_value={"passed": True}) as knots, \
                self.assertWarnsRegex(RuntimeWarning, "optional observer unavailable"):
            result = self.search(observer=broken_observer)
        self.assertEqual(audited.call_count, 2)
        knots.assert_called_once()
        self.assertEqual(result["status"], "audited")
        self.assertFalse(result["candidate"]["audit"]["passed"])
        self.assertEqual(result["candidate"]["audit"]["failed_checks"], ["acceleration"])
        self.assertTrue(result["observation_warnings"])
        self.assertTrue(all("optional observer unavailable" in message for message in result["observation_warnings"]))


class TraceAnalysisTests(unittest.TestCase):
    def first_stencil(self):
        head = [4.5, 1., .5, .125, .5, .875]
        steps = [2.**-20, -2.**-21, 2.**-22, -2.**-23, 2.**-24, -2.**-25]
        events = [event(head)]
        for axis, step in enumerate(steps):
            values = head.copy()
            values[axis] += step
            events.append(event(values))
        return events, steps

    def test_stencil_uses_actual_signed_steps_and_quantity_order(self):
        events, steps = self.first_stencil()
        before = copy.deepcopy(events)
        result = trace.stencil(events+[event([99.]*6)])
        self.assertEqual(events, before)
        self.assertEqual(result["status"], "observed")
        self.assertEqual(result["actual_steps"], steps)
        np.testing.assert_array_equal(result["quantity_jacobian"], [
            [2., -3., 0., 0., 0., 0.], [0., 0., 1., 0., 0., 0.],
            [0., 0., 0., 4., 0., 0.], [0., 0., 0., 0., -5., 0.],
            [0., 0., 0., 0., 0., 6.], [1., 0., 0., 0., 0., 1.],
            [0., -1., 2., 0., 0., 0.]])
        self.assertEqual(result["quantity_order"], ["acceleration_peak", "upper_x", "upper_y", "upper_z", "lower_x", "lower_y", "lower_z"])
        self.assertIn("not exact derivatives", result["scope"])

    def test_recorded_margin_jacobian_keeps_actual_direction_and_optional_missing_field(self):
        events, _ = self.first_stencil()
        for observed in events:
            x = observed["values"]
            observed["planning_margins"] = [x[0], -2*x[1], 3*x[2], -4*x[3], 5*x[4], -6*x[5]]
        result = trace.stencil(events)
        np.testing.assert_array_equal(result["actual_margin_jacobian"], np.diag([1., -2., 3., -4., 5., -6.]))
        del events[2]["planning_margins"]
        partial = trace.stencil(events)
        self.assertEqual(partial["status"], "observed")
        self.assertIsNone(partial["actual_margin_jacobian"])

    def test_incomplete_or_noncoordinate_stencil_is_unscored(self):
        events, _ = self.first_stencil()
        duplicate = copy.deepcopy(events)
        duplicate[2] = copy.deepcopy(duplicate[1])
        two_axes = copy.deepcopy(events)
        two_axes[1]["values"][1] += 2.**-20
        for malformed, reason in ((events[:6], "fewer_than_seven_unique_evaluations"),
                (duplicate, "not_a_six_axis_stencil"), (two_axes, "not_a_six_axis_stencil")):
            with self.subTest(reason=reason):
                result = trace.stencil(malformed)
                self.assertEqual(result["status"], "unscored")
                self.assertEqual(result["reason"], reason)

    def test_query_comparison_only_scores_exact_common_input_prefix(self):
        events, _ = self.first_stencil()
        left = copy.deepcopy(events[:3])
        right = copy.deepcopy(left)
        right[0]["metrics"]["acceleration_peak_m_s2"] += .125
        right[1]["metrics"]["upper"][1] += .25
        right[2]["values"][0] = float(np.nextafter(right[2]["values"][0], np.inf))
        right[2]["metrics"]["acceleration_peak_m_s2"] += 1e6
        result = trace.compare_queries(left, right)
        self.assertEqual(result["identical_input_prefix"], 2)
        self.assertEqual(result["common_prefix_maximum_quantity_difference"], .25)
        self.assertEqual(result["first_distinct_queries"], {"python": left[2]["values"], "rootfinder": right[2]["values"]})
        shortened = trace.compare_queries(left[:2], right)
        self.assertEqual(shortened["identical_input_prefix"], 2)
        self.assertIsNone(shortened["first_distinct_queries"]["python"])
        distinct = trace.compare_queries(left[2:], right[2:])
        self.assertEqual(distinct["identical_input_prefix"], 0)
        self.assertIsNone(distinct["common_prefix_maximum_quantity_difference"])

    def test_missing_or_ambiguous_source_does_not_start_native_process(self):
        original = shared.source()
        duplicate = copy.deepcopy(original)
        duplicate["rows"].append(copy.deepcopy(duplicate["rows"][0]))
        bad_profile = {"rows": [None, {"variant_id": "fixture", "profile": None}]}
        missing_boundary = {"rows": [{"variant_id": "fixture", "profile": {"name": "zero_A_J"}}]}
        for source, reason in (({"rows": []}, "one_variant_profile_required"),
                (duplicate, "one_variant_profile_required"), (None, "archive_rows_unavailable"),
                ({}, "archive_rows_unavailable"), ({"rows": None}, "archive_rows_unavailable"),
                (bad_profile, "one_variant_profile_required"),
                (missing_boundary, "archive_boundary_or_provenance_unavailable")):
            with self.subTest(source=source):
                with patch.object(trace.qualification.sessions, "NativeSession") as session:
                    result = trace.run(source, shared.fixture.ROOT, BINARY, variant_id="fixture", profile_name="zero_A_J", max_iterations=1)
                session.assert_not_called()
                self.assertEqual(result["status"], "unscored")
                self.assertEqual(result["reason"], reason)

    def test_paired_driver_and_cli_forward_explicit_derivative_and_acceleration_options(self):
        qualification = trace.qualification
        with patch.object(qualification.sessions, "NativeSession", side_effect=lambda *a, **k: shared.session_stub()), \
                patch.object(geometry, "search", return_value={"status": "unscored", "reason": "unit fixture"}) as search:
            result = qualification.run_search(shared.source(), shared.fixture.ROOT, BINARY, variant_id="fixture",
                profile_names=("zero_A_J",), repetitions=1, max_iterations=1,
                derivative_method="3-point", constrain_acceleration=True)
        self.assertEqual(search.call_count, 2)
        self.assertEqual(result["configuration"]["derivative_method"], "3-point")
        self.assertIs(result["configuration"]["constrain_acceleration"], True)
        for call in search.call_args_list:
            self.assertEqual(call.kwargs["derivative_method"], "3-point")
            self.assertIs(call.kwargs["constrain_acceleration"], True)
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory)/"source.json"
            source_path.write_text(json.dumps(shared.source()))
            argv = ["extrema-qualification", "--compare-search", "--reanchor-report", str(source_path),
                "--derivative-method", "3-point", "--constrain-acceleration", "--repetitions", "1",
                "--output", str(Path(directory)/"output.json")]
            with patch.object(sys, "argv", argv), \
                    patch.object(qualification, "run_search", return_value={"summary": {}}) as compare, \
                    patch.object(qualification, "run") as fixed_curve, patch("builtins.print"):
                qualification.main()
        fixed_curve.assert_not_called()
        self.assertEqual(compare.call_args.kwargs["derivative_method"], "3-point")
        self.assertIs(compare.call_args.kwargs["constrain_acceleration"], True)

    def test_fixed_curve_cli_warns_that_optimizer_options_are_not_applied(self):
        qualification = trace.qualification
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory)/"source.json"
            output_path = Path(directory)/"output.json"
            source_path.write_text("{}")
            argv = ["extrema-qualification", "--reanchor-report", str(source_path),
                "--derivative-method", "3-point", "--constrain-acceleration", "--output", str(output_path)]
            with patch.object(sys, "argv", argv), \
                    patch.object(qualification, "run", return_value={"summary": {}, "warnings": []}) as fixed, \
                    patch.object(qualification, "run_search") as search, patch("builtins.print") as printed:
                qualification.main()
            saved = json.loads(output_path.read_text())
        fixed.assert_called_once()
        search.assert_not_called()
        self.assertIn("not applied", saved["warnings"][0])
        self.assertTrue(any("WARNING:" in str(call) for call in printed.call_args_list))

    def test_shadow_runs_after_main_close_and_shadow_failure_is_local(self):
        original = shared.source()
        original["rows"][:0] = [None, {"variant_id": "fixture", "profile": None}]
        before = copy.deepcopy(original)
        sessions = []
        testcase = self

        class Session:
            def __init__(self, *args, **kwargs):
                testcase.assertTrue(all(item.closed for item in sessions))
                self.index = len(sessions)
                self.closed = False
                self.process = SimpleNamespace(poll=lambda: 0 if self.closed else None)
                sessions.append(self)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

            def close(self):
                self.closed = True

            def exchange(self, request):
                testcase.assertTrue(sessions[self.index-1].closed)
                testcase.assertEqual(request["mode"], "rootfinder_extrema")
                if self.index == 1:
                    raise ValueError("first shadow unavailable")
                return {"native_success": True, **shared.metrics()}

        def search(*args, **options):
            options["observer"]({"kind": "evaluation", "values": VALUES.copy(), "native": native_fixture(),
                "metrics": shared.metrics(), "planning_margins": [1.]*6})
            return {"status": "unscored", "reason": "search fixture"}

        with patch.object(trace.qualification.sessions, "NativeSession", Session), \
                patch.object(geometry, "search", side_effect=search), \
                patch.object(geometry, "extrema", return_value=shared.metrics()), \
                patch.object(trace, "piece_peaks", return_value=[]):
            result = trace.run(original, shared.fixture.ROOT, BINARY, variant_id="fixture", profile_name="zero_A_J", max_iterations=1)
        self.assertEqual(original, before)
        self.assertEqual(len(sessions), 4)
        self.assertTrue(all(session.closed for session in sessions))
        self.assertIn("first shadow unavailable", result["rows"][0]["events"][0]["shadow_error"])
        self.assertEqual(result["rows"][1]["maximum_same_coefficient_quantity_difference"], 0.)
        self.assertEqual(result["query_comparison"]["identical_input_prefix"], 1)
        self.assertIn("not a performance benchmark", result["scope"])


@unittest.skipUnless(BINARY.exists(), "compiled offline MINCO extrema executable unavailable")
class NativeObserverEquivalenceTests(unittest.TestCase):
    def test_one_iteration_observation_keeps_pieces_optimizer_and_audit_identical(self):
        base = shared.boundary()
        before = copy.deepcopy(base)
        events = []
        results = []
        for observer in (None, events.append):
            with NativeSession(BINARY, timeout=2.) as session:
                results.append(geometry.search(base, shared.fixture.BOX, shared.fixture.LIMITS, BINARY,
                    shared.fixture.audit, y_inner=True, z_time_bounds=(.1, 1.2), max_iterations=1,
                    exchange=session.exchange, observer=observer))
            self.assertTrue(session.closed)
            self.assertIsNotNone(session.process.poll())
        self.assertEqual(base, before)
        plain, observed = results
        self.assertEqual(plain["status"], "audited")
        self.assertEqual(observed["status"], "audited")
        self.assertEqual(plain["candidate"]["native"]["pieces"], observed["candidate"]["native"]["pieces"])
        self.assertEqual(plain["candidate"]["request"], observed["candidate"]["request"])
        self.assertEqual(plain["candidate"]["audit"], observed["candidate"]["audit"])
        self.assertEqual(plain["candidate"]["axis_knot_contract"], observed["candidate"]["axis_knot_contract"])
        self.assertEqual(plain["optimizer"], observed["optimizer"])
        self.assertFalse(observed["optimizer"]["success"])
        self.assertTrue(any(row["kind"] == "evaluation" for row in events))
        self.assertEqual(sum(row["kind"] == "solver_exit" for row in events), 1)


if __name__ == "__main__":
    unittest.main()
