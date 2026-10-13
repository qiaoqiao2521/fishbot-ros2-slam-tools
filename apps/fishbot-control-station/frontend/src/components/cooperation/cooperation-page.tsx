import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, Box, Camera, CircleCheck, MapPin, Play, RefreshCw, Square, Truck } from 'lucide-react'

import {
  COOPERATION_DOMAIN, COOPERATION_POLL_MS, COOPERATION_STAGES, CooperationController,
  cooperationCanCancel, cooperationCanStart, cooperationConnected, cooperationFrameLabel,
  cooperationStageLabel, cooperationStatusLabel,
  type CooperationFrameObservation, type CooperationSnapshot,
} from '@/lib/cooperation'
import './cooperation.css'
import { CooperationFrameBuffer } from '@/lib/cooperation-frame'

export function CooperationPage({ onBack, controller: suppliedController }: { onBack: () => void; controller?: CooperationController }) {
  const [controller] = useState(() => {
    if (suppliedController) return suppliedController
    let storage: Storage | null = null
    try { storage = window.sessionStorage } catch { /* The controller retains receipts in memory when storage is blocked. */ }
    return new CooperationController({ storage })
  })
  const [snapshot, setSnapshot] = useState(controller.getSnapshot)
  const [now, setNow] = useState(Date.now)
  const [frame, setFrame] = useState<CooperationFrameObservation | null>(null)
  const [displayedFrameSrc, setDisplayedFrameSrc] = useState<string | null>(null)
  const frameStamp = snapshot.state?.frame.available ? snapshot.state.frame.stamp : null
  const frameScene = snapshot.state?.source?.scene_sha ?? null
  const frameBuffer = useRef<CooperationFrameBuffer | null>(null)

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    const unsubscribe = controller.subscribe(setSnapshot)
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      await controller.refresh()
      if (!stopped) timer = setTimeout(poll, COOPERATION_POLL_MS)
    }
    void poll()
    return () => { stopped = true; clearTimeout(timer); unsubscribe() }
  }, [controller])

  useEffect(() => {
    const buffer = new CooperationFrameBuffer({ display: setDisplayedFrameSrc, observe: setFrame })
    frameBuffer.current = buffer
    return () => { buffer.dispose(); frameBuffer.current = null }
  }, [])
  useEffect(() => { frameBuffer.current?.request(frameScene, frameStamp) }, [frameScene, frameStamp])

  return <CooperationView snapshot={snapshot} now={now} frame={frame} onBack={onBack}
    onStart={() => { void controller.act('start') }} onCancel={() => { void controller.act('cancel') }}
    onRefresh={() => { void controller.refresh() }} displayedFrameSrc={displayedFrameSrc} />
}

type CooperationViewProps = {
  snapshot: CooperationSnapshot
  now: number
  frame: CooperationFrameObservation | null
  onBack: () => void
  onStart: () => void
  onCancel: () => void
  onRefresh: () => void
  displayedFrameSrc?: string | null
}

function metric(value: number | undefined, digits = 3): string {
  return value === undefined ? '未收到' : value.toFixed(digits)
}

