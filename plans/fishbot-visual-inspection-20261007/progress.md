# Progress

## Current
2026-10-07: the user-authorized simulation-first inspection passed. One command starts the isolated stack, visits three observation poses, classifies fresh RGB, returns home, writes the report and stops the owned simulation. No real hardware was operated.

## Done
- Added a robot-mounted RGB CameraPlugin and a three-station synthetic scene without changing original robot contact/mass/inertia parameters.
- Added bounded sequential Nav2 goals, source/receipt freshness, image-to-physical-pose binding, three-frame agreement, partial reports and late-ack cancellation handling.
- Final mission `run03`: completed in 73.703 s; each observation and return had action status 4/error 0. Nine photo hashes verified. States were green/green/green, red/red/red, empty/empty/empty.
- Physical XY arrival errors: 0.11477 m, 0.15368 m, 0.17696 m. Camera/physical-pose timestamp mismatch at most 0.010 s. Return XY error 0.12287 m and yaw error 0.23434 rad; continuous final stationary feedback passed.
- Negative `run04-cancel`: one-second goal deadline produced a failed report, cancellation acknowledgement, terminal status 5, and final stationary feedback. No later station dispatched. Exit 1 was expected.
- 22 inspection tests and 4 existing domain tests passed. Native MuJoCo/EGL checked unchanged physical model, nine station/tolerance views and one away view. Static view placement is not counted as navigation.
- Desktop and 390 px mobile reports rendered actual local PNGs; all three images decoded at 640 px width, with no page errors or horizontal mobile overflow.
- Native/runtime evidence is local under the chat's `work/inspection-20261007/`. Final acceptance is `run03`; cancellation is `run04-cancel`. Runtime files and images are excluded from Git.

## Remaining
No required virtual-demo work remains. General object understanding, real camera integration and charging remain future scope.

## Issues
- First startup exposed lifecycle discovery before activation; the runner now waits for ACTIVE states. Failed `run01` remains preserved.
- `run02` completed the motion/vision mission, but editing its running shell script caused a shell read-offset error at exit. Final `run03` used the unchanged final runtime files and exited 0; no simulation processes remained after cleanup.
- EGL emits one OpenGL 0x502 warning during renderer creation. Actual ROS RGB frames decoded and classified correctly. Keep the warning visible; it did not invalidate the checked renders.
- Recognition is an explicit synthetic blue-panel/indicator pixel rule, not a general visual model. Unknown frames are not converted to normal results.

## Next
Root owns follow-up at `docs/VISUAL_INSPECTION.md` and `./tools/fishbot_inspection.sh`. Root retains the parent migration handoff at `../../plans/hardware-consolidation-20260915/`: 316 preexisting tracked changes plus untracked/nested migration work remain preserved. Their cross-project move validation starts at that existing plan; this demo does not establish their delivery status. No push target is configured.
