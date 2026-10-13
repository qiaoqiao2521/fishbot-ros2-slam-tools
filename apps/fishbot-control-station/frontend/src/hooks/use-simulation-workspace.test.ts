import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useSimulationWorkspace } from '@/hooks/use-simulation-workspace'
import { requestSimulation } from '@/lib/simulation'
import { emptyRulesEditor, rulesReducer, type MapRules, type RouteCollection, type RunCollection } from '@/lib/simulation-workspace'

const hooks = vi.hoisted(() => ({
  effects: [] as Array<() => (() => void) | undefined>,
  values: [] as unknown[],
  rules: null as unknown,
}))
// Isolate the hook's actual asynchronous readback logic without a browser DOM.
vi.mock('react', () => ({
  useRef: (current: unknown) => ({ current }),
  useEffect: (effect: () => (() => void) | undefined) => hooks.effects.push(effect),
  useState: (initial: unknown) => [initial, (value: unknown) => hooks.values.push(value)],
  useReducer: (_reducer: typeof rulesReducer, _argument: unknown, initialize: typeof emptyRulesEditor) => {
    hooks.rules = initialize()
    return [hooks.rules, (event: Parameters<typeof rulesReducer>[1]) => { hooks.rules = rulesReducer(hooks.rules as ReturnType<typeof emptyRulesEditor>, event) }]
  },
}))
vi.mock('@/lib/simulation', async (original) => ({ ...await original<typeof import('@/lib/simulation')>(), requestSimulation: vi.fn() }))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((complete) => { resolve = complete })
  return { promise, resolve }
}
function round(rules: MapRules, routeId: string) {
  return {
    rules, routes: { map_id: rules.map_id, routes: [{ id: routeId, name: routeId, map_id: rules.map_id, revision: 1,
      waypoints: [{ x: 1, y: 1, yaw: 0 }], return_home: false }] } as RouteCollection,
    pendingRules: deferred<MapRules>(), pendingRoutes: deferred<RouteCollection>(), pendingRuns: deferred<RunCollection>(),
  }
}
const map = { map_id: 'map-a', width: 4, height: 4, resolution: 1, origin: [0, 0, 0] as [number, number, number], data: new Array(16).fill(0) }

beforeEach(() => { vi.useFakeTimers(); hooks.effects = []; hooks.values = []; hooks.rules = null; vi.mocked(requestSimulation).mockReset() })
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

describe('workspace out-of-order resource replies', () => {
  it('retains the newer navigation application report and routes when an older GET finishes last', async () => {
    const old = round({ map_id: 'map-a', revision: 3, zones: [], apply_state: 'applied', message: '旧确认' }, 'old-route')
    const latest = round({ ...old.rules, apply_state: 'published', message: '当前等待恢复确认' }, 'new-route')
    let batch = old
    vi.mocked(requestSimulation).mockImplementation((path) => {
      const value = path === 'map-rules' ? batch.pendingRules.promise : path === 'routes' ? batch.pendingRoutes.promise : batch.pendingRuns.promise
      return value as ReturnType<typeof requestSimulation>
    })
    const workspace = useSimulationWorkspace(map, false)
    const dispose = hooks.effects[0]()
    batch = latest
    const refresh = workspace.refresh()
    latest.pendingRules.resolve(latest.rules)
    latest.pendingRoutes.resolve(latest.routes)
    latest.pendingRuns.resolve({ runs: [] })
    await refresh
    old.pendingRules.resolve(old.rules)
    old.pendingRoutes.resolve(old.routes)
    old.pendingRuns.resolve({ runs: [] })
    await vi.advanceTimersByTimeAsync(0)
    const editor = hooks.rules as ReturnType<typeof emptyRulesEditor>
    expect(editor.saved?.apply_state).toBe('published')
    expect(editor.saved?.message).toBe('当前等待恢复确认')
    expect(hooks.values).toContainEqual(latest.routes.routes)
    expect(hooks.values).not.toContainEqual(old.routes.routes)
    dispose?.()
  })
})
