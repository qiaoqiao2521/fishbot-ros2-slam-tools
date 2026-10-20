# 实施进度

## 2026-10-20 无人机扩展（本轮已交付）

用户批准在同一工作台增加 `/drone-station`，先航点、再 EGO 静态绕障。原 SO101 默认文档与入口保持；RobotStation 按平台选择动作和独立执行 API。
飞行代码位于独立本地项目 `/home/muqiao/dev/ros2/projects/drone`，没有把 ROS/PX4 依赖加入 Web 构建。
任务 HTTP 层复用原 SO101 生命周期；共用服务器统一分发 WebSocket，MCAP 继续使用原生播放器。

已通过原 SO101 服务 8 项、无人机服务 5 项、前端 Jest 40 项、无人机无运动浏览器 16 项和 SO101 既有无运动 13 项。最终生产构建通过，保留上游两项包体积警告。
网页任务 `08793a65-5ed6-4573-b4ed-a98a47d8d3fc` 完成三航点、高度变化、返航、落地/disarm，Gazebo 峰速 0.8156m/s。复制改目标的新任务 `d0d4f904-bce3-4a6a-aa8c-9746342ae279` 空中刷新零重发，取消后实际落地；原任务快照保留。
MCAP 的 URL 后缀、跨端口资源及 Collada 图片引用已修复。原记录通过原生 seek/播放/暂停/倒退，零控制写请求或 WebSocket，五种官方网格及纹理全 200。浏览器证据在忽略的 `workbench-review-tests/output/drone-replay-final/`、`drone-execution/`、`drone-task-drafts/`。
EGO 执行器通过 CLI 静态障碍和移动障碍的完整返航回合，以及深度中断、暂停恢复和障碍内目标的真实故障落地。网页先后暴露传感输入间隔与规划速度预算问题；原失败保留，执行源使用同 stamp 配对、匹配的 SensorDataQoS 和保守各轴参数，保持 PVA 与原失效阈值。
最终同一网页示例 `5c1ac934-4843-477a-ad84-4539eed8e4ed` 完成三航点、规划返航及落地/disarm，Gazebo 峰速 0.6493m/s、MAVSDK 峰速 0.5579m/s，机体保守净空 0.3079m。根独立检查五段最后一秒真值，最大误差均小于 0.5m；本轮无碰撞。实际输入经导入/保存/刷新保持，只有一次起飞 POST。
常用入口已切至 <http://127.0.0.1:5186/drone-station>，旧 SO101 入口保留。最终 EGO MCAP 从 5187 录制后在 5186 原生 seek/播放/暂停/倒退通过，五种官方网格与纹理全 200，零控制写请求或 WebSocket。SO101 原脚本在 5186 再次 13 项通过，零运动请求。隔离 5187 服务已退出。
最终证据位于 `drone-ego-execution-sensor-qos/`、`drone-replay-ego-5186/` 和 `station-task-drafts-5186/`；旧失败及 5187 回归均独立保留。传感停滞的底层 Fast DDS 原因未完全证明，不把单个通过回合扩大成可靠性保证。范围限本机单架、静态障碍、Gazebo 理想定位；起飞/降落由 PX4 执行，未验起降段避障。
完整状态、故障记录和交付由根串行记录于 `/home/muqiao/文档/ChatGPT/ros2/plans/drone-workbench-20261020/`。Knowledge closeout: already_covered。

## Current

2026-10-18，P1 可运行底座、真实记录与原生回合面板已完成独立验收。隔离分支 `codex/workbench-code-rebuild-20261018` 已推送既有远端，适配提交 `fb4a6622d5df024e7851a92f3351b3f223ef584b` 经 GitHub ref 回读一致。新仿真任务、完整能力迁移与 CY 正式切换仍为 P2–P5。

预览：<http://127.0.0.1:5186/so101>。手机浏览器布局：<http://127.0.0.1:5186/so101-mobile>。服务仅监听本机，按 `apps/fishbot-control-station/WORKBENCH.md` 重启。当前读取历史回合，没有发送机器人动作或启动训练。

## Source and build

