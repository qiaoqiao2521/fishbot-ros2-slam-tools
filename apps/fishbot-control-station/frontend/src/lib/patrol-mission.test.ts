import { describe, expect, it } from 'vitest'
import { calculatePolylineDistance, PatrolMissionTracker, type PatrolMissionConfig } from './patrol-mission'

function rehearsal(config: Partial<PatrolMissionConfig> = {}) {
  let now = 0
  const tracker = new PatrolMissionTracker({ returnHomeOnComplete: false, ...config }, () => now)
  return { tracker, advanceMs: (milliseconds: number) => { now += milliseconds } }
}
const request = { issuedAt: 1000, mapId: 'map-current', rulesRevision: 3 }

describe('read-only observed route distance', () => {
  it('accepts twelve owned waypoints plus the thirteenth automatic return point', () => {
    const observed = Array.from({ length: 12 }, (_, x) => ({ x, y: 0 }))
    observed.push({ x: 0, y: 0 })
    expect(calculatePolylineDistance(observed)).toBe(22)
    expect(observed).toHaveLength(13)
    const { tracker } = rehearsal()
    observed.slice(0, 12).forEach((point) => tracker.addWaypoint(point))
    expect(() => tracker.addWaypoint(observed[12])).toThrow('12')
  })
  it('includes a two-point closure while empty and stationary routes stay zero', () => {
    expect(calculatePolylineDistance([], true)).toBe(0)
    expect(calculatePolylineDistance([{ x: 3, y: 4 }], true)).toBe(0)
    expect(calculatePolylineDistance([{ x: 0, y: 0 }, { x: 3, y: 4 }], true)).toBe(10)
  })
  it('rejects non-finite observations rather than displaying a false finite metric', () => {
    expect(() => calculatePolylineDistance([{ x: NaN, y: 0 }])).toThrow()
    expect(() => calculatePolylineDistance([{ x: 0, y: Infinity }])).toThrow()
    expect(() => calculatePolylineDistance([{ x: 1e308, y: 0 }, { x: -1e308, y: 0 }])).toThrow()
  })
})

