# 成熟源码工作台实施

## Goal

实施用户批准的[源码重建总计划](/home/muqiao/文档/ChatGPT/ros2/plans/cy-workbench-review-20261018/task_plan.md)。以 Lichtblick 完整源码替换自制工作台底座，迁入有效业务与安全行为。

## Scope

P1 已完成。当前接 P2：借用 RoboDK 的场景树、平移坐标系、目标引用和指令组织，接入 Lichtblick 原生配置与布局保存。P2 编辑器已交付，P3 固定抓放模板的新仿真、查询、取消与结果已验收；任意程序与全能力迁移继续待办。

实现位于独立工作树 `/home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018`，分支 `codex/workbench-code-rebuild-20261018`，基线 `325fa260096d421d07035c4a64cb765e5006501b`。FishBot 原工作区的在途改动原位保留，合并前由根串行对齐。

## Phases

1. 导入固定官方源码、安装锁定依赖：complete。
2. 构建原版 Web，核对真实页面和原生面板：complete。
3. 官方 MCAP 写入库转换既有 trace/视频，独立读回；注册 EpisodeReview 并接共享时间：complete。
4. 实际验证同源布局、seek、图像、3D、曲线与只读边界：complete。跨回合换源与实时连接留后续。
5. 提交推送有效源码，更新总计划：complete。产品化与实际仿真接入属于 P2/P3。

## Acceptance

完整上游构建成功只是起点。新页面必须显示原记录、联动时间且不伪造缺失数据；刷新、seek、布局变化不能发运动。原始产物保持哈希不变，数据、日志、缓存不入库。

## Owners

根 Codex 维护入口、构建、注册、布局、验收与整合。数据 worker 仅写 `workbench-tools/`，面板 worker 完成隔离草稿，根已迁入 `workbench/packages/suite-base/src/panels/EpisodeReview/`。共享注册表与计划由根串行维护。

## Next Step

P1 实现与独立验收已提交推送隔离分支。P2/P3 由根 Codex 继续：复用 FishBot 的 RuntimeRegistry 与 CooperationController；与 SO101 模块 owner 接通现有 full_cycle CLI 的运行身份、显式启动、协作取消和原任务查询，再接新界面的完整抓放。当前 coop-api 的 transport 不能代替独立 SO101 抓放。


## 2026-10-20 P3 固定模板闭环

状态：complete（固定八步抓放、方块小范围移动、附加障碍）。真实浏览器发起的新完整回合、刷新不重发、结果及录像读取、另轮协作取消均通过。来源与证据见 progress 末节。

下一步按用户任务扩充受支持参数或其他能力，不自动恢复训练、20+20、实机或CY发布。任意程序编译、实时三维数据源和整站能力迁移未完成。
