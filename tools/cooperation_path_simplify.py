"""Bounded OMPL simplification of an existing exact SO101 joint-space plan.

This adapter owns no planner or motion command. The original validity callback,
clearance margin and edge validator remain authoritative. Call only on an
unloaded RRT path, never on carried Cartesian motion or a detachment prefix.
"""
from __future__ import annotations

import copy
from importlib.metadata import version
import logging
import math
import time


def path_length(path):
    return sum(math.dist(a, b) for a, b in zip(path, path[1:]))


def simplify_joint_plan(planned, bounds, is_valid, validate_joint_path, *,
                        resolution_rad=None, budget_s=.25):
    """Return a new plan dict; unsuccessful simplification retains its path.

    ``budget_s`` bounds expensive callbacks in OMPL's native shortcut operation, not copying and final
    validation. Native search rejects new states after its deadline; a running
    geometry callback cannot be preempted. The existing query covers all work.
    No exceptions from this optional optimization stop an otherwise valid plan;
    task-owner interruption exceptions derived directly from BaseException pass.
    """
    started = time.perf_counter()
    result = copy.deepcopy(planned)
    audit = {'applied': False, 'implementation': 'OMPL PathSimplifier.ropeShortcutPath',
             'original_planner': planned.get('planner'),
             'requested_budget_s': budget_s, 'native_time_parameter': False,
             'native_parameters': {'delta': 1., 'equivalence_tolerance': .1},
             'elapsed_wall_s': None, 'native_simplify_wall_s': None,
             'original_length_rad': None, 'simplified_length_rad': None,
             'resolution_rad': None, 'endpoints_unchanged': True,
             'validity_callback_replaced': False, 'collision_margin_changed': False,
             'rng_reseeded': False, 'native_search_guard': 'reject_after_deadline; final original validation unchanged', 'scope': 'existing unloaded joint-space path only'}
    result['path_simplification'] = audit

    def finish(reason):
        audit['reason'] = reason
        audit['elapsed_wall_s'] = time.perf_counter()-started
        return result

    if planned.get('status') != 'solved' or planned.get('exact_solution') is False:
        return finish('original_plan_not_exact_solved')
    try:
        limits = [[float(x) for x in pair] for pair in bounds]
        original = [[float(x) for x in point] for point in planned.get('path') or []]
        dim = len(limits)
        if (dim != 5 or any(len(pair) != 2 or not all(math.isfinite(x) for x in pair)
                           or pair[0] >= pair[1] for pair in limits)
                or len(original) < 2 or any(len(point) != dim or not all(math.isfinite(x) for x in point) for point in original)):
            return finish('unsupported_or_invalid_input')
        resolutions = [float(x) for x in (planned.get('resolution_rad'), resolution_rad) if x is not None]
        if not resolutions or any(not math.isfinite(x) or x <= 0 for x in resolutions):
            return finish('invalid_original_resolution')
        resolution = min(resolutions)  # Never make the original check coarser.
        budget = float(budget_s)
        if not math.isfinite(budget) or not 0 < budget <= 1.0:
            return finish('invalid_bounded_simplification_budget')
        audit.update(original_length_rad=path_length(original),
                     simplified_length_rad=path_length(original), resolution_rad=resolution,
                     effective_budget_s=budget)

        exact_states = {}
        def bounded_valid(point):
            # The source callback is deterministic for this frozen query. Keep
            # exact (unrounded) previously evaluated states for native search's
            # repeated checks. Final validation calls this callback afresh.
            value = all(lo <= x <= hi for x, (lo, hi) in zip(point, limits)) and bool(is_valid(list(point)))
            exact_states[tuple(point)] = value
            return value

        original_validation = validate_joint_path(original, bounded_valid, resolution)
        audit['original_validation'] = original_validation
        if not original_validation.get('valid'):
            return finish('original_path_invalid_in_current_context')
        from ompl import base as ob, geometric as og
        audit['ompl_version'] = version('ompl')
        space = ob.RealVectorStateSpace(dim)
        native_bounds = ob.RealVectorBounds(dim)
        for index, (low, high) in enumerate(limits):
            native_bounds.setLow(index, low); native_bounds.setHigh(index, high)
        space.setBounds(native_bounds)
        space.setLongestValidSegmentFraction(min(.5, resolution/space.getMaximumExtent()))
        info = ob.SpaceInformation(space)
        deadline = [math.inf]
        audit['native_budget_state_rejections'] = 0
        audit['native_callback_count'] = 0
        audit['native_exact_state_cache_hits'] = 0
        audit['native_cache_scope'] = 'exact unrounded states within this frozen optimization only; final validation is uncached'
        def native_valid(state):
            point = [float(state[i]) for i in range(dim)]
            key = tuple(point)
            if key in exact_states:
                audit['native_exact_state_cache_hits'] += 1
                return exact_states[key]
            # Native shortcut routines do not preempt an internal batch.
            # An expensive batch can therefore overrun maxTime. After the
            # deadline, conservatively reject further search states instead of
            # running expensive geometry callbacks. This never admits a state
            # rejected by the original callback. Final validation below always
            # uses the unmodified original callback, without this search guard.
            if time.perf_counter() >= deadline[0]:
                audit['native_budget_state_rejections'] += 1
                return False
            audit['native_callback_count'] += 1
            return bounded_valid(point)
        info.setStateValidityChecker(native_valid)
        info.setup()
        path = og.PathGeometric(info)
        states = []
        for point in original:
            state = space.allocState()
            for index, value in enumerate(point):
                state[index] = value
            states.append(state)
            path.append(state)
        native = og.PathSimplifier(info)
        entered = time.perf_counter()
        deadline[0] = entered+budget
        audit['native_return_value'] = bool(native.ropeShortcutPath(path, 1., .1))
        audit['native_simplify_wall_s'] = time.perf_counter()-entered
        # Native interpolation respects the same longest-valid-segment fraction.
        # It does not change the simplified geometric route.
        path.interpolate()
        candidate = [[float(state[i]) for i in range(dim)] for state in path.getStates()]
        if len(candidate) < 2:
            return finish('native_returned_empty_path')
        candidate[0], candidate[-1] = original[0].copy(), original[-1].copy()
        new_length = path_length(candidate)
        audit['candidate_length_rad'] = new_length
        checked = validate_joint_path(candidate, bounded_valid, resolution)
        audit['candidate_validation'] = checked
        if not checked.get('valid'):
            return finish('simplified_path_post_validation_failed')
        if new_length >= audit['original_length_rad']-1e-9:
            return finish('no_path_length_improvement')
        result.update(path=candidate, waypoint_count=len(candidate), path_length_rad=new_length,
                      validation=checked)
        audit.update(applied=True, simplified_length_rad=new_length,
                     original_waypoint_count=len(original), simplified_waypoint_count=len(candidate))
        return finish('native_simplified_and_original_validator_passed')
    except Exception as error:
        audit['error_type'] = type(error).__name__
        audit['error'] = str(error)[:240]
        logging.warning('Optional OMPL simplification retained original path: %s', error)
        return finish('simplification_unavailable_or_failed')
