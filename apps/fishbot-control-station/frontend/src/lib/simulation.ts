import { runtimeFetch, runtimeJson } from '@/lib/runtime-context'

export type Point = { x: number; y: number }
export type Pose = Point & { yaw: number }
export type SimulationMap = {
  map_id?: string
  width: number
  height: number
  resolution: number
  origin: [number, number, number]
  data: number[]
}
export type MissionStatus = 'idle' | 'running' | 'canceling' | 'canceled' | 'succeeded' | 'failed'
export type MissionDispatchState = 'pending' | 'accepted' | 'rejected' | 'unavailable'
export type CollisionMonitorReport = {
  source: '/collision_monitor_state'
  available: boolean
  action: 'unknown' | 'do_nothing' | 'stop' | 'slowdown' | 'approach' | 'limit'
  action_type: number | null
  polygon_name: string | null
  observation_age_s: number | null
}
export type SimulationState = {
  mode: 'mujoco'
  domain: number
  ready: boolean
  reason: string
  pose: Pose | null
  truth: (Pose & { linear_speed: number; angular_speed: number }) | null
  path: Point[]
  mission: {
    id: string | null
    status: MissionStatus
    current_index: number
    waypoints: Pose[]
    return_home: boolean
    message: string
    dispatch_state?: MissionDispatchState | null
    stop_reason?: string | null
    cleanup_state?: 'retrying' | 'unresolved' | null
    start_pose?: Pose | null
  }
  collision_monitor?: CollisionMonitorReport
  obstacle: { state: string; x: number | null; y: number | null; size: number }
  home: Pose | null
}

export const MAX_WAYPOINTS = 12
export function simulationDomain(value = '93'): number {
  if (!/^[0-9]+$/.test(value) || Number(value) < 1 || Number(value) > 232) {
    throw new Error('仿真域必须为 1–232，不能使用实车域 0。')
  }
  return Number(value)
}
export const SIMULATION_DOMAIN = simulationDomain(import.meta.env.VITE_FISHBOT_SIM_DOMAIN)
/** OccupancyGrid rows begin at the lower-left; the SVG begins at the upper-left. */
export function worldToMap(point: Point, map: SimulationMap): Point {
  const dx = point.x - map.origin[0]
  const dy = point.y - map.origin[1]
  const cos = Math.cos(map.origin[2])
  const sin = Math.sin(map.origin[2])
  return {
    x: (cos * dx + sin * dy) / map.resolution,
    y: map.height - (-sin * dx + cos * dy) / map.resolution,
  }
}

export function mapToWorld(point: Point, map: SimulationMap): Point {
  const x = point.x * map.resolution
  const y = (map.height - point.y) * map.resolution
  const cos = Math.cos(map.origin[2])
  const sin = Math.sin(map.origin[2])
  return { x: map.origin[0] + cos * x - sin * y, y: map.origin[1] + sin * x + cos * y }
}

export function isFreeWaypoint(point: Point, map: SimulationMap, clearance = 0.18): boolean {
  const pixel = worldToMap(point, map)
  const cx = Math.floor(pixel.x)
  const cy = Math.floor(map.height - pixel.y)
  const radius = Math.ceil(clearance / map.resolution)
  for (let dy = -radius; dy <= radius; dy += 1) {
    for (let dx = -radius; dx <= radius; dx += 1) {
      if (Math.hypot(dx, dy) > radius) continue
      const x = cx + dx
      const y = cy + dy
      if (x < 0 || y < 0 || x >= map.width || y >= map.height) return false
      const value = map.data[y * map.width + x]
      if (value === undefined || value < 0 || value >= 50) return false
    }
  }
  return true
}

