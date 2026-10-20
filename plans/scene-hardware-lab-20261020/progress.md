# 进度

## Current

三个分项已分别实际通过，旧FishBot默认往返回归也通过。J100-E具备原生Nav2成功、同UUID和独立物理停车证据；所有ROS实验已结束。工作台已接最终报告并完成实际浏览器复核；源码验证完成，具体远端交付以本任务Git回执为准。

## Ownership

- real_map_slice：真实图适配与known-only几何检查；根运行domain132。
- new_base_slice：J100模型/控制器/URDF生成和静态物理探针；根运行domain133。
- suction_slice：隔离Python负压物理实验；无ROS动作。
- root：共享launch/campaign/工作台/SpecMesh/Git与独立验收。

## Knowledge

already_covered：本轮采用的区分真实旋转/定位/进展、双时钟、真值隔离和分层评分，已覆盖于Wiki/ROS2 与 FishBot第11、18–20节。J100特定起步值、理想IMU协方差和摩擦假设留在项目；原理与作用范围记录findings，未向共享知识库写入未标定参数。本轮无共享知识写入。

## Next

三个实验已验收。保留A–D失败与私有数据，最终工作台只读展示；无排队运动，后续组合整机/硬件标定需另立任务。

## 实际进展

- 真实图real-a passed：task3fadbf0d-2025-4220-9a7f-589dcf6cf8e5 / native6c1a834361ef418fbea2aa292f28826b，原生4；行程2.737m、1181帧full-circle known-free检查通过、最小已知余量0.02748m，实际碰撞增量0、停稳2.070s；实例清理完成。Interface-only三维探针明确没有低物体评分。
- J100-A启动期旧bridge固定.13m，与新配置.3304m不一致，未派Goal，incomplete并清理。bridge改为显式radius，贯穿freepoint、返航、倒车扫掠、路线保存和参数确认；根在正确ROS环境复跑118任务桥测试通过。旧默认不变。
- J100-B已实际到外出目标，返程规划/控制失败，原UUID终态6、零接触；发现inflation .3小于车体内接半径。只改生成参数为body外接圆.330414+原渐变带.17=.500414m，保持碰撞/物理模型。C轮仍失败，详见后续融合接续。
- J100 native3.12探针直行2s为.2964555m，四轮真实接地。滑移转向2s仅.171rad而轮式理想约1.04rad，不能称轮胎标定；不使用轮距倍率掩盖。
- 负压D五例通过，根独立root-e复跑五例全通过，每例20000物理步、4秒、原生warning0。关泵横推滑1.8524m，开泵3.94微米；四轮持压下滑5.125mm、失压前2.657mm后自然落1.480m；沿墙上行150.857mm。泵估计38.09J、驱动机械正功6.232J分开。
- 负压1ms四轮B曾失败，全部保留。0.2ms最终与0.1ms三竖墙复核分别通过，上行约150.9/154.0mm。不是CFD/真实电耗或整机过墙角验收。
- 只构建fishbot_mujoco成功。根首次在子workspace误用了相对env路径导致构建失败，随后使用绝对env入口成功；任务桥单测首次缺ROS环境，修正入口后118项通过。没有修改系统ROS。
- 网页22项相关测试通过；实际后台Chrome12项通过（real通过/J100待补齐/suction通过），GET一次且零写入，390px无横溢。最终报告后只复查状态。

## J100融合接续

C仍失败/原生6，外出到达但返程无路径，零碰撞。独立路径反推姿态与真值同源偏航差2.3009rad，不能把wheel yaw当真实姿态。

已复用官方ImuBroadcaster/EKF（无truth输入），仅J100开启；旧默认节点与配置不变。diffdrive停止发TF，wheel vx/vy+IMU roll/pitch/gyroZ输入，EKF唯一发布odom姿态。静止134有实际标准消息与full-rpy TF证据，根清理进程组完成；因为清理先到，第一次enable_odom_tf服务读回没有取得，保留available=false。

