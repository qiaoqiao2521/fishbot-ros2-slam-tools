# M2：原记录的状态、跟踪与地图资格

本片从原748回合MCAP读取PV，回查FSM实际使用的状态时刻，并核对局部地图见证。
它接续[完整提交轨迹静态回放](DRONE_COMMITTED_REPLAY.md)，不将静态夹具混进真实飞行记录。
无人机源码保持c866441冻结。没有启动ROS节点、PX4/Gazebo、训练或控制写入。

## 数据来自哪里

- 原记录目录：`/home/muqiao/dev/ros2/projects/drone/output/measured-state-reanchor-flight-748f910e`。
- `depth-input`的原生MCAP有13个通道，其中`/drone/ego/odom`保存1926条nav_msgs/Odometry。
- 位置是sidecar从Gazebo读取的理想位姿；速度是sidecar相邻位姿的因果差分，world坐标系。不是PX4直接测得的PVA。
- 原truth.jsonl只有位姿，telemetry.jsonl保存速度模长及发送参考；不能用参考V/A补足实测PVA。
- Odometry没有加速度状态。报告明确acceleration=null，不在此做差分补值或默认置零。

`ego/sidecar.py:245–274`给出该里程计发布来源，`flight.py:340–362`给出两个JSONL的记录语义。
原MCAP的345个源时刻与truth.jsonl位置完全一致；这是同一理想源的两份存储，不是独立定位验证。
7条FSMStart的PV与CDR同stamp值匹配，最大差约6.95e−13，符合日志小数舍入精度。
这些结果核对提取与来源，不证明闭环跟踪、飞控采用或定位精度。

## 时间和参考如何对齐

实现：`apps/fishbot-control-station/workbench-tools/drone-recorded-tracking.py`。
复用原ROS2 CDR读包、N1的`clock_bracket`和N2的既有BSpline求值器，不实现新定位器或规划器。

每个PV保留源stamp、录制时间、frame和前后/clock的区间。
录制器可用上界不晚于曲线接收时刻，才计入该接收事件的“可用PV”；它不是planner callback消费ACK。
原记录只有一个已观察到的clock epoch；1899条状态取得录制可用上界，27条未包围，保持未知。
录制年龄上界最大.832s，只描述录制路径；曲线接收事件所选PV年龄为.016–.044s。
重置/未包围、未知frame或未归属任务不参与跟踪统计。

跟踪对照按PV源时刻选择当时已收到的最新曲线，使用同一时刻的解析P/V。
严格排除首发故障33.452s及其后状态；原任务仍failed/planner_emergency，恢复落地不改判。
新曲线没有task身份时不退回使用上一条曲线；新曲线定义域外不外推。
该对照描述名义参考和理想里程计之差，不等同实际命令接收或完整连续跟踪误差。

## 首发故障前的实测差值

| 项目 | 本次结果 |
| --- | ---: |
| 同源时刻可对齐PV样本 | 195 |
| 位置差峰值 / P95 / RMS | .292422 / .276889 / .168736m |
| 正向Z差峰值 | .073111m |
| 速度差峰值 | .219773m/s |
| 位置差峰值源时刻 | 32.688s |

195个样本来自同一旧回合，相关性强；不是统计置信包络、连续最大值或跨场景资格。
原#5/#6数学候选的名义高度余量分别.071047/.066949m，低于该历史正向Z差峰值。
这是余量不足的诊断，不是将历史最大误差当新硬界，也不证明未执行候选必然超高。
没有修改1.8m/s、1m/s²、2.2m硬界或旧飞行报告。

## FSM的混时差与同刻差分开

| FSM sim | 轨迹 | 里程计源时刻 | 年龄s | 原混时位置差m | 同一源时刻位置差m |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 29.704 | 1 | 29.604 | .100 | .006496 | .003112 |
| 30.632 | 2 | 30.524 | .108 | .118275 | .076952 |
| 31.644 | 3 | 31.500 | .144 | .334423 | .171719 |
| 32.660 | 4 | 32.532 | .128 | .473489 | .280180 |
| 32.832 | 5 | 32.688 | .144 | .440407 | 无法对齐 |
| 32.928 | 6 | 32.848 | .080 | .316364 | 无法对齐 |
| 33.388 | 7 | 33.228 | .160 | .385835 | .166906 |

#5/#6当时的里程计源时刻早于新曲线起点，不能反向外推或拿另一条旧曲线凑同刻差。
FSM关联还检查曲线在FSM开始前已收到，以及CDR状态的frame/epoch。
这是一组回顾性的同刻比较；不是把旧PV无模型预测到当前时刻，也不替代原始FSM输入。

## 地图和融合见证能证明什么

原planner.log有1138次VoxelEvidence，涉及425个cell；仅记录占据阈值穿越。
计数覆盖完整日志，含恢复阶段，不冒充195样本时间窗内的地图覆盖率。
InflatedVoxelTransition只保存一个目标格两次变化（31.228s的0→1、42.972s的1→0）。
没有完整GridMap/known-free快照、地图revision、未来safe set或终端区域；没有出现的cell不能判为空闲。
原MCAP通道目录没有完整地图通道，只有深度、点云、位姿、里程计、曲线、状态和clock。

