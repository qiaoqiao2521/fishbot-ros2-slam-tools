# Progress — 连续业务世界与可视化回归

## Current

2026-10-25，目标仍为完成本计划M1–M4，尚未完成。R1四类各10000步通过；R2已补实际AMCL先验注入、静止新帧及分进程发布环境观察，正常载货仍未通过。新无ROS探针已在原.10转向输入下复现支撑波动；Graceful轮的该输入来自预测碰撞后的Spin恢复，未误改主控制器。M4b只读双轨迹保持，M4c新增CPU工作流；独立环境74项、全前端687项及构建通过。GitHub原运行40111818800已接受，最后读回queued/0 jobs，尚无远端通过证据。M2实体、显式多臂/多货物查询和第二货物真实抓取分项已验，B新初态卸货分项已验，端到端卸货/连续订单仍未完成。M3、原生CI与正式A/B仍待完成。本轮完整反馈为1855项通过（1098/22/209/61/465），0失败/0跳过；不替代原生业务验收。

| 范围 | 当前状态 |
| --- | --- |
| D0／M1a | 完成：旧K耗时、SQLite索引、瀑布图 |
| M1b R1 | 完成：四类各两分支10000步，状态/接触/观测差异0 |
| M1b R2 | 恢复、先验输入与静止预热已验；载货路线仍无新成功，未收尾 |
| M2 | 双臂/双自由货物、按名控制/查询、接触/快照及第二货物抓取分项已验；B新初态卸货分项已验；owner/Workflow/独立评分已接，独立货位卸货分项已验；无reset双订单未验 |
| M3 | 故障、异常前留存、模拟充电续单尚未实施 |
| M4a | 开发试验未晋级，正式5+5／留出／完整回验未派发 |
| M4b | 只读双轨迹/Ghost首版已验；矩阵编辑与原owner派发未完成 |
| M4c | CPU工作流与本机验证已实施，原远端run排队；原生CI/发布未完成 |

根入口为[任务计划](task_plan.md)，原生结果、限制和技术修正见[发现](findings.md)。旧F1完整K仍为J100＋3D雷达同轮B→A2/2，B119.793848秒；麦轮P1–P3在8b3b9ec独立交付。这些旧成功不抵消本轮新失败，也不复跑它们充数。

## Done

- M2显式查询已复用原IK/OMPL，完整冻结其他实体并进行工位旋转变换。原pad组漏检反例已补；14项原生实体检查通过。第二货物抓取c轮在强化后的源版本复跑，23420步/2242帧，最小抬升40.913mm、双指1.587N、连续保持1.5源秒，原.025m/.02N/.7s条件通过；禁碰和重置0、保持阶段支撑接触样本0，world/episode和选定源码起止一致。不是运输或连续订单通过。早期a/b原记录与独立fixture-score.json保留。
- B新初态卸货a因连接台/固定底座重叠约2.759mm而在派发前拒绝；新增显式bridge_center_xy_m=(.033,-.145)，只移动新工位连接台，尺寸/掩码/原margin保持。独立查询的home、托盘和货架IK端点通过，但不等于整条载荷路径。b轮真实抓起后，低放置点.019导致载荷/货架约.114mm穿透，原.2mm载荷检查拒绝；c改用原放置配方.023的释放高度后完成真实抓取/搬运/释放/货架落稳/归位，未放宽碰撞或改旧原成功。

