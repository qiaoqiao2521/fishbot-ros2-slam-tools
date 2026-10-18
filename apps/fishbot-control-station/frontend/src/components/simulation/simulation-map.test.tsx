import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { SimulationMapView } from '@/components/simulation/simulation-map'
import { WorkspaceVisibilityContext } from '@/components/workspace/workspace-visibility'
import type { SimulationGoalIssue, SimulationMap, SimulationState } from '@/lib/simulation'
import type { MapZone } from '@/lib/simulation-workspace'

const map: SimulationMap = { map_id: 'map-a', width: 40, height: 40, resolution: 0.1, origin: [-2, -2, 0], data: new Array(1600).fill(0) }
const wall: MapZone = { id: 'wall-a', kind: 'wall', points: [{ x: -1, y: 0 }, { x: 1, y: 0 }], width: 0.1 }
const zone: MapZone = { id: 'zone-a', kind: 'no_go', points: [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }, { x: 0, y: 1 }] }
const issue: SimulationGoalIssue = { kind: 'map_rule', target: 'waypoint', waypoint_index: 2,
  point: { x: -1, y: 0.05, yaw: 0 }, rule_id: 'wall-a', rule_kind: 'wall', rule_index: 1,
  required_clearance_m: 0.13, blocking_point: { x: -1, y: 0 }, map_id: 'map-a', rules_revision: 2 }

