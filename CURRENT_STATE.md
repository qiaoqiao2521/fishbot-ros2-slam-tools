# CURRENT_STATE.md — fishbot-ros2-slam-tools

> 恢复日期：2026-09-15（按"作者已忘记实现细节"从零勘察 + 实测）
> 环境：Ubuntu 24.04 / **ROS2 Jazzy**（/opt/ros/jazzy）/ colcon / CMake 3.28 / GCC 13
> 本地克隆：`/home/muqiao/repo-revival/fishbot-ros2-slam-tools`（GitHub: muqiao215/fishbot-ros2-slam-tools，最后推送 2026-04-25）

## 一句话结论

**6 个 ROS2 包现在全部能编译通过（改了 2 处 CMake install），并且 odom→TF 与 URDF→TF 两条链路我用真实消息验证过。**
但它是"课程/实车快照"：缺雷达参数、缺导航地图与参数、脚本里全是 Humble 硬编码，Cartographer 线在本机跑不起来。

## 1. 用途

FishBot 移动机器人「雷达 → SLAM → 导航」工具集 + 一个 Web 控制台快照（README.md:3；README.md:13 明确"必须先原生 ROS2 建图，前端渲染不算建图成功"）。

三个顶层目录：

| 目录 | 内容 |
|---|---|
| `fishbot-nav-src/` | 6 个 ROS2 包：雷达驱动 / URDF / odom→TF / Cartographer / Nav2 / 自定义 srv |
| `ros2-tools/` | tmux 分阶段启动器、探针脚本、micro-ROS agent 的 Dockerfile、两份长文档 |
| `fishbot-control-station/` | Spring Boot 3(Java17) + React/Vite 控制台，经 rosbridge 订阅 /scan /odom /map |

## 2. ROS2 包与入口

| 包 | 入口 | 产物 |
|---|---|---|
| `ydlidar` | `ydlidar/src/ydlidar_node.cpp:35` `main` | `ydlidar_node`(发 `/scan`、`/point_cloud`)、`ydlidar_client` |
| `fishbot_bringup` | `fishbot_bringup/src/odom2tf.cpp:38` `main` | `odom2tf`（订阅 `odom` → 广播 TF） |
| `fishbot_cartographer` | `launch/cartographer.launch.py` | 仅配置/launch/rviz，无可执行文件 |
| `fishbot_description` | — | 仅 URDF |
| `fishbot_interfaces` | — | rosidl 生成 `srv/FishBotConfig.srv` |
| `fishbot_navigation2` | `launch/navigation2.launch.py` | 仅 launch（include nav2_bringup） |

## 3. 依赖

本机实测（Jazzy）：

- ✅ 已装：`nav2_bringup`、`slam_toolbox`、`rosbridge_server`、`robot_state_publisher`、`joint_state_publisher`、`tf2_ros`、`rviz2`
- ❌ 未装：`cartographer_ros`（apt 有 `ros-jazzy-cartographer-ros`，未装）、`micro_ros_agent`（apt 无，需源码构建 micro_ros_setup）
- ydlidar 的 serial / 数学库由 vendored SDK 自带（`sdk/core/serial/`），不依赖系统 `serial` 包。
- 无 `.gitmodules`、无子模块缺失。

## 4. 构建与运行

```bash
mkdir -p ~/ws/src && cp -r fishbot-nav-src/* ~/ws/src/
cd ~/ws && source /opt/ros/jazzy/setup.bash
# ⚠️ 必须显式指定系统 python，见第 7 节
colcon build --symlink-install --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3
source install/setup.bash
```

仓库内**没有构建说明**，README.md:17-25 给的是 `/home/muqiao/dev/ros2` + `tools/fishbot_stack.sh` 的旧路径流程。

## 5. 核心数据流

```
micro-ROS agent(udp4:8888) → /odom → odom2tf(odom2tf.cpp:11→34) → TF(odom→base_footprint)
ydlidar → /scan (ydlidar_node.cpp:165)
静态 TF base_footprint→laser_frame
SLAM 两套并行：slam_toolbox(ros2-tools/fishbot_stack.sh:213) 或 cartographer(cartographer.launch.py)
   → /map
保存地图：ros2-tools/fishbot_save_map.sh:36 (nav2_map_server map_saver_cli)
导航：navigation2.launch.py include nav2_bringup
控制台：rosbridge → control-station 前端
```

## 6. 我实际做了什么

### ✅ 真实验证过

1. `colcon build --symlink-install --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3`
   → **6 packages finished**（ydlidar 11.3s、fishbot_bringup 12.0s、fishbot_interfaces 9.1s、fishbot_cartographer / fishbot_description / fishbot_navigation2 各 ~1.3s）。
