# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Native MINCO comparison with source PVAJ and explicit non-admission."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np

TOOLS = Path(__file__).parents[1] / "workbench-tools"
def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

primitives = load("drone-trajectory-primitives")
candidates = load("drone-stop-candidates")
ROOT = Path.home() / "dev/ros2/projects/drone"
curve, audit = primitives.reuse(ROOT)
_, handoff = candidates.load_modules(ROOT)
NATIVE = Path.home() / ".cache/ros2-drone/minco-probe/minco_probe"
LIMITS = {"speed": 1.8, "acceleration": 1., "ceiling": 2.2, "local_target_tolerance": .3}

def window(scale=.05):
    return primitives.restrict({"order": 3, "knots": [0.,0.,0.,0.,1.,1.,1.,1.],
        "control_points": [[0.,0.,1.5],[0.,0.,1.5],[0.,0.,1.5],[scale,0.,1.5]],
        "start_sim_s": 10., "received_sim_s": 10., "task_id": "fixture", "trajectory_id": 1},
        .8, curve, audit, LIMITS)

class StopTests(unittest.TestCase):
    def compare(self, row, native=NATIVE):
        return candidates.compare(row, LIMITS, [3.5,1.,.4], native, audit, handoff)

    def test_native_tail_preserves_nonzero_reference_jerk_and_stops(self):
        row = self.compare(window())
        self.assertEqual(row["status"], "generated")
        self.assertTrue(row["full_math_gate"]["passed"])
        self.assertTrue(row["tail_math_gate"]["passed"])
        self.assertLess(max(row["cut_pvaj_error"]), 1e-8)
        np.testing.assert_allclose(row["request"]["initial_jerk"], [.3,0.,0.], atol=1e-12)
        self.assertEqual(row["full_continuity_claim"], "C2")
        self.assertEqual(row["occupancy"]["status"], "unverified")
        self.assertEqual(row["execution_admission"], "not_performed")

    def test_original_acceleration_gate_rejects_without_changing_input(self):
        source = window(1.)
        row = self.compare(source)
        self.assertFalse(row["full_math_gate"]["passed"])
        self.assertIn("acceleration", row["full_math_gate"]["failed_checks"])
        np.testing.assert_allclose(row["request"]["initial_pva"], np.asarray(source["terminal_pvaj_xyz_columns"])[:,:3])
        self.assertTrue(row["cut_c3_passed"])

    def test_missing_identity_or_native_does_not_fabricate_candidate(self):
        row = self.compare({**window(), "task_attribution": "unrecorded"})
        self.assertEqual(row["status"], "unscored")
        self.assertNotIn("preview_points", row)
        row = self.compare(window(), Path('/nonexistent-drone-minco'))
        self.assertEqual(row["status"], "generation_failed")
        self.assertNotIn("preview_points", row)

if __name__ == "__main__":
    unittest.main()
