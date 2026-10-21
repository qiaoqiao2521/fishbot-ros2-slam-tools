# Findings

## Existing contract
`start` body 为 `task_id/episode_id/issued_at`；`cancel` 为原 `task_id/issued_at`；`reset` 为 `request_id/episode_id/issued_at`。基线不接受 `scope`；当前 dirty 版才接受显式 scope。两版默认均为完整运输，薄层使用基线最小键集。`state` 忽略 task_id query；其 history 仅最近 10 项。按 ID 与 episode 检索，缺失不推断未执行。

基线未公开 cleanup/native_actions，当前主区 dirty 版有。原 `state.reset.available` 内部核对任务非 ACTIVE、worker 结束、原生 dispatch 终态、car_hold、guard 关闭及车臂货物 quiet。薄层跨两个版本使用该现有门禁。桥接进程带旧账本启动保护保持；恢复只针对编排器，不能借重启桥接器接管未知动作。

## Reuse and knowledge
复用 `fishbot_simulation_suite.write_json`，原子 replace 后同步 final 文件和目录，完成提交前稳定写入屏障。标准库 HTTP 不自动重试 POST；标准 `flock` 保证同账本只有一个 CLI owner。无需新调度、认证、ROS 协议或通用服务。

采用 `Wiki/自动化开发范式与智能体协作.md#远端任务恢复：先确认提交边界`：仅提交次数零的明确未发送才能首次发送；尝试后只恢复查询。替身回归证明应用层不重放，不能声明服务端恰好执行一次。

## Model boundary
Laundry readiness 为合成领域事件；刚性货物复用现有物理场景。消费混合衣物与商业标准床单的几何/材料差异不在本模块实现范围。容量一与 batch 身份属于软件合同，物理库存仍为每 episode 一个自由货物。

## Review corrections
独立审查复现基线严格键集拒绝 scope，已删除。原请求校验器直接进入 CPU fake API 边界，防止宽松 mock 漏检。基线 fresh 断流时合法 source=None；薄层先检查 source 类型，再把断流落盘 unknown，恢复后只对账原 ID。两项原复现独立通过。reset 后旧 consumed ready 清空，但事件 ID 与 version 保留；失败 retry 也必须新版本 ready。

run 只循环本 workflow。fault/unknown 立即返回，不隐式 recover；成功路径自动处理 ready、原 ID 轮询和显式配置流程内的 between-job reset。单步 reset/recover 保留供调试与故障处理。runner deadline 不取消原任务；HTTP 每步有固定 5 秒 timeout，退出时刻可被当前一步有限超出。

独立 run 审查复现慢 GET 越过 deadline 后仍 POST。已在 start/reset 的 intent 前及同步后 POST 前检查预算；原复现零 POST/零 attempt，intent 后超时也零 POST并保留 unknown。预检失败但从未生成任何意图，保留 waiting_ready 与 blocked_preflight；此有证据的 unsent 可以恢复首次提交，不可套用于已尝试动作。旧 v1 证据保持，不冒充新版运行。

## 实际桥端与采集边界

新runtime源与独立接收每20ms推进，但桥缓存落后0.28源秒，原门槛触发取消；没有物理源暂停的证据。分段计时尚待确定readiness/锁/调度具体阻塞点，不预设根因。普通HTTP reset ACK缺源reset_stamp，不满足现有oracle；独立ROS reset_result与新episode physics的原源时间须绑定后再开始采集。两次运输尚未通过，取消与原ID恢复证据分别成立。

## 第二轮诊断：桥Clock落后，不能归为同一个缓存原因

`runtime-20261015-a82c8b55`在冻结14a6daf下执行。独立可靠ROS reset_result、原physics reset_stamp、新episode和采集起点绑定通过。移动Dock原UUID取消与独立quiet/cleanup通过；job1在准备Nav失败，job2未派发。完整评分仍false。

