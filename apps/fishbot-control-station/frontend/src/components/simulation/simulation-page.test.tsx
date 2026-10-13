import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SimulationPage } from '@/components/simulation/simulation-page'
import { emptyRulesEditor, rulesReducer } from '@/lib/simulation-workspace'

const fixture = vi.hoisted(() => ({ routeWrite: 'idle', seedDraft: false, draftConsumed: false }))
vi.mock('react', async (original) => {
  const actual = await original<typeof import('react')>()
  return { ...actual, useState: (initial: unknown) => {
    if (fixture.seedDraft && !fixture.draftConsumed && Array.isArray(initial) && initial.length === 0) {
      fixture.draftConsumed = true
      return actual.useState([{ x: 1, y: 1, yaw: 0 }])
    }
    return actual.useState(initial)
  } }
})

vi.mock('@/hooks/use-simulation', () => ({
  useSimulation: () => ({
    state: { mode: 'mujoco', domain: 93, ready: true, reason: '就绪', pose: null, truth: null,
      path: [], mission: { id: null, status: 'idle', current_index: 0, waypoints: [], return_home: false, message: '等待巡逻任务' },
      obstacle: { state: 'parked', x: null, y: null, size: 0.36 }, home: { x: 0, y: 0, yaw: 0 } },
    map: { map_id: 'map-a', width: 4, height: 4, resolution: 1, origin: [0, 0, 0], data: new Array(16).fill(0) },
    connectionError: null, mapError: null, actionError: null, pending: null, missionRequestUnknown: false, act: vi.fn(),
  }),
}))
vi.mock('@/hooks/use-rviz', () => ({
  useRviz: () => ({ status: { available: true, running: false, domain: 107, message: '可打开' },
    pending: false, unknown: false, message: '可打开', open: vi.fn() }),
}))
vi.mock('@/hooks/use-simulation-workspace', () => ({
  useSimulationWorkspace: () => ({
    editor: rulesReducer(emptyRulesEditor(), { type: 'received', value: { map_id: 'map-a', revision: 2,
      zones: [], apply_state: 'applied', message: '已确认' } }),
    dispatch: vi.fn(), rulesError: null, routes: [], routesError: null,
    runs: [{ id: 'interrupted-run', status: 'unknown', map_id: 'map-a', rules_revision: 1,
      message: '桥接重启，旧任务实际终态未知；不会恢复或重发', stop_reason: '扫描断流' }],
    runsError: null, routeWrite: fixture.routeWrite, routeMessage: '', refreshing: false,
    refresh: vi.fn(), saveRules: vi.fn(), saveRoute: vi.fn(),
  }),
}))

afterEach(() => { fixture.routeWrite = 'idle'; fixture.seedDraft = false; fixture.draftConsumed = false })

describe('simulation historical task record presentation', () => {
  it('exposes a separate native RViz launcher and explains where its window appears', () => {
    const html = renderToStaticMarkup(<SimulationPage onBack={() => {}} />)
    expect(html).toContain('打开 RViz')
    expect(html).toContain('窗口显示在控制站电脑，手机可发起打开。')
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
})
