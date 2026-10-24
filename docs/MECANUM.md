# 麦克纳姆底盘接入

`robot_base` 已并入 FishBot。后续修改本仓库的 `workspaces/mecanum_ws/src/robot_base/`，共用本仓库提交、反馈测试和成果工作台。旧独立目录保留为历史来源，不再作为运行依赖。来源与九月修复见包内 [UPSTREAM](../workspaces/mecanum_ws/src/robot_base/UPSTREAM.md)。

## 已复用的能力

| 层 | 本轮处理 |
| --- | --- |
| 串口驱动 | 保留 `$pwm:m1,m2,m3,m4#` 与 `$MSPD` 协议、限幅和重连归零 |
| 麦克纳姆运动学 | 保留 vx/vy/wz、轮序和正逆运动学，反馈以 mm/s 输入 |
| ROS 接口 | 保留 Twist、Odometry、odom→base_link TF，接现有 scan/map/Nav2 接口 |
| 启动与参数 | 合并重复 drive/TF 定义；保留 C1、SLAM、Nav2 与 RViz 启动入口 |
| 平台 | 使用同一 `fishbot.sh`、成果页、构建/测试与 Git 远端 |

原例图、旧构建、会话状态、硬件练轮脚本和模板lint测试没有迁入。没有另写串口协议、地图编辑器或任务调度器。

## 根入口

```bash
./fishbot.sh mecanum info
./fishbot.sh mecanum build
./fishbot.sh mecanum args drive
./fishbot.sh mecanum args minimal
```

info 不导入 ROS 或打开设备。build 仅构建这一个 ament_python 包，默认输出到 `~/.cache/fishbot/mecanum-build/`。可用 `FISHBOT_MECANUM_BUILD_ROOT` 改变输出位置。args 解析 launch 参数，不启动节点。包通过安装 overlay 加载，不依赖旧源码目录。

以下为后续有硬件时显式启动的入口，本次没有运行。填写已确认的设备、雷达朝向与地图，保留现有命令owner的最终输出topic。

```bash
./fishbot.sh mecanum minimal \
  serial_port:="$DRIVE_PORT" laser_port:="$LASER_PORT" laser_yaw:="$LASER_YAW" \
  cmd_topic:="$FINAL_CMD_TOPIC" odom_topic:=odom
./fishbot.sh mecanum mapping \
  serial_port:="$DRIVE_PORT" laser_port:="$LASER_PORT" laser_yaw:="$LASER_YAW"
./fishbot.sh mecanum navigation map:="$MAP_YAML"
./fishbot.sh mecanum rviz
```

mapping 复用同一 minimal/drive 和官方 slam_toolbox launch，配置来自包内 YAML。navigation 延续旧方式，不重复启动底盘。没有新增第二个命令仲裁器；应把 cmd_topic 接在现有仲裁/平滑/碰撞链的最终出口。不得同时运行同名底盘或 TF 发布者。

原参数是历史硬件基线：轮径 .097m、左右距 .445m、前后距 .17m、k=.3075m、反馈极性 -1、主机超时 .5s。开环 odom 回退仍是显式配置项，不能当作轮速观测或定位真值。主机看门狗发零的测试不证明断串口/主机停机时的实体制动。

## 验收边界

本轮真实 Jazzy 节点只连接 Linux 创建的 `/dev/pts/*` 伪终端。8项检查覆盖连接归零与回传启用、前进/横移/旋转报文、超时归零、反馈odom与TF、非有限指令归零及重连后重新启用反馈。先保留失败a，再用最小修复通过b；没有用构建成功代替这些行为。

在已构建overlay上复核，输出放Git外：

```bash
source /opt/ros/jazzy/setup.bash
source ~/.cache/fishbot/mecanum-build/install/setup.bash
python3 -B tools/mecanum_serial_probe.py --domain 181 --output "$PTY_REPORT"
```

普通离线入口：

```bash
python3 -B -m unittest tools.tests.test_mecanum_integration
./fishbot.sh check
```

原 Nav2 smoother 的横向速度上限为零。驱动能横移不等于自主导航已验证横移。还没有麦克纳姆 MuJoCo 接触模型、已核尺寸/外廓/托盘与机械臂交接模型，因此未把它加入已通过运输的仿真车型选择；FishBot/J100 的原结果不改变。下一步应先验证本体平移/旋转，再跑相同 Nav2 与配送任务，而不是复用差速接触模型冒充麦克纳姆。
