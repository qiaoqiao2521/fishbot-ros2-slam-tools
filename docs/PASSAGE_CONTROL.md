# FishBot 连续过窄口控制

按用户选择使用官方开源模型，不要求先现场量尺寸。此入口实现整段目标、本地持续控制、分级避障和停车回放。2026-10-06 完成隔离仿真；2026-10-08 修复联轴器后，实车25厘米导航目标完成并通过新鲜静止反馈。独立激光测得净位移22.59厘米，组合运动的轮式与激光转角仍差2.58°。短段结果支持机械一致性明显改善；2026-10-09 用户已接受工作地图，固定图去程及接续返程完成并通过新鲜停车反馈；轮式标定、连续全路线及板端 watchdog 仍待验收。

## 控制链

`Nav2 /cmd_vel_nav → velocity_smoother /cmd_vel_smoothed → Collision Monitor /cmd_vel_safe_candidate → fishbot_command_guard → /cmd_vel`

`fishbot_passage_goal.py` 接受当前朝向的距离目标，或显式地图目标 `--target X Y YAW`，持续交给 Nav2 RPP 执行。它不会承诺几何直线：局部控制仍可修正路线以避障。行为树只允许一次清图恢复，没有自动旋转/后退重试循环；超时先锁定最终零速，再取消任务。完成后最多观察五秒，并要求末尾连续一秒的新鲜静止反馈。

距离、地图单点与路线文件三个参数互斥，坐标必须有限。地图目标依据新鲜实测位姿检查相对 XY 距离，限制为 `(0, 3]` 米；该限制不是绕行路径总长度。目标朝向使用弧度，记录分别保留实际起点朝向和请求目标朝向。

连续地图路线使用 `--route-file`，格式为 `[[x, y, yaw], ...]`，包含 2–20 个地图点。客户端只提交一次 `/navigate_through_poses`，中间点引导连续路径，不运行逐点停车观察。最终仍要求新鲜静止反馈；遇到门禁异常时锁定零速并取消整条路线。

新鲜当前位姿到首点及相邻点间距离均限制为 `(0, 3]` 米，总请求折线不超过 10 米。终点距当前起点必须大于 10 cm，防止闭环起终点重合时提前满足终点检查。客户端同时要求新鲜地图反馈按顺序经过全部中间点；Nav2 成功但缺少经过反馈仍判失败。`route_length` 记录请求折线，实际 Nav2 避障路程可能不同。行为树在 10 cm 内移除已通过的中间点，持续重规划整条剩余路线，仅保留一次清图恢复。终点朝向决定最终停车朝向；中间点朝向不会强制逐点停稳。转弯仍可能减速或原地调整。

守卫是唯一最终速度发布者，校验候选发布者、底盘订阅者、原始命令/odom/scan 时间和坐标系。上游使用带时间戳速度；实车末端转换为现有固件使用的 Twist，仿真末端保留 TwistStamped。仅在配置健康且有新的有效候选时放行。硬故障停机需要显式 reset 及新鲜零速候选；记录写盘失败也会阻止运动。宽松档的普通时间异常按下文自动恢复。板端 watchdog/旧指令拒绝是否生效仍需单独验收。

平滑器在停止时会保留原输入时间戳；过期但有效的全零指令只保持空闲停车，不触发永久误锁。过期非零、未来及无效时间戳仍拒绝，绝不将旧指令重打为当前时间。

Collision Monitor 的 `stop_pub_timeout=3600` 延长停车后的零速输出窗口，使新的上游零速能够到达守卫的 reset 检查。它不延长非零命令有效期：最终守卫按所选时间档检查命令过期，默认 0.25 秒，宽松档 0.35 秒。reset 仍要求新鲜零速和健康传感器。恢复时以有限频率发布零速，不要由收到零速的回调再次无节制发布。

## 实车时间抖动档

