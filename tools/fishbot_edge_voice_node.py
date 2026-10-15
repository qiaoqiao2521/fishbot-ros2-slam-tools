#!/usr/bin/env python3
"""Offline text intents and a ROS String adapter for the local voice gateway.

This module performs no audio capture, ASR, acceleration or velocity control.
The gateway admits commands and delegates tasks to the existing task owners.
"""

import argparse
import http.client
import ipaddress
import json
import math
import re
import sys
import unicodedata
import uuid
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, parse, request

DEFAULT_GATEWAY_URL = "http://127.0.0.1:9094/voice-api/execute"
MAX_TEXT_LENGTH = 256
MAX_ENVELOPE_BYTES = 8192


class EdgeHardwareDetector:
    """Report CPU flags; a detected flag does not prove model acceleration."""

    @staticmethod
    def detect_capabilities() -> Dict[str, bool]:
        caps = dict.fromkeys(("is_arm64", "has_arm_fp16", "has_arm_fp16_scalar",
                              "has_arm_fp16_vector", "has_neon", "has_vfpv4",
                              "has_x86_avx2"), False)
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as stream:
                content = stream.read().lower()
        except OSError:
            return caps
        flags = set()
        for line in content.splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip() in {"flags", "features"}:
                flags.update(value.split())
        caps.update(
            is_arm64=("aarch64" in content or "arm64" in content
                      or "cpu implementer" in content),
            has_arm_fp16_scalar="fphp" in flags,
            has_arm_fp16_vector="asimdhp" in flags,
            has_arm_fp16=bool({"fphp", "asimdhp"} & flags),
            has_neon=bool({"neon", "asimd"} & flags),
            has_vfpv4="vfpv4" in flags,
            has_x86_avx2="avx2" in flags,
        )
        return caps


class FillerWordFilter:
    """Remove edge hesitation tokens, preserving words inside the instruction."""

    _LEFT = re.compile(r"^(?:(?:呃|啊|嗯|唔|那个|就是说)|(?:um|uh|er|ah)\b)[\s,，.。…]*", re.I)
    _RIGHT = re.compile(r"[\s,，.。…]*(?:(?:呃|啊|嗯|唔)|\b(?:um|uh|er|ah))$", re.I)

    @classmethod
    def clean(cls, text: str) -> Tuple[str, List[str]]:
        cleaned, removed = text.strip(), []
        for pattern in (cls._LEFT, cls._RIGHT):
            while True:
                match = pattern.search(cleaned)
                if not match:
                    break
                removed.append(match.group().strip(" \t\r\n,，.。…"))
                cleaned = (cleaned[:match.start()] + cleaned[match.end():]).strip()
        return cleaned, removed


