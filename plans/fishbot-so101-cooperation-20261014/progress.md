# Progress

## Current

共享物理世界、ROS薄适配、原生Nav2和网页已实现。静止工位的抓放探针通过；完整网页运输尚未通过，不能算闭环完成。

## Done

- 保留原domain107；独立domain114启动同一MuJoCo世界与Nav2。
- 原SO101规划复用通过，真实自由货物抬升40.806mm；双指约1.45N。货物松爪后由车载托盘四处接触支撑。
- 独立ROS测试验证真实轮速、编码器里程计、过期命令停车和机械臂引用来源。
- 网页桌面入口、实际960像素共享画面、390px触控已验证。
- UI运行中取消同ID到canceled；原生与实际静止评分由独立观察器核对。
- 最终525项组合反馈检查、完整前端132项、39项显式场景/物理/prepare/launch检查全部通过，零跳过；类型、lint与原107域生产构建通过。物理门槛还通过K完整实际任务评分，未用测试替代。

## Attempt B

实际网页派发任务3f6e1858-d71e-4079-a7b7-a292f63c46b0在工位末端转向失败。Nav2状态6，RPP预测碰撞；机械臂没有启动，非预期物理接触为0。

估计XY距dock约1.18cm，真实距dock8.745cm，真实与估计偏差约9.06cm。真实激光与MuJoCo独立重算212束匹配，误差≤1.19e-7m，laser TF一致。当前局部地图估计足迹触碰approach_obstacle栅格；真实足迹与目标足迹均未触碰。正在核对AMCL地图的低台面投影与真实激光高度。

证据：本机缓存fishbot/cooperation/session-20261014/runtime-b、attempt-b-ui及oracle/nav114-{snapshot,analysis}.json。失败不覆盖；不得缩小足迹或关闭碰撞检查以通过。

## Attempt C

双地图已通过原生逐像素与topic读回，两个MapServer与Nav2均ACTIVE，完整避障图SHA与B一致。任务4fe8f572-9074-4d9c-b44e-9bdbf718d7da仍在最后转向以Nav2状态6/错误码104失败；官方未提供具体error_msg。实际XY与估计偏差10.63cm；没有进入抓放。继续核对AMCL匹配得分与传感精度配置，保留本轮失败及markers-c。

## Final source preflight

D只进行了空闲就绪检查，没有派发任务。独立代码审查后补入实际ctrl8/time_s，并分开当前接触与累计step计数；两者任何非预期接触都禁止执行。16项core回归与18项场景/physics/双图回归通过，零跳过。D保留preflight后停止。

E使用最终源与经离线概率评分支持的原生AMCL模型。源SHA、两MapServer与Nav2 ACTIVE、实际AMCL8项参数已独立读回；world/collision geometry未改。即将以手机页面派发完整任务，未宣称已通过。

## Attempt E/F and G preflight

E 的纯激光定位在交接点仍偏差约6.63cm；任务未进入机械臂阶段。F 改用原生 DockRobot 和范围1m的理想化仿真工位信标。首次 Dock 实际运动后取消通过：同一原生UUID终态5、车体原点独立速度确认停稳1.12s。第二任务在短距离预停靠导航超时，没有抓放。失败资料分别保留，不覆盖。

F 暴露两项修正。massless base_footprint 的 `mjOBJ_BODY` 速度参考点为惯性中心，旋转时产生虚假线速度；改用 `mjOBJ_XBODY`，与 `mj_jacBody @ qvel` 及位置有限差分一致，14项回归通过。短途转向未计入 SimpleProgressChecker；复用已安装 PoseProgressChecker，角度阈值0.1rad，原位移0.15m、超时10s保留。

G 使用完整原车圆外廓与实际托盘的28点足迹。固定交接中心不变，调整车停靠位置和托盘偏移，使扫掠净距42mm；保留10mm padding。30项场景/物理/prepare/launch回归通过。独立原生readback确认两个地图、Nav2与Dock均ACTIVE，足迹与参数匹配，速度经过原平滑和碰撞链。G正在进行网页取消与完整运输验收，尚未通过。

采用既有知识 `Wiki/ROS2 与 FishBot.md` 第11节：转向应计入进展，保留超时与碰撞阈值；不能用配置绿灯替代实际位姿验收。

## Attempt G and H

