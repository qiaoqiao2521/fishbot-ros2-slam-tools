import { runtimeFetch, runtimeJson } from '@/lib/runtime-context'

export const VOICE_DOMAIN = Number(import.meta.env.VITE_FISHBOT_VOICE_DOMAIN ?? '121')
if (!Number.isInteger(VOICE_DOMAIN) || VOICE_DOMAIN < 1 || VOICE_DOMAIN > 232) throw new Error('语音服务必须配置明确的隔离 ROS 域。')
export const VOICE_AUDIO_MAX_BYTES = 4 * 1024 * 1024
export const VOICE_AUDIO_MAX_MS = 15000
export const VOICE_AUDIO_TTL_MS = 5000
export const VOICE_STATE_MAX_AGE_MS = 30000

export type VoiceParse = {
  accepted: boolean
  intent: string | null
  parameters: Record<string, unknown>
  reason: string
}
export type VoiceCapability = { available: boolean; reason: string }
export type VoiceCommand = {
  command_id: string; status: string; reason?: string; task_id?: string | null; sequence?: number; task?: VoiceTask | null
  accepted?: boolean | null; session_id?: string
}
export type VoiceTask = {
  id: string | null; status: string; message?: string; reason?: string
  task_id?: string; owner?: string
  phase?: string; intent?: string; upstream?: string; upstream_record?: Record<string, unknown>
  native_status?: string | number | null; physical_result?: unknown
}
export type VoiceState = {
  mode: 'simulation'; domain: number; session_id: string; ready: boolean; reason: string
  last_sequence?: number
  asr: VoiceCapability & { engine?: string; model?: string }
  capabilities: Record<string, boolean | string | string[]>
  latest_command: VoiceCommand | null; task: VoiceTask | null
}
export type VoiceTranscript = {
  text: string; asr_id: string; session_id: string; parse: VoiceParse; received_at_ms: number; expires_at_ms: number
}
export type VoiceEnvelope = {
  command_id: string; session_id: string; sequence: number; issued_at_ms: number; ttl_ms: number
  text: string; asr_id?: string
}
export type VoiceReceipt = { envelope: VoiceEnvelope; unknown: boolean; command: VoiceCommand | null }
export type VoiceSnapshot = {
  text: string; state: VoiceState | null; receivedAt: number | null
  preview: VoiceParse | null; transcript: VoiceTranscript | null
  connectionError: string | null; actionError: string | null
  pending: 'connect' | 'preview' | 'transcribe' | 'execute' | null; receipt: VoiceReceipt | null
}
export const EMPTY_VOICE_SNAPSHOT: VoiceSnapshot = {
  text: '', state: null, receivedAt: null, preview: null, transcript: null,
  connectionError: null, actionError: null, pending: null, receipt: null,
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
function identity(value: unknown): value is string { return typeof value === 'string' && value.trim().length > 0 }
function finite(value: unknown): value is number { return typeof value === 'number' && Number.isFinite(value) }
class VoiceRejectedError extends Error {}
function capability(value: unknown): value is VoiceCapability {
  return record(value) && typeof value.available === 'boolean' && typeof value.reason === 'string'
}
export function validateVoiceParse(value: unknown): VoiceParse {
  if (!record(value) || typeof value.accepted !== 'boolean' || !(value.intent === null || identity(value.intent))
    || !record(value.parameters) || typeof value.reason !== 'string') throw new Error('语音解析响应不完整，请重新预览。')
  return value as VoiceParse
}
export function validateVoiceCommand(value: unknown): VoiceCommand {
  if (!record(value) || !identity(value.command_id) || !identity(value.status)
    || !['accepted', 'submitting', 'running', 'canceling', 'succeeded', 'failed', 'canceled', 'rejected', 'unknown', 'task_unknown'].includes(value.status)
    || (value.accepted !== undefined && value.accepted !== null && typeof value.accepted !== 'boolean')
    || (value.accepted === false && value.status !== 'rejected')
    || (value.session_id !== undefined && !identity(value.session_id))
    || (value.reason !== undefined && typeof value.reason !== 'string')
    || (value.task_id !== undefined && value.task_id !== null && !identity(value.task_id))) throw new Error('执行回执不完整。')
  return value as VoiceCommand
}
export function validateVoiceState(value: unknown, expectedDomain = VOICE_DOMAIN): VoiceState {
  if (!record(value) || value.mode !== 'simulation') throw new Error('语音服务模式不匹配，仅允许仿真服务。')
  if (value.domain !== expectedDomain) throw new Error(`语音服务 ROS 域不匹配：需要 ${expectedDomain}，收到 ${String(value.domain)}。`)
  if (!identity(value.session_id) || typeof value.ready !== 'boolean' || typeof value.reason !== 'string'
    || (value.last_sequence !== undefined && (!Number.isSafeInteger(value.last_sequence) || (value.last_sequence as number) < 0))
    || !capability(value.asr) || !record(value.capabilities)
    || !Object.values(value.capabilities).every((item) => typeof item === 'boolean' || typeof item === 'string' || (Array.isArray(item) && item.every((part) => typeof part === 'string')))
    || !(value.task === null || (record(value.task) && (value.task.id === null || identity(value.task.id)) && identity(value.task.status)))) {
    throw new Error('语音服务状态不完整，已禁止执行。')
  }
  if (value.latest_command !== null) validateVoiceCommand(value.latest_command)
  return value as VoiceState
}
export function validateVoiceTranscript(value: unknown): VoiceTranscript {
  if (!record(value) || !identity(value.text) || !identity(value.asr_id) || !identity(value.session_id) || !finite(value.received_at_ms)
    || !finite(value.expires_at_ms) || value.expires_at_ms <= value.received_at_ms
    || value.expires_at_ms - value.received_at_ms > VOICE_AUDIO_TTL_MS) throw new Error('转写响应缺少有效时限，请重新录音。')
  validateVoiceParse(value.parse)
  return value as VoiceTranscript
}
export function voiceAudioError(audio: Blob): string | null {
  if (!audio.size) return '音频为空，请重新录音或选择文件。'
  if (audio.size > VOICE_AUDIO_MAX_BYTES) return '音频超过 4 MiB，请缩短到 15 秒以内。'
  if (!/^(audio\/(webm|ogg|wav|x-wav|wave))(;.*)?$/i.test(audio.type)) return '请选择 WebM、Ogg 或 WAV 音频。'
  return null
}
export function voiceTranscriptExpired(transcript: VoiceTranscript | null, now: number): boolean {
  return transcript !== null && (now >= transcript.expires_at_ms || now - transcript.received_at_ms >= VOICE_AUDIO_TTL_MS)
}
function unknownTaskCanStop(snapshot: VoiceSnapshot): boolean {
  const { state, receipt } = snapshot
  if (!state || !receipt?.unknown || state.session_id !== receipt.envelope.session_id) return false
  const { task, latest_command: latest } = state
  // Only a GET readback may bind an unknown original motion to a new STOP.
  // A lost STOP receipt must never authorize another cancellation command.
  return !!task?.id && task.id === receipt.envelope.command_id && task.owner === `voice:${state.session_id}`
    && (task.task_id === undefined || task.task_id === task.id)
    && latest?.command_id === receipt.envelope.command_id && latest.task_id === task.id
    && (latest.session_id === undefined || latest.session_id === state.session_id)
    && (receipt.command === null || (receipt.command.command_id === receipt.envelope.command_id
      && (receipt.command.task_id === undefined || receipt.command.task_id === task.id)
      && (receipt.command.session_id === undefined || receipt.command.session_id === state.session_id)))
}
export function voiceExecuteReason(snapshot: VoiceSnapshot, now: number): string | null {
  if (snapshot.pending) return '正在处理上一项操作。'
  if (!snapshot.state || snapshot.connectionError) return '请先连接语音服务。'
  if (snapshot.receivedAt === null || now - snapshot.receivedAt >= VOICE_STATE_MAX_AGE_MS) return '服务状态已过期，请手动刷新。'
  if (!snapshot.preview?.accepted || !snapshot.preview.intent) return snapshot.preview?.reason || '请先预览任务。'
  const stop = snapshot.preview.intent === 'STOP'
  if (snapshot.receipt?.unknown && !(stop && unknownTaskCanStop(snapshot))) return '执行回执未知，请用原命令编号刷新状态。'
  if (voiceTranscriptExpired(snapshot.transcript, now)) return '这段音频已超过 5 秒，请重新录音或上传。'
  if (snapshot.transcript && snapshot.transcript.session_id !== snapshot.state.session_id) return '转写会话已变化，请重新录音或上传。'
  const current = voiceCapability(snapshot.state, snapshot.preview.intent)
  if (!current.available) return current.reason || '当前服务未提供此任务能力。'
  const active = ['submitting', 'running', 'unknown', 'accepted', 'canceling', 'task_unknown']
  const taskStatus = snapshot.state.task?.status || snapshot.receipt?.command?.status || 'idle'
  if (stop && active.includes(taskStatus)) return null
  if (stop) return '当前没有语音拥有的任务可停止。'
  if (!stop && (active.includes(taskStatus) || snapshot.receipt?.command?.status === 'task_unknown')) return '已有语音任务尚未结束，请先刷新状态或预览“停止”。'
  if (!snapshot.state.ready) return snapshot.state.reason || '仿真尚未就绪。'
  return null
}
export const VOICE_INTENT_LABELS: Record<string, string> = {
  move: '直线移动', forward: '前进', backward: '后退', turn: '转向', rotate: '转向',
  return_home: '返航', home: '返航', transport: '装货运输', stop: '停止当前语音任务', recharge: '回充',
  FORWARD: '前进', BACKWARD: '后退', TURN_LEFT: '向左转', TURN_RIGHT: '向右转', STOP: '停止当前语音任务',
  RETURN_HOME: '返航', GOTO: '前往地点', TRANSPORT: '装货运输', DOCK: '回充',
}
export function voiceCapability(state: VoiceState, intent: string): VoiceCapability {
  const reason = state.capabilities[`${intent.toLowerCase()}_reason`] ?? state.capabilities[`${intent}_reason`]
  const unavailable = ({ RETURN_HOME: '本次语音会话尚未记录返航起点。', TRANSPORT: '装货运输服务尚未就绪。',
    GOTO: '尚未配置可前往的地点。', DOCK: '未配置有效回充适配器。' } as Record<string, string>)[intent] || '当前服务未提供此任务能力。'
  const available = state.capabilities[intent] === true
  return { available, reason: typeof reason === 'string' ? reason : available ? '' : unavailable }
}
export function voiceReasonLabel(reason: string): string {
  const label = ({ ready: '服务已就绪', accepted: '已识别，请检查参数后确认', parsed: '已解析',
    unknown_intent: '未识别出支持的任务，请换一个简短指令', invalid_text: '输入内容无效', empty_text: '请输入任务',
    text_too_long: '输入过长，请缩短任务', negated_command: '检测到否定指令，不执行动作',
    multiple_actions: '一次只支持一个任务，请拆开输入', invalid_distance: '距离须在 5 厘米至 1 米之间，且只填写一个距离',
    invalid_angle: '转角须大于 0 度且不超过 180 度，且只填写一个角度', invalid_number: '数字格式无法识别',
    unexpected_quantity: '此任务不接受距离或角度参数', unsupported_text: '指令包含无法确认的内容，请简化输入',
    invalid_place: '地点名称无法识别', place_not_configured: '该地点尚未配置',
    charging_dock_adapter_not_configured: '尚未配置有效回充适配器', charging_dock_not_ready: '回充适配器尚未就绪',
    charging_adapter_purpose_unconfirmed: '尚未确认适配器用于充电',
    local_asr_unavailable: '本地转写不可用，请输入文字', asr_failed: '音频转写失败，请重新录音或输入文字',
    vosk_or_model_missing: '离线识别引擎或中文模型尚未配置，请输入文字', silence: '没有检测到清晰的声音，请重新录音',
    asr_busy: '正在处理另一段录音，请稍后再试', audio_duration: '每段音频须为 0.15 至 15 秒',
    model_load_failed: '离线中文模型加载失败，请检查安装',
    audio_type_unsupported: '音频格式不支持，请使用 WebM、Ogg 或 WAV', audio_size_invalid: '音频为空或超过 4 MiB',
    asr_source_expired: '音频来源已超过 5 秒，请重新录音或上传', asr_source_missing_or_expired: '音频来源已过期，请重新录音或上传',
    asr_source_mismatch: '转写文字与音频来源不一致，请重新预览', asr_source_already_used: '该音频已经执行过，请重新录音',
    mission_not_ready: '导航服务尚未就绪', cooperation_not_ready: '装货运输服务尚未就绪',
    upstream_task_busy: '上游任务正在运行', upstream_state_unavailable: '无法读取上游任务服务',
    upstream_domain_mismatch: '上游服务 ROS 域不匹配', upstream_simulation_mode_required: '上游服务不是仿真模式',
    owned_task_busy_or_unknown: '当前语音任务尚未结束或回执未知', no_owned_task: '当前没有语音拥有的任务可停止',
    owned_task_id_not_current: '当前任务归属不一致，已拒绝停止', voice_home_not_captured: '本次会话尚未记录返航起点',
    voice_home_map_changed: '地图已变化，原返航起点失效', command_expired_or_future: '命令已过期或系统时钟不一致',
    session_mismatch: '服务会话已变化，请重新连接', sequence_replayed: '命令序号已使用，请刷新服务状态',
    upstream_receipt_unknown: '上游任务回执未知，请保留原命令编号并刷新状态',
  } as Record<string, string>)[reason]
  return label ? `${label}（${reason}）` : reason
}
export function voiceIntentLabel(intent: string | null): string { return intent ? VOICE_INTENT_LABELS[intent] || intent : '未识别' }
export function voiceStatusLabel(status: string): string {
  return ({ accepted: '已接受，等待任务反馈', submitting: '正在等待上游确认', running: '任务进行中', succeeded: '任务报告成功',
    completed: '任务报告完成', canceled: '任务已取消', canceling: '正在取消，等待终态',
    rejected: '命令已拒绝', failed: '任务失败', idle: '等待任务', unknown: '状态未知', task_unknown: '上游任务状态未知' } as Record<string, string>)[status] || status
}

export class VoiceController {
  private snapshot: VoiceSnapshot = { ...EMPTY_VOICE_SNAPSHOT }
  private listeners = new Set<() => void>()
  private sequence = 0
  private revision = 0
  private fetcher: typeof fetch
  private now: () => number
  private commandId: () => string
  readonly expectedDomain: number
  constructor(options: { fetcher?: typeof fetch; now?: () => number; commandId?: () => string; expectedDomain?: number } = {}) {
    this.fetcher = options.fetcher ?? ((input, init) => runtimeFetch('voice', input, init))
    this.now = options.now ?? Date.now
    this.commandId = options.commandId ?? (() => crypto.randomUUID())
    this.expectedDomain = options.expectedDomain ?? VOICE_DOMAIN
  }
  getSnapshot = (): VoiceSnapshot => this.snapshot
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  private update(patch: Partial<VoiceSnapshot>) { this.snapshot = { ...this.snapshot, ...patch }; this.listeners.forEach((listener) => listener()) }
  setText(text: string) { this.revision++; this.update({ text, preview: null, transcript: null, actionError: null }) }
  private async request(path: string, init?: RequestInit): Promise<unknown> {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 15000)
    try {
      const response = await this.fetcher(`/voice-api/${path}`, { ...init, signal: controller.signal, cache: 'no-store' })
      const body: unknown = await runtimeJson(response)
      if (path !== 'execute' && record(body) && body.status === 'rejected' && body.accepted === false) {
        throw new VoiceRejectedError(typeof body.reason === 'string' ? body.reason : '语音服务已拒绝本次请求。')
      }
      if (!response.ok && !(record(body) && body.status === 'rejected')) {
        const reason = record(body) && typeof body.reason === 'string' ? body.reason
          : record(body) && typeof body.error === 'string' ? body.error : `语音服务返回 ${response.status}。`
        if (record(body) && body.outcome === 'rejected') throw new VoiceRejectedError(reason)
        throw new Error(reason)
      }
      return body
    } finally { clearTimeout(timer) }
  }
  async connect(): Promise<void> {
    if (this.snapshot.pending) return
    this.update({ pending: 'connect', connectionError: null })
    try {
      const state = validateVoiceState(await this.request('state'), this.expectedDomain)
      if (state.last_sequence !== undefined) this.sequence = Math.max(this.sequence, state.last_sequence)
      if (Number.isInteger(state.latest_command?.sequence)) this.sequence = Math.max(this.sequence, state.latest_command!.sequence!)
      const receipt = this.snapshot.receipt
      const recovered = receipt?.unknown && state.session_id === receipt.envelope.session_id
        && state.latest_command?.command_id === receipt.envelope.command_id
      const changed = this.snapshot.state && this.snapshot.state.session_id !== state.session_id
      if (changed) this.revision++
      this.update({ state, receivedAt: this.now(), connectionError: null,
        ...(changed ? { preview: null, transcript: null } : {}),
        ...(recovered ? { receipt: { ...receipt, unknown: state.latest_command!.status === 'task_unknown', command: state.latest_command },
          actionError: state.latest_command!.status === 'task_unknown' ? '原命令的上游任务状态未知，请继续刷新，不要重发。' : null } : {}),
      })
    } catch (error) { this.update({ connectionError: `语音服务连接失败：${errorMessage(error, '请检查服务后手动重连。')}` }) }
    finally { this.update({ pending: null }) }
  }
  async preview(): Promise<void> {
    if (this.snapshot.pending || !this.snapshot.state || this.snapshot.connectionError || !this.snapshot.text.trim()) return
    const revision = this.revision
    const text = this.snapshot.text
    this.update({ pending: 'preview', preview: null, actionError: null })
    try {
      const parsed = validateVoiceParse(await this.request('preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) }))
      if (revision === this.revision) this.update({ preview: parsed })
    } catch (error) { if (revision === this.revision) this.update({ actionError: errorMessage(error, '任务预览失败。') }) }
    finally { this.update({ pending: null }) }
  }
  async transcribe(audio: Blob): Promise<void> {
    if (this.snapshot.pending || !this.snapshot.state?.asr.available || this.snapshot.connectionError) return
    const invalid = voiceAudioError(audio)
    this.revision++
    const revision = this.revision
    this.update({ preview: null, transcript: null, actionError: invalid })
    if (invalid) return
    this.update({ pending: 'transcribe' })
    try {
      const transcript = validateVoiceTranscript(await this.request('transcribe', { method: 'POST', headers: { 'Content-Type': audio.type }, body: audio }))
      if (transcript.session_id !== this.snapshot.state?.session_id) throw new Error('转写会话已变化，请重新连接语音服务。')
      if (revision === this.revision) this.update({ text: transcript.text, transcript, preview: transcript.parse })
    } catch (error) { if (revision === this.revision) this.update({ actionError: errorMessage(error, '音频转写失败，请上传音频或输入文字。') }) }
    finally { this.update({ pending: null }) }
  }
  async execute(): Promise<void> {
    const reason = voiceExecuteReason(this.snapshot, this.now())
    if (reason) { this.update({ actionError: reason }); return }
    const state = this.snapshot.state!
    let id: string
    try { id = this.commandId() } catch { this.update({ actionError: '当前页面无法生成安全命令编号，请使用 localhost 或 HTTPS 打开。' }); return }
    const envelope: VoiceEnvelope = { command_id: id, session_id: state.session_id, sequence: ++this.sequence,
      issued_at_ms: this.now(), ttl_ms: VOICE_AUDIO_TTL_MS, text: this.snapshot.text,
      ...(this.snapshot.transcript ? { asr_id: this.snapshot.transcript.asr_id } : {}),
    }
    this.update({ pending: 'execute', actionError: null, receipt: { envelope, unknown: true, command: null }, preview: null })
    try {
      const result = await this.request('execute', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(envelope) })
      const command = validateVoiceCommand(record(result) && result.accepted === false && result.status === 'rejected' && result.command_id === undefined
        ? { ...result, command_id: envelope.command_id } : result)
      if (command.command_id !== envelope.command_id) throw new Error('返回的命令编号不匹配。')
      if (command.session_id !== undefined && command.session_id !== envelope.session_id) throw new Error('返回的服务会话不匹配。')
      this.update({ receipt: { envelope, unknown: command.accepted === null || ['task_unknown', 'unknown'].includes(command.status), command },
        state: command.task ? { ...state, task: command.task } : { ...state, task: command.task_id ? { id: command.task_id, status: command.status } : state.task },
        actionError: command.status === 'rejected' ? command.reason || '命令已拒绝。' : null })
    } catch (error) {
      if (error instanceof VoiceRejectedError) {
        this.update({ receipt: { envelope, unknown: false, command: { command_id: envelope.command_id, status: 'rejected', reason: error.message } }, actionError: error.message })
      } else this.update({ actionError: `执行回执未知：${errorMessage(error, '连接中断。')} 请刷新状态核对原命令，勿重复执行。` })
    } finally { this.update({ pending: null }) }
  }
}
function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.name === 'AbortError') return '语音服务请求超时。'
  return error instanceof Error ? error.message : fallback
}
