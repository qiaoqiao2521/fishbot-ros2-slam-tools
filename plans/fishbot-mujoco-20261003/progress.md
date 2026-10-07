# Progress

## Current
2026-10-04: FishROS-derived MuJoCo + Jazzy Nav2 automatic navigation passed in the synthetic fixture. The accepted default is RPP. Hardware navigation remains unverified.

## Done
- Pinned BCR reference at `58b9220f35870bf8543db12f8b457942fa07cac3`; its independent MPPI goal reproduction passed. Reference-only changes are retained in [bcr-compat.patch](bcr-compat.patch).
- Reused the FishROS six-link physical model at `84f863f4955891a5e20dd4e68aca442eb3ec0e32`; native wheel/contact test and selected colcon build passed.
- Locally extracted pinned runtime dependencies; no host-wide package installation. Wrapper and launch enforce domain 93 and localhost discovery.
- Final obstacle-avoiding goal `(2,1)`: action status 4/error 0, 22.4028 s, actual XY error 0.1333 m, yaw error 0.0566 rad, final planar/angular speed near zero. Laser measured 360 beams at 9.95 Hz; wheel odometry 29.99 Hz.
- Independent motion test: last command to stopped state 0.6068 s, negligible later drift; repeated commands stamped 10 s old did not restart motion.
- Actual command graph: only Collision Monitor publishes `/cmd_vel`; docking now enters `/cmd_vel_nav` with other Nav2 sources, followed by the smoother and Collision Monitor.
- Verifier checks finite and advancing physical state, ROS-stamp and wall-time freshness, valid laser returns, action result, actual position/yaw and stopped velocity. Independent read-only review found no blocking defect for this fixture.
- Saved commands in [package README](../../workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/README.md). Final report, measured trajectory and JSON evidence are in `local-only: outputs/`. Testing processes were stopped.
- Prepared a selective local source commit of this package, its three entry tools and this task directory; preserve generated maps, extracted runtimes, logs and other project work outside that commit.
- User-visible desktop demonstration also passed after restart: MuJoCo viewer + RViz, goal `(2,1)`, action status 4/error 0, elapsed 20.7523 s, actual position error 0.1020 m and negligible final speed. A 42 s direct recording of the MuJoCo window and a cropped 2x-speed GIF are saved in the chat's outputs as `fishbot-live-navigation.mp4` and `fishbot-live-navigation.gif`; raw result is `fishbot-gui-navigation-result.json`. The simulator and RViz are left open for the user to inspect, with the robot stopped at its goal.

## Remaining
- No remaining work for this bounded simulation navigation acceptance.
- Physical validation requires separately resolving the real transport delay, firmware stopping protection and model calibration before an authorized hardware motion test.

## Issues
- FishBot MPPI final approach failed; [experimental profile](../../workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/config/nav2_mppi.yaml) is not accepted. RPP passed twice, with the final run using strengthened truth/yaw/stop checks.
- Sampled geometric clearance is approximately 0.2384 m using a 0.13 m circular footprint; this is not continuous contact verification. Sensor rates are measurements, not automatic rate gates.
- Existing approximately 10 s hardware control delay and unflashed firmware watchdog remain real-car prerequisites. Manual/web arbitration, future stamps, sequence ordering and arrival-restamping are outside this test.
- Publication: parent Git `<historical-parent-repository>` has no remote; nested FishROS upstream is not the integration destination. No push was performed.
- Recoverable owner: root Codex must reconcile the preserved 316 tracked migration changes and untracked/nested light-sim work, following `<historical-workbench>/plans/hardware-consolidation-20260915/progress.md`. Do not fold those changes into this bounded commit. Shortest publication entry: establish and verify the intended existing `qiaoqiao2521` destination for the actual parent/project, then review migration scope and rerun its recorded layout checks.
- `FISHBOT_STATUS.md` and `PROJECT.md` were updated locally for continuity but are not staged with this new integration; the status file contains historical private network details that must remain local.
- First simultaneous GUI/Nav2/RViz startup stalled: controller configuration completed, but its lifecycle service response timed out and navigation manager continued waiting. This was not an accepted navigation run; failed video/result remain under the ignored local evidence directory. Restarting with `sim rviz:=false`, confirming navigation active, then launching RViz separately succeeded. A DDS startup race is an inference, not a proven cause. The default `sim` entry still starts RViz concurrently; automated readiness gating remains an optional robustness improvement.

## Next
Reproduce with `./tools/fishbot_mujoco.sh headless`, then in another terminal `./tools/fishbot_mujoco.sh verify nav --x 2 --y 1`. For the verified desktop sequence, use `sim rviz:=false`, wait for navigation's `Managed nodes are active`, then source `tools/fishbot_mujoco_env.sh` in another terminal and run `ros2 run rviz2 rviz2 -d /opt/ros/jazzy/share/nav2_bringup/rviz/nav2_default_view.rviz --ros-args -p use_sim_time:=true`. Mouse-selected RViz goals and real-car navigation retain separate acceptance boundaries. Close the simulation launch and the separately launched RViz when finished viewing.
