# F1 Progress

## Current
2026-10-24转入用户授权Kaggle，CLI身份经官方token introspection为`muqiaoqiao`，用户已确认继续该账号。真实私有CPU前检v1完成：Ubuntu24.04.5、glibc2.39、4核配额、约32GB内存，默认Python3.13、无ROS/MuJoCo；loopback UDP与GitHub可达。上传本机原Jazzy运行库，独立使用Python3.12，不绕过ROS源TLS主机名错误。运行包220.66MiB，原许可证保留。旧cache目录已不存在，新输入是重建候选，不称同输入重放。

私有运行包首创建返回Ok，但status/files/metadata均403、mine无该条目。完整作业v1因CLI剔除无效数据源而在启动ROS前失败；同时保留异常报告拼写错误，当前已修复并故障注入验证。小型同账号私有数据集实际ready，排除“账号不能创建任何私有数据集”；正在给原运行包补许可证description后重试同slug，尚未宣称根因。未运行云端导航或两单。产物留`~/.local/share/fishbot/cloud-jobs/kaggle-20261024/`；部署入口`experiments/kaggle/`。

运行包补description后仍403；保持相同description和私有slug，给四个原tar/gzip增加19字节格式头后实际ready。独立CLI文件列表读回四个`.tar.gz.bin`原尺寸加19字节，及bundle/candidate/versions三文件。官方文档明确平台自动解压archives；本地往返测试保留执行权限和符号链接。该对照支持归档摄取路径问题，不排除平台时序因素。新增显式`--isolated-runtime`仅跳过云端不存在的本机systemd服务快照，记录空范围；原UUID/静止/owned清理与全部物理评分不变，25项factory检查通过。部署四个脚本语法、异常报告故障注入和候选7项原门槛检查通过；将更新输入源码版本后运行云端部署。

本轮不暂停本机其它任务，也不换浏览器账号。下一步先核实运行包ready/文件及真实挂载，再完成依赖、同版原生补丁与时钟检查，最后原factory的B→A独立评分。原速度.06/.10、加减速、碰撞、支撑与120/360/1000保持。knowledge_status=pending（云部署尚在执行，root收尾再判定可复用结论）。下文为历史本机试验，不作为云端通过证据。

2026-10-23用户接续要求恢复计算余量后继续。启动前load12.668、CPU等待压力约3%、频率约1.99GHz；未停止其它任务，同配置复跑`native-loaded-east-terminal-tracking-recover.py`。运行中再次出现Blender/Applio并行占用、频率约1GHz，19.3墙秒仅推进8.28源秒。原UUID8ec8b63099a9425aa8c1508e1e8532ff在1帧原载货支撑失败后取消5；1396个独立物理样本、禁碰累计0，最大位移.397988m，1442条带plan非零cmd。最终相对B误差1.249013m/.873102rad，不是到达；最终hold=true，但原post-hold源时间停稳等待超时、quiet=null，不能计清理静止通过。

原生进程/9111关闭、owned存活0；sim节点销毁阶段KeyboardInterrupt仍保留。包装物理步均值6.682ms、发布19.402ms，源样本保留窗内无>.1s缺口，不据此否认墙钟计算不足。新完整B→A未派发，速度/加减速/模型/碰撞/载货/评分/期限未变。证据根`j100-transport-20261023/native-loaded-east-terminal-tracking-recover/`，包括result、independent-ros、launch、loop-timing和少量只读bridge采样。

历史上曾请求允许临时暂停本机Blender渲染和Applio语音任务，未获确认、未执行暂停；后续已按用户授权采用Kaggle。仍不自动改变热控制、网络或其它任务。owner=本对话root，原FishBot19/20双时钟、证据分层和进行中任务保护继续采用。

2026-10-23 J100组合仍未通过完整B→A。已采用用户确认的.06m/s/.10rad/s上限；原B空托盘原生4/86.151s/2.079cm。首轮完整B原K通过，但起步后瞬时托盘断触，连续支撑与交付失败，A未执行。后续载货诊断分别出现原120秒取消或1–3帧支撑失败；远侧(1.7,-2)入口原生4且连续支撑通过，但用时118.429秒，最终B仍取消，不能计交付成功。

原生半速时钟对照已通过：原墙钟平滑器源时间斜率.04997/.09995，显式ROS时钟候选.025/.05；暂停时钟输出6/0，动态调频均接纳。此事实修正计时语义，不独占货物失败因果。雷达查询仅做原生运动学，20组×5760射线的点/命中ID与完整forward逐点一致，13项雷达测试通过。可选关闭概览渲染保留RGB路径。

116项相关检查通过；同一个performance窗口零运动对照，原inline推进.89173倍实时，显式queued推进1.000倍，清理无错误。队列只在后台接收，原回调接收墙钟保留、命令/重置/物理仍由主线程应用。默认inline保持。公开原生时钟入口在改频后重测源斜率.05及暂停0输出，通过；不是仅ACK。

最新两个短试验均全程载货支撑通过。50Hz源时钟/.055弯道候选在终点附近w=0，未完成收尾；trace目标距最小15.618mm，原RPP在31.62mm内曲率归零，未进15mm目标圈。保持全部容差，启用原生fixed curvature/after-goal后，入口(.95,-2,0)原生4、连续静止与hold确认通过，但用时114.524墙秒；原B第二段5.56秒后在9.406cm处取消5，整路仍false。曲率前视点实际发布2137条，参数回读true/.2/true。owned/9111全部清理。

完整反馈的control组首次外层180秒超时，其余mission209/autonomy61/frontend460共730项通过；同源码control组从原`--python-group control`独立入口完成997项/435.448秒，无跳过或缺依赖，未修改测试或配送期限。首次整命令仍记failed，不改写为默认入口通过。相关源码9bf99c7已推既有远端，116项相关检查通过；没有改测试来消除超时。

最新`.3m`曲率前视/`.12m`接近距离/`.02m/s`最低接近速度候选及同配置复跑均未到达。复跑原UUID00f5de16108f4733945ca991afa9bd9a在120.062695墙秒取消5，仅派第一入口，最终相对B误差.949036m/.747186rad。1981个独立物理样本连续载货失败0、累计车/臂禁碰0；1761条带plan的非零cmd和1.035450m真值位移证明实际跟踪，不能代替到达。源起点4.46s、清理quiet40.24s，包含清理也仅35.78源秒；最大保留源间隙.24s。末hold/原.7源秒静止、owned进程与9111清理通过；sim销毁节点阶段出现KeyboardInterrupt，保留该finalization诊断，不称无异常退出。未启动新的完整抓放/B→A。

最新静止交替诊断将线程切换5ms/.5ms/5ms/.5ms/5ms逐段恢复。五段仅.286/.296/.305/.291/.263倍实时，主线程CPU占墙钟.846–.964；原生mj_step线程CPU均值3.009–3.173ms，墙钟3.191–3.603ms。当前有限面板支持计算能力不足，不能再把主要耗时猜作GIL等待；没有证据采用短切换间隔或实时调度。独立接收97条实际点云，物理观测全hold，0任务/0Goal，退出0且无finalization错误；保存phases/receipt，不是逐帧点云归档。原较好窗口曾到1倍实时，不能据此预测当前完整图也能实时。

当前没有运行中的本轮ROS实验。候选未晋级默认参数，原完整`full-scene/world.xml`/A/B/自由货物保持。计算余量恢复后，从`native-loaded-east-terminal-tracking-reproduce.py`同配置短路线继续，先完整到达、连续载货、停稳和清理；随后才运行已dry-run的`j100-source-clock-terminal-full-manifest.json`同轮order-b/order-a，输出`full-source-clock-terminal-b-a`仍未创建。原native1.5cm/.035rad、物理4cm/.05rad及120/360/1000不变。不要放宽时间、关闭碰撞、减少雷达或修改其他任务来制造通过。

新增证据均在`~/.cache/fishbot/factory-line-delivery-20261021/j100-transport-20261023/`：`native-loaded-east-terminal-tracking-{probe,reproduce}/`原result/ROS记录/loop-timing；`capacity-profile/`只作剖析、不用于性能排名；`capacity-native-thread-clock/`交替phases/receipt。`capacity-gil-aba/`探针末段ValueError保留；修正后的`capacity-gil-aba-b/`同时受频率变化影响，恢复5ms也达1倍实时，不宣称1ms改进。`capacity-physics-scheduler/`RR10仅.362→.423倍，已恢复SCHED_OTHER，不采用。CY只读确认3vCPU/约952MiB可用内存/无ROS容器栈，未部署、未改远端文件或网络。

知识回写`updated(local)`：原`Wiki/ROS2 与 FishBot.md`第19节补半速/暂停/改频的原生计时验证和后台接收/物理owner/原收包时刻边界，保留“计时不替代连续载货”的限定；`Wiki/开发知识入口.md`新增对应触发行。原页与入口已读回。知识仓已有其它dirty修改，保留且本轮未宣称发布知识仓。

最新线程CPU对照的knowledge_status=already_covered：原第19/20节与“控制排程：先核唯一业务组，再选执行器”已要求区分墙钟、同线程CPU与GIL/OS假设。本次有限数值留在项目，不重复写知识页。接续owner=本对话root。

最终独立清理读回`source-clock-terminal-closeout.json`：原复跑PID/starttime匹配存活0，本轮sim/bridge/探针匹配进程0，9111关闭，无FishBot临时inhibitor，power profile恢复balanced。保留其它任务和网络。本次追加仅更新现有SpecMesh三文件，源码检查证据仍绑定9bf99c7，不为文档改动重复完整回归。

2026-10-23 Smac Lattice显式接入与有限面板已交付，J100组合仍未通过。原生1.3.13插件、官方248条diff/.60m/2cm原语、独立库缓存补丁、可选Rotation Shim均落盘；39项相关与1727项完整反馈检查通过。9轮只规划找到完整几何正余量.05479m、估算118.844秒候选；3轮原B空托盘真实跟踪均在原120秒取消，最后22.614cm/1.00360rad，未执行新的完整抓放或A。不拼接成B→A成功。全部owned实例/9111/inhibitor已清理；知识updated(local)且读回。细节与最短接续入口见本文件末节，owner=本对话root。

