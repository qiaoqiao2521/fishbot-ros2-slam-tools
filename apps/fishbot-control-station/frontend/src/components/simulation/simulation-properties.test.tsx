import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import { SimulationProperties, type SimulationObjectSelection } from './simulation-properties'
import { goalDraftIdentity } from '@/lib/simulation-errors'
import type { Pose, SimulationGoalIssue, SimulationMap } from '@/lib/simulation'
import { parseObjectPoseFields, type MapZone, type SavedRoute } from '@/lib/simulation-workspace'

const map: SimulationMap = { map_id: 'map-a', width: 40, height: 20, resolution: .1, origin: [-2, -1, Math.PI / 2], data: new Array(800).fill(0) }
const point: Pose = { x: .42, y: -.23, yaw: Math.PI / 4 }
const wall: MapZone = { id: 'wall-a', kind: 'wall', points: [{ x: -1, y: 0 }, { x: 1, y: .5 }], width: .04 }
const route: SavedRoute = { id: 'route-a', name: '工位往返', map_id: 'map-a', revision: 3, waypoints: [point], return_home: true }
const issue: SimulationGoalIssue = { kind: 'map_rule', target: 'waypoint', waypoint_index: 1, point,
  rule_id: 'wall-a', rule_kind: 'wall', rule_index: 1, map_id: 'map-a', rules_revision: 3 }
const identity = goalDraftIdentity([point], true)

function render(selection: SimulationObjectSelection, overrides: Partial<Parameters<typeof SimulationProperties>[0]> = {}) {
  return renderToStaticMarkup(<SimulationProperties selection={selection} map={map} zones={[wall]} points={[point]}
    routes={[route]} pointIdentity={identity} revision={3} goalIssue={null} issueCurrent={false} {...overrides} />)
}

describe('simulation object inspection', () => {
  it('uses world coordinates and the map yaw for scene inspection', () => {
    const html = render({ kind: 'scene' })
    expect(html).toContain('map-a')
    expect(html).toContain('4.00 × 2.00 米')
    expect(html).toContain('-2.00, -1.00 米')
    expect(html).toContain('90.0°')
    expect(html).not.toContain('<button')
  })

  it('shows the selected waypoint and only its matching authoritative rejection', () => {
    const html = render({ kind: 'waypoint', index: 0, draftIdentity: identity }, { goalIssue: issue, issueCurrent: true })
    expect(html).toContain('巡逻点 1')
    expect(html).toContain('0.420 米')
    expect(html).toContain('-0.230 米')
    expect(html).toContain('45.0°')
    expect(html).toContain('本次拒绝详情')
    expect(html).toContain('车体范围与虚拟墙 1冲突')
    expect(render({ kind: 'waypoint', index: 0, draftIdentity: identity }, { goalIssue: { ...issue, point: { ...point, x: 1 } }, issueCurrent: true }))
      .not.toContain('本次拒绝详情')
  })

  it('does not relabel another point after a draft change or reorder', () => {
    const html = render({ kind: 'waypoint', index: 0, draftIdentity: identity }, {
      points: [{ x: 1, y: 2, yaw: 0 }], pointIdentity: 'changed-draft', goalIssue: issue,
    })
    expect(html).toContain('选中对象已随草稿或地图变化，请重新选择')
    expect(html).not.toContain('1.000 米')
    expect(html).not.toContain('上次拒绝记录')
  })

  it('pairs a wall by its stable id and keeps a previous rejection historical', () => {
    const html = render({ kind: 'zone', id: wall.id }, { goalIssue: issue })
    expect(html).toContain('wall-a')
    expect(html).toContain('0.040 米')
    expect(html).toContain('-1.000, 0.000 米')
    expect(html).toContain('上次拒绝记录')
    expect(html).toContain('不代表当前对象仍被拒绝')
    expect(html).not.toContain('本次拒绝详情')
  })

  it('does not associate a rejection from another map or another rule', () => {
    expect(render({ kind: 'zone', id: wall.id }, { goalIssue: { ...issue, map_id: 'other-map' }, issueCurrent: true }))
      .not.toContain('拒绝详情')
    expect(render({ kind: 'zone', id: wall.id }, { goalIssue: { ...issue, rule_id: 'wall-b' }, issueCurrent: true }))
      .not.toContain('拒绝详情')
    expect(render({ kind: 'zone', id: 'removed-wall' }, { goalIssue: issue }))
      .toContain('选中对象已随草稿或地图变化，请重新选择')
  })

  it('inspects a route without exposing a load or motion command', () => {
    const html = render({ kind: 'route', id: route.id })
    expect(html).toContain('工位往返')
    expect(html).toContain('route-a')
    expect(html).toContain('返回本次出发点')
    expect(html).not.toContain('<button')
    expect(html).not.toContain('载入草稿')
    expect(html).toContain('属性查看不会发送运动命令')
  })

  it('offers explicit draft edits without submitting on render and disables them while locked', () => {
    const apply = vi.fn(() => null)
    const html = render({ kind: 'waypoint', index: 0, draftIdentity: identity }, { onApply: apply, editable: true })
    expect(html).toContain('aria-label="编辑所选对象草稿"')
    expect(html).toContain('aria-label="朝向（度）"')
    expect(html).toContain('应用到草稿')
    expect(html).not.toMatch(/type="submit" disabled/)
    const locked = render({ kind: 'waypoint', index: 0, draftIdentity: identity }, { onApply: apply, editable: false })
    expect(locked).toContain('type="submit" disabled=""')
    expect(locked).toContain('当前任务、保存或连接状态不允许修改')
    expect(apply).not.toHaveBeenCalled()
  })

  it('exposes only translation for an axis-aligned forbidden area', () => {
    const area: MapZone = { id: 'area', kind: 'no_go', points: [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }, { x: 0, y: 1 }] }
    const html = render({ kind: 'zone', id: area.id }, { zones: [area], onApply: () => null, editable: true })
    expect(html).toContain('中心 X（米）')
    expect(html).toContain('只修改中心位置')
    expect(html).not.toContain('aria-label="朝向（度）"')
  })

  it('explains unsupported source geometry instead of crashing an object inspection', () => {
    const malformed = { ...wall, points: [{ x: 0, y: 0 }, { x: 0, y: 0 }] }
    const html = render({ kind: 'zone', id: wall.id }, { zones: [malformed], onApply: () => null, editable: true })
    expect(html).toContain('无法编辑此对象')
    expect(html).not.toContain('type="submit"')
  })

  it('rejects blank, malformed and nonfinite form fields instead of interpreting blank as zero', () => {
    for (const value of ['', '  ', 'NaN', 'Infinity', '1e309', 'one']) {
      expect(() => parseObjectPoseFields({ x: value, y: '0', yaw: '0' })).toThrow()
      expect(() => parseObjectPoseFields({ x: '0', y: value, yaw: '0' })).toThrow()
      expect(() => parseObjectPoseFields({ x: '0', y: '0', yaw: value })).toThrow()
    }
    expect(parseObjectPoseFields({ x: '.42', y: '-.23', yaw: '90' })).toEqual({ x: .42, y: -.23, yaw: Math.PI / 2 })
    expect(parseObjectPoseFields({ x: '0', y: '1', yaw: 'ignored' }, true)).toEqual({ x: 0, y: 1, yaw: 0 })
    expect(() => parseObjectPoseFields({ x: '0', y: '0', yaw: '1e308' })).toThrow('过大')
  })
})
