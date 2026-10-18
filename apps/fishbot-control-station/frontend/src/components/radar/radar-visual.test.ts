import { describe, expect, it } from 'vitest'
import type { RadarViewportProps } from './radar-viewport'
import { radarViewportInputsEqual } from './radar-visual'
import { createDefaultRadarWorkbenchConfig } from '@/lib/radar-workbench'
import { mockNavigation, mockPerception, mockRobotState } from '@/lib/mock-station'

function input(): RadarViewportProps {
  return { config: createDefaultRadarWorkbenchConfig(), mapMode: 'observe', draftPose: null, selectionDisabled: false,
    pathTelemetryLive: true, history: [structuredClone(mockPerception.scan)], scan: structuredClone(mockPerception.scan),
    robotState: structuredClone(mockRobotState), navigation: structuredClone(mockNavigation), selectedPoint: null,
    onPoseSelect: () => {}, onPointSelect: () => {} }
}
function next(a: RadarViewportProps): RadarViewportProps {
  return { ...a, scan: structuredClone(a.scan), history: structuredClone(a.history), robotState: structuredClone(a.robotState), navigation: structuredClone(a.navigation) }
}
describe('radar visual geometry reuse', () => {
  it('does not rebuild static SVG for timestamp-only arrivals; the original snapshots stay intact', () => {
    const a = input(), b = next(a)
    b.scan.lastUpdate = 'new-source-receipt'; b.history[0].lastUpdate = 'new-history-receipt'
    b.navigation.localization.lastUpdate = 'new-location-receipt'; b.robotState.lastUpdatedAt = 'new-odom-receipt'
    expect(radarViewportInputsEqual(a, b)).toBe(true)
    expect(b.scan.lastUpdate).toBe('new-source-receipt'); expect(a.scan.lastUpdate).not.toBe(b.scan.lastUpdate)
  })
  it('redraws actual points, history, frame changes, or heading changes without a tolerance shortcut', () => {
    for (const mutate of [
      (b: RadarViewportProps) => { b.scan.samplePoints[0].x += 1e-9 },
      (b: RadarViewportProps) => { b.history[0].samplePoints[0].y += .01 },
      (b: RadarViewportProps) => { b.scan.frameId = 'different-frame' },
      (b: RadarViewportProps) => { b.robotState.odom.yaw += .01 },
      (b: RadarViewportProps) => { b.navigation.localization.ready = !b.navigation.localization.ready },
    ]) { const a = input(), b = next(a); mutate(b); expect(radarViewportInputsEqual(a, b)).toBe(false) }
  })
  it('preserves operator selection, callbacks, mode and disabled-state updates', () => {
    const a = input()
    for (const b of [{ ...a, selectedPoint: a.scan.samplePoints[0] }, { ...a, draftPose: { x: 1, y: 2, yaw: 0 } },
      { ...a, selectionDisabled: true }, { ...a, onPoseSelect: () => {} }, { ...a, mapMode: 'goal' as const },
      { ...a, config: { ...a.config, freeze: true } }]) expect(radarViewportInputsEqual(a, b)).toBe(false)
  })
  it('redraws changed map origin/yaw/cells, path replacement and telemetry loss', () => {
    const a = input(); a.config.layerMode = 'scan+map'; a.navigation.map.ready = true
    a.navigation.map.sampledCells = [{ x: 0, y: 0, occupancy: 0 }]
    a.navigation.path = { ready: true, frameId: 'map', poseCount: 2, points: [{ x: 0, y: 0 }, { x: 1, y: 1 }], lastUpdate: '', statusMessage: '' }
    for (const mutate of [
      (b: RadarViewportProps) => { b.navigation.map.originYaw += .01 },
      (b: RadarViewportProps) => { b.navigation.map.sampledCells[0].occupancy = 100 },
      (b: RadarViewportProps) => { b.navigation.path!.points[1].x += .01 },
      (b: RadarViewportProps) => { b.pathTelemetryLive = false },
    ]) { const b = next(a); mutate(b); expect(radarViewportInputsEqual(a, b)).toBe(false) }
  })
})
