# FishBot 启动脚本维护手册

如果你想先判断 FishBot 当前做到哪一步，先看：

- `/home/muqiao/dev/ros2/FISHBOT_STATUS.md`

这份手册只负责“怎么启动”，不负责承担唯一进度入口。

这份手册只做一件事：

- 把 FishBot 现在真正可用的入口命令写清楚
- 把控制桥 `9090`、雷达桥 `9091`、原生 SLAM/RViz 的关系讲清楚
- 避免每次都在一堆命令里重新选

---

## 1. 常用命令

先看这一段就够了。

### 1.1 全栈联调

```bash
cd /home/muqiao/dev/ros2
./tools/fishbot_stack.sh start
```

用途：

- 起本地 micro-ROS agent 和控制 rosbridge
- 起雷达驱动
- 起本地 `rosbridge`
- 起 backend / frontend

这是平时默认入口。

### 1.2 从零开始重新建图

```bash
cd /home/muqiao/dev/ros2
./tools/fishbot_stack.sh restart-slam
```

用途：

- 停掉旧会话
- 重新起本地 micro-ROS agent、控制桥、雷达桥、SLAM
- 自动起原生 `rviz` 窗口

这是现在“重新开始建图”的唯一推荐入口。

建图前先做前置检查：

```bash
cd /home/muqiao/dev/ros2
./tools/fishbot_stack.sh preflight-slam
```

通过后再开低速键盘：

```bash
cd /home/muqiao/dev/ros2
./tools/fishbot.sh arrows
```

默认速度已经按建图调低：

- 前进/后退：`0.05 m/s`
- 原地转向：`0.35 rad/s`
- 松开按键后约 `0.25s` 自动停

如果仍然太快，再手动压低：

```bash
FISHBOT_ARROW_LINEAR=0.03 FISHBOT_ARROW_ANGULAR=0.20 ./tools/fishbot.sh arrows
```

### 1.3 用已保存地图启动导航

```bash
cd /home/muqiao/dev/ros2
./tools/fishbot_stack.sh restart-nav
```

用途：

- 起控制桥
- 起雷达驱动
- 起 Nav2
- 自动起导航用 `rviz`

说明：

- 默认优先使用 `fishbot_navigation2/maps/current_map.yaml`
- 如果 `current_map.yaml` 不存在，就回退到 `live_map.yaml`
- 如果 `live_map.yaml` 也不存在，再回退到 `room.yaml`

### 1.4 查看后台窗口

```bash
cd /home/muqiao/dev/ros2
./tools/fishbot_stack.sh attach
```

### 1.5 看状态

```bash
cd /home/muqiao/dev/ros2
./tools/fishbot_stack.sh status
```

### 1.6 停掉整套

```bash
cd /home/muqiao/dev/ros2
./tools/fishbot_stack.sh stop
```

### 1.7 真机停车安全

当前 FishBot 主控板没有 `cmd_vel` 超时自动刹停；如果上位机掉线，车端可能继续保持最后一次速度。因此真机动作测试必须把“动作”和“停止”绑定执行。

默认停车命令会持续 30 秒发布零速度：

```bash
cd /home/muqiao/dev/ros2
./tools/fishbot.sh estop
```

`stop_cmd` 现在也是同样的 30 秒零速度保持，不再是单次零速度包：

```bash
./tools/fishbot.sh stop_cmd
```

如需调整保持时间：

```bash
FISHBOT_STOP_HOLD_SECONDS=45 ./tools/fishbot.sh estop
```

实机测试前后都要检查并清理残留控制源：

```bash
ps -ef | grep -E 'ros2 topic pub|teleop|fishbot-arrow-teleop|cmd_vel' | grep -v grep
tmux list-sessions
```

---

### 1.8 Docker 弃用说明

当前主线放弃 `fishbot_agent` Docker 容器。原因：Windows + Docker + WSL 会把 UDP 接收、ROS 图、rosbridge、调试 CLI 分裂成多层，建图排障时很难统一调度。

