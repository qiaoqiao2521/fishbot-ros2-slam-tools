from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.ros_topic_bridge import adapt_status_payload, extract_odom_state


def _ns(**kwargs):
    return SimpleNamespace(**kwargs)


def test_odom_to_robot_pose_extracts_pose_and_velocity():
    yaw = math.pi / 2
    odom = _ns(
        header=_ns(frame_id="odom"),
        pose=_ns(
            pose=_ns(
                position=_ns(x=1.25, y=-0.5),
                orientation=_ns(x=0.0, y=0.0, z=math.sin(yaw / 2), w=math.cos(yaw / 2)),
            ),
        ),
        twist=_ns(twist=_ns(linear=_ns(x=0.42), angular=_ns(z=-0.18))),
    )

    odom_state = extract_odom_state(odom)

    assert odom_state.pose.x == pytest.approx(1.25)
    assert odom_state.pose.y == pytest.approx(-0.5)
    assert odom_state.pose.yaw == pytest.approx(yaw)
    assert odom_state.pose.frame == "odom"
    assert odom_state.pose.source == "/odom"
    assert odom_state.linear_speed == pytest.approx(0.42)
    assert odom_state.angular_speed == pytest.approx(-0.18)


def test_missing_custom_status_fields_fall_back_to_null_or_unknown():
    status = adapt_status_payload({})

    assert status.mode == "unknown"
    assert status.nav_status == "unknown"
    assert status.battery_pct is None
    assert status.read_only is None


def test_websocket_system_state_includes_day3_status_fields():
    client = TestClient(app)

    with client.websocket_connect("/ws") as websocket:
        message = websocket.receive_json()

    assert message["type"] == "system_state"
    payload = message["payload"]
    assert "latency_ms" in payload
    assert "read_only" in payload
    assert "mode" in payload
    assert "battery_pct" in payload
    assert "nav_status" in payload
    assert "linear_speed" in payload
    assert "angular_speed" in payload
