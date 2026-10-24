# N3/N4：离线参考前缀与MINCO刹停对照

本片把已有N2窗口接到现有MINCO S4NU分轴制动，在原生MCAP中展示对照候选和拒绝原因。
这是记录驱动的离线推演。没有新的飞行、控制提交、动态占据资格或任务成功率结论。
无人机源码保持c866441冻结；没有训练、重编译无人机或新增规划器。

## 现有方法如何组合

1. 读取[N2精确分段窗口](DRONE_TRAJECTORY_PRIMITIVES.md)，保留原任务、参考曲线和绝对sim相位。
2. 取0.8s前缀末端的完整PVA及左极限参考jerk，交给既有`axis_stop_request`。
3. 用原生`minco_probe`的`axis_stop`调用官方MINCO_S4NU，固定停止时长XYZ=3.5/1/.4s。
4. 复用原连续审计检查刹停尾与完整拼接曲线，分列动力学、切点PVAJ、尾内C3和资格未知项。

本节固定参数比较没有调用L-BFGS优化或调参筛选。停止位置沿用现有p0+.5*T*v0，不能因此假设该终点在自由空间。
参考jerk来自已知曲线，未称实测飞机jerk。原cubic前缀内部仍有J跳变；全曲线只声明C2，切点及尾内单列C3。

原速度1.8m/s、加速度1m/s²、Z2.2m硬界不变。原审计器在本片的`corridor`仅检查Z上界；XY走廊、动态占据和终端区域均未验证。
报告明确`math_gate_scope`、`occupancy=unverified`和`execution_admission=not_performed`。
参考继续前进与制动停稳的目标不同，不能把两者的数学通过率当算法任务成功率排名。

## 当前固定参数结果

| 原曲线 | 生成 | 完整曲线V峰m/s | A峰m/s² | Z峰m | 原数学判据 |
| --- | --- | ---: | ---: | ---: | --- |
| 1 | 是 | .572879 | .691061 | 1.759597 | 通过；占据未知 |
| 2 | 是 | .526417 | .835167 | 1.769847 | 通过；占据未知 |
| 3 | 是 | 1.228397 | 1.674366 | 1.806082 | 加速度拒绝 |
| 4 | 是 | 1.585710 | 1.661290 | 1.986593 | 加速度拒绝 |
| 5 | 是 | 1.574017 | .923821 | 2.128953 | 通过；占据未知 |
| 6 | 是 | 1.680871 | .981600 | 2.133051 | 通过；占据未知 |
| 7 | 是 | 1.578854 | 1.081960 | 2.138174 | 加速度拒绝 |
| 8 | 未评分 | — | — | — | 原task/goal身份缺失，不派生 |

7条均生成，4条数学通过，3条因A超界拒绝；切点PVAJ均在1e-8数值容差内。
最大切点误差约2.30e-16，尾内J连接误差约4.77e-13。没有用J=0替代参考值，没有放宽A界。
生成/进程往返/审计耗时按离线墙钟另存，不映射成原飞行sim截止预算或实时性能成绩。

## 原生页面

常用入口仍为`/drone-diagnostics?taskId=748f910e-f0f8-4ecf-b2d5-22b7b15d57e6`，手机加`&mobile=1`。
新增`/drone/candidates`原生MCAP通道和“离线前缀＋MINCO刹停”说明。
紫线为数学通过候选，红线为拒绝候选；原历史备份未记录，仍不补青色已执行轨迹。
曲线#7在首发故障33.452s显示加速度拒绝；32.920s的#6显示数学通过/占据未验证；33.552s的无身份#8不派生。

候选只跟随当时最新收到的原名义曲线，新曲线替换后移除旧候选。seek、后退和刷新不发送控制。
可选文件缺失、ID不符、顶层null或空条目降级处理；损坏条目不阻断原任务回放。
预览每段17点仅用于绘图，动力学采用原连续极值与区间覆盖，不用显示采样判安全。

