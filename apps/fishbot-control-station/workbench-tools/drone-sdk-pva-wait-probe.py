#!/usr/bin/env python3
"""Real SDK PVA response fault → guarded wait → recover; no PX4 or flight."""
import argparse
import asyncio
from contextlib import nullcontext
import importlib.util
import json
import math
from pathlib import Path
import socket
import sys
import tempfile
import time
import types
from functools import partial

sys.dont_write_bytecode = True
TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent/'workbench-review-tests'))
from test_drone_command_revalidation_patch import REPAIR, apply, copy_source
from test_drone_recovery_cache_chain import RecoveryHarness
spec = importlib.util.spec_from_file_location('pva_wait_transport', TOOLS/'drone-sdk-cache-probe.py')
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


def wire_checks(packets, phases, mode):
    result = {}
    expected = {'pending_unconfirmed': 2048 if mode == 'after_forward' else 2552,
                'recovery_position': 2552, 'after_stop': None}
    for name, start, end in phases:
        rows = [p for p in packets if p['type'] == 'SET_POSITION_TARGET_LOCAL_NED'
                and start <= p['host_monotonic_ns'] <= end]
        if name == 'after_stop':
            result[name] = not rows
            continue
        pva = expected[name] == 2048
        values = [0.,1.,-1.,.1,.2,0.,0.,.01,0.] if pva else [0.,0.,-1.]
        result[name] = (len(rows) >= 2 and len({p['time_boot_ms'] for p in rows}) >= 2 and
            all(p.get('type_mask') == expected[name] and p.get('coordinate_frame') == 1 and
                p.get('target_system') == 7 and p.get('target_component') == 1 and
                abs(p['yaw']-(math.pi/2-(.25 if pva else 0.))) <= 1e-6 and
                all(math.isfinite(p[k]) and abs(p[k]-v) <= 1e-6 for k,v in
                    zip(('x','y','z','vx','vy','vz','afx','afy','afz'), values)) for p in rows))
    result['all_windows_observed'] = set(result) == set(expected)
    return result


