#!/usr/bin/env python3
"""Native same-query MJB transfer check; no ROS, inference, or physical stepping.

Use --manifest and --request for a saved real snapshot. Without --manifest,
construct the existing named J100 full-geometry fixture in a TemporaryDirectory.
Timings here measure this static verification, not a completed 30s query.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cooperation_arm import ArmPlanner


def check(manifest, request, directory):
    import mujoco
    import numpy as np
    model = mujoco.MjModel.from_xml_path(manifest['world_xml'])
    data = mujoco.MjData(model)
    snapshot = request.get('snapshot') if request else None
    if snapshot is None:
        snapshot = {'qpos': data.qpos.tolist(), 'qvel': data.qvel.tolist(),
                    'ctrl': data.ctrl.tolist(), 'stamp': 0., 'sequence': 0,
                    'episode_id': 'native-transfer-fixture'}
    arm_id = request.get('arm_id', 'load') if request else 'load'
    cargo_id = request.get('cargo_id', 'cargo_1') if request else 'cargo_1'
    car_joint = model.joint('base_free_joint').qposadr[0]
    car_pose = request.get('car_pose') if request else None
    if car_pose is None:
        car_pose = snapshot['qpos'][car_joint:car_joint+7]
    started = time.monotonic()
    original = ArmPlanner(manifest, car_pose, arm_id=arm_id, cargo_id=cargo_id, snapshot=snapshot)
    original_s = time.monotonic()-started
    started = time.monotonic()
    transferred = original.save_query_models(directory)
    save_s = time.monotonic()-started
    started = time.monotonic()
    restored = ArmPlanner(manifest, car_pose, arm_id=arm_id, cargo_id=cargo_id,
                          snapshot=snapshot, prepared_models=transferred)
    load_s = time.monotonic()-started
    fields = ('qpos0', 'body_mass', 'body_inertia', 'body_pos', 'body_quat',
        'geom_type', 'geom_bodyid', 'geom_contype', 'geom_conaffinity', 'geom_group',
        'geom_size', 'geom_pos', 'geom_quat', 'geom_dataid', 'mesh_vert', 'mesh_face',
        'jnt_type', 'jnt_axis', 'jnt_pos', 'jnt_range', 'jnt_qposadr', 'jnt_dofadr',
        'actuator_trnid', 'actuator_gainprm', 'actuator_biasprm', 'actuator_ctrlrange')
    reports = {}
    for name in ('common', 'contact', 'rig'):
        a, b = getattr(original, name), getattr(restored, name)
        dimensions = {field: [int(getattr(a, field)), int(getattr(b, field))]
                      for field in ('nq', 'nv', 'nu', 'ngeom', 'nmesh', 'nbody')}
        if not all(x == y for x, y in dimensions.values()):
            raise AssertionError(name+' model dimensions changed')
        if a.names != b.names:
            raise AssertionError(name+' compiled object names changed')
        if int(a.opt.disableflags) != int(b.opt.disableflags):
            raise AssertionError(name+' engine flags changed')
        different = [field for field in fields if not np.array_equal(getattr(a, field), getattr(b, field))]
        if different:
            raise AssertionError(name+' model data changed: '+str(different))
        ad, bd = mujoco.MjData(a), mujoco.MjData(b)
        if name == 'common':
            ad.qpos[:] = snapshot['qpos']; bd.qpos[:] = snapshot['qpos']
        mujoco.mj_kinematics(a, ad); mujoco.mj_kinematics(b, bd)
        kine = ['xpos', 'xquat', 'geom_xpos', 'geom_xmat', 'xanchor', 'xaxis']
        if not all(np.array_equal(getattr(ad, key), getattr(bd, key)) for key in kine):
            raise AssertionError(name+' kinematics changed')
        reports[name] = {'dimensions': dimensions, 'full_visual_geom_count': int(np.sum(
            (a.geom_contype == 0) & (a.geom_conaffinity == 0))), 'arrays_equal': list(fields),
            'kinematics_equal': kine, 'binary_bytes': Path(transferred['paths'][name]).stat().st_size}
    q = np.asarray(snapshot['qpos'])[original.entity_view.arm['qpos']]
    low, high = original.rig.jnt_range[:5].T
    samples = [q, original.home, np.r_[low*.75+high*.25, .5],
               np.r_[low*.25+high*.75, .5], np.r_[(low+high)/2., .015]]
    verdicts = []
    for sample in samples:
        a = original.open_checker.evaluate(sample, require_fixed_gripper=False)
        b = restored.open_checker.evaluate(sample, require_fixed_gripper=False)
        if a != b:
            raise AssertionError('Original collision verdict/distance/pair differs after transfer')
        verdicts.append({'q6': sample.tolist(), 'original': a, 'restored': b})
    if original.entity_contract() != restored.entity_contract():
        raise AssertionError('Frozen entity binding changed')
    return {'passed': True, 'scope': 'independent query model binary transfer; no ROS/inference/mj_step',
        'is_delivery_acceptance': False, 'is_30s_query_acceptance': False,
        'source_snapshot': 'saved_request' if request else 'default_fixture',
        'original_init_wall_s': original_s, 'serialize_wall_s': save_s,
        'restored_init_wall_s': load_s, 'models': reports,
        'collision_verdicts': verdicts, 'frozen_geoms_equal': True,
        'visual_discard_applied': False, 'original_collision_thresholds_unchanged': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--request', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = {'passed': False, 'is_delivery_acceptance': False}
    try:
        with tempfile.TemporaryDirectory(prefix='fishbot-mjb-transfer-') as folder:
            directory = Path(folder)
            if args.manifest:
                manifest = json.loads(args.manifest.read_text())
            else:
                from cooperation_scene import build_scene
                repo = Path(__file__).resolve().parents[2]
                manifest = build_scene(repo.parent/'so101', repo, directory/'scene',
                    scene_profile=json.loads((repo/'tools/config/cooperation_profiles/jackal_j100-lidar3d-transport.json').read_text()),
                    continuous_delivery=json.loads((repo/'tools/config/factory_delivery/j100-wide-entities.json').read_text()),
                    arena_xml=repo/'tools/config/factory_delivery/j100-wide-arena.xml',
                    spawn=(-.9, -1.68), camera=True)
            request = json.loads(args.request.read_text()) if args.request else None
            report = check(manifest, request, directory)
    except Exception as error:
        report.update(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        args.output.parent.mkdir(exist_ok=True, parents=True)
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
        print(json.dumps(report, allow_nan=False))


if __name__ == '__main__':
    main()
