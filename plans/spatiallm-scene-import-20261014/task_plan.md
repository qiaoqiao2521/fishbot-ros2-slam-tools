# SpatialLM离线场景导入

## Goal

在FishBot独立实验模块实现官方layout查看、显式人工校正、MJCF导出及实际MuJoCo加载。条件合适才做单个官方推理样例；不申请云GPU、不付费、不训练。

## Scope and ownership

根持有独立worktree `/home/muqiao/worktrees/fishbot-spatiallm-scene-import-20261014`，分支`codex/spatiallm-scene-import-20261014`，基线`aab0da4`。FishBot主区和main由原对话01a101eb-92b4-78b3-a725-361dc7342c05整合。只改本模块`experiments/spatiallm/`和此计划，不修改根总研究三文件、共享Wiki、生产地图/规则及107/114实例。

2026-10-15可选Rerun收尾修复在独立worktree `/home/muqiao/worktrees/fishbot-spatiallm-rerun-finalize-20261015`，分支`codex/spatiallm-rerun-finalize-20261015`，基线`0d11a5b`。原工作区保持冻结；本修复仅关闭RRD文件、定向测试和本模块文档，不运行GPU或新增服务。

## Phases

1. 官方来源/schema/许可/样例核查：complete。
2. 严格导入、校正与MJCF转换：complete。
3. 人工编辑UI与本地软件入口：complete；空坐标拒绝和纯场景导出表单已读回。
4. 官方样例实际加载、渲染与负例验收：complete；最终65项测试、100物理步及执行源码指纹读回通过。
5. 官方单例推理：complete。固定官方CLI在26.903秒后退出0，16实体严格解析通过；相对GT18实体有差异。6墙显式校正后完成原FishBot CPU100步，无渲染及起点净空验收；原件绑定冻结0d版本。
6. scoped提交和特性分支交付：complete。初版`03e37eb`及起点修复`fcf0e919cbbfb75540d87227161b5758f8d1d411`均已独立验收；分支最终tip见Git及v5交接证据。main串行整合归FishBot owner，仍待其验收。
7. 可选Rerun原件绑定修复：complete。代码提交`6f5dd4aeef7eecdb4d112ee036083ab34f2fbc4e`；官方disconnect关闭后才取hash。新RRD/manifest退出后二次读回一致，原生SDK读取点云及18结构图层通过。独立分支提交与远端读回由Git及新交接证据记录，main归owner整合。

## Assignments

- spatiallm_source_audit：来源/样例核查已交付；接续editor.py与static UI。
- spatiallm_converter：scene_import.py、受限官方layout模块接入与行为测试。
- 根：环境、计划、许可边界、实际MuJoCo/网页验收、串行提交和交接。

## Acceptance

- 使用固定revision官方真实GT或有来源的预测文件，GT不得冒充推理。
- 错误行/缺引用/负尺寸/非有限数不得静默丢失；18实体完整。
- 零墙厚保留原始值并警告，导出前显式校正且保存before/after。
- 门洞必须真实贯通碰撞几何，窗采用明确保守策略；bbox标注近似占用。
- MuJoCo实际compile/step、几何检查和真实PNG证据；不能以XML生成或exit0替代。
- 网页实际导入、选择、校正、导出/下载，错误反馈，桌面/390px可用。
- 来源commit/样例revision/输入输出SHA和许可证边界可追溯，raw资产与运行输出不入Git。
- 可选RRD的manifest必须绑定已关闭文件；失败不生成成功manifest，旧输出和旁账保留。
- 推理与转换分别报告；无官方推理结果时不以合成替代。

## Reuse decision

复用官方Layout/entity和原生Rerun可视化，复用FishBot MJCF机器人；已有栅格/固定工位生成器不支持语义向量layout、门窗与编辑，因此只补严格验证、开孔和输出薄适配，不重写模型或通用场景框架。
