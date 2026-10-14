#!/usr/bin/env python3
"""Read-only native GPU diagnostics; no installation or Isaac/Arena imports."""
import argparse
import csv
import ctypes as C
import ctypes.util
import glob
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


class ApplicationInfo(C.Structure):
    _fields_ = [("sType", C.c_uint32), ("pNext", C.c_void_p), ("pApplicationName", C.c_char_p),
                ("applicationVersion", C.c_uint32), ("pEngineName", C.c_char_p),
                ("engineVersion", C.c_uint32), ("apiVersion", C.c_uint32)]


class InstanceCreateInfo(C.Structure):
    _fields_ = [("sType", C.c_uint32), ("pNext", C.c_void_p), ("flags", C.c_uint32),
                ("pApplicationInfo", C.POINTER(ApplicationInfo)), ("enabledLayerCount", C.c_uint32),
                ("ppEnabledLayerNames", C.POINTER(C.c_char_p)), ("enabledExtensionCount", C.c_uint32),
                ("ppEnabledExtensionNames", C.POINTER(C.c_char_p))]


class PropertiesPrefix(C.Structure):
    # VkPhysicalDeviceProperties prefix, not the complete output allocation.
    _fields_ = [(name, C.c_uint32) for name in
                ("apiVersion", "driverVersion", "vendorID", "deviceID", "deviceType")] + [
                ("deviceName", C.c_char * 256)]


class ExtensionProperties(C.Structure):
    _fields_ = [("extensionName", C.c_char * 256), ("specVersion", C.c_uint32)]


def command(argv, limit=16384):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=8, check=False)
        return {"returncode": result.returncode, "stdout": result.stdout[:limit],
                "stderr": result.stderr[:4096]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"returncode": None, "error": str(exc)}


def library_probe():
    result = command(["ldconfig", "-p"], limit=262144)
    names = ("libvulkan.so", "libGLX_nvidia.so", "libEGL_nvidia.so", "libnvidia-glcore.so")
    private = []
    for folder in os.environ.get("LD_LIBRARY_PATH", "").split(":")[:64]:
        if folder:
            for name in names:
                private.extend(sorted(glob.glob(str(Path(folder) / (name + "*"))))[:64])
    return {"ldconfig_returncode": result["returncode"],
            "private_candidates": private,
            "entries": [line.strip() for line in result.get("stdout", "").splitlines()
                        if any(name in line for name in names)],
            "error": result.get("error") or result.get("stderr") or None}