## 使用与复验

```sh
python3 apps/fishbot-control-station/workbench-tools/drone-stop-candidates.py --primitives "$PRIMITIVES_JSON" --output "$CANDIDATES_JSON"
python3 apps/fishbot-control-station/workbench-review-tests/test_drone_stop_candidates.py
node --test apps/fishbot-control-station/workbench-review-tests/drone-candidates.test.cjs
```

`PRIMITIVES_JSON`为N2输出；`CANDIDATES_JSON`写入原诊断缓存同ID的`stop-candidates.json`。
默认原生可执行文件为`~/.cache/ros2-drone/minco-probe/minco_probe`，支持`--native`和`--drone-root`显式指定；不自动安装或重构建。
`--stopping-times`可显式修改；上表仅本次预声明3.5/1/.4s对照，不宣称参数对任意初态可行。
原生不可用或某条生成失败时，保留该条原因并继续其他条目，不画伪造候选。

页面复验沿用项目脚本，增加`DRONE_CANDIDATES_EXPECTED=1`；同时设置`DRONE_SPARSE_EXPECTED=1`保留原稀疏观测回归。
JSON、原生输出、构建产物和QA截图留忽略目录；代码与文档按既有仓库边界交付。

本片完成组件对照与N4历史旁路展示，不代表N3任务级方法比较、M2完整滚动提交或M3动态执行完成。
官方Gatekeeper源码/机载许可及本地CommittedTail差异已核，离线完整选择切片见[滚动回放](DRONE_COMMITTED_REPLAY.md)。
当前仍缺动态安全集、终端区域、实际跟踪包络与PX4采用回执；动态闭环仍未通过。
实际页面验收与交付见[进度](../plans/workbench-code-rebuild-20261018/progress.md)。

## 原历史前缀接S4NU内点尾（2026-10-24）

新增`drone-reference-stops.py`，复用上述8个原N2前缀、现有`geometry.search(y_inner=True)`、官方S4NU薄CLI和原Replay。
旧固定参数结果保持。新比较保留完整原前缀和原参考切点PVA/J，不用合成前缀，不将参考J称实测J。
`compare(tail_request=...)`先从前缀实际多项式核切点，再检查最终原生内点接口回执、尾内C3及内点/逐轴停稳合同。
完整曲线仍为C2，切点与新尾分别为C3；不改冻结无人机源码或原速度1.8、A1.0、Z2.2硬界。

本轮预声明宽盒为`[-10,-10,0]→[15,10,2.2]`，窄盒对照只将Y上界改为2.03m。
两个盒都是手工静态配置空间fixture，不是原动态GridMap。宽盒复用已有Replay配置，不作为真实场景净空证书。
每个最终实际输出都对完整前缀＋尾做两次原连续盒审计，不能借用搜索期间另一条尾的通过标志。
搜索域不变：Tx=[3.5,5]、Ty=[.6,2]、Tz=[.1,.4]，仅+Y画像；没有为原记录改硬阈值。

| 原曲线 | 旧完整A峰 | 新完整A峰 | 宽盒/原动力学界 | 窄盒/原动力学界 |
| --- | ---: | ---: | --- | --- |
| 1 | .691061 | 未评分 | −Y超出当前搜索域，保留基线 | 未派生 |
| 2 | .835167 | .769225 | 通过 | 通过 |
| 3 | 1.674366 | .817598 | 通过 | 通过 |
| 4 | 1.661290 | 1.541738 | 加速度拒绝 | 加速度及走廊拒绝 |
| 5 | .923821 | .923821 | 通过 | 走廊拒绝 |
| 6 | .981600 | .940275 | 通过 | 走廊拒绝 |
| 7 | 1.081960 | 1.051164 | 加速度拒绝 | 加速度及走廊拒绝 |
| 8 | 未评分 | 未评分 | 原任务身份缺失 | 未派生 |

