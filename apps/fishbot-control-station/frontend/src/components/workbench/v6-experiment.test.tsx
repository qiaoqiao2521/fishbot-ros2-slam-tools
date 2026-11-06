import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import catalog from '../../../public/workbench/delivery-results.json'
import result from '../../../public/workbench/f2-warehouse-v6-result.json'
import chain from '../../../public/workbench/f2-warehouse-v6/visual/visual-chain.json'
import score from '../../../public/workbench/f2-warehouse-v6/original-components.json'
import frames from '../../../public/workbench/f2-warehouse-v6/video-frame-index.json'
import { parseVisualEvidence } from '@/lib/visual-evidence'
import { VisualEvidencePanel } from './visual-evidence-panel'

describe('v6 actual same-task visual loading chain', () => {
  it('keeps source identity and earlier experiments while the original whole task stays failed', () => {
    expect(catalog.groups).toHaveLength(4)
    for (const id of ['f2-warehouse-v4', 'f2-warehouse-v5', 'f2-workshop-v5', 'f2-warehouse-v6']) expect(catalog.experiments.some(e => e.id === id)).toBe(true)
    expect(chain.run_id).toBe(result.run_id); expect(chain.scene_id).toBe('f1-j100-wide-continuous-ba')
    expect(chain.entries[0].task_id).toBe(result.orders[0].task_id)
    expect(chain.entries[0].observation.episode_id).toBe(result.provenance.episode_id)
    expect(result.orders[0].passed).toBe(false); expect(score.original_task_passed).toBe(false)
    expect(score.pickup_and_transport_observed.passed).toBe(true)
  })
  it('shows actual input, selected51 and same-task physical lift/tray placement without pretending unloading happened', () => {
    const parsed = parseVisualEvidence(chain), entry = parsed.entries[0]
    expect(entry.points.xyz).toHaveLength(312); expect(entry.observation.pointCount).toBe(312)
    expect(entry.selected?.index).toBe(51); expect(entry.selected?.origin).toBe('obb')
    expect(entry.inference.requestWall).toBeCloseTo(4.33115855, 7)
    expect(entry.milestones.lift?.originalPassed).toBe(true); expect(entry.milestones.placement?.originalPassed).toBe(true)
    expect(entry.milestones.lift?.image).toBeTruthy(); expect(entry.milestones.placement?.image).toBeTruthy()
    expect(score.unload_samples_after_arrival).toBe(0)
    const html = renderToStaticMarkup(<VisualEvidencePanel sourceUrl={result.assets.visual_chain} initialReport={chain} expectedRunId={result.run_id} taskId={result.orders[0].task_id} />)
    expect(html).toContain('候选 #51'); expect(html).toContain('原分项评分通过')
    expect(html).toContain('本项是装货后放入小车托盘，不是目的地卸货上架')
    expect(html).not.toContain('模型生成候选（未执行）')
  })
  it('uses original same-episode media frames within one source second of each original observed gate', () => {
    expect(frames.frame_count).toBe(826)
    for (const milestone of [chain.entries[0].milestones.lift, chain.entries[0].milestones.placement]) {
      expect(milestone.original_gate_scope).toBe('original_named_attempt_pickup_observed_not_delivery_success')
      expect(milestone.image_max_gate_source_delta_s).toBe(1)
      expect(milestone.image_gate_source_delta_s).toBeGreaterThanOrEqual(0)
      expect(milestone.image_gate_source_delta_s).toBeLessThanOrEqual(1)
      const frame = frames.frames.find(f => f.video_frame === milestone.video_frame)!
      expect(frame.episode_id).toBe(chain.entries[0].observation.episode_id)
      expect(frame.source_s).toBe(milestone.source_s)
    }
  })
  it('separates accepted23.385s query and remaining route time from exhausted360s whole-task budget', () => {
    const stages = parseVisualEvidence(chain).queries[0].stages
    expect(chain.queries[0].outcome).toBe('accepted')
    expect(stages.find(e => e.stage === 'query_cleanup_completed')?.elapsed).toBeCloseTo(23.385075412, 6)
    expect(stages.some(e => e.stage === 'query_deadline_reached')).toBe(false)
    expect(score.wall_budget.passed).toBe(false); expect(score.wall_budget.load_and_delivery_limit_wall_s).toBe(360)
    expect(score.delivery_route_budget.receipt.elapsed_wall_s).toBeCloseTo(34.635851097, 6)
    expect(score.delivery_route_budget.receipt.remaining_wall_s).toBeCloseTo(85.364148903, 6)
    expect(result.orders[0].failure_reason).toContain('不把总预算耗尽写成路线预算到期')
  })
})
