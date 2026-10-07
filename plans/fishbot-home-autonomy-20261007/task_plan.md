# Home-map autonomous simulation

## Goal
Use the latest saved room map for a MuJoCo mission that links named-place inspection, active re-observation and battery-triggered charging.

## User intent
The user authorizes completing unknown map regions as simulation assumptions. Preserve observed cells and the original map. Operate only isolated simulation.

## Scope and acceptance
- Generate physics geometry and the navigation map from one completed occupancy grid. Record source hashes and an assumption mask.
- Keep captured room geometry and generated room-specific scenes local. Commit reusable generators and mission code only.
- Reuse wheel contact physics, AMCL, Nav2, velocity smoothing and Collision Monitor. Ground truth checks outcomes and models simulated contact sensors; it does not drive navigation or visual recognition.
- Resolve named locations from a bounded Chinese task grammar. Derive object results from fresh RGB only. A physically occluded first view must trigger another navigation viewpoint.
- Consume simulated battery energy. Low battery must cancel the active navigation, reach a dock through DockRobot, obtain simulated contact/charging feedback and increasing charge, undock and resume the pending task.
- Save timestamps, poses, photos, navigation/cancellation results, battery history and a human-readable report.
- Validate success and meaningful failure/cancellation cases. Simulation acceptance does not establish physical charging or general object understanding.

## Work allocation
Root owns launch, mission orchestration, integrated runs and serial Git delivery. Scene worker owns map completion and MJCF generation. Semantics worker owns bounded parsing, RGB interpretation and reporting. Power worker owns simulated battery/contact sensing and Nav2 docking configuration.

## Plan
1. Verify the saved input and existing runtime; establish module contracts.
2. Implement the scene, semantics, power and orchestration modules.
3. Run focused tests and build the selected workspace.
4. Run the integrated mission and failure checks in domain 98 with localhost discovery.
5. Inspect real outputs, preserve private evidence, document limits and push verified reusable source.

## Status
Complete: the map-based simulation, same-run seven-check acceptance, two negative runs and documentation are verified. Private maps and evidence remain local.

## Adopted reference
Obsidian Wiki/自动化开发范式与智能体协作, section 按当前任务选择验收依据: judge this task from simulated physical motion and fresh visual/power feedback, separately from unit tests and hardware acceptance. CapMesh inventory/community-alternatives.md favors reuse of Nav2 rather than replacing its navigation stack.
