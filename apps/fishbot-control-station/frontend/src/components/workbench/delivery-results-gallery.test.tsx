import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import catalog from '../../../public/workbench/delivery-results.json'
import ideal from '../../../public/workbench/j100-ideal-wide-result.json'
import old from '../../../public/workbench/j100-ideal-k-result.json'
import replay from '../../../public/workbench/j100-ideal-k-replay.json'
import two from '../../../public/workbench/mecanum-2d-result.json'
import three from '../../../public/workbench/mecanum-3d-result.json'
import twoTiming from '../../../public/workbench/mecanum-planar-queued-delivery-timing.json'
import threeTiming from '../../../public/workbench/mecanum-lidar3d-delivery-timing.json'
import { DeliveryResultsGallery } from './delivery-results-gallery'
import { VisionDeliveryResult } from './vision-delivery-result'
import { parseVisionResult } from '@/lib/vision-delivery'

describe('four delivery result groups', () => {
  it('offers four actual configurations and no execution action', () => {
    const html = renderToStaticMarkup(<DeliveryResultsGallery />)
    expect(catalog.groups).toHaveLength(4)
    expect(html.match(/data-result-group=/g)).toHaveLength(4)
    expect(html).toContain('筛选成果车型'); expect(html).toContain('筛选成果雷达')
    expect(html).not.toContain('/coop-api/start')
  })
  it('keeps wide-scene unknown UUIDs and timeline unknown rather than borrowing the old run', () => {
    const result = parseVisionResult(ideal)
    expect(result.orders.map(o => o.taskId)).toEqual(['', ''])
    expect(result.timingUrl).toBeNull(); expect(result.replayUrl).toBeNull()
    expect(result.runId).not.toBe(old.run_id)
    const html = renderToStaticMarkup(<VisionDeliveryResult initialResult={ideal} />)
    expect(html).toContain('48.78 s'); expect(html).toContain('该回合阶段时间原件缺失')
    expect(html).not.toContain('选择配送记录'); expect(html).not.toContain('所选模型候选')
  })
  it('binds the two mecanum sensor reports independently and never claims zero resets', () => {
    for (const [result, timing] of [[two, twoTiming], [three, threeTiming]] as const) {
      expect(result.run_id).toBe(timing.source_run_id)
      expect(result.orders.map(o => o.task_id)).toEqual(timing.cases.map(c => c.task_id))
      expect(result.orders.map(o => o.passed)).toEqual([true, true])
      const html = renderToStaticMarkup(<VisionDeliveryResult initialResult={result} />)
      expect(html).toContain('1 次世界重置'); expect(html).toContain('两单配送，分轮验收')
      expect(html).not.toContain('两件货物，同一世界'); expect(html).not.toContain('所选模型候选')
    }
  })
  it('binds old J100 replay to original tasks with real samples and no generated arm geometry', () => {
    expect(replay.runs.map(r => r.task_id)).toEqual(old.orders.map(o => o.task_id))
    expect(replay.runs.map(r => r.frames.length)).toEqual([2685, 1740])
    expect(replay.runs.every(r => r.frames.every(f => f.arm_joints_world === null))).toBe(true)
    expect(replay.scene.static_boxes).toEqual([])
    expect(replay.rescored).toBe(false)
  })
})
