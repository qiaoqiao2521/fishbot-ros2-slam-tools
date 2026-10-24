/** Recorded delivery projections only. No runtime, ROS or command dependency. */
type ObjectValue = Record<string, unknown>
const object = (v: unknown): ObjectValue => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as ObjectValue : {}
const list = (v: unknown): unknown[] => Array.isArray(v) ? v : []
const numeric = (v: unknown): number | null => typeof v === 'number' && Number.isFinite(v) ? v : null
const text = (v: unknown, fallback = '未知') => typeof v === 'string' && v ? v : fallback
const vector = (v: unknown, n: number): number[] | null => Array.isArray(v) && v.length === n && v.every(x => numeric(x) !== null && Math.abs(x as number) <= 1e6) ? v as number[] : null

export type ReplayFrame = { source: number; sequence: number | null; stage: string; gap: boolean; hold: boolean | null
  car: number[] | null; quaternion: number[] | null; cargo: number[] | null; joints: number[][]; q6: number[] | null }
export type ReplayRun = { id: string; label: string; group: string; taskId: string; episodeId: string; scope: string; snapshot: string | null
  passed: boolean | null; routeSeconds: number | null; budget: number | null; positionError: number | null; yawError: number | null
  missing: number | null; guardSeconds: number | null; anchors: Record<string, number>; frames: ReplayFrame[]; warnings: string[]
  nativeActions: { label: string; uuid: string; status: number | null }[] }
export type ReplayReport = { source: ObjectValue; runs: ReplayRun[]; bounds: number[]; warnings: string[]; sameSnapshot: boolean; sameScene: boolean
  boxes: { id: string; position: number[]; size: number[]; yaw: number }[]; footprint: number[][] }

export function parseDeliveryComparison(input: unknown): ReplayReport {
  const raw = object(input), warnings: string[] = []
  if (raw.schema !== 'fishbot.delivery-comparison.v1') warnings.push('报告版本未确认，按可识别字段展示。')
  if (raw.read_only !== true || raw.rescored !== false) warnings.push('来源边界未确认；播放不代表执行或重新评分。')
  const runs = list(raw.runs).flatMap((entry, index): ReplayRun[] => {
    const run = object(entry), notes = list(run.warnings).filter((s): s is string => typeof s === 'string')
    if (!Object.keys(run).length) { warnings.push(`第 ${index + 1} 个回合无法读取，其余回合继续展示。`); return [] }
    let previous = -Infinity, interrupted = false, invalidFrames = 0
    const frames = list(run.frames).slice(0, 20000).flatMap((entry): ReplayFrame[] => {
      const frame = object(entry), source = numeric(frame.source_s)
      if (source === null || source <= previous) { interrupted = true; invalidFrames++; return [] }
      const gap = frame.gap_before === true || interrupted
      previous = source; interrupted = false
      return [{ source, sequence: numeric(frame.sequence), stage: text(frame.stage), gap,
        hold: typeof frame.hold === 'boolean' ? frame.hold : null,
        car: vector(frame.car, 3), quaternion: vector(frame.quaternion, 4), cargo: vector(frame.cargo, 3),
        joints: list(frame.arm_joints_world).flatMap(v => { const p = vector(v, 3); return p ? [p] : [] }), q6: vector(frame.arm_q6, 6) }]
    })
    if (list(run.frames).length > 20000) notes.push('超过展示帧数上限，仅显示前 20000 帧；原评分保持。')
    if (invalidFrames) notes.push(`跳过 ${invalidFrames} 个无效或未递增采样；展示不完整，缺口未补造。`)
    const anchors: Record<string, number> = {}
    for (const [name, value] of Object.entries(object(run.anchors))) if (numeric(value) !== null) anchors[name] = value as number
    const verdict = object(run.original_verdict), route = object(run.route), physical = object(run.physical)
    const guards = list(run.guard).map(v => numeric(object(v).tripped_observed_contiguous_source_duration_s))
    return [{ id: text(run.id, `run-${index}`), label: text(run.label), group: text(run.group, 'unassigned'), taskId: text(run.task_id), episodeId: text(run.episode_id),
      scope: text(run.scope), snapshot: typeof run.snapshot_id === 'string' ? run.snapshot_id : null,
      passed: typeof verdict.original_score_passed === 'boolean' ? verdict.original_score_passed : null,
      routeSeconds: numeric(route.elapsed_s), budget: numeric(route.budget_s), positionError: numeric(physical.final_position_error_m),
      yawError: numeric(physical.final_yaw_error_rad), missing: numeric(object(run.sampling).missing_samples),
      guardSeconds: guards.length && guards.every(v => v !== null) ? guards.reduce<number>((sum, v) => sum + (v ?? 0), 0) : null,
      anchors, frames, warnings: notes,
      nativeActions: list(run.spans).flatMap(entry => { const span = object(entry)
        return span.layer === 'native' && typeof span.goal_id === 'string' ? [{ label: text(span.label), uuid: span.goal_id, status: numeric(span.terminal_status) }] : [] }) }]
  })
  const scene = object(raw.scene), bounds = vector(raw.view_bounds_xy, 4)
  return { source: raw, runs, warnings, sameSnapshot: raw.same_checkpoint_id === true, sameScene: raw.same_scene_geometry === true,
    bounds: bounds && bounds[2] > bounds[0] && bounds[3] > bounds[1] ? bounds : [-2, -3, 2, 0],
    boxes: list(scene.static_boxes).flatMap(entry => { const box = object(entry), position = vector(box.position, 3), size = vector(box.half_size, 3)
      return position && size && size.every(v => v >= 0) ? [{ id: text(box.id), position, size, yaw: numeric(box.yaw) ?? 0 }] : [] }),
    footprint: list(scene.car_footprint_xy).flatMap(v => { const p = vector(v, 2); return p ? [p] : [] }) }
}

