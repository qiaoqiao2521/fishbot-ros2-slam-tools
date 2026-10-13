import { describe, expect, it, vi } from 'vitest'
import {
  COOPERATION_STALE_MS, CooperationController, EMPTY_COOPERATION_SNAPSHOT,
  cooperationCanCancel, cooperationCanReset, cooperationCanStart, cooperationFrameLabel, cooperationFrameSourceKey,
  validateCooperationState, type CooperationResetRecord, type CooperationSnapshot, type CooperationState,
} from './cooperation'

const completed: CooperationState = {
  mode: 'mujoco', domain: 114, ready: false, reason: '货物已交付', episode_id: 'episode-a',
  reset: { available: true, reason: '可重置', pending: false, last: null }, history: [],
  task: { id: 'old-task', status: 'succeeded', stage: 'delivery_stopped', message: '旧回合运输完成' },
  events: [{ sequence: 1, time_s: 20, role: 'car', message: '旧回合实际反馈' }],
  physics: null, nav: null, stations: null, frame: { available: false, stamp: null }, source: { scene_sha: 'unchanged-xml-sha' },
}
const prepared: CooperationState = {
  ...completed, ready: true, reason: '新回合已就绪', episode_id: 'episode-b',
  task: { id: null, status: 'idle', stage: 'idle', message: '等待开始' }, events: [],
  history: [{ episode_id: 'episode-a', task: completed.task, events: completed.events, completed_at: 100 }],
  reset: { available: true, reason: '可重置', pending: false,
    last: { request_id: 'reset-a', status: 'succeeded', from_episode: 'episode-a', to_episode: 'episode-b', message: '已重置' } },
}
const pendingRecord: CooperationResetRecord = { request_id: 'reset-a', episode_id: 'episode-a', status: 'pending', new_episode_id: null, message: '正在重置' }
const successRecord: CooperationResetRecord = { ...pendingRecord, status: 'succeeded', new_episode_id: 'episode-b', message: '已重置' }
function response(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status }) }
function snapshot(state = completed): CooperationSnapshot { return { ...EMPTY_COOPERATION_SNAPSHOT, state, receivedAt: 10000 } }

