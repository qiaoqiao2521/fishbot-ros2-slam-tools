import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import catalog from '../../../public/workbench/delivery-results.json'
import result from '../../../public/workbench/f2-warehouse-local-175145-result.json'
import chain from '../../../public/workbench/f2-warehouse-local-175145/visual/visual-chain.json'
import timing from '../../../public/workbench/f2-warehouse-local-175145/timing.json'
import components from '../../../public/workbench/f2-warehouse-local-175145/original-components.json'
import sensor from '../../../public/workbench/f2-warehouse-local-175145/sensor/sensor-experience.json'
import native from '../../../public/workbench/f2-warehouse-local-175145/native-lidar-consumer.json'
import { parseVisualEvidence } from '@/lib/visual-evidence'
import { VisualEvidencePanel } from './visual-evidence-panel'

describe('actual local warehouse B success and A return failure', () => {
  it('keeps original two-order verdicts separate and retains historical records', () => {
    expect(catalog.groups).toHaveLength(4)
    expect(catalog.experiments.some(e => e.id === 'f2-warehouse-v6')).toBe(true)
    expect(catalog.experiments.some(e => e.id === 'f2-warehouse-local-175145')).toBe(true)
    expect(result.orders.map(o => o.passed)).toEqual([true, false])
    expect(components.original_whole_task_passed).toBe(false)
    expect(timing.source_run_id).toBe(result.run_id)
    expect(result.orders[0].route_seconds).toBeCloseTo(71.131359353, 6)
    expect(result.orders[1].failure_reason).toContain('非预期物理接触')
  })
  it('keeps the complete B loading/unloading chain within the same task and actual episode', () => {
    expect(chain.entries).toHaveLength(2)
    expect(chain.entries.map(e => e.phase)).toEqual(['load', 'unload'])
    expect(chain.entries.every(e => e.task_id === result.orders[0].task_id)).toBe(true)
    expect(chain.entries.every(e => e.observation.episode_id === result.provenance.episode_ids[0])).toBe(true)
    expect(chain.entries.map(e => e.observation.point_count)).toEqual([312, 235])
    for (const e of chain.entries) {
      expect(e.milestones.lift?.original_passed).toBe(true)
      expect(e.milestones.placement?.original_passed).toBe(true)
      expect(e.milestones.lift?.image).toBeTruthy(); expect(e.milestones.placement?.image).toBeTruthy()
    }
  })
  it('identifies selected51/49 as OBB proposals and does not borrow B model queries for failed A', () => {
    expect(chain.entries.map(e => e.selected?.index)).toEqual([51, 49])
    expect(chain.entries.every(e => e.selected?.origin === 'obb')).toBe(true)
    const parsed = parseVisualEvidence(chain)
    expect(parsed.queries.every(q => q.taskId === result.orders[0].task_id)).toBe(true)
    const a = renderToStaticMarkup(<VisualEvidencePanel sourceUrl={result.assets.visual_chain} initialReport={chain} expectedRunId={result.run_id} taskId={result.orders[1].task_id} />)
    expect(a).toContain('当前订单没有匹配的查询，未借用其他订单取证')
    for (const query of parsed.queries) expect(a).not.toContain(`查询 ${query.id}`)
    const b = renderToStaticMarkup(<VisualEvidencePanel sourceUrl={result.assets.visual_chain} initialReport={chain} expectedRunId={result.run_id} taskId={result.orders[0].task_id} />)
    expect(b).toContain('OBB几何候选（原来源 obb）')
    expect(b).toContain('不能写成神经网络生成的最终抓取')
    expect(b).toContain('原候选分数')
  })
  it('keeps actual MID startup coverage and consumer evidence bounded rather than claiming delivery-time ACK', () => {
    expect(sensor.frames).toHaveLength(6)
    expect(sensor.tf).toEqual({ requested: 6, matched_source: 0, failed: 6 })
    expect(sensor.frames.every(f => f.identity.episode_id === result.provenance.episode_ids[0])).toBe(true)
    expect(native.pointcloud.width).toBe(4000); expect(native.pointcloud.messages).toBe(54)
    expect(native.pointcloud.source_stamp_sec).toBe(6); expect(native.pointcloud.source_stamp_nanosec).toBe(700000000)
    expect(native.tf.successful_lookups).toBe(2)
    expect(result.warnings.join(' ')).toContain('启动阶段6帧')
    expect(result.warnings.join(' ')).toContain('静态collision_map')
    expect(result.provenance.native_consumer_binding.native_receipt_itself_has_episode_id).toBe(false)
  })
})
