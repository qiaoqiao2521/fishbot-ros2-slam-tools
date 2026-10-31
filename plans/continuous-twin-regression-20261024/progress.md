# Progress — 连续业务世界与可视化回归

## Current

2026-10-31：本次V1–V4模型推理与视觉配送完成。K同一world/episode无reset完成B→A，两单独立命名原物理、业务及原记录重算均通过；源码起止一致，原时限/碰撞/接触门槛保持，owned进程和端口已清理。整轮958.277墙秒，路线49.902/20.968秒，末XY31.065/21.215mm。停车保护辅助、源采样缺口和A–J全部失败保留；本文件末尾记录当前验收和恢复入口，下方2026-10-27及以前状态为历史。持续孪生M3/M4等其他计划项仍按未验边界接续，不能由本次视觉两单代替。配置见[预训练感知](../../docs/PRETRAINED_PERCEPTION.md)。

2026-10-27 本轮：卡点快照10档原地小角速离线测试完成，±.001/.003几乎无响应、±.01已转动；原载货/几何不变。30秒固定路径原生FollowPath确认Shim约8.3秒后MPPI输出，继续前进但偏离增加、角命令接近小角速响应不足区间。PathAngle阈值.15单变量短测进度失败；temperature .03单变量前段更快、后段仍停且偏差增长；两者均不晋级，原owner完整进场/配送尚未运行通过。下一步针对运动时小角响应与路径偏移做分层修复，保留hold切换接触瞬态及采样缺口。

2026-10-27 固定卡点：新原生快照4377a191已恢复R2，局部路径40点经TF与缓存全局路径对应；AMCL/控制器状态重新初始化。独立FollowPath在原载货限速下15秒真值转向-.331rad，temperature=.03对照-.330rad；已采50Hz支撑/禁碰0，smoothed观察有缺口，两轮原UUID取消5/hold/实例已退出。不支持必然存在.15rad/s以下转向死区；两轮未证明路线或配送通过。进场/完整运输仍需下一步原owner验收。

2026-10-27 最新：MPPI逐critic实测定位到min_x=.001速度反馈归零导致起步死区，设0后10秒物理位移.00568→.22491m；完整载货进场仍120.006秒失败。min_theta=0的65秒对照仍在转弯处停滞，具体代价、采样缺口和取消终态见findings。当前准备冻结真实卡点的物理积分快照和原生Path，以15秒短试验隔离转弯；不得用普通truth帧冒充完整快照。

2026-10-27定向处理J100进场/转向。相同新载货fixture下原yaw和yaw0两轮均在原120秒预算耗尽，第一进场点未完成；分别为120.008秒和120.027秒，原生Goal终态均5，已清理独占168/9138。原yaw录得一次载货支撑/归位评分异常，需保留并调查。真实控制器诊断显示路径裁剪跨过折返点，尾30秒600个有效周期中378次目标在倒车段却位于车前。现评估复用Nav2 MPPI现有方向转换保护；两轮均不计路线或完整运输通过。观察新增三个原生诊断话题，77项相关测试通过。详细证据见findings。 原生MPPI换向候选b也失败：112.124秒载货支撑检查触发，Nav UUID 0f5f08414dee4a09b8e3e12fbd2774e0终态5、第一进场未完成；代码起止一致且进程/端口已清理。首次候选因预建输出目录在派发前拒绝，未启动车辆。第二MPPI角度候选120.023秒超时，第一进场0段，货物持续受支撑但车最大位移仅.03742m，故不晋级。新增三层速度与MPPI最优轨迹诊断：输出几乎为零，30–85秒三层指令P95差0；不是平滑/监测拦截。回读角度阈值.15、inversion=true、Spin max/min/acc=.055/.01/.05。恢复项目模板噪声尺度对照在120.024秒超时、第一进场0段，原Nav UUID 58fcb2304bb4438988e1a32ffbc0bd2a终态5，未证明原因或解决路线。原末端、速度和评分不变；此轮结果保留。

2026-10-26，M1–M4仍未完成。M2旧B/B首单原360秒装运失败；本轮命名放货已走受控查询子进程，实际10.020秒并保持原计划/几何，新的B/B首单仍在配送路线120.018秒超时，第二单未执行。外层协调进程退出143、原因unknown；root只接管原任务，独立终态/连续quiet/guard退出/参数恢复成立，owned实例和端口均清理，无额外start/reset/cancel POST。新轮源起止一致，命名GID已独立核验，不计连续业务通过。M3外力已接Physics/R1/R2，根独立32项通过，ROS实时Goal/阶段触发及安全面板仍缺；M4正式对照、留出、矩阵和原生CI待办保持。最新完整反馈1865项通过，后续局部报告/信号修正分别执行定向检查，不虚增完整回归数。

| 范围 | 当前状态 |
| --- | --- |
| D0／M1a | 完成：旧K耗时、SQLite索引、瀑布图 |
| M1b R1 | 完成：四类各两分支10000步，状态/接触/观测差异0 |
| M1b R2 | 恢复、先验输入与静止预热已验；载货路线仍无新成功，未收尾 |
| M2 | 双臂/双自由货物、按名控制/查询、接触/快照及第二货物抓取分项已验；B新初态卸货分项已验；owner/Workflow/独立评分已接，独立货位卸货分项已验；无reset B/B已尝试但未通过，B/A未派发 |
| M3 | 源时间外力已接Physics/R1/R2，根独立32项通过；原生Goal实时触发、实际取消、异常前留存和充电续单未验 |
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

### 2026-10-30 RGB-D 输入切片

- 已实现 `--camera-rgbd`，默认关闭；开启后保持原ideal/vision语义，同一快照发布RGB、CameraInfo、32FC1米制光轴深度和原来源信息。NaN代表无效深度，远平面无效；相对安装外参来自车型编译MJCF，不发布世界位姿或目标真值。SO101固定工位与J100继续独立控制。
- 6项真实MuJoCo/ROS消息检查通过：深度单位与背景、时间/字节、错误尺寸、RGB-only/RGB-D线程、变车型安装、实际J100 prepare及640×480渲染。未启动DDS/动作/Nav2，也未作模型推理。原相机/prepare/sim共76项通过，无跳过；native6另计。EGL依赖有已存在的/proc/cpuinfo ResourceWarning，不影响通过；未修改第三方库。
- 独立内置审查指出float深度用0会被标准点云组件当作有效原点，已改NaN并复验。首次扩展测试还暴露旧模拟桩缺Physics.close和business_cargo_pubs：先出现12个错误/1跳过，改用原规划环境后剩1错误，补桩后76项全通过。只补测试接口和关闭检查，未改生产清理或任务评分。
- 复用调查确认SO101现有GraspGen-X官方模型曾在完整几何输入下完成固定方块抓放；不把它等同视觉。原缓存venv/models路径已缺失；当前规划环境缺Torch，4GB GPU、约2GB余盘。没有下载权重、另建训练/推理平台或自动启动云作业。FoundationPose及openpi输入/运行约束见文档。
- 下一owner=root：恢复原GraspGen-X可运行位置，配置可见货物的固定相机，用真实图像选区/分割与深度生成可见点云，复用原候选/IK/OMPL做单次抓放，再进入原配送owner。当前后向停靠相机并不证明货物可见；先不跑几十单面板，不以ideal回退冒充视觉。
- 清理：所有本轮native/prepare临时场景由TemporaryDirectory退出回收，renderer线程在测试中确认退出；没有常驻仿真实例、逐帧图像日志或大模型下载。开始约2.0GiB可用，收尾2024951808字节；全盘变化含其他任务，不据此报告本轮回收收益。旧场景、模型来源和失败/成功原件保留。
- knowledge_status=already_covered：采用Wiki/ROS2 与 FishBot第19/20节的真值隔离、同源时间和分层验收；本轮运行状态及模型缺失留项目，未另写知识状态。SpecMesh三文件和PROJECT入口已同步；源码语法、diff与本地链接检查通过。

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

