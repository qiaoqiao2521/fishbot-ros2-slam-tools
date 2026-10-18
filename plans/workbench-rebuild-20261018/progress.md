# 重构进度

## Current

P0/P1已提交推送，P2–P5阶段验收通过。当前源码完成真实导航、返航、运动取消、原任务恢复及同一实例两轮完整抓放运输。P4硬件生产面板已通过100ms交互及真实30分钟长测；P5人工控制八项、文字语音四项通过。最终1552项反馈与641项完整前端检查通过；G生产短测及实验清理完成，P6正在收束Git交付。

原121/122进程在主机中断后已退出，本轮未恢复。临时ROS实例仅由当轮owner启动与清理，不能按旧端口猜测在线。主机重启使manual-runtime-p及旧产品进程消失，不追认P清理成功；B07m零POST/零案例失败保持。Q/R和语音F/G/H/I均已有独立清理记录，最后I的9097/9099关闭、domain129为空；不再启动实验。当前产品为Java8087（PID106778/start361789）和Vite5182（PID38447/start129606）。旧Java37767的SIGTERM/143只证明退出，不推测发送者或原因。G生产预览5187已由原owner清理，5186未操作。语音E/H原失败与I通过分开保存。没有实体操作、固件写入、CY部署或网络更改。

Lichtblick完整源码在独立工作树推进。历史回放、当前Dockview工作面、真实ROS与独立物理评分分别记录，不能互相转记通过。

## Done

### 基线、复用与交付边界

- 已读项目入口、SpecMesh v1.1、用户反馈、CapMesh和选定知识；根串行维护本计划。
- P0规划提交`bf135d0fba8edd042f2e6d4b75206a93428d48e5`，P1合同提交`325fa260096d421d07035c4a64cb765e5006501b`，已推既有qiaoqiao2521远端。后续源码仍未提交，实验期间保持Git身份。
- 商业研究来自cy固定源码与只读页面；Dockview8.6.0/Three0.186.1/URDFLoader0.13.1已核版本与许可证。来源、拒绝的实现和已知缺口见findings。
- 当前全部私有证据根为`~/.cache/fishbot/workbench-rebuild-20261018/`。地图、运行日志、截图、MCAP、JAR和凭据不提交。

### P1 运行身份与命令合同

- 四服务提供独立runtime与能力；网页按实例/场景/回合隔离迟到响应。Java五资源分别记录来源，任务分提交、原生终态、清理停稳和独立评分。
- 修复Java SSE最后订阅退出后不能重订阅，以及身份晚到、畸形高序号推进水位、明确409被误判unknown的竞态。256条有界缓冲，旧实例写入在业务前409拒绝。
- 隔离127真实节点、Java HTTP/SSE及桌面/手机浏览器合同通过，初次打开零写入。证据`actual-runtime-result.json`、`browser-result.json`、`browser-actual-result.json`；不是物理运动验收。

### P2/P3 共享工作面与地图任务

- 桌面Dockview四槽、手机单画布加底部面板；业务owner位于视图外，关闭/切页不重建任务。布局缓存只保存显示配置。`/workbench`与`/simulation`共用地图，历史成果移至`/results`。
- 航点xy/yaw、墙平移/旋转、轴对齐禁区平移、撤销/重做、规则草稿/CAS与原任务UUID恢复已接回。规则与路线版本独立，不以直线预检替代Nav2绕行。
- 实际桌面1440×900画布550px、1280×800为526px；390×844手机452.23px且无横向溢出。`edit-contract-b/browser-result.json`通过11项浏览器流程，21源/输入一致，规则/模板请求由fixture拦截，零运动POST。
- `nav127/ui-a/result.json`真实规则保存→原生costmap读回→删除→模板丢回执恢复→两点单UUID任务通过。原任务`e0d69f61-1413-4da5-8cb2-b71e766a9092`，原生4/0；917真值帧，终点误差0.06624m/0.12085rad、连续静止0.7s。return_home=false，不计返航。
- `nav127/recovery-b/result.json`通过真实返航及运动取消。返航任务`4f7e0595-1e5e-40d2-b338-2a047fccc840`经历丢POST回执、2.828s读取断流、刷新/切路由，仍仅派发一次；原生4/0、位姿误差0.08549m/0.20702rad、真值漂移0.030997m、quiet源2.904s/墙2.910s。
- 同面板取消任务`c781a09c-5766-4fc6-8115-7a5150c56144`在位移>0.05m、速度0.138m/s后取消，原生5/0，quiet源1.322s/墙1.324s。最大接收间隔0.07224/0.05628s；原边界帧与20执行源保留并重评。首次A目标足迹拒绝、零派发失败保留。127已清理。

### P4 三维与图形取证

