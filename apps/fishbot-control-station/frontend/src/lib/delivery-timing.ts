export interface TimingSpan {
  id: string; label: string; layer: string; parent_id: string | null
  start_wall_s: number | null; end_wall_s: number | null; duration_s: number | null
  goal_id: string | null; terminal_status: number | null; evidence: string
  start_boundary_wall_s: (number | null)[]; end_boundary_wall_s: (number | null)[]
  start_source_s: number | null; end_source_s: number | null; right_censored: boolean
}
export interface TimingGap {
  missing: number | null; before_source_s: number | null; after_source_s: number | null
  before_wall_s: number | null; after_wall_s: number | null; stage_before: string; stage_after: string
}
export interface TimingCase {
  id: string; label: string; task_id: string; episode_id: string; vehicle: string; sensor: string; observation_mode: string
  start_wall_s: number | null; end_wall_s: number | null; task_budget_s: number | null; task_elapsed_s: number | null
  route: { start_wall_s: number | null; end_wall_s: number | null; elapsed_s: number | null; budget_s: number | null; remaining_s: number | null; boundary: string }
  physical: { final_position_error_m: number | null; final_yaw_error_rad: number | null; continuous_final_stop_source_s: number | null }
  sampling: { physics_records: number | null; task_physics_records: number | null; missing_samples: number | null; gaps: TimingGap[] }
  trajectory: { sample_count: number | null; byte_count: number | null }
  guard_seconds: number | null; spans: TimingSpan[]; warnings: string[]; import_status: string
  original_passed: boolean | null; original_verdict: string; unavailable: string[]
}
export interface TimingReport {
  label: string; source_run_id: string; cases: TimingCase[]; warnings: string[]
  historical: boolean; rescored: boolean | null; new_execution: boolean | null
  loop: { name: string; count: number | null; max_s: number | null }[]
  source: Record<string, unknown>
}
const record = (v: unknown): Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {}
const list = (v: unknown): unknown[] => Array.isArray(v) ? v : []
const strings = (v: unknown) => list(v).filter((item): item is string => typeof item === 'string')
const text = (v: unknown, fallback = '未提供') => typeof v === 'string' && v.trim() ? v : fallback
const numeric = (v: unknown): number | null => typeof v === 'number' && Number.isFinite(v) ? v : null
const boolean = (v: unknown): boolean | null => typeof v === 'boolean' ? v : null