继续查询GitHub原run40111818800，不重新派发。M2显式实体查询与第二货物真实抓取分项已通；独立货位卸货分项、原owner/Workflow/Factory/命名独立评分及逐帧臂速度已接；下一步核实新场景运输配置与算力，验A卸货臂，再跑无reset B/B与B/A。M1继续补原Graceful预测碰撞前的原生轨迹/局部地图证据；probe-c已复现支撑波动，不重复低速阴性探针。原120秒/GoalChecker/独立评分保持，取得合格R2后跑正式5+5/留出/完整B→A。M2/M3及矩阵/原生CI范围不缩减，本目标保持active，root继续，不联系其他对话。


## M2 owner 接续结果（2026-10-25）

原 Bridge/Workflow/Factory 已接显式 cargo/arm/station、独立 shelf cell、有限库存、清理后新源帧再次核验与无 reset 接单。新独立 Oracle 按货物订阅真实 ROS 位姿，并与原物理/Clock、完整夹取/运输/卸货评分交叉核对。当前只是代码和已列分项完成；M1–M4整体仍 active，正式无reset B/B、B/A、M3和M4原范围不缩减。

本轮完整反馈 m2-feedback-owner-a 为1855项通过（1098/22/209/61/465），无失败/跳过。B/B公开dry-run为0 ROS/0 POST、540单单/1360整轮，原360装运/120路线/默认旧360与1000保持；新增180只属于卸货。历史定向测试不与本轮计数叠加。私有原型和早期夹具失败保留，见findings。

冻结后第一 cell b 和保留已交付 cargo_1 的第二 cell fixture a 独立评分均通过；源起止一致、禁碰/reset0，逐帧原生臂速度已记录。第二轮57230步/5623帧，支撑落稳1.52源秒、双指0、最大臂速度1.792e-5rad/s；第一货物全样本仍在自己的 cell 并有货架支撑。这是两个独立新初态 fixture，不能拼成连续两单。第一开发轮a源码变化，因此不追认为冻结通过。

165静止真实ROS烟测匹配两件货物各194帧，位姿/四元数差0，保持/同世界/同episode/reset0/禁碰0；owned进程与context退出。命名发布端GID核验仍未加入；烟测退出后endpoint为空，不冒充活动发布端证明。B/A新增第三台臂的43/40/22模型公开prepare、1000步静置及A/B完整几何预检通过，A实际卸货和完整路线仍未验。

接续 owner=root。最短入口为 docs/FACTORY_DELIVERY.md“有限库存与连续配送”，两组entities/orders JSON已入源；私有准备场景 m2-prepared-slots-a、m2-prepared-ba-a。当前准备场景为默认NavFn/source定位构建，尚未按合格J100运输配置完成新工位路线验收；不能仅去掉dry-run就宣称复用了旧K。先核控制配置/算力与新场景路线，再执行原Factory的B/B、B/A，并保留原预算及独立原生终态/卸货评分。原GitHub40111818800本轮读回仍queued，没有远端CI通过证明。


本轮知识回写 knowledge_status=updated：既有 Wiki/ROS2 与 FishBot.md 第20节补“连续配送的独立货位、命名独立观测及清理后新帧更新库存”；开发知识入口补货位占用/清理后回执触发词，原段落与入口各唯一读回。知识仓其它大量未审改动保留，未整库提交；后续整合 owner=root。

本轮清理已执行 m2-owner-cleanup-a.json：开发 cell1-a 全目录归档并读回原 source_unchanged=false/物理判定，移除展开副本；采用 cell1-b、cell2-occupied-a 的原采样以 gzip 保存并读回帧数/末源时间，移除展开 samples.json。独立 scorer 已支持压缩原件，压缩后复算仍为两分项通过。选定模型/XML依赖、R1状态、当前源码和失败证据保留。目标分配空间218497024→136859648字节，释放81637376字节（77.86MiB）。恢复开发轮：`tar -xzf ~/.cache/fishbot/continuous-twin-20261024/archives/m2-cell1-development-a.tar.gz -C ~/.cache/fishbot/continuous-twin-20261024`；恢复单份原采样：`gzip -dk <fixture>/samples.json.gz`。原生165和全部本轮无ROS fixture进程/context已退出，未启动完整运输或GPU作业，未碰107/114和5191只读页。


本轮有效代码/配置/测试/SpecMesh 已提交 d4e5d395d2b3d9860558738cbc1795daa4966afa 并推送既有 qiaoqiao2521/fishbot-ros2-slam-tools/main，原生 ls-remote 与本地精确 SHA 一致，推送后工作区干净。GitHub身份 qiaoqiao2521/238822818 与目标 owner 已验证；运行时JSONL、模型快照、私有场景/采样/日志和知识库其它变动未入该提交。91处当前文档本地链接检查无缺失。上述交付只覆盖本轮有效实施，不把 M1–M4 或原生双订单状态改为完成。


2026-10-26接续读回：m2-native-b-b-b已结束并完成清理，原任务51a90819-27dd-4516-b419-23dfb2406566失败。装运实际362.544墙秒；路线执行83.196秒时被整单360秒上限终止，不能称路线先耗尽120秒。DriveOnHeading原UUID终态4，入站approach Nav UUID cab4903b53f247b68283683d0124429c终态5，第二单order-a未执行。独立403.48源秒quiet读回通过，实例/API9136已关闭，选定源码起止一致。不可重发原任务冒充恢复。


2026-10-26本轮定向验证：命名Oracle/owner 21项通过；domain167静止ROS烟测两件货物各181个匹配帧，位姿/四元数差0，运行中各唯一GID且与physics节点同owner，hold/reset0/禁碰0，进程与context已退出。只证明发布端和观测，不计动作消费或运输通过。M3根独立force/Physics/checkpoint32项通过，无跳过；实际原场景0.01N·s脉冲和R1/R2受力边界成立，ROS实时Goal绑定仍缺。

原B/B证据218538行/467354404字节已以gzip无损归档，逐块读回与原字节一致后移除展开件；分配467361792→51322880字节，释放416038912字节（396.77MiB）。压缩后由原Oracle直接重算，phase_evidence和wall_budget与展开件复算一致，整体仍false。原结果、输入、模型、源文本、真实hold快照保留。原件恢复：`gzip -dk ~/.cache/fishbot/continuous-twin-20261024/m2-native-b-b-b/order-1/observer/observer.jsonl.gz`。清理回执m2-native-b-b-cleanup-a.json。

knowledge_status=updated：原Wiki/ROS2 与 FishBot.md第20节补“成功前缀为空不等于观测缺失”和“剖析插桩耗时不能当原始耗时”，开发知识入口同步成功前缀/插桩触发词，两段原文与入口各唯一读回。其它知识库未审变动保持，未整库发布。


