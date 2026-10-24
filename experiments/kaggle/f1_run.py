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
NATIVE_BUILD_SHELL = """source /opt/ros/jazzy/setup.bash
_f1_native="$1"; _f1_python="$2"; _f1_colcon="$3"; shift 3
_f1_paths=()
for _f1_package in "$@"; do
  _f1_paths+=("$_f1_native/src/navigation2/$_f1_package")
done
"$_f1_python" "$_f1_colcon" --log-base "$_f1_native/log" build \\
  --base-paths "${_f1_paths[@]}" --build-base "$_f1_native/build" \\
  --install-base "$_f1_native/install" --packages-select "$@" \\
  --allow-overriding "$@" --parallel-workers 1 --cmake-args \\
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DPython3_EXECUTABLE="$_f1_python"
"""


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
            print("WARNING:", name, "failed; retaining log and continuing independent checks", flush=True)
    finally:
        save({"kind": "f1_kaggle_deployment", "task_acceptance": False, "steps": STEPS})
    return row


def prepare_scene(fishbot, so101, python, data, runtime_env):
    scene = ARTIFACTS/"scene"
    explicit_factory = os.environ.get("FISHBOT_F1_FACTORY_CONFIG")
    source = Path(explicit_factory) if explicit_factory else Path(
        "tools/config/factory_delivery/line-side-occupied.json")
    factory = json.loads((source if source.is_absolute() else fishbot/source).read_text())
    if not explicit_factory:
        for destination in factory["destinations"]:
            if destination["id"] == "line_b":
                destination["approach_poses"] = [{"x": 1.35, "y": -2., "yaw": 0.}]
    factory_file = ARTIFACTS/"factory.json"
    factory_file.write_text(json.dumps(factory, indent=2)+"\n")
    options = (["--omit-unused-native-rangefinders"]
               if os.environ.get("FISHBOT_OMIT_UNUSED_NATIVE_RANGEFINDERS") == "1" else [])
    if os.environ.get("FISHBOT_STAGING_REVERSING") == "1":
        options.append("--staging-reversing")
    run("scene-prepare", ["bash", "-ec", "source /opt/ros/jazzy/setup.bash; exec \"$@\"",
        "f1-prepare", str(fishbot/"tools/fishbot_cooperation.sh"), "prepare",
        "--so101-project", str(so101), "--scene-profile",
        str(fishbot/"tools/config/cooperation_profiles/jackal_j100-lidar3d-transport.json"),
        "--factory-config", str(factory_file), "--navigation-planner", "smac-lattice",
        "--lattice-allow-reversing", "--lattice-rotation-shim", "--amcl-motion-model", "omni",
        "--output", str(scene), *options], env=runtime_env, timeout=180)
    candidate = data/"f1_candidate.py"
    controller_options = []
    if os.environ.get("FISHBOT_TRANSPORT_CONTROLLER") == "graceful":
        candidate = fishbot/"experiments/kaggle/f1_candidate.py"
        controller_options = ["--transport-controller-yaml",
                              str(fishbot/"experiments/kaggle/graceful-j100.yaml")]
    if os.environ.get("FISHBOT_LATTICE_SMOOTH_PATH") == "1":
        candidate = fishbot/"experiments/kaggle/f1_candidate.py"
        controller_options.append("--lattice-smooth-path")
    global_padding = os.environ.get("FISHBOT_GLOBAL_EXTRA_PADDING_M")
    if global_padding is not None:
        candidate = fishbot/"experiments/kaggle/f1_candidate.py"
        controller_options.extend(["--global-extra-padding-m", global_padding])
    run("candidate-configuration", [python, str(candidate),
                                     str(scene/"scene-manifest.json"), *controller_options], env=runtime_env)
    if os.environ.get("FISHBOT_TERMINAL_STOP_HEARTBEAT") == "1":
        path=scene/"scene-manifest.json"
        manifest=json.loads(path.read_text());manifest['terminal_stop_heartbeat']=True
        path.write_text(json.dumps(manifest,indent=2)+"\n")
    return scene


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
    overlays = globals().get("FISHBOT_SOURCE_OVERLAYS", {})
    for relative, content in overlays.items():
        target = fishbot/relative
        target.write_text(content)
    if overlays:
        (ARTIFACTS/"source-overlay.json").write_text(json.dumps({
            "base_commit": bundle.get("fishbot_commit"),
            "files": list(overlays), "basis": "explicit Kaggle code-version source overlay"}, indent=2)+"\n")
        for relative in overlays:
            target = ARTIFACTS/"source-overlay"/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(overlays[relative])
    apt_env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    run("ubuntu-index", ["apt-get", "update"], env=apt_env, required=False)
    packages = sorted(set(bundle["system_packages"]+[
        "python3.12", "python3.12-dev", "python3.12-venv",
        "build-essential", "cmake", "pkg-config", "libeigen3-dev", "libboost-dev",
        "libboost-filesystem-dev", "libboost-program-options-dev", "libyaml-cpp-dev",
        "libtinyxml2-dev", "libompl-dev", "libassimp5", "libglib2.0-0t64", "libgl1", "libegl1",
        "liborocos-kdl-dev", "liblttng-ust-dev", "libyaml-dev", "nlohmann-json3-dev",
        "libatomic1", "libconsole-bridge-dev", "libssl-dev", "libboost-atomic-dev",
        "libboost-serialization-dev", "libboost-system-dev"]))
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
        "colcon-common-extensions==0.3.0", "colcon-override-check==0.0.1",
        "catkin-pkg==1.1.1", "empy==3.3.4", "lark==1.1.9"],
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
    native_packages = ["nav2_smac_planner", "nav2_velocity_smoother"]
    yaw_stop = os.environ.get("FISHBOT_TRANSPORT_CONTROLLER") == "graceful"
    if yaw_stop:
        run("rotation-yaw-stop-patch", ["git", "apply",
            str(fishbot/"tools/patches/nav2-1.3.13-rotation-yaw-stop.patch")], cwd=source)
        run("rotation-position-namespace-patch", ["git", "apply",
            str(fishbot/"tools/patches/nav2-1.3.13-rotation-position-namespace.patch")], cwd=source)
        run("graceful-path-distance-patch", ["git", "apply",
            str(fishbot/"tools/patches/nav2-1.3.13-graceful-path-distance.patch")], cwd=source)
        transport_packages = ["nav2_rotation_shim_controller", "nav2_graceful_controller"]
        native_packages.extend(transport_packages)
    runtime_env = dict(os.environ, CMAKE_BUILD_PARALLEL_LEVEL="2", OMP_NUM_THREADS="2",
                       OPENBLAS_NUM_THREADS="1", FISHBOT_COOP_PYTHON=python,
                       FISHBOT_MUJOCO_DOMAIN_ID="141", FISHBOT_NAV2_QUERY_OVERLAY=str(native/"install"),
                       PATH="/usr/bin:/bin:"+os.environ.get("PATH", ""),
                       PYTHONPATH=":".join(map(str, (fishbot/"tools",
                           planning/"lib/python3.12/site-packages", Path("/usr/lib/python3/dist-packages")))))
    if os.environ.get("FISHBOT_KAGGLE_SCOPE") == "compute":
        scene = prepare_scene(fishbot, so101, python, data, runtime_env)
        worker = WORK/"f1_compute.py"
        source_text = globals().get("COMPUTE_WORKER_SOURCE")
        worker.write_text(source_text if source_text is not None else
                          Path(__file__).with_name("f1_compute.py").read_text())
        fixtures = ARTIFACTS/"compute-fixtures.json"
        fixtures.write_text(json.dumps(globals().get("COMPUTE_FIXTURES", []), indent=2)+"\n")
        run("compute-profile", ["bash", "-ec", 'source tools/fishbot_mujoco_env.sh; exec "$@"',
            "f1-compute", python, "-B", str(worker), str(scene/"scene-manifest.json"),
            str(fixtures), str(ARTIFACTS/"compute")], cwd=fishbot, env=runtime_env, timeout=180)
        save({"kind": "f1_kaggle_compute", "task_acceptance": False, "navigation_goals": 0,
              "steps": STEPS, "benchmark": json.loads((ARTIFACTS/"compute/result.json").read_text())})
        return
    archives=(list(Path('/kaggle/input').rglob('native-install.tar.gz'))
              if os.environ.get('FISHBOT_REUSE_NATIVE_INSTALL') == '1' else [])
    if len(archives)==1:
        with tarfile.open(archives[0],'r:gz') as archive:archive.extractall(native,filter='data')
        STEPS.append({'stage':'native-overlay-reused','input':str(archives[0]),
                      'origin':globals().get('NATIVE_INSTALL_ORIGIN','explicit private kernel output'),
                      'basis':'same Nav2 1.3.13 and unchanged project native patches; native checks still required'})
        if yaw_stop:
            # An older cache can retain the planner/smoother. Build the newly
            # selected controllers instead of treating cached declarations as proof.
            run("native-transport-build", ["bash", "-ec", NATIVE_BUILD_SHELL,
                "f1-build", str(native), python, str(planning/"bin/colcon"),
                *transport_packages], env=runtime_env, timeout=900)
    else:
        if os.environ.get('FISHBOT_REUSE_NATIVE_INSTALL') == '1':
            print('WARNING: no unique native artifact; building the selected sources',flush=True)
        run("nav2-build", ["bash", "-ec", NATIVE_BUILD_SHELL, "f1-build", str(native),
            python, str(planning/"bin/colcon"), *native_packages],
            env=runtime_env, timeout=900)
    with tarfile.open(ARTIFACTS/"native-install.tar.gz", "w:gz") as archive:
        archive.add(native/"install", arcname="install")
    scene = prepare_scene(fishbot, so101, python, data, runtime_env)
    setup = 'source tools/fishbot_mujoco_env.sh; source "$FISHBOT_NAV2_QUERY_OVERLAY/local_setup.bash"; exec "$@"'
    if os.environ.get("FISHBOT_OMIT_UNUSED_NATIVE_RANGEFINDERS") == "1":
        capacity = WORK/"f1_capacity.py"
        capacity.write_text(globals().get("CAPACITY_WORKER_SOURCE") or
                            Path(__file__).with_name("f1_capacity.py").read_text())
        run("held-ros-capacity", ["bash", "-ec", setup, "f1-capacity", python, "-B", str(capacity),
            str(scene/"scene-manifest.json"),str(ARTIFACTS/"capacity"),
            'full' if os.environ.get('FISHBOT_FULL_STACK_CAPACITY')=='1' else 'simulator'],
            cwd=fishbot,env=runtime_env,timeout=120)
        capacity_result=json.loads((ARTIFACTS/"capacity/result.json").read_text())
        if not capacity_result['capacity_passed']:
            raise RuntimeError("Held ROS loop has insufficient measured capacity; see capacity/result.json")
    run("native-clock", ["bash", "-ec", setup, "f1-clock", "/usr/bin/python3.12", "-B",
        "tools/tests/verify_nav2_smoothing_clock.py", "--domain", "142", "--output",
        str(ARTIFACTS/"native-clock")], cwd=fishbot, env=runtime_env, timeout=150)
    if os.environ.get('FISHBOT_KAGGLE_SCOPE') == 'terminal_stop':
        (WORK/'f1_compute.py').write_text(globals()['COMPUTE_WORKER_SOURCE'])
        worker=WORK/'f1_terminal_stop.py'
        worker.write_text(globals()['TERMINAL_WORKER_SOURCE'])
        fixtures=ARTIFACTS/'terminal-fixture.json'
        fixtures.write_text(json.dumps(globals()['TERMINAL_FIXTURE'],indent=2)+'\n')
        run('terminal-stop-native-physics',['bash','-ec',setup,'terminal-stop',python,'-B',str(worker),
            str(scene/'scene-manifest.json'),str(fixtures),str(ARTIFACTS/'terminal-stop')],
            cwd=fishbot,env=runtime_env,timeout=120,required=False)
        run('full-stack-held-capacity',['bash','-ec',setup,'full-capacity',python,'-B',str(capacity),
            str(scene/'scene-manifest.json'),str(ARTIFACTS/'full-capacity'),'full'],
            cwd=fishbot,env=runtime_env,timeout=120)
        save({'kind':'f1_terminal_stop_diagnostic','task_acceptance':False,'navigation_goals':0,
              'steps':STEPS,'result':json.loads((ARTIFACTS/'terminal-stop/result.json').read_text()),
              'full_capacity':json.loads((ARTIFACTS/'full-capacity/result.json').read_text())})
        return
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