2026-10-23 配送站进场与共享路线预算已实现：可选有序map姿态沿原Workflow持久化，原J100 body-frame出站后各进场点和最终点共用120墙秒，原360/1000与评分保持。当前原生只规划15组/25请求，5组整路完整几何通过，但这些采样路径预算均不足；新运输与新路线实际运动未启动、不计验收。两实例5583物理样本全hold、零任务/运动Goal，owned/9111已清理。原J100两次完整失败、A未执行和父FishBot2/2均保留；后续须先找到可验收路线。软件最终回归见下方本轮条目。

2026-10-23 本轮 J100＋3D 雷达验证已结束，组合未通过；父FishBot/planar同轮B→A物理2/2保持。新硬件已真实发布点云/IMU/wheel odom、接入原生两costmap/CM，完成入站、Dock、SO101抓放及出站；第二完整尝试的原K和连续交接/运输通过，但B载货Nav原120秒超时、交付false，A未执行。两个完整B尝试与短探针失败均保留，不拼接为两单成功。当前源码63ca9c4的140项相关检查通过；未通过的曲率/接近参数改动已存私有patch并从默认源码撤回。全部owned实例、9111和sleep inhibitor已清理。其后已补进场姿态与路径预算，当前仍需合格路线后验证同轮B→A。

2026-10-22 本轮F1 direct基线完成：实体占用场景同轮B→A原独立完整物理2/2，run5e1f02eb-d912-452d-9c76-0acc42d9b029、源码b158b65。B3.259cm/.02692rad、A2.531cm/.01719rad；原抓放/交接/留盘/运输/清理与120/360/1000预算保持。109项相关检查和两份原ROS记录独立回算通过。有效配置为Omni参考点模型＋运输Smac半径.10m＋两Python进程异步发布；默认值保持。旧失败保留，当前没有运行中的owned实例。

用户本轮明确后续只在当前对话独立实施，不再等待跨对话资源交接。每次原生运行前核对实际进程和端口，不停止其他任务。本轮141/9111、探针143/9113及临时sleep inhibitor均已清理；完整取证与采样缺口见下方“本轮有效交付”。原固定direct、NavFn/Smac .20、休眠/时效失败及e/d各轮历史仍保留。

## Done
- 2026-10-22当前有效切片：B→A完整物理2/2、109项相关检查通过；默认兼容、原门槛和独立知识本地回写已核对。细节见下方本轮有效交付。
- 已读 F0 厂区协作约定，明确两个配送工位/目的地和可选通道占用。
- 确认现有订单/目标、prepare 地图生成和原物理 oracle 可直接复用。
- prepare 的可选 --factory-config 与 workflow 场景订单薄 hook 已接入；旧 workflow 49 项回归通过，尚未计厂区实际配送成绩。
- 场景worker 10项含四个真实静态MuJoCo3.3.7构建通过（13.690s，临时目录清理、仅标准输出证据）。根公开prepare成功且manifest独立读回。
- 评测入口经独立审查修复running任务误清理及跨360秒误通过，根独立19项合同回归过（0.011s）；不修改原评分。根另重跑10项场景/四静态构建过（16.954s），证据 ~/.cache/fishbot/factory-line-delivery-20261021/factory-scene-tests-root.log。

## Remaining
本轮occupied direct的B→A已通过，原open无需重复；旧occupied-v2 B失败保持其历史裁决。via策略、RGB和P8的J100/3D雷达复用仍待各自面板，不算本轮全场景通过。下一实施owner为本对话FishBot root。

## First entry
公开入口 tools/cooperation_factory.py 已冻结，完整命令见 docs/FACTORY_DELIVERY.md。根已生成 ~/.cache/fishbot/factory-line-delivery-20261021/open-v1/scene/scene-manifest.json，并独立dry-run确认两订单A/B、0 ROS/动作、输出未创建。实际命令：

```bash
FISHBOT_MUJOCO_DOMAIN_ID=141 XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus bash -c 'source tools/fishbot_mujoco_env.sh; exec /usr/bin/python3 -B tools/cooperation_factory.py run --manifest /home/muqiao/.cache/fishbot/factory-line-delivery-20261021/open-v1/scene/scene-manifest.json --output /home/muqiao/.cache/fishbot/factory-line-delivery-20261021/open-v1/run --candidate baseline'
```

`--order order-b --order order-a`改变订单排列；候选标签不加载代码。执行状态、原物理裁决与单单360/整轮1000预算分列。未执行和未评分均不计通过。

## Knowledge closeout
updated(local)：根已回写 Wiki/ROS2 与 FishBot.md 第19节车型/曲率/缓存/厂区配置经验，第20节同任务终态/预算/保护快照边界，并更新 Wiki/开发知识入口.md 的触发词；rg 读回已核对。知识库独立未提交，不宣称远端发布。

## 首个原生结果与独立读回
- 场景 f1-line-side-open，run 7daac585-8230-4c15-b4b3-36e8c7f4ef8e；结果 ~/.cache/fishbot/factory-line-delivery-20261021/open-v1/run/result.json，执行completed，任务裁决passed，overall=true。观测mode=ideal，车辆FishBot，planar。
- A：task f70f62ae-7cd2-4076-92f8-2d7ee949b901，221.105墙秒，交接后货物XY位移1.789756m；末误差.0323364m/.0301715rad，连续停稳2.48源秒；载货Nav eaf5473fa88b4a56bd58f50bf8908ab1，原始status2→4。
- B：task 34f7348a-ba63-4425-af3c-0a1dc51881f6，207.481墙秒，交接后货物XY位移2.473837m；末误差.0302101m/.0211736rad，连续停稳2.62源秒；载货Nav01946538961a4ae3a7e6af0b2900f6b3，原始status2→4。
- 独立worker仅读磁盘再次核原K、双指抬升/释放落稳/臂回位/同自由货物运输与交付均过；累计车臂禁碰0。原reset回执/新episode/源stamp交叉吻合，无重发。10份选定源码起止一致；不是所有二进制/子进程import的完整冻结证明。
- 保留缺口：A最大physics源间隙.260s，B.040s，记录器完整写出不等于源采样无孔洞。before六个旧systemd单位均not-found/inactive，after只有原result比较布尔而无原样快照；不能宣称旧107/114活进程持续保持运行。本轮只操作own launch，未补启旧实例。目标发送证据仍为桥冻结请求/accepted handle，独立原生status不冒充控制器消费回执。
- 订单间reset车和同一个自由cargo；不声称连续无复位排程收益、多货物并行、目的地下货或PLC签收。

## 实体占用变体
- occupied-v1 run bf05918e-14a2-4efa-bc1a-2495f0f6dd1c：旧箱(-.45,-2.10,.25)、尺寸(.18,.30,.50)挡住声明的直线入站扫掠，margin=-.163494m；0 start/reset/cancel，未启动世界。仅说明这条入站证书失败，不说明全局不可达。
- v2 将箱声明改为中心(.35,-2.10,.25)、完整尺寸(.12,.30,.50)，open/occupied 配置使用同一几何，仅 occupied 不同。四个 FishBot/J100×open/occupied 静态编译、原入站扫掠通过（19.84mm 总余量）；不算四组合运动验收。worker 11 项通过。
- occupied-v2 run 630e7143-a33b-4b71-a357-d3c7102d7404，454.848墙秒；task状态两单succeeded，原物理 task_verdict failed、overall false。A task4c74591b-a9ff-40f1-8fff-25438ce8ca5b，189.607墙秒，末 .0319643m/.0232663rad、停稳2.48源秒，物理passed；B task0e7feb87-016a-4522-99a6-8f32a164e86d，216.670墙秒，末 .0434781m/.0289143rad、不满足4cm内连续停稳，物理failed。
- 同一桥2start/1reset、原生载货Nav分别ed93dc3ae0a5479f8010e104d25183fd和d12ad4d4975d4c3a9cd7591cfb0c0994，均原UUID status4。原K均通过；原整体评分仍拒绝B，未放宽任何物理门槛。
- 选定源码起止一致，任务/总预算均内，owned launch/observer/端口均关闭；保护before/after原样快照齐全且六个配置单位均not-found，historical_instances_were_running=false。这不是旧实例运行证明。独立原始来源：~/.cache/fishbot/factory-line-delivery-20261021/occupied-v2/run/。
- open-v1到occupied-v2间仅补teardown诊断及保护快照元数据，不宣称严格同源码性能A/B。原失败不覆盖，未自动重发。

## 最近回归与后续候选
根完整反馈1621项及133项P8/F1相关原生离线检查通过，零skip。goal持续XY检查和雷达自定义配置接线随后6项局部检查通过。B失败只读取证：载货轨迹实际从箱下侧绕过，车/臂禁碰0；早期XY进入容差时朝向未达标，Nav4时真值43.447mm，hold后仅移动31.9µm。候选持续检查XY以免转向漂移后继续算到达，控制器内部锁定仍需核实，尚未记新原生通过。

下一真实策略入口已在task_plan指定，状态pending、owner=FishBot root。--candidate仍只作标签；不把源码观察当加载证明。优先路线/中转选择的同场景独立比较，订单全reset边界保持，不宣称连续排序收益。F0根已独立读回open两份原score；不重复open运行。

F1实现与已完成结果作为bb9141e交付到既有origin/main并读回；82902c5补车型执行器候选及后续策略边界，未宣称占用变体或P8全通过。P8 L首行保持失败，在途运动实例已清理，源码由FishBot root统筹。

## 路线策略加载软件交付
新增cooperation_factory_policy.py及--policy-config，实际加载内置/本地函数并调用一次，返回None或map{x,y,yaw}；原SceneGeometry点检、原native carrying Nav2与oracle继续执行。保存真实模块/__file__/函数/输入/返回/异常回执与私有派生manifest，原prepared不改，label仍不加载代码。只支持FishBot factory/no body egress_motion；J100在import前明确不支持，dry-run/report不执行目标函数。

worker31项0.149s过；根独立31项0.164s过，含真实纯软件子进程导入并调用自定义函数，非空点→派生manifest→geometry/launch参数消费为mock合同而非物理成绩。root已审context深拷贝、原目标保留、异常不回退、复用既有owned进程回收。原生occupied direct/via对照pending，由root在P8 M清理后执行；不重复已通过open、不把策略调用当改善证明。例配置与使用见docs/FACTORY_DELIVERY.md。


