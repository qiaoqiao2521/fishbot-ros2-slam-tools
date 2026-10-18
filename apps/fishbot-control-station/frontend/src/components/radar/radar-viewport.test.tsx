import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { RadarViewport } from '@/components/radar/radar-viewport'
import { mockNavigation, mockPerception, mockRobotState } from '@/lib/mock-station'
import { createDefaultRadarWorkbenchConfig } from '@/lib/radar-workbench'
import type { NavigationPathSnapshot } from '@/types/station'

const path: NavigationPathSnapshot = {
  ready: true, frameId: 'map', poseCount: 2, points: [{ x: 0, y: 0 }, { x: 1, y: 1 }],
  lastUpdate: '2026-10-13T00:00:00Z', statusMessage: 'latest Nav2 path report',
}

function viewport(pathReport = path, pathTelemetryLive = true) {
  return renderToStaticMarkup(<RadarViewport
    config={{ ...createDefaultRadarWorkbenchConfig(), layerMode: 'scan+map' }}
    mapMode="observe" draftPose={null} selectionDisabled={false} pathTelemetryLive={pathTelemetryLive}
    history={[]} scan={mockPerception.scan} robotState={mockRobotState} selectedPoint={null}
    onPointSelect={() => {}} onPoseSelect={() => {}}
    navigation={{ ...mockNavigation,
      map: { ...mockNavigation.map, ready: true, width: 200, height: 100, resolution: 0.05, originX: -5, originY: -2.5, originYaw: 0, sampledCells: [] },
      localization: { ...mockNavigation.localization, ready: true, x: 0, y: 0, yaw: Math.PI / 2 },
      path: pathReport,
    }}
  />)
}

describe('radar viewport map rendering', () => {
  it('renders the actual map-frame path with the shared projection', () => {
    const html = viewport()
    expect(html).toContain('data-testid="navigation-path"')
    expect(html).toContain('points="50,50 59.4,40.6"')
  })

  it('removes an empty replacement and never renders an odom-frame path', () => {
    expect(viewport({ ...path, points: [], poseCount: 0 })).not.toContain('data-testid="navigation-path"')
    expect(viewport({ ...path, frameId: 'odom' })).not.toContain('data-testid="navigation-path"')
  })

  it('does not present an offline or fallback path as live telemetry', () => {
    expect(viewport(path, false)).not.toContain('data-testid="navigation-path"')
  })

  it('points the rightward robot arrow north for positive ninety-degree yaw', () => {
    const html = viewport()
    expect(html).toContain('data-testid="map-robot-pose" transform="translate(50 50) rotate(-90)"')
    expect(html).toContain('points="2.4,0 -1.5,-1.1 -1.5,1.1"')
    expect(html).toContain('观察模式 · 仅查看地图')
    expect(html).not.toContain('data-testid="map-pose-draft"')
  })
  it('keeps distinct history geometry and the existing per-index fading after group reuse', () => {
    const frames = [structuredClone(mockPerception.scan), structuredClone(mockPerception.scan)]
    frames[0].lastUpdate = 'older'; frames[1].lastUpdate = 'newer'; frames[1].samplePoints[0].x += 1
    const html = renderToStaticMarkup(<RadarViewport config={createDefaultRadarWorkbenchConfig()} mapMode="observe" draftPose={null}
      selectionDisabled={false} pathTelemetryLive={false} history={frames} scan={mockPerception.scan} robotState={mockRobotState}
      selectedPoint={null} onPointSelect={() => {}} onPoseSelect={() => {}} navigation={mockNavigation} />)
    expect(html).toContain('data-radar-history="0" fill-opacity="0.42"')
    expect(html).toContain('data-radar-history="1" fill-opacity="0.33999999999999997"')
    expect(html.match(/r="0.38"/g)).toHaveLength(frames.reduce((sum, frame) => sum + frame.samplePoints.length, 0))
  })
})
