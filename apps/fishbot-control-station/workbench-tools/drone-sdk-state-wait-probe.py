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


def wire_checks(packets, phases):
    """Check active fields on each observed window, including the late reply."""
    expected = {
        'pva_pending': (2048, [0., 1., -1., .1, .2, 0., 0., .01, 0.]),
        'position_before_late': (2552, [0., 0., -1.]),
        'position_after_late': (2552, [0., 0., -1.]),
    }
    checks = {}
    for name, start, end in phases:
        rows = [p for p in packets if p['type'] == 'SET_POSITION_TARGET_LOCAL_NED'
                and start <= p['host_monotonic_ns'] <= end]
        if name == 'after_stop':
            checks[name] = not rows
        else:
            mask, values = expected[name]
            checks[name] = (len(rows) >= 2 and
                len({p['time_boot_ms'] for p in rows}) >= 2 and
                all(p['type_mask'] == mask and p.get('coordinate_frame') == 1 and
                    p.get('target_system') == 7 and p.get('target_component') == 1 and
                    abs(p['yaw']-(math.pi/2-(.25 if name == 'pva_pending' else 0.))) <= 1e-6 and
                    all(math.isfinite(p[key]) and abs(p[key]-value) <= 1e-6
                    for key, value in zip(('x', 'y', 'z', 'vx', 'vy', 'vz', 'afx', 'afy', 'afz'), values))
                    for p in rows))
    checks['all_windows_observed'] = set(checks) == set(expected) | {'after_stop'}
    return checks


async def scenario(system, invoke, calls, packets, phases, output):
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

        def note(event, **fields):
            h.events.append(dict(event=event, host_monotonic_ns=time.monotonic_ns(),
                reference=copy.deepcopy(h.owner.reference), **fields))
        h.note = note

        class OnlySetpoints:
            # No arm/start/land interface is exposed to this fixture executor.
            async def set_position_ned(self, position):
                name = 'flight.recovery_position' if h.owner.recovering else 'flight.initial_position'
                await invoke(name, lambda: system.offboard.set_position_ned(position))
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
        task = asyncio.create_task(h.run())
        evidence = {'state_scope': 'synthetic pose, armed/IN_AIR/OFFBOARD telemetry and scene.pause',
                    'sdk_cleanup_scope': 'deferred to transport owner, not production cleanup acceptance',
                    'physical_pause_confirmed': False, 'flight_accepted': False,
                    'http_port': fixture.server.server_port, 'events': []}

        def mark(name, **fields):
            evidence['events'].append(dict(event=name, host_monotonic_ns=time.monotonic_ns(), **fields))

        try:
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
            await asyncio.wait_for(asyncio.shield(task), 2.)
            mark('flight_fixture_returned', status=h.owner.status,
                 http_still_waiting=not fixture.client_read_finished.is_set())
            recovery_calls = [c for c in calls if c['method'] == 'flight.recovery_position']
            if len(recovery_calls) != 1 or not recovery_calls[0].get('returned'):
                raise RuntimeError('Recovery position RPC did not return exactly once')
            await asyncio.sleep(.22)
            late_release = time.monotonic_ns()
            phases.append(('position_before_late', recovery_calls[0]['host_end_ns']+100_000_000, late_release))
            # A fresh, distinct PVA would be eligible if the abandoned await resumed.
            h.response['setpoint'] = original.command(position=[3., 2., 1.5],
                velocity=[.5, -.2, 0.], acceleration=[-.01, .02, .03], yaw_rad=-.4,
                stamp_sim_s=10.4, source_end_sim_s=11.2, trajectory_id=8)
            (output/'http-late-response.json').write_text(json.dumps(h.response, indent=2)+'\n')
            mark('release_fresh_late_response', stamp_sim_s=10.4, source_end_sim_s=11.2)
            fixture.release.set()
            if not await asyncio.to_thread(fixture.client_read_finished.wait, 1.):
                raise RuntimeError('The original HTTP worker did not finish')
            mark('late_http_read_finished', error=fixture.late_error)
            after_late = time.monotonic_ns()
            await asyncio.sleep(.3)
            stop_start = time.monotonic_ns()
            phases.append(('position_after_late', after_late+100_000_000, stop_start))
            stopped = await invoke('probe.offboard_stop', system.offboard.stop)
            await asyncio.sleep(.3)
            phases.append(('after_stop', stopped['host_end_ns']+100_000_000, time.monotonic_ns()))
            evidence.update(status=h.owner.status, wait_failures=h.owner.report.get('command_wait_failures'),
                reference=copy.deepcopy(h.owner.reference), deferred_sdk_cleanup=deferred,
                late_http_received=fixture.late_response == h.response, late_http_error=fixture.late_error)
            evidence['diagnostic_checks'] = wire_checks(packets, phases)
            evidence['diagnostic_checks'].update({
                'source_expiry_observed': h.owner.report.get('command_wait_failures', [{}])[0].get('reason')
                                          == 'cached_command_source_expired',
                'failed_not_landed': h.owner.status == 'failed' and not h.owner.report.get('landed', False),
                'fresh_late_response_received': fixture.late_response == h.response and fixture.late_error is None,
                'single_pva_rpc': sum(c['method'] == 'flight.pva' for c in calls) == 1,
                'position_reference_after_recovery': h.owner.reference.get('mode') == 'position',
                'cleanup_explicitly_deferred': deferred,
            })
        finally:
            fixture.release.set()
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)
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
    args = parser.parse_args()
    return asyncio.run(transport.run(args.output.resolve(), scenario=scenario))


if __name__ == '__main__':
    raise SystemExit(main())
