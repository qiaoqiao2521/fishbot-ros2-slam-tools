export const COOPERATION_DOMAIN = 114
export const COOPERATION_POLL_MS = 1000
export const COOPERATION_STALE_MS = 3500

export type CooperationStatus = 'idle' | 'running' | 'canceling' | 'succeeded' | 'failed' | 'canceled' | 'unknown'
export type CooperationPose = { x: number; y: number; yaw: number }
export type CooperationEvent = { sequence: number; time_s: number; role: 'car' | 'arm' | 'system'; message: string }
export type CooperationTask = { id: string | null; status: CooperationStatus; stage: string; message: string; stop_reason?: string | null }
export type CooperationResetStatus = 'pending' | 'succeeded' | 'failed' | 'unknown'
export type CooperationResetRecord = {
  request_id: string; episode_id: string; status: CooperationResetStatus; new_episode_id: string | null; message: string
}
export type CooperationHistory = { episode_id: string; task: CooperationTask; events: CooperationEvent[]; completed_at: string | number }
export type CooperationState = {
  mode: 'mujoco'
  domain: number
  ready: boolean
  reason: string
  episode_id?: string
  reset?: { available: boolean; reason: string; pending: boolean;
    last: { request_id: string; status: CooperationResetStatus; from_episode: string; to_episode: string | null; message: string } | null }
  history?: CooperationHistory[]
  task: CooperationTask
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
export type CooperationResetReceipt = { requestId: string; fromEpisode: string; unknown: boolean }
export type CooperationSnapshot = {
  state: CooperationState | null
  receivedAt: number | null
  connectionError: string | null
  actionError: string | null
  pending: 'start' | 'cancel' | 'reset' | null
  receipt: CooperationReceipt | null
  resetReceipt: CooperationResetReceipt | null
  ownedTaskId: string | null
}
export const EMPTY_COOPERATION_SNAPSHOT: CooperationSnapshot = {
  state: null, receivedAt: null, connectionError: null, actionError: null,
  pending: null, receipt: null, resetReceipt: null, ownedTaskId: null,
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
function finite(value: unknown): value is number { return typeof value === 'number' && Number.isFinite(value) }
function pose(value: unknown): boolean { return record(value) && finite(value.x) && finite(value.y) && finite(value.yaw) }
function numbers(value: unknown): value is number[] { return Array.isArray(value) && value.every(finite) }
function identity(value: unknown): value is string { return typeof value === 'string' && value.length > 0 }
function resetStatus(value: unknown): value is CooperationResetStatus { return typeof value === 'string' && ['pending', 'succeeded', 'failed', 'unknown'].includes(value) }
function validTask(value: unknown): boolean {
  return record(value) && (value.id === null || identity(value.id)) && typeof value.status === 'string'
    && ['idle', 'running', 'canceling', 'succeeded', 'failed', 'canceled', 'unknown'].includes(value.status)
    && typeof value.stage === 'string' && typeof value.message === 'string'
    && (value.stop_reason == null || typeof value.stop_reason === 'string')
}
function validEvents(value: unknown): boolean {
  return Array.isArray(value) && value.every((event) => record(event)
    && Number.isInteger(event.sequence) && finite(event.sequence) && event.sequence >= 0
    && finite(event.time_s) && event.time_s >= 0 && typeof event.role === 'string'
    && ['car', 'arm', 'system'].includes(event.role) && typeof event.message === 'string')
}

export function validateCooperationState(value: unknown): CooperationState {
  if (!record(value) || value.mode !== 'mujoco' || value.domain !== COOPERATION_DOMAIN
    || typeof value.ready !== 'boolean' || typeof value.reason !== 'string'
    || !validTask(value.task) || !validEvents(value.events)
    || (value.episode_id !== undefined && !identity(value.episode_id))
    || (value.reset !== undefined && (!record(value.reset) || typeof value.reset.available !== 'boolean'
      || typeof value.reset.pending !== 'boolean' || typeof value.reset.reason !== 'string'
      || (value.reset.last !== null && (!record(value.reset.last) || !identity(value.reset.last.request_id)
        || !resetStatus(value.reset.last.status) || !identity(value.reset.last.from_episode)
        || !(value.reset.last.to_episode === null || identity(value.reset.last.to_episode)) || typeof value.reset.last.message !== 'string'))))
    || (value.history !== undefined && (!Array.isArray(value.history) || !value.history.every((entry) => record(entry)
      && identity(entry.episode_id) && validTask(entry.task) && validEvents(entry.events)
      && ((finite(entry.completed_at) && entry.completed_at >= 0)
        || (identity(entry.completed_at) && Number.isFinite(Date.parse(entry.completed_at)))))))
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
  return cooperationConnected(snapshot, now) && snapshot.state!.ready && !snapshot.state!.reset?.pending
    && !snapshot.pending && !snapshot.receipt && !snapshot.resetReceipt
    && ['idle', 'succeeded', 'failed', 'canceled'].includes(snapshot.state!.task.status)
}
export function cooperationCanCancel(snapshot: CooperationSnapshot, now = Date.now()): boolean {
  return cooperationConnected(snapshot, now) && !snapshot.state!.reset?.pending && !snapshot.pending && !snapshot.receipt && !snapshot.resetReceipt
    && !!snapshot.ownedTaskId && snapshot.ownedTaskId === snapshot.state!.task.id
    && snapshot.state!.task.status === 'running'
}
export function cooperationCanReset(snapshot: CooperationSnapshot, now = Date.now()): boolean {
  return cooperationConnected(snapshot, now) && !!snapshot.state!.episode_id && !!snapshot.state!.reset?.available
    && !snapshot.state!.reset?.pending && !snapshot.pending && !snapshot.receipt && !snapshot.resetReceipt
    && ['idle', 'succeeded', 'failed', 'canceled'].includes(snapshot.state!.task.status)
}
export function cooperationFrameSourceKey(state: CooperationState | null): string | null {
  const scene = state?.source?.scene_sha
  return scene ? state?.episode_id ? JSON.stringify([scene, state.episode_id]) : scene : null
}

class CooperationRequestError extends Error {
  readonly rejected: boolean
  constructor(message: string, rejected: boolean) { super(message); this.rejected = rejected }
}
function validateResetRecord(value: unknown): CooperationResetRecord {
  if (!record(value) || !identity(value.request_id) || !identity(value.episode_id) || !resetStatus(value.status)
    || !(value.new_episode_id === null || identity(value.new_episode_id)) || typeof value.message !== 'string'
    || (value.status === 'succeeded' && (!identity(value.new_episode_id) || value.new_episode_id === value.episode_id))) {
    throw new CooperationRequestError('重置记录不完整，继续核对原请求。', false)
  }
  return value as CooperationResetRecord
}
type Fetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
type ReceiptStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
const STORAGE_KEY = 'fishbot.cooperation.receipt.v1'
type ControllerOptions = { fetcher?: Fetcher; now?: () => number; taskId?: () => string; resetId?: () => string; storage?: ReceiptStorage | null }

/** Only user actions send POST. Polling reconciles the same task and never resends a mutation. */
export class CooperationController {
  private snapshot: CooperationSnapshot = { ...EMPTY_COOPERATION_SNAPSHOT }
  private listeners = new Set<(value: CooperationSnapshot) => void>()
  private fetcher: Fetcher
  private now: () => number
  private taskId: () => string
  private resetId: () => string
  private storage: ReceiptStorage | null
  private reading: Promise<void> | null = null
  private requestVersion = 0

  constructor(options: ControllerOptions = {}) {
    this.fetcher = options.fetcher ?? ((input, init) => fetch(input, init))
    this.now = options.now ?? Date.now
    this.taskId = options.taskId ?? (() => crypto.randomUUID())
    this.resetId = options.resetId ?? (() => crypto.randomUUID())
    this.storage = options.storage ?? null
    try {
      const raw = this.storage?.getItem(STORAGE_KEY)
      const stored: unknown = raw ? JSON.parse(raw) : null
      if (record(stored)) {
        if (identity(stored.ownedTaskId)) this.snapshot.ownedTaskId = stored.ownedTaskId
        if (record(stored.receipt) && ['start', 'cancel'].includes(String(stored.receipt.action))
          && identity(stored.ownedTaskId) && stored.receipt.taskId === stored.ownedTaskId && typeof stored.receipt.unknown === 'boolean') {
          this.snapshot.receipt = stored.receipt as CooperationReceipt
        }
        if (record(stored.resetReceipt) && identity(stored.resetReceipt.requestId) && identity(stored.resetReceipt.fromEpisode)
          && typeof stored.resetReceipt.unknown === 'boolean') this.snapshot.resetReceipt = stored.resetReceipt as CooperationResetReceipt
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
      if (this.snapshot.ownedTaskId || this.snapshot.receipt || this.snapshot.resetReceipt) this.storage?.setItem(STORAGE_KEY, JSON.stringify({
        ownedTaskId: this.snapshot.ownedTaskId, receipt: this.snapshot.receipt, resetReceipt: this.snapshot.resetReceipt,
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
    const resetReceipt = this.snapshot.resetReceipt
    this.reading = (async () => {
      try {
        let resetRecord: CooperationResetRecord | null = null
        let resetError: string | null = null
        if (resetReceipt) {
          try {
            resetRecord = validateResetRecord(await this.request(`reset/${encodeURIComponent(resetReceipt.requestId)}`))
            if (resetRecord.request_id !== resetReceipt.requestId || resetRecord.episode_id !== resetReceipt.fromEpisode) {
              throw new CooperationRequestError('重置回执的请求编号或原回合不匹配，继续核对原请求。', false)
            }
          } catch (error) {
            resetRecord = null
            resetError = error instanceof Error ? error.message : '未读取到原重置记录。'
          }
        }
        const value = validateCooperationState(await this.request(`state${taskId ? `?task_id=${encodeURIComponent(taskId)}` : ''}`))
        if (version !== this.requestVersion) return
        const receipt = this.snapshot.receipt
        const resolved = !!receipt && value.task.id === receipt.taskId
          && (receipt.action === 'start' ? value.task.status !== 'idle' && value.task.status !== 'unknown'
            : ['canceled', 'succeeded', 'failed'].includes(value.task.status))
        const patch: Partial<CooperationSnapshot> = { state: value, receivedAt: this.now(), connectionError: null,
          ...(resolved ? { receipt: null, actionError: null } : {}) }
        if (resetReceipt) {
          if (resetRecord?.status === 'failed') {
            patch.resetReceipt = null
            patch.actionError = resetRecord.message || '场景重置失败，服务未提供具体原因。'
          } else if (resetRecord?.status === 'succeeded' && value.episode_id === resetRecord.new_episode_id) {
            patch.resetReceipt = null
            patch.ownedTaskId = null
            patch.actionError = null
          } else {
            patch.resetReceipt = { ...resetReceipt, unknown: !resetRecord || resetRecord.status === 'unknown' || resetRecord.status === 'succeeded' }
            patch.actionError = resetError ? `${resetError} 重置回执未知，只读取原请求；请勿重复重置。`
              : resetRecord?.status === 'succeeded' ? '重置记录已完成，但当前回合编号不匹配；继续核对，不能向其他回合派发。'
                : resetRecord?.status === 'unknown' ? resetRecord.message || '重置结果未知，只读取原请求；请勿重复重置。' : null
          }
        }
        this.update(patch)
      } catch (error) {
        if (version === this.requestVersion) this.update({ connectionError: error instanceof Error ? error.message : '协同服务暂时无法连接。' })
      } finally { this.reading = null }
    })()
    return this.reading
  }
  act = async (action: 'start' | 'cancel'): Promise<void> => {
    if (action === 'start' ? !cooperationCanStart(this.snapshot, this.now()) : !cooperationCanCancel(this.snapshot, this.now())) return
    const taskId = action === 'start' ? this.taskId() : this.snapshot.ownedTaskId!
    const episodeId = this.snapshot.state?.episode_id
    ++this.requestVersion
    this.update({ pending: action, actionError: null, ownedTaskId: taskId,
      receipt: { action, taskId, unknown: true } })
    try {
      const value = await this.request(action, { task_id: taskId, issued_at: this.now() / 1000,
        ...(action === 'start' && episodeId ? { episode_id: episodeId } : {}) })
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
  reset = async (): Promise<void> => {
    if (!cooperationCanReset(this.snapshot, this.now())) return
    const requestId = this.resetId(), fromEpisode = this.snapshot.state!.episode_id!
    const ownsReceipt = () => this.snapshot.resetReceipt?.requestId === requestId
      && this.snapshot.resetReceipt.fromEpisode === fromEpisode
    ++this.requestVersion
    this.update({ pending: 'reset', actionError: null, resetReceipt: { requestId, fromEpisode, unknown: true } })
    try {
      const value = await this.request('reset', { request_id: requestId, issued_at: this.now() / 1000, episode_id: fromEpisode })
      if (!record(value) || value.request_id !== requestId || !resetStatus(value.status)) {
        throw new CooperationRequestError('重置回执的请求编号或状态不匹配。', false)
      }
      if (ownsReceipt()) this.update({ resetReceipt: { requestId, fromEpisode, unknown: value.status === 'unknown' } })
    } catch (error) {
      const rejected = error instanceof CooperationRequestError && error.rejected
      const message = error instanceof Error ? error.message : '请求未收到明确回执。'
      if (ownsReceipt()) this.update({ actionError: rejected ? message : `${message} 重置回执未知，只读取原请求；请勿重复重置。`,
        ...(rejected ? { resetReceipt: null } : {}) })
    } finally {
      this.update({ pending: null })
      await this.refresh()
    }
  }
}

export type CooperationFrameObservation = { scene: string; stamp: number; changedAt: number; loadedStamp: number | null; error: boolean }
export function cooperationFrameLabel(state: CooperationState | null, frame: CooperationFrameObservation | null, connected: boolean, now: number): string {
  if (!state?.frame.available || state.frame.stamp === null) return '等待相机画面'
  if (frame && frame.scene !== cooperationFrameSourceKey(state)) return '画面来源已变化，等待新帧'
  if (frame?.error) return '相机画面读取失败'
  if (!frame || frame.loadedStamp === null) return '正在读取相机画面'
  if (!connected || now - frame.changedAt >= COOPERATION_STALE_MS) return '画面已过期'
  if (state.frame.stamp < frame.loadedStamp || state.frame.stamp - frame.loadedStamp > 1.5) return '画面已过期'
  return '相机画面持续更新'
}
