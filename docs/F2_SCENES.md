# 两个可复用配送场景

`tools/config/factory_delivery/f2-scenes.json` 是两组可编辑配方。它只引用已有的 prepare、车型、传感器、实体和订单接口，不创建第二任务执行器。新增 arena 是真正不同的静态布局；取货和卸货工位保留已验几何，便于核对新场景下的复用。

| 配方 | 新布局 | 复用配置 |
| --- | --- | --- |
| `f2-wide-warehouse` | 10×9m围护、四列货架、北库存台、南发货台 | J100＋3D雷达、RGB AprilTag停靠、GraspGen-X可见点云抓放、三SO101、连续B→A |
| `f2-workshop-line` | 8×7.8m围护、机器岛、检验台、线体、工具库及交叉通道 | 麦轮＋3D雷达、显式ideal工位观测、原三SO101、B→A |

新增物体全部是仓库原生MJCF box、plane、灯光和小型checker材质，不增加外部网格。实体障碍、地图与传感器射线继续来自同一 arena；不是只加网页装饰。货架/机器是明确的静态实体近似，不包含制造设备运动或真实材质感知模型。

## 准备宽通道仓库

条件：使用已恢复的 SO101/规划环境。在 FishBot 根执行，选择新输出目录。云端已生成的预训练模型配置替代示例路径；其Python、权重与夹爪描述必须仍指向实际安装。

```bash
./fishbot.sh cooperation prepare \
  --so101-project /home/muqiao/dev/ros2/projects/so101 \
  --scene-profile tools/config/factory_delivery/j100-wide-profile.json \
  --arena-xml tools/config/factory_delivery/f2-wide-warehouse-arena.xml \
  --factory-config tools/config/factory_delivery/f2-wide-warehouse.json \
  --continuous-delivery tools/config/factory_delivery/j100-wide-entities.json \
  --spawn -.9 -1.68 \
  --perception-config tools/config/perception/apriltag-station.example.json \
  --pretrained-grasp-config tools/config/perception/pretrained-grasp.example.json \
  --lidar3d-config tools/config/cooperation_profiles/mid360-sensor.json \
  --camera-rgbd --queued-ros-dispatch --terminal-stop-heartbeat \
  --output "$HOME/.local/share/fishbot/f2-warehouse/scene"
```

该命令不替代已验J100控制器/原生overlay配置。云端原视觉入口应继续执行原 `f1_candidate.py` 配置步骤，并保持原控制、加减速、碰撞、30秒抓取接近期限及物理评分。新 arena 的静态准备通过，也不能宣称新的完整配送通过。

## 准备车间线边

```bash
./fishbot.sh cooperation prepare \
  --so101-project /home/muqiao/dev/ros2/projects/so101 \
  --scene-profile tools/config/cooperation_profiles/robot_base_mecanum-lidar3d-transport.json \
  --arena-xml tools/config/factory_delivery/f2-workshop-line-arena.xml \
  --factory-config tools/config/factory_delivery/f2-workshop-line-coaxial.json \
  --continuous-delivery tools/config/factory_delivery/f2-workshop-line-coaxial-entities.json \
  --spawn -.9 -1.64 --staging-reversing \
  --queued-ros-dispatch --terminal-stop-heartbeat \
  --output "$HOME/.local/share/fishbot/f2-workshop/scene"
```

此版本把两个卸货位及其实际工位/地图同步对齐原`y=-1.64`车道，并使用已有RPP倒车进站；原`y=-2`文件保留为失败对照。它不是只改网页目标，也不放宽车体、碰撞或时间预算。

这里没有启用视觉工位观测或预训练抓取。RGB或深度可作为只读取证额外开启，但不能据相机存在把ideal结果解释为视觉控制。原麦轮控制/直线出站及评分继续复用；不要给麦轮套J100候选控制器文件。

## 原任务入口

准备后，先调用既有完整几何预检。选定独占域/端口后由原Factory启动；每场景一个B→A，成功后即收口，不展开矩阵。

```bash
python3 tools/cooperation_factory.py run \
  --manifest "$scene_out/scene-manifest.json" \
  --output "$run_out" --domain "$domain" --port "$port" \
  --publication-mode asynchronous \
  --continuous-deliveries tools/config/factory_delivery/continuous-ba-orders.json \
  --order order-b --order order-a --scope transport
```

所有卸货实体配置继续保留 `load_and_delivery=360s`、`unload=180s`。载货路线仍用原120墙秒预算。声明的 `static_route_reference` 只用于新增arena障碍的离线几何预检，不是Nav2必须执行的路线，也不会在运行时注入真值目标。

## 当前验证范围

`python3 -m unittest tools/tests/test_f2_scene_profiles.py -v` 的六项检查覆盖：配方路径与原订单/预算、visual与ideal显式边界、两布局真实几何差异，同轴相对工位/预算保持，以及完整车体/托盘包围圆在新增arena中扫掠的保守净距。它不导入MuJoCo或ROS。

