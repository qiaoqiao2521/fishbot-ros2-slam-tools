# 无人机历史诊断

在同一网页查看已保存飞行的EGO名义曲线、实际轨迹、事件与原报告。使用Lichtblick原生MCAP播放器，不启动飞行。

## 使用

启动已有工作台服务后，打开 `/drone-diagnostics?taskId=<原任务ID>`。手机使用相同链接并追加 `&mobile=1`。
`/drone-station` 的“打开历史飞行诊断”进入对应回合；也可以在诊断面板切换历史记录。

点击“定位首发故障”或带时刻的事件，三维、曲线和面板共用播放时间。支持后退、播放和暂停。
黄线表示当时已收到、仍在时域内的名义B样条；绿线为保存的Gazebo位姿，缺真值时改为橙色MAVSDK估计。
显示官方X500网格与记录姿态；网格缺失时显示位姿示意，不声称模型正在加载。

## 证据边界

- 整回合通过项、落地与解除电机直接读原报告，和播放时刻的阶段分开。恢复落地不改变原任务失败。
- 未记录备份时不画青线。离线MINCO结果不被混入历史执行。
- 候选界只是原阶段日志诊断，不等同最终接纳或拒绝。缺绝对时刻的碰撞日志保留局部时间和行号，定位按钮禁用。
- 感知时序来自原失流日志，显示可用的源、接收、匹配和融合时刻；不冒充全帧延迟统计，不混减墙钟。
- 实际轨迹是保存的位姿样本，原报告的全频评分另列。过期位姿不继续显示为新鲜机位。
- 可选文件缺失或单行损坏仅降级相应通道。报告任务ID明确不符时只跳过该报告，保留轨迹。

## 实现与接口

`drone-diagnostics.cjs`在已有任务目录和drone的`output/`下一层记录目录中按`request.json`原ID发现终态记录。
`GET /api/drone/diagnostics`列出可用回合；`GET /api/drone/diagnostics/<id>`返回摘要。
`GET /api/drone/diagnostics/<id>/diagnostics.mcap`支持Range读取；入口跳转至原生remote-file播放器。
这些接口不接受控制写请求。诊断页面不挂载RobotStation或实时WebSocket。

派生MCAP位于工作台忽略的`workbench-tools/output/drone-diagnostics/`，原记录不改写。
输入的大小/mtime和模型定义变化会刷新派生缓存；不使用内容哈希执行锁。源码不包含原日志、模型或MCAP。

## 局部验证

在项目根运行：

```sh
node --test apps/fishbot-control-station/workbench-review-tests/drone-diagnostics.test.cjs apps/fishbot-control-station/workbench-review-tests/drone-services.test.cjs
```

已有工作台启动后，使用本机已安装Chrome和项目Playwright检查真实历史回放：

```sh
STATION_TEST_URL=http://127.0.0.1:5187 DRONE_DIAGNOSTIC_ID=<原任务ID> node apps/fishbot-control-station/workbench-review-tests/drone-diagnostics-browser.cjs
```

该浏览器检查使用独立临时资料，记录并拦截控制写请求，不使用日常Chrome账号。
结果与桌面/390px截图保存在忽略的`workbench-review-tests/output/drone-diagnostics/`。
检查不代替PX4飞行、动态避障或SO101物理验收。
