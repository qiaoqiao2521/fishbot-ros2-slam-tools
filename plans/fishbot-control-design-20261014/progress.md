# Progress

## Current
本轮实施、Figma与网页验收完成。源码交付目标为既有 main；具体提交以 Git 历史为准。

## Done
- 根首页整体重排，复用控制/数据/地图/日志实现。四工作区共用响应式导航；手控hook仍只随dashboard挂载。
- Header区分fallback/offline/ROS来源及连接/数据报告；连接成功不冒充实体在线。保留日志导出与地图投影函数；IMU与技术来源可展开。
- 最小持按取消修补：松手、停止锁定、方向替换和卸载均使迟到回执失效；卸载有挂起方向时主动零速。4项异步回归通过。
- 前端148/148、0 failed/pending/todo；类型检查、lint、domain107生产构建通过。3项来源语义测试拒绝fallback/offline假在线。
- 1440、937、390px网页四工作区无水平溢出；desktop控制与状态并排。持按/松手、IMU展开、导出JSON、路由与顶部恢复均验证。所有隔离浏览器写请求均被终止在mock interceptor，forwardedWrites=0。
- 当前用户IAB根页面已刷新；读回资产 `index-DxS3mL7d.js`、页面标题及ROS来源。浏览器宽961/scrollWidth946，无横向溢出；保持现有ROS进程、网络及协同任务。
- Figma可编辑设计：[桌面](https://www.figma.com/design/pqZuyO2RL12O9KoQ1Aevdr?node-id=3-519)、[手机](https://www.figma.com/design/pqZuyO2RL12O9KoQ1Aevdr?node-id=3-520)。43 scoped tokens、6 styles、4本地components并复用Simple Design System Button；desktop243层、mobile211层；两者image fills0/missing fonts0。字体Noto Sans SC，数据明确设计示例。桌面完成截图检查，手机版完成结构/字体/边界读回；实际手机版网页另做390px截图与交互。
- 原coop图片buffer、source/clock代次、截止时间和unknown任务所有权逻辑保持；当前实际任务完成记录保持。未新增物理运输验收。

## Evidence
本机忽略目录 `/home/muqiao/.cache/fishbot/control-design-20261014/`：`check.cjs`、`acceptance.json`、`tests-final.json`、桌面/手机截图、私下导出JSON和首轮QA失败记录。Figma ledger `/tmp/design-system-state-fishbot-control-20261014.json`，桌面截图 `/tmp/fishbot-control-figma-desktop-20261014.png`；原agent画板创建及读回记录保留会话。
验证：frontend目录 `npm test`、`npm run typecheck`、`npm run lint`、`VITE_FISHBOT_SIM_DOMAIN=107 npm run build`；本机隔离QA脚本不透传写请求。

## Remaining
无实施或验收剩余项。仓库交付由本轮根 Agent 按既有提交推送约定收尾，最终 SHA 以远端读回为准。

## Issues
- `fishbot_motion_control_microros/release.sh`继续保留未执行、未提交；同工具链boot_app0、micro-ROS构建配置、esptool/merge CLI及4MB板型分区未验收。根负责离线审查，入口仍为既有合作计划progress，实体已售，不刷写。
- 断流后的旧桥接报告有效期未新增检测；保持最近报告语义，后续数据源完整性任务独立处理。
- Figma桌面/手机版是配套可编辑设计，网页响应式布局适配实际数据与现有操作，不声称逐像素相同或手机APK验收。

## Next
按真实使用反馈细调UI，保持ROS/任务与当前来源边界。

## Knowledge closeout
already_covered：my-programming-world/Wiki/自动化开发范式与智能体协作.md「按当前任务选择验收依据」已覆盖UI真实渲染/交互与代码检查分开验收。本轮已核对原段，不重复写知识页；布局与Figma状态保留项目中。
