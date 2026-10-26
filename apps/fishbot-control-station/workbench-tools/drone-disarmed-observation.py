#!/usr/bin/env python3
"""Finite disarmed observations using the existing Flight startup and PX4 listener.

This is a transport observation, not a flight or candidate-adoption acceptance.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time


SETPOINT_TIMEOUT_S = 4.

TOPICS = ('offboard_control_mode', 'trajectory_setpoint', 'position_control_handoff',
          'mavlink_setpoint_ingress', 'vehicle_control_mode', 'vehicle_status')



async def close_owned(flight, runtime):
    """Finish owned cleanup even if the parent Flight finally was cancelled."""
    errors = []
    if flight is not None:
        for task in flight.tasks:
            task.cancel()
        await asyncio.gather(*flight.tasks, return_exceptions=True)
        server = getattr(getattr(flight, 'drone', None), '_server_process', None)
        if server is not None and server.poll() is None:
            try:
                await asyncio.wait_for(flight.close_mavsdk(), timeout=8.)
            except Exception as error:
                errors.append('mavsdk cleanup: '+type(error).__name__+': '+str(error))
    try:
        await asyncio.to_thread(runtime.close)
    except Exception as error:
        errors.append('SITL cleanup: '+type(error).__name__+': '+str(error))
    return errors


def collector_type(Flight):
    class DisarmedObservation(Flight):
        request_offboard = False
        armed_received_s = None
        armed_seen_true = False
        armed_stream_ended = False

        async def stream(self, name, generator):
            async def stamped():
                try:
                    async for value in generator:
                        if name == 'armed':
                            self.armed_received_s = time.monotonic()
                            self.armed_seen_true = self.armed_seen_true or bool(value)
                            self.report.setdefault('armed_stream_events', []).append({
                                'armed': bool(value), 'host_monotonic_s': self.armed_received_s,
                                'simulation_s': self.observer.simulation_s})
                        yield value
                finally:
                    if name == 'armed':
                        self.armed_stream_ended = True
            return await super().stream(name, stamped())

        def require_disarmed(self):
            age = None if self.armed_received_s is None else time.monotonic()-self.armed_received_s
            if self.telemetry.get('armed') is not False or self.armed_seen_true or self.armed_stream_ended:
                raise RuntimeError('Disarmed observation lost; no further setpoints')
            # Armed streams may emit only on change; their age is not a heartbeat.
            self.report.setdefault('armed_stream_emission_ages_s', []).append(age)
            self.check_startup_processes()

        async def recover(self, *args, **kwargs):
            # This diagnostic has no movement or landing recovery authority.
            raise RuntimeError('No motion recovery in disarmed observation; close owned simulation')

        async def land(self, *args, **kwargs):
            raise RuntimeError('No landing action in disarmed observation')

        async def return_home(self, *args, **kwargs):
            raise RuntimeError('No return-home action in disarmed observation')

        async def native(self, module, *arguments):
            binary = Path(os.environ['DRONE_CACHE'])/'PX4-Autopilot/build/px4_sitl_default/bin'/('px4-'+module)
            record = {'command': [str(binary), '--instance', str(self.runtime['instance']), *arguments],
                      'host_start_ns': time.monotonic_ns(), 'sim_before_s': self.observer.simulation_s}
            try:
                result = await asyncio.to_thread(subprocess.run, record['command'], text=True,
                    capture_output=True, timeout=3)
                record.update(exit_code=result.returncode, raw=result.stdout+result.stderr)
            except (OSError, subprocess.TimeoutExpired) as error:
                record.update(exit_code=None, error=type(error).__name__+': '+str(error), raw='')
            record.update(host_end_ns=time.monotonic_ns(), sim_after_s=self.observer.simulation_s)
            # These are query bounds, not calibrated source-clock correspondences.
            with (self.output/'native-observations.jsonl').open('a') as stream:
                stream.write(json.dumps(record, ensure_ascii=False)+'\n')
            return record

        async def snapshots(self, phase):
            results = await asyncio.gather(*(self.native('listener', topic, '-n', '1') for topic in TOPICS))
            for topic, record in zip(TOPICS, results):
                record.update(topic=topic, phase=phase)
                record['topic_observed'] = (record['exit_code'] == 0 and ('TOPIC: '+topic) in record['raw'])
            self.report['disarmed_observation']['snapshots'].extend(results)
            self.require_disarmed()

        async def connect(self):
            await super().connect()
            self.require_disarmed()
            observation = {'scope': 'isolated startup and disarmed transport observation',
                'snapshots': [], 'calls': [], 'flight_accepted': False,
                'candidate_adoption': 'not_proven', 'clock_correspondence': 'not_calibrated',
                'collection_completed': False, 'offboard_started': False, 'arm_requested': False}
            self.report['disarmed_observation'] = observation
            self.set_phase('disarmed_observation', '未解锁发送及PX4原生观测；仅按显式选项切换模式')
            observation['logger_on'] = await self.native('logger', 'on')
            try:
                for phase, velocity, acceleration in [('position', None, None),
                        ('pva', [.12, -.08, .06], [.03, .02, -.01]), ('clear_position', None, None)]:
                    if phase == 'pva' and self.request_offboard:
                        await asyncio.sleep(.6)
                        self.require_disarmed()
                        observation['offboard_start_requested'] = True
                        await asyncio.wait_for(self.drone.offboard.start(), timeout=SETPOINT_TIMEOUT_S)
                        self.offboard = True
                        observation['offboard_started'] = True
                        self.require_disarmed()
                    for sample in range(6):
                        self.require_disarmed()
                        position = list(self.pose['position'])
                        await asyncio.wait_for(self.setpoint(position, yaw=.25, velocity=velocity, acceleration=acceleration,
                            observation_context={'probe_phase': phase, 'probe_sample': sample}), timeout=SETPOINT_TIMEOUT_S)
                        self.require_disarmed()
                        observation['calls'].append({'phase': phase, 'sample': sample,
                            'host_monotonic_ns': time.monotonic_ns(),
                            'simulation_s': self.observer.simulation_s, 'armed': self.telemetry['armed'],
                            'landed': self.telemetry.get('landed'), 'reference': dict(self.reference)})
                        await asyncio.sleep(.1)
                    await self.snapshots(phase)
                observation['logger_status'] = await self.native('logger', 'status')
            finally:
                try:
                    if observation.get('offboard_start_requested') and self.telemetry.get('armed') is False and not self.armed_seen_true and not self.armed_stream_ended:
                        await asyncio.wait_for(self.drone.offboard.stop(), timeout=SETPOINT_TIMEOUT_S)
                        self.offboard = False
                        observation['offboard_stop_returned'] = True
                finally:
                    observation['logger_off'] = await self.native('logger', 'off')
            self.require_disarmed()
            observation['collection_completed'] = True
    return DisarmedObservation


async def run(args):
    source = args.drone_source.resolve()
    mesh = Path(os.environ['DRONE_CACHE'])/'mesh-libs'
    if mesh.is_dir():
        os.environ['PYTHONPATH'] = str(mesh)+os.pathsep+os.environ.get('PYTHONPATH', '')
    sys.path.insert(0, str(source))
    from flight import Flight, atomic_json
    from sitl import SITL
    from preflight import process_alive
    output = args.output.resolve()
    setup = json.loads((output/'collection-setup.json').read_text())
    request = {'id': setup['run_id'], 'station': {'name': 'Disarmed handoff observation', 'platform': 'px4',
        'flight': {'planner': 'ego', 'instance': args.instance, 'speed_m_s': 2.,
                  'ego_url': 'http://127.0.0.1:'+str(args.ego_port),
                  'initialization_timeout_s': 90,
                  'acceptance': {'max_altitude_m': 2.2, 'position_tolerance_m': .3, 'min_clearance_m': .25}},
        'nodes': [{'id': 'base', 'kind': 'robot', 'parent': 'world', 'position': [5., 0., 0.]}],
        'program': []}}
    atomic_json(output/'request.json', request)
    runtime = SITL(output, request['station']['flight'], request['id'], [5., 0., 0.])
    flight = None
    startup_and_cleanup_ok = False
    manifest = {}
    startup_error = None
    try:
        dependencies = subprocess.run(['/usr/bin/python3', '-c', 'import rclpy, numpy, trimesh, rtree, collada; print(\"sidecar imports available\")'],
            text=True, capture_output=True, timeout=10)
        atomic_json(output/'startup-dependencies.json', {'exit_code': dependencies.returncode,
            'raw': dependencies.stdout+dependencies.stderr, 'mesh_path': str(mesh)})
        if dependencies.returncode:
            raise RuntimeError('Required sidecar imports unavailable: '+dependencies.stderr[-1000:])
        manifest = runtime.start()
        flight = collector_type(Flight)(request, output, output/'cancel.json', output/'return-home.json', manifest)
        flight.request_offboard = args.request_offboard
        startup_and_cleanup_ok = await asyncio.wait_for(
            flight.run(close_runtime=runtime.close, preflight_only=True), timeout=240.)
    except Exception as error:
        startup_error = type(error).__name__+': '+str(error)
    finally:
        cleanup_errors = await close_owned(flight, runtime)
    report = {} if flight is None else flight.report
    report['collector_cleanup_errors'] = cleanup_errors
    atomic_json(output/'report.json', report)
    observation = report.get('disarmed_observation', {})
    rows = [json.loads(line) for line in (output/'telemetry.jsonl').read_text().splitlines()] if (output/'telemetry.jsonl').exists() else []
    armed = [row.get('telemetry', {}).get('armed') for row in rows]
    identities = dict(manifest.get('processes', {}))
    sdk = report.get('mavsdk_server', {})
    if sdk.get('pid'):
        identities['mavsdk'] = sdk
    identity_checks = {}
    for name, identity in identities.items():
        alive, reason = process_alive(identity.get('pid'), identity.get('start_ticks'))
        identity_checks[name] = {'alive': alive if reason != 'identity_not_recorded' else None, 'reason': reason}
    cleanup = {name: check['alive'] for name, check in identity_checks.items()}
    cleanup_confirmed = bool(identity_checks) and all(check['reason'] in ('pid_not_running', 'pid_zombie', 'pid_reused') for check in identity_checks.values())
    summary = {'task_id': request['id'], 'startup_and_cleanup_ok': startup_and_cleanup_ok,
        'collection_completed': observation.get('collection_completed', False),
        'armed_observations': {'false': armed.count(False), 'true': armed.count(True), 'unknown': armed.count(None)},
        'native_topics': {topic: [row['phase'] for row in observation.get('snapshots', []) if row['topic'] == topic and row['topic_observed']] for topic in TOPICS},
        'setpoint_calls_returned': len(observation.get('calls', [])),
        'owned_processes_alive_after_cleanup': cleanup, 'process_identity_checks': identity_checks,
        'cleanup_confirmed': cleanup_confirmed, 'cleanup_errors': cleanup_errors, 'startup_error': startup_error,
        'flight_accepted': False, 'candidate_adoption': 'not_proven',
        'clock_correspondence': 'not_calibrated', 'report': str(output/'report.json')}
    atomic_json(output/'disarmed-observation.json', summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    # Exit is for collection/cleanup only; absent consumption is preserved in the report.
    return 0 if startup_and_cleanup_ok and summary['collection_completed'] and armed.count(False) and not armed.count(True) and cleanup_confirmed and not cleanup_errors else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--drone-source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--instance', type=int, default=6)
    parser.add_argument('--ego-port', type=int, default=8792)
    parser.add_argument('--request-offboard', action='store_true', help='Request only the mode, while disarmed; never arm')
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == '__main__':
    sys.exit(main())
