# FishBot

Main repository: [qiaoqiao2521/fishbot-ros2-slam-tools](https://github.com/qiaoqiao2521/fishbot-ros2-slam-tools).

One robot, one project: controller UI, ROS2 navigation, network LiDAR driver,
micro-ROS Agent sources, firmware source and staged runtime tools.

## Start here

Read [PROJECT](PROJECT.md) for current priorities, then follow the relevant plan.
Open the [results workbench](docs/WORKBENCH.md) at `/workbench` for six capability entrances and frozen acceptance evidence.
It preserves original failures and keeps tool availability separate from experiment results.
The [voice task panel](docs/VOICE.md) adds local audio recognition, text preview,
and explicit confirmation through existing ROS task owners.
New scene inputs use [SpatialLM import](experiments/spatiallm/README.md).
Two-job sequencing uses the [bounded workflow](docs/COOPERATION_WORKFLOW.md).
Both preserve separate inference, editing and physical acceptance boundaries.
See [architecture](docs/ARCHITECTURE.md) and [decisions](docs/DECISIONS.md) for context.

From this checkout (no personal workspace path required):

```bash
./fishbot.sh check
./fishbot.sh check-feedback
./fishbot.sh stack help
./fishbot.sh teleop help
./fishbot.sh voice help
python3 tools/test_layout.py
```

`check` validates layout and shell syntax. `check-feedback` runs existing offline
guard, route, mission and UI regressions. It starts no ROS graph or simulation.
Missing dependencies and skipped tests mean incomplete verification.
See [feedback workflow](docs/USER_FEEDBACK.md) for commands and remaining cases.
The physical robot was sold; the user confirmed mapping and navigation complete.

Run the [six-case simulation suite](docs/SIMULATION_SUITE.md) with `./fishbot.sh sim-suite`.
It records actual truth trajectories, moving scan faults, cancellation and old-command rejection.

The simulation extensions reuse the same ROS 2 and MuJoCo stack:

- [Localization recovery](docs/LOCALIZATION_RECOVERY.md): `./fishbot.sh localization-recovery --output <new-directory>`.
- [Object inspection](docs/OBJECT_INSPECTION.md): `./fishbot.sh object-inspection <new-directory>`.
- [Random and continuous campaigns](docs/SIMULATION_CAMPAIGN.md): `./fishbot.sh sim-campaign --mode random` or `--mode soak`.
- [Web runtime acceptance](docs/WEB_RUNTIME_ACCEPTANCE.md): isolated Goal dispatch, cancellation and observed Collision Monitor states.
- [Map rules and route templates](docs/MAP_RULES.md): edit software keepouts, save routes, and inspect actual task records in `/simulation`.
- [Fixed SO101 cooperation](docs/COOPERATION.md): share one physical world, dock, load a free payload, and transport it through `/cooperation`.
  Rear RGB AprilTag docking, optional dock-only tasks, and a frozen acceptance panel reuse the same stack.
  Current native and physical results are recorded in the [visual docking progress](plans/visual-docking-robustness-20261014/progress.md).

The optional [Arena evaluation deployment](experiments/arena/README.md) provides
pinned upstream preparation and a two-condition policy evaluation configuration.
Run `./fishbot.sh arena doctor` before installing its separate Isaac Sim stack.
The licensed Colab L4 run completed native execution, evidence recovery, and resource release.
Both zero-action task results were false; policy training and SO101 adaptation remain unverified.
See the [Arena progress](plans/fishbot-arena-evaluation-20261014/progress.md) for evidence and limits.

## Layout

- tools/: staged startup, preflight, teleop and map saving.
- apps/fishbot-control-station/: Gradle/Spring Boot backend and React frontend.
- fishbot_nav/src/: navigation, description and bringup packages.
- fishbot_laser_ws/src/: actual Python network LiDAR driver.
- workspaces/micro_ros_agent_ws/src/: Agent and message dependencies.
- fishbot_motion_control_microros/: firmware source and [clock repair](docs/FIRMWARE_TIME_SYNC.md).
- fishbot-web-panel/: phone PWA for live telemetry and safe jog teleop
  (absorbed from ros2-mobile-panel-day1; FastAPI + prebuilt assets in one
  uvicorn process, default port 8010).

## Virtual navigation and inspection

On a ROS 2 Jazzy workstation, prepare the extracted runtime and selected workspace:

```bash
./tools/fishbot_mujoco_bootstrap.py
./tools/fishbot_mujoco.sh build
./tools/fishbot_inspection.sh
```

The inspection command runs three observation goals and returns home in isolated domain 97. Its HTML report contains actual onboard RGB images, pixel observations and physical pose/stop evidence. See [visual inspection](docs/VISUAL_INSPECTION.md) for scope and validation. The existing [web patrol](workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/README.md) uses domain 93; [passage control](docs/PASSAGE_CONTROL.md) has its own isolated acceptance.

The [home autonomy simulation](tools/README_FISHBOT_HOME.md) uses a private local map in isolated domain 98. One complete mission verified named-place inspection, active observation, charging, task resumption and return home. Unknown map regions are explicit assumptions; visual targets and charging feedback are simulated.

## Mobile panel

```bash
./fishbot.sh stack start-web      # or: it starts automatically with stack start/start-slam/start-nav
```

Open `http://<host-ip>:8010` from a phone on the same LAN. Shows `/odom`,
`/scan`, `/map` plus serial heartbeat when enabled (`SERIAL_ENABLED=true` on
hosts that have the bottom-board serial). Jog commands carry a deadman token
with a 300 ms TTL: release, page-hide or disconnect all stop the robot, and
stale/replayed commands are rejected server-side. Limits: 0.2 m/s, 0.8 rad/s.
The web panel never replaces a physical e-stop.

Build workspaces separately; never run a whole-repository colcon build.
Dependency origins/revisions are in docs/DEPENDENCIES.md.
This update excludes private maps, posegraphs, flash backups and runtime data.
Historical already-published maps remain in Git history.

Former ros2-tools, fishbot-control-station and fishbot-nav-src have moved to the
paths above. The canonical development checkout directly tracks this repository; see [repository continuity](docs/REPOSITORY.md).

## Acceptance boundary

Synthetic MuJoCo navigation, patrol, passage and visual-inspection evidence is recorded in the project plans. The inspection fixture completed three stations and return in 73.703 seconds, with nine fresh photos and a 0.12287 m return error. Its classifier is limited to synthetic indicator panels.

The separate object-inspection fixture runs local YOLO11n on actual camera RGB. It completed seven navigation actions and captured eighteen images. Cup/laptop detection, an alternate occluded view, and return passed; return error was 0.09044 m.

Missing detections remain unknown. Its image-position gate is 0.22 m; this is not a real-world accuracy benchmark. See [object inspection](docs/OBJECT_INSPECTION.md).

The user accepted the latest measured map as this scene's working map; unknown cells remain unknown. Fixed-map outbound and a resumed return passed fresh stopping feedback. A [single continuous map-route entry](docs/PASSAGE_CONTROL.md) avoids intermediate stop-and-observe loops.

The user closed the physical stage on 2026-10-11 after selling the robot.
Historical limits remain: complete-route patrol, full passage, vehicle-side stale-command protection and camera inspection lack physical acceptance.
Sustained native freshness remains unresolved. These limits do not reopen physical work.
Offline regressions and repository synchronization establish no additional physical acceptance.
