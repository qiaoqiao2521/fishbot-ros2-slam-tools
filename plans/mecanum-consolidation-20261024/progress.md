# Progress — 麦克纳姆合并

## Current

P2本轮交付完成：共享MuJoCo/Jazzy/Nav2/SO101、原owner/oracle下，运动16/16、短停靠和完整E轮B→A2/2通过。1755项原反馈回归、生产构建、局部lint及桌面/手机检查通过；有效源码与报告串行整合，Git发布以最终提交及远端读回为准。P1下列证据保留，与P2范围分别解释。

P1历史范围：2026-10-24运行包迁入FishBot独立工作区，根CLI和/results底盘接入面板完成。原驱动/配置与九月修复已整合，保留Apache来源与旧目录；没有地图、会话、旧构建或嵌套Git。该阶段尚未实施MuJoCo麦轮模型；后续P2结果见上。Git修订与发布由仓库历史及最终远端读回核实。

## Verification

- P2 `mecanum-simulation-20261024/motion-a`：MuJoCo3.3.7共享Physics完成空载/载货各8例，正反直行/横移/旋转/斜行/弧线16/16。驱动仅作用四轮铰链，滚子被动；非地面碰撞0，载货500Hz接触缺失0，均停稳。横移真值约.0507m/s（请求.06），6秒编码器端点差约18.2mm；保留滑移，不称零误差或Nav2全向运输。载货初始放托盘，仅为接触面板，不替代双指交接。
- P2 nav-native-a因缺imu_link启动失败，补齐共享静态TF合同后b通过：check1e8f42ad-f2db-48a1-af7b-97aa20d6ad04，146/9116，48.080墙秒；staging/default UUID均4，原生DDS不同发布GID确认消费。位移.21770/.24511m，真值XY.02795/.03298m、yaw.00388/.01276rad，禁碰0、连续.7源秒静止及owned清理通过。72合同检查通过，1项ROS环境条件跳过；8项前端profile及后续20项局部检查/生产构建通过。实际页面桌面/390px、真实146状态/解码帧/配置导出通过，0写请求/0页面异常。
- P2 delivery-a未启动动作：当时shell缺用户DBus环境；显式连接本用户既有/run/user/1000/bus后b运行。b保留完整失败：B入站、双指抬升、释放落稳/home通过，直接离站路线RPP预测碰撞而status6，A未派发；153.575墙秒/路线20.929秒，评分失败，owned清理完成。后续宽麦轮配置复用现成DriveOnHeading直线离站，不放宽原碰撞或时间门槛。
- J100精确margin差异在未修改HEAD的profiles/scene源码同环境复现：.02565237m大于原.01984143m。测试改为保持原净距下限，未改几何或物理评分；不将差异归因本轮麦轮分支。
- P2 delivery-c在原生精停靠阶段预测碰撞（905），尚未执行离站；37.882墙秒失败、A未派发，未据此宣称离站补丁有效。静态原图足迹无重叠，但原生预测/定位存在边缘差异，不能将其等同真实接触。候选将车体横移+.04m、托盘相对-.04m，保持交货XY=.24/.14；新增实体支柱与壳体重叠10mm。过重100mm实心支柱的motion-b四项横移1秒停车失败保留；改40×40×80mm铝柱，按2700kg/m³计.3456kg后motion-c16/16通过，原阈值/1秒停车保持。factory-scene-e完整几何扫掠余量.025652m通过，先验短停靠再完整运输。
- short-dock-a原独立评分通过，原Dock UUID07d8fe1f90e54074a8cc937290976f84状态4；停稳误差P95=.02076m/.02393rad，.7源秒连续与清理通过，64.258墙秒含启动/评分。随后完整D遭记录IO失败，独立评分false/物理未评；owner另因固定指未退出而release等待失败。D保留实例已由fresh ROS UUID终态＋.72源秒quiet独立回收，原报告不改通过。过渡修复的177项core/oracle检查通过，最终物理门槛保持；随后以D真实grasp帧原生重放，再执行/tmp新完整验收，结果见下。
- D真实grasp帧原生重放`release-replay-a`：同计划、同状态，旧过渡停在固定指.189N，未退出；新过渡退出后两指0、原最终handoff成立，车/臂禁碰0。只证明该过渡，不充当完整任务。E轮原生run94ed2798-319b-4eee-a762-8d55e71efb4e随后完整通过：B/A原K和目的地2/2，232.320/230.112墙秒、路线35.241/22.042秒、末XY.020643/.022463m、yaw.000317/.003425rad，连续终点静止2.60/2.56源秒。
- E沿原360/120/1000预算，2start/1reset/0cancel、全轮540.261墙秒。原生载货离站和Nav2 UUID均4；双指、实际抬升、释放落稳、home、同货物运输与禁碰原评分通过。选定运行源码起止文本一致、manifest输入一致，owned进程/端口关闭，原配置保护单位前后一致（当时均未运行，不称保护了活实例）。
- E为开放通道、2D、ideal工位观测；停车保护介入B/A=.88/.40源秒，原物理序号缺38/28，缺口不插值。不同于旧J100占用通道，不做跨车型A/B增益或纯视觉/真机结论。3D配置prepare与5760真实射线/独立查询保持plant测试通过，完整3D麦轮配送未执行。
- E两单原记录离线复算均通过。第二单首个复算因传错reset回执路径保留score-error；改用原reset请求对应文件后通过，未改原运行或评分。记录与代码仍在`/tmp/fishbot-mecanum-20261024/`；私有持久归档`~/.cache/fishbot/mecanum-simulation-20261024/delivery-e.tar.gz`约72MB，已读回原result的2/2与两score成员，原始文件未删除。
- 同一报告合同导出2案例、0缺项，原J100 public JSON未覆盖；前端记录选择器与车型草稿共用现有页面。实际桌面/390px旧K＋新麦轮切换、异常保留、下载检查11组通过，写请求/页面异常0，测试浏览器关闭。既有组合回归首轮control180秒超时，其余mission209/autonomy61/frontend460通过；control原组直接1025项151.410秒全通过，随后复跑原组合入口，不放宽原测试时限。
- 最终原组合入口复跑通过：control1025、mission209、autonomy61、frontend460，共1755项，无失败/跳过/缺失；原180秒时限未改。首轮超时保留，不能称从未失败。当前生产构建和8个改动TS/TSX文件lint通过，73相对链接存在，diff无空白错误。最终浏览器11组再通过，桌面/390px与0写请求/0页面异常、owned浏览器关闭；Vite5191只读报告预览保留，9116及ROS实验均关闭。
- prepare历史失败a缺IMU sensor容器、b缺胶囊冻结几何支持均保留，修复后c及带两目的地factory-scene-a生成72/70/10自由度/控制布局。最初合同失败包含未source Jazzy的diagnostic_msgs、旧Physics测试对象无新属性；后者已兼容。新测试序列化list误用tolist已修正。J100旧精确margin断言差异的HEAD对照结果见上，未调整原评分。
- 最终回归、原生release重放与浏览器证据另归档为`~/.cache/fishbot/mecanum-simulation-20261024/validation-final.tar.gz`；已读回原反馈passed及浏览器11项通过，归档权限600。原物理E包与该验证包均留Git外。

