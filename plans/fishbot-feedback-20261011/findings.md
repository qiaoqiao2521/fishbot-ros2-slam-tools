# 核对结果

## 已有能力

连续 `NavigateThroughPoses`、完整模型足迹、分级碰撞区和 tolerant 自动恢复已经存在。默认 `check` 只有布局与 Shell 语法检查。守卫、路线、碰撞配置、回放、BT 插件、MuJoCo mission bridge 和仿真页面已有回归，可组合调用。

`/simulation` 已有 Nav2 接受/拒绝、取消与结果处理。缺口是确认前即显示 running，以及取消终态覆盖触发原因。本轮新增可选字段，不另建任务调度或状态系统。

## 必须保留的边界

Collision Monitor 已配置 `/collision_monitor_state`，但桥接尚未订阅。加入诊断前须核对安装版本的消息类型与状态发布语义；持续 STOP 可能只在变化时发布，不能用任意收包年龄阈值判断失效。零速不能直接归因于碰撞。

离线测试覆盖状态机与几何，不包含行驶中断流恢复、网页巡逻独立真值有序覆盖、当前窄口停顿统计。历史仿真记录保留；不称为本轮重新运行。

独立复核发现既有结果订阅异常边界：Nav2 accepted 后 `get_result_async()` 抛错，mission 被标为 failed，取消入口不再视其为活动任务，但 goal_handle 仍保留。新增回执字段如实保留 accepted；未改变原有生命周期行为。这不是物理停稳证据，后续须保留取消通道并收束已接受任务。

统一回归首轮发现四项既有回放测试失败。合成 `guard_snapshot()` 使用 laser_link 扫描和 TF，但几何仍配置 laser_frame。单独运行旧测试也复现。只修夹具的 `frames.scan` 并断言投影成功；未放松生产坐标系检查。

## 复用决定

回归入口直接调用现有 unittest/Vitest。Goal 改进扩展已有 bridge JSON 与页面 helper。没有新增 ROS 控制器、反馈数据库、全局 Hook 或技能。