6条生成、4条宽盒数学通过；不能把4/6与旧4/7当任务成功率排名。#3的完整A峰已在不变的原前缀，#5也由原前缀决定。
#4刹停尾首段峰出现在切点后.188203s，A约(.107338,−.00000145,−1.537997)；#7在.163840s，A约(.210664,.00000171,1.029838)m/s²。
两者Y分量接近零，Tz均抵达旧搜索上界.4s。下一项先核垂直时长域及连续极值，不预设延长Tz必然可行。
本轮搜索wall .129–2.975s，6条优化器均返回success；仍不能以success替代硬界，#4/#7照常拒绝。J峰最高约15.877，尚无推力/角速度资格。

每条生成曲线复用16个静态反事实情景，共96个情景。4条数学正例保持原绝对相位，拒绝替换后沿旧相位进入尾段/终端；占据、过期及缺图撤销参考。
另2条从首次提交即拒绝，不能称成功进入刹停。当前真实A、当前/未来地图、终端区域、截止、跟踪与PX4采用仍未获得资格。
原曲线#1/#5/#6/#7的完整.8s前缀切点晚于下一曲线接收；`timing.replaced_before_cut`保留这一事实，新比较不是原飞行执行证明。
新结束时刻按实际段长重算；完整时长4.3–5.8sim秒，地图覆盖须到实际结束后.5秒，不能沿用旧5秒标签或混用wall时间。

```sh
python3 apps/fishbot-control-station/workbench-tools/drone-reference-stops.py --primitives "$PRIMITIVES_JSON" --output "$REFERENCE_STOPS_JSON"
cd apps/fishbot-control-station/workbench-review-tests
python3 -m unittest test_drone_reference_stops test_drone_stop_candidates test_drone_committed_replay test_drone_s4_knots
```

`PRIMITIVES_JSON`仍为原N2 exact-windows.json；新原生默认`~/.cache/ros2-drone/minco-s4-knots/minco_s4_knots`，不自动编译或安装。
`REFERENCE_STOPS_JSON`为原忽略目录`workbench-tools/output/drone-committed/748f910e-f0f8-4ecf-b2d5-22b7b15d57e6/reference-s4-inner-point-comparison.json`。
同目录`reference-s4-inner-readback.json`保存93项独立原JSONL/BSpline/系数实根/相位与选择结果检查；PNG为静态诊断图，非新飞行录像。
31项相关测试通过，其中10项新集成测试；原界、原失败和未评分均保留，没有修改Web或运行服务，不重复浏览器验收。
首轮因旧请求缺`integral_resolution`/走廊字段，6条未评分；补对接字段后通过完整入口测试。首报first-integration保留。
首次独立读回把无candidate情景的None误要求为False；修正为核全部事件无参考，first-readback保留。没有修改控制或审计判据迁就检查。
agent-link qoder超时60秒，无有效审查；内置只读审查指出再生成回执缺口，已补原生身份/段数负例。根独立读回通过。
本片只增加离线对照工具。M2仍部分完成、M3不启动，真实动态闭环仍未通过。

## Z时长域与数值表示（2026-10-24）

新增`drone-stop-time-study.py`复用原N2窗口、上节报告、现有六维搜索、原连续审计与Replay。
先固定其余五维，对#4/#7逐项重解Tz=.4/.5/.6/.8/1.0/1.2s；Z终点仍按既有`p0+.5*Tz*v0`计算，并非固定终点的纯时间缩放。
初始原参考PVA/J、完整前缀及硬界不动。由于Tx≥3.5s，固定五维对照中的总尾长和绝对结束时刻不变。

