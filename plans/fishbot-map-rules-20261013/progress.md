# Progress

## Current

当前第一阶段六项Acceptance均已实现并逐项验证。严格复审补齐手机完整保存/载入、UI模板派发以及删除后实际路线恢复；修复已确认删除被新观测撤销的状态错误。既有与新增失败记录全部保留；根串行提交推送本轮修复与可复用验收入口。无实体车操作，没有训练策略权重。

## Delivered behavior

- `/simulation` 增加虚拟墙、矩形禁区、观察、撤销、移除和显式保存。
- 保存、发布、应用分别表达；地图SHA、规则revision和实际发布版本绑定。外部writer刷新不伪报applied，活动/未知任务保护原规则。
- 两张原生costmap应用KeepoutFilter与后置InflationLayer；软件规则不改实体、雷达或AMCL地图。完整足迹、padding与RPP碰撞检查保留。
- 复用现有FollowWaypoints；路线保存/载入不运动，实际任务记录保留版本与首次停止原因。
- 规则保存、模板保存与mission结果未知均不自动重发。模板保存未知只阻止重复保存；明确派发有效草稿仍可用。
- 晚到的旧GET不能覆盖新资源。任务终态unknown显示“终态未知”。

## Verification

- `./fishbot.sh check-feedback`：402项通过，control209、mission94、autonomy61、frontend38，零跳过/缺依赖。包含67项bridge与27项map helper、8项Keepout配置测试。
- 全前端80项测试、类型检查、相关lint和构建通过；根另存最终测试/构建输出。
- 选定MuJoCo workspace构建通过；`./fishbot.sh check` 布局/语法通过；diff检查通过；7份受影响文档21个相对链接目标存在。
- 最终原生 `acceptance-c` 7/7：global/local禁区点cost 0→254→0；区内Goal具体footprint拒绝且任务身份不变；活动规则更新409；实际绕行成功；两costmap删除读回；行驶中取消同ID终态并停稳；真实成功/取消任务记录持久化。
- 绕行终点误差0.024763米、偏航0.039681弧度。590帧独立真值；最大接收间隙0.052400秒、源间隙0.048秒。全部源年龄及严格时钟推进通过。
- 两costmap实际radius0.13米、padding约0.01米；独立oracle使用保守外接圆0.144142米，最小采样净距0.222314米、分段线性扫掠下界0.217179米。此界不证明未采样连续运动。
- 到点与取消后均检查完整连续0.7秒窗口内全部真值帧；取消接口终态早于物理停稳，二者分别验收。
- 最终Playwright桌面1480×1080与手机390×950触屏7/7；无页面异常/横向溢出。实际保存已转发后丢掉浏览器回执，读回对账成功，仅一次POST；编辑与模板操作未发mission，实际位移小于0.01米。

## Preserved failures and corrections

- `acceptance-a` 失败：mask先扩0.13米，再由RPP完整足迹重复检查；清图恢复短暂重建订阅又被立即取消。改为原始规则几何+半格栅格余量、后置原生膨胀；短缺确认等待，连续有效缺失/反证至少3秒才收束。沿用同一矩形、目标与原碰撞参数复测。
- `acceptance-b` 在测试用GetParameters动态client发现前调用，4秒无回执，未改规则/派发任务。补DDS服务就绪等待，保留原响应与评分门限；`acceptance-c`重新执行通过。
- 浏览器早期a/b是QA选择器错误；c及最终脚本通过。原输出全部保留，不写成产品缺陷或重试首轮通过。

## Runtime and evidence

本机证据根：`~/.cache/fishbot/map-rules-acceptance/session-20261013/`。运行数据与截图均在Git外；不提交实际地图、私有逆向产物或运行日志。

最终运行：domain107，合成arena；simulation PID532886。frontend5179、mission9079、Java8089、rosbridge9099均loopback。页面 `http://127.0.0.1:5179/simulation`。只验收此合成场景，不能外推住宅实测图、手机APK、实车或生产长测。

Owned units（root Codex）：

- `fishbot-map-rules-simulation-107-fadd107c.service`
- `fishbot-map-rules-rosbridge-107-fadd107c.service`
- `fishbot-map-rules-backend-107-fadd107c.service`
- `fishbot-map-rules-frontend-107-fadd107c.service`

仅用精确unit名管理，不按进程名批量结束。`runtime-fadd107c/owned-services.json`保存脚本与启动身份；`restart-source-manifest.json`记录最终Python运行启动前源码；`delivery-runtime.json`核对主PID/子进程、6个关键源SHA、当前frontend SHA和有效生成参数。生成参数SHA为`85801d6c741b965790e2db5382df0b9895b407af5ac3a952794e4ce8bb1ccb9d`。Nav2状态查询overlay继续复用既有固定源小补丁，未改系统版本。

