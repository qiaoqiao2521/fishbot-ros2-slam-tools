# 进度

## Current

原三分项与旧FishBot往返已通过并推送ba03c62。新增P5同一整车地面→墙面连续转接已通过根独立复跑与半步长复验，原地面/墙面分项不代替本轮结果。本轮无ROS运动。

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

## P5进行中

- 根：接口整合、SpecMesh、独立物理验收、视频、报告/Git；串行维护共享文件。
- transition_physics：私有cache先验证完整四轮/碰撞机壳与原生吸附，暂不改旧suction输入。
- transition_review：只读官方接触语义、可复用机制与评分复核。
- transition_workbench：固定只读MP4入口与条件视频展示，保留旧三分项。
- knowledge pending：根据真实转接结果判断可复用增量，owner根；不把理想轮式接触说成真实负压密封方案。

## P5实际验收

- 源码由physics冻结后，根root-a独立复跑两例/render：ground_to_wall passed/task_motion_success=true，episode `20dc7080-59dc-4735-b563-cdf79baed576`；pump_off expected passed/task_motion_success=false，episode `4d1ea312-a646-4e83-b3c4-b7a7f218a8bb`。各901行，source0–18s，最大采样间隙0.020s。
- ground_to_wall：初始承载0.04s，交接4.50s，全轮墙面承载/离地8.52s；之后爬升0.31742075m，末连续停稳4.50s。最大轮矩10.51327Nm<12，接触穿透0.509mm，外加body/generalized force0，native warnings0，机壳支撑0。完整机壳碰撞启用，模型18.431kg、4hinge、自由体、0equality。
- pump_off：全程压力/实际吸附力0，未四轮全上墙，物理任务未完成。实际机壳接触峰643.679N保留；只证明关闭吸附的负控行为，不称取消/防护成功。
- half-a仅把dt从0.0002改0.0001，normal再通过，爬升0.31730670m、停稳4.50s，差0.114mm；源18s/901行与阈值保持。这是步长复验，不叫新策略改进。
- 独立reviewer解析原模型、审查AST无运行期状态/外力写入，并从formal-f、root-a、half-a完整JSONL再次score，和根结果一致。
- 根实际查看root-a初始/俯仰/保持三帧，完整车可见。ffprobe H264640×480/15fps/271帧，视频18.066667s，源18s含末帧；固定GET200/video/mp4，原生源速。
- 根31项Python定向检查与前端最终16项定向检查通过，tsc/Vite构建通过。原源码/五负压分项未改；wrapper、聚合与条件播放器兼容旧入口。
- 旧报告real-a、jackal-e、suction/root-e保留，加P5两例聚合共9例。媒体单文件固定读取，不开目录、不启动ROS。后端原runtime离线不影响只读报告，也不冒称全部服务在线。

## P5知识状态

pending：候选为MuJoCo吸附跨接触分力、角点后腔排气和承载接触/近接触的区分。原Wiki/ROS2 与 FishBot.md与开发知识入口.md已存在其他未提交修改，归属未核实，本轮不覆盖或混合提交。候选与来源先保存在本项目findings；接续owner根Codex，最短入口为本计划findings的P5实施结论与tools/fishbot_ground_wall.py。未宣称共享知识已写入；本轮是单一理想机构，不推广未标定硬件参数。

## P5最终工作台与交付

- 根独立实际GET验证前缀/后缀Range均206且16字节，越界416/Content-Range正确；播放器通过成熟send1.2.1读取固定单文件。
- 最终浏览器9项通过：3分项9案例、负控任务false、默认零视频预取/自动播放、实际播放超过1秒、解码640×480/18.0667秒、seek10秒实际帧可见、390px含展开指标无横溢、零写请求/页面异常。根回读result.json并查看实际10秒截图。旧全文件200导致seek失败证据留failure-before-send.json。
- 最终前端16项定向测试、类型/lint和生产构建通过；根31项Python定向测试通过。shell与diff检查通过；未增加ROS节点，所有本轮physics/ffmpeg/浏览器进程已退出，只保留5188成果工作台。
- 物理生成器、评分器和默认物理参数在正式root-a与half-a期间冻结；随后网页发送层修复不改变物理；不同dt使用独立私有JSON，原输入未改。旧三项报告与源码不改；私有地图、视频、JSONL、venv和编译产物不入Git。根按既有main/qiaoqiao2521远端串行交付，确切版本以本任务Git回执为准。

