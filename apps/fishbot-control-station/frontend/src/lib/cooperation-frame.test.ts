import { describe, expect, it, vi } from 'vitest'
import { CooperationFrameBuffer } from './cooperation-frame'
import type { CooperationFrameObservation, CooperationVisionFrame } from './cooperation'
import { COOPERATION_STALE_MS } from './cooperation'

function fixture(endpoint?: 'vision-frame.jpg') {
  const requests: Array<{ url: string; signal: AbortSignal; resolve: (response: Response) => void; reject: (reason: Error) => void }> = []
  const decodes: Array<{ url: string; resolve: () => void; reject: (reason: Error) => void }> = []
  const displays: Array<string | null> = [], observations: Array<CooperationFrameObservation | null> = [], revoked: string[] = []
  let clock = 10000, serial = 0
  const buffer = new CooperationFrameBuffer({
    endpoint,
    display: (url) => displays.push(url), observe: (frame) => observations.push(frame),
    fetcher: (input, init) => new Promise<Response>((resolve, reject) => requests.push({ url: String(input), signal: init!.signal!, resolve, reject })),
    decode: (url) => new Promise<void>((resolve, reject) => decodes.push({ url, resolve, reject })),
    createUrl: () => `blob:frame-${++serial}`, revokeUrl: (url) => revoked.push(url), now: () => clock,
  })
  async function decoded(index: number) {
    requests[index].resolve(new Response(new Blob(['jpeg']), { status: 200 }))
    await vi.waitFor(() => expect(decodes).toHaveLength(index + 1))
    decodes[index].resolve()
    await vi.waitFor(() => expect(displays).toContain(decodes[index].url))
  }
  return { buffer, requests, decodes, displays, observations, revoked, decoded, advance: (milliseconds: number) => { clock += milliseconds } }
}

