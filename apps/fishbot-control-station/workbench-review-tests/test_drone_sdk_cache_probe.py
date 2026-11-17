import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import types
import unittest
from unittest.mock import AsyncMock, Mock


SOURCE = Path(__file__).resolve().parents[1]/'workbench-tools/drone-sdk-cache-probe.py'
spec = importlib.util.spec_from_file_location('sdk_cache_probe', SOURCE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ProbeTests(unittest.IsolatedAsyncioTestCase):
    def test_nonfinite_protocol_fields_remain_unknown_without_losing_the_record(self):
        value = {'type': 'COMMAND_LONG', 'param1': float('nan'), 'array': [1., float('inf')]}
        encoded = json.dumps(probe.json_safe(value), allow_nan=False)
        self.assertEqual(json.loads(encoded), {'type': 'COMMAND_LONG', 'param1': None, 'array': [1., None]})
        self.assertNotEqual(probe.json_safe(value)['param1'], 0.)

    async def test_response_fault_distinguishes_forwarding_and_releases_both_channels(self):
        import grpc
        import socket
        from mavsdk_grpc import offboard_pb2 as pb, offboard_pb2_grpc as rpc
        from mavsdk_grpc.offboard import PositionNedYaw

        accepted = []
        class Upstream(rpc.OffboardServiceServicer):
            async def SetPositionNed(self, request, context):
                accepted.append(request)
                return pb.SetPositionNedResponse(offboard_result=pb.OffboardResult(result=1))

        server = grpc.aio.server()
        rpc.add_OffboardServiceServicer_to_server(Upstream(), server)
        port = server.add_insecure_port('127.0.0.1:0')
        await server.start()
        try:
            for mode, count in [('before_forward', 0), ('after_forward', 1)]:
                with self.subTest(mode=mode):
                    relay = probe.PositionResponseFault(mode, port)
                    try:
                        client = await relay.start()
                        with self.assertRaises(TimeoutError):
                            await asyncio.wait_for(client.set_position_ned(PositionNedYaw(.4, .5, -.6, 15.)), .1)
                        await asyncio.wait_for(relay.cancelled.wait(), 1.)
                        self.assertEqual(len(accepted), count)
                        self.assertEqual([e['event'] for e in relay.events],
                            ['relay_received'] + (['upstream_call_started', 'upstream_returned']
                                                if count else []) + ['relay_handler_cancelled'])
                    finally:
                        await relay.close()
                    with socket.socket() as sock:
                        self.assertNotEqual(sock.connect_ex(('127.0.0.1', relay.port)), 0)
        finally:
            await server.stop(0)

    async def test_relay_cleanup_failure_does_not_skip_remaining_resources(self):
        relay = probe.PositionResponseFault('before_forward', 1)
        relay.client_channel = types.SimpleNamespace(close=AsyncMock(side_effect=RuntimeError('fixture closed')))
        relay.server = types.SimpleNamespace(stop=AsyncMock())
        relay.channel = types.SimpleNamespace(close=AsyncMock())
        errors = await relay.close()
        self.assertEqual(len(errors), 1)
        self.assertIn('client cleanup', errors[0])
        relay.server.stop.assert_awaited_once_with(0)
        relay.channel.close.assert_awaited_once_with()

    async def test_cleanup_handles_exit_between_poll_and_terminate(self):
        process = types.SimpleNamespace(poll=lambda: None,
            terminate=Mock(side_effect=ProcessLookupError()), wait=Mock(return_value=-15))
        self.assertEqual(await probe.close_sdk_process(process), [])
        process.wait.assert_called_once_with(timeout=3.)

    async def test_cleanup_retains_final_timeout_instead_of_skipping_report(self):
        process = types.SimpleNamespace(poll=lambda: None, terminate=Mock(),
            wait=Mock(side_effect=subprocess.TimeoutExpired('owned-sdk', 3)), kill=Mock())
        errors = await probe.close_sdk_process(process)
        process.kill.assert_called_once()
        self.assertEqual(len(errors), 1)
        self.assertIn('TimeoutExpired', errors[0])


if __name__ == '__main__':
    unittest.main()
