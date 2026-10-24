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

## 六阶段离线事件夹具（2026-10-25）

`drone-handoff-event-fixtures.py`复用原`Replay`完整硬审计/剩余占据/终端检查和冻结`frames.py`转换。使用原#4/h=.1、zero_A_J尾段和原起点/盒/限；不重新优化，不生成新飞行数据。
每个夹具隔离一个候选、一个发送样本和一个消费周期。阶段为ready、audited、RPC开始、RPC返回、PX4输入观察、控制器消费观察。输入/消费事件不填写原生消息没有的候选UUID或sample序号。
跨域只接受`declared_fixture_correspondence`显式点对应区间。它不是实测校时结果，也不是通用时间转换器；原`clock_bracket`仅证明录制可用性，不能代替源事件时钟对应。

34个声明夹具期望全部吻合：6个一致、28个不成立、未评分0。六个正例分别验证以下行为：

| 正例 | 允许的行为 |
| --- | --- |
| normal | 同候选版本、原相位、当前地图、单个正常消费周期 |
| input_before_rpc_return | 输入先抵达，SDK随后返回；不强排两个并行环节 |
| sim_paused | host单调时钟前进而sim不变；保留原相位 |
| map_changed_and_rechecked | 新revision经原Replay复审仍安全；revision变化本身不拒绝 |
| native_resends_unique_consumed_timestamp | 多条原生重发按实际使用的raw input timestamp唯一关联 |
| rejected_new_candidate_keeps_original | 新提案被原门拒绝后继续原有效候选，不把拒绝当成全链中止 |

负例覆盖版本/body/采样相位串线、跨goal、缺/重sample、clock epoch和源时钟回退、缺对应锚/区间重叠、原生时钟改名绕锚、地图声明过期、终端不足/新占据、未知A、篡改系数、旧输入/failsafe/update失败、payload符号/frame不符、伪原生UUID、重复输入timestamp、缺消费见证及曲线已结束。
候选绑定至采样时`Replay.server.active`的实际body、ID、起点；仅绑定最初ready事件会漏掉中途换候选。新提案被拒但旧候选保留时，仍可记录旧候选的完整一致链。
PX4 boot域及epoch独立声明并必须与sim异域；不能将两条原生事件直接改名为sim、删掉对应锚后通过。区间不能证明先后时标ambiguous，不取中点。

payload按声明的MAVLink float32表示比较，仅用于关联，不修改原物理PVA、速度/加速度/高度或占据门。极端原点下两个ENU位置可能落入同一float32 bin；物理状态偏移仍由原Replay拒绝，不能把wire相等当作跟踪误差预算。
原selector已因状态、占据或终端拒绝时，payload关联标为未评分，保留原拒绝，不再制造附带的payload不匹配原因。坏case局部未评分并继续；NaN原夹具仅省略不可JSON化的嵌入，保留诊断并warning，不填0或中断整份输出。

14项新检查加原17项legacy和8项Replay，共39项通过，无跳过。根145项独立读回复用原Replay逐case重审，另核源不变、原起点/盒/限、NED三阶payload、原生无伪身份与原拒绝分列，全部通过。
审查实际复现的三处假阳性/输出缺口已修并覆盖：采样前换活跃候选、原生clock改名绕锚、NaN fixture阻断严格JSON序列化。忽略目录保存`handoff-event-fixtures.json`和`handoff-event-readback.json`。

```sh
STOP_REPORT_ROOT=apps/fishbot-control-station/workbench-tools/output/drone-committed/748f910e-f0f8-4ecf-b2d5-22b7b15d57e6
python3 apps/fishbot-control-station/workbench-tools/drone-handoff-event-fixtures.py --reanchor-report "$STOP_REPORT_ROOT/recorder-PV-reanchored-stopping-tails.json" --output "$STOP_REPORT_ROOT/handoff-event-fixtures-rerun.json"
cd apps/fishbot-control-station/workbench-review-tests
python3 -m unittest test_drone_handoff_event_fixtures test_drone_handoff_evidence test_drone_committed_replay
```

