# 协同长流程编排薄层

## Goal
复用现有 `/coop-api`，串行执行两个逻辑搬运，合成洗衣机 readiness 延迟到达。保留 batch、machine、事件版本、动作 UUID、episode 与取消/重置记录。

## Constraints
基线 `aab0da45a45ac3e380d0afe538adcfae59c22537`。仅独立 worktree `fishbot-workflow-20261014` 与 `codex/workflow-20261014`。不改 bridge/core、主区 dirty 实现、SpatialLM、共享 Wiki。不得启动 ROS、MuJoCo、GPU、服务或实机。

## Scope
单步 CLI、领域状态机与有界 run；复用 `fishbot_simulation_suite.write_json` 原子替换、标准 `flock/fsync/urllib/UUID`。run 每轮短持锁后释放，等待另一 CLI 的 ready，timeout 1–1800 秒、poll 0.1–10 秒。超时只退出编排器，保留原执行端与任务状态。动作意图先同步落盘，再一次 POST；不重试 POST。原 ID GET 对账。失败在终态与 quiet 已知后显式恢复，新 UUID 留原失败。未知或缺历史封锁下一步。

单货物场景：前 job 实际终态且 `reset.available` 后，显式提交 episode reset。原 reset ID ACK、新 episode 与旧任务 history 一致，才放行第二 job。此流程不代表同一 episode 两货物库存或真实纺织品处理。

## Acceptance
- 两搬运合同：ready 延迟、容量一、batch 身份与事件 ID/连续版本。
- 提交前断电、丢 POST 回执、取消丢回执与重启：原 ID 查询，无动作重放。
- 乱序、冲突重复事件、缺原任务 history、未知终态：封锁。
- between-job reset：terminal/quiet、同 ID ACK、新 episode、保留旧历史缺一不可。
- task failed/canceled：显式恢复；原 attempt 与原因保留。
- CPU 合同回归与 CLI readback，不能代替 ROS/物理验收。

## Phases
1. 接口核对与独立边界：complete。
2. 薄层实施与 CPU 回归：complete，36 项无跳过。
3. 独立审查与 scoped 交付：complete，根独立36项与源SHA核对通过，特性分支远端读回一致。
4. FishBot owner 串行整合与物理验收：pending。

## Next Step
根在原生 queue 可接续后交 FishBot owner 串行整合，执行隔离实际运输与独立 oracle 验收。
