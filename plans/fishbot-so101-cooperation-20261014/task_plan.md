# 固定 SO101 工位与小车运输

## Goal

在同一 MuJoCo 世界完成 FishBot 停靠、SO101 真实抓放到车载托盘、机械臂退出和小车运输。App 显示实际阶段与合作对话。

## Scope

- 复用既有 FishBot 车体、ROS2 Jazzy/Nav2、SO101 原模型及 IK/OMPL/碰撞规划。
- 活动任务内同一自由货物始终通过物理接触交接，不重置、吸附或跨世界复制。显式新回合边界可恢复编译初态。
- 独立 domain114；当前107网页、用户规则与ROS保持；RViz配置保留。
- SO101 项目只读依赖，明确路径与来源；不提交其既有大量未交付状态、标定或运行日志。
- 固定工位与合成10g物体；没有实体操作或策略训练。宇树作为后续移动角色，模型与行走控制另行验收。

## Phases

1. 同一物理场景、静止车障碍规划与真实接触探针：complete。
2. ROS薄传感/执行适配及Nav2停靠：complete。
3. 任务编排、取消与实际反馈对话：complete。
4. 网页可见入口、共世界画面与手机交互：complete。
5. 原生完整运输、负例、独立真值、全部检查与Git源码交付：complete。

## Ownership

- 根：编排/API、launch/CLI、原生与页面验收、项目与知识收尾、串行提交推送。
- coop_scene_arm：场景与复用规划薄适配。
- coop_ros_physics：共享物理世界ROS传感与setpoint薄适配。
- coop_ui：协同页面、状态契约与交互测试。

## Acceptance

同一货物实际抬升至少25mm、双指各至少0.02N且保持1s；释放后托盘支撑、低指力和低相对速度持续1s；机械臂实际退出再启动车辆。独立记录车、臂、货物和clock，验证货物随车至少0.5m并最终留在托盘；车体与货物停稳。未停靠和抓空不能报成功；取消保持同ID并停稳，未知不重发。网页展示实际共享画面和真实事件，桌面/390px可操作。

## Adopted knowledge

采用 Obsidian FishBot 的未知回执约定，以及 SO101 现有 grasp_episode/placement 的自由物体接触与落稳条件。保留原1mm碰撞与0.2mm载荷余量；不能把ROS task_executor仅发轨迹后sleep的OK当成抓放反馈。

## Next Step

K原验收与L用户完成记录保留。M同一114进程连续两轮独立物理评分通过；第三回合已通过网页重置为ready/idle。当前用户可显式开始新运输。后续移动角色、噪声/遮挡与真实视觉停靠另开验收边界。

## 2026-10-14 重复回合补充

用户反馈一轮完成后不能再次开始。当前success货物已离开取货盘，原ready门禁正确，但缺少新episode入口，视为必需UX缺口。

实施：terminal/原生动作终态/车臂货物quiet/hold与guard确认后，一次UUID+expected episode重置合成世界；时钟、编码器odom与累计发布序号连续；帧与旧命令按episode/source时刻隔离。重置后原生初位姿与costmap清理确认，再开放Start。未知只核对原reset编号，不重复操作、不自动开任务；保留旧server账本与对话。网页明确“重置场景”→“开始装货运输”。

分工：root维护bridge/core/frame URL与串行部署；coop_ros_physics维护plant reset/物理回归；coop_ui维护控制器/页面/receipt；coop_nav_diagnostic维护只读私有oracle。SO101只读；107/网络/地图规则不改。

验收：至少两轮实际完整运输，每轮相同自由货物接触抓放/≥.5m运输/quiet/无禁止接触与native status4；第二轮通过网页reset恢复，并保留第一轮历史。新episode边界允许恢复编译初态，任务活动窗口仍禁止reset、吸附或teleport。失败与误判保留，source冻结与运行绑定。

本补充实施与两轮独立物理验收已完成。详细检查、迟到反馈修正及Git交付回源progress；不将旧观察器退出超时抹去。
