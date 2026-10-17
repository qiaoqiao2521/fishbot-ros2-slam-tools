/** Click-draft correction only. Native Nav2 planning and backend dispatch checks remain authoritative. */
import { MapZonesManager } from './map-zones'
import { isFreeWaypoint, validateSimulationMap, worldToMap, type Point, type SimulationMap } from './simulation'
import type { MapZone } from './simulation-workspace'

export const DEFAULT_ROUTE_RADIUS_M = .13
export const SNAP_MARGIN_M = .01
/** Per forward/backward scan; both scans and the two bisections are bounded. */
export const MAX_SNAP_SAMPLES = 4096
export const MAX_CONFLICT_POINTS = 2048
const MIN_SNAP_PROGRESS_M = .001
const BISECTION_STEPS = 20

type Collision = { hasCollision: boolean; collidedEntityId?: string; collisionType?: 'wall' | 'zone' }
export type SegmentConflict = {
  /** Zero-based index of the segment's start. A single stationary point uses 0. */
  index: number
  start: Point
  end: Point
  entityId: string
  collisionType: 'wall' | 'zone'
}
export type WaypointSelection = {
  kind: 'accepted' | 'snapped' | 'rejected'
  requested: Point
  point?: Point
  conflict?: SegmentConflict
  reason: string
}

const finitePoint = (point: Point): boolean => !!point && typeof point === 'object'
  && Number.isFinite(point.x) && Number.isFinite(point.y)
const copyPoint = (point: Point): Point => ({ x: point?.x ?? NaN, y: point?.y ?? NaN })
const validRadius = (radius: number): boolean => typeof radius === 'number' && Number.isFinite(radius) && radius >= 0
const between = (start: Point, end: Point, fraction: number): Point => ({
  x: start.x+(end.x-start.x)*fraction, y: start.y+(end.y-start.y)*fraction,
})
function conflictValue(index: number, start: Point, end: Point, collision: Collision): SegmentConflict {
  if (!collision.hasCollision || !collision.collidedEntityId || !collision.collisionType) {
    throw new Error('Incomplete geometry conflict result.')
  }
  return {index,start:copyPoint(start),end:copyPoint(end),entityId:collision.collidedEntityId,collisionType:collision.collisionType}
}

/** Every returned segment really intersects an existing wall/zone with the given footprint. */
export function segmentConflicts(points: Point[], zones: MapZone[], radiusM = DEFAULT_ROUTE_RADIUS_M): SegmentConflict[] {
  if (!Array.isArray(points) || points.length > MAX_CONFLICT_POINTS
    || !Array.from(points).every(finitePoint) || !validRadius(radiusM)) {
    throw new Error('路线必须包含有限坐标，且不能超过 2048 个点；车体半径必须为非负有限值。')
  }
  const manager=MapZonesManager.fromMapRulesZones(zones)
  if (!points.length) return []
  const conflicts: SegmentConflict[]=[]
  for (let index=0;index<Math.max(1,points.length-1);index++) {
    const start=points[index], end=points[Math.min(index+1,points.length-1)]
    const collision=manager.checkPathCollision([start,end],radiusM)
    if (collision.hasCollision) conflicts.push(conflictValue(index,start,end,collision))
  }
  return conflicts
}

function freeGridPoint(point: Point, map: SimulationMap, radiusM: number): boolean {
  // Cheap bounds precede the existing cell scan. This also avoids an unbounded
  // radius loop for an impossibly small resolution or an out-of-map coordinate.
  const pixel=worldToMap(point,map)
  const cx=Math.floor(pixel.x), cy=Math.floor(map.height-pixel.y), cells=Math.ceil(radiusM/map.resolution)
  if (![cx,cy,cells].every(Number.isSafeInteger) || cells > Math.max(map.width,map.height)
    || cx-cells < 0 || cy-cells < 0 || cx+cells >= map.width || cy+cells >= map.height) return false
  return isFreeWaypoint(point,map,radiusM)
}

/**
 * Preserves the original requested point for red-line preview. A snap corrects
 * only this click's straight-line draft; it never bans a saved Nav2 detour.
 */