紧停前可对齐的时间链为：

| 来源 | 观测源sim | callback结束sim | 融合结束时年龄 | FSM开始时年龄 |
| --- | ---: | ---: | ---: | ---: |
| front，planner.log:2333 | 32.968 | 33.332 | .364s | .420s |
| down，planner.log:2338 | 33.100 | 33.356 | .256s | .288s |
| odom，planner.log:2346 | 33.228 | 接收33.232 | — | .160s |

FSM从33.388s开始，33.420s重锚时相同odom已老化到.192s。字段均来自原行；wall时间单独保存为字符串。
只关联FSM开始前已结束的callback；不把更晚融合帧倒灌进当时状态。
callback完成见证仍不证明完整曲线所需空间已知，也不把累计延迟直接归因为某个DDS/CPU故障。
原report的37.392s下降检查是恢复时的单点/路径摘要，不能外推为#6完整前缀和刹停尾的准入证书。

## 资格与复验

当前有来源的PV已经找回；完整PVA、物理跟踪包络、时间有效完整地图、未来安全集、终端区域和采用回执仍未获资格。
报告始终`execution_admission=not_performed`。缺项逐条保留，不把报告成功生成当M2完成。

```sh
. /opt/ros/jazzy/setup.bash
python3 apps/fishbot-control-station/workbench-tools/drone-recorded-tracking.py --run-dir "$DRONE_RUN" --candidates "$CANDIDATES_JSON" --output "$STATE_JSON" --plot "$STATE_PNG"
python3 apps/fishbot-control-station/workbench-review-tests/test_drone_recorded_tracking.py
```

运行目录为工作台仓库；`DRONE_RUN`取上方原记录，`CANDIDATES_JSON`为N3 stop-candidates.json。
本次JSON/PNG在忽略的`apps/fishbot-control-station/workbench-tools/output/drone-committed/748f910e-f0f8-4ecf-b2d5-22b7b15d57e6/`。
文件名分别为recorded-state-qualification.json、recorded-state-diagnostics.png。
PNG三图分别显示同源位置差、Z差与名义余量比较、FSM混时/同刻差；图只表达历史采样证据。
绘图可选；缺matplotlib或写图失败保留JSON并WARNING。缺ROS2读包Python时不安装组件，先使用已装Jazzy环境。

9项局部检查覆盖未收到曲线、首发后样本、错任务替换、录制可用上界、混时比较、定义域、frame/epoch和损坏见证。
独立只读审查发现的FSM曲线可用性/frame遗漏已修补并补负例；原静态回放8项复验通过。
没有改网页或服务，不重复Web构建和浏览器QA。下一步在冻结边界内做有限来源的状态预测/误差适用域分析，再推进完整M2资格；不自动飞行。
交接与交付见[工作台进度](../plans/workbench-code-rebuild-20261018/progress.md)。


## PV外推离线比较（2026-10-24接续）

在同一脚本增加`--forecast`，复用原MCAP读取与时钟夹逼。没有改飞行源码、优化器或控制owner。
现有`ego/frames.py::interpolate_pose`需要两个已知端点，只用于插值，不能当在线外推。新增部分仅为三种固定代数基线和评测适配。

| 模型名 | 输入与含义 |
| --- | --- |
| 缓存保持 hold | 保留旧P、旧V的状态快照基线；不是满足运动学一致性的可执行轨迹 |
| 恒速外推 constant_velocity | 用原PV向目标时刻积分；A=0是模型假设，未填入实测A |
| 因果加速度外推 causal_acceleration | 用过去两帧V的差分估计A并保持该值；估计A单列，不冒充实测A或参考A |

保留两类输入证据。recorder分支要求初始帧的录制可用上界到达，历史帧也必须已可用。
FSM分支用原日志和CDR数值匹配确认其已消费的初始PV；不能要求独立录制器一定先于该消费事件写入。用于估计A的历史帧仍须在预测开始前录制可用。
两类路径分列，不将“源stamp较早”单独当成已消费证据，不把未评分帧补零。

预测函数不接收未来P/V。对每个请求时刻，评分选择该时刻之后第一条实际源样本，在它的源时刻评价已定义的预测公式。
请求时刻、实际评分源时刻和二者偏移分别保存；本次偏移0–.016s。没有插值出新的真值，也不把未来样本倒灌初值。
预声明时域为录制可用时刻后0/.04/.08/.16/.24sim秒，真实传播时长还包含源年龄及评分偏移，本次总范围.012–.300s。
首发33.452s及其后样本不评分；27条frame/state/epoch未获资格，33个请求因无首发前评分样本被排除。

### 固定时域结果

共949组评分case：942组recorder和7组FSM；每组的三个模型均可评分。它们是相关的旧数据样本，不是949次飞行。
下表为位置RMS，单位米；各模型在同一行使用相同初始PV和评分目标，因果模型另使用已可用历史V。

| 可用时刻后请求时域s | case数 | 缓存保持 | 恒速外推 | 因果加速度外推 |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 194 | .027773 | .000525 | .000209 |
| .04 | 191 | .067847 | .002050 | .000660 |
| .08 | 190 | .108638 | .004637 | .001494 |
| .16 | 185 | .190965 | .013075 | .004855 |
| .24 | 182 | .274381 | .025713 | .010833 |

