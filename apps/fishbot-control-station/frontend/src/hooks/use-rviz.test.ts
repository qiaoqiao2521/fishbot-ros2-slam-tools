import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useRviz } from '@/hooks/use-rviz'
import { requestSimulation, SIMULATION_DOMAIN, SimulationRejectedRequest } from '@/lib/simulation'

const hooks = vi.hoisted(() => ({ effects: [] as Array<() => (() => void) | undefined>, values: [] as unknown[] }))
vi.mock('react', () => ({
  useRef: (current: unknown) => ({ current }),
  useEffect: (effect: () => (() => void) | undefined) => hooks.effects.push(effect),
  useState: (initial: unknown) => {
    const index = hooks.values.push(initial) - 1
    return [initial, (value: unknown) => { hooks.values[index] = value }]
  },
}))
vi.mock('@/lib/simulation', async (original) => ({ ...await original<typeof import('@/lib/simulation')>(), requestSimulation: vi.fn() }))

const stopped = { available: true, running: false, domain: SIMULATION_DOMAIN, message: '可以打开 RViz' }
const running = { ...stopped, running: true, message: '已启动' }
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((complete) => { resolve = complete })
  return { promise, resolve }
}
function RvizHarness() { return useRviz() }
async function mount() {
  const rviz = RvizHarness()
  const dispose = hooks.effects[0]()
  await vi.advanceTimersByTimeAsync(0)
  return { rviz, dispose }
}
beforeEach(() => {
  vi.useFakeTimers()
  hooks.effects = []
  hooks.values = []
  vi.mocked(requestSimulation).mockReset()
})
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