export function validateSimulationMap(value: SimulationMap): SimulationMap {
  if (!value || (value.map_id !== undefined && (typeof value.map_id !== 'string' || !value.map_id)) || !Number.isInteger(value.width) || !Number.isInteger(value.height) || value.width < 1 || value.height < 1
    || value.width > 4096 || value.height > 4096
    || !Number.isFinite(value.resolution) || value.resolution <= 0 || !Array.isArray(value.origin)
    || value.origin.length !== 3 || !value.origin.every(Number.isFinite) || !Array.isArray(value.data)
    || value.data.length !== value.width * value.height || !value.data.every((cell) => Number.isInteger(cell) && cell >= -1 && cell <= 100)) {
    throw new Error('地图数据不完整，等待仿真重新发布地图。')
  }
  return value
}

export function validateSimulationState(value: SimulationState, expectedDomain = SIMULATION_DOMAIN): SimulationState {
  if (!value || value.mode !== 'mujoco' || value.domain !== expectedDomain || !Number.isInteger(value.domain)
    || value.domain < 1 || value.domain > 232 || typeof value.ready !== 'boolean' || !value.mission
    || (value.mission.id !== null && typeof value.mission.id !== 'string')
    || !['idle', 'running', 'canceling', 'canceled', 'succeeded', 'failed'].includes(value.mission.status)
    || (value.mission.dispatch_state != null && !['pending', 'accepted', 'rejected', 'unavailable'].includes(value.mission.dispatch_state))
    || (value.mission.stop_reason != null && typeof value.mission.stop_reason !== 'string')
    || (value.mission.cleanup_state != null && !['retrying', 'unresolved'].includes(value.mission.cleanup_state))
    || (value.mission.start_pose != null && !finitePose(value.mission.start_pose))
    || (value.collision_monitor != null && !validCollisionMonitor(value.collision_monitor))
    || !Number.isInteger(value.mission.current_index) || value.mission.current_index < 0
    || !Array.isArray(value.mission.waypoints) || !value.mission.waypoints.every(finitePose)
    || !Array.isArray(value.path) || !value.path.every(finitePoint) || (value.home !== null && !finitePose(value.home))
    || (value.pose !== null && !finitePose(value.pose)) || (value.truth !== null && (!finitePose(value.truth)
      || !Number.isFinite(value.truth.linear_speed) || !Number.isFinite(value.truth.angular_speed)))
    || !value.obstacle || !((value.obstacle.x === null && value.obstacle.y === null)
      || (Number.isFinite(value.obstacle.x) && Number.isFinite(value.obstacle.y)))
    || !Number.isFinite(value.obstacle.size) || value.obstacle.size <= 0) {
    throw new Error('收到的状态不是当前 MuJoCo 仿真，请检查仿真服务。')
  }
  return value
}

function validCollisionMonitor(value: CollisionMonitorReport): boolean {
  return !!value && value.source === '/collision_monitor_state' && typeof value.available === 'boolean'
    && ['unknown', 'do_nothing', 'stop', 'slowdown', 'approach', 'limit'].includes(value.action)
    && (value.action_type === null || (Number.isInteger(value.action_type) && value.action_type >= 0 && value.action_type <= 4))
    && (value.polygon_name === null || typeof value.polygon_name === 'string')
    && (value.observation_age_s === null || (Number.isFinite(value.observation_age_s) && value.observation_age_s >= 0))
}

export function collisionMonitorText(report?: CollisionMonitorReport): string {
  if (!report?.available || report.action === 'unknown') return '未知：尚无可用的 Collision Monitor 报告。'
  const label = { do_nothing: '放行', stop: '停车', slowdown: '减速', approach: '接近限速', limit: '速度限制' }[report.action]
  const polygon = report.polygon_name === 'invalid source' ? '传感器或坐标变换来源无效' : report.polygon_name || '无触发区域'
  return `${label} · ${polygon}`
}

export function missionCanRetryCancel(mission?: SimulationState['mission']): boolean {
  return mission?.status === 'canceling' && mission.cleanup_state === 'unresolved'
    && mission.dispatch_state !== 'unavailable'
}

