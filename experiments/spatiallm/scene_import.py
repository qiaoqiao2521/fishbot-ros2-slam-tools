"""Strict, offline SpatialLM layout adapter and conservative MuJoCo export.

The official parser supplies entity objects. This adapter checks its complete
result because upstream Layout.from_str deliberately skips invalid lines.
No model is imported and no layout text is executed as Python.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import threading
import types
import xml.etree.ElementTree as ET


_FIELDS = {
    "wall": ("ax", "ay", "az", "bx", "by", "bz", "height", "thickness"),
    "door": ("wall_id", "position_x", "position_y", "position_z", "width", "height"),
    "window": ("wall_id", "position_x", "position_y", "position_z", "width", "height"),
    "bbox": ("class_name", "position_x", "position_y", "position_z", "angle_z",
             "scale_x", "scale_y", "scale_z"),
}
_LINE = re.compile(r"(wall|door|window|bbox)_(0|[1-9]\d*)\s*=\s*(Wall|Door|Window|Bbox)\(([^()]*)\)")
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_ID = re.compile(r"(wall|door|window|bbox)_(0|[1-9]\d*)")
_IMPORT_LOCK = threading.RLock()
_TOL = 1e-6
_MAX_ENTITIES = 10000
_MAX_TEXT_BYTES = 5_000_000
OFFICIAL_SOURCE_COMMIT = "8913c44d84a450c53e9340b13317f8cf7144a738"
_OFFICIAL_MODULE_HASHES = {
    "official_layout_module_sha256": "f3abe67c4bf5221c269e11885b8a1258abb3b4a403eaa19a094d37eff85756cf",
    "official_entity_module_sha256": "0384d489f4af8600123a35f1cda75695a7b9d6d840bcf39a69322d1bce2c8c0b",
}
_ROBOT_MODEL = Path("workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/mjcf/fishbot.xml")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_value(value, location: str = "metadata") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            _json_value(item, f"{location}[{i}]")
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for key, item in value.items():
            _json_value(item, f"{location}.{key}")
        return
    raise ValueError(f"{location}: only finite JSON metadata is accepted")


def _finite(value, location: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{location}: expected a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{location}: expected a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{location}: expected a finite number")
    return result


def _validate_params(kind: str, params: dict, entity_id: str) -> dict:
    if not isinstance(params, dict) or set(params) != set(_FIELDS[kind]):
        raise ValueError(f"{entity_id}: expected exactly {', '.join(_FIELDS[kind])}")
    result = {}
    for key, value in params.items():
        if key == "wall_id":
            if type(value) is not int or value < 0:
                raise ValueError(f"{entity_id}.wall_id: expected a nonnegative integer")
            result[key] = value
        elif key == "class_name":
            if (not isinstance(value, str) or not value.strip() or len(value) > 128
                    or any(ord(c) < 32 or c in ",()" for c in value)):
                raise ValueError(f"{entity_id}.class_name: expected a plain, nonempty label")
            result[key] = value.strip()
        else:
            result[key] = _finite(value, f"{entity_id}.{key}")
    if kind == "wall":
        if result["height"] <= 0 or result["thickness"] < 0:
            raise ValueError(f"{entity_id}: height must be positive; thickness cannot be negative")
        length = math.hypot(result["bx"] - result["ax"], result["by"] - result["ay"])
        if not math.isfinite(length) or length <= _TOL:
            raise ValueError(f"{entity_id}: wall needs a nonzero horizontal baseline")
    elif kind in ("door", "window"):
        if result["width"] <= 0 or result["height"] <= 0:
            raise ValueError(f"{entity_id}: opening width and height must be positive")
    elif any(result[key] <= 0 for key in ("scale_x", "scale_y", "scale_z")):
        raise ValueError(f"{entity_id}: bbox full dimensions must be positive")
    return result


def _warnings(entities: list) -> list[str]:
    warnings = [f"{e['id']}: zero wall thickness; set an explicit positive thickness before collision export"
                for e in entities if e["kind"] == "wall" and e["params"]["thickness"] == 0]
    if any(e["kind"] == "bbox" for e in entities):
        warnings.append("Object bboxes are conservative solid collision approximations, not furniture meshes.")
    if any(e["kind"] == "window" for e in entities):
        warnings.append("Window apertures retain full-thickness collision panels; only doors are open passages.")
    return warnings


def _validated_doc(doc: dict) -> dict:
    if not isinstance(doc, dict):
        raise ValueError("layout document must be an object")
    required = {"schema_version", "coordinate_system", "units", "source", "entities", "corrections", "warnings"}
    if set(doc) != required:
        raise ValueError(f"layout document requires exactly {', '.join(sorted(required))}")
    if type(doc["schema_version"]) is not int or doc["schema_version"] != 1:
        raise ValueError("unsupported schema_version; expected 1")
    if doc["coordinate_system"] != "right-handed-z-up" or doc["units"] != "m":
        raise ValueError("expected right-handed-z-up coordinates in metres")
    if not isinstance(doc["source"], dict):
        raise ValueError("source metadata must be an object")
    _json_value(doc["source"], "source")
    for key in ("layout_sha256", "official_layout_module_sha256", "official_entity_module_sha256"):
        if not re.fullmatch(r"[a-f0-9]{64}", str(doc["source"].get(key, ""))):
            raise ValueError(f"source.{key}: expected a SHA-256 digest from load_layout")
    if doc["source"].get("official_source_commit") != OFFICIAL_SOURCE_COMMIT:
        raise ValueError("source.official_source_commit differs from the pinned official parser")
    if any(doc["source"][key] != value for key, value in _OFFICIAL_MODULE_HASHES.items()):
        raise ValueError("source geometry module hashes differ from the pinned official parser")
    if type(doc["source"].get("layout_bytes")) is not int or doc["source"]["layout_bytes"] <= 0:
        raise ValueError("source.layout_bytes: expected a positive integer from load_layout")
    if not isinstance(doc["entities"], list) or not 0 < len(doc["entities"]) <= _MAX_ENTITIES:
        raise ValueError(f"entities: expected 1 to {_MAX_ENTITIES} entities")
    result = copy.deepcopy(doc)
    ids = set()
    for entity in result["entities"]:
        if not isinstance(entity, dict) or set(entity) != {"id", "kind", "params"}:
            raise ValueError("each entity needs exactly id, kind, params")
        entity_id, kind = entity["id"], entity["kind"]
        match = _ID.fullmatch(entity_id) if isinstance(entity_id, str) else None
        if not match or match[1] != kind or kind not in _FIELDS:
            raise ValueError(f"{entity_id}: invalid entity id or kind")
        if entity_id in ids:
            raise ValueError(f"{entity_id}: duplicate entity id")
        ids.add(entity_id)
        entity["params"] = _validate_params(kind, entity["params"], entity_id)
    for entity in result["entities"]:
        if entity["kind"] in ("door", "window"):
            wall_id = entity["params"]["wall_id"]
            if f"wall_{wall_id}" not in ids:
                raise ValueError(f"{entity['id']}: referenced wall_{wall_id} does not exist")
    if not isinstance(result["corrections"], list) or not isinstance(result["warnings"], list):
        raise ValueError("corrections and warnings must be lists")
    if not all(isinstance(w, str) for w in result["warnings"]):
        raise ValueError("warnings must contain strings")
    for correction in result["corrections"]:
        if not isinstance(correction, dict) or set(correction) != {"id", "before", "after"}:
            raise ValueError("corrections require id, before and after")
        entity_id = correction["id"]
        match = _ID.fullmatch(entity_id) if isinstance(entity_id, str) else None
        if not match or entity_id not in ids:
            raise ValueError("correction references an invalid entity id")
        _validate_params(match[1], correction["before"], entity_id)
        _validate_params(match[1], correction["after"], entity_id)
    result["warnings"] = _warnings(result["entities"])
    return result


def _official_layout_class(source_dir: Path):
    """Load only the two official geometry modules, restoring package aliases."""
    source_dir = Path(source_dir).resolve()
    layout_file = source_dir / "spatiallm/layout/layout.py"
    entity_file = source_dir / "spatiallm/layout/entity.py"
    if not layout_file.is_file() or not entity_file.is_file():
        raise ValueError("source_dir must contain official spatiallm/layout/{layout,entity}.py")
    digests = {"official_layout_module_sha256": _sha(layout_file.read_bytes()),
               "official_entity_module_sha256": _sha(entity_file.read_bytes())}
    if digests != _OFFICIAL_MODULE_HASHES:
        raise ValueError(f"official geometry modules differ from pinned source {OFFICIAL_SOURCE_COMMIT}")
    names = ("spatiallm", "spatiallm.layout", "spatiallm.layout.entity", "spatiallm.layout.layout")
    with _IMPORT_LOCK:
        previous = {name: sys.modules.get(name) for name in names}
        try:
            for name, folder in (("spatiallm", source_dir / "spatiallm"),
                                 ("spatiallm.layout", source_dir / "spatiallm/layout")):
                package = types.ModuleType(name)
                package.__path__ = [str(folder)]
                sys.modules[name] = package
            for name, path in (("spatiallm.layout.entity", entity_file),
                               ("spatiallm.layout.layout", layout_file)):
                spec = importlib.util.spec_from_file_location(name, path)
                if spec is None or spec.loader is None:
                    raise ValueError(f"cannot load official module {path.name}")
                module = importlib.util.module_from_spec(spec)
                sys.modules[name] = module
                spec.loader.exec_module(module)
            return sys.modules["spatiallm.layout.layout"].Layout, digests
        except ImportError as exc:
            raise ValueError("official geometry parser needs numpy and scipy; no model dependency is needed") from exc
        finally:
            for name, old in previous.items():
                if old is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = old


def load_layout(text: str, source_dir: Path, source: dict) -> dict:
    """Import official floating-point layout text with loss detection."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("layout text must be a nonempty string")
    try:
        raw = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("layout text must contain valid UTF-8 characters") from exc
    if len(raw) > _MAX_TEXT_BYTES:
        raise ValueError(f"layout text exceeds {_MAX_TEXT_BYTES} bytes")
    if not isinstance(source, dict):
        raise ValueError("source metadata must be an object")
    _json_value(source, "source")
    entities = []
    ids, walls = set(), set()
    for line_no, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        match = _LINE.fullmatch(line)
        if not match:
            raise ValueError(f"line {line_no}: invalid entity assignment; executable Python is not accepted")
        kind, number, constructor, arguments = match.groups()
        entity_id = f"{kind}_{number}"
        if constructor != kind.capitalize():
            raise ValueError(f"line {line_no}: constructor does not match {kind}")
        if entity_id in ids:
            raise ValueError(f"line {line_no}: duplicate entity id {entity_id}")
        values = [value.strip() for value in arguments.split(",")]
        if len(values) != len(_FIELDS[kind]):
            raise ValueError(f"line {line_no}: {kind} expects {len(_FIELDS[kind])} parameters")
        params = {}
        for key, value in zip(_FIELDS[kind], values):
            if key == "wall_id":
                wall_match = re.fullmatch(r"wall_(0|[1-9]\d*)", value)
                if not wall_match or int(wall_match[1]) not in walls:
                    raise ValueError(f"line {line_no}: opening must reference an earlier existing wall")
                params[key] = int(wall_match[1])
            elif key == "class_name":
                params[key] = value
            else:
                if not _NUMBER.fullmatch(value):
                    raise ValueError(f"line {line_no}: {key} must be a finite numeric literal")
                params[key] = float(value)
        params = _validate_params(kind, params, entity_id)
        entities.append({"id": entity_id, "kind": kind, "params": params})
        ids.add(entity_id)
        if kind == "wall":
            walls.add(int(number))
        if len(entities) > _MAX_ENTITIES:
            raise ValueError(f"layout exceeds {_MAX_ENTITIES} entities")
    if not entities:
        raise ValueError("layout contains no entities")
    layout_class, module_digests = _official_layout_class(source_dir)
    # Canonical spacing prevents upstream's positional parser from losing IDs.
    canonical = []
    for entity in entities:
        params = entity["params"]
        values = [f"wall_{params[key]}" if key == "wall_id" else str(params[key])
                  for key in _FIELDS[entity["kind"]]]
        canonical.append(f"{entity['id']}={entity['kind'].capitalize()}({','.join(values)})")
    official = layout_class("\n".join(canonical))
    parsed = {}
    for entity in official.get_entities():
        kind = entity.entity_label
        entity_id = f"{kind}_{entity.id}"
        if kind not in _FIELDS or entity_id in parsed:
            raise ValueError("official parser returned an invalid or duplicate entity")
        parsed[entity_id] = {key: getattr(entity, key) for key in _FIELDS[kind]}
    if len(parsed) != len(entities):
        raise ValueError("official parser silently lost entities; import was rejected")
    for entity in entities:
        if parsed.get(entity["id"]) != entity["params"]:
            raise ValueError(f"official parser changed {entity['id']}; import was rejected")
    provenance = copy.deepcopy(source)
    computed = {"layout_sha256": _sha(raw), "layout_bytes": len(raw),
                "official_source_commit": OFFICIAL_SOURCE_COMMIT, **module_digests}
    for key, value in computed.items():
        if key in provenance and provenance[key] != value:
            raise ValueError(f"source.{key}: supplied metadata conflicts with imported bytes")
        provenance[key] = value
    return _validated_doc({"schema_version": 1, "coordinate_system": "right-handed-z-up",
                           "units": "m", "source": provenance, "entities": entities,
                           "corrections": [], "warnings": []})


