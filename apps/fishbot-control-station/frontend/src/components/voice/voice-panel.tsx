import { useEffect, useRef, useState } from 'react'
import { Check, FileAudio, Mic, RefreshCw, Square } from 'lucide-react'

import {
  EMPTY_VOICE_SNAPSHOT, VOICE_AUDIO_MAX_MS, VOICE_DOMAIN, VoiceController,
  voiceCapability, voiceExecuteReason, voiceIntentLabel, voiceReasonLabel, voiceStatusLabel, voiceTranscriptExpired,
  type VoiceSnapshot,
} from '@/lib/voice'
import './voice.css'

const examples = ['前进40厘米', '向左转90度', '返航', '装货运输', '停止']

export function VoicePanel({ expectedDomain = VOICE_DOMAIN, controller: suppliedController }: {
  expectedDomain?: number; controller?: VoiceController
}) {
  const [controller] = useState(() => suppliedController ?? new VoiceController({ expectedDomain }))
  const [snapshot, setSnapshot] = useState<VoiceSnapshot>(() => controller.getSnapshot())
  const [now, setNow] = useState(Date.now)
  const [recording, setRecording] = useState(false)
  const [recordingMs, setRecordingMs] = useState(0)
  const [microphoneError, setMicrophoneError] = useState<string | null>(null)
  const [recordingSupported, setRecordingSupported] = useState(false)
  const [requestingMicrophone, setRequestingMicrophone] = useState(false)
  const recorder = useRef<MediaRecorder | null>(null)
  const stream = useRef<MediaStream | null>(null)
  const recordingTimer = useRef<ReturnType<typeof setInterval> | null>(null)
  const recordingGeneration = useRef(0)
  const requesting = useRef(false)
  const mounted = useRef(false)
  const fileInput = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    mounted.current = true
    const unsubscribe = controller.subscribe(() => setSnapshot(controller.getSnapshot()))
    setRecordingSupported(typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia)
    // This timer only expires local evidence. It never polls or sends a command.
    const clock = setInterval(() => setNow(Date.now()), 250)
    const stopCapture = () => {
      recordingGeneration.current++
      requesting.current = false
      if (recordingTimer.current) clearInterval(recordingTimer.current)
      recordingTimer.current = null
      if (recorder.current && recorder.current.state !== 'inactive') recorder.current.stop()
      stream.current?.getTracks().forEach((track) => track.stop())
      stream.current = null
      recorder.current = null
      if (mounted.current) {
        setRecording(false)
        setRequestingMicrophone(false)
      }
    }
    const interrupt = () => {
      if (recorder.current || requesting.current) {
        stopCapture()
        setMicrophoneError('录音已因页面失焦而停止，音频已丢弃。请重新录音。')
      }
    }
    window.addEventListener('blur', interrupt)
    const visibility = () => { if (document.hidden) interrupt() }
    document.addEventListener('visibilitychange', visibility)
    return () => {
      mounted.current = false
      stopCapture()
      clearInterval(clock)
      unsubscribe()
      window.removeEventListener('blur', interrupt)
      document.removeEventListener('visibilitychange', visibility)
    }
  }, [controller])

  const stopRecording = () => {
    if (recordingTimer.current) clearInterval(recordingTimer.current)
    recordingTimer.current = null
    if (recorder.current && recorder.current.state !== 'inactive') recorder.current.stop()
    stream.current?.getTracks().forEach((track) => track.stop())
    stream.current = null
  }

  const startRecording = async () => {
    if (requesting.current || recorder.current || snapshot.pending || !snapshot.state?.asr.available || snapshot.connectionError) return
    if (typeof MediaRecorder === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      setMicrophoneError('当前浏览器不支持录音，请上传音频或输入文字。')
      return
    }
    const generation = ++recordingGeneration.current
    requesting.current = true
    setRequestingMicrophone(true)
    setMicrophoneError(null)
    // Starting another recording makes every previous preview unusable immediately.
    controller.setText(snapshot.text)
    let capture: MediaStream | null = null
    try {
      capture = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (!mounted.current || generation !== recordingGeneration.current) { capture.getTracks().forEach((track) => track.stop()); return }
      const supported = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/ogg', 'audio/wav']
        .find((type) => MediaRecorder.isTypeSupported(type))
      if (!supported) throw new Error('当前浏览器没有支持的 WebM、Ogg 或 WAV 录音格式，请上传音频或输入文字。')
      stream.current = capture
      const current = new MediaRecorder(capture, { mimeType: supported })
      recorder.current = current
      const chunks: Blob[] = []
      let failed = false
      current.ondataavailable = (event) => { if (event.data.size && generation === recordingGeneration.current) chunks.push(event.data) }
      current.onerror = () => {
        if (!mounted.current || generation !== recordingGeneration.current) return
        failed = true
        setMicrophoneError('录音发生错误，请上传音频或输入文字。')
        stopRecording()
      }
      current.onstop = () => {
        capture?.getTracks().forEach((track) => track.stop())
        if (!mounted.current || generation !== recordingGeneration.current) { chunks.length = 0; return }
        if (recordingTimer.current) clearInterval(recordingTimer.current)
        recordingTimer.current = null
        if (recorder.current === current) recorder.current = null
        setRecording(false)
        if (failed) { chunks.length = 0; return }
        const audio = new Blob(chunks, { type: current.mimeType })
        chunks.length = 0
        // No object URL, file export, storage, or command is created from this audio.
        void controller.transcribe(audio)
      }
      current.start()
      const started = Date.now()
      setRecordingMs(0)
      setRecording(true)
      recordingTimer.current = setInterval(() => {
        const elapsed = Date.now() - started
        setRecordingMs(Math.min(elapsed, VOICE_AUDIO_MAX_MS))
        if (elapsed >= VOICE_AUDIO_MAX_MS) stopRecording()
      }, 100)
    } catch (error) {
      capture?.getTracks().forEach((track) => track.stop())
      recorder.current = null
      stream.current = null
      if (mounted.current && generation === recordingGeneration.current) {
        const denied = error instanceof DOMException && ['NotAllowedError', 'SecurityError'].includes(error.name)
        setMicrophoneError(denied ? '未获得麦克风权限。请允许权限后重试，或上传音频、输入文字。'
          : error instanceof Error ? error.message : '无法使用麦克风，请上传音频或输入文字。')
      }
    } finally {
      if (generation === recordingGeneration.current) {
        requesting.current = false
        if (mounted.current) setRequestingMicrophone(false)
      }
    }
  }

  return <VoicePanelView snapshot={snapshot} now={now} expectedDomain={controller.expectedDomain}
    recording={recording} recordingMs={recordingMs} recordingSupported={recordingSupported}
    microphoneError={microphoneError} requestingMicrophone={requestingMicrophone}
    onConnect={() => { void controller.connect() }} onTextChange={(text) => controller.setText(text)}
    onPreview={() => { void controller.preview() }} onExecute={() => { void controller.execute() }}
    onRecord={() => { if (recording) stopRecording(); else void startRecording() }}
    onUpload={() => fileInput.current?.click()}
    fileInput={<input ref={fileInput} className="voice-file-input" type="file" accept="audio/webm,audio/ogg,audio/wav,audio/x-wav,.webm,.ogg,.wav"
      aria-label="选择待转写音频" disabled={!!snapshot.pending || recording || requestingMicrophone || !snapshot.state?.asr.available || !!snapshot.connectionError}
      onChange={(event) => {
        const audio = event.currentTarget.files?.[0]
        event.currentTarget.value = ''
        if (audio) {
          const suffix = audio.name.split('.').at(-1)?.toLowerCase()
          const type = audio.type || ({ webm: 'audio/webm', ogg: 'audio/ogg', wav: 'audio/wav' } as Record<string, string>)[suffix || ''] || ''
          void controller.transcribe(new Blob([audio], { type }))
        }
      }} />}
  />
}

