# 批量仿真验收

本入口把已有 MuJoCo 场景、passage 控制链、Goal 客户端、守卫记录和扫描回放串起来。它不连接实车，不读取住宅地图，不启动 domain 93 的网页巡逻。

## 运行

条件：本机已具备 [MuJoCo 运行环境](../workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/README.md)，domain 96 没有运行中的节点。

```bash
./fishbot.sh sim-suite
```

默认输出位于 `~/.cache/fishbot/simulation-suites/`。指定一个尚不存在、位于源码仓库之外的目录：

```bash
./fishbot.sh sim-suite --seed 12 --output /tmp/fishbot-suite-example
```

仅运行一个场景：

```bash
./fishbot.sh sim-suite --cases 04-moving-scan-gap --output /tmp/fishbot-gap-example
```

打开命令最后打印的 `index.html`。`report.json` 保存结构化汇总；各场景保留原始真值、Goal、日志、合成模型来源和实际存在的触发回放。运行产物不提交 Git。命令返回 `0` 表示所选场景全部通过，返回 `1` 表示失败、中断或证据不足。单场景通过不等于六场景通过。

## 场景矩阵

| 名称 | 验证内容 |
| --- | --- |
| `01-doorway` | 36 厘米门口，连续导航至 1.25 米目标 |
| `02-varied-doorway` | seed 决定门宽与初始朝向；模型姿态和 map→odom 一致 |
| `03-continuous-route` | 一个 NavigateThroughPoses 请求，按序覆盖三个点 |
| `04-moving-scan-gap` | 真值确认行驶后丢弃扫描 0.9 秒；tolerant 暂停、停稳、恢复原目标 |
| `05-cancel-moving-goal` | 新鲜真值确认移动约 25 厘米后请求取消，核对取消终态和独立停车 |
| `06-old-command-and-timeout` | 复用既有底盘探针，验证命令超时制动和十秒旧命令拒绝 |

扫描 relay 只在 domain 96 的故障场景启用。它丢弃故障窗口内的帧，不改时间戳、不缓存后补。`scan_restored` 表示第一帧恢复扫描实际转发，`gap_ended` 只表示计时窗口结束。

## 判断依据

导航同时要求真实 action 终态、新鲜 MuJoCo 真值、终点误差不超过 15 厘米、偏航误差不超过 0.30 弧度，以及至少 0.7 秒连续停稳。路线还要求所有中间点按序进入 15 厘米范围。停稳阈值为线速度低于 0.005 米/秒、角速度低于 0.02 弧度/秒。

真值检查接收时钟和仿真时钟。运动窗口从 Goal 提交前最后一帧开始，最大采样间隙不得超过 0.30 秒；最终源时间和接收时间年龄均不得超过 0.25 秒。启动间隙单独保留。缺失数据、时钟停滞、异常退出和不完整分析均不能通过。

报告的内部停顿只统计首次运动与末次运动之间、持续至少 0.2 秒的真实停稳。初始等待和最终停车不计入。姿态调整中的低线速度不等于停顿，角速度也须满足阈值。

断流案例必须同时证明：运动时触发、守卫暂停、实际停稳、新扫描恢复、守卫恢复、随后重新运动、原始单 Goal 成功。取消案例要求真实 CANCELED 终态，不能把取消回执当作已经停稳。reset 数量仅统计批量执行器调用，不推断外部操作者行为。

每个场景独立启动进程组。执行器只清理自己启动的进程；中断也保存失败场景和整批状态。启动时检测到已有 domain 96 节点就拒绝运行。

就绪超时只有一次冷启动重试。重试前须证明所有真值均静止、原进程组已清理、命令进程尚未启动，且不存在 Goal、motion 或 ready 文件。缺真值、异常数据、中断或任一命令已经启动都禁止重试。第二次启动仍须重新检查隔离域为空。

报告分别显示首轮通过数、最终通过数、启动重启次数和总耗时。重试使用新目录，首轮失败记录与日志保留。场景总耗时包含启动、重试、清理和回放；Goal 耗时只描述目标执行，两者不能互相替代。

仿真传感器就绪后才启动地图与导航。合成场景的 map_server 使用 Nav2 1.3.13 已有的 [`autostart_node`](https://raw.githubusercontent.com/ros-navigation/navigation2/1.3.13/nav2_util/src/lifecycle_node.cpp) 内部配置和激活，不再另设地图生命周期管理者。发 Goal 前核对 map_server、controller、planner、BT 和 CM 的新鲜 ACTIVE 状态，并确认实际收到有效地图。`ready.json` 保存状态回执和地图尺寸、分辨率、原点；action 服务可发现不等于节点已激活。

## 停车原因和界面

报告组合守卫触发、扫描事件、Collision Monitor 状态和真值轨迹。复用 [扫描回放](PASSAGE_CONTROL.md) 绘制实际扫描及碰撞区域。零速度本身不能指认触发层。

Nav2 1.3.13 的 `CollisionMonitorState` 没有时间戳，只在多边形状态变化时发布。界面因此显示“最近 CM 报告”，保留最近 action 和 polygon；不能把长期没有新事件解释为保护消息过期。发布者消失、更换、生命周期失效或时钟回退时显示未知。CM 与扫描按接收时间近似关联，不能据此指认某一帧中的具体激光点。

mission bridge 对已接受目标的结果订阅或取消异常做有限收束。重试的是同一目标的结果和取消请求，不重发 Goal。仍无法确认终态时保留目标、允许再次取消，并阻止新目标覆盖它。此分支由离线回归验证；本批次通过原有 CLI 路径验证导航取消，不宣称运行了网页异常注入。

本入口证明合成仿真中的行为。它不证明无线链路、已售主控、实体制动距离或生产稳定性。已知实车成功和失败继续按原记录保存。

## 开发检查

```bash
./fishbot.sh check
./fishbot.sh check-feedback
```

统一离线检查包含 relay、批量执行器、报告、mission bridge 和前端状态测试。它不启动 ROS 节点，不能代替上述整批运行。当前任务的实际结果和接续入口见 [本次计划](../plans/fishbot-simulation-suite-20261012/progress.md)。