7组FSM的真实传播时长.080–.160s，评分时间相对FSM起点最多再偏移.016s。
其位置RMS分别.164031/.007136/.003245m；峰值分别.239405/.010564/.006433m。
首个FSM样本恒速误差.000588m、因果加速度误差.001361m，不能宣称后者逐帧更优或直接晋级。

33.388s的评分源时刻恰好也是33.388s：恒速预测误差.010564m、因果加速度预测误差.003918m。
该时刻的参考与实际位置仍相差.185380m；预测更准不等于控制跟踪已经修好。
这些模型仍基于理想Gazebo位置/差分V，没有验证实际传感噪声、执行器扰动、连续误差包络或未来自由空间。
实测A继续保持null，原硬界和`execution_admission=not_performed`保持。

### 输入边界与复验

整数/字符串的同一source_stamp_ns按整数统一比较；冲突PV整组不评分，相同PV采用最早有效录制可用时刻。
NaN/缺失首发时刻、未来历史帧、无效frame/epoch和非有限PV均不进入该评分分支，其他数据仍可保留。
未来Oracle改值只能改变评分，不改变预测；单测已覆盖。模型中没有参考曲线、目标点或未来PV输入。

```sh
. /opt/ros/jazzy/setup.bash
python3 apps/fishbot-control-station/workbench-tools/drone-recorded-tracking.py --forecast --run-dir "$DRONE_RUN" --candidates "$CANDIDATES_JSON" --output "$FORECAST_JSON" --forecast-plot "$FORECAST_PNG"
```

本次输出留原忽略目录：pv-forecast-evaluation.json和pv-forecast-comparison.png；前轮recorded-state-qualification.json保留。
图为固定时域RMS及7个FSM样本比较；只做离线科学诊断，不接网页、控制命令或飞控读回。
相关测试现为20项（原9＋预测11），加原静态回放8项共28项；真实CDR另做输入/时钟/评分来源读回。
Qoder首轮时间建议可用，二次代码审查超时且句柄已缺失；内置只读审查找到时间戳表示和NaN截止两处边界，均已修补/补负例。
下一步从预测后的参考偏差与必要制动可行域接续M2，再核时间有效几何；本次经验结果不作为动态安全证书，M3仍冻结。

## 必要刹停条件与旧曲线适用域（2026-10-24接续）

同一脚本新增`--stopping-fixture`，读取历史box和limits；可选`--native`复用已有MINCO和连续审计器。
box下界[1.5,-1,.8]、上界[9.5,2.03,2.2]是手工静态夹具，不是当前自由空间。原加速度硬界仍为1.0m/s²。

逐面使用单位外法向n、距离d、外向速度u=max(0,n·v)，计算必要净空u²/(2A)。
在给定加速度范数上限A成立的模型内，d小于必要净空则标`necessary_reject`；已经在box外另标`outside`。
通过只标`not_ruled_out`和`joint_viability=not_proven`。该界允许瞬时把全部预算分配给每个面，忽略A/J连续性、三轴竞争、扰动和动态占据。
没有数值容差放宽。等号及浮点两侧分别测试；静止于边界也只是不排除，不能保证未来安全。

原33.228s缓存PV的Y/Z必要减速度为.496427/.317697m/s²，未被排除。
历史报告已有XYZ停止时间3.5/1/.4s的C3分轴刹停，本轮复验仍通过：A峰.990634、Z峰2.194629m。
其中A=J=0仍是显式假设，不是测量；该结果早已存在，不是本轮新解，也不能据旧两段Y越界宣称原初态为ICS。

### 推进后状态的比较

7个FSM加1个reanchor形成32个相关PV比较；只对最后FSM和reanchor的8个变体做原生刹停审计。
2个通过都是同一旧缓存PV的重复计算，不能当两次独立成功；其余6个均被`corridor`拒绝，A峰未超1.0。
更早FSM可能在此局部box之外；`outside`只说明不适用夹具，不能倒推实际飞行违规。

| 事件→评分源时刻s | 状态来源 | Y必要减速度 | Z必要减速度 | 必要条件 | 固定时间刹停 |
| --- | --- | ---: | ---: | --- | --- |
| 33.388→33.388 | 33.228缓存PV | .496427 | .317697 | 未排除 | 通过，仅A/J=0夹具 |
| 33.388→33.388 | 恒速预测 | .714148 | .987944 | 未排除 | 走廊拒绝 |
| 33.388→33.388 | 过去V差分预测 | .498523 | .264605 | 未排除 | 走廊拒绝 |
| 33.388→33.388 | 同刻记录PV | .524730 | .117921 | 未排除 | Y终点2.060475m越界 |
| 33.420→33.428 | 恒速预测 | .802093 | 2.090563 | Z必要拒绝 | 走廊拒绝 |
| 33.420→33.428 | 过去V差分预测 | .499241 | .238513 | 未排除 | 走廊拒绝 |
| 33.420→33.428 | 后继记录PV | .550687 | .069113 | 未排除 | Y终点2.073068m越界 |

