import { describe, expect, it, vi } from 'vitest'
import { resolveAppRoute } from './app-route'
import { isWorkbenchLocalHost, selectVisualCases, workbenchSnapshot } from './workbench-catalog'
import { checkWorkbenchService, EMPTY_WORKBENCH_SERVICES } from './workbench-services'

describe('workbench evidence and independent workspace boundaries', () => {
  it('adds the workbench while preserving all existing operation paths', () => {
    expect(resolveAppRoute('/workbench')).toBe('workbench')
    expect(['/','/radar','/simulation','/cooperation'].map(resolveAppRoute)).toEqual(['dashboard','radar','simulation','cooperation'])
  })

  it('retains every declared case and separates cancellations from completed tasks', () => {
    const cases = workbenchSnapshot.visual.cases
    expect(cases).toHaveLength(56)
    expect(new Set(cases.map((item) => item.id)).size).toBe(56)
    expect(selectVisualCases('completed')).toHaveLength(38)
    expect(selectVisualCases('safe-cancel')).toHaveLength(7)
    expect(selectVisualCases('failed')).toHaveLength(11)
    expect(workbenchSnapshot.visual.qualified).toBe(false)
    expect(selectVisualCases('failed').every((item) => item.reason.length > 0)).toBe(true)
    expect(selectVisualCases('failed').filter((item) => item.id.startsWith('full-'))).toHaveLength(2)
    expect(workbenchSnapshot.workflow.cases.filter((item) => item.outcome === 'completed')).toHaveLength(2)
    expect(workbenchSnapshot.workflow.cases.filter((item) => item.outcome === 'safe-cancel')).toHaveLength(1)
    expect(workbenchSnapshot.workflow.cases.every((item) => item.passed)).toBe(true)
  })

  it('publishes a bounded summary without private filesystem links or fabricated online state', () => {
    const text = JSON.stringify(workbenchSnapshot)
    expect(text).not.toMatch(/file:\/\/|\/home\/muqiao|\.env|Bearer /)
    expect(workbenchSnapshot.provenance.every((item) => /^[a-f0-9]{64}$/.test(item.sha256))).toBe(true)
    expect(EMPTY_WORKBENCH_SERVICES.spatiallm.status).toBe('unchecked')
    expect(EMPTY_WORKBENCH_SERVICES.video.status).toBe('unchecked')
    expect(isWorkbenchLocalHost('127.0.0.1')).toBe(true)
    expect(isWorkbenchLocalHost('localhost')).toBe(true)
    expect(isWorkbenchLocalHost('192.168.0.101')).toBe(false)
    expect(workbenchSnapshot.capabilities.find((item) => item.id === 'arena')?.boundary).toContain('success均为false')
  })
})

describe('explicit read-only workbench service checks', () => {
  it('checks only the fixed GET endpoint and verifies tool identity', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({ status: 'ready', mode: 'offline', model_inference: 'not_run', render_requested: false })))
    const result = await checkWorkbenchService('spatiallm', { fetcher, now: () => 123 })
    expect(result).toEqual({ status: 'available', message: '本机工具入口可访问；不代表新任务已经运行', checkedAt: 123 })
    expect(fetcher.mock.calls[0][0]).toBe('/workbench-service/spatiallm')
    expect(fetcher.mock.calls[0][1]).toMatchObject({ method: 'GET', cache: 'no-store' })
  })

  it('accepts a closed failed video run as an available review tool, without calling it a successful analysis', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({ version: 'offline-person-events-v1', run_id: 'a'.repeat(32), state: 'failed', event_count: 0 })))
    const result = await checkWorkbenchService('video', { fetcher })
    expect(result.status).toBe('available')
    expect(result.message).toContain('不代表新任务已经运行')
    expect(fetcher.mock.calls[0][0]).toBe('/workbench-service/video')
  })

  it('keeps unexpected responses unknown and preserves integrity rejection reasons', async () => {
    expect((await checkWorkbenchService('video', { fetcher: vi.fn<typeof fetch>().mockResolvedValue(new Response('{}')) })).status).toBe('unexpected')
    const result = await checkWorkbenchService('video', { fetcher: vi.fn<typeof fetch>().mockResolvedValue(new Response('{}', { status: 409 })) })
    expect(result.status).toBe('unavailable')
    expect(result.message).toContain('原件或复核记录')
  })

  it('identifies an HTML page at a service endpoint instead of claiming a connection outage', async () => {
    const result = await checkWorkbenchService('video', { fetcher: vi.fn<typeof fetch>().mockResolvedValue(new Response('<html>other app</html>')) })
    expect(result.status).toBe('unexpected')
    expect(result.message).toContain('内容无法识别')
  })

  it('reports a connection failure without changing frozen experimental results', async () => {
    const before = JSON.stringify(workbenchSnapshot)
    const result = await checkWorkbenchService('spatiallm', { fetcher: vi.fn<typeof fetch>().mockRejectedValue(new TypeError('connection refused')) })
    expect(result.status).toBe('unavailable')
    expect(JSON.stringify(workbenchSnapshot)).toBe(before)
  })

  it('aborts a slow check within its own wall-clock budget', async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation((_url, options) => new Promise((_resolve, reject) => {
      options?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true })
    }))
    const result = await checkWorkbenchService('video', { fetcher, timeoutMs: 5 })
    expect(result.status).toBe('unavailable')
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
})
