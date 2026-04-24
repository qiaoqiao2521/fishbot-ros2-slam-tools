import { describe, expect, it } from 'vitest'

import type {
  ConnectionSnapshot,
  ControlFeedbackSnapshot,
  DiagnosticSnapshot,
  NavigationSnapshot,
  PerceptionSnapshot,
  RobotStateSnapshot,
} from '@/types/station'
import {
  buildExportSnapshot,
  getMapDataSections,
  getMapShellPresentation,
  getModePresentation,
  getNavigationSlots,
} from '@/lib/station-runtime'

const connection: ConnectionSnapshot = {
  rosbridgeConnected: true,
  robotOnline: true,
  reconnecting: false,
  lastMessageAt: '2026-03-18T02:00:00.000Z',
  endpoint: 'offline://simulator',
  mode: 'offline',
  statusLabel: 'offline simulator',
  controlBridge: {
    connected: true,
    telemetryOnline: true,
    lastMessageAt: '2026-03-18T02:00:00.000Z',
    endpoint: 'offline://control',
    statusLabel: 'offline simulator',
  },
  laserBridge: {
    connected: true,
    telemetryOnline: true,
    lastMessageAt: '2026-03-18T02:00:00.000Z',
    endpoint: 'offline://laser',
    statusLabel: 'offline simulator',
  },
}

const robotState: RobotStateSnapshot = {
  odom: {
    x: 1.2,
    y: -0.4,
    yaw: 0.5,
    linearVelocity: 0.3,
    angularVelocity: 0.1,
  },
  imu: {
    angularVelocity: { x: 0, y: 0, z: 0.1 },
    linearAcceleration: { x: 0.2, y: 0, z: 9.81 },
    orientation: { roll: 0, pitch: 0, yaw: 0.5 },
  },
  messageRateHz: 12.5,
  lastUpdatedAt: '2026-03-18T02:00:00.000Z',
}

const diagnostics: DiagnosticSnapshot = {
  commands: [{ id: '1', level: 'info', message: 'cmd_vel', timestamp: '2026-03-18T02:00:00.000Z' }],
  errors: [],
  transport: [{ id: '2', level: 'info', message: 'offline', timestamp: '2026-03-18T02:00:00.000Z' }],
}

const navigation: NavigationSnapshot = {
  map: {
    ready: true,
    width: 384,
    height: 256,
    resolution: 0.05,
    originX: -3.9,
    originY: -1.82,
    originYaw: 0,
    sampleStride: 2,
    lastUpdate: '2026-03-18T02:00:00.000Z',
    statusMessage: 'live occupancy grid',
    sampledCells: [
      { x: 0, y: 0, occupancy: 0 },
      { x: 2, y: 0, occupancy: 100 },
      { x: 2, y: 2, occupancy: 64 },
    ],
  },
  tf: {
    ready: true,
    mapToOdomPresent: true,
    odomToBasePresent: true,
    transformCount: 2,
    staticTransformCount: 1,
    lastUpdate: '2026-03-18T02:00:00.000Z',
    statusMessage: 'tf graph observed',
  },
  localization: {
    ready: true,
    x: 2.4,
    y: -1.2,
    yaw: 0.785,
    covarianceScore: 0.16,
    lastUpdate: '2026-03-18T02:00:00.000Z',
    statusMessage: 'amcl pose locked',
  },
  navStatus: {
    ready: true,
    activeGoals: 1,
    totalGoals: 3,
    statusSummary: 'EXECUTING:1, SUCCEEDED:1, ABORTED:1',
    lastUpdate: '2026-03-18T02:00:00.000Z',
    statusMessage: 'nav action status observed',
  },
}

const perception: PerceptionSnapshot = {
  scan: {
    ready: true,
    frameId: 'laser_link',
    beamCount: 6,
    angleMin: -1.1,
    angleMax: 0.9,
    rangeMin: 0.12,
    rangeMax: 8,
    observedRange: 2.1,
    lastUpdate: '2026-03-18T02:00:00.000Z',
    statusMessage: 'offline scan preview',
    samplePoints: [{ angleRad: 0, rangeMeters: 1.2, x: 1.2, y: 0 }],
  },
  ultrasonic: {
    ready: true,
    sourceTopic: '/ultrasonic',
    frameId: 'ultrasonic_link',
    distanceMeters: 0.42,
    maxRangeMeters: 2,
    blocked: false,
    lastUpdate: '2026-03-18T02:00:00.000Z',
    statusMessage: 'offline ultrasonic preview',
  },
  infrared: {
    ready: true,
    sourceTopic: '/infrared',
    frameId: 'infrared_link',
    distanceMeters: 0.24,
    maxRangeMeters: 0.8,
    blocked: false,
    lastUpdate: '2026-03-18T02:00:00.000Z',
    statusMessage: 'offline infrared preview',
  },
}

