import { describe, expect, it } from 'vitest'

import { PatrolMissionTracker } from './patrol-mission'

describe('PatrolMissionTracker', () => {
  it('initializes with default configuration and idle status', () => {
    const tracker = new PatrolMissionTracker()
    expect(tracker.getStatus()).toBe('idle')
    expect(tracker.getCurrentIndex()).toBe(0)
    expect(tracker.getCurrentWaypoint()).toBeNull()
    expect(tracker.getWaypoints()).toHaveLength(0)
  })

  it('adds and removes waypoints correctly', () => {
    const tracker = new PatrolMissionTracker()
    const wp1 = tracker.addWaypoint({ x: 1.0, y: 2.0 }, 1.57, 5, 'Point A')
    const wp2 = tracker.addWaypoint({ x: 4.0, y: 6.0 }, 0, 0, 'Point B')

    expect(tracker.getWaypoints()).toHaveLength(2)
    expect(wp1.label).toBe('Point A')
    expect(wp1.x).toBe(1.0)
    expect(wp1.y).toBe(2.0)
    expect(wp1.yaw).toBe(1.57)
    expect(wp1.waitTimeSeconds).toBe(5)

    expect(wp2.label).toBe('Point B')
    expect(wp2.x).toBe(4.0)
    expect(wp2.y).toBe(6.0)

    const removed = tracker.removeWaypoint(wp1.id)
    expect(removed).toBe(true)
    expect(tracker.getWaypoints()).toHaveLength(1)
    expect(tracker.getWaypoints()[0].id).toBe(wp2.id)

    const removeNonExistent = tracker.removeWaypoint('non_existent')
    expect(removeNonExistent).toBe(false)
  })

  it('calculates total Euclidean distance for linear and looped routes', () => {
    const tracker = new PatrolMissionTracker({ loop: false })
    // Route: (0,0) -> (3,0) -> (3,4) => 3 + 4 = 7
    tracker.addWaypoint({ x: 0, y: 0 })
    tracker.addWaypoint({ x: 3, y: 0 })
    tracker.addWaypoint({ x: 3, y: 4 })

    expect(tracker.calculateTotalDistance()).toBe(7)

    const loopTracker = new PatrolMissionTracker({ loop: true })
    // (0,0) -> (3,0) -> (3,4) -> (0,0) => 3 + 4 + 5 = 12
    loopTracker.addWaypoint({ x: 0, y: 0 })
    loopTracker.addWaypoint({ x: 3, y: 0 })
    loopTracker.addWaypoint({ x: 3, y: 4 })

    expect(loopTracker.calculateTotalDistance()).toBe(12)
  })

  it('manages mission lifecycle: start, pause, resume, abort', () => {
    const tracker = new PatrolMissionTracker()
    expect(tracker.start()).toBe(false) // cannot start empty

    tracker.addWaypoint({ x: 1, y: 1 })
    expect(tracker.start()).toBe(true)
    expect(tracker.getStatus()).toBe('running')

    tracker.pause()
    expect(tracker.getStatus()).toBe('paused')

    tracker.resume()
    expect(tracker.getStatus()).toBe('running')

    tracker.abort()
    expect(tracker.getStatus()).toBe('aborted')
  })

  it('tracks mission progress and advances waypoints upon reaching threshold', () => {
    const tracker = new PatrolMissionTracker({ loop: false, toleranceMeters: 0.5 })
    tracker.addWaypoint({ x: 2, y: 0 })
    tracker.addWaypoint({ x: 5, y: 0 })
    tracker.start()

    expect(tracker.getCurrentIndex()).toBe(0)

    // Robot far from wp 0: distance = 2.0 > 0.5
    let result = tracker.advance({ x: 0, y: 0 })
    expect(result).toBe('reached')
    expect(tracker.getCurrentIndex()).toBe(0)

    // Robot close to wp 0: distance = 0.2 <= 0.5 -> advances to wp 1
    result = tracker.advance({ x: 1.8, y: 0 })
    expect(result).toBe('advancing')
    expect(tracker.getCurrentIndex()).toBe(1)

    // Robot close to wp 1: distance = 0.1 <= 0.5 -> finished
    result = tracker.advance({ x: 4.9, y: 0 })
    expect(result).toBe('finished')
    expect(tracker.getStatus()).toBe('completed')
  })

  it('loops back to initial waypoint when configured for loop', () => {
    const tracker = new PatrolMissionTracker({ loop: true, toleranceMeters: 0.5 })
    tracker.addWaypoint({ x: 2, y: 0 })
    tracker.addWaypoint({ x: 5, y: 0 })
    tracker.start()

    tracker.advance({ x: 2.1, y: 0 }) // reaches wp 0, advances to 1
    expect(tracker.getCurrentIndex()).toBe(1)

    tracker.advance({ x: 5.1, y: 0 }) // reaches wp 1, loops to 0
    expect(tracker.getCurrentIndex()).toBe(0)
    expect(tracker.getStatus()).toBe('running')
  })

  it('exports payload formatted for Nav2 Waypoint Follower action', () => {
    const tracker = new PatrolMissionTracker()
    tracker.addWaypoint({ x: 1.5, y: 2.5 }, 0.785)
    tracker.addWaypoint({ x: 4.0, y: -1.2 }, -1.57)

    const payload = tracker.toNav2GoalPayload()
    expect(payload.poses).toEqual([
      { x: 1.5, y: 2.5, yaw: 0.785 },
      { x: 4.0, y: -1.2, yaw: -1.57 },
    ])
  })
})
