/** Service identity is evidence, never inferred from a reachable URL or a shared domain. */
export const RUNTIME_ENDPOINTS = {
  station: '/api/v1/runtime', mission: '/sim-api/runtime',
  cooperation: '/coop-api/runtime', voice: '/voice-api/runtime',
} as const
export type RuntimeService = keyof typeof RUNTIME_ENDPOINTS
export type RuntimeCapability = {
  id: string
  submission: 'native_action' | 'topic_publish' | 'delegated' | 'read_only'
  task_lookup: boolean
  cancel: boolean
  event_history: 'none' | 'snapshot' | 'bounded'
}
export type RuntimeDescriptor = {
  schema_version: 1
  service: RuntimeService
  instance_id: string
  mode: 'simulation' | 'offline' | 'live' | 'unknown'
  domain: number | null
  scene_id: string | null
  episode_id: string | null
  capabilities: RuntimeCapability[]
}
export type RuntimeEntry = {
  descriptor: RuntimeDescriptor | null
  status: 'unchecked' | 'verified' | 'legacy' | 'unavailable' | 'invalid'
  error: string | null
  receivedAt: number | null
  generation: number
}
export type RuntimeSnapshot = Record<RuntimeService, RuntimeEntry>
export type Fetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const id = (value: unknown): value is string => typeof value === 'string' && value.length > 0 && value.length <= 256
const oneOf = (value: unknown, options: readonly string[]) => typeof value === 'string' && options.includes(value)

export function validateRuntimeDescriptor(value: unknown, service: RuntimeService): RuntimeDescriptor {
  if (!record(value) || value.schema_version !== 1 || value.service !== service || !id(value.instance_id)
    || !oneOf(value.mode, ['simulation', 'offline', 'live', 'unknown'])
    || !(value.domain === null || (Number.isInteger(value.domain) && Number(value.domain) >= 0 && Number(value.domain) <= 232))
    || !(value.scene_id === null || id(value.scene_id)) || !(value.episode_id === null || id(value.episode_id))
    || !Array.isArray(value.capabilities) || value.capabilities.length > 32
    || !value.capabilities.every((cap) => record(cap) && id(cap.id)
      && oneOf(cap.submission, ['native_action', 'topic_publish', 'delegated', 'read_only'])
      && typeof cap.task_lookup === 'boolean' && typeof cap.cancel === 'boolean'
      && oneOf(cap.event_history, ['none', 'snapshot', 'bounded']))
    || new Set(value.capabilities.map((cap) => cap.id)).size !== value.capabilities.length) {
    throw new Error('运行环境身份不完整或服务不匹配。')
  }
  return value as RuntimeDescriptor
}

function emptyEntry(): RuntimeEntry {
  return { descriptor: null, status: 'unchecked', error: null, receivedAt: null, generation: 0 }
}
export function emptyRuntimeSnapshot(): RuntimeSnapshot {
  return { station: emptyEntry(), mission: emptyEntry(), cooperation: emptyEntry(), voice: emptyEntry() }
}
function identity(descriptor: RuntimeDescriptor | null) {
  return descriptor && JSON.stringify([descriptor.instance_id, descriptor.domain, descriptor.mode, descriptor.scene_id, descriptor.episode_id])
}
export class RuntimeChangedError extends Error {
  readonly name = 'RuntimeChangedError'
  constructor() { super('服务实例或回合已变化；读取原任务状态，不自动重发指令。') }
}

function explicitRuntimeRejection(status: number, value: unknown): boolean {
  return status === 409 && record(value) && value.error === 'runtime_changed' && value.outcome === 'rejected'
}