| Tz秒 | #4完整A峰m/s² | #7完整A峰m/s² | 原数学界 |
| --- | ---: | ---: | --- |
| .4 | 1.541738 | 1.051164 | 两条拒绝，复现旧结果 |
| .5 | 1.529433 | .966149 | 仅#7通过 |
| .6 | 1.529433 | .966986 | 仅#7通过 |
| .8 | 1.529434 | .972313 | 仅#7通过 |
| 1.0 | 1.542232 | 1.064629 | 两条拒绝 |
| 1.2 | 1.571403 | 1.121968 | 两条拒绝 |

#4峰从Z转为约.794s处的Y减速，A约(−.402918,−1.475406,0)。#7也不随Tz单调改善，不能把更长时长当作通用解。
随后只显式扩展联合搜索Tz域至[.1,1.2]s，其他五维域、默认Tz域[.1,.4]、2mm规划目标及原硬界保持。
这复用既有SLSQP，不新增求解器或GCOPTER权重；没有后处理拉伸或替换初始A/J。

| 原曲线 | 联合重解后完整A峰 | V峰m/s | Z峰m | 宽盒 | 窄盒 |
| --- | ---: | ---: | ---: | --- | --- |
| #4 | .723131 | 1.585710 | 2.109727 | 通过 | Y走廊拒绝 |
| #7 | .764559 | 1.586434 | 2.138174 | 通过 | Y走廊拒绝 |

两条峰都回到未改的历史前缀；完整曲线最高Y约2.212936/2.288586m，不可称Y≤2.03m场景通过。
联合重解后的完整时长约5.800000/5.294058sim秒，按最后实际段长重算未来地图覆盖；32个理想静态Replay情景只验证选择分支。
两条优化器均success，联合搜索wall约2.386/.197s；不是端到端截止或实时证书。真实完整状态、地图、终端、跟踪和PX4采用仍未获资格。

独立连续读回曾发现#7的Tz=.5/1.0对照中，固定XY的PVA/J曲线最大差约3.295e−5/2.834e−4；源端点PVA/J仍过，区间内部不变性却失败。
原因是适配器把近邻轴节点分出的极短段再次按端点PVA/J拟合，舍入误差在高阶导数中被放大。
`drone-minco-s4-knots.cpp`现直接对官方源系数做`p(offset+t)`的binomial平移，用long double累加再转double；不重写官方系数求解器。
原累计double节点保存一次、精确并集、左端等于内节点取右段、停止后常数。没有epsilon选片、合并近邻节点、缩时或放宽1e−8端点护栏。
原生回执新增`unified_piece_method=source_polynomial_time_translation_no_refit`，证明当前使用了新表示；仍须核实际曲线，不靠回执判安全。

最终51相关测试通过：8时长研究、11几何、10原前缀、11S4NU、3候选、8Replay；无跳过。
129项独立原源/系数实根/完整宽窄盒/绝对时长/分段XY PVAJ差/选择结果读回全部通过，两个旧不变性失败消失；PNG已目视核对。
空源条目、坏ID或无效Tz只跳过相应条目；无效声明转为可严格JSON序列化的空值，不终止其余样本。
agent-link沿用已知超时的内置只读备选，核对数学替换及两项坏条目隔离问题；根独立验收，未联系其他聊天。

```sh
c++ -std=c++14 -O2 -Wall -Wextra -isystem /usr/include/eigen3 -isystem /home/muqiao/.cache/ros2-drone/reuse/GCOPTER/gcopter/include apps/fishbot-control-station/workbench-tools/drone-minco-s4-knots.cpp -o /home/muqiao/.cache/ros2-drone/minco-s4-knots/minco_s4_knots
python3 apps/fishbot-control-station/workbench-tools/drone-stop-time-study.py --primitives "$PRIMITIVES_JSON" --reference-report "$REFERENCE_STOPS_JSON" --output "$Z_TIME_REPORT_JSON"
cd apps/fishbot-control-station/workbench-review-tests
python3 -m unittest test_drone_stop_time_study test_drone_stop_geometry test_drone_reference_stops test_drone_s4_knots test_drone_stop_candidates test_drone_committed_replay
```

