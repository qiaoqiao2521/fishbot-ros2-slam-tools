#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Offline complete-trajectory selection replay. No ROS or control transport."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path

import numpy as np
from numpy.polynomial import polynomial as poly


def reuse(root):
    path = Path(__file__).with_name("drone-stop-candidates.py")
    spec = importlib.util.spec_from_file_location("stop_candidates", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_modules(root)


def complete(row):
    return {"native_success": row["native"]["native_success"],
            "pieces": row["prefix_pieces"] + row["native"]["pieces"]}


class Replay:
    """Thin offline adapter around the frozen CommittedTail prototype.

    Map validity and known-space declarations are fixture assumptions, not
    perception output. Numeric PVA tolerances do not certify physical tracking.
    """
    def __init__(self, context, limits, audit, handoff):
        self.context = context
        self.limits, self.audit, self.handoff = limits, audit, handoff
        self.server = handoff.CommittedTail([1e-7] * 3)
        self.last_now = None
        self.snapshot = None
        self.admitted_map_revision = None

    def protect(self, reason):
        self.server.active = None
        return {"mode": "protect", "reason": reason, "selected_reference_pva": None}

    def validate(self, native, elapsed, now):
        snapshot = self.snapshot
        if not isinstance(snapshot, dict):
            return {"safe": False, "reason": "map_unknown"}
        if snapshot.get("context") != self.context:
            return {"safe": False, "reason": "map_context_mismatch"}
        if not isinstance(snapshot.get("revision"), str) or not snapshot["revision"]:
            return {"safe": False, "reason": "map_revision_unrecorded"}
        if snapshot.get("known_space") != "declared_static_configuration_space_fixture":
            return {"safe": False, "reason": "known_space_unverified"}
        end = now - elapsed + self.handoff.duration(native)
        # A finite half-second terminal observation window is an experiment
        # parameter. It is NOT a proof of an invariant hover region.
        required_until = max(end, now) + .5
        bounds = [snapshot.get("valid_from_sim_s", np.nan), snapshot.get("valid_until_sim_s", np.nan)]
        if not np.all(np.isfinite(bounds)) or not bounds[0] <= now <= required_until <= bounds[1]:
            return {"safe": False, "reason": "map_prediction_horizon_unverified"}
        result = self.handoff.remaining_clear(native, elapsed, now, snapshot.get("observed_sim_s"),
            snapshot["box"], snapshot["voxels"], self.limits)
        return {**result, "required_until_sim_s": required_until}

    def score(self, row):
        native = complete(row)
        # Re-audit mutable input; never trust a cached 'passed' boolean.
        request = {**row["request"], "required_continuity_order": 2,
            "initial_pva": row["full_math_gate"]["pieces"][0]["start_pva"],
            "integral_resolution": 16,
            "corridor": [[[0., 0., 1., -self.limits["ceiling"]]]]}
        box = [[-np.inf] * 3, [np.inf, np.inf, self.limits["ceiling"]]]
        result = self.audit.audit_trajectory(native, request, [], self.limits, box)
        tail = self.audit.audit_trajectory(row["native"], {**request, **row["request"],
            "integral_resolution": 16, "corridor": request["corridor"]}, [], self.limits, box)
        prefix, first = row["prefix_pieces"][-1], row["native"]["pieces"][0]
        left = poly.polyval(1., self.audit.derivative(self.audit.normalized_power(prefix), prefix["duration"], 3))
        right = poly.polyval(0., self.audit.derivative(self.audit.normalized_power(first), first["duration"], 3))
        failures = result["failed_checks"] + ["tail_" + key for key in tail["failed_checks"]]
        if np.linalg.norm(left - right) > 1e-8:
            failures.append("cut_jerk")
        return native, {**result, "passed": not failures, "failed_checks": sorted(set(failures))}

    def step(self, event):
        now = event.get("now_sim_s", np.nan)
        if not np.isfinite(now):
            return self.protect("invalid_clock_or_state")
        # Admission is also a clock event. Preserve the finite high-water mark
        # after invalid input; do not let NaN or a rewind erase the comparison.
        if self.last_now is not None and now < self.last_now:
            return self.protect("clock_rewind")
        self.last_now = now
        if event.get("context") != self.context:
            return self.protect("event_context_mismatch")
        measured = np.asarray(event.get("observed_pva"), dtype=float)
        if measured.shape != (3, 3) or not np.all(np.isfinite(measured)):
            return self.protect("invalid_clock_or_state")
        if "snapshot" in event:
            self.snapshot = copy.deepcopy(event["snapshot"])
        accepted, reasons, scored = None, [], None
        if "candidate" in event:
            row = event["candidate"]
            try:
                if row.get("recorded_task_id") != self.context["task_id"]:
                    reasons = ["candidate_task_mismatch"]
                else:
                    native, scored = self.score(row)
                    previous = self.server.rejections.copy()
                    accepted = self.server.admit(str(row["trajectory_id"]), native, scored,
                        row["start_sim_s"], now, measured, self.validate)
                    reasons = list((self.server.rejections - previous).keys())
                    if accepted:
                        self.admitted_map_revision = self.snapshot.get("revision")
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                reasons = ["malformed_candidate"]
            if reasons and accepted is None:
                accepted = False
                self.server.last_rejected = True
        result = self.server.tick(now, measured, self.validate)
        result["selected_reference_pva"] = result.pop("command")
        return {**result, "candidate_accepted": accepted, "candidate_rejections": reasons,
            "candidate_math_gate": scored,
            "admitted_map_revision": self.admitted_map_revision,
            "checked_map_revision": self.snapshot.get("revision") if isinstance(self.snapshot, dict) else None}


def fixture_scenarios(row, rejected, context, handoff):
    """Declared counterfactual world and ideal reference observations, not flight."""
    native = complete(row)
    start = row["start_sim_s"]
    total = handoff.duration(native)

    def event(offset, **changes):
        now = start + offset
        return {"context": context, "now_sim_s": now,
            "observed_pva": handoff.pva(native, offset).tolist(),
            "snapshot": {"context": context, "revision": "fixture-open",
                "known_space": "declared_static_configuration_space_fixture",
                "observed_sim_s": now, "valid_from_sim_s": start,
                "valid_until_sim_s": start + total + 2.,
                "box": [[-10., -10., 0.], [15., 10., 2.2]], "voxels": []}, **changes}

    def occupied(offset, terminal=False):
        e = event(offset)
        p = handoff.pva(native, total if terminal else offset)[:, 0]
        e["snapshot"].update(revision="fixture-intrusion", voxels=[[(p-.01).tolist(), (p+.01).tolist()]])
        return e

    first = event(0., candidate=row)
    no_forecast = event(0., candidate=row)
    no_forecast["snapshot"]["valid_until_sim_s"] = start
    unknown = event(0., candidate=row)
    unknown["snapshot"].pop("known_space")
    stale = event(.7)
    stale["snapshot"]["observed_sim_s"] = start
    future_map = event(.2)
    future_map["snapshot"]["observed_sim_s"] += .01
    drift = event(.2)
    drift["observed_pva"][0][0] += .01
    rewind = event(-.01)
    invalid = event(.2)
    invalid["now_sim_s"] = float("nan")
    mismatch = event(.2)
    mismatch["snapshot"]["context"] = {**context, "scene_revision": "different"}
    wrong_task = copy.deepcopy(rejected)
    wrong_task["recorded_task_id"] = "other-task"
    return {
        "reject_preserves_phase_then_brakes": [first, event(.2, candidate=rejected), event(.4),
            event(total-.2), event(total+.1)],
        "new_occupied_remaining_curve": [first, occupied(.2)],
        "terminal_region_intrusion": [first, event(total+.1), occupied(total+.2, terminal=True)],
        "paused_clock_then_state_drift": [first, event(.2), event(.2), drift],
        "first_tick_rewind": [first, rewind],
        "invalid_clock_does_not_erase_anchor": [first, invalid, rewind],
        "stale_map": [first, stale],
        "future_dated_observation": [first, future_map],
        "unknown_map": [event(0., candidate=row, snapshot=None)],
        "unknown_free_space": [unknown],
        "current_snapshot_without_future_coverage": [no_forecast],
        "map_context_changed": [first, mismatch],
        "candidate_task_mismatch": [first, event(.2, candidate=wrong_task)],
        "future_start_rejected": [event(0., candidate={**row, "start_sim_s": start+.1})],
        "tracking_mismatch": [first, drift],
        "no_backup": [event(0.)],
    }


def run(data, root):
    audit, handoff = reuse(root)
    context = {"task_id": data["archive_task_id"], "scene_revision": "counterfactual-static-fixture-v1",
               "clock_id": "historical-sim-counterfactual-epoch-1", "frame_id": "scene_enu_m"}
    # Predeclared #6 positive and #7 acceleration rejection; no parameter search.
    row = next(r for r in data["rows"] if r["trajectory_id"] == 6)
    rejected = next(r for r in data["rows"] if r["trajectory_id"] == 7)
    scenarios = fixture_scenarios(row, rejected, context, handoff)
    results = []
    for name, events in scenarios.items():
        replay = Replay(context, data["limits"], audit, handoff)
        rows = []
        for event in events:
            try:
                result = replay.step(event)
            except (ValueError, KeyError, IndexError, TypeError) as error:
                result = {**replay.protect("malformed_fixture_item"), "error": str(error)}
            now = event["now_sim_s"]
            rows.append({"now_sim_s": now if np.isfinite(now) else None,
                "result": result, "input": {**event, "now_sim_s": now if np.isfinite(now) else None}})
        results.append({"scenario": name, "events": rows, "native_selection_stats": replay.server.stats()})
    return {"schema_version": 1, "archive_task_id": data["archive_task_id"], "context": context,
        "kind": "offline_complete_trajectory_counterfactual_replay",
        "state_source": "ideal reference PVA fixture; drift explicitly injected; not measured PX4",
        "map_source": "declared static configuration space fixture; not reconstructed original GridMap",
        "tracking_tolerance_scope": "1e-7 per PVA column; numeric regression only, not calibrated tracking",
        "terminal_scope": "finite .5s map coverage check, not an invariant terminal set",
        "dynamic_safety": "unverified", "execution_admission": "not_performed", "scenarios": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--drone-root", type=Path, default=Path.home()/"dev/ros2/projects/drone")
    args = parser.parse_args()
    report = run(json.loads(args.candidates.read_text()), args.drone_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"scenarios": len(report["scenarios"]), "output": str(args.output),
                      "execution_admission": report["execution_admission"]}))


if __name__ == "__main__":
    main()
