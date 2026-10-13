import { MAX_WAYPOINTS, type MissionDispatchState, type Point, type Pose, type SimulationMap } from '@/lib/simulation'

export const MAX_MAP_ZONES = 64

export type MapEditMode = 'waypoint' | 'wall' | 'no_go' | 'observe'
export type MapZone = { id: string; kind: 'wall' | 'no_go'; points: Point[]; width?: number }
export type MapRules = {
  map_id: string
  revision: number
  zones: MapZone[]
  apply_state: 'unavailable' | 'published' | 'applied'
  message: string
}
export type SavedRoute = {
  id: string; name: string; map_id: string; revision: number
  waypoints: Pose[]; return_home: boolean
}
export type RouteCollection = { map_id: string; routes: SavedRoute[] }
export type MissionRun = {
  id: string; status: string; dispatch_state?: MissionDispatchState | null; map_id?: string; rules_revision?: number
  message?: string; stop_reason?: string | null; waypoints?: Pose[]
  started_at?: number; finished_at?: number | null
}
export type RunCollection = { runs: MissionRun[] }
export type RulesEditor = {
  mapId: string | null
  saved: MapRules | null
  baseRevision: number | null
  zones: MapZone[]
  history: MapZone[][]
  anchor: Point | null
  writeState: 'idle' | 'saving' | 'unknown' | 'rejected'
  error: string | null
  attempted: { baseRevision: number; zones: MapZone[] } | null
}

export const emptyRulesEditor = (): RulesEditor => ({
  mapId: null, saved: null, baseRevision: null, zones: [], history: [], anchor: null,
  writeState: 'idle', error: null, attempted: null,
})
const pointValid = (point: Point): boolean => !!point && Number.isFinite(point.x) && Number.isFinite(point.y)
const poseValid = (pose: Pose): boolean => pointValid(pose) && Number.isFinite(pose.yaw)
const cloneZones = (zones: MapZone[]) => zones.map((zone) => ({ ...zone, points: zone.points.map((point) => ({ ...point })) }))
export const zonesEqual = (left: MapZone[], right: MapZone[]): boolean => left.length === right.length
  && left.every((zone, index) => {
    const other = right[index]
    return zone.id === other.id && zone.kind === other.kind && (zone.width ?? 0.02) === (other.width ?? 0.02)
      && zone.points.length === other.points.length && zone.points.every((point, i) => point.x === other.points[i].x && point.y === other.points[i].y)
  })
export const rulesDirty = (editor: RulesEditor): boolean => !!editor.anchor || !zonesEqual(editor.zones, editor.saved?.zones ?? [])

export function validateMapRules(value: MapRules, mapId?: string): MapRules {
  if (!value || typeof value.map_id !== 'string' || !value.map_id || (mapId && value.map_id !== mapId)
    || !Number.isInteger(value.revision) || value.revision < 0 || !Array.isArray(value.zones)
    || value.zones.length > MAX_MAP_ZONES || !['unavailable', 'published', 'applied'].includes(value.apply_state)
    || typeof value.message !== 'string' || !value.zones.every((zone) => !!zone
      && typeof zone.id === 'string' && !!zone.id && ['wall', 'no_go'].includes(zone.kind)
      && Array.isArray(zone.points) && zone.points.length === (zone.kind === 'wall' ? 2 : 4)
      && zone.points.every(pointValid) && (zone.width === undefined || (Number.isFinite(zone.width) && zone.width > 0)))
    || new Set(value.zones.map((zone) => zone.id)).size !== value.zones.length) {
    throw new Error('地图规则无效或已属于另一张地图，请重新读取。')
  }
  return value
}

export function validateRoutes(value: RouteCollection, mapId?: string): RouteCollection {
  if (!value || typeof value.map_id !== 'string' || !value.map_id || (mapId && value.map_id !== mapId)
    || !Array.isArray(value.routes) || !value.routes.every((route) => !!route
      && typeof route.id === 'string' && !!route.id && typeof route.name === 'string' && !!route.name
      && route.map_id === value.map_id && Number.isInteger(route.revision) && route.revision >= 0
      && typeof route.return_home === 'boolean' && Array.isArray(route.waypoints)
      && route.waypoints.length > 0 && route.waypoints.length <= MAX_WAYPOINTS && route.waypoints.every(poseValid))) {
    throw new Error('路线数据无效或已属于另一张地图，请重新读取。')
  }
  return value
}

export function validateRuns(value: RunCollection): RunCollection {
  if (!value || !Array.isArray(value.runs) || !value.runs.every((run) => !!run && typeof run.id === 'string'
    && ['running', 'canceling', 'canceled', 'succeeded', 'failed', 'unknown'].includes(run.status) && (run.dispatch_state == null || ['pending', 'accepted', 'rejected', 'unavailable'].includes(run.dispatch_state)) && (run.map_id === undefined || typeof run.map_id === 'string')
    && (run.rules_revision === undefined || Number.isInteger(run.rules_revision))
    && (run.message === undefined || typeof run.message === 'string')
    && (run.stop_reason == null || typeof run.stop_reason === 'string'))) {
    throw new Error('任务记录格式无效，请重新读取。')
  }
  return value
}

/** Stable even though /map polling returns a new object each time. */
export function mapGeneration(map: SimulationMap | null): string | null {
  if (!map) return null
  if (map.map_id) return map.map_id
  let hash = 2166136261
  for (const value of map.data) hash = Math.imul(hash ^ (value + 1), 16777619) >>> 0
  return `${map.width}:${map.height}:${map.resolution}:${map.origin.join(',')}:${hash.toString(16)}`
}

