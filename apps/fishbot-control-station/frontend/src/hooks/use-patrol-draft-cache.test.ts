import { describe, expect, it } from 'vitest'
import { PatrolDraftController } from './use-patrol-draft-cache'
import { PatrolDraftCache, PatrolDraftCacheError, type DraftCache, type PatrolDraftRecord } from '@/lib/patrol-draft-cache'

const binding = { domain: 122, mapId: 'map-a', rulesRevision: 3 }
const online = { ...binding, connected: true, ready: true }
const content = { waypoints: [{ x: 1, y: 2, yaw: 0.3 }], returnHome: true, routeName: '本页草稿' }
const memory = () => new PatrolDraftCache({ storage: null, locks: null })
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
async function seeded() {
  const cache = memory(), record = await cache.write(binding, content, null)
  const controller = new PatrolDraftController(cache)
  controller.bind(online); await controller.whenIdle()
  return { cache, controller, record }
}

describe('draft controller recovery and validation fences', () => {
  it('waits for connection, map/rules readiness and a valid rules version before reading', async () => {
    let reads = 0
    const backing = memory()
    const cache: DraftCache = { mode: 'memory_only', read: (scope) => { reads++; return backing.read(scope) }, write: (...args) => backing.write(...args) }
    const controller = new PatrolDraftController(cache)
    controller.bind({ ...online, ready: false }); await controller.whenIdle()
    controller.bind({ ...online, connected: false }); await controller.whenIdle()
    controller.bind({ ...online, rulesRevision: null }); await controller.whenIdle()
    expect(reads).toBe(0); expect(controller.getSnapshot().loaded).toBe(false)
    controller.bind(online); await controller.whenIdle()
    expect(reads).toBe(1); expect(controller.getSnapshot()).toMatchObject({ loaded: true, validation: 'validated' })
    expect(controller.getSnapshot().draft.waypoints).toEqual([])
    expect(controller.getSnapshot().mode).toBe('memory_only')
  })
  it('restores only a draft and requires explicit confirmation for nonempty restored points', async () => {
    const { controller, record } = await seeded()
    const state = controller.getSnapshot()
    expect(state.draft).toEqual(content)
    expect(state.revisionId).toBe(record.revision_id)
    expect(state.validation).toBe('unvalidated')
    expect(controller.confirmValidated(state.validationToken)).toBe(true)
    expect(controller.getSnapshot().validation).toBe('validated')
    expect(() => { state.draft.waypoints[0].x = 99 }).toThrow()
    expect(controller.getSnapshot().draft.waypoints[0].x).toBe(1)
  })
  it('accepts functional draft updates and serializes rapid edits to the newest version', async () => {
    const { cache, controller } = await seeded()
    controller.setDraft((previous) => ({ ...previous, returnHome: false }))
    controller.setDraft((previous) => ({ ...previous, routeName: '最新路线' }))
    controller.setDraft((previous) => ({ ...previous, waypoints: [...previous.waypoints, { x: 3, y: 4, yaw: 0 }] }))
    await controller.whenIdle()
    const saved = await cache.read(binding)
    expect(saved).toMatchObject({ return_home: false, route_name: '最新路线', waypoints: [{ x: 1, y: 2, yaw: 0.3 }, { x: 3, y: 4, yaw: 0 }] })
    expect(controller.getSnapshot()).toMatchObject({ conflict: false, saving: false, validation: 'unvalidated', revisionId: saved?.revision_id })
  })
  it('rejects stale confirmation tokens after an edit and preserves data on invalid updates', async () => {
    const { controller } = await seeded()
    const oldToken = controller.getSnapshot().validationToken
    controller.setDraft((previous) => ({ ...previous, returnHome: false }))
    expect(controller.confirmValidated(oldToken)).toBe(false)
    controller.setDraft((previous) => ({ ...previous, waypoints: [{ x: NaN, y: 0, yaw: 0 }] }))
    expect(controller.getSnapshot().draft.waypoints).toEqual(content.waypoints)
    expect(controller.getSnapshot().message).toContain('有限')
    await controller.whenIdle()
  })
  it('retains points across a rules revision change and persists the new revision only after explicit revalidation', async () => {
    const { cache, controller } = await seeded()
    controller.confirmValidated(controller.getSnapshot().validationToken)
    await controller.whenIdle()
    controller.bind({ ...online, rulesRevision: 4 })
    expect(controller.getSnapshot().validation).toBe('stale')
    expect(controller.getSnapshot().draft).toEqual(content)
    await controller.whenIdle()
    expect((await cache.read(binding))?.rules_revision).toBe(3)
    expect(controller.confirmValidated(controller.getSnapshot().validationToken)).toBe(true)
    await controller.whenIdle()
    expect((await cache.read(binding))?.rules_revision).toBe(4)
    expect(controller.getSnapshot().validation).toBe('validated')
  })
  it('checks revision_id after reconnection and does not replace local points on a cross-tab conflict', async () => {
    const { cache, controller, record } = await seeded()
    controller.confirmValidated(controller.getSnapshot().validationToken)
    controller.bind({ ...online, connected: false })
    expect(controller.getSnapshot().validation).toBe('unvalidated')
    expect(controller.getSnapshot().draft).toEqual(content)
    const remote = await cache.write(binding, { ...content, routeName: '其他标签页' }, record.revision_id)
    controller.bind(online); await controller.whenIdle()
    expect(controller.getSnapshot()).toMatchObject({ conflict: true, revisionId: record.revision_id })
    expect(controller.getSnapshot().draft.routeName).toBe(content.routeName)
    expect(controller.confirmValidated(controller.getSnapshot().validationToken)).toBe(false)
    controller.reloadCache(); await controller.whenIdle()
    expect(controller.getSnapshot()).toMatchObject({ conflict: false, revisionId: remote.revision_id, validation: 'unvalidated' })
    expect(controller.getSnapshot().draft.routeName).toBe('其他标签页')
  })
  it('retains and caches explicit local edits while disconnected without executing them', async () => {
    const { cache, controller } = await seeded()
    controller.bind({ ...online, connected: false })
    controller.setDraft((previous) => ({ ...previous, routeName: '离线修改' }))
    await controller.whenIdle()
    expect((await cache.read(binding))?.route_name).toBe('离线修改')
    expect(controller.confirmValidated(controller.getSnapshot().validationToken)).toBe(false)
    controller.bind(online); await controller.whenIdle()
    expect(controller.getSnapshot().draft.routeName).toBe('离线修改')
    expect(controller.getSnapshot().validation).toBe('unvalidated')
  })
})

