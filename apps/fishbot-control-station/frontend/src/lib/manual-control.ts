import { requestSimulation, simulationRequestRejected } from './simulation'

export type ManualDirection = 'forward' | 'backward' | 'left' | 'right'
export type QuietEvidence = { confirmed: boolean; duration_s: number; source: '/ground_truth/free_joint_states'; source_stamp: number | null; receive_age_s: number | null; source_age_s: number | null }
export type ManualIdentity = { session_id: string; runtime_instance_id: string; map_id: string; profile_id: 'passage_manual' }
export type ManualLimits = { forward_mps: number; reverse_mps: number; angular_rps: number; command_ttl_ms: number; acquire_ttl_ms: number; heartbeat_ms: number }
export type ManualIdleRecovery = { trigger_id: string; state: 'resetting' | 'ready' | 'unknown'; reason: string | null; guard_reset_acknowledged: boolean | null; runtime_instance_id: string; native_task_id: string | null }
export type ManualStatus = {
  runtime_instance_id: string; map_id: string; profile_id: 'passage_manual'; available: boolean; can_acquire: boolean; can_stop: boolean; can_reset: boolean
  reason: string | null; active_lease_id: string | null; active_stop_request_id: string | null; stop_latched: boolean
  native_owner: { task_id: string | null; status: string; native_goal_id: string | null; terminal: boolean }; quiet: QuietEvidence; limits: ManualLimits
  idle_recovery?: ManualIdleRecovery | null; idle_recovery_attempts?: number
}
export type ManualLease = ManualIdentity & { lease_id: string; last_sequence: number; state: 'arming' | 'ready' | 'active' | 'released' | 'expired' | 'stopped' | 'unknown'; reason: string | null; expires_at_ms: number; remaining_ms: number; guard_reset_acknowledged: boolean | null; guard_stop_acknowledged: boolean | null; quiet: QuietEvidence }
export type ManualStop = { request_id: string; target_id: string | null; target_kind: 'manual' | 'mission' | 'idle'; state: 'stopping' | 'stopped' | 'unknown'; guard_stop_acknowledged: boolean | null; native_cancel_acknowledged: boolean | null; native_terminal: boolean | null; native_status: number | null; quiet: QuietEvidence; reason: string | null; runtime_instance_id: string }
export type ManualReset = { request_id: string; stop_request_id: string; state: 'resetting' | 'ready' | 'unknown'; guard_reset_acknowledged: boolean | null; reason: string | null; runtime_instance_id: string }
type PriorReset = { stop_id: string; stop_target_id: string | null; reset_id: string; last_sequence: number }
type Receipt = ManualIdentity & { lease_id: string | null; stop_id: string | null; stop_target_id: string | null; reset_id: string | null; last_sequence: number; prior_reset?: PriorReset }
export type ManualSnapshot = { status: ManualStatus | null; lease: ManualLease | null; stop: ManualStop | null; reset: ManualReset | null; direction: ManualDirection | null; pending: string | null; unknown: boolean; message: string; error: string | null }
/** Explain admission without turning a blocked or unknown result into health. */
export function manualAdmissionMessage(status: Pick<ManualStatus, 'reason' | 'can_acquire'> | null): string {
  if (!status) return '正在核对原任务与停车状态。'
  const messages: Record<string, string> = {
    manual_profile_not_enabled: '当前实例未启用人工控制。请使用带速度仲裁与碰撞监测的仿真实例。',
    manual_map_unavailable: '地图尚未绑定，暂不能申请控制权。请等待地图就绪。',
    explicit_stop_latched: '本次软件停车锁仍有效。请在原动作结束并停稳后，显式解除本次停车锁。',
    native_owner_unresolved: '原导航动作尚未确认结束。请查看原任务回执，或停止原任务后等待终态与停稳。',
    manual_lease_busy: '上一轮人工控制尚未释放或结果未确认。请松手并等待原控制回执。',
    manual_cleanup_unconfirmed: '正在核对停车清理与守卫回执。确认前不会接纳新的行驶请求。',
    continuous_quiet_unconfirmed: '尚未取得连续 0.7 秒的新鲜静止证据。请等待车辆停稳。',
    guard_unavailable: '守卫尚未就绪或已锁定。请查看控制与停车证据；恢复未确认前不接纳行驶请求。',
    guard_reset_required: '守卫零速恢复尚未确认。请等待原恢复回执；不会恢复上次行驶。',
    manual_zero_dispatch_unknown: '零速停车或速度仲裁的结果未确认。请核对原停车证据，不要重复行驶请求。',
    manual_nav_lock_unknown: '导航速度仲裁的结果未确认。请核对原执行器与停车证据。',
  }
  if (status.reason) return messages[status.reason] ?? `控制准入尚未通过（${status.reason}）。请查看控制与停车证据；不会自动恢复行驶。`
  return status.can_acquire ? '可申请控制权；下一次按住才会行驶。' : '正在核对原任务与停车状态。'
}
export function manualIdleRecoveryMessage(status: Pick<ManualStatus, 'idle_recovery' | 'idle_recovery_attempts'> | null): string | null {
  const recovery = status?.idle_recovery
  if (!recovery) return null
  const attempts = status?.idle_recovery_attempts === undefined ? '' : ` 累计尝试 ${status.idle_recovery_attempts} 次。`
  if (recovery.state === 'resetting') return `正在确认空闲守卫恢复；期间只发送零速，不恢复上次行驶。${attempts}`
  if (recovery.state === 'ready') return `最近一次空闲恢复已获守卫确认；当前能否行驶仍以准入核对为准。${attempts}`
  const explanations: Record<string, string> = {
    guard_reset_timeout: '未在期限内收到守卫恢复回执，请核对原执行器与停车证据',
    guard_reset_unconfirmed: '守卫没有明确确认恢复，请核对原停车证据',
    guard_reset_dispatch_failed: '恢复请求的发送未确认，请核对原执行器',
    idle_recovery_owner_or_fault_changed: '恢复期间任务归属或故障已变化，已重新要求停车确认',
    manual_zero_dispatch_unknown: '零速停车或速度仲裁未确认，请核对原停车证据',
  }
  const detail = recovery.reason ? ` 详情：${explanations[recovery.reason] ?? '未识别的恢复状态'}（${recovery.reason}）。` : ''
  return `空闲恢复未确认；不会自动重试或恢复上次行驶。${attempts}${detail}`
}
export function manualResetBlockReason(value: ManualSnapshot): string | null {
  if (!value.status?.stop_latched) return '当前没有停车锁。'
  if (!value.stop || value.stop.request_id !== value.status.active_stop_request_id) {
    return '本页没有当前停车锁的原回执。请在原会话解除，或先点“停止”建立本页停车回执。'
  }
  if (value.pending || value.reset) return '正在核对原请求；不会重复提交解除。'
  if (!value.status.can_reset || value.stop.state !== 'stopped' || !value.stop.quiet.confirmed
    || value.stop.guard_stop_acknowledged !== true || value.stop.native_terminal !== true) return '等待原动作终态、守卫停车和连续静止。'
  return null
}
type Request = <T>(path: string, body?: object, signal?: AbortSignal) => Promise<T>
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)
const nullableBoolean = (v: unknown) => v === null || typeof v === 'boolean'
const nullableNumber = (v: unknown) => v === null || typeof v === 'number' && Number.isFinite(v)
const id = (v: unknown): v is string => typeof v === 'string' && v.length > 0 && v.length <= 256
const nullableId = (v: unknown) => v === null || id(v)
const reason = (v: unknown) => v === null || typeof v === 'string'
function accepted<T extends object>(value: T & { accepted?: boolean; outcome?: string }): T {
  if (value.accepted !== true || value.outcome !== 'accepted') throw new Error('控制请求未返回明确接纳回执。')
  return value
}
function quiet(v: unknown): v is QuietEvidence {
  return object(v) && typeof v.confirmed === 'boolean' && typeof v.duration_s === 'number' && Number.isFinite(v.duration_s) && v.duration_s >= 0
    && v.source === '/ground_truth/free_joint_states' && nullableNumber(v.source_stamp) && nullableNumber(v.receive_age_s) && nullableNumber(v.source_age_s)
    && (!v.confirmed || v.duration_s >= .7 && typeof v.source_stamp === 'number' && typeof v.receive_age_s === 'number' && v.receive_age_s >= 0 && v.receive_age_s <= .25 && typeof v.source_age_s === 'number' && v.source_age_s >= -.05 && v.source_age_s <= .25)
}
export function validateManualStatus(v: unknown): ManualStatus {
  if (!object(v) || !id(v.runtime_instance_id) || !id(v.map_id) || v.profile_id !== 'passage_manual'
    || !['available', 'can_acquire', 'can_stop', 'can_reset', 'stop_latched'].every(k => typeof v[k] === 'boolean')
    || ![v.active_lease_id, v.active_stop_request_id].every(x => x === null || typeof x === 'string' && UUID.test(x))
    || !reason(v.reason) || !object(v.native_owner) || typeof v.native_owner.terminal !== 'boolean'
    || !nullableId(v.native_owner.task_id) || !nullableId(v.native_owner.native_goal_id) || !id(v.native_owner.status)
    || !quiet(v.quiet) || !object(v.limits)) throw new Error('人工控制能力或停车证据无效。')
  const l = v.limits
  for (const [k, max] of Object.entries({ forward_mps: .08, reverse_mps: .03, angular_rps: .25, command_ttl_ms: 250, acquire_ttl_ms: 1000, heartbeat_ms: 140 })) {
    if (typeof l[k] !== 'number' || !Number.isFinite(l[k]) || l[k] <= 0 || l[k] > max) throw new Error('人工控制速限或时限不符合当前守卫。')
  }
  if (Number(l.heartbeat_ms) >= Number(l.command_ttl_ms)) throw new Error('人工控制心跳必须短于命令有效期。')
  if (v.idle_recovery_attempts !== undefined && (!Number.isSafeInteger(v.idle_recovery_attempts) || Number(v.idle_recovery_attempts) < 0)) throw new Error('空闲守卫恢复次数无效。')
  if (v.idle_recovery !== undefined && v.idle_recovery !== null) {
    const r = v.idle_recovery
    if (!object(r) || typeof r.trigger_id !== 'string' || !r.trigger_id || r.trigger_id.length > 4096
      || !['resetting', 'ready', 'unknown'].includes(String(r.state)) || !reason(r.reason)
      || r.runtime_instance_id !== v.runtime_instance_id || !nullableId(r.native_task_id) || !nullableBoolean(r.guard_reset_acknowledged)
      || (r.state === 'ready' && r.guard_reset_acknowledged !== true)) throw new Error('空闲守卫恢复身份或回执无效。')
  }
  return v as ManualStatus
}
function sameIdentity(v: Record<string, unknown>, r: Receipt): boolean {
  return ['session_id', 'runtime_instance_id', 'map_id', 'profile_id'].every(k => v[k] === r[k as keyof Receipt])
}
export function validateManualLease(v: unknown, r: Receipt, acceptedSequence = true): ManualLease {
  if (!object(v) || !sameIdentity(v, r) || v.lease_id !== r.lease_id || !Number.isSafeInteger(v.last_sequence)
    || Number(v.last_sequence) < 0 || (acceptedSequence && Number(v.last_sequence) !== r.last_sequence)
    || !['arming', 'ready', 'active', 'released', 'expired', 'stopped', 'unknown'].includes(String(v.state))
    || !nullableBoolean(v.guard_reset_acknowledged) || !nullableBoolean(v.guard_stop_acknowledged) || !quiet(v.quiet)
    || !reason(v.reason) || !Number.isFinite(v.expires_at_ms) || !Number.isFinite(v.remaining_ms) || Number(v.remaining_ms) < 0) throw new Error('原控制租约身份、序号或证据不匹配。')
  return v as ManualLease
}
function validateStop(v: unknown, r: Receipt): ManualStop {
  if (!object(v) || v.request_id !== r.stop_id || v.runtime_instance_id !== r.runtime_instance_id
    || !nullableId(v.target_id) || (r.stop_target_id !== null && v.target_id !== r.stop_target_id)
    || !['manual', 'mission', 'idle'].includes(String(v.target_kind)) || !['stopping', 'stopped', 'unknown'].includes(String(v.state))
    || !reason(v.reason) || !nullableNumber(v.native_status)
    || ![v.guard_stop_acknowledged, v.native_cancel_acknowledged, v.native_terminal].every(nullableBoolean) || !quiet(v.quiet)
    || (v.state === 'stopped' && (v.guard_stop_acknowledged !== true || v.native_terminal !== true || !v.quiet.confirmed))) throw new Error('原停车请求身份或证据不匹配。')
  return v as ManualStop
}
function validateReset(v: unknown, r: Receipt): ManualReset {
  if (!object(v) || v.request_id !== r.reset_id || v.stop_request_id !== r.stop_id || v.runtime_instance_id !== r.runtime_instance_id
    || !['resetting', 'ready', 'unknown'].includes(String(v.state)) || !reason(v.reason) || !nullableBoolean(v.guard_reset_acknowledged)
    || (v.state === 'ready' && v.guard_reset_acknowledged !== true)) throw new Error('原解除请求身份不匹配。')
  return v as ManualReset
}

