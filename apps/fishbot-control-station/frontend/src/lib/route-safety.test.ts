import { describe, expect, it, vi } from 'vitest'
import { MapZonesManager, distanceToSegment } from './map-zones'
import { evaluateWaypointSelection, MAX_CONFLICT_POINTS, segmentConflicts, SNAP_MARGIN_M } from './route-safety'
import { worldToMap, type Point, type SimulationMap } from './simulation'
import type { MapZone } from './simulation-workspace'

const mapFixture = (rotated=false): SimulationMap => ({
  width:100,height:100,resolution:.1,origin:rotated ? [5,-5,Math.PI/2] : [-5,-5,0],data:Array(10_000).fill(0),
})
const wall = (x=0,id='wall',width=.02): MapZone => ({id,kind:'wall',width,points:[{x,y:-2},{x,y:2}]})
const area: MapZone={id:'area',kind:'no_go',points:[{x:0,y:-1},{x:1,y:-1},{x:1,y:1},{x:0,y:1}]}
const mark = (map: SimulationMap, point: Point, value=100) => {
  const pixel=worldToMap(point,map)
  map.data[Math.floor(map.height-pixel.y)*map.width+Math.floor(pixel.x)]=value
}
function requireSnap(result: ReturnType<typeof evaluateWaypointSelection>): Point {
  expect(result.kind).toBe('snapped')
  expect(result.point).toBeDefined()
  return result.point!
}

