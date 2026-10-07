# FishBot 家庭场景仿真闭环

把一份本地占用地图接入 MuJoCo，串联视觉巡检、具名地点找物、主动换位观察和低电回充。
**完整闭环已在隔离 MuJoCo 场景通过。** 2026-10-07 的 `run13` 同轮完成七项检查，独立复核通过。实车与真实住宅补全正确性尚未验收。

## 运行

在项目根执行。先准备已有的 Jazzy/MuJoCo 运行环境并构建 `fishbot_mujoco`，见 [仿真包说明](../workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/README.md)。系统 Python 需要 NumPy、Pillow、SciPy、PyYAML 和 Matplotlib。

```bash
bash tools/fishbot_mujoco.sh build
bash tools/fishbot_home.sh /path/to/private/room.yaml
```

输入必须是轴对齐的 `trinary` 地图 YAML，图像采用 8 位灰度，分辨率为 0.01–0.20 米。生成器保留原始图；若起点 `[0, 0, 0]` 不可用或找不到合适的补全区域，会停止并说明原因。

默认任务：

> 去工具架找红色盒子，看看门口指示灯，再去观察点找红色盒子，然后回来

三个地点依次检查红盒、指示灯、红盒。第三观察点复核红盒，结论由到点后的三帧 RGB 决定。
工具架包含受遮挡的初始视角；识别返回 `unknown` 时，执行器按限定策略选择另一观察位。

可指定新的本地输出目录和任务。源码仓库内的输出目录必须被 Git 忽略。

```bash
bash tools/fishbot_home.sh /path/to/private/room.yaml \
  workspaces/fishbot_mujoco_ws/.runs/home-demo \
  --task '去工具架找红色盒子，看看门口指示灯，再去观察点找红色盒子，然后回来' \
  --goal-timeout 120
```

输出目录必须尚不存在。省略时，脚本在 `workspaces/fishbot_mujoco_ws/.runs/` 下创建带时间戳的目录。入口固定使用 **domain 98、localhost discovery、空 static peers**。脚本退出时仅清理它创建的仿真进程组。

`--goal-timeout` 默认 120 秒，允许 1–180 秒；`--low-soc` 和 `--resume-soc` 默认分别为 `0.28`、`0.80`。
降低低电阈值可用于独立路线诊断，但没有实际回充和恢复任务证据的路线不满足完整场景验收。

只生成地图与场景，不启动 ROS：

```bash
/usr/bin/python3 tools/fishbot_home_scene.py \
  --map /path/to/private/room.yaml \
  --output workspaces/fishbot_mujoco_ws/.runs/home-fixture
```

`--source-map`、`--output-dir` 分别是上述参数的别名。`--padding` 控制未知外界的补全范围，默认 3 米。

## 输入来源与本地产物

生成器逐像素保留源图中已经观测的自由格和占用格。未知格及新增边界才允许按仿真假设补全。场景中的新工位和遮挡物只占用假设区域；充电标记贴在既有占用墙上。

| 产物 | 内容 |
| --- | --- |
| `fixture/map.yaml`、`map.pgm` | 完成后的 Nav2 地图 |
| `fixture/scene.xml` | 同一占用栅格划分出的 MuJoCo 墙体；复用原车动力学与相机 |
| `fixture/assumption_mask.pgm` | `0`：保留实测格；`127`：假设自由格；`255`：假设占用格 |
| `fixture/semantic.json` | 地点、观察位、巡检站、充电目标及其 staging pose |
| `fixture/provenance.json` | 源 YAML/图像哈希、原图偏移、足迹来源、墙体范围和产物哈希 |
| `fixture/home-nav2.yaml` | 本轮实际生成的 Nav2 配置，包括两个控制器、行为树和对接参数 |
| `fixture/overview.png` | 带坐标的实测/假设区域总览 |
| `runtime-source.json` | 启动时的 Git HEAD、domain、记录时间和关键源码/配置 SHA-256；包含未提交源码的实际内容哈希 |
| `report.json`、`index.html` | 任务结果、图文报告、轨迹、电量和动作事件 |
| `step-*-view-*-frame-*.png` | 每次观察保存的三张新 RGB 图像 |
| `diagnostics.json`、日志 | 实际代价地图、雷达、TF 与失败线索 |

地图、场景、来源绝对路径、照片和报告都属于本地数据，不随公共源码提交。`semantic.json` 的目标名称表示“要检查什么”，不表示“已经看到了什么”。

`runtime-source.json` 绑定启动时的源码快照；地图与机器人资产另由 `fixture/provenance.json` 绑定。
启动后应冻结源码，并结合生成的 `home-nav2.yaml` 复核本轮配置。源码哈希本身不能证明运行成功，也不覆盖所有已安装依赖。

