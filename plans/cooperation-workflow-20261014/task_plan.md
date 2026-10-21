# 协同长流程编排薄层

## Goal
复用现有 `/coop-api`，串行执行输入列表决定的N个逻辑搬运，每批可选独立目的地。保留 batch、machine、readiness事件版本、动作 UUID、episode 与取消/重置记录。早期两作业模板和历史验收保留；当前新增范围见P7。

## Constraints
基线 `aab0da45a45ac3e380d0afe538adcfae59c22537`。仅独立 worktree `fishbot-workflow-20261014` 与 `codex/workflow-20261014`。不改 bridge/core、主区 dirty 实现、SpatialLM、共享 Wiki。此句限定模块worker交付阶段。FishBot root已串行合入，并按原用户“都做/跨对话协作”授权准备新隔离domain120/API9090实际面板；不接实机。

## Scope
单步 CLI、领域状态机与有界 run；复用 `fishbot_simulation_suite.write_json` 原子替换、标准 `flock/fsync/urllib/UUID`。run 每轮短持锁后释放，等待另一 CLI 的 ready，timeout 1–1800 秒、poll 0.1–10 秒。超时只退出编排器，保留原执行端与任务状态。动作意图先同步落盘，再一次 POST；不重试 POST。原 ID GET 对账。失败在终态与 quiet 已知后显式恢复，新 UUID 留原失败。未知或缺历史封锁下一步。

单货物场景：前 job 实际终态且 `reset.available` 后，显式提交 episode reset。原 reset ID ACK、新 episode 与旧任务 history 一致，才放行第二 job。此流程不代表同一 episode 两货物库存或真实纺织品处理。

## Acceptance
- 两搬运合同：ready 延迟、容量一、batch 身份与事件 ID/连续版本。
- 提交前断电、丢 POST 回执、取消丢回执与重启：原 ID 查询，无动作重放。
- 乱序、冲突重复事件、缺原任务 history、未知终态：封锁。
- between-job reset：terminal/quiet、同 ID ACK、新 episode、保留旧历史缺一不可。
- task failed/canceled：显式恢复；原 attempt 与原因保留。
- CPU 合同回归与 CLI readback，不能代替 ROS/物理验收。

## Phases
1. 接口核对与独立边界：complete。
2. 薄层实施与 CPU 回归：complete，36 项无跳过。
3. 独立审查与 scoped 交付：complete，根独立36项与源SHA核对通过，特性分支远端读回一致。
4. Codex内部交接与root串行整合：complete；原36CPU合同在合入main后再次通过。
5. 前两轮独立取消/恢复通过，运输失败原件保留；第三轮取消＋两运输物理评分通过。
6. 桥端缓存分段诊断与正确reset源时间采集：complete，第二轮仍失败。
7. 原生Clock回调组的实际ROS阻塞验证、最小分组候选与新面板：complete，owner=root。

## Next Step
P8先核对J100物理资产、传感器和现cooperation执行环境的接入差距，再冻结组合配置与实际面板。P7三批通过保持；视觉资格整改仍回源visual-docking计划，不改写此前11失败。

## Root实际面板（2026-10-15）

新输出、新场景，保留原107/114与此前56例。两个不同batch、容量一，默认ideal信标/原远端spawn；同一桥/world跨三个episode：首次job1在已接受且移动的Dock UUID上取消；确认原终态、hold、guard关闭和0.7源秒quiet后显式recover一次。原reset ACK、历史和新episode确认后以新ready版本完成job1；独立score后advance reset，再新ready版本完成job2。只重启CLI/编排过程，不重启桥伪造恢复。两次reset均仅显式新回合边界恢复合成单货物，不称同回合两货物库存。

原每完整任务360s与全部物理/时间/碰撞门槛保持；首启动55s，移动取消阶段120s、每次清理15s，根整项上限1100墙秒。最多一次取消尝试＋两次完整运输，无自动重发；unknown保留封锁和执行owner。延迟合成ready、重复/旧版本/容量一拒绝、原ID重启查询和run有界超时分别取证。每个episode使用独立oracle/markers；静止与原UUID/raw/同货物评分不由网页或退出码代替。

执行源/实际XML/manifest/模块/private验收脚本在派发前冻结，期间root不改源码或计划。SpatialLM官方推理释放窗口后才启动MuJoCo；没有云GPU或新模型训练。此面板不修复或重复本轮视觉留出，不改其11失败。owner=root。

## P7：第三批运输＋第二目的地（2026-10-20）

