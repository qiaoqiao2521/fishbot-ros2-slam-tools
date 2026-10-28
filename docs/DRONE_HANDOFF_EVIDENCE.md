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

Next/owner：用户已明确解除隔离启动及无解锁采集限制，本轮实际读回见下节。原`check_minco_link.py`只有模式掩码，不能替代新记录；MAVLink ingress与跨域对应仍待证。许可不包含解锁、起飞或动态任务。
M2仍部分完成，M3未启动，动态闭环未通过。补片未应用原冻结树，原drone/PX4/GCOPTER源码保持清洁。本片没有新增算法、训练、ROS节点或控制调用。


## 隔离无解锁实际读回（2026-10-25）

用户回复“解除”，授权独立副本启动和无解锁采集。直接复用原Flight/SITL启动预检、遥测、清理及官方PX4 listener/logger；新增[有限采集适配](../apps/fishbot-control-station/workbench-tools/drone-disarmed-observation.py)，未修改原冻结树。
默认不请求Offboard；`--request-offboard`显式开启未解锁模式对照。它只切换模式，不调用arm或起飞。空program、preflight_only及拒绝land/return_home/recover的子类入口阻断运动路径；任何已收到的armed=True或armed流结束均锁存，停止继续发送。发送4s、原生查询3s、整段240s有界，超时取消后仍兜底关闭所属SDK/SITL并保留清理错误。

| run_id | 实际范围 | 发送/原生证据 | 保留结论 |
| --- | --- | --- | --- |
| 3852b3b0-7f11-41c0-ba2b-3b716b857284 | 首次隔离启动 | EGO缺trimesh，0发送；4个所属PID退出 | 启动失败，未采集；不是算法失败 |
| b913b0ab-be8e-4b7f-aef4-a03da63d4920 | 未解锁Loiter对照 | 18调用/18返回，36事件；ULog 962控制行，外部PVA兼容raw为0 | 模式掩码可变化，外部PVA未进入当前原始输入 |
| b34abfea-ff8e-4072-9063-5fb630a5a950 | 未解锁Offboard对照 | 18调用/18返回，36事件；953控制行，6组PVA全找到兼容raw，共74行 | 输入链路读回成立；实际使用值仍被地面保护改写 |

首轮仅因独立cache遗漏已有mesh-libs，未安装新包；复用原缓存trimesh 4.11.2并在启动前用实际sidecar解释器检查rclpy/numpy/trimesh/rtree/collada，随后两轮启动预检均ready。每次换新UUID，旧失败保留；只在上轮终态及所属PID退出后启动下一轮。
两轮成功采集分别有43/31个armed=False、0个True，连接建立前4/10个未知保持未知。原生vehicle_status分别19/21条，均为arming_state=1；命令日志均无400（arm/disarm）。模式对照的nav_state含4和14，记录两条176模式命令；没有解锁和起飞。

独立读回使用官方pyulog和冻结frames.py。两轮各18份发送记录的ENU/NED位置、速度、加速度及应用侧yaw转换一致。Offboard轮按MAVLink float32逐轴比较完整PVA，控制raw中6组均兼容，计数7/12/13/13/13/16，总74；这包含缓存/重发，不是74个调用或唯一ACK。相同PVA的原trajectory_setpoint日志仅3行，对应其200ms日志间隔；原生yaw读回相对解析转换最大误差4.371139e-8rad，仅报告观察值，不新增物理容差。
两份ULog的dropout记录均0，不代表每条uORB发布都被完整记录，也不证明未来实时性。

**地面保护必须单独解释。** 两轮全部控制行分别962/953，均used_branch=PRIMARY、update_success_mask=1；但used位置/速度为NaN，used加速度是NED `[0,0,100]`。固定PX4源在not_taken_off/ground_contact分支故意这样改写，确保零推力。这不是飞机实测100m/s²，不应混入空中轨迹A≤1的算法判据，也不能以PRIMARY/更新成功冒称外部PVA被执行。
已录Gazebo独立真值窗口XYZ跨度约2.105e-13/1.829e-19/1.001e-6m。PX4 pose全记录中约5m的跳变来自初始场景原点校准，不是实际位移；读回已分列，不改变原坐标或飞行判据。
原生候选UUID/逐调用身份仍不存在，source epoch及跨域clock未校准，actual adoption/flight_accepted仍未证明。真实A/J、时间有效地图/终端、跟踪与动态闭环资格仍缺。

本轮10项局部检查通过、无跳过。覆盖默认无模式请求、显式未解锁模式请求/退出、失去未解锁/流结束锁存、原流值、SDK pending超时、禁止运动恢复、超时击中父类finally后的SDK兜底和关闭异常仍保摘要。独立审查发现并修补这些路径；末次仅补流结束后不发mode-stop的条件，正常采集路径不变，新增负例已测，没有为未触发分支重跑仿真。
Loiter轮EGO退出日志出现publisher context invalid，Offboard轮未复现但未修复源码；Offboard轮SDK有两条176额外ACK警告，根因待核。原生状态已证明模式进入，不能忽略警告，也不能把整个采集标成飞行成功。

原忽略目录`workbench-tools/output/drone-committed/<run_id>/`保留request/runtime/preflight、sender/native/telemetry/truth、模型定义、原ULog/深度及失败报告。最新轮另有`independent-readback.py/.json/.log`、`source-build-info.json`、`cleanup.json`及两份实际observer patch归档。
独立副本及其源码/build/ccache共1310040064B已删除；两个临时辅助文件及三个生成etc链接已清理，保留原cache和所有原始实验记录。可用空间18664943616→19973898240B仅为收尾时全盘观测；12个所属PID、其进程组及14546/20066/8792监听均无残留。清理后再次读回所有新记录成功，原drone/PX4/GCOPTER仍为c866441/d6f12ad/e0444f6且clean。

```sh
cd apps/fishbot-control-station/workbench-review-tests
python3 -m unittest test_drone_disarmed_observation -v
cd ../workbench-tools/output/drone-committed/b34abfea-ff8e-4072-9063-5fb630a5a950
/home/muqiao/.cache/ros2-drone/venv/bin/python independent-readback.py
```

重新采集时先按上节重建独立PX4副本与ON构建，向独立drone副本应用sender patch，设置DRONE_CACHE指向副本cache，复用原venv/mesh-libs与DRONE_EGO_WS。新output目录的collection-setup.json至少提供新run_id。从已source ROS Jazzy的shell运行采集适配，传入--drone-source、--output和独立实例/端口；只有显式--request-offboard才请求模式。原运行目录不重派、不覆盖。
恢复observer补片可在新目录解开applied-observer-patches.tar.gz；大副本按固定源＋补片重建，原ULog可直接由pyulog读取，无需恢复整树。
Next/owner：根Codex核原生时钟来源/点对应区间、MAVLink ingress与地面改写标记，保留未采用结论；本片不授权后续解锁/起飞。M3无解锁输入读回片完成，完整M3/动态闭环未完成，M2仍部分完成。


## 原生接收、时钟与地面改写读回（2026-10-26）

本轮继续既有隔离启动/未解锁许可。新增[接收观测补片](../apps/fishbot-control-station/workbench-tools/patches/px4-handoff-ingress.patch)，先应用前节consumption补片，再应用本片；仅临时副本使用。原drone/PX4/GCOPTER保持c866441/d6f12ad/e0444f6且clean，未解锁、起飞或更改算法/物理门槛。

**源码时钟边界。** 固定PX4 `GZBridge.cpp:331–345`从同分区Gazebo Clock的sim字段取值；首回调设置REALTIME，后续设置MONOTONIC。`platforms/posix/src/px4/common/drv_hrt.cpp:106–110,484–490`在ENABLE_LOCKSTEP_SCHEDULER下直接读写锁步时钟，scheduler直接赋值，微秒转换会截断。真实编译命令已确认该宏。故PX4 HRT在这个运行配置中由Gazebo仿真时钟驱动；同tick可相等，不承诺严格递增或与宿主同步。
固定`mavlink_receiver.cpp:1034–1151`的LOCAL_NED处理不使用wire time_boot_ms；地址/forward/frame/force/PVA检查后发布offboard_control_mode，仅nav_state=OFFBOARD时调用trajectory_setpoint发布。两个stamp均取本地HRT。SDK host monotonic、wire发送方boot时间、PX4 HRT与异步缓存sim必须分列；没有建立跨域实际锚点或延迟上界。

补片默认`DRONE_HANDOFF_INGRESS_OBSERVATION=OFF`。开启后在原handler旁路记录源sysid/compid、8bit报文seq、receiver channel/局部序号、wire时间/掩码/原始PVA/yaw、解码PVA、nav_state、接收/结束/原发布HRT。RAII保留提前拒绝分支，不改变原检查、转换、发布次序或返回；PUBLISH_CALLED仅指原发布被调用，不是订阅消费ACK。receiver局部序号不跨对象生命周期，不能当候选UUID。
原consumption消息另加ground_state_evaluated、not_taken_off、flying_ground_contact、ground_override、rampup_acceleration_cleared，取自原生分支条件，不修改地面零推力或rampup规则。两开关均关闭时仍注册消息schema；ingress logger预留订阅，不能声称整个构建/资源占用完全不变。开启旁路的执行开销仍无上界证据。

| run_id | 实际结果 | 结论范围 |
| --- | --- | --- |
| 7242409e-7bb8-44c9-89e0-1c1baaff78b8 | 18开始/18返回，未解锁；listener三阶段可见ingress，ULog缺该topic，968控制行 | 日志链不成立，原记录保留 |
| adbbaa2d-6e06-4653-8ba9-ca158a04db20 | 修日志登记后新UUID；18开始/18返回，53 ingress、962控制行、40原轨迹行 | 26次新raw更新有单一记录内stamp＋完整PVA关联；仅已录原生链 |

首轮不是网络/算法失败：官方`LoggedTopics::add_topic`在optional且启动时orb不存在时不登记该订阅，logger早于首次SDK指令。仅将新ingress登记改为add_topic，复用原logger的晚订阅；不另建日志线程或强迫启动顺序。第二轮证实可写ULog。两轮实际应用的三份patch分别归档，旧失败不被新源码覆盖。
第二轮53条中21条MODE_NOT_OFFBOARD、32条PUBLISH_CALLED；源sysid245/compid190、channel1、frame1。position-only掩码2552共36条，PVA掩码2048共17条。六组SDK PVA各有wire兼容3/2/3/3/3/3行、controller raw兼容7/12/13/13/13/17行；ENU/NED三阶应用转换独立核对无误，26对关联的wire/raw yaw相等。缓存/重发不是新RPC，也不证明新候选。
原生发布stamp有4组重复，各2条。receiver序号已录范围11–69，内部缺13/32/38/51/63/66；ULog dropout记录0仍不等于全消息完整，不能确定每个缺号发生在哪层。346次新raw更新中26次相符、320次未关联、歧义0、同stamp但PVA不符0、未来接收候选0。未关联包含其他来源/窗口且可能有记录缺失，不判为320次外部指令丢失。
26对native接收到控制观测的HRT差为0–8000µs，handler内差均0；这是本次锁步分辨率下的仿真时间观察，不是CPU耗时、宿主端到端延迟或性能保证。wire boot时间2084206–2086419ms，native接收7264000–9432000µs，不直接相减。当前源route已核，跨域样本锚点/epoch仍未知。
第二轮962行ground_state_evaluated/not_taken_off/ground_override均true，flying_ground_contact/rampup清除均false；used P/V全NaN、A为NED[0,0,100]。26关联行也全在地面保护中，不能称外部PVA实际跟踪。原生arming_state两轮全1，400命令0；SDK False31/32、True0/0、连接前未知8/7保留。已录Gazebo真值窗口5.832–9.400/5.868–9.472sim内XYZ跨度均0；不扩大到记录前启动全过程。

[只读审计](../apps/fishbot-control-station/workbench-tools/drone-native-ingress-audit.py)仅计算native域差，保留所有stamp/PVA候选；歧义不选，未来接收记录单列排除，跨channel序号按各channel检查。缺ULog/topic写warning并保留未知，不制造空成功。它不发控制，不认定日志完整、唯一RPC采用或飞行资格。
27项局部检查通过、0跳过：原有限采集10项、新接收/地面补片10项、审计7项。新补片测试编译实际原/OFF/ON接收全函数和ground块，BODY_NED使用真实PX4 matrix头；覆盖地址/forward/frame/force/无PVA/Loiter/Offboard/位置-only、8bit回绕、同tick、观测丢失和12组ground/rampup组合。审计负例覆盖不同PVA、重复stamp、交错channel回退、未来接收及缺日志；不将局部编译替身视作整栈运行。
官方生成＋ON真px4构建1076步完成；修日志后增量构建完成，末次OFF真构建也通过，两模块编译命令均无观测宏。ON中LOCKSTEP及两个观测宏均确认。两轮原生读回由独立pyulog脚本重算，源码副本清理后再次成功。两轮SDK仍各有两条176额外ACK warning，根因未修；EGO context-invalid本轮未出现，不称此前问题解决。

恢复入口：原忽略`workbench-tools/output/drone-committed/<run_id>/`保存原始sender/native/telemetry/truth/depth/ULog/模型、构建日志、精确三patch归档及报告。最新adb目录有native-ingress-audit.json、independent-ingress-readback.py/.json/.log、source-build-info.json、off-build-info.json及cleanup.json。恢复补片到新目录并按原固定源重建；重新采集仍用新UUID，独立DRONE_CACHE、原venv/mesh-libs/EGO overlay，ON配置需另加`-DDRONE_HANDOFF_INGRESS_OBSERVATION=ON`。
已删本轮临时源码/build/ccache1310269440B（约1.22GiB）、三个临时辅助文件和四个生成链接；八个所属PID及其进程组无残留。可用空间5053059072→6363344896B仅为收尾时全盘观测。两份patch归档已逐成员完整解压读回，原cache与全部新记录保留。

```sh
cd apps/fishbot-control-station/workbench-review-tests
python3 -m unittest test_drone_disarmed_observation test_drone_ingress_patch test_drone_native_ingress_audit -v
cd ../workbench-tools
/home/muqiao/.cache/ros2-drone/venv/bin/python drone-native-ingress-audit.py output/drone-committed/adbbaa2d-6e06-4653-8ba9-ca158a04db20
cd output/drone-committed/adbbaa2d-6e06-4653-8ba9-ca158a04db20
/home/muqiao/.cache/ros2-drone/venv/bin/python independent-ingress-readback.py
```

Next/owner：根Codex核已有发送边界的候选样本身份、源有效期与SDK重发缓存，复用现有失效处理。因为PX4按每次接收重打HRT、忽略wire boot，新的raw stamp不能单独证明候选仍新鲜。先明确过期/暂停/恢复/撤销合同，再准备可审查的执行适配；当前不自动解锁或飞行。此接收/地面诊断片完成，M2部分完成、完整M3与动态闭环仍未验收。


## 候选有效期与SDK缓存核对（2026-10-27）

本轮只核现有合同与边界，未应用修复到冻结源。原drone/PX4/GCOPTER保持c866441/d6f12ad/e0444f6。未启动ROS、PX4/Gazebo或飞行；另用真实mavsdk-grpc 4.0.5和现有pymavlink搭建明确标注的本地协议测试端，不将其ACK当PX4接受。

### 已有保护与发送前窗口

[局部核对](../apps/fishbot-control-station/workbench-review-tests/test_drone_command_validity.py)通过AST提取冻结原方法，不导入Flight/ROS，不创建线程或服务。实际保留的合同如下。

