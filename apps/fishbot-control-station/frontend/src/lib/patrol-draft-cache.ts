/** Draft persistence only. This module cannot send, cache or replay robot actions. */
export type PatrolDraftPose = { x: number; y: number; yaw: number }
export type PatrolDraftContent = { waypoints: PatrolDraftPose[]; returnHome: boolean; routeName: string }
export type PatrolDraft = PatrolDraftContent
export type PatrolDraftScope = { domain: number; mapId: string }
export type PatrolDraftBinding = PatrolDraftScope & { rulesRevision: number }
export type PatrolDraftRecord = {
  version: 1; domain: number; map_id: string; revision_id: string; rules_revision: number; saved_at: number
  waypoints: PatrolDraftPose[]; return_home: boolean; route_name: string
}
export type DraftCacheMode = 'persistent_atomic' | 'memory_only'
export type DraftStorage = Pick<Storage, 'getItem' | 'setItem'>
export interface DraftLocks { request<T>(key: string, callback: () => T | Promise<T>): Promise<T> }
export interface DraftCache {
  readonly mode: DraftCacheMode
  read(scope: PatrolDraftScope): Promise<PatrolDraftRecord | null>
  write(binding: PatrolDraftBinding, draft: PatrolDraftContent, expectedRevisionId: string | null): Promise<PatrolDraftRecord>
}
export const MAX_DRAFT_BYTES = 16384
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const RECORD_KEYS = ['version', 'domain', 'map_id', 'revision_id', 'rules_revision', 'saved_at', 'waypoints', 'return_home', 'route_name']
const hasControlCharacter = (value: string): boolean => [...value].some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)
export class PatrolDraftCacheError extends Error {
  readonly code: 'invalid' | 'conflict' | 'read_failed' | 'write_failed'
  readonly remote: PatrolDraftRecord | null
  constructor(code: PatrolDraftCacheError['code'], message: string, remote: PatrolDraftRecord | null = null) {
    super(message); this.name = 'PatrolDraftCacheError'; this.code = code; this.remote = remote ? structuredClone(remote) : null
  }
}
const invalid = (message: string): never => { throw new PatrolDraftCacheError('invalid', message) }
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid('草稿结构无效。')
  return value as Record<string, unknown>
}
function exactKeys(value: Record<string, unknown>, allowed: string[]): void {
  if (Object.keys(value).length !== allowed.length || Object.keys(value).some((key) => !allowed.includes(key))) invalid('草稿含未支持的字段。')
}
function number(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return invalid('草稿坐标或时间不是有限数值。')
  return value
}
function revision(value: unknown): number {
  const result = number(value)
  if (!Number.isSafeInteger(result) || result < 0) return invalid('规则版本无效。')
  return result
}
function scopeValue(scope: PatrolDraftScope): PatrolDraftScope {
  if (!Number.isInteger(scope.domain) || scope.domain < 1 || scope.domain > 232) return invalid('草稿仿真域必须为 1–232。')
  if (typeof scope.mapId !== 'string' || !scope.mapId.trim() || scope.mapId.length > 128 || hasControlCharacter(scope.mapId)) return invalid('草稿地图标识无效。')
  return { domain: scope.domain, mapId: scope.mapId }
}
export function patrolDraftCacheKey(scope: PatrolDraftScope): string {
  const value = scopeValue(scope)
  return `fishbot.patrol-draft.v1:d${value.domain}:m${encodeURIComponent(value.mapId)}`
}
export function validatePatrolDraft(value: unknown): PatrolDraftContent {
  const draft = object(value)
  exactKeys(draft, ['waypoints', 'returnHome', 'routeName'])
  if (!Array.isArray(draft.waypoints) || draft.waypoints.length > 12) return invalid('草稿最多支持 12 个航点。')
  const waypoints = draft.waypoints.map((item) => {
    const point = object(item); exactKeys(point, ['x', 'y', 'yaw'])
    return { x: number(point.x), y: number(point.y), yaw: number(point.yaw) }
  })
  if (typeof draft.returnHome !== 'boolean') return invalid('草稿返航开关无效。')
  if (typeof draft.routeName !== 'string' || draft.routeName.length > 80 || hasControlCharacter(draft.routeName)) return invalid('草稿路线名称过长或含控制字符。')
  return { waypoints, returnHome: draft.returnHome, routeName: draft.routeName }
}
export function decodePatrolDraft(raw: string, scope: PatrolDraftScope): PatrolDraftRecord {
  scopeValue(scope)
  if (typeof raw !== 'string' || new TextEncoder().encode(raw).byteLength > MAX_DRAFT_BYTES) return invalid('草稿缓存超过大小上限。')
  let parsed: unknown
  try { parsed = JSON.parse(raw) } catch { return invalid('草稿缓存不是有效 JSON。') }
  const value = object(parsed); exactKeys(value, RECORD_KEYS)
  if (value.version !== 1 || value.domain !== scope.domain || value.map_id !== scope.mapId) return invalid('草稿缓存的版本、域或地图不匹配。')
  if (typeof value.revision_id !== 'string' || !UUID.test(value.revision_id)) return invalid('草稿 revision_id 无效。')
  const rulesRevision = revision(value.rules_revision), savedAt = number(value.saved_at)
  if (savedAt < 0) return invalid('草稿缓存保存时间无效。')
  const content = validatePatrolDraft({ waypoints: value.waypoints, returnHome: value.return_home, routeName: value.route_name })
  return { version: 1, domain: scope.domain, map_id: scope.mapId, revision_id: value.revision_id, rules_revision: rulesRevision,
    saved_at: savedAt, waypoints: content.waypoints, return_home: content.returnHome, route_name: content.routeName }
}
export const emptyPatrolDraft = (): PatrolDraftContent => ({ waypoints: [], returnHome: true, routeName: '' })
export function contentFromDraftRecord(record: PatrolDraftRecord): PatrolDraftContent {
  return validatePatrolDraft({ waypoints: record.waypoints, returnHome: record.return_home, routeName: record.route_name })
}
function browserStorage(): DraftStorage | null {
  try { return typeof localStorage === 'undefined' ? null : localStorage } catch { return null }
}
function browserLocks(): DraftLocks | null {
  if (typeof navigator === 'undefined' || !navigator.locks) return null
  return { request: (key, callback) => navigator.locks.request(key, callback) }
}
export class PatrolDraftCache implements DraftCache {
  readonly mode: DraftCacheMode
  private readonly storage: DraftStorage | null
  private readonly locks: DraftLocks | null
  private readonly memory = new Map<string, string>()
  private readonly uuid: () => string
  private readonly nowSeconds: () => number
  constructor(options: { storage?: DraftStorage | null; locks?: DraftLocks | null; uuid?: () => string; nowSeconds?: () => number } = {}) {
    this.storage = options.storage === undefined ? browserStorage() : options.storage
    this.locks = options.locks === undefined ? browserLocks() : options.locks
    this.mode = this.storage && this.locks ? 'persistent_atomic' : 'memory_only'
    this.uuid = options.uuid ?? (() => crypto.randomUUID())
    this.nowSeconds = options.nowSeconds ?? (() => Date.now() / 1000)
  }
  private readUnlocked(scope: PatrolDraftScope, key: string): PatrolDraftRecord | null {
    let raw: string | null | undefined
    try { raw = this.mode === 'persistent_atomic' ? this.storage!.getItem(key) : this.memory.get(key) }
    catch { throw new PatrolDraftCacheError('read_failed', '无法读取草稿缓存；未覆盖已有数据。') }
    return raw == null ? null : decodePatrolDraft(raw, scope)
  }
  private async locked<T>(key: string, callback: () => T): Promise<T> {
    if (this.mode === 'persistent_atomic') return this.locks!.request(key, callback)
    // This branch never reads or writes localStorage, and makes no cross-tab guarantee.
    return callback()
  }
  async read(scope: PatrolDraftScope): Promise<PatrolDraftRecord | null> {
    const bound = scopeValue(scope), key = patrolDraftCacheKey(bound)
    return this.locked(key, () => this.readUnlocked(bound, key))
  }
  async write(binding: PatrolDraftBinding, draft: PatrolDraftContent, expectedRevisionId: string | null): Promise<PatrolDraftRecord> {
    const bound = scopeValue(binding), key = patrolDraftCacheKey(bound)
    const content = validatePatrolDraft(draft), rulesRevision = revision(binding.rulesRevision)
    if (expectedRevisionId !== null && (typeof expectedRevisionId !== 'string' || !UUID.test(expectedRevisionId))) return invalid('预期草稿 revision_id 无效。')
    return this.locked(key, () => {
      const current = this.readUnlocked(bound, key)
      if ((current?.revision_id ?? null) !== expectedRevisionId) throw new PatrolDraftCacheError('conflict', '其他页面已更新此草稿；保留本页内容，请显式读取后再编辑。', current)
      const record: PatrolDraftRecord = { version: 1, domain: bound.domain, map_id: bound.mapId,
        revision_id: this.uuid(), rules_revision: rulesRevision, saved_at: this.nowSeconds(),
        waypoints: content.waypoints, return_home: content.returnHome, route_name: content.routeName }
      const serialized = JSON.stringify(record)
      const checked = decodePatrolDraft(serialized, bound)
      if (checked.revision_id === current?.revision_id) return invalid('新草稿必须使用不同的 revision_id。')
      try {
        if (this.mode === 'persistent_atomic') this.storage!.setItem(key, serialized)
        else this.memory.set(key, serialized)
      } catch { throw new PatrolDraftCacheError('write_failed', '草稿缓存写入失败；本页草稿仍保留，未确认持久保存。') }
      return checked
    })
  }
}
