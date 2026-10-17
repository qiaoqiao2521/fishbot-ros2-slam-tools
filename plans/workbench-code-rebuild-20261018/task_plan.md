# 成熟源码工作台实施

## Goal

实施用户批准的[源码重建总计划](/home/muqiao/文档/ChatGPT/ros2/plans/cy-workbench-review-20261018/task_plan.md)。以 Lichtblick 完整源码替换自制工作台底座，迁入有效业务与安全行为。

## Scope

当前 P1：固定上游构建、真实 SO101 记录导入、只读任务面板和浏览器验收。完成后接 P2/P3 的产品化和新仿真任务，不把回放算作新抓放成功。

实现位于独立工作树 `/home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018`，分支 `codex/workbench-code-rebuild-20261018`，基线 `325fa260096d421d07035c4a64cb765e5006501b`。FishBot 原工作区的在途改动原位保留，合并前由根串行对齐。

## Phases

1. 导入固定官方源码、安装锁定依赖：complete。
2. 构建原版 Web，核对真实页面和原生面板：complete。
3. 官方 MCAP 写入库转换既有 trace/视频，独立读回；注册 EpisodeReview 并接共享时间：complete。
4. 实际验证同源布局、seek、图像、3D、曲线与只读边界：complete。跨回合换源与实时连接留后续。
5. 提交推送有效源码，更新总计划：in_progress。产品化与实际仿真接入属于 P2/P3。

## Acceptance

完整上游构建成功只是起点。新页面必须显示原记录、联动时间且不伪造缺失数据；刷新、seek、布局变化不能发运动。原始产物保持哈希不变，数据、日志、缓存不入库。

## Owners

根 Codex 维护入口、构建、注册、布局、验收与整合。数据 worker 仅写 `workbench-tools/`，面板 worker 完成隔离草稿，根已迁入 `workbench/packages/suite-base/src/panels/EpisodeReview/`。共享注册表与计划由根串行维护。

## Next Step

P1 实现与独立验收完成，固化适配提交并推送隔离分支。P2/P3 由根 Codex 继续：复用 FishBot 的 RuntimeRegistry 与 CooperationController；与 SO101 模块 owner 接通现有 full_cycle CLI 的运行身份、显式启动、协作取消和原任务查询，再接新界面的完整抓放。当前 coop-api 的 transport 不能代替独立 SO101 抓放。
