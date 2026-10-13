# 地图规则与巡航模板

## Goal

将扫地机逆向得到的地图编辑、路线与预约语义落到 FishBot 第一阶段：网页/触屏编辑虚拟墙与禁区，Nav2 实际遵守独立规则，保存巡航路线与执行记录，形成后续训练与对照评测的任务基线。

## Scope

- 沿用 `/simulation`、现有 mission bridge 和 FollowWaypoints 生命周期。
- 墙为两点线段，禁区为四点轴对齐矩形；显式保存、撤销、移除，保存不产生运动。
- 规则与模板绑定地图内容标识和版本；活动或结果未知的任务期间拒绝改规则。
- Nav2 global/local KeepoutFilter 读取独立 mask，MuJoCo 实体与 AMCL 原地图保持原样。
- 本地持久化位于仓库外缓存；发布、导航确认、执行与终态分别表达。
- 保存路线、加载为草稿、沿用开始巡逻与取消；执行记录不冒充独立物理验收。
- 用隔离仿真实际验证禁区绕行、禁区 Goal 拒绝、取消停稳和规则删除后的恢复。

## Deferred

强化学习训练器与策略权重、日历 Schedule、BLE 配网、自动房间分区和实车迁移属于后续阶段。本阶段不操作已售实体车，不复制厂商协议实现或私有逆向素材，不公开住宅地图。

## Architecture and reuse

复用 Nav2 1.3.13 KeepoutFilter、现有 React 页面与 Python mission queue。薄适配只包含几何/持久化、mask 发布、确认查询和编辑界面。普通 InflationLayer 在 filters 前执行，另加后置原生 InflationLayer 处理 keepout；mask 不重复扩张车体半径。

规则 API：GET/POST `/sim-api/map-rules`；提交包含 `map_id/base_revision/zones`。路线 API：GET/POST `/sim-api/routes`，保存不派发。GET `/sim-api/runs` 读取真实任务实例记录。运动仍仅通过现有 `/sim-api/mission`。

## Work ownership

- 根 Codex：串行整合；ROS launch/config、运行验收、项目入口、文档与 Git 交付。
- map_rules_backend：Python helper、mission bridge、相关测试和 helper 安装。
- map_rules_frontend：simulation UI、类型/资源 hook、相关前端测试。
- reverse_sim_alignment：只读 Keepout/运行/保留脚本审查。

## Acceptance

1. 非法几何、冲突版本、地图变更、活动任务与未知结果均不能绕过规则。
2. 桌面和390px触屏能画、撤销、保存规则和保存/加载路线；观察与保存不发运动。
3. 原生 Nav2 两 costmap 读回实际禁区；独立真值证明整段绕行且不侵入规则。
4. 删除规则后 costmap 与路线实际恢复；缺确认不显示已应用。
5. 原任务确认/取消/未知收束及时间保护回归通过。
6. 现有 app 可打开新增功能；当前源与运行来源绑定；有效源码提交推送既有新账户远端。

## Adopted knowledge

采用 Obsidian `Wiki/ROS2 与 FishBot.md` 第12节：结果未知保留原任务，不自动重发；CM变化事件不作为心跳。适用于规则保存回执、mission状态与本次验收分层。

## Status

第一阶段功能、合成仿真及浏览器验收、源码提交推送完成。当前结果、运行入口、保留项与训练边界见progress。
