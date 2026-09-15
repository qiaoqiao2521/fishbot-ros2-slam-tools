from fastapi.testclient import TestClient

from backend.app import app
from backend.schemas import make_fake_system_state


def test_fake_system_state_has_day1_contract_fields():
    state = make_fake_system_state(start_monotonic_s=100.0, now_monotonic_s=142.0)

    assert state.online is True
    assert state.uptime_s == 42
    assert state.power.battery_pct is not None
    assert state.pi.cpu_pct >= 0
    assert state.ros.ok is False
    assert state.ros.nav_state in {"idle", "unknown"}
    assert state.serial.ok is False
    assert state.control.read_only is True
    assert state.control.output_enabled is False
    assert state.control.active_command is None
    assert state.network.rtt_ms is not None


def test_websocket_sends_system_state_envelope():
    client = TestClient(app)

    with client.websocket_connect("/ws") as websocket:
        message = websocket.receive_json()

    assert message["type"] == "system_state"
    assert isinstance(message["seq"], int)
    assert isinstance(message["ts_ms"], int)
    assert message["payload"]["online"] is True
    assert message["payload"]["control"]["read_only"] is True
    assert message["payload"]["control"]["output_enabled"] is False
    assert "network" in message["payload"]