class EdgeVoiceIntentParser:
    """Conservative single-task grammar; positive STOP takes precedence."""

    MAX_TEXT_LENGTH = MAX_TEXT_LENGTH
    _NUMBER = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+|[零〇一二两三四五六七八九十百千点半]+)"
    _QUANTITY = re.compile(
        r"(?P<number>" + _NUMBER + r")\s*(?P<unit>厘米|公分|米|度|cm\b|m\b|degrees?\b|deg\b|°)", re.I)
    _PATTERNS = {
        "FORWARD": r"向前(?:走|行驶|移动)?|往前(?:走|行驶|移动)?|前进|直行|\b(?:go\s+)?forward\b",
        "BACKWARD": r"向后(?:走|退|移动)?|往后(?:走|退|移动)?|后退|倒车|退后|\b(?:go\s+back|(?:go\s+)?backward)\b",
        "TURN_LEFT": r"(?:向左|往左)(?:转弯|转|旋转)?|左转(?:弯)?|左拐|\b(?:turn\s+)?left\b",
        "TURN_RIGHT": r"(?:向右|往右)(?:转弯|转|旋转)?|右转(?:弯)?|右拐|\b(?:turn\s+)?right\b",
        "STOP": r"紧急停止|停下(?:来)?|停止(?!线)|停车(?!场|位|点|区)|暂停|刹车|立定|别动|不许动|不要动|住手|停(?!靠|车场|车位|车点|车区|止线)|\b(?:stop|halt)\b",
        "DOCK": r"回家充电|(?:返回|回到|回|去|前往|停靠)充电(?:桩|站)|返回充电|去充电|回充|充电|\b(?:return\s+to\s+dock|go\s+to\s+dock|dock|recharge)\b",
        "RETURN_HOME": r"返回起点|回到起点|返回出发点|回起点|回家|返航|\b(?:return\s+home|go\s+home|return\s+to\s+start|home)\b",
        "TRANSPORT": r"装货(?:然后|并|并且)?(?:运输|运送)|运送货物|搬运货物|运输(?:货物)?|装货|\b(?:load\s+and\s+transport|transport|deliver\s+cargo)\b",
    }
    _ACTIONS = {intent: re.compile(pattern, re.I) for intent, pattern in _PATTERNS.items()}
    _NEGATION = re.compile(
        r"不要|别|不准|禁止|不能|不许|不用|不想|勿|莫|没有|不"
        r"|\b(?:do\s+not|don't|dont|never|not|no)\b", re.I)
    _POLITE = re.compile(
        r"小车|机器人|帮我|给我|麻烦|请|马上|现在|立刻|立即|赶快|快|慢慢|缓慢|一下|一点点|一点|一段|吧|谢谢|执行|开始"
        r"|\b(?:please|robot|slowly|now|immediately)\b", re.I)
    _SEPARATORS = re.compile(r"[\s,，。.!！?？;；:：、…]+")
    _GOTO = re.compile(r"^(?:请\s*)?(?:前往|去|到|go\s+to\s+|navigate\s+to\s+)(.+)$", re.I)

    @staticmethod
    def _number(token: str) -> float:
        if token == "半":
            return .5
        try:
            return float(token)
        except ValueError:
            pass
        if token.count("点") > 1 or "半" in token:
            raise ValueError("invalid_number")
        parts = token.split("点")
        digits = {char: value for value, chars in enumerate(("零〇", "一", "二两", "三", "四", "五", "六", "七", "八", "九")) for char in chars}
        integer, current, previous_unit, zero_placeholder = 0, None, 10000, False
        for char in parts[0]:
            if char in digits:
                if current not in (None, 0):
                    raise ValueError("invalid_number")
                current = digits[char]
                zero_placeholder = zero_placeholder or (current == 0 and previous_unit != 10000)
            elif char in {"十", "百", "千"}:
                unit = {"十": 10, "百": 100, "千": 1000}[char]
                if unit >= previous_unit:
                    raise ValueError("invalid_number")
                integer += (1 if current is None else current) * unit
                current, previous_unit = None, unit
            else:
                raise ValueError("invalid_number")
        if previous_unit >= 100 and previous_unit != 10000 and current and not zero_placeholder:
            raise ValueError("invalid_number")
        integer += current or 0
        if len(parts) == 1:
            return float(integer)
        if not parts[1] or any(char not in digits for char in parts[1]):
            raise ValueError("invalid_number")
        return integer + float("0." + "".join(str(digits[char]) for char in parts[1]))

    @classmethod
    def _matches(cls, text: str) -> List[Tuple[int, int, str]]:
        candidates = [(match.start(), match.end(), intent)
                      for intent, pattern in cls._ACTIONS.items() for match in pattern.finditer(text)]
        # Longest phrases own overlapping words: 回家充电 is DOCK, not RETURN_HOME.
        selected = []
        for candidate in sorted(candidates, key=lambda item: (-(item[1] - item[0]), item[0])):
            if not any(candidate[0] < item[1] and candidate[1] > item[0] for item in selected):
                selected.append(candidate)
        return sorted(selected)

    @classmethod
    def parse(cls, raw_transcript: str) -> Dict[str, Any]:
        result = dict(raw=raw_transcript, cleaned="", dropped_fillers=[], intent="UNKNOWN",
                      accepted=False, reason="invalid_text", parameters={}, linear_x=0.0, angular_z=0.0)

        def reject(reason: str) -> Dict[str, Any]:
            result["reason"] = reason
            return result

        def accept(intent: str, parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
            result.update(intent=intent, accepted=True, reason="accepted", parameters=parameters or {})
            return result

        if not isinstance(raw_transcript, str):
            return reject("invalid_text")
        if len(raw_transcript) > cls.MAX_TEXT_LENGTH:
            return reject("text_too_long")
        if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} and char not in "\r\n\t" for char in raw_transcript):
            return reject("invalid_text")
        cleaned, dropped = FillerWordFilter.clean(unicodedata.normalize("NFKC", raw_transcript))
        result.update(cleaned=cleaned, dropped_fillers=dropped)
        if len(cleaned) > cls.MAX_TEXT_LENGTH:
            return reject("text_too_long")
        if not cleaned or not cls._SEPARATORS.sub("", cleaned):
            return reject("empty_text")
        matches = cls._matches(cleaned)
        # A bare 走 is supported only as the complete instruction or a negated verb.
        if not matches and re.fullmatch(r"(?:(?:小车|机器人|请|不要|别)\s*)*走(?:吧)?", cleaned):
            start = cleaned.index("走")
            matches = [(start, start + 1, "FORWARD")]
        negated = []
        previous_end, previous_negative = 0, False
        for start, end, intent in matches:
            segment = cleaned[previous_end:start]
            clauses = re.split(r"[,，;；。.!！?？\n]|\b(?:then|but)\b|然后|接着|但是|马上|立刻|立即", segment, flags=re.I)
            prefix = clauses[-1]
            # Negation also covers coordinated verbs: 不要前进和停止 is not STOP.
            coordinated = re.fullmatch(r"(?:\s|和|与|或|或者|以及|并且|and|or)*", prefix, flags=re.I)
            negative = bool(cls._NEGATION.search(prefix)) or bool(previous_negative and len(clauses) == 1 and coordinated)
            # A comma inside 不要，停下 must not erase its only negation.
            if not previous_end and cls._NEGATION.search(segment):
                negative = True
            negated.append(negative)
            previous_negative = negative
            previous_end = end
        if any(intent == "STOP" and not negative
               for (_, _, intent), negative in zip(matches, negated)):
            return accept("STOP")
        if any(negated):
            return reject("negated_command")
        goto_text = re.sub(r"^(?:小车|机器人|麻烦|帮我|请)\s*", "", cleaned).strip()
        goto_match = cls._GOTO.fullmatch(goto_text)
        if goto_match and not any(item[2] in {"DOCK", "RETURN_HOME"} for item in matches):
            place = goto_match.group(1).strip().strip('"\'“”‘’').strip()
            if (not 1 <= len(place) <= 32 or not re.fullmatch(r"[\w\u4e00-\u9fff -]+", place)
                    or not re.search(r"[A-Za-z\u4e00-\u9fff]", place)
                    or re.search(r"然后|接着|并且|再|不要|别|禁止|\b(?:then|and|not|stop)\b", place, re.I)):
                return reject("invalid_place")
            if matches:
                return reject("multiple_actions")
            return accept("GOTO", {"place": place})
        if not matches:
            return reject("unknown_intent")
        if len(matches) != 1:
            return reject("multiple_actions")
        start, end, intent = matches[0]
        remaining = cleaned[:start] + " " + cleaned[end:]
        quantities = list(cls._QUANTITY.finditer(remaining))
        parameters = {}
        if intent in {"FORWARD", "BACKWARD", "TURN_LEFT", "TURN_RIGHT"}:
            is_distance = intent in {"FORWARD", "BACKWARD"}
            failure = "invalid_distance" if is_distance else "invalid_angle"
            if len(quantities) > 1:
                return reject(failure)
            value = (.4 if intent == "FORWARD" else .3) if is_distance else 90.0
            if quantities:
                quantity = quantities[0]
                unit = quantity["unit"].lower()
                if (unit in {"厘米", "公分", "米", "cm", "m"}) != is_distance:
                    return reject(failure)
                try:
                    value = cls._number(quantity["number"])
                except ValueError:
                    return reject("invalid_number")
                if unit in {"厘米", "公分", "cm"}:
                    value /= 100
                remaining = remaining[:quantity.start()] + " " + remaining[quantity.end():]
            if not math.isfinite(value) or not ((.05 <= value <= 1.0) if is_distance else (0 < value <= 180)):
                return reject(failure)
            if is_distance:
                parameters["distance_m"] = value
            else:
                parameters["angle_rad"] = math.radians(value) * (1 if intent == "TURN_LEFT" else -1)
        elif quantities:
            return reject("unexpected_quantity")
        residue = cls._SEPARATORS.sub("", cls._POLITE.sub("", remaining))
        if residue:
            return reject("unsupported_text")
        return accept(intent, parameters)


