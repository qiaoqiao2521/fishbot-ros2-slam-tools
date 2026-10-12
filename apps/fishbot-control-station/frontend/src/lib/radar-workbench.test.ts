import { describe, expect, it } from 'vitest'

import { resolveAppRoute } from '@/lib/app-route'
import {
  buildRadarWorkbenchMetrics,
  cellWorldCenter,
  createDefaultRadarWorkbenchConfig,
  createMapProjection,
  isPointInsideMap,
  mapHeadingDegrees,
  mapPublicationBlocksDraft,
  mapPointerToWorld,
  renderableNavigationPath,
  resolveMapWorldBounds,
  scanPointInMapFrame,
  selectMapPose,
} from '@/lib/radar-workbench'
import type { LaserScanSnapshot, MapSnapshot } from '@/types/station'

const scan: LaserScanSnapshot = {
  ready: true,
  frameId: 'laser_frame',
  beamCount: 720,
  angleMin: -3.14,
  angleMax: 3.14,
  rangeMin: 0.1,
  rangeMax: 12,
  observedRange: 8.4,
  lastUpdate: '2026-03-23T06:00:00.000Z',
  statusMessage: 'laser scan sampled',
  samplePoints: [
    { angleRad: -2.9, rangeMeters: 4.2, x: -4.08, y: -1.0 },
    { angleRad: -2.1, rangeMeters: 0.52, x: -0.26, y: -0.45 },
    { angleRad: -1.4, rangeMeters: 0.68, x: 0.12, y: -0.67 },
    { angleRad: -0.2, rangeMeters: 2.1, x: 2.06, y: -0.41 },
    { angleRad: 0.5, rangeMeters: 3.7, x: 3.24, y: 1.77 },
    { angleRad: 1.2, rangeMeters: 1.9, x: 0.69, y: 1.77 },
    { angleRad: 2.4, rangeMeters: 0.74, x: -0.55, y: 0.49 },
  ],
}

describe('radar workbench helpers', () => {
  it('resolves /radar as the radar page and defaults everything else to dashboard', () => {
    expect(resolveAppRoute('/')).toBe('dashboard')
    expect(resolveAppRoute('/radar')).toBe('radar')
    expect(resolveAppRoute('/anything-else')).toBe('dashboard')
  })

  it('builds stable radar quality metrics from sampled scan points', () => {
    const metrics = buildRadarWorkbenchMetrics(scan)

    expect(metrics.beamCount).toBe(720)
    expect(metrics.sampleCount).toBe(7)
    expect(metrics.validRatio).toBeCloseTo(0.97, 1)
    expect(metrics.nearFieldCount).toBe(3)
    expect(metrics.coverageRatio).toBeGreaterThan(30)
    expect(metrics.obstructionLevel).toBe('moderate')
  })

  it('creates an interactive default config for the radar page', () => {
    expect(createDefaultRadarWorkbenchConfig()).toEqual({
      zoom: 1,
      freeze: false,
      showGhost: true,
      showSweep: true,
      showGrid: true,
      layerMode: 'scan',
    })
  })
})