当前源码完整反馈m2m3-feedback-query-a为1865项通过（1108控制/22检查点/209任务/61自治/465前端），0失败/0跳过；新的force17和Physics8原生检查另由根显式运行，不能把重叠32项再累加成全套数。91处本地文档链接无缺失。query_placement实际held快照子进程10.096墙秒，原8段/345退出样本及所有计划字段一致（仅排除进程回执和两耗时字段）；owner检查504次、最大间隔22.35ms，子进程已退出。它证明规划与取消检查能力，不证明完整业务提速或运输成功。

下一步root在本对话冻结源码，以原m2-k-b-b-a场景、domain166/API9136执行新的B/B，不重发旧任务；原360/120及独立卸货180预算不变。完整B/A仍未派发。M3实时原生UUID/阶段交接、故障安全评分/前5秒留存/SoC与M4全部原待办保持。GitHub原run40111818800本轮读回仍queued/conclusion=null，不重复派发或记远端通过。


有效实施已提交734550b38ef555fd2f2ccd651b7eea01479bd1cb并推送既有qiaoqiao2521远端，ls-remote精确一致；提交后工作区干净。GitHub有效身份qiaoqiao2521/238822818和目的仓owner已读回，第一次user API超时后单次重查成功，未更改网络/认证配置。私有原始记录与知识库其它改动未入提交。

新B/B m2-placement-process-b-b-c已结束，原任务585b47b3-1811-4971-9fc5-6137730eaf21、episode cae2d10e-5922-476b-99f9-8a6b241dc93a，Nav原UUID b829949de6774efab66ffddf1fe59eaf终态5，DriveOnHeading 4b4120e614184ecc937825f605564b3e终态4。第一进场点未完成，最终真位姿(1.26044,-2.15578,1.75735rad)；路线120.01777秒失败，第二单未派发。协调器退出143且没有标准result.json，不能补称标准Factory完整验收；原recovery.json保存实际接管和清理、原始observer score保留。root回收原任务的原生终态、连续quiet与新增源时间1秒，保护服务快照不变、owned descendants空、9136关闭，selected_source_unchanged=true；返回码未知的借用observer不伪造exit0。恢复marker时间仅为接管观察上界，不当作精确终态。

协调器SIGTERM最小修复：CLI把该信号转换为现有run异常，让原任务取消/清理链能展开；无新重发或调度器。真实子进程信号测试确认进入原finally、报告unknown并退出2，而非直接丢弃；与原Factory/continuous/policy共49项通过。报告/owner/信号组合24项通过；它们与1865完整反馈有重叠，不合计。未以此声称新的ROS SIGTERM整链实跑已验。

新C原observer260567行/573124982字节gzip无损读回后移除展开件，分配573132800→61140992字节，释放511991808字节（488.27MiB）；本轮两份原始流共释放928030720字节（885.04MiB）。归档及原件恢复记录m2-placement-c-cleanup-a.json；原路径加.gz后使用`gzip -dk`恢复。当前所有本轮owned native/observer均退出，私有输入、原始失败、source、held快照、采用模型和必要对照保留。

下一步root：先用新C原计划/反馈/局部碰撞轨迹，区分大底盘到进场点的定位误差、恢复转向与实际路径跟踪；优先prepare检查点/载货切片，避免重复完整抓放。协调器回收修复已局部验，后续正式长任务需再验证真实信号清理。没有因该失败缩减M1–M4范围或放宽原评分。


接管后压缩原件的m2-placement-c-recovery-replay-a独立复算仍false：21322有效命名样本、命名发布端checked=true，装运第一终态观察291.82777秒、成功到站前缀0，路线120.01777秒。426.85050秒仅是包含迟到接管marker的整个观察窗口；不再误标为装运超360秒。报告局部修复后23项Oracle/owner通过、含真实SIGTERM的组合24项通过，Factory/continuous/policy/信号49项通过；完整1865项对应734550b冻结实现，最后两项局部修正未重复全套。knowledge_status=updated再补原第20节“接管marker迟到”一句，入口同步，原页与入口各唯一读回。


2026-10-27 J100进场接续：所有五轮短路线均未通过，最新noise-b虽无载货违例但物理位移不足；root下一步读取MPPI逐critic代价或做有界原生短查询消融，停止同类盲调。私有对照候选不作为默认；完整B/B、B/A未跑。knowledge_status=updated：原Wiki/ROS2 与 FishBot.md“差速进场”及开发知识入口已补折返裁剪、恢复速度分层，并逐项读回。知识库其它未审改动保留。

空间收尾：五份短路线原始observer JSONL均gzip并与原流逐块比对无误后移除展开件；分配合计1050296320→207020032字节，释放843276288字节（约804.21MiB）。证据可由现有Oracle直接读取.gz；若需原格式，`gzip -dk <observer.jsonl.gz>`。失败日志、私有fixture/配置、独立评分和采样缺口均保留。只关闭本轮查询启动的domain168 CLI daemon及本轮owned进程；9138已释放。


2026-10-27 本轮空间回收：短代价两个observer流分别无损压缩释放29351936/63963136字节，后续完整路线与yaw短测分别释放174522368/95207424字节；卡点采集流释放129822720字节。每份gzip逐块比对后才删展开件，现有Oracle可直接读取；恢复 `gzip -dk <observer.jsonl.gz>`。快照、模型、固定路径、原始失败、短测观测和代价记录保留。独占168/API9138实例与本轮查询进程已退出，端口已释放。

knowledge_status=updated：既有 Wiki/ROS2 与 FishBot.md“差速进场”补MPPI速度反馈归零和固定FollowPath的载货参数边界，Wiki/开发知识入口增加触发词，原页及入口均已读回；其它知识库改动保留。


2026-10-27 本轮空间收尾：三份固定路径观察流逐块比对gzip后删除展开件，分配410603520→110497792字节，释放300105728字节；恢复 `gzip -dk <observations.jsonl.gz>`。原动作/物理报告、代价文件、10档原始采样、快照/路径和失败记录保留。所有本轮隔离实例已停止，端口9138已释放。

knowledge_status=updated：既有 Wiki/ROS2 与 FishBot.md“差速进场”补卡点小角速和Shim/MPPI交接，Wiki/开发知识入口加触发词，均已读回；其它知识库改动保持。


## 2026-10-28 J100宽场景已接入，完整配送待运行

实现：可选--arena-xml已接既有prepare/build_scene，新增j100-wide场地、车型/传感器、订单目标及连续实体四份配置。原窄场地/默认配置保留。J100后续正常业务验证入口改为docs/FACTORY_DELIVERY.md“J100宽场景”，完整两单仍复用原Factory/Workflow和continuous-ba-orders。

验收：新增4项原生场景测试通过；原厂区场景/连续任务回归22项通过，0失败/跳过。新场景43qpos/40qvel/22ctrl，1000步静止禁碰0。真实ROS170/API9140三次规划均status4，完整几何扫掠和120秒预算估算均通过；保留408条物理观察全部hold，未发运动Goal。完整B/A dry-run已接受新的实体绑定和订单顺序，未实际派发；完整载货/卸货/无reset双单继续pending，owner=root。下一步从独立新输出目录运行原Factory，不复用旧失败UUID。

