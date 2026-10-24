# 实施进度

## 2026-10-24 M2提前交接对照

- Current：原三个拒绝画像＋两PV零A/J控制，在预定33.248/33.388/33.428s共15组，8过7拒。提前180ms只解除事后Jy画像拒绝，两个外向Ay仍拒；本族结果不能当ICS或飞行成功率。
- Done：drone-stop-qualification.py新增earlier-handoff模式，复用相同geometry.search/MINCO/硬审计。PV来自同一过去配对的逐时刻积分或精确源时刻事后对照，原A/J画像保持；输出初末合同、峰段号/时刻/向量和recorder/FSM身份。20项资格测试通过（8项新增），122项独立原CDR/录制时钟/多项式读回通过，图已目视核对。原CLI额外回归仍10组/7过/2时效集，regression报告独立保存、不覆盖原基准。
- 结果：事后Jy峰.934342/.982959/1.027612；两个最早外向Ay范数1.028683/1.024262，Y分量−1.027311/−1.022883单轴已超1，不仅是XY预算挤占。原硬界、2mm内部规划目标和搜索域不变；没有新动态或执行资格。
- 输入/审查：源V33.208/33.228，recorder upper33.212/33.232；33.388仅原FSM定位，不冒称33.248已消费。oracle改值不影响预测，缺/冲突分支隔离；旧曲线改标签不算新解。agent-link agy因--print启动参数错位失败，未计审查；内置只读审查已核，previous晚到/缺失负例落实。未联系其他已有聊天。
- 产物与边界：原忽略目录下stop-earlier-handoff-comparison.json、stop-earlier-handoff-readback.json、stop-earlier-handoff-comparison.png及首轮probe保留。方法和CLI在docs/DRONE_RECORDED_STATE.md末节。只改离线工具/测试/文档，无Web改动、训练、ROS节点、仿真、控制或飞行；drone c866441冻结。SO101接续搬运八文件继续原位保留，接续入口沿前节，未混入本提交。
- Next/owner：根Codex核当前Y单轴C3生成族的几何/末端合同与既有分段自由度，不继续盲扫同类时刻，不预设存在合法备份。完整M2仍缺真实A/J、时间有效自由图、终端/截止及跟踪/采用，M3不解冻、动态闭环未过，goal active。knowledge_status=already_covered，沿用Wiki/ROS2与FishBot§20、原生时钟与CapMesh PIT-004；新数值留项目，未写memory。

## 2026-10-24 M2非零边界与刹停时效离线资格

- Current：有限A/J敏感性与时效分支可复验；10组中7组过原连续界、3组有界重解仍A拒绝。不是鲁棒通过率；原硬界和drone c866441冻结保持，M2部分完成、M3未启动、goal active。
- Done：新drone-stop-qualification.py复用原MINCO/连续审计/Replay。原PV保持，过去A按父行的可用FSM证据重算后作为保持假设，缺失只跳该项；Replay接完整C3刹停不编造已执行前缀，并核mode及末端VAJ为0。12新＋8回放＋11几何＋31状态，共62项通过；81项独立源、PVAJ、时长/选择结果读回通过，科学图已目视核对。
- 时效：两条原零假设候选各12个理想PVA/声明静态图情景。实际5秒＋终端.5秒，使33.428s接纳需覆盖到38.928s；仅新鲜、仅曲线覆盖、未知A、旧头晚交、A漂移、终点占据、时钟不符均不给参考。暂停sim不因wall10秒推进；实际6秒曲线不会被metadata5秒缩短覆盖。有限终端窗口后续仍过期，不冒称不变集或真实保护动作。
- Issues：3组重解A峰1.035868/1.128389/1.027612m/s²；当前搜索族不能解，不证明全部轨迹无解或ICS。实测A/J、当前已知自由体积、未来动态图、终端安全区域、实时截止和采用/跟踪仍未验证。protect只表示离线参考撤销，无落地或受控制动证明；原748失败保持。
- 审查：agent-link CBC返回done空正文，未计有效审查；内置只读审查完成，来源可用时刻、局部坏行隔离、完整刹停末端合同已修且补负例。未联系已有聊天。期间SO101已交付92c2962/197e343，保留其变更，本无人机提交只含三个工具/测试、方法文档和本计划。
- 进行中改动保留：收尾复核又出现SO101“夹起后等待/原任务接续搬运”八文件：so101-runtime.cjs、task-runtime.cjs、runtime.test.cjs及RobotStation的execution.ts/.test.ts、index.tsx、station.ts/.test.ts。差异已定向读回为resume-carry能力/原ID标记及文档意图保留，不是本轮已验收成果；当前仍在改，不混入本提交。接续整合owner=根Codex，最短入口为runtime.test.cjs、execution.test.ts、station.test.ts及原站点无运动QA；物理消费与超时结果须回SO101实施计划，不能凭按钮或HTTP标记宣称搬运完成。其余新增文件以后续实时status为准。
- 产物：原忽略目录workbench-tools/output/drone-committed/748f910e-f0f8-4ecf-b2d5-22b7b15d57e6/下stop-boundary-temporal-qualification.json、stop-qualification-readback-checks.json、stop-boundary-sensitivity.png。命令及十组表见docs/DRONE_RECORDED_STATE.md末节。无Web改动，不重复构建/浏览器验收；无训练、ROS节点、仿真或控制写。
- Next：根Codex对三组拒绝输入做有界提前交接对照，保留同类假设、原硬界与原PV来源；先区分时刻/几何与当前生成族的限制，不盲加margin或解冻。knowledge_status=already_covered，沿用Wiki/ROS2与FishBot§20、原生时钟与CapMesh PIT-004；新数值留项目，未写memory。

