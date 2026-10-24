# Progress — 麦克纳姆合并

## Current

P3验收完成：3D H与同源码2D回归分别完成B→A原独立评分2/2，四单离线原评分复算一致；151/9121与152/9122均已清理。1758项反馈、2项原生几何回归、生产构建、局部lint、布局/文档链接及桌面/390px共13项浏览器检查通过。工作台5191保留只读结果，四类报告共用入口；原物理/传感器/速度/评分/时间门槛保持，旧失败与无效优化保留。有效工作由本轮提交及既有远端读回交付，owner=root。

P2已交付fb1b96f，既有远端main读回一致、工作区当时干净：共享MuJoCo/Jazzy/Nav2/SO101、原owner/oracle下，运动16/16、短停靠和完整E轮B→A2/2通过。1755项原反馈回归、生产构建、局部lint及桌面/手机检查通过。P1下列证据保留，与P2范围分别解释。

P1历史范围：2026-10-24运行包迁入FishBot独立工作区，根CLI和/results底盘接入面板完成。原驱动/配置与九月修复已整合，保留Apache来源与旧目录；没有地图、会话、旧构建或嵌套Git。该阶段尚未实施MuJoCo麦轮模型；后续P2结果见上。Git修订与发布由仓库历史及最终远端读回核实。

## Verification

