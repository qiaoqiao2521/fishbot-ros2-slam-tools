# MuJoCo visual inspection

Run three observation goals, capture onboard RGB, identify synthetic indicator states, and return home. The implementation uses wheel contact physics, AMCL and Nav2. It operates only in ROS domain 97 with local discovery.

## Run

Build the selected workspace once:

```bash
./tools/fishbot_mujoco.sh build
```

Run the full mission:

```bash
./tools/fishbot_inspection.sh
```

The script creates a dated directory under `workspaces/fishbot_mujoco_ws/.runs/`. It stops its own simulation process group after success or failure. To select a location, pass a new directory as the first argument. Existing directories are refused.

Open `index.html` to see the route, photos, observations, return result and final stop result. `report.json` preserves action status, image hashes, source timestamps and physical pose evidence. Each station retains three PNG frames. Raw launch logs remain in the same local directory.

To exercise cancellation, choose a new directory and append `--goal-timeout 1`. The result should remain failed, with cancellation and stationary feedback recorded. The timeout applies to each navigation goal, measured in wall time.

## Data flow

`Named observation pose → NavigateToPose → stationary arrival → three fresh RGB frames → pixel classifier → report → next goal → return home`

Navigation retains the previously accepted simulation chain: Nav2 → velocity smoother → Collision Monitor → stamped diff-drive controller. This demo uses AMCL. It does not replace localization with MuJoCo ground truth or change the real-car pipeline.

The robot-mounted `inspection_camera` publishes RGB8 images at 640×480 and 5 Hz. Its optical frame is `inspection_camera_optical_frame`; the RGB topic is `/inspection/camera/image_raw`. The camera sits at `(0.06, 0, 0.168)` relative to `base_link` and faces the robot's forward direction. An explicit CameraPlugin runs only in the inspection scene; the original arena defaults remain unchanged.

The three goals and their questions are in `tools/config/fishbot_inspection_route.json`. Their coordinates are navigation requests, not recognition answers. The recognizer accepts only RGB arrays. It checks a complete blue frame and dark inner panel before classifying green, red or empty. Multiple panels, clipping, missing frames, conflicting colors and small uncertain indicators return `unknown`.

## Acceptance boundary

- Require Nav2 `SUCCEEDED` and error code zero at every observation and return goal.
- Require fresh wheel odometry and independent MuJoCo pose, plus stationary feedback.
- Require image timestamps after arrival and fresh source/receipt times.
- Bind every image to a physical pose within 120 ms. Require XY error at most 22 cm, yaw error at most 0.25 rad and planar/yaw speed components at most 0.015.
- Require three consistent frame classifications. Unknown observations remain visible and make the report `completed_with_unknown`, not a fully accepted inspection.
- Save partial reports on failure. Late goal acknowledgement retains cancellation intent. The owner script stops the isolated stack during cleanup.

This is a synthetic indicator demonstration. It does not establish general object recognition, household clutter detection, real camera availability or real-car navigation. The next extension can replace the RGB classifier while retaining capture freshness, pose evidence and reporting.

## Checks and continuity

```bash
/usr/bin/python3 -m unittest discover -s tools/tests -p 'test_inspection*.py' -v
/usr/bin/python3 -m unittest discover -s workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/tests -p 'test_sim_domain.py' -v
```

The optional native test at `workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/tests/test_inspection_camera.cpp` checks model preservation and static camera sight lines using the extracted MuJoCo library and EGL. Its static body placement is not navigation evidence.

Current measurements and handoff: [task progress](../plans/fishbot-visual-inspection-20261007/progress.md).