describe('simulation software constraint overlay', () => {
  it('highlights the exact selected rule or waypoint without changing the source geometry', () => {
    const selectedZone = renderToStaticMarkup(<SimulationMapView map={map} state={null} points={[]} editable onSelect={() => {}} zones={[wall]}
      selectedObject={{ kind: 'zone', id: wall.id }} />)
    expect(selectedZone).toContain('data-selected-zone="wall-a"')
    expect(selectedZone).toContain('points="10,20 30,20"')
    expect(selectedZone).toContain('属性修改只更新草稿')
    expect(selectedZone).toContain('pointer-events="none"')
    const selectedPoint = renderToStaticMarkup(<SimulationMapView map={map} state={null} points={[]} editable onSelect={() => {}}
      selectedObject={{ kind: 'waypoint', index: 2, point: { x: 1, y: -1, yaw: .4 } }} />)
    expect(selectedPoint).toContain('data-selected-waypoint="3"')
    expect(selectedPoint).toContain('cx="30" cy="30"')
    expect(selectedPoint).toContain('已选巡逻点 3（1.000, -1.000）米')
    expect(wall.points).toEqual([{ x: -1, y: 0 }, { x: 1, y: 0 }])
  })
  it('shows the attempted red segment and the exact snapped point without replacing native navigation data', () => {
    const html = renderToStaticMarkup(<SimulationMapView map={map} state={null} points={[{ x: -.2, y: 0, yaw: 0 }]} editable onSelect={() => {}}
      selectionPreview={{ start: { x: -1, y: 0 }, selection: { kind: 'snapped', requested: { x: 1, y: 0 }, point: { x: -.2, y: 0 }, reason: '保留安全间隔' } }}
      draftConflicts={[{ index: 0, start: { x: -1, y: 0 }, end: { x: 1, y: 0 }, entityId: 'wall-a', collisionType: 'wall' }]} />)
    expect(html).toContain('data-selection-preview="snapped"')
    expect(html).toContain('data-draft-conflict="wall-a"')
    expect(html).toContain('points="10,20 30,20"')
    expect(html).toContain('原目标')
    expect(html).toContain('安全吸附点')
    expect(html).toContain('实际绕行由 Nav2 规划')
    expect(html).toContain('pointer-events="none"')
  })
  it('keeps a nonzero departure point visible above the robot and diagnostic overlays at the same exact anchor', () => {
    const home = { x: 0.5, y: -0.5, yaw: 0.3 }
    const state: SimulationState = { mode: 'mujoco', domain: 107, ready: true, reason: '', pose: home,
      truth: { ...home, linear_speed: 0, angular_speed: 0 }, path: [],
      mission: { id: null, status: 'idle', current_index: 0, waypoints: [], return_home: false, message: '' },
      obstacle: { state: 'parked', x: null, y: null, size: 0.36 }, home }
    const html = renderToStaticMarkup(<SimulationMapView map={map} state={state} points={[]} editable onSelect={() => {}} goalIssue={issue} issueCurrent homeEmphasized />)
    expect(html).toContain('left:62.5%;top:62.5%')
    expect(html).toContain('本次出发点（0.50, -0.50）米')
    expect(html).toContain('data-home-emphasized="true"')
    expect(html.indexOf('simulation-home-marker')).toBeGreaterThan(html.indexOf('</svg>'))
    expect(html).toContain('data-goal-issue-current="true"')
    expect(html).not.toContain('本轮仿真起点')
  })

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

  it('makes a hidden canvas noninteractive while keeping original world coordinates', () => {
    const html = renderToStaticMarkup(<WorkspaceVisibilityContext.Provider value={false}>
      <SimulationMapView map={map} state={null} points={[]} editable onSelect={() => {}} zones={[wall]} savedZones={[wall]} />
    </WorkspaceVisibilityContext.Provider>)
    expect(html).toContain('data-workspace-visible="false"')
    expect(html).toContain('tabindex="-1"')
    expect(html).not.toContain('simulation-map-editable')
    expect(html).toContain('points="10,20 30,20"')
  })

  it('marks the authoritative rejected coordinate and footprint even if another draft is on the map', () => {
    const html = renderToStaticMarkup(<SimulationMapView map={map} state={null} points={[{ x: 1.5, y: 1.5, yaw: 0 }]} editable onSelect={() => {}} zones={[wall]} savedZones={[wall]} goalIssue={issue} issueCurrent />)
    expect(html).toContain('data-goal-issue-current="true"')
    expect(html).toContain('data-rule-issue="true"')
    const footprint = html.match(/<circle cx="([^"]+)" cy="([^"]+)" r="1.3"/)
    expect(Number(footprint?.[1])).toBeCloseTo(10)
    expect(Number(footprint?.[2])).toBeCloseTo(19.5)
    expect(html).toContain('拒绝点：巡逻点 2')
    const connector = html.match(/<line x1="([^"]+)" y1="([^"]+)" x2="10" y2="20"/)
    expect(Number(connector?.[1])).toBeCloseTo(10)
    expect(Number(connector?.[2])).toBeCloseTo(19.5)
    expect(html).toContain('pointer-events="none"')
  })

  it('keeps stale coordinates as a historical marker without accusing an edited rule', () => {
    const html = renderToStaticMarkup(<SimulationMapView map={map} state={null} points={[]} editable onSelect={() => {}} zones={[wall]} goalIssue={issue} issueCurrent={false} />)
    expect(html).toContain('data-goal-issue-current="false"')
    expect(html).toContain('上次拒绝点：巡逻点 2')
    expect(html).toContain('对应上一版路线或规则')
    expect(html).not.toContain('data-rule-issue')
  })

  it('does not place another map’s diagnostic on the current map', () => {
    const html = renderToStaticMarkup(<SimulationMapView map={map} state={null} points={[]} editable onSelect={() => {}} zones={[wall]} goalIssue={{ ...issue, map_id: 'other-map' }} issueCurrent />)
    expect(html).not.toContain('simulation-goal-issue-overlay')
    expect(html).not.toContain('data-rule-issue')
  })

  it('does not interpret two missing map identities as the same map', () => {
    const html = renderToStaticMarkup(<SimulationMapView map={{ ...map, map_id: undefined }} state={null} points={[]} editable onSelect={() => {}} goalIssue={{ ...issue, map_id: undefined }} issueCurrent />)
    expect(html).not.toContain('simulation-goal-issue-overlay')
  })
})
