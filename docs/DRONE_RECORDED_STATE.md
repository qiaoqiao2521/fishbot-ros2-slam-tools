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
