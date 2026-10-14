# 成果工作台

打开网页控制站的 `/workbench`。左侧“工作台”和FishBot标志都回到这里。原 `/` 控制总览、`/radar` 地图、`/simulation` 巡逻、`/cooperation` 协同路径保持。

## 能看什么

| 能力 | 已验证的收获 | 保留边界 |
|---|---|---|
| 地图与导航 | 选点、规则、路线、派发时捕获返航点、原生RViz | 后续验收限合成仿真；当前运行状态到操作页查看 |
| 车臂运输 | 同桥取消恢复与两轮完整运输，新三回合独立评分通过 | 使用ideal工位观测；不能补齐旧RGB失败 |
| RGB停靠 | 实际后向RGB、AprilTag/IPPE、观测/动作/物理分层评分 | 原56例为38完成、7正确取消、11失败，严格资格尚未全通过 |
| 空间场景生成 | 官方单例16实体，人工校正六墙后原FishBot CPU100步 | GT18实体；重建精度、起点净空与导航尚未验证 |
| 视频过程分析 | 单个CC0样本375解码帧、29采样、1候选事件和持久复核 | 不代表人数精度、身份、家庭泛化、RTSP或设备部署 |
| Arena组合评测 | L4预检20步、两组各23步、取证与回收链闭合 | zero_action两组success均false，不算抓放或训练提升 |

原56例明细可按全部、完成、正确取消、失败筛选。案例采用中文名称，原ID、原因和评分指纹保留。新增三回合单列，取消不计任务完成，旧失败不被新成功覆盖。

## 快照与当前入口

`frontend/public/workbench/recent-results.json` 是唯一经过审定的成果快照源。页面直接读取它，网页和手机可下载同源JSON。数据绑定冻结日期、来源版本、原报告及59份评分指纹；不包含本机绝对路径、地图、媒体、原始日志或凭据。未来更新必须回源报告审定，不按页面“成功”或进程退出码改判。

“检查本机工具”仅发GET。Vite开发/预览代理固定映射到SpatialLM `/api/health` 与视频 `/api/run`；响应身份、闭合运行状态、HTTP拒绝和连接失败分别显示。初始未检查，不自动轮询，不启动服务、推理、导出、审批或ROS任务。显示的是上次检查时刻，不是持续心跳。代理透传HTTP方法；只读检查由页面GET与上游只读路径共同约束，不宣称代理层强制GET。

编辑器与复核台继续在原页面处理导出和审批。两者只绑定电脑loopback；手机的localhost指手机自身，因此不开放错误的本机直链。当前前端若部署到其他服务器，需显式配置这些只读代理；快照无需依赖分析服务在线。

## 启动与验证

条件：已安装项目现有Node/npm依赖，端口空闲。从前端目录启动：

```bash
FRONTEND_PORT=5180 npm run dev -- --host 127.0.0.1 --strictPort
```

本轮工作台入口为 `http://127.0.0.1:5180/workbench`。场景编辑器 `http://127.0.0.1:8867/` 不带render标记启动；视频复核台 `http://127.0.0.1:18089/` 读取已有公开样本。启动原工具分别见 [SpatialLM](../experiments/spatiallm/README.md) 与 [视频仓库使用说明](https://github.com/qiaoqiao2521/uw-yolo-code-assets/blob/908f5bd8e40241bb74ec1bf384205c638edf7b1d/docs/OFFLINE_VIDEO_EVENTS.md)。本次不运行分析、推理或物理任务。

前端运行 `npm test`、`npm run typecheck`、`npm run lint`、`npm run build`。项目 `./fishbot.sh check-feedback` 已纳入工作台数据与页面合同。实际桌面/390px只读QA验证过滤、五区导航、同源快照、两个本机页面与零写请求；记录在项目外缓存，具体进度见 [本轮计划](../plans/workbench-harvest-20261015/progress.md)。
