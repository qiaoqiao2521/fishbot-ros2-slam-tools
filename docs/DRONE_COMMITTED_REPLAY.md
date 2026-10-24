# M0 / M2：官方复用边界与完整提交轨迹的离线回放

本片核对Gatekeeper官方源码与本地`CommittedTail`，并增加完整前缀＋MINCO刹停尾的离线选择回放。
无人机源码仍冻结在`c866441`。没有训练、ROS启动、PX4/Gazebo、控制提交或新飞行。
M0源码选型已核；M2仅完成静态反事实场景中的接纳/失效切片，动态闭环仍未通过。

## 官方源码和许可

2026-10-24从官方GitHub读取下列版本。提交号用于标识本次阅读，不用于限制文件编辑或执行。

| 官方项目 | 阅读版本 | 实际内容与本轮结论 |
| --- | --- | --- |
| [gatekeeper](https://github.com/dev10110/gatekeeper/tree/a54dac7e3bf94686bd99d7f95d601069ecaa6e56) | TRO / a54dac7e3bf94686bd99d7f95d601069ecaa6e56 | 根[LICENSE](https://github.com/dev10110/gatekeeper/blob/a54dac7e3bf94686bd99d7f95d601069ecaa6e56/LICENSE)为MIT。README明确src是firewatch示例，Project.toml含Julia/Gurobi等依赖。它不是本机可直接启动的ROS2无人机包 |
| [gatekeeper-exp-xavier](https://github.com/dev10110/gatekeeper-exp-xavier/tree/7c8f87adcf4f7c93866a7e35e3ed66efb4fc775a) | master / 7c8f87adcf4f7c93866a7e35e3ed66efb4fc775a | 官方主仓指向的机载实验。递归树未见独立LICENSE/COPYING；gatekeeper的[package.xml](https://github.com/dev10110/gatekeeper-exp-xavier/blob/7c8f87adcf4f7c93866a7e35e3ed66efb4fc775a/colcon_ws/src/gatekeeper/package.xml)与setup.py均为TODO许可。不能沿用另一个仓的MIT声明，当前不复制其实现 |

机载README使用Isaac ROS开发容器和RealSense。子模块记录了各自提交，但没有本项目所需的Jazzy/PX4 v1.17/MAVSDK版本合同。
其`.gitmodules`含独立的dasc_ros、px4_msgs、DecompROS2、nvblox、vicon、JPS等来源；子模块许可各自适用，本轮未做全部许可证审计。
未克隆、安装或编译该机载栈；Jazzy兼容性仍待核，不能以Python源码可读判为可运行。

**采用决定：**复用本项目已有`CommittedTail`、MINCO_S4NU和连续审计；官方机载源只用于核对算法/接口条件。
MIT firewatch示例与本机执行接口差距较大，机载包许可未明确；当前缺口只需离线薄适配，不重建其ROS容器、消息栈或控制owner。
没有移植Gatekeeper实现，也不声称本地原型继承其安全定理。

## 具体接口差异

官方源码链接均固定到上表机载提交。

| 项目 | 官方机载实验 | 本地实现与本片处理 |
| --- | --- | --- |
| 状态/动力学 | [gatekeeper.py L46/L104](https://github.com/dev10110/gatekeeper-exp-xavier/blob/7c8f87adcf4f7c93866a7e35e3ed66efb4fc775a/colcon_ws/src/gatekeeper/gatekeeper/gatekeeper.py#L104)默认ORDER=2，用当前位置和速度；加速度为控制输入。[Integrator](https://github.com/dev10110/gatekeeper-exp-xavier/blob/7c8f87adcf4f7c93866a7e35e3ed66efb4fc775a/colcon_ws/src/gatekeeper/gatekeeper/utils_integrator.py#L94)构造离散积分器与LQR闭环传播 | 本地直接比较参考/观测PVA，不预测PX4闭环响应。本片观测由参考曲线合成，漂移显式注入；没有标定跟踪包络 |
| 备份 | [simulate_tree](https://github.com/dev10110/gatekeeper-exp-xavier/blob/7c8f87adcf4f7c93866a7e35e3ed66efb4fc775a/colcon_ws/src/gatekeeper/gatekeeper/utils_integrator.py#L199)枚举切换时刻，传播跟踪及停止控制；按最长名义跟踪分支先验 | 已有分轴S4NU保留切点参考PVAJ；本片复用N3已生成的固定时长3.5/1/.4s，没有新搜索或优化 |
| 几何/终端 | [is_valid](https://github.com/dev10110/gatekeeper-exp-xavier/blob/7c8f87adcf4f7c93866a7e35e3ed66efb4fc775a/colcon_ws/src/gatekeeper/gatekeeper/gatekeeper.py#L384)验终端控制/速度与离散位置SFC；utils_gatekeeper对终点加倍tracking radius，并含近地判定条件 | 本地连续Bernstein余段检查；终端VA接近零仍不等于未来安全。适配要求显式已知空间、当前观测时效和覆盖剩余时域＋有限.5s的静态地图有效期；不称不变终端集 |
| 时间/坐标 | 源状态转换NED→ENU；[state_callback](https://github.com/dev10110/gatekeeper-exp-xavier/blob/7c8f87adcf4f7c93866a7e35e3ed66efb4fc775a/colcon_ws/src/gatekeeper/gatekeeper/gatekeeper.py#L136)有PX4与ROS时间差计算；[publish_traj](https://github.com/dev10110/gatekeeper-exp-xavier/blob/7c8f87adcf4f7c93866a7e35e3ed66efb4fc775a/colcon_ws/src/gatekeeper/gatekeeper/gatekeeper.py#L468)输出vicon/world、header.stamp、dt及离散PVA | 本片全部为同一显式sim epoch、scene_enu_m和绝对start_sim_s。未引入墙钟、坐标转换或飞控消息；禁止把原时钟公式直接套到Gazebo |
| 提交/执行 | 机载节点发布DITrajectory；launch另起setpointPublisher。候选无解时节点不发布新轨迹，旧轨迹的实际继续行为还依赖下游 | 本地拒绝保留旧active及start；每次tick重验当前地图/误差。适配只输出selected_reference_pva，没有ROS/MAVSDK传输和采用回执 |

## 已复现的时间缺口

冻结源`scripts/replay_minco_handoff.py::CommittedTail.admit`不检查/更新`last_now`。
最小复现：接纳start=now后，首次tick(now−.1)仍返回track；负elapsed被原pva函数截到起点。
复现的validate仅为显式桩函数，用于隔离时钟问题，不是占据证据。
原tick还会用无效now覆盖last_now，NaN可令后续大小比较失效。

适配在每次事件、包括admit之前维护有限时钟高水位；NaN或回退不覆盖基点，撤销当前选择。
没有修改冻结源。连续拒绝、空备份、跟踪误差仍保留原保护语义。
重复sim时刻的参考相位不前进；观测漂移超过数值容差则protect。
这不能检测停钟时墙钟经过了多久，也没有真实遥测序号/新鲜度接线；在线前仍需该合同。

## 离线回放如何组合

入口为`apps/fishbot-control-station/workbench-tools/drone-committed-replay.py`。

1. 读取[N3候选](DRONE_STOP_CANDIDATES.md)中预声明的#6和#7，不搜索其他初态或调低原判据。
2. 将原0.8s参考前缀和S4NU刹停尾作为一个带绝对起始时刻的对象。
3. 重新调用原audit_minco检查完整曲线、尾段C3及切点jerk；不信任缓存passed布尔值。
4. 以原CommittedTail接纳/选择，适配核task/scene/clock/frame及map revision。
5. 候选拒绝后，仍在同一事件按旧start取值并重验旧曲线；新占据/未知/过期等则撤销选择。

整条参考前缀保留原cubic内部jerk跳变，只声明C2；切点与刹停尾的C3单列。
已知地图使用反事实静态配置空间box=[−10,−10,0]至[15,10,2.2]及显式体素。
它是测试夹具，不是原748回合GridMap，不证明原#6的Y终点2.325m在原场景安全。
地图未来有效区间同样是合成已知静态世界的声明；没有动态预测器或感知生成的safe set。
1e−7的P/V/A列误差仅隔离数值回归，不能作为飞机的物理跟踪预算。

`protect`输出`selected_reference_pva=null`，不是刹停、返航或落地控制。撤销轨迹后的现实恢复仍未闭合。
终点侵入负例只证明下一次当前观测检查会撤销悬停，不证明侵入前可避开障碍。

## 本次结果

#6完整曲线重审V=1.680870694m/s、A=.981600424m/s²、Z=2.133050762m；原1.8/1/2.2硬界保持。
#7因acceleration/tail_acceleration拒绝，旧#6按原相位继续，进入braking_tail与有限terminal_hold。
16个反事实情景、8项局部测试覆盖：

| 行为 | 观测结果 |
| --- | --- |
| 拒绝新候选 | 旧start不变；选取旧elapsed=.2s，未跳未来切点 |
| 新占据进入余段/终点 | remaining_voxel_violation，清除当前选择 |
| 重复时刻/观测漂移 | 相位不变；漂移触发tracking_state_mismatch |
| 首tick回退/NaN后回退 | clock_rewind；有限高水位保留 |
| 地图未知/未声明已知覆盖 | map_unknown / known_space_unverified |
| 只有当前快照、无未来区间 | map_prediction_horizon_unverified |
| 过期/未来时间戳/不同场景 | 各自拒绝，旧证书不继续称安全 |
| 错任务/未来start/无备份 | 候选身份拒绝或protect；有效旧轨迹可继续 |
| 缓存passed仍真但系数被编辑 | 重审拒绝；坏候选条目不抹掉仍有效旧轨迹 |

这是选择逻辑和连续审计的离线证据，不是新任务的安全/功能通过率，也不是动态hazard→safe闭环。
原历史failed、未记录备份和感知缺口保持原状。

## 复验与接续

在工作台仓库运行：

```sh
python3 apps/fishbot-control-station/workbench-review-tests/test_drone_committed_replay.py
python3 apps/fishbot-control-station/workbench-tools/drone-committed-replay.py --candidates "$CANDIDATES_JSON" --output "$REPLAY_JSON"
```

`CANDIDATES_JSON`取原诊断缓存748回合的stop-candidates.json；生成方法见N3文档。
本次REPLAY_JSON位于忽略的`apps/fishbot-control-station/workbench-tools/output/drone-committed/748f910e-f0f8-4ecf-b2d5-22b7b15d57e6/selection-replay.json`。
JSON保留输入、上下文、每事件的候选拒绝/选择、原审计和地图revision；原生采纳与dynamic_safety始终未验证。
坏候选局部拒绝；坏场景项保留错误并继续其他情景，不通过异常退出伪装整体安全。

下一项仍是M2：明确有来源的实际状态/预测、时间有效地图与终端区域，再做完整滚动替换资格；没有这些输入时保持unverified。
本片未改网页、服务或飞行源码，因此不重复Web构建、浏览器QA或机器人实验。
验收与owner见[工作台进度](../plans/workbench-code-rebuild-20261018/progress.md)，由当前对话接续。
