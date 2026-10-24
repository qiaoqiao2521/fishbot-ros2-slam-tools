import { describe, expect, it, vi } from 'vitest'
import snapshot from '../../public/workbench/delivery-timing.json'
import { parseDeliveryTiming, readDeliveryTiming, readLocalDeliveryTiming, timingWindow } from './delivery-timing'

describe('delivery timing evidence boundaries', () => {
  it('shows real K route budgets without counting egress or adding the parent twice', () => {
    const report = parseDeliveryTiming(snapshot)
    const b = report.cases[0], a = report.cases[1]
    expect(report.cases).toHaveLength(2)
    expect(b.route.elapsed_s).toBeCloseTo(119.793848021, 8)
    expect(b.route.remaining_s).toBeCloseTo(.206151979, 8)
    expect(a.route.elapsed_s).toBeCloseTo(34.883377231, 8)
    expect(report.new_execution).toBe(false); expect(report.rescored).toBe(false)
    const route = timingWindow(b, 'route')
    expect(route.spans.every(s => s.parent_id === 'route')).toBe(true)
    expect(route.spans.some(s => s.label.includes('离站'))).toBe(false)
    expect(route.spans.reduce((sum, s) => sum + (s.duration_s ?? 0), 0)).toBeCloseTo(b.route.elapsed_s!, 3)
    expect(timingWindow(b, 'task').spans.some(s => s.label.includes('离站'))).toBe(true)
    expect(b.sampling.missing_samples).toBe(1); expect(a.sampling.missing_samples).toBe(50)
    expect(b.sampling.gaps).toHaveLength(1); expect(a.sampling.gaps).toHaveLength(3)
  })

  it('retains failures and unknowns while skipping a malformed case', () => {
    const report = parseDeliveryTiming({ schema: 'editable', cases: [null, {
      id: 'failed', original_verdict: { original_score_passed: false, task_verdict: 'failed' },
      route: { elapsed_s: 'not a number', remaining_s: -2 }, physical: {},
    }] })
    expect(report.cases).toHaveLength(1)
    expect(report.cases[0].original_passed).toBe(false)
    expect(report.cases[0].route.elapsed_s).toBeNull()
    expect(report.cases[0].route.remaining_s).toBe(-2)
    expect(report.cases[0].guard_seconds).toBeNull()
    expect(report.warnings.length).toBeGreaterThan(0)
    expect(timingWindow(report.cases[0], 'route').origin).toBeNull()
  })

  it('uses only a read request and reports an absent snapshot honestly', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => snapshot })
    await readDeliveryTiming(undefined, fetcher)
    expect(fetcher).toHaveBeenCalledExactlyOnceWith('/workbench/delivery-timing.json', { method: 'GET', cache: 'no-store', signal: undefined })
    await expect(readDeliveryTiming(undefined, vi.fn().mockResolvedValue({ ok: false, status: 404 }))).rejects.toThrow('HTTP 404')
    await readDeliveryTiming(undefined, fetcher, 'mecanum')
    expect(fetcher).toHaveBeenLastCalledWith('/workbench/mecanum-delivery-timing.json', { method: 'GET', cache: 'no-store', signal: undefined })
  })

  it('accepts locally edited summaries and refuses raw logs without parsing them', async () => {
    const data = JSON.stringify({ ...snapshot, label: '人工补注' })
    const report = await readLocalDeliveryTiming({ size: data.length, text: async () => data })
    expect(report.label).toBe('人工补注'); expect(report.source.label).toBe('人工补注')
    const text = vi.fn()
    await expect(readLocalDeliveryTiming({ size: 5 * 1024 * 1024, text })).rejects.toThrow('摘要 JSON')
    expect(text).not.toHaveBeenCalled()
    await expect(readLocalDeliveryTiming({ size: 10, text: async () => '{bad' })).rejects.toThrow(SyntaxError)
  })
})
