# Progress

## Current

预声明50短停靠＋6完整运输已全部执行。独立读回：34短停靠完成、7正确取消、9短回合失败；运输ideal1/2、perturbed2/2、vision1/2，共4/6通过。整体验收未通过，11失败保持。P1开发/留出各3通过，阈值只从开发冻结；留出未用于调参。原物理/时间/碰撞门槛不变。以下较早段落保留阶段历史，以本节及末尾最终读回为当前状态。

## Done

- 核对 SpecMesh v1.1、项目状态与 Arena 已交付边界。
- 阅读根研究 REPORT 的项目基础、分工和实验范围。
- 保留已有未提交 release.sh 与两个独立 Git 边界。
- 只读核对 StationBeacon、原生停靠、AMCL合同、相机、SO101规划、取消/清理与独立oracle；root重算三个私有评分脚本SHA。
- 定义P0合同、P1基线、P2受扰面板、P3实际RGB的实施顺序，保留原物理与完整运输评分。
- 补CLAUDE.md、docs/DECISIONS.md与README/PROJECT/ARCHITECTURE/COOPERATION渐进入口；纠正README仍称Arena待GPU/许可的旧状态。
- 独立审查指出视觉观测与既有物理安全反馈不可混称、基线面板须预声明；root已修正两处。
- root检查6个标准核心文件、10份文档及49个相对链接，缺文件/断链均0；git diff --check通过。本轮只改文档，不重复运行代码回归或仿真。
- 有效GitHub账号qiaoqiao2521/id238822818与既有public目标仓库/main均已读回。10份文档提交954be89e723e77982691e69a4219e45256fe7691，已推送并经GitHub API确认同SHA；本条状态收尾随后单独同步，最新版本以远端Git为准。
- 用户“开始”后实施P0：标准PoseWithCovarianceStamped/DiagnosticArray、Exact TimeSynchronizer、来源/时龄/回合/序号校验、协方差传播和唯一原生转发；理想默认保留，vision不产生真值检测。
- 独立评分迁入仓库，保留原9项函数AST；历史成功/失败重放分别保持通过/失败，明确offline_replay。当前stack-gate仍不消费车臂结果。
- root最终114合同/core/oracle、54场景/物理/prepare/launch检查通过；全反馈696/696（control416/mission145/autonomy61/frontend74），零跳过。layout12、bash/diff通过。独立审查发现旧物理信标来源前提遗漏，已补5种拒绝负例并独立复核关闭。
- 隔离domain120/9090已就绪，107/114的PID与invocation保持。冻结34项输入/执行源；面板预声明一次运动取消与一次完整运输，原物理门槛不变。

## Remaining

- 11个预声明失败的资格验收仍incomplete，owner=root。接续仅用开发pose/seed11/29/47的新输出调查偏航持续停稳、接收时龄与RGB准备可见性；不得用本轮留出调参或改写评分。开发修复后需另冻结新面板/预算与新留出。
- 本轮源码、知识状态和远端串行交付由root收尾。原release.sh继续保留、不执行、不暂存；既有静态阻碍回源协同计划。
- SpatialLM和工作流模块由内部对话独立交付，root串行整合并在各自计划记录实际边界，不计入本轮56例。

## Issues

此前把待建计划留为 pending，没有完成已派发的规划责任。本次补齐，不将计划建立称作视觉停靠能力完成。

初次猜测tools/fishbot_cooperation_oracle.py不存在，已回源实际私有缓存。一次组合文档补丁未匹配COOPERATION行，工具整体拒绝、未留下部分改动；读取准确行后重做。源码与历史证据均未修改。

独立oracle仍在私有缓存，真视觉合同与车载标定尚未实现；由root在P0审查最小持久化范围。原release.sh继续按协同计划Retained work的阻碍保留，不执行/提交。

P0更新：独立oracle已完成最小迁入，原缓存仍保留。首次native采集因venv缺系统yaml路径在派发前退出，start_posts=0、source34未变；原failed报告/日志不修改。启动就绪不能要求1m内有效位姿，远处合法out_of_range诊断同样证明接口就绪；root已改为校验合法诊断，停止错误等待器。采集改用现有fishbot_cooperation.sh oracle环境入口，在新observer-fixed目录复用同一尚未派发任务的世界和episode，不重发或重启任务。

