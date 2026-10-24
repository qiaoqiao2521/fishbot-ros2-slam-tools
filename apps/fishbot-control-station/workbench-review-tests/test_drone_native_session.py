# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""A search may reuse native transport without reusing state or math results."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch


HERE = Path(__file__).parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


session_module = load("native_session", HERE.parent/"workbench-tools/drone-native-session.py")
fixture = load("native_session_geometry_fixture", HERE/"test_drone_stop_geometry.py")
reanchor_fixture = load("native_session_reanchor_fixture", HERE/"test_drone_handoff_reanchor.py")
NativeSession = session_module.NativeSession
geometry = fixture.module
NATIVE = Path.home()/".cache/ros2-drone/minco-s4-knots/minco_s4_knots"


def without_runtime(value):
    """Only elapsed durations vary between otherwise identical invocations."""
    if isinstance(value, dict):
        return {key: without_runtime(item) for key, item in value.items()
            if key not in ("elapsed_ms", "offline_wall_s")}
    if isinstance(value, list):
        return [without_runtime(item) for item in value]
    return value


def boundary():
    result = fixture.boundary([2.5, 1., 1.5], [.5, .2, .01])
    result["initial_jerk"] = [0., 0., 0.]
    return result


class NativeSessionProtocolTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.executable = Path(self.directory.name)/"native-fixture"
        self.executable.write_text(f"#!{sys.executable}\n"+"""
import json
import sys
import time

for line in sys.stdin:
    request = json.loads(line)
    mode = request.get("mode")
    if mode == "timeout":
        print("fixture reply stalled", file=sys.stderr, flush=True)
        time.sleep(30)
    elif mode == "eof":
        break
    elif mode == "bad_json":
        print("MincoResult {", flush=True)
    elif mode == "bad_type":
        print("MincoResult []", flush=True)
    elif mode == "bad_frame":
        print("UnexpectedResult {}", flush=True)
    elif mode == "reject":
        print('MincoResult {"native_success": false, "error": "bad fixture request"}', flush=True)
    elif mode == "success_then_exit":
        print('MincoResult {"native_success": true}', flush=True)
        sys.exit(7)
    elif mode == "partial":
        sys.stdout.write("MincoResult ")
        sys.stdout.flush()
        time.sleep(.02)
        print('{"native_success": true, "value": "partial"}', flush=True)
    else:
        print("MincoResult "+json.dumps({"native_success": True, "value": request.get("value")}), flush=True)
""")
        self.executable.chmod(0o700)

    def assert_closed_and_reaped(self, session):
        self.assertTrue(session.closed)
        self.assertIsNotNone(session.process.poll())
        self.assertTrue(session.process.stdin.closed)
        self.assertTrue(session.process.stdout.closed)
        with self.assertRaises(ValueError):
            session.exchange({"value": "after close"})

    def test_context_closes_only_its_owned_process(self):
        with NativeSession(self.executable) as peer:
            with NativeSession(self.executable) as session:
                self.assertNotEqual(session.process.pid, peer.process.pid)
                self.assertEqual(session.exchange({"value": "A"})["value"], "A")
                self.assertFalse(session.closed)
                self.assertIsNone(session.process.poll())
            self.assert_closed_and_reaped(session)
            self.assertEqual(peer.exchange({"value": "peer"})["value"], "peer")
            self.assertIsNone(peer.process.poll())
        self.assert_closed_and_reaped(peer)

    def test_error_response_consumes_one_reply_and_next_request_can_succeed(self):
        with NativeSession(self.executable) as session:
            pid = session.process.pid
            rejected = session.exchange({"mode": "reject"})
            self.assertIs(rejected["native_success"], False)
            self.assertFalse(session.closed)
            self.assertEqual(session.exchange({"value": "good"}), {"native_success": True, "value": "good"})
            self.assertEqual(session.process.pid, pid)
        self.assert_closed_and_reaped(session)

    def test_successful_reply_followed_by_nonzero_exit_is_not_successful_session(self):
        with self.assertRaisesRegex(ValueError, "exit=7"):
            with NativeSession(self.executable) as session:
                self.assertTrue(session.exchange({"mode": "success_then_exit"})["native_success"])
        self.assert_closed_and_reaped(session)

    def test_partial_reply_does_not_shift_next_request(self):
        with NativeSession(self.executable) as session:
            self.assertEqual(session.exchange({"mode":"partial"})["value"],"partial")
            self.assertEqual(session.exchange({"value":"next"})["value"],"next")
        self.assert_closed_and_reaped(session)

    def test_write_timeout_reaps_worker_that_never_reads_input(self):
        self.executable.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
        with NativeSession(self.executable,timeout=.2) as session:
            with self.assertRaisesRegex(ValueError,"request timeout"):
                session.exchange({"value":"x"*(1024*1024)})
            self.assert_closed_and_reaped(session)

    def test_body_error_is_not_replaced_by_nonzero_close_status(self):
        with self.assertRaisesRegex(RuntimeError,"original body failure"):
            with NativeSession(self.executable) as session:
                session.exchange({"mode":"success_then_exit"})
                raise RuntimeError("original body failure")
        self.assert_closed_and_reaped(session)

    def test_timeout_closes_and_reaps_own_process_without_stopping_peer(self):
        with NativeSession(self.executable) as peer:
            with NativeSession(self.executable, timeout=.2) as session:
                with self.assertRaisesRegex(ValueError, "timeout") as error:
                    session.exchange({"mode": "timeout"})
                self.assertIn("fixture reply stalled", str(error.exception))
                self.assert_closed_and_reaped(session)
            self.assertTrue(peer.exchange({"value": "still alive"})["native_success"])
            self.assertIsNone(peer.process.poll())

    def test_eof_closes_and_reaps_process(self):
        with NativeSession(self.executable) as session:
            with self.assertRaisesRegex(ValueError, "EOF"):
                session.exchange({"mode": "eof"})
            self.assert_closed_and_reaped(session)

    def test_bad_json_type_or_framing_closes_and_reaps_process(self):
        for mode in ("bad_json", "bad_type", "bad_frame"):
            with self.subTest(mode=mode):
                with NativeSession(self.executable) as session:
                    with self.assertRaises(ValueError):
                        session.exchange({"mode": mode})
                    self.assert_closed_and_reaped(session)

    def test_reanchor_timeout_is_local_and_every_search_closes_its_session(self):
        study = reanchor_fixture.study
        sessions = []
        original_load = study.load

        def make_session(executable):
            self.assertEqual(executable, NATIVE)
            self.assertTrue(all(session.closed for session in sessions))
            session = NativeSession(self.executable, timeout=.2)
            sessions.append(session)
            return session

        def load_with_fixture(name):
            if name == "drone-native-session":
                return SimpleNamespace(NativeSession=make_session)
            return original_load(name)

        def search(request, box, limits, executable, audit, **options):
            self.assertIs(options["exchange"].__self__, sessions[-1])
            if len(sessions) == 1:
                options["exchange"]({"mode": "timeout"})
                self.fail("timeout did not stop the current search")
            self.assertTrue(options["exchange"]({"value": len(sessions)})["native_success"])
            return {"status": "unscored", "reason": "later search ran"}

        with patch.object(study, "load", side_effect=load_with_fixture), \
                patch.object(study.geometry, "search", side_effect=search) as searched:
            result = study.run([reanchor_fixture.source_report()], [reanchor_fixture.anchor()], 1,
                fixture.ROOT, NATIVE, "fixture", max_iterations=1, reuse_native=True)
        self.assertEqual(searched.call_count, 4)
        self.assertEqual(len({session.process.pid for session in sessions}), 4)
        for session in sessions:
            self.assert_closed_and_reaped(session)
        self.assertIn("timeout", result["rows"][0]["reason"])
        self.assertTrue(all(row["resolved"]["reason"] == "later search ran" for row in result["rows"][1:]))
        self.assertEqual(result["summary"]["full_vehicle_handoffs_qualified"], 0)

    def test_reanchor_cli_opt_in_forwards_reuse_native_with_original_odometry(self):
        study = reanchor_fixture.study
        run_dir = Path(self.directory.name)
        candidate = run_dir/"candidate.json"
        candidate.write_text(json.dumps(reanchor_fixture.source_report()))
        (run_dir/"request.json").write_text(json.dumps({"id": "fixture"}))
        states = [reanchor_fixture.anchor()]
        argv = ["drone-handoff-reanchor", "--candidates", str(candidate), "--run-dir", str(run_dir),
            "--drone-root", str(fixture.ROOT), "--native", str(NATIVE), "--max-iterations", "1",
            "--reuse-native", "--output", str(run_dir/"out.json")]
        with patch.object(sys, "argv", argv), \
                patch.object(study.pv.tracking, "read_odometry", return_value=(states, {}, 1)) as read, \
                patch.object(study, "run", return_value={"summary": {}}) as run, patch("builtins.print"):
            study.main()
        read.assert_called_once_with(run_dir)
        self.assertEqual(run.call_args.args[1], states)
        self.assertEqual(run.call_args.kwargs, {"max_iterations": 1, "reuse_native": True})


