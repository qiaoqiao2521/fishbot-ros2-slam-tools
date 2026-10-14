# SpatialLM离线场景导入

## Goal

在FishBot独立实验模块实现官方layout查看、显式人工校正、MJCF导出及实际MuJoCo加载。条件合适才做单个官方推理样例；不申请云GPU、不付费、不训练。

## Scope and ownership

根持有独立worktree `/home/muqiao/worktrees/fishbot-spatiallm-scene-import-20261014`，分支`codex/spatiallm-scene-import-20261014`，基线`aab0da4`。FishBot主区和main由原对话01a101eb-92b4-78b3-a725-361dc7342c05整合。只改本模块`experiments/spatiallm/`和此计划，不修改根总研究三文件、共享Wiki、生产地图/规则及107/114实例。

## Phases

1. 官方来源/schema/许可/样例核查：complete。
2. 严格导入、校正与MJCF转换：complete。
3. 人工编辑UI与本地软件入口：complete；空坐标拒绝和纯场景导出表单已读回。
4. 官方样例实际加载、渲染与负例验收：complete；最终65项测试、100物理步及执行源码指纹读回通过。
5. 推理条件评估：complete。官方环境与模型缓存准备完成；单例推理待FishBot owner提供GPU空闲窗口。
6. scoped提交和特性分支交付：complete。代码提交`03e37eb166eeff553d9149d55a934e4d6db7c13b`已推送并独立读回；main串行整合归FishBot owner，仍待其验收。

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
- 推理与转换分别报告；无官方推理结果时不以合成替代。

## Reuse decision

复用官方Layout/entity和原生Rerun可视化，复用FishBot MJCF机器人；已有栅格/固定工位生成器不支持语义向量layout、门窗与编辑，因此只补严格验证、开孔和输出薄适配，不重写模型或通用场景框架。
