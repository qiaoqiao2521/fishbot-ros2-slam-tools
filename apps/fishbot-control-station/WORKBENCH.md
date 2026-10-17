# 成熟源码工作台

新底座使用完整 Lichtblick v1.29.1 源码。布局、播放器、时间线、3D、图像和曲线直接使用上游实现。
来源、精确版本和许可见 [UPSTREAM.md](workbench/UPSTREAM.md)。实施进度见 [SpecMesh](../../plans/workbench-code-rebuild-20261018/task_plan.md)。

当前入口用于查看已保存的 SO101 仿真回合。新的仿真任务、启动与取消入口按实施计划接续。

## 启动

条件：Node >=20，已安装系统 Chrome，已准备经过核验的 MCAP 目录。
在本目录执行：

```bash
./workbench-dev.sh install --immutable
./workbench-dev.sh web:build:prod
WORKBENCH_RECORDINGS_DIR=/absolute/path/to/verified-recording node workbench-preview.cjs
```

`WORKBENCH_RECORDINGS_DIR` 必须包含 `so101.mcap`。默认只监听 `127.0.0.1:5186`，端口可通过 `WORKBENCH_PORT` 指定。
打开 <http://127.0.0.1:5186/so101>，自动加载记录与项目布局，并定位首个视频帧的物理时间0.04秒。

界面包括原录像、保存的物体三维姿态、双指接触力、关节角度，以及回合结果和阶段按钮。
点击“闭爪”“释放”“脱离”等阶段按钮，所有面板共用原生播放指针。
回合结果来自完整历史报告；阶段定位只改变观察时间。

新用户默认使用秒显示时间并折叠设置侧栏。既有用户设置保留。
窄屏布局入口为 <http://127.0.0.1:5186/so101-mobile>，保留录像、结果与阶段定位；它仍使用同一个原生播放器。
当前服务仅监听本机。窄屏测试使用浏览器设备仿真，CY部署与手机真机验收按后续阶段进行。
视频首帧对应物理 0.04 秒。在这之前显示缺帧状态符合原采集时序。

## 数据

使用 [转换工具](workbench-tools/README.md) 生成 MCAP，再执行独立读回验证。
保留原始 NPZ、视频、报告和源码摘要。转换器不会运行新仿真。
输出和环境保存在被 Git 忽略的 `workbench-tools/output/`。

三维视图显示原记录中的方块中心与姿态。原记录没有保存连杆变换，因此全臂动作通过同步录像观察。
全臂 FK、实时仿真与任务控制分别接入后再验收。

## 验证

预览服务运行后，执行项目浏览器验收：

```bash
node workbench-review-tests/run-review.cjs
```

测试使用独立 Chrome 上下文和上游 Playwright。它检查真实数据、阶段定位、播放、布局保存与重开，并记录网络请求。
浏览器只允许同源读取。实际页面、截图及失败步骤保存在被忽略的 `workbench-review-tests/output/`。
这里的通过表示记录查看功能通过，不改变原物理任务的验收结论。

## 修改边界

- 上游源码导入与本项目适配分别提交，便于追踪和更新。
- 新回合面板通过原 `Panel`、`MessagePipeline` 和 `seekPlayback` 接口注册。
- 预览服务复用上游已有 `serve-handler`，只提供明确允许的记录、布局和静态资源。
- Web 依赖与机器人运行环境分别安装。既有执行端继续拥有任务身份、取消和物理终态。
- 不提交 `node_modules`、构建产物、本地记录、缓存、环境或运行日志。
