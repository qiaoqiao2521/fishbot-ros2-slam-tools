# Local architecture

- `apps/fishbot-control-station/`：Java/React控制台。
- `fishbot_nav/`：Jazzy导航/描述/接口工作区。
- `fishbot_laser_ws/`：实际使用的Python网络雷达驱动工作区。
- `workspaces/micro_ros_agent_ws/`：micro-ROS Agent及消息源码与本机构建。
- `fishbot_motion_control_microros/`：主控固件源；`fishbot_tool/`：烧录工具与固件素材。
- `tools/`：运行编排和安全门；`fishbot.sh`：统一入口。
- `plans/`：建图、网络及本地成果。`fishbot/`和`fishbot-control-ros2/`是保留的历史实现，不与活动工作区混编。

源码向内收敛，旧路径向新项目链接。保留Git目录以保护历史，暂不自动压平为单仓。旧安装目录中的绝对路径可能经兼容链接工作；fresh build验收应另行记录，不能用布局通过替代。

连续过窄口入口使用 `Nav2 → 速度平滑 → Collision Monitor → 最终命令守卫 → 底盘`，统一官方模型外廓，区分限速余量和硬碰撞范围，并记录可回放的停车数据。配置、仿真和实车接入边界见 [PASSAGE_CONTROL.md](PASSAGE_CONTROL.md)。原短段控制脚本保留；两套入口不可同时控制最终速度。

虚拟视觉巡检使用独立 domain 97：AMCL/Nav2 到点、停稳、三帧新鲜车载 RGB、像素判断、图文报告、返航。相机与三工位场景位于 `workspaces/fishbot_mujoco_ws`；入口和验收边界见 [VISUAL_INSPECTION.md](VISUAL_INSPECTION.md)。物理真值只核验拍摄位姿和到点误差，不输入图像识别。
