import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SimulationPage } from '@/components/simulation/simulation-page'
import { goalDraftIdentity } from '@/lib/simulation-errors'
import type { SimulationGoalIssue, SimulationState } from '@/lib/simulation'
import type { MapZone, MissionRun } from '@/lib/simulation-workspace'
import { emptyRulesEditor, rulesReducer } from '@/lib/simulation-workspace'

const fixture = vi.hoisted(() => ({ routeWrite: 'idle', seedDraft: false, draftConsumed: false,
  cacheValidation: 'validated', cacheConflict: false, cacheMode: 'persistent_atomic', connectionError: null as string | null,
  attemptedDraft: null as string | null, goalIssue: null as SimulationGoalIssue | null, zones: [] as MapZone[], revision: 2,
  home: { x: 0, y: 0, yaw: 0 }, mission: null as SimulationState['mission'] | null, runs: null as MissionRun[] | null }))
vi.mock('react', async (original) => {
  const actual = await original<typeof import('react')>()
  return { ...actual, useState: (initial: unknown) => {
    if (initial === null && fixture.attemptedDraft && !fixture.draftConsumed) {
      fixture.draftConsumed = true
      return actual.useState(fixture.attemptedDraft)
    }
    return actual.useState(initial)
  } }
})

vi.mock('@/hooks/use-simulation', () => ({
  useSimulation: () => ({
    state: { mode: 'mujoco', domain: 93, ready: true, reason: '就绪', pose: null, truth: null,
      path: [], mission: fixture.mission ?? { id: null, status: 'idle', current_index: 0, waypoints: [], return_home: false, message: '等待巡逻任务' },
      obstacle: { state: 'parked', x: null, y: null, size: 0.36 }, home: fixture.home },
    map: { map_id: 'map-a', width: 4, height: 4, resolution: 1, origin: [0, 0, 0], data: new Array(16).fill(0) },
    connectionError: fixture.connectionError, mapError: null, actionError: fixture.goalIssue ? 'rejected' : null, goalIssue: fixture.goalIssue, pending: null, missionRequestUnknown: false, act: vi.fn(),
  }),
}))
vi.mock('@/hooks/use-patrol-draft-cache', () => ({
  usePatrolDraftCache: () => ({ draft: { waypoints: fixture.seedDraft ? [{ x: 1, y: 1, yaw: 0 }] : [], returnHome: true, routeName: '' },
    loaded: true, loading: false, saving: false, revisionId: '00000000-0000-4000-8000-000000000001', mode: fixture.cacheMode,
    validation: fixture.cacheValidation, validationToken: 'token', conflict: fixture.cacheConflict, message: '草稿已保留',
    setDraft: vi.fn(), confirmValidated: vi.fn(() => true), reloadCache: vi.fn() }),
}))
vi.mock('@/hooks/use-rviz', () => ({
  useRviz: () => ({ status: { available: true, running: false, domain: 107, message: '可打开' },
    pending: false, unknown: false, message: '可打开', open: vi.fn() }),
}))
vi.mock('@/hooks/use-simulation-workspace', () => ({
  useSimulationWorkspace: () => ({
    editor: rulesReducer(emptyRulesEditor(), { type: 'received', value: { map_id: 'map-a', revision: fixture.revision,
      zones: fixture.zones, apply_state: 'applied', message: '已确认' } }),
    dispatch: vi.fn(), rulesError: null, routes: [], routesError: null,
    runs: fixture.runs ?? [{ id: 'interrupted-run', status: 'unknown', map_id: 'map-a', rules_revision: 1,
      message: '桥接重启，旧任务实际终态未知；不会恢复或重发', stop_reason: '扫描断流' }],
    runsError: null, routeWrite: fixture.routeWrite, routeMessage: '', refreshing: false,
    refresh: vi.fn(), saveRules: vi.fn(), saveRoute: vi.fn(),
  }),
}))

afterEach(() => { fixture.routeWrite = 'idle'; fixture.seedDraft = false; fixture.draftConsumed = false;
  fixture.cacheValidation = 'validated'; fixture.cacheConflict = false; fixture.cacheMode = 'persistent_atomic'; fixture.connectionError = null;
  fixture.attemptedDraft = null; fixture.goalIssue = null; fixture.zones = []; fixture.revision = 2;
  fixture.home = { x: 0, y: 0, yaw: 0 }; fixture.mission = null; fixture.runs = null; vi.restoreAllMocks() })