证据：~/.cache/fishbot/j100-wide-20261028/，scene/为实际世界及地图，native-plan.json保留三UUID/路径/原生状态/扫掠/预算，geometry.json保留静态边界，factory-dry-run.json保留两单声明；tests.log/regression.log为4+22项，j100-wide.png为实际新模型渲染。初次import失败保留native-plan.log，成功复跑日志native-plan-b.log。只查规划与静置，未称新的完整配送通过。

清理：owned原生18个身份均已退出，survivors=[]，API9140关闭；没有动107/114等旧实例。原生场景测试TemporaryDirectory已自动移除。未开启完整physics日志，本轮目录约1.7MiB，保留必要场景/截图/短日志和脚本，不产生大型训练或渲染缓存。磁盘仍约6.7GiB可用。knowledge_status=already_covered：Wiki/ROS2 与 FishBot“差速进场”已覆盖完整几何/宽处转向/预算与完整任务分层，本轮场地状态仅回写本项目。


2026-10-28 用户要求实际运行宽场景B→A：root已派发 full-ba-a，独占170/API9140、原Factory连续模式、原360/120/180预算及物理评分。使用已验证的scene/scene-manifest.json与native-current-goal overlay，原.06/.10载货限速、默认25mm全局附加缓冲；无新参数调优。结果进行中，未计通过；原始输出~/.cache/fishbot/j100-wide-20261028/full-ba-a，接续只查询该原run，不重复派发。

full-ba-a在protected_snapshot连接用户systemd bus时退出，发生于任何world launch/start之前，无动作；本会话缺XDG_RUNTIME_DIR/DBUS_SESSION_BUS_ADDRESS。实际/run/user/1000/bus存在，显式传入后原保护单元身份可读。新full-ba-b沿用同输入/预算重新启动，a记录保留；不是重发已接受任务。


full-ba-b实际Dock过期取消，full-ba-c完成抓放/出站但支撑丢失失败；两轮均未执行A，原任务和原生UUID、独立评分与清理回执保留。详见findings。现只补观测双龄诊断与prepare对既有terminal_stop_heartbeat的显式入口；103项BridgeRaceTests和4项原生场景检查通过，无门槛变更。

full-ba-d使用scene-terminal、原170/9140和原B→A owner，task 5576f001-f38f-4dbc-bbc8-ba5cadd905d2；原输出不覆盖，结果进行中。B/C完成流gzip逐字节回读后删除展开副本，分别释放6053888/203268096字节，恢复gzip -dk <observer.jsonl.gz>；原评分和模型保留。


## 2026-10-28 B→A实跑收尾：B跟踪已证明，完整双单未通过

- D：task 5576f001-f38f-4dbc-bbc8-ba5cadd905d2，B路线49.857384墙秒，原生Nav 7269a222137d45bda02eec46bb4c75d4终态4；独立末XY29.498mm/yaw.015381rad，原装运K通过。924条transformed_global_plan、949条非零nav速度及2.549m真位移证明实际计算/运动；活动窗2387样本支撑失联0，序号缺口4处。卸货上方准备点IK失败，整任务仍false，A未执行。
- 工位修正：prepare已显式暴露原terminal_stop_heartbeat；卸货站可配置pickup_xy_m，默认原(.24,.14)不变。宽场景采用(.24,.04)，两站各沿-X平移.10m；实际D快照的原5段抓取查询solved。6cm候选未覆盖4cm误差八方向，不晋级；10cm候选5项原生场景检查通过，另有15项多实体和103项BridgeRaceTests通过。上述合计123个不同测试，不把重复运行累加；未重复全仓前端/反馈回归。
- E：task 987c4d9f-d81c-4fc6-a2bb-9d20af67835c在停靠源龄.30秒失败，接收龄.353秒。独立传感器仍50Hz，HTTP组装峰值与配对空档共现，因果未定。
- F：同源码/输入复现，run 1e3eeddb-dcf6-4a2f-ba2f-e6ed9d7ccf24，task 1c184d60-bafe-41b5-ae9c-aa07862f84fb；已抓放出站，路线26.7257秒因共享物理反馈时间失效终止。Drive d90b93a0011947d5b9c61945cc9fb838状态4，Nav 23fa75de8f7e495b85176696d6412b49取消5。清理窗最后失败证据clock216.96、physics217.30，源龄-.34秒，接收龄.00204秒；它是清理时再次观察到的异常，不能冒充首次中止时刻。hold/连续静止/guard关闭与参数恢复已确认，A未执行。

E/F不放宽时间、碰撞、载货、速度或评分；没有继续盲重试。D理想停车保护触发.78源秒，F .86源秒，不能称无保护辅助或视觉/真机成功。D/E/F选定源码起止一致，owned_process_survivors均空，9140已关闭。旧107/114未操作；保护配置单元前后一致且均not-found，只证明该集合不变。

证据入口：~/.cache/fishbot/j100-wide-20261028/full-ba-{b,c,d,e,f}/result.json、order-1/observer、runtime/tasks/task.json；full-ba-d-controller-evidence.json记录控制活动窗；unload-failed-physics.json为实际D终态快照，unload-margin-query.json为其新工位静态查询，不是运行快照恢复或新配送成绩。scene/、scene-terminal/、scene-unload/（未晋级6cm）与scene-unload-margin/分别保留。

knowledge_status=already_covered：已读回Wiki/ROS2 与 FishBot的原生终态新零目标、差速进场及第20节分层验收；本轮时序根因未定、卸货仅静态修正，有限场景结论留项目，不写成已验证通用修复。下一owner=root，最短接续见task_plan末节。

收尾核验：D/F以原observer重新运行独立Oracle，整项仍false；passed、原K、目的地、业务评分和保护遥测五组字段与现场评分逐项一致，回执replay-comparison.json。93个文档本地链接无缺失，git diff --check通过。五份B–F原始流逐块核验gzip后删除展开件，分配900354048→148467712字节，释放751886336字节（717.05MiB）；保留原模型、失败快照、原始压缩流、评分、短诊断和未晋级配置。恢复gzip -dk <observer.jsonl.gz>，不会重启任务。全盘可用约5.38GiB；只统计本轮文件的实际回收，不将其冒充全盘净增量。


## 2026-10-29 完成：修接纳/接收调度，宽场景连续B→A通过

实现：保留标准TimeSource，将其订阅移到专用接收Node/executor；销毁/参数切换继续走原生命周期。工位两DDS输入depth5匹配原同步器queue5；新增有界callback入口最大间隔诊断，原源龄/接收龄、碰撞、载货和评分门槛不变。完成后补接收线程异常原生Task转发与done唤醒，使无其他输入时也能进入主流程清理。

原生验收：full-ba-g/run b8dc8641-77e6-4bc3-b32c-822767b011f0，原170/9140、J100＋3D雷达宽场景、原SO101与Factory。B/A两单各自命名货物原K、实际抓放/装运/卸货/回位/停稳评分均通过；原生载货Nav终态4，路线48.781/19.263墙秒，位置误差28.044/21.291mm，偏航.028485/.020467rad。总889.584墙秒；39940独立物理样本证明同world/episode、reset0、源序推进，start2/cancel0/reset0。两单末freshness_failure均null。

边界：这是一次宽场景完整B/A通过，不是全计划、旧窄场地或长期稳定通过。启动期clock/physics最大入口空档.325/.347秒保留；没有找出全部底层调度停顿的唯一来源。理想停车guard两次各约.8源秒；不宣称纯视觉/真机。A旧primary cargo_1的顶层K仍false，活动cargo_2按命名物理原K通过，旧字段未篡改。G执行源码起止一致；异常转发补丁在G结束后加入，以生产MultiThreadedExecutor无后续事件原生注入验证，未重跑完整两单。

