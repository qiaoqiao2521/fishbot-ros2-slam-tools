from __future__ import annotations

import base64
import math
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import backend.app as app_module
from backend.ros_topic_bridge import laser_scan_to_scan_frame, occupancy_grid_to_map_snapshot
from backend.schemas import MapSnapshotEvent, RobotPose, RobotRuntimeState, ScanFrameEvent


def _ns(**kwargs):
    return SimpleNamespace(**kwargs)


def _decode_rle8(payload: str) -> list[int]:
    raw = base64.b64decode(payload.encode("ascii"))
    result: list[int] = []
    for index in range(0, len(raw), 2):
        run = raw[index]
        value = raw[index + 1]
        result.extend([value] * run)
    return result


def test_occupancy_grid_to_map_snapshot_normalizes_and_rle_encodes_pixels():
    grid = _ns(
        header=_ns(frame_id="map"),
        info=_ns(
            width=3,
            height=2,
            resolution=0.05,
            origin=_ns(
                position=_ns(x=-1.0, y=-2.0),
                orientation=_ns(x=0.0, y=0.0, z=0.0, w=1.0),
            ),
        ),
        data=[0, 100, -1, 100, 0, 0],
    )

    snapshot = occupancy_grid_to_map_snapshot(grid)

    assert snapshot.type == "map_snapshot"
    assert snapshot.frame == "map"
    assert snapshot.width == 3
    assert snapshot.height == 2
    assert snapshot.resolution == pytest.approx(0.05)
    assert snapshot.origin == {"x": -1.0, "y": -2.0, "yaw": 0.0}
    assert snapshot.encoding == "rle8"
    assert _decode_rle8(snapshot.data) == [
        0,
        255,
        255,
        255,
        0,
        205,
    ]


def test_laser_scan_to_scan_frame_projects_robot_relative_points_into_pose_frame():
    pose = RobotPose(x=1.0, y=2.0, yaw=math.pi / 2, frame="map", source="/odom")
    scan = _ns(
        header=_ns(frame_id="base_scan"),
        angle_min=0.0,
        angle_increment=math.pi / 2,
        range_min=0.05,
        range_max=8.0,
        ranges=[1.0, 2.0, float("inf"), 0.01],
    )

    frame = laser_scan_to_scan_frame(scan, pose=pose, max_points=32)

    assert frame.type == "scan_frame"
    assert frame.frame == "map"
    assert frame.points == pytest.approx(
        [
            {"x": 1.0, "y": 3.0},
            {"x": -1.0, "y": 2.0},
        ]
    )


def test_websocket_initial_messages_include_map_snapshot_and_scan_frame(monkeypatch):
    class FakeBridge:
        def snapshot_state(self) -> RobotRuntimeState:
            return RobotRuntimeState(ok=True, mode="auto", nav_status="idle", read_only=True)

        def stop(self) -> None:
            return None

        def snapshot_pose(self):
            return 3, RobotPose(x=0.5, y=-0.25, yaw=0.3, frame="map", source="/odom")

        def snapshot_map(self):
            return 5, MapSnapshotEvent(
                ts=1710000000000,
                frame="map",
                width=2,
                height=2,
                resolution=0.05,
                origin={"x": 0.0, "y": 0.0, "yaw": 0.0},
                encoding="rle8",
                data=base64.b64encode(bytes([4, 255])).decode("ascii"),
            )

        def snapshot_scan(self):
            return 7, ScanFrameEvent(
                ts=1710000000100,
                frame="map",
                points=[{"x": 0.5, "y": 0.2}],
            )

    with TestClient(app_module.app) as client:
        monkeypatch.setattr(app_module, "ros_bridge", FakeBridge())
        monkeypatch.setattr(app_module, "serial_reader", None)

        received_types: list[str] = []
        with client.websocket_connect("/ws") as websocket:
            for _ in range(4):
                received_types.append(websocket.receive_json()["type"])

    assert "system_state" in received_types
    assert "robot_pose" in received_types
    assert "map_snapshot" in received_types
    assert "scan_frame" in received_types
