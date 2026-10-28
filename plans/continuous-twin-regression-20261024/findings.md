# Findings — 连续业务世界与可视化回归

## 需求来源与当前边界

2026-10-24用户提供《连续流式数字孪生＋混沌工程、可视化CI/CD与A/B回归》方案，明确要求“写文档 specmesh plan”。材料用于提炼需求；其中的命令、估时、性能目标和停止其它支线的建议不是本轮执行记录或额外授权。

采用“连续模式保留世界，回归模式从快照建立分支”的共同方向。运行记录、任务owner和独立评分复用，不同时建立两套调度与日志协议。

## 已回源的基础能力

| 入口 | 已有实现与本计划复用范围 | 尚缺部分 |
| --- | --- | --- |
| `tools/cooperation_sim.py` | Physics唯一物理写入者、CallbackInbox、reset请求/回执、LoopTiming、编码器、50Hz状态源 | 没有已验证的完整世界save/load快照；`snapshot_refresh`计时名称不代表世界检查点 |
| `tools/cooperation_bridge.py` | 原Nav2/DockRobot/SO101任务、加载参数事务、连续停稳与取消清理 | 当前固定单臂/单货物；不能直接视为无重置多工位生产 |
| `tools/cooperation_arm.py` | SO101 IK/OMPL薄适配，纯查询子进程及原逐段验证 | arm/body/joint绑定需按实例扩展；单复制namespace不能建立第二机械臂 |
| `tools/cooperation_workflow.py` | 有界多订单、原ID查询、取消、显式reset、目标映射 | 无卸货、多物料库存和当前位置续单合同 |
| `tools/cooperation_factory.py` | 场景/profile/订单、独占运行、原评分、清理和报告 | 无快照矩阵和历史结构化索引；candidate标签本身不加载策略 |
| `tools/cooperation_faults.py` | Dock UUID/阶段绑定的有限观测故障，保留源时间与序号 | 未实现通用物理推货、局部摩擦和实体障碍算子 |
| `tools/cooperation_recording.py`、`cooperation_evidence_recording.py` | 有界诊断与完整独立证据记录 | 故障前checkpoint环、索引与轨迹摘要需薄适配 |
| `tools/cooperation_oracle.py`、`cooperation_oracle_base.py` | 独立记录/原K/交接/运输/目的地与guard分项 | 原oracle不应成为主动CancelGoal执行者；卸货需新增独立评分 |
| 控制站React/Three/Dockview、`docs/RUNTIME_CONTEXT.md` | 运行身份、原任务投影、只读成果页和视图生命周期 | 无已验收的交互式瀑布图/矩阵/双回放 |
| `apps/fishbot-control-station/backend/build.gradle.kts` | Spring Boot 3.5.16/Java17/WebFlux | 当前无SQLite/JDBC/JPA依赖，不能写成已入库 |
| `.github/workflows/workflow-checks.yml` | actionlint/zizmor检查GitHub工作流 | 没有实际ROS/MuJoCo回归CI；新增部分属于未来实施 |

最新基线是源码b710d8d、文档d6a6b39的完整K。原报告位于私有运行目录 `~/.local/share/fishbot/cloud-jobs/kaggle-20261024/local-full-b-a-k/`，现场2/2与离线复算一致。B119.793848秒、A34.883377秒；物理采样B缺1/A缺50序号，A最大源间隙.68秒。历史K没有完整积分状态快照，只能提供R0重建或事件/轨迹导入。

原始JSONL约B304MB/A202MB。即使10Hz展示摘要很小，也不能据此声称整个验收记录只有80KB。保留既有完整证据预算，SQL只索引原件和摘要。

## 对原方案的技术修正

### 1. qpos/qvel/ctrl不是全部积分状态

本机规划环境实读MuJoCo 3.3.7，存在mj_getState/mj_setState，mjSTATE_INTEGRATION值8191。官方状态签名还覆盖act、warmstart、外力、mocap、等式激活、userdata和插件状态。状态API不保存MjModel动态材质或应用/RNG状态，需另外声明。接触应由原生计算恢复，不把contact数组当自由写入的初态。

