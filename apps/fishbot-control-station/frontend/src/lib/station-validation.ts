import type {
  RawConnectionSnapshot, RawDiagnosticSnapshot, RawNavigationSnapshot,
  RawPerceptionSnapshot, RawRobotStateSnapshot,
} from './api'

export type StationResource = 'connection' | 'robotState' | 'navigation' | 'perception' | 'diagnostics'
export type RawResourceMap = {
  connection: RawConnectionSnapshot
  robotState: RawRobotStateSnapshot
  navigation: RawNavigationSnapshot
  perception: RawPerceptionSnapshot
  diagnostics: RawDiagnosticSnapshot
}
export const STATION_RESOURCE_LIMITS = { mapCells: 6000, pathPoints: 2000, scanPoints: 4096, diagnostics: 512, stringLength: 16384 } as const

export class StationValidationError extends Error {
  readonly name = 'StationValidationError'
  readonly resource: StationResource
  readonly field: string
  constructor(resource: StationResource, field: string) {
    super(`控制站 ${resource} 数据无效（${field}），保留此前快照并等待有效数据。`)
    this.resource = resource
    this.field = field
  }
}
type JsonRecord = Record<string, unknown>
function record(value: unknown): value is JsonRecord { return value !== null && typeof value === 'object' && !Array.isArray(value) }
function finite(value: unknown): value is number { return typeof value === 'number' && Number.isFinite(value) }
function integer(value: unknown, minimum = 0): value is number { return Number.isSafeInteger(value) && (value as number) >= minimum }
function text(value: unknown): value is string { return typeof value === 'string' && value.length <= STATION_RESOURCE_LIMITS.stringLength }

