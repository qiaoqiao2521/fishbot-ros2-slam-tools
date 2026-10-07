# FishBot MuJoCo physical description

This package adapts the existing FishROS FishBot physical description to ROS 2 Jazzy and `mujoco_ros2_control`. Wheel servos drive actual hinges against floor contacts; it does not override the base pose or velocity. The arena is a synthetic fixture, with no captured room map or hardware/network configuration.

## Run on this workstation

Use Ubuntu 24.04 / ROS 2 Jazzy with Nav2, RPP, xacro and robot_state_publisher already installed. The missing MuJoCo/control dependencies are downloaded and extracted locally, without a host-wide apt install. Pinned packages are listed in `docs/runtime-packages.json`.

```bash
cd /path/to/fishbot-ros2-slam-tools
# Only needed when the extracted runtime is absent:
./tools/fishbot_mujoco_bootstrap.py
./tools/fishbot_mujoco.sh build
./tools/fishbot_mujoco.sh headless
```

In another terminal, request the verified obstacle-avoiding goal:

```bash
cd /path/to/fishbot-ros2-slam-tools
./tools/fishbot_mujoco.sh verify nav --x 2.0 --y 1.0
```

`sim` instead of `headless` opens the MuJoCo viewer and RViz when a desktop display is available. The unattended acceptance uses `headless`; desktop interaction is a separate check. Press Ctrl+C in the launch terminal to stop that simulation.

For command timeout and stale-command acceptance, stop the navigation launch first, then launch `headless nav:=false` and run `verify motion` in the other terminal. The probe refuses competing command publishers. Reports and ROS logs stay in the workspace's ignored `.runs/` directory.

The wrapper and launch default to ROS domain **93** and loopback discovery. Isolated acceptance may explicitly select another nonzero domain; the inspection demo uses domain 97. The simulation page connects only this isolated stack; the real-car control station and micro-ROS session retain their own configuration. Do not source this simulation environment into the real-car session.

## Web patrol

For the separate three-point onboard-camera inspection demo, run `./tools/fishbot_inspection.sh` from the project root. It uses isolated domain 97, its own synthetic scene, and AMCL/Nav2. The resulting HTML report includes actual RGB observations and return/stop evidence. See [visual inspection](../../../../docs/VISUAL_INSPECTION.md) for the pixel-recognition scope and acceptance.

```bash
cd /path/to/fishbot-ros2-slam-tools
./tools/fishbot_mujoco.sh web
# A GUI-free alternative for the same physical/navigation stack:
./tools/fishbot_mujoco.sh web headless:=true
```

Open `http://127.0.0.1:5173/simulation`. Load the three-point route or select free map locations, then start patrol; return home is selected by default. Cancel waits for the actual Nav2 result. During patrol, move the physical obstacle into the route; it yields and returns to parking. A tight location can reject insertion rather than placing the box through the car or fixed scene.

This uses the existing frontend in `apps/fishbot-control-station/frontend`; its dependencies must be installed with `npm ci` once. The web entry starts its own loopback Vite server and ROS mission bridge, refuses occupied ports and cleans up only its own frontend process group. It keeps the original console's Java API separate. The mission bridge has no velocity-command endpoint.

The actual map, localization, plan and independent physical pose come from ROS. Browser goals carry a sender timestamp; expired requests, occupied/unknown footprint cells and overlapping tasks are rejected. A task has at most 12 user points plus its optional return-home point. FollowWaypoints feedback and terminal results determine mission status; missed points prevent success. Simulation-clock freshness and navigation readiness gate new dispatch. RViz opens after a bounded 45-second startup readiness check when requested.

The external `moving_obstacle` is a real MuJoCo free body with contact and lidar geometry, moved by a named-body-only service. Its motion is prescribed for this demo, rather than a calibrated driven vehicle. Ground truth never replaces the robot odometry or AMCL transform. Details and acceptance are in [the web patrol plan](../../../../plans/fishbot-web-patrol-20261004/task_plan.md).

## Navigation baseline

The default `config/nav2.yaml` uses AMCL + NavFn + Regulated Pure Pursuit, followed by the velocity smoother and Collision Monitor. The docking node is remapped into the same filtered command chain. Robot radius is 0.13 m and maximum forward speed is 0.25 m/s. Initial localization is explicitly seeded at the synthetic arena's known `(0,0,0)` start.

`config/nav2_mppi.yaml` preserves an **experimental** MPPI profile. It did not pass the final approach test and is not the accepted baseline. BCR's own MPPI reference passed its separate reproduction test; that does not establish FishBot MPPI tuning.

The synthetic map is generated from the arena's static boxes during CMake configuration. `arena.pgm` is a build product, not a captured room map. The source controller measures wheel position for odometry; the ground-truth pose is used only for independent acceptance.

## Source and changes

