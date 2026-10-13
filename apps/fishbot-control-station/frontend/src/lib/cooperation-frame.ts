import { COOPERATION_STALE_MS, type CooperationFrameObservation } from './cooperation'

type Target = { scene: string; stamp: number; episodeId?: string }
type Decoded = Target & { url: string; requestedAt: number }
type Options = {
  display: (url: string | null) => void
  observe: (frame: CooperationFrameObservation | null) => void
  fetcher?: typeof fetch
  decode?: (url: string) => Promise<void>
  createUrl?: (blob: Blob) => string
  revokeUrl?: (url: string) => void
  now?: () => number
}

/** Keep the displayed JPEG until its successor has decoded. Queue only the latest target. */
export class CooperationFrameBuffer {
  private target: Target | null = null
  private displayed: Decoded | null = null
  private active: AbortController | null = null
  private cancelActive: (() => void) | null = null
  private activeTimer: ReturnType<typeof setTimeout> | null = null
  private generation = 0
  private disposed = false
  private urls = new Set<string>()
  private fetcher: typeof fetch
  private decode: (url: string) => Promise<void>
  private createUrl: (blob: Blob) => string
  private revokeUrl: (url: string) => void
  private now: () => number
  private options: Options

  constructor(options: Options) {
    this.options = options
    this.fetcher = options.fetcher ?? ((input, init) => fetch(input, init))
    this.decode = options.decode ?? (async (url) => { const image = new Image(); image.src = url; await image.decode() })
    this.createUrl = options.createUrl ?? ((blob) => URL.createObjectURL(blob))
    this.revokeUrl = options.revokeUrl ?? ((url) => URL.revokeObjectURL(url))
    this.now = options.now ?? Date.now
  }

  request(scene: string | null, stamp: number | null, episodeId?: string): void {
    if (this.disposed) return
    if (scene !== this.target?.scene || episodeId !== this.target?.episodeId || (stamp !== null && this.target && stamp < this.target.stamp)) this.reset()
    if (!scene || stamp === null) return
    const changed = this.target?.stamp !== stamp
    this.target = { scene, stamp, episodeId }
    if (changed && !this.active) void this.load()
  }

  private release(url: string): void { if (this.urls.delete(url)) this.revokeUrl(url) }
  private reset(): void {
    ++this.generation
    this.cancelActive?.(); this.cancelActive = null
    if (this.activeTimer !== null) clearTimeout(this.activeTimer)
    this.activeTimer = null
    this.active?.abort(); this.active = null
    this.target = null; this.displayed = null
    for (const url of this.urls) this.release(url)
    this.options.display(null); this.options.observe(null)
  }
  dispose(): void { this.disposed = true; this.reset() }

  private async load(): Promise<void> {
    const target = this.target
    if (!target || this.disposed) return
    const generation = this.generation, controller = new AbortController(), requestedAt = this.now()
    this.active = controller
    let timedOut = false
    const interrupted = new Promise<never>((_, reject) => {
      this.cancelActive = () => reject(new Error('Camera request canceled'))
      this.activeTimer = setTimeout(() => {
        timedOut = true; controller.abort(); reject(new Error('Camera request expired'))
      }, COOPERATION_STALE_MS)
    })
    const timer = this.activeTimer
    if (!this.displayed) this.options.observe({ scene: target.scene, stamp: target.stamp, changedAt: requestedAt, loadedStamp: null, error: false })
    let url: string | null = null
    try {
      const response = await Promise.race([this.fetcher(`/coop-api/frame.jpg?stamp=${encodeURIComponent(target.stamp)}${target.episodeId ? `&episode_id=${encodeURIComponent(target.episodeId)}` : ''}`, { cache: 'no-store', signal: controller.signal }), interrupted])
      if (!response.ok) throw new Error(`Camera HTTP ${response.status}`)
      const blob = await Promise.race([response.blob(), interrupted])
      if (controller.signal.aborted || generation !== this.generation) return
      url = this.createUrl(blob); this.urls.add(url)
      await Promise.race([this.decode(url), interrupted])
      if (controller.signal.aborted || generation !== this.generation) return
      const previous = this.displayed
      this.displayed = { ...target, url, requestedAt }
      this.options.display(url)
      this.options.observe({ scene: target.scene, stamp: target.stamp, changedAt: requestedAt, loadedStamp: target.stamp, error: false })
      if (previous) this.release(previous.url)
      url = null
    } catch {
      if ((!controller.signal.aborted || timedOut) && generation === this.generation) this.options.observe({
        scene: target.scene, stamp: target.stamp, changedAt: this.displayed?.requestedAt ?? requestedAt,
        loadedStamp: this.displayed?.stamp ?? null, error: true,
      })
    } finally {
      if (timer !== null) clearTimeout(timer)
      if (url) this.release(url)
      if (this.active === controller) {
        this.active = null
        this.cancelActive = null; this.activeTimer = null
        if (this.target && this.target.stamp !== target.stamp) void this.load()
      }
    }
  }
}
