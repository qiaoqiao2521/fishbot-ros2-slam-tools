#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Declared offline event-link fixtures; never a live admission or ACK service."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path

import numpy as np


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).parent
legacy = load("event_fixture_legacy", HERE / "drone-handoff-evidence.py")
committed = load("event_fixture_replay", HERE / "drone-committed-replay.py")
APP_STAGES = ("candidate_ready", "candidate_audited", "sender_rpc_started", "sender_rpc_returned")


def natural(value):
    return isinstance(value, int) and legacy.finite(value) and value >= 0


def payload(pva, origin, frames):
    return {"frame": "MAV_FRAME_LOCAL_NED", "type_mask": 2048, "yaw_rad": 0.,
        "position": frames.enu_to_ned((np.asarray(pva)[:, 0] - origin).tolist()),
        "velocity": frames.enu_to_ned(np.asarray(pva)[:, 1].tolist()),
        "acceleration": frames.enu_to_ned(np.asarray(pva)[:, 2].tolist())}


def wire_values(value):
    """Compare the declared float32 wire payload, not physical tolerances."""
    if not isinstance(value, dict) or value.get("frame") != "MAV_FRAME_LOCAL_NED" or not natural(value.get("type_mask")):
        return None
    numbers = [value.get("yaw_rad")]
    for name in ("position", "velocity", "acceleration"):
        vector = value.get(name)
        if not isinstance(vector, list) or len(vector) != 3:
            return None
        numbers.extend(vector)
    if not all(legacy.finite(v) for v in numbers):
        return None
    with np.errstate(over="ignore", invalid="ignore"):
        rounded = np.asarray(numbers, dtype=np.float32)
    if not np.all(np.isfinite(rounded)):
        return None
    return value["frame"], value["type_mask"], tuple(float(x) for x in rounded)