测试：BridgeRaceTests105项通过；既有check-feedback1869项（control1112/checkpoint22/mission209/autonomy61/frontend465）全部通过，无跳过；其中已包含桥接回归，不重复累加。另3项实际ROS测试通过：停用control executor仍更新时间及参数切换/回跳；DDS错位缓存depth1零配对/当前depth5四对；接收异常晚于主executor首次扫描且无其它ROS事件仍能传播。两份压缩原observer独立重放仍passed，passed/原K/delivery/business/guard五组结果与现场逐项一致。只读Qoder超时未改文件，内置审查发现异常传播缺口，已修并用实际MultiThreadedExecutor补测。

证据：~/.cache/fishbot/j100-wide-20261028/full-ba-g/{result.json,verified-summary.json,replay-comparison.json,archive-receipt.json}及两order/observer；root保留原任务/UUID和B–F失败。原生运行owned_process_survivors=[]、API9140关闭，原生测试171也已退出。只核既有保护单元快照一致，未触碰107/114或宣称它们仍运行。

空间收尾：G两原始observer逐块核验gzip可还原后移除展开件，释放958377984字节；另6份已结束旧连续/麦克纳姆observer归档释放412561408字节，合计1370939392字节（约1.277GiB）。保留场景、快照、源记录、markers、独立评分与失败证据；恢复gzip -dk <observer.jsonl.gz>，索引分别为full-ba-g/archive-receipt.json与cleanup-20261029.json。本轮早期全盘约1.1GiB可用，收尾约2.7GiB；全盘受其它工作影响，回收量以本轮文件分配块为准。没有清理未知/运行中模型或环境。

knowledge_status=updated：已将独立executor的边界、标准TimeSource生命周期、双层队列配对及MultiThreadedExecutor异常唤醒经验补入Wiki/ROS2 与 FishBot“原生 ROS 时钟与回调组”，开发知识入口同行已补触发词，并读回验证。当前B/A结果只回写项目，源龄与真实物理证据分层沿用第19/20节。下一owner=root；M1/M3/M4及其它M2分支仍按task_plan独立推进。


## 2026-10-31 模型推理与视觉配送（进行中）

V1/V2已通过agent-link交给Qoder/AGY，范围分别为推理环境与固定工位RGB-D。root新增模型姿态→mink→原OMPL/五阶段执行薄适配，以及渲染生产器与独立推理进程边界；暂未计模型或运输成功。历史候选103在J100宽场景的原查询几何中经新mink接口求得.156mm/.000131rad拟合，约4秒完成原扫掠/路径；这是机械适配测试，输入不是本轮视觉。

后向相机预检第一次因辅助脚本属性名错误退出；第二次默认可见组遗漏业务group4而失检。按实际CameraRenderer的geomgroup全开设置复跑，进场/停靠均有效检测；停靠相对误差约.207mm/.000184rad。未修改生产摄像头或放宽评分，尚未证明运动RGB停靠。图像与原结果保留在~/.cache/fishbot/pretrained-vision-20261031/。

执行接续：agent-link外部Qoder/AGY同步调用超时，确认无产物后分别取消；改用当前会话内置Agent完成同一V1/V2范围。没有联系其它对话。恢复官方代码b9429097与模型7c834043，现有GraspGen-X venv及权重放回原cache入口。Kaggle muqiaoqiao只读CLI核对成功，未派发云作业；30秒原在线查询采用本机RTX3050，避免引入云kernel冷启动。

实际推理：312个RGB-D可见点，固定颜色先验选区、固定工位标定转到Z向上推理系，再将候选还原相机系。官方输出408候选（48扩散＋360 OBB），冷推理总12.717秒、神经推理.863秒，显存峰值584MiB。候选51（OBB，预训练判别分.71622）经mink和原OMPL/扫掠可执行；不是神经分支单独成功。完整离线视觉查询28.583秒通过原30秒期限，尚不等于物理抓起。

single-b-a：原生RGB Dock终态4，随后抓取查询失败。模型report实际17.728秒完成408候选，但新增18秒子进程截止在Python退出时将其截断，任务失败、A未派发。相同输入退出取证实测report15.303秒、进程16.962秒，退出多1.387秒。已移除新增18秒子限制，仍由原整个query的30秒owner截止并回收进程组；未扩大原任务360/路线120/卸货180秒。失败run清理通过、owned survivors空、端口9146关闭、原UUID终态和hold/guard关闭确认。独立物理评分仍false；不将Dock原生成功当作整项通过。single-b-b为修复后新实例，结果待回读。

single-b-b实际在模型查询前失败：RGB观测源龄.26>.25秒，detector各帧均正常、渲染最大39ms/检测最大22ms；相机已产出的755/759两序号未完成视觉同步。原三topic DDS depth1与TimeSynchronizer5不匹配；仅相机三pub/sub改depth5，latest单槽、其它topic depth1和原鲜度阈值不变。受控原生DDS夹具depth1收[1,1,1]/配对0，depth5收[4,5,5]/配对2/3/4，鲜度约.12秒；只能证明这一机制可致漏配对，实际回合修复仍需复验。新增分topic接收与同步计数用于后续区分缺口。失败owned实例清理完成。

机械接触边界：第一次原生probe-a虽规划成功，却压低货物7.58mm、最大lift0；官方OBB以面中心为tip轴，SO101实际PINCH_POINT相对body横偏6mm，直接映射不一致。保留失败；以公开机械坐标建立虚拟模型原点，descriptor两offset_x减.006、extents/depth不变，所有扩散/OBB/判别器共享该坐标，执行边界只做逆变换。probe-b旧51修正后抓起，明确旧score不适用；随后重新官方推理408候选并重新评分，probe-c使用整池排序、新score .774583、report T_body_model且无事后手调，实际lift40.780mm、连续lift≥25mm且双指> .02N为3.14源秒，末双指1.266/1.236N，原五段收敛、非预期接触0。它是单次原生抓起，不是ROS或完整配送通过。

推理时限接续：本机负载波动下冷启动inference-centered-a共26.90秒（模型加载5.16、推理1.91），不足以稳定容纳同30秒内的IK。复用官方GraspGenXZMQServer共享权重，随同一个ROS launch拥有和清理，客户端仍使用官方infer_object全候选协议；不新建通用推理平台，不放宽原查询期限。热推理和正式ROS结果待回读。

knowledge_status=updated：已将“预训练抓取：先对齐夹爪坐标，再验接触”写入Wiki/ROS2 与 FishBot，覆盖可见点云／分支来源／非对称夹爪坐标与重评分／冷启动和退出分层；开发知识入口已增加对应触发词，并逐段读回。这里只回写已实测的机械和推理经验，完整业务结果仍留本计划。

full-ba-c实际未到模型查询：首单e23cd1e3-6138-4939-8c70-740a2191af94在进场时观测源龄.26秒取消，A未派发。新计数显示图像入口195→196、标定／metadata355→359；相机正常产生1387/1392/1397，但大图未进入回调。全程图像250、其它431，说明原depth修正不足；不是已完成图像在检测器计算过慢。失败回合57.443墙秒，清理、API9146／模型10146关闭、owned survivors空、选定源码起止一致。

