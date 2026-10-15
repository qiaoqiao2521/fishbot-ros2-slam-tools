import { describe, expect, it } from 'vitest'

import {
  distanceToSegment,
  doLineSegmentsIntersect,
  isPointInsidePolygon,
  MapZonesManager,
  validateNativeCostmapExport,
  type NativeCostmapExport,
} from './map-zones'
import type { MapZone } from './simulation-workspace'

const square = [{x:0,y:0},{x:2,y:0},{x:2,y:2},{x:0,y:2}]
const nativeExport = (): NativeCostmapExport => ({
  map_id:'map-a',revision:3,
  info:{header:{frame_id:'map',stamp:{sec:5,nanosec:20}},type:0,
    filter_mask_topic:'/keepout_filter_mask',base:0,multiplier:1},
  mask:{header:{frame_id:'map',stamp:{sec:5,nanosec:20}},
    info:{map_load_time:{sec:1,nanosec:0},resolution:.05,width:2,height:2,
      origin:{position:{x:-1,y:-2,z:0},orientation:{x:0,y:0,z:0,w:1}}},data:[0,100,-1,0]},
})

describe('Map Geometry Helpers', () => {
  it('correctly determines line segment intersections', () => {
    // Cross: (0, 0)-(2, 2) and (0, 2)-(2, 0)
    expect(
      doLineSegmentsIntersect({ x: 0, y: 0 }, { x: 2, y: 2 }, { x: 0, y: 2 }, { x: 2, y: 0 }),
    ).toBe(true)

    // Parallel lines: (0, 0)-(2, 0) and (0, 1)-(2, 1)
    expect(
      doLineSegmentsIntersect({ x: 0, y: 0 }, { x: 2, y: 0 }, { x: 0, y: 1 }, { x: 2, y: 1 }),
    ).toBe(false)

    // Non-intersecting disjoint: (0, 0)-(1, 1) and (2, 2)-(3, 3)
    expect(
      doLineSegmentsIntersect({ x: 0, y: 0 }, { x: 1, y: 1 }, { x: 2, y: 2 }, { x: 3, y: 3 }),
    ).toBe(false)
  })

  it('correctly determines point in polygon via ray casting', () => {
    // Unit square: (0,0), (2,0), (2,2), (0,2)
    const square = [
      { x: 0, y: 0 },
      { x: 2, y: 0 },
      { x: 2, y: 2 },
      { x: 0, y: 2 },
    ]

    expect(isPointInsidePolygon({ x: 1, y: 1 }, square)).toBe(true)
    expect(isPointInsidePolygon({ x: 3, y: 3 }, square)).toBe(false)
    expect(isPointInsidePolygon({ x: -1, y: 1 }, square)).toBe(false)

    // Degenerate polygon (< 3 vertices) returns false
    expect(isPointInsidePolygon({ x: 0, y: 0 }, [{ x: 0, y: 0 }, { x: 1, y: 1 }])).toBe(false)
  })

  it('calculates point to line segment distance', () => {
    const a = { x: 0, y: 0 }
    const b = { x: 4, y: 0 }

    // Point perpendicular to segment midpoint
    expect(distanceToSegment({ x: 2, y: 3 }, a, b)).toBeCloseTo(3)

    // Point closest to endpoint A
    expect(distanceToSegment({ x: -3, y: 4 }, a, b)).toBeCloseTo(5)

    // Point closest to endpoint B
    expect(distanceToSegment({ x: 7, y: 4 }, a, b)).toBeCloseTo(5)
  })
})