新报告为原忽略drone-committed/748…目录的`reference-z-time-domain-comparison.json`；同目录保留`reference-z-time-readback.json`、PNG、首轮probe及两份before-translation报告。
下步由根Codex结合原接收/替换时刻与窄盒，核更早参考切点及必要刹停范围；不把宽盒数学正例当原动态场景可采用。
本轮只改离线适配器/工具/测试/文档，无Web改动、训练、ROS节点、仿真、控制、飞行或新落地证据。drone c866441冻结、M2部分完成、M3不启动。

## 窄盒更早切点与历史时序（2026-10-24）

新增`drone-narrow-handoff.py`，复用`restrict`、逐面必要刹停界、现有S4NU搜索/完整连续审计和Replay。
从原#4/#7 raw cubic记录的接收相位，分别截取h=.1/.2/.4/.6/.8s。每个切点保留自己的完整参考PVA/J，不把晚切点状态搬到过去。
实际cut按截断后duration计算；源曲线不足h时保留截短事实，节点J取前缀末段左极限。完整仍C2，切点及尾单列C3。
继续使用硬盒`[-10,-10,0]→[15,2.03,2.2]`、2mm规划inset及Tz显式域[.1,1.2]；原V1.8/A1/Z2.2不变。

| 原曲线 / h秒 | 最乐观Y刹停余量m | 完整A峰m/s² | 原连续界＋窄盒 |
| --- | ---: | ---: | --- |
| #4 / .1 | .876595 | .754442 | 通过 |
| #4 / .2 | .759882 | .777721 | 通过 |
| #4 / .4 | .536642 | .783283 | 通过 |
| #4 / .6 | .354708 | .895545 | 通过 |
| #4 / .8 | .222529 | .810276 | 通过 |
| #7 / .1 | .044289 | 1.050777 | 加速度拒绝 |
| #7 / .2 | .010208 | 1.164543 | 加速度拒绝 |
| #7 / .4 | −.058099 | 未生成 | 逐面必要界拒绝 |
| #7 / .6 | −.119066 | 未生成 | 逐面必要界拒绝 |
| #7 / .8 | −.170268 | 未生成 | 逐面必要界拒绝 |

最初四档必要界probe保留；.1s是probe后显式加入的更早对照。正式十组7生成、5通过、2A拒、3必要界拒，无未评分。
必要界允许单面瞬时使用全部A预算，忽略已知参考A/J连续性，不是joint viability或实测飞机ICS证明。
#7的.1/.2s峰主要为Y单轴−1.029983/−1.162129，不只是XY模长预算挤占；未被必要界排除也不保证当前有限生成族能过。
#4原.8s也能在窄盒内重解通过，说明上一节宽盒最优候选越Y不等于此切点没有窄盒候选。

### 显式追加的#7早切对照

根据上述Y峰诊断，另存h=.05s报告，不覆盖原十组。cut=33.046s，下一曲线接收33.496s、首条故障记录33.452s，均为同一sim时间域。
完整A=.926514、V=1.515465m/s、Z最高2.198m、Y最高2.028m，原连续界＋窄盒通过；Y和Z仅剩约2mm边界余量。
本组优化器仍为60次迭代上限false，搜索wall3.026s；原十组搜索wall4.743–8.048s，7个搜索中5个迭代上限。
独立硬审计可确认有限可行见证，不据此宣称优化收敛、实时计算、物理跟踪余量或在线可采用。
.05s是仿真参考前缀长度，不代表50ms墙钟感知注入，也不能直接用wall耗时判断sim截止；真实时钟映射/截止仍未获资格。

### 时间、数学与采用分列