## 同一新prepare的direct/via窗口
O已清理且当前无FishBot物理进程。研究根与无人机已确认串行交接：无人机原生ground/箱顶取消在先，明确terminal交回后先direct，完成/清理即归还，via另约窗口。一次run两订单沿用总1000墙秒/每单360墙秒，不要求不可分割长窗口；预估450–650墙秒仅计划值。root不停止他人渲染或修改全局算力。

已从同一line-side-occupied配置新prepare到~/.cache/fishbot/factory-line-delivery-20261021/occupied-policy-20261021/scene/scene-manifest.json。只读核对FishBot/planar/transport、实体占用=true、A=(0,-2,0)/B=(.7,-2,0)，新YAML双stateful=false、原native .015m/.035rad不变。旧occupied-v2 prepared仍checker stateful=true、RPP未显式false，不能混用旧运行配置检验新候选。两次策略只改可选中转，复用这一份新prepared以及同一源码/固定订单/原裁判，分离输出和新UUID。

```bash
# 先等明确窗口；在FishBot根执行。两条分别占用一个窗口。
FISHBOT_MUJOCO_DOMAIN_ID=141 XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus bash -c 'source tools/fishbot_mujoco_env.sh; exec /usr/bin/python3 -B tools/cooperation_factory.py run --manifest "$HOME/.cache/fishbot/factory-line-delivery-20261021/occupied-policy-20261021/scene/scene-manifest.json" --output "$HOME/.cache/fishbot/factory-line-delivery-20261021/occupied-policy-20261021/direct/run" --candidate direct-current --policy-config tools/config/factory_policies/line-side-direct.json --order order-a --order order-b'
FISHBOT_MUJOCO_DOMAIN_ID=141 XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus bash -c 'source tools/fishbot_mujoco_env.sh; exec /usr/bin/python3 -B tools/cooperation_factory.py run --manifest "$HOME/.cache/fishbot/factory-line-delivery-20261021/occupied-policy-20261021/scene/scene-manifest.json" --output "$HOME/.cache/fishbot/factory-line-delivery-20261021/occupied-policy-20261021/via/run" --candidate lower-via-current --policy-config tools/config/factory_policies/line-side-lower-via.json --order order-a --order order-b'
```

窗口等待期间只做离线回归/文档；两条尚未执行，不称已有真实路线策略对照。若其间源码变化，先记录并重新协调同源对照，保留原失败。知识updated(local)，第19节及入口已补末段速度/进度分辨率和连续样本诊断，读回成功，未发布知识仓。


统一check-feedback已纳入loaded limits和factory/policy三组55项，集成完整1678项通过（control948/mission209/autonomy61/frontend460），零skip/缺依赖。两条实际命令已通过bash -n，新prepared双stateful和原目标/容差读回有效；窗口尚未释放，未启动direct/via。


## direct窗口已启动（在途）
无人机owner明确完成ground32/48 terminal和owned清理后交回，研究根再次确认。最后147项native相关离线回归过144.492s并退出；1678反馈保持。direct首次run已启动，141/9111，checkpoint78c3db1；无重复派发，不扩via。真实policy-receipt已经记录cooperation_factory_policy.py的direct函数实际被调用、返回None、derived manifest无egress，静态geometry通过；运输结果仍在途。结束/失败与清理后向无人机及研究根回告，来源三层不混计。


## direct零订单启动失败与显式manifest修复
原run3f80df76-e520-4fd8-a65c-ad6671a0ffd5：readiness70.315墙秒超时、0订单、0start/cancel/reset，实际策略函数direct调用成功/返回None、geometry过，原result执行unknown/任务unknown。launch将私有derived-manifest交给bridge，sim.source_identity仍固定读world.xml同目录scene-manifest.json，导致生产器manifest身份与bridge不符，原日志持续拒收。不是路线失败成绩，也不是只改标签。

根先核API task idle/id=None与零mutation，复核保留launchPID2383948/PGID及derived参数，SIGINT仅owned组。18个owned身份均退出、9111关闭，另存原run/reconciled-cleanup.json，不改写原result为成功。原窗口已明确回告并归还无人机/研究根，不自行扩展via或继续重发。

最小修复：sim新增可选--manifest，Physics/source_identity接收显式路径；launch把同一路径同时传给producer与bridge。未指定时仍读scene sibling，原物理/身份/时龄/评分不变，不新增hash执行锁或绕过校验。新增实际MuJoCo构造derived身份/原prepared不变检查与原launch命令接线回归2项通过7.224s；78项相关sim/launch/factory/policy完整回归过62.003s。随后补充真实raw按派生身份接纳、按旧身份拒绝的断言，单项过5.910s。新direct/via须使用修复后同源配置与独立新输出，旧direct/run原件保留。


## 修复后窗口准备
显式manifest两端接线修复通过78项相关回归，真实raw原身份不匹配仍拒绝，默认省略参数行为由原完整sim用例保持。新共享prepare输出改为~/.cache/fishbot/factory-line-delivery-20261021/occupied-policy-fixed-20261021/scene/scene-manifest.json；两轮输出分别为direct/run、via/run。原occupied-policy-20261021/direct/run为零订单unknown历史，不覆盖。两条命令只把前节三处父目录occupied-policy-20261021改为occupied-policy-fixed-20261021，其余目标、order-a/order-b、policy-config、141/9111与1000/360预算保持。

root核实修复、读回新prepare后申请direct新窗口；明确交回前不启动。知识updated(local)：原第19节377行与开发知识入口48行已补派生配置生产器接线经验并读回，独立知识库仍未发布。P8 O仅参数应用前超时，不因本修复记导航通过。


## 可恢复交接
owner=FishBot root。最新研究根排程尚未给F1放行：SO101独立XY两短回合后，无人机还有native48正负与箱顶取消闭环；不能把SO结束当自动放行。当前没有FishBot ROS/MuJoCo/浏览器QA/测试/prepare在途，源码修复e573eb6及共享fixed输入已完成验证并保留。接续只在原对话收到明确窗口后，以本节fixed父目录、新direct/run执行一次；同次运行对账不重派。完成或失败后保留原oracle与原1000/360期限，owned清理，再同时通知研究根和无人机；via及P8另约。知识updated(local)与全部原失败状态保持。


## fixed direct真实结果：入站失败，未进入载货
任务437abb20-ffbf-4dd6-a749-71f0d1cb709a、回合4bf9999c-94da-45bd-bd48-e5ebc6597608；实际direct函数与derived身份已接纳，唯一start。入站目标(-1.1,-1.8,0)，原Nav UUID846d3462e24c477e99cd3b7a51f10072在120墙秒取消终态5、result_known=true。标记wall持续120.87754s，未触360；无Dock/抓放/运输。原score-1792574214379374646.json passed=false/原K=false，交付误差None是未到交付的合法状态，B未执行。

报告器把None当dict，order_report在正文与finally各抛AttributeError，原result及source-end快照未落盘，caller134。不能用调用退出码替代原oracle，原run_id仅曾在内存，现不可恢复。null指标两行兼容修复保留None和failed；22项factory检查过.007s。只读reconciled-result.json从原declaration/terminal/score/markers/cleanup恢复摘要，original_run_id=None、source end未观察，不冒充原runner成功完成或源码全起止一致。

原bridge cleanup verified（native_terminal/quiet/hold/guard_disabled），独立observer连续quiet1.88源秒通过。根复核task/UUID/owned命令行与PGID，SIGINT仅launch2478406组；reconciled-cleanup.json记录所有owned身份消失、9111关闭。窗口已分别明确归还无人机与研究根；无自动重试、无via、无新P8。

只读原observer入站末端：source95.38–125.38的1501个去重map姿态，goal距离5.743–23.660mm、yaw1.989–2.545rad，15mm圈跨110次。下游cmd v始终0、w-.68653至+.59992；真实车体hold=false、yawrate-.60159至+.56764，XY仅约9×7mm范围运动。符合圈内终态转向/圈外路径转向切换，非单纯转不动；没有controller内部逐分支回执，不能独占因果。证据inbound-convergence-readback.json，原source/姿态/动作门槛保持。下一修复先查阶段XY状态锁/紧目标圈的控制合同，不能把它记为路线策略差异。


独立原nav_status已核UUID846d3462e24c477e99cd3b7a51f10072：status2接收于1792574087.019367、3于1792574207.048853、5于1792574207.073928墙时。不是只采信bridge终态。knowledge_status=already_covered：Wiki/ROS2 与 FishBot第19节已记录双XY锁、关闭后位置/朝向往返及独立原ID/物理评分边界，本次追加量化证据留项目，不复制原日志；null指标修复为通用可选值处理，无新知识页。root后续先恢复入站收敛基线；保持原目标容差、物理评分、期限，不扩展本轮窗口。


## 阶段XY软件候选（禁止冒充运动通过）
按研究根授权只做软件整改：复用原Nav2 1.3.13 FollowPath.controller_id/goal_checker_id与NavigateToPose.behavior_tree，为入站复制同一RPP/目标检查器配置，仅stateful=true；原交付FollowPath/general_goal_checker false保持。两个XML共用原规划/恢复图，主树显式绑定general_goal_checker，staging树显式绑定StagingPath/staging_goal_checker，避免多checker时空ID歧义。所有原速度、容差、碰撞、进度期限和120/360保持，DockRobot/owner/原UUID/取消清理不变。无运行时参数交易或新控制器算法。

新prepare生成staging_navigation_behavior_tree；bridge仅显式staging=True的非载货入站在原NavigateToPose请求设置该路径，carrying及旧manifest默认空路径。native_actions.goal_behavior_tree单列实际请求，非控制器逐条消费ACK。官方同版源码已核对FollowPath端口与逐goal行为树装载；切换必须在前动作终态后，现owner合同保持。私人P8 runner生成输入观察纳入可选staging XML，旧证据不改写。

纯软件36项（3个阶段配置/XML、1个桥请求路由、22个factory、10个policy）检查通过，未启动ROS/编译/物理步进。原13项prepare及实际多插件生命周期尚未重跑，留下一明确窗口；现有fixed prepared尚无阶段树，不可用它验新候选。旧failed/unknown/reconciled记录与物理评分均保持，root不自动native/via。


