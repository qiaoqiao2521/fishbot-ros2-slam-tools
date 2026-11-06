import { describe, expect, it } from 'vitest'
import summary from '../../public/workbench/j100-vision-result.json'
import timing from '../../public/workbench/j100-vision-timing.json'
import { parseVisionResult } from './vision-delivery'
import v5 from '../../public/workbench/j100-vision-v5-result.json'
import v5Timing from '../../public/workbench/j100-vision-v5-timing.json'
import v5Replay from '../../public/workbench/j100-vision-v5-replay.json'
import { parseDeliveryComparison } from './delivery-comparison'
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
  it('joins the actual v5 task while keeping native docking separate from whole delivery failure', () => {
    const result = parseVisionResult(v5), report = parseDeliveryTiming(v5Timing), replay = parseDeliveryComparison(v5Replay)
    const order = result.orders[0], recording = replay.runs.find(run => run.taskId === order.taskId), timing = report.cases.find(item => item.task_id === order.taskId)
    expect(recording).toBeDefined(); expect(timing).toBeDefined()
    expect(order.passed).toBe(false); expect(recording?.passed).toBe(false); expect(timing?.original_passed).toBe(false)
    expect(order.positionError).toBeNull(); expect(order.routeSeconds).toBeNull()
    expect(order.componentSummary).toContain('保护介入0.82'); expect(result.model).toContain('推理未证实')
    expect(recording?.nativeActions.map(action => action.status)).toEqual([4, 4])
    expect(recording?.frames.length).toBeGreaterThan(0); expect(order.candidates).toEqual([])
  })
  it('accepts official Drive folder archives without opening other hosts, paths or protocols', () => {
    const folder = 'https://drive.google.com/drive/folders/1VFpP8qsDs_4dIVigPUWHp3RMd3ikaV_L'
    expect(parseVisionResult({ ...summary, archive_url: folder }).archiveUrl).toBe(folder)
    expect(parseVisionResult({ ...summary, archive_url: folder, archive_verified: false }).archiveVerified).toBe(false)
    for (const url of ['http://drive.google.com/drive/folders/ui-only', 'https://drive.google.com.example/drive/folders/ui-only', 'https://drive.google.com/open?id=ui-only', 'https://ui-only:ui-only@drive.google.com/drive/folders/ui-only']) {
      expect(parseVisionResult({ ...summary, archive_url: url }).archiveUrl).toBeNull()
    }
    expect(parseVisionResult(summary).archiveUrl).toBe(summary.archive_url)
  })
  it('degrades one bad optional asset and row without hiding an explicitly failed order', () => {
    const result = parseVisionResult({ schema: 'editable', assets: { replay: '/coop-api/start', video: '/workbench/../private.mp4' },
      orders: [null, { id: 'failure', passed: false, route_seconds: 'unknown', failure_reason: '进场Goal未通过' }] })
    expect(result.orders).toHaveLength(1)
    expect(result.orders[0].passed).toBe(false); expect(result.orders[0].failureReason).toBe('进场Goal未通过'); expect(result.orders[0].routeSeconds).toBeNull()
    expect(result.replayUrl).toBeNull(); expect(result.videoUrl).toBeNull()
    expect(result.warnings.length).toBeGreaterThan(0)
  })
})