每条保存cut相对原完整事件序列中下一接收、首条故障记录的before/at/after/unknown。原首条故障33.452s不是精确故障起点。
#7的.4s cut33.396s虽在记录边界之前，必要界已拒；.6/.8s在替换和故障记录之后，仅保留反事实诊断。
没有在历史时间上被排除，不等于原FSM已消费、算法来得及计算或当前地图支持。缺失/损坏故障元数据保持unknown，数学比较可继续。
`variant_id`区分父曲线与h；原trajectory_id保留。Replay优先candidate_id，继续原绝对start，不按新cut重启相位。
Replay的全部实际snapshot明确使用窄盒；未知图仍未知。8条生成候选各16个理想静态情景，共128；6个数学正例可接纳、2个始终拒绝。
通过统计同时要求完整数学合同（含切点J、尾C3、axis_knots）与窄盒门，不能只凭C2盒审计计为通过。

30相关测试通过：10新切点/时序＋2原精确分段＋10参考前缀＋8Replay，无跳过。
216项独立原JSONL/BSpline PVAJ/系数实根/必要界/时序/完整窄盒与选择结果读回通过；PNG已目视核对。
内置只读审查指出通过统计曾漏完整合同，已修并补“盒过、合同失败”的计数负例；沿用agent-link已知超时备选，根独立验收。
源字典、坏h、故障信息缺失分别降级，严格JSON仍可输出；没有把坏项或未知资格变为通过。

```sh
python3 apps/fishbot-control-station/workbench-tools/drone-narrow-handoff.py --primitives "$PRIMITIVES_JSON" --failure-report "$DRONE_RUN/report.json" --output "$NARROW_REPORT_JSON"
python3 apps/fishbot-control-station/workbench-tools/drone-narrow-handoff.py --primitives "$PRIMITIVES_JSON" --failure-report "$DRONE_RUN/report.json" --trajectory-ids 7 --horizons 0.05 --output "$EARLY05_REPORT_JSON"
cd apps/fishbot-control-station/workbench-review-tests
python3 -m unittest test_drone_narrow_handoff test_drone_primitives test_drone_reference_stops test_drone_committed_replay
```

原忽略drone-committed/748…目录保留reference-narrow-cut-probe.json、reference-narrow-handoff-comparison.json、reference-narrow-handoff-early05.json、reference-narrow-handoff-readback.json和PNG。
下一项根Codex将这些候选切点与原记录实测PV及可用时刻比对，核交接误差与毫米级余量；不继续以参考数学证书替代状态/地图/截止资格。
drone c866441仍冻结；没有Web改动、训练、ROS节点、仿真、控制、新飞行或新落地证据。M2部分完成、M3不启动，真实动态闭环未通过。


后续原记录PV比较已完成：六切点无同stamp测量，历史可用恒速PV与名义P差.156912–.277444m；#7向上差71.003mm对照名义2mm顶部余量，不构成未来碰撞证明。完整A/J仍未知，未采用。表格、精确时间规则、53测试及154项原始读回见[状态比较](DRONE_RECORDED_STATE.md#候选切点的原记录pv比较2026-10-24)。下一项按实际可用PV重锚并显式分列A/J假设，冻结保持。


进一步按可用PV重解的24个有限A/J画像均通过原连续门与axis_knots；新尾从cut独立开始，不拼原前缀。#7 A峰.953297–.968077，但YZ部分仍2mm、17组优化迭代上限，不能冒称在线接管。详细表格、64测试/1131系数读回和复验见[PV重锚尾段](DRONE_RECORDED_STATE.md#按可用pv重解独立尾段2026-10-24)。下一项核实际求解链耗时与提交时效，冻结保持。


原生进程复用与迟交时效已核：同#7三组成对的全部系数/硬审计/axis_knots相同，完整生命周期中位2.891→1.825wall秒；未证明实时。11个显式sim情景保原start，旧首态/CV传播迟交拒绝，理想当前相位仅条件通过。方法、108测试/86独立读回及命令见[原生传输与迟交](DRONE_RECORDED_STATE.md#原生进程复用与迟交时效2026-10-24)。下一项核官方连续极值接口的复用，原门限与冻结不变。