G唯一Nav目标7810c4aebdd842809671b0453fda84c3在物理状态墙钟接收间隙0.707s后取消终态5；桥接无法在清理窗口确认全部新鲜条件，记录unknown。物理积分源时间同期仅推进0.02s，未创建Dock或抓放。独立观察器后续确认车臂静止、hold与零轮控、非预期接触0；失败原件及脚本中断事实保留，未补造成功。

H将物理状态和clock改为标准SensorQoS的BEST_EFFORT/volatile/KEEP_LAST1，桥接与观察器同步。私有116域实测端点与读者暂停后首帧序号跳跃通过；Fast DDS端点查询不提供history/depth，保留未知，深度由实际Publisher元数据核对。17项物理回归通过。保留原源时间、新鲜度和命令TTL；此次QoS调整不证明G停顿由DDS导致。

H复用项目已有compose_navigation_tree，把官方default中的规划分支替换为官方GoalUpdated/IsPathValid条件；其余原生控制与恢复节点逐节点一致，10项prepare/launch检查通过。原生路径有效时保持，目标或路径失效时重算，碰撞检查保留。加入最多32条慢事件的观测计时；它不参与决策。新H源10项冻结、无并发测试，开始网页取消后完整运输验收。

22项任务编排回归已通过，包括错误UUID不触碰当前Nav与Dock句柄。未知任务当前没有自动对账解锁，具体恢复与单回合边界见docs/COOPERATION.md，不声明生产稳定性或全部重启路径已验收。

## Attempt H result and I

H首次实际NativeDock取消仍通过：同UUID终态5，真正车体原点速度峰值0.08544m/s，独立停稳1.60s。第二任务在原120s导航回执超时后取消终态5，没有抓放；完整任务仍失败。源127–137s的有界记录没有新全局plan，证明validity tree已消除周期重规划；AMCL转向后位置偏差8–10cm仍妨碍几厘米短staging。此处不把单一配置修复称为充分解决。

I在staging导航期间提前使用同一1m内有效信标辅助AMCL。新任务若已停稳并处于原生停靠捕获区，直接停稳对准后派发DockRobot；避免先追身后几厘米点位。判断来自唯一、SHA绑定、原时间戳新鲜观测，范围外/过期的可选观测不用于校准；Dock阶段仍严格要求有效观测。实际车辆仍由执行器推进，未更改qpos。25项编排回归通过，包括捕获区侧向/朝向、转动/越界/过期拒绝和任务所有权。I新回合开始实测。

## Attempt I/J and K

I第二次停靠以原生状态6/905失败，没有抓放。原生1.3.13将控制目标外推至真实停靠点后0.25m；完整足迹回放证明预测到该虚拟点会碰工位。设置dock_collision_threshold=0.25与max_retries=0，保留真实进站段的完整检查，禁止原生reset/undock自动旁路。500Hz仿真执行端增加停车平面前1cm轮目标归零保护，原生成功仍为抓放必要条件；动态物理测试确认惯性仍正常积分。

编码器原先积分轮轴中心却发布base_footprint，现用编译模型固定偏移(-0.02,0,0.032)变换位置与twist。原地旋转的车体原点独立误差由16.80mm降至2.02mm；残余滑移保留，没有真值纠正。21项物理回归与11项prepare/launch检查通过。

J网页取消通过：同一NativeDock UUID cb8d49d6e9e145bf91202a25f879fd9d到5，真实线速度峰值0.070813m/s，取消后连续车臂静止1.18s。第二NativeDock UUID 5d8b106f278e44f1b8aa911be61ea9e3到4，真实停车距离18.77mm、朝向误差0.007306rad；使能期间未越过停靠平面，最小沿距17.69mm。完整任务随后在机械臂approach未完成时失败，货物未动、非预期接触0，独立评分明确full failed。

J源223.66至242.32推进18.66s，实际墙钟45.79s，独立clock与physics确认实时因子约0.407。轨迹按源时间推进，但旧段超时按墙钟计算，错误出口提前触发。K改为源时间duration+dwell+20s；关节精度、新鲜度和整项360s墙钟上限保持。增加慢仿真、暂停源与不收敛具体关节回归。旧账本在任何控制发布前拒绝；禁用保护须等新鲜ACK。34项core与启动干运行通过。K将从新episode继续完整运输验收，尚未通过。

## Final K acceptance and current source

K两项独立评分PASS。取消task 1a228406-c566-4505-8806-b64d9b5739e2持有NativeDock 38ba909cc7914a8ba62497eda32bb5b2，实际运动峰值0.111093m/s后同UUID终态5，连续静止1.10源秒。完整task b0eeb2b6-bb1f-46ab-92e7-63a8e763ae84的NativeDock 223c1630f43e40c79865b8126d9f60c4及deliveryNav 21a18e1c8c0344f3b784c249d04aa337均到4。

