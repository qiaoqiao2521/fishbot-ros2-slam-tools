import { useCallback, useEffect, useMemo, useSyncExternalStore } from 'react'
import { PatrolDraftCache, PatrolDraftCacheError, contentFromDraftRecord, emptyPatrolDraft, patrolDraftCacheKey, validatePatrolDraft,
  type DraftCache, type DraftCacheMode, type PatrolDraftContent, type PatrolDraftRecord, type PatrolDraftScope } from '@/lib/patrol-draft-cache'

export type DraftValidation = 'unvalidated' | 'stale' | 'validated'
export type PatrolDraftCacheOptions = {
  domain: number; mapId: string | null | undefined; rulesRevision: number | null | undefined
  connected: boolean; ready: boolean; cache?: DraftCache
}
export type PatrolDraftCacheState = {
  scopeKey: string | null; draft: PatrolDraftContent; loaded: boolean; loading: boolean; saving: boolean
  rulesRevision: number | null
  revisionId: string | null; mode: DraftCacheMode; validation: DraftValidation; validationToken: string
  conflict: boolean; message: string; error: string | null
}
type DraftUpdate = PatrolDraftContent | ((previous: PatrolDraftContent) => PatrolDraftContent)
type Context = {
  key: string; scope: PatrolDraftScope; generation: number; rulesRevision: number | null; connected: boolean; ready: boolean
  draft: PatrolDraftContent; version: number; persistedVersion: number; draftRulesRevision: number | null
  persistedRulesRevision: number | null; revisionId: string | null; confirmedToken: string | null
  loaded: boolean; loading: boolean; saving: boolean; conflict: boolean; message: string; queue: Promise<void>; readEpoch: number
  cacheUsable: boolean; error: string | null
}
const freezeDraft = (draft: PatrolDraftContent): PatrolDraftContent => {
  draft.waypoints.forEach(Object.freeze); Object.freeze(draft.waypoints); Object.freeze(draft)
  return draft
}
const validRulesRevision = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
const blankState = (mode: DraftCacheMode, scopeKey: string | null = null): PatrolDraftCacheState => ({
  scopeKey, draft: freezeDraft(emptyPatrolDraft()), loaded: false, loading: false, saving: false, rulesRevision: null,
  revisionId: null, mode, validation: 'unvalidated', validationToken: '', conflict: false, error: null,
  message: mode === 'memory_only' ? '当前仅保留本页内存草稿；没有持久保存或跨标签页原子写保证。' : '等待地图与规则身份读回后恢复草稿。',
})
let defaultCache: DraftCache | null = null
const browserCache = (): DraftCache => defaultCache ??= new PatrolDraftCache()

