# Arena 组合评测接入

## Goal

部署官方 Isaac Lab-Arena，新增同一策略在不同物体条件下的组合评测入口。运行结果与策略成功率分别验收。

## Scope

复用官方 ExperimentRunner、PolicyBase、结果文件和报告，不自建仿真器或训练器。锁定 Arena commit、Isaac Lab gitlink 与 uv.lock。先完成部署准备，再在用户选择且许可已确认的 GPU 机器上运行 20 步预检与 baseline/swap_objects 两个 Run。

当前 MuJoCo/Nav2、107/114服务、网页与SO101只读依赖保持。不迁移模型，不宣称新抓取能力，不下载策略权重。

## Phases

1. 官方版本、依赖、许可和本机条件核对：complete。
2. 锁版源码、独立部署入口、两Run配置与预检：complete。
3. 用户选择Colab；首次L4预检Vulkan不兼容，补齐同版私有图形库后通过。用户已明确接受NVIDIA软件与Isaac Sim/Omniverse许可，许可后所有重试沿用原45分钟窗口，现已收尾且活动会话0；20物理步已执行但关闭失败。
4. 前一窗口安装与20步完成但关闭失败；失败保留。新增窗口关闭复验及两Run评测：complete。
5. 前一轮代码/项目/知识与Git交付：complete；旧运行失败保留。

6. 用户要求完善闭环：逐episode交叉读回、阶段checkpoint、末尾recovery index与失败路径取证/释放：complete。
7. 沿既有设置开启一个新有界窗口：只用一个L4，最多2700秒，不购买额度，不改kernel；关闭复验和两个Run：complete。
8. 项目/知识收尾与代码Git交付读回：complete。

## Acceptance

准备验收：预检如实报告4GB本机不满足16GB支持基线；版本和源码差异不能静默忽略。未知许可不得自动接受。

运行验收：真实官方runner推进环境；两个Run各1env/1episode，实际输出arena_experiment_result.json与逐episode结果；核对物体组合和终止原因。zero_action的任务失败不能算策略成功，源码存在/安装退出0不能算运行验收。

## Adopted knowledge

采用FishBot独立输出/源SHA/失败保留做部署回执；采用既有SO101训练经验，区分框架接入、策略效果与真机验收。只有已核实缺口才写薄入口，全部评测执行仍由官方runner完成。

## Next Step

本轮执行、取证、回收、代码验证及源码远端交付完成。当前活动会话0，不再申请GPU。后续真实策略、更多留出任务与SO101/FishBot适配按新需求单独验收；本次零动作结果不当训练或抓取成功。
