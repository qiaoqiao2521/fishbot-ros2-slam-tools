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
