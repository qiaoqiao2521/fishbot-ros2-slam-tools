import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import { CooperationPage, CooperationView } from '@/components/cooperation/cooperation-page'
import { COOPERATION_STALE_MS, EMPTY_COOPERATION_SNAPSHOT, cooperationFrameSourceKey, type CooperationController, type CooperationSnapshot, type CooperationState, type CooperationFrameObservation } from '@/lib/cooperation'

const hooks = vi.hoisted(() => ({ active: false, cursor: 0, values: [] as unknown[], effects: [] as Array<() => (() => void) | undefined>,
  frames: null as null | { display: (url: string | null) => void; observe: (frame: CooperationFrameObservation | null) => void },
}))
vi.mock('@/lib/cooperation-frame', async (original) => {
  const actual = await original<typeof import('@/lib/cooperation-frame')>()
  return { CooperationFrameBuffer: class extends actual.CooperationFrameBuffer {
    constructor(options: ConstructorParameters<typeof actual.CooperationFrameBuffer>[0]) { super(options); if (hooks.active && options.endpoint !== 'vision-frame.jpg') hooks.frames = options }
    request(scene: string | null, stamp: number | null) { if (!hooks.active) super.request(scene, stamp) }
  } }
})
vi.mock('react', async (original) => {
  const actual = await original<typeof import('react')>()
  return { ...actual,
    useRef: (current: unknown) => hooks.active ? { current } : actual.useRef(current),
    useEffect: (effect: () => (() => void) | undefined, dependencies: unknown[]) => {
      if (hooks.active) hooks.effects.push(effect)
      else actual.useEffect(effect, dependencies)
    },
    useState: (initial: unknown) => {
      if (!hooks.active) return actual.useState(initial)
      const index = hooks.cursor++
      if (index >= hooks.values.length) hooks.values[index] = typeof initial === 'function' ? initial() : initial
      return [hooks.values[index], (value: unknown) => {
        hooks.values[index] = typeof value === 'function' ? value(hooks.values[index]) : value
      }]
    },
  }
})

const state: CooperationState = {
  mode: 'mujoco', domain: 114, ready: true, reason: '已就绪',
  task: { id: 'task-a', status: 'running', stage: 'arm_lift', message: '实际夹指接触确认，正在抬升' },
  events: [{ sequence: 2, time_s: 12, role: 'arm', message: '已检测到双侧夹指接触，开始抬起货物。' },
    { sequence: 1, time_s: 10, role: 'car', message: '已到固定工位，速度检查通过。' }],
  physics: { stamp: 12.5, car: { x: 1.1, y: 0.3, yaw: 0, linear_speed: 0, angular_speed: 0 },
    arm: { q: [0.1, 0.2], velocity: [0.3, 0.4] }, cargo: { x: 1.2, y: 0.3, z: 0.24, speed: 0.06, tip_forces: [2.1, 1.9], tray_contact: false } },
  frame: { available: true, stamp: 12.5 }, source: { scene_sha: 'actual-scene-sha-123' },
  nav: { ready: true, pose: { x: 1.09, y: 0.29, yaw: 0 } }, stations: null,
}
function render(patch: Partial<CooperationSnapshot> = {}, loaded = true) {
  return renderToStaticMarkup(<CooperationView snapshot={{ ...EMPTY_COOPERATION_SNAPSHOT, state, receivedAt: 10000, ownedTaskId: 'task-a', ...patch }}
    now={10000} frame={{ scene: 'actual-scene-sha-123', stamp: 12.5, changedAt: 10000, loadedStamp: loaded ? 12.5 : null, error: !loaded }}
    onBack={() => {}} onStart={() => {}} onCancel={() => {}} onReset={() => {}} onRefresh={() => {}} />)
}

