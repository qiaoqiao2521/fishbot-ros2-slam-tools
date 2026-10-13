import { describe, expect, it } from 'vitest'

import { goalDraftIdentity, goalIssueMatchesWaypoint, mapRuleErrorMessage } from '@/lib/simulation-errors'
import type { SimulationGoalIssue } from '@/lib/simulation'
import type { MapZone } from '@/lib/simulation-workspace'

const zones: MapZone[] = [
  { id: 'wall-id', kind: 'wall', points: [{ x: 0, y: 0 }, { x: 1, y: 0 }], width: 0.02 },
  { id: 'zone-id', kind: 'no_go', points: [{ x: 2, y: 2 }, { x: 3, y: 2 }, { x: 3, y: 3 }, { x: 2, y: 3 }] },
]
const issue: SimulationGoalIssue = { kind: 'map_rule', target: 'waypoint', waypoint_index: 2,
  point: { x: 0.61, y: 0, yaw: 0 }, rule_id: 'wall-id', rule_kind: 'wall', rule_index: 5,
  clearance_m: 0.04217, required_clearance_m: 0.13, shortfall_m: 0.08783,
  blocking_point: { x: 0.61, y: 0.04217 }, map_id: 'map-a', rules_revision: 2 }

describe('map rule rejection display', () => {
  it('uses the same list label and explains the implicit return waypoint', () => {
    const message = mapRuleErrorMessage('Waypoint footprint intersects map rule wall-id', zones)
    expect(message).toContain('虚拟墙 1')
    expect(message).toContain('巡逻点或返航点的车体范围')
    expect(message).toContain('取消“巡逻结束后返回本次出发点”')
    expect(message).not.toContain('wall-id')
  })

  it('labels rectangular rules and handles a rule missing from the latest UI snapshot', () => {
    expect(mapRuleErrorMessage('Waypoint footprint intersects map rule zone-id', zones)).toContain('禁区 2')
    expect(mapRuleErrorMessage('Waypoint footprint intersects map rule old-id', zones)).toContain('地图中的虚拟墙或禁区')
  })

  it('preserves other errors and absent errors', () => {
    expect(mapRuleErrorMessage('派发回执未知，不能重复派发。', zones)).toBe('派发回执未知，不能重复派发。')
    expect(mapRuleErrorMessage(null, zones)).toBeNull()
  })

  it('identifies the rejected point and authoritative rule snapshot with conservative centimeter rounding', () => {
    const message = mapRuleErrorMessage('old English error', zones, issue)
    expect(message).toContain('巡逻点 2（0.61, 0.00）米')
    expect(message).toContain('虚拟墙 5')
    expect(message).not.toContain('虚拟墙 1')
    expect(message).toContain('净距 4.2 厘米')
    expect(message).toContain('至少需要 13.0 厘米')
    expect(message).toContain('净距不足约 8.8 厘米')
    expect(message).not.toContain('移动 8.8')
  })

  it('identifies the implicit home separately from the user waypoint list', () => {
    const message = mapRuleErrorMessage('rejected', [], { ...issue, target: 'return_home', waypoint_index: null, point: { x: 0, y: 0, yaw: 0 } })
    expect(message).toContain('返航点（本次出发点）（0.00, 0.00）米')
    expect(message).toContain('取消“巡逻结束后返回本次出发点”')
    expect(message).not.toContain('巡逻点 null')
  })

  it('describes exact contact instead of claiming a positive clearance shortage', () => {
    const message = mapRuleErrorMessage('rejected', [], { ...issue, clearance_m: 0.13, shortfall_m: 0 })
    expect(message).toContain('车体与边缘相接，需留出额外净距')
    expect(message).not.toContain('不足约 0.0')
  })

  it('distinguishes native-map occupied, unknown and boundary diagnostics', () => {
    expect(mapRuleErrorMessage('rejected', [], { ...issue, kind: 'occupied_cell' })).toContain('地图占用格（0.61, 0.04）米')
    expect(mapRuleErrorMessage('rejected', [], { ...issue, kind: 'unknown_cell' })).toContain('地图未知格')
    expect(mapRuleErrorMessage('rejected', [], { ...issue, kind: 'map_boundary' })).toContain('车体范围越过地图边缘')
  })

  it('does not substitute a new reordered or edited waypoint for the rejected point', () => {
    const earlier = { x: 0.2, y: 0.1, yaw: 0 }
    expect(goalIssueMatchesWaypoint(issue, 1, issue.point)).toBe(true)
    expect(goalIssueMatchesWaypoint(issue, 0, issue.point)).toBe(false)
    expect(goalIssueMatchesWaypoint(issue, 1, earlier)).toBe(false)
    expect(goalIssueMatchesWaypoint(issue, 1, { ...issue.point, yaw: 1 })).toBe(false)
    expect(goalDraftIdentity([earlier, issue.point], true)).not.toBe(goalDraftIdentity([issue.point, earlier], true))
    expect(goalDraftIdentity([issue.point], true)).not.toBe(goalDraftIdentity([issue.point], false))
  })
})
