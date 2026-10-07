"""Offline regressions for laser connection waiting and TCP reconnection.

Run with ``python3 -B tools/tests/test_laser_connection_timer.py``.
The actual constructor, connection callbacks, and receive loop are compiled
from each driver copy. ROS, timers, and sockets use in-memory doubles;
this test never imports rclpy, binds a port, or connects to hardware.
"""

import ast
from collections import deque
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DRIVER_PATHS = (
    PROJECT_ROOT / "fishbot_laser_ws/src/ydlidar_ros2/ydlidar/ydlidar_node.py",
    PROJECT_ROOT / "tools/fishbot_laser_patch/ydlidar_node.py",
)


class FakeSocket:
    def __init__(self):
        self.pending = deque()
        self.incoming = deque()
        self.polls = 0
        self.recv_calls = 0
        self.closed = False
        self.blocking = None

    def _check_open(self):
        if self.closed:
            raise OSError(9, "Bad file descriptor")

    def accept(self):
        self._check_open()
        self.polls += 1
        if not self.pending:
            raise BlockingIOError()
        return self.pending.popleft(), ("127.0.0.1", 12345)

    def recvfrom(self, _size):
        self._check_open()
        self.polls += 1
        if not self.pending:
            raise BlockingIOError()
        return self.pending.popleft(), ("127.0.0.1", 12345)

    def recv(self, size):
        self._check_open()
        self.recv_calls += 1
        if not self.incoming:
            raise BlockingIOError()
        result = self.incoming.popleft()
        if isinstance(result, BaseException):
            raise result
        if len(result) > size:
            self.incoming.appendleft(result[size:])
        return result[:size]

    def setblocking(self, blocking):
        self.blocking = blocking

    def close(self):
        self.closed = True

    def fileno(self):
        return -1 if self.closed else 100


class FakeClock:
    def __init__(self):
        self.monotonic_value = 100.0
        self.wall_value = 1000.0

    def time(self):
        return self.wall_value

    def monotonic(self):
        return self.monotonic_value

    def advance(self, seconds):
        self.monotonic_value += seconds
        self.wall_value += seconds


class FakeTimer:
    def __init__(self, period, callback):
        self.period = period
        self.callback = callback
        self.cancelled = False
        self.reset_count = 0

    def cancel(self):
        self.cancelled = True

    def reset(self):
        self.reset_count += 1
        self.cancelled = False


class FakeParser:
    def __init__(self):
        self.data_buffer = bytearray()
        self.scan_data_buffer = []

    def set_scan_params(self, *args):
        self.params = args

    def add_scan_callback(self, callback):
        self.callback = callback


class FakeNode:
    protocol_override = "net"

    def __init__(self, _name):
        self.parameters = {}
        self.timers = []
        self.messages = []
        self.parsed_frames = []

    def declare_parameter(self, name, value):
        self.parameters[name] = self.protocol_override if name == "protocol" else value

    def get_parameter(self, name):
        return SimpleNamespace(value=self.parameters[name])

    def create_timer(self, period, callback):
        timer = FakeTimer(period, callback)
        self.timers.append(timer)
        return timer

    def create_publisher(self, *_args):
        return SimpleNamespace()

    def get_clock(self):
        return SimpleNamespace(now=lambda: SimpleNamespace(
            nanoseconds=int(self.clock.monotonic() * 1e9)))

    def get_logger(self):
        return SimpleNamespace(info=self.messages.append, warning=self.messages.append,
                               warn=self.messages.append, error=self.messages.append)

    def _init_tcp(self):
        self.tcp_sock = FakeSocket()
        self.conn = None

    def _init_udp(self):
        self.udp_sock = FakeSocket()

    def _init_serial(self):
        self.protocol_mode = "serial"

    def parse_frame(self, frame):
        self.parsed_frames.append(bytes(frame))

    def _handle_m1c1_scan(self, _scan):
        pass


