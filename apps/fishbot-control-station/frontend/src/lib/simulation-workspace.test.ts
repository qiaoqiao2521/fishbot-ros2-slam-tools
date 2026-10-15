import { afterEach, describe, expect, it, vi } from 'vitest'

import { requestSimulation, SimulationRejectedRequest, type SimulationMap } from '@/lib/simulation'
import {
  emptyRulesEditor, mapGeneration, missionElapsedSeconds, rectanglePoints, routeDraft, ruleStartBlock, rulesDirty, rulesReducer,
  validateMapRules, validateRoutes, validateRuns, zoneFromSelection, zonesEqual,
  type MapRules, type MapZone, type RulesEditor, type SavedRoute,
} from '@/lib/simulation-workspace'

const saved: MapRules = { map_id: 'map-a', revision: 0, zones: [], apply_state: 'applied', message: '确认' }
const wall: MapZone = { id: 'wall-a', kind: 'wall', points: [{ x: 0, y: 1 }, { x: 2, y: 1 }], width: 0.1 }
const route: SavedRoute = { id: 'route-a', name: '窄口', map_id: 'map-a', revision: 1,
  waypoints: [{ x: 1, y: 2, yaw: 0.3 }], return_home: true }
const editor = (): RulesEditor => rulesReducer(emptyRulesEditor(), { type: 'received', value: saved })
afterEach(() => vi.unstubAllGlobals())