早期只读阶段曾使用临时65MiB原生query环境；以下v5/v6状态作为历史边界保留，随后本机完整回合结果见本节末尾。前五次原生失败均保留。v5仓库已有实际312点/408候选及4.577秒模型请求取证，后续OMPL仍30秒超时；车间K抓放/运输分项通过，但末偏航约-.410rad未达标，B未完成。当前同轴布局与保守查询优化进入第六轮，完整配送尚待原记录确认。原机械臂抓放、载货运输、卸货和最终物理评分仍由独占云端回合确认，不能把几何/停靠组件计成F2配送完成。

两场景从明确的空载取货候车位开始；仓库为`[-.9,-1.68,0]`，车间为`[-.9,-1.64,0]`。这避免在卸货机械臂旁原地转向，不验证从A站远端空载进场。B→A载货路线、双指交接、卸货与原时限/碰撞评分仍须实际通过。v2原出生点重叠和车间进场失败继续保留。


### 2026-11-06 本机实际边界与返站候选

仓库run132c3ad1的B完整原评分通过；A返站失败，整轮仍false。B装/卸所选51/49均为OBB几何候选，官方扩散模型同时实际推理但不能据此称所选抓取来自扩散网络。完整两段视觉证据和原失败均在/results。

返站仍用GridBased/NavFn，RPP碰撞拒绝后Spin恢复导致托盘触台沿。实验配置器增加显式`--staging-planner HeadingAware`，同时绑定原树的所有规划引用，复用已有SmacLattice；默认不改原树。原控制器、恢复、碰撞、速度和预算不变。此参数存在和单测通过不代表路线或完整配送已通过，原生结果以当前progress为准。

车间单次源龄.36秒失败。`dedicated_station_receiver: true`是默认关闭的实验manifest选项，给原工位pose/detection/quality独立标准ROS接收执行器。原exact同步队列5、QoS5、来源和时龄阈值保持。入口receipt仅诊断，不作为接纳或控制器消费回执，也不据单次成功宣称长期时钟空档已消除。


新车间 `mounted_load_fixture` 只在 coaxial 配方启用：保留原挡块尺寸，将其固定在 local(.05,.15,.065)，增加从地面到原挡块底部的真实支架。原默认、两个卸货工位与货物均保持，生成后的几何和地图必须一致。两货物关键抓放段、47.341mm障碍余量和25.652mm车体扫掠是静态候选证据；完整B→A仍看原Factory结果。Clock/physics恢复交错读取已改为在原接收预算内等待真实Clock，再按原门槛验收，绝不替换时间源或给旧帧改stamp。


车间卸货候选复用entities的 `pickup_xy_m=[.24,.04]`：卸货臂yaw为pi/2，这使整套工位向世界-X移动.10m，保留dock、局部抓放/货架与碰撞尺寸。不是增大机械臂工作空间或改IK容差。原失败快照和两站静态预测均过原检查，完整任务另验。仓库D同世界B→A已实跑通过（source08b0cb2），传感器/视觉/原生返程与独立评分详见当前progress。


### 车间仅规划候选的恢复入口

先按上方原Mec配方准备场景，再显式选择既有原生规划器：

```bash
python3 experiments/kaggle/f1_candidate.py "$scene_out/scene-manifest.json" \
  --planner-only --staging-planner HeadingAware
```

该模式绑定主任务与返站树的原生规划引用。它不套用J100运输调参，保留Mec控制器、平滑器、两套costmap、车体与速度配置。原生只规划已验证中线与完整车体净距；这不替代原Factory完整B→A评分。完整回合状态见当前progress，失败仍保留。


### 本轮最终原生配送结果

仓库D `ecfa94dd-0570-4691-b5f2-542e923f1a7f`：J100＋MID式扫描＋RGB-D混合抓取，同世界B→A、零reset/取消，两个原命名货物完整评分通过。四个实际所选均为OBB，官方扩散推理与所选来源分开；完整装/卸链、回放和源输入可在 `/results` 查看。

车间F `f5791fca-7354-4db3-bf35-7c80ff9e9497`：麦轮＋原16线＋ideal工位观测，同世界B→A、零reset/取消，两个原命名货物完整评分通过。B/A路线23.902/20.313墙秒、末XY21.118/21.708mm；原RPP、平滑器、速度、接触/碰撞和时间门槛保持。原生进程/端口和保护快照清理核对通过。两轮共四单的原Oracle直接gzip独立重算逐项一致。

第二单legacy primary K仍false，保留诊断；按cargo_2身份的原命名K、实体卸货和完整评分true。不把同一套输入的重复评分称为改进，也不外推真实硬件。恢复与原件见[归档入口](VISUAL_DELIVERY_ARCHIVE.md)。
