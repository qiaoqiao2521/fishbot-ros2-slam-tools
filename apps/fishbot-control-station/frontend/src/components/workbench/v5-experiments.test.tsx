import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import catalog from '../../../public/workbench/delivery-results.json'
import warehouse from '../../../public/workbench/f2-warehouse-v5-result.json'
import workshop from '../../../public/workbench/f2-workshop-v5-result.json'
import chain from '../../../public/workbench/f2-warehouse-v5/visual/visual-chain.json'
import candidates from '../../../public/workbench/f2-warehouse-v5/visual/b98bf0fa-4522-42a3-974c-6b3dc69db49d-load-cargo_1-1474/generated-candidates.json'
import model from '../../../public/workbench/f2-warehouse-v5/visual/b98bf0fa-4522-42a3-974c-6b3dc69db49d-load-cargo_1-1474/model-report.json'
import components from '../../../public/workbench/f2-workshop-v5/original-components.json'
import { parseVisualEvidence } from '@/lib/visual-evidence'
import { VisualEvidencePanel } from './visual-evidence-panel'

describe('v5 actual inference and incomplete transport', () => {
  it('preserves source identity and all older results as independent records', () => {
    expect(catalog.groups).toHaveLength(4)
    for (const id of ['f2-workshop-v2', 'f2-warehouse-v3', 'f2-warehouse-v4', 'f2-workshop-v4', 'f2-warehouse-v5', 'f2-workshop-v5']) expect(catalog.experiments.some(e => e.id === id)).toBe(true)
    expect(chain.run_id).toBe(warehouse.run_id); expect(chain.entries[0].task_id).toBe(warehouse.orders[0].task_id)
    expect(chain.scene_id).toBe('f1-j100-wide-continuous-ba'); expect(chain.candidate_label).toBe('f2-wide-warehouse')
    expect(warehouse.orders[0].passed).toBe(false); expect(workshop.orders[0].passed).toBe(false)
  })
  it('shows actual312-point input and original408 proposals without inventing selected or physical milestones', () => {
    const report = parseVisualEvidence(chain), entry = report.entries[0]
    expect(entry.points.xyz).toHaveLength(312); expect(entry.observation.pointCount).toBe(312)
    expect(entry.observation.stamp).toBeCloseTo(29.49999999999453, 10)
    expect(entry.inference.status).toBe('inference_completed'); expect(entry.inference.requestWall).toBeCloseTo(4.57680908, 7)
    expect(model.candidate_count).toBe(408); expect(model.diffusion_count).toBe(48); expect(model.obb_count).toBe(360)
    expect(candidates.candidates).toHaveLength(408); expect(candidates.candidates.map(c => c.index)).toEqual(Array.from({ length: 408 }, (_, i) => i))
    expect(candidates.candidates.filter(c => c.origin === 'diff')).toHaveLength(48)
    expect(candidates.candidates.filter(c => c.origin === 'obb')).toHaveLength(360)
    expect(entry.generatedCandidates?.count).toBe(408); expect(entry.generatedCandidates?.preview.map(c => c.index)).toEqual([0, 1, 2, 3, 4, 5, 6, 7])
    expect(entry.selected).toBeNull(); expect(entry.milestones.lift).toBeNull(); expect(entry.milestones.placement).toBeNull()
    const html = renderToStaticMarkup(<VisualEvidencePanel sourceUrl={warehouse.assets.visual_chain} initialReport={chain} expectedRunId={warehouse.run_id} taskId={warehouse.orders[0].task_id} />)
    expect(html).toContain('模型生成候选（未执行）'); expect(html).toContain('未提供已执行的候选选择')
    expect(html).toContain('请求 4.577 s'); expect(html).toContain('下载全部生成候选')
  })
  it('locates timeout after actual model inference at candidate51 OMPL rather than claiming model failure', () => {
    const stages = parseVisualEvidence(chain).queries[0].stages
    const request = stages.find(s => s.stage === 'official_inference_request_started')!
    const response = stages.find(s => s.stage === 'official_inference_response_received')!
    expect(response.elapsed! - request.elapsed!).toBeCloseTo(model.inference_request_wall_s, 3)
    expect(stages.find(s => s.phase === 'ompl_approach' && s.candidateIndex === 51)?.elapsed).toBeCloseTo(24.900163009, 6)
    expect(stages.find(s => s.stage === 'query_deadline_reached')?.elapsed).toBeCloseTo(30.032522127, 6)
  })
  it('keeps actual K transport success separate from destination/360s/unload business failure', () => {
    expect(workshop.observation_mode).toBe('ideal'); expect(workshop.sensor).toContain('360×16')
    expect('visual_chain' in workshop.assets).toBe(false)
    expect(components.pickup_and_transport_observed.passed).toBe(true)
    expect(components.pickup_and_transport_observed.transport.max_true_cargo_displacement_m).toBeCloseTo(2.2741997776, 8)
    expect(components.wall_budget.passed).toBe(false); expect(components.wall_budget.load_and_delivery_limit_wall_s).toBe(360)
    expect(components.unload_samples_after_arrival).toBe(0); expect(components.original_task_passed).toBe(false)
    expect(workshop.orders[0].failure_reason).toContain('终态5'); expect(workshop.orders[0].failure_reason).toContain('B未完成')
  })
})