- 同源码2D runf871d5d2-00c9-47af-81dd-4b975cd8efda完整B→A2/2：B200.906/A212.952墙秒，原路线31.732/26.951秒；末XY.014747/.023532m、yaw.034774/.009613rad、连续静止1.96/3.66源秒。2start/1reset/0cancel，整轮472.630秒，原360/120/1000预算保持；guard介入.78/0源秒。选定运行源码与H逐字相同，两组各自起止不变；17组共同安装/路线/控制/观测/计算输入相同，物理XML归一输出目录后相同，AMCL参数相同。只有传感器生产及其障碍接入不同，不宣称严格统计性能增益。
- 四单独立原评分离线重放4/4，order-2绑定各自实际reset回执与episode；原失败未重写。零callback错误、原K/连续交接/同货物载运/目标/最终停稳均通过。摘要按原导入器白名单导出，warnings为空、四case均complete；3D缺失物理序号13/25，2D30/58，不插值补证据。2D/3D owned进程和端口关闭，H点云见证上下文已关闭；原107/114配置快照保持。
- 当前反馈全绿1758：control1028、mission209、autonomy61、frontend460，0跳过/缺依赖/失败；另跑原生几何2项通过。生产构建、5个受影响前端文件lint、根布局12路径/0失败、diff检查通过。浏览器final-b的13组行为通过：原J100、P2历史、本轮2D/3D切换、真实UUID/预算、390px内部滚动、坏JSON/404保留和导入下载，0写请求/0未捕获异常，测试浏览器关闭。
- 网页预检final-a因托管启动用了系统Node18而连接拒绝；日志明确Vite要求20.19+/22.12+。改用本机已有Node22.23.2后5191 HTTP200，final-b通过；未安装新依赖或改全局Node配置。一次布局命令从前端cwd调用根CLI失败，已保留原log并回根重跑；不把后续lint退出0当作那次布局通过。当前只读Vite的owned unit为fishbot-workbench-mecanum-b-20261024，实验API关闭。
- P3原始证据与失败留在`~/.cache/fishbot/mecanum-lidar3d-20261024/`：delivery-h-queued、baseline-2d-queued、offline-final-summary.json、final-pair-comparison.json、witness-delivery-h-queued及ui-final-b。只提交运行代码、测试、文档和两个白名单摘要，不提交原始流、运行配置、会话或凭据。
- H runb3d1ed7f-27e3-4e28-bf98-7d7d5cf3200a原B→A完整2/2：B204.051/A200.351墙秒，原路线28.679/22.289秒；末XY.023856/.022806m、yaw.002288/.001100rad、连续静止3.72/3.60源秒。2start/1reset/0cancel，整轮460.235秒，源码选定文本起止相同、零callback错误/零owned survivor、端口关闭。两单guard均启用但介入0；不是纯视觉。只读见证实收4434帧16×360点云，三个Nav2订阅端及实际参数确认；它不冒充逐周期消费ACK。四单离线复算与同源码2D回归最终通过，结果见后续验收。
- P3 scene-a生成通过：72/70/10布局与P2相同，16组车体/工位/路线/控制/预算/评分输入均相同，world/rig/arm XML归一输出目录后逐字相同。nav2差异仅输出目录引用及新增3D点云障碍源；原360束实际scan保留；当时对native rangefinder数量的推断已由后述组件核对撤回。实际B→A已启动，尚未裁决。只读点云探针a因DiagnosticStatus.level在本机rclpy为bytes而退出，原脚本与失败结果保留；兼容bytes后重开取证，不覆盖缺失的初段。一次状态打印将native_actions列表当对象而失败，已读到arm_grasp；未因此重发任务或更改控制。
- P3 delivery-a最终false：run872a2b33-53a0-41bd-92c5-a8214ea4252a；原Nav2/精停靠均4、双指抬升通过，搬运规划拒绝place_wall_x_-1，未执行载货路线。原记录完整、零callback错误，selected运行源码起止相同，A未派发，owned端口/进程已清理。点云独立见证397帧，360×16、实际三订阅端和原生参数确认；它不等同逐周期消费ACK。
- 同一91.66源秒抓持快照重放原错误：legacy cap=.02给出-.077730m且反向调用返回+.02，几何坐标分离；cap=.01不误拒绝。按MuJoCo3.3.7官方文档，legacy CCD距离可能不准确。独立payload模型启用nativeCCD后8段/149航点通过、最小净距.006327m，原.0002m阈值/.02m查询上限、执行世界flags131072与臂rig131072保持，payload副本flags0。SO101源码未改。14项arm/scene回归含分离误报及真实近接/穿透负例通过；原失败不改为通过。
- P3下一次准备阶段因只读witness提前占用domain147被原运行器拒绝，无动作/输出账本。已停止并核对准确witness进程，保留runner-b-preflight-domain-occupied.log与witness-preflight-b；改为API启动后才创建witness ROS上下文。随后delivery-b使用新输出与相同原配置运行，不覆盖首轮失败。
- P3 delivery-b原生生命周期未激活，60秒readiness失败、68.531墙秒结束、零start/零订单，原结果unknown。controller_server/change_state回应超时与collision_monitor参数查询失败被保留，未唯一归因witness或CPU负载。原运行器未获得清理证明而保留实例；根复用ReadOnlyMonitor确认原idle/无UUID/连续.7源秒静止，再核对准确launch命令与PID生命期，stop_owned_launch回收。retained-cleanup.json已读回零survivor/端口关闭；原unknown不改通过。恢复脚本第一次缺tools导入路径、第二次假定原报告有owned identities均退出且未发信号，最终按原命令＋当前生命期核对后完成。
- 新delivery-c使用148/9118隔离域，避免复用刚关闭的ROS图；同一scene-a与修复源码，原门槛不变。取证只在ready后创建ROS上下文，等待期间纯HTTP，不参与生命周期启动。
- delivery-c runb6032734-9264-43f3-800b-8f790da15f5b在118.990墙秒后失败并清理；原Nav/停靠4，抓稳抬升通过，nativeCCD载货查询将底板对报0。94.92源秒快照独立重放得到解析底板间隙.018563m，说明仅改nativeCCD不足；不另归因实际低放或调整释放高度，完整记录/零禁碰与原失败保留。
- 最终候选撤回nativeCCD，恢复所有模型flags131072。复用pair_clearance，不复制几何/路径算法；因源placement无距离注入参数，私有加载同一源文件并只为副本提供查询接口，共享模块和SO101源码未改。两真实抓持快照重放均8段通过，保守净距.006327/.006230m、3.793/2.767墙秒；载货阈值.0002、cap.02与臂margin.001保持。17项arm/scene/geometry回归通过，追加底板分离覆盖的局部复查独立记录。
- D实际B独立通过：214.747墙秒、终点.008122m/.021160rad，连续静止2.44源秒。A账本succeeded、full_finished与cleanup_checked存在，但执行会话中断，order-2仅collection-end等记录、无最终score和整轮result；不计整轮2/2。原数据与缺口保留，原实验进程/端口均已关闭，旧5191工具进程也消失；未唯一归因工具重载。新E使用既有用户systemd有限托管，保持同一修复源码、场景和评分；只读witness也托管并在ready后接入。
- agent-link随后加载，按用户约定经同步spawn_agent委派只读几何审查：AGY因--print/--output-format参数兼容错误退出2，Qoder单次55秒超时；未获有效审查结论，未自动重试或改全局CLI配置。get_status回读sessions为空。根Agent负责既有17项行为/几何检查和完整物理验收，不以委派失败充当审查通过。
- 托管E run1381c59d-0cb2-448a-b630-9654f6b03911仍false，B账本成功、原K/交接/载货/无禁碰/原生导航/目标/预算均通过，但最终连续证据仅.72源秒（此前最长1.92，后因采样间隙重起），未满足原1秒尾段；A未派发。229.742墙秒、原记录完整且owned清理完成，旧失败保留。独立原评分重放与函数返回条件直接确认binding/native/budget/last_valid均true，仅settled=false，未改裁决。
- 收尾修复复用EvidenceTail.quiet_proof，增加默认仍.7的可选最短源时长；factory等同一observer文件的1秒连续停止证据后再写full_finished。原评分/接收时效/窗口和360/120/1000预算不变，额外取证计入单单时间。111项acceptance/factory/arm/oracle测试通过，含“曾有2秒静止但间隙后只有.72秒不能关闭、补满1秒才可关闭”的原Gate行为用例。未改评分器。F在原148/9118及同scene启动；新增依赖geometry_check进入原选定源码观察范围，不作为执行锁。
- F run5edc50da-10f8-40f1-9e9d-fa8547d570e1原任务成功，但新FileTail停止检查未缓存首帧manifest，首帧被20000条环形尾缓冲淘汰后触发KeyError。原结果unknown、无full_finished，后续oracle只有原K通过，不能计配送通过。用户systemd已关闭旧launch/observer，根核对两PID消失及9118关闭并另写retained-cleanup，原结果不改。补充单份来源缓存；元数据未知时返回未就绪而非抛异常。112项相关测试通过，包括真实去重JSONL首帧淘汰后取证及缺失元数据不误通过。新G使用相同场景托管验收，未重发F原UUID。
- G runa06be1c7-ac08-4c0b-8b0e-8f8ff5850f34最终1/2：B282.808墙秒、.019148m/.006967rad、尾段1.92源秒；A在原360秒任务预算到达时仅执行载货Nav约17.926墙秒，原UUID取消5，路线本身尚有102.074秒余量；整轮722.912秒，owned清理完成。不能将其解释为载货路线120秒超时或确认3D避障卡住。原基线baseline-2d run3b59603a-3fe5-446b-864d-b516cbfa72be在48.351墙秒未取得停靠前连续物理确认，整轮82.765秒后清理，A未派发。
- G循环观测为inline ROS分派：211240步，mj_step累计306.337墙秒、spin_once193.855秒、publish178.173秒；统计包含阶段调用，未当作CPU独占根因。采用知识库FishBot§19已有“未消费360原生rangefinder与实际10Hz测距分开”经验，先准备显式omit候选做动力学和实际传感器输出对照，不先重复完整任务。
- 当前goal前一回合归类progress：有代码、测试和原生结果变化；本次重新核对systemd显示2D已终态而非仍运行，读取实际失败后改做组件对照。未因观察超时重启同一活动任务。CBC经同步agent-link返回done但结果为空，不计有效审查；首个私有组件探针误用NativeCloudQuery.query而退出，改用源码已有compute，失败脚本/日志保留。
- 组件对照最终完成：原/omit都是2000步、4源秒、3个IMU声明、0个原生rangefinder；动力学与实际scan/cloud/IMU相同但无加速（.689/.709墙秒），故不采用该候选。既有queued模式原生probe通过：150/9120、51.596墙秒、两个25cm原Goal状态4，实际位移.211824/.250787m；原生见证两RPP发布实例分离，计划391/199、命令392/200，final hold/.7源秒quiet及owned清理通过。它只证明移动控制与分派，不充当配送成功。
- 准备CLI仅补--queued-ros-dispatch薄入口，默认保持inline；显式true写入manifest，经现成launch送入CallbackInbox。四项原队列/launch合同和新增入口在内的21项准备检查通过。新3D生成文件与scene-a的15组车体/安装/控制/路线/观测/传感器计算字段均相同，world XML归一输出目录后相同，仅queued=true；没有省略传感器或关闭相机。完整H与后续2D冻结这项配置，H151/9121、2D152/9122。
- P2 `mecanum-simulation-20261024/motion-a`：MuJoCo3.3.7共享Physics完成空载/载货各8例，正反直行/横移/旋转/斜行/弧线16/16。驱动仅作用四轮铰链，滚子被动；非地面碰撞0，载货500Hz接触缺失0，均停稳。横移真值约.0507m/s（请求.06），6秒编码器端点差约18.2mm；保留滑移，不称零误差或Nav2全向运输。载货初始放托盘，仅为接触面板，不替代双指交接。
- P2 nav-native-a因缺imu_link启动失败，补齐共享静态TF合同后b通过：check1e8f42ad-f2db-48a1-af7b-97aa20d6ad04，146/9116，48.080墙秒；staging/default UUID均4，原生DDS不同发布GID确认消费。位移.21770/.24511m，真值XY.02795/.03298m、yaw.00388/.01276rad，禁碰0、连续.7源秒静止及owned清理通过。72合同检查通过，1项ROS环境条件跳过；8项前端profile及后续20项局部检查/生产构建通过。实际页面桌面/390px、真实146状态/解码帧/配置导出通过，0写请求/0页面异常。
- P2 delivery-a未启动动作：当时shell缺用户DBus环境；显式连接本用户既有/run/user/1000/bus后b运行。b保留完整失败：B入站、双指抬升、释放落稳/home通过，直接离站路线RPP预测碰撞而status6，A未派发；153.575墙秒/路线20.929秒，评分失败，owned清理完成。后续宽麦轮配置复用现成DriveOnHeading直线离站，不放宽原碰撞或时间门槛。
- J100精确margin差异在未修改HEAD的profiles/scene源码同环境复现：.02565237m大于原.01984143m。测试改为保持原净距下限，未改几何或物理评分；不将差异归因本轮麦轮分支。
- P2 delivery-c在原生精停靠阶段预测碰撞（905），尚未执行离站；37.882墙秒失败、A未派发，未据此宣称离站补丁有效。静态原图足迹无重叠，但原生预测/定位存在边缘差异，不能将其等同真实接触。候选将车体横移+.04m、托盘相对-.04m，保持交货XY=.24/.14；新增实体支柱与壳体重叠10mm。过重100mm实心支柱的motion-b四项横移1秒停车失败保留；改40×40×80mm铝柱，按2700kg/m³计.3456kg后motion-c16/16通过，原阈值/1秒停车保持。factory-scene-e完整几何扫掠余量.025652m通过，先验短停靠再完整运输。
- short-dock-a原独立评分通过，原Dock UUID07d8fe1f90e54074a8cc937290976f84状态4；停稳误差P95=.02076m/.02393rad，.7源秒连续与清理通过，64.258墙秒含启动/评分。随后完整D遭记录IO失败，独立评分false/物理未评；owner另因固定指未退出而release等待失败。D保留实例已由fresh ROS UUID终态＋.72源秒quiet独立回收，原报告不改通过。过渡修复的177项core/oracle检查通过，最终物理门槛保持；随后以D真实grasp帧原生重放，再执行/tmp新完整验收，结果见下。
- D真实grasp帧原生重放`release-replay-a`：同计划、同状态，旧过渡停在固定指.189N，未退出；新过渡退出后两指0、原最终handoff成立，车/臂禁碰0。只证明该过渡，不充当完整任务。E轮原生run94ed2798-319b-4eee-a762-8d55e71efb4e随后完整通过：B/A原K和目的地2/2，232.320/230.112墙秒、路线35.241/22.042秒、末XY.020643/.022463m、yaw.000317/.003425rad，连续终点静止2.60/2.56源秒。
- E沿原360/120/1000预算，2start/1reset/0cancel、全轮540.261墙秒。原生载货离站和Nav2 UUID均4；双指、实际抬升、释放落稳、home、同货物运输与禁碰原评分通过。选定运行源码起止文本一致、manifest输入一致，owned进程/端口关闭，原配置保护单位前后一致（当时均未运行，不称保护了活实例）。
- E为开放通道、2D、ideal工位观测；停车保护介入B/A=.88/.40源秒，原物理序号缺38/28，缺口不插值。不同于旧J100占用通道，不做跨车型A/B增益或纯视觉/真机结论。3D配置prepare与5760真实射线/独立查询保持plant测试通过，完整3D麦轮配送未执行。
- E两单原记录离线复算均通过。第二单首个复算因传错reset回执路径保留score-error；改用原reset请求对应文件后通过，未改原运行或评分。记录与代码仍在`/tmp/fishbot-mecanum-20261024/`；私有持久归档`~/.cache/fishbot/mecanum-simulation-20261024/delivery-e.tar.gz`约72MB，已读回原result的2/2与两score成员，原始文件未删除。
- 同一报告合同导出2案例、0缺项，原J100 public JSON未覆盖；前端记录选择器与车型草稿共用现有页面。实际桌面/390px旧K＋新麦轮切换、异常保留、下载检查11组通过，写请求/页面异常0，测试浏览器关闭。既有组合回归首轮control180秒超时，其余mission209/autonomy61/frontend460通过；control原组直接1025项151.410秒全通过，随后复跑原组合入口，不放宽原测试时限。
- 最终原组合入口复跑通过：control1025、mission209、autonomy61、frontend460，共1755项，无失败/跳过/缺失；原180秒时限未改。首轮超时保留，不能称从未失败。当前生产构建和8个改动TS/TSX文件lint通过，73相对链接存在，diff无空白错误。最终浏览器11组再通过，桌面/390px与0写请求/0页面异常、owned浏览器关闭；Vite5191只读报告预览保留，9116及ROS实验均关闭。
- prepare历史失败a缺IMU sensor容器、b缺胶囊冻结几何支持均保留，修复后c及带两目的地factory-scene-a生成72/70/10自由度/控制布局。最初合同失败包含未source Jazzy的diagnostic_msgs、旧Physics测试对象无新属性；后者已兼容。新测试序列化list误用tolist已修正。J100旧精确margin断言差异的HEAD对照结果见上，未调整原评分。
- 最终回归、原生release重放与浏览器证据另归档为`~/.cache/fishbot/mecanum-simulation-20261024/validation-final.tar.gz`；已读回原反馈passed及浏览器11项通过，归档权限600。原物理E包与该验证包均留Git外。

