import { describe, expect, it } from 'vitest'
import { MAX_DRAFT_BYTES, PatrolDraftCache, PatrolDraftCacheError, contentFromDraftRecord, decodePatrolDraft,
  emptyPatrolDraft, patrolDraftCacheKey, validatePatrolDraft, type DraftLocks, type DraftStorage, type PatrolDraftRecord } from './patrol-draft-cache'

class StorageFixture implements DraftStorage {
  readonly values = new Map<string, string>()
  reads = 0
  writes = 0
  failWrite = false
  getItem(key: string) { this.reads++; return this.values.get(key) ?? null }
  setItem(key: string, value: string) { this.writes++; if (this.failWrite) throw new Error('quota'); this.values.set(key, value) }
}
class ExclusiveLocks implements DraftLocks {
  readonly tails = new Map<string, Promise<unknown>>()
  readonly keys: string[] = []
  async request<T>(key: string, callback: () => T | Promise<T>): Promise<T> {
    this.keys.push(key)
    const operation = (this.tails.get(key) ?? Promise.resolve()).catch(() => {}).then(callback)
    this.tails.set(key, operation)
    return operation
  }
}
const binding = { domain: 122, mapId: 'map-a', rulesRevision: 3 }
const draft = { waypoints: [{ x: 1, y: 2, yaw: 0.3 }], returnHome: true, routeName: '工位巡逻' }
function fixture() {
  const storage = new StorageFixture(), locks = new ExclusiveLocks()
  return { storage, locks, first: new PatrolDraftCache({ storage, locks }), second: new PatrolDraftCache({ storage, locks }) }
}
const record = (): PatrolDraftRecord => ({ version: 1, domain: 122, map_id: 'map-a',
  revision_id: '62753286-32e5-4679-a0b1-e6245c5fa705', rules_revision: 3, saved_at: 1234,
  waypoints: [{ x: 1, y: 2, yaw: 0.3 }], return_home: true, route_name: '工位' })

describe('strict draft cache records', () => {
  it('accepts only draft fields and isolates returned objects', () => {
    const input = record(), parsed = decodePatrolDraft(JSON.stringify(input), binding)
    const content = contentFromDraftRecord(parsed)
    content.waypoints[0].x = 99
    expect(parsed.waypoints[0].x).toBe(1)
    expect(emptyPatrolDraft()).toEqual({ waypoints: [], returnHome: true, routeName: '' })
    expect(Object.keys(parsed).sort()).toEqual(['version','domain','map_id','revision_id','rules_revision','saved_at','waypoints','return_home','route_name'].sort())
  })
  it.each([
    (r: PatrolDraftRecord) => ({ ...r, issued_at: 123 }), (r: PatrolDraftRecord) => ({ ...r, action: 'mission' }),
    (r: PatrolDraftRecord) => ({ ...r, version: 2 }), (r: PatrolDraftRecord) => ({ ...r, domain: 0 }),
    (r: PatrolDraftRecord) => ({ ...r, map_id: 'other-map' }), (r: PatrolDraftRecord) => ({ ...r, revision_id: 'bad' }),
    (r: PatrolDraftRecord) => ({ ...r, rules_revision: -1 }), (r: PatrolDraftRecord) => ({ ...r, rules_revision: 1.2 }),
    (r: PatrolDraftRecord) => ({ ...r, saved_at: -1 }), (r: PatrolDraftRecord) => ({ ...r, saved_at: NaN }),
    (r: PatrolDraftRecord) => ({ ...r, return_home: 1 }), (r: PatrolDraftRecord) => ({ ...r, route_name: 'x'.repeat(81) }),
    (r: PatrolDraftRecord) => ({ ...r, waypoints: Array.from({ length: 13 }, () => ({ x: 0, y: 0, yaw: 0 })) }),
    (r: PatrolDraftRecord) => ({ ...r, waypoints: [{ x: NaN, y: 0, yaw: 0 }] }),
    (r: PatrolDraftRecord) => ({ ...r, waypoints: [{ x: 0, y: 0, yaw: 0, issued_at: 1 }] }),
  ])('rejects untrusted, excessive or executable storage data', (mutate) => {
    expect(() => decodePatrolDraft(JSON.stringify(mutate(record())), binding)).toThrow(PatrolDraftCacheError)
  })
  it('bounds raw storage size before parsing and rejects invalid JSON', () => {
    expect(() => decodePatrolDraft(' '.repeat(MAX_DRAFT_BYTES + 1), binding)).toThrow('大小')
    expect(() => decodePatrolDraft('{', binding)).toThrow('JSON')
    expect(() => validatePatrolDraft({ ...draft, waypoints: [{ x: 0, y: Infinity, yaw: 0 }] })).toThrow()
  })
  it('keeps domain and map identities in separate encoded keys', () => {
    expect(patrolDraftCacheKey(binding)).not.toBe(patrolDraftCacheKey({ ...binding, domain: 123 }))
    expect(patrolDraftCacheKey(binding)).not.toBe(patrolDraftCacheKey({ ...binding, mapId: 'map-b' }))
    expect(patrolDraftCacheKey({ ...binding, mapId: 'a:b/c' })).toContain('a%3Ab%2Fc')
    expect(() => patrolDraftCacheKey({ ...binding, domain: 0 })).toThrow()
    expect(() => patrolDraftCacheKey({ ...binding, mapId: '\n' })).toThrow()
  })
})

