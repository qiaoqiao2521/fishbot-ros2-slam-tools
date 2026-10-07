#!/usr/bin/env python3
"""Offline geometric diagnostics for saved LaserScan JSON; never imports ROS.

This is an observed-point replay, not a passability certificate. Missing beams,
unseen obstacles, braking, moving objects and the turn to a proposed heading are
not inferred. Geometry comes from fishbot_model_geometry.yaml, not this file.
Historical scans without a frame require an explicit, recorded assumption.
"""

import argparse
from collections import Counter
import hashlib
import html
import importlib.util
import json
import math
from pathlib import Path
import sys

import yaml


HERE = Path(__file__).resolve().parent
DEFAULT_GEOMETRY = HERE / "config/fishbot_model_geometry.yaml"
DEFAULT_CM_CONFIG = HERE / "config/fishbot_passage_nav.yaml"
_builder = None
_guard = None


def parameter_builder():
    global _builder
    if _builder is None:
        module_path = HERE / "fishbot_passage.launch.py"
        spec = importlib.util.spec_from_file_location("fishbot_passage_config_replay", module_path)
        _builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_builder)
    return _builder


def command_guard_module():
    """Import only the guard's ROS-free definitions, never its main/ROS runner."""
    global _guard
    if _guard is None:
        name = "fishbot_command_guard_replay"
        spec = importlib.util.spec_from_file_location(name, HERE / "fishbot_command_guard.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module  # dataclasses resolves the defining module.
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(name, None)
            raise
        _guard = module
    return _guard


def finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def convex_hull(points):
    points = sorted(set(tuple(p) for p in points))
    if len(points) < 3:
        raise ValueError("footprint must enclose an area")

    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])

    lower, upper = [], []
    for collection, values in ((lower, points), (upper, reversed(points))):
        for point in values:
            while len(collection) >= 2 and cross(collection[-2], collection[-1], point) <= 0:
                collection.pop()
            collection.append(point)
    hull = lower[:-1] + upper[:-1]
    if len(hull) < 3:
        raise ValueError("footprint must enclose an area")
    return hull


