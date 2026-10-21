# Progress

## Current
软件薄层、36项CPU合同与main整合完成。第三轮隔离同桥面板通过：一次移动取消＋两次完整运输，原ID恢复、两次显式reset和独立物理评分通过。前两轮失败原件保留，原视觉56例中的11失败仍incomplete。以下较早段落是阶段历史，当前以本节及末尾实际读回为准。

## Done
- 已读项目入口、SpecMesh v1.1、现有 action/reset/history 与原子写入工具。
- 当前主区仅只读合同参照；未复制或修改 dirty 实现。
- CLI 包含 init/event/status/tick/dispatch/cancel/reset/recover 及有界 run。两 job 自动成功路径、短锁外部事件、超时保留原动作、unknown/fault 封锁已由 fake clock/sleep 定向回归。
- 独立审查复现并闭合 scope 键集、source=None 和慢 GET 超预算后新 POST 三问题。根在最终源下独立重跑36项且起止SHA一致，最后 preflight 无intent首次发送分类也已读回确认。
- 当前证据 `/home/muqiao/.cache/fishbot/workflow/acceptance-20261014-v2/cpu-acceptance.json` 与同目录 `cpu-tests.log`：36 运行、失败0、错误0、skip0；4执行/校验源前后 hash 一致。旧 v1 的32项证据保留。没有 ROS/MuJoCo/GPU/服务/浏览器/实机运行。
- workflow 源 SHA `582f979da1c7a70ee5558be48019e8d0502e6e280fa6a4783882683e8a3a2ae4`；tests SHA `8836bed9c13fc1299019dde319373a0c01b8ddf58569705e428aeaef5bd93f91`。
- 代码 commit `3aa3f61a4c5d55a5bc71fede33ee75922bd0c6d4` 已推送 `qiaoqiao2521/fishbot-ros2-slam-tools` 的 `codex/workflow-20261014`，GitHub REST ref读回一致。身份 `qiaoqiao2521/238822818`、既有repo `1381244533`、fetch/push URL与原public可见性均核对；未推main、未创建PR。代码提交仅6模块文件，独立worktree当时clean。
- 根交接回执：已用 Codex 内部 `send_message_to_thread` 向原 FishBot owner 投递候选 `85e9e07aa5e2347cc19c52c066feb69c89ae2272`、最终源码 SHA 与36项根独立测试证据；工具返回预期 threadId。投递不等于 owner 已整合或物理验收通过。

## Remaining
本模块预声明物理面板已通过，源码、文档与知识小段已完成远端读回。视觉11失败另由visual-docking计划的新开发整改入口接续；广泛旧知识18–20节发布仍由研究根审定。完整任务成功不外推生产稳定性或真机。

## Issues
基线没有 cleanup/native_actions 公开字段；复用已有 reset.available 门禁。主桥历史截断时缺任务 ID 必须 unknown，不修主桥。
reset 本身失败或拒绝保留原 ID/receipt，交 FishBot owner 审查，不自动生成第二重置请求。编排器重启不包含 bridge 重启恢复。
已纠正 queue 适用范围：当前 Codex App 对话、线程与内置子 Agent 属于内部协作，直接复用已有工具接续；无需 queue 迁移或重开。原生 queue 仅适用于 Paperclip 等独立外部系统回传。依据当前共享 `~/.agents/AGENTS.md` 的“外界 Agent 协作与原生队列”，不再以外部 queue 接入状态阻挡本模块内部交接。

## Next
交付当前同桥、持久账本和有界run能力。后续重复仿真复用既有入口，保留原ID与episode边界；不重启未知bridge，不替代原视觉资格整改。运行入口 `docs/COOPERATION_WORKFLOW.md`。

## Knowledge closeout
`updated`：root本地修正Wiki/ROS2 与 FishBot第19节的旧“时钟保留原group”及两种滞后方向。研究根将本轮TimeSource风险、公开专组路由和消费回执边界单独整理到同页“原生 ROS 时钟与回调组”，补开发知识入口的独立触发。该小段已从干净远端基线发布到私有my-programming-world main a2b99a5f0c2bc9701504b7caa20790ab949c7208。根实际fetch/REST、原小节与入口行逐字读回一致，receipt见新runtime的knowledge-closeout.json。第20节原ID与交接评分约定already_covered；canonical其它18–20节及累计dirty的整体发布pending，研究根接续，不宣称整库已交付。

## Root串行接入

2026-10-15 root在视觉56例及GET-only实例安全关闭后合入exact9c581f8，6模块路径不与视觉执行源重叠。合入前后独立36CPU检查均通过，默认start三键仍走完整transport。真实验收按task_plan新隔离面板，状态pending；等待SpatialLM600s单例释放，当前没有该面板ROS或运输派发。原oracle按episode分段采集，不用跨reset日志冒充一次评分。知识状态pending，由root实际取证后审定；模块worktree仍保持原件。

## 首次实际面板与原失败保留

主区包含workflow原9c581f8与SpatialLM最终a84d9ce，main/REST读回ddbfeab714f0cec76b755908324c82eaa5afa04f。首次私有预检`runtime-20261015-1bf29cc1`因父进程D-Bus环境缺失零派发退出；没有world或任务。补同一既有环境后新目录`~/.cache/fishbot/workflow/runtime-20261015-cfae3abf/`执行，新输入/源码45份在启动前冻结。

移动取消通过原Dock UUID bdcc99cbcd9f458a8016d0e3860e74eb/raw5、真实0.15–0.164m/s运动、连续静止3.4源秒、hold/guard禁用及原safety评分；task completion仍false。recover只发原reset b9a824c2一次，新episode99160ab1与旧任务history确认。迟到ready未派发、同事件重复、占用/旧版本拒绝、真实接纳后显式丢回执、unknown封锁新dispatch、独立CLI按原ID对账、有界run超时不动原执行端均有原件；实际总POST为2start/1cancel/1reset。