const controlFeedback: ControlFeedbackSnapshot = {
  holdCadenceMs: 140,
  lastCommandAt: '2026-03-18T02:00:00.000Z',
  lastStopAt: null,
  lastAckAt: '2026-03-18T02:00:00.000Z',
  lastAckMessage: 'offline simulator ack: cmd_vel forward',
  lastSequence: 12,
  throttleActive: false,
  releaseToZeroArmed: true,
}

describe('station runtime helpers', () => {
  it('builds an export payload with runtime metadata', () => {
    const snapshot = buildExportSnapshot(connection, robotState, navigation, perception, diagnostics, controlFeedback, false)

    expect(snapshot.mode).toBe('offline')
    expect(snapshot.connection.endpoint).toBe('offline://simulator')
    expect(snapshot.robotState.odom.x).toBe(1.2)
    expect(snapshot.navigation.map.width).toBe(384)
    expect(snapshot.perception.scan.frameId).toBe('laser_link')
    expect(snapshot.diagnostics.commands).toHaveLength(1)
    expect(snapshot.controlFeedback.lastSequence).toBe(12)
  })

  it('describes offline mode distinctly from fallback mode', () => {
    const offline = getModePresentation(connection, false)
    const fallback = getModePresentation({ ...connection, mode: 'fallback' }, true)

    expect(offline.label).toBe('offline simulator')
    expect(offline.summary).toContain('无车开发')
    expect(fallback.label).toBe('fallback snapshot')
    expect(fallback.tone).toBe('warning')
  })

  it('marks nav slots as waiting for live telemetry in offline mode', () => {
    const slots = getNavigationSlots(connection, navigation, false)

    expect(slots[0].status).toBe('simulated input')
    expect(slots[1].status).toBe('waiting live nav2')
  })

  it('builds a bounded map shell marker and offline heading summary', () => {
    const map = getMapShellPresentation(connection, robotState, navigation, false)

    expect(map.label).toBe('simulated pose')
    expect(map.robotPercentX).toBeGreaterThanOrEqual(8)
    expect(map.robotPercentX).toBeLessThanOrEqual(92)
    expect(map.robotPercentY).toBeGreaterThanOrEqual(8)
    expect(map.robotPercentY).toBeLessThanOrEqual(92)
    expect(map.headingLabel).toContain('deg')
  })

  it('describes map data readiness without pretending live map feeds exist', () => {
    const offlineSections = getMapDataSections(connection, navigation, false)
    const liveSections = getMapDataSections(
      { ...connection, mode: 'live', robotOnline: true, endpoint: 'ws://robot' },
      navigation,
      false,
    )

    expect(offlineSections).toHaveLength(4)
    expect(offlineSections[0].status).toBe('simulated pose stream')
    expect(offlineSections[1].hooks).toContain('/tf_static')
    expect(offlineSections[2].detail).toContain('AMCL')

    expect(liveSections[0].status).toContain('384x256')
    expect(liveSections[0].status).toContain('stride 2')
    expect(liveSections[1].status).toContain('2 transforms')
    expect(liveSections[2].status).toContain('cov')
    expect(liveSections[3].status).toContain('EXECUTING')
    expect(liveSections[3].hooks).toContain('/global_costmap/costmap')
  })

  it('prefers localization pose and live nav readiness when navigation data is available', () => {
    const liveMap = getMapShellPresentation(
      { ...connection, mode: 'live', robotOnline: true, endpoint: 'ws://robot' },
      robotState,
      navigation,
      false,
    )
    const slots = getNavigationSlots(
      { ...connection, mode: 'live', robotOnline: true, endpoint: 'ws://robot' },
      navigation,
      false,
    )

    expect(liveMap.label).toBe('amcl pose lock')
    expect(liveMap.caption).toContain('真实地图坐标')
    expect(slots[0].status).toBe('map/tf/localization ready')
    expect(slots[1].status).toContain('1 active / 3 tracked')
  })
})
