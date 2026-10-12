# 进度

## Current

2026-10-12 本次稳定性修复已完成：原20种子首试20/20，零重启，5次运动断流同Goal恢复；同launch PID680651与单一client连续1808.296秒，25/25动作及物理评分通过。完整就绪窗45202帧零孔洞（接收82.449ms、源56ms）；root独立延伸到recorder退出的45203帧同样连续。12执行源SHA逐blob匹配代码commit5746210，已推送并读回。原19/20、23/24失败及repair-a中断保留。详细数据与额外冷启动空窗/窗口截断见docs/SIMULATION_CAMPAIGN.md；待验收和正在运行文字以下保留为本阶段过程记录，不代表仍未完成。

2026-10-12 用户要求解决随机启动失败与长测采样间隙，修复版正在验证。已增加有界MessageInfo/分段计时，确认旧记录器4936帧重复写327374次；新记录器逐帧写、就绪后停止启动RPC，Goal客户端常驻。Nav2只查一次的启动确认已加一次有界只读重查；9项生产C++函数行为与真实3项延迟服务故障注入通过。321项离线回归零跳过；checkpoint改用独立当前ROS时钟并修正先读帧后取检查时钟的顺序，16项相关回归通过。长测repair-b使用同一launch、同一client正在运行1800秒，随后原20种子。repair-a主动中断记录保留，不累计为完整长测；旧19/20与23/24保持failed。

验收阶段改为domain96长测与domain102随机批次并行。诊断阶段已串行完成；启动并行前主机16逻辑核、load1约5.23、MemAvailable约10.7GB，memory PSI为0。root监控长测，design worker串行跑原20种子；两批各自ROS域、进程组、输出目录与来源，记录重叠区间和主机压力。禁止并行编译或变更已执行源码。此测量明确包含两批共用主机，不能写成无其他负载的实验。

2026-10-12 四项实现与本轮实测完成，43文件源码已提交推送，远端读回一致。定位r的14项原验收全部通过：两恢复12.084/37.071秒，原Goal取消5，同目标新UUID成功4，末真值11.4037厘米/.07711rad、停稳1.308秒；root独立复算4232真值及恢复/动作停车，三源SHA一致。控制XY容差只复用既有passage的.03，物理.15、速率、45/240秒预算保持。此前a–q失败继续保留。巡检f与网页闭环通过；随机19/20、同PID312439长测1854.274秒/24个动作成功/23个物理证据评分，稳定性整体failed。原第8启动失败、第18真值间隙344ms及其他静止空窗继续保留，不自动重试或改判。

## Done

AMCL短往返c完成2/2物理评分。对象巡检f135.802秒，18帧/6视角/7真实动作，遮挡换位cup恢复，缺席保持unknown且无cup误报，返航.09044m/.11274rad，末尾1s停稳；13源码SHA、照片与模型输入SHA、双龄期独立读回通过。网页原真实确认/取消/结果异常同UUID收束和CM展示通过；新增接收Future异常持原id禁止重发，44桥接/15前端回归通过。整合check-feedback n版已296项通过、0跳过（178控制、44任务、59自主、15前端）；对应源码与实际仿真分别验收。o源码296项亦已通过。p完整回归因g++编译60秒超时failed，原回执保留；相同源码随后单独原生测试7.858秒通过（13场景），串行check-feedback共298项通过、零跳过。r只收紧控制XY容差并读回七项控制参数，当前源码再跑298项通过、零跳过。前端待提交快照60个SHA保持，类型、构建及相关lint通过；未验收的同期雷达14项继续独立保留。

## Remaining

本轮源码与实测记录已交付。后续pending由root接续：随机启动失败与长测记录间隙、生成参数启动前收据、AMCL挂起证据及同期15项未验收改动；最短入口见以下各节。随机与长测已完成实际测量但稳定性门禁未通过，接续项见下文。

## Issues