/** Application-owned, bounded manual adapter. A recovered receipt never restores a gesture. */
export class ManualController {
  private state: ManualSnapshot = { status: null, lease: null, stop: null, reset: null, direction: null, pending: null, unknown: false, message: '尚未读取人工控制能力。', error: null }
  private listeners = new Set<() => void>()
  private receipt: Receipt | null = null
  private generation = 0
  private sequence = 0
  private timer: ReturnType<typeof setTimeout> | null = null
  private request: Request
  private now: () => number
  private steadyNow: () => number
  private uuid: () => string
  private storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
  private key: string
  constructor(options: { request?: Request; now?: () => number; steadyNow?: () => number; uuid?: () => string; storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>; domain: number }) {
    if (!Number.isInteger(options.domain) || options.domain < 1 || options.domain > 232) throw new Error('人工控制需要明确的隔离 ROS domain。')
    this.request = options.request ?? requestSimulation; this.now = options.now ?? Date.now; this.steadyNow = options.steadyNow ?? (() => performance.now()); this.uuid = options.uuid ?? (() => crypto.randomUUID()); this.storage = options.storage
    this.key = `fishbot.manual-receipt.v1:${options.domain}`
    try {
      const raw = this.storage?.getItem(this.key)
      if (raw) {
        const r = JSON.parse(raw)
        if (raw.length > 2048 || !object(r) || !UUID.test(String(r.session_id)) || !id(r.runtime_instance_id) || !id(r.map_id) || r.profile_id !== 'passage_manual'
          || ![r.lease_id, r.stop_id, r.reset_id].every(v => v === null || typeof v === 'string' && UUID.test(v)) || !nullableId(r.stop_target_id)
          || !Number.isSafeInteger(r.last_sequence) || Number(r.last_sequence) < 0 || (r.reset_id !== null && r.stop_id === null)
          || (r.prior_reset !== undefined && (!object(r.prior_reset)
            || !UUID.test(String(r.prior_reset.stop_id)) || !UUID.test(String(r.prior_reset.reset_id))
            || !nullableId(r.prior_reset.stop_target_id) || !Number.isSafeInteger(r.prior_reset.last_sequence)
            || Number(r.prior_reset.last_sequence) < 0 || Number(r.prior_reset.last_sequence) > Number(r.last_sequence)
            || !r.stop_id || r.prior_reset.stop_id === r.stop_id
            || Object.keys(r.prior_reset).some(k => !['stop_id', 'stop_target_id', 'reset_id', 'last_sequence'].includes(k))))
          || Object.keys(r).some(k => !['session_id', 'runtime_instance_id', 'map_id', 'profile_id', 'lease_id', 'stop_id', 'stop_target_id', 'reset_id', 'last_sequence', 'prior_reset'].includes(k))) throw new Error('人工控制原回执缓存无效，请核对原执行器。')
        this.receipt = r as Receipt; this.sequence = r.last_sequence as number; this.state.unknown = true; this.state.message = '正在核对原控制请求；刷新不会恢复按住动作。'
      }
    } catch (error) { this.state.unknown = true; this.state.error = String(error) }
  }
  getSnapshot = () => this.state
  canBegin = () => !!this.state.status?.available && this.state.status.can_acquire && !this.receipt
    && !this.state.unknown && !this.state.pending && !this.state.direction
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  private patch(value: Partial<ManualSnapshot>) { this.state = { ...this.state, ...value }; this.listeners.forEach(fn => fn()) }
  private persist() { if (this.receipt) this.storage?.setItem(this.key, JSON.stringify(this.receipt)); else this.storage?.removeItem(this.key) }
  private halt() { ++this.generation; if (this.timer !== null) clearTimeout(this.timer); this.timer = null; this.patch({ direction: null }) }
  private envelope(ttl: number) {
    if (!this.receipt) throw new Error('缺少原控制身份。')
    this.receipt.last_sequence = ++this.sequence; this.persist()
    return { session_id: this.receipt.session_id, runtime_instance_id: this.receipt.runtime_instance_id, map_id: this.receipt.map_id, profile_id: this.receipt.profile_id,
      sequence: this.sequence, issued_at_ms: this.now(), ttl_ms: ttl }
  }
  private async call<T>(path: string, body?: object): Promise<T> {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), body ? 1500 : 2000)
    try { return await this.request<T>(`manual/${path}`, body, controller.signal) } finally { clearTimeout(timeout) }
  }
  async refresh(): Promise<void> {
    try {
      const status = validateManualStatus(await this.call<unknown>('status')); this.patch({ status, error: null })
      if (!status.available && this.state.direction) { this.halt(); this.patch({ unknown: true, message: '人工控制能力已失效，停止发送并核对原租约。' }) }
      const r = this.receipt
      if (!r) return
      if (r.runtime_instance_id !== status.runtime_instance_id || r.map_id !== status.map_id) {
        this.halt(); this.patch({ unknown: true, error: '运行环境已变化，原控制结果未核实；不会恢复动作。' }); return
      }
      if (r.reset_id) {
        const value = await this.call<{ reset: unknown }>(`resets/${r.reset_id}`); if (r !== this.receipt) return
        const reset = validateReset(value.reset, r); this.patch({ reset })
        if (reset.state === 'ready' && reset.guard_reset_acknowledged === true) { this.receipt = null; this.persist(); this.patch({ unknown: false, pending: null, message: '原停车锁已解除；下一次按住才会申请新控制权。' }) }
      } else if (r.stop_id) {
        const value = await this.call<{ stop: unknown }>(`stops/${r.stop_id}`); if (r !== this.receipt) return
        const stop = validateStop(value.stop, r); this.patch({ stop, unknown: stop.state === 'unknown', pending: null,
          message: stop.state === 'stopped' && stop.quiet.confirmed ? '原停车请求已确认；解除后仍需重新按住。' : '正在核对守卫、原动作终态与连续静止。' })
      } else if (r.lease_id) {
        const value = await this.call<{ lease: unknown }>(r.lease_id); if (r !== this.receipt) return
        const lease = validateManualLease(value.lease, r, false); this.patch({ lease })
        if (['released', 'expired', 'stopped'].includes(lease.state) && lease.quiet.confirmed && lease.guard_stop_acknowledged === true) {
          this.halt(); this.receipt = null; this.persist(); this.patch({ unknown: false, pending: null, message: '控制权已撤销，守卫停车和连续静止已确认。' })
        } else if (lease.state === 'unknown') { this.halt(); this.patch({ unknown: true, message: '原控制结果未知，只读核对中。' }) }
        // GET evidence does not restore the pointer/key gesture or restart the heartbeat.
      }
    } catch (error) {
      if (this.state.direction) { this.halt(); this.patch({ unknown: true, message: '控制回读中断，停止发送并等待原租约到期证据。' }) }
      this.patch({ error: error instanceof Error ? error.message : '控制回读失败。' })
    }
  }
  async begin(direction: ManualDirection, requestedLinear: number, requestedAngular: number): Promise<void> {
    const status = this.state.status
    if (!status || !this.canBegin()) return
    if (![requestedLinear, requestedAngular].every(v => Number.isFinite(v) && v > 0)) { this.patch({ error: '速度必须为有限正数。' }); return }
    this.halt(); const generation = this.generation
    const r: Receipt = { session_id: this.uuid(), runtime_instance_id: status.runtime_instance_id, map_id: status.map_id, profile_id: 'passage_manual', lease_id: this.uuid(), stop_id: null, stop_target_id: null, reset_id: null, last_sequence: 0 }
    this.receipt = r; this.sequence = 0
    const linear = Math.min(requestedLinear, direction === 'backward' ? status.limits.reverse_mps : status.limits.forward_mps)
    const angular = Math.min(requestedAngular, status.limits.angular_rps)
    const vector = { linear_x: direction === 'forward' ? linear : direction === 'backward' ? -linear : 0, angular_z: direction === 'left' ? angular : direction === 'right' ? -angular : 0 }
    this.patch({ direction, pending: 'acquire', lease: null, stop: null, reset: null, error: null, message: '申请低速控制权；尚未发送非零速度。' })
    let sent = false
    const acquisitionDeadline = this.now() + status.limits.acquire_ttl_ms
    try {
      this.persist(); sent = true
      const { lease } = accepted(await this.call<{ lease: unknown }>('acquire', { lease_id: r.lease_id, session_id: r.session_id, runtime_instance_id: r.runtime_instance_id, map_id: r.map_id, profile_id: r.profile_id, sequence: 0, issued_at_ms: this.now(), ttl_ms: status.limits.acquire_ttl_ms, gesture: 'press' }))
      if (generation !== this.generation || r !== this.receipt) return
      this.patch({ lease: validateManualLease(lease, r), pending: null })
      const advance = async (): Promise<void> => {
        if (generation !== this.generation || r !== this.receipt || !this.state.direction || this.state.unknown) return
        const sentAt = this.steadyNow()
        try {
          if (this.state.lease?.state === 'arming') {
            if (this.now() >= acquisitionDeadline) throw new Error('控制权准备超时；停止等待并核对原租约。')
            const value = await this.call<{ lease: unknown }>(r.lease_id!); if (generation !== this.generation) return
            this.patch({ lease: validateManualLease(value.lease, r, false) })
          } else if (['ready', 'active'].includes(this.state.lease?.state ?? '')) {
            if (this.now() >= this.state.lease!.expires_at_ms) throw new Error('原控制租约已到期；停止发送并核对停车。')
            const body = { ...this.envelope(status.limits.command_ttl_ms), lease_id: r.lease_id, ...vector }
            const value = accepted(await this.call<{ lease: unknown }>('command', body)); if (generation !== this.generation) return
            const lease = validateManualLease(value.lease, r)
            this.patch({ lease })
            if (lease.state !== 'active' || this.now() >= lease.expires_at_ms) throw new Error('命令回执到达时原租约已结束；停止发送并核对停车。')
            this.patch({ message: '速度命令已获租约接纳；物理运动与停车另行读回。' })
          } else { this.halt(); this.patch({ unknown: true, message: '控制租约已结束，核对停车后重新按住。' }); return }
          const elapsed = this.steadyNow() - sentAt
          if (!Number.isFinite(elapsed) || elapsed < 0) throw new Error('人工控制单调时钟无效；停止发送并核对原租约。')
          // One fresh request after its predecessor's reply. Account for ACK
          // time, without overlapping requests or replaying missed intervals.
          if (generation === this.generation) this.timer = setTimeout(() => { void advance() }, Math.max(0, status.limits.heartbeat_ms - elapsed))
        } catch (error) { if (generation === this.generation) { this.halt(); this.patch({ unknown: true, error: String(error), message: '停止发送，正在核对原租约；不会重试旧命令。' }) } }
      }
      void advance()
    } catch (error) {
      if (generation !== this.generation) return
      this.halt()
      if (!sent || simulationRequestRejected(error)) {
        this.receipt = null
        try { this.persist(); this.patch({ unknown: false }) } catch { this.patch({ unknown: true }) }
      }
      else this.patch({ unknown: true })
      this.patch({ pending: null, error: String(error), message: '控制申请未获确认；未发送非零速度。' })
    }
  }
  async release(): Promise<void> {
    const wasHeld = this.state.direction !== null; this.halt(); const r = this.receipt
    if (!wasHeld || !r?.lease_id || r.stop_id) return
    this.patch({ pending: 'release', message: '已停止发送；等待原租约撤销与连续静止。' })
    try {
      const value = accepted(await this.call<{ lease: unknown }>('release', { ...this.envelope(1000), lease_id: r.lease_id }))
      if (r === this.receipt) this.patch({ lease: validateManualLease(value.lease, r), pending: null })
    } catch (error) { if (r === this.receipt) this.patch({ pending: null, unknown: true, error: String(error) }) }
  }
  async stop(): Promise<void> {
    this.halt(); const s = this.state.status
    const previous = this.receipt
    // A new explicit STOP supersedes an already-issued reset. An unknown
    // STOP without a reset still remains read-only; it is never resubmitted.
    if (!s?.can_stop || (previous?.stop_id && !previous.reset_id)) return
    const target = s.active_lease_id ?? (!s.native_owner.terminal ? s.native_owner.task_id : null)
    if (this.receipt && (this.receipt.runtime_instance_id !== s.runtime_instance_id || this.receipt.map_id !== s.map_id)) {
      this.patch({ unknown: true, error: '原请求属于另一个运行环境；请先核对原执行器。' }); return
    }
    if (this.receipt?.lease_id && s.active_lease_id && this.receipt.lease_id !== s.active_lease_id) {
      this.patch({ unknown: true, error: '当前活动租约与本页原租约不一致；未替换停车目标，请先核对原执行器。' }); return
    }
    const priorUnknown = this.state.unknown
    const priorState = { stop: this.state.stop, reset: this.state.reset }
    const priorReset = previous?.stop_id && previous.reset_id ? {
      stop_id: previous.stop_id, stop_target_id: previous.stop_target_id,
      reset_id: previous.reset_id, last_sequence: previous.last_sequence,
    } : undefined
    this.receipt = { session_id: previous?.session_id ?? this.uuid(), runtime_instance_id: s.runtime_instance_id, map_id: s.map_id, profile_id: 'passage_manual', lease_id: previous?.lease_id ?? null, stop_id: this.uuid(), stop_target_id: target, reset_id: null, last_sequence: this.sequence,
      ...(priorReset ? { prior_reset: priorReset } : {}) }
    const r = this.receipt; this.patch({ pending: 'stop', stop: null, reset: null, message: '正在请求原执行器停车。' })
    let sent = false
    try {
      const body = { ...this.envelope(1000), request_id: r.stop_id, target_id: target }; sent = true
      const value = accepted(await this.call<{ stop: unknown }>('stop', body))
      if (r === this.receipt) {
        const stop = validateStop(value.stop, r)
        this.patch({ stop, pending: null, unknown: stop.state === 'unknown' })
      }
    } catch (error) {
      if (r !== this.receipt) return
      if (!sent || simulationRequestRejected(error)) {
        if (previous && priorReset) {
          // A definite rejection cannot erase the original reset. Restore
          // its IDs in a fresh object so only new reads can resolve it.
          this.receipt = { ...previous, last_sequence: this.sequence }
          let detail = String(error)
          try { this.persist() } catch (storageError) { detail += `；原回执缓存更新失败：${String(storageError)}` }
          this.patch({ ...priorState, pending: 'reset-recovery', unknown: true, error: detail,
            message: '新的停车请求未被接纳；正在只读核对先前的解除请求。不会重发解除或行驶。' })
          return
        }
        r.stop_id = null; r.stop_target_id = null
        if (!r.lease_id) this.receipt = null
        try { this.persist(); this.patch({ unknown: priorUnknown }) } catch { this.patch({ unknown: true }) }
        this.patch({ pending: null, error: String(error), message: '停车请求未被接纳；不会自动重发。请核对原控制状态后再点击停止。' })
      } else this.patch({ pending: null, unknown: true, error: String(error) })
    }
  }
  async reset(): Promise<void> {
    this.halt(); const r = this.receipt
    const blocked = manualResetBlockReason(this.state)
    if (!r?.stop_id || r.reset_id || blocked) { this.patch({ message: blocked ?? '缺少原停车回执；请先核对当前停车锁。' }); return }
    const priorUnknown = this.state.unknown
    r.reset_id = this.uuid(); this.patch({ pending: 'reset', message: '正在解除已确认的原停车锁；不会恢复行走。' })
    let sent = false
    try {
      const body = { ...this.envelope(1000), request_id: r.reset_id, stop_request_id: r.stop_id, gesture: 'reset' }; sent = true
      const value = accepted(await this.call<{ reset: unknown }>('reset', body))
      if (r === this.receipt) this.patch({ reset: validateReset(value.reset, r), pending: null })
    } catch (error) {
      if (r !== this.receipt) return
      if (!sent || simulationRequestRejected(error)) {
        r.reset_id = null
        try { this.persist(); this.patch({ unknown: priorUnknown }) } catch { this.patch({ unknown: true }) }
        this.patch({ reset: null, pending: null, error: String(error), message: '解除请求未被接纳，原停车锁仍保持；重新核对后可再次点击解除。' })
      } else this.patch({ pending: null, unknown: true, error: String(error) })
    }
  }
}
