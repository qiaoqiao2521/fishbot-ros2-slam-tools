# 实施发现

- 官方源码归档固定为 `95713edb309d77589b130286642ab149995a5f7b`，17,376,926 字节，2,297 个源文件；来源和摘要在 `apps/fishbot-control-station/workbench/UPSTREAM.md`。
- 本机 Node 22.23.2；上游 packageManager 为 Yarn 4.17.0。AGENTS 的 Yarn 3.6.3 文案已落后于固定配置。
- 直接启动 Yarn 被上游 wrapper 拒绝，因为缺 Corepack。实际 Corepack 启动又受 `/home/muqiao/package.json` 的 ESM 作用域影响，报 `Dynamic require of util`。隔离 `COREPACK_HOME` 并声明其 CommonJS 作用域后，Yarn 4.17.0 正常启动。没有修改该主目录配置。
- 源码依赖使用 shared Panel、MessagePipeline 与 Player。最小任务面板直接使用原接口；注册、默认布局和深链已有实现，不新增状态总线。
- 原 FishBot 对话仍在修运动规划。新工作树使用明确已提交基线，尚未引入其未提交源码或修改运行服务。

## Knowledge

采用 CapMesh PIT-004 的依赖/发布周期隔离与现有任务身份复用。收尾为 already_covered；不把一次构建故障提升为新通用平台。

## P2/P3 已核实的接入合同

- `GET /api/v1/runtime`、`/sim-api/runtime`、`/coop-api/runtime`、`/voice-api/runtime` 已有只读身份与能力入口。它们由各自服务拥有，不能按端口或domain拼成同一环境。本轮查源码，未宣称CY进程可达。
- 原 `frontend/src/lib/runtime-context.ts` 的 RuntimeRegistry 和 runtimeFetch 可移入原生面板；原 `frontend/src/lib/cooperation.ts` 的 CooperationController 可在应用层单例复用。只做路径和配置适配，面板订阅同一个owner。
- `POST /coop-api/start` 只接受 `scope=dock|transport`（`tools/cooperation_core.py:163-192`）。transport包含车体停靠、机械臂装车和车体运输，不是独立SO101 full_cycle。
- `/coop-api/state?task_id=`只返回当前快照，客户端必须核对返回ID；历史最多10条。取消接纳、canceling和实际停稳必须分别显示。实例请求头 `X-Fishbot-Instance` 沿用原合同。
- 模型catalog是静态历史结果目录，不等于可以启动任意模型的运行时注册表。不得把已有录制成功当成按钮触发的新推理。
- SO101 `experiments/graspgenx-demo/full_cycle.py` 已有严格绑定motion plan/preflight的CLI。其 `--output` 参数指已审核候选目录；实际产物另建子目录。当前未找到独立HTTP runtime/start/cancel/task lookup与协作取消hook。
- 下一步由根与SO101模块owner接回现有CLI生命周期；不得以杀进程冒充取消落盘，也不得用协同transport接口替代独立抓放。FishBot原根仍在验证运动路径，合并须等其可交付基线，保留在途改动。

## 视觉人工审查

浏览器full-a的9项行为检查通过，但默认三维坐标轴尺度过大、相机中心使用错误字段，人工视觉验收未通过。已依原CameraStateSettings改用targetOffset，并将坐标轴缩到0.03；最终验收须绑定修改后的布局。

桌面保留五面板。手机使用同一底座的双面板布局，集中录像和阶段结果。新用户默认秒显示并折叠侧栏，原持久化偏好保持优先。

full-b仍有初始物体贴边，已将相机distance调到0.8m。mobile-a发现无viewport声明，CSS实际宽980px；该轮不计手机通过。已用原HtmlWebpackPlugin配置增加device-width，验收脚本明确核对实际390×844，并检查物体起点/持物/落定三处的完整可见边界。

最终 full-c 和 mobile-b 分别通过 11、9 项检查，根已目视核验截图。手机底部次要同步/速度选项有裁切；已验证的是录像、报告、播放暂停和阶段定位，不包括完整手机编辑。实际跨回合换源及实时连接留后续。


## 2026-10-20 现有执行器接入结论

旧GraspGenX full_cycle以冻结motion-plan/preflight为入口，不适合直接接受编辑草稿。现有 run_visual_grasp.run_physical_episode 已有RGB定位、IK/OMPL、物理控制和原评分，仅缺场景/进度/取消等注入点。本轮新增可选hook和薄station_executor，无需另写控制器，也没有引入内容哈希门锁。

FishBot coop-api的transport仍是车臂协同任务，不能替代SO101独立抓放。新 `/api/so101/` 适配只有本机CLI生命周期和产物读取，worker status.json是执行状态来源，未新增通用调度/认证平台。网页运行输入是独立快照；后续编辑不会修改已启动任务。