describe('native Web Locks plus expected revision CAS', () => {
  it('serializes reads/writes under the same scoped lock and does not reuse source times', async () => {
    const { first, storage, locks } = fixture()
    expect(first.mode).toBe('persistent_atomic')
    expect(await first.read(binding)).toBeNull()
    const saved = await first.write(binding, draft, null)
    expect(saved.revision_id).toMatch(/^[0-9a-f-]{36}$/)
    expect(saved.saved_at).toBeGreaterThan(0)
    expect((await first.read(binding))?.revision_id).toBe(saved.revision_id)
    expect(locks.keys).toEqual(Array(3).fill(patrolDraftCacheKey(binding)))
    expect(storage.writes).toBe(1)
    expect(storage.values.values().next().value).not.toContain('issued_at')
  })
  it('allows one of two concurrent editors and preserves the winning draft', async () => {
    const { first, second } = fixture()
    const initial = await first.write(binding, draft, null)
    const attempts = await Promise.allSettled([
      first.write(binding, { ...draft, routeName: 'A' }, initial.revision_id),
      second.write(binding, { ...draft, routeName: 'B' }, initial.revision_id),
    ])
    expect(attempts.filter((r) => r.status === 'fulfilled')).toHaveLength(1)
    const rejected = attempts.find((r) => r.status === 'rejected') as PromiseRejectedResult
    expect(rejected.reason).toMatchObject({ code: 'conflict' })
    expect((await second.read(binding))?.route_name).toBe('A')
    expect(rejected.reason.remote.route_name).toBe('A')
  })
  it('requires an expected absence for a new record, and preserves data after write failures', async () => {
    const { first, second, storage } = fixture()
    const initial = await first.write(binding, draft, null)
    await expect(second.write(binding, draft, null)).rejects.toMatchObject({ code: 'conflict' })
    storage.failWrite = true
    await expect(second.write(binding, { ...draft, routeName: 'unsaved' }, initial.revision_id)).rejects.toMatchObject({ code: 'write_failed' })
    expect((await first.read(binding))?.route_name).toBe(draft.routeName)
  })
  it('rejects corrupt storage instead of silently overwriting it', async () => {
    const { first, storage } = fixture()
    storage.values.set(patrolDraftCacheKey(binding), '{corrupt')
    await expect(first.read(binding)).rejects.toMatchObject({ code: 'invalid' })
    await expect(first.write(binding, draft, null)).rejects.toMatchObject({ code: 'invalid' })
    expect(storage.values.get(patrolDraftCacheKey(binding))).toBe('{corrupt')
  })
  it('isolates persistent maps and domains', async () => {
    const { first } = fixture()
    await first.write(binding, draft, null)
    expect(await first.read({ ...binding, mapId: 'map-b' })).toBeNull()
    expect(await first.read({ ...binding, domain: 123 })).toBeNull()
  })
  it('does not access localStorage at all without Web Locks', async () => {
    const storage = new StorageFixture()
    const first = new PatrolDraftCache({ storage, locks: null })
    expect(first.mode).toBe('memory_only')
    const saved = await first.write(binding, draft, null)
    expect((await first.read(binding))?.revision_id).toBe(saved.revision_id)
    expect(storage.reads).toBe(0); expect(storage.writes).toBe(0)
    expect(await new PatrolDraftCache({ storage, locks: null }).read(binding)).toBeNull()
  })
})