job1新attempt 0c1bf47d在准备导航失败：原Nav31701beb到5，没有Dock/装载/运输。完整原oracle=false，job2未发送，整体passed=false。失败诊断clock57.82、bridge raw57.54，source age0.28s/received0.279845s；同时producer每0.02源秒持续生成，最大墙gap20.625ms，独立observer最大25.499ms，station admission也迟到约0.28s。最早可证异常位于桥端接收/处理/缓存路径，具体executor/RMW/readiness/共享锁原因尚未证明。原0.25源龄门槛正确保留，不直接归因网络或reset。

另一个附加评分缺口是私有harness传了不含reset_stamp的普通HTTP ACK。独立原physics确有epoch reset源stamp48.56000000001338，早于首采集54.28和任务55.58。下一轮只改采集，绑定原reset UUID、独立ROS ACK/physics stamp和new episode，不能用wall时间替代或回填旧score。

原result.json默认source/protected false不重写；root另写`root-failure-closeout-readback.json`，独立45文件SHA/HEAD、六保护单位与闭9090核对通过。原17owned PID身份无存活，held/guard关闭/真实quiet后安全停止；无retained launch/oracle/CLI。所有旧视觉11失败和83result不变。此为可恢复失败，不是完整两作业成功。

知识状态`already_covered`：Wiki/ROS2 与 FishBot第19节已经覆盖源及时但桥缓存滞后、双时钟分层；第20节覆盖原ID对账/未知不重发/动作与任务评分分离。实际面板证据留项目私有缓存，当前不新增知识数据库，也不把未证实的锁原因写进知识页。owner=root。

## 分段诊断源冻结准备

只新增可选`state.bridge_timing`，复用原LoopTiming的0.1s慢阶段阈值/32尾部、淘汰数与count/max；分别记录callback入口、JSON/validation/readiness、锁等待/提交、工位输入/逐topic图查询、HTTP锁等待/组装。场景/manifest/episode/sequence/原stamp绑定；DDS原ns明确未核时钟，不计算伪源龄或声明控制器消费回执。没有新线程、逐帧文件日志或控制门槛。受保护11个控制方法AST保持。系统/planning各70合同通过，当前反馈873（control513/mission145/autonomy61/frontend154）通过，零skip/缺依赖。

下一轮私有`runtime-20261015-a82c8b55`采用修正后的独立ROS reset_result可靠接收与真实physics reset_stamp交叉绑定，在采集之前写envelope；原HTTP ACK同时保留。源码/门槛与模型保持，诊断运行若同控制器再次成功只能称复现，不宣称改善。私有脚本最终passed按最新source/protected/port/quiet/所有者/预算和空errors统一收紧。root独立预检通过后冻结新源码开始同3case，当前尚未派发。

## 第二轮已执行与新Clock验证声明

`runtime-20261015-a82c8b55`实际94.167墙秒；2start/1cancel/1reset。移动原Dock c4675b16的status5、quiet和safety评分通过。job1 f98c2614在source55.86→75.72准备Nav失败，没有Dock、机械臂或货物运输；完整评分false，job2未发送。独立reset源envelope评分通过，不回填第一轮缺口。

桥clock74.5/raw74.82对应负source age0.32s；独立原clock74.84在失败前5.277ms已收到。新分段记录没有证明失败时physics/readiness/锁等待变慢。旧episode慢事件不解释此次failure。源起止45文件/HEAD、六保护实例、预算、guard/quiet、17owned身份全部关闭与9090关闭均true；原passed=false保留。源14a6daf及原score SHA记录在该目录，未修改旧56/83原件。

下一轮目录`~/.cache/fishbot/workflow/runtime-20261015-clock-afde67e5/`，新batch IDs，原三case/360s任务和1100s根预算保持。先以实际ROS受控阻塞probe验证原生Clock的默认组串行限制，并读回唯一标准Clock回调/QoS/专用组；候选只用公开订阅入口路由。尚未证明具体占组实体，不宣称解决原全部时间异常。CPU源码审查通过且根提交冻结后才派发。owner=root。

知识状态`already_covered`：FishBot第19/20节已涵盖双时钟、接收与消费分层、原ID对账和评分隔离。新的回调组因果结论等待实际probe/新面板；当前不写入未证明根因。实际失败原件保留项目私有缓存。

受控probe c32d691b实际通过，根独立读回原publisher/witness/script SHA与清理。hold0.759191墙秒内shared源推进0、isolated/witness推进0.634229源秒；原TimeSource callback/QoS一致。前两fixture false仍保留。桥候选只解除已证明的默认组串行风险，新物理面板尚未派发；不归因a82具体占组实体。

候选已停写。系统/planning各74项core/readiness合同通过、零skip；根独立planning core72项和项目反馈877项（control517/mission145/autonomy61/frontend154）通过。根实际ROS `candidate-clock-probe.json`直接抽取候选四方法，确认唯一/clock订阅、原TimeSource实例/方法、专用组、depth1/BEST_EFFORT和3次原clock更新，实际DDS元数据可用；two nodes/executor/thread与domain120全部清理。旧Bridge方法AST只有构造函数增专组，原控制逻辑不变。bridge SHA aa3fec2f0e5f3106d5309cdf9d868e1193e87497bd1eddcb40f49dbebafa6208。新增clock_callback/clock_update仍明确bridge processing，不冒充controller consumption。

根新harness只读复审通过，沿原oracle的完整http_state采集新clock字段，无额外服务/请求。根将在提交冻结后派发同三case；原failed结果不覆盖，正常transport仍须独立oracle通过，unknown不算通过。

## 第三轮最终实际读回

`runtime-20261015-clock-afde67e5`冻结ec879ed，544.531墙秒完成同桥三episode，低于1100根预算。三次start分别对应移动取消、job1与job2；一次cancel、两次显式reset，无重发。迟到ready、重复/旧版本/占用拒绝、真实丢start回执、unknown封锁、新CLI原ID对账和run超时保留执行端均通过。原CLI退出不冒充动作终态。

取消task af333561/Dock c0f8c91d原status5，真值移动约0.160770m/s、连续quiet2.48源秒、hold/guard关闭确认，原score0b27bacf true；task completion仍false。job1 45b0bc70/episode d384a502与job2 c45fb177/episode9bc848af各原1Dock＋2Nav UUID终态4。原score76736d91、62073d38均true，原K/episode/reset源时间/完整交接评分通过；实际双指抬升、释放完整外廓留盘、臂回位后携同一自由货物运输、最终停稳通过。货物位移1.788226083m、1.787300786m，连续携货违规0。每个完整任务仍在原360s上限内。

