# F1 Progress

## Current
in_progress：修复后fixed direct窗口已结束且归还，未追加via/重试。身份接线实际接纳且1次start成立；A task437abb20-ffbf-4dd6-a749-71f0d1cb709a入站Nav原120墙秒超时、原UUID终态5，未Dock/抓放/载货；原score false，B未执行。报告器对合法null终点误差调用.get，导致原result未落盘/调用进程134；原run_id不可恢复，不伪造。独立cleanup/原native终态核对后仅SIGINT owned组，reconciled-cleanup确认无存活/9111关闭。已最小修复null指标并22项回归过；只读reconciled-result保留失败与缺口。最后30源秒地图跨15mm目标圈110次，cmd v=0、w交替，入站末端收敛待修；目前仅源码/证据审查，无FishBot实例，下一窗口另约。 阶段XY最小软件候选已接并局部检查通过：同RPP/检查器复制两配置，只有入站stateful=true；显式staging=True且非载货才选树，其他及旧/null字段保留默认。新prepare/多插件实际加载、原13项和完整运输pending，旧fixed输入未改，无FishBot实例。

## Done
- 已读 F0 厂区协作约定，明确两个配送工位/目的地和可选通道占用。
- 确认现有订单/目标、prepare 地图生成和原物理 oracle 可直接复用。
- prepare 的可选 --factory-config 与 workflow 场景订单薄 hook 已接入；旧 workflow 49 项回归通过，尚未计厂区实际配送成绩。
- 场景worker 10项含四个真实静态MuJoCo3.3.7构建通过（13.690s，临时目录清理、仅标准输出证据）。根公开prepare成功且manifest独立读回。
- 评测入口经独立审查修复running任务误清理及跨360秒误通过，根独立19项合同回归过（0.011s）；不修改原评分。根另重跑10项场景/四静态构建过（16.954s），证据 ~/.cache/fishbot/factory-line-delivery-20261021/factory-scene-tests-root.log。

## Remaining
原open无需重复。后续真实策略入口按task_plan接续；occupied-v2 的 B 物理未到位保留为后续策略开发失败样本，不算全场景通过。

## First entry
公开入口 tools/cooperation_factory.py 已冻结，完整命令见 docs/FACTORY_DELIVERY.md。根已生成 ~/.cache/fishbot/factory-line-delivery-20261021/open-v1/scene/scene-manifest.json，并独立dry-run确认两订单A/B、0 ROS/动作、输出未创建。实际命令：

```bash
FISHBOT_MUJOCO_DOMAIN_ID=141 XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus bash -c 'source tools/fishbot_mujoco_env.sh; exec /usr/bin/python3 -B tools/cooperation_factory.py run --manifest /home/muqiao/.cache/fishbot/factory-line-delivery-20261021/open-v1/scene/scene-manifest.json --output /home/muqiao/.cache/fishbot/factory-line-delivery-20261021/open-v1/run --candidate baseline'
```

`--order order-b --order order-a`改变订单排列；候选标签不加载代码。执行状态、原物理裁决与单单360/整轮1000预算分列。未执行和未评分均不计通过。

## Knowledge closeout
updated(local)：根已回写 Wiki/ROS2 与 FishBot.md 第19节车型/曲率/缓存/厂区配置经验，第20节同任务终态/预算/保护快照边界，并更新 Wiki/开发知识入口.md 的触发词；rg 读回已核对。知识库独立未提交，不宣称远端发布。

## 首个原生结果与独立读回
- 场景 f1-line-side-open，run 7daac585-8230-4c15-b4b3-36e8c7f4ef8e；结果 ~/.cache/fishbot/factory-line-delivery-20261021/open-v1/run/result.json，执行completed，任务裁决passed，overall=true。观测mode=ideal，车辆FishBot，planar。
- A：task f70f62ae-7cd2-4076-92f8-2d7ee949b901，221.105墙秒，交接后货物XY位移1.789756m；末误差.0323364m/.0301715rad，连续停稳2.48源秒；载货Nav eaf5473fa88b4a56bd58f50bf8908ab1，原始status2→4。
- B：task 34f7348a-ba63-4425-af3c-0a1dc51881f6，207.481墙秒，交接后货物XY位移2.473837m；末误差.0302101m/.0211736rad，连续停稳2.62源秒；载货Nav01946538961a4ae3a7e6af0b2900f6b3，原始status2→4。
- 独立worker仅读磁盘再次核原K、双指抬升/释放落稳/臂回位/同自由货物运输与交付均过；累计车臂禁碰0。原reset回执/新episode/源stamp交叉吻合，无重发。10份选定源码起止一致；不是所有二进制/子进程import的完整冻结证明。
- 保留缺口：A最大physics源间隙.260s，B.040s，记录器完整写出不等于源采样无孔洞。before六个旧systemd单位均not-found/inactive，after只有原result比较布尔而无原样快照；不能宣称旧107/114活进程持续保持运行。本轮只操作own launch，未补启旧实例。目标发送证据仍为桥冻结请求/accepted handle，独立原生status不冒充控制器消费回执。
- 订单间reset车和同一个自由cargo；不声称连续无复位排程收益、多货物并行、目的地下货或PLC签收。

