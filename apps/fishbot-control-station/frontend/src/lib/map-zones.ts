/**
 * 地图禁行区与虚拟墙几何引擎 (Map Zones & Virtual Obstacles Engine)
 * 对标工业级移动机器人与扫地机器人（Nav2 Costmap Filters 工业规范）
 * 支持线段虚拟墙、多边形禁行区、避障碰撞检测与撤销/重做事务栈。
 */

import type { WorldPoint } from './radar-workbench'

export interface VirtualWall {
  id: string
  name: string
  start: WorldPoint
  end: WorldPoint
}

export type ZoneType = 'keep_out' | 'no_clean' | 'speed_restricted'

export interface RestrictedZone {
  id: string
  name: string
  type: ZoneType
  /** 顶点列表，顺时针或逆时针排列，至少 3 个点构成多边形 */
  points: WorldPoint[]
  /** 当类型为 speed_restricted 时的限速值 (m/s) */
  maxSpeedMps?: number
}

export interface MapZonesSnapshot {
  walls: VirtualWall[]
  zones: RestrictedZone[]
}

/**
 * 判断两个 2D 线段 (p1-p2) 与 (p3-p4) 是否相交
 */
export function doLineSegmentsIntersect(
  p1: WorldPoint,
  p2: WorldPoint,
  p3: WorldPoint,
  p4: WorldPoint,
): boolean {
  const ccw = (a: WorldPoint, b: WorldPoint, c: WorldPoint) => {
    return (c.y - a.y) * (b.x - a.x) > (b.y - a.y) * (c.x - a.x)
  }
  return (
    ccw(p1, p3, p4) !== ccw(p2, p3, p4) &&
    ccw(p1, p2, p3) !== ccw(p1, p2, p4)
  )
}

/**
 * 使用射线法 (Ray Casting Algorithm) 判断点是否在多边形内部
 */
export function isPointInsidePolygon(point: WorldPoint, polygon: WorldPoint[]): boolean {
  if (polygon.length < 3) return false
  let inside = false
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i].x
    const yi = polygon[i].y
    const xj = polygon[j].x
    const yj = polygon[j].y

    const intersect =
      yi > point.y !== yj > point.y &&
      point.x < ((xj - xi) * (point.y - yi)) / (yj - yi + Number.EPSILON) + xi
    if (intersect) {
      inside = !inside
    }
  }
  return inside
}

/**
 * 计算点到线段的最短距离
 */
export function distanceToSegment(p: WorldPoint, a: WorldPoint, b: WorldPoint): number {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const l2 = dx * dx + dy * dy
  if (l2 === 0) return Math.hypot(p.x - a.x, p.y - a.y)
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / l2))
  const projX = a.x + t * dx
  const projY = a.y + t * dy
  return Math.hypot(p.x - projX, p.y - projY)
}

export class MapZonesManager {
  private walls: VirtualWall[] = []
  private zones: RestrictedZone[] = []
  private historyStack: MapZonesSnapshot[] = []
  private redoStack: MapZonesSnapshot[] = []

  constructor(initial?: Partial<MapZonesSnapshot>) {
    if (initial?.walls) this.walls = [...initial.walls]
    if (initial?.zones) this.zones = [...initial.zones]
  }

  private saveState(): void {
    this.historyStack.push({
      walls: JSON.parse(JSON.stringify(this.walls)),
      zones: JSON.parse(JSON.stringify(this.zones)),
    })
    this.redoStack = []
  }

  public getSnapshot(): MapZonesSnapshot {
    return {
      walls: [...this.walls],
      zones: [...this.zones],
    }
  }

  public addWall(start: WorldPoint, end: WorldPoint, name?: string): VirtualWall {
    this.saveState()
    const wall: VirtualWall = {
      id: `wall_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`,
      name: name ?? `虚拟墙 ${this.walls.length + 1}`,
      start: { x: Number(start.x.toFixed(3)), y: Number(start.y.toFixed(3)) },
      end: { x: Number(end.x.toFixed(3)), y: Number(end.y.toFixed(3)) },
    }
    this.walls.push(wall)
    return wall
  }

  public removeWall(id: string): boolean {
    const idx = this.walls.findIndex((w) => w.id === id)
    if (idx === -1) return false
    this.saveState()
    this.walls.splice(idx, 1)
    return true
  }