def vulkan_probe():
    result = {"nvidia_verified": False, "physical_devices": [], "runtime_verified": False}
    instance = C.c_void_p()
    vk = None
    try:
        vk = C.CDLL(ctypes.util.find_library("vulkan") or "libvulkan.so.1")
        bindings = {
            "vkCreateInstance": (C.c_int32, [C.POINTER(InstanceCreateInfo), C.c_void_p, C.POINTER(C.c_void_p)]),
            "vkDestroyInstance": (None, [C.c_void_p, C.c_void_p]),
            "vkEnumeratePhysicalDevices": (C.c_int32, [C.c_void_p, C.POINTER(C.c_uint32), C.POINTER(C.c_void_p)]),
            "vkGetPhysicalDeviceProperties": (None, [C.c_void_p, C.c_void_p]),
            "vkEnumerateDeviceExtensionProperties": (C.c_int32, [C.c_void_p, C.c_char_p,
                                                                 C.POINTER(C.c_uint32), C.POINTER(ExtensionProperties)]),
        }
        for name, (restype, argtypes) in bindings.items():
            function = getattr(vk, name)
            function.restype, function.argtypes = restype, argtypes
        app = ApplicationInfo(sType=0, pApplicationName=b"fishbot-arena-preflight", apiVersion=(1 << 22) | (2 << 12))
        info = InstanceCreateInfo(sType=1, pApplicationInfo=C.pointer(app))
        code = vk.vkCreateInstance(C.byref(info), None, C.byref(instance))
        result["create_instance_result"] = code
        if code != 0:
            result["error"] = "VK_ERROR_INCOMPATIBLE_DRIVER" if code == -9 else f"vkCreateInstance returned {code}"
            return result
        count = C.c_uint32()
        code = vk.vkEnumeratePhysicalDevices(instance, C.byref(count), None)
        if code != 0 or not 0 < count.value <= 64:
            raise RuntimeError(f"physical-device count query failed: result={code}, count={count.value}")
        devices = (C.c_void_p * count.value)()
        code = vk.vkEnumeratePhysicalDevices(instance, C.byref(count), devices)
        if code != 0:
            raise RuntimeError(f"physical-device enumeration incomplete: result={code}")
        required = {"VK_KHR_acceleration_structure", "VK_KHR_ray_tracing_pipeline"}
        for device in devices[:count.value]:
            # Full VkPhysicalDeviceProperties writes <1KiB today. Allocate 4KiB,
            # aligned to uint64, and only interpret its header-verified prefix.
            storage = (C.c_uint64 * 512)()
            vk.vkGetPhysicalDeviceProperties(device, C.byref(storage))
            props = C.cast(C.byref(storage), C.POINTER(PropertiesPrefix)).contents
            name = props.deviceName.decode("utf-8", "replace")
            n = C.c_uint32()
            code = vk.vkEnumerateDeviceExtensionProperties(device, None, C.byref(n), None)
            if code != 0 or n.value > 1024:
                raise RuntimeError(f"extension count query failed: result={code}, count={n.value}")
            extensions = (ExtensionProperties * n.value)()
            code = vk.vkEnumerateDeviceExtensionProperties(device, None, C.byref(n), extensions)
            if code != 0:
                raise RuntimeError(f"extension enumeration incomplete: result={code}")
            supported = {item.extensionName.decode("ascii", "replace") for item in extensions[:n.value]}
            software = props.deviceType == 4 or any(token in name.lower() for token in
                                                    ("llvmpipe", "lavapipe", "swiftshader", "softpipe"))
            verified = props.vendorID == 0x10DE and props.deviceType in (1, 2, 3) and not software
            item = {"name": name, "vendor_id": props.vendorID, "device_id": props.deviceID,
                    "device_type": props.deviceType, "software_device": software,
                    "nvidia_device": verified, "required_rt_extensions": sorted(required & supported),
                    "missing_rt_extensions": sorted(required - supported), "api_version": props.apiVersion}
            result["physical_devices"].append(item)
        result["nvidia_verified"] = any(item["nvidia_device"] and not item["missing_rt_extensions"]
                                        for item in result["physical_devices"])
    except (OSError, AttributeError, RuntimeError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if vk is not None and instance.value:
            vk.vkDestroyInstance(instance, None)
    return result


def collect():
    try:
        os_release = platform.freedesktop_os_release()
    except OSError as exc:
        os_release = {"error": str(exc)}
    gpu = command(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"])
    gpu["devices"] = [dict(zip(("name", "memory_mib", "driver_version"), (part.strip() for part in row)))
                      for row in csv.reader(gpu.get("stdout", "").splitlines()) if len(row) == 3]
    try:
        memory = {key: int(value.split()[0]) * 1024 for key, value in
                  (line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
                  if key in ("MemTotal", "MemAvailable")}
    except (OSError, ValueError) as exc:
        memory = {"error": str(exc)}
    icds = []
    paths = set()
    for pattern in ("/etc/vulkan/icd.d/*.json", "/usr/share/vulkan/icd.d/*.json"):
        paths.update(glob.glob(pattern))
    overrides = {name: os.environ.get(name) for name in ("VK_DRIVER_FILES", "VK_ICD_FILENAMES")}
    for value in overrides.values():
        paths.update(part for part in (value or "").split(":") if part)
    for path in sorted(paths):
        try:
            icds.append({"path": path, "document": json.loads(Path(path).read_text())})
        except (OSError, ValueError) as exc:
            icds.append({"path": path, "error": str(exc)})
    usage = shutil.disk_usage(Path.cwd())
    return {"schema": "fishbot.arena.native-preflight.v1", "observed_at": datetime.now(timezone.utc).isoformat(),
            "system": {"platform": platform.platform(), "machine": platform.machine(),
                       "python": platform.python_version(), "libc": list(platform.libc_ver()),
                       "os_release": os_release},
            "memory_bytes": memory, "disk_bytes": dict(zip(("total", "used", "free"), usage)),
            "nvidia_smi": gpu, "vulkan_icds": icds, "vulkan_driver_overrides": overrides,
            "graphics_libraries": library_probe(),
            "vulkan": vulkan_probe(), "runtime_verified": False,
            "scope": "Native NVIDIA Vulkan/RT preflight only; Isaac Sim and Arena were not started."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New JSON evidence file; existing files are refused.")
    args = parser.parse_args(argv)
    if os.path.lexists(args.output):
        parser.error("output already exists; choose a new evidence file")
    result = collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"output": str(args.output), "nvidia_verified": result["vulkan"]["nvidia_verified"],
                      "runtime_verified": False}, ensure_ascii=False))
    return 0 if result["vulkan"]["nvidia_verified"] else 1


if __name__ == "__main__":
    sys.exit(main())
