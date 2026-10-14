# Findings

## 已核对的项目边界

- 仓库为 FishBot 独立 Git 根；规划前 HEAD 为 284e7c809a3d0ef58dbbf52e1c0731c517f608af。
- PROJECT.md 和 docs/COOPERATION.md 已声明理想信标没有噪声、遮挡或丢检模型。页面相机画面不等于视觉定位参与控制。
- 现有完整运输与 Arena 执行各有独立验收；视觉停靠的规划与实验必须分别接续。
- 固件 release.sh 是原有未提交保留项；本轮不执行或提交。

## 研究来源与职责

根研究仓库 ros2 的 plans/robotics-research-20261014/REPORT.md 要求 FishBot 承接视觉停靠规划，并核对多工位路由与语义观测的收益。该报告保存研究排序，不替代本项目实现验收。

root 维护本计划、项目索引和交付；根研究协调者维护研究总表与 Drive 快照。本轮不编辑根研究文件。

## 已核对的源码合同（规划基线）

本表记录P0实施前的合同；当前观测入口与频率见末尾“P0实施中的实际变化”和progress。

| 入口 | 当前事实 | 后续缺口 |
| --- | --- | --- |
| [StationBeacon](../../tools/cooperation_sim.py) | 真值派生相对位姿，1m范围，10Hz，base_footprint，原源时间 | 无噪声、遮挡、丢检或RGB识别 |
| [update_station_localization](../../tools/cooperation_bridge.py) | 只接受 idealized_truth_derived=True、匹配 scene/manifest 和唯一 cooperation_physics 发布者 | 新模式、传感器所有者和不确定度合同尚未实现 |
| 同一定位函数 | 接收龄不超过0.5s；源龄−0.1至0.25s；AMCL更新间隔0.3源秒，三项协方差固定0.0001 | 不能用固定理想协方差代表真实视觉误差 |
| [prepare](../../tools/cooperation_prepare.py) | 原生1.3.13 SimpleNonChargingDock，外部PoseStamped，检测超时0.5s、filter_coef=1、检测阈值0.02m | 仅DockRobot approach；max_retries=0，不支持resetApproach/UndockRobot |
| dock_at_station / execute | 独立staging导航；原生停靠60s墙钟；成功后另验实际位置≤0.04m、偏航≤0.05rad | 原生成功不能代替完整装载运输 |
| [ArmPlanner](../../tools/cooperation_arm.py) | 复用SO101 solve_pinch_ik、plan_joint_path、plan_transport、CollisionChecker | 冻结本机只读依赖；不用理想停靠位姿替代实际车体与接触快照 |
| [source_modules](../../tools/cooperation_scene.py) | 校验实际SO101规划模块来源 | 远端基线不足以唯一复现本机依赖，实际SHA须保留 |
| [ContinuousEvidence](../../tools/cooperation_core.py) | 重复源样本不增长连续时长；回退或间隔>0.15s重置 | 保持原门槛，不用墙钟轮询次数代替连续观测 |
| cleanup | 6s内取消原目标，确认终态、car_hold、0.7源秒连续静止、guard禁用新鲜ACK | 超时保留unknown，不重发或自动解锁 |

## 相机与采样

cooperation_sim.py 的物理步进500Hz；状态/odom50Hz，scan/beacon10Hz。physics.jsonl每状态样本写入并flush；LoopTiming慢事件尾部只有32项，附带淘汰计数，不是全量慢事件日志。

FrameWriter只保留最新待渲染快照。当前总览相机960×540、2FPS，帧绑定scene/episode、仿真与墙钟时间。它不是车载标定相机，也不是完整训练图像序列；内外参、标记、RGB检测和动作采用时间均待接入。

## 独立 oracle 的实际归属

根缓存为 ~/.cache/fishbot/。下列文件现存，root本次独立重算SHA；仅作为本机规划依据，不复制原始资料或上传日志。

| 缓存相对路径 | 本次SHA256 |
| --- | --- |
| cooperation/session-20261014/oracle/observer.py | cf315731f102c26774e3a9eee77be11a0f8f87357b775739e37e637a8c13abe9 |
| recursia/full-20261014-a640db0f0a/oracle/repeat-observer.py | 788383af86568da7d5ddfec6d37e7b6285a08b2ec01b1f3ec095e4c8914c9058 |
| recursia/full-20261014-a640db0f0a/oracle/repeat-base-observer.py | 9bb7be2cc2f8d9dad099533fea91b8d457a55fe5ab4f06969a0c07f21c227088 |

observer.py包含physical_sample、full_score、cancellation_score、observe/score和--score-only。追加评分复用原K判据，并核对episode、原生时间窗、clock/sequence/physics_steps、零任务内reset和持续交接。它们尚不是仓库内可复现入口；后续P0先审查依赖与最小迁入范围。

tools/fishbot_cooperation_oracle.py不存在，初次按该猜测路径检索失败；已改查实际缓存和计划来源。现有 [stack-gate](../../tools/fishbot_stack_gate.py) 不消费车臂或视觉结果，尚不能直接作为新计划的晋级门禁。

## 标准入口审计（规划前）

SpecMesh v1.1。README、PROJECT、AGENTS与ARCHITECTURE存在；CLAUDE.md和docs/DECISIONS.md原先缺失。README仍写Arena等待GPU/许可，与已完成的Arena进度冲突。本轮只补启动入口、真实架构决定、当前状态与渐进链接，不改执行源码。

## 未核实与验收边界

基线覆盖数量、seed面板和预算待首次实施前预声明；扰动幅度与统计门槛根据基线测量，在候选对照前冻结。视觉检测器与标定误差待后续核实。本次不把研究REPORT的Route Server/SAM3源码存在当运行收益，也不改根研究排序。计划建立、受扰实验、实际RGB停靠与完整运输分别验收。

## P0实施中的实际变化

用户要求开始后，新增cooperation_perception.py纯合同；source/episode/seq、完整协方差PSD与地图传播在转发前校验。producer使用标准位姿/诊断，本桥成为唯一原生PoseStamped发布者。ideal旧定位参数保留，vision模式不会创建假视觉生产者。

独立oracle已最小迁入仓库。原K的9项核心函数AST保持；附加既有episode/native/reset和连续交接/载物臂状态检查，不导入控制侧评分helper。旧118成功与旧失败分别重放保持通过/失败；原件不改，不能冒充新ROS结果。

Jazzy diagnostic_msgs5.3.8的DiagnosticStatus.level实际为单字节bytes；适配兼容ROS真实值与有限纯测试int，拒绝bool或未知级别。两份标准消息必须具有完全一致的header源时间与frame。实际ROS发布/接收已由隔离120确认，原生完整任务仍继续验收。

首次完整任务的取消通过，后续Dock因接收龄约0.50227s失败；source-age只有0.08s。独立流式对照153–159源秒61帧，源最大间隔0.1s，全部与生产端匹配；同stamp state生成循环gap0.56958s，转发接收gap0.58131s，clock/physics却仍低于0.14s。证据支持低RTF下10Hz源采样跨过0.5墙钟门槛，不支持网络/配对漏帧解释。

修复边界：把真实工位测量从scan周期解耦，复用既有50Hz状态发布；不修改原始时间、门槛、模型或评分。每次state读取只读缓存，真正的新测量在发布周期执行一次。新的周期声明与采样/原生验收分别确认，不能从旧失败推断修复成功。
