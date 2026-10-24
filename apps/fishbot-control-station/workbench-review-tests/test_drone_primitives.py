# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Two focused exact-restriction fixtures, independent of saved flight records."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np
from numpy.polynomial import polynomial as poly
from scipy.interpolate import BSpline

spec = importlib.util.spec_from_file_location("drone_primitives", Path(__file__).parents[1] / "workbench-tools/drone-trajectory-primitives.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
curve, auditor = module.reuse(Path.home() / "dev/ros2/projects/drone")
LIMITS = {"speed": 1.8, "acceleration": 1., "ceiling": 2.2}


class PrimitiveTests(unittest.TestCase):
    def test_single_span_keeps_receipt_phase_and_nonzero_initial_pva(self):
        # x=t^3: at receipt t=.2, P/V/A must be .008/.12/1.2, not zero.
        record = {"order": 3, "knots": [0., 0., 0., 0., 1., 1., 1., 1.],
                  "control_points": [[0., 0., 1.], [0., 0., 1.], [0., 0., 1.], [1., 0., 1.]],
                  "start_sim_s": 100., "received_sim_s": 100.2, "task_id": None}
        result = module.restrict(record, .2, curve, auditor, LIMITS)
        np.testing.assert_allclose(result["initial_pvaj_xyz_columns"][0], [.008, .12, 1.2, 6.], atol=1e-12)
        self.assertEqual(len(result["pieces"]), 1)
        self.assertTrue(result["conversion"]["passed"])
        self.assertEqual(result["vaz_gate"]["failed_checks"], ["acceleration"])
        self.assertEqual(result["occupancy"]["status"], "unverified")
        self.assertEqual(result["task_attribution"], "unrecorded")

    def test_cross_knot_preserves_curve_and_real_jerk_jump(self):
        knots = [-3., -2., -1., 0., 1., 2., 3., 4., 5.]
        points = [[0., 0., 1.], [.1, .01, 1.], [.3, .01, 1.], [.31, -.01, 1.], [.6, 0., 1.]]
        record = {"order": 3, "knots": knots, "control_points": points,
                  "start_sim_s": 20., "received_sim_s": 20.75, "task_id": "original"}
        result = module.restrict(record, .8, curve, auditor, LIMITS)
        self.assertEqual(len(result["pieces"]), 2)
        self.assertTrue(result["conversion"]["passed"])
        self.assertGreater(result["conversion"]["source_jerk_jump_max_m_s3"], .1)
        source = BSpline(knots, points, 3, extrapolate=False)
        for piece in result["pieces"]:
            power = auditor.normalized_power(piece)
            for fraction in (0., .13, .5, .87):
                stamp = piece["source_parameter_start_s"]+fraction*piece["duration"]
                for order in range(4):
                    np.testing.assert_allclose(poly.polyval(fraction, auditor.derivative(power, piece["duration"], order)),
                                               source(stamp, nu=order), atol=1e-12)


if __name__ == "__main__":
    unittest.main()
