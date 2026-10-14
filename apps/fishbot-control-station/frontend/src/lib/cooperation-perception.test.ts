import { describe, expect, it, vi } from 'vitest'
import {
  CooperationController, cooperationExpectedDomain, cooperationFrameSourceKey, cooperationVisionFrameLabel,
  cooperationVisionFrameMatches, cooperationPerceptionReason, validateCooperationState,
  type CooperationFrameObservation, type CooperationState,
} from './cooperation'

const visualState: CooperationState = {
  mode: 'mujoco', domain: 114, ready: false, reason: '等待视觉观测', episode_id: 'episode-a',
  task: { id: null, status: 'idle', stage: 'idle', message: '等待开始' }, events: [],
  physics: null, nav: null, stations: null, frame: { available: false, stamp: null }, source: { scene_sha: 'scene-a' },
  perception: { mode: 'vision', publisher: 'apriltag_rgb', detected: true, reason: '图像位姿有效', confidence: 0.83,
    stamp: 10, received_age_s: 0.02, source_age_s: 0.04, counts: { frames: 50, detected: 40 }, reprojection_error_px: 0.42 },
  vision_frame: { available: true, stamp: 10, episode_id: 'episode-a', sequence: 50,
    corners: [[10, 20], [50, 20], [50, 60], [10, 60]], image_width: 640, image_height: 480 },
  acceptance_report: { available: true, url: '/coop-api/report' },
}

describe('optional cooperation perception contract', () => {
  it('distinguishes insufficient pixels from clipping', () => {
    expect(cooperationPerceptionReason('insufficient_resolution')).toContain('像素尺寸不足')
    expect(cooperationPerceptionReason('clipped_tag')).toContain('画面边缘裁切')
  })
  it('binds the expected ROS domain to configuration rather than the returned state', () => {
    expect(cooperationExpectedDomain(undefined)).toBe(114)
    expect(cooperationExpectedDomain('120')).toBe(120)
    for (const invalid of ['-1', '233', '120.5', 'vision', null]) expect(() => cooperationExpectedDomain(invalid)).toThrow('ROS 域')
    expect(() => validateCooperationState({ ...visualState, domain: 120 })).toThrow('ROS 域不匹配')
    expect(validateCooperationState({ ...visualState, domain: 120 }, 120).domain).toBe(120)
    expect(() => validateCooperationState(visualState, 120)).toThrow('ROS 域不匹配')
  })

  it('keeps legacy services and nullable startup diagnostics valid', () => {
    const legacy = { ...visualState }
    delete legacy.perception; delete legacy.vision_frame; delete legacy.acceptance_report
    expect(validateCooperationState(legacy)).toEqual(legacy)
    expect(validateCooperationState({ ...visualState, perception: { ...visualState.perception!, confidence: null,
      stamp: null, received_age_s: null, source_age_s: null, reprojection_error_px: null },
      vision_frame: { ...visualState.vision_frame!, available: false, stamp: null, corners: null, episode_id: '' },
      acceptance_report: { available: false, url: null } }).ready).toBe(false)
    expect(validateCooperationState({ ...visualState, perception: { ...visualState.perception!, source_age_s: -0.02 } }).perception?.source_age_s).toBe(-0.02)
  })

  it.each([
    { perception: { ...visualState.perception!, source_age_s: Number.POSITIVE_INFINITY } },
    { perception: { ...visualState.perception!, confidence: 1.1 } },
    { perception: { ...visualState.perception!, reprojection_error_px: Number.NaN } },
    { perception: { ...visualState.perception!, counts: { frames: 1.5 } } },
    { vision_frame: { ...visualState.vision_frame!, episode_id: 'previous-episode' } },
    { vision_frame: { ...visualState.vision_frame!, corners: [[1, 2], [3, 4]] } },
    { vision_frame: { ...visualState.vision_frame!, corners: [[Number.NaN, 2], [3, 4], [5, 6], [7, 8]] } },
    { acceptance_report: { available: true, url: 'https://external.test/report' } },
    { acceptance_report: { available: true, url: '/coop-api/../admin' } },
  ])('rejects malformed perception, mismatched images and unrelated report links', (patch) => {
    expect(() => validateCooperationState({ ...visualState, ...patch })).toThrow('状态不完整')
  })

  it('retains the original task receipt when optional visual telemetry is invalid', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ ...visualState, vision_frame: { ...visualState.vision_frame!, sequence: -1 } })))
    const storage = { getItem: () => JSON.stringify({ ownedTaskId: 'old-task', receipt: { action: 'start', taskId: 'old-task', unknown: true } }), setItem: vi.fn(), removeItem: vi.fn() }
    const controller = new CooperationController({ fetcher, now: () => 10000, storage })
    await controller.refresh(); await controller.act('start')
    expect(controller.getSnapshot().state).toBeNull()
    expect(controller.getSnapshot().connectionError).toContain('状态不完整')
    expect(controller.getSnapshot().receipt).toEqual({ action: 'start', taskId: 'old-task', unknown: true })
    expect(fetcher.mock.calls).toHaveLength(1)
  })

  it('rejects old episodes and sequence regression before rendering a displayed image', () => {
    const observation: CooperationFrameObservation = { scene: cooperationFrameSourceKey(visualState)!, stamp: 10, changedAt: 10000, loadedStamp: 10, error: false, vision: visualState.vision_frame }
    expect(cooperationVisionFrameMatches(visualState, observation)).toBe(true)
    expect(cooperationVisionFrameLabel(visualState, observation, true, 10000)).toBe('相机画面持续更新')
    const next = { ...visualState, episode_id: 'episode-b', vision_frame: { ...visualState.vision_frame!, episode_id: 'episode-b' } }
    expect(cooperationVisionFrameMatches(next, observation)).toBe(false)
    expect(cooperationVisionFrameLabel(next, observation, true, 10000)).toContain('来源已变化')
    expect(cooperationVisionFrameMatches({ ...visualState, vision_frame: { ...visualState.vision_frame!, sequence: 49 } }, observation)).toBe(false)
    expect(cooperationVisionFrameLabel(visualState, observation, false, 10000)).toBe('画面已过期')
  })
})
