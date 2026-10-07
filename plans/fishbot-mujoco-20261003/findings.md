# Findings

- Existing full physical model: fishbot/src/fishbot_description/urdf/fishbot_gazebo.urdf, upstream fishros/fishbot humble at 84f863f. Active fishbot_nav description is only the simplified visualization/TF model.
- BCR reference: blackcoffeerobotics/bcr_bot ros2-jazzy, 58b9220f35870bf8543db12f8b457942fa07cac3.
- Installed Jazzy already supplies Nav2, SLAM Toolbox and diff-drive controller. Local apt candidates: mujoco_ros2_control/plugins/msgs 0.1.1; mujoco_vendor 0.1.0 (MuJoCo 3.12.0).
- BCR hardcodes headless=false. Its legacy lidar interface remains compatible in 0.1.1, but legacy publish_rate differs from lidar_publish_rate; set the plugin parameter explicitly.
- BCR MJCF wheels have radius 0.1 m and separation 0.6 m; controller YAML says 0.11/0.64. Correct only the isolated reference config.
- Project root resolves to parent Git <historical-parent-repository> with no remotes and extensive preserved migration changes. Nested fishbot_nav points to FishROS upstream / archived old account. No verified qiaoqiao2521 publication destination is attached to the actual development root.
- The 0.1.1 free-joint publisher reads topic/publish_rate/body_names at top-level ROS parameters, unlike the lidar plugin's nested parameters. Explicit /ground_truth/free_joint_states avoids accidental defaults.
- Docking in installed Nav2 originally published directly to /cmd_vel. Node-scoped remapping now puts it on /cmd_vel_nav; actual graph shows only collision_monitor publishing final /cmd_vel and diff_drive_controller consuming it. All command edges use TwistStamped.
- Original timestamps survive the Nav2 smoother and Collision Monitor. Jazzy diff_drive_controller rejects nonzero timestamps older than its timeout. This does not solve arrival-stamping, future timestamps or command ordering, and does not change the real firmware.
- FishBot MPPI failed final approach; RPP succeeded twice. Final strengthened check includes fresh wall-time truth, advancing clock/state, valid lidar returns, action success/error code, physical XY/yaw and stopped velocity.
- Synthetic map generation belongs to CMake build output; no real map or generated PGM belongs in the source commit.
- Desktop demo exposed an intermittent startup problem: navigation manager stuck after controller configure response timeout, despite successful configuration. Installed Nav2 service invocation can wait indefinitely; no exposed lifecycle service-response timeout was found. A fresh restart without early RViz, followed by RViz only after Nav2 became active, passed actual GUI navigation. Do not claim that increasing `bond_timeout` fixes a pre-activation lost service response, or that the inferred DDS startup race is established root cause.
