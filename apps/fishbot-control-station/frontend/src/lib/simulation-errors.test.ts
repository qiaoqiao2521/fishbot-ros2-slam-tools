import { describe, expect, it } from 'vitest'

import { mapRuleErrorMessage } from '@/lib/simulation-errors'
import type { MapZone } from '@/lib/simulation-workspace'

const zones: MapZone[] = [
  { id: 'wall-id', kind: 'wall', points: [{ x: 0, y: 0 }, { x: 1, y: 0 }], width: 0.02 },
  { id: 'zone-id', kind: 'no_go', points: [{ x: 2, y: 2 }, { x: 3, y: 2 }, { x: 3, y: 3 }, { x: 2, y: 3 }] },
]

describe('map rule rejection display', () => {
  it('uses the same list label and explains the implicit return waypoint', () => {
    const message = mapRuleErrorMessage('Waypoint footprint intersects map rule wall-id', zones)
    expect(message).toContain('虚拟墙 1')
    expect(message).toContain('巡逻点或返航起点的车体范围')
    expect(message).toContain('取消“巡逻结束后返回起点”')
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
})
