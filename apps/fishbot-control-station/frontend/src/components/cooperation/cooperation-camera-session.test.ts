import { describe, expect, it, vi } from 'vitest'
import { CooperationFrameBuffer } from '@/lib/cooperation-frame'
import { cooperationFrameSourceKey, type CooperationState } from '@/lib/cooperation'
import { CooperationCameraSession, type CameraCallbacks } from './cooperation-camera-session'

const state: CooperationState = {
  mode: 'mujoco', domain: 114, ready: true, reason: 'ready', episode_id: 'episode-a',
  task: { id: 'original-task', status: 'running', stage: 'car_to_dock', message: '正在停靠' },
  events: [], physics: null, nav: null, stations: null, source: { scene_sha: 'scene-a' },
  frame: { available: true, stamp: 10 },
  vision_frame: { available: true, stamp: 10, episode_id: 'episode-a', sequence: 50,
    corners: null, image_width: 640, image_height: 480 },
}
const callbacks = (): CameraCallbacks => ({ scene: { display: vi.fn(), observe: vi.fn() }, rear: { display: vi.fn(), observe: vi.fn() } })
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done }); return { resolve, promise } }

describe('cooperation canvas visibility lifecycle', () => {
  it('does no image work while hidden, resumes at the latest episode and releases the one active buffer', () => {
    const buffers: Array<{ request: ReturnType<typeof vi.fn>; dispose: ReturnType<typeof vi.fn> }> = []
    const create = vi.fn(() => { const buffer = { request: vi.fn(), dispose: vi.fn() }; buffers.push(buffer); return buffer })
    const session = new CooperationCameraSession(callbacks(), create)
    session.update(state, false, true)
    expect(create).not.toHaveBeenCalled()
    session.update(state, true, false)
    expect(create).toHaveBeenCalledTimes(1)
    expect(buffers[0].request).toHaveBeenCalledWith(cooperationFrameSourceKey(state), 10, 'episode-a')
    session.update(state, false, false)
    expect(buffers[0].dispose).toHaveBeenCalledTimes(1)
    const newer = { ...state, episode_id: 'episode-b', frame: { available: true, stamp: 1 } }
    session.update(newer, false, false)
    expect(create).toHaveBeenCalledTimes(1)
    session.update(newer, true, false)
    expect(create).toHaveBeenCalledTimes(2)
    expect(buffers[1].request).toHaveBeenCalledWith(cooperationFrameSourceKey(newer), 1, 'episode-b')
    session.dispose()
    expect(buffers[1].dispose).toHaveBeenCalledTimes(1)
    session.update(state, true, true)
    expect(create).toHaveBeenCalledTimes(2)
  })

  it('switches to actual rear RGB with exact frame identity, without decoding a hidden scene camera', () => {
    const buffers: Array<{ options: ConstructorParameters<typeof CooperationFrameBuffer>[0]; request: ReturnType<typeof vi.fn>; dispose: ReturnType<typeof vi.fn> }> = []
    const session = new CooperationCameraSession(callbacks(), (options) => {
      const buffer = { options, request: vi.fn(), dispose: vi.fn() }; buffers.push(buffer); return buffer
    })
    session.update(state, true, false)
    session.update(state, true, true)
    expect(buffers[0].dispose).toHaveBeenCalledTimes(1)
    expect(buffers[1].options.endpoint).toBe('vision-frame.jpg')
    expect(buffers[1].request).toHaveBeenCalledWith(cooperationFrameSourceKey(state), 10, 'episode-a', state.vision_frame)
    session.update({ ...state, vision_frame: { ...state.vision_frame!, sequence: 51, stamp: 11 } }, true, true)
    expect(buffers).toHaveLength(2)
    expect(buffers[1].request).toHaveBeenLastCalledWith(cooperationFrameSourceKey(state), 11, 'episode-a', expect.objectContaining({ sequence: 51 }))
    session.update(state, false, true)
    expect(buffers[1].dispose).toHaveBeenCalledTimes(1)
  })

  it('aborts a real pending image on hide and cannot display its late reply after another episode resumes', async () => {
    const first = deferred<Response>(), second = deferred<Response>(), signals: AbortSignal[] = []
    const fetcher = vi.fn((_path: RequestInfo | URL, options?: RequestInit) => {
      signals.push(options!.signal as AbortSignal)
      return signals.length === 1 ? first.promise : second.promise
    })
    const observe = callbacks(), createUrl = vi.fn(() => 'blob:current-episode'), revokeUrl = vi.fn()
    const session = new CooperationCameraSession(observe, (options) => new CooperationFrameBuffer({
      ...options, fetcher, decode: async () => {}, createUrl, revokeUrl, now: () => 10000,
    }))
    try {
      session.update(state, true, false)
      expect(fetcher).toHaveBeenCalledTimes(1)
      session.update(state, false, false)
      expect(signals[0].aborted).toBe(true)
      const newer = { ...state, episode_id: 'episode-b', frame: { available: true, stamp: 1 } }
      session.update(newer, true, false)
      second.resolve(new Response(new Uint8Array([1])))
      await vi.waitFor(() => expect(observe.scene.display).toHaveBeenLastCalledWith('blob:current-episode'))
      first.resolve(new Response(new Uint8Array([2])))
      await new Promise((done) => setTimeout(done, 0))
      expect(createUrl).toHaveBeenCalledTimes(1)
      expect(observe.scene.observe).toHaveBeenLastCalledWith(expect.objectContaining({ scene: cooperationFrameSourceKey(newer), loadedStamp: 1 }))
      expect(fetcher.mock.calls[1][0]).toContain('episode_id=episode-b')
    } finally { session.dispose() }
    expect(revokeUrl).toHaveBeenCalledWith('blob:current-episode')
  })
})