## 2026-10-24 SO101 原物理抓取证据展示

- Current：RobotStation读取原status／report.skill_evidence，单列“曾确认持续持物”，不由close/hold阶段推断成功、不覆盖task终态。旧记录没有新证据就不补造；无人机显示路径保持。
- Done：12项相关execution数据测试、最终生产构建通过（原2项包体警告）；10项桌面／390px无运动浏览器通过，写请求0、页面异常0。成功／取消回放显示27.68s，历史失物28.80s，失败／取消与原false结果保持。证据和截图在忽略目录workbench-review-tests/output/grasp-evidence/；scope明确为真实记录回放的HTTP fixture，未启动新物理。
- 原物理独立验收：SO101固定b21b1d9的3d3cefa8…新原完整抓放pass（77.90sim），49f2d252…运行中取消原fail/exit1保留。两例原monitor重放与skill_evidence完全一致，唯一事件index1383/27.68s；取消观察1511/1512行，taskcancelled／worker清理确认。源码与事实回源SO101 plans/workcell-productization-20261024/m2-grasp-evidence-results.md；本次网页HTTP fixture QA不替代该原物理。
- Remaining：六技能、同世界恢复与卸货未因增加展示而完成；完整50Hz仍未过（新完整159拍>20ms）。
- Issues：此前Drone源码／测试／说明已由原owner交付至275f6bf，当前按实时diff只整合本轮4个前端／QA文件及文档，不覆盖其他成果。根继续保留共享树在途内容。
- 末次交接：Drone原owner又在修改drone-committed-replay.py（7行新增）并新增drone-stop-qualification.py，用于离线停止边界假设与时效核准，尚未执行接纳。保留进行中源码，不混入SO101交付；接续owner=无人机当前根Codex，最短验收入口为该CLI的geometry-report/stopping-report与原native硬审计，完成后再核原记录与测试。共享树不宣称干净。
- Next：物理证据与技能生命周期继续在SO101主计划推进。Knowledge=already_covered，沿用Wiki《ROS2 与FishBot》§20；未写共享知识或memory。

## 2026-10-24 M2停止位置与时间联合重解

