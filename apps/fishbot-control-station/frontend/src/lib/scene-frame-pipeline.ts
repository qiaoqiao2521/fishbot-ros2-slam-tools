import type { LaserScanSnapshot } from '@/types/station'
import type { ScenePoints } from './scene-contract'

export type SceneWorkerInput = { kind: 'scan'; scan: LaserScanSnapshot } | { kind: 'pcd'; bytes: ArrayBuffer }
export type SceneWorkerRequest = { generation: number; requestId: number; input: SceneWorkerInput }
export type SceneWorkerReply = { generation: number; requestId: number; points?: ScenePoints; error?: string }
export type SceneWorkerPort = {
  postMessage: (value: SceneWorkerRequest) => void
  terminate: () => void
  onmessage: ((event: MessageEvent<SceneWorkerReply>) => void) | null
  onerror: ((event: ErrorEvent) => void) | null
}
export type ScenePipelineMetrics = { active: boolean; pending: boolean; overwritten: number; generation: number; disposed: boolean; delivered: number; running: boolean }

/** One in flight plus one latest pending input. This owns rendering work only. */
export class SceneFramePipeline {
  private create: () => SceneWorkerPort
  private display: (value: ScenePoints) => void
  private failed: (reason: string) => void
  private port: SceneWorkerPort | null = null
  private scope: string | null = null
  private generation = 0
  private sequence = 0
  private active: number | null = null
  private pending: SceneWorkerInput | null = null
  private disposed = false
  private overwritten = 0
  private timeout: ReturnType<typeof setTimeout> | null = null
  private observe: (value: ScenePipelineMetrics) => void
  private delivered = 0

  constructor(create: () => SceneWorkerPort, display: (value: ScenePoints) => void, failed: (reason: string) => void,
    observe: (value: ScenePipelineMetrics) => void = () => {}) {
    this.create = create; this.display = display; this.failed = failed; this.observe = observe
  }
  setScope(scope: string | null): void {
    if (this.disposed) return
    if (scope === this.scope) { this.report(); return }
    this.scope = scope; ++this.generation; this.active = null; this.pending = null
    if (this.timeout !== null) clearTimeout(this.timeout)
    this.timeout = null
    this.port?.terminate(); this.port = null
    if (scope !== null) {
      try {
        const port = this.create(); this.port = port
        port.onmessage = (event) => this.receive(port, event.data)
        port.onerror = () => { if (this.port === port) this.failPort('三维数据 Worker 已停止；可重建视图重试。') }
      } catch { this.failed('浏览器无法启动三维数据 Worker；可重建视图重试。') }
    }
    this.report()
  }
  offer(input: SceneWorkerInput): void {
    if (this.disposed || !this.port || !this.scope) return
    if (this.active !== null) { if (this.pending) ++this.overwritten; this.pending = input; this.report(); return }
    this.send(input)
  }
  private send(input: SceneWorkerInput): void {
    const requestId = ++this.sequence
    this.active = requestId
    this.timeout = setTimeout(() => this.failPort('三维解析超过 5 秒；Worker 已释放，可重建视图重试。'), 5000)
    try { this.port?.postMessage({ generation: this.generation, requestId, input }) }
    catch { this.failPort('三维数据无法传入 Worker；可重建视图重试。') }
    this.report()
  }
  private failPort(reason: string): void {
    if (this.timeout !== null) clearTimeout(this.timeout)
    this.timeout = null; this.active = null; this.pending = null
    this.port?.terminate(); this.port = null; this.failed(reason); this.report()
  }
  private receive(port: SceneWorkerPort, reply: SceneWorkerReply): void {
    if (this.disposed || port !== this.port || reply.generation !== this.generation || reply.requestId !== this.active) return
    if (this.timeout !== null) clearTimeout(this.timeout)
    this.timeout = null
    this.active = null
    if (reply.error) this.failed(reply.error)
    else if (reply.points) { ++this.delivered; this.display(reply.points) }
    else this.failed('三维 Worker 返回了不完整结果。')
    const pending = this.pending; this.pending = null
    if (pending) this.send(pending)
    this.report()
  }
  snapshot(): ScenePipelineMetrics { return { active: this.active !== null, pending: this.pending !== null, overwritten: this.overwritten, generation: this.generation, disposed: this.disposed, delivered: this.delivered, running: this.port !== null } }
  private report() { this.observe(this.snapshot()) }
  dispose(): void { if (this.disposed) return; this.disposed = true; ++this.generation; this.pending = null; this.active = null; if (this.timeout !== null) clearTimeout(this.timeout); this.timeout = null; this.port?.terminate(); this.port = null; this.report() }
}