- 官方GLTF/PCD与URDF加载器已接入项目自有简化模型。拒绝URDF纹理、GLTF images和外部资源；单文件8MiB、PCD声明10万点/显示4096点、路径2000点。Worker一帧执行加一帧最新等待，独立绘制上限20Hz。
- 同尺寸点云/路径复用材质与GPU缓冲；首帧准备骨架与真实绘制耗时分开。缺TF的sensor-local XY扫描不冒充地图坐标或三维雷达。
- 旧B/C通过11功能项与生命周期、失流、WebGL恢复，零动作；旧计时口径不能替代可信输入v3。原A React dispatcher失败与long-a实收约8Hz提前结束均保留。
- 新Native Node SSE固定20Hz加4×1Hz慢资源，保留真实EventSource/输入时间戳。开发G/H/I仍失败；I pointer P95=186.2ms/key=103.2ms、155源一致、零POST。183ms长task没有完整函数栈，不推测唯一根因。
- 生产`scene/preflight-j/browser-result.json`12功能/资产项通过、22实际HTTP资产/3index引用、195项闭包一致、零POST/pageerror；pointer P95=108.8ms/key=65.6ms，仍未达100ms。最慢aria→RAF104ms窗内无≥50ms JS长task，之后的WebGL初始化不倒作为原因。没有1800s结果。build-a receipt SHA`1e3b51a0c68e43de613d19675e5bda6b5a462520dd650c28836133a1f0ebb92b`。
- `scene/production-j-diagnose-a`未完成trace导出；b达到16MiB并dataLossOccurred=true/stream_complete=false。两段新复现aria→RAF102.926/95.122ms，只证明延后主线程帧，不能凭缺失记录排除工作或回填I/J。195闭包一致，浏览器均已退；b审计SHA`e63190679308fe3953c0edd64458675957a5dad08c291d19ed3682bbdd6c34c0`。
- GPU-a被可选CDP接口阻断；b实际SwiftShader且Playwright默认注入软件后备覆盖，不称硬件测试。c用官方Vulkan候选、移除三项默认安全覆盖，一次1.050s获得实际NVIDIA RTX3050 WebGL2、正确像素/零请求、195闭包一致并清理；SHA`d962c5232cb9f767f87e316d62ddd0f61994dc86c570c7067794f0d7314b14c7`。CDP GPU子进程sandboxed=false原样保留；设备存在、硬件上下文和性能通过分别判断。
- harness已新增显式software/hardware面板及C03/C04独立评分，默认software不变。首轮100ms失败不能由长测快样本稀释；C04继续原1800s/20Hz/队列/浏览器GC/监听器门槛。22项纯Node检查通过，不冒充真实长测。
- `scene/preflight-k/browser-result.json`硬件生产短测13项通过；pointer P95=14.7ms/key=10.9ms，实际NVIDIA/Vulkan，195项源码/产物闭包一致、零POST/error、最终隐藏canvas/worker均0、browser退出。result SHA`c749bb7b5700e1219487c8d90f74fe2ab59c117fae7475674b54b62945eba860`；build-b receipt SHA`69c8275fafde33b1dc54e36706639aee578df8a404c0032cf41c8e55b6aa01c0`，当时保留preview5184，现已按owner清理，build-b产物保留。软件J失败不改判。
- `scene/long-b`在前置资产`response.body`读取时target closed失败，约7.3s、0长测样本，尚未开始1800s。22资产已至少一次验过，但旧错误没带具体URL，不能唯一归因；不直接忽略错误。195闭包同、零POST、browser/profile退出、fixture1建1关。原结果SHA`b2bc8e97ceba6948418485d7b0ace8f02e083ddb1bdd8c8ce3498f33372dfcb7`，C04=incomplete。
- 工具改为同一拦截请求`route.fetch`→验证200/原URL/冻结hash→以同一response和bytes履行，再显式dispose；失败保留URL、阶段和原错误。六项资产生命周期回归与原22项检查通过。根已审查SHA`1905cdbebd68640b3f551f1d4d09a13b899f25404df34d3159a4bb42d7379ab2`，授权新build-c/5185及硬件短测；长测仍须新结果，旧失败不追认通过。
- `scene/preflight-l`通过硬件URDF/scan两项后，二维动态路径等候20s超时；0长测样本。17个资产请求均完整履行，没有资产阶段错误；独立SSE offered471，但clients_created/sent均0，不能把初始HTTP水合当连续数据。195项闭包一致、browser已退出；当时源传输边界未定位，后续2×2对照见下条。build-c receipt SHA`f47fab6546bdc99c042c01a32f96f45841526320bc5cf94eab110f4561d04e3a`。
- 后续2×2私有探针8.711s确认：原生主文档配同源或跨端口SSE均40/40，合成主文档配同源也40/40；唯合成主文档配跨端口为0连接/0帧。CDP发起方地址空间从Loopback变成Unknown，明确报`LocalNetworkAccessPermissionDenied`；不是路径几何故障。result SHA`7aff41587e51367481f99ee18f33bf889dee339e220f1f3695a6f479591b12b9`。浏览器/profile/server已退；destroy后的socket close事件未等完即快照，原open_sockets=1取证缺口保留。
- 根审查新的薄修：顶层文档保留原`route.continue`，在首次UI操作前核验`page.goto`同一原生Response的GET/顶层/无重定向/URL/200/index完整hash，不另发GET或合成文档。其他资产保持验证后履行及dispose；不授予网络权限或改浏览器安全开关。新build-d/5187与预检M接续，不能沿用build-c封源。
- 文档薄修后31项Node检查通过。`scene/preflight-m/browser-result.json`13项通过，pointer P95=14.6ms/key=9.7ms；原生SSE125发125收、1建1关，22资产完整验证，195项闭包一致、零POST/error，browser/profile清理。result SHA`0b387f9ec7482359559e4101f37d37065c20f21df811f2f760620ccf0c931f1d`；build-d receipt SHA`b6c1f4d8c25427ba4a5529ee4c8028203bd84e166a63f588f503752818619bf0`。根独立读回后授权long-c真实1800s；该条记录启动状态，已结束的结果见下条。
- `scene/long-c/browser-result.json`已完成1800.000589s、360样本和14项检查，C03/C04/图形/功能/清理/来源全部通过。首段pointer P95=14.9ms/key=10.1ms；最终37/35样本分别14.7/10.9ms。源/接收约19.913Hz、实际draw19.502Hz，peak worker1/72点、队列覆盖0；post-GC增长1,123,820字节、斜率0.028290MiB/min、listener_delta22。隐藏canvas/worker0且保留唯一遥测；browser退出、源client1建1关。result SHA`0883121e1389555b06c7733c456d15bc14cc9d65551965a917508f0c990e1054`。根独立读回原结果并重哈希195项，无差异。只证明该NVIDIA/生产构建/固定输入面板，不代替ROS消费或无泄漏证明。

### P5 后端整合与两轮运输