- 当前：新drone-stop-geometry.py复用MINCO stop_positions，SLSQP仅外部有界四维[Tx,Ty,Tz,dy]搜索。初始PVA/J和原target来源保持，不做生成后时间拉伸；终点三联同步，最终原连续审计独立执行。
- 结果：同一33.428s过去V差分预测PV/事后PV，在原A=J=0假设下均过原连续界，A峰.898199/.990466，XYZ停止约5/.977/.201和5/.930/.176s。Y最高2.028m，规划向内2mm、原硬界2.03m不变。缓存旧合格保持、恒速模型必要拒绝不搜索；事后PV仅明确反事实生成输入，不当在线证据。
- 验证：11新＋31状态/预测＋8提交回放，共50项通过；独立源报告/多项式读回32项通过，科学对比图已目视核验。独立审查两项来源合同缺口已修并补负例；Qoder超时且句柄缺失后用内置只读审查，无旧聊天协作。首轮测试缺corridor夹具失败，修正后重跑，不计首轮通过。
- 边界：J峰11.681/9.787m/s³尚无J硬界，约.416/.430wall只是离线观察值；5秒刹停没有时间有效地图、终端区域或实测跟踪证书。next=核非零A/J假设与5秒自由体积/终端/截止条件，owner=根Codex。drone c866441清洁冻结，无训练/ROS节点/飞行/控制；M2部分完成、M3未解冻、goal active。
- 产物：原忽略的workbench-tools/output/drone-committed/748f910e-f0f8-4ecf-b2d5-22b7b15d57e6/下stop-position-time-comparison.json、stop-geometry-readback-checks.json、stop-geometry-comparison.png。命令和完整边界见docs/DRONE_RECORDED_STATE.md末节。
- 共享树：本轮期间SO101配方提交7ac8d86/f29a85a已出现，HEAD/origin一致，保留其已提交文档，不混入本无人机提交。当前Station在途改为execution.ts、execution.test.ts、index.tsx三文件，内容是observation_only物理持物证据标签及其负例；已只读理解，继续原位保留，owner=当前SO101根/根Codex，最短接续为execution.test.ts和原站点无运动检查，不能以标签证据宣称回合成功。
- knowledge_status=already_covered；沿用参考/实际/采用、输入身份和时钟边界经验，新曲线数值留项目，未写memory。

## 2026-10-24 SO101 可编辑配方交换

- 当前：原RobotStation增加“导出工位配方”，原JSON导入可载入station-recipe v1；保留Station、execution、来源及未知可选元数据。导入不执行，旧任务／历史成功不继承；活任务及文件读取竞态保留原ID与取消入口。
- 已验：74项相关Jest、最终webpack生产构建通过（2项原包体警告）；18项实际浏览器检查通过，含保存刷新／复制撤销／390px、单位／旋转／动态／平台／负时长拒绝、异步文件读取竞态。页面异常0、真实任务写请求0；竞态1次POST为隔离模拟，不到后端。证据在忽略目录workbench-review-tests/output/recipe-workflow/。
- 实际运行：浏览器new-recipe.json与首轮副本及云输入逐字节相同，交SO101固定fd20512原evaluate_station，10f9c86e…原pass（77.96sim/55.544episode-wall），真实抓放／释放／脱离／回位、244、自由物体与双worker清理通过。另0181e8f1…运输worker运行中真实取消，原fail/exit1保持、taskcancelled、joined/closed及无活线程确认；不是第二次抓放成功。详见SO101 plans/workcell-productization-20261024/m4-recipe-results.md。
- 发现与修正：配方负时长原被普通草稿容错修成1；仅配方路径改为明确拒绝，自定义执行语义不静默替换，普通Station容错保持。独立审查与最终浏览器负例均覆盖。
- 边界：米制平移、SO101固定尺寸静态几何、独立episode；不是六技能恢复或FishBot同世界卸货，完整50Hz仍未过。本轮由根Codex串行整合，其他Drone在途成果已由原owner提交7fc5695，无覆盖／混入；Mint未改。
- 交付末次回读：Drone原owner继续出现drone-recorded-tracking.py（10增3删）及新drone-stop-geometry.py；后者为MINCO离线停止位置／时间比较，源码仍在变化，未按SO101验收或代交。现场保留；接续owner=无人机当前根Codex，最短入口为该CLI与本计划必要刹停节，结束后再独立审查其原始CDR／硬审计结果。本轮仅交付已冻结的RobotStation配方，不宣称共享树干净。
- Next：SO101主计划继续M2原物理技能证据及安全恢复，连续卸货另接FishBot单一Physics。Knowledge=already_covered，沿用Wiki《ROS2 与FishBot》§20；本轮项目事实不写共享知识或memory。