describe('software map rules drafting', () => {
  it('constructs the same rectangular polygon regardless of diagonal click order', () => {
    const points = [{ x: -2, y: 1 }, { x: 3, y: 1 }, { x: 3, y: 4 }, { x: -2, y: 4 }]
    expect(rectanglePoints({ x: 3, y: 1 }, { x: -2, y: 4 })).toEqual(points)
    expect(zoneFromSelection('no_go', { x: -2, y: 4 }, { x: 3, y: 1 }, 'zone').points).toEqual(points)
    expect(zoneFromSelection('wall', { x: 1, y: 1 }, { x: 2, y: 3 }, 'wall').points).toHaveLength(2)
  })

  it('rejects degenerate rectangles, short walls and nonfinite coordinates', () => {
    expect(() => zoneFromSelection('wall', { x: 0, y: 0 }, { x: 0.01, y: 0 }, 'wall')).toThrow('两点太近')
    expect(() => zoneFromSelection('no_go', { x: 0, y: 0 }, { x: 0, y: 2 }, 'zone')).toThrow('有面积')
    expect(() => zoneFromSelection('wall', { x: NaN, y: 0 }, { x: 1, y: 1 }, 'wall')).toThrow()
  })

  it('keeps selecting, adding, removing and undoing entirely local until explicit save', () => {
    let current = rulesReducer(editor(), { type: 'anchor', point: { x: 0, y: 1 } })
    expect(rulesDirty(current)).toBe(true)
    expect(current.saved?.zones).toEqual([])
    current = rulesReducer(current, { type: 'add', zone: wall })
    expect(current.anchor).toBeNull()
    expect(current.saved?.revision).toBe(0)
    expect(current.saved?.zones).toEqual([])
    expect(ruleStartBlock(current, true)).toContain('未保存')
    const removed = rulesReducer(current, { type: 'remove', id: wall.id })
    expect(removed.zones).toEqual([])
    expect(rulesReducer(removed, { type: 'undo' }).zones).toEqual([wall])
    expect(rulesReducer(current, { type: 'restore' }).zones).toEqual([])
  })

  it('undoes an incomplete selection before undoing an earlier completed shape', () => {
    const completed = rulesReducer(editor(), { type: 'add', zone: wall })
    const unfinished = rulesReducer(completed, { type: 'anchor', point: { x: 1, y: 2 } })
    const undone = rulesReducer(unfinished, { type: 'undo' })
    expect(undone.zones).toEqual([wall])
    expect(undone.anchor).toBeNull()
    expect(rulesReducer(undone, { type: 'undo' }).zones).toEqual([])
  })

  it('does not turn an HTTP publish receipt into navigation application', () => {
    const draft = rulesReducer(editor(), { type: 'add', zone: wall })
    const saving = rulesReducer(draft, { type: 'saving' })
    expect(ruleStartBlock(saving, true)).toContain('正在保存')
    expect(rulesReducer(saving, { type: 'remove', id: wall.id })).toBe(saving)
    const published = rulesReducer(saving, { type: 'saved', value: { ...saved, revision: 1, zones: [wall], apply_state: 'published' } })
    expect(rulesDirty(published)).toBe(false)
    expect(ruleStartBlock(published, true)).toContain('等待导航确认')
    const applied = rulesReducer(published, { type: 'received', value: { ...published.saved!, apply_state: 'applied' } })
    expect(ruleStartBlock(applied, true)).toBeNull()
    expect(ruleStartBlock(applied, false)).toContain('尚未读回')
    expect(ruleStartBlock({ ...applied, saved: { ...applied.saved!, apply_state: 'unavailable' } }, true)).toContain('尚未应用')
  })

  it('retains unknown submission until GET confirms the attempted contents in a new revision', () => {
    const saving = rulesReducer(rulesReducer(editor(), { type: 'add', zone: wall }), { type: 'saving' })
    let unknown = rulesReducer(saving, { type: 'unknown', message: '回执未知' })
    expect(unknown.writeState).toBe('unknown')
    for (const event of [{ type: 'saving' }, { type: 'restore' }, { type: 'undo' }, { type: 'remove', id: wall.id }] as const) {
      expect(rulesReducer(unknown, event)).toBe(unknown)
    }
    unknown = rulesReducer(unknown, { type: 'received', value: saved })
    expect(unknown.writeState).toBe('unknown')
    expect(ruleStartBlock(unknown, true)).toContain('不能重复提交')
    unknown = rulesReducer(unknown, { type: 'received', value: { ...saved, revision: 1, zones: [] } })
    expect(unknown.writeState).toBe('unknown')
    const confirmed = rulesReducer(unknown, { type: 'received', value: { ...saved, revision: 2, zones: [wall], apply_state: 'published' } })
    expect(confirmed.writeState).toBe('idle')
    expect(confirmed.zones).toEqual([wall])
    expect(ruleStartBlock(confirmed, true)).toContain('等待导航确认')
  })

  it('preserves rejected drafts and does not hide the reason behind successful GET polling', () => {
    const saving = rulesReducer(rulesReducer(editor(), { type: 'add', zone: wall }), { type: 'saving' })
    const rejected = rulesReducer(saving, { type: 'rejected', message: '当前有活动任务' })
    expect(rejected.writeState).toBe('rejected')
    expect(rejected.error).toBe('当前有活动任务')
    expect(rejected.zones).toEqual([wall])
    expect(rulesReducer(rejected, { type: 'received', value: saved }).error).toBe('当前有活动任务')
    expect(ruleStartBlock(rejected, true)).toContain('未保存')
  })

  it('keeps the original CAS revision when another editor publishes during local edits', () => {
    const draft = rulesReducer(editor(), { type: 'add', zone: wall })
    const external = rulesReducer(draft, { type: 'received', value: { ...saved, revision: 1, zones: [{ ...wall, id: 'external' }] } })
    expect(external.baseRevision).toBe(0)
    expect(external.saved?.revision).toBe(1)
    expect(external.zones).toEqual([wall])
    expect(ruleStartBlock(external, true)).toContain('其他编辑更新')
    const restored = rulesReducer(external, { type: 'restore' })
    expect(restored.baseRevision).toBe(1)
    expect(restored.zones[0].id).toBe('external')
  })

  it('clears stale and even unresolved drafts when the map identity changes', () => {
    const unknown = rulesReducer(rulesReducer(rulesReducer(editor(), { type: 'add', zone: wall }), { type: 'saving' }), { type: 'unknown', message: '未知' })
    const changed = rulesReducer(unknown, { type: 'received', value: { ...saved, map_id: 'map-b', revision: 0 } })
    expect(changed.mapId).toBe('map-b')
    expect(changed.zones).toEqual([])
    expect(changed.history).toEqual([])
    expect(changed.attempted).toBeNull()
    expect(changed.writeState).toBe('idle')
  })

  it('compares values independently of JSON object key order', () => {
    expect(zonesEqual([wall], [{ width: 0.1, points: wall.points, kind: 'wall', id: 'wall-a' }])).toBe(true)
    expect(zonesEqual([wall], [{ ...wall, points: wall.points.toReversed() }])).toBe(false)
  })
})