## 1 / 2 / 3 验收契约

报告采用 `schema_version: 1`。以下三项已由同一轮实际仿真运动、RGB 和模拟充电反馈确认。

| 项目 | 通过所需证据 | `closed_loop_checks` 对应字段 |
| --- | --- | --- |
| 1. 视觉巡检 | 导航到点、停稳；每个观察位获取三张新 RGB；保存时间戳、位姿绑定、图像哈希及一致的像素分类 | `inspection_completed` |
| 2. 语义地点与主动重观测 | 具名指令解析到观察位；第一次因实体遮挡返回 `unknown`；机器人移动至另一视角后得到可靠结论 | `active_observation` |
| 3. 低电回充并继续任务 | 低电取消正在执行的导航；确认取消终态及停稳；执行 `DockRobot`；新鲜接触/充电反馈和 SOC 增长成立；执行 `UndockRobot`；继续未完成任务 | `low_battery_navigation_cancel`、`charging_and_undocking`、`resumed_task` |

`UndockRobot` 完成后先记录 `task_resume_ready`，表示具备恢复条件。
只有原先中断的地点和观察位再次导航成功，通过实际位姿、停稳和 TF 新鲜度检查后，才记录 `task_resumed`。
`recharge_cycles[].resume_target` 保存中断目标；`resumed_navigation` 通过 `step_id` 和 `attempt_index` 关联实际导航记录。
`resumed_task` 重新核对动作成功、目标一致和先后时间关系，不能由恢复事件单独置为通过。

共同要求：`returned_home` 和 `stopped` 均为 `true`。整轮只有在所有检查成立时才可保持 `overall_status: completed`。

走完路线但没有实际触发重观测或低电回充，会报告 `incomplete_scenario`。`failed`、`interrupted`、动作成功码、进程退出或单元测试通过，均不能替代整轮通过。

目前离线验证覆盖源图保留、假设标注、物理墙体/地图一致、输入边界、语义解析、像素识别和电池/接触逻辑。原生相机视角检查确认了遮挡视角 `unknown`、第二视角红盒可见及绿/红/空标牌。窄口差速转弯、AMCL 实际定位和闭环动作仍以运行报告为准。

## 当前配置与诊断记录

以下调整只用于本次完整静态仿真场景，不修改实测地图的占用格。

| 模块 | 当前配置与依据 |
| --- | --- |
| 全局代价地图 | 静态层与膨胀层。诊断发现，AMCL 投影后重复标记的 6 个占用格可封闭原图通道；该静态场景采用已生成的地图作为全局墙体来源。 |
| 局部代价地图 | 雷达体素层与膨胀层，分辨率 1 厘米。本轮源地图和全局地图仍为 5 厘米；Collision Monitor 保持启用。 |
| AMCL | `sigma_hit=0.05`、`max_beams=180`、`z_hit=0.95`、`z_rand=0.05`；位移与转角更新阈值均为 `0.02`。这些参数针对本次无噪声模拟雷达。 |
| 到点判定 | `xy_goal_tolerance=0.05` 米、`yaw_goal_tolerance=0.05` 弧度；执行器仍独立检查实际位姿及停稳。 |
| 默认导航控制器 | 保留基线 RPP，控制器 ID 为 `FollowPath`；巡检、默认导航和 DockRobot staging 共用 [家庭场景行为树](config/fishbot_home_tree.xml)。 |
| 有限回退 | 普通 `Fallback` 只在 RPP 返回 `104`（等待有效控制超时）、`105`（没有进展）、`106`（无有效控制）后选用 `NarrowPassage`。每次先清旧错误码；TF、路径、代价地图超时及动作响应超时不触发该回退。外层最多刷新一次代价地图再重试。 |
| MPPI 参数 | [当前配置](config/fishbot_home_controller.yaml) 使用 Rotation Shim、`temperature=0.1`、40 步与 `model_dt=0.05` 秒、1000 条候选；最大前进速度 `0.2 m/s`，`CostCritic.consider_footprint=true`。MPPI 接管当前目标剩余全程，下一目标重新从 RPP 开始。 |
| 末段转向 | `PathAngleCritic.threshold_to_consider=0.05` 米，使路径朝向评分持续到 Rotation Shim 接管终点朝向的范围。此前 0.4 米阈值留下了转向引导空档。 |
| 对接到站判定 | `docking_threshold=min(0.02, min(half_length, half_width)/2)` 米，默认由 6 厘米收紧至 2 厘米；到站后仍须独立验证接触条件和充电反馈。 |
| 末端碰撞检查 | `dock_collision_threshold=0.30` 米，匹配官方控制器的 0.25 米目标外推段；`use_collision_detection=true` 和 Collision Monitor 保持启用。 |