describe('PatrolMissionTracker draft and rehearsal', () => {
  it('identifies preview state separately from native ROS results', () => {
    const tracker = new PatrolMissionTracker()
    expect(tracker.mode).toBe('draft_preview')
    expect(tracker.getStatus()).toBe('idle')
    expect(tracker.getCurrentIndex()).toBe(0)
    expect(tracker.getCurrentWaypoint()).toBeNull()
    expect(tracker.getWaypoints()).toEqual([])
    expect(tracker.start()).toBe(false)
    expect(tracker.advance({ x: 0, y: 0 })).toBe('inactive')
  })
  it('copies the caller configuration', () => {
    const config = { returnHomeOnComplete: false, toleranceMeters: 0.2 }
    const tracker = new PatrolMissionTracker(config)
    config.toleranceMeters = Infinity
    tracker.addWaypoint({ x: 1, y: 0 }); tracker.start()
    expect(tracker.advance({ x: 0.5, y: 0 })).toBe('approaching')
    expect(tracker.toMissionPayload(request).timeout_s).toBe(360)
  })
  it.each([
    { maxDurationSeconds: NaN }, { maxDurationSeconds: Infinity }, { maxDurationSeconds: 0.49 },
    { toleranceMeters: NaN }, { toleranceMeters: Infinity }, { toleranceMeters: 0 }, { toleranceMeters: -1 },
  ])('rejects invalid configuration %j', (config) => {
    expect(() => new PatrolMissionTracker(config)).toThrow()
  })
  it('isolates waypoint input, add result, snapshots and current waypoint from mutation', () => {
    const { tracker } = rehearsal()
    const input = { x: 1, y: 2 }
    const added = tracker.addWaypoint(input, Math.PI / 2, 2, '工位')
    input.x = 90; added.x = 91
    tracker.getWaypoints()[0].x = 92
    tracker.getCurrentWaypoint()!.y = 93
    expect(tracker.getWaypoints()[0]).toMatchObject({ x: 1, y: 2, yaw: Math.PI / 2, waitTimeSeconds: 2, label: '工位' })
    expect(tracker.removeWaypoint('not-present')).toBe(false)
    expect(tracker.removeWaypoint(added.id)).toBe(true)
    expect(tracker.getWaypoints()).toEqual([])
  })
  it.each([
    [{ x: NaN, y: 0 }, 0, 0], [{ x: 0, y: Infinity }, 0, 0], [{ x: 0, y: 0 }, NaN, 0],
    [{ x: 0, y: 0 }, 0, NaN], [{ x: 0, y: 0 }, 0, Infinity], [{ x: 0, y: 0 }, 0, -1],
  ] as const)('rejects invalid waypoint data', (point, yaw, wait) => {
    const { tracker } = rehearsal()
    expect(() => tracker.addWaypoint(point, yaw, wait)).toThrow()
    expect(tracker.getWaypoints()).toHaveLength(0)
  })
  it('enforces twelve user waypoints', () => {
    const { tracker } = rehearsal()
    for (let i = 0; i < 12; i++) tracker.addWaypoint({ x: i, y: 0 })
    expect(() => tracker.addWaypoint({ x: 13, y: 0 })).toThrow('12')
  })
  it('counts two-waypoint loop closure and distinguishes waypoint legs from complete travel', () => {
    const { tracker } = rehearsal({ loop: true })
    tracker.addWaypoint({ x: 0, y: 0 }); tracker.addWaypoint({ x: 3, y: 4 })
    expect(tracker.calculateTotalDistance()).toBe(10)
    const { tracker: linear } = rehearsal({ returnHomeOnComplete: true })
    linear.addWaypoint({ x: 3, y: 0 }); linear.addWaypoint({ x: 3, y: 4 })
    expect(linear.calculateTotalDistance()).toBe(4)
    expect(linear.calculateTotalDistance({ x: 0, y: 0, yaw: 0 })).toBe(12)
  })
  it('freezes elapsed time on completion, starting from a valid zero monotonic clock', () => {
    const { tracker, advanceMs } = rehearsal()
    tracker.addWaypoint({ x: 2, y: 0 }); tracker.start(); advanceMs(2300)
    expect(tracker.advance({ x: 0, y: 0 })).toBe('approaching')
    expect(tracker.advance({ x: 2, y: 0 })).toBe('finished')
    expect(tracker.getStatus()).toBe('completed')
    expect(tracker.getElapsedSeconds()).toBe(2.3)
    advanceMs(100000)
    expect(tracker.getElapsedSeconds()).toBe(2.3)
    expect(tracker.getCurrentWaypoint()).toBeNull()
    tracker.abort()
    expect(tracker.getStatus()).toBe('completed')
  })
  it('requires continuous in-tolerance dwell, resetting it after departure', () => {
    const { tracker, advanceMs } = rehearsal()
    tracker.addWaypoint({ x: 2, y: 0 }, 0, 2); tracker.addWaypoint({ x: 4, y: 0 }); tracker.start()
    expect(tracker.advance({ x: 2, y: 0 })).toBe('waiting')
    advanceMs(1500)
    expect(tracker.advance({ x: 3, y: 0 })).toBe('approaching')
    expect(tracker.advance({ x: 2, y: 0 })).toBe('waiting')
    advanceMs(1999)
    expect(tracker.advance({ x: 2, y: 0 })).toBe('waiting')
    advanceMs(1)
    expect(tracker.advance({ x: 2, y: 0 })).toBe('advancing')
    expect(tracker.getCurrentIndex()).toBe(1)
    expect(tracker.advance({ x: 4, y: 0 })).toBe('finished')
  })
  it('pauses elapsed and dwell time without claiming to pause a ROS task', () => {
    const { tracker, advanceMs } = rehearsal()
    tracker.addWaypoint({ x: 0, y: 0 }, 0, 2); tracker.start(); tracker.advance({ x: 0, y: 0 })
    advanceMs(1000); tracker.pause(); advanceMs(20000)
    expect(tracker.getStatus()).toBe('paused')
    expect(tracker.getElapsedSeconds()).toBe(1)
    expect(tracker.advance({ x: 0, y: 0 })).toBe('inactive')
    tracker.resume(); advanceMs(999)
    expect(tracker.advance({ x: 0, y: 0 })).toBe('waiting')
    advanceMs(1)
    expect(tracker.advance({ x: 0, y: 0 })).toBe('finished')
    expect(tracker.getElapsedSeconds()).toBe(2)
  })
  it('enforces the exact active-duration boundary and freezes the timeout verdict', () => {
    const { tracker, advanceMs } = rehearsal({ maxDurationSeconds: 2 })
    tracker.addWaypoint({ x: 2, y: 0 }); tracker.start(); advanceMs(1999)
    expect(tracker.getStatus()).toBe('running')
    advanceMs(1)
    expect(tracker.advance({ x: 2, y: 0 })).toBe('timed_out')
    expect(tracker.getStatus()).toBe('aborted')
    expect(tracker.getStopReason()).toBe('duration_exceeded')
    expect(tracker.getElapsedSeconds()).toBe(2)
    advanceMs(99999)
    expect(tracker.getElapsedSeconds()).toBe(2)
  })
  it('aborts a rehearsal and rejects edits while running or paused', () => {
    const { tracker, advanceMs } = rehearsal()
    const waypoint = tracker.addWaypoint({ x: 1, y: 0 }); tracker.start(); advanceMs(1000)
    expect(() => tracker.addWaypoint({ x: 2, y: 0 })).toThrow('结束演练')
    expect(() => tracker.removeWaypoint(waypoint.id)).toThrow('结束演练')
    tracker.pause()
    expect(() => tracker.clear()).toThrow('结束演练')
    expect(tracker.start()).toBe(false)
    tracker.abort(); advanceMs(10000)
    expect(tracker.getElapsedSeconds()).toBe(1)
    expect(tracker.getStopReason()).toBe('aborted')
    tracker.clear()
    expect(tracker.getStatus()).toBe('idle')
    expect(tracker.getElapsedSeconds()).toBe(0)
  })
  it('requires and freezes a per-rehearsal return point rather than guessing an origin', () => {
    const { tracker } = rehearsal({ returnHomeOnComplete: true })
    tracker.addWaypoint({ x: 4, y: 2 })
    expect(() => tracker.start()).toThrow('出发位姿')
    const home = { x: 2, y: 2, yaw: Math.PI / 2 }
    tracker.start(home); home.x = 99
    expect(tracker.advance({ x: 4, y: 2 })).toBe('returning_home')
    expect(tracker.getPhase()).toBe('returning_home')
    expect(tracker.getCurrentWaypoint()).toMatchObject({ x: 2, y: 2, yaw: Math.PI / 2 })
    expect(tracker.getStatus()).toBe('running')
    expect(tracker.advance({ x: 2, y: 2 })).toBe('finished')
    tracker.addWaypoint({ x: 5, y: 2 })
    expect(() => tracker.toNav2GoalPayload()).toThrow('捕获')
  })
  it('bounds repeated loop rehearsals with their declared duration', () => {
    const { tracker, advanceMs } = rehearsal({ loop: true, maxDurationSeconds: 5 })
    tracker.addWaypoint({ x: 2, y: 0 }); tracker.addWaypoint({ x: 5, y: 0 }); tracker.start()
    expect(tracker.advance({ x: 2, y: 0 })).toBe('advancing')
    expect(tracker.advance({ x: 5, y: 0 })).toBe('advancing')
    expect(tracker.getCurrentIndex()).toBe(0)
    advanceMs(5000)
    expect(tracker.advance({ x: 2, y: 0 })).toBe('timed_out')
  })
})