describe('MapZonesManager', () => {
  it('manages virtual walls with undo and redo stack', () => {
    const manager = new MapZonesManager()
    const wall1 = manager.addWall({ x: 0, y: 0 }, { x: 2, y: 0 }, 'Wall 1')
    expect(manager.getSnapshot().walls).toHaveLength(1)
    expect(manager.getSnapshot().walls[0].id).toBe(wall1.id)

    const wall2 = manager.addWall({ x: 1, y: 1 }, { x: 1, y: 3 }, 'Wall 2')
    expect(manager.getSnapshot().walls).toHaveLength(2)

    // Undo adding wall 2
    expect(manager.undo()).toBe(true)
    expect(manager.getSnapshot().walls).toHaveLength(1)
    expect(manager.getSnapshot().walls[0].id).toBe(wall1.id)

    // Redo adding wall 2
    expect(manager.redo()).toBe(true)
    expect(manager.getSnapshot().walls).toHaveLength(2)
    expect(manager.getSnapshot().walls[1].id).toBe(wall2.id)

    // Remove wall 1
    expect(manager.removeWall(wall1.id)).toBe(true)
    expect(manager.getSnapshot().walls).toHaveLength(1)
    expect(manager.getSnapshot().walls[0].id).toBe(wall2.id)
  })

  it('manages restricted zones and validates minimum vertex count', () => {
    const manager = new MapZonesManager()
    expect(() => manager.addZone([{ x: 0, y: 0 }, { x: 1, y: 1 }])).toThrowError(
      'A zone must have at least 3 vertices.',
    )

    const zone = manager.addZone(
      [
        { x: 0, y: 0 },
        { x: 2, y: 0 },
        { x: 2, y: 2 },
        { x: 0, y: 2 },
      ],
      'keep_out',
      'No Entry Area',
    )

    expect(manager.getSnapshot().zones).toHaveLength(1)
    expect(zone.name).toBe('No Entry Area')
    expect(zone.type).toBe('keep_out')

    manager.removeZone(zone.id)
    expect(manager.getSnapshot().zones).toHaveLength(0)
  })

  it('detects collisions between robot trajectory and virtual walls or keep-out zones', () => {
    const manager = new MapZonesManager()
    const wall = manager.addWall({ x: 2, y: -2 }, { x: 2, y: 2 }, 'Barrier')
    const zone = manager.addZone(
      [
        { x: 5, y: 0 },
        { x: 7, y: 0 },
        { x: 7, y: 2 },
        { x: 5, y: 2 },
      ],
      'keep_out',
    )

    // Clear path
    const clearPath = [
      { x: 0, y: -5 },
      { x: 1, y: -5 },
    ]
    expect(manager.checkPathCollision(clearPath).hasCollision).toBe(false)

    // Path crossing the virtual wall at x = 2
    const wallCrossingPath = [
      { x: 0, y: 0 },
      { x: 4, y: 0 },
    ]
    const wallCollision = manager.checkPathCollision(wallCrossingPath)
    expect(wallCollision.hasCollision).toBe(true)
    expect(wallCollision.collisionType).toBe('wall')
    expect(wallCollision.collidedEntityId).toBe(wall.id)

    // Path penetrating the keep out zone
    const zoneCrossingPath = [
      { x: 4, y: 1 },
      { x: 6, y: 1 },
    ]
    const zoneCollision = manager.checkPathCollision(zoneCrossingPath)
    expect(zoneCollision.hasCollision).toBe(true)
    expect(zoneCollision.collisionType).toBe('zone')
    expect(zoneCollision.collidedEntityId).toBe(zone.id)
  })

  it('validates a native backend keepout export instead of inventing polygons', () => {
    const manager = new MapZonesManager()
    manager.addWall({ x: 1, y: 1 }, { x: 2, y: 2 })
    const source=nativeExport()
    const payload=manager.toCostmapFilterPayload(source,'map-a',3)
    expect(payload).toEqual(source)
    expect(payload).not.toHaveProperty('polygons')
    expect(payload.info.type).toBe(0)
    payload.mask.data[0]=100
    payload.mask.info.origin.position.x=99
    payload.info.header.stamp.sec=99
    expect(source.mask.data[0]).toBe(0)
    expect(source.mask.info.origin.position.x).toBe(-1)
    expect(source.info.header.stamp.sec).toBe(5)
  })
})

