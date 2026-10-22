# F1 Findings

## 已复用
- 原 workflow 已支持任意 N 个 batch 和每批 delivery_pose；只需让新场景的订单数据进入原初始化入口。
- 原 prepare 在编译碰撞体后生成激光切片和完整碰撞图。实体通道占用在编译前加入，可复用同一地图生成链。
- 原独立 oracle 区分执行终态、物理交接/运输与目标停车，不新增评分实现。

## 当前边界
P8 保留 39 项运行文本观测和所有 A–J 失败。J 的新 frame 已进入回调但缓存提交受控制锁阻塞；独立短缓存锁候选尚待定向测试与原生运行。H 未获得 callback 调度的间隙不能由该修复直接宣称解决。

ARIAC2025 仅作订单、工位与交付评价语义参照。官方来源已由场景worker打开核实：[ARIAC仓库](https://github.com/usnistgov/ARIAC)、[2025文档](https://pages.nist.gov/ARIAC_docs/en/stable/index.html)、[任务场景](https://pages.nist.gov/ARIAC_docs/en/main/pages/scenario.html)。当前一物体在两订单之间显式 reset；不宣称同回合多货物库存、真实产线 PLC 签收或跨引擎统一物理。

## 实体通道与缓存修复
- 占用箱 world 中心(-.45,-2.10,.25)m，完整尺寸(.18,.30,.50)m；同步写入 world、arm-contact 与 rig，arm-local 坐标按原 station_offset 平移。原 prepare 自动生成两地图，无第二套栅格化。
- 四个静态 MuJoCo3.3.7 场景（FishBot/J100×open/occupied）由场景 worker 编译测试；两图占用中心 open254/occupied0、原状态维数与物理参数保持。完整足迹直线受阻但端点/出站不占，有几何连通路径。这不是 Nav2 可达或实际配送证明。
- 缓存修复209项相关回归通过，P8原生K在140/9110独占运行；F1将在其清理后串行启动，不让同机两物理运行争用。

## 评测审查修正
- 原 native_cleanup_known 不能单独授权关闭运行中的整车臂任务；F1薄层先核同任务/回合明确终态，再复用原native/quiet证明。不修改P8运行源。
- 物理裁决与预算分开：原score通过不代表360秒内完成。每单finite elapsed≤360和整轮≤1000另外进入整体验收，缺时长不计通过。1000是验收预算，不冒充包含阻塞评分/清理的硬退出时刻。

## 当前修正
上述 v1 箱体与运行状态是历史记录。v1 原几何预检失败且零运动；当前 v2 箱体中心(.35,-2.10,.25)、完整尺寸(.12,.30,.50)。独立实跑开放场景2/2、占用场景1/2物理通过；B原生成功但物理位置4.3478cm，保持false。不能把Workflow或Nav2终态当作物理通过。短缓存锁与清理诊断已验收实现，J100的低速小转向响应不足仍独立校准中。


旧prepared不是当前实现：occupied-v2的生成YAML仍checker stateful=true且RPP未显式false；新prepare已读回双false、原native .015/.035门槛。direct/via必须共用新prepared，不能把旧YAML和新代码组合冒充当前配置。同一已生成输入可跨两个资源窗口独立启动，前提运行源码、场景、订单和原评分不变；新run/UUID分开，时段负载差异不得当策略效果。


实际派生manifest需要贯通生产器：首direct零订单启动失败揭示cooperation_sim.source_identity固定从world旁读scene-manifest，launch却只给bridge传derived路径。模拟器实际仍有物理帧，但bridge按现有manifest身份合同拒收，因此无ready。薄修复显式--manifest→Physics→source_identity并由launch共传，两端同源；保留无新参数的默认。原result保留unknown/未评分及独立owned清理回执，不当运输失败样本或成功成绩。


失败任务的原oracle可合法返回final_true_pose_error=None；汇总器必须保留缺失，而不是调用.get导致报告与finally二次失败。最小or{}只让读取可用，输出仍None、原false评分不变。实际fixed direct入站超时揭示该缺口，22项回归覆盖。原内存run_id/源码end快照丢失时，只读恢复摘要应明确不可恢复，不伪造ID或起止一致；同task/episode/native UUID仍可独立验收失败与清理。

fixed direct末段真实cmd线速度0而角速度正负交替，map 15mm圈30源秒跨110次；状态锁成对关闭可能将入站也带入位置/朝向切换。派生身份修复已通过真实ROS接纳，但不是完整配送已修复。需要阶段控制合同整改，再冻结同源direct/via；不把该入站失败当两种路线的对照。


阶段整改采用原生配置实例而非新控制器：Nav2 1.3.13 [FollowPathAction](https://raw.githubusercontent.com/ros-navigation/navigation2/1.3.13/nav2_behavior_tree/plugins/action/follow_path_action.cpp)确实将controller_id/goal_checker_id写入原action；[NavigateToPoseNavigator](https://raw.githubusercontent.com/ros-navigation/navigation2/1.3.13/nav2_bt_navigator/src/navigators/navigate_to_pose.cpp)在goalReceived读取behavior_tree，不允许活动目标用不同树直接抢占。现桥原目标终态后才下一动作，故可复用阶段树而无需额外owner/重发机制。软件XML绑定不等于已证原生插件消费，多实例生命周期、连续新回合和完整物理回合仍待验。

2026-10-22静止阶段实跑补充：Nav2 controller_server先处理goal更新、costmap freshness并调用`isGoalReached()`，只有未到达才进入`computeAndPublishVelocity()`；RPP的`/received_global_plan`发布位于`computeVelocityCommands()`内部。原e两个目标均取当前AMCL位姿，日志连续显示`Received a goal`和`Reached the goal!`，中间没有控制计算。因此零路径消息不能解释成DDS QoS失配，也不能证明StagingPath或FollowPath消费了路径。BestEffort订阅通常可接收Reliable/Volatile发布；若要观察阶段控制器，必须使用会进入控制循环且产生至少一次控制计算的路径/目标，并同时保存消息、endpoint QoS和阶段时序，不能靠只改订阅QoS把静止测试变成成功。

同一e日志的17条旧时戳车体命令拒绝分布在两个静止Goal结束及清理周围，没有造成样本离开`car_hold`。它记录的是该旧命令被物理侧拒绝，不证明新鲜命令可被接纳，也不覆盖运动中的命令时效、导航或交付验收。

2026-10-22 0.25m两阶段运动探针补充：RPP的`/received_global_plan`发布端在DDS发现中确有两个原生`controller_server` endpoint；rclpy普通消息回调未暴露`publisher_gid`，所以该字段只能作诊断，不能把“两阶段消息GID不相交”设为通过条件。Stage1收到364份计划、365条控制命令且原Goal4，证明该请求窗口出现了控制计算；具体RPP实例的独立发布者归属仍缺失。Stage1物理终点误差0.0940874m仍失败。Stage2从该偏差状态进入RPP碰撞重试与恢复，原Goal5；旧探针超时后未复制该阶段消息，空数组不能证明没有计算。实体碰撞几何、软膨胀代价与RPP预测足迹是不同判据；缺少实际局部轨迹/costmap逐点代价证据，不能独占根因或换成开阔场景冒充原厂区路径通过。

探针RCL上下文退出后，清理阶段的hold由真实physics源确认；这与launch/端口回收分开验收。阶段探针本身不改控制器、收敛或安全门槛。下一软件单位宜先只读提取Stage2的计划、局部costmap、RPP候选carrot/碰撞采样，并检查是否由终点收敛与inflation共同造成；任何修复须在新prepare、原场景和原评分下独立验收。

### 本轮撤回的解释与已验证缺陷

同版[InflationLayer](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_costmap_2d/include/nav2_costmap_2d/inflation_layer.hpp)提供分级代价；[RPP CollisionChecker](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_regulated_pure_pursuit_controller/src/collision_checker.cpp)按预测足迹及致命代价判断。不能从“目标中心距占用0.29m，膨胀半径0.3m”推断硬碰撞，也不能据此断言0.044m/s由膨胀层导致；[接近目标减速](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_regulated_pure_pursuit_controller/include/nav2_regulated_pure_pursuit_controller/regulation_functions.hpp)等机制同样影响速度。本次明确撤回此前这两条因果解释，原运动失败不改判。

旧探针在`get_result`成功返回之后才复制阶段消息。Stage2超时会跳过复制，故原result中的消息数量未知；不能再写“未产生计划/控制命令”。新增`record_phase_wait`在finally保存，测试实际触发其TimeoutError分支，核对已保存消息、原计数与未知终态。source/wall预算分开，缺GID保持unknown；每帧删除重复manifest，保留episode身份与单份完整来源。

静态新fixture的首轮预检失败定位到MuJoCo3.3.7旧箱体查询：车姿态(0,-2,2.2938613026)，托盘中心(.0185194,-1.9303076,.162)，障碍中心(.35,-2.1,.25)，两世界AABB沿X分离，`mj_geomDistance(...,.2)`却返回-.506279389m。独立双箱最小模型复现其矛盾。公共几何查询现对严格分离的box-box返回保守AABB下界，AABB重叠仍调用原生查询；真实重叠负例和原声明路线的开放/占用检查通过。不改变nativeccd、接触、几何尺寸或原物理评分，不将该静态查询缺陷倒推为旧RPP失败根因。

2026-10-22固定朝向probe check9fe1577a-54f3-4583-8a54-44adc61c133d：Stage1计划331/命令332，Stage2计划1411/命令1411；前者原UUID4但真值XY.066540481m，后者末端转向超时取消原UUID5。日志未出现collision ahead、Failed to make progress或Controller patience exceeded，不能将本轮归为碰撞拒绝。Stage1首次AMCL进入15mm圈时yaw误差2.601rad，结束时AMCL XY6.227cm/真值6.654cm；Stage2进入位置圈后多次角速度反向，末yaw仍2.745rad。此为收敛现象证据，不独占根因。

`EncoderOdometry`已从真实编译轮轴推导偏置并转换回foot原点，不能把忽略轮轴偏置当作漏改。为隔离控制消费，新增显式aligned目标朝向，不改固定目标或配送验收。系统已安装rclcpp28.1.22的MessageInfo暴露原生rmw publisher_gid，而本地rclpy包装层没有；故采用约60行只读订阅器，不改RPP、不造控制器。其消息按同机CLOCK_MONOTONIC对齐原accepted窗口，必须归属已发现的controller_server endpoint，overflow/未知来源不充作完成。

aligned原生checkfa4ebc93：C++实际消息GID分别为010fa54e488cb39f0000000000006c03与010fa54e488cb39f0000000000006703，与运行中的两个controller_server endpoint逐项一致；331/193条在原accepted时间窗内、两阶段独占且不同。Python计划数331/195，默认阶段额外2条落在C++accepted窗外，分开记录不强行凑齐。每阶段均有实际平移、非零控制、原外层及FollowPath子Goal成功和原物理误差通过；控制器消费/切换缺口已补齐，不能据此称原F1配送已通过。

fixed首阶段在源18.5s以后命令v始终0，轮轴真值从(-.2118484,-1.9716661)到(-.2111766,-1.9692849)，只漂2.47mm；foot原点则随转向绕轮轴移动。该读回支持坐标点转向位移的几何解释，但18.5s的AMCL/真值还存在平移差，不能把全6.65cm终误差独占归为轮轴或忽略定位误差。已有原里程计补偿与物理碰撞保持。

原staged occupied direct run c15891fe-7f44-48de-93ab-935b4b98c050：两单入站各使用staging树，原入站Nav与Dock均4，第一单完整通过；第二单装货/交接/原K仍通过，但载货目标(.7,-2,0)原UUID39cdc2aefe75407f82aa008a13418693在120.06墙秒取消5。最后30墙秒，862物理样本、源330.20–347.42，hold全部false、禁碰0；XY误差.013092–.022339m，abs yaw1.301287–1.787098rad，真实yawrate-.744188至+.704035。601条原cmd的v全0，w±.8，角速度符号变21次；54个HTTP map样本跨15mm圈20次，不能把该HTTP位姿当同步控制分支ACK。日志没有collision ahead/progress/patience错误，本轮不支持安全层锁住或没有Goal消费的解释，也尚不能独占根因。

此轮源码selected_text起止一致、运行681墙秒内、两任务均360内；A完整物理通过，B最终位置1.85cm但yaw1.57329rad失败。原完整oracle的native_goal_consumption_ack_claimed=false保持；先前两阶段DDS证明只能覆盖对应探针，不能转写为这两订单每个控制循环的回执。路线策略direct确实调用并返回None，无中转；via仍未跑，不形成策略优劣结论。

当前源planner为NavfnPlanner，配置没有显式use_final_approach_orientation；RPP use_rotate_to_heading=true、stateful=false。同版RPP源码先按carrot到达距离选择目标朝向，否则按carrot方向选择路径转向。RotationShim的末端分支也以XY位置检查为入口，暂不叠加另一层转向。已安装同版SmacPlannerHybrid，官方实现将起终点yaw加入搜索，并使用原完整costmap足迹；选择其作为可选路径候选，控制/评分不改。来源：https://raw.githubusercontent.com/ros-navigation/navigation2/1.3.13/nav2_regulated_pure_pursuit_controller/src/regulated_pure_pursuit_controller.cpp 及 nav2_smac_planner/src/smac_planner_hybrid.cpp。当前只完成候选接线，尚未有新原生结果。

全Smac check2604eaa4-3aef-4bc3-bf20-6d115323673c：原两个Goal均4，stage XY.06730769m/yaw.05267926rad失败，default XY.03825184m/yaw.02458898rad通过；整体false、errors空不等于业务通过。原生planner参数匹配，运行前后不变；GID切换已观察，69.224墙秒且完整清理。日志曾无法规划短U形再由原BT spin恢复，不能称姿态规划全面更优。基于默认运输段通过、原完整任务入站已成功的证据，下一候选仅运输换Smac，入站保留NavFn；保留该试验原件与源码a076e86。

分阶段Smac短试验check686917c3-21ee-40d9-9b2c-cecfb73c8b04仍failed：两原Nav4，stage .06634146m/.03468895rad、default .05913391m/.02441632rad；双planner/原RPP参数前后不变，完整清理。default同末段AMCL近邻源44.3与真值44.22，XY差.0719843m，源龄差.08s；成功到hold后真实位移.1258mm，不能把5.91cm归为刹车滑移。离线模型重建扫描的近似likelihood在真值附近优于该估计，但非原生AMCL重放，保留这个边界。

原生AMCL 1.3.13均值复现发现可确定的模型不匹配：实际foot在轮轴前2cm，转向会有每步<1cm的侧向圆弧；DifferentialMotionModel在此分支rot1=0，半圈100步的期望位移(-.04,0)被预测为(.0006283,.0399951)，误差.0570111m。直接调用已安装lib的OmniMotionModel得几何期望（误差1.72e-19）；偏置0及25cm直线对照均正确。这不是“忽略轮轴的里程计”旧猜测：原EncoderOdometry已正确转换，问题在下游提议模型如何解释该参考点的增量。它证明均值合同缺陷，仍不独占运行中的全部误差或证明整滤波已修复。
