/** Same-source received lidar observations and display-only collision box truth. */
const record = (v: unknown): Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {}
const list = (v: unknown): unknown[] => Array.isArray(v) ? v : []
const text = (v: unknown, fallback = '') => typeof v === 'string' && v.trim() ? v : fallback
const numeric = (v: unknown): number | null => typeof v === 'number' && Number.isFinite(v) ? v : null
const strings = (v: unknown) => list(v).filter((item): item is string => typeof item === 'string')
const decimal = (v: unknown): string => typeof v === 'string' && /^\d+$/.test(v) ? v : typeof v === 'number' && Number.isSafeInteger(v) ? String(v) : ''
const names = ['scene_sha256', 'manifest_sha256', 'episode_id', 'sequence'] as const
export type SensorIdentity = Record<typeof names[number], string>
function identity(v: unknown): SensorIdentity {
  const raw = record(v)
  return { scene_sha256: text(raw.scene_sha256), manifest_sha256: text(raw.manifest_sha256), episode_id: text(raw.episode_id), sequence: typeof raw.sequence === 'number' ? String(raw.sequence) : text(raw.sequence) }
}
function vectors(v: unknown): [number, number, number][] {
  return list(v).flatMap(value => { const row = list(value).map(numeric); return row.length === 3 && row.every(x => x !== null) ? [row as [number, number, number]] : [] })
}
export function sensorFrameAsset(value: unknown, reportUrl: string): string | null {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_./-]+$/.test(value) || value.includes('..')) return null
  const url = new URL(value, new URL(reportUrl, 'https://sensor-assets.invalid'))
  return url.origin === 'https://sensor-assets.invalid' && url.pathname.startsWith('/workbench/') ? url.pathname : null
}
export interface SensorFrameReference { url: string | null; identity: SensorIdentity; source: number | null; validPoints: number | null }
export interface SensorExperience {
  runId: string; status: string; frameId: string; sensor: Record<string, unknown>; frames: SensorFrameReference[]
  subscribers: { node: string; type: string }[]; counts: Record<string, number | null>; tf: Record<string, number | null>
  confirmedReadOnly: boolean; truthToControl: boolean | null; warnings: string[]
}
export interface SensorFrame {
  identity: SensorIdentity; source: number | null; sourceNs: string; frameId: string; observedTopic: string; observedSource: string
  points: [number, number, number][]; validPoints: number | null; width: number | null; height: number | null
  truth: { boxes: { id: string; vertices: [number, number, number][] }[]; frameId: string; scope: string; omitted: number | null; referenceOnly: boolean }
  actualTf: { source: string; target: string; sourceNs: string; translation: [number, number, number][]; quaternion: number[] } | null
  truthToControl: boolean | null; warnings: string[]
}
export function parseSensorExperience(value: unknown, sourceUrl: string): SensorExperience {
  const raw = record(value), warnings = [...strings(raw.warnings)], counts = record(raw.message_counts), tf = record(raw.tf)
  const confirmedReadOnly = raw.schema === 'fishbot.sensor-experience.v1' && raw.read_only === true && raw.new_execution === false && raw.rescored === false
  if (!confirmedReadOnly) warnings.push('采集版本或只读边界未确认，不把页面显示当作任务验收。')
  return { runId: text(raw.run_id), status: text(raw.status, '未提供'), frameId: text(raw.frame_id), sensor: record(raw.sensor),
    frames: list(raw.frames).map(v => { const row = record(v); return { url: sensorFrameAsset(row.url, sourceUrl), identity: identity(row.identity), source: numeric(row.source_s), validPoints: numeric(row.valid_points) } }),
    subscribers: list(raw.actual_subscribers).map(v => { const row = record(v); return { node: text(row.node, '节点未提供'), type: text(row.type, '类型未提供') } }),
    counts: Object.fromEntries(Object.entries(counts).map(([k, v]) => [k, numeric(v)])), tf: Object.fromEntries(Object.entries(tf).map(([k, v]) => [k, numeric(v)])),
    confirmedReadOnly, truthToControl: typeof raw.truth_to_control === 'boolean' ? raw.truth_to_control : null, warnings }
}
export function parseSensorFrame(value: unknown): SensorFrame {
  const raw = record(value), observed = record(raw.observed), truth = record(raw.truth), actual = record(raw.actual_tf), warnings: string[] = []
  const points = vectors(observed.points), sourceNs = decimal(raw.source_stamp_ns)
  if (points.length !== list(observed.points).length) warnings.push('部分非有限点未绘制，未补点。')
  if (!sourceNs) warnings.push('精确源纳秒整数未提供或超出安全数值范围；本页不推断匹配。')
  return { identity: identity(raw.identity), source: numeric(raw.source_s), sourceNs, frameId: text(raw.frame_id), observedTopic: text(observed.topic), observedSource: text(observed.source), points,
    validPoints: numeric(observed.valid_points), width: numeric(observed.width), height: numeric(observed.height),
    truth: { boxes: list(truth.boxes).flatMap(v => { const row = record(v), vertices = vectors(row.vertices); return vertices.length === 8 ? [{ id: text(row.id, '未命名BOX'), vertices }] : [] }), frameId: text(truth.frame_id), scope: text(truth.scope), omitted: numeric(truth.omitted_nonbox_collision_geometries), referenceOnly: truth.reference_only === true },
    actualTf: Object.keys(actual).length ? { source: text(actual.source_frame), target: text(actual.target_frame), sourceNs: decimal(actual.source_stamp_ns), translation: vectors([actual.translation_m]), quaternion: list(actual.quaternion_xyzw).flatMap(v => numeric(v) === null ? [] : [v as number]) } : null,
    truthToControl: typeof raw.truth_to_control === 'boolean' ? raw.truth_to_control : null, warnings }
}
export function sameSensorIdentity(a: SensorIdentity, b: SensorIdentity) { return names.every(name => Boolean(a[name]) && a[name] === b[name]) }
/** Preserve source nanoseconds as decimal text before JavaScript numeric rounding. */
export function decodeSensorFrame(text: string): SensorFrame { return parseSensorFrame(JSON.parse(text.replace(/("source_stamp_ns"\s*:\s*)(\d+)/g, '$1"$2"'))) }
export function angularPoint(point: [number, number, number]): [number, number] | null {
  if (Math.hypot(...point) === 0) return null
  return [(Math.atan2(point[1], point[0]) + Math.PI) / (2 * Math.PI) * 720, (Math.PI / 2 - Math.atan2(point[2], Math.hypot(point[0], point[1]))) / Math.PI * 320]
}
export function boxAngularEdges(vertices: [number, number, number][]) {
  const edges: { from: [number, number]; to: [number, number] }[] = []; let wrapped = 0
  for (let i = 0; i < vertices.length; i++) for (const bit of [1, 2, 4]) {
    const j = i ^ bit
    if (i >= j || j >= vertices.length) continue
    const from = angularPoint(vertices[i]), to = angularPoint(vertices[j])
    if (!from || !to) continue
    if (Math.abs(from[0] - to[0]) > 360) { wrapped++; continue }
    edges.push({ from, to })
  }
  return { edges, wrapped }
}
export async function readSensorExperience(url: string, signal?: AbortSignal) {
  const response = await fetch(url, { method: 'GET', cache: 'no-store', signal })
  if (!response.ok) throw new Error(`传感器对比目录不可读取（HTTP ${response.status}），其他成果保留。`)
  return parseSensorExperience(await response.json(), url)
}
export async function readSensorFrame(url: string, signal?: AbortSignal) {
  const response = await fetch(url, { method: 'GET', cache: 'no-store', signal })
  if (!response.ok) throw new Error(`该帧不可读取（HTTP ${response.status}），不使用其他时刻替代。`)
  return decodeSensorFrame(await response.text())
}
