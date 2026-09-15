from __future__ import annotations

import math
import time
from typing import Any, Literal

from pydantic import BaseModel, Field


class PiState(BaseModel):
    cpu_pct: float = Field(ge=0, le=100)
    mem_pct: float = Field(ge=0, le=100)
    temp_c: float | None


class PowerState(BaseModel):
    battery_pct: float = Field(ge=0, le=100)
    charging: bool


class RosState(BaseModel):
    ok: bool
    nav_state: str


class SerialState(BaseModel):
    ok: bool
    port: str
    baud: int
    last_rx_age_ms: int | None


class ControlState(BaseModel):
    read_only: bool
    output_enabled: bool
    deadman_timeout_ms: int
    active_command: str | None
    last_stop_reason: str


class NetworkState(BaseModel):
    rtt_ms: int | None


class RobotPose(BaseModel):
    x: float
    y: float
    yaw: float
    frame: str
    source: str


class RobotRuntimeState(BaseModel):
    ok: bool = False
    mode: str = "unknown"
    battery_pct: float | None = None
    nav_status: str = "unknown"
    linear_speed: float | None = None
    angular_speed: float | None = None
    read_only: bool | None = None
    pose: RobotPose | None = None


class SystemState(BaseModel):
    online: bool
    latency_ms: int | None = None
    read_only: bool
    mode: str
    battery_pct: float | None = None
    nav_status: str
    linear_speed: float | None = None
    angular_speed: float | None = None
    server_time_ms: int
    uptime_s: int
    pi: PiState
    power: PowerState
    ros: RosState
    serial: SerialState
    control: ControlState
    network: NetworkState


class ServerEvent(BaseModel):
    type: Literal["system_state", "robot_pose"]
    seq: int
    ts_ms: int
    payload: dict[str, Any]


class MapSnapshotEvent(BaseModel):
    type: Literal["map_snapshot"] = "map_snapshot"
    ts: int
    frame: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    resolution: float = Field(gt=0)
    origin: dict[str, float]
    encoding: Literal["rle8"] = "rle8"
    data: str


class ScanFrameEvent(BaseModel):
    type: Literal["scan_frame"] = "scan_frame"
    ts: int
    frame: str
    points: list[dict[str, float]]


class SerialBatchPoint(BaseModel):
    t: int
    v: float


class SerialBatchEvent(BaseModel):
    type: Literal["serial_batch"] = "serial_batch"
    ts: int
    stream: str
    points: list[SerialBatchPoint]


class SerialStatsEvent(BaseModel):
    type: Literal["serial_stats"] = "serial_stats"
    ts: int
    stream: str
    count: int
    min: float | None
    max: float | None
    avg: float | None
    paused: bool


class RobotPoseEvent(BaseModel):
    type: Literal["robot_pose"] = "robot_pose"
    seq: int
    ts_ms: int
    payload: dict[str, Any]


class MoveCommandMessage(BaseModel):
    op: Literal["move_command"] = "move_command"
    ts: int
    linear: float
    angular: float
    deadman_token: str = Field(min_length=1)
    ttl_ms: int = Field(gt=0)


class StopCommandMessage(BaseModel):
    op: Literal["stop"] = "stop"
    ts: int
    reason: str = Field(min_length=1)


class PingMessage(BaseModel):
    op: Literal["ping"] = "ping"
    ts: int


class ControlAckEvent(BaseModel):
    type: Literal["control_ack"] = "control_ack"
    ts: int
    ok: bool
    op: str
    applied_linear: float | None = None
    applied_angular: float | None = None
    read_only: bool
    message: str


def now_ms() -> int:
    return int(time.time() * 1000)


def make_fake_system_state(
    start_monotonic_s: float,
    now_monotonic_s: float | None = None,
    serial: SerialState | None = None,
    ros_runtime: RobotRuntimeState | None = None,
    control_state: ControlState | None = None,
) -> SystemState:
    """Day 3 merged state: preserves Day 1/2 shape while exposing ROS-ready flat fields."""
    current = time.monotonic() if now_monotonic_s is None else now_monotonic_s
    uptime_s = max(0, int(current - start_monotonic_s))
    wave = math.sin(uptime_s / 8)
    runtime = ros_runtime or RobotRuntimeState()
    latency_ms = 24 + int(abs(8 * math.sin(uptime_s / 5)))
    read_only = True if runtime.read_only is None else runtime.read_only
    battery_pct = runtime.battery_pct

    return SystemState(
        online=True,
        latency_ms=latency_ms,
        read_only=read_only,
        mode=runtime.mode or "unknown",
        battery_pct=battery_pct,
        nav_status=runtime.nav_status or "unknown",
        linear_speed=runtime.linear_speed,
        angular_speed=runtime.angular_speed,
        server_time_ms=now_ms(),
        uptime_s=uptime_s,
        pi=PiState(
            cpu_pct=round(18 + 6 * wave, 1),
            mem_pct=round(42 + 3 * math.cos(uptime_s / 11), 1),
            temp_c=round(49 + 2 * wave, 1),
        ),
        power=PowerState(
            battery_pct=(
                battery_pct
                if battery_pct is not None
                else round(82 - min(uptime_s / 600, 12), 1)
            ),
            charging=False,
        ),
        ros=RosState(
            ok=runtime.ok,
            nav_state=runtime.nav_status or "unknown",
        ),
        serial=serial
        or SerialState(
            ok=False,
            port="mock://day1",
            baud=115200,
            last_rx_age_ms=None,
        ),
        control=control_state
        or ControlState(
            read_only=read_only,
            output_enabled=False,
            deadman_timeout_ms=400,
            active_command=None,
            last_stop_reason="day1_read_only_mock",
        ),
        network=NetworkState(
            rtt_ms=latency_ms,
        ),
    )


def system_state_event(seq: int, state: SystemState) -> ServerEvent:
    return ServerEvent(
        type="system_state",
        seq=seq,
        ts_ms=now_ms(),
        payload=state.model_dump(mode="json"),
    )


def robot_pose_event(seq: int, pose: RobotPose) -> RobotPoseEvent:
    return RobotPoseEvent(
        type="robot_pose",
        seq=seq,
        ts_ms=now_ms(),
        payload=pose.model_dump(mode="json"),
    )


def serial_batch_event(stream: str, points: list[tuple[int, float]], ts: int | None = None) -> SerialBatchEvent:
    return SerialBatchEvent(
        ts=now_ms() if ts is None else ts,
        stream=stream,
        points=[SerialBatchPoint(t=point_t, v=point_v) for point_t, point_v in points],
    )


def serial_stats_event(
    *,
    stream: str,
    count: int,
    minimum: float | None,
    maximum: float | None,
    average: float | None,
    paused: bool = False,
    ts: int | None = None,
) -> SerialStatsEvent:
    return SerialStatsEvent(
        ts=now_ms() if ts is None else ts,
        stream=stream,
        count=count,
        min=minimum,
        max=maximum,
        avg=average,
        paused=paused,
    )