@unittest.skipUnless(NATIVE.exists(), "existing offline MINCO S4 inner-point executable unavailable")
class NativeSessionEquivalenceTests(unittest.TestCase):
    def request_pair(self):
        a = geometry.geometry_request(boundary(), [4.5, 1., .4, .12, .5, .85], y_inner=True)
        b_base = copy.deepcopy(boundary())
        b_base["initial_pva"][0][2] = .01
        b_base["initial_pva"][1][2] = .02
        b_base["initial_jerk"] = [.02, -.04, .01]
        b = geometry.geometry_request(b_base, [4.8, 1.2, .6, .15, .6, .4], y_inner=True)
        return a, b

    def test_a_b_a_matches_oneshot_coefficients_and_complete_audit(self):
        a, b = self.request_pair()
        requests = [a, b, a]
        before = copy.deepcopy(requests)
        expected = [geometry.tracking.audit_axis_request(request, fixture.BOX, fixture.LIMITS,
            NATIVE, fixture.audit) for request in requests]
        with NativeSession(NATIVE) as session:
            actual = [geometry.tracking.audit_axis_request(request, fixture.BOX, fixture.LIMITS,
                NATIVE, fixture.audit, exchange=session.exchange) for request in requests]
            self.assertFalse(session.closed)
            self.assertIsNone(session.process.poll())
        self.assertEqual(requests, before)
        self.assertEqual([single["audit"]["passed"] for single in expected], [True, False, True])
        for single, reused in zip(expected, actual):
            self.assertEqual(single["status"], "audited")
            self.assertEqual(without_runtime(single), without_runtime(reused))
        self.assertEqual(actual[0]["native"]["pieces"], actual[2]["native"]["pieces"])
        self.assertNotEqual(actual[0]["native"]["pieces"], actual[1]["native"]["pieces"])
        self.assertTrue(session.closed)
        self.assertIsNotNone(session.process.poll())

    def test_native_invalid_request_does_not_prevent_following_valid_request(self):
        request, _ = self.request_pair()
        with NativeSession(NATIVE) as session:
            pid = session.process.pid
            self.assertFalse(session.exchange({"mode": "axis_stop"}).get("native_success", False))
            self.assertFalse(session.closed)
            good = session.exchange(request)
            self.assertTrue(good["native_success"])
            self.assertEqual(session.process.pid, pid)
            self.assertTrue(fixture.audit.audit_trajectory(good, request, [], fixture.LIMITS, fixture.BOX)["passed"])

    def test_one_iteration_search_is_equivalent_and_exchange_does_not_leak_to_next_search(self):
        options = {"y_inner": True, "z_time_bounds": (.1, 1.2), "max_iterations": 1}
        base = boundary()
        original_run = geometry.tracking.subprocess.run
        with NativeSession(NATIVE) as session:
            with patch.object(geometry.tracking.subprocess, "run", wraps=original_run) as oneshot:
                reused = geometry.search(base, fixture.BOX, fixture.LIMITS, NATIVE,
                    fixture.audit, exchange=session.exchange, **options)
                oneshot.assert_not_called()
                single = geometry.search(base, fixture.BOX, fixture.LIMITS, NATIVE, fixture.audit, **options)
                self.assertGreater(oneshot.call_count, 0)
            self.assertIsNone(session.process.poll())
            self.assertFalse(session.closed)
        self.assertEqual(reused["status"], "audited")
        self.assertTrue(reused["candidate"]["axis_knot_contract"]["passed"])
        self.assertLessEqual(reused["optimizer"]["iterations"], 1)
        self.assertEqual(without_runtime(reused), without_runtime(single))
        self.assertEqual(reused["execution_admission"], "not_performed")


if __name__ == "__main__":
    unittest.main()