/** One application-scoped registry; view mounts never create command owners. */
export class RuntimeRegistry {
  private snapshot = emptyRuntimeSnapshot()
  private listeners = new Set<() => void>()
  private refreshSequence: Record<RuntimeService, number> = { station: 0, mission: 0, cooperation: 0, voice: 0 }
  private pollOwner: symbol | null = null
  private responses = new WeakMap<Response, { service: RuntimeService; generation: number; runtimeRejection: boolean }>()
  getSnapshot = () => this.snapshot
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }

  private update(service: RuntimeService, change: Partial<RuntimeEntry>) {
    this.snapshot = { ...this.snapshot, [service]: { ...this.snapshot[service], ...change } }
    for (const listener of this.listeners) listener()
  }

  async refresh(service: RuntimeService, fetcher: Fetcher = fetch, signal?: AbortSignal) {
    const sequence = ++this.refreshSequence[service]
    try {
      const response = await fetcher(RUNTIME_ENDPOINTS[service], { cache: 'no-store', signal })
      if (signal?.aborted || sequence !== this.refreshSequence[service]) return
      if (response.status === 404) {
        this.update(service, { status: 'legacy', error: '此服务尚未提供运行身份；保持原接口校验。' })
        return
      }
      if (!response.ok) throw new Error(`运行身份读取失败（${response.status}）`)
      const value = await response.json()
      if (signal?.aborted || sequence !== this.refreshSequence[service]) return
      let descriptor: RuntimeDescriptor
      try { descriptor = validateRuntimeDescriptor(value, service) }
      catch (error) {
        this.update(service, { status: 'invalid', error: (error as Error).message })
        return
      }
      const header = response.headers?.get('X-Fishbot-Instance')
      if (!header || header !== descriptor.instance_id) {
        this.update(service, { status: 'invalid', error: '运行身份与响应来源不一致。' })
        return
      }
      const previous = this.snapshot[service]
      this.update(service, { descriptor, status: 'verified', error: null, receivedAt: Date.now(),
        generation: previous.generation + (identity(previous.descriptor) !== identity(descriptor) ? 1 : 0) })
    } catch (error) {
      if (!signal?.aborted && sequence === this.refreshSequence[service]) {
        this.update(service, { status: 'unavailable', error: error instanceof Error ? error.message : '运行身份暂不可用。' })
      }
    }
  }

  /** Polling is bounded, read-only and shared across the application. */
  start(fetcher: Fetcher = fetch, periodMs = 5000) {
    if (this.pollOwner) return () => {}
    const owner = Symbol('runtime-reader')
    this.pollOwner = owner
    const abort = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    const poll = async () => {
      const abortRequest = new AbortController()
      const services = Object.keys(RUNTIME_ENDPOINTS) as RuntimeService[]
      const pending = new Set(services)
      const timeout = setTimeout(() => {
        if (!abort.signal.aborted) for (const service of pending) this.update(service, { status: 'unavailable', error: '运行身份读取超时，等待重连。' })
        abortRequest.abort()
      }, 3000)
      const stop = () => abortRequest.abort()
      abort.signal.addEventListener('abort', stop, { once: true })
      try { await Promise.all(services.map((service) => this.refresh(service, fetcher, abortRequest.signal).finally(() => pending.delete(service)))) }
      finally { clearTimeout(timeout); abort.signal.removeEventListener('abort', stop) }
      if (!abort.signal.aborted) timer = setTimeout(poll, periodMs)
    }
    void poll()
    return () => {
      abort.abort()
      clearTimeout(timer)
      if (this.pollOwner === owner) this.pollOwner = null
    }
  }

  /** Optional instance fencing preserves old clients; it does not arbitrate competing ROS owners. */
  async request(service: RuntimeService, input: RequestInfo | URL, init?: RequestInit, fetcher: Fetcher = fetch): Promise<Response> {
    const before = this.snapshot[service]
    const headers = new Headers(init?.headers)
    if (before.descriptor) headers.set('X-Fishbot-Instance', before.descriptor.instance_id)
    const response = await fetcher(input, before.descriptor ? { ...init, headers } : init)
    let runtimeRejection = false
    if (before.descriptor && response.status === 409) {
      try { runtimeRejection = explicitRuntimeRejection(response.status, await response.clone().json()) }
      catch { /* An unreadable body cannot establish that dispatch was rejected. */ }
    }
    const after = this.snapshot[service]
    if (before.generation !== after.generation && !runtimeRejection) throw new RuntimeChangedError()
    if (before.descriptor && response.headers?.get('X-Fishbot-Instance') !== before.descriptor.instance_id) {
      // A late rejection cannot invalidate an identity already discovered after it.
      if (before.generation === after.generation) {
        this.update(service, { status: 'invalid', error: '响应来自不同服务实例；正在重新核对身份。' })
      }
      if (!runtimeRejection) throw new RuntimeChangedError()
    }
    this.responses.set(response, { service, generation: before.generation, runtimeRejection })
    return response
  }

  async json(response: Response): Promise<unknown> {
    const ticket = this.responses.get(response)
    const value: unknown = await response.json()
    if (ticket && this.snapshot[ticket.service].generation !== ticket.generation
      && !(ticket.runtimeRejection && explicitRuntimeRejection(response.status, value))) throw new RuntimeChangedError()
    return value
  }
}
export const runtimeRegistry = new RuntimeRegistry()
export const runtimeFetch = (service: RuntimeService, input: RequestInfo | URL, init?: RequestInit) => runtimeRegistry.request(service, input, init)

export const runtimeJson = (response: Response) => runtimeRegistry.json(response)

export function runtimeContextLabel(entry: RuntimeEntry): string {
  const descriptor = entry.descriptor
  if (!descriptor) return entry.status === 'legacy' ? '旧接口 · 环境身份未提供' : '环境身份待核对'
  const mode = { simulation: '仿真', offline: '离线', live: 'ROS 链路', unknown: '模式未知' }[descriptor.mode]
  const domain = descriptor.domain === null ? '域未确认' : `域 ${descriptor.domain}`
  return `${mode} · ${domain}${entry.status === 'verified' ? '' : ' · 身份待重核'}`
}
