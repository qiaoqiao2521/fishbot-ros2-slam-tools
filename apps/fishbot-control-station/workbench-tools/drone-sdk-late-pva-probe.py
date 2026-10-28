#!/usr/bin/env python3
"""Controlled receiver-side late PVA delivery; real SDK, synthetic peer/state."""
import argparse
import asyncio
from contextlib import nullcontext
from functools import partial
import importlib.util
import json
import math
from pathlib import Path
import socket
import sys
import time
from unittest.mock import patch

sys.dont_write_bytecode = True
TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent/'workbench-review-tests'))
import test_drone_source_watch as watches
from test_drone_state_epoch_window import http_source
from test_drone_recovery_cache_chain import RecoveryBlocked

spec = importlib.util.spec_from_file_location('late_pva_production', TOOLS/'drone-sdk-production-close-probe.py')
production = importlib.util.module_from_spec(spec)
spec.loader.exec_module(production)
transport = production.transport


def wire_matches(rows, point, pva):
    values = ([v for key in ('position','velocity','acceleration')
               for v in (point[key][1],point[key][0],-point[key][2])] if pva else [0.,0.,-1.])
    return len(rows)>=2 and len({p['time_boot_ms'] for p in rows})>=2 and all(
        p['type_mask']==(2048 if pva else 2552) and p['coordinate_frame']==1 and
        p['target_system']==7 and p['target_component']==1 and abs(p['yaw']-math.pi/2)<=1e-6 and
        all(math.isfinite(p[k]) and abs(p[k]-v)<=1e-6 for k,v in
            zip(('x','y','z','vx','vy','vz','afx','afy','afz'),values)) for p in rows)