def apply_edits(doc: dict, edits: list) -> dict:
    """Return a corrected copy, retaining complete before/after parameters."""
    result = _validated_doc(doc)
    if not isinstance(edits, list):
        raise ValueError("edits must be a list of {id, params} objects")
    lookup = {entity["id"]: entity for entity in result["entities"]}
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {"id", "params"}:
            raise ValueError("each edit needs exactly id and params")
        if not isinstance(edit["id"], str) or edit["id"] not in lookup:
            raise ValueError(f"unknown edit entity {edit.get('id')}")
        entity = lookup[edit["id"]]
        if not isinstance(edit["params"], dict) or not edit["params"]:
            raise ValueError(f"{edit['id']}: edit params must be a nonempty object")
        if not set(edit["params"]) <= set(_FIELDS[entity["kind"]]):
            raise ValueError(f"{edit['id']}: unknown parameter in edit")
        before = copy.deepcopy(entity["params"])
        after = _validate_params(entity["kind"], {**before, **edit["params"]}, entity["id"])
        entity["params"] = after
        if before != after:
            result["corrections"].append({"id": entity["id"], "before": before, "after": copy.deepcopy(after)})
    return _validated_doc(result)


def serialize_layout(doc: dict, source_dir: Path) -> str:
    """Return corrected official layout text, rejecting any lossy roundtrip.

    Upstream door/window/bbox serializers reduce IDs modulo 1000. The adapter
    must reject that identity change rather than silently relabel corrections.
    """
    clean = _validated_doc(doc)
    layout_class, _ = _official_layout_class(source_dir)
    layout = layout_class()
    groups = {"wall": "walls", "door": "doors", "window": "windows", "bbox": "bboxes"}
    official_classes = layout_class.from_str.__globals__
    for entity in clean["entities"]:
        entity_class = official_classes[entity["kind"].capitalize()]
        official_entity = entity_class(id=int(entity["id"].split("_")[1]), **entity["params"])
        getattr(layout, groups[entity["kind"]]).append(official_entity)
    text = layout.to_language_string() + "\n"
    try:
        imported = load_layout(text, source_dir, {"kind": "official-serialization-roundtrip"})
    except ValueError as exc:
        raise ValueError(f"official serialization cannot roundtrip this layout: {exc}") from exc
    expected = {entity["id"]: entity for entity in clean["entities"]}
    actual = {entity["id"]: entity for entity in imported["entities"]}
    if actual != expected:
        raise ValueError("official serialization changed entity IDs or parameters; door/window/bbox IDs must be below 1000")
    return text