describe('Map geometry boundaries and swept footprints', () => {
  it.each([
    [[.5,0],[1.5,0]], [[2,0],[3,0]], [[1,-1],[1,0]], [[1,0],[1,-1]],
    [[1,0],[1,0]], [[0,0],[2,0]],
  ])('detects collinear overlap and contact for %j', (a,b) => {
    const start={x:a[0],y:a[1]}, end={x:b[0],y:b[1]}
    expect(doLineSegmentsIntersect(start,end,{x:0,y:0},{x:2,y:0})).toBe(true)
    expect(doLineSegmentsIntersect(end,start,{x:2,y:0},{x:0,y:0})).toBe(true)
    const manager=new MapZonesManager()
    manager.addWall({x:0,y:0},{x:2,y:0})
    expect(manager.checkPathCollision([start,end]).collisionType).toBe('wall')
  })
  it('does not join disjoint collinear segments', () => {
    expect(doLineSegmentsIntersect({x:0,y:0},{x:1,y:0},{x:1.1,y:0},{x:2,y:0})).toBe(false)
  })
  it.each([{x:0,y:1},{x:2,y:1},{x:1,y:0},{x:1,y:2},{x:2,y:2}])('includes polygon edge %j', (point) => {
    expect(isPointInsidePolygon(point,square)).toBe(true)
    const manager=new MapZonesManager(); manager.addZone(square)
    expect(manager.checkPathCollision([point]).collisionType).toBe('zone')
  })
  it('checks a single occupied point, boundary-following path and empty path', () => {
    const manager=new MapZonesManager(); manager.addZone(square)
    expect(manager.checkPathCollision([{x:1,y:1}]).hasCollision).toBe(true)
    expect(manager.checkPathCollision([{x:2,y:.5},{x:2,y:1.5}]).hasCollision).toBe(true)
    expect(manager.checkPathCollision([{x:3,y:3}]).hasCollision).toBe(false)
    expect(manager.checkPathCollision([])).toEqual({hasCollision:false})
  })
  it('distinguishes a clear centerline from a colliding circular footprint', () => {
    const manager=new MapZonesManager(); manager.addWall({x:0,y:0},{x:2,y:0})
    const path=[{x:.2,y:.1},{x:1.8,y:.1}]
    expect(manager.checkPathCollision(path).hasCollision).toBe(false)
    expect(manager.checkPathCollision(path,.13).hasCollision).toBe(true)
    expect(manager.checkPathCollision([{x:-.1,y:0}],.13).hasCollision).toBe(true)
    expect(manager.checkPathCollision([{x:.2,y:.141},{x:1.8,y:.141}],.13).hasCollision).toBe(false)
    expect(manager.checkPathCollision([{x:.2,y:.14},{x:1.8,y:.14}],.13).hasCollision).toBe(true)
  })
  it('checks the continuous sweep against a zone even when endpoints are clear', () => {
    const manager=new MapZonesManager(); manager.addZone(square)
    const path=[{x:-1,y:2.1},{x:3,y:2.1}]
    expect(manager.checkPathCollision(path).hasCollision).toBe(false)
    expect(manager.checkPathCollision(path,.13).collisionType).toBe('zone')
    expect(manager.checkPathCollision([{x:-1,y:1},{x:3,y:1}]).collisionType).toBe('zone')
  })
})