export function CooperationView({ snapshot, now, frame, onBack, onStart, onCancel, onRefresh, displayedFrameSrc }: CooperationViewProps) {
  const { state, pending, receipt, actionError, connectionError } = snapshot
  const connected = cooperationConnected(snapshot, now)
  const ready = connected && !!state?.ready
  const physics = state?.physics
  const frameStamp = state?.frame.available ? state.frame.stamp : null
  const frameLabel = cooperationFrameLabel(state, frame, connected, now)
  const frameLive = frameLabel === '相机画面持续更新'
  const frameMatchesSource = !!frame && frame.scene === state?.source?.scene_sha
    && (frame.loadedStamp === null || frameStamp === null || frame.loadedStamp <= frameStamp)
  const imageSrc = !frameMatchesSource ? null : displayedFrameSrc === undefined && frameStamp !== null
    ? `/coop-api/frame.jpg?stamp=${encodeURIComponent(frame?.loadedStamp ?? frameStamp)}` : displayedFrameSrc
  const task = state?.task
  const stageLabel = cooperationStageLabel(task?.stage)
  const canStart = cooperationCanStart(snapshot, now)
  const canCancel = cooperationCanCancel(snapshot, now)
  const events = [...new Map((state?.events ?? []).map((event) => [event.sequence, event])).values()]
    .sort((first, second) => first.sequence - second.sequence)
  const carStopped = !!physics && Math.abs(physics.car.linear_speed) < 0.01 && Math.abs(physics.car.angular_speed) < 0.03
  const stageRole = COOPERATION_STAGES.find((item) => item.key === task?.stage)?.role
  const armPhase = stageRole === 'arm' ? stageLabel : task?.status === 'succeeded' ? '机械臂已退出' : '等待机械臂阶段反馈'
  const startReason = receipt ? '正在核对原任务，暂不能重复派发。' : !connected ? '等待有效的协同服务状态。'
    : !state?.ready ? state?.reason : !canStart ? '当前任务尚未结束。' : '小车到固定工位装货，再驶向交付点。'

  return <main className="cooperation-page">
    <header className="cooperation-header">
      <div>
        <div className="cooperation-mode"><span aria-hidden="true" />共享 MuJoCo 仿真<span>ROS 域 {COOPERATION_DOMAIN}</span></div>
        <h1>车臂协同</h1>
        <p>固定 SO101 工位装货，FishBot 运输到交付点。</p>
      </div>
      <div className="cooperation-header-actions">
        <button type="button" className="cooperation-button cooperation-quiet" onClick={onRefresh}><RefreshCw size={16} aria-hidden="true" />读取最新反馈</button>
        <button type="button" className="cooperation-button cooperation-quiet" onClick={onBack}><ArrowLeft size={16} aria-hidden="true" />返回控制台</button>
      </div>
    </header>

    <div className={`cooperation-readiness ${ready ? 'cooperation-ready' : ''}`} role="status">
      <span aria-hidden="true" /><strong>{ready ? '共享场景已就绪' : connected ? '暂不能开始' : '等待协同服务'}</strong>
      <p>{connectionError ?? (!connected && state ? '状态已过期，正在读取最新反馈。' : state?.reason ?? '正在连接共享场景与导航服务。')}</p>
    </div>
    {actionError && <div className="cooperation-error" role="alert">{actionError}</div>}
    {receipt && <div className="cooperation-receipt" role="status">
      <strong>{receipt.unknown ? '操作回执未知' : '已收到操作回执，正在核对任务状态'}</strong>
      <p>只读取任务 {receipt.taskId}。{receipt.action === 'cancel' ? '等待原任务取消或结束的反馈。' : '等待原任务接收或结束的反馈。'}</p>
    </div>}

    <div className="cooperation-layout">
      <section className="cooperation-scene" aria-labelledby="cooperation-camera-heading">
        <div className="cooperation-section-heading">
          <div><h2 id="cooperation-camera-heading">共享场景相机</h2><p>小车、机械臂与自由货物处于同一个物理场景。</p></div>
          <span className={`cooperation-camera-status ${frameLive ? 'cooperation-camera-live' : ''}`}><Camera size={14} aria-hidden="true" />{frameLabel}</span>
        </div>
        <div className={`cooperation-camera ${frameLive ? '' : 'cooperation-camera-unavailable'}`} data-frame-live={frameLive}>
          {imageSrc ? <>
            <img src={imageSrc} alt="共享 MuJoCo 场景的实际相机画面" />
            {!frameLive && <div className="cooperation-camera-notice"><Camera size={24} aria-hidden="true" /><span>{frameLabel}</span></div>}
          </> : <div className="cooperation-camera-empty"><Camera size={34} aria-hidden="true" /><strong>等待实际相机画面</strong><p>相机帧就绪后将在这里显示。</p></div>}
        </div>
        <div className="cooperation-camera-footer">
          <span>相机仿真时间 {frameMatchesSource && frame?.loadedStamp !== null ? `${frame.loadedStamp.toFixed(3)} s` : '未收到'}</span>
          <span>物理反馈 {physics ? `${physics.stamp.toFixed(3)} s` : '未收到'}</span>
          <span>{connected ? '状态每秒读取' : '当前显示为历史反馈'}</span>
        </div>
        <div className="cooperation-process">
          <h2>装货运输流程</h2>
          <ol>{COOPERATION_STAGES.map((stage, index) => <li key={stage.key} aria-current={stage.key === task?.stage ? 'step' : undefined}>
            <span>{index + 1}</span><strong>{stage.label}</strong>
          </li>)}</ol>
          <p>当前阶段：<strong>{stageLabel}</strong>。阶段由协同服务的实际反馈更新。</p>
          <p>近距离精停靠使用理想化仿真信标；未接入视觉识别。</p>
        </div>
      </section>

      <aside className="cooperation-sidebar">
        <section className="cooperation-task" aria-labelledby="cooperation-task-heading">
          <div className="cooperation-section-heading"><h2 id="cooperation-task-heading">装货运输任务</h2><Truck size={20} aria-hidden="true" /></div>
          <div className={`cooperation-task-state cooperation-task-${task?.status ?? 'idle'}`} role="status">
            <strong>{pending === 'start' ? '正在派发任务' : pending === 'cancel' ? '正在发送取消' : cooperationStatusLabel(task?.status)}</strong>
            <p>{task?.message || '开始后，小车先驶向固定 SO101 工位。'}</p>
            {task?.id && <small>任务 {task.id}</small>}
          </div>
          {task?.stop_reason && <p className="cooperation-stop-reason">停止原因：{task.stop_reason}</p>}
          <div className="cooperation-task-actions">
            <button type="button" className="cooperation-button cooperation-primary" disabled={!canStart} onClick={onStart} title={startReason}><Play size={16} aria-hidden="true" />开始装货运输</button>
            <button type="button" className="cooperation-button cooperation-cancel" disabled={!canCancel} onClick={onCancel}><Square size={15} aria-hidden="true" />取消当前任务</button>
          </div>
          <p className="cooperation-action-help">{startReason}</p>
          {task?.status === 'running' && snapshot.ownedTaskId !== task.id && <p className="cooperation-action-help">当前任务由另一页面发起。这里只读取反馈。</p>}
          <div className="cooperation-stations">
            <div><MapPin size={15} aria-hidden="true" /><span>固定工位</span><strong>{state?.stations ? `${metric(state.stations.dock.x, 2)}, ${metric(state.stations.dock.y, 2)} m` : '等待坐标'}</strong></div>
            <div><CircleCheck size={15} aria-hidden="true" /><span>交付点</span><strong>{state?.stations ? `${metric(state.stations.delivery.x, 2)}, ${metric(state.stations.delivery.y, 2)} m` : '等待坐标'}</strong></div>
          </div>
        </section>
        <section className="cooperation-dialogue" aria-labelledby="cooperation-dialogue-heading">
          <div className="cooperation-section-heading"><div><h2 id="cooperation-dialogue-heading">合作对话</h2><p>每条消息来自实际动作反馈。</p></div><span>{events.length} 条</span></div>
          {events.length ? <ol>{events.map((event) => <li key={event.sequence} className={`cooperation-event-${event.role}`}>
            <div><strong>{{ car: 'FishBot', arm: 'SO101', system: '协同服务' }[event.role]}</strong><time>{event.time_s.toFixed(2)} s</time></div>
            <p>{event.message}</p>
          </li>)}</ol> : <div className="cooperation-dialogue-empty"><p>尚未收到合作消息。</p><span>开始任务后，这里记录小车和机械臂的实际回应。</span></div>}
        </section>
      </aside>
    </div>

    <section className="cooperation-telemetry" aria-label="实际物理反馈" data-current={connected}>
      <div>
        <h2><Truck size={19} aria-hidden="true" />小车定位与运动</h2>
        <strong className="cooperation-telemetry-status">{physics ? carStopped ? '当前速度低于停稳阈值' : '当前小车有运动' : '等待小车反馈'}</strong>
        <dl><div><dt>物理位置</dt><dd>{physics ? `${metric(physics.car.x)}, ${metric(physics.car.y)} m` : '未收到'}</dd></div>
          <div><dt>物理朝向</dt><dd>{physics ? `${metric(physics.car.yaw * 180 / Math.PI, 1)}°` : '未收到'}</dd></div>
          <div><dt>线速度</dt><dd>{physics ? `${metric(physics.car.linear_speed)} m/s` : '未收到'}</dd></div>
          <div><dt>角速度</dt><dd>{physics ? `${metric(physics.car.angular_speed)} rad/s` : '未收到'}</dd></div>
          <div><dt>导航定位</dt><dd>{state?.nav?.pose ? `${metric(state.nav.pose.x)}, ${metric(state.nav.pose.y)} m` : '未收到'}</dd></div>
          <div><dt>Nav2</dt><dd>{state?.nav ? state.nav.ready ? '已就绪' : '未就绪' : '未收到'}</dd></div></dl>
      </div>
      <div>
        <h2><svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M4 21h13M7 21v-6l6-5-3-6 3-2 5 8-6 7v4M18 10l3 3-3 3" /><circle cx="13" cy="10" r="2" /></svg>SO101 机械臂</h2>
        <strong className="cooperation-telemetry-status">{armPhase}</strong>
        <dl><div><dt>关节数量</dt><dd>{physics ? physics.arm.q.length : '未收到'}</dd></div>
          <div><dt>最大关节速度</dt><dd>{physics && physics.arm.velocity.length ? `${metric(Math.max(...physics.arm.velocity.map(Math.abs)))} rad/s` : '未收到'}</dd></div>
          <div className="cooperation-joints"><dt>实际关节角度</dt><dd>{physics && physics.arm.q.length ? physics.arm.q.map((value) => `${(value * 180 / Math.PI).toFixed(1)}°`).join(' / ') : '未收到'}</dd></div></dl>
        <p>只有机械臂退出与货物放稳均确认后，小车才能出发。</p>
      </div>
      <div>
        <h2><Box size={19} aria-hidden="true" />自由货物</h2>
        <strong className="cooperation-telemetry-status">{physics ? physics.cargo.tray_contact ? '检测到托盘接触' : '当前无托盘接触' : '等待货物反馈'}</strong>
        <dl><div><dt>位置</dt><dd>{physics ? `${metric(physics.cargo.x)}, ${metric(physics.cargo.y)} m` : '未收到'}</dd></div>
          <div><dt>高度</dt><dd>{physics ? `${metric(physics.cargo.z)} m` : '未收到'}</dd></div>
          <div><dt>速度</dt><dd>{physics ? `${metric(physics.cargo.speed)} m/s` : '未收到'}</dd></div>
          <div><dt>夹指接触力</dt><dd>{physics ? `${physics.cargo.tip_forces.map((value) => value.toFixed(2)).join(' / ') || '未收到'} N` : '未收到'}</dd></div></dl>
        <p>货物位置与接触来自物理反馈。</p>
      </div>
    </section>
    <footer className="cooperation-source"><span>仅用于仿真</span><span>场景来源 SHA：{state?.source?.scene_sha || '等待服务发布'}</span></footer>
  </main>
}
