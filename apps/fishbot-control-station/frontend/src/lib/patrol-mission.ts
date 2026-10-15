/**
 * 多航点巡逻与任务调度引擎 (Waypoint Patrol Mission Engine)
 * 对标工业级移动机器人与四足机器人（如巡检底盘、四足机器狗）的自主多航点巡航交互标准。
 */

import type { WorldPoint } from './radar-workbench'

export interface PatrolWaypoint {
  id: string
  x: number
  y: number
  yaw: number
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

export class PatrolMissionTracker {
  private waypoints: PatrolWaypoint[] = []
  private config: PatrolMissionConfig
  private currentIndex = 0
  private status: PatrolMissionStatus = 'idle'
  private startTime = 0
  private elapsedSeconds = 0

  constructor(config?: Partial<PatrolMissionConfig>) {
    this.config = {
      loop: false,
      maxDurationSeconds: 1800,
      returnHomeOnComplete: true,
      toleranceMeters: 0.25,
      ...config,
    }
  }

  public getWaypoints(): readonly PatrolWaypoint[] {
    return this.waypoints
  }

  public getStatus(): PatrolMissionStatus {
    return this.status
  }

  public getCurrentIndex(): number {
    return this.currentIndex
  }

  public getCurrentWaypoint(): PatrolWaypoint | null {
    if (this.currentIndex >= 0 && this.currentIndex < this.waypoints.length) {
      return this.waypoints[this.currentIndex]
    }
    return null
  }

  public addWaypoint(point: WorldPoint, yaw = 0, waitTimeSeconds = 0, label?: string): PatrolWaypoint {
    const wp: PatrolWaypoint = {
      id: `wp_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
      x: Number(point.x.toFixed(3)),
      y: Number(point.y.toFixed(3)),
      yaw: Number(yaw.toFixed(3)),
      waitTimeSeconds: Math.max(0, waitTimeSeconds),
      label: label ?? `航点 ${this.waypoints.length + 1}`,
    }
    this.waypoints.push(wp)
    return wp
  }

  public removeWaypoint(id: string): boolean {
    const idx = this.waypoints.findIndex((w) => w.id === id)
    if (idx === -1) return false
    this.waypoints.splice(idx, 1)
    if (this.currentIndex >= this.waypoints.length) {
      this.currentIndex = Math.max(0, this.waypoints.length - 1)
    }
    return true
  }

  public clear(): void {
    this.waypoints = []
    this.currentIndex = 0
    this.status = 'idle'
    this.startTime = 0
    this.elapsedSeconds = 0
  }

  public getElapsedSeconds(): number {
    if (this.status === 'running' && this.startTime > 0) {
      return this.elapsedSeconds + (Date.now() - this.startTime) / 1000
    }
    return this.elapsedSeconds
  }

  public calculateTotalDistance(): number {
    if (this.waypoints.length < 2) return 0
    let total = 0
    for (let i = 1; i < this.waypoints.length; i++) {
      const prev = this.waypoints[i - 1]
      const curr = this.waypoints[i]
      total += Math.hypot(curr.x - prev.x, curr.y - prev.y)
    }
    if (this.config.loop && this.waypoints.length > 2) {
      const last = this.waypoints[this.waypoints.length - 1]
      const first = this.waypoints[0]
      total += Math.hypot(first.x - last.x, first.y - last.y)
    }
    return Math.round(total * 1000) / 1000
  }

  public start(): boolean {
    if (this.waypoints.length === 0) return false
    this.status = 'running'
    this.currentIndex = 0
    this.startTime = Date.now()
    this.elapsedSeconds = 0
    return true
  }

  public pause(): void {
    if (this.status === 'running') {
      this.status = 'paused'
      if (this.startTime > 0) {
        this.elapsedSeconds += (Date.now() - this.startTime) / 1000
        this.startTime = 0
      }
    }
  }

  public resume(): void {
    if (this.status === 'paused') {
      this.status = 'running'
      this.startTime = Date.now()
    }
  }

  public abort(): void {
    if (this.status === 'running' && this.startTime > 0) {
      this.elapsedSeconds += (Date.now() - this.startTime) / 1000
      this.startTime = 0
    }
    this.status = 'aborted'
  }

  public advance(robotPose: WorldPoint): 'reached' | 'advancing' | 'finished' {
    if (this.status !== 'running' || this.waypoints.length === 0) return 'finished'

    const target = this.waypoints[this.currentIndex]
    const distance = Math.hypot(target.x - robotPose.x, target.y - robotPose.y)

    if (distance <= this.config.toleranceMeters) {
      if (this.currentIndex < this.waypoints.length - 1) {
        this.currentIndex++
        return 'advancing'
      } else if (this.config.loop) {
        this.currentIndex = 0
        return 'advancing'
      } else {
        this.status = 'completed'
        return 'finished'
      }
    }

    return 'reached'
  }

  public toNav2GoalPayload(): { poses: Array<{ x: number; y: number; yaw: number }> } {
    return {
      poses: this.waypoints.map((w) => ({ x: w.x, y: w.y, yaw: w.yaw })),
    }
  }
}
