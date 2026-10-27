#!/usr/bin/env python3
"""Real SDK cache probe against a synthetic local MAVLink peer, never a vehicle."""
import argparse
import asyncio
import json
import logging
import math
from pathlib import Path
import socket
import subprocess
import time


def free_port(kind):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def summarize(packets, phases):
    result = {}
    for name, start, end in phases:
        rows = [p for p in packets if start <= p['host_monotonic_ns'] <= end and p['type'] == 'SET_POSITION_TARGET_LOCAL_NED']
        result[name] = {'window_host_ns': [start, end], 'packets': len(rows),
                        'masks': sorted({p['type_mask'] for p in rows}),
                        'distinct_wire_times': len({p['time_boot_ms'] for p in rows}),
                        'distinct_pva': len({tuple(p[k] for k in ('x', 'y', 'z', 'vx', 'vy', 'vz', 'afx', 'afy', 'afz')) for p in rows})}
    return result


async def close_sdk_process(process):
    errors = []
    if process is None:
        return errors
    try:
        if process.poll() is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.to_thread(process.wait, timeout=3.)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await asyncio.to_thread(process.wait, timeout=3.)
    except Exception as error:
        errors.append('SDK cleanup: '+type(error).__name__+': '+str(error))
    return errors


async def run(output):
    from mavsdk_grpc import System
    from mavsdk_grpc.offboard import PositionNedYaw, VelocityNedYaw, AccelerationNed
    from pymavlink.dialects.v20 import common as mavlink
    output.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=output/'sdk.log', level=logging.INFO)
    sdk_udp, grpc_port = free_port(socket.SOCK_DGRAM), free_port(socket.SOCK_STREAM)
    peer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    peer.bind(('127.0.0.1', 0))
    peer.setblocking(False)
    loop = asyncio.get_running_loop()
    packets, calls, phases, errors = [], [], [], []

    class Writer:
        def write(self, data):
            peer.sendto(data, ('127.0.0.1', sdk_udp))

    encoder = mavlink.MAVLink(Writer(), srcSystem=7, srcComponent=1)
    parser = mavlink.MAVLink(None)

    async def heartbeat():
        while True:
            # Deliberately synthetic, unarmed PX4-style Offboard heartbeat.
            encoder.heartbeat_send(mavlink.MAV_TYPE_QUADROTOR, mavlink.MAV_AUTOPILOT_PX4,
                mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, 6 << 16, mavlink.MAV_STATE_STANDBY)
            await asyncio.sleep(.1)

    async def receive():
        while True:
            data, _ = await loop.sock_recvfrom(peer, 65535)
            for msg in parser.parse_buffer(data) or []:
                row = dict(msg.to_dict(), host_monotonic_ns=time.monotonic_ns(),
                           sender_system=msg.get_srcSystem(), sender_component=msg.get_srcComponent(),
                           message_sequence=msg.get_seq(), type=msg.get_type())
                row['nonfinite_fields'] = [key for key, value in row.items()
                    if isinstance(value, float) and not math.isfinite(value)]
                packets.append(row)
                if msg.get_type() == 'COMMAND_LONG':
                    # Fixture ACKs are not PX4 acceptance; reject every arm request.
                    encoder.command_ack_send(msg.command,
                        mavlink.MAV_RESULT_DENIED if msg.command == 400 else mavlink.MAV_RESULT_ACCEPTED,
                        target_system=msg.get_srcSystem(), target_component=msg.get_srcComponent())
                    if msg.command == 512 and int(msg.param1) == 148:
                        encoder.autopilot_version_send(mavlink.MAV_PROTOCOL_CAPABILITY_MAVLINK2,
                            0, 0, 0, 0, [0]*8, [0]*8, [0]*8, 0, 0, 0)

    system = System(port=grpc_port)
    tasks = [asyncio.create_task(heartbeat()), asyncio.create_task(receive())]
    sdk_process = None
    started = time.monotonic_ns()

    async def invoke(name, function):
        row = {'method': name, 'host_start_ns': time.monotonic_ns()}
        calls.append(row)
        try:
            await asyncio.wait_for(function(), timeout=5.)
            row['returned'] = True
        except Exception as error:
            row['error'] = type(error).__name__+': '+str(error)
            raise
        finally:
            row['host_end_ns'] = time.monotonic_ns()
        return row

    try:
        await asyncio.wait_for(system.connect(system_address=f'udpin://127.0.0.1:{sdk_udp}'), timeout=10.)
        sdk_process = system._server_process
        (output/'sdk-process.json').write_text(json.dumps({'pid': sdk_process.pid,
            'sdk_udp_port': sdk_udp, 'grpc_port': grpc_port,
            'argv': sdk_process.args, 'scope': 'synthetic peer only'}, indent=2)+'\n')
        listener_record = {'client_connects_to': '127.0.0.1',
                           'bind_scope_is_observation_not_client_assumption': True}
        try:
            listeners = subprocess.run(['ss', '-H', '-ltnp'], text=True, capture_output=True, timeout=2.)
            listener_record.update(exit_code=listeners.returncode,
                matching_grpc_listener=[line for line in listeners.stdout.splitlines() if f':{grpc_port} ' in line])
        except (OSError, subprocess.TimeoutExpired) as error:
            listener_record['warning'] = type(error).__name__+': '+str(error)
        (output/'sdk-listeners.json').write_text(json.dumps(listener_record, indent=2)+'\n')
        async def connected():
            async for state in system.core.connection_state():
                if state.is_connected:
                    return
        await asyncio.wait_for(connected(), timeout=10.)
        pva = await invoke('set_position_velocity_acceleration_ned', lambda:
            system.offboard.set_position_velocity_acceleration_ned(
                PositionNedYaw(.1, .2, -.3, 15.), VelocityNedYaw(.12, -.08, .06, 15.),
                AccelerationNed(.03, .02, -.01)))
        await asyncio.sleep(.65)  # No setter call during this observation window.
        position_start = time.monotonic_ns()
        phases.append(('pva_without_new_rpc', pva['host_end_ns']+100_000_000, position_start))
        position = await invoke('set_position_ned', lambda: system.offboard.set_position_ned(PositionNedYaw(.1, .2, -.3, 15.)))
        await asyncio.sleep(.55)
        stop_start = time.monotonic_ns()
        phases.append(('position_replaced_pva', position['host_end_ns']+100_000_000, stop_start))
        stopped = await invoke('stop', system.offboard.stop)
        await asyncio.sleep(.4)
        phases.append(('after_stop', stopped['host_end_ns']+100_000_000, time.monotonic_ns()))
    except Exception as error:
        errors.append(type(error).__name__+': '+str(error))
    finally:
        for task in tasks:
            task.cancel()
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        errors.extend(type(value).__name__+': '+str(value) for value in outcomes
                      if isinstance(value, Exception) and not isinstance(value, asyncio.CancelledError))
        peer.close()
        sdk_process = sdk_process or getattr(system, '_server_process', None)
        errors.extend(await close_sdk_process(sdk_process))
        system._server_process = None
        system = None
    summary = {'scope': 'real SDK and synthetic MAVLink peer; no PX4/Gazebo/flight',
        'host_started_ns': started, 'sdk_udp_port': sdk_udp, 'grpc_port': grpc_port,
        'rpc_calls': calls, 'phase_results': summarize(packets, phases), 'errors': errors,
        'arm_command_count': sum(p.get('command') == 400 for p in packets if p['type'] == 'COMMAND_LONG'),
        'sdk_pid': None if sdk_process is None else sdk_process.pid,
        'sdk_exit_code': None if sdk_process is None else sdk_process.poll(),
        'candidate_expiry_enforced': 'not_implemented_by_this_probe', 'px4_acceptance': 'not_tested',
        'synthetic_peer_acknowledgements': True, 'flight_accepted': False}
    (output/'sdk-cache-probe.json').write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n')
    (output/'sdk-cache-peer.jsonl').write_text(''.join(json.dumps(json_safe(p), allow_nan=False)+'\n' for p in packets))
    print(json.dumps(summary, indent=2))
    return int(bool(errors) or len(phases) != 3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    return asyncio.run(run(args.output.resolve()))


if __name__ == '__main__':
    raise SystemExit(main())