def polygon_distance(point, polygon):
    """Distance to a convex filled polygon, zero on its boundary or inside."""
    x, y = point
    signs, distances = [], []
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        dx, dy = b[0]-a[0], b[1]-a[1]
        signs.append(dx*(y-a[1])-dy*(x-a[0]))
        t = max(0.0, min(1.0, ((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy)))
        distances.append(math.hypot(x-a[0]-t*dx, y-a[1]-t*dy))
    if all(s >= -1e-12 for s in signs) or all(s <= 1e-12 for s in signs):
        return 0.0
    return min(distances)


def rotate(point, angle):
    c, s = math.cos(angle), math.sin(angle)
    return (c*point[0]-s*point[1], s*point[0]+c*point[1])


def swept_polygon(polygon, distance):
    """Exact convex envelope for constant-heading straight translation."""
    return convex_hull(polygon + [(x+distance, y) for x, y in polygon])


def validate_geometry(geometry):
    if not isinstance(geometry, dict) or geometry.get("schema_version") != 1:
        raise ValueError("unsupported geometry schema")
    frames = geometry["frames"]
    if not all(isinstance(frames.get(k), str) and frames[k] for k in ("base", "scan")):
        raise ValueError("geometry requires base and scan frame names")
    transform = geometry["scan_to_base"]
    for key in ("x_m", "y_m", "yaw_rad"):
        finite(transform[key], key)
    points = geometry["footprint"]["points_m"]
    vertices = parameter_builder().convex_polygon(points)
    for key, value in (
        ("padding", geometry["footprint"]["padding_m"]),
        ("soft_padding", geometry["collision"]["soft_padding_m"]),
        ("hard_reaction_time", geometry["collision"]["hard_reaction_time_s"]),
        ("approach_time", geometry["collision"]["approach_time_s"]),
    ):
        if finite(value, key) < 0:
            raise ValueError(f"{key} must be nonnegative")
    if geometry["collision"]["min_points"] != 1:
        raise ValueError("replay requires min_points=1; thin obstacles must remain visible")
    return vertices


def load_geometry(path):
    geometry = yaml.safe_load(Path(path).read_text())
    validate_geometry(geometry)
    return geometry


def scan_points(document, geometry, assume_scan_frame=None):
    if not isinstance(document, dict) or not isinstance(document.get("latest", {}), dict):
        raise ValueError("scan document and latest must be objects")
    record = document.get("latest", {}).get("scan")
    if record is not None and not isinstance(record, dict):
        raise ValueError("saved scan record must be an object")
    if record is not None and record.get("error"):
        raise ValueError("saved scan rejected by command guard: " + str(record["error"]))
    scan = record["data"] if record is not None else document.get("scan", document)
    if not isinstance(scan, dict) or not isinstance(scan.get("header", {}), dict):
        raise ValueError("scan data/header must be objects")
    header = scan.get("header", {})
    frame = scan.get("frame_id") or header.get("frame_id")
    recorded_transform = scan.get("transform")
    if recorded_transform is not None:
        if not isinstance(recorded_transform, dict) or not isinstance(frame, str) or not frame:
            raise ValueError("recorded TF and scan frame are malformed")
        if (recorded_transform.get("source_frame") != frame
                or recorded_transform.get("target_frame") != geometry["frames"]["base"]):
            raise ValueError("recorded TF source/target frames disagree with scan/base")
        if assume_scan_frame and assume_scan_frame != frame:
            raise ValueError("frame assumption conflicts with the recorded frame")
        projected = command_guard_module().project_scan(scan, recorded_transform)
        recomputed = projected["points_base"]
        if "points_base" in scan:
            saved = scan["points_base"]
            if not isinstance(saved, list) or len(saved) != len(recomputed):
                raise ValueError("saved points_base disagrees with raw scan/TF")
            for original, actual in zip(saved, recomputed):
                if not isinstance(original, dict):
                    raise ValueError("saved points_base must contain point objects")
                for key in ("index", "range", "x", "y", "z"):
                    if abs(finite(original.get(key), "saved point " + key) - actual[key]) > 1e-7:
                        raise ValueError("saved points_base disagrees with raw scan/TF")
        points = [{"beam": p["index"], "x": p["x"], "y": p["y"], "z": p["z"]} for p in recomputed]
        ranges = scan["ranges"]
        return points, {"frame": frame, "frame_assumed": False,
            "projection": "recorded_3d_tf_recomputed", "target_frame": recorded_transform["target_frame"],
            "transform": recorded_transform, "points_base_verified": "points_base" in scan,
            "total_beams": len(ranges), "valid_returns": len(points),
            "invalid_returns": len(ranges)-len(points),
            "negative_returns": sum(isinstance(r, (int, float)) and not isinstance(r, bool) and r < 0 for r in ranges),
            "source_stamp": record.get("source_stamp") if record else None,
            "source_age_s": record.get("source_age_s") if record else None,
            "receive_age_s": record.get("receive_age_s") if record else None}
    if record is not None:
        raise ValueError("command guard snapshot has no recorded scan TF")
    assumed = not frame and bool(assume_scan_frame)
    if not frame:
        frame = assume_scan_frame
    if frame not in (geometry["frames"]["scan"], geometry["frames"]["base"]):
        raise ValueError(f"missing or unknown scan frame: {frame!r}")
    if assume_scan_frame and not assumed and assume_scan_frame != frame:
        raise ValueError("frame assumption conflicts with the recorded frame")
    angle_min = finite(scan["angle_min"], "angle_min")
    increment = finite(scan["angle_increment"], "angle_increment")
    minimum = finite(scan["range_min"], "range_min")
    maximum = finite(scan["range_max"], "range_max")
    ranges = scan["ranges"]
    if not isinstance(ranges, list) or not ranges or len(ranges) > 200000:
        raise ValueError("ranges must be a nonempty bounded list")
    if increment == 0 or minimum < 0 or maximum <= minimum:
        raise ValueError("invalid angle increment or range limits")
    points, invalid, negative = [], 0, 0
    transform = geometry["scan_to_base"]
    for i, distance in enumerate(ranges):
        if distance is None or isinstance(distance, bool) or not isinstance(distance, (int, float)):
            invalid += 1
            continue
        if distance < 0:
            negative += 1
        if not math.isfinite(distance) or distance <= 0 or not minimum <= distance <= maximum:
            invalid += 1
            continue
        angle = angle_min + i*increment
        point = (distance*math.cos(angle), distance*math.sin(angle))
        if frame != geometry["frames"]["base"]:
            x, y = rotate(point, transform["yaw_rad"])
            point = (x+transform["x_m"], y+transform["y_m"])
        points.append({"beam": i, "x": point[0], "y": point[1]})
    return points, {"frame": frame, "frame_assumed": assumed,
                    "projection": "configured_static_planar_tf",
                    "total_beams": len(ranges), "valid_returns": len(points),
                    "invalid_returns": invalid, "negative_returns": negative}


def cm_polygons(parameters, velocity, angular_velocity=0.0):
    """Use the exact generated Collision Monitor polygons, in selection order."""
    node = parameters.get("collision_monitor", parameters)
    node = node.get("ros__parameters", node)
    result = {}
    for name in node.get("polygons", []):
        zone = node[name]
        if zone.get("type") == "velocity_polygon":
            for child in zone["velocity_polygons"]:
                candidate = zone[child]
                if (candidate["linear_min"] <= velocity <= candidate["linear_max"]
                        and candidate["theta_min"] <= angular_velocity <= candidate["theta_max"]):
                    result["cm_hard"] = {"polygon": json.loads(candidate["points"]),
                                         "padding_m": 0.0, "selected_polygon": child}
                    break
            else:
                raise ValueError("velocity is outside Collision Monitor polygon ranges")
        elif zone.get("action_type") == "limit":
            result["cm_slow"] = {"polygon": json.loads(zone["points"]), "padding_m": 0.0}
    if set(result) != {"cm_hard", "cm_slow"}:
        raise ValueError("missing generated Collision Monitor hard/slow polygons")
    return result


def load_cm_parameters(config_path, geometry_path):
    parameters, _geometry = parameter_builder().load_parameters(config_path, geometry_path)
    return parameters


def evaluate_scan(document, geometry, velocity_mps=None, heading_rad=0.0,
                  assume_scan_frame=None, cm_parameters=None, legacy_guard=None,
                  angular_velocity_rps=None):
    """Evaluate observed points in the current and hypothetical straight sweeps.

    heading_rad rotates the proposed footprint and motion relative to the saved
    base frame; it does not certify the intervening rotation. Nonzero angular
    motion uses the generated CM velocity envelope; straight sweep zones remain
    labeled counterfactual diagnostics, not approximations of a turning arc.
    """
    if not isinstance(document, dict) or not isinstance(document.get("latest", {}), dict):
        raise ValueError("scan document and latest must be objects")
    snapshot = "latest" in document
    if snapshot and "geometry" in document:
        geometry = document["geometry"]
        if cm_parameters is not None:
            cm_parameters = parameter_builder().build_parameters(cm_parameters, geometry)
    raw_footprint = validate_geometry(geometry)
    command_record = document.get("latest", {}).get("command", {})
    upstream_record = document.get("latest", {}).get("desired_command", {})
    use_upstream = document.get("kind") == "collision_stop" and bool(upstream_record)
    velocity_record = upstream_record if use_upstream else command_record
    command = velocity_record.get("data", {}).get("twist")
    if velocity_mps is None and command is not None:
        command = command_guard_module().vector(command, 6, "saved Twist")
        velocity_mps = command[0]
        velocity_source = ("saved_upstream_command_at_state_callback" if use_upstream else
                           "saved_latest_command_not_time_synchronized_with_scan")
    else:
        velocity_source = "explicit_offline_scenario" if velocity_mps is not None else "default_offline_scenario"
        velocity_mps = 0.03 if velocity_mps is None else velocity_mps
    if angular_velocity_rps is None:
        angular_velocity_rps = command[5] if command is not None and velocity_source.startswith("saved_") else 0.0
    velocity = finite(velocity_mps, "velocity_mps")
    angular_velocity = finite(angular_velocity_rps, "angular_velocity_rps")
    heading = finite(heading_rad, "heading_rad")
    if (abs(velocity) > geometry["motion"]["max_linear_mps"] + 1e-9
            or abs(angular_velocity) > geometry["motion"]["max_angular_rps"] + 1e-9):
        raise ValueError("velocity exceeds the configured model profile")
    points, quality = scan_points(document, geometry, assume_scan_frame)
    collision = geometry["collision"]
    padding = geometry["footprint"]["padding_m"]
    # Share the exact padded support envelope used by Nav2, including corners.
    footprint = parameter_builder().expanded_polygon(raw_footprint, padding)
    soft_footprint = parameter_builder().expanded_polygon(raw_footprint, padding+collision["soft_padding_m"])
    zones = {
        "hard_current": {"polygon": footprint, "padding_m": 0.0},
        "hard_straight": {"polygon": swept_polygon(footprint, velocity*collision["hard_reaction_time_s"]),
                          "padding_m": 0.0},
        "approach_straight": {"polygon": swept_polygon(footprint, velocity*collision["approach_time_s"]),
                              "padding_m": 0.0},
        "soft_straight": {"polygon": swept_polygon(soft_footprint, velocity*collision["approach_time_s"]),
                          "padding_m": 0.0},
    }
    if cm_parameters is not None:
        zones.update(cm_polygons(cm_parameters, velocity, angular_velocity))
    for name, zone in zones.items():
        # hard_current is the actual current pose, even in a heading preview.
        zone["polygon"] = [rotate(p, 0 if name == "hard_current" else heading) for p in zone["polygon"]]
        zone["hits"] = [p for p in points if polygon_distance((p["x"], p["y"]), zone["polygon"])
                        <= zone["padding_m"] + 1e-12]
    hard = "cm_hard" if cm_parameters is not None else "hard_straight"
    slow = "cm_slow" if cm_parameters is not None else "soft_straight"
    classification = ("hard_current" if zones["hard_current"]["hits"] else
                      "hard_future" if zones[hard]["hits"] else
                      "slowdown" if zones[slow]["hits"] or (angular_velocity == 0 and zones["approach_straight"]["hits"]) else
                      "clear_observed")
    if not points or quality["negative_returns"]:
        classification = "unknown"
    saved_velocity = document.get("odom", {}).get("v")
    if snapshot:
        linear = document.get("latest", {}).get("odom", {}).get("data", {}).get("linear", [])
        saved_velocity = linear[0] if linear else None
    if isinstance(saved_velocity, bool) or not isinstance(saved_velocity, (int, float)) or not math.isfinite(saved_velocity):
        saved_velocity = None
    report = {"classification": classification, "quality": quality,
              "velocity_mps": velocity, "angular_velocity_rps": angular_velocity,
              "straight_sweeps_applicable": angular_velocity == 0,
              "heading_rad": heading, "zones": zones,
              "velocity_source": velocity_source,
              "saved_velocity_mps": saved_velocity,
              "points": points, "physical_passability": "not_established",
              "model_basis": "official_model_not_measured_robot",
              "geometry_used": geometry,
              "geometry_basis": "saved_guard_snapshot" if snapshot and "geometry" in document else "supplied_configuration",
              "limitations": ["observed returns only; invalid or missing beams are unknown",
                              "static scan; no braking or latency validation",
                              "heading preview excludes the turn needed to align",
                              "post-stop snapshot is not the unrecorded triggering scan"]}
    if snapshot:
        report["collision_association"] = document.get("collision_association", "not recorded; association unknown")
        report["collision_decision_reproduction"] = "not_established"
        report["event"] = {key: document.get(key) for key in ("kind", "reason", "ros_time", "event_sequence")}
        report["saved_command"] = command_record
        report["saved_upstream_command"] = upstream_record
        if velocity_record.get("error") and velocity_source.startswith("saved_"):
            report["classification"] = "unknown"
        report["recorded_zones"] = {}
        report["recorded_zone_errors"] = {}
        for name, zone in document.get("zones", {}).items():
            try:
                if zone.get("frame_id") != geometry["frames"]["base"]:
                    raise ValueError("recorded polygon is not in the base frame")
                vertices = [command_guard_module().vector(p, 3, "zone point") for p in zone["points"]]
                polygon = convex_hull([(p[0], p[1]) for p in vertices])
                report["recorded_zones"][name] = {**zone,
                    "comparison": "latest received polygon and scan; exact CM pairing unknown",
                    "hits": [p for p in points if polygon_distance((p["x"], p["y"]), polygon) <= 1e-12]}
            except (KeyError, TypeError, ValueError) as exc:
                report["recorded_zone_errors"][name] = str(exc)
        report["limitations"][-1] = report["collision_association"]
    if legacy_guard is not None:
        front, half_width = legacy_guard
        report["legacy_guard"] = {"front_m": front, "half_width_m": half_width,
            "hits": [p for p in points if 0 < p["x"] < front and abs(p["y"]) < half_width]}
    return report


def svg_report(report, title):
    """A local diagnostic drawing, with forward up and left to the left."""
    def xy(point):
        return 400-point[1]*450, 470-point[0]*450

    def polygon(points):
        return " ".join(f"{x:.2f},{y:.2f}" for x, y in map(xy, points))

    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="800" height="800" viewBox="0 0 800 800">',
             '<rect width="800" height="800" fill="#f6f8fa"/>',
             f'<text x="24" y="30" font-family="sans-serif" font-size="18">{html.escape(title)}</text>',
             f'<text x="24" y="57" font-family="sans-serif">{html.escape(report["classification"])} | model assumption | offline only</text>',
             '<path d="M400 680 V100 M100 470 H700" stroke="#bcc6ce" stroke-dasharray="4 4"/>',
             '<text x="410" y="95">+x forward</text><text x="35" y="465">+y left</text>']
    colors = {"hard_current": "#991b1b", "hard_straight": "#dc2626", "approach_straight": "#7c3aed",
              "soft_straight": "#d97706", "cm_hard": "#dc2626", "cm_slow": "#d97706"}
    names = ["cm_slow", "cm_hard", "hard_current"] if "cm_hard" in report["zones"] else ["soft_straight", "hard_straight", "hard_current"]
    for name in names:
        zone = report["zones"][name]
        parts.append(f'<polygon points="{polygon(zone["polygon"])}" fill="{colors[name]}" fill-opacity=".09" '
                     f'stroke="{colors[name]}" stroke-width="{max(1, zone["padding_m"]*900):.2f}" stroke-linejoin="round"/>')
    if "legacy_guard" in report:
        front, width = report["legacy_guard"]["front_m"], report["legacy_guard"]["half_width_m"]
        parts.append(f'<polygon points="{polygon([(0, -width), (front, -width), (front, width), (0, width)])}" '
                     'fill="none" stroke="#64748b" stroke-dasharray="5 4" stroke-width="1.5"/>')
        parts.append('<text x="450" y="660" font-family="sans-serif" fill="#64748b">dashed: historical stop box</text>')
    recorded_stop = report.get("recorded_zones", {}).get("stop_polygon")
    if recorded_stop:
        parts.append(f'<polygon points="{polygon([(p[0], p[1]) for p in recorded_stop["points"]])}" '
                     'fill="none" stroke="#0891b2" stroke-dasharray="3 3" stroke-width="2"/>')
        parts.append('<text x="430" y="680" font-family="sans-serif" fill="#0891b2">recorded stop zone (async)</text>')
    for point in report["points"]:
        x, y = xy((point["x"], point["y"]))
        if 5 < x < 795 and 75 < y < 690:
            parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2.1" fill="#253850"/>')
    for index, name in enumerate(names):
        parts.append(f'<text x="24" y="{715+index*23}" fill="{colors[name]}" font-family="sans-serif">'
                     f'{name}: {len(report["zones"][name]["hits"])} observed points</text>')
    frame_note = "assumed" if report["quality"]["frame_assumed"] else "recorded"
    parts.append(f'<text x="24" y="790" font-family="sans-serif" font-size="13">'
                 f'frame {html.escape(report["quality"]["frame"])} ({frame_note}); v={report["velocity_mps"]:.3f}, w={report["angular_velocity_rps"]:.3f}; '
                 'not physical passability</text>')
    parts.append('</svg>')
    return "\n".join(parts)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def private_write(path, content):
    with path.open("x") as handle:
        path.chmod(0o600)
        handle.write(content)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scans", nargs="+", type=Path)
    parser.add_argument("--geometry", type=Path, default=DEFAULT_GEOMETRY)
    parser.add_argument("--cm-config", type=Path, default=DEFAULT_CM_CONFIG,
                        help="exact generated Collision Monitor zones (default: shared passage config)")
    parser.add_argument("--assume-scan-frame", help="historical data only; cannot override a recorded frame")
    parser.add_argument("--frame-evidence", type=Path, help="hash a local historical frame configuration")
    parser.add_argument("--velocity", type=float,
                        help="scenario override; collision stop uses saved upstream input, else saved candidate or 0.03")
    parser.add_argument("--angular-velocity", type=float, help="scenario override; default: saved command, else zero")
    parser.add_argument("--heading-deg", type=float, default=0.0)
    parser.add_argument("--legacy-guard", nargs=2, type=float, metavar=("FRONT_M", "HALF_WIDTH_M"))
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    geometry = load_geometry(args.geometry)
    cm = load_cm_parameters(args.cm_config, args.geometry) if args.cm_config else None
    args.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    summaries = []
    for index, path in enumerate(args.scans):
        identifier = f"{index:03d}-{path.stem}"
        document = {}
        try:
            document = json.loads(path.read_text())
            report = evaluate_scan(document, geometry, args.velocity,
                                   math.radians(args.heading_deg), args.assume_scan_frame, cm,
                                   args.legacy_guard, args.angular_velocity)
        except (KeyError, TypeError, ValueError) as exc:
            report = {"classification": "unknown", "error": str(exc), "physical_passability": "not_established"}
            if isinstance(document, dict) and "collision_association" in document:
                report["collision_association"] = document["collision_association"]
        report.update({"source": str(path.resolve()), "source_sha256": sha256(path),
                       "configured_geometry_source": str(args.geometry.resolve()), "configured_geometry_sha256": sha256(args.geometry),
                       "geometry_sha256": hashlib.sha256(json.dumps(report.get("geometry_used", geometry), sort_keys=True).encode()).hexdigest(),
                       "tool_sha256": sha256(__file__)})
        if report.get("quality", {}).get("projection") == "recorded_3d_tf_recomputed":
            report["scan_projector_sha256"] = sha256(HERE / "fishbot_command_guard.py")
        if args.cm_config:
            report["cm_config_sha256"] = sha256(args.cm_config)
            report["cm_builder_sha256"] = sha256(HERE / "fishbot_passage.launch.py")
        if args.frame_evidence:
            report["frame_evidence"] = {"path": str(args.frame_evidence.resolve()), "sha256": sha256(args.frame_evidence)}
        private_write(args.output_dir / (identifier+".json"), json.dumps(report, indent=2, allow_nan=False))
        if "zones" in report:
            private_write(args.output_dir / (identifier+".svg"), svg_report(report, path.name))
        summaries.append({"input": path.name, "report": identifier+".json", "classification": report["classification"],
                          "frame_assumed": report.get("quality", {}).get("frame_assumed"),
                          "legacy_hits": len(report.get("legacy_guard", {}).get("hits", [])),
                          "zone_hits": {k: len(v["hits"]) for k, v in report.get("zones", {}).items()}})
    counts = dict(Counter(s["classification"] for s in summaries))
    private_write(args.output_dir / "summary.json", json.dumps({"counts": counts, "scans": summaries}, indent=2))
    rows = "".join(f'<tr><td><a href="{html.escape(s["report"][:-5]+".svg" if s["zone_hits"] else s["report"])}">{html.escape(s["input"])}</a></td>'
                   f'<td>{s["classification"]}</td><td>{s["legacy_hits"]}</td><td>{html.escape(str(s["zone_hits"]))}</td></tr>' for s in summaries)
    private_write(args.output_dir / "index.html", '<!doctype html><meta charset="utf-8"><title>FishBot offline scan replay</title>'
                  '<style>body{font:16px system-ui;max-width:1200px;margin:40px auto}td,th{padding:10px;border-bottom:1px solid #ccc;text-align:left}</style>'
                  '<h1>FishBot offline scan replay</h1><p>Official model assumption; observed points only. This does not establish a physical passage.</p>'
                  '<p>Missing scan frames are explicit historical assumptions. Later snapshots cannot establish why an earlier unrecorded scan stopped the car.</p>'
                  '<p>Guard snapshots use recorded 3D TF and verify saved points. Latest scans, CM polygons and commands are not a synchronized Collision Monitor input set.</p>'
                  f'<pre>{html.escape(json.dumps(counts))}</pre><table><tr><th>Scan</th><th>Classification</th><th>Legacy points</th><th>Zone points</th></tr>{rows}</table>')
    print(json.dumps({"output_dir": str(args.output_dir.resolve()), "counts": counts, "scans": len(summaries)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