`fixture_chain_consistent`只表示声明夹具一致。所有行和总报告均保留`actual_execution_admission=not_performed`，动态闭环仍未通过。没有真实clock对应、完整known-free/终端或控制器消费采集，新事件合同不能从旧原包补出这些事实。
Next/owner：根Codex准备默认关闭、可审查的最小旁路观测补片，复用现有任务JSONL和PX4消费点；先给出精确diff及离线验证，不应用到冻结树、不启动仿真。停止扩同类数值/事件网格；真实闭环仍需后续解冻后的新采集。drone c866441、PX4 d6f12ad和GCOPTER e0444f6保持，M2部分完成、M3不启动。


## 默认关闭的观测补片（2026-10-25，未应用）

本片交付可审查diff，保持drone `c866441`、PX4 `d6f12ad`、GCOPTER `e0444f6`冻结。
[发送侧补片](../apps/fishbot-control-station/workbench-tools/patches/drone-handoff-sender.patch)针对现有`Flight.setpoint/goto`；[控制消费补片](../apps/fishbot-control-station/workbench-tools/patches/px4-handoff-consumption.patch)针对PX4 v1.17的`mc_pos_control`、消息注册和既有ULog。它们保存在工作台，不是已部署功能。

| 观测点 | 实际新增内容 | 默认及资格边界 |
| --- | --- | --- |
| sender | task、trace session、逐RPC序号；EGO调用已有goal/trajectory/source stamp；调用开始/返回/错误的host monotonic及分别采样的sim值；原ENU reference、origin和传给SDK的NED PVA/yaw | `DRONE_TRACE_HANDOFF`不等于`1`时不创建日志。开启后写任务目录`handoff-sender.jsonl`。source epoch仍未知，序号不是原生PX4序号；SDK载荷尚非MAVLink wire读回 |
| controller | 真正订阅更新的原始快照及available/updated；实际选用输入、原生时间戳、状态sample和输出PVA；primary/old/failsafe、update次数及成功位 | `DRONE_HANDOFF_OBSERVATION` CMake选项默认`OFF`。开启才发布`position_control_handoff`；原logger新增optional topic、interval=0。消息schema注册始终存在，不称整个构建不变 |
| provenance | 本轮前置failsafe生成与持续使用本地failsafe来源分别记录，last-valid来源随保存/旧输入切换传播 | `PRIMARY`只表示主路径，不推断外部发送者；`OLD_INPUT`也可能来自此前本地failsafe。raw缓存只在订阅真更新时覆盖，不将上轮内部改写值冒充原始输入 |

保持SDK参数、次数及原`reference`提交时机；错误/取消原样重抛。JSON/文件错误warning后继续原调用，不将观测失败变为飞行失败。
启用后同步JSONL会增加延迟，尚无延迟上界；uORB/ULog仍可能丢记录，不能因interval=0假定零丢帧。跨域clock对应、每个MAVLink ingress、原生发送者身份/候选版本、地图/终端与真实A/J资格仍未补齐。
控制器读取的是订阅最新值，不是所有接收事件；日志仍不足以建立逐候选唯一采用ACK。没有新MINCO执行器、控制器或安全接管行为。

[局部检查](../apps/fishbot-control-station/workbench-review-tests/test_drone_observation_patches.py)仅向临时副本应用补片。Python提取真实原/补片`setpoint`对照；C++编译真实原/补片控制块及消息字段，以替身依赖比较开关和分支。
11项检查通过、无跳过。覆盖两种发送模式、ENU/NED三阶值、异常/取消与I/O失败、无新订阅且原对象已改、没有raw、前置failsafe首算成功、连续两周期保留来源、第三算failsafe也失败，以及七组主/旧/无旧/失败计算序列。
原树`git apply --check`均过，未写原树。C++替身编译不是PX4全构建。初轮系统Python运行官方生成器时缺少`genmsg`，未安装依赖；当时uORB生成、真实头文件/模块链接及ULog在线记录未验证。随后已有隔离环境的构建结果见下节，在线记录仍未验证。

```sh
cd apps/fishbot-control-station/workbench-review-tests
python3 -m unittest test_drone_observation_patches -v
```

Next/owner：根Codex的临时副本官方生成/构建已完成，见下节。实际采集须另行解冻后执行，保留raw缺失/重发/clock不确定，不以新日志形式冒充实测闭环。
M2部分完成，M3未启动，动态闭环未通过。本轮没有ROS初始化、服务/仿真、控制、新飞行或落地。


## 官方工具链构建与清理（2026-10-25）

