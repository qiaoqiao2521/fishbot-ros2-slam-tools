"""Snapshot invalidation ordering across actual Flight/Sidecar methods, no flight.

The after-snapshot case is an explicit known-gap witness, not a safety pass.
Control cache, sensing, graph, and recovery pause remain named substitutes.
"""
import asyncio
import copy
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import types
import unittest
from urllib.request import Request, urlopen

import test_drone_command_validity as original
from test_drone_command_revalidation_patch import REPAIR, apply
from test_drone_recovery_cache_chain import RecoveryHarness
import test_drone_source_graph_guard as graphs


@contextmanager
def http_source(h, before_send=None):
    """Real loopback transport around the explicitly substituted source node."""
    source_request = h.source_request

    class Handler(BaseHTTPRequestHandler):
        def respond(self, body):
            if before_send:
                before_send(self.path, body)
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.respond(source_request(self.path))

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            self.respond(source_request(self.path, body))

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    worker.start()
    h.owner.ego_url = 'http://127.0.0.1:'+str(server.server_port)
    namespace = h.owner.goto.__func__.__globals__
    namespace.update(Request=Request, urlopen=urlopen)
    namespace['asyncio'].to_thread = asyncio.to_thread
    h.owner.ego_request = types.MethodType(original.methods(h.root/'flight.py',
        'Flight', ('ego_request',), namespace)['ego_request'], h.owner)
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=1.)
        h.http_worker_closed = not worker.is_alive()


class StateEpochWindow(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        graphs.SourceGraphGuard.setUpClass()
        cls.fixture = graphs.SourceGraphGuard.fixture
        apply(cls.fixture.root, REPAIR)

    @classmethod
    def tearDownClass(cls):
        graphs.SourceGraphGuard.tearDownClass()

    def bridge(self, ordering='after_snapshot'):
        source = graphs.SourceGraphGuard.harness(self)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        flight = RecoveryHarness(self.fixture.root, Path(directory.name))
        flight.root = self.fixture.root
        flight.owner.observer.command_epoch = self.fixture.guard()
        flight.owner.observer.command_epoch.observe(flight.clock.sim, flight.clock.wall)
        flight.snapshots = []

        def request(path, body=None):
            flight.note('source.request', path=path)
            if path in ('/goal', '/stop'):
                code, reply = self.fixture.post(source.node, path, body)[0]
                if code != 202:
                    raise RuntimeError('Fixture source rejected request: '+str(reply))
                if path == '/goal':
                    identity = source.node.last_trajectory_id+1
                    source.ack(floor=identity-1, stamp=source.node.goal_stamp_ns)
                    source.node.on_bspline(source.curve(identity))
                    source.node.on_command(source.command(identity))
                return reply
            if path != '/state':
                raise ValueError(path)
            first = not flight.snapshots
            if first and ordering == 'before_snapshot':
                source.node.invalidate_command_source('fixture_source_changed')
            snapshot = copy.deepcopy(source.node.state())
            if first and ordering != 'before_snapshot':
                source.node.invalidate_command_source('fixture_source_changed')
                if ordering == 'sample_expired':
                    flight.advance(10.5)  # Original .3s sample gate, no tolerance change.
            flight.snapshots.append(dict(snapshot=snapshot,
                current_source_epoch=source.node.command_epoch.token,
                local_clock_epoch=flight.owner.observer.command_epoch.token,
                simulation_s=flight.owner.observer.simulation_s,
                cache=copy.deepcopy(flight.cache)))
            return snapshot

        flight.owner.ego_request = request
        flight.source_request = request
        flight.source = source
        self.latest_bridge = flight
        return flight

    def assert_old_snapshot_dispatch_then_recovery(self, h):
        first, second = h.snapshots[:2]
        old_epoch = first['snapshot']['command_epoch']
        self.assertNotEqual(old_epoch, first['current_source_epoch'])
        self.assertEqual(old_epoch, first['snapshot']['setpoint']['command_epoch'])
        self.assertEqual(first['local_clock_epoch'], second['local_clock_epoch'])
        self.assertNotEqual(first['local_clock_epoch'], old_epoch)
        self.assertEqual(first['simulation_s'], first['snapshot']['setpoint']['stamp_sim_s'])
        self.assertEqual(len(h.rows('pva.return')), 1)
        self.assertEqual(second['cache']['mode'], 'pva')
        self.assertEqual(h.owner.report['recovery']['trigger'], 'command_epoch_mismatch')
        self.assertEqual(h.owner.status, 'failed')
        self.assertFalse(h.owner.report.get('landed', False))
        stop = next(r for r in h.rows('source.request') if r['path'] == '/stop')
        self.assertEqual(stop['cache']['mode'], 'position')

    async def test_invalidation_before_snapshot_blocks_pva(self):
        h = self.bridge('before_snapshot')
        await h.run()
        self.assertEqual(h.rows('pva.return'), [])
        self.assertEqual(h.owner.report['recovery']['trigger'], 'command_epoch_mismatch')
        self.assertEqual(h.owner.status, 'failed')

    async def test_known_gap_fresh_old_snapshot_can_dispatch_after_source_invalidation(self):
        h = self.bridge()
        await h.run()
        self.assert_old_snapshot_dispatch_then_recovery(h)

    async def test_original_sample_expiry_blocks_the_same_invalidated_snapshot(self):
        h = self.bridge('sample_expired')
        await h.run()
        self.assertEqual(h.rows('pva.return'), [])
        self.assertEqual(h.owner.report['recovery']['trigger'], 'EGO 轨迹样本已过期（发送前复查）')
        self.assertEqual(h.owner.status, 'failed')

    async def test_known_gap_also_crosses_real_loopback_http(self):
        h = self.bridge()
        with http_source(h):
            await h.run()
            self.assert_old_snapshot_dispatch_then_recovery(h)
        self.assertTrue(h.http_worker_closed)


if __name__ == '__main__':
    unittest.main()
