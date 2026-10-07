"""Offline checks of real scan normalization and its publishing integration.

Run: python3 -B tools/tests/test_laser_scan_grid.py
No ROS imports, sockets, or hardware are used.
"""

import ast
import math
from pathlib import Path
import struct
from types import SimpleNamespace as NS
import unittest


ROOT = Path(__file__).resolve().parents[2]
PATHS = (ROOT / "tools/fishbot_laser_patch/ydlidar_node.py",
         ROOT / "fishbot_laser_ws/src/ydlidar_ros2/ydlidar/ydlidar_node.py")


def load_functions(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    normalize = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == "normalize_scan_grid")
    driver = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                  and node.name == "FishBotLaserDriverNode")
    callback = next(node for node in driver.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_handle_m1c1_scan")
    namespace = {"math": math}
    exec(compile(ast.Module(body=[normalize, callback], type_ignores=[]),
                 str(path), "exec"), namespace)
    return namespace["normalize_scan_grid"], namespace["_handle_m1c1_scan"]


def scan(ranges, angle_min=-math.pi, increment=math.pi / 360, intensities=None):
    return NS(ranges=list(ranges), intensities=list(intensities or []),
              angle_min=angle_min, angle_increment=increment,
              angle_max=angle_min + (len(ranges) - 1) * increment,
              range_min=0.05, range_max=8.0, scan_time=0.125, time_increment=0.0,
              header=NS(frame_id="laser_frame", stamp=NS(sec=123, nanosec=456)))


class Stamp:
    def __init__(self, nanoseconds):
        self.nanoseconds = nanoseconds

    def to_msg(self):
        return NS(sec=self.nanoseconds // 1_000_000_000,
                  nanosec=self.nanoseconds % 1_000_000_000)

    def __sub__(self, other):
        return Stamp(self.nanoseconds - other.nanoseconds)


class LaserScanGridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.drivers = [(path.relative_to(ROOT), *load_functions(path)) for path in PATHS]

    def assert_fixed_grid(self, message):
        self.assertEqual(len(message.ranges), 720)
        self.assertEqual(len(message.intensities), 720)
        self.assertAlmostEqual(message.angle_min, -math.pi)
        self.assertAlmostEqual(message.angle_increment, 2 * math.pi / 720)
        self.assertAlmostEqual(message.angle_max, math.pi - 2 * math.pi / 720)
        # LaserScan angle fields cross DDS as float32. Their span must still
        # describe the published readings after that loss of precision.
        wire = lambda value: struct.unpack("<f", struct.pack("<f", value))[0]
        span_steps = ((wire(message.angle_max) - wire(message.angle_min))
                      / wire(message.angle_increment))
        self.assertAlmostEqual(span_steps, len(message.ranges) - 1, places=3)

    def test_variable_input_counts_use_identical_grid_and_preserve_header_timing(self):
        for path, normalize, _ in self.drivers:
            for count in (716, 717, 718, 719, 720, 721):
                with self.subTest(driver=path, count=count):
                    message = scan([2.0] * count, angle_min=-math.pi + 0.002)
                    header = message.header
                    normalize(message)
                    self.assert_fixed_grid(message)
                    self.assertIs(message.header, header)
                    self.assertEqual((message.header.frame_id, message.header.stamp.sec,
                                      message.header.stamp.nanosec), ("laser_frame", 123, 456))
                    self.assertEqual(message.scan_time, 0.125)
                    self.assertEqual((message.range_min, message.range_max), (0.05, 8.0))

    def test_front_left_right_and_back_directions_do_not_rotate(self):
        for path, normalize, _ in self.drivers:
            with self.subTest(driver=path):
                message = scan([4.0, 3.0, 2.0, 1.0], increment=math.pi / 2)
                normalize(message)
                self.assertEqual([message.ranges[i] for i in (0, 180, 360, 540)],
                                 [4.0, 3.0, 2.0, 1.0])
                self.assertEqual(sum(math.isfinite(d) for d in message.ranges), 4)

    def test_negative_input_angle_increment_preserves_directions(self):
        for path, normalize, _ in self.drivers:
            with self.subTest(driver=path):
                message = scan([4.0, 3.0, 2.0, 1.0], angle_min=math.pi,
                               increment=-math.pi / 2)
                normalize(message)
                self.assertEqual([message.ranges[i] for i in (0, 180, 360, 540)],
                                 [4.0, 1.0, 2.0, 3.0])

    def test_pi_boundary_wraps_to_single_rear_bin(self):
        for path, normalize, _ in self.drivers:
            for start in (math.pi - math.radians(0.1), -math.pi - math.radians(0.1)):
                with self.subTest(driver=path, start=start):
                    message = scan([2.0, 0.7], angle_min=start,
                                   increment=math.radians(0.2))
                    normalize(message)
                    self.assertEqual(message.ranges[0], 0.7)
                    self.assertEqual(sum(math.isfinite(d) for d in message.ranges), 1)

    def test_duplicate_direction_keeps_nearer_echo_and_its_intensity(self):
        for path, normalize, _ in self.drivers:
            for distances, strengths in (([2.0, 0.4], [10.0, 90.0]),
                                         ([0.4, 2.0], [90.0, 10.0])):
                with self.subTest(driver=path, distances=distances):
                    message = scan(distances, angle_min=-math.radians(0.1),
                                   increment=math.radians(0.2), intensities=strengths)
                    normalize(message)
                    self.assertEqual(message.ranges[360], 0.4)
                    self.assertEqual(message.intensities[360], 90.0)
                    self.assertEqual(sum(math.isfinite(d) for d in message.ranges), 1)

    def test_invalid_ranges_never_create_echoes(self):
        for path, normalize, _ in self.drivers:
            with self.subTest(driver=path):
                message = scan([math.nan, math.inf, -math.inf, 0.0, 0.01, 9.0])
                normalize(message)
                self.assert_fixed_grid(message)
                self.assertTrue(all(d == math.inf for d in message.ranges))
                self.assertTrue(all(value == 0.0 for value in message.intensities))

    def test_range_boundaries_are_valid_and_missing_intensity_stays_zero(self):
        for path, normalize, _ in self.drivers:
            with self.subTest(driver=path):
                message = scan([0.05, 8.0], angle_min=0.0, increment=math.pi / 2,
                               intensities=[math.nan])
                normalize(message)
                self.assertEqual(message.ranges[360], 0.05)
                self.assertEqual(message.ranges[540], 8.0)
                self.assertTrue(all(value == 0.0 for value in message.intensities))

    def test_invalid_angle_metadata_does_not_manufacture_obstacles(self):
        for path, normalize, _ in self.drivers:
            for start, increment in ((math.nan, 0.01), (0.0, math.nan), (0.0, 0.0)):
                with self.subTest(driver=path, start=start, increment=increment):
                    message = scan([0.1] * 720, angle_min=start, increment=increment)
                    normalize(message)
                    self.assert_fixed_grid(message)
                    self.assertTrue(all(d == math.inf for d in message.ranges))

    def test_publishing_callback_normalizes_after_existing_reversal(self):
        for path, _, callback in self.drivers:
            for count in (716, 720):
                with self.subTest(driver=path, count=count):
                    messages = []
                    now = Stamp(1_000_000_000)
                    node = NS(rate=0.0, scan_count=0, last_report_count=0,
                              last_report_time=Stamp(0), publisher=NS(publish=messages.append),
                              get_clock=lambda: NS(now=lambda: now))
                    message = scan([math.inf] * count, intensities=[0.0] * count)
                    # Existing reversal puts this return at zero radians.
                    message.ranges[count - 1 - 360] = 0.8
                    message.intensities[count - 1 - 360] = 42.0
                    callback(node, message)
                    self.assertEqual(len(messages), 1)
                    self.assert_fixed_grid(messages[0])
                    self.assertEqual(messages[0].ranges[360], 0.8)
                    self.assertEqual(messages[0].intensities[360], 42.0)
                    self.assertAlmostEqual(messages[0].time_increment,
                                           messages[0].scan_time / 720)


if __name__ == "__main__":
    unittest.main(verbosity=2)
