# Local architecture

- `apps/fishbot-control-station/`：Java/React控制台。
- `fishbot_nav/`：Jazzy导航/描述/接口工作区。
- `fishbot_laser_ws/`：实际使用的Python网络雷达驱动工作区。
- `workspaces/micro_ros_agent_ws/`：micro-ROS Agent及消息源码与本机构建。
- `fishbot_motion_control_microros/`：主控固件源；`fishbot_tool/`：烧录工具与固件素材。
- `tools/`：运行编排和安全门；`fishbot.sh`：统一入口。
- `plans/`：建图、网络及本地成果。`fishbot/`和`fishbot-control-ros2/`是保留的历史实现，不与活动工作区混编。

源码向内收敛，旧路径向新项目链接。保留Git目录以保护历史，暂不自动压平为单仓。旧安装目录中的绝对路径可能经兼容链接工作；fresh build验收应另行记录，不能用布局通过替代。