- 包发现为一个robot_base；独立colcon构建通过，输出`~/.cache/fishbot/mecanum-build/`。drive与minimal的show-args解析通过，未执行硬件launch。
- 真Jazzy节点在独占domain181、内核伪终端上验收。pty-a先复现重连漏开反馈；最小补丁后pty-b八项通过：启动归零/回传、前进/横移/旋转、超时停车、MSPD→Odometry/TF、非有限指令归零、看门狗重连恢复回传。实收vy=.05、vx/wz=0，反馈为测试合成，不是车体真值。原失败与成功报告位于`~/.cache/fishbot/mecanum-import-20261024/`；节点、线程、PTY均清理。
- 3项合并行为测试与7项耗时导入测试通过；前端4文件18项、TypeScript/生产构建与新增文件lint通过。布局检查0失败，98处相对文档链接存在，diff检查通过。
- P1归档时既有反馈入口：control987项中7项因旧planning-venv/bin/python缺失失败；mission209、autonomy61、frontend入口460项通过。P2恢复环境后的最终1755通过见上。这里保留历史边界，460不称全前端测试全集。
- Playwright桌面/390px共10组行为通过，增加三车型入口与麦轮待接入边界检查；写请求0、页面未捕获错误0，测试浏览器已关闭，截图在`ui-b/`。只读Vite5191保留供查看。
- 外层dev工作树有既有大规模迁移和独立Git，未整仓stage或发布；本次有效运行代码只交付FishBot既有远端。旧robot_base九月dirty保留历史，后续维护以新包和本PROJECT为准。
- 功能提交fff8227连同耗时页4ebb08c已推送qiaoqiao2521/fishbot-ros2-slam-tools的main，远端读回与本地完整提交一致。后续文档接续修订由Git历史保留；提交推送不替代上述验收。

