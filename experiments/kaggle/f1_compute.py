#!/usr/bin/env python3
"""Compare unused native rangefinders without ROS goals or task acceptance."""
import cProfile
import io
import json
import pstats
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from cooperation_sim import Physics
from cooperation_lidar import NativeCloudQuery, configuration


def error(a, b):
    a, b = np.asarray(a), np.asarray(b)
    if a.shape != b.shape or not (np.isfinite(a).all() and np.isfinite(b).all()):
        return float('inf')
    return float(np.max(np.abs(a-b), initial=0.))


def restore(physics, fixture):
    physics.mj.mj_resetData(physics.model, physics.data)
    for key in ('qpos', 'qvel', 'ctrl'):
        getattr(physics.data, key)[:] = fixture[key]
    physics.data.time = fixture['stamp']
    physics.reference = tuple(fixture['arm_reference_q6'])
    physics.mj.mj_forward(physics.model, physics.data)


def imu(physics):
    return np.concatenate([physics.data.sensordata[
        physics.model.sensor(name).adr[0]:
        physics.model.sensor(name).adr[0]+physics.model.sensor(name).dim[0]]
        for name in ('imu_quat', 'imu_gyro', 'imu_accel')])


def forces(physics):
    output = np.empty((physics.data.ncon, 6))
    for index in range(physics.data.ncon):
        physics.mj.mj_contactForce(physics.model, physics.data, index, output[index])
    return output


def main(manifest_path, fixtures_path, output_path):
    manifest = json.loads(Path(manifest_path).read_text())
    output = Path(output_path); output.mkdir(parents=True, exist_ok=True)
    original = Path(manifest['world_xml'])
    tree = ET.parse(original)
    removed = []
    for block in tree.getroot().findall('sensor'):
        for sensor in list(block):
            if sensor.tag == 'rangefinder':
                removed.append(dict(sensor.attrib)); block.remove(sensor)
    candidate = original.with_name('compute-without-unused-rangefinders.xml')
    tree.write(candidate, encoding='unicode')
    candidate_manifest = candidate.with_suffix('.json')
    candidate_manifest.write_text(json.dumps({**manifest, 'world_xml': str(candidate),
        'compute_variant': 'omit_unused_native_rangefinders'}, indent=2)+'\n')
    pair = [Physics(original, manifest=manifest_path), Physics(candidate, manifest=candidate_manifest)]
    a, b = pair
    static = {field: np.array_equal(getattr(a.model, field), getattr(b.model, field))
              for field in ('body_mass', 'body_inertia', 'body_pos', 'body_quat',
                  'geom_type', 'geom_size', 'geom_pos', 'geom_quat', 'geom_friction',
                  'geom_contype', 'geom_conaffinity', 'geom_solref', 'geom_solimp',
                  'jnt_range', 'jnt_stiffness', 'actuator_gear', 'actuator_gainprm',
                  'actuator_biasprm', 'actuator_ctrlrange', 'actuator_forcerange')}
    static.update({field: getattr(a.model.opt, field) == getattr(b.model.opt, field)
                   for field in ('timestep', 'integrator', 'solver', 'iterations',
                                 'tolerance', 'noslip_iterations', 'disableflags', 'enableflags')})
    counts = [{key: int(getattr(p.model, key)) for key in
               ('nq', 'nv', 'nu', 'nbody', 'ngeom', 'nsite', 'nsensor', 'nsensordata')} for p in pair]
    fixtures = json.loads(Path(fixtures_path).read_text())
    cloud_config = configuration(manifest)
    queries = [NativeCloudQuery(path, cloud_config) for path in (original, candidate)]
    cases = []
    for fixture in fixtures:
        row = {'label': fixture['label'], 'origin': fixture.get('origin'), 'source_stamp': fixture['stamp']}
        try:
            for p in pair: restore(p, fixture)
            maximum = {key: 0. for key in ('qpos', 'qvel', 'qacc', 'actuator_force', 'qfrc_constraint', 'xpos')}
            elapsed, cpu = [0., 0.], [0., 0.]
            for _ in range(200):
                for index, p in enumerate(pair):
                    start, thread = time.perf_counter(), time.thread_time()
                    p.mj.mj_step(p.model, p.data)
                    elapsed[index] += time.perf_counter()-start
                    cpu[index] += time.thread_time()-thread
                for key in maximum:
                    maximum[key] = max(maximum[key], error(getattr(a.data, key), getattr(b.data, key)))
            row.update(steps=200, maximum_absolute_errors=maximum,
                       native_step_mean_ms=[value/200*1000 for value in elapsed],
                       native_step_thread_cpu_ms=[value/200*1000 for value in cpu],
                       imu_error=error(imu(a), imu(b)), contact_force_error=error(forces(a), forces(b)),
                       scan_360_equal=np.array_equal(a.scan(), b.scan(), equal_nan=True))
            snapshots = [{'qpos': p.data.qpos.copy(), 'qvel': p.data.qvel.copy(),
                          'stamp': float(p.data.time)} for p in pair]
            clouds = [q.compute(snapshot) for q, snapshot in zip(queries, snapshots)]
            row['cloud_5760_equal'] = bool(
                np.array_equal(clouds[0]['points'], clouds[1]['points'], equal_nan=True)
                and np.array_equal(clouds[0]['raw_points'], clouds[1]['raw_points'], equal_nan=True)
                and np.array_equal(queries[0].hit, queries[1].hit))
            row['cloud_shape'] = list(clouds[0]['points'].shape)
            row['cloud_raw_returns'] = [c['raw_valid_points'] for c in clouds]
            row['equivalent'] = bool(max(maximum.values()) <= 1e-12 and row['imu_error'] <= 1e-12
                and row['contact_force_error'] <= 1e-12 and row['scan_360_equal'] and row['cloud_5760_equal'])
        except (ValueError, RuntimeError, KeyError) as exc:
            row.update(equivalent=False, error=type(exc).__name__+': '+str(exc))
            print('WARNING:', row['label'], row['error'], flush=True)
        cases.append(row)
    profiles = []
    for name, p in zip(('original', 'without_unused_rangefinders'), pair):
        restore(p, fixtures[0])
        profiler = cProfile.Profile(); profiler.enable()
        for _ in range(500): p.step()
        profiler.disable(); profiler.dump_stats(str(output/(name+'.prof')))
        buffer = io.StringIO(); pstats.Stats(profiler, stream=buffer).sort_stats('cumulative').print_stats(30)
        (output/(name+'-profile.txt')).write_text(buffer.getvalue())
        start = time.perf_counter()
        for _ in range(200): json.dumps(p.state(), separators=(',', ':'))
        profiles.append({'variant': name, 'state_and_json_mean_ms': (time.perf_counter()-start)/200*1000,
                         'profile_file': name+'-profile.txt'})
    result = {'kind': 'f1_rangefinder_compute_ablation', 'task_acceptance': False,
              'navigation_goals': 0, 'actuator_topics_published': False,
              'fixture_scope': 'reconstructed observation states, not exact live continuation or delivery scoring',
              'removed_xml_declarations': removed, 'compiled_counts': counts,
              'physical_model_equal': {key: bool(value) for key, value in static.items()},
              'cases': cases, 'profiles': profiles,
              'equivalent': bool(removed and fixtures and all(static.values())
                                 and len(cases) == len(fixtures) and all(row['equivalent'] for row in cases)),
              'lidar_config_preserved': cloud_config,
              'boundary': 'Only unused native rangefinder declarations differ; original physics and used rays/IMU checked.'}
    (output/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main(*sys.argv[1:])
