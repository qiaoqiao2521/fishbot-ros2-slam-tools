from __future__ import annotations

import time

from fastapi.testclient import TestClient

from backend.app import app
from backend.config import get_settings
from backend.serial_reader import RingBuffer, SerialReader, parse_serial_line


def test_parse_serial_line_accepts_float_and_timestamp_value():
    assert parse_serial_line("1.23", fallback_ts_ms=1000) == (1000, 1.23)
    assert parse_serial_line("1710000000000,2.5", fallback_ts_ms=1000) == (1710000000000, 2.5)
    assert parse_serial_line("bad,line", fallback_ts_ms=1000) is None
    assert parse_serial_line("", fallback_ts_ms=1000) is None


def test_ring_buffer_has_fixed_upper_bound():
    ring = RingBuffer(max_points=3)

    ring.append((1, 1.0))
    ring.append((2, 2.0))
    ring.append((3, 3.0))
    ring.append((4, 4.0))

    assert ring.snapshot() == [(2, 2.0), (3, 3.0), (4, 4.0)]
    assert len(ring) == 3


def test_invalid_lines_increment_counter_without_interrupting_reader():
    settings = get_settings().model_copy(update={"serial_port": "mock://disabled"})
    reader = SerialReader(settings=settings, manager=None)
    base_ts = int(time.time() * 1000)

    reader.ingest_line("not-a-number", fallback_ts_ms=base_ts)
    reader.ingest_line("1.5", fallback_ts_ms=base_ts + 100)

    stats = reader.build_stats_event(ts_ms=base_ts + 200)

    assert reader.invalid_lines == 1
    assert stats.count == 1
    assert stats.avg == 1.5


def test_websocket_receives_serial_messages_from_mock_source(monkeypatch):
    monkeypatch.setenv("SERIAL_ENABLED", "true")
    monkeypatch.setenv("SERIAL_PORT", "mock://sine")
    monkeypatch.setenv("SERIAL_BATCH_INTERVAL_MS", "50")
    monkeypatch.setenv("SERIAL_STATS_INTERVAL_MS", "100")
    monkeypatch.setenv("SERIAL_WINDOW_SECONDS", "5")
    monkeypatch.setenv("SERIAL_WINDOW_MAX_POINTS", "128")
    get_settings.cache_clear()

    seen_types: set[str] = set()

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            deadline = time.time() + 3.0
            while time.time() < deadline and seen_types != {"serial_batch", "serial_stats"}:
                message = websocket.receive_json()
                msg_type = message["type"]
                if msg_type == "serial_batch":
                    assert message["points"]
                    seen_types.add(msg_type)
                elif msg_type == "serial_stats":
                    assert "avg" in message
                    seen_types.add(msg_type)

    assert seen_types == {"serial_batch", "serial_stats"}
    get_settings.cache_clear()