源起止45文件及revision相同；root逐项重算当前45SHA、score SHA、当前HEAD、六保护单元、17owned PID身份与9090关闭，全部通过。最终无活跃launch/oracle/CLI，连续静止2.98源秒，guard关闭，result.passed=true。原P1–P3的83 result与11失败保持，新增3case单列，不替代旧分母。

边界仍保留：job2末账本保存clock225.74/raw225.48的+0.26s transient freshness_failure，以及3次共享物理拒绝；任务最终通过不代表全部抖动消失。专组只解除已证实的默认组串行风险，没有证明旧a82具体占组实体。新增clock_update是桥更新证据，native_consumption_ack仍false。两运输使用ideal工位观测，不能计为新的RGB或sim-to-real成功。

独立复审再核两运输墙钟208.307s/224.146s、7409/8197独立物理样本与全部原gate。最终quiet快照clock_update max0.898ms、slow0；桥全阶段仍有5慢事件，主要位于between-job reset边界，HTTP组装max0.7005s、physics锁等待0.6170s。不能写全桥slow0。root另保存六保护实例原字段root-protected-after.json，与before一致。

知识发布差异已闭合本轮小段：远端80ab374原页只有1–17，不能整页复制canonical旧dirty。研究根从该干净基线只发布本轮独立Clock小节与入口到a2b99a5；canonical同名小节与远端逐字一致。其它扩展18–20节仍pending，owner=根总协调/机器人知识接续；最短入口是审定这些已存段后从远端基线隔离补丁。该pending不是本轮Clock小段未发布。

## Git与报告交付

执行候选ec879ed8bcc95225f4845b5a6c295bdaa1fbc40f和最终结果文档4189fce981abc8be452f7fa6e8c4c6275a89267b已串行推送既有qiaoqiao2521/fishbot-ros2-slam-tools main，GitHub REST与本地读回一致。有效账号238822818、仓库1381244533、公有可见性及fetch/push目标保持；运行后只改文档，45执行源当前仍匹配冻结。此元数据收尾另作文档提交，最新tip回源远端。

私有index.html和acceptance-report.json单列3case通过，链接原视觉56报告；83原result哈希再次核对不变。原release.sh保持未执行、未暂存，具体依赖/分区静态阻碍及owner仍见cooperation计划Retained work。没有运行日志、地图、模型或凭据入Git。

## P7 完成（2026-10-20）

- complete：用户授权的三批＋第二目的地复用验证已通过。原main在768ea35收尾干净后开始；根串行整合。worker边界和原阈值见task_plan P7。
- start可选delivery_pose；workflow init保留--batch，新增--batches与可选--delivery-poses JSON映射。N来自输入，不新增人造批次上限。未提供目标时保持旧行为。
- domain136/API9106在新目录执行，未重启旧实例。复用既有验收器、真实ROS独立observer和oracle，未新建调度/运动owner。实际C源起止10文件逐文本一致。
- knowledge：采用的双时钟、原ID恢复、桥回显与原生/物理评分分离为`already_covered`，来源为Wiki/ROS2 与 FishBot第19/20节及“原生 ROS 时钟与回调组”。新增慢几何预检锁边界经验为`pending`：该知识页及入口另有未交付改动，本轮不整体覆盖或发布；owner=根Codex，最短入口为审定本项目findings的“P7实际暴露的锁边界”后，局部补入原知识页。项目实现与验收不依赖此知识发布。

### P7 前两次尝试与修复

- A在用户DBus查询前退出，未prepare/launch/start；根为新命令补XDG/DBUS路径，未重启服务或改网络。
- B首任务原ID `12d721d7-8b02-4241-8f3a-f5b8aff1c538` 接纳后源龄失败，0原生派发、0reset，原失败保留。根独立原episode的1.28源秒静止、guard关闭和明确cleanup后核PID清理，9106关闭、原launch/observer PID消失，见私有root-closeout。
- worker移出耗时预检临界区；85core、46workflow、49oracle、1真实几何与25acceptance定向检查分别通过。canonical transport marker现在兼容默认目标声明，新oracle不误拒原无参数入口。
- C使用新目录和新UUID，控制/评分源码冻结；同一136/9106 world跑A/A/B。5189复用原前端，仅用workbench JSON映射该cooperation服务，0前端源码修改。三次完整运输已通过独立评分，见下表。

### P7 最终实际结果与交付边界

原件位于`~/.cache/fishbot/workflow-reuse-20261020/c/`；result.json、workflow.json、逐case observer/score、cleanup-quiet与root-closeout-readback.json共同取证。A/B失败原件与root清理回执保留，未回填成功。C耗时643.777墙秒，在1400秒总预算内；各任务保留原360秒上限。

| 批次 | 目标(x,y,yaw) | task UUID | 载货Nav UUID | 位置/偏航误差 | 终点连续停稳 | 同货物净位移 |
|---|---|---|---|---|---|---|
| 1 | (0,-2,0) | 695f0f51-7a0a-4c2b-af7b-cdc8cd91ea62 | 03ddbb2edb56401cb6e77f09c4f7625a | .033854m/.015640rad | 2.46源秒 | 1.79146m |
| 2 | (0,-2,0) | 88edb274-6338-4b30-9f7e-656db5c7acdc | ece828226c91494ea42c5b7c7785a389 | .031832m/.032529rad | 2.54源秒 | 1.79003m |
| 3 | (.7,-2,0) | dc99a6fc-f44e-43b0-abc7-9c5a93dcae21 | 9dec77e0933143989f44a2778c7357a8 | .022101m/.002298rad | 2.42源秒 | 2.48919m |

三task/episode目标绑定一致，载货Nav独立ROS终态均4；原K抓取、抬升、释放、完整货物留盘、臂回位、持续携货与终态评分均通过。目标桥回显仍标`goal_request_independently_observed=false`，不冒充控制器消费回执。workflow最终succeeded，3start/2reset/0cancel，无额外重发。两reset绑定独立ROS源时间，桥/world未重启。