export function evaluateWaypointSelection(
  start: Point, requested: Point, map: SimulationMap, zones: MapZone[], radiusM = DEFAULT_ROUTE_RADIUS_M,
): WaypointSelection {
  const requestedCopy=copyPoint(requested)
  const rejected=(reason: string, conflict?: SegmentConflict): WaypointSelection =>
    ({kind:'rejected',requested:requestedCopy,...(conflict ? {conflict} : {}),reason})
  if (!finitePoint(start) || !finitePoint(requested) || !validRadius(radiusM)) {
    return rejected('起点、所选目标和车体半径必须是有限值；未修改草稿。')
  }
  const distance=Math.hypot(requested.x-start.x,requested.y-start.y)
  if (!Number.isFinite(distance)) return rejected('目标距离超出即时校验范围，请选择更近的点。')
  let manager: MapZonesManager
  try {
    validateSimulationMap(map)
    manager=MapZonesManager.fromMapRulesZones(zones)
  } catch {
    return rejected('地图或禁区数据无效，请重新读取后再选点。')
  }
  try {
    const startCollision=manager.checkPathCollision([start],radiusM)
    if (startCollision.hasCollision) {
      return rejected('起点车体已接触虚拟墙或禁区，无法判断安全的吸附方向。',
        conflictValue(0,start,requested,startCollision))
    }
    if (!freeGridPoint(start,map,radiusM)) return rejected('起点车体范围处于地图外、未知区域或实体障碍内，未修改草稿。')
    if (!freeGridPoint(requested,map,radiusM)) return rejected('所选点的车体范围过于接近地图边界、未知区域或实体障碍，请另选位置。')
    const directCollision=manager.checkPathCollision([start,requested],radiusM)
    const spacing=Math.min(.01,map.resolution/2)
    const samples=distance === 0 ? 0 : Math.ceil(distance/spacing)
    if (!Number.isFinite(samples) || samples > MAX_SNAP_SAMPLES) {
      return rejected('直线草稿超出即时吸附采样预算，请分段选点；原目标已保留。',
        directCollision.hasCollision ? conflictValue(0,start,requested,directCollision) : undefined)
    }
    if (!directCollision.hasCollision) {
      return {kind:'accepted',requested:requestedCopy,point:copyPoint(requested),reason:'所选点通过草稿校验；实际路线仍由 Nav2 规划。'}
    }
    const originalConflict=conflictValue(0,start,requested,directCollision)
    if (samples < 1) return rejected('未能定位有效的直线草稿区间，请重新选择目标。',originalConflict)
    let low=0, high: number | null=null
    let boundaryCollision=directCollision
    for (let index=1;index<=samples;index++) {
      const fraction=index/samples
      // Check a continuous swept segment, not merely its endpoint: a thin wall
      // between two samples is still detected and cannot be skipped.
      const collision=manager.checkPathCollision([between(start,requested,low),between(start,requested,fraction)],radiusM)
      if (collision.hasCollision) { high=fraction; boundaryCollision=collision; break }
      low=fraction
    }
    if (high === null) return rejected('未能稳定定位首次冲突边界，请另选目标。',originalConflict)
    let upper: number=high
    for (let iteration=0;iteration<BISECTION_STEPS;iteration++) {
      const middle: number=(low+upper)/2
      // Prefix intersection is monotonic even after the endpoint crosses a
      // thin wall, unlike testing only whether the midpoint itself is occupied.
      const collision=manager.checkPathCollision([start,between(start,requested,middle)],radiusM)
      if (collision.hasCollision) { upper=middle; boundaryCollision=collision }
      else low=middle
    }
    const firstConflict=conflictValue(0,start,requested,boundaryCollision)
    const contactTravel=low*distance
    const marginRadius=radiusM+SNAP_MARGIN_M
    let travel: number | null=null, marginUpper=contactTravel
    // An oblique wall needs more than a 1 cm retreat along the route to obtain
    // 1 cm perpendicular clearance. Check an expanded footprint, still strictly
    // before the first original collision. Never jump through to its far side.
    for (let index=0;index<=samples;index++) {
      const candidateTravel=Math.max(0,contactTravel-index*spacing)
      if (candidateTravel < MIN_SNAP_PROGRESS_M) break
      if (!manager.checkPathCollision([between(start,requested,candidateTravel/distance)],marginRadius).hasCollision) {
        travel=candidateTravel
        break
      }
      marginUpper=candidateTravel
    }
    if (travel === null) {
      return rejected('起点到规则边界的余量不足，无法保留 1 厘米间隔；请重新选择目标。',firstConflict)
    }
    let marginLow: number=travel
    const marginStart=between(start,requested,marginLow/distance)
    for (let iteration=0;iteration<BISECTION_STEPS;iteration++) {
      const middle: number=(marginLow+marginUpper)/2
      if (manager.checkPathCollision([marginStart,between(start,requested,middle/distance)],marginRadius).hasCollision) marginUpper=middle
      else marginLow=middle
    }
    const candidate=between(start,requested,marginLow/distance)
    // Do not quantize before this final full-footprint check: rounding can move
    // a near-boundary candidate back into the forbidden area.
    if (!finitePoint(candidate) || !freeGridPoint(candidate,map,radiusM)
      || manager.checkPathCollision([start,candidate],radiusM).hasCollision
      || manager.checkPathCollision([candidate],marginRadius).hasCollision) {
      return rejected('冲突前的吸附点未通过完整车体复验，请另选目标。',firstConflict)
    }
    return {kind:'snapped',requested:requestedCopy,point:copyPoint(candidate),conflict:firstConflict,
      reason:'已吸附到首次规则冲突前的安全点，并额外保留 1 厘米间隔；红线保留原目标。'}
  } catch {
    return rejected('几何计算未通过校验，请重新读取地图并选择有限坐标。')
  }
}