- 复用Vite同源代理与服务器profile，不新增网关；浏览器不能选择代理目的地。mission/cooperation固定同UID/domain flock，仅约束参与新合同的进程，不能证明旧外部动作已结束。
- Java五个旧写入口默认409，读/SSE保留；显式legacy仅恢复原topic发布能力。Java45项与实际8087五拒绝/只读runtime通过，见`java-p5-readonly.json`。
- SO101保留原IK/RRT、速度、逐段0.015rad采样、1mm碰撞余量及360s总限。每次approach使用一个有界纯查询子进程，seed0是该进程首次查询；父持唯一owner/hold并每20ms检查取消，30s查询限及原ID/5段/1MiB结果校验，回收仅自己的子进程。5项生命周期及73原流程/37工作流检查通过。
- `approach-query-a`两次真实查询路径摘要相同`da5b0877485bd4cc8e8ba2f0c7a22b324154270d7b39fdb301674caaaa2ada7e`、接近时长23.1662196s；41源/输入一致。只证明离线查询，不替代运输。
- 静态scene身份固定到启动manifest的world XML SHA；缺fresh反馈仍physics=null/ready=false，不伪造reset ACK/新episode。修复F的source暂缺身份问题，原F unknown不改判。
- `coop128-g/result.json`整组通过，442.128s≤1100s。移动Dock取消`0ed37f43-99a9-4dc4-ba1c-028642a1f6f7`按原oracle safe_cancel；完整运输`1927b50e-170c-4580-9073-82221ebc4aa7`与`0740edf4-af0c-425d-8808-8023f978cb2e`通过原K评分。7328/7457独立物理帧，同一货物位移1.79409173/1.79224002m，真实双指抓取、抬升、释放、托盘落稳、完整足迹、先回臂、运输/最终停车均通过，禁碰/交接违规/crosscheck缺失0；每轮3原生UUID均4。
- G另含丢POST回执unknown/no-resend、原编号新CLI恢复、两次显式reset与旧版本拒绝，3start/1cancel/2reset。49源/输入起止及根当前重哈希一致；owned全部退出、9098关，Java/Vite身份保持。result SHA`ae96c98cada573703e595e9ad42719e5470777eeb3e53873c17116ae94cd68c4`，三评分SHA分别`5fae8b07376172a2244523637dab008a0b77325e39e26167d7f3a921097b5ad2`/`bc5c92692a3c1b880162372336eb52eed11498e2cfc7f4671c7166b1ce33976c`/`e22db78910c2cbf1ff2c9711c42cd5e7e438334976f35e67a11042c291ef42da`。
- `coop-view-a/result.json`四项实际只读浏览器通过：同episode相机、HTTP失败及恢复、切页保留原任务；零POST，不干扰运输。

### 人工控制：候选、保留失败与最终八项通过

- 单一应用owner、租约/原时间/序号、显式STOP/原ID查询已接入。`passage_manual`复用官方twist_mux4.5.0→平滑→Collision Monitor→原strict守卫→底盘；前进0.08/后退0.03m/s、转向0.25rad/s，TTL250ms/心跳140ms不变。普通tick只发零，不刷新旧非零命令。
- 初期修复空map_id规范化、保留Nav2备用robot_radius但仍用完整polygon。idle-only时序恢复只允许原有bounded ring中明确六维零、fresh quiet、无运动/unknown/显式STOP，并需真实reset ACK。D曾实际触发一次恢复，不能外推普遍成功。
- 前端按发送起点计算140ms间隔，串行等ACK，无catch-up。修复reset→STOP竞态：新STOP用新UUID，晚到reset不可覆盖；新STOP明确拒绝才恢复旧reset编号只读查询，缓存仅有界一代，不入API、不回放。
- 原FIFO32/每drain最多4，加原生GuardCondition即时唤醒及100ms fallback；仅manual配置给stock TimeSource独立回调组/2线程，其余业务保留唯一锁/owner。零动作机制探针等待0.000872s、180ms业务阻塞时clock推进0.164854s，只是机制证据。EventsExecutor因不支持当前GuardCondition未采用。
- 已移除控制锁内同步诊断logger/file I/O，慢事件仅当前租约内存32条/8KiB，原status GET读回。晚事件按session/sequence/issued关联，当前scope不冒充来源。后补同线程CPU/native tid和GC固定tuple/各代计数，只有GC2记录时长，覆盖/拒绝显式。hook不取owner锁、不做JSON/ROS/I/O；仅manual配置注册，正常/构造失败/节点销毁均幂等卸载自身hook。141项定向与独立审查通过；仪表不是控制故障修复。当前mission SHA`f8213b90f10b0dbc33ef120de1b2375638771808baf81da2f1734287ddf01c4f`。
- `manual-ui-b/browser-result.json`11项mock浏览器合同通过：按住/松手/失焦/切页、键盘与输入框保护、unknown不重发、STOP/reset不自动运动；不等于真实B07。

- 已核本机rclpy7.1.12缺官方Jazzy PR1726/rolling1547的GIL yield。当前只在manual配置使用薄ManualExecutor，调用原父调度方法返回后执行官方sched_yield/fallback sleep0；父spin/shutdown/单spin保护、2worker及原FIFO/TTL/140ms不变，不改系统安装或OS策略。146项定向干净通过；最早测试fixture缺destructor sentinel的unraisable警告已修后重跑，首轮不算完整通过。mission SHA`559e951b15cd2e470d22ffaf29ddc8ab49591712a9ffe26568c636783d73a436`。J首项通过而整组失败，不能证明该候选带来统计改善或把旧I追认唯一根因。
- 根审查了J之后的工具修复：在生成新lease与时间戳前，最多15s只读等待后端准入，且不超过原active440s期限；仅明确的quiet/cleanup等待状态可继续。身份、原生UUID、其他租约、STOP或unknown恢复异常立即失败。新增延迟准入/总限/12种致命变化回归，共26项通过；工具SHA`eb9a38d5d936f6f91470c2ac0cea96f1ac611542c9e7d2fd86d50b02a898cf14`。八例/480s/250ms TTL/140ms心跳不变，尚未新跑。
- K没有收到独立guard诊断，而非测得旧诊断。首次15s就绪等待已同时要求至少20真值帧与一份实际fresh guard证据；只等明确的缺失/陈旧，错误profile/execute或其它异常立即失败。后续quiet边界及动作/cleanup逻辑保持。manual29+voice12共41项通过、pycompile/diff通过；工具最终SHA`4d02af2d638b8861a1f3e0e54f2f4d6407a47b0ab8e0a2c9a9166efa9058132e`。后端仍`559e951b…`，待新O/B07l实测。

