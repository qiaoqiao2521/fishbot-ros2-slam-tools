# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Local geometry and clock contracts; synthetic fixtures are not flight evidence."""
import importlib.util
import math
import os
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(os.environ.get("DRONE_ROOT", Path.home() / "dev/ros2/projects/drone"))
sys.path.insert(0, str(ROOT))
from inspection_depth import sample_pixel
from ego.frames import rotate, CAMERA_ROTATION_XYZW

spec = importlib.util.spec_from_file_location("drone_sparse", Path(__file__).parents[1] / "workbench-tools/drone-sparse-observations.py")
sparse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sparse)


def image(value=4., big=False, padding=0):
    width, height = 640, 480
    row = struct.pack(">f" if big else "<f", value) * width + b"x" * padding
    return {"width": width, "height": height, "step": len(row), "data": row * height,
            "pixel_format": "R_FLOAT32", "byte_order": "big" if big else "little"}


CAL = {"fx": 432.496, "fy": 432.496, "cx": 320., "cy": 240., "width": 640, "height": 480, "near_m": .2, "far_m": 19.1}


class SparseTests(unittest.TestCase):
    def rays(self, img, stream="front", cal=CAL):
        return sparse.sample_rays(img, cal, stream, sample_pixel, rotate, CAMERA_ROTATION_XYZW)

    def test_slant_range_padded_big_endian_and_body_direction(self):
        rays = self.rays(image(big=True, padding=12))
        self.assertEqual(len(rays), 4)
        for ray in rays:
            u, v = ray["pixel"]
            expected = 4 * math.sqrt(1 + ((u-320)/432.496)**2 + ((v-240)/432.496)**2)
            self.assertAlmostEqual(ray["range_m"], expected)
            self.assertGreater(ray["range_m"], ray["depth_z_m"])
            self.assertGreater(ray["direction_body_flu"][0], 0)
            self.assertEqual(ray["direction_body_flu"][1] > 0, ray["requested_yaw_deg"] > 0)

    def test_no_return_invalid_and_unsupported_format_are_distinct(self):
        self.assertTrue(all(r["state"] == "no_return" and r["range_m"] is None for r in self.rays(image(math.inf))))
        for value in [math.nan, -math.inf, 0., -.1, .1]:
            self.assertTrue(all(r["state"] == "invalid" for r in self.rays(image(value))))
        bad = image(); bad["pixel_format"] = "16UC1"
        self.assertTrue(all(r["state"] == "invalid" for r in self.rays(bad)))

    def test_missing_calibration_and_size_mismatch_degrade(self):
        self.assertEqual(self.rays(image(), cal=None)[0]["reason"], "calibration_unavailable")
        self.assertEqual(self.rays(image(), cal={**CAL, "width": 320})[0]["reason"], "calibration_size_mismatch")
        self.assertIsNone(self.rays(image(math.inf), cal={**CAL, "far_m": None})[0]["display_range_m"])

    def test_world_ray_uses_recorded_optical_pose_and_extrinsics(self):
        obs = {"rays": self.rays(image())}
        pose = {"position": [1, 2, 3], "orientation": CAMERA_ROTATION_XYZW, "record_ns": 123, "frame": "world"}
        sparse.attach_pose(obs, pose, rotate)
        self.assertEqual(obs["origin_world"], [1, 2, 3])
        for ray in obs["rays"]:
            self.assertAlmostEqual(ray["endpoint_world"][0], 5.)
            self.assertAlmostEqual(ray["endpoint_world"][2], 3.)
        other = {"rays": self.rays(image())}
        sparse.attach_pose(other, {**pose, "frame": "unknown_camera_frame"}, rotate)
        self.assertNotIn("origin_world", other)

    def test_clock_bracket_does_not_mix_record_ns_and_source_seconds(self):
        clocks = [(1_000_000_000_000, 10_000_000_000, 0), (1_000_100_000_000, 10_004_000_000, 0)]
        self.assertEqual(sparse.clock_bracket(clocks, 1_000_050_000_000)["sim_s"], [10., 10.004])
        self.assertIn("reason", sparse.clock_bracket(clocks, 1))
        reset = [(10, 10_000_000_000, 0), (20, 0, 1)]
        self.assertEqual(sparse.clock_bracket(reset, 15)["reason"], "clock_reset_between_receipts")

    def test_fixed_rays_miss_a_thin_center_column_synthetic_negative(self):
        img = image(math.inf)
        data = bytearray(img["data"])
        # A narrow observed center strip is between all four fixed rays.
        for y in range(230, 250):
            for x in range(315, 326):
                struct.pack_into("<f", data, y * img["step"] + x*4, 4.7)
        img["data"] = data
        self.assertAlmostEqual(sample_pixel(img, [320, 240])["depth_m"], 4.7, places=5)
        self.assertTrue(all(ray["state"] == "no_return" for ray in self.rays(img)))


if __name__ == "__main__":
    unittest.main()
