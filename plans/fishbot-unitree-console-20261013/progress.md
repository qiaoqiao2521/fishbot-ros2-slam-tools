# Progress

## Current

2026-10-13：用户明确选择 FishBot 控制站。原对话检索、前后端实施、只读复核和隔离运行验收完成。root 负责最终提交、推送与远端回读。

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

供本机查看的隔离实例：`http://127.0.0.1:5178/radar`，domain106；mission9078、rosbridge9098、backend8088。所有服务仅监听回环。owner=root。

本轮拥有的进程组：simulation838478、rosbridge840986、frontend845975、backend855731。来源记录为上述目录的 `owned-processes.json`。结束查看时先核对PID、PGID和命令仍对应本轮，再逐个停止进程组；不要按进程名称批量停止其他实例。验收观察器843537已停止，原记录保留。收尾HTTP读回为200，任务为succeeded，真值速度近零。当前无排队Goal，仿真车已停稳。旧domain93及用户网络未更改。

## Retained Work

`fishbot_motion_control_microros/release.sh` 是独立固件保留项，未执行或提交。owner=root。最短入口：阅读脚本，检查shell语法，逐项核对工具链、板型、分区、合并镜像地址与参数材料；没有真实板型与固件发布任务时停在静态审查。实车已售，本次不进行烧录。

知识收尾：already_covered。采用既有 `Wiki/ROS2 与 FishBot.md` 第4节逐层反馈、第11节独立真值和第12节未知结果保留原Goal；本轮没有需要重复写入的新规则。项目测量与运行状态留在本计划，原始历史证据留在History Viewer。

## Delivery

提交与远端回读待root完成；只提交已验证源码、文档和原有离线演示PNG。运行日志、实际地图、私有逆向素材和release.sh不入库。