减速度单位m/s²。reanchor在33.420s，下一条源样本在33.428s，偏移.008s；未伪造同刻真值。
预测公式从33.228s原PV积分到实际评分源时刻，过去V差分沿用已可用历史对。未来PV只评分。
每个变体另存`pv_at_sim_s`与来源；缓存仍属于旧时刻，原始实测A仍null。
恒速模型的Z必要拒绝不能代替记录PV，也不能证明实际状态无解。

### 固定终点规则的限制

33.428s记录为y=1.851165234m、vy=.443806027m/s，距Y边界.178834766m。
若固定A=J=0、y_end=y+vy*T/2、末端V/A/J=0，现有单轴S4NU解的峰值减速度为1.875*vy/T。
原生系数在归一化中点的导数读回为1.875000000000014。该对称曲线族仅Y轴就要求T≥.832136301s，同时几何要求T≤.805914093s，两者无交集。
本族最低所需Y减速度约1.032537225m/s²。它比物理最乐观必要界.550687更强，但只约束当前曲线族，不能升级为所有刹停均无解。
下一步复用已有`stop_positions`核停止位置自由度和边界重解，再核时间有效几何；不继续盲调T或补造实测A/J。

### 验证与复验入口

31项状态/预测/刹停检查加8项已提交轨迹回放，共39项通过。独立原始CDR/多项式读回19项通过：1926条原PV、8事件、输入/Oracle/恒速公式、8个原生审计及曲线族时间矛盾。
Qoder审查超时，get_status确认句柄缺失后由内置只读审查完成；模型前提、时刻偏移、逐变体时间及冲突PV建议已落实。
独立读回首次因NumPy bool_写JSON失败；转为原生bool后重跑通过，首次不计验收。密集采样只做交叉检查，连续判据仍由原审计器承担。

```sh
. /opt/ros/jazzy/setup.bash
python3 apps/fishbot-control-station/workbench-tools/drone-recorded-tracking.py --run-dir "$DRONE_RUN" --stopping-fixture "$DRONE_RUN/minco-piecewise-timing-final-r2-audit.json" --native "$HOME/.cache/ros2-drone/minco-probe/minco_probe" --output "$STOPPING_JSON"
python3 -m unittest discover -s apps/fishbot-control-station/workbench-review-tests -p test_drone_recorded_tracking.py
python3 -m unittest discover -s apps/fishbot-control-station/workbench-review-tests -p test_drone_committed_replay.py
```

原忽略目录新增stopping-viability-evaluation.json、stopping-readback-checks.json，前轮报告保留。完整当前地图、时间有效占据、终端区域、实测A/J和实际接管仍未获资格。
drone c866441清洁冻结，M2部分完成、M3不解冻；本轮无训练、ROS节点、飞行或控制写入。

## 停止位置与时间联合重解（2026-10-24接续）

新增`workbench-tools/drone-stop-geometry.py`，复用现有S4NU的`stop_positions`和原连续审计。
SciPy SLSQP只做外部四变量有界搜索[Tx,Ty,Tz,dy]，不修改GCOPTER残差、a_opt或weiAcc。
搜索范围分别为[3.5,5]s、[.6,2]s、[.1,.4]s及[0,Y规划余量]；本工具仅处理当前正Y运动的静态box夹具，不是通用规划器或全局无解证明。

初始PVA和显式J按原请求保持，重新求解多项式系数，不对生成曲线做全局时间拉伸。
同步`stop_positions`、`terminal_pva[:,0]`和备份评分target；末端V/A/J保持0，`source_local_target_before_stop`保留原值，备份终点不冒充任务航点。
提取公共`audit_axis_request`以复用原生生成；搜索探针不调用昂贵的最终证书，最终候选才做完整原连续审计。
优化器success、原生native_success与`candidate.audit.passed`分列，前两项不能代替后者。

首个自由终点探针A峰.978886，但终点贴Y=2.03m硬边界，仍被原审计corridor拒绝。后续明确向内规划2mm，外部硬界仍保持2.03m及A≤1、V≤1.8、Z≤2.2。
2mm是本次优化目标余量，不是已校准跟踪包络，也不是机体到障碍物的净空。X停止时间上限收至5s；不能用更长刹停直接宣称动态安全。

### 同一输入的条件构造结果

| 输入PV | 初始A/J来源 | XYZ停止时间s | A范数峰m/s² | Z峰m | Y峰m | 原连续审计 |
| --- | --- | --- | ---: | ---: | ---: | --- |
| 33.428s过去V差分预测PV | 保留原请求A=J=0假设 | 5/.977107/.200703 | .898199 | 2.195178 | 2.028 | 通过 |
| 33.428s事后记录PV | 保留原请求A=J=0假设 | 5/.929705/.176402 | .990466 | 2.187738 | 2.028 | 通过 |

事后PV在此明确作为反事实生成输入，不是在线可用证据；它没有倒灌预测函数。因果预测的模型A也未替换原请求A或冒充实测A。
缓存PV的旧合格曲线保持原样；恒速模型的Z向必要拒绝保留且不搜索。不是从四条里挑两条来算成功率，也没有实际采用回执。
新曲线最小Y速度分别约−5.55e−16和0m/s，前者属于浮点量级；逐段极值和接缝均纳入统计。
全段最小box余量均为Y向2mm；端点六面余量与全段余量分开保存，不能以端点自由替代中段检查。

