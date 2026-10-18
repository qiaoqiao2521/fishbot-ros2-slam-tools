import { useEffect, useRef, useState } from 'react'
import { Camera, FileCheck, Pause } from 'lucide-react'
import { useWorkspaceVisible } from '@/components/workspace/workspace-visibility'
import { cooperationConnected, cooperationFrameLabel, cooperationFrameSourceKey,
  type CooperationFrameObservation, type CooperationSnapshot } from '@/lib/cooperation'
import { CooperationCameraSession } from './cooperation-camera-session'
import { CooperationPerceptionPanel } from './cooperation-perception-panel'

export type CooperationCanvasProps = {
  snapshot: CooperationSnapshot
  now: number
  frame: CooperationFrameObservation | null
  displayedFrameSrc?: string | null
  visionFrame?: CooperationFrameObservation | null
  displayedVisionSrc?: string | null
  rearOpen?: boolean
  onRearOpen?: (open: boolean) => void
}

/** Pure image projection, also used by the existing evidence/SSR tests. */
export function CooperationCanvasView({ snapshot, now, frame, displayedFrameSrc, visionFrame = null,
  displayedVisionSrc = null, rearOpen = false, onRearOpen }: CooperationCanvasProps) {
  const { state } = snapshot
  const connected = cooperationConnected(snapshot, now)
  const frameStamp = state?.frame.available ? state.frame.stamp : null
  const frameLabel = cooperationFrameLabel(state, frame, connected, now)
  const frameLive = frameLabel === '相机画面持续更新'
  const matches = !!frame && frame.scene === cooperationFrameSourceKey(state)
    && (frame.loadedStamp === null || frameStamp === null || frame.loadedStamp <= frameStamp)
  const imageSrc = !matches ? null : displayedFrameSrc === undefined && frameStamp !== null
    ? `/coop-api/frame.jpg?stamp=${encodeURIComponent(frame?.loadedStamp ?? frameStamp)}${state?.episode_id ? `&episode_id=${encodeURIComponent(state.episode_id)}` : ''}` : displayedFrameSrc
  return <div className="cooperation-canvas" data-rear-open={rearOpen}>
    <div className="cooperation-canvas-caption">
      <span>{rearOpen ? '后向相机与停靠感知' : '共享物理场景'}</span>
      {state?.acceptance_report?.available && state.acceptance_report.url && <a href={state.acceptance_report.url} target="_blank" rel="noopener noreferrer" className="cooperation-canvas-report"><FileCheck size={14} aria-hidden="true" />验收报告</a>}
      {!rearOpen && <span className={`cooperation-camera-status ${frameLive ? 'cooperation-camera-live' : ''}`}><Camera size={14} aria-hidden="true" />{frameLabel}</span>}
    </div>
    <div className={`cooperation-camera ${frameLive ? '' : 'cooperation-camera-unavailable'}`} data-frame-live={frameLive}>
      {imageSrc ? <>
        <img src={imageSrc} alt="共享 MuJoCo 场景的实际相机画面" />
        {!frameLive && <div className="cooperation-camera-notice"><Camera size={20} aria-hidden="true" /><span>{frameLabel}</span></div>}
      </> : <div className="cooperation-camera-empty"><Camera size={34} aria-hidden="true" /><strong>等待实际相机画面</strong><p>小车、机械臂与自由货物处于同一个物理场景。</p></div>}
    </div>
    <div className="cooperation-camera-footer">
      <span>相机仿真时间 {matches && frame?.loadedStamp !== null ? `${frame.loadedStamp.toFixed(3)} s` : '未收到'}</span>
      <span>物理反馈 {state?.physics ? `${state.physics.stamp.toFixed(3)} s` : '未收到'}</span>
      <span>{connected ? '状态每秒读取' : '当前显示为历史反馈'}</span>
    </div>
    <details className="cooperation-rear-details" open={rearOpen} onToggle={(event) => onRearOpen?.(event.currentTarget.open)}>
      <summary>后向相机、停靠感知与验收报告</summary>
      <CooperationPerceptionPanel state={state} connected={connected} now={now} frame={visionFrame} imageSrc={displayedVisionSrc} />
    </details>
  </div>
}

/** Only this panel owns image decoding; the page retains the sole business controller. */
export function LiveCooperationCanvas({ snapshot, now, active = true }: {
  snapshot: CooperationSnapshot; now: number; active?: boolean
}) {
  const panelVisible = useWorkspaceVisible()
  const visible = active && panelVisible
  const [rearOpen, setRearOpen] = useState(false)
  const [frame, setFrame] = useState<CooperationFrameObservation | null>(null)
  const [displayedFrameSrc, setDisplayedFrameSrc] = useState<string | null>(null)
  const [visionFrame, setVisionFrame] = useState<CooperationFrameObservation | null>(null)
  const [displayedVisionSrc, setDisplayedVisionSrc] = useState<string | null>(null)
  const session = useRef<CooperationCameraSession | null>(null)
  useEffect(() => {
    const current = new CooperationCameraSession({
      scene: { display: setDisplayedFrameSrc, observe: setFrame },
      rear: { display: setDisplayedVisionSrc, observe: setVisionFrame },
    })
    session.current = current
    return () => { current.dispose(); session.current = null }
  }, [])
  useEffect(() => { session.current?.update(snapshot.state, visible, rearOpen) }, [snapshot.state, visible, rearOpen])
  if (!visible) return <div className="cooperation-canvas-paused" role="status"><Pause size={24} aria-hidden="true" /><strong>画布已暂停</strong><p>相机解码已暂停，原任务与状态读取继续。</p></div>
  return <CooperationCanvasView snapshot={snapshot} now={now} frame={frame} displayedFrameSrc={displayedFrameSrc}
    visionFrame={visionFrame} displayedVisionSrc={displayedVisionSrc} rearOpen={rearOpen} onRearOpen={setRearOpen} />
}