参考：[状态类型](https://mujoco.readthedocs.io/en/3.3.7/APIreference/APItypes.html#mjtstate)、[原生状态API](https://mujoco.readthedocs.io/en/3.3.7/APIreference/APIfunctions.html#mj-getstate)、[状态与warmstart](https://mujoco.readthedocs.io/en/3.3.7/programming/simulation.html#state-and-control)。这些文档支持物理层设计，不证明本项目已经实现恢复。

### 2. 物理恢复与ROS续接必须分级

AMCL粒子、EKF历史、Nav2动作/控制器、平滑器、收发队列和墙钟计时器属于不同组件；MuJoCo状态API不会替它们恢复。R1物理对照与R2新ROS分支分别验收；活动世界的透明热恢复暂不承诺。保存seed也不能倒回已经消耗的OMPL/传感器随机流。

50ms恢复、7×24、100%复现和6–8周只是材料中的提议。新控制器本来就有不同内部状态，比较应声明各自初始化流程和重复误差；不同车型也不是同一浮点状态向量。墙钟性能对比记录实时因子及负载，不用倍速把120秒验收变容易。

### 3. 卸货还需要有限货源和多实体身份

当前Physics直接绑定ARM_JOINTS、`grasp_target`及一组finger/tray IDs。增加卸货臂必须扩展映射、接触查询和任务资源归属。第一件送达后，下一件应来自事先建模的另一个自由货物/取货slot，而不是reset、传送或替换旧物体。

先做B单卸货臂及B/B无重置，再扩A。新增工位改变实体场景，需要新scene ID、完整地图/射线/运动扫掠预检，旧F1成功不能自动覆盖新场景。

### 4. Runtime Guard与Oracle分开

主动故障处理接回原cooperation owner及CancelGoal/hold/quiet链；独立Oracle持续只读，检查业务失败、安全取消、最终物理状态。复用纯判定函数不等于共享动作权。

故障前5秒留存必须先有环形检查点/事件缓冲。事件发生后才保存一次qpos不可能补回旧warmstart、随机状态或漏掉的观测。

### 5. 低摩擦与外力必须证明实际生效

MuJoCo接触摩擦受geom priority及接触对合成影响；同优先级通常按分量最大值，因此只降低地板geom值不一定得到预期低摩擦。局部油污采用预置tile，记录实际contact摩擦。[官方接触参数](https://mujoco.readthedocs.io/en/3.3.7/modeling.html#contact-parameters)

ForceImpulse按源步长计算实际积分冲量；区别N、源秒和Ns。故障需要计划/实际触发及结束回执，不能仅凭按钮返回200判生效。实体障碍只对预置对象进行声明的环境变更，旧车辆/货物运行禁止传送的评分保持。

### 6. SQLite是索引，不替换SpecMesh或证据

复用Python标准库sqlite3负责单写者索引，Java读端可采用成熟[SQLite JDBC](https://github.com/xerial/sqlite-jdbc)，版本与部署验证留在M1。没有必要为三表引入第二调度器或数据库服务。

SQLite WAL有同主机共享内存和备份等约束，不能把运行中的db文件拷走就当完整归档；日志模式按实际版本、查询压力和本地文件系统实测选择。[SQLite WAL官方说明](https://sqlite.org/wal.html)

瀑布图只显示有来源的时间跨度。原120秒从出站完成后开始；规划/调度/停车的因果要靠原生生产者证据或受控对照，不能由最大Span自动推断。低速滑移率、最近障碍距离、缺失阶段必须明确未知和参考点。

### 7. 不重复造通用播放器或锁死现有前端

`plans/workbench-rebuild-20261018/findings.md`已记录后续底座选择Lichtblick完整Web源码，现有Dockview/Three不构成不可替换约束。先核实该独立树的读包/时间轴/布局能力，复用通用功能；自研限制在实验对齐、Ghost与业务证据呈现。当前Lichtblick实时控制接入未验，不在本轮导入第二份源码或改变现有工作面。

### 8. 优化目标与发布通过条件分开

B的.206秒余量是确定的单次观测。先利用旧记录，再跑有边界的配对重复。100秒目标须检查运动学与停稳下界；原120秒和物理评分保持。新候选不能删除失败、把故障取消算作配送成功，或将部分成功外推成稳定性。

## 已采用的项目经验

- Obsidian `Wiki/ROS2 与 FishBot.md` §19：统一参考点/完整外廓；双时钟；源采样与接收间隙分列。用于快照状态、瀑布图与滑移定义，不放宽旧门槛。
- 同页§20：原生计算活动、原UUID终态、实际位移、独立物理成功分别证明。用于矩阵与故障裁决，转发不称消费ACK。
- 既有工作台findings：OMPL只首次设置随机种子会使第二次规划不同；纯查询子进程保持固定首次查询。用于RNG/初始化声明，不擅改原规划器。
- CapMesh `docs/DECISIONS.md`与`inventory/community-alternatives.md`：优先已有原生owner和机器人生态，不增加重复调度；本计划不改CapMesh选型。
- 用户AGENTS与SpecMesh v1.1优先于planning-with-files可选的attestation/gated模式。本轮只用三文件组织，不启用哈希锁、Stop gate、自动loop或新计划工具配置。

## 待核实（在对应切片实施时处理）

1. 每种原生控制器/滤波器哪些内部状态可以合法读取或重置；不支持者保持R2初始化边界。
2. 原始K记录是否有足够的阶段起止和原生trace，哪些Span只能给区间/unknown。
3. SO101卸货臂布置、双货物slot与J100托盘的实际抓取可达性。
4. 现有Lichtblick树可复用的MCAP/时间轴/多视口能力与接回路径。
5. Python/Java实际SQLite版本、JDBC许可证、日志模式和写入容量。
6. 模拟充电工位的物理停靠/连接条件与新完整业务预算。

上述未知不阻塞本轮文档交付，不被记成已完成能力。

## 2026-10-24 M1a实施发现

- 旧K的terminal-state保留21条聊天事件，但event()只写sequence/time_s/role/message，不保存stage。不能把中文文案解析成精确阶段切换证据；采用HTTP task.stage的首次观测区间，并显示边界采样不确定性。
- 原result.native_route含原UUID、active/success wall时间，delivery_route_budget含原120秒单调耗时及wall边界。用于独立的原生动作行/段间确认区间，不称控制器逐条消费ACK，也不将receipt跨度全归给规划。
- 既有Oracle读取全量记录后评分；M1a仅做流式只读导入，不导入ROS或重新裁决原评分。SQLite三表索引与10Hz展示流分别保存；公开成果摘要按白名单导出，不带私有路径、原始JSONL或地图。
- 旧K记录的physics_hz字段为2500，不能据此代替实际编译步长；后续核XML为.002秒，即500Hz。发布周期为20ms，间隙判定按50Hz合同。实际缺口B/A为1/3处、缺失序号1/50，和旧独立抽取一致，原字段作为历史不一致保留。
- B预算内进场89.251333秒、最终配送26.860442秒、其余约3.682秒；属于原生回执区间分布，没有新增规划/控制器消费或唯一根因证据。

## M1b实现与验证

### 最新实测边界

R1-c四类均通过原/恢复分支各10000步，积分、接触、车货轨迹、编码器、感知随机流和360束scan最大差异0。20次copy的P50/P95为1.139/1.968ms；四次恢复为.131–.220秒。这不包括ROS启动，也不证明所有模型字段的任意运行时变更均已验收。

最终R1-d补齐选定源码及XML/manifest起止观察，文本一致、观察错误0；四类仍各10000步/分支且最大差异0。20次copy P50/P95为.889/39.228ms，最大76.301ms；恢复.097–.108秒。物理确定性与墙钟调度尾延迟是不同结论，保留所有轮次，不挑较快轮次承诺50ms。原生单元已退出，performance持有已释放。

真实装货/出站父回合取得b649aaf7检查点，随后原B路线120.014秒失败。两次R2同配置复现1c/2b从同一检查点恢复，原生积分读回误差0、相同初始真位姿、新world/episode、旧移动命令隔离；独立货物保持均无违例，实际位移1.843/2.032m。两次路线分别120.058/120.028秒失败，末位置21.23/30.82cm；原UUID终态、连续静止、guard关闭、参数恢复及owned清理分别成立。物理恢复成立不能代替配送成功；这两次标为replication，不宣称改进。

每次R2末尾在原静止清理后调用5次capture RPC，观察端到端P50为62/91ms，P95为794/827ms；冷模型首次落盘包含约16.5MB描述，热状态约80KB。回执轮询20ms使端到端值为观察上界，不能当控制器消费ACK或50ms恢复承诺。

| 开发试验 | 唯一控制变化/计算条件 | 实际结果 | 晋级 |
| --- | --- | --- | --- |
| 原参数performance复测 | 原.055/原减速半径，仅进程持有performance | 120.011秒超时；1个保持违例，末53.88cm | 否；不支持CPU单因果 |
| angular-010 | FollowPath.v_angular_max .055→.10 | 12.769秒货物支撑失败，取消原UUID | 否；恢复原角速 |
| slowdown-008 | slowdown_radius .12→.08，原角速/加减速/容差保持 | 120.019秒超时；1个保持违例，末1.588cm但偏航.1265rad | 否 |
| slowdown-004 | slowdown_radius .12→.04，其余同原值 | 108.564秒货物支撑失败，末41.46cm | 否 |

所有上表试验源起止一致、原完整外廓/碰撞/物理评分保持、owned清理通过。performance按进程申请并已释放为balanced，不改变全局配置；.008开发试验与统一反馈存在计算重叠，不能按它排名。试验均未进入正式5+5、留出或完整B→A，不能拼成成功。

首R2-1a因我在发包hook临时增加scope而破坏已持久保存的账本合同，协调器退出；systemd随后回收子进程，缺原生终态/连续静止证明，保留unknown。现改为Workflow先持久化scope再派发，并在执行异常时取消原UUID、保存终态/关闭窗口/清理。1b还暴露调用方将初始化也塞进120秒的错误；现恢复原360任务总预算，路线仍独立120秒。早期两轮不计正常通过。

1c/2b的首条记录AMCL输出分别在首Nav激活后3.164/1.007墙秒才出现。派发前TF等于父均值，不能仅凭TF存在宣称定位已预热；这也不足以判定路线超时根因。[Nav2 1.3.13原生实现](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_amcl/src/amcl_node.cpp)的request_nomotion_update只设置force_update_，服务返回不是新位姿回执。本机同实现已核，R2薄适配只接该服务与AMCL标准输出，不发布真值initialpose、不改噪声/协方差或控制门槛；保存服务回执与请求后新源帧两层证据。新开发轮仍使用原120秒，尚未形成路线通过结论。

新增适配自身的a/b两轮在准备期失败，start/cancel/reset均0。a的严格内置float检查误拒ROS固定数组的NumPy float64；b又把协方差负对角线当硬门槛。实际同域AMCL读到-3.94e-14/-1.75e-13等数值，已改为诊断：原值保留，缺失记unknown，不改数值、不以其拦有效新位姿。43项定向检查通过；c轮已取得三条请求后新AMCL帧。a/b原结果与准备失败保留，unit已退出、9130已关闭后才复用隔离端口，不追认配送或安全取消通过。

c轮仍失败：与1c/2b使用同一真实装货快照、相同Nav2参数及balanced。预热.558墙秒后原Nav UUID 47d879b28f1942048d86aee4997de9b6实际运行，120.016秒超时，第一进场段未完成；货物实际移动1.868m，保持违例1，末46.59cm/.67499rad。日志在路线约46/72墙秒分别报告Collision detected in trajectory，达到原patience后清图重试；只证明原生预测碰撞阻断，未定位到具体障碍或唯一根因。清理完整、原UUID终态5、连续quiet、guard关闭、参数恢复、源码起止一致及owned关闭分别核实，正常任务仍记失败。AMCL新帧到达不是收敛，补预热不是已证明的路线优化。

继续回源发现明确的初始化合同缺口：同版AmclNode::on_activate在set_initial_pose分支新建PoseWithCovarianceStamped，只填均值、时间与frame，没有给默认零协方差赋值；initial_cov_xx/yy/aa没有本版参数读取点。e2ed656时prepare_ros_branch只保存配置，不能称实际生效。c轮三帧均值几乎等于父均值，协方差约零与此一致。据此选择通过已有SetInitialPose原生接口传入相同父均值及已声明的分支协方差；不增加真值输入或调大参数。该缺口已确认，仍不据此宣布它是路线失败的唯一根因。

该输入缺口现已按原生SetInitialPose接回，保留旧manifest行为；实际SDK类型与46项相关合同通过。r2-prior-a与原两基线使用同快照、相同Nav2 YAML值和balanced，唯一初始化差异为显式输入已有先验协方差。实际读回初始化state=received，输入对角线.0004/.0004/.001；三条新帧协方差约1e-5且均值发生更新，证明输入链起效。该轮仍在120.004秒失败，首进场94.594秒成功，剩余约23.836秒配送未完成，末25.75cm/.03623rad，保持违例1；原UUID终态、quiet、清理与源起止一致均成立，不称路线修复。

随后试用本机已有[Nav2 1.3.13 RPP](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_regulated_pure_pursuit_controller/README.md)，仅修改FollowPath控制器配方。RotationShim沿原值，RPP的最大/最小线速、lookahead范围和减速距离映射原Graceful值，其余复用StagingPath既有RPP配置。完整车体、地图余量、平台.06/.10、原加减速、GoalChecker和物理评分保持。source开发轮r2-rpp-a在81.811秒支撑失败，原UUID920411f8终态5；不晋级，也不声称单个标量对照。

原完整K的declaration/launch_command明确为asynchronous，旧新切片却选择source；我漏带了这一原启动参数。旧进程未保存实际环境，不能从source直接断言它已使用同步发布。现于两节点及factory报告增加publication_mode_env、起止系统load平均值，39项相关检查通过；字段只观察，不新增门禁。新两轮分别读回两个Python进程ASYNCHRONOUS，仍保留原全部门槛：

| 开发轮 | 唯一控制配方／发布条件 | 结果 |
| --- | --- | --- |
| r2-prior-async-a | 原Graceful＋显式异步，已注入同一先验 | 109.393秒支撑失败，末95.56cm/.07223rad，原UUIDc0a2a5c5终态5 |
| r2-rpp-async-a | 上述固定RPP配方＋显式异步，同一先验 | 31.172秒支撑失败，末84.26cm/.36828rad，原UUID53d67844终态5 |

两轮源/墙记录时长比约.99995/.99997，源码起止一致，原生终态/quiet/guard关闭/参数恢复/owned退出均核实。并发系统负载另存；发布环境与负载不是唯一因果结论。两轮失败帧中，货物完整平面足迹仍在原边界内、双指力为0，底面接触曾为false；不能把通用错误文案直接解释为货物已经滑出托盘，也不修改原接触门槛。详见私有async-support-diagnostic-a.json。

时钟速率接近1不表示采样无损：新Graceful/RPP异步记录分别缺37/6个物理序号，最大源间隙.34/.04秒。缺口按原样保留并在回放断开，不能由展示插值补成评分证据。

RPP异步轮收到440条received_global_plan及440条lookahead_collision_arc；旧source轮分别1359条。本机源码的发布点位于computeVelocityCommands，证明存在原生RPP计算活动；不冒充每条命令消费ACK、GID独占或任务成功。所有试验仍是开发数据，未派发正式5+5、留出或原出生点完整回验。

### 真实装货快照的无ROS驱动隔离

drive-support-probe-a从同一b649aaf7 R1状态分别恢复四次，积分读回误差均0。按源时间施加零指令、.06m/s直行、±.055rad/s转向，斜率不超过原.025/.05，并回稳；先检原完整几何的名义扫掠，保守净距均至少.197m。模型、材料、限值均未更改，不传送运行物体，不初始化ROS。

四类分别3/6.3/5.2/5.2源秒，共9850步与985个50Hz样本，源码起止一致；采样中底面接触丢失0、足迹越界0、车体禁止接触0。该短探针没有复现完整路径故障，不代表长时间或混合指令安全，也不计导航成功。正转向目标平台段车体/编码器均值.03753/.05086rad/s，负转向-.03759/-.05057；正/负瞬时车体峰值.10805/.07826rad/s。这里的平台段均值不宣称系统已达完全稳态，不能把目标或编码器速度直接当车体响应，也不据此自动改轮距。脚本、原样本与结果保留在同名私有目录。

2026-10-25继续隔离：drive-support-probe-b按同一快照与原斜率执行±.055rad/s长转向各23.2源秒，以及.02m/s、±.055rad/s混合弧线各7.2源秒。混合指令的名义扫掠改用等曲率弧线，保守净距至少.198m。共30400物理步、3040个50Hz样本；500Hz求解步和50Hz前向刷新两层底面失联均0，足迹越界和禁止接触均0，恢复读回误差0、源码起止一致。实际编译选项为implicitfast/Newton、.002s、100次迭代、tolerance=1e-8；不猜测为Euler积分问题，也未改求解器。

随后对失败原记录按实际轮目标反算输入：原Graceful首失联前为±.862324rad/s轮速，对应原有效轮距1.690155m、轮半径.098m下的.10rad/s纯转向；RPP首失联约为.024m/s、.066667rad/s混合指令。此前.055探针并未覆盖这两个实际组合。原记录有50Hz采样与缺口，尚不声称已精确回放500Hz实际输入时序。

probe-c按这两个已观察且原平台允许的输入隔离，共22666步/2268帧，恢复误差0、源码起止一致。±.10纯转向各13源秒，分别出现21/18个求解步和3/3个发布帧底面失联；.024、+.066667混合运动9.666源秒有2个求解步失联、发布帧0，负向同组合两层均0。所有足迹仍在托盘内、禁止车体接触0，净距至少.198m。由此复现了物理接触波动，不是运输或故障取消验收；低速阴性结果不能外推到其它指令，50Hz没采到也不能证明500Hz没有。

进一步对齐原生launch日志与首失联接收墙钟：Graceful轮先于1792854703.426报告Running spin/Turning 1.57，首失联接收为1792854710.068，相隔约6.64秒；主控制器此前已报告预测轨迹碰撞。原FollowPath YAML的原地转向设定本来就是.055，载货参数事务也未覆盖它；不能把Spin恢复动作的.10输入归因于主控制器配置被覆写。RPP首失联前没有Running spin记录，不能把两轮写成相同根因。下一步应记录主路径预测碰撞的具体轨迹/局部地图，保留独立原评分；本轮没有据猜测更改任何生产控制参数。

CLI只读复核qoder-8e15b7在180秒超时，没有可用结论；get_status确认该会话已不在活动列表。上述结论来自根Agent对源码、轮目标、原日志和本轮物理探针的独立读回，不来自子Agent自报。

### M4c CPU回归首片

复用现有unittest、Vitest、TypeScript/Vite和GitHub Actions，不增加调度器。新增continuous-twin-cpu.yml，两个独立托管CPU作业分别检查任务/初始化/参数回执/时间索引/对照投影与完整前端，相关PR/main代码变化或显式手动触发；不启动ROS、GPU或运动API，不上传原数据。官方setup-python/setup-node v6当前提交已由官方仓库API核对并固定，checkout沿用既有工作流版本。

首轮stdlib-only预检74项中有1项因测试fixture明确需要NumPy失败，保留ci-cpu-contracts-a.log；因此明确安装本机已使用的NumPy1.26.4，不跳过该固定数组用例。系统Python同命令74项通过；全前端57文件/687项通过，不能和旧1778总反馈计数拼接。独立环境、构建与远端实际运行结果见progress；原生CI、正式A/B及业务面板仍待完成。

独立venv仅安装NumPy1.26.4，确认没有rclpy/mujoco，74项通过；生产构建通过，包体积警告保留。edd6b5b已推送并读回完整SHA一致。GitHub注册的工作流395248656为active；初次push未找到同SHA运行记录，显式派发一次后返回40111818800，绑定edd6b5b9cbef3848608aca9d331af09b0b94fa13。已读回status=queued、conclusion=null及jobs=0；没有远端通过证据，不重复派发。后续继续查询原run，不因本地watch超时重启作业；自动push触发的实际行为仍待核。

### M2只读入口核对

根Agent直接读取build_scene与ArmPlanner，确认当前生成器只追加一套SO101执行资产和一个target_free，关节维度公式20/18/6加轮系、期望关节顺序和manifest.layout都固定单臂/单货物。ArmPlanner从manifest顶层读取一套station_offset、arm_home_qpos6、arm_contact_xml，并依赖grasp_target名；只复制namespace不足以获得第二卸货臂的物理/碰撞/IK映射。首个实现切片仍为显式新scene/profile下的B卸货臂＋第二独立货物实体映射，再验证真实抓放与库存，不修改默认K或reset造货。

CBC只读子任务cbc-2c3839返回done但result为空，没有可采用产物，未计为M2实施；get_status已确认终态。上述入口事实由根Agent独立读源码，不来自空结果。共享计划/源码继续由root串行整合。

### M2实体场景与Physics首片

- 新增可选--continuous-delivery与continuous-b-entities.json，原build_scene/prepare默认路径保持。原生MJCF attach引用原SO101与货物子树，编译后的B场景为nq/nv/nu=37/34/16，新增一台六轴臂和一个独立自由关节货物；两臂/两货物按名字绑定。序列化索引仅作提示，不以其重绑另一台臂，不增加内容锁。
- 先试MjSpec.attach＋to_xml，测试发现原有11个body的惯量被导出舍入，base最大差约2.79e-10。该实现未晋级，首6项测试的1个失败保留。改用[MuJoCo 3.3.7原生MJCF attach](https://mujoco.readthedocs.io/en/3.3.7/XMLreference.html#body-attach)直接引用原XML，不放宽断言；原body质量/惯量、geom尺寸/摩擦/solref/solimp和执行器增益/控制/力矩范围逐项精确比较通过。
- 首次工位沿车辆朝向布置时，新增upper_arm与原factory_channel_occupancy产生约83.5N真实接触，m2-model-a保留为失败（现已归档，恢复入口见progress）。采用新工位旋转pi/2、货架本臂坐标(.05,-.22)，重定位新工位的连接台面；原占道箱体、车体、机械臂碰撞网格与限值未删改。m2-model-b（同一归档）静置2源秒禁碰0，完整几何出生点/B点保守净距约61mm；这是静态预检，不是到达或路线成功。
- 正常prepare已从原CLI产出新world、定位图、碰撞图和Nav2配置。Physics仍是唯一物理写入者，新增臂servo进入同一step；逐cargo记录支撑、各arm指夹和另一货物接触。原单货物/单臂状态字段保留。既有positions-only关节名输入现能选择附加臂，乱序名字按本臂映射，超范围原子拒绝；原发布者/时间检查保留，未声称ROS端到端卸货已通。
- 附加臂目标进入R1应用状态，缺失时只跳过该恢复案例；新鲜实例恢复后两臂及两货物100步一致。reset静止条件覆盖第二货物，显式reset恢复附加臂home，但M2订单编排尚未接入，不用reset制造连续库存。
- m2-prepared-a的原生5源秒/2500步/250个50Hz样本，world/episode不变、reset=0，车体/机械臂500Hz禁止接触累计0；1秒沉降后两件货物各自pickup支撑在50Hz样本中失联0，不外推500Hz支撑连续。最终proof-b.json另核选择源码与四XML输入起止一致；B点初始物理场景的1000步测试也无禁止接触，均不计导航、抓取、卸货或连续订单。
- 相关93项首跑有11个旧退出fixture错误：SimpleNamespace缺已有checkpoint_io；AST核对该finally与HEAD完全相同。只补fixture的可选字段并新增checkpoint close失败仍完成其余清理的用例，80项运行/工厂检查通过。38项原生场景/快照/prepare检查通过；新增按名路由后60项实体/仿真检查通过。各组有重叠，不相加冒充新全仓总数。旧失败和第三方OpenGL ResourceWarning均保留。
- zcode-06a373只读复核90秒超时，未采用其结论；get_status确认不在活动列表。所有实体/接触/参数/测试结论由根Agent独立读回。

### M2显式实体规划与当前失败

- ArmPlanner保留默认路径；显式arm_id/cargo_id必须携带当前完整snapshot。新增ArmEntityView按名字抽取本臂六关节和所选自由货物，将位置、四元数、线速度转入工位坐标；自由关节角速度保留本体坐标。B工位yaw=pi/2，不能只复制namespace。其他臂、货物、车型和工位按实际姿态冻结完整碰撞geom，网格使用编译顶点/面，不替换成包围盒。所有写入仅发生在独立查询MjData。
- 原SO101 plan_transport硬编码原取货台到托盘的路径，不能直接复用于卸货架。prepare_placement仅扩展显式局部路点，复用原carried_configuration_checker、IK和joint_planner；保留.003m笛卡尔、.01rad关节采样、原.2mm载荷和1mm臂余量。选错实体或缺实测状态只拒绝该查询，原单臂默认不变；尚未接入订单owner。
- m2-entity-grasp-a在派发前失败，0运动样本：误把沉降后的箱体中心当成夹取点，原生查询明确报告夹指与pick_floor穿透约2.5/3.7mm。修复沿用原成功.019m pinch与原台面/箱体尺寸算出的偏移，没有改余量。
- m2-entity-grasp-b执行同一Physics中的cargo_2抓取：23420步、2242个50Hz样本、world/episode不变、reset=0、车hold、禁碰0。原.025m抬升/.02N双指/.7s连续保持条件离线复核通过：保持1.5s、最小抬升.040913m、最小双指1.587475N、支撑样本0、最大源间隙.02s。fixture-score.json是分项独立评分；原result的passed=false是未评分默认，未改写原记录。不是原运输oracle、ROS或连续订单通过。
- 内置只读复核在独立查询中复现遗漏：原pad属group0，不在原group3碰撞对；把非目标货物放在pad中心时，原查询valid但原生距离约-6.14mm。新增EntityPadChecker仅补pad与冻结实体的原mask兼容碰撞对；选中目标仍不在rig中，既有目标夹持豁免保持。增加该反例回归；强化后的c轮另存，不把b追认为新源通过。
- prepare_placement还补回本臂ctrl和源时间，避免用零执行器参考重算所谓实测指夹力；新增捕获独立查询MjData的回归。m2-unload-fixture-a只建立B点托盘有货的新初态，在0运动样本前被invalid_start拒绝；不算从源头配送、不算卸货或库存变化。私有探针首次缩进错误只影响准备，未创建Physics；修复后保留上述真实失败。
- 最新完整反馈m2-feedback-current-b为1798项通过（1048/15/209/61/465），早于随后补齐的实体规划反例；其前一轮control超时后，追踪发现旧AST测试夹具缺os和localization_warmup，23失败/错误均保留，只修fixture。正确PYTHONPATH下core120项通过；一次直接unittest缺tools路径的导入错误单列。当前最终新增组继续定向复验，不借旧全绿覆盖新源码。

- 强化pad检查后的grasp-c完整复跑，物理与独立分项数值同b，选定源起止一致，14项实体回归通过。独立审查另核B连接台仅改center=(.033,-.145)后，home/托盘/货架(.06/.023/.019)IK端点均通过；距离饱和在2mm，不解读为精确最近净距。原a的2.759mm固定几何重叠保留，新配置不修改旧场景。
- B卸货b已在真实物理抓起，但显式路径末点.019低于原放置配方.023，载荷检查报告frozen__unload_line_b__pick_floor约-.000114m。未派发该放置路径，保持.0002m载荷门槛。c使用.023并在抓起后保存原生R1，原物理执行与独立分项评分通过；不是调宽门槛，也不把fresh B初态当导航完成。

- 最终卸货c为同一world/episode的51510步、5051帧、103.02源秒，无reset/禁碰，选定源码起止一致。实际抬升最小.040857m、保持双指1.529768N/1.5s，搬运双指最小1.550056N且支撑0。释放后完整货物足迹在本架.058m范围内，line_b支撑、无pad接触和低于.002m/s线速持续1.52源秒；回位误差.000580rad，最终原生速度范数1.725e-5rad/s。fixture-score.json为独立卸货分项通过，原result.completed_segments=5只计初始approach方案；placement-plan另有8段，原标签连续块为10，不以该计数当验收。逐帧臂速度缺失明确记录，不能称原owner连续quiet已验。R1抓起状态和最终图另存，不重置物体、不回写库存、不称导航或连续订单。
- 最终完整反馈c=1805项（1049/21/209/61/465）全部通过、无失败/跳过。测试是在最终相关源码修改后运行，原时间/碰撞/力/几何门槛未变。90个当前入口/计划本地Markdown链接有效。GitHub原run40111818800最后仍queued，不从本机检查改写远端结论。

- 收尾再增加多实体漏传身份的局部反例：拒绝该查询，不能默默使用只冻结车型的legacy查询；默认原单臂场景保持。7项当前显式选择/子进程测试通过。1805项完整回归发生在该小补丁前，源版本界限明确，不虚增全仓总数。此错误路径不代表已完成owner实体接入。

### 只读对照页

既有Lichtblick树已有MCAP/时间轴/模型能力，但该树仍有在途修改，不导入第二份播放器或覆盖它。此轮只复用cooperation_timing的流式索引/10Hz投影，新增配送专用comparison JSON：按原世界坐标展示两车、货物、由q6正解的关节线框、原生UUID和原评分；源时间按明确锚点同步，缺口断开。此图不是完整碰撞模型或新评分。

控制站/regression复用原GET报告中间件，文件由operator配置，不接受浏览器文件路径。原始记录和详细轨迹均留私有目录；公开源码不带JSONL、模型状态、SQLite或截图。真实浏览器1440/390px的11项检查通过，写请求和pageerror均0；human编辑、404、坏JSON保留原数据，来源不符时关闭Ghost，不用哈希锁住文件。矩阵编辑/原owner派发、正式配对面板及CI尚未实现。

- 模型网格描述约18MB，不能每个物理周期复制/序列化。复用同一已编译模型的固定描述，启动时准备；状态文件引用同目录的可编辑模型定义，积分/应用状态与IO分开。兼容性核对实际名字、拓扑、网格、质量/惯量等结构字段，不用内容hash或计划revision门禁。
- R1-b四类各10000步的两分支均无观测差异；只证明该有限同构模型/源控制序列。需再通过加强兼容后的同面板、真实R2分支和旧默认回归；不可由此称ROS历史或旧Goal已恢复。
- R2须保存父实例原生map→base_footprint定位输入及缺失协方差说明。新分支从冻结定位均值初始化并预热，原生载货Goal/物理评分单列；原世界不回滚、旧指令不重放。原K的实际XML步长仍.002s，不能从旧报告physics_hz字段推断新的积分频率。


## M2 原 owner、独立货位和命名 Oracle（2026-10-25）

- 原 Bridge/Workflow 已接显式三字段 business_delivery、按 cargo/arm 选择实测视图和原执行器参考。库存由原 owner 持有，同 UUID 不能改绑；只有物理托盘交接后记 on_tray，清理后以新源帧再次连续核验 .7 秒才记 delivered。失败归 unknown，不自动补货；连续 Workflow 的显式恢复入口也不能调用 reset。默认单实体和显式 reset 流程保留。
- 独立审查复现同一货位问题：第二货物瞄准原货架中心时，夹爪与已送达第一货物碰撞，约 -4.066mm。新增配置将同一原货架划为两个不重叠 cell，中心 (.02,-.22)/(.08,-.22)、半尺寸 (.028,.058)。两者均在原 .058m 货架内，不移动已送达货物、不删碰撞几何。生成器拒绝重叠/越界/错 ID，仅拒绝该配置；多货物配送缺货位时拒绝该任务。
- 第一货位 a 实际完成抓放，但运行期发生源码变动，source_unchanged=false；保留为开发证据。冻结后的第一货位 b 为 52440 步/5144 帧，第二货位占用 fixture a 为 57230 步/5623 帧，两者独立原门槛分项评分通过，源码起止一致。两轮都是新 B 托盘初态，不是同一订单链。第二轮的第一货物初态来自前开发轮实测末位姿，第二货物在创建 Physics 前置于托盘；明确不是返回取货或连续导航，不将它们拼成无 reset 双订单。
- 第二货位 fixture 抬升最小40.857mm、保持双指1.529768N/1.5源秒，搬运最小1.550056N/无支撑；最终完整足迹在自己的 cell 内，货架支撑/双指0/静止持续1.52源秒。回位误差 .000581rad、逐帧原生臂速度最大1.792e-5rad/s，禁碰/reset=0，最大采样间隙 .02s。第一货物全样本在原 cell 且有货架支撑。额外端点查询中重新指向已占第一 cell 仍被 -2.760mm 拒绝，第二 cell 通过；2mm 是原查询距离饱和值，不当精确净距。
- 新逐货物 PoseStamped 发布沿原单一 Physics owner 与50Hz周期，旧话题保留。165 原生静止烟测实际接收194组同步帧，两 named pose 与对应物理位姿/四元数差0，world/episode固定、reset0、hold、禁碰0，进程/context关闭；只验 ROS 发布/订阅，不验任务。退出后的发布端清单为空，不能用该清单追认活动发布端 GID；新 Oracle 也明确标注该核验缺口。
- 原独立 Oracle 只订阅旧 cargo_1 话题会误评 cargo_2。新增 --business-manifest 和只读命名订阅适配，仍使用原独立车体/Clock/选中货物 ROS 位姿，原 load/transport评分和额外卸货/完整 cell 足迹/全实体静止分列。HTTP 成功和库存回执只作身份对账，不代替物理评分。缺第二货物独立观测、清理末端失去支撑/home、错误/旧库存回执均有拒绝反例。
- 原 Factory 增加可选 --continuous-deliveries，按原订单 ID 映射 cargo/工位，再传原 Workflow。B/B 不再派 reset，B/A 新增第三台臂配置。原360装运/120路线不变，独立声明180卸货，单单540、两单1360（包含原280启动清理余量）；旧360/1000不变。连续帧汇总跨有界缓存保存 world/episode/reset证据，订单间另核原停车位。原 runner+真实 Workflow 的模拟 IO 双订单通过不能计原生配送。
- B/A 配置公开 prepare 得到43qpos/40qvel/22ctrl；1000原生静止步的禁碰/reset0，原完整几何 A/B 点预检通过。初次私有静态脚本误导入 SceneGeometry，在创建 Physics 前失败；正确入口 cooperation_geometry_check 后通过。未验 A 卸货臂实际抓放或 B/A 路线。
- 最新 m2-feedback-owner-a 完整反馈1855项通过：control1098/checkpoint22/mission209/autonomy61/frontend465，0失败/跳过。定向25/26项早期 fixture 错误及漏声明 slot 失败保留；125旧计数曾含导入 TestCase 重复收集，已改模块别名，不当125个独立新用例。
- CLI 子 Agent 本批 AGY 90s、额度预检 usable=true 的 Qoder 180s 均超时，未据此称交付；Qoder get_status sessions=0、无残留进程，未产生源码改动。根与内部子 Agent 实施并独立核验。原 GitHub run40111818800 本轮再次读回 queued/conclusion=null；未重复派发。


## M2 K 配置接续与 A 卸货（2026-10-25）

- 原完整K的实际缓存位于 ~/.local/share/fishbot/cloud-jobs/kaggle-20261024/local-full-b-a-k，不是旧 ~/.cache/fishbot/factory-line-delivery-20261021。原 manifest/nav2/最终读回均可读取。新B/B与B/A以公开prepare重新生成多实体世界与地图，再复用现有f1_candidate.configure选择原Graceful配置与已确认.005全局附加余量；控制器、平滑器、行为服务器三节点YAML、载货事务限速、工厂输入、Omni模型、staging和传感器计算设置与K分别相等。新地图/实体和当前源码不同，不称K原回合重放。默认旧配置未修改。
- 发现并修正可选 capture_before_delivery 的主货物别名检查：原检查在第二件配送时会读已经在货架的 cargo_1；现调用原 task_handoff 选择当前货物。6项真实Bridge方法定向合同通过。新完整场景该可选开关仍为false，未靠关闭一个原已启用能力来绕过本轮失败。
- A新初态卸货 cargo_2-a 的57960步/5696帧、115.92源秒完成，源码起止一致；最小抬升40.858mm、双指保持1.5源秒、最终支撑/独立cell/夹指0/原生静止1.52源秒。臂速度范数最大1.791e-5rad/s，B上第一货物全样本保持其货位和支撑，禁碰/reset0。只是A到站后卸货分项，不是B/A连续运输。
- 新完整B/B a在保护快照阶段因当前shell缺XDG_RUNTIME_DIR/DBUS_SESSION_BUS_ADDRESS而退出，0 native launch/0动作，原目录及setup-failure保留；现有uid1000总线socket可用。仅在下一条运行命令设置现存用户bus地址，未启动/重启daemon，也未改全局环境或保护实例。b使用新输出目录、domain166/9136；已实际进入第一单，原UUID51a90819-27dd-4516-b419-23dfb2406566，实际加载native-current-goal的四个预期库。最终业务结果待原run结束，不从当前stage计通过。
- M3只读接口核对：现FaultInjector每episode只接受一个Dock UUID，不适用于无reset第二订单；SensorDrop宜在Bridge转发detected_dock_pose前真实跳过发布，保留源端及Oracle流。ForceImpulse应在Physics步边界累积源时间Ns，结束仅撤销本事件wrench。transport现有Oracle仍以业务成功为条件，掉货后的正确取消需单列task_completion=false与expected_safety结果。SoC应复用fishbot_sim_power.PowerModel，prefault ring复用R1/CheckpointIO；应用快照还须保存故障水位/剩余冲量/SoC，R2去激活时移除旧故障自有外力。不能从原R1含xfrc就推断这些新应用状态已恢复。


## 2026-10-26：B/B失败边界与规划剖析

- m2-native-b-b-b第一单原装运360墙秒失败，路线83.196墙秒/120秒并未先耗尽；任务实际362.544秒，单次start、reset0、同world/episode，第二单未执行。原生DriveOnHeading成功，approach Nav终态5；quiet、参数恢复和owned清理分别成立，不计运输通过。
- 历史独立复算m2-native-b-b-diagnostic-replay-a：17337有效命名样本、缺独立样本0；抓取/放货/回位及载货位移分项成立，但未到站，所以最终成功前缀0。原报告把空前缀装运耗时显示0；现补实际终态耗时362.544及phase_evidence，不改成功门槛。
- m2-placement-profile-a从真实source99/seq4949双指保持帧单次离线prepare_placement，未启动ROS或推进物理。原checker1335×1061=1416435次距离查询，固定底座/world304380次；原生距离累计4.264秒，forward6102次0.641秒，因此“forward主导”被否定。cProfile/计数包装器有显著开销，32.65秒不是未插桩基线，不宣称提速；原完整几何、1mm/0.2mm与345路径样本保持。
- M3新ForceImpulse独立复验发现可编辑快照的非终态累计时长超过目标会产生负剩余反向力；现恢复前检查时长/源窗/尾段比例，step局部撤销无效事件，其他外力保持。17项含两个原生小模型通过；尚无Physics接入、真实掉货取消或长测结论。

- 固定pair缓存候选在531状态（含9个碰撞负例）与原判定0差异，但单次顺序对照.921707/.964599秒，没有提速；生产代码已撤回，patch/测试/全结果在私有m2-fixed-pair-cache-a，不能称预算修复。原无插桩全placement在同真实快照6.007墙秒/6.001CPU秒、初始化3.484秒，原345路径样本保持。活动任务95源秒与离线6墙秒的原因未唯一定位；独立查询用于复用现有取消/期限响应能力，提速必须另验。
- 新命名GID核验保存运行中端点，与physics节点owner交叉核对；domain167实际两cargo各181帧，均唯一真实端点，全部hold/reset0/禁碰0，producer退出/context关闭。历史B/B没有该命名端点字段，明确unavailable，不追补为核验成功。
- ForceImpulse现已接原Physics唯一mj_step与checkpoint，默认无事件轨迹保持，R1待执行脉冲恰好一次，R2撤销旧自有wrench。根独立force17+Physics8+原checkpoint7共32通过；未增加ROS触发器，也未声称有原生Goal接纳证明、掉货取消或长测。

- query_placement复用原受控子进程，只隔离命名装/卸货IK/OMPL。父执行检查器另用同一快照refresh，防止沿用抓取前的冻结实体；原360装运/180卸货剩余期限及owner取消检查保留，不设新配额。实际快照子进程计划逐项一致，记录m2-placement-query-a；共享负载不同，不把10秒与95源秒之差宣称已定位GIL或已解决预算。

## 2026-10-26：子进程放货原生试验与接管

新C在源码734550b冻结下真实运行，放货查询source80.28、子PID175935已退出、10.020墙秒，剩余原360预算288.671秒。第一载货进场Nav仍在120.01777秒终态5，最终真位姿(1.26044,-2.15578,1.75735)，目标(1.25,-2,.463648)未完成；没有卸货或第二单。新旧轮共享负载/起始误差并非严格配对面板，不称稳定提速或算法改进。

外层协调器退出143原因unknown，但Bridge与原独立observer继续工作；root不重发，回收已失败原UUID，按既有cleanup_proof/EvidenceTail连续quiet/stop_owned_launch清理。原recovery侧车、terminal-state、cleanup-quiet、score、sources与protected snapshots保留。接管延迟不能算进装运执行时间：报告改用第一条原任务终态HTTP接收时间；full_task窗口仍保留接管上界，两者不混用。原始marker不回写为更早的伪精确时间。

CLI已让SIGTERM进入原RuntimeError清理路径，真实子进程信号fixture证明可展开原finally；不能仅凭这个fixture声称ROS取消整链在受信号时已验。未定位外部SIGTERM发送方，也没有修改其它任务、网络或平台配置。


## 2026-10-27：J100进场路径与转向定向修复

原C独立流6001真值帧与导航地图位姿对照，位置P95 .02749m/max .03030m、yaw max .00827rad；南绕是真实规划/执行，非大幅定位漂移。5896个cmd，负v0、角速度饱和3681（62.4%）。第一全局路径3.87022m，平移>1mm的倒车.45435m/16段；第二/三计划2.15483/1.37164m，倒车.22555/.33040m。原Graceful allow_backward=true且源码支持负v，不能称不支持倒车；按位置前视目标选择/最近点裁剪是否跳过近回折仍为待核实。首预测碰撞在118.29墙秒，5998物理帧实际禁碰0、guard0，命令龄max .0389秒。私有summary/trace位于j100-route-trace-20261027。

最小候选只将B approach(1.25,-2,.4636476)改为(1.25,-2,0)，终点(.7,-2,0)不变。原完整实体几何下，候选静态净距 .077788m、最后.55m倒车段扫掠认证净距 .025509m。原边平移边转向段采样净距.001m、扣间距界后不能认证，不等于已证明碰撞。两个北侧候选撞baffle_right，排除。原占道障碍/挡板缝.45m小于足迹宽.48m，仍需真实Lattice绕行。几何report位于j100-entry-geometry-20261027。

下一原生短测保持Smac/Graceful、完整几何、原速度/加减速、120路线预算和4cm/.05rad评分；先用明确声明的新载货初态fixture建立R1/R2，不能把旧发布qpos初始化冒充原积分状态重放，也不算完整装货运输。新增motion_target/transformed_global_plan/local_plan记录复用原observer，不录全量costmap。优先验证同一初态下原yaw/对齐yaw，再考虑控制器方向转换点修改。


载货短路线原yaw与yaw0均实际运行并在120.008/120.027墙秒耗尽预算，第一进场点未到，Goal终态均5；对应私有结果j100-entry-baseline-20261027与j100-entry-yaw0-20261027。均为相同新载货初态，不是完整抓取/运输。原yaw的控制器直接输出2197组诊断，117.224秒已裁剪路径从全局i94跳到i103，越过i101折返点；最后30秒600个完整周期378次目标在倒车段但相对车坐标仍在前方。原yaw独立评分出现1个载货支撑/归位异常，不能称载货安全通过。yaw0的细节仍在核对。只改变进场yaw没有通过，不进入生产配置。

现有Nav2 1.3.13 MPPI自带enforce_path_inversion，可限制路径和前视目标不跨未完成折返点，正在独立评估能否复用；速度、加减速、碰撞及原评分不变。Graceful原生支持倒车，现象并非笼统的“不支持倒车”。77项Oracle相关测试通过；这些测试不代表任务通过。

yaw0第二计划于路线35.894秒发布，全长2.52784m，唯一换向点(1.59917,-1.88793)；实际车体最近距该点.17536m，并未跨越该计划换向点。2201帧motion_target/裁剪路径/局部轨迹证明控制计算；无碰撞/进度恢复日志，不能归因为碰撞锁。独立载货分项6250帧/货物位移2.68970m/支撑归位违例0，但最终误差.75483m/1.96926rad且无停稳，整体失败；physics缺5序号、最大源间隙.04秒。严格逐段位姿的理想源时间下界104.7秒、重规划余段102.1秒只作路线负担指标，不当实际墙秒。

MPPI候选复用系统原生1.3.13及已有RotationShim配置，完整模型、原进场角、Smac、costmap、限速和评分保持；使用原有15mm/35mrad为转换点阈值，保留预测和采样局限。首次启动因输出目录预先创建，被Factory在派发前拒绝；新路径j100-entry-mppi-b-20261027独占168/9138进行原生短路线对照。

MPPI原生候选b真实加载并执行，实际任务cacb2cb5-3413-45a1-846e-0f2863ea69b2、Nav UUID 0f5f08414dee4a09b8e3e12fbd2774e0终态5；路线112.124墙秒时原Workflow报告货物离开托盘支撑范围，第一进场点未完成，最终误差.78066m/.55468rad，评分失败。控制器曾报告未进展，重试后出现20Hz目标但实测6.25Hz告警；非持续频率结论。原结果、原生日志与物理帧保存于j100-entry-mppi-b-20261027，源码起止一致、owned进程0/9138端口关闭。该候选未晋级，不改默认。

MPPI候选坏帧source122.88，处于原生Spin恢复（此前4次未进展）；货物仍完整位于托盘内，floor_contact瞬间为false、最低角距托盘约6.87µm，前后各一帧接触均恢复。实际角速约.146rad/s，邻近/cmd_vel=.10rad/s；这是一帧支撑失检，不称货物落地或证明动力学因果。Spin经过载货smoother，限速.10而MPPI本身.055；原behavior参数max1/min.4/acc3.2未被载货控制器参数更改。0.1与0.055的差别解释指令范围，不能证明接触失联的根因。MPPI的visualize关闭，三Graceful诊断主题为空，不能声称已经验证MPPI换向点推进。

MPPI角度候选真实结果：任务7e09af9b-4ce6-41ad-a09a-34a67d038139，原Nav UUID f5da5fe2cd35444f930e6e63c862b5ea终态5，120.023秒超时、第一进场未到；车辆最大距初态.03742m，货物净位移.04489m未达原.5m。6262帧支撑/臂归位违例0、禁碰0；Physics缺10序号/最大源间隙.04秒。Spin命令最大.055，实际峰值.14098发生在hold切换附近。原阈值/换向/Spin参数已在运行中逐项GetParameters读回。2141周期原生最优轨迹与裁剪路径，30–85秒控制/平滑/最终速度P95差0；30–60秒原始控制vx P95 .000530m/s、w P95 .0000312rad/s，最优轨迹弧长P50 .005494m，说明此次控制器本身接近零输出，不称监测阻断。证据j100-entry-mppi-angle-20261027和j100-mppi-angle-analysis-20261027。

MPPI代价实现含gamma/std²；本轮候选把wz_std由模板.4缩至.0275而gamma保持.015，导致角向系数约放大211.6倍、线向放大11.1倍；是源码支持的零输出原因候选，不是逐critic因果证明。下一轮mppi-template-noise恢复既有模板std .12/.4与原gamma、原PathAngle阈值，保留慢Spin、诊断和所有物理/碰撞/限速，正在独占168/9138验证。

恢复模板采样尺度b真实任务d63b6aef-08e1-4f5b-8f19-d7ccd2978065在120.024秒超时，原Nav UUID 58fcb2304bb4438988e1a32ffbc0bd2a终态5、完成0段，终点误差1.54764m/.35917rad，评分失败；源码起止和进程回收以result为准。首个noise尝试因ROS CLI读参留下本轮domain168 daemon，在派发前被拒，已用ros2 daemon stop仅关闭该隔离域daemon后改用新输出目录；该前检失败不算运动实验。模板噪声、角度阈值及可视化/慢Spin组合变化，非单因素因果证明，不能以此判明gamma根因。

noise-b的30–60秒nav线速度P95 .000676m/s、2秒最优轨迹弧长P50 .00709m，三层指令差P95 0；2195个原生最优轨迹周期、独立载货6256样本支撑/归位违例0，货物净位移仅.04597m。记录94756条无截断/回调错误，定位差P95 .02724m/.00152rad。持续蠕动刚好满足该候选的5mm/10s进度阈值，所以无恢复，不能以此证明Spin配置改善运输。恢复采样尺度未修复，不能认定std缩放是根因；下一步提取原生逐critic代价或有界短查询消融，再判断是否改控制器。分析j100-mppi-noise-analysis-20261027。


## 2026-10-27：MPPI逐项代价和低速反馈对照

独立私有诊断overlay基于同版Nav2 1.3.13，原生controller进程映射确认为该库；低频记录同索引critic增量、gamma、softmax权重和约束/滤波后速度。首个载货20秒原生对照，cycle200样本vx在±.0025m/s，加权.000599/滤后.000681；相近源帧encoder和真值均约.000681m/s，低于controller_server min_x_velocity_threshold=.001而被过滤为0。成本项当时只有PathFollow与PreferForward非零，Cost/Constraint/Goal/PathAlign/PathAngle为0，gamma加权约.0000059；此周期无证据支持碰撞或gamma迫停。

同模型/同任务两个YAML唯一差异min_x=.001→0；首10秒真值净位移.00568→.22491m、cycle200滤后.000681→.03939m/s，各500物理帧内支撑/禁碰0。后者初始AMCL噪声存在差异，非逐帧重放；短对照强支持反馈归零死区，并非完整配送通过。对照原限时器在任务创建竞态退出，未发取消；根对原instance/episode/UUID接管单次取消，累计约44秒，原UUID baf46588f02b45f9bbf047c5b1f8cbed终态5。取消后hold窗口有一帧臂速度.0724>.05rad/s，货物4点支撑未离盘；前后帧低于门槛，不能归因取消。

无诊断库的完整进场复测在运行中GetParameters读回min_x=0/MPPI/inversion=true；120.006秒首进场未到，原UUID 531ebb2cc1ad48d8b26bb3b4898ec2ce终态5，6140物理帧支撑/归位违规0，货物位移.3126m未达.5m；物理缺21序号、最大源间隙.34s。车体在路径转弯前后徘徊，50秒时车身与路径方向差约26.6°，局部路径起点横向差.14m；不能归因碰撞监测。

只将min_theta=.001→0的65秒对照仍未完成进场：3414物理帧支撑/归位/禁碰0，缺16序号/最大源间隙.34s；同一原UUID 5eef3cd460764ffaa99fe675473864fe取消5，连续静止2.30源秒，进程和端口已清理。此轮PathAngle项有效；cycle800负角样本总权重.306、近零.485、正角.203，wz加权约-.00052。对同批样本离线仅重算temperature从.1→.03，cycle600/800/1000加权wz约-.00052→-.00153rad/s，但不能代表闭环再运行或证明该参数可通过。用户建议的物理死区、原地旋转与路径假设须分别核验，不当既定事实。


## 2026-10-27：用户建议核对与固定路径短测

当前J100实际使用SmacPlannerLattice而非Hybrid-A*；diff-r060-2cm primitive含64原地旋转，半径约束曲线而非禁止原地转。allow_reverse_expansion=true、rotation_penalty=12/reverse_penalty=1可能影响规划偏好，非已证cusp原因。Nav2 1.3.13 RPP内置rotate_to_heading与allow_reversing不兼容；速度缩放lookahead无证据与旋转必然冲突。当前MPPI已为temperature=.1、wz_std=.4、vx_min=-.06、PathAngle mode2，未启用Twirling；不能将其它默认值当作当前配置。

已有同R1载货阶跃±.055rad/s平台真值约±.0375，未支持低于.15就无法转向；±.10出现过支撑波动。用户举例的.2/.3rad/s及.1m/s超过原J100限值，未执行，不改摩擦、模型或评分。10秒位移.225m是窗口平均.0225m/s，不单独证明摩擦饱和。

重新跑原场景捕获checkpoint 4377a191，积分状态312项及引用模型可读，源时105.942、局部TF先验105.920。自动采集误订阅本MPPI实例未发布的received_global_plan，第一次采集失败；根按同一活跃原Nav UUID d99c0183d7904d45b74c4dd9d3eb6020实际观察器保存/plan并捕获一次快照，原工厂最终取消5并清理。最新/plan虽较快照早82.14墙秒，经同轮map→odom TF转换，快照附近transformed_global_plan 40点与此plan连续索引18–57最大XY差1.74e-11m；这证明该局部段几何一致，不证明完整FollowPath action payload或姿态一致。快照与TF先验不同源帧间隔.022源秒，不当全ROS状态重放。

R2分支恢复积分读回最大差0，AMCL重新预热并hold，Nav2/滤波器未恢复；冻结同一候选路径的原生FollowPath 15秒短段。首次脚本因物理话题QoS不兼容在派发前失败，沿现有sensor QoS修后原生UUID 5c684fab13834aa3b20d17a9e07a4ec8接受并取消5；发现直接FollowPath没有触发owner的动态载货平滑限速，因此该轮只记机制探索、不与原载货条件等同。

随后在独立分支显式复用原载货平滑max/min v=.06/-.06、w=.1/-.1、线/角加减速.025/.05及progress .005m/.05rad，真实ROS读回一致。原生UUID c3550d9ecfe241939ae3a98db1c9b7ee 15秒后取消5并hold；真实yaw -0.34606→-0.67745（-0.33139rad），实际平面位移.04435m、实际平均角速-.02266rad/s；753个50Hz物理帧无序号缺失、支撑失联0、禁碰0。前3帧hold，smoothed仅687条/13.719s有采样缺口，不能当连续安全或配送通过。

同快照/路径/载货参数，仅将MPPI temperature .1→.03的独立分支（未取得该参数运行时读回）同样15秒后取消5/hold，yaw -0.34606→-0.67595（-0.32989rad），平面位移.11393m；750个50Hz物理帧无序号缺失、支撑失联0/禁碰0，smoothed 645条/12.878s有缺口。单次两轮转角接近，低温前进更多但不足以证明稳定改善，控制器内部/AMCL状态和随机噪声未恢复。两轮均非完整目标验收；不能据此改变默认温度或主张解决路线。


## 2026-10-27：固定卡点小角速度与交接后路径跟踪

同卡点积分快照4377a191、原几何/轮地/载货与原加速度斜率，离线MuJoCo源时间阶跃各恢复独立分支。±.001的真实平均偏航约±.0000016rad/s，±.003约±.0000047，+.01/-.01为+.01066/-.00826，+.03/-.03为+.01944/-.02298，+.055/-.055为+.03996/-.04026；编码器均值分别约±.000001/±.000003、+.00543/-.00573、+.02585/-.02588、+.05063/-.05056。10档各8源秒平台、恢复误差0、源起止一致；500Hz求解输入与50Hz重新forward均未见托盘支撑失联，完整名义扫掠净距下界≥.199m、禁碰0。首轮未给源时间戳被episode fence拒绝、10档无运动，保留失败。仅证明同快照静止原地和当前模型在该样本内存在极小指令响应不足，不外推运动中阈值、具体摩擦因果或实体硬件；实际MPPI后段-.00014～-.00095处于相近量级。报告j100-small-yaw-response-stamped-20261027。

固定路径30秒（原动态载货限速显式加载，低频诊断插桩）：FollowPath UUID be0918f63b9c4bcea0a533ba5f7104d3接受、取消5/hold；首次/optimal_trajectory在接受8.312秒后，证实MPPI实际产生优化轨迹，先前8.3秒符合Shim对准。MPPI后各5秒真位移.0308/.1075/.1781/.2281m，最近路径点距离中位.0659/.0731/.0892/.1184m、最后2秒.1357m（最近点近似非严格线段距离）；nav角速度约-.00014至-.00095，车辆随路径偏离变大。采样周期1/200/400的PathAngleCritic增量为0，具体提前返回条件未确认。source160.280的一帧托盘底接触为0，发生在短测取消后hold切换窗口，前后帧有接触；无掉货证据但不得算连续载货通过。

同快照/路径/原载货限制下只将PathAngleCritic.max_angle_to_furthest由本版默认.785398设.15：UUID d7f3f2d0ef6f49e0ba2fc6ede0e3aac5提前status6/error105，日志Failed to make progress，MPPI后4个5秒真位移.0056/.0065/.0022/.0001m；诊断确认PathAngle项非零，但该单次候选失败不晋级，不否定所有阈值。1523个50Hz物理帧支撑失联/禁碰0，不代表500Hz连续。stale/future命令告警起于action abort之后，不作停滞原因。

同快照/路径/原载货限制下只将temperature由.1设.03：UUID 0a236844299f4bacab3d06ad51aab461按探针取消5/hold；MPPI后各5秒真位移.0608/.2143/.2934/.1912m，最近路径点距离中位.0653/.0800/.1141/.1447m、末2秒.1492m，前段较快但后段停滞/偏差增长。日志8次Optimizer fail to compute path/reset，1608个50Hz物理帧支撑/禁碰0；不可将代价升高直接判为物理碰撞。每候选仅一次，AMCL/MPPI内部状态和随机性未恢复，诊断记录本身有开销，不宣称统计优劣；均不构成完整进场候选。


## 2026-10-28：J100 场地适配与真实规划

用户明确将正常业务场景按J100适配，旧窄场地保留困难对照。复用现有prepare/build_scene，仅新增可选arena_xml；同一场地进入物理世界、arm-contact/rig和静态地图。未新增仿真器、控制器或任务引擎。装货工位保持，出生改staging=(-.9,-1.68,0)，A=(0,-1.68,0)，B=(1.7,-1.68,0)；旧远端初态不再当作本轮初态。

南侧baffle_right从(1.4,-1.4)移到(1.4,1.8)，block从y=.5移到.8；8m外墙保持。两卸货臂仍π/2，基座分别(-.02,-2.10)、(1.68,-2.10)，货架中心(.20,-2.05)、(1.90,-2.05)。相对托盘抓取和货架槽位保持，装运/卸货评分未改。静态直行最小间距约30.42mm，扣5mm采样界后25.42mm；见证为托盘边墙与归位夹爪，说明交接附近仍是局部贴近区，不称全场任意姿态宽裕。x=2.7掉头区全角样本净距至少.2m（查询上限），交接点旋转样本仅1mm，不能作为可自由掉头结论。

独占170/API9140，原生Smac Lattice三次ComputePathToPose均accepted/status4/error0。到B、到A、B返回staging的原生路径分别92/32/92点；完整模型插值扫掠364/124/364样本，扣空间采样界后余量25.580/25.658/25.580mm。路径时间估算49.533/21.200/49.533墙秒，假设实时率1且跟踪路径；是估算而非实跑耗时或上界。控制配置复用现有Graceful候选、Smac平滑、.06/.10载货限速与原加减速；全局附加缓冲为默认25mm。未派发NavigateToPose、Dock或装运，规划通过不代表控制消费或完整运输。

模型原生1000步静置禁碰0；原始模型参数、地图像素迁移、工位/订单一致和直线/转向分项测试通过。首次原生脚本因PYTHONPATH覆盖ROS路径而在import rclpy时退出，无ROS动作；随后复用fishbot_mujoco_env并追加路径运行成功，失败日志保留。截图使用新MjModel和实际home姿态，避免Physics用于排除自身雷达的group4/5把显示模型隐藏；仅调显示灯光，不改变执行模型。

采用知识库Wiki/ROS2 与 FishBot“差速进场：宽处完成朝向，再倒入目标”的完整几何/转角/预算分开判断经验，以及原生动作/物理评分分层；本轮范围为场景切换与规划，不将它写成载货或sim-to-real验收。
