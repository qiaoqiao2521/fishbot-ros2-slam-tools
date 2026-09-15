"""Execute real methods with isolated dependencies; never instantiate hardware runtimes."""
import ast
import io
import json
import math
from pathlib import Path
import time
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]


def extract(path, name, scope=None):
    tree = ast.parse((ROOT / path).read_text())
    nodes = tree.body
    if scope:
        nodes = next(n for n in nodes if isinstance(n, ast.ClassDef) and n.name == scope).body
    fn = next(n for n in nodes if isinstance(n, ast.FunctionDef) and n.name == name)
    fn.decorator_list = []
    namespace = {'time': time, 'math': math, 'json': json}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name], namespace


class ReviewSafety(unittest.TestCase):
    demo = 'projects/so101-win7-follower-demo/mint_follower_demo/app.py'
    drive = 'projects/robot_base/robot_base/robot_base/drive_node.py'

    def test_missing_session_is_not_admin(self):
        method, ns = extract(self.demo, '_session', 'Handler')
        ns['login_session_from_token'] = lambda token: None
        self.assertIsNone(method(types.SimpleNamespace(headers={})))

    def test_all_post_operations_require_login(self):
        method, ns = extract(self.demo, 'do_POST', 'Handler')
        ns['unquote'] = lambda p: p
        for path in ('connect', 'stop', 'rviz-sync/start', 'gz-debug/start', 'mode', 'action'):
            handler = types.SimpleNamespace(path='/api/' + path, _require_login=lambda: None,
                                            _read_body=Mock(side_effect=AssertionError('read before authorization')))
            method(handler)
            handler._read_body.assert_not_called()

    def test_request_body_limits_and_object_shape(self):
        method, ns = extract(self.demo, '_read_body', 'Handler')
        ns['MAX_BODY_BYTES'] = 1024
        for headers, raw in (({'Content-Length': '1025'}, b''),
                             ({'Content-Length': '-1'}, b''),
                             ({'Transfer-Encoding': 'chunked'}, b''),
                             ({'Content-Length': '2'}, b'[]')):
            with self.assertRaises(ValueError):
                method(types.SimpleNamespace(headers=headers, rfile=io.BytesIO(raw)))

    def test_credentials_fail_closed_for_both_roles(self):
        method, ns = extract(self.demo, 'login_from_payload')
        import re
        ns.update(re=re, normalize_login_role=lambda r: r, ADMIN_USERNAME='admin',
                  ADMIN_PASSWORD='', OPERATOR_PASSWORD='')
        for role in ('admin', 'employee'):
            with self.assertRaises(ValueError):
                method({'role': role, 'operator': 'admin', 'password': '1234'}, '')

    def test_expired_session_rejected(self):
        method, ns = extract(self.demo, 'login_session_from_token')
        ns.update(LOGIN_SESSIONS={'t': {'created_ms': 0}}, now_ms=lambda: 9 * 3600 * 1000)
        self.assertIsNone(method('t'))
        self.assertEqual(ns['LOGIN_SESSIONS'], {})

    def test_stale_command_sends_zero_pwm(self):
        method, _ = extract(self.drive, 'check_command_timeout', 'RobotDriveNode')
        node = types.SimpleNamespace(last_cmd_time=time.monotonic() - 1, cmd_timeout=0.5,
                                     cmd_vx=1, cmd_vy=1, cmd_wz=1, send_motor_cmd=Mock())
        method(node)
        node.send_motor_cmd.assert_called_once_with(0, 0, 0, 0)
        self.assertEqual((node.cmd_vx, node.cmd_vy, node.cmd_wz), (0, 0, 0))

    def test_fresh_command_not_stopped(self):
        method, _ = extract(self.drive, 'check_command_timeout', 'RobotDriveNode')
        node = types.SimpleNamespace(last_cmd_time=time.monotonic(), cmd_timeout=0.5, send_motor_cmd=Mock())
        method(node)
        node.send_motor_cmd.assert_not_called()

    def test_nan_command_stops_instead_of_reaching_pwm(self):
        method, _ = extract(self.drive, 'cmd_vel_callback', 'RobotDriveNode')
        node = types.SimpleNamespace(send_motor_cmd=Mock())
        msg = types.SimpleNamespace(linear=types.SimpleNamespace(x=float('nan'), y=0),
                                    angular=types.SimpleNamespace(z=0))
        method(node, msg)
        node.send_motor_cmd.assert_called_once_with(0, 0, 0, 0)

    def test_teleop_repeats_identical_commands(self):
        method, ns = extract('tools/fishbot_arrow_teleop.py', 'publish', 'ArrowTeleop')
        ns['Twist'] = lambda: types.SimpleNamespace(linear=types.SimpleNamespace(), angular=types.SimpleNamespace())
        node = types.SimpleNamespace(linear_x=0.1, angular_z=0.0, last_sent=(0.1, 0.0), pub=Mock())
        method(node)
        method(node)
        self.assertEqual(node.pub.publish.call_count, 2)

    def test_timed_teleop_sigterm_sends_zero_before_shutdown(self):
        import argparse
        import signal
        method, ns = extract('tools/fishbot_timed_cmd_vel.py', 'main')
        handlers = {}
        def install(sig, handler):
            previous = handlers.get(sig)
            handlers[sig] = handler
            return previous
        node = types.SimpleNamespace(done=False, deadline=999, destroy_node=Mock())
        published = []
        node.publish_once = lambda: published.append(node.deadline)
        ros = Mock()
        ros.ok.return_value = True
        ros.spin_once.side_effect = lambda *a, **kw: handlers[signal.SIGTERM](signal.SIGTERM, None)
        ns.update(argparse=argparse, rclpy=ros, TimedCmdVel=lambda *a: node,
                  signal=types.SimpleNamespace(signal=install, SIGINT=signal.SIGINT, SIGTERM=signal.SIGTERM),
                  time=types.SimpleNamespace(sleep=lambda _: None))
        signals = types.ModuleType('rclpy.signals')
        signals.SignalHandlerOptions = types.SimpleNamespace(NO=0)
        with patch.dict('sys.modules', {'rclpy.signals': signals}), patch('sys.argv', ['timed']):
            self.assertEqual(method(), 0)
        self.assertEqual(published, [0.0, 0.0, 0.0])
        node.destroy_node.assert_called_once()
        ros.shutdown.assert_called_once()


if __name__ == '__main__':
    unittest.main()