第 04 轮扫描及实际位姿的原生代价地图回放显示：仅使用扫描的 5 厘米局部栅格仍会判定足迹碰撞；改为 1 厘米后，四种栅格原点相位下均未出现该碰撞判定。因此，单独移除局部静态层不足以解决该问题。此证据说明局部光栅化的差异，整段物理通行仍须另行验收。

早期试验分别暴露了窄口转弯、接触朝向和全程 MPPI 行驶过慢的问题；当前配置因此采用 RPP 默认导航和有限 MPPI 回退。第 12 轮在返航末段停止；保存现场的原生碰撞检查显示转向与接近目标均有空间，随后修正了末段朝向评分范围。

第 13 轮耗时 **328.336 秒**，七项检查全部通过。12 张实际 RGB 覆盖四次观察：遮挡 `unknown`、换位后红色目标、绿色指示灯、另一具名观察点复核同一红色目标。低电取消后，模拟 SOC 从约 27.87% 升至 80.20%，离站并成功回到原定视角。最终物理真值距原点 **0.11063 米**、朝向误差 **0.17623 弧度**，已验证停稳。报告 SHA-256 为 `8e49b0560a0a97bc51b1039710a0863904730a45438179d6435c307074ff272c`；私有照片、地图与录像保留在本机。

204 项工具测试通过。独立禁充运行在模拟接触成立时保持零充电增量，Dock 返回 `906`，任务失败并停稳；该测试将低电阈值设为 `0.35` 以缩短触发时间。独立 1 秒导航期限测试确认取消终态 `5` 及实际停稳。失败记录不会被计入完整场景成功。

## 能力范围

- 语言采用受限中文语法，支持已登记地点、红色盒子和指示灯。未消费的指令文本会被拒绝。
- 视觉只识别合成蓝框黑底标牌内的颜色与红色矩形。看不到完整标牌时返回 `unknown`；不能推断整个房间没有目标。
- 相机来自 MuJoCo 原生 RGB 渲染。视觉分类不读取世界物体标签；真值仅用于独立运动/拍摄证据和仿真传感器模型。
- 回充使用模拟电池与接触条件。接触由真值位姿、速度、朝向与停留时间合成，未建模电极压力或真实电气连接。`/detected_dock_pose` 是真值派生的模拟定位信标，不是视觉检测结果。
- 默认电量为 36%，低电阈值 28%，恢复阈值 80%；放电和充电时间倍率分别为 45、288，并随状态报告。到达充电位不足以证明正在充电。
- SOC 到达 0 会触发独立的 `BatteryDepleted` 任务硬失败。每次发送动作前及运行中的健康检查均执行该门禁；返航、Dock 和 Undock 同样受约束，修改低电阈值不能绕过。随后取消当前动作并验证停稳；清理步骤保留执行能力。该门禁是仿真任务的软件停止，不代表真实电池断电或电机掉电模型。
- 全局代价地图在该完整静态场景使用静态层与膨胀层；局部雷达体素层和 Collision Monitor 继续工作。此配置不构成对动态实车环境的验收。
- 补全空间不代表未观测的真实住宅结构。几何连通与静态可见性不证明实际路径可通过，也不证明实车导航或真实充电。

## 离线检查与负向入口

```bash
/usr/bin/python3 -m unittest discover -s tools/tests -p 'test_home_*.py' -v
/usr/bin/python3 -m unittest discover -s tools/tests -p test_sim_power.py -v
```

行为树边界测试需要本机 Jazzy 的 BehaviorTree.CPP 和 `g++`。测试使用原生控制节点与假动作叶节点，检查错误码门禁、旧错误清理、取消传播及下一目标恢复 RPP；它不启动 ROS 节点。

禁充测试保留接触反馈，但禁止 SOC 增长；应留下失败及停车证据，不能被算作闭环成功。以下命令仍会启动隔离仿真：

```bash
FISHBOT_HOME_DISABLE_CHARGING=true \
  bash tools/fishbot_home.sh /path/to/private/room.yaml
```

模块入口：[场景](fishbot_home_scene.py)、[任务执行](fishbot_home_mission.py)、[语义与视觉](fishbot_home_semantics.py)、[电池与对接配置](fishbot_sim_power.py)、[对接字段说明](fishbot_home_docking.yaml)、[家庭场景 launch](fishbot_home.launch.py)。先前独立三站巡检见 [视觉巡检说明](../docs/VISUAL_INSPECTION.md)。
