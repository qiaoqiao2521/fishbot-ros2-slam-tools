export type Point = { x: number; y: number }
export type Pose = Point & { yaw: number }
export type SimulationMap = {
  width: number
  height: number
  resolution: number
  origin: [number, number, number]
  data: number[]
}
export type MissionStatus = 'idle' | 'running' | 'canceling' | 'canceled' | 'succeeded' | 'failed'
export type SimulationState = {
  mode: 'mujoco'
  domain: 93
  ready: boolean
  reason: string
  pose: Pose | null
  truth: (Pose & { linear_speed: number; angular_speed: number }) | null
  path: Point[]
  mission: {
    id: string
    status: MissionStatus
    current_index: number
    waypoints: Pose[]
    return_home: boolean
    message: string
  }
  obstacle: { state: string; x: number | null; y: number | null; size: number }
  home: Pose
}

export const MAX_WAYPOINTS = 12
export const DEMO_WAYPOINTS: Pose[] = [
  { x: 2, y: 1, yaw: 0 },
  { x: 2, y: 2, yaw: Math.PI },
  { x: -0.5, y: 2, yaw: -Math.PI / 2 },
]

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
  if (!value || !Number.isInteger(value.width) || !Number.isInteger(value.height) || value.width < 1 || value.height < 1
    || value.width > 4096 || value.height > 4096
    || !Number.isFinite(value.resolution) || value.resolution <= 0 || !Array.isArray(value.origin)
    || value.origin.length !== 3 || !value.origin.every(Number.isFinite) || !Array.isArray(value.data)
    || value.data.length !== value.width * value.height || !value.data.every((cell) => Number.isInteger(cell) && cell >= -1 && cell <= 100)) {
    throw new Error('地图数据不完整，等待仿真重新发布地图。')
  }
  return value
}

export function validateSimulationState(value: SimulationState): SimulationState {
  if (!value || value.mode !== 'mujoco' || value.domain !== 93 || typeof value.ready !== 'boolean' || !value.mission
    || !['idle', 'running', 'canceling', 'canceled', 'succeeded', 'failed'].includes(value.mission.status)
    || !Number.isInteger(value.mission.current_index) || value.mission.current_index < 0
    || !Array.isArray(value.mission.waypoints) || !value.mission.waypoints.every(finitePose)
    || !Array.isArray(value.path) || !value.path.every(finitePoint) || !finitePose(value.home)
    || (value.pose !== null && !finitePose(value.pose)) || (value.truth !== null && (!finitePose(value.truth)
      || !Number.isFinite(value.truth.linear_speed) || !Number.isFinite(value.truth.angular_speed)))
    || !value.obstacle || !((value.obstacle.x === null && value.obstacle.y === null)
      || (Number.isFinite(value.obstacle.x) && Number.isFinite(value.obstacle.y)))
    || !Number.isFinite(value.obstacle.size) || value.obstacle.size <= 0) {
    throw new Error('收到的状态不是当前 MuJoCo 仿真，请检查仿真服务。')
  }
  return value
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

export function missionLabel(status?: MissionStatus): string {
  return status ? {
    idle: '尚未派发', running: '正在巡逻', canceling: '正在取消', canceled: '已取消',
    succeeded: '巡逻完成', failed: '任务失败',
  }[status] : '等待连接'
}

export async function requestSimulation<T>(path: string, body?: object, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/sim-api/${path}`, {
    method: body ? 'POST' : 'GET',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal,
  })
  let value: unknown
  try {
    value = await response.json()
  } catch {
    throw new Error('仿真服务没有返回有效数据，请检查启动窗口。')
  }
  if (!response.ok) {
    const error = value && typeof value === 'object' && 'error' in value ? String(value.error) : `仿真请求失败（${response.status}）`
    throw new Error(error)
  }
  return value as T
}