保留边界的数值误差：PVA约1.17e−15/1.55e−15，原审计J接缝约2.85e−14；这是所给数学边界，不是实测交接证明。
最大J约11.681/9.787m/s³；原验收器没有对应J硬界，本次不额外宣称推力、角速度或PX4可跟踪性通过。
本次离线进程往返＋搜索＋审计墙钟约.416/.430s，是单轮观察值，不是实时截止预算；不能直接与仿真秒相加。

### 输入合同与验证

独立只读审查发现“variant来源PV与baseline请求PV可能不一致”和“未知必要界被说成拒绝”两处问题，均已修复。
二改后的PV若与基线请求不一致，只WARNING并跳该行；其他行继续，初始A/J不被偷偷替换。必要界未知保留unscored。
11项新增检查覆盖终点三联同步、历史target/非零初始A/J保持、未知J、端点合法但中段超调、优化success但审计失败、缺原生程序、来源PV错配与未知必要界。
加原31状态/预测和8提交轨迹检查，共50项通过；首轮测试因测试夹具缺corridor失败，补齐真实接口合同后重跑通过，不把首轮计通过。
独立源报告/多项式读回32项通过，另生成科学对比图；密集采样只用于画图，连续判据仍由原Bernstein审计承担。
Qoder审查超时且get_status确认无句柄，随后由内置只读审查完成，无旧聊天协作。

```sh
python3 apps/fishbot-control-station/workbench-tools/drone-stop-geometry.py --stopping-report "$STOPPING_JSON" --planning-inset .002 --output "$GEOMETRY_JSON"
python3 -m unittest discover -s apps/fishbot-control-station/workbench-review-tests -p test_drone_stop_geometry.py
```

原忽略目录新增stop-position-time-comparison.json、stop-geometry-readback-checks.json、stop-geometry-comparison.png；前轮探针和报告保留。
下一步核非零A/J假设与5秒刹停所需的时间有效自由体积、终端窗口和求解截止条件。当前地图/跟踪管道仍未获资格，不能把静态几何构造晋级成在线备份。
drone c866441继续清洁冻结；本轮未训练、启动ROS节点或飞行，也没有控制写入。M2仍部分完成，动态闭环未通过。

## 非零边界与刹停时效资格（2026-10-24接续）

新增`workbench-tools/drone-stop-qualification.py`，复用上一节的MINCO、连续审计和现有Replay。
只改变明确列出的A/J假设，保留输入PV、原硬box和V≤1.8、A范数≤1.0、Z≤2.2；不存在新实测A/J。
每条先按原停止位置/时间重解系数，只有失败项再运行相同有界Tx/Ty/Tz/dy搜索；不拉伸已生成曲线。

### 十组有限假设

| 输入PV | 初始A/J假设 | 固定几何/时间A峰m/s² | 有界重解A峰m/s² | 原连续审计 |
| --- | --- | ---: | ---: | --- |
| 因果预测 | 原边界A=J=0 | .898199 | — | 通过 |
| 因果预测 | 过去V差分A保持、J=0 | .815136 | — | 通过 |
| 因果预测 | Ay=+.2、J=0 | 1.039018 | 1.035868 | A拒绝 |
| 因果预测 | A=0、Jy=+1 | .937582 | — | 通过 |
| 因果预测 | A=0、Jy=−1 | .858847 | — | 通过 |
| 事后PV反事实 | 原边界A=J=0 | .990466 | — | 通过 |
| 事后PV反事实 | 过去V差分A保持、J=0 | .694153 | — | 通过 |
| 事后PV反事实 | Ay=+.2、J=0 | 1.131267 | 1.128389 | A拒绝 |
| 事后PV反事实 | A=0、Jy=+1 | 1.027946 | 1.027612 | A拒绝 |
| 事后PV反事实 | A=0、Jy=−1 | .953011 | — | 通过 |

7/10只是五个命名假设在两个相关输入上的有限结果，不是独立飞行成功率或鲁棒不确定集证书。
三组失败说明当前搜索范围和生成族仍未找到合法候选，不证明全部刹停轨迹无解，更不证明ICS。
当前事后PV始终标反事实输入；它不参与因果模型的预测或可用性判定。

过去V差分A为[−.085237267,−.491086827,−.361582126]m/s²，源V在33.208/33.228s，FSM构造时刻33.388s。
把它保持至33.428s时年龄为.2s；J=0也是附加假设，不能称交接时刻的测量A/J。
每个父行独立筛选构造时刻≤min(事件时刻,边界时刻)的历史，且由原V重算并核对模型A。
录制到达上界与`FSM logged consumed PV`明确消费证据分开；禁止只取全文件最后一条FSM倒灌早时刻。
可选历史坏行或缺失只让该假设unscored，其他假设继续，原PV不变。

### 完整刹停接入现有离线选择器

Replay增加`axis_stop_geometry_candidate`入口，直接审计整个C3刹停，不把第一段伪装成历史名义前缀。
外部传来的native、request和终点均重新连续审计，不信缓存passed。
还要求mode=axis_stop、实际总时长有限且大于0、末端V/A/J=0；普通数学边界可通过但不是停稳合同的输入仍拒绝。
原完整前缀＋尾段入口保持原行为。缺A不由参考补0，候选被拒时只沿用仍合法的旧绝对相位。