2. **odom→TF 真链路**：起 `ros2 run fishbot_bringup odom2tf`，用 `ros2 topic pub /odom nav_msgs/msg/Odometry` 灌入 x=1.5,y=0.25，`ros2 topic echo /tf` 收到
   `frame_id: odom → child_frame_id: base_footprint, translation: {x: 1.5, y: 0.25, z: 0.0}`。值完全一致。
3. **URDF 链路**：`ros2 launch fishbot_bringup urdf2tf.launch.py` 正常拉起 `joint_state_publisher` + `robot_state_publisher`，`/robot_description` 有内容（`Robot initialized` / `Got description, configuring robot`）。
4. **雷达节点可运行**：`ros2 run ydlidar ydlidar_node` 能初始化 SDK（打印 `SDK Version: 1.2.9`），然后按预期失败在串口：
   `[error] Error, cannot bind to the specified [serial port:/dev/ydlidar] and [baudrate:230400]` —— 说明节点本体是好的，只差硬件。

### ⚠️ 只是静态推断 / 未验证

- SLAM（slam_toolbox / cartographer）与导航（nav2）**未跑**：需要真实雷达数据流；且 `cartographer_ros` 本机未安装。
- `fishbot-control-station`（Spring Boot + React）**未构建**：需要 JDK17 + Node/npm 与一个在线的 rosbridge。
- micro-ROS agent 链路未验证（本机无 agent、无下位机）。

### ❌ 明确跑不了的

- `bringup.launch.py:30-31` 引用包 `ros_serail2wifi`（拼写疑似应为 ros_serial2wifi）的 `tcp_server`，仓库内不存在、本机未安装 → 该 launch 整体不可用（可用 `bringup_quick.launch.py` 代替）。
- Cartographer 线：`cartographer_ros` 未装。
- `ydlidar/launch/ydlidar.py` 用的是 ROS2 Ardent 时代已移除的 `launch_descriptor` / `ros2run.api`，完全不可用。

## 7. 当前失效点

1. **conda 环境下 colcon 构建 100% 失败（环境陷阱，非仓库缺陷）**：CMake 的 FindPython3 会挑到 `/home/muqiao/miniconda3/bin/python3`（3.13），而 ROS 的 ament 脚本需要带 `catkin_pkg` 的系统 python3.12，结果 6 个包全挂（`ModuleNotFoundError: No module named 'catkin_pkg'`）。
   解法：`colcon build --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3`（已验证）。注意 `export PATH=/usr/bin:$PATH` **不够**，必须显式给 `-D`。
2. **快照缺文件（仓库缺陷，已绕过未补齐）**：
   - `ydlidar/CMakeLists.txt:128` 安装 `params/` —— 该目录不存在；`ydlidar/launch/ydlidar_launch.py:35` 默认参数文件 `params/ydlidar.yaml` 也不存在。
   - `fishbot_navigation2/CMakeLists.txt:26-31` 安装 `config/`、`maps/` —— 都不存在；`navigation2.launch.py:20,22` 引用的 `maps/current_map.yaml`、`config/nav2_params.yaml` 同样缺失。
   我给这两条 install 规则加了 `OPTIONAL`（见第 9 节），让构建能过；但**参数/地图本身仍然缺失，雷达与导航的 launch 依旧起不来**。
3. **ros2-tools 里全是 Humble 硬编码**，本机只有 Jazzy：`fishbot.sh:10-12`、`fishbot_laser_scan_probe.sh:8`、`Dockerfile.fishbot_tools:1`（`microros/micro-ros-agent:humble`）等，需要全局 humble→jazzy 改造。
4. 硬编码宿主路径：`fishbot_stack.sh` 里的 `ROOT=/home/muqiao/dev/ros2` 与 control-station 路径。
5. WSL/Windows 残留：`fishbot.sh:76-84` 探测 `docker.exe`、`fishbot_slam_preflight.sh` 里的 `powershell.exe`、control-station README 里的 `.\\gradlew.bat` 与 `E:\web\...`。
6. `ydlidar_launch.py:38` 用 `LifecycleNode`，但 `ydlidar_node.cpp:38` 是普通 `rclcpp::Node`，没有生命周期转换，节点不会自动 activate。
7. `cmake_minimum_required(VERSION 3.5)`（fishbot_interfaces / fishbot_cartographer / ydlidar），CMake 3.28 只是告警，CMake ≥4 会直接报错。
8. `fishbot_interfaces/msg/MyCustomMessage.msg` 未在 `rosidl_generate_interfaces` 中注册，不会被生成。
9. `ydlidar_node.cpp` 与其副本 `ydlidar_ros2_driver_node.cpp` 内容完全相同（client 同理），重复文件。

## 8. 本次恢复对仓库做的改动（2 个文件，纯构建修复）

