import { describe, expect, it } from 'vitest'

import { resolveAppRoute } from '@/lib/app-route'
import { buildRadarWorkbenchMetrics, createDefaultRadarWorkbenchConfig } from '@/lib/radar-workbench'
import type { LaserScanSnapshot } from '@/types/station'

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
