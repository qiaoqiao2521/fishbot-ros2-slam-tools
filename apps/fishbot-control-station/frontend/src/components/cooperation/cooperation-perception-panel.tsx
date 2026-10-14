import { Camera, FileCheck } from 'lucide-react'
import {
  cooperationPerceptionModeLabel, cooperationPerceptionReason, cooperationVisionFrameLabel, cooperationVisionFrameMatches,
  type CooperationFrameObservation, type CooperationState,
} from '@/lib/cooperation'

function value(number: number | null | undefined, unit: string, digits = 3): string {
  return number == null ? '未提供' : `${number.toFixed(digits)}${unit}`
}
const countLabels: Record<string, string> = { accepted: '有效观测', rejected: '拒绝', forwarded: '已发送', unavailable: '未就绪', frames: '图像', detected: '检出' }

export function CooperationPerceptionPanel({ state, connected, now, frame, imageSrc }: {
  state: CooperationState | null; connected: boolean; now: number
  frame: CooperationFrameObservation | null; imageSrc: string | null
}) {
  const perception = state?.perception, report = state?.acceptance_report
  if (!perception && !state?.vision_frame && !report) return null
  const label = cooperationVisionFrameLabel(state, frame, connected, now)
  const live = label === '相机画面持续更新'
  const matches = cooperationVisionFrameMatches(state, frame)
  const displayed = matches ? frame?.vision : null
  const src = matches ? imageSrc : null
  const showCamera = perception?.mode === 'vision' || state?.vision_frame?.available

  return <section className="cooperation-perception" aria-labelledby="cooperation-perception-heading" data-current={connected}>
    <div className="cooperation-section-heading">
      <div><h2 id="cooperation-perception-heading">停靠感知</h2><p>{cooperationPerceptionModeLabel(perception?.mode)} · 仅用于仿真</p></div>
      <span className="cooperation-perception-status">{!connected ? '感知反馈已过期' : perception ? `最近观测：${perception.detected ? '检出目标' : '未检出目标'}` : '等待感知反馈'}</span>
    </div>
    {perception && <>
      <p className="cooperation-perception-reason" role="status">{cooperationPerceptionReason(perception.reason)}</p>
      <dl className="cooperation-perception-metrics">
        <div><dt>发布者</dt><dd>{perception.publisher || '未提供'}</dd></div>
        <div><dt>观测源时间</dt><dd>{value(perception.stamp, ' s')}</dd></div>
        <div><dt>接收时龄</dt><dd>{value(perception.received_age_s, ' s')}</dd></div>
        <div><dt>源时龄</dt><dd>{value(perception.source_age_s, ' s')}{perception.source_age_s != null && perception.source_age_s < 0 ? '（源时钟领先）' : ''}</dd></div>
        <div><dt>几何质量</dt><dd>{value(perception.confidence, '', 3)}</dd></div>
        <div><dt>重投影误差</dt><dd>{value(perception.reprojection_error_px, ' px', 2)}</dd></div>
      </dl>
      <p className="cooperation-perception-note">几何质量是来源提供的评分，不能解释为成功概率。计数：{Object.entries(perception.counts).map(([name, count]) => `${countLabels[name] ?? name} ${count}`).join(' · ') || '未提供'}。</p>
    </>}
    {showCamera && <>
      <div className="cooperation-section-heading"><h2>后视相机 · AprilTag</h2><span className={`cooperation-camera-status ${live ? 'cooperation-camera-live' : ''}`}><Camera size={14} aria-hidden="true" />{label}</span></div>
      <div className={`cooperation-camera cooperation-vision-camera ${live ? '' : 'cooperation-camera-unavailable'}`} data-vision-frame-live={live}>
        {src && displayed ? <>
          <img src={src} alt="FishBot 后视相机的实际 MuJoCo RGB 画面" />
          {displayed.corners && <svg className="cooperation-tag-overlay" viewBox={`0 0 ${displayed.image_width} ${displayed.image_height}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label={`AprilTag 实际检测框，帧 ${displayed.sequence}`}>
            <polygon points={displayed.corners.map(([x, y]) => `${x},${y}`).join(' ')} vectorEffect="non-scaling-stroke" />
          </svg>}
          {!live && <div className="cooperation-camera-notice"><Camera size={20} aria-hidden="true" /><span>{label}</span></div>}
        </> : <div className="cooperation-camera-empty"><Camera size={28} aria-hidden="true" /><strong>等待后视相机画面</strong><p>{perception ? cooperationPerceptionReason(perception.reason) : '检测帧就绪后将在这里显示。'}</p></div>}
      </div>
      <div className="cooperation-camera-footer">
        <span>图像源时间 {displayed && frame?.loadedStamp != null ? `${frame.loadedStamp.toFixed(3)} s` : '未收到'}</span>
        <span>图像帧号 {displayed?.sequence ?? '未收到'}</span>
        <span>{displayed?.corners ? '检测框与当前显示帧对应' : '当前显示帧没有检测框'}</span>
      </div>
    </>}
    {report?.available && report.url && <a className="cooperation-button cooperation-quiet cooperation-report-link" href={report.url} target="_blank" rel="noopener noreferrer"><FileCheck size={16} aria-hidden="true" />查看验收报告</a>}
  </section>
}
