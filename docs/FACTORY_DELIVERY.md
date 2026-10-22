# 厂区线边配送 F1

首片复用现有 MuJoCo、Nav2/DockRobot、SO101、Workflow 与独立物理 oracle。输入改为厂区场景和订单，控制与评分保持原实现。当前结果以[实施进度](../plans/factory-line-delivery-20261021/progress.md)为准；不要把配置可生成解释为运输通过。

## 场景与任务

配置在 `tools/config/factory_delivery/line-side-open.json` 和 `line-side-occupied.json`。位置单位 m，偏航 rad，采用当前 map/world 坐标。A=(0,-2,0)，B=(.7,-2,0)，取货点是原固定 SO101。`orders` 选择目的地；CLI 可用两个 `--order` 调整排列。

`channel.occupied` 控制真实箱体。当前 v2 箱体中心(.35,-2.10,.25)，完整边长(.12,.30,.50)；同一几何进入实体碰撞、传感器、机械臂查询和原 prepare 的两张地图。FishBot/J100×open/occupied 已有四个静态编译及原入站扫掠验证。v1 的旧箱体挡住声明的直线入站路径，原件保留为零运动预检失败；v2 留出入站路线，将占用放在第二目的地的运输通道。`centerline_m` 仅说明通道位置，不约束 Nav2 轨迹；实际路线仍由原 Nav2 规划。连通几何不等于 Nav2 路径或完整配送成功。

同一场景只有一个自由刚性货物。订单之间用原显式 reset 生成新回合并重新初始化它。交付是载货到指定停车点并停稳；不包含目的地下货、PLC 签收、多货物库存或整套 ARIAC 工厂。reset 也会把车复位，因此本切片可核对订单消费与目的地结果，尚不能据此宣称连续订单排序节省了行驶里程；这需要后续保留车位的补货回合。

## 首个运行入口

条件：在 FishBot 根目录操作，使用已有规划 Python，选择新的私有输出目录。运行前检查新 ROS 域与端口可用，保留 107/114 和旧网页。以下示例准备开放通道，换成 occupied 配置即可生成实体占用变体。

```bash
FISHBOT_COOP_PYTHON=/home/muqiao/.cache/so101-colab/planning-venv/bin/python \
./fishbot.sh cooperation prepare \
  --so101-project /home/muqiao/dev/ros2/projects/so101 \
  --factory-config tools/config/factory_delivery/line-side-open.json \
  --output "$HOME/.cache/fishbot/factory-example/scene"
```

可选：给 prepare 增加 `--scene-profile tools/config/cooperation_profiles/jackal_j100-lidar3d.json`，复用车型与传感器配置。profile 保留原任务类型，F1 订单独立决定本次作业数量；P8 的一／三批演示模板不会覆盖厂区订单。

先检查参数和订单。dry-run 不初始化 ROS、不发动作、不创建输出或账本。

```bash
python3 -B tools/cooperation_factory.py run \
  --manifest "$HOME/.cache/fishbot/factory-example/scene/scene-manifest.json" \
  --output "$HOME/.cache/fishbot/factory-example/run" --dry-run
```

实际评测启动一个独占实例，执行两单并清理其已知终态。domain141/API9111 为默认值，可显式指定其他空闲值。

```bash
FISHBOT_MUJOCO_DOMAIN_ID=141 XDG_RUNTIME_DIR=/run/user/1000 \
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
bash -c 'source tools/fishbot_mujoco_env.sh; exec /usr/bin/python3 -B tools/cooperation_factory.py run \
  --manifest "$HOME/.cache/fishbot/factory-example/scene/scene-manifest.json" \
  --output "$HOME/.cache/fishbot/factory-example/run" --candidate baseline'
```

运行后读回报告，不重新执行动作。

```bash
python3 -B tools/cooperation_factory.py report \
  --run "$HOME/.cache/fishbot/factory-example/run"
```

## 可改策略与评分边界