describe('Waypoint draft selection and first-boundary snapping', () => {
  it('accepts a clear target without changing input or pretending to plan a native route', () => {
    const start={x:-1,y:0}, requested={x:1,y:0}
    const result=evaluateWaypointSelection(start,requested,mapFixture(),[])
    expect(result).toMatchObject({kind:'accepted',requested,point:requested})
    expect(result.point).not.toBe(requested)
    expect(result.requested).not.toBe(requested)
    expect(result.reason).toContain('Nav2')
    result.point!.x=99
    expect(requested.x).toBe(1)
  })
  it('snaps before a thin wall and retains the exact original red-line request', () => {
    const requested={x:1.93743,y:0}, zones=[wall(.33333,'thin',.01)]
    const result=evaluateWaypointSelection({x:-1,y:0},requested,mapFixture(),zones)
    const point=requireSnap(result)
    expect(point.x).toBeCloseTo(.33333-.005-.13-SNAP_MARGIN_M,5)
    expect(point.x).toBeLessThan(.33333)
    expect(point.y).toBe(0)
    expect(result.requested).toEqual(requested)
    expect(result.conflict).toMatchObject({index:0,entityId:'thin',start:{x:-1,y:0},end:requested})
    const manager=MapZonesManager.fromMapRulesZones(zones)
    expect(manager.checkPathCollision([{x:-1,y:0},point],.13).hasCollision).toBe(false)
    expect(manager.checkPathCollision([point],.13+SNAP_MARGIN_M).hasCollision).toBe(false)
  })
  it('finds the first wall rather than whichever wall appears first in the array', () => {
    const result=evaluateWaypointSelection({x:-1,y:0},{x:1,y:0},mapFixture(),[wall(.6,'far'),wall(-.3,'near')])
    expect(requireSnap(result).x).toBeCloseTo(-.45,5)
    expect(result.conflict?.entityId).toBe('near')
  })
  it('preserves one centimetre of normal clearance against a diagonal wall', () => {
    const diagonal: MapZone={id:'diagonal',kind:'wall',width:.02,points:[{x:-2,y:-2},{x:2,y:2}]}
    const point=requireSnap(evaluateWaypointSelection({x:-1,y:0},{x:1,y:0},mapFixture(),[diagonal]))
    const centerClearance=distanceToSegment(point,diagonal.points[0],diagonal.points[1])
    expect(centerClearance-.01-.13).toBeGreaterThanOrEqual(.01)
    expect(centerClearance-.01-.13).toBeLessThan(.010001)
    expect(point.x).toBeCloseTo(-Math.SQRT2*.15,5)
  })
  it('handles collinear overlap and snaps before the wall endpoint', () => {
    const horizontal: MapZone={id:'collinear',kind:'wall',points:[{x:0,y:0},{x:2,y:0}]}
    const point=requireSnap(evaluateWaypointSelection({x:-1,y:0},{x:3,y:0},mapFixture(),[horizontal]))
    expect(point.x).toBeCloseTo(-.15,5)
    expect(point.x).toBeLessThan(0)
  })
  it('allows a grid-free request inside a no_go area to snap to its near edge', () => {
    const result=evaluateWaypointSelection({x:-1,y:0},{x:.5,y:0},mapFixture(),[area])
    expect(requireSnap(result).x).toBeCloseTo(-.14,5)
    expect(result.conflict?.collisionType).toBe('zone')
    expect(result.requested).toEqual({x:.5,y:0})
  })
  it('rejects an initial footprint already in a rule instead of guessing an escape direction', () => {
    for (const [start,zones] of [[{x:.5,y:0},[area]],[{x:-.14,y:0},[wall()]]] as const) {
      const result=evaluateWaypointSelection(start,{x:2,y:0},mapFixture(),[...zones])
      expect(result.kind).toBe('rejected')
      expect(result.point).toBeUndefined()
      expect(result.reason).toContain('起点车体')
      expect(result.conflict).toBeDefined()
    }
  })
  it('rejects when no forward snap can preserve the added one-centimetre clearance', () => {
    const result=evaluateWaypointSelection({x:-.145,y:0},{x:1,y:0},mapFixture(),[wall()])
    expect(result.kind).toBe('rejected')
    expect(result.reason).toContain('余量不足')
    expect(result.point).toBeUndefined()
  })
  it.each([100,-1])('rejects an occupied/unknown requested footprint with cell %s', (value) => {
    const map=mapFixture(); mark(map,{x:1,y:0},value)
    const result=evaluateWaypointSelection({x:-1,y:0},{x:1,y:0},map,[wall()])
    expect(result.kind).toBe('rejected')
    expect(result.reason).toContain('所选点')
    expect(result.point).toBeUndefined()
  })
  it('does not guess a physical obstacle boundary when the rule snap itself is occupied', () => {
    const map=mapFixture(); mark(map,{x:-.15,y:0})
    const result=evaluateWaypointSelection({x:-1,y:0},{x:1,y:0},map,[wall()])
    expect(result.kind).toBe('rejected')
    expect(result.reason).toContain('复验')
  })
  it('rejects an occupied start or an out-of-map request', () => {
    const map=mapFixture(); mark(map,{x:-1,y:0})
    expect(evaluateWaypointSelection({x:-1,y:0},{x:1,y:0},map,[]).reason).toContain('起点')
    expect(evaluateWaypointSelection({x:-1,y:0},{x:6,y:0},mapFixture(),[]).kind).toBe('rejected')
  })
  it('uses rotated map coordinates for free-point validation', () => {
    const rotated=mapFixture(true)
    const point=requireSnap(evaluateWaypointSelection({x:-1,y:0},{x:1,y:0},rotated,[wall()]))
    expect(point.x).toBeCloseTo(-.15,5)
    mark(rotated,{x:1,y:0})
    expect(evaluateWaypointSelection({x:-1,y:0},{x:1,y:0},rotated,[wall()]).kind).toBe('rejected')
  })
  it.each([NaN,Infinity,-Infinity])('rejects nonfinite input %s without throwing', (invalid) => {
    expect(evaluateWaypointSelection({x:-1,y:0},{x:invalid,y:0},mapFixture(),[]).kind).toBe('rejected')
    expect(evaluateWaypointSelection({x:invalid,y:0},{x:1,y:0},mapFixture(),[]).kind).toBe('rejected')
    expect(evaluateWaypointSelection({x:-1,y:0},{x:1,y:0},mapFixture(),[],invalid).kind).toBe('rejected')
  })
  it('rejects invalid map/rules/radius and tiny-resolution maps without scanning forever', () => {
    const map=mapFixture(); map.data=[]
    expect(evaluateWaypointSelection({x:-1,y:0},{x:1,y:0},map,[]).kind).toBe('rejected')
    expect(evaluateWaypointSelection({x:-1,y:0},{x:1,y:0},mapFixture(),[{...wall(),id:'invalid!'}]).kind).toBe('rejected')
    expect(evaluateWaypointSelection({x:-1,y:0},{x:1,y:0},mapFixture(),[],-.1).kind).toBe('rejected')
    const tiny=mapFixture(); tiny.resolution=Number.MIN_VALUE
    expect(evaluateWaypointSelection({x:0,y:0},{x:0,y:0},tiny,[]).kind).toBe('rejected')
  })
  it('bounds very long conflicted drafts before beginning the sampling loop', () => {
    const map: SimulationMap={width:2000,height:20,resolution:.1,origin:[-100,-1,0],data:Array(40_000).fill(0)}
    const calls=vi.spyOn(MapZonesManager.prototype,'checkPathCollision')
    try {
      const result=evaluateWaypointSelection({x:-40,y:0},{x:40,y:0},map,[wall()])
      expect(result.kind).toBe('rejected')
      expect(result.reason).toContain('预算')
      expect(calls.mock.calls.length).toBeLessThan(5)
      expect(evaluateWaypointSelection({x:-40,y:0},{x:40,y:0},map,[]).kind).toBe('rejected')
    } finally { calls.mockRestore() }
  })
  it('keeps an already-safe zero-length request and does not mutate map or zone input', () => {
    const map=mapFixture(), zones=[wall()]
    const original=structuredClone(zones), data=[...map.data]
    const result=evaluateWaypointSelection({x:-1,y:0},{x:-1,y:0},map,zones)
    expect(result.kind).toBe('accepted')
    expect(zones).toEqual(original)
    expect(map.data).toEqual(data)
  })
})