def _wall_geometry(wall: dict, openings: list) -> tuple:
    p = wall["params"]
    if p["thickness"] <= 0:
        raise ValueError(f"{wall['id']}: zero thickness cannot produce collision walls; apply an explicit correction")
    if abs(p["az"] - p["bz"]) > _TOL:
        raise ValueError(f"{wall['id']}: non-horizontal wall baseline is not supported")
    length = math.hypot(p["bx"] - p["ax"], p["by"] - p["ay"])
    tx, ty = (p["bx"] - p["ax"]) / length, (p["by"] - p["ay"]) / length
    holes = []
    for opening in openings:
        op = opening["params"]
        dx, dy = op["position_x"] - p["ax"], op["position_y"] - p["ay"]
        offset = -ty * dx + tx * dy
        if abs(offset) > _TOL:
            raise ValueError(f"{opening['id']}: opening center is off the wall plane by {offset:.6g} m")
        u = tx * dx + ty * dy
        z = op["position_z"] - p["az"]
        rect = (u - op["width"] / 2, u + op["width"] / 2,
                z - op["height"] / 2, z + op["height"] / 2)
        if rect[0] < -_TOL or rect[1] > length + _TOL or rect[2] < -_TOL or rect[3] > p["height"] + _TOL:
            raise ValueError(f"{opening['id']}: opening extends beyond {wall['id']} bounds")
        # Clamp floating-point annotation noise, not materially invalid dimensions.
        rect = (max(0., rect[0]), min(length, rect[1]), max(0., rect[2]), min(p["height"], rect[3]))
        for previous, other in holes:
            if min(rect[1], previous[1]) - max(rect[0], previous[0]) > _TOL and min(rect[3], previous[3]) - max(rect[2], previous[2]) > _TOL:
                raise ValueError(f"{opening['id']}: opening overlaps {other['id']}")
        holes.append((rect, opening))
    cuts = sorted({0., length, *(value for rect, _ in holes for value in rect[:2])})
    pieces = []
    for left, right in zip(cuts, cuts[1:]):
        if right - left <= _TOL:
            continue
        middle = (left + right) / 2
        excluded = sorted((rect[2], rect[3]) for rect, _ in holes if rect[0] < middle < rect[1])
        bottom = 0.
        for low, high in excluded:
            if low - bottom > _TOL:
                pieces.append((left, right, bottom, low))
            bottom = max(bottom, high)
        if p["height"] - bottom > _TOL:
            pieces.append((left, right, bottom, p["height"]))
    return tx, ty, pieces, holes