## 2026-10-24 M2必要刹停条件与旧曲线适用域

- 当前：同一drone-recorded-tracking.py新增可选stopping-fixture/native，复用原CDR、MINCO和连续审计。7 FSM＋1 reanchor、32相关PV比较，未来PV只评分；手工box、假定A≤1、未知实测A/J均明示。
- 已核：原33.228s缓存的C3刹停早已合格，本轮复验A峰.990634。33.388/33.428s记录PV未被逐面必要界排除，但固定3.5/1/.4s候选Y越界；8个原生审计2过/6走廊拒绝，两个通过是同一缓存重复，不算两次独立成功。恒速预测的Z拒绝不冒充实际ICS。
- 新限制：33.428s对称终点族y_end=y+vy*T/2、A=J=0下，仅Y轴就要求T≥.832136301s且T≤.805914093s。最低标量A约1.032537225；不能仅调T，也不能推成所有刹停无解。
- 验证：31状态/预测/刹停＋8提交轨迹，共39项通过；独立原CDR/多项式读回19项通过。Qoder超时且句柄缺失，内置只读审查完成。读回脚本首次NumPy bool_序列化失败，修正后重跑，首次不计。
- 产物：忽略目录workbench-tools/output/drone-committed/748f910e-f0f8-4ecf-b2d5-22b7b15d57e6/的stopping-viability-evaluation.json和stopping-readback-checks.json；命令、完整表格、条件和后续见docs/DRONE_RECORDED_STATE.md新增节。
- 接续owner=根Codex：先复用已有stop_positions核停止位置自由度/边界重解，再核时间有效几何。完整A/J、当前已知地图、跟踪包络、终端区域均未获资格。drone c866441清洁冻结，无训练/ROS节点/飞行/控制，M2部分完成、M3未解冻，goal active。
- 在途保护：Station的index.tsx、station.ts、station.test.ts、stationRecipe.ts、stationRecipe.test.ts及workbench-review-tests/recipe-workflow.cjs共6文件仍保留，不混无人机提交。根先回读最新SO101产品化进度/diff，再运行既有stationRecipe/station定向测试和recipe-workflow隔离检查；未得到交付验收前不声称可合并，不联系旧聊天。
- knowledge_status=already_covered；沿用既有参考/实际/采用及时间边界经验，数值/曲线族限制留项目，未写memory。

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


## 2026-10-24 无人机历史诊断交付

- 入口：常用5186的`/drone-diagnostics?taskId=748f910e-f0f8-4ecf-b2d5-22b7b15d57e6`；手机追加`&mobile=1`。5187完成隔离验收后归还。
- 复用原播放器、三维、X500网格与任务身份。659个源仿真时刻的派生MCAP包含scene/telemetry/diagnostics三通道；原日志、MCAP和报告未改写。
- 11项Node局部检查通过，含旧MCAP、双WebSocket共存及缺真值/损坏行/报告ID不符/只读HTTP/反向读取。定向ESLint与生产构建通过，保留两项上游包体积警告；初次lint问题已修复。
- 实际历史记录桌面1440×1000及手机390×844检查9项通过：原ID与终态、故障跳转、前后seek、播放暂停、无时刻事件禁用、缺失通道说明、无横向溢出。控制写请求0、实时WebSocket0、pageerror0。
- 截图和result.json保存在忽略的workbench-review-tests/output/drone-diagnostics-release；根已目视核对。曲线和原报告的全频评分分列，回放不构成新飞行验收。
- 当前环境的SO101模型导出Python路径不存在，服务启动给出WARNING。本片不使用它；仅双WebSocket合同单测通过，没有宣称SO101完整三维/物理回归。
- 未改drone飞行源码、未启动PX4/Gazebo、未训练；动态闭环仍失败，在线备份、精确拒绝绝对区间和全帧感知延迟链仍待补齐。
- Knowledge closeout: already_covered，沿用Wiki/ROS2与FishBot§20及源时钟/回执分层经验。事实留本计划；未修改共享知识或memory。owner=本对话Codex。


## 2026-10-24 N0/N1选型与只读稀疏观测交付