固定八步模板当前只支持方块XY各±10mm和50×56×130mm附加障碍。设计目标高度与执行器指间高度不同，运行能力描述明确映射；不支持的节点、世界位置、步骤重排和时长会具体拒绝。第一次新CLI释放后再接触失败，复用已有floor_yaw/28mm后新CLI及浏览器实际完整回合均通过，原物理阈值保持。

## 2026-10-20 原生实时三维复用

- 已安装的 `@foxglove/ws-protocol@0.8.0` 和 `ws` 可直接提供标准 Foxglove WebSocket；原生3D接受 `foxglove.SceneUpdate` 和同源原STL，不需要再造播放器、模型加载器或渲染器。
- 原SO101模型含13个原STL、17个视觉网格实例。MuJoCo编译mesh后会重心平移/旋转；向浏览器服务原STL时只反解该变换一次，独立XML姿态对照误差≤2e-12。
- 编辑预览只做`mj_forward`，任务场景只读执行中的`MjData`。终态在后置录像编码前捕获；相对URL统一由本机STL白名单服务。缺少新scene字段的旧任务不虚构全臂姿态。
- 模式切换必须使慢预览请求失效，包括重新选择同一个任务；Node回归覆盖新ID/同ID交错。普通preview POST本身不切模式，任务中编辑草稿不发预览请求。
- 本机浏览器确认world坐标已被原生3D识别；原生面板在首消息前保留过No coordinate frames/Frame world not found的启动日志。完整模型随后正确渲染，不把这些历史日志当持续物理失败。手机截图需等待13个STL加载，不能只凭canvas存在验收。

## 2026-10-20 任务目标参数化缺口

现有限制有两层：station_executor固定节点/八步验证；VisualGraspController的搬运末三点固定PLACE_CENTER，异步worker也需传目标。原场景与planning clone都从同一workcell生成，因此优先增加可选place_xy并共享该场景，不复制场景实现。物理diagnostics原来按固定中心判盘内，必须同步按实际place_floor位置评分，保留原边界与静稳阈值。


### 参数化后的实际路径缺口

新目标(.22,.17)已放盘但固定37mm脱离触腕限，34.154mm前缀在原全臂/释放物1mm与回位检查下可认证。(.20,.20)的28mm释放目标可达，但60/57mm中转不可达；54mm完整五段通过。故保留60/37mm优先，复用原IK与全arm/payload样本认证候选，不按坐标特判或扩大关节范围。

独立审核负例发现RuntimeError泛捕获会把未知后端故障当成IK不可达，已限定已知No vertical前缀；未知错误/取消保留原异常身份。默认/B两轮同源码实跑后再加分类补丁；最终A完整实跑与最终B保存snapshot离线逐字段重演覆盖该影响范围。任务变化与性能/模型候选比较分开，不把三回合称统计鲁棒性。


## 2026-10-24 无人机历史诊断复用

- 748原回合保留在drone的output一级记录目录，未出现在网页tasksRoot。通过request.json原ID发现它，与已有任务目录去重；不复制成新任务、不触发派发。
- 原记录含345条真值位姿、346条遥测、8条名义曲线。planner.log可对齐10条失流见证；17条ReboundCollision只有曲线局部时间，不能直接放到绝对播放轴。
- 复用drone-scene、drone-live.sceneOptions和McapWriter；旧flight.mcap生成与新诊断导出共用writeFrames。诊断缓存独立，原记录和旧MCAP不改写。
- 黄线只采样记录中的B样条作显示，不参与碰撞判定。绿线为已保存Gazebo位姿；无真值时明确改为橙色估计，缺备份不补青线。
- 原报告33.452s的planner_emergency、Z最高2.210886m、最终landed/disarmed分别保留。连接期失流不能自动解释巡航期紧停。
- 原生3D的Frame world not found/No coordinate frames为首帧前INFO，官方13网格随后实际加载；未作为飞行错误或新物理成绩。


## 2026-10-24 N0/N1复用与时间边界

复用drone inspection_depth.sample_pixel、ego.frames、rosbag2_py和原生MCAP写出，不新建传感器驱动或播放器。EGO原GPLv3/GCOPTER MIT各自保留；完整GCOPTER和神经策略未接实时执行，旧NavRL缓存当前缺失标待核。

681前视＋648下视的全部1329帧有同源光学PoseStamped，记录/clock包络分开处理墙钟与仿真时间；图像和位姿共同可用时刻用较晚记录时间及clock上界。原包没有CameraInfo，yaml/SDF内参来源明确。光学世界位姿来自原sidecar理想Gazebo定位，不是独立VIO。

