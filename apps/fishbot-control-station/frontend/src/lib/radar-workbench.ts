import type { LaserScanPointSnapshot, LaserScanSnapshot, MapSnapshot, NavigationPathSnapshot } from '@/types/station'

export type RadarLayerMode = 'scan' | 'scan+pose' | 'scan+map'
export type RadarMapMode = 'observe' | 'goal' | 'initial-pose'
export type RadarMapPose = WorldPoint & { yaw: number }
export type MapPublicationStatus = 'idle' | 'sending' | 'published' | 'unconfirmed' | 'error'

export function mapPublicationBlocksDraft(status: MapPublicationStatus): boolean {
  return status === 'sending' || status === 'published' || status === 'unconfirmed'
}

export type RadarWorkbenchConfig = {
  zoom: number
  freeze: boolean
  showGhost: boolean
  showSweep: boolean
  showGrid: boolean
  layerMode: RadarLayerMode
}

export type RadarSelectedPoint = LaserScanPointSnapshot

export type RadarWorkbenchMetrics = {
  beamCount: number
  sampleCount: number
  validRatio: number
  nearFieldCount: number
  coverageRatio: number
  obstructionLevel: 'low' | 'moderate' | 'high'
}

export function createDefaultRadarWorkbenchConfig(): RadarWorkbenchConfig {
  return {
    zoom: 1,
    freeze: false,
    showGhost: true,
    showSweep: true,
    showGrid: true,
    layerMode: 'scan',
  }
}

export function buildRadarWorkbenchMetrics(scan: LaserScanSnapshot): RadarWorkbenchMetrics {
  const beamCount = Math.max(scan.beamCount, 1)
  const sampleCount = scan.samplePoints.length
  const validRatio = (sampleCount / beamCount) * 100

  const sectorHits = new Set<number>()
  const nearFieldCount = scan.samplePoints.filter((point) => {
    const normalized = ((point.angleRad + Math.PI) / (Math.PI * 2)) * 12
    sectorHits.add(Math.max(0, Math.min(11, Math.floor(normalized))))
    return point.rangeMeters <= 0.8
  }).length

  const coverageRatio = (sectorHits.size / 12) * 100
  const obstructionLevel = nearFieldCount >= 8 ? 'high' : nearFieldCount >= 3 ? 'moderate' : 'low'

  return {
    beamCount,
    sampleCount,
    validRatio,
    nearFieldCount,
    coverageRatio,
    obstructionLevel,
  }
}

// ---------------------------------------------------------------------------
// Map-frame projection (scan+map layer)
//
// The map layer mirrors the Unitree Go2 app's SLAM view approach: occupancy
// grid + live scan in the map frame + robot pose + operator selection. Coordinates
// here are world meters (ROS map frame); the viewport is the shared 100x100
// SVG viewBox, scaled uniformly so the map never distorts.
// ---------------------------------------------------------------------------

export type MapWorldBounds = {
  minX: number
  minY: number
  maxX: number
  maxY: number
}

export type WorldPoint = {
  x: number
  y: number
}

export type MapProjection = {
  toViewport: (point: WorldPoint) => { left: number; top: number }
  toWorld: (left: number, top: number) => WorldPoint
  /** Size of one occupancy cell (already stride-multiplied) in viewport units. */
  cellViewportSize: (map: MapSnapshot) => number
  /** Meters covered by the viewport's longer axis; used for the scale readout. */
  visibleExtent: number
}

export function resolveMapWorldBounds(map: MapSnapshot): MapWorldBounds {
  const corners = mapWorldCorners(map)
  return {
    minX: Math.min(...corners.map((point) => point.x)),
    minY: Math.min(...corners.map((point) => point.y)),
    maxX: Math.max(...corners.map((point) => point.x)),
    maxY: Math.max(...corners.map((point) => point.y)),
  }
}

export function mapWorldCorners(map: MapSnapshot): WorldPoint[] {
  const width = map.width * map.resolution
  const height = map.height * map.resolution
  const cos = Math.cos(map.originYaw)
  const sin = Math.sin(map.originYaw)
  return [[0, 0], [width, 0], [width, height], [0, height]].map(([x, y]) => ({
    x: map.originX + x * cos - y * sin,
    y: map.originY + x * sin + y * cos,
  }))
}

export function isPointInsideMap(point: WorldPoint, map: MapSnapshot): boolean {
  if (!map.ready || map.width <= 0 || map.height <= 0 || map.resolution <= 0
    || ![point.x, point.y, map.originX, map.originY, map.originYaw, map.resolution].every(Number.isFinite)) return false
  const dx = point.x - map.originX
  const dy = point.y - map.originY
  const x = dx * Math.cos(map.originYaw) + dy * Math.sin(map.originYaw)
  const y = -dx * Math.sin(map.originYaw) + dy * Math.cos(map.originYaw)
  const epsilon = 1e-8
  return x >= -epsilon && y >= -epsilon
    && x <= map.width * map.resolution + epsilon && y <= map.height * map.resolution + epsilon
}

