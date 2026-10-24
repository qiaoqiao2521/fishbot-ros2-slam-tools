# 多作业运输编排

## 入口与边界
运行 `tools/cooperation_workflow.py`。它只调用现有本地 `/coop-api`；不启动服务，不接管 ROS，不重启合作桥。`run` 有界轮询本流程，其他命令每次只做一个显式步骤。

作业数量由输入的非空 batch 列表决定，每批可选独立交付点。容量一的合成 machine-ready 工位与原完整刚性货物运输模板保持。物理场景只有一个自由货物；作业之间显式新 episode 会重新初始化该货物。本模块不提供同回合多货物库存、真实衣物抓取、洗衣机控制或任意技能图。

早期实现基线为 `aab0da45`。未配置目标时，`start` 仍只发送 `task_id/episode_id/issued_at`；配置后增加可选 `delivery_pose={x,y,yaw}`，单位为米/弧度、世界坐标。默认完整运输与原交付点保持。原 `reset.available` 已包含 worker 清理、原生动作终态、车臂货物静止、car_hold 与 guard 退出，薄层复用它。实际物理验收由 FishBot owner 在隔离实例完成，沿用独立 oracle；本模块 CPU fixtures 不证明机器人搬运成功。

## 有界运行

条件：FishBot owner 已建立**新的、空闲、ready 合成 episode**，且确认该实例由本流程独占。保留当前运行实例与旧账本。选择对应 HTTP 端口；默认 `9086`，仅允许 localhost HTTP。运行时 JSON 保存在私有 cache，不能入 Git。

先准备两个固定 batch UUID，然后初始化一次。下列 UUID 只是新流程的示例。

```bash
python3 -B tools/cooperation_workflow.py \
  --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" \
  --bridge http://127.0.0.1:9086 init \
  --batch 74a9049e-b2f0-4c4a-bf56-14539465c66a \
  --batch 2e640edc-40d9-4a51-b5fc-08a841b7a3ab
```

启动有界流程。ready 事件从另一个 CLI 到达后，`run` 自动完成派发、原 ID 查询、各非末作业成功后的重置及下一作业派发。每轮释放 ledger 锁，允许事件并发写入。自定义端口时，每条命令都带相同 `--bridge`。

```bash
python3 -B tools/cooperation_workflow.py \
  --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" \
  run --timeout 900 --poll 1
```

`timeout` 为 1–1800 秒；`poll` 为 0.1–10 秒。当前有界 HTTP 或持久化步骤可以有限超出退出时刻，但完成后不发新 POST。返回码：成功 `0`、fault/unknown 封锁 `2`、编排超时 `3`。超时只保存 runner 原因并退出编排器，保留原桥和原任务，不取消或重发动作。若预检后预算已耗尽，不创建派发意图；若同步意图后才耗尽，保留该 ID 为 unknown。`fault/unknown` 同样即时退出；显式恢复后可再次 `run`。

尚无任何派发意图的 ready job，预检断流或未就绪会以 `blocked_preflight` 返回 `2`。该 job 保留 `waiting_ready`，恢复反馈后可以再次 `run`；这属于有证据的未发送，不能类推到已经尝试 POST 的 unknown 动作。

准备 `ready-1.json`，内容如下。事件为合成输入；不要把示例解释为实际设备回执。

```json
{
  "event_id": "7eea093d-4e60-4505-9de8-198673f85655",
  "batch_id": "74a9049e-b2f0-4c4a-bf56-14539465c66a",
  "machine_id": "laundry-machine-1",
  "version": 1,
  "ready": true
}
```

载入 ready 事件。若 `run` 正在轮询，事件到达后自动推进。下面保留单步命令用于调试与恢复；运行 `run` 时不用同时手动 `dispatch/reset`。

```bash
python3 -B tools/cooperation_workflow.py --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" event --file ready-1.json
python3 -B tools/cooperation_workflow.py --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" dispatch
python3 -B tools/cooperation_workflow.py --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" tick
```

`tick` 只查询原动作 ID；任务运行期间可再次调用。`status` 只读本地账本，完全不请求桥。第一作业已知成功且 quiet 时进入 `waiting_reset`。显式提交回合重置，然后调用 `tick`，直到原 reset ID ACK、新 episode、旧作业 history 与 ready 一致。

```bash
python3 -B tools/cooperation_workflow.py --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" reset
python3 -B tools/cooperation_workflow.py --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" tick
```

