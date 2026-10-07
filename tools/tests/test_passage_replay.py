"""Synthetic-only offline replay tests. Never import ROS or private room scans."""

import copy
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


TOOLS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("passage_replay", TOOLS / "fishbot_passage_replay.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


def scan_with_points(*points, frame="laser_frame"):
    """A full background scan, with returns from isolated narrow obstacles."""
    scan = dict(frame_id=frame, angle_min=-math.pi, angle_increment=math.pi/360,
                range_min=0.01, range_max=10.0, ranges=[8.0]*720)
    for x, y in points:
        index = round((math.atan2(y, x)+math.pi)/scan["angle_increment"]) % 720
        scan["ranges"][index] = math.hypot(x, y)
    return scan


def corridor(half_width):
    scan = scan_with_points()
    for i in range(720):
        angle = scan["angle_min"] + i*scan["angle_increment"]
        distances = [8.0]
        if abs(math.sin(angle)) > 1e-10:
            distances.append(half_width/abs(math.sin(angle)))
        if abs(math.cos(angle)) > 1e-10:
            distances.append(3.0/abs(math.cos(angle)))
        scan["ranges"][i] = min(distances)
    return scan


class ReplayTests(unittest.TestCase):
    def test_import_and_snapshot_in_fresh_interpreter_do_not_load_ros(self):
        code = ("import runpy, sys; "
                "m = runpy.run_path(sys.argv[1]); "
                "case = m['ReplayTests'](); case.setUpClass(); "
                "case.evaluate(case.guard_snapshot()); "
                "assert 'rclpy' not in sys.modules")
        result = subprocess.run([sys.executable, '-c', code, __file__],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    @classmethod
    def setUpClass(cls):
        cls.geometry = replay.load_geometry(replay.DEFAULT_GEOMETRY)
        cls.parameters = replay.load_cm_parameters(replay.DEFAULT_CM_CONFIG, replay.DEFAULT_GEOMETRY)

    def evaluate(self, scan, **kwargs):
        return replay.evaluate_scan(scan, self.geometry, cm_parameters=self.parameters, **kwargs)

    def test_clear_corridor_is_only_observed_clear(self):
        report = self.evaluate(corridor(1.0))
        self.assertEqual(report["classification"], "clear_observed")
        self.assertEqual(report["physical_passability"], "not_established")

    def test_one_return_from_a_thin_leg_stops(self):
        report = self.evaluate(scan_with_points((0.08, 0)))
        self.assertEqual(report["classification"], "hard_current")
        self.assertEqual(len(report["zones"]["hard_current"]["hits"]), 1)

    def test_wall_intersects_vehicle(self):
        report = self.evaluate(corridor(0.08))
        self.assertEqual(report["classification"], "hard_current")

    def test_future_hit_is_distinct_from_current_hit(self):
        report = self.evaluate(scan_with_points((0.12, 0)), velocity_mps=0.08)
        self.assertFalse(report["zones"]["hard_current"]["hits"])
        self.assertTrue(report["zones"]["hard_straight"]["hits"])
        self.assertEqual(report["classification"], "hard_future")

    def test_obstacle_in_slow_zone_does_not_become_hard_hit(self):
        report = self.evaluate(scan_with_points((0.15, 0)), velocity_mps=0.0,
                               legacy_guard=(0.34, 0.18))
        self.assertFalse(report["zones"]["hard_current"]["hits"])
        self.assertFalse(report["zones"]["cm_hard"]["hits"])
        self.assertEqual(report["classification"], "slowdown")
        self.assertEqual(len(report["legacy_guard"]["hits"]), 1)

    def test_reverse_sweep_checks_rear_not_front(self):
        report = self.evaluate(scan_with_points((-0.12, 0)), velocity_mps=-0.08)
        self.assertEqual(report["classification"], "hard_future")
        forward = self.evaluate(scan_with_points((-0.12, 0)), velocity_mps=0.08)
        self.assertFalse(forward["zones"]["cm_hard"]["hits"])

    def test_heading_preview_accounts_for_rotated_body(self):
        scan = corridor(0.13)
        aligned = self.evaluate(scan, velocity_mps=0.08)
        angled = self.evaluate(scan, velocity_mps=0.08, heading_rad=math.radians(30))
        self.assertFalse(aligned["zones"]["cm_hard"]["hits"])
        self.assertTrue(angled["zones"]["cm_hard"]["hits"])
        self.assertFalse(angled["zones"]["hard_current"]["hits"])

    def test_missing_frame_requires_recorded_explicit_assumption(self):
        scan = scan_with_points()
        del scan["frame_id"]
        with self.assertRaisesRegex(ValueError, "frame"):
            self.evaluate(scan)
        report = self.evaluate(scan, assume_scan_frame="laser_frame")
        self.assertTrue(report["quality"]["frame_assumed"])

    def test_unknown_frame_cannot_be_overridden(self):
        with self.assertRaisesRegex(ValueError, "frame"):
            self.evaluate(scan_with_points(frame="camera"), assume_scan_frame="laser_frame")

    def test_frame_assumption_cannot_conflict_with_saved_frame(self):
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.evaluate(scan_with_points(), assume_scan_frame="base_footprint")

    def test_explicit_scan_to_base_transform_is_applied_once(self):
        geometry = copy.deepcopy(self.geometry)
        geometry["scan_to_base"] = dict(x_m=0.0, y_m=0.0, yaw_rad=math.pi)
        points, _ = replay.scan_points(scan_with_points((0.12, 0)), geometry)
        point = min(points, key=lambda p: math.hypot(p["x"], p["y"]))
        self.assertAlmostEqual(point["x"], -0.12)
        points, _ = replay.scan_points(scan_with_points((0.12, 0), frame="base_footprint"), geometry)
        self.assertAlmostEqual(min(points, key=lambda p: math.hypot(p["x"], p["y"]))["x"], 0.12)

    def test_negative_ranges_cannot_be_a_clearance_claim(self):
        scan = scan_with_points()
        scan["ranges"][20] = -1.0
        report = self.evaluate(scan)
        self.assertEqual(report["classification"], "unknown")
        self.assertEqual(report["quality"]["negative_returns"], 1)

    def test_empty_returns_are_unknown(self):
        scan = scan_with_points()
        scan["ranges"] = [None]*720
        self.assertEqual(self.evaluate(scan)["classification"], "unknown")

    def test_bad_metadata_rejected(self):
        for field, value in [("range_min", -0.1), ("range_max", 0.0),
                             ("angle_increment", 0.0), ("angle_min", math.nan)]:
            scan = scan_with_points()
            scan[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.evaluate(scan)

    def test_exact_boundary_is_hard_collision(self):
        report = self.evaluate(scan_with_points((0.105, 0)), velocity_mps=0.0)
        self.assertEqual(report["classification"], "hard_current")

    def test_same_padded_polygon_as_nav2(self):
        report = self.evaluate(scan_with_points())
        actual = report["zones"]["hard_current"]["polygon"]
        expected = json.loads(self.parameters["local_costmap"]["local_costmap"]["ros__parameters"]["footprint"])
        self.assertEqual([list(p) for p in actual], expected)

    def test_geometry_must_not_drop_single_points(self):
        geometry = copy.deepcopy(self.geometry)
        geometry["collision"]["min_points"] = 2
        with self.assertRaisesRegex(ValueError, "min_points"):
            replay.evaluate_scan(scan_with_points(), geometry)

    def test_cm_velocity_boundary_uses_first_inclusive_match(self):
        zones = replay.cm_polygons(self.parameters, self.geometry["motion"]["slow_linear_mps"])
        self.assertEqual(zones["cm_hard"]["selected_polygon"], "forward_slow_straight")

    def guard_snapshot(self):
        guard = replay.command_guard_module()
        geometry = copy.deepcopy(self.geometry)
        geometry["frames"]["base"] = "base_link"
        core = guard.CommandGuard(guard.Settings.from_mapping(geometry))
        transform = dict(translation=[0.08, 0.01, 0.4],
                         rotation=[0.0, math.sin(math.pi/4), 0.0, math.cos(math.pi/4)],
                         source_frame="laser_link", target_frame="base_link", stamp=100.0)
        core.accept_scan(scan_with_points((0.12, 0), frame="laser_link"), transform,
                         100.0, 100.01, 20.0)
        core.accept_command([0.03, 0, 0, 0, 0, 0.15], 100.0, 100.01, 20.0)
        core.zones["stop_polygon"] = dict(frame_id="base_link", source_stamp=99.95,
            points=[[-.13, -.13, 0], [.13, -.13, 0], [.13, .13, 0], [-.13, .13, 0]])
        return core.snapshot("synthetic CM transition", "collision", 100.02, 20.01)

    def test_guard_snapshot_uses_recorded_3d_tf_and_preserves_association(self):
        ros_was_loaded = "rclpy" in sys.modules
        event = self.guard_snapshot()
        report = self.evaluate(event)
        self.assertEqual(report["quality"]["projection"], "recorded_3d_tf_recomputed")
        self.assertTrue(report["quality"]["points_base_verified"])
        self.assertFalse(report["quality"]["frame_assumed"])
        self.assertEqual(report["quality"]["target_frame"], "base_link")
        projected = next(p for p in report["points"] if p["beam"] == 360)
        self.assertAlmostEqual(projected["x"], 0.08)
        self.assertAlmostEqual(projected["y"], 0.01)
        self.assertAlmostEqual(projected["z"], 0.28)
        self.assertEqual(report["velocity_mps"], .03)
        self.assertEqual(report["angular_velocity_rps"], .15)
        self.assertFalse(report["straight_sweeps_applicable"])
        self.assertEqual(report["zones"]["cm_hard"]["selected_polygon"], "forward_slow_left")
        self.assertEqual(report["collision_association"], event["collision_association"])
        self.assertEqual(report["collision_decision_reproduction"], "not_established")
        self.assertTrue(report["recorded_zones"]["stop_polygon"]["hits"])
        self.assertEqual("rclpy" in sys.modules, ros_was_loaded)

    def test_guard_snapshot_rejects_mismatched_tf_points_and_invalid_scan(self):
        for mutation in ("point", "target", "source", "error", "missing_tf", "quaternion"):
            event = self.guard_snapshot()
            record = event["latest"]["scan"]
            scan = record["data"]
            if mutation == "point":
                scan["points_base"][0]["x"] += .1
            elif mutation in ("target", "source"):
                scan["transform"][mutation+"_frame"] = "wrong_frame"
            elif mutation == "error":
                record["error"] = "scan TF unavailable"
            elif mutation == "quaternion":
                scan["transform"]["rotation"] = [0, 0, 0, 0]
            else:
                del scan["transform"]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.evaluate(event)

    def test_collision_stop_uses_saved_upstream_input_instead_of_zero_output(self):
        event = self.guard_snapshot()
        event["kind"] = "collision_stop"
        event["latest"]["desired_command"] = copy.deepcopy(event["latest"]["command"])
        event["latest"]["desired_command"]["data"]["twist"] = [.08, 0, 0, 0, 0, 0]
        event["latest"]["command"]["data"]["twist"] = [0]*6
        report = self.evaluate(event)
        self.assertEqual(report["velocity_source"], "saved_upstream_command_at_state_callback")
        self.assertEqual(report["velocity_mps"], .08)
        self.assertEqual(report["zones"]["cm_hard"]["selected_polygon"], "forward_straight")
        self.assertEqual(report["saved_command"]["data"]["twist"], [0]*6)
        self.assertEqual(report["saved_upstream_command"]["data"]["twist"][0], .08)
        self.assertEqual(report["collision_association"], event["collision_association"])
        override = self.evaluate(event, velocity_mps=.03)
        self.assertEqual(override["velocity_source"], "explicit_offline_scenario")
        del event["latest"]["desired_command"]
        fallback = self.evaluate(event)
        self.assertEqual(fallback["velocity_mps"], 0)
        self.assertEqual(fallback["velocity_source"], "saved_latest_command_not_time_synchronized_with_scan")

    def test_cli_synthetic_batch_records_unknown_and_visualization(self):
        ros_was_loaded = "rclpy" in sys.modules
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clear, bad = root/"clear.json", root/"bad.json"
            clear.write_text(json.dumps(scan_with_points()))
            bad.write_text(json.dumps(scan_with_points(frame="unknown")))
            output = root/"report"
            self.assertEqual(replay.main([str(clear), str(bad), "--output-dir", str(output)]), 0)
            summary = json.loads((output/"summary.json").read_text())
            self.assertEqual(summary["counts"], {"clear_observed": 1, "unknown": 1})
            self.assertTrue((output/"000-clear.svg").exists())
            self.assertEqual((output/"000-clear.json").stat().st_mode & 0o777, 0o600)
            evidence = json.loads((output/"000-clear.json").read_text())
            self.assertEqual(len(evidence["geometry_sha256"]), 64)
        self.assertEqual("rclpy" in sys.modules, ros_was_loaded)


if __name__ == "__main__":
    unittest.main()
