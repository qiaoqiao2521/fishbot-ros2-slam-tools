# fishbot_light_sim

这是保留的轻量二维仿真代码。它用用户指定的栅格地图生成 raycast 雷达，积分差速里程计，并支持虚拟障碍。它不模拟轮地接触；当前 MuJoCo 巡检入口见项目的 `docs/VISUAL_INSPECTION.md`。

2026-10-07 的公开整理只做离线边界测试，没有重跑本包的导航端到端测试，也没有操作实车。历史验证不能替代新环境验收。

## 构建与启动

在项目根目录安装 ROS 2 Jazzy 与 `package.xml` 声明的依赖。仅构建导航工作区所需包：

```bash
source .ros2_env jazzy
cd fishbot_nav
colcon build --symlink-install --packages-select fishbot_description fishbot_navigation2 fishbot_light_sim
source install/setup.bash
ros2 launch fishbot_light_sim light_sim.launch.py map:=/absolute/path/to/map.yaml
```

必须显式指定可读的地图 YAML。其 `image` 必须是可读的 P2/P5 PGM；相对图像路径按 YAML 所在目录解析。本包不附带房间地图，也不回退到本地 `current_map`。请用 `sim_config` 设置所选地图内的自由初始位置；旧配置中的位姿不保证适用于新地图。

默认 ROS 域为 **94**，发现范围限定为本机，并清空静态 peers。`ros_domain_id:=0` 会在创建仿真节点前失败。不要选择已有仿真实例占用的域。

直接运行节点时，`FISHBOT_LIGHT_SIM_DOMAIN_ID` 选择仿真域，默认仍为 94。节点会在初始化 ROS 前覆盖环境中的 `ROS_DOMAIN_ID`；所选仿真域必须为 1–232，禁止 0。

## 定位与交互

| 参数 | 默认 | 行为 |
| --- | --- | --- |
| `map` | 必填 | 用户明确指定的地图 YAML |
| `ros_domain_id` | 94 | 本机仿真域，拒绝 0 |
| `use_amcl` | false | false 时仿真发布 `map→odom`；true 时关闭该真值 TF，由 AMCL 发布 |
| `nav` | true | 启动 Nav2 |
| `rviz` | true | 启动 RViz |
| `sim_config` | `config/light_sim.yaml` | 初始位姿、雷达和噪声参数 |

`use_amcl` 会覆盖配置文件的 `ground_truth_localization`，保证启动器只选择一个 `map→odom` 发布者。AMCL 模式仍需提供初始定位并现场检查结果。

在同一个仿真域使用 RViz 的 “2D Nav Goal” 提交目标。用 “Publish Point” 添加虚拟障碍；用 “2D Pose Estimate” 重置仿真位姿。默认雷达为 719 点、7 Hz；参数与真实传感器相近不代表实车验收。

## 离线验证

从本包目录运行：

```bash
PYTHONPATH=. python3 -m unittest discover -s test -v
```

测试只检查域隔离、地图读取条件及定位所有权，不初始化 ROS，不发送命令。传感器噪声、真实控制延迟和实车避障仍需各自验证。