def validate_gateway_url(url: str) -> str:
    """Limit forwarding to a literal loopback HTTP endpoint with no redirects."""
    try:
        parts = parse.urlsplit(url)
        address = ipaddress.ip_address(parts.hostname or "")
        port = parts.port
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid_gateway_url") from exc
    if (parts.scheme != "http" or not address.is_loopback or port is None
            or not 1 <= port <= 65535 or parts.username is not None or parts.password is not None
            or parts.path != "/voice-api/execute" or parts.query or parts.fragment):
        raise ValueError("invalid_gateway_url")
    return url


def validate_voice_envelope(envelope: Any) -> Dict[str, Any]:
    """Validate structure only; gateway owns identity, freshness and deduplication."""
    required = {"command_id", "session_id", "sequence", "issued_at_ms", "ttl_ms", "text"}
    if not isinstance(envelope, dict) or not required <= envelope.keys() or envelope.keys() - required - {"asr_id"}:
        raise ValueError("invalid_envelope")
    try:
        if not isinstance(envelope["command_id"], str):
            raise ValueError("invalid_command_id")
        uuid.UUID(envelope["command_id"])
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("invalid_command_id") from exc
    for name in ("session_id", "asr_id"):
        if name in envelope and (not isinstance(envelope[name], str)
                                 or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", envelope[name])):
            raise ValueError("invalid_" + name)
    for name, minimum in (("sequence", 0), ("issued_at_ms", 1), ("ttl_ms", 1)):
        if type(envelope[name]) is not int or not minimum <= envelope[name] <= 2**53 - 1:
            raise ValueError("invalid_" + name)
    text = envelope["text"]
    if (not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_LENGTH
            or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} and char not in "\r\n\t" for char in text)):
        raise ValueError("invalid_text")
    return dict(envelope)


