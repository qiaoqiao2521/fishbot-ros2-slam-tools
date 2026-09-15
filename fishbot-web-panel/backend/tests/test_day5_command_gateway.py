from __future__ import annotations

from backend.command_gateway import CommandGateway
from backend.config import Settings, get_settings
from backend.schemas import ControlState, RobotRuntimeState, now_ms

import backend.app as app_module
from fastapi.testclient import TestClient


class CapturingGateway(CommandGateway):
    def __init__(self, *, now: callable | None = None) -> None:
        super().__init__(
            settings=Settings(ros_enabled=False),
            monotonic=now,
        )
        self.published: list[tuple[float, float]] = []

    def _publish_velocity(self, linear: float, angular: float) -> None:
        self.published.append((linear, angular))

    def _publisher_available(self) -> bool:
        return True


def test_read_only_blocks_move_but_allows_explicit_stop():
    gateway = CapturingGateway()

    move_ack = gateway.handle_message(
        {
            "op": "move_command",
            "ts": 1710000000000,
            "linear": 0.15,
            "angular": 0.0,
            "deadman_token": "phone-press-1",
            "ttl_ms": 300,
        },
        client_id="phone",
        read_only=True,
    )

    assert move_ack.ok is False
    assert move_ack.op == "move_command"
    assert move_ack.read_only is True
    assert move_ack.message == "read_only: move_command blocked"
    assert gateway.published == []

    stop_ack = gateway.handle_message(
        {"op": "stop", "ts": 1710000000050, "reason": "ui_stop"},
        client_id="phone",
        read_only=True,
    )

    assert stop_ack.ok is True
    assert stop_ack.op == "stop"
    assert stop_ack.read_only is True
    assert stop_ack.message == "stopped"
    assert gateway.published == [(0.0, 0.0)]


def test_deadman_expiry_publishes_zero_once():
    now = 100.0

    def monotonic() -> float:
        return now

    gateway = CapturingGateway(now=monotonic)

    ack = gateway.handle_message(
        {
            "op": "move_command",
            "ts": now_ms(),
            "linear": 0.15,
            "angular": 0.0,
            "deadman_token": "phone-press-1",
            "ttl_ms": 300,
        },
        client_id="phone",
        read_only=False,
    )

    assert ack.ok is True
    assert gateway.published == [(0.15, 0.0)]
    assert gateway.expire_deadman() is False

    now = 100.31

    assert gateway.expire_deadman() is True
    assert gateway.expire_deadman() is False
    assert gateway.published == [(0.15, 0.0), (0.0, 0.0)]

    state = gateway.snapshot_state(read_only=False)
    assert state.active_command is None
    assert state.last_stop_reason == "deadman_timeout"


def test_stale_move_command_is_rejected_without_publish():
    gateway = CapturingGateway()

    ack = gateway.handle_message(
        {
            "op": "move_command",
            "ts": now_ms() - 10_000,
            "linear": 0.15,
            "angular": 0.0,
            "deadman_token": "replay-of-expired-press",
            "ttl_ms": 300,
        },
        client_id="replay",
        read_only=False,
    )

    assert ack.ok is False
    assert ack.op == "move_command"
    assert ack.message == "stale move_command rejected"
    assert ack.applied_linear is None
    assert gateway.published == []
    assert gateway.snapshot_state(read_only=False).active_command is None


def test_fresh_move_command_with_same_deadman_token_is_still_accepted():
    gateway = CapturingGateway()

    stale = gateway.handle_message(
        {
            "op": "move_command",
            "ts": now_ms() - 10_000,
            "linear": 0.15,
            "angular": 0.0,
            "deadman_token": "same-press-token",
            "ttl_ms": 300,
        },
        client_id="replay",
        read_only=False,
    )
    fresh = gateway.handle_message(
        {
            "op": "move_command",
            "ts": now_ms() + 200,  # 允许少量时钟前偏
            "linear": 0.15,
            "angular": 0.0,
            "deadman_token": "same-press-token",
            "ttl_ms": 300,
        },
        client_id="phone",
        read_only=False,
    )

    assert stale.ok is False
    assert stale.message == "stale move_command rejected"
    assert fresh.ok is True
    assert fresh.applied_linear == 0.15
    assert gateway.published == [(0.15, 0.0)]


def test_active_controller_disconnect_stops_robot():
    gateway = CapturingGateway()

    gateway.handle_message(
        {
            "op": "move_command",
            "ts": now_ms(),
            "linear": 0.0,
            "angular": 0.5,
            "deadman_token": "turn-1",
            "ttl_ms": 300,
        },
        client_id="phone",
        read_only=False,
    )

    gateway.handle_disconnect("status-only")
    assert gateway.published == [(0.0, 0.5)]

    gateway.handle_disconnect("phone")
    assert gateway.published == [(0.0, 0.5), (0.0, 0.0)]
    assert gateway.snapshot_state(read_only=False).last_stop_reason == "ws_disconnect"


