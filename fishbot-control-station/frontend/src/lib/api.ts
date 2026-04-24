import type {
  BridgeStatusSnapshot,
  ConnectionSnapshot,
  ControlCommandPayload,
  DiagnosticEntry,
  DiagnosticSnapshot,
  NavigationSnapshot,
  PerceptionSnapshot,
  RobotStateSnapshot,
} from '@/types/station'

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
    throw new Error(`Request failed: ${path}`)
  }

  return (await response.json()) as T
}

export type RawConnectionSnapshot = {
  rosbridgeConnected: boolean
  robotOnline: boolean
  rosbridgeUrl: string
  lastMessage: string
  statusMessage: string
  controlBridge?: RawBridgeConnectionSnapshot
  laserBridge?: RawBridgeConnectionSnapshot
}

export type RawBridgeConnectionSnapshot = {
  connected: boolean
  telemetryOnline: boolean
  endpoint: string
  lastMessage: string
  statusMessage: string
}

export type RawRobotStateSnapshot = {
  x: number
  y: number
  yaw: number
  roll?: number
  pitch?: number
  linearVelocity: number
  angularVelocity: number
  accelX: number
  accelY: number
  accelZ: number
  angularVelX: number
  angularVelY: number
  angularVelZ: number
  timestamp: string
}

export type RawDiagnosticEntry = {
  timestamp: string
  source: string
  message: string
  severity: string
}

export type RawDiagnosticSnapshot = {
  generatedAt: string
  entries: RawDiagnosticEntry[]
}

export type RawMapSnapshot = NavigationSnapshot['map']
export type RawTfSnapshot = NavigationSnapshot['tf']
export type RawLocalizationSnapshot = NavigationSnapshot['localization']
export type RawNavStatusSnapshot = NavigationSnapshot['navStatus']

export type RawNavigationSnapshot = {
  map: RawMapSnapshot
  tf: RawTfSnapshot
  localization: RawLocalizationSnapshot
  navStatus: RawNavStatusSnapshot
}

export type RawPerceptionSnapshot = PerceptionSnapshot

export function mapConnectionSnapshot(raw: RawConnectionSnapshot): ConnectionSnapshot {
  const offline = raw.statusMessage === 'offline-sim' || raw.rosbridgeUrl.startsWith('offline://')
  const controlBridge = mapBridgeSnapshot(raw.controlBridge, {
    connected: raw.rosbridgeConnected,
    telemetryOnline: raw.robotOnline,
    endpoint: raw.rosbridgeUrl,
    lastMessage: raw.lastMessage,
    statusMessage: raw.statusMessage,
  })
  const laserBridge = mapBridgeSnapshot(raw.laserBridge, {
    connected: false,
    telemetryOnline: false,
    endpoint: 'ws://127.0.0.1:9091/',
    lastMessage: raw.lastMessage,
    statusMessage: 'disconnected',
  })

  return {
    rosbridgeConnected: raw.rosbridgeConnected,
    robotOnline: raw.robotOnline,
    reconnecting: !offline && raw.statusMessage.toLowerCase().includes('reconnect'),
    lastMessageAt: raw.lastMessage,
    endpoint: raw.rosbridgeUrl,
    mode: offline ? 'offline' : 'live',
    statusLabel: offline ? 'offline simulator' : raw.statusMessage,
    controlBridge,
    laserBridge,
  }
}

function mapBridgeSnapshot(
  raw: RawBridgeConnectionSnapshot | undefined,
  fallback: RawBridgeConnectionSnapshot,
): BridgeStatusSnapshot {
  const value = raw ?? fallback
  return {
    connected: value.connected,
    telemetryOnline: value.telemetryOnline,
    lastMessageAt: value.lastMessage,
    endpoint: value.endpoint,
    statusLabel: value.statusMessage,
  }
}

export function mapRobotStateSnapshot(raw: RawRobotStateSnapshot): RobotStateSnapshot {
  const messageRateHz = Math.max(1, Number((1000 / 120).toFixed(1)))

  return {
    odom: {
      x: raw.x,
      y: raw.y,
      yaw: raw.yaw,
      linearVelocity: raw.linearVelocity,
      angularVelocity: raw.angularVelocity,
    },
    imu: {
      angularVelocity: {
        x: raw.angularVelX,
        y: raw.angularVelY,
        z: raw.angularVelZ,
      },
      linearAcceleration: {
        x: raw.accelX,
        y: raw.accelY,
        z: raw.accelZ,
      },
      orientation: {
        roll: raw.roll ?? 0,
        pitch: raw.pitch ?? 0,
        yaw: raw.yaw,
      },
    },
    messageRateHz,
    lastUpdatedAt: raw.timestamp,
  }
}

function toEntry(raw: RawDiagnosticEntry, prefix: string): DiagnosticEntry {
  return {
    id: `${prefix}-${raw.timestamp}-${raw.source}`,
    level:
      raw.severity === 'ERROR'
        ? 'error'
        : raw.severity === 'WARN'
          ? 'warning'
          : 'info',
    message: raw.message,
    timestamp: raw.timestamp,
  }
}

export function mapDiagnosticSnapshot(raw: RawDiagnosticSnapshot): DiagnosticSnapshot {
  return {
    commands: raw.entries
      .filter((entry) => entry.source.toLowerCase().includes('control'))
      .map((entry) => toEntry(entry, 'command')),
    errors: raw.entries
      .filter((entry) => entry.severity === 'ERROR')
      .map((entry) => toEntry(entry, 'error')),
    transport: raw.entries
      .filter((entry) => !entry.source.toLowerCase().includes('control'))
      .map((entry) => toEntry(entry, 'transport')),
  }
}

export function mapNavigationSnapshot(raw: RawNavigationSnapshot): NavigationSnapshot {
  return {
    map: raw.map,
    tf: raw.tf,
    localization: raw.localization,
    navStatus: raw.navStatus,
  }
}

export function mapPerceptionSnapshot(raw: RawPerceptionSnapshot): PerceptionSnapshot {
  return raw
}

export function fetchConnection() {
  return getJson<RawConnectionSnapshot>('/api/v1/connection').then(mapConnectionSnapshot)
}

export function fetchRobotState() {
  return getJson<RawRobotStateSnapshot>('/api/v1/state').then(mapRobotStateSnapshot)
}

export function fetchDiagnostics() {
  return getJson<RawDiagnosticSnapshot>('/api/v1/diagnostics').then(mapDiagnosticSnapshot)
}

export function fetchNavigation() {
  return getJson<RawNavigationSnapshot>('/api/v1/navigation').then(mapNavigationSnapshot)
}

export function fetchPerception() {
  return getJson<RawPerceptionSnapshot>('/api/v1/perception').then(mapPerceptionSnapshot)
}

export async function postCommand(payload: ControlCommandPayload) {
  const response = await fetch('/api/v1/control/cmd-vel', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    throw new Error('Failed to publish cmd_vel')
  }
}

export async function postStop(path: '/api/v1/control/stop' | '/api/v1/control/emergency-stop') {
  const response = await fetch(path, {
    method: 'POST',
  })

  if (!response.ok) {
    throw new Error(`Failed to call ${path}`)
  }
}