## 实体占用变体
- occupied-v1 run bf05918e-14a2-4efa-bc1a-2495f0f6dd1c：旧箱(-.45,-2.10,.25)、尺寸(.18,.30,.50)挡住声明的直线入站扫掠，margin=-.163494m；0 start/reset/cancel，未启动世界。仅说明这条入站证书失败，不说明全局不可达。
- v2 将箱声明改为中心(.35,-2.10,.25)、完整尺寸(.12,.30,.50)，open/occupied 配置使用同一几何，仅 occupied 不同。四个 FishBot/J100×open/occupied 静态编译、原入站扫掠通过（19.84mm 总余量）；不算四组合运动验收。worker 11 项通过。
- occupied-v2 run 630e7143-a33b-4b71-a357-d3c7102d7404，454.848墙秒；task状态两单succeeded，原物理 task_verdict failed、overall false。A task4c74591b-a9ff-40f1-8fff-25438ce8ca5b，189.607墙秒，末 .0319643m/.0232663rad、停稳2.48源秒，物理passed；B task0e7feb87-016a-4522-99a6-8f32a164e86d，216.670墙秒，末 .0434781m/.0289143rad、不满足4cm内连续停稳，物理failed。
- 同一桥2start/1reset、原生载货Nav分别ed93dc3ae0a5479f8010e104d25183fd和d12ad4d4975d4c3a9cd7591cfb0c0994，均原UUID status4。原K均通过；原整体评分仍拒绝B，未放宽任何物理门槛。
- 选定源码起止一致，任务/总预算均内，owned launch/observer/端口均关闭；保护before/after原样快照齐全且六个配置单位均not-found，historical_instances_were_running=false。这不是旧实例运行证明。独立原始来源：~/.cache/fishbot/factory-line-delivery-20261021/occupied-v2/run/。
- open-v1到occupied-v2间仅补teardown诊断及保护快照元数据，不宣称严格同源码性能A/B。原失败不覆盖，未自动重发。

## 最近回归与后续候选
根完整反馈1621项及133项P8/F1相关原生离线检查通过，零skip。goal持续XY检查和雷达自定义配置接线随后6项局部检查通过。B失败只读取证：载货轨迹实际从箱下侧绕过，车/臂禁碰0；早期XY进入容差时朝向未达标，Nav4时真值43.447mm，hold后仅移动31.9µm。候选持续检查XY以免转向漂移后继续算到达，控制器内部锁定仍需核实，尚未记新原生通过。

下一真实策略入口已在task_plan指定，状态pending、owner=FishBot root。--candidate仍只作标签；不把源码观察当加载证明。优先路线/中转选择的同场景独立比较，订单全reset边界保持，不宣称连续排序收益。F0根已独立读回open两份原score；不重复open运行。

F1实现与已完成结果作为bb9141e交付到既有origin/main并读回；82902c5补车型执行器候选及后续策略边界，未宣称占用变体或P8全通过。P8 L首行保持失败，在途运动实例已清理，源码由FishBot root统筹。

## 路线策略加载软件交付
新增cooperation_factory_policy.py及--policy-config，实际加载内置/本地函数并调用一次，返回None或map{x,y,yaw}；原SceneGeometry点检、原native carrying Nav2与oracle继续执行。保存真实模块/__file__/函数/输入/返回/异常回执与私有派生manifest，原prepared不改，label仍不加载代码。只支持FishBot factory/no body egress_motion；J100在import前明确不支持，dry-run/report不执行目标函数。

