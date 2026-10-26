"""Thin queries around the existing SO101 IK, OMPL and carried planning.

All qpos writes are to independent planning data. This module cannot move or
reset the live common world. The ROS controller executes the returned joint
paths through position actuators while the target remains a free body.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import time
import xml.etree.ElementTree as ET

from cooperation_scene import frozen_car_geoms, source_modules


class _PayloadQueryBackend:
    """Keep the source planner; reuse proven separation for box distances."""
    def __init__(self, native):
        self.native = native

    def __getattr__(self, name):
        return getattr(self.native, name)

    def mj_geomDistance(self, model, data, a, b, cutoff, fromto):
        if fromto is not None:
            return self.native.mj_geomDistance(model, data, a, b, cutoff, fromto)
        from cooperation_geometry_check import pair_clearance
        return pair_clearance(model, data, a, b, cutoff)


def query_approach(manifest, q6, car_pose, *, check, timeout_s=30.,
                   arm_id=None, cargo_id=None, snapshot=None):
    """Original bounded approach query; input and its 30s limit stay intact."""
    if not math.isfinite(timeout_s) or not 0 < timeout_s <= 30.:
        raise ValueError('Approach query requires a wall budget up to 30 seconds')
    payload = {'manifest': manifest, 'q6': [float(v) for v in q6],
               'car_pose': [float(v) for v in car_pose]}
    if arm_id is not None or cargo_id is not None:
        payload.update(arm_id=arm_id, cargo_id=cargo_id, snapshot=snapshot)
    return _query('approach', payload, check=check, timeout_s=timeout_s)


def query_placement(manifest, snapshot, centers_local, *, check, timeout_s,
                    arm_id, cargo_id, car_pose=None):
    """Pure named placement under the owner's remaining original task budget."""
    if not math.isfinite(timeout_s) or not 0 < timeout_s <= 360.:
        raise ValueError('Placement query requires remaining original task budget up to 360 seconds')
    if arm_id is None or cargo_id is None:
        raise ValueError('Placement query requires explicit arm_id and cargo_id')
    if car_pose is None:
        car_pose = snapshot['car']['position']+snapshot['car']['quaternion_wxyz']
    payload = {'manifest': manifest, 'snapshot': snapshot,
               'centers_local': centers_local, 'car_pose': [float(v) for v in car_pose],
               'arm_id': arm_id, 'cargo_id': cargo_id}
    return _query('placement', payload, check=check, timeout_s=timeout_s)


