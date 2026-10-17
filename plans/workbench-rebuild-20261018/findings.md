# 重构发现与采纳依据

## Current source

- FishBot当前起点：`e52223b746f4fbd939774aca35c0fa4a9b4771c2`，main，工作区干净。既有远端为 `qiaoqiao2521/fishbot-ros2-slam-tools`。
- cy成果：`/opt/re-workbench`，master `eb674a66c45c85e91b589f30ca42c2cef29db9ce`。只读SSH经Tailscale；没有修改服务、网络或研究目录。仓库已有dirty/未跟踪brief不参与本地交付。
- 本地实际页面：5180 `/workbench` 与 `/simulation`。首屏为成果长页；巡逻地图被标题、状态和编辑提示下推。截图属于此次只读观察，不是新UI验收。

## 商业成果采纳矩阵

| 来源 | 已核实事实 | 本项目采纳方向 | 不直接采纳 |
|---|---|---|---|
| `mihome-probe` | 内置spec插件有地图编辑模式、草稿、按变更显示完成、保存与状态门控 | 上下文编辑工具、草稿事务、具体对象提示 | 离页清草稿；厂商数量常量；未确认保存回执语义 |
| `restricted-zone-pilot` | 石头4.74.08线墙、四角禁区、编辑/只读结构、单会话请求关联 | 统一对象选择与几何表达；呈现层区分编辑/观察 | 把传输ACK当已应用；固定10秒作为全局策略 |
| `unitree-web-loader` | 模型注册表、GLB/URDF链路、点云Worker和独立连接提示 | 模型/关节配置数据化；加载和渲染可独立恢复 | 私有整包、无reject的加载Promise、厂商坐标偏移与恢复常量 |
| `product-patterns/async-operation.md` | 原创条件化设计规格，未交付运行时 | 统一结果未知、迟到回执和取消呈现 | 将规格当成已实现通用引擎 |
| `roborock-g3db` | 两份完整样本的只读格式解析 | 后续资产检查候选；首轮无必要依赖 | 商业家具模型直接分发；推断单位/动画语义 |
| `ecovacs-map-codec` | 本地有界LZMA示例，来源未核验 | 输入边界检查思路 | 当原厂协议适配器替换现有ROS地图 |
| `dreamehome-probe` | 插件化架构与通道静态线索 | 保留研究来源 | 宣称已有可用地图编辑器 |

上轮限定解析测试34项通过：Unitree 15，G3DB 11（含两份完整样本，0 skip），codec 8。它们不覆盖商业运行行为或FishBot UI。

### 定位证据

以下路径以cy成果根为基准；原样本不复制入本仓：

- 米家实际临时解包文件 `/tmp/t7/spec-main.bundle`，约601046–601340行：草稿、zoneChanges与保存；约274675行：位置检查。SHA前缀 `38f58139`，完整指纹回源研究记录。
- 米家 `getWarnStr` 开头直接返回null，后续数量提示不可达；充电桩检查被逗号表达式丢弃。不能把模板10/10/1或提示文本当作已运行的完整保护。
- `assets/js-bundles/unitree/dist-decrypted/js/robot/RobotModelLoader.BK0VqEMu.js:436`：模型注册表；457起为一次性URDF Worker。
- `assets/js-bundles/unitree/dist-decrypted/assets/main-LIOZh9o1.js:18646`：点云Worker与连接恢复分层；17967起的loadPCD缺拒绝路径。
- 研究README可能概括过强，采纳以具体代码与本地验收校正。商业规模不等于每段代码无缺陷。

## 当前实现与缺口

- `frontend/src/App.tsx` 统一五路由及StationFrame，但工作区仍按独立页面组合；跨地图/巡逻/协同缺共享选择和环境上下文。
- `components/workbench/workbench-page.tsx` 同页排列成果流程、语音、能力验证、验收、经验和下一步。成果信息挤占操作入口。
- `lib/patrol-draft-cache.ts`、`hooks/use-patrol-draft-cache.ts`、`lib/route-safety.ts` 已有版本/缓存/足迹保护，不能把商业样本的更少校验当升级。
- `lib/cooperation.ts`、`lib/cooperation-frame.ts` 有任务/回合隔离与新帧解码替换。可以重构归属，但需迁移这些行为。
- 现有Java/SSE station、仿真HTTP轮询、cooperation和voice控制器各自处理连接、状态和命令。需逐项抽取共性，不抹平原生能力差异。
- Java导航发布与Python FollowWaypoints的回执层次不同。统一接口必须保留“发布完成”与“原生接纳”的差别。
- SpatialLM/视频直链使用loopback，非本机hostname会禁用。远程工作台需明确部署配置和服务身份，同源地址配置不能伪造工具已上线。

## Open-source selection

2026-10-18以官方仓库/文档核验。当前React19.2、Vite7、Zustand5未依赖下列新组件；本轮没有安装或宣称浏览器兼容通过。