def load_driver(path, protocol="net", source=None):
    """Load real control flow, without executing the module's ROS imports."""
    tree = ast.parse(path.read_text() if source is None else source, filename=str(path))
    lidar_type = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                      and node.name == "LidarType")
    driver = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                  and node.name == "FishBotLaserDriverNode")
    driver.body = [node for node in driver.body if isinstance(node, ast.FunctionDef)
                   and node.name in {"__init__", "_accept_connection", "process_data",
                                     "_reset_parsers", "_reset_tcp_connection"}]
    clock = FakeClock()
    fake_base = type("ConfiguredFakeNode", (FakeNode,),
                     {"protocol_override": protocol, "clock": clock})
    namespace = {
        "Node": fake_base,
        "Enum": Enum,
        "time": clock,
        "LaserScan": lambda: SimpleNamespace(header=SimpleNamespace()),
        "LidarX2Parser": FakeParser,
        "LidarM1C1Parser": FakeParser,
        "LidarX2NParser": FakeParser,
        "LidarX2KParser": FakeParser,
    }
    module = ast.Module(body=[lidar_type, driver], type_ignores=[])
    exec(compile(module, str(path), "exec"), namespace)
    return namespace["FishBotLaserDriverNode"]()


class ConnectionTimerTests(unittest.TestCase):
    parser_names = ("laser_x2_parser", "laser_m1c1_parser",
                    "laser_x2n_parser", "laser_x2k_parser")

    def connect_tcp(self, node):
        connection = FakeSocket()
        node.tcp_sock.pending.append(connection)
        node._accept_connection()
        self.assertIs(node.conn, connection)
        return connection

    def assert_waiting(self, node, old_connection, listener, timers):
        self.assertTrue(old_connection.closed)
        self.assertIsNone(node.conn)
        self.assertIsNone(node.protocol_mode)
        self.assertIs(node.tcp_sock, listener)
        self.assertFalse(listener.closed)
        self.assertFalse(node.connection_timer.cancelled)
        self.assertEqual(tuple(node.timers), timers)

    def test_initialization_creates_one_connection_timer_without_polling(self):
        for path in DRIVER_PATHS:
            with self.subTest(driver=path.relative_to(PROJECT_ROOT)):
                node = load_driver(path)
                poll_timers = [timer for timer in node.timers
                               if timer.callback.__name__ == "_accept_connection"]
                self.assertEqual(len(poll_timers), 1)
                self.assertIs(node.connection_timer, poll_timers[0])
                self.assertEqual(node.tcp_sock.polls, 0)
                self.assertEqual(node.udp_sock.polls, 0)
                self.assertFalse(node.connection_timer.cancelled)

    def test_repeated_empty_polls_do_not_allocate_timers(self):
        for path in DRIVER_PATHS:
            with self.subTest(driver=path.relative_to(PROJECT_ROOT)):
                node = load_driver(path)
                initial_timers = tuple(node.timers)
                for _ in range(1000):
                    node._accept_connection()
                self.assertEqual(tuple(node.timers), initial_timers)
                self.assertIsNone(node.protocol_mode)
                self.assertFalse(node.connection_timer.cancelled)

    def test_tcp_connection_cancels_polling_and_keeps_nonblocking_socket(self):
        for path in DRIVER_PATHS:
            with self.subTest(driver=path.relative_to(PROJECT_ROOT)):
                node = load_driver(path)
                accepted = FakeSocket()
                node.tcp_sock.pending.append(accepted)
                initial_timers = tuple(node.timers)
                node._accept_connection()
                self.assertEqual(node.protocol_mode, "tcp")
                self.assertIs(node.conn, accepted)
                self.assertFalse(accepted.blocking)
                self.assertTrue(node.connection_timer.cancelled)
                self.assertTrue(node.udp_sock.closed)
                self.assertEqual(tuple(node.timers), initial_timers)

    def test_udp_connection_cancels_polling_and_preserves_first_datagram(self):
        for path in DRIVER_PATHS:
            with self.subTest(driver=path.relative_to(PROJECT_ROOT)):
                node = load_driver(path)
                first_datagram = b"\xaa\x55\x99\x01"
                node.udp_sock.pending.append(first_datagram)
                initial_timers = tuple(node.timers)
                node._accept_connection()
                self.assertEqual(node.protocol_mode, "udp")
                self.assertEqual(node.data_buffer, first_datagram)
                self.assertTrue(node.connection_timer.cancelled)
                self.assertTrue(node.tcp_sock.closed)
                self.assertEqual(tuple(node.timers), initial_timers)

    def test_already_selected_protocol_does_not_poll_or_recreate_timer(self):
        for path in DRIVER_PATHS:
            for protocol in ("tcp", "udp"):
                with self.subTest(driver=path.relative_to(PROJECT_ROOT), protocol=protocol):
                    node = load_driver(path)
                    node.protocol_mode = protocol
                    initial_timers = tuple(node.timers)
                    for _ in range(20):
                        node._accept_connection()
                    self.assertEqual(node.tcp_sock.polls, 0)
                    self.assertEqual(node.udp_sock.polls, 0)
                    self.assertTrue(node.connection_timer.cancelled)
                    self.assertEqual(tuple(node.timers), initial_timers)

    def test_serial_mode_does_not_create_network_polling_timer(self):
        for path in DRIVER_PATHS:
            with self.subTest(driver=path.relative_to(PROJECT_ROOT)):
                node = load_driver(path, protocol="serial")
                self.assertIsNone(node.connection_timer)
                self.assertEqual(node.protocol_mode, "serial")
                self.assertFalse(any(timer.callback.__name__ == "_accept_connection"
                                     for timer in node.timers))
                node._accept_connection()

    def test_tcp_eof_discards_old_bytes_and_rebuilds_parser_state(self):
        for path in DRIVER_PATHS:
            with self.subTest(driver=path.relative_to(PROJECT_ROOT)):
                node = load_driver(path)
                old_connection = self.connect_tcp(node)
                old_udp = node.udp_sock
                listener, timers = node.tcp_sock, tuple(node.timers)
                old_parsers = [getattr(node, name) for name in self.parser_names]
                for parser in old_parsers:
                    parser.data_buffer.extend(b"old partial bytes")
                    parser.scan_data_buffer.append("old partial revolution")
                # Two headers would reach parse_frame if reset did not return.
                node.data_buffer.extend(b"\xaa\x55old\xaa\x55tail")
                node.full_scan_buffer.append("old scan")
                node.laser_type = type(node.laser_type).LIDAR_TYPE_X2
                node.is_receive_laser_type = True
                node.rate, node.scan_count, node.last_report_count = 7.0, 120, 110
                node.clock.advance(3.0)
                old_connection.incoming.append(b"")

                node.process_data()

                self.assert_waiting(node, old_connection, listener, timers)
                self.assertFalse(node.data_buffer)
                self.assertFalse(node.full_scan_buffer)
                self.assertFalse(node.parsed_frames)
                self.assertEqual(node.laser_type.value, 0)
                self.assertFalse(node.is_receive_laser_type)
                self.assertEqual((node.rate, node.scan_count, node.last_report_count),
                                 (0, 0, 0))
                self.assertEqual(node.last_report_time.nanoseconds,
                                 int(node.clock.monotonic() * 1e9))
                for name, old_parser in zip(self.parser_names, old_parsers):
                    parser = getattr(node, name)
                    self.assertIsNot(parser, old_parser)
                    self.assertFalse(parser.data_buffer)
                    self.assertFalse(parser.scan_data_buffer)
                    self.assertEqual(parser.callback, node._handle_m1c1_scan)
                self.assertEqual(node.laser_m1c1_parser.params[:3],
                                 (node.parameters["frame_id"], node.parameters["min_range"],
                                  node.parameters["max_range"]))
                self.assertTrue(old_udp.closed)
                self.assertIsNot(node.udp_sock, old_udp)
                self.assertFalse(node.udp_sock.closed)
                # Polling again must not hit the already closed UDP descriptor.
                node._accept_connection()

    def test_tcp_connection_reset_and_other_socket_errors_resume_polling(self):
        for path in DRIVER_PATHS:
            for error in (ConnectionResetError("peer reset"),
                          ConnectionAbortedError("peer aborted"),
                          OSError(5, "simulated socket failure")):
                with self.subTest(driver=path.relative_to(PROJECT_ROOT), error=type(error)):
                    node = load_driver(path)
                    connection = self.connect_tcp(node)
                    listener, timers = node.tcp_sock, tuple(node.timers)
                    connection.incoming.append(error)
                    node.process_data()
                    self.assert_waiting(node, connection, listener, timers)

    def test_idle_timeout_uses_monotonic_clock_and_exact_two_second_boundary(self):
        for path in DRIVER_PATHS:
            with self.subTest(driver=path.relative_to(PROJECT_ROOT)):
                node = load_driver(path)
                connection = self.connect_tcp(node)
                listener, timers = node.tcp_sock, tuple(node.timers)
                started = node.clock.monotonic()
                node.clock.monotonic_value = started + 1.99
                node.clock.wall_value += 3600.0
                node.process_data()
                self.assertIs(node.conn, connection)
                self.assertTrue(node.connection_timer.cancelled)
                node.clock.monotonic_value = started + 2.0
                node.clock.wall_value -= 7200.0
                node.process_data()
                self.assert_waiting(node, connection, listener, timers)

    def test_available_bytes_refresh_timeout_before_idle_check(self):
        for path in DRIVER_PATHS:
            with self.subTest(driver=path.relative_to(PROJECT_ROOT)):
                node = load_driver(path)
                connection = self.connect_tcp(node)
                node.clock.advance(5.0)
                # Data is already queued when the delayed callback finally runs.
                connection.incoming.append(b"\xaa\x55fresh\xaa\x55")
                node.process_data()
                self.assertIs(node.conn, connection)
                self.assertFalse(connection.closed)
                self.assertEqual(node.last_rx_monotonic, node.clock.monotonic())
                self.assertEqual(node.parsed_frames, [b"\xaa\x55fresh"])
                node.clock.advance(1.99)
                node.process_data()
                self.assertIs(node.conn, connection)

    def test_pending_new_connection_survives_reset_and_gets_full_idle_window(self):
        for path in DRIVER_PATHS:
            with self.subTest(driver=path.relative_to(PROJECT_ROOT)):
                node = load_driver(path)
                connection = self.connect_tcp(node)
                listener, timers = node.tcp_sock, tuple(node.timers)
                replacement = FakeSocket()
                replacement.incoming.append(b"\xaa\x55new\xaa\x55")
                listener.pending.append(replacement)
                node.clock.advance(2.0)
                node.process_data()
                self.assert_waiting(node, connection, listener, timers)
                node.clock.advance(10.0)
                node.connection_timer.callback()
                self.assertIs(node.conn, replacement)
                self.assertFalse(replacement.blocking)
                self.assertEqual(node.last_rx_monotonic, node.clock.monotonic())
                self.assertTrue(node.connection_timer.cancelled)
                node.process_data()
                self.assertEqual(node.parsed_frames, [b"\xaa\x55new"])
                node.clock.advance(1.99)
                node.process_data()
                self.assertIs(node.conn, replacement)

    def test_one_hundred_reconnections_reuse_timer_and_listener(self):
        for path in DRIVER_PATHS:
            with self.subTest(driver=path.relative_to(PROJECT_ROOT)):
                node = load_driver(path)
                listener, timers = node.tcp_sock, tuple(node.timers)
                connection_timer = node.connection_timer
                for _ in range(100):
                    connection = self.connect_tcp(node)
                    connection.incoming.append(b"")
                    node.process_data()
                    self.assert_waiting(node, connection, listener, timers)
                self.assertIs(node.connection_timer, connection_timer)
                self.assertEqual(connection_timer.reset_count, 100)

    def test_no_connection_does_not_repeat_reset_or_parse_stale_data(self):
        for path in DRIVER_PATHS:
            with self.subTest(driver=path.relative_to(PROJECT_ROOT)):
                node = load_driver(path)
                connection = self.connect_tcp(node)
                connection.incoming.append(b"")
                node.process_data()
                reset_count = node.connection_timer.reset_count
                for _ in range(100):
                    node.process_data()
                self.assertEqual(node.connection_timer.reset_count, reset_count)
                self.assertFalse(node.parsed_frames)

    def test_udp_can_be_selected_after_tcp_disconnect(self):
        for path in DRIVER_PATHS:
            with self.subTest(driver=path.relative_to(PROJECT_ROOT)):
                node = load_driver(path)
                connection = self.connect_tcp(node)
                connection.incoming.append(b"")
                node.process_data()
                datagram = b"\xaa\x55\x99\x01"
                node.udp_sock.pending.append(datagram)
                node._accept_connection()
                self.assertEqual(node.protocol_mode, "udp")
                self.assertEqual(node.data_buffer, datagram)
                self.assertTrue(node.connection_timer.cancelled)


if __name__ == "__main__":
    unittest.main(verbosity=2)