def _query(kind, values, *, check, timeout_s):
    """One owned pure child, polled through the existing task owner's check.

    No ROS, live-data writes, retries or new scheduler. Query artifacts and the
    child are reclaimed on success, original cancellation, timeout or failure.
    """
    import os
    import subprocess
    import sys
    import tempfile
    import uuid
    label = kind.capitalize()
    identity = str(uuid.uuid4()); started = time.monotonic(); process = None
    payload = {'query_id': identity, **values}
    encoded = json.dumps(payload, allow_nan=False)
    if len(encoded.encode()) > 1024*1024:
        raise ValueError(label+' query exceeds one MiB')
    with tempfile.TemporaryDirectory(prefix='fishbot-'+kind+'-') as folder:
        request, response = Path(folder)/'request.json', Path(folder)/'response.json'
        request.write_text(encoded)
        try:
            check()
            process = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()),
                '--query-'+kind, str(request), str(response)], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            while process.poll() is None:
                check()
                if time.monotonic()-started >= timeout_s:
                    raise TimeoutError(label+' planning exceeded its wall budget')
                time.sleep(.02)
            check()
            if time.monotonic()-started >= timeout_s:
                raise TimeoutError(label+' planning exceeded its wall budget')
            if not response.is_file() or response.stat().st_size > 1024*1024:
                raise RuntimeError(label+' query returned no bounded result')
            result = json.loads(response.read_text())
            if result.get('query_id') != identity:
                raise RuntimeError(label+' query identity mismatch')
            if process.returncode or result.get('error'):
                raise RuntimeError(label+' query failed: '+str(result.get('error', process.returncode)))
            plan = result['plan']
            if kind == 'approach':
                valid = (isinstance(plan, dict) and plan.get('planning', {}).get('status') == 'solved'
                    and isinstance(plan.get('segments'), list) and len(plan['segments']) == 5)
                field = 'planning'
            else:
                valid = (isinstance(plan, dict) and plan.get('retreat', {}).get('status') == 'solved'
                    and isinstance(plan.get('report'), dict)
                    and isinstance(plan.get('segments'), list)
                    and len(plan['segments']) == len(payload['centers_local'])+3)
                field = 'report'
            if not valid:
                raise RuntimeError('Malformed '+kind+' query result')
            execution = {'mode': 'one_owned_query_process', 'query_id': identity,
                'input_sha256': hashlib.sha256(json.dumps(
                    {key: value for key, value in payload.items() if key != 'query_id'},
                    sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest(),
                'child_pid': process.pid, 'caller_pid': os.getpid(), 'child_exited': True,
                'elapsed_wall_s': time.monotonic()-started, 'wall_budget_s': timeout_s,
                'seed_scope': 'first_plan_of_each_query_process', 'shortcut_applied': False}
            if kind == 'placement':
                execution['wall_remaining_s'] = max(0., timeout_s-execution['elapsed_wall_s'])
                execution['is_controller_consumption_ack'] = False
            plan[field]['execution'] = execution
            return plan
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try: process.wait(timeout=2.)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=2.)


class ArmPlanner:
    def __init__(self, manifest: dict | Path, car_pose=None, *, arm_id=None, cargo_id=None, snapshot=None):
        if not isinstance(manifest, dict):
            manifest = json.loads(Path(manifest).read_text())
        if manifest.get('business_entities') and arm_id is None and cargo_id is None:
            raise ValueError('Multi-entity scene requires explicit arm_id and cargo_id; legacy query would omit other entities')
        self.manifest = manifest
        self.modules = source_modules(Path(manifest["so101_project"]))
        import mujoco
        import numpy as np

        self.mujoco, self.np = mujoco, np
        # Source placement has no injectable distance API. Load a private copy
        # of that same file, leaving its shared import and native module alone.
        spec = importlib.util.spec_from_file_location(
            '_fishbot_payload_placement', self.modules['placement'].__file__)
        self.payload_placement = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.payload_placement)
        self.payload_placement.mujoco = _PayloadQueryBackend(mujoco)
        self.common = mujoco.MjModel.from_xml_path(manifest["world_xml"])
        self.entity_view = None
        if arm_id is not None or cargo_id is not None:
            from cooperation_arm_entities import ArmEntityView
            if arm_id is None or cargo_id is None or snapshot is None:
                raise ValueError('Named arm planning requires arm_id, cargo_id and a measured snapshot')
            self.entity_view = ArmEntityView(manifest, self.common, arm_id, cargo_id, snapshot)
        self.station = np.asarray(manifest["station_offset"], dtype=float)
        self.home = np.asarray(manifest["arm_home_qpos6"], dtype=float)
        if self.entity_view is not None:
            self.station = self.entity_view.origin
            self.home = np.asarray(self.entity_view.description['home_qpos6'], dtype=float)
            if car_pose is None:
                adr = int(self.common.joint('base_free_joint').qposadr[0])
                car_pose = self.entity_view.data.qpos[adr:adr+7].tolist()
        self.car_pose = manifest["dock_pose"] if car_pose is None else car_pose
        self._base_root = ET.parse(manifest["arm_contact_xml"]).getroot()
        self._frozen_names = ({geom.get("name") for geom in
                              frozen_car_geoms(self.common, self.car_pose, self.station)}
                              if self.entity_view is None else set())
        self._refresh_models(self.car_pose)

    def _refresh_models(self, car_pose):
        root = (copy.deepcopy(self._base_root) if self.entity_view is None else
                self.entity_view.query_root(self._base_root, car_pose))
        world = root.find("worldbody")
        if self.entity_view is None:
            for child in list(world):
                if child.get("name") in self._frozen_names:
                    world.remove(child)
            for geom in frozen_car_geoms(self.common, car_pose, self.station):
                world.append(geom)
        self.contact = self.mujoco.MjModel.from_xml_string(ET.tostring(root, encoding="unicode"))
        world.remove(world.find("body[@name='grasp_target']"))
        self.rig = self.mujoco.MjModel.from_xml_string(ET.tostring(root, encoding="unicode"))
        self.open_checker = self.modules["collision_scene"].CollisionChecker(
            self.rig, gripper=.5, margin_m=.001)
        self.closed_checker = self.modules["collision_scene"].CollisionChecker(
            self.rig, gripper=.025, margin_m=.001)
        # Reuse the source checker's local-distance API. Large distmax values
        # make legacy MPR report false near-collisions for separated box/meshes.
        # Twice the unchanged margin covers the full admission boundary.
        for checker in (self.open_checker, self.closed_checker):
            checker.distance_cap_m = 2*checker.margin_m
        if self.entity_view is not None:
            from cooperation_arm_entities import EntityPadChecker
            self.open_checker = EntityPadChecker(self.open_checker)
            self.closed_checker = EntityPadChecker(self.closed_checker)
        self.query_clearance = {"backend": "source_legacy_mpr",
            "margin_m": self.closed_checker.margin_m,
            "distance_cap_m": self.closed_checker.distance_cap_m,
            "beyond_cap": "saturated_not_measured_clearance",
            "payload_query_backend": "disjoint_box_projection_lower_bound_else_native",
            "payload_source_isolated": True,
            "payload_distance_semantics": "conservative_lower_bound_not_exact_distance",
            "payload_margin_m": .0002, "payload_distance_cap_m": .02,
            "plant_flags_changed": False}
        if self.entity_view is not None:
            self.query_clearance['entity_pad_obstacle_pairs'] = len(self.open_checker.pairs)
        self.car_pose = self.np.asarray(car_pose, dtype=float).tolist()

    def entity_contract(self):
        if self.entity_view is None:
            return {}
        view = self.entity_view
        return {'arm_id': view.arm_id, 'cargo_id': view.cargo_id,
                'joint_names': view.arm['joint_names'],
                'station_position_m': view.origin.tolist(),
                'station_yaw_rad': view.description['station_yaw_rad'],
                'frozen_geoms': copy.deepcopy(view.frozen_geoms),
                'source': 'measured_common_world_query_only'}

    def _q6(self, q):
        q = self.np.asarray(q, dtype=float)
        if q.shape != (6,) or not self.np.isfinite(q).all():
            raise ValueError("Arm state must contain six finite joint angles")
        return q

    def _segment(self, stage, points, jaw, *, dwell_s=.6, duration_s=None):
        points = self.np.asarray(points, dtype=float)
        if points.ndim != 2 or points.shape[1] != 5 or not self.np.isfinite(points).all():
            raise ValueError("Joint path must contain finite five-joint waypoints")
        length = float(self.np.linalg.norm(self.np.diff(points, axis=0), axis=1).sum())
        return {"stage": stage, "path": points.tolist(), "gripper": jaw,
                "duration_s": max(2., length * 1.875 / .3) if duration_s is None else duration_s,
                "dwell_s": dwell_s}

    def grasp_target(self):
        target = self.np.array([.24, -.13, .019])
        if self.entity_view is not None:
            view = self.entity_view
            target = view.point(view.data.xpos[view.cargo['body']])
            # The proven source pinch is above the settled box center, not at
            # it. Preserve that offset using the original floor/box geometry.
            floor = self._base_root.find("worldbody/geom[@name='pick_floor']")
            floor_top = float(floor.get('pos').split()[2])+float(floor.get('size').split()[2])
            half_height = float(self.common.geom_size[view.cargo['geom'], 2])
            target[2] += .019-floor_top-half_height
        return target

    def prepare_approach(self, q6, *, car_pose=None, seed=0):
        """Plan from the actual arm state, with the stopped car as an obstacle."""
        if car_pose is not None:
            self._refresh_models(car_pose)
        q = self._q6(q6)
        grasp = self.modules["grasp_episode"]
        planner = self.modules["joint_planner"]
        target = self.grasp_target()
        overhead = target + self.np.array([0., 0., .041])
        approach = grasp.solve_pinch_ik(self.rig, overhead, q[:5])
        down = grasp.solve_pinch_ik(self.rig, target, approach)
        lift = grasp.solve_pinch_ik(self.rig, overhead, down)
        direct = planner.validate_joint_path([q[:5], approach], self.open_checker.is_valid, .015)
        planned = planner.plan_joint_path(q[:5], approach, self.open_checker.bounds,
                                         self.open_checker.is_valid, seed=seed,
                                         timeout_s=10, resolution_rad=.015)
        if planned["status"] != "solved":
            raise RuntimeError(f"Approach planning failed: {planned}")
        descent = planner.validate_joint_path([approach, down], self.open_checker.is_valid, .015)
        ascent = planner.validate_joint_path([down, lift], self.closed_checker.is_valid, .015)
        if not descent["valid"] or not ascent["valid"]:
            raise RuntimeError(f"Grasp legs rejected: descent={descent}, ascent={ascent}")
        self.approach, self.down, self.lift = approach, down, lift
        segments = [self._segment("approach", planned["path"], .5),
                    self._segment("descend", [approach, down], .5),
                    self._segment("close", [down, down], .015, duration_s=0., dwell_s=6.),
                    self._segment("lift", [down, lift], .015),
                    self._segment("hold", [lift, lift], .015, duration_s=0., dwell_s=1.5)]
        return {"segments": segments, "planning": planned, "direct_approach": direct,
                "descent": descent, "ascent": ascent, "car_pose": self.car_pose,
                "query_clearance": self.query_clearance.copy(),
                **self.entity_contract()}

    def prepare_transport(self, snapshot, *, car_pose=None):
        """Clone a refreshed actual grasp and reuse source plan_transport."""
        if self.entity_view is not None:
            raise ValueError('Named cargo placement needs an explicit station route; use prepare_placement')
        np, mj = self.np, self.mujoco
        qpos = np.asarray(snapshot["qpos"], dtype=float)
        qvel = np.asarray(snapshot["qvel"], dtype=float)
        if (qpos.shape != (self.common.nq,) or qvel.shape != (self.common.nv,)
                or not np.isfinite(np.r_[qpos, qvel]).all()):
            raise ValueError("Transport snapshot must match the compiled common-world joint layout")
        # Actual car pose, including its settled height and roll/pitch, always
        # wins over the ideal dock when constructing collision query models.
        pose = qpos[13:20] if car_pose is None else car_pose
        self._refresh_models(pose)
        execution = mj.MjData(self.contact)
        execution.qpos[:] = qpos[:13]
        execution.qpos[6:9] -= self.station
        execution.qvel[:] = qvel[:12]
        if "ctrl" in snapshot:
            ctrl = np.asarray(snapshot["ctrl"], dtype=float)
            if ctrl.shape not in ((6,), (self.common.nu,)) or not np.isfinite(ctrl).all():
                raise ValueError("Snapshot control must contain arm-only or compiled-world finite commands")
            execution.ctrl[:] = ctrl[:6]
        if "time_s" in snapshot:
            execution.time = float(snapshot["time_s"])
        mj.mj_forward(self.contact, execution)
        grasp = self.modules["grasp_episode"]
        forces = grasp.grasp_contacts(self.contact, execution)
        if min(forces.values()) <= .02:
            raise RuntimeError(f"Transport snapshot has no dual-finger contact: {forces}")
        paths, report = self.payload_placement.plan_transport(
            self.contact, self.rig, execution, self.closed_checker,
            solve_ik=grasp.solve_pinch_ik, pinch_point=grasp.PINCH_POINT)
        report["arm_query_clearance"] = self.query_clearance.copy()
        segments = [self._segment("lower" if index == len(paths) - 1 else "transport", path, .015)
                    for index, path in enumerate(paths)]
        released = paths[-1][-1]
        # Reuse source post-release retreat from the delivery pinch to its
        # initial overhead pose. The target is checked by live release/settle.
        retreat = self.modules["joint_planner"].validate_joint_path(
            [released, self.home[:5]], self.open_checker.is_valid, .01)
        if not retreat["valid"]:
            raise RuntimeError(f"Delivery retreat rejected: {retreat}")
        segments.extend([self._segment("release", [released, released], .5, duration_s=0., dwell_s=6.),
                         self._segment("retreat", [released, self.home[:5]], .5),
                         self._segment("settle", [self.home[:5], self.home[:5]], .5,
                                       duration_s=0., dwell_s=1.5)])
        return {"segments": segments, "report": report, "retreat": retreat,
                "car_pose": self.car_pose, "snapshot_tip_forces_n": forces}

    def refresh_placement_context(self, snapshot, *, car_pose=None):
        """Refresh only the parent's measured execution collision-check context."""
        if self.entity_view is None:
            raise ValueError('Station placement requires named entities')
        view = self.entity_view
        local = view.canonical_snapshot(snapshot)
        if 'ctrl' not in local:
            raise ValueError('Measured station grasp requires the current actuator references')
        if car_pose is None:
            adr = int(self.common.joint('base_free_joint').qposadr[0])
            car_pose = view.data.qpos[adr:adr+7]
        self._refresh_models(car_pose)
        return local

    def prepare_placement(self, snapshot, centers_local, *, car_pose=None):
        """Explicit station route using the original carried checker and IK.

        The upstream transport function hardcodes the original tray route.
        Only waypoint selection is generalized here; its margins, upright IK,
        Cartesian/joint resolutions and measured dual-pad admission stay intact.
        """
        np, mj = self.np, self.mujoco
        local = self.refresh_placement_context(snapshot, car_pose=car_pose)
        execution = mj.MjData(self.contact)
        execution.qpos[:] = local['qpos']; execution.qvel[:] = local['qvel']
        if 'ctrl' in local:
            execution.ctrl[:] = local['ctrl']
        if 'time_s' in local:
            execution.time = local['time_s']
        mj.mj_forward(self.contact, execution)
        grasp = self.modules['grasp_episode']
        forces = grasp.grasp_contacts(self.contact, execution)
        if min(forces.values()) <= .02:
            raise RuntimeError(f'Station placement has no measured dual-finger contact: {forces}')
        centers = np.asarray(centers_local, dtype=float)
        if centers.ndim != 2 or centers.shape[1] != 3 or not len(centers) or not np.isfinite(centers).all():
            raise ValueError('Station route must contain finite local xyz waypoints')
        valid, audit = self.payload_placement.carried_configuration_checker(
            self.contact, execution, self.closed_checker)
        gripper = self.contact.body('gripper').id
        current = execution.xpos[gripper]+execution.xmat[gripper].reshape(3, 3) @ grasp.PINCH_POINT
        q = execution.qpos[:5].copy(); paths = []
        for a, b in zip(np.vstack([current, centers])[:-1], centers):
            points = [q.copy()]
            for fraction in np.linspace(0, 1, max(2, int(np.ceil(np.linalg.norm(b-a)/.003))+1))[1:]:
                goal = grasp.solve_pinch_ik(self.rig, a+(b-a)*fraction, q)
                edge = self.modules['joint_planner'].validate_joint_path([q, goal], valid, .01)
                if not edge['valid']:
                    raise RuntimeError(f'Station carried route rejected: {audit["last_rejection"]}')
                points.append(goal.copy()); q = goal
            paths.append(np.asarray(points))
        retreat = self.modules['joint_planner'].plan_joint_path(q, self.home[:5],
            self.open_checker.bounds, self.open_checker.is_valid, seed=0, timeout_s=10, resolution_rad=.01)
        if retreat['status'] != 'solved':
            raise RuntimeError(f'Station retreat rejected: {retreat}')
        segments = [self._segment('lower' if i == len(paths)-1 else 'transport', path, .015)
                    for i, path in enumerate(paths)]
        segments.extend([self._segment('release', [q, q], .5, duration_s=0., dwell_s=6.),
                         self._segment('retreat', retreat['path'], .5),
                         self._segment('settle', [self.home[:5], self.home[:5]], .5,
                                       duration_s=0., dwell_s=1.5)])
        return {'segments': segments, 'snapshot_tip_forces_n': forces, 'retreat': retreat,
                'report': {'kind': 'upright_cartesian_ik', 'centers_local_m': centers.tolist(),
                           'cartesian_resolution_m': .003, 'joint_edge_resolution_rad': .01,
                           **audit, 'arm_query_clearance': self.query_clearance.copy()},
                **self.entity_contract()}

    def evaluate(self, q6):
        return self.open_checker.evaluate(self._q6(q6), require_fixed_gripper=False)


def _query_main():
    import sys
    if len(sys.argv) != 4 or sys.argv[1] not in ('--query-approach', '--query-placement'):
        raise SystemExit('Use the bounded query adapter from the existing owner')
    request, response = map(Path, sys.argv[2:])
    payload = json.loads(request.read_text())
    result = {'query_id': payload['query_id']}
    try:
        planner = ArmPlanner(payload['manifest'], car_pose=payload['car_pose'],
            arm_id=payload.get('arm_id'), cargo_id=payload.get('cargo_id'), snapshot=payload.get('snapshot'))
        result['plan'] = (planner.prepare_approach(payload['q6'], seed=0)
                          if sys.argv[1] == '--query-approach' else
                          planner.prepare_placement(payload['snapshot'], payload['centers_local']))
    except Exception as error:
        result['error'] = str(error)[:2000]
    response.write_text(json.dumps(result, allow_nan=False))
    raise SystemExit(1 if 'error' in result else 0)


if __name__ == '__main__':
    _query_main()
