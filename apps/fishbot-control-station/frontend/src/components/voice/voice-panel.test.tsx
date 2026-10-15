import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import { VoicePanel, VoicePanelView } from '@/components/voice/voice-panel'
import { EMPTY_VOICE_SNAPSHOT, VoiceController, type VoiceSnapshot, type VoiceState } from '@/lib/voice'

const hooks = vi.hoisted(() => ({ active: false, cursor: 0, values: [] as unknown[], effects: [] as Array<() => (() => void) | undefined> }))
vi.mock('react', async (original) => {
  const actual = await original<typeof import('react')>()
  return { ...actual,
    useRef: (initial: unknown) => {
      if (!hooks.active) return actual.useRef(initial)
      const index = hooks.cursor++
      if (!(index in hooks.values)) hooks.values[index] = { current: initial }
      return hooks.values[index]
    },
    useEffect: (effect: () => (() => void) | undefined, dependencies: unknown[]) => {
      if (hooks.active) hooks.effects.push(effect)
      else actual.useEffect(effect, dependencies)
    },
    useState: (initial: unknown) => {
      if (!hooks.active) return actual.useState(initial)
      const index = hooks.cursor++
      if (!(index in hooks.values)) hooks.values[index] = typeof initial === 'function' ? initial() : initial
      return [hooks.values[index], (value: unknown) => {
        hooks.values[index] = typeof value === 'function' ? value(hooks.values[index]) : value
      }]
    },
  }
})

const state: VoiceState = { mode: 'simulation', domain: 121, session_id: 'actual-session', ready: true, reason: '仿真已就绪',
  asr: { available: false, reason: '未安装本地转写依赖' }, capabilities: { FORWARD: true, STOP: true, DOCK: false, dock_reason: '回充适配器未配置' },
  latest_command: null, task: null }
function render(patch: Partial<VoiceSnapshot> = {}, now = 10000) {
  return renderToStaticMarkup(<VoicePanelView snapshot={{ ...EMPTY_VOICE_SNAPSHOT, state, receivedAt: 10000, ...patch }} now={now}
    onConnect={() => {}} onTextChange={() => {}} onPreview={() => {}} onExecute={() => {}} onRecord={() => {}} onUpload={() => {}} />)
}
describe('voice panel evidence and explicit controls', () => {
  it('renders without fetching, recording, uploading or executing on mount', () => {
    const fetcher = vi.fn()
    vi.stubGlobal('fetch', fetcher)
    try {
      const html = renderToStaticMarkup(<VoicePanel />)
      expect(html).toContain('连接语音服务')
      expect(html).toContain('目标域 121')
      expect(html).toContain('浏览器不会自动录音或派发任务')
      expect(html).toContain('等待任务预览')
      expect(html).not.toContain('确认执行此任务')
      expect(fetcher).not.toHaveBeenCalled()
    } finally { vi.unstubAllGlobals() }
  })
  it('offers text examples and clear audio limits when local ASR is unavailable', () => {
    const html = render()
    for (const text of ['前进40厘米', '向左转90度', '返航', '装货运输', '停止', '15 秒', '4 MiB', '未安装本地转写依赖', '回充适配器未配置']) expect(html).toContain(text)
    expect(html).toContain('停止后只转写')
    expect(html).toContain('只在手动刷新时更新')
  })
  it('shows parsed parameters but no execute button for a rejected preview', () => {
    const html = render({ preview: { accepted: false, intent: 'FORWARD', parameters: { distance_m: 30 }, reason: '移动距离超过限制' } })
    expect(html).toContain('移动距离超过限制')
    expect(html).toContain('距离（米）')
    expect(html).not.toContain('确认执行此任务')
  })
  it('requires a new recording after the source age limit and disables its execution', () => {
    const parse = { accepted: true, intent: 'FORWARD', parameters: { distance_m: .4 }, reason: '已解析' }
    const html = render({ text: '前进40厘米', preview: parse,
      transcript: { text: '前进40厘米', asr_id: 'asr-a', session_id: 'actual-session', parse, received_at_ms: 10000, expires_at_ms: 15000 } }, 15000)
    expect(html).toContain('这段音频已超过 5 秒')
    const button = html.match(/<button[^>]*>(?:(?!<\/button>).)*确认执行此任务<\/button>/s)?.[0]
    expect(button).toContain('disabled=""')
  })
  it('renders unknown receipts with the original command and separates native and physical evidence', () => {
    const html = render({ receipt: { envelope: { command_id: 'original-uuid', session_id: 'actual-session', sequence: 1, issued_at_ms: 10000, ttl_ms: 5000, text: '前进40厘米' }, unknown: true, command: null },
      state: { ...state, task: { id: 'native-task', status: 'running', message: '等待导航反馈' } } })
    expect(html).toContain('执行回执未知')
    expect(html).toContain('original-uuid')
    expect(html).toContain('不会自动重发')
    expect(html).toContain('native-task')
    expect(html).toContain('原生终态')
    expect(html).toContain('尚未收到')
    expect(html).toContain('尚未提供独立评分')
    expect(html).not.toContain('任务报告成功')
  })
  it('keeps STOP on the task adapter and explains accepted is only submission', () => {
    const html = render({ preview: { accepted: true, intent: 'STOP', parameters: {}, reason: '取消当前语音任务' },
      state: { ...state, ready: false, task: { id: 'owned-task', status: 'running' } } })
    expect(html).toContain('确认停止当前语音任务')
    expect(html).toContain('经任务适配器取消当前语音拥有的任务')
    expect(html).toContain('已接受表示任务已提交')
  })
})

