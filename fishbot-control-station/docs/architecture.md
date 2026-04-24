# FishBot Control Station Architecture

## 1. System Architecture Design

Phase 1 keeps the topology simple:

`Browser UI <-> Spring Boot Gateway <-> rosbridge websocket <-> ROS topics`

Spring Boot stays in the middle for three reasons:

1. It isolates the browser from direct ROS protocol concerns and WSL networking details.
2. It centralizes motion safety logic, reconnects, timeouts, and emergency stop semantics.
3. It creates a stable application API that can stay unchanged when the UI is later wrapped as a desktop app.

If the stack were re-evaluated from scratch, a lighter Node gateway could reduce implementation cost. It is not a better fit here because the long-term requirement is a durable control console with stricter control semantics, service layering, and future integration points. Keeping Spring Boot as the control gateway is reasonable.

## 2. Phase 1 Functional Layout

The UI is intentionally split into four zones:

- Header status bar: ROS bridge connectivity, robot liveness, last message timestamp, WSL endpoint
- Main control surface: directional movement, speed sliders, emergency stop, keyboard hinting
- Robot observation zone: odom, imu, timestamps, message freshness, stream cadence
- Diagnostics zone: recent commands, errors, rosbridge events, debug placeholders

The second phase remains visible but not implemented:

- Map panel slot
- Navigation goal slot
- Task and patrol slot
- Parameter configuration slot

## 3. Backend Module Boundaries

- `config`: app properties, websocket client config, CORS and SSE settings
- `domain`: immutable DTOs for connection status, robot state, control requests, logs
- `ros`: rosbridge client abstraction and reconnect logic
- `service`: command publishing, topic subscription handling, snapshot aggregation, log ring buffers
- `web`: REST controllers and event streaming endpoints

Key services:

- `RosbridgeClient`: low-level websocket lifecycle and raw message send/receive
- `RosTopicService`: subscribe/publish orchestration for `/cmd_vel`, `/odom`, `/imu`
- `RobotStateService`: holds latest robot snapshot, liveness state, timestamps, derived telemetry
- `ControlService`: validates and publishes teleop commands, stop, emergency stop
- `DiagnosticsService`: recent commands, errors, rosbridge log buffer

## 4. Frontend Module Boundaries

- `app shell`: layout and page composition
- `features/control`: motion input surface and safety interactions
- `features/status`: connection, odom, imu, and freshness cards
- `features/logs`: command history, errors, transport logs
- `shared/ui`: shadcn-style primitives and local visual wrappers
- `shared/state`: websocket or SSE subscription state, query layer, optimistic control feedback

The UI should feel like an operator station:

- graphite and warm-neutral base surfaces
- controlled accent colors for connection, warning, and emergency states
- restrained motion on state transitions, not decorative animation
- dense enough for operators, but not overloaded

## 5. API Contract

### REST

- `GET /api/v1/connection`
  - returns current rosbridge and robot connection snapshot
- `GET /api/v1/state`
  - returns latest aggregated robot state snapshot
- `GET /api/v1/diagnostics`
  - returns recent commands, errors, and rosbridge transport logs
- `POST /api/v1/control/cmd-vel`
  - body:
    - `linearX`
    - `angularZ`
    - `source`
    - `sequence`
- `POST /api/v1/control/stop`
  - publishes zeroed velocity and marks stop reason
- `POST /api/v1/control/emergency-stop`
  - immediate zeroed velocity publish with dedicated audit trail

### Event Stream

- `GET /api/v1/stream/events`
  - SSE channel used by the frontend for connection and robot state updates
  - event types:
    - `connection`
    - `robot-state`
    - `diagnostic`

## 6. Safety Rules

- `cmd_vel` values are clamped server-side.
- hold-to-run behavior is implemented in the frontend, but stop-on-release is backed by explicit backend stop actions.
- emergency stop is its own endpoint and should bypass any queued command intent.
- connection loss marks robot status as stale and the UI shifts into a guarded state.

## 7. Directory Structure

```text
fishbot-control-station/
  backend/
    src/main/java/com/fishbot/station/
    src/main/resources/
    src/test/java/com/fishbot/station/
  frontend/
    src/components/
    src/hooks/
    src/lib/
    src/store/
    src/test/
    src/types/
  docs/
    architecture.md
```

## 8. Local Startup Shape

Phase 1 local startup is intentionally simple:

1. Start rosbridge in WSL
2. Start Spring Boot backend
3. Start Vite frontend

The backend owns the WSL rosbridge URL through config so the frontend only needs the backend base URL.