describe('cooperation page evidence rendering', () => {
  it('renders the actual camera source, current stage, source SHA and physical cargo state', () => {
    const html = render()
    expect(html).toContain('/coop-api/frame.jpg?stamp=12.5')
    expect(html).toContain('data-frame-live="true"')
    expect(html).toContain('相机画面持续更新')
    expect(html).toContain('aria-current="step"')
    expect(html).toContain('抬起货物')
    expect(html).toContain('actual-scene-sha-123')
    expect(html).toContain('0.240 m')
    expect(html).toContain('2.10 / 1.90 N')
    expect(html).toContain('当前无托盘接触')
    expect(html).not.toContain('物品已放稳')
  })

  it('visibly discloses the ideal simulation beacon beside the loading workflow', () => {
    const html = render()
    const workflow = html.slice(html.indexOf('<div class="cooperation-process">'), html.indexOf('<aside class="cooperation-sidebar">'))
    expect(workflow).toContain('<p>近距离精停靠使用理想化仿真信标；未接入视觉识别。</p>')
    expect(workflow).not.toContain('hidden')
    expect(workflow).not.toContain('aria-hidden')
    expect(workflow).toContain('当前阶段')
  })

  it.each(['vision', 'perturbed'])('discloses the actual %s mode instead of retaining the ideal-beacon claim', (mode) => {
    const html = render({ state: { ...state, perception: { mode, publisher: 'actual-publisher', detected: false,
      reason: '等待已确认观测', confidence: null, stamp: null, received_age_s: null, source_age_s: null,
      counts: {}, reprojection_error_px: null } } })
    expect(html).toContain(mode === 'vision' ? '近距离精停靠使用 AprilTag 图像观测' : '近距离精停靠使用受扰仿真信标')
    expect(html).not.toContain('近距离精停靠使用理想化仿真信标；未接入视觉识别')
    expect(html).toContain('等待已确认观测')
  })

  it('rejects the previous source in the first render before camera effects clear it', () => {
    const html = render({ state: { ...state, source: { scene_sha: 'replacement-scene' } } })
    expect(html).toContain('画面来源已变化，等待新帧')
    expect(html).toContain('data-frame-live="false"'); expect(html).not.toContain('<img')
    expect(html).toContain('相机仿真时间 未收到')
  })

  it('hides the previous episode immediately when its clock restarts', () => {
    const html = render({ state: { ...state, frame: { available: true, stamp: 1 } } })
    expect(html).toContain('画面已过期'); expect(html).not.toContain('<img')
    expect(html).toContain('相机仿真时间 未收到')
  })

  it('shows backend messages in sequence without generating cooperation dialogue', () => {
    const html = render()
    expect(html.indexOf('已到固定工位，速度检查通过。')).toBeLessThan(html.indexOf('已检测到双侧夹指接触，开始抬起货物。'))
    const empty = render({ state: { ...state, events: [], task: { id: null, status: 'idle', stage: 'idle', message: '等待任务' } } })
    expect(empty).toContain('尚未收到合作消息')
    expect(empty).not.toContain('已到固定工位，速度检查通过。')
    expect(empty).not.toContain('已检测到双侧夹指接触')
  })

  it('clearly labels missing or failed camera frames without a live claim', () => {
    const failed = render({}, false)
    expect(failed).toContain('相机画面读取失败')
    expect(failed).toContain('data-frame-live="false"')
    expect(failed).not.toContain('相机画面持续更新')
    const missing = render({ state: { ...state, frame: { available: false, stamp: null } } })
    expect(missing).toContain('等待实际相机画面')
    expect(missing).not.toContain('<img')
  })

  it('keeps unknown receipts and original stop reasons visible', () => {
    const html = render({ receipt: { action: 'cancel', taskId: 'task-a', unknown: true },
      actionError: '回执未知，请勿重复派发。', state: { ...state, ready: false, reason: '仿真时钟暂停',
        task: { ...state.task, status: 'canceling', stop_reason: '仿真时钟暂停' } } })
    expect(html).toContain('操作回执未知')
    expect(html).toContain('只读取任务 task-a')
    expect(html).toContain('停止原因：仿真时钟暂停')
    expect(html).toContain('正在取消，等待停稳')
    expect(html.match(/disabled=""/g)).toHaveLength(2)
    expect(html).not.toContain('装货运输完成')
  })

  it.each(['running', 'succeeded'] as const)('shows %s dock feedback without claiming arm loading or full transport', (status) => {
    const html = render({ state: { ...state, task: { ...state.task, scope: 'dock', status,
      stage: status === 'succeeded' ? 'succeeded' : 'car_to_dock', message: status === 'succeeded' ? '停靠完成' : '正在停靠' } } })
    expect(html).toContain('停靠任务')
    expect(html).toContain(status === 'succeeded' ? '停靠完成' : '停靠进行中')
    expect(html).toContain('本回合未执行装货')
    expect(html).not.toContain('机械臂已退出')
    expect(html).not.toContain('装货运输完成')
    expect(html).not.toContain('装货运输流程')
    const flow = html.match(/<div class="cooperation-process">([\s\S]*?)<\/ol>/)?.[1]
    expect(flow).toContain('停靠流程')
    expect(flow).toContain('确认小车停稳')
    expect(flow).not.toContain('机械臂抓取')
    expect(flow).not.toContain('小车运输')
    if (status === 'succeeded') expect(html).toContain('停靠停稳验证完成')
    // The existing start action still requests a complete transport task.
    expect(html).toContain('开始装货运输')
  })

  it.each([undefined, 'transport'] as const)('retains complete transport wording for scope %s', (scope) => {
    const html = render({ state: { ...state, task: { ...state.task, scope, status: 'succeeded',
      stage: 'delivery_stopped', message: '实际装货运输完成' } } })
    expect(html).toContain('装货运输任务')
    expect(html).toContain('装货运输流程')
    expect(html).toContain('装货运输完成')
    expect(html).toContain('机械臂已退出')
    expect(html).not.toContain('本回合未执行装货')
  })

  it('labels archived dock success independently from legacy transport success', () => {
    const task = { ...state.task, status: 'succeeded' as const, stage: 'succeeded', message: '历史任务已完成' }
    const html = render({ state: { ...state, history: [
      { episode_id: 'dock-episode', task: { ...task, id: 'dock-task', scope: 'dock' }, events: [], completed_at: 10000 },
      { episode_id: 'transport-episode', task: { ...task, id: 'transport-task' }, events: [], completed_at: 10001 },
    ] } })
    const summaries = [...html.matchAll(/<summary>(.*?)<\/summary>/g)].map((match) => match[1])
    expect(summaries).toHaveLength(2)
    expect(summaries.find((summary) => summary.startsWith('停靠完成'))).toBeDefined()
    expect(summaries.find((summary) => summary.startsWith('装货运输完成'))).toBeDefined()
  })

  it('explains why a delivered round cannot start again without resetting the synthetic scene', () => {
    const html = render({ state: { ...state, ready: false, reason: '物体已离开取货盘；本回合完成后需重置合成场景',
      task: { ...state.task, status: 'succeeded', stage: 'delivery_stopped', message: '装货运输完成' } } })
    expect(html).toContain('装货运输完成')
    expect(html).toContain('需重置合成场景')
    expect(html.match(/disabled=""/g)).toHaveLength(2)
    expect(html).not.toContain('当前任务尚未结束')
    expect(html).toContain('当前协同服务不支持网页重置')
  })

  it('offers a distinct reset action after delivery and explains the next explicit start', () => {
    const html = render({ state: { ...state, episode_id: 'episode-a', ready: false, reason: '本回合已交付',
      reset: { available: true, reason: '可恢复到新回合', pending: false, last: null },
      task: { ...state.task, status: 'succeeded', message: '旧任务装货运输完成' } } })
    const resetButton = html.match(/<button\b[^>]*>(?:(?!<\/button>).)*重置场景<\/button>/s)?.[0]
    expect(resetButton).toBeDefined(); expect(resetButton).not.toContain('disabled=')
    const startButton = html.match(/<button\b[^>]*>(?:(?!<\/button>).)*开始装货运输<\/button>/s)?.[0]
    expect(startButton).toContain('disabled=')
    expect(html).toContain('旧任务装货运输完成')
    expect(html).toContain('重置完成后，请再点击')
  })

  it('keeps reset receipts visible and blocks every mutation while their result is unknown', () => {
    const html = render({ resetReceipt: { requestId: 'reset-a', fromEpisode: 'episode-a', unknown: true },
      state: { ...state, episode_id: 'episode-a', reset: { available: true, reason: '可重置', pending: false, last: null },
        task: { ...state.task, status: 'succeeded' } } })
    expect(html).toContain('场景重置回执未知')
    expect(html).toContain('只读取重置请求 reset-a，原回合 episode-a')
    expect(html).toContain('不重复重置，不自动开始运输')
    expect(html.match(/disabled=""/g)).toHaveLength(3)
  })

  it('preserves server history and presents a ready new episode without replaying its old task', () => {
    const html = render({ state: { ...state, episode_id: 'episode-b',
      task: { id: null, status: 'idle', stage: 'idle', message: '等待本轮开始' }, events: [],
      reset: { available: true, reason: '可重置', pending: false,
        last: { request_id: 'reset-a', status: 'succeeded', from_episode: 'episode-a', to_episode: 'episode-b', message: '已重置' } },
      history: [{ episode_id: 'episode-a', task: { id: 'archived-task', status: 'succeeded', stage: 'delivery_stopped', message: '历史运输已完成' },
        events: [{ sequence: 1, time_s: 40, role: 'car', message: '历史实际交付反馈' }], completed_at: 10000 }] } })
    expect(html).toContain('新回合已就绪，请点击开始装货运输')
    expect(html).toContain('由协同服务保存')
    expect(html).toContain('archived-task'); expect(html).toContain('episode-a'); expect(html).toContain('episode-b')
    expect(html).toContain('历史运输已完成'); expect(html).toContain('历史实际交付反馈')
    const startButton = html.match(/<button\b[^>]*>(?:(?!<\/button>).)*开始装货运输<\/button>/s)?.[0]
    expect(startButton).toBeDefined(); expect(startButton).not.toContain('disabled=')
  })

  it('rejects an old episode frame on the first render even with the same scene SHA and stamp', () => {
    const oldState = { ...state, episode_id: 'episode-a' }
    const html = renderToStaticMarkup(<CooperationView snapshot={{ ...EMPTY_COOPERATION_SNAPSHOT, state: { ...oldState, episode_id: 'episode-b' }, receivedAt: 10000 }}
      now={10000} frame={{ scene: cooperationFrameSourceKey(oldState)!, stamp: 12.5, changedAt: 10000, loadedStamp: 12.5, error: false }}
      displayedFrameSrc="blob:old-episode" onBack={() => {}} onStart={() => {}} onCancel={() => {}} onRefresh={() => {}} />)
    expect(html).not.toContain('<img'); expect(html).toContain('data-frame-live="false"')
    expect(html).toContain('画面来源已变化'); expect(html).toContain('相机仿真时间 未收到')
    expect(html).toContain('actual-scene-sha-123')
  })

  it('expires the real rendered frame and readiness while the next GET remains hung', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(10000)
    hooks.active = true
    hooks.cursor = 0
    hooks.values = []
    hooks.effects = []
    const initial: CooperationSnapshot = { ...EMPTY_COOPERATION_SNAPSHOT, state: { ...state, task: { ...state.task, status: 'idle', id: null } }, receivedAt: 10000 }
    const controller = {
      getSnapshot: () => initial, subscribe: () => () => {}, refresh: vi.fn(() => new Promise<void>(() => {})), act: vi.fn(),
    } as unknown as CooperationController
    const cleanups: Array<(() => void) | undefined> = []
    try {
      let page = CooperationPage({ onBack: () => {}, controller })
      cleanups.push(...hooks.effects.map((effect) => effect()))
      hooks.frames!.display('blob:decoded-frame')
      hooks.frames!.observe({ scene: 'actual-scene-sha-123', stamp: 12.5, changedAt: 10000, loadedStamp: 12.5, error: false })
      hooks.cursor = 0
      page = CooperationPage({ onBack: () => {}, controller })
      expect(renderToStaticMarkup(page)).toContain('data-frame-live="true"')
      await vi.advanceTimersByTimeAsync(COOPERATION_STALE_MS)
      hooks.cursor = 0
      page = CooperationPage({ onBack: () => {}, controller })
      const expired = renderToStaticMarkup(page)
      expect(expired).toContain('data-frame-live="false"')
      expect(expired).toContain('画面已过期')
      expect(expired).toContain('状态已过期')
      expect(expired.match(/disabled=""/g)).toHaveLength(2)
      expect(controller.refresh).toHaveBeenCalledTimes(1)
      expect(controller.act).not.toHaveBeenCalled()
      cleanups.forEach((cleanup) => cleanup?.())
      cleanups.length = 0
      expect(vi.getTimerCount()).toBe(0)
    } finally {
      cleanups.forEach((cleanup) => cleanup?.())
      hooks.active = false
      vi.useRealTimers()
    }
  })
})
