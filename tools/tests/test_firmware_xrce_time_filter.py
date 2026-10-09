"""Offline C++ parser and real UDP transport logic tests with an in-memory UDP double.

No network, ROS, serial, SDK changes, or hardware operations.
Run: python3 -B tools/tests/test_firmware_xrce_time_filter.py
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / "fishbot_motion_control_microros"


class XrceTimeFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="fishbot-xrce-test-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        cls.binary = directory / "test-filter"
        source = (FIRMWARE / "lib/MicroRosRwm/micro_ros_transport_wifi_udp.cpp").read_text()
        (directory / "udp_transport_under_test.h").write_text(
            "extern \"C\"" + source.split('extern "C"', 1)[1])
        result = subprocess.run([
            "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1",
            "-Wno-unused-parameter", "-fsanitize=undefined", "-fno-sanitize-recover=all",
            "-I", str(FIRMWARE / "include"), "-I", str(FIRMWARE / "lib/MicroRosRwm"),
            "-I", str(directory), str(Path(__file__).with_name("firmware_xrce_time_filter_test.cpp")),
            "-o", str(cls.binary),
        ], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)

    def run_case(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


for case in ("layouts", "mismatches", "time_bounds", "windows_and_send", "mixed_atomic_rejection",
             "truncation_and_ordinary", "transport_zero_timeout", "transport_partial_and_oversize",
             "transport_drop_then_continue", "transport_reopen_and_failed_send",
             "hidden_replies_are_rejected", "ordinary_profile", "transport_success_and_partial_send",
             "captured_agent_info28"):
    setattr(XrceTimeFilterTests, "test_" + case, lambda self, name=case: self.run_case(name))

if __name__ == "__main__":
    unittest.main(verbosity=2)