独立门槛首次通过源时间：dock停稳119.86、双指与25mm以上lift 157.60、完整货物外廓留盘/真实支撑/松指与相对静止193.18、arm home静止201.30。车辆203.68才开始运动；同一货物实际位移1.790841m，车辆1.791690m，留盘违规0，车货终态静止228.98通过，非预期接触0。没有teleport、clock回退、physics reset或多场景身份。GUI完整运输208.344墙秒，只有2次start与1次cancel，390px操作/完成页/只读刷新无异常或自动重发。

独立12635帧physics最大源间隔20ms、缺失序号0，与独立truth/cargo/clock全部对齐。339.739ms墙钟接收孔洞保留；K首任务前source38.10的clock_publish曾耗0.31905s，inclusive publish0.32469s，不能宣称BE完全无阻塞。实际本轮命令TTL与物理门槛通过。停靠保护最小采样沿距14.214mm且没有trip；真正trip属于独立动态物理回归。

K source10前后均匹配，原件快照存runtime-k/accepted-source。K完整验收后精确停止owned unit，再修正常禁用超时进入cleanup时localactive=False漏验actualenabled=True的边界；新增两条对应负例。当前cleanup总验actualFalse/untripped及更新源ACK，不以发送状态解除任务所有权。当前36项编排通过，最终反馈control245/mission145/autonomy61/frontend74共525通过；全前端132、typecheck/lint/build通过。最终显式scene7/sim21/prepare10/launch1共39通过，fail/error/skip全部0，43.963s；测试前后9项源与测试SHA一致。没有在动作期间并发测试或改运行源。

本机完整证据：session-20261014/ui-k-result.json、oracle/run-1791919665149152720/score-1791920037922113535.json、oracle/k-native-guard-end-proof.json、oracle/k-acceptance-summary.md、oracle/final-physical-tests-1791920179971651082/result.json；最终反馈与前端报告为final-feedback-check-current.json与frontend-test-current.json。旧失败全保留，不重评分为成功。

## Remaining

本轮实施与验收完成，无必需步骤遗留。L新episode已同源原生读回ready/idle：7ACTIVE、配置归一化SHA与K一致、source10匹配、完整速度链、车臂货物静止及相机来源绑定正确。390px完整运输归属K；L桌面开始可用、960px实际相机和0POST/页面异常单独通过，没有自动派发新任务。L unit fishbot-cooperation-114-20261014-l.service，invocation 5a6b4f65cbaf471eb1ce7b6a8bb92ab1，报告oracle/nav114-l-ready-report.json和ui-l-ready-result.json。没有新训练、硬件或宇树控制结论。

## Retained work

固件release.sh保留未执行、未提交。具体阻碍：同版BOOT_APP0_BIN缺失、被忽略micro-ROS配置的来源、未固定esptool及merge CLI、4MB板型/分区与tag替换均未验证。接续owner为根Codex；最短入口是先固定Arduino/PlatformIO依赖与boot_app0来源，再在离线构建目录验证分区/合并，不对已售硬件刷写。simulation.rviz的GUI保存已语义审查：原fixed frame、七个Display、Topic/QoS和GoalTool保持；保留zoom与dock布局，只将共享窗口X从-363恢复至30，避免离屏。

## Knowledge closeout

updated：root已修订并再次读回知识库既有 `Wiki/ROS2 与 FishBot.md` 第19节“共同物理世界中，地图、外廓与速度各自对齐”，并同步 `Wiki/开发知识入口.md` 的触发词与段落链接。已读回新段落和入口，内容只记录可复用地图表达、完整足迹、速度参考点与验收边界，后来补入固定编码器参考点、原生虚拟目标/保护回执边界与仿真轨迹时钟预算；阶段结果回源项目，未把原始资料复制到知识库。第11节的转向进展经验已准确覆盖本轮，记为already_covered。

## Git delivery

源码与全部32个已审查文件提交为6972ba4d3049e721f4c802bd543d14854cb9b37a，已推送qiaoqiao2521/fishbot-ros2-slam-tools main并通过GitHub API读回同SHA。有效遗留simulation.rviz一并整合；只有未验收release.sh继续保留，阻碍与root接续入口见Retained work。此收尾记录为单独文档提交；不修改已验收源码或提交任何运行日志/地图/模型素材。
