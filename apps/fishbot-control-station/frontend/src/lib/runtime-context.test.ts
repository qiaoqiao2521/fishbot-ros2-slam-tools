import { afterEach, describe, expect, it, vi } from 'vitest'
import { RuntimeChangedError, RuntimeRegistry, runtimeContextLabel, validateRuntimeDescriptor, type RuntimeDescriptor } from './runtime-context'

const descriptor = (patch: Partial<RuntimeDescriptor> = {}): RuntimeDescriptor => ({
  schema_version: 1, service: 'mission', instance_id: 'process-a', mode: 'simulation',
  domain: 127, scene_id: null, episode_id: null,
  capabilities: [{ id: 'navigation', submission: 'native_action', task_lookup: false, cancel: true, event_history: 'snapshot' }], ...patch,
})
const response = (value: unknown, instance = 'process-a', status = 200) => new Response(JSON.stringify(value), { status, headers: { 'X-Fishbot-Instance': instance } })
const defer = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done }); return { resolve, promise } }
afterEach(() => { vi.useRealTimers() })

describe('service runtime contract', () => {
  it('preserves unknown remote domains and rejects another service, malformed identity and invented capabilities', () => {
    expect(validateRuntimeDescriptor(descriptor({ domain: null }), 'mission').domain).toBeNull()
    for (const bad of [{ service: 'cooperation' }, { domain: 233 }, { domain: NaN }, { schema_version: 2 }, { instance_id: '' }, { capabilities: [{ id: 'navigation', submission: 'success' }] }]) {
      expect(() => validateRuntimeDescriptor({ ...descriptor(), ...bad }, 'mission')).toThrow()
    }
  })
  it('keeps legacy and unreachable sources explicitly unknown without fabricating a domain', async () => {
    const registry = new RuntimeRegistry()
    await registry.refresh('station', async () => new Response('', { status: 404 }))
    await registry.refresh('mission', async () => { throw new Error('offline') })
    expect(registry.getSnapshot().station).toMatchObject({ status: 'legacy', descriptor: null })
    expect(registry.getSnapshot().mission).toMatchObject({ status: 'unavailable', descriptor: null })
    expect(runtimeContextLabel(registry.getSnapshot().station)).toContain('未提供')
  })
  it('does not trust a valid body from a different process or a legacy body returned as HTML', async () => {
    const registry = new RuntimeRegistry()
    await registry.refresh('mission', async () => response(descriptor(), 'process-b'))
    expect(registry.getSnapshot().mission.status).toBe('invalid')
    await registry.refresh('mission', async () => new Response('<html>fallback</html>'))
    expect(registry.getSnapshot().mission.descriptor).toBeNull()
  })
  it('does not merge reachable services in different domains', async () => {
    const registry = new RuntimeRegistry()
    await registry.refresh('mission', async () => response(descriptor()))
    await registry.refresh('cooperation', async () => response(descriptor({ service: 'cooperation', domain: 128 })))
    expect(registry.getSnapshot().mission.descriptor?.domain).toBe(127)
    expect(registry.getSnapshot().cooperation.descriptor?.domain).toBe(128)
    expect(registry.getSnapshot().voice.descriptor).toBeNull()
  })
  it('ignores a delayed discovery response after a new connection generation', async () => {
    const registry = new RuntimeRegistry(), old = defer<Response>()
    const stale = registry.refresh('mission', () => old.promise)
    await registry.refresh('mission', async () => response(descriptor({ instance_id: 'process-b' }), 'process-b'))
    old.resolve(response(descriptor())); await stale
    expect(registry.getSnapshot().mission.descriptor?.instance_id).toBe('process-b')
  })
  it('binds a command to the observed server instance and never retries a failed request', async () => {
    const registry = new RuntimeRegistry()
    await registry.refresh('mission', async () => response(descriptor()))
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(new Headers(init?.headers).get('X-Fishbot-Instance')).toBe('process-a')
      throw new Error('lost receipt')
    })
    await expect(registry.request('mission', '/sim-api/mission', { method: 'POST' }, fetcher)).rejects.toThrow('lost receipt')
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
  it('preserves authoritative retirement rejection for the existing adapter', async () => {
    const registry = new RuntimeRegistry()
    await registry.refresh('mission', async () => response(descriptor()))
    const result = await registry.request('mission', '/sim-api/mission', { method: 'POST' }, async () => response({ error: 'runtime_changed', outcome: 'rejected' }, 'process-b', 409))
    expect(result.status).toBe(409)
    expect(await registry.json(result)).toMatchObject({ outcome: 'rejected' })
    expect(registry.getSnapshot().mission.status).toBe('invalid')
  })
  it('preserves a definite rejection when discovery advances while the write is pending', async () => {
    const registry = new RuntimeRegistry(), pending = defer<Response>()
    await registry.refresh('mission', async () => response(descriptor()))
    const writing = registry.request('mission', '/sim-api/mission', { method: 'POST' }, () => pending.promise)
    await registry.refresh('mission', async () => response(descriptor({ instance_id: 'process-b' }), 'process-b'))
    pending.resolve(response({ error: 'runtime_changed', outcome: 'rejected' }, 'process-b', 409))
    const refused = await writing
    expect(await registry.json(refused)).toEqual({ error: 'runtime_changed', outcome: 'rejected' })
    expect(registry.getSnapshot().mission).toMatchObject({ status: 'verified', descriptor: { instance_id: 'process-b' } })
  })
  it('preserves a definite rejection when generation changes during original JSON decoding', async () => {
    const registry = new RuntimeRegistry(), body = defer<unknown>()
    await registry.refresh('mission', async () => response(descriptor()))
    const refusal = response({ error: 'runtime_changed', outcome: 'rejected' }, 'process-a', 409)
    refusal.json = () => body.promise
    const refused = await registry.request('mission', '/sim-api/mission', { method: 'POST' }, async () => refusal)
    const decoding = registry.json(refused)
    await registry.refresh('mission', async () => response(descriptor({ episode_id: 'episode-b' })))
    body.resolve({ error: 'runtime_changed', outcome: 'rejected' })
    await expect(decoding).resolves.toEqual({ error: 'runtime_changed', outcome: 'rejected' })
    expect(registry.getSnapshot().mission.status).toBe('verified')
  })
  it('does not exempt ordinary conflicts, malformed refusals, or successful responses from generation isolation', async () => {
    for (const [status, value] of [[409, { error: 'busy', outcome: 'rejected' }],
      [409, { error: 'runtime_changed', outcome: 'unknown' }], [409, { error: 'runtime_changed' }],
      [200, { error: 'runtime_changed', outcome: 'rejected' }], [202, { mission: { status: 'running' } }]] as const) {
      const registry = new RuntimeRegistry(), pending = defer<Response>()
      await registry.refresh('mission', async () => response(descriptor()))
      const writing = registry.request('mission', '/sim-api/mission', { method: 'POST' }, () => pending.promise)
      const assertion = expect(writing).rejects.toBeInstanceOf(RuntimeChangedError)
      await registry.refresh('mission', async () => response(descriptor({ instance_id: 'process-b' }), 'process-b'))
      pending.resolve(response(value, 'process-b', status))
      await assertion
    }
    const registry = new RuntimeRegistry()
    await registry.refresh('mission', async () => response(descriptor()))
    await expect(registry.request('mission', '/sim-api/mission', { method: 'POST' }, async () =>
      response({ error: 'busy', outcome: 'rejected' }, 'process-b', 409))).rejects.toBeInstanceOf(RuntimeChangedError)
  })
  it('keeps same-instance business rejections compatible but rejects their late decoded body', async () => {
    const registry = new RuntimeRegistry(), body = defer<unknown>()
    await registry.refresh('mission', async () => response(descriptor()))
    const refusal = response({ error: 'geometry', outcome: 'rejected' }, 'process-a', 409)
    const refused = await registry.request('mission', '/sim-api/mission', { method: 'POST' }, async () => refusal)
    expect(refused.status).toBe(409)
    refused.json = () => body.promise
    const decoding = registry.json(refused)
    const assertion = expect(decoding).rejects.toBeInstanceOf(RuntimeChangedError)
    await registry.refresh('mission', async () => response(descriptor({ instance_id: 'process-b' }), 'process-b'))
    body.resolve({ error: 'geometry', outcome: 'rejected' })
    await assertion
  })
  it('rejects a late response across restart and across reset, including delayed JSON decoding', async () => {
    for (const patch of [{ instance_id: 'process-b' }, { episode_id: 'episode-b' }, { domain: 128 }]) {
      const registry = new RuntimeRegistry(), late = defer<unknown>()
      await registry.refresh('mission', async () => response(descriptor()))
      const body = response({}); body.json = () => late.promise
      const result = await registry.request('mission', '/sim-api/state', undefined, async () => body)
      const decoding = registry.json(result)
      await registry.refresh('mission', async () => response(descriptor(patch), patch.instance_id ?? 'process-a'))
      late.resolve({ ready: true })
      await expect(decoding).rejects.toBeInstanceOf(RuntimeChangedError)
    }
  })
  it('does not let an abort-resistant discovery finish after unmount', async () => {
    const registry = new RuntimeRegistry(), waiting = defer<Response>(), controller = new AbortController()
    const run = registry.refresh('mission', () => waiting.promise, controller.signal)
    controller.abort(); waiting.resolve(response(descriptor())); await run
    expect(registry.getSnapshot().mission.status).toBe('unchecked')
  })
  it('owns one bounded read-only polling loop and releases it', async () => {
    vi.useFakeTimers()
    const registry = new RuntimeRegistry(), fetcher = vi.fn(async () => new Response('', { status: 404 }))
    const stop = registry.start(fetcher, 5000), extra = registry.start(fetcher, 5000)
    await vi.advanceTimersByTimeAsync(0)
    expect(fetcher).toHaveBeenCalledTimes(4)
    expect(fetcher.mock.calls.every((call) => !((call as unknown[])[1] as RequestInit)?.method)).toBe(true)
    extra(); await vi.advanceTimersByTimeAsync(5000)
    expect(fetcher).toHaveBeenCalledTimes(8)
    stop(); await vi.advanceTimersByTimeAsync(10000)
    expect(fetcher).toHaveBeenCalledTimes(8)
    expect(vi.getTimerCount()).toBe(0)
  })
})
