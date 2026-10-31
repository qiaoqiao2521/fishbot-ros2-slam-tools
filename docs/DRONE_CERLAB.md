# CERLAB 网页任务与回放

现有 `/drone-station` 现在默认选择 CERLAB 作者栈。旧 PX4/MAVSDK 执行器仍可用
`DRONE_BACKEND=px4` 显式选择。切换执行器不会删除原任务；同一任务只由提交时的执行器处理。

## 使用

在常用入口 `http://127.0.0.1:5186/drone-station` 点击「载入 CERLAB 往返示例」，
再点击「起飞并执行仿真」。示例从原点起飞，到 (8,0,1)，返回后请求原生降落。
编辑航点 X/Y 后可另建任务；当前目标 Z 固定 1m，速度参数是作者配置值 1.5m/s。
固定场景来自作者 corridor_dynamic_9，后墙后移 0.25m 的独立副本。网页障碍编辑、
任意高度、验收参数及深度故障注入尚未接入；不支持的输入会明确失败，不会静默改值。

运行中刷新继续查询原任务 ID。取消按钮是「取消并请求返航降落」；仅停止后续程序，
向作者规划器请求原点，再调用 MAVROS AUTO.LAND。它不包含旧栈的历史安全轨迹回退，
也没有取得动态环境中安全取消的普遍保证。确认 landed_state=1 且 armed=false 后才结束。

历史任务选择器保留原记录。「历史回放」使用已有原生播放器，可 seek、倒退、播放；
回放不挂载飞行控制。记录包含真实 Gazebo 位姿、实际轨迹、作者世界静态几何和真值动态框。
IRIS 当前用位姿标记显示；不是 X500 模型。动态输入仍标为 `oracle_dynamic`。

## 运行与数据

```bash
cd /home/muqiao/worktrees/fishbot-workbench-code-rebuild-20261018/apps/fishbot-control-station
CERLAB_ROOT=/home/muqiao/worktrees/drone-cerlab-20261031 WORKBENCH_PORT=5186 node workbench-preview.cjs
```

服务复用 `createTaskRuntime`、`drone-live`、`writeRecording`；`createDroneRuntime` 根据 backend
选择已存在的执行脚本。每个 CERLAB 任务使用独立私网 Docker 容器，无宿主飞控端口。
CERLAB 的任务边界代码在实现仓 `cerlab/run_station.py`、`cerlab/station_task.py`：只负责
启动原生 launch、发布 `/move_base_simple/goal`、读取 Gazebo/MAVROS 状态、结束服务和记录。
规划器、检测器、跟踪控制器、飞行 FSM 均为原作者实现，不运行旧 MAVSDK 发送器。

任务目录沿用 `apps/fishbot-control-station/workbench-tools/output/drone-tasks/<UUID>/`，
包含 request/status/report、telemetry.jsonl、native flight.bag、ULog、日志及 flight.mcap。
主机适配器在原生录包关闭、报告写好和容器清理后唯一发布终态；Node 复用原 MCAP 写入器。
MCAP 存在时不会因历史查询再次生成，原始 bag/遥测仍保留。只启动网页不会自动起飞。

## 本轮验收

- `7c32d745-cacf-45b7-a033-5f419a7f5d02`：真实航点往返及落地通过；首次网页验收发现
  提前终态导致首 GET 缺 report，保留失败记录。改为主机清理后发布终态。
- `25a1b511-53a8-4ef5-a8b0-13b6b006f6c6`：网页新任务成功；8m/返程真值到点误差
  0.230141/0.095245m，均按 0.3m 并保持 1sim 秒判到达，落地/disarm 确认。
  空中刷新同 ID、零重复提交；原生 MCAP 定位、倒退、播放通过，零控制写入。
  MCAP 693帧/约25.5MiB，实际最高高度1.832602m；1m参考不等于精确高度跟踪。
- `c7c88e8f-026e-4ed1-8d26-d7a799391601`：网页空中取消；返航并落地/disarm 后 cancelled。
  实时三维实际轨迹可见；该 MCAP 回放同样通过且零控制写入。
- 3个任务边界单测、6个服务/双WebSocket/记录检查、43个Station文档检查通过。
  前端构建通过；真实任务和原生回放由项目 Playwright 验收，不以单测替代飞行。

QA 入口：`workbench-review-tests/drone-cerlab-browser.cjs`。默认会显式创建一次真实仿真任务。
设置 `CERLAB_REPLAY_TASK_ID=<UUID>` 仅验已有记录，不再飞行；`CERLAB_CANCEL=1` 验取消任务。
可用 `STATION_TEST_URL` 选择隔离端口，`CERLAB_QA_OUTPUT` 指定证据目录。失败后先查询原 ID，
不要盲目重跑新任务。取消在该限定场景通过，不代表完整动态安全控制闭环通过。

报告 `scope=functional_waypoints_and_observed_landing`、`safety_qualified=false`。
全程机体净空、hazard→safe链、真实深度、退化、高速和通用恢复尚未验收。