阶段候选完整core108项纯软件回归过15.452s；补充可选staging路径为null时保持旧默认的路由断言后，3个阶段配置+1个路由复验过。分别用原FishBot/planar与J100/3D完整YAML/原BT复制到临时目录核对，两个阶段引用相同RPP类、Simple/Stopped检查器保持、.015/.035不变、ID均可解析到声明列表，未初始化ROS/步进物理/编译。该检查不是插件实际加载、prepare完整回归或运输验收。当前候选只在新prepare生效，旧fixed失败场景不修改，等明确软件/仿真窗口后生成新的共享stage场景再验收。


knowledge_status=pending（仅新阶段候选）：双RPP实例/阶段树目前仅软件配置与路由验证，未取得原生加载/完整运输证据，不向知识库写成已修复。owner=FishBot root；最短接续是下一明确窗口先做prepare/native消息与插件加载检查，再新共享场景direct原单轮，原评分/期限保持。既有双XY锁风险经验为already_covered。


为避免未来普通非载货导航误选入站树，bridge另用显式staging=True角色；只在既有vision/ideal两个入站调用处设置，载货优先保持默认。非staging的普通导航、旧/null manifest均默认树，不扩大作用域；该收紧仍纯软件，目标与原owner/期限保持。下一共享目录预定occupied-policy-staged-20261021/scene及direct/run、via/run，尚未生成或启动；明确窗口先原13项prepare/多插件加载与切树，再正式同源direct。


显式角色收紧后的111项局部回归首轮110通过，唯一失败为原vision入站测试仍期望旧kwargs（缺staging=True），原27.135s失败日志保留；已更新该原入站合同，未改任何物理条件，重跑到新corrected日志。此前108过/36过/4过保持各自版本边界，不把此首轮说成全绿。


显式角色合同修正后core+staging共111项全部通过12.996s（新corrected日志），原110/1失败日志保留。已收到无人机/研究根明确限定窗口：仅原13prepare与一个隔离实例两次AMCL当前位姿静止Goal加载核对（staging→默认，前UUID terminal后才下一）；car_hold保持，不扩完整direct/via/P8/QA或批次。完成后核原UUID/参数/独立静止与owned清理，立即归还。软件切片先冻结版本再检查；若静止Goal有误差不释放hold追目标，只保留失败/取消原ID，不重发。


限定静止窗口已结束并归还：`d`仅因未加载ROS环境而在rclpy导入前失败，零launch/端口。补正环境后`e`在domain143/9113一次启动，源码e4527a0，manifest staged与probe起止副本同hash。控制器双RPP、双GoalChecker六参数实际读回一致且运行前后不变，planner/controller/bt三节点active；请求行为树为staged XML，AMCL无运动更新产生新源戳7.6/8.5。staging/默认两个独立UUID均status4、result error0，两个follow_path子目标各自status4，439个独立物理样本全程car_hold，源0.82–10.02s。owned launch、9113、native上下文均已清理，未跑运输/13项/via/P8，窗口已归还。原探针`passed=false`，但后续只读原launch日志确认不是QoS不兼容：两Goal均以当前AMCL位姿发出，controller_server在`Reached the goal!`后直接结束，未到达先于`computeVelocityCommands`的调用点，因此RPP没有计算控制量，也未发布`/received_global_plan`；它是静止同点fixture无法证明阶段消费的预期结果。发布端默认Reliable/Volatile、KeepLast10，探针sensor-data为BestEffort/Volatile、KeepLast5，常见RMW本可建立匹配；原结果未保存端点QoS诊断，原“QoS不兼容”因果已撤回，改QoS仅保留为待验证的诊断假设。`e`还在原有限`d`授权明确“不自动e”后多执行了一次，属于流程偏差，失败保留且未自动续跑。原launch共有17条`Rejected car reference: stamped car command is stale or in the future`，其中首Goal结束到次Goal开始之间7条，其余在次Goal结束和清理阶段；这些旧时戳命令被拒未破坏观测到的hold，但本轮不能外推为运动中命令时效通过。原始结果`~/.cache/fishbot/factory-line-delivery-20261021/staging-native-load-e4527a0-e/run/`保留；私人探针后续改动仅py_compile通过，无新原生结果。

## 0.25m运动探针：首阶段有控制消费，第二段安全层拒绝
源码`baeee9c`、独占domain143/9113的`staging-native-motion-baeee9c-20261022-d`只做0.25m两阶段探针，未启动运输任务。私有探针把PublisherInfo的两发布端与消息回调GID分开：端点实际发现两个原生`controller_server`发布端，回调包装层`publisher_gid=None`只记`unavailable`，不再用不可观察的GID互斥否证阶段消费；每阶段以计划消息、控制命令、原Goal UUID/终态和物理位移分别判据。探针仍因阶段失败而`passed=false`，错误为等待第二Goal终态超时；原始214781290字节结果、launch日志和启动时源码副本保留；未保存收尾源码副本，不宣称探针源码起止一致。

Staging Goal UUID`b397308cebdb4f529642c6dc7e2ffb97`原状态2→4，result error0；收到364份`/received_global_plan`和365条`/cmd_vel_nav`，真值位移0.174915m，但终点`(-.0469720,-2.1684766,+1.6038226)`相对`(0,-2.25,+π/2)`为XY0.0940874m/yaw0.0330263rad，超过原0.04m/0.05rad验收，不能计阶段到达。第二Goal UUID`a8d75a9bc5aa4b789570ce6b2a83364a`从该偏差位姿发起，原状态2→3→5；RPP反复报collision ahead并patience exceeded，原树清除costmap后的重试和spin/backup恢复同样被碰撞拒绝；阶段消息在异常后未复制，数量未知，撤回“未产生计划/控制命令”。controller参数运行前一致，planner/controller/bt三节点active；探针等待终态超时后取消该原Goal。

只读分层解释：实体占用箱中心(.35,-2.10,.25)、完整尺寸(.12,.30,.50)，原完整碰撞几何静态预检在该局部仍为可走；Nav2运行costmap配置0.3m inflation，源图最近占用像元中心距起终点约0.29m。这只能定位软代价区域；本轮未抓RPP所用局部轨迹与costmap逐点代价，不能从进入膨胀半径推导碰撞，也不把第二段失败归为RPP阶段切换失效。Stage1没有达到原评分，整个fixture不可替换原配送或换路线记通过。

收尾独立读回`owned_launch_stopped=true`、`owned_port_closed=true`、`retained_launch_pid=null`、`native_terminal_known=true`、探针RCL上下文关闭；最终hold发布后被真实物理源观察，源戳91.46s、速度与角速度均约1e-17。顶层final_hold_restored在原失败主路径未写出，以cleanup_hold.observed为已观察字段，保留该字段缺口。资源owner消息明确本轮后交回SO101，因此未新启ROS/MuJoCo、未另换开阔fixture、未执行via/完整direct/P8；当前无本组owned进程或9113监听。


## 离线探针交付与真实扫掠复核

新增`tools/cooperation_staging_probe.py`，默认仅预检；显式`--run-native`才初始化ROS。复用原SceneGeometry、原owned launch/收尾和NavigationDiagnostics，不另建控制器或运输owner。修复嵌套costmap配置读取与相对地图图片路径，按源图negate/origin yaw和栅格半对角线给fixture余量；它只挑低干扰目标，不重定义硬碰撞。两个目标(-.25,-2,0)/(-.50,-2,+π/2)，每段25cm；源60s/墙70s分列，原到达4cm/.05rad、连续.7源秒停稳保持。

旧探针的Stage2空数组源于result超时跳过复制；新record_phase_wait在finally保留计划、命令、原计数、AMCL/TF和四个导航话题。有界样本与总计数分开，manifest每轮一份，每帧留episode身份，防止重复场景膨胀日志；接触异常总计数独立于有界尾部，不能因截断样本遗忘早期碰撞。请求发送前声明UUID，未回accepted不能被空集合算为已知终态；取消后hold、新源戳、quiet和进程/端口分别取证。原生分支尚待实际运行，软件测试不冒充其验收。

新fixture首轮静态check44ebe331-5342-44d5-9617-b45f3739d34d为false，来源`~/.cache/fishbot/factory-line-delivery-20261021/staging-probe-offline-20261022-v1/`。定位到分离旋转box-box的原生距离假负值，最小模型复现；公共pair_clearance只对严格分离AABB用保守下界，重叠保留原生查询。新v2 checkd5a2da81-cbee-46aa-a240-6bb7cc2dfd07为preflight_passed=true、passed=false（未运行）、ros_initialized=false、277姿态、physics_steps=0，扣5mm采样界后最小余量.1288312419m。目标到占用单元面积的距离下界分别.525950/.775921m，预检5342字节。原v1保留，原运动失败不改写。

首轮相关14项检查通过23.308s；补充有界尾部不能隐藏早期接触/缺失接触字段的负例后，最终15项检查通过8.184s，包括原真实场景的开放扫掠/占用拒绝、独立双箱几何正负例、阶段树合同、默认零ROS入口、超时实存、双时钟边界和重复manifest回归；零skip。没有运行完整反馈套件、任何新ROS/MuJoCo动作或完整运输。新入口使用说明与测试命令已写入FACTORY_DELIVERY.md。

Knowledge：already_covered，沿用原Wiki/ROS2 与 FishBot第18节软代价与禁区分层、第19/20节真值/原ID/物理评分、第17节去重记录；本轮只纠正项目记录。新增MuJoCo3.3.7旋转箱体静态距离边界为pending，owner=研究根Codex，最短入口为本节双箱负例与pair_clearance审阅，再串行回写原第19节，避免并发写共享知识页。

## 当前对话首轮运动结果与GID补证准备

本对话独立运行`staging-native-044acee-20261022-a`，check9fe1577a-54f3-4583-8a54-44adc61c133d，143/9113，一次launch、两个顺序原Goal。staging UUID77cad8cdb5634a3c843c8bae5b0836a6状态4，331计划/332命令、330非零，物理XY.066540481m/yaw.01980702rad，位置失败。default UUIDeb6536a51a304262a1c96d37ed7dd0d1状态5，1411计划/命令/非零，物理XY.0251961m/yaw2.74538349rad，70墙秒预算超时并取消；不是碰撞或progress拒绝。整体false，107.896墙秒，禁碰0，完整有界报告16.39MB。