现在的默认策略是：

```text
Windows 防火墙放行 8888/udp
小车 UDP -> WSL 本地 micro_ros_agent
WSL 本地 ROS 图 -> /odom /imu /cmd_vel /scan /tf /map
```

因此：

- `./tools/fishbot_stack.sh slam-base` 会在 tmux 中启动 `agent` 和 `control_rosbridge` 窗口。
- `./tools/fishbot.sh arrows/drive/estop` 都直接使用 WSL 本地 ROS2。
- 旧的 `docker.exe logs/exec fishbot_agent ...` 不再是主线排障入口。
- 如果 `micro_ros_agent` 包不存在，先补齐 `/home/muqiao/dev/ros2/workspaces/micro_ros_agent_ws` 源码构建。

## 2. 现在到底起了什么

当前主线不是“只看浏览器”，而是两层同时存在：

```text
浏览器层:
  frontend:5173
  backend:8080

ROS2 原生层:
  control bridge
  lidar
  rosbridge:9091
  odom2tf
  static_tf
  slam_toolbox
  rviz2
```

重点：

- 浏览器只是辅助观察
- 真正建图工具是 ROS2 原生 `rviz2`
- `restart-slam` 现在已经会顺手把 `rviz` 窗口一起起起来

---

## 3. 端口约定

这些端口固定，不要混：

```text
8888/udp  -> WSL 本地 micro-ROS agent
9090/tcp  -> WSL 本地 rosbridge（控制桥）
8889/tcp  -> 无线 TCP 雷达输入
9091/tcp  -> WSL 本地 rosbridge（雷达桥）
8080/tcp  -> fishbot-control-station backend
5173/tcp  -> fishbot-control-station frontend
8010/tcp  -> fishbot-web-panel（手机 PWA 遥控/诊断，absorbed ros2-mobile-panel）
```

一句话记忆：

- `9090` = 控制桥
- `9091` = 雷达桥
- 浏览器只看 `8080/5173`
- 手机看 `8010`（同一局域网，`http://<主机IP>:8010`，可加桌面安装成 PWA）
- 建图还是看 `rviz`

### 3.1 Windows 防火墙前置条件

小车、雷达板、电脑在同一 WiFi 时，Windows 入站防火墙必须放行这些端口：

```powershell
New-NetFirewallRule -DisplayName "FishBot micro-ROS 8888 UDP Any" -Direction Inbound -Action Allow -Protocol UDP -LocalPort 8888 -Profile Any
New-NetFirewallRule -DisplayName "FishBot LiDAR 8889 TCP Any" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8889 -Profile Any
New-NetFirewallRule -DisplayName "FishBot LiDAR 8889 UDP Any" -Direction Inbound -Action Allow -Protocol UDP -LocalPort 8889 -Profile Any
New-NetFirewallRule -DisplayName "FishBot rosbridge 9090 TCP Any" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 9090 -Profile Any
New-NetFirewallRule -DisplayName "FishBot laser bridge 9091 TCP Any" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 9091 -Profile Any
```

验证：

```powershell
Get-NetFirewallRule -DisplayName "FishBot*" | Select-Object DisplayName, Enabled, Direction, Action
Get-NetConnectionProfile
```

即使 WiFi 是 `Public`，上面的规则因为用了 `-Profile Any` 也应该生效。

---

## 4. 典型场景

### 场景 A：我要只开控制台

```bash
cd /home/muqiao/dev/ros2
./tools/fishbot_stack.sh start-control
```

### 场景 B：我要只看雷达

```bash
cd /home/muqiao/dev/ros2
./tools/fishbot_stack.sh start-laser
```

### 场景 C：我要正常全栈联调

```bash
cd /home/muqiao/dev/ros2
./tools/fishbot_stack.sh start
```

### 场景 D：我要从零开始重新建图