D轮新输入含完整几何、匹配inflation、官方mesh固定轴quat修复、原生IMU/EKF和PoseProgressChecker。D轮180s未完成返程，原UUID9191ce4f6e644972aa2450e7173a8a9f终态5，4526帧真值、源最大缺口44ms、实际碰撞0、停稳0.959s、清理完成。不能把超时取消写成导航通过。原A/B/C/D均保留。

## 转向起步对照

- D实际参数服务读回enable_odom_tf=false；标准IMU gyroZ与融合odom同源角速度相近，实际pose/truth航向差约0.015rad；EKF无truth订阅。保留Jazzy消息不暴露publisher GID的证据边界。
- 官方Jazzy RPP在rotateToHeading按实际角速度±max_angular_accel×dt限制新指令。冻结D plant四档2s native实验：体wz请求0.1/0.25/0.5/1.0，IMU观测转角0.01909/0.07306/0.15470/0.36901rad。四轮接触与warning0；前三档峰值1.533/3.833/7.665Nm均低于12Nm。
- 下一候选只改J100 RPP max_angular_accel=10，避免旧2导致每次仅0.1rad/s起步。diffdrive实际加速度限2、最高速度、摩擦、力矩、180s和所有物理评分不变。实际ROS闭环尚待E验收。
- 根在独立135/9105运行旧FishBot clear回归，确认新增可选launch节点没有改变默认运行；最终原生4、3.6761m、碰撞0、位置误差0.04634m、停稳2.406s，passed并清理。

## E最终闭环

- J100-E passed：task `be26eb78-028e-45c8-8f50-c78072d650ab`，native `4e642b38053d47fdb1763c9d19b2e243`，原生4/route_completed。3.9085068m、2539真值帧、50859接触物理步、碰撞增量0；最终位置误差0.0598009m/偏航0.115465rad；连续停稳2.4899s，最近物理几何余量0.06003m。全部独立检查通过且cleanup=true。
- E只读命令/传感器证据保留65.414–113.488源秒，覆盖返程转向及末转。三层cmd13组同stamp交集，标准IMU与融合odom保留实际源时间；不声称65s之前也采到、不把转发当控制器消费。CM窗口无消息不等于证明整轮没有保护介入。
- 仅RPP请求变化上限改为10，四轮物理、轮控加速度2、速度/力矩限、足迹和评分保留。原0.1rad/s请求弱响应由冻结native对照定位；真实gyro融合纠正旧轮式yaw偏差。
- 新界面审查修正了『头部passed但案例缺失/失败』误绿；有效其他案例保留。人工破坏源YAML使地图评分unknown，不使整批崩溃。
- 根定向工具测试56项、任务桥118项、前端相关30项通过；最终tsc+Vite构建通过。只构建fishbot_mujoco成功。既有Browserslist陈旧与chunk体积提示保留，未混同为功能失败。
- 三项最终报告位于私有`~/.cache/fishbot/hardware-lab/latest/report.json`，聚合real-a、jackal-e、suction/root-e，共7个实际案例。原生物理报告、A–D失败及旧成功均保留；负压补说明不改原始case/参数/判定。
- 负压边界补充：机壳仅视觉/惯量、四轮参与碰撞；失压掉落不验证机壳撞击或整机防护。本轮无CFD或真机推断。

## 交付检查

最终工作台9项复核通过：三个分项7个案例真实通过，J100原task/native UUID/终态4显示准确；显式GET一次、初始0次、零写入、零页面异常，390px无横溢。根独立GET读回与截图核对一致。旧12项浏览器证据保留，新截图位于私有hardware-lab/browser-qa/final。

实验端口9102/9103/9105已关闭，5188只读成果工作台保持可访问。根独立发现ROS域132/133/134/135均无节点，退出确认见本任务清理回执；仅ROS_LOCALHOST_ONLY弃用提示，未改网络设置。远端源码由根串行推送并读回，不改网络/VPN、原实车或其他ROS域。源码/输入/运行记录均留原路径，不把私有地图、日志、环境和编译产物纳入Git。
