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
from cooperation_query_trace import emit, optional_query_trace, trace_from_context


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
                   arm_id=None, cargo_id=None, snapshot=None, model_grasps=None, prepared_planner=None):
    """Original bounded approach query; input and its 30s limit stay intact."""
    if not math.isfinite(timeout_s) or not 0 < timeout_s <= 30.:
        raise ValueError('Approach query requires a wall budget up to 30 seconds')
    payload = {'manifest': manifest, 'q6': [float(v) for v in q6],
               'car_pose': [float(v) for v in car_pose]}
    if arm_id is not None or cargo_id is not None:
        payload.update(arm_id=arm_id, cargo_id=cargo_id, snapshot=snapshot)
    if model_grasps is not None:
        payload['model_grasps'] = model_grasps
    return _query('approach', payload, check=check, timeout_s=timeout_s, prepared_planner=prepared_planner)


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


def _query(kind, values, *, check, timeout_s, prepared_planner=None):
    """One owned pure child, polled through the existing task owner's check.

    No ROS, live-data writes, retries or new scheduler. Temporary requests, MJB
    transfers and the child are reclaimed on every exit; optional small receipts
    survive timeout and failure for diagnosis.
    """
    import os
    import subprocess
    import sys
    import tempfile
    import uuid
    label = kind.capitalize()
    identity = str(uuid.uuid4()); started = time.monotonic(); process = None
    trace = optional_query_trace(values.get('manifest', {}), identity, started)
    payload = {'query_id': identity, **values}
    if trace is not None:
        payload['_query_trace'] = trace.context()
    emit(trace, 'query_started', kind=kind, wall_budget_s=timeout_s,
         arm_id=values.get('arm_id'), cargo_id=values.get('cargo_id'),
         episode_id=(values.get('snapshot') or {}).get('episode_id'),
         source_sequence=(values.get('snapshot') or {}).get('sequence'))
    encoded = json.dumps(payload, allow_nan=False)
    if len(encoded.encode()) > 1024*1024:
        raise ValueError(label+' query exceeds one MiB')
    with tempfile.TemporaryDirectory(prefix='fishbot-'+kind+'-') as folder:
        request, response = Path(folder)/'request.json', Path(folder)/'response.json'
        child_log = (Path(folder)/'child.log').open('wb') if trace is not None else None
        outcome = 'interrupted_or_failed'
        try:
            check()
            if prepared_planner is not None:
                emit(trace, 'prepared_models_save_started')
                payload['prepared_models'] = prepared_planner.save_query_models(Path(folder))
                emit(trace, 'prepared_models_save_completed',
                     model_files=list(payload['prepared_models']['paths']))
                encoded = json.dumps(payload, allow_nan=False)
                if len(encoded.encode()) > 1024*1024:
                    raise ValueError(label+' query exceeds one MiB')
            request.write_text(encoded)
            if trace is not None:
                trace.save('request.json', payload)
            if time.monotonic()-started >= timeout_s:
                emit(trace, 'query_deadline_reached', wall_budget_s=timeout_s)
                raise TimeoutError(label+' planning exceeded its wall budget')
            process = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()),
                '--query-'+kind, str(request), str(response)], stdin=subprocess.DEVNULL,
                stdout=child_log if child_log is not None else subprocess.DEVNULL,
                stderr=subprocess.STDOUT if child_log is not None else subprocess.DEVNULL,
                start_new_session=True)
            emit(trace, 'child_spawned', child_pid=process.pid)
            while process.poll() is None:
                check()
                if time.monotonic()-started >= timeout_s:
                    emit(trace, 'query_deadline_reached', child_pid=process.pid, wall_budget_s=timeout_s)
                    raise TimeoutError(label+' planning exceeded its wall budget')
                time.sleep(.02)
            emit(trace, 'child_exited', returncode=process.returncode)
            check()
            if time.monotonic()-started >= timeout_s:
                emit(trace, 'query_deadline_reached', child_pid=process.pid, wall_budget_s=timeout_s)
                raise TimeoutError(label+' planning exceeded its wall budget')
            if not response.is_file() or response.stat().st_size > 1024*1024:
                raise RuntimeError(label+' query returned no bounded result')
            result = json.loads(response.read_text())
            if trace is not None:
                trace.save('response.json', result)
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
                    {key: value for key, value in payload.items() if key not in ('query_id', '_query_trace', 'prepared_models')},
                    sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest(),
                'child_pid': process.pid, 'caller_pid': os.getpid(), 'child_exited': True,
                'elapsed_wall_s': time.monotonic()-started, 'wall_budget_s': timeout_s,
                'seed_scope': 'first_plan_of_each_query_process', 'shortcut_applied': False}
            if kind == 'placement':
                execution['wall_remaining_s'] = max(0., timeout_s-execution['elapsed_wall_s'])
                execution['is_controller_consumption_ack'] = False
            execution['prepared_model_transfer'] = prepared_planner is not None
            if trace is not None:
                execution['evidence_directory'] = str(trace.directory)
            plan[field]['execution'] = execution
            outcome = 'accepted'
            emit(trace, 'query_result_accepted', is_physical_success_receipt=False)
            return plan
        except BaseException as error:
            outcome = type(error).__name__
            emit(trace, 'query_failed', error_type=outcome, error=str(error)[:1200])
            raise
        finally:
            if process is not None:
                # A visual query owns a model subprocess in this new session.
                # Cancel the owned group so Torch cannot outlive its query.
                nested = values.get('manifest', {}).get('pretrained_grasp', {}).get('enabled', False)
                def stop_query(force=False):
                    if nested:
                        import signal
                        try:
                            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                    elif force:
                        process.kill()
                    else:
                        process.terminate()
                if process.poll() is None:
                    stop_query()
                    try: process.wait(timeout=2.)
                    except subprocess.TimeoutExpired:
                        stop_query(force=True); process.wait(timeout=2.)
                if nested:
                    # The direct child may have exited before a stubborn model
                    # worker. This owned group cannot be left behind in either case.
                    stop_query(force=True)
            if child_log is not None:
                child_log.close()
                try:
                    log_path = Path(folder)/'child.log'
                    size = log_path.stat().st_size
                    with log_path.open('rb') as incoming:
                        incoming.seek(max(0, size-65536))
                        tail = incoming.read()
                    (trace.directory/'child-log-tail.txt').write_bytes(tail)
                    trace.save('cleanup.json', {'query_id': identity, 'outcome': outcome,
                        'elapsed_wall_s': time.monotonic()-started,
                        'child_exited': process is None or process.poll() is not None,
                        'child_returncode': process.returncode if process is not None else None,
                        'log_original_bytes': size, 'log_retained_bytes': len(tail),
                        'log_is_tail': size > len(tail), 'is_controller_consumption_ack': False})
                    emit(trace, 'query_cleanup_completed', outcome=outcome)
                except OSError as error:
                    import logging
                    logging.warning('Could not retain arm query log tail: %s', error)