- B卸货c独立分项评分通过：新B初态（车/货物起初已在托盘）同一world/episode、reset=0，共51510步/5051帧/103.02源秒。抬升最小40.857mm、双指保持1.530N/1.5源秒；搬运最小双指1.550N且无支撑接触。最终货物完整足迹在货架内、支撑持续1.52源秒、指夹0、最大线速约1.1e-14m/s；回位位置误差.000580rad、终帧原生速度范数1.73e-5rad/s，禁碰0、hold、源码起止一致。逐帧臂原生速度未记录，不追认为完整连续quiet或原任务oracle通过；初态不是到站导航。证据m2-unload-fixture-c/fixture-score.json及原R1 grasp-checkpoint.json；货物未传送，cargo_1保持同一自由关节，cargo_2仍在取货台。
- 最终m2-feedback-current-c全部1805项通过，control1049/checkpoint21/mission209/autonomy61/frontend465，0失败/0跳过。实体原生14项包含坐标/完整网格、pad重叠拒绝、ctrl/源时间、原pinch偏移与快照；旧fixture和早期探针失败均保留，不将旧结果擦除。
- M2实体首片已接prepare可选配置：J100＋3D雷达、B卸货臂和两件自由货物在同一Physics中运行；原默认构建不变。最终proof-b的5源秒/2500步/250帧，world/episode保持、reset=0、车体/臂禁碰累计0，沉降后两cargo的50Hz支撑样本失联0；所选源码及4个XML输入起止一致。出生点/B目标静态净距约61mm，B初始物理fixture另验1000步无禁碰；都不冒充导航、500Hz支撑连续或卸货通过。
- 质量/惯量、完整geom与执行器原参数精确回归通过；按名字路由附加臂、R1额外参考恢复和第二cargo静止检查已验。原生实体/快照/scene/prepare组38项通过，运行/工厂组80项通过，最新实体/仿真路由组60项通过，互有重叠不合计。首轮to_xml惯量舍入失败、原工位83.5N碰撞及旧退出fixture11错均保留，原因/修复见findings。

