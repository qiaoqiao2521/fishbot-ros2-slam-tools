import { describe, expect, it, vi } from 'vitest'

import {
  EMPTY_VOICE_SNAPSHOT, VOICE_AUDIO_MAX_BYTES, VOICE_DOMAIN, VOICE_STATE_MAX_AGE_MS,
  VoiceController, validateVoiceState, validateVoiceTranscript, voiceAudioError,
  voiceExecuteReason, type VoiceParse, type VoiceSnapshot, type VoiceState, type VoiceTranscript,
} from '@/lib/voice'

const parse: VoiceParse = { accepted: true, intent: 'FORWARD', parameters: { distance_m: .4 }, reason: 'parsed' }
const state: VoiceState = { mode: 'simulation', domain: VOICE_DOMAIN, session_id: 'session-a', ready: true, reason: '已就绪',
  asr: { available: true, reason: '本地转写已就绪' }, capabilities: { FORWARD: true, STOP: true, DOCK: false, dock_reason: '未配置回充适配器' },
  latest_command: null, task: null }
const transcript: VoiceTranscript = { text: '前进40厘米', asr_id: 'asr-a', session_id: 'session-a', parse, received_at_ms: 10000, expires_at_ms: 15000 }
const snapshot: VoiceSnapshot = { ...EMPTY_VOICE_SNAPSHOT, state, text: '前进40厘米', preview: parse, receivedAt: 10000 }
function response(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status }) }
function deferred<T>() { let resolve!: (value: T) => void; return { promise: new Promise<T>((done) => { resolve = done }), resolve } }

describe('voice validation and execution gates', () => {
  it('only accepts the configured simulation domain and complete service identity', () => {
    expect(validateVoiceState(state)).toEqual(state)
    expect(() => validateVoiceState({ ...state, domain: 107 })).toThrow('ROS 域不匹配')
    expect(() => validateVoiceState({ ...state, mode: 'physical' })).toThrow('仅允许仿真')
    expect(() => validateVoiceState({ ...state, session_id: '' })).toThrow('状态不完整')
    expect(() => validateVoiceState({ ...state, capabilities: { FORWARD: {} } })).toThrow('状态不完整')
    expect(() => validateVoiceState({ ...state, latest_command: undefined })).toThrow('回执不完整')
    expect(validateVoiceState({ ...state, last_sequence: 42 }).last_sequence).toBe(42)
    for (const last_sequence of [-1, 1.5, '42', null, Number.NaN, Number.MAX_SAFE_INTEGER + 1]) {
      expect(() => validateVoiceState({ ...state, last_sequence })).toThrow('状态不完整')
    }
  })
  it('rejects missing or expanded ASR validity instead of extending the source lifetime', () => {
    expect(validateVoiceTranscript(transcript)).toEqual(transcript)
    expect(() => validateVoiceTranscript({ ...transcript, expires_at_ms: 15001 })).toThrow('有效时限')
    expect(() => validateVoiceTranscript({ ...transcript, session_id: null })).toThrow('有效时限')
  })
  it('uses raw standard audio types and enforces the byte bound before uploading', () => {
    expect(voiceAudioError(new Blob(['sound'], { type: 'audio/webm;codecs=opus' }))).toBeNull()
    expect(voiceAudioError(new Blob(['sound'], { type: 'audio/ogg' }))).toBeNull()
    expect(voiceAudioError(new Blob(['sound'], { type: 'audio/wav' }))).toBeNull()
    expect(voiceAudioError(new Blob([], { type: 'audio/wav' }))).toContain('为空')
    expect(voiceAudioError(new Blob(['sound'], { type: 'audio/mp3' }))).toContain('WebM')
    expect(voiceAudioError(new Blob([new Uint8Array(VOICE_AUDIO_MAX_BYTES + 1)], { type: 'audio/wav' }))).toContain('4 MiB')
  })
  it('requires a preview, capability, recent state, explicit source lifetime and readiness', () => {
    expect(voiceExecuteReason(snapshot, 10000)).toBeNull()
    expect(voiceExecuteReason({ ...snapshot, preview: null }, 10000)).toContain('先预览')
    expect(voiceExecuteReason({ ...snapshot, preview: { ...parse, accepted: false, reason: '距离超限' } }, 10000)).toBe('距离超限')
    expect(voiceExecuteReason({ ...snapshot, preview: { ...parse, intent: 'DOCK' } }, 10000)).toBe('未配置回充适配器')
    expect(voiceExecuteReason(snapshot, 10000 + VOICE_STATE_MAX_AGE_MS)).toContain('状态已过期')
    expect(voiceExecuteReason({ ...snapshot, state: { ...state, ready: false, reason: '仿真未启动' } }, 10000)).toBe('仿真未启动')
    expect(voiceExecuteReason({ ...snapshot, transcript }, 14999)).toBeNull()
    expect(voiceExecuteReason({ ...snapshot, transcript }, 15000)).toContain('超过 5 秒')
    expect(voiceExecuteReason({ ...snapshot, transcript: { ...transcript, session_id: 'previous' } }, 10000)).toContain('会话已变化')
  })
  it('allows STOP for an owned active task even when motion readiness is false', () => {
    const running: VoiceState = { ...state, ready: false, reason: '运动中', task: { id: 'task-a', status: 'running' } }
    expect(voiceExecuteReason({ ...snapshot, state: running }, 10000)).toContain('尚未结束')
    expect(voiceExecuteReason({ ...snapshot, state: running, preview: { ...parse, intent: 'STOP' } }, 10000)).toBeNull()
  })
})

