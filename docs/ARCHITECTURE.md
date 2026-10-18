# Local architecture

重要取舍见 [DECISIONS](DECISIONS.md)。当前阶段与计划入口见 [PROJECT](../PROJECT.md)。

2026-10-18 [跨层重构](../plans/workbench-rebuild-20261018/task_plan.md)的运行合同、共享工作面和地图任务迁移已实施。下文描述当前结构；未通过的人工控制、语音及性能验收见[进度](../plans/workbench-rebuild-20261018/progress.md)。Lichtblick完整源码重建在独立工作树推进，本目录不同时导入第二份上游源码。

四个服务已提供独立运行身份与能力。网页共用运行上下文读取器，并按实例/场景/回合代次隔离迟到响应；五类Java资源分别标识来源。任务页面将提交、原生执行、清理停稳和独立评分分开展示。兼容与恢复边界见[RUNTIME_CONTEXT](RUNTIME_CONTEXT.md)。

- `apps/fishbot-control-station/`：Java/React控制台。
- `fishbot_nav/`：Jazzy导航/描述/接口工作区。
- `fishbot_laser_ws/`：实际使用的Python网络雷达驱动工作区。
- `workspaces/micro_ros_agent_ws/`：micro-ROS Agent及消息源码与本机构建。
- `fishbot_motion_control_microros/`：主控固件源；`fishbot_tool/`：烧录工具与固件素材。
- `tools/`：运行编排和安全门；`fishbot.sh`：统一入口。
- `plans/`：建图、网络及本地成果。`fishbot/`和`fishbot-control-ros2/`是保留的历史实现，不与活动工作区混编。

源码向内收敛，旧路径向新项目链接。保留Git目录以保护历史，暂不自动压平为单仓。旧安装目录中的绝对路径可能经兼容链接工作；fresh build验收应另行记录，不能用布局通过替代。

`/workbench` 与 `/simulation` 共用地图工作面和唯一任务owner；`/radar` 与 `/cooperation` 使用相同布局宿主。桌面复用Dockview，手机显示单画布和底部面板。provider持有任务与连接，视图隐藏时暂停绘制和解码；布局缓存只保存显示配置。`/results` 汇总六项成果和冻结评分摘要，不初始化运动控制。SpatialLM与视频工具保留独立仓库和写协议；工具检查仅发GET，上次检查时刻不代表持续在线。原56例与新增回合分开展示，见[WORKBENCH](WORKBENCH.md)。

三维视图复用Three.js官方GLTF/PCD加载器及URDFLoader。解码输入、点数、队列和刷新率均有上限，Worker只保留最新待处理帧；同尺寸数据更新复用GPU缓冲。渲染只读取投影，不拥有ROS动作。WebGL恢复、布局重建和历史回放不能重发运动。模型许可、来源与能力按注册表声明，简化模型不冒充完整硬件模型。

人工控制使用唯一前端owner与租约合同，经官方twist_mux、速度平滑、Collision Monitor和最终守卫驱动仿真底盘。过期非零命令不回放；停止、原动作终态和连续静止分别确认。Java旧写入口默认由服务端拒绝。ROS桥的慢事件诊断仅写有界内存环，原状态GET读回，不在控制锁内同步写诊断日志。真实面板尚未通过，不能把静态合同称为已验收的人工控制。

语音面板通过固定loopback代理连接`fishbot_voice_bridge.py`。真实音频复用Vosk CPU识别与FFmpeg，识别后先预览，再显式确认。网关校验原时间、会话、序号和UUID，将任务交回既有MissionBridge或cooperation bridge；没有语音Twist发布者。取消只针对原任务，未知回执禁止重发，任务期限由原owner执行。默认独占仿真域121，模型和音频留在项目外。回充适配器未配置时明确禁用。协议和运行入口见[VOICE](VOICE.md)。

控制站 `/radar` 使用 React → Java → rosbridge，提供初位姿、导航目标和真实 `/plan` 叠层。显式提交前只保留位置与朝向草稿。模拟环境采用实际 `/clock`，连接代次隔离旧路径和旧时钟。`/simulation` 继续复用 Python mission bridge 的巡逻与 Goal 所有权，两页分别标识运行环境。数据契约和本轮验收见 [map-navigation.md](../apps/fishbot-control-station/docs/map-navigation.md)。

