import { describe, expect, it } from 'vitest'
import summary from '../../public/workbench/j100-vision-result.json'
import timing from '../../public/workbench/j100-vision-timing.json'
import { parseVisionResult } from './vision-delivery'
import { parseDeliveryTiming } from './delivery-timing'

describe('visual delivery result index', () => {
  it('retains documented metrics without inventing deleted replay material', () => {
    const result = parseVisionResult(summary)
    expect(result.orders.map(order => order.routeSeconds)).toEqual([49.90201967599933, 20.967781600000308])
    expect(result.orders.map(order => order.passed)).toEqual([true, true])
    expect(result.evidenceKind).toBe('documented_acceptance')
    expect(result.archiveUrl).toMatch(/^https:\/\/drive.google.com\/file\/d\//)
    expect(result.replayUrl).toBeNull(); expect(result.videoUrl).toBeNull()
    const report = parseDeliveryTiming(timing)
    expect(report.cases.every(item => item.spans.length === 0 && item.start_wall_s === null)).toBe(true)
    expect(report.cases.every(item => item.import_status === 'partial')).toBe(true)
  })
  it('degrades one bad optional asset and row without hiding an explicitly failed order', () => {
    const result = parseVisionResult({ schema: 'editable', assets: { replay: '/coop-api/start', video: '/workbench/../private.mp4' },
      orders: [null, { id: 'failure', passed: false, route_seconds: 'unknown' }] })
    expect(result.orders).toHaveLength(1)
    expect(result.orders[0].passed).toBe(false); expect(result.orders[0].routeSeconds).toBeNull()
    expect(result.replayUrl).toBeNull(); expect(result.videoUrl).toBeNull()
    expect(result.warnings.length).toBeGreaterThan(0)
  })
})
