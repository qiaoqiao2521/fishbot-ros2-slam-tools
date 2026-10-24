#!/usr/bin/env python3
"""Native R1 restoration fixtures; no ROS, navigation, or grasp acceptance."""
import argparse
import json
import math
from pathlib import Path
import time

import numpy as np

from cooperation_checkpoint import (capture, restore, signature, write_checkpoint,
                                    read_checkpoint)
from cooperation_scene import build_scene
from cooperation_sim import Physics


def native_state(plant):
    spec = int(plant.mj.mjtState.mjSTATE_INTEGRATION)
    state = np.empty(plant.mj.mj_stateSize(plant.model, spec))
    plant.mj.mj_getState(plant.model, plant.data, state, spec)
    return state


def loaded_fixture(plant):
    """Initial condition only, before the first source step; no live teleport."""
    plant.mj.mj_forward(plant.model, plant.data)
    floor = plant.tray_floor
    center = plant.data.geom_xpos[floor].copy()
    center[2] += plant.model.geom_size[floor, 2]+plant.model.geom_size[plant.cargo_geom, 2]+.001
    offset = int(plant.model.jnt_qposadr[plant.model.joint('target_free').id])
    plant.data.qpos[offset:offset+7] = [*center, 1., 0., 0., 0.]
    plant.refresh_snapshot()


def sensor_tick(plant):
    if plant.steps % 10 == 0:
        plant.refresh_snapshot()
        return plant.observe_station()
    return None


def replay_control(plant, case, index):
    if case == 'nonzero_wheels':
        plant.wheels.accept(.025 if index < 6000 else -.015 if index < 8000 else 0.,
                            0., time.monotonic())
    if case == 'material_and_force':
        plant.data.xfrc_applied[plant.car_body, 0] = .15 if index < 2500 else 0.