- 新增cooperation_checkpoint薄适配，复用mjSTATE_INTEGRATION、原Physics收件箱与有界异步IO。固定模型描述预先准备并单份落盘；物理周期只复制状态/模型声明可变项/编码器/RNG，后台不持有MjData。活动世界只捕获，新实例才能恢复；没有内容哈希锁。
- R1-b及加强结构兼容后的R1-c均4/4通过：自由货物静止、载货静止、非零轮速、材质＋外力。每类原/恢复分支各10000步；积分、接触、车货轨迹、编码器、感知随机流与360束scan最大差异0。实际接触friction含.25，冲量.75Ns。c的20次copy P50/P95为1.139/1.968ms，恢复.131–.220秒；b曾有36.9ms尾部，不外推50ms端到端。
- 最终R1-d同四类4/4通过，每分支10000步，全部状态/接触/观测差异0。选定源码与XML/manifest起止一致，观测错误0。20次copy P50/P95为.889/39.228ms，最大76.301ms；恢复.097–.108秒。该尾延迟保留，不能以c的较低P95承诺50ms。原生单元已退出，performance持有释放为balanced。
- capture RPC沿原bridge→Physics请求/回执，不增第二个写入owner。真实父回合完成抓放/出站，保存b649aaf7检查点；随后B路线120.014秒失败，不能计新完整成功。实际动态库路径与旧K相同已核，不用进程启动代替评分。
- R2-1c/2b位于154/9124、155/9125：原生积分读回误差0、初始真位姿相同、新world/episode且旧命令清除。实际载货1.843/2.032m，独立保持无违例。路线120.058/120.028秒失败，末21.23/30.82cm。原UUID终态、连续quiet、guard关闭、参数恢复、owned清理与源起止一致分别成立。两次是replication，不宣称改进。
- 每分支原清理后5次capture RPC，观察端到端P50为62/91ms，P95为794/827ms，包含约16.5MB冷模型首次写入。热状态约80KB，轮询20ms使端到端值为观察上界，不是控制器消费ACK。R2仅用父TF均值，父协方差unknown；未恢复AMCL/EKF/Nav2/DDS历史。
- 四轮开发试验均失败并清理：原参数performance复测仍超时且有1个保持违例；角速.10触支撑失败，已撤回；减速半径.08超时且有1个保持违例；.04在108.564秒触支撑失败。原加减速、GoalChecker、完整几何与物理评分保持。performance按进程申请并已释放，不从单次关联宣布根因；具体试验条件见findings。
- /regression复用原耗时索引/10Hz流，新增左右同坐标、显式源锚点、Ghost、货物/关节投影、原生UUID、原失败分布、缺口和未知。真实1440/390px浏览器11项通过，写请求0、pageerror0。GET接口复用现有中间件；原日志/轨迹/SQLite留本地，没有导入第二个Lichtblick源码树。
- 前阶段完整反馈1778项通过：control1037、checkpoint6、mission209、autonomy61、frontend465。检查点独立使用已有规划Python，避免污染系统OpenCV/NumPy。构建/类型检查通过；之后小幅展示和来源核对改动14项Python、11项前端定向通过，未重复全仓测试充数。
- 收口补充异步捕获去重：同ID落盘未完成时不重复捕获，完成后释放in-flight登记。原重置默认行为保持；7项checkpoint加原reset/launch/route共27项通过。新视图最终浏览器11项（含原生UUID）与生产构建通过；完整回归的1778计数是补此新增用例前的实测，不虚增为1779全套。
- 快照与只读回放切片已提交5bc20db并推送既有qiaoqiao2521远端，读回一致。随后补R2显式静止预热：复用AMCL原服务，分别保存服务回执、三条请求后新定位及原协方差，不称收敛或控制消费ACK；默认非R2流程不变。实际ROS固定数组为NumPy float64，微小负协方差仅记录；a/b两轮适配准备失败、0次动作派发保留，修复后43项相关检查通过。
- r2-warmup-3-c使用同快照、相同Nav2参数、balanced与160/9130。实际三条请求后新帧预热在.558秒完成，随后原UUID 47d879b28f1942048d86aee4997de9b6进入真实控制。仍在120.016秒超时，进场0/1，最终46.59cm/.67499rad；货物移动1.868m，有1个保持违例，任务失败。日志在约46/72墙秒两次报告预测轨迹碰撞并清图重试，不足以单凭日志判定具体障碍或唯一根因。原UUID终态5、连续quiet、guard关闭、参数恢复、owned清理与源码起止一致均成立；不称改进。
- 已补分支先验原生提交：prepare保留同父均值与已有.0004/.0004/.001协方差，经SetInitialPose一次提交后才做新帧预热；未知回执不重发，可对账迟到的原回执。46项相关检查及实际SDK消息构造通过。161/9131的r2-prior-a实际返回服务回执并取得更新位姿/非零协方差，仍在120.004秒超时，末25.75cm；输入修复与业务失败分别记录。
- 已核对原K明确使用asynchronous，旧切片遗漏该参数。现记录bridge/physics实际publication_mode_env及系统load，39项相关检查通过。固定RPP source开发轮81.811秒支撑失败；恢复显式异步后，原Graceful在109.393秒、RPP在31.172秒支撑失败，未晋级。两个异步进程的环境、原UUID5、quiet/guard关闭/参数恢复/owned退出及源起止分别核实；不从单次对照宣布根因。详情见findings。
- 失败帧的货物平面足迹仍在原边界内，底面接触曾为false，双指均0；通用“离开支撑范围”不能直接解释为滑出。RPP异步440条变换路径/碰撞投影与源码computeVelocityCommands发布点提供计算活动证据，不是逐条消费ACK或业务成功。原门槛不变，故障面板未以这些非预声明失败补数。
- 无ROS短驱动探针drive-support-probe-a完成：同真实装货快照四次R1读回误差0，原完整名义扫掠预检净距至少.197m。零指令、.06直行、±.055转向按原斜率升降回稳，共9850步/985个50Hz样本，底面失联/足迹越界/车体禁止接触均0、源起止一致。未复现长路径故障，不算导航通过；目标平台段真实角速约±.0375，编码器约±.0507，目标±.055，瞬态峰值另存，不能直接当稳态标定结论。
- 早期126项检查点/原启动/控制、198项原合同及145项scope相关检查保留。首R1-a因探针缺显式covariance在准备期失败，补原契约后复跑，未放宽1m观测范围。初版测试fixture缺nav2_yaml的错误亦保留，修复后6项检查点通过。

## Remaining

2026-10-25驱动隔离续接：probe-b四项完成，共30400步/3040帧，两层均无失联。probe-c共22666步/2268帧，在±.10纯转向复现21/18个求解步与3/3个发布帧失联；混合正向有2个求解步，发布帧0。完整几何、源起止与评分保持，均不是导航或运输通过。Graceful首次失联位于原生Spin恢复启动约6.64秒后；原FollowPath已是.055，未更改主控制参数。RPP该时窗无Spin，不合并根因。