该回合真实运动取消原UUID到CANCELED，真值停车1.38源秒；后续完整任务停在原生Dock，观测接收龄约0.50227s。源码34起止一致。独立窗口153–159源秒61帧无配对漏帧，source gap0.1/producer循环wallgap0.56958s/转发wallgap0.58131s，clock和physics仍<0.14s；root没有放宽门槛。原failed score与cleanup失败报告保留。验收脚本原来遇重复静止帧会重置计时；追加只读三UUID终态和真实连续1s停车后已停止owned120（MainPID0），原107/114保持。补清理报告的raw age在stop之后采集，不能当停止前精确年龄；动态判据在stop前确认<0.5s，原值不回填。

最小修复改为50Hz状态周期测量，与scan解耦且先发布；没有新scheduler、旧帧重打时间或模型/门槛改动。新native-20261014-50hz预声明同两案例、34源冻结、新独立episode，正在复验；旧失败源34份副本已冻结保留。新清理记录停止前精确age，重复帧不增长但也不重置静止证据。

## Knowledge closeout

规划阶段already_covered：Wiki/ROS2 与 FishBot第19、20节覆盖理想信标、物理交接和配对边界。P0实测后updated：root补第19节“源频率与墙钟接收龄”、标准消息/字节诊断/协方差边界；开发知识入口新增对应触发词，原页与入口均已读回。保留10个物理记录缺序号、单回合与未接视觉边界；没有发布知识库其它累计修改。根研究总表仍由研究协调者维护。

## Next

先完成当前比例回归、源码审查和远端交付。此后按Remaining建立开发整改入口，保持原失败、原107/114与独立Git边界。

## 当前独立验收读回

native-20261014-50hz完整任务SUCCEEDED，原生1Dock+2Nav均终态4；运动取消同原Nav UUID终态5、真值停稳2.18源秒。独立原K与追加episode/handoff/transport评分均通过。货物实际位移1.789564056m、车体1.790401062m；抬升/双指接触、完整外廓释放留盘、臂home先连续1s、持续携货和最终停稳均通过。越界/非预期接触/独立位姿坏样本均0，载物1397样本违规0；clock/step/seq无回退、任务内reset0。

完整任务墙钟317.428s，未触发原360s上限。source34 start=end=当前文件，root逐项重算确认；原场景模型与Nav2/BT参数保持。新转发信标5752帧最大接收gap0.181980s、源gap0.04s；物理记录7376帧仍有10缺序号，max source gap0.2s、max接收gap0.333410s，不能称无采样缺口或长期稳定性。没有配对总体增益/训练/真实视觉声明。

停止前新鲜raw age0.008087s、native全部终态、连续静止与guard关闭已确认；systemctl readback MainPID0/inactive，9090关闭，owned120两个实例均已停止。107 PID626695/invocation17212db542fa466996fbe2af461e6253、114 PID1467776/invocation208ccc5e476942148b077ceef4dc6d4a均保持原进程。

root在50Hz最终源后再跑全反馈696/696，零skip/error/缺依赖；前述54物理/场景检查加8项本次采样相关回归通过。唯一证据入口为~/.cache/fishbot/visual-docking-p0/native-20261014-50hz/：acceptance-report.json、observer/score原件、source-start/end、root-independent-readback.json与cleanup-quiet.json。先前零派发采集失败、完整Dock失败及补清理均保留；原始日志/地图/模型不入Git。

## Git delivery

19份明确审查的代码/测试/文档提交5060fa0a9f881160991057bb507576749e8b625b，已推送既有qiaoqiao2521/fishbot-ros2-slam-tools main，并经GitHub API独立读回同SHA。有效账号qiaoqiao2521/id238822818、fetch/push与public可见性保持。本条收尾状态另行同步；最新HEAD以远端Git为准。仅release.sh未提交，沿既有阻碍由root接续；认证、日志/地图/模型素材和其它知识库累计修改未入此提交。

## P1开发基线与预检收尾（实施中）

三个开发基线分别在baseline-dev-r2、baseline-dev-r3-1、baseline-dev-r3-2通过原生同UUID成功、独立物理停车与有效清理；全部owned进程已停止、9090关闭、源起止一致。三组控制/producer/observer源码相同，仅runner在第一、二组之间修正closed socket TIME_WAIT预检；source兼容差异已列在私有baseline-development-summary。留出运动数据尚未读取或用于调参。

阈值只从上述三组开发数据冻结：位置剩余余量0.016409m，偏航剩余余量0.041334rad；高噪声位置σ0.001934m、偏航σ0.006889rad，固定位置偏差0.008204m、偏航偏差0.020667rad。原0.04m/0.05rad物理门槛保持；高斯噪声尾部仍非有界。冻结panel、thresholds、vision-config与calibration receipt均在私有实验根。