campaign记账缺口已修，6项回归通过；a原执行/新分析SHA分开保存。运行中random只加载修改前campaign；改动只在run_soak真实终态计数，原文件按启动SHA完整归档execution-source-campaign.py。对象采样门限22cm/.25rad，f最大21.46cm/.16194rad，不声称15cm导航精度。定位e终点17.74cm失败，f全局多模态，g官方prob模型90°假匹配均被门禁拒绝；h保留原map/target/kidnap/评分并恢复e likelihood参数及低速三字段。nomotion只在新鲜odom静止时调用。网页原运行未记录执行SHA，不能事后补造；新harness启动前记录源码。

## Next

96b已结束且清理，root独立复算24个动作、物理误差、双龄期、停稳和源哈希。PID成员全程相同，18进程/895FD恒定。web100已清理，99r定位验收已通过并清理；旧domain93保持。root已逐例重算20随机检查，19实际Goal终态4、误差2.42–3.45cm，4运动断流同Goal恢复；第8保留启动失败。网页启动前30输入SHA和2次取消真实连续1.32s停车均独立读回。全部失败和来源SHA保留，root串行整合。

## 固件遗留接续

pending，owner=root Codex：保留未跟踪 `fishbot_motion_control_microros/release.sh`，不执行或提交。已只读核对：它会改版本头、安装未钉版本的esptool、重建micro-ROS依赖，并按4MB布局合并0x1000/0x8000/0xe000/0x10000。尚未验证BOOT_APP0_BIN与所选Arduino工具链一致、发布版本可复现、实际分区兼容及私有配置不会进入产物。最短接续入口：先对该脚本和platformio配置做来源/分区/构建依赖审查，再在无私有配网参数的隔离构建目录运行构建并核对输出，不接已售实车。本次纯仿真功能不依赖此脚本。

## 参数来源接续

pending，owner=root Codex：本轮96b的AMCL生成参数没有启动前hash。运行中后验读取SHA为2e229033…，当前passage配置与package Nav2 AMCL输入可逐字节重建该文件；回执明确after-start，不能证明先前或全程未变。11运行源码SHA仍全部一致。最短接续入口：在 `fishbot_passage_sim.launch.py` 的AMCL YAML生成后、返回节点动作前记录原始AMCL配置与生成参数SHA，再用下一轮原有入口核对；本轮冻结源不修改，不补造历史回执。

## 知识收尾

updated：root修订既有Obsidian `Wiki/ROS2 与 FishBot.md` 第11/12/13节，记录调头进展与定位分别验证、CM变化与心跳、未知Goal所有权、Guard局部处理滞后证据边界和统计分母。`Wiki/开发知识入口.md`同步触发词与段落锚点；每处均读回核对。未复制原始日志/地图，未改Codex memory。项目状态留在本计划。两页在既有干净的远端基线worktree提交推送，commit 26d787dd23dd834421c1bf956ec1afe6c4482b1a，远端HEAD已读回相等。随后新增第14节与索引触发词，记录轮轴前2cm原点的圆弧位移，704帧实际真值由root独立复算；commit ebf8b1ee00929e15d5e9e6766a1e4dbd84d84cdc已推送，远端HEAD相等。原19条反馈与历史定位清单逐字保留。原vault的分叉历史及其余dirty/untracked积累保留，未合并或重置。长测b的动作/评分区分和无法确定间隙机制属于已有第13节边界：already_covered，不另建重复知识页。


## 稳定性接续

pending，owner=root Codex：随机种子1207启动失败及长测b第18真值接收间隙尚未消除。实现和本轮测量已交付，稳定性未通过。最短入口是对应外部report/recording与 `docs/SIMULATION_CAMPAIGN.md`。先复用rclpy MessageInfo记录DDS到达/序号及truth与clock回调，并分段测量spin、文件写入、生命周期查询耗时；用有界窗口保存截断信息，缺失元数据保留unknown，区分来源后做最小修复；保持300ms连续性和250ms双龄期要求，新一轮使用新目录，不覆盖本轮失败。不从24个action4推断24个物理证据验收通过。

## 既有知识库工作目录接续

