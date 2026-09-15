from __future__ import annotations

import asyncio
import math
import threading
import time
from collections import deque
from collections.abc import Iterable

from backend.config import Settings
from backend.schemas import (
    SerialBatchEvent,
    SerialState,
    SerialStatsEvent,
    now_ms,
    serial_batch_event,
    serial_stats_event,
)

try:
    import serial  # type: ignore
except Exception:  # pragma: no cover - real serial support is optional in tests
    serial = None


def parse_serial_line(raw_line: str, fallback_ts_ms: int) -> tuple[int, float] | None:
    line = raw_line.strip()
    if not line:
        return None

    if "," in line:
        raw_t, raw_v = line.split(",", maxsplit=1)
        try:
            return int(float(raw_t.strip())), float(raw_v.strip())
        except ValueError:
            return None

    try:
        return fallback_ts_ms, float(line)
    except ValueError:
        return None


class RingBuffer:
    def __init__(self, max_points: int) -> None:
        self._points: deque[tuple[int, float]] = deque(maxlen=max_points)

    def append(self, point: tuple[int, float]) -> None:
        self._points.append(point)

    def clear(self) -> None:
        self._points.clear()

    def trim_older_than(self, min_ts_ms: int) -> None:
        while self._points and self._points[0][0] < min_ts_ms:
            self._points.popleft()

    def snapshot(self) -> list[tuple[int, float]]:
        return list(self._points)

    def __len__(self) -> int:
        return len(self._points)


class SerialReader:
    def __init__(self, settings: Settings, manager: object | None) -> None:
        self.settings = settings
        self.manager = manager
        self.invalid_lines = 0
        self._total_valid_points = 0
        self._last_rx_ms: int | None = None
        self._source_open = False
        self._pending_points: list[tuple[int, float]] = []
        self._ring = RingBuffer(max_points=settings.serial_window_max_points)
        self._lock = threading.Lock()
        self._thread_stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def total_valid_points(self) -> int:
        with self._lock:
            return self._total_valid_points

    def snapshot_state(self, current_ts_ms: int | None = None) -> SerialState:
        current_ts_ms = now_ms() if current_ts_ms is None else current_ts_ms
        with self._lock:
            last_rx_ms = self._last_rx_ms
            source_open = self._source_open

        age_ms = None if last_rx_ms is None else max(0, current_ts_ms - last_rx_ms)
        ok = bool(source_open and age_ms is not None and age_ms <= self.settings.serial_stale_after_ms)

        return SerialState(
            ok=ok,
            port=self.settings.serial_port,
            baud=self.settings.serial_baud,
            last_rx_age_ms=age_ms,
        )

    def snapshot_points(self) -> list[tuple[int, float]]:
        with self._lock:
            return self._ring.snapshot()

    def ingest_line(self, raw_line: str, fallback_ts_ms: int | None = None) -> tuple[int, float] | None:
        point = parse_serial_line(raw_line, fallback_ts_ms=now_ms() if fallback_ts_ms is None else fallback_ts_ms)
        received_at_ms = now_ms()
        with self._lock:
            if point is None:
                self.invalid_lines += 1
                return None

            self._ring.append(point)
            self._trim_locked()
            self._pending_points.append(point)
            self._last_rx_ms = received_at_ms
            self._total_valid_points += 1
            return point

    def drain_pending_points(self) -> list[tuple[int, float]]:
        with self._lock:
            points = list(self._pending_points)
            self._pending_points.clear()
            return points

    def build_batch_event(
        self,
        points: Iterable[tuple[int, float]] | None = None,
        *,
        ts_ms: int | None = None,
    ) -> SerialBatchEvent | None:
        payload = list(self.snapshot_points() if points is None else points)
        if not payload:
            return None
        return serial_batch_event(self.settings.serial_stream, payload, ts=ts_ms)

    def build_stats_event(self, *, ts_ms: int | None = None) -> SerialStatsEvent:
        with self._lock:
            self._trim_locked()
            points = self._ring.snapshot()
            values = [value for _, value in points]

        minimum = min(values) if values else None
        maximum = max(values) if values else None
        average = round(sum(values) / len(values), 4) if values else None

        return serial_stats_event(
            stream=self.settings.serial_stream,
            count=len(points),
            minimum=minimum,
            maximum=maximum,
            average=average,
            paused=False,
            ts=ts_ms,
        )

    async def run(self, stop_event: asyncio.Event) -> None:
        if not self.settings.serial_enabled:
            return

        self._start_thread()
        next_stats_at = time.monotonic() + self.settings.serial_stats_interval_s

        try:
            while not stop_event.is_set():
                timeout = min(
                    self.settings.serial_batch_interval_s,
                    max(0.01, next_stats_at - time.monotonic()),
                )
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=timeout)
                except TimeoutError:
                    pass

                batch = self.drain_pending_points()
                if batch and self.manager is not None:
                    event = self.build_batch_event(batch)
                    if event is not None:
                        await self.manager.broadcast_serial_batch(event)

                if time.monotonic() >= next_stats_at:
                    if self.manager is not None:
                        await self.manager.broadcast_serial_stats(self.build_stats_event())
                    next_stats_at = time.monotonic() + self.settings.serial_stats_interval_s
        finally:
            self.stop()

    def stop(self) -> None:
        self._thread_stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None
        with self._lock:
            self._source_open = False

    def _start_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        self._thread_stop.clear()
        self._thread = threading.Thread(target=self._thread_main, name="serial-reader", daemon=True)
        self._thread.start()

    def _thread_main(self) -> None:
        if self.settings.serial_port.startswith("mock://"):
            self._run_mock_source()
            return

        while not self._thread_stop.is_set():
            try:
                self._run_real_serial()
            except Exception:
                with self._lock:
                    self._source_open = False
                self._thread_stop.wait(self.settings.serial_reconnect_interval_s)

    def _run_real_serial(self) -> None:
        if serial is None:
            raise RuntimeError("pyserial is required for real serial ports")

        with serial.serial_for_url(  # type: ignore[union-attr]
            self.settings.serial_port,
            baudrate=self.settings.serial_baud,
            timeout=self.settings.serial_read_timeout_s,
        ) as port:
            with self._lock:
                self._source_open = True

            while not self._thread_stop.is_set():
                raw = port.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="ignore")
                self.ingest_line(line)

        with self._lock:
            self._source_open = False

    def _run_mock_source(self) -> None:
        start = time.monotonic()
        index = 0
        with self._lock:
            self._source_open = True

        while not self._thread_stop.is_set():
            elapsed = time.monotonic() - start
            value = round(1.2 + math.sin(elapsed * 2.5) * 0.35 + (index % 5) * 0.01, 4)
            self.ingest_line(str(value))
            index += 1
            self._thread_stop.wait(self.settings.serial_mock_interval_s)

        with self._lock:
            self._source_open = False

    def _trim_locked(self) -> None:
        min_ts = now_ms() - self.settings.serial_window_seconds * 1000
        self._ring.trim_older_than(min_ts)