function finitePoint(value: Point): boolean {
  return !!value && Number.isFinite(value.x) && Number.isFinite(value.y)
}

function finitePose(value: Pose): boolean {
  return finitePoint(value) && Number.isFinite(value.yaw)
}

export function missionIsActive(state: SimulationState | null): boolean {
  return state?.mission.status === 'running' || state?.mission.status === 'canceling'
}

export function missionLabel(status?: MissionStatus, dispatchState?: MissionDispatchState | null): string {
  if (status === 'running' && dispatchState === 'pending') return '等待 Nav2 确认'
  if (status === 'canceling' && dispatchState === 'unavailable') return '接收状态未知'
  return status ? {
    idle: '尚未派发', running: '正在巡逻', canceling: '正在取消', canceled: '已取消',
    succeeded: '巡逻完成', failed: '任务失败',
  }[status] : '等待连接'
}

export function missionProgressText(mission?: SimulationState['mission']): string {
  if (mission?.status === 'running') {
    if (mission.dispatch_state === 'pending') return '任务已提交，尚未收到 Nav2 接收回执。'
    return mission.return_home && mission.current_index === mission.waypoints.length - 1
      ? '正在返回本次出发点' : `正在前往第 ${mission.current_index + 1} / ${mission.waypoints.length} 个点`
  }
  if (mission?.status === 'succeeded') return `已完成 ${mission.waypoints.length} 个导航点`
  if (mission?.status === 'canceling') {
    if (mission.dispatch_state === 'unavailable') return 'Nav2 接收状态仍未知，原任务保留；当前无法确认取消。'
    return mission.cleanup_state === 'unresolved'
      ? '终态仍未知，原目标保留；可以重试取消。' : '等待 Nav2 取消结果'
  }
  if (mission?.status === 'canceled') return 'Nav2 已确认取消任务。'
  if (mission?.status === 'failed') return '任务未完成，请查看 Nav2 回执。'
  return '选点后派发，小车会依次前往。'
}

export type SimulationGoalIssue = {
  kind: 'map_rule' | 'occupied_cell' | 'unknown_cell' | 'map_boundary'
  target: 'waypoint' | 'return_home'
  waypoint_index: number | null
  point: Pose
  rule_id?: string
  rule_kind?: 'wall' | 'no_go'
  rule_index?: number
  clearance_m?: number
  required_clearance_m?: number
  shortfall_m?: number
  blocking_point?: Point
  map_id?: string
  rules_revision?: number
}

/** Invalid optional diagnostics must not erase an authoritative HTTP rejection. */
export function parseSimulationGoalIssue(value: unknown): SimulationGoalIssue | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const raw = value as Record<string, unknown>
  if (typeof raw.kind !== 'string' || !['map_rule', 'occupied_cell', 'unknown_cell', 'map_boundary'].includes(raw.kind)
    || typeof raw.target !== 'string' || !['waypoint', 'return_home'].includes(raw.target) || !finitePose(raw.point as Pose)
    || (raw.target === 'return_home' ? raw.waypoint_index !== null
      : !Number.isInteger(raw.waypoint_index) || Number(raw.waypoint_index) < 1 || Number(raw.waypoint_index) > MAX_WAYPOINTS)) return null
  if (raw.rule_id !== undefined && (typeof raw.rule_id !== 'string' || !/^[A-Za-z0-9_-]{1,64}$/.test(raw.rule_id))) return null
  if (raw.rule_kind !== undefined && (typeof raw.rule_kind !== 'string' || !['wall', 'no_go'].includes(raw.rule_kind))) return null
  if (raw.rule_index !== undefined && (!Number.isInteger(raw.rule_index) || Number(raw.rule_index) < 1 || Number(raw.rule_index) > 64)) return null
  for (const key of ['clearance_m', 'required_clearance_m', 'shortfall_m']) {
    if (raw[key] !== undefined && (typeof raw[key] !== 'number' || !Number.isFinite(raw[key]) || Number(raw[key]) < 0)) return null
  }
  if (raw.blocking_point !== undefined && !finitePoint(raw.blocking_point as Point)) return null
  if (raw.map_id !== undefined && (typeof raw.map_id !== 'string' || !raw.map_id)) return null
  if (raw.rules_revision !== undefined && (!Number.isSafeInteger(raw.rules_revision) || Number(raw.rules_revision) < 0)) return null
  const point = raw.point as Pose
  const result: SimulationGoalIssue = { kind: raw.kind as SimulationGoalIssue['kind'], target: raw.target as SimulationGoalIssue['target'],
    waypoint_index: raw.waypoint_index as number | null, point: { x: point.x, y: point.y, yaw: point.yaw } }
  for (const key of ['rule_id', 'rule_kind', 'rule_index', 'clearance_m', 'required_clearance_m', 'shortfall_m', 'map_id', 'rules_revision'] as const) {
    if (raw[key] !== undefined) Object.assign(result, { [key]: raw[key] })
  }
  if (raw.blocking_point !== undefined) {
    const point = raw.blocking_point as Point
    result.blocking_point = { x: point.x, y: point.y }
  }
  return result
}