RGB静态预检20帧为15近距有效位姿和5远距正确拒绝，不能写成20有效检测。有效样本最大误差0.008897m/0.030277rad；低于60px边长的远标签明确拒绝。标记横移+0.03m、相机cx319.5/cy239.5、单UV纹理和5px角点细化在运动前冻结。检测使用系统OpenCV4.6与显式平面车体先验，完整6D图像协方差仍传播；没有真值检测回退。

失败诊断保留：首次Dock lifecycle尚未ACTIVE，已接受的开发运动回合因桥回调积压触发取消，以及闭端口TIME_WAIT零派发失败。原失败、unknown和清理未合格结果不回填。修复独立物理/感知callback group、4线程executor、锁外lifecycle更新，以及原6s清理预算内对瞬态旧样本继续等待。native未知不重发；wrong-owner guard关闭被原发布者校验拒绝，保留此未合格清理边界。每次修复后使用新目录/新episode。

root当前119项core/oracle/acceptance/fault/readiness检查通过；plant_guard_telemetry只添加独立raw采样描述，不参与通过判据。几何预检覆盖直接与staging两条实际可走分支。P2开发首例通过，其余覆盖以逐轮result为准。

P2首批保留4通过及1个start_posts=0启动失败；第五例map_server配置后ChangeState响应超时，AMCL尚未配置/激活，初位姿参数正确。独立采样确认零任务、held、guard关闭与连续停稳后只停止本owned进程树；root-cleanup-proof明确survivors0、9090关闭、原失败报告不变。临时取证脚本先误用API摘要速度字段、再误用MuJoCo字段，均KeyError且没有停止/改写；读取原raw合同后按speed/yaw_rate重新证明，失败脚本同样保留。

复用项目localization/passage仿真的官方Nav2 autostart_node；三个地图/AMCL原生节点直接自启动，保留原参数和导航manager、Dock速度链。没有同时管理这些节点的第二owner。Launch对象真实展开、AMCL偏航/参数保持与地图scope检查通过；原55s时限保持。旧freeze与新freeze均留私有目录，新freeze只有cooperation.launch.py差异。P2统一新源在perturbed-dev-native-start重跑；额外诊断回合单列，不能隐藏旧分母或宣称父候选改进。

P2新原生启动批5个通过；第6例POST返回明确409“Nav2定位已过期”，backend账本为空、原生handle为空，车辆没有执行任务。旧runner错误混称unknown并等75s，保留原失败。root独立held/quiet/guard关闭和零任务确认后停止launch及observer，源起止一致；observer实际停止并输出原failed score，不重发该编号。新runner区分ApiRejected，仅明确拒绝/idle且无活跃原UUID时允许原清理证明；未知仍核对同编号。采集器就绪后再读ready，和采集准备共用原55s启动预算。当前82项acceptance/core/launch/readiness通过（先前直接core命令缺PYTHONPATH导致import错误，已按项目tools路径重跑，未改控制代码）。

P2开发12/12通过，独立审查核对原result/score、两对raw原UUID4、清理与source/protected。位置P95最高0.026107m、偏航P95最高0.010496rad；plant未观察到tripped，但累计10个采样缺口，不声称连续无介入。控制/producer/注入器保持，分组runner/oracle修复明列；每例源起止一致不等于跨组44文件全相同。开发故障4/4通过：delay两例task completion=false/safety=true，replay两例正常停靠；旧失败原件保持。

P3第一批6例均在派发前No module named cooperation_camera退出，start_posts0，没有物理实例。Launch只在本进程加tools import path；清空PYTHONPATH的真实vision Launch构建与camera7检查通过。第二批vision-development-path实际RGB6例全部正常取消/清理，但未通过正常停靠；相机标准配对本身合格，任务因工位观测过期失败。原图/源/失败score保持，留出运动仍未执行。

开发RGB揭示硬平面先验不适合动态俯仰：帧524原IPPE误差0.00535px，强制平面6.2807px；帧528原0.09742px，强制平面21.5448px。独立物理分别读回pitch=-0.012334/-0.043692rad，z小幅变化；静态20帧不能替代运动标定。root/worker只做RGB离线重放与独立真值对照，未放宽质量、时龄或物理评分；修复边界待私有证据确认。

真实网页桌面取证已取得，但390整体验收未完成。初次QA response.body空buffer与实际解码图像不符，私有QA改取已显示blob字节，产品源不变。窗口结束后的超时和所有零POST取证失败保留；正式GUI acceptance待可持续vision回合。知识回写已局部updated并读回第19/20节及开发知识入口，尚需根据动态俯仰修正硬平面先验认识，不发布其它vault累计工作。