const issue: SimulationGoalIssue = { kind: 'map_rule', target: 'waypoint', waypoint_index: 1,
  point: { x: 1, y: 1, yaw: 0 }, rule_id: 'wall-a', rule_kind: 'wall', rule_index: 1,
  clearance_m: 0.04, required_clearance_m: 0.13, shortfall_m: 0.09,
  map_id: 'map-a', rules_revision: 2 }
const wall: MapZone = { id: 'wall-a', kind: 'wall', points: [{ x: 0, y: 0 }, { x: 1, y: 0 }], width: 0.02 }

describe('simulation historical task record presentation', () => {
  it('keeps stale-rule drafts visible but requires an explicit review before start', () => {
    fixture.seedDraft = true; fixture.cacheValidation = 'stale'
    const html = renderToStaticMarkup(<SimulationPage onBack={() => {}} />)
    expect(html).toContain('巡逻点 1')
    expect(html).toContain('按当前规则复核')
    const start = [...html.matchAll(/<button([^>]*)>(.*?)<\/button>/gs)].find((button) => button[2].includes('开始巡逻'))
    expect(start?.[1]).toContain('disabled')
  })
  it('exposes a cache conflict without silently replacing the local route', () => {
    fixture.seedDraft = true; fixture.cacheConflict = true
    const html = renderToStaticMarkup(<SimulationPage onBack={() => {}} />)
    expect(html).toContain('草稿版本冲突')
    expect(html).toContain('用缓存替换本页草稿')
    expect(html).toContain('巡逻点 1')
    const start = [...html.matchAll(/<button([^>]*)>(.*?)<\/button>/gs)].find((button) => button[2].includes('开始巡逻'))
    expect(start?.[1]).toContain('disabled')
  })
  it('allows offline draft edits but disables execution and discloses the absence of persistence', () => {
    fixture.seedDraft = true; fixture.connectionError = '断流'; fixture.cacheMode = 'memory_only'
    const html = renderToStaticMarkup(<SimulationPage onBack={() => {}} />)
    expect(html).toContain('离线草稿保留')
    expect(html).toContain('仅当前页面内存')
    const buttons = [...html.matchAll(/<button([^>]*)>(.*?)<\/button>/gs)]
    expect(buttons.find((button) => button[2].includes('开始巡逻'))?.[1]).toContain('disabled')
    expect(buttons.find((button) => button[1].includes('移除巡逻点 1'))?.[1]).not.toContain('disabled')
  })
  it('shows the prospective departure coordinate and location action before any waypoint is drafted', () => {
    fixture.home = { x: 0.75, y: 0.25, yaw: 0.3 }
    const html = renderToStaticMarkup(<SimulationPage onBack={() => {}} />)
    expect(html).toContain('本次出发点（按当前定位）')
    expect(html).toContain('(0.75, 0.25) 米')
    expect(html).toContain('定位本次出发点')
    expect(html).toContain('开始巡逻时记录当前定位，任务中保持不变。这里不是最后一个巡逻点。')
  })
  it('exposes a separate native RViz launcher and explains where its window appears', () => {
    const html = renderToStaticMarkup(<SimulationPage onBack={() => {}} />)
    expect(html).toContain('打开 RViz')
    expect(html).toContain('窗口显示在控制站电脑，手机可发起打开。')
  })
  it('guides an empty route to map selection or saved routes without a fixed demo action', () => {
    const html = renderToStaticMarkup(<SimulationPage onBack={() => {}} />)
    expect(html).toContain('在地图上选择巡逻点，或载入已保存的路线。')
    expect(html).toContain('路线模板')
    expect(html).not.toContain('载入三点路线')
  })
  it('allows explicit start of a valid local draft while an unrelated route-template save remains unknown', () => {
    fixture.routeWrite = 'unknown'
    fixture.seedDraft = true
    const html = renderToStaticMarkup(<SimulationPage onBack={() => {}} />)
    const buttons = [...html.matchAll(/<button([^>]*)>(.*?)<\/button>/gs)]
    const start = buttons.find((button) => button[2].includes('开始巡逻'))
    const save = buttons.find((button) => button[2].includes('保存当前路线'))
    expect(start).toBeDefined()
    expect(start?.[1]).not.toContain('disabled')
    expect(save?.[1]).toContain('disabled')
  })

  it('shows an interrupted task as terminal unknown and preserves the first stop reason', () => {
    const html = renderToStaticMarkup(<SimulationPage onBack={() => {}} />)
    const records = html.slice(html.indexOf('simulation-runs'))
    expect(records).toContain('<strong>终态未知</strong>')
    expect(records).toContain('interrupted-run')
    expect(records).toContain('扫描断流')
    expect(records).not.toContain('<strong>等待连接</strong>')
    expect(records).not.toContain('<strong>等待任务</strong>')
    expect(records).not.toContain('<strong>巡逻完成</strong>')
  })

  it('links a current rejection to the exact map marker, rule and unchanged draft waypoint', () => {
    fixture.seedDraft = true
    fixture.goalIssue = issue
    fixture.zones = [wall]
    fixture.attemptedDraft = goalDraftIdentity([issue.point], true)
    const html = renderToStaticMarkup(<SimulationPage onBack={() => {}} />)
    expect(html).toContain('巡逻点 1（1.00, 1.00）米')
    expect(html).toContain('在地图上定位问题')
    expect(html).toContain('simulation-waypoint-issue')
    expect(html).toContain('simulation-rule-issue')
    expect(html).toContain('data-goal-issue-current="true"')
    expect(html).not.toContain('此提示来自上一版路线或规则')
  })

  it('downgrades an edited route to a historical coordinate without marking another draft point', () => {
    fixture.seedDraft = true
    fixture.goalIssue = issue
    fixture.zones = [wall]
    fixture.attemptedDraft = goalDraftIdentity([{ x: 2, y: 2, yaw: 0 }], true)
    const html = renderToStaticMarkup(<SimulationPage onBack={() => {}} />)
    expect(html).toContain('此提示来自上一版路线或规则')
    expect(html).toContain('定位上次问题')
    expect(html).toContain('上次拒绝点：巡逻点 1')
    expect(html).not.toContain('simulation-waypoint-issue')
    expect(html).not.toContain('simulation-rule-issue')
  })

  it('does not accuse a current rule when its backend snapshot revision has changed', () => {
    fixture.seedDraft = true
    fixture.goalIssue = issue
    fixture.zones = [wall]
    fixture.attemptedDraft = goalDraftIdentity([issue.point], true)
    fixture.revision = 3
    const html = renderToStaticMarkup(<SimulationPage onBack={() => {}} />)
    expect(html).toContain('此提示来自上一版路线或规则')
    expect(html).not.toContain('simulation-rule-issue')
    expect(html).not.toContain('simulation-waypoint-issue')
  })

  it('does not offer map location for a diagnostic belonging to another map', () => {
    fixture.goalIssue = { ...issue, map_id: 'old-map' }
    const html = renderToStaticMarkup(<SimulationPage onBack={() => {}} />)
    expect(html).toContain('地图已不同，不在当前地图标记')
    expect(html).not.toContain('定位上次问题')
    expect(html).not.toContain('simulation-goal-issue-overlay')
  })
})


describe('native route metrics', () => {
  it('renders twelve accepted waypoints plus the backend return point without a draft-limit crash', () => {
    vi.spyOn(Date, 'now').mockReturnValue(12_000)
    fixture.mission = { id: 'native-route', status: 'running', dispatch_state: 'accepted',
      current_index: 0, waypoints: Array.from({ length: 13 }, (_, x) => ({ x, y: 0, yaw: 0 })),
      return_home: true, message: '原生执行' }
    fixture.runs = [{ id: 'native-route', map_id: 'map-a', status: 'running', started_at: 10 }]
    const html = renderToStaticMarkup(<SimulationPage onBack={() => {}} />)
    expect(html).toContain('航点间直线 12.00 米')
    expect(html).toContain('任务耗时 2.0 秒')
    expect(html).toContain('返回本次出发点')
    expect(html).not.toContain('巡逻完成')
  })
})
