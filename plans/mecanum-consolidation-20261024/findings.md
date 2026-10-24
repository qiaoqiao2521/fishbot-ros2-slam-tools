# Findings — 麦克纳姆合并

- 当前来源：`/home/muqiao/dev/ros2/projects/robot_base`，HEAD77d1ba2，Apache-2.0，Jazzy/Python3.12。旧origin仍为归档账号muqiao215；本轮不向该远端写入。
- 9处dirty修改时间为2026-09-11，涉及串口锁/有限读缓冲、连接归零、cmd_timeout停车、参数化端口、odom协方差、launch路径与包元数据。保留并逐项核对后迁入；.omo/.devcontainer不属于运行包。
- 运动学轮序沿用m1/m2/m3/m4：vx-vy-k*wz、vx+vy-k*wz、vx+vy+k*wz、vx-vy+k*wz。k=.3075m，反馈为mm/s，默认极性-1。PWM死区与限幅是已有硬件假设，不外推到仿真真值。
- 旧AMCL为OmniMotionModel；旧velocity_smoother的vy限制为0，不能从驱动支持横移推断自主Nav2横移已通过。保留其基线参数，不替换原FishBot/J100参数。
- 已有rclpy、pyserial、Nav2可用于隔离伪终端验收。无需安装新协议栈、申请GPU或操作真实串口。
- 原驱动send_motor_cmd重连后不调用enable_feedback；看门狗会抢在2秒重连timer之前打开端口，导致后者不再恢复MSPD。pty-a复现，保留失败；新包只补该路径的enable_feedback调用，重建后pty-b同面板8项通过，实收横移odom vy=.05m/s、vx/wz=0，串口线程与ROS上下文已关闭。
- drive/minimal参数解析均通过；mapping改为复用官方online_async_launch，已核本机参数名slam_params_file。构建输出在Git外，发现的ROS包只有robot_base，没有引入旧目录或嵌套Git。
- TraceMesh codex刷新为partial，部分历史超出捕获预算；robot_base检索超出查询预算。本次按当前源码、Git与九月文件时间核对，不声称覆盖全部对话。旧总目录把robot_base列作独立项目的决定被用户本次统一维护要求更新。