describe('Map rule transactions and input boundaries', () => {
  it('deeply separates constructor input, snapshots and add return values', () => {
    const input={id:'original',name:'Original',start:{x:0,y:0},end:{x:2,y:0}}
    const manager=new MapZonesManager({walls:[input]})
    input.start.y=99
    const returned=manager.addZone(square)
    const snapshot=manager.getSnapshot()
    snapshot.walls[0].end.x=99
    snapshot.zones[0].points[0].x=99
    returned.points[0].x=-99
    expect(manager.getSnapshot().walls[0].start.y).toBe(0)
    expect(manager.getSnapshot().walls[0].end.x).toBe(2)
    expect(manager.getSnapshot().zones[0].points[0].x).toBe(0)
    const wall=manager.addWall({x:3,y:0},{x:4,y:0})
    wall.start.y=99
    expect(manager.getSnapshot().walls[1].start.y).toBe(0)
  })
  it('does not let external edits pollute undo/redo and invalid additions preserve redo', () => {
    const manager=new MapZonesManager()
    const wall=manager.addWall({x:0,y:0},{x:2,y:0})
    manager.addZone(square)
    manager.undo()
    manager.getSnapshot().walls[0].start.y=10
    wall.end.x=99
    expect(() => manager.addWall({x:0,y:0},{x:0,y:0})).toThrow()
    expect(manager.redo()).toBe(true)
    expect(manager.getSnapshot().walls[0].start.y).toBe(0)
    expect(manager.getSnapshot().walls[0].end.x).toBe(2)
    manager.undo(); manager.undo(); manager.redo(); manager.redo()
    expect(manager.getSnapshot().zones[0].points).toEqual(square)
  })
  it('clears redo only after a valid new transaction', () => {
    const manager=new MapZonesManager(); manager.addWall({x:0,y:0},{x:2,y:0})
    manager.addZone(square); manager.undo()
    manager.addWall({x:3,y:0},{x:4,y:0})
    expect(manager.redo()).toBe(false)
    expect(manager.removeWall('missing')).toBe(false)
    manager.clear(); expect(manager.getSnapshot()).toEqual({walls:[],zones:[]})
    expect(manager.undo()).toBe(true)
    expect(manager.getSnapshot().walls).toHaveLength(2)
  })
  it.each([NaN,Infinity,-Infinity])('rejects nonfinite coordinates %s without a transaction', (value) => {
    const manager=new MapZonesManager()
    expect(() => manager.addWall({x:value,y:0},{x:2,y:0})).toThrow()
    expect(() => manager.addZone([{x:value,y:0},{x:2,y:0},{x:2,y:2}])).toThrow()
    expect(() => manager.checkPathCollision([{x:0,y:value}])).toThrow()
    expect(() => distanceToSegment({x:value,y:0},{x:0,y:0},{x:1,y:0})).toThrow()
    expect(() => manager.checkPathCollision([],value)).toThrow()
    expect(manager.undo()).toBe(false)
  })
  it('rejects zero-size, rounded-collapse, duplicate and self-crossing geometry', () => {
    const manager=new MapZonesManager()
    expect(() => manager.addWall({x:0,y:0},{x:.0001,y:0})).toThrow()
    expect(() => manager.addWall({x:0,y:0},{x:1,y:0},'wall',0)).toThrow()
    expect(() => manager.addZone([{x:0,y:0},{x:1,y:0},{x:2,y:0}])).toThrow()
    expect(() => manager.addZone([{x:0,y:0},{x:1,y:0},{x:0,y:0}])).toThrow()
    expect(() => manager.addZone([{x:0,y:0},{x:2,y:2},{x:0,y:2},{x:2,y:0}])).toThrow()
    expect(() => manager.addZone(square,'speed_restricted')).toThrow()
    expect(() => manager.addZone(square,'speed_restricted','slow',-.1)).toThrow()
    expect(() => manager.checkPathCollision([],-.1)).toThrow()
    expect(manager.undo()).toBe(false)
  })
  it('rejects duplicate imported IDs', () => {
    const wall={id:'same',name:'wall',start:{x:0,y:0},end:{x:1,y:0}}
    expect(() => new MapZonesManager({walls:[wall,wall]})).toThrow('unique')
  })
})

