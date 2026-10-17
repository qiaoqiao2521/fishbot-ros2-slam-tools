import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
const lifecycle = vi.hoisted(() => ({ cleanup: null as (() => void) | null }))
vi.mock('react', async (original) => ({ ...await original<typeof import('react')>(), useEffect: (effect: () => (() => void)) => { lifecycle.cleanup = effect() } }))
vi.mock('@/store/station-store', async (original) => {
  const module = await original<typeof import('@/store/station-store')>()
  return { ...module, useStationStore: Object.assign(() => module.useStationStore.getState(), module.useStationStore) }
})
import { useStationBootstrap } from './use-station-bootstrap'
import { useStationStore } from '@/store/station-store'
import { runtimeRegistry } from '@/lib/runtime-context'
import { mockNavigation, mockPerception } from '@/lib/mock-station'

const connection = { rosbridgeConnected: true, robotOnline: false, rosbridgeUrl: 'ws://127.0.0.1:9090', lastMessage: '2026-10-18T00:00:00Z', statusMessage: 'connected' }
const state = { x: 1, y: 2, yaw: 0, linearVelocity: 0, angularVelocity: 0, accelX: 0, accelY: 0, accelZ: 9.8, angularVelX: 0, angularVelY: 0, angularVelZ: 0, timestamp: '2026-10-18T00:00:00Z' }
class Stream {
  static instance: Stream
  listeners = new Map<string, (event: unknown) => void>()
  onerror: (() => void) | null = null
  closed = false
  constructor() { Stream.instance = this }
  addEventListener(name: string, listener: (event: unknown) => void) { this.listeners.set(name, listener) }
  emit(name: string, value: unknown, lastEventId = '') { this.listeners.get(name)?.({ data: JSON.stringify(value), lastEventId }) }
  close() { this.closed = true }
}
const json = (value: unknown) => new Response(JSON.stringify(value))
function fetcher(input: RequestInfo | URL) {
  return Promise.resolve(json({ '/api/v1/connection': connection, '/api/v1/state': state,
    '/api/v1/navigation': mockNavigation, '/api/v1/perception': mockPerception,
    '/api/v1/diagnostics': { generatedAt: state.timestamp, entries: [] },
  }[String(input)]))
}
beforeEach(() => { useStationStore.setState(useStationStore.getInitialState(), true); vi.stubGlobal('EventSource', Stream); vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
  const response = await fetcher(input)
  const instance = runtimeRegistry.getSnapshot().station.descriptor?.instance_id
  if (instance) response.headers.set('X-Fishbot-Instance', instance)
  return response
})) })
afterEach(() => { lifecycle.cleanup?.(); lifecycle.cleanup = null; vi.unstubAllGlobals() })

describe('station readback isolation', () => {
  it('hydrates each validated resource and releases its sole stream on unmount', async () => {
    useStationBootstrap()
    await vi.waitFor(() => expect(useStationStore.getState().usingFallbackData).toBe(false))
    expect(useStationStore.getState().robotState.odom.x).toBe(1)
    lifecycle.cleanup?.(); expect(Stream.instance.closed).toBe(true)
  })
  it('does not replace newer SSE data with a delayed initial HTTP snapshot', async () => {
    let release!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => String(input) === '/api/v1/state' ? new Promise<Response>((done) => { release = done }) : fetcher(input)))
    useStationBootstrap()
    Stream.instance.emit('robot-state', { ...state, x: 9 })
    release(json(state))
    await vi.waitFor(() => expect(useStationStore.getState().resourceProvenance.navigation.status).toBe('received'))
    expect(useStationStore.getState().robotState.odom.x).toBe(9)
  })
  it('contains malformed JSON, preserves other resources and recovers on a valid event', async () => {
    useStationBootstrap()
    await vi.waitFor(() => expect(useStationStore.getState().usingFallbackData).toBe(false))
    expect(() => Stream.instance.listeners.get('robot-state')?.({ data: '{broken', lastEventId: '' })).not.toThrow()
    expect(useStationStore.getState().resourceProvenance.robotState.status).toBe('invalid')
    expect(useStationStore.getState().resourceProvenance.navigation.status).toBe('received')
    Stream.instance.emit('robot-state', { ...state, x: 8 })
    expect(useStationStore.getState().robotState.odom.x).toBe(8)
    expect(useStationStore.getState().resourceProvenance.robotState.status).toBe('received')
  })
  it('marks disconnection as old data, not a return to manufactured examples', async () => {
    useStationBootstrap()
    await vi.waitFor(() => expect(useStationStore.getState().usingFallbackData).toBe(false))
    Stream.instance.onerror?.()
    expect(useStationStore.getState().robotState.odom.x).toBe(1)
    expect(useStationStore.getState().resourceProvenance.robotState.status).toBe('stale')
  })
  it('rejects malformed diagnostic HTTP snapshots before mapping', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => String(input) === '/api/v1/diagnostics'
      ? Promise.resolve(json({ generatedAt: state.timestamp, entries: [{ message: 'missing fields' }] })) : fetcher(input)))
    useStationBootstrap()
    await vi.waitFor(() => expect(useStationStore.getState().resourceProvenance.diagnostics.error).toContain('数据无效'))
    expect(useStationStore.getState().resourceProvenance.diagnostics.receivedAt).toBeNull()
  })
  it('rereads all resources when discovery finishes after the first snapshots', async () => {
    useStationBootstrap()
    await vi.waitFor(() => expect(useStationStore.getState().usingFallbackData).toBe(false))
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const response = await fetcher(input)
      return new Response(await response.text(), { headers: { 'X-Fishbot-Instance': 'discovered-instance' } })
    }))
    await runtimeRegistry.refresh('station', async () => new Response(JSON.stringify({ schema_version: 1, service: 'station', instance_id: 'discovered-instance', mode: 'live', domain: null, scene_id: null, episode_id: null, capabilities: [] }), { headers: { 'X-Fishbot-Instance': 'discovered-instance' } }))
    await vi.waitFor(() => expect(Object.values(useStationStore.getState().resourceProvenance).every((resource) => resource.status === 'received')).toBe(true))
  })
  it('ignores previous process telemetry and descending event ids after identity is known', async () => {
    useStationBootstrap()
    await vi.waitFor(() => expect(useStationStore.getState().usingFallbackData).toBe(false))
    await runtimeRegistry.refresh('station', async () => new Response(JSON.stringify({ schema_version: 1, service: 'station', instance_id: 'new-instance', mode: 'live', domain: null, scene_id: null, episode_id: null, capabilities: [] }), { headers: { 'X-Fishbot-Instance': 'new-instance' } }))
    Stream.instance.emit('robot-state', { ...state, x: 7 }, 'old-instance:100')
    expect(useStationStore.getState().robotState.odom.x).toBe(1)
    Stream.instance.emit('robot-state', { ...state, x: 8 }, 'new-instance:3')
    Stream.instance.emit('robot-state', { ...state, x: 2 }, 'new-instance:2')
    expect(useStationStore.getState().robotState.odom.x).toBe(8)
    Stream.instance.listeners.get('robot-state')?.({ data: '{broken', lastEventId: 'new-instance:900000' })
    Stream.instance.emit('robot-state', { ...state, x: 10 }, 'new-instance:4')
    expect(useStationStore.getState().robotState.odom.x).toBe(10)
    expect(useStationStore.getState().resourceProvenance.robotState.status).toBe('received')
  })
})
