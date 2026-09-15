# FishBot

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
paths above. This repository is published from the canonical local project.

## Acceptance boundary

Offline layout and dispatch tests pass. A clean build and hardware revalidation
were not performed for this publication. Historical mapping and serialization
succeeded; delayed motion, posegraph restore/localization and Nav2 remain
unresolved. Never bypass fresh-odometry motion gates.