定向检查共206项：core85、workflow46、oracle49、实际MuJoCo几何1、acceptance25，均通过。C清理后只收紧acceptance缺失native_actions的负例，25项重跑通过；实际C字段明确为空/有值，控制器与评分源码保持，未重跑运动冒称新改善。既有旧无参数合同与默认目标测试保持。

原前端桌面/390px分别读回A与B，任务目标与界面属性一致，零写请求、零页面错误、手机无横向溢出。证据位于同级ui/goal-a.json、goal-b.json及截图。实验owned进程全部退出、9106/5189关闭；原5188仍监听，保护实例状态一致。只读核对与清理记录已回读。

可直接复用：输入作业数量、每批交付点、同ID查询/取消/恢复、既有停靠/抓放/载货导航、原前端与独立评分。仍需适配：不同工位/物体/底盘、同回合多货物库存、任意地图、视觉留出与真实硬件。本轮ideal观测三批成功不计为新RGB或sim-to-real验收。原固件脚本保留，未刷写。

## P8 Current

in_progress：车型/传感器/任务配置、实际四轮底盘/工位/托盘、2D+3D接线、原UUID出站/载货参数与网页配置草稿已实现。当前 J100+3D 多次完整运输有单批成功，但同一冻结候选的三批 A/A/B 尚未全部通过；其余三条最终矩阵尚未运行，不能称4组合12/12。K2在360墙秒内未完成最终朝向；最新只读证据显示小转向请求下轮速伺服稳态误差大，正独立做20例低速响应校准。原质量/摩擦/扭矩、碰撞/时效/评分不放宽。F1默认FishBot开放场景2/2已独立交付，不能代替P8。

最新根验证：完整反馈1621项通过（control891/mission209/autonomy61/frontend460，零skip/缺依赖）；133项P8/F1相关完整原生离线测试通过。随后雷达自定义topic/range统一接线与goal XY持续检查的6项composition测试通过；新goal参数尚待完整原生运行验证。前端桌面/390px实际配置草稿与下载验收保持，非运行时热换。知识updated(local)，已回写Wiki/ROS2 与 FishBot第19/20节及开发知识入口并读回，独立知识仓未提交发布。当前root继续校准与冻结面板；后文为逐轮历史，旧失败原件不覆盖。

配置/轮控/原生点云/前端初版已接。根86core、48workflow、3composition、7原雷达参数、12prepare及1launch通过；全sim在正确ROS＋planning环境38项通过，零skip。第一次系统Python缺diagnostic_msgs且2项skip，仅环境无效结果保留，不改实现绕过；重新使用既有ROS环境后全过。前端worker59项/构建/lint通过，实际浏览器待根验收。J100工位/真实托盘支承块仍在完整几何余量修正中，实际运输尚未开始。

J100完整fixture修正后profiles8/8与旧scene7/7通过，保守扫掠余量19.84mm，真实18mm铝支承块0.486kg。开发dev-jackal-lidar3d-a在DBus环境查询前退出，零launch/start；父命令补既有XDG/DBUS环境后，dev-jackal-lidar3d-b实际准备Nav成功，但Dock在距目标约.257m处因原生预测碰撞905失败。无实体禁碰、无guard trip、源门槛无异常；原UUID明确终态6，原失败评分保留。129.89秒后独立quiet/cleanup通过并清理owned实例，原服务保持。

只读回放原生最后10预测点：精确3D几何最小净距29.95mm，完整矩形静态地图占用格0，驱动轮正确且未接近限幅。正在区分动态点云的高度投影与坐标变换；不因失败关闭collision或放评分。dev-jackal-planar-a仅改传感器配置做对照，使用独立138/9108。最终四组合面板尚未开始。晚启3Dprobe因实例已结束无数据，记incomplete；UI首次严格label选择器不匹配、第二次读已关闭服务，均不能记浏览器通过。

### P8 开发排障与候选冻结

dev-jackal-planar-a在原120秒准备Nav回执期限内未进入15mm目标圈，按原UUID取消到status5，未进入Dock或抓放；最终所有owned进程及9108清理，旧结果保留false。独立trace在首个AMCL重置之前已看到命令.573rad/s、真值.0846、EKF.0846；不是IMU航向反向。原生独立14组阶跃复现直行正常、四轮擦滑转向仅约15%，扩大力矩上限不改变结果，不把问题归给网络或评分。

候选保留官方质量、惯量、真实轮距.37559m、轮径.098m、四真实轮、摩擦.5和12Nm限制，复用滑移转向有效轮距惯例。固定离线30组面板选单一系数4.5；命令与编码器共用1.690155m有效轮距，真实几何另存。该MuJoCo3.3.7平地参数不是实车标定或在线真值反馈：空载纯旋转最大绝对误差.04702rad/s，曲线仍有约.066rad/s、.032m/s残差，满载同样保留。新原生正负转向回归通过；原FishBot系数1保持。全部候选参数与旧失败在私有skid-response-probe保存。

三维失败离线同帧回放在原生预测足迹内只命中33–34.5cm高夹爪，二维扫描与静态栅格均为空；未保存原costmap帧，因果结论保持强候选。现从名义编译几何计算车体＋任意朝向货物上界，J100加原10mm padding为.30956659m，FishBot为.20306659m；不使用沉降后的较低高度。两costmap和CollisionMonitor共用该观测上界，原完整碰撞几何与物理评分保留。5个真实几何包络测试、3composition、12prepare通过，实际新运输仍待执行。

AMCL原生initialpose查询包含接收端now()，桥等待旧观测TF不能保证消除20ms未来端点竞态。当前不改观测stamp、covariance或原15mm/.035rad目标门槛；该警告与粒子重置的厘米级偏移单列，不能据此伪称已修。后续开发单批先验证固定物理适配是否足以完成原门槛，再派发最终面板。

私有runner观察37个实际源码文本，另独立记录生成manifest/XML/Nav2/EKF/地图YAML/BT及输入的起止文本；不引入hash执行锁。二进制mesh、PGM和原生库不在该文本观察范围。新增非默认A/A/B跨reset与账本reopen组合测试，全workflow49项通过。知识状态仍pending，owner=root，待实际复用结论后收尾。

