import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  isFreeWaypoint, mapToWorld, missionIsActive, missionLabel, requestSimulation,
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
  mission: { id: 'mission-1', status: 'running', current_index: 0, waypoints: [{ x: 2, y: 1, yaw: 0 }], return_home: false, message: '前往中' },
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