| 组件 | 官方事实与来源 | 本轮选择 |
|---|---|---|
| Dockview React | [8.6.0](https://github.com/dockview/dockview/releases/tag/v8.6.0)，2026-10-16；[MIT核心与Enterprise区别](https://dockview.dev/docs/overview/licence/) | 桌面布局直接复用核心；不自建通用布局引擎，不依赖商业layout history或高级键盘docking |
| Three.js | [r186](https://github.com/mrdoob/three.js/releases/tag/r186)，2026-09-24；[MIT](https://github.com/mrdoob/three.js/blob/dev/LICENSE)；[官方PCDLoader](https://threejs.org/docs/pages/PCDLoader.html) | 按需加载3D模块；直接用官方GLTF/PCD加载器 |
| URDFLoader | [0.13.1变更记录](https://github.com/gkjohnson/urdf-loaders/blob/master/javascript/CHANGELOG.md)，2026-07-08；[仓库与Apache-2.0许可](https://github.com/gkjohnson/urdf-loaders) | 只补FishBot模型、坐标/关节映射；资产许可单列 |
| Foxglove | [当前更新](https://docs.foxglove.dev/changelog)与[开源Studio边界](https://foxglove.dev/blog/foxglove-vs-foxglove-studio-two-years-on)；[React Embed](https://docs.foxglove.dev/docs/embed/react-sdk)需Pro/Enterprise/Academic | 不当作免费独立3D React库；本轮核心不依赖账号/付费资格 |

[Dockview渲染文档](https://dockview.dev/docs/core/panels/rendering/)明确：默认隐藏会移出DOM，尺寸可能为0；always保留DOM但不停止面板逻辑。采用工作台级业务owner与面板可见性事件暂停渲染。布局只保存展示设置，不保存任务副作用。

比较结论：CSS固定布局适合手机和受限预设；桌面多视图的分栏/序列化优先Dockview核心。Three/URDF提供已有模型解析能力，自有代码只处理ROS数据映射。整套Foxglove嵌入和新调度平台均没有本轮必要性。后续若兼容实测不通过，记录具体缺口后调整，而非因框架偏好重写。

## 底层审查落点

以下均为当前源码结构证据，尚未实测为延迟或丢包根因：

| 问题 | 当前落点 | 重构目标 |
|---|---|---|
| 域和地址分散 | frontend `lib/simulation.ts:47`、`lib/cooperation.ts:1`、`lib/voice.ts:1`、`vite.config.ts:18` | 运行时发布环境身份与能力，页面选明确runtime，不以一份构建隐含混域 |
| 示例与实时来源有全局混合标记 | `store/station-store.ts:51`、`hooks/use-station-bootstrap.ts:56`、`lib/api.ts:12` | 每资源运行时校验和来源/龄期/错误，示例不冒充实时 |
| 重复命令竞态处理 | `hooks/use-simulation.ts:108`、`lib/cooperation.ts:219`、`lib/voice.ts:184` | 共享transport与回执投影；业务adapter保留原生能力差别 |
| 发布成功与动作接纳不同 | backend `web/ControlController.java:38`、`service/NavigationStateService.java:209`；mission `scripts/mission_bridge.py:1241` | 不把Java HTTP200及全局status_list当原提交UUID的接纳 |
| 传输无统一采样与丢弃统计 | backend `service/ConnectionStateService.java:100`、`service/EventStreamService.java:47`、`ros/RosbridgeClient.java:156` | 按资源采用版本更新/最新值/事件序列；检查emit结果并显式记录gap |
| owner职责过多 | mission `scripts/mission_bridge.py:321,994,1427`；`tools/cooperation_bridge.py:94,1409` | 拆ROS、状态机、快照、HTTP和证据；一轮仅启一个动作owner |
| 人工停车和序号语义不足 | backend `service/ControlService.java:17,98`、`service/RosTopicService.java:39,116` | 控制权/有效期/停车分层，连接最终守卫后端到端验收 |

frontend/backend分别相对 `apps/fishbot-control-station/frontend/src/` 与 `apps/fishbot-control-station/backend/src/main/java/com/fishbot/station/`；mission相对 `workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/`。原类和文件并非必须保留。

## Adopted knowledge

- CapMesh D021与PIT-001：按缺口复用；避免没有收益的第二语言平行重写。这里用于约束选型，不限制用户已授权的底层重构。
- 知识库 `Wiki/ROS2 与 FishBot` 第18节：草稿revision、规则版本与任务UUID分开；规则与实体障碍分开；诊断绑定原草稿。
- 同页第19/20节与项目COOPERATION合同：scene/episode、原生动作、交接与评分分开，渲染与控制分别恢复。
- 同页第17节与日志容量计划：普通诊断有界，完整取证超限明确失败，不让重构重新引入无限日志。

## Unknown

- 新布局、3D和数据通路的实际性能尚未测量；浏览器截图不证明长期稳定。
- 后端职责拆分方向已确认；P1实施时冻结具体schema与模块边界，Java保留adapter或退休按兼容迁移证据决定。
- cy没有新的FishBot部署验收；本计划不自动把研究服务器变成机器人网关。
- 原视觉11失败仍存在；UI和架构重构不改其评分。
