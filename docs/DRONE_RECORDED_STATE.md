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
