# Jackal J100 source-derived MuJoCo adapter

Source: [Clearpath ROS 2 Jazzy description](https://github.com/clearpathrobotics/clearpath_common/tree/78e3677412f1fed881f6436cdaf404f04f28ee4f/clearpath_platform_description/urdf/j100).
Revision: `78e3677412f1fed881f6436cdaf404f04f28ee4f`.
License: BSD-3-Clause; the upstream license is retained in `LICENSE`.

`source_j100.urdf.xacro`, `source_outdoor.urdf.xacro`, `j100_base.stl`, and
`outdoor.stl` are unchanged upstream source/visual assets. The adapter uses the
upstream box/cylinder collision shapes, chassis center of mass/full inertia,
four wheel inertias, nominal wheel radius, wheelbase and track. The upstream
visual mesh transforms are retained. No full Clearpath bringup stack is copied.

`tools/fishbot_base_profile.py` generates an editable native MJCF plant, matching
ROS 2 control/TF description, controller arrays, Nav2 footprint and provenance.
The geometry encloses all four tires. Its 15 mm padding is a stated simulation
margin and is exported as a rectangle for independent geometric scoring. Nav2
uses the circumscribed circle of that complete rectangle, because the existing
NavFn planner uses circular inflation. A tire-track-only circle is insufficient.
The generated inflation radius preserves the baseline's 0.17 m gradient beyond
the selected body radius. It is an editable profile assumption, not a smaller
robot envelope or a relaxed collision check.

MuJoCo wheel friction, bounded wheel velocity servos and sensor mounting are
explicit assumptions in `tools/config/base_profiles/jackal_j100.yaml`. They are
not manufacturer motor limits, calibrated tire slip or a validated digital twin.
The controller keeps the existing low-speed limits and feedback odometry.
Real J100 odometry may require calibration; no effective skid-steer track is
invented to hide the difference between wheel odometry and physical motion.

The J100 profile uses the installed upstream `robot_localization` EKF and
`imu_sensor_broadcaster`. Only wheel vx/vy and native MuJoCo IMU roll/pitch/gyroZ
are fused. Wheel yaw/wz, absolute IMU yaw, acceleration and ground-truth pose
are excluded. The IMU is ideal simulation sensing, not measured hardware noise.
The EKF alone publishes full-rpy `odom -> base_footprint`; the diff-drive
controller retains feedback wheel odometry but does not publish TF. FishBot's
default launch remains unchanged. Fusion is editable in the J100 profile.

The installed Nav2 [PoseProgressChecker](https://github.com/ros-navigation/navigation2/blob/jazzy/nav2_controller/plugins/pose_progress_checker.cpp)
counts rotation as well as translation. J100 uses 0.2 rad of angular progress,
while retaining the existing 0.15 m translation threshold and 10 s deadline.
This avoids classifying a real skid-steer turn as a stationary failure. No
deadline is extended. The native probe's observed turn supplies a limited
simulation basis; actual ROS navigation still needs independent scoring.

J100's editable `rpp_rotation_max_angular_accel_rad_s2` is 10.0. This configures
RPP's rotation-command slew relative to measured gyro speed; it is not a claim
that the body achieves 10 rad/s². The existing wheel controller keeps its
2 rad/s² command limit, velocity limits, torque cap and watchdog. A frozen
native plant comparison produced 0.0191 rad of actual IMU yaw for a 0.1 rad/s
body command held for 2 s, versus 0.1547 rad for 0.5 rad/s. At 20 Hz, the old
RPP value 2 only allowed a 0.1 rad/s increment over measured speed. The new
value permits a 0.5 rad/s initial increment, whose native probe wheel torque
peak was 7.665 Nm, below the unchanged 12 Nm cap. These observations justify a
simulation control adaptation, not real J100 actuator/tire calibration.

`tools/tests/base_profile_probe.cpp` loads the generated scene with the same
native MuJoCo SDK as the ROS plant, settles on the floor, commands bounded wheel
servos to drive and turn, then stops. It records actual wheel angles, angular
speeds, actuator torques, positive wheel/floor contacts and body motion. It
never writes base position, velocity or simulation time. A native probe pass
does not prove ROS navigation. Strong turn slip remains visible in the report.

Example build from the repository root (compiled files stay outside Git):

```bash
task_mj_prefix="$PWD/workspaces/fishbot_mujoco_ws/.runtime/opt/ros/jazzy/opt/mujoco_vendor"
task_probe_dir="$HOME/.cache/fishbot/base-profile-probe"
mkdir -p "$task_probe_dir"
g++ -std=c++17 -O2 tools/tests/base_profile_probe.cpp \
  -I "$task_mj_prefix/include" -L "$task_mj_prefix/lib" \
  -Wl,-rpath,"$task_mj_prefix/lib" -lmujoco -o "$task_probe_dir/probe"
python3 tools/fishbot_base_profile.py \
  --scene workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/mjcf/arena.xml \
  --output "$task_probe_dir/generated"
"$task_probe_dir/probe" "$task_probe_dir/generated/scene.xml" "$task_probe_dir/result.json"
```