失败wall1791996994.829836时，桥clock74.5、raw physics74.82，source age为负0.32s，接收龄约3.57ms。独立observer在此前5.277ms收到clock74.84、此前2.084ms收到physics74.84；原Clock每0.02源秒持续更新。失败附近已测physics全callback1.266ms、readiness0.165ms、锁等待0.000792ms；旧episode的0.107s HTTP慢事件发生约56秒之前，不能作为本次原因。

安装版rclpy7.1.12的标准TimeSource创建`/clock`时未指定callback_group，因此和桥的ActionClient等实体共享默认MutuallyExclusive组。四executor线程不会绕过同组互斥。这是结构证据；具体占组callback及DDS排队尚未证明。候选仅以公开create_subscription透传原标准Clock callback到专用互斥组，不复制时钟、改vendor或改物理门槛。实际阻塞probe和唯一订阅/QoS读回后才进入新物理面板。

受控实际ROS probe `clock-group-controlled-20261015-c32d691b`通过。默认组busy callback持有0.759191墙秒，实际publisher20条推进0.634229源秒；shared Clock零推进，专组与独立witness精确匹配末戳，释放后全部同步。四节点destroy、executor停止、spin退出和新context空domain120读回通过。标准TimeSource.clock_callback与depth1/BEST_EFFORT/原QoS一致。根核对script SHA、publisher/witness原件和receipt SHA `dd61b6aca40652d69b28354a7ca26277e93c8be447c761de10d3ce0185fcbfae`。

前两probe false原件保留：ac80d0c9的虚拟源推进预期不成立；b49ae70f把成功返回None的destroy_node误计0。新判据绑定实际publisher推进与独立witness，不把墙时间当源时间。通过probe只证明可构造的默认组阻塞风险，不声称复现桥原guard或识别a82占组实体。

第三轮ec879ed下同三case全部通过，原360s完整任务与所有物理门槛保持。两作业之间独立reset源stamp早于采集和派发，原UUID、单货物自由体与完整交接评分通过；只重启CLI，不重启bridge。末账本仍保留一次+0.26s的物理源龄边界诊断和3次拒绝，因此不宣称全部时序异常已解决。新面板使用ideal信标，不能补齐旧RGB留出失败或重写原视觉56例。

## P7 复用差距核实（2026-10-20）

- 当前workflow是恰好两批的专用编排；jobs长度、index边界和末作业判断固定为2。start原负载只有身份/时刻，不包含目的地。重复同模板可复用，但第三批或新终点不是现有配置即用能力。
- cooperation_bridge执行层已有stations.delivery→原navigate(carrying=True)，且任务/history/取消均归同owner；本轮只需把目标从固定点改为每task冻结参数，不重写抓放、DockRobot或载货导航。
- 原full_score验证真实抓放、同货物位移≥.5m、quiet等，但没有独立目的地XY/yaw条件。必须增加目标绑定和实际末端检查，不能拿旧passed推断到了B。
- 采用既有Wiki/ROS2与FishBot的原生时钟/回调组、真实动作与独立物理评分分离经验；本轮保持源时钟/TTL/物理门槛，不用桥转发当控制器消费。配置路径按本机knowledge-workflow解析，知识只作参考。

### P7 实际暴露的锁边界

B首任务接纳时，首次SceneGeometry编译在telemetry锁内耗时约3.17秒；独立Clock继续前进，但物理callback等待锁3.1717秒、station等待3.216秒。失败点源龄2.4秒、接收龄14.6ms，原native尚未派发。这是新预检接入造成的反馈阻塞，不能怪网络或放宽原0.25秒源龄门槛。

修复采用独立geometry锁与启动预热，runtime查询在telemetry锁外；回来后重新核UUID/episode/TTL/ready才接纳。真实双线程回归确认慢query期间observe仍更新原缓存。可选几何依赖缺失不破坏旧默认路线，只给显式新目标具体原因。

C实际physics锁等待最大68.39ms，slow计数0；全桥仍有4个慢事件，包含station锁127ms与HTTP组装128ms。因此可确认本轮编译占锁缺陷已修复，不能宣称全桥没有慢事件或所有时序抖动已解决。几何clearance的.20m是搜索截断上限，不能解释为精确净距。