- 从 FishBot `325fa260096d421d07035c4a64cb765e5006501b` 建立隔离工作树；原 FishBot 工作区、服务及在途运动规划由原根继续维护。
- 固定 Lichtblick v1.29.1 / `95713edb309d77589b130286642ab149995a5f7b`。导入提交 `0eaa6d9` 的 2,297 个原文件与官方归档逐字节一致；原版权、许可证和测试数据保留。
- Node 22.23.2、Yarn 4.17.0，immutable 安装通过，`yarn.lock` 未改。Corepack 的父目录 ESM 冲突通过独立缓存作用域修复，没有修改全局 Node 配置。
- 原版生产构建 147.562 秒通过；最终含移动视口的构建 168.654 秒通过。均只有两项资源体积警告，不宣称加载性能验收。
- 新面板使用原 Panel、MessagePipeline、seekPlayback。原文件适配仅注册表、默认侧栏、秒显示和 HTML viewport；桌面/手机布局使用原格式。

## Data verification

- 原 SO101 回合：`reviewed-20261014-183003-2405056/full-cycle-20261014-212632-2677556`。转换后 MCAP 为 26,525,186 字节，SHA-256 `73d74dc37a548193ce8fc6109abc421b1a197ce612e164efab83213b4df90d5d`。
- 共 14,976 条消息：3,328 组关节、接触、阶段、物体姿态，以及 1,664 帧原录像。视频帧 j 对应 trace[2*j+1]，首帧物理 0.04 秒，按原 recorder 源码、帧数与 PTS 核准。
- 独立全量读回通过：原输入哈希不变、四条来源绑定、七项报告指标、分块与全数据节 CRC、索引读取和全部数值。姿态往返最大误差 2.11e-15。
- 独立审查曾发现指标、来源绑定和 DataEnd CRC 的检查不足，已补入可重复读回；另有 8 项转换边界、4 项语义/CRC 负例通过。
- EpisodeReview 的 28 项 Jest、定向 ESLint/Biome 和生产构建通过。独立检查 JPEG 全帧流与原视频重新转码一致。
- MCAP、视频、报告、日志、依赖、构建和浏览器截图均被 Git 忽略。公开源码不含本地 manifest 或原报告路径数据。

## Browser acceptance

在独立 Chrome 153.0.8010.36 / headless 软件 ANGLE 下运行，未使用日常浏览器资料。以下报告位于 `apps/fishbot-control-station/workbench-review-tests/output/`。

- `baseline-a`：原版 5 项通过，只证明原生读取和播放。
- `full-c`：最终桌面 11 项通过，203 个请求。首帧即显示 RGB；图像、物体 3D、双指力、关节曲线和回合面板已读取真实数据。前后 seek、播放暂停、分割面板、保存后不带 layoutUrl 重载、移除后保存重载均通过。
- `mobile-b`：最终手机浏览器仿真 9 项通过，57 个请求；实际 CSS 和 visual viewport 均为 390×844。首帧、报告、播放暂停、滚动及点击阶段到 64.44 秒通过。
- 两轮 pageErrors、consoleErrors、写请求、外站请求和 WebSocket 均为 0；输入资产起止不变。
- 根独立查看起点、持物 14.38 秒、落定 64.44 秒和手机截图。三维方块完整可见，桌面三处离画布边界至少 62 像素；录像与物体变化、阶段一致。
- 最终报告摘要：full-c `7cc0895ca5b1f6adb6ce2297002c190ffefd4f64881e52135a640d72b335fa97`；mobile-b `1a151fd5eee4e07aad783b0d0498bd26bf9cf48ea458da36669eb6138f20618d`。

保留失败证据：full-a 行为通过但坐标轴过大、中心字段错误；full-b 起始物体贴边。调整原相机配置后才通过 full-c。mobile-a 实际 CSS 宽 980 像素，被独立审计否决；补原生 viewport 后才通过 mobile-b。手机底部次要同步/速度选项仍有裁切，已测核心操作可用，不宣称完整手机编辑器。

## Remaining and ownership

- 历史回放通过不等于新的抓放成功。当前 3D 只有记录中的物体姿态，全臂看同步录像；全臂 FK、跨回合换源、实时连接和性能未验收。
- P2/P3 的入口差异见 findings：FishBot 有 runtime 和协同控制合同；独立 SO101 full_cycle 缺已核实的 HTTP 启动、协作取消及查询适配。根 Codex 与原模块 owner 接续，保留原任务账本与物理评分。
- 原 FishBot 根仍在运动路径验收。隔离分支不合入其 dirty main；待其可交付基线后串行整合。保留原未提交改动，不替代其测试结论。
- CY 未部署，旧站点未切换，手机真机与长期性能留后续。

