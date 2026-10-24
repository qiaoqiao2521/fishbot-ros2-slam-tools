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