describe('PatrolMissionTracker existing HTTP owner adapter', () => {
  it('preserves map/version/source/deadline/return contract without a preview start or guessed home', () => {
    const tracker = new PatrolMissionTracker()
    tracker.addWaypoint({ x: 1.5, y: 2.5 }, Math.PI / 2)
    expect(tracker.toMissionPayload(request)).toEqual({
      waypoints: [{ x: 1.5, y: 2.5, yaw: Math.PI / 2 }], return_home: true,
      issued_at: 1000, map_id: 'map-current', rules_revision: 3, timeout_s: 360,
    })
    const payload = tracker.toMissionPayload(request)
    payload.waypoints[0].x = 99
    expect(tracker.toMissionPayload(request).waypoints[0].x).toBe(1.5)
    expect(tracker.getStatus()).toBe('idle')
  })
  it('rejects loops, dwell and over-limit deadlines instead of silently dropping them', () => {
    for (const config of [{ loop: true }, { maxDurationSeconds: 361 }]) {
      const { tracker } = rehearsal(config)
      tracker.addWaypoint({ x: 1, y: 1 })
      expect(() => tracker.toMissionPayload(request)).toThrow()
    }
    const { tracker } = rehearsal()
    tracker.addWaypoint({ x: 1, y: 1 }, 0, 1)
    expect(() => tracker.toMissionPayload(request)).toThrow('停留')
    expect(tracker.getWaypoints()[0].waitTimeSeconds).toBe(1)
  })
  it.each([
    { ...request, issuedAt: NaN }, { ...request, issuedAt: -1 }, { ...request, mapId: ' ' },
    { ...request, rulesRevision: -1 }, { ...request, rulesRevision: 1.5 }, { ...request, rulesRevision: Infinity },
  ])('rejects invalid dispatch provenance %j', (options) => {
    const { tracker } = rehearsal()
    tracker.addWaypoint({ x: 1, y: 1 })
    expect(() => tracker.toMissionPayload(options)).toThrow()
  })
})

