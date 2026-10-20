# 实施进度

## Current

2026-10-18，P1 可运行底座、真实记录与原生回合面板已完成独立验收。隔离分支 `codex/workbench-code-rebuild-20261018` 已推送既有远端，适配提交 `fb4a6622d5df024e7851a92f3351b3f223ef584b` 经 GitHub ref 回读一致。新仿真任务、完整能力迁移与 CY 正式切换仍为 P2–P5。

预览：<http://127.0.0.1:5186/so101>。手机浏览器布局：<http://127.0.0.1:5186/so101-mobile>。服务仅监听本机，按 `apps/fishbot-control-station/WORKBENCH.md` 重启。当前读取历史回合，没有发送机器人动作或启动训练。

## Source and build

- 从 FishBot `325fa260096d421d07035c4a64cb765e5006501b` 建立隔离工作树；原 FishBot 工作区、服务及在途运动规划由原根继续维护。
- 固定 Lichtblick v1.29.1 / `95713edb309d77589b130286642ab149995a5f7b`。导入提交 `0eaa6d9` 的 2,297 个原文件与官方归档逐字节一致；原版权、许可证和测试数据保留。
- Node 22.23.2、Yarn 4.17.0，immutable 安装通过，`yarn.lock` 未改。Corepack 的父目录 ESM 冲突通过独立缓存作用域修复，没有修改全局 Node 配置。
- 原版生产构建 147.562 秒通过；最终含移动视口的构建 168.654 秒通过。均只有两项资源体积警告，不宣称加载性能验收。
- 新面板使用原 Panel、MessagePipeline、seekPlayback。原文件适配仅注册表、默认侧栏、秒显示和 HTML viewport；桌面/手机布局使用原格式。

## Data verification

- 原 SO101 回合：`reviewed-20261014-183003-2405056/full-cycle-20261014-212632-2677556`。转换后 MCAP 为 26,525,186 字节，SHA-256 `73d74dc37a548193ce8fc6109abc421b1a197ce612e164efab83213b4df90d5d`。
- 共 14,976 条消息：3,328 组关节、接触、阶段、物体姿态，以及 1,664 帧原录像。视频帧 j 对应 trace[2*j+1]，首帧物理 0.04 秒，按原 recorder 源码、帧数与 PTS 核准。
- 独立全量读回通过：原输入哈希不变、四条来源绑定、七项报告指标、分块与全数据节 CRC、索引读取和全部数值。姿态往返最大误差 2.11e-15。
- 独立审查曾发现指标、来源绑定和 DataEnd CRC 的检查不足，已补入可重复读回；另有 8 项转换边界、4 项语义/CRC 负例通过。
- EpisodeReview 的 28 项 Jest、定向 ESLint/Biome 和生产构建通过。独立检查 JPEG 全帧流与原视频重新转码一致。
- MCAP、视频、报告、日志、依赖、构建和浏览器截图均被 Git 忽略。公开源码不含本地 manifest 或原报告路径数据。

## Browser acceptance

在独立 Chrome 153.0.8010.36 / headless 软件 ANGLE 下运行，未使用日常浏览器资料。以下报告位于 `apps/fishbot-control-station/workbench-review-tests/output/`。

- `baseline-a`：原版 5 项通过，只证明原生读取和播放。
- `full-c`：最终桌面 11 项通过，203 个请求。首帧即显示 RGB；图像、物体 3D、双指力、关节曲线和回合面板已读取真实数据。前后 seek、播放暂停、分割面板、保存后不带 layoutUrl 重载、移除后保存重载均通过。
- `mobile-b`：最终手机浏览器仿真 9 项通过，57 个请求；实际 CSS 和 visual viewport 均为 390×844。首帧、报告、播放暂停、滚动及点击阶段到 64.44 秒通过。
- 两轮 pageErrors、consoleErrors、写请求、外站请求和 WebSocket 均为 0；输入资产起止不变。
- 根独立查看起点、持物 14.38 秒、落定 64.44 秒和手机截图。三维方块完整可见，桌面三处离画布边界至少 62 像素；录像与物体变化、阶段一致。
- 最终报告摘要：full-c `7cc0895ca5b1f6adb6ce2297002c190ffefd4f64881e52135a640d72b335fa97`；mobile-b `1a151fd5eee4e07aad783b0d0498bd26bf9cf48ea458da36669eb6138f20618d`。

