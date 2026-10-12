# 网页运行验收

2026-10-12 在隔离 domain 100 实测新版网页反馈。前端端口为 5176，任务 API 端口为 9076。网页复用 Vite、React 和 Python `mission_bridge.py`，没有新增 Java 服务或控制框架。未接触实车，未重启 domain 93，未修改网络或保护参数。

## 独立实例入口

先完成现有 MuJoCo 构建和前端依赖安装。保持目标端口空闲，再运行：

```bash
FISHBOT_MUJOCO_DOMAIN_ID=100 FISHBOT_WEB_PORT=5176 FISHBOT_MISSION_PORT=9076 \
  ./tools/fishbot_mujoco.sh web headless:=true
```

打开 `http://127.0.0.1:5176/simulation`。默认入口仍使用 domain 93 和端口 5173/9070。域必须为 1–232，API 域必须匹配选择；domain 0 和非本地 HTTP 来源被拒绝。网页入口清空静态 peer；直接启动 bridge 时拒绝非空静态 peer。每个域和端口组合使用独立日志目录。网页与 API 均监听回环地址。

本轮异常验收使用 `bridge:=false`，另启动忽略目录中的临时验收适配。适配复用真实 `MissionBridge` 与 Nav2 ActionClient，只让第二个真实接受目标的前三次结果订阅抛异常。它保留实际目标 handle、实际取消请求和最终结果；没有增加产品故障端点。正常 launch 到标准 bridge 的端口传参已做源码检查，本轮运行证据来自该临时适配。

## 实际结果

| 检查 | 实际证据 |
| --- | --- |
| Goal 确认 | HTTP 202 返回 `pending`；真实 Nav2 接受后变为 `accepted`，随后观察到物理运动。 |
| 移动取消 | 网页取消任务 `b68e1f3698fc45d6ad8fbc2af8ee4580`；实际 Goal UUID `94121f6e8f014963ab7012326db14ae9` 返回 Nav2 状态 5。 |
| 回执异常 | 任务 `48a7a11d35da4266935d5155d644a99f` 三次结果订阅异常后保持 `canceling/unresolved`，原 UUID `457bb12a07544fe6a2932d52ea7693c6` 保留。派发按钮禁用，重叠请求返回 409。 |
| 再次取消 | 网页点击“重试取消”；同一 UUID 第四次结果订阅取得真实状态 5，首次停止原因保留。前两个验收任务各发送一个 Goal，没有因结果未知重发。 |
| 真实 CM 报告 | 临时停用本实例的 `diff_drive_controller` 后，CM 实际发布 action 1、`invalid source`；界面显示最近的停车报告。 |
| 来源恢复 | 控制器恢复读回 `active`。无新命令时最近 STOP 保留约 62.65 秒；新导航命令触发真实 action 0、空 polygon，界面更新放行。 |
| 实例清理 | 自身三个进程组均无活进程，5176/9076 均关闭。 |

停止真值与 Nav2 终态分别检查。前两任务各有至少 7 个连续新鲜真值样本，低速持续约 0.702/0.726 秒；源时间与观察到的仿真时钟最大差约 0.018/0.006 秒。第一任务在 Nav2 状态 5 后约 0.417 秒首次观察到低速，不能将终态回执解释为瞬时停稳。阈值为线速度小于 0.005 m/s、角速度小于 0.01 rad/s。

CM 源失效的依据来自实际日志：scan 请求时刻约 491.478 秒，而 odom→base 的最新 TF 为 491.238 秒，CM 报告 future extrapolation。该演练只验收真实状态来源与网页显示。控制器停用期间不再接收 CM 输出，因此不能据此宣称物理急停通过。持续 STOP 的年龄表示最近变化距今多久，不是心跳超时。物理箱体进入路线时，RPP 先处理障碍，CM 未产生状态变化；当时界面如实显示未知。

## 验证与证据边界

原网页运行对应桥接回归 42 项、前端 simulation 回归 14 项通过，零跳过。类型检查、前端构建、相关 ESLint、shell 语法和 diff 检查通过。实际浏览器使用 bundled Playwright 和系统 Chrome 的新建临时无头上下文，没有操作用户日常浏览器。

本机证据目录为 `workspaces/fishbot_mujoco_ws/.runs/web-feedback-20261012/`，按项目规则忽略，未推送运行日志：

- `browser-result.json`、`web-feedback-summary.json`：两项网页任务及独立真值停车检查。
- `bridge-events.jsonl`：真实 Goal UUID、发送次数、结果和 CM 事件。
- `controller-readbacks.jsonl`、`source-persistent-report-result.json`、`cm-resume-result.json`：控制器来源故障、恢复和新 CM 放行。
- `03-original-goal-retained.png`、`04-retry-terminal.png`：异常保持目标和重试终态页面。
- `05-real-cm-source-stop.png`、`06-persistent-last-cm-report.png`、`07-new-cm-release-report.png`：真实 CM 状态页面。
- `cleanup.json`：仅清理本次拥有进程组和端口的读回。