/** Reject SVG letterboxes, view padding, and the empty corners around rotated maps. */
export function mapPointerToWorld(
  pointer: { clientX: number; clientY: number },
  rect: { left: number; top: number; width: number; height: number },
  projection: MapProjection,
  map: MapSnapshot,
): WorldPoint | null {
  if (rect.width <= 0 || rect.height <= 0) return null
  const scale = Math.min(rect.width, rect.height) / 100
  const left = (pointer.clientX - rect.left - (rect.width - 100 * scale) / 2) / scale
  const top = (pointer.clientY - rect.top - (rect.height - 100 * scale) / 2) / scale
  if (!Number.isFinite(left) || !Number.isFinite(top) || left < 0 || top < 0 || left > 100 || top > 100) return null
  const point = projection.toWorld(left, top)
  return isPointInsideMap(point, map) ? point : null
}

/** Selection is a draft only. Sending belongs exclusively to the explicit page button. */
export function selectMapPose(
  mode: RadarMapMode,
  current: RadarMapPose | null,
  start: WorldPoint,
  end: WorldPoint,
  dragged = false,
): RadarMapPose | null {
  if (mode === 'observe') return null
  const position = current ?? start
  const dx = end.x - position.x
  const dy = end.y - position.y
  const yaw = (current || dragged) && Math.hypot(dx, dy) > 1e-8 ? Math.atan2(dy, dx) : current?.yaw ?? 0
  return { ...position, yaw }
}

/** A path in another frame needs a real TF transform; never guess it from odometry. */
export function renderableNavigationPath(path: NavigationPathSnapshot | undefined): WorldPoint[] {
  if (!path?.ready || path.frameId !== 'map' || path.points.length < 2) return []
  if (!path.points.every((point) => Number.isFinite(point.x) && Number.isFinite(point.y))) return []
  return path.points
}

export function mapHeadingDegrees(yaw: number): number {
  return -yaw * 180 / Math.PI
}

export function createMapProjection(bounds: MapWorldBounds, zoom = 1): MapProjection {
  const padding = 3
  const usable = 100 - padding * 2
  const spanX = Math.max(bounds.maxX - bounds.minX, 1e-6)
  const spanY = Math.max(bounds.maxY - bounds.minY, 1e-6)
  const baseScale = usable / Math.max(spanX, spanY)
  const scale = baseScale * Math.max(zoom, 0.1)
  const centerX = (bounds.minX + bounds.maxX) / 2
  const centerY = (bounds.minY + bounds.maxY) / 2

  return {
    toViewport: (point) => ({
      left: 50 + (point.x - centerX) * scale,
      // SVG y grows downward; world y grows upward.
      top: 50 - (point.y - centerY) * scale,
    }),
    toWorld: (left, top) => ({
      x: centerX + (left - 50) / scale,
      y: centerY - (top - 50) / scale,
    }),
    cellViewportSize: (map) => Math.max(map.resolution * map.sampleStride * scale, 0.15),
    visibleExtent: Math.max(spanX, spanY) / Math.max(zoom, 0.1),
  }
}

export function cellWorldCenter(cell: { x: number; y: number }, map: MapSnapshot): WorldPoint {
  const localX = (cell.x + 0.5) * map.resolution
  const localY = (cell.y + 0.5) * map.resolution
  const cos = Math.cos(map.originYaw)
  const sin = Math.sin(map.originYaw)

  return {
    x: map.originX + localX * cos - localY * sin,
    y: map.originY + localX * sin + localY * cos,
  }
}

/**
 * Places a robot-frame laser point into the map frame using the localized
 * pose. The laser->base offset is unknown until real TF values are wired
 * (the backend currently reports TF presence only), so this assumes the
 * scan frame origin coincides with the base footprint origin.
 */
export function scanPointInMapFrame(point: { x: number; y: number }, pose: { x: number; y: number; yaw: number }): WorldPoint {
  const cos = Math.cos(pose.yaw)
  const sin = Math.sin(pose.yaw)

  return {
    x: pose.x + point.x * cos - point.y * sin,
    y: pose.y + point.x * sin + point.y * cos,
  }
}

export function occupancyColor(occupancy: number): string {
  if (occupancy >= 65) return 'rgba(58,44,26,0.92)'
  if (occupancy >= 40) return 'rgba(96,74,38,0.55)'
  if (occupancy > 0) return 'rgba(150,116,60,0.28)'
  return 'rgba(214,196,166,0.16)'
}
