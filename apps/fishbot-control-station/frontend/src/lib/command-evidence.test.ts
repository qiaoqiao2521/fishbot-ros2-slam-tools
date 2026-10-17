import { describe, expect, it, vi } from 'vitest'

import {
  observeEventSequence, projectCooperationEvidence, projectLegacyPublicationEvidence,
  projectMissionEvidence, projectVoiceEvidence,
} from './command-evidence'
import type { CooperationTask } from './cooperation'
import type { SimulationState } from './simulation'
import type { VoiceReceipt, VoiceTask } from './voice'

const nativeId = '0123456789abcdef0123456789abcdef'
const mission: SimulationState['mission'] = {
  id: 'task-a', status: 'running', current_index: 0, waypoints: [], return_home: false,
  message: '任务运行中', dispatch_state: 'accepted',
}
const task: CooperationTask = { id: 'task-a', status: 'running', stage: 'car_to_dock', message: '前往工位' }
const voiceTask: VoiceTask = { id: 'task-a', status: 'running' }
const scope = { instanceId: 'sim:121', episodeId: 'episode-a', taskId: 'task-a' }
const events = (...sequences: number[]) => sequences.map((sequence) => ({ sequence }))
const receipt: VoiceReceipt = {
  envelope: { command_id: 'command-a', session_id: 'session-a', sequence: 1, issued_at_ms: 10, ttl_ms: 5000, text: '前进' },
  unknown: true, command: null,
}