## RGB六维位姿与接收修复开发回合

`vision-development-sixd`实际6回合仅light-dev-1通过，5失败均正确清理。clear-dev-1仅Nav UUID成功，没有派发Dock；一次RGB initialpose与后续AMCL差0.032930m，超过原0.025m/.025rad、0.4源秒校准确认。其他4回合工位观测过期，其中dev-2存在臂遮挡、歧义和分辨率拒绝。静态预检不能证明动态闭环。

开发失败未被重写或计入通过。根Agent保留AMCL原生激光定位，vision不再用远处PnP重置AMCL；RGB继续驱动原生Dock目标且源龄/接收龄/.04m/.05rad/0.7源秒门槛不变。detector原单次spin_once与推理/PNG共循环，三输入接收会被检测挤占；worker在划定文件改为连续接收线程与最新单槽检测，待新运动验证。新core60通过。

完整6D预检20实际渲染：15正例＋5分辨率拒绝，源一致。根按实际`positive`类型重新验证原冻结质量/协方差门槛，receipt-sixd已写入并读回；此前私有脚本误用`pose`类型导致assert失败，该失败不作为验收。无阈值放宽。


接收薄线程已冻结：标准SingleThreadedExecutor后台持续处理三输入和clock，主线程仅取最新帧推理；FaultInjector begin/trigger/apply/status统一互斥，输入/推理后均核对回合。系统与planning关联55/55通过，线程回归实际确认慢检测时clock/frame仍推进、无FIFO积压、shutdown与错误明确。

vision准备点沿程从0.70m改为0.65m，避免Nav2约2.3cm的允许到达误差把标签压到59.67px而被原60px门槛拒绝。最终dock、原车臂模型/碰撞、ideal/perturbed准备点不变；每回合仍按真实manifest检查完整扫掠。新增实际场景生成回归与geometry13/13通过；实现时两次误用尚未赋值的manifest/config名称产生测试失败，已修为现有station_perception并重跑，不记旧失败为通过。


## 冻结后开发验收与留出开始

`vision-development-receiver`6/6通过，root与独立worker分别确认原score、同accepted Dock UUID raw4、原.04m/.05rad/.7源秒、contacts/crosschecks、cleanup、owned0/port关闭与source起止一致。六例公共源码相同。最大停车P95位置0.01793084m、yaw0.01234213rad。guard观察tripped/rising均0，但有4个源采样缺口；不推断缺口内无介入。

实际RGB不是全程厘米精度：整个任务的最差观测P95为0.086615m/0.080622rad，包含接近段部分遮挡；只有终点停靠独立评分通过。相机exact配对覆盖不完整，早期独立pose接收也有空窗；源龄、接收龄、推理时间与采样缺口分别保留。静态预检再次20/20（15有效/5正确拒绝），冻结质量/方差门槛不变。

29项项目执行源码与面板/阈值/私有CLI已冻结至`frozen-code-final/receipt.json`；每回合额外冻结实际manifest/XML/SO101依赖等输入。串行pipeline先baseline-holdout3/3通过，继续P2/P3留出与6full。完整运输保持360秒；短Dock成功不外推运输成功。留出结果不参与调参。

## P1–P3最终独立读回

唯一私有实验根为`~/.cache/fishbot/visual-docking-p1-p3/acceptance-20261014-3b9bd8b3/`。`independent-panel-final-rollup.json`、`independent-panel-declared-50-short-summary.json`、`independent-panel-full-transport-review.json`和`acceptance-report-final.json/index.html`均按原score路径、SHA和task UUID逐项核对。50短回合＋6运输覆盖完整；41短回合达到其预声明结果，但其中7是取消，不是停靠成功。全部56例共38任务完成、7正确取消、11未通过。原83份result原件未改，27次额外尝试单列；8零派发与1unknown保留。中断的零派发目录没有score，不补造结果。

P2留出失败5：两次bias-yaw与combined-parent真值yaw约0.057–0.058rad，超过原0.05rad；dropout-candidate yaw约0.05006765rad且有效停稳仅0.500源秒；combined-candidate物理源龄0.36s/接收龄0.351857s失败。原生终态4不替代独立偏航/停稳判据；unknown和采样缺口不算通过。

