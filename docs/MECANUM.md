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

## 同一 MuJoCo 配送环境

车型配置新增 `robot_base_mecanum`。网页协同页共用“车型＋传感器＋任务”草稿；下载 JSON 后沿用原 prepare/run/workflow，不创建第二套模拟器、ROS桥或任务owner。草稿不会热替换当前实例。

```json
{"schema":1,"vehicle":"robot_base_mecanum","sensors":"planar","task":"transport"}
```

```bash
export FISHBOT_COOP_PYTHON="$HOME/.cache/so101-colab/planning-venv/bin/python"
./fishbot.sh cooperation prepare \
  --so101-project ../so101 --scene-profile /path/to/cooperation-profile.json \
  --factory-config tools/config/factory_delivery/line-side-open.json \
  --output "$NEW_SCENE"
```

启动沿用[原配送入口](FACTORY_DELIVERY.md)，选择独立ROS域、端口与新输出目录。常规运行默认不写完整物理日志；验收继续使用原独立observer、原生动作终态和物理评分。

模型使用4个驱动轮铰链和48个被动滚子铰链，驱动不写车体自由关节。滚子轴构造改编自MIT的[JunHeonYoon/mujoco_mecanum](https://github.com/JunHeonYoon/mujoco_mecanum)，保留[许可证](../tools/licenses/mujoco_mecanum.MIT)；没有迁入旧mujoco_py运行器。原模型不适合直接缩放，当前使用胶囊滚子与有界轮速伺服，通过原生接触面板验证。

轮径97mm、左右距445mm、前后距170mm来自原robot_base参数。车壳50×52×10cm、壳体6kg、轮毂/滚子质量、45°胶囊形状和电机力矩均为仿真假设。完整壳体、轮组与托盘参加外部碰撞，内部轮组自碰撞被过滤。假设保存在manifest的vehicle_profile中，不称实物标定。

宽车壳使用侧移40mm的安装位置，托盘反向补偿40mm，保持SO101交货点XY=.24/.14m。40×40×80mm铝立柱连接托盘和车壳，按2700kg/m³计.3456kg；刚性连接与紧固强度仍是假设。先调用原DriveOnHeading直线离站.7m，再由原Nav2驶向目的地，保留原碰撞检查。

四轮编码器按关节名读取，避开中间48个被动自由度。里程计只积分编码器，真值仅评分；默认使用原生AMCL OmniMotionModel。配送继续复用RPP的vx/wz，横移运动面板与自主横移导航分别验收。原FishBot/J100默认与历史评分保持。

2026-10-24原生运动面板16/16通过：空载/载货分别执行直行、倒行、左右横移、正反旋转、斜行与弧线。请求横移.06m/s，实际约.0507m/s；6秒编码器端点偏差约18.2mm。非地面碰撞与500Hz载货支撑缺失均0。载货初始摆放仅为接触测试，不代替机械臂交接。

同日移动Nav2探针通过：两个25cm目标的原生Goal均status4，实际位移21.8/24.5cm，终点XY2.80/3.30cm。原生DDS见证器确认两阶段控制器各自消费计划，最终hold与连续.7源秒静止、实例清理通过。该探针对应初版安装；新安装另通过16项运动和原独立短停靠评分。

完整E轮在同一146/9116实例完成开放通道B→A，原独立K与目的地评分2/2通过。B/A分别用时232.320/230.112墙秒，配送预算内35.241/22.042秒，最终XY误差2.064/2.246cm，yaw.00032/.00342rad；每单仍360秒、路线120秒，原.04m/.05rad与所有交接/载货条件保持。两次start、一次显式reset、零cancel，540.261秒收尾后实例关闭。

本轮使用ideal工位观测，停车保护介入.88/.40源秒；原物理序号缺失38/28，采样不插值。它只证明本轮仿真，不能称纯视觉、生产稳定、真机或sim-to-real成功。3D配置的场景生成与5760射线查询通过，本次完整配送实际使用2D雷达。所有早期失败、源边界和清理证据见[接续进度](../plans/mecanum-consolidation-20261024/progress.md)。

成果页的配送记录可切换“J100 · 原完整K”和“麦克纳姆 · 配送验收”，共用[耗时报告合同](DELIVERY_TIMING.md)。旧J100记录保持；其占用通道与本轮开放通道不同，不把这两份耗时当作车型A/B对照。

复核接触面板和合同：

```bash
"$FISHBOT_COOP_PYTHON" -B tools/cooperation_mecanum_probe.py --output "$NEW_MOTION_REPORT" --render
source /opt/ros/jazzy/setup.bash
python3 -B -m unittest tools.tests.test_cooperation_mecanum
```
