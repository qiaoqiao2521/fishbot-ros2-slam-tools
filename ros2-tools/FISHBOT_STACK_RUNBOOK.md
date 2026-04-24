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

- 起控制容器
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
- 重新起控制桥、雷达桥、SLAM
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

---

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
8888/udp  -> fishbot_agent 容器里的 micro-ROS agent
9090/tcp  -> fishbot_agent 容器里的 rosbridge（控制桥）
8889/tcp  -> 无线 TCP 雷达输入
9091/tcp  -> WSL 本地 rosbridge（雷达桥）
8080/tcp  -> fishbot-control-station backend
5173/tcp  -> fishbot-control-station frontend
```

一句话记忆：

- `9090` = 控制桥
- `9091` = 雷达桥
- 浏览器只看 `8080/5173`
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
odom2tf
static_tf
slam
nav
rviz
```

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
- `fishbot_agent` 容器运行，且暴露 `8888/udp`、`9090/tcp`
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
docker.exe logs --tail 160 fishbot_agent
```

```bash
docker.exe exec -it fishbot_agent bash -lc 'source /opt/ros/humble/setup.bash; ros2 topic list'
```

```bash
docker.exe exec -it fishbot_agent bash -lc 'source /opt/ros/humble/setup.bash; timeout 8 ros2 topic echo /odom --once'
docker.exe exec -it fishbot_agent bash -lc 'source /opt/ros/humble/setup.bash; timeout 8 ros2 topic echo /imu --once'
```

恢复顺序：

```bash
cd /home/muqiao/dev/ros2
./tools/fishbot.sh stop
./tools/fishbot.sh start
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

## 8. 排障顺序

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

## 9. 文件索引

- [fishbot.sh](/home/muqiao/dev/ros2/tools/fishbot.sh)
- [fishbot_stack.sh](/home/muqiao/dev/ros2/tools/fishbot_stack.sh)
- [fishbot_control_state_bridge.py](/home/muqiao/dev/ros2/tools/fishbot_control_state_bridge.py)
- [fishbot_laser_scan_probe.sh](/home/muqiao/dev/ros2/tools/fishbot_laser_scan_probe.sh)
- [fishbot_map_probe.sh](/home/muqiao/dev/ros2/tools/fishbot_map_probe.sh)
- [fishbot_live_slam.sh](/home/muqiao/dev/ros2/tools/fishbot_live_slam.sh)
- [FISHBOT_CH9_WSL_NAT_UDP.md](/home/muqiao/dev/ros2/tools/FISHBOT_CH9_WSL_NAT_UDP.md)
