import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ManualController, manualAdmissionMessage, manualIdleRecoveryMessage, manualResetBlockReason, validateManualStatus, type ManualStatus } from './manual-control'
import { SimulationRejectedRequest } from './simulation'

const quiet = { confirmed: false, duration_s: 0, source: '/ground_truth/free_joint_states', source_stamp: null, receive_age_s: null, source_age_s: null }
const stopped = { confirmed: true, duration_s: .8, source: '/ground_truth/free_joint_states', source_stamp: 42, receive_age_s: .02, source_age_s: .01 }
const status = (): ManualStatus => ({ runtime_instance_id: 'runtime-1', map_id: 'map-1', profile_id: 'passage_manual', available: true, can_acquire: true, can_stop: true, can_reset: false,
  reason: null, active_lease_id: null, active_stop_request_id: null, stop_latched: false, native_owner: { task_id: null, status: 'idle', native_goal_id: null, terminal: true }, quiet: quiet as ManualStatus['quiet'],
  limits: { forward_mps: .08, reverse_mps: .03, angular_rps: .25, command_ttl_ms: 250, acquire_ttl_ms: 1000, heartbeat_ms: 140 } })
function fixture() {
  const values = new Map<string, string>(), posts: Array<{ path: string; body: Record<string, unknown> }> = []
  const storage = { getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => { values.set(k, v) }, removeItem: (k: string) => { values.delete(k) } }
  let number = 0, current: Record<string, unknown> | null = null, state = status()
  const request = vi.fn(async (path: string, body?: object): Promise<unknown> => {
    if (path === 'manual/status') return state
    if (!body) return { lease: current }
    const b = body as Record<string, unknown>; posts.push({ path, body: b })
    if (path === 'manual/acquire') current = { ...b, last_sequence: 0, state: 'ready', reason: null, expires_at_ms: Date.now() + 1000, remaining_ms: 1000, guard_reset_acknowledged: true, guard_stop_acknowledged: false, quiet }
    if (path === 'manual/command') current = { ...current, last_sequence: b.sequence, state: 'active', expires_at_ms: Date.now() + 250, remaining_ms: 250 }
    if (path === 'manual/release') current = { ...current, last_sequence: b.sequence, state: 'released', guard_stop_acknowledged: true, quiet: stopped }
    return { accepted: true, outcome: 'accepted', lease: current }
  })
  const create = () => new ManualController({ request: request as never, domain: 127, storage, uuid: () => `00000000-0000-4000-8000-${String(++number).padStart(12, '0')}` })
  return { create, request, posts, storage, values, getLease: () => current, setLease: (v: Record<string, unknown>) => { current = v }, setStatus: (v: ManualStatus) => { state = v } }
}
beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(100000) })
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers() })
async function settle() { await vi.advanceTimersByTimeAsync(0) }
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
async function resetRaceFixture() {
  const f = fixture(), c = f.create(), resetPost = deferred<unknown>(), resetRead = deferred<unknown>()
  const stops = new Map<string, Record<string, unknown>>()
  let s = status(), reset: Record<string, unknown> | null = null
  let nextStop: 'accepted' | 'rejected' | 'unknown' | 'receipt-unknown' = 'accepted'
  f.request.mockImplementation(async (path, body) => {
    if (path === 'manual/status') return s
    if (!body) {
      if (path.startsWith('manual/stops/')) return { stop: stops.get(path.slice('manual/stops/'.length)) }
      if (path.startsWith('manual/resets/')) return resetRead.promise
      throw new Error('Unexpected read '+path)
    }
    const b = body as Record<string, unknown>; f.posts.push({ path, body: b })
    if (path === 'manual/reset') {
      reset = { request_id: b.request_id, stop_request_id: b.stop_request_id, state: 'resetting',
        guard_reset_acknowledged: null, reason: null, runtime_instance_id: 'runtime-1' }
      return resetPost.promise
    }
    if (path !== 'manual/stop') throw new Error('Unexpected mutation '+path)
    const first = stops.size === 0
    if (!first && nextStop === 'rejected') throw new SimulationRejectedRequest('stop_target_changed', 409, 'rejected')
    const stop = { request_id: b.request_id, target_id: b.target_id, target_kind: 'idle', state: first ? 'stopped' : nextStop === 'receipt-unknown' ? 'unknown' : 'stopping',
      runtime_instance_id: 'runtime-1', native_terminal: true, native_status: null, native_cancel_acknowledged: null,
      guard_stop_acknowledged: first ? true : null, quiet: first ? stopped : quiet, reason: null }
    stops.set(String(b.request_id), stop)
    s = { ...s, stop_latched: true, can_acquire: false, can_reset: first, active_stop_request_id: String(b.request_id), quiet: stopped as ManualStatus['quiet'] }
    if (!first && nextStop === 'unknown') throw new Error('Lost new STOP response')
    return { accepted: true, outcome: 'accepted', stop }
  })
  await c.refresh(); await c.stop(); await c.refresh()
  const pendingReset = c.reset(); await settle()
  return { ...f, c, pendingReset, resetPost, resetRead, stops,
    setNextStop: (value: typeof nextStop) => { nextStop = value },
    readyReset: () => ({ ...reset!, state: 'ready', guard_reset_acknowledged: true }),
    setResetCompleted: () => { s = { ...s, stop_latched: false, can_acquire: true, can_reset: false } },
    cached: () => JSON.parse([...f.values.values()][0]),
  }
}
describe('manual control original intent and ownership', () => {
  it('explains admission blocks in Chinese and retains unknown reason codes without implying health', () => {
    const explanations: Record<string, string> = { guard_unavailable: '守卫尚未就绪或已锁定', native_owner_unresolved: '原导航动作尚未确认结束',
      explicit_stop_latched: '显式解除', manual_lease_busy: '原控制回执', manual_cleanup_unconfirmed: '停车清理', continuous_quiet_unconfirmed: '0.7 秒' }
    for (const [reason, text] of Object.entries(explanations)) expect(manualAdmissionMessage({ reason, can_acquire: false })).toContain(text)
    expect(manualAdmissionMessage({ reason: 'future_guard_code', can_acquire: false })).toContain('future_guard_code')
    expect(manualAdmissionMessage({ reason: null, can_acquire: false })).not.toContain('可申请控制权')
    expect(manualAdmissionMessage({ reason: null, can_acquire: true })).toContain('下一次按住')
  })
  it('accepts optional bounded recovery evidence without treating attempts or past recovery as current readiness', () => {
    expect(validateManualStatus(status()).idle_recovery).toBeUndefined()
    const recovery = { trigger_id: '/private/trigger-a.json', state: 'resetting', reason: 'odom: receive timeout', guard_reset_acknowledged: null, runtime_instance_id: 'runtime-1', native_task_id: null }
    const current = validateManualStatus({ ...status(), can_acquire: false, reason: 'guard_unavailable', idle_recovery: recovery, idle_recovery_attempts: 2 })
    expect(manualIdleRecoveryMessage(current)).toContain('正在确认')
    expect(manualIdleRecoveryMessage(current)).toContain('累计尝试 2 次')
    const ready = validateManualStatus({ ...current, idle_recovery: { ...recovery, state: 'ready', reason: null, guard_reset_acknowledged: true } })
    expect(manualIdleRecoveryMessage(ready)).toContain('当前能否行驶仍以准入核对为准')
    expect(manualAdmissionMessage(ready)).toContain('守卫尚未就绪或已锁定')
    expect(manualIdleRecoveryMessage({ idle_recovery: { ...recovery, state: 'unknown' } as never })).toContain('未确认')
    expect(manualIdleRecoveryMessage({ idle_recovery: { ...recovery, state: 'unknown', reason: 'guard_reset_timeout' } as never })).toContain('期限内收到守卫恢复回执')
    for (const patch of [{ idle_recovery_attempts: -1 }, { idle_recovery_attempts: Infinity }, { idle_recovery_attempts: true },
      { idle_recovery: { ...recovery, runtime_instance_id: 'another-runtime' } }, { idle_recovery: { ...recovery, state: 'ready' } },
      { idle_recovery: { ...recovery, state: 'success' } }, { idle_recovery: { ...recovery, trigger_id: 'x'.repeat(4097) } }]) {
      expect(() => validateManualStatus({ ...status(), ...patch })).toThrow()
    }
  })
  it('does no write on construction or capability read, and rejects relaxed speed or fake quiet', async () => {
    const f = fixture(), c = f.create(); expect(f.request).not.toHaveBeenCalled(); await c.refresh(); expect(f.posts).toEqual([])
    expect(() => validateManualStatus({ ...status(), limits: { ...status().limits, forward_mps: .25 } })).toThrow()
    expect(() => validateManualStatus({ ...status(), quiet: { ...quiet, confirmed: true } })).toThrow()
  })
  it('bounds both directions and angular speed, serializes heartbeat, and stops on release', async () => {
    for (const direction of ['forward', 'backward', 'left', 'right'] as const) {
      const f = fixture(), c = f.create(); await c.refresh(); await c.begin(direction, 1, 2); await settle()
      await vi.advanceTimersByTimeAsync(280)
      const commands = f.posts.filter(v => v.path === 'manual/command'); expect(commands.length).toBe(3)
      expect(commands.map(v => v.body.sequence)).toEqual([1, 2, 3]); expect(commands.every(v => v.body.ttl_ms === 250)).toBe(true)
      const vector = commands[0].body
      expect(vector.linear_x).toBe(direction === 'forward' ? .08 : direction === 'backward' ? -.03 : 0)
      expect(vector.angular_z).toBe(direction === 'left' ? .25 : direction === 'right' ? -.25 : 0)
      await c.release(); const count = f.posts.length; await vi.advanceTimersByTimeAsync(1000); expect(f.posts).toHaveLength(count)
      await c.refresh(); expect(c.getSnapshot().unknown).toBe(false); expect(c.getSnapshot().lease?.quiet.confirmed).toBe(true)
      expect(f.values.size).toBe(0)
    }
  })
  it.each([80, 100])('includes a %ims ACK in the 140ms send interval without overlapping commands', async delay => {
    const f = fixture(), c = f.create(), delegate = f.request.getMockImplementation()!
    let inFlight = 0, maximum = 0
    f.request.mockImplementation(async (path, body) => {
      const value = await delegate(path, body)
      if (path === 'manual/command') {
        ++inFlight; maximum = Math.max(maximum, inFlight)
        await new Promise(resolve => setTimeout(resolve, delay)); --inFlight
      }
      return value
    })
    await c.refresh(); await c.begin('forward', .04, .1); await settle()
    await vi.advanceTimersByTimeAsync(420)
    const commands = f.posts.filter(v => v.path === 'manual/command')
    expect(commands.map(v => v.body.issued_at_ms)).toEqual([100000, 100140, 100280, 100420])
    expect(commands.map(v => v.body.sequence)).toEqual([1, 2, 3, 4]); expect(maximum).toBe(1)
    await c.release(); const before = f.posts.length; await vi.advanceTimersByTimeAsync(1000)
    expect(f.posts).toHaveLength(before); expect(c.getSnapshot().direction).toBeNull()
  })
  it('late ACK after a release cannot schedule a new heartbeat for the old generation', async () => {
    const f = fixture(), c = f.create(), delegate = f.request.getMockImplementation()!
    f.request.mockImplementation(async (path, body) => {
      const value = await delegate(path, body)
      if (path === 'manual/command') await new Promise(resolve => setTimeout(resolve, 100))
      return value
    })
    await c.refresh(); await c.begin('left', .04, .15); await settle()
    await vi.advanceTimersByTimeAsync(50); await c.release(); await vi.advanceTimersByTimeAsync(1000)
    expect(f.posts.map(v => v.path)).toEqual(['manual/acquire', 'manual/command', 'manual/release'])
    expect(c.getSnapshot().direction).toBeNull(); expect(c.getSnapshot().lease?.state).toBe('released')
  })
  it('does not catch up or renew a command whose ACK arrives after its original 250ms lease', async () => {
    const f = fixture(), c = f.create(), delegate = f.request.getMockImplementation()!
    f.request.mockImplementation(async (path, body) => {
      const value = await delegate(path, body)
      if (path === 'manual/command') await new Promise(resolve => setTimeout(resolve, 280))
      return value
    })
    await c.refresh(); await c.begin('forward', .04, .1); await settle(); await vi.advanceTimersByTimeAsync(1000)
    expect(f.posts.filter(v => v.path === 'manual/command')).toHaveLength(1)
    expect(c.getSnapshot().unknown).toBe(true); expect(c.getSnapshot().direction).toBeNull()
    expect(c.getSnapshot().error).toContain('租约已结束')
  })
  it('release before acquire acknowledgement cannot start or renew an old hold', async () => {
    const f = fixture(), c = f.create(); await c.refresh()
    const original = f.request.getMockImplementation()!; let resolve!: (value: unknown) => void
    f.request.mockImplementation(async (path, body) => {
      const value = await original(path, body)
      if (path === 'manual/acquire') return await new Promise(done => { resolve = done })
      return value
    })
    const began = c.begin('forward', .04, .2); await settle(); await c.release()
    resolve({ accepted: true, outcome: 'accepted', lease: f.getLease() }); await began; await vi.advanceTimersByTimeAsync(1000)
    expect(f.posts.filter(v => v.path === 'manual/command')).toEqual([])
    expect(f.posts.map(v => v.path)).toEqual(['manual/acquire', 'manual/release'])
  })
  it('arming polls are reads and do not queue nonzero commands', async () => {
    const f = fixture(), c = f.create(); await c.refresh(); const original = f.request.getMockImplementation()!
    f.request.mockImplementation(async (path, body) => {
      const value = await original(path, body)
      if (path === 'manual/acquire') { f.setLease({ ...f.getLease(), state: 'arming' }); return { accepted: true, outcome: 'accepted', lease: f.getLease() } }
      return value
    })
    await c.begin('left', .04, .1); await vi.advanceTimersByTimeAsync(300)
    expect(f.posts).toHaveLength(1); await c.release(); await c.refresh()
    expect(f.posts.filter(v => v.path === 'manual/command')).toHaveLength(0)
  })
  it('unknown acquisition is not replayed or silently unlocked by elapsed time', async () => {
    const f = fixture(), c = f.create(); await c.refresh()
    f.request.mockImplementation(async (path, body) => { if (body) { f.posts.push({ path, body: body as Record<string, unknown> }); throw new Error('lost') } return status() })
    await c.begin('forward', .04, .1); await vi.advanceTimersByTimeAsync(10000); await c.begin('forward', .04, .1)
    expect(f.posts).toHaveLength(1); expect(c.getSnapshot().unknown).toBe(true)
  })
  it('command timeout halts heartbeat, retains identity, and never replays the failed sequence', async () => {
    const f = fixture(), c = f.create(); await c.refresh(); const original = f.request.getMockImplementation()!
    f.request.mockImplementation(async (path, body) => { const value = await original(path, body); if (path === 'manual/command') throw new Error('lost response'); return value })
    await c.begin('forward', .04, .1); await vi.advanceTimersByTimeAsync(1000)
    expect(f.posts.filter(v => v.path === 'manual/command')).toHaveLength(1); expect(c.getSnapshot().unknown).toBe(true); expect(c.getSnapshot().direction).toBeNull()
    f.setLease({ ...f.getLease(), state: 'expired', guard_stop_acknowledged: true, quiet: stopped }); await c.refresh()
    expect(c.getSnapshot().unknown).toBe(false); const count = f.posts.length; await vi.advanceTimersByTimeAsync(1000); expect(f.posts).toHaveLength(count)
  })
  it('recovers original expiry when a command never reached the server and accepted sequence is lower', async () => {
    const f = fixture(), c = f.create(); await c.refresh(); const original = f.request.getMockImplementation()!
    f.request.mockImplementation(async (path, body) => {
      if (path === 'manual/command') { f.posts.push({ path, body: body as Record<string, unknown> }); throw new Error('network lost before server') }
      return original(path, body)
    })
    await c.begin('forward', .04, .1); await settle(); expect(c.getSnapshot().unknown).toBe(true)
    expect(f.getLease()?.last_sequence).toBe(0)
    f.setLease({ ...f.getLease(), state: 'expired', remaining_ms: 0, guard_stop_acknowledged: true, quiet: stopped })
    const count = f.posts.length; await c.refresh(); await vi.advanceTimersByTimeAsync(1000)
    expect(c.getSnapshot().unknown).toBe(false); expect(c.getSnapshot().direction).toBeNull(); expect(f.values.size).toBe(0); expect(f.posts).toHaveLength(count)
  })
  it('recovers expiry after a release never reached the server without replaying release or motion', async () => {
    const f = fixture(), c = f.create(); await c.refresh(); await c.begin('left', .04, .1); await settle()
    const original = f.request.getMockImplementation()!, lastAccepted = f.getLease()?.last_sequence
    f.request.mockImplementation(async (path, body) => {
      if (path === 'manual/release') { f.posts.push({ path, body: body as Record<string, unknown> }); throw new Error('release lost before server') }
      return original(path, body)
    })
    await c.release(); expect(c.getSnapshot().unknown).toBe(true); expect(f.getLease()?.last_sequence).toBe(lastAccepted)
    f.setLease({ ...f.getLease(), state: 'expired', remaining_ms: 0, guard_stop_acknowledged: true, quiet: stopped })
    const count = f.posts.length; await c.refresh(); await vi.advanceTimersByTimeAsync(1000)
    expect(c.getSnapshot().unknown).toBe(false); expect(c.getSnapshot().direction).toBeNull(); expect(f.values.size).toBe(0); expect(f.posts).toHaveLength(count)
  })
  it('still rejects an accepted POST acknowledgement with a different sequence', async () => {
    const f = fixture(), c = f.create(); await c.refresh(); const original = f.request.getMockImplementation()!
    f.request.mockImplementation(async (path, body) => {
      if (path === 'manual/command') { f.posts.push({ path, body: body as Record<string, unknown> }); return { accepted: true, outcome: 'accepted', lease: f.getLease() } }
      return original(path, body)
    })
    await c.begin('forward', .04, .1); await settle(); await vi.advanceTimersByTimeAsync(1000)
    expect(c.getSnapshot().unknown).toBe(true); expect(c.getSnapshot().direction).toBeNull(); expect(f.posts.filter(p => p.path === 'manual/command')).toHaveLength(1)
  })
  it('page reload reads original receipt but never recreates pointer or keyboard intent', async () => {
    const f = fixture(), first = f.create(); await first.refresh(); await first.begin('forward', .04, .1); await settle()
    // Simulate abrupt browser loss: no lifecycle handler or release can run.
    vi.clearAllTimers(); const restarted = f.create(); await restarted.refresh(); await vi.advanceTimersByTimeAsync(1000)
    expect(f.posts.filter(v => v.path === 'manual/acquire')).toHaveLength(1); expect(f.posts.filter(v => v.path === 'manual/command')).toHaveLength(1)
    expect(restarted.getSnapshot().direction).toBeNull(); expect(restarted.getSnapshot().unknown).toBe(true)
    f.setLease({ ...f.getLease(), state: 'expired', guard_stop_acknowledged: true, quiet: stopped }); await restarted.refresh(); expect(restarted.getSnapshot().unknown).toBe(false)
  })
  it('an old instance cannot supply a new motion or falsely resolve the receipt', async () => {
    const f = fixture(), c = f.create(); await c.refresh(); await c.begin('left', .04, .1); await settle()
    f.setStatus({ ...status(), runtime_instance_id: 'runtime-2' }); await c.refresh(); await vi.advanceTimersByTimeAsync(1000)
    expect(c.getSnapshot().unknown).toBe(true); expect(c.getSnapshot().direction).toBeNull(); expect(f.posts.filter(v => v.path === 'manual/command')).toHaveLength(1)
  })
  it('explicit rejection permits a new gesture while storage failure prevents dispatch', async () => {
    const f = fixture(), c = f.create(); await c.refresh()
    f.request.mockRejectedValueOnce(new SimulationRejectedRequest('manual_busy', 409, 'rejected'))
    await c.begin('forward', .04, .1); expect(c.getSnapshot().unknown).toBe(false); expect(f.values.size).toBe(0)
    const broken = new ManualController({ domain: 127, request: f.request as never, storage: { ...f.storage, setItem: () => { throw new Error('quota') } } })
    await broken.refresh(); const count = f.posts.length; await broken.begin('forward', .04, .1); expect(f.posts).toHaveLength(count)
  })
  it('bounds arming time and rejects ambiguous acceptance without sending velocity', async () => {
    const f = fixture(), c = f.create(); await c.refresh(); const original = f.request.getMockImplementation()!
    f.request.mockImplementation(async (path, body) => {
      const value = await original(path, body)
      if (path === 'manual/acquire') { f.setLease({ ...f.getLease(), state: 'arming' }); return { accepted: true, outcome: 'accepted', lease: f.getLease() } }
      return value
    })
    await c.begin('forward', .04, .1); await vi.advanceTimersByTimeAsync(1600)
    expect(c.getSnapshot().unknown).toBe(true); expect(c.getSnapshot().direction).toBeNull(); expect(f.posts).toHaveLength(1)
    const g = fixture(), d = g.create(); await d.refresh(); const delegate = g.request.getMockImplementation()!
    g.request.mockImplementation(async (path, body) => { const v = await delegate(path, body); return path === 'manual/acquire' ? { lease: g.getLease() } : v })
    await d.begin('forward', .04, .1); await settle(); expect(g.posts).toHaveLength(1); expect(d.getSnapshot().unknown).toBe(true)
  })
  it('keeps exact stop/reset identities through reload, and reset never starts motion', async () => {
    const f = fixture(), c = f.create(); const task = '00000000-0000-4000-8000-999999999999'
    let stop: Record<string, unknown> | null = null, reset: Record<string, unknown> | null = null
    let s = { ...status(), native_owner: { task_id: task, native_goal_id: 'native-goal', terminal: false, status: 'running' }, can_acquire: false }
    f.request.mockImplementation(async (path, body) => {
      if (path === 'manual/status') return s
      if (!body) return path.includes('/stops/') ? { stop } : { reset }
      const b = body as Record<string, unknown>; f.posts.push({ path, body: b })
      if (path === 'manual/stop') {
        stop = { request_id: b.request_id, target_id: b.target_id, target_kind: 'mission', state: 'stopping', runtime_instance_id: 'runtime-1', reason: null,
          guard_stop_acknowledged: true, native_cancel_acknowledged: true, native_terminal: false, native_status: 2, quiet }
        throw new Error('lost stop response')
      }
      reset = { request_id: b.request_id, stop_request_id: b.stop_request_id, state: 'ready', guard_reset_acknowledged: true, reason: null, runtime_instance_id: 'runtime-1' }
      return { accepted: true, outcome: 'accepted', reset }
    })
    await c.refresh(); await c.stop(); await c.stop(); expect(f.posts).toHaveLength(1); expect(f.posts[0].body.target_id).toBe(task)
    const recovered = f.create(); await recovered.refresh(); expect(recovered.getSnapshot().stop?.target_id).toBe(task)
    stop = { ...(stop as Record<string, unknown> | null), state: 'stopped', native_terminal: true, native_status: 5, quiet: stopped }
    s = { ...s, can_reset: true, stop_latched: true, active_stop_request_id: String(f.posts[0].body.request_id) }
    await recovered.refresh(); await recovered.reset(); await recovered.refresh(); await vi.advanceTimersByTimeAsync(1000)
    expect(f.posts.map(v => v.path)).toEqual(['manual/stop', 'manual/reset'])
    expect(f.posts[1].body.stop_request_id).toBe(f.posts[0].body.request_id)
    expect(recovered.getSnapshot().unknown).toBe(false); expect(recovered.getSnapshot().direction).toBeNull(); expect(f.values.size).toBe(0)
  })
  it('does not accept a stopped label without exact target and independent quiet', async () => {
    const f = fixture(), c = f.create(); await c.refresh(); await c.begin('left', .04, .1); await settle()
    const originalTarget = f.getLease()!.lease_id
    f.setStatus({ ...status(), active_lease_id: String(originalTarget) }); await c.refresh()
    f.request.mockImplementation(async (path, body) => {
      if (!body) return status()
      const b = body as Record<string, unknown>; f.posts.push({ path, body: b })
      return { accepted: true, outcome: 'accepted', stop: { request_id: b.request_id, target_id: 'other-target', target_kind: 'manual', state: 'stopped', runtime_instance_id: 'runtime-1',
        native_terminal: true, native_status: null, native_cancel_acknowledged: true, guard_stop_acknowledged: true, quiet, reason: null } }
    })
    await c.stop(); expect(f.posts.at(-1)?.body.target_id).toBe(originalTarget); expect(c.getSnapshot().unknown).toBe(true)
    await vi.advanceTimersByTimeAsync(1000); expect(f.posts.filter(v => v.path === 'manual/command')).toHaveLength(1)
  })
  it('allows a new explicit STOP after definite rejection without replaying the rejected ID', async () => {
    const f = fixture(), c = f.create(); let rejected = true
    f.request.mockImplementation(async (path, body) => {
      if (!body) return status()
      const b = body as Record<string, unknown>; f.posts.push({ path, body: b })
      if (rejected) { rejected = false; throw new SimulationRejectedRequest('truth_not_ready', 409, 'rejected') }
      return { accepted: true, outcome: 'accepted', stop: { request_id: b.request_id, target_id: b.target_id, target_kind: 'idle', state: 'stopping', runtime_instance_id: 'runtime-1',
        native_terminal: true, native_status: null, native_cancel_acknowledged: null, guard_stop_acknowledged: null, quiet, reason: null } }
    })
    await c.refresh(); await c.stop(); expect(c.getSnapshot().unknown).toBe(false); expect(f.values.size).toBe(0)
    await vi.advanceTimersByTimeAsync(5000); expect(f.posts).toHaveLength(1)
    await c.stop(); expect(f.posts).toHaveLength(2)
    expect(f.posts[1].body.request_id).not.toBe(f.posts[0].body.request_id)
    expect(c.getSnapshot().stop?.request_id).toBe(f.posts[1].body.request_id)
  })
  it('retains the original STOP after definite reset rejection and retries only on another click', async () => {
    const f = fixture(), c = f.create(); let s = status(), stop: Record<string, unknown> | null = null, reset: Record<string, unknown> | null = null, rejectReset = true
    f.request.mockImplementation(async (path, body) => {
      if (path === 'manual/status') return s
      if (!body) return path.includes('/stops/') ? { stop } : { reset }
      const b = body as Record<string, unknown>; f.posts.push({ path, body: b })
      if (path === 'manual/stop') {
        stop = { request_id: b.request_id, target_id: b.target_id, target_kind: 'idle', state: 'stopped', runtime_instance_id: 'runtime-1',
          native_terminal: true, native_status: null, native_cancel_acknowledged: null, guard_stop_acknowledged: true, quiet: stopped, reason: null }
        s = { ...s, stop_latched: true, can_acquire: false, can_reset: true, active_stop_request_id: String(b.request_id) }
        return { accepted: true, outcome: 'accepted', stop }
      }
      if (rejectReset) { rejectReset = false; throw new SimulationRejectedRequest('stop_cleanup_unconfirmed', 409, 'rejected') }
      reset = { request_id: b.request_id, stop_request_id: b.stop_request_id, state: 'ready', guard_reset_acknowledged: true, reason: null, runtime_instance_id: 'runtime-1' }
      s = { ...s, stop_latched: false, can_acquire: true, can_reset: false }
      return { accepted: true, outcome: 'accepted', reset }
    })
    await c.refresh(); await c.stop(); await c.refresh(); await c.reset()
    expect(c.getSnapshot().unknown).toBe(false); expect(c.getSnapshot().reset).toBeNull()
    expect(c.getSnapshot().stop?.request_id).toBe(f.posts[0].body.request_id)
    await c.refresh(); await vi.advanceTimersByTimeAsync(1000); expect(f.posts).toHaveLength(2)
    expect(f.request.mock.calls.some(([path]) => path === `manual/resets/${f.posts[1].body.request_id}`)).toBe(false)
    await c.reset(); await c.refresh()
    expect(f.posts.map(v => v.path)).toEqual(['manual/stop', 'manual/reset', 'manual/reset'])
    expect(f.posts[2].body.request_id).not.toBe(f.posts[1].body.request_id)
    expect(f.posts[2].body.stop_request_id).toBe(f.posts[0].body.request_id)
    expect(c.getSnapshot().unknown).toBe(false); expect(f.values.size).toBe(0)
  })
  it('a new explicit STOP supersedes pending reset POST and GET replies with a new receipt generation', async () => {
    const f = await resetRaceFixture(), oldStop = f.posts[0].body.request_id, oldReset = f.posts[1].body.request_id
    const staleRead = f.c.refresh(); await settle()
    await f.c.stop()
    const newStop = f.posts[2].body.request_id
    expect(newStop).not.toBe(oldStop)
    expect(f.cached().prior_reset).toMatchObject({ stop_id: oldStop, reset_id: oldReset })
    f.resetPost.resolve({ accepted: true, outcome: 'accepted', reset: f.readyReset() })
    f.resetRead.resolve({ reset: f.readyReset() })
    await f.pendingReset; await staleRead
    expect(f.c.getSnapshot().stop?.request_id).toBe(newStop)
    expect(f.c.getSnapshot().reset).toBeNull()
    expect(f.cached().stop_id).toBe(newStop)
    expect(f.c.canBegin()).toBe(false)
    await vi.advanceTimersByTimeAsync(5000)
    expect(f.posts.map(v => v.path)).toEqual(['manual/stop', 'manual/reset', 'manual/stop'])
  })
  it('a STOP after an unknown reset gets a fresh identity and retains an unknown STOP receipt as unknown', async () => {
    const f = await resetRaceFixture()
    f.resetPost.reject(new Error('Lost reset response')); await f.pendingReset
    expect(f.c.getSnapshot().unknown).toBe(true)
    f.setNextStop('receipt-unknown'); await f.c.stop()
    expect(f.posts[2].body.request_id).not.toBe(f.posts[0].body.request_id)
    expect(f.c.getSnapshot().stop?.state).toBe('unknown')
    expect(f.c.getSnapshot().unknown).toBe(true)
    const recovered = f.create(); await recovered.refresh(); await recovered.stop()
    expect(recovered.getSnapshot().stop?.request_id).toBe(f.posts[2].body.request_id)
    expect(recovered.getSnapshot().unknown).toBe(true)
    expect(f.cached().prior_reset.reset_id).toBe(f.posts[1].body.request_id)
    expect(f.posts).toHaveLength(3)
  })
  it('a definitely rejected superseding STOP restores the old reset for fresh read-only recovery', async () => {
    const f = await resetRaceFixture(), staleRead = f.c.refresh(); await settle()
    f.setNextStop('rejected'); await f.c.stop()
    expect(f.cached()).toMatchObject({ stop_id: f.posts[0].body.request_id, reset_id: f.posts[1].body.request_id, last_sequence: f.posts[2].body.sequence })
    expect(f.c.getSnapshot().unknown).toBe(true)
    expect(f.c.getSnapshot().pending).toBe('reset-recovery')
    f.resetPost.resolve({ accepted: true, outcome: 'accepted', reset: f.readyReset() })
    f.resetRead.resolve({ reset: f.readyReset() })
    await f.pendingReset; await staleRead
    expect(f.values.size).toBe(1)
    expect(f.c.getSnapshot().reset).toBeNull()
    const recovered = f.create(); f.setResetCompleted(); await recovered.refresh()
    expect(recovered.getSnapshot().unknown).toBe(false)
    expect(recovered.getSnapshot().direction).toBeNull()
    expect(f.values.size).toBe(0)
    expect(f.posts.map(v => v.path)).toEqual(['manual/stop', 'manual/reset', 'manual/stop'])
  })
  it('an unknown superseding STOP survives reload and never falls back to or replays the old reset', async () => {
    const f = await resetRaceFixture(); f.setNextStop('unknown'); await f.c.stop()
    const currentStop = f.posts[2].body.request_id
    expect(f.c.getSnapshot().unknown).toBe(true)
    f.resetPost.resolve({ accepted: true, outcome: 'accepted', reset: f.readyReset() }); await f.pendingReset
    const recovered = f.create(), before = f.request.mock.calls.length
    await recovered.refresh(); await recovered.stop(); await vi.advanceTimersByTimeAsync(5000)
    expect(recovered.getSnapshot().stop?.request_id).toBe(currentStop)
    expect(f.request.mock.calls.slice(before).map(([path]) => path)).toEqual(['manual/status', `manual/stops/${currentStop}`])
    expect(f.cached().stop_id).toBe(currentStop)
    expect(f.cached().prior_reset.reset_id).toBe(f.posts[1].body.request_id)
    expect(f.posts).toHaveLength(3)
  })
  it('an unsent superseding STOP preserves the old reset when its receipt cache cannot be updated', async () => {
    const f = await resetRaceFixture()
    vi.spyOn(f.storage, 'setItem').mockImplementation(() => { throw new Error('disk unavailable') })
    await f.c.stop()
    expect(f.posts).toHaveLength(2)
    expect(f.c.getSnapshot().unknown).toBe(true)
    expect(f.c.getSnapshot().error).toContain('原回执缓存更新失败')
    expect(f.cached().reset_id).toBe(f.posts[1].body.request_id)
    f.resetPost.resolve({ accepted: true, outcome: 'accepted', reset: f.readyReset() }); await f.pendingReset
    expect(f.c.getSnapshot().reset).toBeNull()
    expect(f.c.canBegin()).toBe(false)
  })
  it('invalid or recursive prior-reset checkpoints remain blocked without writes after reload', async () => {
    const f = await resetRaceFixture(); await f.c.stop()
    const saved = f.cached(), [key] = f.values.keys(), count = f.posts.length
    for (const prior of [{ ...saved.prior_reset, stop_id: saved.stop_id },
      { ...saved.prior_reset, last_sequence: saved.last_sequence+1 },
      { ...saved.prior_reset, prior_reset: saved.prior_reset }]) {
      f.values.set(key, JSON.stringify({ ...saved, prior_reset: prior }))
      const recovered = f.create(); expect(recovered.getSnapshot().unknown).toBe(true)
      expect(recovered.getSnapshot().error).toContain('缓存无效')
      expect(recovered.canBegin()).toBe(false)
    }
    expect(f.posts).toHaveLength(count)
    f.resetPost.resolve({ accepted: true, outcome: 'accepted', reset: f.readyReset() }); await f.pendingReset
  })
  it('a fresh tab explains that it lacks the active STOP receipt and cannot silently reset it', async () => {
    const f = fixture(), c = f.create()
    f.setStatus({ ...status(), stop_latched: true, can_reset: true, active_stop_request_id: '00000000-0000-4000-8000-999999999999' })
    await c.refresh(); expect(manualResetBlockReason(c.getSnapshot())).toContain('本页没有当前停车锁的原回执')
    await c.reset(); expect(f.posts).toHaveLength(0); expect(c.getSnapshot().message).toContain('原会话解除')
    expect(c.getSnapshot().direction).toBeNull()
  })
  it('does not offer a new gesture until the original released receipt is read back', async () => {
    const f = fixture(), c = f.create(); await c.refresh(); expect(c.canBegin()).toBe(true)
    await c.begin('forward', .04, .1); await settle(); await c.release()
    expect(c.getSnapshot().status?.can_acquire).toBe(true); expect(c.getSnapshot().pending).toBeNull()
    expect(c.canBegin()).toBe(false)
    const count = f.posts.length; await c.begin('left', .04, .1); expect(f.posts).toHaveLength(count)
    await c.refresh(); expect(c.canBegin()).toBe(true)
  })
  it('targets idle after a completed native task or a released lease instead of reusing a stale ID', async () => {
    for (const prior of ['native', 'lease'] as const) {
      const f = fixture(), c = f.create(); await c.refresh()
      if (prior === 'native') {
        f.setStatus({ ...status(), native_owner: { task_id: 'old-completed-task', native_goal_id: 'old-native', terminal: true, status: 'completed' } }); await c.refresh()
      } else { await c.begin('forward', .04, .1); await settle(); await c.release() }
      const delegate = f.request.getMockImplementation()!
      f.request.mockImplementation(async (path, body) => {
        if (path !== 'manual/stop') return delegate(path, body)
        const b = body as Record<string, unknown>; f.posts.push({ path, body: b })
        return { accepted: true, outcome: 'accepted', stop: { request_id: b.request_id, target_id: null, target_kind: 'idle', state: 'stopping', runtime_instance_id: 'runtime-1',
          native_terminal: true, native_status: null, native_cancel_acknowledged: null, guard_stop_acknowledged: null, quiet, reason: null } }
      })
      await c.stop(); expect(f.posts.at(-1)?.body.target_id).toBeNull(); expect(c.getSnapshot().unknown).toBe(false)
    }
  })
  it('does not replace a different active lease target silently', async () => {
    const f = fixture(), c = f.create(); await c.refresh(); await c.begin('forward', .04, .1); await settle()
    f.setStatus({ ...status(), active_lease_id: '00000000-0000-4000-8000-888888888888' }); await c.refresh()
    const before = f.posts.length; await c.stop(); expect(f.posts).toHaveLength(before)
    expect(c.getSnapshot().error).toContain('当前活动租约与本页原租约不一致'); expect(c.getSnapshot().direction).toBeNull()
  })
})