## P6进行中

- User：补真实密封与新增泵阀重量建模。根负责可选hardware候选集成、实际回合、工作台对照和Git；旧P5理想结果保留。
- seal_model：独立裙边几何/原生间隙采样/连续泄漏helper与局部测试。
- pump_hardware：厂家证据、固定硬件实体/质量惯量、单泵共享气路helper与局部测试。
- 已查明P5每轮面积不符合原胎几何，不能将其通过视为真实吸附轮可制造性。新候选允许上墙失败，结果以实际新输入独立评分为准。

## P6 实际验收与边界

- P6降阶建模完成；整车爬壁任务未成功。两helper/配置/局部测试与根集成已交叉审查；仅根串行改共享SpecMesh、聚合与Git。没有ROS、实机、CY或网络/VPN操作。
- 首轮hardware-a完成两例：normal failed，negative expectedpassed/taskfalse。原生接触probe随后发现lip摩擦/柔顺被混合覆盖，before/after回执位于私有seal-model-20261020目录，首轮完整保留。
- 最终hardware-b使用修复后的同一冻结源码/配置，两进程互不共享native状态。normal episode `1693aed7-cfdc-43d4-8eb8-e791f542166d` failed；negative `09568bf0-7d2b-4b83-accf-482a55038e0d` expectedpassed/taskfalse。两XML完全一致、四pad执行器后四drive；完整0–18源秒/各901行，最大gap0.020s。独立reviewer从完整JSONL重score一致，无qpos/qvel/xfrc/qfrc写入。
- B有泵峰8kPa/每pad30.787608N、轮矩10.248453Nm；负控压力和吸附全0、轮矩9.976646Nm。两案最大穿透0.509177mm、warnings0、外力0、机壳及携带硬件支撑0。实际64个lip priority1、摩擦.05、solref.02，与原声明匹配。没有交接、全车竖墙、额外爬升或墙上保持。完整压力8kPa仍不能上墙，不能把结果包装成漏气已修复或成功爬壁。
- mass19.823910629kg、新增1.392910629kg，质量/重心由原生模型回读并与独立计算一致；真实气腔/管容已进入network。压力、轮矩、时间与独立任务评分均保留。无泵仍有阀额定电耗，不把系统功耗当纯泵实测。
- 根当前52项Python定向检查（20ground-wall/7聚合/25真空模块）全过；前端18项、定向lint、tsc/Vite生产构建通过，仅原Browserslist与chunk提示。原ideal-regression实际18s再通过，爬升0.317420748m/停稳4.50s，旧成功无丢失。
- 原生渲染B录像H264640×480/15fps/271帧、源18s/播放18.066667s。两model-views静态图来自同一B XML，仅隐藏世界表面观察结构，不冒充运动验收。
- 最新工作台保留原9案例，加硬件两例共11例；suction状态failed，旧成功和负控区分。固定两段录像分别命名，成熟send/Range入口兼容。源码配置/文档入库；私有地图、JSONL、录像、Python环境和浏览器截图不入Git。

## P6 知识回写

pending：候选为原生接触参数混合读回、实际多边形ray/气腔体积、native actuator标量与实际施力的区别。已在本项目findings保存可复用结论。共享知识页 `Wiki/ROS2 与 FishBot.md` 与 `Wiki/开发知识入口.md` 当前仍有其他未提交修改，归属未核实，本轮不覆盖或混合提交；接续owner根Codex，最短入口为本计划P6 findings和三份helper/native测试。未声明知识库已写入。

## P6 最终工作台检查

根对B报告/录像重新执行实际浏览器9项检查：11个原始案例、保留旧成功、新候选失败、负控车辆任务false；显式读取一次、视频零预取；实际解码640×480/18.066667s、播放超过1秒、seek10秒可见真实帧；390px无横溢、零写请求和页面异常。根实际查看桌面截图，失败车辆位于墙前。最终媒体来自B，未用A或旧成功录像替换。只保留既有5188只读工作台，本轮physics、ffmpeg、隔离QA进程均已退出；原项目runtime离线不冒称全部ROS服务在线。

共享知识状态仍为pending；本项目三文件、PROJECT和运行文档已读回，5文档相对链接无缺失、diff检查通过。源码与原始输入在B回合中未修改；随后仅更新文档与私有聚合/媒体。确切Git交付版本以本轮提交回执为准。
