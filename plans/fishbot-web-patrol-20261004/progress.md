# Progress

## Current
Completed the user-approved web multi-point patrol, physical obstacle handling and startup readiness on 2026-10-05. The live page was reopened with the three-point route loaded and dispatch enabled. The final accepted physical run is preserved separately from earlier failed actor experiments.

## Done
- Inspected actual source roots, current navigation baseline and API/UI boundaries.
- Established [API contract](api-contract.md) and acceptance in [task plan](task_plan.md).
- Added the isolated simulation page, actual FollowWaypoints dispatch/cancellation, named physical actor controller and bounded startup gate. Robot propulsion remains wheel/contact driven; AMCL uses wheel odometry, not ground truth.
- Frontend build, 21 tests and full lint passed on 2026-10-04. Independent review on 2026-10-05 passed 27 Python boundary tests, simulation frontend 8 tests, typecheck and wrapper syntax checks.
- Browser buttons dispatched the real action, inserted the actual obstacle and canceled an active task. Expired/outside/occupied/foreign-origin/overlap requests were rejected; the mission identity was preserved on rejection. Pausing MuJoCo made the page not-ready and blocked dispatch; resume restored readiness.
- Final accepted mission ba2ba335182f4605a257991d5aba4193 completed three patrol points plus home, with no missed points, in 90.94 seconds. Physical final XY error was 0.11643 m and final speed was approximately 6.06e-11 m/s.
- The actor completed moving → blocking → returning → parked. Held blocking produced actor-surface matches in 33/33 scan frames. The car slowed forward motion, continued turning and resumed travel. This trace does not prove a complete stationary stop or Collision Monitor intervention.
- Saved actual browser captures and an 11-second edited GIF/MP4 excerpt. The captures do not show the terminal task screen; completion is established by telemetry and independent physical truth. Compact metrics and source telemetry SHA256 are in [web_patrol_reference.json](../../workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/docs/web_patrol_reference.json).
- Reopened the headless physical stack and verified ready=true on 2026-10-05. The user's page remains open with the three points loaded.
- Root selected the necessary frontend baseline and task sources for local delivery, excluding runtime files, private state, the unrelated migration and nested repositories. Parent Git has no remote, so no push can be performed.

## Acceptance limits
- Simulation only. Real-car latency, MCU watchdog, calibration and hardware Nav2 acceptance remain open.
- Actor motion is prescribed for the demo, with physical contact/lidar geometry; it is not a calibrated driven obstacle vehicle.
- Minimum sampled geometric net clearance was 8.24 cm. This is a sampled estimate, not a continuous no-contact proof.
- The upstream desktop renderer once segfaulted during controlled shutdown; current web entry uses headless physics. Navigation did not crash during the accepted run.

## Owner and recovery
Root Codex owns the remaining integration/publication handoff. Existing 316 tracked migration changes and private/nested project work remain preserved. Parent Git has no remote; publication requires a separately verified intended qiaoqiao2521 destination. Do not stage the entire parent blindly.

Shortest recovery entries:
- Demo: `./tools/fishbot_mujoco.sh web headless:=true` at the FishBot root; frontend `npm ci` and `./tools/fishbot_mujoco.sh build` if dependencies/build outputs are absent. See the package [README](../../workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/README.md).
- Migration: inspect `git -C <historical-parent-repository> status --short` with `ros2/docs/plans/2026-05-08-ros2-workspace-cleanup.md` and `ros2/task_plan.md`; verify each moved destination before committing deletions or compatibility links.
- Existing Java backend and untracked control-station material: retain local files; root must separately review its API/hardware scope and run its existing Gradle tests before integrating that module. The simulation frontend/bridge does not require the Java service.
- Nested FishROS repositories and private FISHBOT_STATUS/maps: inspect their own Git/config boundaries; they were neither reset nor published by this task.