  public addZone(points: WorldPoint[], type: ZoneType = 'keep_out', name?: string, maxSpeed?: number): RestrictedZone {
    if (points.length < 3) {
      throw new Error('A zone must have at least 3 vertices.')
    }
    this.saveState()
    const zone: RestrictedZone = {
      id: `zone_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`,
      name: name ?? `禁区 ${this.zones.length + 1}`,
      type,
      points: points.map((p) => ({ x: Number(p.x.toFixed(3)), y: Number(p.y.toFixed(3)) })),
      maxSpeedMps: maxSpeed,
    }
    this.zones.push(zone)
    return zone
  }

  public removeZone(id: string): boolean {
    const idx = this.zones.findIndex((z) => z.id === id)
    if (idx === -1) return false
    this.saveState()
    this.zones.splice(idx, 1)
    return true
  }

  public clear(): void {
    this.saveState()
    this.walls = []
    this.zones = []
  }

  public undo(): boolean {
    if (this.historyStack.length === 0) return false
    const previous = this.historyStack.pop()!
    this.redoStack.push({
      walls: JSON.parse(JSON.stringify(this.walls)),
      zones: JSON.parse(JSON.stringify(this.zones)),
    })
    this.walls = previous.walls
    this.zones = previous.zones
    return true
  }

  public redo(): boolean {
    if (this.redoStack.length === 0) return false
    const next = this.redoStack.pop()!
    this.historyStack.push({
      walls: JSON.parse(JSON.stringify(this.walls)),
      zones: JSON.parse(JSON.stringify(this.zones)),
    })
    this.walls = next.walls
    this.zones = next.zones
    return true
  }

  /**
   * 碰撞检测：检查规划路径是否穿过虚拟墙或进入禁行区
   */
  public checkPathCollision(path: WorldPoint[]): {
    hasCollision: boolean
    collidedEntityId?: string
    collisionType?: 'wall' | 'zone'
  } {
    if (path.length < 2) return { hasCollision: false }

    for (let i = 1; i < path.length; i++) {
      const p1 = path[i - 1]
      const p2 = path[i]

      // 检查虚拟墙交点
      for (const wall of this.walls) {
        if (doLineSegmentsIntersect(p1, p2, wall.start, wall.end)) {
          return {
            hasCollision: true,
            collidedEntityId: wall.id,
            collisionType: 'wall',
          }
        }
      }

      // 检查禁行区
      for (const zone of this.zones) {
        if (zone.type === 'keep_out') {
          // 检查路径端点是否在多边形内
          if (isPointInsidePolygon(p1, zone.points) || isPointInsidePolygon(p2, zone.points)) {
            return {
              hasCollision: true,
              collidedEntityId: zone.id,
              collisionType: 'zone',
            }
          }
          // 检查路径线段是否与多边形边界边相交
          for (let j = 0; j < zone.points.length; j++) {
            const edgeStart = zone.points[j]
            const edgeEnd = zone.points[(j + 1) % zone.points.length]
            if (doLineSegmentsIntersect(p1, p2, edgeStart, edgeEnd)) {
              return {
                hasCollision: true,
                collidedEntityId: zone.id,
                collisionType: 'zone',
              }
            }
          }
        }
      }
    }

    return { hasCollision: false }
  }

  /**
   * 导出为 ROS2 Nav2 Costmap Filter 标准格式结构体
   */
  public toCostmapFilterPayload(): {
    filter_type: 'keepout' | 'speed_limit'
    polygons: Array<{
      points: Array<{ x: number; y: number }>
      type: string
      value?: number
    }>
  } {
    const polygons: Array<{
      points: Array<{ x: number; y: number }>
      type: string
      value?: number
    }> = []

    // 虚拟墙转换为细长多边形或几何线段
    for (const wall of this.walls) {
      polygons.push({
        type: 'wall',
        points: [
          { x: wall.start.x, y: wall.start.y },
          { x: wall.end.x, y: wall.end.y },
        ],
      })
    }

    // 禁区多边形
    for (const zone of this.zones) {
      polygons.push({
        type: zone.type,
        value: zone.maxSpeedMps,
        points: zone.points.map((p) => ({ x: p.x, y: p.y })),
      })
    }

    return {
      filter_type: 'keepout',
      polygons,
    }
  }
}
