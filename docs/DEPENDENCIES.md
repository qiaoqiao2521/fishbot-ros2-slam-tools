# Dependency / build boundary

本机Ubuntu24.04 / ROS2 Jazzy；Python固定使用 `/usr/bin/python3`。Java后端用Gradle wrapper，前端用package-lock.json。项目根不执行统一colcon build。

## 当前工作台依赖

前端锁定`dockview-react 8.6.0`、`three 0.186.1`、`urdf-loader 0.13.1`及`@types/three 0.186.0`。前两项使用MIT，URDFLoader使用Apache-2.0；安装包保留上游许可证。选型来源与后续源码底座迁移见[重构依据](../plans/workbench-rebuild-20261018/findings.md)。

当前导入支持有界、无纹理的内嵌资产，不请求外部网格、图片或解码器。项目自有简化模型不代表FishROS或SO101完整网格已获分发授权。完整仿真依赖与网页预览模型分别核验。

依赖审计尚未收束：最新报告保留22项既有告警（2critical/14high/4moderate/2low）。没有执行跨主版本强制升级；具体审计、兼容修复与新底座迁移状态回源[当前进度](../plans/workbench-rebuild-20261018/progress.md)。

## 可选 Arena 组合评测

`./fishbot.sh arena` 是独立评测的薄部署入口，使用系统Python做预检，使用官方独立uv环境执行。版本、gitlink与lock文件来源见 [Arena说明](../experiments/arena/README.md)；源码/环境/资产留在缓存，不进入本项目Git。Arena的Isaac Sim6.1/Torch2.11/MuJoCo3.11依赖不会安装到既有ROS或SO101规划环境。当前本机4GB显存低于官方基线，真实运行尚未部署；不自动接受许可。

保留的上游来源与本机HEAD（2026-09-15）：

| Source | Revision | Local path |
| --- | --- | --- |
| https://github.com/micro-ROS/micro-ROS-Agent.git | 7c932329ad5591ef23942ef1962534258c16b000 | workspaces/micro_ros_agent_ws/src/micro-ROS-Agent |
| https://github.com/micro-ROS/micro_ros_msgs.git | e65ab21bd0733ebff2af6317d573cc584efa5893 | workspaces/micro_ros_agent_ws/src/micro_ros_msgs |

这些版本只记录上游基线；本机dirty内容仍随工作区保留，不能checkout覆盖。导航包与实际Python雷达源码均已纳入本项目目录。旧C++雷达包和历史工作区不与活动雷达混用。

按需在对应workspace source `/opt/ros/jazzy/setup.bash` 后构建；为避免Conda污染可用 `PATH=/usr/bin:/bin`，指定 `-DPython3_EXECUTABLE=/usr/bin/python3`。导航工作区只选择实际需要的包，雷达工作区独立构建，agent工作区构建其消息与agent。不要复用其他机器的build/install目录。

本轮保存了现有build/install，没有声明clean build通过。新机器还需安装ROS系统依赖、Java/Node工具链并执行独立构建；`./fishbot.sh check`只验证源码布局，不代表这些依赖已在新机器安装。

## 固定 SO101 协同

协同入口是 Python 规则的局部例外：通过 `FISHBOT_COOP_PYTHON` 显式选择已有 SO101 规划环境，复用 MuJoCo3.3.7、NumPy、SciPy和OMPL。没有替换系统Python或安装全局包。ROS2 Jazzy及系统PyYAML继续从原安装读取。

只读依赖来自 [qiaoqiao2521/so101](https://github.com/qiaoqiao2521/so101)。本轮checkout基线为 `427e3eb72760ac71e8a272498b28fd90ff8de1a2`，规划模块还有本机未提交状态；因此基线SHA不能唯一复现本轮。准备器在每个私有 `scene-manifest.json` 记录实际模型、网格和规划源码SHA，验收按这些源码逐项核对。

SO101模型上游为 [TheRobotStudio/SO-ARM100](https://github.com/TheRobotStudio/SO-ARM100)，Apache-2.0许可证保存在SO101依赖中。FishBot提交薄适配与测试，不提交依赖的网格、模型副本或运行时生成世界。新机器需要同版接触规划实现；缺文件时明确失败，不替换为动画或另一套算法。见 [COOPERATION.md](COOPERATION.md)。

本机使用rclpy7.1.12。人工控制与原导航路径统一使用官方`SingleThreadedExecutor`，业务回调仍由唯一互斥组和原锁管理。此前参考官方[Jazzy回补1726](https://github.com/ros2/rclpy/pull/1726)的局部多线程yield候选仍出现到期失败，现已撤下，不修改系统rclpy或OS策略。标准执行器对照的实际完成状态见[重构进度](../plans/workbench-rebuild-20261018/progress.md)。

## 可选的本机 Cyclone DDS 对照

本轮在独占仿真domain129验证了rmw_cyclonedds_cpp2.2.4、CycloneDDS0.10.5和iceoryx2.0.6。七个官方Deb版本与SHA256固定在[包清单](../tools/config/fishbot_cyclonedds_packages.json)。约1.99MB下载、8.06MiB解压，许可证保留在解压前缀；不提交二进制，不安装系统包，也不替换原MuJoCo runtime。

复用`fishbot_mujoco_bootstrap.py --packages-file ... --no-link`。自定义清单的全部包先核哈希、Package和Version，再开始解包；无关缓存不参与。默认bootstrap流程保持原行为。实际CLI已用同七包重建750个相同文件，原工作区runtime链接保持。

[loopback配置](../tools/config/fishbot_cyclonedds_localhost.xml)只适用于domain129，固定lo、禁用multicast及共享内存。它与本轮实际配置字节一致。H/I各一次启动13.861s/13.805s，仅是两次观察；不据此宣称解决所有Fast DDS故障或达到统计可靠性。F/G旧发现匹配失败及H验收工具失败保持，细节见本轮progress。