新增实际负载传输对照：921600字节640×480 RGB、20Hz、每组80帧、原异步发送。BestEffort baseline入口65/80/80、受控暂停59/80/80；RELIABLE两组均80/80/80且同步80。可靠组最大源龄.0387/.1365秒、过期0，最大发布3.51/.80ms；受控暂停后latest单槽保留最新，未把队列当指令缓存。只将相机三topic改可靠depth5，其它传感器QoS及原.25秒接纳不变。实际业务效果仍待full-ba-d验收。

full-ba-d：原单B task69e90c4a-c42b-4f53-ad08-25bcda9184fe完成RGB Dock、实际模型查询与双指抬升、托盘放货；在回位后的连续交接确认失败，A未派发。实际抓取输入312点、全部408候选，新51/OBB分.774583；模型owner1.823秒、完整query17.690秒，原30秒保持。相机三个入口与同步均3103帧，检测最大源龄.100／捕获龄.112秒，无station_freshness_failure，真实负载相机修复在该有限回合有效。

D失败不是时间门槛：末8秒371个唯一物理样本全部不满足handoff，机械臂已回位，货物实际落地。151.36源秒仍有固定pad压货物的5个接触，法向Z约-.9976，固定指7.47N／托盘7.53N；随后的OMPL侧摆把货物拖离盘，约155秒落地。假设沿-X脱离经接触法向检查否定，未执行；先垂直反走原最后下降段再OMPL回位作为有证据的候选，不扩大接触/支撑门槛。D209.031墙秒，cleanup与两端口关闭、owned survivors空，选定源码起止一致；保持failed。

释放修正原生证据：release-diagnosis-d取151.36源秒实录qpos/qvel/ctrl及参考量作R0重建；未保存warmstart，不称精确R1重放。原OMPL退让复现落地、最大货速1.84m/s、交接0秒；开爪后反走原竖直lower，再OMPL回位，维持托盘完整足迹/实际支撑、双指0N、回home，原transport_handoff_ready连续5.18源秒、最大货速.00650m/s、forbidden0。仅pretrained模式采用；前缀及组合路径重新按原open_checker1mm/.01rad检查，仍合并同一个retreat段、原segments计数不变。非竖直末段复用原IK与41mm standoff；没有调接触或交接谓词。7原生模型/退让与11查询进程检查通过。full-ba-e将验证完整B→A，尚未计成功。

阶段清理：A/B/C三份已结束失败observer逐块核验gzip还原字节后移除展开件，释放66.391MiB，回执cleanup-ended-failures.json；原输入、模型候选、失败报告保留。D仍保留展开供释放问题取证，待本轮最终收尾归档。


### 2026-10-31 E与回归复核（接续，未计完整配送通过）

E/order-1任务ec77104e-e700-4ac1-82a6-3d442a53cfb7在原30秒接近查询预算内超时，A未执行；官方模型已返回408个候选，热推理owner耗时2.897秒。与D相比，可见312点、408候选姿态/分数/来源全部一致，初始关节差约1e-7rad，但实际停车位置相差约1.62mm/yaw约.00103rad，因此几何影响仍须短对照，不把负载当成唯一根因。真实producer墙钟映射显示D/E查询事件至RGB落盘分别7.839/15.487秒；E模型报告前已耗约19.085秒，旧日志不足以再拆分前半段。原输出与失败保留，owned清理通过，模型端口和API已关闭。

root此前将全回归与E实时任务并行，排程不合适。后续串行运行；不停止其它项目，不放宽30秒查询或碰撞/接触/载货门槛。已给候选筛选补原子小型阶段journal（IK/预抓取/OMPL），可选记录写失败只警告，不改变候选数学或执行。

反馈回归首次control1116中一项夹具错误：旧fake Popen不支持新无start清理分支的ps调用。已在该夹具mock原stop_owned_launch并断言调用一次；policy10项通过。修后control1121项全部通过、零跳过（包含新增5项推理合同）。首次其余checkpoint22/mission209/autonomy61/frontend465均通过，无跳过；这些与修后control共1878项，不重复累计。另推理+工位CPU合同6项通过，原生camera/station16项通过。当前完整B/A仍pending，owner=root。


### F：实际模型交接通过，载货Nav入口接收饥饿（保留失败）

F/task303e24e8-2238-4e86-87f2-9fab6314a425，episode95575302-d90d-4f7d-a73c-15584c39509f：RGB标记停靠后，以312个可见点重新进行官方408候选推理；选中OBB候选51、预训练判别分.77458322，原接近查询18.184秒。真实双指抬升、托盘放置、竖直清离与回位交接均执行通过；载货DriveOnHeading终态4。载货Nav UUID77d2d4aeffef42baa1b701809c22dac8已接受，随后因桥接物理反馈中断取消至5；任务unknown，A未执行。原Factory清理证明未通过，结果不重写为成功。

独立取证：source209–220连续550个physics/551个clock，producer最大间隔22.87ms、observer接收最大41.79ms。桥接physics入口最大空档.8995秒，缓存锁等待最大32微秒、提交最大2.17ms；原源龄保护记录clock212.06对physics211.66的.4秒差。恢复包新鲜，缺口发生在进入主执行器回调前。支持主执行器接纳饥饿，不将HTTP慢事件相关性当作唯一根因。证据full-ba-f/readonly-feedback-window.json。

root独立收尾：原Nav终态已知、60帧跨1.18源秒均hold/停稳/guard关闭后，复用stop_owned_launch发送SIGINT；survivors=[]、9146/10146关闭、observer完成。root-reconciliation.json只证明安全资源收回，不改变原任务unknown和评分失败。

最小修复仅将/cooperation/physics_state订阅路由到现有clock_receiver执行器；原BEST_EFFORT depth1、标准TimeSource、源龄/接收龄、速度及物理门槛不变。新增原生测试故意不spin主执行器：旧路由40帧收0而失败，新路由持续收到末帧；四项实际ROS时钟/接收测试全部通过。相关BridgeRace105+原query11=116项通过，mink/退让原生7项通过。G在新独立输出、同场景/订单/预算启动，未计通过；运行时不再并行重测试。


### G：载货导航已通过，视觉卸货转运滑脱（保留失败）

G/task4acad401-61cb-49aa-916d-0bb65933443f：修后桥接鲜度失败为null；RGB停靠、模型装货抓取、实际放盘/清离/交接、DriveOnHeading与B载货Nav均通过原生阶段。B Nav UUIDfdf08a0a57024aaf8f536117805004f8终态4，末位置误差33.453mm/yaw.005895rad。B卸货用新的210点可见RGB-D推理408候选，选择99后实际双指抬升得到确认。

随后货架释放前的原连续确认失败，任务和独立评分仍false，A未执行。source398–414的独立记录表明cargo_1已落回原车载托盘、双指力0、trayforce.0981N，不能解释为货架gate过严。此前实际抓持姿态wrist_roll约2.2768rad；原source solve_pinch_ik显式偏好q[4]=0，转运姿态突变为当前待验证假设。root已派当前内置Agent做原始掉落时刻取证与有界R0对照；不放宽评分或故意跳过货架验收。

G原Factory清理通过，owned survivors=[]、API与模型端口关闭，原源码起止观察保留；输出full-ba-g。最短下一步是先验证搬运时保留实际抓持方向的薄适配（mink＋原载物checker），再由原Factory运行新独立回合B→A。


