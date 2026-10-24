# M2：接管证据与最小补录合同

本片接续[原24输入数值覆盖](DRONE_RECORDED_STATE.md#显式a合同的原24输入覆盖2026-10-25)。数值覆盖已经完成，下一项补齐候选到控制器之间的可观察链路。本文是离线合同，不解除drone c866441冻结，也不实现控制通道。

## 当前确实有什么

源为原748回合，执行源c866441。`drone-handoff-evidence.py`复用现有`recorded-tracking.json_rows`，只读原`request.json`、`report.json`、`ego/trajectory-events.jsonl`和`telemetry.jsonl`。
它按原task/goal/trajectory三元组关联，再检查接收、命令、reference和录制的原sim先后关系。没有最近时间吸附、补ID、重标起点、曲线重解或控制调用。
此读取器不解析clock通道，先后检查只针对legacy sim数值；epoch对应仍明确未验证，不因此建立跨时钟或实际接管资格。

| 原轨迹ID | 有身份的发送侧PVA reference快照 |
| --- | ---: |
| 1 | 1 |
| 2 | 10 |
| 3 | 10 |
| 4 | 10 |
| 5 | 2 |
| 6 | 1 |
| 7 | 4 |
| 8 | 0；task/goal原本为空，继续未归属 |

共8条曲线记录，7条有本地task/goal身份；263条非空reference中，38条PVA快照可关联这7条曲线，225条position引用缺对应身份，不补为轨迹样本。
快照不是逐指令日志，重复快照也不按发送次数计。元数据/时间关联没有检验PVA与曲线逐值相等，更不建立控制器消费资格。
原任务报告仍为failed、landed=true、disarmed=true；这是历史记录，不是本轮新飞行或新落地。

## 三种回执必须分开

| 层级 | 当前来源 | 证明范围与缺口 |
| --- | --- | --- |
| sidecar曲线接收 | [sidecar.py:479](/home/muqiao/dev/ros2/projects/drone/ego/sidecar.py:479) | 保存已发布Bspline及源起点；不是所有未选候选。task/goal由active_goal补标，原Bspline没有这两个字段。 |
| 规划目标接纳 | [sidecar.py:958](/home/muqiao/dev/ros2/projects/drone/ego/sidecar.py:958) | HTTP202及ROS goal stamp门控，不是PX4回执。 |
| SDK返回后的本地reference | [flight.py:518](/home/muqiao/dev/ros2/projects/drone/flight.py:518)、[flight.py:648](/home/muqiao/dev/ros2/projects/drone/flight.py:648) | await返回后更新reference并补身份；sim时刻在await前取得，不能称返回时刻。 |
| PX4输入总线见证 | 当前未记录 | `trajectory_setpoint`发布只能证明输入抵达，不能证明位置控制器采用。 |
| 控制器消费/回退分支 | 当前未记录 | 普通飞行遥测、控制输出或运动跟踪不能单独填补。 |

冻结源码只读核对后，确认本地PX4 v1.17.0源码为d6f12ad；本片没有验证曾运行二进制与其一致。
其[MAVLink接收端](/home/muqiao/.cache/ros2-drone/PX4-Autopilot/src/modules/mavlink/mavlink_receiver.cpp:1034)在OFFBOARD下发布输入，使用本机HRT重打timestamp，没有保留候选UUID或原消息序号。
[TrajectorySetpoint.msg](/home/muqiao/.cache/ros2-drone/PX4-Autopilot/msg/versioned/TrajectorySetpoint.msg:8)也没有候选ID。不能要求原生消息给出一个不存在的UUID ACK，再把其他回执冒充它。

[MC位置控制器](/home/muqiao/.cache/ros2-drone/PX4-Autopilot/src/modules/mc_pos_control/MulticopterPositionControl.cpp:438)读取后仍检查启用时间、状态有效性，可能调整EKF reset、起飞和地面接触输入。
[update失败分支](/home/muqiao/.cache/ros2-drone/PX4-Autopilot/src/modules/mc_pos_control/MulticopterPositionControl.cpp:574)可能沿用200ms内旧有效输入，或改为failsafe。
[vehicle_local_position_setpoint输出](/home/muqiao/.cache/ros2-drone/PX4-Autopilot/src/modules/mc_pos_control/MulticopterPositionControl.cpp:600)含PID修正且重打输出时间，没有原输入身份和分支结果。监听它是更深一层的见证，仍不是逐候选采用ACK。

## 已有、可派生、必须补录

| 对象 | 已有 | 可派生 | 必须补录或验证 |
| --- | --- | --- | --- |
| 状态 | 原MCAP理想Gazebo PV、source stamp、录制时钟夹逼、部分FSM消费PV | 因果PV预测与经验误差；必须保留模型标签 | 实际控制状态的源/到达/消费时刻、frame、有效性及A/J来源/误差合同。PV差分不是实测A/J。 |
| 候选 | 已发布Bspline ID/系数/起点；离线MINCO原请求与完整硬审计 | 曲线相位PVA/J、原起止、各轴停止、连续极值 | 候选产生/拒绝事件及与父曲线、边界状态、地图版本的关联。不得把离线variant ID当已发送候选。 |
| 地图 | 深度/位姿/clock、局部融合和阈值穿越见证 | 已存局部格事件及年龄；缺失格仍未知 | 审计时完整known-free/occupied/unknown表示、revision、坐标/膨胀规则、有效范围与预测依据。freshness stamp不是revision。 |
| 终端 | 多项式零V/A/J；理想fixture的额外.5秒窗口 | 末端位置与有限窗口到期 | 末端体积、有效时段、保持/后续动作条件；.5秒fixture不是悬停不变集。 |
| 提交 | 稀疏post-await reference、command stamp、原点origin | 用原origin做位置ENU→NED；V/A只换轴和符号 | 每次调用的序号、原候选相位、ENU和实际NED payload、mask/yaw、开始/返回时钟、结果/错误。 |
| PX4 | 原报告模式和任务级运动 | 不能从上述值唯一反推逐候选采用 | 原生输入、控制使能/估计reset/有效性、控制输出及回退分支的同周期见证；运行二进制身份。 |

IMU给出的比力不能直接填作场景ENU加速度。若采用IMU或估计器输出，须记录姿态、重力处理、坐标转换、滤波/延迟和有效性；J若由差分取得仍须标模型。当前不预设传感器误差界。
已有原包没有完整known-free地图、未来安全体积或终端区域。把`voxels=[]`或1138条局部阈值事件转换成全图自由空间，会伪造资格，本片不做该转换。

## 最小事件字段与记录位置

复用原任务目录、JSONL、报告与MCAP，不新增服务、认证、调度器或状态数据库。事件缺失只产生该候选的诊断缺项，不阻断其他任务或记录批次。
本地`candidate_id`和版本供人编辑与关联，不使用内容哈希锁。重规划/重解明确换版本；不要靠序号相同推断曲线不变。

| 事件 | 最少新增内容 |
| --- | --- |
| candidate_ready / candidate_rejected | task/goal/candidate ID与版本、父trajectory ID、原起点、PVA/J边界及来源、完成时刻、失败原因。 |
| candidate_audited | 同候选版本、硬门结果/拒绝列表、地图revision、审计时相位、状态来源、terminal覆盖；保留数值和占据拒绝两类原因。 |
| sender_rpc_started / sender_rpc_returned | 同候选版本、逐调用sample_seq、原sample时刻、ENU/NED payload、frame/mask/yaw、开始/返回时刻、结果。异常也落盘；不重发同任务掩盖超时。 |
| px4_input_observed | PX4 boot域timestamp、PVA/mask/yaw、OFFBOARD/控制使能、观测源与接收时钟。只称输入见证。 |
| controller_step_observed | 本周期状态sample时刻、实际使用输入的timestamp/payload、normal/old-input/failsafe/reset分支、update结果及输出timestamp。此观察点当前未实现。 |

公共上下文保留task、scene/frame、clock domain/epoch，以及host monotonic时刻。ROS sim、PX4 boot微秒和host时钟分别记录；只有有误差范围的对应锚成立后才比较跨域先后。
不要把本轮离线wall耗时加到历史sim，不要用记录到达时间覆盖原sample或调用返回时间。暂停和回退保留epoch变化，不允许换标签使旧候选变新。

PX4原生消息没有candidate ID。以后优先保留原生输入/状态/输出，再用发送payload、时序区间和本地sample_seq做旁路关联；多对一、重复或时间不确定时继续标ambiguous。
若要证明本周期究竟采用新输入、旧输入还是failsafe，还需控制器消费点的只读分支见证；仅增加桌面关联ID无法补足它。本轮不改PX4或飞行源码。
精确UUID端到端ACK不是现成能力。未实现消费点见证前，报告层级停在实际取得的见证，不把近似匹配、控制输出或跟踪结果命名为ACK。

## 验证入口与下一步

```sh
STOP_REPORT_ROOT=apps/fishbot-control-station/workbench-tools/output/drone-committed/748f910e-f0f8-4ecf-b2d5-22b7b15d57e6
python3 apps/fishbot-control-station/workbench-tools/drone-handoff-evidence.py --run-dir /home/muqiao/dev/ros2/projects/drone/output/measured-state-reanchor-flight-748f910e --output "$STOP_REPORT_ROOT/handoff-evidence-inventory-rerun.json"
cd apps/fishbot-control-station/workbench-review-tests
python3 -m unittest test_drone_handoff_evidence
```

旧流中的额外`passed/adopted/ACK`字段不会被当作消费证书。缺文件、坏JSON行、身份歧义和不合法时序局部报告；不补0、未来帧或最近身份。
当前只读关联报告为`handoff-evidence-inventory.json`，保存在原忽略目录，不提交原日志。原历史failed和落地/disarm记录原样保留。
17项新检查与原Replay8项共25项通过，无跳过。覆盖错task/goal、重复ID、时序/域外、NaN/超大JSON整数、畸形PVA、伪ACK和缺文件/坏行/坏UTF-8流的局部降级；输入保持不变。
根137项直接原文件读回通过，逐快照核身份/源行/时序/PVA形状，四份原源文件前后逐字节相同；`handoff-evidence-readback.json`保存结果。这些检查验证读取器，不验证飞行或采用。

Next/owner：根Codex先将上述公共上下文、事件关联和时钟歧义做成离线正反夹具，复用已有Replay审计/拒绝逻辑；不新写控制器，不改原硬门，也不靠旧原包伪造新采集字段。采集点和冻结边界分开，M2仍部分完成、M3不启动，动态闭环未过。
