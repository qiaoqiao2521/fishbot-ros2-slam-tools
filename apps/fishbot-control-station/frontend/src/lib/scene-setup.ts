/** Give selection/loading feedback a paint before synchronous WebGL setup. */
export function scheduleSceneSetup(start: () => void, clock = {
  frame: (callback: FrameRequestCallback) => requestAnimationFrame(callback),
  cancelFrame: (id: number) => cancelAnimationFrame(id),
  delay: (callback: () => void) => setTimeout(callback, 0),
  cancelDelay: (id: ReturnType<typeof setTimeout>) => clearTimeout(id),
}): () => void {
  let cancelled = false, frame: number | null = null, timer: ReturnType<typeof setTimeout> | null = null
  frame = clock.frame(() => {
    frame = null
    timer = clock.delay(() => { timer = null; if (!cancelled) start() })
  })
  return () => { cancelled = true; if (frame !== null) clock.cancelFrame(frame); if (timer !== null) clock.cancelDelay(timer) }
}
