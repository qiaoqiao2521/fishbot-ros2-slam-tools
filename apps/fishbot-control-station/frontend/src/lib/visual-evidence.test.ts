import { describe, expect, it, vi } from 'vitest'
import { parseVisualEvidence, readVisualEvidence, visualAsset } from './visual-evidence'

describe('recorded visual evidence', () => {
  it('preserves original failed and missing physical receipts without turning inference into success', () => {
    const report = parseVisualEvidence({ schema: 'fishbot.visual-chain.v1', new_execution: false, rescored: false, run_id: 'recorded-run', entries: [{ id: 'capture', task_id: 'task-b', observation: { sequence: 12, stamp: 3, point_count: 2 }, selected: { index: 0, score: .9 }, inference: { status: 'inference_completed', request_wall_s: 1.3, candidate_count: 12 }, milestones: { lift: { original_passed: false, source_s: 4, measured_lift_m: .01 }, placement: null }, points: { xyz: [[1, 2, 3], [4, 5, 6]] } }] })
    expect(report.sourceConfirmed).toBe(true)
    expect(report.entries[0].selected?.index).toBe(0)
    expect(report.entries[0].milestones.lift?.originalPassed).toBe(false)
    expect(report.entries[0].milestones.placement).toBeNull()
    expect(report.entries[0].inference.requestWall).toBe(1.3)
  })
  it('degrades one bad optional image and invalid point without adding fabricated geometry', () => {
    const report = parseVisualEvidence({ schema: 'editable', entries: [null, { images: { rgb: '/coop-api/start', depth: '/workbench/depth.png' }, points: { xyz: [[1, 2, 3], [null, 0, 0], [1, Infinity, 3]] }, selected: { pose_camera: [[1]] } }] })
    expect(report.entries).toHaveLength(1)
    expect(report.entries[0].images.rgb).toBeNull(); expect(report.entries[0].images.depth).toBe('/workbench/depth.png')
    expect(report.entries[0].points.xyz).toEqual([[1, 2, 3]])
    expect(report.entries[0].selected?.poseCamera).toBeNull()
    expect(report.entries[0].warnings.length).toBeGreaterThan(0)
    expect(report.sourceConfirmed).toBe(false)
  })
  it('retains optional raw candidate phase and index without changing timing or event order', () => {
    const events = [{ stage: 'candidate_phase_started', phase: 'ompl_approach', candidate_index: 0, elapsed_wall_s: 7.123456 }, { stage: 'candidate_phase_finished', phase: 'editable_phase', candidate_index: 8, elapsed_wall_s: 7.923456 }]
    const report = parseVisualEvidence({ queries: [{ id: 'query', stages: events }] })
    expect(report.queries[0].stages).toEqual([
      { stage: 'candidate_phase_started', phase: 'ompl_approach', candidateIndex: 0, elapsed: 7.123456 },
      { stage: 'candidate_phase_finished', phase: 'editable_phase', candidateIndex: 8, elapsed: 7.923456 },
    ])
  })
  it('does not admit remote or parent-relative assets', () => {
    expect(visualAsset('https://example.com/image.png')).toBeNull()
    expect(visualAsset('/workbench/../private')).toBeNull()
    expect(visualAsset('/workbench/capture/rgb.png')).toBe('/workbench/capture/rgb.png')
  })
  it('reads through GET only and reports unavailable material separately', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: false, status: 404 }); vi.stubGlobal('fetch', fetcher)
    try {
      await expect(readVisualEvidence('/workbench/visual-chain.json')).rejects.toThrow('HTTP 404')
      expect(fetcher).toHaveBeenCalledWith('/workbench/visual-chain.json', expect.objectContaining({ method: 'GET' }))
    } finally { vi.unstubAllGlobals() }
  })
})