1. `fishbot-nav-src/ydlidar/CMakeLists.txt:128-130`：install(DIRECTORY ...) 加 `OPTIONAL`。
2. `fishbot-nav-src/fishbot_navigation2/CMakeLists.txt:26-31`：install(DIRECTORY ...) 加 `OPTIONAL`。

理由：这两处 install 指向快照里不存在的目录，任何一次 `colcon build` 都会在安装阶段硬失败。加 `OPTIONAL` 是最小、可逆、不改语义的修法（目录存在时行为完全不变）。
**没有补齐缺失的 ydlidar.yaml / nav2_params.yaml / 地图**——那需要真实硬件参数与实车地图，属于新内容创作，不该我替你编。
**未升级任何技术栈**：没有动 ROS 版本、CMake 标准、C++ 标准、依赖版本。

## 9. 继续维护是否值得？

**建议：作为"可编译的硬件快照"保留并冻结；除非你还要上实车，否则不再投入。**

- 值得做的（<1 小时）：把 ros2-tools 的 humble→jazzy 改掉、清掉 WSL 残留、给 README 补一条正确的 colcon 构建命令（含 `-DPython3_EXECUTABLE` 这个坑）。这样它就是一份能复现的教学/归档材料。
- 不值得做的：补齐 radar params / nav2 params / 地图并重新跑通 SLAM 与导航 —— 这需要真实 FishBot 硬件 + 场地，纯软件恢复做不到，做了也无法验证。
- `fishbot-control-station`（115 文件）是独立价值最高的一块（Java+React 控制台），如果要复用，建议单独拆仓库维护，比继续养整个 ros2 快照划算。

## 10. 2026-09-15 主线同步（本文件提交同批次）

三块内容全部从活跃主线 `/home/muqiao/dev/ros2` 刷新（脚本 9 月 11 日、控制台与导航包持续演进中），本仓库自此是 FishBot 唯一总仓：

1. `ros2-tools/` ← `dev/ros2/tools/`（`fishbot_stack.sh`、RUNBOOK、CH9 文档全部更新；新增 `config/fishbot_slam.yaml`、`fishbot_ros_env.sh`、`tests/` 等；`__pycache__` 未入库）。
2. `fishbot-control-station/` ← `dev/ros2/apps/fishbot-control-station/`（后端安全改造、新增 3 个测试类、前端 logs 组件；`build/ .gradle/ dist/ node_modules/ src-stale/` 未入库）。
3. `fishbot-nav-src/` ← `dev/ros2/fishbot_nav/src/`（六包全量刷新；新增 `ydlidar/params/ydlidar.yaml`、`fishbot_navigation2/config/nav2_params.yaml` 与 `maps/{room,live_map,current_map}` —— **第 7.2 节"快照缺文件"缺陷就此消除**，两处 CMake 的 `OPTIONAL` 补丁也随之不再需要，已还原为主线原版）。
4. 第 7 节其余失效点状态：Humble 硬编码已在主线脚本中清理（Jazzy 可用）；`ros_serail2wifi`、Cartographer 依赖、ydlidar launch 生命周期问题仍存在；`micro_ros_agent` 仍需实车链路验证。
5. 原 GitHub 私有仓 `muqiao215/fishbot_nav`（2026-05-08 快照）内容已确认为本仓库子集，同日归档。

## 11. 2026-09-15 晚：吸收 ros2-mobile-panel 为 fishbot-web-panel

按"把已验证的 PWA 面板嵌进 FishBot"任务执行。`fishbot-web-panel/` 为上游
ros2-mobile-panel-day1（Day 6，v0.1.0-soft-validated，含 09-14 防重放修复）
的原样吸收：backend/ 原样、frontend-dist/ 预构建 PWA、deploy/ 模板改路径；
仅新增 `fishbot_app.py`（把 frontend-dist 挂载到 "/"，单进程同时服务 UI 与
API/WS）和 `run_web_panel.sh`（`--system-site-packages` venv：web 依赖装
venv，rclpy/numpy 继承系统；默认 `SERIAL_ENABLED=false`——FishBot 控制链路
是 micro-ROS UDP，非 USB 串口，树莓派等有串口的宿主手动开启）。

话题名与栈原生一致（/odom /scan /map /cmd_vel）。端口 8010（8080 已被
control-station backend 占用）；`fishbot_stack.sh start-web` 单独启动，
start/start-slam/start-nav 经 start_base_windows 默认拉起，restart-web 重启。

实测（本机 Jazzy）：上游 20 个契约/网关/桥接测试通过；`start-web` 全链路
冒烟通过（tmux web_panel 窗口 → healthz ok → PWA 首页 200 → WS 收到
system_state/serial_stats 事件，单 worker 常驻）。雷达/里程计真数据视图与
触屏遥控未实测——需要实车在线，与既有验收边界一致。
