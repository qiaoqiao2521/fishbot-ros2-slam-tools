"""Offline contract tests; official-source dependency must be provisioned first."""

import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import types
import xml.etree.ElementTree as ET

import pytest


PROJECT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("spatiallm_scene_import_test", PROJECT / "experiments/spatiallm/scene_import.py")
scene = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scene)
SOURCE = Path(os.environ.get("SPATIALLM_SOURCE_DIR", str(Path.home() / ".cache/spatiallm-source-20261014")))
SAMPLE = Path(os.environ.get("SPATIALLM_SAMPLE_LAYOUT", str(Path.home() / ".cache/spatiallm-audit-20261014/sample/layout/scene0000_00.txt")))
WALL = "wall_0=Wall(0,0,0,4,0,0,3,0.2)"
DOOR = "door_0=Door(wall_0,2,0,1,1,2)"
WINDOW = "window_0=Window(wall_0,0.5,0,2.2,1,0.6)"
BBOX = "bbox_0=Bbox(chair,5,2,0.5,1.5707963267948966,2,1,1)"


def load(text=WALL):
    return scene.load_layout(text, SOURCE, {"test_fixture": True})


def export(tmp_path, text=WALL, robot=None):
    return scene.export_mjcf(load(text), tmp_path / "export", PROJECT, robot)


def geoms(manifest):
    return ET.parse(manifest["mjcf_path"]).getroot().findall("worldbody/geom")


def inside_box(geom, point):
    center = [float(v) for v in geom.get("pos").split()]
    size = [float(v) for v in geom.get("size").split()]
    quat = [float(v) for v in geom.get("quat").split()]
    yaw = 2 * math.atan2(quat[3], quat[0])
    dx, dy, dz = (p - c for p, c in zip(point, center))
    local = (math.cos(yaw) * dx + math.sin(yaw) * dy,
             -math.sin(yaw) * dx + math.cos(yaw) * dy, dz)
    return all(abs(v) < bound - 1e-8 for v, bound in zip(local, size))


