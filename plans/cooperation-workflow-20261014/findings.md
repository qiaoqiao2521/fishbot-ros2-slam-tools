# Findings

## Existing contract
`start` body 为 `task_id/episode_id/issued_at`；`cancel` 为原 `task_id/issued_at`；`reset` 为 `request_id/episode_id/issued_at`。基线不接受 `scope`；当前 dirty 版才接受显式 scope。两版默认均为完整运输，薄层使用基线最小键集。`state` 忽略 task_id query；其 history 仅最近 10 项。按 ID 与 episode 检索，缺失不推断未执行。

基线未公开 cleanup/native_actions，当前主区 dirty 版有。原 `state.reset.available` 内部核对任务非 ACTIVE、worker 结束、原生 dispatch 终态、car_hold、guard 关闭及车臂货物 quiet。薄层跨两个版本使用该现有门禁。桥接进程带旧账本启动保护保持；恢复只针对编排器，不能借重启桥接器接管未知动作。

## Reuse and knowledge
复用 `fishbot_simulation_suite.write_json`，原子 replace 后同步 final 文件和目录，完成提交前稳定写入屏障。标准库 HTTP 不自动重试 POST；标准 `flock` 保证同账本只有一个 CLI owner。无需新调度、认证、ROS 协议或通用服务。

采用 `Wiki/自动化开发范式与智能体协作.md#远端任务恢复：先确认提交边界`：仅提交次数零的明确未发送才能首次发送；尝试后只恢复查询。替身回归证明应用层不重放，不能声明服务端恰好执行一次。

## Model boundary
Laundry readiness 为合成领域事件；刚性货物复用现有物理场景。消费混合衣物与商业标准床单的几何/材料差异不在本模块实现范围。容量一与 batch 身份属于软件合同，物理库存仍为每 episode 一个自由货物。

## Review corrections
独立审查复现基线严格键集拒绝 scope，已删除。原请求校验器直接进入 CPU fake API 边界，防止宽松 mock 漏检。基线 fresh 断流时合法 source=None；薄层先检查 source 类型，再把断流落盘 unknown，恢复后只对账原 ID。两项原复现独立通过。reset 后旧 consumed ready 清空，但事件 ID 与 version 保留；失败 retry 也必须新版本 ready。

run 只循环本 workflow。fault/unknown 立即返回，不隐式 recover；成功路径自动处理 ready、原 ID 轮询和显式配置流程内的 between-job reset。单步 reset/recover 保留供调试与故障处理。runner deadline 不取消原任务；HTTP 每步有固定 5 秒 timeout，退出时刻可被当前一步有限超出。

独立 run 审查复现慢 GET 越过 deadline 后仍 POST。已在 start/reset 的 intent 前及同步后 POST 前检查预算；原复现零 POST/零 attempt，intent 后超时也零 POST并保留 unknown。预检失败但从未生成任何意图，保留 waiting_ready 与 blocked_preflight；此有证据的 unsent 可以恢复首次提交，不可套用于已尝试动作。旧 v1 证据保持，不冒充新版运行。

## 实际桥端与采集边界

新runtime源与独立接收每20ms推进，但桥缓存落后0.28源秒，原门槛触发取消；没有物理源暂停的证据。分段计时尚待确定readiness/锁/调度具体阻塞点，不预设根因。普通HTTP reset ACK缺源reset_stamp，不满足现有oracle；独立ROS reset_result与新episode physics的原源时间须绑定后再开始采集。两次运输尚未通过，取消与原ID恢复证据分别成立。

## 第二轮诊断：桥Clock落后，不能归为同一个缓存原因

`runtime-20261015-a82c8b55`在冻结14a6daf下执行。独立可靠ROS reset_result、原physics reset_stamp、新episode和采集起点绑定通过。移动Dock原UUID取消与独立quiet/cleanup通过；job1在准备Nav失败，job2未派发。完整评分仍false。

失败wall1791996994.829836时，桥clock74.5、raw physics74.82，source age为负0.32s，接收龄约3.57ms。独立observer在此前5.277ms收到clock74.84、此前2.084ms收到physics74.84；原Clock每0.02源秒持续更新。失败附近已测physics全callback1.266ms、readiness0.165ms、锁等待0.000792ms；旧episode的0.107s HTTP慢事件发生约56秒之前，不能作为本次原因。

安装版rclpy7.1.12的标准TimeSource创建`/clock`时未指定callback_group，因此和桥的ActionClient等实体共享默认MutuallyExclusive组。四executor线程不会绕过同组互斥。这是结构证据；具体占组callback及DDS排队尚未证明。候选仅以公开create_subscription透传原标准Clock callback到专用互斥组，不复制时钟、改vendor或改物理门槛。实际阻塞probe和唯一订阅/QoS读回后才进入新物理面板。

受控实际ROS probe `clock-group-controlled-20261015-c32d691b`通过。默认组busy callback持有0.759191墙秒，实际publisher20条推进0.634229源秒；shared Clock零推进，专组与独立witness精确匹配末戳，释放后全部同步。四节点destroy、executor停止、spin退出和新context空domain120读回通过。标准TimeSource.clock_callback与depth1/BEST_EFFORT/原QoS一致。根核对script SHA、publisher/witness原件和receipt SHA `dd61b6aca40652d69b28354a7ca26277e93c8be447c761de10d3ce0185fcbfae`。

前两probe false原件保留：ac80d0c9的虚拟源推进预期不成立；b49ae70f把成功返回None的destroy_node误计0。新判据绑定实际publisher推进与独立witness，不把墙时间当源时间。通过probe只证明可构造的默认组阻塞风险，不声称复现桥原guard或识别a82占组实体。

第三轮ec879ed下同三case全部通过，原360s完整任务与所有物理门槛保持。两作业之间独立reset源stamp早于采集和派发，原UUID、单货物自由体与完整交接评分通过；只重启CLI，不重启bridge。末账本仍保留一次+0.26s的物理源龄边界诊断和3次拒绝，因此不宣称全部时序异常已解决。新面板使用ideal信标，不能补齐旧RGB留出失败或重写原视觉56例。
