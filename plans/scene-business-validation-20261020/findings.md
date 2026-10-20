# 已知事实与采纳

- 用户要求借鉴引用对话实施；引用新增了通用三维雷达和更换FishBot的意向。
- 当前实现使用MuJoCo，不迁移Gazebo作为本轮前置条件。
- 原suite覆盖窄口、连续路线、断流、取消和旧命令，未形成畅通/绕行/堵塞三工况业务面板。
- home_scene已有地图生成、补全区域mask与moving_obstacle_free_joint，可直接扩展。
- 已安装mujoco_ros2_control_plugins 0.1.1声明Mujoco3dLidarPlugin。采用其原生PointCloud2路径；扩展已用C++ MuJoCo3.12.0 vendor编译并实际加载；360×16点云进入全局/局部Voxel Layer。
- 新底盘与传感器按配置分开。保留FishBot作为回归对照，不把更换外观称为新机器人动力学验收。

## 采用的项目经验

采用知识库FishBot第19/20节：观测、原生动作终态、交接和独立物理评分分别判断；补全场景不冒充实测；原任务恢复不自动重发。范围限仿真，不据此宣称sim-to-real成功。

## 实际调试结论

- 只读点云探针不能在解析主循环中仅spin一次回调。B轮捕获到TF落后0.35–1.25s，原5帧队列提前退休待配准数据。改为单个ROS executor持续回调、32帧/3秒有限待配准队列；仍按原stamp查TF。C轮实际取得56个低障碍点，世界高度0.03675–0.08007m。
- C轮绕障最终为90秒期限到达后的原任务取消。末段source95→103，起点距离减少0.721m，剩余规划长度连续下降；不能把期间的预测碰撞直接解释为最终卡死。只给detour改为120秒，不改变物理/碰撞/误差门槛。A/C原始失败保留。
- 现Nav2采用0.13m圆近似，评分采用0.105×0.125m半尺寸的矩形。圆近似未包住矩形全部朝向；路径贴角与定位误差存在风险线索。当前通过范围只限具体三案例，不据此宣称全姿态硬件替换已完成。后续足迹/规划器专项保留此差异，避免随意关闭碰撞保护。
- 调试快照使用有限保留：每主题最多2Hz，末10份栅格和20份路径/前瞻点。单轮失败不会生成无限物理日志。

官方版本依据：[MuJoCo插件0.1.1](https://github.com/ros-controls/mujoco_ros2_control/tree/0.1.1/mujoco_extensions/mujoco_3d_lidar)、[Jazzy RPP参数](https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/controller_plugins/configuring_regulated_pp/)。RPP以前瞻点生成跟踪弧线，路径存在不等于该跟踪弧线在当前定位下可通过。
