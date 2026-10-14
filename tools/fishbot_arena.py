#!/usr/bin/env python3
"""Identity-checked entry points for unmodified IsaacLab-Arena runners."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "experiments/arena/upstream.lock.json"
CONFIG = ROOT / "experiments/arena/evaluation.yaml"
EVALUATION_CONFIG_SHA256 = "0ceaf7b67224153bebafbfe2d9b6bd24d35e76e22e5b6d492d4a35a078a86414"
DEFAULT_SOURCE = Path.home() / ".cache/fishbot/arena/IsaacLab-Arena-0.3.1"
HTTPS = ["-c", "url.https://github.com/.insteadOf=git@github.com:",
         "-c", "url.https://github.com/.insteadOf=ssh://git@github.com/"]
EULA_KEYS = ("OMNI_KIT_ACCEPT_EULA", "ACCEPT_EULA")


def read_lock():
    return json.loads(LOCK.read_text())


def query(command, cwd=None):
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=15)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def source_status(source, lock):
    """Read actual Git identities; an uninitialized submodule is not verified."""
    source = Path(source).resolve()
    errors = []
    top = query(["git", "rev-parse", "--show-toplevel"], source) if source.is_dir() else None
    if top is None or Path(top).resolve() != source:
        return {"path": str(source), "verified": False, "errors": ["not an independent Git checkout"]}
    head = query(["git", "rev-parse", "HEAD"], source)
    if head != lock["commit"]:
        errors.append("Arena HEAD differs from locked commit")
    dirty = query(["git", "status", "--porcelain=v1", "--untracked-files=all"], source)
    if dirty is None or dirty:
        errors.append("Arena working tree is changed or unreadable")
    hashes = {}
    for name, expected in lock["source_sha256"].items():
        path = source / name
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        except OSError:
            actual = None
        hashes[name] = actual
        if actual != expected:
            errors.append(f"source hash differs: {name}")
    submodules = {}
    for name, expected in lock["submodules"].items():
        tree = query(["git", "ls-tree", "HEAD", "--", name], source)
        gitlink = tree.split()[2] if tree and tree.startswith("160000 commit ") else None
        path = source / name
        child_top = query(["git", "rev-parse", "--show-toplevel"], path) if path.is_dir() else None
        independent = child_top is not None and Path(child_top).resolve() == path.resolve()
        actual = query(["git", "rev-parse", "HEAD"], path) if independent else None
        child_dirty = query(["git", "status", "--porcelain=v1", "--untracked-files=all"], path) if independent else None
        submodules[name] = {"expected": expected, "gitlink": gitlink, "head": actual,
                           "clean": child_dirty == ""}
        if gitlink != expected or actual != expected or child_dirty != "":
            errors.append(f"submodule is missing, changed or differs: {name}")
    recursive = query(["git", "submodule", "status", "--recursive"], source)
    if recursive is None or any(line[0] in "-+U" for line in recursive.splitlines() if line):
        errors.append("recursive submodule identities are incomplete or changed")
    return {"path": str(source), "head": head, "source_sha256": hashes,
            "submodules": submodules, "verified": not errors, "errors": errors}


def hardware_status(source, lock, gpu_index=0):
    """Query NVML through nvidia-smi, without importing CUDA, Kit or Torch."""
    raw = query(["nvidia-smi", "--query-gpu=index,name,memory.total,driver_version,uuid",
                 "--format=csv,noheader,nounits"])
    gpus = []
    try:
        for row in csv.reader(raw.splitlines() if raw else []):
            index, name, memory, driver, identity = (value.strip() for value in row)
            gpus.append({"index": int(index), "name": name,
                         "vram_mib": int(memory), "driver": driver, "uuid": identity})
    except (ValueError, TypeError):
        gpus = []
    selected = next((gpu for gpu in gpus if gpu["index"] == gpu_index), None)
    cloud_t4 = selected is not None and selected['name'] in ('T4', 'Tesla T4', 'NVIDIA T4')
    minimum_memory = 15360 if cloud_t4 else lock['minimum_vram_mib']
    profile = 'official GCP T4 (nominal 16 GB)' if cloud_t4 else 'desktop conservative precheck'
    os_supported = platform.system() == "Linux" and platform.machine() == "x86_64"
    reasons = []
    if not os_supported:
        reasons.append("requires Linux x86_64")
    if selected is None or not selected["uuid"].startswith("GPU-"):
        reasons.append("selected NVIDIA GPU identity or memory is unknown")
    elif any(name in selected['name'].upper() for name in ('A100', 'H100')):
        reasons.append('selected GPU lacks required RT cores according to official Isaac Sim requirements')
    elif selected["vram_mib"] < minimum_memory:
        reasons.append(f"selected GPU has {selected['vram_mib']} MiB; selected precheck requires {minimum_memory} MiB")
    try:
        ram = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                       if line.startswith("MemTotal:"))) * 1024
    except (OSError, ValueError, StopIteration):
        ram = None
    existing = Path(source).resolve()
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    try:
        disk = shutil.disk_usage(existing).free
    except OSError:
        disk = None
    return {"platform": f"{platform.system()}-{platform.machine()}", "gpus": gpus,
            "selected_gpu": selected, "minimum_vram_mib": lock["minimum_vram_mib"],
            "ram_bytes": ram, "disk_free_bytes": disk, "precheck_passed": not reasons,
            "hardware_profile": profile, "selected_minimum_vram_mib": minimum_memory,
            "cloud_gpu_source": "https://docs.isaacsim.omniverse.nvidia.com/6.1.0/installation/install_advanced_cloud_setup_gcp.html",
            "errors": reasons, "official_compatibility": "unknown; requires official checker and actual rollout",
            "official_requirements": {"ram": "32 GB", "ssd": "50 GB", "linux_driver": "595.58.03",
                                      "minimum_gpu": "RTX 4080", "url": lock["requirements_url"]}}


def dependency_status(source, lock):
    venv = Path(source) / ".venv"
    versions = {}
    for path in venv.glob("lib/python*/site-packages/*.dist-info/METADATA"):
        name = version = None
        for line in path.read_text(errors="replace").splitlines():
            if line.startswith("Name: "):
                name = line[6:].lower().replace("_", "-")
            elif line.startswith("Version: "):
                version = line[9:]
            if name and version:
                versions[name] = version
                break
    cfg = venv / "pyvenv.cfg"
    python_version = None
    if cfg.is_file():
        fields = dict(line.split('=', 1) for line in cfg.read_text().splitlines() if '=' in line)
        fields = {key.strip(): value.strip() for key, value in fields.items()}
        python_version = fields.get('version_info', fields.get('version'))
        if fields.get('version') and fields.get('version_info') and fields['version'] != fields['version_info']:
            python_version = None
    required = ("isaaclab-arena", "isaaclab", "isaacsim", "torch")
    try:
        packages = tomllib.loads((Path(source) / "uv.lock").read_text()).get("package", [])
        expected = {item["name"].replace("_", "-"): item["version"] for item in packages
                    if item.get("name", "").replace("_", "-") in required}
    except (OSError, ValueError, KeyError):
        expected = {}
    installed = ((venv / "bin/python").is_file()
                 and python_version is not None and python_version.startswith(lock["python"] + ".")
                 and all(name in expected and versions.get(name) == expected[name] for name in required)
                 and versions.get("isaacsim") == lock["isaac_sim"])
    return {"uv": shutil.which("uv"), "git_lfs": query(["git", "lfs", "version"]),
            "python": python_version, "installed": installed,
            "required_versions": {name: versions.get(name) for name in required}, "expected_versions": expected,
            "runtime_imports_verified": False}


def doctor(source, lock, gpu_index=0):
    state = {"source": source_status(source, lock), "hardware": hardware_status(source, lock, gpu_index),
             "dependencies": dependency_status(source, lock), "runtime_verified": False, "ready": False}
    state["preflight_passed"] = (state["source"]["verified"] and state["hardware"]["precheck_passed"]
                                 and state["dependencies"]["installed"])
    return state


def runtime_environment(accept_eula):
    env = os.environ.copy()
    # Native runners are standalone processes. Isaac Sim otherwise inherits
    # notebook shutdown behavior from Colab's parent kernel (v6.1.0).
    for key in ("JPY_PARENT_PID", "ISAAC_JUPYTER_KERNEL", "ISAAC_JUPYTER_PYTHON_PACKAGE"):
        env.pop(key, None)
    env.pop("ISAACLAB_ARENA_FORCE_EXIT_ON_COMPLETE", None)
    for key in EULA_KEYS:
        env.pop(key, None)
    if accept_eula:
        env.update(OMNI_KIT_ACCEPT_EULA="YES", ACCEPT_EULA="Y")
    return env


def run_checked(command, source, *, accept_eula=False, skip_lfs=False, gpu_identity=None):
    env = runtime_environment(accept_eula)
    if gpu_identity is not None:
        # Pin the checked physical GPU even when the caller has a masking environment.
        env["CUDA_VISIBLE_DEVICES"] = gpu_identity
    if skip_lfs:
        env["GIT_LFS_SKIP_SMUDGE"] = "1"
    # Keep native logs visible; reserve stdout for the entry-point JSON receipt.
    subprocess.run(command, cwd=source, env=env, check=True, stdout=sys.stderr)


def prepare(source, lock):
    source = Path(source).resolve()
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run_checked(["git", *HTTPS, "clone", "--filter=blob:none", "--no-checkout", lock["repository"], str(source)],
                    source.parent, skip_lfs=True)
        run_checked(["git", *HTTPS, "fetch", "origin", lock["commit"]], source, skip_lfs=True)
        run_checked(["git", "checkout", "--detach", lock["commit"]], source, skip_lfs=True)
    else:
        top = query(["git", "rev-parse", "--show-toplevel"], source) if source.is_dir() else None
        if top is None or Path(top).resolve() != source:
            raise RuntimeError("refusing to replace an existing non-checkout path")
        if query(["git", "rev-parse", "HEAD"], source) != lock["commit"]:
            raise RuntimeError("existing Arena checkout has a different HEAD; choose a new --source")
        if query(["git", "status", "--porcelain=v1", "--untracked-files=all"], source) != "":
            raise RuntimeError("existing Arena checkout is changed; preserving it")
    run_checked(["git", *HTTPS, "submodule", "update", "--init", "--recursive", "--depth", "1"], source, skip_lfs=True)
    state = source_status(source, lock)
    if not state["verified"]:
        raise RuntimeError("prepared source failed identity verification: " + "; ".join(state["errors"]))
    return state


def native_commands(source, output=None, gpu_index=0):
    source = Path(source).resolve()
    python = str(source / ".venv/bin/python")
    return {
        "install": ["uv", "sync", "--locked"],
        "smoke": [python, "isaaclab_arena/evaluation/policy_runner.py", "--viz", "none",
                  "--device", "cuda:0", "--policy_type", "zero_action",
                  "--num_steps", "20", "--num_envs", "1", "cube_goal_pose"],
        "evaluate": [python, "isaaclab_arena/evaluation/experiment_runner.py", "--viz", "none",
                     "--device", "cuda:0", "--experiment_config", str(CONFIG),
                     "--experiment_output_directory", str(Path(output).resolve()) if output else "<NEW_OUTPUT_DIRECTORY>"],
    }


def result_readback(output, *, runner_receipt=None):
    """Match native aggregate and JSONL receipts; never replace task scores.

    This acceptance contract is for the fixed two-Run evaluation.yaml. Its
    1.5-second budget has at most ceil(1.5 / (8 / 120)) = 23 control steps in
    pinned Arena's default manager cfg. Earlier native termination is valid.
    """
    output = Path(output).resolve()
    path = output / "arena_experiment_result.json"
    config_sha = hashlib.sha256(CONFIG.read_bytes()).hexdigest()

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("nonfinite JSON constant: " + value)

    def decode(text):
        return json.loads(text, object_pairs_hook=unique_pairs, parse_constant=invalid_constant)

    def timing_numbers(record, fields):
        import math
        return all(type(record.get(key)) in (int, float) and math.isfinite(record[key])
                   and record[key] >= 0 for key in fields)

    def stamp(value):
        if not isinstance(value, str) or not value:
            raise ValueError("missing native timestamp")
        # Pinned record_core_episode_results uses datetime.now().isoformat().
        # A naive timestamp therefore has the same local zone as this runner.
        return datetime.fromisoformat(value).astimezone(timezone.utc)

    def fresh_file(file):
        if file.is_symlink() or not file.is_file() or not file.resolve().is_relative_to(output):
            raise RuntimeError("native artifact is missing or redirects outside output: " + str(file))
        if not start.timestamp() <= file.stat().st_mtime <= end.timestamp():
            raise RuntimeError("native artifact timestamp is outside this runner interval: " + str(file))

    try:
        if runner_receipt is None:
            runner_receipt = decode((output / "fishbot-runner-receipt.json").read_text())
        if (not isinstance(runner_receipt, dict) or type(runner_receipt.get("returncode")) is not int
                or runner_receipt["returncode"] != 0 or runner_receipt.get("source_unchanged") is not True
                or runner_receipt.get("config_unchanged") is not True
                or runner_receipt.get("config_sha256") != config_sha or config_sha != EVALUATION_CONFIG_SHA256):
            raise ValueError("runner exit/source/config freeze does not bind this evaluation")
        before, after = runner_receipt.get("source_before"), runner_receipt.get("source_after")
        if (not isinstance(before, dict) or not isinstance(after, dict) or before != after
                or before.get("verified") is not True or after.get("verified") is not True):
            raise ValueError("verified source boundary receipts are missing or changed")
        if runner_receipt.get("command") != native_commands(before["path"], output)["evaluate"]:
            raise ValueError("runner command does not bind the native evaluation and output")
        start, end = stamp(runner_receipt.get("started_utc")), stamp(runner_receipt.get("finished_utc"))
        if end <= start:
            raise ValueError("invalid runner interval")
        fresh_file(path)
        runs = decode(path.read_text())["runs"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("native experiment result or runner evidence is missing, invalid or unreadable: " + str(exc)) from exc
    if not isinstance(runs, dict) or set(runs) != {"baseline", "swap_objects"}:
        raise RuntimeError("native result does not contain exactly the configured two Runs")
    successes, episode_records, artifacts, timing_artifacts, all_timings = {}, {}, {}, {}, []
    objects = {"baseline": ("rubiks_cube_hot3d_robolab", "bowl_ycb_robolab"),
               "swap_objects": ("mustard_bottle_hot3d_robolab", "wooden_bowl_hot3d_robolab")}
    for name, run in runs.items():
        if not isinstance(run, dict) or run.get("status") != "completed":
            raise RuntimeError(f"native Run did not complete: {name}")
        expected_environment = {"name": "pick_and_place_maple_table", "definition": "pick_and_place_maple_table"}
        if run.get("environment") != expected_environment or run.get("policy_variant") != "zero_action":
            raise RuntimeError(f"native Run environment/policy does not match the frozen configuration: {name}")
        rebuilds = run.get("rebuilds")
        if (not isinstance(rebuilds, list) or len(rebuilds) != 1 or not isinstance(rebuilds[0], dict)
                or type(rebuilds[0].get("index")) is not int or rebuilds[0]["index"] != 0
                or not isinstance(rebuilds[0].get("episodes"), list) or len(rebuilds[0]["episodes"]) != 1):
            raise RuntimeError(f"native Run must contain exactly rebuild 0 and one episode: {name}")
        ep = rebuilds[0]["episodes"][0]
        instruction = f"Pick up the {objects[name][0]}, and place it into the {objects[name][1]}"
        if (not isinstance(ep, dict) or ep.get("job_name") != name
                or type(ep.get("env_id")) is not int or ep["env_id"] != 0
                or type(ep.get("episode_in_env")) is not int or ep["episode_in_env"] != 0
                or type(ep.get("seed")) is not int or ep["seed"] != 42
                or "success" not in ep or not (ep["success"] is None or type(ep["success"]) is bool)
                or type(ep.get("episode_length")) is not int or not 1 <= ep["episode_length"] <= 23
                or ep.get("language_instruction") != instruction):
            raise RuntimeError(f"native Run episode identity/steps/object instruction does not match: {name}")
        try:
            if not start <= stamp(ep.get("timestamp")) <= end:
                raise ValueError("episode timestamp is outside runner interval")
        except (ValueError, TypeError, OverflowError) as exc:
            raise RuntimeError(f"native Run has invalid episode timestamp: {name}") from exc
        run_output = output / name
        episode_path = run_output / "episode_results_rebuild0.jsonl"
        if run_output.is_symlink() or not run_output.is_dir():
            raise RuntimeError(f"native Run output directory is missing or redirected: {name}")
        found = {file for file in run_output.rglob("episode_results*.jsonl")
                 if file.relative_to(run_output).parts[0] != "report"}
        if found != {episode_path}:
            raise RuntimeError(f"native Run must have exactly its single rebuild JSONL: {name}")
        fresh_file(episode_path)
        try:
            lines = [line for line in episode_path.read_text().splitlines() if line.strip()]
            if (len(lines) != 1 or json.dumps(decode(lines[0]), sort_keys=True, allow_nan=False)
                    != json.dumps(ep, sort_keys=True, allow_nan=False)):
                raise ValueError("aggregate differs from the single native JSONL episode")
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError(f"native Run aggregate/JSONL mismatch: {name}") from exc
        successes[name] = [ep["success"]]
        episode_records[name] = [dict(ep, termination_reason=ep.get("termination_reason"))]
        artifacts[name] = {"path": str(episode_path), "sha256": hashlib.sha256(episode_path.read_bytes()).hexdigest()}
        timings_path = run_output / "arena_experiment_timings.json"
        fresh_file(timings_path)
        try:
            timings = decode(timings_path.read_text())
            if (not isinstance(timings, list) or not timings or any(not isinstance(record, dict)
                    or record.get("type") != "timing" or record.get("app_name") != "experiment_runner"
                    or not isinstance(record.get("name"), str) or not record["name"]
                    or type(record.get("count")) is not int or record["count"] <= 0
                    or not timing_numbers(record, ("mean_ms", "total_ms", "min_ms", "max_ms", "p10_ms", "p50_ms", "p90_ms"))
                    or record["total_ms"] <= 0 for record in timings)
                    or len({record["name"] for record in timings}) != len(timings)):
                raise ValueError("missing, duplicate or invalid native timing records")
            counts = {record["name"]: record["count"] for record in timings}
            if any(counts.get(key) != ep["episode_length"] for key in
                   ("step", "step/env_step", "step/policy_inference")):
                raise ValueError("native step/env_step/policy_inference counts differ from the episode")
            all_timings.extend(dict(record, run_name=name) for record in timings)
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError(f"native Run timing/episode mismatch: {name}") from exc
        timing_artifacts[name] = {"path": str(timings_path), "sha256": hashlib.sha256(timings_path.read_bytes()).hexdigest()}
    combined_path = output / "arena_experiment_timings.json"
    fresh_file(combined_path)
    try:
        combined = decode(combined_path.read_text())
        run_timings = combined.get("runs") if isinstance(combined, dict) else None
        if (not isinstance(run_timings, list) or any(not isinstance(record, dict) for record in run_timings)
                or json.dumps(sorted(run_timings, key=lambda record: (record.get("run_name", ""), record.get("name", ""))),
                              sort_keys=True, allow_nan=False)
                != json.dumps(sorted(all_timings, key=lambda record: (record["run_name"], record["name"])),
                              sort_keys=True, allow_nan=False)):
            raise ValueError("combined timings do not match the two original Run timing files")
        totals = combined.get("totals")
        counts = {}
        for record in all_timings:
            counts[record["name"]] = counts.get(record["name"], 0) + record["count"]
        if (not isinstance(totals, list) or any(not isinstance(record, dict)
                or not isinstance(record.get("name"), str) or type(record.get("count")) is not int
                or not timing_numbers(record, ("mean_ms", "total_ms", "min_ms", "max_ms")) for record in totals)
                or len(totals) != len(counts) or {record["name"]: record["count"] for record in totals} != counts):
            raise ValueError("combined native timing counts do not match the Run counts")
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("native combined timing receipts are incomplete or inconsistent") from exc
    return {"pipeline_completed": True, "policy_success": successes,
            "episodes": episode_records, "native_episode_files": artifacts,
            "native_timing_files": timing_artifacts,
            "native_combined_timings": {"path": str(combined_path), "sha256": hashlib.sha256(combined_path.read_bytes()).hexdigest()},
            "native_result": str(path), "native_result_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "episode_step_limit": 23,
            "limitations": ["Pinned upstream does not record termination_reason; missing reasons remain null.",
                            "Object names are checked in the frozen config and native task instruction, not independent geometry.",
                            "Local source and artifact receipts are observations, not cryptographic attestations."]}


def runtime_gate(source, lock, accept_eula, *, installed, gpu_index=0):
    if not accept_eula:
        raise RuntimeError("explicit --accept-eula is required; inherited environment does not count")
    state = doctor(source, lock, gpu_index)
    if not state["source"]["verified"]:
        raise RuntimeError("source identity is unverified: " + "; ".join(state["source"]["errors"]))
    if not state["hardware"]["precheck_passed"]:
        raise RuntimeError("hardware precheck rejected: " + "; ".join(state["hardware"]["errors"]))
    if installed and not state["dependencies"]["installed"]:
        raise RuntimeError("locked runtime is not installed; use install on a supported target")
    return state


def execute(action, source, lock, *, accept_eula=False, output=None, gpu_index=0):
    source = Path(source).resolve()
    before = runtime_gate(source, lock, accept_eula, installed=action != "install", gpu_index=gpu_index)
    commands = native_commands(source, output, gpu_index)
    if action == "install":
        if not before["dependencies"]["uv"] or not before["dependencies"]["git_lfs"]:
            raise RuntimeError("install requires existing uv and Git LFS executables")
        run_checked(["git", *HTTPS, "lfs", "pull"], source, accept_eula=True)
        run_checked(["git", *HTTPS, "submodule", "foreach", "--recursive", "git lfs pull"], source,
                    accept_eula=True)
        run_checked(commands[action], source, accept_eula=True)
        result = doctor(source, lock, gpu_index)
        if not result["source"]["verified"] or not result["dependencies"]["installed"]:
            raise RuntimeError("uv finished but pinned source or locked package metadata did not verify: "
                               + json.dumps({'source_errors': result['source'].get('errors', []),
                                             'dependencies': result['dependencies']}, ensure_ascii=False))
        return result
    if action == "evaluate":
        if output is None:
            raise RuntimeError("evaluate requires an explicit new --output directory")
        output = Path(output).resolve()
        if output.exists() or output.is_symlink():
            raise RuntimeError("output already exists; previous evidence is preserved")
        if hashlib.sha256(CONFIG.read_bytes()).hexdigest() != EVALUATION_CONFIG_SHA256:
            raise RuntimeError("evaluation configuration differs from the frozen two-Run preset; no native run started")
        output.mkdir(parents=True, exist_ok=False)
    start = datetime.now(timezone.utc).isoformat()
    config_sha = hashlib.sha256(CONFIG.read_bytes()).hexdigest() if action == "evaluate" else None
    returncode = None
    try:
        run_checked(commands[action], source, accept_eula=True,
                    gpu_identity=before["hardware"]["selected_gpu"]["uuid"])
        returncode = 0
    except subprocess.CalledProcessError as exc:
        returncode = exc.returncode
        raise
    finally:
        after = source_status(source, lock)
        receipt = {"command": commands[action], "started_utc": start,
                   "finished_utc": datetime.now(timezone.utc).isoformat(), "returncode": returncode,
                   "source_before": before["source"], "source_after": after,
                   "source_unchanged": before["source"] == after,
                   "task_success": "read native per-episode result; runner exit is not task success"}
        if action == "evaluate":
            receipt.update(pipeline_completed=False, policy_success=None)
            receipt["config_sha256"] = config_sha
            receipt["config_unchanged"] = (CONFIG.is_file()
                                           and hashlib.sha256(CONFIG.read_bytes()).hexdigest() == config_sha)
            (output / "fishbot-runner-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    try:
        if not receipt["source_unchanged"] or not after["verified"]:
            raise RuntimeError("source changed during native execution; evidence is retained")
        if action == "evaluate":
            if not receipt["config_unchanged"]:
                raise RuntimeError("experiment configuration changed during execution; evidence is retained")
            receipt.update(result_readback(output, runner_receipt=receipt))
    except (RuntimeError, OSError, ValueError, TypeError) as exc:
        if action == "evaluate":
            receipt["validation_error"] = str(exc)
        raise
    finally:
        if action == "evaluate":
            (output / "fishbot-runner-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("doctor", "prepare", "install", "smoke", "evaluate", "plan"))
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--gpu", type=int, default=0, help="physical nvidia-smi GPU index")
    parser.add_argument("--accept-eula", action="store_true", help="explicitly accept the linked NVIDIA EULA")
    args = parser.parse_args(argv)
    try:
        lock = read_lock()
        if args.action == "doctor":
            result = doctor(args.source, lock, args.gpu)
        elif args.action == "prepare":
            result = prepare(args.source, lock)
        elif args.action == "plan":
            result = {"executed": False, "cwd": str(args.source.resolve()),
                      "commands": native_commands(args.source, args.output, args.gpu),
                      "runtime_gpu_environment": {"CUDA_VISIBLE_DEVICES": f"GPU UUID resolved for --gpu {args.gpu}"},
                      "requires": ["verified pinned source", "hardware precheck", "explicit --accept-eula"],
                      "eula_url": lock["eula_url"]}
        else:
            result = execute(args.action, args.source, lock, accept_eula=args.accept_eula,
                             output=args.output, gpu_index=args.gpu)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return exc.returncode if isinstance(exc, subprocess.CalledProcessError) and exc.returncode > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