dev-jackal-lidar3d-c实际122.09墙秒，原Nav/Dock UUID均独立成功；位置误差约13.81mm、偏航.01367rad，连续.7源秒停稳，双指抓取/抬升保持通过。随后原carried-route几何查询发现base_collision与moving_jaw仅.5459mm，不满足原1mm查询余量，任务失败且未发载货Nav。完整oracle=false，故不计运输通过。source37及generated11文本起止一致、独立quiet/guard退出/全部owned和9107关闭、保护实例不变。正检查实际停靠姿态下的托盘/车壳/夹爪交接余量，不删碰撞、不改评分。

实际浏览器ui-v2通过：J100/3D当前组合与FishBot/planar三批草稿独立，导出JSON内容正确，零写请求、零页面错误；390px实际切“任务与反馈”后可配置且无横向溢出。前一fixture未切手机tab而等待隐藏select，失败原件保留，未改产品以迁就测试。根CLI原缺cooperation分支已补薄转发，实际prepare --help可见--scene-profile；不增加执行owner。根既有反馈回归1594项全过，零skip/缺依赖；包含control864、mission209、autonomy61、frontend460。

dev-c只读probe收到853点云元数据、800同stamp物理配对、832精确源时刻TF和真实local/global ROI。低bench/table保留lethal占用，上方夹爪ROI无lethal但有正常膨胀253，不能称全零代价或独立消费回执。probe整体false另有fixture缺陷：批量请求未初始化的EKF imu1导致整批参数空，结束时空图谱覆盖活跃订阅；旧结果保留，修私有采样器后需重新取证，不把false直接归给产品EKF或实际订阅缺失。

### P8 距离查询、横向布局与自体回波

修正dev-c几何解释：.5459mm是旧MPR查询返回值，严格compiled box/mesh分离平面实际至少30.8mm。相同query/model/data/pair的distmax=.04/.05返回30.8168mm，.1返回.5458mm、.2及1出现错误负距；GJK在此pair正常，却让旧FishBot/SO101的pick_floor/gripper远隔47mm也报0。全query切GJK的候选和两组旧场景失败已保留并撤销，未运行实际运输，不抬高18mm支架回避查询错误。

最终局部修复只设原open/closed CollisionChecker公开distance_cap_m=2×原margin，即2mm/1mm；原MPR、payload查询20mm/.2mm及运行物理模型均保持。原actual完整149waypoints载货＋37states回位查询通过。独立重编译反例确认.5mm间隙拒绝、-.5mm交叠拒绝且有真实contact、1.5mm间隙通过、2.5mm返回饱和2mm通过。新真实compiled回归1项、旧scene7项、当时profiles9项通过。饱和值不称真实净距。18个有限停车姿态中接近18/18，完整运输查询仅5/18；其余13失败留存，不宣称全±.04m/.05rad交接可达。

dev-d和planar-b都在原Nav成功后Dock905，未进入机械臂；分别88.32/96.19墙秒，source/generated起止一致、quiet/guard退出/owned清理/端口关闭、保护实例保持。D明确Collision detected，停靠窗口clock最大墙gap52.4ms，并非长时间卡死。C/D/planar-b的AMCL XY误差P95约26.4/25.9/26.9mm，大于原低侧19.2mm净距；重建pad足迹距原静态占用格边界约数毫米。二维同样拒绝，不把一切归给3D或未来TF警告。具体254格来自哪个输入层仍未独立确认。

J100布局已作实体参数适配：dock Y=.32、tray Y=-.18、mount相对tray Y=.075；交接仍(.24,.14)，高度/18mm支承块/.486kg不变。完整hull自动增至6点，不缩几何。低侧保留原10mm Navpadding后净距42mm，实际原误差回放41.43mm；整体3D扫掠余量仍19.84mm，不误称所有精度提高。mount支持重叠100×35mm、悬臂85mm，刚性固定可做当前仿真，未验结构挠曲或紧固。最新profiles10项通过。

dev-e实际270.44墙秒，新布局Nav/Dock通过，位置约10.67mm/偏航.00740rad；真实双指抬升、放货留盘与臂回位均通过后，载货Nav原UUID457f238c82a643e9940198b9410ea01a因104失败。完整oracle=false，原E不改通过；cleanup/source/端口/保护实例均通过。根随后显式cancel因原任务已终态被preflight拒绝，零新增POST，未重发任务。

E的native独立回放在source159.98s找到完整footprint内11个低点，11/11均来自自由货物target_collision，车外障碍0；超过CollisionMonitor原6点。车辆未移动、货物真实留盘。正在现有3D适配器补标准空间自体包络过滤，保留原生首回波和raw点云对照；不按taskstage/接触状态隐藏cargo、不移除物理geom、不放minrange或评分。当前仅原sensor合同通过，不能提前称载货闭环完成。

E运行后启动的修正只读probe整体通过：669帧metadata/physics原stamp配对、657精确stamp TF、真实16×360/10Hz，两costmap与CollisionMonitor实际参数和同一活跃时刻订阅、J100轮速/IMU输入及无truth/绝对yaw配置均通过。此前D probe又遇到启动期仅use_sim_time参数表和误加two_d_mode=True预期，均只修私有probe并保留旧false。原J100 six-DOF配置不改。未独立证明唯一odom TF逐帧发布者，亦不称控制器逐点消费回执。

自体过滤实现冻结：仅按同帧base坐标的完整凸包和未膨胀车体/载货高度过滤实际首回波，不按任务阶段/货物身份/接触判断，不向后重射。raw与filtered保留原16×360布局及源stamp，新增独立raw发布。E同帧重放空车0点、载货11点移除，其他点逐值不变；边界外1mm和低障碍保留。最新lidar12、全sim38、横向fixture后的arm_geometry1均通过。正式矩阵按预声明四组合执行，先J100＋3D；源码38项与生成输入起止单列观察，尚无正式通过结论。

