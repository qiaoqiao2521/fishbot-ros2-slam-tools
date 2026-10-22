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

2026-10-22 aligned实跑check`fa4ebc93-8bfe-49ae-8fa1-f3153223d251`通过：源码`fbfdbbe`、143/9113，staging/default原Goal各status4，C++分别接收331/193份计划，独占对应不同controller_server GID；非零命令331/195条、物理位移23.43/24.42cm。最终真值XY2.548/2.629cm、yaw.02554/.01358rad，连续静止各.72源秒，禁碰0。51.241墙秒、参数/探针源码起止一致、原UUID与owned清理完成。证据`~/.cache/fishbot/factory-line-delivery-20261021/staging-aligned-fbfdbbe-20261022-a/`。它证明两阶段实际计算与实例切换，不是原固定朝向配送通过。

## 实测边界

可选姿态规划候选：`tools/cooperation_prepare.py --navigation-planner smac-hybrid`保留原入站GridBased/NavFn，增加运输HeadingAware/SmacPlannerHybrid；默认`navfn`沿用源配置。两阶段树的ComputePathToPose分别明确选择插件。候选使用DUBIN前进搜索、.20m最小转弯半径、72方向格和原生平滑，近似目标容差0。不改RPP、检查器、足迹、碰撞、地图、速度或原评分。生成manifest记录实际planner配置；短探针前后回读全部规划插件。此前全阶段Smac试验未整体通过，不能默认部署或称完整运输已修复。

可选定位候选：`--amcl-motion-model omni`仅选择已安装的`nav2_amcl::OmniMotionModel`，保持噪声参数、base_footprint、传感器输入、物理底盘与评分。默认`source`保持原配置。FishBot的foot原点比轮轴前移2cm；原生DifferentialMotionModel对不足1cm的逐次圆弧位移把rot1设0，离线零噪声半圈输入产生5.701cm均值误差。原生Omni模型对此输入、零偏置旋转与25cm直线均匹配几何期望。它描述参考点的侧向位移，不改变车轮可执行运动；运行仍使用原噪声，真值只作独立评分。

原生复现构建在`tools/cooperation_plan_witness/`，运行其中`cooperation_amcl_motion_probe`。该程序不初始化ROS或步进物理；其结果验证运动模型均值合同，不代表AMCL整滤波、完整运输或真机已通过。两份原始运动模型源码：[Differential](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_amcl/src/motion_model/differential_motion_model.cpp)、[Omni](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_amcl/src/motion_model/omni_motion_model.cpp)。

开放通道首轮两订单均通过原物理评分。v2 占用通道的两次原生 Nav2 均成功，独立物理评分只有 A 通过；B 的最终位置误差 0.043478m，超过原 0.04m，保持失败。各轮任务均未超 360 墙秒，owned 实例已清理。详见所属进度与私有原始报告。

open-v1 与 occupied-v2 之间补充了 teardown 诊断及保护单位快照，不宣称严格同源码性能对照。保护检查仅比较配置的 systemd 单位；这些历史单位当时均不存在，不能解释成旧 107/114 活进程持续运行。

2026-10-22原staged occupied direct两订单实跑`c15891fe-7f44-48de-93ab-935b4b98c050`：两单入站/精停靠成功，原双指抓取、释放、机械臂回位及连续交接/运输均通过；独立完整评分只有A通过。A用时266.791墙秒，最终XY.035936m/yaw.043753rad、连续停稳2.58源秒。B用时351.736墙秒，载货原UUID在约120墙秒取消5，最终XY.018539m/yaw1.573289rad，保持失败。总680.861墙秒、2start/1reset、同源码与原评分，owned清理完成；没有改变原4cm/.05rad、120/360/1000预算。此轮ideal/FishBot/planar，不是视觉或跨车型通过。

B末30墙秒的862个原物理样本全程hold=false、禁碰0，XY误差1.31–2.23cm、偏航1.30–1.79rad；601条命令线速度全0、角速度±.8rad/s并换向21次。HTTP所记map位姿跨15mm圈20次，它不是逐周期控制器分支回执；只将末端收敛列为已定位环节，不独占因果。原完整任务oracle的`native_goal_consumption_ack_claimed=false`保持，本节前面的DDS消费证据来自独立两段探针，不移花接木为这轮每个动作的消费ACK。via尚未执行，需先解决末端收敛，再冻结新同源对照。

## 2026-10-22 已验收的有限配置

原实体通道占用场景、FishBot＋平面雷达＋理想工位观测，采用同一程序完成B→A，原独立物理评分2/2。原始记录另行重算真值和原生UUID终态均吻合；同轮完整抓放、回位、留盘、运输与清理通过，原4cm/.05rad及120/360/1000秒门槛保持。

