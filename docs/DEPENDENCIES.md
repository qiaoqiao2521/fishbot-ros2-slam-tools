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
