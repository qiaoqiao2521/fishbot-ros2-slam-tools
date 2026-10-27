"""Actual installed MAVSDK Python/gRPC client, synthetic loopback service only.

Run with ros2-drone/venv/bin/python. No MAVSDK server binary, MAVLink peer,
PX4, ROS, Gazebo or aircraft is started. Server-side cache effects are fixtures.
"""
import asyncio
from contextlib import nullcontext
from importlib.metadata import version
from pathlib import Path
import socket
import tempfile
import types
import unittest

from test_drone_command_revalidation_patch import REPAIR, apply, copy_source
from test_drone_recovery_cache_chain import RecoveryHarness


class RecoveryGrpcDeadline(unittest.IsolatedAsyncioTestCase):
    async def test_real_client_cancellation_reaches_handler_and_preserves_unknown_effect(self):
        import grpc
        from mavsdk_grpc import offboard_pb2 as pb, offboard_pb2_grpc as rpc
        from mavsdk_grpc.offboard import Offboard

        self.assertEqual(version('mavsdk-grpc'), '4.0.5')
        for accepted_before_delay in (False, True):
            with self.subTest(accepted_before_delay=accepted_before_delay), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                copy_source(root)
                apply(root, REPAIR)
                output = root/'output'
                output.mkdir()
                h = RecoveryHarness(root, output)
                h.owner.options['recovery_rpc_timeout_s'] = .1
                h.sdk_modules = nullcontext  # Use actual SDK value classes and translations.
                handler_cancelled = asyncio.Event()
                server_positions = []

                class Service(rpc.OffboardServiceServicer):
                    async def SetPositionNed(self, request, context):
                        server_positions.append(request)
                        if len(server_positions) == 1:
                            h.cache = {'mode': 'position'}
                            return pb.SetPositionNedResponse(offboard_result=pb.OffboardResult(result=1))
                        h.note('synthetic.position.received')
                        if accepted_before_delay:
                            h.cache = {'mode': 'position'}
                        try:
                            await asyncio.Event().wait()
                        except asyncio.CancelledError:
                            handler_cancelled.set()
                            raise

                    async def SetPositionVelocityAccelerationNed(self, request, context):
                        h.cache = {'mode': 'pva'}
                        h.note('synthetic.pva.accepted')
                        return pb.SetPositionVelocityAccelerationNedResponse(
                            offboard_result=pb.OffboardResult(result=1))

                server = grpc.aio.server()
                rpc.add_OffboardServiceServicer_to_server(Service(), server)
                port = server.add_insecure_port('127.0.0.1:0')
                self.assertGreater(port, 0)
                channel = grpc.aio.insecure_channel(f'127.0.0.1:{port}')
                try:
                    await server.start()
                    await asyncio.wait_for(channel.channel_ready(), 1.)
                    h.owner.drone = types.SimpleNamespace(
                        offboard=Offboard(types.SimpleNamespace(channel=channel)))
                    await asyncio.wait_for(h.run(), 2.)
                    await asyncio.wait_for(handler_cancelled.wait(), 1.)
                    self.assertEqual(len(server_positions), 2)
                    self.assertEqual(len(h.rows('synthetic.pva.accepted')), 1)
                    attempt = h.owner.report['recovery']['rpc_attempts'][0]
                    self.assertEqual(attempt['status'], 'unconfirmed')
                    self.assertEqual(attempt['remote_effect'], 'unknown')
                    self.assertEqual(attempt['error_type'], 'TimeoutError')
                    pause = h.rows('scene.pause')[0]
                    self.assertEqual(pause['cache']['mode'], 'position' if accepted_before_delay else 'pva')
                    self.assertEqual(pause['reference']['mode'], 'position_velocity_acceleration')
                    self.assertEqual(h.owner.status, 'failed')
                    self.assertFalse(h.owner.report.get('landed', False))
                    self.assertEqual(len(h.rows('sdk.close.fixture')), 1)
                finally:
                    await channel.close()
                    await server.stop(0)
                with socket.socket() as sock:
                    self.assertNotEqual(sock.connect_ex(('127.0.0.1', port)), 0)


if __name__ == '__main__':
    unittest.main()
