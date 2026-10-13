export const COOPERATION_DOMAIN = 114
export const COOPERATION_POLL_MS = 1000
export const COOPERATION_STALE_MS = 3500

export type CooperationStatus = 'idle' | 'running' | 'canceling' | 'succeeded' | 'failed' | 'canceled' | 'unknown'
export type CooperationPose = { x: number; y: number; yaw: number }
export type CooperationEvent = { sequence: number; time_s: number; role: 'car' | 'arm' | 'system'; message: string }
export type CooperationState = {
  mode: 'mujoco'
  domain: number
  ready: boolean
  reason: string
  task: { id: string | null; status: CooperationStatus; stage: string; message: string; stop_reason?: string | null }
  events: CooperationEvent[]
  physics: {
    stamp: number
    car: CooperationPose & { linear_speed: number; angular_speed: number }
    arm: { q: number[]; velocity: number[] }
    cargo: { x: number; y: number; z: number; speed: number; tip_forces: number[]; tray_contact: boolean }
  } | null
  frame: { available: boolean; stamp: number | null }
  source: { scene_sha: string } | null
  nav: { ready: boolean; pose?: CooperationPose | null } | null
  stations: { dock: CooperationPose; delivery: CooperationPose } | null
}
export type CooperationReceipt = { action: 'start' | 'cancel'; taskId: string; unknown: boolean }
export type CooperationSnapshot = {
  state: CooperationState | null
  receivedAt: number | null
  connectionError: string | null
  actionError: string | null
  pending: 'start' | 'cancel' | null
  receipt: CooperationReceipt | null
  ownedTaskId: string | null
}
export const EMPTY_COOPERATION_SNAPSHOT: CooperationSnapshot = {
  state: null, receivedAt: null, connectionError: null, actionError: null,
  pending: null, receipt: null, ownedTaskId: null,
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
function finite(value: unknown): value is number { return typeof value === 'number' && Number.isFinite(value) }
function pose(value: unknown): boolean { return record(value) && finite(value.x) && finite(value.y) && finite(value.yaw) }
function numbers(value: unknown): value is number[] { return Array.isArray(value) && value.every(finite) }

export function validateCooperationState(value: unknown): CooperationState {
  if (!record(value) || value.mode !== 'mujoco' || value.domain !== COOPERATION_DOMAIN
    || typeof value.ready !== 'boolean' || typeof value.reason !== 'string'
    || !record(value.task) || !(value.task.id === null || (typeof value.task.id === 'string' && value.task.id.length > 0))
    || typeof value.task.status !== 'string' || !['idle', 'running', 'canceling', 'succeeded', 'failed', 'canceled', 'unknown'].includes(value.task.status)
    || typeof value.task.stage !== 'string' || typeof value.task.message !== 'string'
    || !(value.task.stop_reason == null || typeof value.task.stop_reason === 'string')
    || !Array.isArray(value.events) || !value.events.every((event) => record(event)
      && Number.isInteger(event.sequence) && finite(event.sequence) && event.sequence >= 0
      && finite(event.time_s) && event.time_s >= 0 && typeof event.role === 'string' && ['car', 'arm', 'system'].includes(event.role) && typeof event.message === 'string')
    || !record(value.frame) || typeof value.frame.available !== 'boolean'
    || !(value.frame.stamp === null || (finite(value.frame.stamp) && value.frame.stamp >= 0))
    || (value.source !== null && (!record(value.source) || typeof value.source.scene_sha !== 'string'))
    || (value.nav !== null && (!record(value.nav) || typeof value.nav.ready !== 'boolean' || (value.nav.pose != null && !pose(value.nav.pose))))
    || (value.stations != null && (!record(value.stations) || !pose(value.stations.dock) || !pose(value.stations.delivery)))) {
    throw new Error('协同服务状态不完整或 ROS 域不匹配，等待有效反馈。')
  }
  if (value.physics !== null) {
    const physics = value.physics
    if (!record(physics) || !finite(physics.stamp) || physics.stamp < 0
      || !record(physics.car) || !pose(physics.car) || !finite(physics.car.linear_speed) || !finite(physics.car.angular_speed)
      || !record(physics.arm) || !numbers(physics.arm.q) || !numbers(physics.arm.velocity)
      || physics.arm.q.length !== physics.arm.velocity.length
      || !record(physics.cargo) || !finite(physics.cargo.x) || !finite(physics.cargo.y) || !finite(physics.cargo.z)
      || !finite(physics.cargo.speed) || physics.cargo.speed < 0 || !numbers(physics.cargo.tip_forces)
      || typeof physics.cargo.tray_contact !== 'boolean') {
      throw new Error('共享场景的物理反馈不完整，暂停操作并等待有效反馈。')
    }
  }
  return value as unknown as CooperationState
}

export const COOPERATION_STAGES = [
  { key: 'car_to_dock', label: '小车驶向工位', role: 'car' },
  { key: 'dock_stopped', label: '确认小车停稳', role: 'car' },
  { key: 'arm_grasp', label: '机械臂抓取', role: 'arm' },
  { key: 'arm_lift', label: '抬起货物', role: 'arm' },
  { key: 'arm_transport', label: '移向小车托盘', role: 'arm' },
  { key: 'arm_release', label: '释放货物', role: 'arm' },
  { key: 'cargo_settle', label: '等待货物放稳', role: 'arm' },
  { key: 'arm_retreat', label: '机械臂退出', role: 'arm' },
  { key: 'car_to_delivery', label: '小车运输', role: 'car' },
  { key: 'delivery_stopped', label: '交付点停稳', role: 'car' },
] as const

export function cooperationStageLabel(stage: string | undefined): string {
  if (!stage || stage === 'idle') return '等待开始'
  return COOPERATION_STAGES.find((item) => item.key === stage)?.label ?? stage
}
export function cooperationStatusLabel(status: CooperationStatus | undefined): string {
  return { idle: '等待开始', running: '协同进行中', canceling: '正在取消，等待停稳',
    succeeded: '装货运输完成', failed: '任务失败', canceled: '任务已取消', unknown: '任务状态未知' }[status ?? 'idle']
}
export function cooperationConnected(snapshot: CooperationSnapshot, now = Date.now()): boolean {
  return !!snapshot.state && !snapshot.connectionError && snapshot.receivedAt !== null
    && now - snapshot.receivedAt < COOPERATION_STALE_MS
}
export function cooperationCanStart(snapshot: CooperationSnapshot, now = Date.now()): boolean {
  return cooperationConnected(snapshot, now) && snapshot.state!.ready && !snapshot.pending && !snapshot.receipt
    && ['idle', 'succeeded', 'failed', 'canceled'].includes(snapshot.state!.task.status)
}
export function cooperationCanCancel(snapshot: CooperationSnapshot, now = Date.now()): boolean {
  return cooperationConnected(snapshot, now) && !snapshot.pending && !snapshot.receipt
    && !!snapshot.ownedTaskId && snapshot.ownedTaskId === snapshot.state!.task.id
    && snapshot.state!.task.status === 'running'
}

class CooperationRequestError extends Error {
  readonly rejected: boolean
  constructor(message: string, rejected: boolean) { super(message); this.rejected = rejected }
}
type Fetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
type ReceiptStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
const STORAGE_KEY = 'fishbot.cooperation.receipt.v1'
type ControllerOptions = { fetcher?: Fetcher; now?: () => number; taskId?: () => string; storage?: ReceiptStorage | null }

/** Only user actions send POST. Polling reconciles the same task and never resends a mutation. */
export class CooperationController {
  private snapshot: CooperationSnapshot = { ...EMPTY_COOPERATION_SNAPSHOT }
  private listeners = new Set<(value: CooperationSnapshot) => void>()
  private fetcher: Fetcher
  private now: () => number
  private taskId: () => string
  private storage: ReceiptStorage | null
  private reading: Promise<void> | null = null
  private requestVersion = 0

  constructor(options: ControllerOptions = {}) {
    this.fetcher = options.fetcher ?? ((input, init) => fetch(input, init))
    this.now = options.now ?? Date.now
    this.taskId = options.taskId ?? (() => crypto.randomUUID())
    this.storage = options.storage ?? null
    try {
      const raw = this.storage?.getItem(STORAGE_KEY)
      const stored: unknown = raw ? JSON.parse(raw) : null
      if (record(stored) && typeof stored.ownedTaskId === 'string') {
        this.snapshot.ownedTaskId = stored.ownedTaskId
        if (record(stored.receipt) && ['start', 'cancel'].includes(String(stored.receipt.action))
          && stored.receipt.taskId === stored.ownedTaskId && typeof stored.receipt.unknown === 'boolean') {
          this.snapshot.receipt = stored.receipt as CooperationReceipt
        }
      }
    } catch { /* Storage is optional. The in-memory receipt remains authoritative for this page. */ }
  }
  getSnapshot = (): CooperationSnapshot => this.snapshot
  subscribe = (listener: (value: CooperationSnapshot) => void): (() => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }
  private update(patch: Partial<CooperationSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...patch }
    try {
      if (this.snapshot.ownedTaskId) this.storage?.setItem(STORAGE_KEY, JSON.stringify({
        ownedTaskId: this.snapshot.ownedTaskId, receipt: this.snapshot.receipt,
      }))
      else this.storage?.removeItem(STORAGE_KEY)
    } catch { /* A blocked browser store does not clear the active in-memory receipt. */ }
    this.listeners.forEach((listener) => listener(this.snapshot))
  }
  private async request(path: string, body?: object): Promise<unknown> {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 5000)
    try {
      const response = await this.fetcher(`/coop-api/${path}`, {
        method: body ? 'POST' : 'GET', cache: 'no-store', signal: controller.signal,
        ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
      })
      let value: unknown
      try { value = await response.json() } catch { throw new CooperationRequestError('协同服务未返回有效 JSON。', false) }
      if (!response.ok) {
        const message = record(value) && (typeof value.reason === 'string' || typeof value.error === 'string')
          ? String(value.reason ?? value.error) : `协同服务请求失败（HTTP ${response.status}）。`
        throw new CooperationRequestError(message, record(value) && value.outcome === 'rejected')
      }
      return value
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') throw new CooperationRequestError('协同服务请求超时。', false)
      throw error
    } finally { clearTimeout(timeout) }
  }
  refresh = (): Promise<void> => {
    if (this.reading) return this.reading
    const version = this.requestVersion
    const taskId = this.snapshot.receipt?.taskId
    this.reading = (async () => {
      try {
        const value = validateCooperationState(await this.request(`state${taskId ? `?task_id=${encodeURIComponent(taskId)}` : ''}`))
        if (version !== this.requestVersion) return
        const receipt = this.snapshot.receipt
        const resolved = !!receipt && value.task.id === receipt.taskId
          && (receipt.action === 'start' ? value.task.status !== 'idle' && value.task.status !== 'unknown'
            : ['canceled', 'succeeded', 'failed'].includes(value.task.status))
        this.update({ state: value, receivedAt: this.now(), connectionError: null,
          ...(resolved ? { receipt: null, actionError: null } : {}) })
      } catch (error) {
        if (version === this.requestVersion) this.update({ connectionError: error instanceof Error ? error.message : '协同服务暂时无法连接。' })
      } finally { this.reading = null }
    })()
    return this.reading
  }
  act = async (action: 'start' | 'cancel'): Promise<void> => {
    if (action === 'start' ? !cooperationCanStart(this.snapshot, this.now()) : !cooperationCanCancel(this.snapshot, this.now())) return
    const taskId = action === 'start' ? this.taskId() : this.snapshot.ownedTaskId!
    ++this.requestVersion
    this.update({ pending: action, actionError: null, ownedTaskId: taskId,
      receipt: { action, taskId, unknown: true } })
    try {
      const value = await this.request(action, { task_id: taskId, issued_at: this.now() / 1000 })
      if (!record(value) || value.task_id !== taskId) throw new CooperationRequestError('协同服务回执的任务编号不匹配。', false)
      this.update({ receipt: { action, taskId, unknown: false } })
    } catch (error) {
      const rejected = error instanceof CooperationRequestError && error.rejected
      const message = error instanceof Error ? error.message : '请求未收到明确回执。'
      this.update({ actionError: rejected ? message : `${message} 回执未知，正在读取原任务；请勿重复派发。`,
        ...(rejected ? { receipt: null } : {}) })
    } finally {
      this.update({ pending: null })
      await this.refresh()
    }
  }
}

export type CooperationFrameObservation = { stamp: number; changedAt: number; loadedStamp: number | null; error: boolean }
export function cooperationFrameLabel(state: CooperationState | null, frame: CooperationFrameObservation | null, connected: boolean, now: number): string {
  if (!state?.frame.available || state.frame.stamp === null) return '等待相机画面'
  if (frame?.error) return '相机画面读取失败'
  if (!frame || frame.loadedStamp !== state.frame.stamp) return '正在读取相机画面'
  if (!connected || now - frame.changedAt >= COOPERATION_STALE_MS) return '画面已过期'
  return '相机画面持续更新'
}
