import { afterEach, describe, expect, it, vi } from 'vitest'

import { requestSimulation, SimulationRejectedRequest, type SimulationMap } from '@/lib/simulation'
import {
  editWaypointPose, emptyRulesEditor, mapGeneration, mapZonePose, missionElapsedSeconds, rectanglePoints, routeDraft, ruleStartBlock, rulesDirty, rulesReducer, transformMapZone,
  validateMapRules, validateRoutes, validateRuns, zoneFromSelection, zonesEqual,
  type MapRules, type MapZone, type RulesEditor, type SavedRoute,
} from '@/lib/simulation-workspace'

const saved: MapRules = { map_id: 'map-a', revision: 0, zones: [], apply_state: 'applied', message: '确认' }
const wall: MapZone = { id: 'wall-a', kind: 'wall', points: [{ x: 0, y: 1 }, { x: 2, y: 1 }], width: 0.1 }
const route: SavedRoute = { id: 'route-a', name: '窄口', map_id: 'map-a', revision: 1,
  waypoints: [{ x: 1, y: 2, yaw: 0.3 }], return_home: true }
const editor = (): RulesEditor => rulesReducer(emptyRulesEditor(), { type: 'received', value: saved })
afterEach(() => vi.unstubAllGlobals())

describe('local object pose editing', () => {
  const map: SimulationMap = { map_id: 'map-a', width: 100, height: 100, resolution: .1, origin: [-5, -5, 0], data: new Array(10000).fill(0) }
  const area = zoneFromSelection('no_go', { x: -1, y: -1 }, { x: 1, y: 1 }, 'area')

  it('moves and rotates a wall rigidly without changing its id, width or length', () => {
    expect(mapZonePose(wall)).toEqual({ x: 1, y: 1, yaw: 0 })
    const moved = transformMapZone(wall, { x: 0, y: 0, yaw: Math.PI / 2 }, map)
    expect(moved.id).toBe(wall.id); expect(moved.width).toBe(wall.width)
    expect(moved.points[0].x).toBeCloseTo(0); expect(moved.points[0].y).toBeCloseTo(-1)
    expect(moved.points[1].x).toBeCloseTo(0); expect(moved.points[1].y).toBeCloseTo(1)
    expect(Math.hypot(moved.points[1].x - moved.points[0].x, moved.points[1].y - moved.points[0].y)).toBeCloseTo(2)
    expect(wall.points).toEqual([{ x: 0, y: 1 }, { x: 2, y: 1 }])
  })

  it('keeps forbidden areas axis aligned and refuses rotation rather than exporting a different shape', () => {
    const moved = transformMapZone(area, { x: 2, y: 1, yaw: 0 }, map)
    expect(moved.points).toEqual([{ x: 1, y: 0 }, { x: 3, y: 0 }, { x: 3, y: 2 }, { x: 1, y: 2 }])
    expect(() => transformMapZone(area, { x: 0, y: 0, yaw: .01 }, map)).toThrow('不能旋转')
  })

  it('checks the actual rotated map boundary and rejects nonfinite or out-of-bounds rule edits', () => {
    const rotated = { ...map, origin: [5, -5, Math.PI / 2] as [number, number, number] }
    expect(() => transformMapZone(wall, { x: 0, y: 0, yaw: Math.PI / 3 }, rotated)).not.toThrow()
    for (const pose of [{ x: NaN, y: 0, yaw: 0 }, { x: 0, y: 0, yaw: Infinity }, { x: 4.9, y: 0, yaw: 0 }]) {
      expect(() => transformMapZone(wall, pose, map)).toThrow()
    }
    expect(() => transformMapZone(wall, { x: 6, y: 0, yaw: 0 }, rotated)).toThrow('地图边缘')
  })

  it('records a rule pose edit as one undoable transaction and truncates redo only on a new edit', () => {
    const initial = rulesReducer(editor(), { type: 'add', zone: wall })
    const zone = transformMapZone(wall, { x: 0, y: 0, yaw: .3 }, map)
    const changed = rulesReducer(initial, { type: 'replace', id: wall.id, expected: wall, zone })
    expect(changed.history).toHaveLength(initial.history.length + 1)
    expect(changed.zones).toEqual([zone]); expect(changed.saved).toEqual(initial.saved)
    const undone = rulesReducer(changed, { type: 'undo' })
    expect(undone.zones).toEqual([wall])
    expect(rulesReducer(undone, { type: 'redo' }).zones).toEqual([zone])
    const noOp = rulesReducer(undone, { type: 'replace', id: wall.id, expected: wall, zone: wall })
    expect(noOp).toBe(undone); expect(noOp.future).toHaveLength(1)
    const newer = rulesReducer(undone, { type: 'replace', id: wall.id, expected: wall, zone: transformMapZone(wall, { x: 1, y: 0, yaw: 0 }, map) })
    expect(newer.future).toEqual([])
  })

  it('does not apply a stale rule form to a removed, replaced or differently identified object', () => {
    const initial = rulesReducer(editor(), { type: 'add', zone: wall })
    const zone = transformMapZone(wall, { x: 0, y: 0, yaw: 0 }, map)
    for (const edit of [
      { type: 'replace' as const, id: 'other', expected: wall, zone },
      { type: 'replace' as const, id: wall.id, expected: { ...wall, width: .2 }, zone },
      { type: 'replace' as const, id: wall.id, expected: wall, zone: { ...zone, id: 'other' } },
    ]) {
      const result = rulesReducer(initial, edit)
      expect(result.zones).toEqual(initial.zones); expect(result.history).toEqual(initial.history)
      expect(result.error).toContain('已变化')
    }
    for (const writeState of ['saving', 'unknown'] as const) {
      const locked = { ...initial, writeState }
      expect(rulesReducer(locked, { type: 'replace', id: wall.id, expected: wall, zone })).toBe(locked)
    }
  })

  it('rejects invalid replacement geometry without mutating the history', () => {
    const initial = rulesReducer(editor(), { type: 'add', zone: wall })
    const result = rulesReducer(initial, { type: 'replace', id: wall.id, expected: wall, zone: { ...wall, points: [{ x: NaN, y: 1 }, { x: 2, y: 1 }] } })
    expect(result.zones).toEqual([wall]); expect(result.history).toEqual(initial.history)
    expect(result.error).toBeTruthy()
  })

  it('updates one waypoint and normalizes yaw while preserving sibling coordinates', () => {
    const points = [{ x: -1, y: 0, yaw: 0 }, { x: 1, y: 0, yaw: .2 }]
    const changed = editWaypointPose(points, 0, points[0], { x: -2, y: 1, yaw: Math.PI * 2 + .1 }, map, [])
    expect(changed[0].x).toBe(-2); expect(changed[0].yaw).toBeCloseTo(.1)
    expect(changed[1]).toEqual(points[1]); expect(changed[1]).not.toBe(points[1])
    expect(points[0]).toEqual({ x: -1, y: 0, yaw: 0 })
  })

  it('rejects stale waypoint identity, invalid numbers, occupied cells and full-footprint rule conflicts', () => {
    const points = [{ x: -1, y: 0, yaw: 0 }]
    expect(() => editWaypointPose(points, 0, { ...points[0], x: 1 }, points[0], map, [])).toThrow('已变化')
    expect(() => editWaypointPose(points, 1, points[0], points[0], map, [])).toThrow('已变化')
    expect(() => editWaypointPose(points, 0, points[0], { x: 0, y: Infinity, yaw: 0 }, map, [])).toThrow('有限数值')
    expect(() => editWaypointPose(points, 0, points[0], { x: 4.99, y: 0, yaw: 0 }, map, [])).toThrow('车体范围')
    const occupied = { ...map, data: [...map.data] }; occupied.data[50 * 100 + 50] = 100
    expect(() => editWaypointPose(points, 0, points[0], { x: 0, y: 0, yaw: 0 }, occupied, [])).toThrow('车体范围')
    expect(() => editWaypointPose(points, 0, points[0], { x: 1, y: .85, yaw: 0 }, map, [wall])).toThrow('wall-a')
    expect(() => editWaypointPose(points, 0, points[0], { x: 0, y: 0, yaw: 0 }, map, [area])).toThrow('area')
  })

  it('allows a safe edited waypoint across a software wall because Nav2 owns actual detours', () => {
    const points = [{ x: -1, y: 0, yaw: 0 }, { x: 1, y: 0, yaw: 0 }]
    const crossWall: MapZone = { ...wall, points: [{ x: 0, y: -2 }, { x: 0, y: 2 }] }
    expect(editWaypointPose(points, 1, points[1], { x: 2, y: 0, yaw: 0 }, map, [crossWall])[1].x).toBe(2)
  })
})

