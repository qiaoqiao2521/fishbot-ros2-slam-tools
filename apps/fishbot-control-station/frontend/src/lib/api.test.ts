import { afterEach, describe, expect, it, vi } from 'vitest'

import { MapPublicationUnconfirmedError, mapNavigationSnapshot, postInitialPose, postNavigationGoal } from '@/lib/api'
import { mockNavigation } from '@/lib/mock-station'

afterEach(() => vi.unstubAllGlobals())

describe('map API contract', () => {
  it('keeps a missing path unknown for an older backend', () => {
    const raw = { ...mockNavigation }
    delete raw.path
    expect(mapNavigationSnapshot(raw).path).toMatchObject({ ready: false, points: [], statusMessage: expect.stringContaining('未知') })
  })

  it('replaces a previous path with the backend empty path', () => {
    const path = { ready: true, frameId: 'map', poseCount: 2, points: [{ x: 1, y: 2 }, { x: 3, y: 4 }], lastUpdate: '2026-10-13T00:00:00Z', statusMessage: 'planned' }
    expect(mapNavigationSnapshot({ ...mockNavigation, path }).path?.points).toHaveLength(2)
    expect(mapNavigationSnapshot({ ...mockNavigation, path: { ...path, ready: false, poseCount: 0, points: [] } }).path?.points).toEqual([])
  })

  it('publishes yaw and source to distinct goal and initial-pose endpoints once each', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)
    await postNavigationGoal({ x: 1, y: 2, yaw: Math.PI / 2, source: 'radar-workbench' })
    await postInitialPose({ x: 3, y: 4, yaw: -Math.PI / 2, source: 'radar-workbench' })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual(['/api/v1/control/goal', '/api/v1/control/initial-pose'])
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ x: 1, y: 2, yaw: Math.PI / 2, source: 'radar-workbench' })
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ x: 3, y: 4, yaw: -Math.PI / 2, source: 'radar-workbench' })
  })

  it('reports initial-pose refusal and never retries a failed publication', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 409, json: async () => ({ error: 'control bridge disconnected' }) })
    vi.stubGlobal('fetch', fetchMock)
    await expect(postInitialPose({ x: 1, y: 2, yaw: 0 })).rejects.toThrow('control bridge disconnected')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it.each([postInitialPose, postNavigationGoal])('marks a missing HTTP response unknown without repeating the request', async (publish) => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('network connection lost'))
    vi.stubGlobal('fetch', fetchMock)
    await expect(publish({ x: 1, y: 2, yaw: 0 })).rejects.toBeInstanceOf(MapPublicationUnconfirmedError)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it.each([400, 409])('keeps an explicit HTTP %i refusal distinct from unknown publication', async (status) => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status, json: async () => ({ error: 'publication refused' }) })
    vi.stubGlobal('fetch', fetchMock)
    const publication = postNavigationGoal({ x: 1, y: 2 })
    await expect(publication).rejects.toMatchObject({ message: 'publication refused' })
    await expect(publication).rejects.not.toBeInstanceOf(MapPublicationUnconfirmedError)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('keeps an unexpected server failure unknown rather than inviting a duplicate publication', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({ error: 'unexpected server error' }) }))
    await expect(postInitialPose({ x: 1, y: 2, yaw: 0 })).rejects.toBeInstanceOf(MapPublicationUnconfirmedError)
  })

  it.each([postInitialPose, postNavigationGoal])('keeps a rosbridge 503 unknown because the socket send may have started', async (publish) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({ error: 'rosbridge_unavailable' }) }))
    await expect(publish({ x: 1, y: 2, yaw: 0 })).rejects.toMatchObject({ possiblySubmitted: true })
  })

  it('keeps a 503 without readable error details unknown', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => { throw new SyntaxError('not JSON') } }))
    await expect(postNavigationGoal({ x: 1, y: 2 })).rejects.toBeInstanceOf(MapPublicationUnconfirmedError)
  })

  it('permits a new explicit attempt after the verified clock preflight refusal', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({ error: 'clock_unavailable' }) }))
    const publication = postInitialPose({ x: 1, y: 2, yaw: 0 })
    await expect(publication).rejects.toThrow('clock_unavailable')
    await expect(publication).rejects.not.toBeInstanceOf(MapPublicationUnconfirmedError)
  })
})