```bash
cd /home/muqiao/dev/ros2
./tools/fishbot_stack.sh restart-slam
./tools/fishbot_stack.sh preflight-slam
./tools/fishbot.sh arrows
```

### 场景 E：我要启动导航

```bash
cd /home/muqiao/dev/ros2
./tools/fishbot_stack.sh restart-nav
```

前提：

- 你已经有一张保存下来的地图
- 默认文件优先级是：
  - `current_map.yaml`
  - `live_map.yaml`
  - `room.yaml`

推荐做法：

- 每次确认一张可用新图后，把它保存成 `current_map`
- `live_map` 可以继续当作临时实验图

然后：

```bash
./tools/fishbot_stack.sh attach
```

在 tmux 里看：

- `slam`
- `rviz`

---

## 5. tmux 窗口说明

默认会话名：

```text
fishbot
```

常见窗口：

```text
control_bridge
lidar
rosbridge
backend
frontend
web_panel
odom2tf
static_tf
slam
nav
rviz
```

`web_panel` 是 absorbed 自 ros2-mobile-panel-day1 的手机面板（FastAPI + PWA 单进程，8010）。
`start` / `start-slam` / `start-nav` 会默认拉起；单独控制用 `fishbot_stack.sh start-web`，
重启用 `restart-web`。手机连同一局域网访问 `http://<主机IP>:8010`；
遥控带死人开关（300ms TTL，松手/锁屏/断连即停），只能替代 RViz 级别的观察与
低速点动，不替代物理急停。详见 `fishbot-web-panel/README.md`。

进入：

```bash
tmux attach -t fishbot
```

离开但不杀后台：

```text
Ctrl+b 然后按 d
```

---

## 6. 常用日志命令

看单个窗口：

```bash
./tools/fishbot_stack.sh logs lidar
./tools/fishbot_stack.sh logs rosbridge
./tools/fishbot_stack.sh logs backend
./tools/fishbot_stack.sh logs frontend
./tools/fishbot_stack.sh logs control_bridge
./tools/fishbot_stack.sh logs odom2tf
./tools/fishbot_stack.sh logs slam
./tools/fishbot_stack.sh logs rviz
```

看地图是否出来：

```bash
./tools/fishbot_map_probe.sh
```

看雷达是否有数据：

```bash
./tools/fishbot_laser_scan_probe.sh
```

---

## 7. 当前主线的判断标准

### 7.1 建图开始前的最低标准

- `/scan` 有数据
- `/odom` 有新数据
- WSL 本地 `micro_ros_agent` 监听 `8888/udp`
- WSL 本地控制 `rosbridge` 监听 `9090/tcp`
- `ydlidar_node` 监听 `8889`，雷达板能连进来
- Windows 防火墙有 `FishBot*` 入站规则

直接跑：

```bash
./tools/fishbot_stack.sh preflight-slam
```

如果看到：

```text
[WARN] backend does not report robotOnline=true
[FAIL] /odom probe did not receive fresh data
```

不要继续执行 `slam-core`，也不要开 `arrows`。这不是雷达问题，是 micro-ROS 控制链没有恢复。

控制链诊断命令：

```bash
cd /home/muqiao/dev/ros2
./tools/fishbot_stack.sh logs agent
```

```bash
source /opt/ros/jazzy/setup.bash
source /home/muqiao/dev/ros2/workspaces/micro_ros_agent_ws/install/setup.bash
ros2 topic list
ros2 topic info -v /odom
ros2 topic info -v /imu
```

```bash
timeout 8 ros2 topic echo /odom --once
timeout 8 ros2 topic echo /imu --once
```

如果 `agent` 窗口提示 `UDP 8888 is already in use`，先释放旧 Docker Desktop 端口映射或旧 agent，再重启 native 栈。

恢复顺序：