### H前局部修复验收与完整接续

G滑脱首次双指失去为source365.60，原IK将腕角2.2768rad拉向0；实际cargo-PINCH偏差仅(+2.973,-.653,-8.488)mm，不需改货架槽或门槛。新增候选声明放货端点的mink IK检查：候选99以48.62mm/1.164rad端点误差拒绝，仍按原池排序接纳候选57、原分.75156不变；使用候选姿态的标签为proposed，实际搬运保存measured方向。端点检查明确kinematic-only，完整原载物路径和物理仍另验。

原G的210可见点／408候选冻结输入，在原pregrasp244.92帧的R0重建中完成候选57五段实际抓取、40.69mm抬升、持货转运、货架释放、竖直清离与归位：before-retreat原gate连续3.96源秒、最终shelf/home连续2.98秒，双指0、禁碰0。没有求解器warmstart，不称精确回放或真实ROS成功。原load51的79.68持货帧也完成同原完整转运／托盘释放／归位，handoff连续2.98秒。卸货初始化4.55秒、候选5.52秒、placement10.61秒；装货init4.60秒、placement9.46秒；端点筛选3候选累计约.06秒。证据unload-preserve-h/{unload-result.json,load-result.json}。卸货probe早于仅改措辞的metadata修正，旧receipt的measured标签不是实测承诺，数值／行为未变。

相关native_model_grasp8＋原query11项全通过；未改官方rank/score、几何、plant、时间、碰撞或物理门槛。H由root独占176/API9146原Factory新输出full-ba-h启动，原B→A同world订单，不重用G任务。当前未计完整通过；模型／ROS测试与H不并行运行。

knowledge_status=updated：原Wiki/ROS2 与 FishBot“预训练抓取”“放货退出”“原生ROS时钟与回调组”补模型夹爪坐标、后续操作原语姿态/机械限位、竖直清离和physics入口饥饿边界；开发知识入口相同行触发词已更新并读回。只沉淀经原生验证的可复用判断，H业务结果仍留项目。


H第一单B已由原独立评分通过：task4e336deb-9b79-4131-a373-0aa9374eb3a9，episode3f1a19b1-e58a-44ef-a2e7-26f3783bf922，401.799墙秒，载货路线48.1957秒（原120秒），末XY33.225mm/yaw.013464rad。装货312点候选51、到站新229点候选85，均由原官方全408池/原分数筛选；实际完整装卸、原K及业务独立评分均true。随后同world无reset启动第二单A/task7fc70b3c-c4a8-4038-a1fd-00a495396217，当前进行中，不把第一单通过写成整轮通过。

最终只读审查：当前标准路线坐标、实测R、官方分数及生命周期无阻断；非竖直/单点自定义撤离仍是原upright fallback，未纳入本轮证明。旧report.kind保兼容，orientation_policy明确measured；此限制已写docs，未在H中途改源码。

### H第二单失败与参考发送节奏修复

H整轮仍失败：A/task7fc70b3c-c4a8-4038-a1fd-00a495396217以新291点输入选择候选87、原分.77662897，双指抓取和抬升成立，source588.28在持货转运中滑脱，最终落回取货台，原释放gate正确拒绝。B的通过不替代A。原Factory清理通过、端口关闭；完整失败保留在full-ba-h。

以H/source586.72的R0重建、原201帧/105条实际reference发送记录作有界对照：原记录重放在同source588.28再次滑脱；同路径、同发送时刻，仅将参考弧长推进限制为原.3rad/s乘min(源间隔,.02s)后，4秒运动＋2秒保持中双指未失持，最小双指力.92949N。82/105次推进被限制。它验证的是该局部转运窗口，不是全路径或完整任务。证据load2-diagnosis-h/{recorded-recorded-replay.json,capped-recorded-replay.json}。

轨迹参考投影到原重建路径的残差约1e-14rad，实际发送会落后20/40/80ms后追赶；更严格IK精度没有改变任何路径点，已撤回，不能记为修复。规划起止快照抓持方向仅差2.63e-5rad、货物相对漂移.0769mm，现有证据不支持将快照陈旧列为该滑脱的唯一原因。

薄修复仅作用于预训练视觉分支的lift/transport/lower：保持原几何路径、夹力、速度、源龄、段内时限和整单预算；不补发漏掉周期，末端实际到达后再计算原dwell。默认ideal与自由接近/撤离保持。新增实际Bridge.segment跳帧推进及重复源帧检查；相关BridgeRace＋原query共118项通过，无跳过。I轮在原场景/订单/176/9146的新输出full-ba-i独占运行；未计完整通过，所有重测试与仿真串行。

I整轮未通过：885.432墙秒，B/task601ed79c-5508-44ea-9ec3-0a8d1cee118e完整原K/业务评分通过；B路线48.73865秒、末30.947mm/.024884rad。A/task8510851a-7d3c-49af-bb35-d0e2a6bb258a仍选候选87，原滑脱段已完成，货物实际放盘/清离/回位后运到A；路线与到站物理评分通过，末20.811mm/.009636rad。新226点卸货选择候选85，实际双指抬升与转运后在source844.32触发原实际臂位姿1mm碰撞余量检查，未计货架交付成功。原生禁止接触累计没有因此改写为通过业务；接续先核具体几何对、开爪中间角和实际/reference差异。

I两单同world756e2553-9f69-4343-b617-c66cbd2654fd、episode49730297-debc-475d-bba8-2797dca84c8e，2start/0reset/0cancel；39862个独立物理样本保持源推进。源码起止一致，Factory清理、全部owned进程退出、两端口关闭和原实例保护均通过；失败及原记录保留。当前根Agent处理收尾与碰撞诊断，内置visual_grasp_review仅做同帧离线有界对照，不运行新完整ROS任务。

I最早离线无效帧为source843.30，实际jaw=.1921956rad，pad_moving_jaw对frozen__unload_line_a__pick_wall_x_1距离.95018mm；前五轴误差约.00053rad。冻结原计划末端也在jaw=.19063786rad（第88/244点）失效，全开端点又有效，确认漏验开爪中间角。现在复用原configuration_sweep，在候选声明端点与实际持货placement终点检查完整.015→.5扫掠；原1mm及.005/.002rad采样、模型排序/score、几何和预算保持。错误信息补具体碰撞对、距离与原因，不再只报泛化文字。

原I的226可见点／完整408候选冻结池：85按新预检拒绝，原排序继续选择97，原分.635462保持；planner初始化5.42秒＋候选10.33秒，未超过原30秒接近查询。以source709.02预抓取帧R0重建，实际完成双指抓取、40.773mm抬升、声明转运路线、开爪、货架落稳、竖直清离和OMPL回位；before-retreat连续3.94源秒、最终shelf/home连续3秒，实际q6原1mm均通过、禁碰0。私有实例关闭。证据unload-collision-i/diagnosis.json；仅局部原生物理，不计完整ROS成功。

新增“端点均有效但开爪中段碰撞”“按原rank跳过不可释放候选”的行为回归。native模型10＋原query11=21通过，随后BridgeRace107通过，无跳过。J轮新输出full-ba-j、原场景/订单/176/9146独占运行中，未计通过。

