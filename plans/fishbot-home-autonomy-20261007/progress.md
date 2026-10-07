# Progress

## Current
Complete within the requested virtual scope. Trial 13 passed all seven closed-loop checks in isolated ROS domain 98.

## Done
- Preserved 3377 observed map cells. Explicit assumptions complete unknown space; one grid defines navigation occupancy and physical walls.
- Completed named-place inspection, physical viewpoint change after occlusion, and RGB-only recognition from 12 fresh frames.
- Verified low-battery cancellation, simulated contact/current/SOC charging, undocking and successful navigation back to the interrupted view.
- Returned home and stopped. The full run took 328.336 s; final physical position error was 0.11063 m and yaw error was 0.17623 rad.
- Independently rechecked images, poses, action transitions, battery history, original pixels and all seven required fields.
- Disabled charging with a 0.35 low-SOC test threshold. Contact became true, charge gain stayed zero, docking failed with code 906, and stationary termination passed.
- Imposed a 1 s navigation deadline with a 0.05 low-SOC threshold. Cancellation reached status 5 and physical stop passed.
- Passed 204 tool tests without skips, source syntax and documentation-link checks. The selected MuJoCo workspace build passed during this task.
- Recorded runtime source hashes and kept failed trials, diagnostics, successful photos and camera recording outside the public source tree.

## Remaining
No implementation or simulation acceptance work remains for this scenario. The result does not establish general object recognition or real-vehicle charging/navigation.

## Issues
The preexisting nested firmware release script remains local and unverified. Root Codex owns its pinned-toolchain build and dependency review; see the remote-connection progress note. No release or flashing was attempted.

The outer development repository retains its existing changes and original HEAD. Its current 327 tracked differences comprise 316 other paths and 11 FishBot paths; its index and history were not integrated here.

## Next
Reproduce with `tools/fishbot_home.sh` and a private source map. Use the local report, independent verification and runtime source manifest together. Preserve the hardware acceptance boundary.
