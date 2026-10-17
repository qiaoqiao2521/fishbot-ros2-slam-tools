import type { CooperationEvent, CooperationReceipt, CooperationTask } from './cooperation'
import type { SimulationState } from './simulation'
import type { VoiceCommand, VoiceReceipt, VoiceTask } from './voice'

export type EvidenceState = 'unsupported' | 'unknown' | 'idle' | 'pending' | 'accepted' | 'rejected'
  | 'running' | 'canceling' | 'succeeded' | 'failed' | 'canceled' | 'retrying' | 'unresolved' | 'confirmed'
export type EvidenceLayer = { state: EvidenceState; label: string; detail: string }
export type CommandEvidence = {
  owner: 'mission' | 'cooperation' | 'voice' | 'topic-publication'
  commandId: string | null
  taskId: string | null
  correlation: 'matched' | 'unmatched' | 'unbound'
  submission: EvidenceLayer
  execution: EvidenceLayer & {
    reportedStatus: string | null; nativeGoalId: string | null; nativeStatus: number | null
    nativeErrorCode: number | null; missedWaypointCount: number | null
  }
  cleanup: EvidenceLayer
  physical: EvidenceLayer
}
export type CommandEvidenceOptions = {
  pending?: boolean
  receiptUnknown?: boolean
  expectedTaskId?: string | null
}
/** Optional wire fields remain unknown until this presentation boundary checks them. */
type TaskEvidenceFields = {
  native_goal_id?: unknown; native_status?: unknown; native_error_code?: unknown
  missed_waypoints?: unknown; physical_result?: unknown
}

const labels: Record<EvidenceState, string> = {
  unsupported: '未提供证据', unknown: '结果未知', idle: '尚未提交', pending: '等待回执',
  accepted: '已接纳', rejected: '已拒绝', running: '执行中', canceling: '取消中', succeeded: '原生成功',
  failed: '原生失败', canceled: '原生已取消', retrying: '清理重试中', unresolved: '清理未确认', confirmed: '清理已确认',
}
function layer(state: EvidenceState, detail: string): EvidenceLayer { return { state, label: labels[state], detail } }
function identity(value: unknown): value is string { return typeof value === 'string' && value.trim().length > 0 }
function fields(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}
function targetMatches(observed: string | null | undefined, expected: string | null | undefined): boolean {
  return !identity(expected) || observed === expected
}
function empty(owner: CommandEvidence['owner'], taskId: string | null): CommandEvidence {
  return {
    owner, taskId, commandId: null, correlation: taskId ? 'matched' : 'unbound',
    submission: layer('idle', '尚无本次提交回执。'),
    execution: { ...layer('unsupported', '服务未提供可关联的原生动作回执。'), reportedStatus: null,
      nativeGoalId: null, nativeStatus: null, nativeErrorCode: null, missedWaypointCount: null },
    cleanup: layer('unsupported', '服务未提供清理确认；任务终态不代替清理证据。'),
    physical: layer('unsupported', '未提供独立物理评分；任务完成不代表物理通过。'),
  }
}
function unmatched(result: CommandEvidence): CommandEvidence {
  result.correlation = 'unmatched'
  result.submission = layer('unknown', '观测不属于本次请求，保留原回执并核对原任务。')
  result.execution = { ...result.execution, ...layer('unknown', '已忽略其他任务或会话的状态。') }
  return result
}

