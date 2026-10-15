import { describe, expect, it } from 'vitest'

import {
  distanceToSegment,
  doLineSegmentsIntersect,
  isPointInsidePolygon,
  MapZonesManager,
} from './map-zones'

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

  it('exports costmap filter payload conforming to Nav2 format', () => {
    const manager = new MapZonesManager()
    manager.addWall({ x: 1, y: 1 }, { x: 2, y: 2 })
    manager.addZone(
      [
        { x: 0, y: 0 },
        { x: 1, y: 0 },
        { x: 1, y: 1 },
      ],
      'speed_restricted',
      'Slow Zone',
      0.3,
    )

    const payload = manager.toCostmapFilterPayload()
    expect(payload.filter_type).toBe('keepout')
    expect(payload.polygons).toHaveLength(2)

    expect(payload.polygons[0].type).toBe('wall')
    expect(payload.polygons[0].points).toHaveLength(2)

    expect(payload.polygons[1].type).toBe('speed_restricted')
    expect(payload.polygons[1].value).toBe(0.3)
    expect(payload.polygons[1].points).toHaveLength(3)
  })
})
