"""RViz launch/API boundaries; native rendering is verified separately."""
import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from mission_bridge import Handler, LocalHTTPServer
from rviz_desktop import PackageNotFoundError, RvizDesktop, RvizDesktopError


class DesktopFixture(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.prefix, self.share = root / 'prefix', root / 'share'
        self.executable = self.prefix / 'lib/rviz2/rviz2'
        self.config = self.share / 'config/simulation.rviz'
        for path in (self.executable, self.config):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture')
        self.desktop = 'DISPLAY=:0\nWAYLAND_DISPLAY=\nUNRELATED=value\n'
        self.active, self.pid = False, 0
        self.commands = []

    def launcher(self, domain=107):
        with patch('rviz_desktop.get_package_prefix', return_value=str(self.prefix)), \
                patch('rviz_desktop.get_package_share_directory', return_value=str(self.share)):
            launcher = RvizDesktop(domain)
        launcher.run = self.runner
        return launcher

    def runner(self, command):
        self.commands.append(command)
        if command[:3] == ['systemctl', '--user', 'show-environment']:
            return subprocess.CompletedProcess(command, 0, self.desktop, '')
        if command[:3] == ['systemctl', '--user', 'show']:
            text = f'ActiveState={"active" if self.active else "inactive"}\nMainPID={self.pid}\n'
            return subprocess.CompletedProcess(command, 0, text, '')
        if command[0] == 'systemd-run':
            self.active, self.pid = True, 43210
            return subprocess.CompletedProcess(command, 0, '', '')
        self.fail(f'Unexpected external operation: {command!r}')


class RvizLaunchTests(DesktopFixture):
    def test_server_domain_cannot_be_nonisolated_or_user_command(self):
        for domain in (0, 233, -1, True, '107', '107;touch /tmp/x', None):
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                self.launcher(domain)

    def test_absent_package_is_optional_and_open_is_explicitly_unavailable(self):
        with patch('rviz_desktop.get_package_prefix', side_effect=PackageNotFoundError('rviz2')):
            launcher = RvizDesktop(107)
        launcher.run = self.runner
        state = launcher.status()
        self.assertFalse(state['available'])
        self.assertFalse(state['running'])
        with self.assertRaises(RvizDesktopError) as caught:
            launcher.open()
        self.assertEqual(caught.exception.status, 503)
        self.assertFalse(any(command[0] == 'systemd-run' for command in self.commands))

    def test_missing_view_config_cannot_launch_a_default_or_other_domain_view(self):
        self.config.unlink()
        launcher = self.launcher()
        with self.assertRaises(RvizDesktopError) as caught:
            launcher.open()
        self.assertEqual(caught.exception.status, 503)
        self.assertFalse(any(command[0] == 'systemd-run' for command in self.commands))

    def test_missing_desktop_cannot_launch_and_reports_why(self):
        self.desktop = 'PATH=/usr/bin\nDISPLAY=\nWAYLAND_DISPLAY=\n'
        launcher = self.launcher()
        self.assertFalse(launcher.status()['available'])
        with self.assertRaises(RvizDesktopError) as caught:
            launcher.open()
        self.assertEqual(caught.exception.status, 503)
        self.assertIn('桌面显示', str(caught.exception))
        self.assertFalse(any(command[0] == 'systemd-run' for command in self.commands))

    def test_manager_failure_does_not_guess_desktop_from_parent_environment(self):
        launcher = self.launcher()
        launcher.run = lambda command: subprocess.CompletedProcess(command, 1, '', 'no bus')
        with patch.dict('rviz_desktop.os.environ', {'DISPLAY': ':0'}):
            state = launcher.status()
        self.assertFalse(state['available'])
        self.assertIn('桌面会话', state['message'])

    def test_existing_same_domain_pid_is_reused_without_another_launch(self):
        self.active, self.pid = True, 43210
        launcher = self.launcher()
        status, result = launcher.open()
        self.assertEqual(status, 200)
        self.assertEqual(result['pid'], 43210)
        self.assertEqual(result['domain'], 107)
        unit_queries = [command for command in self.commands if command[:3] == ['systemctl', '--user', 'show']]
        self.assertEqual(unit_queries[0][3], 'fishbot-rviz-domain-107.service')
        self.assertFalse(any(command[0] == 'systemd-run' for command in self.commands))

    def test_fixed_native_command_keeps_domain_and_localhost_isolation(self):
        launcher = self.launcher()
        with patch.dict('rviz_desktop.os.environ', {'ROS_DOMAIN_ID': '0', 'ROS_STATIC_PEERS': 'remote',
                'DISPLAY': ':999', 'PATH': '/fixed/path', 'LD_LIBRARY_PATH': '/fixed/lib'}, clear=True):
            status, result = launcher.open()
        self.assertEqual(status, 202)
        self.assertTrue(result['running'])
        launched = [command for command in self.commands if command[0] == 'systemd-run']
        self.assertEqual(len(launched), 1)
        command = launched[0]
        self.assertIn('--unit=fishbot-rviz-domain-107.service', command)
        self.assertIn('--setenv=ROS_DOMAIN_ID=107', command)
        self.assertIn('--setenv=ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST', command)
        self.assertIn('--setenv=ROS_LOCALHOST_ONLY=1', command)
        self.assertIn('--setenv=ROS_STATIC_PEERS=', command)
        self.assertNotIn('--setenv=ROS_DOMAIN_ID=0', command)
        self.assertNotIn('--setenv=ROS_STATIC_PEERS=remote', command)
        self.assertNotIn('--setenv=DISPLAY=:999', command)
        self.assertEqual(command[command.index(str(self.executable)):],
            [str(self.executable), '-d', str(self.config), '--ros-args', '-p',
             'use_sim_time:=true', '-r', '__node:=fishbot_rviz_107'])

    def test_simultaneous_clicks_launch_once_and_return_the_same_pid(self):
        launcher = self.launcher()
        barrier = threading.Barrier(2)
        def click():
            barrier.wait(timeout=2)
            return launcher.open()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(click) for _ in range(2)]
            results = [future.result(timeout=3) for future in futures]
        self.assertEqual(sorted(status for status, _ in results), [200, 202])
        self.assertEqual({result['pid'] for _, result in results}, {43210})
        self.assertEqual(sum(command[0] == 'systemd-run' for command in self.commands), 1)

    def test_timeout_is_unknown_and_does_not_automatically_launch_again(self):
        launcher = self.launcher()
        def timeout_runner(command):
            if command[0] == 'systemd-run':
                self.commands.append(command)
                self.active, self.pid = True, 43210
                raise subprocess.TimeoutExpired(command, 2)
            return self.runner(command)
        launcher.run = timeout_runner
        with self.assertRaises(RvizDesktopError) as caught:
            launcher.open()
        self.assertEqual(caught.exception.status, 504)
        self.assertIn('回执未知', str(caught.exception))
        self.assertTrue(launcher.status()['running'])
        self.assertEqual(launcher.open()[0], 200)
        self.assertEqual(sum(command[0] == 'systemd-run' for command in self.commands), 1)

    def test_early_process_exit_never_claims_the_window_is_running(self):
        launcher = self.launcher()
        def early_exit(command):
            if command[0] == 'systemd-run':
                self.commands.append(command)
                return subprocess.CompletedProcess(command, 0, '', '')
            return self.runner(command)
        launcher.run = early_exit
        with self.assertRaises(RvizDesktopError) as caught:
            launcher.open()
        self.assertEqual(caught.exception.status, 504)
        self.assertFalse(launcher.status()['running'])

    def test_rejected_launch_is_not_success_without_a_confirmed_process(self):
        launcher = self.launcher()
        def rejected(command):
            if command[0] == 'systemd-run':
                return subprocess.CompletedProcess(command, 1, '', 'failed')
            return self.runner(command)
        launcher.run = rejected
        with self.assertRaises(RvizDesktopError) as caught:
            launcher.open()
        self.assertEqual(caught.exception.status, 503)

    def test_other_request_winning_systemd_singleton_race_is_reconciled(self):
        launcher = self.launcher()
        def raced(command):
            if command[0] == 'systemd-run':
                self.active, self.pid = True, 43210
                return subprocess.CompletedProcess(command, 1, '', 'unit already exists')
            return self.runner(command)
        launcher.run = raced
        status, result = launcher.open()
        self.assertEqual(status, 200)
        self.assertTrue(result['running'])
        self.assertEqual(result['pid'], 43210)

    def test_all_subprocess_queries_are_bounded_and_never_use_a_shell(self):
        launcher = self.launcher()
        # Exercise the actual adapter instead of the fixture runner.
        del launcher.run
        with patch('rviz_desktop.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            launcher.run(['systemctl', '--user', 'show-environment'])
        self.assertEqual(run.call_args.kwargs['timeout'], 2)
        self.assertFalse(run.call_args.kwargs['check'])
        self.assertNotIn('shell', run.call_args.kwargs)


class RvizHTTPTests(unittest.TestCase):
    def harness(self, body=b'{}', headers=None, path='/sim-api/rviz'):
        replies = []
        bridge = SimpleNamespace(enqueue=Mock(side_effect=AssertionError('RViz must not dispatch navigation')))
        rviz = SimpleNamespace(status=Mock(return_value={'available': True, 'running': False, 'domain': 107}),
            open=Mock(return_value=(202, {'available': True, 'running': True, 'domain': 107, 'pid': 43210})))
        handler = SimpleNamespace(path=path, server=SimpleNamespace(port=9079, ui_ports={5179},
            bridge=bridge, rviz=rviz), headers={'Host': '127.0.0.1:9079',
            'Origin': 'http://127.0.0.1:5179', 'Content-Type': 'application/json',
            'Content-Length': str(len(body)), **(headers or {})}, rfile=io.BytesIO(body),
            reply=lambda status, response: replies.append((status, response)))
        handler.allowed = MethodType(Handler.allowed, handler)
        return handler, replies

    def test_get_returns_native_state_without_launch_or_navigation(self):
        handler, replies = self.harness()
        Handler.do_GET(handler)
        self.assertEqual(replies[0][0], 200)
        self.assertEqual(replies[0][1]['domain'], 107)
        handler.server.rviz.open.assert_not_called()
        handler.server.bridge.enqueue.assert_not_called()

    def test_explicit_empty_object_opens_native_window_without_ros_action_queue(self):
        handler, replies = self.harness()
        Handler.do_POST(handler)
        self.assertEqual(replies[0][0], 202)
        handler.server.rviz.open.assert_called_once_with()
        handler.server.bridge.enqueue.assert_not_called()

    def test_command_path_and_domain_injection_are_rejected_before_launch(self):
        for body in ({'command': 'touch /tmp/injected'}, {'path': '/tmp/other.rviz'},
                     {'domain': 0}, {'ROS_DOMAIN_ID': 0}, {'args': ['-r', '/cmd_vel:=/evil']},
                     {'ignored': False}):
            with self.subTest(body=body):
                handler, replies = self.harness(json.dumps(body).encode())
                Handler.do_POST(handler)
                self.assertEqual(replies[0][0], 400)
                handler.server.rviz.open.assert_not_called()
                handler.server.bridge.enqueue.assert_not_called()

    def test_existing_host_and_origin_restrictions_apply_to_both_rviz_methods(self):
        for headers in ({'Host': 'evil.example:9079'}, {'Host': '192.168.0.1:9079'},
                        {'Origin': 'http://evil.example:5179'}, {'Origin': 'http://127.0.0.1:5180'},
                        {'Origin': 'http://user@127.0.0.1:5179'}, {'Origin': 'http://127.0.0.1:5179/path'},
                        {'Origin': 'http://127.0.0.1:5179?x=1'}):
            for method in (Handler.do_GET, Handler.do_POST):
                with self.subTest(headers=headers, method=method.__name__):
                    handler, replies = self.harness(headers=headers)
                    method(handler)
                    self.assertEqual(replies[0][0], 403)
                    handler.server.rviz.open.assert_not_called()
                    handler.server.rviz.status.assert_not_called()
                    handler.server.bridge.enqueue.assert_not_called()

    def test_non_json_empty_or_invalid_json_never_launches(self):
        cases = [(b'{}', {'Content-Type': 'text/plain'}, 415),
                 (b'', {}, 413), (b'{}', {'Content-Length': '-1'}, 413),
                 (b'{}', {'Content-Length': '8193'}, 413),
                 (b'[]', {}, 400), (b'null', {}, 400), (b'{', {}, 400),
                 (b'\xff\xff', {}, 400)]
        for body, headers, expected in cases:
            with self.subTest(body=body, headers=headers):
                handler, replies = self.harness(body, headers)
                Handler.do_POST(handler)
                self.assertEqual(replies[0][0], expected)
                handler.server.rviz.open.assert_not_called()
                handler.server.bridge.enqueue.assert_not_called()

    def test_unknown_and_unavailable_launch_statuses_are_preserved(self):
        for status in (503, 504):
            with self.subTest(status=status):
                handler, replies = self.harness()
                handler.server.rviz.open.side_effect = RvizDesktopError('native state unknown', status)
                Handler.do_POST(handler)
                self.assertEqual(replies[0], (status, {'error': 'native state unknown'}))
                handler.server.rviz.open.assert_called_once_with()
                handler.server.bridge.enqueue.assert_not_called()

    def test_optional_rviz_unavailability_does_not_block_existing_mission_queue(self):
        handler, replies = self.harness(path='/sim-api/mission')
        future = Future()
        future.set_result((202, {'id': 'existing-mission'}))
        handler.server.bridge.enqueue = Mock(return_value=future)
        handler.server.rviz.open.side_effect = RvizDesktopError('No desktop')
        Handler.do_POST(handler)
        self.assertEqual(replies[0], (202, {'id': 'existing-mission'}))
        handler.server.bridge.enqueue.assert_called_once_with('mission', {})
        handler.server.rviz.open.assert_not_called()
        handler.server.rviz.status.assert_not_called()

    def test_server_owns_launcher_domain_and_remains_loopback_bound(self):
        bridge = SimpleNamespace(domain=107)
        with patch('mission_bridge.RvizDesktop') as desktop:
            server = LocalHTTPServer(0, bridge, ui_port=5179)
            try:
                desktop.assert_called_once_with(107)
                self.assertEqual(server.server_address[0], '127.0.0.1')
                self.assertIn(5179, server.ui_ports)
                self.assertIs(server.bridge, bridge)
            finally:
                server.server_close()


if __name__ == '__main__':
    unittest.main()