后续事件使用新 `event_id`、对应 batch UUID 和连续递增 `version`。事件到达前不会派发。载入事件后，再显式 `dispatch`；`tick` 确认最后一批成功且 quiet 后，状态为 `succeeded`。成功账本保留并冻结，不因后续其他 episode 操作改写。

## 取消与恢复

`cancel` 先查原任务，仅对已知 running/canceling 的原 UUID 提交一次取消。回执丢失后，重复 `cancel` 只查询，不能再 POST。

```bash
python3 -B tools/cooperation_workflow.py --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" cancel
python3 -B tools/cooperation_workflow.py --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" tick
```

原任务已知 failed/canceled、原生动作结束且 quiet 后，`recover` 显式重置该合成 episode。旧失败 attempt、取消回执和 task ID 保留。ACK 确认后还需要新版本 ready；再次 `dispatch` 会生成新 UUID，属于同一逻辑 job 的新 attempt，不重放旧动作。

```bash
python3 -B tools/cooperation_workflow.py --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" recover
python3 -B tools/cooperation_workflow.py --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" tick
```

明确 start 拒绝也保留失败记录，显式恢复走同样门禁。reset 自身失败或拒绝保留原请求与原因，交 FishBot owner 审查；本模块不替 owner 再发一个重置。

## 不明结果与重启

每个 start/cancel/reset 都先同步落盘派发意图，再进行一次 POST。即使进程死在 POST 前，重启也不能证明未发送，只能保留未知。重启同一 CLI、同一 ledger、同一 bridge 端口，用 `tick` 原 ID 查询。不要删除账本、改变端口、重启原 bridge 或重新初始化来跳过门禁。

`GET /state` 不按 query task_id 过滤，所以薄层自己查 current/history 的精确 ID 与 episode。原桥只返回最近十条 history；找不到原 ID 即 `unknown`。同 ID 状态冲突、物理 source 不可用、episode 未经本流程 ACK 改变，也封锁推进。缺失记录不代表请求没有执行，`unknown` 不能 `dispatch/reset/recover/cancel`。

ready 事件绑定 event UUID、batch、machine 和连续 version。重复同 ID 同内容只读；同 ID 改内容、旧版本、跳版本、不同 batch、工位占用期间的新事件均拒绝。每次 reset 清除已消费 readiness，但保留事件历史与版本。

## 可选检查点与R2载货路线

manifest设置`checkpoint_directory`后，原bridge的`POST /coop-api/checkpoint`接纳`request_id`和可选`context`，沿原ROS收件箱交给Physics在周期边界捕获。按原请求ID读取`GET /coop-api/checkpoint/<request_id>`；捕获、后台落盘及回执分开计时。活动世界没有加载/回滚接口。

`tools/cooperation_checkpoint.prepare_ros_branch`从检查点准备新分支。只用父回合记录的map到base TF均值初始化AMCL，缺失时不借真值补齐；粒子、EKF/Nav2/DDS历史明确未恢复。新launch读取`restore_checkpoint`，分配新world/episode身份、保持车辆并清除旧移动命令。

显式`scope=route`仅允许合格R2载货分支，复用原加载参数事务、Nav2路线、货物保持和清理。Workflow在发包前持久保存该scope。默认请求仍为完整transport；route没有本回合装货，不继承原K完整抓放成绩。任务总预算仍为360秒，出站后配送路线独立保持120秒，不把初始化误计入这120秒。

factory增加`--scope route --select-order order-b`用于单个恢复切片；`--checkpoint-samples 5`在原清理确认后测量只读捕获RPC。标签不加载策略，原物理评分不变。当前R1四类通过、R2两次载货路线超时，完整验收状态见[计划进度](../plans/continuous-twin-regression-20261024/progress.md)。

## CPU 验收

```bash
python3 -B -m unittest discover -s tools/tests -p test_cooperation_workflow.py -v
```

fixtures 使用基线 `request_identity/reset_request_identity`，覆盖提交前后断点、lost receipts、同 UUID 取消/重启、版本乱序、缺 history、unknown、source=None 与 reset ACK 门禁。测试不启动 ROS、MuJoCo、浏览器、服务或 GPU。计划入口：[cooperation-workflow-20261014](../plans/cooperation-workflow-20261014/task_plan.md)。

## 三批与第二目的地配置

旧的重复 `--batch` 用法保留。新流程也可用 `--batches` 一次给出三个或更多 UUID，再用 `--delivery-poses` 读取 UUID 到目标的 JSON 映射。未列入映射的批次使用原默认交付点。每个目标在任务接纳时冻结；修改已派发任务同一 UUID 的目标会明确拒绝，恢复查询不会改写原目标或重放动作。

