# F1 Findings

## 2026-10-24：完整e未复现短测；显式原生运输候选

- 公开prepare的原spawn/A/B/occupied与短测控制合同读回一致，但完整e仍在1.35进场120.039秒取消，K与连续货物保持通过、A未执行。重建装货初态不包含solver warmstart与AMCL滤波历史，不把短测105.794秒外推为完整业务。原独立记录完整，owned清理、源起止均通过。
- 真实1.3.13 RPP函数对e实录路径的独立C++探针表明：普通carrot在90秒附近触零阈值，但当前use_fixed_curvature_lookahead=.3的活动曲率非零；后续普通carrot方向翻转。修改C++零阈值没有获证据支持，未实施。原件在私有rpp-recorded-probe/，不把观察关联宣称完整因果。
- MPPI DiffDrive候选在有限载货初态未保持货物；原生Graceful可完成两UUID，.055最终停稳超120秒，.060/.12实际118.615秒、2.215cm/.00218rad并保持5709个采样检查。增角速.065触载货失败，降速范围.08首段超时。失败全保留，不晋级；选.060/.12继续完整原factory，仍未宣称稳定。
- 新薄适配只选择已有FollowPath YAML并复制输入；不新建控制实现、owner或评分器。其它控制器不得继承未消费的RPP速度ACK字段，原共享progress与载货smoother事务保持。默认RPP与人工二改可继续使用，不以来源hash锁住内容。
- 证据根仍为~/.local/share/fishbot/cloud-jobs/kaggle-20261024/；local-full-b-a-e、local-loaded-e-via135-{mppi-a,graceful-a,graceful060-a,graceful065-a,graceful060-slow008-a}分别保留。新完整结果回写本计划，不拼接各轮成功。

## Kaggle计算瓶颈有限对照（2026-10-24）

- v6是真实原任务失败，非部署失败：KDL/ConsoleBridge等补齐后原生构建与source-clock通过；原任务360墙秒仅约146源秒，B真实抓放/home成立而尚无载货Nav，A未运行。loop包装step77046次总279.375s，publish7704次92.423s；前者包含控制/接触/静止检查，不冒称纯mj_step。
- 合作场景复制的laser/laser_ray原生rangefinder扩展为360个，每500Hz物理步计算；实际合作驱动从不读该测距数组。/scan来自Physics.scan的10Hz mj_multiRay，3D来自NativeCloudQuery的16×360/10Hz，原生3个IMU仍消费sensordata。省略旧声明不等于降低被使用的传感器分辨率。
- compute v2五个v6观测初态（start/docked/lifting/released/loaded_home），各200步的全部记录误差0；scan/点云/raw_points/命中ID相同，质量/惯量/接触/执行器/求解器参数相同。原生单步范围1.023–2.138ms→.198–.274ms。fixture没有solver warmstart，不能称逐比特现场续跑、泛化等价或配送成功。
- 对照仍受云VM分配与采样范围限制。后续保留默认场景，显式配置省略、清单可追溯；实际ROS held容量另验，再跑原始任务。source overlay由Kaggle代码版本保存原文，输入v2仍明确634c6e6；不引入内容哈希执行锁。
- 取证根~/.local/share/fishbot/cloud-jobs/kaggle-20261024/{f1-output-v6,compute-output-v2}。全输出下载曾连接超时，已完整读回关键result/score/任务账本/世界XML/195MB observer（0坏行）/loop timing，不能把下载失败归为机器人失败。

## 载货路线与已验证入站（2026-10-24）

原NavFn入站先向车后，前进RPP原地转向受前方46mm余量限制；显式原生Shim＋反向RPP在同原实体场景24.119秒完成短停靠。--staging-reversing默认关闭，保持transport/GoalChecker/速度与世界；16项prepare通过。该分项有理想plant guard介入，不称纯观测或RGB精度。

完整d已完成真实抓放、home、出站和连续运输，但(.95,-2,0)在共享120秒前未收敛。原B直达的path约2.656m/累计偏航4.429rad，6.18mm最小采样净距；跟踪到末y偏差约56mm后超时。.065曲率候选虽然更快，却触原cargo_retained=false，不能用它换成绩。原1Hz重规划确实发布61个新plan但仍超时，不能称重规划修复了配送。

只规划有限面板的经(1.35,-2,0)第一段3.201m/累计偏航π、净距66.0mm，第二段.65m纯倒车；完整加密扫掠和spacing bound均通过。经1.70的名义下界90.424秒，经1.35为89.554秒；均不代替实际预算。经1.35实际双原UUID4/105.794秒/15.43mm/.00543rad与原载货保持、原停稳/restore/清理通过，支持选择宽处完成姿态再倒入原B，不能泛化所有路径或拼接成完整K。

官方Nav2 1.3.13 IsPathValid服务从近点检查原路径代价/足迹；它不证明当前车辆可按原姿态连接路径。原stock树周期1Hz；这只是本次对照的源码依据，不是本轮通过结论。来源：https://raw.githubusercontent.com/ros-navigation/navigation2/1.3.13/nav2_planner/src/planner_server.cpp ；https://raw.githubusercontent.com/ros-navigation/navigation2/1.3.13/nav2_bt_navigator/behavior_trees/navigate_to_pose_w_replanning_and_recovery.xml 。桥与观察记录不冒充控制器逐帧消费ACK，GID缺失也未被伪装为实例绑定证明。

## 当前入站控制证据（2026-10-24）

本机完整b/c首个NavFn路径相同，前12点向车后负X，初始yaw0；StagingPath仍为前进RPP/rotate_to_heading=true，与载货FollowPath的反向＋原生Shim不同。初态车前沿x=.244m，实体占用障碍近沿x=.29m，仅约.046m余量；旋转扩大扫掠。c记录明确collision ahead，几乎没有平移。只支持测试倒退原生控制组合，不用关闭碰撞或缩足迹处理。b曾经恢复后到站，不能声称现配置绝对无法入站。c已清理，桥析构publish/context退出诊断单列。

## Kaggle接续（2026-10-24）

