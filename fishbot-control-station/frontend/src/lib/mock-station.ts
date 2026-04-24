import type {
  ConnectionSnapshot,
  ControlFeedbackSnapshot,
  DiagnosticSnapshot,
  NavigationSnapshot,
  PerceptionSnapshot,
  RobotStateSnapshot,
} from '@/types/station'

const now = new Date().toISOString()

export const mockConnection: ConnectionSnapshot = {
  rosbridgeConnected: true,
  robotOnline: true,
  reconnecting: false,
  lastMessageAt: now,
  endpoint: 'ws://127.0.0.1:9090',
  mode: 'fallback',
  statusLabel: 'fallback snapshot',
  controlBridge: {
    connected: true,
    telemetryOnline: true,
    lastMessageAt: now,
    endpoint: 'ws://127.0.0.1:9090',
    statusLabel: 'connected',
  },
  laserBridge: {
    connected: true,
    telemetryOnline: true,
    lastMessageAt: now,
    endpoint: 'ws://127.0.0.1:9091',
    statusLabel: 'connected',
  },
}

export const mockRobotState: RobotStateSnapshot = {
  odom: {
    x: 1.284,
    y: -0.412,
    yaw: 0.376,
    linearVelocity: 0.26,
    angularVelocity: 0.18,
  },
  imu: {
    angularVelocity: {
      x: 0.01,
      y: -0.03,
      z: 0.18,
    },
    linearAcceleration: {
      x: 0.12,
      y: -0.04,
      z: 9.81,
    },
    orientation: {
      roll: 0.02,
      pitch: -0.06,
      yaw: 0.38,
    },
  },
  messageRateHz: 18.6,
  lastUpdatedAt: now,
}

export const mockDiagnostics: DiagnosticSnapshot = {
  commands: [
    {
      id: 'cmd-3',
      level: 'info',
      message: 'cmd_vel publish linear=0.26 angular=0.18',
      timestamp: now,
    },
    {
      id: 'cmd-2',
      level: 'info',
      message: 'hold-to-run active: forward-left vector',
      timestamp: now,
    },
  ],
  errors: [
    {
      id: 'err-1',
      level: 'warning',
      message: 'No backend stream yet, using local fallback snapshot',
      timestamp: now,
    },
  ],
  transport: [
    {
      id: 'net-2',
      level: 'info',
      message: 'rosbridge heartbeat nominal',
      timestamp: now,
    },
    {
      id: 'net-1',
      level: 'info',
      message: 'SSE connected to /api/v1/stream/events',
      timestamp: now,
    },
  ],
}

export const mockNavigation: NavigationSnapshot = {
  map: {
    ready: false,
    width: 0,
    height: 0,
    resolution: 0,
    originX: 0,
    originY: 0,
    originYaw: 0,
    sampleStride: 1,
    lastUpdate: now,
    statusMessage: 'fallback map shell',
    sampledCells: [],
  },
  tf: {
    ready: false,
    mapToOdomPresent: false,
    odomToBasePresent: false,
    transformCount: 0,
    staticTransformCount: 0,
    lastUpdate: now,
    statusMessage: 'fallback tf shell',
  },
  localization: {
    ready: false,
    x: 0,
    y: 0,
    yaw: 0,
    covarianceScore: 0,
    lastUpdate: now,
    statusMessage: 'fallback localization shell',
  },
  navStatus: {
    ready: false,
    activeGoals: 0,
    totalGoals: 0,
    statusSummary: 'idle',
    lastUpdate: now,
    statusMessage: 'fallback nav shell',
  },
}

export const mockPerception: PerceptionSnapshot = {
  scan: {
    ready: true,
    frameId: 'laser_link',
    beamCount: 6,
    angleMin: -1.1,
    angleMax: 0.9,
    rangeMin: 0.12,
    rangeMax: 8,
    observedRange: 2.1,
    lastUpdate: now,
    statusMessage: 'offline scan preview',
    samplePoints: [
      { angleRad: -1.1, rangeMeters: 1.2, x: 0.54, y: -1.07 },
      { angleRad: -0.6, rangeMeters: 1.8, x: 1.49, y: -1.02 },
      { angleRad: -0.2, rangeMeters: 2.1, x: 2.06, y: -0.42 },
      { angleRad: 0.2, rangeMeters: 1.9, x: 1.86, y: 0.38 },
      { angleRad: 0.55, rangeMeters: 1.3, x: 1.11, y: 0.68 },
      { angleRad: 0.9, rangeMeters: 0.92, x: 0.57, y: 0.72 },
    ],
  },
  ultrasonic: {
    ready: true,
    sourceTopic: '/ultrasonic',
    frameId: 'ultrasonic_link',
    distanceMeters: 0.42,
    maxRangeMeters: 2,
    blocked: false,
    lastUpdate: now,
    statusMessage: 'offline ultrasonic preview',
  },
  infrared: {
    ready: true,
    sourceTopic: '/infrared',
    frameId: 'infrared_link',
    distanceMeters: 0.24,
    maxRangeMeters: 0.8,
    blocked: false,
    lastUpdate: now,
    statusMessage: 'offline infrared preview',
  },
}

export const mockControlFeedback: ControlFeedbackSnapshot = {
  holdCadenceMs: 140,
  lastCommandAt: now,
  lastStopAt: null,
  lastAckAt: now,
  lastAckMessage: 'offline simulator ack: cmd_vel forward',
  lastSequence: 12,
  throttleActive: false,
  releaseToZeroArmed: true,
}
