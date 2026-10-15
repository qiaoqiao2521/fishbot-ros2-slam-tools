/** Route drafts and local progress rehearsal. Native ROS results remain authoritative. */
import type { WorldPoint } from './radar-workbench'

export type PatrolPose = WorldPoint & { yaw: number }
export interface PatrolWaypoint extends PatrolPose {
  id: string
  waitTimeSeconds: number
  label?: string
}
export interface PatrolMissionConfig {
  loop: boolean
  maxDurationSeconds: number
  returnHomeOnComplete: boolean
  toleranceMeters: number
}
export type PatrolMissionStatus = 'idle' | 'running' | 'paused' | 'completed' | 'aborted'
export type PatrolAdvance = 'approaching' | 'waiting' | 'advancing' | 'returning_home' | 'finished' | 'inactive' | 'timed_out'
export type RosStamp = { sec: number; nanosec: number }
export type FollowWaypointsGoal = {
  number_of_loops: number
  goal_index: number
  poses: Array<{
    header: { frame_id: 'map'; stamp: RosStamp }
    pose: { position: { x: number; y: number; z: number }; orientation: { x: number; y: number; z: number; w: number } }
  }>
}
export type MissionPayload = {
  waypoints: PatrolPose[]
  return_home: boolean
  issued_at: number
  map_id: string
  rules_revision: number
  timeout_s: number
}
const MAX_WAYPOINTS = 12
const MAX_ADDITIONAL_LOOPS = 100

function finite(value: number, label: string): number {
  if (!Number.isFinite(value)) throw new Error(`${label} 必须是有限数值。`)
  return value
}
function validatePose(pose: PatrolPose): PatrolPose {
  return { x: finite(pose.x, 'x'), y: finite(pose.y, 'y'), yaw: finite(pose.yaw, 'yaw') }
}
function distance(a: WorldPoint, b: WorldPoint): number { return Math.hypot(a.x - b.x, a.y - b.y) }
function polylineDistance(points: readonly WorldPoint[], closed: boolean): number {
  if (!Array.isArray(points) || typeof closed !== 'boolean') throw new Error('路线必须是点数组，闭合开关必须为布尔值。')
  for (const point of points) {
    if (!point || typeof point !== 'object') throw new Error('路线点无效。')
    finite(point.x, '路线 x'); finite(point.y, '路线 y')
  }
  let total = 0
  for (let i = 1; i < points.length; i++) total += distance(points[i - 1], points[i])
  if (closed && points.length > 1) total += distance(points[points.length - 1], points[0])
  return finite(total, '路线长度')
}
/** Read-only observation metric; accepted owner routes may include an extra return point. */
export function calculatePolylineDistance(points: readonly WorldPoint[], closed = false): number {
  return Number(polylineDistance(points, closed).toFixed(3))
}

export class PatrolMissionTracker {
  /** This state never represents a native action result or a physical task verdict. */
  public readonly mode = 'draft_preview' as const
  private waypoints: PatrolWaypoint[] = []
  private readonly config: PatrolMissionConfig
  private targets: PatrolWaypoint[] = []
  private homePose: PatrolPose | null = null
  private currentIndex = 0
  private status: PatrolMissionStatus = 'idle'
  private lastClockMs: number | null = null
  private elapsedSeconds = 0
  private dwellStartedAt: number | null = null
  private stopReason: 'duration_exceeded' | 'aborted' | null = null
  private readonly nowMs: () => number

  /** nowMs is monotonic. Rehearsal elapsed time excludes explicitly paused intervals. */
  constructor(config?: Partial<PatrolMissionConfig>, nowMs: () => number = () => performance.now()) {
    this.nowMs = nowMs
    this.config = { loop: false, maxDurationSeconds: 360, returnHomeOnComplete: true, toleranceMeters: 0.25, ...config }
    if (typeof this.config.loop !== 'boolean' || typeof this.config.returnHomeOnComplete !== 'boolean') throw new Error('巡逻开关必须为布尔值。')
    if (finite(this.config.maxDurationSeconds, '最大时长') < 0.5) throw new Error('最大时长至少为 0.5 秒。')
    if (finite(this.config.toleranceMeters, '位置容差') <= 0) throw new Error('位置容差必须大于零。')
  }

  private syncClock(): void {
    if (this.status !== 'running') return
    const now = Math.max(finite(this.nowMs(), '演练时钟'), this.lastClockMs ?? -Infinity)
    if (this.lastClockMs !== null) this.elapsedSeconds += (now - this.lastClockMs) / 1000
    this.lastClockMs = now
    if (this.elapsedSeconds >= this.config.maxDurationSeconds) {
      this.elapsedSeconds = this.config.maxDurationSeconds
      this.status = 'aborted'
      this.stopReason = 'duration_exceeded'
      this.lastClockMs = null
    }
  }