RGB留出失败4：clear-0与long-occlusion-0没有有效位姿或Dock UUID，长遮挡未实际触发，不能算正确取消；clear-2在Dock前过期；short-occlusion-2实际渲染遮挡有两张匹配PNG失检，随后过期取消，正常场景仍失败。clear-1完成、variant-1同Dock UUID正确取消。runner清理六例均有效，但三个未使能guard的无Dock回合原oracle保守cleanup仍false；两层原值均保留。

完整运输通过ideal-1、perturbed-1/2、vision-1。同一自由货物分别位移1.788199/1.793034/1.789250/1.790188m，原K及追加交接评分通过；实际双指接触、抬升、释放留盘、落稳、机械臂先回位、携货和终态停车均独立读回。ideal-2因物理时间失败、vision-2因观测过期失败，均未进入装载/运输，不以Nav成功计运输成功。每轮360s上限保持。

四个运输成功的原生均1Dock＋2Nav终态4，独立真值/货物与raw采样一致；活动货物自由关节、无任务内reset/传送/吸附。所有案例源起止与实际manifest/模型绑定、protected状态和owned清理经过独立核对。guard在已观察样本未tripped，但采样孔洞仍保留，不能声称无保护辅助或纯视觉泛化精度。此结论只限仿真，不外推真机或sim-to-real。

## 查看接口的独立显示修复

运动面板后只修查看JPEG/元数据的竞态与quality跨回合诊断。32组不可变JPEG/JSON原时间成对保留；请求读取指定episode/sequence，不替换为latest，仍保持原源龄/接收龄门禁。该源版本与此前冻结运动面板分开，不能把新查看源冒充56例执行源。

root仅启动开发scene的GET-only实例：无start/cancel/reset POST，task.id为空、native_actions为空。桌面1440与手机390均匹配同scene/episode/sequence4553/stamp91.06、角点及26111-byte JPEG实际body/decoded blob；共6次HTTP200、409为0，各30采样持续解码/live=false为0/横向溢出0。手机阻断GET后明确过期并禁用三个动作按钮。此前活动窗口18/20次409原报告保留；不同物理状态只证明静止显示窗口改善，不证明运动成功率或长期稳定。

`viewer-display-validation/root-pre-stop-proof.json`确认独立0.7源秒连续静止、hold与guard关闭；source-start/end起止一致。`root-cleanup-proof.json`确认exact PID/starttime owned树survivors=[]、9090关闭；root随后关闭本5180。原107/114的六保护实例保持本轮冻结inactive/not-found，不恢复历史进程。

## 本轮知识状态与后续接续

knowledge closeout为`updated`：局部更新`Wiki/ROS2 与 FishBot.md`第19/20节及`Wiki/开发知识入口.md`，已读回。记录动态俯仰下硬平面先验的失败、AMCL接近/RGB停靠职责、连续三输入接收与双时钟、动作/物理评分分离。`knowledge-closeout.json`保存页/入口hash与publication=false；没有复制raw或发布vault其他累计修改。根研究总表由研究对话owner维护。

本轮交付保留11个资格失败，接续owner=root；最短入口是原开发scene与`tools/cooperation_acceptance.py`。复现与修复另用新目录/新面板，旧留出保持封存。本轮没有训练、刷写、网络变更或云GPU。内部SpatialLM/workflow模块另有计划和预算，不借此宣称本轮整体通过。

## 最终比例回归与交付准备（2026-10-15）

当前有效源反馈867/867通过（control507/mission145/autonomy61/frontend154），零跳过/缺依赖；全前端203/203、类型/lint/domain120构建通过。新相机、连续接收、readiness、场景/完整几何与launch接入原反馈入口。共享物理适配另在既有planning＋ROS环境36/36通过，包括真实标准QoS/读者暂停后的最新接收。首次将planning-only fixture放进system反馈出现skip，已分开验证；首次planning缺系统PyYAML路径导致两项ROS检查skip，补现有脚本相同路径后零skip，未安装或改库。原partial报告仍留存。

8份当前文档52相对链接全部存在，bash/diff检查通过。root与独立worker复审原9项评分函数AST/门槛保持；查看器身份、不可变元数据与quality回合锁修复没有真值检测回退。受保护六实例再次读回MainPID0/inactive，与冻结基线一致；本轮owned120与5180均关闭。知识页/索引局部内容再次读回，状态updated、publication=false。

源码提交仅包含已核实本轮有效代码、测试和计划摘要，私有输入/图像/地图/逐帧日志/账号信息不入库。原release.sh保持未执行未暂存，沿既有阻碍由root接续。提交与远端SHA由Git独立读回确认；整体验收仍incomplete，不能用测试通过替换11个真实失败。
