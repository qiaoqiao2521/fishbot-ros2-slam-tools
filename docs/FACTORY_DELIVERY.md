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

## 实测边界

开放通道首轮两订单均通过原物理评分。v2 占用通道的两次原生 Nav2 均成功，独立物理评分只有 A 通过；B 的最终位置误差 0.043478m，超过原 0.04m，保持失败。各轮任务均未超 360 墙秒，owned 实例已清理。详见所属进度与私有原始报告。

open-v1 与 occupied-v2 之间补充了 teardown 诊断及保护单位快照，不宣称严格同源码性能对照。保护检查仅比较配置的 systemd 单位；这些历史单位当时均不存在，不能解释成旧 107/114 活进程持续运行。

## 来源

借用 [ARIAC 官方任务场景](https://pages.nist.gov/ARIAC_docs/en/main/pages/scenario.html)的订单、运输车、命名工位与独立评价语义。没有复制其资产、AGV锁定机制或评分。当前小场景不是完整工业尺度或真机验收。