两条原边界合格曲线各复验12个情景，共24个静态声明夹具；观测PVA为理想参考值，地图为空占据加手工box的声明，不是飞机传感器证据。
实际总长均5s，从33.428s至38.428s；接纳还需有限.5s终端窗口，因此当拍需图有效至38.928s。
`.6s`新鲜度只说明观察足够近，不代表已知未来5.5s无障碍。
覆盖取native实际段长之和；测试中的6s曲线即使标记5s，仍需6.5s覆盖，不额外硬编码5s全局限长。

| 情景 | 离线预期及已核结果 |
| --- | --- |
| 声明足够长覆盖＋理想PVA | track → braking_tail → terminal_hold |
| 仅新鲜快照或仅覆盖曲线 | map_prediction_horizon_unverified，无参考 |
| 仅覆盖至曲线结束＋.5s | 接纳当拍可过，后续悬停窗口滑动后过期，无参考 |
| 未声明已知自由空间、图过期、地图时钟不符 | 相应资格拒绝，无参考 |
| 实测A缺失 | invalid_clock_or_state，不从参考补造 |
| 晚.2s提交却仍给旧头PVA | handoff_state_mismatch，无参考 |
| 当拍A偏差+.2 | tracking_state_mismatch，无参考 |
| 终点被占据 | remaining_voxel_violation，无参考 |
| wall过去10s但sim暂停 | 相位与参考均不推进 |

有限终端窗口不是终端不变安全集；后续仍需持续合格观测与覆盖。
`protect`仅表示选择器撤销可执行参考，未证明物理控制器已制动、悬停、回退或落地。
本轮没有采用回执，也没有把wall离线计算耗时直接加到sim交接时刻。

### 验证与最短接续

12项新资格测试＋8项提交回放＋11项几何＋31项状态/预测，共62项通过。
覆盖过去A的逐父行因果性、坏项隔离、C3/末端合同、原生段长、未知A、时钟/地图失效、候选重审与旧合法相位。
冻结审计器已有逐段正时长检查，负时长反例走原拒绝路径，没有再实现一套多项式审计器。
独立从源报告和降幂系数读回初末PVA/J、实际时长及选择结果，共81项通过；图已目视核对。
CBC返回done但正文为空，不算审查；内置只读审查所指来源、局部异常和末端合同问题已修并补负例。没有联系已有聊天。

在实现仓运行，输入为前两节保留的产物；不启动ROS或飞行：

```sh
STOP_REPORT_ROOT=apps/fishbot-control-station/workbench-tools/output/drone-committed/748f910e-f0f8-4ecf-b2d5-22b7b15d57e6
python3 apps/fishbot-control-station/workbench-tools/drone-stop-qualification.py --geometry-report "$STOP_REPORT_ROOT/stop-position-time-comparison.json" --stopping-report "$STOP_REPORT_ROOT/stopping-viability-evaluation.json" --output "$STOP_REPORT_ROOT/stop-boundary-temporal-qualification.json"
python3 -m unittest discover -s apps/fishbot-control-station/workbench-review-tests -p test_drone_stop_qualification.py
python3 -m unittest discover -s apps/fishbot-control-station/workbench-review-tests -p test_drone_committed_replay.py
python3 -m unittest discover -s apps/fishbot-control-station/workbench-review-tests -p test_drone_stop_geometry.py
python3 -m unittest discover -s apps/fishbot-control-station/workbench-review-tests -p test_drone_recorded_tracking.py
```

原忽略产物新增stop-boundary-temporal-qualification.json、stop-qualification-readback-checks.json及stop-boundary-sensitivity.png。
本轮无Web改动，不重跑构建或浏览器；drone c866441清洁冻结，无训练、ROS节点、仿真、控制或新落地证据。
下一项由根Codex做三组拒绝输入的有界提前交接对照，保留同类A/J假设与原PV来源，不预设提前必然可行。
真实A/J、当前/未来自由图、终端区域、实时截止及物理跟踪/采用仍未获资格，M2部分完成，M3与动态闭环未通过。

## 提前交接时刻对照（2026-10-24接续）

同一`drone-stop-qualification.py`新增`--earlier-handoff`，复用原SLSQP搜索、MINCO与连续审计。
预先固定33.248/33.388/33.428s三个边界，各比较原三组拒绝画像和两个零A/J控制，共15组。
所有时刻沿用Tx[3.5,5]、Ty[.6,2]、Tz[.1,.4]与相同2mm内部规划余量；不改变原硬界，不拉伸旧系数。
每组从对应新PV和同类A/J重新求系数；只给旧曲线改时间标签会因初始PVA不匹配被拒绝。

### 输入时刻与角色