- v4/v5实际错误区分运行依赖与构建SDK：liborocos-kdl1.5存在不代表orocos_kdlConfig.cmake存在，LTTng运行库不含开发链接名，class_loader实际CMake导出还要求console_bridge。仅递归package.xml公开字段未完全覆盖，先前“依赖已核对”不能外推编译通过。原生CMake查询两安装包+OMPL，trace与cache文件通过dpkg归属找到Console Bridge/OpenSSL与Boost组件；3.12配置返回0，仍不是云端编译或运动证据。查询、旧默认3.11记录及所有云失败保留在私有交接根。
- pip colcon-common-extensions0.3.0不含override-check插件；--allow-overriding由独立colcon-override-check提供。本机0.0.1与源码参数定义已核对，显式补依赖，保留原覆写声明。空隔离目录只证明原命令可解析，不是C++编译、控制器计算或配送验收。
- 云端v2确认原archives解包通过，但apt缺python3-colcon-common-extensions。官方文档说明该元包经ROS/packagecloud仓分发，并支持venv pip；本轮采用本机版本的pip colcon工具链，不绕过ROS仓TLS错误或重置系统Python。真实错误143字节原log已通过官方SDK的DownloadKernelOutput(file_path)读回。
- Kaggle CLI output的file-pattern仅过滤下载，仍循环列举整个输出树。此前把源码/runtime/venv放working会增加至少数千文件，未来完整venv更大；临时依赖树转/tmp，scene及原任务证据继续持久化。网络ConnectTimeout也真实出现，二者不能混成单一原因；本机取证进程可限定单次连接超时，不改账号或全局网络。新失败日志尾部输出保留原状态，低层异常不替代物理裁决。
- 用户已选择CLI账号`muqiaoqiao`；官方access-token introspection与私有前检作业属该账号。Chrome的`muqiao147`不是该私有数据集的访问凭据，不据其404判断CLI资源不存在，也不切换账号。
- 真实前检v1完成，不是本机模拟输出：Ubuntu24.04/glibc2.39可承载本机Jazzy库，默认Python却为3.13。薄适配另装3.12、固定ROS CLI及colcon解释器、隔离PYTHONPATH；不替换Kaggle系统Python。Smac 1.3.13原CMake明确依赖OMPL开发包。
- Kaggle CLI可在无效dataset_sources被剔除后仍返回kernel推送成功；本次完整v1实际在输入检查失败，零ROS动作，不能算配送试验。补异常报告拼写并用真实except路径故障注入确认保留原RuntimeError与false评分。
- 原运行包创建Ok后持续403且mine无记录；一个同账号、同other许可证且带description的小私有数据集实际ready。此对照只排除普遍账号创建失败，尚不能把原包问题唯一归因于description或文件。保持私有、原许可证，不反复创建公共副本。
- 同slug补description重试仍403；四个原gzip/tar包加19字节格式头后ready，文件列表读回七文件，库包未自动展开。官方datasets文档明确会自动解压archives；ROS包含40533项和532个符号链接，平台摄取不宜代替原tarfile解包。保留原包与两次失败，不把文件封装与平台时序的联合变化写成唯一根因。标准流式tarfile小样本往返已保留内容、执行权限与符号链接。
- 原factory的protected_snapshot强依赖本机user systemd，云端不存在该服务。增加显式isolated-runtime只选择空的本机保护对象，原本机默认和自选units保持；同时记录作用域，原任务/native/连续quiet/owned进程与端口清理仍硬性参与原评分。25项相关factory检查通过，不伪造107/114快照。
- 历史`~/.cache/fishbot/factory-line-delivery-20261021/`与planning venv已不可用。此次从a8fe76f核心源码、现存Jazzy/vendor runtime、SO101实际工作源码与模型重建，不声明旧输入完整复现。SO101只打包8模块依赖闭包及原模型，不上传9.6GB实验历史。

## 最新已核实结论

- 计算余量恢复不能只看启动前一次load：CPU压力从约31%降到3%后，同配置`recover`进入实际跟踪，但中途频率约1GHz；实测物理包装步均值6.682ms、50Hz发布19.402ms。原UUID8ec8b63099a9425aa8c1508e1e8532ff取消5，出现1个原载货失败样本；只有hold确认，没有连续quiet通过。资源波动与支撑失败分别保留，未用猜测给失败去抖，也不宣布算法通过。

- J100源码9bf99c7后的同配置实际复跑仍未交付：原入口UUID00f5de16108f4733945ca991afa9bd9a在120.063墙秒取消，第二段未发。完整抓放两单未重跑；连续支撑、禁碰和清理通过不抵消路线未到达。原生规划成功、带plan的非零cmd与真实位移各自留证，不再从静止Goal推断消费。
- 最新静止交替面板在相同原物理/16×360雷达/50Hz观测下得到.263–.305倍实时；原生步同线程CPU3.009–3.173ms，接近其墙钟耗时且已超过2ms步预算。缩短Python切换间隔没有可重复收益。支持当前计算能力不足，不支持把旧回合都归因GIL；不采用该调参，不改步长、碰撞、门槛或其他运行任务。
- 最新短路线复用的仅是逐姿态相同、场景/资产/检查器mtime未变且余量为正的静态证书；当前ComputePathToPose的UUID/status独立记录。证书命中不复用导航终态，也不构成完整新一轮几何复验。变化时回到原完整扫掠，无哈希执行锁。
- `capacity-profile`是有剖析开销的单次观测，不与无剖析速度排名。此前GIL ABA恢复默认也实时、RR10改善仍不足，均保留为阴性/不确定证据。最新sim销毁节点阶段的KeyboardInterrupt和原.24s源间隙仍保留，不用owned清理成功抹掉诊断异常。

2026-10-23新增原生计时与执行边界：Nav2 1.3.13 velocity_smoother用墙钟timer和固定`accel/frequency`增量。半速`/clock`实测原配置源时间加速度约为参数两倍；显式ROS时钟补丁恢复原.025/.05，并在暂停时钟时停止加速。默认false，动态频率调整保留所选时钟。公开零运动入口`tools/tests/verify_nav2_smoothing_clock.py`在domain142通过；全部速度话题使用私有重映射，没有导航或执行器发布。原生库不改系统安装，只在独立overlay使用。

不能据此宣布载货修复：源时钟.06弧线仍有1帧断触，联动加速度.06仍有1帧；更慢.05远侧路线支撑通过但共享120秒不足。上侧(.75/-1.5)、(.9/-1.5)被原`baffle_right`占用，原生206，不绕过。原始失败和UUID保存在`~/.cache/fishbot/factory-line-delivery-20261021/j100-transport-20261023/`。

循环性能不能脱离CPU状态比较：balanced窗口曾读到约.8GHz，AC在线且电池100%；现成`powerprofilesctl launch --profile performance`按进程持有并自动恢复balanced，不改温控或其他任务。固定性能窗口中显式队列接收令15秒零运动推进率从.89173到1.000，主线程应用均值.00362ms，原spin均值.44686ms；两者原生physics耗时相近，均无清理错误。该有限对照不代替载货或长测验收。
2026-10-23 已新增有序配送站进场合同和出站后的共用120墙秒。只规划预检15组、25个原生请求：原direct的采样路径时间下界128.690秒；四组新增进场的整路几何通过，下界140.342至176.523秒，均不满足原预算。此为指定采样路径、跟踪朝向和源/墙速率1假设下的估算，不证明所有路线不可能，也不证明RPP实际执行。新完整运输未启动；父FishBot2/2与原J100失败保持。