export function rectanglePoints(first: Point, second: Point): Point[] {
  const minX = Math.min(first.x, second.x), maxX = Math.max(first.x, second.x)
  const minY = Math.min(first.y, second.y), maxY = Math.max(first.y, second.y)
  return [{ x: minX, y: minY }, { x: maxX, y: minY }, { x: maxX, y: maxY }, { x: minX, y: maxY }]
}

export function zoneFromSelection(kind: 'wall' | 'no_go', first: Point, second: Point, id: string): MapZone {
  if (!pointValid(first) || !pointValid(second) || Math.hypot(first.x - second.x, first.y - second.y) < 0.05) {
    throw new Error('两点太近，请选择至少相隔 5 厘米的位置。')
  }
  if (kind === 'no_go' && (Math.abs(first.x - second.x) < 0.05 || Math.abs(first.y - second.y) < 0.05)) {
    throw new Error('禁区需要有面积，请重新选择两个对角。')
  }
  return { id, kind, points: kind === 'wall' ? [{ ...first }, { ...second }] : rectanglePoints(first, second),
    ...(kind === 'wall' ? { width: 0.02 } : {}) }
}

export type RulesEdit =
  | { type: 'received'; value: MapRules }
  | { type: 'saved'; value: MapRules }
  | { type: 'anchor'; point: Point | null }
  | { type: 'add'; zone: MapZone }
  | { type: 'remove'; id: string }
  | { type: 'undo' }
  | { type: 'restore' }
  | { type: 'saving' }
  | { type: 'unknown'; message: string }
  | { type: 'rejected'; message: string }
  | { type: 'reset' }

export function rulesReducer(editor: RulesEditor, edit: RulesEdit): RulesEditor {
  if (edit.type === 'reset') return emptyRulesEditor()
  if (edit.type === 'received') {
    const value = edit.value
    if (editor.mapId !== value.map_id) return { ...emptyRulesEditor(), mapId: value.map_id, saved: value, baseRevision: value.revision, zones: cloneZones(value.zones) }
    if (editor.saved && value.revision < editor.saved.revision) return editor
    if (editor.writeState === 'unknown') {
      const confirmed = editor.attempted && value.revision > editor.attempted.baseRevision
        && zonesEqual(value.zones, editor.attempted.zones)
      return confirmed ? { ...editor, saved: value, baseRevision: value.revision, zones: cloneZones(value.zones), history: [],
        anchor: null, writeState: 'idle', attempted: null, error: null } : { ...editor, saved: value }
    }
    if (editor.writeState === 'saving') return editor
    const dirty = rulesDirty(editor)
    return { ...editor, saved: value, ...(dirty ? {} : { zones: cloneZones(value.zones), baseRevision: value.revision, history: [], anchor: null }) }
  }
  if (edit.type === 'saved') return { ...editor, saved: edit.value, baseRevision: edit.value.revision, zones: cloneZones(edit.value.zones),
    history: [], anchor: null, writeState: 'idle', attempted: null, error: null }
  if (edit.type === 'rejected') return { ...editor, writeState: 'rejected', error: edit.message, attempted: null }
  if (edit.type === 'unknown') return { ...editor, writeState: 'unknown', error: edit.message }
  if (editor.writeState === 'saving' || editor.writeState === 'unknown') return editor
  if (edit.type === 'anchor') return { ...editor, anchor: edit.point, error: null }
  if (edit.type === 'saving') return editor.saved && !editor.anchor
    ? { ...editor, writeState: 'saving', error: null, attempted: { baseRevision: editor.baseRevision ?? editor.saved.revision, zones: cloneZones(editor.zones) } } : editor
  if (edit.type === 'restore') return { ...editor, zones: cloneZones(editor.saved?.zones ?? []), baseRevision: editor.saved?.revision ?? null, history: [], anchor: null, error: null, writeState: 'idle' }
  if (edit.type === 'undo') {
    if (editor.anchor) return { ...editor, anchor: null }
    const previous = editor.history.at(-1)
    return previous ? { ...editor, zones: cloneZones(previous), history: editor.history.slice(0, -1), error: null, writeState: 'idle' } : editor
  }
  const zones = edit.type === 'add' ? [...editor.zones, edit.zone] : editor.zones.filter((zone) => zone.id !== edit.id)
  return { ...editor, zones, history: [...editor.history.slice(-49), cloneZones(editor.zones)], anchor: null,
    error: null, writeState: 'idle' }
}

export function ruleStartBlock(editor: RulesEditor, available: boolean): string | null {
  if (!available || !editor.saved) return '地图规则尚未读回，暂不能派发。'
  if (editor.writeState === 'saving') return '正在保存规则，请等待回执。'
  if (editor.writeState === 'unknown') return '规则保存结果未知，请读取规则确认，不能重复提交或派发。'
  if (editor.baseRevision !== editor.saved.revision) return '已保存规则被其他编辑更新，请恢复最新规则后重新编辑。'
  if (rulesDirty(editor)) return '有未保存的地图规则，请保存或恢复已保存规则。'
  if (editor.saved.apply_state !== 'applied') return editor.saved.apply_state === 'published'
    ? '规则已发布，等待导航确认。' : '规则尚未应用到导航，请检查服务。'
  return null
}

export function routeDraft(route: SavedRoute, mapId: string): { waypoints: Pose[]; returnHome: boolean } {
  if (route.map_id !== mapId) throw new Error('路线属于另一张地图，不能载入。')
  return { waypoints: route.waypoints.map((point) => ({ ...point })), returnHome: route.return_home }
}