独立清理还需区分“已有原生UUID待终态”和“在第一次派发前已失败”。后者没有UUID，需明确failed、空dispatch/handles、verified cleanup与独立连续静止，不可等一个从未产生的UUID，也不把这类清理叫任务成功。canonical验收已补此分支与目标marker兼容，不改变真实运动标准。

### P7 已验证的复用范围

C同桥连续完成A/A/B，任务请求、接纳目标、最后载货Nav UUID及独立真实终点一致，三份原K与新增目标评分均通过。第三货物实际净位移2.48919m、目标误差.022101m，证明并非仍送往默认A。源码执行前后逐文本一致，原前端仅换运行配置即读回B，无前端源码适配。

因此，同模板新增批次和当前场景内可达目标已是输入层变化。首次实现仍需扩展workflow数量、start目标冻结与oracle目的地评分三处通用接口；不能把本轮称为零代码修改。不同工位/货物/底盘以及真实场地仍需独立适配，三次合成episode也不是三件同时存在的库存。

## P8 接入边界

现cooperation_scene/sim固定FishBot两轮关节、.13m圆、托盘偏移与站台高度。J100已在另一个ROS C++ MuJoCo3.12链路实际导航通过，但尚未与SO101的Python3.3.7共同世界组合。当前网页car标签也固定FishBot。原生3D扫描器插件同样属于3.12边界；跨栈需要核对API/资产适配，不能把现有.so注入3.3.7。

3D适配选择复用当前3.3.7的原生mj_multiRay与sensor_msgs_py标准编码，不另建物理执行世界；共享原fishbot_lidar3d的VoxelLayer参数。官方3.12插件保留原入口和许可，不能声称它运行于3.3.7。AMCL仍取/scan，所以准确对照名为“2D”与“2D＋3D”，不称纯3D定位。官方API与Nav2 1.3.13 PointCloud源码已核对，3D输入还接原CollisionMonitor，而非只在页面画点云。

J100四轮共享scene实测编译为24/22/10；旧qpos22/qvel20键名为兼容保留，但携带完整数组，由接收端按当前编译manifest尺寸验证。相同前13货物/机械臂、13:20车体索引保持；规划与评分不能截掉新车尾部关节。J100复用已有robot_localization EKF，仅轮式vx/vy、IMU roll/pitch/gyroZ，排除绝对yaw和车体真值。

### P8 已取证的适配经验