The physical source is [`fishros/fishbot`, Humble, `src/fishbot_description/urdf/fishbot_gazebo.urdf`](https://github.com/fishros/fishbot/blob/humble/src/fishbot_description/urdf/fishbot_gazebo.urdf). The local source used for this adaptation is at Git commit `84f863f4955891a5e20dd4e68aca442eb3ec0e32`; the source file SHA256 is `f55c71f7ad644637a4d43d60bc17e9b91138b294c4ac31ee5e30b1fbf0056749`.

All six physical links retain their source mass and diagonal inertia. The source's total modeled mass is 0.82 kg. These are educational-model parameters, not measurements of this particular real robot. The upstream description's package currently declares `TODO: License declaration`; attribution is retained here and this package does not assert a license for the upstream-derived description.

| Parameter | Source and adaptation |
|---|---|
| Chassis | Cylinder radius 0.10 m, length 0.12 m, mass 0.20 kg |
| Driven wheels | Radius 0.032 m, width 0.04 m, mass 0.20 kg each |
| Wheel centers | `x=-0.02 m`, `y=±0.10 m`, `z=-0.06 m` from `base_link` |
| Support | Fixed sphere, radius 0.016 m at `(0.06, 0, -0.076)`, source frictionless contact |
| Laser | Radius 0.02 m, length 0.02 m, `z=0.075 m` from `base_link` |
| Ground frame | Source `base_joint` height 0.076 m becomes 0.092 m; this 16 mm adjustment puts wheels and support sphere on the same ground plane |

The controller uses the geometry's wheel radius **0.032 m**. The legacy Gazebo plugin rounded wheel diameter to 0.065 m; copying that rounded setting into the new controller would introduce a scale mismatch. Driven-wheel friction (1.0), servo gain (0.25), contact solver parameters, velocity/acceleration limits and the 2 mm initial drop are explicit simulation assumptions. The torque cap (20 Nm) follows the source Gazebo plugin but is not a calibrated motor model. The source's interior IMU box is visual-only in MJCF; this does not change external robot contact geometry.

## Model and ROS interfaces

- [`mjcf/fishbot.xml`](mjcf/fishbot.xml): six-DoF floating base, two driven wheel hinges, frictionless support contact, IMU and 360 horizontal rangefinders.
- [`mjcf/arena.xml`](mjcf/arena.xml): 8 m square synthetic arena with three obstacles. The robot starts at `(0, 0)` facing `+X`.
- [`urdf/fishbot_mujoco.urdf.xacro`](urdf/fishbot_mujoco.urdf.xacro): original link/joint names, adapted ground height and the MuJoCo system interface. Arguments: `headless`, `scene_path`, `sim_speed_factor`.
- [`config/controllers.yaml`](config/controllers.yaml): `joint_state_broadcaster`, `diff_drive_controller`, wheel-position feedback and 0.5 s command timeout. The launch layer must remap the controller's TwistStamped command input and odometry output.
- [`config/plugins.yaml`](config/plugins.yaml): `/scan` at 10 Hz in `laser_link`, source range limits 0.12–3.5 m, and isolated ground-truth state.

Laser directions are `0°..359°` with 1° spacing, avoiding the duplicate end beam at 360°. Noise is currently zero; this is an explicit repeatable baseline, not a claim that the source Gazebo laser noise was reproduced.

`diff_drive_controller` owns `odom → base_footprint`; `robot_state_publisher` owns the link transforms below it. AMCL or SLAM must be the sole owner of `map → odom`. The ground-truth plugin owns **no TF edge** and its output must not replace `/odom` during navigation acceptance.

The control hardware sets `auto_register_cameras=false`; the arena overview camera is therefore viewer-only. The explicit RangefinderLidarPlugin config avoids the `mujoco_ros2_control 0.1.1` legacy lidar rate parameter mismatch. Its free-joint publisher in that version reads `topic`, `publish_rate` and `body_names` at the top ROS parameter level; the explicit topic is `/ground_truth/free_joint_states`. Its default empty `frame_id` means MuJoCo world coordinates. The `free_joints[].name` is the body `base_footprint`, not the joint `base_free_joint`.

## Validation boundary

On 2026-10-05 the web patrol acceptance completed three selected patrol points plus return home in approximately 90.94 s, with no missed waypoints. Independent physical return-home XY error was 0.11643 m and the final robot was stopped. The moving box completed insertion, held blocking, retreat and parking; its surface appeared in all 33 held-blocking lidar frames. The robot slowed forward motion, continued turning and resumed travel. The saved trace does not prove a full stationary stop during blocking or attribute intervention to Collision Monitor. See [`docs/web_patrol_reference.json`](docs/web_patrol_reference.json) for measurements and limits, and [the progress record](../../../../plans/fishbot-web-patrol-20261004/progress.md) for browser/error/cancellation checks. This is simulation acceptance only.

On 2026-10-04 the isolated ROS stack also passed the synthetic fixture's obstacle-avoiding goal `(2,1)` using AMCL and RPP: action status 4/error 0, elapsed 22.40 s, physical XY error 0.1333 m, yaw error 0.0566 rad, and negligible final planar/angular speed. Measured scan was 360 beams at 9.95 Hz and wheel odometry 29.99 Hz. A separate motion test stopped approximately 0.607 s after the last command and rejected repeated commands carrying timestamps 10 s old. Acceptance uses the MuJoCo body state independently of odometry and localization. These results apply to this fixture and controller profile; desktop interaction, dynamic obstacles and hardware remain separate acceptance scopes.

On 2026-10-03, MuJoCo 3.12.0 compiled both MJCF files, resolved both driven joints and all 360 rangefinder names. A native smoke test settled for 2 s, commanded both wheels at 3 rad/s for 2 s, then commanded zero for 2 s. Measured values are retained in [`docs/native_model_reference.json`](docs/native_model_reference.json): forward travel 0.191661 m, wheel-position prediction 0.191766 m, additional stopping travel 0.001073 m, negligible lateral drift and a settled footprint height of approximately -0.000028 m. All generalized coordinates remained finite.

This verifies model compilation and basic native contact/actuation behavior. ROS timing, controllers, laser publication, localization, Nav2, the real transport path, motor dynamics and physical stopping protection require their own acceptance. The Jazzy controller rejects expired nonzero-stamped commands when their original timestamps are preserved through the smoother and Collision Monitor. Arrival-only firmware watchdogs and bridges that replace source timestamps cannot provide this guarantee; the real FishBot firmware has not gained this protection from simulation work.