- 根复核并修复键盘焦点：checkbox可直接W/方向；Space保原生切换，不误触STOP；Ctrl/Meta/Alt不启运动；持按时Tab/ShiftTab移出面板释放原lease，面板内焦点不误释放。沿用原owner/代次，未增执行路径。`manual-keyboard-fix-a/browser-b`19项真实fixture浏览器通过、14.116s、8源起止一致、无真实ROS/其它POST；原a的15项通过与源码副本保留。最终panel SHA`b181d1eea02c18201fccef63dcdb696345d579f3763232276e2bded38aac8a88`，合同SHA`097ce2638608f1d6de6cd345380d155dc9c74688ae3fda470d05180f9b59edb1`，result SHA`67e96c45a51728b879eb615a87be3860b2602b555e2ca2ffeddc98e02467ea84`。33项controller、type/lint/nodecheck通过；这些不代替B07真实动作。
- 语音准入工具已离线修复，19项通过（原12＋7）；Python首次、JS首次/确认点击前只读等待明确quiet/cleanup，原120s内每段≤15s。route已有body时立即严格检查、不等待/改时间/重发，原status与HTTP异常留存。Python SHA`c522ca38116f2e0689a0e4fe04d6b4fe6822e91cdd0e3fb7ed402c901ca61bbd`、JS SHA`4d085af246eb30c0b1fa43332479f38e20277bf2c46c9fecab6b7a7750274bc4`；manual工具4d02与backend559e均未改。未新跑E。

- 键盘补丁后的build-e采用相同profile/Node/lock，165源起止一致，29产物与封存receipt完整验证。与build-d实际字节13/29同；归一化已知文件名哈希引用后只有包含未挂载键盘handler的主chunk存在代码差异，其它28逻辑产物同。该比较不冒充字节一致，初版方法缺basename引用的报告也保留。原C04全程/radar↔/results，dashboard键盘组件未挂载；owner、renderer、worker、输入和门槛源码未改，旧long-c不换成新195源通过。
- `scene/preflight-n`绑定build-e，13项生产硬件短测通过：pointer P95=57.4ms/key=40.5ms、queue1.9ms；实际RTX3050/Vulkan、offer/receive19.8666Hz。22资产/195闭包起止及根重新散列一致、零POST/error、隐藏canvas/worker0、SSE1建1关；result SHA`3d0cae0b9412f34b4641883cb24c5e18f68238f52d0ba729cb4da2763e606e3d`。短测包含切页/故障重建，draw3.2712Hz不解释为稳态或新C04；新长测not_requested。E预览已仅一次SIGTERM回收，5187关、8087/5182身份不变、5186未动；首审计误把进程state作identity，原失败留存，后续只读核验SHA`71ac758e5c348dfb600ebfe3023a115435fe7f96d3805c707c3157a25ca8051e`。

- 语音验收工具补齐原STOP响应status/headers/rawJSON及异常，使用原120s总限与STOP起固定15s；只在原STOP明确unknown时允许原ID GET超时恢复。Python尾部不足固定GET2s时保守失败，不重建窗口；JS转发前再次校验原deadline。失败前未发送STOP且原任务身份/原生UUID一致时，最多一次原cancel替代第四POST；已尝试STOP后只读。新增准确的前端unknownSTOP→同ID取消5组合，原accepted=null/receipt_status不改写。Python29/29与voice前端29/29、语法/diff通过；PY SHA`619e8ebbc63793f233fe0e879df1de8c7dabd2d6525dd02e76142b6c127540ed`、JS SHA`03a0d85499636d2453285370b1970dde9a25239e3efd7afbeb9e4b8a3621224a`。未改生产App/bridge/manual源；E失败不追认，待新F。

- F唯一启动在原45s门禁失败，原wait_ready报告AMCL生命周期未fresh ACTIVE；之后planner/context错误发生在自动shutdown，不当作最初原因。9099未启动、0POST、voice-real-f未运行。29源/6输入/115前端起止一致、原进程全部退出/9097和9099关/129空，cleanup SHA`da9066e5a2756bfbfc5c55189cdf1b6ee0eaa12bfc900215a503b6d6ba0c1247`。
- N后独立源码审查未发现必须使用双worker的正确性依赖。仅撤下ManualExecutor兼容层与多线程import，两个profile复用原标准SingleThreadedExecutor；默认业务互斥组/RLock、TimeSource组、FIFO32/drain4/GuardCondition、速度/140ms/250ms及物理评分保持。候选SHA`806ec48d15874aeefb75834c89939745cfd738cb6b6e5e60bb17b03b097fdea7`。21dispatch＋8HTTP＋113mission共142项通过；首次编辑脚本未更新测试import的失败保留，修正后重跑21干净。旧4项shim实现测试随类删除；本轮检查不证明物理通过，待新R/B07o。

- `manual-real-o`原B07八项全部通过，35.8308s/69POST/约2.03MB证据；result SHA`45d343302c9617ea55178dce3bf18329b2fdda0f49d718fff0fe9b738e56cde2`。前进0.101951m/后退0.042390m、左转+0.260781rad/右转-0.254384rad、真实网页前进0.044054m，释放及双时钟quiet均通过。两项断流/重复与过期拒绝保持原TTL且无补发；同task`d33ab059-3100-493d-a59e-0559735737b9`/native`a155a60e29d34b1c9a57a7a5c924d9c4`的运动取消、互斥拒绝与显式reset通过。21执行源/6输入/164前端源起止及根当前重哈希同；独立最大接收间隔约50ms、源间隔46ms。最终guard healthy、canAcquire=true、无活动租约/停车锁；cleanup无额外STOP，独立quiet0.72源/0.719墙。初始空闲零速恢复1次单列，不能称零保护介入。只证明本面板，不把A–N改判或称唯一GIL根因/统计提升；R由owner另行清理。
- 修复车臂页属性分组错误：car朝向/线速不再被嵌套的arm/cargo隐藏条件遮挡，真正的arm/cargo容器按选中对象显示。相关29项与type/lint通过；`coop-properties-fix-d`桌面/390px触屏四对象9项通过，实际样本数值/9源起止及根重哈希同，18API读均fixture履行、零POST/真实API/外域/pageerror。result SHA`e4572da2577e1858c465458b373a49e4d37cac679e7f5d1e1d358103148cfea9`。旧a只证标签、b域不符被拒、c期望单位错误均保留，不用它们代替d。

