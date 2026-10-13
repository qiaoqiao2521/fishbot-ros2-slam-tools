import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { SimulationMapView } from '@/components/simulation/simulation-map'
import type { SimulationMap } from '@/lib/simulation'
import type { MapZone } from '@/lib/simulation-workspace'

const map: SimulationMap = { map_id: 'map-a', width: 40, height: 40, resolution: 0.1, origin: [-2, -2, 0], data: new Array(1600).fill(0) }
const wall: MapZone = { id: 'wall-a', kind: 'wall', points: [{ x: -1, y: 0 }, { x: 1, y: 0 }], width: 0.1 }
const zone: MapZone = { id: 'zone-a', kind: 'no_go', points: [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }, { x: 0, y: 1 }] }

describe('simulation software constraint overlay', () => {
  it('renders saved walls and unsaved rectangles as software overlays with actual world coordinates', () => {
    const html = renderToStaticMarkup(<SimulationMapView map={map} state={null} points={[]} editable onSelect={() => {}} mode="no_go" zones={[wall, zone]} savedZones={[wall]} />)
    expect(html).toContain('points="10,20 30,20"')
    expect(html).toContain('已保存虚拟墙')
    expect(html).toContain('禁区草稿')
    expect(html).toContain('points="20,20 30,20 30,10 20,10"')
    expect(html).toContain('当前禁区模式')
  })

  it('keeps observation mode labeled and does not expose an editable keyboard target', () => {
    const html = renderToStaticMarkup(<SimulationMapView map={map} state={null} points={[]} editable={false} onSelect={() => {}} mode="observe" />)
    expect(html).toContain('当前观察模式')
    expect(html).toContain('tabindex="-1"')
    expect(html).not.toContain('simulation-map-editable')
  })
})
