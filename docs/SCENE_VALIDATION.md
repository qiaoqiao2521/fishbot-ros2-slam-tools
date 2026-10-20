# 场景、三维雷达与路线验证

本入口验证房间、门口、走廊中的导航往返。它复用MuJoCo、Nav2和已有mission owner，不新增任务调度服务。默认场景有明确尺寸，但属于合成参考，不代表当前住宅实测，也不包含货物装卸或收货签收。

## 运行

先构建对应工作区中的fishbot_mujoco包。不要在项目根统一构建。

```bash
source tools/fishbot_mujoco_env.sh
cd workspaces/fishbot_mujoco_ws
colcon build --packages-select fishbot_mujoco
```

返回项目根后执行全部案例：

```bash
./fishbot.sh scene-validation \
  --output "$HOME/.cache/fishbot/scene-validation/run"
```

默认独占domain130和API9100。畅通与堵塞案例预算90秒，绕障预算120秒；原90秒绕障在仍有返程进展时到期的失败记录保留。每例使用独立世界，逐例启动、采集、评分和清理；某例失败仍继续后面的案例。输出目录中的report.json和index.html汇总全部结果，各次原始尝试分别保留。只准备场景时使用`--prepare-only`。

## 三个案例

| 案例 | 地图与物理世界 | 路线预期 |
|---|---|---|
| clear | 门口畅通 | 到目标后返回本轮起点并停稳 |
| detour | 静态地图外有箱子，旁边可绕行 | 实时感知箱子并完成往返 |
| blocked | 同一门口被更宽的箱子堵住 | 不穿墙、不碰撞，结束原任务并停稳 |

三例共享基图，仅改变外部障碍。另有8厘米高的矮障碍，低于二维雷达扫描平面，且不写入静态地图。只读探针核对它在三维点云及实际Nav2代价地图中的表现。

`route_completed`只表示本轮往返路线完成。`route_incomplete`表示路线未完成。堵塞后正确取消可以是案例验收通过，同时路线未完成；不能把取消或到点写成已收货。

## 修改输入

编辑[示例配置](../tools/config/scene_validation.example.json)，修改目标点、门口案例和来源说明。重复运行会读取当前内容；没有文件哈希执行锁。

需要接入已有地图时，先运行：

```bash
/usr/bin/python3 tools/fishbot_scene_validation.py prepare \
  --config tools/config/scene_validation.example.json \
  --source-map /absolute/path/map.yaml --output /absolute/path/prepared
```

此路径复用home_scene，保留实测格和assumption_mask。补全区域仍是假设。地图、物理墙、障碍高度、出生点和坐标对应关系需要分别核对，不能仅凭地图存在判断场景可用。默认参考场景的结果不转记为这份地图的验收。

## 三维雷达