- M1b：R1已合格，R2先验/预热已验但正常载货仍未通过；继续做原模型驱动与支撑分项探针。
- M2：实体已接；多实体查询与第二货物抓取分项已验，原owner/Workflow/命名独立评分与逐ID库存已接，继续真实导航、A卸货臂分项和无reset B/B与B/A。
- M3：实际故障/原UUID安全处理/异常前留存、模拟低电充电续单。
- M4：矩阵编辑/原owner派发、正式配对5+5、留出与完整B→A、分层CI及可追溯发布。

## Issues

- 所有本轮新运输结果均为失败；R1一致或R2恢复/保持成立不能改判为业务通过。原120秒与原物理评分未放宽；没有唯一根因结论。
- 早期R2-1a在发包hook临时增加scope，破坏已持久化账本合同，协调器退出；systemd回收后缺原生终态/quiet证明，保留unknown。现改Workflow先持久scope再派发，异常时取消原UUID并保存终态/关闭窗口/清理。
- 1b还把初始化误计入路线120秒，提前取消；该失败保留。现在任务总计原360秒，出站后路线独立120秒，原15mm/35mrad GoalChecker与独立40mm/50mrad/1秒停稳保持。
- 原K没有完整积分状态，只能作R0/历史导入。AMCL粒子、EKF/Nav2/DDS/计时器不是R1组成，跨车型不共享浮点状态。
- 实体层、原owner/Workflow与逐ID库存已接；两独立货位卸货分项通过。B/A三臂配置已生成并静置/点位预检，尚无原生无reset B/B或B/A双订单，不用合同/分项替代连续生产验收。
- 原7项规划环境缺失已由麦轮P2/P3恢复；不再列为当前阻塞。7×24、倍速等价、真机或sim-to-real成功均未声明。

## Knowledge Writeback

knowledge_status=updated。原Wiki/ROS2 与 FishBot.md第20节“快照恢复：物理状态、ROS分支与预算分开”已补R1/R2、双预算、原生先验/新帧与ROS数值类型及DDS实际环境观察；本轮再补命令超主控制设定时先区分Spin等恢复动作、低速/低频阴性结果不外推，以及模型导出惯量精度、名称绑定、附加臂目标和第二货物快照/静止判定经验。开发知识入口补Spin、模型导出惯量舍入、多臂/多货物快照和夹指碰撞组漏检触发词，另补pad碰撞组与pinch偏移经验，两处原文各唯一读回。只写可复用经验，不写项目成功状态。知识库两文件原有大量未审改动保留，未整库提交或发布；该库后续整合owner=根Codex，最短入口为两原文件局部diff。

## Cleanup / Recovery

m2-cleanup-a.json已实际核验并执行：旧m2-model-a/b十个文件以原生tar/gzip归档，读回失败1017禁碰和后续0禁碰后移除展开目录；删除已空闲的可重建ci-cpu-venv、ci-frontend-dist-a和三张弃用试拍，保留采用图model-scene-b-clean.png。目标已分配空间从98983936字节降到98304字节，释放98885632字节，约94.3MiB。原R1/R2、采用场景XML依赖、规划环境、共享node_modules与数值/来源记录均保留，未停止其他任务。

恢复旧模型探针：`tar -xzf ~/.cache/fishbot/continuous-twin-20261024/archives/m2-model-prototypes-a-b.tar.gz -C ~/.cache/fishbot/continuous-twin-20261024`。CI临时venv已删除，不能再把该路径当现存环境；环境与构建可由工作流重建。后续m2-cleanup-b.json又归档并读回四个早期实体抓取/卸货a/b目录，共28成员，释放6758400字节；归档archives/m2-early-entity-fixtures-a-b.tar.gz。恢复同样用`tar -xzf ~/.cache/fishbot/continuous-twin-20261024/archives/m2-early-entity-fixtures-a-b.tar.gz -C ~/.cache/fishbot/continuous-twin-20261024`。两轮合计释放105644032字节（100.75MiB）。当前采用的grasp-c/unload-c、原生R1、最终图与全部模型依赖保留；旧根日志/脚本也保留。

## Verification

2026-10-25：ci-cpu-contracts-isolated-a.log在仅安装NumPy1.26.4的独立Python环境74/74通过，rclpy/mujoco均未安装；ci-frontend-a.log为57文件/687项通过，ci-frontend-build-a.log构建通过，保留500KB chunk警告。actionlint1.7.12检查新增工作流通过。不是新的1778全仓回归、浏览器验收或原生配送通过。