class ArmPlanner:
    def __init__(self, manifest: dict | Path, car_pose=None, *, arm_id=None, cargo_id=None, snapshot=None, trace=None, prepared_models=None):
        self.trace = trace
        if not isinstance(manifest, dict):
            manifest = json.loads(Path(manifest).read_text())
        if manifest.get('business_entities') and arm_id is None and cargo_id is None:
            raise ValueError('Multi-entity scene requires explicit arm_id and cargo_id; legacy query would omit other entities')
        self.manifest = manifest
        emit(trace, 'source_modules_import_started')
        self.modules = source_modules(Path(manifest["so101_project"]))
        emit(trace, 'source_modules_import_completed')
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
        world_event = 'world_model_binary_load' if prepared_models is not None else 'world_model_compile'
        emit(trace, world_event+'_started')
        self.common = (mujoco.MjModel.from_binary_path(prepared_models['paths']['common'])
                       if prepared_models is not None else
                       mujoco.MjModel.from_xml_path(manifest["world_xml"]))
        emit(trace, world_event+'_completed')
        self.entity_view = None
        if arm_id is not None or cargo_id is not None:
            from cooperation_arm_entities import ArmEntityView
            if arm_id is None or cargo_id is None or snapshot is None:
                raise ValueError('Named arm planning requires arm_id, cargo_id and a measured snapshot')
            emit(trace, 'named_entity_view_started')
            self.entity_view = ArmEntityView(manifest, self.common, arm_id, cargo_id, snapshot)
            emit(trace, 'named_entity_view_completed')
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
        self._refresh_models(self.car_pose, prepared_models=prepared_models)

    def save_query_models(self, directory):
        """Serialize this owner's exact compiled models for one temporary query.

        This is not a cross-task cache: all files live in the existing owned
        TemporaryDirectory and are deleted after the original query cleanup.
        """
        paths = {}
        for name in ('common', 'contact', 'rig'):
            path = Path(directory)/(name+'.mjb')
            self.mujoco.mj_saveModel(getattr(self, name), str(path))
            paths[name] = str(path)
        return {'paths': paths,
                'frozen_geoms': copy.deepcopy(self.entity_view.frozen_geoms) if self.entity_view is not None else [],
                'scope': 'same_owner_same_query_compiled_model_transfer',
                'full_visual_and_collision_models_retained': True}

    def _refresh_models(self, car_pose, *, prepared_models=None):
        if prepared_models is not None:
            emit(getattr(self, 'trace', None), 'prepared_collision_models_load_started')
            self.contact = self.mujoco.MjModel.from_binary_path(prepared_models['paths']['contact'])
            self.rig = self.mujoco.MjModel.from_binary_path(prepared_models['paths']['rig'])
            if self.entity_view is not None:
                self.entity_view.frozen_geoms = copy.deepcopy(prepared_models['frozen_geoms'])
            emit(getattr(self, 'trace', None), 'prepared_collision_models_load_completed')
        else:
            root = (copy.deepcopy(self._base_root) if self.entity_view is None else
                    self.entity_view.query_root(self._base_root, car_pose))
            world = root.find("worldbody")
            if self.entity_view is None:
                for child in list(world):
                    if child.get("name") in self._frozen_names:
                        world.remove(child)
                for geom in frozen_car_geoms(self.common, car_pose, self.station):
                    world.append(geom)
            emit(getattr(self, 'trace', None), 'contact_model_compile_started')
            self.contact = self.mujoco.MjModel.from_xml_string(ET.tostring(root, encoding="unicode"))
            emit(getattr(self, 'trace', None), 'contact_model_compile_completed')
            world.remove(world.find("body[@name='grasp_target']"))
            emit(getattr(self, 'trace', None), 'rig_model_compile_started')
            self.rig = self.mujoco.MjModel.from_xml_string(ET.tostring(root, encoding="unicode"))
            emit(getattr(self, 'trace', None), 'rig_model_compile_completed')
        emit(getattr(self, 'trace', None), 'collision_checkers_init_started')
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
        emit(getattr(self, 'trace', None), 'collision_checkers_init_completed')

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
        Its margins, Cartesian/joint resolutions and measured dual-pad admission
        stay intact. Model grasps retain the measured gripper rotation using
        the existing mink task; ideal grasps keep the original upright IK.
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
        rotation = execution.xmat[gripper].reshape(3, 3).copy()
        current = execution.xpos[gripper]+rotation @ grasp.PINCH_POINT
        preserve_rotation = self.manifest.get('pretrained_grasp', {}).get('enabled', False)
        q = execution.qpos[:5].copy(); paths = []
        for a, b in zip(np.vstack([current, centers])[:-1], centers):
            points = [q.copy()]
            for fraction in np.linspace(0, 1, max(2, int(np.ceil(np.linalg.norm(b-a)/.003))+1))[1:]:
                xyz = a+(b-a)*fraction
                if preserve_rotation:
                    from cooperation_model_grasp import fit_body_pose
                    target = np.eye(4)
                    target[:3, :3] = rotation
                    target[:3, 3] = xyz-rotation @ grasp.PINCH_POINT
                    goal, position_error, angle_error = fit_body_pose(self.rig, np.r_[q, .5], target)
                    if goal is None:
                        raise RuntimeError('Measured-orientation placement is unreachable: '
                            f'position={position_error:.6f}m rotation={angle_error:.6f}rad')
                else:
                    goal = grasp.solve_pinch_ik(self.rig, xyz, q)
                edge = self.modules['joint_planner'].validate_joint_path([q, goal], valid, .01)
                if not edge['valid']:
                    raise RuntimeError(f'Station carried route rejected: {audit["last_rejection"]}')
                points.append(goal.copy()); q = goal
            paths.append(np.asarray(points))
        release = None
        if preserve_rotation:
            from cooperation_model_grasp import release_sweep
            release = release_sweep(self, q)
            if not release['valid']:
                raise RuntimeError(f'Measured-grasp release sweep rejected: {release}')
        retreat = self._placement_retreat(q, paths[-1], centers)
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
                           'orientation_policy': 'preserve_measured_gripper_rotation' if preserve_rotation else 'original_upright_zero_roll',
                           **({'measured_gripper_rotation_station': rotation.tolist()} if preserve_rotation else {}),
                           **({'release_configuration_sweep': release} if release is not None else {}),
                           'cartesian_resolution_m': .003, 'joint_edge_resolution_rad': .01,
                           **({'release_detachment': retreat['release_detachment']}
                              if 'release_detachment' in retreat else {}),
                           **audit, 'arm_query_clearance': self.query_clearance.copy()},
                **self.entity_contract()}

    def _placement_retreat(self, q, lowering_path, centers):
        """Clear released cargo vertically before the original OMPL home query."""
        np = self.np
        source = self.modules['joint_planner']
        prefix = None
        if self.manifest.get('pretrained_grasp', {}).get('enabled'):
            centers = np.asarray(centers, dtype=float)
            if (len(centers) >= 2 and np.allclose(centers[-2, :2], centers[-1, :2], atol=1e-9)
                    and centers[-2, 2] > centers[-1, 2]):
                # Reuse the exact already-planned upright descent in reverse.
                # The jaw is now open, so validate it again with the open checker.
                prefix = np.asarray(lowering_path, dtype=float)[::-1].copy()
                kind = 'reverse_last_vertical_lowering_path'
            else:
                grasp = self.modules['grasp_episode']
                data = self.mujoco.MjData(self.rig)
                data.qpos[:6] = np.r_[q, .5]
                self.mujoco.mj_forward(self.rig, data)
                body = self.rig.body('gripper').id
                pinch = data.xpos[body] + data.xmat[body].reshape(3, 3) @ grasp.PINCH_POINT
                points = [np.asarray(q, dtype=float).copy()]
                for fraction in np.linspace(0., 1., int(np.ceil(.041/.003))+1)[1:]:
                    points.append(grasp.solve_pinch_ik(self.rig,
                        pinch + np.array([0., 0., .041*fraction]), points[-1]))
                prefix = np.asarray(points)
                kind = 'upright_original_41mm_standoff'
            checked = source.validate_joint_path(prefix, self.open_checker.is_valid, .01)
            if not checked['valid']:
                raise RuntimeError(f'Open-jaw vertical detachment rejected: {checked}')
        retreat = source.plan_joint_path(q if prefix is None else prefix[-1], self.home[:5],
            self.open_checker.bounds, self.open_checker.is_valid, seed=0, timeout_s=10, resolution_rad=.01)
        if prefix is not None and retreat['status'] == 'solved':
            retreat['path'] = np.vstack([prefix, np.asarray(retreat['path'])[1:]]).tolist()
            combined = source.validate_joint_path(retreat['path'], self.open_checker.is_valid, .01)
            if not combined['valid']:
                raise RuntimeError(f'Combined open-jaw retreat rejected: {combined}')
            home_query = {key: copy.deepcopy(retreat[key]) for key in
                ('validation', 'waypoint_count', 'path_length_rad') if key in retreat}
            retreat['validation'] = combined
            retreat['waypoint_count'] = len(retreat['path'])
            retreat['path_length_rad'] = float(np.linalg.norm(
                np.diff(np.asarray(retreat['path']), axis=0), axis=1).sum())
            retreat['release_detachment'] = {'kind': kind, 'jaw_rad': .5,
                'prefix_waypoints': len(prefix), 'joint_edge_resolution_rad': .01,
                'margin_m': self.open_checker.margin_m, 'checked': checked,
                'original_home_query': home_query,
                'boundary': 'Geometric open-jaw path; live cargo support and release gates remain required'}
        return retreat

    def evaluate(self, q6):
        return self.open_checker.evaluate(self._q6(q6), require_fixed_gripper=False)