正式matrix-final-a首个J100＋3D回合258.90墙秒，task ebe44854-134c-4138-867b-0a208538b91f/episode b3fb54a1-ea3f-47e6-946e-461176ab5441。Nav/Dock、实际抓放与臂回位通过，载货Nav f42e10c97e564bc2ac10c25b2c6b7a45终态6，最终未到交付点；oracle=false，不续发后两批。source38/generated11起止一致，独立quiet/guard关闭/全部owned退出/9110关闭，保护实例保持。原始失败保留。运行中ROS合同通过；raw/filtered实际逐点复核另存，外点不变。正在区分出站转向几何与地图投影，尚未增加新候选或放宽门槛。

正式A同源取证：raw/filtered1015配对帧逐点符合空间mask；空车138帧移除0，载货729帧移除12–22，2675701个体外首回波全部保持。末姿态footprint内剩余0，预测正转+.2rad时有9个2D/36个3D approach_obstacle回波，不是cargo。实际costmap当帧仍缺失。离线完整455对检查actual交接姿态直行→staging141样本，扣平移采样半间距后3D下界29.98mm、padding后静态格间隙42.01mm，均正；这是声明路径几何证书，不是执行结果。

最小出站候选已接：仅J100 profile声明transport_egress=staging，prepare生成egress_pose；同owner、原car_to_delivery阶段先载货导航出站，再执行冻结交付目标。原取消/hold/guard/360秒预算与物理评分保持。独立oracle要求两段不同UUID、目标顺序及原生成功；未声明场景继续exact1，拒绝未知额外段。141 core/oracle与13 prepare回归通过。新矩阵使用matrix-final-b，保留A及所有开发失败；四组合/12运输声明、每组合1400秒上限不变，尚未称候选通过。

出站补丁后根既有反馈回归1601项全过：control871、mission209、autonomy61、frontend460；零skip/缺依赖。该检查为离线回归，不替代正式矩阵。matrix-final-b先启动J100＋3D，独占140/9110，其余实例与源码保持。

B首批176.17墙秒，task a89a06e7-dde2-4fa1-907b-46dbc7c56b67；egress原UUID268c71dc7f3a437c8bfd87f1e416e14f在载货守卫触发后明确status5，未派发final delivery，完整评分false。source38/generated11/quiet/guard退出/全部owned清理/9110关闭/保护实例保持。不能把取消或新出站段开始叫运输成功。

B精确触发source126.30：floor_contact=false为唯一cargo_retained失败项，中心与旋转完整足迹仍距边界至少33mm；126.28/126.32均有4个floor接触、约.124/.125N。原world/qpos/qvel独立mj_forward同pair0contact，严格顶点到floor正间隙8.958µm，确为微小离面而非遥测漏标或真实滑出。真实持续时长只有前后40ms采样夹界，不称精确20ms。现检查J100原max_accel[.5,0,2]对四轮载货起步激励；不放宽接触或物理评分门槛。

J100平缓起步候选冻结：仅profile生成原生velocity_smoother max_accel[.1,0,.2]/max_decel[-.1,0,-.2]，最大速度、CM与hold不变。原短重放首个角命令造成每轮约6.9Nm请求；候选短脉冲1250物理步全接触，延长1s候选仍有5个500Hz短失接触，125个20ms相位均保持。仅近似原ctrl ZOH重放，缺精确DDS子采样/warmstart，不称native smoother或全任务已过。4composition测试通过；前端33定向与生产构建通过。新matrix-final-c启动，A/B原失败保持，评分和原任务预算不改。

C首批82.19墙秒，Nav/Dock原生status4，但真实停靠yaw=.25534rad超原.05交接门槛，task 0e0fe5ce-f2d4-4eb1-9ec7-f2342759ce26因此在机械臂前失败；oracle=false。完整cleanup/source/generated/端口/保护实例保持。不能把原生Dock4当实际交接成功。全局低accel候选已撤销，不覆盖C原失败。

后续改为vehicle_profile.loaded_velocity_smoother，仅loaded后hold/停稳时通过标准ROS参数服务应用并读回；原Nav/Dock继续原YAML参数，cleanup原动作终态/quiet后恢复。原生smoother1.3.13按wall timer，配置值不直接称源时间实际加速度。worker在142只做无机器人原生参数验证；正式组合尚未重启。新薄模块cooperation_loaded_limits.py将计入39项文本观察。知识状态pending(root)，尚未把候选当长期已验结论。

载货阶段原生参数适配已冻结。156helper/core/oracle定向检查与实际142无运动服务验证通过；仅官方smoother active/get/set原子ACK/独立get恢复，零运动命令，原node/142均清理。根当前反馈回归1605项通过（control875、mission209、autonomy61、frontend460），零skip/缺依赖。manifest缺loaded字段旧路径无RPC。正式D开始，39项源/生成输入起止观察，仍保留原360/1400/5600秒预算。

知识回写updated（本地）：Wiki/ROS2 与 FishBot第19节新增“换车型与雷达：配置、进出站和观测分别验收”，以及开发知识入口新增相应触发词。根已读回原文与锚点；保留该独立知识仓原有dirty/untracked修改，未声称远端发布。此条只记录已验证的几何/观测/原生服务机制，不写尚未完成的运输成绩。

D首批178.20墙秒，task b14afb41-686c-43d1-8444-3dca48cab7c0；loaded参数原生独立GetParameters/GetState读回通过，cleanup已恢复实际原值。egress NavigateToPose UUID92d84fb415ee411f8bcca714ff1e9f3e仍选择原位正转至.16483rad，RPP collision/error104/status6，未到最终目标；oracle=false。source39/generated11/quiet/guard/owned/9110/保护实例均保持。D采集308对点云校验过，仅载货单epoch，缺空车/reset导致通用probe顶层false，不能称完整sensor面板过。

改进出站约束：J100使用已安装且原YAML已启用的Nav2 DriveOnHeading，manifest.egress_motion记录body相对distance/speed/source时间allowance，nominal egress_pose不冒充原生map目标。实际步长来自staging_distance（ideal .7/vision .65），原碰撞检查保持。原owner派发、同UUID终态/取消、最终Nav目标/原K评分继续复用，observer/cleanup将核新原生状态话题。