/** Last observed sample only. A missing interval is never filled by interpolation. */
export function replayFrame(run: ReplayRun, elapsed: number, anchor: string): ReplayFrame | null {
  const start = run.anchors[anchor]
  if (start === undefined || !Number.isFinite(elapsed)) return null
  const target = start + elapsed
  let a = 0, b = run.frames.length
  while (a < b) { const m = (a + b) >>> 1; if (run.frames[m].source <= target) a = m + 1; else b = m }
  const frame = run.frames[a - 1]
  return frame && target - frame.source <= .15 ? frame : null
}

export function replayPath(run: ReplayRun): string {
  let path = '', pen = false
  for (const frame of run.frames) {
    if (!frame.car) { pen = false; continue }
    path += `${!pen || frame.gap ? 'M' : 'L'}${frame.car[0]},${-frame.car[1]} `
    pen = true
  }
  return path.trim()
}

export function commonAnchors(runs: ReplayRun[]): string[] {
  return runs.length ? Object.keys(runs[0].anchors).filter(k => runs.every(r => k in r.anchors)) : []
}

export function runDuration(run: ReplayRun, anchor: string): number {
  const last = run.frames.at(-1)
  return last && run.anchors[anchor] !== undefined ? Math.max(0, last.source - run.anchors[anchor]) : 0
}

export function distribution(values: (number | null)[]) {
  const finite = values.filter((n): n is number => n !== null && Number.isFinite(n)).sort((a, b) => a - b)
  const q = (n: number) => finite.length ? finite[Math.max(0, Math.ceil(n * finite.length) - 1)] : null
  return { n: finite.length, p25: q(.25), median: q(.5), p75: q(.75), p95: q(.95), min: q(0), max: q(1), missing: values.length - finite.length }
}

export async function readComparison(file: Pick<File, 'size' | 'text'>): Promise<ReplayReport> {
  if (file.size > 8 * 1024 * 1024) throw new Error('请选择 8 MiB 以内的对照摘要；原始日志由离线导入器处理。')
  return parseDeliveryComparison(JSON.parse(await file.text()))
}
