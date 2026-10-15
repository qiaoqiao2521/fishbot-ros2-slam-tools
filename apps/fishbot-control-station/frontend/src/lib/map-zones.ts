/** Frontend geometry and edit transactions. The backend remains the dispatch authority. */
import type { WorldPoint } from './radar-workbench'
import type { MapZone } from './simulation-workspace'

export interface VirtualWall {
  id: string
  name: string
  start: WorldPoint
  end: WorldPoint
  /** Full wall width, matching the existing map-rules contract. */
  width?: number
}
export type ZoneType = 'keep_out' | 'no_clean' | 'speed_restricted'
export interface RestrictedZone {
  id: string
  name: string
  type: ZoneType
  points: WorldPoint[]
  maxSpeedMps?: number
}
export interface MapZonesSnapshot {
  walls: VirtualWall[]
  zones: RestrictedZone[]
}
export type RosTime = { sec: number; nanosec: number }
export type RosHeader = { stamp: RosTime; frame_id: string }
export type NativeCostmapExport = {
  map_id: string
  revision: number
  info: { header: RosHeader; type: 0; filter_mask_topic: string; base: 0; multiplier: 1 }
  mask: {
    header: RosHeader
    info: {
      map_load_time: RosTime; resolution: number; width: number; height: number
      origin: {
        position: { x: number; y: number; z: number }
        orientation: { x: number; y: number; z: number; w: number }
      }
    }
    data: number[]
  }
}

