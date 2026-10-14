"""Exercise the reused production GetState method without ROS imports."""
import ast
import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock,patch

TOOLS=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('cooperation_readiness',TOOLS/'cooperation_readiness.py')
readiness=importlib.util.module_from_spec(spec);spec.loader.exec_module(readiness)


def existing_update():
    tree=ast.parse(readiness.SOURCE.read_text())
    method=next(m for c in tree.body if isinstance(c,ast.ClassDef) and c.name=='Readiness'
                for m in c.body if isinstance(m,ast.FunctionDef) and m.name=='update_lifecycle')
    clock=Mock();clock.monotonic.return_value=100.
    state_type=NS(Request=lambda:object())
    namespace={'time':clock,'math':math,'GetState':state_type}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),str(readiness.SOURCE),'exec'),namespace)
    return namespace['update_lifecycle'],state_type,clock


class NativeReadinessTests(unittest.TestCase):
    def test_existing_query_method_waits_for_both_active_receipts(self):
        update,state_type,clock=existing_update();node=Mock();clients={}
        def create_client(kind,path):
            client=Mock();client.service_is_ready.return_value=True
            future=Mock();future.done.return_value=False
            future.result.return_value=NS(current_state=NS(id=1 if 'docking' in path else 3))
            client.call_async.return_value=future;clients[path]=client;return client
        node.create_client.side_effect=create_client
        with patch.object(readiness,'_load_runtime',return_value=(update,state_type)),patch.object(readiness.time,'monotonic',side_effect=lambda:clock.monotonic()):
            gate=readiness.NativeReadiness(node);self.assertFalse(gate.active())
            gate.update()
            for client in clients.values():client.call_async.return_value.done.return_value=True
            gate.update();self.assertFalse(gate.active())
            clock.monotonic.return_value=100.6;gate.update()
            clients['/docking_server/get_state'].call_async.return_value.result.return_value.current_state.id=3
            gate.update();self.assertTrue(gate.active())
        for client in clients.values():self.assertLessEqual(client.call_async.call_count,2)
        self.assertEqual(set(clients),{'/docking_server/get_state','/bt_navigator/get_state'})

    def test_stale_inactive_missing_and_malformed_receipts_never_ready(self):
        snapshot={'ready':True,'observed_monotonic':100.,'lifecycle':{'docking_server':[3,100.],'bt_navigator':[3,100.]}}
        self.assertTrue(readiness.snapshot_active(snapshot,100.1))
        for state in ([1,100.],[3,96.],[True,100.],None):
            changed={**snapshot,'lifecycle':{**snapshot['lifecycle'],'docking_server':state}}
            with self.subTest(state=state):self.assertFalse(readiness.snapshot_active(changed,100.1))


if __name__=='__main__':unittest.main()
