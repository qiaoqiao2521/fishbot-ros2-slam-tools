# 地图规则与巡航模板

本功能借鉴地图编辑与预约的产品语义，复用现有 `/simulation`、mission bridge、Nav2 KeepoutFilter 和 FollowWaypoints。同一地图标注用于执行规则和独立验收，后续可作为训练场景输入。本阶段没有训练策略权重，没有操作已售实车。

## 操作

1. 进入控制站的“仿真巡逻”。
2. 选择“虚拟墙”，依次选择两个端点；或选择“禁区”，选择矩形的两个对角。
3. 检查草稿；用“撤销”“重做”“移除”或“恢复已保存”调整。
4. 点击“保存规则”，等待“导航已应用”。
5. 切回“巡逻点”，选择航点并填写路线名称。
6. 点击“保存当前路线”。保存和载入只改变路线草稿。
7. 点击“开始巡逻”执行；取消沿用现有任务终态确认。

桌面支持方向键移动选点十字、回车或空格选择；手机使用触屏选点。观察模式不创建草稿或发送动作。规则没有应用、存在未保存规则草稿或规则回执未知时不能开始新任务。模板保存回执未知只阻止重复保存模板；已确认的巡逻草稿仍可显式派发。

路线使用地图选点或已保存模板，不再提供写死坐标的三点演示入口。目标检查覆盖车体范围，也检查勾选返航时自动添加的起点；目标中心在规则外仍可能因车体重叠而被拒绝。

## TypeScript 模块与原执行链

`patrol-mission.ts`保留纯TypeScript草稿和演练状态机。演练支持连续停留、暂停、期限、闭环距离与显式出发点；它的completed不代表ROS动作成功。页面用其`toMissionPayload`生成现有任务请求，实际索引、取消和终态仍取原MissionBridge。任务耗时按同一任务ID与地图匹配`/runs`记录，终态等待相同状态记录后冻结；缺失记录不猜起始时刻。

`toNav2GoalPayload`生成标准`PoseStamped[]`，包含map帧、明确时间和偏航四元数；默认零时间不冒充当前时刻。现有HTTP任务暂不支持逐点等待和循环，导出会明确拒绝这些配置。原生有限循环需显式次数；逐点等待、无限循环、循环加一次性返航不能静默丢失。页面派发期限为360秒，不放宽原几何或物理评分。

`map-zones.ts`处理接触、共线和可选圆足迹，并隔离全部输入、返回值和撤销历史。页面使用原规则DTO转换与半径0.13米的路径提示。点间直线可能被Nav2绕开，因此提示不阻止合法派发，也不代替真实碰撞层。规则草稿重做跨相同轮询保留，新编辑、确认保存和地图切换清空历史；保存未知时不允许重做。

“导出 Nav2 规则”只下载当前已应用版本实际发布的`CostmapFilterInfo`和`OccupancyGrid`。GET `/sim-api/map-rules/export`复用原栅格器和ROS标准序列化；前端校验地图、版本、消息形状和迟到回复，不另造栅格协议。导出不会发布或派发。后台暂不支持的任意多边形、no_clean及speed类型明确拒绝转换；当前只交付wall与矩形no_go的keepout链。修复与实际122验收见[本轮进度](../plans/navigation-modules-repair-20261016/progress.md)。

“本次出发点”在点击“开始巡逻”时，从新鲜的 `map → base_footprint` 定位捕获坐标和朝向。返航目标、任务与持久化记录使用同一快照；执行和取消期间保持不变。空闲时地图预览当前定位；定位不可用显示“等待定位”，不会回落到地图原点。地图标签常驻显示，侧栏“定位本次出发点”只聚焦地图。

路线模板只保存用户航点与返航开关，不保存当时的出发点。每次执行重新捕获；回执未知时按该任务的 `start_pose` 对账。旧记录缺少快照时保持缺失，跨地图隐藏旧点。当前出发位置若与软件规则重叠，返航仍会明确拒绝；按提示调整冲突规则或取消本次返航选项。

几何拒绝返回可选`issue`：明确的航点序号或自动返航起点、米制坐标、规则ID/类型/当时列表编号、距阻挡边缘净距、所需车体半径、净距差额和最近阻挡位置，并绑定校验时地图与规则版本。占用格、未知格和地图边界也给出具体位置；地图格沿原校验顺序报告首个命中格。中心已经越过边界时不显示误导性的距离差额。原错误文本、状态码和派发前`outcome=rejected`保留；诊断字段异常不改变明确拒绝的交付判断。

