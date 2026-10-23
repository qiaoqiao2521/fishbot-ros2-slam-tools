#!/usr/bin/env python3
"""Package existing F1 dependencies for a private Kaggle dataset."""
import argparse
import ast
import json
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_MAGIC = b"FISHBOT-TAR-GZIP-1\n"


def preserve_archive(path):
    """Keep Kaggle's dataset ingestion from unpacking runtime permissions/links."""
    destination = path.with_name(path.name+".bin")
    with path.open("rb") as source, destination.open("wb") as target:
        target.write(ARCHIVE_MAGIC)
        shutil.copyfileobj(source, target)
    path.unlink()
    return destination


def local_modules(folder):
    pending = ["grasp_episode", "collision_scene", "joint_planner", "placement"]
    found = {}
    while pending:
        name = pending.pop()
        source = folder/(name+".py")
        if name in found or not source.is_file():
            continue
        found[name] = source
        for node in ast.walk(ast.parse(source.read_text())):
            imports = ([item.name for item in node.names] if isinstance(node, ast.Import)
                       else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            pending.extend(value.split(".")[0] for value in imports)
    return found


def system_packages():
    libraries = set()
    prefix = Path("/opt/ros/jazzy")
    for folder in ("nav2_planner", "nav2_controller", "nav2_bt_navigator", "nav2_behaviors",
                   "nav2_velocity_smoother", "nav2_map_server", "nav2_amcl", "opennav_docking",
                   "robot_localization", "robot_state_publisher"):
        directory = prefix/"lib"/folder
        if not directory.is_dir():
            continue
        for file in directory.iterdir():
            if not file.is_file() or file.read_bytes()[:4] != b"\x7fELF":
                continue
            result = subprocess.run(["ldd", str(file)], text=True, capture_output=True)
            for name in re.findall(r"(?:=>\s+|^\s*)(/[^\s]+)", result.stdout, re.M):
                path = Path(name).resolve()
                if str(path).startswith("/usr/"):
                    libraries.add(path)
    packages = set()
    unresolved = []
    for library in sorted(libraries):
        query = subprocess.run(["dpkg-query", "-S", str(library)], text=True, capture_output=True)
        if query.returncode:
            unresolved.append(str(library))
        else:
            packages.add(query.stdout.split(": ", 1)[0].split(":", 1)[0])
    return sorted(packages), unresolved


def pack(output, so101):
    output.mkdir(parents=True, exist_ok=False)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    subprocess.run(["git", "archive", "--format=tar.gz", "-o", str(output/"fishbot-source.tar.gz"),
                    commit, "tools", "fishbot.sh", "workspaces/fishbot_mujoco_ws/src"],
                   cwd=ROOT, check=True)
    with tarfile.open(output/"ros-jazzy.tar.gz", "w:gz", compresslevel=1) as archive:
        archive.add("/opt/ros/jazzy", arcname="opt/ros/jazzy")
    runtime = ROOT/"workspaces/fishbot_mujoco_ws/.runtime"
    with tarfile.open(output/"fishbot-runtime.tar.gz", "w:gz", compresslevel=1,
                      dereference=True) as archive:
        archive.add(runtime, arcname="workspaces/fishbot_mujoco_ws/.runtime")
    modules = local_modules(so101/"experiments/colab-twin")
    with tarfile.open(output/"so101-source.tar.gz", "w:gz", compresslevel=1) as archive:
        for source in sorted(modules.values()):
            archive.add(source, arcname=str(source.relative_to(so101)))
        for name in ("requirements.txt",):
            source = so101/"experiments/colab-twin"/name
            archive.add(source, arcname=str(source.relative_to(so101)))
        archive.add(so101/"workspaces/so101_ws/src/so101_mujoco/models",
                    arcname="workspaces/so101_ws/src/so101_mujoco/models")
        for name in ("LICENSE", "LICENSE.md", "LICENSE.txt"):
            if (so101/name).is_file():
                archive.add(so101/name, arcname=name)
    packages, unresolved = system_packages()
    versions = subprocess.run(["dpkg-query", "-W", "-f=${Package}\t${Version}\n", "ros-jazzy-*"],
                              text=True, capture_output=True)
    (output/"ros-package-versions.txt").write_text(versions.stdout)
    for archive in output.glob("*.tar.gz"):
        preserve_archive(archive)
    manifest = {"kind": "private_f1_runtime_bundle", "fishbot_commit": commit,
                "archive_encoding": "fishbot-prefixed-tar-gzip-v1",
                "so101_modules": sorted(modules), "system_packages": packages,
                "unresolved_system_libraries": unresolved,
                "so101_working_sources_copied": True,
                "historical_cache_included": False, "credentials_included": False,
                "task_acceptance": False}
    (output/"bundle.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print(json.dumps({**manifest, "archive_bytes": {
        path.name: path.stat().st_size for path in output.glob("*.tar.gz.bin")}}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--so101-project", required=True, type=Path)
    args = parser.parse_args()
    pack(args.output.resolve(), args.so101_project.resolve())
