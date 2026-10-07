# FishBot MuJoCo integration

## Goal
Reproduce BCR Bot's ROS 2 Jazzy + MuJoCo wheel physics and Nav2 in an isolated simulation, then reuse the existing FishROS model for a FishBot variant.

## Scope and acceptance
- Pin BCR upstream and ROS binary versions; keep existing workspaces and hardware untouched.
- Validate real MuJoCo wheel/contact motion, fresh LaserScan/odom/TF, then a successful NavigateToPose action with measured final pose error.
- Adapt the FishROS physical model rather than inventing robot geometry. Educational inertials are not physical calibration.
- Provide runnable commands and bounded evidence. No firmware flashing, physical movement, real maps upload, control-console redesign or command arbitration in this task.

## Plan
1. [done] Bootstrap local extracted dependencies and pinned BCR reference.
2. [done] Verify BCR headless wheel/sensor stack and navigation.
3. [done] Integrate FishROS-derived MJCF, isolated ROS control, and RPP navigation.
4. [done] Independently review evidence, document runnable entry and publication boundaries, and preserve a selective local source commit.

## Implementation decision
FishBot MPPI stalled near the final pose; preserve it as an experimental profile. The accepted default uses existing Nav2 RPP. Final acceptance on 2026-10-04: obstacle-avoiding goal (2,1), action status 4/error 0, physical XY error 0.1333 m, yaw error 0.0566 rad, final speed near zero. Timeout and 10 s old stamped-command rejection also passed.

## Knowledge applied
Reuse mature Nav2 and an existing integrated simulator instead of implementing another navigation stack (CapMesh community alternatives / development knowledge entry, consulted during selection). Sensor/TF ownership must be explicit: a localization node owns map→odom.