使用官方mujoco_ros2_control_plugins 0.1.1的Mujoco3dLidarPlugin和同源mujoco_3d_lidar扩展，Apache-2.0。复用官方射线与PointCloud2发布，不编写替代传感器。上游说明：[官方插件文档](https://control.ros.org/jazzy/doc/mujoco_ros2_control/mujoco_ros2_control_plugins/doc/plugins.html)。

通用配置为16线、每圈360点、10Hz、垂直正负15度、量程0.12至8米。它是理想化通用扫描器，不标为某款Ouster、Velodyne或Livox的标定模型。配置在[lidar3d.yaml](../workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/config/lidar3d.yaml)，可直接编辑。

二维scan继续供AMCL定位。三维点云发布到`/sensors/lidar3d/points`，进入局部和全局Voxel Layer。雷达位于laser_link上方3.5厘米，发布正确的lidar3d_link静态TF。点云不附加虚构的ring、逐束时间或反射率。

本机扩展位于`~/.cache/fishbot/lidar3d/prefix`。包装器、扩展和实际C++ engine已核为同一MuJoCo3.12.0 vendor；SO101规划环境的3.3.7属于另一依赖边界。启动包装器只给本命令添加ament前缀，不修改原vendor、系统ROS或网络。

### 在新环境构建官方扩展

现有ROS包装器之外，还需要同源原生扩展。下列命令使用0.1.1源码和当前vendor，只构建扩展并暂存到用户缓存；保留上游LICENSE。

```bash
source tools/fishbot_mujoco_env.sh
lidar_cache="$HOME/.cache/fishbot/lidar3d"
lidar_source="$lidar_cache/upstream-0.1.1"
lidar_prefix="$lidar_cache/prefix"
mkdir -p "$lidar_source"
curl -fL https://codeload.github.com/ros-controls/mujoco_ros2_control/tar.gz/refs/tags/0.1.1 \
  | tar -xz --strip-components=1 -C "$lidar_source"
cmake -S "$lidar_source/mujoco_extensions/mujoco_3d_lidar" \
  -B "$lidar_cache/build-0.1.1" -DCMAKE_BUILD_TYPE=Release \
  -DPython3_EXECUTABLE=/usr/bin/python3 \
  -DCMAKE_PREFIX_PATH="$PWD/workspaces/fishbot_mujoco_ws/.runtime/opt/ros/jazzy;/opt/ros/jazzy"
cmake --build "$lidar_cache/build-0.1.1" --parallel 2
mkdir -p "$lidar_prefix/lib/mujoco_3d_lidar/mujoco_plugin" \
  "$lidar_prefix/share/mujoco_3d_lidar" \
  "$lidar_prefix/share/ament_index/resource_index/mujoco_plugins" \
  "$lidar_prefix/share/ament_index/resource_index/packages"
cp "$lidar_cache/build-0.1.1/libmujoco_3d_lidar.so" \
  "$lidar_prefix/lib/mujoco_3d_lidar/mujoco_plugin/"
cp "$lidar_source/mujoco_extensions/mujoco_3d_lidar/package.xml" \
  "$lidar_source/LICENSE" "$lidar_prefix/share/mujoco_3d_lidar/"
printf '%s' 'lib/mujoco_3d_lidar/mujoco_plugin' \
  > "$lidar_prefix/share/ament_index/resource_index/mujoco_plugins/mujoco_3d_lidar"
touch "$lidar_prefix/share/ament_index/resource_index/packages/mujoco_3d_lidar"
```

不要运行上游`cmake --install`到当前vendor目录。`scene-validation`包装器自动读取上述私有前缀；单独启动时需将它加入当前命令的`AMENT_PREFIX_PATH`。自定义安装路径可用`FISHBOT_LIDAR3D_PREFIX`选择。

## 评分与报告

- 原任务UUID：从原mission owner查询，独立读取同UUID原生动作终态。回执未知不重发Goal。
- 实际运动：独立读取真值、航点按序覆盖、终误差、数据新鲜度及连续停稳。
- 实际碰撞：只读ContactAudit在每物理步检查正法向接触，累计机器人对非地板碰撞步数。它不改qpos、qvel或控制量。
- 几何净距：单独计算，不冒充实际接触力。缺少证据时标为incomplete。
- 三维感知：分别记录真实点云、订阅端点、Nav2参数、原时间戳TF下的低障碍回波和costmap占用。

在网页的“成果验收”查看“场景业务验证”。显式点击“读取最新报告”，或导入本地JSON。服务端用`FISHBOT_SCENE_REPORT=/absolute/path/report.json`选择报告文件；浏览器不能指定服务器文件路径。编辑报告后重读即可，无需重跑仿真。报告入口只支持GET。

## 当前限制

Nav2沿用0.13米圆形足迹近似；独立评分另用0.105×0.125米半尺寸矩形。这两个几何模型尚未统一，不能从三个案例通过推断所有姿态和窄口都可通过。替换底盘前应单独核对完整外廓、定位误差和转弯扫掠。

路径诊断只保留末段有限快照：每主题最多2Hz，栅格10份，路径与前瞻点各20份。它用于定位失败，不向机器人发布控制命令。

## 保留范围

本轮保留FishBot作为对照底盘，新增通用三维传感器和路线验收。更换整车需要接回实际运动学、碰撞外廓和执行接口。涵道负压、爬壁、货物签收及sim-to-real不在本轮通过范围。

当前运行结果与失败见[实施进度](../plans/scene-business-validation-20261020/progress.md)。
