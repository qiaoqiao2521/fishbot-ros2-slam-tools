"""Named, measured entity views for the existing canonical SO101 planner.

Only independent query data is written. The common Physics remains the owner
of every arm and free cargo. Other entities become full frozen collision geoms.
"""
from __future__ import annotations

import copy
import math
import xml.etree.ElementTree as ET


def _numbers(values):
    return ' '.join(repr(float(value)) for value in values)


class EntityPadChecker:
    """Keep the source arm policy; also check pads against frozen entities.

    Pads are intentionally outside its group-3 self-collision set. The selected
    cargo is absent from the rig, so intended grasp contact stays exempt.
    """
    def __init__(self, native):
        self.native = native
        model = native.model
        self.pairs = []
        for name in ('pad_gripper', 'pad_moving_jaw'):
            pad = model.geom(name).id
            for geom in range(model.ngeom):
                if model.geom_bodyid[geom] != 0:
                    continue
                if (int(model.geom_contype[pad]) & int(model.geom_conaffinity[geom]) or
                        int(model.geom_contype[geom]) & int(model.geom_conaffinity[pad])):
                    self.pairs.append((pad, geom))

    def __getattr__(self, name):
        return getattr(self.native, name)

    def evaluate(self, q, *, require_fixed_gripper=True):
        import mujoco
        result = self.native.evaluate(q, require_fixed_gripper=require_fixed_gripper)
        if not result['valid']:
            return result
        for pad, geom in self.pairs:
            distance = float(mujoco.mj_geomDistance(self.model, self.data, pad, geom,
                                                   self.distance_cap_m, None))
            if not math.isfinite(distance) or distance < self.margin_m:
                return {'valid': False, 'reason': 'nonfinite_geometry_distance' if not math.isfinite(distance)
                        else 'obstacle_collision', 'min_distance_m': distance if math.isfinite(distance) else None,
                        'pair': [self.model.geom(pad).name, self.model.geom(geom).name]}
            if distance < result['min_distance_m']:
                result = {**result, 'min_distance_m': distance,
                          'pair': [self.model.geom(pad).name, self.model.geom(geom).name]}
        return result

    def is_valid(self, q):
        return bool(self.evaluate(q)['valid'])