describe('episode-bound cooperation reset', () => {
  it('requires fresh server admission and terminal ownership, independently of start readiness', () => {
    expect(cooperationCanReset(snapshot(), 10000)).toBe(true)
    expect(cooperationCanStart(snapshot(), 10000)).toBe(false)
    for (const status of ['running', 'canceling', 'unknown'] as const) {
      expect(cooperationCanReset(snapshot({ ...completed, task: { ...completed.task, status } }), 10000)).toBe(false)
    }
    for (const status of ['idle', 'succeeded', 'failed', 'canceled'] as const) {
      expect(cooperationCanReset(snapshot({ ...completed, task: { ...completed.task, status } }), 10000)).toBe(true)
    }
    expect(cooperationCanReset(snapshot(), 10000 + COOPERATION_STALE_MS)).toBe(false)
    expect(cooperationCanReset(snapshot({ ...completed, reset: { ...completed.reset!, available: false } }), 10000)).toBe(false)
    expect(cooperationCanReset(snapshot({ ...completed, reset: { ...completed.reset!, pending: true } }), 10000)).toBe(false)
    expect(cooperationCanReset({ ...snapshot(), pending: 'start' }, 10000)).toBe(false)
    expect(cooperationCanReset({ ...snapshot(), receipt: { action: 'start', taskId: 'lost-task', unknown: true } }, 10000)).toBe(false)
    const unresolved = { ...snapshot(prepared), resetReceipt: { requestId: 'reset-a', fromEpisode: 'episode-a', unknown: true } }
    expect(cooperationCanReset(unresolved, 10000)).toBe(false)
    expect(cooperationCanStart(unresolved, 10000)).toBe(false)
  })

  it('keeps legacy start support while rejecting malformed reset and history metadata', () => {
    const legacy = { ...prepared, episode_id: undefined, reset: undefined, history: undefined }
    expect(validateCooperationState(legacy)).toEqual(legacy)
    expect(cooperationCanStart(snapshot(legacy), 10000)).toBe(true)
    expect(cooperationCanReset(snapshot(legacy), 10000)).toBe(false)
    for (const patch of [{ episode_id: '' }, { reset: { ...prepared.reset!, pending: 'yes' } },
      { history: [{ ...prepared.history![0], task: { ...completed.task, status: 'invented' } }] }]) {
      expect(() => validateCooperationState({ ...prepared, ...patch })).toThrow('状态不完整')
    }
  })

  it('posts a reset only once, retains the old result, and starts only after another explicit click', async () => {
    let current = completed, resetRecord = pendingRecord
    const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') return response(String(url).endsWith('/reset') ? { request_id: 'reset-a', status: 'pending' } : { task_id: 'new-task' })
      return response(String(url).includes('/reset/') ? resetRecord : current)
    })
    const controller = new CooperationController({ fetcher, now: () => 10000, resetId: () => 'reset-a', taskId: () => 'new-task' })
    await controller.refresh(); await controller.reset(); await controller.reset()
    expect(controller.getSnapshot().state?.task).toEqual(completed.task)
    expect(controller.getSnapshot().resetReceipt).toEqual({ requestId: 'reset-a', fromEpisode: 'episode-a', unknown: false })
    const posts = fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')
    expect(posts).toHaveLength(1)
    expect(JSON.parse(posts[0][1]!.body as string)).toEqual({ request_id: 'reset-a', issued_at: 10, episode_id: 'episode-a' })
    current = prepared; resetRecord = successRecord
    await controller.refresh()
    expect(controller.getSnapshot().resetReceipt).toBeNull()
    expect(controller.getSnapshot().state?.history).toEqual(prepared.history)
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
    await controller.act('start')
    const start = fetcher.mock.calls.find(([url, init]) => String(url).endsWith('/start') && init?.method === 'POST')!
    expect(JSON.parse(start[1]!.body as string)).toEqual({ task_id: 'new-task', issued_at: 10, episode_id: 'episode-b' })
  })

  it('reconciles a lost reset response by its original request without late automatic start', async () => {
    let current = completed, resetRecord: CooperationResetRecord | null = null
    const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') throw new Error('回执丢失')
      if (String(url).includes('/reset/')) {
        if (!resetRecord) throw new Error('尚未读取到记录')
        return response(resetRecord)
      }
      return response(current)
    })
    const controller = new CooperationController({ fetcher, now: () => 10000, resetId: () => 'reset-a' })
    await controller.refresh(); await controller.reset()
    expect(controller.getSnapshot().resetReceipt?.unknown).toBe(true)
    await controller.reset()
    current = prepared; resetRecord = successRecord
    await controller.refresh(); await controller.refresh()
    expect(controller.getSnapshot().resetReceipt).toBeNull()
    expect(fetcher.mock.calls.filter(([url, init]) => String(url).endsWith('/reset') && init?.method === 'POST')).toHaveLength(1)
    expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith('/start'))).toHaveLength(0)
    expect(fetcher.mock.calls.some(([url]) => String(url) === '/coop-api/reset/reset-a')).toBe(true)
  })

  it.each(['accepted', 'lost'] as const)('keeps GET-confirmed success when the reset POST is late: %s', async (outcome) => {
    let current = completed
    let acceptPost!: (value: Response) => void
    let rejectPost!: (error: Error) => void
    const post = new Promise<Response>((resolve, reject) => { acceptPost = resolve; rejectPost = reject })
    const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') { current = prepared; return post }
      return response(String(url).includes('/reset/') ? successRecord : current)
    })
    const controller = new CooperationController({ fetcher, now: () => 10000, resetId: () => 'reset-a' })
    await controller.refresh()
    const action = controller.reset()
    await controller.refresh()
    expect(controller.getSnapshot().resetReceipt).toBeNull()
    expect(controller.getSnapshot().state?.episode_id).toBe('episode-b')
    expect(controller.getSnapshot().pending).toBe('reset')
    const lateSnapshots: CooperationSnapshot[] = []
    const unsubscribe = controller.subscribe((value) => { lateSnapshots.push(value) })
    if (outcome === 'accepted') acceptPost(response({ request_id: 'reset-a', status: 'pending' }))
    else rejectPost(new Error('迟到的 POST 连接超时'))
    await action
    unsubscribe()
    expect(lateSnapshots.length).toBeGreaterThan(0)
    expect(lateSnapshots.every((value) => value.resetReceipt === null && value.actionError === null)).toBe(true)
    expect(controller.getSnapshot().pending).toBeNull()
    expect(controller.getSnapshot().state?.history).toEqual(prepared.history)
    expect(cooperationCanStart(controller.getSnapshot(), 10000)).toBe(true)
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
    expect(fetcher.mock.calls.some(([url]) => String(url).endsWith('/start'))).toBe(false)
  })

  it.each([
    { ...successRecord, request_id: 'another-reset' },
    { ...successRecord, episode_id: 'another-episode' },
    { ...successRecord, new_episode_id: 'episode-a' },
    { ...pendingRecord, status: 'unknown' as const },
  ])('does not unlock on a mismatched or unknown reset record', async (resetRecord) => {
    let current = completed
    const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') return response({ request_id: 'reset-a', status: 'pending' })
      return response(String(url).includes('/reset/') ? resetRecord : current)
    })
    const controller = new CooperationController({ fetcher, now: () => 10000, resetId: () => 'reset-a' })
    await controller.refresh(); await controller.reset()
    current = prepared; await controller.refresh(); await controller.act('start'); await controller.reset()
    expect(controller.getSnapshot().resetReceipt?.unknown).toBe(true)
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  })

  it('requires the successful receipt destination to match the current episode', async () => {
    let current = completed
    const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => init?.method === 'POST'
      ? response({ request_id: 'reset-a', status: 'pending' }) : response(String(url).includes('/reset/') ? successRecord : current))
    const controller = new CooperationController({ fetcher, now: () => 10000, resetId: () => 'reset-a' })
    await controller.refresh(); await controller.reset()
    current = { ...prepared, episode_id: 'episode-c' }; await controller.refresh()
    expect(controller.getSnapshot().resetReceipt?.unknown).toBe(true)
    current = { ...prepared, ready: false }; await controller.refresh()
    expect(controller.getSnapshot().resetReceipt).toBeNull()
    expect(cooperationCanStart(controller.getSnapshot(), 10000)).toBe(false)
  })

  it('persists an unknown reset even without task ownership and reload only reads it', async () => {
    const values = new Map<string, string>()
    const storage = { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value) }, removeItem: (key: string) => { values.delete(key) } }
    const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST' || String(url).includes('/reset/')) throw new Error('连接中断')
      return response(completed)
    })
    const controller = new CooperationController({ fetcher, storage, now: () => 10000, resetId: () => 'reset-a' })
    await controller.refresh(); await controller.reset()
    expect(controller.getSnapshot().ownedTaskId).toBeNull(); expect(values.size).toBe(1)
    fetcher.mockClear()
    const reloaded = new CooperationController({ fetcher, storage, now: () => 10000 })
    await reloaded.refresh(); await reloaded.reset(); await reloaded.act('start')
    expect(reloaded.getSnapshot().resetReceipt).toEqual({ requestId: 'reset-a', fromEpisode: 'episode-a', unknown: true })
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
    expect(fetcher.mock.calls[0][0]).toBe('/coop-api/reset/reset-a')
  })

  it('reports a confirmed failed reset and never cancels a task taken over by another page', async () => {
    let current = completed, resetRecord: CooperationResetRecord = pendingRecord
    const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => init?.method === 'POST'
      ? response({ request_id: 'reset-a', status: 'pending' }) : response(String(url).includes('/reset/') ? resetRecord : current))
    const controller = new CooperationController({ fetcher, now: () => 10000, resetId: () => 'reset-a' })
    await controller.refresh(); await controller.reset()
    resetRecord = { ...pendingRecord, status: 'failed', message: '原生代价地图清理失败' }
    await controller.refresh()
    expect(controller.getSnapshot().resetReceipt).toBeNull()
    expect(controller.getSnapshot().actionError).toBe('原生代价地图清理失败')
    current = { ...prepared, ready: false, task: { ...completed.task, id: 'foreign-task', status: 'running' } }
    await controller.refresh(); await controller.act('cancel'); await controller.reset()
    expect(cooperationCanCancel(controller.getSnapshot(), 10000)).toBe(false)
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  })

  it('clears only an explicitly rejected reset receipt and keeps the completed result', async () => {
    const fetcher = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => init?.method === 'POST'
      ? response({ outcome: 'rejected', reason: '原回合已变化' }, 409) : response(completed))
    const controller = new CooperationController({ fetcher, now: () => 10000, resetId: () => 'reset-a' })
    await controller.refresh(); await controller.reset()
    expect(controller.getSnapshot().resetReceipt).toBeNull()
    expect(controller.getSnapshot().actionError).toBe('原回合已变化')
    expect(controller.getSnapshot().state?.task.status).toBe('succeeded')
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes('/reset/'))).toHaveLength(0)
  })

  it('binds frame identity to the episode without altering the actual XML SHA', () => {
    const old = { ...completed, frame: { available: true, stamp: 10 } }
    const next = { ...prepared, frame: { available: true, stamp: 10 } }
    const frame = { scene: cooperationFrameSourceKey(old)!, stamp: 10, changedAt: 10000, loadedStamp: 10, error: false }
    expect(old.source?.scene_sha).toBe(next.source?.scene_sha)
    expect(cooperationFrameSourceKey(old)).not.toBe(cooperationFrameSourceKey(next))
    expect(cooperationFrameLabel(next, frame, true, 10000)).toBe('画面来源已变化，等待新帧')
  })
})
