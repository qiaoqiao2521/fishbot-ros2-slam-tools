# Progress

## Current

P0代码、原默认链和独立取消/完整运输验收complete，root已独立读回。当前文档/知识/源码Git交付in_progress；真实RGB、完整扰动面板与泛化仍pending。没有云端GPU或实体操作。

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

- 完成本轮文档、知识与源码Git交付读回。
- 后续P1完整面板、P2受扰对照、P3真实RGB定位分别验收，owner=root。

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

完成P0文档与源码Git交付，然后P1预声明基线/留出面板与预算。root负责；当前RGB生产器未实施。

## 当前独立验收读回

native-20261014-50hz完整任务SUCCEEDED，原生1Dock+2Nav均终态4；运动取消同原Nav UUID终态5、真值停稳2.18源秒。独立原K与追加episode/handoff/transport评分均通过。货物实际位移1.789564056m、车体1.790401062m；抬升/双指接触、完整外廓释放留盘、臂home先连续1s、持续携货和最终停稳均通过。越界/非预期接触/独立位姿坏样本均0，载物1397样本违规0；clock/step/seq无回退、任务内reset0。

完整任务墙钟317.428s，未触发原360s上限。source34 start=end=当前文件，root逐项重算确认；原场景模型与Nav2/BT参数保持。新转发信标5752帧最大接收gap0.181980s、源gap0.04s；物理记录7376帧仍有10缺序号，max source gap0.2s、max接收gap0.333410s，不能称无采样缺口或长期稳定性。没有配对总体增益/训练/真实视觉声明。

停止前新鲜raw age0.008087s、native全部终态、连续静止与guard关闭已确认；systemctl readback MainPID0/inactive，9090关闭，owned120两个实例均已停止。107 PID626695/invocation17212db542fa466996fbe2af461e6253、114 PID1467776/invocation208ccc5e476942148b077ceef4dc6d4a均保持原进程。

root在50Hz最终源后再跑全反馈696/696，零skip/error/缺依赖；前述54物理/场景检查加8项本次采样相关回归通过。唯一证据入口为~/.cache/fishbot/visual-docking-p0/native-20261014-50hz/：acceptance-report.json、observer/score原件、source-start/end、root-independent-readback.json与cleanup-quiet.json。先前零派发采集失败、完整Dock失败及补清理均保留；原始日志/地图/模型不入Git。