- N0选择EGO＋PX4现有执行/历史基线，MINCO S4NU仅离线候选；完整GCOPTER、稀疏网络和NavRL未接入。来源、许可、接口及差异见[稀疏观测](../../docs/DRONE_SPARSE_OBSERVATIONS.md)。
- N1从原748深度包抽取1329帧/3372束（前681×4、下648×1）；965hit、2407no_return。源像素字节、斜距/光学方向、同源理想Gazebo光学位姿、分离时钟和可用包络保留。0未对齐/0重复/单时钟回合；不称四向ToF、真实VIO或稀疏控制。
- 独立原CDR审计3372像素/1329位姿通过：斜距误差≤1.78e-15m、世界端点≤7.11e-15m。56帧可用时已过期，全部不生成新鲜射线；前/下视最长源间隔1.124/.892s。数据缺口不能直接当注入丢帧率或准确传输延迟。
- 6项Python及14项Node局部检查、定向ESLint、最终生产构建通过；仍两项上游包体积警告。合成细柱、大小端/行填充、光学旋转、无回波/无效、时钟reset、未来/过期及旧诊断/双WS均覆盖，没有重跑全部机器人实验。
- 5187隔离、常用5186最终各13项浏览器行为检查通过（桌面1440×1000、手机390×844）；原ID/失败报告、射线与表格、过期清除、故障seek/后退/播放暂停均通过。writes=0、live websockets=0、pageerror=0。根已目视核对两端截图；手机使用原生2px标注线解决世界尺寸线宽的子像素不可见。
- 常用入口：`http://127.0.0.1:5186/drone-diagnostics?taskId=748f910e-f0f8-4ecf-b2d5-22b7b15d57e6`；手机追加`&mobile=1`。原生MCAP保留原659个位姿时刻，完整源帧在独立JSON；缺导出时只降级本片，不影响原任务回放。
- 证据：忽略的`workbench-tools/output/drone-diagnostics/<id>/sparse-observations.json`和`sparse-audit.json`；页面QA在`workbench-review-tests/output/drone-sparse-release/`及隔离`drone-sparse-acceptance-v5/`。早期审计/截图检查失败保留：整数ns修复审计浮点假失败；颜色背景误判和手机线宽失败未计通过。
- 复验：先按文档离线抽取/独立审计，再执行`STATION_TEST_URL=http://127.0.0.1:5186 DRONE_SPARSE_EXPECTED=1 DRONE_DIAGNOSTIC_ID=748f910e-f0f8-4ecf-b2d5-22b7b15d57e6 node apps/fishbot-control-station/workbench-review-tests/drone-diagnostics-browser.cjs`。不启动ROS节点、仿真或飞行。
- 内置只读复核未发现核心P1/P2问题，.25s标签/射线边界差异已统一并局部复验；agent-link工具未加载，已如实告知，未联系其他已有对话。原SO101模型Python路径WARNING保持，未宣称SO101实际三维/物理回归。
- drone始终c866441且清洁；未改算法、未启动PX4/Gazebo、未训练。动态闭环仍失败、在线备份未接入。下一切片为N2轨迹接口旁路资格，不能把本片当控制成功。owner=本对话Codex。
- Knowledge closeout: already_covered。沿用任务身份/回放、原生时钟与PIT-004；数值与兼容性发现留项目，未改共享知识或个人memory。


## 2026-10-24 N2精确分段接口交付

- 离线新增drone-trajectory-primitives.py，复用原audit_retiming.curve、SciPy PPoly、audit_minco证书，不新增求解器、传感器或控制owner。8条记录在收到相位起取0.8s，共23段；三次多项式高阶补零复用原3×6容器。原首尾PVA/J、绝对sim时间和空身份保留。
- 8窗conversion通过、8窗V/A/Z证书clear（原离线候选1.8m/s、1m/s²、2.2m）；PVA拼接误差≤1.48e-15。最大J跳变2.268873m/s³原样保留，只声称C2。occupancy=unverified，execution_admission=not_performed。不是新飞行、动态通过或在线MINCO接管。
- 两个局部Python检查通过：段内相位、初态PVA/J、A超界拒绝、跨节点PVA/J、常量轴和空身份。独立只读审查核对相位/Taylor/补零/身份/资格，无核心阻断；确认.8s为本次值而非CLI硬上限。没有改UI、服务或运行依赖，不重复Web构建和浏览器检查。
- 忽略产物：workbench-tools/output/drone-primitives/748f910e-f0f8-4ecf-b2d5-22b7b15d57e6/exact-windows.json。初次constant-axis-error报告保留（当时仅7窗），修复后8窗warnings为空。原记录、drone c866441和5186只读页面保持。
- [方法、结果表与命令](../../docs/DRONE_TRAJECTORY_PRIMITIVES.md)为最短接续入口；N2仅精确分段资格，单段压缩/教师/模型比较未做。后续选定实际候选再接旁路，不自动训练、启动飞行或解冻。owner=本对话Codex。
- Knowledge closeout: already_covered。采用Wiki/ROS2与FishBot原生源时间、参考/实际分层及既有连续审计；数值、C2合同与代码适配留项目，不写memory。