```bash
cd /home/muqiao/dev/ros2
./tools/fishbot_stack.sh slam-reset
./tools/fishbot_stack.sh slam-base
./tools/fishbot_stack.sh preflight-slam
```

如果仍然没有 `/odom`，把小车拿近、重启主控板、确认主控板连接同一 WiFi。不要只重启雷达板。

### 7.2 建图过程中才看的标准

- `odomToBasePresent = true`
- `/map` 能被 probe 到
- `rviz` 能看到地图增长

### 7.3 浏览器不是最终判断标准

浏览器可以辅助看状态，但不是建图是否成功的最终标准。

真正标准是：

- ROS2 原生 `/map`
- ROS2 原生 TF
- `rviz`

---

## 8. 固件烧录与板子配置（2026-09-06 实测沉淀）

工具全部在本机，**不再需要 Windows**：`ros2/fishbot_tool/`。

### 8.1 关键铁律（踩过的坑，勿再踩）

1. **烧录前必须全量备份 flash**：`read_flash 0 0x400000 xxx_backup.bin`。备份文件放 `ros2/plans/fishbot-jazzy-mapping/firmware_backup/`（主控板 20260906 备份 md5 `9fba7634...`，雷达板 `81118edc...`）。
2. **雷达板固件版本锁定 `v1.4.0.250711`，不要升级 v2.1.0**：v2.1.0 的"启动检测"有死锁 bug——雷达上电即流式发数据，板子在 WiFi 初始化的几秒里没人读 UART → 硬件 FIFO 溢出卡死 → 检测永远失败 → 永远卡 `mode:flash&config` 配置模式。v1.4.0 无此逻辑。若上游修复再评估升级。
3. **重启雷达驱动或 stop 栈之后，雷达板必须断电重上电一次**：监听端正常关闭（FIN）后板子察觉不到，会卡在半开 TCP 上不再重连（表现为 OLED `wifi:running` 但主机侧 ping 不通、无连接）。若是端口拒绝（RST）板子会立刻重试，无此问题。
4. **两块板子的配置协议相同**：串口 115200，发 `$key=value\n`，回 `$result=ok`；`$command=read_config` 读全部配置。雷达板读配置没响应 ≠ 板子死，可能只是不在配置模式。
5. **WiFi SSID 大小写敏感**：历史板子里存的是 `MuqiaoBot`，当前热点是 `Muqiaobot`——这曾导致主控板 `NO_AP_FOUND(201)`。改网络后用板子 OLED 或 read_config 复核。
6. 板子 OLED 是最快的诊断面：`mode:laser2wifi`（正常桥接）/ `mode:flash&config`（雷达数据没到 UART）+ `wifi:` 状态行 + `ip:`/`s_ip:`。

### 8.2 烧录命令（esptool 独立二进制，无需 pip）

```bash
cd /home/muqiao/dev/ros2/fishbot_tool
# 备份（先做！）
./esptool/esptool_linux_amd64 --chip esp32   --port /dev/ttyUSB0 --baud 460800 read_flash 0 0x400000 backup_main.bin
./esptool/esptool_linux_amd64 --chip esp8266 --port /dev/ttyUSB0 --baud 460800 read_flash 0 0x400000 backup_laser.bin
# 烧录（官方参数；固件为合并镜像，整包 0x0）
./esptool/esptool_linux_amd64 --chip esp32   --port /dev/ttyUSB0 --baud 460800 --before default_reset --after hard_reset write_flash --flash_mode dio --flash_size detect --flash_freq 40m 0x00 <motion.bin>
./esptool/esptool_linux_amd64 --chip esp8266 --port /dev/ttyUSB0 --baud 460800 --before default_reset --after hard_reset write_flash --flash_mode dio --flash_size detect --flash_freq 40m 0x00 <laser.bin>
```