- R已按原owner收束，21源/6输入同、全21退出/9097与9099关/129空，cleanup SHA`24bb263e7ee68763231bab2d9d19d01dd5aa2e29af94518fde5a3970a42ea627`。G在原45s startup门禁失败；响应发现匹配问题阻止controller ACTIVE，0POST/未启动9099/未运行voice-real-g。29源/6输入/115前端同且全清，cleanup SHA`11b326b8db706fe548745fb3f1875368229813a519ed74ef35e32fec30952ca5`。H仅授权私有官方Cyclone DDS前缀对照，未改系统或扩大发现范围。
- 替代人工控制通过后，已退休旧motion-control-panel/use-teleop-control及其4项旧测试。新F/G生产构建165→162源，29产物路径/大小/SHA全部逐字节相同，共2,166,456bytes。比较仅证明F/G死代码删除等价，不把旧build-e或long-c换源。G receipt SHA`819386df509fda87bd165a9159c00b6d066e9ed56e4bf63e7afd1d2a51ccd4cc`，F receipt SHA`9730054c1b67e9e68670659ac3c83fb4c8e20c32b85bef6abbcc79e745cf2cff`；旧源副本与全部产物留私有缓存。
- `final-checks-d`最终受影响回归1544项通过：control820/mission204/autonomy61/frontend459；零skip/missing/importfail。全前端641/641、typecheck/lint通过，403相关源起止同。feedback SHA`f4f7172515d9c7784e46789649322b8f0e29b68fad7a4f72030f76a5a7f3150d`，frontend SHA`b25d346cc9d161e2b4bec57305c3c2533dc232c6476930b3df39d2f6efb6fb5f`。首次提前读取未写完feedback的JSON错误保留，进程完成后实际回读与重新封end，未重跑或改分。
- 知识仍为updated：原页第20节“控制排程：先核唯一业务组，再选执行器”补充同组worker不等于业务并行、标准执行器与时钟隔离的适用范围、墙钟/CPU差的归因边界；开发入口同步精确触发词。两页已读回，最新SHA分别`131c5fd8995eec719a4e2d455e2eee9a6245b712254c531534b85cec9444ef2c`、`aa8594ec14de3f6f9d43cc0288e97d57350a3b3c27a0474940dbd1e4de5d0ca8`；保留其它dirty，不提交知识库。

- Cyclone官方七包私有前缀验证通过：固定版本/apt SHA、750文件与14符号链接、许可证来源完整。H/I启动各13.861s/13.805s，配置lo/domain129/禁用multicast和SHM，无全局包或网络更改。仅两次观察，不称统计可靠性或SHM唯一根因。
- H实际移动并取消同UUID，原STOP HTTP200/accepted=true/canceled，但工具在异步提交完成前复制stop编号为undefined，6.283s/4POST原失败保留，SHA`59ec4e1f4083b2a5e8f97c23d1933b2d33b5abe91f3ca6fa089dbdc634ea3b84`；同原生5/quiet0.72源/0.71995墙另列。29源/6输入/前缀/config同且全清，cleanup SHA`18551e281da3e30db2f3266ea83d973d7ff51bd13513162ed8b842f587e5fdbc`。根仅修工具等待顺序并增加异步/超时不取编号回归，30/30通过；首个新fixture缺fixture回显的测试错误修正后保留原失败。最终JS SHA`49750fb08a77ea85765150d7af43572559665958aebcccfed99421289280e742`。
- `voice-real-i`原四项全部通过，5.5947s/四POST，原生`5105967d90024112822a4fdf2f77b556`、task`dfc12250-3948-43de-b85c-202c8abd83be`终态canceled5/cleanup=null，DDS同UUID5。独立移动0.05927m后STOP，quiet0.72源/0.71941墙、最大gap45.775ms/源42ms。STOP`26fe76b4-2d47-4f45-9e29-1de207a4029f`原HTTP200/accepted=true；显式UI刷新恢复原编号，无重发，不计ASR/未知回执实测概率。result SHA`cd85499c14460445bbb9a684d22a6827862e05586b8dbaad080822f93ec53539`；29源/6输入/162生产源/113运行前端/750前缀及14符号链接起止同，两个owner/9099与21ROS全退出、9097/9099关、129空，无额外STOP/reset。cleanup SHA`a4fe08cc62eab6a143f258b1e19ccb30e73a1e39b3dbc6f9fbec916b8477b6e6`。H原失败不改判。
- 配置已落到项目：原bootstrap可选packages-file/no-link，自定义七包全部核哈希/身份后才解包，默认路径不变。7项单元通过；实际CLI重建750字节相同的文件、原.runtime链接及原私有前缀保持，无ROS init或系统安装。公网包清单与loopback XML均已入源码，XML与H/I输入字节同；实际复现入口见WORKBENCH。

### 当前自动检查与知识

