# FishBot Control Station

FishBot Control Station provides observation, editing, and explicit robot task controls.
Runtime identity, native execution, and independent physical results remain separate.

## Why This Stack

- `backend/`: Spring Boot 3 on Java 17, providing compatibility observation and SSE.
- `frontend/`: React + TypeScript + Vite, used for a fast operator console with clear component boundaries.
- Task commands use the existing mission, cooperation, and voice owners through fixed same-origin proxies.
- UI direction: restrained modern robotics console, not an admin dashboard and not a cheap industrial skin.

## Phase 1 Scope

- Connection status panel
- Leased manual controls require the explicit `passage_manual` ROS profile
- Odom and IMU observation panels
- Logs and diagnostics
- Expandable layout for map, navigation goals, patrol tasks, and parameter configuration

## Map Navigation

`/workbench` and `/simulation` open the same map and patrol workspace.
`/results` contains frozen results, report links, and the voice panel.
The sidebar keeps control, radar, cooperation, and evidence views accessible.

Desktop panels use Dockview. Mobile uses a canvas and bottom panels.
Panel visibility does not create, cancel, or restart a task owner.
Map edits remain drafts until explicitly saved or dispatched.

`/radar` provides 2D observation and a lazy 3D view.
The 3D view accepts bounded local URDF, GLTF/GLB, and PCD files.
Sensor-local scans stay separate from map paths when source TF is unavailable.
Legacy Java goal, initial-pose, and velocity writes are disabled by default.
Manual leases bind runtime, map, session, sequence, and command expiry.
Release, native cancellation, guard acknowledgement, and continuous quiet are reported separately.
See [runtime contracts](../../docs/RUNTIME_CONTEXT.md) and the [workbench guide](../../docs/WORKBENCH.md).

## Workspace Layout

- `backend/`: Spring Boot project, rosbridge client abstraction, REST and event streaming APIs
- `frontend/`: Vite application, operator console UI, realtime client state, reusable UI primitives
- `docs/`: architecture, API contract, and follow-up design notes

## Directory Snapshot

```text
fishbot-control-station/
  backend/
    src/main/java/com/fishbot/station/
      config/
      domain/
      ros/
      service/
      web/
    src/main/resources/application.yml
    src/test/java/com/fishbot/station/service/
  frontend/
    src/components/
      control/
      layout/
      logs/
      roadmap/
      status/
      ui/
    src/hooks/
    src/lib/
    src/store/
    src/types/
  docs/
    architecture.md
```

## Core Runtime Contract

- ROS bridge runs in the configured ROS host environment as an upstream dependency.
- Spring Boot owns rosbridge connection lifecycle, timeout detection, reconnects, and publish safety.
- Frontend never talks to rosbridge directly in phase 1.
- Legacy Java writes default to rejected. Explicit compatibility mode retains topic publication semantics, without native cancellation or verified stopping.
- Default startup is loopback-only, including the Vite proxy. There is no remote-user authentication: do not expose these services to a LAN/public network.
- Native FishBot startup defaults to Jazzy. Laser-only startup maps both backend rosbridge endpoint variables to the requested laser port.
- `/station/odom` and `/station/imu` from the HTTP diagnostic bridge must never be remapped into authoritative SLAM/EKF sensor topics.

## Expected Local Ports

- Frontend dev server: `5173`
- Backend app: `8080`
- WSL rosbridge: configurable, default `ws://127.0.0.1:9090`

## Local Startup In WSL

Install frontend dependencies once:

```bash
cd /home/muqiao/dev/ros2/projects/fishbot/apps/fishbot-control-station/frontend
npm install
```

Offline development mode:

```bash
cd /home/muqiao/dev/ros2/projects/fishbot/apps/fishbot-control-station
./scripts/dev-offline.sh
```

Online mode with rosbridge in WSL:

```bash
cd /home/muqiao/dev/ros2/projects/fishbot/apps/fishbot-control-station
./scripts/dev-online.sh
```

Direct backend-only startup:

```bash
cd /home/muqiao/dev/ros2/projects/fishbot/apps/fishbot-control-station/backend
./gradlew bootRun
```

Direct frontend-only startup:

```bash
cd /home/muqiao/dev/ros2/projects/fishbot/apps/fishbot-control-station/frontend
npm run dev -- --host 127.0.0.1
```

Offline mode is driven by `STATION_TELEMETRY_MODE=offline`. It provides synthetic observation state. Legacy control writes remain disabled unless explicitly enabled for compatibility.

## Verification

- Backend tests: `cd backend && ./gradlew test`
- Frontend production build: `cd frontend && npm run build`

See [architecture.md](docs/architecture.md) for the detailed phase 1 design and API contract.
