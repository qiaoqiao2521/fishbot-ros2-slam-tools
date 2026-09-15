from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.command_gateway import CommandGateway
from backend.config import get_settings
from backend.schemas import RobotRuntimeState, make_fake_system_state
from backend.ros_topic_bridge import RosTopicBridge
from backend.serial_reader import SerialReader
from backend.websocket_manager import ConnectionContext, WebSocketManager


START_MONOTONIC_S = time.monotonic()
manager = WebSocketManager()
serial_reader: SerialReader | None = None
ros_bridge: RosTopicBridge | None = None
command_gateway: CommandGateway | None = None


def _normalize_host(value: str) -> str:
    host = value.strip().lower()
    if host.startswith("::ffff:"):
        return host.removeprefix("::ffff:")
    return host


def _resolve_read_only(runtime: RobotRuntimeState | None, *, read_only_override: bool | None = None) -> bool:
    if read_only_override is not None:
        return read_only_override
    if runtime is None:
        return True
    return True if runtime.read_only is None else runtime.read_only


def _runtime_with_override(
    runtime: RobotRuntimeState | None,
    *,
    read_only_override: bool | None = None,
) -> RobotRuntimeState | None:
    if read_only_override is None:
        return runtime
    effective = runtime.model_copy(deep=True) if runtime is not None else RobotRuntimeState()
    effective.read_only = read_only_override
    return effective


def _resolve_debug_read_only_override(websocket: WebSocket) -> bool | None:
    settings = get_settings()
    requested = str(websocket.query_params.get("debug_writable", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not requested or not settings.control_debug_override_active:
        return None

    allowed_hosts = {_normalize_host(host) for host in settings.control_debug_override_allow_hosts}
    client_host = _normalize_host(websocket.client.host if websocket.client is not None else "")
    if "*" not in allowed_hosts and client_host not in allowed_hosts:
        return None
    return False


def _build_system_state(
    reader: SerialReader | None,
    bridge: RosTopicBridge | None,
    *,
    read_only_override: bool | None = None,
):
    serial_state = reader.snapshot_state() if reader is not None else None
    ros_runtime = bridge.snapshot_state() if bridge is not None else None
    effective_runtime = _runtime_with_override(ros_runtime, read_only_override=read_only_override)
    gateway = command_gateway
    control_state = (
        gateway.snapshot_state(read_only=_resolve_read_only(effective_runtime, read_only_override=read_only_override))
        if gateway is not None
        else None
    )
    return make_fake_system_state(
        START_MONOTONIC_S,
        serial=serial_state,
        ros_runtime=effective_runtime,
        control_state=control_state,
    )


async def _system_state_loop(
    stop_event: asyncio.Event,
    *,
    reader: SerialReader | None,
    bridge: RosTopicBridge | None,
) -> None:
    settings = get_settings()
    while not stop_event.is_set():
        await manager.broadcast_personalized_system_state(
            lambda context: _build_system_state(
                reader,
                bridge,
                read_only_override=context.read_only_override,
            )
        )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.system_state_interval_s)
        except TimeoutError:
            continue


async def _robot_pose_loop(stop_event: asyncio.Event, bridge: RosTopicBridge | None) -> None:
    if bridge is None:
        await stop_event.wait()
        return

    settings = get_settings()
    last_revision = -1

    while not stop_event.is_set():
        revision, pose = bridge.snapshot_pose()
        if pose is not None and revision != last_revision:
            await manager.broadcast_robot_pose(pose)
            last_revision = revision
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.robot_pose_interval_s)
        except TimeoutError:
            continue


async def _map_snapshot_loop(stop_event: asyncio.Event, bridge: RosTopicBridge | None) -> None:
    if bridge is None:
        await stop_event.wait()
        return

    settings = get_settings()
    last_revision = -1

    while not stop_event.is_set():
        revision, snapshot = bridge.snapshot_map()
        if snapshot is not None and revision != last_revision:
            await manager.broadcast_map_snapshot(snapshot)
            last_revision = revision
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.map_snapshot_interval_s)
        except TimeoutError:
            continue


async def _scan_frame_loop(stop_event: asyncio.Event, bridge: RosTopicBridge | None) -> None:
    if bridge is None:
        await stop_event.wait()
        return

    settings = get_settings()
    last_revision = -1

    while not stop_event.is_set():
        revision, scan_frame = bridge.snapshot_scan()
        if scan_frame is not None and revision != last_revision:
            await manager.broadcast_scan_frame(scan_frame)
            last_revision = revision
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.scan_frame_interval_s)
        except TimeoutError:
            continue