describe('old asynchronous cache work and current scope', () => {
  it('immediately replaces the exposed scope and ignores the former map’s late read', async () => {
    const old = deferred<PatrolDraftRecord | null>()
    const original = await memory().write(binding, content, null)
    const cache: DraftCache = { mode: 'memory_only', read: (scope) => scope.mapId === 'map-a' ? old.promise : Promise.resolve(null),
      write: () => Promise.reject(new Error('unexpected write')) }
    const controller = new PatrolDraftController(cache)
    controller.bind(online); await Promise.resolve()
    controller.bind({ ...online, mapId: 'map-b' })
    expect(controller.getSnapshot().scopeKey).toContain('map-b')
    expect(controller.getSnapshot().draft.waypoints).toEqual([])
    await controller.whenIdle()
    old.resolve(original); await Promise.resolve(); await Promise.resolve()
    expect(controller.getSnapshot().scopeKey).toContain('map-b')
    expect(controller.getSnapshot().draft.waypoints).toEqual([])
  })
  it('rejects a pre-disconnection read even when it resolves after reconnection', async () => {
    const old = deferred<PatrolDraftRecord | null>(), fresh = deferred<PatrolDraftRecord | null>()
    const source = memory(), a = await source.write(binding, content, null)
    const b = await source.write(binding, { ...content, routeName: '重连新版本' }, a.revision_id)
    let count = 0
    const cache: DraftCache = { mode: 'memory_only', read: () => ++count === 1 ? old.promise : fresh.promise,
      write: () => Promise.reject(new Error('unexpected write')) }
    const controller = new PatrolDraftController(cache)
    const names: string[] = []
    controller.subscribe(() => names.push(controller.getSnapshot().draft.routeName))
    controller.bind(online); await Promise.resolve()
    controller.bind({ ...online, connected: false }); controller.bind(online)
    old.resolve(a); await Promise.resolve(); await Promise.resolve()
    fresh.resolve(b); await controller.whenIdle()
    expect(controller.getSnapshot().draft.routeName).toBe('重连新版本')
    expect(names).not.toContain(content.routeName)
  })
  it('does not publish an old in-flight write result into the new map', async () => {
    const pending = deferred<PatrolDraftRecord>()
    const record = await memory().write(binding, content, null)
    const cache: DraftCache = { mode: 'memory_only', read: () => Promise.resolve(null), write: () => pending.promise }
    const controller = new PatrolDraftController(cache)
    controller.bind(online); await controller.whenIdle()
    controller.setDraft(content); await Promise.resolve()
    controller.bind({ ...online, mapId: 'map-b' }); await controller.whenIdle()
    pending.resolve(record); await Promise.resolve(); await Promise.resolve()
    expect(controller.getSnapshot()).toMatchObject({ revisionId: null, saving: false })
    expect(controller.getSnapshot().scopeKey).toContain('map-b')
    expect(controller.getSnapshot().draft.waypoints).toEqual([])
  })
  it('rejects old confirmation tokens after domain changes', async () => {
    const { controller } = await seeded()
    const token = controller.getSnapshot().validationToken
    controller.bind({ ...online, domain: 123 }); await controller.whenIdle()
    expect(controller.confirmValidated(token)).toBe(false)
  })
})