原生来源：`acceptance-c/result.json`、`truth.jsonl`、`acceptance-c.log`；最终浏览器：`browser-result-final.json`、`final-desktop-rules.png`、`final-phone-rectangle-draft.png`、`final-unknown-save-recovered.png`。离线：`feedback-delivery.json`、`frontend-delivery-test.json`、`frontend-delivery-build.log`、`layout-delivery.log`、`build-final.log`。

## Retained firmware work

`fishbot_motion_control_microros/release.sh`为开始前唯一未跟踪成果，保留未执行/未提交，owner=root Codex。bash语法通过，发布验收未过：引用`.config/microros/colcon.meta`需核对忽略的本机来源；已有root `microros-colcon.meta`不能擅自替换；workflow未提供必需`BOOT_APP0_BIN`；esptool未固定版本且旧merge_bin CLI兼容性待核实；实际板型/4MB分区与boot_app0来源未核实；tag插入sed未经转义。最短接续入口：读脚本、workflow与platformio配置，补可复现工具链及纯构建验收。无当前实体/固件发布任务，不运行烧录或发布。

## Deferred

日历Schedule、BLE配网、自动房间划分、完整episode采样、domain randomization、学习策略及真实迁移属后续阶段。任务记录约1Hz/末60份，是紧凑摘要；不是完整obs/action/next_obs训练数据。丢失action handle后的unknown目前无自动对账入口，保留不重放。

## Knowledge closeout

updated：Obsidian既有 `Wiki/ROS2 与 FishBot.md` 第18节“软件禁区与实体障碍分开，规则确认绑定版本”，并同步 `Wiki/开发知识入口.md` 触发词。根追加局部段落，保留既有dirty内容；实际读回段落与入口锚点通过。原始材料留在本机，当前验收状态回源项目。

## Git delivery

功能提交 `422e26fb2995e7ad612f912b23aae937c007bf5c` 已推送既有 `qiaoqiao2521/fishbot-ros2-slam-tools` 的main；GitHub API读回一致。操作前验证新账户ID238822818、目标owner和fetch/push URL，保持公开可见性。只提交29份已审查代码/测试/文档；最终收尾文档另行提交。不上传缓存、运行日志、地图、凭据或固件保留项。最终运行关键源与当前frontend SHA再次读回一致，规则revision10已applied，真值静止。根为保留项及后续接续owner。

## Strict closeout audit

根与独立只读审查对照原始脚本/轨迹确认：上一轮第1/3/5/6项证据满足；第2/4项partial。手机仅画图并撤销；桌面模板载入只核点数，未跑UI派发；删除后返程真值最小x约1.113609，没有穿过原禁区x0.45～0.75。原7/7报告真实，但不能等同六项Acceptance全部完成。

接续：保留原domain107运行和原规则；390px触屏新增远处临时规则，保存后只删除自己ID；保存两点模板、载入并核坐标/yaw/返航开关；UI派发一次并真实到达原禁区内部及最终点。独立Probe持续记录truth，读回两costmap、按序经过两点、同ID终态与完整连续停稳。脚本为tools/fishbot_map_rules_ui_acceptance.py及伴随cjs。根负责实际运行及串行交付。

## Strict closeout results

| 原计划验收项 | 结果 | 对应证据 |
| --- | --- | --- |
| 1. 几何、版本、地图、活动/未知保护 | PASS | 当前405项反馈回归，其中97项mission（27 helper+70 bridge）；native禁区目标拒绝、活动规则409且原ID不变。 |
| 2. 桌面/390触屏完整规则与模板操作 | PASS | 原最终桌面7项+当前ui-strict-f的9项手机行为；触屏画/撤销/保存/仅移除自己的ID；实际模板保存、读取、载入，坐标/yaw/返航开关逐值核对。 |
| 3. 两costmap实际禁区与独立绕行 | PASS | 新版acceptance-strict-d 7/7，原参数和0.144142米保守外接圆；593帧，终点1.713厘米，最小净距23.592厘米，扫掠下界22.790厘米。 |
| 4. 删除后costmap及路线实际恢复 | PASS | native点0→254→0；ui-strict-f两点实际完成，252帧进入原x0.45～0.75/y±0.3区域，前后两图与实际mask测试点均为0。该轮临时软件规则位于原生81点确认空旷区，未覆盖实体障碍。 |
| 5. 原确认/取消/未知/时间保护 | PASS | 当前405回归零跳过；native行驶取消同ID终态并完整停稳；UI真实模板保存转发后丢回执，只有一次保存POST，同ID读回对账；全程仅一次mission POST。 |
| 6. app、执行源与既有远端交付 | PASS | 页面HTTP/真实UI可用，6个关键启动源+54个frontend源SHA核对；固定生成参数SHA；功能与本次修复均由根交付既有新账户main，远端读回另由Git确认。 |

