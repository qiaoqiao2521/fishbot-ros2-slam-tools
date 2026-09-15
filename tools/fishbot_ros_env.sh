#!/usr/bin/env bash
# FishBot ROS 发行版解析助手。
# 解析顺序：FISHBOT_ROS_DISTRO 环境变量 > /opt/ros 下自动探测。
# 同装 humble/jazzy 时必须显式选择，禁止悄悄替换发行版。
# 用法：source 本文件后调用 fishbot_source_ros；成功后导出 FISHBOT_ROS_DISTRO。

fishbot_ros_distro() {
  if [[ -n "${FISHBOT_ROS_DISTRO:-}" ]]; then
    if [[ -f "/opt/ros/${FISHBOT_ROS_DISTRO}/setup.bash" ]]; then
      echo "${FISHBOT_ROS_DISTRO}"
      return 0
    fi
    echo "error: FISHBOT_ROS_DISTRO=${FISHBOT_ROS_DISTRO} but /opt/ros/${FISHBOT_ROS_DISTRO}/setup.bash not found" >&2
    return 1
  fi

  local found=()
  [[ -f /opt/ros/humble/setup.bash ]] && found+=(humble)
  [[ -f /opt/ros/jazzy/setup.bash ]] && found+=(jazzy)

  if (( ${#found[@]} == 1 )); then
    echo "${found[0]}"
    return 0
  elif (( ${#found[@]} == 0 )); then
    echo "error: no ROS 2 distro under /opt/ros (expected humble or jazzy); set FISHBOT_ROS_DISTRO" >&2
  else
    echo "error: both humble and jazzy installed; set FISHBOT_ROS_DISTRO=humble|jazzy explicitly" >&2
  fi
  return 1
}

fishbot_source_ros() {
  local distro
  distro="$(fishbot_ros_distro)" || return 1
  # colcon 生成的 setup.sh 在 set -u 下会因未绑定变量报错；
  # 本函数进入 +u 后不恢复，调用方在全部 overlay 加载完成后再自行 set -u。
  set +u
  # shellcheck disable=SC1090
  source "/opt/ros/${distro}/setup.bash"
  export FISHBOT_ROS_DISTRO="${distro}"
}