| 层 | 固定实现的现有处理 | 不能据此推断 |
| --- | --- | --- |
| sidecar on_command | 必须有active goal、ACK、traj_id不低于floor且曲线已知，PVA/yaw有限；输出task/goal、sample stamp与曲线起止 | 原生SDK载荷具有这些身份或TTL |
| sidecar state | sample龄期>0.3s拒绝；曲线结束后>0.15s拒绝；到目标且V/A逐轴<1e-6允许goal_hold；clock wall超2s拒绝 | 返回的ready快照在HTTP等待结束时仍有效 |
| Flight.goto | HTTP返回后核task/goal及sample龄期[-0.1,0.5]；新goal先发position清旧PVA | 已重核source_end、取消状态或clock epoch |
| stop/newgoal | paused clock时stop仍能清active goal/setpoint/排队请求/ACK；新goal检查当前state，再清旧样本与ACK、抬traj floor | 已同步清掉SDK缓存 |
| recovery/land | 现有路径先用position替换PVA再做planner HTTP；land调用offboard.stop后请求降落；future-odom专用等待有await后输入复查 | 普通goto /state等待也有同样复查，或位置保持本身保证动态安全 |

两处发送窗口已通过真实方法的受控反例复现，尚未修复：
1. `flight.py:632–647`普通/state等待期间取消到达，返回后仍发一次PVA，下一轮才抛CancelFlight。不能把future-odom分支已有的post-await检查误说成不存在。
2. sidecar在10.15sim返回ready，sample stamp10.15、source_end10.2；HTTP返回时10.4，sample age0.25仍在Flight窗内，但曲线已结束0.2s，重新执行原sidecar.state会判trajectory_expired；原goto仍发送。缺口是发送前没有按新sim重核源期限，非所有龄期检查缺失。
另有两个时钟边界：小回退0.05s落在既有future容差内仍可发送，这只证明容差不等于epoch身份，不把容差本身改判为Bug；`land`的验证HTTP期间10→5后，旧now写入last_check_s，5.1/5.2不再触发原0.2s周期检查，须等追过旧节拍。后者为AST局部反例，不是实飞中发生的事件。
15项原方法检查中4项明确命名observed_diagnostic，绿色代表当前边界可复现，不代表已修复；修复时应翻转这些期望，不能长期将漏洞当目标行为。其余检查确认原过期/身份/大回退拒绝、goal_hold例外、暂停stop与newgoal处理，以及reference使用发送前stamp且只在RPC成功返回后提交。

### 真实SDK缓存与协议端读回