describe('cache failures do not erase drafts or retry silently', () => {
  it('retains the latest local draft and stops queued writes after a CAS conflict', async () => {
    const backing = memory(), first = await backing.write(binding, content, null)
    let writes = 0
    const cache: DraftCache = { mode: 'memory_only', read: (scope) => backing.read(scope), write: () => {
      writes++; return Promise.reject(new PatrolDraftCacheError('conflict', '他页冲突', first))
    } }
    const controller = new PatrolDraftController(cache)
    controller.bind(online); await controller.whenIdle()
    controller.setDraft((draft) => ({ ...draft, routeName: 'first' }))
    controller.setDraft((draft) => ({ ...draft, routeName: 'latest' }))
    await controller.whenIdle()
    expect(writes).toBe(1)
    expect(controller.getSnapshot()).toMatchObject({ conflict: true, validation: 'unvalidated' })
    expect(controller.getSnapshot().draft.routeName).toBe('latest')
  })
  it('surfaces read corruption, preserves it, and lets the page continue with an explicit memory-only draft', async () => {
    let writes = 0
    const cache: DraftCache = { mode: 'persistent_atomic', read: () => Promise.reject(new PatrolDraftCacheError('invalid', '缓存损坏')),
      write: () => { writes++; return Promise.reject(new Error('unexpected')) } }
    const controller = new PatrolDraftController(cache)
    controller.bind(online); await controller.whenIdle()
    expect(controller.getSnapshot()).toMatchObject({ loaded: true, loading: false, mode: 'memory_only', error: '缓存损坏' })
    controller.setDraft(content); await controller.whenIdle()
    expect(controller.getSnapshot().draft).toEqual(content)
    expect(controller.confirmValidated(controller.getSnapshot().validationToken)).toBe(true)
    expect(controller.getSnapshot().error).toBe('缓存损坏')
    expect(controller.getSnapshot().message).not.toContain('已保存')
    expect(writes).toBe(0)
  })
  it('keeps write failures visible after explicit validation and does not silently retry persistence', async () => {
    const backing = memory()
    let writes = 0
    const cache: DraftCache = { mode: 'persistent_atomic', read: (scope) => backing.read(scope), write: () => {
      writes++; return Promise.reject(new PatrolDraftCacheError('write_failed', '存储被禁止'))
    } }
    const controller = new PatrolDraftController(cache)
    controller.bind(online); await controller.whenIdle(); controller.setDraft(content); await controller.whenIdle()
    expect(controller.getSnapshot()).toMatchObject({ loaded: true, mode: 'memory_only', error: '存储被禁止' })
    expect(controller.confirmValidated(controller.getSnapshot().validationToken)).toBe(true)
    await controller.whenIdle()
    expect(controller.getSnapshot().draft).toEqual(content)
    expect(controller.getSnapshot().error).toBe('存储被禁止')
    expect(writes).toBe(1)
  })
})
