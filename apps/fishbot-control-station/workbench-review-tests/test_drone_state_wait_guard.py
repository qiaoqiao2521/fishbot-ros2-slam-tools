"""Expired cached PVA during a pending state read: real methods, fake control."""
import asyncio
import copy
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from pathlib import Path
import tempfile
import unittest

from test_drone_command_revalidation_patch import REPAIR, apply, copy_source
from test_drone_recovery_cache_chain import RecoveryHarness, ReturnHome
import test_drone_command_validity as original


class StateWaitGuard(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        copy_source(cls.root)
        apply(cls.root, REPAIR)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def harness(self, enabled=True, response_error=None):
        out = tempfile.TemporaryDirectory()
        self.addCleanup(out.cleanup)
        h = RecoveryHarness(self.root, Path(out.name), trigger='expired')
        h.owner.command_revalidation_enabled = enabled
        h.owner.options['recovery_rpc_timeout_s'] = .01
        pending, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        reads = 0
        async def delayed_read(function, *args, **kwargs):
            nonlocal reads
            if args and args[0] == '/state':
                reads += 1
                if reads == 2:
                    h.note('http.pending.fixture')
                    pending.set()
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        cancelled.set()
                        raise
                    if response_error is not None:
                        raise response_error
                    return copy.deepcopy(h.response)
            return function(*args, **kwargs)
        h.owner.goto.__func__.__globals__['asyncio'].to_thread = delayed_read
        return h, pending, release, cancelled

    async def test_expired_cache_enters_recovery_without_waiting_for_http_response(self):
        h, pending, release, cancelled = self.harness()
        task = asyncio.create_task(h.run())
        try:
            await asyncio.wait_for(pending.wait(), 1.)
            self.assertEqual(h.cache['mode'], 'pva')
            h.advance(10.4)  # sample age .25 but curve end + .2: existing source expiry.
            await asyncio.wait_for(asyncio.shield(task), .2)
            self.assertTrue(cancelled.is_set())
            self.assertEqual(h.owner.status, 'failed')
            self.assertEqual(h.rows('http.pending.fixture')[0]['cache']['mode'], 'pva')
            stop = next(row for row in h.rows('http') if row['path'] == '/stop')
            self.assertEqual(stop['cache']['mode'], 'position')
            self.assertEqual(len(h.rows('pva.return')), 1)
            self.assertFalse(h.owner.report.get('landed', False))
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def finish_after_pending(self, change, reason):
        h, pending, release, cancelled = self.harness()
        task = asyncio.create_task(h.run())
        try:
            await asyncio.wait_for(pending.wait(), 1.)
            change(h, release)
            await asyncio.wait_for(asyncio.shield(task), .5)
            self.assertEqual(h.owner.status, 'failed')
            self.assertIn(reason, h.owner.report['command_wait_failures'][0]['reason'])
            self.assertEqual(h.owner.report['command_wait_failures'][0]['sdk_cache_effect'], 'unknown')
            json.dumps(h.owner.report['command_wait_failures'], allow_nan=False)
            self.assertEqual(len(h.rows('pva.return')), 1)
            self.assertFalse(h.owner.report.get('landed', False))
        finally:
            release.set()
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_pending_read_detects_sample_expiry_and_original_input_faults(self):
        cases = [
            (lambda h, _: h.advance(10.5), 'cached_command_sample_expired'),
            (lambda h, _: setattr(h.owner, 'position_valid', False), 'PX4 本地定位无效'),
            (lambda h, _: setattr(h.owner.scene, 'failure', 'fixture-motion'), '动态障碍驱动失效'),
            (lambda h, _: setattr(h.owner.observer, 'clock_received', 97.), 'simulation_clock_stopped'),
            (lambda h, _: h.advance(10.15, wall=201.), '未在期限内到达'),
        ]
        for change, reason in cases:
            with self.subTest(reason=reason):
                await self.finish_after_pending(change, reason)

    async def test_sample_uses_source_stamp_not_rpc_reference_timestamp(self):
        def later_rpc_timestamp(h, _):
            h.owner.reference['simulation_s'] = 10.49
            h.advance(10.5)
        await self.finish_after_pending(later_rpc_timestamp, 'cached_command_sample_expired')

    async def test_missing_or_nonfinite_source_is_not_filled_with_fresh_default(self):
        for end in (None, float('nan')):
            with self.subTest(end=end):
                def invalid(h, _):
                    h.owner.reference['source_end_sim_s'] = end
                await self.finish_after_pending(invalid, 'cached_command_source_unavailable')

    async def test_cancel_wins_even_when_http_response_completes_in_same_turn(self):
        def cancel_and_complete(h, release):
            h.cancelled = True
            release.set()
        await self.finish_after_pending(cancel_and_complete, 'CancelFlight')

    async def test_numeric_string_source_end_preserves_the_existing_parsed_contract(self):
        h, pending, release, _ = self.harness()
        h.response['setpoint']['source_end_sim_s'] = '10.2'
        task = asyncio.create_task(h.run())
        try:
            await asyncio.wait_for(pending.wait(), 1.)
            self.assertEqual(h.owner.reference['source_end_sim_s'], 10.2)
            await asyncio.sleep(.03)
            self.assertFalse(task.done())
            h.advance(10.4)
            await asyncio.wait_for(asyncio.shield(task), .5)
            self.assertEqual(h.owner.report['command_wait_failures'][0]['reason'], 'cached_command_source_expired')
        finally:
            release.set()
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_terminal_hold_does_not_waive_sample_age(self):
        h, pending, release, cancelled = self.harness()
        h.response['setpoint'].update(position=[5., 0., 1.], velocity=[0.]*3, acceleration=[0.]*3)
        task = asyncio.create_task(h.run())
        try:
            await asyncio.wait_for(pending.wait(), 1.)
            h.advance(10.4)
            await asyncio.sleep(.05)
            self.assertFalse(task.done())  # source-end exception, not an extra grace.
            self.assertFalse(cancelled.is_set())
            h.advance(10.5)
            await asyncio.wait_for(asyncio.shield(task), .5)
            self.assertEqual(h.owner.report['command_wait_failures'][0]['reason'], 'cached_command_sample_expired')
        finally:
            release.set()
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_successful_position_hold_removes_pva_expiry_obligation(self):
        h, pending, release, _ = self.harness()
        task = asyncio.create_task(h.run())
        try:
            await asyncio.wait_for(pending.wait(), 1.)
            await h.owner.setpoint([0., 0., 1.])  # Explicit fixture action by the same owner.
            h.advance(10.5)
            await asyncio.sleep(.05)
            self.assertFalse(task.done())
            self.assertNotIn('command_wait_failures', h.owner.report)
            h.cancelled = True
            await asyncio.wait_for(asyncio.shield(task), .5)
        finally:
            release.set()
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_operator_return_home_propagates_only_when_requested(self):
        for operator in (True, False):
            with self.subTest(operator=operator):
                h, pending, release, _ = self.harness()
                returning = False
                old_check = h.owner.check_operator
                def check():
                    if returning: raise ReturnHome()
                    old_check()
                h.owner.check_operator = check
                with h.sdk_modules():
                    task = asyncio.create_task(h.owner.goto([5., 0., 1.], use_ego=True, operator=operator))
                    try:
                        await asyncio.wait_for(pending.wait(), 1.)
                        returning = True
                        if operator:
                            with self.assertRaises(ReturnHome):
                                await asyncio.wait_for(task, .5)
                        else:
                            await asyncio.sleep(.05)
                            self.assertFalse(task.done())
                            h.advance(10.4)
                            with self.assertRaisesRegex(RuntimeError, 'cached_command_source_expired'):
                                await asyncio.wait_for(task, .5)
                        self.assertEqual(len(h.rows('pva.return')), 1)
                    finally:
                        release.set()
                        if not task.done(): task.cancel()
                        await asyncio.gather(task, return_exceptions=True)

    async def test_http_error_is_retrieved_and_routes_to_original_recovery(self):
        h, pending, release, _ = self.harness(response_error=OSError('fixture-http-failed'))
        task = asyncio.create_task(h.run())
        try:
            await asyncio.wait_for(pending.wait(), 1.)
            release.set()
            await asyncio.wait_for(asyncio.shield(task), .5)
            self.assertEqual(h.owner.report['command_wait_failures'][0]['error_type'], 'OSError')
            self.assertIn('fixture-http-failed', h.owner.report['recovery']['trigger'])
            self.assertEqual(len(h.rows('pva.return')), 1)
        finally:
            release.set()
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_external_task_cancel_reaps_http_await_but_does_not_invent_business_recovery(self):
        h, pending, release, cancelled = self.harness()
        task = asyncio.create_task(h.run())
        try:
            await asyncio.wait_for(pending.wait(), 1.)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(cancelled.is_set())
            self.assertEqual(h.owner.report['command_wait_failures'][0]['error_type'], 'CancelledError')
            self.assertNotIn('recovery', h.owner.report)
            self.assertFalse(h.owner.report.get('landed', False))
        finally:
            release.set()
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_disabled_guard_keeps_original_pending_read(self):
        h, pending, release, _ = self.harness(enabled=False)
        task = asyncio.create_task(h.run())
        try:
            await asyncio.wait_for(pending.wait(), 1.)
            h.advance(10.4)
            await asyncio.sleep(.05)
            self.assertFalse(task.done())
            self.assertNotIn('command_wait_failures', h.owner.report)
        finally:
            task.cancel()
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    async def test_real_http_thread_can_finish_late_without_dispatching_late_pva(self):
        h, _, _, _ = self.harness()
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        client_read_finished = threading.Event()
        reads = 0
        class Handler(BaseHTTPRequestHandler):
            def respond(self, value):
                data = json.dumps(value).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # Fixture response may outlive its cancelled client await.
            def do_GET(self):
                nonlocal reads
                reads += 1
                if reads == 2:
                    entered.set()
                    try:
                        release.wait(2.)
                        self.respond(h.response)
                    finally:
                        finished.set()
                else:
                    self.respond(h.response)
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length', '0')))
                h.note('real_http', path=self.path)
                self.respond({'accepted': True})
            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
        worker.start()
        ns = h.owner.goto.__func__.__globals__
        ns.update(Request=Request, urlopen=urlopen)
        ns['asyncio'].to_thread = asyncio.to_thread
        h.owner.ego_url = f'http://127.0.0.1:{server.server_port}'
        method = original.methods(self.root/'flight.py', 'Flight', ('ego_request',), ns)['ego_request']
        def real_request(path, body=None):
            try:
                return method(h.owner, path, body)
            finally:
                if path == '/state' and entered.is_set():
                    client_read_finished.set()
        h.owner.ego_request = real_request
        task = asyncio.create_task(h.run())
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 1.))
            h.advance(10.4)
            await asyncio.wait_for(asyncio.shield(task), .5)
            self.assertFalse(finished.is_set())  # Cancelling await did not kill the network thread.
            self.assertEqual(h.owner.report['command_wait_failures'][0]['reason'], 'cached_command_source_expired')
            stop = next(row for row in h.rows('real_http') if row['path'] == '/stop')
            self.assertEqual(stop['cache']['mode'], 'position')
            self.assertEqual(len(h.rows('pva.return')), 1)
            self.assertFalse(h.owner.report.get('landed', False))
        finally:
            release.set()
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await asyncio.to_thread(server.shutdown)
            server.server_close()
            await asyncio.to_thread(worker.join, 1.)
            self.assertTrue(await asyncio.to_thread(finished.wait, 1.))
            self.assertTrue(await asyncio.to_thread(client_read_finished.wait, 1.))
            self.assertEqual(len(h.rows('pva.return')), 1)
            self.assertFalse(worker.is_alive())
            with socket.socket() as sock:
                self.assertNotEqual(sock.connect_ex(('127.0.0.1', server.server_port)), 0)


if __name__ == '__main__':
    unittest.main()