原Goal终态、fresh hold、连续quiet.72源秒、owned launch/端口/native上下文关闭均独立确认。旧失败不覆盖。下一aligned fixture只隔离路径跟踪，目标(-.25,-2,π)/(-.5,-2,π)，相同25cm与原门槛；静态check0064a1ed-b7ff-451d-8172-5c6836847c19通过，未步进。

新增只读C++ plan witness编译通过，16项阶段/探针局部检查全部通过.259s。覆盖实际accepted时间窗、共享/未知GID、溢出拒绝及默认fixture保持。下一次新输出运行两段运动并记录native GID，不启动完整运输或把探针替代F1；资源依据实际进程核对，不再跨对话排队。knowledge_status=already_covered（双时钟、真值与物理评分），MuJoCo双箱经验pending接续owner更正为本对话FishBot root。

## 控制器消费与实例切换已取得原生证据

`staging-aligned-fbfdbbe-20261022-a`，checkfa4ebc93-8bfe-49ae-8fa1-f3153223d251，源码fbfdbbe071d5e384a79a88417ed4f5710ec83e41起止一致，51.2408墙秒。staging UUID027e86545ae8485eb75a52e80638d7f6、default UUID5c80075efeef4742ab56bdd510d6292a均原状态4且FollowPath子目标独立成功。真实rmw GID分别尾6c03与6703，对应同运行已发现的两controller_server发布者；331/193份计划、Python非零命令331/195、实际位移.234267/.244159m，阶段实例切换true。

原真值XY .0254803/.0262903m、yaw .0255410/.0135831rad，禁碰0、连续quiet各.72源秒，参数未变。native见证527事件（含ready及窗外消息）、无overflow，原始文件76328字节、结果11966911字节。原Goal终态、hold、连续quiet、native上下文、见证进程、owned launch与9113关闭均确认。原fixed失败保持，aligned只完成路径跟踪/阶段切换验收，不证明原固定朝向到达、整车臂任务或泛化。

随后实际核对无机器人仿真实例及9111/9113空闲，在本对话启动原`occupied-policy-staged-20261021/direct/run`，141/9111。保持原direct函数、原工位/订单目标、120/360/1000预算与物理评分，不修改路径或运行源码。首单taskbfe5a9c1-0377-4309-bd8e-d5629c989bbb已越过入站与Dock，正在arm_grasp；完整评分在途，不提前记成功，不自动扩via。

knowledge_status=updated(local)。原`Wiki/ROS2 与 FishBot.md`第19节“换车型与雷达”新增同点Goal/原生DDS消费见证与MuJoCo分离箱体距离边界两段；`Wiki/开发知识入口.md`同步触发词，已读回381/383及50行并diff检查通过。保留知识仓原dirty内容，未提交或推送该独立知识仓；此前MuJoCo经验pending已由本对话完成正文回写，不再挂给其他对话。

## 原staged occupied direct已完成：A通过，B末端朝向失败

run c15891fe-7f44-48de-93ab-935b4b98c050、源码fbfdbbe、141/9111，证据`~/.cache/fishbot/factory-line-delivery-20261021/occupied-policy-staged-20261021/direct/run/`。整轮680.8608墙秒，两个原task耗时266.7911/351.7359，均在原360内；总在1000内。原direct函数实际调用/返回None，新derived manifest两端接纳；2start/1reset/0 API cancel，没有自动重发。execution completed、task_verdict failed、overall=false，不能把执行完成当业务通过。

A taskbfe5a9c1-0377-4309-bd8e-d5629c989bbb/episode9280b416-1989-4d56-ad7e-00abfbf1fe68，原载货Nav6957fe4b98cb4b7cba6a6e7dd3b04995状态4，原K与完整评分均true；末XY.03593570m/yaw.04375309rad、连续停稳2.58源秒。B task17c13bd7-22d4-4536-ba23-70ef5a429e7b/episode85c1838f-f2d7-47f2-9388-4917ba4d6c4e，原载货Nav39cdc2aefe75407f82aa008a13418693在约120.06墙秒取消5；原K/连续交接与运输true，但目标yaw1.573289rad、XY.01853856m，完整评分false。双指抓取/抬升/释放/落稳/home/留盘不等于最终朝向达标。

两单入站Nav分别1b9252f6f0494bd3b4885b6a8f04ceb5、75d20cf5e08847af9e05e62f8cd73d1c，均请求staging XML并原状态4；对应Dock7a6badb0be1b4c03b27ccb982b9d50b1、946b5f116386438faeaa06899776868f均4。原完整oracle未声称控制消费ACK；此前两段探针独立GID见证已通过，不移植其字段来修饰完整任务。

B最后30墙秒只读取证已保存`order-2/terminal-convergence-readback.json`：862物理帧hold全false、禁碰0、XY1.31–2.23cm、yaw1.30–1.79rad；601条原命令v=0、w±.8、换向21次，HTTP map15mm圈20次。它定位末端位置/朝向切换环节，不独占内部根因，原日志无collision/progress/patience错误。下一步先此局部收敛，via和P8未派发；不新引模型或放宽原评分。

两份原score、独立native状态、source_integrity/recording_integrity均已读回；两份原记录未截断。护栏enabled但tripped样本0，未观察plant辅助介入。原task/UUID终态、hold/quiet/guard-off、owned launch/observer/上下文与9111关闭已确认，owned_process_survivors=[]，保留源码起止selected_text一致。保护单位前后仍均not-found，只说明该集合未改，不是旧实例活跃证明。

独立两段探针另保存`independent-readback.json`，不用探针评分函数，从原四元数/位置和accepted窗重新计算出同样2.548/2.629cm、.02554/.01358rad与331/193个原GID消息；两原UUID独立状态2→4，禁碰0。knowledge_status=updated(local)见前节；本次B末端现象为第19节既有双XY锁经验的实例证据，already_covered，不将尚未修复的候选写成长期结论。接续owner=当前对话FishBot root。

## B末端原生姿态规划候选（软件准备中）

新增可选navigation_planner配置与prepare参数，默认不改原源配置；smac-hybrid只替换GridBased，控制/碰撞/目标检查器不变。原短探针新增真实planner参数前后回读，避免只换标签。尚未启动新原生试验；下一入口为原fixed两段Goal和新私有candidate manifest。采用知识第19节的双XY锁风险/目标方向、双时钟和真值隔离经验；knowledge_status=already_covered，候选未验收不写为知识结论。

19项配置/探针检查通过.172s，原13项真实场景prepare检查通过10.149s，零skip。新candidate输入`smac-hybrid-20261022/scene/scene-manifest.json`直接复用原staged世界、两地图、原BT与几何，只使用同一navigation_planner函数替换GridBased；全部非planner节点独立比较不变。fixed静态check9bbf592c-7806-485e-9982-645f96611358通过，目标仍(-.25,-2,0)/(-.5,-2,π/2)，未步进。新原生短试验准备在143/9113单独执行，默认60源秒/70墙秒每段，完整运输尚未启动。

全Smac原生试验`smac-hybrid-20261022/fixed-a076e86-a`已结束，check2604eaa4-3aef-4bc3-bf20-6d115323673c、69.224墙秒，passed=false/errors=[]。原Goal均4，stage物理.06730769m/.05267926rad失败，default物理.03825184m/.02458898rad通过；真实planner参数匹配/前后不变、RPP GID切换已观察、原UUID/hold/quiet/见证/native上下文/launch/端口全清理。不修改该失败，不因两个Nav4当通过。

下一软件候选保留原GridBased/NavFn及全部入站控制，只增加HeadingAware给运输树显式选择；短探针回读双planner。此更改不是原全Smac结果改判，新输入另建`smac-transport-20261022/scene/`。短入站旧失败不重定义评分，若新默认运输段通过且原入站软件未变，再用原完整任务验证实际Dock/交接与A/B；完整运输此前未启动。

分阶段短试验`smac-transport-20261022/fixed-027fd08-a`已结束，check686917c3-21ee-40d9-9b2c-cecfb73c8b04、55.248墙秒，整体false。stage UUIDe322013c5c754ca09fb879b20d90fa96/default UUIDb37f483ce382499d801d2180622fe177均4，误差分别6.634cm/.03469rad、5.913cm/.02442rad；控制/RPP GID/双planner实际回读，参数与源码前后不变、禁碰0、清理全过。结果保留，不按成功重写，未跑完整运输。

随后离线只读真值/AMCL与native模型：`offline-scan-map-readback.json`明确为重建扫描近似评分、0步进，非实时AMCL重放。真正原生均值复现在`amcl-motion-model-proof-20261022`，直接链接系统nav2_amcl；差速模型2cm偏置半圈误差5.701cm，Omni近0，零偏置与25cm直线控制正确。首手工链接失败已保留工具输出，改用原生ament依赖后编译成功。新增项目`cooperation_amcl_motion_probe`六案例均值合同通过，不把诊断退出码当物理验收。

新候选只比前一双planner输入改一字段AMCL robot_model_type，私有manifest在`smac-transport-20261022/amcl-motion-omni-20261022/scene/scene-manifest.json`；独立字典比较确认仅此字段改变。默认source不改源设置，所有噪声/观测/TF/物理/控制/评分保持。新增AMCL参数原生前后回读、34项配置/探针/prepare检查过9.646s，C++原生六案例过；短运动待验。knowledge_status=pending（新的参考点/运动模型均值经验），owner=本对话FishBot root，运行边界明确后写原第19节，不把尚未验收业务写成已修复。

Omni短运动`fixed-cbe3251-a`已结束，check3e782927-7a2f-4341-9f59-bcb16e962765、54.919墙秒，原两Goal均4；stage .05678021m/.03230424rad仍失败，default .01344995m/.00420539rad通过。整探针false不改。实际AMCL Omni/alpha=.2/500–2000粒子已回读，AMCL/双planner/控制参数与源码起止不变，禁碰0、原UUID/hold/quiet/见证/上下文/launch/9113全清理。