## 2026-10-24 — SO101 工作区开发样例接入中

根Codex沿SO101 `plans/workcell-productization-20261024/` 接续。RobotStation新增两样例按钮与显式execution往返；原task-runtime/UUID/取消/scene/录像保持。默认±10mm不变，新声明域不代表连续物理已验，原失败和历史结果不继承到草稿。

数据层33项、任务服务3项通过；生产构建通过，仅原两项包体积警告。桌面／390px九项浏览器检查通过，零tasks写请求／pageerror；真实导出fixture经SO101准入检查通过。根查看两屏截图。5186以交付SO101_ROOT及planning-venv显式恢复，已有5187别人的服务未动。新网页完整物理待验，不使用此前开发CLI4/4替代。

本轮只提交RobotStation、so101-runtime、样例浏览器检查和本记录/说明。DroneDiagnostics/drone-diagnostics/drone-candidates仍由原owner在途，保留不纳入本次提交；不停止它们的服务或任务。主FishBot dirty main未改。Knowledge=already_covered，项目状态回源SO101主计划。


## 2026-10-24 N3组件对照/N4历史候选交付

- 原生axis_stop/S4NU接N2参考前缀，固定停止时间3.5/1/.4；7条生成、4数学过、3A拒绝、1无任务身份未评分。切点PVAJ最大误差约2.30e-16，尾内J连接约4.77e-13，完整原前缀仍C2。动态占据/终端区域未知、未采用执行，保原V1.8/A1/Z2.2。
- 新增离线drone-stop-candidates.py、只读drone-candidates.cjs和原生面板子节；/drone/candidates随原MCAP时间，紫候选/红拒绝与原报告分列，父曲线替换后不串用。未写飞控或另建播放器。
- 3项原生Python检查＋17项Node定向检查、定向ESLint和生产构建通过（仍2项上游包体积警告）。可选null/坏行降级、缺原生程序、真实非零参考J、保原PVA/A拒绝和旧接口/双WS均覆盖。初始lint空值表达式已修复。
- 隔离5187和常用5186最终各19项浏览器检查通过：#7红线/1.082 A拒绝、#6数学过/占据未知、#8无身份/旧尾清除、原稀疏/后退seek/原报告回归；桌面及390px，writes=0、live WS=0、pageerror=0。根目视核对正负候选、原父替换及手机。
- QA：忽略的workbench-review-tests/output/drone-candidates-release/（含candidate-panel、math-pass、parent-replaced截图）；首轮toolbar颜色误判在drone-candidates-acceptance/保留，未算通过。JSON在原诊断缓存同ID的stop-candidates.json，首版stop-candidates-first-comparison.json保留。
- 常用5186兼容后端已存在并复用；旧工具会话已失效，先核实际端口/工作目录/只读能力，不重复启动进程。构建在隔离输出验证后移入默认web/.webpack，上一版在忽略的drone-candidate-previous-build-20261024保留；5187已停。未改其他机器人运行环境；SO101 Python路径WARNING仍未修，未宣称其实际物理/3D回归。
- agent-link qoder超时无活会话，CBC结束但无正文，均不当通过；内置只读审查提出可选坏JSON阻断原回放，已最小修复并原负例核对。根负责实际结果与串行整合。
- [使用/参数/数字与边界](../../docs/DRONE_STOP_CANDIDATES.md)。本片完成N3组件基线与N4历史旁路，N3任务级比较、M2滚动提交、M3动态闭环及后续空地臂联动仍未完成；下一项M0源码/许可及CommittedTail差异，不自动训练、解冻或飞行。owner=本对话Codex，整体goal保持active。
- Knowledge closeout: already_covered。沿用任务身份/源时钟、动作与物理资格分层及PIT-004；数值、可选输入降级和CLI兼容性留项目，未写共享知识或memory。