/** Small external store so asynchronous cache ordering can be tested without a simulated React lifecycle. */
export class PatrolDraftController {
  private readonly cache: DraftCache
  private context: Context | null = null
  private generation = 0
  private snapshot: PatrolDraftCacheState
  private readonly listeners = new Set<() => void>()
  constructor(cache: DraftCache = browserCache()) { this.cache = cache; this.snapshot = blankState(cache.mode) }
  readonly subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener) }
  readonly getSnapshot = (): PatrolDraftCacheState => this.snapshot
  private token(context: Context): string { return `${context.key}:g${context.generation}:v${context.version}:r${context.rulesRevision}` }
  private current(context: Context): boolean { return this.context === context }
  private emit(): void {
    const context = this.context
    if (!context) this.snapshot = blankState(this.cache.mode)
    else {
      const token = this.token(context)
      const stale = context.draft.waypoints.length > 0 && context.draftRulesRevision !== context.rulesRevision
      this.snapshot = {
        scopeKey: context.key, draft: freezeDraft(structuredClone(context.draft)), loaded: context.loaded,
        rulesRevision: context.rulesRevision,
        loading: context.loading, saving: context.saving, revisionId: context.revisionId, mode: context.cacheUsable ? this.cache.mode : 'memory_only',
        validation: stale ? 'stale' : context.confirmedToken === token ? 'validated' : 'unvalidated',
        validationToken: token, conflict: context.conflict, message: context.message, error: context.error,
      }
    }
    this.listeners.forEach((listener) => listener())
  }
  private enqueue(context: Context, work: () => Promise<void>): void {
    context.queue = context.queue.then(async () => { if (this.current(context)) await work() })
      .catch((error: unknown) => {
        if (!this.current(context)) return
        this.memoryFallback(context, error)
      })
  }
  private invalidateConfirmation(context: Context): void {
    context.confirmedToken = context.draft.waypoints.length === 0 && context.loaded ? this.token(context) : null
  }
  private memoryFallback(context: Context, error: unknown): void {
    context.error = error instanceof Error ? error.message : '草稿缓存操作失败。'
    context.cacheUsable = false; context.loading = false; context.saving = false
    // Do not replace or overwrite malformed/blocked storage. Keep an editable page-local draft.
    context.loaded = true
    this.invalidateConfirmation(context)
    context.message = '草稿缓存未恢复或未保存；当前仅保留本页内存，可继续编辑，不会覆盖已有缓存。'
    this.emit()
  }
  bind(options: Omit<PatrolDraftCacheOptions, 'cache'>): void {
    if (!options.mapId) {
      if (this.context) { this.context = null; this.generation++; this.emit() }
      return
    }
    const scope = { domain: options.domain, mapId: options.mapId }, key = patrolDraftCacheKey(scope)
    const rulesRevision = validRulesRevision(options.rulesRevision) ? options.rulesRevision : null
    let context = this.context
    const changedScope = context?.key !== key
    if (changedScope) {
      context = { key, scope, generation: ++this.generation, rulesRevision, connected: options.connected, ready: options.ready,
        draft: emptyPatrolDraft(), version: 0, persistedVersion: 0, draftRulesRevision: rulesRevision,
        persistedRulesRevision: rulesRevision, revisionId: null, confirmedToken: null,
        loaded: false, loading: false, saving: false, conflict: false, message: '', queue: Promise.resolve(), readEpoch: 0,
        cacheUsable: true, error: null }
      this.context = context
    }
    if (!context) return
    const reconnect = !changedScope && !context.connected && options.connected
    const becameReady = !changedScope && !context.ready && options.ready
    const rulesChanged = context.rulesRevision !== rulesRevision
    if (!options.connected || !options.ready || rulesChanged) { context.readEpoch++; context.loading = false }
    context.connected = options.connected; context.ready = options.ready; context.rulesRevision = rulesRevision
    if (!options.connected || rulesChanged) this.invalidateConfirmation(context)
    if (!options.connected) context.message = '连接已断开，草稿仍保留；重连后核验缓存版本，不会自动派发。'
    else if (rulesChanged && context.draft.waypoints.length) context.message = '规则版本已变化，保留航点；请显式重新核验。'
    this.emit()
    if (options.connected && options.ready && rulesRevision !== null && (changedScope || reconnect || becameReady || rulesChanged || !context.loaded)) {
      this.read(context, false)
    }
  }
  private adopt(context: Context, record: PatrolDraftRecord | null): void {
    context.draft = record ? contentFromDraftRecord(record) : emptyPatrolDraft()
    context.version++; context.persistedVersion = context.version
    context.revisionId = record?.revision_id ?? null
    context.draftRulesRevision = record?.rules_revision ?? context.rulesRevision
    context.persistedRulesRevision = context.draftRulesRevision
    context.loaded = true; context.conflict = false
    this.invalidateConfirmation(context)
    context.message = record ? '已恢复草稿，尚未派发；请核验地图规则与航点。' : '没有已保存草稿，可选择新航点。'
    if (this.cache.mode === 'memory_only') context.message += ' 当前仅保留内存，刷新页面不会保证恢复。'
  }
  private read(context: Context, replace: boolean): void {
    const epoch = ++context.readEpoch
    context.loading = true; this.invalidateConfirmation(context); this.emit()
    this.enqueue(context, async () => {
      if (epoch !== context.readEpoch) return
      if (!context.connected || !context.ready || context.rulesRevision === null) { context.loading = false; this.emit(); return }
      if (!context.cacheUsable && !replace) { context.loading = false; this.emit(); return }
      const expectedRevisionId = context.revisionId
      let record: PatrolDraftRecord | null
      try { record = await this.cache.read(context.scope) }
      catch (error) {
        if (this.current(context) && epoch === context.readEpoch) this.memoryFallback(context, error)
        return
      }
      if (!this.current(context) || epoch !== context.readEpoch) return
      context.loading = false
      if (!context.connected || !context.ready) { this.emit(); return }
      if (replace || !context.loaded) { context.cacheUsable = true; context.error = null; this.adopt(context, record) }
      else if ((record?.revision_id ?? null) !== expectedRevisionId) {
        context.conflict = true; context.confirmedToken = null
        context.message = '其他页面已更新草稿；本页航点仍保留，请显式读取缓存后再核验。'
      } else {
        this.invalidateConfirmation(context)
        context.message = context.draft.waypoints.length ? '缓存 revision_id 已核对；请显式核验航点后再派发。' : '空草稿已核对，没有动作需要恢复。'
      }
      this.emit()
    })
  }
  readonly reloadCache = (): void => {
    const context = this.context
    if (!context || !context.connected || !context.ready || context.rulesRevision === null) return
    this.read(context, true)
  }
  readonly setDraft = (update: DraftUpdate): void => {
    const context = this.context
    if (!context || !context.loaded) return
    try {
      const proposed = typeof update === 'function' ? update(structuredClone(context.draft)) : update
      const next = validatePatrolDraft(proposed)
      if (JSON.stringify(next) === JSON.stringify(context.draft)) return
      context.draft = next; context.version++
      if (context.draftRulesRevision === null) context.draftRulesRevision = context.rulesRevision
      this.invalidateConfirmation(context)
      context.message = context.conflict ? '缓存存在版本冲突；保留本页新编辑，未覆盖其他页面。' : '草稿已更新；尚未派发机器人任务。'
      this.emit(); this.persist(context)
    } catch (error) {
      context.message = error instanceof Error ? error.message : '草稿无效，原内容已保留。'; this.emit()
    }
  }
  private persist(context: Context): void {
    this.enqueue(context, async () => {
      if (!context.loaded || !context.cacheUsable || context.conflict || context.draftRulesRevision === null
        || context.persistedVersion === context.version && context.persistedRulesRevision === context.draftRulesRevision) return
      const version = context.version, rulesRevision = context.draftRulesRevision, draft = structuredClone(context.draft)
      context.saving = true; this.emit()
      try {
        const record = await this.cache.write({ ...context.scope, rulesRevision }, draft, context.revisionId)
        if (!this.current(context)) return
        context.revisionId = record.revision_id; context.persistedVersion = version; context.persistedRulesRevision = rulesRevision
        context.message = this.cache.mode === 'persistent_atomic' ? '草稿已缓存；没有缓存或重放动作请求。' : '草稿仅保存在内存；未写入持久缓存。'
      } catch (error) {
        if (!this.current(context)) return
        context.confirmedToken = null
        if (error instanceof PatrolDraftCacheError && error.code === 'conflict') {
          context.conflict = true; context.message = error.message
        } else this.memoryFallback(context, error)
      } finally {
        if (this.current(context)) { context.saving = false; this.emit() }
      }
    })
  }
  /** Caller performs geometry validation; this only fences that explicit result to the unchanged draft. */
  readonly confirmValidated = (token: string): boolean => {
    const context = this.context
    if (!context || !context.loaded || context.loading || context.conflict || !context.connected || !context.ready
      || context.rulesRevision === null || token !== this.token(context)) return false
    context.draftRulesRevision = context.rulesRevision; context.confirmedToken = token
    context.message = '当前草稿已显式核验；实际任务仍由原 ROS owner 接收与裁决。'
    this.emit(); this.persist(context)
    return true
  }
  /** Test/closeout observation only; awaiting this never dispatches a robot operation. */
  async whenIdle(): Promise<void> {
    const context = this.context
    if (!context) return
    let pending: Promise<void>
    do { pending = context.queue; await pending } while (this.current(context) && pending !== context.queue)
  }
  detach(): void { this.context = null; this.generation++; this.emit() }
}

