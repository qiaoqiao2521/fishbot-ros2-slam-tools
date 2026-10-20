# 成熟源码工作台

新底座使用完整 Lichtblick v1.29.1 源码。布局、播放器、时间线、3D、图像和曲线直接使用上游实现。
来源、精确版本和许可见 [UPSTREAM.md](workbench/UPSTREAM.md)。实施进度见 [SpecMesh](../../plans/workbench-code-rebuild-20261018/task_plan.md)。

当前支持历史回合查看，以及固定抓放模板的新仿真启动、查询和取消。

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

## 场景与程序编辑（2026-10-20）

首次从 <http://127.0.0.1:5186/so101-station> 导入桌面模板，或从 <http://127.0.0.1:5186/so101-station-mobile> 导入窄屏模板。保存后刷新当前页面，或打开 <http://127.0.0.1:5186/> 继续已有布局；再次打开模板入口会重新导入模板。

- 在对象树或俯视草图选择对象，编辑名称和以米计的 XYZ。
- 新建目标点、平移坐标系、物体或障碍。改变父坐标系时保持世界位置；改变坐标系位置时带动子节点。
- 在程序中选择目标，添加移动、张开、闭合、等待步骤，调整顺序。
- 点击“保存草稿”，使用 Lichtblick 原生布局保存。编辑可撤销/重做；导出 JSON 可备份和手工修改，再导入继续。
- 导入会报告并跳过坏条目，修复无效父节点；无法识别的文件不会覆盖当前草稿。删除目标保留程序步骤，并提示重新选择目标。

此入口支持工作站草稿编辑。坐标系仅支持平移，工具 TCP 尚未定义，虚线是步骤顺序，不是运动规划。右侧历史录像不随草稿改变。下方任务栏可以运行当前受支持的固定抓放模板。

来源：CY `re-packages/robodk-probe/README.md` M1–M4 的场景树、参考系、目标与指令组织；Lichtblick 原生 `Panel`、`saveConfig`、`LayoutManager.overwriteLayout`。未移植商业运动引擎或二进制。

局部测试：

```bash
./workbench-dev.sh test --runInBand packages/suite-base/src/panels/RobotStation/station.test.ts
node workbench-review-tests/station-editor.cjs
```

后者验证编辑、撤销重做、步骤排序、JSON往返、刷新恢复和390px编辑，不启动运动。

## 从编辑器运行新仿真

在场景面板下方点击“规划并运行仿真”。网页将当前草稿保存为该任务输入快照，调用 SO101 既有视觉定位、IK/OMPL 和抓放控制器；原报告决定成功。执行时可继续编辑下一份草稿，当前任务不受影响。

当前支持原始八步模板、取料中心 XY 各 ±10mm 内的方块移动，以及 50×56×130mm 的附加障碍。其他目标点、步骤顺序和自定义时长会给出明确错误，不会偷偷运行旧配置。现有固定障碍保留；释放复用 floor_yaw 和 28mm 指间高度，原碰撞与释放判据保持。

任务栏显示原 ID、阶段、原物理结果与本次录像。刷新仅查询任务；提交响应未知时点击“查询原任务”，不会自动再提交。点击“取消任务”请求现有执行循环协作停止，终态落盘后才显示已取消。历史回放右侧仍显示原记录，本次结果显示在任务栏。

预览服务通过 `SO101_ROOT` 和 `SO101_PYTHON` 指向已有项目与环境。默认使用本机 `~/dev/ros2/projects/so101` 及 `~/.cache/so101-graspgenx/upstream/.venv/bin/python`。可复现交付环境使用：

```bash
SO101_ROOT=/home/muqiao/dev/ros2/_delivery/so101-colab-20261001 \
WORKBENCH_RECORDINGS_DIR=/absolute/path/to/verified-recording \
node workbench-preview.cjs
```

任务产物保存在被忽略的 `workbench-tools/output/station-tasks/<id>/`，可通过 `SO101_TASKS_DIR` 修改。每个任务独立运行；同 ID 重复提交只查询已有任务，无每日限额和前序任务依赖。

接口：`GET /api/so101/runtime`、`GET/POST /api/so101/tasks`、`GET /api/so101/tasks/<id>`、`POST /api/so101/tasks/<id>/cancel`；录像与报告由同源产物链接读取。服务继续只监听回环地址，不接实机。

开发验证：`node --test workbench-review-tests/runtime.test.cjs`；启动服务后用 `STATION_TEST_URL=http://127.0.0.1:5186 node workbench-review-tests/station-execution.cjs` 运行一次真实抓放及取消验收。