export class SimulationRejectedRequest extends Error {
  readonly status: number
  readonly outcome: 'rejected' | null
  readonly issue: SimulationGoalIssue | null
  constructor(message: string, status: number, outcome: 'rejected' | null = null, issue: SimulationGoalIssue | null = null) {
    super(message); this.status = status; this.outcome = outcome; this.issue = issue; this.name = 'SimulationRejectedRequest'
  }
}

export function simulationRequestRejected(error: unknown): boolean {
  // The bridge uses 4xx only for rejection before dispatch, including its 408 deadline.
  return error instanceof SimulationRejectedRequest && (error.outcome === 'rejected' || (error.status >= 400 && error.status < 500))
}

export type UnknownMissionReceipt = { previousId: string | null; waypoints: Pose[]; returnHome: boolean }
export function missionReceiptResolved(receipt: UnknownMissionReceipt, value: SimulationState): boolean {
  const mission = value.mission
  const returnPoint = mission.start_pose ?? value.home
  return !!mission.id && mission.id !== receipt.previousId && mission.return_home === receipt.returnHome
    && (mission.waypoints.length === receipt.waypoints.length
      || (receipt.returnHome && mission.waypoints.length === receipt.waypoints.length + 1
        && !!returnPoint && posesEquivalent(mission.waypoints.at(-1)!, returnPoint)))
    && receipt.waypoints.every((point, index) => {
      const actual = mission.waypoints[index]
      return posesEquivalent(point, actual)
    })
}

export function posesEquivalent(left: Pose, right: Pose): boolean {
  return Math.abs(left.x - right.x) < 1e-8 && Math.abs(left.y - right.y) < 1e-8
    && Math.abs(Math.atan2(Math.sin(left.yaw - right.yaw), Math.cos(left.yaw - right.yaw))) < 1e-8
}

export async function requestSimulation<T>(path: string, body?: object, signal?: AbortSignal): Promise<T> {
  const response = await runtimeFetch('mission', `/sim-api/${path}`, {
    method: body ? 'POST' : 'GET',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal,
  })
  let value: unknown
  try {
    value = await runtimeJson(response)
  } catch {
    throw new Error('仿真服务没有返回有效数据，请检查启动窗口。')
  }
  if (!response.ok) {
    const error = value && typeof value === 'object' && 'error' in value ? String(value.error) : `仿真请求失败（${response.status}）`
    const outcome = value && typeof value === 'object' && 'outcome' in value && value.outcome === 'rejected' ? 'rejected' : null
    const issue = value && typeof value === 'object' && 'issue' in value ? parseSimulationGoalIssue(value.issue) : null
    throw new SimulationRejectedRequest(error, response.status, outcome, issue)
  }
  return value as T
}
