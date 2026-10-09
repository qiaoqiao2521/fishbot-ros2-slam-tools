"""Host C++ regressions. No ROS, network, serial, PlatformIO, or device access.

Run: python3 -B tools/tests/test_firmware_time_sync.py
Compiles the real policy, motor gate, and complete resource create/destroy functions.
Arduino primitives and resource API results use in-memory substitutes.
This does not establish ESP32 build success or board behavior.
"""

from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / "fishbot_motion_control_microros"


class FirmwareTimeSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="fishbot-time-sync-test-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        cls.binary = directory / "test-time-sync"
        source = (FIRMWARE / "src/fishbot.cpp").read_text()
        globals_and_gate = source.split("static portMUX_TYPE command_mux", 1)[1]
        globals_and_gate = "static portMUX_TYPE command_mux" + globals_and_gate.split(
            "/*==================MicroROS消息", 1)[0]
        motor_body = source.split("void loop_fishbot_control()", 1)[1].split(
            "void loop_fishbot_transport()", 1)[0]
        motor_gate = motor_body.split("// Only this task changes PID motion targets.", 1)[0]
        motor_gate = motor_gate.replace("float targets[2];", "float *targets = observed_targets;")
        display_call = re.search(r"display\.updateCurrentTime\([^;]+;", motor_body).group(0)
        (directory / "firmware_glue_under_test.h").write_text(
            "using portMUX_TYPE = int;\n"
            "#define portMUX_INITIALIZER_UNLOCKED 0\n"
            "#define portENTER_CRITICAL(mux) ((void)(mux))\n"
            "#define portEXIT_CRITICAL(mux) ((void)(mux))\n"
            "static uint32_t fake_millis = 0;\n"
            "static uint32_t millis() { return fake_millis; }\n"
            "static float observed_targets[2] = {0, 0};\n"
            "struct Display { int64_t stamp = 0; void updateCurrentTime(int64_t value) { stamp = value; } };\n"
            "static Display display;\n"
            + globals_and_gate
            + "\nvoid sample_motor_targets()" + motor_gate + display_call + "\n}\n"
        )
        release = "static bool release_init_options()" + source.split(
            "static bool release_init_options()", 1)[1].split("\nenum states", 1)[0]
        create_and_destroy = "bool create_fishbot_transport()" + source.split(
            "bool create_fishbot_transport()", 1)[1].split("void loop_fishbot_control()", 1)[0]
        (directory / "firmware_lifecycle_under_test.h").write_text(
            release + "\n" + create_and_destroy)
        subprocess.run([
            "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
            "-Wno-unused-function", "-pedantic", "-O1",
            "-fsanitize=undefined", "-fno-sanitize-recover=all",
            "-I", str(FIRMWARE / "include"), "-I", str(directory),
            str(Path(__file__).with_name("firmware_time_sync_test.cpp")),
            "-o", str(cls.binary),
        ], check=True, capture_output=True, text=True)

    def run_case(self, name):
        subprocess.run([str(self.binary), name], check=True, capture_output=True, text=True)

    def test_motor_task_never_reads_rmw_session(self):
        source = (FIRMWARE / "src/fishbot.cpp").read_text()
        motor_body = source.split("void loop_fishbot_control()", 1)[1].split(
            "void loop_fishbot_transport()", 1)[0]
        self.assertNotRegex(motor_body, r"\brmw_\w+\s*\(")

    def test_ping_is_only_used_while_waiting(self):
        source = (FIRMWARE / "src/fishbot.cpp").read_text()
        transport_body = source.split("void loop_fishbot_transport()", 1)[1]
        waiting = transport_body.split("case WAITING_AGENT:", 1)[1].split(
            "case AGENT_AVAILABLE:", 1)[0]
        connected = transport_body.split("case AGENT_CONNECTED:", 1)[1].split(
            "case AGENT_DISCONNECTED:", 1)[0]
        self.assertRegex(waiting, r"\brmw_uros_ping_agent\s*\(")
        self.assertNotRegex(connected, r"\brmw_uros_ping_agent(?:_options)?\s*\(")


for case in (
    "startup", "failure_does_not_renew", "invalid_epoch", "renewal",
    "native_stamps", "backward_sync", "reconnect", "rollover",
    "maintenance_budget", "connected_sync_heartbeat", "motor_lease", "command_watchdog",
    "backward_invalidates_motion",
    "display_snapshot",
    "reconnect_first_sync_timeout", "reconnect_after_last_success",
    "reconnect_success_renews", "reconnect_rollover", "reconnect_reset_preserves_stamp",
    "options_repeated_lifecycle", "options_failed_creation", "both_publishers_released",
    "entity_creation_failures", "support_partial_failure", "partial_cleanup_stops_motion",
):
    setattr(FirmwareTimeSyncTests, "test_" + case,
            lambda self, name=case: self.run_case(name))


if __name__ == "__main__":
    unittest.main(verbosity=2)