预测固定使用33.208/33.228s源V配对，记录可用上界分别33.212/33.232s，均早于最早边界33.248s。
各时刻重新积分PV，源对保持；模型A用于PV预测，初始A/J仍按各组明确假设给定，两者不混称测量。
33.388s只是定位该对输入的原FSM消费记录；33.248s预测只具备recorder可用资格，不证明原规划器已提前消费。
真实PV只在相同源时刻取事后反事实对照，不进入预测函数；缺精确源时刻或存在冲突时只跳该分支，不取邻近PV替代。
两项历史可用上界取最大值；anchor或previous任一个晚到/缺失都不能凭另一项补齐资格。

### 三个原拒绝画像的结果

数值为原连续审计的三维加速度范数峰，单位m/s²，硬界仍为1.0。

| 同类A/J画像 | 33.248s | 33.388s | 33.428s |
| --- | ---: | ---: | ---: |
| 预测PV，Ay=+.2、J=0 | 1.028683 拒绝 | 1.033810 拒绝 | 1.035868 拒绝 |
| 事后PV，Ay=+.2、J=0 | 1.024262 拒绝 | 1.080840 拒绝 | 1.128389 拒绝 |
| 事后PV，A=0、Jy=+1 | .934342 通过 | .982959 通过 | 1.027612 拒绝 |

两PV的原零A/J控制在三个时刻均通过，因此总计8通过/7拒绝；不是独立飞行成功率或动态鲁棒证书。
提前180ms可解除事后Jy画像的本族拒绝，不能解除两个外向Ay画像，不能将全部失败解释为接管太晚。
33.248s预测外向Ay在曲线相对.461568s处，A=[−.053100,−1.027311,0]m/s²；事后PV为[−.053133,−1.022883,0]。
Y单轴已超过1.0，因此这两例不能仅归因于X挤占三维加速度预算。只证明当前有界搜索/生成族失败，不证明所有轨迹无解或ICS。

### 验收与接续

资格文件共20项测试通过，其中本轮新增8项；覆盖recorder/FSM区别、前/后历史晚到或缺失、坐标/epoch错误、冲突源对、oracle编辑隔离、精确时刻、坏行跳过、逐时刻重解及旧曲线重标拒绝。
独立从原MCAP CDR回读源PV/录制时钟，并从降幂系数重新求极值、初末PVA/J和峰向量，共122项检查通过；图已目视核对。
agent-link agy因启动器`--print`参数错位而失败，未计有效审查；内置只读审查完成，建议的previous晚到/缺失负例已补。没有联系其他已有聊天。
原常用模式保持`fixed_passes`输出；额外CLI回归读回10组/7过/2个时效集，另存stop-boundary-temporal-qualification-regression.json，不覆盖原报告。新增比较模式使用`comparison_passes`，不改变控制路径。

在前节相同`STOP_REPORT_ROOT`下运行：

```sh
python3 apps/fishbot-control-station/workbench-tools/drone-stop-qualification.py --geometry-report "$STOP_REPORT_ROOT/stop-position-time-comparison.json" --stopping-report "$STOP_REPORT_ROOT/stopping-viability-evaluation.json" --earlier-handoff --handoff-times 33.248 33.388 33.428 --output "$STOP_REPORT_ROOT/stop-earlier-handoff-comparison.json"
python3 -m unittest discover -s apps/fishbot-control-station/workbench-review-tests -p test_drone_stop_qualification.py
```

原忽略目录保留stop-earlier-handoff-probe.json，并新增stop-earlier-handoff-comparison.json、stop-earlier-handoff-readback.json和stop-earlier-handoff-comparison.png。
下一项核当前Y单轴C3生成族的几何/末端边界与可复用分段自由度；不继续盲增同类时刻搜索，不改冻结算法或放宽硬界。
真实完整A/J、时间有效已知自由图、终端区域和跟踪/采用仍未获资格。无训练、ROS节点、仿真、控制或新飞行，drone c866441清洁冻结；M2部分完成、M3及动态闭环未通过。

## 官方S4NU内点薄适配（2026-10-24接续）