首次完整`.../amcl-motion-omni-20261022/direct/run`，runfc8589c7-d008-4816-ace2-a29a9159d869、20.204墙秒。首单task0d1580bb-3d7e-45bb-80c1-04478554db5d在3.008秒因共享反馈源龄.340s/接收龄.348s失效；入站UUIDc0428a6376724d2099c1b723f3b8bc95取消5并原清理verified。1start/0reset/0 API cancel，原score失败、B未执行、overallfalse；没有放宽门槛或重发未知任务。桥计时physics callback最大34ms、cache锁等待最大1.2µs，无>100ms slow事件，不能将该空窗独占归为长锁。原observer与result完整保留，owned进程/9111已清理。

按task_plan只允许一次独立同源复现到`direct-repeat/run`，若再出现同类时效失败便停止完整重复，先取证；不称同源码复现为新改善。当前task21cdd2d8-446e-4a2b-86a5-e7e5e3432db7已完成入站Nav eb096c050f114a9aaecb4fea188f4871及Dock aa1804c925084877a41907c001b7a94e（均4），闭爪装货中，完整结果在途。knowledge_status=updated(local)：原Wiki/ROS2 与 FishBot第19节加入参考点/原生AMCL均值段落，开发知识入口同步触发词，已rg读回原385/入口52行且diff检查通过；只讲已复现均值，不写完整业务已修复。独立知识仓保留原dirty，未提交推送。
# 回合切换修复接续（2026-10-22）

当前：本轮F1实体占用场景的B→A完整验收已完成，原独立物理评分2/2，109项相关检查通过。有效候选为Omni参考点模型＋运输Smac半径.10m＋显式异步发布；原阶段树、速度、碰撞、目标容差和120/360/1000期限保持。源码b158b65，独立原记录回算、同源/清理与临时防休眠释放均已确认。旧失败保持，via、RGB与J100/3D雷达不计本轮通过。

## 本轮有效交付：同轮B→A完整物理2/2

- run `5e1f02eb-d912-452d-9c76-0acc42d9b029`，源码`b158b65af753f5c6422bbab796d44f6054520bf7`，domain141/API9111，输入`~/.cache/fishbot/factory-line-delivery-20261021/smac-r010-omni-20261022/scene/scene-manifest.json`，输出同目录`b-first/run`。执行completed、task_verdict passed、overall true；479.706单调秒，实际墙钟479.706秒。两单分别203.638/232.162秒，均在原360内，总在原1000内；2start/1reset/0APIcancel，不重发。
- B task `aab663ba-f2a4-449c-966f-ea13097447a4`、episode `e5c73a76-8894-4439-b03f-1ac9859c6d57`，原载货Nav `1bdab46c3a8249629ac7fae585aa553e` 独立状态2→4；XY.03258884m/yaw.02692002rad，连续终点静止3.62源秒。A task `29d42ad3-33e4-49b1-b308-ae27118b94b5`、episode `459b348d-dfe3-4f5b-9ebe-4363bc13a31e`，载货Nav `96b67e0d2a4c4d9b87569131b6c4feaa` 2→4；XY.02531214m/yaw.01719479rad，连续静止2.50源秒。原K、连续交接与运输、完整目的地评分分别true，目标仍B(.7,-2,0)/A(0,-2,0)。
- 双指抓取/抬升/松爪落稳/机械臂回位、同自由货物运输和最终留盘均由原oracle验收。reset `f7963040-4dcb-4c3e-a42b-51d15d7d66a7` 原ACK、新episode与独立physics吻合。原生参数服务实际读回半径.10、DUBIN、近似目标容差0、双planner；原RPP、足迹、地图/世界及物理评分不变。B→A顺序已预声明，不能当相同顺序的单因素性能对照。
- 两份`order-N/independent-readback.json`只流式读原ROS记录，不导入控制或oracle helper；独立重算真值XY/yaw与原评分相差<1e-6、原UUID2→4、末hold/guard-off/留盘均确认。B90433/A81171行与原recording written逐项一致，164717516/152353509字节、无截断；source_integrity/recording_integrity均true。`independent-final-readback.json`确认选定源码起止一致、预算和原任务/回合独立。
- 采样仍有缺口：两单physics各缺2序号，最大接收间隔.07217/.10743秒、最大源间隔.04/.04秒；A clock最大接收间隔.13489秒。完整落盘不等于无损采集。guard enabled约6.44/6.36源秒、tripped样本均0，未观察plant辅助；mode仍ideal，不宣称RGB、真机或泛化。
- 两原task/所有原动作终态、hold、quiet、guard-off已读回，owned launch/observer/端口关闭、survivors=[]；临时sleep inhibitor随父进程释放，未改全局电源。旧107/114配置单位仍not-found前后一致，只说明该集合未变化，不宣称旧活实例持续运行。
- 最终六模块相关检查109项全部通过10.896秒、零skip，日志`smac-r010-omni-20261022/final-contract-tests.log`。没有前端变更，不额外跑全工作台或实车测试。默认NavFn/source AMCL/.20m半径和原固件脚本保持，成功配置需显式选择。

knowledge_status=updated(local)：原Wiki/ROS2 与 FishBot第19节387行已纠正“NavFn有路即可”的不充分结论，补路径末段切线/显式半径与有限F1结果；第20节395/397行记录重置竞态与宿主休眠，开发知识入口56行同步触发词，已读回并diff检查通过。保留知识仓原dirty，未提交推送该独立仓库。

下一步：冻结本轮F1有效配置；由本对话沿`plans/cooperation-workflow-20261014/`的P8入口验证J100＋3D雷达复用，不盲目复制FishBot的参考点模型或半径。via、其他研究候选和跨硬件成绩仍待各自原oracle，未运行不记通过。

NavFn＋Omni run6f7b9880-07a8-4332-981d-2891a1403d5e，a27cb6e，302.732秒，执行incomplete、0/1通过、A未执行。B taske9196637-2f3a-4622-a42c-7dab67f84b2a，272.542秒，原载货Nav764b9823af324e48a9eb7a998b393802在原120秒超时取消5；真值XY.03860390m/yaw1.356731rad，未完成连续终点静止。无freshness_failure，原生终态与hold/quiet/guard-off、owned launch/9111已清理；没有延长期限或拼旧A。

`native-planner-radius-20261022`零运动对照：.20m UUID31d71329ea3248609733f0abb254fc44为6/207、4.444秒0点；.10m UUID8837d98a3b434b148c3ccc8b91d23335为4/0、.10114秒86点；.05m UUIDe84873f6722b4eda84d46e82729bd724为4/0、.10115秒95点；NavFn4092158100184a01a1084db96da6452b为4/0、342点。实际参数读回分别.20/.10/.05。目标末段方向：.10为-.1433rad、.05为-.2912、NavFn2.3562；目标orientation均0，位置误差<.2µm。733原物理样本全hold、quiet2.98源秒、零车辆动作和速度发布，owned清理完成。

prepare新增显式规划半径、默认.20保留；无效半径不部分改原配置。36项配置/场景/探针检查通过16.980秒、零skip。新candidate与原Omni/Smac父配置仅半径.20→.10，其余节点、原双树、世界/地图不变；尚待完整物理验收。knowledge_status=updated(local)：规划对照和宿主休眠两条已写原Wiki第19/20节，原387/397及入口56行读回、diff检查通过，独立知识仓未提交推送；新半径效果仍不写成完整业务成功。

保持唤醒run477813c5-e130-4fe7-a0bb-e16c87bd3738，6b01bde（运行代码同353701c），442.357秒，执行completed/完整物理1/2。A task316cca14-fbac-4b02-bbea-c555b4aec4cc，163.811秒，末2.416cm/.01763rad、静止2.58源秒通过。B task40d0cd60-6fc3-42d4-8c85-dad9f71d964c，234.562秒，双指/交接/留盘通过，但载货Nav5faad13b8d8d4e66b5d8b6ba1e0657f1失败6/208，末距2.533m/yaw2.902rad；原HeadingAware多次no valid path，车辆未完成运输。无freshness_failure，两份source/recording完整性过、全部owned实例/9111已关闭，临时sleep inhibitor已自动释放。

`native-planner-contrast-20261022`只规划对照：HeadingAware UUID3ead6e54a5574ea689ad78e0b523838b失败6/207，4.351秒、0点；GridBased UUID1e8fe2432aa04e0395e5e6c433981f64成功4/0，.18282秒、342点、3.43764m，终点(.7,-2,0)精确。560物理样本全hold、连续quiet2.98源秒、零Navigate/Dock/速度发布、owned launch/9111已清理。其costmap为同场景原spawn的新实例，不冒充原载货B costmap重放。

`navfn-omni-20261022/scene/derivation.json`独立字典差异只有amcl.ros__parameters.robot_model_type，原GridBased/NavFn和原双树保留，地图/世界路径未变。新实验预声明B→A，原任务目标与期限不变；先完成新同轮原oracle，不拼旧成功。

异步run5a9e2528-eee6-46ae-a0cb-2fb735efbd06，353701c，328.617单调墙秒，执行completed/物理1/2/overallfalse；A task73420a4e-1bfd-4c00-978e-52a0cc793e18，165.848秒、2.444cm/.01697rad、静止2.44源秒通过。reset d50fbf69-bcea-4371-9e75-a668af3df8b5成功；B task999e60ee-82a7-4dee-b062-bfe02a6b50fa，121.529秒，在arm_transport因共享物理反馈中断失败；入站820f5ed7ba8f40178c9153f9d3c7731c与Dock fd217807509c43aa98bf8f5700bc4d21原4，未载货导航。2start/1reset/0APIcancel；原source/recording完整性过、原生终态/hold/quiet/guard-off、owned进程与9111均清理，源码起止不变。

`source-pause-readback.json`测得源262.26→262.28、seq+1，接收单调间隙1.47256秒、墙钟间隙6478.011秒。systemd-suspend.service原日志确认19:36:30进入休眠至21:24:28恢复，不将它误记为单一publish或MuJoCo算法耗时。下一运行明确临时阻止休眠、不是修改评分或算法后再碰运气；旧失败保留。73项局部检查不新增次数，源代码不再修改。