默认 `timing_profile:=strict` 保留原有 250 ms 命令和里程计门限。用户可明确选择 `timing_profile:=tolerant`；本次实车运行已按用户要求启用。其命令与里程计门限为 350 ms，雷达仍为 500 ms。

超过门限立即输出零速并丢掉旧命令。短暂抖动恢复后，连续健康 200 ms 才结束暂停；随后必须收到新的候选命令，接收序号和源时间都需晚于恢复边界。

宽松档区分已解锁和正在运动。只有实际放行非零命令，或新鲜原始里程计仍报告运动，才进入运动状态。恢复空闲需要新鲜零速候选，以及在最后非零输出之后收到的新鲜静止里程计；该里程计的源时间不得早于该输出。单条后到的零速不能提前认定车辆已停稳。

宽松档的普通过期、时间提前、断流、暂时无法查询激光 TF 及 Collision Monitor `invalid source` 都进入可自动恢复的零速暂停。静止和运动使用同一恢复政策，不再因超过两秒而永久锁存。数据和 CM 来源恢复后，连续健康 200 ms，再接新的有效候选。旧候选不会重放，源时间戳不会被改成当前时间。

TF 临时故障按异常类型识别：查询、连接、外推及查询超时。记录独立的 `tf_issue` 和具体原因；非法扫描不会被临时 TF 故障掩盖。错误坐标系、非有限变换及非法参数仍属于硬故障。

非有限时间、非法数据、发布者冲突、记录器故障和人工停车仍需要显式复位。严格档行为不变。诊断报告 `recovery_policy=auto_resume`、`hold_escalates_to_latch=False` 和 `hold_timeout_s=none`。暂停开始及自动恢复分别写入触发记录；恢复记录包含原因和持续时间。

该调整避免常见链路异常演变为人工解锁流程。它不扩大车体、速度或碰撞距离，也不证明主控无线延迟已修复。新逻辑的部署及新 RViz 目标实车验收见任务进度。

```bash
ros2 launch tools/fishbot_passage.launch.py \
  ros_domain_id:=0 allow_real:=true execute:=true \
  timing_profile:=tolerant output_dir:=/tmp/fishbot-real-session/passage
```

独立守卫使用 `--timing-profile tolerant`。启动器会监督守卫退出；切换档位时先停止当前任务，再重启该导航入口。诊断话题报告有效档位与全部时间限值，复位成功后等待新目标。RViz 配置已包含顶部的 2D Goal Pose 工具，向 Nav2 监听的 `/goal_pose` 发布地图目标。

宽松档的默认单点行为树保留当前目标。遇到 TF 错误或代价地图更新超时，等待一秒后重新规划，最多等待五次。普通无进展、无路径及碰撞仍最多清图一次。每次尝试清零旧错误码；取消和新目标会中断等待。五次等待包含额外调度时间，不能当作严格五秒总期限。用尽重试后该目标明确失败，但时间暂停不会留下永久锁；已经失败的目标不自动重放。

这个默认树用于 RViz 单点导航。显式指定其他行为树的客户端继续使用其所选树；不能据此声称所有巡逻入口都已采用相同恢复政策。

## 一份外廓、两种距离处理

[官方模型参数](../tools/config/fishbot_model_geometry.yaml) 保存出处、固定版本和哈希。外廓覆盖直径 20 cm 的圆车身及左右车轮，最大宽 24 cm；另加 5 mm 建模余量。Nav2 两张代价地图、碰撞区域和离线回放都从这一文件生成。

- 靠近外廓约 5 cm 的区域触发限速，直线速度最多 0.03 m/s，不直接按“大矩形”停车。
- 硬停车区域覆盖外廓及当前速度档在 0.3 秒内的运动范围，包括转向扫过的角；这是设计时域，尚不是实车制动距离标定。
- 另有 1 秒预测接近减速；自由空间最大 0.08 m/s。
- 单个有效激光点仍可触发碰撞停车，保留细腿障碍。未知/过期数据不能被当成可通行。