ui-strict-f总12项（9 UI+3独立物理）通过，零页面异常或横向溢出。920帧，最大接收间隙0.047107秒、源间隙0.040秒，源年龄0～0.006秒；终点误差0.059990米、偏航0.167429弧度。按保存模板实际触屏坐标(.61,0)、(.15,.40)评分，顺序经过两点、同ID成功/记录与完整0.7秒新鲜停稳通过。触屏像素取整允许目标选点至多3厘米差异；保存→载入→真实派发的坐标/yaw/返航开关必须完全相同，未放宽物理评分。

### 这轮故障与失败边界

- ui-strict-a：新Probe尚未发现snapshot-time map TF，未操作UI或运动；补有界只读发现等待，保留快照时间与响应门限。
- ui-strict-b：UI9项与物理路线已执行，但任务后规则持续published。原因是已确认的删除事务永久保留；后续扫描在旧删格产生254，误撤销applied。4帧生产匹配重放与UI先前applied事件定位因果。仅在同版本全healthy后退休previous mask；当前墙持续查、新版本重建、初次254/255或部分图确认仍等待。新增3行为回归，未改Nav2参数、模型、TF选择或时间门限。
- ui-strict-c：新版UI9项和完整路线通过，规则状态保持applied；父验收错误要求后续local软代价140等于0。12帧原生数据/TF一致，mask0，global0、local140，最近实时lethal距离约0.293米；保留软代价，不改导航。修正测试为mask0且成本<253，保留实际值。
- ui-strict-d：复用负x测试区后首次删除无法确认。该区域覆盖合成实体挡板边缘；这是首次未确认的合法拒绝，不作为修复失败或强制标applied。改用原生数据证实空旷的独立测试区。
- ui-strict-e：2,-2候选区接近另一挡板的膨胀边缘，81点初始全0门禁拒绝，未操作UI或任务。结合实际arena.xml选择2,2区域；ui-strict-f81点0门禁与完整链通过。
- native GetCostmap存在已观察到的raw拷贝/更新并发空白；snapshot/latest TF在静止探针一致。此项保留为独立局限，不以它忽略有效当前禁区反证，未新增生产稳定性声明。

### 当前运行与新增证据

证据根沿用session-20261013。`runtime-fadd107c/strict-restart-source-manifest.json`绑定当前bridge SHA `4d16b15e4df970726a874ff3611f56c71d880cbc75834a79c84226a6084bc2c0`；`strict-delivery-runtime.json`绑定native回归PID604602；`strict-final-runtime.json`绑定最终UI episode PID626695。四unit、端口、生成参数SHA不变。重启只发生在自有空闲合成episode，规则、模板、实际记录与每轮失败均保存；没有操作其他运行实例或网络。

新增结果：`acceptance-strict-d/result.json`/truth.jsonl、`ui-strict-f/result.json`/truth.jsonl/browser-result.json/marker.json及5张手机阶段图；`feedback-strict.json`；诊断为`rules-confirmation-debug/`与`after-route-point/`。ui-strict-b/physical-analysis.json为离线分析，未把失败记录改为重跑通过。

Knowledge strict closeout: updated。根修订原Obsidian FishBot第18节，追加删除版本事务、软代价及同一UI任务链验收；同步原问题入口触发词。两处文本与锚点实际读回通过，保留既有dirty内容，未复制原始日志。当前进度只留项目。

UI终态补充读回3项通过：同ui-strict-f原ID的记录实际显示“巡逻完成”；规则显示导航已应用，载入同模板后开始可用；零POST。使用可复用terminalVisible等待资源异步刷新，再保存06-phone-confirmed-terminal-and-applied.png。此为同一任务继续只读验收，不新增任务或重跑。运行关键6源与54前端源再次匹配，规则22 applied、同ID succeeded、真值静止。第6项本轮提交/推送已完成；根通过Git ref与GitHub API双读回确认。

Strict Git delivery: 修复与可复用CLI提交 `f37e326b9841261faf873a007603bf893f9fbf3d` 已推送新账户既有main；git ls-remote与GitHub API两路均读回该SHA。只包含9份已验证代码/测试/文档。最终收尾表随独立文档提交同步；模型、网络和实际地图未修改。仓库唯一未跟踪项仍为原release.sh，owner和具体阻碍保持本页保留项记录。

QA来源：ui-strict-f的执行版cjs已按报告SHA重建归档为executed-browser-source.cjs，SHA `0d8db4e42798f61491071221e7cf71005cb458f4fff21274b0874947e652e5f6` 严格匹配。当前源码额外等待UI同ID记录终态和applied，terminalVisible共享断言已由同一任务只读补验收3项验证，不新增动作。该补充不被写成另一次完整路线重跑。