describe('browser recording resource lifecycle', () => {
  async function setup(capturePending = false) {
    vi.useFakeTimers()
    const trackStop = vi.fn()
    const capture = { getTracks: () => [{ stop: trackStop }] } as unknown as MediaStream
    let releaseCapture!: (stream: MediaStream) => void
    const getUserMedia = vi.fn(() => capturePending ? new Promise<MediaStream>((resolve) => { releaseCapture = resolve }) : Promise.resolve(capture))
    class Recorder {
      static isTypeSupported = () => true
      state: RecordingState = 'inactive'
      mimeType: string
      ondataavailable: ((event: { data: Blob }) => void) | null = null
      onstop: (() => void) | null = null
      onerror: (() => void) | null = null
      constructor(_stream: MediaStream, options: MediaRecorderOptions) { this.mimeType = options.mimeType! }
      start() { this.state = 'recording' }
      stop() {
        this.state = 'inactive'
        this.ondataavailable?.({ data: new Blob(['recording'], { type: this.mimeType }) })
        this.onstop?.()
      }
    }
    const browserWindow = new EventTarget()
    const browserDocument = Object.assign(new EventTarget(), { hidden: false })
    vi.stubGlobal('MediaRecorder', Recorder)
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })
    vi.stubGlobal('window', browserWindow)
    vi.stubGlobal('document', browserDocument)
    const controller = new VoiceController({ fetcher: vi.fn(async () => new Response(JSON.stringify({ ...state, asr: { available: true, reason: 'ready' } }))), now: () => 10000 })
    await controller.connect()
    const transcribe = vi.spyOn(controller, 'transcribe').mockResolvedValue(undefined)
    const execute = vi.spyOn(controller, 'execute')
    hooks.active = true; hooks.cursor = 0; hooks.values = []; hooks.effects = []
    let page = VoicePanel({ controller })
    const cleanups = hooks.effects.map((effect) => effect())
    const rerender = () => { hooks.cursor = 0; page = VoicePanel({ controller }); return page }
    const start = async () => { page.props.onRecord(); await Promise.resolve(); await Promise.resolve(); rerender() }
    const cleanup = () => {
      cleanups.forEach((effect) => effect?.())
      const remainingTimers = vi.getTimerCount()
      hooks.active = false; vi.unstubAllGlobals(); vi.useRealTimers()
      expect(remainingTimers).toBe(0)
    }
    return { start, rerender, cleanup, trackStop, transcribe, execute, browserWindow, releaseCapture: () => releaseCapture(capture) }
  }

  it('stops microphone tracks and only transcribes on explicit stop, without executing', async () => {
    const fixture = await setup()
    try {
      await fixture.start()
      expect(fixture.trackStop).not.toHaveBeenCalled()
      fixture.rerender().props.onRecord()
      expect(fixture.trackStop).toHaveBeenCalled()
      expect(fixture.transcribe).toHaveBeenCalledTimes(1)
      expect(fixture.transcribe.mock.calls[0][0].type).toContain('audio/webm')
      expect(fixture.execute).not.toHaveBeenCalled()
    } finally { fixture.cleanup() }
  })

  it('discards a blurred capture and clears recording timers and microphone tracks on unmount', async () => {
    const fixture = await setup()
    try {
      await fixture.start()
      fixture.browserWindow.dispatchEvent(new Event('blur'))
      expect(fixture.trackStop).toHaveBeenCalled()
      expect(fixture.transcribe).not.toHaveBeenCalled()
      expect(renderToStaticMarkup(fixture.rerender())).toContain('录音已因页面失焦而停止')
      expect(fixture.execute).not.toHaveBeenCalled()
    } finally { fixture.cleanup() }
    expect(vi.isFakeTimers()).toBe(false)
  })

  it('closes permission-delayed capture if the panel unmounts before permission arrives', async () => {
    const fixture = await setup(true)
    try {
      await fixture.start()
      fixture.cleanup()
      fixture.releaseCapture()
      await Promise.resolve(); await Promise.resolve()
      expect(fixture.trackStop).toHaveBeenCalled()
      expect(fixture.transcribe).not.toHaveBeenCalled()
      expect(fixture.execute).not.toHaveBeenCalled()
    } finally { hooks.active = false; vi.unstubAllGlobals(); vi.useRealTimers() }
  })

  it('automatically stops after 15 seconds and never dispatches the transcription', async () => {
    const fixture = await setup()
    try {
      await fixture.start()
      await vi.advanceTimersByTimeAsync(15000)
      expect(fixture.trackStop).toHaveBeenCalled()
      expect(fixture.transcribe).toHaveBeenCalledTimes(1)
      expect(fixture.execute).not.toHaveBeenCalled()
    } finally { fixture.cleanup() }
  })
})
