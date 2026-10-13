import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  collisionMonitorText, isFreeWaypoint, mapToWorld, missionCanRetryCancel,
  missionIsActive, missionLabel, missionProgressText, missionReceiptResolved, requestSimulation, simulationDomain, simulationRequestRejected, SimulationRejectedRequest,
  validateSimulationMap, validateSimulationState, worldToMap,
  type SimulationMap, type SimulationState,
} from '@/lib/simulation'
import { resolveAppRoute } from '@/lib/app-route'

const map: SimulationMap = {
  width: 4, height: 3, resolution: 1, origin: [-2, -1, 0],
  data: [0, 0, 100, 0, 0, -1, 0, 0, 0, 0, 0, 0],
}
const state: SimulationState = {
  mode: 'mujoco', domain: 93, ready: true, reason: '已就绪',
  pose: { x: 0, y: 0, yaw: 0 }, truth: { x: 0, y: 0, yaw: 0, linear_speed: 0, angular_speed: 0 },
  path: [], home: { x: 0, y: 0, yaw: 0 },
  mission: { id: 'mission-1', status: 'running', current_index: 0, waypoints: [{ x: 2, y: 1, yaw: 0 }], return_home: false, message: '前往中', dispatch_state: 'accepted', stop_reason: null },
  obstacle: { state: 'parked', x: -0.7, y: -0.7, size: 0.36 },
}

afterEach(() => vi.unstubAllGlobals())

describe('simulation map coordinates', () => {
  it('places an occupied lower ROS row at the lower screen edge', () => {
    const point = { x: 0.5, y: -0.5 }
    expect(worldToMap(point, map)).toEqual({ x: 2.5, y: 2.5 })
    expect(mapToWorld({ x: 2.5, y: 2.5 }, map)).toEqual(point)
    expect(isFreeWaypoint(point, map, 0)).toBe(false)
    expect(isFreeWaypoint({ x: -0.5, y: 1.5 }, map, 0)).toBe(true)
  })

  it('accounts for rotated origins rather than treating all grids as axis aligned', () => {
    const rotated = { ...map, width: 4, height: 6, resolution: 0.5, origin: [10, 20, Math.PI / 2] as [number, number, number] }
    const pixel = worldToMap({ x: 9, y: 20.5 }, rotated)
    expect(pixel.x).toBeCloseTo(1)
    expect(pixel.y).toBeCloseTo(4)
    const world = mapToWorld({ x: 1, y: 4 }, rotated)
    expect(world.x).toBeCloseTo(9)
    expect(world.y).toBeCloseTo(20.5)
  })

  it('rejects unknown cells and goals too close to occupied cells or map boundaries', () => {
    expect(isFreeWaypoint({ x: -0.5, y: 0.5 }, map, 0)).toBe(false)
    expect(isFreeWaypoint({ x: 1.5, y: -0.5 }, map, 1)).toBe(false)
    expect(isFreeWaypoint({ x: -1.99, y: -0.99 }, map, 0.18)).toBe(false)
    expect(() => validateSimulationMap({ ...map, data: [] })).toThrow('地图数据不完整')
  })
})