describe('independent native RViz launch', () => {
  it('only reads capability on mount and submits one launch while duplicate clicks are pending', async () => {
    const launch = deferred<typeof running>()
    vi.mocked(requestSimulation).mockResolvedValueOnce(stopped).mockImplementationOnce(() => launch.promise)
    const { rviz, dispose } = await mount()
    expect(requestSimulation).toHaveBeenCalledWith('rviz', undefined, expect.any(AbortSignal))
    const pending = rviz.open()
    await rviz.open()
    expect(requestSimulation).toHaveBeenCalledTimes(2)
    expect(requestSimulation).toHaveBeenLastCalledWith('rviz', {}, expect.any(AbortSignal))
    launch.resolve(running)
    await pending
    expect(hooks.values[1]).toBe(false)
    expect(hooks.values[2]).toBe(`RViz 已在控制站电脑打开（ROS 域 ${SIMULATION_DOMAIN}）。`)
    dispose?.()
  })

  it('reconciles a lost launch receipt through GET without retrying POST', async () => {
    vi.mocked(requestSimulation).mockResolvedValueOnce(stopped).mockRejectedValueOnce(new Error('connection lost')).mockResolvedValueOnce(running)
    const { rviz, dispose } = await mount()
    await rviz.open()
    expect(vi.mocked(requestSimulation).mock.calls.map(([, body]) => body)).toEqual([undefined, {}, undefined])
    expect(hooks.values[3]).toBe(false)
    expect(hooks.values[2]).toContain(`ROS 域 ${SIMULATION_DOMAIN}`)
    dispose?.()
  })

  it('keeps unresolved receipt in read-only confirmation until a GET resolves it', async () => {
    vi.mocked(requestSimulation).mockResolvedValueOnce(stopped).mockRejectedValueOnce(new Error('connection lost'))
      .mockRejectedValueOnce(new Error('still offline')).mockResolvedValueOnce(running)
    const { rviz, dispose } = await mount()
    await rviz.open()
    expect(hooks.values[3]).toBe(true)
    expect(hooks.values[2]).toContain('确认 RViz 状态')
    await rviz.open()
    expect(vi.mocked(requestSimulation).mock.calls.map(([, body]) => body)).toEqual([undefined, {}, undefined, undefined])
    expect(hooks.values[3]).toBe(false)
    dispose?.()
  })

  it('shows explicit unavailability without calling any navigation operation', async () => {
    vi.mocked(requestSimulation).mockResolvedValueOnce(stopped).mockRejectedValueOnce(new SimulationRejectedRequest('控制站没有桌面会话', 503))
    const { rviz, dispose } = await mount()
    await rviz.open()
    expect(requestSimulation).toHaveBeenCalledTimes(2)
    expect(hooks.values[2]).toBe('控制站没有桌面会话')
    expect(hooks.values[3]).toBe(false)
    expect(vi.mocked(requestSimulation).mock.calls.every(([path]) => path === 'rviz')).toBe(true)
    dispose?.()
  })

  it('aborts the bounded launch request and reconciles the running process', async () => {
    vi.mocked(requestSimulation).mockResolvedValueOnce(stopped).mockImplementationOnce((_path, _body, signal) =>
      new Promise((_resolve, reject) => signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))))
      .mockResolvedValueOnce(running)
    const { rviz, dispose } = await mount()
    const launch = rviz.open()
    await vi.advanceTimersByTimeAsync(5000)
    await launch
    expect(vi.mocked(requestSimulation).mock.calls[1][2]?.aborted).toBe(true)
    expect(requestSimulation).toHaveBeenCalledTimes(3)
    expect(hooks.values[2]).toContain(`ROS 域 ${SIMULATION_DOMAIN}`)
    dispose?.()
  })

  it('aborts requests on unmount without accepting late replies', async () => {
    const late = deferred<typeof stopped>()
    vi.mocked(requestSimulation).mockImplementationOnce(() => late.promise)
    const { dispose } = await mount()
    dispose?.()
    expect(vi.mocked(requestSimulation).mock.calls[0][2]?.aborted).toBe(true)
    late.resolve(stopped)
    await vi.advanceTimersByTimeAsync(0)
    expect(hooks.values[0]).toBe(null)
  })

  it.each([0, 233, 0.5, SIMULATION_DOMAIN + 1])('rejects ROS domain %s and only reads status until the current domain is confirmed', async (domain) => {
    vi.mocked(requestSimulation).mockResolvedValueOnce({ ...running, domain }).mockResolvedValueOnce(stopped).mockResolvedValueOnce(running)
    const { rviz, dispose } = await mount()
    expect(hooks.values[0]).toBe(null)
    expect(hooks.values[3]).toBe(true)
    expect(hooks.values[2]).toContain('RViz 未连接当前 MuJoCo 仿真')
    await rviz.open()
    expect(vi.mocked(requestSimulation).mock.calls.map(([, body]) => body)).toEqual([undefined, undefined])
    expect(hooks.values[3]).toBe(false)
    await rviz.open()
    expect(vi.mocked(requestSimulation).mock.calls.map(([, body]) => body)).toEqual([undefined, undefined, {}])
    dispose?.()
  })

  it('reconciles a 504 unknown launch receipt using GET alone', async () => {
    vi.mocked(requestSimulation).mockResolvedValueOnce(stopped)
      .mockRejectedValueOnce(new SimulationRejectedRequest('RViz 启动回执未知', 504)).mockResolvedValueOnce(running)
    const { rviz, dispose } = await mount()
    await rviz.open()
    expect(vi.mocked(requestSimulation).mock.calls.map(([, body]) => body)).toEqual([undefined, {}, undefined])
    expect(hooks.values[0]).toEqual(running)
    expect(hooks.values[3]).toBe(false)
    dispose?.()
  })

  it('allows a new explicit open after the native window is closed without automatic launch retries', async () => {
    vi.mocked(requestSimulation).mockResolvedValueOnce(stopped).mockResolvedValueOnce(running).mockResolvedValueOnce(running)
    const { rviz, dispose } = await mount()
    await rviz.open()
    await vi.advanceTimersByTimeAsync(6000)
    expect(requestSimulation).toHaveBeenCalledTimes(2)
    // The second user click asks the server to recheck its actual PID and reopen a closed window.
    await rviz.open()
    expect(vi.mocked(requestSimulation).mock.calls.map(([, body]) => body)).toEqual([undefined, {}, {}])
    expect(hooks.values[0]).toEqual(running)
    dispose?.()
  })
})
