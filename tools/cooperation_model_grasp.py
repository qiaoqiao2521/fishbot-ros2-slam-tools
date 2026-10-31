"""Apply pretrained grasp poses through existing mink, OMPL and arm segments."""
from __future__ import annotations

import time


def fit_body_pose(model, initial, target):
    """Use mink's native SE3 task; the gripper hinge remains fixed open."""
    import mink
    import numpy as np
    configuration = mink.Configuration(model)
    q = configuration.q.copy()
    q[:6] = initial
    q[5] = .5
    configuration.update(q)
    task = mink.FrameTask('gripper', 'body', position_cost=1., orientation_cost=.1,
                          lm_damping=1e-6)
    task.set_target(mink.SE3.from_matrix(target))
    limits = [mink.ConfigurationLimit(model), mink.VelocityLimit(model, {
        model.joint(i).name: 0. if i == 5 else 2. for i in range(6)})]
    for iteration in range(100):
        actual = configuration.get_transform_frame_to_world('gripper', 'body').as_matrix()
        translation_error = float(np.linalg.norm(actual[:3, 3]-target[:3, 3]))
        rotation_error = float(np.linalg.norm(mink.SO3.from_matrix(
            target[:3, :3].T @ actual[:3, :3]).log()))
        if translation_error <= .001 and rotation_error <= .01:
            return configuration.q[:5].copy(), translation_error, rotation_error
        velocity = mink.solve_ik(configuration, [task], .1, solver='daqp', damping=1e-5,
                                 limits=limits)
        configuration.integrate_inplace(velocity, .1)
    return None, translation_error, rotation_error


def transfer_endpoint(planner):
    """Read the declared delivery cell, never a measured cargo target."""
    view = planner.entity_view
    if view.arm_id == 'load':
        return [.24, .14, .023]
    from cooperation_business import placement_slot
    stations = planner.manifest['business_entities']['unload_stations']
    station_id = next(key for key, value in stations.items() if value['arm_id'] == view.arm_id)
    if stations[station_id].get('placement_centers_m'):
        return stations[station_id]['placement_centers_m'][-1]
    return [*placement_slot(planner.manifest, station_id, view.cargo_id)['center_xy_m'], .023]


def release_sweep(planner, arm_q):
    """Reuse the existing six-joint sweep for the whole release aperture."""
    from configuration_sweep import validate_configuration_path
    np = planner.np
    return validate_configuration_path(np.r_[arm_q, .015], np.r_[arm_q, .5],
        lambda value: planner.open_checker.evaluate(value, require_fixed_gripper=False)['valid'],
        arm_resolution_rad=.005, jaw_resolution_rad=.002)


