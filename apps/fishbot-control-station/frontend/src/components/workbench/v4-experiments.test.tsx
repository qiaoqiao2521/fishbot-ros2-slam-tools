import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import catalog from '../../../public/workbench/delivery-results.json'
import warehouse from '../../../public/workbench/f2-warehouse-v4-result.json'
import workshop from '../../../public/workbench/f2-workshop-v4-result.json'
import chain from '../../../public/workbench/f2-warehouse-v4/visual-chain.json'
import components from '../../../public/workbench/f2-workshop-v4/original-components.json'
import warehouseTiming from '../../../public/workbench/f2-warehouse-v4/timing.json'
import workshopTiming from '../../../public/workbench/f2-workshop-v4/timing.json'
import warehouseIndex from '../../../public/workbench/f2-warehouse-v4/video-frame-index.json'
import workshopIndex from '../../../public/workbench/f2-workshop-v4/video-frame-index.json'
import { parseVisualEvidence } from '@/lib/visual-evidence'
import { VisualEvidencePanel } from './visual-evidence-panel'

describe('v4 actual failed experiments', () => {
  it('preserves four original groups and separate failed experiments with matching task boundaries', () => {
    expect(catalog.groups).toHaveLength(4)
    for (const [result, timing] of [[warehouse, warehouseTiming], [workshop, workshopTiming]] as const) {
      expect(result.orders).toHaveLength(1); expect(result.orders[0].passed).toBe(false)
      expect(result.provenance.new_execution).toBe(false); expect(result.provenance.rescored).toBe(false)
      expect(timing.source_run_id).toBe(result.run_id); expect(timing.cases[0].task_id).toBe(result.orders[0].task_id)
      expect(catalog.experiments.some(e => e.source === `/workbench/${result === warehouse ? 'f2-warehouse-v4' : 'f2-workshop-v4'}-result.json`)).toBe(true)
    }
    expect(catalog.experiments.some(e => e.id === 'f2-workshop-v2')).toBe(true)
    expect(catalog.experiments.some(e => e.id === 'f2-warehouse-v3')).toBe(true)
  })
  it('shows recovered RGB-D and the true ABI boundary without a synthetic cloud or inference', () => {
    const parsed = parseVisualEvidence(chain), entry = parsed.entries[0]
    expect(chain.scene_id).toBe('f1-j100-wide-continuous-ba')
    expect(chain.candidate_label).toBe('f2-wide-warehouse')
    expect(chain.scene_profile_label).toBe('f2-wide-warehouse')
    expect(parsed.runId).toBe(warehouse.run_id); expect(entry.taskId).toBe(warehouse.orders[0].task_id)
    expect(entry.observation.sequence).toBe(1663); expect(entry.observation.stamp).toBeCloseTo(33.27999999999471, 10)
    expect(chain.entries[0].provenance.source_stamp_basis).toBe('derived_from_query_request')
    expect(entry.images.rgb).toBeTruthy(); expect(entry.images.depth).toBeTruthy()
    expect(entry.points.xyz).toEqual([]); expect(entry.selected).toBeNull()
    expect(entry.inference.requestWall).toBeNull(); expect(entry.inference.candidateCount).toBeNull()
    expect(entry.milestones.lift).toBeNull(); expect(entry.milestones.placement).toBeNull()
    const stages = parsed.queries[0].stages
    expect(stages.find(e => e.stage === 'query_failed')?.elapsed).toBeCloseTo(9.988783045, 6)
    expect(stages.some(e => ['official_inference_request_started', 'query_deadline_reached'].includes(e.stage))).toBe(false)
    const html = renderToStaticMarkup(<VisualEvidencePanel sourceUrl="/workbench/f2-warehouse-v4/visual-chain.json" initialReport={chain} expectedRunId={warehouse.run_id} taskId={warehouse.orders[0].task_id} />)
    expect(html).toContain('原始 RGB'); expect(html).toContain('未调用：可见点云提取ImportError')
    expect(html).not.toContain('本回合未保存RGB-D输入')
  })
  it('separates genuine ideal loading milestones from original360s transport failure', () => {
    expect(workshop.observation_mode).toBe('ideal')
    expect(workshop.sensor).toContain('360×16'); expect(workshop.sensor).not.toContain('MID-360')
    expect('visual_chain' in workshop.assets).toBe(false)
    const phase = components.pickup_and_transport_observed
    expect(phase.actual_lift_and_two_tip_forces.passed).toBe(true)
    expect(phase.released_full_footprint_supported_and_relative_rest.passed).toBe(true)
    expect(phase.arm_home_before_motion.passed).toBe(true)
    expect(phase.transport.passed).toBe(false); expect(phase.final_car_and_cargo_rest.passed).toBe(false)
    expect(components.wall_budget.load_and_delivery_limit_wall_s).toBe(360)
    expect(components.wall_budget.load_and_delivery_wall_s).toBeGreaterThan(360)
    expect(components.original_task_passed).toBe(false); expect(components.unload_samples_after_arrival).toBe(0)
    expect(workshop.orders[0].component_summary).toContain('源66.260s')
  })
  it('publishes curated actual-frame indices with original episode and no raw recording log', () => {
    for (const [result, index, count] of [[warehouse, warehouseIndex, 201], [workshop, workshopIndex, 703]] as const) {
      expect(result.assets.video_index).toMatch(/video-frame-index\.json$/)
      expect(index.new_execution).toBe(false); expect(index.rescored).toBe(false)
      expect(index.frame_count).toBe(count); expect(index.frames).toHaveLength(count)
      expect(index.frames.every(f => f.episode_id === result.provenance.episode_id)).toBe(true)
      expect(Object.keys(index.frames[0]).sort()).toEqual(['episode_id', 'scene_id', 'sim_s', 'source_s', 'video_frame'])
    }
  })
})