保留失败证据：full-a 行为通过但坐标轴过大、中心字段错误；full-b 起始物体贴边。调整原相机配置后才通过 full-c。mobile-a 实际 CSS 宽 980 像素，被独立审计否决；补原生 viewport 后才通过 mobile-b。手机底部次要同步/速度选项仍有裁切，已测核心操作可用，不宣称完整手机编辑器。

## Remaining and ownership

- 历史回放通过不等于新的抓放成功。当前 3D 只有记录中的物体姿态，全臂看同步录像；全臂 FK、跨回合换源、实时连接和性能未验收。
- P2/P3 的入口差异见 findings：FishBot 有 runtime 和协同控制合同；独立 SO101 full_cycle 缺已核实的 HTTP 启动、协作取消及查询适配。根 Codex 与原模块 owner 接续，保留原任务账本与物理评分。
- 原 FishBot 根仍在运动路径验收。隔离分支不合入其 dirty main；待其可交付基线后串行整合。保留原未提交改动，不替代其测试结论。
- CY 未部署，旧站点未切换，手机真机与长期性能留后续。

## Knowledge closeout

`already_covered`：CapMesh PIT-004 已覆盖依赖与发布周期隔离；本轮源码、时序、视口和接口边界记录在项目计划，没有新增通用平台或全局规则。

## 2026-10-20 场景与程序编辑接续

用户要求继续修改项目，尽可能复用 CY 成熟产品成果。沿已有 Lichtblick 底座新增 RobotStation 原生面板，采用 RoboDK 对象树、坐标系归属、目标引用和指令列表设计。布局、保存、播放器和历史回放继续使用上游实现。

本轮编辑范围：平移坐标系、对象/目标/障碍、世界位置保持的重挂父节点、指令排序、撤销重做、人可编辑 JSON 导入导出。坏条目警告并局部跳过，无内容哈希锁、前序任务锁或每日限额。

新入口 `/so101-station`；窄屏 `/so101-station-mobile`。俯视虚线仅是程序顺序，右侧录像仍是历史回合。未定义旋转坐标系、工具 TCP、碰撞规划或执行适配，不能将草稿标为可执行任务。P2 部分实施，P3 未完成。

验证：10 项局部单元测试、生产构建和定向 ESLint 通过；桌面/390px 共 11 项浏览器交互检查通过，编辑/撤销重做/步骤排序/导出/刷新后的完整 JSON 一致/手工导入/坏 JSON 保留草稿/手机编辑均覆盖，pageerror 与运动写请求为 0。最终截图与结果位于被忽略的 `workbench-review-tests/output/station-editor/`。构建保留上游两项包体积警告，不宣称加载性能通过。接续 owner：根 Codex。独立 SO101 full_cycle 仍要求已有 motion-plan/preflight，不能直接消费任意新坐标；需在 SO101 侧接入重新规划及原任务生命周期。

Knowledge closeout：already_covered。继续采用 CapMesh PIT-004 的 Web/机器人依赖隔离，不新增通用知识规则。

本轮修复：上游 `isLayoutEqual` 忽略基线配置中不存在的新键。最初布局只有面板标题，导致 `station` 内容无法保存。两个入口布局现包含完整初始 station，面板默认配置也包含 station；保存通过原 `updateLayout` 与 `overwriteLayout`。移除当前地址的 layoutUrl 后刷新，不再重新导入初始模板。相关原生比较回归有 2 个测试。失败试验未误记为通过。
