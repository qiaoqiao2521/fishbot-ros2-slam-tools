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
