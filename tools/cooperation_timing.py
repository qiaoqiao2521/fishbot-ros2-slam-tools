#!/usr/bin/env python3
"""Read-only historical timing import. No ROS, simulator, or rescoring dependency."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Any

SCHEMA = "fishbot.delivery-timing.v1"


def number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def obj(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def vector(value: Any, size: int) -> list[float] | None:
    if isinstance(value, list) and len(value) == size and all(number(x) is not None for x in value):
        return [float(x) for x in value]
    return None


def read_json(path: Path, warnings: list[str]) -> dict:
    try:
        value = json.loads(path.read_text())
        if isinstance(value, dict):
            return value
    except (OSError, ValueError) as error:
        warnings.append(f"{path.name}: {type(error).__name__}")
        return {}
    warnings.append(f"{path.name}: expected object")
    return {}


def duration(start: Any, end: Any) -> float | None:
    a, b = number(start), number(end)
    return b - a if a is not None and b is not None and b >= a else None


def span(identifier: str, label: str, layer: str, start: Any, end: Any, **extra: Any) -> dict:
    return {"id": identifier, "label": label, "layer": layer,
            "start_wall_s": number(start), "end_wall_s": number(end),
            "duration_s": duration(start, end), "clock": "observer_wall_receipt", **extra}


def route_spans(order: dict, receipt: dict) -> list[dict]:
    """Native action intervals are receipts, not controller-consumption acknowledgements."""
    result = []
    start, end = number(receipt.get("started_wall_time")), number(receipt.get("finished_wall_time"))
    if start is not None:
        result.append(span("route", "配送预算区间", "budget", start, end,
                           clock=receipt.get("clock", "unknown"), duration_s=number(receipt.get("elapsed_wall_s")),
                           boundary=receipt.get("boundary", "unknown"), parent_id=None))
    cursor = start
    for index, raw in enumerate(order.get("native_route") or []):
        item = obj(raw)
        a, b = number(item.get("active_wall_time")), number(item.get("success_wall_time"))
        in_route = start is not None and a is not None and a >= start and (end is None or a <= end)
        if in_route and cursor is not None and a > cursor:
            result.append(span(f"interval-{index}", "动作间隔（未细分）", "interval", cursor, a, parent_id="route"))
        label = "离站 · DriveOnHeading" if item.get("label") == "DriveOnHeading" else (
            "配送目标 · Nav2" if item.get("uuid") == order.get("carrying_nav_uuid") else "进场目标 · Nav2")
        result.append(span(f"native-{index}", label, "native", a, b,
                           parent_id="route" if in_route else None, goal_id=item.get("uuid"),
                           terminal_status=item.get("terminal_status"), goal_pose=item.get("goal_pose"),
                           evidence="result.native_route", consumption_ack=False))
        if in_route and b is not None:
            cursor = max(cursor or b, b)
    if cursor is not None and end is not None and end > cursor:
        result.append(span("route-confirmation", "终态至停稳确认区间", "interval", cursor, end, parent_id="route"))
    return result


def scan_observer(path: Path, case: dict, trajectory: Path) -> dict:
    warnings = case["warnings"]
    counts = {"records": 0, "physics_records": 0, "task_physics_records": 0,
              "malformed_records": 0, "foreign_episode_records": 0, "nonadvancing_records": 0}
    gaps: list[dict] = []
    stages: list[dict] = []
    previous = None
    phase = None
    last_http_wall = None
    last_http_mono = None
    last_bin = None
    written = 0
    clock_break_pending = False
    sequence_start = sequence_end = None
    start, end = case["start_wall_s"], case["end_wall_s"]
    before_stat = None
    try:
        before_stat = path.stat()
        source = path.open()
    except OSError as error:
        warnings.append(f"observer.jsonl: {type(error).__name__}")
        return {**counts, "gaps": [], "stages": [], "trajectory_points": 0, "trajectory_bytes": 0,
                "sequence_start": None, "sequence_end": None}
    with source, trajectory.open("w") as stream:
        for line_no, line in enumerate(source, 1):
            counts["records"] += 1
            try:
                row = json.loads(line)
                if not isinstance(row, dict) or not isinstance(row.get("payload"), dict):
                    raise ValueError("record shape")
            except (ValueError, TypeError):
                counts["malformed_records"] += 1
                continue
            payload = row["payload"]
            wall = number(row.get("received_wall_time"))
            if wall is None:
                continue
            if row.get("topic") == "http_state":
                task = obj(payload.get("task"))
                if task.get("id") != case["task_id"] or payload.get("episode_id") not in (None, case["episode_id"]):
                    continue
                if start is None or end is None or not start <= wall <= end:
                    continue
                if last_http_wall is not None and wall < last_http_wall:
                    counts["nonadvancing_records"] += 1
                    continue
                name = task.get("stage")
                if not isinstance(name, str):
                    continue
                stamp = number(obj(payload.get("physics")).get("stamp"))
                if phase is None or phase["label"] != name:
                    if phase is not None:
                        phase.update(end_wall_s=wall, duration_s=duration(phase["start_wall_s"], wall),
                                     end_boundary_wall_s=[last_http_wall, wall], end_source_s=stamp,
                                     end_monotonic_s=number(row.get("received_monotonic")),
                                     end_ref=f"observer.jsonl:{line_no}")
                        stages.append(phase)
                    phase = span(f"stage-{len(stages)}", name, "observed_stage", wall, None,
                                 parent_id=None, start_boundary_wall_s=[last_http_wall, wall],
                                 start_source_s=stamp, end_source_s=None, end_boundary_wall_s=None,
                                 start_monotonic_s=number(row.get("received_monotonic")), end_monotonic_s=None,
                                 start_ref=f"observer.jsonl:{line_no}", end_ref=None,
                                 evidence="http_state.task.stage; sampled, not exact transition")
                last_http_wall = wall
                last_http_mono = number(row.get("received_monotonic"))
                continue
            if row.get("topic") != "physics":
                continue
            if payload.get("episode_id") != case["episode_id"]:
                counts["foreign_episode_records"] += 1
                continue
            stamp = number(payload.get("stamp"))
            sequence = number(payload.get("sequence"))
            if stamp is None or sequence is None:
                counts["malformed_records"] += 1
                continue
            counts["physics_records"] += 1
            current = {"source_s": stamp, "receive_wall_s": wall, "sequence": sequence,
                       "stage": phase["label"] if phase else "unknown", "hold": payload.get("car_hold")}
            gap_before = False
            if previous is not None:
                delta = sequence - previous["sequence"]
                if delta <= 0 or stamp <= previous["source_s"]:
                    counts["nonadvancing_records"] += 1
                    # Keep the next valid display sample disconnected as well.
                    clock_break_pending = True
                    continue
                # physics_hz describes MuJoCo integration (2500Hz in K), not the
                # observer publication cadence. This importer uses K's 50Hz contract.
                gap_before = delta > 1 or stamp - previous["source_s"] > .03
                if gap_before:
                    gaps.append({"missing": max(0, int(delta) - 1), "before_source_s": previous["source_s"],
                                 "after_source_s": stamp, "before_wall_s": previous["receive_wall_s"], "after_wall_s": wall,
                                 "stage_before": previous["stage"], "stage_after": current["stage"],
                                 "hold_before": previous["hold"], "hold_after": current["hold"],
                                 "line": line_no})
            previous = current
            if start is None or end is None or not start <= wall <= end:
                continue
            counts["task_physics_records"] += 1
            sequence_start = sequence if sequence_start is None else sequence_start
            sequence_end = sequence
            # Source-time bins select one observed sample; no interpolation or gap filling.
            sample_bin = math.floor((stamp + 1e-8) * 10)
            if sample_bin == last_bin and not gap_before and not clock_break_pending:
                continue
            last_bin = sample_bin
            car, cargo = obj(payload.get("car")), obj(payload.get("cargo"))
            sample = {**current, "gap_before": gap_before or clock_break_pending,
                      "car_position_m": vector(car.get("position"), 3), "car_quaternion_wxyz": vector(car.get("quaternion_wxyz"), 4),
                      "cargo_position_m": vector(cargo.get("position"), 3), "arm_q6_rad": vector(payload.get("q6"), 6)}
            stream.write(json.dumps(sample, allow_nan=False, separators=(",", ":")) + "\n")
            written += 1
            clock_break_pending = False
    if phase is not None:
        # Last observation is not proof that the stage remained active until task end.
        phase.update(end_wall_s=last_http_wall, duration_s=duration(phase["start_wall_s"], last_http_wall),
                     end_monotonic_s=last_http_mono, end_boundary_wall_s=[last_http_wall, None], right_censored=True)
        stages.append(phase)
    try:
        after_stat = path.stat()
        if (before_stat.st_size, before_stat.st_mtime_ns) != (after_stat.st_size, after_stat.st_mtime_ns):
            warnings.append("observer.jsonl changed while reading; import is partial")
    except OSError:
        warnings.append("observer.jsonl unavailable after reading; import is partial")
    if counts["task_physics_records"] == 0:
        warnings.append("No valid physics records in task window")
    if not stages:
        warnings.append("No task-stage HTTP observations")
    for name in ("malformed_records", "foreign_episode_records", "nonadvancing_records"):
        if counts[name]:
            warnings.append(f"{name}: {counts[name]}")
    return {**counts, "gaps": gaps, "stages": stages, "trajectory_points": written,
            "trajectory_bytes": trajectory.stat().st_size, "sequence_start": sequence_start, "sequence_end": sequence_end}


def index_report(database: Path, cases: list[dict], run_path: Path) -> None:
    with sqlite3.connect(database) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS eval_runs (
          case_id TEXT PRIMARY KEY, source_run_id TEXT, task_id TEXT, episode_id TEXT,
          source_ref TEXT, import_status TEXT, summary_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS eval_stage_spans (
          case_id TEXT, span_id TEXT, parent_span_id TEXT, layer TEXT, details_json TEXT NOT NULL,
          PRIMARY KEY(case_id,span_id));
        CREATE TABLE IF NOT EXISTS eval_trajectories (
          case_id TEXT PRIMARY KEY, stream_ref TEXT, clock TEXT, frame TEXT, sample_count INTEGER,
          byte_count INTEGER, details_json TEXT NOT NULL);
        """)
        for case in cases:
            key = case["id"]
            db.execute("INSERT OR REPLACE INTO eval_runs VALUES(?,?,?,?,?,?,?)",
                       (key, case["source_run_id"], case["task_id"], case["episode_id"], str(run_path),
                        case["import_status"], json.dumps(case)))
            db.execute("DELETE FROM eval_stage_spans WHERE case_id=?", (key,))
            for item in case["spans"]:
                db.execute("INSERT INTO eval_stage_spans VALUES(?,?,?,?,?)",
                           (key, item["id"], item.get("parent_id"), item["layer"], json.dumps(item)))
            item = case["trajectory"]
            db.execute("INSERT OR REPLACE INTO eval_trajectories VALUES(?,?,?,?,?,?,?)",
                       (key, item["stream_ref"], "source", "world", item["sample_count"], item["byte_count"], json.dumps(item)))


