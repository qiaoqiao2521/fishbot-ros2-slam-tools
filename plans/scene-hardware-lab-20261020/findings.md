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

## P5地面到墙面

- 现有墙面试件起始已竖直且机壳不碰撞，不能直接扩充其成功声明。新连续场景必须保留完整机壳碰撞和四轮接触。
- 官方MuJoCo adhesion按所挂body的接触法向分配吸力；无接触不施吸力。复用每轮独立chamber和原生actuator，地/墙接触允许自然交接，不新增固定约束。来源：MuJoCo3.3.7 XMLreference actuator-adhesion。
- 刚性四轮凹角过渡需要前后轮不同切向速度；统一速度除45°附近外会产生滑移。优先试现有四轮完整车体，不先引入铰接/新平台。
- 对比来源Disney VertiGo确有地墙过渡，但采用可倾推进器，不能当本轮负压模型或可复用仿真包；Scorpius公开机械设计没有已验证的地墙过渡代码。本轮最小扩展既有MuJoCo而非照抄演示结论。
- 采用既有Wiki/ROS2 与 FishBot第19–20节：单一连续货物/车体、实际接触和时间序列评分；图像与进程成功均不代替物理任务。

### P5实施结论

- 保留J100质量18.431kg、完整惯量、四轮尺寸和机壳碰撞。新增吸附轮假设：总有效面积0.08m²、每轮独立压力腔、摩擦0.8；新增泵阀密封机构质量未计入，不能称原厂J100可爬壁。
- 原生adhesion在轮子同时碰地/墙时分配到两个法向，会在竖直角点把后轮压住。只在前轮墙面承载且地面密封已开后短暂排后腔，后轮离地恢复吸附。相同速度目标允许真实滑移，未强制无滑轨迹。
- 只归零轮速会受重力慢慢滑落；采用理想轮编码器角度反馈，经已有kv8/12Nm受限电机制动。自由车体没有位置目标或外力。
- near contact用于密封代理，mj_contactForce>1e-6才计承载。mj_step后调用原生mj_forward，使qpos、姿态、速度与接触属于同一源时刻；沿用知识第19节的参考点与双时钟经验。
- 独立oracle用完整901行重评分，初始自然沉降保留源0时钟，不通过重置对齐；承载起点0.04s。先四轮完全离地/竖直再累计爬升，最终hold阶段连续静止。
- 正常与无泵场景XML逐字一致、相同名义驱动与停车策略；后续实际PD命令因反馈不同而分叉，不能声称全部控制逐帧相同。负控的原始机壳碰撞保留，反映失败，不外推安全停车能力。
- 早期rigid-a、J100-a在角点停住，后续prototype-only结果和formal-d负控误判保留。formal-e画面被墙挡住，物理结果未抹掉，但录像不合格；仅相机145→45修复后formal-f/root-a实际可见。

### P5播放器接回

- 初始Vite send整文件200可播放，但实际Chrome跳转10秒失败，保留browser-qa/failure.json。小视频仍需要正确Range支持，不能只用loadedmetadata和exit0验收。
- 已装Vite的内部sirv不是公开模块；单独sirv3.0.2的suffix Range行为不满足测试，未采纳且已移除。改用成熟send1.2.1（MIT）和DefinitelyTyped声明，精确GET守卫后只发送配置文件basename/root，不暴露目录；不自写Range解析。
- npm首次未使用命令级代理而卡住；curl可达官方registry。仅给本次npm配置代理、关闭audit/fund并设置请求期限后安装完成，未改全局npm、电脑网络或VPN。
