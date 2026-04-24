#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/muqiao/dev/ros2"
BACKEND_PORT="${BACKEND_PORT:-8080}"
LASER_SOCKET_PORT="${LASER_SOCKET_PORT:-8889}"
ROS_LOG_DIR="${ROS_LOG_DIR:-/tmp/fishbot_ros_logs}"

mkdir -p "$ROS_LOG_DIR"
export ROS_LOG_DIR

failures=0

ok() {
  printf '[OK] %s\n' "$1"
}

warn() {
  printf '[WARN] %s\n' "$1"
}

fail() {
  printf '[FAIL] %s\n' "$1"
  failures=$((failures + 1))
}

print_control_chain_recovery() {
  cat <<'EOF'

Control-chain recovery commands:
1. Inspect micro-ROS agent logs:
   docker.exe logs --tail 160 fishbot_agent

2. Inspect robot topics inside the agent container:
   docker.exe exec -it fishbot_agent bash -lc 'source /opt/ros/humble/setup.bash; ros2 topic list'

3. Check fresh odom and imu:
   docker.exe exec -it fishbot_agent bash -lc 'source /opt/ros/humble/setup.bash; timeout 8 ros2 topic echo /odom --once'
   docker.exe exec -it fishbot_agent bash -lc 'source /opt/ros/humble/setup.bash; timeout 8 ros2 topic echo /imu --once'

4. If /odom is still missing, power-cycle the FishBot main control board or reconnect WiFi, then restart the agent:
   cd /home/muqiao/dev/ros2
   ./tools/fishbot.sh stop
   ./tools/fishbot.sh start
   ./tools/fishbot_stack.sh preflight-slam

Do not run slam-core or arrows until /odom is fresh.
EOF
}

check_windows_firewall() {
  if ! command -v powershell.exe >/dev/null 2>&1; then
    warn "powershell.exe not available; skip Windows firewall rule check"
    return
  fi

  local output
  output="$(powershell.exe -NoProfile -Command \
    "Get-NetFirewallRule -DisplayName 'FishBot*' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty DisplayName" \
    2>/dev/null | tr -d '\r' || true)"

  if grep -Fq "FishBot LiDAR 8889 TCP Any" <<<"$output" &&
     grep -Fq "FishBot LiDAR 8889 UDP Any" <<<"$output" &&
     grep -Fq "FishBot micro-ROS 8888 UDP Any" <<<"$output"; then
    ok "Windows FishBot firewall rules exist"
  else
    warn "Windows FishBot firewall rules are missing or incomplete"
    cat <<'EOF'
Run this in Administrator PowerShell:
New-NetFirewallRule -DisplayName "FishBot micro-ROS 8888 UDP Any" -Direction Inbound -Action Allow -Protocol UDP -LocalPort 8888 -Profile Any
New-NetFirewallRule -DisplayName "FishBot LiDAR 8889 TCP Any" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8889 -Profile Any
New-NetFirewallRule -DisplayName "FishBot LiDAR 8889 UDP Any" -Direction Inbound -Action Allow -Protocol UDP -LocalPort 8889 -Profile Any
New-NetFirewallRule -DisplayName "FishBot rosbridge 9090 TCP Any" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 9090 -Profile Any
New-NetFirewallRule -DisplayName "FishBot laser bridge 9091 TCP Any" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 9091 -Profile Any
EOF
  fi
}

check_agent_container() {
  if ! command -v docker.exe >/dev/null 2>&1; then
    fail "docker.exe not available from WSL"
    return
  fi

  if docker.exe ps --format '{{.Names}}' | grep -Fxq fishbot_agent; then
    ok "fishbot_agent container is running"
  else
    fail "fishbot_agent container is not running"
    printf 'Run: cd %s && ./tools/fishbot.sh start\n' "$ROOT"
    return
  fi

  local ports
  ports="$(docker.exe port fishbot_agent 2>/dev/null || true)"
  grep -Fq "8888/udp -> 0.0.0.0:8888" <<<"$ports" \
    && ok "fishbot_agent exposes UDP 8888" \
    || fail "fishbot_agent does not expose UDP 8888"
  grep -Fq "9090/tcp -> 0.0.0.0:9090" <<<"$ports" \
    && ok "fishbot_agent exposes TCP 9090" \
    || fail "fishbot_agent does not expose TCP 9090"
}

check_lidar_socket() {
  local listen_sockets active_sockets

  if ! listen_sockets="$(ss -ltnup 2>/tmp/fishbot_ss_listen.err)"; then
    warn "cannot inspect listening sockets with ss; skip ${LASER_SOCKET_PORT} listener check"
    sed -n '1,20p' /tmp/fishbot_ss_listen.err || true
    return
  fi

  if grep -q ":${LASER_SOCKET_PORT}" <<<"$listen_sockets"; then
    ok "lidar driver is listening on ${LASER_SOCKET_PORT}"
  else
    fail "lidar driver is not listening on ${LASER_SOCKET_PORT}"
    printf 'Run: cd %s && ./tools/fishbot_stack.sh restart-slam\n' "$ROOT"
  fi

  if ! active_sockets="$(ss -tnp 2>/tmp/fishbot_ss_active.err)"; then
    warn "cannot inspect active TCP sockets with ss; skip radar-board connection check"
    sed -n '1,20p' /tmp/fishbot_ss_active.err || true
    return
  fi

  if grep -q ":${LASER_SOCKET_PORT}" <<<"$active_sockets"; then
    ok "radar board has an active ${LASER_SOCKET_PORT} TCP connection"
  else
    warn "no active radar-board TCP connection on ${LASER_SOCKET_PORT} yet"
  fi
}

check_scan() {
  if timeout 12 "$ROOT/tools/fishbot_laser_scan_probe.sh" >/tmp/fishbot_scan_probe.log 2>&1; then
    ok "/scan is publishing real LaserScan frames"
  else
    fail "/scan probe did not receive frames"
    sed -n '1,80p' /tmp/fishbot_scan_probe.log || true
  fi
}

check_backend_and_odom() {
  local connection
  connection="$(curl -m 2 -fsS "http://127.0.0.1:${BACKEND_PORT}/api/v1/connection" 2>/dev/null || true)"
  if grep -q '"robotOnline":true' <<<"$connection"; then
    ok "backend reports robotOnline=true"
  else
    warn "backend does not report robotOnline=true"
  fi

  if command -v docker.exe >/dev/null 2>&1 &&
     docker.exe exec fishbot_agent bash -lc \
       'source /opt/ros/humble/setup.bash && timeout 8 ros2 topic echo /odom --once' \
       >/tmp/fishbot_odom_probe.log 2>&1; then
    ok "/odom has fresh data"
  else
    fail "/odom probe did not receive fresh data"
    sed -n '1,60p' /tmp/fishbot_odom_probe.log || true
    print_control_chain_recovery
  fi
}

main() {
  printf 'FishBot SLAM preflight\n'
  printf '======================\n'
  check_windows_firewall
  check_agent_container
  check_lidar_socket
  check_scan
  check_backend_and_odom

  if ((failures == 0)); then
    printf '\nREADY: start slow mapping with ./tools/fishbot.sh arrows\n'
    return 0
  fi

  printf '\nNOT READY: fix the FAIL items before moving the robot.\n'
  return 1
}

main "$@"