可直接复用[三批目的地示例](../tools/config/cooperation_delivery_poses.example.json)。以下文件记为 `delivery-poses.json`。UUID 仅作示例，实际运行使用新 UUID 和新账本路径：

```json
{
  "74a9049e-b2f0-4c4a-bf56-14539465c66a": {"x": 0, "y": -2, "yaw": 0},
  "2e640edc-40d9-4a51-b5fc-08a841b7a3ab": {"x": 0, "y": -2, "yaw": 0},
  "cd7eb7d0-194d-4aad-bad7-d30189d46463": {"x": 0.7, "y": -2, "yaw": 0}
}
```

```bash
python3 -B tools/cooperation_workflow.py \
  --ledger "$HOME/.cache/fishbot/three-jobs/workflow.json" \
  --bridge http://127.0.0.1:9106 init \
  --batches 74a9049e-b2f0-4c4a-bf56-14539465c66a \
            2e640edc-40d9-4a51-b5fc-08a841b7a3ab \
            cd7eb7d0-194d-4aad-bad7-d30189d46463 \
  --delivery-poses /absolute/path/delivery-poses.json
```

这是同一运输模板的参数化，不是更换工位、抓取物或机械臂的通用适配器。增加下一批或另一个已支持的目标只改新流程输入；现有DockRobot、抓放、载货Nav2、取消和静止清理继续复用。

显式目标先复用原始MuJoCo完整碰撞几何与足迹做静态预检。当前边界适配四面具名BOX围墙的合作场景；不是任意地图加载器，也不证明路径、到达或货物净位移达标。旧无目标请求不新增这项几何准入。原货物净位移≥0.5m业务要求保持，不能把任意近点都视为有效运输。

几何模型启动时预热，查询使用独立锁；预检后重新核对回合、UUID、期限和ready。耗时模型编译不占用物理反馈锁。原源龄与接收龄门槛保留。

## 独立目的地验收

每个 `full_started` 事件在POST之前记录 `expected_delivery_pose` 和原 `requested_delivery_pose`。默认目标也由原请求及manifest/default在派发前声明，不能到达后反推预期。接纳任务、载货Nav2发送目标和同任务history保留该目标。桥的目标回显是请求证据，不是控制器消费回执；原UUID活动与终态由独立ROS订阅确认。

原K抓放/同货物运输评分继续要求通过。新目标还需独立真值在0.04m/0.05rad内、车货停稳、货物完整留盘、机械臂回位，并连续保持1源秒。缺少目标声明或接纳证据不能跳过这项检查。完全没有任务目标字段的旧历史记录保持原历史评分，不补造新目的地通过。

## 实际仿真验收边界

2026-10-15，ec879ed冻结源在独占domain120/API9090完成一次移动取消与两次完整运输，逐episode原物理评分均通过。全过程保持同一bridge，只重启CLI；3start/1cancel/2reset，无未知重发。两次完整任务分别验证真实双指接触、抬升、释放、落稳、机械臂回位、携同一货物和最终停车。两次reset使用独立ROS回执源stamp，早于新episode采集和派发。

私有报告位于`~/.cache/fishbot/workflow/runtime-20261015-clock-afde67e5/`的result.json、逐episode score与root-closeout-readback.json。45项执行源/输入起止一致，17owned进程停止、9090关闭、原107/114保持。此前两轮失败原件保留。受控ROS证明默认回调组可阻塞原生Clock；专组路由保留标准TimeSource及QoS，仍不保证所有时序抖动消失。新增clock_update记录不是控制器消费回执。

本面板使用ideal工位观测与显式合成回合重置，不是新RGB留出、同回合多货物库存或真机验收。原视觉50短停靠＋6运输的11失败仍由[视觉计划](../plans/visual-docking-robustness-20261014/task_plan.md)接续。

### 2026-10-20：三批＋第二目的地

独占domain136/API9106的同一bridge/world完成三次完整运输，独立原K与新增目的地评分均通过。三批目标依次为A `(0,-2,0)`、A `(0,-2,0)`、B `(.7,-2,0)`。最终位置误差依次3.39cm、3.18cm、2.21cm，偏航误差.015640rad、.032529rad、.002298rad，目标内连续停稳2.46、2.54、2.42源秒；原门槛0.04m/0.05rad及1源秒保持。

实际3次start、2次显式episode reset、0次cancel。只重启编排CLI查询原任务，不重启桥；抓放、携同一货物、臂回位及原生载货导航继续复用。第三货物净位移2.48919m，载货Nav UUID `9dec77e0933143989f44a2778c7357a8` 由独立ROS订阅确认终态4。