def _fmt(values) -> str:
    return " ".join(format(_finite(value, "exported geometry"), ".17g") for value in values)


def _box(parent, name: str, center, dimensions, yaw: float, rgba: str):
    if any(value <= 0 or not math.isfinite(value) for value in dimensions):
        raise ValueError(f"{name}: invalid exported full box dimensions")
    ET.SubElement(parent, "geom", name=name, type="box", pos=_fmt(center),
                  size=_fmt([value / 2 for value in dimensions]),
                  quat=_fmt([math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]),
                  rgba=rgba, contype="1", conaffinity="1", friction="1 0.005 0.0001")


def export_mjcf(doc: dict, output_dir: Path, fishbot_project: Path, robot: dict | None = None) -> dict:
    """Export fixed conservative geometry; robot is opt-in and never actuated."""
    clean = _validated_doc(doc)
    walls = [e for e in clean["entities"] if e["kind"] == "wall"]
    if not walls:
        raise ValueError("collision scene export requires at least one wall for floor context")
    geometry = {}
    for wall in walls:
        number = int(wall["id"].split("_")[1])
        openings = [e for e in clean["entities"] if e["kind"] in ("door", "window") and e["params"]["wall_id"] == number]
        geometry[wall["id"]] = _wall_geometry(wall, openings)
    robot_record = None
    if robot is not None:
        if not isinstance(robot, dict) or not set(robot) <= {"position_x", "position_y", "position_z", "angle_z"}:
            raise ValueError("robot accepts position_x, position_y, position_z, angle_z only")
        model_path = Path(fishbot_project).resolve() / _ROBOT_MODEL
        if not model_path.is_file():
            raise ValueError(f"FishBot base MJCF is missing: {_ROBOT_MODEL}")
        model_bytes = model_path.read_bytes()
        try:
            root = ET.fromstring(model_bytes)
        except ET.ParseError as exc:
            raise ValueError("FishBot base MJCF is not valid XML") from exc
        if root.tag != "mujoco" or root.find("worldbody") is None:
            raise ValueError("FishBot base MJCF lacks mujoco/worldbody")
        if root.findall(".//include") or root.find("asset") is not None:
            raise ValueError("FishBot base model now requires external assets; explicit asset integration is needed")
        body = root.find("worldbody/body[@name='base_footprint']")
        if body is None:
            raise ValueError("FishBot base_footprint body is missing")
        floor_z = min(e["params"]["az"] for e in walls)
        position = [_finite(robot.get("position_x", 0.), "robot.position_x"),
                    _finite(robot.get("position_y", 0.), "robot.position_y"),
                    _finite(robot.get("position_z", floor_z + 0.002), "robot.position_z")]
        yaw = _finite(robot.get("angle_z", 0.), "robot.angle_z")
        body.set("pos", _fmt(position))
        body.set("quat", _fmt([math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]))
        body.attrib.pop("euler", None)
        robot_record = {"base_model_path": str(_ROBOT_MODEL), "base_model_sha256": _sha(model_bytes),
                        "position": position, "angle_z": yaw,
                        "initial_pose_checked_for_collision": False}
    else:
        root = ET.Element("mujoco", model="spatiallm_offline_scene")
        ET.SubElement(root, "compiler", angle="radian")
        ET.SubElement(root, "option", timestep="0.002", gravity="0 0 -9.81", integrator="implicitfast")
        ET.SubElement(root, "worldbody")
    root.set("model", "spatiallm_offline_scene")
    world = root.find("worldbody")
    floor_z = min(e["params"]["az"] for e in walls)
    bounds = [(e["params"][key], e["params"][other]) for e in walls for key, other in (("ax", "ay"), ("bx", "by"))]
    for entity in clean["entities"]:
        if entity["kind"] == "bbox":
            p = entity["params"]
            radius = math.hypot(p["scale_x"], p["scale_y"]) / 2
            bounds.extend([(p["position_x"] - radius, p["position_y"] - radius),
                           (p["position_x"] + radius, p["position_y"] + radius)])
    min_x, max_x = min(x for x, _ in bounds) - 1, max(x for x, _ in bounds) + 1
    min_y, max_y = min(y for _, y in bounds) - 1, max(y for _, y in bounds) + 1
    ET.SubElement(world, "geom", name="spatiallm_floor", type="plane",
                  pos=_fmt([(min_x + max_x) / 2, (min_y + max_y) / 2, floor_z]),
                  size=_fmt([(max_x - min_x) / 2, (max_y - min_y) / 2, 0.1]),
                  rgba="0.82 0.83 0.85 1", friction="1 0.005 0.0001")
    ET.SubElement(world, "light", name="spatiallm_light", pos=_fmt([(min_x + max_x) / 2, (min_y + max_y) / 2, floor_z + 8]), dir="0 0 -1")
    segment_count, window_count, doors = 0, 0, []
    for wall in walls:
        p = wall["params"]
        tx, ty, pieces, holes = geometry[wall["id"]]
        yaw = math.atan2(ty, tx)
        for i, (left, right, low, high) in enumerate(pieces):
            u = (left + right) / 2
            _box(world, f"spatiallm_{wall['id']}_segment_{i}",
                 [p["ax"] + tx * u, p["ay"] + ty * u, p["az"] + (low + high) / 2],
                 [right - left, p["thickness"], high - low], yaw, "0.70 0.73 0.77 1")
            segment_count += 1
        for (left, right, low, high), opening in holes:
            if opening["kind"] == "window":
                u = (left + right) / 2
                _box(world, f"spatiallm_{opening['id']}_collision_panel",
                     [p["ax"] + tx * u, p["ay"] + ty * u, p["az"] + (low + high) / 2],
                     [right - left, p["thickness"], high - low], yaw, "0.3 0.55 0.75 0.65")
                window_count += 1
            else:
                doors.append({"id": opening["id"], "wall_id": opening["params"]["wall_id"],
                              "wall_local_bounds": [left, right, low, high], "collision_fill": False})
    for entity in clean["entities"]:
        if entity["kind"] == "bbox":
            p = entity["params"]
            _box(world, f"spatiallm_{entity['id']}",
                 [p["position_x"], p["position_y"], p["position_z"]],
                 [p["scale_x"], p["scale_y"], p["scale_z"]], p["angle_z"], "0.76 0.52 0.29 1")
    ET.indent(root)
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    layout_bytes = (json.dumps(clean, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    output_dir = Path(output_dir).resolve()
    if output_dir.exists() and (not output_dir.is_dir() or any((output_dir / name).exists() for name in ("scene.xml", "layout.json", "manifest.json"))):
        raise ValueError("output already exists; choose a fresh export directory")
    manifest = {"schema_version": 1, "coordinate_system": clean["coordinate_system"], "units": "m",
                "source": clean["source"], "corrections": clean["corrections"], "warnings": clean["warnings"],
                "mjcf_path": str(output_dir / "scene.xml"), "layout_path": str(output_dir / "layout.json"),
                "manifest_path": str(output_dir / "manifest.json"),
                "files": ["scene.xml", "layout.json", "manifest.json"],
                "generated_xml_sha256": _sha(xml),
                "outputs": {"scene.xml": {"sha256": _sha(xml), "bytes": len(xml)},
                            "layout.json": {"sha256": _sha(layout_bytes), "bytes": len(layout_bytes)}},
                "entity_counts": {kind: sum(e["kind"] == kind for e in clean["entities"]) for kind in _FIELDS},
                "wall_segments": segment_count, "window_collision_panels": window_count,
                "door_openings": doors, "robot": robot_record,
                "floor": {"z": floor_z, "derivation": "minimum wall baseline z; flat infinite collision plane"},
                "approximations": ["Object bboxes are fixed solid conservative boxes, not exact furniture geometry.",
                                   "Doors are empty wall apertures; no door leaf or hinge is inferred.",
                                   "Windows are cut visually and filled with full-thickness conservative collision panels.",
                                   "Floor is a flat infinite plane inferred from wall baseline elevations.",
                                   "Initial robot pose, room accessibility and navigation safety are not inferred."]}
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    output_dir.mkdir(parents=True, exist_ok=True)
    # Exclusive creation makes an accidental concurrent export fail visibly.
    for name, data in (("scene.xml", xml), ("layout.json", layout_bytes), ("manifest.json", manifest_bytes)):
        with (output_dir / name).open("xb") as handle:
            handle.write(data)
    return manifest