- 包发现为一个robot_base；独立colcon构建通过，输出`~/.cache/fishbot/mecanum-build/`。drive与minimal的show-args解析通过，未执行硬件launch。
- 真Jazzy节点在独占domain181、内核伪终端上验收。pty-a先复现重连漏开反馈；最小补丁后pty-b八项通过：启动归零/回传、前进/横移/旋转、超时停车、MSPD→Odometry/TF、非有限指令归零、看门狗重连恢复回传。实收vy=.05、vx/wz=0，反馈为测试合成，不是车体真值。原失败与成功报告位于`~/.cache/fishbot/mecanum-import-20261024/`；节点、线程、PTY均清理。
- 3项合并行为测试与7项耗时导入测试通过；前端4文件18项、TypeScript/生产构建与新增文件lint通过。布局检查0失败，98处相对文档链接存在，diff检查通过。
- P1归档时既有反馈入口：control987项中7项因旧planning-venv/bin/python缺失失败；mission209、autonomy61、frontend入口460项通过。P2恢复环境后的最终1755通过见上。这里保留历史边界，460不称全前端测试全集。
- Playwright桌面/390px共10组行为通过，增加三车型入口与麦轮待接入边界检查；写请求0、页面未捕获错误0，测试浏览器已关闭，截图在`ui-b/`。只读Vite5191保留供查看。
- 外层dev工作树有既有大规模迁移和独立Git，未整仓stage或发布；本次有效运行代码只交付FishBot既有远端。旧robot_base九月dirty保留历史，后续维护以新包和本PROJECT为准。
- 功能提交fff8227连同耗时页4ebb08c已推送qiaoqiao2521/fishbot-ros2-slam-tools的main，远端读回与本地完整提交一致。后续文档接续修订由Git历史保留；提交推送不替代上述验收。

## Knowledge Writeback

knowledge_status=updated。采用FishBot§19/20；在原`Wiki/ROS2 与 FishBot.md`第20节新增“放货退出：过渡条件和最终交接分开”，同步`Wiki/开发知识入口.md`触发词，并已读回两处正文/锚点。来源为原SO101实时release分支与同帧原生对照。只写机制与边界，当前状态留项目；知识库既有dirty保留，未整库stage或推送，owner=root。

## Next

本轮完成。后续继续复用同一车型/传感器/任务配置与原owner/oracle；连续世界M1b以后、全向Nav2与完整3D麦轮运输保持各自未验范围，不自动派发，owner=root。
