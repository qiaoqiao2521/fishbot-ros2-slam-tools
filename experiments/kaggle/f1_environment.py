#!/usr/bin/env python3
"""Read-only Kaggle runtime probe. It does not accept a robotics task."""
from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen


def command(args):
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=10)
        return {"returncode": result.returncode, "stdout": result.stdout[:2000],
                "stderr": result.stderr[:1000]}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"error": str(error)}


def inspect_runtime():
    report = {"kind": "fishbot_kaggle_environment", "task_acceptance": False,
              "navigation_goals": 0, "task_requests": 0,
              "python": sys.version, "platform": platform.platform(),
              "libc": platform.libc_ver(), "uid": os.getuid(),
              "cpu_affinity_count": len(os.sched_getaffinity(0)),
              "kaggle_runtime_observed": Path("/kaggle/working").is_dir(),
              "commands": {name: shutil.which(name) for name in
                           ("apt-get", "sudo", "docker", "proot", "ros2", "git", "cmake")}}
    for path in ("/etc/os-release", "/sys/fs/cgroup/cpu.max", "/proc/pressure/cpu"):
        file = Path(path)
        try:
            report[path] = file.read_text()[:3000] if file.is_file() else None
        except OSError as error:
            report[path] = {"error": str(error)}
    memory = Path("/proc/meminfo")
    report["memory"] = [line for line in memory.read_text().splitlines()
                        if line.startswith(("MemTotal:", "MemAvailable:", "SwapFree:"))]
    report['cpu_models'] = sorted({line.split(':',1)[1].strip()
        for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')})
    report['gpu'] = command(['nvidia-smi','--query-gpu=name,memory.total','--format=csv,noheader'])
    report["disk_free_bytes"] = shutil.disk_usage(Path.cwd()).free
    report["system_python"] = command(["/usr/bin/python3", "--version"])
    report["ros_prefix_exists"] = Path("/opt/ros/jazzy").is_dir()
    report["python_packages"] = {}
    for package in ("mujoco", "numpy", "scipy", "ompl", "rclpy"):
        try:
            report["python_packages"][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            report["python_packages"][package] = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(("127.0.0.1", 0))
            receiver.settimeout(2)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
                started = time.monotonic()
                sender.sendto(b"fishbot-environment", receiver.getsockname())
                payload, _ = receiver.recvfrom(128)
                report["loopback_udp"] = {"received": payload == b"fishbot-environment",
                                          "elapsed_s": time.monotonic()-started}
    except OSError as error:
        report["loopback_udp"] = {"received": False, "error": str(error)}
    report["network"] = {}
    for url in ("https://raw.githubusercontent.com/ros/rosdistro/master/ros.key",
                "https://packages.ros.org/ros2/ubuntu/dists/noble/Release"):
        try:
            with urlopen(url, timeout=10) as response:
                report["network"][url] = {"status": response.status,
                                           "sample_bytes": len(response.read(128))}
        except Exception as error:
            report["network"][url] = {"error": str(error)}
    return report


if __name__ == "__main__":
    destination = Path("/kaggle/working") if Path("/kaggle/working").is_dir() else Path.cwd()
    result = inspect_runtime()
    output = destination/"fishbot-env.json"
    output.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, indent=2), flush=True)