const EPSILON = 1e-9
const DEFAULT_WALL_WIDTH_M = .02
const clone = <T>(value: T): T => structuredClone(value)
const object = (value: unknown, label: string): Record<string, unknown> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} must be an object.`)
  return value as Record<string, unknown>
}
const finite = (value: unknown, label: string): number => {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`${label} must be finite.`)
  return value
}
const point = (value: unknown, label = 'Point'): WorldPoint => {
  const p = object(value, label)
  return { x: finite(p.x, `${label}.x`), y: finite(p.y, `${label}.y`) }
}
const roundedPoint = (value: unknown): WorldPoint => {
  const p = point(value)
  return { x: Number(p.x.toFixed(3)), y: Number(p.y.toFixed(3)) }
}
const identifier = (value: unknown): string => {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{1,64}$/.test(value)) throw new Error('Invalid map-rule ID.')
  return value
}
const nameValue = (value: unknown): string => {
  if (typeof value !== 'string' || !value.trim()) throw new Error('Entity name must be nonempty.')
  return value
}
const wallWidth = (value: unknown = DEFAULT_WALL_WIDTH_M): number => {
  const width = finite(value, 'Wall width')
  if (width < .01 || width > .5) throw new Error('Wall width must be between 0.01 and 0.5 metres.')
  return width
}
const cross = (a: WorldPoint, b: WorldPoint, c: WorldPoint): number =>
  finite((b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x), 'Geometry cross product')
const orientation = (a: WorldPoint, b: WorldPoint, c: WorldPoint): number => {
  const value = cross(a, b, c)
  const tolerance = EPSILON*Math.max(Math.hypot(b.x-a.x, b.y-a.y), EPSILON)
  return Math.abs(value) <= tolerance ? 0 : Math.sign(value)
}
const onSegment = (a: WorldPoint, b: WorldPoint, p: WorldPoint): boolean =>
  orientation(a, b, p) === 0 && p.x >= Math.min(a.x,b.x)-EPSILON && p.x <= Math.max(a.x,b.x)+EPSILON
    && p.y >= Math.min(a.y,b.y)-EPSILON && p.y <= Math.max(a.y,b.y)+EPSILON

/** Includes endpoint contact, collinear overlap and zero-length segments. */
export function doLineSegmentsIntersect(p1: WorldPoint, p2: WorldPoint, p3: WorldPoint, p4: WorldPoint): boolean {
  const [a,b,c,d] = [p1,p2,p3,p4].map((p) => point(p))
  const abC = orientation(a,b,c), abD = orientation(a,b,d)
  const cdA = orientation(c,d,a), cdB = orientation(c,d,b)
  if (abC === 0 && onSegment(a,b,c) || abD === 0 && onSegment(a,b,d)
    || cdA === 0 && onSegment(c,d,a) || cdB === 0 && onSegment(c,d,b)) return true
  return abC*abD < 0 && cdA*cdB < 0
}

/** Boundary points count as inside. Fewer than three vertices remain an empty polygon. */
export function isPointInsidePolygon(value: WorldPoint, polygon: WorldPoint[]): boolean {
  const p = point(value)
  if (!Array.isArray(polygon)) throw new Error('Polygon must be an array.')
  const vertices = polygon.map((v) => point(v))
  if (vertices.length < 3) return false
  let inside = false
  for (let i=0,j=vertices.length-1; i<vertices.length; j=i++) {
    const a=vertices[j], b=vertices[i]
    if (onSegment(a,b,p)) return true
    if ((a.y>p.y) !== (b.y>p.y) && p.x < (b.x-a.x)*(p.y-a.y)/(b.y-a.y)+a.x) inside=!inside
  }
  return inside
}

export function distanceToSegment(value: WorldPoint, first: WorldPoint, second: WorldPoint): number {
  const p=point(value), a=point(first), b=point(second)
  const dx=b.x-a.x, dy=b.y-a.y, length=finite(Math.hypot(dx,dy), 'Segment length')
  if (length === 0) return finite(Math.hypot(p.x-a.x,p.y-a.y), 'Point distance')
  const ux=dx/length, uy=dy/length
  const along=Math.max(0,Math.min(length,(p.x-a.x)*ux+(p.y-a.y)*uy))
  return finite(Math.hypot(p.x-a.x-along*ux,p.y-a.y-along*uy), 'Point distance')
}
const segmentDistance = (a: WorldPoint,b: WorldPoint,c: WorldPoint,d: WorldPoint): number =>
  doLineSegmentsIntersect(a,b,c,d) ? 0 : Math.min(distanceToSegment(a,c,d),distanceToSegment(b,c,d),
    distanceToSegment(c,a,b),distanceToSegment(d,a,b))

function validPolygon(values: unknown, round = false): WorldPoint[] {
  if (!Array.isArray(values) || values.length < 3) throw new Error('A zone must have at least 3 vertices.')
  const points = values.map((p) => round ? roundedPoint(p) : point(p))
  if (points.some((p,i) => points.slice(i+1).some((q) => Math.hypot(p.x-q.x,p.y-q.y) <= EPSILON))) {
    throw new Error('A zone must have distinct vertices.')
  }
  let twiceArea=0
  for (let i=1;i<points.length-1;i++) twiceArea+=cross(points[0],points[i],points[i+1])
  if (!Number.isFinite(twiceArea) || Math.abs(twiceArea) <= EPSILON) throw new Error('A zone must have nonzero area.')
  for (let i=0;i<points.length;i++) {
    for (let j=i+1;j<points.length;j++) {
      if (j === i+1 || i === 0 && j === points.length-1) continue
      if (doLineSegmentsIntersect(points[i],points[(i+1)%points.length],points[j],points[(j+1)%points.length])) {
        throw new Error('A zone must not self-intersect.')
      }
    }
  }
  return points
}
function rectangle(values: WorldPoint[]): WorldPoint[] {
  // Backend no_go rectangles are axis aligned; input corner order is irrelevant.
  if (values.length !== 4) throw new Error('The backend supports four-corner no_go rectangles only.')
  const points=values.map((p) => point(p))
  const xs=[...new Set(points.map((p) => p.x))].sort((a,b) => a-b)
  const ys=[...new Set(points.map((p) => p.y))].sort((a,b) => a-b)
  if (xs.length !== 2 || ys.length !== 2 || xs[1]-xs[0] < 1e-6 || ys[1]-ys[0] < 1e-6
    || new Set(points.map((p) => `${p.x},${p.y}`)).size !== 4) {
    throw new Error('The backend supports nonzero axis-aligned no_go rectangles only.')
  }
  return [{x:xs[0],y:ys[0]},{x:xs[1],y:ys[0]},{x:xs[1],y:ys[1]},{x:xs[0],y:ys[1]}]
}
function wallValue(value: unknown): VirtualWall {
  const wall=object(value,'Wall'), start=point(wall.start), end=point(wall.end)
  if (finite(Math.hypot(end.x-start.x,end.y-start.y),'Wall length') < 1e-6) throw new Error('Wall endpoints must differ.')
  return {id:identifier(wall.id),name:nameValue(wall.name),start,end,width:wallWidth(wall.width)}
}
function zoneValue(value: unknown): RestrictedZone {
  const zone=object(value,'Zone')
  if (typeof zone.type !== 'string' || !['keep_out','no_clean','speed_restricted'].includes(zone.type)) throw new Error('Unsupported zone type.')
  const type=zone.type as ZoneType
  const maxSpeed=zone.maxSpeedMps === undefined ? undefined : finite(zone.maxSpeedMps,'Maximum speed')
  if (type === 'speed_restricted' && (maxSpeed === undefined || maxSpeed <= 0)) throw new Error('A speed zone needs a positive maximum speed.')
  if (type !== 'speed_restricted' && maxSpeed !== undefined) throw new Error('Maximum speed belongs to speed zones only.')
  return {id:identifier(zone.id),name:nameValue(zone.name),type,points:validPolygon(zone.points),
    ...(maxSpeed === undefined ? {} : {maxSpeedMps:maxSpeed})}
}

function rosTime(value: unknown, label: string): RosTime {
  const valueObject=object(value,label), sec=finite(valueObject.sec,`${label}.sec`), nanosec=finite(valueObject.nanosec,`${label}.nanosec`)
  if (!Number.isInteger(sec) || sec < 0 || sec > 2_147_483_647 || !Number.isInteger(nanosec) || nanosec < 0 || nanosec >= 1e9) throw new Error(`${label} is not a ROS time.`)
  return {sec,nanosec}
}
function rosHeader(value: unknown, label: string): RosHeader {
  const header=object(value,label)
  if (typeof header.frame_id !== 'string' || !header.frame_id.trim()) throw new Error(`${label}.frame_id is missing.`)
  return {stamp:rosTime(header.stamp,`${label}.stamp`),frame_id:header.frame_id}
}
/** Validate this project's backend-generated keepout export. This does not rasterize rules. */
export function validateNativeCostmapExport(value: unknown, expectedMapId: string, expectedRevision: number): NativeCostmapExport {
  if (typeof expectedMapId !== 'string' || !expectedMapId || !Number.isSafeInteger(expectedRevision) || expectedRevision < 0) {
    throw new Error('An expected map identity and revision are required.')
  }
  const root=object(value,'Native export')
  if (root.map_id !== expectedMapId || root.revision !== expectedRevision) throw new Error('Native export map identity or revision changed.')
  const info=object(root.info,'Filter info'), mask=object(root.mask,'Mask'), metadata=object(mask.info,'Mask metadata')
  if (info.type !== 0 || info.base !== 0 || info.multiplier !== 1) throw new Error('Expected this project’s keepout filter type 0, base 0 and multiplier 1.')
  if (info.filter_mask_topic !== '/keepout_filter_mask') throw new Error('Expected this project’s /keepout_filter_mask topic.')
  const infoHeader=rosHeader(info.header,'Filter info header'), maskHeader=rosHeader(mask.header,'Mask header')
  if (infoHeader.frame_id !== 'map' || maskHeader.frame_id !== 'map') throw new Error('Filter info and mask must use the map frame.')
  const width=finite(metadata.width,'Mask width'), height=finite(metadata.height,'Mask height'), resolution=finite(metadata.resolution,'Mask resolution')
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 || width > 4096 || height > 4096 || resolution <= 0) throw new Error('Invalid mask dimensions or resolution.')
  if (!Array.isArray(mask.data) || mask.data.length !== width*height
    || !Array.from(mask.data).every((cell) => typeof cell === 'number' && Number.isInteger(cell) && cell >= -1 && cell <= 100)) throw new Error('Invalid native OccupancyGrid data.')
  const origin=object(metadata.origin,'Mask origin'), position=object(origin.position,'Mask position'), orientationValue=object(origin.orientation,'Mask orientation')
  const parsedPosition={x:finite(position.x,'Origin x'),y:finite(position.y,'Origin y'),z:finite(position.z,'Origin z')}
  const quaternion={x:finite(orientationValue.x,'Orientation x'),y:finite(orientationValue.y,'Orientation y'),z:finite(orientationValue.z,'Orientation z'),w:finite(orientationValue.w,'Orientation w')}
  if (Math.abs(Math.hypot(quaternion.x,quaternion.y,quaternion.z,quaternion.w)-1) > 1e-3) throw new Error('Mask orientation must be a unit quaternion.')
  return {
    map_id:expectedMapId,revision:expectedRevision,
    info:{header:infoHeader,type:0,filter_mask_topic:info.filter_mask_topic,base:0,multiplier:1},
    mask:{header:maskHeader,info:{map_load_time:rosTime(metadata.map_load_time,'Map load time'),resolution,width,height,
      origin:{position:parsedPosition,orientation:quaternion}},data:[...mask.data] as number[]},
  }
}

export class MapZonesManager {
  private walls: VirtualWall[] = []
  private zones: RestrictedZone[] = []
  private historyStack: MapZonesSnapshot[] = []
  private redoStack: MapZonesSnapshot[] = []
  private nativeOrder: string[] = []

  constructor(initial?: Partial<MapZonesSnapshot>) {
    if (initial?.walls !== undefined) {
      if (!Array.isArray(initial.walls)) throw new Error('Walls must be an array.')
      this.walls=initial.walls.map(wallValue)
    }
    if (initial?.zones !== undefined) {
      if (!Array.isArray(initial.zones)) throw new Error('Zones must be an array.')
      this.zones=initial.zones.map(zoneValue)
    }
    const ids=[...this.walls,...this.zones].map((entity) => entity.id)
    if (new Set(ids).size !== ids.length) throw new Error('Map-rule IDs must be unique.')
  }

  static fromMapRulesZones(zones: MapZone[]): MapZonesManager {
    if (!Array.isArray(zones) || zones.length > 64) throw new Error('Provide at most 64 map rules.')
    const walls: VirtualWall[]=[], areas: RestrictedZone[]=[]
    for (const value of zones) {
      const zone=object(value,'Map rule'), id=identifier(zone.id)
      if (!Array.isArray(zone.points)) throw new Error('Map-rule points must be an array.')
      if (zone.kind === 'wall') {
        if (zone.points.length !== 2) throw new Error('A virtual wall needs exactly two points.')
        walls.push(wallValue({id,name:id,start:zone.points[0],end:zone.points[1],width:zone.width}))
      } else if (zone.kind === 'no_go') {
        if (zone.width !== undefined) throw new Error('Only virtual walls have a width.')
        areas.push({id,name:id,type:'keep_out',points:rectangle(zone.points as WorldPoint[])})
      } else throw new Error('Unsupported backend map-rule kind.')
    }
    const manager=new MapZonesManager({walls,zones:areas})
    manager.nativeOrder=zones.map((zone) => zone.id)
    return manager
  }

  toMapRulesZones(): MapZone[] {
    if (this.walls.length+this.zones.length > 64) throw new Error('The backend supports at most 64 map rules.')
    const zones: MapZone[] = [
      ...this.walls.map((wall): MapZone => ({id:wall.id,kind:'wall',points:[clone(wall.start),clone(wall.end)],width:wallWidth(wall.width)})),
      ...this.zones.map((zone): MapZone => {
        if (zone.type !== 'keep_out') throw new Error(`The backend does not support ${zone.type}; it was not converted to keepout.`)
        return {id:zone.id,kind:'no_go',points:rectangle(zone.points)}
      }),
    ]
    // Preserve backend input order; an import/export must not create a dirty edit.
    const order=new Map(this.nativeOrder.map((id,index) => [id,index]))
    return zones.sort((a,b) => (order.get(a.id) ?? Infinity)-(order.get(b.id) ?? Infinity))
  }

  private saveState(): void {
    this.historyStack.push(this.getSnapshot())
    this.redoStack=[]
  }
  getSnapshot(): MapZonesSnapshot { return clone({walls:this.walls,zones:this.zones}) }

  addWall(start: WorldPoint,end: WorldPoint,name?: string,widthM=DEFAULT_WALL_WIDTH_M): VirtualWall {
    const wall=wallValue({id:`wall_${crypto.randomUUID()}`,name:name ?? `虚拟墙 ${this.walls.length+1}`,
      start:roundedPoint(start),end:roundedPoint(end),width:widthM})
    this.saveState()
    this.walls.push(wall)
    return clone(wall)
  }
  removeWall(id: string): boolean {
    const index=this.walls.findIndex((wall) => wall.id === id)
    if (index < 0) return false
    this.saveState()
    this.walls.splice(index,1)
    return true
  }
  addZone(points: WorldPoint[],type: ZoneType='keep_out',name?: string,maxSpeed?: number): RestrictedZone {
    const zone=zoneValue({id:`zone_${crypto.randomUUID()}`,name:name ?? `禁区 ${this.zones.length+1}`,
      type,points:validPolygon(points,true),maxSpeedMps:maxSpeed})
    this.saveState()
    this.zones.push(zone)
    return clone(zone)
  }
  removeZone(id: string): boolean {
    const index=this.zones.findIndex((zone) => zone.id === id)
    if (index < 0) return false
    this.saveState()
    this.zones.splice(index,1)
    return true
  }
  clear(): void { this.saveState(); this.walls=[]; this.zones=[] }
  undo(): boolean {
    const previous=this.historyStack.pop()
    if (!previous) return false
    this.redoStack.push(this.getSnapshot())
    const restored=clone(previous)
    this.walls=restored.walls; this.zones=restored.zones
    return true
  }
  redo(): boolean {
    const next=this.redoStack.pop()
    if (!next) return false
    this.historyStack.push(this.getSnapshot())
    const restored=clone(next)
    this.walls=restored.walls; this.zones=restored.zones
    return true
  }

  /** Radius 0 checks the centerline; a nonzero radius checks the swept circular footprint. */
  checkPathCollision(path: WorldPoint[],footprintRadiusM=0): {
    hasCollision: boolean; collidedEntityId?: string; collisionType?: 'wall' | 'zone'
  } {
    if (!Array.isArray(path)) throw new Error('Path must be an array.')
    const radius=finite(footprintRadiusM,'Footprint radius')
    if (radius < 0) throw new Error('Footprint radius cannot be negative.')
    const points=path.map((p) => point(p))
    if (!points.length) return {hasCollision:false}
    // A single stationary point is a zero-length sweep, so it is still checked.
    for (let i=0;i<Math.max(1,points.length-1);i++) {
      const a=points[i],b=points[Math.min(i+1,points.length-1)]
      for (const wall of this.walls) {
        if (segmentDistance(a,b,wall.start,wall.end) <= radius+wallWidth(wall.width)/2+EPSILON) {
          return {hasCollision:true,collidedEntityId:wall.id,collisionType:'wall'}
        }
      }
      for (const zone of this.zones) {
        if (zone.type !== 'keep_out') continue
        if (isPointInsidePolygon(a,zone.points) || isPointInsidePolygon(b,zone.points)
          || zone.points.some((p,j) => segmentDistance(a,b,p,zone.points[(j+1)%zone.points.length]) <= radius+EPSILON)) {
          return {hasCollision:true,collidedEntityId:zone.id,collisionType:'zone'}
        }
      }
    }
    return {hasCollision:false}
  }

  static validateNativeCostmapExport(value: unknown,expectedMapId: string,expectedRevision: number): NativeCostmapExport {
    return validateNativeCostmapExport(value,expectedMapId,expectedRevision)
  }
  /** Returns a checked copy of the real backend keepout mask; never fabricates a ROS payload. */
  toCostmapFilterPayload(value: unknown,expectedMapId: string,expectedRevision: number): NativeCostmapExport {
    this.toMapRulesZones() // Reject unsupported local-only types before accepting an export.
    return validateNativeCostmapExport(value,expectedMapId,expectedRevision)
  }
}
