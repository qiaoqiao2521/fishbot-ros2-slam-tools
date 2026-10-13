# Dependency / build boundary

本机Ubuntu24.04 / ROS2 Jazzy；Python固定使用 `/usr/bin/python3`。Java后端用Gradle wrapper，前端用package-lock.json。项目根不执行统一colcon build。

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