describe('PatrolMissionTracker Jazzy FollowWaypoints message adapter', () => {
  it('exports map-frame PoseStamped messages, unit quaternions and the supplied ROS stamp', () => {
    const { tracker } = rehearsal()
    tracker.addWaypoint({ x: 1.5, y: 2.5 }, Math.PI / 2); tracker.addWaypoint({ x: 4, y: -1.2 }, -Math.PI)
    const stamp = { sec: 17, nanosec: 345000000 }
    const payload = tracker.toNav2GoalPayload({ stamp })
    expect(payload.number_of_loops).toBe(0)
    expect(payload.goal_index).toBe(0)
    expect(payload.poses[0]).toEqual({
      header: { frame_id: 'map', stamp },
      pose: { position: { x: 1.5, y: 2.5, z: 0 }, orientation: { x: 0, y: 0, z: Math.sin(Math.PI / 4), w: Math.cos(Math.PI / 4) } },
    })
    expect(Math.hypot(payload.poses[1].pose.orientation.z, payload.poses[1].pose.orientation.w)).toBeCloseTo(1)
    stamp.sec = 99; payload.poses[0].header.stamp.sec = 100
    expect(payload.poses[1].header.stamp.sec).toBe(17)
    expect(tracker.toNav2GoalPayload().poses[0].header.stamp).toEqual({ sec: 0, nanosec: 0 })
  })
  it('uses only the captured home for native return export', () => {
    const { tracker } = rehearsal({ returnHomeOnComplete: true })
    tracker.addWaypoint({ x: 4, y: 0 })
    expect(() => tracker.toNav2GoalPayload()).toThrow('捕获')
    tracker.start({ x: 2, y: 1, yaw: 0.3 })
    expect(tracker.toNav2GoalPayload().poses[1].pose.position).toEqual({ x: 2, y: 1, z: 0 })
  })
  it('requires finite positive additional cycles and rejects mismatched configuration', () => {
    const { tracker } = rehearsal({ loop: true })
    tracker.addWaypoint({ x: 1, y: 0 }); tracker.addWaypoint({ x: 2, y: 0 })
    expect(() => tracker.toNav2GoalPayload()).toThrow('额外循环')
    for (const additionalLoops of [0, -1, 0.5, Infinity, NaN, 101]) expect(() => tracker.toNav2GoalPayload({ additionalLoops })).toThrow('额外循环')
    expect(tracker.toNav2GoalPayload({ additionalLoops: 2 }).number_of_loops).toBe(2)
    const { tracker: single } = rehearsal()
    single.addWaypoint({ x: 0, y: 0 })
    expect(() => single.toNav2GoalPayload({ additionalLoops: 1 })).toThrow('非循环')
    const { tracker: returnLoop } = rehearsal({ loop: true, returnHomeOnComplete: true })
    returnLoop.addWaypoint({ x: 1, y: 0 })
    expect(() => returnLoop.toNav2GoalPayload({ additionalLoops: 1 })).toThrow('一次性返航')
  })
  it('rejects per-waypoint dwell instead of losing it in a native Goal', () => {
    const { tracker } = rehearsal()
    tracker.addWaypoint({ x: 1, y: 0 }, 0, 0.1)
    expect(() => tracker.toNav2GoalPayload()).toThrow('停留')
  })
  it.each([
    { sec: NaN, nanosec: 0 }, { sec: 1.2, nanosec: 0 }, { sec: 2147483648, nanosec: 0 },
    { sec: 1, nanosec: -1 }, { sec: 1, nanosec: 1e9 }, { sec: 1, nanosec: 0.5 },
  ])('validates native Time wire bounds %j', (stamp) => {
    const { tracker } = rehearsal()
    tracker.addWaypoint({ x: 1, y: 0 })
    expect(() => tracker.toNav2GoalPayload({ stamp })).toThrow('时间戳')
  })
})