describe('explicit voice operations and original command receipts', () => {
  it('does nothing on construction and preview only parses text when ROS is not ready', async () => {
    const fetcher = vi.fn(async (url: RequestInfo | URL) => response(String(url).endsWith('/state') ? { ...state, ready: false } : parse))
    const controller = new VoiceController({ fetcher, now: () => 10000 })
    expect(fetcher).not.toHaveBeenCalled()
    controller.setText('前进40厘米')
    await controller.preview()
    expect(fetcher).not.toHaveBeenCalled()
    await controller.connect()
    await controller.preview()
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual(['/voice-api/state', '/voice-api/preview'])
    expect(controller.getSnapshot().preview).toEqual(parse)
    expect(controller.getSnapshot().receipt).toBeNull()
  })
  it('ignores a late preview after the text changes', async () => {
    const pending = deferred<Response>()
    const fetcher = vi.fn(async (url: RequestInfo | URL) => String(url).endsWith('/state') ? response(state) : pending.promise)
    const controller = new VoiceController({ fetcher, now: () => 10000 })
    await controller.connect()
    controller.setText('前进40厘米')
    const operation = controller.preview()
    controller.setText('向左转90度')
    pending.resolve(response(parse)); await operation
    expect(controller.getSnapshot().text).toBe('向左转90度')
    expect(controller.getSnapshot().preview).toBeNull()
  })
  it('transcribes raw audio with no execute call, preserves ASR source and invalidates it on edit', async () => {
    const fetcher = vi.fn<typeof fetch>(async (url: RequestInfo | URL) => response(String(url).endsWith('/state') ? { ...state, ready: false } : transcript))
    const controller = new VoiceController({ fetcher, now: () => 10000 })
    await controller.connect()
    const audio = new Blob(['recorded'], { type: 'audio/ogg' })
    await controller.transcribe(audio)
    const [, init] = fetcher.mock.calls.at(-1)! as [RequestInfo | URL, RequestInit]
    expect(fetcher.mock.calls.at(-1)![0]).toBe('/voice-api/transcribe')
    expect(init.body).toBe(audio)
    expect(init.headers).toEqual({ 'Content-Type': 'audio/ogg' })
    expect(controller.getSnapshot().transcript).toEqual(transcript)
    expect(controller.getSnapshot().preview).toEqual(parse)
    expect(controller.getSnapshot().receipt).toBeNull()
    controller.setText('前进30厘米')
    expect(controller.getSnapshot().preview).toBeNull()
    expect(controller.getSnapshot().transcript).toBeNull()
  })
  it('rejects invalid audio and another session before any execution', async () => {
    const fetcher = vi.fn(async (url: RequestInfo | URL) => response(String(url).endsWith('/state') ? state : { ...transcript, session_id: 'wrong' }))
    const controller = new VoiceController({ fetcher, now: () => 10000 })
    await controller.connect()
    await controller.transcribe(new Blob(['sound'], { type: 'text/plain' }))
    expect(fetcher).toHaveBeenCalledTimes(1)
    await controller.transcribe(new Blob(['sound'], { type: 'audio/wav' }))
    expect(controller.getSnapshot().actionError).toContain('会话已变化')
    expect(controller.getSnapshot().preview).toBeNull()
  })
  it('posts one envelope and never retries or creates a new UUID after a lost receipt', async () => {
    let current = state
    const fetcher = vi.fn<typeof fetch>(async (url: RequestInfo | URL) => {
      if (String(url).endsWith('/execute')) throw new Error('connection lost')
      return response(String(url).endsWith('/state') ? current : parse)
    })
    const commandId = vi.fn(() => 'command-a')
    const controller = new VoiceController({ fetcher, now: () => 10000, commandId })
    await controller.connect(); controller.setText('前进40厘米'); await controller.preview(); await controller.execute()
    expect(controller.getSnapshot().receipt?.unknown).toBe(true)
    const execute = fetcher.mock.calls.find(([url]) => String(url).endsWith('/execute'))! as [RequestInfo | URL, RequestInit]
    expect(JSON.parse(execute[1].body as string)).toEqual({ command_id: 'command-a', session_id: 'session-a', sequence: 1, issued_at_ms: 10000, ttl_ms: 5000, text: '前进40厘米' })
    controller.setText('前进30厘米'); await controller.preview(); await controller.execute()
    expect(commandId).toHaveBeenCalledTimes(1)
    current = { ...state, latest_command: { command_id: 'unrelated', status: 'succeeded' } }
    await controller.connect()
    expect(controller.getSnapshot().receipt?.unknown).toBe(true)
    current = { ...state, latest_command: { command_id: 'command-a', status: 'running', task_id: 'actual-task' }, task: { id: 'actual-task', status: 'running' } }
    await controller.connect()
    expect(controller.getSnapshot().receipt?.unknown).toBe(false)
    expect(controller.getSnapshot().receipt?.command?.task_id).toBe('actual-task')
    expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith('/execute'))).toHaveLength(1)
  })
  it('keeps task_unknown and changed-session receipts locked instead of interpreting them as delivery failure', async () => {
    let current = state
    const fetcher = vi.fn(async (url: RequestInfo | URL) => response(String(url).endsWith('/state') ? current : String(url).endsWith('/preview') ? parse : { command_id: 'command-a', status: 'task_unknown' }))
    const controller = new VoiceController({ fetcher, now: () => 10000, commandId: () => 'command-a' })
    await controller.connect(); controller.setText('前进40厘米'); await controller.preview(); await controller.execute()
    expect(controller.getSnapshot().receipt?.unknown).toBe(true)
    current = { ...state, session_id: 'restarted', latest_command: { command_id: 'command-a', status: 'succeeded' } }
    await controller.connect()
    expect(controller.getSnapshot().receipt?.unknown).toBe(true)
    expect(controller.getSnapshot().preview).toBeNull()
  })
  it('includes ASR identity, consumes preview once, and continues the server sequence after reconnection', async () => {
    let current: VoiceState = { ...state, latest_command: { command_id: 'older', sequence: 7, status: 'succeeded' } }
    const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url).endsWith('/state')) return response(current)
      if (String(url).endsWith('/transcribe')) return response(transcript)
      if (String(url).endsWith('/preview')) return response(parse)
      const envelope = JSON.parse(init!.body as string)
      return response({ command_id: envelope.command_id, status: 'running', task_id: 'task-a' })
    })
    const controller = new VoiceController({ fetcher, now: () => 10000, commandId: () => 'new-a' })
    await controller.connect(); await controller.transcribe(new Blob(['sound'], { type: 'audio/webm' })); await controller.execute()
    const request = fetcher.mock.calls.find(([url]) => String(url).endsWith('/execute'))!
    expect(JSON.parse(request[1]!.body as string)).toMatchObject({ sequence: 8, asr_id: 'asr-a' })
    expect(controller.getSnapshot().preview).toBeNull()
    controller.setText('前进40厘米'); await controller.preview()
    expect(voiceExecuteReason(controller.getSnapshot(), 10000)).toContain('尚未结束')
    current = { ...state, task: { id: 'task-a', status: 'succeeded' } }; await controller.connect()
    expect(voiceExecuteReason(controller.getSnapshot(), 10000)).toBeNull()
  })
  it('never executes expired ASR and reports an explicit rejected receipt without claiming success', async () => {
    let now = 10000
    const fetcher = vi.fn(async (url: RequestInfo | URL) => response(String(url).endsWith('/state') ? state : String(url).endsWith('/transcribe') ? transcript
      : String(url).endsWith('/preview') ? parse : { command_id: 'a', status: 'rejected', reason: '障碍物挡住路线' }, String(url).endsWith('/execute') ? 409 : 200))
    const controller = new VoiceController({ fetcher, now: () => now, commandId: () => 'a' })
    await controller.connect(); await controller.transcribe(new Blob(['sound'], { type: 'audio/wav' }))
    now = 15000; await controller.execute()
    expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith('/execute'))).toHaveLength(0)
    controller.setText('前进40厘米'); await controller.preview(); await controller.execute()
    expect(controller.getSnapshot().receipt?.command?.status).toBe('rejected')
    expect(controller.getSnapshot().receipt?.unknown).toBe(false)
    expect(controller.getSnapshot().actionError).toBe('障碍物挡住路线')
  })
  it('distinguishes an explicit HTTP admission rejection from an unknown delivery', async () => {
    const fetcher = vi.fn(async (url: RequestInfo | URL) => String(url).endsWith('/execute')
      ? response({ outcome: 'rejected', error: 'session_mismatch' }, 409)
      : response(String(url).endsWith('/state') ? state : parse))
    const controller = new VoiceController({ fetcher, now: () => 10000, commandId: () => 'rejected-command' })
    await controller.connect(); controller.setText('前进40厘米'); await controller.preview(); await controller.execute()
    expect(controller.getSnapshot().receipt?.unknown).toBe(false)
    expect(controller.getSnapshot().receipt?.command).toEqual({ command_id: 'rejected-command', status: 'rejected', reason: 'session_mismatch' })
    expect(controller.getSnapshot().preview).toBeNull()
    expect(controller.getSnapshot().actionError).toBe('session_mismatch')
  })
  it('accepts an admission rejection without echoed identity only when accepted is explicitly false', async () => {
    const fetcher = vi.fn(async (url: RequestInfo | URL) => String(url).endsWith('/execute')
      ? response({ accepted: false, status: 'rejected', reason: 'command_expired_or_future' }, 408)
      : response(String(url).endsWith('/state') ? state : parse))
    const controller = new VoiceController({ fetcher, now: () => 10000, commandId: () => 'original' })
    await controller.connect(); controller.setText('前进40厘米'); await controller.preview(); await controller.execute()
    expect(controller.getSnapshot().receipt).toMatchObject({ unknown: false, command: { command_id: 'original', accepted: false, status: 'rejected' } })
  })
  it('retains accepted null as receipt evidence while exact state reconciliation recovers the actual terminal result', async () => {
    let current = state
    const fetcher = vi.fn(async (url: RequestInfo | URL) => response(String(url).endsWith('/state') ? current : String(url).endsWith('/preview') ? parse
      : { command_id: 'original', accepted: null, status: 'task_unknown', task_id: 'task-a' }))
    const controller = new VoiceController({ fetcher, now: () => 10000, commandId: () => 'original' })
    await controller.connect(); controller.setText('前进40厘米'); await controller.preview(); await controller.execute()
    expect(controller.getSnapshot().receipt?.unknown).toBe(true)
    current = { ...state, latest_command: { command_id: 'original', accepted: null, status: 'succeeded', task_id: 'task-a' }, task: { id: 'task-a', status: 'succeeded' } }
    await controller.connect()
    expect(controller.getSnapshot().receipt).toMatchObject({ unknown: false, command: { accepted: null, status: 'succeeded' } })
  })
  it('allows one explicit STOP after GET confirms the owned unknown original task, without replaying motion', async () => {
    const originalTask = { id: 'motion-a', task_id: 'motion-a', owner: 'voice:session-a', status: 'task_unknown' }
    let current: VoiceState = state
    const posted: Array<{ command_id: string; sequence: number; text: string }> = []
    const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url).endsWith('/state')) return response(current)
      const body = JSON.parse(init!.body as string)
      if (String(url).endsWith('/preview')) return response(body.text === '停止' ? { ...parse, intent: 'STOP', parameters: {} } : parse)
      posted.push(body)
      return response({ command_id: body.command_id, session_id: 'session-a', accepted: body.text === '停止' ? true : null,
        status: body.text === '停止' ? 'canceling' : 'task_unknown', task_id: 'motion-a', task: { ...originalTask, status: body.text === '停止' ? 'canceling' : 'task_unknown' } })
    })
    const commandId = vi.fn().mockReturnValueOnce('motion-a').mockReturnValueOnce('stop-a')
    const controller = new VoiceController({ fetcher, now: () => 10000, commandId })
    await controller.connect(); controller.setText('前进40厘米'); await controller.preview(); await controller.execute()
    controller.setText('停止'); await controller.preview(); await controller.execute()
    expect(posted).toHaveLength(1) // The POST task record alone does not grant the exception.
    current = { ...state, ready: false, reason: 'owned_task_task_unknown', task: originalTask,
      latest_command: { command_id: 'motion-a', session_id: 'session-a', accepted: null, status: 'task_unknown', task_id: 'motion-a', sequence: 1 } }
    await controller.connect()
    controller.setText('前进40厘米'); await controller.preview(); await controller.execute()
    expect(posted).toHaveLength(1)
    controller.setText('停止'); await controller.preview()
    expect(voiceExecuteReason(controller.getSnapshot(), 10000)).toBeNull()
    await controller.execute()
    expect(posted.map(({ command_id, sequence, text }) => ({ command_id, sequence, text }))).toEqual([
      { command_id: 'motion-a', sequence: 1, text: '前进40厘米' },
      { command_id: 'stop-a', sequence: 2, text: '停止' },
    ])
    expect(controller.getSnapshot().receipt).toMatchObject({ unknown: false, command: { task_id: 'motion-a', status: 'canceling' } })
  })
  it.each(['session', 'task', 'owner', 'no-owner', 'no-task', 'latest-command', 'latest-task', 'task-alias'] as const)(
    'blocks STOP while an unknown receipt cannot verify %s against the state readback', async (mismatch) => {
      const originalTask = { id: 'motion-a', task_id: 'motion-a', owner: 'voice:session-a', status: 'task_unknown' }
      let current: VoiceState = state
      const posted: string[] = []
      const commandId = vi.fn(() => 'motion-a')
      const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
        if (String(url).endsWith('/state')) return response(current)
        const body = JSON.parse(init!.body as string)
        if (String(url).endsWith('/preview')) return response(body.text === '停止' ? { ...parse, intent: 'STOP', parameters: {} } : parse)
        posted.push(body.text)
        return response({ command_id: 'motion-a', accepted: null, status: 'task_unknown', task_id: 'motion-a', task: originalTask })
      })
      const controller = new VoiceController({ fetcher, now: () => 10000, commandId })
      await controller.connect(); controller.setText('前进40厘米'); await controller.preview(); await controller.execute()
      current = { ...state, ready: false, task: { ...originalTask },
        latest_command: { command_id: 'motion-a', session_id: 'session-a', accepted: null, status: 'task_unknown', task_id: 'motion-a' } }
      if (mismatch === 'session') current.session_id = 'another-session'
      if (mismatch === 'task') current.task = { ...originalTask, id: 'unrelated-task', task_id: 'unrelated-task' }
      if (mismatch === 'owner') current.task = { ...originalTask, owner: 'voice:another-session' }
      if (mismatch === 'no-owner') current.task = { id: 'motion-a', status: 'task_unknown' }
      if (mismatch === 'no-task') current.task = null
      if (mismatch === 'latest-command') current.latest_command!.command_id = 'another-command'
      if (mismatch === 'latest-task') current.latest_command!.task_id = 'another-task'
      if (mismatch === 'task-alias') current.task = { ...originalTask, task_id: 'another-task' }
      await controller.connect(); controller.setText('停止'); await controller.preview(); await controller.execute()
      expect(posted).toEqual(['前进40厘米'])
      expect(commandId).toHaveBeenCalledTimes(1)
      expect(controller.getSnapshot().receipt?.unknown).toBe(true)
      expect(controller.getSnapshot().actionError).toContain('回执未知')
    })
  it('does not authorize another STOP from an unknown cancellation receipt even after readback', async () => {
    const originalTask = { id: 'motion-a', task_id: 'motion-a', owner: 'voice:session-a', status: 'task_unknown' }
    let current: VoiceState = state
    const posted: string[] = []
    const commandId = vi.fn().mockReturnValueOnce('motion-a').mockReturnValueOnce('stop-a')
    const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url).endsWith('/state')) return response(current)
      const body = JSON.parse(init!.body as string)
      if (String(url).endsWith('/preview')) return response(body.text === '停止' ? { ...parse, intent: 'STOP', parameters: {} } : parse)
      posted.push(body.text)
      return response({ command_id: body.command_id, accepted: null, status: 'task_unknown', task_id: 'motion-a', task: originalTask })
    })
    const controller = new VoiceController({ fetcher, now: () => 10000, commandId })
    await controller.connect(); controller.setText('前进40厘米'); await controller.preview(); await controller.execute()
    current = { ...state, ready: false, task: originalTask, latest_command: { command_id: 'motion-a', accepted: null, status: 'task_unknown', task_id: 'motion-a' } }
    await controller.connect(); controller.setText('停止'); await controller.preview(); await controller.execute()
    current = { ...current, latest_command: { command_id: 'stop-a', accepted: null, status: 'task_unknown', task_id: 'motion-a' } }
    await controller.connect(); controller.setText('停止'); await controller.preview(); await controller.execute()
    expect(posted).toEqual(['前进40厘米', '停止'])
    expect(commandId).toHaveBeenCalledTimes(2)
    expect(controller.getSnapshot().receipt?.unknown).toBe(true)
  })
  it('recovers the original unknown STOP as canceled native 5 on explicit connect without rewriting its receipt or replaying', async () => {
    const native = '17c93304fd0c4816b7137304519a2aa2'
    const running = { id: 'motion-a', task_id: 'motion-a', owner: 'voice:session-a',
      status: 'running', native_goal_id: native, native_status: 2 }
    let current: VoiceState = state
    const posted: Array<{ command_id: string; session_id: string; sequence: number; issued_at_ms: number; text: string }> = []
    const fetcher = vi.fn<typeof fetch>(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url).endsWith('/state')) return response(current)
      const body = JSON.parse(init!.body as string)
      if (String(url).endsWith('/preview')) return response(body.text === '停止' ? { ...parse, intent: 'STOP', parameters: {} } : parse)
      posted.push(body)
      return response({ command_id: body.command_id, session_id: 'session-a', task_id: 'motion-a', task: running,
        accepted: body.text === '停止' ? null : true, status: body.text === '停止' ? 'task_unknown' : 'running' })
    })
    const commandId = vi.fn().mockReturnValueOnce('motion-a').mockReturnValueOnce('stop-a')
    const controller = new VoiceController({ fetcher, now: () => 10000, commandId })
    await controller.connect(); controller.setText('前进40厘米'); await controller.preview(); await controller.execute()
    current = { ...state, ready: false, task: running,
      latest_command: { command_id: 'motion-a', session_id: 'session-a', accepted: true, status: 'running', task_id: 'motion-a' } }
    await controller.connect(); controller.setText('停止'); await controller.preview(); await controller.execute()
    const original = controller.getSnapshot().receipt!
    expect(original).toMatchObject({ unknown: true, command: { command_id: 'stop-a', accepted: null, status: 'task_unknown' } })
    const canceled = { ...running, status: 'canceled', native_status: 5 }
    current = { ...state, task: canceled, latest_command: { command_id: 'stop-a', session_id: 'session-a',
      accepted: null, status: 'canceled', task_id: 'motion-a', task: canceled,
      ...{ receipt_status: 'task_unknown' } } }
    const beforeRefresh = fetcher.mock.calls.length
    await controller.connect()
    expect(fetcher.mock.calls.slice(beforeRefresh).map(([url]) => url)).toEqual(['/voice-api/state'])
    expect(controller.getSnapshot().receipt).toMatchObject({ unknown: false, envelope: original.envelope,
      command: { command_id: 'stop-a', session_id: 'session-a', task_id: 'motion-a', accepted: null,
        receipt_status: 'task_unknown', status: 'canceled', task: { ...canceled } } })
    expect(original.command?.status).toBe('task_unknown')
    controller.setText('停止'); await controller.preview(); await controller.execute()
    expect(commandId).toHaveBeenCalledTimes(2)
    expect(posted.map(({ command_id, session_id, sequence, issued_at_ms, text }) =>
      ({ command_id, session_id, sequence, issued_at_ms, text }))).toEqual([
      { command_id: 'motion-a', session_id: 'session-a', sequence: 1, issued_at_ms: 10000, text: '前进40厘米' },
      { command_id: 'stop-a', session_id: 'session-a', sequence: 2, issued_at_ms: 10000, text: '停止' },
    ])
  })
  it('starts from last_sequence on first connect and on a fresh page controller', async () => {
    const posted: Array<{ command_id: string; sequence: number }> = []
    const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url).endsWith('/state')) return response({ ...state, last_sequence: 42 })
      if (String(url).endsWith('/preview')) return response(parse)
      const envelope = JSON.parse(init!.body as string)
      posted.push(envelope)
      return response({ command_id: envelope.command_id, status: 'succeeded', accepted: true })
    })
    for (const command_id of ['first-page', 'refreshed-page']) {
      const controller = new VoiceController({ fetcher, now: () => 10000, commandId: () => command_id })
      await controller.connect(); controller.setText('前进40厘米'); await controller.preview(); await controller.execute()
    }
    expect(posted.map(({ command_id, sequence }) => ({ command_id, sequence }))).toEqual([
      { command_id: 'first-page', sequence: 43 }, { command_id: 'refreshed-page', sequence: 43 },
    ])
  })
  it('never decreases its sequence after stale state and only reports a concurrent replay rejection', async () => {
    let lastSequence = 42
    let reject = false
    let nextId = 0
    const posted: number[] = []
    const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url).endsWith('/state')) return response({ ...state, last_sequence: lastSequence })
      if (String(url).endsWith('/preview')) return response(parse)
      const envelope = JSON.parse(init!.body as string)
      posted.push(envelope.sequence)
      return response({ command_id: envelope.command_id, status: reject ? 'rejected' : 'succeeded', accepted: !reject,
        ...(reject ? { reason: 'sequence_replayed' } : {}) })
    })
    const controller = new VoiceController({ fetcher, now: () => 10000, commandId: () => `command-${++nextId}` })
    await controller.connect(); controller.setText('前进40厘米'); await controller.preview(); await controller.execute()
    lastSequence = 12
    await controller.connect(); controller.setText('前进40厘米'); await controller.preview(); await controller.execute()
    expect(posted).toEqual([43, 44])
    reject = true
    controller.setText('前进40厘米'); await controller.preview(); await controller.execute()
    expect(posted).toEqual([43, 44, 45])
    expect(controller.getSnapshot().receipt?.unknown).toBe(false)
    expect(controller.getSnapshot().receipt?.command?.status).toBe('rejected')
    expect(controller.getSnapshot().actionError).toBe('sequence_replayed')
    await Promise.resolve()
    expect(posted).toHaveLength(3)
    expect(nextId).toBe(3)
  })
})
