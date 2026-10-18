import type { RadarViewportProps } from './radar-viewport'
import type { LaserScanSnapshot, MapSnapshot, NavigationPathSnapshot } from '@/types/station'

/** Compare only drawn geometry. Source clocks and quality remain in the unthrottled owner. */
function sameScan(a: LaserScanSnapshot, b: LaserScanSnapshot): boolean {
  return a === b || a.ready === b.ready && a.frameId === b.frameId && a.rangeMax === b.rangeMax
    && a.observedRange === b.observedRange && a.samplePoints.length === b.samplePoints.length
    && a.samplePoints.every((point, i) => {
      const other = b.samplePoints[i]
      return point.x === other.x && point.y === other.y && point.angleRad === other.angleRad && point.rangeMeters === other.rangeMeters
    })
}
function sameMap(a: MapSnapshot, b: MapSnapshot): boolean {
  return a === b || a.ready === b.ready && a.width === b.width && a.height === b.height && a.resolution === b.resolution
    && a.originX === b.originX && a.originY === b.originY && a.originYaw === b.originYaw && a.sampleStride === b.sampleStride
    && a.sampledCells.length === b.sampledCells.length && a.sampledCells.every((cell, i) => {
      const other = b.sampledCells[i]; return cell.x === other.x && cell.y === other.y && cell.occupancy === other.occupancy
    })
}
function samePath(a: NavigationPathSnapshot | undefined, b: NavigationPathSnapshot | undefined): boolean {
  return a === b || !!a && !!b && a.ready === b.ready && a.frameId === b.frameId && a.points.length === b.points.length
    && a.points.every((p, i) => p.x === b.points[i].x && p.y === b.points[i].y)
}

/** Never reuse this as a telemetry admission check or a command/pose validity check. */
export function radarViewportInputsEqual(a: RadarViewportProps, b: RadarViewportProps): boolean {
  if (a.config !== b.config || a.mapMode !== b.mapMode || a.draftPose !== b.draftPose || a.selectionDisabled !== b.selectionDisabled
    || a.pathTelemetryLive !== b.pathTelemetryLive || a.selectedPoint !== b.selectedPoint || a.onPointSelect !== b.onPointSelect
    || a.onPoseSelect !== b.onPoseSelect || !sameScan(a.scan, b.scan)) return false
  const ap = a.navigation.localization, bp = b.navigation.localization
  if (ap.ready !== bp.ready || ap.x !== bp.x || ap.y !== bp.y || ap.yaw !== bp.yaw
    || a.robotState.odom.x !== b.robotState.odom.x || a.robotState.odom.y !== b.robotState.odom.y || a.robotState.odom.yaw !== b.robotState.odom.yaw) return false
  const mapActive = a.config.layerMode === 'scan+map' && a.navigation.map.ready
  if (a.navigation.map.ready !== b.navigation.map.ready) return false
  if (mapActive) return sameMap(a.navigation.map, b.navigation.map)
    && (!a.pathTelemetryLive || samePath(a.navigation.path, b.navigation.path))
  if (a.config.showGhost) {
    const ah = a.history.slice(-5), bh = b.history.slice(-5)
    if (ah.length !== bh.length || !ah.every((frame, i) => sameScan(frame, bh[i]))) return false
  }
  return true
}