async def _control_watchdog_loop(stop_event: asyncio.Event, gateway: CommandGateway | None) -> None:
    if gateway is None:
        await stop_event.wait()
        return

    settings = get_settings()
    while not stop_event.is_set():
        gateway.expire_deadman()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.control_watchdog_interval_s)
        except TimeoutError:
            continue


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global ros_bridge, serial_reader, command_gateway

    settings = get_settings()
    stop_event = asyncio.Event()
    serial_reader = SerialReader(settings=settings, manager=manager)
    ros_bridge = RosTopicBridge(settings=settings)
    command_gateway = CommandGateway(settings=settings)
    ros_bridge.start()
    command_gateway.start()
    system_task = asyncio.create_task(_system_state_loop(stop_event, reader=serial_reader, bridge=ros_bridge))
    pose_task = asyncio.create_task(_robot_pose_loop(stop_event, ros_bridge))
    map_task = asyncio.create_task(_map_snapshot_loop(stop_event, ros_bridge))
    scan_task = asyncio.create_task(_scan_frame_loop(stop_event, ros_bridge))
    control_task = asyncio.create_task(_control_watchdog_loop(stop_event, command_gateway))
    serial_task = asyncio.create_task(serial_reader.run(stop_event))
    try:
        yield
    finally:
        stop_event.set()
        system_task.cancel()
        pose_task.cancel()
        map_task.cancel()
        scan_task.cancel()
        control_task.cancel()
        serial_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await system_task
        with contextlib.suppress(asyncio.CancelledError):
            await pose_task
        with contextlib.suppress(asyncio.CancelledError):
            await map_task
        with contextlib.suppress(asyncio.CancelledError):
            await scan_task
        with contextlib.suppress(asyncio.CancelledError):
            await control_task
        with contextlib.suppress(asyncio.CancelledError):
            await serial_task
        serial_reader = None
        if ros_bridge is not None:
            ros_bridge.stop()
        ros_bridge = None
        if command_gateway is not None:
            command_gateway.stop()
        command_gateway = None


app = FastAPI(title="ROS2 Mobile Panel Day 5", version="0.5.0-day5", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "scope": "day5_control_loop"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    client_id = uuid.uuid4().hex
    connection_context = ConnectionContext(read_only_override=_resolve_debug_read_only_override(websocket))
    await manager.connect(websocket, context=connection_context)
    try:
        current_serial_reader = serial_reader
        current_ros_bridge = ros_bridge
        current_gateway = command_gateway
        await manager.send_system_state(
            websocket,
            _build_system_state(
                current_serial_reader,
                current_ros_bridge,
                read_only_override=connection_context.read_only_override,
            ),
        )
        if current_serial_reader is not None:
            batch = current_serial_reader.build_batch_event()
            if batch is not None:
                await manager.send_serial_batch(websocket, batch)
            await manager.send_serial_stats(websocket, current_serial_reader.build_stats_event())
        if current_ros_bridge is not None:
            _, pose = current_ros_bridge.snapshot_pose()
            if pose is not None:
                await manager.send_robot_pose(websocket, pose)
            _, snapshot = current_ros_bridge.snapshot_map()
            if snapshot is not None:
                await manager.send_map_snapshot(websocket, snapshot)
            _, scan_frame = current_ros_bridge.snapshot_scan()
            if scan_frame is not None:
                await manager.send_scan_frame(websocket, scan_frame)
        while True:
            raw_message = await websocket.receive_text()
            if current_gateway is None:
                continue
            try:
                payload = json.loads(raw_message)
            except json.JSONDecodeError:
                ack = {
                    "type": "control_ack",
                    "ts": int(time.time() * 1000),
                    "ok": False,
                    "op": "invalid_json",
                    "applied_linear": None,
                    "applied_angular": None,
                    "read_only": _resolve_read_only(
                        current_ros_bridge.snapshot_state() if current_ros_bridge is not None else None,
                        read_only_override=connection_context.read_only_override,
                    ),
                    "message": "invalid json",
                }
            else:
                if not isinstance(payload, dict):
                    ack = {
                        "type": "control_ack",
                        "ts": int(time.time() * 1000),
                        "ok": False,
                        "op": "invalid_payload",
                        "applied_linear": None,
                        "applied_angular": None,
                        "read_only": _resolve_read_only(
                            current_ros_bridge.snapshot_state() if current_ros_bridge is not None else None,
                            read_only_override=connection_context.read_only_override,
                        ),
                        "message": "payload must be object",
                    }
                else:
                    ack = current_gateway.handle_message(
                        payload,
                        client_id=client_id,
                        read_only=_resolve_read_only(
                            current_ros_bridge.snapshot_state() if current_ros_bridge is not None else None,
                            read_only_override=connection_context.read_only_override,
                        ),
                    )
            await manager.send_control_ack(websocket, ack)
    except WebSocketDisconnect:
        pass
    finally:
        current_gateway = command_gateway
        if current_gateway is not None:
            current_gateway.handle_disconnect(client_id)
        await manager.disconnect(websocket)