- `scene/preflight-o/browser-result.json`绑定当前build-G，13/13通过。实际RTX3050/Vulkan，pointer P95=14.7ms/key=14.1ms/queue=0.9ms；20Hz输入offer/receive19.8386Hz。22实际资产和192项源码/产物闭包起止及根当前重哈希一致，零POST/页面错。result SHA`edf863b233b685fc3a13b2b4ef303c5d1bc8909369b5f824c4b6a868d1211173`。浏览器/profile退出、SSE1建1关/active0，原owner一次SIGTERM回收5187；8087/5182稳定身份保持、5186未操作。cleanup SHA`c81965e8bd67985d6240271061c6e1d095e9bc9cd15e283b20b83a8fc637108a`。O没有新1800s，C04=not_requested；原long-c保留自身源边界。
- `final-checks-e/feedback.json`最终1552项通过：control828/mission204/autonomy61/frontend459，零跳过/缺依赖/导入错误，406项源码起止及当前重哈希一致。SHA`8bab1af42194ae9d7b001dc45ada8a9e29d56927b8fde2aad6a1c2ca431e4a75`。E完成后的汇总脚本误按Python组读取前端的skipped字段而报KeyError；原测试exit0和JSON保留，改用实际字段只读汇总，没有重跑或改分。完整前端641/641、typecheck/lint结果沿用D；其前端源码之后未改。
- `final-checks-c/feedback.json`当时1533项通过：control810/mission208/autonomy61/frontend454，零跳过/缺依赖/导入错误；全前端640/640，零pending/todo/failed。406项相关代码与测试源起止一致。feedback SHA`e16718dea3c53500f104ea4f8217fd7f3370208e7a0337ab538f2f57f6611fab`，frontend SHA`a390688a0ac3c3d302cfd4020d950ec41fbb3b75a5adc9b9de97302e6fdb32a9`；历史B/C/D轮不替代当前E。
- `final-checks-b/feedback.json`1502项通过：control793、mission194、autonomy61、frontend454，零跳过/缺依赖/导入错误。全前端640/640、typecheck/lint通过；165前端/验收源起止一致。最终harness变更另有22项Node检查。
- Java45项/11 suites零失败/跳过，bootJar通过；Gradle采用已验证缓存。离线布局12入口有效。按需3D chunk约748kB仍有500kB警告，没有提高阈值。
- 依赖审计`npm-audit-retry.json`22项：2critical/14high/4moderate/2low；新三库未在该报告中不等于无漏洞。兼容dry-run45s未完成，未force升级或改锁。依赖安全未收束。
- 既有知识采用为`already_covered`：FishBot第17–20节及CapMesh复用/平行重写经验已采用并读回。第19节明确区分当时参考、实际关节与abort后冻结参考；E订正是再次应用。未证明的控制调度/GC解释不新增通用结论。
- 本轮新增知识回写为`updated`：主知识库`Wiki/ROS2 与 FishBot.md`第20节的“浏览器实时流：先核传输，再看画面”，记录原生/合成主文档对照、SSE四段取证和原响应生命周期；同步`Wiki/开发知识入口.md`的新触发词与锚点。已实际读回两页、检查锚点与diff；原页SHA`7df107ec0ae0d33860c1745a55431c2a827bde1f5ec53f392f7d783296411dd7`，入口SHA`b6e3a3a7f3def7653114be5719a340827ba16ead16c1d509bda63cb6c58e28a1`。保留知识库已有dirty内容，未发布或提交其它知识库变动；原始资料仍在私有缓存。
- 知识回写补充仍为`updated`：同页第20节新增“按住控制：把焦点与原生控件纳入验收”，入口同步checkbox/Tab/Space/修饰键触发词；实际读回段落与锚点、两文件diff检查通过。最新原页SHA`d789a0d0aa6f62d258f98c6d5fc06d7407577c76872e7f4d857107b2f0623ef9`，入口SHA`44a80c50dcc8dcc4ca0bae14467a076749c3fc5eaa2853005e1fd46d98fefeb2`。浏览器fixture不代替ROS评分；知识库其它dirty内容未提交。
- 最终知识状态为`updated`：第20节新增“ROS服务超时：先定位所用RMW的报错分支”，保留前述三个经验段和适用边界；开发入口同步四条触发词与原锚点。根实际读回两页，最终SHA分别`04c8cd75bbb2b216b68341dc1e7e448b1af4955843353fd4ce254c121258b1fc`、`f54597e41aa2f3a46c7b1d97db7970e95e8b5410cd97459646f754fd0290f330`。知识库原有dirty内容保持，未并入FishBot提交。

## Remaining

1. 根完成明确文件审查、核账号/目标、提交推送并读回。源码验收已完成，不再自动派发动作。
2. 后续独立范围：22项依赖安全告警尚未收束，Lichtblick实时控制/CY切换由独立工作树持有；本轮不把它们写成通过。

## Issues

### 已保留的车臂失败

| 面板 | 原结果与具体边界 |
|---|---|
| coop128-a | Dock取消通过；第一运输360s未完成，货物仍夹持。混合事件20000上限曾挤出原生终态，后补采quiet/hold/guard后根清理；原失败不改判。已补按UUID有界终态索引。 |
| coop128-b | 取消/重置后source变化，idle收束；source_unchanged=false，不继续采运输。 |
| coop128-c | 第一运输通过；第二抓放/携货各项通过但最终Nav2在360s被取消，整组失败。48源一致/清理。 |
| coop128-d | 父命令缺用户bus环境预检失败，2.687s零launch/POST；未改全局环境。 |
| coop128-e | PathSimplifier静态复验有效，动态实际余量0.873314mm<1mm，失败285.792s。失败前参考1.106068mm；abort后参考冻结到实际，不能倒推原路径违规。候选已撤回，原接触0仍按失败。 |
| coop128-f | 移动取消通过，原reset ac5893f4-983c-45bf-bf07-0e4eb2b432c5 pending/source缺失后unknown，0运输；当时cleanup未确认，后来主机中断进程消失不追认当时清理成功。 |

### 已保留的人工控制失败

每轮证据位于同名`manual-real-*/result.json`及`read-only-timing-detail.json`（后者存在时）。A/B八例均未运行；后续整组也未通过，不把初始ready、单次forward或STOP清理计为全通过。

| 面板 | 原结果与具体边界 |
|---|---|
| A/B | 26.375/26.509s初始guard时序故障，零POST/lease/native；分别odom间隔0.273507/0.288538s越原0.25s。候选/desired ring显式零已用于后续恢复修复，原失败保留。 |
| C | 实际移动0.002899m；旧发送器ACK后再等140ms，第三命令过期。已修发送起点周期，STOP/quiet通过不改判。 |
| D | 新周期正常但原guard报旧source，10.602s/0.001625m；原STOP/quiet通过。启动实际idle恢复一次单列。 |
| E | 前5命令3–8ms，第6 intent→receipt269.814ms；无真实urlopen/server边界，不能确定阻塞段。移动0.04480365m，原STOP/quiet及129-g全21清理。 |
| F | urlopen→server5.339ms，enqueue入口→drain263.626ms，处理0.406ms；入口标记早于put/trigger，不能全称回调组等待。移动0.01239408m；原STOP03b8483e-1468-4877-9bbb-4812f5ec42f8/ACK/quiet约0.720s，21源/6输入一致并清理。 |
| G | 1/8完成，forward_release独立位移0.10157664m；第二租约seq5过期，put0.017/trigger0.006ms，trigger后→drain599.986ms、处理0.346ms，tick782ms。同步诊断与排程需区分，不认定唯一logger根因。STOP0ce0bc11-cf1e-4ab1-ac87-4942266dd9c0/quiet通过，i全清理。 |
| H | 6.759s/0完成；seq8自身TTL通过，但上一seq7续租已到期。发出时余109ms，HTTP回执151ms；规则同步墙钟215.911ms覆盖旧expiry。revision0/空zones/目录为空，只走缺文件stat快路，不读JSON/文件锁/几何。移动0.068367m；原lease32c1976d-ecd7-47d0-8e01-a50f7f114e3a确认expired/ACK。随后STOPb28e87bc-4416-4d40-b672-91f980ecc604针对idle/target=null，不称leaseSTOP。quiet源0.720/墙0.719s，j全21清理/129空/9097关/21源6输入一致。 |

