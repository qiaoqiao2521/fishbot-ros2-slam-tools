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

- 新布局和3D性能已实测；生产软件面板J仍未达100ms。硬件生产long-c已完成1800s并通过原交互、队列、堆增长与生命周期门槛；范围仅限该版本与固定输入，不证明一般长期稳定。
- 后端职责拆分方向已确认；P1实施时冻结具体schema与模块边界，Java保留adapter或退休按兼容迁移证据决定。
- cy没有新的FishBot部署验收；本计划不自动把研究服务器变成机器人网关。
- 原视觉11失败仍存在；UI和架构重构不改其评分。

## P1 实施证据与修正

四服务身份与写入检查已实现。Java只证明topic发布，远端domain/scene/episode不猜测。mission/cooperation/voice当前没有任意task_id查询；descriptor的task_lookup=false。详细owner表见[运行合同](../../docs/RUNTIME_CONTEXT.md)。

真实Java浏览器检查发现：Reactor multicast默认autoCancel会在最后一个订阅取消后停止接纳事件，重开网页不能恢复。改为256条有界缓冲、autoCancel=false，增加断开重订阅回归。第一次发现身份晚于HTTP快照时，需要重新读取五类资源，不能只标stale后等待可能不再变化的数据。

独立评审发现两处竞态：畸形高序号SSE不能提前推进接纳水位；实例改变期间的明确runtime_changed拒绝不能退化为unknown。保留负例，不把错误统一包成结果未知。前端和实际Java DTO验证中另补诊断资源入口校验。

P1没有修改ROS控制算法，也没有运行导航/抓放。domain127仅用于真实mission节点的身份、状态和写入拒绝验证；物理验收仍属于P6。原5180/5181是共享源码的Vite开发服务，前端会HMR；原ROS进程没有重启。

## P2浏览器与P3/P4接续发现

- 关闭视图与业务owner必须独立。React开发StrictMode清理会再次执行，不能让一次清理永久清空仍由布局组件使用的API引用；布局订阅应跟就绪API绑定，可见性通过外部store读取。
- 当前地图禁区后端仅接受轴对齐矩形。P3先提供禁区平移，墙可刚体平移/旋转、航点可改xy/yaw；任意旋转禁区不能只改前端。
- 现有Nav2提交已支持客户端mission_id，运行记录含原生结果。旧前端通过相同航点猜测丢回执任务，刷新后丢失未知态。P3复用原ID和账本查询，不新建执行器。
- FishROS描述许可尚待清，不直接打包到网页；本地SO101源checkout网格为空，运行副本网格来源需逐件核对。P4先使用项目自有简化URDF、真实已有LaserScan/路径/位姿，不将XY摘要冒充三维雷达。

## 原生规划复用与交接

完整运输第二轮超时已复现为RRTConnect可行路径长度变化的一项具体贡献。原SO101模块在同进程仅首次设置随机种子，后续调用继续同一随机流；重复传seed不代表每次重新确定同一路径。

