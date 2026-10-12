"""Scan/map quality gate for the AMCL recovery benchmark; no truth input."""
from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import distance_transform_edt


def angle_difference(a, b):
    return math.atan2(math.sin(a-b), math.cos(a-b))


def fresh_stationary_odom(sample, steady_now, ros_now):
    """A zero velocity from an old source cannot authorize stationary updates."""
    if not isinstance(sample, dict):
        return False
    try:
        values = [sample[name] for name in ('stamp', 'steady_time', 'linear_speed', 'angular_speed')]
        return (all(map(math.isfinite, [*values, steady_now, ros_now]))
                and 0 <= steady_now-sample['steady_time'] <= .25
                and -.05 <= ros_now-sample['stamp'] <= .25
                and 0 <= sample['linear_speed'] < .005
                and abs(sample['angular_speed']) < .02)
    except (KeyError, TypeError, ValueError):
        return False


def quality_sample_fresh(sample, steady_now, ros_now):
    """Allow asynchronous TF arrival only while actual prior evidence is fresh."""
    if not isinstance(sample,dict) or sample.get('score',{}).get('valid') is not True:
        return False
    try:
        stamp, processed = sample['stamp'],sample['steady_time']
        received = sample.get('scan_received_steady_time',processed)
        return (all(map(math.isfinite,[stamp,received,processed,steady_now,ros_now]))
                and 0 <= steady_now-processed <= .35 and 0 <= steady_now-received <= .35
                and -.05 <= ros_now-stamp <= .35)
    except (KeyError,TypeError,ValueError):
        return False


def recovery_quality_ready(gate, sample, steady_now, ros_now):
    """Sticky loss hysteresis does not authorize a new navigation action."""
    if not isinstance(sample,dict):
        return False
    try:
        return (gate.state == 'healthy' and gate.good_since is not None
                and steady_now-gate.good_since >= gate.good_duration
                and sample.get('good') is True and sample.get('fresh') is True
                and sample.get('stamp',-math.inf) > gate.after_stamp
                and 0 <= steady_now-sample['amcl_received_steady_time'] <= .75
                and -.05 <= ros_now-sample['amcl_stamp'] <= .75
                and quality_sample_fresh(sample,steady_now,ros_now))
    except (KeyError,TypeError,ValueError):
        return False


class MapDistanceField:
    """Use the existing trinary map reader and keep unknown space unknown."""

    def __init__(self, occupied, known, resolution, origin):
        self.occupied = np.asarray(occupied, dtype=bool)
        self.known = np.asarray(known, dtype=bool)
        self.resolution = float(resolution)
        self.origin = list(map(float, origin))
        if (self.occupied.ndim != 2 or self.known.shape != self.occupied.shape
                or not self.occupied.any() or self.resolution <= 0
                or not all(map(math.isfinite, [self.resolution, *self.origin]))
                or len(self.origin) != 3 or abs(self.origin[2]) > 1e-9):
            raise ValueError('Quality monitor requires a finite axis-aligned occupancy map')
        self.distances = distance_transform_edt(~self.occupied)*self.resolution

    @classmethod
    def from_yaml(cls, path):
        from fishbot_home_scene import load_map
        info, _raw, free, occupied, _path, _image = load_map(path)
        return cls(occupied, free | occupied, info['resolution'], info['origin'])

    def score(self, ranges, angle_min, angle_increment, range_min, range_max,
              map_to_laser, tolerance=.12, minimum_returns=40):
        """Finite hit endpoints only; unknown/outside endpoints cannot earn matches.

        This measures consistency, not localization. A small dynamic obstacle may
        account for unmatched hits without replacing the map or clearing cells.
        """
        pose = list(map(float, map_to_laser))
        if len(pose) != 3 or not all(map(math.isfinite, pose)):
            raise ValueError('Nonfinite map-to-laser pose')
        values = np.asarray(ranges, dtype=float)
        valid = np.isfinite(values) & (values > range_min) & (values < range_max-.01)
        indices = np.flatnonzero(valid)[::2]
        count = len(indices)
        if count < minimum_returns:
            return dict(valid=False, reason='insufficient_finite_hits', returns=count)
        angles = angle_min+indices*angle_increment+pose[2]
        xs = pose[0]+values[indices]*np.cos(angles)
        ys = pose[1]+values[indices]*np.sin(angles)
        cols = np.floor((xs-self.origin[0])/self.resolution).astype(int)
        rows = self.occupied.shape[0]-1-np.floor((ys-self.origin[1])/self.resolution).astype(int)
        inside = ((cols >= 0) & (cols < self.occupied.shape[1])
                  & (rows >= 0) & (rows < self.occupied.shape[0]))
        known = np.zeros(count, dtype=bool)
        distance = np.full(count, .5)
        known[inside] = self.known[rows[inside], cols[inside]]
        distance[known] = self.distances[rows[known], cols[known]]
        matched = known & (distance <= tolerance)
        return dict(valid=True, reason='scan_map_endpoints', returns=count,
                    known_fraction=float(np.mean(known)), match_ratio=float(np.mean(matched)),
                    mean_distance_m=float(np.mean(np.minimum(distance, .5))),
                    tolerance_m=tolerance, unknown_or_outside=int(np.sum(~known)))


