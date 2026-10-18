"""Thin queries around the existing SO101 IK, OMPL and carried planning.

All qpos writes are to independent planning data. This module cannot move or
reset the live common world. The ROS controller executes the returned joint
paths through position actuators while the target remains a free body.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import time
import xml.etree.ElementTree as ET

from cooperation_scene import frozen_car_geoms, source_modules


def query_approach(manifest, q6, car_pose, *, check, timeout_s=30.):
    """One pure planning process; the caller retains action ownership and hold.

    Each query uses the original planner's first seed, without global RNG resets.
    Poll the existing owner's check while waiting. Cancel/timeout closes the owned
    query before returning; the child never creates ROS nodes or moves live data.
    """
    import os
    import subprocess
    import sys
    import tempfile
    import uuid
    if not math.isfinite(timeout_s) or not 0 < timeout_s <= 30.:
        raise ValueError('Approach query requires a wall budget up to 30 seconds')
    identity = str(uuid.uuid4()); started = time.monotonic(); process = None
    payload = {'query_id': identity, 'manifest': manifest,
               'q6': [float(v) for v in q6], 'car_pose': [float(v) for v in car_pose]}
    encoded = json.dumps(payload, allow_nan=False)
    if len(encoded.encode()) > 1024*1024:
        raise ValueError('Approach query exceeds one MiB')
    with tempfile.TemporaryDirectory(prefix='fishbot-approach-') as folder:
        request, response = Path(folder)/'request.json', Path(folder)/'response.json'
        request.write_text(encoded)
        try:
            check()
            process = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()),
                '--query-approach', str(request), str(response)], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            while process.poll() is None:
                check()
                if time.monotonic()-started >= timeout_s:
                    raise TimeoutError('Approach planning exceeded its wall budget')
                time.sleep(.02)
            check()
            if time.monotonic()-started >= timeout_s:
                raise TimeoutError('Approach planning exceeded its wall budget')
            if not response.is_file() or response.stat().st_size > 1024*1024:
                raise RuntimeError('Approach query returned no bounded result')
            result = json.loads(response.read_text())
            if result.get('query_id') != identity:
                raise RuntimeError('Approach query identity mismatch')
            if process.returncode or result.get('error'):
                raise RuntimeError('Approach query failed: '+str(result.get('error', process.returncode)))
            plan = result['plan']
            if (not isinstance(plan, dict) or plan.get('planning', {}).get('status') != 'solved'
                    or not isinstance(plan.get('segments'), list) or len(plan['segments']) != 5):
                raise RuntimeError('Malformed approach query result')
            plan['planning']['execution'] = {'mode': 'one_owned_query_process',
                'query_id': identity,
                'input_sha256': hashlib.sha256(json.dumps(
                    {key: value for key, value in payload.items() if key != 'query_id'},
                    sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest(),
                'child_pid': process.pid, 'caller_pid': os.getpid(), 'child_exited': True,
                'elapsed_wall_s': time.monotonic()-started, 'wall_budget_s': timeout_s,
                'seed_scope': 'first_plan_of_each_query_process', 'shortcut_applied': False}
            return plan
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try: process.wait(timeout=2.)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=2.)


class ArmPlanner:
    def __init__(self, manifest: dict | Path, car_pose=None):
        if not isinstance(manifest, dict):
            manifest = json.loads(Path(manifest).read_text())
        self.manifest = manifest
        self.modules = source_modules(Path(manifest["so101_project"]))
        import mujoco
        import numpy as np

        self.mujoco, self.np = mujoco, np
        self.common = mujoco.MjModel.from_xml_path(manifest["world_xml"])
        self.station = np.asarray(manifest["station_offset"], dtype=float)
        self.home = np.asarray(manifest["arm_home_qpos6"], dtype=float)
        self.car_pose = manifest["dock_pose"] if car_pose is None else car_pose
        self._base_root = ET.parse(manifest["arm_contact_xml"]).getroot()
        self._frozen_names = {geom.get("name") for geom in
                              frozen_car_geoms(self.common, self.car_pose, self.station)}
        self._refresh_models(self.car_pose)

    def _refresh_models(self, car_pose):
        root = copy.deepcopy(self._base_root)
        world = root.find("worldbody")
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
        self.car_pose = self.np.asarray(car_pose, dtype=float).tolist()

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

    def prepare_approach(self, q6, *, car_pose=None, seed=0):
        """Plan from the actual arm state, with the stopped car as an obstacle."""
        if car_pose is not None:
            self._refresh_models(car_pose)
        q = self._q6(q6)
        grasp = self.modules["grasp_episode"]
        planner = self.modules["joint_planner"]
        approach = grasp.solve_pinch_ik(self.rig, self.np.array([.24, -.13, .06]), q[:5])
        down = grasp.solve_pinch_ik(self.rig, self.np.array([.24, -.13, .019]), approach)
        lift = grasp.solve_pinch_ik(self.rig, self.np.array([.24, -.13, .06]), down)
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
                "descent": descent, "ascent": ascent, "car_pose": self.car_pose}

    def prepare_transport(self, snapshot, *, car_pose=None):
        """Clone a refreshed actual grasp and reuse source plan_transport."""
        np, mj = self.np, self.mujoco
        qpos = np.asarray(snapshot["qpos"], dtype=float)
        qvel = np.asarray(snapshot["qvel"], dtype=float)
        if qpos.shape != (22,) or qvel.shape != (20,) or not np.isfinite(np.r_[qpos, qvel]).all():
            raise ValueError("Transport requires finite common-world qpos22/qvel20")
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
            if ctrl.shape not in ((6,), (8,)) or not np.isfinite(ctrl).all():
                raise ValueError("Snapshot control must contain six or eight finite commands")
            execution.ctrl[:] = ctrl[:6]
        if "time_s" in snapshot:
            execution.time = float(snapshot["time_s"])
        mj.mj_forward(self.contact, execution)
        grasp = self.modules["grasp_episode"]
        forces = grasp.grasp_contacts(self.contact, execution)
        if min(forces.values()) <= .02:
            raise RuntimeError(f"Transport snapshot has no dual-finger contact: {forces}")
        paths, report = self.modules["placement"].plan_transport(
            self.contact, self.rig, execution, self.closed_checker,
            solve_ik=grasp.solve_pinch_ik, pinch_point=grasp.PINCH_POINT)
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

    def evaluate(self, q6):
        return self.open_checker.evaluate(self._q6(q6), require_fixed_gripper=False)


def _query_main():
    import sys
    if len(sys.argv) != 4 or sys.argv[1] != '--query-approach':
        raise SystemExit('Use the bounded query adapter from the existing owner')
    request, response = map(Path, sys.argv[2:])
    payload = json.loads(request.read_text())
    result = {'query_id': payload['query_id']}
    try:
        planner = ArmPlanner(payload['manifest'], car_pose=payload['car_pose'])
        result['plan'] = planner.prepare_approach(payload['q6'], seed=0)
    except Exception as error:
        result['error'] = str(error)[:2000]
    response.write_text(json.dumps(result, allow_nan=False))
    raise SystemExit(1 if 'error' in result else 0)


if __name__ == '__main__':
    _query_main()