私有证据根目录为`~/.cache/fishbot/workflow-reuse-20261020/`：c/result.json、c/workflow.json、逐case score与c/root-closeout-readback.json。A的启动环境失败、B的预检锁阻塞失败和各自清理回执保留。慢几何查询已移出反馈锁，原时龄门槛未放宽。206项定向检查通过；原前端只改运行配置即显示A/B，桌面/390px零写请求、零页面错误。实验进程及9106/5189已关闭，原5188保持。

这证明当前固定工位、刚性货物、ideal观测下的运输模板可通过输入增加批次与目标。它不证明不同物体/工位、多货物库存、新RGB留出或真实硬件。后续使用上面的新账本与目标映射入口；完整记录见[本轮进度](../plans/cooperation-workflow-20261014/progress.md)。

## 车型、传感器与任务组合

新场景由一个可编辑 JSON 选择车型、传感器和任务。沿用现有 MuJoCo 共同世界、Nav2 和 SO101 规划，不另建执行器。已有组合示例位于 [cooperation_profiles](../tools/config/cooperation_profiles/)；网页协同页也可下载同格式文件。

```json
{"schema":1,"vehicle":"jackal_j100","sensors":"lidar3d","task":"three_batch_transport"}
```

| 字段 | 当前选项 | 实际作用 |
|---|---|---|
| `vehicle` | `fishbot`、`jackal_j100` | 编译仿真底盘、轮控、里程计、完整足迹、托盘与工位交接位置 |
| `sensors` | `planar`、`lidar3d` | 二维激光；或保留二维定位并增加16线原生三维射线、标准点云与避障输入 |
| `task` | `transport`、`three_batch_transport` | 单批运输；或由原workflow执行三批A/A/B |

三维点云来自当前 MuJoCo 版本的 `mj_multiRay`，不是商业雷达的已标定模型。点云进入两个原生 costmap 和 Collision Monitor；AMCL仍使用 `/scan`。高度上界从编译后的整车碰撞几何、托盘和任意朝向刚性货物包络计算，保留原足迹padding。该界限只适用于当前平地、单件刚性货物和已配置附件；坡面、车身大幅侧倾或堆叠货物需要重新建包络。

J100 保留官方尺寸、惯量和真实轮距。转向使用当前 MuJoCo 3.3.7 平地模型离线标定的有效轮距系数4.5，命令与编码器使用同一值。它不是厂家或实车标定，也不使用在线真值反馈；方向、速度和载荷变化仍有残差。原生轮速伺服增益由8适配为32，原12Nm限幅、质量、摩擦和真实几何保持；低速开发面板改善小差速执行，仍不是精确逆动力学或完整运输证明。

J100 继续使用原生 RPP，`max_angular_accel=2`、`rotate_to_heading_angular_vel=0.4`。原生 `StoppedGoalChecker` 保留原位姿门槛，并要求平移/转动速度分别不超过0.01m/s、0.01rad/s。组合场景把检查器与 `FollowPath.stateful` 同时设为false，避免转向漂出位置容差后仍沿用先前XY达标状态；实际末端收敛仍由原生面板核对。控制器每周期从实测速度夹限，不能把过小的加速度参数当作能累积起转的命令。

完成实际交接、回臂并hold停稳后，J100通过原生服务临时应用载货参数：`max_accel=[.025,0,.05]`、`max_decel=[-.1,0,-.2]`、`max_velocity=[.03,0,.05]`、`min_velocity=[-.03,0,-.05]`。应用和恢复均核原请求ACK及实际读回；清理时恢复任务开始前的原值。空车入站和Dock继续原平滑参数。参数值是命令限制，不是物理加速度保证；原物理评分保持。同时在原生RPP把载货期 `desired_linear_vel`、`regulated_linear_scaling_min_speed`设为0.03m/s，`min_approach_linear_velocity`设为0.005m/s以保留近终点减速，`rotate_to_heading_angular_vel`设为0.05rad/s；对应 `FollowPath.*` DOUBLE通过同一参数事务机制核active、应用、读回并恢复。低速曲线应由控制器按低速生成，不能只在下游分别裁线速度和角速度。载货期同时将原PoseProgressChecker的位移/偏航进度分辨率设为0.005m/0.05rad，适配末段慢行；原10s进度期限、120墙秒Nav和360墙秒任务期限不变。两项与RPP四参数共用原ACK、读回和恢复事务；原最终位置/朝向/停稳评分不变。

