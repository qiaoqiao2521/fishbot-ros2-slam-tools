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