网页提示精确到点位和规则；“在地图上定位问题”仅聚焦地图，显示拒绝点、实际校验范围和冲突规则。当前标红绑定派发时路线、地图和规则快照。编辑后旧坐标改为琥珀色历史标记，不标红新点位或新规则；不同地图隐藏标记。墙的中心线与墙边净距区分；显示净距向下、所需范围向上取精度。旧后端没有`issue`时保留概括提示。

## 本机页面运行

当前本机5179页面使用 `VITE_FISHBOT_SIM_DOMAIN=107 npm run build` 生成的生产包，通过既有 `npm run preview` 与原代理提供服务。它避开已观察到的 React 开发版 `Performance.measure` 数据克隆路径；不是生产托管配置或浏览器长期稳定性的证明。开发时仍可使用原 `npm run dev`。切换后刷新已打开的页面，才能加载新包。

## 原生 RViz

`/simulation` 标题旁的“打开 RViz”在控制站电脑打开原生窗口。窗口直接读取同一 ROS 域的 `/map`、`/scan`、`/robot_description`、global/local costmap 和 `/plan`，使用 `/clock` 的仿真时间。MuJoCo 模拟车体与传感器，ROS 2、DDS、Nav2 和 RViz 为本机真实进程。

GET `/sim-api/rviz` 读取本机可用性、进程和域；POST 仅接受 `{}`。服务端固定域、可执行文件和视图配置，不接收网页命令或路径。复用 Linux 用户 systemd 的 `fishbot-rviz-domain-{domain}.service`；同域重复点击复用进程，关闭后可再开。没有桌面、RViz 或配置时明确显示不可用，导航接口仍可用。启动回执未知只 GET 确认，不自动重复 POST。

`rviz:=true` 和网页按钮使用同一 `config/simulation.rviz`。查看窗口本身不派发任务；RViz 的 Nav2 Goal 和初位姿工具由用户显式操作。实际窗口截图与独立 ROS 订阅证据留在本机，见本次进度。

## 数据与坐标

规则包含 `id/kind/points`。`kind=wall` 为两点线段，声明宽度默认0.02米；`kind=no_go` 为四点矩形。形状与用途明确保存，不依赖点数猜测用途。所有坐标均为 `map` frame 的米制世界坐标。地图内容SHA绑定尺寸、分辨率、原点和栅格，地图变更清除旧编辑草稿，存储按地图标识隔离。

最多64条规则、100条路线模板、12个用户航点。规则提交使用 `map_id/base_revision/zones` 做版本比较；冲突保留草稿，要求读回后重新编辑。活动或终态未知的任务期间拒绝改规则。路线保存不派发；每次任务实例绑定实际使用的地图与规则版本。

## Nav2集成

`map_rules` launch参数默认跟随 `bridge`。不开bridge时使用原参数文件；开启时在本机运行目录生成独立配置，仅增加global/local的 `keepout_filter` 与后置 `keepout_inflation`。输入和生成文件SHA保存在邻接 `.source.json`。原plugins、footprint、速度、目标容差和RPP碰撞检查保留。

bridge发布可靠、transient-local、depth1的 `/keepout_filter_mask` 和 `/keepout_costmap_filter_info`。软件规则不改MuJoCo实体、雷达回波或AMCL原地图。旋转原图先转换为世界轴对齐mask，避免Jazzy KeepoutFilter忽略mask origin yaw。

mask仅包含禁区几何和半格对角栅格余量，不能再次扩张机器人半径。后置原生InflationLayer沿用原障碍膨胀参数（基础场景0.30米、代价因子4.0），给中心规划器提供梯度；局部RPP仍核完整车体外廓。API目标核原0.13米圆形足迹；独立验收读取原生footprint与padding，当前基础场景使用约0.144142米的保守外接圆评分。线墙声明宽度不等于额外车体余量。

“已保存并发布”与“导航已应用”分开。应用确认核对当前发布的地图/规则版本、过滤器参数、两节点生命周期、真实订阅和原生GetCostmap格值。Nav2没有原生revision回执，订阅数或HTTP成功不能单独作为确认。新增与删除都必须读回；移除全部规则发布全0mask，只删除一项时保留其他规则。查询短缺保留等待，不把正常Nav2清图恢复当成永久失效；确认的持续失配置与持续有效反证分别收束。同版本删除事务在两张代价地图、配置、生命周期和订阅首次完整确认后结束；后续新障碍观测不能撤销已确认的删除。当前规则持续核对，下一版本重新建立删除验证。