复现run4da35c3e-84b2-4f0c-b933-205cabb0fb02，237.506墙秒：首单task21cdd2d8-446e-4a2b-86a5-e7e5e3432db7通过原K/完整物理，XY2.439cm/yaw.02658rad、停稳2.58源秒；1start/1reset/0cancel，B未执行。reset原编号f8bb2c00-8be4-4517-9aed-2949e931a6e1已成功，新idle回合独立quiet.74源秒、原历史/所有Nav终态确认，确切owned PID432025、进程组和9111已清理；补充回读单列，不覆盖原runner清理失败。

新增竞态回归先失败，再以成功ACK后重读state的最小修复通过72项调度/厂区测试（.396s，零skip）；原记录离线重放3GET/0POST推进waiting_ready/index1。源码尚待本轮冻结；不得把软件测试当完整业务通过。既有知识写回updated(local)保持，新竞态经验暂为pending，owner=本对话FishBot root，原生结果后串行决定是否回写原第20节。

修复源码1790ccc的新原生run9ecd328c-002d-447a-86c3-f6cbc31b0d13，227.661墙秒，执行completed/任务failed/overallfalse。2start/1reset/0APIcancel，A taskb5f3bdd6-9604-43a7-82ee-028f067081c8原K及完整物理通过，165.638墙秒、XY.02500741m/yaw.00922804rad、连续静止2.52源秒；载货Nav ff7026deb7734821b53677eb44606118原4。原reset bb9eaf55-0437-44e4-93a9-acf63fd5eca4成功，B已派发，证明跨单衔接。B task9f90958d-f0a4-4634-ba10-d69cff5004c5，30.827墙秒，在Dock cb53cfeaa27c4a9da8e325d3666e5282阶段因工位相对观测过期取消5，入站Nav47b211257f974518b092b3b75a86fc73原4；源龄.34/接收龄.33279，不记B运输成绩。两份原source/recording完整性通过，owned进程/observer/端口全清理，源码起止不变。

新证据`publication-stall-readback.json`：桥位姿publish用时.323778秒，期间独立physics收到17帧（9694–9710）、源间隔.02秒、接收最大.02116秒、缺序0；cache锁max12.43µs、physics callbackmax45.57ms。只定位桥发布/调度路径，底层等待原因未唯一隔离。官方rmw_fastrtps异步发送复用候选通过原生writer get_qos读回，私有诊断0消息/0动作；新增--publication-mode仅作用sim/bridge，原Nav2、QoS、阈值保持。73项调度/启动/厂区合同通过.909秒，下一完整运行仅测试新配置，不是原配置第三次重试。

knowledge_status=updated(local)：重置两次GET竞态已写原Wiki/ROS2 与 FishBot第20节，原393行读回；开发知识入口54行已补触发词，两个文件diff检查通过。保留知识仓原dirty，未提交推送。异步发布尚为候选，不将未验收的效果写成知识结论。

## J100＋3D 雷达同任务复用启动（2026-10-22）

当前 in_progress；父 FishBot/planar/ideal 的同轮 B→A 2/2 保持。新组合尚未运行，不把既有 J100 模型或旧 P8 两批成功计入本轮。输出：`~/.cache/fishbot/factory-line-delivery-20261021/j100-lidar3d-20261022/`。owner=本对话 root，不跨对话协调。knowledge_status=already_covered：采用原第19/20节，待实际新证据后决定是否修订。

预检已结束并清理：`native-preflight`、`native-preflight-radii`、`native-preflight-navfn`保留全部未通过，`native-preflight-reverse`的入站/A/B原生路径与完整几何采样通过，独立全hold、无Navigate/Dock/速度发布。109原合同与新增反向阶段合同11项定向通过（重复项不相加）；冻结源码后以同订单B→A、same factory配置和新 `run-reverse` 运行，不传仅支持FishBot的map-egress policy，保留J100必要的原生body-frame直线出站。知识已覆盖，阶段/方向适配结果仍待完整运输。

首完整 J100 轮未通过：B在换向时一帧底面失接触，原K通过但原连续运输/交付失败，载货Nav5，A未执行。原360/120/评分保持。source/recording完整、quiet/hold/guard-off/两参数组恢复和owned实例/9111关闭均已确认。独立原始记录倒车7.24源秒，16个物理序号缺失保留。下一候选只将车型载货减速上限对称收敛，先离线检查后新输入新run；不重发旧UUID。knowledge_status=pending（本对话root，待候选实证后审定）。

减速新实例连续支撑通过，但B载货Nav仍原120秒超时，完整评分false、A未执行，全部清理。当前控制缺口收敛到较长Reeds路径及RPP换向/曲率跟踪；转短空托盘原B点探针（原120秒与几何/碰撞不改），通过后才重返完整B→A。零派发启动与动态重配bond失败分别保留，不归入运输统计。原父FishBot2/2不变。

## J100＋3D 本轮最终读回（2026-10-23）

- 交付源码：可选原生 `smac-reeds-shepp` 与前进入站／双向载货阶段配置、单任务profile JSON、载货对称缓减速。NavFn/DUBIN默认、原目标、完整几何、120/360/1000与原物理评分保持。软件与配置入口可复用，不称新组合通过。
- 实际两次完整B：5783e801在253.38源秒出现一帧底面失接触，原K true、连续运输/交付 false；bb15595d原K与连续运输 true、零violation，但原UUID61212817127c443b84b7d763fc46eb00经独立2→3→5取消，物理交付false。A两次均未执行。
- bb15595d独立读回：14493个含点云状态的物理帧，published140→3039、raw3039、错误空；源样本缺3序号、最大源隙.04秒。原source/recording完整性通过，不称无损采样。停车guard有介入，原telemetry单列，不称纯导航精度。
- 原生配置已在运行中GET读回：FollowPath反向true/rotatefalse，Staging反向false/rotate true，REEDS_SHEPP/.60，两costmap和CM同一标准点云topic。3D仅增加障碍观测；定位仍使用/scan＋IMU/EKF，不是3D SLAM、RGB或标定商业雷达。
- 空托盘B控制探针40ba0413e56c4d1288301b342aba0970原120秒后5，最后离目标.30998m/.66821rad；2310条原RPP速度命令角速超限0。接近距离候选另一原UUID也5，末.41997m/.74472rad，未通过。均无业务start，不算完整运输。
- 两份零Goal探针是测试工具hold QoS不匹配；动态半径对照是lookup重算触bond后未接纳，均不归入运动成绩。软代价/半径只规划对照保留所有不合格路径；不得从路径存在推定控制成功或所有路径均不可行。
- 未通过候选已完整保存 `~/.cache/fishbot/factory-line-delivery-20261021/j100-lidar3d-20261022/unqualified-curvature-approach-candidate.patch`（5610字节），相关输入/原生结果同目录，默认源码回到63ca9c4。保留曾通过42项局部软件检查的记录，但最终有效代码回归为140项，不合并计数。
- `final-cleanup-readback.json`独立核对14份owned报告，零匹配存活PID，当前9111关闭；零派发startup原unknown由单列补充cleanup读回，不覆盖原result。临时防休眠已释放，配置的旧systemd快照均not-found，不称旧107/114当时在运行。
- knowledge_status=updated(local)：原 `Wiki/ROS2 与 FishBot.md` 第19节补路径线／角速时间下界、活动Reeds重配的bond证据与hold QoS；原开发知识入口补触发词，已读回。独立知识仓原dirty保留、未提交发布。owner=本对话root。

## 配送站进场与共享预算交付（2026-10-23）

- 实现 `destinations[].approach_poses` → 原 Workflow → `delivery_approach_poses` → 原 Bridge 顺序 Nav2 Goal。进场、最终交付与原 task ID 共同保存，重连核对原请求；同 ID 改进场会拒绝。保留旧请求/ledger 与历史评分兼容，`--from-scene` 和显式批次 CLI 均接入。
- 原J100 body-frame出站先完成；之后进场与最终段共享120单调墙秒，Goal接纳/规划/运动、原生成功、两次原`.7`源秒停稳与hold确认均计入，不逐段重置。原360/1000与45秒出站允许时间保持。截止后取消当前原UUID，不派发后段；超时、连续支撑/几何/清理和unknown规则未放宽。
- 状态提供当前段、进场/交付类型、已用/剩余预算；factory报告/oracle绑定完整原生路线、进场列表和共享预算。独立ROS UUID活动/成功及最终真值/同货物/连续支撑/停稳仍分别检查，桥元数据不冒充消费ACK。
- 软件验证：`./fishbot.sh check-feedback` control989、mission209、autonomy61、frontend460，共1719项通过，0skip、0缺依赖。补充from-scene实际CLI/进场提取/预算5项通过（包含重复覆盖，不与1719叠加）。覆盖接纳等待也占预算、超时取消原handle、多段不重置、预算耗尽不派下一段、changed/missing approach/receipt/240秒伪预算不能通过及历史默认兼容。
- 新候选公开prepare真实构建成功：24qpos/22qvel/10ctrl、J100/lidar3d/transport、原Reeds .60、原最终B/A与body-frame出站；`scene/scene-manifest.json`读回后，原factory `--dry-run --order order-b --order order-a`正确输出B进场/A空列表/共用120/360/1000，0ROS初始化/0动作/0ledger。该scene尚未运动，不称运输验收。
- 真实原生只规划两实例合计15组/25请求：第一实例1337、第二4246物理帧全hold，0任务start/0Navigate/0Dock。5组完整路径几何通过，未找到预算合格候选；原direct采样下界128.690秒，含双停稳/加减速余量142.090秒。示例B进场(.9,-2.4,1.1)下界141.189秒、估算155.989秒。其他几何通过候选下界140.342–176.523秒；lethal/206与几何不合格路径均保留。此下界仅针对按所采样路径朝向跟踪、源/墙速率1的假设，不是对所有路线的不可行性证明。
- 原始估算只含一次`.7`源秒余量，现以同一保存路径离线补全pre/post-hold双停稳至1.4秒；单列`time-budget-recalculation.json`，原result未改，不计新仿真或改进成绩。规划、实体扫掠与时间估算通过也不代替实际RPP/完整运输。
- 取证根：`~/.cache/fishbot/factory-line-delivery-20261021/j100-delivery-approach-20261023/`；`native-route-preflight`、`native-route-preflight-south`、`time-budget-recalculation.json`、`final-cleanup.json`。最终独立进程starttime对账零owned存活、9111关闭；FishBot临时sleep inhibitor已释放，其他系统inhibitor未动。无新完整运输，原J100失败与父FishBot2/2保持。
- knowledge_status=already_covered：沿用原Wiki/ROS2 与 FishBot第19/20节的双时钟、原ID、完整几何、线/角速预算和真值隔离；本轮新增的是项目合同与有限候选证据，不重复写知识页。独立知识仓原dirty保持。owner=本对话root。
- 最短接续：在原实体/最终姿态/速度/120秒内先找一条几何与预算均合理的进场路线，再运行原UUID真实跟踪和停稳，最后同轮B→A完整oracle。当前具名JSON明确为未通过候选，不能直接作为默认可交付路线。