def test_official_sample_is_preserved_and_zero_thickness_is_explicit(tmp_path):
    assert SAMPLE.is_file(), "provision the pinned official sample before running this test"
    text = SAMPLE.read_text()
    doc = scene.load_layout(text, SOURCE, {"sample_path": str(SAMPLE)})
    assert len(doc["entities"]) == 18
    assert {k: sum(e["kind"] == k for e in doc["entities"]) for k in scene._FIELDS} == {"wall": 6, "door": 2, "window": 1, "bbox": 9}
    assert len([w for w in doc["warnings"] if "zero wall thickness" in w]) == 6
    assert doc["source"]["layout_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    with pytest.raises(ValueError, match="zero thickness"):
        scene.export_mjcf(doc, tmp_path / "bad", PROJECT)
    assert not (tmp_path / "bad").exists()
    corrected = scene.apply_edits(doc, [{"id": f"wall_{i}", "params": {"thickness": 0.12}} for i in range(6)])
    manifest = scene.export_mjcf(corrected, tmp_path / "corrected", PROJECT)
    assert manifest["entity_counts"] == {"wall": 6, "door": 2, "window": 1, "bbox": 9}
    assert manifest["window_collision_panels"] == 1
    assert len(manifest["corrections"]) == 6
    assert len(manifest["door_openings"]) == 2
    assert all(not item["collision_fill"] for item in manifest["door_openings"])


@pytest.mark.parametrize("bad", [
    "wall_0=Wall(0,0,0,4,0,0,0,0.2)",
    "wall_0=Wall(0,0,0,4,0,0,3,-0.2)",
    "wall_0=Wall(0,0,0,0,0,0,3,0.2)",
    "wall_0=Wall(0,0,0,4,0,0,3,nan)",
    "wall_0=Wall(0,0,0,4,0,0,3,1e309)",
    "wall_0=Wall(0,0,0,4,0,0,3,0.2,1)",
    "wall_0=Door(0,0,0,4,0,0,3,0.2)",
    "wall_00=Wall(0,0,0,4,0,0,3,0.2)",
    "wall_0=Wall(0,0,0,4,0,0,3,0.2);print('bad')",
    "unknown_0=Unknown(1)",
    WALL + "\n" + WALL,
    DOOR + "\n" + WALL,
    WALL + "\ndoor_0=Door(wall_1,2,0,1,1,2)",
    WALL + "\nbbox_0=Bbox(chair,1,1,1,0,0,1,1)",
])
def test_invalid_layout_is_rejected_without_silent_loss(bad):
    with pytest.raises(ValueError):
        load(bad)


def test_executable_input_is_never_executed(tmp_path):
    marker = tmp_path / "must-not-exist"
    with pytest.raises(ValueError):
        load(f"__import__('pathlib').Path('{marker}').write_text('executed')")
    assert not marker.exists()


def test_official_parser_silent_loss_is_detected(monkeypatch):
    class LostLayout:
        def __init__(self, text):
            pass

        def get_entities(self):
            return []
    monkeypatch.setattr(scene, "_official_layout_class", lambda source: (LostLayout, scene._OFFICIAL_MODULE_HASHES))
    with pytest.raises(ValueError, match="silently lost"):
        load()


def test_official_import_restores_existing_package_aliases(monkeypatch):
    names = ("spatiallm", "spatiallm.layout", "spatiallm.layout.entity", "spatiallm.layout.layout")
    sentinels = {name: types.ModuleType(name) for name in names}
    for name, module in sentinels.items():
        monkeypatch.setitem(sys.modules, name, module)
    load()
    assert all(sys.modules[name] is module for name, module in sentinels.items())


def test_modified_official_source_is_rejected(tmp_path):
    folder = tmp_path / "source/spatiallm/layout"
    folder.mkdir(parents=True)
    for name in ("layout.py", "entity.py"):
        (folder / name).write_bytes((SOURCE / "spatiallm/layout" / name).read_bytes())
    with (folder / "entity.py").open("a") as handle:
        handle.write("\n# local modification\n")
    with pytest.raises(ValueError, match="pinned source"):
        scene.load_layout(WALL, tmp_path / "source", {})


def test_source_hash_cannot_be_claimed_for_different_input():
    with pytest.raises(ValueError, match="conflicts"):
        scene.load_layout(WALL, SOURCE, {"layout_sha256": "0" * 64})


@pytest.mark.parametrize("metadata", [{"x": float("nan")}, {"x": Path(".")}, {1: "bad"}])
def test_non_json_metadata_is_rejected(metadata):
    with pytest.raises(ValueError, match="metadata|JSON"):
        scene.load_layout(WALL, SOURCE, metadata)


def test_edits_are_immutable_and_record_complete_parameters():
    doc = load()
    original = copy.deepcopy(doc)
    corrected = scene.apply_edits(doc, [{"id": "wall_0", "params": {"thickness": 0.35}}])
    assert doc == original
    assert corrected["entities"][0]["params"]["thickness"] == 0.35
    record = corrected["corrections"][0]
    assert record["before"] == original["entities"][0]["params"]
    assert record["after"] == corrected["entities"][0]["params"]
    unchanged = scene.apply_edits(corrected, [{"id": "wall_0", "params": {"thickness": 0.35}}])
    assert len(unchanged["corrections"]) == 1


@pytest.mark.parametrize("edit", [
    {"id": "wall_9", "params": {"thickness": 0.1}},
    {"id": "wall_0", "params": {"thickness": True}},
    {"id": "wall_0", "params": {"thickness": float("inf")}},
    {"id": "wall_0", "params": {"unknown": 1}},
    {"id": "wall_0", "params": {}},
    {"id": "wall_0", "params": {"height": -1}},
])
def test_invalid_edits_do_not_change_original(edit):
    doc = load()
    original = copy.deepcopy(doc)
    with pytest.raises(ValueError):
        scene.apply_edits(doc, [edit])
    assert doc == original


def test_dangling_wall_edit_is_rejected():
    with pytest.raises(ValueError, match="does not exist"):
        scene.apply_edits(load(WALL + "\n" + DOOR), [{"id": "door_0", "params": {"wall_id": 2}}])


def test_real_thickness_door_aperture_and_conservative_window(tmp_path):
    manifest = export(tmp_path, "\n".join([WALL, DOOR, WINDOW, BBOX]))
    boxes = [g for g in geoms(manifest) if g.get("type") == "box"]
    walls = [g for g in boxes if "wall_0_segment" in g.get("name")]
    assert all(float(g.get("size").split()[1]) == 0.1 for g in walls)
    assert not any(inside_box(g, [2, 0, 1]) for g in boxes)
    assert any(inside_box(g, [1.25, 0, 1]) for g in walls)
    panel = next(g for g in boxes if "window_0_collision_panel" in g.get("name"))
    assert inside_box(panel, [0.5, 0, 2.2])
    assert panel.get("contype") == "1" and panel.get("conaffinity") == "1"
    bbox = next(g for g in boxes if g.get("name") == "spatiallm_bbox_0")
    assert [float(v) for v in bbox.get("size").split()] == [1, 0.5, 0.5]
    assert inside_box(bbox, [5, 2.8, 0.5])
    assert not inside_box(bbox, [5.8, 2, 0.5])


@pytest.mark.parametrize("text, message", [
    (WALL + "\ndoor_0=Door(wall_0,2,0.02,1,1,2)", "off the wall"),
    (WALL + "\ndoor_0=Door(wall_0,0,0,1,1,2)", "bounds"),
    (WALL + "\ndoor_0=Door(wall_0,2,0,3,1,2)", "bounds"),
    (WALL + "\n" + DOOR + "\nwindow_0=Window(wall_0,2,0,1.5,1,1)", "overlaps"),
    ("wall_0=Wall(0,0,0,4,0,0.1,3,0.2)", "non-horizontal"),
])
def test_invalid_opening_geometry_prevents_any_export(tmp_path, text, message):
    with pytest.raises(ValueError, match=message):
        export(tmp_path, text)
    assert not (tmp_path / "export").exists()


def test_rotated_wall_aperture_uses_wall_tangent(tmp_path):
    manifest = export(tmp_path, "wall_0=Wall(1,1,0,1,5,0,3,0.2)\ndoor_0=Door(wall_0,1,3,1,1,2)")
    boxes = [g for g in geoms(manifest) if g.get("type") == "box"]
    assert not any(inside_box(g, [1, 3, 1]) for g in boxes)
    assert any(inside_box(g, [1, 1.5, 1]) for g in boxes)


def test_manifest_hashes_and_json_match_exported_bytes(tmp_path):
    manifest = export(tmp_path)
    for name, evidence in manifest["outputs"].items():
        data = (tmp_path / "export" / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == evidence["sha256"]
        assert len(data) == evidence["bytes"]
    assert json.loads(Path(manifest["manifest_path"]).read_text()) == manifest
    assert set(manifest["files"]) == {"scene.xml", "layout.json", "manifest.json"}
    assert manifest["generated_xml_sha256"] == manifest["outputs"]["scene.xml"]["sha256"]


def test_existing_exports_are_not_overwritten(tmp_path):
    export(tmp_path)
    before = (tmp_path / "export/scene.xml").read_bytes()
    with pytest.raises(ValueError, match="fresh export"):
        export(tmp_path)
    assert (tmp_path / "export/scene.xml").read_bytes() == before


def test_opt_in_fishbot_keeps_joint_and_actuator_contract(tmp_path):
    manifest = export(tmp_path, robot={"position_x": 2, "position_y": 3, "angle_z": 0.4})
    root = ET.parse(manifest["mjcf_path"]).getroot()
    original = ET.parse(PROJECT / scene._ROBOT_MODEL).getroot()
    for section in ("actuator", "sensor"):
        exported = [(node.tag, node.attrib) for node in root.find(section).iter()]
        existing = [(node.tag, node.attrib) for node in original.find(section).iter()]
        assert exported == existing
    body = root.find("worldbody/body[@name='base_footprint']")
    assert [float(v) for v in body.get("pos").split()] == [2, 3, 0.002]
    assert root.find(".//freejoint[@name='base_free_joint']") is not None
    assert manifest["robot"]["initial_pose_checked_for_collision"] is False


@pytest.mark.parametrize("field,value", [("units", "cm"), ("coordinate_system", "left-handed"), ("schema_version", True)])
def test_document_contract_cannot_be_reinterpreted(tmp_path, field, value):
    doc = load()
    doc[field] = value
    with pytest.raises(ValueError):
        scene.export_mjcf(doc, tmp_path / "bad", PROJECT)


@pytest.mark.parametrize("field,value", [("official_source_commit", "wrong"), ("official_layout_module_sha256", "0" * 64)])
def test_document_parser_provenance_is_pinned(tmp_path, field, value):
    doc = load()
    doc["source"][field] = value
    with pytest.raises(ValueError, match="pinned"):
        scene.export_mjcf(doc, tmp_path / "bad", PROJECT)


def test_invalid_unicode_produces_clear_value_error():
    with pytest.raises(ValueError, match="UTF-8"):
        load("\ud800")


def test_corrected_official_sample_serializes_without_mutating_history():
    original = scene.load_layout(SAMPLE.read_text(), SOURCE, {"sample_path": str(SAMPLE)})
    corrected = scene.apply_edits(original, [{"id": f"wall_{i}", "params": {"thickness": 0.12}} for i in range(6)])
    before = copy.deepcopy(corrected)
    text = scene.serialize_layout(corrected, SOURCE)
    roundtrip = scene.load_layout(text, SOURCE, {})
    assert corrected == before
    assert {e["id"]: e for e in roundtrip["entities"]} == {e["id"]: e for e in corrected["entities"]}
    assert len(text.strip().splitlines()) == 18
    assert roundtrip["source"]["layout_sha256"] != original["source"]["layout_sha256"]
    assert all(e["params"]["thickness"] == 0.12 for e in roundtrip["entities"] if e["kind"] == "wall")


def test_official_text_roundtrip_preserves_units_yaw_and_bbox_full_dimensions():
    doc = load("\n".join([WALL, DOOR, WINDOW, BBOX]))
    text = scene.serialize_layout(doc, SOURCE)
    imported = scene.load_layout(text, SOURCE, {})
    assert imported["entities"] == doc["entities"]


@pytest.mark.parametrize("fixture", [DOOR.replace("door_0", "door_1000"), WINDOW.replace("window_0", "window_1000"), BBOX.replace("bbox_0", "bbox_1000")])
def test_official_serializer_id_wrapping_is_rejected_without_mutation(fixture):
    doc = load(WALL + "\n" + fixture)
    before = copy.deepcopy(doc)
    with pytest.raises(ValueError, match="official serialization"):
        scene.serialize_layout(doc, SOURCE)
    assert doc == before
