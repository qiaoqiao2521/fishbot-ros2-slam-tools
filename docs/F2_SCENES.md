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
  --factory-config tools/config/factory_delivery/f2-workshop-line.json \
  --continuous-delivery tools/config/factory_delivery/continuous-ba-entities.json \
  --spawn -.9 -1.64 \
  --queued-ros-dispatch --terminal-stop-heartbeat \
  --output "$HOME/.local/share/fishbot/f2-workshop/scene"
```

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

`python3 -m unittest tools/tests/test_f2_scene_profiles.py -v` 的五项检查覆盖：配方路径与原订单/预算、visual与ideal显式边界、两布局真实几何差异，以及完整车体/托盘包围圆在新增arena中扫掠的保守净距。它不导入MuJoCo或ROS。

本机使用临时65MiB原生query环境做只读模型交接验证，不恢复GPU模型或整套规划环境。v3两个场景的原完整几何和原生停靠已通过，但Approach查询30秒超时，完整配送尚未通过。原机械臂抓放、载货运输、卸货和最终物理评分仍由独占云端回合确认，不能把几何/停靠组件计成F2配送完成。

两场景从明确的空载取货候车位开始；仓库为`[-.9,-1.68,0]`，车间为`[-.9,-1.64,0]`。这避免在卸货机械臂旁原地转向，不验证从A站远端空载进场。B→A载货路线、双指交接、卸货与原时限/碰撞评分仍须实际通过。v2原出生点重叠和车间进场失败继续保留。