  private requireEditable(): void {
    this.syncClock()
    if (this.status === 'running' || this.status === 'paused') throw new Error('请先结束演练，再编辑路线。')
  }
  private requireRoute(): void {
    if (!this.waypoints.length) throw new Error('路线至少需要一个航点。')
  }
  private requireNoWait(): void {
    if (this.waypoints.some((point) => point.waitTimeSeconds !== 0)) {
      throw new Error('当前原生动作与任务接口不支持逐航点停留；请将停留时间设为零。')
    }
  }
  private invalidateRehearsal(): void {
    this.targets = []; this.homePose = null; this.currentIndex = 0
    this.status = 'idle'; this.lastClockMs = null; this.elapsedSeconds = 0
    this.dwellStartedAt = null; this.stopReason = null
  }

  public getWaypoints(): readonly PatrolWaypoint[] { return this.waypoints.map((point) => ({ ...point })) }
  public getStatus(): PatrolMissionStatus { this.syncClock(); return this.status }
  public getStopReason(): 'duration_exceeded' | 'aborted' | null { this.syncClock(); return this.stopReason }
  public getCurrentIndex(): number { return this.currentIndex }
  public getPhase(): 'waypoints' | 'returning_home' | 'finished' {
    this.syncClock()
    if (this.status === 'completed' || this.status === 'aborted') return 'finished'
    return this.currentIndex >= this.waypoints.length && this.homePose ? 'returning_home' : 'waypoints'
  }
  public getCurrentWaypoint(): PatrolWaypoint | null {
    this.syncClock()
    if (this.status === 'completed' || this.status === 'aborted') return null
    const point = (this.status === 'idle' ? this.waypoints : this.targets)[this.currentIndex]
    return point ? { ...point } : null
  }

  public addWaypoint(point: WorldPoint, yaw = 0, waitTimeSeconds = 0, label?: string): PatrolWaypoint {
    this.requireEditable()
    if (this.waypoints.length >= MAX_WAYPOINTS) throw new Error('路线最多支持 12 个航点。')
    const pose = validatePose({ ...point, yaw })
    if (finite(waitTimeSeconds, '停留时间') < 0) throw new Error('停留时间不能为负数。')
    const waypoint: PatrolWaypoint = {
      id: `wp_${crypto.randomUUID()}`, x: pose.x, y: pose.y,
      yaw: Math.atan2(Math.sin(pose.yaw), Math.cos(pose.yaw)), waitTimeSeconds,
      label: label ?? `航点 ${this.waypoints.length + 1}`,
    }
    this.waypoints.push(waypoint)
    this.invalidateRehearsal()
    return { ...waypoint }
  }
  public removeWaypoint(id: string): boolean {
    this.requireEditable()
    const index = this.waypoints.findIndex((point) => point.id === id)
    if (index === -1) return false
    this.waypoints.splice(index, 1)
    this.invalidateRehearsal()
    return true
  }
  public clear(): void {
    this.requireEditable()
    this.waypoints = []
    this.invalidateRehearsal()
  }
  public getElapsedSeconds(): number { this.syncClock(); return this.elapsedSeconds }

  /** Straight-line draft estimate, not a Nav2 path length. Without a start pose, only waypoint legs are known. */
  public calculateTotalDistance(startPose?: PatrolPose): number {
    if (!this.waypoints.length) return 0
    const home = startPose ? validatePose(startPose) : this.homePose
    const first = this.waypoints[0], last = this.waypoints[this.waypoints.length - 1]
    let total = polylineDistance(this.waypoints, this.config.loop) + (home ? distance(home, first) : 0)
    if (this.config.returnHomeOnComplete && home && !this.config.loop) total += distance(last, home)
    return Number(finite(total, '路线长度').toFixed(3))
  }

