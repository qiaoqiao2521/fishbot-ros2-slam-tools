# 固定 SO101 工位与小车运输

## Goal

在同一 MuJoCo 世界完成 FishBot 停靠、SO101 真实抓放到车载托盘、机械臂退出和小车运输。App 显示实际阶段与合作对话。

## Scope

- 复用既有 FishBot 车体、ROS2 Jazzy/Nav2、SO101 原模型及 IK/OMPL/碰撞规划。
- 同一自由货物始终通过物理接触交接，不重置、吸附或跨世界复制。
- 独立 domain114；当前107网页、用户规则与ROS保持；RViz配置保留。
- SO101 项目只读依赖，明确路径与来源；不提交其既有大量未交付状态、标定或运行日志。
- 固定工位与合成10g物体；没有实体操作或策略训练。宇树作为后续移动角色，模型与行走控制另行验收。

## Phases

1. 同一物理场景、静止车障碍规划与真实接触探针：complete。
2. ROS薄传感/执行适配及Nav2停靠：complete。
3. 任务编排、取消与实际反馈对话：complete。
4. 网页可见入口、共世界画面与手机交互：complete。
5. 原生完整运输、负例、独立真值与全部检查：complete；Git交付收尾中。

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

K完整网页、原生与独立物理运输验收已通过。完成显式依赖检查、恢复空闲新episode并串行提交推送。后续移动角色、噪声/遮挡与真实视觉停靠另开验收边界。