## Knowledge closeout

`already_covered`：CapMesh PIT-004 已覆盖依赖与发布周期隔离；本轮源码、时序、视口和接口边界记录在项目计划，没有新增通用平台或全局规则。

## 2026-10-20 场景与程序编辑接续

用户要求继续修改项目，尽可能复用 CY 成熟产品成果。沿已有 Lichtblick 底座新增 RobotStation 原生面板，采用 RoboDK 对象树、坐标系归属、目标引用和指令列表设计。布局、保存、播放器和历史回放继续使用上游实现。

本轮编辑范围：平移坐标系、对象/目标/障碍、世界位置保持的重挂父节点、指令排序、撤销重做、人可编辑 JSON 导入导出。坏条目警告并局部跳过，无内容哈希锁、前序任务锁或每日限额。

新入口 `/so101-station`；窄屏 `/so101-station-mobile`。俯视虚线仅是程序顺序，右侧录像仍是历史回合。未定义旋转坐标系、工具 TCP、碰撞规划或执行适配，不能将草稿标为可执行任务。P2 部分实施，P3 未完成。

验证：10 项局部单元测试、生产构建和定向 ESLint 通过；桌面/390px 共 11 项浏览器交互检查通过，编辑/撤销重做/步骤排序/导出/刷新后的完整 JSON 一致/手工导入/坏 JSON 保留草稿/手机编辑均覆盖，pageerror 与运动写请求为 0。最终截图与结果位于被忽略的 `workbench-review-tests/output/station-editor/`。构建保留上游两项包体积警告，不宣称加载性能通过。接续 owner：根 Codex。独立 SO101 full_cycle 仍要求已有 motion-plan/preflight，不能直接消费任意新坐标；需在 SO101 侧接入重新规划及原任务生命周期。

Knowledge closeout：already_covered。继续采用 CapMesh PIT-004 的 Web/机器人依赖隔离，不新增通用知识规则。

本轮修复：上游 `isLayoutEqual` 忽略基线配置中不存在的新键。最初布局只有面板标题，导致 `station` 内容无法保存。两个入口布局现包含完整初始 station，面板默认配置也包含 station；保存通过原 `updateLayout` 与 `overwriteLayout`。移除当前地址的 layoutUrl 后刷新，不再重新导入初始模板。相关原生比较回归有 2 个测试。失败试验未误记为通过。

## 2026-10-20 P3 规划执行接入（进行中）

用户授权接已有规划执行器。复用 SO101 `run_visual_grasp.run_physical_episode` 的实际控制器和原评分，新增薄 CLI 适配；预览服务仅提供本机任务提交、原 ID 查询、协作取消和结果读取。UI 明确点击才提交，刷新只恢复原任务。每回合独立产物目录，可并行，不新增每日限额或内容哈希门锁。

首版边界：固定完整抓放程序，方块受支持的小范围 XY 修改、已有/新增障碍；无法映射的程序/坐标必须明确反馈。通用程序执行器和真机不在本轮。根负责 HTTP/整合；内部 worker 分别负责原生执行适配和面板调用。验收至少覆盖新完整回合、协作取消、刷新不重发和输入拒绝。


### P3 固定模板验收完成

