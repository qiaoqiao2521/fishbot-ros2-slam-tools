# FishBot web patrol and physical obstacle demo

## Goal
Make the existing control station operate the isolated MuJoCo robot: select three map locations, run a real multi-waypoint patrol, encounter a physical moving obstacle, stop/wait or avoid it, complete the route and return home.

## Scope and acceptance
- Simulation only: localhost HTTP and ROS domain 93. No hardware teleoperation, firmware changes, room-map upload or new repository.
- Reuse the existing React control station and Nav2 FollowWaypoints; preserve old console/radar and Java telemetry behavior.
- The browser sends real mission/cancel requests and displays action feedback, actual map/pose/path and truthful readiness.
- Dynamic obstacle must exist in MuJoCo contacts and rangefinder data, with fresh physical state as evidence. Robot remains wheel/contact driven.
- Startup has a bounded readiness gate; RViz opens only after sensors, clock, TF and navigation lifecycle nodes are ready.
- Verify frontend checks, HTTP/ROS errors and cancellation, browser click-to-dispatch, actual complete patrol and measured obstacle response/resumed motion. Save user-visible screenshots and an excerpt assembled from the actual browser captures; distinguish this from a continuous recording.

## Plan
1. [complete] Record baseline and contracts; delegate frontend, ROS bridge and physics/readiness.
2. [complete] Integrate selected workspace launch, entry tools and camera framing.
3. [complete] Build/test and validate mission, cancellation and moving-obstacle behavior.
4. [complete] Browser acceptance, captured-frame excerpt, documentation and selective local Git closeout. No parent remote exists; publication remains in the recoverable handoff.

## Coordination
- Root: contracts, CMake/launch/nav config, entry tools, integration, browser/physical acceptance and serial Git closeout.
- patrol_ui: frontend source/config/tests only.
- patrol_bridge: mission_bridge.py and its tests only.
- patrol_physics: arena.xml, plugins.yaml, obstacle_controller.py, wait_ready.py and scoped tests only.

## Knowledge adopted
Use existing capability and verify actual task behavior separately from builds. Source: Obsidian Wiki development entry / automation collaboration acceptance guidance; existing FishBot MuJoCo and console source. The old console's navigation actions are local previews, not real goal dispatch. Prior GUI startup response loss requires readiness-based sequencing, not a longer arbitrary timer.

## Publication boundary
The actual source is under parent Git `<historical-parent-repository>`, which has no remote. Preserve the existing 316 tracked migration changes, private maps/config and nested FishROS Git. Root owns recoverable handoff for pending migration/publication; do not push to third-party or archived-account remotes.