已有`/home/muqiao/.cache/ros2-drone/venv/bin/python`具备genmsg、empy、jinja2、kconfiglib及pyulog；原PX4构建缓存同样使用这个环境。系统Python缺genmsg是解释器选择问题，本轮未安装或更新依赖。
仅在新建临时目录复制原源码及Git元数据，排除原`build`，应用既有补片。使用官方`GIT_SUBMODULES_ARE_EVIL=1`保持现有子模块，不自动下载或更新；已初始化子模块无版本偏移。23个未初始化子模块未被本次目标要求，不声称其他板型和插件也能构建。

| 检查 | 新鲜证据 | 结论范围 |
| --- | --- | --- |
| 默认关闭 | 新CMake缓存`DRONE_HANDOFF_OBSERVATION:BOOL=OFF`；真实控制器编译命令没有该宏 | 补片的构建开关默认关闭 |
| 官方生成 | 构建日志包含uORB headers/json/sources/compressed fields生成，新消息头真实存在 | 消息格式与当前官方生成器兼容 |
| OFF构建 | `cmake --build ... --target px4 --parallel 4`完成1075步，最终链接`bin/px4`，exit 0 | 当前px4_sitl_default的px4目标可编译链接 |
| ON构建 | 同副本重新配置ON，编译命令包含`-DDRONE_HANDOFF_OBSERVATION=1`，真实mc_pos_control重编译，11步后链接exit 0 | 观测代码与当前真实PX4类型/模块链接兼容 |

OFF/ON产物经`file`读为带调试信息的x86-64 ELF，大小57529472/57533312字节。没有执行二进制，不以文件大小证明记录成功或实时开销。
两次配置均提示可选GStreamer插件依赖缺失；`px4`目标仍通过。不升级依赖，也不将此结论扩大到GStreamer视频能力。68.226s完整构建与9.114s增量构建只是单次记录，两者工作量不同，不做性能比较。

复验需先新建源码副本、排除原build、应用上节补片，并将`DRONE_BUILD_SOURCE`和`DRONE_BUILD_DIR`指向该副本。以下只配置和编译，不运行SITL：

```sh
export PATH="/home/muqiao/.cache/ros2-drone/venv/bin:$PATH"
export GIT_SUBMODULES_ARE_EVIL=1
cmake -S "$DRONE_BUILD_SOURCE" -B "$DRONE_BUILD_DIR" -G Ninja -DCONFIG=px4_sitl_default -DPYTHON_EXECUTABLE=/home/muqiao/.cache/ros2-drone/venv/bin/python
cmake --build "$DRONE_BUILD_DIR" --target px4 --parallel 4
cmake -S "$DRONE_BUILD_SOURCE" -B "$DRONE_BUILD_DIR" -DDRONE_HANDOFF_OBSERVATION=ON
cmake --build "$DRONE_BUILD_DIR" --target px4 --parallel 4
```

原忽略输出目录保存`handoff-observation-build.json`及`handoff-observation-build-logs.tar.gz`。归档五个成员全部解压读回后，已删除本轮临时源码、build/ccache及两份本轮/前轮生成辅助文件；移除目录分配空间1306947584字节（约1.217GiB）。文件系统可用空间由8566022144增至9872965632字节；这是收尾时观测，不当作受控性能指标。保留原源码、虚拟环境、旧构建、原遥测和必要新记录。
恢复日志时新建目录后解压，不需要恢复可再生成的整棵源码副本：

```sh
DRONE_LOG_DIR=$(mktemp -d)
tar -xzf apps/fishbot-control-station/workbench-tools/output/drone-committed/748f910e-f0f8-4ecf-b2d5-22b7b15d57e6/handoff-observation-build-logs.tar.gz -C "$DRONE_LOG_DIR"
```

Next/owner：根Codex等待用户明确解除“隔离仿真启动/无解锁采集”这一项冻结，再在独立副本做有限记录验证。原`check_minco_link.py`仅监听offboard_control_mode且不启动Offboard，不能直接冒称新增消费topic或PVA读回已通过；未采集/未激活/缺topic必须分别保留，MAVLink ingress与跨域对应仍待证。此许可不包含解锁、起飞或动态任务。
M2仍部分完成，M3未启动，动态闭环未通过。补片未应用原冻结树，原drone/PX4/GCOPTER源码保持清洁。本片没有新增算法、训练、ROS节点或控制调用。
