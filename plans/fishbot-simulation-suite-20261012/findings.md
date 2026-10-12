# 核对结果

passage 仿真已有 domain 96 合成36cm门口、独立真值、共享足迹/碰撞区域、连续目标和守卫事件回放。批量入口只需组合已有执行器、场景参数和报告，不另建导航框架。

现有 `verify_stack.py` 使用 domain93，并检查独占速度发布者。批量套件须保持 domain 隔离，不能误接用户现有 baseline。

现有 Goal 客户端默认守卫异常即取消；运动断流恢复演练需要核对 tolerant 软暂停与客户端监控的关系，不能仅改场景就假定会恢复。

Collision Monitor 状态没有扫描编号与时间戳。事件与最近扫描是异步关联，报告不得声称精确同步的触发帧。

## 已核对的复用边界

复用 `verify_stack.Probe` 的真实 MuJoCo 位姿/速度与旧命令探针，`wait_ready.Readiness` 的生命周期、双时钟、传感器和 TF 门禁，以及 inspection 的轨迹 SVG 和 passage 的触发回放。新增代码限于合成参数、单次扫描 relay、串行执行器和证据分析。

原有 Goal 客户端已经允许 level 1 的 tolerant 软暂停，只有锁存/硬故障才取消。不修改该健康策略。单点选择原有 tolerant BT；连续路线保留原严格 BT，不复制另一份路线树。

Nav2 1.3.13 CM 只有多边形状态变化才发布，无 Header。最近 STOP 不因事件年龄变旧；来源更换、生命周期失效与时钟回退才让观测失效。原始 action_type=4 对应 limit；区域名称 Slowdown 不能替代实际 action 类型。

## 实际运行发现及修复

第一次 smoke 已到达目标并停稳，但报告用启动期约 0.353 秒采样间隙否定运动窗口。已把连续性限定为 Goal 提交前最后一帧至最终真值；保留全记录最大间隙，执行窗口的 0.30 秒阈值不变。新增行为回归区分启动间隙和跨 Goal 间隙。

第一整批 `/tmp/fishbot-suite-20261012-full-a` 为 5/6。取消场景的原日志显示：1791795299.472 action server inactive 拒绝目标，1791795299.575 才开始激活 bt_navigator。服务发现不能证明 ACTIVE。已复用现成生命周期门禁；不以固定等待或重新发送 Goal 掩盖失败。

第二批 `/tmp/fishbot-suite-20261012-full-b` 启动超时并保留中断报告。两个节点交替使用全局 spin_once 无法可靠处理门禁回调；已让 recorder 和 Readiness 持续注册在同一个 SingleThreadedExecutor。单独取消复测 `/tmp/fishbot-suite-cancel-20261012-c` 通过，ready 记录四个 ACTIVE 状态，Goal 被接受后实际移动、取消终态 5 和真值停稳均通过。

第三批 `/tmp/fishbot-suite-20261012-full-c` 为 5/6。路线已接受，但地图服务配置响应丢失后未激活；global costmap 未收到地图，规划超时。原日志有 `/map_server/change_state` failed to send response，地图管理者停在配置阶段。第四批 full-d 主动中断，保留中断与失败 case，不作为整批通过。

最终复用本机 Nav2 1.3.13 的 `autostart_node=true`：只对合成场景 map_server 进行内部 configure/activate，移除另一地图管理者，避免双 owner；以既有传感器就绪事件开始地图和导航。门禁核对五个实际生命周期节点 ACTIVE 和有效地图内容。依据是已安装的 nav2_util 二进制/头文件与官方固定版本 lifecycle_node.cpp；没有自建生命周期重试框架。

第五整批 `/tmp/fishbot-suite-20261012-full-e` 为 5/6。变化门宽场景在发 Goal 前就绪超时；Nav2 manager 的 `planner_server/get_state` 请求发送失败，中止 bringup。1309 帧真值最大速度约 0.000155 米/秒，最大位移约 2.36 微米；无 Goal、motion 或 ready 文件。门禁阻止了未激活导航任务。其余五场景的动作、真值、断流恢复、取消和旧命令检查均通过。

新增一次有界冷启动：只针对尚未创建命令进程、已完成清理且真值证实静止的 readiness timeout。失败尝试单独保留；已发任务或缺证据不重试。报告列首轮通过、最终通过、重启次数与全部实际耗时。这是 suite 的启动恢复，不是 Nav2 生命周期框架或任务重发策略。

最终整批 `/tmp/fishbot-suite-20261012-final-f` 首轮6/6通过、零启动重启，总耗时276.958514秒。七项运行源码SHA与最终源码一致。首轮36厘米窄口在终点附近有0.240秒内部停顿，未在门口停顿；变化门宽与单Goal三点路线无≥0.2秒停顿。断流0.920765秒后恢复原扫描，真值停稳0.560秒，原Goal继续成功；移动取消终态5，随后停稳6.162秒；命令超时0.610780秒刹停，十秒旧命令漂移约6.14e-11米。早期批次原文件不修改。full-a运行期间runner有后续修订，不能声称对应最终源版本。

一次冷启动恢复分支由离线边界与报告测试覆盖；本轮实际整批没有触发该分支。未来可进一步核对启动静止证据的双时钟推进和末次年龄，避免只用两帧有限但冻结的静止数据判断完整观测。此项不改变本轮持续推进且新鲜的实际真值结果。
