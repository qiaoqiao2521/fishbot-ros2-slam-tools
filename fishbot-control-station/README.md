# FishBot Control Station

FishBot Control Station is a web-first robot control console for FishBot. It replaces keyboard-first teleoperation with a safer, stateful operator surface that can evolve into a desktop shell later without changing the core frontend or backend architecture.

## Why This Stack

- `backend/`: Spring Boot 3 on Java 17, used as the control gateway between the browser and ROS bridge in WSL.
- `frontend/`: React + TypeScript + Vite, used for a fast operator console with clear component boundaries.
- Real-time flow: Browser -> Spring Boot -> rosbridge websocket.
- UI direction: restrained modern robotics console, not an admin dashboard and not a cheap industrial skin.

## Phase 1 Scope

- Connection status panel
- Motion control panel with hold-to-run and dedicated emergency stop
- Odom and IMU observation panels
- Logs and diagnostics
- Expandable layout for map, navigation goals, patrol tasks, and parameter configuration

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

- ROS bridge runs in WSL and is treated as an upstream dependency.
- Spring Boot owns rosbridge connection lifecycle, timeout detection, reconnects, and publish safety.
- Frontend never talks to rosbridge directly in phase 1.
- Emergency stop remains a dedicated backend action and publishes a zeroed `cmd_vel` immediately.

## Expected Local Ports

- Frontend dev server: `5173`
- Backend app: `8080`
- WSL rosbridge: configurable, default `ws://127.0.0.1:9090`

## Local Startup In WSL

Install frontend dependencies once:

```bash
cd /home/muqiao/dev/fishbot-control-station/frontend
npm install
```

Offline development mode:

```bash
cd /home/muqiao/dev/fishbot-control-station
./scripts/dev-offline.sh
```

Online mode with rosbridge in WSL:

```bash
cd /home/muqiao/dev/fishbot-control-station
./scripts/dev-online.sh
```

Direct backend-only startup:

```bash
cd /home/muqiao/dev/fishbot-control-station/backend
./gradlew bootRun
```

Direct frontend-only startup:

```bash
cd /home/muqiao/dev/fishbot-control-station/frontend
npm run dev -- --host 0.0.0.0
```

Offline mode is driven by `STATION_TELEMETRY_MODE=offline`. In that mode the backend publishes synthetic `/odom` and `/imu`-like state, and control commands move the simulated robot state without requiring rosbridge or a powered robot.

## Verification

- Backend tests: `cd backend && .\gradlew.bat test`
- Frontend production build: `cd frontend && npm run build`

See [architecture.md](E:\web\fishbot-control-station\docs\architecture.md) for the detailed phase 1 design and API contract.
