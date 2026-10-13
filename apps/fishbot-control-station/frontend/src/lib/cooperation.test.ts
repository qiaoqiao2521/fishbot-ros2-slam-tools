import { describe, expect, it, vi } from 'vitest'

import {
  COOPERATION_STALE_MS, CooperationController, EMPTY_COOPERATION_SNAPSHOT,
  cooperationCanCancel, cooperationCanStart, cooperationFrameLabel, validateCooperationState,
  type CooperationSnapshot, type CooperationState,
} from '@/lib/cooperation'

const idle: CooperationState = {
  mode: 'mujoco', domain: 114, ready: true, reason: '共享场景已就绪',
  task: { id: null, status: 'idle', stage: 'idle', message: '等待开始' }, events: [],
  physics: { stamp: 10, car: { x: 0, y: 0, yaw: 0, linear_speed: 0, angular_speed: 0 },
    arm: { q: [0, 1], velocity: [0, 0] }, cargo: { x: 0.1, y: 0, z: 0.2, speed: 0, tip_forces: [0, 0], tray_contact: false } },
  frame: { available: true, stamp: 10 }, source: { scene_sha: 'scene-a' },
  nav: { ready: true, pose: { x: 0, y: 0, yaw: 0 } },
  stations: { dock: { x: 1, y: 0, yaw: 0 }, delivery: { x: 2, y: 0, yaw: 0 } },
}
function response(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status }) }
function snapshot(state = idle): CooperationSnapshot { return { ...EMPTY_COOPERATION_SNAPSHOT, state, receivedAt: 10000 } }

describe('cooperation service validation and action gates', () => {
  it('rejects another domain and malformed actual feedback while accepting startup nulls', () => {
    expect(validateCooperationState(idle)).toEqual(idle)
    expect(validateCooperationState({ ...idle, ready: false, physics: null, source: null, nav: null, stations: null }).ready).toBe(false)
    expect(() => validateCooperationState({ ...idle, domain: 107 })).toThrow('ROS 域不匹配')
    expect(() => validateCooperationState({ ...idle, frame: { available: true, stamp: Number.NaN } })).toThrow()
    expect(() => validateCooperationState({ ...idle, physics: { ...idle.physics, arm: { q: [0], velocity: [] } } })).toThrow('物理反馈不完整')
    expect(() => validateCooperationState({ ...idle, events: [{ sequence: 1, time_s: 10, role: 'invented', message: 'arrived' }] })).toThrow()
  })

  it('starts only from fresh backend readiness and a final task state', () => {
    expect(cooperationCanStart(snapshot(), 10000)).toBe(true)
    for (const status of ['running', 'canceling', 'unknown'] as const) {
      expect(cooperationCanStart(snapshot({ ...idle, task: { ...idle.task, id: 'task-a', status } }), 10000)).toBe(false)
    }
    expect(cooperationCanStart(snapshot({ ...idle, ready: false, reason: '仿真暂停' }), 10000)).toBe(false)
    expect(cooperationCanStart(snapshot(), 10000 + COOPERATION_STALE_MS)).toBe(false)
    expect(cooperationCanStart({ ...snapshot(), receipt: { action: 'start', taskId: 'task-a', unknown: true } }, 10000)).toBe(false)
  })

  it('cancels only the task owned by this page, including when simulation readiness is paused', () => {
    const running = snapshot({ ...idle, ready: false, task: { ...idle.task, id: 'task-a', status: 'running' } })
    expect(cooperationCanCancel({ ...running, ownedTaskId: 'task-a' }, 10000)).toBe(true)
    expect(cooperationCanCancel({ ...running, ownedTaskId: 'task-b' }, 10000)).toBe(false)
    expect(cooperationCanCancel({ ...running, ownedTaskId: 'task-a', receipt: { action: 'cancel', taskId: 'task-a', unknown: true } }, 10000)).toBe(false)
  })
})