## 2026-10-24 — SO101 网页开发布局2/2原物理通过

沿原5186样例按钮→task-runtime→Station执行器完整新跑，右task6e86ec73-db38-4d19-b48d-56dec4c1006c、左taskf7c265d5-5668-4643-a2f0-b7db2bc05d83均原passed/grasp/place/done=true。78.02/78.08sim、59.131/58.445episode-wall；planned/measured各244，free/weld0/mocap0，无无效轨迹、障碍接触或安全停机。释放/脱离/回位、双worker清理及两份488帧录像由根与独立reader核实，warnings=0。

浏览器每例一次POST，原harness刷新同ID/无重发、报告与视频Range206断言通过；仅checks标签保存在结果，独立JSON核查不外推完整网络时序重建。前述九项无运动检查、33数据/50Python/3服务及构建通过保持。实际SO101运行采用显式交付ROOT/planning-venv，已独立核ready及完整物理；不据此改写无人机诊断页自身历史WARNING或N3/N4的验收范围。

SO101来源084cc7f，工作台本轮abc0ac7/2b9fd90；并行Drone源码已由原owner提交并推送de94a6d，原成绩保留，本轮未改其模块。主FishBot dirty main及Mint未触碰。5186继续可用；5187原owner自行收尾，本轮未停止他人进程。原件在station-tasks/<ID>、浏览器output/workspace-execution-20261024[-left]-v1/，均不提交。

本轮未采EpisodeTiming或精确process CPU，unknown保留；旧Kaggle计时不填此空缺。SO101连续包络、恢复、20+20、50Hz与同世界卸货仍未完成，继续回源SO101主计划推进M1b。Knowledge=already_covered，领域事实只写原计划。


## 2026-10-24 M0 / M2完整轨迹静态回放

官方Gatekeeper源码/许可与本地原型对照已核，见[方法与边界](../../docs/DRONE_COMMITTED_REPLAY.md)。机载包许可TODO，未移植；现有CommittedTail＋MINCO＋连续审计以外只有离线薄适配。

新增workbench-tools/drone-committed-replay.py和8项局部检查。已复现admit后首次tick倒退仍track，外部适配以有限时钟高水位修补；不改冻结drone。重审完整前缀/尾段、上下文和地图有效期，不信任缓存passed。

实际N3#6/#7系数的16个静态反事实情景已运行/回读：#6原V1.680871/A.981600/Z2.133051，#7 A拒绝后旧绝对相位保留；占据/终点侵入、未知/过期图、暂停漂移和时间回退均按具体原因撤销选择。原1.8/1/2.2硬界不变。

输出在忽略的apps/fishbot-control-station/workbench-tools/output/drone-committed/748f910e-f0f8-4ecf-b2d5-22b7b15d57e6/selection-replay.json。地图/未来覆盖和理想PVA是声明的fixture，不是原动态感知；protect输出空参考，不是实现安全恢复。M2未完成，动态闭环未通过。

8新局部检查＋原N3三项/N2两项，共13项通过；实际报告20项读回检查通过，9份变更文档72处本地链接无缺失，diff检查通过；内置只读审查无阻断，根核实际结果。AGY启动参数错误无审查结果，未改其配置、不联系旧聊天。未改网页/服务，无需重构建或浏览器QA；5186旧历史展示保持。无训练、飞行、ROS或控制写，drone c866441冻结。

后续由本对话从有来源的实际状态/预测、时间有效地图和终端区域资格接续M2，M3不自动启动。knowledge_status=already_covered，项目事实不写个人memory。


## 2026-10-24 M2原CDR状态与地图资格

实现[原记录资格](../../docs/DRONE_RECORDED_STATE.md)：原depth-input MCAP有1926条/drone/ego/odom，复用CDR与N1 clock_bracket读取PV，不启动ROS节点。位置为理想Gazebo，速度为sidecar因果差分；A未记录，不补参考值。

