import { describe, expect, it } from 'vitest'

import { mockNavigation, mockPerception } from './mock-station'
import { STATION_RESOURCE_LIMITS, StationValidationError, validateStationResource } from './station-validation'
import type { RawResourceMap, StationResource } from './station-validation'

const time = '2026-10-18T00:00:00Z'
const fixtures: RawResourceMap = {
  connection: { rosbridgeConnected: true, robotOnline: false, rosbridgeUrl: 'ws://127.0.0.1:9090', lastMessage: time, statusMessage: 'connected' },
  robotState: { x: 0, y: 0, yaw: 0, linearVelocity: 0, angularVelocity: 0, accelX: 0, accelY: 0, accelZ: 9.81,
    angularVelX: 0, angularVelY: 0, angularVelZ: 0, timestamp: time },
  navigation: mockNavigation,
  perception: mockPerception,
  diagnostics: { generatedAt: time, entries: [{ timestamp: time, source: 'control', message: 'observed', severity: 'INFO' }] },
}
function fresh<T extends StationResource>(resource: T): RawResourceMap[T] { return structuredClone(fixtures[resource]) }

describe('station wire resource validation', () => {
  it.each(['connection', 'robotState', 'navigation', 'perception', 'diagnostics'] as const)('accepts the existing %s wire shape independently', (resource) => {
    const input = fresh(resource)
    expect(validateStationResource(resource, input)).toBe(input)
  })

  it.each([null, [], 'JSON text', 3, true])('rejects non-object roots: %j', (input) => {
    expect(() => validateStationResource('connection', input)).toThrow(StationValidationError)
  })

  it('does not accept a successful connection object as another resource', () => {
    for (const resource of ['robotState', 'navigation', 'perception', 'diagnostics'] as const) {
      expect(() => validateStationResource(resource, fresh('connection'))).toThrow(StationValidationError)
    }
  })

  it('retains legacy optional bridges and validates a bridge when it is provided', () => {
    const input = fresh('connection')
    input.controlBridge = { connected: false, telemetryOnline: false, endpoint: 'ws://localhost:9090', lastMessage: time, statusMessage: 'disconnected' }
    expect(validateStationResource('connection', input).laserBridge).toBeUndefined()
    expect(() => validateStationResource('connection', { ...input, laserBridge: [] })).toThrow('laserBridge')
    expect(() => validateStationResource('connection', { ...input, controlBridge: { ...input.controlBridge, connected: 'yes' } })).toThrow('controlBridge.connected')
  })

  it('rejects malformed critical strings rather than throwing later in the mapper', () => {
    const input = fresh('connection')
    for (const patch of [{ rosbridgeUrl: null }, { statusMessage: {} }, { lastMessage: 1 }, { robotOnline: 'true' }]) {
      expect(() => validateStationResource('connection', { ...input, ...patch })).toThrow(StationValidationError)
    }
    expect(() => validateStationResource('connection', { ...input, rosbridgeUrl: 'x'.repeat(STATION_RESOURCE_LIMITS.stringLength + 1) })).toThrow('rosbridgeUrl')
  })

  it('accepts absent roll and pitch but rejects null, strings and nonfinite robot numbers', () => {
    expect(validateStationResource('robotState', fresh('robotState')).roll).toBeUndefined()
    for (const patch of [{ x: Number.NaN }, { yaw: Infinity }, { accelZ: '9.81' }, { roll: null }, { pitch: true }]) {
      expect(() => validateStationResource('robotState', { ...fresh('robotState'), ...patch })).toThrow(StationValidationError)
    }
  })

  it('preserves empty startup maps and optional or nullable legacy paths', () => {
    for (const path of [undefined, null]) expect(validateStationResource('navigation', { ...fresh('navigation'), path }).path).toBe(path)
    const input = fresh('navigation')
    input.path = { ready: false, frameId: '', poseCount: 0, points: [], lastUpdate: null, statusMessage: 'waiting' }
    expect(validateStationResource('navigation', input).path?.lastUpdate).toBeNull()
  })

  it('rejects missing navigation sections, nonfinite transforms and invalid ready maps', () => {
    const input = fresh('navigation')
    for (const patch of [{ map: null }, { tf: [] }, { localization: {} }, { navStatus: undefined }]) {
      expect(() => validateStationResource('navigation', { ...input, ...patch })).toThrow(StationValidationError)
    }
    expect(() => validateStationResource('navigation', { ...input, map: { ...input.map, ready: true } })).toThrow('map.ready')
    expect(() => validateStationResource('navigation', { ...input, map: { ...input.map, originYaw: Infinity } })).toThrow('originYaw')
  })

  it('checks sampled cell bounds and occupancy before rendering them', () => {
    const input = fresh('navigation')
    input.map = { ...input.map, ready: true, width: 10, height: 10, resolution: 0.05, sampledCells: [{ x: 0, y: 0, occupancy: -1 }] }
    expect(validateStationResource('navigation', input)).toBe(input)
    for (const cell of [{ x: 10, y: 0, occupancy: 0 }, { x: 0, y: -1, occupancy: 0 }, { x: 0.5, y: 0, occupancy: 0 },
      { x: 0, y: 0, occupancy: 101 }, { x: 0, y: 0, occupancy: -2 }, null]) {
      expect(() => validateStationResource('navigation', { ...input, map: { ...input.map, sampledCells: [cell] } })).toThrow('sampledCells')
    }
  })

  it('bounds map cells and rejects sparse arrays instead of skipping invalid entries', () => {
    const input = fresh('navigation')
    input.map = { ...input.map, ready: true, width: 100, height: 100, resolution: 0.05,
      sampledCells: Array.from({ length: STATION_RESOURCE_LIMITS.mapCells }, () => ({ x: 0, y: 0, occupancy: 0 })) }
    expect(validateStationResource('navigation', input)).toBe(input)
    input.map.sampledCells.push({ x: 0, y: 0, occupancy: 0 })
    expect(() => validateStationResource('navigation', input)).toThrow('sampledCells')
    expect(() => validateStationResource('navigation', { ...input, map: { ...input.map, sampledCells: new Array(1) } })).toThrow('sampledCells[0]')
  })

  it('accepts sampled paths whose source pose count exceeds displayed points and bounds the displayed array', () => {
    const input = fresh('navigation')
    input.path = { ready: true, frameId: 'map', poseCount: 10000, lastUpdate: time, statusMessage: 'sampled',
      points: Array.from({ length: STATION_RESOURCE_LIMITS.pathPoints }, () => ({ x: 1, y: -2 })) }
    expect(validateStationResource('navigation', input)).toBe(input)
    input.path.points.push({ x: 1, y: 2 })
    expect(() => validateStationResource('navigation', input)).toThrow('path.points')
  })

  it('rejects invalid path points and inconsistent navigation counters', () => {
    const input = fresh('navigation')
    const path = { ready: true, frameId: 'map', poseCount: 1, points: [{ x: 0, y: 0 }], lastUpdate: null, statusMessage: 'observed' }
    for (const patch of [{ points: [null] }, { points: [{ x: Infinity, y: 0 }] }, { points: [] }, { poseCount: 0 }, { lastUpdate: 1 }]) {
      expect(() => validateStationResource('navigation', { ...input, path: { ...path, ...patch } })).toThrow('path.')
    }
    expect(() => validateStationResource('navigation', { ...input, navStatus: { ...input.navStatus, activeGoals: 2, totalGoals: 1 } })).toThrow('activeGoals')
  })

  it('checks every perception section and finite scan point', () => {
    const input = fresh('perception')
    for (const patch of [{ scan: null }, { ultrasonic: [] }, { infrared: { ...input.infrared, blocked: 1 } }]) {
      expect(() => validateStationResource('perception', { ...input, ...patch })).toThrow(StationValidationError)
    }
    expect(() => validateStationResource('perception', { ...input, scan: { ...input.scan, samplePoints: [{ angleRad: 0, rangeMeters: 1, x: Number.NaN, y: 0 }] } })).toThrow('samplePoints[0].x')
    expect(() => validateStationResource('perception', { ...input, ultrasonic: { ...input.ultrasonic, distanceMeters: Infinity } })).toThrow('distanceMeters')
  })

  it('bounds scan points without requiring a full raw laser beam array', () => {
    const input = fresh('perception')
    input.scan.beamCount = 10000
    input.scan.samplePoints = Array.from({ length: STATION_RESOURCE_LIMITS.scanPoints }, () => ({ angleRad: 0, rangeMeters: 1, x: 1, y: 0 }))
    expect(validateStationResource('perception', input)).toBe(input)
    input.scan.samplePoints.push({ angleRad: 0, rangeMeters: 1, x: 1, y: 0 })
    expect(() => validateStationResource('perception', input)).toThrow('samplePoints')
  })

  it('accepts epoch and empty timestamp placeholders while honoring nullable path time only', () => {
    expect(validateStationResource('connection', { ...fresh('connection'), lastMessage: '' }).lastMessage).toBe('')
    expect(validateStationResource('robotState', { ...fresh('robotState'), timestamp: '1970-01-01T00:00:00Z' }).timestamp).toContain('1970')
    expect(() => validateStationResource('robotState', { ...fresh('robotState'), timestamp: null })).toThrow('timestamp')
  })

  it('bounds diagnostics and rejects malformed entries with a precise field', () => {
    const input = fresh('diagnostics')
    input.entries = Array.from({ length: STATION_RESOURCE_LIMITS.diagnostics }, () => ({ timestamp: time, source: 'control', message: 'observed', severity: 'FUTURE_LEVEL' }))
    expect(validateStationResource('diagnostics', input)).toBe(input)
    input.entries.push(input.entries[0])
    expect(() => validateStationResource('diagnostics', input)).toThrow('entries')
    expect(() => validateStationResource('diagnostics', { generatedAt: time, entries: [{ timestamp: time, source: {}, message: 'text', severity: 'INFO' }] })).toThrow('entries[0].source')
  })

  it('preserves unknown additive fields without mutating or manufacturing freshness', () => {
    const input = { ...fresh('connection'), futureCapability: { enabled: false } }
    const before = structuredClone(input)
    expect(validateStationResource('connection', input)).toEqual(before)
    expect(input).toEqual(before)
    expect('receivedAt' in input).toBe(false)
  })
})