普通J100导航使用原生StoppedGoalChecker，保留原.015/.035位姿门槛，速度门槛对齐原物理.01；RPP角加速度.2匹配载货平滑预测。Dock仍原smoother参数，FishBot默认配置不改。成功路径等待原生零命令平滑停稳后才hold，失败/取消保持原即刻hold。4composition与13prepare定向回归已过；新的Drive合同/原生面板待worker冻结后执行。

正式E首批158.74墙秒，Nav UUID4a6cface6562492090af8787a87304e3超原120秒明确取消，未进入Dock/机械臂/Drive；source39/generated11/quiet/guard/owned/9110/保护实例均保持。实际指令连续w=.01、hold=false，轮速与真yawrate约3.93e-6；恢复w=1后能转。官方RPP逐周期按当前odom而非上一条命令夹限，.2/20=.01且odom低于原.001阈值，导致静摩擦起转死区。该候选失败保留，不提高超时或放宽评分。E889对点云逐点一致，但只有空车单epoch、缺载货/reset，顶层probe仍false。

E之后最小候选仅J100 navigation改为RPP max_angular_accel=2、rotate_to_heading_angular_vel=.1；启动单周期上限.1脱离已证实的.01死区，原地转速单独限.1。StoppedGoalChecker原pose与.01速度、Dock普通smoother、loaded-only.1/.2与清理均保持。4composition通过；实际起转/收敛与完整矩阵仍待验证，不称已经解决。

F首批286.74墙秒：Nav/Dock成功，实际停车约10mm/.01784rad，真实抓放/留盘/臂回位过；Drive UUID724472acb864461daf181b8df3a4f4db独立GetResult status4/error0，35.22源秒。成功软停后最终载货Nav UUID335236b2a0a6444398860b6f48a417c8启动，随后cargo_retained触发并明确取消status5；完整oracle=false，不续发后两批。source39/generated11/quiet/guard/参数原值恢复/owned/9110/保护实例保持。当前核对最后一段接触间断，不能把Drive过或cargo位移>.5m算全运输完成。

F失接触source238.10精确重放复现+32.449µm正gap；floor阻尼1.5/2仍离面，故不采用物理参数候选。同F235.88静稳快照、原accept/500Hz、实际cmd前缀与合成延长2s有限重放：1×/0.5×/0.25×在210个20ms样本失接触4/1/0，500Hz 19/7/0；header ZOH不是精确原执行相位，不称全任务通过。G最小候选保留原物理与评分，仅载货段max_accel[.025,0,.05]、max_decel[-.1,0,-.2]、max/min_velocity[±.03,0,±.08]；heading RPP起转保持2/.1。四参数native helper兼容原2字段，112联合与17helper过；142无机器人以角上限.05的4参数ACK/读回/恢复已过，实际G .08仍须现场读回。

G执行前根既有反馈回归1612项通过（control882、mission209、autonomy61、frontend460），零skip/缺依赖。知识回写updated（本地）再次读回：Wiki/ROS2 与 FishBot第19节补正Drive body请求与map参考、RPP实测速度逐周期夹限，开发知识入口补低速起转死区。未发布独立知识仓、未覆盖其原有dirty/untracked内容。G首批原K与目的地完整评分过，终点误差22.22mm/.00430rad；已在原world真实reset进入第二批，整四组合面板仍in_progress。

G整行646.13墙秒：job1完整K和目标通过；原world真实reset后job2在source537.02失接触，精确forward接触0、signedgap+1.228µm，仍在盘中央，完整评分false，第三批未派。两轮source39/generated11/quiet/guard/四参数恢复/owned/9110/保护实例保持。实际raw5311对跨2epoch/1reset全匹配，空载removed0、载货10–21、外部首回波保留；仍缺第三epoch，完整coverage=false。

H候选只调J100参数：空车heading cap=.4、RPP maxa2；载货保留accel[.025,0,.05]/decel[-.1,0,-.2]，速度上限降到[.02,0,.05]及对应负值。已有阶段native cap使空车不必再受.1慢转限制，原360任务上限不改。G2重新静稳1s后，原/低速/两soft liner四组都未复现失接触，因此不声明因果修复、不采用liner；低速候选仅有降低滚俯和扩大负gap余量的证据，必须新原生面板。旧成功和失败保持原件。

H整行596.89墙秒：job1/job2完整K与目的地过，原world两次reset成功；job3在Dock中因共享物理反馈时间失效取消，原Nav4/Dock5，未装货。完整行false，全部source39/generated11/quiet/guard/原参数恢复/owned/9110/保护实例保持。H实际5394对raw/filtered跨3epoch/2reset合同过，第三epoch只有空车，不能称三批载货覆盖。后续I保持H源码/输入模板与评分不变，作为同候选复现而非改进；不再启额外raw/native probe，H采集已有前两轮载货与两次reset实证。时序具体原因由transition只读核，未知不归因网络。

H时序只读取证：首次Dock cancel前bridge物理callback约.458s未进入，缓存双龄期.46/.4626；独立observer生产流持续20ms。后续HTTP组装/锁等待.29–.47s有据，但不能证明首发。该性能风险仍pending，owner=root，最短入口H job3/readonly-freshness-review.json。I相同runtime39源码复现正在跑140/9110，私有matrix-final-i；未再启动额外采样器。

I同H源码复现整行911.54墙秒：job1/job2完整过；job3原K、抓放留盘与出站均过，最终B的carrying Nav UUIDc8bb1e823a714534aa8f3030ae853621原120墙秒超时并明确取消5，未通过目标/朝向验收。终点约42.85mm/.53574rad；source39/generated11/quiet/guard/四参数原值恢复/owned/9110/保护实例保持。未把原K通过或近B当完整运输成功。

下一候选改为载货期间通过原生RPP动态参数主动低速规划；官方1.3.13 smoother的absolute速度分别clamp在scale_eta前，scale_velocities bool也未在dynamic callback处理，不能通过flag显示值假称曲率保持。复用现原生参数状态机，新增固定白名单DOUBLE的LoadedRppLimits/vehicle_profile.loaded_controller，hold下apply/ACK/readback，原cleanup恢复；原控制器、动作和所有物理/时间门槛保持。transition负责helper/bridge/定向tests，root负责profile与文档，不运行新动作直到冻结。

