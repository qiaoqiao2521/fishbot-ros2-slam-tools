# 协同日志容量修复

## Goal
解释已清理的90GB物理日志增长原因，并消除默认无界写入。演示诊断与独立验收证据采用不同容量策略。

## Scope
- 旧cooperation/session-20261014目录本轮已不存在；当前cooperation约2.1MB、FishBot缓存约8.9GiB。不再删除历史文件，不重启121/122或改网络。
- 默认演示不创建physics.jsonl；显式记录采用2Hz墙钟限频、stdlib RotatingFileHandler，默认8MiB×4部分，合计32MiB。诊断不是完整证据。
- 独立observer保留逐条采样，仅去重重复manifest；默认900秒/1GiB硬预算。达到预算或写失败明确结束采集、保留原行、标记不完整，评分不得通过。不修改物理或时间门槛。
- 保持ROS状态消息与source合同、原UUID和评分所有权。原始证据不轮转；旧离线报告的未声明预算不伪称本轮已验证。

## Plan
1. 只读核对当前文件/进程fd、bounded历史抽样和所有写入入口。root + audit_nav_contract，已完成。
2. 最薄滚动诊断记录器与测试。native_backup，仅新recording模块及测试。
3. 独立证据预算/静态manifest去重与测试。audit_nav_contract，仅新evidence模块及测试。
4. root串行接入sim/launch/oracle，更新既有反馈入口，做真实隔离ROS短时验证，不发送动作。
5. root审查、反馈回归、文档/知识收尾、提交推送既有远端。

## Acceptance
默认launch不传--state-log；显式诊断限频且总字节受限；完整observer不静默丢采样，超限/IO失败在最终评分拒绝。相同源/时间/序号、首份完整身份与原ROS消息保持。新日志只在新临时目录创建，121/122原进程保持，所有保留项与验证边界写清。

## Status
completed：实现、独立审查、验收与Git交付完成。实施提交e9f36d6已推送既有远端并读回一致。没有新增动作、删除历史文件或重启原服务；滚动诊断与原始证据的限制分别保留。