| 目的地 | 位置误差 | 偏航误差 | 单单耗时 | 连续停稳 |
| --- | --- | --- | --- | --- |
| B `(.7,-2,0)` | 3.259cm | .02692rad | 203.638s | 3.62源秒 |
| A `(0,-2,0)` | 2.531cm | .01719rad | 232.162s | 2.50源秒 |

prepare显式组合为`--amcl-motion-model omni --navigation-planner smac-hybrid --planner-minimum-turning-radius 0.10`；沿用原工位、阶段树及factory配置。factory run显式选择`--publication-mode asynchronous --order order-b --order order-a`。验收期间可用现成`systemd-inhibit --what=sleep --mode=block`包裹该运行命令，退出即释放；不修改全局电源策略。默认配置保持旧值，不能把FishBot参考点模型和半径直接套到其它底盘。

原始源码为b158b65、run5e1f02eb-d912-452d-9c76-0acc42d9b029、总479.706秒。guard触发0；每单physics仍缺2序号，完整记录不代表无损采样或生产稳定性。本轮不覆盖RGB、via或J100/3D雷达；历史失败、完整取证与下一入口见[本轮进度](../plans/factory-line-delivery-20261021/progress.md)。

## 发布阻塞配置实验

Smac的路径曲率约束可显式设置：prepare使用`--navigation-planner smac-hybrid --planner-minimum-turning-radius 0.10`。默认0.20保持旧行为；字段写入native planner参数和manifest说明。该值不修改车体或RPP执行限制，需按车型与具体场景做原生规划、实际路径跟踪及完整物理评分。F1的0.20/0.10对照结果见计划，不把更小半径解释成通用升级。

`run --publication-mode asynchronous`只为共同世界和任务桥两个Python子进程设置Fast DDS异步发布；默认`source`沿用原环境。Nav2和独立观察器不随此开关改变；源时间戳、QoS、时效阈值、速度与物理评分保持原值。直接启动同一launch时对应`publication_mode:=asynchronous`。

