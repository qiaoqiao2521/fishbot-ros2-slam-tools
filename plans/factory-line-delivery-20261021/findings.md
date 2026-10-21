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