/** Read-only presentation. This never decides admission, cancellation or retries. */
function projectTask(result: CommandEvidence, task: unknown): void {
  const record = fields(task)
  const upstream = fields(record.upstream_record)
  // Voice delegates the original result. Never borrow another task/Goal's result fields.
  const boundUpstream = upstream.id === result.taskId && identity(result.taskId)
    && identity(upstream.native_goal_id) && upstream.native_goal_id === record.native_goal_id ? upstream : {}
  const errorCode = record.native_error_code !== undefined ? record.native_error_code : boundUpstream.native_error_code
  const missed = record.missed_waypoints !== undefined ? record.missed_waypoints : boundUpstream.missed_waypoints
  const validCode = typeof errorCode === 'number' && Number.isSafeInteger(errorCode)
  const validMissed = Array.isArray(missed) && missed.length <= 4096 && missed.every((item) => {
    const waypoint = fields(item)
    return Number.isSafeInteger(waypoint.index) && (waypoint.index as number) >= 0 && Number.isSafeInteger(waypoint.error_code)
  })
  result.execution.reportedStatus = typeof record.status === 'string' ? record.status : null
  const id = record.native_goal_id, status = record.native_status
  const hasNative = id != null || status != null
  if (hasNative) {
    const validId = typeof id === 'string' && /^(?:[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$/i.test(id)
    const validStatus = typeof status === 'number' && Number.isInteger(status) && status >= 0 && status <= 6
    result.execution = {
      ...layer('unknown', '原生目标编号或状态不完整，不能确认原生动作结果。'),
      reportedStatus: result.execution.reportedStatus,
      nativeGoalId: validId ? id : null, nativeStatus: validStatus ? status : null,
      nativeErrorCode: validCode ? errorCode : null, missedWaypointCount: validMissed ? missed.length : null,
    }
    if (validId && validStatus) {
      const nativeState = (['unknown', 'accepted', 'running', 'canceling', 'succeeded', 'canceled', 'failed'] as const)[status]
      Object.assign(result.execution, layer(nativeState, `原生 Goal ${id}，ROS 动作状态 ${status}。`))
      if (status === 4) {
        if ((validCode && errorCode !== 0) || (validMissed && missed.length > 0)) {
          Object.assign(result.execution, { ...layer('failed', `ROS 动作状态仍为 4；错误码 ${validCode ? errorCode : '未提供'}，漏跑航点 ${validMissed ? missed.length : '未提供'}。不能视为完整任务成功。`),
            label: '动作返回成功，任务结果失败' })
        } else if (!validCode || !validMissed) {
          Object.assign(result.execution, { ...layer('unknown', 'ROS 动作状态为 4，但错误码或漏跑航点明细缺失／无效，不能确认完整任务成功。'),
            label: '动作终态成功，任务结果未确认' })
        }
      }
    }
  }
  if (record.cleanup_state === 'retrying' || record.cleanup_state === 'unresolved') {
    result.cleanup = layer(record.cleanup_state, '等待原任务的清理结果；取消请求不等于车辆已经停稳。')
  }
  // Existing payloads have no shared, independently verified physical-score schema.
  if (record.physical_result != null) result.physical = layer('unknown', '收到物理结果字段，尚未提供可核验的独立评分合同。')
}

export function projectMissionEvidence(mission: (SimulationState['mission'] & TaskEvidenceFields) | null,
  options: CommandEvidenceOptions = {}): CommandEvidence {
  const result = empty('mission', options.expectedTaskId ?? mission?.id ?? null)
  if (options.pending || options.receiptUnknown) {
    result.taskId = options.expectedTaskId ?? null
    result.correlation = result.taskId ? 'matched' : 'unbound'
    result.submission = layer(options.receiptUnknown ? 'unknown' : 'pending', '新派发尚未核对到对应任务，不采用此前任务的终态。')
    result.execution = { ...result.execution, ...layer('unknown', '等待原任务 owner 核对本次派发；不从旧快照推断执行结果。') }
    return result
  }
  if (!mission) return result
  if (!targetMatches(mission.id, options.expectedTaskId)) return unmatched(result)
  projectTask(result, mission)
  if (options.receiptUnknown || mission.dispatch_state === 'unavailable') {
    result.submission = layer('unknown', '提交回执未知，只核对原任务，不自动重发。')
  } else if (options.pending || mission.dispatch_state === 'pending') {
    result.submission = layer('pending', '等待本次提交回执，不代表原生动作已经执行。')
  } else if (mission.dispatch_state === 'accepted') {
    result.submission = layer('accepted', '任务桥报告已接纳；原生执行证据单独列出。')
  } else if (mission.dispatch_state === 'rejected') {
    result.submission = layer('rejected', mission.stop_reason || mission.message || '任务桥明确拒绝本次派发。')
  } else if (mission.status !== 'idle') {
    result.submission = layer('unknown', '服务未提供派发回执，不能从任务状态推断接纳。')
  }
  return result
}

export function projectCooperationEvidence(task: (CooperationTask & TaskEvidenceFields) | null, receipt: CooperationReceipt | null,
  options: CommandEvidenceOptions = {}): CommandEvidence {
  const expectedId = options.expectedTaskId ?? receipt?.taskId
  const result = empty('cooperation', expectedId ?? task?.id ?? null)
  if (task && !targetMatches(task.id, expectedId)) return unmatched(result)
  if (task) projectTask(result, task)
  if (options.receiptUnknown || receipt?.unknown) result.submission = layer('unknown', '协同回执未知，只读取原任务。')
  else if (options.pending) result.submission = layer('pending', '协同请求正在提交。')
  else if (receipt) result.submission = layer('accepted', receipt.action === 'cancel'
    ? '取消请求已收到回执，仍需等待原任务终态。' : '开始请求已收到回执，仍需等待原任务执行反馈。')
  else if (task && task.status !== 'idle') result.submission = layer('unsupported', '任务状态已上报，当前快照未保留提交回执。')
  return result
}

export type VoiceEvidenceOptions = CommandEvidenceOptions & {
  receipt?: VoiceReceipt | null
  expectedCommandId?: string | null
  expectedSessionId?: string | null
}
export function projectVoiceEvidence(command: VoiceCommand | null, task: (VoiceTask & TaskEvidenceFields) | null,
  options: VoiceEvidenceOptions = {}): CommandEvidence {
  const expectedCommand = options.expectedCommandId ?? options.receipt?.envelope.command_id
  const expectedSession = options.expectedSessionId ?? options.receipt?.envelope.session_id
  const expectedTask = options.expectedTaskId ?? command?.task_id ?? command?.task?.id
  const result = empty('voice', expectedTask ?? null)
  result.commandId = expectedCommand ?? command?.command_id ?? null
  if (command && (!targetMatches(command.command_id, expectedCommand)
    || (identity(expectedSession) && command.session_id !== undefined && command.session_id !== expectedSession))) return unmatched(result)
  if (identity(expectedTask) && ((task && task.id !== expectedTask)
    || (identity(command?.task_id) && command.task_id !== expectedTask))) return unmatched(result)
  if (command) {
    if (identity(expectedTask) && task?.id === expectedTask) projectTask(result, task)
    else if (command.task && command.task.id === expectedTask) projectTask(result, command.task)
    else result.execution.reportedStatus = command.status
  }
  if (options.receiptUnknown || options.receipt?.unknown || command?.accepted === null
    || command?.status === 'unknown' || command?.status === 'task_unknown') {
    result.submission = layer('unknown', '语音命令回执未知，核对原命令编号，不重放运动。')
  } else if (options.pending) result.submission = layer('pending', '语音命令正在提交。')
  else if (command?.status === 'rejected' || command?.accepted === false) result.submission = layer('rejected', command.reason || '语音命令已明确拒绝。')
  else if (command?.accepted === true) result.submission = layer('accepted', '语音服务已接纳，原生动作和物理评分分别核对。')
  else if (command) result.submission = layer('unknown', '服务未提供明确接纳字段，任务状态不能代替提交回执。')
  return result
}

export function projectLegacyPublicationEvidence(publication: {
  state: 'idle' | 'pending' | 'published' | 'rejected' | 'unknown'
  reason?: string | null
}): CommandEvidence {
  const result = empty('topic-publication', null)
  result.submission = publication.state === 'published'
    ? layer('accepted', '发布接口已返回；未提供原生 Goal UUID 或执行终态。')
    : layer(publication.state, publication.reason || '仅展示发布接口结果，不推断机器人动作。')
  return result
}

export type EventSequenceScope = { instanceId: string; episodeId: string | null; taskId: string | null }
export type SequenceRange = { from: number; to: number }
export type EventSequenceCursor = {
  scope: EventSequenceScope
  observed: SequenceRange[]
  highWaterMark: number
  truncated: boolean
}
export type EventSequenceEvidence = {
  cursor: EventSequenceCursor
  gaps: SequenceRange[]
  hasGaps: boolean | null
  duplicateCount: number
  outOfOrderCount: number
  invalidCount: number
  scopeChanged: boolean
  staleSnapshot: boolean
  label: string
}
function sameScope(left: EventSequenceScope, right: EventSequenceScope): boolean {
  return left.instanceId === right.instanceId && left.episodeId === right.episodeId && left.taskId === right.taskId
}

/** Track observed source numbers only. Bounded ranges store no messages and never synthesize events. */
export function observeEventSequence(previous: EventSequenceCursor | null, scope: EventSequenceScope,
  events: readonly Pick<CooperationEvent, 'sequence'>[], limit = 256): EventSequenceEvidence {
  if (!identity(scope.instanceId) || ![scope.episodeId, scope.taskId].every((id) => id === null || identity(id))) throw new Error('事件来源标识无效。')
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 4096) throw new Error('事件采样上限必须为 1–4096。')
  const scopeChanged = previous !== null && !sameScope(previous.scope, scope)
  const prior = !scopeChanged ? previous : null
  let ranges = (prior?.observed ?? []).map((range) => ({ ...range }))
  let highWaterMark = prior?.highWaterMark ?? 0
  let truncated = (prior?.truncated ?? false) || events.length > limit || ranges.length > limit
  ranges = ranges.slice(-limit)
  let duplicateCount = 0, outOfOrderCount = 0, invalidCount = 0, snapshotMax = 0, last = 0
  for (const event of events.slice(-limit)) {
    const sequence = event.sequence
    if (!Number.isSafeInteger(sequence) || sequence < 1) { invalidCount++; continue }
    if (sequence < last) outOfOrderCount++
    last = sequence
    snapshotMax = Math.max(snapshotMax, sequence)
    if (ranges.some((range) => sequence >= range.from && sequence <= range.to)) duplicateCount++
    const incoming = [...ranges, { from: sequence, to: sequence }].sort((a, b) => a.from - b.from)
    ranges = []
    for (const range of incoming) {
      const tail = ranges.at(-1)
      if (tail && range.from - 1 <= tail.to) tail.to = Math.max(tail.to, range.to)
      else ranges.push({ ...range })
    }
    if (ranges.length > limit) { truncated = true; ranges = ranges.slice(-limit) }
    highWaterMark = Math.max(highWaterMark, sequence)
  }
  const gaps: SequenceRange[] = []
  if (!truncated) {
    let next = 1
    for (const range of ranges) {
      if (range.from > next) gaps.push({ from: next, to: range.from - 1 })
      next = range.to + 1
    }
  }
  const staleSnapshot = !!prior && snapshotMax > 0 && snapshotMax < prior.highWaterMark
  const hasGaps = truncated ? null : gaps.length > 0
  const label = truncated ? '事件采样达到上限，连续性未知'
    : invalidCount ? '事件含无效序号，不能确认快照完整'
      : hasGaps ? `事件有 ${gaps.length} 段缺口，未补造记录`
        : staleSnapshot ? '收到旧事件快照，保留较新记录'
          : highWaterMark ? '已观测序号连续；不代表过程采样完整' : '尚无事件观测'
  return { cursor: { scope: { ...scope }, observed: ranges, highWaterMark, truncated }, gaps, hasGaps,
    duplicateCount, outOfOrderCount, invalidCount, scopeChanged, staleSnapshot, label }
}