describe('Segment conflict overlays', () => {
  it('returns each actual conflicting segment with original endpoints', () => {
    const points=[{x:-1,y:0},{x:1,y:0},{x:-1,y:0}]
    const result=segmentConflicts(points,[wall()])
    expect(result.map((hit) => hit.index)).toEqual([0,1])
    expect(result[1]).toMatchObject({start:points[1],end:points[2],entityId:'wall',collisionType:'wall'})
    result[0].start.x=99
    expect(points[0].x).toBe(-1)
  })
  it('uses circular footprints by default while allowing explicit centerline semantics', () => {
    const horizontal: MapZone={id:'horizontal',kind:'wall',points:[{x:0,y:0},{x:2,y:0}]}
    const points=[{x:.2,y:.1},{x:1.8,y:.1}]
    expect(segmentConflicts(points,[horizontal])).toHaveLength(1)
    expect(segmentConflicts(points,[horizontal],0)).toEqual([])
  })
  it('handles stationary points and empty paths', () => {
    expect(segmentConflicts([{x:.5,y:0}],[area])[0].index).toBe(0)
    expect(segmentConflicts([],[])).toEqual([])
    expect(segmentConflicts([{x:-1,y:0}],[area])).toEqual([])
  })
  it('rejects invalid/sparse/oversized paths and invalid radii explicitly', () => {
    expect(() => segmentConflicts([{x:NaN,y:0}],[])).toThrow()
    expect(() => segmentConflicts(Array(2),[])).toThrow()
    expect(() => segmentConflicts(Array.from({length:MAX_CONFLICT_POINTS+1},()=>({x:0,y:0})),[])).toThrow()
    expect(() => segmentConflicts([],[],-1)).toThrow()
  })
})