worker31项0.149s过；根独立31项0.164s过，含真实纯软件子进程导入并调用自定义函数，非空点→派生manifest→geometry/launch参数消费为mock合同而非物理成绩。root已审context深拷贝、原目标保留、异常不回退、复用既有owned进程回收。原生occupied direct/via对照pending，由root在P8 M清理后执行；不重复已通过open、不把策略调用当改善证明。例配置与使用见docs/FACTORY_DELIVERY.md。


## 同一新prepare的direct/via窗口
O已清理且当前无FishBot物理进程。研究根与无人机已确认串行交接：无人机原生ground/箱顶取消在先，明确terminal交回后先direct，完成/清理即归还，via另约窗口。一次run两订单沿用总1000墙秒/每单360墙秒，不要求不可分割长窗口；预估450–650墙秒仅计划值。root不停止他人渲染或修改全局算力。

已从同一line-side-occupied配置新prepare到~/.cache/fishbot/factory-line-delivery-20261021/occupied-policy-20261021/scene/scene-manifest.json。只读核对FishBot/planar/transport、实体占用=true、A=(0,-2,0)/B=(.7,-2,0)，新YAML双stateful=false、原native .015m/.035rad不变。旧occupied-v2 prepared仍checker stateful=true、RPP未显式false，不能混用旧运行配置检验新候选。两次策略只改可选中转，复用这一份新prepared以及同一源码/固定订单/原裁判，分离输出和新UUID。

```bash
# 先等明确窗口；在FishBot根执行。两条分别占用一个窗口。
FISHBOT_MUJOCO_DOMAIN_ID=141 XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus bash -c 'source tools/fishbot_mujoco_env.sh; exec /usr/bin/python3 -B tools/cooperation_factory.py run --manifest "$HOME/.cache/fishbot/factory-line-delivery-20261021/occupied-policy-20261021/scene/scene-manifest.json" --output "$HOME/.cache/fishbot/factory-line-delivery-20261021/occupied-policy-20261021/direct/run" --candidate direct-current --policy-config tools/config/factory_policies/line-side-direct.json --order order-a --order order-b'
FISHBOT_MUJOCO_DOMAIN_ID=141 XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus bash -c 'source tools/fishbot_mujoco_env.sh; exec /usr/bin/python3 -B tools/cooperation_factory.py run --manifest "$HOME/.cache/fishbot/factory-line-delivery-20261021/occupied-policy-20261021/scene/scene-manifest.json" --output "$HOME/.cache/fishbot/factory-line-delivery-20261021/occupied-policy-20261021/via/run" --candidate lower-via-current --policy-config tools/config/factory_policies/line-side-lower-via.json --order order-a --order order-b'
```

窗口等待期间只做离线回归/文档；两条尚未执行，不称已有真实路线策略对照。若其间源码变化，先记录并重新协调同源对照，保留原失败。知识updated(local)，第19节及入口已补末段速度/进度分辨率和连续样本诊断，读回成功，未发布知识仓。


统一check-feedback已纳入loaded limits和factory/policy三组55项，集成完整1678项通过（control948/mission209/autonomy61/frontend460），零skip/缺依赖。两条实际命令已通过bash -n，新prepared双stateful和原目标/容差读回有效；窗口尚未释放，未启动direct/via。


## direct窗口已启动（在途）
无人机owner明确完成ground32/48 terminal和owned清理后交回，研究根再次确认。最后147项native相关离线回归过144.492s并退出；1678反馈保持。direct首次run已启动，141/9111，checkpoint78c3db1；无重复派发，不扩via。真实policy-receipt已经记录cooperation_factory_policy.py的direct函数实际被调用、返回None、derived manifest无egress，静态geometry通过；运输结果仍在途。结束/失败与清理后向无人机及研究根回告，来源三层不混计。


## direct零订单启动失败与显式manifest修复
原run3f80df76-e520-4fd8-a65c-ad6671a0ffd5：readiness70.315墙秒超时、0订单、0start/cancel/reset，实际策略函数direct调用成功/返回None、geometry过，原result执行unknown/任务unknown。launch将私有derived-manifest交给bridge，sim.source_identity仍固定读world.xml同目录scene-manifest.json，导致生产器manifest身份与bridge不符，原日志持续拒收。不是路线失败成绩，也不是只改标签。