- SO101 新增 station_executor/test_station_executor，原 run_physical_episode 增加可选场景/进度/取消/视频/控制器参数，默认历史路径保持。复用已核准 floor_yaw 与28mm释放高度。canonical原现场保留，发布同步到既有SO101交付分支。
- Node薄适配提供runtime、任务提交/原ID查询/列表/协作取消与报告/录像Range读取。每任务独立快照与产物目录，可并行；同ID只启动一次。面板重载/刷新只GET，不POST。
- UI明确显示本次任务和历史回放；终态、原物理报告和本次录像独立显示。技术报告默认折叠。新建布局初始化executionTaskId，原布局也可从任务目录恢复最近任务。
- 18项面板/transport、3项Node进程合同、SO101 35项定向测试与生产构建、定向ESLint通过。包体积两警告保留，未宣称页面加载性能或50Hz。
- 真实浏览器在隔离5187通过新抓放、运行中刷新原ID/零重发、原报告、视频Range读回、再次启动和取消。成功任务 `fd3e7408-b4da-4d44-a186-ce8b90d61447`：74.76sim/50.219wall，grasp_success/place_success/controller_done均true，safety_stop=false，静稳7.52s；release审计通过、脱离后接触峰值0。新录像468帧，640×480/6.25fps；独立浏览器实际播放和seek通过，readyState=4、error=null。
- 网页取消任务 `a4604f07-7251-489e-9f40-c8e5d745b2e6`：4.16sim，cancelled、passed=false，无safety_stop，26帧部分录像完整。总2次显式启动+1次取消POST；刷新无重复POST。pageErrors=0。
- CLI另验修改方块X=.245和新增障碍，实际初态及XML确认消费，在25.30sim协作取消。首CLI默认旧释放高度触发再次接触，失败保留；未修改原安全判据。
- 本机5186已换为新服务，SO101_ROOT指向已同步的独立交付工作树；原任务成功/取消与报告经5186读回。CY未部署，训练/实机/20+20未启动，任意目标或自定义程序仍不支持。

证据：忽略的 `workbench-review-tests/output/station-execution/result.json`、截图与 `workbench-tools/output/station-tasks/<id>/`。浏览器测试是新物理执行，右侧共享时间轴仍属历史回放，未声明新的实时三维联动。根Codex负责后续更多任务/参数和CY部署；本轮固定模板接入完成。

Knowledge closeout：already_covered。沿用既有任务ID恢复与CapMesh PIT-004依赖隔离，接口细节留项目文档。

执行器已提交推送既有 SO101 分支 `codex/colab-twin-20261001`，提交 `c33a4df`。本工作台通过 `SO101_ROOT` 指向该交付工作树。新增执行UI后，原编辑器11项浏览器验收也通过；零运动写请求，旧编辑/保存/导入行为保持。

## 2026-10-20 当前任务实时三维（已验收）

用户授权将新任务和编辑草稿接入成熟3D底座。复用现有 @foxglove/ws-protocol、ws 和 Lichtblick 原生3D/数据源，沿用原MuJoCo模型/FK，不新增渲染器。SO101 worker输出世界空间的完整机械臂、夹爪、物体及场景；Node只转标准SceneUpdate和同源STL。预览与任务画面显式切换，草稿编辑不得覆盖运行状态；取消/终态强制保留最后物理姿态。原控制与评分保持。根负责WS/整合，内部worker分别负责几何和UI/布局。

验收：改物体/障碍的预览确实更新，完整新回合的机械臂/物体同步，取消/终态姿态保持，任务隔离，原编辑和执行接口无回归。后续由根记录实际结果，不能把消息数或页面启动当三维验收。


### 实际结果与交付范围

- Web生产构建通过，保留上游两个包体积警告；23项RobotStation Jest、8项Node进程/原生协议测试、SO10119项几何/执行适配测试、定向ESLint及语法检查通过。原编辑器11项浏览器交互也通过，预览POST允许，但运动提交为0。
- 完整浏览器新任务`e6ddc0ce-682c-4923-aebb-1990b3840784`：74.74sim/106.662wall，真实夹起、放稳、脱离和回位通过，无安全停止；静稳7.52s、scene_seq=838、scene_final=true。最终物块中心约(0.238631,0.139046,0.009961)m，实际到达蓝盘。
- 另一网页任务`5f390fa1-ad63-433f-ab4d-32cf7d9fe924`：5.12sim取消，scene_seq=36、scene_final=true。Web当前源与原任务末态几何逐值一致；切到草稿再切回可恢复同一末态，未回跳到默认姿态。
- 独立浏览器覆盖：修改方块与附加障碍确实更新三维且零运动；完整13STL加载、17实例；运行中编辑隔离、刷新同ID零重发、实际模型运动、新录像Range、终态保持、390px完整模型和无横向溢出。pageerror=0、模型请求失败=0。首次手机截图在模型未加载完时拍摄，未作为完整模型验收；等待13个资源后重新目视确认。
- 复核补齐可选显示模块导入降级：导入移至scene callback内，由原warning catch处理；额外回归证实缺显示模块仍保留原定位拒绝结果，没有把显示异常覆盖为物理失败。正常模块路径不改物理控制。
- 证据：忽略的`workbench-review-tests/output/station-live/result.json`及initial/running/success/cancelled/mobile截图；真实运行数据在`workbench-tools/output/station-tasks/<id>/`。显示约10Hz，不声称新50Hz、长期性能、CY或实机通过。

