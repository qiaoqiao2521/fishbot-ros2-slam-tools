"""Independent MuJoCo load, step, contact probes and optional real rendering."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wall_contacts(model, data, probe_geom: int) -> list[str]:
    result = []
    for contact in data.contact[:data.ncon]:
        pair = [int(contact.geom1), int(contact.geom2)]
        if probe_geom not in pair:
            continue
        other = pair[1] if pair[0] == probe_geom else pair[0]
        name = model.geom(other).name or ""
        if name.startswith("spatiallm_wall_") or name.startswith("spatiallm_window_"):
            result.append(name)
    return sorted(set(result))


def validate_scene(scene: Path, output_dir: Path, steps: int = 20, render: bool = True) -> dict:
    """Use a new model/data only; never connect to ROS or an existing simulator."""
    import mujoco
    import numpy as np

    scene, output_dir = Path(scene).resolve(), Path(output_dir).resolve()
    if not isinstance(steps, int) or isinstance(steps, bool) or not 1 <= steps <= 10000:
        raise ValueError("steps must be an integer between 1 and 10000")
    manifest_path, layout_path = scene.parent / "manifest.json", scene.parent / "layout.json"
    if not manifest_path.is_file() or not layout_path.is_file():
        raise ValueError("scene validation requires manifest.json and layout.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    outputs = manifest.get("outputs", {})
    for name, path in (("scene.xml", scene), ("layout.json", layout_path)):
        expected = outputs.get(name, {}).get("sha256")
        if not expected or _digest(path) != expected:
            raise ValueError(f"{name} SHA256 does not match the export manifest")
    if manifest.get("generated_xml_sha256") != outputs["scene.xml"]["sha256"]:
        raise ValueError("scene SHA256 fields in the export manifest disagree")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    model = mujoco.MjModel.from_xml_path(str(scene))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    initial_time = float(data.time)
    initial_qpos = data.qpos.copy()
    for _ in range(steps):
        mujoco.mj_step(model, data)
    finite = bool(np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all()
                  and np.isfinite(data.sensordata).all())
    if not finite or not math.isclose(float(data.time) - initial_time,
                                     steps * model.opt.timestep, rel_tol=1e-8, abs_tol=1e-9):
        raise RuntimeError("MuJoCo did not advance finite physical state for the requested steps")
    root = ET.parse(scene).getroot()
    world = root.find("worldbody")
    if world is None:
        raise ValueError("scene has no worldbody")
    probe_body = ET.SubElement(world, "body", name="spatiallm_validation_probe", pos="0 0 10")
    ET.SubElement(probe_body, "freejoint", name="spatiallm_validation_probe_joint")
    ET.SubElement(probe_body, "geom", name="spatiallm_validation_probe_geom",
                  type="sphere", size="0.005", mass="0.001", contype="1", conaffinity="1")
    probe_model = mujoco.MjModel.from_xml_string(ET.tostring(root, encoding="unicode"))
    probe_data = mujoco.MjData(probe_model)
    probe_id = probe_model.geom("spatiallm_validation_probe_geom").id
    address = int(probe_model.joint("spatiallm_validation_probe_joint").qposadr[0])

    def contacts(position):
        probe_data.qpos[address:address + 3] = position
        probe_data.qpos[address + 3:address + 7] = [1., 0., 0., 0.]
        mujoco.mj_forward(probe_model, probe_data)
        return _wall_contacts(probe_model, probe_data, probe_id)

    solid_probes = []
    for i in range(model.ngeom):
        name = model.geom(i).name or ""
        if not (name.startswith("spatiallm_wall_") or name.startswith("spatiallm_window_")):
            continue
        hits = contacts(model.geom_pos[i])
        solid_probes.append({"geom": name, "contacts": hits, "passed": name in hits})
    if not solid_probes or not all(p["passed"] for p in solid_probes):
        raise RuntimeError("native collision negative probes did not detect every exported wall/window solid")

    walls = {int(e["id"].split("_")[1]): e["params"] for e in layout["entities"] if e["kind"] == "wall"}
    door_probes = []
    for e in layout["entities"]:
        if e["kind"] != "door":
            continue
        p, wall = e["params"], walls[e["params"]["wall_id"]]
        length = math.hypot(wall["bx"] - wall["ax"], wall["by"] - wall["ay"])
        tx, ty = (wall["bx"] - wall["ax"]) / length, (wall["by"] - wall["ay"]) / length
        for level_name, z in [("center", p["position_z"]),
                              ("lower_aperture", p["position_z"] - p["height"] / 2 + min(.15, p["height"] / 3))]:
            samples = []
            for offset in np.linspace(-wall["thickness"] - .025, wall["thickness"] + .025, 9):
                pos = [p["position_x"] - ty * offset, p["position_y"] + tx * offset, z]
                hits = contacts(pos)
                samples.append({"normal_offset_m": float(offset), "wall_contacts": hits})
            door_probes.append({"door": e["id"], "level": level_name, "samples": samples,
                                "passed": not any(s["wall_contacts"] for s in samples)})
    if not all(p["passed"] for p in door_probes):
        raise RuntimeError("native door-aperture probes encountered wall collisions")

    report = {"schema_version": 1, "validator_sha256": _digest(Path(__file__).resolve()), "mujoco_version": mujoco.__version__, "scene_sha256": _digest(scene),
              "compiled": True, "steps": steps, "elapsed_simulation_s": float(data.time) - initial_time,
              "finite_physical_state": finite, "ngeom": model.ngeom, "nq": model.nq,
              "nv": model.nv, "nu": model.nu, "nsensor": model.nsensor,
              "initial_qpos": initial_qpos.tolist(), "final_qpos": data.qpos.tolist(),
              "solid_collision_probes": solid_probes, "door_aperture_probes": door_probes,
              "limits": ["Contact probes check wall apertures at sampled positions, not whole-robot navigation.",
                         "Semantic object boxes and conservative windows remain approximations.",
                         "No ROS process, production map or physical robot was used."],
              "rendered": False}
    output_dir.mkdir(parents=True, exist_ok=True)
    if render:
        from PIL import Image
        positions = np.asarray([model.geom_pos[i] for i in range(model.ngeom)
                                if (model.geom(i).name or "").startswith("spatiallm_wall_")])
        center = np.mean(positions, axis=0)
        span = float(np.max(np.ptp(positions[:, :2], axis=0)))
        camera = mujoco.MjvCamera()
        camera.lookat[:] = center
        camera.lookat[2] = min(float(center[2]), .7)
        camera.distance = max(span * 2.2, 6.)
        camera.azimuth = 100
        camera.elevation = -65
        options = mujoco.MjvOption()
        options.flags[mujoco.mjtVisFlag.mjVIS_RANGEFINDER] = False
        with mujoco.Renderer(model, height=480, width=640) as renderer:
            renderer.update_scene(data, camera=camera, scene_option=options)
            pixels = renderer.render()
            Image.fromarray(pixels).save(output_dir / "scene.png")
        report.update(rendered=True, render_sha256=_digest(output_dir / "scene.png"),
                      render_path=str(output_dir / "scene.png"))
    (output_dir / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args()
    report = validate_scene(args.scene, args.output_dir, args.steps, not args.no_render)
    print(json.dumps({k: report[k] for k in ("compiled", "steps", "ngeom", "rendered")}, indent=2))


if __name__ == "__main__":
    main()
