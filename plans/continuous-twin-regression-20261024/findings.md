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