首片策略范围是订单排列、目的地选择和声明的通道配置。`--order order-b --order order-a` 修改排列；编辑目的地坐标或占用状态后重新 prepare。不得把本轮评价场景、物理参数或评分门槛一起改成更容易的条件。独立场景不做活动实例热替换。

`--candidate` 是显示标签，不加载其他代码。`loaded-code-start/end.json` 记录评测进程实际导入路径、Git HEAD/dirty 状态和选定运行源码文本，声明了观察范围；不是子进程完整 import 回执。后续接策略进化时须另验证候选实际加载，不能只改标签。

`execution` 记录是否执行、终态与清理；`task_verdict` 只摘要原独立 oracle，保留交接、抬升、释放、留盘、臂回位、同货物运输与最终位置/偏航/连续停稳。报告按原 task/episode/载货 Nav UUID 绑定目的地。保护介入单列，HTTP 200、Workflow succeeded 或退出码不能代替任务裁决。

单订单沿用360墙秒上限，整轮验收预算1000墙秒。阻塞调用、评分和清理可有限超出；超预算不得记整体通过。未知或仍运行的任务不因评测异常被当作已清理，不自动重发；报告保留原ID、owned PID和具体缺口，由owner接续。

## 实际路线策略入口

`--candidate`继续只作显示标签，`candidate_label_loads_code=false`。新增`--policy-config`才实际加载和调用策略：`direct`返回None，`declared_via`返回配置中的一个map中转点。示例配置在`tools/config/factory_policies/line-side-direct.json`与`line-side-lower-via.json`。后者是本参考场景的(0,-2.7,0)，不代表任意场地的通用安全路线。

```bash
# 在上述实际评测命令中增加一个参数；仍用新的独立输出目录
--policy-config tools/config/factory_policies/line-side-lower-via.json
```

本地策略可用以下JSON选择实际Python函数，module_path相对该配置文件解析。函数签名为`select_egress(context)`，返回None或`{x,y,yaw}`。context包含冻结订单、场景配置、原中转点与parameters；不提供运行真值作为控制输入。只接纳返回的中转点，原订单目标不由该返回值覆盖。

```json
{"schema":1,"entrypoint":{"module_path":"my_route.py","function":"select_egress"},"parameters":{}}
```

选择在launch前由原owned子进程助手执行一次，两订单共用该中转点。支持FishBot厂区场景；J100已有body-frame DriveOnHeading，当前接口明确不支持用map点替换它。未来支持J100时应在原直线出站之后接中转，不得只改参考坐标却声称路线已执行。

launch将同一显式manifest路径传给物理生产器和控制桥；独立sim省略--manifest时仍兼容world旁的scene-manifest.json。派生配置不会覆盖原prepared，也不绕过原身份校验。

`policy-receipt.json`保存实际模块/文件/函数、调用输入/配置/返回、阶段与异常、原SceneGeometry选点结果。原prepared manifest保持，运行使用私有`derived-manifest.json`；静态点检不证明整路可达。`native_route`和`expected_egress_pose`来自原oracle，实际试验要核对receipt返回值、派生manifest、原生中转目标与UUID，再看原物理评分。加载回执不是任务成功。

未知错误、非法点、碰撞或子进程超时保留失败，不回退成baseline通过。dry-run只描述请求，不import或调用目标策略；report仅回读。31项纯软件合同检查通过，包括真实自定义模块调用；原生occupied的direct/via同场景对照仍pending，不能宣称路线更优或已通过。订单全reset边界不变。

## 阶段控制探针

`tools/cooperation_staging_probe.py` 已从私有探针整理成项目入口，默认只做静态预检。用当前 staged manifest 时，起点(0,-2,0)，两段目标为(-.25,-2,0)和(-.50,-2,π/2)。每段都有25cm平移，避免同点Goal在控制计算之前直接返回。这个fixture只验证控制流程，不能替代原厂区订单或direct/via对照。

