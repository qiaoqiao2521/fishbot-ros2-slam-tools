import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { VisualEvidencePanel } from './visual-evidence-panel'

// UI-only fixture, never published as a recorded task or physical result.
const fixture = {
  schema: 'fishbot.visual-chain.v1', run_id: 'ui-only-run', scene_id: 'ui-only-scene', new_execution: false, rescored: false,
  entries: [{ id: 'ui-input', task_id: 'task-b', arm_id: 'load', cargo_id: 'cargo-b', phase: 'load',
    observation: { sequence: 11, stamp: 2, episode_id: 'ui-episode', frame: 'camera', point_count: 2 },
    images: { rgb: '/workbench/ui-rgb.png', depth: '/workbench/ui-depth.png', grasp_overlay: '/workbench/ui-candidate.png' },
    points: { frame: 'camera', xyz: [[.1, .2, .3], [.2, .3, .4]] }, selected: { index: 8, score: .82, origin: 'obb' },
    inference: { status: 'inference_completed', request_wall_s: 1.3, total_s: 2.1, candidate_count: 408 },
    milestones: { lift: { source_s: 4, image: '/workbench/ui-lift.png', measured_lift_m: .04, original_passed: false }, placement: null } }],
  queries: [{ id: 'ui-query', outcome: 'timeout', timeout_s: 30, stages: [{ stage: 'planner_init_started', elapsed_wall_s: .1 }, { stage: 'planner_init_completed', elapsed_wall_s: 10 }] }],
}
describe('visual evidence panel', () => {
  it('renders input-to-action stages while preserving a failed physical milestone and missing placement', () => {
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher)
    try {
      const html = renderToStaticMarkup(<VisualEvidencePanel sourceUrl="/workbench/ui-chain.json" initialReport={fixture} expectedRunId="ui-only-run" taskId="task-b" />)
      for (const label of ['RGB／深度输入', '实际可见点云', '所选抓取候选', '实际抬升', '实际放货']) expect(html).toContain(label)
      expect(html).toContain('原分项评分未通过'); expect(html).toContain('未提供原分项评分')
      expect(html).toContain('模型分数不解释为成功概率'); expect(html).toContain('实际放货采样画面未提供')
      expect(html).toContain('40.000 mm'); expect(html).toContain('累计 10.000 s')
      expect(html).not.toContain('/coop-api/start'); expect(fetcher).not.toHaveBeenCalled()
    } finally { vi.unstubAllGlobals() }
  })
  it('explains known query stages in Chinese while preserving raw identifiers, order and elapsed times', () => {
    const stages = [
      { stage: 'planner_init_started', elapsed_wall_s: .1 },
      { stage: 'world_model_compile_started', elapsed_wall_s: 1.2 },
      { stage: 'rgbd_render_started', elapsed_wall_s: 8.3 },
      { stage: 'visible_cloud_saved', elapsed_wall_s: 9.4 },
      { stage: 'official_inference_request_started', elapsed_wall_s: 10.5 },
      { stage: 'official_inference_response_received', elapsed_wall_s: 12.6 },
      { stage: 'candidate_phase_started', elapsed_wall_s: 14.7 },
      { stage: 'ompl_approach', elapsed_wall_s: 20.8 },
      { stage: 'unknown_editable_stage', elapsed_wall_s: 29.9 },
      { stage: 'query_deadline_reached', elapsed_wall_s: 30.1 },
      { stage: 'child_exited', elapsed_wall_s: 30.2 },
    ]
    const html = renderToStaticMarkup(<VisualEvidencePanel sourceUrl="/workbench/ui-chain.json" initialReport={{ ...fixture, queries: [{ id: 'ui-timeout', outcome: 'TimeoutError', timeout_s: 30, stages }] }} />)
    for (const label of ['规划初始化开始', '世界模型编译开始', '相机渲染开始', '可见点云已保存', '模型推理请求', '模型候选响应', '候选IK／碰撞／OMPL步骤开始', 'OMPL接近路径规划', '原30秒到期', '子进程退出', '查询超时']) expect(html).toContain(label)
    expect(html).toContain('<code>TimeoutError</code>')
    expect(html).toContain('<code>query_deadline_reached</code>')
    expect(html).toContain('unknown_editable_stage'); expect(html).toContain('累计 30.100 s')
    expect(html.indexOf('模型推理请求')).toBeLessThan(html.indexOf('模型候选响应'))
  })
  it('names actual candidate phases without losing the original identifiers or index zero', () => {
    const html = renderToStaticMarkup(<VisualEvidencePanel sourceUrl="/workbench/ui-chain.json" initialReport={{ ...fixture, queries: [{ id: 'ui-phases', outcome: 'accepted', timeout_s: 30, stages: [
      { stage: 'candidate_phase_started', phase: 'grasp_ik', candidate_index: 0, elapsed_wall_s: 1.1 },
      { stage: 'candidate_phase_finished', phase: 'transfer_release_sweep', candidate_index: 51, elapsed_wall_s: 2.2 },
      { stage: 'candidate_phase_started', phase: 'ompl_approach', candidate_index: 51, elapsed_wall_s: 3.3 },
      { stage: 'candidate_phase_finished', phase: 'editable_phase', candidate_index: 51, elapsed_wall_s: 4.4 },
    ] }] }} />)
    for (const label of ['抓取姿态IK开始', '开爪碰撞扫掠完成', 'OMPL接近路径规划开始', 'editable_phase完成', '规划结果已接纳（非物理成功）']) expect(html).toContain(label)
    expect(html).toContain('<code>candidate_phase_started</code>'); expect(html).toContain('<code>ompl_approach</code>')
    expect(html).toContain('候选 #0'); expect(html).toContain('候选 #51'); expect(html).toContain('累计 3.300 s')
  })
  it('keeps a different run out of the active order without blocking other materials', () => {
    const html = renderToStaticMarkup(<VisualEvidencePanel sourceUrl="/workbench/ui-chain.json" initialReport={fixture} expectedRunId="other-run" />)
    expect(html).toContain('与当前配送运行不一致')
    expect(html).not.toContain('<img'); expect(html).toContain('下载视觉证据目录')
  })
  it('does not substitute another task when the chosen order has no evidence', () => {
    const html = renderToStaticMarkup(<VisualEvidencePanel sourceUrl="/workbench/ui-chain.json" initialReport={fixture} expectedRunId="ui-only-run" taskId="task-a" />)
    expect(html).toContain('当前订单没有匹配的视觉输入或候选记录')
    expect(html).not.toContain('src="/workbench/ui-rgb.png"')
  })
})
