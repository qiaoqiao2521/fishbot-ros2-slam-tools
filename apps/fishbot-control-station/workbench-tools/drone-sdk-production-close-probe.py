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
import types
from functools import partial

sys.dont_write_bytecode = True
TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent/'workbench-review-tests'))
from test_drone_state_epoch_window import StateEpochWindow, http_source
import test_drone_command_validity as original

spec = importlib.util.spec_from_file_location('production_close_transport', TOOLS/'drone-sdk-cache-probe.py')
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


def production_close_method(root, owner):
    namespace = dict(asyncio=asyncio, subprocess=subprocess, json=json)
    atomic = next(n for n in ast.parse((root/'flight.py').read_text()).body
                  if isinstance(n, ast.FunctionDef) and n.name == 'atomic_json')
    exec(compile(ast.Module(body=[atomic], type_ignores=[]), str(root/'flight.py'), 'exec'), namespace)
    method = original.methods(root/'flight.py', 'Flight', ('close_mavsdk',), namespace)['close_mavsdk']
    return types.MethodType(method, owner)


async def scenario(system, invoke, calls, packets, phases, output, source_watch=False):
    if source_watch:
        from test_drone_source_watch import SourceWatchPropagation
        case = SourceWatchPropagation
    else:
        case = StateEpochWindow
    case.setUpClass()
    fixture = case()
    task = None
    release, entered = threading.Event(), threading.Event()
    events = []
    h = fixture.bridge()
    h.owner.output = output
    h.owner.drone = system
    h.sdk_modules = nullcontext
    h.owner.recovering = False
    close = production_close_method(h.root, h.owner)
    process = system._server_process
    old_position = system.offboard.set_position_ned
    old_pva = system.offboard.set_position_velocity_acceleration_ned
    pva_method = 'initial_valid_pva' if source_watch else 'stale_snapshot_pva'

    def mark(event, **details):
        events.append(dict(event=event, host_monotonic_ns=time.monotonic_ns(), **details))

    async def position(value):
        name = 'recovery_position' if h.owner.recovering else 'initial_position'
        await invoke(name, lambda: old_position(value))

    async def pva(position, velocity, acceleration):
        snapshot = h.snapshots[-1]
        mark('pva_rpc_before_source_invalidation' if source_watch else 'pva_rpc_after_source_invalidation', snapshot_epoch=snapshot['snapshot']['command_epoch'],
             current_source_epoch=h.source.node.command_epoch.token)
        await invoke(pva_method, lambda: old_pva(position, velocity, acceleration))

    async def production_close():
        mark('production_close_begin', pid=process.pid, poll=process.poll())
        await close()
        mark('production_close_return', pid=process.pid, poll=process.poll())

    system.offboard.set_position_ned = position
    system.offboard.set_position_velocity_acceleration_ned = pva
    h.owner.close_mavsdk = production_close

    def before_send(path, body):
        if path == '/state' and len(h.snapshots) == 2:
            mark('second_state_response_held', response_epoch=body['command_epoch'])
            if source_watch:
                # Establish a visible, valid PVA cache before introducing the fault.
                time.sleep(.15)
                h.source.node.invalidate_command_source('fixture_source_changed')
                mark('source_invalidated_while_state_held', epoch=h.source.node.command_epoch.token)
            entered.set()
            release.wait(2.)

    try:
        with http_source(h, before_send) as http_port:
            request = h.owner.ego_request
            def tracked_request(path, body=None):
                reply = request(path, body)
                if path == '/state':
                    mark('state_client_returned', response_epoch=reply.get('command_epoch'))
                return reply
            h.owner.ego_request = tracked_request
            task = asyncio.create_task(h.run())
            if not await asyncio.to_thread(entered.wait, 2.):
                raise RuntimeError('Second state response was not reached')
            if source_watch:
                await asyncio.wait_for(asyncio.shield(task), 8.)
                invalidated = next(e['host_monotonic_ns'] for e in events if e['event']=='source_invalidated_while_state_held')
                closed = next(e['host_monotonic_ns'] for e in events if e['event']=='production_close_return')
                pva_call = next(c for c in calls if c['method']==pva_method)
                phases.extend([('valid_pva_before_invalidation', pva_call['host_end_ns'], invalidated),
                    ('source_invalidation_until_close', invalidated, closed)])
                mark('recovery_finished_while_state_held', held=not release.is_set())
                mark('release_held_old_state_response')
                release.set()
            else:
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
        after = [p for p in packets if p['type']=='SET_POSITION_TARGET_LOCAL_NED' and phases[-1][1]<=p['host_monotonic_ns']<=phases[-1][2]]
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
            source_watch_enabled=source_watch, source_watch_records=h.owner.report.get('source_epoch_watches',[]),
            events=events, snapshots=h.snapshots, production_server_record=record,
            diagnostic_checks=dict(
                initial_epoch_matches_fault_order=(first['snapshot']['command_epoch']==first['current_source_epoch'])==source_watch,
                one_pva_rpc=sum(c['method']==pva_method for c in calls)==1,
                actual_pva_window_matches=len(active)>=2 and active_values_match,
                later_epoch_routes_to_recovery=h.owner.report['recovery']['trigger']==('command_source_epoch_changed' if source_watch else 'command_epoch_mismatch'),
                recovery_position_rpc_returned=any(c['method']=='recovery_position' and c.get('returned') for c in calls),
                production_close_returned=any(e['event']=='production_close_return' for e in events),
                production_record_matches_owner=record.get('pid')==process.pid and record.get('cleanup_wait_confirmed') is True,
                process_reaped_before_probe_fallback=process.poll() is not None and not Path('/proc',str(process.pid)).exists(),
                no_resend_after_production_close=not after, http_and_grpc_closed=http_closed and grpc_closed,
                task_failed_without_landing=h.owner.status=='failed' and not h.owner.report.get('landed',False)))
        if source_watch:
            watch = result['source_watch_records'][-1]
            release_ns = next(e['host_monotonic_ns'] for e in events if e['event']=='release_held_old_state_response')
            closed_ns = next(e['host_monotonic_ns'] for e in events if e['event']=='production_close_return')
            result['diagnostic_checks'].update(
                source_watch_received_change=watch.get('failure')=='command_source_epoch_changed',
                recovery_before_held_state_release=closed_ns<release_ns,
                actual_late_state_read_ignored=any(e['event']=='state_client_returned' and e['host_monotonic_ns']>release_ns for e in events),
                single_pva_despite_late_state=sum(c['method']==pva_method for c in calls)==1)
        (output/'production-close-evidence.json').write_text(json.dumps(result, indent=2)+'\n')
        return result
    finally:
        release.set()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        fixture.doCleanups()
        case.tearDownClass()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-watch', action='store_true')
    args = parser.parse_args()
    return asyncio.run(transport.run(args.output.resolve(), scenario=partial(scenario, source_watch=args.source_watch)))


if __name__ == '__main__':
    raise SystemExit(main())