def parse_voice_envelope(raw: str) -> Dict[str, Any]:
    if not isinstance(raw, str):
        raise ValueError("invalid_envelope")
    try:
        if len(raw.encode("utf-8")) > MAX_ENVELOPE_BYTES:
            raise ValueError("invalid_envelope")
    except UnicodeError as exc:
        raise ValueError("invalid_envelope") from exc

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_envelope_key")
            result[key] = value
        return result

    try:
        return validate_voice_envelope(json.loads(raw, object_pairs_hook=unique_pairs))
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("invalid_envelope_json") from exc


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class VoiceGatewayClient:
    """Send each envelope once; retain uncertainty when a response is lost."""

    def __init__(self, url: str = DEFAULT_GATEWAY_URL, timeout: float = 3.0):
        self.url = validate_gateway_url(url)
        if not .1 <= timeout <= 10:
            raise ValueError("invalid_gateway_timeout")
        self.timeout = timeout
        self.opener = request.build_opener(request.ProxyHandler({}), _NoRedirect())

    @staticmethod
    def _unknown(envelope: Dict[str, Any], reason: str) -> Dict[str, Any]:
        return {"command_id": envelope["command_id"], "session_id": envelope["session_id"],
                "sequence": envelope["sequence"], "accepted": None, "status": "unknown",
                "reason": reason, "retry_allowed": False}

    def forward(self, envelope: Dict[str, Any]) -> Dict[str, Any]:
        envelope = validate_voice_envelope(envelope)
        outgoing = request.Request(self.url, data=json.dumps(envelope, ensure_ascii=False).encode("utf-8"),
                                   headers={"Content-Type": "application/json"}, method="POST")
        try:
            try:
                response = self.opener.open(outgoing, timeout=self.timeout)
            except error.HTTPError as exc:
                if 300 <= exc.code < 400:
                    exc.close()
                    return self._unknown(envelope, "gateway_redirect_refused")
                response = exc
            with response:
                response_code = response.getcode()
                body = response.read(65537)
            if len(body) > 65536:
                return self._unknown(envelope, "invalid_gateway_receipt")
            receipt = json.loads(body.decode("utf-8"))
            if (not isinstance(receipt, dict) or "accepted" not in receipt
                    or type(receipt["accepted"]) not in {bool, type(None)}
                    or not isinstance(receipt.get("status"), str) or not receipt["status"]
                    or ("command_id" in receipt and receipt["command_id"] != envelope["command_id"])
                    or (response_code >= 400 and receipt["accepted"] is True)):
                return self._unknown(envelope, "invalid_gateway_receipt")
            return receipt
        except (error.URLError, OSError, TimeoutError, http.client.HTTPException):
            return self._unknown(envelope, "gateway_unavailable")
        except (ValueError, UnicodeError, RecursionError):
            return self._unknown(envelope, "invalid_gateway_receipt")


