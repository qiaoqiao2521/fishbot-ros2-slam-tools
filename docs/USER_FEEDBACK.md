# 用户反馈与执行约定

本页把本次 FishBot 反馈转成项目执行约定。详细复盘保存在 Obsidian 的 `Wiki/ROS2 与 FishBot.md` → `用户反馈驱动的工程复盘`。原始消息及修订定位由 TraceMesh 保留；本页不复制原始会话。

实车已售，用户已确认本次建图和导航完成。当前改进使用源码、离线测试和虚拟环境；历史未验收项不构成重新接车、刷写或改网络的授权。

## 开始任务

1. 读取 [PROJECT.md](../PROJECT.md) 的当前状态与优先级。
2. 遇到重复问题时，选读本页相关条目和实现入口。
3. 需要核对用户原话时，用 TraceMesh 定点展开消息。
4. 核对已有代码、工具和验收记录，再列出具体缺口。
5. 明确本次验收模式：离线、仿真或实体。

旧记录只说明当时发生过什么。当前源码、最新用户决定和新一次运行结果共同决定本次状态。

## 执行约定

| 用户反馈 | 本项目执行方式 | 已有入口与边界 |
|---|---|---|
| 不要一直短距离走走停停 | 一个地图目标交给本地控制器连续执行；Agent 观察目标与异常，不把聊天轮次当作控制周期 | [连续地图路线](PASSAGE_CONTROL.md)；仿真网页巡逻仍使用既有 mission bridge |
| 点 Goal 没反应 | 分清请求提交、Nav2 确认、执行和终态；拒绝与取消显示原因 | `/simulation` 的 mission bridge 与页面；地图点击先选点，启动按钮才提交任务 |
| 普通时间问题不要反复锁死 | 沿用 tolerant 的零速暂停和健康后新命令恢复；保留时间与原因 | [时序策略](PASSAGE_CONTROL.md)；不重放过期非零命令 |
| 窄口明明能过却停 | 先查触发层、完整足迹、转弯扫掠、扫描与旧地图；随后只改对应参数 | [模型与分级碰撞区](PASSAGE_CONTROL.md)；零速本身不能证明碰撞触发 |
| 卡住太久、重复排查 | 连续两轮诊断没有新证据时，改方法或明确保留问题继续交付；影响运动正确性的条件仍须解决 | 在当前任务 progress 记录证据、退出条件与接续入口，不以重复重启代替判断 |
| 开源项目已有模型和工具 | 先查已有实现、官方资产与社区能力，再写最小补丁 | [依赖来源](DEPENDENCIES.md)、[架构](ARCHITECTURE.md) |
| 要看到实际结果 | 报告这次运行的状态、图或轨迹；失败与未验证范围一并说明 | 测试通过不替代完整路线或实车验收 |

## Goal 反馈契约

仿真 mission 保留现有 `status`，新增可选 `dispatch_state`：`pending`、`accepted`、`rejected` 或 `unavailable`。`pending` 时显示“等待 Nav2 确认”；只有确认后才显示任务正在前往目标。旧 bridge 缺少字段时，新界面沿用旧状态解释。

停止请求的首次原因保存在可选 `stop_reason`。后续“正在取消”或最终“已取消”不覆盖原因。该字段记录任务停止原因，不代表已观测到 Collision Monitor 的触发多边形，也不单独证明车体停稳。

本轮只更新源码和构建产物验证，不重启当前 app 或 ROS 运行环境。运行新版反馈需要部署同批 bridge 与前端。新增字段不改变既有 `MissionStatus` 枚举；旧前端仍能解析原有状态。

## 反馈回归入口

从项目根执行：

```bash
./fishbot.sh check
./fishbot.sh check-feedback
```

`check` 只查布局与 Shell 语法。`check-feedback` 组合已有 unittest 和 Vitest，不启动 ROS 节点、仿真或硬件连接，不安装依赖。ROS 消息和 BT 插件测试使用已安装的 Jazzy 环境；前端使用现有 `node_modules`。缺依赖或跳过测试须报告为验证不完整，不能算完整通过。

返回值：`0` 表示所有组通过且零跳过；`1` 表示至少一组失败；`2` 表示缺依赖、跳过或没有运行到完整测试。JSON 输出包含分组测试数、跳过原因与缺失依赖。已有任一失败时，返回 `1`，不被其他组的缺依赖覆盖。

| 回归场景 | 复用的测试 | 仍需仿真集成验收 |
|---|---|---|
| 窄口与分级碰撞区 | [配置](../tools/tests/test_passage_config.py)、[回放](../tools/tests/test_passage_replay.py) | 当前整段过门的真值轨迹及停顿统计 |
| 过期非零命令 | [守卫](../tools/tests/test_command_guard.py) | [既有 motion 验证](../workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/README.md)；不代表已售主控抗重放 |
| 短暂断流恢复 | 守卫与[真实 BT 插件回归](../tools/tests/test_passage_timing_tree.py) | 行驶中断流、真值停稳、恢复后继续原目标 |
| Goal 确认、取消与原因 | [任务桥接](../workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/tests/test_mission_bridge.py)、[页面状态](../apps/fishbot-control-station/frontend/src/lib/simulation.test.ts) | 取消后的独立真值停稳；Collision Monitor 来源与状态发布语义 |
| 顺序经过路线点 | [路线客户端](../tools/tests/test_passage_goal.py)、任务桥接 | 网页巡逻的独立真值逐点有序覆盖 |

完整仿真使用既有入口，不再创建新的控制框架：

```bash
./tools/fishbot_mujoco.sh verify motion
./tools/fishbot_mujoco.sh verify nav
```

`verify` 连接现有仿真，必须按 [MuJoCo README](../workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/README.md) 的就绪与独占命令要求运行。它不包含在离线回归中。窄口入口与 domain 96 条件见 [PASSAGE_CONTROL.md](PASSAGE_CONTROL.md)。不要在已有任务运行时直接启动另一个导航源。

## 后续仿真记录

沿用任务计划和既有运行证据目录，不建第二套反馈数据库。每次完整运行记录：Goal 确认等待、总耗时、零速停顿次数与时长、停止原因、人工 reset 次数、实际有序路线覆盖和最终停稳。

使用真值与任务反馈交叉核对。`Nav2 success`、`motion_active=true` 或进程退出码均不能单独证明全路线通过。上述统计尚未接入自动报告，下一项工作先复用现有真值轨迹和事件记录。

桥接另有既有异常边界：Nav2 已接受任务后，若结果订阅抛错，当前会标为 `failed`，但不能证明该任务已停止。后续需收束该任务并保留取消入口；定位入口为 `MissionBridge.goal_response()` 的接受后异常分支。本轮未修改这条生命周期路径。