- 主控板 = esp32（`fishbot_motion_control_v1.8.0.alpha.250724.bin`，tool 目录里有）
- 雷达板 = esp8266（`fishbot_laser_control_v1.4.0.250711.bin`，tool 目录里有）
- 官方固件清单在论坛 API：`https://fishros.org.cn/forum/api/v3/posts/10390`（YAML 内含各版本 URL）
- 烧合并镜像会重置 NVS：烧完必须重新配置网络。

### 8.3 串口配置示例

```bash
# 交互式读取（python serial 115200 发 $command=read_config）
# 主控板关键键：wifi_ssid wifi_pswd udpserver_ip udpserver_port microros_mode
# 雷达板关键键：wifi_ssid wifi_pswd server_ip server_port(tcp:8889) net_mode laser_baud motor_speed
```

雷达板配置后重启生效；主控板同理。烧录模式（进下载模式）用板上按键/短接，esptool 秒连即表示成功。

### 8.4 当前网络基线（2026-09-06）

- 主机热点 `Muqiaobot`（注意大小写），主机 IP `10.215.71.172`（DHCP，会变；变了两块板子都要重新配置，建议热点侧做静态分配）
- 主控板 → UDP 8888 → micro_ros_agent（Jazzy，micro_ros_agent 5.0.2 + micro_ros_msgs，源码构建于 `workspaces/micro_ros_agent_ws`）
- 雷达板 → TCP 8889 → ydlidar_node（protocol:=net）
- 首图证据：`fishbot_nav/src/fishbot_navigation2/maps/live_map.{pgm,yaml}`，重载验证通过

---

## 9. 排障顺序

推荐每次按这个顺序查：

```bash
./tools/fishbot_stack.sh status
./tools/fishbot_stack.sh preflight-slam
./tools/fishbot_laser_scan_probe.sh
./tools/fishbot_map_probe.sh
./tools/fishbot_stack.sh logs slam
./tools/fishbot_stack.sh logs control_bridge
./tools/fishbot_stack.sh logs odom2tf
```

如果你已经在建图模式里，优先盯：

- `slam`
- `rviz`

---

## 10. 文件索引

### Conda 环境启动遥控（2026-09-11）

若错误包含 miniconda Python 3.13 与 Jazzy `cpython-313` 扩展缺失，是解释器 ABI 不匹配，不是网络断流。`source /opt/ros/jazzy/setup.bash` 不会自动替换 Conda Python。`fishbot.sh` 的 arrows 与定时速度/停车入口现明确使用 `/usr/bin/python3`（本机3.12）；不要用 pip 重装 rclpy 或绕过 odom 门禁来解决。Conda 优先 PATH 下非 TTY 启动已通过 import/帮助输出并在创建控制节点前退出，未发速度；真实键盘运动仍由用户现场验收。

2026-09-11 安全说明：HTTP 状态桥只发布 `/station/odom`、`/station/imu` 诊断副本，不再发布 SLAM 使用的 `/odom`、`/imu`。不要将诊断副本重映射回传感器话题。控制站软件停止不能排除 Nav2 等外部发布者；源码中新增的固件 500 ms 超时保护尚未烧录、尚未实机验收。

- [fishbot.sh](/home/muqiao/dev/ros2/tools/fishbot.sh)
- [fishbot_stack.sh](/home/muqiao/dev/ros2/tools/fishbot_stack.sh)
- [fishbot_control_state_bridge.py](/home/muqiao/dev/ros2/tools/fishbot_control_state_bridge.py)
- [fishbot_laser_scan_probe.sh](/home/muqiao/dev/ros2/tools/fishbot_laser_scan_probe.sh)
- [fishbot_map_probe.sh](/home/muqiao/dev/ros2/tools/fishbot_map_probe.sh)
- [fishbot_live_slam.sh](/home/muqiao/dev/ros2/tools/fishbot_live_slam.sh)
- [FISHBOT_CH9_WSL_NAT_UDP.md](/home/muqiao/dev/ros2/tools/FISHBOT_CH9_WSL_NAT_UDP.md)
