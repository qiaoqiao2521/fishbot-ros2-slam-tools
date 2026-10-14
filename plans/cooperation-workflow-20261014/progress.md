# Progress

## Current
软件薄层实施、36 项 CPU 合同回归、根独立复审与特性分支交付完成。实际 ROS/物理验收 pending，由 FishBot owner 串行整合后执行；跨对话派发等待根接续原生 queue。

## Done
- 已读项目入口、SpecMesh v1.1、现有 action/reset/history 与原子写入工具。
- 当前主区仅只读合同参照；未复制或修改 dirty 实现。
- CLI 包含 init/event/status/tick/dispatch/cancel/reset/recover 及有界 run。两 job 自动成功路径、短锁外部事件、超时保留原动作、unknown/fault 封锁已由 fake clock/sleep 定向回归。
- 独立审查复现并闭合 scope 键集、source=None 和慢 GET 超预算后新 POST 三问题。根在最终源下独立重跑36项且起止SHA一致，最后 preflight 无intent首次发送分类也已读回确认。
- 当前证据 `/home/muqiao/.cache/fishbot/workflow/acceptance-20261014-v2/cpu-acceptance.json` 与同目录 `cpu-tests.log`：36 运行、失败0、错误0、skip0；4执行/校验源前后 hash 一致。旧 v1 的32项证据保留。没有 ROS/MuJoCo/GPU/服务/浏览器/实机运行。
- workflow 源 SHA `582f979da1c7a70ee5558be48019e8d0502e6e280fa6a4783882683e8a3a2ae4`；tests SHA `8836bed9c13fc1299019dde319373a0c01b8ddf58569705e428aeaef5bd93f91`。
- 代码 commit `3aa3f61a4c5d55a5bc71fede33ee75922bd0c6d4` 已推送 `qiaoqiao2521/fishbot-ros2-slam-tools` 的 `codex/workflow-20261014`，GitHub REST ref读回一致。身份 `qiaoqiao2521/238822818`、既有repo `1381244533`、fetch/push URL与原public可见性均核对；未推main、未创建PR。代码提交仅6模块文件，独立worktree当时clean。

## Remaining
FishBot owner 负责串行整合及隔离实例实际两次运输、原生终态、between-job reset、取消/重启对账与独立 oracle 评分。CPU 成功不是整体实施验收。根负责原生 queue 接续与跨对话派发，不旁路新增协作条件。

## Issues
基线没有 cleanup/native_actions 公开字段；复用已有 reset.available 门禁。主桥历史截断时缺任务 ID 必须 unknown，不修主桥。
reset 本身失败或拒绝保留原 ID/receipt，交 FishBot owner 审查，不自动生成第二重置请求。编排器重启不包含 bridge 重启恢复。
根回执：原生queue daemon可连接，但桌面 `thread/loaded/list` 为空，尚无共享接入；不通过第二daemon resume或其他聊天发送路径派发本模块。候选分支保留，接续 owner=根Codex。

## Next
根在原生 queue 就绪后向原 FishBot owner 派发已审候选，再串行整合与物理验收。运行入口 `docs/COOPERATION_WORKFLOW.md`；CPU最短入口为其中 unittest 命令；不启动当前107/114。

## Knowledge closeout
`already_covered`：原知识页的提交边界原则已采用。新增领域经验候选由根决定；不编辑共享 Wiki。
