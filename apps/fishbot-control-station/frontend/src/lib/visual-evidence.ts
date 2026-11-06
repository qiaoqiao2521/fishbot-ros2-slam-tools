/** Read-only presentation of recorded visual inputs and original physical receipts. */
const record = (v: unknown): Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {}
const list = (v: unknown): unknown[] => Array.isArray(v) ? v : []
const text = (v: unknown, fallback = '') => typeof v === 'string' && v.trim() ? v : fallback
const number = (v: unknown): number | null => typeof v === 'number' && Number.isFinite(v) ? v : null
const strings = (v: unknown) => list(v).filter((x): x is string => typeof x === 'string')
const boolean = (v: unknown) => typeof v === 'boolean' ? v : null
export function visualAsset(value: unknown): string | null {
  return typeof value === 'string' && /^\/workbench\/[A-Za-z0-9_./-]+$/.test(value) && !value.includes('..') ? value : null
}
export interface VisualMilestone {
  sourceTime: number | null; image: string | null; measuredLift: number | null; originalPassed: boolean | null
}
export interface VisualEvidenceEntry {
  id: string; taskId: string; armId: string; cargoId: string; phase: string
  observation: { sequence: number | null; stamp: number | null; episodeId: string; frame: string; pointCount: number | null }
  images: { rgb: string | null; depth: string | null; mask: string | null; graspOverlay: string | null }
  points: { frame: string; xyz: [number, number, number][] }
  selected: { index: number | null; score: number | null; origin: string; poseCamera: number[][] | null } | null
  inference: { status: string; requestWall: number | null; total: number | null; candidateCount: number | null; sourceReport: string | null }
  milestones: { lift: VisualMilestone | null; placement: VisualMilestone | null }; warnings: string[]
}
export interface VisualQuery {
  id: string; outcome: string; timeout: number | null
  stages: { stage: string; elapsed: number | null; phase: string; candidateIndex: number | null }[]
}
export interface VisualEvidence {
  runId: string; sceneId: string; taskId: string; sourceConfirmed: boolean
  entries: VisualEvidenceEntry[]; queries: VisualQuery[]; warnings: string[]
}
function milestone(value: unknown): VisualMilestone | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const raw = record(value)
  return { sourceTime: number(raw.source_s), image: visualAsset(raw.image), measuredLift: number(raw.measured_lift_m), originalPassed: boolean(raw.original_passed) }
}
function pose(value: unknown): number[][] | null {
  const rows = list(value).map(row => list(row).map(number))
  return rows.length === 4 && rows.every(row => row.length === 4 && row.every(n => n !== null)) ? rows as number[][] : null
}
export function parseVisualEvidence(value: unknown): VisualEvidence {
  const raw = record(value), warnings = [...strings(raw.warnings)]
  const sourceConfirmed = raw.schema === 'fishbot.visual-chain.v1' && raw.new_execution === false && raw.rescored === false
  if (!sourceConfirmed) warnings.push('证据版本或只读导入边界未确认，不能把页面显示解释成新执行或新评分。')
  const entries = list(raw.entries).flatMap((value, index): VisualEvidenceEntry[] => {
    const entry = record(value)
    if (!Object.keys(entry).length) { warnings.push(`第${index + 1}项视觉材料无法识别，其他材料继续展示。`); return [] }
    const observation = record(entry.observation), images = record(entry.images), points = record(entry.points)
    const selected = record(entry.selected), inference = record(entry.inference), milestones = record(entry.milestones)
    const xyz = list(points.xyz).flatMap((value): [number, number, number][] => {
      const vector = list(value).map(number)
      return vector.length === 3 && vector.every(n => n !== null) ? [vector as [number, number, number]] : []
    })
    const entryWarnings = [...strings(entry.warnings)]
    if (xyz.length !== list(points.xyz).length) entryWarnings.push('有坐标缺失或非有限值的点未绘制，未补点。')
    for (const [name, url] of Object.entries(images)) if (url && !visualAsset(url)) entryWarnings.push(`${name}地址无法识别，其余材料保留。`)
    return [{ id: text(entry.id, `visual-entry-${index}`), taskId: text(entry.task_id), armId: text(entry.arm_id, '机械臂未提供'), cargoId: text(entry.cargo_id, '货物未提供'), phase: text(entry.phase, '阶段未提供'),
      observation: { sequence: number(observation.sequence), stamp: number(observation.stamp), episodeId: text(observation.episode_id), frame: text(observation.frame, '坐标系未提供'), pointCount: number(observation.point_count) },
      images: { rgb: visualAsset(images.rgb), depth: visualAsset(images.depth), mask: visualAsset(images.mask), graspOverlay: visualAsset(images.grasp_overlay) },
      points: { frame: text(points.frame, text(observation.frame, '坐标系未提供')), xyz },
      selected: Object.keys(selected).length ? { index: number(selected.index), score: number(selected.score), origin: text(selected.origin, '来源未提供'), poseCamera: pose(selected.pose_camera) } : null,
      inference: { status: text(inference.status, '未取得推理回执'), requestWall: number(inference.request_wall_s), total: number(inference.total_s), candidateCount: number(inference.candidate_count), sourceReport: visualAsset(inference.source_report) },
      milestones: { lift: milestone(milestones.lift), placement: milestone(milestones.placement) }, warnings: entryWarnings }]
  })
  return { runId: text(raw.run_id), sceneId: text(raw.scene_id, '场景未提供'), taskId: text(raw.task_id), sourceConfirmed, entries,
    queries: list(raw.queries).flatMap(value => { const row = record(value); return Object.keys(row).length ? [{ id: text(row.id, '查询身份未提供'), outcome: text(row.outcome, '终态未提供'), timeout: number(row.timeout_s), stages: list(row.stages).map(value => { const stage = record(value); return { stage: text(stage.stage, '事件未提供'), elapsed: number(stage.elapsed_wall_s), phase: text(stage.phase), candidateIndex: number(stage.candidate_index) } }) }] : [] }), warnings }
}
export async function readVisualEvidence(url: string, signal?: AbortSignal): Promise<VisualEvidence> {
  const response = await fetch(url, { method: 'GET', cache: 'no-store', signal })
  if (!response.ok) throw new Error(`视觉证据链读取失败（HTTP ${response.status}），配送摘要与其他材料继续保留。`)
  return parseVisualEvidence(await response.json())
}