根先核API task idle/id=None与零mutation，复核保留launchPID2383948/PGID及derived参数，SIGINT仅owned组。18个owned身份均退出、9111关闭，另存原run/reconciled-cleanup.json，不改写原result为成功。原窗口已明确回告并归还无人机/研究根，不自行扩展via或继续重发。

最小修复：sim新增可选--manifest，Physics/source_identity接收显式路径；launch把同一路径同时传给producer与bridge。未指定时仍读scene sibling，原物理/身份/时龄/评分不变，不新增hash执行锁或绕过校验。新增实际MuJoCo构造derived身份/原prepared不变检查与原launch命令接线回归2项通过7.224s；78项相关sim/launch/factory/policy完整回归过62.003s。随后补充真实raw按派生身份接纳、按旧身份拒绝的断言，单项过5.910s。新direct/via须使用修复后同源配置与独立新输出，旧direct/run原件保留。


## 修复后窗口准备
显式manifest两端接线修复通过78项相关回归，真实raw原身份不匹配仍拒绝，默认省略参数行为由原完整sim用例保持。新共享prepare输出改为~/.cache/fishbot/factory-line-delivery-20261021/occupied-policy-fixed-20261021/scene/scene-manifest.json；两轮输出分别为direct/run、via/run。原occupied-policy-20261021/direct/run为零订单unknown历史，不覆盖。两条命令只把前节三处父目录occupied-policy-20261021改为occupied-policy-fixed-20261021，其余目标、order-a/order-b、policy-config、141/9111与1000/360预算保持。

root核实修复、读回新prepare后申请direct新窗口；明确交回前不启动。知识updated(local)：原第19节377行与开发知识入口48行已补派生配置生产器接线经验并读回，独立知识库仍未发布。P8 O仅参数应用前超时，不因本修复记导航通过。


## 可恢复交接
owner=FishBot root。最新研究根排程尚未给F1放行：SO101独立XY两短回合后，无人机还有native48正负与箱顶取消闭环；不能把SO结束当自动放行。当前没有FishBot ROS/MuJoCo/浏览器QA/测试/prepare在途，源码修复e573eb6及共享fixed输入已完成验证并保留。接续只在原对话收到明确窗口后，以本节fixed父目录、新direct/run执行一次；同次运行对账不重派。完成或失败后保留原oracle与原1000/360期限，owned清理，再同时通知研究根和无人机；via及P8另约。知识updated(local)与全部原失败状态保持。


## fixed direct真实结果：入站失败，未进入载货
任务437abb20-ffbf-4dd6-a749-71f0d1cb709a、回合4bf9999c-94da-45bd-bd48-e5ebc6597608；实际direct函数与derived身份已接纳，唯一start。入站目标(-1.1,-1.8,0)，原Nav UUID846d3462e24c477e99cd3b7a51f10072在120墙秒取消终态5、result_known=true。标记wall持续120.87754s，未触360；无Dock/抓放/运输。原score-1792574214379374646.json passed=false/原K=false，交付误差None是未到交付的合法状态，B未执行。

报告器把None当dict，order_report在正文与finally各抛AttributeError，原result及source-end快照未落盘，caller134。不能用调用退出码替代原oracle，原run_id仅曾在内存，现不可恢复。null指标两行兼容修复保留None和failed；22项factory检查过.007s。只读reconciled-result.json从原declaration/terminal/score/markers/cleanup恢复摘要，original_run_id=None、source end未观察，不冒充原runner成功完成或源码全起止一致。

原bridge cleanup verified（native_terminal/quiet/hold/guard_disabled），独立observer连续quiet1.88源秒通过。根复核task/UUID/owned命令行与PGID，SIGINT仅launch2478406组；reconciled-cleanup.json记录所有owned身份消失、9111关闭。窗口已分别明确归还无人机与研究根；无自动重试、无via、无新P8。

只读原observer入站末端：source95.38–125.38的1501个去重map姿态，goal距离5.743–23.660mm、yaw1.989–2.545rad，15mm圈跨110次。下游cmd v始终0、w-.68653至+.59992；真实车体hold=false、yawrate-.60159至+.56764，XY仅约9×7mm范围运动。符合圈内终态转向/圈外路径转向切换，非单纯转不动；没有controller内部逐分支回执，不能独占因果。证据inbound-convergence-readback.json，原source/姿态/动作门槛保持。下一修复先查阶段XY状态锁/紧目标圈的控制合同，不能把它记为路线策略差异。