describe('Existing map-rule adapters', () => {
  it('round-trips native walls and rectangles without sharing their points', () => {
    const source: MapZone[]=[{id:'wall-a',kind:'wall',width:.04,points:[{x:-2,y:0},{x:-1,y:0}]},
      {id:'zone-a',kind:'no_go',points:square.map((p) => ({...p}))}]
    const manager=MapZonesManager.fromMapRulesZones(source)
    expect(manager.toMapRulesZones()).toEqual(source)
    source[0].points[0].x=-99
    const exported=manager.toMapRulesZones(); exported[1].points[0].x=99
    expect(manager.toMapRulesZones()[0].points[0].x).toBe(-2)
    expect(manager.toMapRulesZones()[1].points[0].x).toBe(0)
    expect(manager.checkPathCollision([{x:-1.5,y:.019}]).hasCollision).toBe(true)
  })
  it('normalizes rectangle corner order and defaults the existing wall width', () => {
    const manager=MapZonesManager.fromMapRulesZones([{id:'r',kind:'no_go',points:[square[2],square[0],square[3],square[1]]},
      {id:'w',kind:'wall',points:[{x:3,y:0},{x:4,y:0}]}])
    expect(manager.toMapRulesZones().find((zone) => zone.id === 'r')?.points).toEqual(square)
    expect(manager.toMapRulesZones().find((zone) => zone.id === 'w')?.width).toBe(.02)
    expect(manager.toMapRulesZones().map((zone) => zone.id)).toEqual(['r','w'])
  })
  it.each(['no_clean','speed_restricted'] as const)('explicitly rejects unsupported %s export', (type) => {
    const manager=new MapZonesManager(); manager.addZone(square,type,'zone',type === 'speed_restricted' ? .3 : undefined)
    expect(() => manager.toMapRulesZones()).toThrow('does not support')
    expect(() => manager.toCostmapFilterPayload(nativeExport(),'map-a',3)).toThrow('does not support')
  })
  it('rejects nonrectangular native areas, wall arity and excess rule count', () => {
    expect(() => MapZonesManager.fromMapRulesZones([{id:'t',kind:'no_go',points:square.slice(0,3)}])).toThrow()
    expect(() => MapZonesManager.fromMapRulesZones([{id:'w',kind:'wall',points:square}])).toThrow()
    expect(() => MapZonesManager.fromMapRulesZones([{id:'r',kind:'no_go',width:.1,points:square}])).toThrow()
    const manager=new MapZonesManager(); manager.addZone([{x:0,y:0},{x:1,y:0},{x:0,y:1}])
    expect(() => manager.toMapRulesZones()).toThrow('four-corner')
    expect(() => MapZonesManager.fromMapRulesZones(Array.from({length:65},(_,i) => ({id:`w${i}`,kind:'wall',points:[{x:0,y:0},{x:1,y:0}]})))).toThrow('64')
  })
})

describe('Native backend keepout export boundary', () => {
  it('requires exact map/revision and type 0 instead of accepting speed or fake polygons', () => {
    expect(() => validateNativeCostmapExport(nativeExport(),'map-b',3)).toThrow('identity')
    expect(() => validateNativeCostmapExport(nativeExport(),'map-a',4)).toThrow('revision')
    expect(() => validateNativeCostmapExport(nativeExport(),'map-a',NaN)).toThrow()
    expect(() => validateNativeCostmapExport({filter_type:'keepout',polygons:[]},'map-a',3)).toThrow()
    for (const mutation of [(value: NativeCostmapExport) => {Object.assign(value.info,{type:1})},
      (value: NativeCostmapExport) => {Object.assign(value.info,{base:1})},
      (value: NativeCostmapExport) => {Object.assign(value.info,{multiplier:100})}]) {
      const value=nativeExport(); mutation(value)
      expect(() => validateNativeCostmapExport(value,'map-a',3)).toThrow('type 0')
    }
  })
  it('validates standard timestamps, dimensions, frames, origin and grid data', () => {
    const mutations: ((value: NativeCostmapExport) => void)[]=[
      (v) => {v.mask.header.frame_id='odom'}, (v) => {v.info.header.frame_id=''},
      (v) => {v.info.header.stamp.nanosec=1e9}, (v) => {v.mask.info.map_load_time.sec=-1},
      (v) => {v.mask.info.map_load_time.sec=2_147_483_648},
      (v) => {v.mask.info.width=4097}, (v) => {v.mask.info.height=0}, (v) => {v.mask.info.width=1.5},
      (v) => {v.mask.info.resolution=0}, (v) => {v.mask.info.resolution=Infinity},
      (v) => {v.mask.info.origin.position.x=NaN}, (v) => {v.mask.info.origin.orientation.w=0},
      (v) => {v.mask.data=[0]}, (v) => {v.mask.data[0]=101}, (v) => {v.mask.data[0]=.5},
      (v) => {v.mask.data=Array(4)},
      (v) => {v.info.filter_mask_topic='relative'},
      (v) => {v.info.filter_mask_topic='/some_other_mask'},
      (v) => {v.info.header.frame_id='odom'; v.mask.header.frame_id='odom'},
    ]
    for (const mutation of mutations) {
      const value=nativeExport(); mutation(value)
      expect(() => validateNativeCostmapExport(value,'map-a',3)).toThrow()
    }
    const coarse=nativeExport(); coarse.mask.info.resolution=2
    expect(MapZonesManager.validateNativeCostmapExport(coarse,'map-a',3).mask.info.resolution).toBe(2)
  })
})
