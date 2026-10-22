"""Shared delivery time accounting, independent of ROS and physical scoring."""
import math

DELIVERY_ROUTE_WALL_S = 120.


def path_time_budget(paths, *, linear_speed, angular_speed, linear_accel,
                     linear_decel, angular_accel, angular_decel):
    """Estimate sampled paths, never claim planner/control/transport success.

    Linear and angular motion may overlap. Acceleration, reversal and the
    original .7 source-second pre-hold and post-hold stops are allowances,
    not a guaranteed upper bound on execution or a source/wall clock identity.
    """
    rates = (linear_speed, angular_speed, linear_accel, linear_decel,
             angular_accel, angular_decel)
    if not paths:
        raise ValueError('At least one sampled route leg is required')
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in rates):
        raise ValueError('Route speeds and acceleration magnitudes must be finite and positive')
    legs = []
    for path in paths:
        if len(path) < 2:
            raise ValueError('Each route leg requires at least two sampled poses')
        length = yaw_total = bound = 0.
        reversals, previous = 0, None
        for a, b in zip(path, path[1:]):
            if any(type(p[k]) not in (int, float) or not math.isfinite(p[k])
                   for p in (a, b) for k in ('x', 'y', 'yaw')):
                raise ValueError('Route samples require finite x, y and yaw')
            dx, dy = b['x']-a['x'], b['y']-a['y']
            distance = math.hypot(dx, dy)
            angle = abs(math.atan2(math.sin(b['yaw']-a['yaw']), math.cos(b['yaw']-a['yaw'])))
            length += distance
            yaw_total += angle
            bound += max(distance/linear_speed, angle/angular_speed)
            forward = dx*math.cos(a['yaw'])+dy*math.sin(a['yaw'])
            direction = 1 if forward > 1e-6 else -1 if forward < -1e-6 else None
            if direction is not None:
                reversals += int(previous is not None and direction != previous)
                previous = direction
        ramp = max(linear_speed/linear_accel+linear_speed/linear_decel,
                   angular_speed/angular_accel+angular_speed/angular_decel)
        allowance = (1+reversals)*ramp+1.4
        legs.append({'length_m': length, 'absolute_yaw_change_rad': yaw_total,
                     'kinematic_lower_bound_s': bound, 'direction_reversals': reversals,
                     'acceleration_and_stop_allowance_s': allowance,
                     'estimated_with_allowance_s': bound+allowance})
    lower = sum(leg['kinematic_lower_bound_s'] for leg in legs)
    estimate = sum(leg['estimated_with_allowance_s'] for leg in legs)
    return {'legs': legs, 'kinematic_lower_bound_s': lower,
            'estimated_with_allowance_s': estimate,
            'budget_wall_s': DELIVERY_ROUTE_WALL_S,
            'estimated_headroom_s': DELIVERY_ROUTE_WALL_S-estimate,
            'per_leg_stop_dwell_source_s': 1.4,
            'execution_upper_bound_claimed': False,
            'sampled_path_heading_tracking_assumed': True,
            'all_routes_lower_bound_claimed': False,
            'source_wall_rate_assumed_for_estimate': 1.,
            'runtime_budget_clock': 'monotonic wall',
            'budget_boundary': 'after required egress through final navigation stop and hold'}
