#!/usr/bin/env python3
"""Real SDK wire evidence for the opt-in wait guard; all flight state is synthetic."""
import argparse
import asyncio
import copy
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

# These are diagnostic fixtures, never imported by the flight executor.
sys.dont_write_bytecode = True
TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent/'workbench-review-tests'))
from test_drone_command_revalidation_patch import REPAIR, apply, copy_source
from test_drone_recovery_cache_chain import RecoveryHarness
from test_drone_state_wait_guard import PendingStateHttp
import test_drone_command_validity as original

spec = importlib.util.spec_from_file_location('sdk_cache_transport', TOOLS/'drone-sdk-cache-probe.py')
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


def wire_checks(packets, phases, recovery_response_fault=None):
    """Check active fields on each observed window, including the late reply."""
    expected = {
        'pva_pending': (2048, [0., 1., -1., .1, .2, 0., 0., .01, 0.]),
        'position_before_late': (2552, [0., 0., -1.]),
        'position_after_late': (2552, [0., 0., -1.]),
    }
    if recovery_response_fault:
        cache = expected['pva_pending'] if recovery_response_fault == 'before_forward' else expected['position_before_late']
        expected = {'pva_pending': expected['pva_pending'],
                    'cache_after_unconfirmed': cache, 'cache_after_late_response': cache}
    checks = {}
    for name, start, end in phases:
        rows = [p for p in packets if p['type'] == 'SET_POSITION_TARGET_LOCAL_NED'
                and start <= p['host_monotonic_ns'] <= end]
        if name == 'after_stop':
            checks[name] = not rows
        else:
            mask, values = expected[name]
            pva = mask == 2048
            checks[name] = (len(rows) >= 2 and
                len({p['time_boot_ms'] for p in rows}) >= 2 and
                all(p['type_mask'] == mask and p.get('coordinate_frame') == 1 and
                    p.get('target_system') == 7 and p.get('target_component') == 1 and
                    abs(p['yaw']-(math.pi/2-(.25 if pva else 0.))) <= 1e-6 and
                    all(math.isfinite(p[key]) and abs(p[key]-value) <= 1e-6
                    for key, value in zip(('x', 'y', 'z', 'vx', 'vy', 'vz', 'afx', 'afy', 'afz'), values))
                    for p in rows))
    checks['all_windows_observed'] = set(checks) == set(expected) | {'after_stop'}
    return checks