前视四像素固定于±25°/±8°，下视独立一束；965hit/2407no_return。原始像素3372个、位姿1329个独立读回通过，转换误差到浮点精度；过期56帧（前26/下30）全部不生成新鲜世界射线。表格保留年龄，MCAP按原659个位姿时刻显示，完整1329源帧另存。合成细柱负例只证明射线间盲区，不能解释为新飞行证据。

独立只读审查仅发现.25s标签/绘图边界不一致，已统一为达到阈值即过期并加局部检查。首次审计因float运算次序产生16条假失败，审计改整数ns后通过；未改原数据/阈值。页面截图颜色检测先误计背景、再过严漏掉抗锯齿像素，原失败产物保留，最终以红蓝相对绿色分量及原生画面核对。知识收尾already_covered，项目数值留本记录。

手机390px真实画面暴露世界尺寸.018m线宽会被缩成子像素，不能仅靠桌面紫线验收。改用原生scale_invariant的2px标注线，测距、源位姿和有效期保持；不因像素不可见调整数据或新鲜门槛。最终桌面/手机证据见progress。


## 2026-10-24 N2分段接口事实

PPoly原系数锚在原knot，截取中段必须平移；normalized_power接物理秒局部系数后归一化一次。原start_pva按PVA行/XYZ列记录，而MINCO读取为XYZ行/PVA列。第6条收到时相位已推进.036s，位置较原起点偏移.05533m；新窗口重算PVAJ，不给旧状态换stamp。

8窗共23段，8/8转换、8/8原离线候选V1.8/A1/Z2.2区间证书clear；原cubic最大J跳变2.268873，只声称PVA连续。PVA拼接误差≤1.48e-15，连续转换误差P/V/A/J分别≤1.02e-15/1.76e-15/1.52e-14/1.31e-13。第8条task/goal空值保持，不归到前七条；archive ID仅定位原包。

没有每窗对应的完整GridMap快照，不套用MINCO静态夹具或稀疏射线充当free-space证据；occupancy unverified、admission not_performed。0.8s只是本次预先固定调用值，CLI允许显式其他正时域，不新增人为上限。首次常量轴Polynomial自动裁剪导致系数长度不齐，2夹具失败/第8条跳过；逐轴补零修复，初次7窗产物保留，最终2检查和8窗均通过。


## 2026-10-24 前缀与S4NU尾的真实区别

原前缀末端PVA/J明确来自参考左极限，不是测量机位；保留原前缀C2，仅切点/尾内声明C3。全拼接V/A/Z与边界复用原审计，水平corridor无证书；代码中的corridor证书本片只检查Z。固定3.5/1/.4对照没有L-BFGS或调参，7生成/4过/3A拒绝；#3/#4/#7 A峰1.674366/1.661290/1.081960，源前缀V/A/Z合格不保证其制动尾合格。第8缺原身份，不派生。

原生MCAP新增/drone/candidates，场景按当前原名义曲线ID选行；替换、无身份和越时域不继承旧候选，实体每帧全清后重发。数学通过用warning，占据未验证/未执行始终保留，紫候选不补成青色历史备份。3D抽样仅展示，判据使用原连续覆盖。

独立只读复核发现合法JSON null或rows内null会导致可选文件阻断原MCAP（500），已验证顶层并跳过坏条目，局部负例通过。首轮像素检查误把工具栏红色日志badge的44像素当残留；查图确认后排除工具栏并匹配实际抗锯齿颜色，原失败QA保留。

agent-link现已加载，qoder同步调用180s超时且get_status确认无活会话；CBC返回done但正文空，均不计审查通过。内置只读fallback完成实际源码审查，根以原生计算/局部检查/真实浏览器独立验收。没有向其他已有对话派发，不扩展认证或外界队列。


## 2026-10-24 Gatekeeper复用与静态滚动选择

官方主仓TRO/a54dac7为MIT的firewatch Julia示例；官方机载master/7c8f87a未提供独立LICENSE，gatekeeper包两处许可TODO。机载默认双积分器LQR前向传播＋离散SFC/终端验收，与本地PVA几何选择不同；不复制机载实现，不继承其安全定理。逐源链接及差异见docs/DRONE_COMMITTED_REPLAY.md。

原CommittedTail的admit未设last_now，首次tick回退可仍track；tick的NaN会覆盖基点。新离线Replay在冻结源外统一检查admission/tick时钟有限高水位。候选拒绝保留旧start本来正确，未将它误列为缺陷。

16个反事实静态情景使用原#6/#7真实系数，但观测/地图是明确fixture；连续重审不采信缓存passed。原#6数学过，#7 A拒绝后保旧相位；新占据使旧证书撤销。动态预测、终端不变集和真实跟踪/飞控采用仍缺，protect不构成安全恢复。