pending，owner=root Codex：主vault先前观察的分叉历史13/15及其他约30项dirty/untracked保留（本轮未fetch或重写主工作目录），已交付的两页在远端基线独立推送。最短入口为主vault `git status --short` 和 `git log --left-right --oneline main...origin/main`，按既有任务记录协调内容后串行整合；不盲目add-A、rebase或覆盖。此次FishBot两页已推送，不由其他历史积累阻断本轮交付。


## 同期雷达界面与Goal API改动接续

2026-10-13 updated：已从 Unitree 原对话与 NOTES.md 核对原14项成果来源，在新的 `plans/fishbot-unitree-console-20261013/` 中审查、复用并完成前后端测试及隔离domain106实际验收。两张PNG确认为相同旧离线演示，不含实测地图。以下pending文字保留为当时接续记录；本项已由新计划收束，独立固件release.sh仍按“固件遗留接续”保留owner=root。

pending，owner=root Codex（原编辑者待核实）：收尾期间新增雷达视图、地图点选与Java `/goal_pose` API修改，mtime表明本轮正在写入，未找到所属本地计划。本轮先只读核对并保留，不覆盖或混入已冻结的仿真功能。涉及 `apps/fishbot-control-station/backend/src/main/java/com/fishbot/station/service/{ControlService,RosTopicService}.java`、`web/ControlController.java`、新增 `domain/NavigationGoalRequest.java`、`src/test/java/com/fishbot/station/service/RosTopicSafetyTest.java`；前端 `src/components/radar/{radar-viewport,radar-workbench-page}.tsx`、`src/lib/{api,radar-workbench,radar-workbench.test}.ts`。实际路径均相对上述backend/frontend根。

最短接续：先确认这些文件是否仍在编辑及目标域；读回 `/goal_pose` 请求、停止锁与源时间语义，再运行backend现有 `RosTopicSafetyTest`、frontend雷达工作台测试、类型检查与构建，使用独立仿真域验收真实接受/取消和到点。不得以HTTP发送成功代表Nav2接受或物理到点。未运行实车，也不重启domain93。仿真网页的30个启动前输入不包含这些同期修改，原回执来源继续单独核对；本轮前端验证采用待提交文件快照，60个启动前源码SHA在验证后仍一致；类型检查及Vite构建通过，避免将进行中的界面改动冒充已验收版本。后续又出现backend `NavigationStateService.java` 与 `NavigationStateServiceTest.java`，同样保留pending。静态审查发现offlineTelemetry请求返回200只证明本地处理，不能作为Nav2接受；primitive double缺省坐标须单独验证。backend使用现有 `./gradlew test --tests '*RosTopicSafetyTest' --tests '*NavigationStateServiceTest'`，不另建框架。

后续新增 `apps/fishbot-control-station/docs/fishbot-console-scanmap-goal.png` 和 `fishbot_radar_goal.png`，与上述12项源码一起保留，合计14项。图片存在不代表对应Goal API或实车验收通过；先确认产物来源和隐私边界，再决定是否交付。

## 定位参数与观察接续

pending，owner=root Codex：l轮AMCL参数设置无回执且位姿停止；官方源码存在候选锁顺序反转，但没有挂起线程栈，不能确认为死锁或CPU饥饿。n使用原子设置减少回调次数，4次Set/Get均确认；此单例不能证明锁风险已消除。最短接续：仅在本任务隔离域复现挂起时，在清理前采集所属AMCL线程栈/锁及阶段时间，再决定官方版本或最小上游补丁。不改系统Nav2安装。

updated：既有Obsidian两页新增FishBot第15节“定位失效与观测暂不可用分别判断”及入口触发词。逐字核对原19条反馈、前14节与历史清单未变；两页在干净远端基线worktree提交00c84a228692fc8f30adf91bde45964caceac4bb并推送，远端HEAD相等。原vault其余工作与分叉历史继续保留。随后精确指明domain99使用Collision Monitor，commit 65046f33e0c0be404f30a49878fc7bf6ebe421f8已推送，远端HEAD和原页读回一致。


