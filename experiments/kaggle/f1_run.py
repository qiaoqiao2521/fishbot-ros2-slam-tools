#!/usr/bin/env python3
"""Bounded private Kaggle adapter around the existing F1 factory entrypoint."""
import json
import os
import shutil
import subprocess
import tarfile
import time
import uuid
from pathlib import Path

RUN_TAG = uuid.uuid4().hex[:8]
WORK = Path("/tmp")/("fishbot-f1-"+RUN_TAG)
ARTIFACTS = Path("/kaggle/working")/("f1-results-"+RUN_TAG)
REPORT = Path("/kaggle/working/f1-deployment.json")
STEPS = []
ARCHIVE_MAGIC = b"FISHBOT-TAR-GZIP-1\n"


def save(value):
    value.setdefault("work_directory", str(WORK))
    value.setdefault("artifact_directory", str(ARTIFACTS))
    REPORT.write_text(json.dumps(value, indent=2)+"\n")


def run(name, args, *, cwd=None, timeout=600, env=None, required=True):
    started = time.monotonic()
    log = REPORT.parent/(name+".log")
    row = {"stage": name, "log": log.name, "args": args}
    STEPS.append(row)
    print("Starting", name, flush=True)
    try:
        with log.open("w") as stream:
            result = subprocess.run(args, cwd=cwd, env=env, timeout=timeout,
                                    stdout=stream, stderr=subprocess.STDOUT)
        row.update(returncode=result.returncode, elapsed_wall_s=time.monotonic()-started)
        if result.returncode and required:
            print(log.read_text(errors="replace")[-6000:], flush=True)
            raise RuntimeError(name+" failed; see "+log.name)
        if result.returncode:
            print("WARNING:", name, "failed; retaining log and trying required installation", flush=True)
    finally:
        save({"kind": "f1_kaggle_deployment", "task_acceptance": False, "steps": STEPS})
    return row