describe('cooperation receipts', () => {
  it('posts start once, preserves its UUID after unknown delivery, and reconciles only that task', async () => {
    let current = idle
    const fetcher = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') throw new Error('连接中断')
      return response(current)
    })
    const controller = new CooperationController({ fetcher, now: () => 10000, taskId: () => 'task-a' })
    await controller.refresh()
    await controller.act('start')
    expect(controller.getSnapshot().receipt).toEqual({ action: 'start', taskId: 'task-a', unknown: true })
    expect(controller.getSnapshot().actionError).toContain('回执未知')
    await controller.act('start')
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
    const start = fetcher.mock.calls.find(([, init]) => init?.method === 'POST')!
    expect(start[0]).toBe('/coop-api/start')
    expect(JSON.parse(start[1]!.body as string)).toEqual({ task_id: 'task-a', issued_at: 10 })
    current = { ...idle, task: { ...idle.task, id: 'task-b', status: 'succeeded' } }
    await controller.refresh()
    expect(controller.getSnapshot().receipt?.taskId).toBe('task-a')
    current = { ...idle, task: { ...idle.task, id: 'task-a', status: 'running', stage: 'car_to_dock' } }
    await controller.refresh()
    expect(fetcher.mock.calls.at(-1)?.[0]).toBe('/coop-api/state?task_id=task-a')
    expect(controller.getSnapshot().receipt).toBeNull()
    expect(controller.getSnapshot().state?.task.stage).toBe('car_to_dock')
    expect(controller.getSnapshot().actionError).toBeNull()
  })

  it('waits for exact task status after an accepted receipt instead of inferring success', async () => {
    let current = idle
    const fetcher = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => response(init?.method === 'POST' ? { task_id: 'task-a' } : current))
    const controller = new CooperationController({ fetcher, now: () => 10000, taskId: () => 'task-a' })
    await controller.refresh()
    await controller.act('start')
    expect(controller.getSnapshot().receipt?.unknown).toBe(false)
    expect(controller.getSnapshot().state?.task.status).toBe('idle')
    expect(cooperationCanStart(controller.getSnapshot(), 10000)).toBe(false)
    current = { ...idle, task: { ...idle.task, id: 'task-a', status: 'failed', message: '抓取失败', stop_reason: '接触力不足' } }
    await controller.refresh()
    expect(controller.getSnapshot().receipt).toBeNull()
    expect(controller.getSnapshot().state?.task.stop_reason).toBe('接触力不足')
  })

  it('does not retry unknown cancellation or treat canceling as final', async () => {
    let current: CooperationState = idle
    const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url).endsWith('/start') && init?.method === 'POST') {
        current = { ...idle, task: { ...idle.task, id: 'task-a', status: 'running' } }
        return response({ task_id: 'task-a' })
      }
      if (init?.method === 'POST') throw new Error('取消回执丢失')
      return response(current)
    })
    const controller = new CooperationController({ fetcher, now: () => 10000, taskId: () => 'task-a' })
    await controller.refresh()
    await controller.act('start')
    await controller.act('cancel')
    current = { ...current, task: { ...current.task, status: 'canceling' } }
    await controller.refresh()
    await controller.act('cancel')
    expect(controller.getSnapshot().receipt?.action).toBe('cancel')
    expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith('/cancel'))).toHaveLength(1)
    current = { ...current, task: { ...current.task, status: 'canceled', stop_reason: '用户取消' } }
    await controller.refresh()
    expect(controller.getSnapshot().receipt).toBeNull()
    expect(controller.getSnapshot().state?.task.status).toBe('canceled')
    expect(controller.getSnapshot().state?.task.stop_reason).toBe('用户取消')
  })

  it('surfaces explicit rejected reasons without locking an unaccepted task', async () => {
    const fetcher = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => init?.method === 'POST'
      ? response({ outcome: 'rejected', reason: '货物已交付，需要重置合成场景' }, 409) : response(idle))
    const controller = new CooperationController({ fetcher, now: () => 10000, taskId: () => 'task-a' })
    await controller.refresh()
    await controller.act('start')
    expect(controller.getSnapshot().receipt).toBeNull()
    expect(controller.getSnapshot().actionError).toBe('货物已交付，需要重置合成场景')
  })

  it('restores an unresolved receipt after page reload and only reads its original task', async () => {
    const values = new Map<string, string>()
    const storage = { getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value) }, removeItem: (key: string) => { values.delete(key) } }
    const fetcher = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') throw new Error('连接中断')
      return response(idle)
    })
    const controller = new CooperationController({ fetcher, storage, now: () => 10000, taskId: () => 'task-a' })
    await controller.refresh()
    await controller.act('start')
    fetcher.mockClear()
    const restored = new CooperationController({ fetcher, storage, now: () => 10000 })
    await restored.refresh()
    await restored.act('start')
    expect(restored.getSnapshot().receipt?.taskId).toBe('task-a')
    expect(fetcher.mock.calls).toHaveLength(1)
    expect(fetcher.mock.calls[0][0]).toBe('/coop-api/state?task_id=task-a')
    expect(fetcher.mock.calls[0][1]?.method).toBe('GET')
  })
})

describe('actual cooperation camera freshness', () => {
  const frame = { scene: 'scene-a', stamp: 10, changedAt: 10000, loadedStamp: 10, error: false }
  it('requires successful image loading and advancing source stamps before claiming live', () => {
    expect(cooperationFrameLabel(idle, frame, true, 10000)).toBe('相机画面持续更新')
    expect(cooperationFrameLabel({ ...idle, frame: { available: true, stamp: 11 } }, frame, true, 11000)).toBe('相机画面持续更新')
    expect(cooperationFrameLabel({ ...idle, frame: { available: true, stamp: 12 } }, frame, true, 11000)).toBe('画面已过期')
    expect(cooperationFrameLabel({ ...idle, source: { scene_sha: 'scene-b' } }, frame, true, 10000)).toBe('画面来源已变化，等待新帧')
    expect(cooperationFrameLabel(idle, { ...frame, loadedStamp: null }, true, 10000)).toBe('正在读取相机画面')
    expect(cooperationFrameLabel(idle, { ...frame, error: true }, true, 10000)).toBe('相机画面读取失败')
    expect(cooperationFrameLabel(idle, frame, true, 10000 + COOPERATION_STALE_MS)).toBe('画面已过期')
    expect(cooperationFrameLabel(idle, frame, false, 10000)).toBe('画面已过期')
    expect(cooperationFrameLabel({ ...idle, frame: { available: false, stamp: null } }, frame, true, 10000)).toBe('等待相机画面')
  })
})
