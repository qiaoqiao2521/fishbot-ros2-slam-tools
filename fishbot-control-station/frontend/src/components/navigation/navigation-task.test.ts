import { describe, expect, it } from 'vitest'

import { getNavigationTaskPresentation } from '@/components/navigation/navigation-task'
import type { ConnectionSnapshot, NavigationSnapshot, RobotStateSnapshot } from '@/types/station'

const robotState: RobotStateSnapshot = {
  odom: {
    x: 1.18,
    y: -0.42,
    yaw: 0.52,
    linearVelocity: 0.24,
    angularVelocity: 0.11,
  },
  imu: {
    angularVelocity: { x: 0, y: 0, z: 0.11 },
    linearAcceleration: { x: 0.03, y: -0.01, z: 9.81 },
    orientation: { roll: 0, pitch: 0, yaw: 0.52 },
  },
  messageRateHz: 16.8,
  lastUpdatedAt: '2026-03-18T02:15:00.000Z',
}

const baseConnection: ConnectionSnapshot = {
  rosbridgeConnected: true,
  robotOnline: true,
  reconnecting: false,
  lastMessageAt: '2026-03-18T02:15:00.000Z',
  endpoint: 'ws://127.0.0.1:9090',
  mode: 'offline',
  statusLabel: 'offline simulator',
  controlBridge: {
    connected: true,
    telemetryOnline: true,
    lastMessageAt: '2026-03-18T02:15:00.000Z',
    endpoint: 'ws://127.0.0.1:9090',
    statusLabel: 'offline simulator',
  },
  laserBridge: {
    connected: true,
    telemetryOnline: true,
    lastMessageAt: '2026-03-18T02:15:00.000Z',
    endpoint: 'ws://127.0.0.1:9091',
    statusLabel: 'offline simulator',
  },
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
    lastUpdate: '2026-03-18T02:15:00.000Z',
    statusMessage: 'live occupancy grid',
    sampledCells: [
      { x: 0, y: 0, occupancy: 0 },
      { x: 2, y: 0, occupancy: 100 },
    ],
  },
  tf: {
    ready: true,
    mapToOdomPresent: true,
    odomToBasePresent: true,
    transformCount: 2,
    staticTransformCount: 1,
    lastUpdate: '2026-03-18T02:15:00.000Z',
    statusMessage: 'tf graph observed',
  },
  localization: {
    ready: true,
    x: 2.4,
    y: -1.2,
    yaw: 0.785,
    covarianceScore: 0.16,
    lastUpdate: '2026-03-18T02:15:00.000Z',
    statusMessage: 'amcl pose locked',
  },
  navStatus: {
    ready: true,
    activeGoals: 1,
    totalGoals: 3,
    statusSummary: 'EXECUTING:1, SUCCEEDED:1, ABORTED:1',
    lastUpdate: '2026-03-18T02:15:00.000Z',
    statusMessage: 'nav action status observed',
  },
}

describe('navigation task presentation', () => {
  it('treats fallback mode as read-only preview with disabled actions', () => {
    const view = getNavigationTaskPresentation(baseConnection, robotState, navigation, true, 'idle')

    expect(view.modeLabel).toBe('fallback snapshot')
    expect(view.cancelDisabled).toBe(true)
    expect(view.clearDisabled).toBe(true)
    expect(view.actionLabel).toContain('preview')
    expect(view.queueItems[0].state).toContain('blocked')
  })

  it('shows offline mode as a local preview surface with cancel and clear enabled', () => {
    const view = getNavigationTaskPresentation(baseConnection, robotState, navigation, false, 'idle')

    expect(view.modeLabel).toBe('offline simulator')
    expect(view.cancelDisabled).toBe(false)
    expect(view.clearDisabled).toBe(false)
    expect(view.taskCards[0].value).toContain('simulated')
    expect(view.queueItems[1].source).toContain('local')
  })

  it('adds local cancel and clear previews without claiming real dispatch', () => {
    const canceled = getNavigationTaskPresentation(baseConnection, robotState, navigation, false, 'cancel-active')
    const cleared = getNavigationTaskPresentation(baseConnection, robotState, navigation, false, 'clear-queue')

    expect(canceled.actionLabel).toContain('cancel')
    expect(canceled.queueItems[0].state).toContain('cancel')
    expect(cleared.actionLabel).toContain('clear')
    expect(cleared.queueItems[0].state).toContain('cleared')
  })

  it('marks live mode as wiring-ready while still staying on the skeleton side', () => {
    const liveView = getNavigationTaskPresentation(
      { ...baseConnection, mode: 'live', statusLabel: 'live robot link' },
      robotState,
      navigation,
      false,
      'idle',
    )

    expect(liveView.modeLabel).toBe('live robot link')
    expect(liveView.taskCards[1].value).toContain('1 active / 3 tracked')
    expect(liveView.taskCards[3].value).toContain('EXECUTING')
    expect(liveView.operatorNote).toContain('action client')
  })
})
