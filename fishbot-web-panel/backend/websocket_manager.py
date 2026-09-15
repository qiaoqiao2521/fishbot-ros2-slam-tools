from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass

from fastapi import WebSocket

from backend.schemas import (
    ControlAckEvent,
    MapSnapshotEvent,
    RobotPose,
    ScanFrameEvent,
    SerialBatchEvent,
    SerialStatsEvent,
    ServerEvent,
    SystemState,
    robot_pose_event,
    system_state_event,
)


@dataclass(slots=True)
class ConnectionContext:
    read_only_override: bool | None = None


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._contexts: dict[WebSocket, ConnectionContext] = {}
        self._lock = asyncio.Lock()
        self._seq = 0

    async def connect(self, websocket: WebSocket, context: ConnectionContext | None = None) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
            self._contexts[websocket] = context or ConnectionContext()

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
            self._contexts.pop(websocket, None)

    async def send_system_state(self, websocket: WebSocket, state: SystemState) -> None:
        event = self._next_system_state_event(state)
        await websocket.send_json(event.model_dump(mode="json"))

    async def broadcast_system_state(self, state: SystemState) -> None:
        event = self._next_system_state_event(state)
        stale: list[WebSocket] = []

        for websocket in await self._snapshot_connections():
            try:
                await websocket.send_json(event.model_dump(mode="json"))
            except Exception:
                stale.append(websocket)

        if stale:
            await self._discard_many(stale)

    async def broadcast_personalized_system_state(self, builder) -> None:
        stale: list[WebSocket] = []

        for websocket, context in await self._snapshot_connection_contexts():
            try:
                event = self._next_system_state_event(builder(context))
                await websocket.send_json(event.model_dump(mode="json"))
            except Exception:
                stale.append(websocket)

        if stale:
            await self._discard_many(stale)

    async def send_robot_pose(self, websocket: WebSocket, pose: RobotPose) -> None:
        event = self._next_robot_pose_event(pose)
        await websocket.send_json(event.model_dump(mode="json"))

    async def broadcast_robot_pose(self, pose: RobotPose) -> None:
        event = self._next_robot_pose_event(pose)
        stale: list[WebSocket] = []

        for websocket in await self._snapshot_connections():
            try:
                await websocket.send_json(event.model_dump(mode="json"))
            except Exception:
                stale.append(websocket)

        if stale:
            await self._discard_many(stale)

    async def send_map_snapshot(self, websocket: WebSocket, event: MapSnapshotEvent) -> None:
        await websocket.send_json(event.model_dump(mode="json"))

    async def broadcast_map_snapshot(self, event: MapSnapshotEvent) -> None:
        await self._broadcast_model(event)

    async def send_scan_frame(self, websocket: WebSocket, event: ScanFrameEvent) -> None:
        await websocket.send_json(event.model_dump(mode="json"))

    async def broadcast_scan_frame(self, event: ScanFrameEvent) -> None:
        await self._broadcast_model(event)

    async def send_control_ack(self, websocket: WebSocket, event: ControlAckEvent | dict) -> None:
        if hasattr(event, "model_dump"):
            await websocket.send_json(event.model_dump(mode="json"))
            return
        await websocket.send_json(event)

    async def send_serial_batch(self, websocket: WebSocket, event: SerialBatchEvent) -> None:
        await websocket.send_json(event.model_dump(mode="json"))

    async def broadcast_serial_batch(self, event: SerialBatchEvent) -> None:
        await self._broadcast_model(event)

    async def send_serial_stats(self, websocket: WebSocket, event: SerialStatsEvent) -> None:
        await websocket.send_json(event.model_dump(mode="json"))

    async def broadcast_serial_stats(self, event: SerialStatsEvent) -> None:
        await self._broadcast_model(event)

    async def _snapshot_connections(self) -> list[WebSocket]:
        async with self._lock:
            return list(self._connections)

    async def _snapshot_connection_contexts(self) -> list[tuple[WebSocket, ConnectionContext]]:
        async with self._lock:
            return [(websocket, self._contexts.get(websocket, ConnectionContext())) for websocket in self._connections]

    async def _discard_many(self, websockets: Iterable[WebSocket]) -> None:
        async with self._lock:
            for websocket in websockets:
                self._connections.discard(websocket)

    async def _broadcast_model(
        self,
        event: SerialBatchEvent | SerialStatsEvent | MapSnapshotEvent | ScanFrameEvent,
    ) -> None:
        stale: list[WebSocket] = []

        for websocket in await self._snapshot_connections():
            try:
                await websocket.send_json(event.model_dump(mode="json"))
            except Exception:
                stale.append(websocket)

        if stale:
            await self._discard_many(stale)

    def _next_system_state_event(self, state: SystemState) -> ServerEvent:
        self._seq += 1
        return system_state_event(self._seq, state)

    def _next_robot_pose_event(self, pose: RobotPose) -> ServerEvent:
        self._seq += 1
        return robot_pose_event(self._seq, pose)