## Smac Lattice 本轮交付与原生有限面板（2026-10-23）

- 实现：prepare显式smac-lattice、原语文件复制与网格适配、可选reverse/原生RotationShim；旧NavFn/Hybrid/Reeds默认不变。公开CLI生成24qpos/22qvel/10ctrl场景，独立读回原语相同、运输Shim/内部RPP和前进入站RPP、manifest修复声明。
- 原生缓存：同一个C++程序在原库得到cold blocked=false/warm blocked=true，在补丁overlay得到false/false。实际native库映射已核对。完整package独立构建通过，未替换系统库。原生反例的无inflation警告属于诊断fixture，不修改真实costmap。
- 几何：新增旋转分离轴正下界，保留真实穿障碍与重叠负例。相同旧路径另存projection读回，不覆盖原coarse报告；padding .04候选710个样本、最小.061000m，扣.006210间距界后余量.054791m。原实际车体、local costmap、CM、接触评分不变。
- 只规划共9轮：原库、costmap读回、禁analytic、补丁前进、补丁倒车、低软代价、padding .03、32heading、padding .04。原库路径真实穿障碍；修库后前进208，倒车长路超预算；有正完整几何与名义118.844秒估算的16heading候选才进入空托盘运动。估算不是执行上界，也不是所有路线不可能性证明。

| 原B空托盘 | 原Navigate UUID | 原生终态 | 到原期限耗时 | 末真值误差 m/rad | 带plan非零cmd | 保留窗位移 m |
|---|---|---|---|---|---|---|
| 原倒车RPP | 56a4914f3f2046cbbf0e38ad2b16133f | 5/取消 | 120.070s | .988705/.326931 | 2339 | 2.138122 |
| 原生Shim＋原RPP | 1621b06d421c4356b742dc42d9aec0a6 | 5/取消 | 120.061s | .349670/.880649 | 2173 | 1.649046 |
| 同Shim＋approach .12 | cd5ccbac3afe46c2ac587b15bd316bea | 5/取消 | 120.071s | .226143/1.003603 | 2157 | 1.636800 |

三轮原生参数服务读回均保留载货max_velocity=.03/0/.05、max_accel=.025/0/.05及原减速度；最后两轮实际Shim/内部RPP和加载overlay已读回。末累计车/臂禁碰均0，原UUID取消、hold=true及.7源秒连续静止确认后才清理。三轮不是严格同随机轨迹的性能A/B，不能用末误差排名宣称改进通过。软代价、padding .04、Shim与approach .12均未提升为默认业务参数。

**记录覆盖限制**：实时monitor有界为20000条；退出保留的三轮物理源窗分别35.42–138.72、33.16–136.74、35.16–138.54秒，未保留各轮所有初始帧。表中位移相对于各自第一条保留真值，不能称从Goal起点的完整路程；仍足以证明实际非零运动。窗口内最大源间隙分别.92/1.04/.88秒；不宣称无损采样。最终累计禁碰和原Goal结果各自保留，桥接转发不冒充控制器逐帧消费ACK，也不据此宣称两阶段GID切换已证。

验证：最新39项相关检查17.015秒通过；完整check-feedback为control997/mission209/autonomy61/frontend460，共1727项，零skip/缺依赖/失败。保留Browserslist数据库陈旧提示，未为此升级依赖。原生build、两版同程序反例、公开prepare和独立YAML/manifest读回通过；源码改动期间未重启其他任务。全部12个owned上下文/9111已关闭，未操作实车或执行固件发布。

原始输出根：`~/.cache/fishbot/factory-line-delivery-20261021/j100-lattice-20261023/`。聚合`native-results-summary.json`；原生`native-*/result.json`、3份`independent-ros.jsonl`保留窗；几何`geometry-projection-summary.json`；反例`cache-probe-{original,fixed}.log`；公开入口`public-cli-readback.json`；完整回归`feedback-final.log`。运行时日志不入Git。

最短接续：先读`native-shim-approach/result.json`和对应路径/ROS保留窗，用已接入的原生planner/controller边界解决路线跟踪的转向、反向切换与时间余量；不要再发送同点Goal，不延长原120/360/1000、不缩车、不关闭碰撞。复现准备命令见`docs/FACTORY_DELIVERY.md`的差速Lattice节，原B探针脚本在同缓存`native-shim-approach.py`，使用domain141/9111，启动前核对实际占用。实际原B到达及清理通过后，再同轮B→A完整原物理评分；当前均pending，owner=本对话root，不跨对话协作。

knowledge_status=updated(local)：已修订原`Wiki/ROS2 与 FishBot.md`第19节的AABB/旋转分离轴下界，并补原生Lattice冷/热边缓存、网格匹配与原地动作消费经验；`Wiki/开发知识入口.md`补触发入口。逐段rg读回已核对，保留知识仓原dirty，本轮未提交/推送知识仓。源码交付提交与远端读回由本节后续Git收尾记录对应。


## J100当前接续：同速失败保留，业务速度待选择
2026-10-23 同速曲率联动＋关闭软代价减速探针，原UUID3c1064ccbc0e45de804fac59698be074在120.054墙秒取消5，末26.226cm/.870140rad；原完整B/A未启动。全起点窗口保留，末hold与quiet、owned/9111清理通过；monitor.close触发executor线程InvalidHandle，作为清理诊断保留，不把调用退出0解释成验收。

原生0.40m/2cm/16向官方差速生成器得到96条原语；仅规划UUID574eb20ad28d4b7d97aeb69beb5283d2/status4、完整几何余量+.055366m且IsPathValid=true，但路径3.252143m/3换向，含余量154.022墙秒，未发运动。917个物理样本全hold，owned已清理。更小半径不保证更短可行路线。

用户速度选择pending，owner=本对话root。已准备独立j100-fast-probe-manifest.json与j100-fast-full-manifest.json（.06m/s/.10rad/s、原加减速、原所有评分/期限），prepared_not_dispatched，不在答复前执行提速。原完整新scene已prepare为原spawn/A/B/occupied/J100/lidar3d/Omni/Lattice；不是旧probe出生点。最短接续：允许后先native-j100-fast-probe.py原B实走，通过再原cooperation_factory.py run绑定j100-fast-full-manifest.json、order-b/order-a，完整oracle与原360/1000；不拼接旧成功。证据根仍为j100-transport-20261023，未覆盖原件。knowledge_status=already_covered（FishBot19/20双时钟与原生/物理分层）。


## 用户确认独立速度后：原B实走通过，完整B→A在途
用户已确认.06m/s/.10rad/s；原加减速.025m/s²/.05rad/s²、完整车体/碰撞/CM、连续载货与4cm/.05rad、120/360/1000均保持。原B探针UUID3a11d31425024d6e81ea7e71db20da65原生4，86.150713墙秒，独立真值2.0793cm/.009458rad、连续quiet .86源秒。5151个物理样本累计车/臂禁碰均0，起点窗口保留；已确认末hold、owned/9111清理。原记录源采样仍有.14–.84s缺口（含只规划预检），不称无损记录。原生速度上限、RPP/.6m曲率调速、.01最低速度及patched库路径已读回。

完整运行已启动：同一cooperation_factory.py原订单B→A，输出j100-transport-20261023/full-b-a，原初态(0,-2,0)，原occupied实体障碍。复用原Workflow/DockRobot/SO101/oracle，无policy-config，无跨对话协作。当前仅短段通过，完整抓放/运输与A仍在途；不以标签或HTTP状态代替原物理评分。knowledge_status=already_covered，收尾按最终结果更新。


## 独立速度首轮完整失败与载货重放（不计两单成功）
- run81d05dac-87a0-4207-8dfd-7e3ecbcbb038，B taska3deb85b-db0c-432e-94ed-a8c5b07460d0，191.978墙秒。原入站77f3741552e24fb3a224c107a402fc7d、Dock7550b9ebf894489fb32a4b31fefeeb7e、原body出站8e2e7aa7f47e456c89e846f5d61d7199均4；载货41a01cf11f8f4d62805cb8f1606b30da在8.084秒正确取消5。原K true，连续支撑false、完整交付false；A未派发。selected_text起止一致、owned/observer/9111清理通过。
- 原记录182.46/184.58源秒floor_contact=false，货物相对托盘仍居中，z=.010017/.010013m；非几何越界，真实floor force=0。仅缺触两个观测也保留原失败，不去抖、不放宽门槛。
- 从记录qpos/qvel/ctrl重放、1s held settle（solver warmstart未存，非逐比特回放），原模型/碰撞/执行器保持。.10纯转与.06/.10弧线各800个50Hz样本失支撑4次、500Hz各30断触；.05正负纯转、.06/.05正负弧线各800个50Hz与8000个500Hz均0断触、车臂禁碰0。只支持该初态有限面板，不宣称泛化。
- 下一候选保留用户.06/.10上限、原加减速，实际载货turn目标.05、RPP调速半径1.2m、最低调速.005，使转弯稳定并提高直线速度。先用记录车/货位姿做载货短段；其初态不是完整抓放验收。首个keyframe载入因MuJoCo replicate的qpos尺寸拒绝，0物理/Goal，保留失败；b2改为记录车/货初始位姿、速度/轮编码器归零，编译后原质量/惯量/摩擦/接触/执行器参数逐项相同。原完整scene与失败原件未修改。
- 证据根j100-transport-20261023/{full-b-a,loaded-turn-replay-result.json,loaded-turn-005-replay-result.json,native-loaded-turn-probe,native-loaded-turn-probe-b2}；owner=本对话root，knowledge_status=already_covered，待最终闭环后回写新增稳载经验。