曾试用安装的OMPL 2.0.1 [`PathSimplifier`](https://ompl.kavrakilab.org/classompl_1_1geometric_1_1PathSimplifier.html)，前后均用原SO101逐段验证器检查。四次离线实际规划通过，但`coop128-e`动态跟随未通过，因此已撤回简化实现。Python的allocState由绑定管理生命周期，见[官方绑定说明](https://github.com/ompl/ompl/blob/main/doc/markdown/python.md)。

E的中止前源时间98.78s，原参考位置碰撞余量1.106068mm，实际位置0.873314mm，低于原1mm门槛。98.80s起参考已被冻结到前帧实际位置，不能据此倒推原规划路径违规。该轮实际接触为0；余量不足仍按原标准失败。

当前改为每次在独立纯查询子进程调用原SO101 IK/RRT，固定seed=0为该进程第一次规划。主任务仍持有唯一动作权、原360s总限和hold；等待中持续检查取消、owner和新鲜物理反馈。子进程最多30s，结束并核对query ID后才接纳结果。没有路径简化、速度或碰撞余量调整。5项真实子进程生命周期测试与72项原车臂流程测试通过。另两次固定理想初态实际查询得到同一路径并通过原逐段复验，后续G已完成连续两轮物理运输，完整评分与旧失败分列见progress。

原错误判读及相邻帧订正保存在私有`coop128-e/diagnosis/`。静态有效、原生动作成功和独立物理成功分别记录；任何单次结果不代表统计意义的成功率提升。

源码重建总计划已选择Lichtblick完整Web源码。当前控制合同、真实验收和失败证据作为迁移输入；Dockview/自有Three封装不再是后续必须保留的底座。本轮不在共享开发目录同时导入第二份上游源码。

## 当前实现的取证边界

- 同一SO101进程的第二次RRT查询执行路径由23.166s变成41.302s；首次seed的全局状态使重复回合不同。独立纯查询子进程保留原规划器、精度和速度，固定首次查询并有界回收。原PathSimplifier候选因实际跟随余量不足撤回；不把清理后的冻结reference视作失败前路径。
- 静态场景身份与当前观测新鲜度分开：已散列的world XML身份在reset等待物理帧期间保持；缺帧仍physics=null/ready=false。G两次显式reset及连续运输通过，F的unknown失败保持。
- B07 F轮的主延迟位于服务器enqueue入口标记到ROS drain入口263.626ms；实际HTTP到达约5.339ms，执行0.406ms。该标记早于真正Queue.put与GuardCondition.trigger，故尚不能把此段全部归为回调组等待。该证据排除本次HTTP传输/客户端日志为主段，但不定位唯一阻塞阶段。Jazzy默认互斥回调组与GuardCondition没有优先派发期限；保留原250ms TTL。
- 3D开发模式CPU profile中，React jsxDEV/createElement及ReactElement自耗时约3.332s/17.892s；本地React19.2源码确有逐元素调试栈开销。生产构建可作为交付模式单独验收，但不能据此解释I轮某个183ms长task的唯一函数，也不能转记旧开发面板通过。生产J已冻结实际195项源码/产物闭包，仍未达100ms。后续帧跟踪仅证明新复现中存在延后的主线程帧/RAF，尚无业务JS唯一根因；不得回填I/J或添加猜测补丁。

- 图形设备与浏览器渲染器分别取证。本机NVIDIA设备和驱动可见，但探针b实际仍为SwiftShader；Playwright默认参数还会注入软件后备覆盖。候选启动必须核对真实argv与WebGL renderer，不能用`nvidia-smi`或API成功代替硬件使用证明。官方无X11 Vulkan候选见[Chromium文档](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/docs/gpu/using-gpu-hardware-in-headless-chrome.md)。

- H轮的215.911ms同步区间与上一条人工命令到期重叠。该回合规则目录为空，路径不读JSON、不取文件锁、不重算几何；只有单调墙钟跨度，未测线程CPU与上下文切换。不得因为函数名含rules就认定计算或磁盘瓶颈。拆callback group而继续等待同RLock也不能保证控制时延，并可能占满两个worker、妨碍时钟更新。

- I的三段rules墙钟74.010/229.394/128.458ms，线程CPU只有2.478/7.275/3.185ms。GC各代start/stop均不增、无pending或最近GC2重叠；排除本次段内CPU密集与已观测GC解释，仍未区分I/O、GIL与OS排程。不能据此禁GC、调阈值或将旧H追认同一根因。

## 上游执行器候选

本机rclpy executors.py逐字匹配官方7.1.12 tag；尚无官方GIL yield行。官方[PR1547](https://github.com/ros2/rclpy/pull/1547)已于2026-01-09合入rolling，[Jazzy回补1726](https://github.com/ros2/rclpy/pull/1726)也有同一处理。官方优先`os.sched_yield()`，无接口时`time.sleep(0)`；不调整OS策略，也不保证硬实时。

本机已有较早的async-ready修复，因此1547初始重复入队案例不直接作为本机I的根因。当前最小候选仅在manual配置薄包原MTE调度方法，保留父类spin、shutdown、单spin保护与唯一FIFO；不复制整份executor、不修改系统安装、不新增clock Node或I/O worker。若安装版包含上游yield，重新验证并移除局部兼容层。候选须通过原8例与源冻结验收后才能称修复。

## 浏览器验收工具的网络来源

Chrome153.0.8010.36的2×2探针确认：真实主文档支持本轮同源和跨端口SSE；以`route.fetch/fulfill`合成主文档后，跨端口SSE被`LocalNetworkAccessPermissionDenied`拒绝。CDP发起地址空间由Loopback变为Unknown。三个对照各接收40帧，失败对照没有服务器连接。该结论绑定本次浏览器和拦截拓扑，不声称所有mock页面都会失流。

后续保留主文档的真实网络响应，在首次UI动作前核验`page.goto`返回的同一Response；其它资源继续先核验再履行，尤其避免Worker销毁后才读取其浏览器响应体。不能用另一次GET、磁盘文件或初始HTTP快照冒充原请求或持续SSE。官方接口见[Playwright Route](https://playwright.dev/docs/api/class-route)，网络权限背景见[Chrome Local Network Access](https://developer.chrome.com/blog/local-network-access)。不通过授予额外权限或关闭安全开关修验收工具。

## 收尾复核新增边界

- `voice-real-d`在Node首次预检即拒绝，尚未启动浏览器或发POST。Python早先准入为true，Node原GET未记录完整reason；后续fresh只读为`continuous_quiet_unconfirmed`。待补Python/JS有界只读准入及原status记录。只等明确quiet/cleanup；身份、原owner、STOP和unknown立即失败。执行body生成后保持即时严格复核，不能等待后改issued_at或UUID。
- 旧manual UI mock在勾选键盘checkbox后额外把焦点移到panel，遗漏真实初始焦点。原typing过滤把checkbox当文字输入，阻止方向键。原keydown只检查起动时焦点，缺持按期间焦点离开面板的release。两项是静态可证的UI缺口，不解释原B07采样或TTL失败。修复沿用原租约与代次，需实际浏览器补证。
- 旧`motion-control-panel.tsx`、`use-teleop-control.ts`及其测试不在当前入口可达链。已核135个TS/TSX的静态导入、字面量动态导入与worker URL；未保存build-d完整Rollup模块图，不能声称读取了该图。旧API与store仍服务地图、遥测和诊断，不能整体删除。

E取消链已核为异步请求，没有源码可证的永久自锁。`record_run`确在owner RLock内调用同步`save_run`，包含文件锁、JSON、fsync/replace；`rules_state`本身只读内存，但周期`refresh`会在签名变化后取共享文件锁。只把save搬到线程仍可能让控制线程等待同一文件写锁。现有TriggerRecorder可作有界writer候选；FrameWriter的latest槽仍持锁做IO，ThreadPoolExecutor原队列则无界，均不能直接替换。首dispatch前带规则版本的持久化准入不能悄悄改成异步未落盘。

E没有上述分段计时，文件mtime与超时窗重叠不证明fsync因果。本轮不因猜测改持久化并发模型。现成语音`state`已能将同STOP编号的原`accepted=null/receipt_status`与后续同task/native终态分开呈现；先验收这条只读恢复链，禁止用新STOP补发原取消。原E失败与旧HTTP响应缺口保持。

### B07n与语音原回执恢复

- 主机重启使旧P及产品进程消失，当前状态不证明当时清理完成。新Q仍复现第二lease到期，排除了“只恢复网页即可修复”的解释；不宣称定位唯一原因。
- N的rules同步213ms墙钟/5.7ms线程CPU且GC计数不变。标准单线程executor是原非manual路径；同mutualgroup与RLock下2worker并不自动提供并行业务收益。是否切换需核实际clock/HTTP依赖并做相同面板对照，当前仍是候选。
- 语音现有state已能把原STOP入口回执与当前task终态分开。验收工具只补取证、固定原期限与只读恢复，保留accepted=null和原命令编号。无需新增命令查询端点或重发STOP。

### 标准执行器对照候选

根与独立owner源码核对没有发现必须依赖两个worker的同步等待：业务组和RLock保持唯一owner，只有TimeSource可并发推进。TTL/expiry使用墙钟/单调时钟；ROSclock等待是标准单线程的代价，仍由原双时钟/guard门槛验收。N仍出现213ms等待后，撤下局部yield类，直接复用原baseline的SingleThreadedExecutor，未更改FIFO、GuardCondition、drain4、100msfallback、速度或TTL。原shim保留为历史失败，不把上游PR当本机唯一根因证明。

### Nav2启动失败的DDS边界

F在map_server/change_state、G在collision_monitor/change_state出现`failed to send response (timeout): client will not receive response`，分别阻止定位或导航生命周期继续。45s fresh ACTIVE检查正确拒绝，shutdown之后的context错误另列。R没有该警告且两个manager均ACTIVE。

已核实际加载rmw_fastrtps_cpp8.4.4/FastDDS2.14.6/FastCDR2.2.8。官方[rmw_response.cpp](https://raw.githubusercontent.com/ros2/rmw_fastrtps/8.4.4/rmw_fastrtps_shared_cpp/src/rmw_response.cpp)表明该文案来自响应读者发现匹配等待，发生在writer.write之前；不能称DDS ACK超时或Python CPU根因。客户端并发发现是待核假设，当前日志不含失败request GUID。

官方[participant.cpp](https://raw.githubusercontent.com/ros2/rmw_fastrtps/8.4.4/rmw_fastrtps_shared_cpp/src/participant.cpp)的LOCALHOST分支关闭builtin并显式加入SHM与UDP。官方[环境变量文档](https://fast-dds.docs.eprosima.com/en/2.14.x/fastdds/env_vars/env_vars.html)说明FASTDDS_BUILTIN_TRANSPORTS仅在builtin启用时生效；因此没有把UDPv4环境变量当有效对照。下一候选是官方Cyclone DDS的私有前缀，保留LOCALHOST，不安装全局包或修改网络；实际完成状态回源progress。

## 最终采纳与证据边界

- 人工控制复用标准SingleThreadedExecutor，B07o原八项通过。原TTL/速度/守卫/独立采样门槛不变；单次面板通过不证明旧失败只有一个根因。
- Cyclone DDS的固定官方七包与loopback XML作为可选配置进入项目。H/I各一次启动通过，I的文字语音四项及清理通过；不将两次观察写成普遍可靠性或共享内存因果证明。
- 文字语音取消复用现有state对原STOP编号和原task/native UUID的投影。只修验收工具的异步取证与有界只读等待，不新增执行通道、不回放未知动作。
- 当前G构建通过实际GPU短测。旧long-c为原构建的1800s证据；删除三份旧teleop的F/G共29产物逐字节相同，仅证明该次死代码退休等价。
- 最终1552项反馈、641项完整前端、真实导航/返航/取消和同世界两轮运输分别验收。22项依赖告警、原视觉11失败、独立Lichtblick树的实时控制与CY部署仍是明确边界。
