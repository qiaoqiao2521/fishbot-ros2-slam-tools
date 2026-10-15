"""Offline regression checks for intent safety and gateway-only ROS forwarding."""
import contextlib
import http.client
import io
import json
import math
import sys
import threading
import types
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, mock_open, patch
from urllib import error

from tools.fishbot_edge_voice_node import (
    DEFAULT_GATEWAY_URL, EdgeHardwareDetector, EdgeVoiceIntentParser,
    FillerWordFilter, VoiceGatewayClient, main, parse_voice_envelope,
    validate_gateway_url, validate_voice_envelope,
)


class TestEdgeVoicePerception(unittest.TestCase):
    def accepted(self, phrase, intent):
        result = EdgeVoiceIntentParser.parse(phrase)
        self.assertTrue(result["accepted"], (phrase, result))
        self.assertEqual(result["intent"], intent, phrase)
        self.assertEqual(result["linear_x"], 0.0)
        self.assertEqual(result["angular_z"], 0.0)
        self.assertNotIn("duration", result)
        self.assertEqual(result["reason"], "accepted")
        return result

    def rejected(self, phrase, reason=None):
        result = EdgeVoiceIntentParser.parse(phrase)
        self.assertFalse(result["accepted"], (phrase, result))
        self.assertEqual(result["intent"], "UNKNOWN")
        self.assertEqual(result["parameters"], {})
        self.assertEqual((result["linear_x"], result["angular_z"]), (0.0, 0.0))
        if reason:
            self.assertEqual(result["reason"], reason, phrase)
        return result

    def test_original_three_regressions(self):
        self.rejected("不要前进", "negated_command")
        self.accepted("往后走", "BACKWARD")
        self.accepted("前进，马上停下", "STOP")

    def test_parse_contract_is_stable(self):
        result = self.accepted("前进", "FORWARD")
        self.assertEqual(set(result), {"raw", "cleaned", "dropped_fillers", "intent", "accepted",
                                      "reason", "parameters", "linear_x", "angular_z"})
        self.assertEqual(result["raw"], "前进")

    def test_hardware_flags_distinguish_scalar_and_vector(self):
        for feature, scalar, vector in (("fphp", True, False), ("asimdhp", False, True),
                                        ("fphp asimdhp asimd", True, True), ("fphpfake", False, False)):
            with self.subTest(feature=feature), patch("builtins.open", mock_open(read_data="CPU implementer: 0x41\nFeatures: " + feature)):
                caps = EdgeHardwareDetector.detect_capabilities()
                self.assertTrue(caps["is_arm64"])
                self.assertEqual(caps["has_arm_fp16_scalar"], scalar)
                self.assertEqual(caps["has_arm_fp16_vector"], vector)
                self.assertEqual(caps["has_arm_fp16"], scalar or vector)
        with patch("builtins.open", side_effect=OSError("unavailable")):
            self.assertFalse(any(EdgeHardwareDetector.detect_capabilities().values()))

    def test_hardware_detection_uses_flags_not_prose(self):
        with patch("builtins.open", mock_open(read_data="model name: avx2fake fphp\nflags: avx2\n")):
            caps = EdgeHardwareDetector.detect_capabilities()
            self.assertTrue(caps["has_x86_avx2"])
            self.assertFalse(caps["has_arm_fp16"])

    def test_fillers_only_clean_text_edges(self):
        cleaned, removed = FillerWordFilter.clean("呃那个……小车前进")
        self.assertEqual(cleaned, "小车前进")
        self.assertEqual(removed, ["呃", "那个"])
        self.assertEqual(FillerWordFilter.clean("um please go forward"), ("please go forward", ["um"]))
        for phrase in ("前进然后左转", "前进那个地方", "I like forward", "前进 um 左转", "you know stop"):
            with self.subTest(phrase=phrase):
                self.assertEqual(FillerWordFilter.clean(phrase), (phrase, []))
        self.assertEqual(FillerWordFilter.clean("前进嗯"), ("前进", ["嗯"]))

    def test_simple_commands_and_defaults(self):
        cases = {"呃那个……小车前进": "FORWARD", "走": "FORWARD", "往前走": "FORWARD",
                 "向前移动": "FORWARD", "倒车": "BACKWARD", "向后走": "BACKWARD",
                 "向左转弯": "TURN_LEFT", "往右转": "TURN_RIGHT",
                 "um please go forward": "FORWARD", "go backward": "BACKWARD",
                 "go back": "BACKWARD", "turn left": "TURN_LEFT", "RIGHT": "TURN_RIGHT"}
        for phrase, intent in cases.items():
            with self.subTest(phrase=phrase):
                self.accepted(phrase, intent)
        self.assertEqual(self.accepted("前进", "FORWARD")["parameters"], {"distance_m": .4})
        self.assertEqual(self.accepted("后退", "BACKWARD")["parameters"], {"distance_m": .3})
        self.assertEqual(self.accepted("左转", "TURN_LEFT")["parameters"], {"angle_rad": math.pi / 2})
        self.assertEqual(self.accepted("右转", "TURN_RIGHT")["parameters"], {"angle_rad": -math.pi / 2})

    def test_negations_never_become_motion_or_stop(self):
        phrases = ("不要前进", "别走", "不要左转", "禁止倒车", "不许向右转", "不用前进",
                   "不能前进", "不要再继续向前走", "不要停下", "不停下", "请不要急着停下",
                   "不要，停下", "don't stop", "do not suddenly stop", "don't turn left",
                   "never go forward", "no forward", "do not go back", "not right",
                   "前进，不要停下", "不要停下，然后前进", "不要前进然后左转",
                   "不要前进和停止", "do not go forward and stop", "不要前进停止")
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.rejected(phrase, "negated_command")

    def test_positive_stop_wins_over_other_actions(self):
        for phrase in ("前进马上停下", "左转，停止", "不要前进，停下", "前进后退停止",
                       "前进100米，停止", "forward then stop", "don't turn left then stop",
                       "快停下", "别动", "不许动", "不要动", "halt", "紧急停止"):
            with self.subTest(phrase=phrase):
                self.assertEqual(self.accepted(phrase, "STOP")["parameters"], {})

    def test_mixed_and_repeated_non_stop_actions_are_rejected(self):
        for phrase in ("前进然后左转", "先后退再前进", "前进前进", "左转和右转", "回家然后回充",
                       "transport and forward", "go forward and go back", "装货运输然后前进"):
            with self.subTest(phrase=phrase):
                self.rejected(phrase, "multiple_actions")

    def test_english_keywords_require_word_boundaries(self):
        for phrase in ("forwarding", "backwardness", "leftover", "bright", "stopwatch", "homeless", "homework", "docking", "transportation"):
            with self.subTest(phrase=phrase):
                self.rejected(phrase, "unknown_intent")

    def test_distance_units_and_chinese_numbers(self):
        for phrase, expected in (("前进半米", .5), ("后退二十厘米", .2), ("前进五厘米", .05),
                                 ("前进一米", 1.0), ("前进零点五米", .5), ("后退0.05米", .05),
                                 ("前进４０厘米", .4), ("forward 30 cm", .3), ("backward .5 m", .5)):
            with self.subTest(phrase=phrase):
                self.assertAlmostEqual(self.accepted(phrase, "BACKWARD" if phrase.startswith(("后退", "backward")) else "FORWARD")["parameters"]["distance_m"], expected)

    def test_angles_use_sign_and_bounds(self):
        for phrase, degrees in (("左转九十度", 90), ("右转四十五度", -45), ("左转一百八十度", 180),
                                ("左转一百零八度", 108), ("右转三十点五度", -30.5),
                                ("turn right 180 degrees", -180), ("左转0.5度", .5)):
            with self.subTest(phrase=phrase):
                result = self.accepted(phrase, "TURN_RIGHT" if degrees < 0 else "TURN_LEFT")
                self.assertAlmostEqual(result["parameters"]["angle_rad"], math.radians(degrees))

    def test_invalid_quantities_are_not_clamped_or_ignored(self):
        for phrase in ("前进0米", "后退负一米", "前进-0.4米", "后退4厘米", "前进1.01米", "前进两米",
                       "前进100米", "前进1米20厘米", "前进1e-1米", "前进NaN米", "前进inf米",
                       "前进0,4米", "前进三点米", "前进90度", "左转1米", "左转0度", "右转-90度", "左转一百二度",
                       "左转181度", "左转三百六十度", "左转90度45度", "回充2米", "前进3", "前进米"):
            with self.subTest(phrase=phrase):
                self.rejected(phrase)

    def test_dock_return_home_and_transport_are_separate(self):
        for phrase in ("回充", "回家充电", "返回充电", "去充电桩", "前往充电站", "dock", "recharge", "return to dock"):
            with self.subTest(phrase=phrase):
                self.accepted(phrase, "DOCK")
        for phrase in ("返航", "回家", "返回起点", "返回出发点", "return home", "home", "go home"):
            with self.subTest(phrase=phrase):
                self.accepted(phrase, "RETURN_HOME")
        for phrase in ("装货运输", "装货并运输", "装货然后运输", "运输", "搬运货物", "装货", "transport", "load and transport"):
            with self.subTest(phrase=phrase):
                self.accepted(phrase, "TRANSPORT")

    def test_goto_requires_explicit_name_and_never_accepts_coordinates(self):
        for phrase, place in (("前往厨房", "厨房"), ("去A1工位", "A1工位"), ("到客厅", "客厅"),
                              ("go to kitchen", "kitchen"), ("前往1号工位", "1号工位"),
                              ("去停车场", "停车场"), ("去停止线", "停止线")):
            with self.subTest(phrase=phrase):
                self.assertEqual(self.accepted(phrase, "GOTO")["parameters"], {"place": place})
        for phrase in ("厨房", "去", "去1.0,2.0", "去123", "去x=1 y=2", "去厨房然后前进", "去厨房并且左转",
                       "go to kitchen and left", "前往" + "甲" * 33, "不要去厨房"):
            with self.subTest(phrase=phrase):
                self.rejected(phrase)

    def test_empty_invalid_and_overlong_inputs(self):
        for phrase in ("", " \n\t", "嗯啊", "……", None, 4, ["前进"], "前进\x00", "前进\x1b", "停下\u200b", "停下\ud800"):
            with self.subTest(phrase=phrase):
                self.rejected(phrase)
        self.rejected("前进" + " " * EdgeVoiceIntentParser.MAX_TEXT_LENGTH, "text_too_long")
        self.rejected("停止" + " " * EdgeVoiceIntentParser.MAX_TEXT_LENGTH, "text_too_long")
        self.rejected("我觉得前进很危险", "unsupported_text")