describe('workspace resource contracts and route-only drafts', () => {
  it('validates map-bound resources and refuses malformed shapes, duplicate ids, and invented application states', () => {
    expect(validateMapRules(saved, 'map-a')).toBe(saved)
    expect(() => validateMapRules(saved, 'map-b')).toThrow('另一张地图')
    expect(() => validateMapRules({ ...saved, zones: [wall, wall] })).toThrow()
    expect(() => validateMapRules({ ...saved, zones: [{ ...wall, kind: 'no_go' }] })).toThrow()
    expect(() => validateMapRules({ ...saved, apply_state: 'success' } as unknown as MapRules)).toThrow()
    expect(() => validateRoutes({ map_id: 'map-b', routes: [route] })).toThrow()
    expect(() => validateRuns({ runs: [{ id: 'run', status: 'running', rules_revision: NaN }] })).toThrow()
  })

  it('accepts an interrupted run as unknown and rejects invented or idle historical statuses', () => {
    const interrupted = { id: 'old-run', status: 'unknown', map_id: 'map-a', rules_revision: 2,
      message: '桥接重启，实际终态未知；不会恢复或重发', waypoints: route.waypoints }
    expect(validateRuns({ runs: [interrupted] }).runs[0].status).toBe('unknown')
    for (const status of ['idle', 'accepted', 'complete', 'done', '', 'UNKNOWN']) {
      expect(() => validateRuns({ runs: [{ ...interrupted, status }] })).toThrow('任务记录格式无效')
    }
  })

  it('loads a route as an independent local draft without network or mission dispatch', () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    const draft = routeDraft(route, 'map-a')
    expect(draft).toEqual({ waypoints: route.waypoints, returnHome: true })
    draft.waypoints[0].x = 9
    expect(route.waypoints[0].x).toBe(1)
    expect(fetch).not.toHaveBeenCalled()
    expect(() => routeDraft(route, 'map-b')).toThrow('另一张地图')
  })

  it('recognizes identical polling maps and detects content changes without server map ids', () => {
    const map: SimulationMap = { width: 2, height: 2, resolution: 0.1, origin: [0, 0, 0], data: [0, 0, 0, 0] }
    expect(mapGeneration(map)).toBe(mapGeneration({ ...map, data: [...map.data] }))
    expect(mapGeneration(map)).not.toBe(mapGeneration({ ...map, data: [0, 100, 0, 0] }))
    expect(mapGeneration({ ...map, map_id: 'map-a' })).toBe('map-a')
    expect(mapGeneration(null)).toBeNull()
  })

  it('surfaces explicit CAS rejection rather than returning a fake saved object', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ error: '规则版本冲突，请重新读取' }), { status: 409 }))))
    await expect(requestSimulation('map-rules', { map_id: 'map-a', base_revision: 0, zones: [] })).rejects.toBeInstanceOf(SimulationRejectedRequest)
    await expect(requestSimulation('map-rules', {})).rejects.toThrow('规则版本冲突')
  })
})


describe('rule redo transaction boundaries', () => {
  it('replays a deep snapshot and clears redo on a new edit', () => {
    const input = { ...wall, points: wall.points.map(p => ({ ...p })) }
    const added = rulesReducer(editor(), { type: 'add', zone: input })
    input.points[0].x = 999
    const undone = rulesReducer(added, { type: 'undo' })
    expect(undone.zones).toEqual([])
    const polled = rulesReducer(undone, { type: 'received', value: saved })
    const redone = rulesReducer(polled, { type: 'redo' })
    expect(redone.zones).toEqual([wall])
    expect(redone.future).toEqual([])
    const branched = rulesReducer(undone, { type: 'add', zone: { ...wall, id: 'branch' } })
    expect(rulesReducer(branched, { type: 'redo' })).toBe(branched)
  })
  it('cannot replay edits across a save or an unknown write', () => {
    const undone = rulesReducer(rulesReducer(editor(), { type: 'add', zone: wall }), { type: 'undo' })
    const saving = rulesReducer(undone, { type: 'saving' })
    const unknown = rulesReducer(saving, { type: 'unknown', message: 'unknown' })
    expect(rulesReducer(unknown, { type: 'redo' })).toBe(unknown)
    const confirmed = rulesReducer(undone, { type: 'saved', value: { ...saved, revision: 1 } })
    expect(rulesReducer(confirmed, { type: 'redo' })).toBe(confirmed)
  })
})


describe('elapsed native task records', () => {
  const mission = { id: 'owned', status: 'running' }
  const run = { id: 'owned', map_id: 'map-a', status: 'running', started_at: 10 }
  it('uses the original ID and map, and freezes a confirmed terminal duration', () => {
    expect(missionElapsedSeconds(mission, [run], 'map-a', 12)).toBe(2)
    const done = { ...run, status: 'succeeded', finished_at: 13 }
    expect(missionElapsedSeconds({ ...mission, status: 'succeeded' }, [done], 'map-a', 50)).toBe(3)
    expect(missionElapsedSeconds(mission, [{ ...run, id: 'other' }], 'map-a', 12)).toBeNull()
    expect(missionElapsedSeconds(mission, [run], 'map-b', 12)).toBeNull()
  })
  it('hides missing, delayed and invalid records without inventing a start time', () => {
    expect(missionElapsedSeconds({ ...mission, status: 'succeeded' }, [run], 'map-a', 12)).toBeNull()
    expect(missionElapsedSeconds(mission, [], 'map-a', 12)).toBeNull()
    expect(missionElapsedSeconds(mission, [{ ...run, started_at: NaN }], 'map-a', 12)).toBeNull()
    expect(missionElapsedSeconds(mission, [run], 'map-a', 9)).toBeNull()
  })
})
