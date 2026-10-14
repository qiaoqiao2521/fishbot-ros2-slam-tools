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