| I | 仅加CPU/GC仪表的复现仍失败，7.098s/0完成。seq7入站age57ms，put9.427µs/trigger4.859µs，trigger→drain230.544ms、处理0.299ms，出队龄估288.519ms而408；独立位移0.056698m。三段rules墙钟74.010/229.394/128.458ms，线程CPU2.478/7.275/3.185ms，各段GC starts/stops均不增、pending空、最近GC2无重叠，故本段不支持CPU密集或已观测GC解释，I/O/GIL/OS仍未分清。原lease9a2fd42f-1404-4eac-bc1f-9866fcd091e3确认expired/ACK；另行idle STOPe3ebd62e-0c3a-468c-a56c-63e5c7871f65与quiet源0.720s/墙0.720495s通过，不冒充leaseSTOP。k全21清理、129空、9097关、21源6输入同。 |
| J | 9.514s、1/8完成。forward_release独立位移0.104775m，13个首租约请求最大回执7.633ms，均明确接纳。第二项前独立真值连续quiet，但后端仅确认0.070115s，工具即时准入检查退出，未发第二个acquire。后端quiet重启原因未定；后续300.080ms慢事件晚于拒绝，不能倒作直接原因。原lease857e64fc-eec8-45da-926a-0e31d7a26c16为released/guard ACK，无额外STOP/reset，最终can_acquire=true。m全21退出、129空、9097关、21源6输入同；cleanup SHA320c31b6fbbb5fdfd2811805b140eb686a39a1d905c588eb5848e3db2135946f。 |
| K | 新N初始ready/quiet后，独立观察器在初始quiet末报告guard diagnostics stale，4.596s/0POST/0lease/native/UI，八例均未运行。原cleanup=false（守卫新鲜性缺失）保留；API owner空闲/无STOP不替代独立守卫证据。后续owner已全部清理21进程、9097关/129空、21源6输入同，cleanup SHA`b8d5be09d5430d2f10605cdc5e637332318174b1b64ea73a6ce70aa73e837259`；不把后续进程清理转记为原业务验收通过。 |

| L | 8.336s、0项计分通过。首租约`119cab3e-1934-4be5-9a46-ddf9c6970517`的11条命令及释放均明确接纳，最大命令HTTP回执8.041ms，实际位移0.103375788m。独立truth第73帧接收间隔347.319284ms越原300ms；源间隔40ms、源龄12ms，单调性合格。未裁帧、重写时钟或改判；原始帧审计SHA`7fbe1eacb12762c80e4d5e812e1468a66f68cf9a847b0fb529e35f7251156f3d`。原lease released/guard ACK；另行idle STOP`d88c8bd7-37c2-417a-b005-5fa9ee3e22a3`及quiet源0.720s/墙0.720914s通过。O全21进程退出、9097关/129空、21源6输入一致，cleanup SHA`c386dd6cb9a77bfa697d062b9b9756bb05a91b060fb62f8736b56b1c3023ff14`。未运行第二租约/native/UI/voice。 |
| M | 前置只读检查已ConnectionRefused，根仍错误地启动验收CLI，已纠正后续依赖执行门槛。原工具0.754s失败、零POST/零案例/source21与input6起止一致，cleanup=false保持。result SHA`4a4d9f0481439496236b12acb022c9029f207efbc6def8bc7cf63eb227de4a5f`。随后核实主机重启：boot`fd86a293-3934-4302-a363-6015966786ea`、原PID331455及产品进程均不存在；这只证明当前状态，不证明P当时有效清理或具体重启原因。 |
| N | Q新实例，11.6865s/1项通过：forward独立位移0.102276m、原lease释放/守卫ACK/双时钟quiet通过。第二lease`bafa4af6-e08a-4fc8-acf5-74d72c64176c`seq3在131ms HTTP后明确409到期；同期rules同步墙213.496ms、线程CPU5.742ms、GC计数不变。文件路径缺失快路，仍未区分FS/GIL/OS。原result SHA`40b7ab310ff134543cfcd835bf889f9176944a4cbb5933efbe8bbd44336ca5d2`，只读审计SHA`bf18b6c804cad53754109da0bc44218521ff54db339087708f4d42946956f21d`。另行idleSTOP`0fd67b8d-7844-41f0-ad67-aab295ea312b`、ACK/原生idleterminal/quiet0.76源/0.7599墙通过，不冒充leaseSTOP或整组通过。21执行源/6输入/164前端源起止同；Q全21退出、9097/9099关、129空，cleanup SHA`66e6fd99517d74c014578efc0dc2a5947f8737d903f39dc407b3cc3502406522`。

- `manual-diagnose-a`20个未知kind均原404、零动作；未复现>250ms，最大182.35ms。trace offered29100/容量20000丢9100，且并行前端修复导致21源整闭包不一致。原result仅代表404流程，独立audit overall=false，SHA`022bf560a32befc293af0e83258de4b4feea814fa7629fdec4d888f0961e20f9`；缺失112ms不得解释为锁内计算。
- `manual-stat-diagnose-b`未在24s内ready、事件0；最终清理52.09s越40s预声明，资格失败。只回收原PGID，现129空/9097关/21源6输入及私有闭包一致。不能归因stat/GIL/GC/OS，不重跑。
- `voice-real-a`在初始quiet前16.188s失败，0POST/无浏览器或原生任务、29源一致。首truth比初HTTP晚3.4485s；318静止帧离线按原评分通过。旧固定sleep(.5)可能早于DDS发现，未记录的精确旧boundary不伪造。新工具先在原120s期限内等待首个fresh真值，再固定quiet边界；11定向测试通过，未改0.7s门槛。voice-runtime-a全部21进程和voice退出，129空、9097/9099关闭。
- I分段审计SHA`210d32b3944983cd20d16736c742dbf22f273e951997a2ea7b6eaf737a635471`。末环7观察/2淘汰/5保留，但早先原status保留被淘汰两条，合并event1..7可核；不修改原环预算。
- H静态路径审计SHA`f28660a202906f4be9e5c61e9e1967fa27755c6e86ad3e19875194463da356f7`，H分段审计SHA`ad48e8dd53af0972709861f4021c8f6232993139491573220d8a6274fd583cd9`；G分段SHA`ee0467af4f1f66b8805be031040e32483497944faac08ce68266b6ae0daf5e0d`。