def assess(case, audit, handoff, frames):
    """One isolated candidate/sample fixture; native events carry no UUID."""
    issues = []
    context = case["context"]
    if context.get("frame_id") != "scene_enu_m":
        issues.append("fixture_frame_unqualified")
    if not natural(case.get("sim_epoch")):
        issues.append("fixture_epoch_unqualified")
    replay = committed.Replay(context, case["limits"], audit, handoff)
    selected = [replay.step(copy.deepcopy(e)) for e in case["selector_events"]]
    result = {"name": case["name"], "selector": selected,
        "fixture_chain_consistent": False, "issues": issues,
        "actual_execution_admission": "not_performed"}
    if len(selected) != 2 or not selected[0].get("candidate_accepted") or selected[1].get("selected_reference_pva") is None:
        issues.append("original_selector_rejected")
    events = case["events"]
    stages = {}
    for name in APP_STAGES + ("controller_step_observed",):
        matches = [e for e in events if e.get("event") == name]
        if len(matches) != 1:
            issues.append("event_missing_or_ambiguous:" + name)
        else:
            stages[name] = matches[0]
    if issues and len(stages) != 5:
        return result
    ready, checked, sent, returned = (stages[n] for n in APP_STAGES)
    controller = stages["controller_step_observed"]
    key = (ready.get("candidate_id"), ready.get("candidate_revision"))
    if not isinstance(key[0], str) or not key[0] or not natural(key[1]):
        issues.append("candidate_identity_unqualified")
    for event in (checked, sent, returned):
        if (event.get("candidate_id"), event.get("candidate_revision")) != key:
            issues.append("candidate_version_mismatch")
    candidate = case["selector_events"][0]["candidate"]
    if key != (candidate.get("candidate_id"), candidate.get("candidate_revision")):
        issues.append("candidate_body_identity_mismatch")
    active = replay.server.active
    if active is not None and (active[0] != candidate.get("candidate_id") or active[1] != candidate["native"]
            or active[2] != candidate["start_sim_s"]):
        issues.append("active_candidate_body_mismatch")
    replacement = case["selector_events"][1].get("candidate")
    if selected[1].get("candidate_accepted") and isinstance(replacement, dict) and key != (
            replacement.get("candidate_id"), replacement.get("candidate_revision")):
        issues.append("active_candidate_version_mismatch")
    for event in stages.values():
        if event.get("context") != context:
            issues.append("event_context_mismatch")
    if not all(natural(e.get("sample_seq")) for e in (sent, returned)) or returned.get("sample_seq") != sent.get("sample_seq"):
        issues.append("sample_sequence_mismatch")
    if not legacy.finite(sent.get("sample_sim_s")) or sent.get("sample_sim_s") != case["selector_events"][1]["now_sim_s"]:
        issues.append("sample_phase_mismatch")
    if not legacy.finite(checked.get("audit_sim_s")) or checked.get("audit_sim_s") != case["selector_events"][0]["now_sim_s"]:
        issues.append("audit_phase_mismatch")
    if returned.get("result") != "success":
        issues.append("sender_return_not_success")
    if selected[0].get("checked_map_revision") is not None and checked.get("map_revision") != selected[0]["checked_map_revision"]:
        issues.append("audit_map_revision_mismatch")
    if selected[1].get("checked_map_revision") is not None and sent.get("checked_map_revision") != selected[1]["checked_map_revision"]:
        issues.append("send_map_revision_mismatch")
    if controller.get("branch") != "normal" or controller.get("update_success") is not True:
        issues.append("controller_not_normal_success")
    if not natural(controller.get("used_input_timestamp_us")):
        issues.append("used_input_timestamp_unqualified")
    inputs = [e for e in events if e.get("event") == "px4_input_observed"
        and natural(e.get("input_timestamp_us")) and e["input_timestamp_us"] == controller.get("used_input_timestamp_us")]
    if len(inputs) != 1:
        issues.append("native_input_missing_or_ambiguous")
        return result
    ingress = inputs[0]
    if ingress.get("context") != context:
        issues.append("event_context_mismatch")
    if any(k in e for e in (ingress, controller) for k in ("candidate_id", "candidate_revision", "sample_seq")):
        issues.append("native_identity_fabricated")
    reference = selected[1].get("selected_reference_pva")
    expected = wire_values(payload(reference, case["origin_enu"], frames)) if reference is not None else None
    result["payload_binding"] = "not_evaluated_selector_reference_unavailable"
    if reference is not None:
        result["payload_binding"] = "matched_float32_fixture" if expected is not None and all(
            wire_values(e.get("payload_ned")) == expected for e in (sent, ingress, controller)) else "mismatch"
    if result["payload_binding"] == "mismatch":
        issues.append("payload_or_frame_mismatch")
    if not isinstance(ingress.get("clock"), dict) or ingress["clock"].get("stamp_s") != ingress["input_timestamp_us"] / 1e6:
        issues.append("input_timestamp_mismatch")

    def interval(event):
        clock = event.get("clock", {})
        if (not isinstance(clock, dict) or not natural(clock.get("epoch"))
                or not isinstance(clock.get("domain"), str) or not clock["domain"] or not legacy.finite(clock.get("stamp_s"))):
            issues.append("clock_unqualified")
            return None
        if clock["domain"] == context["clock_id"]:
            if clock["epoch"] != case["sim_epoch"]:
                issues.append("clock_epoch_mismatch")
                return None
            return [clock["stamp_s"], clock["stamp_s"]]
        link_id = event.get("clock_link_id")
        if not isinstance(link_id, str) or not link_id:
            issues.append("clock_link_missing_or_ambiguous")
            return None
        links = [link for link in case.get("clock_links", []) if link.get("id") == link_id]
        if len(links) != 1:
            issues.append("clock_link_missing_or_ambiguous")
            return None
        link = links[0]; bounds = link.get("sim_interval_s")
        if (link.get("scope") != "declared_fixture_correspondence" or link.get("source_clock") != clock
                or link.get("target_domain") != context["clock_id"] or not natural(link.get("target_epoch"))
                or link.get("target_epoch") != case["sim_epoch"]
                or not isinstance(bounds, list) or len(bounds) != 2 or not all(legacy.finite(v) for v in bounds)
                or bounds[0] > bounds[1]):
            issues.append("clock_link_unqualified")
            return None
        return bounds

    linked = [ready, checked, sent, returned, ingress, controller]
    times = {id(event): interval(event) for event in linked}
    for event, stamp in ((checked, checked.get("audit_sim_s")), (sent, sent.get("sample_sim_s"))):
        bounds = times[id(event)]
        if bounds is not None and (not legacy.finite(stamp) or stamp > bounds[0]):
            issues.append("phase_not_available_at_event")
    # Return and ingress have no required order relative to each other.
    for left, right in ((ready, checked), (checked, sent), (sent, returned), (sent, ingress), (ingress, controller)):
        a, b = times[id(left)], times[id(right)]
        if a is not None and b is not None and a[1] > b[0]:
            issues.append("clock_order_reversed" if a[0] > b[1] else "clock_order_ambiguous")
        mono = [left.get("host_monotonic_ns"), right.get("host_monotonic_ns")]
        if not all(natural(v) for v in mono) or mono[0] > mono[1]:
            issues.append("host_order_unqualified")
    for event in (ingress, controller):
        bounds = times[id(event)]
        start = candidate["start_sim_s"]; end = start + handoff.duration(candidate["native"])
        if bounds is not None and not start <= bounds[0] <= bounds[1] < end:
            issues.append("native_observation_outside_candidate_domain")
    native_clocks = [e["clock"] if isinstance(e.get("clock"), dict) else {} for e in (ingress, controller)]
    role = (case.get("native_clock_domain"), case.get("native_clock_epoch"))
    if (not isinstance(role[0], str) or not role[0] or role[0] == context["clock_id"] or not natural(role[1])
            or any((c.get("domain"), c.get("epoch")) != role for c in native_clocks)):
        issues.append("native_clock_role_mismatch")
    if (native_clocks[0].get("domain"), native_clocks[0].get("epoch")) != (native_clocks[1].get("domain"), native_clocks[1].get("epoch")):
        issues.append("native_clock_context_mismatch")
    if all(legacy.finite(c.get("stamp_s")) for c in native_clocks) and native_clocks[0]["stamp_s"] > native_clocks[1]["stamp_s"]:
        issues.append("native_clock_rewind")
    result["issues"] = sorted(set(issues))
    result["fixture_chain_consistent"] = not issues
    return result