浏览器预检缺少 bundled Chromium 二进制、一次错误选择器，以及错误期待无新命令就自动发布 CM 放行的尝试均保留。后续使用系统 Chrome、实际按钮名称和新导航命令分别完成对应验收。保留这些失败，不将整目录所有尝试都算通过。

这批证据覆盖合成 MuJoCo 环境的网页任务反馈。它不证明实车、完整巡逻路线、生产稳定性或控制器停用时的物理急停。

## 接收回执异常补丁

后续独立复核发现：接收 Future 抛异常时，原实现把任务改成 `failed`，允许再次派发。未知回执不能证明 Nav2 未收到原目标。同步发送抛异常也没有确定未发送的证据。

现有 `canceling/unresolved` 字段保留原任务 ID 与路线。无 handle 时，取消 API 如实保留未知，禁止新目标。网页显示“接收状态未知”和“取消无法确认”，不提供无法发出的取消重试。已接受且持有 handle 的结果订阅异常，仍复用原目标进行有限收束和重试取消。

该补丁先完成离线回归，随后完成下面的独立网页重验。上面的 CM 状态验收仍有效。原网页产物没有启动时源码 SHA 记录；`ack-ownership-prepatch.json` 只记录补丁前的后续源码观察，不能补作历史运行来源。新重验保留原产物，并在启动前另记源码 SHA。

补丁后桥接回归 44 项、前端 simulation 回归 15 项通过，零跳过。类型检查、构建和相关 ESLint 通过。新增回归确认同步发送异常与接收 Future 异常都保留原任务，重叠请求被拒绝；无 handle 的取消请求仍为未知，没有虚构成功或重发 Goal。

## 接收异常实际重验

2026-10-12 18:42 CST 另起 domain 100、5176/9076 实例。启动前写入 `source-receipt.json`，记录 30 个源码、配置和临时验收文件的 SHA-256。桥接源码 SHA 为 `dc49b89ae405b35b953e98312c4cffff85680f347a183822827edd064afa367e`。结束后逐文件读回一致。该记录只证明本次新运行的来源，不补作前一次运行的来源。

| 检查 | 实际结果 |
| --- | --- |
| 正常接收与取消 | 任务 `6d1c2785e5a6472dbd6a59f7db129077` 从 HTTP `pending` 变为真实 `accepted`。Goal UUID `383779060b784d75a9ea95ec0f47b2a2` 移动后经网页取消，返回真实状态 5。 |
| 结果订阅异常 | 任务 `c6d398d3d22c4512934a911742c188a7` 的 Goal UUID `17c4b335bda448c0b114807c4156afe3` 三次订阅抛异常后仍占有原任务。重叠派发返回 409；网页重试取消后第四次订阅得到真实状态 5。 |
| 接收回执异常 | Nav2 真实接受任务 `7936a689b6c04dfebceaee7669fa56e1`、Goal UUID `8333a64790004566a488f6ce604db5cb`。临时验收适配只向业务层交付异常 Future，实际 handle 只留在验收侧。业务保留原 ID，状态为 `canceling/unavailable/unresolved`。 |
| 未知状态与所有权 | 界面显示“接收状态未知”，禁用派发和无法发出的取消重试。重叠派发返回 409；无 handle 的取消 API 返回 202，但状态仍未知，首次原因保留。此时仍观察到实际真值运动，说明未知回执不能证明目标未执行。 |
| 发送与清理 | 全程恰好发送并接受三个不同 UUID。前两个有真实取消终态；第三个没有虚构终态或自动重发。随后只清理自身实例，不能把栈清理算作第三任务取消成功。所有自有组无活进程，5176/9076 均关闭。 |

前两任务各有 12 个连续新鲜低速真值样本。源时间与接收时间都持续推进，低速持续约 1.32 秒，源时钟年龄最大为 0.002 秒。正常取消在终态后约 0.329 秒首次观察到低速；结果订阅异常任务约 0.052 秒。停车验收继续使用线速度小于 0.005 m/s、角速度小于 0.01 rad/s，样本间隔不超过 0.3 秒，源时钟年龄不超过 0.25 秒。

本次后台 Playwright 运行退出 0，页面无异常。另读回真实 UUID、结果、连续真值和清理记录；页面截图实际显示原目标保留和接收状态未知。新证据目录为 `workspaces/fishbot_mujoco_ws/.runs/web-feedback-ack-20261012/`，仍按规则忽略：

- `source-receipt.json`：真实启动前来源；`web-feedback-summary.json`：结果、独立真值停车检查、来源一致性与清理读回。
- `bridge-events.jsonl`：三个真实 UUID、结果订阅次数、两个真实终态和第三个隐藏 handle 记录。
- `browser-result.json`、`browser-events.jsonl`：页面操作、409 拒绝、取消响应与未知状态读回。
- `03-original-goal-retained.png`、`04-retry-terminal.png`、`05-unknown-acceptance-retained.png`：实际页面状态。

同步 `send_goal_async` 抛异常的分支仍只有离线回归；本次实际注入的是已接受目标的接收 Future 异常。CM 来源故障没有重复演练，原状态与界面证据保留其既有局限。本次也不证明完整路线或生产稳定性。
