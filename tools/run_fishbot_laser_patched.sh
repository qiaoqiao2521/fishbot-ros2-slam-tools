#!/usr/bin/env bash
set -euo pipefail

WORKBENCH_ROOT="$(dirname -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")")"

PATCH_FILE="${WORKBENCH_ROOT}/tools/fishbot_laser_patch/ydlidar_node.py"
IMAGE="registry.cn-hangzhou.aliyuncs.com/fishros/fishbot_laser"

if [[ ! -f "$PATCH_FILE" ]]; then
  echo "patch file not found: $PATCH_FILE" >&2
  exit 1
fi

xhost +

exec docker.exe run -it --rm \
  -p 8889:8889 \
  -p 8889:8889/udp \
  -v /dev:/dev \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  --device /dev/snd \
  -e DISPLAY="unix${DISPLAY}" \
  -v "${PATCH_FILE}:/workspace/install/ydlidar/lib/python3.10/site-packages/ydlidar/ydlidar_node.py:ro" \
  "$IMAGE"