  public start(homePose?: PatrolPose): boolean {
    this.syncClock()
    if (!this.waypoints.length || this.status === 'running' || this.status === 'paused') return false
    if (this.config.returnHomeOnComplete && !homePose) throw new Error('返航演练需要显式提供本次出发位姿。')
    const home = homePose ? validatePose(homePose) : null
    const now = finite(this.nowMs(), '演练时钟')
    this.homePose = home
    this.targets = this.waypoints.map((point) => ({ ...point }))
    if (this.config.returnHomeOnComplete && home && !this.config.loop) {
      this.targets.push({ ...home, id: 'preview_return_home', waitTimeSeconds: 0, label: '本次出发点（演练）' })
    }
    this.currentIndex = 0; this.status = 'running'; this.lastClockMs = now
    this.elapsedSeconds = 0; this.dwellStartedAt = null; this.stopReason = null
    return true
  }
  public pause(): void {
    this.syncClock()
    if (this.status === 'running') { this.status = 'paused'; this.lastClockMs = null }
  }
  public resume(): void {
    if (this.status === 'paused') { this.lastClockMs = finite(this.nowMs(), '演练时钟'); this.status = 'running' }
  }
  public abort(): void {
    this.syncClock()
    if (this.status === 'completed' || this.status === 'aborted') return
    this.status = 'aborted'; this.stopReason = 'aborted'; this.lastClockMs = null
  }
  public advance(robotPose: WorldPoint): PatrolAdvance {
    finite(robotPose.x, '机器人 x'); finite(robotPose.y, '机器人 y')
    this.syncClock()
    if (this.stopReason === 'duration_exceeded') return 'timed_out'
    if (this.status === 'completed') return 'finished'
    if (this.status !== 'running') return 'inactive'
    const target = this.targets[this.currentIndex]
    if (distance(target, robotPose) > this.config.toleranceMeters) { this.dwellStartedAt = null; return 'approaching' }
    this.dwellStartedAt ??= this.elapsedSeconds
    if (this.elapsedSeconds - this.dwellStartedAt < target.waitTimeSeconds) return 'waiting'
    this.dwellStartedAt = null
    if (this.currentIndex < this.targets.length - 1) {
      this.currentIndex++
      return this.currentIndex >= this.waypoints.length && this.homePose ? 'returning_home' : 'advancing'
    }
    if (this.config.loop) { this.currentIndex = 0; return 'advancing' }
    this.status = 'completed'; this.lastClockMs = null
    return 'finished'
  }

  /** ROS message shape only. This does not send an action or implement an owner deadline. */
  public toNav2GoalPayload(options: { stamp?: RosStamp; additionalLoops?: number } = {}): FollowWaypointsGoal {
    this.requireRoute(); this.requireNoWait()
    const stamp = { ...(options.stamp ?? { sec: 0, nanosec: 0 }) }
    if (!Number.isInteger(stamp.sec) || stamp.sec < -2147483648 || stamp.sec > 2147483647
      || !Number.isInteger(stamp.nanosec) || stamp.nanosec < 0 || stamp.nanosec >= 1e9) throw new Error('ROS 时间戳无效。')
    const loops = options.additionalLoops ?? 0
    if (this.config.loop && (!Number.isInteger(options.additionalLoops) || loops < 1 || loops > MAX_ADDITIONAL_LOOPS)) {
      throw new Error('循环导出必须明确指定 1–100 次额外循环。')
    }
    if (!this.config.loop && loops !== 0) throw new Error('非循环路线不能指定额外循环。')
    if (this.config.loop && this.config.returnHomeOnComplete) throw new Error('原生循环导出不能同时附加一次性返航；请使用单次路线。')
    const poses: PatrolPose[] = this.waypoints.map(({ x, y, yaw }) => ({ x, y, yaw }))
    if (this.config.returnHomeOnComplete) {
      if (!this.homePose) throw new Error('原生返航导出需要先捕获本次出发位姿。')
      poses.push({ ...this.homePose })
    }
    return { number_of_loops: loops, goal_index: 0, poses: poses.map((point) => ({
      header: { frame_id: 'map', stamp: { ...stamp } },
      pose: { position: { x: point.x, y: point.y, z: 0 }, orientation: { x: 0, y: 0, z: Math.sin(point.yaw / 2), w: Math.cos(point.yaw / 2) } },
    })) }
  }

  /** Existing HTTP owner captures its own fresh start pose and native terminal result. */
  public toMissionPayload(options: { issuedAt: number; mapId: string; rulesRevision: number }): MissionPayload {
    this.requireRoute(); this.requireNoWait()
    if (this.config.loop) throw new Error('当前任务接口不支持循环路线。')
    if (this.config.maxDurationSeconds > 360) throw new Error('当前任务接口的最大时长不能超过 360 秒。')
    if (finite(options.issuedAt, '派发时间') < 0) throw new Error('派发时间不能为负数。')
    if (typeof options.mapId !== 'string' || !options.mapId.trim()) throw new Error('派发需要当前地图标识。')
    if (!Number.isSafeInteger(options.rulesRevision) || options.rulesRevision < 0) throw new Error('派发需要有效的规则版本。')
    return { waypoints: this.waypoints.map(({ x, y, yaw }) => ({ x, y, yaw })), return_home: this.config.returnHomeOnComplete,
      issued_at: options.issuedAt, map_id: options.mapId, rules_revision: options.rulesRevision, timeout_s: this.config.maxDurationSeconds }
  }
}