def _query_main():
    import sys
    if len(sys.argv) != 4 or sys.argv[1] not in ('--query-approach', '--query-placement'):
        raise SystemExit('Use the bounded query adapter from the existing owner')
    request, response = map(Path, sys.argv[2:])
    payload = json.loads(request.read_text())
    result = {'query_id': payload['query_id']}
    trace = trace_from_context(payload.get('_query_trace'))
    emit(trace, 'child_started')
    try:
        began = time.monotonic()
        emit(trace, 'planner_init_started')
        planner = ArmPlanner(payload['manifest'], car_pose=payload['car_pose'],
            arm_id=payload.get('arm_id'), cargo_id=payload.get('cargo_id'), snapshot=payload.get('snapshot'), trace=trace,
            prepared_models=payload.get('prepared_models'))
        emit(trace, 'planner_init_completed')
        timing = {'planner_init_wall_s': time.monotonic()-began}
        if sys.argv[1] == '--query-approach':
            if payload.get('model_grasps') is None and payload['manifest'].get('pretrained_grasp', {}).get('enabled'):
                from cooperation_visual_grasp import model_proposals
                observed = time.monotonic()
                payload['model_grasps'] = model_proposals(payload['manifest'], payload['snapshot'],
                    payload['arm_id'], payload['cargo_id'], model=planner.common, trace=trace)
                timing['rgbd_and_inference_wall_s'] = time.monotonic()-observed
            if payload.get('model_grasps') is not None:
                from cooperation_model_grasp import prepare_model_approach
                planned = time.monotonic()
                result['plan'] = prepare_model_approach(planner, payload['q6'], payload['model_grasps'], trace=trace)
                timing['candidate_planning_wall_s'] = time.monotonic()-planned
                result['plan']['planning']['visual_query_timing'] = timing
            else:
                result['plan'] = planner.prepare_approach(payload['q6'], seed=0)
        else:
            result['plan'] = planner.prepare_placement(payload['snapshot'], payload['centers_local'])
    except Exception as error:
        result['error'] = str(error)[:2000]
        emit(trace, 'child_failed', error_type=type(error).__name__, error=str(error)[:1200])
    emit(trace, 'child_response_writing', has_error='error' in result)
    response.write_text(json.dumps(result, allow_nan=False))
    raise SystemExit(1 if 'error' in result else 0)


if __name__ == '__main__':
    _query_main()
