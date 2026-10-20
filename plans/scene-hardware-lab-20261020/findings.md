# 发现

- 起始源码fe544eb，工作区干净；上轮三工况完成，不改写旧失败。
- 复用scene_campaign、home_scene地图解析/矩形化、Nav2 mission owner、独立ContactAudit及工作台GET报告；本轮不重写仿真平台。
- 实测图由私有2026-10-08接续记录定位，119×108、0.05m；free2963/occupied896/unknown8993。地图保持私有。
- J100来源为官方clearpath_common Jazzy（BSD-3-Clause），质量/惯量/轮几何来自实际URDF；摩擦与伺服参数明确假设。
- 官方MuJoCo已有adhesion actuator，优先复用，不自造吸附约束；压强/泄漏/耗能属于薄适配。实际支持版本与输入值由分项报告给出。

## 采用经验

采用Wiki/ROS2 与 FishBot第18–20节：软件禁入不成为AMCL激光墙，真值/观测/原生动作/物理验收分开；日志有界。CapMesh现有社区表只作线索，本轮采用官方模型与原生MuJoCo，不新增基础平台。

## 接入修复

- 新底盘配置必须贯穿实际plant、URDF、四轮控制、Nav2足迹和任务桥；仅替换scene会保留旧几何校验。本轮修复默认半径硬编码，未跳过确认。
- keepout merge按baseline inflation覆盖默认，保留其通用逻辑；只让J100生成器输出与车体相容的膨胀半径。不是缩小车体通过。
- 本机有robot_localization3.8.3；官方Clearpath通用定位使用原生EKF。后续已核实本机原生IMU broadcaster标准消息与实际参数；具体厂家实机IMU链仍未核实。本轮复用该官方节点，不自造融合实现。
- Python负压环境3.3.7与ROS C++ vendor3.12.0隔离；wrapper清除继承PYTHONPATH/LD_LIBRARY_PATH，避免ABI混用。

- 已采用知识第11节：先区分真实旋转、进展判定和定位误差。J100切PoseProgressChecker识别转角，仍保留原平移/无进展时间条件。
- C轮独立RPP路径旋转/真值同源对比显示末段yaw差2.3009rad；局部致命格密集是线索，缺rawcloud时不直接认定地面误投影。优先融合真实gyro，不关闭三维标记或用truth冒充里程计。
- 私有runtime已安装官方imu_sensor_broadcaster4.42.1，无需自写传感器适配。静止134实际标准Imu、wheel/filtered Odometry各3帧，dynamic_joint_states原生imu10interfaces一致；EKF无truth订阅。静止probe已由根清理。
- 官方URDF固定轴mesh旋转与MJCF默认内禀Euler不同；已改显式quat并核同SDK变换。不改collision几何，旧C保留。

- Jazzy RPP的rotateToHeading按当前实测角速度限制命令变化；两轮默认2×0.05=0.1rad/s在四轮擦滑模型中仅约0.01rad/s实际响应。只在J100 profile设置RPP上限10，轮控2与执行器12Nm均保留；不是改plant摩擦以获取成功。
- 工作台读取的人可编辑JSON可能出现头部passed和缺失/失败案例矛盾；展示层局部降级并保留兄弟项，既不伪绿也不阻塞仿真。地图YAML损坏只使独立评分unknown，不中断其他报告。
- 墙面试件机壳不参与碰撞，质量/惯量保留；轮接触与失压脱落不能推出机壳撞击或整机防护有效。该边界已补说明，物理参数/测量/判定未改。