`/cooperation` 使用独立domain114及同一MuJoCo世界。Nav2速度通过ROS薄适配驱动车轮；SO101规划复用只读依赖，规划克隆冻结停止车辆，执行器驱动实际关节。任务桥按双指接触、货物抬升、托盘落稳、机械臂退出与载物停车的反馈推进。相机与货物始终属于同一世界；原生目标回执和取消按任务所有权分别确认。入口与验收边界见 [COOPERATION.md](COOPERATION.md)。

工位观测通过标准PoseWithCovarianceStamped与DiagnosticArray同源时间配对，在桥接器校验来源、回合、序号、时龄与协方差后，才唯一转发原生停靠PoseStamped。显式ideal/perturbed/vision模式固定到manifest，vision使用独立系统OpenCV的AprilTag/IPPE生产器，只接真实后向RGB、标定和帧身份。AMCL负责接近段，RGB只提供原生Dock目标。默认/受扰物理传感器复用50Hz状态测量，旧帧与失检不重打时间；独立cooperation_oracle只观察和评分，不控制车辆。完整源冻结与清理由运行验收负责。

`/simulation` 的虚拟墙与禁区使用独立版本化规则。mission bridge 发布 mask 与 filter info，Nav2 global/local 的 KeepoutFilter 和后置原生 InflationLayer 实际应用规则；软件规则不成为 MuJoCo 墙体、雷达回波或 AMCL 原地图。路线模板只保存任务输入，实际执行仍由原 FollowWaypoints 所有者派发并记录终态。配置、应用读回、未知回执与独立物理验收见 [MAP_RULES.md](MAP_RULES.md)。

纯TypeScript的PatrolMissionTracker负责草稿/演练及标准Goal、现有HTTP任务转换；MapZonesManager负责几何、对象隔离与既有规则转换。页面不使用演练completed判断真实任务完成。地图导出直接返回原发布者的实际FilterInfo与OccupancyGrid快照，按地图和版本校验后下载；没有第二个ROS栅格器或任务执行者。

巡逻选点通过route-safety薄适配复用原几何库，显示原目标红线与首次冲突前的吸附点。PatrolDraftController只管理本地草稿、Web Locks/CAS与连接代次，不发送ROS请求。缓存revision_id、服务器规则revision和原任务UUID分别校验；存储异常降级内存并保留错误，未知任务不重发。详见[航点草稿保护](MAP_RULES.md#浏览器航点草稿保护)。

连续过窄口入口使用 `Nav2 → 速度平滑 → Collision Monitor → 最终命令守卫 → 底盘`，统一官方模型外廓，区分限速余量和硬碰撞范围，并记录可回放的停车数据。配置、仿真和实车接入边界见 [PASSAGE_CONTROL.md](PASSAGE_CONTROL.md)。原短段控制脚本保留；两套入口不可同时控制最终速度。

虚拟视觉巡检使用独立 domain 97：AMCL/Nav2 到点、停稳、三帧新鲜车载 RGB、像素判断、图文报告、返航。相机与三工位场景位于 `workspaces/fishbot_mujoco_ws`；入口和验收边界见 [VISUAL_INSPECTION.md](VISUAL_INSPECTION.md)。物理真值只核验拍摄位姿和到点误差，不输入图像识别。

家庭场景闭环使用独立 domain 98，串联具名地点、视觉巡检、换位重观测和低电回充。生成器保留本地地图的已知格，只补全未知区域，并从同一栅格生成 MuJoCo 墙体和 Nav2 地图。图像判断只读取 RGB；模拟电池、接触条件和对接信标使用明确标注的仿真模型。导航优先使用 RPP，指定控制失败可串行回退至 MPPI；速度平滑与 Collision Monitor 保留。七项同轮验收和两种失败退出已通过，入口、证据与能力边界见 [README_FISHBOT_HOME.md](../tools/README_FISHBOT_HOME.md)。