## 本轮实测交付边界

定位r的完整合成场景通过，不代表AMCL所有随机粒子初始化或生产稳定性通过。q完整链成功但物理误差15.3663厘米，仍failed；r11.4037厘米通过原15厘米门槛。原速度、模型、45/240秒与真值300ms连续性要求保持。已有有限TF等待不重置整个Goal的共享次数；实际Wait日志缺少动作UUID/黑板，次数归属仍按证据边界记录。p的多秒空窗、后来的OOM与编译异常不能凭时间相近互相归因。

知识收尾：already_covered。本轮控制容差与物理评分分开、坐标点圆弧位移、定位失效与观测不可用、失败分母与未知Goal所有权均被既有第13–15节覆盖，不新增重复知识页。项目当前结果只更新本计划与PROJECT，原始结果留本机。


## 源码交付

updated：43个已验证文件提交为 76d67d48731f14a934147d467cd350d0c152397a，推送到既有qiaoqiao2521/fishbot-ros2-slam-tools的main；远端refs/heads/main读回与本地相同。身份qiaoqiao2521/238822818、仓库ID1381244533/public和fetch/push URL均核对，未修改账户配置或可见性。43个工作树与暂存blob的SHA一致，60个前端candidate blob与验收快照一致，文档18个相对链接有效。298项回归零跳过，类型/构建和相关lint已通过，定位r与巡检f的运行源码来源核对。定位a–r、对象a–f及q/r宿主证据已按逐文件SHA归档到本机缓存；地图、权重、日志与图片产物不入本次提交。

剩余15项为上述14项同期雷达/API/图片和legacy release脚本。保留原文件，owner=root Codex，原编辑者仍待核实，验收入口已记录；不以本轮成功冒充这些改动通过，也未盲目add-A。旧domain93与网络保持，本轮实例已清理。知识第13–15节already_covered，实际项目状态留本计划。

## 稳定性修复知识回写

updated：root在既有 `Wiki/ROS2 与 FishBot.md` 新增第16节“状态变更成功与查询确认失败分别处理”、第17节“按新帧写入，使用独立当前时钟验收”。来源为官方1.3.13调用链、真实服务延迟3例及分段计时；底层DDS原因仍unknown。`Wiki/开发知识入口.md`同步触发词与锚点。主vault与干净远端基线worktree的两页逐字相同；插入后剔除新增段落可还原原页，原19条反馈及前15节保留。两页读回、diff与锚点已核对，commit 08fac89b5b1817d8d507eff7530b1786390fc59d已推送，远端HEAD相同。未改Codex memory，主vault其他改动及分叉历史保留。

## 本次稳定性修复收尾

Done：321项离线回归零跳过；最终checkpoint读序16相关回归通过；生产函数9项、真实延迟服务3项通过。原20随机20/20、0restart/0unknown，每个Goal一次send；常驻长测25/25、完整就绪连续性与独立终点钟通过。182资源样本18进程/895FD恒定；long全部19 PID已清理，random父和20launch PGID均空。原source_revision保留f3ba429，12实际文件SHA与已推送5746210的blob一致，AMCL启动参数及实际loaded库校验。两批并行主机负载范围已留私有monitor，不声称空载实验。

Remaining：本次两项已授权目标完成。若接续额外范围，owner=root：随机1208/1210/1213发送前约.35–.37s空窗、长测就绪前.346s空窗和有界诊断事件截断；保留原truth，不提高门限。最短入口为新campaign原始recording/trace及private independent_stability_readback.py；优先利用已存DDS/clock/stage观测，不据时间关联编造底层原因。同期15项仍按原明确接续项保留，未验收即不混入本次交付。旧domain93、网络和实车不操作。

知识收尾：updated，第16/17节与入口已读回、提交推送08fac89；原19条反馈及前15节保持。最终数值与本轮状态留项目及私有验收汇总，不另建知识状态表或修改Codex memory。源码与结果元数据串行整合，所有原失败目录保留。