def main():
    WORK.mkdir(parents=True, exist_ok=False)
    ARTIFACTS.mkdir(parents=True, exist_ok=False)
    save({"kind": "f1_kaggle_deployment", "task_acceptance": False,
          "status": "checking_inputs", "work_directory": str(WORK), "steps": STEPS})
    inputs = list(Path("/kaggle/input").rglob("bundle.json"))
    if len(inputs) != 1:
        raise RuntimeError("Attach the single private F1 runtime dataset")
    data = inputs[0].parent
    bundle = json.loads(inputs[0].read_text())
    fishbot, so101 = WORK/"fishbot", WORK/"so101"
    fishbot.mkdir(); so101.mkdir()
    for name, destination in (("ros-jazzy.tar.gz", Path("/")),
                              ("fishbot-source.tar.gz", fishbot),
                              ("fishbot-runtime.tar.gz", fishbot),
                              ("so101-source.tar.gz", so101)):
        encoded = bundle.get("archive_encoding") == "fishbot-prefixed-tar-gzip-v1"
        with (data/(name+".bin" if encoded else name)).open("rb") as source:
            if encoded and source.read(len(ARCHIVE_MAGIC)) != ARCHIVE_MAGIC:
                raise ValueError("Invalid runtime archive header: "+name)
            with tarfile.open(fileobj=source, mode="r|gz") as archive:
                archive.extractall(destination, filter="data")
    apt_env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    run("ubuntu-index", ["apt-get", "update"], env=apt_env, required=False)
    packages = sorted(set(bundle["system_packages"]+[
        "python3.12", "python3.12-dev", "python3.12-venv",
        "build-essential", "cmake", "pkg-config", "libeigen3-dev", "libboost-dev",
        "libboost-filesystem-dev", "libboost-program-options-dev", "libyaml-cpp-dev",
        "libtinyxml2-dev", "libompl-dev", "libassimp5", "libglib2.0-0t64", "libgl1", "libegl1"]))
    run("ubuntu-dependencies", ["apt-get", "install", "-y", "--no-install-recommends", *packages],
        env=apt_env, timeout=900)
    version = subprocess.check_output(["/usr/bin/python3", "--version"], text=True).strip()
    # Only the uploaded ROS CLI selects 3.12; Kaggle retains its own interpreter.
    ros_cli = Path("/opt/ros/jazzy/bin/ros2")
    cli_text = ros_cli.read_text()
    ros_cli.write_text("#!/usr/bin/python3.12\n"+cli_text.partition("\n")[2])
    STEPS.append({"stage": "ros-cli-python", "path": str(ros_cli),
                  "interpreter": "/usr/bin/python3.12",
                  "original_shebang": cli_text.splitlines()[0]})
    planning = WORK/"planning-venv"
    planning_env = dict(os.environ)
    planning_env.pop("PYTHONPATH", None)
    run("planning-venv", ["/usr/bin/python3.12", "-m", "venv", "--system-site-packages", str(planning)],
        env=planning_env)
    python = str(planning/"bin/python")
    run("planning-dependencies", [python, "-m", "pip", "install", "--disable-pip-version-check",
        "-r", str(so101/"experiments/colab-twin/requirements.txt"), "PyYAML", "daqp",
        "colcon-common-extensions==0.3.0", "catkin-pkg==1.1.1", "empy==3.3.4", "lark==1.1.9"],
        env=planning_env, timeout=900)
    run("planning-versions", [python, "-m", "pip", "freeze"], env=planning_env)
    native = WORK/"native"
    source = native/"src/navigation2"
    source.parent.mkdir(parents=True)
    run("nav2-source", ["git", "clone", "--depth", "1", "--branch", "1.3.13",
                        "https://github.com/ros-navigation/navigation2.git", str(source)], timeout=180)
    run("lattice-patch", ["git", "apply", "--directory=nav2_smac_planner",
        str(fishbot/"tools/patches/nav2-1.3.13-lattice-edge-cache.patch")], cwd=source)
    run("smoother-patch", ["git", "apply",
        str(fishbot/"tools/patches/nav2-1.3.13-velocity-smoother-ros-time.patch")], cwd=source)
    build = """source /opt/ros/jazzy/setup.bash
"$2" "$3" --log-base "$1/log" build --base-paths "$1/src/navigation2/nav2_smac_planner" "$1/src/navigation2/nav2_velocity_smoother" --build-base "$1/build" --install-base "$1/install" --packages-select nav2_smac_planner nav2_velocity_smoother --allow-overriding nav2_smac_planner nav2_velocity_smoother --parallel-workers 1 --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DPython3_EXECUTABLE="$2"
"""
    runtime_env = dict(os.environ, CMAKE_BUILD_PARALLEL_LEVEL="2", OMP_NUM_THREADS="2",
                       OPENBLAS_NUM_THREADS="1", FISHBOT_COOP_PYTHON=python,
                       FISHBOT_MUJOCO_DOMAIN_ID="141", FISHBOT_NAV2_QUERY_OVERLAY=str(native/"install"),
                       PATH="/usr/bin:/bin:"+os.environ.get("PATH", ""),
                       PYTHONPATH=":".join(map(str, (fishbot/"tools",
                           planning/"lib/python3.12/site-packages", Path("/usr/lib/python3/dist-packages")))))
    run("nav2-build", ["bash", "-ec", build, "f1-build", str(native), python, str(planning/"bin/colcon")],
        env=runtime_env, timeout=900)
    scene = ARTIFACTS/"scene"
    factory = json.loads((fishbot/"tools/config/factory_delivery/line-side-occupied.json").read_text())
    for destination in factory["destinations"]:
        if destination["id"] == "line_b":
            destination["approach_poses"] = [{"x": .95, "y": -2., "yaw": 0.}]
    factory_file = ARTIFACTS/"factory.json"
    factory_file.write_text(json.dumps(factory, indent=2)+"\n")
    run("scene-prepare", ["bash", "-ec", "source /opt/ros/jazzy/setup.bash; exec \"$@\"",
        "f1-prepare", str(fishbot/"tools/fishbot_cooperation.sh"), "prepare",
        "--so101-project", str(so101), "--scene-profile",
        str(fishbot/"tools/config/cooperation_profiles/jackal_j100-lidar3d-transport.json"),
        "--factory-config", str(factory_file), "--navigation-planner", "smac-lattice",
        "--lattice-allow-reversing", "--lattice-rotation-shim", "--amcl-motion-model", "omni",
        "--output", str(scene)], env=runtime_env, timeout=180)
    run("candidate-configuration", [python, str(data/"f1_candidate.py"),
                                     str(scene/"scene-manifest.json")], env=runtime_env)
    setup = 'source tools/fishbot_mujoco_env.sh; source "$FISHBOT_NAV2_QUERY_OVERLAY/local_setup.bash"; exec "$@"'
    run("native-clock", ["bash", "-ec", setup, "f1-clock", "/usr/bin/python3.12", "-B",
        "tools/tests/verify_nav2_smoothing_clock.py", "--domain", "142", "--output",
        str(ARTIFACTS/"native-clock")], cwd=fishbot, env=runtime_env, timeout=150)
    # This is a rebuilt input, not a replay of the deleted loaded-state cache.
    try:
        run("factory-b-a", ["bash", "-ec", setup, "f1-factory", "/usr/bin/python3.12", "-B",
            "tools/cooperation_factory.py", "run", "--manifest", str(scene/"scene-manifest.json"),
            "--planning-python", python, "--output", str(ARTIFACTS/"full-run"), "--candidate",
            "kaggle-j100-rebuilt-terminal", "--publication-mode", "asynchronous",
            "--order", "order-b", "--order", "order-a", "--isolated-runtime"],
            cwd=fishbot, env=runtime_env, timeout=1500)
    finally:
        result_file = ARTIFACTS/"full-run/result.json"
        result = json.loads(result_file.read_text()) if result_file.is_file() else None
        save({"kind": "f1_kaggle_deployment", "bundle": bundle,
              "original_system_python": version, "steps": STEPS,
              "task_acceptance": bool(result and result.get("passed") is True),
              "factory_result": result, "replay_of_deleted_inputs_claimed": False})


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        report = json.loads(REPORT.read_text()) if REPORT.exists() else {"steps": STEPS}
        report["deployment_error"] = type(error).__name__+": "+str(error)
        save(report)
        print(report["deployment_error"], flush=True)
        raise