async def scenario(system, invoke, calls, packets, phases, output, mode, trigger):
    port = json.loads((output/'sdk-process.json').read_text())['grpc_port']
    relay = transport.PositionResponseFault(mode, port, method='pva')
    task = None
    evidence = {'scope': 'real SDK/cache and relay; synthetic planner, clock, telemetry, pose and pause',
        'rpc_response_fault': mode, 'trigger': trigger, 'flight_accepted': False, 'physical_pause_confirmed': False,
        'sdk_cleanup_scope': 'deferred to transport owner, not production cleanup acceptance', 'events': []}
    def mark(event, **fields):
        evidence['events'].append(dict(event=event, host_monotonic_ns=time.monotonic_ns(), **fields))
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        copy_source(root)
        apply(root, REPAIR)
        h = RecoveryHarness(root, output)
        h.sdk_modules = nullcontext
        h.owner.options['command_rpc_timeout_s'] = .5 if trigger == 'rpc_timeout' else 1.
        h.owner.report.update(flight_accepted=False, validation_scope=evidence['scope'])
        h.note = lambda event, **fields: mark(event, **fields)
        h.owner.recovering = False
        deferred = False
        async def defer_close():
            nonlocal deferred
            deferred = True
            mark('sdk_cleanup_deferred')
        h.owner.close_mavsdk = defer_close
        try:
            client = await relay.start()
            class OnlySetpoints:
                async def set_position_ned(self, position):
                    name = 'flight.recovery_position' if h.owner.recovering else 'flight.initial_position'
                    await invoke(name, lambda: system.offboard.set_position_ned(position))
                async def set_position_velocity_acceleration_ned(self, position, velocity, acceleration):
                    await invoke('flight.pva_unconfirmed', lambda:
                        client.set_position_velocity_acceleration_ned(position, velocity, acceleration))
            h.owner.drone = types.SimpleNamespace(offboard=OnlySetpoints())
            task = asyncio.create_task(h.run())
            await asyncio.wait_for(relay.received.wait(), 2.)
            if mode == 'after_forward':
                await asyncio.wait_for(relay.forwarded.wait(), 1.)
            start = time.monotonic_ns()
            mark('unconfirmed_pva_waiting', simulation_s=h.clock.sim)
            await asyncio.sleep(.25)
            invalidated = time.monotonic_ns()
            phases.append(('pending_unconfirmed', start+100_000_000, invalidated))
            if trigger == 'source_expiry':
                mark('advance_fixture_clock', old_sim_s=h.clock.sim, new_sim_s=10.4)
                h.advance(10.4)
            else:
                mark('keep_simulation_clock_fresh_and_wait_for_rpc_deadline', simulation_s=h.clock.sim)
            await asyncio.wait_for(asyncio.shield(task), 2.)
            await asyncio.wait_for(relay.cancelled.wait(), 1.)
            mark('run_returned', status=h.owner.status)
            recovery = next(c for c in calls if c['method'] == 'flight.recovery_position')
            if not recovery.get('returned'):
                raise RuntimeError('Recovery position did not return')
            await asyncio.sleep(.28)
            stop_start = time.monotonic_ns()
            phases.append(('recovery_position', recovery['host_end_ns']+100_000_000, stop_start))
            stopped = await invoke('probe.offboard_stop', system.offboard.stop)
            await asyncio.sleep(.3)
            phases.append(('after_stop', stopped['host_end_ns']+100_000_000, time.monotonic_ns()))
            attempt = h.owner.report.get('command_rpc_attempts', [{}])[0]
            checks = wire_checks(packets, phases, mode)
            checks.update({
                'unconfirmed_effect_preserved': attempt.get('status') == 'unconfirmed' and
                    attempt.get('remote_effect') == 'unknown' and not attempt.get('rpc_returned', True),
                'requested_failure_observed': attempt.get('reason') == ('command_rpc_timeout' if trigger == 'rpc_timeout'
                    else 'inflight_command_source_expired'),
                'only_one_pva_attempt': sum(c['method'] == 'flight.pva_unconfirmed' for c in calls) == 1,
                'cancel_reached_relay': relay.cancelled.is_set(),
                'forwarding_matches_injection': relay.forwarded.is_set() == (mode == 'after_forward'),
                'no_pva_after_recovery_return': not any(p['type'] == 'SET_POSITION_TARGET_LOCAL_NED' and
                    p['host_monotonic_ns'] > recovery['host_end_ns'] and p['type_mask'] == 2048 for p in packets),
                'failed_not_landed': h.owner.status == 'failed' and not h.owner.report.get('landed', False),
                'position_reference': h.owner.reference.get('mode') == 'position',
                'cleanup_deferred': deferred,
            })
            evidence.update(diagnostic_checks=checks, attempt=attempt, status=h.owner.status)
        finally:
            if task is not None:
                if not task.done(): task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            cleanup_errors = await relay.close()
            evidence.update(relay_events=relay.events, relay_port=relay.port, cleanup_errors=cleanup_errors)
            with socket.socket() as sock:
                closed = relay.port is not None and sock.connect_ex(('127.0.0.1', relay.port)) != 0
            evidence.setdefault('diagnostic_checks', {}).update(relay_closed=closed, relay_cleanup_ok=not cleanup_errors)
            (output/'pva-wait-scenario.json').write_text(json.dumps(evidence, indent=2, allow_nan=False)+'\n')
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rpc-response-fault', choices=('before_forward','after_forward'), required=True)
    parser.add_argument('--trigger', choices=('source_expiry','rpc_timeout'), default='source_expiry')
    args = parser.parse_args()
    return asyncio.run(transport.run(args.output.resolve(), scenario=partial(scenario, mode=args.rpc_response_fault, trigger=args.trigger)))


if __name__ == '__main__':
    raise SystemExit(main())