describe('late rules draft restoration', () => {
  const cached: MapZone[] = [wall]
  it('restores only the local zones and old CAS baseline while retaining the server snapshot', () => {
    const initial = rulesReducer(emptyRulesEditor(), { type: 'received', value: { ...saved, revision: 4 } })
    const restored = rulesReducer(initial, { type: 'restoreDraft', mapId: 'map-a', baseRevision: 2, zones: cached })
    expect(restored.saved).toBe(initial.saved)
    expect(restored.zones).toEqual(cached); expect(restored.baseRevision).toBe(2)
    expect(ruleStartBlock(restored, true)).toContain('其他编辑更新')
    expect(restored.history).toEqual([initial.saved!.zones])
    expect(rulesReducer(restored, { type: 'undo' }).zones).toEqual(initial.saved!.zones)
    cached[0].points[0].x = .2
    expect(restored.zones[0].points[0].x).toBe(0)
    cached[0].points[0].x = 0
    expect(rulesReducer(restored, { type: 'restore' }).baseRevision).toBe(4)
  })

  it('does not overwrite another map, locked saves, active geometry/history or a redo branch', () => {
    const initial = editor()
    const modified = rulesReducer(initial, { type: 'add', zone: wall })
    const redoBranch = rulesReducer(modified, { type: 'undo' })
    for (const current of [modified, redoBranch, { ...initial, history: [[]] }, { ...initial, anchor: { x: 0, y: 0 } },
      { ...initial, writeState: 'saving' as const }, { ...initial, writeState: 'unknown' as const }, { ...initial, writeState: 'rejected' as const }]) {
      expect(rulesReducer(current, { type: 'restoreDraft', mapId: 'map-a', baseRevision: 0, zones: cached })).toBe(current)
    }
    expect(rulesReducer(initial, { type: 'restoreDraft', mapId: 'other', baseRevision: 0, zones: cached })).toBe(initial)
  })

  it('refuses invalid cache geometry and revisions before creating any undo transaction', () => {
    const initial = editor()
    for (const baseRevision of [-1, Infinity, NaN, .1]) {
      expect(rulesReducer(initial, { type: 'restoreDraft', mapId: 'map-a', baseRevision, zones: cached })).toBe(initial)
    }
    expect(rulesReducer(initial, { type: 'restoreDraft', mapId: 'map-a', baseRevision: 0,
      zones: [{ ...wall, points: [{ x: 0, y: 0 }, { x: 0, y: 0 }] }] })).toBe(initial)
  })
})

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
