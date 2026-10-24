# Findings — 麦克纳姆合并

- 当前来源：`/home/muqiao/dev/ros2/projects/robot_base`，HEAD77d1ba2，Apache-2.0，Jazzy/Python3.12。旧origin仍为归档账号muqiao215；本轮不向该远端写入。
- 9处dirty修改时间为2026-09-11，涉及串口锁/有限读缓冲、连接归零、cmd_timeout停车、参数化端口、odom协方差、launch路径与包元数据。保留并逐项核对后迁入；.omo/.devcontainer不属于运行包。
- 运动学轮序沿用m1/m2/m3/m4：vx-vy-k*wz、vx+vy-k*wz、vx+vy+k*wz、vx-vy+k*wz。k=.3075m，反馈为mm/s，默认极性-1。PWM死区与限幅是已有硬件假设，不外推到仿真真值。
- 旧AMCL为OmniMotionModel；旧velocity_smoother的vy限制为0，不能从驱动支持横移推断自主Nav2横移已通过。保留其基线参数，不替换原FishBot/J100参数。
- 已有rclpy、pyserial、Nav2可用于隔离伪终端验收。无需安装新协议栈、申请GPU或操作真实串口。
- 原驱动send_motor_cmd重连后不调用enable_feedback；看门狗会抢在2秒重连timer之前打开端口，导致后者不再恢复MSPD。pty-a复现，保留失败；新包只补该路径的enable_feedback调用，重建后pty-b同面板8项通过，实收横移odom vy=.05m/s、vx/wz=0，串口线程与ROS上下文已关闭。
- drive/minimal参数解析均通过；mapping改为复用官方online_async_launch，已核本机参数名slam_params_file。构建输出在Git外，发现的ROS包只有robot_base，没有引入旧目录或嵌套Git。
- TraceMesh codex刷新为partial，部分历史超出捕获预算；robot_base检索超出查询预算。本次按当前源码、Git与九月文件时间核对，不声称覆盖全部对话。旧总目录把robot_base列作独立项目的决定被用户本次统一维护要求更新。

## P2来源与边界

- 现成实现：JunHeonYoon/mujoco_mecanum，MIT、Copyright2023；只复用wheel_code_gen的滚子pin/轴构造，不迁入旧mujoco_py运行器或SUMMIT整车。原生成器硬编码质量/惯量且球形滚子用了整轮半径，不能不核对就照搬到97mm车轮。
- 官方MuJoCo3.3.7建模文档明确关节树和真实接触求解；本轮用独立被动滚子关节，不用直接驱动车体平面自由度。来源：https://github.com/JunHeonYoon/mujoco_mecanum 与 https://mujoco.readthedocs.io/en/3.3.7/modeling.html 。
- 采用知识库FishBot§19的参考点、完整几何、双时钟与编码器/真值隔离，§20的原生动作/交接/物理评分分层；同一接口或模型文件存在不计运输通过。
- 宽车壳不能照搬托盘安装：侧移车体40mm并反向补偿托盘，保持SO101交货XY=.24/.14；实体40×40×80mm立柱和密度质量进入原生动力学。过重立柱横移停车失败保留，当前motion-c16/16及short-dock-a原独立停靠评分通过。
- 完整D的release阶段固定指残余接触约.177N、活动指0、托盘已支撑。原SO101 `grasp_episode.py` 的实时release分支只要求活动指<.02N、jaw>.45及托盘接触，然后退出固定指；FishBot桥却在retreat之前调用最终settled_cargo，造成先后矛盾。本轮修复过渡条件；最终双指<.02N、完整足迹、相对静止、home与运输评分保持。
- D另有独立记录器write_failed/close_flush_failed，原始流在约100.9源秒截断，正式评分false且不评物理；没有把后续HTTP状态代替缺失记录。/home仅约1.5GiB可用，未唯一归因errno。原运行器保留实例后，根另用新鲜原生Goal终态与连续.72源秒quiet读回，再关闭准确owned进程；独立retained-cleanup.json确认无survivor、端口关闭。原D结果仍保留unknown/failed，新验收输出使用/tmp独立文件系统。

## P3输入与范围

- 只复用现有lidar3d适配，不开发新雷达或调度器。prepare将实际PointCloud2接入全局/局部costmap和Collision Monitor；AMCL继续原/scan。此次只验混合2D定位＋3D障碍感知的完整麦轮运输。
- P2 E输入为navfn、OmniMotionModel、360束实际scan、ideal工位观测、开放通道、原出生点(0,-2)。不改速度、几何或实际传感器采样；omit配置标志本身不证明模型有原生rangefinder声明。
- 前检9117空闲，无同类原生配送进程；/home当前约62.77GiB可用，使用私有持久输出保留原始证据。这些是本次读回，不推断此前D的IO错误唯一原因。
- 首轮失败并非未抓到货物：原双指/抬升通过后，源placement.plan_transport在20mm cap下将明显分离的箱体对报成-77.730mm。反向查询与较小cap给出不同符号，原生fromto还超出实际小箱体。独立同帧重放可复现，不据此认定3D射线导致碰撞或称真实接触。
- 官方3.3.7 mj_geomDistance文档明确legacy CCD距离不准确：https://mujoco.readthedocs.io/en/3.3.7/APIreference/APIfunctions.html#mj-geomdistance 。本轮比较现有box投影下界、局部cap与官方nativeCCD；nativeCCD初选后在C的真实分离底板帧仍报零，已撤回。源载货API没有距离注入参数，最终私有加载同一placement源文件，只为该副本提供现有pair_clearance接口；共享import、SO101源、所有模型flags、margin和cap保持。保守下界不解释为精确距离。
- E的失败是记录窗口收尾不足：delivery_checks返回binding/native/budget/last_valid均true，但当前gate从208.40到209.12只有.72源秒，曾达到1.92秒不能替代最新连续停稳。先等原observer文件的1秒尾段，再写full_finished；原oracle和1秒/.1秒gap判据保持，不改分数或把缺口插值。额外观测计入360秒任务时间。
- 原麦轮与omit候选的2000步本机组件对照：两者原生rangefinder均0，原生IMU声明均3；qpos/qvel最大差0、360束scan/5760点点云/IMU均逐项相同。墙钟.688810/.709415秒，速度比.971，无优化收益，不采用。旧“保留360原生rangefinder”推断撤回：实际仅保留360束独立scan，不能从omit=false推断原生声明数量。
- 既有queued_ros_dispatch在独立SingleThreadedExecutor接收，CallbackInbox按接收顺序交回物理主线程；with_received_time不刷新看门狗。它只替换每步inline spin_once，不改物理/实际传感器与QoS。只通过软件合同还不能称性能或完整配送改善，需原生探针与原完整任务。

## P3最终范围

- 3D H与同源码2D各自完整B→A及离线原评分均通过；同一queued接收、完整物理XML、安装、AMCL、路线和阈值，区别为传感器生产与障碍接入。短移动探针证明两阶段原生计划消费；完整运输另以原UUID和原物理评分判断，点云订阅端不冒充逐周期消费回执。
- H真实点云4434帧、16×360、多高度返回，实际进入两个costmap和Collision Monitor；AMCL仍/scan。guard可用且H介入0，2D B介入.78源秒；工位仍ideal。采样缺口与原失败保留，不把此有限面板称作纯视觉、任意车型/雷达、全向Nav2、生产或sim-to-real验收。
- 现有cooperation_timing导入器和同一网页面板可直接复用到本轮两组；只扩固定摘要映射及选择项。原J100/P2文件保持，当前2D/3D分别有实际sensor与run/task身份，不需新建报告系统或仿真平台。
