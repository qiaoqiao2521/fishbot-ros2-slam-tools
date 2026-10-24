# Progress — 连续业务世界与可视化回归

## Current

2026-10-24，D0文档规划完成；M1–M4均planned/pending，实施未开始。用户本轮请求为“写文档 specmesh plan”。没有新ROS动作、快照恢复、卸货、注入、数据库迁移、CI作业或云资源申请。

根入口为[任务计划](task_plan.md)，来源/技术修正见[发现](findings.md)。最新已完成业务仍是旧F1完整K：J100＋3D雷达同轮B→A2/2，B路线119.793848秒、余.206152秒；原采样与ideal守卫边界保留。

## Done

- 已读用户材料，核对现有Physics/reset、任务bridge、Workflow/factory、有限fault adapter、记录器、只读Oracle与前端/CI入口。
- 已核MuJoCo本机3.3.7状态API、官方状态/warmstart/接触文档与SQLite/JDBC来源；物理状态与ROS续接分R0–R3，首版不承诺50ms热恢复或逐位确定性。
- 已明确先从旧K只读耗时入手，再做分级快照；无reset卸货、首批故障、充电、矩阵/双视口/CI拆成可独立验收切片，依赖仅保留真实条件。
- 已保留原任务owner、只读Oracle、原始证据与旧评分；SQLite为可重建索引，SpecMesh继续保存目标/决策/进度。
- 已选定首片M1a、首批SensorDrop/ForceImpulse、B/B后B/A无reset、同一J100快照配对重复的有限范围。

## Remaining

- M1a：旧K阶段/缺口报告、SQLite导入与只读瀑布图。
- M1b：完整物理快照资格和R2独立ROS分支。
- M2：多臂/多物料、实际卸货、当前位置续单及库存核对。
- M3：真实故障生效/原UUID安全处理/异常前留存、模拟低电充电续单。
- M4：配对矩阵、留出与完整回验、只读双回放、分层CI和可追溯结果发布。

## Issues

- 原K不含完整积分状态，历史记录重建不能冒充快照热恢复。
- 原ROS系统内部状态尚无统一恢复能力；型号切换也不具备相同物理状态向量。
- B时间余量、初入站采样间隙仍是原已知问题；没有新实验定位唯一根因。
- 原框架是单臂/单货物、订单间reset；连续闭环需要真实卸货和有限第二货源。
- 瀑布图、SQLite、矩阵、充电和双视口均为计划能力，不能因本文件存在宣称完成。
- 本轮文档不采用用户材料中的全局冻结支线、7×24运行、倍速等价和固定工期假设。

## Knowledge Writeback

knowledge_status=already_covered。采用既有FishBot知识§19双时钟/参考点、§20原生与物理分层，以及原工作台RNG/规划过程经验。新增快照与索引选择仅完成官方接口核对，恢复精度和业务效果待实施；本轮不把设计晋升为已验证知识。未编辑知识库，既有未审修改与原发布状态保留；owner=本对话root。

## Verification

三文件与PROJECT/README入口已读回；97处相对文件链接全部存在，D0 complete/M1–M4 pending状态一致，`git diff --check`通过。变动仅Markdown，未执行代码测试或运动面板；实施验收数量=0。Git交付沿用既有main与qiaoqiao2521目标，具体修订由Git历史记录；提交成功不替代M1–M4验证。

## Next

下一实施入口为M1a：只读导入现有完整K的原记录，区分360秒全任务与120秒配送边界，输出有证据的阶段耗时及unknown。root在本对话接续；本轮文档任务不派发该运行。