J仍未通过：986.029墙秒，B/taskb6641fbe-20d3-4592-89bf-19b815183bd0完整独立原K/业务通过，路线51.42229秒、末29.601mm/.016002rad。A/task2b09f4b6-f218-44a6-9830-157f90a36ff8的新230点选择97，实际抓取/放架/清离/home已执行，source935.80发出unloaded；最终清理后的新帧确认在937.56超过原180秒卸货deadline，终态failed，不能改判完整配送成功。A末21.054mm/.025731rad，物理完成与任务期限失败分别保留。原源码起止一致、2start/0reset/0cancel、Factory清理通过、survivors=[]、两端口关闭。

接续只检查原接近规划是否有可省的无载绕行：当前官方RRTConnect适配保留原树路径、不作simplify，即使直达关节边可能有效仍调用随机树。先用J原冻结输入和现有validate_joint_path/.005rad/1mm验证直达，证据成立后才复用该已有路径；不移动deadline、不省略清理或连续停稳，不放宽速度/碰撞/评分。

J同source756.80／230点池的候选97：原RRT路径4.808396rad、标称30.05248源秒，重建到实际reference投影残差2.24e-14rad；同起终点直达1.521132rad、标称9.50708秒，原1mm/.005rad检查306状态全部clear。直达验证.630墙秒，原OMPL查询4.019秒。真实壁钟拆分还记录query23.92秒、placement query/刷新26.54秒、放货与退出77.46秒，不把模型.52秒等同整个查询成本。证据latency-j/direct-check.json及timing-breakdown.json。

最小修复仅视觉无载approach优先复用原直达边检查，无效仍回退RRTConnect；持货路径、速度、dwell、清理及180秒期限不改。21项native模型/原query相关测试通过，包含直达/回退及JSON回执；首次native预执行发现np.ndarray无法序列化，已改普通列表并保留该零动作失败，不冒充物理运行。

同J/A冻结输入当前源码完整native通过：直达接近标称9.507秒／实际10.14源秒，期间货物XY变化约7e-12m、双指0；随后实际抬升40.782mm、保持双指1.626/1.637N，原货架before-retreat连续3.92秒、最终shelf/home连续3秒、tips0，实际原1mm及禁碰检查通过。整计划JSON落盘成功，实例关闭。证据latency-j/direct-native-result.json；K轮新输出full-ba-k、原176/9146、同场景/两单/预算已启动，未计完整通过。

## 2026-10-31 K最终验收：模型推理与视觉B→A完成

run a7264eae-5138-4ee7-9e14-1a727d550d57，world6ede1c78-a38e-4b1a-86fb-3ba5a146755b，episode38b64699-d53e-4248-9fe5-5cc88d9c481c。原Factory同一世界执行B→A，2start/0reset/0cancel，41973个独立物理样本保持源推进；958.277墙秒，errors=[]，整体passed=true。原声明每单装运360秒＋卸货180秒、路线120秒、整轮1360秒，均未改动；不把历史无卸货单360秒与本业务阶段预算混写。

| 订单／原任务 | 任务墙秒 | 路线墙秒 | 最终XY／yaw | 独立命名原K／业务 |
| --- | ---: | ---: | --- | --- |
| B／b8e18c78-0a1d-442d-8fdb-8d5269f2b8ac | 448.649 | 49.902 | 31.065mm／.001365rad | true／true |
| A／62e383a7-64c3-4672-bdce-8d3ec8e16662 | 415.055 | 20.968 | 21.215mm／.014968rad | true／true |

四次实际RGB-D可见点为312/226/291/227，候选51/85/87/61；每次官方池完整408（48diff＋360OBB），原分数保留，最终四次均选OBB＋预训练判别分。GPU推理1.096/.625/.500/.503墙秒，RTX3050 Laptop峰值分配584.3MiB，training_steps=0；查询总耗时还含场景/机械初始化和规划。装货两次直达被拒并正常RRT回退，卸货两次直达通过；不是从冻结快照拷贝指定候选或修改模型分数。

原独立评分覆盖同一货物双指抓起/抬升、托盘释放/完整足迹支撑、臂清离/home、载货实际位移、配送目标停车、卸货抓起/货架落稳/清离与清理后的新帧确认。A的兼容original_k_oracle_passed=false仍保留：未投影的旧诊断始终看cargo_1，它此时已在B货架；A实际搬运cargo_2，对应独立命名原K及业务均true，不改旧诊断字段或用网页状态替代物理验收。

root用两个独立score-only进程读取原记录，B/A均passed；full_attempts、旧诊断、目标交付、命名业务、guard及observation_metrics与现场评分逐项精确一致。证据replay-k/comparison.json、verified-k-summary.json和full-ba-k/result.json。选定源码/输入起止一致，owned_process_survivors=[]，launch/API9146/模型10146均关闭，原配置systemd快照一致。

边界：plant停车guard分别介入.80/.74源秒；物理序号缺227/28，最大源间隔.34/.06秒，未补帧。K在第一件持货时出现主机负载/发送空档，相关源间隔与执行节奏原样保留；不把单次通过称为零丢包、纯视觉精度或稳定生产。只证明已声明绿色货物/固定工位仿真，地图/激光Nav2与既有物理反馈继续参与，不外推任意物体、真机或sim-to-real。

验证：完整反馈在早期代码切片已1878项通过（control1121/checkpoint22/mission209/autonomy61/frontend465），不改称最终全仓重跑。后续故障修复分别验证；最终相关BridgeRace107＋native模型10/原query11共128项通过，无跳过，包含直达回退、开爪扫掠和JSON回执。实际ROS时钟/physics独立接收4项与相机DDS对照、原生RGB-D6项等早期证据保持；K运行时未并行重测试。

knowledge_status=updated：原Wiki/ROS2 与 FishBot“预训练抓取”“放货退出”“原生ROS时钟与回调组”及开发知识入口已补夹爪坐标、姿态接续、完整开爪扫掠、无载直达预检、发送节奏与回调饥饿边界，原文和触发词均读回。只写复用经验；本轮成功/失败及原日志仍留项目。知识库其他未审改动保留，未整库提交，后续owner=根Codex。


### K空间与交付收尾

结束并核实无人占用后，G/H/I/J/K共9份observer原始JSONL用gzip归档，逐字节解压对比一致后删除展开件；实际回收已分配空间4042481664字节（3.765GiB）。自由空间前后变化另记，不据此归因其他任务。结果cleanup-ended-ghijk.json；此前A–C与D–F归档记录保持。所有成功/失败评分、模型原候选、RGB/深度/掩码、标定、R0对照和源配置均保留，当前GraspGen-X环境/权重及原生overlay未删除，未停止其他项目。

恢复任一原记录：`gzip -dk ~/.cache/fishbot/pretrained-vision-20261031/full-ba-k/order-1/observer/observer.jsonl.gz`；第二单替换order-2。恢复后可按原score-only或耗时导入命令重算。归档保留原路径，原JSON报告不改写；未声称当前不存在的展开文件仍可直接读取。私有总摘要verified-k-summary.json包含现场/离线比较和边界，原输入图像/深度在grasp-observations对应episode目录。

最终25个改动Python文件AST、84个本地文档链接和git diff --check通过；无额外全仓构建。根Agent已核实qiaoqiao2521账号及既有origin，Git交付覆盖本轮已验源码、文档与测试，具体版本以仓库当前提交及远端读回为准；模型、原日志、私有快照和本地会话不入Git。