## 接口

| API | 行为 |
| --- | --- |
| GET `/sim-api/map-rules` | 返回地图标识、revision、规则、发布/应用状态。 |
| POST `/sim-api/map-rules` | CAS保存并发布软件规则；不发送运动。 |
| GET/POST `/sim-api/routes` | 读取或保存当前地图的路线模板。客户端ID用于未知回执的读回比对。 |
| GET `/sim-api/runs` | 读取最多50条真实任务实例，包含任务状态、首次停止原因和规则版本。 |
| POST `/sim-api/mission` | 原有巡逻接口；可附 `map_id/rules_revision`，发送前校验图与当前应用版本。 |

明确发送前拒绝使用 `outcome=rejected`；发送后异常和持久化结果不明仍保留未知，不自动重试状态变更。禁止用旧idle状态或同名旧路线推断新请求没有执行。

## 存储与训练边界

规则、路线和任务记录默认保存在 `~/.cache/fishbot/map-rules/domain-{domain}/`，可通过 `FISHBOT_MAP_RULES_DIR` 指定独立本地目录。内容原子写入，损坏时明确报不可用并保留原件；不入Git。进程重启前未确认终态的任务标为unknown，不恢复或重发，目前无丢失handle后的自动对账入口。

任务记录是紧凑执行摘要：事件、实际速度命令、估计位姿、仿真真值、扫描摘要和截取路径。活动观测约1Hz、最多300份，终态保留末60份。它不是时间对齐的完整 `obs/action/next_obs/done` 数据集，也不是独立物理评分。后续训练仍需统一episode、完整传感采样、随机化、训练/留出场景与策略对照。

## 验收入口

离线回归：`./fishbot.sh check-feedback`。原生验收只连接明确选择的、空闲的隔离合成场景，修改该实例规则并发送有界任务：

```bash
export FISHBOT_MUJOCO_DOMAIN_ID=107
export ROS_STATIC_PEERS=''
source tools/fishbot_mujoco_env.sh
python3 -B tools/fishbot_map_rules_acceptance.py \
  --domain 107 --api http://127.0.0.1:9079 \
  --output /tmp/fishbot-map-rules-acceptance
```

输出目录必须是仓库外的新目录。脚本要求合成arena初始位置和空规则，保留已有编辑而不清除。运行要求没有其他任务；失败保留证据，仅取消已确认归属本次验收的任务。取消结果未知不能算停稳。

完整触屏与模板执行验收使用配套入口。要求Node、已有Playwright模块（必要时通过`NODE_PATH`提供）及独立Chromium可用；只操作新建的隔离浏览器，不使用日常登录态：

```bash
python3 -B tools/fishbot_map_rules_ui_acceptance.py \
  --domain 107 --api http://127.0.0.1:9079 \
  --web http://127.0.0.1:5179 --chromium /path/to/chrome \
  --output /tmp/fishbot-map-rules-ui-acceptance
```

此脚本沿用前述localhost/domain环境。它要求合成arena的临时测试区`[2.0,2.3]×[2.0,2.3]`及栅格余量内81个原生全局采样点全部为0，否则拒绝测试。保留现有规则与模板；只移除自己新建的规则。触屏保存两点模板、丢失实际保存回执并按ID读回、载入后核坐标/yaw/返航选项、只点击一次开始，并核对真实任务和独立真值。固定航点用于穿过已删除的旧验收矩形，不能直接用于任意家庭地图。

删除软件规则不能清空后续扫描形成的软膨胀。实际mask须为0，原生点代价须低于253，并保存实际成本；253/254/255仍拒绝。原生删除用例另证0→254→0。时钟连续性、按序到点、终点15厘米/0.30弧度及完整0.7秒停稳门限保持原值。

实际结果、运行身份、桌面/390px截图、源码绑定与未验收边界见 [本次进度](../plans/fishbot-map-rules-20261013/progress.md)。全局与局部禁区语义参考 [Nav2官方文档](https://docs.nav2.org/rolling/tutorials/general_tutorials/navigation2_with_keepout_filter/navigation2_with_keepout_filter/)。
