import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import types
import unittest
from unittest.mock import Mock


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
