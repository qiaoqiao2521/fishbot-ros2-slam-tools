import { afterEach, describe, expect, it, vi } from 'vitest'
import { scheduleSceneSetup } from './scene-setup'

afterEach(() => vi.useRealTimers())
describe('scene setup scheduling', () => {
  it('does not perform heavy setup before the feedback frame and following task', () => {
    vi.useFakeTimers(); const start = vi.fn(); let frame: FrameRequestCallback | null = null
    scheduleSceneSetup(start, { frame: callback => { frame = callback; return 1 }, cancelFrame: vi.fn(),
      delay: callback => setTimeout(callback, 0), cancelDelay: clearTimeout })
    expect(start).not.toHaveBeenCalled(); (frame as unknown as FrameRequestCallback)(0)
    expect(start).not.toHaveBeenCalled(); vi.runAllTimers(); expect(start).toHaveBeenCalledOnce()
  })
  it('releases a hidden or replaced view before its setup task runs', () => {
    vi.useFakeTimers(); const start = vi.fn(); let frame: FrameRequestCallback | null = null
    const cancel = scheduleSceneSetup(start, { frame: callback => { frame = callback; return 1 }, cancelFrame: vi.fn(),
      delay: callback => setTimeout(callback, 0), cancelDelay: clearTimeout })
    ;(frame as unknown as FrameRequestCallback)(0); cancel(); vi.runAllTimers(); expect(start).not.toHaveBeenCalled()
  })
})