## Knowledge Writeback

knowledge_status=updated。采用FishBot§19/20；在原`Wiki/ROS2 与 FishBot.md`第20节新增“放货退出：过渡条件和最终交接分开”，同步`Wiki/开发知识入口.md`触发词，并已读回两处正文/锚点。来源为原SO101实时release分支与同帧原生对照。只写机制与边界，当前状态留项目；知识库既有dirty保留，未整库stage或推送，owner=root。

P3 knowledge_status=updated：同页几何段补`^native-payload-query`，记录legacy查询误报、nativeCCD候选撤回、复用保守分离下界与原阈值/执行世界和基线复验边界；开发知识入口增加对应触发词。两处正文和锚点已读回，只记录已复现机制，不预写完整任务成功；保留知识库既有dirty，owner=root。

收尾经验继续updated：同页第20节补`^terminal-capture-dwell`与`^deduplicated-tail-metadata`，索引增加对应触发词，两页三处正文/锚点已读回。分别解释当前尾段与历史最长、来源缓存与去重日志，不预写G/2D成功。原知识库dirty保留，未整库stage/push。

P3传感器核对knowledge_status=updated：同页第19节“传感器计算”补充按车型核编译声明、麦轮无原生rangefinder及omit无收益边界；开发知识入口第29行同步“omit无收益”触发与cooperation_mecanum来源。两处已读回。既有后台接收/物理owner/接收时间经验已覆盖，不重复新建页；owner=root。

## Next

P1–P3验收已完成，Git交付由本文件所属提交与既有远端main读回核实。后续连续世界M1b以后、自主全向Nav2仍未验收，沿各自计划接续，不自动派发，owner=root。