/** Validate wire DTOs before mapping. A valid resource does not certify any other resource or task. */
export function validateStationResource<T extends keyof RawResourceMap>(resource: T, value: unknown): RawResourceMap[T] {
  const check = (valid: boolean, field: string): void => { if (!valid) throw new StationValidationError(resource, field) }
  const object = (input: unknown, field: string): JsonRecord => {
    check(record(input), field)
    return input as JsonRecord
  }
  const bools = (input: JsonRecord, keys: string[], field: string): void => {
    for (const key of keys) check(typeof input[key] === 'boolean', `${field}.${key}`)
  }
  const strings = (input: JsonRecord, keys: string[], field: string): void => {
    for (const key of keys) check(text(input[key]), `${field}.${key}`)
  }
  const numbers = (input: JsonRecord, keys: string[], field: string): void => {
    for (const key of keys) check(finite(input[key]), `${field}.${key}`)
  }
  const counts = (input: JsonRecord, keys: string[], field: string): void => {
    for (const key of keys) check(integer(input[key]), `${field}.${key}`)
  }
  const array = (input: unknown, limit: number, field: string): unknown[] => {
    check(Array.isArray(input) && input.length <= limit, field)
    return input as unknown[]
  }
  const root = object(value, resource)
  switch (resource) {
    case 'connection': {
      bools(root, ['rosbridgeConnected', 'robotOnline'], resource)
      strings(root, ['rosbridgeUrl', 'lastMessage', 'statusMessage'], resource)
      for (const key of ['controlBridge', 'laserBridge']) {
        if (root[key] === undefined) continue
        const bridge = object(root[key], key)
        bools(bridge, ['connected', 'telemetryOnline'], key)
        strings(bridge, ['endpoint', 'lastMessage', 'statusMessage'], key)
      }
      break
    }
    case 'robotState':
      numbers(root, ['x', 'y', 'yaw', 'linearVelocity', 'angularVelocity', 'accelX', 'accelY', 'accelZ', 'angularVelX', 'angularVelY', 'angularVelZ'], resource)
      for (const key of ['roll', 'pitch']) if (root[key] !== undefined) check(finite(root[key]), key)
      strings(root, ['timestamp'], resource)
      break
    case 'navigation': {
      const map = object(root.map, 'map')
      bools(map, ['ready'], 'map')
      counts(map, ['width', 'height'], 'map')
      check(integer(map.sampleStride, 1), 'map.sampleStride')
      numbers(map, ['resolution', 'originX', 'originY', 'originYaw'], 'map')
      check((map.resolution as number) >= 0, 'map.resolution')
      check(!map.ready || ((map.width as number) > 0 && (map.height as number) > 0 && (map.resolution as number) > 0), 'map.ready')
      strings(map, ['lastUpdate', 'statusMessage'], 'map')
      for (const [index, item] of array(map.sampledCells, STATION_RESOURCE_LIMITS.mapCells, 'map.sampledCells').entries()) {
        const cell = object(item, `map.sampledCells[${index}]`)
        check(integer(cell.x) && (cell.x as number) < (map.width as number), `map.sampledCells[${index}].x`)
        check(integer(cell.y) && (cell.y as number) < (map.height as number), `map.sampledCells[${index}].y`)
        check(integer(cell.occupancy, -1) && (cell.occupancy as number) <= 100, `map.sampledCells[${index}].occupancy`)
      }
      const tf = object(root.tf, 'tf')
      bools(tf, ['ready', 'mapToOdomPresent', 'odomToBasePresent'], 'tf')
      counts(tf, ['transformCount', 'staticTransformCount'], 'tf')
      strings(tf, ['lastUpdate', 'statusMessage'], 'tf')
      const localization = object(root.localization, 'localization')
      bools(localization, ['ready'], 'localization')
      numbers(localization, ['x', 'y', 'yaw', 'covarianceScore'], 'localization')
      strings(localization, ['lastUpdate', 'statusMessage'], 'localization')
      const nav = object(root.navStatus, 'navStatus')
      bools(nav, ['ready'], 'navStatus')
      counts(nav, ['activeGoals', 'totalGoals'], 'navStatus')
      check((nav.activeGoals as number) <= (nav.totalGoals as number), 'navStatus.activeGoals')
      strings(nav, ['statusSummary', 'lastUpdate', 'statusMessage'], 'navStatus')
      if (root.path !== undefined && root.path !== null) {
        const path = object(root.path, 'path')
        bools(path, ['ready'], 'path')
        counts(path, ['poseCount'], 'path')
        strings(path, ['frameId', 'statusMessage'], 'path')
        check(path.lastUpdate === null || text(path.lastUpdate), 'path.lastUpdate')
        const points = array(path.points, STATION_RESOURCE_LIMITS.pathPoints, 'path.points')
        check((path.poseCount as number) >= points.length && (!path.ready || points.length > 0), 'path.poseCount')
        for (const [index, item] of points.entries()) numbers(object(item, `path.points[${index}]`), ['x', 'y'], `path.points[${index}]`)
      }
      break
    }
    case 'perception': {
      const scan = object(root.scan, 'scan')
      bools(scan, ['ready'], 'scan')
      strings(scan, ['frameId', 'lastUpdate', 'statusMessage'], 'scan')
      counts(scan, ['beamCount'], 'scan')
      numbers(scan, ['angleMin', 'angleMax', 'rangeMin', 'rangeMax', 'observedRange'], 'scan')
      check((scan.rangeMin as number) >= 0 && (scan.rangeMax as number) >= 0 && (scan.observedRange as number) >= 0, 'scan.range')
      const points = array(scan.samplePoints, STATION_RESOURCE_LIMITS.scanPoints, 'scan.samplePoints')
      check((scan.beamCount as number) >= points.length && (!scan.ready || points.length > 0), 'scan.beamCount')
      for (const [index, item] of points.entries()) {
        const point = object(item, `scan.samplePoints[${index}]`)
        numbers(point, ['angleRad', 'rangeMeters', 'x', 'y'], `scan.samplePoints[${index}]`)
        check((point.rangeMeters as number) >= 0, `scan.samplePoints[${index}].rangeMeters`)
      }
      for (const key of ['ultrasonic', 'infrared']) {
        const range = object(root[key], key)
        bools(range, ['ready', 'blocked'], key)
        strings(range, ['sourceTopic', 'frameId', 'lastUpdate', 'statusMessage'], key)
        numbers(range, ['distanceMeters', 'maxRangeMeters'], key)
      }
      break
    }
    case 'diagnostics':
      strings(root, ['generatedAt'], resource)
      for (const [index, item] of array(root.entries, STATION_RESOURCE_LIMITS.diagnostics, 'entries').entries()) {
        strings(object(item, `entries[${index}]`), ['timestamp', 'source', 'message', 'severity'], `entries[${index}]`)
      }
      break
    default:
      throw new StationValidationError(resource, 'resource')
  }
  return value as RawResourceMap[T]
}
