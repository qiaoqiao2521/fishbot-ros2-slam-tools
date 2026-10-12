# Findings

- `unitree-app-re/FISHBOT_MAPPING.md` 的初始映射表已经过时：单点 Goal 已包含 yaw，`/simulation` 已有真实 `/plan` 叠层、FollowWaypoints、返航和取消。不按旧表重造。
- `unitree-app-re/NOTES.md` 的第一轮控制站交付记录，逐项对应本仓原 11 个 tracked 修改、NavigationGoalRequest 和两张 PNG。它们是可复用成果。
- 主控制站 `/radar` 走 Java / rosbridge / SSE；`/simulation` 走既有 Python mission bridge。两条通路的运行实例必须明确区分。
- 接手时 `/radar` 尚缺 `/initialpose`、`/plan`，任意地图点击立即发布 Goal；本轮补齐接口并改成模式选择和显式提交，避免观察时触发动作。
- 本轮采用知识库 `Wiki/ROS2 与 FishBot` 第4节“点击 Goal 必须有逐层反馈”和第12节“结果未知不是重发许可”。用于限制发布回执和巡逻目标所有权的声明；不增加第二套调度器。
- 源文档对 BLE 时间戳 t+1 和信令防重放的说法属于历史分析。没有必要将其引入已有 rosbridge 控制站，也不把这种挑战独立称为充分鉴权。

## Evidence

TraceMesh 原对话为 ZCode《了解 rea 仓库及其部署》：source=`zcode`，store=`bde513028216f5f09ffecde7`，session=`sess_17a0e175-8a15-4fe2-84e6-9d18bffb651e`。公开消息 #25、#79、#137 表达将宇树手机端 ROS2 建图、雷达和导航能力借鉴到 FishBot；#757、#773 授权继续分析；#805 为本轮粘贴的历史助手总结。用户本轮明确选择控制站，覆盖原安卓指代歧义。

七条公开消息 `[25,79,137,144,757,773,805]` 读前后修订一致：`26a3b786f8aff4d0616c9538b4c58a81eb284c1dc6f96d109d7efca9636cae2d`；所读内容 SHA256=`bfd3c897001b1ed3a3e72322877581449c3523ff351cbc77f5adbfbed3f640e5`。使用项目现有原生阅读器定点展开。ZCode 不支持 CLI brief/message；完整 review 包受64 MiB物理快照上限限制。Codex refresh 遇到活跃来源变化，未将刷新失败当作零命中。

逆向素材保留原目录，不复制原始脱壳源码、APK 或密钥到 FishBot。本次以现有 ROS 标准接口独立实施 UI 行为。

## 实测发现

第一轮 Nav2 两点巡逻加返航全部成功，但独立物理返航误差为0.188280515米，未通过原15厘米门槛。复用项目既有0.03米估计容差，将仿真YAML的0.12收紧为0.03；动态参数读回确认后，在同一launch、同样目标序列再次运行，返航误差为0.125651041米并停稳。不是3厘米物理精度，也未通过放宽真值评分消除失败。

实际重定位消息采用 `/clock`，两次源年龄为30/6毫秒。新连接代次使旧Path和Clock失效。规划器可能只在路径变化时发布，因此展示最新观测路径及更新时间，不另设固定路径年龄锁。

丢回执前端检查只中止浏览器请求，未发送到服务端；不将其扩写为已接受Goal后失联验收。HTTP主题发布、AMCL消息更新、Nav2动作终态和独立物理真值分别记录。