export function usePatrolDraftCache(options: PatrolDraftCacheOptions) {
  const { domain, mapId, rulesRevision, connected, ready } = options
  const controller = useMemo(() => new PatrolDraftController(options.cache ?? browserCache()), [options.cache])
  const observed = useSyncExternalStore(controller.subscribe, controller.getSnapshot, controller.getSnapshot)
  const scopeKey = options.mapId ? patrolDraftCacheKey({ domain: options.domain, mapId: options.mapId }) : null
  // Render a correctly scoped empty value immediately; never expose the previous map until an effect runs.
  const fallback = useMemo(() => blankState(options.cache?.mode ?? browserCache().mode, scopeKey), [options.cache, scopeKey])
  const scoped = observed.scopeKey === scopeKey ? observed : fallback
  const bindingCurrent = observed.scopeKey === scopeKey && observed.rulesRevision === rulesRevision
  const state = bindingCurrent && connected ? scoped : {
    ...scoped, validation: scoped.draft.waypoints.length && observed.rulesRevision !== rulesRevision ? 'stale' as const : 'unvalidated' as const,
    validationToken: '',
  }
  const setDraft = useCallback((update: DraftUpdate) => {
    if (controller.getSnapshot().scopeKey === scopeKey) controller.setDraft(update)
  }, [controller, scopeKey])
  const confirmValidated = useCallback((token: string): boolean => {
    const current = controller.getSnapshot()
    return connected && ready && current.scopeKey === scopeKey && current.rulesRevision === rulesRevision
      ? controller.confirmValidated(token) : false
  }, [controller, connected, ready, scopeKey, rulesRevision])
  const reloadCache = useCallback(() => {
    if (controller.getSnapshot().scopeKey === scopeKey) controller.reloadCache()
  }, [controller, scopeKey])
  useEffect(() => {
    controller.bind({ domain, mapId, rulesRevision, connected, ready })
  }, [controller, domain, mapId, rulesRevision, connected, ready])
  useEffect(() => () => controller.detach(), [controller])
  return { ...state, setDraft, confirmValidated, reloadCache }
}