- `voice-real-b`首fresh等待生效，但只有单帧时直接进入原quiet scorer，2.672s内因样本不足失败；0POST/无browser/native/lease，29源同且b全清。工具现复用B07双帧门槛，边界/期限不变，真实main单帧→双帧循环回归通过；voice12+B07工具23共35通过，尚未运行C。当前voice工具SHA`e6872fcf19a2c7300d55aa0cf5ba029513067bd96bfbc3a983e547e223b3fb48`。

- `voice-real-c`初始独立quiet源0.720s/墙0.71998s及19帧通过；Node在启动浏览器前因`playwright`模块解析缺失退出，2.656s、0POST/0native/0lease，未生成browser-result。原result SHA`61b16e5e63dd25ab3857fd559725addb570f1c411085beeb7ea5055381003035`与browser.log保留，不把缺文件当ROS拒绝。29源/6输入一致；9099/observer/Node已清。根与accept分别核同用户/node v22.23.2及显式NODE_PATH能解析已安装Playwright；C原ROS实例保持fresh idle，显式授权新voice-real-d原120s/4POST，不改源码、不重启ROS、不自动重试。

- `voice-real-d`显式模块路径后进入Node预检，但`can_acquire`单次断言为false，2.674s内仍0POST/0browser/0native/0lease。Python早先为true/quiet16.78s，Node原GET完整reason未保存；随后只读见`continuous_quiet_unconfirmed`/quiet0.5968s及新鲜双龄，不能倒填原GET。独立quiet源0.720s/墙0.719737s通过不替代业务验收。原result SHA`0d9b6b60c0d1b88ae3ce11330fd3aaa4845708a1e56d943e6355b832aa4d3a75`、自有清理SHA`7352c896faae60efd1a91e45204240fe69f1626309b3538ef67f3c2edd0ebcad`；29源6输入一致。下一步离线修复Python/JS有界只读准入，保留原120s及所有身份、停稳和运动门槛，先封C end并清理后再改源码。

- `voice-real-e`实际4POST、17.551s失败，原result SHA`3a364bb95fed069e2f4caf657bbcbdca2a5baab9d02a1be24ac4c87e1570c953`/cleanup unknown保留。task`9de1571c-f3d3-4723-b932-54a50b7af7bc`、native`7e935507cf3640089b64f207140b6caf`；预览零派发、确认运动及切页原任务保留两项通过，独立x0.05436m/v0.06038m/s后发STOP`e0dfdf12-0770-40f5-901a-4e3a27c8509f`，未重发。原STOP确切HTTP状态/JSON未留，只有accepted=null断言；不能用后续state冒充原响应。原DDS在1792322534.4013693已记录同native5，原139静止尾帧源/收5.52/5.519713s、最大gap42/41.427ms。后续原task GET恢复为canceled5，不倒改E结论；按ID语音查询路径实际404，仅state支持同latest_command投影。只读审计SHA`79c5a27643268d07208c28ce258cf304c055e35fcc809b0f42e874440b51321d`。29源/6输入及额外164前端源起止一致；9099/browser/observer已清，E原21进程/PGID全退出、9097关/129实际空，cleanup SHA`06b74328548c8aae2597fd04010b083502fd834410245a2a4fe4b716eebf70a1`。

- `manual-runtime-l`采用官方yield候选的唯一launch未通过原45s启动预检：controller_server lifecycle未fresh ACTIVE，change_state回包timeout，launch自动exit1并回收。没有ready身份，B07j未创建/未运行，0POST/lease/STOP/browser。21源起止一致；6输入只取得end、缺input_start，资格缺口明确不补造。原PGID202404退出、9097关、129空；cleanup SHA`34117f40ecebc5af9479c86b7bdd9dbbdb988c00939364a01abde10920dfdb66`。不能据此判yield运动效果。

- `voice-runtime-c`完整清理：source21/voice8/input6在voice工具改源前封end并全same；原21 PID/PGID均退出，9097/9099关闭，domain129实际nodes[]，无STOP/reset。cleanup SHA`80dcbc6b42d4e0f7d4353c8206a64c72f7a7a87ebe261fe5e767b650f96706c4`。C/D原失败不改判。

### 其它保留边界

- 原56视觉38完成/7正确取消/11失败保持，UI重构不修正其评分。
- 独立Lichtblick树在`codex/workbench-code-rebuild-20261018`，基线本main的325fa26；固定v1.29.1上游导入`0eaa6d92af69da3b2827153d6e59fe9114f89557`、SO101历史回放`fb4a6622d5df024e7851a92f3351b3f223ef584b`、P1收尾文档`c62ab26d20697910deb18affa8582fbae154fe12`已在对象库读回。当前该树clean、比main多3提交，未合入。P1是历史MCAP桌面/手机回放；实时runtime/跨回合/新任务/取消查询/CY切换仍pending，独立SO101 full_cycle CLI尚缺已核HTTP生命周期合同。本轮不转记新物理通过，不改5186或CY，新runtime/control迁移仍由该树计划持有。
- 首次反馈测试误依赖已安装workspace失败，已修源码测试路径；后续1502绿灯不删除原失败。旧图形trace/软件失败、无GPU安全隔离证明及依赖22告警均保留。

## Next

根串行完成文件审查和Git交付。G图形短测、B07o/voice-I及各自清理、旧teleop退休、产物等价和最终E反馈均完成。知识已实际回写并读回；原成果快照未改。后续显式运行按WORKBENCH选择匹配profile，不自动恢复已清理实验。