2026-10-22源码b158b65在原占用场景同轮B→A完整物理2/2，原ROS记录独立回算及109项相关检查通过。有效组合为Omni参考点模型、运输Smac显式半径.10m、两Python进程异步发布及验收期间临时阻止sleep；原控制/碰撞/到达与预算保持。这是有限配置组合结果，不唯一分解各改动因果，也不覆盖P8、RGB或via。后文阶段性失败按原证据保留，完整参数/ID与缺口见progress。

## 已复用
- 原 workflow 已支持任意 N 个 batch 和每批 delivery_pose；只需让新场景的订单数据进入原初始化入口。
- 原 prepare 在编译碰撞体后生成激光切片和完整碰撞图。实体通道占用在编译前加入，可复用同一地图生成链。
- 原独立 oracle 区分执行终态、物理交接/运输与目标停车，不新增评分实现。

## P8历史边界
P8旧记录保留39项运行文本观测和所有A–J失败：当时J的新frame进入回调而缓存提交受控制锁阻塞，H存在未获得callback调度的间隙。本轮F1成功不证明P8全部组合已修复；后续回原P8计划与实际实例验收，不能用本轮成绩覆盖旧失败。

ARIAC2025 仅作订单、工位与交付评价语义参照。官方来源已由场景worker打开核实：[ARIAC仓库](https://github.com/usnistgov/ARIAC)、[2025文档](https://pages.nist.gov/ARIAC_docs/en/stable/index.html)、[任务场景](https://pages.nist.gov/ARIAC_docs/en/main/pages/scenario.html)。当前一物体在两订单之间显式 reset；不宣称同回合多货物库存、真实产线 PLC 签收或跨引擎统一物理。

## 实体通道与缓存修复
- 占用箱 world 中心(-.45,-2.10,.25)m，完整尺寸(.18,.30,.50)m；同步写入 world、arm-contact 与 rig，arm-local 坐标按原 station_offset 平移。原 prepare 自动生成两地图，无第二套栅格化。
- 四个静态 MuJoCo3.3.7 场景（FishBot/J100×open/occupied）由场景 worker 编译测试；两图占用中心 open254/occupied0、原状态维数与物理参数保持。完整足迹直线受阻但端点/出站不占，有几何连通路径。这不是 Nav2 可达或实际配送证明。
- 缓存修复209项相关回归通过，P8原生K在140/9110独占运行；F1将在其清理后串行启动，不让同机两物理运行争用。

## 评测审查修正
- 原 native_cleanup_known 不能单独授权关闭运行中的整车臂任务；F1薄层先核同任务/回合明确终态，再复用原native/quiet证明。不修改P8运行源。
- 物理裁决与预算分开：原score通过不代表360秒内完成。每单finite elapsed≤360和整轮≤1000另外进入整体验收，缺时长不计通过。1000是验收预算，不冒充包含阻塞评分/清理的硬退出时刻。

## 当前修正
上述 v1 箱体与运行状态是历史记录。v1 原几何预检失败且零运动；当前 v2 箱体中心(.35,-2.10,.25)、完整尺寸(.12,.30,.50)。独立实跑开放场景2/2、占用场景1/2物理通过；B原生成功但物理位置4.3478cm，保持false。不能把Workflow或Nav2终态当作物理通过。短缓存锁与清理诊断已验收实现，J100的低速小转向响应不足仍独立校准中。


旧prepared不是当前实现：occupied-v2的生成YAML仍checker stateful=true且RPP未显式false；新prepare已读回双false、原native .015/.035门槛。direct/via必须共用新prepared，不能把旧YAML和新代码组合冒充当前配置。同一已生成输入可跨两个资源窗口独立启动，前提运行源码、场景、订单和原评分不变；新run/UUID分开，时段负载差异不得当策略效果。


实际派生manifest需要贯通生产器：首direct零订单启动失败揭示cooperation_sim.source_identity固定从world旁读scene-manifest，launch却只给bridge传derived路径。模拟器实际仍有物理帧，但bridge按现有manifest身份合同拒收，因此无ready。薄修复显式--manifest→Physics→source_identity并由launch共传，两端同源；保留无新参数的默认。原result保留unknown/未评分及独立owned清理回执，不当运输失败样本或成功成绩。


失败任务的原oracle可合法返回final_true_pose_error=None；汇总器必须保留缺失，而不是调用.get导致报告与finally二次失败。最小or{}只让读取可用，输出仍None、原false评分不变。实际fixed direct入站超时揭示该缺口，22项回归覆盖。原内存run_id/源码end快照丢失时，只读恢复摘要应明确不可恢复，不伪造ID或起止一致；同task/episode/native UUID仍可独立验收失败与清理。

fixed direct末段真实cmd线速度0而角速度正负交替，map 15mm圈30源秒跨110次；状态锁成对关闭可能将入站也带入位置/朝向切换。派生身份修复已通过真实ROS接纳，但不是完整配送已修复。需要阶段控制合同整改，再冻结同源direct/via；不把该入站失败当两种路线的对照。


阶段整改采用原生配置实例而非新控制器：Nav2 1.3.13 [FollowPathAction](https://raw.githubusercontent.com/ros-navigation/navigation2/1.3.13/nav2_behavior_tree/plugins/action/follow_path_action.cpp)确实将controller_id/goal_checker_id写入原action；[NavigateToPoseNavigator](https://raw.githubusercontent.com/ros-navigation/navigation2/1.3.13/nav2_bt_navigator/src/navigators/navigate_to_pose.cpp)在goalReceived读取behavior_tree，不允许活动目标用不同树直接抢占。现桥原目标终态后才下一动作，故可复用阶段树而无需额外owner/重发机制。软件XML绑定不等于已证原生插件消费，多实例生命周期、连续新回合和完整物理回合仍待验。

2026-10-22静止阶段实跑补充：Nav2 controller_server先处理goal更新、costmap freshness并调用`isGoalReached()`，只有未到达才进入`computeAndPublishVelocity()`；RPP的`/received_global_plan`发布位于`computeVelocityCommands()`内部。原e两个目标均取当前AMCL位姿，日志连续显示`Received a goal`和`Reached the goal!`，中间没有控制计算。因此零路径消息不能解释成DDS QoS失配，也不能证明StagingPath或FollowPath消费了路径。BestEffort订阅通常可接收Reliable/Volatile发布；若要观察阶段控制器，必须使用会进入控制循环且产生至少一次控制计算的路径/目标，并同时保存消息、endpoint QoS和阶段时序，不能靠只改订阅QoS把静止测试变成成功。

同一e日志的17条旧时戳车体命令拒绝分布在两个静止Goal结束及清理周围，没有造成样本离开`car_hold`。它记录的是该旧命令被物理侧拒绝，不证明新鲜命令可被接纳，也不覆盖运动中的命令时效、导航或交付验收。

2026-10-22 0.25m两阶段运动探针补充：RPP的`/received_global_plan`发布端在DDS发现中确有两个原生`controller_server` endpoint；rclpy普通消息回调未暴露`publisher_gid`，所以该字段只能作诊断，不能把“两阶段消息GID不相交”设为通过条件。Stage1收到364份计划、365条控制命令且原Goal4，证明该请求窗口出现了控制计算；具体RPP实例的独立发布者归属仍缺失。Stage1物理终点误差0.0940874m仍失败。Stage2从该偏差状态进入RPP碰撞重试与恢复，原Goal5；旧探针超时后未复制该阶段消息，空数组不能证明没有计算。实体碰撞几何、软膨胀代价与RPP预测足迹是不同判据；缺少实际局部轨迹/costmap逐点代价证据，不能独占根因或换成开阔场景冒充原厂区路径通过。

探针RCL上下文退出后，清理阶段的hold由真实physics源确认；这与launch/端口回收分开验收。阶段探针本身不改控制器、收敛或安全门槛。下一软件单位宜先只读提取Stage2的计划、局部costmap、RPP候选carrot/碰撞采样，并检查是否由终点收敛与inflation共同造成；任何修复须在新prepare、原场景和原评分下独立验收。

### 本轮撤回的解释与已验证缺陷

同版[InflationLayer](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_costmap_2d/include/nav2_costmap_2d/inflation_layer.hpp)提供分级代价；[RPP CollisionChecker](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_regulated_pure_pursuit_controller/src/collision_checker.cpp)按预测足迹及致命代价判断。不能从“目标中心距占用0.29m，膨胀半径0.3m”推断硬碰撞，也不能据此断言0.044m/s由膨胀层导致；[接近目标减速](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_regulated_pure_pursuit_controller/include/nav2_regulated_pure_pursuit_controller/regulation_functions.hpp)等机制同样影响速度。本次明确撤回此前这两条因果解释，原运动失败不改判。

旧探针在`get_result`成功返回之后才复制阶段消息。Stage2超时会跳过复制，故原result中的消息数量未知；不能再写“未产生计划/控制命令”。新增`record_phase_wait`在finally保存，测试实际触发其TimeoutError分支，核对已保存消息、原计数与未知终态。source/wall预算分开，缺GID保持unknown；每帧删除重复manifest，保留episode身份与单份完整来源。

静态新fixture的首轮预检失败定位到MuJoCo3.3.7旧箱体查询：车姿态(0,-2,2.2938613026)，托盘中心(.0185194,-1.9303076,.162)，障碍中心(.35,-2.1,.25)，两世界AABB沿X分离，`mj_geomDistance(...,.2)`却返回-.506279389m。独立双箱最小模型复现其矛盾。公共几何查询现对严格分离的box-box返回保守AABB下界，AABB重叠仍调用原生查询；真实重叠负例和原声明路线的开放/占用检查通过。不改变nativeccd、接触、几何尺寸或原物理评分，不将该静态查询缺陷倒推为旧RPP失败根因。

2026-10-22固定朝向probe check9fe1577a-54f3-4583-8a54-44adc61c133d：Stage1计划331/命令332，Stage2计划1411/命令1411；前者原UUID4但真值XY.066540481m，后者末端转向超时取消原UUID5。日志未出现collision ahead、Failed to make progress或Controller patience exceeded，不能将本轮归为碰撞拒绝。Stage1首次AMCL进入15mm圈时yaw误差2.601rad，结束时AMCL XY6.227cm/真值6.654cm；Stage2进入位置圈后多次角速度反向，末yaw仍2.745rad。此为收敛现象证据，不独占根因。

`EncoderOdometry`已从真实编译轮轴推导偏置并转换回foot原点，不能把忽略轮轴偏置当作漏改。为隔离控制消费，新增显式aligned目标朝向，不改固定目标或配送验收。系统已安装rclcpp28.1.22的MessageInfo暴露原生rmw publisher_gid，而本地rclpy包装层没有；故采用约60行只读订阅器，不改RPP、不造控制器。其消息按同机CLOCK_MONOTONIC对齐原accepted窗口，必须归属已发现的controller_server endpoint，overflow/未知来源不充作完成。

aligned原生checkfa4ebc93：C++实际消息GID分别为010fa54e488cb39f0000000000006c03与010fa54e488cb39f0000000000006703，与运行中的两个controller_server endpoint逐项一致；331/193条在原accepted时间窗内、两阶段独占且不同。Python计划数331/195，默认阶段额外2条落在C++accepted窗外，分开记录不强行凑齐。每阶段均有实际平移、非零控制、原外层及FollowPath子Goal成功和原物理误差通过；控制器消费/切换缺口已补齐，不能据此称原F1配送已通过。

fixed首阶段在源18.5s以后命令v始终0，轮轴真值从(-.2118484,-1.9716661)到(-.2111766,-1.9692849)，只漂2.47mm；foot原点则随转向绕轮轴移动。该读回支持坐标点转向位移的几何解释，但18.5s的AMCL/真值还存在平移差，不能把全6.65cm终误差独占归为轮轴或忽略定位误差。已有原里程计补偿与物理碰撞保持。

原staged occupied direct run c15891fe-7f44-48de-93ab-935b4b98c050：两单入站各使用staging树，原入站Nav与Dock均4，第一单完整通过；第二单装货/交接/原K仍通过，但载货目标(.7,-2,0)原UUID39cdc2aefe75407f82aa008a13418693在120.06墙秒取消5。最后30墙秒，862物理样本、源330.20–347.42，hold全部false、禁碰0；XY误差.013092–.022339m，abs yaw1.301287–1.787098rad，真实yawrate-.744188至+.704035。601条原cmd的v全0，w±.8，角速度符号变21次；54个HTTP map样本跨15mm圈20次，不能把该HTTP位姿当同步控制分支ACK。日志没有collision ahead/progress/patience错误，本轮不支持安全层锁住或没有Goal消费的解释，也尚不能独占根因。

此轮源码selected_text起止一致、运行681墙秒内、两任务均360内；A完整物理通过，B最终位置1.85cm但yaw1.57329rad失败。原完整oracle的native_goal_consumption_ack_claimed=false保持；先前两阶段DDS证明只能覆盖对应探针，不能转写为这两订单每个控制循环的回执。路线策略direct确实调用并返回None，无中转；via仍未跑，不形成策略优劣结论。

当前源planner为NavfnPlanner，配置没有显式use_final_approach_orientation；RPP use_rotate_to_heading=true、stateful=false。同版RPP源码先按carrot到达距离选择目标朝向，否则按carrot方向选择路径转向。RotationShim的末端分支也以XY位置检查为入口，暂不叠加另一层转向。已安装同版SmacPlannerHybrid，官方实现将起终点yaw加入搜索，并使用原完整costmap足迹；选择其作为可选路径候选，控制/评分不改。来源：https://raw.githubusercontent.com/ros-navigation/navigation2/1.3.13/nav2_regulated_pure_pursuit_controller/src/regulated_pure_pursuit_controller.cpp 及 nav2_smac_planner/src/smac_planner_hybrid.cpp。当前只完成候选接线，尚未有新原生结果。

全Smac check2604eaa4-3aef-4bc3-bf20-6d115323673c：原两个Goal均4，stage XY.06730769m/yaw.05267926rad失败，default XY.03825184m/yaw.02458898rad通过；整体false、errors空不等于业务通过。原生planner参数匹配，运行前后不变；GID切换已观察，69.224墙秒且完整清理。日志曾无法规划短U形再由原BT spin恢复，不能称姿态规划全面更优。基于默认运输段通过、原完整任务入站已成功的证据，下一候选仅运输换Smac，入站保留NavFn；保留该试验原件与源码a076e86。

分阶段Smac短试验check686917c3-21ee-40d9-9b2c-cecfb73c8b04仍failed：两原Nav4，stage .06634146m/.03468895rad、default .05913391m/.02441632rad；双planner/原RPP参数前后不变，完整清理。default同末段AMCL近邻源44.3与真值44.22，XY差.0719843m，源龄差.08s；成功到hold后真实位移.1258mm，不能把5.91cm归为刹车滑移。离线模型重建扫描的近似likelihood在真值附近优于该估计，但非原生AMCL重放，保留这个边界。

原生AMCL 1.3.13均值复现发现可确定的模型不匹配：实际foot在轮轴前2cm，转向会有每步<1cm的侧向圆弧；DifferentialMotionModel在此分支rot1=0，半圈100步的期望位移(-.04,0)被预测为(.0006283,.0399951)，误差.0570111m。直接调用已安装lib的OmniMotionModel得几何期望（误差1.72e-19）；偏置0及25cm直线对照均正确。这不是“忽略轮轴的里程计”旧猜测：原EncoderOdometry已正确转换，问题在下游提议模型如何解释该参考点的增量。它证明均值合同缺陷，仍不独占运行中的全部误差或证明整滤波已修复。
# 2026-10-22 回合切换竞态

本轮已得到有限有效结果：Smac显式.10m＋Omni参考点模型＋两Python进程异步发布，在原占用场景同轮B→A完整物理2/2；B末3.259cm/.02692rad，A末2.531cm/.01719rad，原UUID均4、全部抓放/交接/运输与预算保持。实际原生planner参数读回.10m、DUBIN、近似目标容差0；选定源码起止一致。它验证这一配置组合覆盖本轮两个目标，不唯一分解各修复的因果，也不证明跨硬件、纯视觉或生产稳定性。

独立原始ROS记录重算两单真值误差与原score吻合（<1e-6），2→4终态、留盘及清理一致；完整落盘但physics各缺2序号，采样不是无损。原NavFn＋Omni的B朝向失败、.20m Smac的B无路、桥同步发布阻塞和宿主真实休眠失败都保留，不能被2/2覆盖。后续经验采用“回合切换/源交付/规划可达/末段跟踪/物理任务”分层，不再把任一诊断说成全部根因。

NavFn＋Omni完整B仍在末端约90°振荡、120秒取消，说明AMCL均值修正不能独占解释原问题。路径最后pose的quaternion为目标朝向，不等于实际末段的切线朝向：原NavFn最后段2.356rad，易使RPP从路径转向切换到大角度目标转向。进一步只规划对照对Smac原生最小半径.20/.10/.05逐项设置并读回，.20仍6/207，.10/.05都4/0、约.101秒。选.10m时86点，末段-.1433rad、原终点误差<.2µm；并未改变实体、速度、碰撞或到达门槛。它仍是配置候选，完整跟踪/交接待验。

保持唤醒后排除了本轮休眠及反馈失效，原生B停在全局规划：HeadingAware多次no valid path，最终Nav6/208；旋转来自原恢复树，不是末端90°切换。只规划对照复用同实例两个已装原生插件：起点取原B前最后独立AMCL（-1.796168,-1.819135,yaw.001078），目标(.7,-2,0)。Smac6/207、4.351秒无路径；NavFn4/0、.18282秒342点，长度3.43764m且精确终点。该对照成本图是原spawn新实例，不是原载货B动态成本图重放；只证明该请求在这份原成本图有NavFn路径，不外推完整运输。

Smac是在排查AMCL均值前加入的假设候选，其B完整任务未验收；不因库更复杂而继续叠加。回到原NavFn和原双树，只保留已复现的Omni参考点修正、已验收重置修复及独立异步发布开关；Nav2参数与原staged父输入相比只变AMCL模型字段。下一B→A完整试验明确不是同顺序的单因素对照。

异步试验run5a9e2528-eee6-46ae-a0cb-2fb735efbd06（353701c）原生1/2：A2.444cm/.01697rad通过，B在arm_transport共享物理中断，未派发载货Nav。源读回显示seq连续、源步.02秒，但接收单调间隔1.47256秒、墙钟间隔6478.011秒；差值6476.539秒。systemd-suspend.service原日志确认19:36:30.288进入suspend、21:24:28.679恢复。该失败不能归为异步发布残留阻塞；桥station_pose_publish最大7.30ms，而两个独立进程的MuJoCo步与publisher query在相同窗口一起停顿约1.42单调秒。原结果保持失败，source-pause-readback与系统日志独列。它也不证明异步发布已彻底消除所有调度抖动。

后续1790ccc原生完整run9ecd328c已通过重置并派发B，纠正竞态有效；A原物理通过，B在Dock因工位观测过期失败，整体仍1/2。源龄.34秒时桥publish耗时.323778秒，独立physics同窗17帧9694–9710连续，最大接收间隔.02116秒。该证据缩小到桥发布/调度路径，不证明源停顿，也未唯一定位具体DDS锁或内核原因。失败、原ID及全部清理均保留。

现有桥已经有独立physics/perception/clock组和4线程；增加线程不能直接排除rclpy底层publish调用阻塞。Jazzy rclpy7.1.12源码的publish直接调用rcl_publish，未在该绑定释放GIL；rmw_fastrtps8.4.4默认同步发送。优先复用官方异步模式，将发送工作交给DDS原有线程，而不增加自制转发器、修改可靠性或放宽时效。来源：[rclpy Jazzy publisher](https://github.com/ros2/rclpy/blob/jazzy/rclpy/src/rclpy/publisher.cpp)、[rmw_fastrtps Jazzy publication mode](https://github.com/ros2/rmw_fastrtps/tree/jazzy#change-publication-mode)。这是机制支持的候选，不是已证明的业务改善。

私有`~/.cache/fishbot/build/publication-mode-proof/`用安装的原生DataWriter.get_qos分别读回SYNCHRONOUS/ASYNCHRONOUS，0消息/0动作；该诊断不入库、不替代实际业务。新增source/asynchronous启动配置只给两个Python进程additional_env，Nav2保持原设置；source默认无新增env。73项调度/启动/厂区合同通过，原生时效和2/2待验。

`direct-repeat/run`（源码cbe3251）首单物理与原K通过，第二单未执行，整轮unknown。Workflow.tick先GET state，随后GET原reset ACK；bridge在reset期间先更新episode、稍后才清空旧task并置reset succeeded。因此ACK可能已完成，而前一个state仍是“新episode＋旧task＋原episode历史”，触发`conflicting task history or episode`。这是两次读取间的竞态，当前只读回看时历史与原任务完全一致，不是重置未执行。

新增回归精确将完成事件插在state与ACK两次GET之间，原代码失败为unknown；成功ACK后再GET state的三行修复使72项调度/厂区合同全部通过（.396s）。保存原workflow/真实state/原ACK的离线重放，结果waiting_ready、index1、0POST；原失败结果不改写。此结果不证明修复后原生两订单已通过，仍须新版本完整原oracle。

旧首单task21cdd2d8-446e-4a2b-86a5-e7e5e3432db7，载货Nav6b12b614f0ad4fd782b469c63a26c90e原状态4；190.153墙秒，末XY.02439442m/yaw.02658130rad，连续停稳2.58源秒；保护enabled但tripped0，不主张纯视觉精度。reset f8bb2c00-8be4-4517-9aed-2949e931a6e1成功到65f9f3e6-0e18-42a7-b23b-cf5f677b2c63，第二单未发。原runner保留实例，根用只读ROS monitor独立确认新idle回合hold/guard-off、连续quiet.74源秒后停止确切owned PID432025，端口与进程组均关闭；补充证据`recovery-cleanup-readback.json`独列，旧result仍unknown。

## J100＋3D 雷达输入核对（2026-10-22）

现有 `cooperation_profiles.py` 已提供 J100 四轮／有效轮距、原生 IMU＋robot_localization、加高托盘、工位偏置、载货 RPP 参数与恢复事务。现有三批 profile 仅是演示模板；本轮显式选择 task=transport，原 F1 两订单与目标不改。先按真实几何和载货控制边界验证，不盲搬 FishBot 的偏心原点 Omni 配置。

J100 新生成场景：工位接近扫掠168样本/432几何对，扣采样间距界后余量.02565237m；原A/B静态净距均.061m。J100参考点在轮轴中心，保留原生DifferentialMotionModel＋既有IMU/EKF，不照搬FishBot Omni。16×360 PointCloud2、raw点云、IMU与wheel/odom原生均有接收；两costmap及CM实际topic读回/scope分别记录。

前向Smac在本次B预检半径.60/.30/.20/.10未得到路径，失败207/208原件保留；不是任意前向路径均不可能的证明。NavFn虽原生4，但采样完整外廓最小-.140855m，不能计作可跟踪成功。新增可选 `smac-reeds-shepp` 复用原Nav2 1.3.13插件：载货RPP反向开启、rotate-to-heading关闭，入站仍原行为。默认navfn/DUBIN保持，控制速度／碰撞／时限／评分不变。反向半径.60原生入站/A/B均4，B95姿态采样最小.04001943m；仅采样静态检查，不冒充连续扫掠或实际运输。

反向完整首轮 run5783e801-998e-4475-ace5-4b3245e7d972（9512ceb）在B载货阶段失败，A未派发。原K为true，但连续运输与交付false；249.968秒单任务、288.208秒整轮。原载货UUID7841a13f40e54fc3be28f4fd3521be08明确取消5。独立接收窗内3604物理样本，362帧投影体轴速度<-.002m/s、实际倒车7.24源秒，不能把配置开启当作倒车证据。3D帧106→2539、raw2539，错误空；原observer/source完整性通过，物理观测缺16序号、最大源隙.30s。guard有42帧tripped，单列不称纯导航精度。

首个运输违规253.38源秒：cargo相对托盘(.028991,-.004376,.010006)m，底面接触false，253.40即恢复；完整足迹仍在范围内，不能称货物实际飞出或放宽原连续接触标准。换向时wheel参考与原生轮速变化伴随vertical velocity扰动；当前max_decel[-.1,0,-.2]为max_accel[.025,0,.05]的4倍。下一单变量候选只对称降为[-.025,0,-.05]，不提高速度、改变几何／质量／摩擦／步长、削弱物理评分或拉长期限。它是控制候选，根因未被单一因素唯一证明。原失败、两组参数已恢复及owned清理证据保留。

减速候选的零派发启动 run 为原生smoother/change_state回执超时；0start/0Goal，不计运输成绩。原runner保留launch805003；root原PID/cmdline及idle空任务核对、独立静止.7源秒后仅SIGINT清理该组，18个owned均退出/9111关闭，补充清理单列且不覆盖原unknown。

同源新实例bb15595d-f9f3-4c7f-b4bb-2215204f56d7（63ca9c4）B实际300.970秒后原120秒载货Nav回执超时，UUID61212817127c443b84b7d763fc46eb00取消5，A未执行；完整物理仍false。原K和连续交接/运输这次均true、零violation；不可升级为减速已普遍解决接触问题。两参数组恢复、原记录/source完整、owned清理过。实际运行中已GET读回RPP正反向合同、Reeds/.60和两costmap/CM点云话题，非控制器消费ACK。

补算原预检路径长3.571300m，以.03m/s理想下界119.043秒，几乎耗尽120秒而没有换向／减速余量；此前遗漏这个检查，不能用后续放宽时限补救。当前切短空托盘控制探针，读取原路径与cmd：RPP载货min regulated speed由等于desired=.03降到.005，并按原载货max(v)/max(w)=.60配置曲率减速半径；不增加速度、进度期限或评分容差。使用原生静态Reeds半径.20生成较短候选，先规划／几何／时长再120秒跟踪；本诊断不算交接/运输成功。

动态调整Reeds半径的零运动对照触发planner lookup重算期间4秒bond超时，三次ComputePath请求均未接纳；失败不能用作半径几何无路的证据。已清理该实例；后续只在准备期静态设定半径，不修改bond期限或活动规划器参数。

## 换硬件验证的最终边界

新车型不是可视化替身：原生四轮/有效轮距、原生IMU＋EKF、真实托盘/交接、标准16×360点云都在共同世界实际运行。任务owner、订单与原评分得到复用；当前B末端换向与有限120秒仍没有通过，不能据此称硬件无关导航已完成，也不能证明所有可行路线都不可能。

曲率候选的2310条原RPP命令角速全部≤.05，但B短探针仍超时；.15m接近距离候选也未通过。它们只取得软件合同与局部控制观测，不进入默认profile；已保存完整patch供后续接续。软代价停车候选的实际路径与新鲜costmap会变化，静态最短/低代价预检不等于原载货回合重放。路径下界应同时计线速与角速，显式增加换向/接近余量，不能只除总里程。

本轮保留的默认改动是63ca9c4之前的可选双向阶段入口、transport profile与对称缓减速；最终140项过、零skip。下一步应把目的地进场姿态作为任务输入，并在同一原导航预算内验证；不是继续叠新模型或把SAM3语义观测当作路径消费证明。父FishBot2/2保持。

## 进场合同与路径预算的本轮边界

新增进场点属于目的地业务输入，不替换车型必要的body-frame出站，也不改最终交付姿态。原Workflow保存与恢复这些输入；原Bridge/原生Nav2继续负责执行。共享期限必须从出站后首次配送Goal之前开始，覆盖接纳和每段停稳；只给各wait函数重设120秒会漏掉累计时间。

`cooperation_delivery_route.py`的路径估算显式考虑线/角运动重叠、换向、加减速与pre/post-hold两段原`.7`源秒停稳。运行预算用单调墙钟，估算声明源/墙速率和路径朝向跟踪假设。它既不是上界，也不是所有可能路线的最优下界，不新增内容哈希或Held执行门禁。

真实25个ComputePath请求证实北侧若干直观点在当前地图为lethal/206；南侧可以找到整路几何通过的候选，但此次采样的时间预算不足。没有因此扩大期限或复跑完整抓放。代码、独立路线评分、原1719项反馈回归和补充CLI检查均通过；J100实际多段路线和完整业务仍待验收。

## Smac Lattice 原生缓存复现（2026-10-23）

系统已安装Nav2 1.3.13 SmacPlannerLattice；官方diff生成器产生前进曲线与原地转向，原5cm样例不匹配当前2cm地图。本轮使用原版生成器生成diff/.60m/2cm/16head原语。

真实原生库最小反例：clear endpoint=true，cold blocked edge=false；先检查同endpoint后，warm blocked edge错误为true。`NodeLattice::isNodeValid`先返回`_cell_cost`缓存，绕过与incoming primitive相关的整段碰撞。补丁只让motion_primitive非空时重新检查；同程序在独立overlay中两条blocked edge均false。源1.3.13头文件node_lattice/types与系统安装完全相同，不改公共ABI、系统安装或已运行实例。实体工厂只规划首次路径穿障碍-.22596m，costmap实际正确为254，关闭analytic无效；修库后前进模式208无路，倒车得到完整几何通过但估算198.14秒的路线，尚非业务成功。

原生入口/最小复现/补丁：`tools/cooperation_lattice.py`、`cooperation_plan_witness/lattice_cache_probe.cpp`、`patches/nav2-1.3.13-lattice-edge-cache.patch`。源码来源为navigation2/1.3.13，license随生成资产保留；实际动态库路径在私有native-patched-preflight/loaded-planner-libraries.json。


### 旋转箱体下界与控制衔接

旧AABB下界可在两包围框相触时趋于0，即使实际箱体仍分离。J100路径一姿态的AABB间距2.06nm，而原生与旋转分离轴均为.138576m。仅加密会追到AABB零点，不能解决下界本身过弱。`pair_clearance`保留远端AABB快速下界，对近端box-box增加15个旋转分离轴投影下界；有正分离证明才使用，重叠仍查原生距离。人工双箱解析距离、AABB两侧小位移和真实重叠负例均回归，未缩车、未改物理接触或原评分。

同一旧路径独立重算未覆盖原报告：原未修库路径仍-.225964m拒绝；低软代价候选仍-.017173m拒绝。padding .03/.04两候选分别取得.006505/.054791m扣采样界后的正余量，32heading也通过完整几何但估算150.96秒。保守padding只作用全局搜索，不改变实际车体/local costmap/CM。原始coarse失败与projection读回分列。

16heading/padding .04/原生reverse，静态长度2.908075m、yaw4.428595rad，采样下界112.644秒、含余量估算118.844秒。该估算未声称执行上界。原B空托盘实际Goal56a4914f3f2046cbbf0e38ad2b16133f接纳，2339条带received_global_plan的非零命令，相对第一条保留真值的最大位移2.138122m；120.070秒取消/原status5，末误差.988705m/.326931rad，禁碰累计0，hold/停稳/owned/端口清理通过。保留物理窗内有.92秒最大源间隙，不称完整无损。

原路径起始同XY三次旋转至-.463648rad；倒车RPP不能同时开启use_rotate_to_heading，初始请求v=.03/w=-.134被原平滑器角上限.05限制，原地动作被走成弧线。复用官方1.3.13 RotationShim（原RPP同命名空间、use_path_orientations=true、原阈值.3/速度限制）后，原B第二Goal1621b06d421c4356b742dc42d9aec0a6仍120.061秒取消，末误差.349670m/.880649rad；2173条实际带plan非零命令、保留窗相对位移1.649046m。此只证明相应控制/物理活动，均非到达或完整交付。下一单参数对照只缩approach_velocity_scaling_dist .6→.12，保留原最高速度、加减速、原min_approach=.005及评分。

最后Shim/approach .12对照Goalcd5ccbac3afe46c2ac587b15bd316bea在120.071秒原status5，末误差.226143m/1.003603rad，2157条带plan非零命令；仍未到达。三轮监控只保留20000条尾窗，原位移统计以第一条保留真值为原点；不能称从Goal起点的完整轨迹。没有做新完整抓放或A目标，也没有把未通过Shim/软代价/padding/approach提升为默认参数。有限试验保留，下一根owner应针对真实跟踪/反向切换与时间裕量继续，不据仅规划参数宣称业务修复。


## J100完整配送接续诊断（2026-10-23，未计配送成功）
- 原生初始路径ComputePath UUID c01539d6deef4d9a9d470e880188c134/status4，长度2.908075m、累计yaw4.428595rad；完整几何减去采样间距界余量+.054791m。原生IsPathValid=true，排除“初始路径天然无效”的假设，不说明全程有效。
- 原生MPPI1.3.13 DiffDrive候选保持原速度/加减速/碰撞，UUID9cb2b790c1e647a690514ccbf12417f6原120墙秒取消5，最大位移.110154m、末1.648764m/.202734rad，未晋级。实时率约.949；完整起点窗口保留。实测transformed path非旋转零长前缀，不采用该猜测为根因。
- RPP旧regulation最低速度=.03与desired=.03相同，覆盖曲率调速。native速度平滑器先独立截绝对分量，scale_velocities只影响后续加速约束，不能恢复曲率。按vmax/wmax=.6配置调速半径、最低速度=.005的私有候选中，1420条行驶命令角速度超限0（前一轮586/1605）。这证明原命令饱和缺口已缩小，不证明到达。
- 该RPP候选UUID85379eb1213c4801ab3bac4fb91efe41，120墙秒取消5，末1.307061m/.826371rad。全记录源37.98s/墙235.074s，明显计算变慢；mj_step均值7.604ms，而MPPI轮1.248ms。离线同物理2500步实测5源秒/2.557墙秒（1.955倍），暂不能独占归因环境或线程。失败与清理均保留。
- 新短段仅恢复旧最低速度曾掩盖的软代价减速关闭，同时保留曲率调速、native collision、CM与原caps；当前运行，不计验收。OMP=2/OpenBLAS=1仅进程环境，未改全局或其他任务。
- 证据根：~/.cache/fishbot/factory-line-delivery-20261021/j100-transport-20261023/。原cap路径估算118.844/120墙秒，提议独立J100业务速度.06/.10（原加减速和评分不变），尚待用户选择。

- 同速曲率联动/无软代价减速轮仍在120墙秒取消，26.226cm/.870140rad；独立原生0.40m原语只规划全几何通过但154.022秒预算不足，未派发运动。更小原语半径并不保证更快路径。本轮owned/9111已清理。

- 用户接受独立J100 .06/.10后，原B同UUID3a11d31425024d6e81ea7e71db20da65在86.151墙秒原生4，真值2.079cm/.009458rad及停稳/清理通过，5151样本累计车/臂禁碰0。只是空托盘跟踪通过，完整配送另用原factory/oracle同轮B→A验证。

- 首轮完整.06/.10不是路径切错的既定根因：native YAML default_nav_to_pose_bt_xml仍指原HeadingAware树；桥goal.behavior_tree空值本身不证明走错默认树。实际独立失败为floor contact两样本中断，几何足迹仍居中；真实状态命令面板复现.10断触而.05正负转向/弧线均未断触，原评分保持。低转向候选仍需载货到达和新完整同轮B→A。

## 停稳时戳与静态接触描述缓存（2026-10-24）

- v7原343.711秒B失败发生在原DriveOnHeading成功后：输出零目标仍携229.56stamp，230.066拒绝过期，230.08原ctrl全0/floor force0而hold=false，位置仍在托盘内。不是已到货或几何越界。原.5源TTL不改。
- Nav2 1.3.13官方已有stamp_smoothed_velocity_with_smoothing_time，且原生clock fixture此前启用true，真实候选却false；加速度/暂停测试不覆盖这种配置差异。全输出刷新会影响旧移动输入的TTL/episode语义，本轮未采用。改为显式终态零目标心跳，只有原owner/原Goal status4/新物理帧才发，仍走原生平滑器与碰撞链，不接管活动Goal或对旧运动改stamp。
- compute v3成功：27→0过期拒绝，两组均50Hz断触0；故只证明时戳改善。根曾误认为辅助模块遗漏，实际上传文本已包含，未取消作业，已纠正。v4补500Hz后，旧路径3步断触、新路径0，双方50Hz仍0、最终静止；有限重建初态无warmstart，不能称现场逐比特重放或完整配送已修复。
- compute v4完整ROS静止22墙秒，physics约1.0073倍、scan/cloud10Hz、IMU/physics50Hz，完整native readiness/owned清理通过；没有原完整oracle及活动规划负载，不能解释为v7活动任务.61实时率已解决。相同版本来源被服务端剔除，真实执行重建，来源拒绝原因仍待核实。
- 另一已剖析热点为contact_state中每步重复的静态geom/body名字、归属和plane类型查询。只缓存不可变编译描述，逐步native force/dist与全部检查仍执行。五个实录状态各200步qpos/接触记录相同，四个真实碰撞反例保留；ABBA各5000次线程CPU原.564/.529秒、缓存.226/.243秒，是该分类片段收益，不冒称整环倍率。已有500Hz原生测距省略是独立可选配置，默认仍保留。
- 本机同版依赖在独立fishbot-compute-tests venv恢复，未改系统包/其它运行环境。只读时16核约3.5GHz/load10.86/80℃，不是持续算力承诺；继续原生时钟与独立域静止，若不合格不开始新完整任务。GPU只读前检为T4×2/4CPU配额，未确认更高单核吞吐，未用GPU运行任务、未开启付费扩容。

- 本机带原oracle测量实际1.0015倍/50Hz、采集closed/complete通过；没有业务marker，oracle业务false符合范围。原first测量1.0026倍但销毁KeyboardInterrupt，保留false。Jazzy execute_local.__on_shutdown对noninteractive会send_sigint，原killpg可重复信号；改只signal owned launcher后，复验finalization=[]/零survivor。所有helper调用者均为非交互ROS launch（包括exec shell入口），不把此法推广为任意进程树终止策略。

- 本机完整b确认compute余量已覆盖真实抓放/出站：包装物理步.914ms、真实任务222.017秒已原K/连续载货通过，仍未交付。随后取消来自fresh()在浮点-0.100000000375928s上拒绝，差原边界.376ns；原接收龄5.791ms，不是收包停止。保持同一100ms/250ms范围，改为生产器同样ROS整数纳秒量化，新增越界1ns负例。较早-120ms的HTTP拒绝是真实越界且仍拒绝；不据此改写所有旧时效问题因果。