export function parseDeliveryTiming(input: unknown): TimingReport {
  const raw = record(input), warnings = strings(raw.warnings)
  if (raw.schema !== 'fishbot.delivery-timing.v1') warnings.push('报告版本未确认，按可识别字段展示。')
  if (raw.scope !== 'historical_simulation_import' || raw.new_execution !== false || raw.rescored !== false) warnings.push('来源边界未确认，不能按新执行或重新评分解释。')
  if (!Array.isArray(raw.cases)) warnings.push('未提供案例列表，可补齐后重新导入。')
  const cases = list(raw.cases).flatMap((entry, index): TimingCase[] => {
    const c = record(entry)
    if (!Object.keys(c).length) { warnings.push(`第 ${index + 1} 条案例无法识别，其余案例继续展示。`); return [] }
    const route = record(c.route), physical = record(c.physical), sampling = record(c.sampling), trajectory = record(c.trajectory), verdict = record(c.original_verdict)
    const guardValues = list(c.guard).map(item => numeric(record(item).tripped_observed_contiguous_source_duration_s))
    return [{
      id: text(c.id, `case-${index}`), label: text(c.label, `案例 ${index + 1}`), task_id: text(c.task_id), episode_id: text(c.episode_id),
      vehicle: text(c.vehicle), sensor: text(c.sensor), observation_mode: text(c.observation_mode),
      start_wall_s: numeric(c.start_wall_s), end_wall_s: numeric(c.end_wall_s), task_budget_s: numeric(c.task_budget_s), task_elapsed_s: numeric(c.task_elapsed_s),
      route: { start_wall_s: numeric(route.start_wall_s), end_wall_s: numeric(route.end_wall_s), elapsed_s: numeric(route.elapsed_s), budget_s: numeric(route.budget_s), remaining_s: numeric(route.remaining_s), boundary: text(route.boundary) },
      physical: { final_position_error_m: numeric(physical.final_position_error_m), final_yaw_error_rad: numeric(physical.final_yaw_error_rad), continuous_final_stop_source_s: numeric(physical.continuous_final_stop_source_s) },
      sampling: { physics_records: numeric(sampling.physics_records), task_physics_records: numeric(sampling.task_physics_records), missing_samples: numeric(sampling.missing_samples),
        gaps: list(sampling.gaps).map(item => { const g = record(item); return { missing: numeric(g.missing), before_source_s: numeric(g.before_source_s), after_source_s: numeric(g.after_source_s), before_wall_s: numeric(g.before_wall_s), after_wall_s: numeric(g.after_wall_s), stage_before: text(g.stage_before), stage_after: text(g.stage_after) } }) },
      trajectory: { sample_count: numeric(trajectory.sample_count), byte_count: numeric(trajectory.byte_count) },
      guard_seconds: guardValues.length && guardValues.every(v => v !== null) ? guardValues.reduce<number>((sum, v) => sum + (v ?? 0), 0) : null,
      original_passed: boolean(verdict.original_score_passed), original_verdict: text(verdict.task_verdict), import_status: text(c.import_status),
      warnings: strings(c.warnings), unavailable: strings(c.unavailable),
      spans: list(c.spans).flatMap((item, i) => { const s = record(item); if (!Object.keys(s).length) return []; return [{
        id: text(s.id, `span-${i}`), label: text(s.label), layer: text(s.layer), parent_id: typeof s.parent_id === 'string' ? s.parent_id : null,
        start_wall_s: numeric(s.start_wall_s), end_wall_s: numeric(s.end_wall_s), duration_s: numeric(s.duration_s), goal_id: typeof s.goal_id === 'string' ? s.goal_id : null,
        terminal_status: numeric(s.terminal_status), evidence: text(s.evidence, s.layer === 'interval' ? '动作回执之间的区间，未归因为规划或控制耗时。' : '原报告时间区间'),
        start_boundary_wall_s: list(s.start_boundary_wall_s).map(numeric), end_boundary_wall_s: list(s.end_boundary_wall_s).map(numeric),
        start_source_s: numeric(s.start_source_s), end_source_s: numeric(s.end_source_s), right_censored: s.right_censored === true,
      }] }),
    }]
  })
  return { source: raw, label: text(raw.label, '配送耗时报告'), source_run_id: text(raw.source_run_id), cases, warnings,
    historical: raw.scope === 'historical_simulation_import', rescored: boolean(raw.rescored), new_execution: boolean(raw.new_execution),
    loop: Object.entries(record(record(raw.loop_diagnostics).stages)).map(([name, v]) => ({ name, count: numeric(record(v).count), max_s: numeric(record(v).max_s) })) }
}

export function timingWindow(item: TimingCase, mode: 'route' | 'task') {
  const origin = mode === 'route' ? item.route.start_wall_s : item.start_wall_s
  const budget = mode === 'route' ? item.route.budget_s : item.task_budget_s
  const elapsed = mode === 'route' ? item.route.elapsed_s : item.task_elapsed_s
  const limit = Math.max(1, budget ?? 0, elapsed ?? 0) * 1.04
  const spans = item.spans.filter(s => mode === 'route' ? s.parent_id === 'route' : s.layer === 'observed_stage' || s.id === 'route' || (s.layer === 'native' && s.parent_id !== 'route'))
  return { origin, budget, elapsed, limit, spans }
}

export async function readDeliveryTiming(signal?: AbortSignal, fetcher: typeof fetch = fetch) {
  const response = await fetcher('/workbench/delivery-timing.json', { method: 'GET', cache: 'no-store', signal })
  if (!response.ok) throw new Error(`耗时报告读取失败（HTTP ${response.status}）。可重试或导入本地 JSON。`)
  return parseDeliveryTiming(await response.json())
}

export async function readLocalDeliveryTiming(file: Pick<File, 'size' | 'text'>) {
  if (file.size > 4 * 1024 * 1024) throw new Error('请选择 4MB 以内的摘要 JSON，原始物理日志留在离线导入器处理。')
  return parseDeliveryTiming(JSON.parse(await file.text()))
}