class QualityGate:
    """Hysteresis around observed scan consistency and AMCL covariance.

    `observe` deliberately accepts no ground-truth field. Source and receipt
    freshness are both required; elapsed wall time cannot promote old evidence.
    """

    def __init__(self, bad_duration=.55, good_duration=.9):
        self.bad_duration, self.good_duration = bad_duration, good_duration
        self.reset()

    def reset(self, after_stamp=-math.inf, after_received_steady_time=-math.inf):
        self.state = 'pending'
        self.bad_since = self.good_since = None
        self.last_stamp = None
        self.last_received = self.last_observed = None
        self.after_stamp = after_stamp
        self.after_received_steady_time = after_received_steady_time

    def observe(self, score, covariance, stamp, received, steady_now, ros_now):
        values = list(map(float,covariance)) if covariance is not None else []
        fresh = (all(map(math.isfinite, [stamp, received, steady_now, ros_now]))
                 and 0 <= steady_now-received <= .35 and -.05 <= ros_now-stamp <= .35
                 and stamp > self.after_stamp and received > self.after_received_steady_time)
        finite_cov = len(values) == 3 and all(math.isfinite(v) and v >= -1e-10 for v in values)
        observable = fresh and score.get('valid') is True and len(values) == 3 and all(map(math.isfinite,values))
        confident = finite_cov and values[0]+values[1] <= .045 and values[2] <= .035
        good = (fresh and confident and score.get('valid') is True
                and score.get('match_ratio', 0) >= .78 and score.get('known_fraction', 0) >= .80)
        bad = (observable and (not finite_cov
               or score.get('match_ratio', 0) < .50 or score.get('known_fraction', 0) < .55
               or (finite_cov and (values[0]+values[1] > .15 or values[2] > .15))))
        # Require new source samples for healthy persistence, including during
        # stationary no-motion updates. Re-reading one sample never recovers.
        advancing = ((self.last_stamp is None or stamp > self.last_stamp)
                     and (self.last_received is None or received > self.last_received))
        if (self.last_observed is not None and (steady_now-self.last_observed > .35
                or self.last_stamp is not None and stamp-self.last_stamp > .35)):
            self.bad_since = self.good_since = None
        if good and advancing:
            self.bad_since = None
            if self.good_since is None:
                self.good_since = steady_now
            if steady_now-self.good_since >= self.good_duration:
                self.state = 'healthy'
        elif good:
            self.good_since = self.bad_since = None
        elif bad and advancing:
            self.good_since = None
            if self.bad_since is None:
                self.bad_since = steady_now
            if steady_now-self.bad_since >= self.bad_duration:
                self.state = 'lost'
        else:
            self.good_since = self.bad_since = None
        if advancing:
            self.last_stamp = stamp
            self.last_received = received
        self.last_observed = steady_now
        current_loss = bool(bad and advancing and self.bad_since is not None
                            and steady_now-self.bad_since >= self.bad_duration)
        return dict(state=self.state, good=good, bad=bad, fresh=fresh, confident=confident,
                    observable=observable,localization_lost_current=current_loss,
                    reason=('fresh_scan_matches_map' if good else
                            'stale_source' if not fresh else
                            'scan_disagrees_with_map' if score.get('valid') else
                            score.get('reason', 'missing_scan_quality')))


def resume_allowed(action, stopped, quality, global_acknowledged):
    """Only this known, terminal action can yield ownership to a replacement."""
    return (action is not None and action.get('accepted') is True
            and isinstance(action.get('uuid'), str) and bool(action['uuid'])
            and action.get('terminal_status') in (5, 6)
            and stopped is True and quality == 'healthy' and global_acknowledged is True)