四轮滑移不是通过提高力矩即可消除。固定离线阶跃测到原转向约15%而直行正常；复用原生diff-drive effective track惯例，只给此仿真接触模型标定4.5，命令与编码器一致使用，真实轮距不改。该参数有速度/方向/载荷残差，不能外推实车。机制来源为[原生Jazzy控制器](https://raw.githubusercontent.com/ros-controls/ros2_controllers/jazzy/diff_drive_controller/src/diff_drive_controller.cpp)，本plant数值来自私有固定阶跃而非官方旧1.5参数。

运行动力学与距离查询的算法选择需分开。[MuJoCo3.3.7官方Geom distance](https://mujoco.readthedocs.io/en/3.3.7/computation/index.html#codistance)说明旧MPR远距不准确；本地同状态确证distmax=.1将30.8mm几何分离误报.55mm。全切GJK又复现原SO101远隔47mm报0的问题，因此不为新车型推翻旧动力学选择。最终只把原checker查询cap设为原1mm阈值的两倍，仍检查所有原pair；.5mm/负.5mm/1.5mm/2.5mm独立重编译反例通过，输出2mm是截断，不是精确净距。旧失败和全GJK候选保留。

二维规划余量不等于3D网格障碍语义。名义低侧19.2mm余量小于实测AMCL XY误差P95约26mm，两种雷达均可因原生碰撞预测拒绝。J100侧移40mm并反向移动托盘，保持原交接点后，该侧padding后余量42mm；整体3D扫掠最小余量未提高。此为实体安装配置适配，不关闭碰撞。悬臂85mm按刚性模型假设，不能当实物强度验收。

三维观测需要整车与载荷自体模型。dev-e物理放货留盘、臂回位后，footprint内11个原生低点全部来自同一自由货物，超过CollisionMonitor原6点，车辆被拦停。原native载货Nav104失败和完整oracle=false保留。标准空间自体过滤属于传感器适配，不能移除货物物理geom、按taskstage编造失检或通过扩大minrange忽略车外障碍；原始首回波应留同源对照。该修复的实际载货验收仍待后续回合。

传感器topic/真实订阅/实际栅格/控制器消费回执是不同证据。E已取证真实16×360/10Hz、原stamp配对、costmap与CM配置及同一时刻订阅、EKF输入；未独立证明逐帧唯一odom TF发布者，也未把观测转发当控制器消费ACK。ROI中的253为膨胀代价，不能写成254碰撞格或零代价。原生[CostmapTopicCollisionChecker](https://raw.githubusercontent.com/ros-navigation/navigation2/1.3.13/nav2_costmap_2d/src/costmap_topic_collision_checker.cpp)以254及以上拒绝。

### P8 出站原语与载货限制

地图前方目标不构成直线约束。正式A/D的RPP会先正转，触发工位邻近障碍预测；只增加staging目标仍不能消除该选择。最终J100复用已启用的DriveOnHeading，以车体相对位移退出，再接原Nav。保留真实body请求与nominal map参考的区别。F独立GetResult确认同Drive UUID status4/error0、35.22源秒；不能据此前置成功声明最终运输完成。

RPP按实测current_w每周期夹限，不累计上一条命令。E的maxa=.2/20Hz固定输出.01rad/s，轮编码/真实角速约3.93e-6，且hold=false；恢复w=1可转，说明低速起转死区而非锁。J100候选改为maxa2、原地转向上限.1，StoppedGoalChecker保留原位姿门槛并核原.01速度条件。机制可对照[1.3.13官方RPP](https://raw.githubusercontent.com/ros-navigation/navigation2/1.3.13/nav2_regulated_pure_pursuit_controller/src/regulated_pure_pursuit_controller.cpp)。

瞬时失接触不等于滑出。B/F都是完整货物足迹仍在盘中央，独立同帧几何分别证实约9/32µm正gap。F精确重放能复现32.449µm；增托盘阻尼1.5/2仍失败，因此未改物理。降低实际命令前缀至四分之一后，有限4.2秒重放2100物理步没有失接触，但不能代替闭环导航或跨reset验证。最终候选只给载货阶段增加速度/加速度限制，通过同一原生服务读回并在清理恢复；原TTL、物理接触、完整足迹和任务时间门槛保持。所有旧失败保留。

H第三批首次取消时，桥当前Clock537.12、缓存physics536.66，源龄.46s/接收龄.4626s，约.458s没有物理callback进入；独立observer仍以20ms收齐physics和Clock，最大接收gap约22ms。此前已完成的Clock专组不等于所有回调都及时。后续HTTP assembly .292/.358s与physics锁等待.300s是具体性能风险，但发生在首次取消后，不能倒置因果；首发执行器/GIL/未计时阻塞仍待核实。I只作同源码复现，不改时间门槛，也不把关闭额外探针当根因已修。

I第三批已有直接曲率证据：同source725.18，原RPP碰撞预测arc三点XY反推κ=.203rad/m，实际cmd v=.02/w=.02447对应κ=1.223rad/m，约6倍；其他近配对亦有类似变化。arc默认quat未填写，不能拿其读航向；±20ms近配对不冒充同迭代ACK或唯一超时因果。只在下游夹限线速度会改变原几何控制器的曲率要求，载货期应优先通过RPP自身desired/min_regulated/min_approach/rotate四DOUBLE生成一致的低速轨迹，再保留smoother安全输出边界。官方[参数回调](https://raw.githubusercontent.com/ros-navigation/navigation2/1.3.13/nav2_regulated_pure_pursuit_controller/src/parameter_handler.cpp)使用与compute共享的mutex并更新内部值，不只是ROS显示值。