def test_websocket_control_messages_return_control_ack(monkeypatch):
    class FakeBridge:
        def snapshot_state(self) -> RobotRuntimeState:
            return RobotRuntimeState(ok=True, mode="manual", nav_status="idle", read_only=False)

        def stop(self) -> None:
            return None

        def snapshot_pose(self):
            return 0, None

        def snapshot_map(self):
            return 0, None

        def snapshot_scan(self):
            return 0, None

    class FakeCommandGateway:
        def __init__(self) -> None:
            self.disconnected_client: str | None = None

        def stop(self) -> None:
            return None

        def snapshot_state(self, *, read_only: bool) -> ControlState:
            return ControlState(
                read_only=read_only,
                output_enabled=not read_only,
                deadman_timeout_ms=300,
                active_command=None,
                last_stop_reason="idle",
            )

        def handle_message(self, message, *, client_id: str, read_only: bool):
            return {
                "type": "control_ack",
                "ts": 1710000000001,
                "ok": True,
                "op": message["op"],
                "applied_linear": 0.0,
                "applied_angular": 0.0,
                "read_only": read_only,
                "message": "stopped",
            }

        def handle_disconnect(self, client_id: str) -> None:
            self.disconnected_client = client_id

    fake_gateway = FakeCommandGateway()

    with TestClient(app_module.app) as client:
        monkeypatch.setattr(app_module, "serial_reader", None)
        monkeypatch.setattr(app_module, "ros_bridge", FakeBridge())
        monkeypatch.setattr(app_module, "command_gateway", fake_gateway)

        with client.websocket_connect("/ws") as websocket:
            assert websocket.receive_json()["type"] == "system_state"
            websocket.send_json({"op": "stop", "ts": 1710000000000, "reason": "ui_stop"})
            ack = websocket.receive_json()

    assert ack["type"] == "control_ack"
    assert ack["ok"] is True
    assert ack["op"] == "stop"
    assert ack["read_only"] is False
    assert fake_gateway.disconnected_client is not None


def test_websocket_debug_override_unlocks_only_the_current_session(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("CONTROL_DEBUG_OVERRIDE_ENABLED", "true")
    monkeypatch.setenv("CONTROL_DEBUG_OVERRIDE_ALLOW_HOSTS", "testclient")
    monkeypatch.setenv("CONTROL_DEBUG_MOCK_CMD_VEL_ENABLED", "true")
    get_settings.cache_clear()

    class FakeBridge:
        def snapshot_state(self) -> RobotRuntimeState:
            return RobotRuntimeState(ok=True, mode="manual", nav_status="idle", read_only=True)

        def stop(self) -> None:
            return None

        def snapshot_pose(self):
            return 0, None

        def snapshot_map(self):
            return 0, None

        def snapshot_scan(self):
            return 0, None

    with TestClient(app_module.app) as client:
        monkeypatch.setattr(app_module, "serial_reader", None)
        monkeypatch.setattr(app_module, "ros_bridge", FakeBridge())

        with client.websocket_connect("/ws") as locked_socket:
            locked_state = locked_socket.receive_json()

        with client.websocket_connect("/ws?debug_writable=1") as writable_socket:
            writable_state = writable_socket.receive_json()
            writable_socket.send_json(
                {
                    "op": "move_command",
                    "ts": now_ms(),
                    "linear": 0.15,
                    "angular": 0.0,
                    "deadman_token": "browser-hold-1",
                    "ttl_ms": 300,
                }
            )
            writable_ack = writable_socket.receive_json()

    get_settings.cache_clear()

    assert locked_state["payload"]["read_only"] is True
    assert locked_state["payload"]["control"]["read_only"] is True
    assert writable_state["payload"]["read_only"] is False
    assert writable_state["payload"]["control"]["read_only"] is False
    assert writable_state["payload"]["control"]["output_enabled"] is True
    assert writable_ack["type"] == "control_ack"
    assert writable_ack["ok"] is True
    assert writable_ack["op"] == "move_command"
    assert writable_ack["read_only"] is False
    assert writable_ack["message"] == "accepted"


def test_websocket_debug_override_is_blocked_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CONTROL_DEBUG_OVERRIDE_ENABLED", "true")
    monkeypatch.setenv("CONTROL_DEBUG_OVERRIDE_ALLOW_HOSTS", "testclient")
    monkeypatch.setenv("CONTROL_DEBUG_MOCK_CMD_VEL_ENABLED", "true")
    get_settings.cache_clear()

    class FakeBridge:
        def snapshot_state(self) -> RobotRuntimeState:
            return RobotRuntimeState(ok=True, mode="manual", nav_status="idle", read_only=True)

        def stop(self) -> None:
            return None

        def snapshot_pose(self):
            return 0, None

        def snapshot_map(self):
            return 0, None

        def snapshot_scan(self):
            return 0, None

    with TestClient(app_module.app) as client:
        monkeypatch.setattr(app_module, "serial_reader", None)
        monkeypatch.setattr(app_module, "ros_bridge", FakeBridge())

        with client.websocket_connect("/ws?debug_writable=1") as websocket:
            state = websocket.receive_json()
            websocket.send_json(
                {
                    "op": "move_command",
                    "ts": 1710000000000,
                    "linear": 0.15,
                    "angular": 0.0,
                    "deadman_token": "blocked-in-prod",
                    "ttl_ms": 300,
                }
            )
            ack = websocket.receive_json()

    get_settings.cache_clear()

    assert state["payload"]["read_only"] is True
    assert state["payload"]["control"]["read_only"] is True
    assert ack["type"] == "control_ack"
    assert ack["ok"] is False
    assert ack["read_only"] is True
    assert ack["message"] == "read_only: move_command blocked"