Knowledge closeout：already_covered。沿用PIT-004依赖隔离和现有任务身份/分层验收知识；模型变换、UI加载时机和本轮证据留本项目。

## 2026-10-20 可复制、可改目标任务（已验收；开发过程保留）

已定位场景/规划/评分三处目标一致性，复用既有Station JSON、saveConfig和任务生命周期。控制worker已提供place_xy默认兼容接口与83项局部通过结果，根待独立复核和实际物理验收；UI/评分worker并行实施。未将局部绿灯记为新目标抓放成功。


新目标CLI首测(.22,.17)在64.40sim失败：真实物体已落新蓝盘，轨迹in_place_tray/place_floor_contact均true，但release后脱离IK残差0.001792被原门拒绝，整轮不得计成功。失败完整保留于SO101 delivery忽略的output/station-task-goals-20261020/goal-a，控制owner继续定位目标变化后的脱离路径；根未放宽阈值或回退旧中心。目标报告字段也发现会被monitor状态覆盖，已移入reset_record随原报告收尾输出。


冻结浏览器第一轮默认任务58d6cdbb成功74.80sim；复制保存/刷新与原快照隔离检查均通过。但副本目标(.20,.20)在32.14sim搬运IK拒绝（residual .001608），任务a2601d76保持失败。控制owner使用保存transport snapshot区分任务不可达与固定60mm中转路线不可达，未改IK/碰撞阈值，根暂停新的物理回合但继续UI与文档工作。首次浏览器结果原样保留output/station-task-goals-before-hover-repair，不被后续成功覆盖。


### 数据驱动目标最终验收

- 生产构建通过（仍两项上游包体积警告）；26项面板Jest、定向ESLint、91项SO101定向测试及81 subtest通过。新目标/旧目标拒绝、全外廓与原58mm边界、实际/规划XML与预览一致、台面外拒绝、异步目标、候选碰撞/取消/全失败不部分提交、脱离原采样与异常身份均覆盖。
- 无运动浏览器13项通过：深复制、蓝盘五片随XY整体平移、原尺寸、保存/导出/刷新完整JSON、旧结果不恢复、JSON再导入、13STL加载和真实390×844无横向溢出；motionPosts=0、pageerror=0。手机按钮显示与布局已验，手机触控复制未另行计通过。最初手机截图1600px和后续并行任务状态自然变化造成的测试假设失败均未计通过；脚本修复为真实viewport与本页面零运动写请求后重验。
- 冻结浏览器12项完整通过：默认任务`0a7fa8c1-ef91-48b4-a60d-bccffe0e6e05`74.80sim/100.940wall；同页复制改为(.20,.20)、保存刷新，新ID`bc8ada28-efd1-4f8a-bdf3-45fe7014da24`77.06sim/110.560wall成功。两轮之间未改Python；原快照未变。B物块最终(0.198959,0.198737,0.009961)m，位于新盘且在旧盘验收区域之外；落稳约7.50s、无安全停止、控制器完成，随后可再次复制且零额外任务POST。
- 首次A失败原输入(.22,.17)在最终源码CLI重验75.16sim/63.479wall通过抓放、脱离和回位。默认仍60mm中转/37mm脱离；B正式54mm中转/25.615mm脱离。未知RuntimeError降级缺口已独立复现、分类修复并回归；最后源码对B保存快照离线重演150/150采样、separation_end逐字段一致，无物理步；A为最后源码的完整回合。
- 初次A64.40sim脱离失败、初次B32.14sim搬运失败和原输入/报告均保留；没有改IK精度、限位、1mm/0.2mm或释放评分，也没有退回旧目标。通用技能自由编排、其他物体/台面高度、CY、真机、20+20与完整50Hz继续未验。

证据：忽略的`output/station-task-goals/`、`station-task-goals-before-hover-repair/`、`station-task-drafts/`和真实task目录；SO101的`output/station-task-goals-20261020/`保留A及离线重演。两实现分支由根串行提交推送，研究仓单独记录。Knowledge closeout：already_covered，沿用Wiki按当前任务选择验收依据、ROS2与FishBot第20节的分层物理验收和PIT-004；本次目标/路径参数留项目，不写个人记忆。
