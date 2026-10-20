# 成熟源码工作台

新底座使用完整 Lichtblick v1.29.1 源码。布局、播放器、时间线、3D、图像和曲线直接使用上游实现。
来源、精确版本和许可见 [UPSTREAM.md](workbench/UPSTREAM.md)。实施进度见 [SpecMesh](../../plans/workbench-code-rebuild-20261018/task_plan.md)。

当前支持历史回合查看、场景编辑预览，以及固定抓放模板的新仿真、实时全臂三维、查询和取消。

## 启动

条件：Node >=20，已安装系统 Chrome。历史回放另需经过核验的 MCAP；新仿真和编辑预览另需现有 SO101 Python 环境。
在本目录执行：

```bash
./workbench-dev.sh install --immutable
./workbench-dev.sh web:build:prod
WORKBENCH_RECORDINGS_DIR=/absolute/path/to/verified-recording node workbench-preview.cjs
```

历史回放使用的 `WORKBENCH_RECORDINGS_DIR` 必须包含 `so101.mcap`。默认只监听 `127.0.0.1:5186`，端口可通过 `WORKBENCH_PORT` 指定。
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
历史记录仍只显示已有字段。当前任务的完整机械臂三维使用下述实时接口。

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

此入口支持工作站草稿编辑。坐标系仅支持平移，工具 TCP 尚未定义，虚线是步骤顺序，不是运动规划。右侧原生 3D 可切换编辑预览和当前任务。下方任务栏可以运行当前受支持的固定抓放模板。

来源：CY `re-packages/robodk-probe/README.md` M1–M4 的场景树、参考系、目标与指令组织；Lichtblick 原生 `Panel`、`saveConfig`、`LayoutManager.overwriteLayout`。未移植商业运动引擎或二进制。

局部测试：

```bash
./workbench-dev.sh test --runInBand packages/suite-base/src/panels/RobotStation/station.test.ts
node workbench-review-tests/station-editor.cjs
```

后者验证编辑、撤销重做、步骤排序、JSON往返、刷新恢复和390px编辑，不启动运动。

## 从编辑器运行新仿真

在场景面板下方点击“规划并运行仿真”。网页将当前草稿保存为该任务输入快照，调用 SO101 既有视觉定位、IK/OMPL 和抓放控制器；原报告决定成功。执行时可继续编辑下一份草稿，当前任务不受影响。

当前支持八步搬运任务、取料中心 XY 各 ±10mm 内的方块移动、同高度同尺寸蓝盘的放置 XY，以及 50×56×130mm 的附加障碍。蓝盘需位于台面，可达性与碰撞逐任务规划；其他目标偏移、步骤顺序和自定义时长会给出明确错误，不会偷偷运行旧配置。现有固定障碍保留；释放复用 floor_yaw 和 28mm 指间高度，原碰撞与释放判据保持。

任务栏显示原 ID、阶段、原物理结果与本次录像。刷新仅查询任务；提交响应未知时点击“查询原任务”，不会自动再提交。点击“取消任务”请求现有执行循环协作停止，终态落盘后才显示已取消。运行自动切到本次任务三维；完成或取消后保留最后实际姿态，本次录像与报告仍在任务栏。历史回放通过独立入口打开。

预览服务通过 `SO101_ROOT` 和 `SO101_PYTHON` 指向已有项目与环境。默认使用本机 `~/dev/ros2/projects/so101` 及 `~/.cache/so101-graspgenx/upstream/.venv/bin/python`。可复现交付环境使用：

```bash
SO101_ROOT=/home/muqiao/dev/ros2/_delivery/so101-colab-20261001 \
WORKBENCH_RECORDINGS_DIR=/absolute/path/to/verified-recording \
node workbench-preview.cjs
```

任务产物保存在被忽略的 `workbench-tools/output/station-tasks/<id>/`，可通过 `SO101_TASKS_DIR` 修改。每个任务独立运行；同 ID 重复提交只查询已有任务，无每日限额和前序任务依赖。

接口：`GET /api/so101/runtime`、`GET/POST /api/so101/tasks`、`GET /api/so101/tasks/<id>`、`POST /api/so101/tasks/<id>/cancel`；录像与报告由同源产物链接读取。服务继续只监听回环地址，不接实机。

开发验证：`node --test workbench-review-tests/runtime.test.cjs`；启动服务后用 `STATION_TEST_URL=http://127.0.0.1:5186 node workbench-review-tests/station-execution.cjs` 运行一次真实抓放及取消验收。

## 当前任务实时三维

`/so101-station` 使用 Lichtblick 原生 Foxglove WebSocket 数据源和 3D 面板。点击“编辑预览”查看当前草稿；修改物体或障碍约 250ms 后提交几何预览。预览调用 MuJoCo `mj_forward`，不运行控制器、不推进物理。

点击“规划并运行仿真”后，画面自动跟随该任务。13 个原始 STL 组成 17 个机械臂/夹爪网格实例，桌面、料盘、障碍和自由物块均取自 MuJoCo 场景；旋转和位置由实际 `MjData` 输出，不用脚本把物体附着到夹爪。

运行中改草稿不会替换任务画面。点击“当前任务”可从预览返回所选任务。终态在视频编码前强制发布实际末态；已取消或已结束的任务保持该姿态。缺少 scene 的旧记录显示空场景，不用最后关节值虚构连杆姿态。

实时发布约 10Hz，阶段变化和终态立即更新；接触力与关节曲线只发布执行器已有真实字段。显示频率与物理控制周期不同，本版不声明完整闭环 50Hz。手机模板使用上下排列的原生 3D 与编辑面板。

接口：`GET/POST /api/so101/scene-mode`、`POST /api/so101/preview`、`GET /api/so101/scene-state`、`GET/HEAD /api/so101/meshes/<原始STL>`；WebSocket 为 `/api/so101/scene`。频道为 `/so101/live/scene`、`joints`、`contact` 和 `status`；场景使用标准 `foxglove.SceneUpdate` schema。

```bash
node --test workbench-review-tests/runtime.test.cjs workbench-review-tests/live.test.cjs
STATION_TEST_URL=http://127.0.0.1:5186 node workbench-review-tests/station-live.cjs
```

后者会真实运行一轮完整抓放及另一轮协作取消，检查编辑预览、运行隔离、刷新、实际末态和手机布局；产物继续被 Git 忽略。固定模板以外的程序、旋转参考系、工具 TCP、CY部署和手机真机仍待后续接入及验收。

## 复制任务并修改放置位置

1. 点击“复制为新任务”。有当前任务时，复制其提交快照；否则复制当前草稿。原任务及报告保持。
2. 修改自动选中的“放料坐标系”X/Y。蓝盘、释放点和脱离点一起移动；本轮保持原盘高、盘尺寸和八步程序。
3. 点击“保存草稿”。刷新或JSON导出/导入可继续编辑；复制和保存不会启动运动，也不会重新挂回旧结果。
4. 点击“规划并运行仿真”。系统创建新任务ID，对新位置重新规划；原物理报告判定抓放、落稳、脱离与回位。

运行或结果未确认时，复制按钮禁用，原取消/查询入口保持。一个同类新目标只修改任务数据；尚不支持自由组合任意技能、更换物体形状或改变支撑台面高度。新位置无法规划时明确失败，绝不改跑旧蓝盘。

开发验证：`node workbench-review-tests/station-task-drafts.cjs`检查无运动编辑与390px；`node workbench-review-tests/station-task-goals.cjs`会实际执行默认任务和一个改目标副本。后者要求新盘内真实落稳、脱离与回位，不能只凭控制器done计成功。
