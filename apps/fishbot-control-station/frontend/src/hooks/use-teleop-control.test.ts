import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const fixture = vi.hoisted(() => ({ cleanup: null as null | (() => void), direction: null as string | null }))
const api = vi.hoisted(() => ({ postCommand: vi.fn(), postStop: vi.fn() }))
vi.mock('@/lib/api', () => api)
vi.mock('react', () => ({
  useRef: (value: unknown) => ({ current: value }),
  useEffectEvent: (callback: unknown) => callback,
  useEffect: (effect: () => (() => void)) => { fixture.cleanup = effect() },
}))
vi.mock('@/store/station-store', () => {
  const useStationStore = Object.assign(() => ({
    activeDirection: fixture.direction, angularSpeed: 1, linearSpeed: 0.32,
    appendCommand: vi.fn(), appendError: vi.fn(), patchControlFeedback: vi.fn(),
    setActiveDirection: (direction: string | null) => { fixture.direction = direction },
  }), { getState: () => ({ activeDirection: fixture.direction }) })
  return { useStationStore }
})

import { useTeleopControl } from '@/hooks/use-teleop-control'

function deferred() {
  let resolve!: () => void
  const promise = new Promise<void>((done) => { resolve = done })
  return { promise, resolve }
}

beforeEach(() => {
  fixture.cleanup = null; fixture.direction = null
  vi.useFakeTimers(); vi.spyOn(performance, 'now').mockImplementation(() => Date.now())
  vi.stubGlobal('window', { setInterval, clearInterval, addEventListener: vi.fn(), removeEventListener: vi.fn() })
  vi.stubGlobal('document', { addEventListener: vi.fn(), removeEventListener: vi.fn(), visibilityState: 'visible' })
  api.postCommand.mockReset(); api.postStop.mockReset().mockResolvedValue(undefined)
})
afterEach(() => { fixture.cleanup?.(); vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('teleop pending acknowledgement cancellation', () => {
  it('does not restart held commands when an acknowledgement arrives after release', async () => {
    const ack = deferred(); api.postCommand.mockReturnValueOnce(ack.promise)
    const control = useTeleopControl(); const begin = control.begin('forward')
    await control.stop(); ack.resolve(); await begin
    await vi.advanceTimersByTimeAsync(500)
    expect(api.postCommand).toHaveBeenCalledTimes(1)
    expect(api.postStop).toHaveBeenCalledWith('/api/v1/control/stop')
    expect(fixture.direction).toBeNull(); expect(vi.getTimerCount()).toBe(0)
  })
  it('does not resurrect a previous direction after a replacement hold starts', async () => {
    const first = deferred(); api.postCommand.mockReturnValueOnce(first.promise).mockResolvedValue(undefined)
    const control = useTeleopControl(); const oldHold = control.begin('forward')
    await control.begin('left'); first.resolve(); await oldHold
    await vi.advanceTimersByTimeAsync(280)
    expect(vi.getTimerCount()).toBe(1)
    const repeated = api.postCommand.mock.calls.slice(1).map(([value]) => value)
    expect(repeated.length).toBeGreaterThan(1)
    expect(repeated.every((value) => value.linearX === 0 && value.angularZ === 1)).toBe(true)
    expect(fixture.direction).toBe('left')
  })
  it('stops a held command on page exit and ignores its late acknowledgement', async () => {
    const ack = deferred(); api.postCommand.mockReturnValueOnce(ack.promise)
    const control = useTeleopControl(); const begin = control.begin('right')
    fixture.cleanup?.(); ack.resolve(); await begin
    await vi.advanceTimersByTimeAsync(500)
    expect(api.postCommand).toHaveBeenCalledTimes(1)
    expect(api.postStop).toHaveBeenCalledWith('/api/v1/control/stop')
    expect(fixture.direction).toBeNull(); expect(vi.getTimerCount()).toBe(0)
  })
  it('does not restart a hold after software stop locks the console', async () => {
    const ack = deferred(); api.postCommand.mockReturnValueOnce(ack.promise)
    const control = useTeleopControl(); const begin = control.begin('forward')
    await control.emergencyStop(); ack.resolve(); await begin
    await vi.advanceTimersByTimeAsync(500)
    expect(api.postCommand).toHaveBeenCalledTimes(1)
    expect(api.postStop).toHaveBeenCalledWith('/api/v1/control/emergency-stop')
    expect(vi.getTimerCount()).toBe(0)
  })
})