export function VoicePanelView({ snapshot = EMPTY_VOICE_SNAPSHOT, now, expectedDomain = VOICE_DOMAIN,
  recording = false, recordingMs = 0, recordingSupported = false, requestingMicrophone = false,
  microphoneError = null, onConnect, onTextChange, onPreview, onExecute, onRecord, onUpload, fileInput,
}: {
  snapshot?: VoiceSnapshot; now: number; expectedDomain?: number; recording?: boolean; recordingMs?: number
  recordingSupported?: boolean; requestingMicrophone?: boolean; microphoneError?: string | null
  onConnect: () => void; onTextChange: (text: string) => void; onPreview: () => void; onExecute: () => void
  onRecord: () => void; onUpload: () => void; fileInput?: React.ReactNode
}) {
  const { state, preview, transcript, receipt } = snapshot
  const busy = !!snapshot.pending || recording || requestingMicrophone
  const connected = !!state && !snapshot.connectionError
  const asrReady = connected && state.asr.available
  const executeReason = voiceExecuteReason(snapshot, now)
  const expired = voiceTranscriptExpired(transcript, now)
  const task = state?.task
  return <section className="voice-panel" aria-labelledby="voice-panel-title" id="workbench-voice">
    <div className="voice-heading">
      <div><h2 id="voice-panel-title">先听懂，再执行</h2><p>说出任务，先检查意图与参数，再确认交给仿真。</p></div>
      <button type="button" className="voice-button voice-connect" disabled={busy} onClick={onConnect}>
        <RefreshCw size={14} aria-hidden="true" />{snapshot.pending === 'connect' ? '正在连接…' : state ? '刷新任务状态' : '连接语音服务'}
      </button>
    </div>
    <div className="voice-service" role="status" data-connected={connected}>
      <span className="voice-service-dot" aria-hidden="true" />
      <strong>{connected ? `仿真语音服务 · ROS 域 ${state.domain}` : `等待语音服务 · 目标域 ${expectedDomain}`}</strong>
      <span>{snapshot.connectionError || (state ? voiceReasonLabel(state.reason) : '点击连接后读取服务状态。浏览器不会自动录音或派发任务。')}</span>
      {state && <small>会话 {state.session_id}。任务状态只在手动刷新时更新。</small>}
    </div>
    <div className="voice-layout">
      <div className="voice-input-column">
        <label className="voice-field-label" htmlFor="voice-task-text">输入想让小车做的事</label>
        <textarea id="voice-task-text" value={snapshot.text} onChange={(event) => onTextChange(event.target.value)}
          placeholder="例如：前进40厘米" rows={3} maxLength={300} disabled={recording || requestingMicrophone || snapshot.pending === 'execute'} />
        <div className="voice-examples" role="group" aria-label="填写任务示例">{examples.map((example) =>
          <button key={example} type="button" disabled={busy} onClick={() => onTextChange(example)}>{example}</button>)}</div>
        <div className="voice-input-actions">
          <button type="button" className={`voice-button ${recording ? 'voice-stop-recording' : ''}`} onClick={onRecord}
            disabled={requestingMicrophone || (!recording && (!!snapshot.pending || !asrReady || !recordingSupported))}>
            {recording ? <Square size={15} aria-hidden="true" /> : <Mic size={16} aria-hidden="true" />}
            {recording ? `停止录音并转写 ${Math.ceil(recordingMs / 1000)}s` : requestingMicrophone ? '等待麦克风权限…' : '点击录音'}
          </button>
          <button type="button" className="voice-button" disabled={busy || !asrReady} onClick={onUpload}><FileAudio size={16} aria-hidden="true" />上传音频</button>
          {fileInput}
        </div>
        <p className="voice-input-note">WebM / Ogg / WAV，最多 15 秒、4 MiB。停止后只转写，等待你确认执行。</p>
        {!asrReady && <p className="voice-input-note">{state?.asr.reason ? voiceReasonLabel(state.asr.reason) : '连接后检查本地转写能力。文字输入始终可用。'}</p>}
        {!recordingSupported && <p className="voice-input-note">此环境暂不支持浏览器录音，可上传音频或输入文字。</p>}
        {microphoneError && <p className="voice-error" role="alert">{microphoneError}</p>}
        <button type="button" className="voice-button voice-primary voice-preview" disabled={busy || !connected || !snapshot.text.trim()} onClick={onPreview}>
          {snapshot.pending === 'preview' ? '正在解析…' : snapshot.pending === 'transcribe' ? '正在转写…' : '预览任务'}
        </button>
        <p className="voice-input-note">预览只解析文字。停止任务也经任务适配器取消当前语音拥有的任务。</p>
      </div>
      <div className="voice-result-column" aria-live="polite">
        <h3>识别意图与执行回执</h3>
        {preview ? <div className="voice-intent" data-accepted={preview.accepted}>
          <span className="voice-result-label">{transcript ? '本地音频转写' : '文字任务解析'}</span>
          <strong>{voiceIntentLabel(preview.intent)}</strong>
          <p>{voiceReasonLabel(preview.reason)}</p>
          {Object.keys(preview.parameters).length > 0 && <dl className="voice-parameters">{Object.entries(preview.parameters).map(([key, value]) =>
            <div key={key}><dt>{parameterLabel(key)}</dt><dd>{parameterValue(key, value)}</dd></div>)}</dl>}
          {transcript && <p className={`voice-audio-age ${expired ? 'voice-error' : ''}`}>{expired ? '这段音频已超过 5 秒，请重新录音或上传。' : `音频确认剩余 ${Math.max(0, Math.ceil((transcript.expires_at_ms - now) / 1000))} 秒。编辑文字将清除音频来源。`}</p>}
          {preview.accepted && <button type="button" className="voice-button voice-primary" disabled={!!executeReason || recording || requestingMicrophone} onClick={onExecute}>
            <Check size={15} aria-hidden="true" />{preview.intent === 'STOP' ? '确认停止当前语音任务' : '确认执行此任务'}</button>}
          {preview.accepted && executeReason && !expired && <p className="voice-gate-reason">{voiceReasonLabel(executeReason)}</p>}
        </div> : <div className="voice-empty"><span>等待任务预览</span><p>任务意图、移动距离和转向角度会出现在这里。</p></div>}
        {snapshot.actionError && <p className="voice-error" role="alert">{voiceReasonLabel(snapshot.actionError)}</p>}
        {receipt && <div className="voice-receipt" data-receipt-unknown={receipt.unknown}>
          <strong>{receipt.unknown ? '执行回执未知' : voiceStatusLabel(receipt.command?.status || 'unknown')}</strong>
          <p>{receipt.unknown ? '保留原命令编号。点击刷新任务状态核对，不会自动重发。' : receipt.command?.reason ? voiceReasonLabel(receipt.command.reason) : '服务已返回回执，请手动刷新任务进度。'}</p>
          <dl><div><dt>命令编号</dt><dd>{receipt.envelope.command_id}</dd></div>
            {receipt.command?.task_id && <div><dt>任务编号</dt><dd>{receipt.command.task_id}</dd></div>}</dl>
        </div>}
        {task?.id && <div className="voice-task-result"><h4>上游任务反馈</h4>
          <dl><div><dt>任务编号</dt><dd>{task.id}</dd></div><div><dt>任务状态</dt><dd>{voiceStatusLabel(task.status)}</dd></div>
            {task.phase && <div><dt>当前阶段</dt><dd>{task.phase}</dd></div>}
            <div><dt>原生终态</dt><dd>{task.native_status === undefined || task.native_status === null ? '尚未收到' : String(task.native_status)}</dd></div>
            <div><dt>物理结果</dt><dd>{task.physical_result === undefined || task.physical_result === null ? '尚未提供独立评分' : JSON.stringify(task.physical_result)}</dd></div></dl>
          {!!(task.message || task.reason || task.upstream_record?.message || task.upstream_record?.stop_reason) && <p>{String(task.message || task.reason || task.upstream_record?.message || task.upstream_record?.stop_reason)}</p>}
          {task.upstream_record && <details><summary>查看上游原始任务记录</summary><pre>{JSON.stringify(task.upstream_record, null, 2)}</pre></details>}
        </div>}
        <p className="voice-evidence-note">已接受表示任务已提交。任务终态、停稳与独立物理评分分别确认。</p>
      </div>
    </div>
    {state && <details className="voice-capabilities"><summary>当前任务能力与不可用原因</summary><dl>{Object.entries(state.capabilities).filter(([, value]) => typeof value === 'boolean').map(([intent]) => {
      const value = voiceCapability(state, intent)
      return <div key={intent}><dt>{voiceIntentLabel(intent)}</dt><dd data-available={value.available}>{value.available ? '可用' : '不可用'}{value.reason && `：${voiceReasonLabel(value.reason)}`}</dd></div>
    })}</dl></details>}
  </section>
}

function parameterLabel(parameter: string): string {
  return ({ distance_m: '距离（米）', angle_deg: '角度（度）', angle_rad: '转向角度', direction: '方向', speed_mps: '速度（米/秒）' } as Record<string, string>)[parameter] || parameter
}

function parameterValue(parameter: string, value: unknown): string {
  if (parameter === 'angle_rad' && typeof value === 'number') return `${Number((value * 180 / Math.PI).toFixed(2))}°`
  return typeof value === 'string' || typeof value === 'number' ? String(value) : JSON.stringify(value)
}