独立原nav_status已核UUID846d3462e24c477e99cd3b7a51f10072：status2接收于1792574087.019367、3于1792574207.048853、5于1792574207.073928墙时。不是只采信bridge终态。knowledge_status=already_covered：Wiki/ROS2 与 FishBot第19节已记录双XY锁、关闭后位置/朝向往返及独立原ID/物理评分边界，本次追加量化证据留项目，不复制原日志；null指标修复为通用可选值处理，无新知识页。root后续先恢复入站收敛基线；保持原目标容差、物理评分、期限，不扩展本轮窗口。


## 阶段XY软件候选（禁止冒充运动通过）
按研究根授权只做软件整改：复用原Nav2 1.3.13 FollowPath.controller_id/goal_checker_id与NavigateToPose.behavior_tree，为入站复制同一RPP/目标检查器配置，仅stateful=true；原交付FollowPath/general_goal_checker false保持。两个XML共用原规划/恢复图，主树显式绑定general_goal_checker，staging树显式绑定StagingPath/staging_goal_checker，避免多checker时空ID歧义。所有原速度、容差、碰撞、进度期限和120/360保持，DockRobot/owner/原UUID/取消清理不变。无运行时参数交易或新控制器算法。

新prepare生成staging_navigation_behavior_tree；bridge仅显式staging=True的非载货入站在原NavigateToPose请求设置该路径，carrying及旧manifest默认空路径。native_actions.goal_behavior_tree单列实际请求，非控制器逐条消费ACK。官方同版源码已核对FollowPath端口与逐goal行为树装载；切换必须在前动作终态后，现owner合同保持。私人P8 runner生成输入观察纳入可选staging XML，旧证据不改写。

纯软件36项（3个阶段配置/XML、1个桥请求路由、22个factory、10个policy）检查通过，未启动ROS/编译/物理步进。原13项prepare及实际多插件生命周期尚未重跑，留下一明确窗口；现有fixed prepared尚无阶段树，不可用它验新候选。旧failed/unknown/reconciled记录与物理评分均保持，root不自动native/via。


阶段候选完整core108项纯软件回归过15.452s；补充可选staging路径为null时保持旧默认的路由断言后，3个阶段配置+1个路由复验过。分别用原FishBot/planar与J100/3D完整YAML/原BT复制到临时目录核对，两个阶段引用相同RPP类、Simple/Stopped检查器保持、.015/.035不变、ID均可解析到声明列表，未初始化ROS/步进物理/编译。该检查不是插件实际加载、prepare完整回归或运输验收。当前候选只在新prepare生效，旧fixed失败场景不修改，等明确软件/仿真窗口后生成新的共享stage场景再验收。


knowledge_status=pending（仅新阶段候选）：双RPP实例/阶段树目前仅软件配置与路由验证，未取得原生加载/完整运输证据，不向知识库写成已修复。owner=FishBot root；最短接续是下一明确窗口先做prepare/native消息与插件加载检查，再新共享场景direct原单轮，原评分/期限保持。既有双XY锁风险经验为already_covered。


为避免未来普通非载货导航误选入站树，bridge另用显式staging=True角色；只在既有vision/ideal两个入站调用处设置，载货优先保持默认。非staging的普通导航、旧/null manifest均默认树，不扩大作用域；该收紧仍纯软件，目标与原owner/期限保持。下一共享目录预定occupied-policy-staged-20261021/scene及direct/run、via/run，尚未生成或启动；明确窗口先原13项prepare/多插件加载与切树，再正式同源direct。


显式角色收紧后的111项局部回归首轮110通过，唯一失败为原vision入站测试仍期望旧kwargs（缺staging=True），原27.135s失败日志保留；已更新该原入站合同，未改任何物理条件，重跑到新corrected日志。此前108过/36过/4过保持各自版本边界，不把此首轮说成全绿。


显式角色合同修正后core+staging共111项全部通过12.996s（新corrected日志），原110/1失败日志保留。已收到无人机/研究根明确限定窗口：仅原13prepare与一个隔离实例两次AMCL当前位姿静止Goal加载核对（staging→默认，前UUID terminal后才下一）；car_hold保持，不扩完整direct/via/P8/QA或批次。完成后核原UUID/参数/独立静止与owned清理，立即归还。软件切片先冻结版本再检查；若静止Goal有误差不释放hold追目标，只保留失败/取消原ID，不重发。
