#!/usr/bin/env python3
"""Read-only collision-distance preflight for the declared approach sweep.

This samples the original compiled collision geoms, not a smaller robot. The
rigid translation/yaw spacing bound is subtracted from measured clearance.
Nav2 and the original physics contact checks still judge the executed path.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path


def check(manifest_path):
    import mujoco
    import numpy as np
    from cooperation_core import within_station_capture
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text())
    model = mujoco.MjModel.from_xml_path(manifest['world_xml'])
    data = mujoco.MjData(model)
    data.qpos[:6] = manifest['arm_home_qpos6']
    base = model.body('base_footprint').id
    bodies = {base}
    for body in range(base+1, model.nbody):
        if int(model.body_parentid[body]) in bodies:
            bodies.add(body)
    car = [g for g in range(model.ngeom) if int(model.geom_bodyid[g]) in bodies
           and (model.geom_contype[g] or model.geom_conaffinity[g])]
    external = [g for g in range(model.ngeom) if int(model.geom_bodyid[g]) not in bodies
                and (model.geom_contype[g] or model.geom_conaffinity[g])
                and model.geom_type[g] != mujoco.mjtGeom.mjGEOM_PLANE
                and model.geom(g).name != 'target_collision']
    pairs = [(a, b) for a in car for b in external
             if (int(model.geom_contype[a]) & int(model.geom_conaffinity[b]))
             or (int(model.geom_contype[b]) & int(model.geom_conaffinity[a]))]
    if not pairs:
        raise ValueError('No original collision pairs were checked')
    spawn = [*manifest['spawn'], manifest.get('spawn_yaw', 0.)]
    dock = manifest['dock_pose']
    via_staging = [spawn, manifest['staging_pose'], dock]
    paths = [via_staging]
    if within_station_capture(dict(zip(('x','y','yaw'), spawn)), dock):
        # Capture admission can fail even at a geometrically valid initial
        # pose. The production branch then approaches the staging point.
        paths.insert(0, [spawn, dock])
    footprint = np.asarray(manifest['car_footprint_xy'], dtype=float)
    radius = float(np.linalg.norm(footprint, axis=1).max())
    free = int(model.joint('base_free_joint').qposadr[0])
    minimum = .20
    witness = None
    count = 0
    maximum_spacing_bound = 0.
    segments = [(start, end) for poses in paths for start, end in zip(poses, poses[1:])]
    for start, end in segments:
        angle = math.atan2(math.sin(end[2]-start[2]), math.cos(end[2]-start[2]))
        distance = math.dist(start[:2], end[:2])
        steps = max(1, math.ceil(distance/.01), math.ceil(abs(angle)/.01))
        maximum_spacing_bound = max(maximum_spacing_bound, (distance+radius*abs(angle))/(2*steps))
        for i in range(steps+1):
            fraction = i/steps
            x, y = (start[j]+fraction*(end[j]-start[j]) for j in (0,1))
            yaw = start[2]+fraction*angle
            data.qpos[free:free+7] = [x, y, .002, math.cos(yaw/2), 0., 0., math.sin(yaw/2)]
            mujoco.mj_forward(model, data)
            count += 1
            for a, b in pairs:
                distance = float(mujoco.mj_geomDistance(model, data, a, b, .20, None))
                if distance < minimum:
                    minimum = distance
                    witness = {'pose':[x,y,yaw], 'car_geom':model.geom(a).name,
                               'external_geom':model.geom(b).name, 'distance_m':distance}
    certified = minimum-maximum_spacing_bound
    return {'schema_version':1, 'passed':certified > 0,
            'scope':'declared_rigid_approach_sweep_with_original_collision_geoms',
            'executed_nav2_path_is_separately_checked':True,
            'minimum_sampled_clearance_m':minimum,
            'spacing_bound_m':maximum_spacing_bound, 'geometry_margin_m':certified,
            'certified_margin_m':certified,
            'sample_count':count, 'collision_pair_count':len(pairs), 'witness':witness,
            'excluded_expected_contacts':['arena_floor_planes','target_collision cargo'],
            'spawn':spawn, 'waypoint_branches':paths, 'robot_geometry_shrunk':False,
            'manifest_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'scene_sha256':hashlib.sha256(Path(manifest['world_xml']).read_bytes()).hexdigest(),
            'checker_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    result=check(args.manifest)
    with args.output.open('x') as file:
        json.dump(result,file,indent=2,allow_nan=False);file.write('\n')
    args.output.chmod(0o600)
    print(json.dumps({'passed':result['passed'],'margin_m':result['geometry_margin_m'],'report':str(args.output)}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':raise SystemExit(main())