def import_run(run_path: Path, output: Path) -> dict:
    run_path, output = run_path.resolve(), output.resolve()
    if output == run_path or run_path in output.parents or output in run_path.parents:
        raise ValueError("Output must be separate from original evidence")
    output.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    source = read_json(run_path / "result.json", warnings)
    declaration = read_json(run_path / "declaration.json", warnings)
    manifest = read_json(run_path / "manifest-used.json", warnings)
    profile = obj(declaration.get("scene_profile"))
    cases = []
    for index, raw in enumerate(source.get("orders") or [], 1):
        if not isinstance(raw, dict):
            warnings.append(f"order {index}: skipped invalid object")
            continue
        order = raw
        folder = run_path / f"order-{index}"
        case_warnings: list[str] = []
        markers = read_json(folder / "markers.json", case_warnings)
        matching = [obj(event) for event in markers.get("events", [])
                    if obj(event).get("task_id") == order.get("task_id") and obj(event).get("episode_id") == order.get("episode_id")]
        start = next((event.get("wall_time") for event in matching if event.get("kind") == "full_started"), None)
        end = next((event.get("wall_time") for event in matching if event.get("kind") == "full_finished"), None)
        receipt = obj(obj(order.get("delivery_route_budget")).get("receipt"))
        metric = obj(order.get("metrics"))
        case = {"id": f"{source.get('run_id', 'unknown')}:{order.get('id', index)}", "label": order.get("id", f"order-{index}"),
                "source_run_id": source.get("run_id"), "task_id": order.get("task_id"), "episode_id": order.get("episode_id"),
                "vehicle": profile.get("vehicle", "unknown"), "sensor": profile.get("sensors", "unknown"),
                "observation_mode": obj(manifest.get("station_perception")).get("mode", "unknown"),
                "start_wall_s": number(start), "end_wall_s": number(end),
                "task_budget_s": number(declaration.get("task_timeout_wall_s")),
                "task_elapsed_s": number(metric.get("elapsed_wall_s")),
                "original_verdict": {k: order.get(k) for k in ("task_verdict", "original_score_passed", "original_k_passed", "failure_reason")},
                "route": {"start_wall_s": number(receipt.get("started_wall_time")), "end_wall_s": number(receipt.get("finished_wall_time")),
                          "elapsed_s": number(receipt.get("elapsed_wall_s")), "budget_s": number(receipt.get("budget_wall_s")),
                          "remaining_s": number(receipt.get("remaining_wall_s")), "clock": receipt.get("clock", "unknown"),
                          "boundary": receipt.get("boundary", "unknown"), "passed": receipt.get("within_budget")},
                "physical": {k: number(metric.get(k)) for k in ("final_position_error_m", "final_yaw_error_rad", "continuous_final_stop_source_s")},
                "spans": route_spans(order, receipt), "warnings": case_warnings,
                "unavailable": ["Nav2 planner CPU time", "controller compute time / consumption acknowledgement", "exact HTTP stage transition time"],
                "evidence_refs": [f"result.json#orders/{index - 1}", f"order-{index}/markers.json", f"order-{index}/observer/observer.jsonl"],
                "guard": [{k: obj(w).get(k) for k in ("tripped_observed_contiguous_source_duration_s", "plant_assistance_observed", "pure_vision_precision_claimed")}
                          for w in obj(order.get("guard_telemetry")).get("windows", [])]}
        if duration(start, end) is None or not case["task_id"] or not case["episode_id"]:
            case_warnings.append("Missing task identity or valid marker interval")
        stream_ref = f"order-{index}-trajectory-10hz.jsonl"
        observed = scan_observer(folder / "observer/observer.jsonl", case, output / stream_ref)
        case["spans"].extend(observed.pop("stages"))
        case["trajectory"] = {"stream_ref": stream_ref, "sample_count": observed.pop("trajectory_points"),
                              "byte_count": observed.pop("trajectory_bytes"), "policy": "first sample per 100ms source bin; retain break samples; no interpolation",
                              "clock": "source", "frame": "world", "units": "m / rad", "score_input": False,
                              "sequence_start": observed.pop("sequence_start"), "sequence_end": observed.pop("sequence_end")}
        case["sampling"] = observed
        case["sampling"]["expected_source_period_s"] = .02
        case["sampling"]["missing_samples"] = sum(g["missing"] for g in observed["gaps"])
        case["import_status"] = "complete" if not case_warnings else "partial"
        cases.append(case)
    timing = read_json(run_path / "runtime/loop-timing.json", warnings)
    loop_stages = {name: {key: obj(value).get(key) for key in ("count", "total_s", "max_s", "slow_count")}
                   for name, value in obj(timing.get("stages")).items()}
    report = {"schema": SCHEMA, "scope": "historical_simulation_import", "label": "完整 K · J100 B→A",
              "source_run_id": source.get("run_id"), "original_run_passed": source.get("passed"),
              "new_execution": False, "rescored": False, "cases": cases, "warnings": warnings,
              "loop_diagnostics": {"scope": "whole_world_session; not attributed to a Nav2 goal", "stages": loop_stages},
              "limits": ["Stage boundaries are sampled HTTP intervals, not exact event timestamps.",
                         "Wall receipt intervals and source time stay separate; route elapsed uses the original monotonic receipt.",
                         "Native terminal status / forwarding are not controller-consumption acknowledgements.",
                         "Historical simulation results do not establish real hardware or sim-to-real success."]}
    index_report(output / "timing.sqlite3", cases, run_path)
    (output / "delivery-timing.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return report


def public_report(report: dict) -> dict:
    """Explicit publication allowlist: no raw logs, manifests, host paths, or error text."""
    def identifier(value: Any) -> str:
        return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:\-]{1,200}", value) else "unknown"

    result = {key: report[key] for key in ("schema", "scope", "label", "new_execution", "rescored", "limits")}
    result.update(source_run_id=identifier(report.get("source_run_id")),
                  original_run_passed=report.get("original_run_passed") if isinstance(report.get("original_run_passed"), bool) else None,
                  warnings=report["warnings"], cases=[])
    for case in report["cases"]:
        exported = {key: case[key] for key in ("start_wall_s", "end_wall_s", "task_budget_s", "task_elapsed_s", "route", "physical",
                    "sampling", "guard", "unavailable", "warnings", "import_status", "evidence_refs", "trajectory")}
        for key in ("id", "label", "source_run_id", "task_id", "episode_id", "vehicle", "sensor", "observation_mode"):
            exported[key] = identifier(case.get(key))
        exported["route"] = {k: identifier(v) if k in ("clock", "boundary") else v for k, v in case["route"].items()}
        exported["sampling"] = {**case["sampling"], "gaps": [
            {k: identifier(v) if k in ("stage_before", "stage_after") else v for k, v in gap.items()} for gap in case["sampling"]["gaps"]]}
        exported["guard"] = [{"tripped_observed_contiguous_source_duration_s": number(g.get("tripped_observed_contiguous_source_duration_s")),
                              **{k: g.get(k) if isinstance(g.get(k), bool) else None for k in ("plant_assistance_observed", "pure_vision_precision_claimed")}} for g in case["guard"]]
        verdict = case["original_verdict"]
        exported["original_verdict"] = {"task_verdict": identifier(verdict.get("task_verdict")),
                                       **{k: v if isinstance(v, bool) else None for k, v in verdict.items() if k in ("original_score_passed", "original_k_passed")}}
        exported["spans"] = []
        for item in case["spans"]:
            clean = {k: v for k, v in item.items() if k != "goal_pose"}
            if item["layer"] == "observed_stage":
                clean["label"] = identifier(item["label"])
            if "goal_id" in clean:
                clean["goal_id"] = identifier(clean["goal_id"])
            exported["spans"].append(clean)
        result["cases"].append(exported)
    result["loop_diagnostics"] = {"scope": report["loop_diagnostics"]["scope"],
                                  "stages": {identifier(k): {name: number(n) for name, n in v.items()} for k, v in report["loop_diagnostics"]["stages"].items()}}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="Derived private output; never the original run")
    parser.add_argument("--public-output", type=Path, help="Optional curated JSON export; excludes private source paths and raw error text")
    args = parser.parse_args()
    report = import_run(args.run, args.output)
    if args.public_output:
        target = args.public_output.resolve()
        if target == args.run.resolve() or args.run.resolve() in target.parents:
            raise ValueError("Public export cannot overwrite original evidence")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(public_report(report), ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"schema": report["schema"], "cases": len(report["cases"]),
                      "warnings": report["warnings"], "imports": [c["import_status"] for c in report["cases"]]}))


if __name__ == "__main__":
    main()
