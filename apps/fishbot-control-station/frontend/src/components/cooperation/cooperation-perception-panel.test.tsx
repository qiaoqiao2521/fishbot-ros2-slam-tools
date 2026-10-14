import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { CooperationPerceptionPanel } from './cooperation-perception-panel'
import { COOPERATION_STALE_MS, cooperationFrameSourceKey, type CooperationFrameObservation, type CooperationState } from '@/lib/cooperation'

const state: CooperationState = {
  mode: 'mujoco', domain: 114, ready: false, reason: '等待', episode_id: 'episode-a',
  task: { id: null, status: 'idle', stage: 'idle', message: '等待' }, events: [],
  physics: null, nav: null, stations: null, frame: { available: false, stamp: null }, source: { scene_sha: 'actual-scene' },
  perception: { mode: 'vision', publisher: 'camera_apriltag', detected: true, reason: 'AprilTag 图像观测有效', confidence: 0.83,
    stamp: 10, received_age_s: 0.02, source_age_s: 0.04, counts: { frames: 50, detected: 40 }, reprojection_error_px: 0.42 },
  vision_frame: { available: true, stamp: 10, episode_id: 'episode-a', sequence: 50,
    corners: [[10, 20], [50, 20], [50, 60], [10, 60]], image_width: 640, image_height: 480 },
  acceptance_report: { available: true, url: '/coop-api/report' },
}
const frame: CooperationFrameObservation = { scene: cooperationFrameSourceKey(state)!, stamp: 10, loadedStamp: 10,
  changedAt: 10000, error: false, vision: state.vision_frame }
function render(current = state, observed: CooperationFrameObservation | null = frame, now = 10000, connected = true) {
  return renderToStaticMarkup(<CooperationPerceptionPanel state={current} connected={connected} now={now} frame={observed} imageSrc="blob:rear-frame-50" />)
}

describe('cooperation perception evidence rendering', () => {
  it('renders actual rear RGB, captured AprilTag corners, geometric quality and a same-origin report', () => {
    const html = render()
    expect(html).toContain('后视相机 · AprilTag'); expect(html).toContain('AprilTag RGB 视觉')
    expect(html).toContain('src="blob:rear-frame-50"'); expect(html).toContain('data-vision-frame-live="true"')
    expect(html).toContain('viewBox="0 0 640 480"'); expect(html).toContain('points="10,20 50,20 50,60 10,60"')
    expect(html).toContain('AprilTag 实际检测框，帧 50'); expect(html).toContain('图像帧号 50')
    expect(html).toContain('camera_apriltag'); expect(html).toContain('图像观测有效')
    expect(html).toContain('几何质量'); expect(html).toContain('不能解释为成功概率'); expect(html).toContain('0.42 px')
    expect(html).toContain('href="/coop-api/report"'); expect(html).toContain('查看验收报告')
  })

  it('retains the displayed frame corners while newer state reports a different detection', () => {
    const html = render({ ...state, vision_frame: { ...state.vision_frame!, stamp: 11, sequence: 51,
      corners: [[111, 222], [333, 222], [333, 444], [111, 444]] } })
    expect(html).toContain('points="10,20 50,20 50,60 10,60"')
    expect(html).not.toContain('111,222'); expect(html).toContain('图像帧号 50')
  })

  it('hides prior episode image and overlay immediately before buffer cleanup effects', () => {
    const html = render({ ...state, episode_id: 'episode-b', vision_frame: { ...state.vision_frame!, episode_id: 'episode-b' } })
    expect(html).not.toContain('<img'); expect(html).not.toContain('<polygon')
    expect(html).toContain('data-vision-frame-live="false"'); expect(html).toContain('来源已变化')
    expect(html).toContain('图像帧号 未收到')
  })

  it('shows a concrete detection failure with no invented overlay or probability', () => {
    const missing = { ...state, perception: { ...state.perception!, detected: false, reason: '工位标记被货物遮挡', confidence: null, reprojection_error_px: null },
      vision_frame: { ...state.vision_frame!, corners: null }, acceptance_report: { available: false, url: null } }
    const html = render(missing, { ...frame, vision: missing.vision_frame })
    expect(html).toContain('工位标记被货物遮挡'); expect(html).toContain('最近观测：未检出目标')
    expect(html).not.toContain('<polygon'); expect(html).not.toContain('查看验收报告')
    expect(html).toContain('当前显示帧没有检测框')
  })

  it('explains detector rejection codes while preserving the original reason', () => {
    const html = render({ ...state, perception: { ...state.perception!, detected: false, reason: 'ambiguous_planar_pose' } })
    expect(html).toContain('平面标记的位姿解存在歧义（ambiguous_planar_pose）')
    expect(html).toContain('最近观测：未检出目标')
  })

  it('expires camera and perception badges without replacing the last displayed image', () => {
    const html = render(state, frame, 10000 + COOPERATION_STALE_MS, false)
    expect(html).toContain('感知反馈已过期'); expect(html).toContain('画面已过期')
    expect(html).toContain('data-vision-frame-live="false"'); expect(html).toContain('blob:rear-frame-50')
  })

  it('labels permitted source clock lead and never declares RGB readiness from mode alone', () => {
    const html = render({ ...state, perception: { ...state.perception!, source_age_s: -0.02, detected: false, reason: '图像帧尚未就绪' },
      vision_frame: { ...state.vision_frame!, available: false, stamp: null, sequence: 0, corners: null } }, null)
    expect(html).toContain('-0.020 s（源时钟领先）'); expect(html).toContain('图像帧尚未就绪')
    expect(html).toContain('data-vision-frame-live="false"'); expect(html).not.toContain('<img')
    expect(html).not.toContain('共享场景已就绪')
  })

  it('retains the last successful rear frame as history when the current image becomes unavailable', () => {
    const html = render({ ...state, vision_frame: { ...state.vision_frame!, available: false, stamp: null, sequence: 0, corners: null } })
    expect(html).toContain('src="blob:rear-frame-50"'); expect(html).toContain('图像帧号 50')
    expect(html).toContain('等待后视相机画面'); expect(html).toContain('data-vision-frame-live="false"')
    expect(html).not.toContain('相机画面持续更新')
  })

  it('keeps the legacy page free of visual detection claims when optional fields are absent', () => {
    const legacy = { ...state, perception: undefined, vision_frame: undefined, acceptance_report: undefined }
    expect(render(legacy)).toBe('')
  })
})