class ArmEntityView:
    def __init__(self, manifest, model, arm_id, cargo_id, snapshot):
        import mujoco
        import numpy as np
        from cooperation_business_scene import bind_entities

        self.mj, self.np, self.model = mujoco, np, model
        entities = manifest['business_entities']
        arms, cargo = bind_entities(model, entities)
        self.arm, self.cargo = arms[arm_id], cargo[cargo_id]
        self.arm_id, self.cargo_id = arm_id, cargo_id
        self.description = entities['arms'][arm_id]
        self.origin = np.asarray(self.description['station_position_m'], dtype=float)
        yaw = self.description['station_yaw_rad']
        c, s = math.cos(yaw), math.sin(yaw)
        self.rotation = np.array([[c, -s, 0.], [s, c, 0.], [0., 0., 1.]])
        self.inverse_quat = np.array([math.cos(yaw/2), 0., 0., -math.sin(yaw/2)])
        self.update(snapshot)

    def update(self, snapshot):
        np, mj, model = self.np, self.mj, self.model
        q = np.asarray(snapshot['qpos'], dtype=float)
        v = np.asarray(snapshot['qvel'], dtype=float)
        if q.shape != (model.nq,) or v.shape != (model.nv,) or not np.isfinite(np.r_[q, v]).all():
            raise ValueError('Entity query requires a finite full common-world snapshot')
        data = mj.MjData(model)
        data.qpos[:] = q; data.qvel[:] = v
        mj.mj_forward(model, data)
        self.data = data

    def point(self, world_xyz):
        return self.rotation.T @ (self.np.asarray(world_xyz)-self.origin)

    def quaternion(self, world_quat):
        result = self.np.empty(4)
        self.mj.mju_mulQuat(result, self.inverse_quat, world_quat)
        return result

    def canonical_snapshot(self, snapshot):
        """Map the selected six hinges/free joint, without positional slices."""
        self.update(snapshot)
        np, model = self.np, self.model
        qadr = int(model.jnt_qposadr[self.cargo['joint']])
        dadr = int(model.jnt_dofadr[self.cargo['joint']])
        q, v = self.data.qpos, self.data.qvel
        result = {'qpos': np.r_[q[self.arm['qpos']], self.point(q[qadr:qadr+3]),
                                 self.quaternion(q[qadr+3:qadr+7])].tolist(),
                  # Free-joint linear velocity uses world axes; angular uses body axes.
                  'qvel': np.r_[v[self.arm['qvel']], self.rotation.T @ v[dadr:dadr+3],
                                v[dadr+3:dadr+6]].tolist()}
        if 'ctrl' in snapshot:
            ctrl = np.asarray(snapshot['ctrl'], dtype=float)
            if ctrl.shape != (model.nu,) or not np.isfinite(ctrl).all():
                raise ValueError('Entity snapshot control must match the common model')
            result['ctrl'] = ctrl[self.arm['actuators']].tolist()
        source_time = snapshot.get('time_s', snapshot.get('stamp'))
        if source_time is not None:
            result['time_s'] = float(source_time)
        return result

    def query_root(self, source_root, car_pose):
        """Preserve selected source arm; freeze all other physical geometry."""
        np, mj, model = self.np, self.mj, self.model
        root = copy.deepcopy(source_root)
        world, assets = root.find('worldbody'), root.find('asset')
        for child in list(world):
            if child.tag == 'geom':
                world.remove(child)
        data = mj.MjData(model)
        data.qpos[:] = self.data.qpos
        pose = np.asarray(car_pose, dtype=float)
        car = model.joint('base_free_joint').qposadr[0]
        if pose.shape == (3,):
            pose = np.array([*pose[:2], .002, math.cos(pose[2]/2), 0., 0., math.sin(pose[2]/2)])
        if pose.shape != (7,) or not np.isfinite(pose).all() or not np.isclose(np.linalg.norm(pose[3:]), 1., atol=1e-4):
            raise ValueError('Entity car pose must be finite xyz/wxyz or xy/yaw')
        data.qpos[car:car+7] = pose
        mj.mj_forward(model, data)
        excluded = {self.arm['body'], self.cargo['body']}
        for body in range(1, model.nbody):
            if int(model.body_parentid[body]) in excluded:
                excluded.add(body)
        kinds = {int(mj.mjtGeom.mjGEOM_BOX): ('box', 3),
                 int(mj.mjtGeom.mjGEOM_PLANE): ('plane', 3),
                 int(mj.mjtGeom.mjGEOM_ELLIPSOID): ('ellipsoid', 3),
                 int(mj.mjtGeom.mjGEOM_CYLINDER): ('cylinder', 2),
                 int(mj.mjtGeom.mjGEOM_CAPSULE): ('capsule', 2),
                 int(mj.mjtGeom.mjGEOM_SPHERE): ('sphere', 1)}
        self.frozen_geoms = []
        prefix = '' if self.arm_id == 'load' else self.arm_id+'__'
        for geom in range(model.ngeom):
            if int(model.geom_bodyid[geom]) in excluded or not (model.geom_contype[geom] or model.geom_conaffinity[geom]):
                continue
            source_name = model.geom(geom).name or f'geom_{geom}'
            # Keep the source checker's explicit fixed-base/table mount policy.
            name = 'worktable' if source_name == prefix+'worktable' else 'frozen__'+source_name
            quat = np.empty(4)
            mj.mju_mat2Quat(quat, (self.rotation.T @ data.geom_xmat[geom].reshape(3, 3)).ravel())
            attrs = dict(name=name, pos=_numbers(self.point(data.geom_xpos[geom])),
                         quat=_numbers(quat), contype=str(model.geom_contype[geom]),
                         conaffinity=str(model.geom_conaffinity[geom]), group='3',
                         friction=_numbers(model.geom_friction[geom]),
                         solref=_numbers(model.geom_solref[geom]), solimp=_numbers(model.geom_solimp[geom]))
            if int(model.geom_type[geom]) == int(mj.mjtGeom.mjGEOM_MESH):
                mesh = int(model.geom_dataid[geom]); asset_name = f'entity_frozen_mesh_{geom}'
                va, vn = int(model.mesh_vertadr[mesh]), int(model.mesh_vertnum[mesh])
                fa, fn = int(model.mesh_faceadr[mesh]), int(model.mesh_facenum[mesh])
                ET.SubElement(assets, 'mesh', name=asset_name,
                              vertex=_numbers(model.mesh_vert[va:va+vn].ravel()),
                              face=' '.join(str(int(x)) for x in model.mesh_face[fa:fa+fn].ravel()))
                attrs.update(type='mesh', mesh=asset_name)
            else:
                kind, size = kinds[int(model.geom_type[geom])]
                attrs.update(type=kind, size=_numbers(model.geom_size[geom, :size]))
            ET.SubElement(world, 'geom', **attrs)
            self.frozen_geoms.append({'source': source_name, 'query': name})
        # The selected cargo stays the original independent free-body geometry.
        target = world.find("body[@name='grasp_target']")
        qadr = int(model.jnt_qposadr[self.cargo['joint']])
        target.set('pos', _numbers(self.point(self.data.qpos[qadr:qadr+3])))
        target.set('quat', _numbers(self.quaternion(self.data.qpos[qadr+3:qadr+7])))
        return root