describe('decoded cooperation camera buffer', () => {
  it('binds decoded rear images to captured sequence and corners, retaining both after HTTP 409', async () => {
    const f = fixture('vision-frame.jpg')
    const metadata: CooperationVisionFrame = { available: true, stamp: 10, episode_id: 'episode-a', sequence: 7,
      corners: [[10, 20], [50, 20], [50, 60], [10, 60]], image_width: 640, image_height: 480 }
    f.buffer.request('scene-a', 10, 'episode-a', metadata)
    metadata.corners![0][0] = 999
    expect(f.requests[0].url).toBe('/coop-api/vision-frame.jpg?stamp=10&episode_id=episode-a&sequence=7')
    await f.decoded(0)
    expect(f.observations.at(-1)?.vision?.corners?.[0]).toEqual([10, 20])
    const next = { ...metadata, stamp: 11, sequence: 8, corners: null }
    f.buffer.request('scene-a', 11, 'episode-a', next)
    expect(f.observations.at(-1)?.vision?.sequence).toBe(7)
    f.requests[1].resolve(new Response('new frame conflict', { status: 409 }))
    await vi.waitFor(() => expect(f.observations.at(-1)?.error).toBe(true))
    expect(f.displays.at(-1)).toBe('blob:frame-1')
    expect(f.observations.at(-1)?.vision?.sequence).toBe(7)
    expect(f.observations.at(-1)?.vision?.corners?.[0]).toEqual([10, 20])
    f.buffer.dispose()
  })

  it('fetches a new sequence even when its source stamp is unchanged', async () => {
    const f = fixture('vision-frame.jpg')
    const metadata: CooperationVisionFrame = { available: true, stamp: 10, episode_id: 'episode-a', sequence: 7,
      corners: null, image_width: 640, image_height: 480 }
    f.buffer.request('scene-a', 10, 'episode-a', metadata); await f.decoded(0)
    f.buffer.request('scene-a', 10, 'episode-a', { ...metadata, sequence: 8 })
    expect(f.requests[1].url).toContain('sequence=8')
    expect(f.displays.at(-1)).toBe('blob:frame-1')
    await f.decoded(1)
    expect(f.observations.at(-1)?.vision?.sequence).toBe(8)
    f.buffer.dispose()
  })

  it('retains the last decoded rear frame when unavailable metadata supplies a zero placeholder sequence', async () => {
    const f = fixture('vision-frame.jpg')
    const metadata: CooperationVisionFrame = { available: true, stamp: 10, episode_id: 'episode-a', sequence: 7,
      corners: null, image_width: 640, image_height: 480 }
    f.buffer.request('scene-a', 10, 'episode-a', metadata); await f.decoded(0)
    const count = f.displays.length
    f.buffer.request('scene-a', null, 'episode-a', { ...metadata, available: false, stamp: null, sequence: 0 })
    expect(f.displays).toHaveLength(count); expect(f.displays.at(-1)).toBe('blob:frame-1')
    expect(f.observations.at(-1)?.vision?.sequence).toBe(7); expect(f.revoked).toEqual([])
    f.buffer.dispose()
  })

  it('rejects late rear decode and corners from the previous episode', async () => {
    const f = fixture('vision-frame.jpg')
    const metadata: CooperationVisionFrame = { available: true, stamp: 10, episode_id: 'episode-a', sequence: 7,
      corners: [[10, 20], [50, 20], [50, 60], [10, 60]], image_width: 640, image_height: 480 }
    f.buffer.request('same-scene', 10, 'episode-a', metadata)
    f.requests[0].resolve(new Response(new Blob(['old rear jpeg'])))
    await vi.waitFor(() => expect(f.decodes).toHaveLength(1))
    f.buffer.request('same-scene', 10, 'episode-b', { ...metadata, episode_id: 'episode-b', sequence: 1, corners: null })
    expect(f.requests[0].signal.aborted).toBe(true)
    await f.decoded(1)
    const observations = f.observations.length
    f.decodes[0].resolve(); await Promise.resolve(); await Promise.resolve()
    expect(f.observations).toHaveLength(observations)
    expect(f.observations.at(-1)?.vision?.episode_id).toBe('episode-b')
    expect(f.observations.at(-1)?.vision?.corners).toBeNull()
    f.buffer.dispose()
  })

  it('keeps the last displayed frame until the successor decodes, without resetting freshness', async () => {
    const f = fixture(); f.buffer.request('scene-a', 10); await f.decoded(0)
    const displayCount = f.displays.length, observationCount = f.observations.length
    f.advance(1000); f.buffer.request('scene-a', 11)
    expect(f.displays).toHaveLength(displayCount); expect(f.observations).toHaveLength(observationCount)
    f.requests[1].resolve(new Response(new Blob(['next jpeg'])))
    await vi.waitFor(() => expect(f.decodes).toHaveLength(2))
    expect(f.displays.at(-1)).toBe('blob:frame-1'); expect(f.revoked).toEqual([])
    f.advance(200); f.decodes[1].resolve()
    await vi.waitFor(() => expect(f.displays.at(-1)).toBe('blob:frame-2'))
    expect(f.observations.at(-1)).toEqual({ scene: 'scene-a', stamp: 11, changedAt: 11000, loadedStamp: 11, error: false })
    expect(f.revoked).toEqual(['blob:frame-1']); f.buffer.dispose()
    expect(f.revoked).toEqual(['blob:frame-1', 'blob:frame-2'])
  })

  it('queues only the latest target behind a slow in-flight image', async () => {
    const f = fixture(); f.buffer.request('scene-a', 10)
    f.buffer.request('scene-a', 11); f.buffer.request('scene-a', 12)
    expect(f.requests).toHaveLength(1)
    await f.decoded(0)
    await vi.waitFor(() => expect(f.requests).toHaveLength(2))
    expect(f.requests[1].url).toBe('/coop-api/frame.jpg?stamp=12')
    await f.decoded(1); expect(f.observations.at(-1)?.loadedStamp).toBe(12); f.buffer.dispose()
  })

  it('retains the displayed image and its age after a failed download or decode', async () => {
    const f = fixture(); f.buffer.request('scene-a', 10); await f.decoded(0)
    f.advance(1000); f.buffer.request('scene-a', 11); f.requests[1].reject(new Error('connection lost'))
    await vi.waitFor(() => expect(f.observations.at(-1)?.error).toBe(true))
    expect(f.displays.at(-1)).toBe('blob:frame-1')
    expect(f.observations.at(-1)).toEqual({ scene: 'scene-a', stamp: 11, changedAt: 10000, loadedStamp: 10, error: true })
    f.buffer.request('scene-a', 12); f.requests[2].resolve(new Response(new Blob(['bad jpeg'])))
    await vi.waitFor(() => expect(f.decodes).toHaveLength(2)); f.decodes[1].reject(new Error('bad jpeg'))
    await vi.waitFor(() => expect(f.revoked).toContain('blob:frame-2'))
    expect(f.displays.at(-1)).toBe('blob:frame-1'); f.buffer.dispose()
  })

  it('clears a changed source and rejects a late decoded frame from the prior source', async () => {
    const f = fixture(); f.buffer.request('scene-a', 10)
    f.requests[0].resolve(new Response(new Blob(['old jpeg'])))
    await vi.waitFor(() => expect(f.decodes).toHaveLength(1))
    f.buffer.request('scene-b', 11); expect(f.requests[0].signal.aborted).toBe(true)
    expect(f.displays.at(-1)).toBe(null); await f.decoded(1)
    const count = f.displays.length; f.decodes[0].resolve(); await Promise.resolve(); await Promise.resolve()
    expect(f.displays).toHaveLength(count); expect(f.displays.at(-1)).toBe('blob:frame-2')
    expect(f.revoked.filter((url) => url === 'blob:frame-1')).toHaveLength(1); f.buffer.dispose()
  })

  it('invalidates the old episode on clock regression and disposes every blob without replay', async () => {
    const f = fixture(); f.buffer.request('scene-a', 10); await f.decoded(0)
    f.buffer.request('scene-a', 1); expect(f.displays.at(-1)).toBe(null)
    expect(f.revoked).toEqual(['blob:frame-1']); f.buffer.dispose()
    const count = f.observations.length
    f.requests[1].resolve(new Response(new Blob(['late jpeg']))); await Promise.resolve(); await Promise.resolve()
    f.buffer.request('scene-a', 2)
    expect(f.requests).toHaveLength(2); expect(f.observations).toHaveLength(count)
    expect(f.requests[1].signal.aborted).toBe(true)
  })

  it.each(['fetch', 'decode'] as const)('recovers after a hung %s without accepting its late completion', async (phase) => {
    vi.useFakeTimers()
    const f = fixture()
    try {
      f.buffer.request('scene-a', 10); await f.decoded(0)
      f.advance(1000); f.buffer.request('scene-a', 11)
      if (phase === 'decode') {
        f.requests[1].resolve(new Response(new Blob(['hung decode jpeg'])))
        await vi.waitFor(() => expect(f.decodes).toHaveLength(2))
      }
      f.buffer.request('scene-a', 12)
      await vi.advanceTimersByTimeAsync(COOPERATION_STALE_MS)
      expect(f.requests).toHaveLength(3); expect(f.requests[1].signal.aborted).toBe(true)
      expect(f.displays.at(-1)).toBe('blob:frame-1')
      expect(f.observations.at(-1)).toEqual({ scene: 'scene-a', stamp: 11, changedAt: 10000, loadedStamp: 10, error: true })
      f.requests[2].resolve(new Response(new Blob(['recovered jpeg'])))
      await vi.waitFor(() => expect(f.decodes).toHaveLength(phase === 'fetch' ? 2 : 3))
      f.decodes.at(-1)!.resolve()
      await vi.waitFor(() => expect(f.observations.at(-1)?.loadedStamp).toBe(12))
      const displayed = f.displays.at(-1), count = f.displays.length
      if (phase === 'fetch') f.requests[1].resolve(new Response(new Blob(['late old jpeg'])))
      else f.decodes[1].resolve()
      await vi.advanceTimersByTimeAsync(0)
      expect(f.displays).toHaveLength(count); expect(f.displays.at(-1)).toBe(displayed)
      f.buffer.dispose()
      expect(new Set(f.revoked).size).toBe(phase === 'fetch' ? 2 : 3)
      expect(vi.getTimerCount()).toBe(0)
    } finally { f.buffer.dispose(); vi.useRealTimers() }
  })
})