J100出站复用原生 `DriveOnHeading`：沿当时车体方向以0.03m/s直行，ideal距离0.70m、vision距离0.65m，原生允许时间45源秒，再执行交付点导航。`egress_pose`仅为标称staging参考；实际请求是车体相对位移，不承诺精确抵达该世界坐标。出站与交付各核自己的UUID、顺序和原生终态。成功载货动作先连续0.7源秒满足原stopped判据再hold，让平滑器减速尾段完成；20ms短暂进入阈值不足以证明减速完成。异常与取消仍立即hold。

上述参数是当前待运输验收候选。kv32的六个载货阶跃中原50Hz保持谓词无失败，但一次500Hz底接触间断已保留；不把离线面板记成整任务成功。

当前横向安装布局在原10mm Nav2 padding后，对指定低侧障碍的标称净距为42mm。该值不是定位精度，也不是全方向三维余量；声明接近扫掠的整体最小余量仍约19.84mm，其他停车误差姿态不保证全部交接可达。托盘按刚性固定悬臂建模：支承块18mm、0.486kg，支撑重叠100×35mm、外伸85mm。结构挠曲、紧固件和真实载荷强度尚未验证。

导航点云 `/sensors/lidar3d/points` 只过滤当前完整凸包与未膨胀载货高度内的自体首回波。`/sensors/lidar3d/points_raw` 保留原始对照，元数据记录同源stamp/scene/episode/sequence及移除数量。该过滤不穿透被移除物体重新射线，不读取任务阶段、货物身份或接触状态；车外和包络外障碍继续保留。

条件：已配置现有 `FISHBOT_COOP_PYTHON`，并选择尚不存在的输出目录。先生成独立场景：

```bash
tools/fishbot_cooperation.sh prepare \
  --so101-project /home/muqiao/dev/ros2/projects/so101 \
  --scene-profile tools/config/cooperation_profiles/jackal_j100-lidar3d.json \
  --output "$HOME/.cache/fishbot/new-j100-scene"
```

确认独立域和端口空闲后，用现有 `run` 启动该manifest。例中的137/9107只表示一组实验配置，不保证当前空闲：

```bash
FISHBOT_COOP_DOMAIN=137 tools/fishbot_cooperation.sh run \
  manifest:="$HOME/.cache/fishbot/new-j100-scene/scene-manifest.json" \
  output:="$HOME/.cache/fishbot/new-j100-runtime" port:=9107
```

等待原桥ready后，由新manifest初始化新账本。三批模板会生成三个新batch UUID，目的地依次为manifest的A、A、A向世界X偏移0.7米的B；显式ready事件和查询/重置流程仍用本文原入口。

```bash
python3 -B tools/cooperation_workflow.py \
  --bridge http://127.0.0.1:9107 \
  --ledger "$HOME/.cache/fishbot/new-j100-workflow/workflow.json" \
  init --from-scene "$HOME/.cache/fishbot/new-j100-scene/scene-manifest.json"
```

网页的“当前运行组合”来自实际manifest；配置草稿只导出新场景输入。选择草稿不会替换活动世界。实际运行三批模板时，原workflow负责派发和回合重置，网页不重复启动这两个动作。单批入口保留原有任务操作。

组合实现和实际验收分开记录。最终四组合运输面板的状态、旧失败和剩余限制以[当前P8进度](../plans/cooperation-workflow-20261014/progress.md#p8-current)为准；不把导出配置、topic存在或网页状态视为完整运输通过。


### 入站与交付的XY状态候选（仅软件验证）
新prepare为入站提供独立staging行为树，使用原RPP类的StagingPath和原目标检查器的staging_goal_checker两个配置实例；只有stateful改为true，其余速度/容差/碰撞/进度参数复制原值。原FollowPath和general_goal_checker保持交付配置false。入站完成后仍须原DockRobot与物理停稳，锁住过渡XY不能替代工位精度验收。

bridge仅在显式staging=True的非载货入站请求使用manifest.staging_navigation_behavior_tree；载货请求留空以使用原默认交付树，旧manifest没有新字段也留默认。native_actions.goal_behavior_tree记录实际请求字符串，属于桥侧冻结输入，不是控制器消费回执。阶段树只能在前一原生动作已终态后切换，原owner/取消/cleanup和120/360期限保持。

该候选仅通过纯软件XML、配置隔离和请求路由检查，尚未新prepare/native验证。旧fixed direct已保留为入站失败，不自动热换或重跑；下一次须新共享prepare与明确资源窗口。