状态：complete。用户确认用第二个业务验证复用。保留现有cooperation owner、Nav2 DockRobot/载货导航、SO101抓放/退避、取消/quiet、事件/原ID查询与物理评分。将固定两作业改成输入决定的N作业，新增可选per-job `delivery_pose={x,y,yaw}`；无新参数时保留旧目的地及API。不是新增调度平台或运动owner。

本轮同一bridge/world已完成三批A/A/B，A为原交付点(0,-2,0)，B为(.7,-2,0)，两者均通过实际几何预检。三批之间仍显式重置单货物合成episode，不称同回合三货物库存。原transport每轮360s、真实双指抓放、同一货物运输、机械臂回位、载物保持、碰撞/停稳与时钟门槛保持。新增业务验收把原task声明的目的地绑定已接纳任务/原生载货Nav2 UUID与实际终点；仅“运走≥.5m”不算新目的地通过。

分工：根串行更新本计划/文档/项目入口、实际隔离验收和Git；transition_physics负责workflow与局部测试；pump_hardware负责start参数/core/bridge及复用几何helper；seal_model负责独立oracle目的地绑定与测试。工作区原有效成果保留。实验使用独占domain136/API9106、独立私有输出，已完成静止清理；原有实例、实机、CY、网络/VPN或固件未改。

完成标准：旧无参数合同/旧两作业不退化；三作业不再需改源码；每作业目标冻结并随原ID恢复，回执未知不重发；实际三次原生成功及独立物理评分通过、A/B实际终点有区别、实例清理完成。失败原件与缺口保留。最后记录到底改了哪些通用接口、哪些执行能力未改，并提交推送既有qiaoqiao2521远端。

## P8：车型＋传感器配置＋任务（2026-10-20）

状态：in_progress。用户明确要验证换车、换雷达仍可复用同算法。先支持已有FishBot和Clearpath Jackal J100，任务复用原三批A/A/B；传感器组合复用标准LaserScan/PointCloud2与原生射线，配置决定安装位姿与避障数据源。参数与已验收状态分开展示。

不增加仿真平台、运动owner或重试引擎。cooperation使用Python MuJoCo3.3.7，原J100/官方3D插件在ROS C++ vendor3.12环境；禁止混用ABI或把后者分项通过冒充车臂组合通过。薄适配限于车型与传感器资产接入、生成参数、标准数据面与原前端配置入口。控制器、抓放规划与原物理/时间门槛继续保留。

步骤：1核实可复用资产与具体缺口；2实现profile组合并贯通scene/manifest/odom/footprint/托盘/交接/导航；3接回原工作台选择与明确的新场景语义；4定向合同/几何/传感器/前端回归；5冻结有限组合面板，按独立原生UUID与物理评分实际执行；6清理、知识状态与提交推送。根串行共享文档与运行，worker负责指定实现切片。

来源：采用Wiki/ROS2 与 FishBot第19节的激光切片/完整碰撞图分离、编译后完整足迹、坐标参考点与真值隔离经验，以及原生时钟专组经验。不同车的轮距、半径、惯量和托盘不能继续读取FishBot常量；传感器存在不等于真正进入避障控制。实际面板与预算在确认物理接入后追加，不把尚未执行的组合记为支持完成。

有限面板：FishBot/J100 × planar(二维)/lidar3d(二维定位＋16线三维避障)，共4组合；每组合以同一bridge/world完成三批A/A/B，共12完整运输。每任务原360墙秒，每组合1400秒、最终面板5600秒；准备/构建与开发排障另列。实际独占domain137–140/API9107–9110以启动前空域/空端口为准，旧5188保持。开发可显式单批检查，不能算最终三批通过。3D标准点云及Nav2/CollisionMonitor真实订阅另行取证，不把topic存在视为避障消费证明。

配置入口在prepare生成新场景，网页导出组合草稿并显示实际manifest组合；不新建浏览器启动服务或在活动场景热换模型。三批由原workflow唯一派发，网页相应只读。`workflow init --from-scene`把已准备模板转换为新UUID和A/A/B输入，不新增任务执行引擎。纯3D定位、任意厂商雷达校准、其他底盘和新策略训练不在本轮完成条件内。


P8当前接续：保留M两批物理成功与第三批失败；N最低接近速度候选确实减速，但原进度检查触发恢复。O仅将原载货参数事务扩展到原PoseProgressChecker的5mm/.05rad进度分辨率，原期限/最终物理评分保持；原生O先在loaded应用前触360墙秒，未验证参数效果。完成共享仿真窗口协调与独立F1 direct/via后，在资源可用窗口复验，不以低实时因子为由改评分或任务期限。
