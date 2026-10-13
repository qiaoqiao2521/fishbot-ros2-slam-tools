# Progress

## Current

第一阶段实现、离线回归、原生导航和桌面/触屏验收已完成。Git提交推送待根串行执行。无实体车操作；没有训练策略权重。

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
