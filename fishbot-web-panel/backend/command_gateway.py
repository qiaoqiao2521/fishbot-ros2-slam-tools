from __future__ import annotations

import importlib
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import ValidationError

from backend.config import Settings
from backend.schemas import (
    ControlAckEvent,
    ControlState,
    MoveCommandMessage,
    PingMessage,
    StopCommandMessage,
    now_ms,
)


class _DebugAxis:
    def __init__(self) -> None:
        self.x = 0.0
        self.z = 0.0


class _DebugTwist:
    def __init__(self) -> None:
        self.linear = _DebugAxis()
        self.angular = _DebugAxis()


class _DebugPublisher:
    def __init__(self) -> None:
        self.published: list[tuple[float, float]] = []

    def publish(self, twist: _DebugTwist) -> None:
        self.published.append((float(twist.linear.x), float(twist.angular.z)))


class CommandGateway:
    def __init__(
        self,
        *,
        settings: Settings,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self.settings = settings
        self._monotonic = monotonic or time.monotonic
        self._lock = threading.Lock()
        self._rclpy: Any = None
        self._node: Any = None
        self._publisher: Any = None
        self._twist_type: Any = None
        self._startup_error: str | None = None
        self._active_command: str | None = None
        self._active_client_id: str | None = None
        self._active_deadman_token: str | None = None
        self._deadline_monotonic_s: float | None = None
        self._last_stop_reason = "idle"
        self._last_applied_linear = 0.0
        self._last_applied_angular = 0.0

    def start(self) -> None:
        if self.settings.control_debug_override_active and self.settings.control_debug_mock_cmd_vel_enabled:
            self._publisher = _DebugPublisher()
            self._twist_type = _DebugTwist
            self._startup_error = None
            return
        if not self.settings.ros_enabled:
            return
        if self._publisher_available():
            return

        try:
            self._setup_publisher()
        except Exception as exc:  # pragma: no cover - depends on ROS2 runtime
            self._startup_error = str(exc)
            self._destroy_node()

    def stop(self) -> None:
        with self._lock:
            should_publish_stop = self._active_command is not None and self._publisher_available()
        if should_publish_stop:
            self._issue_stop("gateway_shutdown")
        self._destroy_node()

    def snapshot_state(self, *, read_only: bool) -> ControlState:
        with self._lock:
            active_command = self._active_command
            deadline = self._deadline_monotonic_s
            last_stop_reason = self._last_stop_reason
            output_enabled = self._publisher_available() and self._startup_error is None and not read_only

        if active_command is not None and deadline is not None and self._monotonic() >= deadline:
            active_command = None

        return ControlState(
            read_only=read_only,
            output_enabled=output_enabled,
            deadman_timeout_ms=self.settings.control_default_ttl_ms,
            active_command=active_command,
            last_stop_reason=last_stop_reason,
        )

    def handle_message(
        self,
        raw_message: Mapping[str, Any],
        *,
        client_id: str,
        read_only: bool,
    ) -> ControlAckEvent:
        op = str(raw_message.get("op", "unknown"))

        if op == "stop":
            try:
                message = StopCommandMessage.model_validate(raw_message)
            except ValidationError:
                return self._ack(ok=False, op=op, read_only=read_only, message="invalid stop payload")
            self._issue_stop(message.reason)
            return self._ack(ok=True, op="stop", read_only=read_only, message="stopped", linear=0.0, angular=0.0)

        if op == "ping":
            try:
                PingMessage.model_validate(raw_message)
            except ValidationError:
                return self._ack(ok=False, op=op, read_only=read_only, message="invalid ping payload")
            return self._ack(ok=True, op="ping", read_only=read_only, message="pong")

        if op != "move_command":
            return self._ack(ok=False, op=op, read_only=read_only, message="unsupported op")

        try:
            message = MoveCommandMessage.model_validate(raw_message)
        except ValidationError:
            return self._ack(ok=False, op=op, read_only=read_only, message="invalid move_command payload")

        if read_only:
            return self._ack(
                ok=False,
                op="move_command",
                read_only=True,
                message="read_only: move_command blocked",
            )

        # 重放防护：move_command 的 ts 明显落后于服务器时间说明是过期/重放命令，
        # 直接拒绝，不给它重新武装 deadman 窗口的机会。
        command_age_ms = now_ms() - message.ts
        if command_age_ms > self.settings.control_command_max_age_ms:
            return self._ack(
                ok=False,
                op="move_command",
                read_only=False,
                message="stale move_command rejected",
            )

        if not self._publisher_available():
            return self._ack(
                ok=False,
                op="move_command",
                read_only=False,
                message="cmd_vel publisher unavailable",
            )

        linear = self._clamp(message.linear, -self.settings.control_max_linear_mps, self.settings.control_max_linear_mps)
        angular = self._clamp(
            message.angular,
            -self.settings.control_max_angular_rps,
            self.settings.control_max_angular_rps,
        )
        ttl_ms = max(self.settings.control_min_ttl_ms, min(message.ttl_ms, self.settings.control_max_ttl_ms))

        self._publish_velocity(linear, angular)
        with self._lock:
            self._active_command = "move_command"
            self._active_client_id = client_id
            self._active_deadman_token = message.deadman_token
            self._deadline_monotonic_s = self._monotonic() + ttl_ms / 1000.0
            self._last_applied_linear = linear
            self._last_applied_angular = angular

        return self._ack(
            ok=True,
            op="move_command",
            read_only=False,
            message="accepted",
            linear=linear,
            angular=angular,
        )

    def handle_disconnect(self, client_id: str) -> None:
        with self._lock:
            if client_id != self._active_client_id:
                return
        self._issue_stop("ws_disconnect")

    def expire_deadman(self) -> bool:
        with self._lock:
            deadline = self._deadline_monotonic_s
            active = self._active_command
        if active is None or deadline is None or self._monotonic() < deadline:
            return False
        self._issue_stop("deadman_timeout")
        return True

    def _setup_publisher(self) -> None:
        rclpy = importlib.import_module("rclpy")
        geometry_module = importlib.import_module("geometry_msgs.msg")

        if not rclpy.ok():
            rclpy.init(args=None)

        node = rclpy.create_node(self.settings.control_node_name)
        publisher = node.create_publisher(geometry_module.Twist, self.settings.ros_cmd_vel_topic, 10)

        self._rclpy = rclpy
        self._node = node
        self._publisher = publisher
        self._twist_type = geometry_module.Twist
        self._startup_error = None

    def _destroy_node(self) -> None:
        if self._node is not None:
            try:
                self._node.destroy_node()
            except Exception:
                pass
        self._node = None
        self._publisher = None
        self._twist_type = None
        self._rclpy = None

    def _publisher_available(self) -> bool:
        return self._publisher is not None and self._twist_type is not None

    def _issue_stop(self, reason: str) -> None:
        if self._publisher_available():
            self._publish_velocity(0.0, 0.0)
        with self._lock:
            self._active_command = None
            self._active_client_id = None
            self._active_deadman_token = None
            self._deadline_monotonic_s = None
            self._last_applied_linear = 0.0
            self._last_applied_angular = 0.0
            self._last_stop_reason = reason

    def _publish_velocity(self, linear: float, angular: float) -> None:
        if not self._publisher_available():
            return

        twist = self._twist_type()
        twist.linear.x = float(linear)
        twist.angular.z = float(angular)
        self._publisher.publish(twist)

    def _ack(
        self,
        *,
        ok: bool,
        op: str,
        read_only: bool,
        message: str,
        linear: float | None = None,
        angular: float | None = None,
    ) -> ControlAckEvent:
        return ControlAckEvent(
            ts=now_ms(),
            ok=ok,
            op=op,
            applied_linear=linear,
            applied_angular=angular,
            read_only=read_only,
            message=message,
        )

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, float(value)))