def build_cases(candidate, task_id, start, box, limits, handoff, frames):
    """Finite declared cases, not fabricated historical observations."""
    context = {"task_id": task_id, "goal_id": "declared-fixture-goal", "scene_revision": "event-static-fixture",
        "clock_id": "fixture-sim", "frame_id": "scene_enu_m"}
    native = candidate["native"]; end = start + handoff.duration(native)
    row = {"kind": "axis_stop_geometry_candidate", "recorded_task_id": task_id,
        "trajectory_id": "fixture-brake", "candidate_id": "fixture-brake", "candidate_revision": 1, "request": candidate["request"],
        "native": native, "hard_box": box, "start_sim_s": start}
    def selector(now, include=False):
        return {"context": copy.deepcopy(context), "now_sim_s": now, "observed_pva": handoff.pva(native, now-start).tolist(),
            "snapshot": {"context": copy.deepcopy(context), "revision": "map-1",
                "known_space": "declared_static_configuration_space_fixture", "box": box, "voxels": [],
                "observed_sim_s": now, "valid_from_sim_s": start, "valid_until_sim_s": end+2.},
            **({"candidate": row} if include else {})}
    def app(name, now):
        return {"event": name, "context": copy.deepcopy(context), "candidate_id": "fixture-brake", "candidate_revision": 1,
            "clock": {"domain": "fixture-sim", "epoch": 0, "stamp_s": now},
            "host_monotonic_ns": 10**12 + round((now-start)*1e9)}
    events = [app("candidate_ready", start), app("candidate_audited", start),
        app("sender_rpc_started", start+.2), app("sender_rpc_returned", start+.21)]
    events[1].update(map_revision="map-1", audit_sim_s=start)
    actual = payload(handoff.pva(native, .2), [0., 0., 0.], frames)
    events[2].update(sample_seq=17, sample_sim_s=start+.2, checked_map_revision="map-1", payload_ned=copy.deepcopy(actual))
    events[3].update(sample_seq=17, result="success")
    links = []
    for name, boot_us, offset in (("px4_input_observed", 12020000, .22), ("controller_step_observed", 12030000, .23)):
        clock = {"domain": "px4-boot-fixture", "epoch": 3, "stamp_s": boot_us / 1e6}
        event = {"event": name, "context": copy.deepcopy(context), "clock": clock,
            "host_monotonic_ns": 10**12 + round(offset*1e9), "clock_link_id": name,
            "payload_ned": copy.deepcopy(actual)}
        event.update(input_timestamp_us=boot_us) if name == "px4_input_observed" else event.update(
            used_input_timestamp_us=12020000, branch="normal", update_success=True)
        events.append(event)
        links.append({"id": name, "scope": "declared_fixture_correspondence", "source_clock": copy.deepcopy(clock),
            "target_domain": "fixture-sim", "target_epoch": 0, "sim_interval_s": [start+offset, start+offset+.001]})
    base = {"context": context, "sim_epoch": 0, "native_clock_domain": "px4-boot-fixture", "native_clock_epoch": 3,
        "origin_enu": [0., 0., 0.], "limits": limits,
        "selector_events": [selector(start, True), selector(start+.2)], "events": events, "clock_links": links}
    cases = []
    def add(name, expected=True):
        item = copy.deepcopy(base); item.update(name=name, expected_fixture_consistency=expected); cases.append(item); return item
    add("normal")
    case = add("input_before_rpc_return"); case["events"][3]["clock"]["stamp_s"] = start+.225
    case["events"][3]["host_monotonic_ns"] = 10**12 + 225000000
    case = add("sim_paused");
    for e in case["events"][3:4]: e["clock"]["stamp_s"] = start+.2
    for link in case["clock_links"]: link["sim_interval_s"] = [start+.2, start+.2]
    case = add("map_changed_and_rechecked"); case["selector_events"][1]["snapshot"]["revision"] = "map-2"
    case["events"][2]["checked_map_revision"] = "map-2"
    case = add("native_resends_unique_consumed_timestamp"); extra = copy.deepcopy(case["events"][4])
    extra["input_timestamp_us"] += 1000
    extra["clock"]["stamp_s"] = extra["input_timestamp_us"] / 1e6
    extra["clock_link_id"] = "resent-input"; extra["host_monotonic_ns"] += 1000000
    case["events"].append(extra)
    link = copy.deepcopy(case["clock_links"][0]); link.update(id="resent-input", source_clock=copy.deepcopy(extra["clock"]),
        sim_interval_s=[start+.221, start+.222]); case["clock_links"].append(link)
    case["events"][5]["used_input_timestamp_us"] = extra["input_timestamp_us"]
    case = add("candidate_version_mismatch", False); case["events"][1]["candidate_revision"] = 2
    case = add("sample_sequence_mismatch", False); case["events"][3]["sample_seq"] = 18
    case = add("clock_epoch_changed", False); case["events"][3]["clock"]["epoch"] = 1
    case = add("native_clock_anchor_missing", False); case["clock_links"] = []
    case = add("overlapping_clock_intervals", False); case["clock_links"][0]["sim_interval_s"][1] = start+.3
    case = add("same_epoch_clock_rewind", False); case["events"][3]["clock"]["stamp_s"] = start+.1
    case = add("map_revision_unrecorded", False); case["selector_events"][1]["snapshot"].pop("revision")
    case = add("map_revision_claim_stale", False); case["selector_events"][1]["snapshot"]["revision"] = "map-2"
    case = add("terminal_window_missing", False); case["selector_events"][1]["snapshot"]["valid_until_sim_s"] = end
    case = add("new_occupied_remaining_curve", False)
    point = handoff.pva(native, .3)[:, 0]; case["selector_events"][1]["snapshot"]["voxels"] = [[(point-.01).tolist(), (point+.01).tolist()]]
    case = add("controller_old_input", False); case["events"][5]["branch"] = "old_input"
    case = add("controller_failsafe", False); case["events"][5]["branch"] = "failsafe"
    case = add("controller_update_failed", False); case["events"][5]["update_success"] = False
    case = add("native_payload_sign_error", False); case["events"][4]["payload_ned"]["velocity"][0] *= -1
    case = add("controller_witness_missing", False); case["events"].pop()
    case = add("native_input_timestamp_ambiguous", False); case["events"].append(copy.deepcopy(case["events"][4]))
    case = add("duplicate_sender_start", False); case["events"].append(copy.deepcopy(case["events"][2]))
    case = add("native_after_candidate_end", False)
    for link in case["clock_links"]: link["sim_interval_s"] = [end+.1, end+.2]
    case = add("frame_context_changed", False); case["events"][1]["context"]["frame_id"] = "other-frame"
    case = add("observed_A_unknown", False)
    for axis in case["selector_events"][1]["observed_pva"]: axis[2] = None
    case = add("candidate_coefficients_tampered", False)
    case["selector_events"][0]["candidate"]["native"]["pieces"][0]["coefficients_descending"][2][-1] += 1.
    case = add("native_uuid_fabricated", False); case["events"][4]["candidate_id"] = "fixture-brake"
    case = add("all_metadata_relabels_candidate_body", False)
    for event in case["events"][:4]: event["candidate_revision"] = 2
    case = add("sample_phase_relabelled", False); case["events"][2]["sample_sim_s"] = start+.1
    case = add("cross_goal_sender", False); case["events"][2]["context"]["goal_id"] = "other-goal"
    case = add("native_source_clock_rewind", False)
    case["events"][5]["clock"]["stamp_s"] = 12.01
    case["clock_links"][1]["source_clock"] = copy.deepcopy(case["events"][5]["clock"])
    case = add("sample_selector_replaced_candidate", False)
    replacement = copy.deepcopy(case["selector_events"][0]["candidate"])
    replacement.update(candidate_id="another-brake", candidate_revision=2)
    case["selector_events"][1]["candidate"] = replacement
    case = add("native_clock_relabelled_to_sim", False)
    for event, offset in zip(case["events"][4:], (.22, .23)):
        event["clock"] = {"domain": "fixture-sim", "epoch": 0, "stamp_s": round((start+offset)*1e6)/1e6}
    case["events"][4]["input_timestamp_us"] = round((start+.22)*1e6)
    case["events"][5]["used_input_timestamp_us"] = case["events"][4]["input_timestamp_us"]
    case["clock_links"] = []
    case = add("rejected_new_candidate_keeps_original", True)
    replacement = copy.deepcopy(case["selector_events"][0]["candidate"])
    replacement.update(candidate_id="rejected-brake", candidate_revision=2)
    replacement["native"]["pieces"][0]["coefficients_descending"][2][-1] += 1.
    case["selector_events"][1]["candidate"] = replacement
    return cases


