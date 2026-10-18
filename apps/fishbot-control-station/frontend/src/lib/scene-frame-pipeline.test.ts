import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockPerception } from '@/lib/mock-station'
import { SceneFramePipeline, type SceneWorkerPort, type SceneWorkerRequest } from './scene-frame-pipeline'
import { sceneScanPoints } from './scene-contract'

class FakePort implements SceneWorkerPort {
  onmessage: SceneWorkerPort['onmessage'] = null
  onerror: SceneWorkerPort['onerror'] = null
  postMessage = vi.fn<(value: SceneWorkerRequest) => void>()
  terminate = vi.fn()
}
const port = () => new FakePort()
const scanInput = () => ({ kind: 'scan' as const, scan: { ...structuredClone(mockPerception).scan, ready: true, frameId: 'laser_link' } })
afterEach(() => vi.useRealTimers())
describe('3D render worker lifecycle', () => {
  it('reports an idle map scope without leaving the previous worker diagnostics in the DOM', () => {
    const create = vi.fn(), observe = vi.fn(), pipeline = new SceneFramePipeline(create, vi.fn(), vi.fn(), observe)
    pipeline.setScope(null)
    expect(create).not.toHaveBeenCalled(); expect(observe).toHaveBeenCalledWith(expect.objectContaining({ active: false, pending: false, disposed: false, running: false }))
    pipeline.dispose(); pipeline.dispose(); expect(observe).toHaveBeenCalledTimes(2)
  })
  it('keeps only one latest pending frame and retains original input clocks', () => {
    const worker = port(), display = vi.fn(), errors = vi.fn()
    const pipeline = new SceneFramePipeline(() => worker, display, errors)
    pipeline.setScope('station-a:domain127:scene1')
    const a = scanInput(), b = scanInput(), c = scanInput()
    a.scan.lastUpdate = 'A'; b.scan.lastUpdate = 'B'; c.scan.lastUpdate = 'C'
    pipeline.offer(a); pipeline.offer(b); pipeline.offer(c)
    expect(worker.postMessage).toHaveBeenCalledTimes(1); expect(pipeline.snapshot()).toMatchObject({ active: true, pending: true, overwritten: 1 })
    const first = worker.postMessage.mock.calls[0][0]
    worker.onmessage?.({ data: { ...first, points: sceneScanPoints(a.scan) } } as never)
    expect(worker.postMessage.mock.calls[1][0].input).toEqual(c)
    const last = worker.postMessage.mock.calls[1][0]
    worker.onmessage?.({ data: { ...last, points: sceneScanPoints(c.scan) } } as never)
    expect(display.mock.calls[1][0].receivedAt).toBe('C'); expect(errors).not.toHaveBeenCalled(); pipeline.dispose()
  })
  it('drops old-source and disposed-worker replies without affecting an owner', () => {
    const old = port(), next = port(), display = vi.fn(), create = vi.fn().mockReturnValueOnce(old).mockReturnValueOnce(next)
    const pipeline = new SceneFramePipeline(create, display, vi.fn())
    pipeline.setScope('scene-old'); pipeline.offer(scanInput())
    const first = old.postMessage.mock.calls[0][0]
    pipeline.setScope('scene-new'); pipeline.offer(scanInput())
    expect(old.terminate).toHaveBeenCalledOnce()
    old.onmessage?.({ data: { ...first, points: sceneScanPoints(scanInput().scan) } } as never)
    expect(display).not.toHaveBeenCalled()
    const current = next.postMessage.mock.calls[0][0]
    pipeline.dispose(); next.onmessage?.({ data: { ...current, points: sceneScanPoints(scanInput().scan) } } as never)
    expect(display).not.toHaveBeenCalled(); expect(next.terminate).toHaveBeenCalledOnce()
  })
  it('releases a hung worker and pending memory with an explicit error', () => {
    vi.useFakeTimers(); const worker = port(), error = vi.fn()
    const pipeline = new SceneFramePipeline(() => worker, vi.fn(), error)
    pipeline.setScope('sensor'); pipeline.offer(scanInput()); pipeline.offer(scanInput())
    vi.advanceTimersByTime(5001)
    expect(worker.terminate).toHaveBeenCalledOnce(); expect(error).toHaveBeenCalledWith(expect.stringContaining('5 秒'))
    expect(pipeline.snapshot()).toMatchObject({ active: false, pending: false }); pipeline.dispose()
  })
  it('reports parser and worker errors without retrying work or any external command', () => {
    const worker = port(), error = vi.fn(), display = vi.fn()
    const pipeline = new SceneFramePipeline(() => worker, display, error)
    pipeline.setScope('sensor'); pipeline.offer(scanInput())
    const sent = worker.postMessage.mock.calls[0][0]
    worker.onmessage?.({ data: { ...sent, error: 'PCD 字段无效' } } as never)
    expect(error).toHaveBeenCalledWith('PCD 字段无效'); expect(display).not.toHaveBeenCalled()
    worker.onerror?.({} as ErrorEvent); expect(worker.terminate).toHaveBeenCalledOnce()
    expect(worker.postMessage).toHaveBeenCalledTimes(1); pipeline.dispose()
  })
})