describe('independent command evidence layers', () => {
  it('never upgrades a legacy HTTP publication to native execution or physical success', () => {
    const result = projectLegacyPublicationEvidence({ state: 'published' })
    expect(result.submission.state).toBe('accepted')
    expect(result.execution).toMatchObject({ state: 'unsupported', nativeGoalId: null, nativeStatus: null })
    expect(result.physical.state).toBe('unsupported')
    expect(result.submission.detail).toContain('未提供原生 Goal UUID')
  })

  it('does not infer native execution from mission bridge admission and running status', () => {
    const result = projectMissionEvidence(mission)
    expect(result.submission.state).toBe('accepted')
    expect(result.execution).toMatchObject({ state: 'unsupported', reportedStatus: 'running', nativeGoalId: null })
    expect(result.cleanup.state).toBe('unsupported')
  })

  it('keeps an older backend without dispatch evidence unknown', () => {
    expect(projectMissionEvidence({ ...mission, dispatch_state: undefined }).submission.state).toBe('unknown')
    expect(projectMissionEvidence(null).submission.state).toBe('idle')
  })

  it('retains pending admission and explicit rejection without guessing native UUIDs', () => {
    expect(projectMissionEvidence({ ...mission, dispatch_state: 'pending' }).submission.state).toBe('pending')
    const refused = projectMissionEvidence({ ...mission, status: 'failed', dispatch_state: 'rejected', stop_reason: '规则阻挡' })
    expect(refused.submission).toMatchObject({ state: 'rejected', detail: '规则阻挡' })
    expect(refused.execution.state).toBe('unsupported')
  })

  it('retains unknown delivery even after a reported business terminal status', () => {
    const result = projectMissionEvidence({ ...mission, status: 'succeeded' }, { receiptUnknown: true })
    expect(result.submission.state).toBe('unknown')
    expect(result.execution).toMatchObject({ state: 'unknown', reportedStatus: null })
    expect(result.physical.state).toBe('unsupported')
  })

  it('does not display an old native success while a new dispatch is pending or unconfirmed', () => {
    const old = { ...mission, status: 'succeeded' as const, native_goal_id: nativeId, native_status: 4 }
    for (const options of [{ pending: true }, { receiptUnknown: true }]) {
      const result = projectMissionEvidence(old, options)
      expect(result.taskId).toBeNull()
      expect(result.execution).toMatchObject({ state: 'unknown', nativeGoalId: null, reportedStatus: null })
    }
    expect(projectMissionEvidence(null, { pending: true }).submission.state).toBe('pending')
  })

  it.each([
    [0, 'unknown'], [1, 'accepted'], [2, 'running'], [3, 'canceling'],
    [4, 'succeeded'], [5, 'canceled'], [6, 'failed'],
  ])('projects explicit correlated ROS action status %i only', (status, expected) => {
    const result = projectMissionEvidence({ ...mission, native_goal_id: nativeId, native_status: status, native_error_code: 0, missed_waypoints: [] })
    expect(result.execution).toMatchObject({ state: expected, nativeGoalId: nativeId, nativeStatus: status })
    expect(result.physical.state).toBe('unsupported')
    expect(result.cleanup.state).toBe('unsupported')
  })

  it.each([
    { native_error_code: 601, missed_waypoints: [] },
    { native_error_code: 0, missed_waypoints: [{ index: 2, error_code: 602 }] },
    { native_error_code: 601, missed_waypoints: [{ index: 2, error_code: 602 }] },
  ])('does not confuse Action SUCCEEDED with a complete task result: %o', (business) => {
    const input = { ...mission, status: 'failed' as const, native_goal_id: nativeId, native_status: 4, ...business }
    const before = structuredClone(input)
    const result = projectMissionEvidence(input)
    expect(result.execution).toMatchObject({ state: 'failed', nativeStatus: 4, reportedStatus: 'failed',
      nativeErrorCode: business.native_error_code, missedWaypointCount: business.missed_waypoints.length })
    expect(result.execution.label).toBe('动作返回成功，任务结果失败')
    expect(result.physical.state).toBe('unsupported')
    expect(input).toEqual(before)
  })

  it.each([
    {}, { native_error_code: 0 }, { missed_waypoints: [] },
    { native_error_code: '0', missed_waypoints: [] },
    { native_error_code: 0, missed_waypoints: null },
    { native_error_code: 0, missed_waypoints: [null] },
    { native_error_code: 0, missed_waypoints: [{ index: '1', error_code: 0 }] },
  ])('does not manufacture zero errors or empty missed-waypoint results: %o', (business) => {
    const result = projectMissionEvidence({ ...mission, native_goal_id: nativeId, native_status: 4, ...business })
    expect(result.execution).toMatchObject({ state: 'unknown', nativeStatus: 4 })
    expect(result.execution.label).toContain('任务结果未确认')
  })

  it.each([
    { native_status: 4 }, { native_goal_id: nativeId },
    { native_goal_id: 'task-a', native_status: 4 }, { native_goal_id: nativeId, native_status: '4' },
    { native_goal_id: nativeId, native_status: 99 }, { native_goal_id: nativeId, native_status: Number.NaN },
  ])('keeps partial or malformed native evidence unknown: %o', (extra) => {
    expect(projectMissionEvidence({ ...mission, ...extra }).execution.state).toBe('unknown')
  })

  it('ignores an old task terminal result instead of resolving the current task', () => {
    const result = projectMissionEvidence({ ...mission, id: 'old-task', status: 'succeeded', native_goal_id: nativeId, native_status: 4 }, { expectedTaskId: 'new-task' })
    expect(result).toMatchObject({ correlation: 'unmatched', taskId: 'new-task', execution: { state: 'unknown', reportedStatus: null, nativeGoalId: null } })
  })

  it('keeps cancellation in progress and unresolved cleanup separate from cancellation success', () => {
    const result = projectMissionEvidence({ ...mission, status: 'canceling', cleanup_state: 'unresolved', native_goal_id: nativeId, native_status: 3 })
    expect(result.execution.state).toBe('canceling')
    expect(result.cleanup.state).toBe('unresolved')
    const terminal = projectMissionEvidence({ ...mission, status: 'canceled', cleanup_state: null, native_goal_id: nativeId, native_status: 5 })
    expect(terminal.execution.state).toBe('canceled')
    expect(terminal.cleanup.state).toBe('unsupported')
  })

  it('does not interpret an acceptance report or stopped car as a physical pass', () => {
    const result = projectCooperationEvidence({ ...task, status: 'succeeded' }, null)
    expect(result.execution).toMatchObject({ state: 'unsupported', reportedStatus: 'succeeded' })
    expect(result.physical.state).toBe('unsupported')
  })

  it('preserves exact cooperative receipt ownership and cancellation uncertainty', () => {
    const result = projectCooperationEvidence({ ...task, status: 'canceling' }, { action: 'cancel', taskId: 'task-a', unknown: true })
    expect(result.submission.state).toBe('unknown')
    expect(result.execution.reportedStatus).toBe('canceling')
    const other = projectCooperationEvidence({ ...task, id: 'task-b', status: 'succeeded' }, { action: 'start', taskId: 'task-a', unknown: false })
    expect(other).toMatchObject({ correlation: 'unmatched', taskId: 'task-a', execution: { reportedStatus: null } })
  })

  it('does not turn a known cancellation POST receipt into a canceled task', () => {
    const result = projectCooperationEvidence(task, { action: 'cancel', taskId: 'task-a', unknown: false })
    expect(result.submission.state).toBe('accepted')
    expect(result.submission.detail).toContain('仍需等待原任务终态')
    expect(result.execution.reportedStatus).toBe('running')
  })

  it('requires the original voice command and session before exposing terminal evidence', () => {
    for (const command of [
      { command_id: 'old-command', session_id: 'session-a', status: 'succeeded', accepted: true },
      { command_id: 'command-a', session_id: 'session-b', status: 'succeeded', accepted: true },
    ]) {
      const result = projectVoiceEvidence(command, voiceTask, { receipt })
      expect(result.correlation).toBe('unmatched')
      expect(result.execution.reportedStatus).toBeNull()
    }
  })

  it('does not let task_unknown or accepted null become delivery rejection', () => {
    const result = projectVoiceEvidence({ command_id: 'command-a', task_id: 'task-a', status: 'task_unknown', accepted: null }, voiceTask, { receipt })
    expect(result.submission.state).toBe('unknown')
    expect(result.execution.state).toBe('unsupported')
  })

  it('does not associate a command targeting another task with the expected task result', () => {
    const result = projectVoiceEvidence({ command_id: 'command-a', task_id: 'task-b', status: 'succeeded', accepted: true }, voiceTask,
      { expectedTaskId: 'task-a', expectedCommandId: 'command-a' })
    expect(result.correlation).toBe('unmatched')
    expect(result.execution.reportedStatus).toBeNull()
  })

  it('keeps native status and arbitrary physical payload independent', () => {
    const result = projectVoiceEvidence({ command_id: 'command-a', task_id: 'task-a', status: 'succeeded', accepted: true },
      { ...voiceTask, status: 'succeeded', native_goal_id: nativeId, native_status: 4,
        native_error_code: 0, missed_waypoints: [], physical_result: { passed: true } })
    expect(result.submission.state).toBe('accepted')
    expect(result.execution.state).toBe('succeeded')
    expect(result.physical.state).toBe('unknown')
  })

  it('reads delegated missed-waypoint evidence only from the exact task and native Goal', () => {
    const command = { command_id: 'command-a', task_id: 'task-a', status: 'failed', accepted: true }
    const upstream = { id: 'task-a', native_goal_id: nativeId, native_error_code: 0, missed_waypoints: [{ index: 1, error_code: 3 }] }
    const delegated = { ...voiceTask, native_goal_id: nativeId, native_status: 4, upstream_record: upstream }
    expect(projectVoiceEvidence(command, delegated).execution).toMatchObject({ state: 'failed', nativeStatus: 4, missedWaypointCount: 1 })
    for (const patch of [{ id: 'other-task' }, { native_goal_id: undefined }, { native_goal_id: 'ffffffffffffffffffffffffffffffff' }]) {
      expect(projectVoiceEvidence(command, { ...delegated, upstream_record: { ...upstream, ...patch } }).execution)
        .toMatchObject({ state: 'unknown', nativeStatus: 4, missedWaypointCount: null })
    }
  })

  it('keeps original objects intact and never sends or retries a command', () => {
    const fetcher = vi.fn()
    vi.stubGlobal('fetch', fetcher)
    try {
      const original = structuredClone(mission)
      const result = projectMissionEvidence(mission)
      result.execution.reportedStatus = 'changed'
      expect(mission).toEqual(original)
      expect(fetcher).not.toHaveBeenCalled()
    } finally { vi.unstubAllGlobals() }
  })
})