不要直接启动 YAML 模板；启动器会先生成共享几何、统一时间配置及速度重映射。旧 `fishbot_guarded_mapping.py` 参数保留，避免两套入口含义混杂。

局部滚动代价地图使用实时激光障碍层和膨胀层，全局代价地图保留 SLAM 静态层。实车续建时，局部静态层曾把旧图占用格投到当前车轮外廓边缘；原生 Nav2 碰撞检查和实时点云给出不同结果。关闭局部静态层后，实际局部代价地图的当前足迹及剩余短路径通过检查。此调整保留 2.5 cm 局部分辨率、完整足迹、5 mm padding 和所有传感器时间检查。

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

## 实车入口

`fishbot_passage.launch.py` 不启动雷达、底盘、SLAM、AMCL 或地图服务器。实车需沿用已有传感器/SLAM，以及新鲜的 `map→odom→base_footprint`。启动前确认没有旧遥控/导航直接发布最终 `/cmd_vel`，底盘 node 名匹配模型配置；守卫会拒绝重复发布和错误接收端。

启动参数明确选择 `ros_domain_id:=0 allow_real:=true use_sim_time:=false execute:=true`，且指定源码 Git 根之外的绝对 `output_dir`。目标客户端也必须显式使用 `--domain 0 --real --execute`。这些开关只表达执行意图，不代表先前实车时钟/转角问题已经修复。2026-10-08 已执行该入口；短段成功与后续碰撞、时间变换中止分别保留证据，不能据此声称完整通道已通过。

在当前传感器与 SLAM 环境中运行地图目标，例如：

```bash
python3 tools/fishbot_passage_goal.py --domain 0 --real \
  --target 0.5 0.5 0.0 --timeout 60 --execute \
  --output /tmp/fishbot-real-session/room-goal.json
```

这些是示例坐标，执行前必须替换为当前地图中核实的目标；输出须为新文件。

把核实过的地图路线保存在私有 JSON 文件后，一次执行：

```bash
python3 tools/fishbot_passage_goal.py --domain 0 --real \
  --route-file /tmp/fishbot-real-session/route.json --timeout 180 \
  --execute --output /tmp/fishbot-real-session/route-result.json
```

路线检查和动作客户端不会填补地图未知区域。现场导航仍由完整足迹、实时激光、Collision Monitor 和最终命令守卫约束。连续入口的离线解析、边界、Jazzy 消息序列化和取消/停车回归通过；完整实车结果以任务进度为准。

## 停车记录和图

事件保存于 `<output_dir>/command_guard/trigger-*.json`，包含原生时间、接收时间、命令、odom、激光、运行时 TF、共享几何、发布者归属、当时区域和最近 40 条输入。先发布零速，再排队写盘；目录 0700，文件 0600。扫描/地图/日志留在私有输出目录，不入 Git。

Collision Monitor 的状态消息没有触发扫描编号和时间戳，因此事件是**状态回调时最近收到的数据及其历史窗口**，不能宣称恰好就是 CM 内部那一帧。RViz 显示停车时扫描与区域，JSON 保留该关联限制。

```bash
python3 tools/fishbot_passage_replay.py --help
```

回放生成 JSON、SVG 和 HTML，逐点区分硬碰撞、预测碰撞、限速区与观测可通行。历史扫描缺帧名时必须显式记录 `--assume-scan-frame laser_frame`；未知 TF 返回 unknown。新事件使用保存的实际 3D TF，并重算点坐标作一致性检查。离线 clear_observed 只代表该帧没有命中，不能替代完成过门。

碰撞事件默认采用保存的上游速度输入来重算区域，并同时保留停车后的候选零速与记录区域。它们可能因回调顺序不同而属于不同瞬间；不能拿停车后的零速反推碰撞原因，也不能将重算结果称为精确同步触发帧。

最新验证和待办见 [任务进度](../plans/fishbot-real-autonomy-20261005/progress.md)。