async def scenario(system, invoke, calls, packets, phases, output, recovery_response_fault=None):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        copy_source(root)
        apply(root, REPAIR)
        h = RecoveryHarness(root, output, trigger='expired')
        h.sdk_modules = nullcontext
        h.cache = {'scope': 'not_observed_here_use_wire_packets'}
        h.owner.report.update(flight_accepted=False,
            validation_scope='Real SDK wire; synthetic telemetry, pose, planner and world')
        deferred = False
        relay = None
        recovery_client = system.offboard
        if recovery_response_fault:
            port = json.loads((output/'sdk-process.json').read_text())['grpc_port']
            relay = transport.PositionResponseFault(recovery_response_fault, port)
            h.owner.options['recovery_rpc_timeout_s'] = .5

        def note(event, **fields):
            h.events.append(dict(event=event, host_monotonic_ns=time.monotonic_ns(),
                reference=copy.deepcopy(h.owner.reference), **fields))
        h.note = note

        class OnlySetpoints:
            # No arm/start/land interface is exposed to this fixture executor.
            async def set_position_ned(self, position):
                name = 'flight.recovery_position' if h.owner.recovering else 'flight.initial_position'
                client = recovery_client if h.owner.recovering else system.offboard
                await invoke(name, lambda: client.set_position_ned(position))
            async def set_position_velocity_acceleration_ned(self, position, velocity, acceleration):
                await invoke('flight.pva', lambda: system.offboard.set_position_velocity_acceleration_ned(
                    position, velocity, acceleration))
        h.owner.recovering = False
        h.owner.drone = types.SimpleNamespace(offboard=OnlySetpoints())

        async def deferred_close():
            nonlocal deferred
            deferred = True
            h.note('sdk_cleanup_deferred_to_probe_owner')
        h.owner.close_mavsdk = deferred_close
        fixture = PendingStateHttp(h, root)
        task = None
        evidence = {'state_scope': 'synthetic pose, armed/IN_AIR/OFFBOARD telemetry and scene.pause',
                    'sdk_cleanup_scope': 'deferred to transport owner, not production cleanup acceptance',
                    'physical_pause_confirmed': False, 'flight_accepted': False,
                    'http_port': fixture.server.server_port, 'events': []}

        def mark(name, **fields):
            evidence['events'].append(dict(event=name, host_monotonic_ns=time.monotonic_ns(), **fields))

        async def release_late_response():
            # Keep the original HTTP timeout; a recovery fault can outlast it.
            h.response['setpoint'] = original.command(position=[3., 2., 1.5],
                velocity=[.5, -.2, 0.], acceleration=[-.01, .02, .03], yaw_rad=-.4,
                stamp_sim_s=10.4, source_end_sim_s=11.2, trajectory_id=8)
            (output/'http-late-response.json').write_text(json.dumps(h.response, indent=2)+'\n')
            mark('release_fresh_late_response', stamp_sim_s=10.4, source_end_sim_s=11.2,
                 recovery_still_pending=not task.done())
            fixture.release.set()
            if not await asyncio.to_thread(fixture.client_read_finished.wait, 1.):
                raise RuntimeError('The original HTTP worker did not finish')
            mark('late_http_read_finished', error=fixture.late_error)

        try:
            if relay is not None:
                recovery_client = await relay.start()
                evidence['recovery_response_fault'] = recovery_response_fault
            task = asyncio.create_task(h.run())
            if not await asyncio.to_thread(fixture.entered.wait, 2.):
                raise RuntimeError('Second synthetic state request was not reached')
            mark('second_state_pending', simulation_s=h.clock.sim)
            # Observe actual PVA resend before advancing the fixture's clock.
            await asyncio.sleep(.24)
            pva_calls = [c for c in calls if c['method'] == 'flight.pva']
            if len(pva_calls) != 1:
                raise RuntimeError('Expected exactly one SDK PVA before expiry')
            invalidated = time.monotonic_ns()
            phases.append(('pva_pending', pva_calls[0]['host_end_ns']+100_000_000, invalidated))
            mark('advance_fixture_clock', old_sim_s=h.clock.sim, new_sim_s=10.4)
            h.advance(10.4)
            if relay is not None:
                await asyncio.wait_for(relay.received.wait(), 1.)
                if recovery_response_fault == 'after_forward':
                    await asyncio.wait_for(relay.forwarded.wait(), 1.)
                # Read the late HTTP response before its unchanged .8s timeout,
                # while the distinct recovery RPC is still awaiting its .5s budget.
                await release_late_response()
                evidence['late_http_read_during_recovery_wait'] = not task.done()
            await asyncio.wait_for(asyncio.shield(task), 2.)
            if relay is not None:
                await asyncio.wait_for(relay.cancelled.wait(), 1.)
            mark('flight_fixture_returned', status=h.owner.status,
                 http_still_waiting=not fixture.client_read_finished.is_set())
            recovery_calls = [c for c in calls if c['method'] == 'flight.recovery_position']
            if len(recovery_calls) != 1 or bool(recovery_calls[0].get('returned')) != (relay is None):
                raise RuntimeError('Recovery position result did not match the injection')
            await asyncio.sleep(.22)
            late_release = time.monotonic_ns()
            phases.append(('cache_after_unconfirmed' if relay else 'position_before_late',
                           recovery_calls[0]['host_end_ns']+100_000_000, late_release))
            if relay is None:
                # A fresh, distinct PVA would be eligible if the abandoned await resumed.
                await release_late_response()
            after_late = time.monotonic_ns()
            await asyncio.sleep(.3)
            stop_start = time.monotonic_ns()
            phases.append(('cache_after_late_response' if relay else 'position_after_late',
                           after_late+100_000_000, stop_start))
            stopped = await invoke('probe.offboard_stop', system.offboard.stop)
            await asyncio.sleep(.3)
            phases.append(('after_stop', stopped['host_end_ns']+100_000_000, time.monotonic_ns()))
            evidence.update(status=h.owner.status, wait_failures=h.owner.report.get('command_wait_failures'),
                reference=copy.deepcopy(h.owner.reference), deferred_sdk_cleanup=deferred,
                late_http_received=fixture.late_response == h.response, late_http_error=fixture.late_error)
            evidence['diagnostic_checks'] = wire_checks(packets, phases, recovery_response_fault)
            evidence['diagnostic_checks'].update({
                'source_expiry_observed': h.owner.report.get('command_wait_failures', [{}])[0].get('reason')
                                          == 'cached_command_source_expired',
                'failed_not_landed': h.owner.status == 'failed' and not h.owner.report.get('landed', False),
                'fresh_late_response_received': fixture.late_response == h.response and fixture.late_error is None,
                'single_pva_rpc': sum(c['method'] == 'flight.pva' for c in calls) == 1,
                'cleanup_explicitly_deferred': deferred,
            })
            if relay is None:
                evidence['diagnostic_checks']['position_reference_after_recovery'] = h.owner.reference.get('mode') == 'position'
            else:
                attempt = h.owner.report.get('recovery', {}).get('rpc_attempts', [{}])[-1]
                evidence['recovery_attempt'] = attempt
                evidence['diagnostic_checks'].update({
                    'recovery_effect_unknown': attempt.get('operation') == 'position' and
                        attempt.get('status') == 'unconfirmed' and attempt.get('remote_effect') == 'unknown' and
                        attempt.get('error_type') == 'TimeoutError',
                    'recovery_blocked_not_landed': h.owner.report.get('recovery', {}).get('outcome') == 'blocked' and
                        h.owner.report.get('landed') is False and h.owner.report.get('disarmed') is False,
                    'stale_reference_not_laundered': h.owner.reference.get('mode') == 'position_velocity_acceleration',
                    'planner_stop_not_reached': not any(e.get('path') == '/stop' for e in h.events),
                    'only_one_recovery_attempt': len(recovery_calls) == 1,
                    'cancel_reached_relay': relay.cancelled.is_set(),
                    'late_http_read_during_recovery_wait': evidence['late_http_read_during_recovery_wait'],
                    'forwarding_matches_injection': relay.forwarded.is_set() == (recovery_response_fault == 'after_forward'),
                })
        finally:
            fixture.release.set()
            if task is not None:
                if not task.done(): task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if relay is not None:
                cleanup_errors = await relay.close()
                with socket.socket() as sock:
                    relay_closed = relay.port is not None and sock.connect_ex(('127.0.0.1', relay.port)) != 0
                evidence.update(relay_events=relay.events, relay_port=relay.port, relay_cleanup_errors=cleanup_errors)
                evidence.setdefault('diagnostic_checks', {}).update(relay_closed=relay_closed,
                    relay_cleanup_ok=not cleanup_errors)
            await fixture.close()
            with socket.socket() as sock:
                evidence['http_port_closed'] = sock.connect_ex(('127.0.0.1', fixture.server.server_port)) != 0
            evidence['http_threads_finished'] = (not fixture.worker.is_alive() and
                (not fixture.entered.is_set() or (fixture.finished.is_set() and fixture.client_read_finished.is_set())))
            (output/'flight-events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in h.events))
            evidence.setdefault('diagnostic_checks', {}).update(http_port_closed=evidence['http_port_closed'],
                http_threads_finished=evidence['http_threads_finished'])
            (output/'guard-recovery-scenario.json').write_text(json.dumps(evidence, indent=2, allow_nan=False)+'\n')
        return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--recovery-response-fault', choices=('before_forward', 'after_forward'),
                        help='Withhold only the recovery position response; synthetic peer only')
    args = parser.parse_args()
    return asyncio.run(transport.run(args.output.resolve(), scenario=partial(scenario,
        recovery_response_fault=args.recovery_response_fault)))


if __name__ == '__main__':
    raise SystemExit(main())