该配置复用[官方异步发送线程](https://github.com/ros2/rmw_fastrtps/tree/jazzy#change-publication-mode)，不新增转发节点。配置写入factory声明和实际启动命令；自定义XML可能覆盖该环境设置，需核原生配置。原生writer模式读回只证明设置生效，发布耗时和完整运输成绩仍以独立运行记录为准。同步模式下的旧时效失败保留。

## 来源

借用 [ARIAC 官方任务场景](https://pages.nist.gov/ARIAC_docs/en/main/pages/scenario.html)的订单、运输车、命名工位与独立评价语义。没有复制其资产、AGV锁定机制或评分。当前小场景不是完整工业尺度或真机验收。

## 同任务切换 J100＋3D 雷达

2026-10-23 实测结论：**组合未通过**。两次完整B均未到交付成功，A未执行；第二次原K与连续支撑通过，但原120秒载货导航超时。以下是实验复现入口，不是已验收的稳定配方。140项有效源码检查通过，所有owned实例已清理；原FishBot两单通过保持。

使用 `tools/config/cooperation_profiles/jackal_j100-lidar3d-transport.json`，原 F1 配置、订单 B→A 和原目的地保持。车型适配复用四轮滑移／有效轮距、原生 IMU＋EKF、完整足迹、托盘高度、工位交接和直线出站；16线通用理想雷达生成标准 PointCloud2，接入两 costmap 与 Collision Monitor。不是标定过的商业雷达，也不是热换活动实例。

本场景中，前向 Smac 的四个半径预检未找到 B 路径；NavFn 路径中有完整 J100 外廓相交。可显式选择原 Nav2 SmacPlannerHybrid 的 REEDS_SHEPP 模式，允许载货阶段倒车，保持原场地／目标和物理评分。原入站 StagingPath 仍为前进＋rotate-to-heading；载货 FollowPath 设置 allow_reversing=true、use_rotate_to_heading=false。默认 navfn 和旧 smac-hybrid/DUBIN 均保持。

```bash
FISHBOT_COOP_PYTHON=/home/muqiao/.cache/so101-colab/planning-venv/bin/python \
./fishbot.sh cooperation prepare \
  --so101-project /home/muqiao/dev/ros2/projects/so101 \
  --scene-profile tools/config/cooperation_profiles/jackal_j100-lidar3d-transport.json \
  --factory-config tools/config/factory_delivery/line-side-occupied.json \
  --navigation-planner smac-reeds-shepp --planner-minimum-turning-radius .60 \
  --output "$HOME/.cache/fishbot/factory-j100-example/scene"
```

随后使用上面的原 factory run，选择此 manifest，增加 `--publication-mode asynchronous --order order-b --order order-a`，输出到新的私有目录。J100 复用原 body-frame DriveOnHeading 出站，不传仅支持 FishBot 的 `--policy-config`。规划器配置、路径预检、原生 Goal 终态、完整物理评分分别报告，不能互相代替。临时进程级防休眠写法与上一节一致。

源码依据：[Nav2 1.3.13 RPP 参数合同](https://raw.githubusercontent.com/ros-navigation/navigation2/1.3.13/nav2_regulated_pure_pursuit_controller/src/parameter_handler.cpp)、[原生 SmacPlannerHybrid](https://raw.githubusercontent.com/ros-navigation/navigation2/1.3.13/nav2_smac_planner/src/smac_planner_hybrid.cpp)。当前完整运输结果回源本轮实施进度；预检成功不计运输成功。

## 配送站进场姿态与共用时间预算

2026-10-23 新增可选 `destinations[].approach_poses`，按顺序填写 map 坐标的 `{x,y,yaw}`，单位 m/rad。它描述如何进入配送站；`pose` 仍是原最终交付姿态。旧配置省略此字段时保持直达，不增加中间目标。

```json
{
  "id": "line_b",
  "pose": {"x": 0.7, "y": -2.0, "yaw": 0.0},
  "approach_poses": [{"x": 0.9, "y": -2.4, "yaw": 1.1}]
}
```

此例是具名**未通过候选**，不是可验收默认路线。完整输入见 [line-side-j100-approach-candidate.json](../tools/config/factory_delivery/line-side-j100-approach-candidate.json)。原 open/occupied 配置与父 FishBot 2/2 输入未改。使用原 `prepare --factory-config` 加载新配置；重建独立 scene，再运行原 factory adapter。只修改已生成 manifest 不会更新其配套输入。

执行顺序为：原 J100 `DriveOnHeading` 车体方向出站 → 可选进场点 → 原最终交付点。出站不能被 map 中转点替换。必需出站结束后，进场与交付共用 **120 墙秒**，含 Goal 接纳、规划、运动、每段原生成功、原 `.7` 源秒停稳以及 hold 后确认。单任务 360 秒、整轮 1000 秒保持；出站仍有原生 45 秒允许时间与原动作 owner。超时取消当前原 UUID，不派发后续段，不自动重发。

`/coop-api/start` 可选字段为 `delivery_approach_poses`。Workflow 将进场列表、最终点与请求共同落盘，重新连接按原任务对账；同 task ID 改进场点会明确拒绝。CLI `cooperation_workflow.py init --delivery-approach-poses JSON` 接收 batch UUID → 姿态列表；`--from-scene` 自动提取厂区进场配置。旧 ledger、旧请求与历史 oracle 捕获仍可读取。

`/coop-api/state` 的 `task.delivery_route` 显示当前段序号、进场/交付阶段、共用预算、单调墙钟已用/剩余时间及完成段数。验收报告新增 `expected_delivery_approach_poses`、`delivery_route_budget`；独立 ROS 状态仍需按顺序证明每个原生 UUID 成功，最终真值、同货物、连续支撑、停稳和清理评分不变。桥预发送元数据不是控制器消费 ACK。

`cooperation_delivery_route.path_time_budget()` 从实际路径采样估算线/角速下界、换向、加减速与段末停稳余量。线/角运动可重叠，不能只算长度/速度。估算假设按采样路径朝向跟踪、源/墙钟速率为 1；不是执行时间上界，不证明所有可行路线都超时，也不增加运行阻塞锁。

本轮仅规划预检使用独占 141/9111，15 组输入、25 个原生 `ComputePathToPose` 请求。两次实例共 5583 个物理样本全部 hold，Navigate/Dock/任务 start 均为零。每条路径用原完整实体几何和采样间距界检查。5 组整路几何通过，但时间估算均超预算：原 direct 下界 128.690 秒、含余量 142.090 秒；上述 B 进场候选下界 141.189 秒、含余量 155.989 秒。北侧若干目标被原生 costmap 以 lethal cost/206 拒绝；这些不计为可用路线。

因此**新增合同和预算实现完成，J100 完整 B→A 尚未通过**。本轮未重复抓放或声称运动验收；下一步须找到兼顾完整几何与原 120 秒的路径，再验证实际 RPP 跟踪，最后回到同轮两单完整 oracle。全部原生失败、路径、估算、静止和清理证据在 `~/.cache/fishbot/factory-line-delivery-20261021/j100-delivery-approach-20261023/`。原结果保留；双停稳余量的离线重算单列 `time-budget-recalculation.json`，没有重跑仿真或覆盖旧结果。