describe('bounded event sequence observations', () => {
  it('starts from source sequence one and identifies a snapshot leading gap', () => {
    const result = observeEventSequence(null, scope, events(4, 5))
    expect(result.gaps).toEqual([{ from: 1, to: 3 }])
    expect(result.hasGaps).toBe(true)
    expect(result.cursor.highWaterMark).toBe(5)
    expect(result.label).toContain('未补造')
  })

  it('keeps holes through a reconnect and closes them only when real sequence values arrive', () => {
    const first = observeEventSequence(null, scope, events(1, 3))
    const reconnected = observeEventSequence(first.cursor, scope, events(3, 4))
    expect(reconnected.gaps).toEqual([{ from: 2, to: 2 }])
    expect(reconnected.duplicateCount).toBe(1)
    const filled = observeEventSequence(reconnected.cursor, scope, events(2, 4, 5))
    expect(filled.gaps).toEqual([])
    expect(filled.hasGaps).toBe(false)
    expect(filled.label).toContain('不代表过程采样完整')
  })

  it('retains a newer cursor after late or empty snapshots', () => {
    const first = observeEventSequence(null, scope, events(1, 2, 3))
    const stale = observeEventSequence(first.cursor, scope, events(1, 2))
    expect(stale.staleSnapshot).toBe(true)
    expect(stale.cursor.highWaterMark).toBe(3)
    expect(observeEventSequence(stale.cursor, scope, []).cursor).toEqual(stale.cursor)
  })

  it.each([
    { ...scope, instanceId: 'sim:122' }, { ...scope, episodeId: 'episode-b' }, { ...scope, taskId: 'task-b' },
  ])('isolates another instance, episode or task: %o', (other) => {
    const previous = observeEventSequence(null, scope, events(1, 2, 3))
    const result = observeEventSequence(previous.cursor, other, events(2))
    expect(result.scopeChanged).toBe(true)
    expect(result.cursor.highWaterMark).toBe(2)
    expect(result.gaps).toEqual([{ from: 1, to: 1 }])
  })

  it('does not assume a backwards sequence is a reset without a changed source scope', () => {
    const previous = observeEventSequence(null, scope, events(1, 2, 3))
    const result = observeEventSequence(previous.cursor, scope, events(1))
    expect(result.scopeChanged).toBe(false)
    expect(result.staleSnapshot).toBe(true)
    expect(result.cursor.highWaterMark).toBe(3)
  })

  it('reports invalid zero, fractional and nonfinite sequences without manufacturing valid events', () => {
    const result = observeEventSequence(null, scope, events(0, -1, 1.5, Number.NaN, Infinity, 1))
    expect(result.invalidCount).toBe(5)
    expect(result.cursor.observed).toEqual([{ from: 1, to: 1 }])
    expect(result.label).toContain('不能确认快照完整')
  })

  it('reports duplicate and backwards values while preserving their actual coverage', () => {
    const result = observeEventSequence(null, scope, events(1, 3, 2, 2))
    expect(result.outOfOrderCount).toBe(1)
    expect(result.duplicateCount).toBe(1)
    expect(result.cursor.observed).toEqual([{ from: 1, to: 3 }])
  })

  it('bounds snapshot work and remains honest after retained ranges overflow', () => {
    const result = observeEventSequence(null, scope, events(1, 2, 3, 4), 2)
    expect(result.cursor.truncated).toBe(true)
    expect(result.hasGaps).toBeNull()
    expect(result.gaps).toEqual([])
    const repeated = observeEventSequence(result.cursor, scope, events(1, 2), 2)
    expect(repeated.hasGaps).toBeNull()
    let current = observeEventSequence(null, scope, events(1, 3), 2)
    current = observeEventSequence(current.cursor, scope, events(5), 2)
    expect(current.cursor.observed).toHaveLength(2)
    expect(current.cursor.truncated).toBe(true)
  })

  it('does not mutate the earlier cursor or reference a mutable scope', () => {
    const originalScope = { ...scope }
    const first = observeEventSequence(null, originalScope, events(1, 3))
    const saved = structuredClone(first.cursor)
    const second = observeEventSequence(first.cursor, scope, events(2))
    second.cursor.observed[0].to = 99
    originalScope.taskId = 'mutated'
    expect(first.cursor).toEqual(saved)
  })

  it('rejects invalid scope and unbounded limits', () => {
    expect(() => observeEventSequence(null, { ...scope, instanceId: '' }, [])).toThrow('来源标识')
    for (const limit of [0, 4097, 1.5, Infinity, Number.NaN]) expect(() => observeEventSequence(null, scope, [], limit)).toThrow('上限')
  })
})
