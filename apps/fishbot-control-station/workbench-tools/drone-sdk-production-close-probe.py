#!/usr/bin/env python3
"""Real SDK + Flight finalizer; synthetic source/sensing and loopback peer only."""
import argparse
import ast
import asyncio
from contextlib import nullcontext
import importlib.util
import json
import math
from importlib.metadata import version
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

sys.dont_write_bytecode = True
TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent/'workbench-review-tests'))
from test_drone_state_epoch_window import StateEpochWindow, http_source
import test_drone_command_validity as original

spec = importlib.util.spec_from_file_location('production_close_transport', TOOLS/'drone-sdk-cache-probe.py')
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


async def scenario(system, invoke, calls, packets, phases, output):
    StateEpochWindow.setUpClass()
    fixture = StateEpochWindow()
    task = None
    release, entered = threading.Event(), threading.Event()
    events = []
    h = fixture.bridge()
    h.owner.output = output
    h.owner.drone = system
    h.sdk_modules = nullcontext
    h.owner.recovering = False
    namespace = dict(asyncio=asyncio, subprocess=subprocess, json=json)
    atomic = next(n for n in ast.parse((h.root/'flight.py').read_text()).body
                  if isinstance(n, ast.FunctionDef) and n.name == 'atomic_json')
    exec(compile(ast.Module(body=[atomic], type_ignores=[]), str(h.root/'flight.py'), 'exec'), namespace)
    close = original.methods(h.root/'flight.py', 'Flight', ('close_mavsdk',), namespace)['close_mavsdk']
    process = system._server_process
    old_position = system.offboard.set_position_ned
    old_pva = system.offboard.set_position_velocity_acceleration_ned

    def mark(event, **details):
        events.append(dict(event=event, host_monotonic_ns=time.monotonic_ns(), **details))

    async def position(value):
        name = 'recovery_position' if h.owner.recovering else 'initial_position'
        await invoke(name, lambda: old_position(value))

    async def pva(position, velocity, acceleration):
        snapshot = h.snapshots[-1]
        mark('pva_rpc_after_source_invalidation', snapshot_epoch=snapshot['snapshot']['command_epoch'],
             current_source_epoch=h.source.node.command_epoch.token)
        await invoke('stale_snapshot_pva', lambda: old_pva(position, velocity, acceleration))

    async def production_close():
        mark('production_close_begin', pid=process.pid, poll=process.poll())
        await close(h.owner)
        mark('production_close_return', pid=process.pid, poll=process.poll())

    system.offboard.set_position_ned = position
    system.offboard.set_position_velocity_acceleration_ned = pva
    h.owner.close_mavsdk = production_close

    def before_send(path, body):
        if path == '/state' and len(h.snapshots) == 2:
            mark('second_state_response_held', response_epoch=body['command_epoch'])
            entered.set()
            release.wait(2.)

    try:
        with http_source(h, before_send) as http_port:
            task = asyncio.create_task(h.run())
            if not await asyncio.to_thread(entered.wait, 2.):
                raise RuntimeError('Second state response was not reached')
            start = time.monotonic_ns()+100_000_000
            await asyncio.sleep(.3)
            phases.append(('stale_pva_until_fresh_state', start, time.monotonic_ns()))
            mark('release_new_epoch_response')
            release.set()
            await asyncio.wait_for(asyncio.shield(task), 8.)
            start = time.monotonic_ns()+100_000_000
            await asyncio.sleep(.35)
            phases.append(('after_production_close', start, time.monotonic_ns()))
        with socket.socket() as probe:
            http_closed = probe.connect_ex(('127.0.0.1', http_port)) != 0
        with socket.socket() as probe:
            grpc_port = json.loads((output/'sdk-process.json').read_text())['grpc_port']
            grpc_closed = probe.connect_ex(('127.0.0.1', grpc_port)) != 0
        active = [p for p in packets if p['type']=='SET_POSITION_TARGET_LOCAL_NED' and phases[0][1]<=p['host_monotonic_ns']<=phases[0][2]]
        after = [p for p in packets if p['type']=='SET_POSITION_TARGET_LOCAL_NED' and phases[1][1]<=p['host_monotonic_ns']<=phases[1][2]]
        record = h.owner.report.get('mavsdk_server', {})
        first = h.snapshots[0]
        point = first['snapshot']['setpoint']
        expected = [value for key in ('position','velocity','acceleration')
                    for value in (point[key][1],point[key][0],-point[key][2])]
        active_values_match = bool(active) and all(
            p['type_mask']==2048 and p['coordinate_frame']==1 and
            p['target_system']==7 and p['target_component']==1 and
            abs(p['yaw']-(math.pi/2-point['yaw_rad']))<=1e-6 and
            all(math.isfinite(p[k]) and abs(p[k]-v)<=1e-6 for k,v in
                zip(('x','y','z','vx','vy','vz','afx','afy','afz'),expected)) for p in active)
        result = dict(scope='real Flight.run/recover/finally/close_mavsdk, SDK, HTTP and MAVLink; graph/pose/clock/armed/pause are fixtures',
            sdk_python_version=version('mavsdk-grpc'), snapshot_cache_fields_are_fixture=True,
            http_port=http_port, grpc_port=grpc_port, http_worker_closed=h.http_worker_closed,
            flight_accepted=False, physical_pause_confirmed=False, distributed_epoch_gap_fixed=False,
            events=events, snapshots=h.snapshots, production_server_record=record,
            diagnostic_checks=dict(
                stale_snapshot_epoch_differs=first['snapshot']['command_epoch']!=first['current_source_epoch'],
                one_stale_pva_rpc=sum(c['method']=='stale_snapshot_pva' for c in calls)==1,
                actual_stale_pva_resends=len(active)>=2 and active_values_match,
                later_epoch_routes_to_recovery=h.owner.report['recovery']['trigger']=='command_epoch_mismatch',
                recovery_position_rpc_returned=any(c['method']=='recovery_position' and c.get('returned') for c in calls),
                production_close_returned=any(e['event']=='production_close_return' for e in events),
                production_record_matches_owner=record.get('pid')==process.pid and record.get('cleanup_wait_confirmed') is True,
                process_reaped_before_probe_fallback=process.poll() is not None and not Path('/proc',str(process.pid)).exists(),
                no_resend_after_production_close=not after, http_and_grpc_closed=http_closed and grpc_closed,
                task_failed_without_landing=h.owner.status=='failed' and not h.owner.report.get('landed',False)))
        (output/'production-close-evidence.json').write_text(json.dumps(result, indent=2)+'\n')
        return result
    finally:
        release.set()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        fixture.doCleanups()
        StateEpochWindow.tearDownClass()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    return asyncio.run(transport.run(args.output.resolve(), scenario=scenario))


if __name__ == '__main__':
    raise SystemExit(main())
