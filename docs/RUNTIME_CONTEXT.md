# 运行环境与命令回执

本页定义工作台重构 P1 的兼容合同。实现进度与实际验收见[重构进度](../plans/workbench-rebuild-20261018/progress.md)。

## 服务与执行归属

| 能力 | 实际 owner | 读取入口 | 写入口 | 回执语义与恢复边界 |
|---|---|---|---|---|
| 手动速度、软件停止 | Java ControlService / RosTopicService，之后由原 ROS 速度链执行 | `/api/v1/connection`、`/api/v1/state` | `/api/v1/control/cmd-vel`、`stop`、`emergency-stop` | 发布结果；零速度发布不是原生 CancelGoal 或连续停稳证明 |
| 雷达页目标、初位姿 | Java topic publication；原 Nav2 接收话题 | `/api/v1/navigation` | `/api/v1/control/goal`、`initial-pose` | HTTP 成功只代表发布。全局 status_list 无法关联这次发布 |
| 巡逻与地图规则 | mission bridge，原 FollowWaypoints 与地图规则发布器 | `/sim-api/state`、`runs`、`map-rules` | `/sim-api/mission`、`cancel`、`map-rules` | 桥接任务状态含 dispatch_state；runs 是当前地图记录集合，不是任意任务 ID 查询接口 |
| 停靠／装货运输 | cooperation bridge，原 DockRobot / Nav2 / SO101 | `/coop-api/state` 与有界 history；`reset/{id}` 查询重置 | `/coop-api/start`、`cancel`、`reset` | task_id 与 episode_id 分开。state 的 task_id query 不是服务端按 ID 查找；客户端必须核对返回任务 |
| 语音任务 | voice bridge 委托 mission/cooperation/native task | `/voice-api/state` | `/voice-api/preview`、`transcribe`、`execute` | accepted 是入口接纳；session_id、command_id、task_id 分开核对。STOP 经原 owner 取消 |

上表描述现有写入路径，不宣称已经实现跨服务互斥。P5 切换时仍需按 robot/runtime/能力明确唯一 owner，关闭旧写入路径并验证回退。P1 没有启动第二个动作执行器。

## RuntimeDescriptor v1

四服务分别提供只读入口：`/api/v1/runtime`、`/sim-api/runtime`、`/coop-api/runtime`、`/voice-api/runtime`。

字段包含 `schema_version=1`、`service`、`instance_id`、`mode`、`domain`、`scene_id`、`episode_id` 和 `capabilities`。身份读取只使用启动信息和本地状态，不查询上游任务，不触发 ROS 动作。

- `instance_id` 是服务本次启动的唯一身份，不能用 domain、端口或源码版本代替。
- Java 不知道远端 rosbridge 的 ROS domain，返回 `null`。本地环境变量不能证明远端身份。
- cooperation 的场景身份使用已读取 world XML 的摘要。mission 与 voice 没有对应真值来源时返回 `null`。
- `task_lookup` 仅指按任务 ID 查询原任务。当前快照、有限历史和重置查询都不能冒充该能力。
- `submission` 区分 `native_action`、`topic_publish`、`delegated`、`read_only`。`event_history` 区分无历史、当前快照与有界历史。
- 同域不等于同场景，不同服务实例也不自动组成一个环境。工作台分别显示服务身份。

## 进程代次与兼容

响应使用 `X-Fishbot-Instance` 标识服务来源。已取得身份的新客户端在后续请求中携带该值。写请求与当前实例不符时，服务器在调用业务 owner 前返回 `409` 和 `outcome=rejected`。只读 GET 不因旧 header 被拒绝，允许重新发现身份。

该检查只防止跨进程重启的迟到请求，不是身份认证、跨 owner 锁或物理停车证明。旧客户端不携带 header 时保持现有行为。老服务没有 runtime 入口时，工作台显示“旧接口／身份未提供”，沿用原 domain、scene、episode 与任务检查，不伪造身份。

网页不自动重发命令。HTTP 结果仍由各原适配器判断明确拒绝或结果未知；不将所有 4xx/5xx 统一改成一种结果。已知代次变化后，迟到响应以及延迟 JSON 解码结果不能覆盖当前状态。

## 数据来源与事件

控制站分别记录连接、位姿、导航、感知、诊断的来源状态：示例、已收到、断流后的旧数据、格式无效。单个资源成功不能让其他示例数据变成实时数据。断流保留最近数据并显示原因；重新接收只恢复对应资源。

Java SSE 的 ID 包含服务实例与单调序号。客户端核对当前实例并忽略倒序事件；先收到的新 SSE 不会被迟到的初次 HTTP 读取覆盖。SSE 是遥测快照，没有原任务历史保证。数据校验成功后才推进序号；首次身份发现与实例切换会重新读取五类快照。Java 使用256条有界缓冲并保留重订阅能力，最后一个浏览器断开不会终止服务端流；丢弃有计数和限频日志。

协同事件单独按 instance/episode/task 的源序号核对。采样窗口有界；重连后已有原始事件可补齐缺号，当前状态不能补造历史。超过窗口时连续性显示未知。完整事件序号不代表完整物理采样；当前后端没有任意任务日志重放接口。

## 四层结果

页面的“回执与验收明细”分别显示：提交回执、原生执行、清理与停稳、独立物理评分。它是只读投影，不控制准入或动作重试。

原生执行需要可关联的原生 Goal UUID 和原生状态。没有字段时显示未提供；业务 `succeeded`、HTTP 200 或语音 `accepted=true` 不能补造原生成功。任务终态不证明连续停稳，收到一个任意 `physical_result` 字段也不等于已核验独立评分。

## 验收入口

- 前端：`npm test -- --run`、类型检查与构建；包含重启、乱序、跨域、未知回执、取消未终态及事件缺口负例。
- 服务端：运行 runtime 定向测试及原 Java/Python 行为回归；验证拒绝发生在业务调用之前。
- 浏览器：隔离端口下验证环境显示、旧接口降级、四层明细与零自动写请求。
- ROS：按本轮进度记录独占实例的实际身份读取；P6 另跑完整运动面板。本页不把只读 HTTP 验收当导航或运输成功。
