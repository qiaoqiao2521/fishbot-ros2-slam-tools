# FishBot 连续过窄口控制

2026-10-06：按用户选择使用官方开源模型，不要求先现场量尺寸。此入口实现整段目标、本地持续控制、分级避障和停车回放；实车充电期间只做离线/隔离仿真验证。

## 控制链

`Nav2 /cmd_vel_nav → velocity_smoother /cmd_vel_smoothed → Collision Monitor /cmd_vel_safe_candidate → fishbot_command_guard → /cmd_vel`

`fishbot_passage_goal.py` 将“按当前朝向前进一段距离”转换成一个地图坐标目标，持续交给 Nav2 RPP 执行。它不会承诺几何直线：局部控制仍可修正路线以避障。行为树只允许一次清图恢复，没有自动旋转/后退重试循环；超时先锁定最终零速，再取消任务。完成后最多观察五秒，并要求末尾连续一秒的新鲜静止反馈。

守卫是唯一最终速度发布者，校验候选发布者、底盘订阅者、原始命令/odom/scan 时间和坐标系。上游使用带时间戳速度；实车末端转换为现有固件使用的 Twist，仿真末端保留 TwistStamped。仅在配置健康且有新的有效候选时放行。异常停机需要显式 reset 及新鲜零速候选；记录写盘失败也会阻止运动。板端 watchdog/旧指令拒绝是否生效仍需单独验收。

平滑器在停止时会保留原输入时间戳；过期但有效的全零指令只保持空闲停车，不触发永久误锁。过期非零、未来及无效时间戳仍拒绝，绝不将旧指令重打为当前时间。

## 一份外廓、两种距离处理

[官方模型参数](../tools/config/fishbot_model_geometry.yaml) 保存出处、固定版本和哈希。外廓覆盖直径 20 cm 的圆车身及左右车轮，最大宽 24 cm；另加 5 mm 建模余量。Nav2 两张代价地图、碰撞区域和离线回放都从这一文件生成。

- 靠近外廓约 5 cm 的区域触发限速，直线速度最多 0.03 m/s，不直接按“大矩形”停车。
- 硬停车区域覆盖外廓及当前速度档在 0.3 秒内的运动范围，包括转向扫过的角；这是设计时域，尚不是实车制动距离标定。
- 另有 1 秒预测接近减速；自由空间最大 0.08 m/s。
- 单个有效激光点仍可触发碰撞停车，保留细腿障碍。未知/过期数据不能被当成可通行。

不要直接启动 YAML 模板；启动器会先生成共享几何、统一时间配置及速度重映射。旧 `fishbot_guarded_mapping.py` 参数保留，避免两套入口含义混杂。

## 隔离仿真

从项目根运行。以下只操作 domain 96，本机回环发现；默认旧仿真 domain 93 和实车 domain 0 保留。

```bash
export FISHBOT_MUJOCO_DOMAIN_ID=96
source tools/fishbot_mujoco_env.sh
ros2 launch tools/fishbot_passage_sim.launch.py \
  ros_domain_id:=96 output_dir:=/tmp/fishbot-passage-session
```

另一个同环境终端：

```bash
python3 tools/fishbot_passage_goal.py --domain 96 --use-sim-time \
  --distance 1.25 --execute --output /tmp/fishbot-passage-session/goal.json
rviz2 -d tools/config/fishbot_passage.rviz --ros-args -p use_sim_time:=true
```

输出必须为新文件。仿真场景是公开的合成 36 cm 门口，不是对用户家中场景的重建；固定 `map→odom` 仅用于该已知初始位置的测试，结果还须核对 MuJoCo 真值。不要把真值或固定 TF 接到实车定位。

仅检查配置、不启动 ROS：

```bash
python3 tools/fishbot_passage.launch.py
python3 tools/fishbot_passage_goal.py --distance 1
```

## 之后接实车的入口

`fishbot_passage.launch.py` 不启动雷达、底盘、SLAM、AMCL 或地图服务器。实车需沿用已有传感器/SLAM，以及新鲜的 `map→odom→base_footprint`。启动前确认没有旧遥控/导航直接发布最终 `/cmd_vel`，底盘 node 名匹配模型配置；守卫会拒绝重复发布和错误接收端。

启动参数明确选择 `ros_domain_id:=0 allow_real:=true use_sim_time:=false execute:=true`，且指定源码 Git 根之外的绝对 `output_dir`。目标客户端也必须显式使用 `--domain 0 --real --execute`。这些开关只表达执行意图，不代表先前实车时钟/转角问题已经修复。当前回合没有执行实车入口。

## 停车记录和图

事件保存于 `<output_dir>/command_guard/trigger-*.json`，包含原生时间、接收时间、命令、odom、激光、运行时 TF、共享几何、发布者归属、当时区域和最近 40 条输入。先发布零速，再排队写盘；目录 0700，文件 0600。扫描/地图/日志留在私有输出目录，不入 Git。

Collision Monitor 的状态消息没有触发扫描编号和时间戳，因此事件是**状态回调时最近收到的数据及其历史窗口**，不能宣称恰好就是 CM 内部那一帧。RViz 显示停车时扫描与区域，JSON 保留该关联限制。

```bash
python3 tools/fishbot_passage_replay.py --help
```

回放生成 JSON、SVG 和 HTML，逐点区分硬碰撞、预测碰撞、限速区与观测可通行。历史扫描缺帧名时必须显式记录 `--assume-scan-frame laser_frame`；未知 TF 返回 unknown。新事件使用保存的实际 3D TF，并重算点坐标作一致性检查。离线 clear_observed 只代表该帧没有命中，不能替代完成过门。

碰撞事件默认采用保存的上游速度输入来重算区域，并同时保留停车后的候选零速与记录区域。它们可能因回调顺序不同而属于不同瞬间；不能拿停车后的零速反推碰撞原因，也不能将重算结果称为精确同步触发帧。

最新验证和待办见 [任务进度](../plans/fishbot-real-autonomy-20261005/progress.md)。
