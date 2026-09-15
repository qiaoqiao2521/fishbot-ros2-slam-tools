export type ControlDirection = 'forward' | 'backward' | 'left' | 'right' | 'stop'

export type BridgeStatusSnapshot = {
  connected: boolean
  telemetryOnline: boolean
  lastMessageAt: string
  endpoint: string
  statusLabel: string
}

export type ConnectionSnapshot = {
  rosbridgeConnected: boolean
  robotOnline: boolean
  reconnecting: boolean
  lastMessageAt: string
  endpoint: string
  mode: 'live' | 'offline' | 'fallback'
  statusLabel: string
  controlBridge: BridgeStatusSnapshot
  laserBridge: BridgeStatusSnapshot
}

export type OdomSnapshot = {
  x: number
  y: number
  yaw: number
  linearVelocity: number
  angularVelocity: number
}

export type ImuSnapshot = {
  angularVelocity: {
    x: number
    y: number
    z: number
  }
  linearAcceleration: {
    x: number
    y: number
    z: number
  }
  orientation?: {
    roll: number
    pitch: number
    yaw: number
  }
}

export type RobotStateSnapshot = {
  odom: OdomSnapshot
  imu: ImuSnapshot
  messageRateHz: number | null
  lastUpdatedAt: string
}

export type DiagnosticEntry = {
  id: string
  level: 'info' | 'warning' | 'error'
  message: string
  timestamp: string
}

export type DiagnosticSnapshot = {
  commands: DiagnosticEntry[]
  errors: DiagnosticEntry[]
  transport: DiagnosticEntry[]
}

export type MapSnapshot = {
  ready: boolean
  width: number
  height: number
  resolution: number
  originX: number
  originY: number
  originYaw: number
  sampleStride: number
  lastUpdate: string
  statusMessage: string
  sampledCells: Array<{
    x: number
    y: number
    occupancy: number
  }>
}

export type TfSnapshot = {
  ready: boolean
  mapToOdomPresent: boolean
  odomToBasePresent: boolean
  transformCount: number
  staticTransformCount: number
  lastUpdate: string
  statusMessage: string
}

export type LocalizationSnapshot = {
  ready: boolean
  x: number
  y: number
  yaw: number
  covarianceScore: number
  lastUpdate: string
  statusMessage: string
}

export type NavStatusSnapshot = {
  ready: boolean
  activeGoals: number
  totalGoals: number
  statusSummary: string
  lastUpdate: string
  statusMessage: string
}

export type NavigationSnapshot = {
  map: MapSnapshot
  tf: TfSnapshot
  localization: LocalizationSnapshot
  navStatus: NavStatusSnapshot
}

export type LaserScanPointSnapshot = {
  angleRad: number
  rangeMeters: number
  x: number
  y: number
}

export type LaserScanSnapshot = {
  ready: boolean
  frameId: string
  beamCount: number
  angleMin: number
  angleMax: number
  rangeMin: number
  rangeMax: number
  observedRange: number
  lastUpdate: string
  statusMessage: string
  samplePoints: LaserScanPointSnapshot[]
}

export type ProximitySensorSnapshot = {
  ready: boolean
  sourceTopic: string
  frameId: string
  distanceMeters: number
  maxRangeMeters: number
  blocked: boolean
  lastUpdate: string
  statusMessage: string
}

export type PerceptionSnapshot = {
  scan: LaserScanSnapshot
  ultrasonic: ProximitySensorSnapshot
  infrared: ProximitySensorSnapshot
}

export type ControlFeedbackSnapshot = {
  holdCadenceMs: number
  lastCommandAt: string | null
  lastStopAt: string | null
  lastAckAt: string | null
  lastAckMessage: string
  lastSequence: number
  throttleActive: boolean
  releaseToZeroArmed: boolean
}

export type ControlCommandPayload = {
  linearX: number
  angularZ: number
  source: string
  sequence: number
}