edd6b5b已推送并读回一致，工作流395248656已注册active。显式dispatch一次返回[原运行40111818800](https://github.com/qiaoqiao2521/fishbot-ros2-slam-tools/actions/runs/40111818800)，head_sha=edd6b5b9cbef3848608aca9d331af09b0b94fa13，最后读回queued/conclusion=null/jobs=0；不计远端通过、不重复dispatch。ci-github-watch-a.log保存原运行观察；本地watch到期不代表远端终态。接续owner=root，最短入口为查询该原run及jobs。

私有证据根为~/.cache/fishbot/continuous-twin-20261024/。R1-b/c/d、父回合、R2早期失败/最终两次复现、四开发试验、warmup-3-a/b/c、capture样本、feedback-current-a.json、closeout-contracts-a.log、r2-warmup-contracts-a/b/c.log和ui-comparison-a/b分别保留。R1-d另存loaded-code-start/end.json及inputs-start/end.json，物理通过与来源观察分列。原记录未重写，详细轨迹/原始日志/模型状态/数据库/截图不提交Git。

所有153–159 owned单元已inactive/not-found，9123–9129关闭，performance持有释放为balanced；早期1a不追认原生安全通过。5191只读Vite保留，/regression读取本地对照，未启动107/114；原受保护实例保持。

160的warmup-3-a/b/c单元均已退出，9130关闭。a/b无Goal且准备失败，不将systemd回收追认为原生取消验收；c独立cleanup_complete=true、原静止窗口约2.98源秒、0 survivors与端口关闭均核实。没有运行正式5+5或完整运输。

本轮161–164单元已退出，9131–9134关闭，0 survivors。r2-prior-a、r2-rpp-a、r2-rpp-async-a、r2-prior-async-a及46/39项相关日志、r2-initialization-diagnostic-a.json、async-support-diagnostic-a.json分别保留。原数据不入Git。最新只读comparison-prior-rpp-async-a为同快照/同几何的两个失败开发样本；Graceful/RPP缺37/6物理序号，最大源间隙.34/.04秒，未插值补齐。5191 GET与浏览器11项通过、写请求0、pageerror0，证据ui-prior-rpp-async-a。非正式A/B，旧对照也保留。

D0/M1a历史验证：97处文档链接，7项导入、17项前端、9组桌面/手机行为通过，写请求0、pageerror0。真实约500MB原记录导入8.45秒、峰值RSS19960KiB；SQLite为2案例/32阶段/2轨迹索引，B/A展示2685/1740点，旧K原评分、119.793848/34.883377秒及缺1/50序号保持。该旧阶段曾有7项规划环境缺失失败，不能拿旧失败描述本轮已恢复的依赖，也不能拿当前全绿擦除它们。

最终显式身份防误用补丁只影响多实体manifest漏传arm/cargo的查询：不再默默走会漏掉额外实体的legacy模型；原单臂场景默认保持。该小补丁在1805项完整回归后增加，随后当前7项显式选择/原有子进程生命周期测试通过；未机械重跑全仓。原生卸货c为补丁前、显式身份路径的证据，源码版本观察保留，不改写成所有新分支均原生验过。下一步必须给原owner传入明确实体，不能以这一错误处理当M2完成。

最终图unloaded-workcell.png从实际final-state与独立新MjModel渲染，未步进物理；缺DISPLAY的首次渲染失败保留说明，改用既有EGL后成功，未安装新平台/驱动。所有本轮原生探针与反馈进程已退出，没有新ROS域/端口或GPU作业；5191只读页与107/114未触碰。

交付：有效源码/配置/测试与本计划已提交174a35f443008c0b95ff124ebab7788ce6f1e9ab并推送既有qiaoqiao2521/fishbot-ros2-slam-tools；实际远端main SHA与本地读回一致，工作区干净。既有CPU工作流的最后API读回仍仅见原dispatch运行40111818800/queued，不宣称远端CI通过，也未重复dispatch。当前源/原生分项验证与M1–M4完整业务验收仍分开。

## Next

继续查询GitHub原run40111818800，不重新派发。M2显式实体查询与第二货物真实抓取分项已通；新B初态卸货c分项已验，下一步将实体选择/卸货接入原owner并补逐帧臂速度，再推进无reset双订单/库存。M1继续补原Graceful预测碰撞前的原生轨迹/局部地图证据；probe-c已复现支撑波动，不重复低速阴性探针。原120秒/GoalChecker/独立评分保持，取得合格R2后跑正式5+5/留出/完整B→A。M2/M3及矩阵/原生CI范围不缩减，本目标保持active，root继续，不联系其他对话。


## M2 owner 接续结果（2026-10-25）

原 Bridge/Workflow/Factory 已接显式 cargo/arm/station、独立 shelf cell、有限库存、清理后新源帧再次核验与无 reset 接单。新独立 Oracle 按货物订阅真实 ROS 位姿，并与原物理/Clock、完整夹取/运输/卸货评分交叉核对。当前只是代码和已列分项完成；M1–M4整体仍 active，正式无reset B/B、B/A、M3和M4原范围不缩减。

本轮完整反馈 m2-feedback-owner-a 为1855项通过（1098/22/209/61/465），无失败/跳过。B/B公开dry-run为0 ROS/0 POST、540单单/1360整轮，原360装运/120路线/默认旧360与1000保持；新增180只属于卸货。历史定向测试不与本轮计数叠加。私有原型和早期夹具失败保留，见findings。

冻结后第一 cell b 和保留已交付 cargo_1 的第二 cell fixture a 独立评分均通过；源起止一致、禁碰/reset0，逐帧原生臂速度已记录。第二轮57230步/5623帧，支撑落稳1.52源秒、双指0、最大臂速度1.792e-5rad/s；第一货物全样本仍在自己的 cell 并有货架支撑。这是两个独立新初态 fixture，不能拼成连续两单。第一开发轮a源码变化，因此不追认为冻结通过。

165静止真实ROS烟测匹配两件货物各194帧，位姿/四元数差0，保持/同世界/同episode/reset0/禁碰0；owned进程与context退出。命名发布端GID核验仍未加入；烟测退出后endpoint为空，不冒充活动发布端证明。B/A新增第三台臂的43/40/22模型公开prepare、1000步静置及A/B完整几何预检通过，A实际卸货和完整路线仍未验。

接续 owner=root。最短入口为 docs/FACTORY_DELIVERY.md“有限库存与连续配送”，两组entities/orders JSON已入源；私有准备场景 m2-prepared-slots-a、m2-prepared-ba-a。当前准备场景为默认NavFn/source定位构建，尚未按合格J100运输配置完成新工位路线验收；不能仅去掉dry-run就宣称复用了旧K。先核控制配置/算力与新场景路线，再执行原Factory的B/B、B/A，并保留原预算及独立原生终态/卸货评分。原GitHub40111818800本轮读回仍queued，没有远端CI通过证明。


本轮知识回写 knowledge_status=updated：既有 Wiki/ROS2 与 FishBot.md 第20节补“连续配送的独立货位、命名独立观测及清理后新帧更新库存”；开发知识入口补货位占用/清理后回执触发词，原段落与入口各唯一读回。知识仓其它大量未审改动保留，未整库提交；后续整合 owner=root。

本轮清理已执行 m2-owner-cleanup-a.json：开发 cell1-a 全目录归档并读回原 source_unchanged=false/物理判定，移除展开副本；采用 cell1-b、cell2-occupied-a 的原采样以 gzip 保存并读回帧数/末源时间，移除展开 samples.json。独立 scorer 已支持压缩原件，压缩后复算仍为两分项通过。选定模型/XML依赖、R1状态、当前源码和失败证据保留。目标分配空间218497024→136859648字节，释放81637376字节（77.86MiB）。恢复开发轮：`tar -xzf ~/.cache/fishbot/continuous-twin-20261024/archives/m2-cell1-development-a.tar.gz -C ~/.cache/fishbot/continuous-twin-20261024`；恢复单份原采样：`gzip -dk <fixture>/samples.json.gz`。原生165和全部本轮无ROS fixture进程/context已退出，未启动完整运输或GPU作业，未碰107/114和5191只读页。