复用[官方同版Offboard实现](https://github.com/mavlink/MAVSDK/blob/v4.0.5/cpp/src/mavsdk/plugins/offboard/offboard_impl.cpp)及其头文件。PVA setter保存P/V/A，登记SEND_INTERVAL_S=0.05并立即发送；后续sender从缓存读取，每次重新填wire time_boot_ms。position setter移除旧类型周期任务、切到position掩码。stop/stop_async先stop_sending_setpoints再请求Hold；heartbeat watchdog在未处Offboard且经过3s宽限时停止，不是候选TTL。未在这些接口中找到source_start/end、task/goal/sample身份或源有效期检查。
新增[有限SDK诊断](../apps/fishbot-control-station/workbench-tools/drone-sdk-cache-probe.py)，只调用一次PVA setter、一次position setter和一次stop；协议端固定localhost、显式synthetic unarmed heartbeat/ACK，拒绝任何arm请求。未调用start/arm/land，无飞机、物理状态或真实模式验收。SDK进程日志再次确认v4.0.5；包元数据同版。不能由客户端127.0.0.1推断服务绑定：末轮ss实际见`*:56051`，退出后该监听已关闭；未改全局网络或SDK配置。

| run_id | 实际结果 | 资格 |
| --- | --- | --- |
| d03123f8-92c9-47ec-a8b8-daf3a7c7fe03 | cleanup之后JSON序列化遇到COMMAND_LONG中的NaN而失败 | 失败日志及官方源码保留，无结构化行为验收 |
| e92d0e9f-d10d-4b49-a81c-36f4186a1b38 | 单PVA RPC后稳定窗12报文/12 wire时刻/1 PVA；position后9报文mask2552；stop后0 | 真实SDK＋协议端观察，不是PX4消费 |
| 6dde3304-cd32-4b80-9cff-7d21e5f04147 | 补清理竞态与监听读回后，新UUID稳定窗11/9/0，masks2048/2552/无 | 同样机制复现，非时延或安全上界 |

观察窗故意排除每次RPC返回后前100ms，只用于区分稳定重发与过渡在途包，不是新物理容差。PVA阶段未再调用setter，等待0.65s；position等待0.55s；stop后等待0.4s，末次有效观察窗约0.3s。两轮均无400 arm命令，三RPC均返回；synthetic ACK不证明Hold在PX4成立。原生PX4接收重打HRT的结论沿用前节adb实测，不能将本轮协议时间换成PX4 HRT或sim。
初轮记录错误已修为非有限协议字段写null并保nonfinite_fields，未填0、未改控制值。两条COMMAND_LONG非有限字段被保留；SDK退出竞态/最终wait超时捕获为清理错误，摘要不再因此跳过。新增3项局部检查覆盖这两类真实诊断问题；总18项检查通过、0跳过，但其中4项仍是未修控制边界见证。
末轮SDK PID455546、前轮449011及不支持--version探测PID434536均退出，UDP49772/gRPC56051及前轮目标端口无残留。--version实际被该二进制当连接串，已关闭该自有探测，不以其退出码当版本成功；版本取实际SDK启动日志。已删除1242B临时路径文件；无新大副本/构建/渲染产物，原失败和必要小记录保留，不凭空声称释放GiB空间。

复验入口：原忽略`workbench-tools/output/drone-committed/6dde3304-cd32-4b80-9cff-7d21e5f04147/`下有sdk-cache-probe.json、sdk-cache-peer.jsonl、sdk-cache-independent.json、sdk-process.json、sdk-listeners.json、sdk.log、probe.log、source-provenance.json和cleanup.json。前两UUID在同级。官方cpp/hpp仅保留一份于失败UUID目录，后续provenance引用原件；不复制vendor源码入Git。重新采集使用新输出目录；真实SDK复验仍只对synthetic peer。

```sh
cd apps/fishbot-control-station/workbench-review-tests
python3 -m unittest test_drone_command_validity test_drone_sdk_cache_probe -v
cd ../workbench-tools
# Replace with a fresh local output directory; this does not launch PX4.
/home/muqiao/.cache/ros2-drone/venv/bin/python drone-sdk-cache-probe.py --output /tmp/drone-sdk-cache-new-run
```

Next/owner：根Codex准备独立副本、默认关闭的最小发送前复查补片：普通/state await后重核取消/操作状态，以及源期限和原goal_hold例外；复用现有错误/恢复入口，不新造lease服务或以SDK新stamp代源合同。另修回退后的降落验证节拍重置，保留原0.2s判据；epoch身份与SDK RPC等待期间失效仍需明确。只读核查片完成，原源码未改；M2部分完成、完整M3/动态闭环仍未通过。


## 默认关闭的发送前复查修复（2026-10-27）

用户要求“开始修复”，按既有独立副本/默认关闭范围完成[修复补片](../apps/fishbot-control-station/workbench-tools/patches/drone-command-revalidation.patch)。基线为drone c866441，仅改flight.py；未应用原冻结树。创建Flight时读取DRONE_REVALIDATE_COMMAND，只有字符串1启用；其他值默认保持旧执行行为，不在运行中动态切换。没有新增ROS节点、消息协议、SDK owner或物理阈值。

| 已修边界 | 开启补片后的行为 | 保留行为 |
| --- | --- | --- |
| 普通/state await后取消/操作变化 | 在任何PVA发送前再次查cancel/operator，以及原deadline、定位、scene和clock限制 | cancel始终检查；operator=False仍不响应返航请求；复用原CancelFlight/RuntimeError/恢复入口 |
| ready快照中的样本或曲线已过期 | 发送时再执行原sidecar的sample>0.3s、source_end后>0.15s规则；缺失/非有限期限给当前任务明确错误 | 原Flight[-0.1,0.5]门保持；增加的是原sidecar ready复查，不新设容差；末端位置达标且VA各轴<1e-6仍允许goal_hold，不盲信mode标签 |
| 降落验证节拍遇时钟回退 | 查询间回退立即恢复原周期检查；查询期间回退则不保存旧节拍，下一轮重验 | 正常0.2s节拍及原不安全通道处理不变，无新epsilon |

[局部验证](../apps/fishbot-control-station/workbench-review-tests/test_drone_command_revalidation_patch.py)只在TemporaryDirectory复制flight.py/frames.py/sidecar.py，apply --check --whitespace=error-all与语法编译通过；提取补片前后实际方法，无ROS/SDK初始化。18项检查通过、0跳过；主Agent与本对话独立审查分别运行同一最终模块。原取消/期限/降落回退反例在ON分支转为不发PVA/恢复复验，OFF分支与旧行为一致。
额外覆盖响应期间返航、定位/场景/clock/原执行预算失效、正常宽限、真正与伪goal_hold、无源期限/NaN/Inf、既有身份与龄期拒绝、正常降落节拍；6组期限判断直接与原Sidecar.state在同发送时刻交叉对照。sender观测补片与本片两种应用顺序均可通过并发送原PVA，不依赖前两份PX4观测补片。
本片没有改Flight.run的异常处理。源码调用链仍为CancelFlight→原取消分支、其他异常→原失败/恢复分支；此轮未执行完整Flight.run→recover集成，因此不以方法级检查证明恢复实际完成。

**仍未解决：** HTTP等待期间先前已接受的SDK缓存仍可能持续重发；PVA RPC已进入后才取消或到期也无法由发送前检查撤回，新测试明确保留这一observed_boundary。未来容差内的小回退没有被新增epoch身份替代；原-0.1s容差保持。降落回退修复只恢复复验节拍，不声称旧safe响应跨epoch仍有效，也不保证此前的动态悬停/回退净空。未新增SDK TTL或确定性备份控制器，M2部分完成、完整M3/动态闭环仍未通过。

复验与后续启用只针对新建独立副本，DRONE_REPAIR_COPY不得指向冻结原树。以下只应用代码/设置开关，不启动飞行：

```sh
cd apps/fishbot-control-station/workbench-review-tests
python3 -m unittest test_drone_command_revalidation_patch -v
# Set DRONE_REPAIR_COPY to an independent copy of drone c866441 first.
git -C "$DRONE_REPAIR_COPY" apply --check /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-tools/patches/drone-command-revalidation.patch
git -C "$DRONE_REPAIR_COPY" apply /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-tools/patches/drone-command-revalidation.patch
export DRONE_REVALIDATE_COMMAND=1
```

Next/owner：根Codex做Flight.run→recover的定向局部集成，核取消/期限异常是否按原入口替换缓存；不重复建同类网格，不解锁/飞行。原drone/PX4/GCOPTER c866441/d6f12ad/e0444f6再次确认clean。本轮无新服务、构建或大产物；测试临时副本自动回收，历史SDK/ULog/失败原件保持。


## Flight.run → recover 缓存替换核对（2026-10-27）

本轮只增加[定向回归夹具](../apps/fishbot-control-station/workbench-review-tests/test_drone_recovery_cache_chain.py)和交接，不修改补片或飞行行为。原drone c866441冻结；临时副本应用上一节默认关闭补片，在夹具中显式启用。提取真实完整run、recover、setpoint、stop_planner、localization_current、current_yaw、record_failure和block_recovery；连接、SDK/cache、暂停、观察、模式确认、落地结果和清理均为明确标注的替身。没有导入ROS、创建HTTP线程、启动SDK或仿真。

取消/期限主用例先让一个合法PVA进入fake cache，再在第二次/state响应注入取消或曲线过期；不是从空缓存起测。正常恢复前缀在观测边界主动拒绝，实际执行原blocked异常处理和run完整finally、写出临时report/telemetry/status。另有一组明确synthetic落地返回，只验证状态路由，不能作为落地或通路安全证据。

| 路径（原flight.py行号） | 本轮确认的执行器行为 | 仍不能确认 |
| --- | --- | --- |
| 取消1057/1063；期限异常1092/1097 | 进入同一原recover；已Offboard时907位置setter返回→908 /stop→909观察；调用载荷经真实frames转换为NED | 真实SDK是否接受、PX4是否保持或已落地 |
| 需要接管894–904 | hold返回→位置setter返回→start→OFFBOARD确认→/stop；未确认不写control_takeover | hold响应本身是否终止原模式或实际运动 |
| 定位失效888–889 | 先block，未发位置指令、未请求/stop；pause之前fake cache仍为旧PVA | 不能称这一路已清缓存；暂停仅适用于本仿真退路 |
| 位置setter未返回或抛错907 | 未返回时stop/pause/finally均未到；抛错后走blocked。接受前失败与接受后丢响应同为TimeoutError，却可有不同fake cache | SDK错误不能反推出缓存未变或已变；本轮未实测网络挂起 |
| 接管hold/arm状态失败896；start/模式确认失败898–899 | 前者未替换；后者位置setter已返回但未确认控制接管；都不进入/stop | 控制权与缓存替换不能合并成一个成功字段 |
| /stop失败689–694 | 先前位置setter已返回，保留WARNING再进入观察 | /stop只清规划器，不是SDK缓存协议 |
| blocked/收尾869–875、1184 | pause返回后才写simulation_pause_confirmed；pause/SDK清理失败留failed及错误，不冒称落地 | close_mavsdk原源码仅析构本实例并等待server退出；本轮清理是替身，未验证真实进程/飞控停止 |
| 已落地且armed=False884–887 | 不再替换，依据输入遥测早退；未发起arm的取消走before_takeoff | 遥测输入在夹具内是合成状态 |
| asyncio.Task.cancel() | CancelledError绕过CancelFlight/Exception恢复分支，直接finally；未调用recover/pause/stop，取消异常仍向外传播 | 未检查实际上层是否以Task.cancel终止飞行，不能声称网页取消会走这一路 |

**结论：正常前缀顺序成立，但恢复不是无条件的缓存失效保护。** 特别是replacement setter持续pending、且未收到外部协程取消时，等待本身没有进入后续暂停/清理的出口。原setpoint:528–534只在await成功返回后更新Python reference；同样的RPC错误下reference仍可为旧PVA，不能用它代替SDK缓存读回。已安装mavsdk-grpc 4.0.5的offboard.py直接await SetPositionNed(request)，该调用处未显式传deadline；这和执行器无wait_for的源码事实相符，但不是网络永远挂起的实测。既有真实SDK重发证据沿用前节，不在本轮假造新SDK实验。

13项局部检查通过、0跳过；主Agent最终0.715s，本对话内置独立审查最终0.638s同模块通过。覆盖两种触发、pending/接受前后丢响应、定位失效、接管成功/hold/start/模式未确认、planner stop warning、pause与cleanup失败、未arm取消、已落地早退、synthetic恢复返回及Task.cancel边界。主Agent首次运行因AST夹具漏注入json全局失败；补齐后通过，属于夹具接线，不是生产源码问题。独立审查指出接管顺序断言未包含/stop，已补明确索引顺序；既有18项补片检查不因新增测试机械重跑。

```sh
cd /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-review-tests
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_drone_recovery_cache_chain -v
```

Next/owner：根Codex优先给独立副本中的恢复替换等待定义有限失败出口，核SDK未确认时能否先暂停本任务仿真并可靠进入原清理；不得把超时直接当远端撤回。另保留Task.cancel生命周期入口、源epoch与持续TTL的未知项。本轮范围未覆盖返航中二次取消/故障转接、真实恢复观测/回退/降落、SDK与PX4端接收、持续备份控制。原硬判据与补片不变，M2部分完成、完整M3/动态闭环未过。
测试临时副本和报告自动删除，未产生新服务/构建/大文件；原SDK/ULog/失败记录保持。Knowledge=already_covered，沿用Wiki/ROS2 与 FishBot§20的动作、接收和实际执行分层；项目事实留本记录，不写memory。


## 恢复入口 RPC 等待与取消终态修复（2026-10-27）

本轮扩展现有默认关闭补片，仍以drone c866441为基线，仅应用于临时独立副本。DRONE_REVALIDATE_COMMAND只有1启用新增行为。recover入口复用原生asyncio.wait_for包裹hold、position和offboard_start；不新建SDK owner、后台lease或规划模式。不修改V/A/Z/净空硬判据。原冻结三源码与既有观测补片未变，未启动ROS、MAVSDK二进制、PX4/Gazebo或飞行。

恢复的可选flight.recovery_rpc_timeout_s默认1.0秒，表示本地单次等待预算，不是实飞安全响应上界；无效、非正或非有限值只记WARNING后回退1.0。OFF分支仍直接await原调用，不加journal。ON分支把每次调用写入report.recovery.rpc_attempts：operation、wait_timeout_s、开始/结束宿主monotonic、status。成功返回为returned，远端效果仍not_independently_observed；异常/超时为unconfirmed，取消为cancelled，远端效果保持unknown。TimeoutError既可能由本地等待也可能由SDK抛出，本片不凭异常类型断言远端未接纳。

调用未确认会转入原RecoveryBlocked→block_recovery尝试暂停本任务仿真，该调用返回或抛错后才进入原run清理；不重试、不请求后续/stop或start，不把取消Python等待当SDK缓存撤回。定位失效、已落地早退等原分支保持。wait_for依赖被等待协程响应取消；已安装gRPC aio的__await__会cancel底层call并重新抛CancelledError，实际MAVSDK Python路径已做下述受控验证，不推广为任意吞取消协程或事件循环停顿下的硬时限。

另修复真实run分支中的终态误报：业务取消已进入recover时再Task.cancel，原finally可能保留cancelled并显示“已落地”，即使没有确认。首版只核report两标志，独立审查发现takeoff→land→takeoff可遗留旧True；根用同输入复现后补当前telemetry检查。ON分支在recover入口先清旧report标志，已落地早退或成功land重新确认，blocked不再沿用上一段成功；除before_takeoff外，必须同时有report.landed/disarmed=True和当前telemetry ON_GROUND/armed is False，否则清理旧report标志、标failed并记录未确认；原CancelledError仍传播，不吞取消、不宣称恢复已完成。新遥测本身的源龄期未因此获得新证明。

### 验证与范围

- [RPC失败出口8项](../apps/fishbot-control-station/workbench-review-tests/test_drone_recovery_rpc_guard.py)：真实run/recover/helper，fake SDK/暂停/清理；两触发的pending位置、pending hold/start、OFF兼容、无效预算、pause失败、恢复内Task.cancel及历史落地flags。两处报告负例先复现失败再修；独立7项0.597s通过；最后入口清旧标志补丁另独立3项0.159s通过，包含合法已落地早退和synthetic成功返回。
- [真实Python/gRPC客户端1项两分支](../apps/fishbot-control-station/workbench-review-tests/test_drone_recovery_grpc_deadline.py)：已安装mavsdk-grpc==4.0.5、真实SDK类型转换及grpc aio，通过临时127.0.0.1端口连接明确synthetic service。首PVA返回后，第二position请求分别模拟接受前延迟、接受后丢响应；本地超时均进入原暂停/清理替身，服务handler实际观察到取消。两种fake cache可不同，但reference仍旧且journal均unknown。不是MAVSDK server二进制、MAVLink/PX4接收或缓存重发新实验；synthetic SUCCESS明确不作原生采用证明。
- 前轮18项补片和13项恢复链随补片变动定向回归，连同新增8+1，共40项最终2.391s通过、0跳过；源码apply --check --whitespace=error-all、整文件编译、sender双应用顺序继续通过。asyncio调试慢回调提示保留，不能当规划延迟测量。

```sh
cd /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-review-tests
PYTHONDONTWRITEBYTECODE=1 /home/muqiao/.cache/ros2-drone/venv/bin/python -m unittest test_drone_command_revalidation_patch test_drone_recovery_cache_chain test_drone_recovery_rpc_guard test_drone_recovery_grpc_deadline -v
```

**未解决/Next：** 本片只覆盖recover入口的三种RPC，后续_hold_for_observation、retreat_to、land内RPC仍为原await，不能称整条recover有硬上限。Scene.pause虽给gz请求1000ms，但父进程Scene.request:185附近的stdout.readline没有父期限，worker/GIL/输出异常仍可能挡住block_recovery及后续清理。根Codex下一项优先给既有请求worker增加有界父读取和所属进程回收，沿用现有协议，不新建运行时；先复现再最小修复。源epoch、HTTP等待中旧缓存TTL、完整备份/真实动态资格仍待完成。原冻结保持，M2部分完成、完整M3/动态闭环未过，整体plan未完成。
收尾：两轮subcase的grpc channel/server在finally关闭，测试独立确认目标端口拒绝新连接；所有临时源码/报告自动回收。无新SDK子进程/构建/大产物，原ULog/SDK/失败材料保留。Knowledge=already_covered，沿用Wiki/ROS2 与 FishBot§20的调用、接收、实际执行分层，模块兼容性留项目，未写memory。


## Scene 请求 worker 父进程期限修复（2026-10-27）

新增独立[Scene补片](../apps/fishbot-control-station/workbench-tools/patches/drone-scene-worker-deadline.patch)，基线仍为drone c866441。原Scene.request将timeout交给gz子进程，却用无期限stdout.readline等结果。根先用真实管道/纯Python worker复现：silent PID642041、partial PID642053均已收到1ms请求，观察150ms仍存活/阻塞；显式回收各自worker后才退出读取，退出码-9均wait确认。这是故障注入，不是Gazebo现场故障。

DRONE_REVALIDATE_COMMAND在Scene创建时只有1启用，默认OFF完整保留原text管道路径。ON继续复用同一request worker、原JSON行和protobuf hex协议。父预算为原timeout毫秒转换为秒再加0.5s IPC余量；同一期限覆盖取锁、进程启动耗时、非阻塞管道写入及完整行读取。原timeout字段不重写，不能把父等待回退当成远端参数有效性证明。NaN先max折零的边界由独立审查复现，现先检查原数值有限性；坏值只WARNING，父等待退为1.5s。同步Popen/序列化不能被期限本身中断，故不称任意系统条件下的严格总墙钟上界。

超时、EOF、不完整响应或解析错误在持锁期间清退旧worker后抛出，不盲目重发原命令；下一次新调用可重建，旧迟到响应不复用。只操作self.worker的Popen句柄。失败回收先TERM等待0.2s，再KILL等待1s；正常close先关stdin/EOF等待2s，再同样升级。退出未确认会报清理失败并保留句柄；close取锁最多等5s，失败不假报已回收。请求取锁超时不清退另一正在处理的worker。远端Gazebo可能已执行命令，父超时不能当撤回或未执行。

[12项局部验证](../apps/fishbot-control-station/workbench-review-tests/test_drone_scene_worker_deadline.py)最终7.327s通过、0跳过，真实Popen/管道/线程、明确替身worker；没有导入gz或启动ROS/SDK/Gazebo。覆盖原silent/半行阻塞、正常/分块响应与两次复用、写满管道、超时后重建、坏JSON/hex/worker error/EOF、忽略TERM、OFF原路径、取锁失败不误杀、坏预算WARNING、close EOF→TERM→KILL及close锁失败。独立原9项4.933s过，最后新增3项2.393s过。

其中一项组合前节Flight补片，执行真实run/recover/block_recovery、Scene.pause/request/close；SDK、protobuf类型与子进程Gazebo部分明确为替身。恢复position超时后，暂停worker再半行失联，父读取超时仍进入原finally/SDK清理替身；最终failed，无simulation_pause_confirmed，无落地声称。两补片apply检查及源整文件编译通过；前轮40项结果不因Scene单独补片机械重跑，Flight补片未改。

```sh
cd /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-review-tests
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_drone_scene_worker_deadline -v
# Apply both patches only to an independent copy of drone c866441.
git -C "$DRONE_REPAIR_COPY" apply --check /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-tools/patches/drone-scene-worker-deadline.patch
```

Next/owner：根Codex补齐恢复后续观察/回退/降落中的控制RPC等待，复用现有recovery_command并区分正常降落记录，避免只保护入口。仍不把有限失败出口当安全备份或动态通过；epoch、SDK旧缓存持续TTL、完整M3与动态闭环未完，整体plan保持active。补片未应用冻结树，不解锁/飞行。
收尾：测试所有自有child均在正常路径或fixture兜底中wait回收、管道关闭，线程join，临时源码/marker/report自动删除；锁失败用例刻意保留句柄直到fixture兜底，不冒称生产close已成功。无SDK/ROS/Gazebo实例、构建或新大产物，原失败/遥测保留。Knowledge=already_covered，沿用Wiki/ROS2 与 FishBot§20的调用、确认和物理验收分层，模块事实留项目，未写memory。


## 恢复尾段与正常降落 RPC 等待（2026-10-27）

继续扩展默认OFF Flight补片，仍未应用冻结树。先在上一版补片临时副本执行真实_hold_for_observation，pending setter只能由测试外层0.5s取消，未进入原恢复异常；新受控反例定位在尾段未使用已有helper，不是新SDK现场故障。现将观察悬停、retreat_to目标/中断保持/恢复推进、land验通道前保持/下降前保持、offboard.stop、action.land以及下降受阻的hold/position/start统一接现有recovery_command。预算和unknown合同沿前节；硬判据、原正常.2s降落复验与回退修复保持。

ON时land的保持和offboard.stop异常向上抛，不再WARNING后继续LAND，也不在stop未确认时将self.offboard置False；OFF保持原警告继续和原等待。普通降落的调用写report.landing_rpc_attempts；只有recovering=True且有当前recovery记录才进recovery.rpc_attempts，不给正常任务捏造故障恢复。正常降落失败仍沿原run异常进入真正recover，helper自身不自动重试。

下降通路失效时，hold→position→start均有本地等待预算；ON再复用原wait_until的5s模式谓词，OFFBOARD快照未满足则不置self.offboard=True；正向接管后仍抛descent_became_unverified回恢复，不恢复未经检查的下降。此谓词未增加新遥测序号/接收龄证明，不能称start后新鲜模式样本或实际停飞。

[新尾段12项](../apps/fishbot-control-station/workbench-review-tests/test_drone_recovery_tail_rpc.py)提取真实_hold_for_observation/retreat_to/land/with_hover_guard，与真实run/recover组合；控制、感知和遥测明确为替身。覆盖各控制阶段pending、禁止继续下一命令、normal/recovery日志归属、模式未确认与正向接管出口、hover watcher取消向控制协程传播、OFF等待/原警告继续、正常合成落地返回。三组真实run取消→recover后段异常→原pause/cleanup/failed均完成，不能充当实际悬停/回退/落地。独立11项1.444s及最后正向出口1项0.053s通过。

原18项中的降落龄期夹具只补options/helper/async依赖，原预期与阈值未改。最终原40项＋新12项＋SceneRecoveryIntegration1项，共53项5.445s通过、0跳过。包含真实已安装SDKPython/gRPC对synthetic服务取消，不启动MAVSDK二进制；Scene子进程仍为纯Python协议替身。Flight/Scene两补片apply与源编译、sender双顺序持续通过；未机械重跑Scene其余11项未变的worker回归或全机器人实验。

```sh
cd /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-review-tests
PYTHONDONTWRITEBYTECODE=1 /home/muqiao/.cache/ros2-drone/venv/bin/python -m unittest test_drone_command_revalidation_patch test_drone_recovery_cache_chain test_drone_recovery_rpc_guard test_drone_recovery_grpc_deadline test_drone_recovery_tail_rpc test_drone_scene_worker_deadline.SceneRecoveryIntegration -v
```

Next/owner：根Codex复用现有drone-sdk-cache-probe及官方4.0.5接口，给真实MAVSDK二进制的RPC响应注入受控失联，核本地超时/取消后的真实缓存重发与所属实例回收。仍只连synthetic本地协议端，不启动PX4/飞行；测试代理只作为诊断fixture，不进入执行架构。不得把Python/gRPC替身缓存证明升级真实SDK行为。后续候选epoch/缓存持续TTL、可行备份、原生空中采用与动态闭环保持未完成，整体plan active。
收尾：全部临时源码/report回收，gRPC fixture端口关闭并拒绝连接，Scene自有worker/线程/pipe回收。原drone c866441/PX4 d6f12ad/GCOPTER e0444f6冻结；Scene补片未改，无ROS/Gazebo/SDKbinary/飞行或大构建产物。Knowledge=already_covered，沿用Wiki/ROS2 与 FishBot§20的调用/接收/实际执行分层，兼容性事实留项目不写memory。


## 真实 SDK 的响应丢失与缓存歧义（2026-10-27）

复用原有限[SDK探针](../apps/fishbot-control-station/workbench-tools/drone-sdk-cache-probe.py)，增加可选--rpc-response-fault before_forward/after_forward。诊断relay仅注册位置setter，绑定127.0.0.1临时端口，不进入生产执行架构；PVA与stop仍直连原SDK。before不提交位置上游，after等待真实SDK成功返回后扣住响应。客户端原生wait_for预算.25s，handler记录实际取消，不伪造SDK成功、不重试。两种客户端结果均TimeoutError且remote_effect=unknown。

| 最终run_id | 超时后的实际稳定报文 | 远端因果 / stop后 |
| --- | --- | --- |
| 337e5be4-26ae-474a-9fe6-5b6a36d1c9f0 | 9包/mask2048，旧P=(.1,.2,-.3)、V=(.12,-.08,.06)、A=(.03,.02,-.01) | 无upstream调用；stop后0包 |
| 8fecabc1-c5f0-4840-bc58-fc1ed481f164 | 10包/mask2552，新P=(.4,.5,-.6)，V/A被掩码忽略 | upstream result=1早于客户端超时，取消没有回滚已接受位置；stop后0包 |

每组初始仅一次PVA、仅一次位置尝试、一次stop，无start/arm/land。PVA稳定初窗分别12/10包；超时后窗口约.45s，各自payload只有1种、wire时刻9/10种。统计沿原探针排除RPC返回/超时后前100ms，只区分在途包，不是新增物理容差。当前数值核对1e-6仅匹配float32载荷编码，不改变飞行硬判据。原生SDK日志均v4.0.5，synthetic unarmed Offboard heartbeat与ACK不能当PX4或真实模式接受。

先行6d7e0f06-c708-4b1f-b080-81698226e85f同before结果9/0包；审查后补具体active字段、distinct payload/wire时刻检查，并修relay首资源关闭异常跳过后续清理的缺口，再用两个新UUID跑最终版。三组自有PID702054/704483/704705均TERM退出(-15)并wait回收，/proc消失，目标UDP/gRPC/relay监听已关闭；原SDK服务绑定沿实际ss记录，不以loopback客户端推断只监听本机。三组必要原始小证据约84KiB，保留而不压缩复制，无新大构建或临时渲染；测试临时端口关闭，无PX4/Gazebo/ROS/飞行。冻结drone c866441/PX4 d6f12ad/GCOPTER e0444f6均clean。

[探针局部5项](../apps/fishbot-control-station/workbench-review-tests/test_drone_sdk_cache_probe.py)0.307s/0跳过通过：原非有限字段/进程清理3项保持；新增实际gRPC relay双时序与关闭、首资源清理异常不跳过后续回收。两组SDK binary现场记录单独验收，不以单测代替。前两次执行曾因工作目录错误而未找到测试/写入目标，已纠正绝对路径和测试cwd，错误不算通过；未因此重启或重复派发同一SDK。原Flight/Scene补片未改，不重跑未变53项或全机器人实验。

产物入口在忽略output/drone-committed/各UUID：sdk-cache-probe.json、sdk-cache-peer.jsonl、sdk-process.json、sdk-listeners.json、sdk.log、probe.log、invocation.json、cleanup.json、最终两组source-provenance.json。Git仅提交探针、测试与文档，不提交运行日志。复验使用新目录：

```sh
cd /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-tools
/home/muqiao/.cache/ros2-drone/venv/bin/python drone-sdk-cache-probe.py --output /tmp/drone-sdk-cache-before-new --rpc-response-fault before_forward
/home/muqiao/.cache/ros2-drone/venv/bin/python drone-sdk-cache-probe.py --output /tmp/drone-sdk-cache-after-new --rpc-response-fault after_forward
```

结论：客户端超时/取消不使真实SDK缓存自动撤销；RPC未转发仍重发旧PVA，已接受后丢响应则持续新位置。当前recovery_command保unknown正确，但仅有限等待不构成缓存TTL、刹停或安全接管。

Next/owner：根Codex核现有Sidecar在暂停/时钟回退/新goal后的候选身份隔离，并制作默认OFF最小epoch适配；随后处理/state等待期间旧SDK缓存持续重发的TTL缺口。沿既有发送层和恢复出口，不引入生产RPC代理，不自动重试未知效果控制。原冻结源不部署、不解锁；可行备份、原生空中采用、完整M3与动态闭环未完，整体plan active。
Knowledge=already_covered，沿用Wiki/ROS2 与 FishBot§20的调用/接收/执行分层；模块新事实留项目，无memory写入。

独立只读审查按raw jsonl和RPC窗重算9/10/0计数、具体载荷与上游成功先于超时的事件顺序一致；原报文arm=0，PID/start_ticks消失及SDK/relay端口拒绝连接均独立复核。SDK实际监听0.0.0.0，不能把本机客户端写成服务仅loopback。


## 默认关闭的候选 epoch 隔离（2026-10-28）

新增独立[epoch补片](../apps/fishbot-control-station/workbench-tools/patches/drone-command-epoch.patch)，未应用冻结源。DRONE_COMMAND_EPOCH仅1启用，执行器/Sidecar需同启用；单侧缺goal token时报告command_epoch_unavailable，不改写/伪造token。OFF保原HTTP字段与原小回退行为；建议后续隔离验证同时使用原DRONE_REVALIDATE_COMMAND补片。所有源码、helper和控制流只在TemporaryDirectory副本提取/编译，不导入ROS，不启动节点/SDK/仿真/飞行。

CommandEpoch使用随机UUID区分候选，不用内容hash或可回退的sim时间作身份。GazeboObserver的真实on_clock回调，以及Sidecar的state/tick/command/curve/ACK入口观察时钟：回退或原2s无进展使epoch失效一次，恢复时钟不能重用旧token。Sidecar清目标/ACK/样本/已登记曲线/排队请求，保存旧关联值后发送原stop；重复暂停不反复刷新预算。新goal与匹配owner的stop再rotate；wrong-owner stop不使有效epoch轮换。目标接受锁内重核state、入队token并捕获reply，tick比较token与goal_id，避免复用同goal_id的旧队列发出。

固定原生补片ego/upstream-jazzy.patch:2392–2406、2457–2469将PoseStamped stamp作为目标接受、取消floor与ACK关联，未用于该目标轨迹采样。原sim_ns+sequence在回退时可能重复，现ON用进程内递增floor保持关联值唯一；不改变曲线的start/knots/采样时间。旧ACK在新目标下拒绝，未ACK或低于既有floor的曲线不登记。ACK与curve跨topic交付仍可能先曲线后ACK，首曲线会被拒绝，需要原生顺序/活性验收，不能据此宣称可运行闭环。

Flight固定保存/goal回复token与独立observer token，HTTP等待之后核验；state token在readiness/matched宽限前核，sample token在存在后核。独立审查曾复现首PVA后新epoch+空样本先走旧宽限，主线程三分支反例先红再修：空样本、其他goal、readyFalse均直接进入epoch故障，不能继续按原宽限等10s。原发送前取消、sample .3/source_end+.15与零VA goal_hold判据保留，未改变V/A/Z/净空门槛。成功RPC后将goal/clock epoch写入原reference便于回看；RPC未确认不提前改reference。

[20项局部检查](../apps/fishbot-control-station/workbench-review-tests/test_drone_command_epoch_patch.py)0.842s/0跳过通过；含新鲜正例、缺/错token、回退追回同值、暂停恢复、真实observer回调、确切native ACK碰撞、同goal_id队列、锁后并发目标回复归属的受控重入、旧ACK/未ACK曲线拒绝。真实三补片EPOCH/REPAIR/SENDER六种顺序apply/compile通过，并执行组合后的epoch/取消/源期限行为。独立原18项0.641s过并发现宽限缺口，修后新增和组合2项0.164s独立通过；不把先前18绿色当完整资格。未改原三补片/冻结树，不重跑未变53项或全机器人实验。

**边界仍在：** Bspline/PositionCommand没有原生epoch字段；本地收到消息时打token不等生产者来源证明，ACK后迟到高ID/多生产者/重启需另外核。state快照生成后服务器再次失效而客户端尚无对应观测，仍存在分布式窗口。RPC中途已经被SDK接受的指令不能由token撤回；/state等待内旧SDK缓存持续重发、可行备份及动态闭环未解决。当前只完成本地候选合同切片。

```sh
cd /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-review-tests
PYTHONDONTWRITEBYTECODE=1 /home/muqiao/.cache/ros2-drone/venv/bin/python -m unittest test_drone_command_epoch_patch -v
```

Next/owner：根Codex沿既有goto /state等待区间补并发失效观察，复用原recover处理过期/取消/回退，不自动重试未知效果RPC；用真实SDK旧缓存重发证据核等待期间的有效期边界。原生ACK→Bspline→PositionCommand顺序与单一生产者资格仍待核，不把receipt token当ROS来源证明。保持冻结、不部署、不解锁；可行备份、原生空中采用、完整M3和动态闭环未完成，整体plan active。
收尾：TemporaryDirectory副本自动回收，无运行实例/新大产物，历史遥测/失败和既有pycache未动。原drone c866441/PX4 d6f12ad/GCOPTER e0444f6均clean。Knowledge=already_covered，沿用Wiki/ROS2 与 FishBot§20的来源/确认/实际执行分层；新兼容性事实留项目，无memory写入。本对话内置独立审查，不联系其他聊天。


## /state 等待期间的旧缓存失效观察（2026-10-28）

扩展原默认OFF[复查补片](../apps/fishbot-control-station/workbench-tools/patches/drone-command-revalidation.patch)，不部署冻结源。先用真实goto/run/recover与明确SDK/HTTP替身复现：首PVA已成功，第二/state持续pending；推进至10.4sim（sample age .25仍合格，但source_end10.2已超过原.15），外层200ms内仍不恢复。该受控反例先失败后修，不是新实飞或真实SDK故障。

新增await_planner_state只在原DRONE_REVALIDATE_COMMAND开启时并发观察；OFF仍直接原await。复用原cancel/operator、deadline、位置有效/遥测、scene、clock与已启用observer epoch检查；上一成功PVA按command_stamp_sim_s原[-.1,.3]、source_end+.15验期限。原到目标零VA hold只豁免source_end，不豁免sample age。成功位置hold不继续承担旧PVA期限；未确认setter不能当缓存已替换。reference在成功后保存已解析float source_end，保原数值字符串兼容；缺/非有限元数据拒绝当前等待，诊断写null而非伪造新鲜值。

HTTP完成与失效同刻时先核失效，再取结果；任务被取消/抛错均cancel+gather本地HTTP task，保原CancelFlight/ReturnHome/CancelledError语义，不重试。监视器不发控制命令，只抛原run→recover；新command_wait_failures记录wait_rejected与sdk_cache_effect=unknown，不伪造接管/暂停/落地。20ms仅轮询间隔，受事件循环调度影响，不是硬实时上界。

[新13项](../apps/fishbot-control-station/workbench-review-tests/test_drone_state_wait_guard.py)覆盖源/样本过期、source stamp而非RPC timestamp、原输入故障、取消与完成同刻、ReturnHome/operator开关、zeroVA例外、位置hold、HTTP错误、外部Task.cancel与OFF原pending、缺/非有限及数值字符串元数据。真实localhost ThreadingHTTPServer＋原ego_request＋原生to_thread用例先不释放第二响应，确认原恢复路径已位置替换后/stop，故意观测边界failed且无落地；再释放HTTP，等待handler与底层client read线程结束，仍仅1PVA、端口拒绝连接。飞控/cache、观测、scene.pause仍替身，不能当实际控制采用。

最终原88相关＋新13，共101项11.261s/0跳过通过。包含原15项基线和已知未部署边界见证，不是101飞行验收。公共AST夹具只在源码存在时绑定helper，旧原方法期望/阈值不变；原恢复顺序测试只将expired精确原因改为更早的cached_command_source_expired，其位置→/stop、终态/unknown等断言保持。REPAIR/EPOCH/SENDER六顺序applycompile与组合行为仍通过；未重跑Scene未变的其余worker或全机器人实验。

独立新12项1.751s及原恢复顺序3项.282s过，并指出source_end字符串接受/保存类型不一致；主修为保存已解析float，新数值字符串用例及强化真实HTTP退出最后独立2项.250s过。原88项首轮有1条旧诊断原因预期不一致，未忽略；先定位后按新触发点更新并全101复验。

```sh
cd /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-review-tests
PYTHONDONTWRITEBYTECODE=1 /home/muqiao/.cache/ros2-drone/venv/bin/python -m unittest test_drone_state_wait_guard test_drone_command_validity test_drone_command_revalidation_patch test_drone_recovery_cache_chain test_drone_recovery_rpc_guard test_drone_recovery_grpc_deadline test_drone_recovery_tail_rpc test_drone_command_epoch_patch test_drone_scene_worker_deadline.SceneRecoveryIntegration
```

边界：取消to_thread的等待不会杀底层网络线程；真实HTTP用例明确观察该线程在恢复完成时仍未返回，再由fixture释放/回收。SDK不会因等待取消而自动失效，既有真实SDK证据沿前节；本轮未启动SDK二进制。普通PVA setter自身pending、循环其他await及恢复替换延迟仍不能作为原生硬TTL；observer epoch不开启时不增加小回退身份保证，state快照之后的分布式窗口仍在。本轮不授予整体缓存期限、安全备份或动态资格。

Next/owner：根Codex复用现有SDK cache探针，把新/state等待保护接真实MAVSDK二进制和synthetic本地peer，核过期→原恢复位置替换→报文切换及迟到HTTP响应不恢复PVA；仍不启动PX4/飞行。随后覆盖普通PVA RPC自身pending/已接受丢响应期间的失败出口，不把本地wait取消当SDK撤回。原生ROS来源/ACK顺序、完整缓存期限、可行备份、原生空中采用、完整M3与动态仍未完成，整体plan active。
收尾/Knowledge：所有临时副本、HTTP handler/读取/serve线程及本地端口回收，真实gRPC/Scene定向夹具按原退出回收；无ROS/Gazebo/PX4/SDKbinary或新大产物，原三冻结源保持。历史遥测/失败与并行空间清理任务保留，already_covered Wiki/ROS2 与 FishBot§20，兼容性事实留项目不写memory；本对话内置只读审查，无跨聊天联系。


## Flight.run → recover 的真实SDK缓存替换（2026-10-28）

本轮只扩展诊断，复用[原SDK探针](../apps/fishbot-control-station/workbench-tools/drone-sdk-cache-probe.py)的进程、synthetic MAVLink peer、报文捕获与清理；新增[等待恢复场景](../apps/fishbot-control-station/workbench-tools/drone-sdk-state-wait-probe.py)，提取原HTTP夹具供复用。默认OFF执行补片及冻结源码未改；临时源码副本只应用既有REPAIR。真实MAVSDK二进制日志为v4.0.5，HTTP及ego_request/to_thread真实；pose、armed/IN_AIR/OFFBOARD状态、场景暂停和恢复观测边界均为夹具，未启动PX4、ROS或Gazebo。

**实际链路：** 首PVA setter成功 → 第二/state挂起且SDK仍重发PVA → 夹具时钟10.15推进至10.4，sample age .25仍合格而source_end10.2超过原.15 → await_planner_state抛cached_command_source_expired → 原Flight.run进入recover → 成功位置setter替换SDK缓存 → HTTP /stop → 夹具恢复观测边界failed，无landed。随后释放原HTTP工作线程读取一条新鲜、任务匹配、数值不同的PVA，未再次派发PVA；最后由探针显式调用SDK offboard.stop，区分位置替换与停止发送。

主要原始证据位于忽略目录apps/fishbot-control-station/workbench-tools/output/drone-committed/65850c7c-4ac3-457b-b056-62e46a886f06/：sdk-cache-peer.jsonl、sdk-cache-probe.json、flight-events.jsonl、http-late-response.json、guard-recovery-scenario.json及raw-wire-audit.json。四窗排除前100ms，仅为稳定报文观测窗，不是控制容差或延迟上界。

| 窗口 | 实收包数 | 掩码与活动字段 |
| --- | ---: | --- |
| /state pending | 2 | mask2048，NED P=(0,1,-1)，V=(.1,.2,0)，A=(0,.01,0)，yaw≈1.32079637rad |
| 恢复位置成功后、释放迟到HTTP前 | 2 | mask2552，NED P=(0,0,-1)，yaw≈π/2；VA字段不活动 |
| 原HTTP线程读到新鲜迟到响应后 | 4 | 同一位置报文；没有PVA重新激活 |
| 显式SDK stop后 | 0 | 该观察窗无setpoint |

所有报文frame1、target7/component1；重发有不同wire time，单一活动载荷。只有一次PVA RPC；恢复位置RPC返回之后原始记录中PVA为0。迟到响应stamp10.4/end11.2、trajectory8，ENU P=(3,2,1.5)、V=(.5,-.2,0)、A=(-.01,.02,.03)、yaw=-.4，与旧PVA和位置保持均可区分；实际HTTP client读取完成且无错误，不能用“它本来过期”解释未发送。

独立审查由raw jsonl重算2/2/4/0及坐标、掩码、yaw、target和时序一致。首恢复位置包比夹具时钟推进晚约5.92ms，比迟到响应释放早约223ms；这是本次host收包观察，不是硬实时保证或PX4采用证明。恢复phase为进入recover的时序证据；helper日志的fake wall=100不得用于真实耗时。

[局部测试](../apps/fishbot-control-station/workbench-review-tests/test_drone_sdk_state_wait_probe.py)检查正确四窗、迟到PVA/错误frame/错误位置及stop后多包反例。最终原state-wait13＋SDK probe5＋新wire3共21项2.109s、0跳过通过；独立相关9项0.426s过。未改执行补片，不重跑未变101项。原探针默认三RPC路径另串行复验UUID bef96002-9d76-4f27-9eb4-786544865c41，原始报文重算PVA11/位置9/stop后0，原参数转换一致；该默认模式diagnostic_checks为空，结论来自原报文复核，不以exit0冒充字段审计。

```sh
cd /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-review-tests
PYTHONDONTWRITEBYTECODE=1 /home/muqiao/.cache/ros2-drone/venv/bin/python -m unittest test_drone_state_wait_guard test_drone_sdk_cache_probe test_drone_sdk_state_wait_probe -v
# 另建唯一output目录；诊断仅synthetic peer，无PX4/飞行。
cd ../workbench-tools
/home/muqiao/.cache/ros2-drone/venv/bin/python drone-sdk-state-wait-probe.py --output /tmp/drone-state-wait-new
```

**证据边界：** 原Flight.close_mavsdk在该夹具中延后交由探针owner，目的是观察run结束后的缓存与迟到响应；这不验证生产清理。实际暂停、制动、落地均未验证，终态仍failed。监视器20ms轮询不是硬TTL；普通PVA RPC自身pending、其他await、恢复RPC未知效果和分布式观测窗口仍可能留下旧缓存，不能宣称全链限期或安全接管。SDK实际监听0.0.0.0/*，仅客户端与synthetic peer在本机，不声称监听仅loopback。

收尾：两串行SDK进程100888/start_ticks214744及126386均wait回收、exit-15，/proc身份已消失，SDK/HTTP监听关闭；HTTP serve/handler/client-read线程均退出。临时源码自动清理，小原始证据原地保留于忽略output，无新增大构建、视频或重复数据包。冻结drone c866441/PX4 d6f12ad/GCOPTER e0444f6均clean，历史失败/遥测保留。Knowledge=already_covered，沿用Wiki/ROS2 与 FishBot§20；兼容性事实留项目，不写memory。本对话独立审查，无跨聊天联系。

Next/owner：根Codex接续普通PVA setter RPC自身pending及已接受后丢响应的失败出口，复用既有发送层和run→recover；不把Python取消当SDK撤回，不自动重试效果未知的控制请求。原生ROS来源/ACK顺序、完整SDK缓存期限、可行备份、原生空中采用、完整M3与动态闭环仍未完成。


## 普通PVA RPC等待保护与取消终态（2026-10-28）

原默认OFF[REPAIR补片](../apps/fishbot-control-station/workbench-tools/patches/drone-command-revalidation.patch)此前只保护/state等待和恢复RPC，普通PVA仍直接等待SDK。[新反例](../apps/fishbot-control-station/workbench-review-tests/test_drone_pva_rpc_guard.py)分别模拟未接受、已接受后丢响应，两者超过测试外部350ms仍不退出，先红后修。新增await_pva_command仍调用原setpoint，不增加控制owner、不重试；共享check_command_wait复用原输入/取消/operator/局部clock epoch和sample/end/零VA例外，同时核上一成功reference与当前在途候选。

等待保存旧reference对象，避免setter返回后self.reference切换为尚未补源元数据的新对象造成误判。失效与RPC完成同turn时先拒失效；command_rpc_timeout_s默认1s，非法/非正/非有限值警告并回退1s，loop.time提供独立于仿真时间的预算。20ms轮询与finally gather均依赖事件循环及底层协程配合取消，不是任意RPC实现的硬实时/强杀期限。command_rpc_attempts把应用status、rpc_returned和remote_effect分别记录；取消/超时效果unknown，确认返回也只记not_independently_observed。

SENDER补片为组合兼容，把候选身份存于goto读到当前command的位置，由setpoint在PVA且没有显式context时读取；position不继承旧PVA身份，显式context优先。未改变坐标、飞行门限或实际SDK发送入口。三补片六种应用顺序apply/compile、组合epoch/取消/源期限行为通过；首轮组合失败来自补片callsite上下文重叠，修正后复验，未忽略失败。

新增[真实SDK探针](../apps/fishbot-control-station/workbench-tools/drone-sdk-pva-wait-probe.py)，复用原诊断relay，仅增加method=pva；默认position注入行为不变。原包与relay事件独立重算如下，窗口均排除前100ms，只用于稳定观察：

| UUID（忽略output/drone-committed/下） | 故障注入与触发 | pending／恢复位置／显式stop后 |
| --- | --- | --- |
| 19798d4f-cfdf-475b-8479-81ad58c083cc | 未转发PVA；推进夹具sim10.15→10.4触发源过期 | 3个旧position／4个position／0 |
| 31e56157-1bc8-4436-8df0-8322483ebc40 | SDK result1后扣响应；同样源过期 | 4个PVA／4个position／0 |
| 73b6bb73-a5ac-4b06-85f2-69d85fefb1cf | SDK result1后扣响应；夹具sim保持10.15，用.5s RPC预算退出 | 3个PVA／3个position／0 |

PVA为mask2048、NED P=(0,1,-1)、V=(.1,.2,0)、A=(0,.01,0)、yaw≈π/2-.25；position为mask2552、P=(0,0,-1)、yaw≈π/2，均frame1/target7/component1。每窗wire time变化、活动载荷单一。每轮只有1次PVA尝试，RPC没有返回；恢复位置返回后完整raw中PVA为0。before无upstream调用，after两轮result1均早于取消；真实顺序为本地等待取消→recovery_hover→开始位置setter，远端relay handler的取消回执稍后到、早于位置setter返回，不能写成“等远端撤销成功才恢复”。wall组实际PVA await约500.77ms，仅该轮host观测；helper fake wall100不可计算实耗时。

**独立审查发现并修复原终态误报：** 旧landed/disarmed/visits存在时，外部Task.cancel虽然传播，原run finally仍可能status=succeeded/passed=True，而telemetry=armed/IN_AIR。先补普通巡航负例，再补except ReturnHome中实际return_home/goto的同类负例，均先红。主try取消标记＋共同finally检查当前task.cancelling，ON时统一failed、清未确认landed/disarmed、记task_cancelled并保原异常传播与清理；不自动发业务recover。只加同级except不能覆盖handler内部取消，已被第二负例证伪。OFF保留原行为。

最终相关检查：124项14.122s、0跳过通过（含原冻结基线已知缺口见证，不是飞行验收）。新增PVA12项覆盖接受前后未知效果、真实墙钟预算、在途及旧cached优先过期、zeroVA sample、epoch、原输入/取消、同turn竞争、数值字符串与非法预算、外部取消及两个旧落地报告负例；另新wire3项检查注入阶段差异/错误mask与frame/多包/漏窗。[协议检查](../apps/fishbot-control-station/workbench-review-tests/test_drone_sdk_pva_wait_probe.py)不启动SDK。独立最初18项/组合3项后，补缺口新10项1.370s；最后取消/组合5项0.492s通过，并独立重算上述三组原包与回收。保留初始组合失败、测试trigger名称误写及ReturnHome负例的发现过程，不把此前119/123绿色当最终资格。

```sh
cd /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-review-tests
PYTHONDONTWRITEBYTECODE=1 /home/muqiao/.cache/ros2-drone/venv/bin/python -m unittest test_drone_pva_rpc_guard test_drone_sdk_pva_wait_probe -v
# 单独建唯一output；--trigger可选source_expiry或rpc_timeout。
cd ../workbench-tools
/home/muqiao/.cache/ros2-drone/venv/bin/python drone-sdk-pva-wait-probe.py --output /tmp/drone-pva-wait-new --rpc-response-fault after_forward --trigger rpc_timeout
```

边界与收尾：日志均MAVSDK v4.0.5，真实二进制/gRPC/MAVLink缓存；planner、pose、telemetry、clock、pause与恢复观测为synthetic，三轮仍failed/landedFalse/disarmedFalse。实际SDK关闭由探针owner延后执行以观测缓存，不验证生产close、物理制动或落地。无PX4/ROS/Gazebo、arm/start/land。SDK实际监听*，本地客户端不等监听仅loopback。161287/start308277、161404/start308490、167035/start321990均wait回收exit-15，六个SDK/relay TCP端口关闭，原包arm=0；临时源码自动回收，约200KiB小原始证据原地保留，未生成重复大副本。三冻结源c866441/d6f12ad/e0444f6 clean，补片未部署，旧失败与遥测保留。Knowledge=already_covered，沿用Wiki/ROS2 与 FishBot§20；事实留项目，不写memory，本对话审查无跨聊天。

Next/owner：根Codex先核原生ACK→Bspline→PositionCommand的来源与跨topic顺序活性，并定点确认固定运行依赖，选现有无解锁入口取证。完整缓存期限、分布式state窗口、可行备份、原生空中采用、完整M3与动态闭环仍未完成；不把本地RPC保护当完整Safety Shield。 整体plan active。


## 原生ACK取证与首曲线有限缓存（2026-10-28）

本机Jazzy与固定ego_ws消息接口可用，source /opt/ros/jazzy/setup.bash及ego_ws/install/setup.bash后两原生可执行文件的动态依赖可解析；未安装新依赖或重建原算法。使用/usr/bin/python3导入rclpy/traj_utils/quadrotor_msgs，避免把未source时的ldd缺库当环境损坏。原缓存树23a8d5a＋既有Jazzy/算法改动保持，实际运行对象是现有install下ego_planner_node、traj_server，不把源码HEAD代替二进制溯源。

[ROS探针](../apps/fishbot-control-station/workbench-tools/drone-ros-ack-probe.py)在独立domain183、唯一topic前缀，向现有C++节点提供显式synthetic /clock、固定odom和远离目标的单点scene cloud；不是Gazebo深度或飞行。两个目标(2,0,1)与(0,2,1)收到原生ACK、Bspline与PositionCommand。最终UUID7d33e778-f0ef-45a5-950b-b7528b6c78ee中ACK为11120000000:0→curve1/PVA1、11160000001:1→curve2/PVA2；callback顺序均ACK先，未观察实际网络乱序。ACK仅说明接收时ID floor，不是路径/优化成功。

rclpy当前callback info实测dict仅含source_timestamp、received_timestamp及两序号，不暴露publisher_gid。先行4d21f8b2/3acb183e因误认接口形状失败，修正后4fb6cfba正向链成立但只得到publisher graph，未升级逐消息来源。已比较本机rclcpp MessageInfo::get_rmw_message_info，可读取16字节RMW GID；新增只读[原生收包器](../apps/fishbot-control-station/workbench-tools/ros-ack-witness/witness.cpp)与[独立CMake目标](../apps/fishbot-control-station/workbench-tools/ros-ack-witness/CMakeLists.txt)，复用已装rclcpp/消息/nlohmann_json，不改消息、规划器或执行器，也不新造控制协议。

最终原生记录ros-events.jsonl与witness.jsonl分别包含Python/CPP回执。ACK2/2、曲线2/2、PositionCommand16/16按(source_timestamp,publication_sequence_number)唯一关联，CPP所载字段与Python一致，三个实际publisher_gid均匹配预期节点的唯一graph endpoint。独立重算一致。cpp_per_message_publisher_verified=true只授予本次连续已知实例的收包归属；source_provenance_verified仍false：原生消息无goal/session，未部署在线来源筛选，重启/多writer仍未证明。

**首曲线活性修复：** 原EPOCH补片在未ACK时直接return，若接收处理顺序为Bspline→ACK，曲线记录永久丢失，之后PositionCommand(id)无法补回。新[7项缓存检查](../apps/fishbot-control-station/workbench-review-tests/test_drone_ack_curve_buffer.py)首反例先红；默认ON增加最多20条待ACK缓存，沿现有轨迹历史容量，不限制任务次数。ACK同RLock核epoch、goal_stamp、ID floor后重放；goal/stop/clock失效清缓存。原source start/end、traj_id及received_sim_s保持，重放另记ack_replayed_sim_s，不把等待时间刷新成感知新鲜度。OFF保持旧schema/行为。

[原生记录回放器](../apps/fishbot-control-station/workbench-tools/drone-ack-order-replay.py)以f3de761的旧EPOCH补片作基线，临时源码分别只交付一次曲线和一次命令，两个目标×ACK先/曲线先×旧/新共8组合。最终回放UUID b7dcf580-857e-4d9e-92ca-c925935f4a02：旧版ACK先2/2登记、曲线先0/2；新版两顺序均2/2登记，时间与载荷不改。该处理乱序是受控注入，不宣称现场网络曾乱序；接收样本登记也不是PX4采用。早期无GID记录回放fc6fe477保留，不替代最终来源证据。

验证：7缓存＋4收包/退出审计＋原20 epoch共31项1.889s、0skip；包含三补片六应用顺序/compile与真实组合、OFF、floor/错ACK、goal/clock清理、原receipt、错误GID/缺回执/序号/载荷及空图反例。独立最初6缓存＋20 epoch共26项1.526s过；独立CPP/Python原包关联和3收包局部过。不重跑未改124项或全机器人实验。ACK早于planNextWaypoint的失败分支是语义边界；固定planGlobalTraj至少构造两点，其cols<2返回false对合法当前输入未证明可达，未作为已native复现缺陷。

**收尾异常未掩盖：** 最终三个自有PID241317/planner、241318/trajectory、241319/receipt均已wait回收、/proc消失；planner/witness exit0，但traj_server exit-11，日志在SIGINT后报datawriter与publisher handle析构错误。旧两失败组trajectory为-6，无GID正向组为SIGTERM后-15。原报告曾仅processes_reaped=true/exit0，独立审核指出其不代表正常退出；原始summary不改写，新增independent-cleanup-audit.json，全部native_shutdown_ok=false。当前探针分开检查正常退出，非零退出不再仅因回收成功而返回诊断通过；已有最终收包关联仍有效，整个原生生命周期验收未过。

```sh
source /opt/ros/jazzy/setup.bash
source /home/muqiao/.cache/ros2-drone/ego_ws/install/setup.bash
cd /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-tools
cmake -S ros-ack-witness -B /home/muqiao/.cache/ros2-drone/ros-ack-witness-build -DCMAKE_BUILD_TYPE=Release
cmake --build /home/muqiao/.cache/ros2-drone/ros-ack-witness-build --parallel 2
/usr/bin/python3 drone-ros-ack-probe.py --output /tmp/drone-native-ack-new --receipt-witness /home/muqiao/.cache/ros2-drone/ros-ack-witness-build/drone_ros_ack_witness
# 无需ROS节点；对已保留的原生记录进行受控处理乱序回放。
/home/muqiao/.cache/ros2-drone/venv/bin/python drone-ack-order-replay.py --recording output/drone-committed/7d33e778-f0ef-45a5-950b-b7528b6c78ee --output /tmp/drone-ack-replay-new
```

没有SDK/PX4/Gazebo、解锁或飞行；原三冻结源c866441/d6f12ad/e0444f6 clean，EPOCH修补未部署。临时源码自动回收，六组约0.3MiB小原始证据保留忽略output；约4.7MiB独立构建缓存仅含当前可复用收包器与元数据，无重复大包或新渲染。原缓存源码的既有dirty、旧失败和遥测保留。Knowledge=already_covered，沿用Wiki/ROS2 与 FishBot§20；Jazzy回调差异等兼容事实留项目，不写memory。本对话独立审查，无跨聊天。

Next/owner：根Codex先定位原生traj_server退出时publisher/datawriter生命周期异常，制作最小独立修补与无解锁复验；保留原退出失败。随后沿当前逐消息GID取证，补多生产者/重启下的候选失效与在线来源绑定。完整缓存期限、可行备份、原生空中采用、完整M3和动态闭环仍未完成，不解冻部署。 整体plan active。


## Flight.run → recover 缓存替换链路复核（2026-10-28）

按用户指定链路复核冻结flight.py与既有默认OFF REPAIR补片。本轮只读执行源码、复验现有夹具并重算历史SDK原包；未修改飞行行为、未部署补片、未启动SDK/PX4/ROS/Gazebo或飞行。

| 分支 | 实际顺序与缓存结论 |
| --- | --- |
| 业务取消/普通故障 | run捕获CancelFlight或Exception；满足drone与armed/arm_requested条件后进入recover。PVA等待helper先取消并收拢本地await，不将它当作远端撤回 |
| 仍持有Offboard | recovery_hover → 核定位 → 当前位置setpoint → setter返回并更新command_position/reference → planner /stop → 新观测与回退/降落验证。/stop不是SDK缓存清理接口 |
| 已失去Offboard | 确认armed → action.hold → 位置setter → offboard.start → 遥测确认OFFBOARD → planner /stop。位置缓存替换与重新获得控制权分别确认 |
| 恢复setter pending/报错 | reference仍可能是旧PVA；SDK可能尚未接受，也可能已接受但丢响应。补片用recovery_command记录unknown并走block_recovery暂停/清理，不继续planner /stop或声称落地；OFF维持原等待行为 |
| 定位不可用 | 当前位置指令尚未下发就进入block_recovery；因此此时旧PVA仍可能保留，不能声称恢复一开始就清缓存 |
| 已落地且disarmed | recover提前返回，不必替换PVA；依赖后续SDK关闭，单独的落地状态不等于缓存为空 |
| 外部Task.cancel() | CancelledError传播并进finally清理，不自动业务recover；ON清旧landed/disarmed，标failed/task_cancelled。不能把它等同网页业务取消 |

setpoint只在SDK调用成功返回后更新Python reference；报错时不能由reference反推SDK真实缓存。旧PVA与当前在途候选的期限保护不等于原生SDK硬TTL。恢复RPC的wait_for依赖协程配合取消，也不是对远端执行的回滚或绝对截止保证。生产close_mavsdk调用原owner的析构并wait服务器；历史SDK探针刻意将该关闭延后，故不构成生产清理链验证。

本轮现有六模块共51项7.611s、0跳过通过：recovery_cache_chain、recovery_rpc_guard、recovery_tail_rpc、pva_rpc_guard、sdk_state_wait_probe、sdk_pva_wait_probe。覆盖真实run/recover方法与显式替身；asyncio慢任务提示不作为控制延迟实测。复验入口：

```sh
cd /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-review-tests
PYTHONDONTWRITEBYTECODE=1 /home/muqiao/.cache/ros2-drone/venv/bin/python -m unittest test_drone_recovery_cache_chain test_drone_recovery_rpc_guard test_drone_recovery_tail_rpc test_drone_pva_rpc_guard test_drone_sdk_state_wait_probe test_drone_sdk_pva_wait_probe -q
```

对前述65850c7c、19798d4f、31e56157、73b6bb73四UUID的sdk-cache-peer.jsonl按各自原phase_results窗口重新调用现有wire_checks，全部通过，计数分别2/2/4/0、3/4/0、4/4/0、3/3/0，arm=0。此次是历史原包重算，不是新SDK试验；坐标、mask/frame/target/yaw及窗口完整性沿用既有检查。没有新发现需改写发送/恢复逻辑的反例。

Remaining/Next：恢复位置setter自身延迟/接受后丢响应尚无同级真实SDK故障注入证据，替身已覆盖但不可升级为远端缓存已知；生产SDK关闭及实际停稳/落地也未获本轮证明。下一步可复用既有position relay注入，在无解锁synthetic peer里走真实run→recover的恢复setter失败分支。原生traj_server退出异常仍是另一未完成项，本轮未处理；完整缓存期限、可行备份、M3和动态闭环仍未通过。owner为当前根Codex。

收尾：临时源码由既有TemporaryDirectory夹具清理，无新运行服务、大文件或可删重复产物；历史原包保留。SO101在途station-execution.cjs修改完整保留，不并入此次文档交付。Knowledge=already_covered，沿用Wiki/ROS2与FishBot§20的回执/缓存/物理结果分层，不写memory。

### 本次指定链路复验：补返航嵌套出口（2026-10-28）

再次定点读取冻结 `flight.py` 的 `setpoint/run/recover/close_mavsdk` 及既有默认 OFF REPAIR。冻结源仍为 c866441，未修改、未部署；本次只增加现有恢复夹具的一项回归，包含返航中业务取消、返航故障两个子例。首 PVA 经真实 `Flight.setpoint` 方法写入显式替身缓存，然后由 `run` 捕获操作员返航，分别进入 `cancel_during_return_home`、`return_home_fault`。两子例均先成功位置替换并更新 reference，再执行 `/stop`，各只替换一次；恢复观测在明确夹具边界结束，最终 failed、无落地证明。

相关六模块本次 **55 项、5.331s、0 跳过通过**，命令沿用上节。其余检查覆盖业务取消、源期限失效、位置 setter pending/接受前失败/接受后丢响应、定位失效、控制接管失败、暂停和清理失败、已落地与外部 Task.cancel。SDK 报文结论沿用下节已录真实原包，不把本次替身复验写成新 SDK 试验。

缓存链结论保持：`run` 业务异常 → `recover` 核定位 → 位置 setter 成功 → Python reference 更新 → planner `/stop`；已失控时另需 hold/start/遥测确认。定位失效可在替换前阻断；RPC 失败时远端效果未知。`/stop` 不是 SDK 清缓存，Python await 取消也不是远端撤回；未确认的远端 PVA 请求是否可能迟到覆盖恢复位置，仍不由本组证明排除。生产 SDK 关闭、实际停稳和安全落地继续单列待验，原界未放宽，动态闭环未通过。

本次未启动 ROS/SDK/PX4/Gazebo 或飞行。测试临时副本自动清理。Knowledge=already_covered，沿用既有回执/缓存/物理结果分层；具体状态只更新项目记录。


## 恢复位置RPC未知效果：真实SDK注入（2026-10-28）

扩展现有drone-sdk-state-wait-probe.py的可选--recovery-response-fault，复用原PositionResponseFault relay，仅恢复位置setter走relay。初始位置与首PVA仍直连；planner HTTP/to_thread和原run/recover均实际执行，pose/clock/armed/场景暂停为显式夹具。原冻结执行源和默认OFF REPAIR未修改、未部署；没有PX4/Gazebo或飞行。

| UUID（忽略output/drone-committed/下） | 注入 | pending／恢复未确认后／迟到HTTP后／显式stop后 |
| --- | --- | --- |
| 3ee2ab75-6a32-4fea-8e83-5f2e4517d473 | 恢复位置未转发 | 3 PVA／3 PVA／4 PVA／0 |
| df7aefd7-f841-4c6f-ab76-de18c0079240 | SDK接受位置后扣响应 | 2 PVA／2 position／4 position／0 |
| 7fea4075-ae75-4160-a635-20088d945b36 | 原默认无故障对照 | 2 PVA／2 position／4 position／0 |

PVA为mask2048、NED P=(0,1,-1)、V=(.1,.2,0)、A=(0,.01,0)、yaw≈π/2-.25；position为mask2552、P=(0,0,-1)、yaw≈π/2；frame1、target7/component1。原包独立重算窗口计数、活动值及恢复顺序一致。窗口排除前100ms，只用于稳定观察，不是容差或控制上界。

两故障组恢复RPC均只尝试1次、未返回；host调用约500.618/501.536ms，使用本探针显式.5s选项，非生产硬期限。after组原relay记录SDK result1；应用两组均unconfirmed/remote_effect=unknown，reference仍旧PVA，未调用planner /stop，随后recovery_blocked并经过原finally。无故障组位置返回后reference才切position，/stop恰1次。report的fake wall100不可用于实耗时；原包/host时间与SDK result分别保留。

故障组在恢复setter等待期间释放新鲜且数值不同的迟到HTTP响应，原client实际读完、无错误；只有原1条PVA调用，未因迟到响应重新派发。前轮未确认恢复时的旧PVA持续重发已在真实SDK复现；synthetic pause不停止SDK报文，不能据此声称实际暂停、制动或落地。生产close_mavsdk仍刻意延后给探针owner，本组不验证生产清理。

首轮af53fb7b-d3e0-4477-8589-4c6ba58e716a保留failed证据：恢复.5s后再等.22s释放HTTP，加上此前.24s，超原/state .8s网络超时；fresh_late_response_received=false使整组exit1。修复仅将故障组释放HTTP前移到恢复RPC等待期间，不改原网络超时、恢复预算或验收门槛。

局部新3项覆盖两种远端结果、迟到异值PVA、缺窗口及stop后多包；相关最终检查与下节原生检查合计26项1.506s/0skip通过。drone-sdk-state-wait-probe.py不加选项仍是原成功替换场景，已实际新SDK复验。三最终SDK版本均4.0.5，arm=0、failed无落地，PID304923/305240/305501均wait回收exit-15，SDK/HTTP/relay端口关闭；初始失败PID301769也已回收。独立读回见各目录independent-recovery-audit.json。

```sh
cd /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-tools
# 使用新UUID目录；另将before_forward换成after_forward复验另一种效果。
/home/muqiao/.cache/ros2-drone/venv/bin/python drone-sdk-state-wait-probe.py --output /tmp/drone-recovery-new --recovery-response-fault before_forward
```

该组补上恢复setter超时的SDK缓存证据，不授予完整TTL、实际安全备份或动态资格。


## traj_server静态publisher析构：独立修补与原生A/B（2026-10-28）

完整GDB记录705594aa-d060-4fc7-89ad-b14a410a447a无曲线输入也复现SIGSEGV。回溯进入__run_exit_handlers → PublisherBase析构 → NodeBase析构 → rcl_node_fini/rmw_destroy_node → FastDDS destroy_participant，再于pthread_mutex_lock崩溃。GDB本身退出0不代表inferior正常；原installed binary及此前-11/-6/-15失败均保留。

新增默认OFF的patches/drone-traj-publisher-lifetime.patch：仅在spin返回、局部node仍存在时可选pos_cmd_pub.reset()，避免全局publisher等到静态退出才释放。它不宣称在Context shutdown前执行，因为SIGINT可能已先关闭Context；不改变轨迹计算或发送。没有重写类/执行器，也未扩大到其它ROS对象清理。

现有ros-ack-witness/CMakeLists.txt增加默认OFF的DRONE_BUILD_TRAJ_LIFETIME_PROBE目标，使用明确提供的临时traj_server.cpp路径及已安装bspline_opt。原上游为CRLF，准备时仅规范独立副本为LF后应用补片；实际副本与当前原源规范化＋补片结果逐字节一致，原源无新lifetime参数。首次链接因原静态bspline库OpenMP符号未导出失败，显式链接OpenMP::OpenMP_CXX后成功；只编译该目标，没有重建EGO workspace。现有ConstPtr弃用警告保留。

| 证据目录UUID | 对照 | 实际结果 |
| --- | --- | --- |
| 51bfecd3-7271-47d7-b90d-1d22aa7536aa | 新二进制，开关false，无输入 | ready后SIGINT，exit-11，复现datawriter/datareader析构错误 |
| f4500d83-c36c-4da1-836d-98544bde43d7 | 同二进制，仅开关true，无输入 | ready后SIGINT，exit0，无上述错误 |
| a29a6356-a42a-4d96-8fd2-c333b9b05f91 | 同二进制ON＋原native两目标＋CPP见证 | ACK2/曲线2/PVA15唯一匹配CPP源时间/序号/载荷及graph GID；planner/trajectory/receipt均exit0、/proc不存在，native_shutdown_ok=true |

只把这组Jazzy/FastDDS退出复现晋级为已验证独立候选，不宣称修复所有RMW退出问题。原native收包器仍用现有二进制；本次建出的trajectory路径、参数、编译/链接配置及独立回执/退出核对保存于最终目录independent-native-lifetime-audit.json。probe新增可选--trajectory-executable与--release-trajectory-publisher，默认仍运行原installed binary。

```sh
# 在独立目录创建规范化副本；这些路径的旧测试进程须已停止。
source /opt/ros/jazzy/setup.bash
source /home/muqiao/.cache/ros2-drone/ego_ws/install/setup.bash
python3 - <<'COPY_SOURCE'
from pathlib import Path
source = Path('/home/muqiao/.cache/ros2-drone/ego_ws/src/ego-planner-swarm/src/planner/plan_manage/src/traj_server.cpp')
copy = Path('/home/muqiao/.cache/ros2-drone/traj-lifetime-source/traj_server.cpp')
copy.parent.mkdir(parents=True, exist_ok=True)
copy.write_text(source.read_text())
COPY_SOURCE
cd /home/muqiao/.cache/ros2-drone/traj-lifetime-source
git apply --check --whitespace=error-all /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-tools/patches/drone-traj-publisher-lifetime.patch
git apply /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-tools/patches/drone-traj-publisher-lifetime.patch
cd /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-tools
cmake -S ros-ack-witness -B /home/muqiao/.cache/ros2-drone/ros-ack-witness-build -DCMAKE_BUILD_TYPE=RelWithDebInfo -DDRONE_BUILD_TRAJ_LIFETIME_PROBE=ON -DDRONE_TRAJ_SERVER_SOURCE=/home/muqiao/.cache/ros2-drone/traj-lifetime-source/traj_server.cpp
cmake --build /home/muqiao/.cache/ros2-drone/ros-ack-witness-build --target drone_traj_lifetime_probe --parallel 2
/usr/bin/python3 drone-ros-ack-probe.py --output /tmp/drone-lifetime-new --receipt-witness /home/muqiao/.cache/ros2-drone/ros-ack-witness-build/drone_ros_ack_witness --trajectory-executable /home/muqiao/.cache/ros2-drone/ros-ack-witness-build/drone_traj_lifetime_probe --release-trajectory-publisher
```

最终26项1.506s/0skip覆盖state-wait wire6、原SDK relay5、恢复RPC8、PVA wire3、native收包/退出4；补片在规范化临时副本check/apply通过，代码/文档diff检查通过。原生A/B和两目标属于实际进程试验，单列于测试计数之外。完整来源仍source_provenance_verified=false：逐消息生产者回执不等goal/session或在线来源准入；多生产者/重启仍是下一项。

全部自有SDK/native/GDB进程已回收，不杀其它任务；八组新增小证据约408KiB忽略保留，必要失败/原包不删。现有独立CMake缓存从约4.7MiB增至约49.4MiB，保留当前可复用binary/object及12KiB规范化源，失败链接中间文件已被同一路径成功构建替代，无重复大包。冻结drone c866441/PX4 d6f12ad/GCOPTER e0444f6均clean；ego_ws既有dirty保留，原traj_server仍只有既有时钟改动、未部署lifetime补片。SO101 station-execution.cjs在途改动保留。

Next/owner：根Codex在隔离ROS入口补多生产者/重启后候选失效与在线来源绑定，保留安装版退出失败和独立候选边界。可行备份、原生空中采用、完整M3与动态闭环仍未完成，整体plan active。

Knowledge=updated：已修订并读回Wiki/ROS2 与 FishBot“rclcpp 静态析构：先核真实释放时机”，同步开发知识入口新触发词；具体运行事实留项目，不写memory。

知识库交付边界：两原页除本次小段外已有大量跨任务未提交内容（ROS2页总diff为516增/1删）。本次知识段和入口已本地读回；不盲提交整页或其它Wiki。保留全部存量，由根Codex后续按知识库原任务审阅整合，最短入口为两文件git diff；工作台/研究源码交付独立执行。


## 多来源与重启：同ID曲线污染及观察式隔离（2026-10-28）

新增drone-native-source-probe.py，复用独立traj_server生命周期候选、CPP收包器和临时Sidecar真实方法夹具。两个独立rclpy发布进程发同一traj_id=1、相同start10s但X几何分别偏移0/10/20/30m的诊断曲线；原生traj_server实际求值并发布PVA，Sidecar真实on_goal_ack/on_bspline/on_command/state参与。clock话题最终隔离到唯一prefix；domain186与全部命令topic隔离。无EGO真实规划、SDK/PX4/Gazebo或飞行，感知/位姿/状态新鲜度为显式健康替身，不能写成完整Sidecar/真实地图闭环。

首轮8e06b0dc-bd77-4b4b-9976-c0f037397b8b只证明回调缓存污染：短曲线已过源有效期，未检查/state ready。保留该记录，不用其exit0声称控制候选可用。后续只把诊断曲线时域改到[10,40]并保持替身感知新鲜，以隔离来源问题；没有改变原sample/end/速度/高度/占据门限。

| 最终同版探针UUID | 模式与实际结果 |
| --- | --- |
| 57f379a4-5b26-494f-b127-918eae2a519d | guard OFF：预期A、第二B、B同名重启、A同名重启未新ACK四阶段均沿用goal-A且/state ready；四个Bspline GID不同，PVA始终来自同一原生轨迹服务 |
| d77309ed-2e39-42fd-a4f7-d27e2464021f | guard ON：预期A正常采用；观察到额外/变化来源后清目标/ACK/曲线/setpoint并轮换epoch；三故障阶段未复活goal-A。恢复单一预期来源后，新goal-B＋新ACK可采用 |

独立raw复核：baseline389条PVA、guard357条PVA全部唯一匹配CPP源时间/序号/完整载荷，每组仅一个PVA GID。baseline有237个外来位置样本继承goal-A；guard本轮0个。计数只描述本轮序列，不是成功率、性能或任意乱序保证。CPP witness新增曲线knots与control_points；曲线按全几何匹配，避免同ID/起始时间但不同几何误归属。ACK baseline仅123:0；guard另有新目标18050000000:0。原始链与进程身份见各目录ros-events.jsonl、witness.log、native-source-probe.json、independent-source-audit.json。

### 默认OFF补片边界

扩展现有EPOCH补片，新增DRONE_SOURCE_GRAPH=1；该开关同时启用原局部epoch。Sidecar构造生成本runtime唯一规划器/轨迹节点名，start_planner显式remap。三类输入的图查询要求每类恰一个非零GID、预期节点名及根namespace；在ACK/曲线/PVA回调、tick与/state读点观察。缺失/多发布者/不符/查询失败或已绑定GID变化时，按原单机owner清当前任务队列、待ACK曲线、曲线时间、目标、ACK与setpoint，轮换epoch并通知旧goal stop；不增加SDK写入口。连续相同故障不重复轮换，输入恢复后可接新目标，没有全工作台前序锁。

/state仅在开启时增加source_graph诊断与原始观察/异常；OFF保留原行为/schema。Flight已有epoch检查用于拒旧goal回复；图观察不直接取消SDK已接受指令，恢复仍沿原run→recover。

**未闭合：** 该guard只处理已经观察到的图变化。发布者已消失但消息仍在DDS队列时，rclpy回调缺逐消息GID，当前图可能又是正常单一来源，外来旧曲线仍可进入。新局部检查明确保留这个known-gap见证；source_provenance_verified始终false。完整Sidecar构造/进程启动、消息来源准入、state分布式窗口及空中采用未验证；不得把观察式隔离当完整来源证明或Safety Shield。

最终56项4.953s/0skip通过：source graph7、原epoch20、首曲线7、native收包4、原revalidation18；其中含上述known-gap及OFF原行为见证，不是56项飞行验收。原三补片六顺序check/apply/compile与组合通过。初次重生成补片扩宽了flight.py未改区域上下文，导致REPAIR先应用时649行冲突；恢复原flight补片片段后最终全过，未改Flight行为或测试标准。一次临时修补命令cwd错误已纠正，失败输出不当成功。

```sh
source /opt/ros/jazzy/setup.bash
source /home/muqiao/.cache/ros2-drone/ego_ws/install/setup.bash
cd /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-tools
cmake --build /home/muqiao/.cache/ros2-drone/ros-ack-witness-build --target drone_ros_ack_witness --parallel 2
# 使用两个新UUID目录；不加开关是旧路径反例，加开关验证观察式失效。
/usr/bin/python3 drone-native-source-probe.py --output /tmp/drone-source-baseline-new
/usr/bin/python3 drone-native-source-probe.py --output /tmp/drone-source-guard-new --source-graph-guard
cd ../workbench-review-tests
PYTHONDONTWRITEBYTECODE=1 /home/muqiao/.cache/ros2-drone/venv/bin/python -m unittest test_drone_source_graph_guard test_drone_command_epoch_patch test_drone_ack_curve_buffer test_drone_ros_ack_probe test_drone_command_revalidation_patch -q
```

收尾：本轮五组共约2.1MiB小证据原地忽略保留（包括首次时域不足和两组修复中间对照），独立CMake缓存约95.9MiB含当前两个可复用binary/object，旧object同路径被重建替代，无重复大包/渲染。全部自有ROS进程已回收、最终两组各六进程均exit0；临时执行源自动删除，未部署冻结源。SO101在途station-execution.cjs本轮从13行扩为17行，新增编辑step id导入对照逻辑；定点diff与node --check通过，原E2E未验，完整保留不抢先提交、不联系其它聊天。

Knowledge=updated：已修订并读回Wiki/ROS2 与 FishBot第19节的来源链段落，同步开发知识入口“可信PVA接收外来曲线/traj_id重用/同名发布者重启”；具体实验留项目，不写memory。两知识原页已有大量跨任务dirty，保留本地修订，按既有根知识库任务整合，不盲提交整页。

Next/owner：根Codex核逐消息来源准入，优先复用现有CPP MessageInfo完整曲线收包与已有epoch/原输入接口；验证“图已正常但队列仍有旧来源消息”的负例。必须同时核曲线、ACK、PVA链，不能只信最终PVA发布进程。冻结源不部署，不解锁；全链TTL/可行备份/生产关闭/原生空中采用/M3和动态闭环仍未完成，整体goal active。

收尾更新：共享工作树的SO101既有任务已将Station17行与自身进度提交为8fc0569；已定点读两文件diff和交付说明，本无人机轮只做语法核对，不把其物理/E2E结论计入本轮验收。保留该提交，本轮串行追加，不覆盖、不跨聊天联系。

## C++逐消息入站与完整Sidecar入口（2026-10-28）

复用现有只读rclcpp MessageInfo见证器、原epoch/ACK缓存和Sidecar进程owner。在默认OFF的EPOCH补片内新增 `native_receipts.py`；只有 `DRONE_NATIVE_RECEIPTS=1` 才启用，并同时启用原epoch与source graph观察。未修改或部署冻结drone c866441、PX4 d6f12ad、GCOPTER e0444f6；既有EGO算法缓存dirty保留。

### 实现边界

- C++保留三类消息的原始DDS GID、source timestamp、publication sequence及同机单调接收时刻；新增曲线/PVA精确整数 `source_stamp_ns`。可选100ms心跳携带实际订阅匹配数，默认关闭；CPP不发布应用控制命令。
- 启用后不创建Python的ACK/Bspline/PVA直收订阅，三类回调直接调用也被拒绝。Sidecar用既有spawn/close管理CPP子进程，并从原日志按增量读取完整回执；缺binary、进程退出、连接未就绪、心跳过旧、日志截断或必需字段错误均明确未就绪，不静默回退到旧输入。
- 逐消息GID需匹配当前已绑定endpoint，保留原时间与序号，不让重复序号或上轮旧日志刷新有效性。当前图健康而消息仍来自已离图旧生产者时，清当前goal/ACK/候选/队列/setpoint并换epoch；健康恢复后允许独立新目标和新ACK，不设跨任务锁。
- 登记可信完整曲线后，以PVA原header整数时间重算位置/速度/加速度，含末端零VA保持；三阶数值不对应即 `native_pva_curve_mismatch`。`1e-6`仅为两个求值器的数值同一性容差，不更改V/A/Z/占据或飞行净空硬界。保留ACK先到/曲线先到的原缓存机制。
- 原生输出来源和曲线数值关系仍不等于完整上游输入合同。yaw只检查有限值，未证明原生goal/session、未来地图、完整原生输入接纳、SDK缓存TTL、飞行跟踪或备份安全。`source_provenance_verified` 与 `flight_accepted` 继续false。

### 原生证据与失败保留

| UUID（均在忽略output/drone-committed下） | 结果与范围 |
| --- | --- |
| a44f726b-d705-4f4a-9886-69f64391dbb9 | 首轮新输入已准入108条PVA，但图恢复时CPP连接仍未匹配，新目标正确拒绝；探针失败。仅将探针等待改为实际channel健康，未放宽门槛 |
| adfb41fb-7a73-446a-98d5-a2cdbcd59ece | 原生轨迹服务＋多个ROS生产者/重启五阶段通过；独立受控投递一条真实CPP旧来源曲线，接收年龄225930112ns，当前图单一正常，仍因GID不符拒绝，goal/setpoint清空、epoch变化。原包全部字段保持，非自然网络乱序 |
| 3b8cd813-13dd-4840-a958-18e707f66ec4 | 完整Sidecar探针未复制冻结planner.yaml，未启动规划器；已补复制，失败原件保留。另首次临时import路径顺序不符在构造前失败，无ROS进程 |
| 74a7ecec-c6fa-4980-989f-fb911e1c5057 | 完整构造中ready时FSM仍INIT，目标后抛std::length_error，planner exit250、无曲线。未取得旧崩溃栈，不能把数学成因定案 |
| 0e668ad6-64c1-4c7d-9018-a4a6859d9893 | 仅探针等待原生WAIT_TARGET后，完整HTTP两目标通过，三个进程均0；对照支持启动竞态解释，非飞行 |
| f745e04d-ee15-4541-a179-3a3dc09a54f8 | 最终候选自身在INIT返回planner_waiting_for_odometry，探针无额外FSM等待；实际构造/HTTP两次202/原生ACK2、曲线2、准入PVA3通过，三自有进程均0并回收，HTTP端口已关 |

最终完整探针复用原CLI解析、Sidecar构造、start_planner、HTTP Handler和close；trajectory仅替换为既有独立生命周期候选binary并显式开启release参数，原installed未换。输入为真实ROS transport的理想静止pose/clock/单点cloud，相机内参与depth健康为明确替身；未运行ros_gz、真实深度、MAVSDK、PX4或Gazebo，未证明到点或任务飞行。

最终入站模式在INIT拒新目标且不排队，观测到WAIT_TARGET后才允许；此健康检查仅本候选ON生效，OFF与原graph-only行为保留。FSM状态仍由原通道观测，非新增逐消息身份认证；本次WAIT_TARGET来自自有原生规划器记录，不升级为所有来源场景的完整健康证明。

两最终目录各保存 `independent-native-admission-audit.json`。独立读取原CPP日志，确认受控旧包逐字段相同、未超原2s接收窗、当前GID不同；新目标的ACK/曲线/PVA各能唯一关联原GID/序号/时间，按精确源时间重算PVA。完整两目标的最大数值误差≤1.12e-16（位置）/2.78e-17（速度）/9.87e-32（加速度）；旧包前的可信点亦到数值精度。原生7＋3进程正常退出、当前/proc无自有PID；历史诊断计数不当物理结果。

### 最小复验

最终六相关模块 **70项、4.477s、0skip通过**，包括native ingress14项、graph-only known-gap、OFF行为、ACK顺序和六补片应用顺序/组合。CPP当前目标单独增量构建成功。无需重跑其他机器人实验。

```sh
cd /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-review-tests
PYTHONDONTWRITEBYTECODE=1 /home/muqiao/.cache/ros2-drone/venv/bin/python -m unittest test_drone_native_receipts test_drone_source_graph_guard test_drone_command_epoch_patch test_drone_ack_curve_buffer test_drone_ros_ack_probe test_drone_command_revalidation_patch -q
# 原生无飞控探针，在workbench-tools目录、已加载Jazzy/ego_ws环境执行；OUTPUT使用新UUID目录。
python3 drone-native-source-probe.py --native-receipts --domain-id 186 --output "$SOURCE_OUTPUT"
python3 drone-sidecar-native-probe.py --domain-id 188 --output "$SIDECAR_OUTPUT"
```

收尾：小原包/失败记录原地保留，不提交Git；当前可复用CPP构建缓存约96.6MiB保留，测试临时源回收，无新大包或渲染。逐消息候选六文件在途工作本轮完成审阅、局部验证与原生入口核对后串行交付，仍默认OFF；冻结源未部署，未恢复其他聊天/子Agent。Knowledge=updated，原Wiki/ROS2与FishBot来源链段落及开发知识入口补逐消息数值核对与FSM就绪触发，实际读回见项目进度；知识库既有跨任务dirty保留，不盲整页提交。

Next/owner：当前根Codex核HTTP `/state` 快照到Flight使用之间的epoch/时间窗口，复用已有迟到HTTP与SDK缓存夹具，先闭合跨组件失效传播；继续核生产关闭与晚到远端PVA，不复派效果未知的控制请求。全链TTL、可行备份、实际状态/地图/终端资格、MINCO在线采用、M3与动态飞行仍未完成；本片不解除冻结、不将局部成功替代整体目标。

## 分布式快照缺口与生产SDK关闭见证（2026-10-28）

### 已确认缺口，尚未修复

新增 `test_drone_state_epoch_window.py`，复用原source-graph/ACK与RecoveryHarness，临时应用既有EPOCH＋REPAIR；Flight和Sidecar各持独立epoch对象。真实方法与真实loopback HTTP均复现：

1. `/goal`回执为epoch A，`/state`生成ready/A快照，PVA也标A。
2. 快照生成后，Sidecar真实 `invalidate_command_source` 旋转为B并清目标/曲线/队列/setpoint；随后才将旧快照交给Flight。
3. Flight本地clock epoch未变，样本源时刻与其仿真时刻均10.15，旧快照内部身份全部一致，仍派发一次PVA。
4. 下一次读到B才抛 `command_epoch_mismatch`，进入原recover，位置替换后 `/stop`。最终failed，观测在显式夹具边界终止，无落地。

反向对照：失效在快照生成前，0条PVA；样本到达时已过原.3s发送前门槛，同样0条PVA。首轮过期用例原预期写成helper错误，但实际先被goto发送前复查拦截；仅修正测试预期，未改执行器。局部known-gap测试成功意味着缺口被稳定观察，不是缺口已关闭。追加普通GET只移动最后一次读取/使用的窗口，不提供原子授权；这轮不靠重复请求或新状态存储伪装修复。

### 真实SDK、HTTP与原Flight finally

`drone-sdk-production-close-probe.py`复用既有SDK cache transport、上述源节点夹具和原HTTP读取函数。Flight实际运行临时EPOCH＋REPAIR组合的run/goto/setpoint/recover/finally；其 `close_mavsdk` 及 `atomic_json` 从冻结源码原样提取，代替原探针刻意延迟关闭的替身。RPC包装只记录调用并转给实际System；探针不调用解锁，合成peer拒绝所有arm请求。源图、ACK/曲线、pose/clock/armed/Offboard遥测、暂停仍是显式替身，无ROS/Gazebo/PX4。

| UUID（忽略output/drone-committed） | 原报文窗口：旧PVA／生产关闭后 | 自有SDK结果 |
| --- | --- | --- |
| c9fe05d2-8733-4588-9a22-2155f3f8decb | 5／0；首版仅mask判别，原包保留 | PID528582、exit-9 |
| 45110d28-4c3b-41f9-aad2-4a26df39d3d6 | 4／0；补完整活动PVA、frame/target/yaw判别 | PID530990、exit-9 |
| 193049a0-eab1-4bcc-a913-c309d65d0298 | 最终4／0；另保存HTTP端口/worker身份供独立复核 | PID534708、exit-9 |

固定新epoch响应被显式扣留约.3墙秒，让SDK缓存重发可见；不是自然延迟或实飞时限。最终旧PVA在约.20s稳定窗内4包，mask2048/frame1/target7:1，ENU转NED三阶量和yaw均匹配原旧快照。只调用1次PVA RPC；释放新epoch响应后恢复position RPC成功，原run finally调用生产close，之后约.25s窗0包。两窗口各排除前100ms仅用于观察对齐，不放宽任何控制/飞行门槛。快照里的cache字段仍为夹具，真实SDK结论只来自原报文和实际RPC。

已安装mavsdk-grpc4.0.5的System析构实现是kill自有server并重新初始化Python实例，因此-9是该路径的预期结束方式，不称正常退出或受控降落。原close在析构前保留Popen，再wait并写mavsdk-process.json；最终记录pid/argv/task、stop_requested_by_executor和cleanup_wait_confirmed与原sdk-process一致。生产close返回前已读回-9；外层transport的兜底清理此时只见已退出实例。本轮补上该有限失败/恢复场景的真实生产SDK server关闭，未证明所有清理异常或空中停稳。

最终 `independent-production-close-audit.json` 独立重读sdk-cache-peer.jsonl、RPC/event时间、两epoch快照与生产记录，15项通过：数值/序号与4／0窗口一致、失效先于PVA调用、原owner被生产close回收、恢复RPC→close→观察窗顺序成立，/proc不存在、HTTP/gRPC端口已关、worker已结束、arm命令0。原任务failed/未落地，`gap_fixed=false` 与 `flight_accepted=false` 保留。

相关最终五模块 **63项5.960s/0skip通过**（其中4项新增，含两条known-gap见证），真实SDK回合不算单测或飞行。复验：

```sh
cd /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-review-tests
PYTHONDONTWRITEBYTECODE=1 /home/muqiao/.cache/ros2-drone/venv/bin/python -m unittest test_drone_state_epoch_window test_drone_command_epoch_patch test_drone_state_wait_guard test_drone_pva_rpc_guard test_drone_recovery_cache_chain -q
# 在workbench-tools目录，OUTPUT指向新UUID目录；只接合成peer，不连接飞控。
/home/muqiao/.cache/ros2-drone/venv/bin/python drone-sdk-production-close-probe.py --output "$OUTPUT"
```

收尾：三SDK实例均已回收，最终端口与线程关闭；三组约208KiB独有小原包/记录保留，无新大缓存或临时帧，测试临时源自动回收。共享station-execution.cjs出现119增/3删的Carry QA在途改动，定点初读/语法检查通过、完整E2E未审；完整保留不混入本次提交、不联系其他聊天。三冻结源不变，不新增控制行为、默认开关不变。

Next/owner：当前根Codex沿已有MAVSDK owner等待/停止接口核失效传播与可观察时限，让源失效能到达实际发送/缓存owner；先核可复用通道及剩余窗口，不把二次GET或本地epoch比较宣称原子撤销。随后继续晚到远端PVA和可行备份/实际状态地图终端资格；本轮生产server关闭正例不代替安全停稳、落地、M3或动态闭环。Knowledge=updated，原Wiki来源链及入口补“自洽旧快照不等当前授权、SDK析构kill与外层terminate分开”，项目运行数值只留项目，知识库大dirty保留。

## 既有HTTP变更等待 → Flight单owner恢复候选（2026-10-28）

新增默认OFF `drone-source-watch.patch`，在既有EPOCH＋REPAIR后应用；含SENDER的六种既有应用顺序也通过。`DRONE_SOURCE_WATCH=1` 才启用并启用原epoch/RPC等待复查。冻结源与installed入口未部署。

复用选择：MAVSDK setter是现有唯一写入口，不携带Sidecar epoch；原普通state快照已证有读取/使用窗口。因此复用现有Sidecar HTTP服务器、RLock和Python Condition增加 `/command-epoch?after=...` 变更等待，不新增服务、数据库或另一套控制owner。CommandEpoch.rotate通知等待者，含目标/stop、来源失效及源时钟换代；Condition等待释放原锁，回复写socket前也释放锁。

服务端最长.5s等待后重新取原state健康；客户端沿原.8s HTTP预算等待，保存服务端原单调观测时刻、实际接收时刻及epoch。2s观测年龄沿用已有本机输入新鲜度边界，不是飞行容差。客户端协程超时依赖事件循环和可取消await，非硬实时证明。

Flight在新目标后先建立监视，后续复用原 `check_command_wait` 在state/PVA RPC等待期间检查。监视器只锁存失效，不写飞控；换代、健康失效、丢失/过旧元数据、通道错误均抛回原run→recover。已在途RPC的远端效果继续unknown，不重试。原tasks owner负责取消/收拢；新目标清理旧watch，迟到旧响应不能给新watch重新绑定。关闭开关时已应用补片仍保留旧快照缺口，作为OFF对照。

### 本轮证据

| UUID（忽略output/drone-committed） | 结果与边界 |
| --- | --- |
| 82514df8-4490-48d4-a992-65e6e5035db4 | 首轮真实SDK通知传播通过；后只调整诊断命名，保留原件 |
| b9dd64b7-7db1-49db-9cda-2cddbb4ad215 | 最终ON：有效epoch下原PVA 3包；失效至生产关闭窗2包均为position/mask2552；关闭后0包。旧state响应仍被扣留时已完成恢复/生产close，之后原旧响应实际读完也未再派发PVA |
| 91705b89-ffd1-4f84-8e2a-12cecc5b6a50 | 最终OFF：原旧快照仍派发1次PVA RPC并重发4包，等待新epoch state释放后才恢复，关闭后0包；未把旧缺口伪装通过 |
| 945adb19-83cc-494e-8d0f-eb757167d13d | 完整原Sidecar构造＋真实HTTP＋native EGO/CPP：两目标/三段原回执成立；探针见证自有Condition确有等待者后POST stop，等待请求收到与stop回执相同的新epoch。三原生进程exit0、HTTP关闭；无SDK/PX4 |

最终ON的同机原时间读回：失效标记→通知接收1.405816ms，→恢复position RPC返回13.630359ms，→生产SDK关闭33.305390ms。这是该轮测量；.15s有效缓存建立、原state扣留和观测窗口均为显式夹具，不用于承诺端到端最坏时限或零旧包。初始快照与发送之间仍非原子，已远端接受请求也不能回滚；`distributed_epoch_gap_fixed=false` 仍保留。相对上轮，已证明无需等待被扣留的普通state响应，通知可驱动当前SDK owner恢复。

ON/OFF实际SDK均为4.0.5，PVA/position原活动字段、NED轴序、frame/target/yaw独立重算。ON仅1次派发时epoch匹配的初始PVA RPC，旧state在SDK关闭后才真正读完；无迟到再派发。探针的initial_valid_pva仅指身份/源龄期匹配，不代表该替身通过完整动力学/占据资格。SDK PID581542/581703及首轮573405均由原生产close kill+wait为-9并回收。原任务均failed、无落地；源图/ACK曲线/pose/clock/armed/暂停为替身，合成peer拒arm，arm命令0。此SDK试验与完整native Sidecar试验分别取证，未冒称同一完整ROS→PX4闭环。

三个最终目录各有 `independent-source-watch-audit.json`：ON17项、OFF12项、native18项原包/epoch/RPC时序/端口读回通过。native两个目标的ACK/曲线/PVA各唯一匹配原CPP GID与序号；自有PID578972/578997/578998均正常退出且/proc无残留。探针只在当前自有Condition上读Python `_waiters` 见证测试条件，生产补片不依赖该私有属性。

最终六相关模块 **75项10.193s/0skip通过**，新增watch12项含：无控制写的锁存、旧state挂起时恢复、PVA等待中断（接受前/后替身）、协议缺失/旧观测拒绝、同epoch健康失效、源时钟换代、通道断开、新目标取消旧watch、已应用但OFF原行为、真实shell导入与六补片顺序。首轮新目标测试仅手工换epoch却保留旧setpoint，被原健康检查正确拒绝；已改用真实目标Handler，未削弱检查。原生与SDK试验不计单测或飞行。

启动入口补核发现实际接线缺口：EPOCH新增根目录模块，原ego/run_sidecar.sh只将脚本目录交给Python。1c4d17fb-59d1-4b8f-af79-820b1dfda06d在空初始PYTHONPATH、真实shell --help下复现ModuleNotFoundError: command_epoch。EPOCH补片增加一行根目录PYTHONPATH，脚本目录仍优先；同条件复验exit0并含--runtime选项。原失败/修补后JSON与最终测试日志保留；--help不初始化ROS或启动飞行，不代替完整构造试验。测试copy_source仅补原launcher文件，CLI夹具另复制三既有ego模块，不编写替代实现。

```sh
cd /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-review-tests
PYTHONDONTWRITEBYTECODE=1 /home/muqiao/.cache/ros2-drone/venv/bin/python -m unittest test_drone_source_watch test_drone_state_epoch_window test_drone_command_epoch_patch test_drone_state_wait_guard test_drone_pva_rpc_guard test_drone_recovery_cache_chain -q
# workbench-tools目录下，两个输出各使用新UUID；native命令先加载Jazzy/ego_ws环境。
/home/muqiao/.cache/ros2-drone/venv/bin/python drone-sdk-production-close-probe.py --source-watch --output "$SDK_WATCH_OUTPUT"
python3 drone-sidecar-native-probe.py --source-watch --domain-id 188 --output "$NATIVE_WATCH_OUTPUT"
```

收尾：五组约384KiB独有小原包/CLI记录保留，临时执行源自动回收，无新大型缓存或渲染。一次相对路径补片写入及一次跨文件系统日志移动失败，均未改冻结源；改用绝对路径、日志copy/读回/unlink后完成。全部自有进程、HTTP/gRPC端口与worker已结束；三冻结源不变，Station Carry QA在途119增/3删保留不混提交、不跨聊天。Knowledge=updated，原Wiki来源链及入口补“变更等待由单控制owner消费、通知/缓存替换/物理结果分层”，实际读回记录在计划，知识库原大dirty保留，不写memory。

Next/owner：当前根Codex核在途PVA远端迟交与新通知共存：客户端取消不等远端撤销，复用现有before/after relay和本轮watch，确认恢复位置是否可能被后来接受的PVA覆盖。随后接实际状态/地图/终端和可行备份资格；不重复扩大普通GET/监视层，不把本轮传播候选升级为硬TTL、原子授权、安全降落或M3/动态通过。整体目标仍active。

## Flight.run → recover：在途PVA与缓存替换（2026-10-28）

结论：位置RPC返回不构成迟交PVA的顺序屏障。原补片下，SDK已发位置保持，之后一次原PVA迟交可覆盖缓存；Python reference仍显示position。使用受控非协作relay保留已经收到的同一protobuf，跨客户端取消后只投递一次，不重建或重试；这不是自然直连gRPC乱序的证明。

| 对照 / UUID | 原报文与结果 |
| --- | --- |
| 原候选 late_forward / 8476f799-c937-4be9-93fa-69556b552920 | pending位置4包 → 恢复位置5包mask2552 → 原请求迟交后PVA4包mask2048 → 生产关闭后0；PID686499/-9 |
| 原候选 after_forward / de65bccb-57bc-45bd-be6c-89c876501916 | PVA接受但响应丢失：4PVA → 恢复位置4 → 后窗4位置 → 关闭0；PID690218/-9，不能据此认为所有迟交已排除 |
| 修补候选 late_forward / 67fe1e61-29c5-4c90-9b0d-2302b6c48738 | unknown在途PVA走recovery_blocked，不写恢复position、不进入观察等待；原生产关闭PID700233/-9后才释放原请求，UNAVAILABLE、两个后窗均0 |
| 修补候选 after_forward / 5afeb7d8-8a95-4c9c-acd2-57db1204e474 | 原SDK已接受但客户端未确认，仍按unknown暂停/关闭；pending4PVA，关闭后0；PID701448/-9 |
| 明确返回后源失效 / d8199f73-a20d-45c2-8b22-9fb30c4b8d92 | 保留普通恢复：有效PVA3包 → 失效至关闭2包仅position → 关闭0；PID702107/-9 |

最小改动只在默认OFF的drone-source-watch.patch：await_pva_command记录rpc_started（本地发送任务已创建，不等于远端收到）；recover在recovery_hover之前检查最后一条已启动且unconfirmed/cancelled、rpc_returned=false、remote_effect=unknown的PVA。没有接收端epoch fence时，保存unfenced_pva，调用已有block_recovery暂停仿真，再由原run finally关闭SDK。保留原触发原因、failed/未落地，不宣称安全悬停。未派发拒绝、已返回PVA后发生源故障及开关OFF均保留原路径；不新增服务、监视器或生产开关。

SDK探针使用真实mavsdk-grpc4.0.5、实际RPC、loopback HTTP、原run/goto/recover/finally/close_mavsdk，MAVLink对端是合成peer。源/pose/clock/armed/暂停均为显式夹具，report中的simulation_pause_confirmed仅为替身结果；本轮没有PX4/Gazebo/解锁/飞行。原System析构kill及Popen wait证实本轮进程回收，不能替代物理暂停、空中停稳、落地、端到端硬TTL或原子撤销。暂停失败/进程死亡/已过暂停点的迟交窗口仍不具备完整保护证明。

五目录各independent-late-pva-audit.json重新读取原jsonl、RPC、报告、时序及端口/进程，20/18/19/17/14项全部通过；完整活动三阶量、frame/target/yaw与mask分别核，不用Python reference代替SDK缓存。五个自有SDK均原生产close为-9、/proc不存在、HTTP/gRPC/relay端口关闭；所有arm=0、failed且landed/disarmed=false。最终六模块77项18.039s/0skip通过，新增两项覆盖未派发及明确返回分支，六补片顺序仍过。工具expect仅选诊断判据，不改变被测恢复策略；baseline-source-watch.patch留在8476目录可回放原缺口。

```sh
cd /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station/workbench-review-tests
PYTHONDONTWRITEBYTECODE=1 /home/muqiao/.cache/ros2-drone/venv/bin/python -m unittest test_drone_source_watch test_drone_state_epoch_window test_drone_command_epoch_patch test_drone_state_wait_guard test_drone_pva_rpc_guard test_drone_recovery_cache_chain -q
# 每次选新输出目录。复现旧反例另加 --watch-patch 指向8476目录保留的baseline补片，并设 --expect overwrite。
/home/muqiao/.cache/ros2-drone/venv/bin/python ../workbench-tools/drone-sdk-late-pva-probe.py --mode late_forward --expect pause --output "$LATE_PVA_OUTPUT"
```

Next/owner：当前根Codex优先核原scene.pause真实调用的失败/超时是否仍能到达finally关闭，继续明确源失效到SDK关闭间的缓存窗口；不凭本轮停仿真策略晋级可行备份或M3。真实状态/地图/终端、MINCO在线与动态闭环仍未通过，三冻结源未部署。

收尾：五组独有证据约267KiB保留，临时源自动清理；最终测试log复制读回后删除/tmp副本。一次生成脚本SyntaxError在写入前失败，改正后成功，无冻结源变动。Station Carry QA在途119增/3删保留，不混提交、不跨聊天；知识页跨任务dirty原位保留。Knowledge=updated：原Wiki/ROS2与FishBot来源链及开发知识入口补“取消/接收端迟交/缓存顺序分层”，已读回，不写memory。