def envelope():
    return {"command_id": str(uuid.uuid4()), "session_id": "voice-session-1", "sequence": 0,
            "issued_at_ms": 1, "ttl_ms": 5000, "text": "前进", "asr_id": "recognition-1"}


class TestVoiceEnvelope(unittest.TestCase):
    def test_envelope_is_preserved_without_timestamp_refresh(self):
        original = envelope()
        validated = parse_voice_envelope(json.dumps(original))
        self.assertEqual(validated, original)
        self.assertEqual(validated["issued_at_ms"], 1)
        self.assertIsNot(validated, original)

    def test_legacy_text_and_malformed_json_are_rejected(self):
        for raw in ("前进", '"前进"', "{}", "[]", "null", "{", " ", "x" * 8193):
            with self.subTest(raw=raw[:20]), self.assertRaises(ValueError):
                parse_voice_envelope(raw)
        original = json.dumps(envelope())
        with self.assertRaisesRegex(ValueError, "duplicate_envelope_key"):
            parse_voice_envelope(original[:-1] + ', "text":"后退"}')

    def test_invalid_identity_and_numeric_types_are_rejected(self):
        cases = (("command_id", "not-a-uuid"), ("command_id", 1), ("session_id", ""),
                 ("session_id", "session with spaces"), ("sequence", True), ("sequence", -1),
                 ("sequence", 1.0), ("issued_at_ms", 0), ("issued_at_ms", "1"),
                 ("ttl_ms", False), ("ttl_ms", -1), ("asr_id", ""), ("text", " "),
                 ("text", 1), ("text", "x" * 257), ("text", "前进\x00"), ("text", "停下\ud800"))
        for name, value in cases:
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                validate_voice_envelope(dict(envelope(), **{name: value}))
        with self.assertRaises(ValueError):
            validate_voice_envelope(dict(envelope(), linear_x=.2))
        for name in envelope():
            if name == "asr_id":
                continue
            invalid = envelope()
            del invalid[name]
            with self.subTest(missing=name), self.assertRaises(ValueError):
                validate_voice_envelope(invalid)

    def test_gateway_url_is_literal_loopback_and_fixed_path(self):
        for url in (DEFAULT_GATEWAY_URL, "http://[::1]:9094/voice-api/execute"):
            self.assertEqual(validate_gateway_url(url), url)
        for url in ("http://localhost:9094/voice-api/execute", "http://192.168.1.2:9094/voice-api/execute",
                    "https://127.0.0.1:9094/voice-api/execute", "http://127.0.0.1:9094/cmd_vel",
                    "http://user:pass@127.0.0.1:9094/voice-api/execute", "http://127.0.0.1/voice-api/execute",
                    DEFAULT_GATEWAY_URL + "?url=remote", DEFAULT_GATEWAY_URL + "#fragment", "garbage"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_gateway_url(url)


class _GatewayFixture(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.server.received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(self.server.reply_status)
        if self.server.reply_status == 302:
            self.send_header("Location", "/redirected")
        self.end_headers()
        self.wfile.write(self.server.reply)


class TestVoiceGatewayClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _GatewayFixture)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:%d/voice-api/execute" % cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.server.received = []
        self.server.reply_status = 200
        self.server.reply = json.dumps({"accepted": True, "status": "accepted", "task_id": "owner-1"}).encode()

    def test_forward_is_one_http_request_with_original_envelope(self):
        original = envelope()
        receipt = VoiceGatewayClient(self.url).forward(original)
        self.assertEqual(self.server.received, [original])
        self.assertEqual(receipt, {"accepted": True, "status": "accepted", "task_id": "owner-1"})
        self.assertEqual(original["issued_at_ms"], 1)

    def test_gateway_rejection_is_preserved(self):
        self.server.reply_status = 409
        self.server.reply = b'{"accepted": false, "status": "rejected", "reason": "stale_command"}'
        receipt = VoiceGatewayClient(self.url).forward(envelope())
        self.assertEqual(receipt["reason"], "stale_command")
        self.assertFalse(receipt["accepted"])
        self.assertEqual(len(self.server.received), 1)

    def test_response_failure_stays_unknown_and_is_never_retried(self):
        client = VoiceGatewayClient(self.url)
        for failure in (error.URLError("response lost"), TimeoutError("response lost"), http.client.IncompleteRead(b"{}", 20)):
            with self.subTest(failure=failure), patch.object(client.opener, "open", side_effect=failure) as opening:
                original = envelope()
                receipt = client.forward(original)
                self.assertIsNone(receipt["accepted"])
                self.assertEqual(receipt["status"], "unknown")
                self.assertEqual(receipt["command_id"], original["command_id"])
                self.assertFalse(receipt["retry_allowed"])
                opening.assert_called_once()

    def test_http_redirect_is_not_followed(self):
        self.server.reply_status = 302
        receipt = VoiceGatewayClient(self.url).forward(envelope())
        self.assertEqual(receipt["reason"], "gateway_redirect_refused")
        self.assertEqual(len(self.server.received), 1)

    def test_invalid_gateway_reply_does_not_claim_success(self):
        for body in (b'[]', b'{}', b'{"accepted": true}', b'{"accepted": 1, "status":"accepted"}',
                     b'{"accepted":true,"status":"accepted","command_id":"different-command"}',
                     b'not json', b'\xff', b'x' * 65537, b'[' * 2000 + b']' * 2000):
            with self.subTest(body=body[:20]):
                self.server.reply = body
                receipt = VoiceGatewayClient(self.url).forward(envelope())
                self.assertIsNone(receipt["accepted"])
                self.assertEqual(receipt["reason"], "invalid_gateway_receipt")

    def test_http_error_cannot_claim_acceptance(self):
        self.server.reply_status = 500
        receipt = VoiceGatewayClient(self.url).forward(envelope())
        self.assertEqual(receipt["reason"], "invalid_gateway_receipt")
        self.assertIsNone(receipt["accepted"])

    def test_invalid_envelope_is_not_sent(self):
        client = VoiceGatewayClient(self.url)
        with patch.object(client.opener, "open") as opening, self.assertRaises(ValueError):
            client.forward({"text": "前进"})
        opening.assert_not_called()


class TestVoiceEntryPoint(unittest.TestCase):
    def test_offline_modes_are_explicit_and_do_not_send_requests(self):
        with patch("tools.fishbot_edge_voice_node.VoiceGatewayClient") as client:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["--phrase", "不要前进"]), 0)
            self.assertFalse(json.loads(output.getvalue())["accepted"])
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["--test"]), 0)
            self.assertEqual(json.loads(output.getvalue())["mode"], "offline_text_only")
        client.assert_not_called()

    def test_missing_ros_is_failure_without_implicit_offline_success(self):
        with patch.dict(sys.modules, {"rclpy": None}), contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(main([]), 2)
        self.assertIn("dependencies are unavailable", output.getvalue())

    def test_ros_adapter_only_forwards_envelopes_and_publishes_receipts(self):
        # These are local doubles, not running ROS nodes or publishers.
        published, publishers, received = [], [], []
        original = envelope()
        class String:
            def __init__(self, data=""):
                self.data = data
        class Node:
            def __init__(self, name):
                self.name = name
            def create_publisher(self, msg_type, topic, queue):
                publishers.append((msg_type, topic))
                return types.SimpleNamespace(publish=lambda message: published.append(json.loads(message.data)))
            def create_subscription(self, msg_type, topic, callback, queue):
                self.callback = callback
            def get_logger(self):
                return types.SimpleNamespace(info=lambda text: None)
            def destroy_node(self):
                pass
        rclpy = types.ModuleType("rclpy")
        rclpy.init = Mock()
        rclpy.shutdown = Mock()
        def spin(node):
            node.callback(String("前进"))
            node.callback(String(json.dumps(original)))
        rclpy.spin = spin
        nodes = types.ModuleType("rclpy.node")
        nodes.Node = Node
        std = types.ModuleType("std_msgs")
        messages = types.ModuleType("std_msgs.msg")
        messages.String = String
        def forward(command):
            received.append(command)
            return {"accepted": True, "status": "accepted", "task_id": "mission-1"}
        with patch.dict(sys.modules, {"rclpy": rclpy, "rclpy.node": nodes, "std_msgs": std, "std_msgs.msg": messages}), patch.object(VoiceGatewayClient, "forward", side_effect=forward):
            self.assertEqual(main([]), 0)
        self.assertEqual(publishers, [(String, "/voice_command")])
        self.assertEqual(received, [original])
        self.assertEqual(published[0]["status"], "rejected")
        self.assertEqual(published[1]["task_id"], "mission-1")
        rclpy.init.assert_called_once()
        rclpy.shutdown.assert_called_once()


if __name__ == "__main__":
    unittest.main()