复用本机GCOPTER e0444f6d47b84f972ced91746b05feb36ce1fd4f的`MINCO_S4NU`，MIT版权/许可保留在原checkout。
官方接口原本就支持3×4首尾PVAJ、3×(N−1)内点和N段时长；冻结wrapper只暴露每轴N=1，旧piecewise_boundary/fixed_times使用S3NU，不能作为C3替代。
新增`workbench-tools/drone-minco-s4-knots.cpp`只暴露该已有接口，不修改冻结drone、上游求解器或重写系数求解。
它按各轴内部位置/时长调用S4NU，取累计节点精确并集。当前统一段直接平移源七次多项式的物理时间原点；早期端点PVAJ重拟合在近邻轴节点下放大舍入误差，已替换，见[Z时长域与数值表示](DRONE_STOP_CANDIDATES.md#z时长域与数值表示2026-10-24)。各轴停止后明确保持位置及零VAJ，不使用原轨迹的尾外推。
不合并真实不同节点、不拉伸时长。累计时间不推进、非法维数/时长、非有限系数或重构PVAJ误差超1e−8，仅拒绝当前输入行，后续JSON行继续。

现有外部SLSQP在[Tx,Ty,Tz,dy]外仅加Y节点时间比例r∈[.15,.85]、位移比例q∈[0,1]；默认四维范围、2mm内部规划目标和硬界不变。后续Z时长域对照仅显式传入`z_time_bounds=(.1,1.2)`，未改变默认(.1,.4)或原硬界；下表仍为此前有限画像的历史证据。
Y内点只固定位置，不人为锁定内部VAJ；初始PVA/J和终端VAJ=0保持，原任务target元数据保留。
新native必须回执正确generator和各轴[1,2,1]段数；冻结旧程序会忽略新增字段，因此只能标unscored，不能伪称内点优化已生效。

### 同一33.428s输入的五个有限见证

| 输入PV与初始A/J假设 | 原单段轴A峰m/s² | 新Y内点A峰m/s² | 原连续硬审计＋内点/停止合同 |
| --- | ---: | ---: | --- |
| 因果预测，A=J=0 | .898199 | .720009 | 通过 |
| 因果预测，Ay=+.2、J=0 | 1.035868 | .774606 | 通过 |
| 事后PV，A=J=0 | .990466 | .710838 | 通过 |
| 事后PV，Ay=+.2、J=0 | 1.128389 | .754274 | 通过 |
| 事后PV，A=0、Jy=+1 | 1.027612 | .718300 | 通过 |

这只解除所列三个原拒绝画像在静态手工box中的本族拒绝，不是动态成功率或任意初态备份证书。
新曲线最高Z为2.197736m，仍只有毫米级高度余量；J峰7.256–12.636m/s³，没有对应原J硬界或推力/角速度资格。
内点位置误差≤2.22e−16m，统一段C3误差≤5.40e−14；这证明所给数学PVAJ合同，不证明实际飞机状态或跟踪成立。
Y反向速度仅约0–1.06e−15m/s，属于数值量级；全段仍由原连续判据验收，不用采样点代替连续检查。

新增局部`audit_axis_knots`检查声明内点在其时刻命中，并检查每轴停止后的全部PVAJ区间。
跨停止时刻的段只检查后半区间，未以1ns时间容差跳过短区间；原全局审计只核首尾/接缝，不能代替此合同。
Replay在完整刹停及“前缀＋尾段”两入口都会重新核该合同；修改内点元数据，即使原全局数学审计仍过，也不能沿用缓存passed。
完整前缀测试使用明确标注的合成恒速前缀，不冒称历史实际执行前缀；原记录切点组合仍待下一项。

### 时效与验证边界

完整离线搜索/生成/审计耗时5.209–10.922wall秒；三组达到60次迭代上限，保留optimizer_success=false，但独立连续审计通过。
因此只记可行见证，不记已收敛最优解或实时求解通过。单次native内部约.108–.214ms，不能代替全流程耗时，也不能直接加到sim时刻。
实际总曲线时长约4.050–5.000sim秒，仍需按真实段长核未来自由体积与终端窗口，不能按固定标签认定安全。

49项相关检查通过：10项新native/内点/停止/回放检查、11几何、20资格及8原回放。
独立降幂系数/根求极值、同源旧输入、初末PVAJ、逐段C3、内点、逐轴hold与原硬界读回81项通过，科学图已目视核对。
内置只读审查所指“极短hold区间漏检”和“累计时间/内点/重构缺口”已修；根测试另覆盖raw/full两种回放的缓存元数据变更。
首次测试仅因fixture把历史mission target与当前backup endpoint混比而失败，改正测试来源后重跑；未为该测试更改实施行为或硬界。

复用现有编译器、Eigen和JSON头文件，二进制只留cache；在实现仓运行：

```sh
STOP_REPORT_ROOT=apps/fishbot-control-station/workbench-tools/output/drone-committed/748f910e-f0f8-4ecf-b2d5-22b7b15d57e6
DRONE_S4_BUILD="$HOME/.cache/ros2-drone/minco-s4-knots"
mkdir -p "$DRONE_S4_BUILD"
c++ -std=c++14 -O2 -Wall -Wextra -isystem /usr/include/eigen3 -isystem "$HOME/.cache/ros2-drone/reuse/GCOPTER/gcopter/include" apps/fishbot-control-station/workbench-tools/drone-minco-s4-knots.cpp -o "$DRONE_S4_BUILD/minco_s4_knots"
python3 apps/fishbot-control-station/workbench-tools/drone-stop-qualification.py --geometry-report "$STOP_REPORT_ROOT/stop-position-time-comparison.json" --stopping-report "$STOP_REPORT_ROOT/stopping-viability-evaluation.json" --earlier-handoff --y-inner --handoff-times 33.428 --native "$DRONE_S4_BUILD/minco_s4_knots" --output "$STOP_REPORT_ROOT/stop-s4-inner-point-qualified.json"
python3 -m unittest discover -s apps/fishbot-control-station/workbench-review-tests -p test_drone_s4_knots.py
```

原忽略目录保留首轮stop-s4-inner-point-comparison.json；正式产物为stop-s4-inner-point-qualified.json、stop-s4-inner-readback.json、stop-s4-inner-comparison.png。
下一项复用原N2参考前缀和N3切点PVA/J，核完整候选适用域；求解截止、实际状态/跟踪、未来自由图与终端区域仍分列未获资格。
无Web改动、训练、ROS节点、仿真、控制或新飞行；drone c866441及官方缓存未改，M2部分完成、M3不解冻、动态闭环未通过。