def prepare_model_approach(planner, q6, proposals):
    """Never read grasp_target(): pose inputs originate in RGB-D inference."""
    np = planner.np
    q = planner._q6(q6)
    source = planner.modules['joint_planner']
    candidates = proposals['candidates']
    attempts = []
    def record_attempts():
        directory = proposals.get('inference', {}).get('source_directory')
        if directory:
            import json
            import logging
            from pathlib import Path
            path = Path(directory)/'plan-attempts.json'
            try:
                pending = path.with_suffix('.json.part')
                pending.write_text(json.dumps(attempts, indent=2)+'\n')
                pending.replace(path)
            except OSError as error:
                logging.warning('Could not record model candidate progress: %s', error)
    began = time.monotonic()
    # The same calibrated virtual frame is used by the descriptor, official
    # diffusion/OBB sampling and discriminator. Invert it only at the IK edge.
    body_from_grasp = np.linalg.inv(np.asarray(proposals.get(
        'T_body_model', np.diag([1., -1., -1., 1.])), dtype=float))
    for candidate in candidates:
        if time.monotonic()-began > 24.:
            break
        grasp = np.asarray(candidate['pose_station'], dtype=float)
        if grasp.shape != (4, 4) or not np.isfinite(grasp).all():
            continue
        body_goal = grasp @ body_from_grasp
        pre_goal = body_goal.copy()
        pre_goal[:3, 3] -= grasp[:3, 2]*.041
        row = {'index': candidate['index'], 'score': candidate['score'],
               'origin': candidate.get('origin'), 'accepted': False, 'phase': 'grasp_ik'}
        attempts.append(row)
        try:
            record_attempts()
            down, xyz_error, angle_error = fit_body_pose(planner.rig, q, body_goal)
            row.update(position_error_m=xyz_error, rotation_error_rad=angle_error)
            if down is None:
                row['reason'] = 'grasp_pose_not_reachable'
                continue
            row['phase'] = 'pregrasp_ik'
            record_attempts()
            approach, _, _ = fit_body_pose(planner.rig, np.r_[down, .5], pre_goal)
            if approach is None:
                row['reason'] = 'pregrasp_pose_not_reachable'
                continue
            if getattr(planner, 'entity_view', None) is not None:
                row['phase'] = 'transfer_endpoint_ik'
                record_attempts()
                endpoint = transfer_endpoint(planner)
                target = body_goal.copy()
                target[:3, 3] = np.asarray(endpoint) - target[:3, :3] @ planner.modules['grasp_episode'].PINCH_POINT
                terminal, endpoint_error, endpoint_angle = fit_body_pose(planner.rig, np.r_[approach, .5], target)
                row['transfer_endpoint'] = {'pinch_station_m': endpoint,
                    'position_error_m': endpoint_error, 'rotation_error_rad': endpoint_angle,
                    'orientation_policy': 'proposed_gripper_rotation',
                    'boundary': 'Kinematic endpoint only; full carried path, collisions and physics still checked'}
                if terminal is None:
                    row['reason'] = 'transfer_endpoint_not_reproduced'
                    continue
                row['phase'] = 'transfer_release_sweep'
                row['transfer_release_sweep'] = release_sweep(planner, terminal)
                if not row['transfer_release_sweep']['valid']:
                    row['reason'] = 'transfer_release_collision'
                    continue
            descent = source.validate_joint_path([approach, down], planner.open_checker.is_valid, .005)
            ascent = source.validate_joint_path([down, approach], planner.closed_checker.is_valid, .005)
            if not descent['valid'] or not ascent['valid']:
                row.update(reason='grasp_leg_collision', descent=descent, ascent=ascent)
                continue
            from configuration_sweep import validate_configuration_path
            closure = validate_configuration_path(np.r_[down, .5], np.r_[down, .015],
                lambda value: planner.open_checker.evaluate(value, require_fixed_gripper=False)['valid'],
                arm_resolution_rad=.005, jaw_resolution_rad=.002)
            if not closure['valid']:
                row.update(reason='gripper_closure_collision', closure=closure)
                continue
            row['phase'] = 'direct_approach'
            record_attempts()
            direct_began = time.monotonic()
            direct = source.validate_joint_path([q[:5], approach], planner.open_checker.is_valid, .005)
            direct_wall = time.monotonic()-direct_began
            if direct['valid']:
                planned = {'status': 'solved', 'path': [q[:5].tolist(), approach.tolist()],
                    'planner': 'validated_direct_joint_edge', 'exact_solution': True,
                    'validation': direct, 'waypoint_count': 2,
                    'path_length_rad': float(np.linalg.norm(approach-q[:5])),
                    'resolution_rad': .005, 'elapsed_seconds': direct_wall}
            else:
                row['phase'] = 'ompl_approach'
                record_attempts()
                planned = source.plan_joint_path(q[:5], approach, planner.open_checker.bounds,
                    planner.open_checker.is_valid, seed=0, timeout_s=5., resolution_rad=.005)
            planned['direct_approach'] = dict(direct, elapsed_wall_s=direct_wall)
            if planned['status'] != 'solved':
                row['reason'] = 'approach_path_not_solved'
                continue
            row.update(accepted=True, reason='planned')
            record_attempts()
            segments = [planner._segment('approach', planned['path'], .5),
                        planner._segment('descend', [approach, down], .5),
                        planner._segment('close', [down, down], .015, duration_s=0., dwell_s=6.),
                        planner._segment('lift', [down, approach], .015),
                        planner._segment('hold', [approach, approach], .015, duration_s=0., dwell_s=1.5)]
            planned['model_grasp'] = {'selected': row, 'attempts': attempts,
                'observation': proposals.get('observation'), 'inference': proposals.get('inference'),
                'source': 'visible_rgbd_pretrained_graspgenx', 'ideal_target_fallback': False}
            return {'segments': segments, 'planning': planned, 'descent': descent, 'ascent': ascent,
                    'car_pose': planner.car_pose, 'query_clearance': planner.query_clearance.copy(),
                    **planner.entity_contract()}
        except (ValueError, RuntimeError) as error:
            row.update(reason='candidate_query_failed', error=str(error)[:240])
        finally:
            row['elapsed_wall_s'] = time.monotonic()-began
            record_attempts()
    record_attempts()
    raise RuntimeError('No executable RGB-D model grasp: '+str(attempts[-6:]))