async def scenario(system, invoke, calls, packets, phases, output, mode, expected, watch_patch):
    if watch_patch:
        with patch.object(watches, 'WATCH', watch_patch):
            watches.SourceWatchPropagation.setUpClass()
    else:
        watches.SourceWatchPropagation.setUpClass()
    fixture = watches.SourceWatchPropagation()
    h = fixture.bridge()
    h.owner.output, h.owner.drone, h.sdk_modules = output, system, nullcontext
    h.owner.recovering = False
    relay = transport.PositionResponseFault(mode,
        json.loads((output/'sdk-process.json').read_text())['grpc_port'], method='pva')
    observation_entered, release_observation = asyncio.Event(), asyncio.Event()
    events, task = [], None
    result = {'scope':'real SDK/RPC/HTTP and original Flight methods; source/pose/clock/armed/pause are fixtures',
        'fault_model':'late_forward retains one original received protobuf after client cancellation; NOT natural direct-channel reordering',
        'mode':mode, 'expected_observation':expected, 'flight_accepted':False,'physical_pause_confirmed':False}

    def mark(event, **fields):
        events.append(dict(event=event,host_monotonic_ns=time.monotonic_ns(),**fields))

    async def window(name, begin=None):
        start = (time.monotonic_ns() if begin is None else begin)+100_000_000
        await asyncio.sleep(.3)
        phases.append((name,start,time.monotonic_ns()))

    original_close = production.production_close_method(h.root,h.owner)
    async def close():
        mark('production_close_begin')
        await original_close()
        mark('production_close_return')
    h.owner.close_mavsdk = close

    async def observation(*args):
        mark('recovery_waiting_for_observation',reference_mode=h.owner.reference.get('mode'))
        observation_entered.set()
        await release_observation.wait()
        raise RecoveryBlocked('fixture_stop_after_cache_observation')
    h.owner.hold_for_observation = observation

    try:
        client = await relay.start()
        direct_position = system.offboard.set_position_ned
        async def position(value):
            await invoke('recovery_position' if h.owner.recovering else 'initial_position',
                lambda:direct_position(value))
        async def pva(position,velocity,acceleration):
            await invoke('unconfirmed_pva',lambda:client.set_position_velocity_acceleration_ned(position,velocity,acceleration))
        system.offboard.set_position_ned = position
        system.offboard.set_position_velocity_acceleration_ned = pva
        with http_source(h) as http_port:
            task = asyncio.create_task(h.run())
            await asyncio.wait_for(relay.received.wait(),2.)
            if mode=='after_forward':await asyncio.wait_for(relay.forwarded.wait(),1.)
            await window('pending_pva')
            h.source.node.invalidate_command_source('fixture_source_changed')
            mark('source_invalidated',epoch=h.source.node.command_epoch.token)
            await asyncio.wait_for(relay.cancelled.wait(),1.)
            if expected=='pause':
                await asyncio.wait_for(asyncio.shield(task),8.)
                mark('guard_finished_before_late_release')
            else:
                await asyncio.wait_for(observation_entered.wait(),1.)
                recovery = next(c for c in calls if c['method']=='recovery_position')
                await window('recovery_position',recovery['host_end_ns'])
            mark('release_original_late_request',reference_mode=h.owner.reference.get('mode'))
            relay.late_release.set()
            if mode=='late_forward':await asyncio.wait_for(relay.late_finished.wait(),2.5)
            await window('after_late_release')
            reference_after = dict(h.owner.reference)
            release_observation.set()
            await asyncio.wait_for(asyncio.shield(task),8.)
            await window('after_production_close')
        point = h.snapshots[0]['snapshot']['setpoint']
        scoped = {name:[p for p in packets if p['type']=='SET_POSITION_TARGET_LOCAL_NED' and lo<=p['host_monotonic_ns']<=hi]
                  for name,lo,hi in phases}
        attempt = h.owner.report['command_rpc_attempts'][0]
        checks = dict(single_pva_rpc=sum(c['method']=='unconfirmed_pva' for c in calls)==1,
            cancel_reached_relay=relay.cancelled.is_set(),remote_effect_unknown=attempt['remote_effect']=='unknown' and not attempt['rpc_returned'],
            source_watch_was_cause=h.owner.report['recovery']['trigger']=='command_source_epoch_changed',
            pending_wire=wire_matches(scoped['pending_pva'],point,mode=='after_forward'),
            production_close_returned=any(e['event']=='production_close_return' for e in events),
            no_packets_after_production_close=not scoped['after_production_close'],
            failed_without_landing=h.owner.status=='failed' and not h.owner.report.get('landed',False))
        if expected=='pause':
            checks.update(no_unfenced_recovery_position=not any(c['method']=='recovery_position' for c in calls),
                blocked_before_observation=not observation_entered.is_set() and h.owner.phase=='recovery_blocked',
                late_request_cannot_reach_closed_backend=(mode!='late_forward' or relay.late_error_code=='UNAVAILABLE'),
                no_late_cache_after_guard=not scoped['after_late_release'])
        else:
            checks.update(recovery_position_returned=any(c['method']=='recovery_position' and c.get('returned') for c in calls),
                position_before_late_request=wire_matches(scoped['recovery_position'],point,False),
                post_release_matches=wire_matches(scoped['after_late_release'],point,expected=='overwrite'),
                python_reference_still_position=reference_after.get('mode')=='position')
        captured=[e for e in relay.events if e['event']=='late_request_captured']
        forwarded=[e for e in relay.events if e['event']=='late_upstream_call_started']
        if mode=='late_forward':
            checks['single_original_request_unchanged']=len(captured)==len(forwarded)==1 and captured[0]['protobuf_hex']==forwarded[0]['protobuf_hex']
        result.update(diagnostic_checks=checks,events=events,snapshots=h.snapshots,
            reference_after_late_release=reference_after,attempt=attempt,watch_records=h.owner.report.get('source_epoch_watches'),
            production_server_record=h.owner.report.get('mavsdk_server'),http_port=http_port)
        return result
    finally:
        release_observation.set()
        if task is not None and not task.done():task.cancel()
        if task is not None:await asyncio.gather(task,return_exceptions=True)
        cleanup_errors = await relay.close()
        with socket.socket() as s:relay_closed=relay.port is not None and s.connect_ex(('127.0.0.1',relay.port))!=0
        result.setdefault('diagnostic_checks',{}).update(relay_closed=relay_closed,relay_cleanup_ok=not cleanup_errors)
        result.update(relay_events=relay.events,relay_port=relay.port,cleanup_errors=cleanup_errors)
        (output/'late-pva-scenario.json').write_text(json.dumps(result,indent=2)+'\n')
        fixture.doCleanups()
        watches.SourceWatchPropagation.tearDownClass()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--mode',choices=('before_forward','after_forward','late_forward'),required=True)
    parser.add_argument('--expect',choices=('hold','overwrite','pause'),default='pause')
    parser.add_argument('--watch-patch',type=Path)
    args=parser.parse_args()
    return asyncio.run(transport.run(args.output.resolve(),scenario=partial(scenario,mode=args.mode,
        expected=args.expect,watch_patch=args.watch_patch)))


if __name__=='__main__':raise SystemExit(main())