describe('radar map projection helpers', () => {
  const map: MapSnapshot = {
    ready: true,
    width: 200,
    height: 100,
    resolution: 0.05,
    originX: -5,
    originY: -2.5,
    originYaw: 0,
    sampleStride: 2,
    lastUpdate: '2026-03-23T06:00:00.000Z',
    statusMessage: 'live occupancy grid sampled',
    sampledCells: [
      { x: 10, y: 20, occupancy: 100 },
      { x: 50, y: 20, occupancy: 0 },
      { x: 90, y: 40, occupancy: 50 },
    ],
  }

  it('resolves world bounds from origin, size and resolution', () => {
    const bounds = resolveMapWorldBounds(map)
    expect(bounds.minX).toBeCloseTo(-5)
    expect(bounds.minY).toBeCloseTo(-2.5)
    expect(bounds.maxX).toBeCloseTo(5)
    expect(bounds.maxY).toBeCloseTo(2.5)
  })

  it('projects the map with a uniform scale and keeps the center centered', () => {
    const projection = createMapProjection(resolveMapWorldBounds(map))
    const center = projection.toViewport({ x: 0, y: 0 })
    expect(center.left).toBeCloseTo(50)
    expect(center.top).toBeCloseTo(50)

    // 10m span maps to the usable 94 units -> 9.4 units per meter on both axes.
    const east = projection.toViewport({ x: 1, y: 0 })
    const north = projection.toViewport({ x: 0, y: 1 })
    expect(east.left - center.left).toBeCloseTo(9.4)
    expect(center.top - north.top).toBeCloseTo(9.4)
  })

  it('round-trips viewport clicks back into world coordinates', () => {
    const projection = createMapProjection(resolveMapWorldBounds(map))
    const world = projection.toWorld(63.2, 41.8)
    const back = projection.toViewport(world)
    expect(back.left).toBeCloseTo(63.2)
    expect(back.top).toBeCloseTo(41.8)
  })

  it('places cell centers from grid indices, stride and origin', () => {
    const center = cellWorldCenter({ x: 10, y: 20 }, map)
    expect(center.x).toBeCloseTo(-5 + 10.5 * 0.05)
    expect(center.y).toBeCloseTo(-2.5 + 20.5 * 0.05)
  })

  it('transforms scan points into the map frame using the localized pose', () => {
    const placed = scanPointInMapFrame({ x: 1, y: 0 }, { x: 2, y: 3, yaw: Math.PI / 2 })
    expect(placed.x).toBeCloseTo(2)
    expect(placed.y).toBeCloseTo(4)
  })

  it('bounds all four corners when the map origin is rotated', () => {
    const rotated = { ...map, originYaw: Math.PI / 2 }
    const bounds = resolveMapWorldBounds(rotated)
    expect(bounds.minX).toBeCloseTo(-10)
    expect(bounds.minY).toBeCloseTo(-2.5)
    expect(bounds.maxX).toBeCloseTo(-5)
    expect(bounds.maxY).toBeCloseTo(7.5)
    const projection = createMapProjection(resolveMapWorldBounds(rotated))
    const cell = cellWorldCenter({ x: 100, y: 50 }, rotated)
    const projected = projection.toViewport(cell)
    const restored = projection.toWorld(projected.left, projected.top)
    expect(restored.x).toBeCloseTo(cell.x)
    expect(restored.y).toBeCloseTo(cell.y)
  })

  it('rejects blank corners of a rotated map even when they lie inside its world bounds', () => {
    const rotated = { ...map, originYaw: Math.PI / 4 }
    const bounds = resolveMapWorldBounds(rotated)
    expect(isPointInsideMap({ x: bounds.minX + 0.01, y: bounds.minY + 0.01 }, rotated)).toBe(false)
    expect(isPointInsideMap(cellWorldCenter({ x: 100, y: 50 }, rotated), rotated)).toBe(true)
    expect(isPointInsideMap({ x: Number.NaN, y: 0 }, map)).toBe(false)
  })

  it('rejects letterboxes, SVG padding and map-free space for a wide touch viewport', () => {
    const projection = createMapProjection(resolveMapWorldBounds(map))
    const rect = { left: 10, top: 20, width: 800, height: 400 }
    expect(mapPointerToWorld({ clientX: 410, clientY: 220 }, rect, projection, map)).toEqual({ x: 0, y: 0 })
    expect(mapPointerToWorld({ clientX: 110, clientY: 220 }, rect, projection, map)).toBeNull()
    expect(mapPointerToWorld({ clientX: 218, clientY: 220 }, rect, projection, map)).toBeNull()
    expect(mapPointerToWorld({ clientX: 410, clientY: 60 }, rect, projection, map)).toBeNull()
    expect(mapPointerToWorld({ clientX: 410, clientY: 700 }, rect, projection, map)).toBeNull()
    expect(mapPointerToWorld({ clientX: 410, clientY: 220 }, { ...rect, width: 0 }, projection, map)).toBeNull()
  })

  it('keeps observe inert and selects a position before adjusting its direction', () => {
    expect(selectMapPose('observe', null, { x: 2, y: 3 }, { x: 4, y: 5 })).toBeNull()
    const selected = selectMapPose('goal', null, { x: 2, y: 3 }, { x: 2, y: 3 })
    expect(selected).toEqual({ x: 2, y: 3, yaw: 0 })
    const north = selectMapPose('goal', selected, { x: 2, y: 4 }, { x: 2, y: 4 })
    expect(north?.x).toBe(2)
    expect(north?.y).toBe(3)
    expect(north?.yaw).toBeCloseTo(Math.PI / 2)
    const dragged = selectMapPose('initial-pose', null, { x: 2, y: 3 }, { x: 1, y: 3 }, true)
    expect(dragged).toEqual({ x: 2, y: 3, yaw: Math.PI })
  })

  it('blocks a dispatched draft while pending, after publication and when its result is unknown', () => {
    expect(mapPublicationBlocksDraft('idle')).toBe(false)
    expect(mapPublicationBlocksDraft('error')).toBe(false)
    expect(mapPublicationBlocksDraft('sending')).toBe(true)
    expect(mapPublicationBlocksDraft('published')).toBe(true)
    expect(mapPublicationBlocksDraft('unconfirmed')).toBe(true)
  })

  it('uses the rightward arrow basis and rotates north upward in SVG coordinates', () => {
    expect(mapHeadingDegrees(0)).toBeCloseTo(0)
    expect(mapHeadingDegrees(Math.PI / 2)).toBeCloseTo(-90)
    expect(mapHeadingDegrees(-Math.PI / 2)).toBeCloseTo(90)
  })

  it('renders only finite map-frame paths and clears an empty replacement', () => {
    const path = { ready: true, frameId: 'map', poseCount: 2, points: [{ x: 1, y: 2 }, { x: 3, y: 4 }], lastUpdate: null, statusMessage: 'planned' }
    expect(renderableNavigationPath(path)).toEqual(path.points)
    expect(renderableNavigationPath({ ...path, frameId: 'odom' })).toEqual([])
    expect(renderableNavigationPath({ ...path, points: [] })).toEqual([])
    expect(renderableNavigationPath({ ...path, points: [{ x: Number.NaN, y: 2 }, { x: 3, y: 4 }] })).toEqual([])
    expect(renderableNavigationPath(undefined)).toEqual([])
  })
})
