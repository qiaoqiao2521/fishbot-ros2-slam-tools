# Virtual visual inspection

## Goal
Run three inspection stops and return home in MuJoCo. Capture fresh onboard RGB at each stopped pose, classify a synthetic indicator, and produce a photo-backed report.

## Scope
- Reuse FishBot contact physics, wheel odometry, AMCL and Nav2.
- Dedicated ROS domain 97 and loopback discovery; no real hardware operation.
- Three synthetic stations: green indicator, red indicator, empty panel.
- An explicit pixel classifier reads RGB only. This demonstrates the observation pipeline, not general object understanding.
- Verify action terminal results, physical pose, fresh camera frames and stationary return independently.
- Unknown/occluded/stale observations remain unknown or fail. Never substitute fixture labels for recognition.

## Plan
1. Add an inspection scene and forward RGB camera.
2. Add bounded sequential navigation, capture and reporting.
3. Test classifier negatives and task freshness/failure handling.
4. Run the complete physical simulation, inspect photos/report, verify return, and record limits.
5. Commit reviewed project changes locally. No parent remote exists.

## Status
Completed in isolated simulation. Three stations, nine fresh images and return home passed. Root owns future extensions and real-car acceptance.

## Adopted reference
Obsidian `Wiki/自动化开发范式与智能体协作.md`, “按当前任务选择验收依据”: code tests, simulated behavior and real hardware acceptance are separate claims. Actual rendered frames and MuJoCo motion are required here.