def run(source, root):
    result = {"kind": "offline_declared_handoff_event_fixtures", "rows": [], "warnings": [],
        "scope": "isolated candidate/sample fixtures, ideal PVA and declared static map/clock links; not recorded ACKs",
        "actual_execution_admission": "not_performed", "dynamic_closed_loop": "not_passed"}
    try:
        selected = [r for r in source["rows"] if isinstance(r, dict) and r.get("variant_id") == "reference-4-h0.1"
            and isinstance(r.get("profile"), dict) and r["profile"].get("name") == "zero_A_J"]
        if len(selected) != 1:
            raise ValueError("one original reference-4-h0.1/zero_A_J required")
        row = selected[0]; audit, handoff = committed.reuse(root)
        frames = load("event_fixture_frames", root / "frames.py")
        cases = build_cases(row["resolved"]["candidate"], source["archive_task_id"], row["start_sim_s"],
            row["hard_box"], row["hard_limits"], handoff, frames)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        return {**result, "status": "unscored", "reason": str(error)}
    result["archive_task_id"] = source["archive_task_id"]
    for case in cases:
        try:
            scored = assess(case, audit, handoff, frames)
            scored.update(expected_fixture_consistency=case["expected_fixture_consistency"],
                expectation_matched=scored["fixture_chain_consistent"] == case["expected_fixture_consistency"])
            try:
                json.dumps(case, allow_nan=False)
                scored["fixture"] = case
            except (ValueError, TypeError, OverflowError):
                scored["fixture_embedding"] = "omitted_nonfinite_or_non_json_values"
                result["warnings"].append(f"{case.get('name')}: invalid JSON fixture omitted; assessment retained")
            json.dumps(scored, allow_nan=False)
            result["rows"].append(scored)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError) as error:
            result["rows"].append({"name": case.get("name"), "status": "unscored", "reason": str(error)})
            result["warnings"].append(f"{case.get('name')}: {error}")
    result["summary"] = {"cases": len(result["rows"]),
        "fixture_consistent": sum(r.get("fixture_chain_consistent", False) for r in result["rows"]),
        "expectations_matched": sum(r.get("expectation_matched", False) for r in result["rows"]),
        "unscored": sum(r.get("status") == "unscored" for r in result["rows"])}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reanchor-report", type=Path, required=True)
    parser.add_argument("--drone-root", type=Path, default=Path.home() / "dev/ros2/projects/drone")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    warnings = []
    result = run(legacy.object_file(args.reanchor_report, warnings), args.drone_root)
    result["warnings"] = warnings + result["warnings"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result.get("summary", {"status": result.get("status"), "reason": result.get("reason")})))
    for warning in result["warnings"]:
        print("WARNING: " + warning)


if __name__ == "__main__":
    main()