def run_standalone_test() -> None:
    print(json.dumps({"mode": "offline_text_only", "hardware_flags": EdgeHardwareDetector.detect_capabilities(),
                      "phrases": [EdgeVoiceIntentParser.parse(phrase) for phrase in
                                  ("呃那个……小车前进", "不要前进", "往后走", "前进，马上停下", "不要停下",
                                   "左转九十度", "前往厨房", "装货运输")]}, ensure_ascii=False, indent=2))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="FishBot text intent and local gateway adapter")
    parser.add_argument("--test", action="store_true", help="Run offline text examples and CPU flag diagnostics")
    parser.add_argument("--phrase", default=None, help="Parse one phrase offline; do not execute it")
    parser.add_argument("--gateway-url", default=DEFAULT_GATEWAY_URL, help="Literal loopback voice gateway endpoint")
    args = parser.parse_args(argv)
    if args.test or args.phrase is not None:
        if args.phrase is not None:
            print(json.dumps(EdgeVoiceIntentParser.parse(args.phrase), ensure_ascii=False, indent=2))
        else:
            run_standalone_test()
        return 0
    try:
        client = VoiceGatewayClient(args.gateway_url)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        import rclpy
        from rclpy.node import Node
        from std_msgs.msg import String
    except ImportError:
        print("ROS 2 Python dependencies are unavailable. Load the ROS environment, or use --test/--phrase for offline parsing.", file=sys.stderr)
        return 2

    class EdgeVoiceNode(Node):
        def __init__(self):
            super().__init__("fishbot_edge_voice_node")
            self.voice_pub = self.create_publisher(String, "/voice_command", 10)
            self.sub = self.create_subscription(String, "/voice_raw_text", self.on_voice_text, 10)
            self.get_logger().info("Listening for JSON command envelopes on /voice_raw_text; forwarding to local task gateway.")

        def on_voice_text(self, msg):
            try:
                receipt = client.forward(parse_voice_envelope(msg.data))
            except ValueError as exc:
                receipt = {"accepted": False, "status": "rejected", "reason": str(exc), "retry_allowed": False}
            output = String()
            output.data = json.dumps(receipt, ensure_ascii=False)
            self.voice_pub.publish(output)

    rclpy.init(args=[])
    node = EdgeVoiceNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