1899条取得录制可用上界，27条未包围保留未知。首发33.452s前195个源时刻对照：P峰.292422/P95 .276889m、正Z峰.073111m、V差峰.219773m/s。7个FSM/bag PV误差≤6.95e-13，345个truth源时刻P完全一致；是同源存储核对，不是独立定位。

33.388s FSM用了33.228s odom：混时P差.385835m，同刻差.166906m。两条odom早于新曲线起点保留未评分，未反向外推。审查提出FSM曲线接收/frame泛化缺口，已修补并用负例验证。旧#5/#6名义高度余量.071047/.066949m低于历史正Z差，只作诊断，不晋级为反事实控制包络。

原1138次/425cell阈值见证和单格两次膨胀变化均是局部记录；原MCAP无完整地图通道。front源32.968、融合结束33.332，down源33.100、结束33.356；FSM开始33.388。完整地图、未来安全集、终端区域、PVA和飞控采用仍未获资格。

9新局部＋8原静态回放检查通过；实际原CDR输出16项读回检查通过，图已生成并目视核。JSON/PNG在忽略的workbench-tools/output/drone-committed/748f910e-f0f8-4ecf-b2d5-22b7b15d57e6/，命令见方法文档。CBC返回空正文无审查结果，内置只读fallback给出具体问题，根修复并重跑。

没有改服务或UI，不重建/重跑浏览器。drone c866441冻结/清洁，无训练/飞行/控制写。M2未完成、动态闭环未通过。下一步在冻结边界内评测现有PV外推的误差/时钟适用域，不把估计A冒称实测A；由本对话接续。knowledge_status=already_covered，项目数值留本仓，未写memory。
- 收尾核对：9份变更文档75处本地链接目标无缺失，diff检查通过。代码/文档按既有qiaoqiao2521分支提交；原CDR、JSON/PNG和日志均留忽略目录。


## 2026-10-24 M2固定PV预测基线

在已有drone-recorded-tracking.py增加--forecast，不建第二套读包/调度。缓存保持、恒速、过去V差分估计A三种基线固定；原PVA/飞行源码不变。recorder可用与FSM消费证据分路，未来PV只评分，评分时间偏移0–.016s公开。

949组旧记录case（942 recorder＋7 FSM），33个请求因评分样本越首发/缺失而排除。7 FSM位置RMS .164031/.007136/.003245m，峰值.239405/.010564/.006433m；CA首个样本比CV差，未晋级运行默认。33.388s真实跟踪P差仍.185380m，预测误差变小不能替代控制资格。

20项状态/预测检查（原9＋新增11）与原静态回放8项通过。内置只读审查指出整型/字符串同stamp冲突绕过和NaN首发截止两项，已修补/补负例。Qoder首轮建议有效、二次审查超时，get_status确认该句柄缺失，没有重启同任务。

实际JSON/PNG在原workbench-tools/output/drone-committed/748f910e-f0f8-4ecf-b2d5-22b7b15d57e6/的pv-forecast-evaluation.json与pv-forecast-comparison.png；图已目视核对。参数/表格/复验见docs/DRONE_RECORDED_STATE.md新增节。生成数据和原日志不提交。

工作树另出现RobotStation/station.ts、index.ts、station.test.ts与新stationRecipe.ts/test.ts共5个配方在途文件，语义为SO101 independent_episode包。尚无本轮交付/验证回执且文件在工作期间出现，保留现场、不混入无人机提交。接续owner=根Codex，需从原Station importer/recipe定向测试入口复核并查对应产品化进度，当前不宣称其验收或废弃；不联系其他旧聊天。

无人机c866441冻结、无训练/ROS节点/飞行/控制写。M2未完成、动态闭环未通过。下一项预测后参考偏差/必要制动可行域和时间有效几何，由本对话接续。knowledge_status=already_covered，项目数字留SpecMesh，未写memory。
- 本轮独立CDR读回17项通过，1926源消息逐个核对预测输入/评分PV，949 case保持原首发截止与时间来源。8份变更文档72处本地链接无缺失，diff检查通过。
