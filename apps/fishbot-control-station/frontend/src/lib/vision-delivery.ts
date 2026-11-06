/** A small read-only index over existing delivery reports and recorded media. */
const object = (v: unknown): Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {}
const number = (v: unknown): number | null => typeof v === 'number' && Number.isFinite(v) ? v : null
const text = (v: unknown, fallback = '') => typeof v === 'string' && v.trim() ? v : fallback
const array = (v: unknown): unknown[] => Array.isArray(v) ? v : []

export interface VisionOrder {
  id: string; label: string; taskId: string; passed: boolean | null
  routeSeconds: number | null; positionError: number | null; yawError: number | null
  points: number[]; candidates: number[]
}
export interface VisionResult {
  source: Record<string, unknown>; title: string; recordedAt: string; runId: string; evidenceKind: string
  vehicle: string; sensor: string; model: string; resets: number | null; elapsed: number | null
  orders: VisionOrder[]; timingUrl: string | null; replayUrl: string | null; videoUrl: string | null
  availabilityNote: string; archiveStatus: string; archiveUrl: string | null; warnings: string[]
}

function driveArchive(value: unknown): string | null {
  if (typeof value !== 'string') return null
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && url.hostname === 'drive.google.com' && !url.username && !url.password && /^\/file\/d\/[A-Za-z0-9_-]+\/view$/.test(url.pathname) ? value : null
  } catch { return null }
}

function asset(value: unknown, warnings: string[]): string | null {
  if (value === null || value === undefined || value === '') return null
  if (typeof value === 'string' && /^\/workbench\/[A-Za-z0-9_./-]+$/.test(value) && !value.includes('..')) return value
  warnings.push('一项媒体地址无法识别，其余成果继续展示。')
  return null
}

export function parseVisionResult(input: unknown): VisionResult {
  const source = object(input), warnings: string[] = [], assets = object(source.assets)
  if (source.schema !== 'fishbot.vision-delivery-result.v1') warnings.push('成果版本未确认，按可识别字段展示。')
  const orders = array(source.orders).flatMap((entry, i): VisionOrder[] => {
    const row = object(entry)
    if (!Object.keys(row).length) { warnings.push(`跳过第${i + 1}条无法识别的订单。`); return [] }
    return [{ id: text(row.id, `order-${i}`), label: text(row.label, `订单 ${i + 1}`), taskId: text(row.task_id),
      passed: typeof row.passed === 'boolean' ? row.passed : null,
      routeSeconds: number(row.route_seconds), positionError: number(row.position_error_m), yawError: number(row.yaw_error_rad),
      points: array(row.visible_points).flatMap(v => number(v) === null ? [] : [v as number]),
      candidates: array(row.selected_candidates).flatMap(v => number(v) === null ? [] : [v as number]) }]
  })
  return { source, title: text(source.title, 'J100 视觉配送'), recordedAt: text(source.recorded_at, '日期未提供'),
    runId: text(source.run_id, '运行身份未提供'), evidenceKind: text(source.evidence_kind, '未确认来源'),
    vehicle: text(source.vehicle, 'J100'), sensor: text(source.sensor, '3D 雷达'), model: text(source.model, 'GraspGen-X'),
    resets: number(source.reset_count), elapsed: number(source.elapsed_wall_s), orders,
    timingUrl: asset(assets.timing, warnings), replayUrl: asset(assets.replay, warnings), videoUrl: asset(assets.video, warnings),
    availabilityNote: text(source.availability_note), archiveStatus: text(source.archive_status, '归档状态未确认'), archiveUrl: driveArchive(source.archive_url), warnings }
}

export async function readVisionResult(signal?: AbortSignal) {
  const response = await fetch('/workbench/j100-vision-result.json', { method: 'GET', cache: 'no-store', signal })
  if (!response.ok) throw new Error(`视觉配送成果暂不可读取（HTTP ${response.status}），其他历史成果仍可查看。`)
  return parseVisionResult(await response.json())
}