describe('simulation server responses', () => {

  it('does not unlock an unknown dispatch from an old or unrelated task readback', () => {
    const receipt = { previousId: state.mission.id, waypoints: state.mission.waypoints, returnHome: false }
    expect(missionReceiptResolved(receipt, state)).toBe(false)
    expect(missionReceiptResolved(receipt, { ...state, mission: { ...state.mission, id: 'unrelated', waypoints: [{ x: 3, y: 4, yaw: 0 }] } })).toBe(false)
    expect(missionReceiptResolved(receipt, { ...state, mission: { ...state.mission, id: 'new' } })).toBe(true)
    const returning = { ...receipt, returnHome: true, waypoints: [{ x: 2, y: 1, yaw: Math.PI * 2 }] }
    expect(missionReceiptResolved(returning, { ...state, mission: { ...state.mission, id: 'new', return_home: true, waypoints: [...state.mission.waypoints, state.home] } })).toBe(true)
    const alreadyHome = { previousId: 'old', waypoints: [state.home], returnHome: true }
    expect(missionReceiptResolved(alreadyHome, { ...state, mission: { ...state.mission, id: 'new', return_home: true, waypoints: [state.home] } })).toBe(true)
  })

  it('distinguishes explicit pre-dispatch expiry from transport and server uncertainty', () => {
    expect(simulationRequestRejected(new SimulationRejectedRequest('expired before dispatch', 408))).toBe(true)
    expect(simulationRequestRejected(new SimulationRejectedRequest('conflict', 409))).toBe(true)
    expect(simulationRequestRejected(new SimulationRejectedRequest('poll actual state', 504))).toBe(false)
    expect(simulationRequestRejected(new SimulationRejectedRequest('readiness unavailable before dispatch', 503, 'rejected'))).toBe(true)
    expect(simulationRequestRejected(new SimulationRejectedRequest('storage unavailable', 503))).toBe(false)
    expect(simulationRequestRejected(new Error('connection reset'))).toBe(false)
  })


  it('reads a definite pre-dispatch rejection without confusing it with an uncertain server failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ error: '规则尚未应用', outcome: 'rejected' }), { status: 503 }))))
    try { await requestSimulation('mission', {}) } catch (error) {
      expect(simulationRequestRejected(error)).toBe(true)
      expect(error).toBeInstanceOf(SimulationRejectedRequest)
      expect((error as SimulationRejectedRequest).outcome).toBe('rejected')
      return
    }
    throw new Error('Missing expected rejection')
  })

  it('requires a matching explicitly selected nonzero simulation domain', () => {
    expect(simulationDomain()).toBe(93)
    expect(simulationDomain('100')).toBe(100)
    for (const value of ['0', '233', '-1', '100.5', '١', '100junk']) {
      expect(() => simulationDomain(value)).toThrow('仿真域必须')
    }
    const isolated = { ...state, domain: 100 }
    expect(validateSimulationState(isolated, 100).domain).toBe(100)
    expect(() => validateSimulationState(isolated)).toThrow('当前 MuJoCo 仿真')
    expect(() => validateSimulationState(state, 100)).toThrow('当前 MuJoCo 仿真')
    expect(() => validateSimulationState({ ...state, domain: 0 }, 0)).toThrow('当前 MuJoCo 仿真')
  })
  it('keeps unknown cleanup active and exposes cancellation retry without accepting new goals', () => {
    const unresolved = { ...state, mission: { ...state.mission, status: 'canceling' as const,
      cleanup_state: 'unresolved' as const, stop_reason: '结果回执异常' } }
    const received = validateSimulationState(unresolved)
    expect(missionIsActive(received)).toBe(true)
    expect(missionCanRetryCancel(received.mission)).toBe(true)
    expect(missionProgressText(received.mission)).toContain('终态仍未知')
    expect(missionCanRetryCancel({ ...received.mission, cleanup_state: 'retrying' })).toBe(false)
    expect(missionCanRetryCancel({ ...received.mission, status: 'canceled' })).toBe(false)
  })

  it('retains an unknown acceptance without offering a cancellation it cannot send', () => {
    const unknown = { ...state, mission: { ...state.mission, status: 'canceling' as const,
      dispatch_state: 'unavailable' as const, cleanup_state: 'unresolved' as const,
      stop_reason: '接收回执异常' } }
    const received = validateSimulationState(unknown)
    expect(received.mission.id).toBe(state.mission.id)
    expect(missionIsActive(received)).toBe(true)
    expect(missionCanRetryCancel(received.mission)).toBe(false)
    expect(missionLabel(received.mission.status, received.mission.dispatch_state)).toBe('接收状态未知')
    expect(missionProgressText(received.mission)).toContain('当前无法确认取消')
    expect(missionProgressText(received.mission)).not.toContain('可以重试取消')
  })

  it('shows real CM events without treating their age as a heartbeat timeout', () => {
    const collision_monitor = { source: '/collision_monitor_state' as const, available: true,
      action: 'stop' as const, action_type: 1, polygon_name: 'VelocityStop', observation_age_s: 90 }
    const received = validateSimulationState({ ...state, collision_monitor })
    expect(collisionMonitorText(received.collision_monitor)).toBe('停车 · VelocityStop')
    expect(collisionMonitorText({ ...collision_monitor, polygon_name: 'invalid source' })).toContain('来源无效')
    expect(collisionMonitorText({ ...collision_monitor, available: false })).toContain('未知')
    expect(collisionMonitorText()).toContain('未知')
    expect(() => validateSimulationState({ ...state, collision_monitor: { ...collision_monitor, observation_age_s: -1 } })).toThrow('当前 MuJoCo 仿真')
  })
  it('shows HTTP dispatch pending as waiting for Nav2 rather than traveling', async () => {
    const pending = { ...state, mission: { ...state.mission, dispatch_state: 'pending' } }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(pending), { status: 202 })))
    const received = validateSimulationState(await requestSimulation<SimulationState>('mission', {}))
    expect(missionIsActive(received)).toBe(true)
    expect(missionLabel(received.mission.status, received.mission.dispatch_state)).toBe('等待 Nav2 确认')
    expect(missionProgressText(received.mission)).toContain('尚未收到 Nav2 接收回执')
    const accepted = { ...received.mission, dispatch_state: 'accepted' as const }
    expect(missionLabel(accepted.status, accepted.dispatch_state)).toBe('正在巡逻')
    expect(missionProgressText(accepted)).toBe('正在前往第 1 / 1 个点')
  })

  it('keeps the original cancellation trigger visible after a final canceled result', () => {
    const canceled = { ...state, mission: { ...state.mission, status: 'canceled' as const,
      message: 'Nav2 已取消巡逻', stop_reason: '仿真未就绪：仿真时钟未就绪或已暂停' } }
    const received = validateSimulationState(canceled)
    expect(received.mission.stop_reason).toBe('仿真未就绪：仿真时钟未就绪或已暂停')
    expect(missionProgressText(received.mission)).toBe('Nav2 已确认取消任务。')
    expect(missionIsActive(received)).toBe(false)
  })

  it('accepts older bridge states without the additive receipt fields', () => {
    const legacy = { ...state, mission: { ...state.mission } }
    delete legacy.mission.dispatch_state
    delete legacy.mission.stop_reason
    expect(validateSimulationState(legacy).mission.status).toBe('running')
    expect(missionLabel(legacy.mission.status)).toBe('正在巡逻')
    expect(() => validateSimulationState({ ...state, mission: { ...state.mission, dispatch_state: 'invented' } } as unknown as SimulationState)).toThrow('当前 MuJoCo 仿真')
    expect(() => validateSimulationState({ ...state, mission: { ...state.mission, stop_reason: 123 } } as unknown as SimulationState)).toThrow('当前 MuJoCo 仿真')
  })

  it('preserves paused readiness reasons when the obstacle has not supplied coordinates', () => {
    const paused = {
      ...state, ready: false, reason: '仿真时钟暂停，等待继续',
      obstacle: { ...state.obstacle, state: 'unknown', x: null, y: null },
    }
    expect(validateSimulationState(paused).reason).toBe('仿真时钟暂停，等待继续')
    expect(validateSimulationState(paused).ready).toBe(false)
    expect(() => validateSimulationState({ ...paused, obstacle: { ...paused.obstacle, y: 0 } })).toThrow('当前 MuJoCo 仿真')
  })

  it('keeps accepted navigation running until the server returns a terminal result', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(state), { status: 202 })))
    const received = validateSimulationState(await requestSimulation<SimulationState>('mission', {
      waypoints: state.mission.waypoints, return_home: false, issued_at: Date.now() / 1000,
    }))
    expect(missionIsActive(received)).toBe(true)
    expect(missionLabel(received.mission.status)).toBe('正在巡逻')
    expect(received.mission.status).not.toBe('succeeded')
  })

  it('retains canceling as active and distinguishes final canceled from succeeded', async () => {
    const canceling = { ...state, mission: { ...state.mission, status: 'canceling' } }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(canceling), { status: 202 })))
    const received = validateSimulationState(await requestSimulation<SimulationState>('cancel', {}))
    expect(missionIsActive(received)).toBe(true)
    expect(missionLabel(received.mission.status)).toBe('正在取消')
    expect(missionIsActive({ ...received, mission: { ...received.mission, status: 'canceled' } })).toBe(false)
    expect(missionLabel('canceled')).toBe('已取消')
    expect(missionLabel('succeeded')).toBe('巡逻完成')
  })

  it('surfaces a rejected mission as an error without inventing an accepted state', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: '任务已过期，请重新派发' }), { status: 409 })))
    await expect(requestSimulation('mission', { issued_at: 0 })).rejects.toThrow('任务已过期，请重新派发')
  })

  it('rejects another ROS domain and routes simulation independently of the original console', () => {
    expect(() => validateSimulationState({ ...state, domain: 94 } as unknown as SimulationState)).toThrow('当前 MuJoCo 仿真')
    expect(resolveAppRoute('/simulation')).toBe('simulation')
    expect(resolveAppRoute('/radar')).toBe('radar')
    expect(resolveAppRoute('/')).toBe('dashboard')
  })
})
