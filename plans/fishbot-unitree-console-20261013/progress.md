# Progress

## Current

2026-10-13：用户明确选择 FishBot 控制站。原对话检索、前后端实施、只读复核、隔离运行验收和功能提交推送完成。远端与本地功能提交一致。

## Done

- 核对真实项目根、SpecMesh、本地逆向文档和原14项地图/Goal/图片成果，复用并整合。
- 实施 `/initialpose`、`/plan`、正确 ROS 时间、路径连接代次隔离和不同失败码。
- 实施观察/Goal/重定位模式、位置与朝向草稿、显式提交、未知回执保留和手机触屏。
- 巡逻入口复用现有 `/simulation`；明确区分控制环境。
- 后端36项测试，前端57项测试、类型检查、构建和相关lint通过；零失败与跳过。
- `./fishbot.sh check` 12项入口检查通过。9个文档相对链接有效，diff 检查通过。
- 桌面、390px触屏和真实ROS通路验收完成。两次初位姿、七个NavigateToPose与两轮FollowWaypoints具有直接观测记录。
- 原15厘米物理门槛保留：首轮返航18.83厘米失败；同路线第二轮12.57厘米通过，最终29帧停稳1.146秒。估计位置容差0.12→0.03不等于实际精度。

## Evidence

本机忽略目录：`workspaces/fishbot_mujoco_ws/.runs/unitree-console-20261013/`。保存浏览器脚本、七项交互检查、原始ROS事件、两轮结果、参数读回、截图和根Agent独立分析。原失败轮与两次修复前观测脚本保留；它们不计入成功。

实际后端Jar SHA256：`f61edd0681d8cd74103605d777a73aa7d2338dd1ac43e18660b05242d37eabe8`。源快照在进程启动后、浏览器动作前取得；运行后独立比较无后端改动。前端首轮快照在浏览器动作前取得；末次修正离线地图标签后，重新通过57项测试、构建并取得最终页面截图。

`root-independent-readback.json` 分析27137帧真值，核对全部动作UUID、两轮相同巡逻请求、时钟及新鲜停车。此统计是分析时快照，不称为完整生命周期采样。当前轮丢回执夹具未送达服务端，不能称为机器人已接受后的失联验收。

## Runtime Handoff

2026-10-13 运行恢复：用户报告页面无法打开，四个端口均拒绝连接。旧后端在08:02:10正常关闭；系统shutdown/reboot记录与当前10:13:36启动时间确认整机重启，不能归因为聊天回合结束。旧PID均已不存在。以下旧进程组段落保留为首轮运行记录。

当前复用原Jar（SHA不变）、ROS修复overlay和同一domain106配置，四个服务由用户级systemd transient units接管。新来源记录位于本机忽略目录 `workspaces/fishbot_mujoco_ws/.runs/unitree-console-20261013-reopen-kqmz0_m_/owned-services.json`，owner=root。unit分别为 `fishbot-console-{simulation,rosbridge,backend,frontend}-106-kqmz0_m_.service`；全部active/running，仅监听原回环端口。管理命令须使用 `env XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus systemctl --user`，停止前先核对上述owned记录和unit身份。不设置开机自启，整机重启后仍需显式启动。

实际HTTP读回 `/radar`、`/sim-api/state`、`/sim-api/map` 正常，仿真ready=true、任务idle且真值速度近零；Java control/laser两桥connected，map/scan/TF/localization均ready。未发送运动、Goal或初位姿。浏览器工具绑定已有错误标签时被URL协议策略拒绝，未绕过策略；本轮不声称已取得恢复后的浏览器画面，提示用户手动刷新。知识收尾仍already_covered，只更新项目运行记录。

供本机查看的隔离实例：`http://127.0.0.1:5178/radar`，domain106；mission9078、rosbridge9098、backend8088。所有服务仅监听回环。owner=root。

本轮拥有的进程组：simulation838478、rosbridge840986、frontend845975、backend855731。来源记录为上述目录的 `owned-processes.json`。结束查看时先核对PID、PGID和命令仍对应本轮，再逐个停止进程组；不要按进程名称批量停止其他实例。验收观察器843537已停止，原记录保留。收尾HTTP读回为200，任务为succeeded，真值速度近零。当前无排队Goal，仿真车已停稳。旧domain93及用户网络未更改。

## Retained Work

`fishbot_motion_control_microros/release.sh` 是独立固件保留项，未执行或提交。owner=root。最短入口：阅读脚本，检查shell语法，逐项核对工具链、板型、分区、合并镜像地址与参数材料；没有真实板型与固件发布任务时停在静态审查。实车已售，本次不进行烧录。

知识收尾：already_covered。采用既有 `Wiki/ROS2 与 FishBot.md` 第4节逐层反馈、第11节独立真值和第12节未知结果保留原Goal；本轮没有需要重复写入的新规则。项目测量与运行状态留在本计划，原始历史证据留在History Viewer。

## Delivery

39个已验证文件提交为 `fb2f32e6db6e694b1e94d37d27fd3f4bcbcbc30d`，已推送到既有 `qiaoqiao2521/fishbot-ros2-slam-tools` 的 main；远端refs/heads/main读回与本地功能提交相同。身份qiaoqiao2521/238822818、仓库ID1381244533/public、fetch/push URL均核对，未改变可见性或账户配置。暂存文件与审查源逐字节相同，最终前端及Nav2配置与收尾快照SHA一致。

只提交已验证源码、文档和原有离线演示PNG。运行日志、实际地图、私有逆向素材和release.sh不入库。剩余唯一未跟踪文件release.sh已保留并记录root接续入口。收尾记录随独立文档提交交付，不新增功能或验收声明。
