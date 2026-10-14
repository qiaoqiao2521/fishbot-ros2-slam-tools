# Progress

## Current
软件薄层实施、36 项 CPU 合同回归、根独立复审与特性分支交付完成。根已通过 Codex 内部协作向原 FishBot owner 投递交接。main 整合与实际 ROS/物理验收仍 pending，由 FishBot owner 接续。

## Done
- 已读项目入口、SpecMesh v1.1、现有 action/reset/history 与原子写入工具。
- 当前主区仅只读合同参照；未复制或修改 dirty 实现。
- CLI 包含 init/event/status/tick/dispatch/cancel/reset/recover 及有界 run。两 job 自动成功路径、短锁外部事件、超时保留原动作、unknown/fault 封锁已由 fake clock/sleep 定向回归。
- 独立审查复现并闭合 scope 键集、source=None 和慢 GET 超预算后新 POST 三问题。根在最终源下独立重跑36项且起止SHA一致，最后 preflight 无intent首次发送分类也已读回确认。
- 当前证据 `/home/muqiao/.cache/fishbot/workflow/acceptance-20261014-v2/cpu-acceptance.json` 与同目录 `cpu-tests.log`：36 运行、失败0、错误0、skip0；4执行/校验源前后 hash 一致。旧 v1 的32项证据保留。没有 ROS/MuJoCo/GPU/服务/浏览器/实机运行。
- workflow 源 SHA `582f979da1c7a70ee5558be48019e8d0502e6e280fa6a4783882683e8a3a2ae4`；tests SHA `8836bed9c13fc1299019dde319373a0c01b8ddf58569705e428aeaef5bd93f91`。
- 代码 commit `3aa3f61a4c5d55a5bc71fede33ee75922bd0c6d4` 已推送 `qiaoqiao2521/fishbot-ros2-slam-tools` 的 `codex/workflow-20261014`，GitHub REST ref读回一致。身份 `qiaoqiao2521/238822818`、既有repo `1381244533`、fetch/push URL与原public可见性均核对；未推main、未创建PR。代码提交仅6模块文件，独立worktree当时clean。
- 根交接回执：已用 Codex 内部 `send_message_to_thread` 向原 FishBot owner 投递候选 `85e9e07aa5e2347cc19c52c066feb69c89ae2272`、最终源码 SHA 与36项根独立测试证据；工具返回预期 threadId。投递不等于 owner 已整合或物理验收通过。

## Remaining
FishBot owner 负责串行 main 整合及隔离实例实际两次运输、原生终态、between-job reset、取消/重启对账与独立 oracle 评分。CPU 成功不是整体实施验收。根负责跟进已投递的 Codex 内部交接。

## Issues
基线没有 cleanup/native_actions 公开字段；复用已有 reset.available 门禁。主桥历史截断时缺任务 ID 必须 unknown，不修主桥。
reset 本身失败或拒绝保留原 ID/receipt，交 FishBot owner 审查，不自动生成第二重置请求。编排器重启不包含 bridge 重启恢复。
已纠正 queue 适用范围：当前 Codex App 对话、线程与内置子 Agent 属于内部协作，直接复用已有工具接续；无需 queue 迁移或重开。原生 queue 仅适用于 Paperclip 等独立外部系统回传。依据当前共享 `~/.agents/AGENTS.md` 的“外界 Agent 协作与原生队列”，不再以外部 queue 接入状态阻挡本模块内部交接。

## Next
FishBot owner 接续已投递候选，串行整合与物理验收。运行入口 `docs/COOPERATION_WORKFLOW.md`；CPU最短入口为其中 unittest 命令；不启动当前107/114。本次仅修正文档，源码与既有测试证据保持。

## Knowledge closeout
`already_covered`：原知识页的提交边界原则已采用。新增领域经验候选由根决定；不编辑共享 Wiki。
