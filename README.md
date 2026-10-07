# FishBot

Main repository: [qiaoqiao2521/fishbot-ros2-slam-tools](https://github.com/qiaoqiao2521/fishbot-ros2-slam-tools).

One robot, one project: controller UI, ROS2 navigation, network LiDAR driver,
micro-ROS Agent sources, firmware source and staged runtime tools.

## Start here

From this checkout (no personal workspace path required):

```bash
./fishbot.sh check
./fishbot.sh stack help
./fishbot.sh teleop help
python3 tools/test_layout.py
```

check is offline only. It does not establish that ROS is built, sensors are fresh
or motion is safe. Read FISHBOT_STATUS.md before operating hardware.

## Layout

- tools/: staged startup, preflight, teleop and map saving.
- apps/fishbot-control-station/: Gradle/Spring Boot backend and React frontend.
- fishbot_nav/src/: navigation, description and bringup packages.
- fishbot_laser_ws/src/: actual Python network LiDAR driver.
- workspaces/micro_ros_agent_ws/src/: Agent and message dependencies.
- fishbot_motion_control_microros/: firmware source, not a flashed update.
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

Real mapping is incomplete. Real navigation, full passage, vehicle-side stale-command protection and camera inspection remain unaccepted. Build workspaces separately and verify current hardware readiness before any real motion. Repository synchronization does not establish additional physical acceptance.
