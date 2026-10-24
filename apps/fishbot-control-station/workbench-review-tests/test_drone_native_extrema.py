# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Analytic extrema fixtures qualify floating-point diagnostics, never flight."""
import copy
import importlib.util
import math
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

import numpy as np


HERE = Path(__file__).parent
TOOLS = HERE.parent/"workbench-tools"
BINARY = Path.home()/".cache/ros2-drone/minco-s4-metrics/minco_s4_metrics"
OLD_BINARY = Path.home()/".cache/ros2-drone/minco-s4-knots/minco_s4_knots"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NativeSession = load("extrema_native_session", TOOLS/"drone-native-session.py").NativeSession


def piece(duration=1., x=(), y=(), z=()):
    """Pad physical-time ascending coefficients to the native 3x8 contract."""
    return {"duration": duration, "coefficients_descending": [
        list(reversed(list(axis)+[0.]*(8-len(axis)))) for axis in (x, y, z)]}


@unittest.skipUnless(BINARY.exists(), "compiled offline MINCO extrema executable unavailable")
class NativeExtremaTests(unittest.TestCase):
    def extrema(self, pieces):
        with NativeSession(BINARY, timeout=2.) as session:
            result = session.exchange({"mode": "rootfinder_extrema", "pieces": pieces})
        self.assertTrue(result.get("native_success"), result)
        return result

    def test_zero_polynomial_is_finite_diagnostic_with_zero_rates(self):
        result = self.extrema([piece()])
        self.assertEqual(result["upper"], [0.]*3)
        self.assertEqual(result["lower"], [0.]*3)
        for key in ("acceleration_peak_m_s2", "velocity_peak_m_s", "minimum_y_velocity_m_s",
                "minimum_y_velocity_at_s", "reverse_y_speed_m_s"):
            self.assertEqual(result[key], 0.)
        row = result["piece_extrema"][0]
        self.assertEqual(row["acceleration_peak_at_s"], 0.)
        self.assertEqual(row["velocity_peak_at_s"], 0.)
        self.assertIn("floating-point", result["scope"])
        self.assertIn("independent final hard gate", result["scope"])
        self.assertEqual(result["execution_admission"], "not_performed")

    def test_constant_velocity_preserves_signed_y_and_has_zero_acceleration(self):
        for vy in (.4, -.4):
            with self.subTest(vy=vy):
                result = self.extrema([piece(2., x=[1., .3], y=[-2., vy], z=[3., -.5])])
                np.testing.assert_allclose(result["upper"], [1.6, max(-2., -2.+2.*vy), 3.], atol=1e-12)
                np.testing.assert_allclose(result["lower"], [1., min(-2., -2.+2.*vy), 2.], atol=1e-12)
                self.assertAlmostEqual(result["velocity_peak_m_s"], math.sqrt(.5), places=12)
                self.assertEqual(result["acceleration_peak_m_s2"], 0.)
                self.assertAlmostEqual(result["minimum_y_velocity_m_s"], vy, places=12)
                self.assertEqual(result["minimum_y_velocity_at_s"], 0.)
                self.assertAlmostEqual(result["reverse_y_speed_m_s"], max(0., -vy), places=12)

    def test_internal_reverse_velocity_and_position_extrema_have_analytic_times(self):
        # Vy=t^2-t+.05 is positive at both ends and reaches -.2 at t=.5.
        result = self.extrema([piece(y=[0., .05, -.5, 1./3.])])
        left = (1.-math.sqrt(.8))/2.
        right = (1.+math.sqrt(.8))/2.
        at = lambda t: t**3/3.-t*t/2.+.05*t
        self.assertAlmostEqual(result["upper"][1], at(left), places=11)
        self.assertAlmostEqual(result["lower"][1], at(right), places=11)
        self.assertAlmostEqual(result["minimum_y_velocity_m_s"], -.2, places=11)
        self.assertAlmostEqual(result["minimum_y_velocity_at_s"], .5, places=9)
        self.assertAlmostEqual(result["reverse_y_speed_m_s"], .2, places=11)
        self.assertAlmostEqual(result["velocity_peak_m_s"], .2, places=11)
        self.assertAlmostEqual(result["piece_extrema"][0]["velocity_peak_at_s"], .5, places=9)
        self.assertAlmostEqual(result["acceleration_peak_m_s2"], 1., places=11)

    def test_endpoint_stationary_roots_remain_bounded(self):
        # Vy=t(t-1) vanishes at both endpoints, with minimum -.25 at t=.5.
        result = self.extrema([piece(y=[0., 0., -.5, 1./3.])])
        np.testing.assert_allclose(result["upper"], [0., 0., 0.], atol=1e-12)
        np.testing.assert_allclose(result["lower"], [0., -1./6., 0.], atol=1e-12)
        self.assertAlmostEqual(result["minimum_y_velocity_m_s"], -.25, places=11)
        self.assertAlmostEqual(result["minimum_y_velocity_at_s"], .5, places=9)
        self.assertAlmostEqual(result["acceleration_peak_m_s2"], 1., places=11)

    def test_repeated_internal_roots_are_not_lost(self):
        # X=(t-.5)^4 and Y=(t-.5)^5/5 share repeated stationary roots.
        result = self.extrema([piece(x=[1./16., -.5, 1.5, -2., 1.],
            y=[-1./160., 1./16., -.25, .5, -.5, .2])])
        np.testing.assert_allclose(result["upper"], [1./16., 1./160., 0.], atol=1e-11)
        np.testing.assert_allclose(result["lower"], [0., -1./160., 0.], atol=1e-11)
        self.assertAlmostEqual(result["minimum_y_velocity_m_s"], 0., places=11)
        self.assertAlmostEqual(result["minimum_y_velocity_at_s"], .5, delta=1e-7)
        self.assertAlmostEqual(result["acceleration_peak_m_s2"], math.sqrt(9.25), places=10)
        self.assertAlmostEqual(result["velocity_peak_m_s"], math.sqrt(.25+1./256.), places=10)

    def test_three_axis_peaks_use_common_time_for_vector_norm(self):
        # Each position peaks at a different time: .25, .5, and .75 seconds.
        result = self.extrema([piece(x=[15./16., .5, -1.], y=[.75, 1., -1.],
            z=[7./16., 1.5, -1.])])
        np.testing.assert_allclose(result["upper"], [1., 1., 1.], atol=1e-11)
        np.testing.assert_allclose(result["lower"], [7./16., .75, 7./16.], atol=1e-11)
        self.assertAlmostEqual(result["velocity_peak_m_s"], math.sqrt(3.5), places=10)
        self.assertAlmostEqual(result["acceleration_peak_m_s2"], math.sqrt(12.), places=10)
        self.assertAlmostEqual(result["minimum_y_velocity_m_s"], -1., places=11)
        self.assertAlmostEqual(result["minimum_y_velocity_at_s"], 1., places=11)

    def test_piece_local_peak_times_and_global_minimum_include_elapsed_duration(self):
        result = self.extrema([piece(2., y=[0., .1]),
            piece(.5, y=[.2, -.75, -1., 4./3.])])
        self.assertEqual(len(result["piece_extrema"]), 2)
        row = result["piece_extrema"][1]
        self.assertAlmostEqual(row["minimum_y_velocity_m_s"], -1., places=11)
        self.assertAlmostEqual(row["minimum_y_velocity_at_s"], .25, places=9)
        self.assertAlmostEqual(row["velocity_peak_at_s"], .25, places=9)
        self.assertAlmostEqual(result["minimum_y_velocity_at_s"], 2.25, places=9)
        self.assertAlmostEqual(result["velocity_peak_m_s"], 1., places=11)
        self.assertAlmostEqual(result["acceleration_peak_m_s2"], 2., places=11)

    def test_nearly_coincident_short_pieces_keep_physical_rates_and_time_offsets(self):
        short = 1e-9
        tiny = 2e-9
        result = self.extrema([piece(1.), piece(short, y=[0., -1., -1./(2.*short)]),
            piece(tiny, y=[0., -2.75, -1./(2.*tiny), 1./(3.*tiny*tiny)])])
        self.assertAlmostEqual(result["minimum_y_velocity_m_s"], -3., places=10)
        self.assertAlmostEqual(result["minimum_y_velocity_at_s"], 1.+short+tiny/2., delta=1e-15)
        self.assertAlmostEqual(result["piece_extrema"][2]["minimum_y_velocity_at_s"], tiny/2., delta=1e-16)
        self.assertAlmostEqual(result["velocity_peak_m_s"], 3., places=10)
        self.assertAlmostEqual(result["acceleration_peak_m_s2"]/1e9, 1., places=10)

    def test_invalid_piece_error_does_not_poison_following_request(self):
        invalid = [[], [piece(0.)], [piece(-1.)], [{"coefficients_descending": [[0.]*8]*3}],
            [{"duration": 1., "coefficients_descending": [[0.]*8]*2}],
            [{"duration": 1., "coefficients_descending": [[0.]*7]*3}],
            [{"duration": 1., "coefficients_descending": [[0.]*8, [0.]*7, [0.]*8]}],
            [{"duration": 1., "coefficients_descending": [[None]*8]*3}],
            [piece(1e308, x=[0., 0., 0., 0., 0., 0., 0., 1e308])],
            [piece(x=[0., 1e200])]]
        with NativeSession(BINARY, timeout=2.) as session:
            pid = session.process.pid
            for pieces in invalid:
                with self.subTest(pieces=pieces):
                    response = session.exchange({"mode": "rootfinder_extrema", "pieces": pieces})
                    self.assertFalse(response.get("native_success", False), response)
                    good = session.exchange({"mode": "rootfinder_extrema", "pieces": [piece()]})
                    self.assertTrue(good.get("native_success"), good)
                    self.assertFalse(session.closed)
                    self.assertEqual(session.process.pid, pid)

    def test_short_duration_physical_acceleration_is_one_despite_official_zero(self):
        duration = 1e-6
        sample = piece(duration, x=[0., 0., 0., 1./(6.*duration)])
        with NativeSession(BINARY, timeout=.25) as session:
            official = session.exchange({"mode": "official_piece_rates", "rate": "acceleration", "pieces": [sample]})
        self.assertTrue(official.get("native_success"), official)
        self.assertEqual(official["piece_rates"][0]["acceleration_peak_m_s2"], 0.)
        result = self.extrema([sample])
        self.assertAlmostEqual(result["acceleration_peak_m_s2"], 1., places=11)
        self.assertAlmostEqual(result["piece_extrema"][0]["acceleration_peak_at_s"], duration, delta=1e-15)

    def test_official_degenerate_polynomial_times_out_and_owned_process_is_reaped(self):
        sample = piece(x=[0., 0., 0., 0., 0., 0., 0., 1e-5])
        with NativeSession(BINARY, timeout=.25) as official:
            with self.assertRaisesRegex(ValueError, "timeout"):
                official.exchange({"mode": "official_piece_rates", "rate": "acceleration", "pieces": [sample]})
            self.assertTrue(official.closed)
            self.assertIsNotNone(official.process.poll())
        result = self.extrema([sample])
        self.assertAlmostEqual(result["acceleration_peak_m_s2"], .00042, places=12)
        self.assertAlmostEqual(result["piece_extrema"][0]["acceleration_peak_at_s"], 1., places=11)

    @unittest.skipUnless(OLD_BINARY.exists(), "original offline MINCO executable unavailable")
    def test_default_axis_stop_generation_keeps_original_piece_coefficients(self):
        fixture = load("extrema_geometry_fixture", HERE/"test_drone_stop_geometry.py")
        request = fixture.module.geometry_request(
            fixture.boundary([2.5, 1., 1.5], [.5, .2, .01]), [4.5, 1., .4, .12, .5, .85], y_inner=True)
        with NativeSession(OLD_BINARY, timeout=2.) as old:
            expected = old.exchange(request)
        with NativeSession(BINARY, timeout=2.) as new:
            actual = new.exchange(request)
        self.assertTrue(expected.get("native_success"), expected)
        self.assertTrue(actual.get("native_success"), actual)
        self.assertEqual(actual["pieces"], expected["pieces"])
        self.assertEqual(actual["axis_piece_counts"], expected["axis_piece_counts"])
        self.assertEqual(actual["generator"], expected["generator"])


class ExtremaQualificationIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qualification = load("extrema_qualification_isolation", TOOLS/"drone-extrema-qualification.py")

    def successful_session(self, response=None):
        session = MagicMock()
        session.__enter__.return_value = session
        session.__exit__.return_value = False
        session.exchange.return_value = response if response is not None else {"native_success": True}
        session.process.poll.return_value = 0
        return session

    def test_constructor_and_close_failures_remain_local_to_the_probe_branch(self):
        for failed_phase in ("constructor", "close"):
            with self.subTest(failed_phase=failed_phase):
                sessions = [self.successful_session() for _ in range(4)]
                if failed_phase == "constructor":
                    sessions[0] = ValueError("constructor unavailable")
                    failed_label, failed_index = "official", 0
                else:
                    sessions[1].__exit__.side_effect = ValueError("native process exit=7")
                    failed_label, failed_index = "rootfinder", 1
                with patch.object(self.qualification.sessions, "NativeSession", side_effect=sessions) as factory:
                    rows = self.qualification.official_negatives(BINARY)
                self.assertEqual(factory.call_count, 4)
                self.assertEqual(rows[0][failed_label+"_status"], "unscored")
                self.assertIn(failed_label+"_error", rows[0])
                self.assertEqual(rows[1]["official_status"], "compared")
                self.assertEqual(rows[1]["rootfinder_status"], "compared")
                self.assertEqual(rows[0][failed_label+"_owned_process_exited"], None if failed_index == 0 else True)
                for session in sessions[failed_index+1:]:
                    session.exchange.assert_called_once()
                    session.__exit__.assert_called_once()

    def test_rootfinder_exchange_failure_does_not_block_next_analytical_probe(self):
        sessions = [self.successful_session() for _ in range(4)]
        sessions[1].exchange.side_effect = ValueError("rootfinder fixture exchange unavailable")
        with patch.object(self.qualification.sessions, "NativeSession", side_effect=sessions) as factory:
            rows = self.qualification.official_negatives(BINARY)
        self.assertEqual(factory.call_count, 4)
        self.assertEqual(rows[0]["official_status"], "compared")
        self.assertEqual(rows[0]["rootfinder_status"], "unscored")
        self.assertIn("exchange unavailable", rows[0]["rootfinder_error"])
        sessions[1].__exit__.assert_called_once()
        self.assertTrue(rows[0]["rootfinder_owned_process_exited"])
        self.assertEqual(rows[1]["official_status"], "compared")
        self.assertEqual(rows[1]["rootfinder_status"], "compared")

    def test_native_error_objects_remain_unscored_without_skipping_later_branches(self):
        error = {"native_success": False, "error": "diagnostic unavailable"}
        sessions = [self.successful_session(error), self.successful_session(error),
            self.successful_session(), self.successful_session()]
        with patch.object(self.qualification.sessions, "NativeSession", side_effect=sessions) as factory:
            rows = self.qualification.official_negatives(BINARY)
        self.assertEqual(factory.call_count, 4)
        for label in ("official", "rootfinder"):
            self.assertEqual(rows[0][label+"_status"], "unscored")
            self.assertEqual(rows[0][label+"_result"], error)
            self.assertTrue(rows[0][label+"_owned_process_exited"])
            self.assertEqual(rows[1][label+"_status"], "compared")

    @unittest.skipUnless(BINARY.exists(), "compiled offline MINCO extrema executable unavailable")
    def test_bad_archived_row_and_failed_probe_do_not_block_next_valid_curve(self):
        fixture = load("qualification_isolation_geometry_fixture", HERE/"test_drone_stop_geometry.py")
        request = fixture.module.geometry_request(
            fixture.boundary([2.5, 1., 1.5], [.5, .2, .01]), [4.5, 1., .4, .12, .5, .85], y_inner=True)
        with NativeSession(BINARY, timeout=2.) as session:
            candidate = fixture.module.tracking.audit_axis_request(request, fixture.BOX, fixture.LIMITS,
                BINARY, fixture.audit, exchange=session.exchange)
        self.assertEqual(candidate["status"], "audited")
        candidate["axis_knot_contract"] = fixture.module.audit_axis_knots(candidate["native"], request, fixture.audit)
        valid = {"variant_id": "valid", "profile": {"name": "zero_A_J"},
            "resolved": {"candidate": candidate}, "hard_limits": fixture.LIMITS, "hard_box": fixture.BOX}
        source = {"rows": [{"variant_id": "broken", "resolved": None}, valid]}
        before = copy.deepcopy(source)
        failed_probe = [{"official_status": "unscored", "rootfinder_status": "unscored"}]
        with patch.object(self.qualification, "official_negatives", return_value=failed_probe):
            result = self.qualification.run(source, fixture.ROOT, BINARY, repetitions=1)
        self.assertEqual(source, before)
        self.assertEqual(result["official_negative_probes"], failed_probe)
        self.assertEqual(result["rows"][0]["status"], "unscored")
        self.assertEqual(result["rows"][1]["status"], "compared")
        self.assertTrue(result["rows"][1]["comparison_passed"])
        self.assertTrue(result["rows"][1]["owned_process_exited"])
        self.assertEqual(result["summary"], {"rows": 2, "compared": 1, "comparison_passed": 1})
        self.assertEqual(len(result["warnings"]), 1)


if __name__ == "__main__":
    unittest.main()