```bash
env PYTHONPATH="/usr/lib/python3/dist-packages:${PYTHONPATH:-}" \
  "$HOME/.cache/so101-colab/planning-venv/bin/python" -B \
  tools/cooperation_staging_probe.py \
  --manifest "$HOME/.cache/fishbot/factory-line-delivery-20261021/occupied-policy-staged-20261021/scene/scene-manifest.json" \
  --output "$HOME/.cache/fishbot/staging-probe/preflight" --preflight-only
```

预检使用完整原始碰撞体，检查声明的“原地转向→直线→目标转向”扫掠，并扣除空间采样间距。箱体世界AABB明确分离时使用保守距离下界，重叠时继续原生几何查询；不改物理碰撞选项。源图到目标的距离只用于选择低干扰fixture，不能将膨胀区内的软代价解释为碰撞。实际Nav2路径、定位和停车仍须另验。

先核对本机仿真实例和端口，再加载`/opt/ros/jazzy/setup.bash`。在上述命令中选择新输出目录，将`--preflight-only`替换为`--run-native`，并增加`--domain 143 --port 9113`。只运行一个实例和两个顺序Goal；默认每段60源秒、70墙秒，最终误差仍要求≤0.04m/0.05rad及连续0.7源秒停稳。2026-10-22固定朝向首轮已运行但未通过：staging原生成功、真值位置误差6.65cm；默认阶段末端转向超时并取消。两个阶段均保留实际路径、非零命令和物理轨迹，不能记配送通过。

报告逐阶段保存原UUID/终态、AMCL、物理姿态、计划和非零命令计数。复用已有`NavigationDiagnostics`有界保存`/plan`、`/received_global_plan`、`/lookahead_point`、`/local_costmap/costmap`，另留必要TF；源戳与接收时刻分列。超时在取消前先保存证据，缺少发布端GID时保留unknown，不把请求树路径或两个endpoint解释成具体RPP实例的消费回执。原UUID取消、fresh hold、连续静止及owned实例清理分别记录。每帧只留episode身份，完整manifest每轮保存一次。

为单独核验控制消费，可显式使用`--heading-mode aligned`：相同25cm西向平移，两目标均朝西，原`fixed`默认保留末端转向。新fixture不替代原配送，也不证明固定朝向已收敛。可选只读C++见证器使用`rclcpp::MessageInfo`读取真实DDS发布者GID，不发布命令，不接入真值；只将accepted Goal时间窗内的消息与原生发现的controller_server endpoint匹配。两阶段GID必须不同，且各自有非零控制与物理位移，才标记实例切换已观察。

```bash
source /opt/ros/jazzy/setup.bash
cmake -S tools/cooperation_plan_witness \
  -B "$HOME/.cache/fishbot/build/cooperation-plan-witness" -DCMAKE_BUILD_TYPE=Release
cmake --build "$HOME/.cache/fishbot/build/cooperation-plan-witness" -j2
# 在原生探针命令追加：
# --heading-mode aligned --plan-witness-bin "$HOME/.cache/fishbot/build/cooperation-plan-witness/cooperation_plan_witness"
```

见证器最多记录20000条计划，达到上限会明确报告overflow，不能再声称来源覆盖完整；原始JSONL与日志只留私有输出目录。来源归属与物理评分分列，终态失败不会因GID已知而改为通过。

## 实测边界

开放通道首轮两订单均通过原物理评分。v2 占用通道的两次原生 Nav2 均成功，独立物理评分只有 A 通过；B 的最终位置误差 0.043478m，超过原 0.04m，保持失败。各轮任务均未超 360 墙秒，owned 实例已清理。详见所属进度与私有原始报告。

open-v1 与 occupied-v2 之间补充了 teardown 诊断及保护单位快照，不宣称严格同源码性能对照。保护检查仅比较配置的 systemd 单位；这些历史单位当时均不存在，不能解释成旧 107/114 活进程持续运行。

## 来源

借用 [ARIAC 官方任务场景](https://pages.nist.gov/ARIAC_docs/en/main/pages/scenario.html)的订单、运输车、命名工位与独立评价语义。没有复制其资产、AGV锁定机制或评分。当前小场景不是完整工业尺度或真机验收。
