"""Compose the existing SO101 contact workcell and FishBot in one world.

SO101 sources remain read-only. Only fixture geometry changes here; source
collision hulls, contact pads, target mass, torque limits and wheel inertia
remain those of the two existing models.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from cooperation_profiles import normalize_scene_profile, vehicle_element, vehicle_profile

ARM_JOINT_NAMES = ("shoulder_pan", "shoulder_lift", "elbow_flex",
                   "wrist_flex", "wrist_roll", "gripper")
TRAY_OFFSET = (.04, -.06, .067)
DEFAULT_STATION = (-2., -2., .16)
DEFAULT_DOCK = (-1.80, -1.80, 0.)


def source_modules(project: Path):
    """Import the existing arm implementation, rather than copy its algorithms."""
    folder = Path(project).resolve() / "experiments/colab-twin"
    if not (folder / "grasp_episode.py").is_file():
        raise FileNotFoundError(f"SO101 contact implementation missing: {folder}")
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        modules = {name: importlib.import_module(name) for name in
                   ("grasp_episode", "collision_scene", "joint_planner", "placement")}
    finally:
        sys.dont_write_bytecode = previous
    for name, module in modules.items():
        if Path(module.__file__).resolve().parent != folder:
            raise RuntimeError(f"{name} was imported from a different SO101 checkout")
    return modules


def _numbers(values):
    return " ".join(format(float(value), ".12g") for value in values)


def _fixture_workcell(root):
    world = root.find("worldbody")
    for child in list(world):
        name = child.get("name", "")
        if (name in ("worktable", "table_edge", "studio_floor") or
                name.startswith("leg_") or name.startswith("place_")):
            world.remove(child)
    # Separate supports leave the delivery side empty for the mobile base.
    fixtures = (("worktable", (0, 0, -.023), (.05, .05, .023)),
                ("pick_bench", (.24, -.13, -.023), (.075, .075, .023)),
                ("bench_bridge", (.12, -.09, -.023), (.075, .035, .023)))
    for name, pos, size in fixtures:
        ET.SubElement(world, "geom", name=name, type="box", pos=_numbers(pos),
                      size=_numbers(size), group="3", contype="1",
                      conaffinity="3", rgba=".72 .75 .77 1")
    return root


def _translate_world(world, offset):
    for child in world:
        if child.tag in ("body", "geom", "light", "camera", "site"):
            position = [float(value) for value in child.get("pos", "0 0 0").split()]
            child.set("pos", _numbers(a + b for a, b in zip(position, offset)))


def _fishbot_element(path, spawn, spawn_yaw=0., scene_profile=None):
    root, car, vehicle = vehicle_element(path, spawn, spawn_yaw, scene_profile)
    if vehicle['id'] == 'fishbot':
        car.find(".//body[@name='laser_link']").set("pos", "-.065 0 .075")
    # Bind the car's original global geom defaults explicitly. The SO101
    # global default must not change its wheel/floor friction or solver terms.
    for geom in car.iter("geom"):
        for key, value in root.find("default/geom").attrib.items():
            if key not in geom.attrib:
                geom.set(key, value)
        geom.set("conaffinity", "3" if geom.get("contype", "1") != "0" else "0")
        geom.set("group", "0")
    tray = ET.SubElement(car.find("body[@name='base_link']"), "body",
                         name="cargo_tray", pos=_numbers(vehicle['tray_offset_m']))
    if vehicle['tray_mount'] is not None:
        mount = vehicle['tray_mount']
        ET.SubElement(tray, 'geom', name='tray_mount', type='box',
            size=_numbers([x/2 for x in mount['size_m']]), pos=_numbers(mount['position_in_tray_m']),
            mass=str(mount['mass_kg']), contype='1', conaffinity='3', group='0', rgba='.5 .55 .6 1')
    ET.SubElement(tray, "geom", name="place_floor", type="box", pos="0 0 .001",
                  size=".06 .06 .001", contype="1", conaffinity="3", group="0",
                  rgba=".20 .39 .58 1", friction="1 .005 .0001")
    for axis in ("x", "y"):
        for side in (-1, 1):
            pos = (side * .059, 0, .009) if axis == "x" else (0, side * .059, .009)
            size = (.001, .06, .009) if axis == "x" else (.06, .001, .009)
            ET.SubElement(tray, "geom", name=f"place_wall_{axis}_{side}", type="box",
                          pos=_numbers(pos), size=_numbers(size), contype="1",
                          conaffinity="3", group="0", rgba=".20 .39 .58 1",
                          friction="1 .005 .0001")
    return root, car


def _append_arena(root, arena_path):
    arena = ET.parse(arena_path).getroot()
    for asset in arena.find("asset"):
        root.find("asset").append(copy.deepcopy(asset))
    for child in arena.find("worldbody"):
        if child.tag == "body":
            continue  # Existing moving-obstacle fixture is a separate task.
        duplicate = copy.deepcopy(child)
        if duplicate.tag == "geom":
            duplicate.set("contype", "1")
            duplicate.set("conaffinity", "3")
            duplicate.set("group", "0")
        root.find("worldbody").append(duplicate)


def frozen_car_geoms(common_model, car_pose, station):
    """Return car obstacles in the arm frame using independent query data."""
    import mujoco
    import numpy as np

    pose = np.asarray(car_pose, dtype=float)
    if pose.shape not in ((3,), (7,)) or not np.isfinite(pose).all():
        raise ValueError("Car pose must be finite (x,y,yaw) or free-joint xyz/wxyz")
    query = mujoco.MjData(common_model)
    joint = common_model.joint("base_free_joint")
    if pose.shape == (3,):
        x, y, yaw = pose
        free = [x, y, .002, math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]
    else:
        if not np.isclose(np.linalg.norm(pose[3:]), 1., atol=1e-4):
            raise ValueError("Car free-joint quaternion must be normalized")
        free = pose
    query.qpos[joint.qposadr[0]:joint.qposadr[0] + 7] = free
    mujoco.mj_forward(common_model, query)
    car_id = common_model.body("base_footprint").id
    car_bodies = {car_id}
    for body in range(car_id + 1, common_model.nbody):
        if int(common_model.body_parentid[body]) in car_bodies:
            car_bodies.add(body)
    kinds = {int(mujoco.mjtGeom.mjGEOM_BOX): ("box", 3),
             int(mujoco.mjtGeom.mjGEOM_CYLINDER): ("cylinder", 2),
             int(mujoco.mjtGeom.mjGEOM_CAPSULE): ("capsule", 2),
             int(mujoco.mjtGeom.mjGEOM_SPHERE): ("sphere", 1)}
    geoms = []
    for index in range(common_model.ngeom):
        if int(common_model.geom_bodyid[index]) not in car_bodies or not common_model.geom_contype[index]:
            continue
        kind, count = kinds[int(common_model.geom_type[index])]
        quat = np.empty(4)
        mujoco.mju_mat2Quat(quat, query.geom_xmat[index])
        geoms.append(ET.Element("geom", name=common_model.geom(index).name,
                               type=kind, pos=_numbers(query.geom_xpos[index] - station),
                               quat=_numbers(quat), size=_numbers(common_model.geom_size[index, :count]),
                               contype=str(common_model.geom_contype[index]),
                               conaffinity=str(common_model.geom_conaffinity[index]), group="3",
                               friction=_numbers(common_model.geom_friction[index]),
                               solref=_numbers(common_model.geom_solref[index]),
                               solimp=_numbers(common_model.geom_solimp[index]),
                               rgba=_numbers(common_model.geom_rgba[index])))
    return geoms


def car_footprint(common_model, radius=.13, vehicle=None):
    """Enclose the existing circular outline and every compiled tray box corner."""
    import mujoco
    import numpy as np
    from scipy.spatial import ConvexHull

    query = mujoco.MjData(common_model)
    mujoco.mj_forward(common_model, query)
    base = common_model.body('base_footprint').id
    base_rotation = query.xmat[base].reshape(3, 3)
    angles = np.arange(32)*2*np.pi/32
    original = radius*np.column_stack((np.cos(angles), np.sin(angles)))
    # An inscribed polygon would shave the original circle between vertices.
    # Its tangent envelope retains the complete original radius without
    # relying on costmap padding to compensate for an undersized footprint.
    outer_angles = angles+np.pi/32
    tangent = radius/np.cos(np.pi/32)*np.column_stack((np.cos(outer_angles), np.sin(outer_angles)))
    if vehicle and vehicle['id'] != 'fishbot':
        original = np.asarray(vehicle['footprint_xy'])
        tangent = original.copy()
    tray_corners = []
    tray_names = ['place_floor', *[f'place_wall_{axis}_{side}' for axis in ('x', 'y') for side in (-1, 1)]]
    signs = np.array([[x,y,z] for x in (-1,1) for y in (-1,1) for z in (-1,1)])
    for name in tray_names:
        geom = common_model.geom(name).id
        if common_model.geom_type[geom] != mujoco.mjtGeom.mjGEOM_BOX:
            raise RuntimeError(f'Tray footprint requires compiled box geometry: {name}')
        world = (signs*common_model.geom_size[geom]) @ query.geom_xmat[geom].reshape(3,3).T + query.geom_xpos[geom]
        local = (world-query.xpos[base]) @ base_rotation
        tray_corners.extend(local[:, :2].tolist())
    points = np.vstack((original,tangent,np.asarray(tray_corners)))
    hull = ConvexHull(points)
    return {'car_footprint_xy':points[hull.vertices].tolist(),
            'car_footprint_frame':'base_footprint', 'car_footprint_original_radius_m':radius,
            'car_footprint_source_points_xy':points.tolist(),
            'car_footprint_tray_corners_xy':tray_corners,
            'car_footprint_tray_geometry_names':tray_names,
            'car_footprint_method':('convex_hull_of_source_vehicle_envelope_and_compiled_tray_corners'
                                    if vehicle and vehicle['id'] != 'fishbot' else
                                    'convex_hull_of_circle_tangent_envelope_and_compiled_tray_corners')}


def build_scene(so101_project: Path, fishbot_project: Path, output: Path,
                spawn=(0., -2.), station=DEFAULT_STATION, spawn_yaw=0., camera=False, camera_light_scale=1.,
                tag_lateral_offset=.03, scene_profile=None, omit_unused_native_rangefinders=False,
                continuous_delivery=None, arena_xml=None):
    import numpy as np

    so101_project, fishbot_project, output = map(lambda path: Path(path).resolve(),
                                                (so101_project, fishbot_project, output))
    spawn, station = np.asarray(spawn, dtype=float), np.asarray(station, dtype=float)
    scene_profile = normalize_scene_profile(scene_profile)
    vehicle = vehicle_profile(scene_profile)
    if (spawn.shape != (2,) or station.shape != (3,) or
            not np.isfinite(np.r_[spawn, station, spawn_yaw]).all()):
        raise ValueError("Spawn xy and station xyz must be finite")
    station = station.copy()
    station[2] += vehicle['station_height_delta_m']
    output.mkdir(parents=True, exist_ok=True)
    modules = source_modules(so101_project)
    import mujoco

    source = so101_project / "workspaces/so101_ws/src/so101_mujoco/models/so101.xml"
    fish_xml = fishbot_project / "workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/mjcf/fishbot.xml"
    arena_xml = (Path(arena_xml).resolve() if arena_xml is not None
                 else fish_xml.parent / "arena.xml")
    _, _, generated = modules["grasp_episode"].build_contact_scene(
        source, output / "source-contact", jaw_force_cap_nm=.15, noslip_iterations=10)
    local_root = _fixture_workcell(ET.parse(generated).getroot())
    for geom in local_root.find("worldbody").iter("geom"):
        if geom.get("contype", "0") != "0" or geom.get("class") == "collision":
            if geom.get("name") not in modules["grasp_episode"].PAD_NAMES:
                geom.set("group", "3")
    common_root = copy.deepcopy(local_root)
    common_root.set("model", "fishbot_so101_contact_cooperation")
    # Planning group 3 hides hulls in ordinary rendering. Restore display
    # groups for fixture surfaces and the payload in the executing world.
    for geom in common_root.find("worldbody").iter("geom"):
        if geom.get("class") != "collision" and geom.get("contype", "0") != "0":
            geom.set("group", "0")
    _translate_world(common_root.find("worldbody"), station)
    fish_root, car = _fishbot_element(fish_xml, spawn, spawn_yaw, scene_profile)
    if fish_root.find('asset') is not None:
        for element in fish_root.find('asset'):
            common_root.find('asset').append(copy.deepcopy(element))
    common_root.find("worldbody").append(car)
    for element in fish_root.find("actuator"):
        common_root.find("actuator").append(copy.deepcopy(element))
    sensors = copy.deepcopy(fish_root.find("sensor"))
    omitted = []
    if omit_unused_native_rangefinders:
        # Cooperation.scan() and NativeCloudQuery produce the used rays. This
        # replicated legacy sensor has no consumer here; preserve all IMUs.
        for sensor in list(sensors):
            if (sensor.tag == 'rangefinder' and sensor.get('name') == 'laser'
                    and sensor.get('site') == 'laser_ray'):
                omitted.append(dict(sensor.attrib))
                sensors.remove(sensor)
    common_root.append(sensors)
    _append_arena(common_root, arena_xml)
    dock = tuple(float(station[i]+vehicle['dock_offset_m'][i] if i < 2 else vehicle['dock_offset_m'][2]) for i in range(3))
    station_camera = None
    if camera:
        from cooperation_camera import add_camera_fixture
        station_camera = add_camera_fixture(common_root, car, dock, output, camera_light_scale, tag_lateral_offset)
    midpoint = (spawn + station[:2]) / 2
    lookat = np.r_[midpoint, station[2] + .05]
    camera_pos = lookat + np.array([0., -2.8, 2.25])
    forward = (lookat - camera_pos) / np.linalg.norm(lookat - camera_pos)
    x_axis = np.cross(forward, [0., 0., 1.])
    x_axis /= np.linalg.norm(x_axis)
    y_axis = np.cross(x_axis, forward)
    ET.SubElement(common_root.find("worldbody"), "camera", name="cooperation_overview",
                  pos=_numbers(camera_pos), xyaxes=_numbers(np.r_[x_axis, y_axis]))
    world_path = output / "world.xml"
    ET.ElementTree(common_root).write(world_path, encoding="utf-8", xml_declaration=True)
    model = mujoco.MjModel.from_xml_path(str(world_path))
    if station_camera is not None:
        from cooperation_camera import camera_mount
        station_camera.update(camera_mount(model, station_camera))
    wheel_names = vehicle['left_wheel_joints']+vehicle['right_wheel_joints']
    wheel_count = len(wheel_names)
    passive_names = vehicle.get('passive_joints', [])
    if (model.nq, model.nv, model.nu) != (20+wheel_count+len(passive_names), 18+wheel_count+len(passive_names), 6+wheel_count):
        raise RuntimeError(f"Unexpected arm/target/car layout: {model.nq}/{model.nv}/{model.nu}")
    expected = (*ARM_JOINT_NAMES, "target_free", "base_free_joint", *wheel_names)
    actual = tuple(model.joint(index).name for index in range(model.njnt))
    if (actual[:8] != expected[:8] or set(actual[8:]) != set(wheel_names+passive_names)
            or (not passive_names and actual != expected)):
        raise RuntimeError("Common scene must preserve arm, target, car joint order")
    arena = ET.parse(arena_xml).getroot()
    for child in arena.find("worldbody").findall("geom"):
        duplicate = copy.deepcopy(child)
        position = [float(value) for value in duplicate.get("pos", "0 0 0").split()]
        duplicate.set("pos", _numbers(a - b for a, b in zip(position, station)))
        duplicate.set("group", "3")
        duplicate.set("contype", "1")
        duplicate.set("conaffinity", "3")
        # Arena materials belong to the common display scene; planning only
        # needs their contact geometry and original color.
        duplicate.attrib.pop("material", None)
        local_root.find("worldbody").append(duplicate)
    for geom in frozen_car_geoms(model, dock, station):
        local_root.find("worldbody").append(geom)
    contact_path = output / "arm-contact.xml"
    ET.ElementTree(local_root).write(contact_path, encoding="utf-8", xml_declaration=True)
    rig_root = copy.deepcopy(local_root)
    world = rig_root.find("worldbody")
    world.remove(world.find("body[@name='grasp_target']"))
    rig_path = output / "rig.xml"
    ET.ElementTree(rig_root).write(rig_path, encoding="utf-8", xml_declaration=True)
    rig = mujoco.MjModel.from_xml_path(str(rig_path))
    contact = mujoco.MjModel.from_xml_path(str(contact_path))
    if rig.nq != 6 or contact.nq != 13:
        raise RuntimeError("Planning models must retain the source SO101 layouts")
    home = np.r_[modules["grasp_episode"].solve_pinch_ik(rig, np.array([.24, .14, .06])), .5]
    checker = modules["collision_scene"].CollisionChecker(rig, gripper=.5, margin_m=.001)
    if not checker.evaluate(home)["valid"]:
        raise RuntimeError(f"Common-scene arm home is obstructed: {checker.evaluate(home)}")
    source_files = [source, fish_xml, arena_xml, *[Path(module.__file__) for module in modules.values()],
                    so101_project / "experiments/colab-twin/grasp_workcell.py"]
    source_files.extend(Path(path) for path in vehicle['source_files'] if Path(path) not in source_files)
    if station_camera is not None:
        source_files.append(Path(station_camera['tag_texture_file']))
    initial = mujoco.MjData(model)
    mujoco.mj_forward(model, initial)
    floor = model.geom('place_floor').id
    initial_tray_top = initial.geom_xpos[floor] + initial.geom_xmat[floor].reshape(3,3) @ np.array([0.,0.,model.geom_size[floor,2]])
    manifest = {"schema": "fishbot-so101-contact-cooperation-v1",
                "world_xml": str(world_path), "rig_xml": str(rig_path),
                "arm_contact_xml": str(contact_path), "so101_project": str(so101_project),
                "fishbot_project": str(fishbot_project), "station_offset": station.tolist(),
                "scene_profile": scene_profile, "vehicle_profile": vehicle,
                "sensor_compute": {"omit_unused_native_rangefinders": bool(omit_unused_native_rangefinders),
                                   "omitted_declarations": omitted,
                                   "scan_producer": "Physics.scan/mj_multiRay",
                                   "cloud_producer": "cooperation_lidar.NativeCloudQuery/mj_multiRay",
                                   "native_imu_preserved": True},
                "station_height_m": float(station[2]),
                "display_cameras": {"overview": "cooperation_overview", "arm_detail": "overview"},
                "spawn": spawn.tolist(), "dock_pose": list(dock),
                "arena_xml": str(arena_xml),
                "tray_offset": list(vehicle['tray_offset_m']),
                "initial_tray_floor_top_world_m": float(initial_tray_top[2]),
                "arm_home_qpos6": home.tolist(), "initial_arm_q6": home.tolist(),
                "arm_joint_names": list(ARM_JOINT_NAMES),
                "actuator_names": [model.actuator(i).name for i in range(model.nu)],
                "joints": [model.joint(i).name for i in range(model.njnt)],
                "layout": {"arm_qpos": [0, 6], "target_qpos": [6, 13],
                           "car_qpos": [13, 20], "wheel_qpos": [20, model.nq],
                           "arm_qvel": [0, 6], "target_qvel": [6, 12],
                           "car_qvel": [12, 18], "wheel_qvel": [18, model.nv]},
                "actuated_wheel_qpos_indices": [int(model.jnt_qposadr[model.joint(name).id]) for name in wheel_names],
                "passive_joint_names": passive_names,
                "nq": model.nq, "nv": model.nv, "nu": model.nu,
                "source_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files},
                "arm_collision_exclusions": checker.excluded_pairs,
                "contact_assumptions": {"jaw_force_cap_nm": .15, "noslip_iterations": 10,
                                        "free_target_mass_kg": .01, "timestep_s": .002}}
    manifest.update(car_footprint(model, radius=vehicle['planning_radius_m'], vehicle=vehicle))
    if spawn_yaw:
        manifest['spawn_yaw'] = float(spawn_yaw)
    if station_camera is not None:
        manifest['station_camera'] = station_camera
    if continuous_delivery is not None:
        from cooperation_business_scene import compose_business_world
        manifest = compose_business_world(manifest, continuous_delivery, output)
    (output / "scene-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--so101-project", type=Path, required=True)
    parser.add_argument("--fishbot-project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(build_scene(arguments.so101_project, arguments.fishbot_project,
                                 arguments.output), indent=2))


if __name__ == "__main__":
    main()