J首批97.78墙秒：task 76394d20-0a6f-4110-b80f-f0ab3df8d218在arm_grasp因物理反馈源龄失效失败；两组loaded参数均not_applied、无参数RPC，不能归为RPP候选失败。独立只读报告显示source74.98的station_pair约338ms，new physics75.28已进入回调却等待control锁，fresh抢先读取74.96/Clock75.30后失败。graph/parse/admission不足以解释全部338ms，未证明网络或单一publish根因。source39/generated11/quiet/guard关闭/owned退出/9110关闭/保护实例保持；候选暂停，先修已证实的缓存提交与大控制锁竞争，不改变原新鲜度阈值。

2026-10-21 缓存最小修复冻结：高频physics提交使用独立短cache锁，不再等待感知/HTTP持有的大control锁；fresh保留control原子语义并在短cache snapshot后校验，reset统一control→cache切回合并清旧。原-.1/.25源龄、.5接收龄不变，无wait/restamp。真实线程与核心/loaded/oracle/acceptance共209项过。J已进入回调的提交竞争有直接修复；H未进入callback间隙仍未证明解决。K在原140/9110新目录启动；F1仅新增未加载模块/配置并行，所选39项运行源保持冻结，不计F1静态几何作K运输成绩。

K整行721.66墙秒未通过：job1原K/目标/同UUID路由过，终点24.95mm/.01432rad、连续停稳2.60源秒；两参数组apply/readback及baseline恢复均收到。job1 physics锁等待最大.311ms，但仍记录source-age .28诊断，不称彻底消除时间异常。第二单caller360秒越界，原observer评分false；源码39/生成11保持，owned全部退出/9110关闭/原保护实例保持，实际任务终态与异常清理细节正由只读审查核对。第三单未执行，不把第一单通过外推整行。下一步先交付独立F1切片，P8时限/动力学整改保留，owner=root。

K2精确复核：原桥task failed/协同任务超过总执行时间，在+360.034墙秒取消原finalNav(仅active80.094wall/54.34source，未超120)，原生5。末位置37.818mm尚在4cm内，但偏航.400904rad未达.05；cargo仍留盘，取消附近保留一条arm_home_quiet=false。前段至装货确认同源约123s，但第二单耗212.60墙秒、第一单169.27；源推进率约.595/.761，具体性能瓶颈未知。两组参数恢复/明确任务failed/native5/独立quiet.88source/owned退出均核实。另计时文件0字节：frames.close thread.join被KeyboardInterrupt打断，跳过dump，随后rclpy.shutdown already-called掩盖首因。只证明退出诊断丢失，不解释运行中RTF下降；拟局部修复，等待当前F1结束后写。

保护记录边界补正：protected_instances_unchanged仅比较预声明六个systemd单位名；当前F1读回这些before均not-found/inactive，不能据其宣称旧107/114活进程持续保持。未向旧实例发送动作或stop，不补启不属于本轮的旧实例。

2026-10-21 清理诊断修复实际读回：独立无动作idle-v2 2源秒/1000步正常退出，timing有效、finalization_errors=[]；F1 occupied-v2实际launch关闭时也保存2921字节timing，保留node.destroy_node的KeyboardInterrupt，不把它隐藏成clean。mj_step171244次、累计285.251s、max122.811ms，publish累计75.315s；嵌套stage是包含式墙时间不能相加当CPU总量。高频源门槛未更改。

F1 occupied-v2终点发现SimpleGoalChecker早锁XY后在转向期间漂出原15mm，native4时真值43.447mm，随后hold仅再移动31.9µm。新增组合场景暂改goal checker stateful=false，不改15mm/.035rad；仍在核对RPP自身XY锁，不能提前称充分修复。自定义雷达topic/min/maxrange已共用configuration同步到发布/两个costmap/CollisionMonitor/manifest，根6项composition读回过。

### L 候选：原生轮速跟踪、同步线速及持续XY检查
20例原kv8低速面板确认v=.02/.03时小yaw请求±.01几乎未执行（真实约±4e-6rad/s），提高线速本身不解决。独立16例kv16/32对照采用当前K2落稳状态和原Physics/WheelCommands，8source s阶跃/4–8s稳定窗；kv32在v=.02,w±.01产生+.010608/-.008285，空载±.3产生+.278861/-.279808。只改原生执行器gain/bias，原4.5有效轮距、质量/摩擦/12Nm保持；六载货例50Hz谓词0失败，+.03保留1个500Hz底接触false。旧超出指定面板的6例和一次私有脚本中断也保留，未混作正式面板。

根采用车型级原生servo kv32，并将RPP/下游/Drive载货线速同步.03，角上限.05和原加减速不变。goal checker及RPP成对stateful=false，防XY早锁；本机1.3.13实现已核实，不调整15mm/.035rad或物理4cm/.05rad/360s。完整136项离线检查135过/1失败：新增empty小转向测试错误套用loaded>.004精度边界，原signed .3转向仍过；根将新增回归限于防4e-6无响应（>.001），保留原失败日志，定向复验待回读。该新测试不能证明精确跟踪。旧30组kv8标定元数据已独立嵌套，不冒充kv32精度。

原始开发证据：~/.cache/fishbot/profile-reuse-20261020/calibration-low-speed/{summary.json,controller-candidates-requested/summary.json,provenance.json}。首批软件checkpoint bb9141e已推origin/main并读回一致；L新增适配尚未提交，四组合最终运输仍待执行。当前owner=root，不启动实车/训练/云GPU。

L冻结前定向回读：signed原回归独立1/1；修正后的skid+composition 8/8（14.511s）；生成prepare合同13/13（12.311s）。control-l的891项中890通过，唯一失败为未更新的出站速度旧期望.02，已由13项prepare完整复验覆盖，保留原fail报告，不伪称那次整组全绿。新源码差异检查通过。知识第19节与入口再补轮速伺服/双重XY锁定，已读回；仅本地知识回写。下一步由内部native_matrix_l按四组合串行执行，同一源码，不重跑F1 open来充数。
