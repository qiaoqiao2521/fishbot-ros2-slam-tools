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


def pair_clearance(model, data, a, b, cutoff=.20):
    """Conservative box separation bound, native query for overlapping boxes.

    A positive-margin legacy box query can report a negative distance for
    clearly separated rotated boxes. World AABB separation proves clearance
    without shrinking either compiled box or changing the physics options.
    Oriented separating axes keep that bound useful where AABBs touch.
    """
    import mujoco
    import numpy as np
    if (model.geom_type[a] == mujoco.mjtGeom.mjGEOM_BOX and
            model.geom_type[b] == mujoco.mjtGeom.mjGEOM_BOX):
        rotations = [data.geom_xmat[i].reshape(3, 3) for i in (a, b)]
        extents = [np.abs(rotation) @ model.geom_size[i]
                   for rotation, i in zip(rotations, (a, b))]
        delta = data.geom_xpos[a]-data.geom_xpos[b]
        gap = np.maximum(np.abs(delta)-
                         extents[0]-extents[1], 0.)
        lower_bound = float(np.linalg.norm(gap))
        if lower_bound < cutoff:
            axes = np.asarray([*rotations[0].T, *rotations[1].T,
                *[np.cross(x, y) for x in rotations[0].T for y in rotations[1].T]])
            norms = np.linalg.norm(axes, axis=1)
            axes = axes[norms > 1e-12]/norms[norms > 1e-12, None]
            radii = sum(np.abs(axes @ rotation) @ model.geom_size[i]
                        for rotation, i in zip(rotations, (a, b)))
            lower_bound = max(lower_bound, float(np.max(np.abs(axes @ delta)-radii)))
        if lower_bound > 0:
            return min(cutoff, lower_bound)
    return float(mujoco.mj_geomDistance(model, data, a, b, cutoff, None))


class SceneGeometry:
    """Independent query data; never changes the running physics instance."""
    def __init__(self, manifest):
        import mujoco
        self.manifest = manifest
        self.model = model = mujoco.MjModel.from_xml_path(manifest['world_xml'])
        self.data = data = mujoco.MjData(model)
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
        self.pairs = [(a, b) for a in car for b in external
                      if (int(model.geom_contype[a]) & int(model.geom_conaffinity[b]))
                      or (int(model.geom_contype[b]) & int(model.geom_conaffinity[a]))]
        if not self.pairs:
            raise ValueError('No original collision pairs were checked')
        self.free = int(model.joint('base_free_joint').qposadr[0])
        self.base_height = float(data.qpos[self.free+2])
        mujoco.mj_forward(model, data)

    def check_pose(self, pose):
        """Static full-body/footprint preflight, not a path or arrival proof."""
        import mujoco
        import numpy as np
        from cooperation_core import task_delivery_pose
        goal = task_delivery_pose({'delivery_pose': pose})
        model, data, free = self.model, self.data, self.free
        x, y, yaw = (goal[key] for key in ('x', 'y', 'yaw'))
        data.qpos[free:free+7] = [x, y, self.base_height, math.cos(yaw/2), 0., 0., math.sin(yaw/2)]
        mujoco.mj_forward(model, data)
        minimum, witness = .20, None
        for a, b in self.pairs:
            distance = pair_clearance(model, data, a, b)
            if distance < minimum:
                minimum, witness = distance, {'car_geom': model.geom(a).name,
                    'external_geom': model.geom(b).name, 'distance_m': distance}
        rotation = np.array([[math.cos(yaw), -math.sin(yaw)], [math.sin(yaw), math.cos(yaw)]])
        footprint = np.asarray(self.manifest['car_footprint_xy'], dtype=float) @ rotation.T + [x, y]
        points = np.column_stack((footprint, np.full(len(footprint), self.base_height)))
        bounds, bounds_reason = [], None
        for name, axis, sign in (('wall_west', 0, 1), ('wall_east', 0, -1),
                                 ('wall_south', 1, 1), ('wall_north', 1, -1)):
            geom = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, name)
            if geom < 0 or model.geom_type[geom] != mujoco.mjtGeom.mjGEOM_BOX:
                bounds_reason = 'scene_enclosure_geometry_unavailable'
                break
            normal = sign*data.geom_xmat[geom].reshape(3, 3)[:, axis]
            clearance = float(np.min((points-data.geom_xpos[geom]) @ normal)-model.geom_size[geom, axis])
            bounds.append({'wall': name, 'footprint_clearance_m': clearance})
        inside = bounds_reason is None and all(item['footprint_clearance_m'] > 0 for item in bounds)
        reason = (bounds_reason if bounds_reason else 'footprint_outside_scene_bounds' if not inside
                  else 'original_geometry_collision' if minimum <= 0 else None)
        return {'passed': reason is None, 'scope': 'static_delivery_goal_original_geometry_and_scene_bounds',
                'delivery_pose': goal, 'minimum_sampled_clearance_m': minimum,
                'collision_pair_count': len(self.pairs), 'witness': witness,
                'distance_policy': 'disjoint_box_projection_lower_bound_else_native',
                'scene_bounds': bounds, 'reason': reason, 'robot_geometry_shrunk': False,
                'path_validated': False, 'arrival_validated': False}


def check(manifest_path):
    import mujoco
    import numpy as np
    from cooperation_core import within_station_capture
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text())
    query = SceneGeometry(manifest)
    model, data, pairs, free = query.model, query.data, query.pairs, query.free
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
                distance = pair_clearance(model, data, a, b)
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
            'distance_policy':'disjoint_box_projection_lower_bound_else_native',
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