def run_case(scene, manifest_path, case, output, steps):
    a = Physics(scene, manifest=manifest_path)
    if case != 'free_cargo_rest':
        loaded_fixture(a)
    if case == 'material_and_force':
        planes = np.where(a.model.geom_type == a.mj.mjtGeom.mjGEOM_PLANE)[0]
        a.model.geom_friction[planes, 0] = .25
        a.model.geom_priority[planes] = 10
        a.data.xfrc_applied[a.car_body, 0] = .15
    if case == 'nonzero_wheels':
        a.wheels.set_hold(False)
    for i in range(500):
        replay_control(a, case, i)
        a.step()
        sensor_tick(a)
    a.refresh_snapshot()
    # Static model preparation happens outside the running step boundary.
    signature(a)
    copies = [capture(a, context={'fixture': case}) for _ in range(5)]
    snapshot = copies[-1]
    folder = output/case
    folder.mkdir()
    wrote = write_checkpoint(folder/'checkpoint.json', snapshot)
    stored = read_checkpoint(folder/'checkpoint.json')
    b = Physics(scene, manifest=manifest_path)
    restored = restore(b, stored)
    if not restored['restored']:
        return {'id': case, 'passed': False, 'restore': restored}
    initial_error = float(np.max(np.abs(native_state(a)-native_state(b))))
    maxima = {'integration_state': initial_error, 'qpos': 0., 'qvel': 0.,
              'cargo_position_m': 0., 'car_position_m': 0.,
              'encoder_pose': 0., 'contact_normal_force_n': 0.}
    observation_mismatches = ray_mismatches = contact_mismatches = 0
    material_contact_friction = []
    actual_impulse = 0.
    start = time.monotonic()
    for i in range(steps):
        for plant in (a, b):
            replay_control(plant, case, i)
            plant.step()
        actual_impulse += float(a.data.xfrc_applied[a.car_body, 0])*a.model.opt.timestep
        maxima['integration_state'] = max(maxima['integration_state'],
            float(np.max(np.abs(native_state(a)-native_state(b)))))
        maxima['qpos'] = max(maxima['qpos'], float(np.max(np.abs(a.data.qpos-b.data.qpos))))
        maxima['qvel'] = max(maxima['qvel'], float(np.max(np.abs(a.data.qvel-b.data.qvel))))
        for label, body in [('cargo_position_m', a.cargo_body), ('car_position_m', a.car_body)]:
            maxima[label] = max(maxima[label], float(np.linalg.norm(a.data.xpos[body]-b.data.xpos[body])))
        maxima['encoder_pose'] = max(maxima['encoder_pose'],
            max(abs(getattr(a.odom, key)-getattr(b.odom, key)) for key in ('x', 'y', 'yaw')))
        observation_mismatches += sensor_tick(a) != sensor_tick(b)
        contact_mismatches += a.data.ncon != b.data.ncon
        maxima['contact_normal_force_n'] = max(maxima['contact_normal_force_n'],
            abs(a.contacts['cargo_tray_floor_normal_force_n']-b.contacts['cargo_tray_floor_normal_force_n']))
        if a.steps % 50 == 0:
            ray_mismatches += not np.array_equal(a.scan(), b.scan())
        if case == 'material_and_force' and i % 100 == 0:
            material_contact_friction.extend(float(c.friction[0]) for c in a.data.contact)
    checks = {'restore_readback': initial_error <= 1e-10,
              'native_and_owned_state': all(value <= 1e-8 for value in maxima.values()),
              'sensor_rng_and_phase': observation_mismatches == ray_mismatches == 0,
              'derived_contacts': contact_mismatches == 0,
              'full_declared_steps': steps >= 10000,
              'time_matches': a.data.time == b.data.time,
              'material_and_force_restored': case != 'material_and_force' or
                    (np.array_equal(a.model.geom_friction, b.model.geom_friction) and actual_impulse > .7)}
    return {'id': case, 'passed': all(checks.values()), 'checks': checks,
            'snapshot_id': snapshot['snapshot_id'], 'restore': restored,
            'steps_per_branch': steps, 'source_s': steps*a.model.opt.timestep,
            'max_errors': maxima, 'observation_mismatches': observation_mismatches,
            'ray_mismatches': ray_mismatches, 'contact_count_mismatches': contact_mismatches,
            'actual_force_impulse_ns': actual_impulse,
            'sampled_contact_friction': sorted(set(material_contact_friction)),
            'capture_copy_wall_s': [item['capture_copy_wall_s'] for item in copies],
            'checkpoint_io': wrote, 'comparison_wall_s': time.monotonic()-start,
            'fixture_scope': 'initial cargo placement is not a real arm handover'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--steps', type=int, default=10000)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    manifest = build_scene(root.parent/'so101', root, args.output/'scene', spawn=(-.7, -1.5),
                           scene_profile={'vehicle': 'jackal_j100', 'sensors': 'lidar3d'})
    from cooperation_perception import normalize_config
    manifest['station_perception'] = normalize_config({'mode':'perturbed', 'seed':47,
        'max_covariance':[.001,.001,.001], 'noise_std':[.001,.001,.002]})
    path = args.output/'scene/scene-manifest.json'
    path.write_text(json.dumps(manifest, indent=2)+'\n')
    from cooperation_factory import loaded_code_reference,save
    sources=[Path(__file__),Path(build_scene.__code__.co_filename),
             Path(normalize_config.__code__.co_filename)]
    sources.extend(Path(p) for p in manifest['source_sha256'] if Path(p).suffix=='.py')
    before=loaded_code_reference(extra_paths=sources)
    inputs={'world_xml':Path(manifest['world_xml']).read_text(),'manifest':path.read_text()}
    save(args.output/'loaded-code-start.json',before)
    save(args.output/'inputs-start.json',inputs)
    result = {'scope': 'R1 physical state fixtures; not ROS, navigation or transport acceptance',
              'declared_steps_per_case_per_branch': args.steps,
              'thresholds': {'initial_state':1e-10, 'max_state_and_contact_error':1e-8},
              'cases': [], 'passed': False}
    for case in ('free_cargo_rest', 'loaded_rest', 'nonzero_wheels', 'material_and_force'):
        try:
            item = run_case(manifest['world_xml'], path, case, args.output, args.steps)
        except Exception as error:
            import traceback
            item = {'id': case, 'passed': False, 'error':str(error), 'traceback':traceback.format_exc()}
        result['cases'].append(item)
        (args.output/'result.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps({k:item.get(k) for k in ('id','passed','max_errors','error')}), flush=True)
    result['passed'] = len(result['cases']) == 4 and all(row['passed'] for row in result['cases'])
    after=loaded_code_reference(extra_paths=sources)
    final_inputs={'world_xml':Path(manifest['world_xml']).read_text(),'manifest':path.read_text()}
    save(args.output/'loaded-code-end.json',after)
    save(args.output/'inputs-end.json',final_inputs)
    result['code_observation']={'selected_text_unchanged':
        before['selected_source_text']==after['selected_source_text'],
        'observation_errors':before['observation_errors']+after['observation_errors'],
        'source_change_blocks_execution':False}
    result['inputs_observation']={'text_unchanged':inputs==final_inputs}
    (args.output/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
